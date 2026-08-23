"""The Python 3.11 floor is declared, checked at install time, and self-reporting.

Three halves of one contract:

1. ``pyproject.toml`` declares ``requires-python >= 3.11`` (installer-level).
2. ``mapify init`` refuses to install when the ``python3`` a shebang resolves is
   older than that, and says so by version (:mod:`mapify_cli.python_runtime`).
3. Every shipped file with a ``#!/usr/bin/env python3`` shebang carries the
   version guard, so an old interpreter reports the version instead of raising
   ``ImportError: cannot import name 'UTC' from 'datetime'``.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.python_runtime import (
    MINIMUM_PYTHON,
    SKIP_ENV_VAR,
    InterpreterInfo,
    check_hook_python,
    detect_hook_interpreter,
    format_problem,
    minimum_python_str,
    skip_requested,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEBANG = "#!/usr/bin/env python3"
GUARD_CONDITION = f"sys.version_info < ({MINIMUM_PYTHON[0]}, {MINIMUM_PYTHON[1]})"
TEMPLATES_SRC = REPO_ROOT / "src" / "mapify_cli" / "templates_src"
GUARD_PARTIAL = "_partials/python-version-guard.py.jinja"
DENY_SELECTOR = 'guard_mode = "deny"'

# The blocking PreToolUse gates (FORBID_GUARD): a hook whose only job is to refuse
# unsafe tool calls must fail CLOSED when it cannot run, or the guardrail silently
# turns into "allow". Every other shipped executable fails open. Keyed by basename
# because each of these is rendered into two or more trees.
FAIL_CLOSED_BASENAMES = frozenset({"safety-guardrails.py", "workflow-gate.py"})

# Every tree that ships or serves executable Python: the jinja sources, the dev
# working set, and both installer payloads.
SHEBANG_ROOTS = (
    REPO_ROOT / "src" / "mapify_cli" / "templates_src",
    REPO_ROOT / "src" / "mapify_cli" / "templates",
    REPO_ROOT / ".claude",
    REPO_ROOT / ".codex",
    REPO_ROOT / ".map",
)

# Gitignored local state that nests a full checkout or a virtualenv inside the
# roots above: this repo's own worktree-isolation and detached-review features
# write whole checkouts under `.claude/worktrees/` and `.map/<branch>/`, each
# potentially carrying a pre-guard snapshot of every hook plus a `.venv` full of
# third-party shebang files. None of it is shipped surface; sweeping it in makes
# the scan fail on any dogfooding machine while CI stays green.
EXCLUDED_PARTS = frozenset(
    {
        "__pycache__",
        "worktrees",
        "detached-review",
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
    }
)


def _shebang_files() -> list[Path]:
    found: list[Path] = []
    for root in SHEBANG_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py*")):
            if path.suffix not in {".py", ".jinja"}:
                continue
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            try:
                first = path.read_text(encoding="utf-8").split("\n", 1)[0]
            except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
                continue
            if first.strip() == SHEBANG:
                found.append(path)
    return found


# --------------------------------------------------------------------------- #
# 1. Declared floor, single source of truth
# --------------------------------------------------------------------------- #
def test_pyproject_declares_the_same_floor() -> None:
    """``requires-python`` must not drift from :data:`MINIMUM_PYTHON`."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml must declare requires-python"
    assert match.group(1) == f">={minimum_python_str()}"


def test_cli_import_guard_agrees_on_the_floor() -> None:
    """``_python_guard`` runs before the 3.11-only imports and uses the same tuple."""
    guard = (REPO_ROOT / "src" / "mapify_cli" / "_python_guard.py").read_text(
        encoding="utf-8"
    )
    assert GUARD_CONDITION in guard

    init_source = (REPO_ROOT / "src" / "mapify_cli" / "__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(init_source)
    imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and node.col_offset == 0
    ]
    guard_index = next(
        i
        for i, node in enumerate(imports)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "_python_guard" for alias in node.names)
    )
    datetime_index = next(
        i
        for i, node in enumerate(imports)
        if isinstance(node, ast.ImportFrom) and node.module == "datetime"
    )
    assert guard_index < datetime_index, (
        "_python_guard must be imported before `from datetime import UTC`, "
        "otherwise the ImportError wins and the version is never named."
    )


