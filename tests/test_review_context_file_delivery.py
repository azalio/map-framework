"""Direct file delivery: the reviewer reads a served path and proves it with a nonce (#650)."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_review_context_delivery import (
    bind,
    cli,
    final_envelope,
    prepare,
    runner,
)
from tests.test_review_context_delivery import repository as _repository

repository = _repository
__all__ = ["repository"]

NONCE_PREFIX = "MAP-CONTEXT-NONCE: "


def serve_file(state, resource=None):
    """Serve one whole resource as a context_file pointer through the bound session."""
    payload = {"type": "context_request", "context_id": state["context_id"],
               "resource_id": resource or state["remaining"][0]["resource_id"], "offset": 0}
    return runner.serve_review_context(state["reviewer"], json.dumps(payload), "delivery-round",
                                         branch="feature", session_id=state["session_id"],
                                         agent_id=state["agent_id"], delivery="file")


def read_nonce(served):
    """What the reviewer does with its Read tool: open exactly the served path and take the last line."""
    lines = Path(served["path"]).read_text(encoding="utf-8").splitlines()
    assert lines[-1].startswith(NONCE_PREFIX)
    return lines[-1].removeprefix(NONCE_PREFIX)


def file_ack(state, served, nonce):
    return {"type": "context_ack", "session_id": state["session_id"], "context_id": served["context_id"],
            "resource_id": served["resource_id"], "sha256": served["sha256"], "nonce": nonce}


def acknowledge(state, payload):
    return runner.ack_review_context(state["session_id"], state["agent_id"], json.dumps(payload),
                                       "delivery-round", branch="feature")


def deliver_all_files(state):
    while state["status"] == "context_pending":
        served = serve_file(state)
        assert served["type"] == "context_file", served
        state = acknowledge(state, file_ack(state, served, read_nonce(served)))
        assert state["status"] in {"context_pending", "context_ready"}, state
    return state


def test_context_file_is_a_small_pointer_and_never_carries_the_nonce_or_bytes(repository):
    state = bind(prepare()["monitor"])
    served = serve_file(state, "prompt")
    assert served["status"] == "context_response"
    assert set(served) >= {"type", "context_id", "resource_id", "session_id", "path", "sha256", "bytes",
                           "resource_sha256", "resource_bytes"}
    assert "content" not in served
    path = Path(served["path"])
    assert path.is_absolute() and path.is_file()
    assert path.is_relative_to((repository / ".map/feature/review-context-files").resolve())
    nonce = read_nonce(served)
    assert nonce and nonce not in json.dumps(served)
    body = path.read_bytes()
    view = body[: body.rindex(NONCE_PREFIX.encode())]
    assert len(view) == served["bytes"]
    assert hashlib.sha256(view).hexdigest() == served["sha256"]
    assert path.name.startswith(served["sha256"])
    assert len(json.dumps(served).encode()) < 1024
    # The served file carries the complete original text line by line, so Read can page through it.
    prompt = runner._review_context_read(repository / ".map/feature", state_resource(state, "prompt"))
    for line in prompt.decode().splitlines()[:5]:
        assert line in body.decode()


def state_resource(state, name):
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    return ledger["convergence"]["rounds"][-1]["context_sessions"][state["session_id"]]["available"][name]


def test_wrong_nonce_is_rejected_and_does_not_advance_delivery(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    before = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert acknowledge(state, file_ack(state, served, "0" * 32))["status"] == "error"
    forged_hash = {**file_ack(state, served, read_nonce(served)), "sha256": "0" * 64}
    assert acknowledge(state, forged_hash)["status"] == "error"
    assert runner.review_context_status(state["session_id"], "delivery-round", branch="feature") == before


def test_correct_nonce_acknowledges_and_replay_is_idempotent(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    proof = file_ack(state, served, read_nonce(served))
    advanced = acknowledge(state, proof)
    assert advanced["status"] in {"context_pending", "context_ready"}, advanced
    assert advanced["remaining_count"] == state["remaining_count"] - 1
    assert acknowledge(state, proof) == advanced
    assert acknowledge(state, file_ack(state, served, "f" * 32))["status"] == "error"


def test_no_finalization_token_until_every_required_resource_is_acknowledged(repository):
    del repository
    state = bind(prepare()["monitor"])
    early = json.dumps({"verdict": "approved", "issues": []})
    while True:
        served = serve_file(state)
        pending = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
        assert pending["status"] == "context_pending" and "finalization_token" not in pending
        assert runner.capture_review_output("monitor", early, "delivery-round", branch="feature")["status"] == "error"
        state = acknowledge(state, file_ack(state, served, read_nonce(served)))
        if state["status"] == "context_ready":
            break
        assert "finalization_token" not in state
    assert state["finalization_token"]
    captured = runner.capture_review_output("monitor", json.dumps(final_envelope(state)), "delivery-round",
                                              branch="feature")
    assert captured["status"] == "success", captured


def test_next_request_may_carry_the_previous_files_nonce(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    advanced_state = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    following = {"type": "context_request", "context_id": state["context_id"], "resource_id": "inventory",
                 "offset": 0, "ack": file_ack(state, served, read_nonce(served))}
    assert runner.serve_review_context("monitor", json.dumps(following), "delivery-round", branch="feature",
                                         session_id=state["session_id"], agent_id=state["agent_id"],
                                         delivery="file")["status"] == "error"
    acked = acknowledge(state, following)
    assert acked["remaining_count"] == advanced_state["remaining_count"] - 1
    nxt = runner.serve_review_context("monitor", json.dumps(following), "delivery-round", branch="feature",
                                        session_id=state["session_id"], agent_id=state["agent_id"], delivery="file")
    assert nxt["type"] == "context_file" and nxt["resource_id"] == "inventory"


def test_pending_file_blocks_other_resources_and_chunk_acks(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state, "manifest")
    assert serve_file(state, "inventory")["status"] == "error"
    again = serve_file(state, "manifest")
    assert again == served
    chunk_shaped = {"session_id": state["session_id"], "context_id": state["context_id"],
                    "resource_id": "manifest", "offset": 0, "next_offset": served["resource_bytes"],
                    "total_bytes": served["resource_bytes"], "sha256": served["resource_sha256"],
                    "chunk_sha256": served["resource_sha256"], "eof": True, "content": ""}
    assert acknowledge(state, chunk_shaped)["status"] == "error"


def test_other_session_nonce_cannot_acknowledge(repository):
    del repository
    entry = prepare()["monitor"]
    first = bind(entry)
    served = serve_file(first, "manifest")
    second = bind(entry, agent="replacement")
    other = serve_file(second, "manifest")
    assert other["path"] != served["path"]
    stolen = file_ack(second, other, read_nonce(served))
    assert acknowledge(second, stolen)["status"] == "error"


def test_file_delivery_requires_a_bound_session(repository):
    del repository
    entry = prepare()["monitor"]
    request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
               "resource_id": "manifest", "offset": 0}
    result = runner.serve_review_context("monitor", json.dumps(request), "delivery-round", branch="feature",
                                           delivery="file")
    assert result["status"] == "error"


def test_full_file_delivery_through_cli_reaches_capture(repository):
    del repository
    state = bind(prepare()["monitor"])
    while state["status"] == "context_pending":
        request = {"type": "context_request", "context_id": state["context_id"],
                   "resource_id": state["remaining"][0]["resource_id"], "offset": 0}
        served = cli("serve_review_context", "--reviewer", "monitor", "--round-id", "delivery-round",
                     "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                     "--delivery", "file", payload=json.dumps(request))
        assert served["type"] == "context_file", served
        state = cli("ack_review_context", "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                    "--round-id", "delivery-round", payload=json.dumps(file_ack(state, served, read_nonce(served))))
    assert state["status"] == "context_ready"
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(state)), "delivery-round",
                                          branch="feature")["status"] == "success"


def test_context_ack_is_classified_as_intermediate_not_final(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    proof = json.dumps(file_ack(state, served, read_nonce(served)))
    classified = runner.serve_review_context("monitor", proof, "delivery-round", branch="feature",
                                               session_id=state["session_id"], agent_id=state["agent_id"])
    assert classified["status"] == "context_ack"
    assert runner.capture_review_output("monitor", proof, "delivery-round", branch="feature")["status"] == "error"


def test_file_delivery_leaves_admission_budget_math_unchanged(repository):
    """Budgets count frozen resource bytes; the served view and nonce never enter that sum."""
    entry = prepare()["monitor"]
    state = bind(entry)
    before = {item["resource_id"]: item for item in [state["remaining"][0]]}
    totals_before = state["remaining_count"]
    objects = sorted(p.name for p in (repository / ".map/feature/review-context-objects").iterdir())
    ready = deliver_all_files(state)
    assert ready["status"] == "context_ready"
    assert sorted(p.name for p in (repository / ".map/feature/review-context-objects").iterdir()) == objects
    first = next(iter(before.values()))
    assert first["total_bytes"] == state_resource(state, first["resource_id"])["bytes"]
    assert totals_before >= 1
    rebuilt = runner.build_review_prompts(branch="feature")
    assert rebuilt["status"] == "success"
    transport = rebuilt["prompts"]["monitor"]["context_transport"]
    assert transport["manifest_bytes"] == entry["context_transport"]["manifest_bytes"]
    assert transport["original_prompt_bytes"] == entry["context_transport"]["original_prompt_bytes"]


@pytest.mark.parametrize("resource", ["manifest", "prompt", "inventory"])
def test_view_preserves_every_text_line_of_the_frozen_resource(repository, resource):
    state = bind(prepare()["monitor"])
    served = serve_file(state, resource)
    raw = runner._review_context_read(repository / ".map/feature", state_resource(state, resource)
                                        if resource != "manifest" else {"sha256": state["context_id"],
                                                                          "bytes": served["resource_bytes"]})
    assert len(raw) == served["resource_bytes"]
    body = Path(served["path"]).read_text(encoding="utf-8")
    lines = body.splitlines()
    assert lines[0] == "MAP-CONTEXT-FILE v1"
    # No physical line in the view is longer than the longest line of any decoded string value.
    value = json.loads(raw) if resource != "prompt" else raw.decode()

    def longest(node):
        if isinstance(node, str):
            return max((len(part) for part in node.split("\n")), default=0)
        if isinstance(node, dict):
            return max([longest(v) for v in node.values()] + [len(json.dumps(k)) for k in node] + [0])
        if isinstance(node, list):
            return max([longest(v) for v in node] + [0])
        return len(json.dumps(node))

    assert max(len(line) for line in lines) <= max(200, longest(value) + 64)


def test_view_text_blocks_reconstruct_every_string_exactly():
    content = "line one\n  indented \"quoted\"\n\nlast"
    resource = {"path": "a.py", "current_content": content + "\n", "long": "x" * 1500,
                "line_mapping": [[index, index] for index in range(60)]}
    raw = json.dumps(resource, sort_keys=True).encode()
    view = runner._review_context_view("source_000000", raw, "0" * 64)
    lines = view.split("\n")
    assert lines[-1] == ""
    blocks = {}
    for number, line in enumerate(lines, 1):
        if line.startswith("=== TEXT "):
            fields = dict(item.split("=", 1) for item in line.removesuffix(" ===").split()[4:])
            start, count = int(fields["first_line"]), int(fields["lines"])
            assert start == number + 1
            text = "\n".join(lines[start - 1:start - 1 + count])
            blocks[line.split()[3]] = text + ("\n" if fields["final_newline"] == "true" else "")
    assert blocks['$["current_content"]'] == content + "\n"
    assert blocks['$["long"]'] == "x" * 1500
    assert max(len(line) for line in lines if not line.startswith("x" * 100)) <= 200


def serve_batch(state):
    payload = {"type": "context_request", "context_id": state["context_id"],
               "resource_id": "*required", "offset": 0}
    return runner.serve_review_context(state["reviewer"], json.dumps(payload), "delivery-round",
                                         branch="feature", session_id=state["session_id"],
                                         agent_id=state["agent_id"], delivery="file")


def test_one_batch_file_delivers_every_remaining_required_resource(repository):
    """One served file and one nonce cover all unacknowledged required resources (#650 scaling)."""
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    state = acknowledge(state, file_ack(state, first, read_nonce(first)))
    assert state["status"] == "context_pending" and state["remaining_count"] >= 2
    session = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())[
        "convergence"]["rounds"][-1]["context_sessions"][state["session_id"]]
    expected = [name for name, item in session["required"].items()
                if session["offsets"].get(name, 0) != item["bytes"]]
    served = serve_batch(state)
    assert served["type"] == "context_file" and served["resource_id"] == "*required", served
    assert served["resources"] == expected
    body = Path(served["path"]).read_text(encoding="utf-8")
    for name in expected:
        assert f"resource_id: {name}\n" in body
    assert first["resource_id"] not in served["resources"]
    assert serve_batch(state) == served
    assert serve_file(state, expected[0])["status"] == "error"
    assert acknowledge(state, file_ack(state, served, "0" * 32))["status"] == "error"
    ready = acknowledge(state, file_ack(state, served, read_nonce(served)))
    assert ready["status"] == "context_ready" and ready["finalization_token"], ready
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(ready)), "delivery-round",
                                          branch="feature")["status"] == "success"


