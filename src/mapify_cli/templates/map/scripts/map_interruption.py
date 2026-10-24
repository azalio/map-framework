"""Serial blocker repair in an independent repository.

Requires exclusive, quiescent checkout ownership. Recovery supports ordinary
process restart at operation boundaries, not power loss or concurrent writers.
The synthetic working snapshot never enters the parent object database.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict


class ActiveInterruption(TypedDict):
    operation_id: str
    contract_digest: str


class RepairContract(TypedDict):
    repair_id: str
    entry: dict[str, Any]
    affected_files: list[str]
    dependencies: list[str]
    repair_checks: list[list[str]]
    dependency_results: dict[str, Any]


class RepairReceipt(TypedDict):
    operation_id: str
    repair_id: str
    contract_digest: str
    commit_sha: str
    status: str


class RepairError(RuntimeError):
    """A fail-closed boundary refusal, without file contents in diagnostics."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RepairError(f"Symlink metadata refused: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepairError(f"Expected object metadata: {path.name}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".repair-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(_json(value))
        os.replace(name, path)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_TERMINAL_PROMPT": "0"})
    environment.update(extra or {})
    return environment


def _git(root: Path, *args: str, data: bytes | None = None,
         env: dict[str, str] | None = None) -> bytes:
    process = subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
         "-c", "core.autocrlf=false", *args], cwd=root, input=data, capture_output=True,
        timeout=60, check=False, env=_git_env(env),
    )
    if process.returncode:
        # Intent: Git output can include payloads; report only the failed verb.
        raise RepairError(f"Git {args[0]} failed (exit {process.returncode})")
    return process.stdout


def _text(root: Path, *args: str) -> str:
    return _git(root, *args).decode().strip()


