"""Shared utilities for MAP workflow scripts."""

import argparse
import ast
import contextlib
import errno
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

_BRANCH_TRANSACTION_THREAD_LOCK = threading.RLock()
_BRANCH_TRANSACTION_DEPTH = 0
_BRANCH_TRANSACTION_DESCRIPTOR: int | None = None
_BRANCH_TRANSACTION_PATH: Path | None = None


def _lock_branch_descriptor(descriptor: int) -> None:
    """Acquire a blocking cross-process lock for an open lock file."""
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if exc.errno not in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                } and getattr(exc, "winerror", None) not in {33, 36}:
                    raise
                time.sleep(0.05)

    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_branch_descriptor(descriptor: int) -> None:
    """Release a lock acquired by :func:`_lock_branch_descriptor`."""
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    fcntl: Any = importlib.import_module("fcntl")
    fcntl.flock(descriptor, fcntl.LOCK_UN)


def acquire_branch_transaction(branch_dir: Path) -> None:
    """Serialize a complete branch read-modify-write transaction.

    The process-local ``RLock`` covers threads and makes nested calls reentrant;
    the persistent advisory lock file coordinates independent CLI processes.
    """
    global _BRANCH_TRANSACTION_DEPTH
    global _BRANCH_TRANSACTION_DESCRIPTOR
    global _BRANCH_TRANSACTION_PATH

    resolved_branch_dir = branch_dir.resolve()
    lock_path = (
        resolved_branch_dir.parent
        / ".locks"
        / f"{resolved_branch_dir.name}.transaction.lock"
    )
    _BRANCH_TRANSACTION_THREAD_LOCK.acquire()
    descriptor: int | None = None
    try:
        if _BRANCH_TRANSACTION_DEPTH:
            if _BRANCH_TRANSACTION_PATH != lock_path:
                raise RuntimeError(
                    "cannot nest MAP branch transactions for different directories"
                )
            _BRANCH_TRANSACTION_DEPTH += 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(lock_path, flags, 0o600)
        _lock_branch_descriptor(descriptor)
        _BRANCH_TRANSACTION_DESCRIPTOR = descriptor
        _BRANCH_TRANSACTION_PATH = lock_path
        _BRANCH_TRANSACTION_DEPTH = 1
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        _BRANCH_TRANSACTION_THREAD_LOCK.release()
        raise


def release_branch_transaction() -> None:
    """Release one nesting level of the current branch transaction."""
    global _BRANCH_TRANSACTION_DEPTH
    global _BRANCH_TRANSACTION_DESCRIPTOR
    global _BRANCH_TRANSACTION_PATH

    if _BRANCH_TRANSACTION_DEPTH <= 0:
        raise RuntimeError("no MAP branch transaction is currently held")

    descriptor: int | None = None
    try:
        _BRANCH_TRANSACTION_DEPTH -= 1
        if _BRANCH_TRANSACTION_DEPTH == 0:
            descriptor = _BRANCH_TRANSACTION_DESCRIPTOR
            _BRANCH_TRANSACTION_DESCRIPTOR = None
            _BRANCH_TRANSACTION_PATH = None
            if descriptor is None:
                raise RuntimeError("MAP branch transaction lost its lock descriptor")
            try:
                _unlock_branch_descriptor(descriptor)
            finally:
                os.close(descriptor)
    finally:
        _BRANCH_TRANSACTION_THREAD_LOCK.release()


@contextlib.contextmanager
def branch_transaction(branch_dir: Path) -> Iterator[None]:
    """Hold the shared branch lock for one complete state transaction."""
    acquire_branch_transaction(branch_dir)
    try:
        yield
    finally:
        release_branch_transaction()


def review_file_entry(name: str, root: Path = Path(".")) -> dict[str, Any]:
    path = root / name
    if path.is_symlink():
        content = os.fsencode(os.readlink(path))
        kind, mode = "symlink", 0o120000
    elif path.is_file():
        content = path.read_bytes()
        kind, mode = "file", path.stat().st_mode & 0o777
    else:
        content, kind, mode = b"", "missing", 0
    return {"path": name, "kind": kind, "mode": mode, "sha256": hashlib.sha256(content).hexdigest()}


