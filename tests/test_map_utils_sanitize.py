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
from pathlib import Path

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
_SPEC = importlib.util.spec_from_file_location("map_utils_under_test", _MAP_UTILS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
sanitize_branch_name = _MODULE.sanitize_branch_name


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
