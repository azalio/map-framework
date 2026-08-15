"""File copy/generation functions for MAP Framework delivery."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import secrets
import shutil
import stat
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from mapify_cli.delivery.agent_generator import (
    create_actor_content,
    create_documentation_reviewer_content,
    create_evaluator_content,
    create_monitor_content,
    create_predictor_content,
    create_reflector_content,
    create_task_decomposer_content,
)
from mapify_cli.delivery.managed_file_copier import (
    DriftReport,
    copy_managed_file,
)
from mapify_cli.schemas import (
    SKILL_REQUIREMENTS_KEYS,
    SKILL_REQUIREMENTS_SCHEMA,
    validate_artifact,
)

_IGNORED_TEMPLATE_NAMES = {"__pycache__", ".DS_Store"}
_IGNORED_TEMPLATE_SUFFIXES = {".pyc", ".pyo"}

# Ordered check dispatch for blocking requires-* keys.
# _BLOCKING_REQUIRES_KEYS is derived from SKILL_REQUIREMENTS_KEYS (schema authority).
# The module-level check below enforces that _REQUIRES_CHECKER covers EVERY
# blocking key derived from the schema: adding a new blocking key to
# SKILL_REQUIREMENTS_SCHEMA raises RuntimeError at import time unless a
# corresponding checker is added here — the invariant is mechanically enforced,
# not just documented. (A bare ``assert`` would be stripped under ``python -O``,
# silently turning the guarantee into a no-op, so we raise explicitly.)
# requires-skills is warn-only (not a skip), handled separately.
_BLOCKING_REQUIRES_KEYS = {k for k in SKILL_REQUIREMENTS_KEYS if k != "requires-skills"}


def _check_requires_cmd(name: str) -> bool:
    """Return True if CLI command *name* is available on PATH.

    Mirrors ``check_tool()`` in ``mapify_cli.__init__``: the Claude CLI may be
    installed only at ``~/.claude/local/claude`` (not on PATH), so that location
    counts as present. Kept deliberately in sync — importing ``check_tool`` here
    would create a circular import (``mapify_cli.__init__`` imports this module).
    """
    if name == "claude":
        claude_local = Path.home() / ".claude" / "local" / "claude"
        if claude_local.is_file():
            return True
    return shutil.which(name) is not None


def _check_requires_pip(name: str) -> bool:
    """Return True if Python module *name* is importable."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _check_requires_env(name: str) -> bool:
    """Return True if environment variable *name* is set.

    SECURITY: reads variable NAME presence only — never reads the value,
    never accesses .env files.
    """
    return name in os.environ


_REQUIRES_CHECKER = {
    "requires-cmd": _check_requires_cmd,
    "requires-pip": _check_requires_pip,
    "requires-env": _check_requires_env,
}

# Enforced invariant: every blocking key derived from the schema must have a
# checker entry here.  Adding a new blocking key to SKILL_REQUIREMENTS_SCHEMA
# without a matching checker raises RuntimeError at import time.  Uses an
# explicit raise (not ``assert``) so the guarantee survives ``python -O``.
if _BLOCKING_REQUIRES_KEYS != set(_REQUIRES_CHECKER):
    raise RuntimeError(
        "_REQUIRES_CHECKER is out of sync with SKILL_REQUIREMENTS_KEYS; "
        f"missing checkers for: {_BLOCKING_REQUIRES_KEYS - set(_REQUIRES_CHECKER)}"
    )


def _skill_missing_dependency(
    requires_block: dict[str, list[str]],
) -> tuple[str, str] | None:
    """Return (kind, name) of the first missing blocking dependency, or None.

    Checks requires-cmd, requires-pip, requires-env in that order (dict
    insertion order — cmd first, then pip, then env — guarantees deterministic
    "first missing" reporting).  Every key in _REQUIRES_CHECKER is checked;
    the module-level assertion guarantees _REQUIRES_CHECKER == _BLOCKING_REQUIRES_KEYS,
    so no blocking key can be silently skipped.
    requires-skills is not a blocking dep; call site emits a warning instead.
    """
    for kind, checker in _REQUIRES_CHECKER.items():
        for dep_name in requires_block.get(kind, []):
            if not checker(dep_name):
                return (kind.removeprefix("requires-"), dep_name)
    return None


def _warn_requires_skills(skill_name: str, skill_names: list[str]) -> None:
    """Emit a WARNING for requires-skills entries (read-only; never a skip)."""
    for dep in skill_names:
        print(f"[warning: {skill_name}: requires skill {dep}]")


def _extract_requires_block(skill_name: str, entry: object) -> dict[str, list[str]]:
    """Return the blocking requires-* sub-block (list-valued) for a skill entry.

    Defensive against a malformed catalog so a single bad entry never corrupts
    the install:
    - a non-dict entry yields ``{}`` (no requirements; never raises);
    - the requires-* sub-block is validated against SKILL_REQUIREMENTS_SCHEMA and
      any violation is surfaced as a ``[warning: ...]`` (never silently dropped),
      so a typo'd scalar like ``"requires-cmd": "git"`` cannot quietly disable the
      gate. This is where the schema earns its keep at install time.

    Only well-formed list-of-strings blocking keys are returned for enforcement.
    """
    if not isinstance(entry, dict):
        return {}
    sub_block = {k: entry[k] for k in SKILL_REQUIREMENTS_KEYS if k in entry}
    if sub_block:
        valid, errors = validate_artifact(sub_block, SKILL_REQUIREMENTS_SCHEMA)
        if not valid:
            print(
                f"[warning: {skill_name}: malformed requires-* in skill-rules.json: "
                f"{'; '.join(errors)}]"
            )
    return {
        k: v
        for k, v in sub_block.items()
        if k in _BLOCKING_REQUIRES_KEYS
        and isinstance(v, list)
        and all(isinstance(item, str) for item in v)
    }


