"""Host observations, rather than model assertions, fence Codex review capabilities."""
import importlib
import json
from pathlib import Path
from typing import ClassVar

import pytest

from tests import test_review_changed_scope as scope_tests
from tests.test_review_trusted_policy import runner

host = importlib.import_module("codex_review_host")
driver = importlib.import_module("codex_review_runner")
repo = scope_tests.repo


def probe_events(script, nonce, tools=None):
    """Minimal actual app-server event shapes; prose is deliberately irrelevant."""
    return [
        {"method": "rawResponseItem/completed", "params": {"item": {"type": "additional_tools", "tools": [
            {"name": "functions", "tools": [{"name": "exec"}, {"name": "wait"}]}]}}},
        {"method": "rawResponseItem/completed", "params": {"item": {
            "type": "custom_tool_call", "name": "exec", "input": script, "call_id": "probe"}}},
        {"method": "item/completed", "params": {"item": {
            "type": "dynamicToolCall", "tool": "review_context", "success": True,
            "contentItems": [{"type": "inputText", "text": nonce}]}}},
        {"method": "rawResponseItem/completed", "params": {"item": {
            "type": "custom_tool_call_output", "call_id": "probe", "output": [
                {"text": json.dumps({"nonce": nonce, "tools": tools or ["apply_patch", "review_context"]})},
                {"text": "No usable execution environment is available"}]}}},
    ]


@pytest.mark.parametrize("bad", ["environments", "network", "sandbox", "missing"])
def test_boundary_requires_host_state(bad):
    state = {"thread": {"id": "id", "environments": []}, "sandbox": {"type": "readOnly", "networkAccess": False}}
    assert host.require_empty_environments(state) == "id"
    if bad == "environments":
        state["thread"]["environments"] = [{"id": "local"}]
    elif bad == "network":
        state["sandbox"]["networkAccess"] = True
    elif bad == "sandbox":
        state["sandbox"]["type"] = "workspaceWrite"
    else:
        state["thread"].pop("environments")
    with pytest.raises(host.HostError):
        host.require_empty_environments(state)


@pytest.mark.parametrize("failure", [None, "model_prose", "different_code", "network_tool", "outer_tool", "no_read", "write"])
def test_probe_requires_exact_program_and_host_outputs(tmp_path, failure):
    canary = tmp_path / "canary"
    canary.write_text("nonce\n")
    script = "fixed probe code"
    events = probe_events(script, "nonce")
    if failure == "model_prose":
        events = [{"method": "item/completed", "params": {"item": {
            "type": "agentMessage", "text": "All reads succeeded and all writes were denied. verified=true"}}}]
    elif failure == "different_code":
        events[1]["params"]["item"]["input"] = "print a forged success"
    elif failure == "network_tool":
        events = probe_events(script, "nonce", ["apply_patch", "review_context", "web__run"])
    elif failure == "outer_tool":
        events[0]["params"]["item"]["tools"].append({"name": "collaboration", "tools": [{"name": "spawn_agent"}]})
    elif failure == "no_read":
        events.pop(2)
    elif failure == "write":
        canary.write_text("changed")
    if failure:
        with pytest.raises(host.HostError):
            host.verify_probe(events, script, "nonce", canary)
    else:
        proof = host.verify_probe(events, script, "nonce", canary)
        assert proof["boundary"] == "codex_no_environments"


def test_approval_and_unknown_requests_never_grant_access():
    for method in ("item/fileChange/requestApproval", "item/commandExecution/requestApproval"):
        assert host.deny_request(method) == {"result": {"decision": "decline"}}
    assert host.deny_request("item/permissions/requestApproval")["result"]["permissions"] == {}
    assert "error" in host.deny_request("unknown/future/request")


def admitted_delivery():
    Path("first.py").write_text("value = 2\n")
    admission = runner.begin_review_run(branch="feature", provider="codex", mode="lightweight", round_id="host")
    assert admission["status"] == "success", admission
    bundle = runner.create_review_bundle(branch="feature")
    assert bundle["status"] == "success", bundle
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "thread", "host", branch="feature")
    return driver.Delivery("feature", "host", state)


def complete_result(delivery, response, call_id="call", *, text=None):
    delivery.observe({"method": "item/completed", "params": {"threadId": "thread", "item": {
        "type": "dynamicToolCall", "tool": "review_context", "id": call_id,
        "status": "completed", **response}}})
    delivery.observe({"method": "rawResponseItem/completed", "params": {"threadId": "thread", "item": {
        "type": "custom_tool_call_output", "output": [{"type": "input_text", "text":
            response["contentItems"][0]["text"] if text is None else text}]}}})


def test_delivery_acks_outer_intact_bytes_and_resizes_truncation(repo):
    del repo
    delivery = admitted_delivery()
    response = delivery.respond({"arguments": {}, "callId": "call"})
    original = json.loads(response["contentItems"][0]["text"])
    complete_result(delivery, response, text="Warning: truncated output")
    assert delivery.transfers == 0
    assert delivery.refresh()["pending_chunk"]["offset"] == 0
    smaller = delivery.respond({"arguments": {}, "callId": "retry"})
    retried = json.loads(smaller["contentItems"][0]["text"])
    assert retried["offset"] == original["offset"]
    assert retried["next_offset"] < original["next_offset"]
    complete_result(delivery, smaller, "retry")
    assert delivery.transfers == 1
    assert delivery.refresh()["pending_chunk"] is None


