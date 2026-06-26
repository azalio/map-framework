"""Unit tests for the internal-ID scrub engine (.map/scripts/scrub_internal_ids).

Two layers:
  * pure-function tests (no git) — token strip per comment leader, pure-marker
    line deletion, test rename + collision guard, scope restriction, residual;
  * git-scoped ``run()`` tests in a real temp repo — scope-safety (pre-existing
    IDs on untouched lines are never modified) and idempotency.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = (
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "scrub_internal_ids.py"
)


def _load_engine():
    # Suppress bytecode so importing a file inside a generated tree does not drop
    # __pycache__/*.pyc that the byte-identity render tests would flag.
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("scrub_internal_ids", ENGINE_PATH)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = prev


engine = _load_engine()


# --------------------------------------------------------------------------- #
# scrub_line — token strip / pure-marker deletion
# --------------------------------------------------------------------------- #
class TestScrubLine:
    def test_token_in_comment_is_stripped_line_kept(self) -> None:
        new, removed, residual = engine.scrub_line("// The rule (INV-7) is: x", False)
        assert new == "// The rule is: x"
        assert removed == ["INV-7"]
        assert residual == []

    def test_intent_comment_ac_stripped(self) -> None:
        new, _, _ = engine.scrub_line("# Intent: AC-3 validation", False)
        assert new == "# Intent: validation"

    def test_pure_marker_comment_line_deleted(self) -> None:
        new, removed, _ = engine.scrub_line("    // ST-001", False)
        assert new is None
        assert removed == ["ST-001"]

    def test_multiple_tokens_and_empty_brackets(self) -> None:
        new, removed, _ = engine.scrub_line("    # VC1 [AC-1]: condition", False)
        assert new == "    # condition"
        assert sorted(removed) == ["AC-1", "VC1"]

    def test_token_in_string_literal_stripped_code_line_kept(self) -> None:
        new, removed, _ = engine.scrub_line('    label = "INV-7"  # note', False)
        assert removed == ["INV-7"]
        assert new is not None and "INV-7" not in new
        assert "label =" in new  # the code itself is preserved

    def test_token_in_bare_code_is_left_untouched_and_reported(self) -> None:
        # `INV-7` contiguous in code position (not comment/string) -> residual.
        new, removed, residual = engine.scrub_line("    x = INV-7 + 1", False)
        assert new == "    x = INV-7 + 1"
        assert removed == []
        assert residual == ["INV-7"]

    def test_line_without_tokens_unchanged(self) -> None:
        new, removed, residual = engine.scrub_line("    return total  # ok", False)
        assert new == "    return total  # ok"
        assert removed == [] and residual == []

    def test_dashless_ac_hc_not_matched(self) -> None:
        # Conservative: dash-less AC1/HC1 are NOT treated as internal IDs.
        new, removed, _ = engine.scrub_line("    reg = AC1  # hardware AC1", False)
        assert removed == []
        assert new == "    reg = AC1  # hardware AC1"


# --------------------------------------------------------------------------- #
# renamed_test_identifier
# --------------------------------------------------------------------------- #
class TestRename:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("test_vc1_register", "test_register"),
            ("test_register_vc2", "test_register"),
            ("TestVC1Foo", "TestFoo"),
            ("TestVc10Bar", "TestBar"),
        ],
    )
    def test_vc_segment_dropped(self, name: str, expected: str) -> None:
        assert engine.renamed_test_identifier(name) == expected

    @pytest.mark.parametrize("name", ["test_register", "TestFoo", "test_vc1", "TestVC2"])
    def test_no_rename_when_unchanged_or_too_bare(self, name: str) -> None:
        # No vc segment, or removing it would collapse to a bare test prefix.
        assert engine.renamed_test_identifier(name) is None


# --------------------------------------------------------------------------- #
# scrub_text — whole-file orchestration
# --------------------------------------------------------------------------- #
class TestScrubText:
    def test_rename_strip_and_delete_together(self) -> None:
        text = "def test_vc1_register():\n    pass  # AC-3 note\n# ST-001\nkeep = 1\n"
        new, report = engine.scrub_text(text, None)
        assert "def test_register():" in new
        assert "# AC-3" not in new and "# note" in new
        assert "# ST-001" not in new  # pure-marker line deleted
        assert "keep = 1" in new
        assert report["renames"] == [{"old": "test_vc1_register", "new": "test_register"}]
        assert report["deleted"] == 1
        assert report["residual"] == []

    def test_scope_limits_edits(self) -> None:
        text = "# INV-1 keep\n# INV-2 strip\n"
        # Only line 2 is in scope -> line 1 is untouched.
        new, _ = engine.scrub_text(text, {2})
        assert "# INV-1 keep" in new
        assert "# INV-2" not in new

    def test_rename_collision_is_skipped_and_reported(self) -> None:
        text = "def test_register():\n    pass\n\ndef test_vc1_register():\n    pass\n"
        new, report = engine.scrub_text(text, None)
        # The target name already exists -> no rename, original kept, reported.
        assert "def test_vc1_register():" in new
        assert report["renames"] == []
        assert any(r["reason"] == "rename_collision" for r in report["residual"])

    def test_docstring_token_stripped(self) -> None:
        text = '"""Implements INV-7 single-writer."""\nx = 1\n'
        new, _ = engine.scrub_text(text, None)
        assert "INV-7" not in new
        assert "Implements" in new


# --------------------------------------------------------------------------- #
# run() — git-scoped behaviour
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "PATH": __import__("os").environ.get("PATH", "")},
    )
    return res.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    return repo


class TestRunGitScoped:
    def test_scope_safety_pre_existing_id_untouched(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        # Base commit: a pre-existing leaked ID the user "owns".
        src.write_text("# INV-1 pre-existing\nold = 1\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-m", "base")
        base = _git(git_repo, "rev-parse", "HEAD")
        # Run change: add a NEW leaked line; leave the pre-existing one alone.
        src.write_text("# INV-1 pre-existing\nold = 1\nnew = 2  # AC-3 leaked\n", encoding="utf-8")

        report = engine.run(git_repo, mode="clean", base=base, branch=None)

        assert report["status"] == "modified"
        result = src.read_text(encoding="utf-8")
        assert "# INV-1 pre-existing" in result  # untouched (not in run scope)
        assert "AC-3" not in result  # run-added leak stripped
        assert "new = 2" in result

    def test_idempotent_second_run_is_clean(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        src.write_text("base = 0\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-m", "base")
        base = _git(git_repo, "rev-parse", "HEAD")
        src.write_text("base = 0\n# ST-001\nrun = 1\n", encoding="utf-8")

        first = engine.run(git_repo, mode="clean", base=base, branch=None)
        assert first["status"] == "modified"
        second = engine.run(git_repo, mode="clean", base=base, branch=None)
        assert second["status"] == "clean"
        assert second["files_modified"] == []

    def test_scan_mode_does_not_mutate(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        src.write_text("base = 0\n", encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-m", "base")
        base = _git(git_repo, "rev-parse", "HEAD")
        src.write_text("base = 0\nrun = 1  # INV-7 leaked\n", encoding="utf-8")

        report = engine.run(git_repo, mode="scan", base=base, branch=None)
        assert report["status"] == "modified"  # would-modify
        assert "INV-7" in src.read_text(encoding="utf-8")  # but file untouched

    def test_unresolvable_base_is_no_op(self, git_repo: Path) -> None:
        # Explicit but non-existent base -> resolve_run_base returns None.
        report = engine.run(git_repo, mode="clean", base="deadbeef", branch=None)
        assert report["status"] == "no_base"
