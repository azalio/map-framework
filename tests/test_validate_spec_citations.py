"""Unit tests for .map/scripts/validate_spec_citations.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = REPO_ROOT / ".map" / "scripts" / "validate_spec_citations.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_spec_citations", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validator():
    return _load_validator()


def _write_spec(tmp_path: Path, body: str) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(body, encoding="utf-8")
    return spec


def _seed_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def test_passes_when_cited_line_contains_identifier(validator, tmp_path: Path):
    repo = _seed_repo(
        tmp_path,
        {"src/pkg/mod.py": "first\nIDENT_TOKEN = 1\nthird\n"},
    )
    spec = _write_spec(repo, "See `IDENT_TOKEN` at `src/pkg/mod.py:2` for details.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    assert result["total_citations"] == 1
    assert result["details"][0]["status"] == "ok"


def test_accepts_sentence_period_after_citation(validator, tmp_path: Path):
    repo = _seed_repo(tmp_path, {"src/pkg/mod.py": "first\nIDENT_TOKEN = 1\n"})
    spec = _write_spec(repo, "See `IDENT_TOKEN` at `src/pkg/mod.py:2`.")

    result = validator.validate_spec(spec, repo)

    assert result["passed"] is True
    assert result["total_citations"] == 1


def test_flags_stale_citation_when_identifier_moved(validator, tmp_path: Path):
    repo = _seed_repo(
        tmp_path,
        {"src/pkg/mod.py": "blank\nblank\nblank\nIDENT_TOKEN = 1\n"},
    )
    # Spec still claims IDENT_TOKEN is at line 2, but it is actually at line 4.
    spec = _write_spec(repo, "Look at `IDENT_TOKEN` at `src/pkg/mod.py:2`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "stale-citation"
    assert result["failures"][0]["identifier"] == "IDENT_TOKEN"


def test_flags_missing_file(validator, tmp_path: Path):
    spec = _write_spec(tmp_path, "See `Symbol` at `does/not/exist.py:10`.")
    result = validator.validate_spec(spec, tmp_path)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
    assert "does not exist" in result["failures"][0]["reason"]


def test_flags_out_of_range_line(validator, tmp_path: Path):
    repo = _seed_repo(tmp_path, {"src/tiny.py": "only\n"})
    spec = _write_spec(repo, "See `only` at `src/tiny.py:50`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
    assert "out of range" in result["failures"][0]["reason"]


def test_flags_reversed_range(validator, tmp_path: Path):
    """Citations like `file.py:20-10` are illegal — end below start."""
    repo = _seed_repo(
        tmp_path,
        {"src/wide.py": "\n".join(f"line{i}" for i in range(1, 30)) + "\n"},
    )
    spec = _write_spec(repo, "See `line5` at `src/wide.py:20-10` (typo).")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
    assert "reversed range" in result["failures"][0]["reason"]


def test_flags_out_of_bounds_start_with_in_bounds_end(validator, tmp_path: Path):
    """Citation `file.py:50-5` on a 10-line file: start fails, end is in range.

    The naive bounds check `end_no > len(lines)` would let this through —
    end_no (5) is within bounds; only start_no (50) is out of range. After
    the reversed-range guard runs (5 < 50 → already caught), this is also
    caught by the independent `line_no > len(lines)` check.
    """
    repo = _seed_repo(
        tmp_path,
        {"src/short.py": "\n".join(f"line{i}" for i in range(1, 11)) + "\n"},
    )
    spec = _write_spec(repo, "See `line3` at `src/short.py:50-5`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"


def test_line_range_is_validated_against_end_line(validator, tmp_path: Path):
    repo = _seed_repo(
        tmp_path,
        {"src/range.py": "\n".join(["pad"] * 10 + ["TOKEN here"] + ["pad"] * 4) + "\n"},
    )
    spec = _write_spec(repo, "Block at `TOKEN` `src/range.py:9-12` covers it.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    assert result["details"][0]["status"] == "ok"
    assert result["details"][0]["end_line"] == 12


def test_no_identifier_within_window_returns_ok_no_identifier(
    validator, tmp_path: Path
):
    repo = _seed_repo(tmp_path, {"docs/page.md": "x\ny\nz\n"})
    # Citation isolated from any backticked identifier nearby.
    spec = _write_spec(
        tmp_path,
        "Reference: docs/page.md:2 — see the full doc for more.",
    )
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    assert result["details"][0]["status"] == "ok-no-identifier"


def test_skips_external_paths(validator, tmp_path: Path):
    spec = _write_spec(
        tmp_path,
        "Roadmap: `/Users/somebody/.claude/plans/roadmap.md:42` (external).",
    )
    result = validator.validate_spec(spec, tmp_path)
    assert result["passed"] is True
    assert result["details"][0]["status"] == "skipped"


def test_recognised_extensions_only(validator, tmp_path: Path):
    repo = _seed_repo(tmp_path, {"binary": "raw", "Makefile": "rule:\n\t@echo\n"})
    spec = _write_spec(repo, "See binary:5 and Makefile:1 — both citations.")
    result = validator.validate_spec(spec, repo)
    # Neither path has a recognised extension; the regex deliberately ignores them.
    assert result["total_citations"] == 0
    assert result["passed"] is True


def test_resolves_path_escapes_repo_root(validator, tmp_path: Path):
    repo = tmp_path / "inside"
    repo.mkdir()
    (tmp_path / "outside.py").write_text("escape\n", encoding="utf-8")
    spec = _write_spec(repo, "See `escape` at `../outside.py:1`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
    assert "escapes repo root" in result["failures"][0]["reason"]


def test_picks_nearest_backticked_identifier_on_left(validator, tmp_path: Path):
    repo = _seed_repo(
        tmp_path,
        {"a.py": "first line\nALPHA\n", "b.py": "first line\nBETA\n"},
    )
    spec = _write_spec(
        tmp_path,
        "We use `BETA` at `b.py:2` while `ALPHA` at `a.py:2` is a sibling.",
    )
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    # Both citations should resolve to their nearest preceding backticked symbol.
    by_path = {d["path"]: d for d in result["details"]}
    assert by_path["b.py"]["identifier"] == "BETA"
    assert by_path["a.py"]["identifier"] == "ALPHA"


# ---------------------------------------------------------------------------
# Bare-basename resolution (#301)
# ---------------------------------------------------------------------------


def test_resolves_unique_bare_basename_no_identifier(validator, tmp_path: Path):
    """A bare filename that is unique in the repo resolves to the full path."""
    repo = _seed_repo(tmp_path, {"sub/pkg/mod.py": "line1\nline2\nline3\n"})
    spec = _write_spec(repo, "See mod.py:2 for context.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    detail = result["details"][0]
    assert detail["status"] == "ok-no-identifier"
    assert detail["path"] == "mod.py"
    assert detail["resolved_to"] == "sub/pkg/mod.py"


def test_resolves_unique_bare_basename_with_identifier(validator, tmp_path: Path):
    """Bare-basename resolution still validates the identifier in the cited line."""
    repo = _seed_repo(tmp_path, {"deep/api.ts": "first\nMY_SYMBOL = 1\nthird\n"})
    spec = _write_spec(repo, "The `MY_SYMBOL` binding lives at `api.ts:2`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is True
    detail = result["details"][0]
    assert detail["status"] == "ok"
    assert detail["resolved_to"] == "deep/api.ts"


def test_bare_basename_stale_identifier_still_fails(validator, tmp_path: Path):
    """Resolved bare basename that fails identifier check is stale-citation."""
    repo = _seed_repo(tmp_path, {"deep/api.ts": "first\nOTHER = 1\nthird\n"})
    # MY_SYMBOL doesn't appear at line 2
    spec = _write_spec(repo, "The `MY_SYMBOL` binding lives at `api.ts:2`.")
    result = validator.validate_spec(spec, repo)
    assert result["passed"] is False
    detail = result["failures"][0]
    assert detail["status"] == "stale-citation"
    assert detail["resolved_to"] == "deep/api.ts"


def test_warns_on_ambiguous_bare_basename(validator, tmp_path: Path):
    """A bare filename that matches multiple files in the repo → warning, not error."""
    repo = _seed_repo(
        tmp_path,
        {
            "pkg_a/utils.py": "line1\nline2\n",
            "pkg_b/utils.py": "lineA\nlineB\n",
        },
    )
    spec = _write_spec(repo, "See utils.py:1 for the helper.")
    result = validator.validate_spec(spec, repo)
    # Ambiguous basename: should NOT hard-fail the plan
    assert result["passed"] is True
    detail = result["details"][0]
    assert detail["status"] == "warning"
    assert "ambiguous" in detail["reason"]
    # warnings list carries it
    assert len(result["warnings"]) == 1


def test_bare_basename_not_in_repo_is_error(validator, tmp_path: Path):
    """A bare filename that doesn't exist anywhere in the repo → error."""
    spec = _write_spec(tmp_path, "See phantom.py:1 for reference.")
    result = validator.validate_spec(spec, tmp_path)
    assert result["passed"] is False
    detail = result["failures"][0]
    assert detail["status"] == "error"
    # Error message should not say misleadingly "file does not exist at phantom.py"
    assert "phantom.py" in detail["reason"]


