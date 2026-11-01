"""Diff coverage is distinct from the immutable context inventory."""

import json
from pathlib import Path

import pytest

from tests.test_review_trusted_policy import git, runner


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    Path(".gitignore").write_text(".map/\n")
    for name in ("first.py", "second.py", "removed.py", "moved.py", "dependency.py"):
        Path(name).write_text("value = 1\n")
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\n")
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    return tmp_path


def test_scope_covers_multiple_commits_and_local_changes(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    git("commit", "-qam", "first change")
    Path("second.py").write_text("value = 2\n")
    git("commit", "-qam", "second change")
    git("mv", "moved.py", "renamed.py")
    Path("removed.py").unlink()
    Path("new file\nwith newline.py").write_text("value = 3\n")
    target = runner._review_target({"base_ref": "main"})
    assert set(target["required_files"]) == {
        "first.py", "second.py", "removed.py", "moved.py", "renamed.py", "new file\nwith newline.py"
    }
    assert "dependency.py" in target["context_files"]
    assert target["required_files"] == sorted(target["required_files"])
    before = target["local_digest"]
    Path("dependency.py").write_text("value = 99\n")
    assert runner._review_target({"base_ref": "main"})["local_digest"] != before


@pytest.mark.parametrize("skip", [[], ["dependency.py"], ["first.py"]])
def test_coverage_requires_changed_paths_only(repo, skip):
    del repo
    Path("first.py").write_text("value = 2\n")
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"],
                                      provider="claude", round_id="scope", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    payload = {"verdict": "approved", "issues": [], "receipt": {
        "covered_files": ["first.py"], "skipped_files": skip, "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(payload), "scope", branch="feature")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == ("INCOMPLETE" if skip == ["first.py"] else "COMPLETE"), result
    assert result["code_approval"]["approved"] is (skip != ["first.py"])


def test_unchanged_context_is_frozen_optional_and_retrievable(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    admitted = runner.begin_review_run(branch="feature", provider="codex", round_id="scope")
    assert admitted["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    context_id = entry["context_transport"]["context_id"]
    state = runner.bind_review_context("monitor", context_id, "reader", "scope", branch="feature")
    request = {"type": "context_request", "context_id": context_id, "resource_id": "manifest", "offset": 0}
    response = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature")
    manifest = json.loads(response["content"])
    resource, metadata = next((k, v) for k, v in manifest["resources"].items() if v.get("path") == "dependency.py")
    assert metadata["required"] is False
    # Optional context remains admissible evidence for dependency/reachability findings.
    assert runner._review_refs_checked([
        {"file_path": "dependency.py", "revision": "current", "quote": "value = 1"},
        {"file_path": "dependency.py", "revision": "baseline", "quote": "value = 1"},
    ], admitted["target"], {"current", "baseline"})
    assert not runner._review_refs_checked([
        {"file_path": "outside.py", "revision": "current", "quote": "value = 1"},
    ], admitted["target"], {"current"})
    row = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    assert resource not in row["context_sessions"][state["session_id"]]["required"]
    request["resource_id"] = resource
    response = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature",
                                         session_id=state["session_id"], agent_id="reader")
    assert json.loads(response["content"])["current_content"] == "value = 1\n"
    ack = runner.ack_review_context(state["session_id"], "reader", json.dumps(response), "scope", branch="feature")
    assert ack["status"] == "context_pending"
    Path("dependency.py").write_text("value = 99\n")
    rejected = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature")
    assert rejected["status"] == "error"
    assert "changed" in str(rejected)


def test_large_inventory_packs_only_changed_sources(repo):
    del repo
    for index in range(1250):
        Path(f"module_{index:04d}.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "large baseline")
    git("branch", "-f", "main", "HEAD")
    changed = {f"module_{index:04d}.py" for index in range(62)}
    for name in changed:
        Path(name).write_text("value = 2\n" + "# unchanged source context\n" * 300)
    admitted = runner.begin_review_run(branch="feature", provider="codex", round_id="large")
    assert set(admitted["required_files"]) == changed
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature", review_bundle_text="Source evidence comes from frozen resources.",
                                        pack_sources=True)
    assert built["status"] == "success", built
    entry = built["prompts"]["monitor"]
    context_id = entry["context_transport"]["context_id"]
    directory = Path(".map/feature")
    manifest = json.loads((directory / "review-context-objects" / context_id).read_text())
    required = {key for key, value in manifest["resources"].items() if value.get("required", True)}
    assert required == {"prompt", "inventory", "source_pack"}
    sources = [value for value in manifest["resources"].values() if "path" in value]
    assert len(sources) >= 1250
    packed = runner._review_context_read(directory, manifest["resources"]["source_pack"])
    files = json.loads(packed)["files"]
    assert {item["path"] for item in files} == changed
    assert all(item["current_content"] == Path(item["path"]).read_text() for item in files)
    assert len(packed) // 65536 < 20


def test_full_task_artifacts_are_frozen_and_role_scoped(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    directory = Path(".map/feature")
    directory.mkdir(parents=True)
    specification = "# Specification\n" + "A requirement.\n" * 500 + "FINAL_REQUIREMENT_MARKER\n"
    (directory / "spec_feature.md").write_text(specification)
    (directory / "task_plan_feature.md").write_text("PLAN_CONTEXT_MARKER\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="artifacts")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature", review_bundle_text="Compact summary", pack_sources=True)
    entry = built["prompts"]["monitor"]
    manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
    frozen = json.loads(runner._review_context_read(directory, manifest["resources"]["artifacts"]))
    assert frozen["spec"][0]["content"] == specification
    assert frozen["task_plan"][0]["content"] == "PLAN_CONTEXT_MARKER\n"
    for role in ("user_experience", "maintainer"):
        entry = built["prompts"][role]
        manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
        assert "artifacts" not in manifest["resources"]
        inventory = runner._review_context_read(directory, manifest["resources"]["inventory"])
        assert b"FINAL_REQUIREMENT_MARKER" not in inventory
    (directory / "task_plan_feature.md").write_text("Changed after admission\n")
    recreated = runner.create_review_bundle(branch="feature")
    assert recreated["status"] == "error", recreated
    assert "changed" in str(recreated).lower()


@pytest.mark.parametrize("name", ["first.py", "untracked.py"])
def test_unknown_base_does_not_label_changed_sources_unchanged(repo, name):
    del repo
    git("branch", "-D", "main")
    Path(name).write_text("value = 2\n")
    admitted = runner.begin_review_run(branch="feature", provider="codex", round_id="unknown")
    assert admitted["status"] == "success", admitted
    assert admitted["required_files"] == [name]
    assert not admitted["target"]["base"]
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    directory = Path(".map/feature")
    entry = built["prompts"]["monitor"]
    manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
    metadata = next(value for value in manifest["resources"].values() if value.get("path") == name)
    source = json.loads(runner._review_context_read(directory, metadata))
    assert source["current_content"] == "value = 2\n"
    assert source["status"] == "unknown"
    assert source["baseline_known"] is False


def test_unreadable_optional_file_cannot_bypass_snapshot_binding(repo, monkeypatch):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="unreadable")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    original = Path.read_bytes

    def unreadable(path):
        if path.name == "dependency.py":
            raise PermissionError("optional source is unreadable")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    result = runner.build_review_prompts(branch="feature")
    assert result["status"] == "error", result
    assert runner._review_target().get("reusable") is False


def test_blind_review_receives_untracked_source_as_diff(repo):
    del repo
    Path("new file.py").write_text("UNTRACKED_REVIEW_MARKER = 42\n")
    runner.begin_review_run(branch="feature", provider="codex", arguments="--adversarial --quick", round_id="untracked")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_adversarial_review_prompts(branch="feature")
    assert built["status"] == "success", built
    entry = built["prompts"]["blind"]
    directory = Path(".map/feature")
    manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
    prompt = runner._review_context_read(directory, manifest["resources"]["prompt"])
    assert b"+UNTRACKED_REVIEW_MARKER = 42" in prompt
    assert not any(key.startswith("source_") for key in manifest["resources"])
    assert "artifacts" not in manifest["resources"]


@pytest.mark.parametrize("filename", ["task_plan_feature.md", "verification-summary.md", "test_handoff_ST-001.json"])
def test_task_input_changes_reject_capture_and_completion(repo, filename):
    del repo
    Path("first.py").write_text("value = 2\n")
    directory = Path(".map/feature")
    directory.mkdir(parents=True)
    artifact = directory / filename
    artifact.write_text("{}")
    runner.begin_review_run(branch="feature", provider="claude", scheduled_reviewers=["monitor"], round_id="task-inputs")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert runner._review_binding_current(row)
    output = {"verdict": "approved", "issues": [], "receipt": {"covered_files": ["first.py"],
              "skipped_files": [], "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(output), "task-inputs", branch="feature")["status"] == "success"
    artifact.write_text('{"changed":true}')
    assert not runner._review_binding_current(row)
    assert runner.capture_review_output("monitor", json.dumps(output), "task-inputs", branch="feature")["status"] == "error"
    assert runner.write_review_verdict_ledger(current_run=True, branch="feature")["status"] == "error"


def test_admitted_handoff_does_not_create_review_inputs(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="claude", scheduled_reviewers=["monitor"], round_id="handoff")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    output = {"verdict": "approved", "issues": [], "receipt": {"covered_files": ["first.py"],
              "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(output), "handoff", branch="feature")
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["code_approval"]["approved"] is True
    assert runner.build_handoff_bundle("feature")["status"] == "success"
    directory = Path(".map/feature")
    assert not (directory / "verification-summary.md").exists()
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert runner._review_binding_current(row)
