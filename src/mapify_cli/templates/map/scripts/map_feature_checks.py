"""Execute the local and joint acceptance checks of an approved feature."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import map_step_runner as runner
from map_feature_plan import feature_projects
from map_utils import atomic_write_text, branch_transaction, review_file_entry


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def _snapshot(root: Path, branch: str, files: list[str]) -> str:
    """Bind HEAD, the staged tree, and working copies not represented by the index."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", "--no-optional-locks", *args], cwd=root, env=runner._attribution_git_env(),
                              capture_output=True, check=True, timeout=30).stdout

    pathspecs = [".", f":(exclude,top,literal).map/{branch}",
                 f":(exclude,top,literal).map/.locks/{branch}.transaction.lock"]
    entries = git("ls-files", "--stage", "-v", "-z", "--", *pathspecs)
    changed = git("ls-files", "--modified", "--others", "--exclude-standard", "-z", "--", *pathspecs)
    paths = set(files) | {os.fsdecode(path) for path in changed.split(b"\0") if path}
    for entry in entries.split(b"\0"):
        # Git omits assume-unchanged and skip-worktree entries from --modified.
        if entry[:1].islower() or entry.startswith(b"S "):
            paths.add(os.fsdecode(entry.split(b"\t", 1)[1]))
    contents = []
    for path in sorted(paths):
        target = root / path
        if not target.parent.resolve().is_relative_to(root):
            raise ValueError(f"Path leaves checkout during verification: {path}")
        if target.exists() and not (target.is_symlink() or target.is_file()):
            raise ValueError(f"Cannot verify a non-file feature input: {path}")
        contents.append(review_file_entry(path, root))
    return _digest([str(root), git("rev-parse", "HEAD").decode().strip(),
                    hashlib.sha256(entries).hexdigest(), contents])


@dataclass
class _Check:
    root: Path
    path: Path
    command: list[str]
    binding: str
    receipt: dict
    project: dict | None = None

    def status(self) -> str:
        if self.receipt.get("binding") != self.binding or not isinstance(self.receipt.get("attempt"), str):
            return "pending"
        status = self.receipt.get("status")
        if status == "passed":
            if type(self.receipt.get("exit_code")) is not int or self.receipt["exit_code"] != 0:
                return "pending"
            if self.project is not None:
                scope = self.receipt.get("scope")
                if not isinstance(scope, dict) or scope.get("status") != "clean" or scope.get("expected") != self.project["files"]:
                    return "pending"
            return "passed"
        return status if status in ("running", "failed") else "pending"


def _attribution_current(check: _Check, receipt: dict, branch: str, task_id: str, coordinator: Path) -> bool:
    scope = receipt.get("scope")
    credited = scope.get("attributed_files") if isinstance(scope, dict) else None
    if not credited or check.project is None:
        return True
    current = runner.validate_feature_mutation(branch, task_id, check.project, coordinator=coordinator)
    return current.get("status") == "clean" and current.get("attributed_files") == credited


def _load_checks(root: Path, branch: str, task_id: str) -> dict[str | None, _Check]:
    from map_orchestrator import StepState, feature_contract_digest

    blueprint = runner.load_blueprint(branch, project_dir=root)
    if (not isinstance(blueprint, dict) or not isinstance(blueprint.get("subtasks"), list)
            or not all(isinstance(item, dict) for item in blueprint["subtasks"])):
        raise ValueError("Could not read the approved feature blueprint")
    task = runner.get_subtask_from_blueprint(blueprint, task_id)
    if not task:
        raise ValueError(f"Feature subtask {task_id} is missing from the blueprint")
    digest = feature_contract_digest(task, root)
    state = StepState.load(root / ".map" / branch / "step_state.json")
    if not state.plan_approved or state.approved_feature_contracts.get(task_id) != digest:
        raise ValueError(f"Approve the current feature plan before checking {task_id}")
    projects = feature_projects(root, task)
    key = _digest([str(root), task_id])

    def make(checkout: Path, filename: str, command: list[str], binding: str, project: dict | None = None) -> _Check:
        path = checkout / ".map" / branch / "feature-checks" / key / filename
        if path.resolve() != path:
            raise ValueError(f"Feature receipt location has changed: {path}")
        return _Check(checkout, path, command, binding, runner._read_json_file(path) or {}, project)

    checks: dict[str | None, _Check] = {}
    for name, project in projects.items():
        checkout = project["root"]
        binding = _digest([str(root), branch, name, digest, _snapshot(checkout, branch, project["files"])])
        local = make(checkout, "local.json", project["command"], binding, project)
        if local.status() == "passed" and not _attribution_current(local, local.receipt, branch, task_id, root):
            local.receipt = {}
        checks[name] = local
    locals_binding = {name: [check.binding, check.receipt.get("attempt")] for name, check in checks.items()}
    coordinator_snapshot = None
    if all(check.root != root for check in checks.values()):
        try:
            coordinator_snapshot = _snapshot(root, branch, [])
        except subprocess.SubprocessError as exc:
            raise ValueError(f"Cannot verify the coordinator checkout at {root}: {exc}") from exc
    joint_binding = _digest([locals_binding, coordinator_snapshot])
    checks[None] = make(root, "joint.json", task["joint_check"], joint_binding)
    return checks