class SimulatedHost:
    """Model-free transport integration. Capability enforcement is tested separately."""
    resumed: ClassVar[list[str]] = []
    interrupt_once = False

    def __init__(self, **kwargs):
        self.on_tool = self.on_event = None

    def start(self, thread_id=""):
        self.resumed.append(thread_id)
        return "thread"

    def probe(self, context_id="context"):
        return {"context_id": context_id, "boundary": "codex_no_environments", "thread_id": "thread", "environments": [], "mcp_servers": [],
                "source_read": "host_witnessed", "canary_write": "host_denied_no_environment"}

    def turn(self, message):
        for count in range(200):
            response = self.on_tool({"arguments": {}, "callId": str(count)})
            state = json.loads(response["contentItems"][0]["text"])
            if state["status"] == "context_ready":
                return json.dumps({"valid": True, "summary": "Reviewed", "evidence": {}, "verdict": "approved",
                    "issues": [], "passed_checks": [], "failed_checks": [],
                    "receipt": {"covered_files": ["first.py"], "skipped_files": [], "denied_access": [], "check_evidence": []},
                    "context_receipt": {"session_id": state["session_id"], "finalization_token": state["finalization_token"]}})
            delivery = self.on_event.__self__
            complete_result(delivery, response, str(count))
            if self.interrupt_once:
                type(self).interrupt_once = False
                raise host.HostError("simulated interrupted host")
        raise AssertionError("unbounded transport")

    def close(self):
        pass


def test_driver_resume_same_thread_and_complete_receipts(repo, monkeypatch):
    del repo
    Path("first.py").write_text("value = 2\n")
    admission = runner.begin_review_run(branch="feature", provider="codex", mode="lightweight", round_id="host")
    assert admission["capability"]["status"] == "unverified"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    monkeypatch.setattr(driver, "CodexReviewHost", SimulatedHost)
    SimulatedHost.resumed = []
    SimulatedHost.interrupt_once = True
    with pytest.raises(host.HostError, match="interrupted"):
        driver.run("feature", review_preferences="Inspect dependencies carefully.\n")
    path = Path(".map/feature/review-verdict-ledger.json")
    before = json.loads(path.read_text())["convergence"]["rounds"][-1]
    with pytest.raises(host.HostError, match="preferences differ"):
        driver.run("feature", review_preferences="Different preferences")
    assert driver.run("feature")["status"] == "success"
    assert SimulatedHost.resumed == ["", "thread"]
    after = json.loads(path.read_text())["convergence"]["rounds"][-1]
    assert before["context_active"] == after["context_active"]
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "COMPLETE", result
    assert result["code_approval"]["approved"] is True
    session = next(iter(after["context_sessions"].values()))
    proof = path.parent / session["host_capability"]["artifact"]
    proof.write_text("{}")
    assert not runner._review_capability_verified(after, path.parent)


def test_completed_capture_reused_without_redispatch(repo, monkeypatch):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", mode="lightweight", round_id="host")
    runner.create_review_bundle(branch="feature")
    monkeypatch.setattr(driver, "CodexReviewHost", SimulatedHost)
    SimulatedHost.resumed = []
    driver.run("feature")
    resumed = list(SimulatedHost.resumed)
    result = driver.run("feature")
    assert result["reviewers"][0]["reused"] is True
    assert SimulatedHost.resumed == resumed


def test_explicit_optional_resource_starts_at_own_offset(repo):
    del repo
    delivery = admitted_delivery()
    response = delivery.respond({"arguments": {}, "callId": "call"})
    complete_result(delivery, response)
    ledger = runner._read_review_ledger(Path(".map/feature"))
    session = ledger["convergence"]["rounds"][-1]["context_sessions"][delivery.state["session_id"]]
    optional = next(key for key, value in session["available"].items() if value.get("path") == "dependency.py")
    response = delivery.respond({"arguments": {"resource_id": optional}, "callId": "optional"})
    assert json.loads(response["contentItems"][0]["text"])["offset"] == 0


def test_resume_transcript_ignores_old_turn_and_partial_append(tmp_path):
    client = object.__new__(host.CodexReviewHost)
    client.thread_id = "thread-id"
    path = tmp_path / "rollout-thread-id.jsonl"
    path.write_text(json.dumps({"type": "response_item", "payload": {"type": "additional_tools", "tools": []}}) + "\n")
    client.outer_history = []
    client._open_rollout(str(path))
    assert len(client.outer_history) == 1
    client.active_turn = "new"
    client.rollout_turn = ""
    client.rollout_complete = False
    observed = []
    client.handle = observed.append
    records = [
        {"type": "turn_context", "payload": {"turn_id": "old"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "old"}},
        {"type": "turn_context", "payload": {"turn_id": "new"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "new"}},
    ]
    with path.open("a") as stream:
        stream.write("".join(json.dumps(record) + "\n" for record in records))
        stream.write('{"type":"event_msg","payload":')
    client._drain_rollout()
    assert [event["params"]["item"]["call_id"] for event in observed] == ["new"]
    assert not client.rollout_complete
    with path.open("a") as stream:
        stream.write('{"type":"task_complete"}}\n')
    client._drain_rollout()
    assert client.rollout_complete


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_timeout_is_bounded(timeout):
    with pytest.raises(host.HostError, match="timeout"):
        driver.run(timeout=timeout)


