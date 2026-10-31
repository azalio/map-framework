"""Delivery ACKs survive restarts and fence final replies independently of capability."""

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.test_review_trusted_policy import SCRIPTS, git, runner


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A real small Git snapshot keeps lifecycle tests focused on delivery state."""
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    Path(".gitignore").write_text(".map/\n")
    Path("code.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    Path("code.py").write_text("value = 2\n")
    git("commit", "-qam", "change")
    return tmp_path


def prepare(mode="normal"):
    """Admit one snapshot and build its role-scoped immutable resources."""
    admitted = runner.begin_review_run(review_mode=mode, arguments="--adversarial --compare-orderings" if mode == "compare_orderings" else "", round_id="delivery-round", provider="codex", branch="feature")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    builder = runner.build_adversarial_review_prompts if mode != "normal" else runner.build_review_prompts
    built = builder(branch="feature")
    assert built["status"] == "success", built
    return built["prompts"]


def bind(entry, role="monitor", agent="native-agent", ordering=""):
    """Bind only after the test's simulated host has accepted the initial dispatch."""
    result = runner.bind_review_context(role, entry["context_transport"]["context_id"], agent,
                                       "delivery-round", branch="feature", ordering=ordering)
    assert result["status"] == "context_pending", result
    return result


def serve(state, resource=None, offset=None, chunk_bytes=65536):
    """Issue bytes without claiming that the host has accepted them."""
    missing = state["remaining"][0]
    payload = {"type": "context_request", "context_id": state["context_id"],
               "resource_id": resource or missing["resource_id"],
               "offset": missing["offset"] if offset is None else offset}
    return runner.serve_review_context(state["reviewer"], json.dumps(payload), "delivery-round",
                                      branch="feature", session_id=state["session_id"],
                                      agent_id=state["agent_id"], chunk_bytes=chunk_bytes)


def acknowledge(state, chunk):
    """Model the parent ACK after native followup acceptance, never after mere serving."""
    return runner.ack_review_context(state["session_id"], state["agent_id"], json.dumps(chunk),
                                    "delivery-round", branch="feature")


def deliver_all(state):
    """Drain required resources through separate serve and host-acceptance acknowledgments."""
    while state["status"] == "context_pending":
        chunk = serve(state)
        assert chunk["status"] == "context_response", chunk
        state = acknowledge(state, chunk)
        assert state["status"] in {"context_pending", "context_ready"}, state
    return state


def final_envelope(state):
    """Only a post-delivery finalization request reveals the token echoed by this response."""
    return {"verdict": "approved", "issues": [],
            "context_receipt": {"session_id": state["session_id"],
                                "finalization_token": state["finalization_token"]}}


