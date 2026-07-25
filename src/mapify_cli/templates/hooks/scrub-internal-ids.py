#!/usr/bin/env python3
"""Strip MAP-internal workflow IDs from shipped code — Stop hook.

Runs when the main agent finishes a turn (Stop event). It is a thin, strictly
gated wrapper: the deterministic work lives in ``.map/scripts/scrub_internal_ids
.py`` (stdlib-only, importable-free, identical in this repo and installed
projects — same split as ``map-token-meter`` / ``map_step_runner``).

Why a Stop hook and not a skill step: the executor must not depend on the agent
remembering to call a command at close. The harness fires Stop deterministically;
the hook decides for itself whether the run is done.

Gating (no-op in ~all turns):
    1. ``MAP_INVOKED_BY`` set            -> exit (don't run inside a sub-agent).
    2. no ``.map/<branch>/step_state.json`` OR ``workflow_status`` is not
       ``WORKFLOW_COMPLETE``            -> exit (run not finished).
    3. marker ``.map/<branch>/.scrub_done`` present -> exit (already ran once).
    4. ``scrub_internal_ids: false`` in ``.map/config.yaml`` -> exit (opt-out).

When it does run: calls the engine in ``clean`` mode, commits the resulting
working-tree changes as a dedicated ``chore(map): strip internal workflow IDs``
commit (never amends), and writes the marker so it fires exactly once.

Synchronous by design (justified exception to the async-hook rule): the scrub
must finish and commit before the run is considered done; a detached run would
race the close/PR and could land after it. The work is fast — scoped to the
run's git diff, like ``end-of-turn.sh``.

Exit codes: always 0. The scrub is advisory and must never block a turn.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
ENGINE = PROJECT_DIR / ".map" / "scripts" / "scrub_internal_ids.py"


def _silent() -> NoReturn:
    sys.stdout.write("{}")
    sys.exit(0)


def _sanitize_branch(branch: str) -> str:
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def _get_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return _sanitize_branch(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def _scrub_enabled(branch_dir: Path) -> bool:
    """Honor the ``scrub_internal_ids`` opt-out in .map/config.yaml (default on).

    Minimal stdlib parse — PyYAML is not guaranteed in installed projects.
    """
    config = PROJECT_DIR / ".map" / "config.yaml"
    if not config.exists():
        return True
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return True
    m = re.search(r"^\s*scrub[._]internal_ids\s*:\s*(\S+)", text, re.MULTILINE)
    return not (m and m.group(1).strip().lower() in ("false", "no", "off", "0"))


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    # Stop payload is read defensively but not required.
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    branch = _get_branch()
    branch_dir = PROJECT_DIR / ".map" / branch
    state_file = branch_dir / "step_state.json"
    if not state_file.exists():
        _silent()
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _silent()

    status = str(state.get("workflow_status") or "").strip().upper()
    if status != "WORKFLOW_COMPLETE":
        _silent()

    marker = branch_dir / ".scrub_done"
    if marker.exists():
        _silent()
    if not _scrub_enabled(branch_dir):
        marker.write_text("disabled\n", encoding="utf-8")
        _silent()
    if not ENGINE.exists():
        _silent()

    # Run the engine. MAP_INVOKED_BY guards any nested hook from re-entering.
    env = {**os.environ, "MAP_INVOKED_BY": "scrub-internal-ids"}
    try:
        proc = subprocess.run(
            [sys.executable, str(ENGINE), "clean", "--branch", branch],
            capture_output=True, text=True, cwd=PROJECT_DIR, env=env, timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _silent()

    report = {}
    try:
        report = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        report = {}

    modified = report.get("files_modified") or []
    if modified:
        try:
            subprocess.run(["git", "add", "--", *modified], cwd=PROJECT_DIR,
                           env=env, capture_output=True, text=True, timeout=15, check=False)
            subprocess.run(
                ["git", "commit", "-m", "chore(map): strip internal workflow IDs"],
                cwd=PROJECT_DIR, env=env, capture_output=True, text=True, timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # leave the cleaned working tree in place; never block

    # Mark done so the scrub fires exactly once for this completed run.
    try:
        marker.write_text(
            json.dumps({
                "files_modified": modified,
                "tokens_removed": report.get("tokens_removed", 0),
                "tests_renamed": report.get("tests_renamed", []),
                "residual": report.get("residual", []),
            }) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    if report.get("residual"):
        sys.stderr.write(
            "[scrub-internal-ids] could not auto-remove some internal IDs; "
            f"see {marker} (residual list).\n"
        )
    _silent()


if __name__ == "__main__":
    main()
