#!/usr/bin/env python3
"""
MAP Workflow Step Execution Utilities

Provides deterministic step executors for /map-efficient workflow.
These handle the mechanical parts of workflow steps that don't require LLM reasoning.

DESIGN PRINCIPLE:
  Separate deterministic operations (file I/O, state updates) from LLM work.
  Python handles the boring stuff, Claude focuses on creative problem-solving.

USAGE:
  Called by map-efficient.md command to handle:
  - State file updates
  - Plan file parsing/updates
  - Checkpoint validation
  - Progress tracking

FUNCTIONS:
  - update_step_state: Mark step complete in step_state.json
  - update_plan_status: Update subtask status in task_plan.md
  - validate_checkpoint: Check if required steps completed
  - create_xml_packet: Build AI-friendly subtask packet

TESTING:
  python3 -c "from map_step_runner import update_step_state; \\
    update_step_state('ST-001', 'actor', 'ACTOR_CALLED')"
"""

import ast
import fnmatch
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, TypedDict, cast

# Keep in sync with workflow-context-injector.py GOAL_HEADING_RE
GOAL_HEADING_RE = r"## (?:Goal|Overview)\n(.*?)(?=\n##|\Z)"

# check_plan_resume() goal-comparison thresholds (issue #164/#166). The resume
# preflight diverts a brand-new request to `goal_mismatch` (instead of falsely
# reporting "plan complete" / silently clobbering the prior plan) ONLY on strong
# evidence: both the existing goal and the incoming request must carry at least
# RESUME_MIN_TOKENS_FOR_MISMATCH significant tokens, and their containment (shared
# tokens / smaller significant-token set) must fall below
# RESUME_GOAL_MISMATCH_CONTAINMENT. Conservative by design so a legitimate resume
# with a shorter paraphrase is never falsely diverted.
RESUME_GOAL_MISMATCH_CONTAINMENT = 0.25
RESUME_MIN_TOKENS_FOR_MISMATCH = 2


HUMAN_ARTIFACT_DEFAULTS = {
    "qa-001.md": "# QA 001\n\n",
    "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Follow-up\n",
    "verification-summary.md": "# Verification Summary\n\n",
}


KNOWN_ISSUES_DEFAULT: dict[str, list[dict[str, object]]] = {"issues": []}
ACTIVE_ISSUES_DEFAULT: dict[str, object] = {"updated_at": "", "issues": []}
VALID_MINIMALITY_LEVELS = frozenset({"off", "lite", "full", "ultra"})
AGGRESSIVE_COMPRESSION_MULTIPLIER = 0.4


def _read_map_config_scalars(project_dir: Path) -> dict[str, str]:
    """Read top-level scalar values from .map/config.yaml without dependencies."""
    config_path = project_dir / ".map" / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            continue
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _map_config_str(project_dir: Path, key: str, default: str) -> str:
    value = _read_map_config_scalars(project_dir).get(key)
    return default if value is None else value


def _map_config_int(project_dir: Path, key: str, default: int) -> int:
    value = _read_map_config_scalars(project_dir).get(key)
    if value is None:
        return default
    try:
        parsed = int(value.replace("_", ""))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _extract_transcript_usage(entry: dict) -> Optional[int]:
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    entry_type = entry.get("type")
    if role != "assistant" and entry_type != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
    except (TypeError, ValueError):
        return None


def _count_last_turn_tokens(transcript_path: Path) -> int:
    if not transcript_path.is_file():
        return 0
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            usage = _extract_transcript_usage(entry)
            if usage is not None:
                return usage
    return 0


def _effective_compression_threshold(policy: str, threshold: int) -> Optional[int]:
    if policy == "never" or threshold <= 0:
        return None
    if policy == "aggressive":
        return max(1, int(threshold * AGGRESSIVE_COMPRESSION_MULTIPLIER))
    return threshold

GATE_VERDICTS = {"ready", "needs-revision", "blocked"}
ARTIFACT_STAGE_NAMES = (
    "workflow_fit",
    "spec",
    "plan",
    "test_contract",
    "implementation",
    "review",
    "verification",
    "retry_quarantine",
    "token_budget",
    "run_health",
    "learn_handoff",
)
RUN_HEALTH_TERMINAL_STATUSES = {
    "pending",
    "complete",
    "blocked",
    "won't_do",
    "superseded",
}
RUN_HEALTH_REQUIRED_KEYS = {
    "schema_version",
    "generated_at",
    "workflow",
    "branch",
    "terminal_status",
    "completed_step_count",
    "pending_step_count",
    "artifacts",
    "resiliency_signals",
}
RUN_HEALTH_ARTIFACT_KEYS = {
    "step_state",
    "artifact_manifest",
    "verification_summary",
    "qa",
    "pr_draft",
    "review_bundle",
    "learning_handoff",
    "task_plan",
    "blueprint",
    "active_issues",
    "known_issues",
}
RUN_HEALTH_SIGNAL_KEYS = {
    "hook_injection",
    "hook_injection_counts",
    "retry_count",
    "max_retries",
    "subtask_retry_counts",
    "max_subtask_retry_count",
    "guard_rework_counts",
    "predictor_called",
    "predictor_skipped",
    "final_verifier_executed",
}
PRIOR_STAGE_CONSUMPTION_STAGES = {"implementation", "review"}
WORKFLOW_FIT_ROUTES = {
    "direct-edit",
    "map-fast",
    "map-efficient",
    "map-tdd",
    "map-plan",
}
DIFF_SIZE_LEVELS = {"tiny", "small", "medium", "large"}
SUBTASK_CONCERN_TYPES = {
    "api",
    "config",
    "cross-repo",
    "data",
    "docs",
    "infra",
    "observability",
    "refactor",
    "release",
    "runtime",
    "security",
    "tests",
    "ui",
    "mixed",
}
LEARNING_CONSUMPTION_SOURCES = {"auto-handoff", "file-handoff", "inline-summary"}
REVIEW_SECTION_IDS: tuple[str, ...] = ("architecture", "code_quality", "tests", "performance")
REVIEW_VALID_MODES: tuple[str, ...] = ("default", "reverse-sections", "shuffle-sections")
LEARNING_IMMEDIATE_WINDOW_SECONDS = 30 * 60
ACCEPTANCE_TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*-\d+[A-Za-z0-9_-]*)\]")
REVIEW_PROMPT_DEFAULT_BUDGET_TOKENS = 12_000
REVIEW_PROMPT_MIN_BUDGET_TOKENS = 1_024
REVIEW_PROMPT_BUDGET_ENV = "MAP_REVIEW_PROMPT_BUDGET_TOKENS"
TOKEN_BUDGET_ARTIFACT_NAME = "token_budget.json"
TOKEN_BUDGET_DECISION_LIMIT = 100
RETRY_QUARANTINE_ARTIFACT_NAME = "retry_quarantine.json"

# Truncation infrastructure deleted by user directive ("убери транкейт уже
# вообще"). build_context_block / _budget_review_prompt now emit raw text;
# operators handle context size via /compact opt-in. The mapify_cli
# token_budget module is no longer imported here — review-prompt budget
# constants remain only because record_token_budget_decision is still
# exposed for callers that want their own accounting.

LEARNING_METRICS_COUNTER_DEFAULTS = {
    "handoff_generated_count": 0,
    "handoff_consumed_count": 0,
    "immediate_learn_count": 0,
    "deferred_learn_count": 0,
    "never_used_handoff_count": 0,
    "manual_summary_count": 0,
    "pending_handoff_count": 0,
    "repeated_violation_scan_count": 0,
    "repeated_violation_match_count": 0,
}
LEARNING_MATCH_STOPWORDS = {
    "after",
    "always",
    "before",
    "branch",
    "because",
    "between",
    "could",
    "failed",
    "failure",
    "false",
    "file",
    "files",
    "from",
    "have",
    "into",
    "issue",
    "just",
    "later",
    "must",
    "needs",
    "none",
    "only",
    "path",
    "paths",
    "return",
    "should",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "this",
    "true",
    "when",
    "with",
    "workflow",
}
LEARNED_RULE_BULLET_RE = re.compile(
    r"^- \*\*(?P<title>.+?)\*\* \((?P<date>\d{4}-\d{2}-\d{2})\): (?P<body>.+?)(?: \[workflow: .+?\])?$"
)
SECTION_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")

# Module-level singleton kept for in-process pytest paths only. The durable staging
# path is the file ``.map/<branch>/pending-ordering.json`` — see
# record_review_ordering() / create_review_bundle() — because the SKILL.md workflow
# calls them across separate ``python3 ...`` subprocesses, and a module-level dict
# evaporates between processes. The in-memory singleton supplements the file for
# tests that mutate it directly with ``map_step_runner._PENDING_REVIEW_ORDERING = ...``.
_PENDING_REVIEW_ORDERING: dict[str, object] | None = None

PENDING_ORDERING_FILENAME = "pending-ordering.json"
PATH_HINT_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)(?::\d+)?"
)
TOKEN_RE = re.compile(r"[a-z0-9]{4,}")


def _utc_timestamp() -> str:
    """Return an unambiguous RFC3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_boolish(value: object) -> bool:
    """Convert common truthy/falsy string forms to bool."""
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y"}


def _shorten_retry_text(text: str, max_chars: int = 1_200) -> str:
    compact = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 15].rstrip() + "\n[truncated]"


def _is_non_negative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _write_json_file(path: Path, payload: dict) -> None:
    """Atomically write JSON payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    tmp_file.replace(path)


def _read_json_file(path: Path) -> Optional[dict[str, object]]:
    """Read a JSON object from disk, returning None on invalid or missing files."""
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def artifact_manifest_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped artifact manifest path."""
    return get_branch_dir(branch) / "artifact_manifest.json"


def learning_metrics_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped learning metrics path."""
    return get_branch_dir(branch) / "learning-metrics.json"


def _default_stage_payload() -> dict[str, object]:
    """Return an empty stage payload for artifact_manifest.json."""
    return {
        "status": "not_started",
        "updated_at": "",
        "artifacts": [],
        "metadata": {},
    }


def default_artifact_manifest(branch: str) -> dict[str, object]:
    """Return a fresh artifact manifest for a branch."""
    return {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "stages": {stage: _default_stage_payload() for stage in ARTIFACT_STAGE_NAMES},
    }


def load_artifact_manifest(branch: Optional[str] = None) -> dict[str, object]:
    """Load artifact_manifest.json, filling missing stages with defaults."""
    branch_name = branch or get_branch_name()
    manifest_path = artifact_manifest_path(branch_name)
    manifest = default_artifact_manifest(branch_name)

    if not manifest_path.exists():
        return manifest

    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return manifest

    if isinstance(loaded, dict):
        manifest.update(
            {
                "schema_version": loaded.get("schema_version", manifest["schema_version"]),
                "branch": branch_name,
                "updated_at": loaded.get("updated_at", manifest["updated_at"]),
            }
        )
        loaded_stages = loaded.get("stages", {})
        if isinstance(loaded_stages, dict):
            stages = cast(dict[str, dict[str, object]], manifest["stages"])
            for stage in ARTIFACT_STAGE_NAMES:
                stage_payload = loaded_stages.get(stage, _default_stage_payload())
                if isinstance(stage_payload, dict):
                    stages[stage] = {
                        "status": stage_payload.get("status", "not_started"),
                        "updated_at": stage_payload.get("updated_at", ""),
                        "artifacts": stage_payload.get("artifacts", []),
                        "metadata": stage_payload.get("metadata", {}),
                    }

    return manifest


def save_artifact_manifest(
    manifest: dict[str, object], branch: Optional[str] = None
) -> dict[str, object]:
    """Persist artifact_manifest.json and return status metadata."""
    branch_name = branch or get_branch_name()
    manifest["branch"] = branch_name
    manifest["updated_at"] = _utc_timestamp()
    path = artifact_manifest_path(branch_name)
    _write_json_file(path, manifest)
    return {"status": "success", "path": str(path), "manifest": manifest}


def _set_manifest_stage(
    manifest: dict[str, object],
    stage: str,
    status: str,
    *,
    artifacts: Optional[list[dict[str, str]]] = None,
    metadata: Optional[dict[str, object]] = None,
) -> None:
    """Update one stage entry inside a manifest payload."""
    if stage not in ARTIFACT_STAGE_NAMES:
        raise ValueError(f"Unknown artifact stage: {stage}")
    stages = manifest.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("artifact manifest stages payload is invalid")
    stages[stage] = {
        "status": status,
        "updated_at": _utc_timestamp(),
        "artifacts": artifacts or [],
        "metadata": metadata or {},
    }


def _artifact_ref(path: Path, kind: str) -> dict[str, str]:
    """Create a manifest artifact reference payload."""
    return {"path": str(path), "kind": kind}


def token_budget_artifact_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped prompt budget decision artifact path."""
    return get_branch_dir(branch) / TOKEN_BUDGET_ARTIFACT_NAME


def _default_token_budget_artifact(branch: str) -> dict[str, object]:
    """Return an empty token budget artifact payload."""
    return {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "decisions": [],
    }


def _normalize_token_budget_artifact_refs(
    artifact_references: Optional[list[Mapping[str, object]]],
) -> list[dict[str, str]]:
    """Keep artifact references compact and schema-friendly."""
    refs: list[dict[str, str]] = []
    for ref in artifact_references or []:
        path = str(ref.get("path") or "").strip()
        kind = str(ref.get("kind") or "artifact").strip() or "artifact"
        if path:
            refs.append({"path": path, "kind": kind})
    return refs


def record_token_budget_decision(
    path_name: str,
    configured_budget_tokens: int,
    estimated_tokens_before: int,
    estimated_tokens_after: int,
    clipped_sections: Optional[list[str]] = None,
    budget_action: str = "none",
    artifact_references: Optional[list[Mapping[str, object]]] = None,
    metadata: Optional[dict[str, object]] = None,
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Append one active prompt-path budget decision to token_budget.json."""
    branch_name = branch or get_branch_name()
    artifact_path = token_budget_artifact_path(branch_name)
    try:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        payload = _default_token_budget_artifact(branch_name)
        existing = _read_json_file(artifact_path)
        if existing:
            payload.update(
                {
                    "schema_version": existing.get(
                        "schema_version", payload["schema_version"]
                    ),
                    "branch": branch_name,
                }
            )
            existing_decisions = existing.get("decisions")
            if isinstance(existing_decisions, list):
                payload["decisions"] = [
                    item for item in existing_decisions if isinstance(item, dict)
                ][-TOKEN_BUDGET_DECISION_LIMIT:]

        decision: dict[str, object] = {
            "recorded_at": _utc_timestamp(),
            "path_name": path_name,
            "configured_budget_tokens": max(0, int(configured_budget_tokens or 0)),
            "estimated_tokens_before": max(0, int(estimated_tokens_before or 0)),
            "estimated_tokens_after": max(0, int(estimated_tokens_after or 0)),
            "budget_action": budget_action or "none",
            "clipped_sections": list(clipped_sections or []),
            "artifact_references": _normalize_token_budget_artifact_refs(
                artifact_references
            ),
        }
        if metadata:
            decision["metadata"] = metadata

        decisions = cast(list[dict[str, object]], payload.setdefault("decisions", []))
        decisions.append(decision)
        del decisions[:-TOKEN_BUDGET_DECISION_LIMIT]
        payload["updated_at"] = _utc_timestamp()
        _write_json_file(artifact_path, payload)

        manifest = load_artifact_manifest(branch_name)
        _set_manifest_stage(
            manifest,
            "token_budget",
            "ready",
            artifacts=[_artifact_ref(artifact_path, "token-budget-report")],
            metadata={
                "last_path_name": path_name,
                "last_budget_action": decision["budget_action"],
                "decision_count": len(decisions),
            },
        )
        manifest_result = save_artifact_manifest(manifest, branch_name)
        return {
            "status": "success",
            "path": str(artifact_path),
            "decision": decision,
            "manifest_path": manifest_result["path"],
        }
    except Exception as exc:
        return {"status": "error", "path": str(artifact_path), "reason": str(exc)}


# ---------------------------------------------------------------------------
# Per-subtask token accounting (input / output / cache).
#
# Distinct from record_token_budget_decision above (which logs prompt-PATH
# budget decisions). This block reads the Claude Code transcript's per-turn
# ``usage`` block and attributes input/output/cache tokens to the active
# subtask/phase/agent so a run produces token_accounting.json with cost and
# cache-hit-ratio rollups. Self-contained on stdlib (no mapify_cli import) so
# the shipped .map/scripts/ copy works in generated projects where the
# mapify_cli package is absent.
# ---------------------------------------------------------------------------

TOKEN_LOG_NAME = "token_log.jsonl"
TOKEN_ACCOUNTING_NAME = "token_accounting.json"
TOKEN_METER_CACHE_NAME = ".token-meter-cache.json"
_SEEN_ID_CACHE_LIMIT = 5000

_TOKEN_FIELDS = ("input", "output", "cache_creation", "cache_read")

# Price per 1M tokens (USD). Update as provider pricing changes; an unknown
# model falls back to the default entry so cost stays an estimate, never a
# crash. cache_creation is the ~1.25x write multiplier and cache_read the
# ~0.1x hit multiplier of the input price.
MODEL_TOKEN_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0, "cache_creation": 18.75, "cache_read": 1.5},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_creation": 18.75, "cache_read": 1.5},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.3},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.3},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_creation": 1.25, "cache_read": 0.1},
}
_DEFAULT_PRICE_MODEL = "claude-opus-4-7"

# step_state phase -> MAP agent name. Claude Code does not put subagent_type on
# the hook stdin, so attribution falls back to the active phase.
_PHASE_TO_AGENT = {
    "DECOMPOSE": "task-decomposer",
    "RESEARCH": "research-agent",
    "ACTOR": "actor",
    "MONITOR": "monitor",
    "PREDICT": "predictor",
}


def _model_price(model: str) -> dict[str, float]:
    """Resolve a price row for a model id, tolerating real-world id shapes.

    Transcript model ids carry a date suffix on some models but not others
    (e.g. ``claude-haiku-4-5-20251001`` vs ``claude-opus-4-7``). Match in
    order: exact key, then the id with a trailing ``-YYYYMMDD`` stripped, then
    a known key that prefixes the id; finally the default. Without this a
    date-suffixed haiku id would silently fall back to Opus pricing (~15x the
    real cost).
    """
    if model in MODEL_TOKEN_PRICES:
        return MODEL_TOKEN_PRICES[model]
    stripped = re.sub(r"-\d{8}$", "", model)
    if stripped in MODEL_TOKEN_PRICES:
        return MODEL_TOKEN_PRICES[stripped]
    for known in MODEL_TOKEN_PRICES:
        if model.startswith(known):
            return MODEL_TOKEN_PRICES[known]
    return MODEL_TOKEN_PRICES[_DEFAULT_PRICE_MODEL]


def _token_cost(usage: Mapping[str, int], model: str) -> float:
    """Best-effort USD cost for one usage record under the model's price."""
    price = _model_price(model)
    total = 0.0
    for field in _TOKEN_FIELDS:
        total += usage.get(field, 0) / 1_000_000 * price.get(field, 0.0)
    return round(total, 6)


def _extract_turn_usage(entry: object) -> Optional[dict[str, object]]:
    """Pull one assistant turn's full usage from a transcript JSONL entry.

    Returns a flat dict (input/output/cache_creation/cache_read as ints, plus
    ``model`` and a stable ``msg_id`` for dedup), or None when the entry is not
    an assistant message carrying a ``usage`` block.
    """
    if not isinstance(entry, dict):
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    if message.get("role") != "assistant" and entry.get("type") != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    def _int(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    msg_id = message.get("id") or entry.get("uuid") or ""
    return {
        "input": _int("input_tokens"),
        "output": _int("output_tokens"),
        "cache_creation": _int("cache_creation_input_tokens"),
        "cache_read": _int("cache_read_input_tokens"),
        "model": str(message.get("model") or ""),
        "msg_id": str(msg_id),
    }


def _coerce_token_int(value: object) -> int:
    """Best-effort int from a token field that may be int / float / str / None."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _usage_token_total(usage: Mapping[str, object]) -> int:
    """Sum of the four token fields for one usage record.

    Used to pick the most complete copy of a turn when the transcript repeats a
    msg_id with diverging usage (a streaming partial vs the final line).
    """
    return sum(_coerce_token_int(usage.get(field, 0)) for field in _TOKEN_FIELDS)


def _iter_new_usage(
    transcript_path: Path, seen_ids: set[str], start_offset: int = 0
) -> tuple[list[dict[str, object]], int]:
    """New assistant-usage dicts from a transcript, read incrementally.

    Reads only the bytes after ``start_offset`` (transcripts are append-only
    JSONL) so a repeatedly-firing Stop/SubagentStop hook does not re-parse the
    whole multi-MB file each turn. Returns ``(usages, new_offset)`` where
    ``new_offset`` advances only past the last COMPLETE line — a partial line
    from a concurrent append is left for the next call.

    A single assistant turn is written to the transcript as SEVERAL JSONL lines
    (one per content / tool_use block) that all share the same ``message.id``
    and the same cumulative ``usage``. Results are deduped by msg_id WITHIN this
    read window — keeping the copy with the most total tokens — so a turn's
    usage is logged exactly once; without it est_cost roughly doubles. The
    persisted ``seen_ids`` is the cross-call safety net (e.g. if the file is
    rotated and the offset resets, or a turn straddles two windows). Entries
    with an empty msg_id or malformed JSON are skipped; a missing/unreadable
    transcript returns ``([], start_offset)``.
    """
    path = Path(transcript_path)
    try:
        if not path.is_file():
            return [], start_offset
        size = path.stat().st_size
    except OSError:
        return [], start_offset
    # A stored offset past EOF means the file was truncated/rotated — restart.
    offset = start_offset if 0 <= start_offset <= size else 0
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], start_offset

    last_newline = chunk.rfind(b"\n")
    if last_newline == -1:
        # No complete line yet beyond the offset.
        return [], offset
    complete = chunk[: last_newline + 1]
    new_offset = offset + len(complete)

    by_mid: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for raw in complete.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        usage = _extract_turn_usage(entry)
        if usage is None:
            continue
        mid = str(usage["msg_id"])
        if not mid or mid in seen_ids:
            continue
        prev = by_mid.get(mid)
        if prev is None:
            order.append(mid)
            by_mid[mid] = usage
        elif _usage_token_total(usage) > _usage_token_total(prev):
            # Same turn repeated in this window — keep the most complete copy.
            by_mid[mid] = usage
    return [by_mid[mid] for mid in order], new_offset


def _token_meter_cache_path(branch_name: str) -> Path:
    return get_branch_dir(branch_name) / TOKEN_METER_CACHE_NAME


def _load_meter_cache(branch_name: str) -> tuple[dict[str, int], set[str]]:
    """Return (per-transcript byte offsets, seen msg_ids) from the meter cache."""
    data = _read_json_file(_token_meter_cache_path(branch_name))
    offsets: dict[str, int] = {}
    seen: set[str] = set()
    if isinstance(data, dict):
        raw_offsets = data.get("offsets")
        if isinstance(raw_offsets, dict):
            for key, value in raw_offsets.items():
                if isinstance(key, str) and isinstance(value, int) and value >= 0:
                    offsets[key] = value
        raw_seen = data.get("seen_ids")
        if isinstance(raw_seen, list):
            seen = {str(x) for x in raw_seen if isinstance(x, str)}
    return offsets, seen


def _save_meter_cache(
    branch_name: str, offsets: dict[str, int], seen_ids: set[str]
) -> None:
    # Offsets are the primary dedup; seen_ids is a bounded safety net (a long
    # run never re-reads old lines, so a lexicographic trim cannot double-count).
    trimmed = sorted(seen_ids)[-_SEEN_ID_CACHE_LIMIT:]
    _write_json_file(
        _token_meter_cache_path(branch_name),
        {"offsets": offsets, "seen_ids": trimmed, "updated_at": _utc_timestamp()},
    )


def _current_token_attribution(branch_name: str) -> tuple[Optional[str], str]:
    """Return (current_subtask_id, current_step_phase) from step_state."""
    data = _read_json_file(get_branch_dir(branch_name) / "step_state.json")
    if not isinstance(data, dict):
        return (None, "")
    sid = data.get("current_subtask_id")
    phase = data.get("current_step_phase")
    return (
        sid if isinstance(sid, str) else None,
        phase if isinstance(phase, str) else "",
    )


def record_token_event(
    branch: Optional[str] = None,
    *,
    transcript_path: str = "",
    agent: str = "",
    phase: str = "",
    subtask_id: str = "",
) -> dict[str, object]:
    """Attribute new transcript token usage to the active subtask and log it.

    Parses assistant ``usage`` blocks from ``transcript_path`` that the
    per-branch dedup cache hasn't seen, appends one attributed row per turn to
    ``token_log.jsonl``, then rebuilds ``token_accounting.json``. Attribution
    (subtask/phase) falls back to step_state and agent to the phase mapping
    when callers don't pass them explicitly. Returns the totals just recorded.
    """
    # Sanitize an explicit branch the same way MAP does elsewhere — the value
    # becomes a path segment via get_branch_dir, so an unsanitized argument
    # (e.g. "../../tmp") would escape the .map tree.
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    if not transcript_path:
        return {"status": "error", "reason": "transcript_path required"}

    cur_subtask, cur_phase = _current_token_attribution(branch_name)
    subtask_id = subtask_id or cur_subtask or "unattributed"
    phase = phase or cur_phase or ""
    agent = agent or _PHASE_TO_AGENT.get(phase, "orchestrator")

    transcript_key = str(transcript_path)
    offsets, seen = _load_meter_cache(branch_name)
    start_offset = offsets.get(transcript_key, 0)
    new_usages, new_offset = _iter_new_usage(
        Path(transcript_path), seen, start_offset
    )
    totals: dict[str, int] = {field: 0 for field in _TOKEN_FIELDS}

    if not new_usages:
        # Still persist an advanced offset so non-usage lines (user turns) are
        # not re-scanned next call.
        if new_offset != start_offset:
            offsets[transcript_key] = new_offset
            _save_meter_cache(branch_name, offsets, seen)
        return {
            "status": "success",
            "recorded": 0,
            "subtask_id": subtask_id,
            "phase": phase,
            "agent": agent,
            **totals,
        }

    log_path = get_branch_dir(branch_name) / TOKEN_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            for usage in new_usages:
                row = {
                    "ts": timestamp,
                    "subtask_id": subtask_id,
                    "phase": phase,
                    "agent": agent,
                    "model": str(usage["model"]),
                    "msg_id": str(usage["msg_id"]),
                    **{field: int(usage[field]) for field in _TOKEN_FIELDS},  # type: ignore[arg-type]
                }
                handle.write(json.dumps(row) + "\n")
                for field in _TOKEN_FIELDS:
                    totals[field] += int(usage[field])  # type: ignore[arg-type]
                seen.add(str(usage["msg_id"]))
    except OSError as exc:
        return {"status": "error", "reason": str(exc)}

    offsets[transcript_key] = new_offset
    _save_meter_cache(branch_name, offsets, seen)
    _rebuild_token_accounting(branch_name)
    return {
        "status": "success",
        "recorded": len(new_usages),
        "subtask_id": subtask_id,
        "phase": phase,
        "agent": agent,
        **totals,
    }


def _empty_token_bucket() -> dict[str, float]:
    return {field: 0 for field in _TOKEN_FIELDS}


def _rebuild_token_accounting(branch: Optional[str] = None) -> dict[str, object]:
    """Roll token_log.jsonl up into token_accounting.json.

    Groups by subtask, agent, and phase, plus an aggregate carrying
    ``cache_hit_ratio`` (cache_read / (input + cache_read)) and
    ``est_cost_usd``. Rows are deduped by msg_id (keeping the most complete
    copy) before rollup, so a log written by an older runner — one assistant
    turn split across several rows — still produces a correct total instead of
    a doubled one. ``event_count`` is therefore the number of distinct turns.
    Returns the written payload.
    """
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    log_path = get_branch_dir(branch_name) / TOKEN_LOG_NAME
    by_subtask: dict[str, dict[str, float]] = {}
    by_agent: dict[str, dict[str, float]] = {}
    by_phase: dict[str, dict[str, float]] = {}
    aggregate: dict[str, float] = _empty_token_bucket()
    total_cost = 0.0
    event_count = 0

    if log_path.is_file():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        # One assistant turn can occupy several token_log rows (Claude Code
        # writes one JSONL line per content/tool_use block, all sharing a
        # msg_id). Logs written before the write-time dedup landed still hold
        # those repeats, so collapse by msg_id here too — keep the row with the
        # most total tokens (the figure the API bills) — and stay correct.
        deduped: dict[str, dict[str, object]] = {}
        order: list[str] = []
        anon = 0
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            mid = str(row.get("msg_id") or "")
            if not mid:
                key = f"__anon_{anon}"
                anon += 1
            else:
                key = mid
            prev = deduped.get(key)
            if prev is None:
                order.append(key)
                deduped[key] = row
            elif _usage_token_total(row) > _usage_token_total(prev):
                deduped[key] = row

        for key in order:
            row = deduped[key]
            event_count += 1
            model = str(row.get("model") or "")
            usage: dict[str, int] = {
                field: _coerce_token_int(row.get(field, 0)) for field in _TOKEN_FIELDS
            }
            row_cost = _token_cost(usage, model)
            total_cost += row_cost
            for dim_key, dim in (
                (str(row.get("subtask_id") or "unattributed"), by_subtask),
                (str(row.get("agent") or "unknown"), by_agent),
                (str(row.get("phase") or "unknown"), by_phase),
            ):
                bucket = dim.setdefault(
                    dim_key, {**_empty_token_bucket(), "est_cost_usd": 0.0}
                )
                for field in _TOKEN_FIELDS:
                    bucket[field] += usage[field]
                bucket["est_cost_usd"] = round(
                    bucket.get("est_cost_usd", 0.0) + row_cost, 6
                )
            for field in _TOKEN_FIELDS:
                aggregate[field] += usage[field]

    cache_read = aggregate["cache_read"]
    cacheable = aggregate["input"] + cache_read
    aggregate["cache_hit_ratio"] = (
        round(cache_read / cacheable, 4) if cacheable else 0.0
    )
    aggregate["est_cost_usd"] = round(total_cost, 4)

    payload: dict[str, object] = {
        "schema_version": "1.0",
        "branch": branch_name,
        "updated_at": _utc_timestamp(),
        "event_count": event_count,
        "aggregate": aggregate,
        "by_subtask": by_subtask,
        "by_agent": by_agent,
        "by_phase": by_phase,
    }
    _write_json_file(get_branch_dir(branch_name) / TOKEN_ACCOUNTING_NAME, payload)
    return payload


def token_report(branch: Optional[str] = None) -> str:
    """Render a per-subtask token table (input/output/cache/cost) as text."""
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    payload = _rebuild_token_accounting(branch_name)
    aggregate = cast(dict[str, float], payload["aggregate"])
    by_subtask = cast(dict[str, dict[str, float]], payload["by_subtask"])

    header = (
        f"{'subtask':<18}{'input':>13}{'output':>12}"
        f"{'cache_rd':>13}{'cache_cr':>12}{'$cost':>10}"
    )
    rows = [
        f"Token accounting — {branch_name} "
        f"({payload['event_count']} assistant turns)",
        "",
        header,
        "-" * len(header),
    ]

    def _fmt(label: str, bucket: Mapping[str, float]) -> str:
        return (
            f"{label:<18}"
            f"{int(bucket.get('input', 0)):>13,}"
            f"{int(bucket.get('output', 0)):>12,}"
            f"{int(bucket.get('cache_read', 0)):>13,}"
            f"{int(bucket.get('cache_creation', 0)):>12,}"
            f"{bucket.get('est_cost_usd', 0.0):>10.2f}"
        )

    for sid in sorted(by_subtask):
        rows.append(_fmt(sid, by_subtask[sid]))
    rows.append("-" * len(header))
    rows.append(_fmt("TOTAL", aggregate))
    rows.append("")
    ratio = float(aggregate.get("cache_hit_ratio", 0.0)) * 100
    rows.append(
        f"cache hit ratio: {ratio:.1f}%   "
        f"est cost: ${float(aggregate.get('est_cost_usd', 0.0)):.2f}"
    )
    return "\n".join(rows) + "\n"


def _prior_stage_file_entry(
    key: str,
    label: str,
    path: Path,
    *,
    required: bool = True,
) -> dict[str, object]:
    """Return one prior-stage artifact consumption entry."""
    present = path.exists() and path.is_file()
    return {
        "key": key,
        "label": label,
        "kind": "file",
        "path": str(path),
        "required": required,
        "present": present,
        "consumed": present,
        "count": 1 if present else 0,
        "reason": "" if present else f"missing required artifact: {path}",
    }


def _prior_stage_glob_entry(
    key: str,
    label: str,
    branch_dir: Path,
    pattern: str,
    *,
    required: bool = True,
) -> dict[str, object]:
    """Return one prior-stage glob artifact consumption entry."""
    try:
        paths = sorted(
            path for path in branch_dir.glob(pattern) if path.exists() and path.is_file()
        )
    except OSError:
        paths = []
    present = bool(paths)
    return {
        "key": key,
        "label": label,
        "kind": "glob",
        "path": str(branch_dir / pattern),
        "paths": [str(path) for path in paths],
        "required": required,
        "present": present,
        "consumed": present,
        "count": len(paths),
        "reason": "" if present else f"missing required artifact matching: {branch_dir / pattern}",
    }


def _prior_stage_diff_entry(
    code_state: Mapping[str, object], *, required: bool = True
) -> dict[str, object]:
    """Return the current diff snapshot as a prior-stage consumption entry."""
    files_changed = code_state.get("files_changed")
    file_count = len(files_changed) if isinstance(files_changed, list) else 0
    diff_stat = code_state.get("diff_stat")
    present = code_state.get("status") == "success" and (file_count > 0 or bool(diff_stat))
    return {
        "key": "code_diff",
        "label": "code diff",
        "kind": "git-diff",
        "path": "git diff --stat HEAD",
        "required": required,
        "present": present,
        "consumed": present,
        "count": file_count,
        "reason": "" if present else "missing code diff snapshot; no changed files were visible against HEAD",
    }


def build_prior_stage_consumption_report(
    stage: str = "review",
    branch: Optional[str] = None,
    code_state: Optional[Mapping[str, object]] = None,
) -> dict[str, object]:
    """Report whether closeout consumed the prior-stage artifacts it depends on."""
    normalized_stage = (stage or "review").strip().lower().replace("-", "_")
    if normalized_stage not in PRIOR_STAGE_CONSUMPTION_STAGES:
        return {
            "status": "error",
            "valid": False,
            "stage": normalized_stage,
            "branch": branch or get_branch_name(),
            "errors": [
                "stage must be one of: "
                + ", ".join(sorted(PRIOR_STAGE_CONSUMPTION_STAGES))
            ],
            "required_artifacts": [],
            "summary": {"required": 0, "consumed": 0, "missing": 0},
        }

    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    current_code_state = code_state or snapshot_code_state(branch_name)
    required_artifacts = [
        _prior_stage_file_entry(
            "spec", "specification", branch_dir / f"spec_{branch_name}.md"
        ),
        _prior_stage_file_entry(
            "task_plan", "task plan", branch_dir / f"task_plan_{branch_name}.md"
        ),
        _prior_stage_file_entry("blueprint", "blueprint", branch_dir / "blueprint.json"),
        _prior_stage_glob_entry(
            "test_contract", "test contract", branch_dir, "test_contract_*.md"
        ),
        _prior_stage_diff_entry(current_code_state),
    ]
    if normalized_stage == "review":
        required_artifacts.append(
            _prior_stage_file_entry(
                "verification_summary",
                "verification summary",
                branch_dir / "verification-summary.md",
            )
        )

    missing = [
        item for item in required_artifacts if item.get("required") and not item.get("consumed")
    ]
    errors = [str(item.get("reason")) for item in missing if item.get("reason")]
    summary = {
        "required": sum(1 for item in required_artifacts if item.get("required")),
        "consumed": sum(
            1
            for item in required_artifacts
            if item.get("required") and item.get("consumed")
        ),
        "missing": len(missing),
    }
    return {
        "status": "ready" if not missing else "blocked",
        "valid": not missing,
        "stage": normalized_stage,
        "branch": branch_name,
        "required_artifacts": required_artifacts,
        "summary": summary,
        "errors": errors,
    }


def _render_prior_stage_consumption_markdown(report: Mapping[str, object]) -> str:
    """Render prior-stage consumption as reviewer-readable Markdown."""
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    required = summary.get("required", 0) if isinstance(summary, Mapping) else 0
    consumed = summary.get("consumed", 0) if isinstance(summary, Mapping) else 0
    missing = summary.get("missing", 0) if isinstance(summary, Mapping) else 0
    lines = [
        "## Prior-Stage Consumption",
        f"- Stage: {report.get('stage') or 'unknown'}",
        f"- Status: {report.get('status') or 'unknown'}",
        f"- Consumed required inputs: {consumed}/{required}",
    ]
    required_artifacts = report.get("required_artifacts", [])
    for item in required_artifacts if isinstance(required_artifacts, list) else []:
        if not isinstance(item, Mapping):
            continue
        status = "consumed" if item.get("consumed") else "missing"
        label = item.get("label") or item.get("key") or "artifact"
        path = item.get("path") or ""
        count = item.get("count", 0)
        reason = item.get("reason") or ""
        detail = f"; {reason}" if reason else ""
        lines.append(f"- [{status}] {label}: `{path}` ({count}){detail}")
    if missing:
        lines.append("- Action: create or refresh the missing prior-stage artifacts before claiming the workflow is ready.")
    return "\n".join(lines) + "\n"


def _metrics_event_log_path() -> Path:
    """Return the append-only metrics JSONL path."""
    return Path(".claude/metrics/agent_metrics.jsonl")


def _append_metrics_event(event: dict[str, object]) -> None:
    """Append one metrics event to .claude/metrics/agent_metrics.jsonl."""
    path = _metrics_event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def _parse_rfc3339_timestamp(value: object) -> Optional[datetime]:
    """Parse RFC3339 timestamps, accepting a trailing Z."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _default_learning_metrics(branch: str) -> dict[str, object]:
    """Return an empty learning metrics payload for a branch."""
    return {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "counters": dict(LEARNING_METRICS_COUNTER_DEFAULTS),
        "current_handoff": None,
        "events": [],
    }


def _refresh_learning_metrics_counters(metrics: dict[str, object]) -> None:
    """Recompute derived counters for the learning metrics payload."""
    counters = metrics.setdefault("counters", {})
    if not isinstance(counters, dict):
        counters = {}
        metrics["counters"] = counters
    for key, value in LEARNING_METRICS_COUNTER_DEFAULTS.items():
        counters[key] = int(counters.get(key, value) or 0)

    current_handoff = metrics.get("current_handoff")
    counters["pending_handoff_count"] = (
        1
        if isinstance(current_handoff, dict) and not current_handoff.get("consumed_at")
        else 0
    )


def load_learning_metrics(branch: Optional[str] = None) -> dict[str, object]:
    """Load branch-scoped learning metrics, filling missing defaults."""
    branch_name = branch or get_branch_name()
    metrics_path = learning_metrics_path(branch_name)
    metrics = _default_learning_metrics(branch_name)

    if metrics_path.exists():
        try:
            loaded = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}

        if isinstance(loaded, dict):
            metrics["updated_at"] = loaded.get("updated_at", metrics["updated_at"])
            counters = loaded.get("counters")
            if isinstance(counters, dict):
                cast(dict[str, int], metrics["counters"]).update(counters)
            current_handoff = loaded.get("current_handoff")
            if isinstance(current_handoff, dict):
                metrics["current_handoff"] = current_handoff
            events = loaded.get("events")
            if isinstance(events, list):
                metrics["events"] = [item for item in events if isinstance(item, dict)][
                    -25:
                ]

    _refresh_learning_metrics_counters(metrics)
    return metrics


def save_learning_metrics(
    metrics: dict[str, object], branch: Optional[str] = None
) -> dict[str, object]:
    """Persist learning metrics and return status metadata."""
    branch_name = branch or get_branch_name()
    metrics["branch"] = branch_name
    metrics["updated_at"] = _utc_timestamp()
    _refresh_learning_metrics_counters(metrics)
    path = learning_metrics_path(branch_name)
    _write_json_file(path, metrics)
    return {"status": "success", "path": str(path), "metrics": metrics}


def _append_learning_metrics_event(
    metrics: dict[str, object], event: dict[str, object]
) -> None:
    """Append a learning metrics event to the branch summary payload."""
    events = metrics.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        metrics["events"] = events
    events.append(event)
    del events[:-25]


def _classify_learning_consumption_mode(
    generated_at: object, consumed_at: object
) -> str:
    """Classify a learn invocation as immediate or deferred based on handoff age."""
    generated_dt = _parse_rfc3339_timestamp(generated_at)
    consumed_dt = _parse_rfc3339_timestamp(consumed_at)
    if not generated_dt or not consumed_dt:
        return "deferred"
    delta_seconds = (consumed_dt - generated_dt).total_seconds()
    if delta_seconds <= LEARNING_IMMEDIATE_WINDOW_SECONDS:
        return "immediate"
    return "deferred"


def _record_learning_handoff_generation_metrics(
    workflow: str,
    generated_at: str,
    markdown_path: Path,
    json_path: Path,
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Update branch/global metrics when a new learning handoff is generated."""
    branch_name = branch or get_branch_name()
    metrics = load_learning_metrics(branch_name)
    counters = cast(dict[str, int], metrics["counters"])
    current_handoff = metrics.get("current_handoff")

    if isinstance(current_handoff, dict) and not current_handoff.get("consumed_at"):
        counters["never_used_handoff_count"] += 1
        abandoned_event: dict[str, object] = {
            "event": "learning_handoff_abandoned",
            "timestamp": generated_at,
            "branch": branch_name,
            "workflow": current_handoff.get("workflow"),
            "generated_at": current_handoff.get("generated_at"),
            "handoff_json_path": current_handoff.get("handoff_json_path"),
        }
        _append_learning_metrics_event(metrics, abandoned_event)
        _append_metrics_event(
            {
                "event": "learning_handoff_abandoned",
                "category": "learning",
                "timestamp": generated_at,
                "branch": branch_name,
                "workflow": current_handoff.get("workflow"),
                "generated_at": current_handoff.get("generated_at"),
                "handoff_json_path": current_handoff.get("handoff_json_path"),
            }
        )

    counters["handoff_generated_count"] += 1
    metrics["current_handoff"] = {
        "workflow": workflow,
        "generated_at": generated_at,
        "consumed_at": "",
        "consumption_mode": "",
        "consumption_source": "",
        "handoff_markdown_path": str(markdown_path),
        "handoff_json_path": str(json_path),
    }
    generation_event: dict[str, object] = {
        "event": "learning_handoff_generated",
        "timestamp": generated_at,
        "branch": branch_name,
        "workflow": workflow,
        "handoff_markdown_path": str(markdown_path),
        "handoff_json_path": str(json_path),
    }
    _append_learning_metrics_event(metrics, generation_event)
    metrics_result = save_learning_metrics(metrics, branch_name)
    _append_metrics_event(
        {
            "event": "learning_handoff_generated",
            "category": "learning",
            "timestamp": generated_at,
            "branch": branch_name,
            "workflow": workflow,
            "handoff_markdown_path": str(markdown_path),
            "handoff_json_path": str(json_path),
            "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
        }
    )
    return metrics_result


def record_learning_consumption(
    summary_source: str = "inline-summary",
    workflow: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Record a completed /map-learn invocation for adoption/deferred-use metrics."""
    branch_name = branch or get_branch_name()
    source = (summary_source or "").strip().lower()
    if source not in LEARNING_CONSUMPTION_SOURCES:
        return {"status": "error", "message": f"Invalid summary_source: {summary_source}"}

    metrics = load_learning_metrics(branch_name)
    counters = cast(dict[str, int], metrics["counters"])
    timestamp = _utc_timestamp()
    current_handoff = metrics.get("current_handoff")
    workflow_name = workflow.strip() or ""

    result: dict[str, object] = {
        "status": "success",
        "branch": branch_name,
        "summary_source": source,
    }

    if source in {"auto-handoff", "file-handoff"} and isinstance(current_handoff, dict):
        workflow_name = current_handoff.get("workflow") or workflow_name
        result["workflow"] = workflow_name
        if current_handoff.get("consumed_at"):
            event: dict[str, object] = {
                "event": "learning_handoff_reused",
                "timestamp": timestamp,
                "branch": branch_name,
                "workflow": workflow_name,
                "summary_source": source,
                "consumption_mode": current_handoff.get("consumption_mode") or "",
            }
            _append_learning_metrics_event(metrics, event)
            metrics_result = save_learning_metrics(metrics, branch_name)
            _append_metrics_event(
                {
                    "event": "learning_handoff_reused",
                    "category": "learning",
                    "timestamp": timestamp,
                    "branch": branch_name,
                    "workflow": workflow_name,
                    "summary_source": source,
                    "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
                }
            )
            result["usage_status"] = "already_recorded"
            result["consumption_mode"] = current_handoff.get("consumption_mode") or ""
            result["metrics_path"] = metrics_result["path"]
            return result

        consumption_mode = _classify_learning_consumption_mode(
            current_handoff.get("generated_at"), timestamp
        )
        current_handoff["consumed_at"] = timestamp
        current_handoff["consumption_mode"] = consumption_mode
        current_handoff["consumption_source"] = source
        counters["handoff_consumed_count"] += 1
        counters[f"{consumption_mode}_learn_count"] += 1
        event = {
            "event": "learning_handoff_consumed",
            "timestamp": timestamp,
            "branch": branch_name,
            "workflow": workflow_name,
            "summary_source": source,
            "consumption_mode": consumption_mode,
            "generated_at": current_handoff.get("generated_at"),
        }
        _append_learning_metrics_event(metrics, event)
        metrics_result = save_learning_metrics(metrics, branch_name)
        _append_metrics_event(
            {
                "event": "learning_handoff_consumed",
                "category": "learning",
                "timestamp": timestamp,
                "branch": branch_name,
                "workflow": workflow_name,
                "summary_source": source,
                "consumption_mode": consumption_mode,
                "generated_at": current_handoff.get("generated_at"),
                "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
            }
        )
        result["usage_status"] = "recorded"
        result["consumption_mode"] = consumption_mode
        result["metrics_path"] = metrics_result["path"]
        return result

    counters["manual_summary_count"] += 1
    event = {
        "event": "learning_manual_summary_recorded",
        "timestamp": timestamp,
        "branch": branch_name,
        "workflow": workflow_name or None,
        "summary_source": source,
    }
    _append_learning_metrics_event(metrics, event)
    metrics_result = save_learning_metrics(metrics, branch_name)
    _append_metrics_event(
        {
            "event": "learning_manual_summary_recorded",
            "category": "learning",
            "timestamp": timestamp,
            "branch": branch_name,
            "workflow": workflow_name or None,
            "summary_source": source,
            "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
        }
    )
    result["usage_status"] = "manual_summary"
    result["metrics_path"] = metrics_result["path"]
    if workflow_name:
        result["workflow"] = workflow_name
    return result


def _normalize_learning_token(token: str) -> str:
    """Normalize lightweight text tokens for repeated-violation matching."""
    normalized = token.lower()
    if normalized.endswith("ies") and len(normalized) > 5:
        normalized = normalized[:-3] + "y"
    elif normalized.endswith("es") and len(normalized) > 5:
        normalized = normalized[:-2]
    elif normalized.endswith("s") and len(normalized) > 4:
        normalized = normalized[:-1]
    return normalized


def _tokenize_learning_text(text: str) -> set[str]:
    """Extract normalized non-trivial tokens from free-form learning text."""
    tokens = {
        _normalize_learning_token(match.group(0))
        for match in TOKEN_RE.finditer((text or "").lower())
    }
    return {
        token
        for token in tokens
        if token and token not in LEARNING_MATCH_STOPWORDS
    }


def _slugify_learning_text(text: str) -> str:
    """Build a stable slug for lightweight identifiers."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "rule"


def _parse_rule_paths(content: str) -> list[str]:
    """Extract optional paths frontmatter globs from a learned-rule markdown file."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    paths: list[str] = []
    in_paths = False
    for raw_line in lines[1:]:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if stripped.startswith("- "):
            candidate = stripped[2:].strip().strip("\"'")
            if candidate:
                paths.append(candidate)
            continue
        if stripped:
            in_paths = False
    return paths


def _load_learned_rules() -> list[dict[str, object]]:
    """Load learned-rule bullets plus their optional path scopes."""
    rules_dir = Path(".claude/rules/learned")
    if not rules_dir.exists():
        return []

    rules: list[dict[str, object]] = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        if rule_file.name == "README.md":
            continue
        try:
            content = rule_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rule_paths = _parse_rule_paths(content)
        for raw_line in content.splitlines():
            match = LEARNED_RULE_BULLET_RE.match(raw_line.strip())
            if not match:
                continue
            title = match.group("title").strip()
            body = match.group("body").strip()
            rules.append(
                {
                    "rule_id": f"{rule_file.stem}:{_slugify_learning_text(title)}",
                    "title": title,
                    "body": body,
                    "file": str(rule_file),
                    "paths": rule_paths,
                    "title_tokens": _tokenize_learning_text(title),
                    "body_tokens": _tokenize_learning_text(body),
                }
            )
    return rules


def _normalize_section_title(title: str) -> str:
    """Normalize markdown section headings for comparison."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _extract_section_bullets(content: str, headings: set[str]) -> list[str]:
    """Extract bullet items from selected markdown sections."""
    allowed = {_normalize_section_title(item) for item in headings}
    bullets: list[str] = []
    current_heading = ""

    for raw_line in content.splitlines():
        heading_match = SECTION_HEADING_RE.match(raw_line.strip())
        if heading_match:
            current_heading = _normalize_section_title(heading_match.group("title"))
            continue

        stripped = raw_line.strip()
        if current_heading not in allowed or not stripped.startswith("- "):
            continue

        bullet = stripped[2:].strip()
        if bullet.lower() in {"(none)", "[not recorded]"}:
            continue
        bullets.append(bullet)

    return bullets


def _extract_path_hints(text: str) -> list[str]:
    """Extract likely repo-relative file paths from finding text."""
    hints: list[str] = []
    seen: set[str] = set()
    for match in PATH_HINT_RE.finditer(text or ""):
        candidate = match.group("path").strip("`'\"").rstrip(".,)]")
        normalized = candidate.lstrip("./")
        if not normalized or normalized in seen:
            continue
        hints.append(normalized)
        seen.add(normalized)
    return hints


def _collect_repeated_violation_findings(branch: str) -> list[dict[str, object]]:
    """Collect findings from branch artifacts that can be correlated with learned rules."""
    branch_dir = get_branch_dir(branch)
    findings: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def append_finding(source: str, text: str, source_artifact: str = "") -> None:
        normalized_text = (text or "").strip()
        if not normalized_text:
            return
        dedupe_key = (source, normalized_text)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        findings.append(
            {
                "source": source,
                "source_artifact": source_artifact or source,
                "text": normalized_text,
                "path_hints": _extract_path_hints(normalized_text),
            }
        )

    active_issues_payload = _read_json_file(branch_dir / "active-issues.json") or {}
    active_issues = active_issues_payload.get("issues", [])
    if isinstance(active_issues, list):
        for issue in active_issues:
            if not isinstance(issue, dict):
                continue
            append_finding(
                "active-issues.json",
                str(issue.get("summary") or issue.get("title") or ""),
                str(issue.get("source_artifact") or "active-issues.json"),
            )

    verification_summary = _read_branch_artifact_text(branch_dir, "verification-summary.md")
    for bullet in _extract_section_bullets(verification_summary, {"Findings"}):
        append_finding("verification-summary.md", bullet)

    review_handoff = build_review_handoff(branch)
    code_review = str(review_handoff.get("code_review") or "")
    code_review_path = str(review_handoff.get("code_review_path") or "code-review")
    for bullet in _extract_section_bullets(
        code_review, {"High", "Medium", "Low", "Open Concerns"}
    ):
        append_finding(code_review_path, bullet, code_review_path)

    return findings


def _paths_match_rule_scope(rule_paths: list[str], path_hints: list[str]) -> bool:
    """Return True when a finding path fits at least one learned-rule glob."""
    for path_hint in path_hints:
        for pattern in rule_paths:
            if fnmatch.fnmatch(path_hint, pattern) or fnmatch.fnmatch(
                f"./{path_hint}", pattern
            ):
                return True
    return False


def _match_finding_to_learned_rule(
    finding: dict[str, object], learned_rules: list[dict[str, object]]
) -> Optional[dict[str, object]]:
    """Find the best learned-rule match for one finding, if any."""
    finding_text = str(finding.get("text") or "")
    finding_tokens = _tokenize_learning_text(finding_text)
    if not finding_tokens:
        return None

    path_hints = [
        str(path)
        for path in cast(list[object], finding.get("path_hints", []))
        if isinstance(path, str) and path.strip()
    ]
    best_match: Optional[dict[str, object]] = None

    for rule in learned_rules:
        rule_paths = [
            str(path)
            for path in cast(list[object], rule.get("paths", []))
            if isinstance(path, str) and path.strip()
        ]
        path_match = _paths_match_rule_scope(rule_paths, path_hints) if path_hints else False
        if rule_paths and path_hints and not path_match:
            continue

        title_tokens = set(cast(Iterable[str], rule.get("title_tokens", set())))
        body_tokens = set(cast(Iterable[str], rule.get("body_tokens", set())))
        title_overlap = sorted(finding_tokens & title_tokens)
        body_overlap = sorted((finding_tokens & body_tokens) - set(title_overlap))
        score = len(title_overlap) * 3 + len(body_overlap)
        if path_match:
            score += 2

        qualifies = len(title_overlap) >= 2 or score >= 4
        if not qualifies:
            continue

        match: dict[str, object] = {
            "rule_id": str(rule["rule_id"]),
            "rule_title": str(rule["title"]),
            "rule_file": str(rule["file"]),
            "rule_paths": rule_paths,
            "finding_source": str(finding.get("source") or ""),
            "finding_source_artifact": str(finding.get("source_artifact") or ""),
            "finding_text": finding_text,
            "finding_path_hints": path_hints,
            "matched_tokens": title_overlap + body_overlap,
            "score": score,
            "path_match": path_match,
        }
        if not best_match or int(cast(int, match["score"])) > int(cast(int, best_match["score"])):
            best_match = match

    return best_match


def record_repeated_learning_violations(
    branch: Optional[str] = None, metrics: Optional[dict[str, object]] = None
) -> dict[str, object]:
    """Correlate current findings with learned rules and persist a summary."""
    branch_name = branch or get_branch_name()
    learned_rules = _load_learned_rules()
    findings = _collect_repeated_violation_findings(branch_name)
    matches = []
    for finding in findings:
        match = _match_finding_to_learned_rule(finding, learned_rules)
        if match:
            matches.append(match)

    summary = {
        "checked_at": _utc_timestamp(),
        "finding_count": len(findings),
        "learned_rule_count": len(learned_rules),
        "matched_count": len(matches),
        "matches": matches[:10],
    }

    metrics_payload = metrics if isinstance(metrics, dict) else load_learning_metrics(branch_name)
    counters = metrics_payload.setdefault("counters", {})
    if not isinstance(counters, dict):
        counters = {}
        metrics_payload["counters"] = counters
    counters["repeated_violation_scan_count"] = (
        int(counters.get("repeated_violation_scan_count", 0) or 0) + 1
    )
    counters["repeated_violation_match_count"] = (
        int(counters.get("repeated_violation_match_count", 0) or 0) + len(matches)
    )
    metrics_payload["repeated_violation_summary"] = summary

    if matches:
        event = {
            "event": "learning_repeated_violation_detected",
            "timestamp": summary["checked_at"],
            "branch": branch_name,
            "match_count": len(matches),
            "matches": matches[:5],
        }
        _append_learning_metrics_event(metrics_payload, event)

    metrics_result = save_learning_metrics(metrics_payload, branch_name)
    if matches:
        _append_metrics_event(
            {
                "event": "learning_repeated_violation_detected",
                "category": "learning",
                "timestamp": summary["checked_at"],
                "branch": branch_name,
                "match_count": len(matches),
                "matches": matches[:5],
                "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
            }
        )

    return {
        "status": "success",
        "summary": summary,
        "metrics": metrics_result["metrics"],
        "path": metrics_result["path"],
    }


def record_workflow_fit(
    recommended_workflow: str,
    expected_diff_size: str = "medium",
    has_new_invariants: object = False,
    needs_independent_review: object = False,
    has_clear_acceptance_criteria: object = True,
    test_first_required: object = False,
    decision_summary: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Persist workflow-fit decision and update the artifact manifest."""
    branch_name = branch or get_branch_name()
    route = (recommended_workflow or "").strip().lower()
    diff_size = (expected_diff_size or "").strip().lower()

    if route not in WORKFLOW_FIT_ROUTES:
        return {
            "status": "error",
            "message": f"Invalid recommended_workflow: {recommended_workflow}",
        }
    if diff_size not in DIFF_SIZE_LEVELS:
        return {
            "status": "error",
            "message": f"Invalid expected_diff_size: {expected_diff_size}",
        }

    signals = {
        "expected_diff_size": diff_size,
        "has_new_invariants": _parse_boolish(has_new_invariants),
        "needs_independent_review": _parse_boolish(needs_independent_review),
        "has_clear_acceptance_criteria": _parse_boolish(
            has_clear_acceptance_criteria
        ),
        "test_first_required": _parse_boolish(test_first_required),
    }
    needs_map = route != "direct-edit"
    payload = {
        "version": "1.0",
        "recommended_workflow": route,
        "needs_map": needs_map,
        "decision_summary": decision_summary or "No decision summary provided.",
        "signals": signals,
        "updated_at": _utc_timestamp(),
    }

    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    decision_path = branch_dir / "workflow-fit.json"
    _write_json_file(decision_path, payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "workflow_fit",
        "recorded",
        artifacts=[_artifact_ref(decision_path, "workflow-fit-decision")],
        metadata={
            "recommended_workflow": route,
            "needs_map": needs_map,
            "signals": signals,
            "decision_summary": payload["decision_summary"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)

    return {
        "status": "success",
        "path": str(decision_path),
        "recommended_workflow": route,
        "needs_map": needs_map,
        "manifest_path": manifest_result["path"],
    }


def record_plan_artifacts(branch: Optional[str] = None) -> dict[str, object]:
    """Persist spec/plan artifact presence into artifact_manifest.json."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)

    spec_path = branch_dir / f"spec_{branch_name}.md"
    task_plan_path = branch_dir / f"task_plan_{branch_name}.md"
    blueprint_path = branch_dir / "blueprint.json"
    step_state_path = branch_dir / "step_state.json"

    manifest = load_artifact_manifest(branch_name)

    spec_artifacts = []
    if spec_path.exists():
        spec_artifacts.append(_artifact_ref(spec_path, "spec"))
    _set_manifest_stage(
        manifest,
        "spec",
        "ready" if spec_artifacts else "missing",
        artifacts=spec_artifacts,
        metadata={},
    )

    plan_artifacts = []
    if task_plan_path.exists():
        plan_artifacts.append(_artifact_ref(task_plan_path, "task-plan"))
    if blueprint_path.exists():
        plan_artifacts.append(_artifact_ref(blueprint_path, "blueprint"))
    if step_state_path.exists():
        plan_artifacts.append(_artifact_ref(step_state_path, "step-state"))

    # /map-plan deliberately stops BEFORE INIT_STATE writes step_state.json
    # — that step belongs to /map-efficient. So "plan complete" means
    # blueprint + task_plan are both present, regardless of step_state.
    # Only flag "partial" when one of those is missing.
    if task_plan_path.exists() and blueprint_path.exists():
        plan_status = "ready"
    elif plan_artifacts:
        plan_status = "partial"
    else:
        plan_status = "missing"

    _set_manifest_stage(
        manifest,
        "plan",
        plan_status,
        artifacts=plan_artifacts,
        metadata={
            "has_task_plan": task_plan_path.exists(),
            "has_blueprint": blueprint_path.exists(),
            "has_step_state": step_state_path.exists(),
        },
    )

    manifest_result = save_artifact_manifest(manifest, branch_name)
    stages = cast(dict[str, dict[str, object]], manifest["stages"])
    return {
        "status": "success",
        "manifest_path": manifest_result["path"],
        "spec_status": stages["spec"]["status"],
        "plan_status": stages["plan"]["status"],
    }


def validate_blueprint_contract(
    blueprint_path: str = "", branch: Optional[str] = None
) -> dict[str, object]:
    """Validate that a blueprint is executable as contract-sized subtasks.

    This is stricter than BLUEPRINT_SCHEMA because it is a user/operator gate:
    plans should fail before implementation when subtasks are oversized,
    mixed-concern without rationale, or impossible to trace back to acceptance
    criteria.
    """
    branch_name = branch or get_branch_name()
    path = Path(blueprint_path) if blueprint_path else get_branch_dir(branch_name) / "blueprint.json"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "valid": False,
            "errors": [f"blueprint not found: {path}"],
            "warnings": [],
            "path": str(path),
        }
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "valid": False,
            "errors": [f"cannot read blueprint {path}: {exc}"],
            "warnings": [],
            "path": str(path),
        }

    blueprint_body = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    subtasks = blueprint_body.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        return {
            "valid": False,
            "errors": ["blueprint must contain at least one subtask"],
            "warnings": [],
            "path": str(path),
        }

    hard_constraints = blueprint_body.get("hard_constraints")
    soft_constraints = blueprint_body.get("soft_constraints")
    if not isinstance(hard_constraints, list):
        errors.append("hard_constraints is required and must be an array")
        hard_constraints = []
    if not isinstance(soft_constraints, list):
        errors.append("soft_constraints is required and must be an array")
        soft_constraints = []

    # Constraints accept either `description` or `text` (some decomposer
    # agent generations use `text`); both fields are read with the same
    # meaning so the contract stops rejecting valid blueprints on a naming
    # mismatch alone.
    def _constraint_body(c: dict) -> str:
        for key in ("description", "text"):
            v = c.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    hard_constraint_ids: list[str] = []
    for index, constraint in enumerate(hard_constraints):
        label = f"hard_constraints[{index}]"
        if not isinstance(constraint, dict):
            errors.append(f"{label}: must be an object with id and description (or text)")
            continue
        constraint_id = str(constraint.get("id") or "").strip()
        description = _constraint_body(constraint)
        if not constraint_id:
            errors.append(f"{label}: missing id")
            continue
        if not description:
            errors.append(f"{label}: missing description (or text)")
        hard_constraint_ids.append(constraint_id)

    for index, constraint in enumerate(soft_constraints):
        label = f"soft_constraints[{index}]"
        if not isinstance(constraint, dict):
            errors.append(f"{label}: must be an object with id and description (or text)")
            continue
        constraint_id = str(constraint.get("id") or "").strip()
        description = _constraint_body(constraint)
        if not constraint_id:
            errors.append(f"{label}: missing id")
            continue
        if not description:
            errors.append(f"{label}: missing description (or text)")

    subtask_id_counts: dict[str, int] = {}
    # Position map: declaration order of each subtask id in the blueprint's
    # `subtasks[]` array. Used to enforce the topological invariant — a
    # subtask may only depend on subtasks declared BEFORE it. Without this
    # check, a blueprint like ST-012 deps=[ST-027] passes the existing
    # "dep exists" guard but the runtime walker hits ST-012 long before
    # ST-027 is finished, producing a deadlock.
    subtask_position: dict[str, int] = {}
    for index, subtask in enumerate(subtasks):
        if not isinstance(subtask, dict):
            continue
        raw_subtask_id = subtask.get("id")
        if isinstance(raw_subtask_id, str) and re.fullmatch(r"ST-\d{3,}", raw_subtask_id):
            subtask_id_counts[raw_subtask_id] = subtask_id_counts.get(raw_subtask_id, 0) + 1
            # First occurrence wins for position (duplicates already flagged
            # below — position is a topology signal, not a dedup signal).
            subtask_position.setdefault(raw_subtask_id, index)

    subtask_ids = set(subtask_id_counts)
    duplicate_subtask_ids = {
        subtask_id for subtask_id, count in subtask_id_counts.items() if count > 1
    }
    oversized_subtasks: list[str] = []
    mixed_concern_subtasks: list[str] = []
    forward_dep_violations: list[str] = []

    for index, subtask in enumerate(subtasks):
        label = f"subtasks[{index}]"
        if not isinstance(subtask, dict):
            errors.append(f"{label}: must be an object")
            continue

        raw_subtask_id = subtask.get("id")
        if not isinstance(raw_subtask_id, str) or not re.fullmatch(r"ST-\d{3,}", raw_subtask_id):
            errors.append(f"{label}: id must match ST-NNN")
            subtask_id = label
        elif raw_subtask_id in duplicate_subtask_ids:
            errors.append(f"{raw_subtask_id}: duplicate subtask id")
            subtask_id = raw_subtask_id
        else:
            subtask_id = raw_subtask_id
        label = subtask_id

        dependencies = subtask.get("dependencies")
        if not isinstance(dependencies, list):
            errors.append(f"{label}: dependencies must be an array")
        else:
            for dependency in dependencies:
                if not isinstance(dependency, str) or not re.fullmatch(r"ST-\d{3,}", dependency):
                    errors.append(f"{label}: dependency {dependency!r} must match ST-NNN")
                    continue
                if dependency not in subtask_ids:
                    errors.append(f"{label}: dependency {dependency!r} points to unknown subtask")
                    continue
                # Self-dependency is a contract violation (subtask cannot
                # block on its own completion).
                if dependency == subtask_id:
                    errors.append(
                        f"{label}: dependency {dependency!r} is a self-reference"
                    )
                    continue
                # Topological invariant: dep must be declared earlier than
                # the dependent. Catches ST-012 deps=[ST-027] before the
                # runtime walker ever sees the blueprint.
                dep_pos = subtask_position.get(dependency)
                self_pos = subtask_position.get(subtask_id, index)
                if dep_pos is not None and dep_pos >= self_pos:
                    errors.append(
                        f"{label}: forward dependency on {dependency!r} (declared at "
                        f"subtasks[{dep_pos}] but {label} is at subtasks[{self_pos}]); "
                        "dependencies must reference only subtasks declared earlier — "
                        "reorder subtasks[] so deps come first"
                    )
                    forward_dep_violations.append(
                        f"{subtask_id}->{dependency}"
                    )

        expected_diff_size = str(subtask.get("expected_diff_size") or "").strip().lower()
        concern_type = str(subtask.get("concern_type") or "").strip().lower()
        validation_criteria = subtask.get("validation_criteria")

        if expected_diff_size not in DIFF_SIZE_LEVELS:
            errors.append(
                f"{label}: expected_diff_size must be one of {sorted(DIFF_SIZE_LEVELS)}"
            )
        elif expected_diff_size == "large":
            split_rationale = str(subtask.get("split_rationale") or "").strip()
            if not split_rationale:
                errors.append(
                    f"{label}: large subtasks require split_rationale or must be decomposed"
                )
                # Only flag in `oversized_subtasks` when there's no
                # rationale — a large subtask WITH split_rationale is an
                # acknowledged design choice, not a flag for the operator.
                oversized_subtasks.append(subtask_id)

        if concern_type not in SUBTASK_CONCERN_TYPES:
            errors.append(
                f"{label}: concern_type must be one of {sorted(SUBTASK_CONCERN_TYPES)}"
            )
        elif concern_type == "mixed":
            concern_justification = str(subtask.get("concern_justification") or "").strip()
            if not concern_justification:
                errors.append(
                    f"{label}: mixed concern_type requires concern_justification"
                )
                # Same treatment: explicitly justified mixed concerns are
                # acknowledged, not surfaced as flags.
                mixed_concern_subtasks.append(subtask_id)

        one_logical_step = subtask.get("one_logical_step")
        if one_logical_step is not True:
            errors.append(f"{label}: one_logical_step must be true")

        if not str(subtask.get("aag_contract") or "").strip():
            errors.append(f"{label}: missing aag_contract")

        if not isinstance(validation_criteria, list) or not validation_criteria:
            errors.append(f"{label}: validation_criteria must contain at least one item")
        elif not all(
            isinstance(item, str) and item.strip() for item in validation_criteria
        ):
            errors.append(f"{label}: validation_criteria items must be non-empty strings")
        elif len(validation_criteria) > 6:
            # Suppress the "consider splitting" hint when split_rationale is
            # present — the author already justified the size. Same logic
            # for affected_files >8: an explicit split_rationale acks scope.
            split_rationale = str(subtask.get("split_rationale") or "").strip()
            if not split_rationale:
                warnings.append(
                    f"{label}: has {len(validation_criteria)} validation criteria; "
                    "consider splitting if ownership is unclear "
                    "(or add split_rationale to ack the size)"
                )

        affected_files = subtask.get("affected_files")
        if isinstance(affected_files, list) and len(affected_files) > 8:
            split_rationale = str(subtask.get("split_rationale") or "").strip()
            if not split_rationale:
                warnings.append(
                    f"{label}: touches {len(affected_files)} files; verify this is still one "
                    "reviewable concern (or add split_rationale to ack the size)"
                )

        # Structural create-vs-modify (issue #167): `creates_files` is the
        # prose-free, canonical list of which affected_files this subtask
        # creates from scratch. It MUST be a subset of affected_files — a
        # created file is part of the mutation surface the scoped gates allow
        # the Actor to write. When the field is ABSENT the subtask is legacy
        # and the drift check below falls back to the deprecated
        # description-phrase heuristic; when PRESENT (even empty) the prose
        # heuristic is ignored and `creates_files` is authoritative.
        raw_creates_files = subtask.get("creates_files")
        creates_files_declared = raw_creates_files is not None
        creates_files_list: list[str] = []
        if creates_files_declared:
            if not isinstance(raw_creates_files, list) or not all(
                isinstance(p, str) for p in raw_creates_files
            ):
                errors.append(
                    f"{label}: creates_files must be an array of path strings"
                )
                creates_files_declared = False
            else:
                creates_files_list = [p for p in raw_creates_files if p.strip()]
                affected_set = (
                    {p for p in affected_files if isinstance(p, str)}
                    if isinstance(affected_files, list)
                    else set()
                )
                orphan_creates = [
                    p for p in creates_files_list if p not in affected_set
                ]
                if orphan_creates:
                    errors.append(
                        f"{label}: creates_files entries {orphan_creates!r} are not "
                        "listed in affected_files — a created file is part of the "
                        "mutation surface; add it to affected_files "
                        "(normalize_blueprint unions these automatically)"
                    )

        # affected_files drift check: warn when EVERY declared path is
        # missing from disk (decomposer hallucinated names that don't
        # exist anywhere — the canonical friction was ST-016 pointing at
        # services/sourcecraft.py when the actual class lives in
        # sourcecraft_publisher.py). Path is resolved against
        # CLAUDE_PROJECT_DIR / cwd. Files that don't yet exist for a
        # "create new file" subtask are common, so this is intentionally
        # warn-only and only triggers when ALL listed paths are missing
        # AND at least one path is declared (empty affected_files is the
        # decomposer's "no claim" signal and gets its own treatment in
        # the file-conflict checker).
        if isinstance(affected_files, list) and affected_files:
            string_files = [p for p in affected_files if isinstance(p, str) and p.strip()]
            if string_files:
                project_root_check = Path(
                    os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
                )
                project_root_resolved = project_root_check.resolve()
                # Cross-repo detection (computed FIRST so drift can dedup
                # against it): any path that resolves OUTSIDE the project
                # root (e.g. ``../LLM-memory/...``) means this subtask
                # plans to mutate a sibling repo. MAP gates can't cover
                # sibling repos.
                cross_repo_paths: list[str] = []
                for p in string_files:
                    try:
                        resolved = (project_root_check / p).resolve()
                    except (OSError, RuntimeError):
                        continue
                    try:
                        resolved.relative_to(project_root_resolved)
                    except ValueError:
                        cross_repo_paths.append(p)
                if cross_repo_paths:
                    warnings.append(
                        f"{label}: cross-repo affected_files detected — "
                        f"{cross_repo_paths!r} resolve outside the project root "
                        f"({project_root_resolved}). MAP gates (workflow-gate, "
                        "validate_mutation_boundary, hooks) do NOT cover sibling "
                        "repos. Either split the subtask into a sibling-repo "
                        "follow-up (recommended) or document the cross-repo "
                        "intent in the subtask description and acknowledge that "
                        "MAP cannot verify the change."
                    )
                # Drift detection: warn ONLY for the affected_files this
                # subtask is expected to MODIFY (not create) that are both
                # (a) missing on disk AND (b) not cross-repo paths. The
                # create-vs-modify split comes structurally from
                # `creates_files` (issue #167): created paths are
                # expected-absent and never count as drift. For legacy
                # blueprints that predate `creates_files`, fall back to the
                # deprecated description-phrase heuristic (whole-subtask
                # opt-out) so their behavior is unchanged.
                cross_repo_set = set(cross_repo_paths)
                local_files = [p for p in string_files if p not in cross_repo_set]
                if creates_files_declared:
                    create_set = set(creates_files_list)
                else:
                    description_text = subtask.get("description") or ""
                    description_str = (
                        description_text
                        if isinstance(description_text, str)
                        else ""
                    ).lower()
                    creates_new = bool(
                        re.search(
                            r"\b(creates? new|new file|introduces?|adds? new)\b",
                            description_str,
                        )
                    )
                    create_set = set(local_files) if creates_new else set()
                if local_files:
                    expected_present = [
                        p for p in local_files if p not in create_set
                    ]
                    missing_present = [
                        p for p in expected_present
                        if not (project_root_check / p).exists()
                    ]
                    if expected_present and missing_present == expected_present:
                        warnings.append(
                            f"{label}: affected_files drift — none of "
                            f"{expected_present!r} exist under {project_root_check}; "
                            "verify the decomposer didn't hallucinate file names. "
                            "If this subtask CREATES these files from scratch, list "
                            "them in the subtask's `creates_files` array (structural "
                            "— preferred over description phrases) so they are "
                            "treated as expected-absent."
                        )

    coverage_map = payload.get("coverage_map") or blueprint_body.get("coverage_map")
    if not isinstance(coverage_map, dict) or not coverage_map:
        errors.append(
            "coverage_map is required and must map each spec AC/invariant to an owning subtask"
        )
    else:
        for constraint_id in hard_constraint_ids:
            if constraint_id not in coverage_map:
                errors.append(
                    f"hard_constraints requirement {constraint_id!r} must appear in coverage_map"
                )
        for constraint in soft_constraints:
            if not isinstance(constraint, dict):
                continue
            constraint_id = str(constraint.get("id") or "").strip()
            if not constraint_id or constraint_id in coverage_map:
                continue
            tradeoff_rationale = str(constraint.get("tradeoff_rationale") or "").strip()
            if not tradeoff_rationale:
                # Forward-disclose the full requirement set so the user
                # doesn't have to round-trip the validator twice (first
                # error: "needs coverage_map OR rationale"; second
                # error after coverage_map fix: "owner VC must cite
                # [SC-N]"). Mention both branches up front.
                errors.append(
                    f"soft_constraints requirement {constraint_id!r} must either: "
                    "(a) include tradeoff_rationale (silences both this check and "
                    f"the [{constraint_id}] bracket-tag requirement), OR "
                    f"(b) appear in coverage_map mapped to an ST-NNN AND that "
                    f"subtask's validation_criteria must cite [{constraint_id}] "
                    "as a bracket tag — path (b) is two requirements, not one"
                )

        requirement_owners: dict[str, list[str]] = {}
        for requirement_id, owner in coverage_map.items():
            if not isinstance(owner, str):
                errors.append(
                    f"coverage_map[{requirement_id!r}] must point to a single ST-NNN subtask id"
                )
                continue
            if owner not in subtask_ids:
                errors.append(
                    f"coverage_map[{requirement_id!r}] points to unknown subtask {owner!r}"
                )
                continue
            requirement_owners.setdefault(owner, []).append(str(requirement_id))

        subtasks_by_id = {
            subtask.get("id"): subtask
            for subtask in subtasks
            if isinstance(subtask, dict) and isinstance(subtask.get("id"), str)
        }
        for owner, requirement_ids in requirement_owners.items():
            owner_subtask = subtasks_by_id.get(owner)
            validation_criteria = (
                owner_subtask.get("validation_criteria")
                if isinstance(owner_subtask, dict)
                else None
            )
            criterion_texts = [
                item for item in validation_criteria or [] if isinstance(item, str)
            ]
            for requirement_id in requirement_ids:
                lineage_tag = f"[{requirement_id}]"
                if not any(lineage_tag in item for item in criterion_texts):
                    errors.append(
                        f"{owner}: validation_criteria must cite coverage_map requirement "
                        f"{requirement_id!r} as {lineage_tag}"
                    )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "path": str(path),
        "subtask_count": len(subtasks),
        "oversized_subtasks": oversized_subtasks,
        "mixed_concern_subtasks": mixed_concern_subtasks,
        "forward_dep_violations": forward_dep_violations,
    }


def _topo_sort_subtasks(
    subtasks: list[object],
) -> tuple[Optional[list[dict[str, object]]], str]:
    """Stable topological sort of a blueprint ``subtasks[]`` list.

    Returns ``(sorted_subtasks, note)``. ``sorted_subtasks`` is ``None`` when
    the list cannot be reordered safely — a non-object entry, a missing or
    duplicate id, or a true dependency cycle — in which case the caller keeps
    the original order and lets ``validate_blueprint_contract`` report the
    underlying problem.

    The sort is *stable*: among subtasks whose declared dependencies are all
    already emitted, the one declared earliest in the original array is emitted
    first. Independent subtasks therefore keep their relative order and the
    rewrite is minimal — only forward-declared dependencies move earlier.
    """
    ids: list[str] = []
    by_id: dict[str, dict[str, object]] = {}
    for entry in subtasks:
        if not isinstance(entry, dict):
            return None, "subtasks contain a non-object entry; skipped reorder"
        sid = entry.get("id")
        if not isinstance(sid, str) or not sid:
            return None, "a subtask is missing a string id; skipped reorder"
        if sid in by_id:
            return None, f"duplicate subtask id {sid!r}; skipped reorder"
        ids.append(sid)
        by_id[sid] = entry

    id_set = set(ids)
    original_index = {sid: i for i, sid in enumerate(ids)}

    # Only intra-blueprint dependencies constrain ordering. Unknown deps and
    # self-references are ignored here — validate_blueprint_contract reports
    # those as hard errors; normalization never invents or rewrites them.
    deps: dict[str, set[str]] = {}
    for sid in ids:
        raw = by_id[sid].get("dependencies")
        dep_set: set[str] = set()
        if isinstance(raw, list):
            for dep in raw:
                if isinstance(dep, str) and dep in id_set and dep != sid:
                    dep_set.add(dep)
        deps[sid] = dep_set

    # Kahn's algorithm with a stable tie-break: among all nodes whose deps are
    # already emitted, pick the one with the smallest original index.
    emitted: list[str] = []
    emitted_set: set[str] = set()
    remaining = set(ids)
    while remaining:
        ready = sorted(
            (sid for sid in remaining if deps[sid] <= emitted_set),
            key=lambda s: original_index[s],
        )
        if not ready:
            # Nothing emittable -> a dependency cycle remains; leave untouched.
            return None, "dependency cycle detected; skipped reorder"
        nxt = ready[0]
        emitted.append(nxt)
        emitted_set.add(nxt)
        remaining.discard(nxt)

    return [by_id[sid] for sid in emitted], ""


def normalize_blueprint(
    blueprint_path: str = "",
    branch: Optional[str] = None,
    write: bool = True,
) -> dict[str, object]:
    """Deterministically repair the two self-consistency violations the
    task-decomposer routinely emits, so planning stays self-serve
    (``decompose -> normalize -> validate -> proceed``) without manual JSON
    surgery (issue #168):

      1. **Forward-dependency ordering** — stably topologically sort
         ``subtasks[]`` so every dependency is declared BEFORE its dependents.
         This satisfies the topological invariant that
         ``validate_blueprint_contract`` enforces (the runtime walker consumes
         subtasks in declaration order) without reordering by hand. A true
         dependency cycle is left untouched so the validator still reports it.
      2. **coverage_map bracket-tags** — for every ``coverage_map[req] = owner``
         whose owner subtask's ``validation_criteria`` does not already cite
         ``[req]``, append a traceability criterion that does. This is the
         auto-fix the validator's ``[AC-N]`` / ``[SC-N]`` lineage check expects.
      3. **creates_files ⊆ affected_files** — for every subtask whose
         ``creates_files`` (the structural create-vs-modify signal, issue #167)
         names a path missing from ``affected_files``, backfill that path into
         ``affected_files`` so a created file stays inside the mutation surface
         the scoped gates allow and ``validate_blueprint_contract`` does not
         hard-stop on the subset rule.

    Normalization is conservative: it never invents ``coverage_map`` ownership,
    never rewrites dependency edges, and never touches a soft constraint that
    relies on ``tradeoff_rationale`` instead of coverage. It only fixes the two
    mechanical drifts above; genuine semantic gaps (a hard constraint missing
    from ``coverage_map``, an unknown/cyclic dependency) remain for the
    validator to flag.

    Idempotent: a second call on already-normalized input reports
    ``changed: false`` and writes nothing.
    """
    branch_name = branch or get_branch_name()
    path = (
        Path(blueprint_path)
        if blueprint_path
        else get_branch_dir(branch_name) / "blueprint.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "error",
            "changed": False,
            "errors": [f"blueprint not found: {path}"],
            "path": str(path),
        }
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "changed": False,
            "errors": [f"cannot read blueprint {path}: {exc}"],
            "path": str(path),
        }

    if not isinstance(payload, dict):
        return {
            "status": "error",
            "changed": False,
            "errors": ["blueprint root must be a JSON object"],
            "path": str(path),
        }

    # Bind the nested lookup so the isinstance narrowing applies to the same
    # expression Pyright tracks (a re-invoked payload.get(...) would not narrow).
    nested_blueprint = payload.get("blueprint")
    blueprint_body = (
        nested_blueprint if isinstance(nested_blueprint, dict) else payload
    )
    subtasks = blueprint_body.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        return {
            "status": "error",
            "changed": False,
            "errors": ["blueprint must contain at least one subtask"],
            "path": str(path),
        }

    notes: list[str] = []

    # --- 1. Stable topological sort of subtasks[] ------------------------
    reordered, sort_note = _topo_sort_subtasks(subtasks)
    if sort_note:
        notes.append(sort_note)
    new_order = reordered if reordered is not None else subtasks
    order_changed = reordered is not None and [
        s.get("id") for s in reordered
    ] != [s.get("id") for s in subtasks if isinstance(s, dict)]

    # --- 2. Inject missing coverage_map bracket-tags ---------------------
    coverage_map = payload.get("coverage_map") or blueprint_body.get("coverage_map")
    subtasks_by_id = {
        s.get("id"): s
        for s in new_order
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    injected_tags: list[str] = []
    if isinstance(coverage_map, dict):
        for requirement_id, owner in coverage_map.items():
            if not isinstance(owner, str):
                continue
            owner_subtask = subtasks_by_id.get(owner)
            if not isinstance(owner_subtask, dict):
                continue
            tag = f"[{requirement_id}]"
            criteria = owner_subtask.get("validation_criteria")
            if not isinstance(criteria, list):
                criteria = []
                owner_subtask["validation_criteria"] = criteria
            if any(isinstance(c, str) and tag in c for c in criteria):
                continue
            criteria.append(
                f"VC{len(criteria) + 1} {tag}: satisfies coverage_map "
                f"requirement {requirement_id}"
            )
            injected_tags.append(f"{owner}:{tag}")

    # --- 3. Union creates_files into affected_files ----------------------
    # A created file is part of the mutation surface; the decomposer
    # occasionally lists a new path in `creates_files` but forgets to add it
    # to `affected_files`. Backfill deterministically so the subset rule in
    # validate_blueprint_contract does not hard-stop the self-serve loop.
    unioned_creates: list[str] = []
    for subtask in new_order:
        if not isinstance(subtask, dict):
            continue
        raw_creates = subtask.get("creates_files")
        if not isinstance(raw_creates, list):
            continue
        create_paths = [
            p for p in raw_creates if isinstance(p, str) and p.strip()
        ]
        if not create_paths:
            continue
        affected = subtask.get("affected_files")
        if not isinstance(affected, list):
            affected = []
            subtask["affected_files"] = affected
        affected_strs = {p for p in affected if isinstance(p, str)}
        for path_str in create_paths:
            if path_str not in affected_strs:
                affected.append(path_str)
                affected_strs.add(path_str)
                unioned_creates.append(f"{subtask.get('id')}:{path_str}")

    changed = order_changed or bool(injected_tags) or bool(unioned_creates)

    if order_changed:
        blueprint_body["subtasks"] = new_order

    if changed and write:
        _write_json_file(path, payload)

    return {
        "status": "ok",
        "changed": changed,
        "reordered": order_changed,
        "subtask_order": [s.get("id") for s in new_order if isinstance(s, dict)],
        "injected_coverage_tags": injected_tags,
        "unioned_creates_files": unioned_creates,
        "notes": notes,
        "path": str(path),
        "written": bool(changed and write),
    }


def record_test_contract_handoff(
    subtask_id: str,
    failing_test_command: str = "",
    test_files_csv: str = "",
    contract_summary: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Create test_handoff_<subtask>.json from an existing test_contract file."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    contract_path = branch_dir / f"test_contract_{subtask_id}.md"
    if not contract_path.exists():
        return {
            "status": "error",
            "message": f"Missing test contract: {contract_path}",
        }

    test_files = [
        item.strip()
        for item in (test_files_csv or "").split(",")
        if item.strip()
    ]
    handoff_payload = {
        "subtask_id": subtask_id,
        "status": "contract_ready",
        "contract_path": str(contract_path),
        "failing_test_command": failing_test_command or None,
        "test_files": test_files,
        "contract_summary": contract_summary or "No contract summary provided.",
        "notes": notes or "",
        "updated_at": _utc_timestamp(),
    }
    handoff_path = branch_dir / f"test_handoff_{subtask_id}.json"
    _write_json_file(handoff_path, handoff_payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "test_contract",
        "contract_ready",
        artifacts=[
            _artifact_ref(contract_path, "test-contract"),
            _artifact_ref(handoff_path, "test-handoff"),
        ],
        metadata={
            "subtask_id": subtask_id,
            "failing_test_command": handoff_payload["failing_test_command"],
            "test_files": test_files,
            "contract_summary": handoff_payload["contract_summary"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)

    return {
        "status": "success",
        "contract_path": str(contract_path),
        "handoff_path": str(handoff_path),
        "manifest_path": manifest_result["path"],
        "subtask_id": subtask_id,
    }


def get_branch_dir(branch: Optional[str] = None) -> Path:
    """Return .map/<branch> directory, auto-detecting branch when omitted."""
    if branch is None:
        branch = get_branch_name()
    return Path(f".map/{branch}")


def ensure_human_artifacts(branch: Optional[str] = None) -> dict:
    """Ensure core human-readable workflow artifacts exist for the branch."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)

    created = []
    existing = []
    for file_name, content in HUMAN_ARTIFACT_DEFAULTS.items():
        path = branch_dir / file_name
        if path.exists():
            existing.append(file_name)
            continue
        path.write_text(content, encoding="utf-8")
        created.append(file_name)

    return {
        "status": "success",
        "branch_dir": str(branch_dir),
        "created": created,
        "existing": existing,
    }


def next_numbered_artifact_path(
    prefix: str, branch: Optional[str] = None, extension: str = ".md"
) -> dict:
    """Return the next numbered artifact path like review-002.md."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}}){re.escape(extension)}$")
    next_index = 1
    for path in branch_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            next_index = max(next_index, int(match.group(1)) + 1)

    file_name = f"{prefix}-{next_index:03d}{extension}"
    return {
        "status": "success",
        "path": str(branch_dir / file_name),
        "file_name": file_name,
        "index": next_index,
    }


def append_session_log(
    phase: str,
    outcome: str,
    subtask_id: str = "",
    details: str = "",
    artifact_refs: Optional[list[str]] = None,
    branch: Optional[str] = None,
) -> dict:
    """Deprecated: session-log.md removed in pipeline simplification.

    Returns {"status": "deprecated", "path": "", "deprecated": True}.
    Kept for CLI backward compatibility — callers should stop using this function.
    """
    del phase, outcome, subtask_id, details, artifact_refs, branch
    return {"status": "deprecated", "path": "", "deprecated": True}


def _load_blueprint_for_coverage(branch_dir: Path) -> tuple[dict[str, object] | None, str]:
    """Load blueprint.json and normalize nested blueprint payloads for coverage reporting."""
    blueprint_path = branch_dir / "blueprint.json"
    try:
        payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "blueprint.json not found"
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"cannot read blueprint.json: {exc}"
    if not isinstance(payload, dict):
        return None, "blueprint.json must contain an object"
    blueprint = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    blueprint = cast(dict[str, object], blueprint)
    if "coverage_map" not in blueprint and isinstance(payload.get("coverage_map"), dict):
        blueprint = dict(blueprint)
        blueprint["coverage_map"] = payload["coverage_map"]
    return blueprint, ""


def _extract_acceptance_tags(text: object) -> set[str]:
    """Return bracketed acceptance/invariant tags found in artifact text."""
    if not isinstance(text, str) or not text:
        return set()
    return {match.group(1) for match in ACCEPTANCE_TAG_RE.finditer(text)}


def _collect_acceptance_evidence_texts(
    branch_dir: Path,
    extra_artifacts: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Collect review/verification artifact text that can prove acceptance tags."""
    evidence: dict[str, str] = {}
    for label, name in (
        ("verification_summary", "verification-summary.md"),
        ("qa", "qa-001.md"),
        ("pr_draft", "pr-draft.md"),
    ):
        text = _read_branch_artifact_text(branch_dir, name)
        if text:
            evidence[label] = text

    for prefix, label in (("code-review", "latest_code_review"),):
        latest = _collect_numbered_artifact(branch_dir, prefix)
        text = latest.get("sanitized_text") if isinstance(latest, dict) else None
        if isinstance(text, str) and text:
            evidence[label] = text

    for pattern, label_prefix in (
        ("test_contract_*.md", "test_contract"),
        ("test_handoff_*.json", "test_handoff"),
    ):
        try:
            matches = sorted(branch_dir.glob(pattern))
        except OSError:
            matches = []
        for path in matches:
            if not path.is_file():
                continue
            try:
                text = _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if text:
                evidence[f"{label_prefix}:{path.name}"] = text

    for label, text in (extra_artifacts or {}).items():
        if text:
            evidence[label] = _sanitize_for_json(text)
    return evidence


def build_acceptance_coverage_report(
    branch: Optional[str] = None,
    extra_artifacts: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """Summarize which blueprint acceptance tags have downstream evidence."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    blueprint, reason = _load_blueprint_for_coverage(branch_dir)
    if blueprint is None:
        return {
            "status": "missing_blueprint",
            "branch": branch_name,
            "reason": reason,
            "requirements": [],
            "summary": {"total": 0, "covered": 0, "missing": 0},
        }

    coverage_map = blueprint.get("coverage_map")
    subtasks = blueprint.get("subtasks")
    if not isinstance(coverage_map, dict) or not isinstance(subtasks, list):
        return {
            "status": "invalid_blueprint",
            "branch": branch_name,
            "reason": "blueprint requires coverage_map and subtasks for acceptance coverage",
            "requirements": [],
            "summary": {"total": 0, "covered": 0, "missing": 0},
        }

    subtasks_by_id = {
        subtask.get("id"): subtask
        for subtask in subtasks
        if isinstance(subtask, dict) and isinstance(subtask.get("id"), str)
    }
    evidence_texts = _collect_acceptance_evidence_texts(
        branch_dir, extra_artifacts=extra_artifacts
    )
    evidence_tags_by_source = {
        source: _extract_acceptance_tags(text)
        for source, text in evidence_texts.items()
    }

    requirements: list[dict[str, object]] = []
    for requirement_id, owner in sorted(coverage_map.items(), key=lambda item: str(item[0])):
        requirement = str(requirement_id)
        owner_id = str(owner) if isinstance(owner, str) else None
        owner_subtask = subtasks_by_id.get(owner_id) if owner_id else None
        criteria = (
            owner_subtask.get("validation_criteria")
            if isinstance(owner_subtask, dict)
            else []
        )
        criterion_texts = (
            [item for item in criteria if isinstance(item, str)]
            if isinstance(criteria, list)
            else []
        )
        validation_criteria_cited = any(
            f"[{requirement}]" in item for item in criterion_texts
        )
        evidence_artifacts = sorted(
            source
            for source, tags in evidence_tags_by_source.items()
            if requirement in tags
        )
        requirements.append(
            {
                "id": requirement,
                "owner": owner_id,
                "validation_criteria_cited": validation_criteria_cited,
                "evidence_artifacts": evidence_artifacts,
                "status": "covered" if evidence_artifacts else "missing_evidence",
            }
        )

    covered = sum(1 for item in requirements if item["status"] == "covered")
    missing = len(requirements) - covered
    tagged_evidence_sources = sorted(
        source for source, tags in evidence_tags_by_source.items() if tags
    )
    return {
        "status": "success",
        "branch": branch_name,
        "blueprint_path": str(branch_dir / "blueprint.json"),
        "evidence_sources": tagged_evidence_sources,
        "requirements": requirements,
        "summary": {"total": len(requirements), "covered": covered, "missing": missing},
    }


def _render_acceptance_coverage_markdown(report: Mapping[str, object]) -> str:
    """Render an acceptance coverage report into a compact Markdown section."""
    if report.get("status") != "success":
        reason = report.get("reason", "not available")
        return "## Acceptance Coverage\n- Status: not available\n- Reason: " + str(reason) + "\n"

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    total = summary.get("total", 0) if isinstance(summary, dict) else 0
    covered = summary.get("covered", 0) if isinstance(summary, dict) else 0
    missing = summary.get("missing", 0) if isinstance(summary, dict) else 0
    lines = [
        "## Acceptance Coverage",
        f"- Covered tags: {covered}/{total}",
        f"- Missing evidence: {missing}",
    ]
    requirements = report.get("requirements")
    if isinstance(requirements, list) and requirements:
        for item in requirements:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence_artifacts")
            if isinstance(evidence, list) and evidence:
                evidence_text = ", ".join(str(source) for source in evidence)
            else:
                evidence_text = "missing"
            lines.append(
                f"- [{item.get('status', 'unknown')}] {item.get('id', 'unknown')} "
                f"owned by {item.get('owner') or 'unknown'}; evidence: {evidence_text}"
            )
    return "\n".join(lines) + "\n"


def write_verification_summary(
    verdict: str,
    task_title: str = "",
    checks_run: str = "",
    findings: str = "",
    next_action: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a compact human-readable verification summary."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    summary_file = branch_dir / "verification-summary.md"

    content = (
        "# Verification Summary\n\n"
        f"- Branch: {branch_name}\n"
        f"- Task: {task_title or '[not provided]'}\n"
        f"- Verdict: {verdict}\n\n"
        "## Checks Run\n"
        f"{checks_run or '- [not recorded]'}\n\n"
        "## Findings\n"
        f"{findings or '- [not recorded]'}\n\n"
        "## Next Action\n"
        f"{next_action or '- [not recorded]'}\n"
    )
    coverage_report = build_acceptance_coverage_report(
        branch_name, extra_artifacts={"verification_summary": content}
    )
    content += "\n" + _render_acceptance_coverage_markdown(coverage_report)
    prior_stage_report = build_prior_stage_consumption_report(
        "implementation", branch_name
    )
    content += "\n" + _render_prior_stage_consumption_markdown(prior_stage_report)
    summary_file.write_text(content, encoding="utf-8")
    return {
        "status": "success",
        "path": str(summary_file),
        "acceptance_coverage": coverage_report,
        "prior_stage_consumption": prior_stage_report,
    }


def _count_step_entries(value: object) -> int:
    """Count step entries across legacy list and per-subtask dict shapes."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        total = 0
        for item in value.values():
            total += len(item) if isinstance(item, list) else 1
        return total
    return 0


def _as_dict(value: object) -> dict[str, object]:
    """Return value when it is a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    """Best-effort integer coercion for counters loaded from JSON artifacts."""
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_DONE_RESULT_STATUSES_FOR_COMPLETION = {
    "valid",
    "completed",
    "done",
    "skipped",
    "no-op",
}
_DONE_PHASE_STATUSES_FOR_COMPLETION = {
    "completed",
    "skipped",
    "no-op",
    "complete",
}


def _state_subtask_coverage_complete(state: dict[str, object]) -> bool:
    """Return True iff every subtask in subtask_sequence has a "done"-class
    signal recorded (subtask_results entry OR subtask_phases marker).

    Mirrors the orchestrator's _completed_subtask_ids_for_deps logic. Used
    by _derive_terminal_status so a stuck cursor (ST-033 friction) no
    longer makes write_run_health_report report ``pending`` when 51/51
    entries actually exist.
    """
    sequence_value = state.get("subtask_sequence")
    if not isinstance(sequence_value, list) or not sequence_value:
        return False
    results_value = state.get("subtask_results")
    results = results_value if isinstance(results_value, dict) else {}
    phases_value = state.get("subtask_phases")
    phases = phases_value if isinstance(phases_value, dict) else {}
    completed: set[str] = set()
    for sid, entry in results.items():
        if not isinstance(sid, str) or not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if not isinstance(status, str) or status.lower() in _DONE_RESULT_STATUSES_FOR_COMPLETION:
            completed.add(sid)
    for sid, phase in phases.items():
        if isinstance(sid, str) and isinstance(phase, str) and phase.lower() in _DONE_PHASE_STATUSES_FOR_COMPLETION:
            completed.add(sid)
    return all(isinstance(sid, str) and sid in completed for sid in sequence_value)


def _derive_terminal_status(state: dict[str, object]) -> str:
    """Derive a stable terminal status from step_state.json when not explicit."""
    existing = str(state.get("terminal_status") or "").strip().lower()
    if existing in RUN_HEALTH_TERMINAL_STATUSES:
        return existing

    workflow_status = str(state.get("workflow_status") or "").strip().upper()
    current_phase = str(state.get("current_step_phase") or "").strip().upper()
    if (
        workflow_status in {"COMPLETE", "COMPLETED", "WORKFLOW_COMPLETE"}
        or current_phase == "COMPLETE"
    ):
        return "complete"
    if workflow_status in {"BLOCKED", "MAX_RETRIES"}:
        return "blocked"
    if workflow_status in {"SUPERSEDED"}:
        return "superseded"
    if workflow_status in {"WONT_DO", "WON'T_DO"}:
        return "won't_do"
    # Cursor-independent fallback: if every subtask has a recorded result
    # (Monitor success OR mark_subtask_complete no-op), treat the run as
    # complete even when current_step_phase still points at a stale stub.
    # This closes the ST-033 friction where cursor sat on a deferred-stub
    # forever while 51/51 entries were recorded.
    if _state_subtask_coverage_complete(state):
        return "complete"
    return "pending"


def _artifact_health_entry(path: Path, kind: str) -> dict[str, object]:
    """Return compact presence metadata for a workflow artifact."""
    try:
        size_bytes = path.stat().st_size
        present = True
    except OSError:
        size_bytes = 0
        present = False

    return {
        "kind": kind,
        "path": str(path),
        "present": present,
        "size_bytes": size_bytes,
    }


def _run_health_artifact_inventory(
    branch_dir: Path, branch: str
) -> dict[str, dict[str, object]]:
    """Collect the artifact set that proves workflow resumability/reviewability."""
    return {
        "step_state": _artifact_health_entry(branch_dir / "step_state.json", "state"),
        "artifact_manifest": _artifact_health_entry(
            branch_dir / "artifact_manifest.json", "manifest"
        ),
        "verification_summary": _artifact_health_entry(
            branch_dir / "verification-summary.md", "verification"
        ),
        "qa": _artifact_health_entry(branch_dir / "qa-001.md", "qa"),
        "pr_draft": _artifact_health_entry(branch_dir / "pr-draft.md", "pr-draft"),
        "review_bundle": _artifact_health_entry(
            branch_dir / "review-bundle.json", "review-bundle"
        ),
        "learning_handoff": _artifact_health_entry(
            branch_dir / "learning-handoff.json", "learning-handoff"
        ),
        "task_plan": _artifact_health_entry(
            branch_dir / f"task_plan_{branch}.md", "task-plan"
        ),
        "blueprint": _artifact_health_entry(branch_dir / "blueprint.json", "blueprint"),
        "active_issues": _artifact_health_entry(
            branch_dir / "active-issues.json", "active-issues"
        ),
        "known_issues": _artifact_health_entry(
            branch_dir / "known-issues.json", "known-issues"
        ),
        "retry_quarantine": _artifact_health_entry(
            branch_dir / RETRY_QUARANTINE_ARTIFACT_NAME, "retry-quarantine"
        ),
    }


def write_run_health_report(
    workflow: str = "map-efficient",
    terminal_status: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Write a machine-readable workflow health report for diagnosis/resume.

    The report intentionally summarizes existing branch artifacts instead of
    inventing a new workflow state source. Callers can run it at normal closeout,
    after a blocked run, or during resume diagnostics.
    """
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    step_state_path = branch_dir / "step_state.json"
    state = _read_json_file(step_state_path) or {}

    status = (terminal_status or "").strip().lower() or _derive_terminal_status(state)
    if status not in RUN_HEALTH_TERMINAL_STATUSES:
        return {
            "status": "error",
            "message": f"Invalid terminal_status: {terminal_status}",
        }

    completed_steps = state.get("completed_steps")
    pending_steps = state.get("pending_steps")
    retry_count = _as_int(state.get("retry_count"))
    subtask_retry_counts = _as_dict(state.get("subtask_retry_counts"))
    guard_rework_counts = _as_dict(state.get("guard_rework_counts"))
    retry_isolation_status = _as_dict(state.get("retry_isolation_status"))
    hook_injection = _as_dict(state.get("hook_injection"))
    artifact_inventory = _run_health_artifact_inventory(branch_dir, branch_name)

    payload: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": _utc_timestamp(),
        "workflow": (workflow or state.get("workflow") or "map-workflow"),
        "branch": branch_name,
        "terminal_status": status,
        "current_step_id": state.get("current_step_id") or None,
        "current_step_phase": state.get("current_step_phase") or None,
        "current_subtask_id": state.get("current_subtask_id") or None,
        "completed_step_count": _count_step_entries(completed_steps),
        "pending_step_count": _count_step_entries(pending_steps),
        "artifacts": artifact_inventory,
        "resiliency_signals": {
            "hook_injection": hook_injection
            or {"status": "unknown", "reason": "not recorded"},
            "hook_injection_counts": _as_dict(state.get("hook_injection_counts")),
            "retry_count": retry_count,
            "max_retries": _as_int(state.get("max_retries")),
            "subtask_retry_counts": subtask_retry_counts,
            "max_subtask_retry_count": max(
                [_as_int(value) for value in subtask_retry_counts.values()] or [0]
            ),
            "clean_retry_count": _as_int(state.get("clean_retry_count")),
            "contaminated_retry_count": _as_int(state.get("contaminated_retry_count")),
            "retry_isolation_status": retry_isolation_status,
            "guard_rework_counts": guard_rework_counts,
            "predictor_called": bool(state.get("predictor_called")),
            "predictor_skipped": bool(state.get("predictor_skipped")),
            "final_verifier_executed": bool(
                state.get("final_verifier_executed")
                or artifact_inventory["verification_summary"]["present"]
            ),
        },
    }

    report_path = branch_dir / "run_health_report.json"
    _write_json_file(report_path, payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "run_health",
        "ready",
        artifacts=[_artifact_ref(report_path, "run-health-report")],
        metadata={
            "terminal_status": status,
            "workflow": payload["workflow"],
            "current_step_phase": payload["current_step_phase"],
            "hook_injection_status": cast(
                Mapping[str, object],
                payload["resiliency_signals"],
            )["hook_injection"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)
    return {
        "status": "success",
        "path": str(report_path),
        "manifest_path": manifest_result["path"],
        "terminal_status": status,
    }


def _load_run_health_schema_validator() -> tuple[
    object, Optional[Callable[[object, object], tuple[bool, list[str]]]]
]:
    """Return optional package schema validator for generated-project installs."""
    try:
        import importlib as _importlib

        _schemas_mod = sys.modules.get("mapify_cli.schemas")
        if _schemas_mod is None:
            _schemas_mod = _importlib.import_module("mapify_cli.schemas")
        return (
            getattr(_schemas_mod, "RUN_HEALTH_REPORT_SCHEMA", None),
            getattr(_schemas_mod, "validate_artifact", None),
        )
    except ImportError:
        return (None, None)


def _artifact_present(report: Mapping[str, object], key: str) -> bool:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return False
    entry = artifacts.get(key)
    return isinstance(entry, Mapping) and bool(entry.get("present"))


def _validate_run_health_report_shape(report: Mapping[str, object]) -> list[str]:
    """Validate the stable run-health contract without optional dependencies."""
    errors: list[str] = []
    unexpected_keys = set(report) - RUN_HEALTH_REQUIRED_KEYS - {
        "current_step_id",
        "current_step_phase",
        "current_subtask_id",
    }
    for key in sorted(RUN_HEALTH_REQUIRED_KEYS - set(report)):
        errors.append(f"missing required field: {key}")
    for key in sorted(unexpected_keys):
        errors.append(f"unexpected field: {key}")

    terminal_status = str(report.get("terminal_status") or "").strip().lower()
    if terminal_status not in RUN_HEALTH_TERMINAL_STATUSES:
        errors.append(f"invalid terminal_status: {terminal_status or '[missing]'}")

    for key in ("schema_version", "generated_at", "workflow", "branch"):
        if key in report and not isinstance(report.get(key), str):
            errors.append(f"{key} must be a string")
    for key in ("completed_step_count", "pending_step_count"):
        value = report.get(key)
        if key in report and not _is_non_negative_int(value):
            errors.append(f"{key} must be a non-negative integer")

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("artifacts must be an object")
    else:
        for key in sorted(RUN_HEALTH_ARTIFACT_KEYS - set(artifacts)):
            errors.append(f"artifacts.{key} is required")
        for key, value in artifacts.items():
            if not isinstance(value, Mapping):
                errors.append(f"artifacts.{key} must be an object")
                continue
            for field in ("kind", "path"):
                if not isinstance(value.get(field), str):
                    errors.append(f"artifacts.{key}.{field} must be a string")
            if not isinstance(value.get("present"), bool):
                errors.append(f"artifacts.{key}.present must be a boolean")
            size_bytes = value.get("size_bytes")
            if not _is_non_negative_int(size_bytes):
                errors.append(f"artifacts.{key}.size_bytes must be a non-negative integer")

    signals = report.get("resiliency_signals")
    if not isinstance(signals, Mapping):
        errors.append("resiliency_signals must be an object")
    else:
        for key in sorted(RUN_HEALTH_SIGNAL_KEYS - set(signals)):
            errors.append(f"resiliency_signals.{key} is required")
        hook = signals.get("hook_injection")
        if not isinstance(hook, Mapping):
            errors.append("resiliency_signals.hook_injection must be an object")
        elif not isinstance(hook.get("status"), str):
            errors.append("resiliency_signals.hook_injection.status must be a string")
        for key in (
            "hook_injection_counts",
            "subtask_retry_counts",
            "guard_rework_counts",
            "retry_isolation_status",
        ):
            if key in signals and not isinstance(signals.get(key), Mapping):
                errors.append(f"resiliency_signals.{key} must be an object")
        for key in (
            "retry_count",
            "max_retries",
            "max_subtask_retry_count",
            "clean_retry_count",
            "contaminated_retry_count",
        ):
            value = signals.get(key)
            if key in signals and not _is_non_negative_int(value):
                errors.append(f"resiliency_signals.{key} must be a non-negative integer")
        for key in ("predictor_called", "predictor_skipped", "final_verifier_executed"):
            if key in signals and not isinstance(signals.get(key), bool):
                errors.append(f"resiliency_signals.{key} must be a boolean")

    return errors


def validate_run_health_report(
    report_path: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Validate run_health_report.json for CI/operator closeout checks."""
    branch_name = branch or get_branch_name()
    path = Path(report_path) if report_path else get_branch_dir(branch_name) / "run_health_report.json"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"run health report not found: {path}"],
            "warnings": [],
        }
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"cannot read run health report: {exc}"],
            "warnings": [],
        }

    if not isinstance(report, dict):
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": ["run health report must be a JSON object"],
            "warnings": [],
        }

    errors.extend(_validate_run_health_report_shape(report))

    schema, validate_artifact = _load_run_health_schema_validator()
    if schema is not None and validate_artifact is not None:
        is_valid, schema_errors = validate_artifact(report, schema)
        if not is_valid:
            errors.extend(f"schema: {error}" for error in schema_errors)
    else:
        warnings.append("schema validator unavailable; semantic checks only")

    terminal_status = str(report.get("terminal_status") or "").strip().lower()
    pending_step_count = _as_int(report.get("pending_step_count"))
    signals = _as_dict(report.get("resiliency_signals"))
    hook_injection = _as_dict(signals.get("hook_injection"))
    hook_status = str(hook_injection.get("status") or "").strip().lower()
    hook_reason = str(hook_injection.get("reason") or "").strip()
    retry_count = _as_int(signals.get("retry_count"))
    max_retries = _as_int(signals.get("max_retries"))
    max_subtask_retry_count = _as_int(signals.get("max_subtask_retry_count"))
    final_verifier_executed = bool(signals.get("final_verifier_executed"))
    verification_present = _artifact_present(report, "verification_summary")

    if terminal_status == "complete":
        if pending_step_count:
            errors.append("complete report must not have pending steps")
        if not (final_verifier_executed or verification_present):
            errors.append(
                "complete report must include a final verifier signal or verification summary artifact"
            )

    if max_retries > 0 and retry_count > max_retries:
        errors.append(f"retry_count {retry_count} exceeds max_retries {max_retries}")
    if max_retries > 0 and max_subtask_retry_count > max_retries:
        errors.append(
            f"max_subtask_retry_count {max_subtask_retry_count} exceeds max_retries {max_retries}"
        )

    if hook_status in {"", "unknown", "skipped", "degraded", "error"} and not hook_reason:
        errors.append(
            "hook_injection degradation must include a reason when status is unknown, skipped, degraded, or error"
        )

    if terminal_status == "pending" and pending_step_count == 0:
        warnings.append("pending report has no pending steps")
    if terminal_status in {"blocked", "superseded"} and not _artifact_present(report, "step_state"):
        warnings.append(f"{terminal_status} report has no step_state artifact")

    valid = not errors
    return {
        "status": "success" if valid else "error",
        "valid": valid,
        "path": str(path),
        "terminal_status": terminal_status,
        "errors": errors,
        "warnings": warnings,
    }


def build_retry_quarantine(
    subtask_id: str,
    retry_count: int,
    monitor_feedback: str,
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Write retry_quarantine.json for clean-room retry in non-orchestrated flows."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    path = branch_dir / RETRY_QUARANTINE_ARTIFACT_NAME
    existing = _read_json_file(path) or {}
    quarantines = existing.get("quarantines")
    if not isinstance(quarantines, list):
        quarantines = []
    quarantines = [
        item
        for item in quarantines
        if not (
            isinstance(item, Mapping)
            and item.get("subtask_id") == subtask_id
            and item.get("retry_count") == retry_count
        )
    ]
    summary = _shorten_retry_text(monitor_feedback) or "See latest Monitor feedback artifact."
    quarantines.append(
        {
            "subtask_id": subtask_id,
            "retry_count": retry_count,
            "isolation_mode": "clean_retry",
            "failed_attempt": f"retry_{retry_count}",
            "monitor_rejection_summary": summary,
            "rejected_assumptions": [],
            "do_not_repeat": [summary],
            "preserved_constraints": [
                "Preserve current blueprint hard_constraints, coverage_map tags, validation_criteria, and mutation boundaries."
            ],
            "required_evidence": [
                "Read blueprint.json or the current task contract before editing.",
                "Read the latest Monitor feedback artifact before choosing a new approach.",
                "Cite passing focused checks or explain the blocker before returning to Monitor.",
            ],
            "source_artifacts": [
                {"path": str(branch_dir / "step_state.json"), "kind": "step-state"},
                {"path": str(branch_dir / "blueprint.json"), "kind": "blueprint"},
                {
                    "path": str(branch_dir / f"task_plan_{branch_name}.md"),
                    "kind": "task-plan",
                },
            ],
        }
    )
    payload = {
        "schema_version": "1.0",
        "branch": branch_name,
        "updated_at": _utc_timestamp(),
        "quarantines": quarantines,
    }
    _write_json_file(path, payload)
    validation = validate_retry_quarantine(str(path), branch_name)
    return {
        "status": "success" if validation.get("valid") else "error",
        "valid": validation.get("valid", False),
        "path": str(path),
        "validation": validation,
    }


def validate_retry_quarantine(
    quarantine_path: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Validate retry_quarantine.json before a clean Actor retry begins."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    path = Path(quarantine_path) if quarantine_path else branch_dir / RETRY_QUARANTINE_ARTIFACT_NAME
    errors: list[str] = []
    warnings: list[str] = []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"retry quarantine not found: {path}"],
            "warnings": [],
        }
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"cannot read retry quarantine: {exc}"],
            "warnings": [],
        }

    if not isinstance(payload, Mapping):
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": ["retry quarantine must be a JSON object"],
            "warnings": [],
        }

    if payload.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if not isinstance(payload.get("branch"), str) or not payload.get("branch"):
        errors.append("branch must be a non-empty string")
    quarantines = payload.get("quarantines")
    if not isinstance(quarantines, list) or not quarantines:
        errors.append("quarantines must be a non-empty array")
        quarantines = []

    required_fields = {
        "subtask_id",
        "retry_count",
        "isolation_mode",
        "failed_attempt",
        "monitor_rejection_summary",
        "rejected_assumptions",
        "do_not_repeat",
        "preserved_constraints",
        "required_evidence",
        "source_artifacts",
    }
    for index, item in enumerate(quarantines):
        prefix = f"quarantines[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        for field_name in sorted(required_fields - set(item)):
            errors.append(f"{prefix}.{field_name} is required")
        if not isinstance(item.get("subtask_id"), str) or not item.get("subtask_id"):
            errors.append(f"{prefix}.subtask_id must be a non-empty string")
        retry_count = item.get("retry_count")
        if type(retry_count) is not int or retry_count < 2:
            errors.append(f"{prefix}.retry_count must be an integer >= 2")
        if item.get("isolation_mode") != "clean_retry":
            errors.append(f"{prefix}.isolation_mode must be clean_retry")
        if not isinstance(item.get("failed_attempt"), str) or not item.get(
            "failed_attempt"
        ):
            errors.append(f"{prefix}.failed_attempt must be non-empty")
        if not isinstance(item.get("monitor_rejection_summary"), str) or not item.get(
            "monitor_rejection_summary"
        ):
            errors.append(f"{prefix}.monitor_rejection_summary must be non-empty")
        for array_field in ("rejected_assumptions", "do_not_repeat"):
            value = item.get(array_field)
            if not isinstance(value, list) or not all(
                isinstance(entry, str) for entry in value
            ):
                errors.append(f"{prefix}.{array_field} must be an array of strings")
        preserved_constraints = item.get("preserved_constraints")
        if (
            not isinstance(preserved_constraints, list)
            or not preserved_constraints
            or not all(isinstance(entry, str) for entry in preserved_constraints)
        ):
            errors.append(f"{prefix}.preserved_constraints must be a non-empty array")
        required_evidence = item.get("required_evidence")
        if (
            not isinstance(required_evidence, list)
            or not required_evidence
            or not all(isinstance(entry, str) for entry in required_evidence)
        ):
            errors.append(f"{prefix}.required_evidence must be a non-empty array")
        source_artifacts = item.get("source_artifacts")
        if not isinstance(source_artifacts, list) or not source_artifacts:
            errors.append(f"{prefix}.source_artifacts must be a non-empty array")
        else:
            for source_index, source in enumerate(source_artifacts):
                source_prefix = f"{prefix}.source_artifacts[{source_index}]"
                if not isinstance(source, Mapping):
                    errors.append(f"{source_prefix} must be an object")
                    continue
                if not isinstance(source.get("path"), str) or not source.get("path"):
                    errors.append(f"{source_prefix}.path must be a non-empty string")
                if not isinstance(source.get("kind"), str) or not source.get("kind"):
                    errors.append(f"{source_prefix}.kind must be a non-empty string")
            kinds = {
                str(source.get("kind"))
                for source in source_artifacts
                if isinstance(source, Mapping)
            }
            if "step-state" not in kinds:
                errors.append(f"{prefix}.source_artifacts must include step-state")
            if "blueprint" not in kinds:
                errors.append(f"{prefix}.source_artifacts must include blueprint")

    valid = not errors
    if valid:
        manifest = load_artifact_manifest(branch_name)
        _set_manifest_stage(
            manifest,
            "retry_quarantine",
            "ready",
            artifacts=[_artifact_ref(path, "retry-quarantine")],
            metadata={"quarantine_count": len(quarantines)},
        )
        manifest_result = save_artifact_manifest(manifest, branch_name)
        manifest_path = manifest_result["path"]
    else:
        manifest_path = str(branch_dir / "artifact_manifest.json")

    return {
        "status": "success" if valid else "error",
        "valid": valid,
        "path": str(path),
        "manifest_path": manifest_path,
        "errors": errors,
        "warnings": warnings,
    }


def write_pr_draft(
    summary: str = "",
    validation: str = "",
    risks_follow_up: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a compact PR draft artifact for the current branch."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    pr_file = branch_dir / "pr-draft.md"

    content = (
        "# PR Draft\n\n"
        "## Summary\n"
        f"{summary or '- [not recorded]'}\n\n"
        "## Validation\n"
        f"{validation or '- [not recorded]'}\n\n"
        "## Risks / Follow-up\n"
        f"{risks_follow_up or '- [not recorded]'}\n"
    )
    pr_file.write_text(content, encoding="utf-8")
    return {"status": "success", "path": str(pr_file)}


def write_plan_review(
    summary: str = "",
    high: str = "",
    medium: str = "",
    low: str = "",
    resolved_since_previous: str = "",
    open_concerns: str = "",
    recommendation: str = "needs-revision",
    branch: Optional[str] = None,
) -> dict:
    """Write the next staged planning review artifact."""
    recommendation = recommendation.strip().lower()
    if recommendation not in GATE_VERDICTS:
        return {
            "status": "error",
            "message": f"Invalid recommendation: {recommendation}",
        }

    artifact = next_numbered_artifact_path("plan-review", branch)
    review_file = Path(artifact["path"])
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_number = artifact["index"]

    content = (
        f"# Plan Review {review_number:03d}\n\n"
        "## Summary\n"
        f"{summary or '- [not recorded]'}\n\n"
        "## High\n"
        f"{high or '(None)'}\n\n"
        "## Medium\n"
        f"{medium or '(None)'}\n\n"
        "## Low\n"
        f"{low or '(None)'}\n\n"
        "## Resolved Since Previous Review\n"
        f"{resolved_since_previous or '(None)'}\n\n"
        "## Open Concerns\n"
        f"{open_concerns or '(None)'}\n\n"
        "## Recommendation\n"
        f"- {recommendation}\n"
    )
    review_file.write_text(content, encoding="utf-8")
    return {
        "status": "success",
        "path": str(review_file),
        "file_name": review_file.name,
        "index": review_number,
    }


def write_stage_gate(
    stage: str,
    verdict: str,
    source_artifact: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a machine-readable gate artifact for a workflow stage."""
    verdict = verdict.strip().lower()
    if verdict not in GATE_VERDICTS:
        return {"status": "error", "message": f"Invalid verdict: {verdict}"}

    normalized_stage = stage.strip().lower().replace("_", "-")
    gate_file = get_branch_dir(branch) / f"{normalized_stage}-gate.json"
    gate_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": normalized_stage,
        "verdict": verdict,
        "source_artifact": source_artifact or None,
        "updated_at": datetime.now().isoformat(),
        "notes": notes or "",
    }
    gate_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {"status": "success", "path": str(gate_file), "verdict": verdict}


def ensure_active_issues_file(branch: Optional[str] = None) -> dict:
    """Ensure active-issues.json exists for current unresolved issue set."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    issues_file = branch_dir / "active-issues.json"
    if not issues_file.exists():
        payload = {**ACTIVE_ISSUES_DEFAULT, "updated_at": datetime.now().isoformat()}
        issues_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        return {"status": "success", "path": str(issues_file), "created": True}
    return {"status": "success", "path": str(issues_file), "created": False}


def replace_active_issues(
    stage: str,
    source_artifact: str,
    issues_text: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Replace active unresolved issue set from newline-delimited bullets/text."""
    ensure_active_issues_file(branch)
    issues_file = get_branch_dir(branch) / "active-issues.json"

    issue_lines = []
    for raw in issues_text.splitlines():
        line = raw.strip()
        if not line or line in {"(None)", "- (None)"}:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        issue_lines.append(line)

    issues = [
        {
            "id": f"{stage[:3].upper()}-{index:03d}",
            "stage": stage,
            "source_artifact": source_artifact,
            "status": "open",
            "summary": line,
        }
        for index, line in enumerate(issue_lines, start=1)
    ]
    payload = {
        "updated_at": datetime.now().isoformat(),
        "issues": issues,
    }
    issues_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {"status": "success", "path": str(issues_file), "count": len(issues)}


def _sanitize_for_json(text: str) -> str:
    """Remove every C0 control character (U+0000-U+001F) and U+007F from text.

    Python's ``json.dumps`` does escape these correctly for strict JSON
    output, but the bundle is then piped through bash command substitution
    (``BUNDLE=$(... step_runner ...)``) and consumed by ``jq``. Bash
    expansion does not preserve byte-perfect roundtrip for embedded
    literal control characters in all locales, so jq receives a string
    with raw controls and rejects it with::

        jq: parse error: Invalid string: control characters from U+0000
        through U+001F must be escaped at line N, column M

    Stripping at source is the only robust fix. We additionally
    normalise newline variants (``\\r\\n``, ``\\r``) into spaces to keep
    word boundaries when multi-line artifact bodies are flattened into a
    single bundle field.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ").replace("\t", " ")
    return re.sub(r"[\x00-\x1f\x7f]", "", text)


def get_review_section_order(mode: str, seed: int | None = None) -> list[str]:
    """Return canonical/reverse/seeded-shuffle section list for /map-review.

    AC-1: 'default' returns canonical; 'reverse-sections' returns reversed;
    'shuffle-sections' uses random.Random(seed).
    AC-2: Same seed -> identical order; different seeds may differ.
    EC-9: Unknown mode -> ValueError listing allowed modes.
    """
    if mode not in REVIEW_VALID_MODES:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {REVIEW_VALID_MODES}"
        )
    sections = list(REVIEW_SECTION_IDS)
    if mode == "default":
        return sections
    if mode == "reverse-sections":
        return list(reversed(sections))
    # shuffle-sections
    if seed is not None and seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    rng = random.Random(seed)
    rng.shuffle(sections)
    return sections


def default_shuffle_seed(branch: str, commit_sha: str | None) -> int:
    """Derive a stable per-branch shuffle seed.

    AC-3: stable for fixed inputs across processes and machines. Uses sha256
    (not built-in hash() — which is randomized per process via PYTHONHASHSEED
    and breaks reproducibility). commit_sha=None falls back to
    sha256(branch + '|detached').
    """
    key = f"{branch}|detached" if commit_sha is None else f"{branch}|{commit_sha}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def compare_review_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate ordering-variant review runs with strict-wins verdict + drift detection.

    INV-4 strict-wins: final_verdict = max over runs of rank BLOCK>REVISE>PROCEED.
    INV-5: drift NEVER auto-escalates beyond the strictest individual verdict.
    EC-10: intra-run issue order irrelevant (set-based overlap).
    EC-11 partial-failure: len(runs)==1 -> compare_status='partial_failure', drift_detected=True.
    EC-13: drift_summary truncated to 2000 chars then sanitized (INV-8).
    """
    _RANK: dict[str, int] = {"PROCEED": 0, "REVISE": 1, "BLOCK": 2}

    if not isinstance(runs, list) or len(runs) == 0:
        raise ValueError("runs must be a non-empty list")

    # Partial failure (EC-11): exactly one run survived
    if len(runs) == 1:
        only = runs[0]
        verdict = only.get("verdict", "PROCEED")
        if verdict not in _RANK:
            raise ValueError(f"unknown verdict {verdict!r}; expected one of {list(_RANK)}")
        raw_issues: Iterable[object] = cast(Iterable[object], only.get("primary_issues") or [])
        issues = [str(i) for i in raw_issues]
        summary_raw = (
            "one ordering run failed; drift could not be confirmed; verdict is provisional"
        )
        return {
            "drift_detected": True,
            "verdicts": [verdict],
            "shared_primary_issues": issues,
            "unique_primary_issues": {str(only.get("ordering_label", "run_0")): []},
            "drift_summary": _sanitize_for_json(summary_raw[:2000]),
            "final_verdict": verdict,
            "compare_status": "partial_failure",
        }

    # Multi-run path
    verdicts: list[str] = []
    issue_sets: list[set[str]] = []
    labels: list[str] = []
    for idx, run in enumerate(runs):
        v = run.get("verdict")
        if v not in _RANK:
            raise ValueError(f"unknown verdict {v!r}; expected one of {list(_RANK)}")
        verdicts.append(str(v))
        run_issues: Iterable[object] = cast(Iterable[object], run.get("primary_issues") or [])
        issue_sets.append({str(i) for i in run_issues})
        labels.append(str(run.get("ordering_label", f"run_{idx}")))

    # Strict-wins (AC-7, INV-4)
    final_verdict = max(verdicts, key=lambda x: _RANK[x])

    # Shared / unique issue computation (EC-10: set-based, order-agnostic)
    shared_set: set[str] = set.intersection(*issue_sets) if issue_sets else set()
    shared_primary_issues = sorted(shared_set)
    unique_primary_issues: dict[str, list[str]] = {}
    for label, s in zip(labels, issue_sets):
        unique_primary_issues[label] = sorted(s - shared_set)

    # Drift detection (AC-6): verdict mismatch OR Jaccard overlap < 0.5
    verdict_mismatch = len(set(verdicts)) > 1
    union_set: set[str] = set.union(*issue_sets) if issue_sets else set()
    overlap = (len(shared_set) / len(union_set)) if union_set else 1.0
    overlap_low = overlap < 0.5
    drift_detected = verdict_mismatch or overlap_low

    # Drift summary (EC-13: truncate BEFORE sanitize; INV-8: sanitize after)
    summary_raw_opt: str | None
    if drift_detected:
        reasons: list[str] = []
        if verdict_mismatch:
            reasons.append(f"verdicts disagree: {verdicts}")
        if overlap_low:
            reasons.append(f"primary-issue overlap {overlap:.2f} < 0.50")
        summary_raw_opt = "; ".join(reasons)
    else:
        summary_raw_opt = None

    drift_summary: str | None = (
        _sanitize_for_json(summary_raw_opt[:2000]) if summary_raw_opt is not None else None
    )

    return {
        "drift_detected": drift_detected,
        "verdicts": verdicts,
        "shared_primary_issues": shared_primary_issues,
        "unique_primary_issues": unique_primary_issues,
        "drift_summary": drift_summary,
        "final_verdict": final_verdict,
        "compare_status": None,
    }


# Modes accepted by record_review_ordering (broader than REVIEW_VALID_MODES because
# 'compare-orderings' is set at the SKILL.md aggregator layer, not the helper layer).
_ORDERING_RECORD_MODES: tuple[str, ...] = (
    "default",
    "reverse-sections",
    "shuffle-sections",
    "compare-orderings",
)


def record_review_ordering(
    mode: str,
    seed: int | None = None,
    runs: list[dict[str, object]] | None = None,
    drift: dict[str, object] | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    """Stage an ordering payload for the next create_review_bundle call (INV-10).

    Stores the payload in the module-level ``_PENDING_REVIEW_ORDERING`` singleton,
    which create_review_bundle() consumes and clears in a single atomic read.

    CRITICAL: this function MUST NOT call ``_set_manifest_stage``,
    ``save_artifact_manifest``, ``load_artifact_manifest``, or ``_write_json_file``.
    The single-writer rule (INV-10) reserves all manifest writes for
    create_review_bundle().
    """
    global _PENDING_REVIEW_ORDERING

    if mode not in _ORDERING_RECORD_MODES:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {_ORDERING_RECORD_MODES}"
        )

    runs_payload: list[dict[str, object]] = (
        [dict(run) for run in runs] if runs is not None else []
    )

    # Drift sub-payload: pull fields from the compare_review_runs result dict
    drift_detected = bool((drift or {}).get("drift_detected", False))
    drift_summary_raw = (drift or {}).get("drift_summary")
    final_verdict = (drift or {}).get("final_verdict")
    compare_status = (drift or {}).get("compare_status")

    # Sanitize string fields (INV-8). Truncate drift_summary to 2000 chars first (EC-13).
    drift_summary: str | None
    if drift_summary_raw is None:
        drift_summary = None
    else:
        drift_summary = _sanitize_for_json(str(drift_summary_raw)[:2000])

    final_verdict_str: str | None = (
        _sanitize_for_json(str(final_verdict)) if final_verdict is not None else None
    )
    compare_status_str: str | None = (
        _sanitize_for_json(str(compare_status)) if compare_status is not None else None
    )

    payload: dict[str, object] = {
        "mode": mode,
        "seed": seed,
        "runs": runs_payload,
        "drift_detected": drift_detected,
        "drift_summary": drift_summary,
        "final_verdict": final_verdict_str,
        "compare_status": compare_status_str,
    }

    # Stage to BOTH the module-level dict (for in-process pytest tests) AND a
    # branch-scoped file (for the real cross-subprocess SKILL.md workflow).
    # See PENDING_ORDERING_FILENAME comment.
    _PENDING_REVIEW_ORDERING = payload
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    pending_path: Path | None = None
    if branch_name:
        try:
            branch_dir = get_branch_dir(branch_name)
            branch_dir.mkdir(parents=True, exist_ok=True)
            pending_path = branch_dir / PENDING_ORDERING_FILENAME
            pending_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pending_path = None

    return {
        "status": "ok",
        "staged": True,
        "mode": mode,
        "branch": branch_name,
        "pending_path": str(pending_path) if pending_path else None,
        # legacy field for callers that referenced the old API
        "branch_in": branch,
    }


def _read_branch_artifact_text(branch_dir: Path, name: str) -> str:
    """Read a branch artifact, treating untouched managed placeholders as empty."""
    path = branch_dir / name
    if not path.exists():
        return ""
    try:
        content = _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""

    default_content = HUMAN_ARTIFACT_DEFAULTS.get(name)
    if default_content and content.strip() == default_content.strip():
        return ""
    return content


def build_handoff_bundle(branch: Optional[str] = None) -> dict:
    """Build a compact handoff bundle from branch-scoped human artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    ensure_human_artifacts(branch_name)

    verification = _read_branch_artifact_text(branch_dir, "verification-summary.md")
    qa = _read_branch_artifact_text(branch_dir, "qa-001.md")
    active_issues = _read_branch_artifact_text(branch_dir, "active-issues.json")
    verification_gate = _read_branch_artifact_text(branch_dir, "verification-gate.json")
    review_path = next_numbered_artifact_path("code-review", branch_name)
    latest_review_index = max(0, review_path["index"] - 1)
    latest_review_name = (
        f"code-review-{latest_review_index:03d}.md" if latest_review_index > 0 else ""
    )
    latest_review = (
        _read_branch_artifact_text(branch_dir, latest_review_name)
        if latest_review_name
        else ""
    )

    summary = []
    if verification:
        summary.append("- Verification summary available")
    if verification_gate:
        summary.append("- Verification gate recorded")
    if latest_review:
        summary.append(f"- Latest review: {latest_review_name}")
    if latest_review:
        summary.append("- Code review history available")
    if active_issues:
        summary.append("- Active unresolved issues tracked")

    validation = []
    if verification:
        validation.append(verification.strip())
    if qa:
        validation.append(qa.strip())
    if verification_gate:
        validation.append(verification_gate.strip())

    risks = []
    if latest_review:
        risks.append(latest_review.strip())
    if active_issues:
        risks.append(active_issues.strip())

    return {
        "status": "success",
        "branch": branch_name,
        "summary": "\n".join(summary) or "- [not recorded]",
        "validation": "\n\n".join(validation) or "- [not recorded]",
        "risks_follow_up": "\n\n".join(risks) or "- [not recorded]",
    }


def build_review_handoff(branch: Optional[str] = None) -> dict:
    """Build final review context from planning, execution, and verification artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)

    plan_review_next = next_numbered_artifact_path("plan-review", branch_name)
    latest_plan_review_index = max(0, plan_review_next["index"] - 1)
    latest_plan_review_name = (
        f"plan-review-{latest_plan_review_index:03d}.md"
        if latest_plan_review_index > 0
        else ""
    )
    code_review_next = next_numbered_artifact_path("code-review", branch_name)
    latest_code_review_index = max(0, code_review_next["index"] - 1)
    latest_code_review_name = (
        f"code-review-{latest_code_review_index:03d}.md"
        if latest_code_review_index > 0
        else ""
    )

    payload = {
        "status": "success",
        "branch": branch_name,
        "plan_review_path": latest_plan_review_name or None,
        "code_review_path": latest_code_review_name or None,
        "verification_summary_path": "verification-summary.md"
        if (branch_dir / "verification-summary.md").exists()
        else None,
        "qa_path": "qa-001.md" if (branch_dir / "qa-001.md").exists() else None,
        "pr_draft_path": "pr-draft.md"
        if (branch_dir / "pr-draft.md").exists()
        else None,
        "active_issues_path": "active-issues.json"
        if (branch_dir / "active-issues.json").exists()
        else None,
        "plan_review": _read_branch_artifact_text(branch_dir, latest_plan_review_name)
        if latest_plan_review_name
        else None,
        "code_review": _read_branch_artifact_text(branch_dir, latest_code_review_name)
        if latest_code_review_name
        else None,
        "verification_summary": _read_branch_artifact_text(
            branch_dir, "verification-summary.md"
        ),
        "qa": _read_branch_artifact_text(branch_dir, "qa-001.md"),
        "pr_draft": _read_branch_artifact_text(branch_dir, "pr-draft.md"),
        "active_issues": _read_branch_artifact_text(branch_dir, "active-issues.json")
        or None,
    }

    # Surface ordering metadata for /map-learn consumers (AC-13).
    # Read review-bundle.json if present; fall back to safe defaults (EC-7)
    # when the file is absent, unreadable, or from a legacy bundle without
    # the "ordering" key.  No exception must escape — handoff must always
    # succeed regardless of ordering availability.
    bundle_path = branch_dir / "review-bundle.json"
    ordering: dict[str, object] = {}
    if bundle_path.exists():
        try:
            with bundle_path.open(encoding="utf-8") as fh:
                bundle_data = json.load(fh)
            if isinstance(bundle_data, dict):
                raw_ordering = bundle_data.get("ordering")
                if isinstance(raw_ordering, dict):
                    ordering = raw_ordering
        except (OSError, ValueError):
            ordering = {}

    payload["review_order_mode"] = str(ordering.get("mode", "default")) if ordering else "default"
    payload["review_order_seed"] = ordering.get("seed") if ordering else None
    payload["drift_detected"] = bool(ordering.get("drift_detected", False)) if ordering else False
    payload["compare_status"] = ordering.get("compare_status") if ordering else None

    return payload


_REVIEW_BUNDLE_TRUNCATE_CHARS = 4000
"""Max sanitized characters to embed per artifact text field.

Reviewers need enough context to assess the artifact, not a full copy.
Files larger than this threshold are truncated; ``truncated: true`` is
recorded so the reviewer knows to open the full file on disk.
"""


def _collect_numbered_artifact(
    branch_dir: Path,
    prefix: str,
) -> dict:
    """Scan branch_dir for ``<prefix>-NNN.md`` files and return the highest one.

    Returns a dict with keys: ``present``, ``path`` (str or None),
    ``index`` (int or None), ``sanitized_text`` (str or None),
    ``truncated`` (bool, omitted when not applicable), ``reason`` (str or None).
    """
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}})\.md$")
    best_index = 0
    best_name = ""
    try:
        for dir_entry in branch_dir.iterdir():
            m = pattern.match(dir_entry.name)
            if m:
                idx = int(m.group(1))
                if idx > best_index:
                    best_index = idx
                    best_name = dir_entry.name
    except OSError:
        pass

    if not best_name:
        return {
            "present": False,
            "path": None,
            "index": None,
            "sanitized_text": None,
            "reason": "none recorded",
        }

    full_path = branch_dir / best_name
    raw = _read_branch_artifact_text(branch_dir, best_name)
    entry: dict = {
        "present": True,
        "path": str(full_path),
        "index": best_index,
    }
    if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
        entry["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
        entry["truncated"] = True
    else:
        entry["sanitized_text"] = raw or None
        entry["truncated"] = False
    entry["reason"] = None
    return entry


def _collect_multi_artifacts(
    branch_dir: Path,
    glob_pattern: str,
) -> list[dict]:
    """Collect all files matching glob_pattern and return a list of artifact entries.

    Each entry: ``{path, sanitized_text, truncated}``.
    Returns an empty list when no files match.
    """
    results = []
    try:
        for entry in sorted(branch_dir.glob(glob_pattern)):
            if not entry.is_file():
                continue
            raw = _sanitize_for_json(
                entry.read_text(encoding="utf-8", errors="replace")
            )
            item: dict = {"path": str(entry)}
            if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
                item["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
                item["truncated"] = True
            else:
                item["sanitized_text"] = raw or None
                item["truncated"] = False
            results.append(item)
    except OSError:
        pass
    return results


def _is_soft_stub_text(name: str, text: str) -> bool:
    """Detect whether artifact text is a soft stub (writer output with no real data).

    Differs from the strict ``HUMAN_ARTIFACT_DEFAULTS`` byte-match: this catches the case
    where ``write_verification_summary`` / ``write_pr_draft`` were called with empty args,
    which produces section bodies of ``- [not recorded]`` while the branch name and/or
    verdict line are dynamically interpolated. Reviewers should treat such artifacts as
    absent (``present=false``) rather than as filled content.

    Note: the input ``text`` has been flattened by ``_sanitize_for_json`` (newlines and
    tabs collapsed to spaces), so the section markers are matched in their post-sanitize
    form (e.g., ``## Summary - [not recorded]`` rather than ``## Summary\n- [not recorded]``).
    """
    if not text:
        return False
    if name == "pr-draft.md":
        return (
            text.lstrip().startswith("# PR Draft")
            and "## Summary - [not recorded]" in text
            and "## Validation - [not recorded]" in text
            and "## Risks / Follow-up - [not recorded]" in text
        )
    if name == "verification-summary.md":
        return (
            text.lstrip().startswith("# Verification Summary")
            and "## Checks Run - [not recorded]" in text
            and "## Findings - [not recorded]" in text
            and "## Next Action - [not recorded]" in text
        )
    return False


def _fixed_artifact_entry(branch_dir: Path, name: str, kind: str) -> dict:
    """Return a single artifact entry for a fixed-name file.

    Keys: ``present``, ``path``, ``sanitized_text`` (or None), ``truncated``
    (omitted if not applicable), ``reason`` (or None), ``kind``.
    """
    full_path = branch_dir / name
    if not full_path.exists():
        return {
            "present": False,
            "path": None,
            "sanitized_text": None,
            "kind": kind,
            "reason": "not found",
        }
    raw = _read_branch_artifact_text(branch_dir, name)
    # Stub detection: ``raw`` is "" when content matches ``HUMAN_ARTIFACT_DEFAULTS[name]``
    # (initial stub from ``ensure_human_artifacts``). ``_is_soft_stub_text`` catches the
    # case where the writer was called with empty args, producing a placeholder body.
    if not raw and HUMAN_ARTIFACT_DEFAULTS.get(name) is not None:
        return {
            "present": False,
            "path": str(full_path),
            "sanitized_text": None,
            "kind": kind,
            "reason": "stub: matches initial placeholder",
        }
    if raw and _is_soft_stub_text(name, raw):
        return {
            "present": False,
            "path": str(full_path),
            "sanitized_text": None,
            "kind": kind,
            "reason": "stub: writer emitted placeholder body",
        }
    entry: dict = {
        "present": True,
        "path": str(full_path),
        "kind": kind,
        "reason": None,
    }
    if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
        entry["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
        entry["truncated"] = True
    else:
        entry["sanitized_text"] = raw or None
        entry["truncated"] = False
    return entry


def _bundle_review_handoff_text_fields(handoff: dict) -> dict:
    """Extract only the sanitized text content fields from build_review_handoff output."""
    return {
        "plan_review": handoff.get("plan_review"),
        "code_review": handoff.get("code_review"),
        "verification_summary": handoff.get("verification_summary") or None,
        "qa": handoff.get("qa") or None,
        "pr_draft": handoff.get("pr_draft") or None,
        "active_issues": handoff.get("active_issues"),
    }


def _bundle_pr_handoff_fields(bundle: dict) -> dict:
    """Extract PR handoff summary fields from build_handoff_bundle output."""
    return {
        "summary": bundle.get("summary", "- [not recorded]"),
        "validation": bundle.get("validation", "- [not recorded]"),
        "risks_follow_up": bundle.get("risks_follow_up", "- [not recorded]"),
    }


def _render_bundle_markdown(result: dict) -> str:
    """Render the review bundle as a human-readable Markdown document."""
    branch = result.get("branch", "unknown")
    generated_at = result.get("generated_at", "")
    artifacts = result.get("artifacts", {})
    code_state = result.get("code_state", {})
    review_handoff = result.get("review_handoff", {})
    pr_handoff = result.get("pr_handoff", {})
    acceptance_coverage = result.get("acceptance_coverage", {})
    prior_stage_consumption = result.get("prior_stage_consumption", {})

    lines = [
        f"# Review Bundle — `{branch}`",
        "",
        f"Generated: {generated_at}",
        f"Bundle JSON: `{result.get('bundle_path_json', '')}`",
        "",
    ]

    # Missing artifacts section (INV-4: every absent artifact listed)
    missing = []
    for key, val in artifacts.items():
        if key in ("test_handoffs", "test_contracts"):
            if isinstance(val, list) and not val:
                missing.append(f"- `{key}`: none recorded")
        elif isinstance(val, dict) and not val.get("present", True):
            reason = val.get("reason", "not found")
            missing.append(f"- `{key}`: {reason}")

    if missing:
        lines += ["## Missing Artifacts", ""]
        lines += missing
        lines += [""]

    # Artifact inventory
    lines += ["## Artifact Inventory", ""]
    for key, val in artifacts.items():
        if key in ("test_handoffs", "test_contracts"):
            count = len(val) if isinstance(val, list) else 0
            lines.append(f"- **{key}**: {count} file(s)")
        elif isinstance(val, dict):
            status = "present" if val.get("present") else "MISSING"
            path = val.get("path") or "—"
            lines.append(f"- **{key}** [{status}]: `{path}`")
    lines += [""]

    # Code state
    lines += ["## Code State", ""]
    cs_status = code_state.get("status", "unknown")
    if cs_status == "success":
        lines.append(f"- Git ref: `{code_state.get('git_ref', 'unknown')}`")
        lines.append(f"- Branch: `{code_state.get('branch', 'unknown')}`")
        files = code_state.get("files_changed", [])
        lines.append(f"- Files changed: {len(files)}")
        diff_stat = code_state.get("diff_stat", "")
        if diff_stat:
            lines.append(f"- Diff stat: {diff_stat[:200]}")
    else:
        lines.append(f"- Status: {cs_status}")
        reason = code_state.get("reason", "")
        if reason:
            lines.append(f"- Reason: {reason}")
    lines += [""]

    # Review handoff text summaries
    lines += ["## Review Handoff Context", ""]
    for field in ("plan_review", "code_review", "verification_summary", "qa", "pr_draft", "active_issues"):
        val = review_handoff.get(field)
        if val:
            label = field.replace("_", " ").title()
            lines.append(f"### {label}")
            lines.append("")
            lines.append(val[:500] + ("…" if len(val) > 500 else ""))
            lines.append("")

    # Acceptance coverage
    if isinstance(acceptance_coverage, dict):
        lines.append(_render_acceptance_coverage_markdown(acceptance_coverage).rstrip())
        lines.append("")

    # Prior-stage consumption
    if isinstance(prior_stage_consumption, dict):
        lines.append(_render_prior_stage_consumption_markdown(prior_stage_consumption).rstrip())
        lines.append("")

    # PR handoff
    lines += ["## PR Handoff Summary", ""]
    lines.append(pr_handoff.get("summary", "- [not recorded]"))
    lines += [""]

    return "\n".join(lines)


def create_review_bundle(branch: Optional[str] = None) -> dict:
    """Write a durable reviewer-facing bundle under .map/<branch>/.

    Collects all branch-scoped artifacts into a structured inventory,
    sanitizes text content, and writes both ``review-bundle.json`` and
    ``review-bundle.md``.  Missing optional artifacts are recorded
    explicitly (INV-4) rather than silently omitted.  Control characters
    are stripped via ``_sanitize_for_json`` so the JSON file remains
    parseable by downstream tools (INV-8).
    """
    # ``get_branch_name`` already sanitizes; explicit ``branch`` callers must be
    # sanitized too so e.g. ``feat/foo`` lands at ``.map/feat-foo/`` instead of a
    # nested ``.map/feat/foo/`` directory.
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_timestamp()

    bundle_json_path = branch_dir / "review-bundle.json"
    bundle_md_path = branch_dir / "review-bundle.md"

    # --- Artifact inventory ---
    fixed_artifacts: dict[str, dict] = {
        "spec": _fixed_artifact_entry(
            branch_dir, f"spec_{branch_name}.md", "spec"
        ),
        "task_plan": _fixed_artifact_entry(
            branch_dir, f"task_plan_{branch_name}.md", "task_plan"
        ),
        "blueprint": _fixed_artifact_entry(
            branch_dir, "blueprint.json", "blueprint"
        ),
        "verification_summary": _fixed_artifact_entry(
            branch_dir, "verification-summary.md", "verification_summary"
        ),
        "qa": _fixed_artifact_entry(
            branch_dir, "qa-001.md", "qa"
        ),
        "pr_draft": _fixed_artifact_entry(
            branch_dir, "pr-draft.md", "pr_draft"
        ),
        "active_issues": _fixed_artifact_entry(
            branch_dir, "active-issues.json", "active_issues"
        ),
        "artifact_manifest": _fixed_artifact_entry(
            branch_dir, "artifact_manifest.json", "artifact_manifest"
        ),
        "run_health_report": _fixed_artifact_entry(
            branch_dir, "run_health_report.json", "run_health_report"
        ),
    }

    latest_plan_review = _collect_numbered_artifact(branch_dir, "plan-review")
    latest_code_review = _collect_numbered_artifact(branch_dir, "code-review")

    test_handoffs = _collect_multi_artifacts(branch_dir, "test_handoff_*.json")
    test_contracts = _collect_multi_artifacts(branch_dir, "test_contract_*.md")

    artifacts: dict = {}
    artifacts.update(fixed_artifacts)
    artifacts["latest_plan_review"] = latest_plan_review
    artifacts["latest_code_review"] = latest_code_review
    artifacts["test_handoffs"] = test_handoffs
    artifacts["test_contracts"] = test_contracts

    # --- Code state ---
    try:
        code_state = snapshot_code_state(branch_name)
    except Exception as exc:
        code_state = {"status": "unavailable", "reason": str(exc)}

    # --- Review handoff context (text fields only) ---
    try:
        review_handoff_raw = build_review_handoff(branch_name)
        review_handoff = _bundle_review_handoff_text_fields(review_handoff_raw)
    except Exception as exc:
        review_handoff = {
            "plan_review": None,
            "code_review": None,
            "verification_summary": None,
            "qa": None,
            "pr_draft": None,
            "active_issues": None,
            "_error": str(exc),
        }

    # --- PR handoff summary ---
    try:
        pr_bundle_raw = build_handoff_bundle(branch_name)
        pr_handoff = _bundle_pr_handoff_fields(pr_bundle_raw)
    except Exception as exc:
        pr_handoff = {
            "summary": "- [not recorded]",
            "validation": "- [not recorded]",
            "risks_follow_up": "- [not recorded]",
            "_error": str(exc),
        }

    acceptance_coverage = build_acceptance_coverage_report(branch_name)
    prior_stage_consumption = build_prior_stage_consumption_report(
        "review", branch_name, code_state=code_state
    )

    # --- Ordering payload (INV-10 single-writer staging) ---
    # Consume from BOTH the file (cross-subprocess durable path) and the module
    # dict (in-process pytest path), preferring whichever is present. Clear both
    # immediately to prevent stale reuse on a second call.
    global _PENDING_REVIEW_ORDERING
    pending_in_memory = _PENDING_REVIEW_ORDERING
    _PENDING_REVIEW_ORDERING = None

    pending_file_path = branch_dir / PENDING_ORDERING_FILENAME
    pending_from_file: dict[str, object] | None = None
    if pending_file_path.exists():
        try:
            with pending_file_path.open(encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                pending_from_file = loaded
        except (OSError, ValueError):
            pending_from_file = None
        finally:
            # Delete unconditionally — staging is one-shot per AC-4 / EC-11 semantics
            try:
                pending_file_path.unlink()
            except OSError:
                pass

    pending = pending_in_memory or pending_from_file
    if pending is None:
        # EC-7 default: normal single-pass review with no ordering staged
        ordering_payload: dict[str, object] = {
            "mode": "default",
            "seed": None,
            "runs": [],
            "drift_detected": False,
            "drift_summary": None,
            "final_verdict": None,
            "compare_status": None,
        }
    else:
        ordering_payload = pending

    result: dict = {
        "status": "success",
        "branch": branch_name,
        "bundle_path_json": str(bundle_json_path),
        "bundle_path_md": str(bundle_md_path),
        "generated_at": generated_at,
        "artifacts": artifacts,
        "code_state": code_state,
        "review_handoff": review_handoff,
        "pr_handoff": pr_handoff,
        "acceptance_coverage": acceptance_coverage,
        "prior_stage_consumption": prior_stage_consumption,
        "ordering": ordering_payload,
    }

    # Soft schema validation: warn on drift but still write the bundle.
    # Uses optional ``mapify_cli.schemas`` import (graceful fallback if the package is
    # absent in a standalone .map/ install). On validation failure the errors are recorded
    # on the result under ``schema_validation_error`` and the manifest stage status is
    # downgraded from "ready" to "warn" below.
    try:
        import importlib as _importlib

        _schemas_mod = sys.modules.get("mapify_cli.schemas")
        if _schemas_mod is None:
            _schemas_mod = _importlib.import_module("mapify_cli.schemas")
        _review_bundle_schema = getattr(_schemas_mod, "REVIEW_BUNDLE_SCHEMA", None)
        _validate_artifact_fn = getattr(_schemas_mod, "validate_artifact", None)
        if _review_bundle_schema is not None and _validate_artifact_fn is not None:
            _is_valid, _errors = _validate_artifact_fn(result, _review_bundle_schema)
            if not _is_valid:
                result["schema_validation_error"] = _errors
    except ImportError:
        pass

    # Write JSON bundle (ensure_ascii=True for jq-safe output per INV-8)
    bundle_json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    # Write human-readable Markdown bundle
    bundle_md_path.write_text(
        _render_bundle_markdown(result),
        encoding="utf-8",
    )

    # --- Manifest integration (AC-4 / INV-5) ---
    # Both bundle files are written; now record them in artifact_manifest.json.
    # Failure here must NOT prevent the caller from receiving the bundle result.
    try:
        manifest = load_artifact_manifest(branch_name)
        artifacts_list = [
            _artifact_ref(bundle_json_path, "review-bundle"),
            _artifact_ref(bundle_md_path, "review-bundle"),
        ]

        # Count present/missing entries from the inventory already built above.
        present_count = 0
        missing_count = 0
        for key, val in artifacts.items():
            if key in ("test_handoffs", "test_contracts"):
                present_count += len(val) if isinstance(val, list) else 0
            elif isinstance(val, dict):
                if val.get("present"):
                    present_count += 1
                else:
                    missing_count += 1

        metadata: dict = {
            "bundle_status": result["status"],
            "selected_artifacts": present_count,
            "missing_artifacts": missing_count,
            "branch": branch_name,
            "generated_at": result["generated_at"],
            "ordering": ordering_payload,
            "acceptance_coverage": acceptance_coverage.get("summary")
            if isinstance(acceptance_coverage, dict)
            else {},
            "prior_stage_consumption": prior_stage_consumption.get("summary")
            if isinstance(prior_stage_consumption, dict)
            else {},
        }
        stage_status = (
            "warn"
            if "schema_validation_error" in result
            or not prior_stage_consumption.get("valid", False)
            else "ready"
        )
        _set_manifest_stage(
            manifest, "review", stage_status, artifacts=artifacts_list, metadata=metadata
        )
        save_result = save_artifact_manifest(manifest, branch_name)
        result["manifest_status"] = {"status": stage_status, "path": save_result["path"]}
    except Exception as exc:
        result["manifest_status"] = {"status": "error", "reason": str(exc)}

    return result


# ---------------------------------------------------------------------------
# AGENT_OUTPUT_SCHEMAS — single source of truth for review-agent output shapes
# (ST-001). REVIEW_PROMPT_SPECS and detect_truncated_agent_output both derive
# from this; do NOT maintain a second hand-written copy elsewhere.
#
# Authoritative field list: .claude/skills/map-review/SKILL.md lines 75-111.
#
# required_keys: UNCONDITIONAL top-level keys only. Conditional fields
#   (sibling_comparison, landmine_evidence) are EXCLUDED so that a valid
#   output omitting only a conditional field is never flagged as truncated.
#
# skeleton: mode-agnostic full output shape. Every SKILL.md gate field
#   is present literally so json.dumps(skeleton) can serve as the
#   <output_schema> block in the rendered prompt. Conditional fields are
#   present as descriptive placeholder strings.
# ---------------------------------------------------------------------------
class AgentOutputSchema(TypedDict):
    required_keys: tuple[str, ...]
    skeleton: dict[str, object]


AGENT_OUTPUT_SCHEMAS: dict[str, AgentOutputSchema] = {
    "monitor": {
        "required_keys": (
            "evidence",
            "valid",
            "summary",
            "verdict",
            "issues",
            "passed_checks",
            "failed_checks",
        ),
        "skeleton": {
            "evidence": [
                {
                    "file_path": "<string>",
                    "line_range": "<string>",
                    "quote": "<string>",
                    "relevance": "<string>",
                }
            ],
            "valid": "<boolean>",
            "summary": "<string>",
            "verdict": "<'approved' | 'needs_revision' | 'rejected'>",
            "issues": [
                {
                    "severity": "<'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'>",
                    "category": "<string>",
                    "description": "<string>",
                    "file_path": "<string>",
                    "line_range": "<string>",
                    "suggestion": "<string>",
                    "was_present_before_pr": "<boolean — required; True => pre-existing tech debt>",
                    "reach_evidence": "<string — required when severity >= MEDIUM: grep:<pattern>:<line> | test_fail:<name> | linter:<tool>:<line>>",
                    "sibling_comparison": "<object — required when mode=sibling-aware: {sibling_path, equivalent_lines, divergences}>",
                }
            ],
            "passed_checks": ["<string>"],
            "failed_checks": ["<string>"],
        },
    },
    "predictor": {
        "required_keys": (
            "evidence",
            "risk_assessment",
            "predicted_state",
            "confidence",
        ),
        "skeleton": {
            "evidence": [
                {
                    "file_path": "<string>",
                    "line_range": "<string>",
                    "quote": "<string>",
                    "relevance": "<string>",
                }
            ],
            "risk_assessment": "<'low' | 'medium' | 'high' | 'critical'>",
            "predicted_state": {
                "affected_components": ["<string>"],
                "breaking_changes": [
                    {"type": "<string>", "description": "<string>", "mitigation": "<string>"}
                ],
                "required_updates": ["<string>"],
            },
            "confidence": {
                "score": "<float 0.0-1.0>",
            },
            "landmine_evidence": "<string — required when raising latent-bug/future-failure claims: failing test, static-analysis line, or grep showing unreachable path is reachable>",
        },
    },
    "evaluator": {
        "required_keys": (
            "evidence",
            "scores",
            "overall_score",
            "recommendation",
            "strengths",
            "weaknesses",
            "next_steps",
            "monitor_severity_audit",
        ),
        "skeleton": {
            "evidence": [
                {
                    "file_path": "<string>",
                    "line_range": "<string>",
                    "quote": "<string>",
                    "relevance": "<string>",
                }
            ],
            "scores": {
                "functionality": "<int 1-10>",
                "completeness": "<int 1-10>",
                "security": "<int 1-10>",
                "code_quality": "<int 1-10>",
                "testability": "<int 1-10>",
                "performance": "<int 1-10>",
                "simplicity": "<int 1-10>",
            },
            "overall_score": "<float 1.0-10.0>",
            "recommendation": "<'proceed' | 'improve' | 'reconsider'>",
            "strengths": ["<string>"],
            "weaknesses": ["<string>"],
            "next_steps": ["<string>"],
            "monitor_severity_audit": [
                {
                    "monitor_issue_index": "<int>",
                    "agreed_severity": "<string>",
                    "rationale": "<string>",
                }
            ],
        },
    },
    # Actor is not a review-prompt role (it has no REVIEW_PROMPT_SPECS entry),
    # but its output schema lives here so build_json_retry_prompt and
    # detect_truncated_agent_output can serve the map-efficient Actor
    # truncation-recovery path (--agent actor) from the same single source.
    "actor": {
        "required_keys": (
            "files_changed",
            "tests_run",
            "validation_notes",
            "blocker",
        ),
        "skeleton": {
            "files_changed": ["<string — path of each file written>"],
            "tests_run": ["<string — command + pass/fail summary>"],
            "validation_notes": "<string — how the change satisfies each validation criterion>",
            "blocker": "<string | null — null when no blocker>",
        },
    },
}

REVIEW_PROMPT_SPECS: dict[str, dict[str, str]] = {
    "monitor": {
        "subagent_type": "monitor",
        "description": "Review code changes",
        "task": "Review code correctness, standards, security, tests, and performance.",
        "instructions": """Check for:
- Code correctness and logic errors
- Security vulnerabilities (OWASP top 10)
- Standards compliance
- Test coverage gaps
- Performance issues""",
    },
    "predictor": {
        "subagent_type": "predictor",
        "description": "Analyze change impact",
        "task": "Analyze the impact and risk of the change.",
        "instructions": """Analyze:
- Affected components and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment (low/medium/high/critical)
- Integration points affected""",
    },
    "evaluator": {
        "subagent_type": "evaluator",
        "description": "Score change quality",
        "task": "Score the change quality using the review bundle and diff evidence.",
        "instructions": """Provide quality assessment using 1-10 scoring:
- Functionality score (1-10)
- Completeness score (1-10)
- Security score (1-10)
- Code quality score (1-10)
- Testability score (1-10)
- Performance score (1-10)
- Simplicity score (1-10)""",
    },
}


def _render_format_block(agent: str) -> str:
    """Return an <output_schema>+<format_rules> block for the given agent role.

    The schema is derived from AGENT_OUTPUT_SCHEMAS[agent]["skeleton"] so there
    is exactly one source of truth for the output shape. format_rules are
    verbatim — callers MUST NOT paraphrase them.
    """
    skeleton = AGENT_OUTPUT_SCHEMAS[agent]["skeleton"]
    schema_json = json.dumps(skeleton, indent=2)
    format_rules_body = (
        "Return exactly one JSON object matching the schema above. "
        "No markdown, no code fences, no prose before/after. "
        "Every key is required EXCEPT fields whose placeholder marks them "
        "conditional (\"required when ...\"): include those only when their "
        "stated condition applies."
    )
    return (
        f"<output_schema>\n{schema_json}\n</output_schema>\n"
        f"<format_rules>\n{format_rules_body}\n</format_rules>"
    )


def _review_prompt_budget_tokens(explicit_budget: Optional[int] = None) -> int:
    """Return the hard estimated-token budget for each review fan-out prompt."""
    if explicit_budget is not None and explicit_budget >= REVIEW_PROMPT_MIN_BUDGET_TOKENS:
        return explicit_budget

    raw = os.environ.get(REVIEW_PROMPT_BUDGET_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= REVIEW_PROMPT_MIN_BUDGET_TOKENS:
                return value
        except ValueError:
            pass
    return REVIEW_PROMPT_DEFAULT_BUDGET_TOKENS


def _read_review_bundle_markdown(branch_name: str) -> str:
    bundle_path = get_branch_dir(branch_name) / "review-bundle.md"
    try:
        return bundle_path.read_text(encoding="utf-8")
    except OSError:
        return "[review-bundle.md missing; run create_review_bundle before launching reviewers]"


def _read_git_diff_for_review() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return f"[git diff unavailable: {exc}]"
    if result.returncode != 0:
        reason = result.stderr.strip() or "git diff exited non-zero"
        return f"[git diff unavailable: {reason}]"
    return result.stdout.strip() or "[no git diff output]"


def _render_review_prompt(
    spec: dict[str, str],
    review_bundle: str,
    review_preferences: str,
    git_diff: str,
    budget_note: str = "",
) -> str:
    preferences = review_preferences.strip() or "[no additional review preferences]"
    documents = [
        "<documents>",
        "  <document source='.map/<branch>/review-bundle.md' priority='primary'>",
        "    <document_content>",
        review_bundle,
        "    </document_content>",
        "  </document>",
        "  <document source='review-preferences'>",
        "    <document_content>",
        preferences,
        "    </document_content>",
        "  </document>",
        "  <document source='git diff' priority='secondary'>",
        "    <document_content>",
        git_diff,
        "    </document_content>",
        "  </document>",
    ]
    if budget_note:
        documents.extend(
            [
                "  <document source='review-prompt-budget' priority='diagnostic'>",
                "    <document_content>",
                budget_note,
                "    </document_content>",
                "  </document>",
            ]
        )
    documents.append("</documents>")

    return "\n\n".join(
        [
            "\n".join(documents),
            f"<task>\n{spec['task']}\n</task>",
            "<workflow_policy>\n"
            "Read the persisted review bundle first. Use the raw diff only to "
            "confirm or expand specific findings the bundle surfaces.\n"
            "</workflow_policy>",
            f"<instructions>\n{spec['instructions']}\n</instructions>",
            f"<expected_output>\n{_render_format_block(spec['subagent_type'])}\n</expected_output>",
        ]
    )


def _budget_review_prompt(
    spec: dict[str, str],
    review_bundle: str,
    review_preferences: str,
    git_diff: str,
    budget_tokens: int,
) -> dict[str, object]:
    # Truncation infrastructure removed by user directive ("убери транкейт
    # уже вообще"). The full review prompt is emitted with no clipping —
    # reviewers see the entire bundle, preferences, and diff. If the
    # prompt exceeds context, the operator opts into /compact themselves.
    prompt = _render_review_prompt(spec, review_bundle, review_preferences, git_diff)
    return {
        "prompt": prompt,
        "estimated_tokens": 0,
        "budget_tokens": budget_tokens,
        "truncated": False,
        "clipped_sections": [],
    }


def build_review_prompts(
    branch: Optional[str] = None,
    review_preferences: str = "",
    budget_tokens: Optional[int] = None,
    review_bundle_text: Optional[str] = None,
    git_diff_text: Optional[str] = None,
) -> dict:
    """Build bounded `/map-review` fan-out prompts for Monitor/Predictor/Evaluator."""
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    budget = _review_prompt_budget_tokens(budget_tokens)
    review_bundle = (
        review_bundle_text
        if review_bundle_text is not None
        else _read_review_bundle_markdown(branch_name)
    )
    git_diff = git_diff_text if git_diff_text is not None else _read_git_diff_for_review()

    prompts: dict[str, dict[str, object]] = {}
    for role, spec in REVIEW_PROMPT_SPECS.items():
        prompt_result = _budget_review_prompt(
            spec, review_bundle, review_preferences, git_diff, budget
        )
        # No token-budget bookkeeping — truncation is gone, so there's
        # nothing to record. Operators chase context-size concerns via
        # the conversation-level /compact opt-in.
        prompts[role] = {
            "subagent_type": spec["subagent_type"],
            "description": spec["description"],
            **prompt_result,
        }

    return {
        "status": "success",
        "branch": branch_name,
        "budget_tokens": budget,
        "budget_env": REVIEW_PROMPT_BUDGET_ENV,
        "prompts": prompts,
    }


def write_learning_handoff(
    workflow: str,
    task_title: str = "",
    outcome: str = "",
    next_action: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a reusable learning handoff artifact for deferred /map-learn runs."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)

    def read(name: str) -> str:
        path = branch_dir / name
        if not path.exists():
            return ""
        try:
            return _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

    def read_json(name: str) -> Optional[dict[str, object]]:
        raw = read(name)
        if not raw:
            return None
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    workflow_name = workflow.strip() or "map-workflow"
    goal = task_title.strip() or read_current_goal(branch_name) or "Workflow summary"
    outcome_text = outcome.strip() or "Learning handoff generated"
    next_action_text = (
        next_action.strip()
        or "Run /map-learn now, or batch it later when you want to pay the learning cost."
    )
    notes_text = notes.strip()
    generated_at = _utc_timestamp()

    review_handoff = build_review_handoff(branch_name)
    bundle = build_handoff_bundle(branch_name)
    code_state = snapshot_code_state(branch_name)
    workflow_fit = read_json("workflow-fit.json")
    manifest = read_json("artifact_manifest.json")
    run_health_report = read_json("run_health_report.json")
    known_issues = read_json("known-issues.json")
    active_issues = read_json("active-issues.json")

    markdown_path = branch_dir / "learning-handoff.md"
    json_path = branch_dir / "learning-handoff.json"

    files_changed = code_state.get("files_changed") or []
    if isinstance(files_changed, list):
        files_section = "\n".join(f"- {path}" for path in files_changed) or "- [not recorded]"
    else:
        files_section = "- [not recorded]"

    artifact_paths = [
        path
        for path in [
            "workflow-fit.json" if workflow_fit else "",
            "artifact_manifest.json",
            "run_health_report.json" if run_health_report else "",
            review_handoff.get("plan_review_path") or "",
            review_handoff.get("code_review_path") or "",
            review_handoff.get("verification_summary_path") or "",
            review_handoff.get("qa_path") or "",
            review_handoff.get("pr_draft_path") or "",
            review_handoff.get("active_issues_path") or "",
            "known-issues.json" if known_issues else "",
        ]
        if path
    ]
    artifacts_section = "\n".join(f"- {path}" for path in artifact_paths) or "- [not recorded]"

    payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "workflow": workflow_name,
        "branch": branch_name,
        "task_title": goal,
        "outcome": outcome_text,
        "next_action": next_action_text,
        "notes": notes_text,
        "git_ref": code_state.get("git_ref", "unknown"),
        "files_changed": files_changed if isinstance(files_changed, list) else [],
        "summary": bundle.get("summary", "- [not recorded]"),
        "validation": bundle.get("validation", "- [not recorded]"),
        "risks_follow_up": bundle.get("risks_follow_up", "- [not recorded]"),
        "artifacts": {
            "workflow_fit": workflow_fit,
            "artifact_manifest": manifest,
            "run_health_report": run_health_report,
            "review_handoff": review_handoff,
            "known_issues": known_issues,
            "active_issues": active_issues,
        },
        "documents": {
            "plan_review": review_handoff.get("plan_review"),
            "code_review": review_handoff.get("code_review"),
            "verification_summary": review_handoff.get("verification_summary"),
            "qa": review_handoff.get("qa"),
            "pr_draft": review_handoff.get("pr_draft"),
        },
    }

    markdown = (
        "# Learning Handoff\n\n"
        f"- Workflow: `{workflow_name}`\n"
        f"- Branch: `{branch_name}`\n"
        f"- Task: {goal}\n"
        f"- Outcome: {outcome_text}\n"
        f"- Generated: {generated_at}\n"
        f"- Git ref: `{code_state.get('git_ref', 'unknown')}`\n"
        f"- Next action: {next_action_text}\n\n"
        "## Recommended Invocation\n\n"
        "Run `/map-learn` with no arguments to auto-load this handoff.\n\n"
        "If you want to pass the artifact explicitly:\n\n"
        f"`/map-learn .map/{branch_name}/learning-handoff.md`\n\n"
        "## Summary\n\n"
        f"{bundle.get('summary', '- [not recorded]')}\n\n"
        "## Validation\n\n"
        f"{bundle.get('validation', '- [not recorded]')}\n\n"
        "## Risks / Follow-up\n\n"
        f"{bundle.get('risks_follow_up', '- [not recorded]')}\n\n"
        "## Files Changed\n\n"
        f"{files_section}\n\n"
        "## Source Artifacts\n\n"
        f"{artifacts_section}\n"
    )
    if notes_text:
        markdown += f"\n## Notes\n\n{notes_text}\n"

    metrics_result = _record_learning_handoff_generation_metrics(
        workflow_name, generated_at, markdown_path, json_path, branch_name
    )
    repeated_violation_result = record_repeated_learning_violations(
        branch_name, cast(dict[str, object], metrics_result["metrics"])
    )
    repeated_violation_summary = cast(dict[str, object], repeated_violation_result["summary"])
    rvr_path = str(repeated_violation_result["path"])
    rvr_metrics = cast(dict[str, object], repeated_violation_result["metrics"])

    repeated_violation_lines = [
        f"- Findings checked: {repeated_violation_summary['finding_count']}",
        f"- Learned rules considered: {repeated_violation_summary['learned_rule_count']}",
        f"- Repeated-rule matches: {repeated_violation_summary['matched_count']}",
    ]
    for match in cast(list[dict[str, object]], repeated_violation_summary["matches"]):
        repeated_violation_lines.append(
            f"- {match['rule_title']} <= {match['finding_text']}"
        )

    manifest_payload = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest_payload,
        "learn_handoff",
        "ready",
        artifacts=[
            _artifact_ref(markdown_path, "learning-handoff-markdown"),
            _artifact_ref(json_path, "learning-handoff-json"),
            _artifact_ref(
                Path(rvr_path), "learning-handoff-metrics"
            ),
        ],
        metadata={
            "workflow": workflow_name,
            "task_title": goal,
            "outcome": outcome_text,
            "next_action": next_action_text,
            "git_ref": code_state.get("git_ref", "unknown"),
            "learning_metrics_path": rvr_path,
            "learning_metrics_counters": dict(
                cast(Mapping[str, int], rvr_metrics["counters"])
            ),
            "repeated_violation_summary": repeated_violation_summary,
        },
    )
    manifest_result = save_artifact_manifest(manifest_payload, branch_name)
    payload["artifacts"]["artifact_manifest"] = manifest_result["manifest"]
    payload["artifacts"]["learning_metrics"] = repeated_violation_result["metrics"]
    payload["artifacts"]["repeated_violation_summary"] = repeated_violation_summary
    _write_json_file(json_path, payload)
    markdown += (
        "\n## Learning Effectiveness Signals\n\n"
        f"{chr(10).join(repeated_violation_lines)}\n"
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "status": "success",
        "branch": branch_name,
        "workflow": workflow_name,
        "task_title": goal,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "manifest_path": manifest_result["path"],
        "learning_metrics_path": repeated_violation_result["path"],
        "generated_at": generated_at,
    }


def ensure_known_issues_file(branch: Optional[str] = None) -> dict:
    """Ensure known-issues.json exists for accepted blockers / known limitations."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    issues_file = branch_dir / "known-issues.json"
    if not issues_file.exists():
        issues_file.write_text(
            json.dumps(KNOWN_ISSUES_DEFAULT, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return {"status": "success", "path": str(issues_file), "created": True}
    return {"status": "success", "path": str(issues_file), "created": False}


def add_known_issue(
    title: str,
    status: str = "accepted",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Append a known issue / accepted blocker entry."""
    ensure_known_issues_file(branch)
    issues_file = get_branch_dir(branch) / "known-issues.json"
    payload = json.loads(issues_file.read_text(encoding="utf-8"))
    payload.setdefault("issues", []).append(
        {
            "title": title,
            "status": status,
            "notes": notes,
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    issues_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "success",
        "path": str(issues_file),
        "count": len(payload["issues"]),
    }


from map_utils import get_branch_name  # noqa: E402  # type: ignore[import-not-found]


def update_step_state(
    subtask_id: str,
    step_name: str,
    new_state: str,
    branch: Optional[str] = None,
) -> dict:
    """
    Update step_state.json after step completion.

    Args:
        subtask_id: Subtask ID (e.g., "ST-001")
        step_name: Step name (e.g., "actor", "monitor")
        new_state: New state (e.g., "ACTOR_CALLED", "MONITOR_PASSED")
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and updated state
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {"status": "error", "message": "step_state.json not found"}

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))

        # Initialize completed_steps dict if missing
        if "completed_steps" not in state:
            state["completed_steps"] = {}

        # Initialize list for this subtask if missing
        if subtask_id not in state["completed_steps"]:
            state["completed_steps"][subtask_id] = []

        # Append step to completed list
        if step_name not in state["completed_steps"][subtask_id]:
            state["completed_steps"][subtask_id].append(step_name)

        # Update current state
        state["current_state"] = new_state
        state["current_subtask"] = subtask_id

        # Write back atomically
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_file.replace(state_file)

        return {
            "status": "success",
            "message": f"Updated {subtask_id}: {step_name} -> {new_state}",
            "completed_steps": state["completed_steps"][subtask_id],
        }

    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": str(e)}


def update_step_state_batch(
    updates: list[dict],
    branch: Optional[str] = None,
) -> dict:
    """
    Update step_state.json for multiple subtasks in one call.

    Used in wave-based parallel execution to update all subtasks in a wave
    after their actors/monitors complete.

    Args:
        updates: List of dicts, each with:
            - subtask_id: Subtask ID (e.g., "ST-002")
            - step_name: Step name (e.g., "actor", "monitor")
            - new_state: New state (e.g., "ACTOR_CALLED", "MONITOR_PASSED")
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and per-subtask results
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {"status": "error", "message": "step_state.json not found"}

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))

        if "completed_steps" not in state:
            state["completed_steps"] = {}

        results = []
        active_subtasks = []

        for update in updates:
            subtask_id = update.get("subtask_id", "")
            step_name = update.get("step_name", "")
            new_state = update.get("new_state", "")

            if subtask_id not in state["completed_steps"]:
                state["completed_steps"][subtask_id] = []

            if step_name not in state["completed_steps"][subtask_id]:
                state["completed_steps"][subtask_id].append(step_name)

            active_subtasks.append(subtask_id)
            results.append(
                {
                    "subtask_id": subtask_id,
                    "step_name": step_name,
                    "new_state": new_state,
                }
            )

        # Set active_subtasks list for wave mode (used by workflow-gate.py)
        state["active_subtasks"] = active_subtasks
        if active_subtasks:
            state["current_subtask"] = active_subtasks[0]
            state["current_state"] = updates[-1].get("new_state", "UPDATED")

        # Write back atomically
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_file.replace(state_file)

        return {
            "status": "success",
            "message": f"Batch updated {len(updates)} subtasks",
            "results": results,
        }

    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": str(e)}


def update_plan_status(
    subtask_id: str,
    new_status: str,
    branch: Optional[str] = None,
) -> dict:
    """
    Update subtask status in task_plan.md.

    Args:
        subtask_id: Subtask ID (e.g., "ST-001")
        new_status: New status (pending|in_progress|complete|blocked)
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and message
    """
    if branch is None:
        branch = get_branch_name()

    plan_file = Path(f".map/{branch}/task_plan_{branch}.md")

    if not plan_file.exists():
        return {"status": "error", "message": f"Plan file not found: {plan_file}"}

    try:
        content = plan_file.read_text(encoding="utf-8")

        # Find subtask section (### ST-XXX: Title)
        pattern = rf"(### {re.escape(subtask_id)}:.*?\n- \*\*Status:\*\*\s+)\w+"
        replacement = rf"\g<1>{new_status}"

        updated_content = re.sub(pattern, replacement, content)

        if updated_content == content:
            return {
                "status": "warning",
                "message": f"Subtask {subtask_id} not found in plan",
            }

        # Write back
        plan_file.write_text(updated_content, encoding="utf-8")

        return {
            "status": "success",
            "message": f"Updated {subtask_id} status to {new_status}",
        }

    except (OSError, re.error) as e:
        return {"status": "error", "message": str(e)}


def validate_checkpoint(
    subtask_id: str,
    required_steps: list[str],
    branch: Optional[str] = None,
) -> dict:
    """
    Validate that required steps are completed for subtask.

    Args:
        subtask_id: Subtask ID to check
        required_steps: List of step names that must be completed
        branch: Git branch (auto-detected if None)

    Returns:
        dict with valid: bool, missing_steps: list[str]
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {
            "valid": False,
            "missing_steps": required_steps,
            "message": "step_state.json not found",
        }

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        completed = state.get("completed_steps", {}).get(subtask_id, [])

        missing = [step for step in required_steps if step not in completed]

        return {
            "valid": len(missing) == 0,
            "missing_steps": missing,
            "completed_steps": completed,
            "message": (
                "All required steps completed"
                if not missing
                else f"Missing steps: {', '.join(missing)}"
            ),
        }

    except (json.JSONDecodeError, OSError) as e:
        return {
            "valid": False,
            "missing_steps": required_steps,
            "message": str(e),
        }


def create_xml_packet(subtask: dict) -> str:
    """
    Create AI-friendly XML packet for subtask.

    Args:
        subtask: dict with subtask data from decomposer blueprint

    Returns:
        XML packet string
    """
    subtask_id = subtask.get("id", "ST-XXX")
    # Convert ST-001 to ST_001 for XML tag safety
    tag_id = subtask_id.replace("-", "_")

    title = subtask.get("title", "Untitled")
    description = subtask.get("description", "")
    risk_level = subtask.get("risk_level", "low")
    security_critical = subtask.get("security_critical", False)
    complexity_score = subtask.get("complexity_score", 1)
    expected_diff_size = subtask.get("expected_diff_size", "medium")
    concern_type = subtask.get("concern_type", "runtime")
    one_logical_step = subtask.get("one_logical_step", "unknown")
    affected_files = ";".join(subtask.get("affected_files", []))
    validation_criteria = "\n".join(
        f"- {c}" for c in subtask.get("validation_criteria", [])
    )
    contracts = subtask.get("contracts", "")
    test_strategy = json.dumps(subtask.get("test_strategy", {}))

    packet = f"""<SUBTASK_{tag_id}>
  <SUBTASK_{tag_id}__ID>{subtask_id}</SUBTASK_{tag_id}__ID>
  <SUBTASK_{tag_id}__TITLE>{title}</SUBTASK_{tag_id}__TITLE>
  <SUBTASK_{tag_id}__DESCRIPTION>{description}</SUBTASK_{tag_id}__DESCRIPTION>
  <SUBTASK_{tag_id}__RISK_LEVEL>{risk_level}</SUBTASK_{tag_id}__RISK_LEVEL>
  <SUBTASK_{tag_id}__SECURITY_CRITICAL>{str(security_critical).lower()}</SUBTASK_{tag_id}__SECURITY_CRITICAL>
  <SUBTASK_{tag_id}__COMPLEXITY_SCORE>{complexity_score}</SUBTASK_{tag_id}__COMPLEXITY_SCORE>
  <SUBTASK_{tag_id}__EXPECTED_DIFF_SIZE>{expected_diff_size}</SUBTASK_{tag_id}__EXPECTED_DIFF_SIZE>
  <SUBTASK_{tag_id}__CONCERN_TYPE>{concern_type}</SUBTASK_{tag_id}__CONCERN_TYPE>
  <SUBTASK_{tag_id}__ONE_LOGICAL_STEP>{one_logical_step}</SUBTASK_{tag_id}__ONE_LOGICAL_STEP>

  <SUBTASK_{tag_id}__AFFECTED_FILES>{affected_files}</SUBTASK_{tag_id}__AFFECTED_FILES>
  <SUBTASK_{tag_id}__VALIDATION_CRITERIA>
{validation_criteria}
  </SUBTASK_{tag_id}__VALIDATION_CRITERIA>
  <SUBTASK_{tag_id}__CONTRACTS>{contracts}</SUBTASK_{tag_id}__CONTRACTS>
  <SUBTASK_{tag_id}__TEST_STRATEGY>{test_strategy}</SUBTASK_{tag_id}__TEST_STRATEGY>
</SUBTASK_{tag_id}>"""

    return packet


def get_plan_path(branch: Optional[str] = None) -> Path:
    """
    Get path to task_plan file for current branch.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Path to task_plan_<branch>.md
    """
    if branch is None:
        branch = get_branch_name()
    return Path(f".map/{branch}/task_plan_{branch}.md")


def read_current_goal(branch: Optional[str] = None) -> Optional[str]:
    """
    Read Goal section from task_plan.md.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Goal text or None if not found
    """
    plan_file = get_plan_path(branch)

    if not plan_file.exists():
        return None

    try:
        content = plan_file.read_text(encoding="utf-8")
        match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    except OSError:
        pass

    return None


def get_current_phase(branch: Optional[str] = None) -> Optional[str]:
    """
    Read Current Phase from task_plan.md.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Current phase ID (e.g., "ST-001") or None
    """
    plan_file = get_plan_path(branch)

    if not plan_file.exists():
        return None

    try:
        content = plan_file.read_text(encoding="utf-8")
        match = re.search(r"## Current Phase\n(\S+)", content)
        if match:
            return match.group(1).strip()
    except OSError:
        pass

    return None


def run_test_gate() -> dict:
    """Run project test suite as a deterministic verification gate.

    Detects the test runner (pytest/npm/go/cargo) and executes it.
    Returns structured result with pass/fail, output, and exit code.
    Called AFTER Monitor returns valid=true, BEFORE validate_step advances state.
    """

    # Detect test runner
    runners = [
        (["pytest.ini", "pyproject.toml", "setup.py", "setup.cfg"], ["pytest", "--tb=short", "-q"]),
        (["package.json"], ["npm", "test"]),
        (["go.mod"], ["go", "test", "./..."]),
        (["Cargo.toml"], ["cargo", "test"]),
    ]

    test_cmd = None
    for markers, cmd in runners:
        for marker in markers:
            if Path(marker).exists():
                # For pyproject.toml, check it actually has pytest config or is a Python project
                if marker == "pyproject.toml":
                    try:
                        content = Path(marker).read_text(encoding="utf-8")
                        if "pytest" not in content and "tool.pytest" not in content:
                            continue
                    except OSError:
                        continue
                test_cmd = cmd
                break
        if test_cmd:
            break

    if not test_cmd:
        return {
            "status": "skipped",
            "passed": True,
            "reason": "No test runner detected",
            "output": "",
            "exit_code": 0,
        }

    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        # Truncate to avoid huge JSON
        if len(output) > 5000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-2000:]

        return {
            "status": "success",
            "passed": passed,
            "output": output,
            "exit_code": result.returncode,
            "test_cmd": " ".join(test_cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "passed": False,
            "output": "Test execution timed out after 300s",
            "exit_code": -1,
            "test_cmd": " ".join(test_cmd),
        }
    except OSError as e:
        return {
            "status": "error",
            "passed": False,
            "output": str(e),
            "exit_code": -1,
            "test_cmd": " ".join(test_cmd),
        }


_DIFF_STAT_MAX_CHARS = 65_536
_FILES_CHANGED_MAX_ENTRIES = 500


def snapshot_code_state(branch: Optional[str] = None) -> dict:
    """Capture current git state for artifact-to-code verification.

    Records git ref, changed files, and diff stat so review artifacts
    can be tied to actual code state. Populates subtask_files_changed.

    Very large repos can produce huge ``diff_stat`` and ``files_changed`` outputs that
    bloat the bundle JSON. Both are capped here (``_DIFF_STAT_MAX_CHARS`` /
    ``_FILES_CHANGED_MAX_ENTRIES``) with a ``diff_truncated=True`` marker so reviewers
    can see at a glance that the snapshot was clipped.
    """

    branch_name = branch or get_branch_name()

    def _run_git(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    git_ref = _run_git(["rev-parse", "HEAD"])
    diff_stat = _run_git(["diff", "--stat", "HEAD"])
    diff_names = _run_git(["diff", "--name-only", "HEAD"])
    files_changed = [f for f in diff_names.splitlines() if f.strip()] if diff_names else []

    diff_truncated = False
    if len(diff_stat) > _DIFF_STAT_MAX_CHARS:
        diff_stat = diff_stat[:_DIFF_STAT_MAX_CHARS] + "\n... [truncated]"
        diff_truncated = True
    if len(files_changed) > _FILES_CHANGED_MAX_ENTRIES:
        files_changed = files_changed[:_FILES_CHANGED_MAX_ENTRIES]
        diff_truncated = True

    return {
        "status": "success",
        "git_ref": git_ref[:12] if git_ref else "unknown",
        "files_changed": files_changed,
        "diff_stat": diff_stat,
        "branch": branch_name,
        "diff_truncated": diff_truncated,
    }


def load_blueprint(
    branch: Optional[str] = None, project_dir: Optional[Path] = None
) -> Optional[dict]:
    """Load blueprint.json for current branch."""
    branch_name: str = branch if branch is not None else get_branch_name()
    base = project_dir or Path(".")
    blueprint_path = base / ".map" / branch_name / "blueprint.json"
    if not blueprint_path.exists():
        return None
    try:
        payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
        if isinstance(payload.get("blueprint"), dict):
            blueprint = dict(payload["blueprint"])
            if "coverage_map" not in blueprint and isinstance(payload.get("coverage_map"), dict):
                blueprint["coverage_map"] = payload["coverage_map"]
            return blueprint
        return payload
    except (json.JSONDecodeError, OSError):
        return None


def get_subtask_from_blueprint(blueprint: dict, subtask_id: str) -> Optional[dict]:
    """Extract single subtask from blueprint by ID."""
    for subtask in blueprint.get("subtasks", []):
        if subtask.get("id") == subtask_id:
            return subtask
    return None


def get_upstream_ids(blueprint: dict, subtask_id: str) -> list[str]:
    """Get dependency subtask IDs for a given subtask."""
    subtask = get_subtask_from_blueprint(blueprint, subtask_id)
    if not subtask:
        return []
    return subtask.get("dependencies", [])


def _sanitize_branch(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths.

    Keep in sync with sanitize_branch_name() in workflow-context-injector.py.
    """
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


_RESEARCH_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESEARCH_SUBTASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _research_path(branch: str, subtask_id: str, kind: str) -> Path:
    """Resolve a research artifact path with strict sanitization."""
    if not _RESEARCH_SUBTASK_ID_RE.match(subtask_id):
        raise ValueError(
            f"Invalid subtask_id for research artifact: {subtask_id!r}. "
            "Must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}."
        )
    if not _RESEARCH_KIND_RE.match(kind):
        raise ValueError(
            f"Invalid research kind: {kind!r}. Must match [a-z][a-z0-9_]*."
        )
    safe_branch = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    return (
        project_dir
        / ".map"
        / safe_branch
        / "research"
        / f"{subtask_id}__{kind}.md"
    )


def save_research(
    branch: str,
    subtask_id: str,
    content: str,
    *,
    kind: str = "actor",
    attempt: Optional[int] = None,
) -> str:
    """Persist research findings for a subtask. Returns the written path.

    Default behaviour overwrites the canonical ``<subtask_id>__<kind>.md`` so
    Actor and Monitor read the latest copy without a sentinel hunt. Pass an
    ``attempt`` integer (e.g. retry_count) to preserve a numbered snapshot at
    ``<subtask_id>__<kind>.attempt-<N>.md`` BEFORE overwriting the canonical
    path — useful for clean-retry diffing without losing the original.
    """
    path = _research_path(branch, subtask_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    if attempt is not None and path.exists():
        snapshot = path.with_name(
            f"{subtask_id}__{kind}.attempt-{int(attempt)}.md"
        )
        try:
            snapshot.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    path.write_text(content, encoding="utf-8")
    return str(path)


# Truncation-detector minimal keys for `detect_truncated_agent_output
# --agent monitor`. This is the common core shared by BOTH Monitor output
# contracts that route through this gate:
#   - map-efficient Monitor: valid/summary/issues/files_changed/tests_run/escalation_required
#   - map-review Monitor:    evidence/valid/summary/verdict/issues/passed_checks/failed_checks
# It is intentionally NOT AGENT_OUTPUT_SCHEMAS["monitor"]["required_keys"]
# (the full review-prompt schema): the map-efficient Monitor never emits
# evidence/verdict/passed_checks/failed_checks, so requiring the full review
# set would make the map-efficient truncation gate reject every valid Monitor
# response. Truncation detection only needs the verdict (valid), the prose
# summary, and the findings (issues) — present in both contracts.
_MONITOR_REQUIRED_KEYS = ("valid", "summary", "issues")
_ACTOR_REQUIRED_KEYS = tuple(AGENT_OUTPUT_SCHEMAS["actor"]["required_keys"])


def detect_truncated_agent_output(
    text: str,
    *,
    expected_keys: Optional[list[str]] = None,
    agent_kind: str = "monitor",
) -> dict[str, object]:
    """Diagnose a possibly-truncated agent response.

    Skill-level rule (added 2026-05-24): if Monitor or Actor returns prose
    instead of the JSON envelope they were prompted for, the workflow
    must retry once with an "emit ONLY JSON" follow-up, then
    CLARIFICATION_NEEDED. The rule was prose; this helper makes it a
    reusable predicate so callers (skills, CI, future automation) all
    classify the same way.

    Returns:
        {
            "truncated": bool,        # True = response is not a complete
                                      # well-formed JSON object with the
                                      # expected keys
            "reasons": [str, ...],    # zero-or-more diagnoses, e.g.:
                                      # "output does not parse as JSON",
                                      # "missing required key: valid",
                                      # "trailing text after JSON object",
                                      # "response ends mid-sentence"
            "parsed": dict | None,    # the parsed object, or None on parse failure
            "agent_kind": str,        # echoed for downstream logging
        }

    ``expected_keys`` defaults per ``agent_kind``: monitor expects
    ``valid``/``summary``/``issues``; actor expects ``files_changed``/
    ``tests_run``. Other kinds pass an explicit list or get a permissive
    "parses as object" check only.
    """
    reasons: list[str] = []
    text = text or ""
    stripped = text.strip()
    if not stripped:
        return {
            "truncated": True,
            "reasons": ["empty response"],
            "parsed": None,
            "agent_kind": agent_kind,
        }

    parsed: Optional[dict[str, object]] = None
    # Two parse attempts: full body, then "first JSON object substring"
    # in case there's a code fence or markdown prelude.
    try:
        candidate = json.loads(stripped)
        if isinstance(candidate, dict):
            parsed = candidate
        else:
            reasons.append("output parses as JSON but is not an object")
    except json.JSONDecodeError:
        # Try to recover a fenced object: ```json\n{...}\n```
        match = re.search(r"\{(?:.|\n)*\}", stripped)
        if match:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    parsed = candidate
                    # Reject if the body has non-JSON trailing/leading
                    # text — that's a strong "wrapped in prose" signal.
                    if stripped != match.group(0):
                        reasons.append("trailing or leading text around JSON object")
                else:
                    reasons.append("recovered JSON is not an object")
            except json.JSONDecodeError:
                reasons.append("output does not parse as JSON")
        else:
            reasons.append("output does not parse as JSON")

    if parsed is None:
        # Mid-sentence ending is a strong "agent cut off" hint.
        if not stripped.endswith(("}", "]")):
            reasons.append("response ends mid-sentence (no closing } or ])")
        return {
            "truncated": True,
            "reasons": reasons,
            "parsed": None,
            "agent_kind": agent_kind,
        }

    # Validate required keys.
    if expected_keys is None:
        if agent_kind == "monitor":
            expected_keys = list(_MONITOR_REQUIRED_KEYS)
        elif agent_kind == "review-monitor":
            # Full review-monitor schema (evidence/valid/summary/verdict/issues/
            # passed_checks/failed_checks). Distinct from "monitor" which uses the
            # minimal map-efficient common core so it doesn't reject valid efficient
            # Monitor responses that never emit evidence/verdict/passed_checks/failed_checks.
            expected_keys = list(AGENT_OUTPUT_SCHEMAS["monitor"]["required_keys"])
        elif agent_kind == "actor":
            expected_keys = list(_ACTOR_REQUIRED_KEYS)
        elif agent_kind in AGENT_OUTPUT_SCHEMAS:
            expected_keys = list(AGENT_OUTPUT_SCHEMAS[agent_kind]["required_keys"])
        else:
            expected_keys = []
    missing = [k for k in expected_keys if k not in parsed]
    for key in missing:
        reasons.append(f"missing required key: {key}")

    return {
        "truncated": bool(reasons),
        "reasons": reasons,
        "parsed": parsed,
        "agent_kind": agent_kind,
    }


def build_json_retry_prompt(
    agent: str,
    errors: Optional[list[str]] = None,
) -> dict[str, object]:
    """Build a retry prompt for a review agent that returned malformed output.

    Uses _render_format_block(agent) as the single source of truth for the
    output schema so the retry prompt embeds the identical skeleton as the
    original review prompt.

    Returns:
        {
            "status": "ok" | "error",
            "agent": str,           # echoed agent name
            "reasons": [str, ...],  # echoed errors (empty list when None)
            "prompt": str,          # retry prompt text ("" on error)
        }

    On unknown agent (not in AGENT_OUTPUT_SCHEMAS), returns status="error"
    with an "unknown agent" entry prepended to reasons and prompt="".
    """
    error_list: list[str] = list(errors) if errors else []

    if agent not in AGENT_OUTPUT_SCHEMAS:
        return {
            "status": "error",
            "agent": agent,
            "reasons": [f"unknown agent: {agent!r}; must be one of {sorted(AGENT_OUTPUT_SCHEMAS)}"] + error_list,
            "prompt": "",
        }

    format_block = _render_format_block(agent)

    # Build the failure section only when there are errors to report.
    if error_list:
        bullet_lines = "\n".join(f"- {e}" for e in error_list)
        failure_section = (
            f"\nYour previous response was rejected for:\n{bullet_lines}\n"
        )
    else:
        failure_section = ""

    prompt = (
        "Emit ONLY one JSON object matching this schema. "
        "No markdown, no prose — just the JSON object.\n"
        f"{failure_section}"
        f"\n{format_block}"
    )

    return {
        "status": "ok",
        "agent": agent,
        "reasons": error_list,
        "prompt": prompt,
    }


def load_research(
    branch: str,
    subtask_id: str,
    *,
    kind: str = "actor",
    merge_all_kinds: bool = False,
) -> str:
    """Return saved research findings; empty string when absent.

    ``merge_all_kinds=True`` concatenates every kind present on disk
    (actor / monitor / decomposer / anything custom) under per-kind
    section headers, so callers that want the full research picture
    don't have to ping each kind individually. Order: actor first if
    present, then monitor, then decomposer, then any other kinds in
    sorted order. Sections are separated by blank lines and prefixed
    with ``# kind=<kind>``. When merge_all_kinds is False (default),
    the function behaves exactly as before — single-kind read.
    """
    if not merge_all_kinds:
        path = _research_path(branch, subtask_id, kind)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    # Merge mode: scan the research directory for this subtask and
    # concatenate every kind.
    seed_path = _research_path(branch, subtask_id, "actor")
    research_dir = seed_path.parent
    if not research_dir.is_dir():
        return ""
    pattern = f"{subtask_id}__*.md"
    found: dict[str, str] = {}
    for candidate in sorted(research_dir.glob(pattern)):
        stem = candidate.stem  # e.g. "ST-001__monitor"
        marker = "__"
        if marker not in stem:
            continue
        kind_name = stem.rsplit(marker, 1)[-1]
        if not _RESEARCH_KIND_RE.match(kind_name):
            continue
        try:
            found[kind_name] = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    if not found:
        return ""
    ordered_kinds: list[str] = []
    for preferred in ("actor", "monitor", "decomposer"):
        if preferred in found:
            ordered_kinds.append(preferred)
    for remaining in sorted(k for k in found if k not in ordered_kinds):
        ordered_kinds.append(remaining)
    parts: list[str] = []
    for k in ordered_kinds:
        parts.append(f"# kind={k}")
        parts.append(found[k].rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _claude_code_log_dir(project_dir: Path) -> Optional[Path]:
    """Claude Code stores per-session jsonl logs under
    ``~/.claude/projects/<project-path-with-slashes-as-dashes>/``.
    Resolve the canonical dir for the given project.
    """
    home = Path(os.environ.get("HOME", "")).expanduser()
    if not home:
        return None
    abs_proj = project_dir.resolve()
    # The harness replaces "/" with "-" verbatim, no other sanitization.
    canonical_name = str(abs_proj).replace("/", "-")
    candidate = home / ".claude" / "projects" / canonical_name
    if candidate.is_dir():
        return candidate
    # Fallback: pick by cwd match across all session logs (slower).
    projects_root = home / ".claude" / "projects"
    if not projects_root.is_dir():
        return None
    for child in projects_root.iterdir():
        if child.is_dir():
            try:
                latest = max(child.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            except ValueError:
                continue
            try:
                first = next(
                    json.loads(line)
                    for line in latest.read_text(errors="replace").splitlines()[:30]
                    if "cwd" in line
                )
            except (StopIteration, json.JSONDecodeError, OSError):
                continue
            if isinstance(first, dict) and str(first.get("cwd")) == str(abs_proj):
                return child
    return None


def subtask_token_usage(
    branch: str,
    subtask_id: Optional[str] = None,
    *,
    since_ts: Optional[str] = None,
) -> dict:
    """Sum Claude Code transcript token usage for the current subtask.

    Reads the most recent ``~/.claude/projects/<project>/*.jsonl`` log and
    aggregates ``message.usage`` fields from assistant turns whose timestamp
    falls AFTER the subtask transition. The transition timestamp defaults to
    ``step_state.json``'s mtime — close enough because the orchestrator
    writes to that file on every advance — or to the explicit ``since_ts``
    parameter when callers want a custom window.

    Returns a dict with:
      status: "success" | "no_logs" | "no_state" | "error"
      subtask_id, since_ts, transcript, messages_counted
      input_tokens, output_tokens, cache_read_input_tokens,
      cache_creation_input_tokens, total_tokens
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()

    state_file = project_dir / ".map" / branch_name / "step_state.json"
    if not state_file.exists():
        return {"status": "no_state", "message": f"missing {state_file}"}
    try:
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"unreadable state: {exc}"}

    if subtask_id is None:
        subtask_id = state_data.get("current_subtask_id") or "unknown"

    log_dir = _claude_code_log_dir(project_dir)
    if log_dir is None:
        return {
            "status": "no_logs",
            "subtask_id": subtask_id,
            "message": f"no Claude Code session log dir under ~/.claude/projects for {project_dir}",
        }
    try:
        latest = max(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except ValueError:
        return {
            "status": "no_logs",
            "subtask_id": subtask_id,
            "message": f"no .jsonl files in {log_dir}",
        }

    # Transition timestamp = explicit since_ts OR step_state.json mtime.
    if since_ts:
        threshold_iso = since_ts
    else:
        from datetime import datetime as _dt, timezone as _tz
        threshold_iso = _dt.fromtimestamp(
            state_file.stat().st_mtime, _tz.utc
        ).isoformat().replace("+00:00", "Z")

    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    messages_counted = 0
    try:
        with latest.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp")
                if not isinstance(ts, str) or ts < threshold_iso:
                    continue
                msg = entry.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                messages_counted += 1
                for key in totals:
                    val = usage.get(key)
                    if isinstance(val, int):
                        totals[key] += val
    except OSError as exc:
        return {"status": "error", "message": f"transcript read failed: {exc}"}

    totals_total = (
        totals["input_tokens"]
        + totals["output_tokens"]
        + totals["cache_creation_input_tokens"]
    )
    return {
        "status": "success",
        "subtask_id": subtask_id,
        "since_ts": threshold_iso,
        "transcript": str(latest),
        "messages_counted": messages_counted,
        "total_tokens": totals_total,
        **totals,
    }


def refresh_blueprint_affected_files(
    branch: str, subtask_id: str, *, dry_run: bool = False
) -> dict:
    """Overwrite a subtask's `affected_files` in blueprint.json with the
    actual files this subtask changed (per-subtask baseline ∆ git status).

    Closes the recurring "blueprint affected_files drift" friction: paths
    decomposer guessed at planning time are routinely wrong, and the
    mutation-boundary check then flags every Monitor pass as `warning`.
    Run this after Actor finishes a subtask to lock the planned surface
    to reality before MONITOR — or after MONITOR pass to keep blueprint
    auditable for downstream review.

    Returns: status, subtask_id, previous, current, diff (added/removed),
    blueprint_path, dry_run.
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    bp_path = project_dir / ".map" / branch_name / "blueprint.json"
    if not bp_path.exists():
        return {"status": "error", "message": f"blueprint.json not found at {bp_path}"}
    try:
        bp_text = bp_path.read_text(encoding="utf-8")
        bp_data = json.loads(bp_text)
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"unreadable blueprint: {exc}"}

    # Both wrapped and flat shapes — same convention as load_blueprint.
    if isinstance(bp_data.get("blueprint"), dict):
        target_body = bp_data["blueprint"]
        body_is_wrapped = True
    else:
        target_body = bp_data
        body_is_wrapped = False
    subtasks = target_body.get("subtasks")
    if not isinstance(subtasks, list):
        return {"status": "error", "message": "blueprint missing subtasks list"}
    found_index: Optional[int] = None
    for idx, st in enumerate(subtasks):
        if isinstance(st, dict) and st.get("id") == subtask_id:
            found_index = idx
            break
    if found_index is None:
        return {
            "status": "error",
            "message": f"subtask {subtask_id!r} not in blueprint",
        }

    # Compute the per-subtask actual surface, using the same baseline
    # subtraction the mutation-boundary validator uses. Bug fix
    # (2026-05-26): previously refresh only consulted `git status
    # --porcelain` (uncommitted only). After the recommended
    # per-subtask-commit workflow the porcelain is empty post-commit,
    # so refresh recorded "current=[]" and dashboard reported "all
    # previous files removed". Now we ALSO diff against
    # baseline.head_sha so committed-since-baseline files are included.
    baseline_files: set[str] = set()
    baseline_head_sha: Optional[str] = None
    subtask_baseline_path = _subtask_baseline_path(
        branch_name, subtask_id, project_dir
    )
    for bp_baseline in (subtask_baseline_path, _scope_baseline_path(branch_name, project_dir)):
        if bp_baseline.exists():
            try:
                data = json.loads(bp_baseline.read_text(encoding="utf-8"))
                raw = data.get("files", [])
                if isinstance(raw, list):
                    baseline_files.update(str(p) for p in raw if isinstance(p, str))
                if bp_baseline == subtask_baseline_path:
                    bp_head = data.get("head_sha")
                    if isinstance(bp_head, str) and bp_head:
                        baseline_head_sha = bp_head
            except (json.JSONDecodeError, OSError):
                pass

    actual_set: set[str] = set()
    # Layer 1: committed-since-baseline files (the per-subtask commit
    # workflow's output). git diff base..HEAD enumerates every path
    # touched in any commit on top of `base`.
    if baseline_head_sha:
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--name-only", f"{baseline_head_sha}..HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if diff_proc.returncode == 0:
                for raw in diff_proc.stdout.splitlines():
                    path = raw.strip()
                    if (
                        path
                        and not path.startswith(".map/")
                        and not path.startswith(".codex/")
                        and not path.startswith(".agents/")
                    ):
                        actual_set.add(path)
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Layer 2: uncommitted (worktree + index) via porcelain.
    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": f"git status failed: {exc}"}
    if status_proc.returncode != 0:
        return {
            "status": "error",
            "message": f"git status non-zero: {status_proc.stderr.strip() or 'no stderr'}",
        }
    for raw in status_proc.stdout.splitlines():
        if len(raw) >= 4:
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if (
                path
                and not path.startswith(".map/")
                and not path.startswith(".codex/")
                and not path.startswith(".agents/")
            ):
                actual_set.add(path)
    actual_set -= baseline_files
    current_files = sorted(actual_set)

    previous_raw = subtasks[found_index].get("affected_files", []) or []
    previous_files = sorted({
        re.split(r"\s+\(", str(p).strip())[0]
        for p in previous_raw
        if isinstance(p, str) and p.strip()
    })

    added = sorted(set(current_files) - set(previous_files))
    removed = sorted(set(previous_files) - set(current_files))

    if dry_run:
        return {
            "status": "dry_run",
            "subtask_id": subtask_id,
            "blueprint_path": str(bp_path),
            "previous": previous_files,
            "current": current_files,
            "diff": {"added": added, "removed": removed},
        }

    subtasks[found_index]["affected_files"] = current_files
    if body_is_wrapped:
        bp_data["blueprint"] = target_body
    else:
        bp_data = target_body
    bp_path.write_text(json.dumps(bp_data, indent=2), encoding="utf-8")
    return {
        "status": "success",
        "subtask_id": subtask_id,
        "blueprint_path": str(bp_path),
        "previous": previous_files,
        "current": current_files,
        "diff": {"added": added, "removed": removed},
    }


def record_diagnostics_baseline(
    branch: str,
    *,
    tools: Optional[list[str]] = None,
    timeout_seconds: int = 180,
) -> dict[str, object]:
    """Snapshot pre-existing static-analysis diagnostics (pyright, ruff,
    mypy, golangci-lint) so subtasks can delta against each tool — the
    pytest-only test baseline missed 123 pyright + 130 ruff diagnostics
    in one production run.

    Auto-detects which tools to run from project markers:
      - ``pyright`` (pyproject.toml or pyrightconfig.json present)
      - ``ruff`` (pyproject.toml / ruff.toml present)
      - ``mypy`` (pyproject.toml or mypy.ini present)
      - ``golangci-lint`` (go.mod + binary on PATH)

    Override the auto-detect by passing ``tools=["pyright", "ruff"]``.

    Persists to ``.map/<branch>/diagnostics_baseline.json`` with the
    shape::
        {
          "branch": ...,
          "recorded_at": ...,
          "tools": {
            "pyright": {"returncode": 1, "error_count": 123, "raw": "..."},
            "ruff":    {"returncode": 1, "error_count": 130, "raw": "..."},
            ...
          }
        }
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    branch_name = _sanitize_branch(branch)
    baseline_dir = project_dir / ".map" / branch_name
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "diagnostics_baseline.json"

    auto_tools: list[str] = []
    if tools is None:
        pyproject_exists = (project_dir / "pyproject.toml").exists()
        if pyproject_exists or (project_dir / "pyrightconfig.json").exists():
            auto_tools.append("pyright")
        if pyproject_exists or (project_dir / "ruff.toml").exists():
            auto_tools.append("ruff")
        if pyproject_exists or (project_dir / "mypy.ini").exists():
            auto_tools.append("mypy")
        if (project_dir / "go.mod").exists():
            auto_tools.append("golangci-lint")
        tools = auto_tools

    tool_commands = {
        "pyright": "pyright .",
        "ruff": "ruff check .",
        "mypy": "mypy .",
        "golangci-lint": "golangci-lint run",
    }
    tool_error_patterns = {
        # Pyright emits "Found N errors" at the tail of its output.
        "pyright": re.compile(r"(\d+)\s+errors?\b", re.IGNORECASE),
        # Ruff emits "Found N error(s)" before the diagnostic list.
        "ruff": re.compile(r"Found\s+(\d+)\s+error", re.IGNORECASE),
        # Mypy emits "Found N errors in M files".
        "mypy": re.compile(r"Found\s+(\d+)\s+error", re.IGNORECASE),
        # Golangci-lint emits each diagnostic on a line; "N issues" summary.
        "golangci-lint": re.compile(r"(\d+)\s+issues?", re.IGNORECASE),
    }

    import shutil as _shutil  # local import keeps the module-level imports tidy
    results: dict[str, dict[str, object]] = {}
    for tool in tools:
        cmd = tool_commands.get(tool)
        if not cmd:
            continue
        # Skip tools whose binary isn't available rather than fail the
        # whole snapshot. shutil.which is the portable way; the prior
        # subprocess(["command", ...]) variant CI-failed on Ubuntu
        # runners where `command` is only a POSIX shell builtin and
        # not a real binary in /usr/bin.
        binary = cmd.split()[0]
        if _shutil.which(binary) is None:
            results[tool] = {
                "status": "skipped",
                "reason": f"binary {binary!r} not on PATH",
            }
            continue
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=project_dir,
                capture_output=True, text=True, timeout=timeout_seconds,
            )
            returncode = proc.returncode
            combined_output = proc.stdout + "\n" + proc.stderr
        except subprocess.TimeoutExpired as exc:
            results[tool] = {
                "status": "timeout",
                "elapsed_seconds": timeout_seconds,
                "reason": str(exc),
            }
            continue
        except OSError as exc:
            results[tool] = {
                "status": "error",
                "reason": str(exc),
            }
            continue
        pattern = tool_error_patterns.get(tool)
        error_count = 0
        if pattern:
            for m in pattern.finditer(combined_output):
                try:
                    error_count = max(error_count, int(m.group(1)))
                except ValueError:
                    continue
        # Cap raw output so the JSON doesn't grow unbounded on 1000-error runs.
        raw_capped = combined_output[:8000]
        results[tool] = {
            "status": "success",
            "command": cmd,
            "returncode": returncode,
            "error_count": error_count,
            "raw": raw_capped,
        }

    payload: dict[str, object] = {
        "branch": branch_name,
        "recorded_at": _utc_timestamp(),
        "tools": results,
    }
    baseline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def list_diagnostics_baseline(branch: str) -> dict[str, object]:
    """Return the recorded diagnostics baseline; used by subtasks to
    compute "delta vs baseline" for each static-analysis tool."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    branch_name = _sanitize_branch(branch)
    baseline_path = project_dir / ".map" / branch_name / "diagnostics_baseline.json"
    if not baseline_path.exists():
        return {
            "status": "no_baseline",
            "branch": branch_name,
            "message": (
                "No diagnostics_baseline.json — run record_diagnostics_baseline "
                "at INIT_STATE to snapshot pre-existing pyright/ruff/mypy noise."
            ),
        }
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"read failed: {exc}"}


def record_test_baseline(
    branch: str,
    test_command: str = "",
    *,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Record a pre-flight test baseline so subtasks can distinguish
    "this regression is mine" from "this was broken before I started".

    Called at INIT_STATE (1.6) or any point before subtask execution.
    Runs ``test_command`` (auto-detected if empty), captures stdout +
    return code + parsed FAILED lines, persists to
    ``.map/<branch>/test_baseline.json``. Future subtasks can compare
    new failures against this baseline.

    Auto-detection prefers, in order:
      - ``make test`` if a Makefile with a ``test:`` target exists
      - ``pytest`` (no arguments) if pyproject.toml or pytest.ini present
      - ``go test ./...`` if go.mod present
      - ``cargo test`` if Cargo.toml present
    Empty auto-detect ⇒ status="skipped" (no test harness found).

    Returns dict with status, command, returncode, baseline_failures (list of
    failing test names parsed from stdout), and elapsed_seconds.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    branch_name = _sanitize_branch(branch)
    baseline_dir = project_dir / ".map" / branch_name
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "test_baseline.json"

    cmd_str = test_command.strip()
    auto_detected_command = ""
    if not cmd_str:
        # Auto-detect a sensible default. Cheap shell probes only.
        if (project_dir / "Makefile").exists():
            try:
                mk_text = (project_dir / "Makefile").read_text(encoding="utf-8")
                if re.search(r"^test:", mk_text, re.MULTILINE):
                    auto_detected_command = "make test"
            except OSError:
                pass
        if not auto_detected_command:
            if (project_dir / "pyproject.toml").exists() or (project_dir / "pytest.ini").exists():
                auto_detected_command = "pytest"
            elif (project_dir / "go.mod").exists():
                auto_detected_command = "go test ./..."
            elif (project_dir / "Cargo.toml").exists():
                auto_detected_command = "cargo test"
        cmd_str = auto_detected_command

    if not cmd_str:
        payload = {
            "branch": branch_name,
            "status": "skipped",
            "reason": "no test harness detected (Makefile / pytest / go.mod / Cargo.toml)",
            "recorded_at": _utc_timestamp(),
        }
        baseline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    started = time.time()
    try:
        proc = subprocess.run(
            cmd_str,
            shell=True,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timed_out = True
    except OSError as exc:
        return {
            "status": "error",
            "message": f"test invocation failed: {exc}",
        }
    elapsed = round(time.time() - started, 2)

    # Parse failing tests from stdout. Heuristics cover pytest "FAILED"
    # lines and Go's "--- FAIL: TestX" pattern; anything else falls back
    # to "see stdout".
    failures: list[str] = []
    for line in (stdout + "\n" + stderr).splitlines():
        line = line.strip()
        # pytest: "FAILED tests/test_foo.py::TestBar::test_baz - ..."
        m = re.match(r"^FAILED (\S+)", line)
        if m:
            failures.append(m.group(1))
            continue
        # Go: "--- FAIL: TestFoo (0.01s)"
        m = re.match(r"^--- FAIL: (\S+)", line)
        if m:
            failures.append(m.group(1))
            continue
        # Cargo: "test foo::bar ... FAILED"
        m = re.match(r"^test (\S+)\s+\.\.\.\s+FAILED", line)
        if m:
            failures.append(m.group(1))

    payload: dict[str, object] = {
        "branch": branch_name,
        "status": "success" if returncode == 0 else "baseline_failures",
        "command": cmd_str,
        "auto_detected": bool(auto_detected_command),
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": elapsed,
        "baseline_failures": sorted(set(failures)),
        "recorded_at": _utc_timestamp(),
    }
    baseline_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def list_baseline_failures(branch: str) -> dict[str, object]:
    """Read the recorded test baseline; useful for subtasks comparing
    new failures against pre-existing ones."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    branch_name = _sanitize_branch(branch)
    baseline_path = project_dir / ".map" / branch_name / "test_baseline.json"
    if not baseline_path.exists():
        return {
            "status": "no_baseline",
            "branch": branch_name,
            "message": (
                "No test_baseline.json — run record_test_baseline at "
                "INIT_STATE to capture pre-existing failures."
            ),
            "baseline_failures": [],
        }
    try:
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"read failed: {exc}"}
    failures = data.get("baseline_failures", [])
    if not isinstance(failures, list):
        failures = []
    return {
        "status": "success",
        "branch": branch_name,
        "command": data.get("command", ""),
        "returncode": data.get("returncode"),
        "baseline_failures": failures,
        "recorded_at": data.get("recorded_at"),
    }


def _acknowledged_diagnostics_path(branch: str) -> Path:
    """Return the per-branch acknowledged-diagnostics ledger path."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    return project_dir / ".map" / _sanitize_branch(branch) / "acknowledged_diagnostics.json"


def _diagnostic_signature(text: str) -> str:
    """Canonicalize a diagnostic line into a stable comparison key.

    Strips leading/trailing whitespace and collapses interior runs of
    whitespace to a single space so cosmetic re-flow doesn't bust the
    match. Callers may pass any text form they wish to acknowledge —
    the comparison is whole-line, not pattern-based.
    """
    return " ".join((text or "").split()).strip()


def acknowledge_diagnostic(
    branch: str, signature: str, reason: str = ""
) -> dict[str, object]:
    """Mark a diagnostic as known/deferred so reporters can suppress it.

    Use case: pre-existing Pyright noise like ``_rescore_cached_findings
    is not accessed`` surfaces on every subtask but isn't caused by the
    current change. Without an acknowledged-baseline mechanism each
    Monitor pass re-flags the same line, drowning real signals.

    The ledger lives at ``.map/<branch>/acknowledged_diagnostics.json``;
    entries are keyed by canonical signature (whitespace-normalised line
    text). Duplicate acknowledgements update the ``reason`` and bump
    ``last_seen_at`` instead of adding a second entry.

    Returns the persisted entry plus an ``already_acknowledged`` flag.
    """
    key = _diagnostic_signature(signature)
    if not key:
        return {"status": "error", "message": "empty signature"}
    path = _acknowledged_diagnostics_path(branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, object] = {"entries": {}}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ledger = data
        except (json.JSONDecodeError, OSError):
            pass
    entries = ledger.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        ledger["entries"] = entries
    existing = entries.get(key)
    now = _utc_timestamp()
    already = isinstance(existing, dict)
    if already:
        existing["reason"] = reason or existing.get("reason", "")
        existing["last_seen_at"] = now
        entry = existing
    else:
        entry = {
            "signature": key,
            "reason": reason,
            "acknowledged_at": now,
            "last_seen_at": now,
        }
        entries[key] = entry
    try:
        path.write_text(
            json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        return {"status": "error", "message": f"write failed: {exc}"}
    return {
        "status": "success",
        "branch": branch,
        "signature": key,
        "entry": entry,
        "already_acknowledged": already,
    }


def list_acknowledged_diagnostics(branch: str) -> dict[str, object]:
    """Return all acknowledged diagnostics on the branch (newest first)."""
    path = _acknowledged_diagnostics_path(branch)
    if not path.exists():
        return {"status": "success", "branch": branch, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"read failed: {exc}"}
    if not isinstance(data, dict):
        return {"status": "success", "branch": branch, "entries": []}
    entries_map = data.get("entries")
    if not isinstance(entries_map, dict):
        return {"status": "success", "branch": branch, "entries": []}
    entries = sorted(
        (e for e in entries_map.values() if isinstance(e, dict)),
        key=lambda e: str(e.get("acknowledged_at", "")),
        reverse=True,
    )
    return {"status": "success", "branch": branch, "entries": entries}


def is_diagnostic_acknowledged(branch: str, signature: str) -> bool:
    """Return True iff the diagnostic signature is in the acknowledged ledger."""
    key = _diagnostic_signature(signature)
    if not key:
        return False
    path = _acknowledged_diagnostics_path(branch)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return False
    return key in entries


def detect_already_done(
    branch: str, subtask_id: str, *, since_ref: Optional[str] = None
) -> dict:
    """Heuristic: does git history suggest the subtask is already shipped?

    Returns ``status``:
      "likely_done" — every affected_file exists AND has at least one commit
        in the configured window (``since_ref`` default: ``HEAD~50``).
      "partial" — some affected_files have commits, some don't / are missing.
      "unclear" — no evidence either way (fresh files, no history).
      "error" — blueprint / git unavailable.

    Pragmatic, not authoritative: callers should still review the listed
    commits before invoking ``mark_subtask_complete``.
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    bp = load_blueprint(branch_name, project_dir=project_dir)
    if bp is None:
        return {"status": "error", "message": "blueprint.json not found"}
    sub = get_subtask_from_blueprint(bp, subtask_id)
    if sub is None:
        return {"status": "error", "message": f"subtask {subtask_id!r} not in blueprint"}

    raw = sub.get("affected_files", []) or []
    # Affected paths in blueprints sometimes carry " (new)" suffixes — strip
    # them so git understands the path.
    files = sorted({
        re.split(r"\s+\(", str(p).strip())[0]
        for p in raw
        if isinstance(p, str) and p.strip()
    })
    if not files:
        return {
            "status": "unclear",
            "subtask_id": subtask_id,
            "message": "no affected_files declared",
        }

    requested_ref = since_ref or "HEAD~50"
    # Probe the requested ref; if it can't be resolved (e.g., HEAD~50 in a
    # repo with only 3 commits), fall back to the entire reachable history.
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", requested_ref],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=5,
    )
    window_ref: Optional[str] = requested_ref if probe.returncode == 0 else None
    evidence: list[dict] = []
    missing: list[str] = []
    have_commit: list[str] = []
    for path in files:
        full = project_dir / path
        if not full.exists():
            missing.append(path)
            continue
        log_cmd = ["git", "log", "--oneline"]
        if window_ref:
            log_cmd.append(f"{window_ref}..HEAD")
        log_cmd.extend(["--", path])
        try:
            log_proc = subprocess.run(
                log_cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "error",
                "message": f"git log failed for {path}: {exc}",
            }
        commits = [
            line.strip()
            for line in log_proc.stdout.splitlines()
            if line.strip()
        ]
        if commits:
            have_commit.append(path)
            evidence.append({"path": path, "commits": commits[:5]})
        else:
            missing.append(path)

    if missing:
        status = "partial" if have_commit else "unclear"
    else:
        status = "likely_done"

    return {
        "status": status,
        "subtask_id": subtask_id,
        "window_ref": window_ref or "all-history",
        "expected_files": files,
        "have_commits": have_commit,
        "missing_or_no_commits": missing,
        "evidence": evidence,
    }


def _scope_baseline_path(branch: str, project_dir: Path) -> Path:
    return project_dir / ".map" / _sanitize_branch(branch) / "scope-baseline.json"


def _subtask_baseline_path(branch: str, subtask_id: str, project_dir: Path) -> Path:
    return (
        project_dir
        / ".map"
        / _sanitize_branch(branch)
        / "subtask-baselines"
        / f"{subtask_id}.json"
    )


def record_subtask_baseline(branch: str, subtask_id: str) -> dict:
    """Snapshot the current `git status --porcelain` set + HEAD SHA as a
    per-subtask baseline that validate_mutation_boundary will subtract
    from `actual` for THIS subtask only — independent from the
    branch-wide scope-baseline.

    Fires automatically at validate_step("2.2") (RESEARCH start) so each
    subtask's mutation boundary check sees only changes since RESEARCH began,
    not the cumulative branch diff. The branch-wide
    .map/<branch>/scope-baseline.json still applies on top as a
    coarse filter.

    Added 2026-05-26: ``head_sha`` field captures the commit SHA at
    baseline time so refresh_blueprint_affected_files can resolve the
    full per-subtask diff (committed + uncommitted) instead of seeing
    porcelain-only and recording an empty current set after a clean
    per-subtask commit.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": f"git status failed: {exc}"}
    if proc.returncode != 0:
        return {
            "status": "error",
            "message": f"git status non-zero: {proc.stderr.strip() or 'no stderr'}",
        }
    files: list[str] = []
    for raw in proc.stdout.splitlines():
        if len(raw) >= 4:
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if (
                path
                and not path.startswith(".map/")
                and not path.startswith(".codex/")
                and not path.startswith(".agents/")
            ):
                files.append(path)
    # Capture HEAD SHA so downstream commits can be diffed against this
    # baseline. Fresh repos with no commits return non-zero — fall back to
    # None (refresh / validate code handles that case).
    head_sha: Optional[str] = None
    try:
        head_proc = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if head_proc.returncode == 0:
            candidate = head_proc.stdout.strip()
            if candidate:
                head_sha = candidate
    except (OSError, subprocess.TimeoutExpired):
        pass
    path = _subtask_baseline_path(branch, subtask_id, project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "branch": _sanitize_branch(branch),
        "subtask_id": subtask_id,
        "recorded_at": _utc_timestamp(),
        "files": sorted(set(files)),
        "head_sha": head_sha,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "status": "success",
        "path": str(path),
        "count": len(files),
        "head_sha": head_sha,
    }


def subtask_boundary_compact_check(branch: str) -> dict:
    """Decide whether the operator should force-compact at the current
    subtask boundary. Reads the project's MAP config + the latest Claude
    Code session jsonl and returns an "advice" payload — the actual
    /compact dispatch is still the operator's call (Claude Code hooks
    can't fire slash commands themselves).

    The cooldown matches context-meter.py (5 min) so two consecutive
    subtasks won't both nag.

    Returns: {status, used, threshold, hard_threshold, force_compact (bool),
             advice, since_last_compact_seconds}.
    """
    import time
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    branch_name = _sanitize_branch(branch)
    policy = _map_config_str(project_dir, "compression_policy", "never")
    configured_threshold = _map_config_int(
        project_dir, "compression_threshold_tokens", 120_000
    )
    threshold = _effective_compression_threshold(
        policy, configured_threshold
    )
    if threshold is None:
        return {"status": "policy_never"}

    marker = project_dir / ".map" / branch_name / "last-compact.marker"
    since_last_compact: Optional[float] = None
    if marker.exists():
        since_last_compact = time.time() - marker.stat().st_mtime
        if since_last_compact < 5 * 60:
            return {
                "status": "cooldown",
                "since_last_compact_seconds": since_last_compact,
                "advice": "compact ran recently; skip force-compact",
            }

    log_dir = _claude_code_log_dir(project_dir)
    used = 0
    if log_dir is not None:
        try:
            latest = max(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            used = _count_last_turn_tokens(latest)
        except (ValueError, OSError):
            used = 0

    # The auto-checkpoint kicks in when current usage is past the soft
    # threshold — twice the threshold means we've blown past the context
    # meter's nudge and the operator has missed the suggestion. At that
    # point the boundary advice escalates to "force compact".
    hard_threshold = threshold * 2
    if used >= hard_threshold:
        force = True
        advice = (
            f"FORCE COMPACT NOW — used {used}/{threshold} ({used / threshold:.0%}). "
            "Subtask boundary is the safe place to /compact + resume."
        )
    elif used >= threshold:
        force = False
        advice = (
            f"Recommend compact at this subtask boundary — used "
            f"{used}/{threshold} ({used / threshold:.0%})."
        )
    else:
        force = False
        advice = "below threshold; continue"

    return {
        "status": "success",
        "used": used,
        "threshold": threshold,
        "hard_threshold": hard_threshold,
        "force_compact": force,
        "advice": advice,
        "since_last_compact_seconds": since_last_compact,
    }


def list_plans() -> dict:
    """Enumerate per-branch plan artifacts under .map/<branch>/ so the
    operator can pick scope from a multi-roadmap workspace without grepping.

    Returns: list of {branch, has_blueprint, has_task_plan, has_step_state,
    workflow_status, completed_at, plan_mtime, subtask_count}.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    map_root = project_dir / ".map"
    if not map_root.is_dir():
        return {"status": "success", "plans": []}
    plans: list[dict[str, object]] = []
    for entry in sorted(map_root.iterdir()):
        if not entry.is_dir() or entry.name == "scripts":
            continue
        branch_name = entry.name
        blueprint_path = entry / "blueprint.json"
        task_plan_path = entry / f"task_plan_{branch_name}.md"
        state_path = entry / "step_state.json"
        info: dict[str, object] = {
            "branch": branch_name,
            "has_blueprint": blueprint_path.exists(),
            "has_task_plan": task_plan_path.exists(),
            "has_step_state": state_path.exists(),
            "plan_mtime": None,
            "workflow_status": None,
            "completed_at": None,
            "subtask_count": None,
        }
        if task_plan_path.exists():
            info["plan_mtime"] = (
                _dt_from_mtime(task_plan_path.stat().st_mtime)
            )
        if blueprint_path.exists():
            try:
                bp = json.loads(blueprint_path.read_text(encoding="utf-8"))
                if isinstance(bp.get("blueprint"), dict):
                    bp = bp["blueprint"]
                if isinstance(bp.get("subtasks"), list):
                    info["subtask_count"] = len(bp["subtasks"])
            except (json.JSONDecodeError, OSError):
                pass
        if state_path.exists():
            try:
                st = json.loads(state_path.read_text(encoding="utf-8"))
                info["workflow_status"] = st.get("workflow_status")
                info["completed_at"] = st.get("completed_at")
            except (json.JSONDecodeError, OSError):
                pass
        plans.append(info)
    return {"status": "success", "plans": plans}


def _dt_from_mtime(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _read_existing_plan_goal(spec_path: Path, task_plan_path: Path) -> str:
    """Extract the existing plan's goal text from task_plan + spec for resume
    comparison. Prefers the task plan's ``- Goal:`` line (falling back to the
    whole ``## Overview``/``## Goal`` block), and folds in the task-plan and spec
    H1 titles so short distinctive goals still yield significant tokens. Returns
    a de-duplicated newline-joined string ("" when nothing is extractable)."""
    parts: list[str] = []
    if task_plan_path.exists():
        try:
            content = task_plan_path.read_text(encoding="utf-8")
            block_match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
            if block_match:
                block = block_match.group(1).strip()
                goal_line = re.search(r"(?im)^[-*]?\s*Goal:\s*(.+)$", block)
                parts.append(goal_line.group(1).strip() if goal_line else block)
            title_match = re.search(
                r"(?m)^#\s+(?:Task Plan:\s*)?(.+)$", content
            )
            if title_match:
                parts.append(title_match.group(1).strip())
        except OSError:
            pass
    if spec_path.exists():
        try:
            content = spec_path.read_text(encoding="utf-8")
            spec_title = re.search(r"(?m)^#\s+(?:Spec:\s*)?(.+)$", content)
            if spec_title:
                parts.append(spec_title.group(1).strip())
        except OSError:
            pass
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            unique.append(part)
    return "\n".join(unique).strip()


def check_plan_resume(request: str = "", branch: Optional[str] = None) -> dict:
    """Resume-detection preflight for /map-plan on the branch-keyed
    ``.map/<branch>/`` layout (issue #166).

    A single git branch can host more than one sequential planning effort over
    its lifetime. Keying resume purely on "does ``step_state.json`` exist?"
    falsely reports "plan complete" for a brand-new, unrelated request and, if
    the operator proceeds anyway, silently clobbers the prior plan's
    spec/blueprint/task_plan. This preflight compares the existing plan's goal
    against the incoming request and returns one of three verdicts:

    - ``no_plan``: no prior planning artifacts on the branch — plan fresh.
    - ``resume``: artifacts exist AND the request matches the existing plan's
      goal (or no request text / extractable goal was available to compare) —
      apply the per-artifact resume rules (existing ``step_state`` => complete).
    - ``goal_mismatch``: artifacts exist BUT the request describes a DIFFERENT
      goal than the completed plan — do NOT report "plan complete"; archive or
      rename the prior ``.map/<branch>/`` artifacts (or plan on a fresh branch)
      before planning the new goal, with operator confirmation.

    Goal comparison is a deterministic token-overlap heuristic (see
    RESUME_GOAL_MISMATCH_CONTAINMENT) — intentionally conservative so a real
    resume with a shorter paraphrase is never falsely diverted.
    """
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    branch_dir = project_dir / ".map" / branch_name
    findings_path = branch_dir / f"findings_{branch_name}.md"
    spec_path = branch_dir / f"spec_{branch_name}.md"
    task_plan_path = branch_dir / f"task_plan_{branch_name}.md"
    state_path = branch_dir / "step_state.json"

    artifacts = {
        "findings": findings_path.exists(),
        "spec": spec_path.exists(),
        "task_plan": task_plan_path.exists(),
        "step_state": state_path.exists(),
    }
    has_plan = (
        artifacts["spec"] or artifacts["task_plan"] or artifacts["step_state"]
    )
    request_text = (request or "").strip()

    if not has_plan:
        return {
            "status": "ok",
            "branch": branch_name,
            "verdict": "no_plan",
            "artifacts": artifacts,
            "existing_goal": None,
            "request": request_text,
            "overlap": 0.0,
            "containment": 0.0,
            "shared_terms": [],
            "recommendation": (
                f"No prior planning artifacts on branch '{branch_name}'. "
                "Proceed with a fresh plan from Step 0."
            ),
        }

    existing_goal = _read_existing_plan_goal(spec_path, task_plan_path)
    goal_tokens = _tokenize_learning_text(existing_goal)
    request_tokens = _tokenize_learning_text(request_text)
    shared = sorted(goal_tokens & request_tokens)
    union = goal_tokens | request_tokens
    overlap = round(len(shared) / len(union), 3) if union else 0.0
    min_len = min(len(goal_tokens), len(request_tokens))
    containment = round(len(shared) / min_len, 3) if min_len else 0.0

    comparable = bool(
        request_text
        and goal_tokens
        and request_tokens
        and min_len >= RESUME_MIN_TOKENS_FOR_MISMATCH
    )

    if comparable and containment < RESUME_GOAL_MISMATCH_CONTAINMENT:
        verdict = "goal_mismatch"
        snippet = " ".join(existing_goal.split())
        if len(snippet) > 160:
            snippet = snippet[:157].rstrip() + "..."
        recommendation = (
            f"The existing plan on branch '{branch_name}' targets a DIFFERENT "
            f"goal than the current request (goal-overlap {overlap}, "
            f"containment {containment} < {RESUME_GOAL_MISMATCH_CONTAINMENT}). "
            f'Existing goal: "{snippet}". Do NOT report "plan complete" / STOP. '
            f"Archive or rename the prior .map/{branch_name}/ artifacts (or run "
            "/map-plan on a fresh branch) so the completed plan is preserved, "
            "then plan the new goal. Confirm the archival/overwrite with the "
            "operator before writing."
        )
    else:
        verdict = "resume"
        if not request_text:
            reason = "No request text supplied to compare against the existing plan"
        elif not existing_goal:
            reason = "Existing plan has no extractable goal to compare"
        else:
            reason = (
                "Incoming request matches the existing plan goal "
                f"(overlap {overlap}, containment {containment})"
            )
        recommendation = (
            f"{reason}. Apply the per-artifact resume rules: existing "
            "step_state => plan complete (print checkpoint and STOP); existing "
            "spec/task_plan => skip those steps and reuse them."
        )

    return {
        "status": "ok",
        "branch": branch_name,
        "verdict": verdict,
        "artifacts": artifacts,
        "existing_goal": existing_goal or None,
        "request": request_text,
        "overlap": overlap,
        "containment": containment,
        "shared_terms": shared,
        "recommendation": recommendation,
    }


def record_scope_baseline(branch: str) -> dict:
    """Snapshot the current uncommitted / untracked file set as a baseline
    that validate_mutation_boundary will subtract from `actual` on future
    runs. Use when the branch carries pre-existing artifacts from prior
    waves that would otherwise flood every subtask with `warning`.

    Returns dict with: status, path, files (count + list).
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "message": f"git status failed: {exc}"}
    if status_proc.returncode != 0:
        return {
            "status": "error",
            "message": (
                f"git status non-zero (exit {status_proc.returncode}): "
                f"{status_proc.stderr.strip() or 'no stderr'}"
            ),
        }
    files: list[str] = []
    for raw in status_proc.stdout.splitlines():
        if len(raw) >= 4:
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if (
                path
                and not path.startswith(".map/")
                and not path.startswith(".codex/")
                and not path.startswith(".agents/")
            ):
                files.append(path)
    path = _scope_baseline_path(branch, project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "branch": _sanitize_branch(branch),
        "recorded_at": _utc_timestamp(),
        "files": sorted(set(files)),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"status": "success", "path": str(path), "count": len(payload["files"]), "files": payload["files"]}


def _resolve_subtask_diff_base(
    branch_name: str, subtask_id: str, project_dir: Path
) -> Optional[str]:
    """Auto-resolve the git base_ref for diffing a subtask's mutation surface.

    Resolution order: ``last_subtask_commit_sha`` from step_state → ``HEAD`` →
    ``None`` (a fresh repo with no commits, where the caller falls through to
    porcelain-only). The returned ref is meant to be diffed against the WORKING
    TREE (``git diff --name-only <ref>``).

    Crucial special case (#162): the documented per-subtask close order is
    ``commit → record_subtask_result --commit-sha → validate_step 2.4``.
    ``record_subtask_result`` advances ``last_subtask_commit_sha`` to the
    subtask's OWN commit, so by the time the boundary check runs the working
    tree is clean and ``git diff <own-commit>`` is empty — which previously
    mis-reported "no files changed" and tripped the false-progress guard on
    every committed subtask. When the auto-resolved base equals the commit
    recorded for THIS subtask, re-base onto that commit's parent so the
    committed work shows up in the diff. The parent is probed first so a root
    commit (no parent) safely keeps the commit itself.
    """
    base_ref: Optional[str] = None
    recorded: Optional[str] = None
    state_file = project_dir / ".map" / branch_name / "step_state.json"
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            last_sha = state_data.get("last_subtask_commit_sha")
            if isinstance(last_sha, str) and last_sha:
                base_ref = last_sha
            results = state_data.get("subtask_results", {})
            if isinstance(results, dict):
                entry = results.get(subtask_id)
                if isinstance(entry, dict):
                    rc = entry.get("commit_sha")
                    if isinstance(rc, str) and rc:
                        recorded = rc
        except (json.JSONDecodeError, OSError):
            pass
    if base_ref and recorded and base_ref == recorded:
        parent_probe = subprocess.run(
            ["git", "rev-parse", "--verify", f"{recorded}^"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if parent_probe.returncode == 0:
            return f"{recorded}^"
        # Root commit (no parent): no usable parent to re-base onto. Keep the
        # commit itself; a subtask whose own commit is the repo's first commit
        # is not a real MAP scenario (the framework is always installed atop
        # prior history).
        return base_ref
    if base_ref:
        return base_ref
    # No recorded subtask commit — probe HEAD before using it; `git rev-parse
    # HEAD` fails in a fresh repo with no commits, and we want porcelain-only
    # rather than a confusing "ambiguous HEAD".
    head_probe = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if head_probe.returncode == 0:
        return "HEAD"
    return None


def validate_mutation_boundary(
    branch: str, subtask_id: str, base_ref: Optional[str] = None
) -> dict:
    """Compare actual repo diff against the subtask's declared affected_files.

    Reads blueprint.subtasks[subtask_id].affected_files (the planned mutation
    surface) and computes the actual paths touched relative to ``base_ref``
    (default: last_subtask_commit_sha from step_state, falling back to
    ``HEAD``). Reports any files outside the planned surface as ``unexpected``.

    Default behaviour is WARN-only: returns the report and appends a row to
    ``.map/<branch>/scope-violations.log`` but exits success-equivalent.
    Strict mode is opt-in via ``MAP_STRICT_SCOPE=1`` in the env — callers (the
    CLI, Monitor) can then treat ``status="violation"`` as a hard reject.

    Return shape on success::
        {
          "status": "clean" | "warning" | "violation",
          "subtask_id": str,
          "base_ref": str,
          "expected": [str],   # declared affected_files
          "actual": [str],     # files actually changed
          "unexpected": [str], # actual but not expected (real scope leak)
          "allowed_test_files": [str],  # out-of-scope but test-convention;
                                        # implied by test-alongside policy, NOT leaks
          "strict": bool,
        }

    Return shape on error (blueprint missing, subtask unknown, git failure,
    not a git repo)::
        {
          "status": "error",
          "subtask_id": str,
          "message": str,      # diagnostic message
        }
    Callers that treat this as a mandatory gate MUST handle "error" — the
    CLI exits non-zero in that case so Bash callers can `set -e` and Monitor
    can verdict `valid: false` with the message.
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    blueprint = load_blueprint(branch_name, project_dir=project_dir)
    if blueprint is None:
        return {
            "status": "error",
            "message": "blueprint.json not found",
            "subtask_id": subtask_id,
        }
    subtask = get_subtask_from_blueprint(blueprint, subtask_id)
    if subtask is None:
        return {
            "status": "error",
            "message": f"subtask {subtask_id!r} not in blueprint",
            "subtask_id": subtask_id,
        }

    expected_raw = subtask.get("affected_files", []) or []
    expected = sorted({str(p) for p in expected_raw if isinstance(p, str)})

    # Pick a base_ref. Caller's explicit arg wins; otherwise auto-resolve from
    # last_subtask_commit_sha (so the diff covers only THIS subtask's work),
    # re-basing onto the commit's parent when the subtask is already committed
    # (#162). If neither resolves to a real commit, skip the commit-range diff
    # entirely and rely on porcelain (uncommitted + untracked) — the only sane
    # behaviour in a brand-new repo before its first commit.
    base_ref_explicit = bool(base_ref)
    if not base_ref:
        base_ref = _resolve_subtask_diff_base(branch_name, subtask_id, project_dir)

    try:
        if base_ref:
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", base_ref],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            diff_result = None
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "error",
            "message": f"git invocation failed: {exc}",
            "subtask_id": subtask_id,
        }

    # `git status --porcelain` non-zero ⇒ not a git repo (or git is broken);
    # without it we can't observe uncommitted work, and treating `actual_set`
    # as empty would mis-report `clean`. Always a hard error.
    if status_result.returncode != 0:
        return {
            "status": "error",
            "subtask_id": subtask_id,
            "message": (
                f"`git status --porcelain` failed (exit {status_result.returncode}): "
                f"{status_result.stderr.strip() or 'no stderr'}"
            ),
        }
    # An explicit invalid base_ref (caller-supplied) is a hard error so the
    # operator sees the mistake. An auto-resolved one that became "no diff"
    # is acceptable (we just fall through to porcelain-only).
    if diff_result is not None and diff_result.returncode != 0:
        if base_ref_explicit:
            return {
                "status": "error",
                "subtask_id": subtask_id,
                "message": (
                    f"`git diff --name-only {base_ref}` failed "
                    f"(exit {diff_result.returncode}): "
                    f"{diff_result.stderr.strip() or 'no stderr'}"
                ),
            }
        diff_result = None  # treat as no commit-range diff available

    actual_set: set[str] = set()
    if diff_result is not None:
        actual_set.update(
            line.strip() for line in diff_result.stdout.splitlines() if line.strip()
        )
    # Include uncommitted (worktree + index) paths from porcelain output.
    for raw in status_result.stdout.splitlines():
        if len(raw) >= 4:
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                actual_set.add(path)

    # Filter framework-owned paths that are NEVER part of a subtask's mutation
    # surface: `.map/` carries orchestrator artifacts (blueprint, step_state,
    # research outputs, scope logs), `.codex/` mirrors Codex-side config, and
    # `.agents/` holds Codex repository skills.
    # Treating them as scope leaks would produce a flood of false positives.
    actual_set = {
        p for p in actual_set
        if not p.startswith(".map/")
        and not p.startswith(".codex/")
        and not p.startswith(".agents/")
    }

    # Baseline filter — two layers:
    #   1. Per-subtask baseline (auto-snapshotted at validate_step('2.2')):
    #      everything dirty in the worktree when THIS subtask started
    #      RESEARCH belongs to prior subtasks. Subtract it so per-subtask
    #      mutation check only sees changes made during the current run.
    #   2. Branch-wide baseline (operator opt-in via record_scope_baseline):
    #      coarser filter for branches that carry pre-existing artifacts
    #      from outside the workflow entirely.
    baseline_files: set[str] = set()
    subtask_baseline_path = _subtask_baseline_path(
        branch_name, subtask_id, project_dir
    )
    if subtask_baseline_path.exists():
        try:
            data = json.loads(subtask_baseline_path.read_text(encoding="utf-8"))
            raw = data.get("files", [])
            if isinstance(raw, list):
                baseline_files.update(str(p) for p in raw if isinstance(p, str))
        except (json.JSONDecodeError, OSError):
            pass
    branch_baseline_path = _scope_baseline_path(branch_name, project_dir)
    if branch_baseline_path.exists():
        try:
            data = json.loads(branch_baseline_path.read_text(encoding="utf-8"))
            raw = data.get("files", [])
            if isinstance(raw, list):
                baseline_files.update(str(p) for p in raw if isinstance(p, str))
        except (json.JSONDecodeError, OSError):
            pass
    if baseline_files:
        actual_set = {p for p in actual_set if p not in baseline_files}

    actual = sorted(actual_set)
    expected_set = set(expected)
    # Test-alongside policy (#163): co-authored test files (test_*.* / *_test.* /
    # *.spec.* / *.test.* / conftest.py / anything under a tests/ dir) are
    # IMPLIED by any subtask whose contract requires tests, so they are NOT
    # scope leaks even when the decomposer listed only production modules in
    # affected_files. Exclude them from `unexpected` (they stay in `actual`,
    # which reflects reality and keeps the false-progress check honest); surface
    # them separately as `allowed_test_files` for auditability. A test file the
    # blueprint DID declare stays in expected_set and is never an "allowed"
    # extra. This makes the check independent of decomposer description wording.
    out_of_scope = [p for p in actual if p not in expected_set]
    allowed_test_files = sorted(p for p in out_of_scope if _is_test_path(p))
    unexpected = sorted(p for p in out_of_scope if not _is_test_path(p))
    strict = os.environ.get("MAP_STRICT_SCOPE", "0") == "1"

    if not unexpected:
        status = "clean"
    elif strict:
        status = "violation"
    else:
        status = "warning"

    # Diagnostic hint: when the warning fires, surface WHY base_ref was
    # selected so the operator can disambiguate "real scope leak" from
    # "I forgot to commit the prior subtask + auto-detect grabbed HEAD".
    # The recommended recovery commands are inline so the operator
    # doesn't have to dig through docs.
    diagnostic_hint = None
    if unexpected:
        if not base_ref_explicit:
            diagnostic_hint = (
                "If 'unexpected' includes files from prior subtasks: either "
                "(a) commit those subtasks and re-run record_subtask_result "
                "--commit-sha <SHA> so this check uses the right base, OR "
                "(b) run `python3 .map/scripts/map_step_runner.py "
                "record_scope_baseline <branch>` to lock the current "
                "uncommitted state as the branch baseline."
            )
        elif not baseline_files:
            diagnostic_hint = (
                "No per-subtask baseline was found — RESEARCH (2.2) likely "
                "didn't auto-snapshot. Run record_subtask_baseline "
                f"{branch} {subtask_id} before MONITOR to filter prior work."
            )

    report = {
        "status": status,
        "subtask_id": subtask_id,
        "base_ref": base_ref,
        "expected": expected,
        "actual": actual,
        "unexpected": unexpected,
        "allowed_test_files": allowed_test_files,
        "strict": strict,
    }
    if diagnostic_hint:
        report["diagnostic_hint"] = diagnostic_hint

    if unexpected:
        log_path = project_dir / ".map" / branch_name / "scope-violations.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            entry = {
                "at": _utc_timestamp(),
                **report,
            }
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    return report


_TEST_DIR_SEGMENTS = {"tests", "test", "testing", "__tests__", "spec", "specs"}


def _is_test_path(path: str) -> bool:
    """Heuristic: does this repo-relative path look like a test file?

    Used only to lower the regression-risk signal for files that two
    subtasks both touched but that cannot themselves cause a regression in
    another subtask's production code (a shared *test* edit is far less
    dangerous than a shared *source* edit). Conventions covered: a ``tests/``
    / ``test/`` / ``__tests__/`` path segment, ``test_*`` / ``*_test`` base
    names, ``*.test.*`` / ``*.spec.*`` suffixes (pytest, go test, jest), and
    pytest's ``conftest.py`` shared-fixture files.
    """
    norm = path.replace("\\", "/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return False
    base = parts[-1]
    if base == "conftest.py":  # pytest shared fixtures — test infra, not source
        return True
    if any(seg in _TEST_DIR_SEGMENTS for seg in parts[:-1]):
        return True
    if re.match(r"(?:test_.+|.+_test)\.[A-Za-z0-9]+$", base):
        return True
    if re.search(r"\.(?:test|spec)\.[A-Za-z0-9]+$", base):
        return True
    return False


def _current_subtask_changed_files(
    branch_name: str, subtask_id: str, project_dir: Path
) -> Optional[set[str]]:
    """Files touched by the in-flight subtask since the prior subtask commit.

    Mirrors ``validate_mutation_boundary``'s diff strategy (commit-range diff
    against ``last_subtask_commit_sha`` — falling back to ``HEAD`` — unioned
    with ``git status --porcelain`` for uncommitted work, minus the framework
    ``.map/`` / ``.codex/`` / ``.agents/`` paths and the per-subtask baseline).
    Returns
    ``None`` on any git failure so callers can fail safe to a full gate
    instead of silently assuming "no changes".

    Shares ``validate_mutation_boundary``'s base-ref resolution (incl. the #162
    re-base onto the subtask's commit parent when it is already committed) via
    ``_resolve_subtask_diff_base``.
    """
    base_ref = _resolve_subtask_diff_base(branch_name, subtask_id, project_dir)

    try:
        if base_ref:
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", base_ref],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            diff_result = None
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if status_result.returncode != 0:
        return None
    if diff_result is not None and diff_result.returncode != 0:
        # A base_ref was resolved (last_subtask_commit_sha or HEAD) but its
        # diff failed — e.g. a stale SHA after a rebase. We cannot determine
        # this subtask's committed surface, and porcelain alone would miss
        # committed work (reporting an empty change set on a clean worktree).
        # Fail safe to "unknown" so the caller forces a full gate, matching
        # this function's documented contract.
        return None

    changed: set[str] = set()
    if diff_result is not None:
        changed.update(
            line.strip() for line in diff_result.stdout.splitlines() if line.strip()
        )
    for raw in status_result.stdout.splitlines():
        if len(raw) >= 4:
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                changed.add(path)

    changed = {
        p for p in changed
        if not p.startswith(".map/")
        and not p.startswith(".codex/")
        and not p.startswith(".agents/")
    }

    baseline_path = _subtask_baseline_path(branch_name, subtask_id, project_dir)
    if baseline_path.exists():
        try:
            baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
            raw_baseline = baseline_data.get("files", [])
            if isinstance(raw_baseline, list):
                baseline_set = {
                    str(p) for p in raw_baseline if isinstance(p, str)
                }
                changed -= baseline_set
        except (json.JSONDecodeError, OSError):
            pass
    return changed


def detect_cross_subtask_regression_risk(
    branch: str, subtask_id: str
) -> dict:
    """Flag when the in-flight subtask edits files that prior subtasks owned.

    Per-subtask Monitor validates only the current subtask's contract and the
    files it touched — it is structurally blind to regressions this change
    induces on *other* subtasks' code. The canonical failure (run
    ``new-road-quantum``): ST-009 edited ``chunked_review_pipeline.py``, which
    seven earlier subtasks had also edited, and broke a stub-path test that
    only surfaced at the final full-suite gate, eight subtasks later.

    This is the deterministic signal the skill uses to decide between a
    ``-k``-scoped test run and the full suite: when the current diff overlaps a
    file a prior subtask changed, a scoped run cannot see the regression, so
    the full suite is mandatory before recording the subtask.

    Returns::
        {
          "status": "ok" | "unknown",
          "subtask_id": str,
          "at_risk": bool,
          "recommended_gate": "full_suite" | "scoped",
          "shared_files": [str],          # all overlapping files
          "shared_source_files": [str],   # non-test overlap (drives at_risk)
          "shared_test_files": [str],     # test-only overlap (weaker signal)
          "prior_owners": {file: [ST-id]},
          "current_changed_files": [str],
          "reason": str,
        }

    ``status="unknown"`` with ``at_risk=true`` / ``recommended_gate=
    "full_suite"`` is the fail-safe when the current diff cannot be computed
    (git error): the gate defaults to thorough rather than silently scoped.
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    prior_owners: dict[str, list[str]] = {}
    state_file = project_dir / ".map" / branch_name / "step_state.json"
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state_data = {}
        results = state_data.get("subtask_results")
        if isinstance(results, dict):
            for prior_id, result in results.items():
                if prior_id == subtask_id or not isinstance(result, dict):
                    continue
                files = result.get("files_changed")
                if not isinstance(files, list):
                    continue
                for path in files:
                    if isinstance(path, str) and path.strip():
                        prior_owners.setdefault(path, [])
                        if prior_id not in prior_owners[path]:
                            prior_owners[path].append(prior_id)

    current = _current_subtask_changed_files(branch_name, subtask_id, project_dir)
    if current is None:
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "at_risk": True,
            "recommended_gate": "full_suite",
            "shared_files": [],
            "shared_source_files": [],
            "shared_test_files": [],
            "prior_owners": prior_owners,
            "current_changed_files": [],
            "reason": (
                "Could not compute the current subtask diff (git unavailable "
                "or not a repo). Defaulting to full_suite as a fail-safe — a "
                "scoped run could hide a cross-subtask regression."
            ),
        }

    shared = sorted(p for p in current if p in prior_owners)
    shared_test = [p for p in shared if _is_test_path(p)]
    shared_source = [p for p in shared if not _is_test_path(p)]
    at_risk = bool(shared_source)

    if at_risk:
        offenders = ", ".join(
            f"{p} (also: {', '.join(prior_owners[p])})" for p in shared_source
        )
        reason = (
            f"Subtask edits {len(shared_source)} source file(s) prior subtasks "
            f"already modified: {offenders}. Run the FULL test suite (no -k "
            "filter) before recording — a scoped run cannot catch a regression "
            "this change induces on prior subtasks' code or stub/no-op paths."
        )
    elif shared_test:
        reason = (
            f"Overlap only on test file(s): {', '.join(shared_test)}. Low "
            "regression risk to production code; a scoped run is acceptable, "
            "but re-run the affected test modules in full."
        )
    else:
        reason = (
            "No overlap with files changed by prior subtasks — a scoped test "
            "run is sufficient for this subtask."
        )

    return {
        "status": "ok",
        "subtask_id": subtask_id,
        "at_risk": at_risk,
        "recommended_gate": "full_suite" if at_risk else "scoped",
        "shared_files": shared,
        "shared_source_files": shared_source,
        "shared_test_files": shared_test,
        "prior_owners": {p: prior_owners[p] for p in shared},
        "current_changed_files": sorted(current),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Actor files-changed mismatch detector
# ---------------------------------------------------------------------------


def detect_actor_files_changed_mismatch(
    branch: str, subtask_id: str, declared_files: list[str]
) -> dict:
    """Flag when an Actor declared files in its envelope that it never wrote.

    The canonical failure mode: the Actor response is truncated mid-edit
    (model context overflow, timeout). The files_changed envelope lists the
    intended targets, but the actual git diff is shorter — some files were
    never written. The Monitor's mutation-boundary check sees *actual* files
    only and cannot detect the omission; this detector closes that gap.

    Distinct from related detectors:
    - ``validate_mutation_boundary`` catches *wrote-but-NOT-declared* (scope
      creep — the opposite direction).
    - ``detect_truncated_agent_output`` checks JSON-envelope key completeness,
      not file-system writes.
    - THIS function checks *declared-but-not-written* only.  The load-bearing
      field is ``declared_not_written``.

    Returns::

        {
          "status": "ok" | "unknown",
          "subtask_id": str,
          "declared": [str],               # sorted; stripped declared_files
          "actual": [str],                 # sorted; files from git diff
          "declared_not_written": [str],   # sorted; declared minus actual
          "status_mismatch": bool,         # True when declared_not_written non-empty
          "recovery_instruction": str,     # non-empty only when status_mismatch
          "reason": str,                   # non-empty only on status=="unknown"
        }

    Fail-safe: any git failure → ``status="unknown"`` + ``status_mismatch=True``
    (never silently ``False``): the Actor gate must not pass blindly on a git
    error.
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    actual_set = _current_subtask_changed_files(branch_name, subtask_id, project_dir)
    if actual_set is None:
        # Intent: fail safe to mismatch so the gate cannot pass blindly.
        declared_sorted = sorted(d.strip() for d in (declared_files or []) if d.strip())
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "declared": declared_sorted,
            "actual": [],
            "declared_not_written": declared_sorted,
            "status_mismatch": True,
            "recovery_instruction": (
                "git diff unavailable (fail-safe — actual changes were NOT "
                f"consulted): treating all declared files as unwritten: {declared_sorted}. "
                "Re-invoke the Actor to finish any truncated edits and re-run this "
                "check once git is available; do NOT record the subtask until "
                "git diff --name-only covers every declared file."
            ),
            "reason": (
                "could not compute the actual diff (git unavailable) — "
                "assuming mismatch as a fail-safe."
            ),
        }

    declared = [d.strip() for d in (declared_files or []) if d.strip()]
    declared_not_written = sorted(d for d in declared if d not in actual_set)
    status_mismatch = bool(declared_not_written)

    recovery_instruction = ""
    if status_mismatch:
        recovery_instruction = (
            f"Actor declared files it did not write: {declared_not_written}. "
            "Its previous response was likely truncated mid-edit — re-invoke "
            "the Actor to finish those files; do NOT record the subtask until "
            "git diff --name-only covers every declared file."
        )

    return {
        "status": "ok",
        "subtask_id": subtask_id,
        "declared": sorted(declared),
        "actual": sorted(actual_set),
        "declared_not_written": declared_not_written,
        "status_mismatch": status_mismatch,
        "recovery_instruction": recovery_instruction,
        "reason": "",
    }


# ---------------------------------------------------------------------------
# Symbol blast-radius detector
# ---------------------------------------------------------------------------

# Directories/globs searched by _grep_external_callers
_GREP_SEARCH_PATHS = [".claude/skills", "src", ".map/scripts"]

# Maximum distinct symbols we'll send to git-grep before short-circuiting
_SYMBOL_GREP_CAP = 40

# Sentinel returned by _grep_external_callers on git/subprocess failure.
# Distinct from the legitimate "no matches" empty list — callers must treat
# any entry with note=="grep_error" as an unknown/fail-safe signal rather
# than evidence that no external callers exist.
_GREP_ERROR_SENTINEL = [{"symbol": "*", "file": "", "line": 0, "note": "grep_error"}]

# Generic process-entrypoint names excluded from blast-radius analysis. A
# function named ``main`` is invoked by convention (``if __name__ == "__main__"``
# inside its own file, or by the harness via a file path) — never imported as a
# shared helper. Treating it as a changed symbol matches the literal word "main"
# in every SKILL.md / settings.json and floods the gate with false callers.
_GENERIC_ENTRYPOINT_NAMES = frozenset({"main"})


def _is_reportable_symbol(name: str) -> bool:
    """Whether a module-level name is worth blast-radius caller analysis.

    Excludes dunders (``__x__``), names shorter than 3 characters, and generic
    process entrypoints (:data:`_GENERIC_ENTRYPOINT_NAMES`). Leading-underscore
    names such as ``_MONITOR_REQUIRED_KEYS`` are intentionally kept.
    """
    return (
        bool(name)
        and not (name.startswith("__") and name.endswith("__"))
        and len(name) >= 3
        and name not in _GENERIC_ENTRYPOINT_NAMES
    )


def _changed_line_numbers_by_file(diff_text: str) -> dict[str, set[int]]:
    """Parse a unified diff and return new-file line numbers of added lines per path.

    Only ``+``-prefixed lines (not ``+++`` headers) are recorded.  Context and
    ``-`` lines advance or preserve the new-file line counter respectively.

    Returns ``{relative_path: set_of_added_new_file_line_numbers}``.
    """
    result: dict[str, set[int]] = {}
    current_file: Optional[str] = None
    new_line: int = 0

    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw in diff_text.splitlines():
        # New file header: "+++ b/<path>"  (ignore /dev/null)
        if raw.startswith("+++ "):
            path = raw[4:]
            if path.startswith("b/"):
                path = path[2:]
            current_file = None if path == "/dev/null" else path
            new_line = 0
            continue

        if current_file is None:
            continue

        # Hunk header: "@@ -a,b +c,d @@"
        hm = hunk_header_re.match(raw)
        if hm:
            new_line = int(hm.group(1))
            continue

        if raw.startswith("+++") or raw.startswith("---"):
            # diff header lines — skip without touching counter
            continue

        if raw.startswith("+"):
            # Added line — record current new_line position then advance
            result.setdefault(current_file, set()).add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            # Removed line — does NOT advance new-file counter
            pass
        else:
            # Context line (space-prefixed or bare) — advance new-file counter
            new_line += 1

    return result


def _enclosing_changed_symbols(
    abs_path: Path, changed_lines: set[int]
) -> Optional[set[str]]:
    """Return top-level symbol names whose span covers any line in *changed_lines*.

    Recognises ``FunctionDef``, ``AsyncFunctionDef``, ``ClassDef``, ``Assign``
    with ``Name`` targets, and ``AnnAssign`` with a ``Name`` target.

    Excludes dunder names (start AND end with ``__``), names shorter than 3
    characters, and generic process entrypoints (``main``) via
    :func:`_is_reportable_symbol`.  Leading-underscore names such as
    ``_MONITOR_REQUIRED_KEYS`` are intentionally kept.

    Returns ``None`` on ``SyntaxError`` or ``OSError`` (caller must treat this as
    a fail-safe / unknown signal).
    """
    try:
        source = abs_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(abs_path))
    except (SyntaxError, OSError):
        return None

    symbols: set[str] = set()

    for node in ast.iter_child_nodes(tree):
        name: Optional[str] = None
        start: int = 0
        end: int = 0

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            # Span starts at earliest decorator line (if any), otherwise def/class line
            decorator_lines = [d.lineno for d in node.decorator_list]
            start = min([node.lineno] + decorator_lines)
            end = node.end_lineno or node.lineno

            if _is_reportable_symbol(name):
                if any(start <= ln <= end for ln in changed_lines):
                    symbols.add(name)

        elif isinstance(node, ast.Assign):
            end = node.end_lineno or node.lineno
            start = node.lineno
            for target in node.targets:
                if isinstance(target, ast.Name):
                    tname = target.id
                    if _is_reportable_symbol(tname) and any(
                        start <= ln <= end for ln in changed_lines
                    ):
                        symbols.add(tname)

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                tname = node.target.id
                start = node.lineno
                end = node.end_lineno or node.lineno
                if _is_reportable_symbol(tname) and any(
                    start <= ln <= end for ln in changed_lines
                ):
                    symbols.add(tname)

    return symbols


def _grep_external_callers(
    symbols: set[str], affected_files: list[str], project_dir: Path
) -> list[dict]:
    """Search for references to *symbols* in the project outside *affected_files*.

    Uses a single batched ``git grep`` call with a whole-word alternation regex.
    Returns a list of ``{"symbol": str, "file": str, "line": int}`` dicts, sorted
    deterministically and deduped.

    Symbol cap: when ``len(symbols) > _SYMBOL_GREP_CAP`` the search is skipped
    and a single marker entry is returned so the caller still recommends
    ``validate_callers`` (too many symbols → thorough gate is the safe default).

    Returns ``_GREP_ERROR_SENTINEL`` (a one-entry list with ``note="grep_error"``)
    on ``OSError``, ``subprocess.TimeoutExpired``, or a git-grep exit code not in
    ``(0, 1)``.  Callers must detect the sentinel (``entry["note"] == "grep_error"``)
    and fail-safe to ``validate_callers`` rather than treating it as evidence that
    no external callers exist.  Do NOT revert this to an empty-list return — an
    empty list means "grep ran and found nothing", which is a different signal.
    """
    if not symbols:
        return []

    # Cap: too many symbols → conservatively flag for caller validation
    if len(symbols) > _SYMBOL_GREP_CAP:
        return [{"symbol": "*", "file": "", "line": 0, "note": "skipped_too_many_symbols"}]

    affected_set = set(affected_files)

    # Build alternation pattern; sort for determinism
    alternation = "|".join(re.escape(s) for s in sorted(symbols))
    pattern = f"({alternation})"

    try:
        result = subprocess.run(
            ["git", "grep", "-n", "-E", "-w", pattern, "--"] + _GREP_SEARCH_PATHS,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return list(_GREP_ERROR_SENTINEL)

    # git grep exits with 1 when no matches (not an error); >1 is a real error
    if result.returncode not in (0, 1):
        return list(_GREP_ERROR_SENTINEL)

    seen: set[tuple[str, str, int]] = set()
    callers: list[dict] = []

    for raw in result.stdout.splitlines():
        # Format: path:lineno:content
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, lineno_str, content = parts[0], parts[1], parts[2]

        # Exclude matches inside the subtask's own affected files
        if file_path in affected_set:
            continue

        try:
            lineno = int(lineno_str)
        except ValueError:
            continue

        # Determine which symbol(s) matched this line
        for sym in sorted(symbols):
            if re.search(rf"\b{re.escape(sym)}\b", content):
                key = (sym, file_path, lineno)
                if key in seen:
                    continue
                seen.add(key)
                callers.append({"symbol": sym, "file": file_path, "line": lineno})

    callers.sort(key=lambda d: (d["file"], d["line"], d["symbol"]))
    return callers


def detect_symbol_blast_radius(branch: str, subtask_id: str) -> dict:
    """Flag when a subtask changed a module-level symbol referenced outside its scope.

    This is an *advisory* detector — it does not block; it informs the Monitor
    gate of external callers that need explicit validation.  The canonical failure
    mode it prevents: a shared helper (e.g. ``chunked_review_pipeline.py``)
    is re-derived in one subtask and silently breaks callers in other subtasks
    that are never re-tested in the scoped gate.

    Returns::

        {
          "status": "ok" | "unknown",
          "subtask_id": str,
          "changed_symbols": [str],         # sorted; module-level additions
          "external_callers": [...],         # {symbol, file, line} outside affected_files
          "recommended_gate": "validate_callers" | "scoped",
          "reason": str,
        }

    Fail-safe: any git failure → ``status="unknown"`` +
    ``recommended_gate="validate_callers"`` (never silently ``"scoped"``).
    """
    branch_name = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # ------------------------------------------------------------------
    # 1. Resolve blueprint + affected_files
    # ------------------------------------------------------------------
    blueprint = load_blueprint(branch_name, project_dir)
    subtask: Optional[dict] = None
    if blueprint is not None:
        subtask = get_subtask_from_blueprint(blueprint, subtask_id)
    affected_files: list[str] = []
    if subtask is not None:
        raw_af = subtask.get("affected_files") or []
        if isinstance(raw_af, list):
            affected_files = [str(f) for f in raw_af if f]

    # ------------------------------------------------------------------
    # 2. Compute changed files for this subtask
    # ------------------------------------------------------------------
    changed = _current_subtask_changed_files(branch_name, subtask_id, project_dir)
    if changed is None:
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "validate_callers",
            "reason": (
                "Could not compute the current subtask diff (git unavailable) "
                "— defaulting to validate_callers as a fail-safe."
            ),
        }

    # ------------------------------------------------------------------
    # 3. Filter to runtime Python files
    # ------------------------------------------------------------------
    runtime_changed = [
        p for p in changed if p.endswith(".py") and not _is_test_path(p)
    ]
    if not runtime_changed:
        return {
            "status": "ok",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "scoped",
            "reason": "No runtime .py symbols changed — scoped gate is sufficient.",
        }

    # ------------------------------------------------------------------
    # 4. Get diff text for runtime files
    # ------------------------------------------------------------------
    base_ref: Optional[str] = None
    state_file = project_dir / ".map" / branch_name / "step_state.json"
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            last_sha = state_data.get("last_subtask_commit_sha")
            if isinstance(last_sha, str) and last_sha:
                base_ref = last_sha
        except (json.JSONDecodeError, OSError):
            pass
    if not base_ref:
        try:
            head_probe = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if head_probe.returncode == 0:
                base_ref = "HEAD"
        except (OSError, subprocess.TimeoutExpired):
            return {
                "status": "unknown",
                "subtask_id": subtask_id,
                "changed_symbols": [],
                "external_callers": [],
                "recommended_gate": "validate_callers",
                "reason": (
                    "git rev-parse failed or timed out — "
                    "defaulting to validate_callers as a fail-safe."
                ),
            }

    if not base_ref:
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "validate_callers",
            "reason": (
                "Could not resolve a git base ref for the diff — "
                "defaulting to validate_callers as a fail-safe."
            ),
        }

    try:
        diff_result = subprocess.run(
            ["git", "diff", base_ref, "--"] + runtime_changed,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "validate_callers",
            "reason": (
                "git diff timed out or failed — "
                "defaulting to validate_callers as a fail-safe."
            ),
        }

    if diff_result.returncode != 0:
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "validate_callers",
            "reason": (
                f"git diff returned non-zero exit code {diff_result.returncode} "
                "— defaulting to validate_callers as a fail-safe."
            ),
        }

    diff_text = diff_result.stdout

    # ------------------------------------------------------------------
    # 5. Extract changed module-level symbols via AST enclosing-symbol mapping
    # ------------------------------------------------------------------
    lines_by_file = _changed_line_numbers_by_file(diff_text)
    changed_symbols: set[str] = set()
    for path in runtime_changed:
        enc = _enclosing_changed_symbols(project_dir / path, lines_by_file.get(path, set()))
        if enc is None:
            # AST parse or read error — fail safe
            return {
                "status": "unknown",
                "subtask_id": subtask_id,
                "changed_symbols": [],
                "external_callers": [],
                "recommended_gate": "validate_callers",
                "reason": (
                    f"Could not parse {path} — defaulting to validate_callers as a fail-safe."
                ),
            }
        changed_symbols |= enc

    if not changed_symbols:
        return {
            "status": "ok",
            "subtask_id": subtask_id,
            "changed_symbols": [],
            "external_callers": [],
            "recommended_gate": "scoped",
            "reason": (
                "Runtime .py files changed but no module-level symbols affected "
                "— scoped gate is sufficient."
            ),
        }

    # ------------------------------------------------------------------
    # 6. Find external callers
    # ------------------------------------------------------------------
    external_callers = _grep_external_callers(changed_symbols, affected_files, project_dir)

    # Detect grep-error sentinel: git/subprocess failure inside _grep_external_callers.
    # An empty list is a legitimate "no matches" result; the sentinel is the fail-safe.
    grep_errored = any(c.get("note") == "grep_error" for c in external_callers)
    if grep_errored:
        return {
            "status": "unknown",
            "subtask_id": subtask_id,
            "changed_symbols": sorted(changed_symbols),
            "external_callers": external_callers,
            "recommended_gate": "validate_callers",
            "reason": (
                "git grep failed — defaulting to validate_callers as a fail-safe."
            ),
        }

    recommended_gate = "validate_callers" if external_callers else "scoped"

    if external_callers and external_callers[0].get("note") == "skipped_too_many_symbols":
        reason = (
            f"Too many changed symbols ({len(changed_symbols)} > {_SYMBOL_GREP_CAP}) "
            "— grep skipped; validate_callers applied conservatively."
        )
    elif external_callers:
        caller_summary = ", ".join(
            f"{c['symbol']} in {c['file']}:{c['line']}"
            for c in external_callers[:5]
        )
        extra = f" (+{len(external_callers) - 5} more)" if len(external_callers) > 5 else ""
        reason = (
            f"Changed symbol(s) {sorted(changed_symbols)!r} are referenced "
            f"outside affected_files: {caller_summary}{extra}. "
            "All external callers must be explicitly validated."
        )
    else:
        reason = (
            f"Changed symbol(s) {sorted(changed_symbols)!r} have no external "
            "callers outside affected_files — scoped gate is sufficient."
        )

    return {
        "status": "ok",
        "subtask_id": subtask_id,
        "changed_symbols": sorted(changed_symbols),
        "external_callers": external_callers,
        "recommended_gate": recommended_gate,
        "reason": reason,
    }


def build_context_block(branch: str, current_subtask_id: str) -> str:
    """Build structured context block for Actor prompt.

    Returns formatted string with:
    - Goal (from task_plan.md)
    - Current subtask full details (from blueprint)
    - Upstream results (from step_state.json subtask_results)
    - Plan overview (all subtasks as ID + title + status one-liners)
    - Repo delta (differential insight, if last_subtask_commit_sha available)

    Returns empty string if blueprint not found (graceful fallback).
    """
    branch = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    blueprint = load_blueprint(branch, project_dir=project_dir)
    if not blueprint:
        return ""

    # Goal — read directly via project_dir for consistency
    goal = None
    plan_file = project_dir / ".map" / branch / f"task_plan_{branch}.md"
    try:
        if plan_file.exists():
            content = plan_file.read_text(encoding="utf-8")
            match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
            if match:
                goal = match.group(1).strip()
    except OSError:
        pass
    goal = goal or "No goal found"
    # Trim trailing whitespace; do not truncate — the user disabled context
    # clipping in build_context_block because the visible "[truncated]" /
    # "[TRUNCATED] see token_budget.json" markers were getting in the way of
    # downstream Actor runs (it lost real subtask description text).
    goal = goal.strip()

    # Current subtask full details
    current = get_subtask_from_blueprint(blueprint, current_subtask_id)
    if not current:
        return ""

    minimality = _load_minimality_level(project_dir)

    current_details = []
    # Emit the full prose `description` field (no per-field truncation).
    description_text = current.get("description")
    if isinstance(description_text, str) and description_text.strip():
        current_details.append(f"Description: {description_text.strip()}")
    current_details.append(f"AAG Contract: {current.get('aag_contract', 'N/A')}")
    current_details.append(
        f"Subtask contract: expected_diff_size={current.get('expected_diff_size', 'unknown')}, "
        f"concern_type={current.get('concern_type', 'unknown')}, "
        f"one_logical_step={current.get('one_logical_step', 'unknown')}, "
        f"risk_level={current.get('risk_level', 'unknown')}"
    )
    files_value = current.get("affected_files", [])
    files = files_value if isinstance(files_value, list) else []
    if files:
        # Emit every affected file — no "+N more" elision.
        current_details.append(
            f"Affected files: {', '.join(str(f) for f in files)}"
        )
    criteria_value = current.get("validation_criteria", [])
    criteria = criteria_value if isinstance(criteria_value, list) else []
    if criteria:
        current_details.append("Validation criteria:")
        for c in criteria:
            current_details.append(f"  - {c}")

    # Plan overview with statuses from step_state.json
    state_path = project_dir / ".map" / branch / "step_state.json"
    subtask_phases: dict = {}
    subtask_results: dict = {}
    last_sha: Optional[str] = None
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            subtask_phases = state.get("subtask_phases", {})
            subtask_results = state.get("subtask_results", {})
            last_sha = state.get("last_subtask_commit_sha")
    except (json.JSONDecodeError, OSError):
        pass

    overview_lines = []
    for st in blueprint.get("subtasks", []):
        st_id = st.get("id", "?")
        st_title = st.get("title", "Untitled")
        if st_id == current_subtask_id:
            overview_lines.append(
                f"  [>>] {st_id}: {st_title} (IN PROGRESS) <- current"
            )
        elif st_id in subtask_results:
            status = subtask_results[st_id].get("status", "done")
            overview_lines.append(f"  [x] {st_id}: {st_title} ({status})")
        else:
            phase = subtask_phases.get(st_id, "pending")
            overview_lines.append(f"  [ ] {st_id}: {st_title} ({phase})")

    # Upstream results (only for dependencies)
    upstream_ids = get_upstream_ids(blueprint, current_subtask_id)
    upstream_lines = []
    for up_id in upstream_ids:
        if up_id in subtask_results:
            result = subtask_results[up_id]
            fc_value = result.get("files_changed", [])
            fc = fc_value if isinstance(fc_value, list) else []
            status = result.get("status", "unknown")
            summary = result.get("summary", "")
            line = f"  {up_id}: files={list(fc)}, status={status}"
            if summary:
                line += f", summary={summary}"
            upstream_lines.append(line)
        else:
            upstream_lines.append(f"  {up_id}: (not yet completed)")

    # Assemble block
    parts = [
        "<map_context>",
        f"# Goal: {goal}",
        "",
        f"# Current Subtask: {current_subtask_id} — {current.get('title', 'Untitled')}",
    ]
    doctrine_block = _minimality_doctrine_block(minimality)
    if doctrine_block:
        parts.append("")
        parts.append(doctrine_block)
    parts.extend(current_details)
    if upstream_lines:
        parts.append("")
        parts.append(f"# Upstream Results (dependencies of {current_subtask_id}):")
        parts.extend(upstream_lines)

    # Inline the latest research artifact for THIS subtask so callers stop
    # having to glue load_research output into the Actor prompt by hand.
    # Tries actor → monitor → decomposer kinds in order; if none exists,
    # nothing is added (RESEARCH may not have run yet). No length cap — the
    # user disabled context-block truncation; the full research file
    # contents are inlined so Actor doesn't have to re-read the file.
    try:
        for _research_kind in ("actor", "monitor", "decomposer"):
            _research_text = load_research(
                branch, current_subtask_id, kind=_research_kind
            )
            if _research_text:
                parts.append("")
                parts.append(
                    f"# Research Findings ({current_subtask_id}, kind={_research_kind}):"
                )
                parts.append(_research_text)
                break
    except (ValueError, OSError):
        pass

    parts.append("")
    parts.append(f"# Plan Overview ({len(blueprint.get('subtasks', []))} subtasks):")
    parts.extend(overview_lines)

    # Repo Delta (via compute_differential_insight from repo_insight)
    if last_sha:
        try:
            import sys
            import importlib

            repo_insight = sys.modules.get("mapify_cli.repo_insight")
            if repo_insight is None:
                repo_insight = importlib.import_module("mapify_cli.repo_insight")
            compute_differential_insight = getattr(
                repo_insight, "compute_differential_insight", None
            )
            if compute_differential_insight is None:
                raise ImportError("compute_differential_insight not available")

            insight = compute_differential_insight(project_dir, last_sha)
            if insight.get("error"):
                insight = {}
            changed = insight.get("changed_files") or []
            deleted = insight.get("deleted_files") or []
            if changed or deleted:
                parts.append("")
                parts.append("# Repo Delta (files changed since last subtask):")
                for f in changed:
                    parts.append(f"  {f}")
                if deleted:
                    parts.append("# Deleted since last subtask:")
                    for f in deleted:
                        parts.append(f"  (deleted) {f}")
        except ImportError:
            # Fallback: repo_insight not available in standalone .map/ context
            pass

    parts.append("</map_context>")

    # All truncation infrastructure removed by user directive: no per-field
    # caps, no budget-based clipping, no token-budget accounting roundtrip.
    # build_context_block emits the raw text — the operator wants the full
    # picture, period. If the block grows beyond context window, the user
    # will opt into /compact themselves (compression_policy default = never).
    return "\n".join(parts)


def _load_minimality_level(project_dir: Path) -> str:
    """Return the configured minimality level from .map/config.yaml."""
    level = _map_config_str(project_dir, "minimality", "off")
    if level not in VALID_MINIMALITY_LEVELS:
        return "off"
    return level


def _minimality_doctrine_block(level: str) -> str:
    """Return the runtime-only Actor doctrine block for non-off minimality."""
    if level == "off":
        return ""
    intensity = {
        "lite": "Build what was asked, then name the lazier safe alternative in one line; do not silently drop work.",
        "full": "Apply the ladder actively before adding code; choose the smaller safe path unless a real blocker requires expansion.",
        "ultra": "Apply the ladder aggressively and surface YAGNI/defer decisions, but never prune explicit, safety, data, or contract work silently.",
    }.get(level, "Build what was asked and prefer the fewest safe moving parts.")
    return "\n".join(
        [
            "<MAP_Minimality_Doctrine>",
            f"Level: {level}",
            f"Intensity: {intensity}",
            "Production-grade means the smallest sufficient safe change, not maximal code.",
            "Decision ladder, stop at the first rung that satisfies the contract:",
            "1. Does this need to exist at all? If no, mark it YAGNI and explain; do not silently omit explicit requirements.",
            "2. Standard library does it? Use that.",
            "3. Native platform feature covers it? Use that.",
            "4. Already-installed project dependency solves it? Use that; do not add a dependency for a few lines.",
            "5. Can it be one clear line? Prefer one clear line.",
            "6. Otherwise write the minimum maintainable code that works.",
            "Shell/Core rule: shell code at trust boundaries stays defensive; core private helpers stay small.",
            "Hard exceptions: security, accessibility, data integrity, real error handling that prevents data loss, and explicitly requested behavior always win over minimality.",
            "When choosing a deliberate simplification, include `map:simplification:` with the ceiling and upgrade path. The marker is evidence, not an exemption.",
            "If retry feedback asks for expansion, re-add code only for named BLOCKER items.",
            "</MAP_Minimality_Doctrine>",
        ]
    )


def prepare_detached_review(
    bundle_path: Optional[str] = None,
    *,
    branch: Optional[str] = None,
    commit: Optional[str] = None,
    target_dir: Optional[str] = None,
) -> dict[str, object]:
    """Prepare a clean review context via git worktree add --detach.

    Returns a dict with:
      status: "success" | "unavailable" | "error"
      reason: human-readable explanation
      worktree_path: absolute str path (only on success, else None)
      commit: short SHA used (only on success, else None)
      bundle_path: input bundle path echoed back if provided
      mutated_source: bool — MUST be False; the source branch is never mutated
    """
    _base: dict[str, object] = {
        "bundle_path": bundle_path,
        "worktree_path": None,
        "commit": None,
        "reason": "",
        "mutated_source": False,
    }

    # Resolve target directory
    # ``get_branch_name`` already sanitizes; explicit ``branch`` callers must be
    # sanitized too (same rationale as ``create_review_bundle``).
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    if target_dir is not None:
        resolved_target = Path(target_dir).resolve()
    else:
        resolved_target = get_branch_dir(branch_name).resolve() / "detached-review"

    # Path-traversal guard: resolved_target MUST stay under .map/<branch>/ or the .map/
    # root. A user-supplied target_dir like "../../tmp/evil" resolves outside both and is
    # rejected to keep the worktree mutation contained to MAP-owned scope.
    branch_dir_resolved = get_branch_dir(branch_name).resolve()
    map_root_resolved = (Path.cwd().resolve() / ".map").resolve()
    if not (
        resolved_target.is_relative_to(branch_dir_resolved)
        or resolved_target.is_relative_to(map_root_resolved)
    ):
        return {
            **_base,
            "status": "error",
            "reason": "target_dir escapes .map/<branch>/ scope",
        }

    # Edge Case 6 + INV-6: never overwrite an existing path
    if resolved_target.exists():
        return {
            **_base,
            "status": "unavailable",
            "reason": f"Detached worktree path already exists: {resolved_target}",
        }

    # Resolve commit SHA (short) — abort if not in a git repo
    if commit is not None:
        short_sha = commit
    else:
        try:
            rev_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except OSError as e:
            return {
                **_base,
                "status": "unavailable",
                "reason": f"git rev-parse failed: {e}",
            }
        if rev_result.returncode != 0:
            return {
                **_base,
                "status": "unavailable",
                "reason": f"git rev-parse failed: {rev_result.stderr.strip()}",
            }
        short_sha = rev_result.stdout.strip()

    # Create the detached worktree — the only git mutation is a new worktree entry
    try:
        wt_result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(resolved_target), short_sha],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except OSError as e:
        return {
            **_base,
            "status": "error",
            "reason": f"git worktree add failed: {e}",
        }

    if wt_result.returncode != 0:
        return {
            **_base,
            "status": "error",
            "reason": f"git worktree add failed: {wt_result.stderr.strip()}",
        }

    return {
        **_base,
        "status": "success",
        "worktree_path": str(resolved_target),
        "commit": short_sha,
        "reason": "",
    }


# ---------------------------------------------------------------------------
# Agent-failure telemetry (ST-003)
# ---------------------------------------------------------------------------

_AGENT_FAILURE_LABELS: frozenset[str] = frozenset(
    {"format_violation", "missing_field", "truncated"}
)


def _agent_failure_log_path(branch: Optional[str] = None) -> Path:
    """Return branch-scoped agent failure JSONL path."""
    return get_branch_dir(branch) / "agent_failure_events.jsonl"


def _validate_agent_failure_event(event: dict[str, object]) -> list[str]:
    """Validate an agent failure event dict.

    Returns an empty list for a valid event, or a non-empty list of
    human-readable reason strings describing every violation found.
    """
    reasons: list[str] = []
    for field in ("agent", "phase", "failure_label", "timestamp"):
        if not event.get(field):
            reasons.append(f"missing required field: {field!r}")
    label = event.get("failure_label")
    if label and label not in _AGENT_FAILURE_LABELS:
        reasons.append(
            f"failure_label {label!r} is not one of {sorted(_AGENT_FAILURE_LABELS)}"
        )
    return reasons


def log_agent_failure(
    agent: str,
    phase: str,
    failure_label: str,
    reasons: Optional[list[str]] = None,
    retry: bool = False,
    schema: Optional[str] = None,
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Append one agent-failure event to the branch-scoped JSONL log.

    Every agent-derived string is routed through _sanitize_for_json (INV-8)
    before the event is serialised, ensuring jq-parseability via bash pipes.

    Returns:
        On success: {"status": "ok", "path": str, "event": dict}
        On validation failure: {"status": "error", "reasons": list[str], "path": None}
    """
    sanitized_reasons: list[str] = [
        _sanitize_for_json(r) for r in (reasons or [])
    ]
    event: dict[str, object] = {
        "agent": _sanitize_for_json(agent),
        "phase": _sanitize_for_json(phase),
        "failure_label": _sanitize_for_json(failure_label),
        "reasons": sanitized_reasons,
        "retry": retry,
        "schema": _sanitize_for_json(schema) if schema is not None else None,
        "timestamp": _utc_timestamp(),
    }
    validation_errors = _validate_agent_failure_event(event)
    if validation_errors:
        return {"status": "error", "reasons": validation_errors, "path": None}
    path = _agent_failure_log_path(branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")
    return {"status": "ok", "path": str(path), "event": event}


if __name__ == "__main__":
    # Simple CLI interface for testing
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 map_step_runner.py <function> [args...]")
        sys.exit(1)

    func_name = sys.argv[1]

    if func_name == "update_step_state_batch" and len(sys.argv) >= 3:
        updates_json = sys.argv[2]
        try:
            updates = json.loads(updates_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON: {e}"}))
            sys.exit(1)
        result = update_step_state_batch(updates)
        print(json.dumps(result, indent=2))

    elif func_name == "update_step_state" and len(sys.argv) >= 5:
        result = update_step_state(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif func_name == "update_plan_status" and len(sys.argv) >= 4:
        result = update_plan_status(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif func_name == "validate_checkpoint" and len(sys.argv) >= 4:
        required = sys.argv[3].split(",")
        result = validate_checkpoint(sys.argv[2], required)
        print(json.dumps(result, indent=2))

    elif func_name == "read_current_goal":
        goal = read_current_goal()
        print(goal or "Goal not found")

    elif func_name == "get_current_phase":
        phase = get_current_phase()
        print(phase or "Phase not found")

    elif func_name == "ensure_human_artifacts":
        result = ensure_human_artifacts()
        print(json.dumps(result, indent=2))

    elif func_name == "next_numbered_artifact_path" and len(sys.argv) >= 3:
        result = next_numbered_artifact_path(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif func_name == "append_session_log" and len(sys.argv) >= 4:
        # Deprecated — kept for backward compatibility, returns {"status": "deprecated"}
        result = append_session_log(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif func_name == "write_verification_summary" and len(sys.argv) >= 3:
        verdict = sys.argv[2]
        task_title = sys.argv[3] if len(sys.argv) >= 4 else ""
        checks_run = sys.argv[4] if len(sys.argv) >= 5 else ""
        findings = sys.argv[5] if len(sys.argv) >= 6 else ""
        next_action = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = write_verification_summary(
            verdict, task_title, checks_run, findings, next_action
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_pr_draft":
        summary = sys.argv[2] if len(sys.argv) >= 3 else ""
        validation = sys.argv[3] if len(sys.argv) >= 4 else ""
        risks_follow_up = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = write_pr_draft(summary, validation, risks_follow_up)
        print(json.dumps(result, indent=2))

    elif func_name == "write_plan_review":
        summary = sys.argv[2] if len(sys.argv) >= 3 else ""
        high = sys.argv[3] if len(sys.argv) >= 4 else ""
        medium = sys.argv[4] if len(sys.argv) >= 5 else ""
        low = sys.argv[5] if len(sys.argv) >= 6 else ""
        resolved = sys.argv[6] if len(sys.argv) >= 7 else ""
        open_concerns = sys.argv[7] if len(sys.argv) >= 8 else ""
        recommendation = sys.argv[8] if len(sys.argv) >= 9 else "needs-revision"
        result = write_plan_review(
            summary, high, medium, low, resolved, open_concerns, recommendation
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_stage_gate" and len(sys.argv) >= 4:
        stage = sys.argv[2]
        verdict = sys.argv[3]
        source_artifact = sys.argv[4] if len(sys.argv) >= 5 else ""
        notes = sys.argv[5] if len(sys.argv) >= 6 else ""
        result = write_stage_gate(stage, verdict, source_artifact, notes)
        print(json.dumps(result, indent=2))

    elif func_name == "load_artifact_manifest":
        result = load_artifact_manifest()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "record_workflow_fit" and len(sys.argv) >= 3:
        # Two calling conventions supported:
        #   legacy (positional, deprecated):
        #     record_workflow_fit <workflow> <diff_size> <inv> <review>
        #         <ac> <tdd> [summary]
        #   keyword (preferred):
        #     record_workflow_fit <workflow> [--diff-size SIZE]
        #         [--has-new-invariants 0|1] [--needs-independent-review 0|1]
        #         [--has-clear-acceptance-criteria 0|1]
        #         [--test-first-required 0|1] [--summary "..."]
        # The keyword form prevents bool-order mix-ups the operator just
        # called out.
        recommended_workflow = sys.argv[2]
        rest = list(sys.argv[3:])
        if rest and not rest[0].startswith("--") and len(rest) >= 5:
            # Legacy positional path
            result = record_workflow_fit(
                recommended_workflow,
                rest[0],
                rest[1],
                rest[2],
                rest[3],
                rest[4],
                rest[5] if len(rest) >= 6 else "",
            )
        else:
            def _flag(name: str, default: str) -> str:
                if f"--{name}" in rest:
                    idx = rest.index(f"--{name}")
                    if idx + 1 < len(rest):
                        return rest[idx + 1]
                return default
            result = record_workflow_fit(
                recommended_workflow,
                expected_diff_size=_flag("diff-size", "medium"),
                has_new_invariants=_flag("has-new-invariants", "0"),
                needs_independent_review=_flag("needs-independent-review", "0"),
                has_clear_acceptance_criteria=_flag(
                    "has-clear-acceptance-criteria", "1"
                ),
                test_first_required=_flag("test-first-required", "0"),
                decision_summary=_flag("summary", ""),
            )
        print(json.dumps(result, indent=2))

    elif func_name == "record_plan_artifacts":
        result = record_plan_artifacts()
        print(json.dumps(result, indent=2))

    elif func_name == "validate_blueprint_contract":
        blueprint_path = sys.argv[2] if len(sys.argv) >= 3 else ""
        result = validate_blueprint_contract(blueprint_path)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "normalize_blueprint":
        extra = sys.argv[2:]
        dry_run = any(arg in ("--check", "--dry-run") for arg in extra)
        positional = [arg for arg in extra if not arg.startswith("--")]
        blueprint_path = positional[0] if positional else ""
        result = normalize_blueprint(blueprint_path, write=not dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if result.get("status") != "ok":
            sys.exit(1)

    elif func_name == "record_test_contract_handoff" and len(sys.argv) >= 3:
        subtask_id = sys.argv[2]
        failing_test_command = sys.argv[3] if len(sys.argv) >= 4 else ""
        test_files_csv = sys.argv[4] if len(sys.argv) >= 5 else ""
        contract_summary = sys.argv[5] if len(sys.argv) >= 6 else ""
        notes = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = record_test_contract_handoff(
            subtask_id,
            failing_test_command,
            test_files_csv,
            contract_summary,
            notes,
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_run_health_report":
        workflow = sys.argv[2] if len(sys.argv) >= 3 else "map-efficient"
        terminal_status = sys.argv[3] if len(sys.argv) >= 4 else ""
        result = write_run_health_report(workflow, terminal_status)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "validate_run_health_report":
        report_path = sys.argv[2] if len(sys.argv) >= 3 else ""
        result = validate_run_health_report(report_path)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "build_retry_quarantine":
        subtask_id = sys.argv[2] if len(sys.argv) >= 3 else "workflow"
        retry_count = int(sys.argv[3]) if len(sys.argv) >= 4 else 2
        monitor_feedback = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = build_retry_quarantine(subtask_id, retry_count, monitor_feedback)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "validate_retry_quarantine":
        quarantine_path = sys.argv[2] if len(sys.argv) >= 3 else ""
        result = validate_retry_quarantine(quarantine_path)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "create_review_bundle":
        result = create_review_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_review_prompts":
        import argparse as _ap

        _p = _ap.ArgumentParser(prog="map_step_runner.py build_review_prompts")
        _p.add_argument("--branch", default=None)
        _p.add_argument("--budget-tokens", type=int, default=None)
        _p.add_argument("--review-preferences", default="")
        _args = _p.parse_args(sys.argv[2:])
        result = build_review_prompts(
            branch=_args.branch,
            review_preferences=_args.review_preferences,
            budget_tokens=_args.budget_tokens,
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_handoff_bundle":
        result = build_handoff_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_review_handoff":
        result = build_review_handoff()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_acceptance_coverage_report":
        result = build_acceptance_coverage_report()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_prior_stage_consumption_report":
        stage = sys.argv[2] if len(sys.argv) >= 3 else "review"
        result = build_prior_stage_consumption_report(stage)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "validate_prior_stage_consumption":
        stage = sys.argv[2] if len(sys.argv) >= 3 else "review"
        result = build_prior_stage_consumption_report(stage)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "write_learning_handoff":
        workflow = sys.argv[2] if len(sys.argv) >= 3 else ""
        task_title = sys.argv[3] if len(sys.argv) >= 4 else ""
        outcome = sys.argv[4] if len(sys.argv) >= 5 else ""
        next_action = sys.argv[5] if len(sys.argv) >= 6 else ""
        notes = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = write_learning_handoff(
            workflow, task_title, outcome, next_action, notes
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "record_learning_consumption":
        summary_source = sys.argv[2] if len(sys.argv) >= 3 else "inline-summary"
        workflow = sys.argv[3] if len(sys.argv) >= 4 else ""
        result = record_learning_consumption(summary_source, workflow)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "ensure_known_issues_file":
        result = ensure_known_issues_file()
        print(json.dumps(result, indent=2))

    elif func_name == "ensure_active_issues_file":
        result = ensure_active_issues_file()
        print(json.dumps(result, indent=2))

    elif func_name == "replace_active_issues" and len(sys.argv) >= 4:
        stage = sys.argv[2]
        source_artifact = sys.argv[3]
        issues_text = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = replace_active_issues(stage, source_artifact, issues_text)
        print(json.dumps(result, indent=2))

    elif func_name == "add_known_issue" and len(sys.argv) >= 3:
        title = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) >= 4 else "accepted"
        notes = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = add_known_issue(title, status, notes)
        print(json.dumps(result, indent=2))

    elif func_name == "run_test_gate":
        result = run_test_gate()
        print(json.dumps(result, indent=2))

    elif func_name == "snapshot_code_state":
        result = snapshot_code_state()
        print(json.dumps(result, indent=2))

    elif func_name == "record_subtask_result":
        # Read JSON from stdin to avoid shell injection: {"files": [...], "status": "...", "summary": "...", "commit_sha": "..."}
        import sys as _sys
        try:
            data = json.loads(_sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON on stdin: {e}"}))
            _sys.exit(1)
        branch_name = get_branch_name()
        state_path = Path(f".map/{branch_name}/step_state.json")
        if not state_path.exists():
            print(json.dumps({"status": "error", "message": "step_state.json not found"}))
            _sys.exit(1)
        from map_orchestrator import StepState  # type: ignore[import-not-found]
        st = StepState.load(state_path)
        subtask_id = data.get("subtask_id") or st.current_subtask_id or ""
        if not subtask_id:
            print(json.dumps({"status": "skipped", "message": "No subtask_id"}))
            _sys.exit(0)
        st.record_subtask_result(
            subtask_id=subtask_id,
            files_changed=data.get("files", []),
            status=data.get("status", "valid"),
            summary=data.get("summary", ""),
            commit_sha=data.get("commit_sha"),
        )
        st.save(state_path)
        print(json.dumps({"status": "success", "subtask_id": subtask_id}))

    elif func_name == "build_context_block" and len(sys.argv) >= 4:
        result = build_context_block(sys.argv[2], sys.argv[3])
        print(result)

    elif func_name == "get_subtask" and len(sys.argv) >= 3:
        # CLI: get_subtask <subtask_id> [--branch <branch>]
        # Hides the {flat shape, blueprint-wrapped shape} dichotomy that
        # forces every caller into ad-hoc jq with two fallbacks. load_blueprint
        # already normalizes both forms.
        sid = sys.argv[2]
        branch_arg: Optional[str] = None
        if "--branch" in sys.argv:
            idx = sys.argv.index("--branch")
            if idx + 1 < len(sys.argv):
                branch_arg = sys.argv[idx + 1]
        bp = load_blueprint(branch_arg)
        if bp is None:
            print(
                json.dumps({"status": "error", "message": "blueprint.json not found"}),
                file=sys.stderr,
            )
            sys.exit(1)
        sub = get_subtask_from_blueprint(bp, sid)
        if sub is None:
            print(
                json.dumps({"status": "error", "message": f"subtask {sid!r} not in blueprint"}),
                file=sys.stderr,
            )
            sys.exit(1)
        print(json.dumps(sub, indent=2))

    elif func_name == "subtask_token_usage" and len(sys.argv) >= 3:
        # CLI: subtask_token_usage <branch> [subtask_id] [--since-ts ISO]
        #      [--all]
        # --all reports the whole-session total (anchors window at epoch);
        # useful when the operator wants "tokens since session start" rather
        # than "tokens since current subtask boundary".
        branch_arg = sys.argv[2]
        sid_arg: Optional[str] = None
        since_arg: Optional[str] = None
        rest = list(sys.argv[3:])
        if rest and not rest[0].startswith("--"):
            sid_arg = rest.pop(0)
        if "--since-ts" in rest:
            idx = rest.index("--since-ts")
            if idx + 1 < len(rest):
                since_arg = rest[idx + 1]
        if "--all" in rest and not since_arg:
            since_arg = "1970-01-01T00:00:00Z"
        report = subtask_token_usage(branch_arg, sid_arg, since_ts=since_arg)
        print(json.dumps(report, indent=2))
        if report.get("status") in {"no_state", "error"}:
            sys.exit(1)

    elif func_name == "list_plans":
        report = list_plans()
        print(json.dumps(report, indent=2))

    elif func_name == "check_plan_resume":
        # CLI: check_plan_resume "<incoming request>" [--branch <branch>]
        # Advisory preflight (always exits 0) — the skill branches on `verdict`.
        rest = list(sys.argv[2:])
        cpr_branch: Optional[str] = None
        if "--branch" in rest:
            bidx = rest.index("--branch")
            if bidx + 1 < len(rest):
                cpr_branch = rest[bidx + 1]
                del rest[bidx:bidx + 2]
        cpr_request = rest[0] if rest else ""
        report = check_plan_resume(cpr_request, branch=cpr_branch)
        print(json.dumps(report, indent=2))

    elif func_name == "subtask_boundary_compact_check" and len(sys.argv) >= 3:
        # CLI: subtask_boundary_compact_check <branch>
        # Exit codes: 0 = below threshold or cooldown; 1 = recommend
        # compact; 2 = force_compact (above 2x threshold). Lets skill
        # bash drive `if (( $? >= 2 )); then ... fi`.
        report = subtask_boundary_compact_check(sys.argv[2])
        print(json.dumps(report, indent=2))
        if report.get("status") == "success":
            if report.get("force_compact"):
                sys.exit(2)
            if report.get("used", 0) >= report.get("threshold", 1):
                sys.exit(1)

    elif func_name == "record_subtask_baseline" and len(sys.argv) >= 4:
        # CLI: record_subtask_baseline <branch> <subtask_id>
        report = record_subtask_baseline(sys.argv[2], sys.argv[3])
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "record_scope_baseline" and len(sys.argv) >= 3:
        # CLI: record_scope_baseline <branch>
        report = record_scope_baseline(sys.argv[2])
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "refresh_blueprint_affected_files" and len(sys.argv) >= 4:
        # CLI: refresh_blueprint_affected_files <branch> <subtask_id> [--dry-run]
        branch_arg = sys.argv[2]
        sid_arg = sys.argv[3]
        dry_run_arg = "--dry-run" in sys.argv
        report = refresh_blueprint_affected_files(
            branch_arg, sid_arg, dry_run=dry_run_arg
        )
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "record_token_event":
        # CLI: record_token_event <branch> --transcript <path>
        #        [--agent A] [--phase P] [--subtask ST-NNN]
        # Advisory token meter: exit 0 always so the SubagentStop/Stop hooks
        # never block the turn. Dedups by msg_id via the per-branch cache.
        def _opt_value(flag: str) -> str:
            if flag in sys.argv:
                pos = sys.argv.index(flag)
                if pos + 1 < len(sys.argv):
                    return sys.argv[pos + 1]
            return ""

        tok_branch = (
            sys.argv[2] if len(sys.argv) >= 3 and not sys.argv[2].startswith("--") else ""
        )
        report = record_token_event(
            tok_branch or None,
            transcript_path=_opt_value("--transcript"),
            agent=_opt_value("--agent"),
            phase=_opt_value("--phase"),
            subtask_id=_opt_value("--subtask"),
        )
        print(json.dumps(report, indent=2))

    elif func_name == "token_report":
        # CLI: token_report [branch]
        tok_branch = sys.argv[2] if len(sys.argv) >= 3 else None
        print(token_report(tok_branch))

    elif func_name == "detect_cross_subtask_regression_risk" and len(sys.argv) >= 4:
        # CLI: detect_cross_subtask_regression_risk <branch> <subtask_id>
        # Read-only. Exit 0 always (callers branch on the `at_risk` /
        # `recommended_gate` fields, like detect_truncated_agent_output) so a
        # shell pipeline can decide full-suite vs scoped without `set -e`
        # tripping on an advisory signal.
        report = detect_cross_subtask_regression_risk(sys.argv[2], sys.argv[3])
        print(json.dumps(report, indent=2))

    elif func_name == "detect_symbol_blast_radius" and len(sys.argv) >= 4:
        # CLI: detect_symbol_blast_radius <branch> <subtask_id>
        # Read-only. Exit 0 always (callers branch on the `recommended_gate`
        # field, like detect_cross_subtask_regression_risk) so a shell pipeline
        # can decide full-suite vs scoped without `set -e` tripping on an
        # advisory signal.
        report = detect_symbol_blast_radius(sys.argv[2], sys.argv[3])
        print(json.dumps(report, indent=2))

    elif func_name == "detect_actor_files_changed_mismatch" and len(sys.argv) >= 4:
        # CLI: detect_actor_files_changed_mismatch <branch> <subtask_id> [--declared f1,f2,...]
        # Read-only. Exit 0 always (callers branch on `status_mismatch` field)
        # so a shell pipeline can decide whether to block recording without
        # `set -e` tripping on an advisory signal.
        declared_arg: list[str] = []
        if "--declared" in sys.argv:
            declared_idx = sys.argv.index("--declared")
            if declared_idx + 1 < len(sys.argv):
                raw_declared = sys.argv[declared_idx + 1]
                declared_arg = [f for f in raw_declared.split(",") if f.strip()]
        report = detect_actor_files_changed_mismatch(sys.argv[2], sys.argv[3], declared_arg)
        print(json.dumps(report, indent=2))

    elif func_name == "detect_already_done" and len(sys.argv) >= 4:
        # CLI: detect_already_done <branch> <subtask_id> [--since-ref REF]
        branch_arg = sys.argv[2]
        sid_arg = sys.argv[3]
        since_arg: Optional[str] = None
        if "--since-ref" in sys.argv:
            idx = sys.argv.index("--since-ref")
            if idx + 1 < len(sys.argv):
                since_arg = sys.argv[idx + 1]
        report = detect_already_done(branch_arg, sid_arg, since_ref=since_arg)
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "validate_mutation_boundary" and len(sys.argv) >= 4:
        # CLI: validate_mutation_boundary <branch> <subtask_id> [base_ref]
        # Exit codes:
        #   0: status in {"clean", "warning"}
        #   1: status == "error" (missing blueprint, unknown subtask, git
        #      failure) — always non-zero so Monitor's mandatory gate cannot
        #      silently pass; OR status == "violation" with MAP_STRICT_SCOPE=1.
        base_ref_arg = sys.argv[4] if len(sys.argv) >= 5 else None
        report = validate_mutation_boundary(sys.argv[2], sys.argv[3], base_ref_arg)
        print(json.dumps(report, indent=2))
        report_status = report.get("status")
        if report_status == "error":
            sys.exit(1)
        if report_status == "violation" and report.get("strict"):
            sys.exit(1)

    elif func_name == "save_research" and len(sys.argv) >= 4:
        # CLI: save_research <branch> <subtask_id> [kind] [--attempt N] [--file PATH]
        # Content source priority: --file PATH > stdin. The --file
        # alternative was added because the stdin-only contract was
        # brittle — a single shell-quoting accident bricked the input
        # with "Invalid JSON on stdin"-class errors and there was no way
        # to pass an already-written research file straight through.
        branch_arg = sys.argv[2]
        subtask_arg = sys.argv[3]
        kind_arg = "actor"
        attempt_arg: Optional[int] = None
        file_arg: Optional[str] = None
        rest = list(sys.argv[4:])
        if rest and not rest[0].startswith("--"):
            kind_arg = rest.pop(0)
        if "--attempt" in rest:
            idx = rest.index("--attempt")
            if idx + 1 < len(rest):
                try:
                    attempt_arg = int(rest[idx + 1])
                except ValueError:
                    print(
                        json.dumps({"status": "error", "message": "--attempt must be int"}),
                        file=sys.stderr,
                    )
                    sys.exit(1)
        if "--file" in rest:
            file_idx = rest.index("--file")
            if file_idx + 1 < len(rest):
                file_arg = rest[file_idx + 1]
        try:
            if file_arg:
                file_path = Path(file_arg)
                if not file_path.is_file():
                    print(
                        json.dumps({
                            "status": "error",
                            "message": f"--file {file_arg!r} not found or not a file",
                        }),
                        file=sys.stderr,
                    )
                    sys.exit(1)
                content_in = file_path.read_text(encoding="utf-8")
            else:
                content_in = sys.stdin.read()
            written = save_research(
                branch_arg, subtask_arg, content_in, kind=kind_arg, attempt=attempt_arg
            )
            print(json.dumps({"status": "success", "path": written}))
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            sys.exit(1)

    elif func_name == "load_research" and len(sys.argv) >= 4:
        # CLI: load_research <branch> <subtask_id> [kind] [--all]
        # Content to stdout. On error: write the diagnostic to STDERR
        # (keeping stdout empty) so callers using command substitution
        # (FOO=$(... load_research ...)) don't get JSON in place of
        # research text. --all merges every kind on disk under section
        # headers — useful when Monitor wants both Actor's research and
        # its own previous notes without two ping-pongs.
        branch_arg = sys.argv[2]
        subtask_arg = sys.argv[3]
        merge_all = "--all" in sys.argv[4:]
        rest_tokens = [t for t in sys.argv[4:] if t != "--all"]
        kind_arg = rest_tokens[0] if rest_tokens else "actor"
        try:
            sys.stdout.write(
                load_research(
                    branch_arg,
                    subtask_arg,
                    kind=kind_arg,
                    merge_all_kinds=merge_all,
                )
            )
        except ValueError as exc:
            print(
                json.dumps({"status": "error", "message": str(exc)}),
                file=sys.stderr,
            )
            sys.exit(1)

    elif func_name == "record_diagnostics_baseline":
        # CLI: record_diagnostics_baseline <branch> [--tools pyright,ruff]
        # Snapshot pyright/ruff/mypy/golangci-lint state pre-execution.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: record_diagnostics_baseline <branch> [--tools ...]"}), file=sys.stderr)
            sys.exit(1)
        diag_branch = sys.argv[2]
        diag_tools: Optional[list[str]] = None
        diag_timeout = 180
        if "--tools" in sys.argv:
            t_idx = sys.argv.index("--tools")
            if t_idx + 1 < len(sys.argv):
                diag_tools = [
                    t.strip() for t in re.split(r"[,\s]+", sys.argv[t_idx + 1])
                    if t.strip()
                ]
        if "--timeout" in sys.argv:
            t_idx = sys.argv.index("--timeout")
            if t_idx + 1 < len(sys.argv):
                try:
                    diag_timeout = int(sys.argv[t_idx + 1])
                except ValueError:
                    print(json.dumps({"status": "error", "message": "--timeout must be int"}), file=sys.stderr)
                    sys.exit(1)
        report = record_diagnostics_baseline(
            diag_branch, tools=diag_tools, timeout_seconds=diag_timeout
        )
        print(json.dumps(report, indent=2))

    elif func_name == "list_diagnostics_baseline":
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: list_diagnostics_baseline <branch>"}), file=sys.stderr)
            sys.exit(1)
        report = list_diagnostics_baseline(sys.argv[2])
        print(json.dumps(report, indent=2))

    elif func_name == "record_test_baseline":
        # CLI: record_test_baseline <branch> [--command "..."] [--timeout N]
        # Snapshot pre-existing test failures so later subtasks can
        # distinguish "I broke this" from "this was broken before plan
        # started". Auto-detects test command when omitted.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: record_test_baseline <branch> [--command ...]"}), file=sys.stderr)
            sys.exit(1)
        baseline_branch = sys.argv[2]
        baseline_cmd = ""
        baseline_timeout = 120
        if "--command" in sys.argv:
            c_idx = sys.argv.index("--command")
            if c_idx + 1 < len(sys.argv):
                baseline_cmd = sys.argv[c_idx + 1]
        if "--timeout" in sys.argv:
            t_idx = sys.argv.index("--timeout")
            if t_idx + 1 < len(sys.argv):
                try:
                    baseline_timeout = int(sys.argv[t_idx + 1])
                except ValueError:
                    print(json.dumps({"status": "error", "message": "--timeout must be int"}), file=sys.stderr)
                    sys.exit(1)
        report = record_test_baseline(
            baseline_branch, baseline_cmd, timeout_seconds=baseline_timeout
        )
        print(json.dumps(report, indent=2))
        # Exit 0 even on baseline_failures — the WHOLE point is to
        # record them, not gate on them. Only exit non-zero on hard
        # error (invocation failed).
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "list_baseline_failures":
        # CLI: list_baseline_failures <branch>
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: list_baseline_failures <branch>"}), file=sys.stderr)
            sys.exit(1)
        report = list_baseline_failures(sys.argv[2])
        print(json.dumps(report, indent=2))

    elif func_name == "acknowledge_diagnostic":
        # CLI: acknowledge_diagnostic <branch> <signature> [--reason "..."]
        # The signature can be any whole-line diagnostic text — we
        # canonicalize internally (collapse whitespace, strip).
        if len(sys.argv) < 4:
            print(json.dumps({"status": "error", "message": "usage: acknowledge_diagnostic <branch> <signature> [--reason ...]"}), file=sys.stderr)
            sys.exit(1)
        ack_branch = sys.argv[2]
        ack_signature = sys.argv[3]
        ack_reason = ""
        if "--reason" in sys.argv:
            r_idx = sys.argv.index("--reason")
            if r_idx + 1 < len(sys.argv):
                ack_reason = sys.argv[r_idx + 1]
        report = acknowledge_diagnostic(ack_branch, ack_signature, ack_reason)
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "list_acknowledged_diagnostics":
        # CLI: list_acknowledged_diagnostics <branch>
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: list_acknowledged_diagnostics <branch>"}), file=sys.stderr)
            sys.exit(1)
        report = list_acknowledged_diagnostics(sys.argv[2])
        print(json.dumps(report, indent=2))
        if report.get("status") == "error":
            sys.exit(1)

    elif func_name == "is_diagnostic_acknowledged":
        # CLI: is_diagnostic_acknowledged <branch> <signature>
        # Exit code 0 if acknowledged, 1 otherwise (lets shell branch:
        # `if python3 ... is_diagnostic_acknowledged $B "$LINE"; then continue; fi`).
        if len(sys.argv) < 4:
            print(json.dumps({"status": "error", "message": "usage: is_diagnostic_acknowledged <branch> <signature>"}), file=sys.stderr)
            sys.exit(1)
        is_ack = is_diagnostic_acknowledged(sys.argv[2], sys.argv[3])
        print(json.dumps({"acknowledged": is_ack, "signature": sys.argv[3]}))
        sys.exit(0 if is_ack else 1)

    elif func_name == "detect_truncated_agent_output":
        # CLI: <pipe agent response> | detect_truncated_agent_output [--agent monitor|actor|...]
        # Reads the candidate agent response from stdin, prints JSON report.
        # Exit code 0 always (callers parse `truncated` field) — no stderr
        # for a clean response, so shell pipelines can branch on it.
        #
        # IMPORTANT: the captured agent response MUST be piped in. A bare call
        # with nothing on stdin is NOT a truncated response — it means the
        # caller forgot to pipe. We surface that as a distinct, non-blocking
        # `status: "no_input"` so it can't masquerade as a hard-stop
        # truncation on every subtask (an empty stdin would otherwise read as
        # `truncated: true / "empty response"`).
        agent_kind_arg = "monitor"
        if "--agent" in sys.argv:
            agent_idx = sys.argv.index("--agent")
            if agent_idx + 1 < len(sys.argv):
                agent_kind_arg = sys.argv[agent_idx + 1]
        text_in = sys.stdin.read()
        if not text_in.strip():
            print(json.dumps({
                "truncated": False,
                "status": "no_input",
                "reasons": [
                    "no agent response on stdin — pipe the captured response, "
                    "e.g. printf '%s' \"$RESPONSE\" | python3 "
                    ".map/scripts/map_step_runner.py "
                    "detect_truncated_agent_output --agent " + agent_kind_arg
                ],
                "agent_kind": agent_kind_arg,
            }, indent=2))
            sys.exit(0)
        report = detect_truncated_agent_output(
            text_in, agent_kind=agent_kind_arg
        )
        # Don't serialize the parsed dict back (callers can re-parse the
        # original text if they want it); keep the report shape small.
        report_summary = {
            "truncated": report["truncated"],
            "status": "ok",
            "reasons": report["reasons"],
            "agent_kind": report["agent_kind"],
        }
        print(json.dumps(report_summary, indent=2))

    elif func_name == "build_json_retry_prompt":
        # CLI: build_json_retry_prompt --agent <role> [--errors '<json array>']
        # Builds a retry prompt for a review agent that returned malformed output.
        # Prints JSON result; exit 0 on success (even for unknown agent — callers
        # check result["status"]).  Exit 1 only when --errors is not a JSON list.
        retry_agent = "monitor"
        if "--agent" in sys.argv:
            agent_idx = sys.argv.index("--agent")
            if agent_idx + 1 < len(sys.argv):
                retry_agent = sys.argv[agent_idx + 1]
        retry_errors: Optional[list[str]] = None
        if "--errors" in sys.argv:
            err_idx = sys.argv.index("--errors")
            if err_idx + 1 < len(sys.argv):
                raw_errors = sys.argv[err_idx + 1]
                try:
                    parsed_errors = json.loads(raw_errors)
                    if not isinstance(parsed_errors, list):
                        # JSON parsed to a scalar (e.g. a JSON string) — coerce to list
                        parsed_errors = [raw_errors]
                except json.JSONDecodeError:
                    # Plain (non-JSON) string — coerce to single-element list
                    parsed_errors = [raw_errors]
                retry_errors = [str(e) for e in parsed_errors]
        retry_result = build_json_retry_prompt(retry_agent, retry_errors)
        print(json.dumps(retry_result, indent=2))

    elif func_name == "shuffle-sections":
        # CLI: shuffle-sections <mode> [seed]
        # Empty string seed is treated as "unset" (None) so SKILL.md can pass "" unconditionally.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: shuffle-sections <mode> [seed]"}))
            sys.exit(1)
        mode_arg = sys.argv[2]
        seed_arg: int | None = None
        if len(sys.argv) >= 4 and sys.argv[3] != "":
            try:
                seed_arg = int(sys.argv[3])  # EC-16: int() rejects non-int via ValueError
            except ValueError as exc:
                print(json.dumps({"status": "error", "message": f"invalid seed: {exc}"}))
                sys.exit(1)
        try:
            order = get_review_section_order(mode_arg, seed_arg)
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            sys.exit(1)
        print(json.dumps({"status": "ok", "mode": mode_arg, "seed": seed_arg, "order": order}))

    elif func_name == "default-shuffle-seed":
        # CLI: default-shuffle-seed <branch> [commit_sha]
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: default-shuffle-seed <branch> [commit_sha]"}))
            sys.exit(1)
        branch_arg = sys.argv[2]
        commit_sha_arg = sys.argv[3] if len(sys.argv) >= 4 and sys.argv[3] else None
        seed_val = default_shuffle_seed(branch_arg, commit_sha_arg)
        print(json.dumps({"status": "ok", "branch": branch_arg, "commit_sha": commit_sha_arg, "seed": seed_val}))

    elif func_name == "prepare_detached_review":
        import argparse as _ap

        _p = _ap.ArgumentParser(prog="map_step_runner.py prepare_detached_review")
        _p.add_argument("bundle_path", nargs="?", default=None)
        _p.add_argument("--commit", default=None)
        _p.add_argument("--target-dir", default=None)
        _p.add_argument("--branch", default=None)
        _args = _p.parse_args(sys.argv[2:])
        result = prepare_detached_review(
            _args.bundle_path,
            branch=_args.branch,
            commit=_args.commit,
            target_dir=_args.target_dir,
        )
        print(json.dumps(result, indent=2))

    elif func_name == "compare-review-runs":
        # CLI: compare-review-runs <runs_json|->
        # runs_json: JSON-encoded list of run dicts. Pass "-" to read from stdin.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: compare-review-runs <runs_json|->"}))
            sys.exit(1)
        raw = sys.stdin.read() if sys.argv[2] == "-" else sys.argv[2]
        try:
            runs_payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            print(json.dumps({"status": "error", "message": f"invalid JSON: {exc}"}))
            sys.exit(1)
        try:
            cmp_result = compare_review_runs(runs_payload)
        except (ValueError, AttributeError, TypeError) as exc:
            print(json.dumps({"status": "error", "message": f"compare-review-runs: {exc}"}))
            sys.exit(1)
        print(json.dumps({"status": "ok", **cmp_result}))

    elif func_name == "record-review-ordering":
        # CLI: record-review-ordering <mode> [seed] [<json: {runs, drift}>|"-" for stdin]
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: record-review-ordering <mode> [seed] [runs_drift_json|-]"}))
            sys.exit(1)
        mode_arg = sys.argv[2]
        seed_arg: int | None = None
        if len(sys.argv) >= 4 and sys.argv[3] != "":
            try:
                seed_arg = int(sys.argv[3])
            except ValueError as exc:
                print(json.dumps({"status": "error", "message": f"invalid seed: {exc}"}))
                sys.exit(1)
        runs_arg: list[dict[str, object]] | None = None
        drift_arg: dict[str, object] | None = None
        if len(sys.argv) >= 5:
            raw_ord = sys.stdin.read() if sys.argv[4] == "-" else sys.argv[4]
            try:
                ord_payload = json.loads(raw_ord)
            except (ValueError, TypeError) as exc:
                print(json.dumps({"status": "error", "message": f"invalid JSON: {exc}"}))
                sys.exit(1)
            if not isinstance(ord_payload, dict):
                print(json.dumps({"status": "error", "message": "JSON payload must be an object"}))
                sys.exit(1)
            runs_field = ord_payload.get("runs")
            if runs_field is not None and not isinstance(runs_field, list):
                print(json.dumps({"status": "error", "message": "payload.runs must be a list"}))
                sys.exit(1)
            runs_arg = cast(list[dict[str, object]], runs_field) if runs_field is not None else None
            drift_field = ord_payload.get("drift")
            if drift_field is not None and not isinstance(drift_field, dict):
                print(json.dumps({"status": "error", "message": "payload.drift must be a dict"}))
                sys.exit(1)
            drift_arg = cast(dict[str, object], drift_field) if drift_field is not None else None
        try:
            ord_result = record_review_ordering(mode_arg, seed_arg, runs_arg, drift_arg, branch=None)
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            sys.exit(1)
        print(json.dumps(ord_result))

    elif func_name == "log_agent_failure":
        # CLI: log_agent_failure --agent <name> --phase <name> --failure-label <label>
        #                        [--reasons '<json array>'] [--retry] [--schema <text>]
        # Appends one JSONL event to the branch-scoped agent_failure_events.jsonl.
        # Prints JSON result; exit 0 on success, exit 1 on validation failure.
        def _flag_val(name: str) -> Optional[str]:
            flag = f"--{name}"
            if flag in sys.argv:
                idx = sys.argv.index(flag)
                if idx + 1 < len(sys.argv):
                    return sys.argv[idx + 1]
            return None

        laf_agent = _flag_val("agent") or ""
        laf_phase = _flag_val("phase") or ""
        laf_label = _flag_val("failure-label") or ""
        laf_schema = _flag_val("schema")
        laf_retry = "--retry" in sys.argv
        laf_reasons: list[str] = []
        raw_reasons = _flag_val("reasons")
        if raw_reasons is not None:
            try:
                parsed_reasons = json.loads(raw_reasons)
                if not isinstance(parsed_reasons, list):
                    # JSON parsed to a scalar (e.g. a JSON string) — coerce to list
                    parsed_reasons = [raw_reasons]
            except json.JSONDecodeError:
                # Plain (non-JSON) string — coerce to single-element list
                parsed_reasons = [raw_reasons]
            laf_reasons = [str(r) for r in parsed_reasons]
        laf_result = log_agent_failure(
            laf_agent,
            laf_phase,
            laf_label,
            reasons=laf_reasons or None,
            retry=laf_retry,
            schema=laf_schema,
        )
        print(json.dumps(laf_result, indent=2))
        if laf_result.get("status") == "error":
            sys.exit(1)

    else:
        # Helpful redirect: when the user passes a command that belongs to
        # the orchestrator (record_subtask_result, mark_subtask_complete,
        # validate_step, ...) the previous "Invalid JSON on stdin" /
        # "Unknown function" error gave no hint about WHICH script to use.
        # Cross-reference the orchestrator's command list so misroutes
        # surface as actionable text instead of cryptic JSON parse errors.
        ORCHESTRATOR_ONLY_COMMANDS = {
            "get_next_step", "peek_current_step", "validate_step",
            "initialize", "set_plan_approved", "set_execution_mode",
            "set_tdd_mode", "skip_step", "set_subtasks",
            "mark_contract_ready", "resume_from_plan",
            "resume_from_test_contract", "check_circuit_breaker",
            "set_waves", "get_wave_step", "validate_wave_step",
            "advance_wave", "resume_single_subtask", "get_plan_progress",
            "monitor_failed", "wave_monitor_failed", "reopen_for_fixes",
            "mark_workflow_complete", "mark_subtask_complete",
            "record_subtask_result", "backfill_subtask_ids",
            "finalize_plan",
        }
        if func_name in ORCHESTRATOR_ONLY_COMMANDS:
            print(
                f"Wrong runner: {func_name!r} lives in map_orchestrator.py, "
                f"not map_step_runner.py.\n"
                f"Try: python3 .map/scripts/map_orchestrator.py {func_name} "
                f"{' '.join(sys.argv[2:])}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Unknown function: {func_name}", file=sys.stderr)
        sys.exit(1)
