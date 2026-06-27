#!/usr/bin/env python3
"""
MAP Hook Recursion-Guard Linter

Enforces the ``MAP_INVOKED_BY`` recursion-guard contract documented in
``.claude/references/hook-patterns.md``. Every hook under the scanned roots is
classified into exactly one class:

  - REQUIRE_GUARD: must early-exit on ``MAP_INVOKED_BY`` as the FIRST statement
    of its entry function (Python) or before any input/tooling (shell).
  - FORBID_GUARD:  must NOT contain a ``MAP_INVOKED_BY``-conditioned early-exit
    anywhere (a guard here would silently disable a safety/workflow gate).

A hook with no classification entry is a hard error (forces the author to
classify it). Position is verified, not just presence: a guard placed after a
side-effecting statement fails — including a module-scope assignment whose RHS
performs I/O (e.g. ``data = sys.stdin.read()``) and a shell ``VAR=$(...)``
command substitution before the guard.

Anti-obfuscation hardening: a FORBID_GUARD hook must reference ``MAP_INVOKED_BY``
exactly zero times at the RAW SOURCE level (a plain substring scan, including
comments and substrings of a larger string), so an indirect guard such as
``flag = "MAP_INVOKED_BY"; if os.environ.get(flag): sys.exit(0)``, a stray
comment, or an embedded mention cannot slip past — and the linter agrees
byte-for-byte with ``tests/test_hook_patterns.py``. For REQUIRE_GUARD shell
hooks, guard *detection* still strips inline comments first, so a prose
``# ... MAP_INVOKED_BY ...`` note is never mistaken for a real guard.

Scans BOTH dev roots, including Codex (INV-A4):
  - .claude/hooks/
  - .codex/hooks/

Template copies (src/mapify_cli/templates/) are validated by
``make render-templates`` + ``tests/test_hook_patterns.py`` over both trees, so
this dev-only tool intentionally does not scan them and is itself not synced.

Usage:
    python scripts/lint-hooks.py [--root DIR ...] [--self-test]

Exit codes:
    0  all scanned hooks conform
    1  one or more violations (missing/misplaced/forbidden guard, or
       unclassified hook)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent

# Default dev roots to scan (INV-A4: both, including Codex).
DEFAULT_ROOTS = [
    REPO_ROOT / ".claude" / "hooks",
    REPO_ROOT / ".codex" / "hooks",
]

# Classification, keyed by file BASENAME so the Codex twin resolves identically.
REQUIRE_GUARD = {
    "context-meter.py",
    "map-token-meter.py",
    "workflow-context-injector.py",
    "detect-clarification-triggers.py",
    "ralph-iteration-logger.py",
    "ralph-context-pruner.py",
    "pre-compact-save-transcript.py",
    "end-of-turn.sh",
    "scrub-internal-ids.py",
    "map-memory-capture.py",
    "map-memory-endmark.py",
    "map-memory-finalize.py",
    "map-memory-recall.py",
}
FORBID_GUARD = {
    "safety-guardrails.py",
    "workflow-gate.py",
    "post-compact-context.py",
}

# Files in a hooks dir that are not themselves MAP_INVOKED_BY recursion-guarded
# event hooks.
#   - README.md / __init__.py: not executable hooks at all.
#   - map-statusline.py: a Claude Code ``statusLine`` render command, not a
#     settings.json event hook. The harness owns its invocation cadence and it
#     NEVER runs inside a MAP-spawned subprocess (subagents have no status line),
#     so the recursion-guard contract does not apply. It must also stay
#     guard-free: a MAP_INVOKED_BY early-exit would print nothing and blank the
#     status row, which violates its never-blank output contract.
IGNORED_BASENAMES = {"README.md", "__init__.py", "map-statusline.py"}

ENV_FLAG = "MAP_INVOKED_BY"


class Colors:
    # Only the codes this linter actually emits are kept (no dead YELLOW/BLUE).
    RED = "\033[91m"
    GREEN = "\033[92m"
    BOLD = "\033[1m"
    END = "\033[0m"


# --------------------------------------------------------------------------- #
# Python AST helpers
# --------------------------------------------------------------------------- #
def _test_references_flag(test: ast.expr) -> bool:
    """True if the If-test references the MAP_INVOKED_BY env flag."""
    return any(
        isinstance(node, ast.Constant) and node.value == ENV_FLAG
        for node in ast.walk(test)
    )


def _stmt_exits(stmt: ast.stmt) -> bool:
    """True if a statement (or nested node) exits/returns the process/function."""
    for node in ast.walk(stmt):
        if isinstance(node, ast.Return):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            # sys.exit(...) / os._exit(...)
            if isinstance(func, ast.Attribute) and func.attr in {"exit", "_exit"}:
                return True
            # bare exit(...) / quit(...)
            if isinstance(func, ast.Name) and func.id in {"exit", "quit"}:
                return True
        if isinstance(node, ast.Raise):
            return True
    return False


def is_recursion_guard(node: ast.AST) -> bool:
    """True if ``node`` is an ``if <MAP_INVOKED_BY ...>: <exit/return>`` guard.

    The exit/return may live in either branch — ``if FLAG: sys.exit(0)`` and the
    inverted ``if not FLAG: ... else: sys.exit(0)`` are both guards. Checking
    ``orelse`` as well as ``body`` (a) recognises the inverted REQUIRE idiom
    instead of mis-reporting it as MISSING, and (b) strengthens the FORBID scan
    so an else-branch bypass cannot slip past.
    """
    if not isinstance(node, ast.If):
        return False
    if not _test_references_flag(node.test):
        return False
    return any(_stmt_exits(s) for s in node.body) or any(
        _stmt_exits(s) for s in node.orelse
    )


def _strip_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return body without a leading docstring Expr, if present."""
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_side_effect_free_assignment(stmt: ast.stmt) -> bool:
    """True if a module-level assignment is a plain constant definition.

    Only literal/constant RHS values count as "constant definitions" the guard
    may follow. An assignment whose RHS performs I/O or runs tooling
    (``data = sys.stdin.read()``) is NOT skippable — the guard must precede it,
    so we stop the module-scope scan there. Detected by the presence of any
    ``Call``/``Await``/``Yield`` node in the RHS.
    """
    if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
        return False
    value = stmt.value  # AnnAssign may be annotation-only (value is None)
    if value is None:
        return True
    return not any(
        isinstance(node, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom))
        for node in ast.walk(value)
    )


