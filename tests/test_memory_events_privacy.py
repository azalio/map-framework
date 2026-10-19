"""Independent privacy and serialized-budget acceptance proofs for issue #551."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.finalize import finalize_dirty


def _capture(tmp_path: Path, messages: list[dict[str, Any]]) -> Path:
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/privacy-proof\n")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(r) + "\n" for r in messages))
    append_turn({"session_id": "privacy-session", "transcript_path": str(transcript)}, tmp_path)
    return tmp_path / ".map/privacy-proof/sessions/scratch/privacy-session.jsonl"


def _provider_input(tmp_path: Path) -> str:
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=subprocess.CompletedProcess(
        ["claude"], 0, json.dumps({"result": '{"title":"Safe","body":"Observed"}'}), ""
    )) as provider:
        assert finalize_dirty(None, tmp_path) == 1
    provider.assert_called_once()
    return provider.call_args.kwargs["input"]


def test_selected_targets_and_prompt_are_private_at_wal_and_provider(tmp_path: Path) -> None:
    """Command bodies, credential URLs and nested arguments are not memory targets."""
    secret = "ghp_0123456789abcdefghijklmnopqrst"
    prompt = "Boundary topic " + ("safe " * 96) + secret + "\x00\x1b\x7f"
    calls = [
        {"type": "tool_use", "id": "url", "name": "WebFetch", "input": {
            "url": "https://alice:password-marker@example.org/docs?q=QUERY_PRIVATE#FRAGMENT_PRIVATE",
            "prompt": "NESTED_FETCH_PROMPT_PRIVATE"}},
        {"type": "tool_use", "id": "bad-url", "name": "WebFetch", "input": {
            "url": "https://[broken/MALFORMED_URL_PRIVATE"}},
        {"type": "tool_use", "id": "body", "name": "Bash", "input": {
            "command": "gh issue create --body 'COMMAND_BODY_PRIVATE'"}},
        {"type": "tool_use", "id": "script", "name": "Bash", "input": {
            "command": "python -c 'SCRIPT_BODY_PRIVATE'"}},
        {"type": "tool_use", "id": "edit", "name": "Edit", "input": {
            "file_path": "src/public.py", "old_string": "EDIT_BODY_PRIVATE",
            "new_string": "EDIT_REPLACEMENT_PRIVATE"}},
        {"type": "tool_use", "id": "secret-file", "name": "Read", "input": {
            "file_path": "/tmp/credentials-private.json"}},
        {"type": "tool_use", "id": "secret-executable", "name": "Bash", "input": {
            "command": "/tmp/credentials-runner --help"}},
    ]
    scratch = _capture(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": prompt}},
        {"type": "user", "isMeta": True, "message": {
            "role": "user", "content": "META_MESSAGE_PRIVATE"}},
        {"type": "assistant", "message": {"role": "assistant", "content": calls}},
    ])
    wal = scratch.read_text()
    records = [json.loads(line) for line in wal.splitlines()]
    provider_input = _provider_input(tmp_path)
    forbidden = [secret, "password-marker", "QUERY_PRIVATE", "FRAGMENT_PRIVATE",
                 "MALFORMED_URL_PRIVATE", "NESTED_FETCH_PROMPT_PRIVATE", "COMMAND_BODY_PRIVATE",
                 "SCRIPT_BODY_PRIVATE", "EDIT_BODY_PRIVATE", "EDIT_REPLACEMENT_PRIVATE",
                 "/tmp/credentials-private.json", "/tmp/credentials-runner", "META_MESSAGE_PRIVATE"]
    for value in forbidden:
        assert value not in wal, f"Unsafe value persisted: {value}"
        assert value not in provider_input, f"Unsafe value reached provider: {value}"
    tools = {r["tool_call_id"]: r for r in records if r["event"] == "tool_used"}
    assert tools["url"]["target"] == "https://example.org/docs"
    assert not tools["bad-url"].get("target")
    assert "https://example.org/docs" in provider_input
    assert tools["edit"]["target"] == "src/public.py"
    prompts = [r for r in records if r["event"] == "user_prompt"]
    assert len(prompts) == 1 and "Boundary topic" in prompts[0]["prefix"]
    assert len(prompts[0]["prefix"]) <= 512
    for event in records:
        for value in event.values():
            if isinstance(value, str):
                assert not re.search(r"[\x00-\x1f\x7f]", value)


def test_credentials_are_redacted_before_prefix_truncation(tmp_path: Path) -> None:
    """Supported credential syntax and PEM text are never retained as prompt snippets."""
    prompt = (
        "Investigate authentication safely. API_KEY=ASSIGNMENT_PRIVATE "
        "Authorization: Bearer BEARER_PRIVATE "
        "https://bob:URL_PASSWORD@example.org/help?URL_QUERY#URL_FRAGMENT "
        "-----BEGIN PRIVATE KEY-----\nPEM_PRIVATE_CONTENT\n-----END PRIVATE KEY----- "
        + "safe " * 100 + "ghp_0123456789abcdefghijklmnopqrst"
    )
    scratch = _capture(tmp_path, [{"type": "user", "message": {
        "role": "user", "content": prompt}}])
    wal = scratch.read_text()
    provider_input = _provider_input(tmp_path)
    assert "Investigate authentication safely" in provider_input
    for value in ("ASSIGNMENT_PRIVATE", "BEARER_PRIVATE", "URL_PASSWORD", "PEM_PRIVATE_CONTENT"):
        assert value not in wal
        assert value not in provider_input


def test_finalizer_revalidates_urls_and_drops_unknown_fields(tmp_path: Path) -> None:
    """A persisted observation is untrusted even when it bypasses current capture."""
    scratch = _capture(tmp_path, [])
    base = {"session_id": "privacy-session", "turn": 1, "ts": "2026-10-19T00:00:00Z"}
    with scratch.open("a") as stream:
        stream.write(json.dumps({**base, "event": "tool_used", "name": "WebFetch",
            "target": "https://alice:WAL_PASSWORD@example.org/help?WAL_QUERY#WAL_FRAGMENT",
            "tool_call_id": "url", "truncated": False, "raw_body": "UNKNOWN_FIELD_PRIVATE"}) + "\n")
        stream.write(json.dumps({**base, "event": "tool_used", "name": "WebFetch",
            "target": "https://[broken/WAL_MALFORMED_PRIVATE", "truncated": False}) + "\n")
        stream.write(json.dumps({**base, "event": "unknown", "prefix": "UNKNOWN_EVENT_PRIVATE"}) + "\n")
    provider_input = _provider_input(tmp_path)
    assert "https://example.org/help" in provider_input
    for value in ("WAL_PASSWORD", "WAL_QUERY", "WAL_FRAGMENT", "UNKNOWN_FIELD_PRIVATE",
                  "WAL_MALFORMED_PRIVATE", "UNKNOWN_EVENT_PRIVATE"):
        assert value not in provider_input
    assert "untrusted" in provider_input.lower()


def test_unicode_batches_and_provider_evidence_have_visible_serialized_bounds(tmp_path: Path) -> None:
    """ASCII JSON expansion counts toward budgets, including legacy turns and metadata."""
    scratch = _capture(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": f"Topic {i} " + "漢🙂 " * 500}}
        for i in range(100)
    ])
    records = [json.loads(line) for line in scratch.read_text().splitlines()]
    context = [r for r in records if r["event"] != "turn"]
    assert len("".join(json.dumps(r, ensure_ascii=True) + "\n" for r in context).encode()) <= 16 * 1024
    assert any(r["event"] == "user_prompt" for r in context)
    assert any(r["event"] == "capture_truncated" and r["omitted_events"] > 0 for r in context)
    assert all(len(r["prefix"]) <= 512 and r["truncated"] for r in context if r["event"] == "user_prompt")
    assert records[-1]["event"] == "turn"
    # Existing historical turns must share the finalizer budget with new observations.
    with scratch.open("a") as stream:
        for i in range(250):
            stream.write(json.dumps({"event": "turn", "session_id": "privacy-session", "turn": i + 2,
                "ts": "2026-10-19T00:00:00Z", "prompt_ref": None,
                "files_touched": [f"src/{i}-" + "漢🙂" * 50 + ".py"]}) + "\n")
    provider_input = _provider_input(tmp_path)
    projected = []
    for line in provider_input.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            projected.append(value)
    assert projected, "Provider must receive structured evidence, not just a budget notice"
    assert len("".join(json.dumps(r, ensure_ascii=True) + "\n" for r in projected).encode()) <= 48 * 1024
    assert len(provider_input.encode()) <= 48 * 1024 + 4096, "Instructions cannot hide an unbounded projection"
    assert "omitted" in provider_input.lower() or "truncat" in provider_input.lower()
