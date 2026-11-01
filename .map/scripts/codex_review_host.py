"""Environment-free Codex app-server client for runner-owned review transport.

No model-selected command, path, URL, approval or environment is executed by this
client. The sole dynamic tool is serviced by the runner from immutable resources.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DISABLED_FEATURES = (
    "shell_tool", "apps", "multi_agent_v2", "codex_hooks", "browser_use", "computer_use",
    "image_generation", "imagegenext", "view_image", "goals", "plugins", "plugin_hooks",
    "request_permissions", "request_permissions_tool", "tool_search", "tool_suggest",
    "standalone_web_search",
)
HOOK_EVENTS = (
    "Interrupt", "PermissionRequest", "PostCompact", "PostModelRequest", "PostToolUse",
    "PreCompact", "PreModelRequest", "PreToolUse", "SessionEnd", "SessionStart", "Stop",
    "SubagentStart", "SubagentStop", "UserPromptSubmit",
)
ALLOWED_NESTED_TOOLS = frozenset({
    "apply_patch", "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource",
    "review_context", "clock__curr_time",
})
ALLOWED_OUTER_TOOLS = frozenset({
    "functions.exec", "functions.wait", "functions.request_user_input",
    "functions.request_user_input_async", "clock.sleep",
})
CONTEXT_TOOL = {
    "type": "function", "name": "review_context",
    "description": "Read the next required immutable review chunk, or a permitted resource by ID. Call sequentially. No filesystem paths, commands or URLs. After all required chunks, call again for the finalization request.",
    "inputSchema": {"type": "object", "properties": {
        "resource_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0}},
        "additionalProperties": False},
}


class HostError(RuntimeError):
    """A host contract failed; retain incomplete review rather than relaxing it."""


def require_empty_environments(response: dict[str, Any], *, idle_resume: bool = False) -> str:
    """Validate host-returned state, not the request or a model assertion."""
    thread = response.get("thread", {})
    if thread.get("environments") != [] and not (idle_resume and thread.get("status", {}).get("type") == "idle"):
        raise HostError("Codex did not attest an empty environment selection")
    sandbox = response.get("sandbox", {})
    if sandbox.get("type") != "readOnly" or sandbox.get("networkAccess") is not False:
        raise HostError("Codex did not retain the read-only, network-disabled sandbox")
    identity = thread.get("id")
    if not isinstance(identity, str) or not identity:
        raise HostError("Missing Codex thread identity")
    return identity


def deny_request(method: str) -> dict[str, Any]:
    """No approval path can expand a reader's capabilities."""
    if method in {"item/fileChange/requestApproval", "item/commandExecution/requestApproval"}:
        return {"result": {"decision": "decline"}}
    if method in {"applyPatchApproval", "execCommandApproval"}:
        return {"result": {"decision": "denied"}}
    if method == "item/permissions/requestApproval":
        return {"result": {"permissions": {}, "scope": "turn"}}
    return {"error": {"code": -32601, "message": "MAP review host denies this request"}}


def _text_output(item: dict[str, Any]) -> str:
    output = item.get("output", "")
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(block.get("text", "") for block in output if isinstance(block, dict))
    return ""