def _prune_catalog_entries(catalog_path: Path, skill_names: list[str]) -> None:
    """Remove *skill_names* from the INSTALLED skill-rules.json.

    Keeps the installed catalog consistent with the on-disk skill set: a skill
    skipped for a missing host dependency must not remain advertised in
    skill-rules.json (a listed-but-absent skill would dangle when its triggers
    fire). Preserves the ``_map_managed`` sentinel and JSON formatting written by
    the managed-file copier. No-op on read/parse error or if nothing matched.
    """
    if not skill_names or not catalog_path.exists():
        return
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        return
    changed = False
    for name in skill_names:
        if name in skills:
            del skills[name]
            changed = True
    if changed:
        catalog_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _get_version() -> str:
    """Get current mapify-cli version for metadata injection."""
    try:
        from mapify_cli import __version__

        return __version__
    except ImportError:
        return "unknown"


def get_templates_dir() -> Path:
    """Get the path to bundled templates directory."""
    import importlib.resources

    try:
        # Python 3.11+ with importlib.resources.files
        if hasattr(importlib.resources, "files"):
            return Path(str(importlib.resources.files("mapify_cli") / "templates"))
    except Exception:  # noqa: BLE001, S110
        pass

    # Fallback to module directory
    module_dir = Path(__file__).parent.parent
    templates_dir = module_dir / "templates"
    if templates_dir.exists():
        return templates_dir

    # Development mode - check parent directories
    for parent in [module_dir.parent, module_dir.parent.parent]:
        templates_dir = parent / "templates"
        if templates_dir.exists():
            return templates_dir

    raise RuntimeError("Templates directory not found. Please reinstall mapify-cli.")