def cli(*args, payload=None):
    """Each call is a fresh process with no shared in-memory transport state."""
    result = subprocess.run([sys.executable, str(SCRIPTS / "map_step_runner.py"), *args],
                            input=payload, capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_chunk_pair_fingerprints_once_per_publication(repository, monkeypatch):
    """Serve and ACK each retain one fresh guard without rediscovering trusted policy."""
    del repository
    state = bind(prepare()["monitor"])
    counts = {"_review_target": 0, "_review_trusted_policy": 0}

    def observe(name):
        """Count actual expensive observations while preserving their implementation."""
        original = getattr(runner, name)

        def counted(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(runner, name, counted)

    for name in counts:
        observe(name)
    chunk = serve(state)
    assert chunk["status"] == "context_response"
    assert acknowledge(state, chunk)["status"] == "context_pending"
    assert counts == {"_review_target": 2, "_review_trusted_policy": 2}


@pytest.mark.parametrize("operation", ["serve", "bind", "status", "ack", "ack_replay"])
@pytest.mark.parametrize("changed", ["source", "policy", "bundle"])
def test_change_during_resource_read_blocks_publication(repository, monkeypatch, operation, changed):
    """A change after initial validation must not publish bytes, progress or a final token."""
    entry = prepare()["monitor"]
    state = bind(entry)
    chunk = serve(state)
    if operation == "ack_replay":
        state = acknowledge(state, chunk)
    ledger_path = repository / ".map/feature/review-verdict-ledger.json"
    before = ledger_path.read_bytes()
    row = json.loads(before)["convergence"]["rounds"][-1]
    target = {
        "source": repository / "code.py",
        "policy": repository / ".map/feature/spec_changed.md",
        "bundle": ledger_path.parent / row["bundle_receipt"]["artifact"],
    }[changed]
    original = runner._review_context_read
    mutated = False

    def read_then_change(*args, **kwargs):
        """Inject a concurrent edit after frozen resource bytes have been verified."""
        nonlocal mutated
        raw = original(*args, **kwargs)
        if not mutated:
            target.write_text("changed during delivery\n")
            mutated = True
        return raw

    monkeypatch.setattr(runner, "_review_context_read", read_then_change)
    if operation == "serve":
        result = serve(state)
    elif operation == "bind":
        result = runner.bind_review_context("monitor", entry["context_transport"]["context_id"],
                                            "new-agent", "delivery-round", branch="feature")
    elif operation == "status":
        result = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    else:
        result = acknowledge(state, chunk)
    assert mutated
    assert result["status"] == "error", result
    assert ledger_path.read_bytes() == before


def test_early_final_stays_rejected_after_delivery_until_new_finalization_token(repository):
    """A queued early response cannot become valid merely because ACKs arrived later."""
    prompts = prepare()
    state = bind(prompts["monitor"])
    early = json.dumps({"verdict": "approved", "issues": []})
    assert runner.capture_review_output("monitor", early, "delivery-round", branch="feature")["status"] == "error"
    chunk = serve(state)
    status = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert status["status"] == "context_pending" and "finalization_token" not in status
    assert status["remaining"] == state["remaining"]
    state = deliver_all(acknowledge(state, chunk))
    assert runner.capture_review_output("monitor", early, "delivery-round", branch="feature")["status"] == "error"
    response = final_envelope(state)
    assert runner.capture_review_output("monitor", json.dumps(response), "delivery-round", branch="feature")["status"] == "success"
    ledger = json.loads((repository / ".map/feature/review-verdict-ledger.json").read_text())
    assert ledger["convergence"]["rounds"][-1]["capability"]["status"] == "unverified"
    assert not ledger.get("code_approval", {}).get("approved", False)


def test_restart_after_issue_and_after_ack_preserves_pending_prefix_and_token(repository):
    """Crash before ACK redelivers; crash after ACK resumes from durable progress."""
    del repository
    state = bind(prepare()["monitor"])
    chunk = serve(state, chunk_bytes=512)
    recovered = cli("review_context_status", "--session-id", state["session_id"], "--round-id", "delivery-round")
    assert recovered["pending_chunk"]["chunk_sha256"] == chunk["chunk_sha256"]
    assert recovered["remaining"] == state["remaining"]
    assert serve(recovered, chunk_bytes=512) == chunk
    advanced = cli("ack_review_context", "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                   "--round-id", "delivery-round", payload=json.dumps(chunk))
    assert advanced["remaining"][0]["offset"] == chunk["next_offset"]
    assert acknowledge(state, chunk) == advanced
    ready = deliver_all(advanced)
    recovered = cli("review_context_status", "--session-id", state["session_id"], "--round-id", "delivery-round")
    assert recovered == ready


def test_resized_pending_chunk_rejects_superseded_ack_without_losing_current_pending(repository):
    """Only the latest same-offset replacement may advance acknowledged bytes."""
    del repository
    state = bind(prepare()["monitor"])
    large = serve(state, chunk_bytes=1024)
    small = serve(state, chunk_bytes=512)
    assert small["next_offset"] < large["next_offset"]
    assert acknowledge(state, large)["status"] == "error"
    current = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert current["pending_chunk"]["next_offset"] == small["next_offset"]
    advanced = acknowledge(state, small)
    assert advanced["remaining"][0]["offset"] == small["next_offset"]
    next_chunk = serve(advanced, chunk_bytes=128)
    replay = acknowledge(state, small)
    assert replay["pending_chunk"]["chunk_sha256"] == next_chunk["chunk_sha256"]


@pytest.mark.parametrize("mutation", ["content", "hash", "gap", "agent", "session", "resource"])
def test_forged_or_misrouted_ack_does_not_advance_state(repository, mutation):
    """ACK identity and exact source bytes are independent of a claimed final receipt."""
    del repository
    state = bind(prepare()["monitor"])
    chunk = serve(state, chunk_bytes=512)
    bad = copy.deepcopy(chunk)
    target = copy.deepcopy(state)
    if mutation == "content":
        bad["content"] = "wrong"
    elif mutation == "hash":
        bad["chunk_sha256"] = "0" * 64
    elif mutation == "gap":
        bad["offset"] += 1
    elif mutation == "agent":
        target["agent_id"] = "other-agent"
    elif mutation == "session":
        bad["session_id"] = "other-session"
    else:
        bad["resource_id"] = "forbidden"
    before = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
    assert acknowledge(target, bad)["status"] == "error"
    assert runner.review_context_status(state["session_id"], "delivery-round", branch="feature") == before


def test_replacement_agent_cannot_borrow_delivery_or_final_token(repository):
    """Even identical source and role require complete redelivery to a replacement agent."""
    del repository
    entry = prepare()["monitor"]
    ready = deliver_all(bind(entry))
    replacement = bind(entry, agent="replacement")
    assert replacement["session_id"] != ready["session_id"]
    assert "finalization_token" not in replacement
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(ready)),
                                       "delivery-round", branch="feature")["status"] == "error"
    finished = deliver_all(replacement)
    assert finished["finalization_token"] != ready["finalization_token"]
    assert runner.capture_review_output("monitor", json.dumps(final_envelope(ready)),
                                       "delivery-round", branch="feature")["status"] == "error"


def test_compare_orderings_and_adversarial_aggregate_require_each_session(repository):
    """A successful constituent cannot borrow the other ordering's completed delivery."""
    del repository
    entry = prepare("compare_orderings")["blind"]
    ready = deliver_all(bind(entry, role="blind", ordering="default"))
    reverse = bind(entry, role="blind", agent="reverse-agent", ordering="reverse")
    statuses = {role: {"status": "not_run"} for role in runner.ADVERSARIAL_REVIEWERS}
    statuses["blind"] = {"status": "ok", "raw": final_envelope(ready)}
    payload = json.dumps({"reviewer_status": statuses})
    assert runner.capture_review_output("adversarial", payload, "delivery-round", ordering="default", branch="feature")["status"] == "success"
    assert runner.capture_review_output("adversarial", payload, "delivery-round", ordering="reverse", branch="feature")["status"] == "error"
    assert runner.review_context_status(reverse["session_id"], "delivery-round", branch="feature")["status"] == "context_pending"


def test_concurrent_ack_replays_advance_once_in_fresh_processes(repository):
    """The existing ledger transaction serializes two host-delivery acknowledgments."""
    del repository
    state = bind(prepare()["monitor"])
    chunk = serve(state, chunk_bytes=512)

    def ack():
        """Submit the same durable delivery event from an independent parent process."""
        return cli("ack_review_context", "--session-id", state["session_id"], "--agent-id", state["agent_id"],
                   "--round-id", "delivery-round", payload=json.dumps(chunk))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ack(), range(2)))
    assert results[0] == results[1]
    assert results[0]["remaining"][0]["offset"] == chunk["next_offset"]