def test_batch_request_through_cli_reaches_ready_in_one_round_trip(repository):
    del repository
    state = bind(prepare()["monitor"])
    request = {"type": "context_request", "context_id": state["context_id"], "resource_id": "*required",
               "offset": 0}
    served = cli("serve_review_context", "--reviewer", "monitor", "--round-id", "delivery-round",
                 "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                 "--delivery", "file", payload=json.dumps(request))
    assert "manifest" in served["resources"]
    ready = cli("ack_review_context", "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                "--round-id", "delivery-round", payload=json.dumps(file_ack(state, served, read_nonce(served))))
    assert ready["status"] == "context_ready", ready


def test_batch_request_requires_file_delivery(repository):
    del repository
    state = bind(prepare()["monitor"])
    payload = {"type": "context_request", "context_id": state["context_id"], "resource_id": "*required",
               "offset": 0}
    result = runner.serve_review_context("monitor", json.dumps(payload), "delivery-round", branch="feature",
                                           session_id=state["session_id"], agent_id=state["agent_id"],
                                           delivery="chunk")
    assert result["status"] == "error"


def test_codex_prompt_keeps_single_resource_requests(repository):
    del repository
    assert '"*required"' not in prepare()["monitor"]["prompt"]


def test_file_reader_prompt_asks_for_the_batch_first(repository):
    del repository
    admitted = runner.begin_review_run(round_id="claude-round", provider="claude", branch="feature")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    prompt = built["prompts"]["monitor"]["prompt"]
    assert '"resource_id": "*required"' in prompt
    assert 'First request resource_id "*required"' in prompt
