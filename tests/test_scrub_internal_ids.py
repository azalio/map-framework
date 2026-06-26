"""Unit tests for the internal-ID scrub engine (.map/scripts/scrub_internal_ids).

Three layers:
  * pure-function tests (no git) — comment token strip per language leader,
    pure-marker deletion, test rename + collision, scope restriction;
  * corruption-avoidance tests derived from the adversarial probes — string
    literals, docstrings, markdown headings, and bare code are NEVER modified;
  * git-scoped ``run()`` tests in a real temp repo — scope-safety, idempotency,
    multi-language, and data-file skipping.
"""
from __future__ import annotations

import importlib.util
import os
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

PY = engine.syntax_for_ext(".py")
GO = engine.syntax_for_ext(".go")
MD = engine.syntax_for_ext(".md")
SQL = engine.syntax_for_ext(".sql")
C = engine.syntax_for_ext(".c")


# --------------------------------------------------------------------------- #
# scrub_line — comment token strip across languages
# --------------------------------------------------------------------------- #
class TestScrubLineComments:
    def test_hash_comment_token_stripped(self) -> None:
        new, removed, _ = engine.scrub_line("    return 1  # Intent: AC-3 validation", PY)
        assert new == "    return 1  # Intent: validation"
        assert removed == ["AC-3"]

    def test_slash_comment_token_stripped(self) -> None:
        new, removed, _ = engine.scrub_line("x := 1 // The rule (INV-7) is here", GO)
        assert new == "x := 1 // The rule is here"
        assert removed == ["INV-7"]

    def test_sql_dash_comment_stripped(self) -> None:
        new, _, _ = engine.scrub_line("SELECT 1 -- AC-3 covered", SQL)
        assert new == "SELECT 1 -- covered"

    def test_block_comment_token_stripped(self) -> None:
        new, _, _ = engine.scrub_line("int x; /* INV-7 holds */", C)
        assert "INV-7" not in new
        assert "holds" in new

    def test_html_comment_token_stripped(self) -> None:
        new, _, _ = engine.scrub_line("<!-- ST-001 internal -->", MD)
        assert new == "<!-- internal -->"

    def test_pure_marker_comment_line_deleted(self) -> None:
        new, removed, _ = engine.scrub_line("    # ST-001", PY)
        assert new is None
        assert removed == ["ST-001"]

    def test_multiple_tokens_and_empty_brackets(self) -> None:
        new, removed, _ = engine.scrub_line("    # VC1 [AC-1]: condition", PY)
        assert new == "    # condition"
        assert sorted(removed) == ["AC-1", "VC1"]


# --------------------------------------------------------------------------- #
# Corruption avoidance — derived from the adversarial probes
# --------------------------------------------------------------------------- #
class TestNoCorruption:
    def test_string_literal_is_never_modified(self) -> None:
        # A token that is a substring of a real value must survive intact.
        line = '    sku = "INV-7-special-sku"'
        new, removed, residual = engine.scrub_line(line, PY)
        assert new == line
        assert removed == []
        assert residual == ["INV-7"]  # reported, not removed

    def test_markdown_heading_is_not_a_comment(self) -> None:
        # In markdown, `#` is a heading, not a comment leader.
        line = "# AC-3 Compliance Heading"
        new, removed, _ = engine.scrub_line(line, MD)
        assert new == line
        assert removed == []

    def test_bare_code_token_left_and_reported(self) -> None:
        line = "    x = INV-7 + 1"
        new, removed, residual = engine.scrub_line(line, PY)
        assert new == line
        assert removed == []
        assert residual == ["INV-7"]

    def test_dashless_ac_hc_not_matched(self) -> None:
        line = "    reg = AC1  # hardware AC1"
        new, removed, _ = engine.scrub_line(line, PY)
        assert removed == []
        assert new == line

    def test_token_inside_string_with_hash_leader_not_treated_as_comment(self) -> None:
        # `#` inside a string is not a comment start; the token stays.
        line = '    label = "value # INV-7"'
        new, removed, _ = engine.scrub_line(line, PY)
        assert new == line
        assert removed == []

    def test_unsupported_syntax_strips_nothing(self) -> None:
        new, removed, _ = engine.scrub_line("anything INV-7 here", None)
        assert new == "anything INV-7 here"
        assert removed == []


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
        assert engine.renamed_test_identifier(name) is None


# --------------------------------------------------------------------------- #
# syntax_for_ext mapping
# --------------------------------------------------------------------------- #
class TestSyntaxMapping:
    @pytest.mark.parametrize("ext", [".py", ".sh", ".go", ".ts", ".rs", ".sql", ".md", ".yaml"])
    def test_known_extensions_have_syntax(self, ext: str) -> None:
        assert engine.syntax_for_ext(ext) is not None

    @pytest.mark.parametrize("ext", [".json", ".lock", ".csv", ".png", ".txt", ""])
    def test_data_and_unknown_extensions_skipped(self, ext: str) -> None:
        assert engine.syntax_for_ext(ext) is None


