"""Independent public-seam regression for issue #551: meaningful prompt evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def test_no_workflow_prompt_reaches_actual_provider_input(tmp_path: Path) -> None:
    """A human topic survives capture/finalize without a MAP subtask or edits."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/memory-proof\n")
    secret = "ghp_0123456789abcdefghijklmnopqrst"
    topic = "Investigate why session digests lose Bash-only work"
    prompt = f"{topic}; synthetic credential {secret}"
    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {
                    "type": "user",
                    "sessionId": "human-session",
                    "message": {"role": "user", "content": prompt},
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "ASSISTANT_BODY_NOT_EVIDENCE"}],
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    append_turn(
        {"session_id": "human-session", "transcript_path": str(transcript)},
        tmp_path,
    )
    scratch = tmp_path / ".map/memory-proof/sessions/scratch/human-session.jsonl"
    wal_text = scratch.read_text(encoding="utf-8")
    records = [json.loads(line) for line in wal_text.splitlines()]
    result = subprocess.CompletedProcess(
        args=["claude"],
        returncode=0,
        stdout=json.dumps(
            {"result": json.dumps({"title": "Memory topic", "body": "Captured topic"})}
        ),
        stderr="",
    )
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=result) as provider:
        assert finalize_dirty(None, tmp_path) == 1
    provider.assert_called_once()
    provider_input = provider.call_args.kwargs["input"]
    assert topic in provider_input, "No-workflow topic was lost before the digest provider"
    assert secret not in provider_input
    assert secret not in wal_text
    assert "ASSISTANT_BODY_NOT_EVIDENCE" not in provider_input
    assert "ASSISTANT_BODY_NOT_EVIDENCE" not in wal_text
    prompts = [record for record in records if record.get("event") == "user_prompt"]
    assert len(prompts) == 1
    event = prompts[0]
    assert event["prompt_hash"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert topic in event["prefix"]
    assert len(event["prefix"]) <= 512
    assert event["truncated"] is False
    assert event["session_id"] == "human-session"
    assert event["turn"] == 1
    assert isinstance(event["ts"], str) and event["ts"]
    assert records[-1] == {
        "event": "turn",
        "ts": event["ts"],
        "session_id": "human-session",
        "turn": 1,
        "files_touched": [],
        "prompt_ref": None,
    }
    assert list(scratch.parent.parent.glob("*.md")), "Finalization must publish a digest"
