"""Drift-aware file copier for MAP Framework delivery.

Provides copy_managed_file() which replaces raw shutil.copy2() with:
  1. Metadata injection (generated_by, mapify_version, template_hash)
  2. Drift detection on upgrade (user modifications vs template)
  3. Automatic .bak backup before overwriting drifted files
  4. Fence-aware merge (C2): managed region inside fence, user tail preserved byte-for-byte

Metadata formats by file type:
  .md   → <!-- MAP-MANAGED: {...} -->
  .py   → # MAP-MANAGED: {...}
  .json → "_map_managed": {...} key in root object
  other → no metadata (plain copy)

Fence formats by file type (C2, ST-010):
  .md              → <!-- map:start --> ... <!-- map:end -->
  .py / .sh / .toml / .yaml / .yml → # map:start ... # map:end
  .json            → NO fence (fully managed via _map_managed root key)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CopyResult:
    """Result of a single managed file copy."""

    src: Path
    dest: Path
    success: bool = True
    drifted: bool = False
    backed_up: bool = False
    backup_path: Path | None = None
    reason: str = ""
    first_install: bool = False
    migrated: bool = False


@dataclass
class DriftReport:
    """Aggregated drift info from an upgrade run."""

    results: list[CopyResult] = field(default_factory=list)

    @property
    def drifted_files(self) -> list[CopyResult]:
        return [r for r in self.results if r.drifted]

    @property
    def backed_up_files(self) -> list[CopyResult]:
        return [r for r in self.results if r.backed_up]

    @property
    def has_drift(self) -> bool:
        return len(self.drifted_files) > 0


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def compute_hash(content: str | bytes) -> str:
    """SHA-256 hex digest of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Metadata injection / extraction
# ---------------------------------------------------------------------------

_MANAGED_TAG = "MAP-MANAGED"
_MD_PATTERN = re.compile(r"^<!--\s*MAP-MANAGED:\s*(\{.*?\})\s*-->\n?", re.DOTALL)
_PY_PATTERN = re.compile(r"^#\s*MAP-MANAGED:\s*(\{.*?\})\n?")
# For .json files we handle it structurally, not via regex.


