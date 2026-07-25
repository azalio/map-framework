"""Offload large tool-result bodies before context compaction.

MAP's compaction is a *soft nudge*: when the token budget is crossed the
framework asks the assistant (Claude Code) or the operator (Codex) to run the
harness ``/compact`` command, and the harness drops old/large tool-result
bodies (grep output, test logs, whole-file reads) to stay within the context
window. Once dropped, the only way to recover such an output is to re-run the
tool — i.e. redo the broad discovery the workflow already paid for.

This module captures those bodies *before* a compaction drops them and writes
each one, at full resolution, to a retrievable sidecar under
``.map/<branch>/compacted/``. An agent that needs a dropped output later reads
the sidecar instead of re-running the tool.

Design notes (see GitHub issue #232 and ``docs/context-compression-plan.md``):

- **Single source of truth.** This is plain ``mapify_cli`` runtime code (like
  ``token_budget.py``). The PreCompact hook and the Codex orchestrator both
  call it via a lazy import that degrades to a silent no-op when ``mapify_cli``
  is not importable — so there is no hand-duplicated copy to drift.
- **Pre-drop capture point.** The PreCompact hook fires before the harness
  compacts and the transcript still holds the full bodies; the Codex
  orchestrator captures at the same budget-warning point. The transcript JSONL
  stores tool-result bodies as UTF-8 text, so no binary handling is needed.
- **Gating.** The caller is responsible for checking ``compression_policy`` and
  only invoking this module when the policy is not ``never`` — so a default
  (``never``) install never creates ``.map/<branch>/compacted/`` at all.
- **Security.** Tool outputs can contain secrets, so every sidecar is written
  ``0o600`` and a ``.gitignore`` containing ``*`` is dropped into the directory
  on creation; the bodies are never redacted (a partial scrubber gives false
  confidence). See ``docs/USAGE.md`` for the operator warning.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Index schema version — bump if the ndjson record shape changes so old
# manifests can be detected and rebuilt rather than mis-parsed.
INDEX_SCHEMA_VERSION = 1

# Selection thresholds (characters). A body this large is worth recovering for
# any tool; below ``DISCOVERY_MIN`` we only bother for broad-discovery tools.
LARGE_ANY_CHARS = 10_000
DISCOVERY_MIN_CHARS = 2_000

# Tools whose output is broad discovery — expensive to re-run, cheap to keep.
BROAD_DISCOVERY_TOOLS = frozenset({"Bash", "Read", "Grep", "Glob"})

# Tools whose output is never worth a sidecar (tiny, ephemeral, or interactive).
DENYLIST_TOOLS = frozenset({"TodoWrite", "AskUserQuestion", "ExitPlanMode"})

# Directory-growth caps. Eviction is FIFO (oldest offload first). Generous
# enough to hold a long workflow's discovery, bounded enough to never balloon
# ``.map/``.
DEFAULT_MAX_FILES = 300
DEFAULT_MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 MiB

_COMPACTED_DIRNAME = "compacted"
_INDEX_NAME = "index.ndjson"
_MANIFEST_NAME = "MANIFEST.md"
_EVICTIONS_LOG = ".evictions.log"
_ERRORS_LOG = ".errors.log"

# Strip C0 control characters (except nothing — newlines/tabs are flattened to
# spaces first) so a one-line input summary stays jq-/markdown-safe. Mirrors the
# sanitisation rule used elsewhere in the framework.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class ToolOutput:
    """A single tool-result body extracted from a transcript."""

    tool_use_id: str
    tool_name: str
    input_summary: str
    body: str

    @property
    def byte_len(self) -> int:
        return len(self.body.encode("utf-8", "replace"))


@dataclass
class OffloadSummary:
    """Result of an offload pass — what was written / skipped / evicted."""

    written: int = 0
    skipped_existing: int = 0
    evicted: int = 0
    errors: int = 0
    compacted_dir: Path | None = None
    written_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sanitize_summary(text: str, limit: int = 200) -> str:
    """Collapse whitespace, strip control chars, bound length — one safe line."""
    flat = text.replace("\r\n", "\n").replace("\r", "\n")
    flat = flat.replace("\n", " ").replace("\t", " ")
    flat = _CONTROL_CHARS.sub("", flat)
    flat = " ".join(flat.split())
    if len(flat) > limit:
        return flat[: max(0, limit - 1)].rstrip() + "…"
    return flat


def _summarize_input(tool_input: object) -> str:
    """Human-readable one-liner describing what the tool was asked to do."""
    if not isinstance(tool_input, dict):
        return _sanitize_summary(str(tool_input))
    # Prefer the field that identifies the work for common tools.
    for key in ("command", "file_path", "pattern", "path", "query", "url"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return _sanitize_summary(value)
    try:
        return _sanitize_summary(json.dumps(tool_input, ensure_ascii=False))
    except (TypeError, ValueError):
        return _sanitize_summary(str(tool_input))


def _result_body_to_text(content: object) -> str:
    """Flatten a ``tool_result`` ``content`` field to a single text body."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text", "")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def extract_tool_outputs(transcript_path: Path) -> list[ToolOutput]:
    """Parse a Claude Code transcript JSONL into a list of tool-result bodies.

    Walks the transcript once, mapping each ``tool_use`` id to its tool name and
    input, then pairs every ``tool_result`` block with that metadata via its
    ``tool_use_id``. Malformed lines are skipped, never fatal. Returns outputs
    in transcript order; later duplicates of the same ``tool_use_id`` are
    ignored (the first body wins).
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.is_file():
        return []
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("tool_output_offload: cannot read %s: %s", transcript_path, exc)
        return []

    meta: dict[str, tuple[str, str]] = {}  # tool_use_id -> (name, input_summary)
    results: dict[str, str] = {}  # tool_use_id -> body (first wins)
    order: list[str] = []

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None

        # tool_result entries sometimes appear at the top level rather than
        # nested in a user message; normalise both into one content list.
        blocks: list[object] = []
        if isinstance(content, list):
            blocks.extend(content)
        if entry.get("type") == "tool_result":
            blocks.append(entry)

        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tid = block.get("id")
                if isinstance(tid, str) and tid:
                    name = block.get("name")
                    name = name if isinstance(name, str) and name else "unknown"
                    meta[tid] = (name, _summarize_input(block.get("input")))
            elif btype == "tool_result":
                tid = block.get("tool_use_id")
                if isinstance(tid, str) and tid and tid not in results:
                    body = _result_body_to_text(block.get("content", ""))
                    results[tid] = body
                    order.append(tid)

    outputs: list[ToolOutput] = []
    for tid in order:
        name, summary = meta.get(tid, ("unknown", ""))
        outputs.append(
            ToolOutput(
                tool_use_id=tid,
                tool_name=name,
                input_summary=summary,
                body=results[tid],
            )
        )
    return outputs


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def should_offload(tool_name: str, body_len: int) -> bool:
    """Return True if a tool-result body is worth offloading.

    Size-based, not age-based: the hook cannot know which bodies the harness
    will actually drop, so it captures every body large enough to be worth
    recovering and lets the FIFO cap bound disk use.
    """
    if tool_name in DENYLIST_TOOLS:
        return False
    if body_len >= LARGE_ANY_CHARS:
        return True
    return bool(body_len >= DISCOVERY_MIN_CHARS and tool_name in BROAD_DISCOVERY_TOOLS)


# ---------------------------------------------------------------------------
# Sidecar / index IO
# ---------------------------------------------------------------------------


def _sidecar_filename(output: ToolOutput) -> str:
    safe_tool = _UNSAFE_FILENAME.sub("", output.tool_name) or "tool"
    safe_id = _UNSAFE_FILENAME.sub("", output.tool_use_id)[:48] or "noid"
    return f"{safe_tool}-{safe_id}.txt"


def _sidecar_text(output: ToolOutput, saved_at: str) -> str:
    """Full body prefixed with a self-describing header (survives standalone)."""
    return (
        f"# map:offloaded tool_use_id={output.tool_use_id} "
        f"tool={output.tool_name} bytes={output.byte_len} saved={saved_at}\n"
        f"# input: {output.input_summary}\n"
        "# Authority: point-in-time snapshot; live source/tests/schemas win "
        "for current truth.\n"
        "# --- body below ---\n"
        f"{output.body}"
    )


def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def _ensure_compacted_dir(branch_dir: Path) -> Path:
    """Create ``compacted/`` (0700) with a self-contained ``.gitignore``.

    The shipped repo-root ``.gitignore`` does not cover this path, and tool
    outputs may contain secrets, so the directory ignores its own contents
    regardless of how the host repo's ignore rules are configured.
    """
    compacted = branch_dir / _COMPACTED_DIRNAME
    compacted.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(compacted, 0o700)
    except OSError:
        pass
    gitignore = compacted / ".gitignore"
    if not gitignore.exists():
        try:
            gitignore.write_text(
                "# map: offloaded tool outputs may contain secrets — never commit\n"
                "*\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return compacted


def _read_index(compacted: Path) -> list[dict]:
    index = compacted / _INDEX_NAME
    if not index.is_file():
        return []
    records: list[dict] = []
    try:
        for raw in index.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("tool_use_id"):
                records.append(rec)
    except (OSError, UnicodeDecodeError):
        return []
    return records


def _append_index(compacted: Path, record: dict) -> None:
    index = compacted / _INDEX_NAME
    line = json.dumps(record, ensure_ascii=False)
    with index.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    try:
        os.chmod(index, 0o600)
    except OSError:
        pass


def _log_line(compacted: Path, name: str, message: str) -> None:
    try:
        with (compacted / name).open("a", encoding="utf-8") as fh:
            fh.write(f"{_now_iso()} {message}\n")
    except OSError:
        pass


def _rewrite_index(compacted: Path, records: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    _atomic_write(compacted / _INDEX_NAME, text, mode=0o600)


def _enforce_cap(
    compacted: Path, *, max_files: int, max_total_bytes: int
) -> int:
    """Evict oldest sidecars until under both caps. Returns evicted count."""
    records = _read_index(compacted)
    evicted = 0

    def total_bytes(recs: list[dict]) -> int:
        return sum(int(r.get("bytes", 0) or 0) for r in recs)

    while records and (
        len(records) > max_files or total_bytes(records) > max_total_bytes
    ):
        victim = records.pop(0)  # FIFO: oldest first
        sidecar = victim.get("sidecar")
        if isinstance(sidecar, str):
            try:
                (compacted / sidecar).unlink(missing_ok=True)
            except OSError:
                pass
        _log_line(
            compacted,
            _EVICTIONS_LOG,
            f"evicted {victim.get('sidecar')} "
            f"(tool={victim.get('tool')} bytes={victim.get('bytes')})",
        )
        evicted += 1

    if evicted:
        _rewrite_index(compacted, records)
    return evicted


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest(compacted: Path) -> Path | None:
    """(Re)build the agent-readable ``MANIFEST.md`` from ``index.ndjson``.

    Returns the manifest path, or ``None`` if there is nothing to index.
    """
    records = _read_index(compacted)
    if not records:
        return None
    lines = [
        "# Offloaded tool outputs",
        "",
        ("Large tool-result bodies saved before context compaction so you can "
        "recover them **without re-running broad discovery** (re-grep, re-read, "
        "re-test). Read the sidecar file directly."),
        "",
        ("> Authority: these are point-in-time snapshots from when the tool ran. "
        "For any question about *current* truth, live source, tests, and "
        "schemas win."),
        "",
        "| tool | input | bytes | saved | sidecar |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rec in records:
        tool = str(rec.get("tool", "")).replace("|", "\\|")
        summary = str(rec.get("input_summary", "")).replace("|", "\\|")
        size = int(rec.get("bytes", 0) or 0)
        saved = str(rec.get("saved_at", ""))
        sidecar = str(rec.get("sidecar", ""))
        lines.append(
            f"| {tool} | {summary} | {size:,} | {saved} | {sidecar} |"
        )
    manifest = compacted / _MANIFEST_NAME
    _atomic_write(manifest, "\n".join(lines) + "\n", mode=0o600)
    return manifest


def recovery_pointer_text(branch: str, branch_dir: Path) -> str | None:
    """The additionalContext / stderr line pointing agents at the offloads.

    Returns ``None`` when nothing has been offloaded, so callers emit the
    pointer only when there is something to recover.
    """
    compacted = branch_dir / _COMPACTED_DIRNAME
    if not _read_index(compacted):
        return None
    return (
        f"Large tool outputs from before compaction were saved under "
        f".map/{branch}/{_COMPACTED_DIRNAME}/. See "
        f".map/{branch}/{_COMPACTED_DIRNAME}/{_MANIFEST_NAME} for a scannable "
        f"index, then read the specific sidecar instead of re-running broad "
        f"discovery (re-grep / re-read / re-test). Authority: live source, "
        f"tests, and schemas beat these snapshots for current truth."
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def offload_transcript_tool_outputs(
    transcript_path: Path,
    branch_dir: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> OffloadSummary:
    """Offload every qualifying tool-result body in *transcript_path*.

    Idempotent: a ``tool_use_id`` already present in the index is skipped, so
    repeated compactions in one run never duplicate or rewrite a sidecar. The
    ``compacted/`` directory is created only when there is at least one body to
    write, so a policy=auto session with no large outputs leaves no trace.

    Never raises on per-output IO problems — those are logged to
    ``.errors.log`` and counted; the caller still wraps the whole call
    defensively because a hook must not break compaction.
    """
    summary = OffloadSummary()
    outputs = extract_tool_outputs(transcript_path)
    candidates = [
        o for o in outputs if should_offload(o.tool_name, len(o.body))
    ]
    if not candidates:
        return summary

    compacted = _ensure_compacted_dir(branch_dir)
    summary.compacted_dir = compacted
    existing_ids = {r["tool_use_id"] for r in _read_index(compacted)}

    for output in candidates:
        if output.tool_use_id in existing_ids:
            summary.skipped_existing += 1
            continue
        saved_at = _now_iso()
        sidecar_name = _sidecar_filename(output)
        try:
            _atomic_write(
                compacted / sidecar_name,
                _sidecar_text(output, saved_at),
                mode=0o600,
            )
            _append_index(
                compacted,
                {
                    "schema_version": INDEX_SCHEMA_VERSION,
                    "tool_use_id": output.tool_use_id,
                    "tool": output.tool_name,
                    "input_summary": output.input_summary,
                    "bytes": output.byte_len,
                    "sidecar": sidecar_name,
                    "saved_at": saved_at,
                },
            )
        except OSError as exc:
            summary.errors += 1
            _log_line(
                compacted, _ERRORS_LOG, f"offload {output.tool_use_id} failed: {exc}"
            )
            continue
        existing_ids.add(output.tool_use_id)
        summary.written += 1
        summary.written_ids.append(output.tool_use_id)

    summary.evicted = _enforce_cap(
        compacted, max_files=max_files, max_total_bytes=max_total_bytes
    )
    build_manifest(compacted)
    return summary