# Declarative reviewer instructions embedded in the shipped scripts. Transport
# functions and delivery bookkeeping do not define what the reviewer must check.
REVIEW_RULE_SOURCES = {
    "map_step_runner.py": {
        "REVIEW_EVIDENCE_CONTRACT", "ROLE_FINDING_OUTPUT_CONTRACT", "ROLE_REVIEWER_SHARED_SCOPE",
        "ROLE_REVIEWER_SPECS", "REVIEW_PROMPT_SPECS", "ADVERSARIAL_REVIEWER_SPECS",
        "AGENT_OUTPUT_SCHEMAS", "ROLE_FINDING_CONTRACT_KEYS", "REVIEWER_PARAPHRASE_RULE",
        "REVIEW_COVERAGE_RECEIPT_SCHEMA", "ROLE_FINDING_SCHEMA",
        "REVIEW_FINDING_EVIDENCE_SCHEMA", "REVIEW_DESIGN_CHANGE_SCHEMA", "ADVERSARIAL_FINDING_SCHEMA",
        "build_cross_ai_review_prompt", "_review_compact_text", "get_review_section_order",
        "build_json_retry_prompt", "build_review_prompts", "build_role_review_prompts", "build_adversarial_review_prompts",
    },
    "codex_review_runner.py": {"ROLE_RUBRICS", "GUIDANCE", "_review_one", "_candidate_recheck_messages"},
    "codex_review_host.py": {"developerInstructions"},
}


# Prompt builders consume the admitted Git tree, policy, bundle and shard through these APIs.
# Their values have their own receipts. Transport/ledger changes below this boundary do not
# redefine reviewer instructions. Follow all other local helpers referenced by the builders.
_REVIEW_INPUT_APIS = {
    "_read_json_file", "_review_admitted_binding", "_review_attribution_artifact", "_review_compact_bundle",
    "_review_diff_resource", "_review_git_optional", "_review_prompt_budget_tokens", "_review_shard_gate",
    "_review_transport_active", "_review_trusted_policy", "_resolve_review_base", "_scoped_review_diff",
}


def review_rules_digest(path: Path, script: str, *, expected_sha: str = "") -> str:
    info = path.stat()
    return _cached_review_rules(path.resolve(), script, expected_sha, info.st_ino, info.st_size, info.st_ctime_ns,
                                info.st_mtime_ns)


def _review_prompt_entries(function: ast.FunctionDef, *, returns_entry: bool = False) -> list[ast.AST]:
    """Read each builder from input selection through prompt construction, up to delivery."""
    sections: list[ast.AST] = []
    body = function.body[1:] if ast.get_docstring(function) is not None else function.body
    for statement in body:
        match statement:
            # Current and historical builders hand completed entries to this same transport API.
            case ast.Assign(value=ast.Call(func=ast.Name(id="_prepare_review_context"))):
                break
            # The budget is returned as telemetry. The builder emits the complete prompt.
            case ast.Assign(targets=[ast.Name(id="budget")], value=ast.Call(func=ast.Name(id="_review_prompt_budget_tokens"))):
                continue
        for item in ast.walk(statement):
            match item:
                case ast.Assign(targets=[ast.Subscript(value=ast.Name(id="prompts"))], value=ast.Dict() as entry) | ast.Return(value=ast.Dict() as entry):
                    if isinstance(item, ast.Return) and not returns_entry:
                        continue
                    # The same entry also carries estimates and other delivery diagnostics.
                    # Keep expanded role entries plus the fields that select a reader, its access and its prompt.
                    fields = [(key, value) for key, value in zip(entry.keys, entry.values)
                              if key is None or (isinstance(key, ast.Constant)
                                                 and key.value in ("prompt", "context_access", "subagent_type"))]
                    entry.keys = [key for key, _ in fields]
                    entry.values = [value for _, value in fields]
        sections.append(statement)
    return sections


def _codex_review_messages(statements: list[ast.stmt]) -> list[ast.stmt]:
    """Retain conditions and their branches only when they determine a message sent to a reviewer."""
    messages: list[ast.stmt] = []
    for statement in statements:
        match statement:
            case ast.Assign(targets=[ast.Name(id="message")]) | ast.AugAssign(target=ast.Name(id="message")):
                messages.append(statement)
            case ast.If():
                yes = _codex_review_messages(statement.body)
                no = _codex_review_messages(statement.orelse)
                if yes or no:
                    messages.append(ast.If(test=statement.test, body=yes, orelse=no))
            case ast.While():
                # Loop progress, retries and host operations do not select a role's output contract.
                messages.extend(_codex_review_messages(statement.body))
    return messages


def _review_ast(value: Any) -> Any:
    """Use named syntax fields. Empty optional fields differ across supported Python versions."""
    if isinstance(value, ast.AST):
        fields = {key: _review_ast(item) for key, item in ast.iter_fields(value) if item is not None and item != []}
        return [type(value).__name__, fields]
    if isinstance(value, list):
        return [_review_ast(item) for item in value]
    return repr(value)  # Python literals include bytes, complex numbers and Ellipsis.