def test_existing_capture_cannot_bypass_delivery_after_transport_is_issued(repository):
    """The completeness gate independently rejects an earlier capture without a delivery receipt."""
    assert runner.begin_review_run(round_id="delivery-round", provider="codex", branch="feature")["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    envelope = {"verdict": "approved", "issues": [],
                "receipt": {"covered_files": [".gitignore", "code.py"], "skipped_files": [], "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(envelope), "delivery-round", branch="feature")["status"] == "success"
    assert runner.build_review_prompts(branch="feature")["status"] == "success"
    directory = repository / ".map/feature"
    row = json.loads((directory / "review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    completeness = runner._review_completeness(row, directory)
    assert completeness["status"] == "INCOMPLETE"
    assert any("post-delivery context_receipt" in reason for reason in completeness["reasons"])


def test_tampered_pending_resource_and_abandoned_round_cannot_be_acknowledged(repository):
    """A delivery receipt cannot be minted from changed objects or terminal admission."""
    state = bind(prepare()["monitor"])
    chunk = serve(state, chunk_bytes=512)
    path = repository / ".map/feature/review-context-objects" / chunk["sha256"]
    original = path.read_bytes()
    path.write_bytes(b"tampered")
    assert acknowledge(state, chunk)["status"] == "error"
    path.write_bytes(original)
    assert runner.abandon_review_round("delivery-round", reason="replaced snapshot", branch="feature")["status"] == "success"
    assert acknowledge(state, chunk)["status"] == "error"


def test_large_inventory_status_returns_bounded_next_work_without_losing_count():
    """A manifest with many sources must not overflow the parent's recovery response."""
    state = {"context_id": "a" * 64, "reviewer": "monitor", "agent_id": "agent", "ordering": "default",
             "offsets": {}, "pending": None,
             "required": {f"source_{i:06d}": {"bytes": 1024} for i in range(10000)}}
    result = runner._review_delivery_state("session", state)
    assert result["remaining_count"] == 10000
    assert len(result["remaining"]) == 1
    assert len(json.dumps(result).encode()) < 1024