def test_partial_guard_agrees_on_the_floor() -> None:
    partial = (
        REPO_ROOT
        / "src"
        / "mapify_cli"
        / "templates_src"
        / "_partials"
        / "python-version-guard.py.jinja"
    ).read_text(encoding="utf-8")
    assert GUARD_CONDITION in partial


# --------------------------------------------------------------------------- #
# 2. Every shipped executable self-reports the version
# --------------------------------------------------------------------------- #
def test_shebang_files_are_discovered() -> None:
    """Guard against a silently empty scan making the checks below vacuous."""
    files = _shebang_files()
    assert len(files) >= 60, f"expected the shebang scan to find files, got {files}"


def test_shebang_scan_skips_nested_worktrees_and_venvs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gitignored nested checkouts and venvs must not leak into the scan.

    `.claude/worktrees/<name>/` (worktree isolation) and `.map/<branch>/`
    detached-review copies hold pre-guard snapshots of every hook plus whole
    virtualenvs; asserting the guard against those fails on any machine that
    has ever run the worktree features, while a fresh CI clone stays green.
    """
    root = tmp_path / "tree"
    (root / "hooks").mkdir(parents=True)
    shipped = root / "hooks" / "shipped.py"
    shipped.write_text(f"{SHEBANG}\n", encoding="utf-8")
    for stray in (
        "worktrees/old-checkout/hooks/stale-hook.py",
        ".venv/lib/python3.11/site-packages/mypy/stubgen.py",
        "detached-review/hooks/copy.py",
        "node_modules/pkg/cli.py",
    ):
        stray_path = root / stray
        stray_path.parent.mkdir(parents=True)
        stray_path.write_text(f"{SHEBANG}\n", encoding="utf-8")

    monkeypatch.setitem(globals(), "SHEBANG_ROOTS", (root,))
    assert _shebang_files() == [shipped]


@pytest.mark.parametrize("path", _shebang_files(), ids=lambda p: str(p.name))
def test_every_shebang_file_carries_the_version_guard(path: Path) -> None:
    """A ``#!/usr/bin/env python3`` file must name the version floor itself."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jinja":
        assert "_partials/python-version-guard.py.jinja" in text, (
            f"{path} ships a python3 shebang but does not include the version "
            "guard partial"
        )
        return
    assert GUARD_CONDITION in text, (
        f"{path} ships a python3 shebang without the version guard — an old "
        "python3 would fail with an ImportError that never mentions the version. "
        "Add the include to its .jinja source and run `make render-templates`."
    )


@pytest.mark.parametrize(
    "relpath",
    [
        ".claude/hooks/pre-compact-save-transcript.py",
        ".claude/hooks/ralph-iteration-logger.py",
        ".claude/hooks/ralph-context-pruner.py",
        ".claude/hooks/workflow-context-injector.py",
    ],
)
def test_guard_precedes_the_utc_import(relpath: str) -> None:
    """The four ``datetime.UTC`` hooks guard BEFORE the import that would fail."""
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    # Anchor at line start: the guard's own comment mentions the import by name.
    utc_import = re.search(r"^from datetime import UTC", text, re.MULTILINE)
    assert utc_import, f"{relpath} no longer imports UTC"
    assert text.index(GUARD_CONDITION) < utc_import.start()


def _render_guard(guard_mode: str | None = None) -> str:
    """Render the guard partial the way the renderer does, in one of its two modes."""
    from mapify_cli.delivery.template_renderer import get_environment

    env = get_environment(TEMPLATES_SRC)
    context = {} if guard_mode is None else {"guard_mode": guard_mode}
    return env.get_template(GUARD_PARTIAL).render(**context)


