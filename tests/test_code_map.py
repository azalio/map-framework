"""Tests for code_map — structural-discovery provider.

All tests are fixture-based (no live model calls, no external services).
Fixture data uses small in-memory Python source strings written to tmp_path.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.code_map import (
    CodeSymbol,
    _SymbolVisitor,
    build_python_ast_index,
    default_index_path,
    query_code_map,
)
from mapify_cli.research_eval import parse_research_locations

runner = CliRunner()

_FIXTURE_SOURCE = """\
class MyClass:
    def my_method(self, x: int) -> int:
        return x + 1

    async def async_method(self) -> None:
        pass


def top_level_function(a: str) -> str:
    return a.upper()


def another_function():
    pass
"""


def _write_fixture(tmp_path: Path, source: str = _FIXTURE_SOURCE) -> Path:
    py = tmp_path / "fixture.py"
    py.write_text(source, encoding="utf-8")
    return py


# ---------------------------------------------------------------------------
# VC1 — build_python_ast_index: extracts classes, functions, and methods
# ---------------------------------------------------------------------------


def test_vc1_extracts_class(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    names = [s.name for s in index.symbols]
    assert "MyClass" in names
    cls = next(s for s in index.symbols if s.name == "MyClass")
    assert cls.kind == "class"
    assert cls.parent is None


def test_vc1_extracts_method_with_parent(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    method = next(s for s in index.symbols if s.name == "my_method")
    assert method.kind == "method"
    assert method.parent == "MyClass"
    assert method.start_line > 0
    assert method.end_line >= method.start_line


def test_vc1_extracts_async_method(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    async_m = next(s for s in index.symbols if s.name == "async_method")
    assert async_m.kind == "method"
    assert async_m.parent == "MyClass"


def test_vc1_extracts_top_level_function(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    func = next(s for s in index.symbols if s.name == "top_level_function")
    assert func.kind == "function"
    assert func.parent is None


def test_vc1_indexed_files_count(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    assert index.indexed_files == 1
    assert index.skipped_files == 0


def test_vc1_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def fa(): pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def fb(): pass\n", encoding="utf-8")
    index = build_python_ast_index(tmp_path)
    assert index.indexed_files == 2
    names = [s.name for s in index.symbols]
    assert "fa" in names
    assert "fb" in names


def test_vc1_path_is_repo_relative_posix(tmp_path: Path) -> None:
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("def fn(): pass\n", encoding="utf-8")
    index = build_python_ast_index(tmp_path)
    sym = next(s for s in index.symbols if s.name == "fn")
    assert sym.path == "pkg/mod.py"
    assert "\\" not in sym.path


# ---------------------------------------------------------------------------
# VC2 — build_python_ast_index: handles malformed and unsafe files
# ---------------------------------------------------------------------------


def test_vc2_skips_malformed_python_file(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def ok(): pass\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def (broken:\n", encoding="utf-8")
    index = build_python_ast_index(tmp_path)
    assert index.indexed_files == 1
    assert index.skipped_files == 1
    assert any(s.name == "ok" for s in index.symbols)


def test_vc2_skips_symlink_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("def secret(): pass\n", encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    link = repo / "evil_link.py"
    link.symlink_to(outside / "secret.py")

    index = build_python_ast_index(repo)
    names = [s.name for s in index.symbols]
    assert "secret" not in names
    assert index.skipped_files == 1


def test_vc2_empty_directory_returns_empty_index(tmp_path: Path) -> None:
    index = build_python_ast_index(tmp_path)
    assert index.symbols == []
    assert index.indexed_files == 0
    assert index.skipped_files == 0


# ---------------------------------------------------------------------------
# VC3 — CodeMapIndex.search: ranking and max_results cap
# ---------------------------------------------------------------------------


def test_vc3_search_exact_match_first(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    # "my_method" is exact, "async_method" contains "method"
    results = index.search("my_method")
    assert results[0].name == "my_method"


def test_vc3_search_prefix_before_contains(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text(
        "def foo(): pass\ndef find_foo(): pass\ndef has_foo_bar(): pass\n",
        encoding="utf-8",
    )
    index = build_python_ast_index(tmp_path)
    results = index.search("foo")
    names = [r.name for r in results]
    assert names.index("foo") < names.index("find_foo")


def test_vc3_search_max_results_respected(tmp_path: Path) -> None:
    lines = "\n".join(f"def func_{i}(): pass" for i in range(20))
    (tmp_path / "many.py").write_text(lines, encoding="utf-8")
    index = build_python_ast_index(tmp_path)
    results = index.search("func", max_results=5)
    assert len(results) <= 5


def test_vc3_search_no_match_returns_empty(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    index = build_python_ast_index(tmp_path)
    results = index.search("zzz_not_a_real_symbol")
    assert results == []


# ---------------------------------------------------------------------------
# VC4 — query_code_map: success, empty_index, error, no_results
# ---------------------------------------------------------------------------


def test_vc4_query_success_returns_ok(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("my_method", tmp_path)
    assert result.status == "ok"
    assert result.search_method == "python_ast"
    assert result.confidence == 1.0
    assert len(result.relevant_locations) >= 1


def test_vc4_query_empty_dir_returns_empty_index(tmp_path: Path) -> None:
    result = query_code_map("anything", tmp_path)
    assert result.status == "empty_index"
    assert result.confidence == 0.0


def test_vc4_query_nonexistent_root_returns_error(tmp_path: Path) -> None:
    result = query_code_map("func", tmp_path / "does_not_exist")
    assert result.status == "error"
    assert result.confidence == 0.0
    assert result.warnings


def test_vc4_query_no_match_returns_no_results(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("zzz_not_real", tmp_path)
    assert result.status == "no_results"
    assert result.relevant_locations == []
    assert result.confidence == 0.0


def test_vc4_query_search_stats_present(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("my_method", tmp_path)
    stats = result.search_stats
    assert "indexed_files" in stats
    assert "total_symbols" in stats
    assert "matches_found" in stats
    assert stats["indexed_files"] >= 1


# ---------------------------------------------------------------------------
# VC5 — as_research_evidence: ResearchEvidence-compatible JSON
# ---------------------------------------------------------------------------


def test_vc5_as_research_evidence_is_valid_json(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("my_method", tmp_path)
    raw = result.as_research_evidence()
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


def test_vc5_as_research_evidence_has_relevant_locations(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("my_method", tmp_path)
    parsed = json.loads(result.as_research_evidence())
    assert "relevant_locations" in parsed
    locs = parsed["relevant_locations"]
    assert isinstance(locs, list)
    assert len(locs) >= 1


def test_vc5_relevant_locations_have_path_and_lines(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("my_method", tmp_path)
    for loc in result.relevant_locations:
        assert "path" in loc
        assert "lines" in loc
        assert isinstance(loc["lines"], list)
        assert len(loc["lines"]) == 2
        assert loc["lines"][0] <= loc["lines"][1]


def test_vc5_parse_research_locations_accepts_output(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = query_code_map("top_level_function", tmp_path)
    evidence = result.as_research_evidence()
    parsed = parse_research_locations(evidence)
    assert len(parsed.locations) >= 1
    assert parsed.malformed == ()


def test_vc5_empty_result_parse_research_locations_compatible(tmp_path: Path) -> None:
    result = query_code_map("anything", tmp_path)
    evidence = result.as_research_evidence()
    # parse_research_locations must not crash even on empty result
    parsed = parse_research_locations(evidence)
    assert parsed.locations == ()


# ---------------------------------------------------------------------------
# VC6 — max_results cap at 5
# ---------------------------------------------------------------------------


def test_vc6_max_results_default_5_cap(tmp_path: Path) -> None:
    lines = "\n".join(f"def method_{i}(): pass" for i in range(20))
    (tmp_path / "many.py").write_text(lines, encoding="utf-8")
    result = query_code_map("method", tmp_path, max_results=5)
    assert result.status == "ok"
    assert len(result.relevant_locations) <= 5


def test_vc6_max_results_custom_respected(tmp_path: Path) -> None:
    lines = "\n".join(f"def method_{i}(): pass" for i in range(20))
    (tmp_path / "many.py").write_text(lines, encoding="utf-8")
    result = query_code_map("method", tmp_path, max_results=3)
    assert len(result.relevant_locations) <= 3


# ---------------------------------------------------------------------------
# VC7 — default_index_path: path helper
# ---------------------------------------------------------------------------


def test_vc7_default_index_path_structure(tmp_path: Path) -> None:
    path = default_index_path(tmp_path)
    assert path == tmp_path / ".map" / "code-map" / "python-ast-index.json"


# ---------------------------------------------------------------------------
# VC8 — _SymbolVisitor: direct unit tests
# ---------------------------------------------------------------------------


def test_vc8_visitor_extracts_symbols() -> None:
    import ast as _ast

    source = "class C:\n    def m(self): pass\n\ndef f(): pass\n"
    tree = _ast.parse(source)
    visitor = _SymbolVisitor("test.py")
    visitor.visit(tree)
    names = {s.name for s in visitor.symbols}
    assert names == {"C", "m", "f"}


def test_vc8_visitor_method_has_correct_parent() -> None:
    import ast as _ast

    source = "class Foo:\n    def bar(self): pass\n"
    tree = _ast.parse(source)
    visitor = _SymbolVisitor("test.py")
    visitor.visit(tree)
    method = next(s for s in visitor.symbols if s.name == "bar")
    assert method.parent == "Foo"
    assert method.kind == "method"


def test_vc8_visitor_function_has_no_parent() -> None:
    import ast as _ast

    source = "def standalone(): pass\n"
    tree = _ast.parse(source)
    visitor = _SymbolVisitor("test.py")
    visitor.visit(tree)
    func = visitor.symbols[0]
    assert func.parent is None
    assert func.kind == "function"


# ---------------------------------------------------------------------------
# VC9 — CodeSymbol dataclass
# ---------------------------------------------------------------------------


def test_vc9_code_symbol_fields() -> None:
    sym = CodeSymbol(
        name="my_func",
        kind="function",
        path="src/mod.py",
        start_line=10,
        end_line=20,
    )
    assert sym.name == "my_func"
    assert sym.kind == "function"
    assert sym.path == "src/mod.py"
    assert sym.start_line == 10
    assert sym.end_line == 20
    assert sym.parent is None


def test_vc9_code_symbol_is_frozen() -> None:
    sym = CodeSymbol(name="f", kind="function", path="a.py", start_line=1, end_line=5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        sym.name = "g"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# VC10 — CLI: mapify code-map query
# ---------------------------------------------------------------------------


def test_vc10_cli_query_exits_0_on_match(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = runner.invoke(
        app,
        ["code-map", "query", "my_method", "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert len(payload["relevant_locations"]) >= 1


def test_vc10_cli_query_exits_1_on_no_match(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    result = runner.invoke(
        app,
        ["code-map", "query", "zzz_no_such_symbol", "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 1


def test_vc10_cli_query_exits_1_on_empty_repo(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["code-map", "query", "anything", "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "empty_index"


def test_vc10_cli_out_flag_persists_report(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    out_file = tmp_path / "evidence.json"
    result = runner.invoke(
        app,
        [
            "code-map",
            "query",
            "my_method",
            "--repo-root",
            str(tmp_path),
            "--out",
            str(out_file),
        ],
    )
    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["status"] == "ok"


def test_vc10_cli_max_results_flag(tmp_path: Path) -> None:
    lines = "\n".join(f"def method_{i}(): pass" for i in range(10))
    (tmp_path / "many.py").write_text(lines, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "code-map",
            "query",
            "method",
            "--repo-root",
            str(tmp_path),
            "--max-results",
            "2",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["relevant_locations"]) <= 2