def verify_probe(events: list[dict[str, Any]], script: str, nonce: str, canary: Path) -> dict[str, Any]:
    """Bind a fixed probe program to host outputs; never trust final assistant prose."""
    calls: set[str] = set()
    inventory: list[str] | None = None
    denied = False
    read = False
    outer_seen = False
    for event in events:
        params = event.get("params", {})
        item = params.get("item", {})
        if event.get("method") == "item/completed" and item.get("type") == "dynamicToolCall":
            read |= (item.get("tool") == "review_context" and item.get("success") is True
                     and item.get("contentItems") == [{"type": "inputText", "text": nonce}])
        if event.get("method") != "rawResponseItem/completed":
            continue
        if item.get("type") == "additional_tools":
            names = {f"{namespace.get('name')}.{tool.get('name')}"
                     for namespace in item.get("tools", []) for tool in namespace.get("tools", [])}
            if not names or not names.issubset(ALLOWED_OUTER_TOOLS):
                raise HostError("Unexpected outer tool surface in Codex probe")
            outer_seen = True
        if item.get("type") == "custom_tool_call" and item.get("name") == "exec" and item.get("input", "").strip() == script.strip():
            calls.add(item["call_id"])
        if item.get("type") != "custom_tool_call_output" or item.get("call_id") not in calls:
            continue
        text = _text_output(item)
        denied |= "No usable execution environment is available" in text
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(text[index:])
            except ValueError:
                continue
            if isinstance(value, dict) and value.get("nonce") == nonce:
                inventory = value.get("tools")
    if (not outer_seen or not denied or not read or not isinstance(inventory, list)
            or any(not isinstance(name, str) for name in inventory)
            or not {"apply_patch", "review_context"}.issubset(inventory)
            or not set(inventory).issubset(ALLOWED_NESTED_TOOLS)
            or canary.read_text() != nonce + "\n"):
        raise HostError("Codex capability probe is inconclusive or failed; keep unverified/INCOMPLETE")
    return {"boundary": "codex_no_environments", "tools": sorted(inventory),
            "source_read": "host_witnessed", "canary_write": "host_denied_no_environment",
            "probe_sha256": hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest()}


