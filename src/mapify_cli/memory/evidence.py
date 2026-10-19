"""Narrow native-envelope observations, without retaining tool payload bodies."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mapify_cli.memory.digest_schema import (
    EVENT_OUTCOME,
    EVENT_TOOL_USED,
    TOOL_CALL_ID_CHARS,
    TOOL_NAME_CHARS,
    TOOL_TARGET_CHARS,
    bounded_text,
    redact_secret_path,
)


def call_id(value: object) -> str | None:
    """Keep exact safe identifiers; never shorten IDs into join collisions."""
    if (isinstance(value, str) and len(value) <= TOOL_CALL_ID_CHARS
            and re.fullmatch(r"[A-Za-z0-9_.:-]+", value)):
        return value
    return None


def safe_target(value: str, *, url_required: bool = False) -> str | None:
    """Drop credential URL components; URL fields fail closed on malformed input."""
    if url_required or "://" in value:
        try:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or re.search(r"\s", value)):
                return None
            port = parsed.port
            hostname = parsed.hostname
            if ":" in hostname:
                hostname = f"[{hostname}]"
            netloc = hostname + (f":{port}" if port is not None else "")
            value = urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            return None
    return bounded_text(redact_secret_path(value), TOOL_TARGET_CHARS)


def _bash_target(command: str) -> str | None:
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    executable = argv[0]
    # Intent: assignments and shell expansion are not executable identities.
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", executable) or executable.startswith("-"):
        return None
    # Intent: never interpret shell syntax or retain arguments containing bodies.
    target = executable
    safe_word = r"[A-Za-z0-9_./:-]+"
    if executable == "gh" and len(argv) >= 3:
        if argv[1] in {"pr", "issue"} and re.fullmatch(r"[a-z]+", argv[2]):
            target = " ".join(argv[:3])
            if len(argv) > 3 and argv[3].isdigit():
                target += " " + argv[3]
    elif (executable in {"git", "make", "pytest"} and len(argv) > 1
          and not argv[1].startswith("-") and re.fullmatch(safe_word, argv[1])):
        target += " " + argv[1]
    return target


def _tool_event(name: object, payload: object, identifier: object) -> dict[str, Any] | None:
    if not isinstance(name, str) or not name:
        return None
    event: dict[str, Any] = {
        "event": EVENT_TOOL_USED,
        "name": bounded_text(name, TOOL_NAME_CHARS),
        "truncated": len(name) > TOOL_NAME_CHARS,
    }
    identifier = call_id(identifier)
    if identifier is not None:
        event["tool_call_id"] = identifier
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = None
    target = None
    if isinstance(payload, dict):
        if name in {"Bash", "exec_command", "shell_command"}:
            command = payload.get("command", payload.get("cmd"))
            if isinstance(command, str):
                selected = _bash_target(command)
                if selected is not None:
                    target = safe_target(selected)
                    event["truncated"] = event["truncated"] or len(selected) > TOOL_TARGET_CHARS
        else:
            fields = {
                "Read": ("file_path",), "Edit": ("file_path",),
                "Write": ("file_path",), "MultiEdit": ("file_path",),
                "WebFetch": ("url",), "Skill": ("skill",),
            }.get(name, ())
            for key in fields:
                value = payload.get(key)
                if isinstance(value, str):
                    target = safe_target(value, url_required=key == "url")
                    event["truncated"] = event["truncated"] or len(value) > TOOL_TARGET_CHARS
                    break
    if target:
        event["target"] = target
    return event


def _outcome(identifier: object, content: object) -> dict[str, Any] | None:
    identifier = call_id(identifier)
    if identifier is None:
        return None
    if isinstance(content, list):
        content = "\n".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    event: dict[str, Any] = {"event": EVENT_OUTCOME, "tool_call_id": identifier}
    if isinstance(content, str):
        refs = []
        for match in re.finditer(r"https://github\.com/[\w.-]+/[\w.-]+/(pull|issues)/(\d+)", content):
            ref = ("pr:" if match[1] == "pull" else "issue:") + match[2]
            if ref not in refs:
                refs.append(ref)
            if len(refs) >= 16:
                break
        if refs:
            event["references"] = refs
    return event


def native_tool_events(record: object) -> Iterator[dict[str, Any]]:
    """Observe only provider-owned envelopes, never recursively nested payloads."""
    if not isinstance(record, dict):
        return
    if record.get("type") in {"assistant", "user"}:
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != record["type"]:
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            event = None
            if record["type"] == "assistant" and block.get("type") == "tool_use":
                event = _tool_event(block.get("name"), block.get("input"), block.get("id"))
            elif record["type"] == "user" and block.get("type") == "tool_result":
                event = _outcome(block.get("tool_use_id"), block.get("content"))
            if event is not None:
                yield event
    elif record.get("type") == "item.completed":
        item = record.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            return
        event = _tool_event("exec_command", {"command": item.get("command")}, item.get("id"))
        if event is not None:
            yield event
        outcome = _outcome(item.get("id"), item.get("aggregated_output"))
        if outcome is not None:
            # Intent: only the native SDK command item supplies numeric exit metadata.
            status = item.get("exit_code")
            if type(status) is int:
                outcome["exit_status"] = status
            yield outcome
    elif record.get("type") == "response_item":
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind in {"function_call", "custom_tool_call"}:
            event = _tool_event(payload.get("name"), payload.get("arguments", payload.get("input")), payload.get("call_id"))
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            event = _outcome(payload.get("call_id"), payload.get("output"))
        else:
            event = None
        if event is not None:
            yield event
