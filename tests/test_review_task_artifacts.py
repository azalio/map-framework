"""Frozen task artifacts do not consume the per-reviewer budget: bounded spec inline, the rest lazy (#648)."""

import hashlib
import json
from pathlib import Path

from tests.test_review_changed_scope import lazy_request, read_resource, runner
from tests.test_review_changed_scope import repo as _base_repo

repo = _base_repo
__all__ = ["repo"]

SPEC = "# Specification\n" + "".join(f"Requirement line {index} with some detail text.\n" for index in range(1500))
PLAN = "# Plan\nPLAN_BODY_MARKER\n" + "Subtask line with detail.\n" * 1500
BLUEPRINT = json.dumps({"subtasks": [{"id": f"ST-{index:03d}", "note": "blueprint detail " * 10} for index in range(900)]})


def admit_with_artifacts(provider="codex", arguments="", round_id="art"):
    Path("first.py").write_text("value = 2\n")
    directory = Path(".map/feature")
    directory.mkdir(parents=True)
    (directory / "spec_feature.md").write_text(SPEC)
    (directory / "task_plan_feature.md").write_text(PLAN)
    (directory / "blueprint.json").write_text(BLUEPRINT)
    admitted = runner.begin_review_run(branch="feature", provider=provider, arguments=arguments, round_id=round_id)
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    return directory, admitted


def artifacts_view(directory, entry):
    return json.loads(read_resource(directory, entry, "artifacts"))


def test_vc1_only_a_bounded_spec_is_inline_and_the_rest_is_an_index(repo):
    del repo
    directory, _ = admit_with_artifacts()
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    view = artifacts_view(directory, entry)
    raw = read_resource(directory, entry, "artifacts")
    assert len(raw.encode()) < runner.REVIEW_SPEC_INLINE_BYTES + 8 * 1024
    assert view["spec"]["truncated"] is True
    assert view["spec"]["content"] in SPEC and 0 < len(view["spec"]["content"]) < len(SPEC)
    assert "PLAN_BODY_MARKER" not in raw and "blueprint detail" not in raw
    index = {item["resource_id"]: item for item in view["index"]}
    assert set(index) >= {"artifact:spec_feature.md", "artifact:task_plan_feature.md", "artifact:blueprint.json"}
    blueprint = index["artifact:blueprint.json"]
    assert blueprint["bytes"] == len(BLUEPRINT.encode())
    assert blueprint["sha256"] == hashlib.sha256(BLUEPRINT.encode()).hexdigest()
    assert blueprint["kind"] == "blueprint" and blueprint["purpose"]


def test_vc1_small_spec_is_inline_whole(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    directory = Path(".map/feature")
    directory.mkdir(parents=True)
    (directory / "spec_feature.md").write_text("# Small spec\nONE_LINE\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="small")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    view = artifacts_view(directory, entry)
    assert view["spec"]["truncated"] is False
    assert view["spec"]["content"] == "# Small spec\nONE_LINE\n"


def test_vc2_artifact_is_a_lazy_frozen_resource_with_its_own_namespace(repo):
    del repo
    directory, _ = admit_with_artifacts()
    built = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]
    entry = built["monitor"]
    manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
    assert not any(key.startswith("artifact:") for key in manifest["resources"])
    served = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "artifact:blueprint.json")),
                                         "art", branch="feature", chunk_bytes=runner.REVIEW_CONTEXT_CHUNK_BYTES)
    assert served["status"] == "context_response"
    assert served["content"] == BLUEPRINT[:len(served["content"])]
    assert served["sha256"] == hashlib.sha256(BLUEPRINT.encode()).hexdigest()
    assert served["total_bytes"] == len(BLUEPRINT.encode())
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert row["context_lazy"]["artifact:blueprint.json"]["required"] is False
    assert row["context_lazy"]["artifact:blueprint.json"]["kind"] == "artifact"
    again = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "artifact:blueprint.json")),
                                        "art", branch="feature")
    assert again["sha256"] == served["sha256"]


def test_vc2_artifact_never_collides_with_repo_namespace(repo):
    del repo
    directory, _ = admit_with_artifacts()
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    Path("blueprint.json").write_text("{}")
    for denied in ("artifact:", "artifact:../first.py", "artifact:first.py", "artifact:missing.md",
                   "artifact:review-bundle.json", "repo:blueprint.json"):
        result = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, denied)), "art", branch="feature")
        assert result["status"] == "error", denied
    assert directory.is_dir()


def test_vc2_role_reviewers_without_artifact_access_cannot_fetch_them(repo):
    del repo
    admit_with_artifacts()
    built = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]
    for role in ("user_experience", "maintainer"):
        result = runner.serve_review_context(
            role, json.dumps(lazy_request(built[role], "artifact:task_plan_feature.md")), "art", branch="feature")
        assert result["status"] == "error", role