def _context(branch: str) -> tuple[Path, Path, Path]:
    if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", branch):
        raise RepairError("Expected sanitized branch identifier")
    if ".." in branch:
        raise RepairError("Unsafe branch identifier")
    root = Path(_text(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    gitdir = Path(_text(root, "rev-parse", "--absolute-git-dir"))
    common = Path(_text(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if (gitdir.is_symlink() or common.is_symlink() or (root / ".git").is_symlink() or
            not gitdir.is_dir() or not common.is_dir() or
            (common / "objects").is_symlink() or not (common / "objects").is_dir()):
        raise RepairError("Invalid Git administration or shared object storage")
    gitdir, common = gitdir.resolve(), common.resolve()
    if gitdir == common:
        if gitdir != root / ".git":
            raise RepairError("Unsupported separate Git directory")
    else:
        # Linked worktrees share objects, never repair journals or index locks.
        backlink = gitdir / "gitdir"
        if (gitdir.parent != common / "worktrees" or gitdir.parent.is_symlink() or
                not (root / ".git").is_file() or backlink.is_symlink() or
                (gitdir / "commondir").is_symlink() or
                (gitdir / backlink.read_text(encoding="utf-8").strip()).resolve() != root / ".git"):
            raise RepairError("Invalid linked worktree administration")
    branch_dir = root / ".map" / branch
    if branch_dir.is_symlink() or (root / ".map").is_symlink():
        raise RepairError("Symlink runtime directory refused")
    return root, gitdir, branch_dir


def _lock(branch_dir: Path) -> Any:
    return importlib.import_module("map_utils").branch_transaction(branch_dir)


def _runtime(path: str) -> bool:
    return (path == ".map" or path.startswith(".map/")) and not path.startswith(".map/scripts/")


def _safe(root: Path, path: str) -> Path:
    parts = Path(path).parts
    if not parts or path.startswith("/") or any(p in (".", "..", ".git") for p in parts):
        raise RepairError("Unsafe snapshot path")
    if any(ord(c) < 32 for c in path) or "\\" in path:
        raise RepairError("Unsupported snapshot path")
    for part in parts:
        lower = part.casefold()
        if (lower.startswith(".env") or "credential" in lower or
                lower in {"id_rsa", "id_ed25519", "secrets", "secrets.json"} or
                lower.endswith((".pem", ".key", ".p12", ".pfx"))):
            raise RepairError("Sensitive snapshot path refused")
    result = root / path
    for ancestor in result.parents:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise RepairError("Symlink ancestor refused")
    return result


def _image(root: Path, path: str) -> dict[str, Any] | None:
    target = _safe(root, path)
    if not os.path.lexists(target):
        return None
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode):
        link = os.readlink(target)
        if Path(link).is_absolute() or ".." in Path(link).parts:
            raise RepairError("Escaping symlink refused")
        return {"kind": "symlink", "target": link}
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RepairError("Special or hardlinked snapshot file refused")
    list_attributes = getattr(os, "listxattr", None)
    if callable(list_attributes) and list_attributes(target):
        raise RepairError("Extended file metadata is unsupported")
    return {"kind": "file", "mode": stat.S_IMODE(info.st_mode),
            "data": base64.b64encode(target.read_bytes()).decode()}


def _put(root: Path, path: str, image: dict[str, Any] | None) -> None:
    target = _safe(root, path)
    if image is None:
        if os.path.lexists(target):
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".repair-", dir=target.parent)
    try:
        if image["kind"] == "symlink":
            os.close(descriptor)
            os.unlink(temporary)
            os.symlink(image["target"], temporary)
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(base64.b64decode(image["data"], validate=True))
                os.fchmod(stream.fileno(), image["mode"])
        os.replace(temporary, target)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def _entries(root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for raw in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not raw:
            continue
        metadata, name = raw.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split()
        if stage != "0" or mode not in {"100644", "100755", "120000"}:
            raise RepairError("Only ordinary stage-zero index entries supported")
        result[name.decode()] = [mode, oid]
    return result


def _paths(root: Path) -> list[str]:
    tracked = _git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    current = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = sorted({p.decode() for p in (tracked + current).split(b"\0") if p})
    names: set[str] = set()
    paths = [p for p in paths if not _runtime(p)]
    for path in paths:
        _safe(root, path)
        key = path.casefold()
        if key in names:
            raise RepairError("Case aliases refused")
        names.add(key)
    return [p for p in paths if not _runtime(p)]


def _preflight(root: Path, gitdir: Path) -> None:
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
                 "rebase-apply", "sequencer", "index.lock", "BISECT_LOG", "info/sparse-checkout"):
        if (gitdir / name).exists():
            raise RepairError("Active Git operation or unsupported index layout")
    for key in ("core.sparseCheckout", "core.splitIndex"):
        value = subprocess.run(["git", "config", "--get", key], cwd=root,
                               capture_output=True, timeout=5, check=False, env=_git_env())
        if value.returncode not in (0, 1):
            raise RepairError("Git configuration read failed")
        if value.stdout.strip().lower() in {b"true", b"1", b"yes"}:
            raise RepairError("Sparse/split index unsupported")
    for raw in _git(root, "ls-files", "-v", "-z").split(b"\0"):
        if raw and raw[:1] != b"H":
            raise RepairError("Special index flags unsupported")
    debug_index = _git(root, "ls-files", "--debug").decode()
    if any(int(flags, 16) for flags in re.findall(r"flags: ([0-9a-fA-F]+)", debug_index)):
        raise RepairError("Intent-to-add or extended index flags unsupported")
    if any(entry[1] == "0" * 40 for entry in _entries(root).values()):
        raise RepairError("Intent-to-add unsupported")
    paths = _paths(root)
    attributes = _git(root, "check-attr", "--stdin", "-z", "filter", "eol", "text", "working-tree-encoding",
                      data=b"\0".join(p.encode() for p in paths) + b"\0")
    fields = attributes.split(b"\0")
    if any(fields[i] not in {b"unspecified", b"unset"} for i in range(2, len(fields)-1, 3)):
        raise RepairError("Git content filters unsupported")
    # Validate every path before reading any file bytes.
    for path in paths:
        _safe(root, path)


def _overlap(left: str, right: str) -> bool:
    a, b = left.casefold().rstrip("/"), right.casefold().rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _contract(branch_dir: Path, repair_id: str, state: dict[str, Any]) -> RepairContract:
    payload = _read(branch_dir / "blueprint.json")
    body = payload.get("blueprint", payload)
    subtasks = body.get("subtasks", [])
    entries = [s for s in subtasks if isinstance(s, dict) and s.get("id") == repair_id]
    if len(entries) != 1 or state.get("current_subtask_id") == repair_id:
        raise RepairError("Repair must name one independent blueprint subtask")
    entry = entries[0]
    affected = entry.get("affected_files")
    deps = entry.get("dependencies", [])
    checks = entry.get("repair_checks")
    if not isinstance(affected, list) or not affected or not all(isinstance(p, str) for p in affected):
        raise RepairError("Explicit affected_files required")
    for path in affected:
        _safe(branch_dir.parents[1], path)
        if _runtime(path) or any(c in path for c in "*?["):
            raise RepairError("Repair scope must use exact ordinary paths")
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise RepairError("Invalid repair dependencies")
    if not isinstance(checks, list) or not checks or not all(
        isinstance(c, list) and c and all(isinstance(a, str) and a and "\0" not in a for a in c)
        for c in checks
    ):
        raise RepairError("Explicit nonempty repair_checks command vectors required")
    ledger = state.get("subtask_results", {})
    dependency_results = {}
    for dep in deps:
        result = ledger.get(dep)
        if dep == state.get("current_subtask_id") or not isinstance(result, dict) or result.get("status") not in {"completed", "done", "success"}:
            raise RepairError("Repair dependency not completed in result ledger")
        dependency_results[dep] = result
    return {"repair_id": repair_id, "entry": entry, "affected_files": affected,
            "dependencies": deps, "repair_checks": checks, "dependency_results": dependency_results}


def _binding(branch: str, contract: RepairContract) -> tuple[str, str, str]:
    digest = _digest(contract)
    operation = "repair-" + _digest([branch, contract["repair_id"], digest])[:24]
    summary = _json({"repair_id": contract["repair_id"], "branch": branch,
                     "contract_digest": digest, "contract": contract})
    return operation, digest, summary


def _journal(gitdir: Path, operation: str) -> Path:
    if not re.fullmatch(r"repair-[a-f0-9]{24}", operation):
        raise RepairError("Invalid operation identifier")
    directory = gitdir / "map-repairs" / operation
    if directory.is_symlink() or (gitdir / "map-repairs").is_symlink():
        raise RepairError("Symlink repair storage refused")
    return directory / "journal.json"


def _guard(root: Path, gitdir: Path, branch_dir: Path) -> dict[str, Any] | None:
    state = _read(branch_dir / "step_state.json")
    marker = state.get("active_interruption")
    storage = gitdir / "map-repairs"
    if storage.is_symlink():
        raise RepairError("Symlink repair storage refused")
    journals = []
    for directory in storage.glob("*"):
        if directory.is_symlink() or not directory.is_dir() or not (directory / "journal.json").is_file():
            raise RepairError("Missing or corrupt repair journal; inspect private repair storage")
        journals.append(directory / "journal.json")
    active = []
    for path in journals:
        journal = _read(path)
        if journal.get("branch") == branch_dir.name and journal.get("stage") != "done":
            active.append(journal)
    if marker is not None:
        if not isinstance(marker, dict):
            raise RepairError("Corrupt interruption marker")
        journal = _read(_journal(gitdir, marker.get("operation_id", "")))
        if (journal.get("contract_digest") != marker.get("contract_digest") or
                journal.get("branch") != branch_dir.name or journal.get("root") != str(root)):
            raise RepairError("Marker/journal binding mismatch")
        return {"status": "interrupted", "operation_id": journal["operation_id"],
                "stage": journal["stage"], "private_checkout": journal["private_checkout"]}
    if active:
        raise RepairError("Unfinished repair journal without interruption marker")
    return None


def _require_serial_repair_state(state: dict[str, Any], branch_dir: Path) -> None:
    """Reject concurrent work, not historical wave/phase metadata."""
    current = state.get("current_subtask_id")
    phases = state.get("subtask_phases", {})
    if not isinstance(phases, dict):
        raise RepairError("Invalid subtask phase metadata")
    inactive = {"complete", "completed", "skipped", "no-op", "deferred_for_deps"}
    for subtask_id, phase in phases.items():
        if not isinstance(subtask_id, str) or not isinstance(phase, str):
            raise RepairError("Invalid subtask phase metadata")
        if subtask_id != current and phase.lower() not in inactive:
            raise RepairError("Another subtask is in progress; serial repair required")
    active = state.get("active_subtasks", [])
    if not isinstance(active, list) or any(not isinstance(item, str) for item in active):
        raise RepairError("Invalid active subtask metadata")
    if any(item != current for item in active):
        raise RepairError("Another subtask is in progress; serial repair required")
    sidecar = branch_dir / "worktrees.json"
    if sidecar.is_symlink():
        raise RepairError("Symlink worktree state refused")
    if sidecar.exists():
        worktree_state = _read(sidecar)
        for key in ("worktrees", "wave_groups"):
            records = worktree_state.get(key, {})
            if not isinstance(records, dict):
                raise RepairError("Invalid worktree state metadata")
            if records:
                raise RepairError("Active managed worktrees or wave group; serial repair required")


def interruption_guard(branch: str) -> dict[str, Any] | None:
    try:
        # Ordinary workflows also support pre-Git planning. Only a clean,
        # marker-free state may bypass repository resolution in that case.
        cwd = Path.cwd()
        if not any(os.path.lexists(ancestor / ".git") for ancestor in (cwd, *cwd.parents)):
            if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", branch) or ".." in branch:
                raise RepairError("Unsafe branch identifier")
            state_path = cwd / ".map" / branch / "step_state.json"
            if state_path.exists() and _read(state_path).get("active_interruption") is not None:
                raise RepairError("Interruption marker without Git repository")
            return None
        root, gitdir, branch_dir = _context(branch)
        if not (branch_dir / "step_state.json").exists():
            if os.path.lexists(gitdir / "map-repairs"):
                raise RepairError("Repair storage exists but workflow state is missing")
            return None
        with _lock(branch_dir):
            return _guard(root, gitdir, branch_dir)
    except (RepairError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reasons": [str(exc)]}


def get_interruption_status(branch: str) -> dict[str, Any]:
    return interruption_guard(branch) or {"status": "idle"}


def request_repair(repair_id: str, branch: str) -> dict[str, Any]:
    try:
        root, gitdir, branch_dir = _context(branch)
        with _lock(branch_dir):
            if _guard(root, gitdir, branch_dir):
                raise RepairError("Another repair is active")
            state = _read(branch_dir / "step_state.json")
            contract = _contract(branch_dir, repair_id, state)
            operation, digest, summary = _binding(branch, contract)
            runner = importlib.import_module("map_step_runner")
            with _cwd(root):
                result = runner.create_approval_hold(
                    kind="dangerous_action", reason="Serial lossless blocker repair",
                    request_summary=summary, source="map_interruption:" + digest,
                    branch=branch, safe_continuation="Approve this exact repair contract before begin_repair",
                )
            return {**result, "operation_id": operation, "contract_digest": digest}
    except (RepairError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reasons": [str(exc)]}


@contextlib.contextmanager
def _cwd(root: Path) -> Any:
    original = Path.cwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(original)


def _commit(root: Path, tree: str, parent: str, message: str) -> str:
    return _git(root, "commit-tree", tree, "-p", parent, data=message.encode(), env={
        "GIT_AUTHOR_NAME": "MAP repair", "GIT_AUTHOR_EMAIL": "map@localhost",
        "GIT_COMMITTER_NAME": "MAP repair", "GIT_COMMITTER_EMAIL": "map@localhost",
    }).decode().strip()


@contextlib.contextmanager
def _initialization(gitdir: Path, branch_dir: Path, path: Path,
                    state: dict[str, Any]) -> Any:
    """Archive only this call's unmarked initialization; never discard a snapshot."""
    path.parent.mkdir(mode=0o700)
    identity = path.parent.stat()
    state_digest = _digest(state)
    expected: dict[str, Any] = {}
    try:
        yield expected
    except Exception as exc:
        try:
            info = path.parent.lstat()
            if (path.parent.is_symlink() or path.parent.parent.is_symlink() or
                    not stat.S_ISDIR(info.st_mode) or
                    (info.st_dev, info.st_ino) != (identity.st_dev, identity.st_ino)):
                raise RepairError("Initialization directory ownership drift")
            current = _read(branch_dir / "step_state.json")
            if current.get("active_interruption") is not None or _digest(current) != state_digest:
                raise RepairError("Initialization state changed; recovery storage retained")
            if expected.get("journal_written") and not os.path.lexists(path):
                raise RepairError("Initialization journal missing; recovery storage retained")
            if os.path.lexists(path) and (
                    "journal_digest" not in expected or _digest(_read(path)) != expected["journal_digest"]):
                raise RepairError("Initialization journal drift; recovery storage retained")
            if gitdir.is_symlink():
                raise RepairError("Git storage identity drift")
            archive = Path(tempfile.mkdtemp(prefix="map-failed-" + path.parent.name + "-", dir=gitdir))
            path.parent.chmod(0o700)
            os.replace(path.parent, archive)
        except (RepairError, OSError, ValueError, KeyError, TypeError) as cleanup_error:
            raise RepairError(f"{exc}; initialization cleanup refused: {cleanup_error}") from exc
        raise RepairError(f"{exc}; failed initialization preserved at {archive}") from exc


def begin_repair(repair_id: str, branch: str, approval_hold_id: str) -> dict[str, Any]:
    try:
        root, gitdir, branch_dir = _context(branch)
        with _lock(branch_dir):
            state = _read(branch_dir / "step_state.json")
            contract = _contract(branch_dir, repair_id, state)
            operation, digest, summary = _binding(branch, contract)
            journal_path = _journal(gitdir, operation)
            holds = _read(branch_dir / "approval_holds.json").get("holds", {})
            hold = holds.get(approval_hold_id, {})
            if (hold.get("kind") != "dangerous_action" or hold.get("state") != "approved" or
                    hold.get("source") != "map_interruption:" + digest or
                    hold.get("request_summary") != summary or hold.get("branch") != branch):
                raise RepairError("Approved hold does not bind this exact repair contract")
            if journal_path.exists():
                journal = _read(journal_path)
                if journal.get("contract_digest") != digest or journal.get("approval_hold_id") != approval_hold_id:
                    raise RepairError("Repeated operation contract mismatch")
                if journal.get("stage") == "done":
                    return {"status": "ok", **journal["receipt"], "stage": "done"}
                marker = state.get("active_interruption")
                expected_marker = {"operation_id": operation, "contract_digest": digest}
                if journal.get("stage") == "prepared" and marker in (None, expected_marker):
                    if _frame(state) != _frame(journal["frame"]) or _entries(root) != journal["original_index"] or any(
                        _image(root, p) != image for p, image in journal["original_images"].items()
                    ) or _text(root, "rev-parse", "HEAD") != journal["head"]:
                        raise RepairError("Prepared initialization preimage drift")
                    state["active_interruption"] = expected_marker
                    _write(branch_dir / "step_state.json", state)
                    journal["stage"] = "active"
                    _write(journal_path, journal)
                elif marker != expected_marker:
                    raise RepairError("Interrupted initialization requires operator inspection")
                return _status(journal)
            if _guard(root, gitdir, branch_dir):
                raise RepairError("Nested repair unsupported")
            if not state.get("current_subtask_id") or state.get("current_step_phase") in {"COMPLETE", "DECOMPOSE"}:
                raise RepairError("An active serial subtask is required")
            _require_serial_repair_state(state, branch_dir)
            _preflight(root, gitdir)
            head = _text(root, "rev-parse", "HEAD")
            ref = _text(root, "symbolic-ref", "HEAD")
            paths = _paths(root)
            index = _entries(root)
            images = {p: _image(root, p) for p in paths}
            dirty = {p.decode() for p in _git(root, "diff", "--name-only", "--no-renames", "-z", "HEAD").split(b"\0") if p}
            dirty.update(p for p in paths if p not in index)
            for path in contract["affected_files"]:
                if any(_overlap(path, paused) for paused in dirty):
                    raise RepairError("Repair scope overlaps paused changes")
            baseline = importlib.import_module("map_step_runner")._resolve_subtask_diff_base(
                branch, state["current_subtask_id"], root
            ) or head
            baseline = _text(root, "rev-parse", baseline + "^{tree}")
            journal_path.parent.parent.mkdir(mode=0o700, exist_ok=True)
            journal_path.parent.parent.chmod(0o700)
            with _initialization(gitdir, branch_dir, journal_path, state) as expected:
                journal_path.parent.chmod(0o700)
                private = journal_path.parent / "checkout"
                private.mkdir(mode=0o700)
                _git(private, "init", "--quiet")
                _git(private, "fetch", "--quiet", "--no-tags", str(root), head)
                _git(private, "symbolic-ref", "HEAD", ref)
                _git(private, "update-ref", ref, head)
                _git(private, "read-tree", head)
                for path, image in images.items():
                    _put(private, path, image)
                # Intent: runtime artifacts belong to the private workflow, not its candidate tree.
                _git(private, "add", "-A", "--", ".")
                excluded = [p for p in _entries(private) if _runtime(p)]
                if excluded:
                    _git(private, "update-index", "--force-remove", "--", *excluded)
                snapshot_tree = _text(private, "write-tree")
                snapshot = _commit(private, snapshot_tree, head, "Private working snapshot\n")
                _git(private, "update-ref", ref, snapshot, head)
                (private / ".git/info/exclude").write_text(".map/*\n", encoding="utf-8")
                # Installed scripts can be ignored in the host. Copy only executable
                # runtime sources, never parent branch artifacts or local settings.
                runtime_images = {}
                instruction_paths = [root / "CLAUDE.md", root / "AGENTS.md"]
                for provider in (".claude", ".codex", ".agents"):
                    instruction_paths.extend((root / provider).rglob("*.md"))
                for runtime_path in [*(root / ".map/scripts").glob("*.py"), *instruction_paths]:
                    if not runtime_path.exists():
                        continue
                    relative = runtime_path.relative_to(root).as_posix()
                    if relative not in images:
                        runtime_images[relative] = _image(root, relative)
                        _put(private, relative, runtime_images[relative])
                        with (private / ".git/info/exclude").open("a", encoding="utf-8") as stream:
                            stream.write("/" + relative + "\n")
                local = private / ".map" / branch
                local.mkdir(parents=True)
                _write(local / "blueprint.json", {"subtasks": [contract["entry"]]})
                (local / f"task_plan_{branch}.md").write_text(
                    f"# Repair plan\n\n## {repair_id}\n\n{_json(contract['entry'])}\n", encoding="utf-8")
                _write(local / "parent_context.json", state)
                orchestrator = importlib.import_module("map_orchestrator")
                order = orchestrator._get_step_order(bool(state.get("tdd_mode")))
                private_state = orchestrator.StepState(
                    current_subtask_id=repair_id, subtask_sequence=[repair_id],
                    current_step_id="2.2", current_step_phase="RESEARCH",
                    completed_steps=["1.0", "1.5", "1.55", "1.56", "1.6"],
                    pending_steps=order[order.index("2.2"):], plan_approved=True,
                    tdd_mode=bool(state.get("tdd_mode")), workflow_status="IN_PROGRESS",
                    subtask_results=contract["dependency_results"],
                )
                private_state.save(local / "step_state.json")
                journal = {"version": 1, "operation_id": operation, "branch": branch,
                           "repair_id": repair_id, "contract": contract, "contract_digest": digest,
                           "approval_hold_id": approval_hold_id, "root": str(root), "gitdir": str(gitdir),
                           "ref": ref, "head": head, "baseline_tree": baseline,
                           "private_checkout": str(private), "snapshot": snapshot,
                           "snapshot_tree": snapshot_tree, "original_index": index,
                           "original_images": images, "runtime_images": runtime_images,
                           "paused_paths": sorted(dirty),
                           "frame": state, "stage": "prepared"}
                expected["journal_digest"] = _digest(journal)
                _write(journal_path, journal)
                expected["journal_written"] = True
                _checkpoint("prepared")
                if _entries(root) != index or _text(root, "rev-parse", "HEAD") != head or any(_image(root, p) != v for p, v in images.items()):
                    raise RepairError("Checkout drift during snapshot; main state not marked")
                state["active_interruption"] = {"operation_id": operation, "contract_digest": digest}
                _write(branch_dir / "step_state.json", state)
                _checkpoint("marker_written")
                journal["stage"] = "active"
                _write(journal_path, journal)
                return _status(journal)
    except (RepairError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reasons": [str(exc)]}


def _status(journal: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", **{k: journal[k] for k in
            ("operation_id", "contract_digest", "private_checkout", "stage")}}


def _load_operation(branch: str, operation: str) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    root, gitdir, branch_dir = _context(branch)
    path = _journal(gitdir, operation)
    journal = _read(path)
    if (journal.get("root") != str(root) or journal.get("gitdir") != str(gitdir) or
            journal.get("branch") != branch or journal.get("operation_id") != operation):
        raise RepairError("Repository/operation identity changed")
    state = _read(branch_dir / "step_state.json")
    if journal["stage"] != "done" and state.get("active_interruption") != {
        "operation_id": operation, "contract_digest": journal["contract_digest"]
    }:
        raise RepairError("Operation marker missing or mismatched")
    if journal["stage"] != "done" and _digest(_contract(branch_dir, journal["repair_id"], state)) != journal["contract_digest"]:
        raise RepairError("Approved repair contract changed")
    return root, gitdir, branch_dir, path, journal


def _tree_entries(root: Path, tree: str) -> dict[str, list[str]]:
    result = {}
    for raw in _git(root, "ls-tree", "-r", "-z", tree).split(b"\0"):
        if raw:
            info, path = raw.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            if kind != "blob":
                raise RepairError("Candidate contains unsupported tree entries")
            result[path.decode()] = [mode, oid]
    return result


def _exact_candidate(private: Path, tree: str) -> dict[str, Any]:
    _preflight(private, private / ".git")
    entries = _tree_entries(private, tree)
    images = {}
    for path, (mode, oid) in entries.items():
        image = _image(private, path)
        blob = _git(private, "cat-file", "blob", oid)
        if mode == "120000":
            matches = image is not None and image.get("kind") == "symlink" and image.get("target", "").encode() == blob
        else:
            matches = (image is not None and image.get("kind") == "file" and
                       base64.b64decode(image["data"]) == blob and
                       bool(image["mode"] & 0o111) == (mode == "100755"))
        if not matches:
            raise RepairError("Raw working files differ from certified candidate tree")
        images[path] = image
    return images


def _apply_entries(root: Path, entries: Mapping[str, list[str] | None], index_path: Path) -> str:
    env = {"GIT_INDEX_FILE": str(index_path)}
    data = b""
    for path, entry in sorted(entries.items()):
        mode, oid = entry if entry else ("0", "0" * 40)
        data += f"{mode} {oid}\t".encode() + path.encode() + b"\0"
    _git(root, "update-index", "-z", "--index-info", data=data, env=env)
    return _git(root, "write-tree", env=env).decode().strip()


def _reconstruct(private: Path, base: str, entries: dict[str, list[str] | None], path: Path) -> str:
    _git(private, "read-tree", base, env={"GIT_INDEX_FILE": str(path)})
    return _apply_entries(private, entries, path)


def verify_repair(operation_id: str, branch: str, monitor_file: str) -> dict[str, Any]:
    try:
        _, _, branch_dir = _context(branch)
        with _lock(branch_dir):
            root, _, _, path, journal = _load_operation(branch, operation_id)
            if journal["stage"] not in {"active", "verified"}:
                raise RepairError("Verification cannot replace a finish in progress")
            private = Path(journal["private_checkout"])
            state = _read(private / ".map" / branch / "step_state.json")
            steps = state.get("completed_steps", [])
            if (state.get("workflow_status") != "WORKFLOW_COMPLETE" or
                    state.get("current_step_phase") != "COMPLETE" or
                    state.get("subtask_sequence") != [journal["repair_id"]] or
                    not all(step in steps for step in ("2.2", "2.3", "2.4"))):
                raise RepairError("Private normal research/actor/monitor workflow is incomplete")
            monitor_path = Path(monitor_file).resolve()
            if not monitor_path.is_relative_to(private / ".map" / branch):
                raise RepairError("Monitor evidence must belong to private repair workflow")
            monitor = _read(monitor_path)
            if (monitor.get("valid") is not True or
                    str(monitor.get("recommendation", "")).lower() != "approve" or
                    not isinstance(monitor.get("summary"), str) or
                    not isinstance(monitor.get("issues"), list)):
                raise RepairError("Monitor requires complete valid/approve envelope")
            if _git(private, "status", "--porcelain", "--untracked-files=all"):
                raise RepairError("Freeze a clean final private candidate before verification")
            if any(_image(private, p) != image for p, image in journal["runtime_images"].items()):
                raise RepairError("Private runtime instructions or scripts drift")
            _preflight(private, private / ".git")
            candidate = _text(private, "rev-parse", "HEAD^{tree}")
            candidate_images = _exact_candidate(private, candidate)
            if any(monitor.get(key) != value for key, value in {
                "operation_id": operation_id, "contract_digest": journal["contract_digest"],
                "candidate_tree": candidate,
            }.items()):
                raise RepairError("Monitor evidence is not bound to this operation and candidate tree")
            changed = sorted(p.decode() for p in _git(private, "diff", "--no-renames", "--name-only", "-z",
                                                     journal["snapshot_tree"], candidate).split(b"\0") if p)
            if not changed or any(p not in journal["contract"]["affected_files"] for p in changed):
                raise RepairError("Candidate delta exceeds exact approved repair scope or is empty")
            if any(_overlap(p, paused) for p in changed for paused in journal["paused_paths"]):
                raise RepairError("Candidate overlaps paused changes")
            journal["stage"] = "active"
            journal.pop("gate_receipt", None)
            _write(path, journal)
            receipts = []
            for command in journal["contract"]["repair_checks"]:
                check = subprocess.run(command, cwd=private, capture_output=True, timeout=600,
                                       check=False, env=_git_env())
                receipts.append({"command": command, "exit_code": check.returncode})
                if check.returncode:
                    raise RepairError(f"Approved repair gate failed (exit {check.returncode})")
                if (_text(private, "rev-parse", "HEAD^{tree}") != candidate or
                        _git(private, "status", "--porcelain", "--untracked-files=all") or
                        _exact_candidate(private, candidate) != candidate_images):
                    raise RepairError("Gate modified the exact candidate tree")
            if any(_image(private, p) != image for p, image in journal["runtime_images"].items()):
                raise RepairError("Gate modified private runtime inputs")
            if _digest(_read(monitor_path)) != _digest(monitor):
                raise RepairError("Monitor evidence changed during verification")
            candidate_entries = _tree_entries(private, candidate)
            delta = {p: candidate_entries.get(p) for p in changed}
            repair_tree = _reconstruct(private, journal["head"], delta, path.parent / "repair.index")
            repair_commit = _commit(private, repair_tree, journal["head"], "Verified blocker repair\n")
            # Import the original baseline tree separately; never import synthetic S.
            _git(private, "fetch", "--quiet", "--no-tags", str(root), journal["head"])
            baseline_entries = _tree_entries(root, journal["baseline_tree"])
            for entry in baseline_entries.values():
                blob = _git(root, "cat-file", "blob", entry[1])
                _git(private, "hash-object", "-w", "--stdin", data=blob)
            baseline_index = path.parent / "baseline.index"
            _git(private, "read-tree", "--empty", env={"GIT_INDEX_FILE": str(baseline_index)})
            _apply_entries(private, baseline_entries, baseline_index)
            adjusted_tree = _apply_entries(private, delta, baseline_index)
            journal.update(stage="verified", candidate_tree=candidate, repair_commit=repair_commit,
                           repair_tree=repair_tree, adjusted_tree=adjusted_tree, delta=delta,
                           repair_images={p: _image(private, p) for p in changed},
                           candidate_images=candidate_images, monitor_path=str(monitor_path),
                           gate_receipt={"tree": candidate, "contract_digest": journal["contract_digest"],
                                         "workflow_digest": _digest(state),
                                         "monitor_digest": _digest(monitor), "checks": receipts})
            _write(path, journal)
            return _status(journal)
    except (RepairError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reasons": [str(exc)]}


def _checkpoint(_name: str) -> None:
    """Test injection seam between durable operations; never reads environment."""


def _frame(state: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in state.items() if k not in {
        "active_interruption", "completed_repair_operations", "subtask_diff_bases", "subtask_results"
    }}


def _validate_finish(root: Path, branch_dir: Path, journal: dict[str, Any]) -> None:
    if _text(root, "symbolic-ref", "HEAD") != journal["ref"]:
        raise RepairError("Attached branch drift")
    if journal["stage"] == "verified":
        allowed_head = {journal["head"]}
    elif journal["stage"] == "head_intent":
        allowed_head = {journal["head"], journal["repair_commit"]}
    else:
        allowed_head = {journal["repair_commit"]}
    if _text(root, "rev-parse", "HEAD") not in allowed_head:
        raise RepairError("External HEAD drift")
    state = _read(branch_dir / "step_state.json")
    if _frame(state) != _frame(journal["frame"]):
        raise RepairError("Paused workflow frame drift")
    for field in ("subtask_results", "subtask_diff_bases", "completed_repair_operations"):
        expected = dict(journal["frame"].get(field, {}))
        actual = state.get(field, {})
        if journal["stage"] == "done" and state.get("active_interruption") is None:
            if field == "subtask_results":
                expected[journal["repair_id"]] = {
                    **journal["receipt"], "subtask_id": journal["repair_id"],
                    "files_changed": sorted(journal["delta"]),
                    "summary": "Verified independent blocker repair",
                }
            elif field == "subtask_diff_bases":
                expected[journal["frame"]["current_subtask_id"]] = journal["adjusted_tree"]
            else:
                expected[journal["operation_id"]] = journal["receipt"]
        if actual != expected:
            raise RepairError("Paused ledger or attribution drift")
    index = _entries(root)
    delta = journal["delta"]
    if {p: e for p, e in index.items() if p not in delta} != {
        p: e for p, e in journal["original_index"].items() if p not in delta
    }:
        raise RepairError("External index paths drift")
    for p, image in journal["original_images"].items():
        if p not in delta and (_image(root, p) != image or index.get(p) != journal["original_index"].get(p)):
            raise RepairError("Paused working/index preimage drift")
    before = {p: journal["original_index"].get(p) for p in delta}
    actual = {p: index.get(p) for p in delta}
    if journal["stage"] in {"verified", "head_intent", "head_done"}:
        accepted_index = [before]
    elif journal["stage"] == "index_intent":
        accepted_index = [before, delta]
    else:
        accepted_index = [delta]
    if actual not in accepted_index:
        raise RepairError("Repair index drift")
    for p in delta:
        old = journal["original_images"].get(p)
        new = journal["repair_images"][p]
        permitted = [old, new] if journal["stage"] in {"files_intent", "files_done", "state_intent", "done"} else [old]
        if _image(root, p) not in permitted:
            raise RepairError("Repair working preimage drift")
    # Newly created paths outside the snapshot must also remain quiescent.
    owned_temporaries = set(journal.get("file_temporaries", {}).values())
    for final, temporary in journal.get("file_temporaries", {}).items():
        if os.path.lexists(root / temporary) and _image(root, temporary) != journal["repair_images"][final]:
            raise RepairError("Owned repair temporary contents drift")
    unexpected = set(_paths(root)) - set(journal["original_images"]) - set(delta) - owned_temporaries
    if unexpected:
        raise RepairError("External working paths appeared during repair")


def _target_index(root: Path, gitdir: Path, journal: dict[str, Any], journal_path: Path) -> None:
    lock = gitdir / "index.lock"
    candidate = journal_path.parent / "publish.index"
    if "index_publication" not in journal:
        if lock.exists():
            raise RepairError("Unfamiliar Git index lock; cannot remove it")
        candidate.write_bytes((gitdir / "index").read_bytes())
        _apply_entries(root, journal["delta"], candidate)
        journal["index_publication"] = {
            "old_digest": hashlib.sha256((gitdir / "index").read_bytes()).hexdigest(),
            "new_digest": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "lock_identity": None,
        }
        _write(journal_path, journal)
    publication = journal["index_publication"]
    current_digest = hashlib.sha256((gitdir / "index").read_bytes()).hexdigest()
    if current_digest not in {publication["old_digest"], publication["new_digest"]}:
        raise RepairError("Current index publication drift")
    if lock.exists():
        info = lock.lstat()
        if publication["lock_identity"] != [info.st_dev, info.st_ino]:
            raise RepairError("Unfamiliar Git index lock; cannot remove it")
        if hashlib.sha256(lock.read_bytes()).hexdigest() != publication["new_digest"]:
            raise RepairError("Incomplete owned index lock; operator inspection required")
    elif current_digest == publication["old_digest"]:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            info = os.fstat(stream.fileno())
            publication["lock_identity"] = [info.st_dev, info.st_ino]
            _write(journal_path, journal)
            stream.write(candidate.read_bytes())
            stream.flush()
        _checkpoint("index_lock_ready")
    if current_digest == publication["old_digest"]:
        os.replace(lock, gitdir / "index")
    elif lock.exists():
        lock.unlink()


def _publish_file(root: Path, final: str, image: dict[str, Any] | None,
                  journal: dict[str, Any], journal_path: Path) -> None:
    if image is None:
        _put(root, final, None)
        return
    temporary = journal.setdefault("file_temporaries", {}).get(final)
    if temporary is None:
        temporary = (Path(final).parent / (".repair-" + journal["operation_id"] + "-" +
                                          _digest(final)[:12])).as_posix()
        if os.path.lexists(root / temporary):
            raise RepairError("Unfamiliar repair temporary; cannot remove it")
        journal["file_temporaries"][final] = temporary
        _write(journal_path, journal)
    temporary_path = _safe(root, temporary)
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    identities = journal.setdefault("temporary_identities", {})
    if not os.path.lexists(temporary_path):
        if image["kind"] == "symlink":
            os.symlink(image["target"], temporary_path)
        else:
            descriptor = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        info = temporary_path.lstat()
        identities[temporary] = [info.st_dev, info.st_ino]
        _write(journal_path, journal)
    info = temporary_path.lstat()
    if identities.get(temporary) != [info.st_dev, info.st_ino]:
        raise RepairError("Unfamiliar file temporary identity")
    if image["kind"] == "file" and _image(root, temporary) != image:
        descriptor = os.open(temporary_path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(base64.b64decode(image["data"], validate=True))
            stream.truncate()
            os.fchmod(stream.fileno(), image["mode"])
    if _image(root, temporary) != image:
        raise RepairError("Owned file temporary drift")
    _checkpoint("file_temporary_ready")
    os.replace(temporary_path, _safe(root, final))


def finish_repair(operation_id: str, branch: str) -> dict[str, Any]:
    try:
        _, _, branch_dir = _context(branch)
        with _lock(branch_dir):
            root, gitdir, branch_dir, path, journal = _load_operation(branch, operation_id)
            if journal["stage"] == "done":
                state = _read(branch_dir / "step_state.json")
                completed_receipt = journal.get("receipt")
                if (state.get("active_interruption") is None and isinstance(completed_receipt, dict) and
                        state.get("completed_repair_operations", {}).get(operation_id) == completed_receipt):
                    return {"status": "ok", **completed_receipt, "stage": "done"}
            if journal["stage"] in {"active", "prepared"}:
                raise RepairError("Runner-owned exact-tree verification receipt required")
            receipt = journal.get("gate_receipt", {})
            if (receipt.get("tree") != journal.get("candidate_tree") or
                    receipt.get("contract_digest") != journal["contract_digest"] or
                    [c.get("command") for c in receipt.get("checks", [])] != journal["contract"]["repair_checks"] or
                    any(c.get("exit_code") != 0 for c in receipt.get("checks", []))):
                raise RepairError("Missing or stale verification receipt")
            private = Path(journal["private_checkout"])
            if any(_image(private, p) != image for p, image in journal["runtime_images"].items()):
                raise RepairError("Certified runtime inputs drift")
            if _digest(_read(private / ".map" / branch / "step_state.json")) != receipt.get("workflow_digest"):
                raise RepairError("Certified private workflow state drift")
            if _digest(_read(Path(journal["monitor_path"]))) != receipt.get("monitor_digest"):
                raise RepairError("Certified Monitor evidence drift")
            if (_text(private, "rev-parse", "HEAD^{tree}") != journal["candidate_tree"] or
                    _git(private, "status", "--porcelain", "--untracked-files=all") or
                    _exact_candidate(private, journal["candidate_tree"]) != journal["candidate_images"]):
                raise RepairError("Certified private candidate drift")
            _validate_finish(root, branch_dir, journal)
            def stage(name: str) -> None:
                journal["stage"] = name
                _write(path, journal)
                _checkpoint(name)
            if journal["stage"] == "verified":
                # Only R enters main history. Adjusted attribution is a tree, not S.
                _git(root, "fetch", "--quiet", "--no-tags", str(private), journal["repair_commit"])
                entries = _tree_entries(private, journal["adjusted_tree"])
                for entry in entries.values():
                    _git(root, "hash-object", "-w", "--stdin", data=_git(private, "cat-file", "blob", entry[1]))
                adjusted = path.parent / "adjusted-main.index"
                _git(root, "read-tree", "--empty", env={"GIT_INDEX_FILE": str(adjusted)})
                if _apply_entries(root, entries, adjusted) != journal["adjusted_tree"]:
                    raise RepairError("Attribution tree reconstruction mismatch")
                stage("head_intent")
            if journal["stage"] == "head_intent":
                if _text(root, "rev-parse", "HEAD") == journal["head"]:
                    _git(root, "update-ref", journal["ref"], journal["repair_commit"], journal["head"])
                _checkpoint("after_cas_before_journal")
                stage("head_done")
            if journal["stage"] == "head_done":
                stage("index_intent")
            if journal["stage"] == "index_intent":
                if {p: _entries(root).get(p) for p in journal["delta"]} != journal["delta"]:
                    _target_index(root, gitdir, journal, path)
                _checkpoint("after_index_before_journal")
                stage("index_done")
            if journal["stage"] == "index_done":
                stage("files_intent")
            if journal["stage"] == "files_intent":
                for number, (p, image) in enumerate(sorted(journal["repair_images"].items())):
                    _validate_finish(root, branch_dir, journal)
                    if _image(root, p) != image:
                        _publish_file(root, p, image, journal, path)
                    _checkpoint(f"file_{number}")
                stage("files_done")
            if journal["stage"] == "files_done":
                stage("state_intent")
            if journal["stage"] == "state_intent":
                state = _read(branch_dir / "step_state.json")
                result: RepairReceipt = {"operation_id": operation_id, "repair_id": journal["repair_id"],
                                         "contract_digest": journal["contract_digest"],
                                         "commit_sha": journal["repair_commit"], "status": "completed"}
                state.setdefault("completed_repair_operations", {})[operation_id] = result
                state.setdefault("subtask_results", {})[journal["repair_id"]] = {
                    **result, "subtask_id": journal["repair_id"], "files_changed": sorted(journal["delta"]),
                    "summary": "Verified independent blocker repair",
                }
                state.setdefault("subtask_diff_bases", {})[journal["frame"]["current_subtask_id"]] = journal["adjusted_tree"]
                state["active_interruption"] = None
                journal["receipt"] = result
                # Keep the marker until the durable done receipt is ready.
                stage("done")
                _write(branch_dir / "step_state.json", state)
                _checkpoint("state_done")
            elif journal["stage"] == "done":
                state = _read(branch_dir / "step_state.json")
                if state.get("active_interruption") is not None:
                    # Recover the journal-done/state-write cut with the same ledger receipt.
                    result = journal["receipt"]
                    state.setdefault("completed_repair_operations", {})[operation_id] = result
                    state.setdefault("subtask_results", {})[journal["repair_id"]] = {
                        **result, "subtask_id": journal["repair_id"], "files_changed": sorted(journal["delta"]),
                        "summary": "Verified independent blocker repair",
                    }
                    state.setdefault("subtask_diff_bases", {})[journal["frame"]["current_subtask_id"]] = journal["adjusted_tree"]
                    state["active_interruption"] = None
                    _write(branch_dir / "step_state.json", state)
            _validate_finish(root, branch_dir, journal)
            return {"status": "ok", **journal["receipt"], "stage": "done"}
    except (RepairError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reasons": [str(exc)]}