def create_agent_files(
    project_path: Path,
    mcp_servers: list[str],
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP agent files in .claude/agents/."""
    agents_dir = project_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    agents_template_dir = templates_dir / "agents"

    if agents_template_dir.exists():
        # Files to exclude from agent directory (documentation, not agents)
        exclude_files = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}
        count = 0
        version = _get_version()

        for agent_template in agents_template_dir.glob("*.md"):
            # Skip documentation files - they're not agents
            if agent_template.name in exclude_files:
                continue
            dest_file = agents_dir / agent_template.name
            result = copy_managed_file(agent_template, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1
        return count
    else:
        # Fallback: generate simplified versions if templates not found
        # NOTE: orchestrator removed (moved to slash commands in production architecture)
        agents = {
            "task-decomposer": create_task_decomposer_content(mcp_servers),
            "actor": create_actor_content(mcp_servers),
            "monitor": create_monitor_content(mcp_servers),
            "predictor": create_predictor_content(mcp_servers),
            "evaluator": create_evaluator_content(mcp_servers),
            "reflector": create_reflector_content(mcp_servers),
            "documentation-reviewer": create_documentation_reviewer_content(
                mcp_servers
            ),
        }

        for name, content in agents.items():
            agent_file = agents_dir / f"{name}.md"
            agent_file.write_text(content)
        return len(agents)


def create_reference_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP reference files in .claude/references/

    Returns:
        Number of reference files installed
    """
    references_dir = project_path / ".claude" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    references_template_dir = templates_dir / "references"

    count = 0
    if references_template_dir.exists():
        version = _get_version()
        for ref_file in references_template_dir.glob("*.md"):
            dest_file = references_dir / ref_file.name
            # References are fully MAP-owned — overwrite on update (no fence).
            result = copy_managed_file(ref_file, dest_file, version, fenced=False)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count


def create_command_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create .claude/commands/ directory structure.

    MAP slash commands are now delivered as skills (.claude/skills/).
    This function creates only the commands directory with a README
    pointing users at the skill-backed surfaces.
    """
    del drift_report  # accepted for caller API compatibility; not used here
    create_commands_dir(project_path)
    return 0


def _load_template_skill_catalog(
    skills_template_dir: Path,
) -> dict[str, dict[str, object]]:
    """Parse the template skill-rules.json and return the skills dict.

    Returns an empty dict on any error (missing file, invalid JSON) so the
    caller falls through to unconditional install — defensive, never gate-blocks
    due to a corrupt catalog.
    """
    catalog_path = skills_template_dir / "skill-rules.json"
    try:
        raw = catalog_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        skills = data.get("skills", {})
        if isinstance(skills, dict):
            return skills  # type: ignore[return-value]
    except Exception:  # noqa: BLE001, S110# FileNotFoundError, JSONDecodeError, etc.
        pass
    return {}


def create_skill_files(project_path: Path) -> int:
    """Create MAP skills in .claude/skills/

    Skips any skill whose blocking runtime dependencies (requires-cmd,
    requires-pip, requires-env) are not satisfied on the current host.
    Prints ``[skipped: <skill>: missing <kind> <name>]`` to stdout for each
    skipped skill.  requires-skills is WARNING-only and never causes a skip.

    Returns:
        Number of skills actually installed (skipped skills not counted).
    """
    skills_dir = project_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    skills_template_dir = templates_dir / "skills"

    count = 0

    if skills_template_dir.exists():
        version = _get_version()

        # Parse catalog ONCE, defensively (missing/invalid -> empty dict -> no gate).
        skill_catalog = _load_template_skill_catalog(skills_template_dir)

        # Top-level skill catalog files (README.md, skill-rules.json).
        for top_name in ("README.md", "skill-rules.json"):
            top_src = skills_template_dir / top_name
            if top_src.exists():
                _install_managed_file(top_src, skills_dir / top_name, version)

        # Copy each skill directory, fence-aware per file (watched category).
        skipped: list[str] = []
        for skill_template in sorted(skills_template_dir.iterdir()):
            if not (skill_template.is_dir() and skill_template.name != "__pycache__"):
                continue

            skill_name = skill_template.name
            entry = skill_catalog.get(skill_name, {})
            requires_block = _extract_requires_block(skill_name, entry)

            # Emit WARNING for requires-skills (read-only; never a skip).
            req_skills = (
                entry.get("requires-skills") if isinstance(entry, dict) else None
            )
            if isinstance(req_skills, list) and req_skills:
                _warn_requires_skills(skill_name, req_skills)

            # Check blocking deps; skip on first missing.
            missing = _skill_missing_dependency(requires_block)
            if missing is not None:
                kind, dep_name = missing
                print(f"[skipped: {skill_name}: missing {kind} {dep_name}]")
                skipped.append(skill_name)
                continue

            _install_managed_tree(skill_template, skills_dir / skill_name, version)
            count += 1

        # Keep the installed catalog consistent with the on-disk skill set:
        # a skill skipped above must not stay advertised in skill-rules.json.
        _prune_catalog_entries(skills_dir / "skill-rules.json", skipped)

    return count


def _install_managed_file(src: Path, dest: Path, version: str) -> None:
    """Install a single watched file fence-aware, preserving executable bits."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_managed_file(src, dest, version)
    if src.suffix in (".sh", ".py") and dest.exists():
        dest.chmod(dest.stat().st_mode | 0o755)


def _install_managed_tree(src_dir: Path, dest_dir: Path, version: str) -> None:
    """Recursively install a directory of watched files via copy_managed_file."""
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        if (
            src.name in _IGNORED_TEMPLATE_NAMES
            or src.suffix in _IGNORED_TEMPLATE_SUFFIXES
        ):
            continue
        rel = src.relative_to(src_dir)
        _install_managed_file(src, dest_dir / rel, version)


def _copy_map_path(src: Path, dest: Path, version: str) -> int:
    """Install a map-tools path into .map/ fully-managed (fenced=False), +x scripts.

    MAP runtime scripts/static-analysis are MAP-owned: overwrite on update with a
    .bak.<ts> on drift (Phase B behavior), never fence them.  Executable bits are
    restored after the metadata-injecting write.
    """
    count = 0
    if src.is_dir():
        for child in sorted(src.rglob("*")):
            if not child.is_file():
                continue
            if (
                child.name in _IGNORED_TEMPLATE_NAMES
                or child.suffix in _IGNORED_TEMPLATE_SUFFIXES
            ):
                continue
            rel = child.relative_to(src)
            count += _install_map_file(child, dest / rel, version)
    else:
        count += _install_map_file(src, dest, version)
    return count


def _install_map_file(src: Path, dest: Path, version: str) -> int:
    """Install one MAP-owned file (overwrite mode) and mark scripts executable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_managed_file(src, dest, version, fenced=False)
    if src.suffix in (".sh", ".py") and dest.exists():
        dest.chmod(dest.stat().st_mode | 0o755)
        return 1
    return 0


def create_map_tools(project_path: Path) -> int:
    """Create .map/ directory with shipped MAP runtime and planning assets."""
    map_dir = project_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = get_templates_dir()
    map_template_dir = templates_dir / "map"

    count = 0
    if map_template_dir.exists():
        version = _get_version()
        for item in map_template_dir.iterdir():
            count += _copy_map_path(item, map_dir / item.name, version)

    return count


_SOFA_GITIGNORE_MARKER = "# map:sofa"
_SOFA_GITIGNORE_BLOCK = (
    "# map:sofa — SOFA credential dir (opt-in); never commit. See docs/USAGE.md\n"
    ".sofa/\n"
)

_AGENT_MEMORY_LOCAL_GITIGNORE_MARKER = "# map:agent-memory-local"
_AGENT_MEMORY_LOCAL_GITIGNORE_BLOCK = (
    "# map:agent-memory-local — user-local agent memory (opt-in); never commit.\n"
    ".claude/agent-memory-local/\n"
)

_SETTINGS_LOCAL_GITIGNORE_MARKER = "# map:settings-local"
_SETTINGS_LOCAL_GITIGNORE_BLOCK = (
    "# map:settings-local — per-user Claude Code approvals / autonomy posture; "
    "never commit\n"
    ".claude/settings.local.json\n"
)


_UPDATE_RUNTIME_GITIGNORE_MARKER = (
    "# map:update-runtime — local automatic-update state; never commit."
)
_UPDATE_RUNTIME_GITIGNORE_PATHS = (
    ".map/update-state.json",
    ".map/update.lock",
    ".map/provider-refresh.lock",
    ".map/installer.lock",
)
_WINDOWS_GITIGNORE_MUTEX_TIMEOUT_MS = 30_000


class UpdateRuntimeGitignoreSecurityError(RuntimeError):
    """Raised when the project .gitignore is unsafe to read or replace."""


def _unsafe_project_gitignore(gitignore: Path, reason: str) -> NoReturn:
    raise UpdateRuntimeGitignoreSecurityError(
        f"unsafe project .gitignore at {gitignore}: {reason}"
    )


def _uses_windows_gitignore_mutex() -> bool:
    """Return whether this platform uses a no-file named mutex."""
    return os.name == "nt"


def _validated_project_root_stat(project_root: Path) -> os.stat_result:
    """Return the direct directory identity used to key and guard the lock."""
    try:
        current = os.stat(project_root, follow_symlinks=False)
    except OSError as exc:
        _unsafe_gitignore_lock(
            project_root,
            f"could not validate the project root ({exc})",
        )
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        _unsafe_gitignore_lock(
            project_root, "the project root must be a direct directory"
        )
    return current


def _validate_project_root_unchanged(
    project_root: Path,
    original: os.stat_result,
) -> None:
    current = _validated_project_root_stat(project_root)
    if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
        _unsafe_gitignore_lock(project_root, "the project root changed")


def _replace_supports_directory_fds() -> bool:
    """Return whether ``os.replace`` accepts pinned directory descriptors."""
    try:
        parameters = inspect.signature(os.replace).parameters
    except (TypeError, ValueError):
        return False
    return "src_dir_fd" in parameters and "dst_dir_fd" in parameters


_CAN_USE_PROJECT_DIRECTORY_FD = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and _replace_supports_directory_fds()
)


def _supports_pinned_project_root() -> bool:
    return _CAN_USE_PROJECT_DIRECTORY_FD


def _gitignore_lock_path_for_stat(
    project_root: Path,
    project_stat: os.stat_result,
) -> Path:
    """Return the shared lock path used by every MAP .gitignore writer.

    The lock is persistent by design: unlinking it after release would create
    an inode race between a waiter and a new caller. POSIX uses a fixed system
    temp root so differing TMPDIR environments cannot split the lock identity;
    Windows uses a named mutex and never calls this file-path helper.
    """
    del project_root
    identity = f"{project_stat.st_dev}:{project_stat.st_ino}".encode("ascii")
    digest = hashlib.sha256(identity).hexdigest()
    # A fixed POSIX root makes independent processes agree even when TMPDIR,
    # TMP, or TEMP differ. The lock file itself is private and identity-checked.
    return Path("/tmp") / f"mapify-gitignore-{digest}.lock"


def _windows_gitignore_mutex_name(project_stat: os.stat_result) -> str:
    identity = f"{project_stat.st_dev}:{project_stat.st_ino}".encode("ascii")
    digest = hashlib.sha256(identity).hexdigest()
    return f"Global\\MapifyGitignore-{digest}"


@contextlib.contextmanager
def _windows_project_gitignore_mutex(
    project_stat: os.stat_result,
) -> Iterator[None]:
    """Acquire a process-shared Windows mutex without a filesystem artifact."""
    ctypes: Any = importlib.import_module("ctypes")
    wintypes: Any = importlib.import_module("ctypes.wintypes")
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = [wintypes.HANDLE]
    release_mutex.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_mutex(None, False, _windows_gitignore_mutex_name(project_stat))
    if not handle:
        create_error = ctypes.get_last_error()
        _unsafe_gitignore_lock(
            Path("<windows-mutex>"),
            "could not create or open the required cross-session mutex "
            f"(WinError {create_error}); run MAP under one Windows account with "
            "Global object access; refusing a session-local fallback",
        )
    wait_result = wait_for_single_object(handle, _WINDOWS_GITIGNORE_MUTEX_TIMEOUT_MS)
    if wait_result not in {0x00000000, 0x00000080}:
        wait_error = ctypes.get_last_error() if wait_result == 0xFFFFFFFF else None
        close_error = None
        if not close_handle(handle):
            close_error = ctypes.get_last_error()
        if wait_result == 0x00000102:
            reason = "the MAP .gitignore mutex timed out"
        elif wait_result == 0xFFFFFFFF:
            reason = f"WaitForSingleObject failed (WinError {wait_error})"
        else:
            reason = f"WaitForSingleObject returned unexpected status {wait_result:#x}"
        if close_error is not None:
            reason += f"; CloseHandle also failed (WinError {close_error})"
        _unsafe_gitignore_lock(Path("<windows-mutex>"), reason)
    try:
        yield
    finally:
        release_error = None
        if not release_mutex(handle):
            release_error = ctypes.get_last_error()
        close_error = None
        if not close_handle(handle):
            close_error = ctypes.get_last_error()
        if release_error is not None or close_error is not None:
            failures: list[str] = []
            if release_error is not None:
                failures.append(f"ReleaseMutex failed (WinError {release_error})")
            if close_error is not None:
                failures.append(f"CloseHandle failed (WinError {close_error})")
            _unsafe_gitignore_lock(Path("<windows-mutex>"), "; ".join(failures))


@contextlib.contextmanager
def _windows_pinned_project_root(
    project_root: Path,
    project_original: os.stat_result,
) -> Iterator[None]:
    """Prevent replacement of a Windows project directory during mutation."""
    ctypes: Any = importlib.import_module("ctypes")
    wintypes: Any = importlib.import_module("ctypes.wintypes")
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    # FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, OPEN_EXISTING,
    # FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT. Deliberately
    # omitting FILE_SHARE_DELETE prevents a rename/replacement while held.
    handle = create_file(
        str(project_root),
        0x00000080,
        0x00000003,
        None,
        3,
        0x02200000,
        None,
    )
    invalid_handle = wintypes.HANDLE(-1).value
    if not handle or handle == invalid_handle:
        _unsafe_gitignore_lock(
            project_root,
            f"could not pin the Windows project root ({ctypes.get_last_error()})",
        )
    try:
        _validate_project_root_unchanged(project_root, project_original)
        yield
    finally:
        if not close_handle(handle):
            close_error = ctypes.get_last_error()
            _unsafe_gitignore_lock(
                project_root,
                f"CloseHandle failed for the project root (WinError {close_error})",
            )


@contextlib.contextmanager
def _pinned_project_root(
    project_root: Path,
    project_original: os.stat_result,
) -> Iterator[int | None]:
    """Pin the project identity used by every relative .gitignore operation."""
    if os.name == "nt":
        with _windows_pinned_project_root(project_root, project_original):
            yield None
        return
    if not _supports_pinned_project_root():
        _unsafe_gitignore_lock(
            project_root,
            "this platform cannot pin project-relative file operations",
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(project_root, flags)
    except OSError as exc:
        _unsafe_gitignore_lock(project_root, f"could not pin the project root ({exc})")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (
            project_original.st_dev,
            project_original.st_ino,
        ):
            _unsafe_gitignore_lock(
                project_root, "the project root changed while opening"
            )
        _validate_project_root_unchanged(project_root, project_original)
        yield descriptor
    finally:
        os.close(descriptor)


def _gitignore_lock_path(project_root: Path) -> Path:
    """Resolve the shared lock from stable filesystem identity, not spelling."""
    return _gitignore_lock_path_for_stat(
        project_root,
        _validated_project_root_stat(project_root),
    )


def _unsafe_gitignore_lock(lock_path: Path, reason: str) -> NoReturn:
    raise UpdateRuntimeGitignoreSecurityError(
        f"unsafe MAP .gitignore lock at {lock_path}: {reason}"
    )


def _descriptor_mode_matches(descriptor: int, expected: int) -> bool:
    """Compare only permission bits the current platform can represent."""
    actual = stat.S_IMODE(os.fstat(descriptor).st_mode)
    if os.name == "nt":
        # Windows chmod/open modes expose only the read-only flag.  Continue
        # validating through the descriptor without requiring POSIX-only bits.
        return bool(actual & stat.S_IWRITE) == bool(expected & stat.S_IWRITE)
    return actual == expected


def _validate_lock_stat(lock_path: Path, current: os.stat_result) -> None:
    if stat.S_ISLNK(current.st_mode):
        _unsafe_gitignore_lock(lock_path, "symbolic links are not allowed")
    if not stat.S_ISREG(current.st_mode):
        _unsafe_gitignore_lock(lock_path, "the path must be a regular file")
    if current.st_nlink != 1:
        _unsafe_gitignore_lock(lock_path, "hard-linked files are not allowed")
    if hasattr(os, "getuid") and current.st_uid != os.getuid():
        _unsafe_gitignore_lock(lock_path, "the file must be owned by the current user")


def _required_lock_stat(lock_path: Path) -> os.stat_result:
    try:
        current = os.lstat(lock_path)
    except FileNotFoundError:
        _unsafe_gitignore_lock(lock_path, "the path disappeared")
    _validate_lock_stat(lock_path, current)
    return current


def _open_gitignore_lock(lock_path: Path) -> int:
    """Open a private persistent lock without following or accepting links."""
    try:
        initial = os.lstat(lock_path)
    except FileNotFoundError:
        initial = None
    if initial is not None:
        _validate_lock_stat(lock_path, initial)

    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        _unsafe_gitignore_lock(lock_path, f"could not open it safely ({exc})")
    try:
        opened = os.fstat(descriptor)
        _validate_lock_stat(lock_path, opened)
        current = _required_lock_stat(lock_path)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            _unsafe_gitignore_lock(lock_path, "the path changed while being opened")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        elif not _descriptor_mode_matches(descriptor, 0o600):
            _unsafe_gitignore_lock(
                lock_path,
                "cannot enforce private mode without descriptor chmod support",
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                } and getattr(exc, "winerror", None) not in {33, 36}:
                    raise
                time.sleep(0.05)
        return
    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextlib.contextmanager
def _project_gitignore_lock(
    project_root: Path,
) -> Iterator[tuple[int | None, os.stat_result]]:
    """Serialize a complete MAP-owned root .gitignore transaction."""
    project_original = _validated_project_root_stat(project_root)
    with _pinned_project_root(project_root, project_original) as directory_fd:
        if _uses_windows_gitignore_mutex():
            with _windows_project_gitignore_mutex(project_original):
                _validate_project_root_unchanged(project_root, project_original)
                yield directory_fd, project_original
                _validate_project_root_unchanged(project_root, project_original)
            return
        lock_path = _gitignore_lock_path_for_stat(project_root, project_original)
        descriptor = _open_gitignore_lock(lock_path)
        locked = False
        try:
            _lock_descriptor(descriptor)
            locked = True
            opened = os.fstat(descriptor)
            _validate_lock_stat(lock_path, opened)
            current = _required_lock_stat(lock_path)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                _unsafe_gitignore_lock(lock_path, "the path changed while waiting")
            _validate_project_root_unchanged(project_root, project_original)
            yield directory_fd, project_original
            _validate_project_root_unchanged(project_root, project_original)
        finally:
            if locked:
                _unlock_descriptor(descriptor)
            os.close(descriptor)


def _validated_gitignore_stat(
    gitignore: Path,
    directory_fd: int | None,
) -> os.stat_result | None:
    """Return a safe direct-child .gitignore stat, or None when absent."""
    try:
        if directory_fd is None:
            current = os.lstat(gitignore)
        else:
            current = os.stat(
                gitignore.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(current.st_mode):
        _unsafe_project_gitignore(gitignore, "symbolic links are not allowed")
    if not stat.S_ISREG(current.st_mode):
        _unsafe_project_gitignore(gitignore, "the path must be a regular file")
    if current.st_nlink != 1:
        _unsafe_project_gitignore(gitignore, "hard-linked files are not allowed")
    return current


def _read_safe_gitignore(
    gitignore: Path,
    directory_fd: int | None,
) -> tuple[bytes, os.stat_result | None]:
    """Read .gitignore without following links and retain its identity."""
    initial = _validated_gitignore_stat(gitignore, directory_fd)
    if initial is None:
        return b"", None

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        if directory_fd is None:
            descriptor = os.open(gitignore, flags)
        else:
            descriptor = os.open(gitignore.name, flags, dir_fd=directory_fd)
    except OSError as exc:
        _unsafe_project_gitignore(gitignore, f"could not open it safely ({exc})")

    try:
        opened = os.fstat(descriptor)
        current = _validated_gitignore_stat(gitignore, directory_fd)
        if current is None or (
            opened.st_dev,
            opened.st_ino,
        ) != (
            current.st_dev,
            current.st_ino,
        ):
            _unsafe_project_gitignore(gitignore, "the path changed while being read")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            _unsafe_project_gitignore(gitignore, "the opened file is not private")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read(), opened
    finally:
        os.close(descriptor)


def _validate_gitignore_unchanged(
    gitignore: Path,
    original: os.stat_result | None,
    directory_fd: int | None,
) -> None:
    """Reject a target created or swapped after the initial safe read."""
    current = _validated_gitignore_stat(gitignore, directory_fd)
    if original is None:
        if current is not None:
            _unsafe_project_gitignore(gitignore, "the path appeared during the update")
        return
    if current is None or (current.st_dev, current.st_ino) != (
        original.st_dev,
        original.st_ino,
    ):
        _unsafe_project_gitignore(gitignore, "the path changed during the update")


def _create_gitignore_temporary(
    gitignore: Path,
    directory_fd: int | None,
) -> tuple[int, str | Path]:
    if directory_fd is None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=gitignore.parent,
            prefix=".gitignore.",
            suffix=".tmp",
        )
        return descriptor, Path(temporary_name)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(32):
        temporary_name = f".gitignore.{secrets.token_hex(12)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            continue
        return descriptor, temporary_name
    raise FileExistsError("could not allocate a private .gitignore temporary file")


def _atomic_replace_gitignore(
    gitignore: Path,
    content: bytes,
    original: os.stat_result | None,
    directory_fd: int | None,
    project_root: Path,
    project_original: os.stat_result,
) -> None:
    """Durably prepare a replacement, then atomically install it."""
    _validate_project_root_unchanged(project_root, project_original)
    descriptor, temporary = _create_gitignore_temporary(gitignore, directory_fd)
    try:
        _validate_project_root_unchanged(project_root, project_original)
        mode = stat.S_IMODE(original.st_mode) if original is not None else 0o644
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        else:
            if original is not None and not _descriptor_mode_matches(descriptor, mode):
                _unsafe_project_gitignore(
                    gitignore,
                    "cannot preserve its mode without descriptor chmod support",
                )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _validate_project_root_unchanged(project_root, project_original)
        _validate_gitignore_unchanged(gitignore, original, directory_fd)
        if directory_fd is None:
            os.replace(temporary, gitignore)
        else:
            os.replace(
                temporary,
                gitignore.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if directory_fd is None:
                Path(temporary).unlink()
            else:
                os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _has_effective_gitignore_path(lines: list[bytes], required_path: str) -> bool:
    """Return whether an exact path remains authoritative after later rules.

    Git evaluates ignore rules in order.  MAP deliberately uses a conservative
    rule here instead of attempting to reproduce git's wildmatch semantics: an
    exact canonical path is effective only when no later unescaped negation
    rule follows it.  Leading-space and otherwise non-canonical variants do not
    count as the required path.
    """
    required = required_path.encode()
    last_exact = -1
    for index, line in enumerate(lines):
        if line == required:
            last_exact = index
    return last_exact >= 0 and not any(
        line.startswith(b"!") for line in lines[last_exact + 1 :]
    )


def _has_gitignore_marker(lines: list[bytes], marker: str) -> bool:
    encoded = marker.encode()
    return any(line == encoded or line.startswith(encoded + b" ") for line in lines)


def _merge_project_gitignore_locked(
    project_root: Path,
    directory_fd: int | None,
    project_original: os.stat_result,
    *,
    include_runtime: bool = False,
    include_sofa: bool = False,
    include_agent_memory_local: bool = False,
    include_settings_local: bool = False,
) -> int:
    """Append selected MAP-owned blocks while the shared lock is held."""
    gitignore = project_root / ".gitignore"
    existing, original = _read_safe_gitignore(gitignore, directory_fd)
    _validate_project_root_unchanged(project_root, project_original)
    existing_lines = existing.splitlines()

    additions: list[bytes] = []
    if include_runtime:
        missing_runtime_paths = [
            path
            for path in _UPDATE_RUNTIME_GITIGNORE_PATHS
            if not _has_effective_gitignore_path(existing_lines, path)
        ]
        if missing_runtime_paths:
            runtime_lines: list[bytes] = []
            marker = _UPDATE_RUNTIME_GITIGNORE_MARKER.encode()
            if not _has_gitignore_marker(
                existing_lines, _UPDATE_RUNTIME_GITIGNORE_MARKER
            ):
                runtime_lines.append(marker)
            runtime_lines.extend(path.encode() for path in missing_runtime_paths)
            additions.append(b"\n".join(runtime_lines) + b"\n")

    def append_optional_block(
        *, marker: str, required_line: str, block: str, enabled: bool
    ) -> None:
        if not enabled or _has_effective_gitignore_path(existing_lines, required_line):
            return
        if _has_gitignore_marker(existing_lines, marker):
            additions.append(f"{required_line}\n".encode())
        else:
            additions.append(block.encode())

    # The exact privacy path is the completion authority. A marker alone is
    # descriptive metadata and must never authorize feature enablement.
    append_optional_block(
        marker=_SOFA_GITIGNORE_MARKER,
        required_line=".sofa/",
        block=_SOFA_GITIGNORE_BLOCK,
        enabled=include_sofa,
    )
    append_optional_block(
        marker=_AGENT_MEMORY_LOCAL_GITIGNORE_MARKER,
        required_line=".claude/agent-memory-local/",
        block=_AGENT_MEMORY_LOCAL_GITIGNORE_BLOCK,
        enabled=include_agent_memory_local,
    )
    append_optional_block(
        marker=_SETTINGS_LOCAL_GITIGNORE_MARKER,
        required_line=".claude/settings.local.json",
        block=_SETTINGS_LOCAL_GITIGNORE_BLOCK,
        enabled=include_settings_local,
    )

    if not additions:
        _validate_gitignore_unchanged(gitignore, original, directory_fd)
        return 0
    separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
    replacement = existing + separator + b"".join(additions)
    _atomic_replace_gitignore(
        gitignore,
        replacement,
        original,
        directory_fd,
        project_root,
        project_original,
    )
    return 1


def _merge_project_gitignore(
    project_path: Path,
    *,
    include_runtime: bool = False,
    include_sofa: bool = False,
    include_agent_memory_local: bool = False,
    include_settings_local: bool = False,
) -> int:
    """Safely, atomically, and serially append MAP-owned ignore blocks."""
    project_root = project_path.resolve(strict=True)
    if not project_root.is_dir():
        raise NotADirectoryError(f"MAP project root is not a directory: {project_root}")
    with _project_gitignore_lock(project_root) as (directory_fd, project_original):
        return _merge_project_gitignore_locked(
            project_root,
            directory_fd,
            project_original,
            include_runtime=include_runtime,
            include_sofa=include_sofa,
            include_agent_memory_local=include_agent_memory_local,
            include_settings_local=include_settings_local,
        )


def merge_update_runtime_gitignore(
    project_path: Path,
    *,
    sofa: bool = False,
    agent_memory_local: bool = False,
    settings_local: bool = False,
) -> int:
    """Atomically establish runtime and requested privacy ignore entries."""
    return _merge_project_gitignore(
        project_path,
        include_runtime=True,
        include_sofa=sofa,
        include_agent_memory_local=agent_memory_local,
        include_settings_local=settings_local,
    )


def merge_sofa_gitignore(project_path: Path) -> int:
    """Idempotently add .sofa/ entry to the repo-root .gitignore.

    Operates on ``project_path / ".gitignore"`` (NOT ``.claude/.gitignore``).
    Returns 1 when the file was created or modified, 0 when already up-to-date
    (no-op / idempotent).
    """
    return _merge_project_gitignore(project_path, include_sofa=True)


def merge_agent_memory_gitignore(project_path: Path) -> int:
    """Idempotently add .claude/agent-memory-local/ to the repo-root .gitignore.

    Only called when ``--agent-memory local`` is used. The project-scoped level
    (``--agent-memory project``) writes to ``.claude/agent-memory/`` which IS
    intended to be committed, so no gitignore entry is needed for it.

    Returns 1 when the file was created or modified, 0 when already up-to-date.
    """
    return _merge_project_gitignore(project_path, include_agent_memory_local=True)


def merge_settings_local_gitignore(project_path: Path) -> int:
    """Safely ignore the user-local Claude settings file for autonomy mode."""
    return _merge_project_gitignore(project_path, include_settings_local=True)


def apply_reflector_memory_field(project_path: Path, level: str) -> int:
    """Add or update the ``memory:`` frontmatter field in the installed reflector.md.

    Called post-install when ``--agent-memory`` is ``"local"`` or ``"project"``.
    Idempotent: if the field already exists with the correct value it is left
    unchanged; if it exists with a different value it is replaced.

    Args:
        project_path: root of the target project (installed ``.claude/`` lives here).
        level: ``"local"`` or ``"project"`` (caller is responsible for validation;
               ``"off"`` callers must not invoke this function).

    Returns:
        1 if the file was modified, 0 if already up-to-date or not found.
    """
    import re

    reflector_path = project_path / ".claude" / "agents" / "reflector.md"
    if not reflector_path.exists():
        return 0

    text = reflector_path.read_text(encoding="utf-8")

    # Determine the correct memory field value based on level.
    # "local"   → memory: user_local   (maps to .claude/agent-memory-local/)
    # "project" → memory: project      (maps to .claude/agent-memory/)
    memory_value = "user_local" if level == "local" else "project"
    new_field_line = f"memory: {memory_value}"

    # If a `memory:` line already exists in the frontmatter, replace it.
    existing_memory_re = re.compile(r"(?m)^memory\s*:.*$")
    if existing_memory_re.search(text):
        updated = existing_memory_re.sub(new_field_line, text, count=1)
        if updated == text:
            return 0  # already up-to-date
        reflector_path.write_text(updated, encoding="utf-8")
        return 1

    # Inject the `memory:` line into the YAML frontmatter, just before the
    # closing `---` delimiter. This preserves the existing frontmatter structure.
    # Match the opening `---\n ... \n---` block.
    frontmatter_re = re.compile(r"^(---\n.*?\n)(---)", re.DOTALL)
    m = frontmatter_re.match(text)
    if not m:
        # No frontmatter — prepend a minimal one.
        updated = f"---\n{new_field_line}\n---\n{text}"
    else:
        # Insert before the closing `---`.
        updated = text[: m.start(2)] + new_field_line + "\n" + text[m.start(2) :]

    reflector_path.write_text(updated, encoding="utf-8")
    return 1


def create_commands_dir(project_path: Path) -> None:
    """Create commands directory with README pointing at skill-backed surfaces."""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    readme = commands_dir / "README.md"
    readme.write_text("""# Claude Code Commands

This directory exists for **user-custom** slash commands. All MAP slash
commands now ship as Skills (`.claude/skills/map-*/SKILL.md`) which give
the same `/map-*` interface but with progressive disclosure (skill body
loads on demand instead of always living in context).

## MAP Slash Commands (skill-backed)

All of these are implemented via `.claude/skills/<name>/SKILL.md`:

- `/map-plan` - Decompose work without implementing it yet
- `/map-efficient` - Implement features with optimized workflow (recommended)
- `/map-fast` - Quick implementation with minimal validation
- `/map-task` - Execute a single subtask from an existing plan
- `/map-tdd` - Run a test-first workflow for one task or plan
- `/map-debug` - Debug issues using MAP analysis
- `/map-review` - Run a structured review workflow
- `/map-check` - Run workflow quality gates and verification
- `/map-release` - Execute MAP Framework package release workflow
- `/map-resume` - Resume an interrupted workflow from `.map/`
- `/map-learn` - Extract lessons from completed workflows

## Creating Custom Commands

Create a new `.md` file in this directory with the following format:

```markdown
---
description: Brief description of your command
---

Your command prompt here
```

The filename becomes the command name (without the `.md` extension).
Per the Claude Code docs, a skill at `.claude/skills/<name>/SKILL.md`
takes precedence over a command at `.claude/commands/<name>.md` with
the same name.
""")


def create_hook_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP hook files in .claude/hooks/

    Returns:
        Number of hook files installed
    """
    hooks_dir = project_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    hooks_template_dir = templates_dir / "hooks"

    count = 0
    if hooks_template_dir.exists():
        version = _get_version()
        for hook_file in hooks_template_dir.iterdir():
            if hook_file.is_file():
                dest_file = hooks_dir / hook_file.name
                result = copy_managed_file(hook_file, dest_file, version)
                if drift_report is not None:
                    drift_report.results.append(result)
                # Preserve executable permissions
                if hook_file.suffix in (".sh", ".py"):
                    dest_file.chmod(0o755)
                count += 1

    return count


def create_config_files(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create MAP config files in .claude/

    Copies configuration files:
    - settings.json
    - ralph-loop-config.json
    - workflow-rules.json

    Returns:
        Number of config files installed
    """
    claude_dir = project_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()

    config_files = [
        "settings.json",
        "ralph-loop-config.json",
        "workflow-rules.json",
    ]

    count = 0
    version = _get_version()

    for config_file in config_files:
        template_file = templates_dir / config_file
        if template_file.exists():
            dest_file = claude_dir / config_file
            result = copy_managed_file(template_file, dest_file, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count


@dataclass
class StatuslineResult:
    """Outcome of :func:`ensure_map_statusline`.

    ``wired`` is True only when a fresh ``statusLine`` entry was written.
    ``reason`` is ``"wired"`` on success, or ``"existing:<scope>"`` when an
    existing status line in the ``user`` / ``project`` / ``local`` scope was
    detected and left untouched.
    """

    wired: bool
    reason: str
    settings_path: Path | None = None


def _read_json_object(path: Path) -> dict | None:
    """Return a parsed JSON object, or None if missing/unreadable/not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _has_status_line(path: Path) -> bool:
    """True when *path* is a settings JSON that already defines a ``statusLine``."""
    obj = _read_json_object(path)
    return bool(obj and obj.get("statusLine"))


def ensure_map_statusline(
    project_path: Path,
    *,
    home: Path | None = None,
) -> StatuslineResult:
    """Non-destructively wire the MAP context status line.

    Claude Code's ``statusLine`` setting fully owns the status row, so MAP must
    never overwrite a status line the user already configured. This detects an
    existing ``statusLine`` in every scope MAP must respect — highest precedence
    first —

      * ``<project>/.claude/settings.local.json`` (project-local overrides)
      * ``<project>/.claude/settings.json``       (project, MAP-managed)
      * ``~/.claude/settings.json``               (user global)

    and, only when NONE is present, merges a ``statusLine`` entry pointing at the
    installed ``map-statusline.py`` hook into ``.claude/settings.local.json``.

    ``settings.local.json`` is deliberately chosen over the MAP-managed
    ``settings.json``: it is user-owned and never re-rendered by the managed
    copier, so the injection introduces no template drift and creates no ``.bak``
    churn on upgrade. The merge preserves any pre-existing keys in that file, and
    the operation is idempotent — a second ``mapify init`` detects MAP's own
    entry and skips.

    Args:
        project_path: Root of the target project.
        home: Override for the user home directory (test seam). Defaults to
            ``Path.home()``.

    Returns:
        StatuslineResult describing whether a status line was wired or skipped.
    """
    home_dir = home if home is not None else Path.home()
    claude_dir = project_path / ".claude"
    scope_paths = {
        "local": claude_dir / "settings.local.json",
        "project": claude_dir / "settings.json",
        "user": home_dir / ".claude" / "settings.json",
    }

    # Highest-precedence scope first so the reported scope is the one that would
    # actually win at runtime.
    for scope in ("local", "project", "user"):
        if _has_status_line(scope_paths[scope]):
            return StatuslineResult(wired=False, reason=f"existing:{scope}")

    local_settings = scope_paths["local"]
    hook_path = claude_dir / "hooks" / "map-statusline.py"
    # Absolute, quoted path: settings.local.json is machine-local, and quoting
    # keeps the shell-invoked command correct when the project path has spaces.
    command = f'"{hook_path}"'

    settings = _read_json_object(local_settings) or {}
    settings["statusLine"] = {"type": "command", "command": command}

    # Revalidate the user-local settings privacy boundary immediately before
    # this direct writer runs.  Init's earlier combined preflight cannot protect
    # against a later .gitignore swap, and this function is also a public test /
    # provider seam that can be called independently.
    merge_settings_local_gitignore(project_path)
    claude_dir.mkdir(parents=True, exist_ok=True)
    local_settings.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return StatuslineResult(wired=True, reason="wired", settings_path=local_settings)


def create_rules_dir(
    project_path: Path,
    drift_report: DriftReport | None = None,
) -> int:
    """Create .claude/rules/learned/ directory with README.

    Creates the directory structure for persisting lessons extracted by
    /map-learn. The README is copied from templates and managed; existing
    user rules files are never touched.

    Returns:
        Number of files installed (0 or 1 for README).
    """
    rules_dir = project_path / ".claude" / "rules" / "learned"
    rules_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = get_templates_dir()
    readme_template = templates_dir / "rules" / "learned" / "README.md"

    count = 0
    if readme_template.exists():
        dest = rules_dir / "README.md"
        if not dest.exists():
            version = _get_version()
            result = copy_managed_file(readme_template, dest, version)
            if drift_report is not None:
                drift_report.results.append(result)
            count += 1

    return count
