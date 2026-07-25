"""Shared pytest fixtures for all test files."""

import os
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


# Worktree-vs-editable-install guard.
#
# When the test session runs from a git worktree (e.g. .warp/worktrees/<feature>/)
# while an editable `pip install -e .` is still pointing at the main repo
# checkout, `import mapify_cli` resolves against the OTHER tree — silently
# importing stale code. Same trap hits `subprocess.Popen([sys.executable, …])`
# helpers that spawn a fresh interpreter inheriting only PYTHONPATH.
#
# Fix: prepend `<this-repo>/src` to both sys.path (for in-process imports) and
# PYTHONPATH (so test-spawned subprocesses inherit the same priority). Idempotent
# — repeated entries are de-duplicated, so re-importing conftest is a no-op.
_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.is_dir():
    _src_str = str(_REPO_SRC)
    if _src_str not in sys.path:
        sys.path.insert(0, _src_str)
    _existing_pp = os.environ.get("PYTHONPATH", "")
    _pp_parts = [p for p in _existing_pp.split(os.pathsep) if p and p != _src_str]
    os.environ["PYTHONPATH"] = os.pathsep.join([_src_str, *_pp_parts])


@pytest.fixture(autouse=True)
def _restore_cwd():
    """Restore working directory after each test.

    Many tests call os.chdir(tmp_path) without cleanup. This fixture
    ensures the CWD is always restored so subsequent tests (especially
    those using relative paths like .claude/hooks/) are not affected.
    """
    original = os.getcwd()
    yield
    os.chdir(original)


# Pytest finds fixtures via module-namespace lookup, which Pylance/Pyright
# can't see — without this sentinel the IDE flags `_restore_cwd` as
# "not accessed". The reference is a no-op at runtime.
_ = _restore_cwd
