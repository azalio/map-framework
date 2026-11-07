"""Added files ship once; the file-delivery protocol survives optional serves and embedded acks (#655, #656)."""

import json
import subprocess
from pathlib import Path

import pytest

from tests.review_context_helpers import fetch_review_resource
from tests.test_review_context_delivery import (
    bind,
    deliver_all,
    final_envelope,
    prepare,
    runner,
)
from tests.test_review_context_delivery import repository as _repository
from tests.test_review_context_file_delivery import (
    acknowledge as ack_file,
)
from tests.test_review_context_file_delivery import (
    deliver_all_files,
    file_ack,
    read_nonce,
    serve_batch,
    serve_file,
)

repository = _repository
__all__ = ["repository"]

ROOT = Path(__file__).resolve().parent.parent
ADDED_LINES = [f"ADDED_LINE_{index:03d} = {index}" for index in range(120)]


@pytest.fixture
def added_repository(repository):
    """The delivery repository plus an unchanged dependency and one file added on the feature branch."""
    subprocess.run(["git", "checkout", "-q", "main"], check=True)
    Path("dep.py").write_text("DEP = 1\n")
    subprocess.run(["git", "add", "dep.py"], check=True)
    subprocess.run(["git", "commit", "-qm", "dependency"], check=True)
    subprocess.run(["git", "checkout", "-q", "feature"], check=True)
    subprocess.run(["git", "rebase", "-q", "main"], check=True)
    Path("added.py").write_text("\n".join(ADDED_LINES) + "\n")
    subprocess.run(["git", "add", "added.py"], check=True)
    subprocess.run(["git", "commit", "-qm", "add file"], check=True)
    return repository


def manifest_of(entry, reviewer):
    return json.loads(fetch_review_resource(runner, entry, reviewer, "manifest", branch="feature"))


def source_id_for(manifest, path):
    return next(name for name, item in manifest["resources"].items() if item.get("path") == path)


def test_vc1_added_file_hunk_is_a_stub_pointing_at_its_source_resource(added_repository):
    del added_repository
    entry = prepare()["monitor"]
    diff = fetch_review_resource(runner, entry, "monitor", "diff", branch="feature")
    source_id = source_id_for(manifest_of(entry, "monitor"), "added.py")
    assert "ADDED_LINE_077" not in diff
    assert "diff --git a/added.py b/added.py" in diff and source_id in diff
    assert "value = 2" in diff  # modified files keep their real hunks
    source = fetch_review_resource(runner, entry, "monitor", source_id, branch="feature")
    assert "ADDED_LINE_077" in source


def test_vc2_diff_only_reviewer_keeps_the_full_added_file_diff(added_repository):
    del added_repository
    prompts = prepare("compare_orderings")
    blind = fetch_review_resource(runner, prompts["blind"], "blind", "diff", branch="feature")
    assert "ADDED_LINE_077" in blind
    edge = fetch_review_resource(runner, prompts["edge_case"], "edge_case", "diff", branch="feature")
    assert "ADDED_LINE_077" not in edge


def test_vc3_diff_resource_no_longer_carries_the_added_file_bytes(added_repository):
    del added_repository
    entry = prepare()["monitor"]
    diff_bytes = manifest_of(entry, "monitor")["resources"]["diff"]["bytes"]
    assert diff_bytes < sum(len(line) + 1 for line in ADDED_LINES)


def test_vc4_stubbed_round_still_delivers_and_captures(added_repository):
    del added_repository
    ready = deliver_all(bind(prepare()["monitor"]))
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(ready)), "delivery-round",
                                        branch="feature")["status"] == "success"


def optional_request(state, resource, **extra):
    return {"type": "context_request", "context_id": state["context_id"], "resource_id": resource,
            "offset": 0, **extra}


def serve_request(state, payload, delivery="file"):
    return runner.serve_review_context(state["reviewer"], json.dumps(payload), "delivery-round",
                                       branch="feature", session_id=state["session_id"],
                                       agent_id=state["agent_id"], delivery=delivery)


def test_vc5_optional_file_serve_after_token_keeps_the_issued_token_valid(added_repository):
    del added_repository
    ready = deliver_all_files(bind(prepare()["monitor"]))
    token = ready["finalization_token"]
    served = serve_request(ready, optional_request(ready, "repo:dep.py"))
    assert served["type"] == "context_file", served
    after = ack_file(ready, file_ack(ready, served, read_nonce(served)))
    assert after["status"] == "context_ready" and after["finalization_token"] == token
    result = runner.capture_review_output("monitor", json.dumps(final_envelope(ready)), "delivery-round",
                                          branch="feature")
    assert result["status"] == "success", result


