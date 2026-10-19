"""Independent native transcript, durable capture and legacy compatibility proofs."""

from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def _repo(root: Path) -> Path:
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_text("ref: refs/heads/compat-proof\n")
    scratch = root / ".map/compat-proof/sessions/scratch"
    scratch.mkdir(parents=True)
    return scratch


def _finalize(root: Path) -> str:
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=subprocess.CompletedProcess(
        ["claude"], 0, json.dumps({"result": '{"title":"Compatibility","body":"Evidence"}'}), ""
    )) as provider:
        assert finalize_dirty(None, root) == 1
    provider.assert_called_once()
    return provider.call_args.kwargs["input"]


def test_native_codex_rollout_prompt_tools_and_patch_remain_useful(tmp_path: Path) -> None:
    scratch = _repo(tmp_path)
    transcript = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "Repair Codex memory observations"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
            "call_id": "call-shell", "arguments": json.dumps({"cmd": "gh issue view 551"})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-shell",
            "output": "https://github.com/azalio/map-framework/issues/551\nCODEX_OUTPUT_PRIVATE"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch",
            "call_id": "call-patch", "input": "*** Begin Patch\n*** Update File: src/parser.py\n"
                "@@\n-old\n+PATCH_BODY_PRIVATE\n*** End Patch"}},
    ]
    transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    append_turn({"session_id": "codex-session", "transcript_path": str(transcript)}, tmp_path)
    wal = (scratch / "codex-session.jsonl").read_text()
    records = [json.loads(line) for line in wal.splitlines()]
    provider_input = _finalize(tmp_path)
    assert "Repair Codex memory observations" in provider_input
    assert "gh issue view 551" in provider_input
    assert "issue:551" in provider_input
    assert records[-1]["files_touched"] == ["src/parser.py"]
    assert records[-1]["event"] == "turn"
    outcomes = [r for r in records if r["event"] == "outcome"]
    assert any(r.get("tool_call_id") == "call-shell" for r in outcomes)
    assert all("exit_status" not in r for r in outcomes)
    assert "CODEX_OUTPUT_PRIVATE" not in wal + provider_input
    assert "PATCH_BODY_PRIVATE" not in wal + provider_input


@pytest.mark.parametrize("failure", ["append", "fsync"])
def test_capture_failure_does_not_consume_transcript_cursor(tmp_path: Path, failure: str) -> None:
    scratch = _repo(tmp_path)
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {
        "role": "user", "content": "First safely captured topic"}}) + "\n")
    payload = {"session_id": "durable-session", "transcript_path": str(transcript)}
    append_turn(payload, tmp_path)
    cursor = scratch / "durable-session.offset"
    before = cursor.read_bytes()
    with transcript.open("a") as stream:
        stream.write(json.dumps({"type": "user", "message": {
            "role": "user", "content": "Later topic must remain recoverable"}}) + "\n")
    original_open = builtins.open

    def fail_append(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if str(file).endswith("durable-session.jsonl") and "a" in mode:
            raise OSError("synthetic WAL append failure")
        return original_open(file, mode, *args, **kwargs)

    target = "builtins.open" if failure == "append" else "os.fsync"
    effect = fail_append if failure == "append" else OSError("synthetic fsync failure")
    with patch(target, side_effect=effect) as boundary:
        append_turn(payload, tmp_path)
    assert boundary.called, "The durability boundary must actually be exercised"
    assert cursor.read_bytes() == before
    append_turn(payload, tmp_path)
    assert cursor.read_bytes() != before, "Successful retry must advance capture progress"
    provider_input = _finalize(tmp_path)
    assert "Later topic must remain recoverable" in provider_input


def test_legacy_turns_still_finalize_with_original_files_and_subtask(tmp_path: Path) -> None:
    scratch = _repo(tmp_path)
    (scratch / "legacy.jsonl").write_text(json.dumps({"event": "turn", "turn": 1,
        "ts": "2026-10-19T00:00:00Z", "session_id": "legacy",
        "files_touched": ["src/legacy.py"], "prompt_ref": "ST-007"}) + "\n")
    provider_input = _finalize(tmp_path)
    assert "src/legacy.py" in provider_input and "ST-007" in provider_input
    assert (scratch / "legacy.finalized").exists()
    assert not (scratch / "legacy.jsonl").exists()


def test_partial_context_wal_without_turn_can_still_be_summarized(tmp_path: Path) -> None:
    scratch = _repo(tmp_path)
    topic = "Recover interrupted batch observations"
    (scratch / "partial.jsonl").write_text(json.dumps({"event": "user_prompt", "turn": 1,
        "ts": "2026-10-19T00:00:00Z", "session_id": "partial", "prefix": topic,
        "prompt_hash": hashlib.sha256(topic.encode()).hexdigest(), "truncated": False}) + "\n")
    provider_input = _finalize(tmp_path)
    assert topic in provider_input
    assert "incomplete" in provider_input.lower() or "partial" in provider_input.lower()


def test_untrusted_common_and_legacy_fields_are_typed_before_provider(tmp_path: Path) -> None:
    scratch = _repo(tmp_path)
    records = [
        {"event": "turn", "turn": 1, "ts": "2026-10-19T00:00:00Z", "session_id": "mixed",
         "files_touched": ["src/valid.py"], "prompt_ref": "ST-008"},
        {"event": "turn", "turn": {"secret": "TURN_OBJECT_PRIVATE"},
         "ts": {"secret": "TS_OBJECT_PRIVATE"}, "session_id": ["SESSION_ARRAY_PRIVATE"],
         "files_touched": [{"body": "FILE_OBJECT_PRIVATE"}], "prompt_ref": ["REF_ARRAY_PRIVATE"]},
        {"event": "tool_used", "name": "Bash", "target": "make check", "truncated": False,
         "turn": True, "ts": {"body": "CONTEXT_TS_PRIVATE"}, "session_id": "mixed"},
        {"event": "outcome", "turn": 1, "ts": "2026-10-19T00:00:00Z", "session_id": "mixed",
         "exit_status": True, "references": [{"body": "REFERENCE_OBJECT_PRIVATE"}]},
    ]
    (scratch / "mixed.jsonl").write_text("[]\nmalformed\n" + "".join(json.dumps(r) + "\n" for r in records))
    provider_input = _finalize(tmp_path)
    assert "src/valid.py" in provider_input and "ST-008" in provider_input
    for marker in ("TURN_OBJECT_PRIVATE", "TS_OBJECT_PRIVATE", "SESSION_ARRAY_PRIVATE",
                   "FILE_OBJECT_PRIVATE", "REF_ARRAY_PRIVATE", "CONTEXT_TS_PRIVATE", "REFERENCE_OBJECT_PRIVATE"):
        assert marker not in provider_input
    assert '"exit_status": true' not in provider_input