def _find_entry_body(tree: ast.Module) -> tuple[list[ast.stmt], str]:
    """Return (entry-function body without docstring, label).

    Prefers a top-level ``def main(...)`` / ``async def main(...)``. Falls back
    to module scope after the import/constant block when there is no main()
    (Decision 4 in the spec).
    """
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        ):
            return _strip_leading_docstring(node.body), "main()"
    # Module-scope fallback: skip the leading docstring, imports and plain
    # constant assignments — the guard must be the first executable statement.
    # A side-effecting assignment RHS (e.g. a stdin read) is NOT a constant and
    # stops the scan, so a guard placed after it is correctly flagged misplaced.
    body = _strip_leading_docstring(tree.body)
    idx = 0
    for stmt in body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            idx += 1
            continue
        if _is_side_effect_free_assignment(stmt):
            idx += 1
            continue
        break
    return body[idx:], "module scope"


# --------------------------------------------------------------------------- #
# Shell helpers
# --------------------------------------------------------------------------- #
# Lines permitted BEFORE the shell guard: shebang, comments, blanks, `set ...`,
# and simple VAR=value assignments. Anything else is an executable command and
# means the guard is misplaced (runs after input/tooling).
#
# The VAR=value branch deliberately forbids command substitution (``$(...)`` and
# backticks): ``OUT=$(curl ...)`` / ``RESPONSE=$(cat /dev/stdin)`` RUN a
# subprocess (I/O / tooling) before the guard, so they are NOT harmless
# assignments. Variable expansion (``$VAR``, ``${VAR}``) stays allowed. The
# value charset is "anything but a backtick/newline, or a ``$`` not followed by
# ``(``".
_SH_PREAMBLE_RE = re.compile(
    r"""^\s*(
        \#.*            # comment / shebang
      | set\s.*         # set -euo pipefail etc.
      | [A-Za-z_][A-Za-z0-9_]*=(?:[^`\n$]|\$(?!\())*   # VAR=value, no command substitution
    )?\s*$""",
    re.VERBOSE,
)
_SH_GUARD_LINE_RE = re.compile(rf"{ENV_FLAG}.*\bexit\b|\bexit\b.*{ENV_FLAG}")