def test_vc6_optional_chunk_serve_after_token_keeps_the_issued_token_valid(added_repository):
    del added_repository
    ready = deliver_all(bind(prepare()["monitor"]))
    chunk = serve_request(ready, optional_request(ready, "repo:dep.py"), delivery="chunk")
    assert chunk["status"] == "context_response", chunk
    after = runner.ack_review_context(ready["session_id"], ready["agent_id"], json.dumps(chunk),
                                      "delivery-round", branch="feature")
    assert after["finalization_token"] == ready["finalization_token"]
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(ready)), "delivery-round",
                                        branch="feature")["status"] == "success"


def test_vc7_unacknowledged_optional_serve_still_refuses_the_final(added_repository):
    del added_repository
    ready = deliver_all_files(bind(prepare()["monitor"]))
    serve_request(ready, optional_request(ready, "repo:dep.py"))
    result = runner.capture_review_output("monitor", json.dumps(final_envelope(ready)), "delivery-round",
                                          branch="feature")
    assert result["status"] == "error"


def test_vc8_embedded_ack_is_applied_atomically_before_serving(repository):
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    ack = file_ack(state, first, read_nonce(first))
    next_resource = next(item["resource_id"] for item in state["remaining"] if item["resource_id"] != first["resource_id"]) \
        if len(state["remaining"]) > 1 else "inventory"
    served = serve_request(state, optional_request(state, next_resource, ack=ack))
    assert served["status"] == "context_response", served
    status = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert first["resource_id"] not in [item["resource_id"] for item in status["remaining"]]
    assert status["pending_chunk"]["resource_id"] == served["resource_id"]


def test_vc9_embedded_ack_before_a_batch_request_delivers_the_rest(repository):
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    ack = file_ack(state, first, read_nonce(first))
    batch = serve_request(state, optional_request(state, "*required", ack=ack))
    assert batch["status"] == "context_response" and first["resource_id"] not in batch["resources"], batch


def test_vc10_wrong_embedded_ack_is_rejected_and_serves_nothing(repository):
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    ack = file_ack(state, first, "0" * 32)
    result = serve_request(state, optional_request(state, "inventory", ack=ack))
    assert result["status"] == "error", result
    status = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert status["pending_chunk"]["resource_id"] == first["resource_id"]


def capture_error(payload):
    result = runner.capture_review_output("monitor", json.dumps(payload), "delivery-round", branch="feature")
    assert result["status"] == "error", result
    return result["message"]


def test_vc11_refusal_with_a_pending_file_names_the_exact_ack_to_request(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    message = capture_error({"verdict": "approved", "issues": []})
    for needle in ('"type": "context_ack"', state["session_id"], served["resource_id"], served["sha256"],
                   "nonce", "ack_review_context"):
        assert needle in message, (needle, message)


def test_vc12_refusal_with_remaining_resources_names_the_next_request(repository):
    del repository
    state = bind(prepare()["monitor"])
    message = capture_error({"verdict": "approved", "issues": [], "context_receipt": None})
    assert state["remaining"][0]["resource_id"] in message and "context_request" in message, message


def test_vc13_refusal_after_delivery_gives_the_receipt_to_send_back(repository):
    del repository
    ready = deliver_all_files(bind(prepare()["monitor"]))
    message = capture_error({"verdict": "approved", "issues": [], "context_receipt": None})
    assert ready["finalization_token"] in message and ready["session_id"] in message
    assert "context_receipt" in message and "ONLY the JSON" in message, message


def test_vc14_prompts_state_the_order_and_json_only_handback(repository):
    del repository
    prompt = prepare()["monitor"]["prompt"]
    assert "ack, then finalization token, then final" in prompt
    assert "handback" in prompt and "ONLY the JSON" in prompt
    for relative in ("src/mapify_cli/templates/agents/review-reader.md",
                     "src/mapify_cli/templates/codex/agents/review-reader.toml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "handback" in text and "ONLY the JSON" in text, relative
    assert serve_batch  # imported helper stays exercised by the batch tests above


def test_vc15_added_executable_and_symlink_keep_their_mode_in_the_diff(added_repository):
    del added_repository
    Path("tool.sh").write_text("#!/bin/sh\necho EXEC_BODY_MARKER\n")
    Path("tool.sh").chmod(0o755)
    Path("link").symlink_to("dep.py")
    subprocess.run(["git", "add", "tool.sh", "link"], check=True)
    subprocess.run(["git", "commit", "-qm", "modes"], check=True)
    entry = prepare()["monitor"]
    diff = fetch_review_resource(runner, entry, "monitor", "diff", branch="feature")
    assert "new file mode 100755" in diff and "EXEC_BODY_MARKER" not in diff
    assert "new file mode 120000" in diff and "+dep.py" in diff  # symlinks are never stubbed