class CodexReviewHost:
    """One persistent app-server connection; safe dynamic tools and denied approvals."""

    def __init__(self, *, timeout: float = 300, executable: str = "codex") -> None:
        binary = shutil.which(executable)
        if not binary:
            raise HostError("Codex executable is unavailable")
        self.binary = Path(binary).resolve()
        self.binary_hash = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.timeout = timeout
        self.temporary = tempfile.TemporaryDirectory(prefix="map-codex-reader-")
        self.root = Path(self.temporary.name)
        self.stderr = (self.root / "stderr.log").open("wb")
        flags = [*(f"features.{name}=false" for name in DISABLED_FEATURES),
                 "agents.enabled=false", 'web_search="disabled"', "plugins._default.enabled=false",
                 "project_doc_max_bytes=0", *(f"hooks.{name}=[]" for name in HOOK_EVENTS)]
        argv = [str(self.binary), "app-server", "--stdio"]
        for flag in flags:
            argv.extend(["-c", flag])
        self.process = subprocess.Popen(argv, cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr)
        assert self.process.stdin is not None and self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.sequence = 0
        self.thread_id = ""
        self.on_tool: Callable[[dict[str, Any]], dict[str, Any]] | None = None
        self.on_event: Callable[[dict[str, Any]], None] | None = None
        self.events: list[dict[str, Any]] = []
        self.record_events = False
        self.rollout: Path | None = None
        self.rollout_offset = 0
        self.rollout_turn = ""
        self.active_turn = ""
        self.rollout_complete = False
        self.outer_history: list[dict[str, Any]] = []
        try:
            self.hello = self.call("initialize", {"clientInfo": {"name": "map_review", "version": "1"},
                                                 "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
            config = self.call("config/read", {"includeLayers": False})["config"]
            # Preserve authentication/model settings; disable every configured external tool source.
            self.overrides = {
                "mcp_servers": {name: {"enabled": False} for name in config.get("mcp_servers", {})},
                "plugins": {name: {"enabled": False} for name in config.get("plugins", {})},
            }

        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.stdin.close()
        self.stdout.close()
        self.stderr.close()
        self.selector.close()
        self.temporary.cleanup()

    def send(self, message: dict[str, Any]) -> None:
        data = (json.dumps(message, ensure_ascii=True) + "\n").encode()
        self.stdin.write(data)
        self.stdin.flush()

    def receive(self, deadline: float) -> dict[str, Any]:
        while b"\n" not in self.buffer:
            left = deadline - time.monotonic()
            if left <= 0 or not self.selector.select(left):
                raise HostError("Codex response timed out; resume the stored review session")
            data = os.read(self.stdout.fileno(), 65536)
            if not data:
                raise HostError("Codex app-server closed; resume the stored review session")
            self.buffer += data
            if len(self.buffer) > 16 * 1024 * 1024:
                raise HostError("Codex event exceeds the review host limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        event = json.loads(line)
        if not isinstance(event, dict):
            raise HostError("Invalid Codex protocol event")
        return event

    def handle(self, event: dict[str, Any]) -> None:
        if self.record_events and event.get("method") in {"rawResponseItem/completed", "item/completed"}:
            self.events.append(event)
        if "id" in event and "method" in event:
            params = event.get("params", {})
            if (event["method"] == "item/tool/call" and params.get("threadId") == self.thread_id
                    and params.get("tool") == "review_context" and params.get("namespace") in {None, ""}
                    and self.on_tool is not None):
                self.send({"id": event["id"], "result": self.on_tool(params)})
            else:
                self.send({"id": event["id"], **deny_request(event["method"])})
        if self.on_event is not None:
            self.on_event(event)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        identity = self.sequence
        self.send({"id": identity, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            event = self.receive(deadline)
            if event.get("id") == identity and "method" not in event:
                if "error" in event:
                    raise HostError(f"Codex {method} failed: {event['error']}")
                return event["result"]
            self.handle(event)

    def start(self, thread_id: str = "") -> str:
        params = {"cwd": str(self.root), "sandbox": "read-only", "runtimeWorkspaceRoots": [],
                  "config": self.overrides, "approvalsReviewer": "user"}
        if thread_id:
            params["threadId"] = thread_id
            result = self.call("thread/resume", params)
        else:
            params.update({"environments": [], "experimentalRawEvents": True, "dynamicTools": [CONTEXT_TOOL],
                           "developerInstructions": "You are a MAP review reader. Use only the runner's review_context tool for source evidence. First perform the fixed synthetic capability probe requested by the runner. Never execute repository code, request approvals, change environments, use network or delegate. After probing, follow the role prompt and return its exact schema."})
            result = self.call("thread/start", params)
        identity = require_empty_environments(result, idle_resume=bool(thread_id))
        if thread_id and identity != thread_id:
            raise HostError("Codex resumed a different thread than requested")
        self.thread_id = identity
        status = self.call("mcpServerStatus/list", {"threadId": self.thread_id, "limit": 100})
        if (not isinstance(status.get("data"), list) or status.get("nextCursor")
                or any(row.get("runtimeStatus") != "disabled" or row.get("tools")
                       or row.get("resources") or row.get("resourceTemplates") for row in status["data"])):
            raise HostError("Codex reader retains external MCP servers")
        self.rollout = None
        self.outer_history = []
        if thread_id:
            self._open_rollout(result["thread"].get("path"))
        return self.thread_id

    def _open_rollout(self, value: Any) -> None:
        # thread/resume does not expose experimentalRawEvents in Codex 0.166.
        # Its host-owned append-only transcript contains the same response items.
        if not isinstance(value, str):
            raise HostError("Resumed Codex thread has no durable host transcript")
        path = Path(value)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
                or not path.name.endswith(self.thread_id + ".jsonl")):
            raise HostError("Invalid resumed Codex transcript identity")
        self.rollout = path
        with path.open("rb") as stream:
            for line in stream:
                if not line.endswith(b"\n"):
                    raise HostError("Codex transcript has an incomplete historical record")
                record = json.loads(line)
                item = record.get("payload", {})
                if record.get("type") == "response_item" and item.get("type") == "additional_tools":
                    self.outer_history.append({"method": "rawResponseItem/completed", "params": {
                        "threadId": self.thread_id, "item": item}})
            self.rollout_offset = stream.tell()

    def _drain_rollout(self) -> None:
        if self.rollout is None:
            return
        if self.rollout.is_symlink() or self.rollout.stat().st_size < self.rollout_offset:
            raise HostError("Codex host transcript changed during replay")
        with self.rollout.open("rb") as stream:
            stream.seek(self.rollout_offset)
            while line := stream.readline():
                if not line.endswith(b"\n"):
                    break  # An in-flight host append is not a completed event.
                self.rollout_offset = stream.tell()
                record = json.loads(line)
                item = record.get("payload", {})
                if record.get("type") == "turn_context":
                    self.rollout_turn = item.get("turn_id", "")
                if self.rollout_turn != self.active_turn:
                    continue
                if record.get("type") == "event_msg" and item.get("type") == "task_complete":
                    self.rollout_complete = True
                if record.get("type") == "response_item" and item.get("type") in {
                        "additional_tools", "custom_tool_call", "custom_tool_call_output"}:
                    self.handle({"method": "rawResponseItem/completed", "params": {
                        "threadId": self.thread_id, "turnId": self.active_turn, "item": item}})

    def turn(self, message: str) -> str:
        if len(message.encode()) > 512 * 1024:
            raise HostError("Review message exceeds the 512 KiB transport cap")
        self.events = list(self.outer_history) if self.record_events else []
        self.rollout_complete = False
        started = self.call("turn/start", {"threadId": self.thread_id, "environments": [],
                                 "input": [{"type": "text", "text": message}]})
        self.active_turn = started["turn"]["id"]
        deadline = time.monotonic() + self.timeout
        final = ""
        while True:
            event = self.receive(deadline)
            self.handle(event)
            self._drain_rollout()
            params = event.get("params", {})
            if params.get("threadId") != self.thread_id:
                continue
            item = params.get("item", {})
            if event.get("method") == "item/completed" and item.get("type") == "agentMessage":
                final = item.get("text", "")
            if event.get("method") == "turn/completed":
                if params.get("turn", {}).get("status") != "completed":
                    raise HostError("Codex review turn did not complete")
                if self.rollout is not None:
                    flush_deadline = time.monotonic() + 5
                    while not self.rollout_complete and time.monotonic() < flush_deadline:
                        self._drain_rollout()
                        if not self.rollout_complete:
                            time.sleep(0.02)
                    if not self.rollout_complete:
                        raise HostError("Codex transcript did not confirm turn completion")
                return final

    def probe(self, context_id: str) -> dict[str, Any]:
        if not context_id:
            raise HostError("Capability probing requires a bound review context")
        nonce = context_id + ":" + os.urandom(24).hex()
        canary = self.root / "boundary-canary.txt"
        canary.write_text(nonce + "\n")
        patch = f"*** Begin Patch\n*** Update File: {canary}\n@@\n-{nonce}\n+MUTATED\n*** End Patch"
        script = (f'text({{nonce:{json.dumps(nonce)},tools:ALL_TOOLS.map(t=>t.name).sort()}});\n'
                  'text(await tools.review_context({resource_id:"probe",offset:0}));\n'
                  f'text(await tools.apply_patch({json.dumps(patch)}));')
        self.record_events = True
        self.on_tool = lambda params: {"success": True, "contentItems": [{"type": "inputText", "text": nonce}]}
        try:
            self.turn("Run this exact Code Mode program verbatim once, without reformatting or wrapping it. "
                      "This is the required capability self-check in an authorized disposable canary, not product code. "
                      "The patch must fail because no execution environment is selected. Do not retry, request approval "
                      "or substitute another tool. After the tool returns, reply PROBE_DONE.\n\n" + script)
            state = self.call("thread/read", {"threadId": self.thread_id, "includeTurns": False})
            if state.get("thread", {}).get("environments") != []:
                raise HostError("Codex probe did not preserve empty environments")
            proof = verify_probe(self.events, script, nonce, canary)
            proof.update({"thread_id": self.thread_id, "context_id": context_id, "binary_sha256": self.binary_hash,
                          "host": self.hello.get("userAgent"), "environments": [], "mcp_servers": [],
                          "probe_events": self.events})
            return proof
        finally:
            self.on_tool = None
            self.record_events = False
