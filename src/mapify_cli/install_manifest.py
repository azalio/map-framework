"""Install manifest/lock for MAP-managed provider surfaces.

Writes .map/mapify.lock.json during ``mapify init`` and provides
``check-installed`` comparison. The manifest records every MAP-managed
file installed by the provider so the installed surface can be audited
as a whole rather than file-by-file.

Security invariants:
- No absolute paths stored in the committed manifest.
- Local-only files (statusline, machine-specific state) are excluded from
  the committed manifest.
- No secrets or credential paths are written here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mapify_cli.delivery.managed_file_copier import compute_hash, extract_metadata

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_FILENAME = "mapify.lock.json"

# Relative paths (from project root) that are machine-local and should
# NOT appear in the committed manifest.
_LOCAL_ONLY_RELPATHS: frozenset[str] = frozenset({
    ".claude/settings.local.json",
})

# Fence start tokens by extension (mirrors managed_file_copier._FENCE_TOKENS)
_FENCE_START_BY_EXT: dict[str, str] = {
    ".md": "<!-- map:start -->",
    ".py": "# map:start",
    ".sh": "# map:start",
    ".bash": "# map:start",
    ".toml": "# map:start",
    ".yaml": "# map:start",
    ".yml": "# map:start",
}

# Files installed WITHOUT MAP-MANAGED metadata (Codex hooks.json uses its own
# merge strategy that is incompatible with the _map_managed root key).
_HOOKS_MERGE_RELPATHS: frozenset[str] = frozenset({
    ".codex/hooks.json",
})

# Directories to scan per provider (relative to project root).
# Only the directories that each provider's install functions write to.
_CLAUDE_SCAN_ROOTS: list[str] = [
    ".claude/agents",
    ".claude/skills",
    ".claude/references",
    ".claude/hooks",
    ".claude/rules",
    ".map/scripts",
    ".map/static-analysis",
]
_CLAUDE_SINGLE_FILES: list[str] = [
    ".claude/settings.json",
    ".claude/ralph-loop-config.json",
    ".claude/workflow-rules.json",
]

_CODEX_SCAN_ROOTS: list[str] = [
    ".agents/skills",
    ".codex/agents",
    ".codex/hooks",
    ".map/scripts",
]
_CODEX_SINGLE_FILES: list[str] = [
    ".codex/config.toml",
    ".codex/hooks.json",
    "AGENTS.md",
]

# Ignored names/suffixes during directory scans (mirrors file_copier constants)
_IGNORED_NAMES: frozenset[str] = frozenset({"__pycache__", ".DS_Store"})
_IGNORED_SUFFIXES: frozenset[str] = frozenset({".pyc", ".pyo"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ManifestEntry:
    """One MAP-managed file in the install manifest."""

    dest: str             # relative path from project root (POSIX separators)
    content_hash: str     # SHA-256 of file content with metadata stripped
    template_hash: str    # SHA-256 of the template source at install time
    management_mode: str  # "fenced" | "full" | "hooks-merge"
    committed: bool       # True when this file should be committed to VCS
    mapify_version: str   # mapify-cli version that installed this file
    installed_at: str     # ISO 8601 UTC timestamp from the MAP-MANAGED header


@dataclass
class InstallManifest:
    """Aggregate install lock for all MAP-managed provider surfaces."""

    mapify_version: str
    provider: str
    installed_at: str     # manifest write timestamp
    entries: list[ManifestEntry] = field(default_factory=list)


@dataclass
class CheckResult:
    """Outcome of check_installed()."""

    missing: list[str] = field(default_factory=list)   # in manifest, absent from disk
    orphaned: list[str] = field(default_factory=list)  # MAP-managed on disk, not in manifest
    drifted: list[str] = field(default_factory=list)   # template_hash differs vs manifest
    ok: list[str] = field(default_factory=list)        # present and matching


# ---------------------------------------------------------------------------
# Management-mode inference
# ---------------------------------------------------------------------------


def _infer_management_mode(dest: Path, content: str, ext: str) -> str:
    """Infer the management mode from the installed file's content."""
    if ext == ".json":
        # JSON files are always fully managed via _map_managed root key.
        return "full"
    fence_start = _FENCE_START_BY_EXT.get(ext)
    if fence_start and fence_start in content:
        return "fenced"
    return "full"