@lru_cache(maxsize=32)
def _cached_review_rules(path: Path, script: str, expected_sha: str, *stat_key: int) -> str:
    """Read declarations as data. An archived file must match the original admission's file entry."""
    raw = path.read_bytes()
    if expected_sha and hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Archived review rules differ from the admitted script")
    try:
        statements = ast.parse(raw).body
    except SyntaxError as exc:
        raise ValueError(f"Cannot read reviewer rules from {script}: {exc.msg}") from exc
    declarations: dict[str, list[ast.AST]] = {}
    for node in statements:
        match node:
            case ast.Assign(targets=[ast.Name(id=name)], value=value) | ast.AnnAssign(target=ast.Name(id=name), value=value) if value:
                declarations.setdefault(name, []).append(value)
            case ast.ClassDef() if script == "codex_review_host.py":
                # Only the developer instructions attached to a new thread define reviewer rules.
                for mapping in (item for item in ast.walk(node) if isinstance(item, ast.Dict)):
                    for key, field in zip(mapping.keys, mapping.values):
                        if isinstance(key, ast.Constant) and key.value == "developerInstructions":
                            declarations.setdefault("developerInstructions", []).append(field)
            case ast.FunctionDef(name="build_review_prompts" | "build_adversarial_review_prompts" | "build_role_review_prompts"):
                declarations[node.name] = _review_prompt_entries(node)
            case ast.FunctionDef(name="_budget_review_prompt" | "_role_prompt_entry"):
                declarations[node.name] = _review_prompt_entries(node, returns_entry=True)
            case ast.FunctionDef(name="_review_one"):
                declarations.setdefault(node.name, []).extend(_codex_review_messages(node.body))
            case ast.FunctionDef(name=name) if name not in _REVIEW_INPUT_APIS:
                # Index helpers without hashing them until reached from a review entry point.
                declarations.setdefault(name, []).extend(node.body[1:] if ast.get_docstring(node) is not None else node.body)
            # The registry also installs schemas for role reviewers and hunters, then adds
            # the common discarded-candidate contract to every participating reviewer.
            case ast.Expr(value=ast.Call(func=ast.Attribute(value=ast.Name(id="AGENT_OUTPUT_SCHEMAS"), attr="update"))):
                declarations.setdefault("AGENT_OUTPUT_SCHEMAS", []).append(node)
            case ast.For(iter=ast.Name(id="REVIEWER_PARAPHRASE_AGENTS")):
                declarations.setdefault("AGENT_OUTPUT_SCHEMAS", []).append(node)

    # Include values referenced by the rules (e.g. the configured paraphrase length).
    # AST values omit comments, indentation and line locations throughout this closure.
    pending = list(REVIEW_RULE_SOURCES[script])
    selected: dict[str, list[Any]] = {}
    while pending:
        name = pending.pop()
        if name in selected or name not in declarations:
            continue
        expressions = declarations[name]
        selected[name] = [_review_ast(value) for value in expressions]
        pending.extend(ref.id for value in expressions for ref in ast.walk(value) if isinstance(ref, ast.Name))
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def legacy_review_scripts(root: Path) -> dict[str, dict[str, Any]]:
    """Reproduce the script entries included in pre-#704 review policy fingerprints."""
    paths = (path for ext in ("py", "sh") for path in (root / ".map/scripts").rglob(f"*.{ext}") if path.is_file())
    return {name: review_file_entry(name, root) for name in (path.relative_to(root).as_posix() for path in paths)}


def atomic_write_text(path: Path, content: str) -> None:
    """Publish UTF-8 text, preserving the caller's line endings."""
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically publish exact bytes through an invocation-unique sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(content)
        temporary_path.replace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except OSError:
            pass


def sanitize_branch_name(branch: str) -> str:
    """Normalize a branch name for safe use as a filesystem path component.

    Replaces ``/`` and any non-``[a-zA-Z0-9_.-]`` character with ``-``,
    collapses runs of hyphens, and strips leading/trailing hyphens. Refuses
    path-traversal patterns (``..`` anywhere, or a leading ``.``) by
    returning ``"default"``. Empty input also yields ``"default"``. Non-empty
    names stripped entirely by normalization use ``branch-<sha256>`` so
    successfully resolved Unicode branches do not share the fallback scope.
    """
    if not isinstance(branch, str):
        return "default"
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or ("branch-" + hashlib.sha256(branch.encode("utf-8")).hexdigest() if branch else "default")


def get_branch_name() -> str:
    """Get sanitized git branch name.

    Returns the current git branch with unsafe characters replaced by hyphens,
    including an unborn branch before its first commit. Detached HEAD retains
    the historical 'HEAD' scope.
    Warns on stderr and falls back to 'default' on any error (not in a git repo, git not installed, etc.).
    """
    try:
        # Symbolic HEAD exists even before the branch has its first commit.
        # rev-parse retains the historical detached-HEAD fallback.
        for command in (
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            ["rev-parse", "--abbrev-ref", "HEAD"],
        ):
            result = subprocess.run(
                ["git", *command],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                break
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- fallback warning follows; raw Git errors may contain sensitive paths
        pass
    print("MAP warning: could not determine Git branch; using .map/default/ for workflow artifacts.", file=sys.stderr)
    return "default"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shared MAP workflow utilities")
    parser.add_argument("command", choices=["branch"], help="print the current artifact branch scope")
    parser.parse_args()
    print(get_branch_name())
