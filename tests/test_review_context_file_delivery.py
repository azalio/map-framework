"""Direct file delivery: the reviewer reads a served path and proves it with a nonce (#650)."""

import hashlib
import json
import re
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

PROOF_LINE = re.compile(r"^proof: (\d+) fragments, each a standalone lowercase hex token of exactly (\d+) characters")


def proof_fragments(path):
    """What a sequential reader does: take the format from line 2, then collect every matching token in order."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    header = PROOF_LINE.match(lines[1])
    assert header, lines[1]
    pattern = re.compile(rf"(?<![0-9A-Za-z])[0-9a-f]{{{header.group(2)}}}(?![0-9A-Za-z])")
    found = pattern.findall("\n".join(lines[2:]))
    assert len(found) == int(header.group(1))
    return found


def serve_file(state, resource=None):
    """Serve one whole resource as a context_file pointer through the bound session."""
    payload = {"type": "context_request", "context_id": state["context_id"],
               "resource_id": resource or state["remaining"][0]["resource_id"], "offset": 0}
    return runner.serve_review_context(state["reviewer"], json.dumps(payload), "delivery-round",
                                         branch="feature", session_id=state["session_id"],
                                         agent_id=state["agent_id"], delivery="file")


def read_nonce(served):
    """The proof a reader returns: every fragment of the served file, concatenated in file order."""
    return "".join(proof_fragments(served["path"]))


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


def test_context_file_is_a_small_pointer_and_never_carries_the_proof_or_bytes(repository):
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
    assert "nonce_line" not in served
    body = path.read_bytes()
    assert b"MAP-CONTEXT-NONCE" not in body
    assert len(body) == served["bytes"]
    assert hashlib.sha256(body).hexdigest() == served["sha256"]
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


def test_unread_role_rubric_is_not_reported_as_denied_review_scope():
    prompt = runner._render_review_prompt(runner.REVIEW_PROMPT_SPECS["monitor"], "B", "P", "D")
    assert "If unavailable, report denied_access" not in prompt
    assert "never list it in skipped_files or denied_access" in prompt
    assert "denied_access names only required review scope the parent refused to serve" in prompt


def served_batch_file():
    state = bind(prepare()["monitor"])
    return state, serve_batch(state)


def fragment_line_numbers(path):
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    header = PROOF_LINE.match(lines[1])
    assert header is not None, lines[1]
    length = int(header.group(2))
    pattern = re.compile(rf"(?<![0-9A-Za-z])[0-9a-f]{{{length}}}(?![0-9A-Za-z])")
    return lines, [number for number, line in enumerate(lines) if number >= 2 and pattern.search(line)]


def test_vc_proof_has_no_fixed_marker_or_grep_handle(repository):
    """A single Grep for the old marker yields nothing; the proof is scattered through the body."""
    del repository
    _, served = served_batch_file()
    body = Path(served["path"]).read_text(encoding="utf-8")
    assert "NONCE" not in body and "nonce" not in body.lower()
    assert "nonce_line" not in served and "last line" not in body
    lines, numbers = fragment_line_numbers(served["path"])
    assert len(numbers) >= 4
    last_content = max(index for index, line in enumerate(lines) if line.strip())
    assert numbers[0] > 1 and numbers[-1] < last_content
    # Each fragment line is syntactically a pair line of the view, with no fixed prefix.
    for number in numbers:
        assert re.fullmatch(r'\s*"[^"\n]+": "[0-9a-f]+",', lines[number]), lines[number]
    keys = {match.group(1) for number in numbers if (match := re.match(r'\s*("[^"\n]+")', lines[number]))}
    assert len(keys) > 1


def test_vc_fragment_count_scales_with_bytes_and_is_spread_through_the_body():
    resource = {"path": "a.py", "current_content": "".join(f"line {n}\n" for n in range(20000))}
    raw = json.dumps(resource, sort_keys=True).encode()
    view = runner._review_context_view("source_000000", raw, "0" * 64, part_bytes=4096)
    for size, expected in ((100, 4), (16 * 1024 * 40, 40), (16 * 1024 * 500, 64)):
        text, proof, count = runner._review_embed_proof(view, size)
        assert count == expected and len(proof) % count == 0
    lines = text.split("\n")
    header = PROOF_LINE.match(lines[1])
    assert header is not None, lines[1]
    pattern = re.compile(rf"(?<![0-9A-Za-z])[0-9a-f]{{{header.group(2)}}}(?![0-9A-Za-z])")
    numbers = [number for number, line in enumerate(lines) if number >= 2 and pattern.search(line)]
    assert len(numbers) == 64
    quarters = [sum(1 for n in numbers if lo <= n / len(lines) < lo + 0.25) for lo in (0, 0.25, 0.5, 0.75)]
    assert all(quarter >= 8 for quarter in quarters), quarters


def test_vc_text_blocks_stay_exact_and_first_line_tracks_the_published_file():
    content = "".join(f"row {n}\n" for n in range(3000))
    raw = json.dumps({"path": "a.py", "current_content": content}, sort_keys=True).encode()
    view = runner._review_context_view("source_000000", raw, "0" * 64, part_bytes=2048)
    text, _, _ = runner._review_embed_proof(view, len(raw))
    lines = text.split("\n")
    rebuilt = []
    for number, line in enumerate(lines):
        header = re.fullmatch(r"=== TEXT \d+ .* lines=(\d+) first_line=(\d+) final_newline=(\w+).*===", line)
        if header:
            count, first = int(header.group(1)), int(header.group(2))
            assert first == number + 2
            rebuilt.extend(lines[first - 1:first - 1 + count])
    assert "\n".join(rebuilt) + "\n" == content


def test_vc_partial_or_reordered_fragments_are_rejected(repository):
    del repository
    state, served = served_batch_file()
    fragments = proof_fragments(served["path"])
    for wrong in ("".join(fragments[:-1]), "".join(reversed(fragments))):
        assert acknowledge(state, file_ack(state, served, wrong))["status"] == "error"
    separated = " ".join(fragments)
    assert acknowledge(state, file_ack(state, served, separated))["status"] == "context_ready"


def test_vc_fragments_are_never_stored_in_the_ledger(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    ledger = Path(".map/feature/review-verdict-ledger.json").read_text()
    assert all(fragment not in ledger for fragment in proof_fragments(served["path"]))
    assert hashlib.sha256(read_nonce(served).encode()).hexdigest() in ledger


def test_vc_proof_comparison_is_constant_time(repository, monkeypatch):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    calls = []
    original = runner.hmac.compare_digest
    monkeypatch.setattr(runner.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or original(a, b))
    acknowledge(state, file_ack(state, served, "0" * 32))
    assert calls


def test_vc_three_wrong_proofs_invalidate_the_delivery_and_reserve_gives_fresh_fragments(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    old_proof = read_nonce(served)
    for attempt in range(3):
        result = acknowledge(state, file_ack(state, served, "0" * 32))
        assert result["status"] == "error"
        assert ("invalidated" in result["message"]) is (attempt == 2)
    # The right proof no longer works once the delivery was invalidated.
    assert acknowledge(state, file_ack(state, served, old_proof))["status"] == "error"
    again = serve_file(state)
    assert again["type"] == "context_file" and again["sha256"] != served["sha256"]
    assert read_nonce(again) != old_proof
    assert acknowledge(state, file_ack(state, again, old_proof))["status"] == "error"
    assert acknowledge(state, file_ack(state, again, read_nonce(again)))["status"] in {
        "context_pending", "context_ready"}


def test_vc_ack_rebinds_content_a_rewritten_body_is_rejected(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    path = Path(served["path"])
    proof = read_nonce(served)
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("resource_id", "resource_ID", 1), encoding="utf-8")
    assert path.read_text(encoding="utf-8") != original
    before = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    result = acknowledge(state, file_ack(state, served, proof))
    assert result["status"] == "error" and "changed after publication" in result["message"]
    after = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert (after["remaining"], after["remaining_count"]) == (before["remaining"], before["remaining_count"])
    fresh = serve_file(state)
    assert acknowledge(state, file_ack(state, fresh, read_nonce(fresh)))["status"] in {
        "context_pending", "context_ready"}


def test_vc_rewritten_batch_body_cannot_advance_delivery(repository):
    del repository
    state, served = served_batch_file()
    path = Path(served["path"])
    proof = read_nonce(served)
    path.write_text(path.read_text(encoding="utf-8").replace("resource_id", "resource_ID", 1), encoding="utf-8")
    assert acknowledge(state, file_ack(state, served, proof))["status"] == "error"
    assert runner.review_context_status(state["session_id"], "delivery-round",
                                        branch="feature")["status"] == "context_pending"


def context_files_dir():
    return Path(".map/feature/review-context-files")


def test_vc_session_files_are_deleted_once_its_delivery_is_complete(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    assert Path(served["path"]).is_file()
    ready = deliver_all_files(acknowledge(state, file_ack(state, served, read_nonce(served))))
    assert ready["status"] == "context_ready"
    assert not (context_files_dir() / state["session_id"]).exists()
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    files = ledger["convergence"]["rounds"][-1]["context_sessions"][state["session_id"]]["files"]
    assert files and all(len(record["sha256"]) == 64 and len(record["nonce_sha256"]) == 64 for record in files.values())
    assert runner.review_context_status(state["session_id"], "delivery-round",
                                        branch="feature")["status"] == "context_ready"


def test_vc_incomplete_session_keeps_its_file_for_retries(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    assert Path(served["path"]).is_file()
    assert serve_file(state) == served


def test_vc_abandoning_a_round_removes_every_context_file(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    assert Path(served["path"]).is_file()
    result = runner.abandon_review_round("delivery-round", "operator abandoned", branch="feature")
    assert result["status"] == "success", result
    assert not context_files_dir().exists()


def test_vc_completing_a_round_removes_every_context_file(repository):
    del repository
    state = bind(prepare()["monitor"])
    served = serve_file(state)
    assert Path(served["path"]).is_file()
    ledger_path = Path(".map/feature/review-verdict-ledger.json")
    ledger = json.loads(ledger_path.read_text())
    row = ledger["convergence"]["rounds"][-1]
    runner._review_purge_context_files(ledger_path.parent, None)
    assert not context_files_dir().exists()
    assert row["round_id"] == "delivery-round"


def claude_round():
    """A Read-capable (Claude) round whose prompts know file delivery; returns its bound monitor session."""
    admitted = runner.begin_review_run(round_id="claude-round", provider="claude", branch="feature")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    context_id = built["prompts"]["monitor"]["context_transport"]["context_id"]
    return runner.bind_review_context("monitor", context_id, "native-agent", "claude-round", branch="feature")


def strip_file_delivery_marker():
    """Model a round admitted by 3.37.0: its manifests carry no file-delivery marker."""
    path = Path(".map/feature/review-verdict-ledger.json")
    ledger = json.loads(path.read_text())
    for entry in ledger["convergence"]["rounds"][-1]["context_manifests"].values():
        entry.pop("file_delivery", None)
    path.write_text(json.dumps(ledger))


def cli_serve(state, resource, *extra):
    request = {"type": "context_request", "context_id": state["context_id"], "resource_id": resource, "offset": 0}
    return cli("serve_review_context", "--reviewer", "monitor", "--round-id", "claude-round",
               "--session-id", state["session_id"], "--agent-id", state["agent_id"], *extra,
               payload=json.dumps(request))


def test_vc_new_read_capable_round_defaults_to_file_delivery(repository):
    del repository
    state = claude_round()
    assert cli_serve(state, "*required")["type"] == "context_file"


def test_vc_codex_round_defaults_to_chunk_delivery(repository):
    del repository
    state = bind(prepare()["monitor"])
    request = {"type": "context_request", "context_id": state["context_id"],
               "resource_id": state["remaining"][0]["resource_id"], "offset": 0}
    served = cli("serve_review_context", "--reviewer", "monitor", "--round-id", "delivery-round",
                 "--session-id", state["session_id"], "--agent-id", state["agent_id"], payload=json.dumps(request))
    assert served["type"] == "context_chunk", served


def test_vc_round_admitted_before_file_delivery_resumes_with_chunk_by_default(repository):
    del repository
    state = claude_round()
    strip_file_delivery_marker()
    # Resuming on the new runner rebuilds the prompts; the frozen ones still only know context_chunk.
    assert runner.build_review_prompts(branch="feature")["status"] == "success"
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    assert not any(entry.get("file_delivery") for entry in
                   ledger["convergence"]["rounds"][-1]["context_manifests"].values())
    served = cli_serve(state, state["remaining"][0]["resource_id"])
    assert served["type"] == "context_chunk", served
    # The whole delivery of the pending round completes by chunks through the CLI default.
    while state["status"] == "context_pending":
        chunk = cli_serve(state, state["remaining"][0]["resource_id"])
        assert chunk["type"] == "context_chunk", chunk
        state = cli("ack_review_context", "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                    "--round-id", "claude-round", payload=json.dumps(chunk))
    assert state["status"] == "context_ready"