def _sh_code(line: str) -> str:
    """Return the executable portion of a shell line (strip inline comments).

    Prevents a prose comment like ``exit 0  # MAP_INVOKED_BY note`` from being
    mistaken for a real guard.
    """
    return line.split("#", 1)[0]


def _first_flag_lineno(source: str) -> int:
    """1-based line of the first raw ``ENV_FLAG`` occurrence (0 if none)."""
    return next(
        (i for i, ln in enumerate(source.splitlines(), 1) if ENV_FLAG in ln), 0
    )


# --------------------------------------------------------------------------- #
# Linter
# --------------------------------------------------------------------------- #
class HookLinter:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []  # (relpath, message)
        self.checked = 0

    def error(self, path: Path, message: str) -> None:
        rel = self._rel(path)
        self.errors.append((rel, message))

    @staticmethod
    def _rel(path: Path) -> str:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)

    # -- per-file checks ---------------------------------------------------- #
    def check_python(self, path: Path, klass: str) -> None:
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - defensive
            self.error(path, f"could not parse: {exc}")
            return

        if klass == "FORBID_GUARD":
            flagged = False
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and is_recursion_guard(node):
                    self.error(
                        path,
                        f"FORBID_GUARD hook must NOT contain a {ENV_FLAG} "
                        f"early-exit (line {node.lineno}) — it would disable "
                        f"the gate for MAP-spawned subagents.",
                    )
                    flagged = True
            # Catch-all (spec AC-2: zero matches), aligned BYTE-FOR-BYTE with
            # tests/test_hook_patterns.py::test_forbid_hook_has_zero_flag_references
            # (``ENV_FLAG not in source``): a raw-source substring scan catches an
            # indirect-variable guard, a comment mention, AND the flag embedded in
            # a larger string constant — all of which the AST If-test / exact
            # ``Constant == ENV_FLAG`` scan misses. Without this, the linter and
            # the pytest gate could disagree on the same FORBID hook.
            if not flagged and ENV_FLAG in source:
                lineno = _first_flag_lineno(source)
                self.error(
                    path,
                    f"FORBID_GUARD hook must contain zero {ENV_FLAG} "
                    f"references; found one at line {lineno} (comment, stray "
                    f"reference, or possible indirect/obfuscated guard).",
                )
            return

        # REQUIRE_GUARD: guard must be the first statement of the entry point.
        entry_body, label = _find_entry_body(tree)
        if not entry_body:
            self.error(path, f"REQUIRE_GUARD hook has empty {label}; no guard.")
            return
        first = entry_body[0]
        if not is_recursion_guard(first):
            # Distinguish "missing entirely" from "present but misplaced".
            if any(is_recursion_guard(n) for n in ast.walk(tree)):
                self.error(
                    path,
                    f"REQUIRE_GUARD guard is present but MISPLACED — it must be "
                    f"the first statement of {label} (after the docstring, "
                    f"before any I/O), found a {type(first).__name__} first.",
                )
            else:
                self.error(
                    path,
                    f"REQUIRE_GUARD hook is MISSING the {ENV_FLAG} early-exit as "
                    f"the first statement of {label}.",
                )

    def check_shell(self, path: Path, klass: str) -> None:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()

        if klass == "FORBID_GUARD":
            # Same raw-source substring rule as check_python's FORBID branch and
            # the pytest gate: zero textual references (incl. comments).
            if ENV_FLAG in source:
                self.error(
                    path,
                    f"FORBID_GUARD shell hook must contain zero {ENV_FLAG} "
                    f"references; found one at line {_first_flag_lineno(source)}.",
                )
            return

        guard_idx = next(
            (i for i, ln in enumerate(lines) if _SH_GUARD_LINE_RE.search(_sh_code(ln))),
            None,
        )

        # REQUIRE_GUARD shell hook.
        if guard_idx is None:
            self.error(
                path,
                f"REQUIRE_GUARD shell hook is MISSING the {ENV_FLAG} early-exit.",
            )
            return
        for i in range(guard_idx):
            if not _SH_PREAMBLE_RE.match(lines[i]):
                self.error(
                    path,
                    f"REQUIRE_GUARD shell guard is MISPLACED — executable line "
                    f'{i + 1} ("{lines[i].strip()}") runs before the guard '
                    f"(line {guard_idx + 1}); the guard must precede all "
                    f"input/tooling.",
                )
                return

    def check_file(self, path: Path) -> None:
        name = path.name
        if name in IGNORED_BASENAMES:
            return
        if path.suffix not in {".py", ".sh"}:
            return

        if name in REQUIRE_GUARD:
            klass = "REQUIRE_GUARD"
        elif name in FORBID_GUARD:
            klass = "FORBID_GUARD"
        else:
            self.error(
                path,
                "UNCLASSIFIED hook — add it to REQUIRE_GUARD or FORBID_GUARD in "
                "scripts/lint-hooks.py (and hook-patterns.md).",
            )
            return

        self.checked += 1
        if path.suffix == ".py":
            self.check_python(path, klass)
        else:
            self.check_shell(path, klass)

    def run(self, roots: list[Path]) -> int:
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.iterdir()):
                if path.is_file():
                    self.check_file(path)

        if self.errors:
            print(
                f"{Colors.RED}{Colors.BOLD}Hook lint failed "
                f"({len(self.errors)} violation(s)):{Colors.END}"
            )
            for rel, message in self.errors:
                print(f"  {Colors.RED}✗{Colors.END} {rel} — {message}")
            return 1

        print(
            f"{Colors.GREEN}✓ All {self.checked} hooks conform to the "
            f"{ENV_FLAG} recursion-guard contract.{Colors.END}"
        )
        return 0


