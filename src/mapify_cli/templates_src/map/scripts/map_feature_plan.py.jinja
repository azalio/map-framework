"""Project an approved multi-repository subtask onto its participating Git checkouts."""

import os
import re
import subprocess
from pathlib import Path
from typing import Any


def _command(value: object, field: str) -> list[str]:
    if (not isinstance(value, list) or not value or not value[0]
            or not all(isinstance(arg, str) and "\x00" not in arg for arg in value)):
        raise ValueError(f"{field} must be a nonempty command argument list")
    return value


def _git(root: Path, *args: str) -> str:
    from map_step_runner import _attribution_git_env

    try:
        proc = subprocess.run(["git", *args], cwd=root, env=_attribution_git_env(),
                              capture_output=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"{root}: git {' '.join(args)} failed: {exc}") from exc
    return os.fsdecode(proc.stdout.removesuffix(b"\n"))


def in_nested_checkout(root: Path, relative: Path) -> bool:
    return any((root / parent / ".git").exists() for parent in relative.parents if parent != Path("."))


def cross_repo_paths(root: Path, declarations: list) -> list[str]:
    canonical = root.resolve()
    external = []
    for name in declarations:
        if not isinstance(name, str) or not name:
            continue
        entry = root / name
        try:
            # Git tracks a symlink as a leaf entry even when its target is in another checkout.
            path = entry.parent.resolve() / entry.name
        except (OSError, RuntimeError, ValueError):
            continue
        if not path.is_relative_to(canonical) or in_nested_checkout(canonical, path.relative_to(canonical)):
            external.append(name)
    return external


def attributed_feature_files(root: Path, branch: str, current: str, base: str, candidates: set[str]) -> dict[str, str]:
    """Recognize clean changes made by other completed subtasks of this coordinator."""
    from map_step_runner import (
        _normalize_mutation_declaration,
        _read_json_file,
        load_blueprint,
    )

    if not candidates:
        return {}
    state = _read_json_file(root / ".map" / branch / "step_state.json") or {}
    results = state.get("subtask_results")
    if not isinstance(results, dict):
        return {}
    blueprint = load_blueprint(branch, project_dir=root) or {}

    def local_names(names: object) -> set[str]:
        found = set()
        for name in names if isinstance(names, list) else ():
            if isinstance(name, str):
                try:
                    found.add(_normalize_mutation_declaration(name, root))
                except ValueError:
                    continue  # A path from another checkout has no claim on this one.
        return found

    claims: dict[str, set[str]] = {}
    for task in blueprint.get("subtasks", []):
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            continue
        sid = task["id"]
        row = results.get(sid)
        if (sid == current or not isinstance(row, dict) or row.get("subtask_id", sid) != sid
                or row.get("status") not in ("valid", "completed", "done")):
            continue
        sha = row.get("commit_sha")
        if not isinstance(sha, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha):
            continue
        for path in candidates & local_names(row.get("files_changed")) & local_names(task.get("affected_files")):
            claims.setdefault(path, set()).add(sha)
    proven = {}
    for path, shas in claims.items():
        # Normal porcelain hides assume-unchanged/skip-worktree entries and ignored replacements of deleted files.
        entry = _git(root, "--literal-pathspecs", "ls-files", "-v", "-z", "--", path)
        if entry != f"H {path}\0" and (entry or os.path.lexists(root / path)):
            continue
        last = _git(root, "--literal-pathspecs", "log", "-1", "--format=%H", f"{base}..HEAD", "--", path)
        if last in shas:
            proven[path] = last
    return proven


def feature_projects(root: Path, subtask: dict) -> dict[str, dict[str, Any]]:
    """Assign each affected file to one local Monitor, preserving literal Git entry names."""
    from map_step_runner import _normalize_mutation_declaration

    root = root.absolute()
    configs = subtask.get("repository_checks")
    if not isinstance(configs, dict) or len(configs) < 2:
        raise ValueError("repository_checks must name at least two participating Git checkouts")
    _command(subtask.get("joint_check"), "joint_check")
    declarations = subtask.get("affected_files")
    if not isinstance(declarations, list) or not declarations:
        raise ValueError("affected_files must list the approved files for all participating repositories")

    projects: dict[str, dict[str, Any]] = {}
    owners: dict[Path, str] = {}
    for key, config in configs.items():
        if not isinstance(key, str) or not key or "\x00" in key or not isinstance(config, dict):
            raise ValueError(f"invalid repository_checks entry {key!r}")
        supplied = root / key
        checkout = supplied.resolve()
        if Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
            raise ValueError(f"repository_checks[{key!r}] must name the Git checkout root")
        spellings = {checkout}
        supplied_absolute = Path(os.path.abspath(supplied))
        if supplied_absolute.resolve() == checkout:
            spellings.add(supplied_absolute)
        if any(path.is_relative_to(other) or other.is_relative_to(path) for path in spellings for other in owners):
            raise ValueError(f"repository_checks[{key!r}] overlaps another participating checkout")
        base = config.get("base")
        if not isinstance(base, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", base):
            raise ValueError(f"repository_checks[{key!r}].base must be a full Git commit SHA")
        if _git(checkout, "merge-base", base, "HEAD") != base:
            raise ValueError(f"repository_checks[{key!r}].base must be a commit in this checkout's history")
        projects[key] = {"root": checkout, "base": base, "files": [],
                         "command": _command(config.get("command"), f"repository_checks[{key!r}].command")}
        owners.update(dict.fromkeys(spellings, key))

    for declaration in declarations:
        if not isinstance(declaration, str) or not declaration or "\x00" in declaration:
            raise ValueError(f"invalid affected_files entry {declaration!r}")
        path = Path(declaration)
        anchor = root
        # Leading '..' identifies a sibling checkout; traversal inside its local scope stays invalid.
        while path.parts and path.parts[0] == "..":
            anchor, path = anchor.resolve().parent, path.relative_to("..")
        absolute = anchor / path
        owner = next((alias for alias in owners if absolute.is_relative_to(alias)), None)
        if owner is None:
            raise ValueError(f"affected_files entry {declaration!r} is outside the registered checkouts")
        project = projects[owners[owner]]
        local = _normalize_mutation_declaration(str(absolute.relative_to(owner)), project["root"])
        if in_nested_checkout(project["root"], Path(local)):
            raise ValueError(f"affected_files entry {declaration!r} belongs to a nested checkout")
        if local in project["files"]:
            raise ValueError(f"duplicate affected_files entry in {owners[owner]!r}: {local!r}")
        project["files"].append(local)

    for key, project in projects.items():
        if not project["files"]:
            raise ValueError(f"repository_checks[{key!r}] has no approved affected_files")
        project["files"].sort()
    return projects
