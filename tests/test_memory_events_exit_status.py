"""Native numeric status proof using the public OpenAI Codex SDK event schema.

Provenance (retrieved 2026-10-19; synthetic data, no private transcripts):
https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts
CommandExecutionItem: id, type=command_execution, command, aggregated_output,
exit_code?: number, status=in_progress|completed|failed.
https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts
ItemCompletedEvent: type=item.completed, item=ThreadItem.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def test_native_codex_numeric_exit_statuses_reach_provider_with_correct_item_ids(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/exit-proof\n")
    transcript = tmp_path / "codex-exec.jsonl"
    transcript.write_text("".join(json.dumps(record) + "\n" for record in [
        {"type": "item.completed", "item": {"id": "item-ok", "type": "command_execution",
            "command": "gh pr view 548", "aggregated_output":
                "https://github.com/azalio/map-framework/pull/548\nSUCCESS_BODY_PRIVATE",
            "exit_code": 0, "status": "completed"}},
        {"type": "item.completed", "item": {"id": "item-failed", "type": "command_execution",
            "command": "make check", "aggregated_output": "FAILURE_BODY_PRIVATE",
            "exit_code": 7, "status": "failed"}},
    ]))
    append_turn({"session_id": "numeric-session", "transcript_path": str(transcript)}, tmp_path)
    scratch = tmp_path / ".map/exit-proof/sessions/scratch/numeric-session.jsonl"
    wal = scratch.read_text()
    records = [json.loads(line) for line in wal.splitlines()]
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=subprocess.CompletedProcess(
        ["claude"], 0, json.dumps({"result": '{"title":"Numeric outcomes","body":"Observed"}'}), ""
    )) as provider:
        assert finalize_dirty(None, tmp_path) == 1
    provider_input = provider.call_args.kwargs["input"]
    outcomes = {r["tool_call_id"]: r for r in records if r["event"] == "outcome"}
    assert {key: r.get("exit_status") for key, r in outcomes.items()} == {"item-ok": 0, "item-failed": 7}
    assert all(type(r["exit_status"]) is int for r in outcomes.values())
    assert "pr:548" in outcomes["item-ok"].get("references", [])
    tools = {r["tool_call_id"]: r for r in records if r["event"] == "tool_used"}
    assert tools["item-ok"]["target"] == "gh pr view 548"
    assert tools["item-failed"]["target"] == "make check"
    projected = []
    for line in provider_input.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("event") == "outcome":
            projected.append(row)
    assert {r["tool_call_id"]: r.get("exit_status") for r in projected} == {"item-ok": 0, "item-failed": 7}
    assert "SUCCESS_BODY_PRIVATE" not in wal + provider_input
    assert "FAILURE_BODY_PRIVATE" not in wal + provider_input
