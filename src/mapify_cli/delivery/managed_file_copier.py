"""Drift-aware file copier for MAP Framework delivery.

Provides copy_managed_file() which replaces raw shutil.copy2() with:
  1. Metadata injection (generated_by, mapify_version, template_hash)
  2. Drift detection on upgrade (user modifications vs template)
  3. Automatic .bak backup before overwriting drifted files

Metadata formats by file type:
  .md   → <!-- MAP-MANAGED: {...} -->
  .py   → # MAP-MANAGED: {...}
  .json → "_map_managed": {...} key in root object
  other → no metadata (plain copy)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


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
    backup_path: Optional[Path] = None
    reason: str = ""
    first_install: bool = False


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
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def inject_metadata(content: str, ext: str, version: str, template_hash: str) -> str:
    """Prepend/inject metadata into file content based on extension.

    Returns modified content. For unsupported extensions, returns content unchanged.
    """
    meta = _build_metadata(version, template_hash)
    meta_json = json.dumps(meta, separators=(",", ":"))

    if ext == ".md":
        header = f"<!-- {_MANAGED_TAG}: {meta_json} -->\n"
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

    # Unknown extension — no metadata
    return content


def extract_metadata(content: str, ext: str) -> tuple[Optional[dict[str, Any]], str]:
    """Extract metadata from file content and return (metadata, clean_content).

    Returns (None, original_content) if no metadata found.
    """
    if ext == ".md":
        m = _MD_PATTERN.match(content)
        if m:
            try:
                meta = json.loads(m.group(1))
                return meta, content[m.end():]
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
                    after_parts = lines[check_idx + 1:]
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
        result.reason = f"content modified (hash {current_hash[:8]}… ≠ {stored_hash[:8]}…)"

    return result


# ---------------------------------------------------------------------------
# Main copy function
# ---------------------------------------------------------------------------

def copy_managed_file(
    src: Path,
    dest: Path,
    version: str,
    *,
    inject_meta: bool = True,
) -> CopyResult:
    """Copy a template file to destination with metadata injection and drift detection.

    Args:
        src: Source template file.
        dest: Destination path in user's project.
        version: Current mapify-cli version string.
        inject_meta: Whether to inject metadata header (False for binary files).

    Returns:
        CopyResult with drift/backup information.
    """
    ext = dest.suffix.lower()
    is_text_ext = ext in (".md", ".py", ".json", ".yaml", ".yml", ".toml", ".sh", ".txt")

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

    # Detect drift if destination exists
    drift_result = detect_drift(src, dest)

    # Create backup if drifted (timestamped to avoid collision on repeated upgrades)
    if drift_result.drifted:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup_path = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
        try:
            shutil.copy2(dest, backup_path)
            drift_result.backed_up = True
            drift_result.backup_path = backup_path
        except OSError:
            drift_result.reason += " (backup failed)"

    # Inject metadata for supported types
    if ext in (".md", ".py", ".json"):
        final_content = inject_metadata(src_content, ext, version, template_hash)
    else:
        # .yaml, .yml, .toml, .sh, .txt — copy without metadata for now
        final_content = src_content

    # Write
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_text(final_content, encoding="utf-8")
    except OSError as exc:
        drift_result.success = False
        drift_result.reason += f" (write failed: {exc})"
        return drift_result

    drift_result.success = True
    return drift_result