def _run_guard(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Execute a rendered guard under an interpreter that reports 3.9."""
    script = tmp_path / "guard_probe.py"
    script.write_text(
        "import sys\n"
        "sys.version_info = (3, 9, 6)\n"  # simulate the stock macOS interpreter
        + body,
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )


def _guard_block(text: str) -> str:
    """Return just the guard's ``if`` block from a rendered file.

    Slices from the guard condition to the first dedented line, so a match inside
    the block cannot be confused with the hook's own ``deny()`` further down.
    """
    lines = text[text.index(GUARD_CONDITION) :].splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if line and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return "\n".join(block)


def test_fail_open_guard_reports_version_and_exits_nonzero_under_old_python(
    tmp_path: Path,
) -> None:
    """Default mode: name the version, exit 1 (non-blocking), decide nothing."""
    proc = _run_guard(tmp_path, _render_guard())
    assert proc.returncode == 1
    assert "Python 3.11 or newer" in proc.stderr
    assert "Python 3.9" in proc.stderr
    assert proc.stdout == "", "a fail-open guard must not emit a hook decision"


def test_fail_closed_guard_denies_the_tool_call_under_old_python(
    tmp_path: Path,
) -> None:
    """``guard_mode="deny"``: a gate that cannot run blocks instead of allowing.

    Exit 0 + a structured ``permissionDecision`` is how a PreToolUse hook blocks;
    exiting 1 here would let the tool call through with the guardrail absent.
    """
    proc = _run_guard(tmp_path, _render_guard("deny"))
    assert proc.returncode == 0
    assert "Python 3.11 or newer" in proc.stderr
    payload = json.loads(proc.stdout)["hookSpecificOutput"]
    assert payload["hookEventName"] == "PreToolUse"
    assert payload["permissionDecision"] == "deny"
    reason = payload["permissionDecisionReason"]
    assert "Python 3.11 or newer" in reason
    assert "Python 3.9" in reason


@pytest.mark.parametrize("path", _shebang_files(), ids=lambda p: str(p.name))
def test_guard_mode_matches_the_hook_class(path: Path) -> None:
    """Only the FORBID_GUARD gates fail closed -- in every tree they render into."""
    text = path.read_text(encoding="utf-8")
    fail_closed = path.name.removesuffix(".jinja") in FAIL_CLOSED_BASENAMES

    if path.suffix == ".jinja":
        assert (DENY_SELECTOR in text) is fail_closed, (
            f"{path}: {DENY_SELECTOR!r} must be set for blocking PreToolUse gates "
            "and for nothing else"
        )
        return

    block = _guard_block(text)
    if fail_closed:
        assert '"permissionDecision": "deny"' in block, (
            f"{path} is a blocking gate but its version guard fails open -- an old "
            "python3 would let the tool call through unguarded"
        )
        assert "sys.exit(0)" in block and "sys.exit(1)" not in block
    else:
        assert "sys.exit(1)" in block, f"{path} lost the fail-open guard exit"
        assert "permissionDecision" not in block, (
            f"{path} is not a blocking gate; it must not emit a deny decision"
        )


# --------------------------------------------------------------------------- #
# 3. Interpreter detection
# --------------------------------------------------------------------------- #
def test_detects_the_running_interpreter_without_a_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mapify_cli.python_runtime.shutil.which", lambda *_a, **_k: sys.executable
    )

    def _fail(*_args: object, **_kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("must not spawn a subprocess for our own interpreter")

    monkeypatch.setattr("mapify_cli.python_runtime.subprocess.run", _fail)
    info = detect_hook_interpreter()
    assert info.version == sys.version_info[:3]
    assert info.satisfies_minimum is True
    assert format_problem(info) is None


def test_missing_python3_is_a_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mapify_cli.python_runtime.shutil.which", lambda *_a, **_k: None
    )
    info = detect_hook_interpreter()
    assert info.found is False
    assert info.satisfies_minimum is False
    problem = format_problem(info)
    assert problem is not None
    assert "not found on PATH" in problem


def test_real_old_interpreter_is_probed_and_rejected(tmp_path: Path) -> None:
    """A stub ``python3`` that reports 3.9 must be read via subprocess and fail."""
    fake = tmp_path / "python3"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then printf "3.9.6"; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    info = detect_hook_interpreter(str(fake))
    assert info.version == (3, 9, 6)
    assert info.satisfies_minimum is False
    problem = format_problem(info)
    assert problem is not None
    assert "3.9.6" in problem
    assert "Python 3.11 or newer" in problem
    assert "--skip-python-check" in problem


def test_unknown_version_never_counts_as_satisfying() -> None:
    info = InterpreterInfo(
        executable="/usr/bin/python3", detection_error="probe exploded"
    )
    assert info.satisfies_minimum is False
    assert info.version_str == "unknown"
    problem = format_problem(info)
    assert problem is not None
    assert "probe exploded" in problem


def test_probe_failure_is_reported_not_raised(tmp_path: Path) -> None:
    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    fake.chmod(0o755)
    info = detect_hook_interpreter(str(fake))
    assert info.version is None
    assert info.detection_error is not None
    assert "failed the version probe" in info.detection_error


def test_shadowed_env_interpreter_is_reported() -> None:
    """`uvx` prepends its ephemeral bin to PATH; the message must say it was skipped."""
    info = InterpreterInfo(
        executable="/usr/bin/python3",
        version=(3, 9, 6),
        shadowed="/tmp/uv-cache/bin/python3",
    )
    problem = format_problem(info)
    assert problem is not None
    assert "/tmp/uv-cache/bin/python3 was skipped" in problem


def test_own_environment_bin_is_excluded_only_for_virtualenvs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mapify_cli import python_runtime

    monkeypatch.setattr(python_runtime.sys, "prefix", "/env")
    monkeypatch.setattr(python_runtime.sys, "base_prefix", "/env")
    assert python_runtime._own_environment_bin_dirs() == set()

    monkeypatch.setattr(python_runtime.sys, "prefix", "/env/.venv")
    monkeypatch.setattr(python_runtime.sys, "base_prefix", "/usr")
    assert python_runtime._own_environment_bin_dirs() != set()


def _fake_python(directory: Path, version: str = "3.9.6") -> Path:
    """A minimal executable that answers the version probe like a real python3."""
    directory.mkdir(parents=True, exist_ok=True)
    fake = directory / "python3"
    fake.write_text(
        f'#!/bin/sh\nif [ "$1" = "-c" ]; then printf "{version}"; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def test_empty_path_entry_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty PATH entry means "the current directory" -- to execvp and to us.

    Dropping it would make the check approve a *later* entry's interpreter while
    the installed hooks keep resolving the ``./python3`` sitting next to them.
    """
    from mapify_cli import python_runtime

    cwd = tmp_path / "cwd"
    _fake_python(cwd)
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(python_runtime.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(python_runtime.sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(python_runtime.sys, "executable", str(venv_bin / "python3"))

    kept = python_runtime._path_outside_own_environment(f"{os.pathsep}{venv_bin}")
    assert kept.split(os.pathsep)[0] == "", "the empty (current-directory) entry"
    assert str(venv_bin) not in kept, "our own venv bin must still be dropped"

    monkeypatch.setenv("PATH", f"{os.pathsep}{venv_bin}")
    info = python_runtime.detect_hook_interpreter()
    assert info.version == (3, 9, 6), "the ./python3 the hooks would run is the verdict"
    assert info.satisfies_minimum is False


def test_empty_path_entry_is_dropped_when_it_is_our_own_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-op side: cwd == our own venv bin, so the empty entry is ours to skip."""
    from mapify_cli import python_runtime

    venv_bin = tmp_path / "venv" / "bin"
    _fake_python(venv_bin)
    monkeypatch.chdir(venv_bin)
    monkeypatch.setattr(python_runtime.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(python_runtime.sys, "base_prefix", str(tmp_path))
    monkeypatch.setattr(python_runtime.sys, "executable", str(venv_bin / "python3"))

    kept = python_runtime._path_outside_own_environment(f"{os.pathsep}/usr/bin")
    assert kept.split(os.pathsep) == ["/usr/bin"]


def test_skip_env_var_bypasses_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("detection must not run when the skip flag is set")

    monkeypatch.setattr("mapify_cli.python_runtime.shutil.which", _fail)
    monkeypatch.setenv(SKIP_ENV_VAR, "1")
    assert skip_requested() is True
    assert check_hook_python() is None
    assert check_hook_python(skip=True) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("", False)],
)
def test_skip_env_var_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv(SKIP_ENV_VAR, value)
    assert skip_requested() is expected


# --------------------------------------------------------------------------- #
# 4. `mapify init` / `mapify check` behaviour
# --------------------------------------------------------------------------- #
def test_init_refuses_and_writes_nothing_when_python3_is_too_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SKIP_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "mapify_cli.python_runtime.detect_hook_interpreter",
        lambda *_a, **_k: InterpreterInfo(
            executable="/usr/bin/python3", version=(3, 9, 6)
        ),
    )
    target = tmp_path / "project"
    result = CliRunner().invoke(
        app, ["init", str(target), "--no-git", "--mcp", "none"]
    )
    # rich hard-wraps to the terminal width, so compare on collapsed whitespace.
    output = " ".join(result.output.split())
    assert result.exit_code == 1
    assert "3.9.6" in output
    assert "Python 3.11 or newer" in output
    assert not target.exists(), "init must not touch the filesystem before the gate"


def test_init_proceeds_with_skip_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SKIP_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "mapify_cli.python_runtime.detect_hook_interpreter",
        lambda *_a, **_k: InterpreterInfo(
            executable="/usr/bin/python3", version=(3, 9, 6)
        ),
    )
    target = tmp_path / "project"
    result = CliRunner().invoke(
        app,
        ["init", str(target), "--no-git", "--mcp", "none", "--skip-python-check"],
    )
    assert result.exit_code == 0, result.output
    assert (target / ".claude" / "hooks").is_dir()


def test_rejected_init_writes_no_workflow_log_even_with_debug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preflight runs before diagnostics: a refused init leaves nothing behind.

    ``--debug`` starts the workflow logger in ``Path.cwd()/.map/logs``, which is the
    one thing that could still write after the gate said no.
    """
    monkeypatch.delenv(SKIP_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mapify_cli.python_runtime.detect_hook_interpreter",
        lambda *_a, **_k: InterpreterInfo(
            executable="/usr/bin/python3", version=(3, 9, 6)
        ),
    )
    target = tmp_path / "project"
    result = CliRunner().invoke(
        app, ["init", str(target), "--no-git", "--mcp", "none", "--debug"]
    )
    assert result.exit_code == 1
    assert not target.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [], (
        "a rejected init must not create .map/logs/ in the current directory"
    )


def test_accepted_init_with_debug_still_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive path: once the preflight passes, --debug logging is unchanged."""
    monkeypatch.delenv(SKIP_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mapify_cli.python_runtime.detect_hook_interpreter",
        lambda *_a, **_k: InterpreterInfo(
            executable="/usr/bin/python3", version=(3, 12, 1)
        ),
    )
    target = tmp_path / "project"
    result = CliRunner().invoke(
        app, ["init", str(target), "--no-git", "--mcp", "none", "--debug"]
    )
    assert result.exit_code == 0, result.output
    logs = sorted((tmp_path / ".map" / "logs").glob("workflow_*.log"))
    assert logs, "an accepted init --debug must still write its workflow log"


def test_check_reports_the_hook_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mapify_cli.python_runtime.detect_hook_interpreter",
        lambda *_a, **_k: InterpreterInfo(
            executable="/usr/bin/python3", version=(3, 9, 6)
        ),
    )
    result = CliRunner().invoke(app, ["check"])
    assert "python3 on PATH" in result.output
    assert "Upgrade python3" in result.output