def _report(checks: dict[str | None, _Check]) -> dict:
    def details(check: _Check) -> dict:
        status = check.status()
        info = {"status": status, "receipt": str(check.path), "root": str(check.root)}
        if check.project is not None:
            info.update(files=check.project["files"], base=check.project["base"])
        if status == "failed":
            info["message"] = check.receipt.get("message", "Check failed")
        return info

    local = {name: details(check) for name, check in checks.items() if name is not None}
    joint = details(checks[None])
    complete = joint["status"] == "passed" and all(row["status"] == "passed" for row in local.values())
    return {"status": "complete" if complete else "pending", "repositories": local, "joint": joint}


def _run(check: _Check, branch: str, task_id: str, coordinator: Path) -> dict:
    result: dict[str, Any] = {}
    if check.project is not None:
        scope = runner.validate_feature_mutation(branch, task_id, check.project, coordinator=coordinator)
        result.update(scope=scope, base=check.project["base"], files=check.project["files"])
        if scope.get("status") != "clean":
            return {**result, "status": "failed", "message": scope.get("message") or
                    f"Local mutation check: {scope.get('status')}, unexpected files: {scope.get('unexpected', [])}"}
    with tempfile.TemporaryFile() as output:
        process = subprocess.run(check.command, cwd=check.root, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, check=False, timeout=600,
                                 env={**runner._attribution_git_env(), "CLAUDE_PROJECT_DIR": str(check.root)})
        result["exit_code"] = process.returncode
        if process.returncode:
            output.seek(max(0, output.tell() - 4096))
            message = output.read().decode(errors="replace").strip()
            return {**result, "status": "failed", "message": f"Check exited {process.returncode}. {message}".rstrip()}
    return {**result, "status": "passed"}


def feature_check(branch: str, subtask_id: str, *, repository: str | None = None,
                  joint: bool = False, project_dir: Path | None = None) -> dict:
    root = Path(project_dir or Path.cwd()).resolve()
    branch = runner._sanitize_branch(branch)
    directory = root / ".map" / branch
    try:
        if directory.resolve() != directory or (directory.parent / ".locks").is_symlink():
            raise ValueError("Feature metadata must stay in the coordinator checkout")
        if repository is None and not joint:
            return _report(_load_checks(root, branch, subtask_id))
        with branch_transaction(directory):
            checks = _load_checks(root, branch, subtask_id)
            report = _report(checks)
            if repository not in checks or (repository is not None and joint):
                raise ValueError("Select one repository named in repository_checks, or the joint check")
            if joint and any(part["status"] != "passed" for part in report["repositories"].values()):
                return {**report, "message": "Every local check must pass before joint acceptance. See repositories for each status."}
            check = checks[repository]
            receipt = {"status": "running", "attempt": uuid.uuid4().hex, "binding": check.binding,
                       "branch": branch, "subtask_id": subtask_id, "root": str(check.root), "command": check.command}
            atomic_write_text(check.path, json.dumps(receipt) + "\n")
        try:
            outcome = _run(check, branch, subtask_id, root)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            outcome = {"status": "failed", "message": str(exc)}
        with branch_transaction(directory):
            current = _load_checks(root, branch, subtask_id)
            updated = current[repository]
            if updated.receipt.get("attempt") != receipt["attempt"]:
                return {**_report(current), "status": "error", "message": "A newer check superseded this attempt"}
            if updated.binding != check.binding or (
                outcome["status"] == "passed" and not _attribution_current(updated, outcome, branch, subtask_id, root)
            ):
                outcome = {"status": "failed", "message": "Feature inputs changed while the check ran"}
            updated.receipt = {**receipt, **outcome}
            atomic_write_text(updated.path, json.dumps(updated.receipt) + "\n")
            report = _report(current)
            if outcome["status"] != "passed":
                report.update(status="error", message=outcome["message"])
            return report
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "error", "message": str(exc)}