# --------------------------------------------------------------------------- #
# scrub_text — whole-file orchestration
# --------------------------------------------------------------------------- #
class TestScrubText:
    def test_rename_strip_and_delete_together(self) -> None:
        text = "def test_vc1_register():\n    pass  # AC-3 note\n# ST-001\nkeep = 1\n"
        new, report = engine.scrub_text(text, None, PY)
        assert "def test_register():" in new
        assert "# AC-3" not in new and "# note" in new
        assert "# ST-001" not in new  # pure-marker line deleted
        assert "keep = 1" in new
        assert report["renames"] == [{"old": "test_vc1_register", "new": "test_register"}]
        assert report["deleted"] == 1

    def test_scope_limits_edits(self) -> None:
        text = "# INV-1 keep\n# INV-2 strip\n"
        new, _ = engine.scrub_text(text, {2}, PY)
        assert "# INV-1 keep" in new
        assert "# INV-2" not in new

    def test_rename_collision_is_skipped_and_reported(self) -> None:
        text = "def test_register():\n    pass\n\ndef test_vc1_register():\n    pass\n"
        new, report = engine.scrub_text(text, None, PY)
        assert "def test_vc1_register():" in new
        assert report["renames"] == []
        assert any(r["reason"] == "rename_collision" for r in report["residual"])

    def test_docstring_token_is_left_intact(self) -> None:
        # Triple-quoted strings are NOT scrubbed (could be multi-line data).
        text = '"""Implements INV-7 single-writer."""\nx = 1\n'
        new, report = engine.scrub_text(text, None, PY)
        assert new == text
        assert any(r["token"] == "INV-7" for r in report["residual"])


# --------------------------------------------------------------------------- #
# run() — git-scoped behaviour
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return res.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    return repo


def _seed_base(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


class TestRunGitScoped:
    def test_scope_safety_pre_existing_id_untouched(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        base = _seed_base(git_repo, "mod.py", "# INV-1 pre-existing\nold = 1\n")
        src.write_text("# INV-1 pre-existing\nold = 1\nnew = 2  # AC-3 leaked\n", encoding="utf-8")

        report = engine.run(git_repo, mode="clean", base=base, branch=None)

        assert report["status"] == "modified"
        result = src.read_text(encoding="utf-8")
        assert "# INV-1 pre-existing" in result  # untouched (not in run scope)
        assert "AC-3" not in result  # run-added leak stripped
        assert "new = 2" in result

    def test_idempotent_second_run_is_clean(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        base = _seed_base(git_repo, "mod.py", "base = 0\n")
        src.write_text("base = 0\n# ST-001\nrun = 1\n", encoding="utf-8")

        first = engine.run(git_repo, mode="clean", base=base, branch=None)
        assert first["status"] == "modified"
        second = engine.run(git_repo, mode="clean", base=base, branch=None)
        assert second["status"] == "clean"
        assert second["files_modified"] == []

    def test_scan_mode_does_not_mutate(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        base = _seed_base(git_repo, "mod.py", "base = 0\n")
        src.write_text("base = 0\nrun = 1  # INV-7 leaked\n", encoding="utf-8")

        report = engine.run(git_repo, mode="scan", base=base, branch=None)
        assert report["status"] == "modified"  # would-modify
        assert "INV-7" in src.read_text(encoding="utf-8")  # but file untouched

    def test_unresolvable_base_is_no_op(self, git_repo: Path) -> None:
        report = engine.run(git_repo, mode="clean", base="deadbeef", branch=None)
        assert report["status"] == "no_base"

    def test_json_data_file_is_never_scrubbed(self, git_repo: Path) -> None:
        cfg = git_repo / "config.json"
        base = _seed_base(git_repo, "seed.txt", "seed\n")
        cfg.write_text('{\n  "label": "AC-3",\n  "note": "ST-001"\n}\n', encoding="utf-8")

        report = engine.run(git_repo, mode="clean", base=base, branch=None)
        assert "config.json" not in report["files_modified"]
        assert cfg.read_text(encoding="utf-8") == '{\n  "label": "AC-3",\n  "note": "ST-001"\n}\n'

    def test_markdown_heading_preserved_but_html_comment_scrubbed(self, git_repo: Path) -> None:
        md = git_repo / "notes.md"
        base = _seed_base(git_repo, "seed.txt", "seed\n")
        md.write_text("# AC-3 Heading\n<!-- ST-001 internal -->\n", encoding="utf-8")

        engine.run(git_repo, mode="clean", base=base, branch=None)
        result = md.read_text(encoding="utf-8")
        assert "# AC-3 Heading" in result  # heading is not a comment -> preserved
        assert "ST-001" not in result  # HTML comment scrubbed
        assert "<!-- internal -->" in result

    def test_string_literal_in_run_line_not_corrupted(self, git_repo: Path) -> None:
        src = git_repo / "mod.py"
        base = _seed_base(git_repo, "mod.py", "x = 0\n")
        src.write_text('x = 0\nsku = "INV-7-special-sku"  # ST-001 here\n', encoding="utf-8")

        engine.run(git_repo, mode="clean", base=base, branch=None)
        result = src.read_text(encoding="utf-8")
        assert '"INV-7-special-sku"' in result  # string value intact
        assert "ST-001" not in result  # comment scrubbed

    def test_multilanguage_run(self, git_repo: Path) -> None:
        base = _seed_base(git_repo, "seed.txt", "seed\n")
        (git_repo / "svc.go").write_text(
            "package svc\n// (INV-7) holds\nfunc TestVC1H(t *testing.T) {}\n", encoding="utf-8"
        )
        (git_repo / "q.sql").write_text("SELECT 1 -- AC-3 covered\n", encoding="utf-8")

        report = engine.run(git_repo, mode="clean", base=base, branch=None)
        go = (git_repo / "svc.go").read_text(encoding="utf-8")
        sql = (git_repo / "q.sql").read_text(encoding="utf-8")
        assert "INV-7" not in go and "func TestH(" in go
        assert "AC-3" not in sql and "SELECT 1" in sql
        assert {"file": "svc.go", "old": "TestVC1H", "new": "TestH"} in report["tests_renamed"]