def test_full_path_missing_is_still_error(validator, tmp_path: Path):
    """An explicit repo-root-relative path that doesn't exist is a hard error."""
    spec = _write_spec(tmp_path, "See `TOKEN` at `src/does/not/exist.py:5`.")
    result = validator.validate_spec(spec, tmp_path)
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
    assert "does not exist" in result["failures"][0]["reason"]


def test_warnings_field_present_even_when_empty(validator, tmp_path: Path):
    """validate_spec always includes 'warnings' in output."""
    repo = _seed_repo(tmp_path, {"src/a.py": "x\n"})
    spec = _write_spec(repo, "See `x` at `src/a.py:1`.")
    result = validator.validate_spec(spec, repo)
    assert "warnings" in result
    assert result["warnings"] == []


def test_skip_dirs_excluded_from_basename_search(validator, tmp_path: Path):
    """Files inside .git / __pycache__ / node_modules are excluded from basename search."""
    # Put the real file inside a skip dir only — should not resolve
    repo = _seed_repo(tmp_path, {"node_modules/api.ts": "line1\nline2\n"})
    spec = _write_spec(repo, "See api.ts:1 here.")
    result = validator.validate_spec(spec, repo)
    # The only match is in node_modules → treated as not found → error
    assert result["passed"] is False
    assert result["failures"][0]["status"] == "error"
