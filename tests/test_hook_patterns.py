"""Tests for the MAP_INVOKED_BY recursion-guard contract (Phase A).

Parametrized per-hook over BOTH the dev trees (.claude/hooks, .codex/hooks) and
the shipped template trees (src/mapify_cli/templates/hooks, .../codex/hooks), so
the guard (or its documented absence) cannot drift between copies.

Proves:
  - INV-A2: every REQUIRE_GUARD hook has a correctly-positioned MAP_INVOKED_BY
            early-exit (first entry-function statement, before any I/O).
  - INV-A1: every FORBID_GUARD hook contains NO such guard and, behaviorally,
            still denies a dangerous command when MAP_INVOKED_BY is set.

Classification and guard-detection logic are imported from scripts/lint-hooks.py
so the contract has a single source of truth.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Hook roots to validate: dev (Claude + Codex) and shipped templates (Claude + Codex).
HOOK_ROOTS = [
    REPO_ROOT / ".claude" / "hooks",
    REPO_ROOT / ".codex" / "hooks",
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "hooks",
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "codex" / "hooks",
]


def _load_lint_hooks():
    """Import scripts/lint-hooks.py (hyphenated filename) as a module."""
    path = REPO_ROOT / "scripts" / "lint-hooks.py"
    spec = importlib.util.spec_from_file_location("lint_hooks", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lh = _load_lint_hooks()


def _hook_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file()
        and p.suffix in {".py", ".sh"}
        and p.name not in lh.IGNORED_BASENAMES
    )


# Flat list of every classified hook file across every tree.
ALL_HOOKS = [path for root in HOOK_ROOTS for path in _hook_files(root)]
ALL_HOOK_IDS = [str(p.relative_to(REPO_ROOT)) for p in ALL_HOOKS]

FORBID_HOOKS = [p for p in ALL_HOOKS if p.name in lh.FORBID_GUARD]
FORBID_HOOK_IDS = [str(p.relative_to(REPO_ROOT)) for p in FORBID_HOOKS]


def test_hooks_were_discovered() -> None:
    """Guard against an empty parametrization silently passing."""
    assert ALL_HOOKS, "no hook files discovered in any tree"
    # Every tree — dev and shipped, Claude and Codex — must contribute hooks,
    # so a wiped tree cannot turn a parametrized check into a vacuous pass.
    roots_with_hooks = {p.parent for p in ALL_HOOKS}
    for root in HOOK_ROOTS:
        assert root in roots_with_hooks, f"no hooks discovered under {root}"


@pytest.mark.parametrize("hook_path", ALL_HOOKS, ids=ALL_HOOK_IDS)
def test_hook_is_executable(hook_path: Path) -> None:
    """Every hook .py/.sh must carry the executable bit in EVERY tree.

    Claude Code execs hooks directly via their shebang (the settings.json
    command is the bare path, e.g. ``"$CLAUDE_PROJECT_DIR"/.claude/hooks/x.py``),
    so a hook without +x fails at runtime with ``Permission denied`` — a failure
    that an interpreter-based test (``python3 <path>``) never reproduces. The
    bit is committed to git, propagated by ``make render-templates`` (the
    renderer force-sets +x for hooks), and re-applied by ``mapify init``
    (``create_hook_files``); this asserts the committed tree stays correct.
    """
    assert os.access(hook_path, os.X_OK), (
        f"hook {hook_path.relative_to(REPO_ROOT)} is not executable — the "
        "harness execs it via its shebang and will fail 'Permission denied'. "
        "Run `chmod +x` on the .jinja source and re-render."
    )


@pytest.mark.parametrize("hook_path", ALL_HOOKS, ids=ALL_HOOK_IDS)
def test_hook_conforms_to_guard_contract(hook_path: Path) -> None:
    """Every hook satisfies its class contract (INV-A1 / INV-A2) in every tree."""
    rel = hook_path.relative_to(REPO_ROOT)
    assert hook_path.name in (lh.REQUIRE_GUARD | lh.FORBID_GUARD), (
        f"{rel} is unclassified — add it to REQUIRE_GUARD/FORBID_GUARD in "
        f"scripts/lint-hooks.py"
    )
    linter = lh.HookLinter()
    linter.check_file(hook_path)
    assert not linter.errors, (
        f"{rel} violates the recursion-guard contract: "
        + "; ".join(msg for _, msg in linter.errors)
    )


@pytest.mark.parametrize("hook_path", FORBID_HOOKS, ids=FORBID_HOOK_IDS)
def test_forbid_hook_has_zero_flag_references(hook_path: Path) -> None:
    """INV-A1: a FORBID_GUARD hook references MAP_INVOKED_BY exactly zero times."""
    source = hook_path.read_text(encoding="utf-8")
    assert lh.ENV_FLAG not in source, (
        f"{hook_path.relative_to(REPO_ROOT)} must contain zero {lh.ENV_FLAG} "
        f"references — a guard here would disable the gate for MAP-spawned subagents."
    )


# safety-guardrails.py copies across all trees that contain it.
_SAFETY_HOOKS = [p for p in ALL_HOOKS if p.name == "safety-guardrails.py"]
_SAFETY_IDS = [str(p.relative_to(REPO_ROOT)) for p in _SAFETY_HOOKS]


@pytest.mark.parametrize("hook_path", _SAFETY_HOOKS, ids=_SAFETY_IDS)
@pytest.mark.parametrize("flag_set", [False, True], ids=["flag_unset", "flag_set"])
def test_deny_still_fires_with_flag(hook_path: Path, flag_set: bool) -> None:
    """INV-A1 (behavioral): the deny gate fires whether or not MAP_INVOKED_BY is set."""
    # Build the dangerous command from fragments so the parent session's own
    # safety hook does not block this test file / process.
    dangerous = "rm" + " -" + "rf" + " /"
    payload = {"tool_name": "Bash", "tool_input": {"command": dangerous}}

    env = dict(os.environ)
    if flag_set:
        env["MAP_INVOKED_BY"] = "nested-actor"
    else:
        env.pop("MAP_INVOKED_BY", None)

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    blob = (result.stdout or "") + (result.stderr or "")
    assert '"permissionDecision": "deny"' in blob, (
        f"{hook_path.relative_to(REPO_ROOT)} did not deny a dangerous command "
        f"with MAP_INVOKED_BY {'set' if flag_set else 'unset'}: {blob!r}"
    )


# --------------------------------------------------------------------------- #
# Doc/classification drift guard
# --------------------------------------------------------------------------- #
# The classification (REQUIRE_GUARD/FORBID_GUARD sets in scripts/lint-hooks.py)
# is the single machine-readable source of truth, but the same per-hook class is
# independently restated in prose tables across four shipped docs. Nothing else
# checks those tables against the sets, so a reclassified/added/dropped hook can
# silently drift. These tests fail loudly on any divergence.
HOOK_DOC_FILES = [
    REPO_ROOT / ".claude" / "hooks" / "README.md",
    REPO_ROOT / ".claude" / "references" / "hook-patterns.md",
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "hooks" / "README.md",
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "references" / "hook-patterns.md",
]
HOOK_DOC_IDS = [str(p.relative_to(REPO_ROOT)) for p in HOOK_DOC_FILES]


def _doc_classification(text: str) -> dict[str, set[str]]:
    """Map each hook basename mentioned in a doc TABLE to the class(es) it is
    shown under.

    Handles both doc shapes: README has a per-row ``Class`` column
    (``| `foo.py` | ... | REQUIRE_GUARD | ... |``); hook-patterns.md groups
    hooks under ``### REQUIRE_GUARD`` / ``### FORBID_GUARD`` section headings.
    Only ``| ...`` table rows with backtick-wrapped ``*.py``/``*.sh`` names
    count, so prose mentions elsewhere never pollute the map.
    """
    found: dict[str, set[str]] = {}
    section: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if "REQUIRE_GUARD" in stripped:
                section = "REQUIRE_GUARD"
            elif "FORBID_GUARD" in stripped:
                section = "FORBID_GUARD"
            elif stripped.startswith("## "):
                section = None  # left the classification sections
            continue
        if not stripped.startswith("|"):
            continue
        if "REQUIRE_GUARD" in line:
            row_class: str | None = "REQUIRE_GUARD"
        elif "FORBID_GUARD" in line:
            row_class = "FORBID_GUARD"
        else:
            row_class = section
        if row_class is None:
            continue
        for token in re.findall(r"`([^`]+)`", line):
            if token.endswith((".py", ".sh")):
                found.setdefault(token, set()).add(row_class)
    return found


@pytest.mark.parametrize("doc_path", HOOK_DOC_FILES, ids=HOOK_DOC_IDS)
def test_doc_tables_match_classification(doc_path: Path) -> None:
    """Every doc table classifies each hook with EXACTLY its lint-hooks class."""
    assert doc_path.exists(), f"missing doc file {doc_path.relative_to(REPO_ROOT)}"
    found = _doc_classification(doc_path.read_text(encoding="utf-8"))
    rel = doc_path.relative_to(REPO_ROOT)
    for name in sorted(lh.REQUIRE_GUARD | lh.FORBID_GUARD):
        expected = "REQUIRE_GUARD" if name in lh.REQUIRE_GUARD else "FORBID_GUARD"
        assert name in found, (
            f"{rel}: hook '{name}' is classified in scripts/lint-hooks.py but "
            f"absent from this doc's tables (classification drift)."
        )
        assert found[name] == {expected}, (
            f"{rel}: hook '{name}' is listed as {sorted(found[name])} but "
            f"scripts/lint-hooks.py classifies it as {expected} (drift)."
        )
