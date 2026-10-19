"""Independent public-seam regressions for issue #551 Monitor findings."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def _capture(root: Path, name: str, arguments: dict[str, Any]) -> Path:
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_text("ref: refs/heads/review-proof\n")
    transcript = root / "claude.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "tool_use", "id": "review-call",
            "name": name, "input": arguments}]}}) + "\n")
    append_turn({"session_id": "review-session", "transcript_path": str(transcript)}, root)
    return root / ".map/review-proof/sessions/scratch/review-session.jsonl"


def _finalize(root: Path) -> str:
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=subprocess.CompletedProcess(
        ["claude"], 0, json.dumps({"result": '{"title":"Reviewed","body":"Observed"}'}), ""
    )) as provider:
        assert finalize_dirty(None, root) == 1
    return provider.call_args.kwargs["input"]


def test_shell_leading_assignment_is_not_an_executable_target(tmp_path: Path) -> None:
    scratch = _capture(tmp_path, "Bash", {"command": "CUSTOM_CONTEXT=assignment-private make check"})
    wal = scratch.read_text()
    provider_input = _finalize(tmp_path)
    assert "assignment-private" not in wal
    assert "assignment-private" not in provider_input
    assert any(json.loads(line)["event"] == "tool_used" for line in wal.splitlines())


@pytest.mark.parametrize("source", ["capture", "persisted"])
def test_malformed_webfetch_target_omits_query_and_fragment(tmp_path: Path, source: str) -> None:
    scratch = _capture(tmp_path, "WebFetch", {"url": "https://example.org/safe"})
    malformed = "example.org/docs?query-private#fragment-private"
    if source == "capture":
        transcript = tmp_path / "claude.jsonl"
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "bad-url", "name": "WebFetch", "input": {"url": malformed}}
            ]}}) + "\n")
        append_turn({"session_id": "review-session", "transcript_path": str(transcript)}, tmp_path)
    else:
        with scratch.open("a") as stream:
            stream.write(json.dumps({"event": "tool_used", "session_id": "review-session", "turn": 1,
                "ts": "2026-10-19T00:00:00Z", "name": "WebFetch", "target": malformed,
                "tool_call_id": "bad-url", "truncated": False}) + "\n")
    wal = scratch.read_text()
    provider_input = _finalize(tmp_path)
    assert "https://example.org/safe" in provider_input
    assert "query-private" not in provider_input and "fragment-private" not in provider_input
    if source == "capture":
        assert "query-private" not in wal and "fragment-private" not in wal


def test_legacy_all_files_survive_digest_even_when_provider_projection_is_bounded(tmp_path: Path) -> None:
    scratch = _capture(tmp_path, "Bash", {"command": "make check"})
    paths = [f"src/file-{i:03d}.py" for i in range(140)]
    scratch.write_text(json.dumps({"event": "turn", "session_id": "review-session", "turn": 1,
        "ts": "2026-10-19T00:00:00Z", "files_touched": paths + ["/tmp/credentials-private.json"],
        "prompt_ref": "ST-001"}) + "\n")
    provider_input = _finalize(tmp_path)
    digest = next(scratch.parent.parent.glob("*.md")).read_text()
    frontmatter = yaml.safe_load(digest.split("---", 2)[1])
    assert set(paths) <= set(frontmatter["files_touched"])
    assert "/tmp/credentials-private.json" not in digest + provider_input
    if not all(path in provider_input for path in paths):
        assert "omitted" in provider_input.lower() or "truncat" in provider_input.lower()
    assert not scratch.exists(), "Only delete WAL after preserving validated digest metadata"


def test_long_bash_target_reports_truncation(tmp_path: Path) -> None:
    target = "group-" * 60
    scratch = _capture(tmp_path, "Bash", {"command": "make " + target})
    records = [json.loads(line) for line in scratch.read_text().splitlines()]
    tool = next(r for r in records if r["event"] == "tool_used")
    assert tool["target"].startswith("make group-")
    assert len(tool["target"]) <= 240
    assert tool["truncated"] is True
    provider_input = _finalize(tmp_path)
    assert '"truncated": true' in provider_input
