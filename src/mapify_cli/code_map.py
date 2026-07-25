"""Optional local structural code-map provider for MAP research.

First slice: Python AST-backed deterministic fallback.  No external
binaries, MCP servers, or network access required.

Researchers can query "what functions/classes match <name>?" and receive
file/line evidence compatible with the existing ResearchEvidence contract,
reducing cold-start Glob/Grep/Read exploration loops.

Output is always ResearchEvidence-compatible JSON so it passes the
existing validate_research / research-eval pipeline unchanged.

Out of scope for this slice:
- Full multi-language tree-sitter implementation.
- Route recognition for all frameworks.
- Mandatory MCP installation or CodeGraph integration.
- Cloud indexing or transmitting source code outside the local machine.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeSymbol:
    """A single named symbol extracted from a source file."""

    name: str
    kind: str  # "function" | "class" | "method"
    path: str  # repo-relative POSIX path
    start_line: int
    end_line: int
    parent: str | None = None  # enclosing class name for methods


@dataclass
class CodeMapIndex:
    """In-memory symbol index built from parsing source files."""

    symbols: list[CodeSymbol] = field(default_factory=list)
    indexed_files: int = 0
    skipped_files: int = 0

    def search(self, query: str, max_results: int = 5) -> list[CodeSymbol]:
        """Return symbols whose name contains *query* (case-insensitive).

        Results are ranked: exact → prefix → contains.
        """
        q = query.lower()
        exact: list[CodeSymbol] = []
        prefix: list[CodeSymbol] = []
        contains: list[CodeSymbol] = []
        for sym in self.symbols:
            n = sym.name.lower()
            if n == q:
                exact.append(sym)
            elif n.startswith(q):
                prefix.append(sym)
            elif q in n:
                contains.append(sym)
        return (exact + prefix + contains)[:max_results]


@dataclass
class CodeMapQueryResult:
    """Result of a structural code-map query."""

    query: str
    # "ok" | "no_results" | "empty_index" | "error"
    status: str
    # "python_ast" | "none"
    search_method: str
    confidence: float
    relevant_locations: list[dict[str, Any]] = field(default_factory=list)
    search_stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_research_evidence(self) -> str:
        """Return ResearchEvidence-compatible JSON string.

        The ``relevant_locations`` list is compatible with
        :func:`mapify_cli.research_eval.parse_research_locations`: each
        entry carries ``path`` (repo-relative) and ``lines`` ([start, end]).
        """
        return json.dumps(
            {
                "relevant_locations": self.relevant_locations,
                "search_method": self.search_method,
                "confidence": self.confidence,
                "status": self.status,
                "search_stats": self.search_stats,
            }
        )


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class _SymbolVisitor(ast.NodeVisitor):
    """Collect function, async-function, and class definitions from an AST."""

    def __init__(self, rel_path: str) -> None:
        self._path = rel_path
        self._class_stack: list[str] = []
        self.symbols: list[CodeSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end_line = node.end_lineno or node.lineno
        self.symbols.append(
            CodeSymbol(
                name=node.name,
                kind="class",
                path=self._path,
                start_line=node.lineno,
                end_line=end_line,
            )
        )
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        end_line = node.end_lineno or node.lineno
        parent = self._class_stack[-1] if self._class_stack else None
        self.symbols.append(
            CodeSymbol(
                name=node.name,
                kind="method" if parent else "function",
                path=self._path,
                start_line=node.lineno,
                end_line=end_line,
                parent=parent,
            )
        )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------


def build_python_ast_index(root: Path) -> CodeMapIndex:
    """Build a :class:`CodeMapIndex` by parsing all ``*.py`` files under *root*.

    Files that cannot be parsed (SyntaxError, OSError) are silently skipped
    and counted in :attr:`CodeMapIndex.skipped_files`.

    Files that resolve outside *root* (e.g. symlinks pointing elsewhere) are
    also skipped — this is the unsafe-path safety guard.
    """
    index = CodeMapIndex()
    resolved_root = root.resolve()

    for py_file in sorted(root.rglob("*.py")):
        resolved_file = py_file.resolve()
        try:
            resolved_file.relative_to(resolved_root)
        except ValueError:
            # Resolves outside root — symlink or path-traversal attempt.
            index.skipped_files += 1
            continue

        rel = resolved_file.relative_to(resolved_root).as_posix()

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            index.skipped_files += 1
            continue

        visitor = _SymbolVisitor(rel)
        visitor.visit(tree)
        index.symbols.extend(visitor.symbols)
        index.indexed_files += 1

    return index


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_code_map(
    query: str,
    repo_root: Path,
    *,
    max_results: int = 5,
) -> CodeMapQueryResult:
    """Query the structural code map for symbols matching *query*.

    In this slice the provider is always the Python AST fallback: every
    ``*.py`` file under *repo_root* is parsed on demand and symbols are
    matched by name.  No persistent index or external binary is required.

    Args:
        query: Symbol name or keyword to search for.
        repo_root: Root of the repository to index.
        max_results: Maximum number of locations to return (capped at 5
            by the ResearchEvidence convention).

    Returns:
        :class:`CodeMapQueryResult` with status, locations, and search stats.
        Call :meth:`CodeMapQueryResult.as_research_evidence` for the
        ResearchEvidence-compatible JSON string that can be passed directly
        to :func:`mapify_cli.research_eval.parse_research_locations`.
    """
    if not repo_root.is_dir():
        return CodeMapQueryResult(
            query=query,
            status="error",
            search_method="none",
            confidence=0.0,
            warnings=[
                f"repo_root does not exist or is not a directory: {repo_root}"
            ],
        )

    index = build_python_ast_index(repo_root)

    if not index.symbols:
        return CodeMapQueryResult(
            query=query,
            status="empty_index",
            search_method="python_ast",
            confidence=0.0,
            search_stats={
                "indexed_files": index.indexed_files,
                "skipped_files": index.skipped_files,
                "total_symbols": 0,
            },
        )

    matches = index.search(query, max_results=max_results)

    relevant_locations: list[dict[str, Any]] = [
        {
            "path": sym.path,
            "lines": [sym.start_line, sym.end_line],
            "signature": (
                f"{sym.kind} {sym.name}"
                + (f" (in {sym.parent})" if sym.parent else "")
            ),
            "relevance": "exact" if sym.name.lower() == query.lower() else "partial",
        }
        for sym in matches
    ]

    return CodeMapQueryResult(
        query=query,
        status="ok" if matches else "no_results",
        search_method="python_ast",
        confidence=1.0 if matches else 0.0,
        relevant_locations=relevant_locations,
        search_stats={
            "indexed_files": index.indexed_files,
            "skipped_files": index.skipped_files,
            "total_symbols": len(index.symbols),
            "matches_found": len(matches),
        },
    )


def default_index_path(root: Path) -> Path:
    """Return the conventional path for a code-map index artifact.

    Clock-free: callers supply the timestamp when the path needs one.
    """
    return root / ".map" / "code-map" / "python-ast-index.json"
