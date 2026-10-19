"""Independent Bash-only observation and correlation proof for issue #551."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def test_bash_only_calls_and_late_results_reach_provider_without_invented_success(
    tmp_path: Path,
) -> None:
    """Observed references are retained; native results without exit codes stay unknown."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/tool-proof\n")
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "call-pr", "name": "Bash",
                 "input": {"command": "gh pr view 548 --json title,body"}},
                {"type": "tool_use", "id": "call-check", "name": "Bash",
                 "input": {"command": "make check"}},
                {"type": "tool_use", "id": "call-pending", "name": "Bash",
                 "input": {"command": "git status --short"}},
            ]},
        }) + "\n", encoding="utf-8",
    )
    payload = {"session_id": "bash-session", "transcript_path": str(transcript)}
    append_turn(payload, tmp_path)
    scratch = tmp_path / ".map/tool-proof/sessions/scratch/bash-session.jsonl"
    first = [json.loads(line) for line in scratch.read_text().splitlines()]
    append_turn(payload, tmp_path)
    repeated = [json.loads(line) for line in scratch.read_text().splitlines()]
    assert [r for r in repeated if r["event"] != "turn"] == [
        r for r in first if r["event"] != "turn"
    ]
    # Native tool_result envelopes carry observations, not a guaranteed numeric status.
    with transcript.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call-check", "is_error": True,
                 "content": "CHECK_RESULT_BODY_NOT_A_PROMPT"},
                {"type": "tool_result", "tool_use_id": "call-pr",
                 "content": "https://github.com/azalio/map-framework/pull/548\n"
                            "https://github.com/azalio/map-framework/issues/551\n"
                            "RESULT_BODY_NOT_FOR_MEMORY"},
            ]},
        }) + "\n")
    append_turn(payload, tmp_path)
    wal_text = scratch.read_text()
    records = [json.loads(line) for line in wal_text.splitlines()]
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=subprocess.CompletedProcess(
        ["claude"], 0, json.dumps({"result": '{"title":"Tools","body":"Observed work"}'}), ""
    )) as provider:
        assert finalize_dirty(None, tmp_path) == 1
    provider_input = provider.call_args.kwargs["input"]
    assert "gh pr view 548" in provider_input, "Bash-only actions vanished before provider"
    tools = {r["tool_call_id"]: r for r in records if r["event"] == "tool_used"}
    assert set(tools) == {"call-pr", "call-check", "call-pending"}
    assert tools["call-pr"]["target"] == "gh pr view 548"
    assert tools["call-check"]["target"] == "make check"
    assert tools["call-pending"]["target"] == "git status"
    assert all(r["name"] == "Bash" and r["turn"] == 1 for r in tools.values())
    outcomes = [r for r in records if r["event"] == "outcome"]
    pr_outcomes = [r for r in outcomes if r.get("tool_call_id") == "call-pr"]
    assert pr_outcomes
    references = {ref for r in pr_outcomes for ref in r.get("references", [])}
    assert {"pr:548", "issue:551"} <= references
    assert all("exit_status" not in r for r in outcomes)
    assert not any(r.get("tool_call_id") == "call-pending" for r in outcomes)
    assert not any(r["event"] == "user_prompt" for r in records)
    assert "pr:548" in provider_input and "issue:551" in provider_input
    for marker in ("CHECK_RESULT_BODY_NOT_A_PROMPT", "RESULT_BODY_NOT_FOR_MEMORY"):
        assert marker not in wal_text and marker not in provider_input
    assert records[-1]["event"] == "turn" and records[-1]["turn"] == 3
    assert records[-1]["files_touched"] == [] and records[-1]["prompt_ref"] is None