# ---------------------------------------------------------------------------
# Single-file entry building
# ---------------------------------------------------------------------------


def _build_entry_from_file(
    project_path: Path,
    abs_path: Path,
) -> Optional[ManifestEntry]:
    """Build a ManifestEntry from an installed managed file.

    Returns None when the file has no MAP-MANAGED metadata (unmanaged).
    Skips symlinks to avoid following them (security invariant).
    """
    if abs_path.is_symlink():
        return None  # AGENTS.md may be a symlink to CLAUDE.md

    rel_str = abs_path.relative_to(project_path).as_posix()

    # Local-only files are excluded from the committed manifest
    if rel_str in _LOCAL_ONLY_RELPATHS:
        return None

    # Special case: hooks.json uses hooks-merge mode without MAP metadata
    if rel_str in _HOOKS_MERGE_RELPATHS:
        if abs_path.exists():
            raw = abs_path.read_text(encoding="utf-8", errors="replace")
            return ManifestEntry(
                dest=rel_str,
                content_hash=compute_hash(raw),
                template_hash="",
                management_mode="hooks-merge",
                committed=True,
                mapify_version="",
                installed_at="",
            )
        return None

    if not abs_path.is_file():
        return None

    try:
        content = abs_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    ext = abs_path.suffix.lower()
    meta, clean_content = extract_metadata(content, ext)
    if meta is None:
        return None  # not a MAP-managed file

    mode = _infer_management_mode(abs_path, content, ext)
    return ManifestEntry(
        dest=rel_str,
        content_hash=compute_hash(clean_content),
        template_hash=meta.get("template_hash", ""),
        management_mode=mode,
        committed=True,
        mapify_version=meta.get("mapify_version", ""),
        installed_at=meta.get("installed_at", ""),
    )


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


def _scan_dir(project_path: Path, rel_dir: str) -> list[ManifestEntry]:
    """Recursively scan a directory for MAP-managed files."""
    entries: list[ManifestEntry] = []
    abs_dir = project_path / rel_dir
    if not abs_dir.is_dir():
        return entries
    for abs_path in sorted(abs_dir.rglob("*")):
        if not abs_path.is_file():
            continue
        if abs_path.name in _IGNORED_NAMES or abs_path.suffix in _IGNORED_SUFFIXES:
            continue
        entry = _build_entry_from_file(project_path, abs_path)
        if entry is not None:
            entries.append(entry)
    return entries


def _scan_file(project_path: Path, rel_file: str) -> Optional[ManifestEntry]:
    """Scan a single known file path."""
    return _build_entry_from_file(project_path, project_path / rel_file)


# ---------------------------------------------------------------------------
# Manifest building
# ---------------------------------------------------------------------------