def test_vc2_tampered_artifact_object_is_rejected_on_the_next_read(repo):
    del repo
    directory, _ = admit_with_artifacts()
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    request = json.dumps(lazy_request(entry, "artifact:task_plan_feature.md"))
    assert runner.serve_review_context("monitor", request, "art", branch="feature")["status"] == "context_response"
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    digest = row["context_lazy"]["artifact:task_plan_feature.md"]["sha256"]
    (directory / "review-context-objects" / digest).write_text("tampered")
    rejected = runner.serve_review_context("monitor", request, "art", branch="feature")
    assert rejected["status"] == "error" and "changed" in str(rejected)


def test_vc2_changed_task_input_after_admission_still_rejects_context_delivery(repo):
    del repo
    directory, _ = admit_with_artifacts()
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    (directory / "task_plan_feature.md").write_text("Changed after admission\n")
    result = runner.serve_review_context(
        "monitor", json.dumps(lazy_request(entry, "artifact:task_plan_feature.md")), "art", branch="feature")
    assert result["status"] == "error"


def test_vc3_fixed_overhead_does_not_count_artifact_bodies_and_stays_at_least_exact(repo):
    del repo
    directory, admitted = admit_with_artifacts()
    built = runner.build_review_prompts(branch="feature", pack_sources=True)
    exact = 0
    for entry in built["prompts"].values():
        manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
        exact = max(exact, sum(item["bytes"] for key, item in manifest["resources"].items()
                               if item.get("required", True) and not key.startswith("source_") and key != "diff"))
    overhead = runner._review_fixed_overhead(admitted["target"], "claude", admitted["scheduled_reviewers"], "feature",
                                             admitted["required_files"], [])
    assert overhead["total"] >= exact, (overhead["total"], exact)
    assert overhead["breakdown"].get("task_artifacts", 0) < runner.REVIEW_SPEC_INLINE_BYTES + 8 * 1024
    assert len(SPEC + PLAN + BLUEPRINT) > 100_000
    assert overhead["total"] < 100_000, overhead


def test_vc3_acceptance_prompt_bounds_the_spec_and_points_to_the_lazy_plan(repo):
    del repo
    directory, admitted = admit_with_artifacts(arguments="--adversarial", round_id="adv")
    built = runner.build_adversarial_review_prompts(branch="feature", reviewers=admitted["scheduled_reviewers"])
    entry = built["prompts"]["acceptance"]
    prompt = read_resource(directory, entry, "prompt") if "context_transport" in entry else entry["prompt"]
    assert "PLAN_BODY_MARKER" not in prompt
    assert "artifact:task_plan_feature.md" in prompt and "artifact:spec_feature.md" in prompt
    assert len(prompt.encode()) < runner.REVIEW_SPEC_INLINE_BYTES * 2


def test_vc3_estimate_covers_the_acceptance_roster_prompt(repo):
    del repo
    directory, admitted = admit_with_artifacts(arguments="--adversarial", round_id="adv2")
    built = runner.build_adversarial_review_prompts(branch="feature", reviewers=admitted["scheduled_reviewers"])
    exact = 0
    for entry in built["prompts"].values():
        manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
        exact = max(exact, sum(item["bytes"] for key, item in manifest["resources"].items()
                               if item.get("required", True) and not key.startswith("source_") and key != "diff"))
    estimate = runner._review_fixed_overhead_bytes(admitted["target"], "claude", admitted["scheduled_reviewers"],
                                                   "feature", admitted["required_files"], [])
    assert estimate >= exact, (estimate, exact)


def test_lazy_artifact_is_acknowledged_through_file_delivery(repo):
    del repo
    _, admitted = admit_with_artifacts(provider="claude", round_id="art-file")
    entry = runner.build_review_prompts(branch="feature", pack_sources=True)["prompts"]["monitor"]
    context_id = entry["context_transport"]["context_id"]
    state = runner.bind_review_context("monitor", context_id, "native-agent", admitted["round_id"], branch="feature")
    assert state["status"] == "context_pending", state
    request = {"type": "context_request", "context_id": context_id,
               "resource_id": "artifact:blueprint.json", "offset": 0}
    served = runner.serve_review_context("monitor", json.dumps(request), admitted["round_id"], branch="feature",
                                         session_id=state["session_id"], agent_id="native-agent", delivery="file")
    assert served["type"] == "context_file", served
    nonce = Path(served["path"]).read_text(encoding="utf-8").splitlines()[-1].removeprefix("MAP-CONTEXT-NONCE: ")
    proof = {"type": "context_ack", "session_id": state["session_id"], "context_id": context_id,
             "resource_id": "artifact:blueprint.json", "sha256": served["sha256"], "nonce": nonce}
    acked = runner.ack_review_context(state["session_id"], "native-agent", json.dumps(proof), admitted["round_id"],
                                      branch="feature")
    assert acked["status"] in {"context_pending", "context_ready"}, acked