def _build_metadata(version: str, template_hash: str) -> dict[str, Any]:
    return {
        "generated_by": "mapify-cli",
        "mapify_version": version,
        "template_hash": template_hash,
        "installed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def inject_metadata(content: str, ext: str, version: str, template_hash: str) -> str:
    """Prepend/inject metadata into file content based on extension.

    Returns modified content. For unsupported extensions, returns content unchanged.
    """
    meta = _build_metadata(version, template_hash)
    meta_json = json.dumps(meta, separators=(",", ":"))

    if ext == ".md":
        header = f"<!-- {_MANAGED_TAG}: {meta_json} -->\n"
        # If content has YAML frontmatter (starts with ---), insert after
        # closing --- to preserve frontmatter parsing by tools like Claude Code.
        if content.startswith("---\n"):
            end_idx = content.find("\n---\n", 3)
            if end_idx != -1:
                insert_pos = end_idx + 5  # after \n---\n
                return content[:insert_pos] + header + content[insert_pos:]
            # Edge case: closing --- at very end (no trailing newline)
            end_idx = content.find("\n---", 3)
            if end_idx != -1 and end_idx + 4 == len(content):
                return content + "\n" + header
        return header + content

    if ext == ".py":
        # Preserve shebang if present
        if content.startswith("#!"):
            first_newline = content.index("\n") + 1
            shebang = content[:first_newline]
            rest = content[first_newline:]
            return shebang + f"# {_MANAGED_TAG}: {meta_json}\n" + rest
        return f"# {_MANAGED_TAG}: {meta_json}\n" + content

    if ext == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                data["_map_managed"] = meta
                return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        except (json.JSONDecodeError, TypeError):
            pass
        # Can't inject into non-dict JSON; return as-is
        return content

    if ext in (".sh", ".bash", ".toml", ".yaml", ".yml"):
        # Hash-comment metadata, no shebang handling needed for toml/yaml.
        # .sh/.bash: preserve shebang if present (same as .py logic).
        if ext in (".sh", ".bash") and content.startswith("#!"):
            first_newline = content.index("\n") + 1
            shebang = content[:first_newline]
            rest = content[first_newline:]
            return shebang + f"# {_MANAGED_TAG}: {meta_json}\n" + rest
        return f"# {_MANAGED_TAG}: {meta_json}\n" + content

    # Unknown extension — no metadata
    return content


def extract_metadata(content: str, ext: str) -> tuple[dict[str, Any] | None, str]:
    """Extract metadata from file content and return (metadata, clean_content).

    Returns (None, original_content) if no metadata found.
    """
    if ext == ".md":
        # Try at start of file (non-frontmatter .md files)
        m = _MD_PATTERN.match(content)
        if m:
            try:
                meta = json.loads(m.group(1))
                return meta, content[m.end() :]
            except json.JSONDecodeError:
                pass
        # Try after YAML frontmatter (agent .md files with ---)
        if content.startswith("---\n"):
            end_idx = content.find("\n---\n", 3)
            if end_idx != -1:
                after_fm = end_idx + 5
                rest = content[after_fm:]
                m = _MD_PATTERN.match(rest)
                if m:
                    try:
                        meta = json.loads(m.group(1))
                        clean = content[:after_fm] + rest[m.end() :]
                        # If nothing followed the MAP-MANAGED comment (it was
                        # at EOF) and clean ends with "\n---\n", the trailing
                        # newline was injected by inject_metadata for the
                        # frontmatter-at-EOF edge case.  Strip it to restore
                        # the original content that had no trailing newline.
                        if not rest[m.end() :] and clean.endswith("\n---\n"):
                            clean = clean[:-1]
                        return meta, clean
                    except json.JSONDecodeError:
                        pass
        return None, content

    if ext == ".py":
        lines = content.split("\n", 3)
        # Check first non-shebang line
        check_idx = 0
        if lines and lines[0].startswith("#!"):
            check_idx = 1
        if check_idx < len(lines):
            m = _PY_PATTERN.match(lines[check_idx])
            if m:
                try:
                    meta = json.loads(m.group(1))
                    # Reconstruct without the metadata line (positional, not search)
                    before_parts = lines[:check_idx]
                    after_parts = lines[check_idx + 1 :]
                    if before_parts:
                        clean = "\n".join(before_parts) + "\n" + "\n".join(after_parts)
                    else:
                        clean = "\n".join(after_parts)
                    return meta, clean
                except json.JSONDecodeError:
                    pass
        return None, content

    if ext == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "_map_managed" in data:
                meta = data.pop("_map_managed")
                clean = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
                return meta, clean
        except (json.JSONDecodeError, TypeError):
            pass
        return None, content

    if ext in (".sh", ".bash", ".toml", ".yaml", ".yml"):
        # Same hash-comment style as .py.  .sh/.bash may have a shebang on line 0.
        lines = content.split("\n", 3)
        check_idx = 0
        if ext in (".sh", ".bash") and lines and lines[0].startswith("#!"):
            check_idx = 1
        if check_idx < len(lines):
            m = _PY_PATTERN.match(lines[check_idx])
            if m:
                try:
                    meta = json.loads(m.group(1))
                    before_parts = lines[:check_idx]
                    after_parts = lines[check_idx + 1 :]
                    if before_parts:
                        clean = "\n".join(before_parts) + "\n" + "\n".join(after_parts)
                    else:
                        clean = "\n".join(after_parts)
                    return meta, clean
                except json.JSONDecodeError:
                    pass
        return None, content

    return None, content


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def detect_drift(src_path: Path, dest_path: Path) -> CopyResult:
    """Check if dest_path has been modified by the user since last install.

    Returns a CopyResult with drifted=True if user has modified the file.
    """
    result = CopyResult(src=src_path, dest=dest_path)

    if not dest_path.exists():
        result.first_install = True
        return result

    ext = dest_path.suffix.lower()
    try:
        dest_content = dest_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Binary or unreadable — can't detect drift
        result.reason = "binary or unreadable"
        return result

    meta, clean_dest = extract_metadata(dest_content, ext)

    if meta is None:
        # No metadata → pre-upgrade file, can't detect drift precisely
        result.reason = "no metadata (pre-upgrade file)"
        return result

    stored_hash = meta.get("template_hash", "")
    if not stored_hash:
        result.reason = "metadata missing template_hash"
        return result

    # Compare hash of clean dest content against stored template hash
    current_hash = compute_hash(clean_dest)
    if current_hash != stored_hash:
        result.drifted = True
        result.reason = (
            f"content modified (hash {current_hash[:8]}… ≠ {stored_hash[:8]}…)"
        )

    return result


# ---------------------------------------------------------------------------
# Security guards (INV-5, SECURITY)
# ---------------------------------------------------------------------------


def _assert_safe_dest(dest: Path) -> None:
    """Refuse to write to a symlink destination.

    Uses os.lstat so the check is against the link itself, not the target.
    Raises OSError if dest is a symlink (O_NOFOLLOW guard pre-check).
    """
    # Intent: prevent symlink-following attacks; check before any write
    if dest.is_symlink():
        raise OSError(
            f"Refusing to write to symlink destination: {dest} "
            "(O_NOFOLLOW guard; ST-010 security invariant)"
        )


def _atomic_write(dest: Path, content: str) -> None:
    """Write content to dest atomically, refusing to follow symlinks.

    Strategy:
      1. _assert_safe_dest(dest) — refuse symlinks upfront.
      2. Write to a sibling temp file using os.open with O_NOFOLLOW to prevent
         TOCTOU races on the temp path.
      3. os.replace(tmp, dest) — atomic rename; replaces dest if it exists.

    This ensures:
      - No partial writes visible to readers (atomic replace).
      - No symlink following on the temp path (O_NOFOLLOW).
      - The upfront symlink check on dest protects against a race where dest
        is replaced by a symlink between _assert_safe_dest and os.replace.
    """
    _assert_safe_dest(dest)

    dest_bytes = content.encode("utf-8")
    tmp_path = dest.parent / f".{dest.name}.tmp"

    # O_NOFOLLOW: refuse to follow symlinks on the temp file itself
    # O_CREAT | O_WRONLY | O_TRUNC: create or truncate
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # O_NOFOLLOW is POSIX; guard for platforms that don't define it (rare)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(str(tmp_path), flags, 0o644)
    try:
        os.write(fd, dest_bytes)
    finally:
        os.close(fd)

    os.replace(str(tmp_path), str(dest))


# ---------------------------------------------------------------------------
# Fence tokens and split helpers (C2, ST-010)
# ---------------------------------------------------------------------------

# Per-format fence token pairs.  None means "no fence" (JSON: fully managed).
_FENCE_TOKENS: dict[str, tuple[str, str] | None] = {
    ".md": ("<!-- map:start -->", "<!-- map:end -->"),
    ".py": ("# map:start", "# map:end"),
    ".sh": ("# map:start", "# map:end"),
    ".bash": ("# map:start", "# map:end"),
    ".toml": ("# map:start", "# map:end"),
    ".yaml": ("# map:start", "# map:end"),
    ".yml": ("# map:start", "# map:end"),
    ".json": None,  # fully managed via _map_managed root key
}


class FenceSplitResult:
    """Outcome of _split_fence."""

    __slots__ = ("after", "before", "managed", "state", "warning")

    def __init__(
        self,
        state: str,
        before: str = "",
        managed: str = "",
        after: str = "",
        warning: str = "",
    ) -> None:
        # state: 'found' | 'no_fence' | 'malformed'
        self.state = state
        self.before = before    # text up to and including fence-start line
        self.managed = managed  # text between fence markers (excl. the marker lines)
        self.after = after      # text after fence-end line (user tail, byte-for-byte)
        self.warning = warning  # human-readable warning for malformed / missing fence


def _split_fence(text: str, start_token: str, end_token: str) -> FenceSplitResult:
    """Split *text* into three regions using fence markers.

    Returns a FenceSplitResult with state in {'found', 'no_fence', 'malformed'}.

    State semantics:
      found    — both markers present and well-formed (start before end, no
                 duplicate start between start and end).
                 .before includes everything up to and including the start line.
                 .managed is the text between markers (may be empty).
                 .after is everything after the end line, byte-for-byte (INV-5).
                 Sentinel lines in .after are ignored — only structural position
                 determines region boundaries (INV-5 data-loss fix).
      no_fence — neither marker found (metadata-only Phase B file).
      malformed — only one marker found, end appears before start, or a second
                  standalone start token appears between start and end.
                  Treat as user-owned; do NOT overwrite. (D12)

    Algorithm (structural-position anchoring):
      1. First standalone start line  → opening fence (structural position).
      2. First standalone end line AFTER the opening fence → closing fence.
      3. Any standalone start line between opening and closing fence → malformed.
      4. Everything after the closing fence line is user tail, preserved
         byte-for-byte regardless of sentinel content (INV-5).
    """
    # Intent: locate fence markers by exact full-line match (rstrip handles
    # trailing CR on Windows); structural position rules, not substring search.
    lines = text.split("\n")

    # Collect all standalone occurrences by index
    start_indices: list[int] = []
    end_indices: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == start_token:
            start_indices.append(i)
        elif stripped == end_token:
            end_indices.append(i)

    has_start = bool(start_indices)
    has_end = bool(end_indices)

    if not has_start and not has_end:
        return FenceSplitResult(state="no_fence")

    if not has_start:
        # End marker(s) present but no start marker
        return FenceSplitResult(
            state="malformed",
            warning=(
                "Fence start marker missing; treating file as user-owned "
                "(D12). File will NOT be overwritten. "
                "Re-install with mapify to restore fence structure."
            ),
        )

    # Opening fence: structurally first standalone start line
    start_idx = start_indices[0]

    # Closing fence: FIRST standalone end line AFTER the opening fence.
    # (End lines at or before start_idx are ignored — they belong to user
    #  content written above the fence, which is unusual but not our bug.)
    end_after_start = [idx for idx in end_indices if idx > start_idx]

    if not end_after_start:
        # No end marker found after the start marker
        return FenceSplitResult(
            state="malformed",
            warning=(
                "Fence end marker missing after start marker; treating file as "
                "user-owned (D12). File will NOT be overwritten. "
                "Re-install with mapify to restore fence structure."
            ),
        )

    end_idx = end_after_start[0]  # FIRST end after start — structural close

    # Check for a second standalone start between start_idx and end_idx.
    # This indicates a corrupted or hand-edited fence structure.
    extra_starts_in_managed = [
        idx for idx in start_indices if start_idx < idx < end_idx
    ]
    if extra_starts_in_managed:
        return FenceSplitResult(
            state="malformed",
            warning=(
                "Duplicate fence start marker found inside managed region; "
                "treating file as user-owned (D12). File will NOT be "
                "overwritten. Re-install with mapify to restore fence structure."
            ),
        )

    # Well-formed fence found.
    # before: lines 0..start_idx inclusive, rejoined + trailing newline
    before_lines = lines[: start_idx + 1]
    before = "\n".join(before_lines) + "\n"

    # managed: lines between markers (exclusive), rejoined
    managed_lines = lines[start_idx + 1 : end_idx]
    managed = "\n".join(managed_lines)
    if managed_lines:
        managed += "\n"

    # after: end_token line + "\n" + everything after it (byte-for-byte, INV-5).
    # Convention: after = end_token + "\n" + user_content_after_fence.
    # lines[end_idx] is the end_token stripped line; lines[end_idx+1:] is user tail.
    # Reconstruct user tail by re-joining the remaining elements.
    # text.split("\n") always produces a trailing "" element when text ends with "\n",
    # so "\n".join(user_tail_lines) already encodes the trailing newline correctly —
    # do NOT add an extra "\n".
    # IMPORTANT: user_tail_lines may contain literal sentinel lines (e.g. a shell
    # heredoc that documents MAP fence syntax).  We do NOT scan them — only the
    # structural position of end_idx determines the boundary (INV-5).
    user_tail_lines = lines[end_idx + 1 :]
    user_tail = "\n".join(user_tail_lines) if user_tail_lines else ""
    after = end_token + "\n" + user_tail

    return FenceSplitResult(
        state="found",
        before=before,
        managed=managed,
        after=after,
    )


def _assemble_fenced(
    before: str,
    new_managed_body: str,
    end_token: str,
    user_tail: str,
) -> str:
    """Assemble the final fenced file text.

    Layout:
      <before>          — includes metadata line + fence-start line + trailing \\n
      <new_managed_body>  — managed region body (should end with \\n or be empty)
      <end_token>\\n
      <user_tail>       — after_user, byte-for-byte (INV-5); may be empty
    """
    # Ensure new_managed_body ends with newline if non-empty
    body = new_managed_body
    if body and not body.endswith("\n"):
        body += "\n"

    # user_tail: preserve byte-for-byte; if it starts with \n that's intentional
    return before + body + end_token + "\n" + user_tail


def _build_fenced_content(
    metadata_line: str,
    start_token: str,
    end_token: str,
    managed_body: str,
    user_tail: str = "",
) -> str:
    """Build full fenced file content for a first-time install.

    Layout:
      <metadata_line>\\n
      <start_token>\\n
      <managed_body>
      <end_token>\\n
      <user_tail>
    """
    # Ensure metadata line ends with \n
    meta = metadata_line if metadata_line.endswith("\n") else metadata_line + "\n"
    # Ensure managed_body ends with \n if non-empty
    body = managed_body
    if body and not body.endswith("\n"):
        body += "\n"
    return meta + start_token + "\n" + body + end_token + "\n" + user_tail


# ---------------------------------------------------------------------------
# Main copy function
# ---------------------------------------------------------------------------


def copy_managed_file(
    src: Path,
    dest: Path,
    version: str,
    *,
    inject_meta: bool = True,
    fenced: bool = True,
) -> CopyResult:
    """Copy a template file to destination with metadata injection and drift detection.

    Two managed modes (per user decision on watched-vs-overwritten categories):

    * ``fenced=True`` (WATCHED) — Phase C2 fence-aware merge.  The managed region
      is wrapped between fence markers; any user content BELOW the closing fence is
      preserved byte-for-byte (INV-5).  Use for files a downstream user may extend
      in place (agents, hooks, skills, CLAUDE.md, codex agents/config/AGENTS.md).

    * ``fenced=False`` (OVERWRITE) — fully-managed Phase B behavior: inject metadata,
      overwrite the whole file, and back up to ``.bak.<ts>`` if the destination
      drifted.  No fence markers.  Use for files we fully own and always replace
      (references, map/scripts, map/static-analysis, workflow-rules/ralph configs).

    JSON is always fully-managed via the ``_map_managed`` root key regardless of
    ``fenced`` (JSON has no comment syntax for fences — D9).

    Args:
        src: Source template file.
        dest: Destination path in user's project.
        version: Current mapify-cli version string.
        inject_meta: Whether to inject metadata header (False for binary files).
        fenced: Whether to wrap the managed region in fence markers (watched mode)
            or fully overwrite (overwrite mode). Ignored for JSON / binary.

    Returns:
        CopyResult with drift/backup information.
    """
    ext = dest.suffix.lower()
    is_text_ext = ext in (
        ".md",
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".sh",
        ".txt",
    )

    # If not a text file we know how to annotate, do a plain copy
    if not is_text_ext or not inject_meta:
        result = CopyResult(src=src, dest=dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return result

    # Read source
    try:
        src_content = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # Binary file masquerading with text extension — plain copy
        result = CopyResult(src=src, dest=dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return result

    template_hash = compute_hash(src_content)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # JSON: fully managed via _map_managed root key — no fence (D9)
    # -----------------------------------------------------------------------
    if ext == ".json":
        return _copy_json_managed(src, dest, src_content, version, template_hash)

    # -----------------------------------------------------------------------
    # OVERWRITE mode (fenced=False): fully-managed text file — inject metadata,
    # back up to .bak.<ts> on drift, overwrite whole file.  No fence markers.
    # Used for categories we fully own (references, map tools, config files).
    # -----------------------------------------------------------------------
    if not fenced and ext in _FENCE_TOKENS:
        return _copy_overwrite_managed(
            src, dest, src_content, version, template_hash, ext
        )

    # -----------------------------------------------------------------------
    # Non-fence-supported extensions (e.g. .txt) — plain copy with no metadata
    # -----------------------------------------------------------------------
    fence_tokens = _FENCE_TOKENS.get(ext)
    if fence_tokens is None and ext not in _FENCE_TOKENS:
        # ext not in map at all (e.g. .txt) — copy without metadata
        result = CopyResult(src=src, dest=dest)
        try:
            _atomic_write(dest, src_content)
            result.success = True
        except OSError as exc:
            result.success = False
            result.reason = f"write failed: {exc}"
        return result

    # -----------------------------------------------------------------------
    # Text formats with metadata support (.md, .py, .sh, .toml, .yaml, .yml)
    # -----------------------------------------------------------------------
    assert fence_tokens is not None  # satisfied for all these extensions
    start_token, end_token = fence_tokens

    # Build the metadata-injected managed body (the src content with meta header)
    # inject_metadata returns: [frontmatter?] + metadata_line + src_body
    # We need to separate the metadata header from the rest for fence assembly.
    injected = inject_metadata(src_content, ext, version, template_hash)

    # Split the injected content into metadata_prefix and body
    # For .md: metadata is <!-- MAP-MANAGED: ... -->\n (possibly after frontmatter)
    # For .py: metadata is # MAP-MANAGED: ...\n (possibly after shebang)
    # We reconstruct: metadata_prefix + fence + body + /fence
    meta_prefix, body_after_meta = _split_metadata_prefix(injected, ext)

    # -----------------------------------------------------------------------
    # Case A: dest does not exist → first install
    # -----------------------------------------------------------------------
    if not dest.exists():
        final_text = _build_fenced_content(
            metadata_line=meta_prefix.rstrip("\n"),
            start_token=start_token,
            end_token=end_token,
            managed_body=body_after_meta,
        )
        result = CopyResult(src=src, dest=dest)
        try:
            _atomic_write(dest, final_text)
            result.success = True
        except OSError as exc:
            result.success = False
            result.reason = f"write failed: {exc}"
        return result

    # -----------------------------------------------------------------------
    # Case B: dest exists → fence-aware merge
    # -----------------------------------------------------------------------

    # Security: refuse symlinks before any read/write
    try:
        _assert_safe_dest(dest)
    except OSError as exc:
        result = CopyResult(src=src, dest=dest)
        result.success = False
        result.reason = str(exc)
        return result

    try:
        dest_content = dest.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        result = CopyResult(src=src, dest=dest)
        result.success = False
        result.reason = f"cannot read dest: {exc}"
        return result

    # Check for existing metadata (required to know if this is a managed file)
    existing_meta, _ = extract_metadata(dest_content, ext)

    if existing_meta is None:
        # No metadata → user file; apply drift backup + overwrite (legacy path)
        return _overwrite_user_file(
            src, dest, meta_prefix, body_after_meta,
            start_token, end_token,
        )

    # --- Managed file: parse fence state ---
    fence_result = _split_fence(dest_content, start_token, end_token)

    if fence_result.state == "malformed":
        # D12: user deleted/corrupted fence markers → treat as user-owned, skip
        result = CopyResult(src=src, dest=dest)
        result.success = True  # not a hard error, just skipped
        result.reason = fence_result.warning
        print(
            f"WARNING: {dest}: {fence_result.warning}",
            file=sys.stderr,
        )
        return result

    if fence_result.state == "no_fence":
        # INV-T / D10: legacy unfenced install (metadata present, no fence markers).
        # Silently upgrade it to the fenced layout — exactly what a fresh install
        # writes (Case A).  Legacy unfenced files were fully managed (no user tail),
        # so the entire body becomes the managed region inside the fence.
        #
        # This migration is one-time and invisible by design: once the fence is
        # written, the next copy_managed_file() run finds state == "found" and takes
        # the normal merge path, so this branch never fires for that file again.
        # We deliberately emit NO per-file notice — a routine, self-healing upgrade
        # should not flood stderr with alarming lines on every `mapify init`.
        stored_hash = existing_meta.get("template_hash", "")
        _, clean_dest = extract_metadata(dest_content, ext)
        current_hash = compute_hash(clean_dest)

        result = CopyResult(src=src, dest=dest)
        result.migrated = True
        result.reason = "upgraded legacy unfenced file to fenced layout"

        # Back up only when the user modified the previously fully-managed body
        # (hash drift), mirroring the fenced-merge drift-backup behavior.
        if stored_hash and current_hash != stored_hash:
            result.drifted = True
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
            try:
                shutil.copy2(dest, backup_path)
                result.backed_up = True
                result.backup_path = backup_path
            except OSError:
                result.reason += " (backup failed)"

        final_text = _build_fenced_content(
            metadata_line=meta_prefix.rstrip("\n"),
            start_token=start_token,
            end_token=end_token,
            managed_body=body_after_meta,
        )
        try:
            _atomic_write(dest, final_text)
            result.success = True
        except OSError as exc:
            result.success = False
            result.reason = f"write failed: {exc}"

        return result

    # fence_result.state == 'found': standard fence-aware merge

    # Drift detection: two cases trigger a backup before overwriting.
    #
    # Case 1 — template changed: stored_hash (written at install) != template_hash
    #           (hash of src NOW).  The managed body will change → backup current dest.
    #
    # Case 2 — user modified the managed region: the managed body currently in dest
    #           differs from what was written there at install time.
    #           At install time we wrote body_after_meta derived from the SAME src.
    #           Recompute body_after_meta from current src (same src as install if no
    #           template change) and compare against the live managed body in dest.
    #           If they differ, user edited inside the fence → backup.
    stored_hash = existing_meta.get("template_hash", "")
    template_changed = bool(stored_hash and stored_hash != template_hash)

    # body_after_meta is already computed above from current src.
    # Normalize trailing newline for comparison (managed body ends with \n or "").
    current_body_norm = body_after_meta if body_after_meta.endswith("\n") else body_after_meta + "\n"
    dest_managed_norm = fence_result.managed if fence_result.managed.endswith("\n") else fence_result.managed + "\n"
    user_modified_managed = (current_body_norm != dest_managed_norm)

    result = CopyResult(src=src, dest=dest)

    if template_changed or user_modified_managed:
        result.drifted = True
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
        try:
            shutil.copy2(dest, backup_path)
            result.backed_up = True
            result.backup_path = backup_path
        except OSError:
            result.reason += " (backup failed)"

    user_tail = _extract_user_tail(fence_result.after, end_token)
    final_text = _assemble_fenced(
        before=fence_result.before,
        new_managed_body=body_after_meta,
        end_token=end_token,
        user_tail=user_tail,
    )

    # Update the metadata line in 'before' to have the new template_hash/version
    # (The current 'before' contains the OLD metadata line from dest.)
    final_text = _replace_metadata_in_before(
        final_text, meta_prefix, ext, start_token
    )

    try:
        _atomic_write(dest, final_text)
        result.success = True
    except OSError as exc:
        result.success = False
        result.reason += f" write failed: {exc}"

    return result


# ---------------------------------------------------------------------------
# Internal helpers for copy_managed_file
# ---------------------------------------------------------------------------


def _copy_json_managed(
    src: Path,
    dest: Path,
    src_content: str,
    version: str,
    template_hash: str,
) -> CopyResult:
    """JSON: fully managed path (no fence). Preserves existing Phase B behavior."""
    # Detect drift if destination exists
    drift_result = detect_drift(src, dest)

    # Create backup if drifted
    if drift_result.drifted:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
        try:
            shutil.copy2(dest, backup_path)
            drift_result.backed_up = True
            drift_result.backup_path = backup_path
        except OSError:
            drift_result.reason += " (backup failed)"

    final_content = inject_metadata(src_content, ".json", version, template_hash)
    try:
        _atomic_write(dest, final_content)
        drift_result.success = True
    except OSError as exc:
        drift_result.success = False
        drift_result.reason += f" (write failed: {exc})"
        return drift_result

    return drift_result


def _copy_overwrite_managed(
    src: Path,
    dest: Path,
    src_content: str,
    version: str,
    template_hash: str,
    ext: str,
) -> CopyResult:
    """Fully-managed text path (no fence): inject metadata, back up on drift, overwrite.

    Mirrors ``_copy_json_managed`` for comment-bearing text formats (.md/.py/.sh/
    .toml/.yaml/.yml) when the caller selects OVERWRITE mode (``fenced=False``).
    The whole file is owned by MAP; a drifted destination is backed up to
    ``.bak.<ts>`` before being replaced.
    """
    drift_result = detect_drift(src, dest)

    if drift_result.drifted:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
        try:
            shutil.copy2(dest, backup_path)
            drift_result.backed_up = True
            drift_result.backup_path = backup_path
        except OSError:
            drift_result.reason += " (backup failed)"

    final_content = inject_metadata(src_content, ext, version, template_hash)
    try:
        _atomic_write(dest, final_content)
        drift_result.success = True
    except OSError as exc:
        drift_result.success = False
        drift_result.reason += f" (write failed: {exc})"

    return drift_result


def _split_metadata_prefix(injected: str, ext: str) -> tuple[str, str]:
    """Split injected content into (metadata_prefix, body_after_meta).

    metadata_prefix: the MAP-MANAGED comment line (incl. trailing \\n),
                     plus any frontmatter/shebang that precedes it.
    body_after_meta: everything after the metadata line.
    """
    if ext == ".md":
        # Case 1: frontmatter before metadata
        if injected.startswith("---\n"):
            end_idx = injected.find("\n---\n", 3)
            if end_idx != -1:
                after_fm = end_idx + 5  # position after \n---\n
                rest = injected[after_fm:]
                m = _MD_PATTERN.match(rest)
                if m:
                    # metadata_prefix = frontmatter + MAP-MANAGED line
                    return injected[:after_fm] + rest[: m.end()], rest[m.end() :]
        # Case 2: no frontmatter
        m = _MD_PATTERN.match(injected)
        if m:
            return injected[: m.end()], injected[m.end() :]
        # Fallback: no metadata found (shouldn't happen for supported ext)
        return "", injected

    if ext in (".py", ".sh", ".bash"):
        # Shebang (optional) + MAP-MANAGED line
        if injected.startswith("#!"):
            newline_pos = injected.index("\n") + 1
            shebang = injected[:newline_pos]
            rest = injected[newline_pos:]
            m = _PY_PATTERN.match(rest)
            if m:
                return shebang + rest[: m.end()], rest[m.end() :]
        m = _PY_PATTERN.match(injected)
        if m:
            return injected[: m.end()], injected[m.end() :]
        return "", injected

    if ext in (".toml", ".yaml", ".yml"):
        # Same comment style as .py
        m = _PY_PATTERN.match(injected)
        if m:
            return injected[: m.end()], injected[m.end() :]
        return "", injected

    return "", injected


def _extract_user_tail(after: str, end_token: str) -> str:
    """Extract the user tail from the fence 'after' region.

    The 'after' region from _split_fence includes the end_token line itself
    followed by the user content.  Strip the end_token line and return
    only the user tail (byte-for-byte, INV-5).
    """
    # after starts with the end_token line; remove it
    prefix = end_token + "\n"
    if after.startswith(prefix):
        return after[len(prefix):]
    # end_token at end of file with no trailing newline
    if after == end_token:
        return ""
    # Unexpected format — return as-is to be safe
    return after


def _replace_metadata_in_before(
    final_text: str, new_meta_prefix: str, ext: str, start_token: str
) -> str:
    """Replace the old metadata line in final_text with new_meta_prefix.

    final_text already has the correct structure:
      [frontmatter] + [old_metadata_line] + start_token + ... + end_token + user_tail

    We want:
      [frontmatter] + [new_metadata_line] + start_token + ... + end_token + user_tail
    """
    # Locate the start_token line; metadata is immediately before it
    start_line = start_token + "\n"
    start_pos = final_text.find(start_line)
    if start_pos == -1:
        # start_token at end of file (no trailing newline)
        start_pos = final_text.find(start_token)
        if start_pos == -1:
            return final_text  # can't locate; return unchanged

    # Everything before start_token is the "before" part incl. old metadata
    before_start = final_text[:start_pos]
    after_start = final_text[start_pos:]

    # Replace old metadata in before_start with new_meta_prefix
    if ext == ".md":
        # Find the MAP-MANAGED comment line in before_start
        m = _MD_PATTERN.search(before_start)
        if m:
            new_before = before_start[: m.start()] + new_meta_prefix
            return new_before + after_start
    elif ext in (".py", ".sh", ".bash", ".toml", ".yaml", ".yml"):
        # Find MAP-MANAGED comment line
        m = _PY_PATTERN.search(before_start)
        if m:
            new_before = before_start[: m.start()] + new_meta_prefix
            return new_before + after_start

    # Fallback: prepend new metadata before start_token
    return new_meta_prefix + after_start


def _overwrite_user_file(
    src: Path,
    dest: Path,
    meta_prefix: str,
    body_after_meta: str,
    start_token: str,
    end_token: str,
) -> CopyResult:
    """Handle dest file with no metadata (user-owned or pre-Phase-B).

    Creates a timestamped backup, then overwrites with fenced content.
    """
    result = CopyResult(src=src, dest=dest)
    result.drifted = True

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
    try:
        shutil.copy2(dest, backup_path)
        result.backed_up = True
        result.backup_path = backup_path
    except OSError:
        result.reason += " (backup failed)"

    final_text = _build_fenced_content(
        metadata_line=meta_prefix.rstrip("\n"),
        start_token=start_token,
        end_token=end_token,
        managed_body=body_after_meta,
    )
    try:
        _atomic_write(dest, final_text)
        result.success = True
    except OSError as exc:
        result.success = False
        result.reason += f" write failed: {exc}"

    return result