def build_manifest(
    project_path: Path,
    provider: str,
    version: str,
) -> InstallManifest:
    """Build an InstallManifest by scanning the installed provider surfaces.

    Scans directories written by the given provider's install() method and
    collects all files that carry MAP-MANAGED metadata. Local-only files and
    symlinks are excluded from the committed manifest.
    """
    entries: list[ManifestEntry] = []

    if provider == "claude":
        for rel_dir in _CLAUDE_SCAN_ROOTS:
            entries.extend(_scan_dir(project_path, rel_dir))
        for rel_file in _CLAUDE_SINGLE_FILES:
            entry = _scan_file(project_path, rel_file)
            if entry is not None:
                entries.append(entry)
    elif provider == "codex":
        for rel_dir in _CODEX_SCAN_ROOTS:
            entries.extend(_scan_dir(project_path, rel_dir))
        for rel_file in _CODEX_SINGLE_FILES:
            entry = _scan_file(project_path, rel_file)
            if entry is not None:
                entries.append(entry)
    # Unknown provider: no entries (still writes an empty manifest)

    # Stable sort: alphabetical by dest path
    entries.sort(key=lambda e: e.dest)

    return InstallManifest(
        mapify_version=version,
        provider=provider,
        installed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Persist / load
# ---------------------------------------------------------------------------


def write_manifest(project_path: Path, manifest: InstallManifest) -> Path:
    """Write the manifest to .map/mapify.lock.json and return the path."""
    map_dir = project_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    dest = map_dir / MANIFEST_FILENAME
    data = asdict(manifest)
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def read_manifest(project_path: Path) -> Optional[InstallManifest]:
    """Read and parse .map/mapify.lock.json.

    Returns None when the manifest does not exist or cannot be parsed.
    """
    path = project_path / ".map" / MANIFEST_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        raw_entries = data.get("entries", [])
        entries = [ManifestEntry(**e) for e in raw_entries if isinstance(e, dict)]
        return InstallManifest(
            mapify_version=data.get("mapify_version", ""),
            provider=data.get("provider", ""),
            installed_at=data.get("installed_at", ""),
            entries=entries,
        )
    except (TypeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# check-installed comparison
# ---------------------------------------------------------------------------


def check_installed(project_path: Path) -> CheckResult:
    """Compare the current installed surface against .map/mapify.lock.json.

    For each manifest entry:
    - missing: file does not exist on disk
    - drifted: file exists but its MAP-MANAGED template_hash differs from the
      manifest's recorded template_hash (template was updated)
    - ok: file present and template_hash matches

    Also scans the installed directories to detect orphaned MAP-managed files
    (files that carry MAP-MANAGED metadata but are not recorded in the manifest).
    """
    result = CheckResult()
    manifest = read_manifest(project_path)
    if manifest is None:
        return result

    manifest_paths: set[str] = set()
    for entry in manifest.entries:
        manifest_paths.add(entry.dest)
        abs_path = project_path / entry.dest

        if entry.management_mode == "hooks-merge":
            # hooks.json has no MAP metadata; just check existence
            if abs_path.exists() and not abs_path.is_symlink():
                result.ok.append(entry.dest)
            else:
                result.missing.append(entry.dest)
            continue

        if not abs_path.exists() or abs_path.is_symlink():
            result.missing.append(entry.dest)
            continue

        try:
            content = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            result.missing.append(entry.dest)
            continue

        ext = abs_path.suffix.lower()
        meta, _ = extract_metadata(content, ext)

        if meta is None:
            # Metadata was stripped — treat as drifted
            result.drifted.append(entry.dest)
            continue

        current_template_hash = meta.get("template_hash", "")
        if current_template_hash != entry.template_hash:
            result.drifted.append(entry.dest)
        else:
            result.ok.append(entry.dest)

    # Orphan detection: scan directories for MAP-managed files not in manifest
    provider = manifest.provider
    scan_roots: list[str] = []
    single_files: list[str] = []
    if provider == "claude":
        scan_roots = _CLAUDE_SCAN_ROOTS
        single_files = _CLAUDE_SINGLE_FILES
    elif provider == "codex":
        scan_roots = _CODEX_SCAN_ROOTS
        single_files = _CODEX_SINGLE_FILES

    on_disk_managed: set[str] = set()
    for rel_dir in scan_roots:
        for entry in _scan_dir(project_path, rel_dir):
            on_disk_managed.add(entry.dest)
    for rel_file in single_files:
        single_entry = _scan_file(project_path, rel_file)
        if single_entry is not None:
            on_disk_managed.add(single_entry.dest)

    for rel in sorted(on_disk_managed - manifest_paths):
        result.orphaned.append(rel)

    return result
