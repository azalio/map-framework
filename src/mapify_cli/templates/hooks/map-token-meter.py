#!/usr/bin/env python3
"""
MAP Token Meter - SubagentStop + Stop hook.

Reads the ``transcript_path`` Claude Code hands the hook and attributes that
transcript's per-turn token ``usage`` (input / output / cache_creation /
cache_read) to the active MAP subtask, phase, and agent. The heavy lifting —
parsing, dedup-by-msg_id, attribution, and the token_accounting.json rollup —
lives in ``.map/scripts/map_step_runner.py`` so the logic is identical whether
it runs in this repo or a generated project (the hook cannot rely on the
``mapify_cli`` package being importable in installed projects).

Wired on two events:
    SubagentStop : Claude Code passes BOTH ``transcript_path`` (the parent
                   session) AND ``agent_transcript_path`` (the sub-agent's own
                   transcript under ``<session>/subagents/agent-*.jsonl``). The
                   sub-agent's tokens — 80%+ of a run — live only in the latter,
                   so we read ``agent_transcript_path`` here and attribute them
                   to ``agent_type`` (e.g. actor / monitor / research-agent).
    Stop         : ``transcript_path`` is the main session transcript — sweeps
                   the orchestrator's own driving turns.

A single per-branch msg_id cache makes both safe to fire repeatedly without
double-counting (the parent and sub-agent transcripts hold disjoint msg_ids).

Exit codes:
    0 - Always. Token metering is advisory and must never block a turn.

Output:
    ``{}`` (silent). The side effect is the token_log.jsonl / token_accounting
    .json artifacts the runner writes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
RUNNER = PROJECT_DIR / ".map" / "scripts" / "map_step_runner.py"


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
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return _sanitize_branch(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def _silent() -> None:
    sys.stdout.write("{}")
    sys.exit(0)


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        _silent()
        return

    # SubagentStop carries the sub-agent's own transcript in
    # ``agent_transcript_path``; prefer it so we meter the sub-agent's tokens
    # (the parent ``transcript_path`` would only re-sweep the orchestrator).
    # Fall back to ``transcript_path`` for the Stop event (main session).
    agent_transcript = input_data.get("agent_transcript_path", "")
    if agent_transcript:
        transcript_path = agent_transcript
        # agent_type is the real sub-agent name (actor/monitor/...); empty
        # lets the runner fall back to the active-phase mapping.
        agent = str(input_data.get("agent_type", "") or "")
    else:
        transcript_path = input_data.get("transcript_path", "")
        # Main-session driving turns belong to the orchestrator, not a phase
        # sub-agent, so label them explicitly rather than by current phase.
        agent = "orchestrator"

    if not transcript_path or not RUNNER.is_file():
        _silent()
        return

    branch = _get_branch()
    command = [
        sys.executable,
        str(RUNNER),
        "record_token_event",
        branch,
        "--transcript",
        str(transcript_path),
    ]
    if agent:
        command += ["--agent", agent]
    try:
        subprocess.run(
            command,
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        # Advisory only — never surface a metering failure to the turn.
        pass
    _silent()


if __name__ == "__main__":
    main()
