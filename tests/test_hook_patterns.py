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
    )
    blob = (result.stdout or "") + (result.stderr or "")
    assert '"permissionDecision": "deny"' in blob, (
        f"{hook_path.relative_to(REPO_ROOT)} did not deny a dangerous command "
        f"with MAP_INVOKED_BY {'set' if flag_set else 'unset'}: {blob!r}"
    )