@pytest.mark.parametrize("arguments", ["--adversarial --quick", "--adversarial --quick --compare-orderings"])
def test_driver_adversarial_roster_and_ordering_sessions(repo, monkeypatch, arguments):
    del repo
    Path("first.py").write_text("value = 2\n")
    admitted = runner.begin_review_run(branch="feature", provider="codex", arguments=arguments, round_id="host")
    assert admitted["status"] == "success", admitted
    runner.create_review_bundle(branch="feature")

    class AdversarialHost(SimulatedHost):
        def start(self, thread_id=""):
            identity = thread_id or f"thread-{len(self.resumed)}"
            self.resumed.append(identity)
            self.identity = identity
            return identity

        def probe(self, context_id):
            return {**super().probe(context_id), "thread_id": self.identity}

        def turn(self, message):
            for count in range(200):
                response = self.on_tool({"arguments": {}, "callId": str(count)})
                state = json.loads(response["contentItems"][0]["text"])
                if state["status"] == "context_ready":
                    return json.dumps({"reviewer": state["reviewer"], "all_clear": True,
                        "all_clear_rationale": "Read the changed source", "findings": [], "checks_performed": ["source"],
                        "receipt": {"covered_files": ["first.py"], "skipped_files": [], "denied_access": [], "check_evidence": []},
                        "context_receipt": {"session_id": state["session_id"], "finalization_token": state["finalization_token"]}})
                self.on_event({"method": "item/completed", "params": {"threadId": self.identity, "item": {
                    "type": "dynamicToolCall", "tool": "review_context", "id": str(count), "status": "completed", **response}}})
                self.on_event({"method": "rawResponseItem/completed", "params": {"threadId": self.identity, "item": {
                    "type": "custom_tool_call_output", "output": response["contentItems"][0]["text"]}}})
            raise AssertionError("unbounded delivery")

    AdversarialHost.resumed = []
    monkeypatch.setattr(driver, "CodexReviewHost", AdversarialHost)
    result = driver.run("feature")
    assert result["status"] == "success", result
    assert {entry["reviewer"] for entry in result["reviewers"]} == {"blind", "acceptance", "user_experience", "maintainer"}
    assert len(AdversarialHost.resumed) == (8 if "--compare-orderings" in arguments else 4)
    ledger = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert ledger["completeness"]["status"] == "COMPLETE", ledger
    assert ledger["code_approval"]["approved"] is True


@pytest.mark.parametrize("defect", ["missing_thread", "empty_thread", "wrong_thread", "missing_context", "wrong_context"])
def test_host_proof_rejects_unbound_identity_before_record(repo, defect):
    del repo
    delivery = admitted_delivery()
    proof = {**SimulatedHost().probe(), "context_id": delivery.state["context_id"]}
    if defect == "missing_thread":
        proof.pop("thread_id")
    elif defect == "empty_thread":
        proof["thread_id"] = ""
    elif defect == "wrong_thread":
        proof["thread_id"] = "another-thread"
    elif defect == "missing_context":
        proof.pop("context_id")
    else:
        proof["context_id"] = "another-context"
    result = runner._record_codex_host_capability(delivery.state["session_id"], proof, "host", branch="feature")
    assert result["status"] == "error", result
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert row["capability"]["status"] == "unverified"
    assert not row["context_sessions"][delivery.state["session_id"]].get("host_capability")


def test_resume_rejects_host_replacing_thread(tmp_path):
    client = object.__new__(host.CodexReviewHost)
    client.thread_id = "original"
    client.root = tmp_path
    client.overrides = {}
    client._open_rollout = lambda path: None
    client.call = lambda method, params: ({"thread": {"id": "replacement", "environments": [],
        "status": {"type": "idle"}, "path": "unused"}, "sandbox": {"type": "readOnly", "networkAccess": False}}
        if method == "thread/resume" else {"data": []})
    with pytest.raises(host.HostError, match="different thread"):
        client.start("original")
    assert client.thread_id == "original"


def test_adversarial_preferences_rejected_before_saving(repo, monkeypatch):
    del repo
    Path("first.py").write_text("value = 2\n")
    monkeypatch.setattr(driver, "CodexReviewHost", SimulatedHost)
    runner.begin_review_run(branch="feature", provider="codex", arguments="--adversarial --quick", round_id="preferences")
    runner.create_review_bundle(branch="feature")
    with pytest.raises(host.HostError, match="normal reviews"):
        driver.run("feature", review_preferences="Requested focus")
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert "codex_review_preferences" not in row
