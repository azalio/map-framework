"""Tests for src/mapify_cli/templates/map/scripts/map_utils.py.

The module ships as a script (loaded from ``.map/scripts/`` at runtime), so
it is not on ``sys.path`` and cannot be imported with a normal ``from … import``.
We load it directly from the templates path via ``importlib`` instead.

These tests focus on ``sanitize_branch_name`` because the orchestrator passes
``--branch`` straight into a filesystem path and a missing sanitiser would
allow path traversal via ``..``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_MAP_UTILS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
    / "map_utils.py"
)
_prev_no_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    _SPEC = importlib.util.spec_from_file_location("map_utils_under_test", _MAP_UTILS_PATH)
    assert _SPEC is not None and _SPEC.loader is not None
    _MODULE = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(_MODULE)
finally:
    sys.dont_write_bytecode = _prev_no_bytecode

sanitize_branch_name = _MODULE.sanitize_branch_name
atomic_write_text = _MODULE.atomic_write_text


class TestSanitizeBranchName:
    """Mirror of ``tests/test_ralph_state.py::TestSanitizeBranchName``.

    The two implementations must stay behaviour-compatible — the orchestrator
    and the ralph-state module both use the same ``.map/<branch>/`` layout,
    so a divergence would put state files in different directories for the
    same logical branch.
    """

    def test_simple_branch_passes_through(self) -> None:
        assert sanitize_branch_name("main") == "main"
        assert sanitize_branch_name("feature") == "feature"

    def test_slash_replaced_with_dash(self) -> None:
        assert sanitize_branch_name("feature/foo") == "feature-foo"
        assert sanitize_branch_name("fix/bug/issue") == "fix-bug-issue"

    def test_special_chars_replaced(self) -> None:
        assert sanitize_branch_name("fix/bug#123") == "fix-bug-123"
        assert sanitize_branch_name("feature@user") == "feature-user"

    def test_underscores_preserved(self) -> None:
        assert sanitize_branch_name("my_branch") == "my_branch"

    def test_runs_of_dashes_collapsed(self) -> None:
        assert sanitize_branch_name("a--b---c") == "a-b-c"

    def test_leading_trailing_dashes_stripped(self) -> None:
        assert sanitize_branch_name("-feature-") == "feature"

    @pytest.mark.parametrize(
        "evil",
        [
            "../etc/passwd",
            "..",
            "../..",
            "foo/../bar",
        ],
    )
    def test_path_traversal_returns_default(self, evil: str) -> None:
        # Any ``..`` segment is the security-critical case: without this guard
        # ``mapify init . --branch ../etc`` would let a path escape ``.map/``.
        assert sanitize_branch_name(evil) == "default"

    def test_leading_dot_returns_default(self) -> None:
        assert sanitize_branch_name(".hidden") == "default"

    def test_empty_returns_default(self) -> None:
        assert sanitize_branch_name("") == "default"
        assert sanitize_branch_name("---") == "default"

    def test_non_string_returns_default(self) -> None:
        # Defensive: if a caller hands us a non-string (e.g. None when an
        # argparse default leaks through), fall back instead of raising.
        assert sanitize_branch_name(None) == "default"  # type: ignore[arg-type]
        assert sanitize_branch_name(123) == "default"  # type: ignore[arg-type]


class TestAtomicWriteText:
    """Tests for the atomic_write_text helper (issue #448).

    Verifies that a cleanup OSError in the finally block does not mask the
    original replace() error -- the fix changed ``except FileNotFoundError``
    to ``except OSError`` so ALL cleanup errors are swallowed instead of only
    FileNotFoundError.
    """

    def test_writes_content_to_destination(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.json"
        atomic_write_text(dest, '{"ok": true}')
        assert dest.read_text(encoding="utf-8") == '{"ok": true}'

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "sub" / "dir" / "out.txt"
        atomic_write_text(dest, "hello")
        assert dest.read_text(encoding="utf-8") == "hello"

    def test_replace_error_propagates_not_masked_by_unlink_oserror(
        self, tmp_path: Path
    ) -> None:
        """If replace() fails, a subsequent OSError from unlink() must not mask it.

        Before the fix, the finally block caught only FileNotFoundError; any
        other OSError from unlink() would propagate and hide the replace() error.
        After the fix, OSError from cleanup is always swallowed, so the original
        replace() error reaches the caller.
        """
        dest = tmp_path / "target.json"
        replace_error = PermissionError("replace denied")
        unlink_error = PermissionError("unlink denied")

        def patched_replace(self: Path, target: object) -> Path:
            raise replace_error

        def patched_unlink(self: Path, missing_ok: bool = False) -> None:
            raise unlink_error

        with (
            patch.object(Path, "replace", patched_replace),
            patch.object(Path, "unlink", patched_unlink),
            pytest.raises(PermissionError) as exc_info,
        ):
            atomic_write_text(dest, "data")

        # The original replace() error must be what the caller sees, not the
        # unlink() error that occurred in cleanup.
        assert exc_info.value is replace_error, (
            "replace() error was masked by the unlink() cleanup error; "
            "expected the original PermissionError from replace() to propagate"
        )