# --------------------------------------------------------------------------- #
# Self-test: prove every failure mode exits non-zero (AC-5 / VC2 fixtures)
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    import tempfile

    cases: list[tuple[str, str, str]] = [
        # (basename, content, why-it-must-fail)
        (
            "context-meter.py",  # REQUIRE_GUARD but guard missing
            'import os, sys\n\ndef main() -> None:\n    print("io")\n',
            "REQUIRE_GUARD missing guard",
        ),
        (
            "map-token-meter.py",  # REQUIRE_GUARD but guard misplaced (after IO)
            'import os, sys\n\ndef main() -> None:\n    print("io")\n'
            '    if os.environ.get("MAP_INVOKED_BY"):\n        sys.exit(0)\n',
            "REQUIRE_GUARD misplaced guard",
        ),
        (
            "safety-guardrails.py",  # FORBID_GUARD but contains a guard
            'import os, sys\n\ndef main() -> None:\n'
            '    if os.environ.get("MAP_INVOKED_BY"):\n        sys.exit(0)\n',
            "FORBID_GUARD contains guard",
        ),
        (
            "brand-new-hook.py",  # unclassified
            'def main() -> None:\n    pass\n',
            "unclassified hook",
        ),
        (
            "end-of-turn.sh",  # REQUIRE_GUARD shell, guard after a command
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'git status\n[ -n "${MAP_INVOKED_BY:-}" ] && exit 0\n',
            "shell guard misplaced",
        ),
        (
            "workflow-gate.py",  # FORBID_GUARD with an INDIRECT/obfuscated guard
            'import os, sys\n\nFLAG = "MAP_INVOKED_BY"\n\ndef main() -> None:\n'
            "    if os.environ.get(FLAG):\n        sys.exit(0)\n",
            "FORBID_GUARD indirect-variable guard",
        ),
        (
            "end-of-turn.sh",  # REQUIRE_GUARD shell: only flag mention is a comment
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            "# exit 0 here if MAP_INVOKED_BY (note only — not a real guard)\n"
            "git status\n",
            "shell guard present only in a comment",
        ),
        (
            "end-of-turn.sh",  # REQUIRE_GUARD shell: command substitution before guard
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'RESPONSE=$(cat /dev/stdin)\n'
            '[ -n "${MAP_INVOKED_BY:-}" ] && exit 0\n',
            "shell guard after a VAR=$(...) command substitution",
        ),
        (
            "context-meter.py",  # REQUIRE_GUARD module-scope: stdin read before guard
            'import os, sys\n\n'
            'data = sys.stdin.read()\n'
            'if os.environ.get("MAP_INVOKED_BY"):\n    sys.exit(0)\n'
            'print(data)\n',
            "module-scope guard after a side-effecting (stdin-read) assignment",
        ),
    ]
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "hooks"
        for basename, content, why in cases:
            root.mkdir(parents=True, exist_ok=True)
            f = root / basename
            f.write_text(content, encoding="utf-8")
            linter = HookLinter()
            rc = linter.run([root])
            f.unlink()
            status = "PASS" if rc != 0 else "FAIL"
            if rc == 0:
                ok = False
            color = Colors.GREEN if rc != 0 else Colors.RED
            print(f"  {color}[{status}]{Colors.END} expected-fail: {why} (rc={rc})")

        # And conformant fixtures must pass (rc == 0) — one per accepted shape,
        # so the happy path of every branch (sync main, async main, module
        # scope after a constant, and shell) is exercised, not just the
        # failure modes.
        good_cases: list[tuple[str, str, str]] = [
            (
                "context-meter.py",
                'import os, sys\n\ndef main() -> None:\n'
                '    if os.environ.get("MAP_INVOKED_BY"):\n        sys.exit(0)\n'
                '    print("io")\n',
                "conformant sync main()",
            ),
            (
                "map-token-meter.py",
                'import asyncio, os, sys\n\nasync def main() -> None:\n'
                '    if os.environ.get("MAP_INVOKED_BY"):\n        sys.exit(0)\n'
                '    print("io")\n\nasyncio.run(main())\n',
                "conformant async main()",
            ),
            (
                "ralph-context-pruner.py",
                'import os, sys\n\nTHRESHOLD = 1000\n'
                'if os.environ.get("MAP_INVOKED_BY"):\n    sys.exit(0)\n'
                'print(sys.stdin.read())\n',
                "conformant module-scope guard after a constant assignment",
            ),
            (
                "end-of-turn.sh",
                '#!/usr/bin/env bash\nset -euo pipefail\n'
                '[ -n "${MAP_INVOKED_BY:-}" ] && exit 0\ngit status\n',
                "conformant shell guard before any tooling",
            ),
        ]
        for basename, content, why in good_cases:
            root.mkdir(parents=True, exist_ok=True)
            good = root / basename
            good.write_text(content, encoding="utf-8")
            rc = HookLinter().run([root])
            good.unlink()
            if rc != 0:
                ok = False
            color = Colors.GREEN if rc == 0 else Colors.RED
            status = "PASS" if rc == 0 else "FAIL"
            print(f"  {color}[{status}]{Colors.END} expected-pass: {why} (rc={rc})")

    if ok:
        print(f"{Colors.GREEN}✓ self-test: all failure modes detected.{Colors.END}")
        return 0
    print(f"{Colors.RED}✗ self-test FAILED.{Colors.END}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint MAP hooks against the MAP_INVOKED_BY recursion-guard contract."
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        dest="roots",
        help="Hook directory to scan (repeatable). Defaults to .claude/hooks "
        "and .codex/hooks.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in fixtures proving every failure mode exits non-zero.",
    )
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    roots = args.roots if args.roots else DEFAULT_ROOTS
    return HookLinter().run(roots)


if __name__ == "__main__":
    sys.exit(main())
