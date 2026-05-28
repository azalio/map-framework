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
