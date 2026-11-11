"""Diff coverage is distinct from the immutable context inventory."""

import importlib
import json
import os
from pathlib import Path

import pytest

from tests.review_paraphrase_helpers import PARAPHRASE, with_paraphrase
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
    payload = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {
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
    # Unchanged repository files are no longer enumerated in the manifest (#625).
    assert not any(v.get("path") == "dependency.py" for v in manifest["resources"].values())
    resource = "repo:dependency.py"
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
    assert "repo:dependency.py" not in row.get("context_lazy", {})
    request["resource_id"] = resource
    response = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature",
                                         session_id=state["session_id"], agent_id="reader")
    assert json.loads(response["content"])["current_content"] == "value = 1\n"
    ack = runner.ack_review_context(state["session_id"], "reader", json.dumps(response), "scope", branch="feature")
    assert ack["status"] == "context_pending"
    row = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    assert row["context_lazy"]["repo:dependency.py"]["required"] is False
    assert row["context_sessions"][state["session_id"]]["offsets"][resource] > 0
    Path("dependency.py").write_text("value = 99\n")
    rejected = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature")
    assert rejected["status"] == "error"
    assert "changed" in str(rejected)


def test_large_inventory_packs_only_changed_sources(repo, monkeypatch):
    del repo
    # Packing keeps transport chunks few; the byte budget is exercised separately.
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
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
    assert required == {"prompt", "inventory", "source_pack", "diff"}
    sources = [value for value in manifest["resources"].values() if "path" in value]
    assert {value["path"] for value in sources} == changed
    inventory = json.loads(runner._review_context_read(Path(".map/feature"), manifest["resources"]["inventory"]))
    assert "context_files" not in inventory["snapshot"]["target"]
    assert inventory["snapshot"]["target"]["context_files_count"] >= 1250
    assert len(inventory["snapshot"]["target"]["context_files_sha256"]) == 64
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
    view = json.loads(runner._review_context_read(directory, manifest["resources"]["artifacts"]))
    assert view["spec"]["content"] == specification and view["spec"]["truncated"] is False
    assert "PLAN_CONTEXT_MARKER" not in json.dumps(view["spec"])
    assert {item["resource_id"] for item in view["index"]} == {"artifact:spec_feature.md", "artifact:task_plan_feature.md"}
    request = lazy_request(entry, "artifact:task_plan_feature.md")
    served = runner.serve_review_context("monitor", json.dumps(request), "artifacts", branch="feature")
    assert served["content"] == "PLAN_CONTEXT_MARKER\n"
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


def test_unreadable_optional_file_cannot_bypass_snapshot_binding(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="unreadable")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    if os.geteuid() == 0:
        pytest.skip("permission bits do not restrict root")
    # Intent: a real permission change (not a patched reader) updates the file's ctime, which the cache signature sees.
    Path("dependency.py").chmod(0)
    try:
        result = runner.build_review_prompts(branch="feature")
        assert result["status"] == "error", result
        assert runner._review_target().get("reusable") is False
    finally:
        Path("dependency.py").chmod(0o644)


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
    diff = runner._review_context_read(directory, manifest["resources"]["diff"])
    assert b"+UNTRACKED_REVIEW_MARKER = 42" in diff
    assert b"UNTRACKED_REVIEW_MARKER" not in runner._review_context_read(directory, manifest["resources"]["prompt"])
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
    output = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {"covered_files": ["first.py"],
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
    output = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {"covered_files": ["first.py"],
              "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(output), "handoff", branch="feature")
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["code_approval"]["approved"] is True
    assert runner.build_handoff_bundle("feature")["status"] == "success"
    directory = Path(".map/feature")
    assert not (directory / "verification-summary.md").exists()
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert runner._review_binding_current(row)


def trust_on_main(files):
    """Commit operator-maintained files to the default branch, leaving the feature tree clean."""
    git("checkout", "-q", "main")
    for name, content in files.items():
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_text(content)
        git("add", "-f", name)
    git("commit", "-qm", "operator policy")
    git("checkout", "-q", "feature")


def write_changes(*names):
    Path("first.py").write_text("value = 2\n")
    for name in names:
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_text(f"// {name}\n")


def admit(round_id="gen"):
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"],
                                      provider="claude", round_id=round_id, base_ref="main")
    assert admitted["status"] == "success", admitted
    return admitted


def test_generated_name_patterns_are_skipped_with_recorded_reason(repo):
    del repo
    generated = ["api/types.pb.go", "api/types.pb.h", "svc_pb2.py", "svc_pb2_grpc.py", "pkg/zz_generated.deepcopy.go"]
    write_changes(*generated)
    admitted = admit()
    assert admitted["required_files"] == ["first.py"]
    assert {item["path"] for item in admitted["coverage_skips"]} == set(generated)
    assert all(item["reason"] == "generated" and item["rule"] for item in admitted["coverage_skips"])
    # The target itself is untouched so legacy binding comparisons keep working.
    assert set(generated) <= set(admitted["target"]["required_files"])
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    bundle = json.loads(Path(".map/feature/review-bundle.json").read_text())
    assert bundle["snapshot"]["required_files"] == ["first.py"]
    assert {item["path"] for item in bundle["snapshot"]["coverage_skips"]} == set(generated)
    assert {item["path"] for item in bundle["attribution"]["files"]} == {"first.py"}
    for name in generated:
        assert name not in bundle["attribution"]["diff"]
    markdown = Path(".map/feature/review-bundle.md").read_text()
    assert "coverage_skips_count" in markdown
    payload = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {
        "covered_files": ["first.py"], "skipped_files": [], "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(payload), "gen", branch="feature")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "COMPLETE", result
    assert {item["path"] for item in result["completeness"]["skipped_scope"]} == set(generated)


def test_generated_header_alone_never_skips(repo):
    del repo
    Path("first.py").write_text("# Code generated by protoc. DO NOT EDIT.\nvalue = 2\n")
    admitted = admit()
    assert admitted["required_files"] == ["first.py"]
    assert "coverage_skips" not in admitted


def test_legacy_row_without_generated_files_has_no_skip_fields(repo):
    del repo
    write_changes()
    admitted = admit()
    assert "coverage_skips" not in admitted
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert "coverage_skips" not in row
    assert row["required_files"] == row["target"]["required_files"]


def test_linguist_generated_is_read_from_trusted_base_only(repo):
    del repo
    trust_on_main({".gitattributes": "gen/*.dat linguist-generated\n*.lock linguist-generated=true\n"})
    write_changes("gen/a.dat", "secret.py", "package-lock.json", "Cargo.lock")
    # The PR cannot mark its own files generated by editing .gitattributes.
    Path(".gitattributes").write_text("secret.py linguist-generated\n")
    admitted = admit()
    assert {item["path"] for item in admitted["coverage_skips"]} == {"gen/a.dat"}
    assert admitted["coverage_skips"][0]["rule"].startswith("gitattributes")
    assert {"secret.py", "package-lock.json", "Cargo.lock", ".gitattributes"} <= set(admitted["required_files"])


def test_lockfiles_stay_required_even_when_marked_generated(repo):
    del repo
    trust_on_main({".gitattributes": "package-lock.json linguist-generated\ngo.sum linguist-generated\n"})
    write_changes("package-lock.json", "go.sum")
    admitted = admit()
    assert "coverage_skips" not in admitted
    assert {"package-lock.json", "go.sum"} <= set(admitted["required_files"])


def test_config_can_disable_or_extend_generated_exclusion(repo):
    del repo
    trust_on_main({".map/config.yaml": "review:\n  generated_patterns:\n    - '*.gen.ts'\n"})
    write_changes("ui/api.gen.ts", "x.pb.go")
    admitted = admit("extend")
    assert {item["path"] for item in admitted["coverage_skips"]} == {"ui/api.gen.ts", "x.pb.go"}
    runner.abandon_review_round("extend", reason="retry", branch="feature")
    git("checkout", "-q", "main")
    Path(".map/config.yaml").write_text("review:\n  exclude_generated: false\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-qm", "disable exclusion")
    git("checkout", "-q", "feature")
    admitted = admit("disabled")
    assert "coverage_skips" not in admitted
    assert {"ui/api.gen.ts", "x.pb.go"} <= set(admitted["required_files"])


def test_strict_security_gates_disable_every_generated_skip(repo):
    del repo
    trust_on_main({".map/config.yaml": "review:\n  security_gates: strict\n"})
    write_changes("x.pb.go")
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="strict", base_ref="main")
    assert "x.pb.go" in admitted["required_files"]
    assert "coverage_skips" not in admitted


def lazy_request(entry, resource, offset=0):
    return {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
            "resource_id": resource, "offset": offset}


def test_lazy_repo_lookup_is_limited_to_unchanged_admitted_context_and_frozen_once(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="lazy")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    entry = built["prompts"]["monitor"]
    manifest_request = lazy_request(entry, "manifest")
    manifest = json.loads(runner.serve_review_context("monitor", json.dumps(manifest_request), "lazy", branch="feature")["content"])
    assert not any(key.startswith("repo:") for key in manifest["resources"])
    for denied in ("repo:first.py", "repo:", "repo:../outside"):
        result = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, denied)), "lazy", branch="feature")
        assert result["status"] == "error", denied
    served = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "repo:dependency.py")), "lazy", branch="feature")
    assert served["status"] == "context_response"
    assert json.loads(served["content"])["current_content"] == "value = 1\n"
    again = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "repo:dependency.py")), "lazy", branch="feature")
    assert again["sha256"] == served["sha256"]
    other = built["prompts"]["user_experience"]
    shared = runner.serve_review_context("user_experience", json.dumps(lazy_request(other, "repo:dependency.py")), "lazy", branch="feature")
    assert shared["sha256"] == served["sha256"]


def test_diff_only_reviewer_cannot_fetch_repository_context(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", arguments="--adversarial", round_id="blind")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_adversarial_review_prompts(branch="feature")
    entry = built["prompts"]["blind"]
    result = runner.serve_review_context("blind", json.dumps(lazy_request(entry, "repo:dependency.py")), "blind", branch="feature")
    assert result["status"] == "error"


def read_resource(directory, entry, resource):
    manifest = json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())
    return runner._review_context_read(directory, manifest["resources"][resource]).decode("utf-8")


def test_original_prompt_is_compact_and_full_diff_is_a_required_resource(repo):
    del repo
    write_changes("api/types.pb.go")
    Path("first.py").write_text("value = 2\n" + "# changed line\n" * 4000)
    Path("new file.py").write_text("UNTRACKED_DIFF_MARKER = 1\n")
    admitted = runner.begin_review_run(branch="feature", provider="codex", round_id="diff", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    directory = Path(".map/feature")
    bundle_before = (directory / "review-bundle.md").read_bytes()
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    assert (directory / "review-bundle.md").read_bytes() == bundle_before
    entry = built["prompts"]["monitor"]
    prompt = read_resource(directory, entry, "prompt")
    assert "# changed line" not in prompt
    assert "required parent-served resource named diff" in prompt
    assert len(prompt.encode()) < 40_000
    diff = read_resource(directory, entry, "diff")
    assert diff.count("# changed line") == 4000
    # The added file's hunks are a stub; its content ships once, in the required source resource.
    assert "UNTRACKED_DIFF_MARKER" not in diff and "added file omitted from diff" in diff
    manifest = shard_manifest(entry)
    source_id = next(name for name, item in manifest["resources"].items() if item.get("path") == "new file.py")
    assert source_id in diff
    assert "UNTRACKED_DIFF_MARKER" in read_resource(directory, entry, source_id)
    assert "diff --git a/api/types.pb.go b/api/types.pb.go" in diff
    assert "// api/types.pb.go" not in diff
    assert "generated file omitted by review coverage policy" in diff
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "reader", "diff", branch="feature")
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert "diff" in row["context_sessions"][state["session_id"]]["required"]


def test_every_builder_serves_the_diff_resource_including_diff_only_reviewers(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", arguments="--adversarial", round_id="all")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    directory = Path(".map/feature")
    built = runner.build_adversarial_review_prompts(branch="feature")
    for name in ("blind", "edge_case", "acceptance", "maintainer"):
        assert "+value = 2" in read_resource(directory, built["prompts"][name], "diff"), name
    blind = json.loads((directory / "review-context-objects" / built["prompts"]["blind"]["context_transport"]["context_id"]).read_text())
    assert set(blind["resources"]) == {"prompt", "diff"}
    roles = runner.build_role_review_prompts(branch="feature")
    assert "+value = 2" in read_resource(directory, roles["prompts"]["maintainer"], "diff")


def test_codex_and_claude_share_one_compact_bundle_text(repo):
    del repo
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="codex", round_id="compact")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    codex_runner = importlib.import_module("codex_review_runner")
    assert codex_runner.compact_bundle("feature") == runner._review_compact_bundle("feature")


def test_default_budget_constants():
    assert runner.REVIEW_CONTEXT_BUDGET_BYTES == 384 * 1024
    assert runner.REVIEW_CONTEXT_RESERVE_BYTES == 64 * 1024
    assert runner.REVIEW_CONTEXT_BUDGET_ENV == "MAP_REVIEW_CONTEXT_BUDGET_BYTES"


def big_change(lines=3000):
    write_changes("small.py")
    Path("first.py").write_text("".join(f"value_{index} = {index}\n" for index in range(lines)))


def test_admission_over_budget_fails_fast_without_consuming_a_round(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 20_000))
    big_change()
    result = runner.begin_review_run(branch="feature", provider="codex", round_id="budget", base_ref="main")
    assert result["status"] == "error"
    assert result["stop_reason"] == "review_context_budget_exceeded"
    assert result["total"] > result["budget"] == runner.REVIEW_CONTEXT_RESERVE_BYTES + 20_000
    assert result["top_paths"][0]["path"] == "first.py"
    assert result["top_paths"][0]["bytes"] > 20_000
    assert result["hints"]
    ledger = runner._read_review_ledger(Path(".map/feature"))
    assert not ledger.get("convergence", {}).get("rounds")
    assert not Path(".map/feature/review-mode.json").exists()
    monkeypatch.delenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES")
    assert runner.begin_review_run(branch="feature", provider="codex", round_id="budget", base_ref="main")["status"] == "success"


def test_budget_comes_from_trusted_config_and_env_overrides_it(repo, monkeypatch):
    del repo
    trust_on_main({".map/config.yaml": f"review:\n  context_budget_bytes: {runner.REVIEW_CONTEXT_RESERVE_BYTES + 20_000}\n"})
    big_change()
    result = runner.begin_review_run(branch="feature", provider="codex", round_id="cfg", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded"
    # A PR-head config cannot raise the budget.
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text("review:\n  context_budget_bytes: 100000000\n")
    assert runner.begin_review_run(branch="feature", provider="codex", round_id="cfg", base_ref="main")["status"] == "error"
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    assert runner.begin_review_run(branch="feature", provider="codex", round_id="cfg", base_ref="main")["status"] == "success"


def test_generated_files_do_not_count_toward_the_admission_estimate(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 20_000))
    write_changes()
    Path("api").mkdir()
    Path("api/huge.pb.go").write_text("x := 1\n" * 50_000)
    admitted = admit("generated-budget")
    assert admitted["required_files"] == ["first.py"]


def test_resuming_an_admitted_round_ignores_a_later_budget_change(repo, monkeypatch):
    del repo
    write_changes()
    admit("resume-budget")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "1")
    resumed = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"], provider="claude",
                                      round_id="resume-budget", base_ref="main")
    assert resumed["status"] == "success" and resumed["resumed"] is True


def test_prompt_build_rejects_any_reviewer_over_budget_without_partial_prompts(repo, monkeypatch):
    del repo
    write_changes()
    directory = Path(".map/feature")
    directory.mkdir(parents=True)
    (directory / "spec_feature.md").write_text("A requirement.\n" * 12_000)
    runner.begin_review_run(branch="feature", provider="codex", round_id="exact", base_ref="main")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    # Admission passed; the exact check sees the bounded spec, the prompt and the inventory against a tight budget.
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "30000")
    result = runner.build_review_prompts(branch="feature")
    assert result["status"] == "error" and result["stop_reason"] == "review_context_budget_exceeded", result
    assert "prompts" not in result
    assert max(result["required_bytes"].values()) > result["budget"]
    row = runner._read_review_ledger(directory)["convergence"]["rounds"][-1]
    assert not row.get("context_manifests")
    monkeypatch.delenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES")
    assert runner.build_review_prompts(branch="feature")["status"] == "success"


def shard_budget(extra=60_000):
    return str(runner.REVIEW_CONTEXT_RESERVE_BYTES + extra)


def write_many(count, lines=900, directories=("pkg_a", "pkg_b", "pkg_c")):
    for index in range(count):
        directory = Path(directories[index % len(directories)])
        directory.mkdir(exist_ok=True)
        (directory / f"module_{index:02d}.py").write_text("".join(f"value_{line} = {line}\n" for line in range(lines)))


def test_shard_planner_is_deterministic_and_keeps_directories_together():
    sizes = {f"{directory}/f{index}.py": 10 for directory in ("a", "b", "c") for index in range(3)}
    first = runner._review_plan_shards(sizes, 35)
    assert first == runner._review_plan_shards(dict(reversed(list(sizes.items()))), 35)
    assert [sorted({name.split("/")[0] for name in shard}) for shard in first] == [["a"], ["b"], ["c"]]
    assert all(sum(sizes[name] for name in shard) <= 35 for shard in first)
    assert sorted(name for shard in first for name in shard) == sorted(sizes)
    # A directory larger than one shard is split by recursion, never dropped.
    deep = {f"root/sub{index}/f.py": 10 for index in range(6)}
    planned = runner._review_plan_shards(deep, 25)
    assert [len(shard) for shard in planned] == [2, 2, 2]
    assert sorted(name for shard in planned for name in shard) == sorted(deep)


def test_over_budget_change_is_admitted_as_disjoint_shards_within_capacity(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"], provider="claude",
                                      round_id="shards", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert len(admitted["shard_ids"]) >= 2
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert [shard["id"] for shard in row["shards"]] == admitted["shard_ids"]
    flat = [name for shard in row["shards"] for name in shard["files"]]
    assert sorted(flat) == sorted(row["required_files"]) and len(flat) == len(set(flat))
    assert all(shard["bytes"] <= 60_000 for shard in row["shards"])
    assert all("files" not in shard for shard in admitted["shards"])
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    bundle = json.loads(Path(".map/feature/review-bundle.json").read_text())
    assert bundle["snapshot"]["shards"] == row["shards"]


def test_default_configuration_never_shards_a_small_change(repo):
    del repo
    write_changes("small.py")
    admitted = admit("unsharded")
    assert "shard_ids" not in admitted and "shards" not in admitted
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert "shards" not in row
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    assert "shards" not in json.loads(Path(".map/feature/review-bundle.json").read_text())["snapshot"]


def test_too_many_shards_and_oversized_single_file_fail_fast(repo, monkeypatch):
    del repo
    write_changes()
    write_many(6)
    trust_on_main({".map/config.yaml": "review:\n  max_shards: 2\n"})
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="many", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded" and result["reason"] == "too_many_shards"
    assert result["shards_needed"] > result["max_shards"] == 2
    assert not runner._read_review_ledger(Path(".map/feature")).get("convergence", {}).get("rounds")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget(10_000))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="big", base_ref="main")
    assert result["reason"] == "file_too_large" and result["oversized_paths"]


@pytest.fixture
def sharded(repo, monkeypatch):
    """A three-way sharded admitted round with its immutable bundle."""
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", provider="codex", arguments="--adversarial",
                                      round_id="sharded", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert len(admitted["shard_ids"]) >= 2
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    return admitted, row


def shard_manifest(entry):
    directory = Path(".map/feature")
    return json.loads((directory / "review-context-objects" / entry["context_transport"]["context_id"]).read_text())


def test_builders_require_a_shard_on_a_sharded_round(sharded):
    admitted, _ = sharded
    for name in ("build_adversarial_review_prompts", "build_role_review_prompts"):
        result = getattr(runner, name)(branch="feature")
        assert result["status"] == "sharded" and result["shard_ids"] == admitted["shard_ids"], name
        assert "prompts" not in result
        bad = getattr(runner, name)(branch="feature", shard="s99")
        assert bad["status"] == "error", name
    # Normal-mode prompts need a normal round; the same gate applies to that builder.
    assert runner.build_review_prompts(branch="feature", shard="s99")["status"] == "error"


def test_shard_manifest_is_scoped_to_its_own_files_and_diff(sharded):
    row = sharded[1]
    directory = Path(".map/feature")
    seen_sources = []
    for shard in row["shards"]:
        built = runner.build_adversarial_review_prompts(branch="feature", shard=shard["id"])
        assert built["status"] == "success" and built["shard"] == shard["id"]
        entry = built["prompts"]["acceptance"]
        manifest = shard_manifest(entry)
        assert manifest["shard"] == shard["id"]
        paths = {item["path"] for item in manifest["resources"].values() if "path" in item}
        assert paths == set(shard["files"])
        seen_sources.append(paths)
        inventory = json.loads(runner._review_context_read(directory, manifest["resources"]["inventory"]))
        assert inventory["snapshot"]["required_files"] == shard["files"]
        assert inventory["snapshot"]["shard"]["id"] == shard["id"]
        diff = runner._review_context_read(directory, manifest["resources"]["diff"]).decode()
        assert diff.count("added file omitted from diff") == len([name for name in shard["files"] if name != "first.py"])
        assert diff.count("+value = 2") == int("first.py" in shard["files"])
        assert "belongs to another review shard" in diff
        blind = shard_manifest(built["prompts"]["blind"])
        assert set(blind["resources"]) == {"prompt", "diff"}
    assert set().union(*seen_sources) == set(row["required_files"])
    assert sum(len(item) for item in seen_sources) == len(row["required_files"])


def test_shard_context_cannot_serve_another_shards_sources_but_allows_them_as_repo_context(sharded):
    _, row = sharded
    first, second = row["shards"][0], row["shards"][1]
    built = runner.build_adversarial_review_prompts(branch="feature", shard=first["id"])
    entry = built["prompts"]["edge_case"]
    context_id = entry["context_transport"]["context_id"]

    def serve(resource):
        request = {"type": "context_request", "context_id": context_id, "resource_id": resource, "offset": 0}
        return runner.serve_review_context("edge_case", json.dumps(request), "sharded", branch="feature")

    own = serve(f"repo:{first['files'][0]}")
    assert own["status"] == "error", "a shard's own required file is delivered as a source resource, not repo context"
    other = serve(f"repo:{second['files'][0]}")
    assert other["status"] == "context_response"
    payload = json.loads(other["content"])
    assert payload["status"] == "changed_in_other_shard" and payload["baseline_known"] is False
    manifest = shard_manifest(entry)
    assert all(item["path"] in first["files"] for item in manifest["resources"].values() if "path" in item)


def test_shard_sessions_are_independent_and_use_shard_scoped_keys(sharded):
    _, row = sharded
    contexts = {}
    for shard in row["shards"][:2]:
        built = runner.build_adversarial_review_prompts(branch="feature", shard=shard["id"])
        contexts[shard["id"]] = built["prompts"]["acceptance"]["context_transport"]["context_id"]
    assert len(set(contexts.values())) == len(contexts)
    states = {sid: runner.bind_review_context("acceptance", cid, f"agent-{sid}", "sharded", branch="feature")
              for sid, cid in contexts.items()}
    active = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]["context_active"]
    for sid, state in states.items():
        assert active[f"default:acceptance#{sid}"] == state["session_id"]
    assert len({state["session_id"] for state in states.values()}) == len(states)
    # Rebuilding the same shard is idempotent.
    again = runner.build_adversarial_review_prompts(branch="feature", shard=row["shards"][0]["id"])
    assert again["prompts"]["acceptance"]["context_transport"]["context_id"] == contexts[row["shards"][0]["id"]]


def test_diff_rewrite_preserves_labels_and_scope_trailers():
    diff = ("diff --git a/a.py b/a.py\n+one\n\n=== untracked source additions ===\n"
            "diff --git a/b.py b/b.py\n+two\n\nReview scope: {\"kind\": \"full\"}")
    rewritten = runner._review_rewrite_diff(diff, lambda old, *_: "[gone]" if old == "b.py" else None)
    assert "+one" in rewritten and "+two" not in rewritten
    assert "=== untracked source additions ===" in rewritten
    assert rewritten.endswith('Review scope: {"kind": "full"}')
    rewritten = runner._review_rewrite_diff(diff, lambda old, *_: "[gone]" if old == "a.py" else None)
    assert "=== untracked source additions ===" in rewritten and "+two" in rewritten


@pytest.fixture
def sharded_monitor(repo, monkeypatch):
    """Sharded normal round scheduled for the monitor only (so delivery stays small)."""
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"], provider="claude",
                                      round_id="r", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    return admitted


def deliver(entry, reviewer, agent, ordering=""):
    """Complete parent-acknowledged delivery for one shard context; return its finalization proof."""
    context_id = entry["context_transport"]["context_id"]
    state = runner.bind_review_context(reviewer, context_id, agent, "r", ordering=ordering, branch="feature")
    while state["status"] == "context_pending":
        pending = state["remaining"][0] if state["remaining"] else state["pending_chunk"]
        request = {"type": "context_request", "context_id": context_id,
                   "resource_id": pending["resource_id"], "offset": pending["offset"]}
        chunk = runner.serve_review_context(reviewer, json.dumps(request), "r", branch="feature",
                                            session_id=state["session_id"], agent_id=agent)
        assert chunk["status"] == "context_response", chunk
        state = runner.ack_review_context(state["session_id"], agent, json.dumps(chunk), "r", branch="feature")
    assert state["status"] == "context_ready", state
    return {"session_id": state["session_id"], "finalization_token": state["finalization_token"]}


def monitor_output(proof, covered, *, verdict="approved", skipped=()):
    return {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": verdict, "valid": verdict == "approved", "issues": [], "summary": "ok",
            "context_receipt": proof,
            "receipt": {"covered_files": list(covered), "skipped_files": list(skipped),
                        "denied_access": [], "check_evidence": []}}


def capture_shard(_row, shard, covered=None, *, ordering="", **kwargs):
    del _row
    built = runner.build_review_prompts(branch="feature", shard=shard["id"])
    assert built["status"] == "success", built
    proof = deliver(built["prompts"]["monitor"], "monitor", f"agent-{ordering}-{shard['id']}", ordering)
    output = monitor_output(proof, shard["files"] if covered is None else covered, **kwargs)
    return runner.capture_review_output("monitor", json.dumps(output), "r", ordering=ordering, branch="feature",
                                        shard=shard["id"])


def current_row():
    return runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]


def test_shard_captures_merge_into_one_canonical_capture_only_when_complete(sharded_monitor):
    del sharded_monitor
    shards = current_row()["shards"]
    first = capture_shard(current_row(), shards[0])
    assert first["status"] == "success" and first["merged"] is False
    assert first["shards_missing"] == [item["id"] for item in shards[1:]]
    directory = Path(".map/feature")
    assert not (directory / "review-agent-monitor.json").exists()
    assert "default:monitor" not in current_row()["receipts"]
    # Shard files live outside the review-agent-* namespace.
    assert not list(directory.rglob("review-agent-monitor.json"))
    partial = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert partial["completeness"]["status"] == "INCOMPLETE", partial
    assert partial["code_approval"]["approved"] is False
    last = first
    for shard in shards[1:]:
        last = capture_shard(current_row(), shard)
    assert last["merged"] is True and last["shards_missing"] == []
    merged = json.loads((directory / "review-agent-monitor.json").read_text())
    assert set(merged["context_receipts"]) == {item["id"] for item in shards}
    assert set(merged["receipt"]["covered_files"]) == set(current_row()["required_files"])
    complete = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert complete["completeness"]["status"] == "COMPLETE", complete
    assert complete["code_approval"]["approved"] is True


@pytest.mark.parametrize("own_denial", [False, True])
def test_shard_denials_keep_the_reporting_scope(sharded_monitor, own_denial):
    del sharded_monitor
    shards = current_row()["shards"]
    denied_path = shards[0 if own_denial else 1]["files"][0]
    for index, shard in enumerate(shards):
        built = runner.build_review_prompts(branch="feature", shard=shard["id"])
        assert built["status"] == "success", built
        proof = deliver(built["prompts"]["monitor"], "monitor", f"agent-{shard['id']}")
        output = monitor_output(proof, shard["files"])
        if index == 0:
            output["receipt"]["denied_access"] = [denied_path]
        result = runner.capture_review_output("monitor", json.dumps(output), "r", branch="feature", shard=shard["id"])
        assert result["status"] == "success", result
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    completeness = result["completeness"]
    assert completeness["status"] == ("BLOCKED" if own_denial else "COMPLETE"), completeness
    merged = json.loads(Path(".map/feature/review-agent-monitor.json").read_text())
    assert denied_path in merged["receipt"]["denied_access"]
    if not own_denial:
        assert any(denied_path in item for item in completeness["informational_denied_access"])


def test_shard_capture_requires_an_admitted_shard_and_its_own_delivery_proof(sharded_monitor):
    del sharded_monitor
    shards = current_row()["shards"]
    built = runner.build_review_prompts(branch="feature", shard=shards[0]["id"])
    proof = deliver(built["prompts"]["monitor"], "monitor", "agent-a")
    payload = json.dumps(monitor_output(proof, shards[0]["files"]))
    for bad in ("", "s99"):
        assert runner.capture_review_output("monitor", payload, "r", branch="feature", shard=bad)["status"] == "error"
    # shard s01's proof cannot stand in for s02
    wrong = runner.capture_review_output("monitor", payload, "r", branch="feature", shard=shards[1]["id"])
    assert wrong["status"] == "error", wrong
    ok = runner.capture_review_output("monitor", payload, "r", branch="feature", shard=shards[0]["id"])
    assert ok["status"] == "success"


def test_union_coverage_cannot_hide_an_unread_shard(sharded_monitor):
    del sharded_monitor
    shards = current_row()["shards"]
    everything = [name for item in shards for name in item["files"]]
    capture_shard(current_row(), shards[0], covered=shards[1]["files"])
    for shard in shards[1:]:
        capture_shard(current_row(), shard, covered=everything)
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "INCOMPLETE", result
    assert any("shard scope is unread or skipped" in reason and shards[0]["id"] in reason
               for reason in result["completeness"]["reasons"]), result["completeness"]["reasons"]


def test_tampered_shard_capture_is_incomplete(sharded_monitor):
    del sharded_monitor
    shards = current_row()["shards"]
    for shard in shards:
        capture_shard(current_row(), shard)
    stored = current_row()["shard_receipts"]["default:monitor"][shards[0]["id"]]
    path = Path(".map/feature") / stored["artifact"]
    path.write_text(path.read_text() + " ")
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "INCOMPLETE", result
    assert any("missing or changed shard capture" in reason for reason in result["completeness"]["reasons"])


def test_unsharded_capture_rejects_a_shard_argument(repo):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"], provider="claude",
                            round_id="plain", base_ref="main")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    payload = json.dumps({"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {
        "covered_files": ["first.py"], "skipped_files": [], "denied_access": [], "check_evidence": []}})
    result = runner.capture_review_output("monitor", payload, "plain", branch="feature", shard="s01")
    assert result["status"] == "error" and "not sharded" in str(result)
    assert runner.capture_review_output("monitor", payload, "plain", branch="feature")["status"] == "success"


def test_compare_orderings_capture_merges_per_ordering(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"], provider="claude",
                                      review_mode="compare_orderings", arguments="--compare-orderings",
                                      round_id="r", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    shards = current_row()["shards"]
    for ordering in ("default", "reverse"):
        for shard in shards:
            capture_shard(current_row(), shard, ordering=ordering)
        assert (Path(".map/feature/review-collections") / ordering / "review-agent-monitor.json").exists()
    keys = current_row()["shard_receipts"]
    assert set(keys) == {"default:monitor", "reverse:monitor"}
    assert all(len(value) == len(shards) for value in keys.values())
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "COMPLETE", result


def envelope(**fields):
    return {"reviewer": "x", "all_clear": True, "findings": [], "checks_performed": [],
            "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}, **fields}


def test_merge_is_worst_of_with_unioned_receipts_and_stable_finding_ids():
    owners = {"s01": {"a.py"}, "s02": {"b.py"}}
    clear = envelope(all_clear_rationale="checked a", receipt={"covered_files": ["a.py"], "skipped_files": ["b.py"],
                     "denied_access": [], "check_evidence": ["c1"]}, context_receipt={"session_id": "1"})
    dirty = envelope(all_clear=False, findings=[{"id": "F-M-01", "problem": "x"}, {"id": "F-M-01", "problem": "y"}],
                     receipt={"covered_files": ["b.py"], "skipped_files": [], "denied_access": ["z"],
                              "check_evidence": ["c1", "c2"]}, context_receipt={"session_id": "2"})
    merged = runner._review_merge_envelopes([("s01", clear), ("s02", dirty)], owners)
    assert merged["all_clear"] is False and len(merged["findings"]) == 2
    assert len({item["id"] for item in merged["findings"]}) == 2
    assert merged["receipt"]["covered_files"] == ["a.py", "b.py"]
    assert merged["receipt"]["skipped_files"] == []  # b.py is s02's file, judged in s02
    assert merged["receipt"]["denied_access"] == ["z"] and merged["receipt"]["check_evidence"] == ["c1", "c2"]
    assert merged["context_receipts"] == {"s01": {"session_id": "1"}, "s02": {"session_id": "2"}}
    monitor = [("s01", {"verdict": "approved", "valid": True, "issues": [], "summary": "a"}),
               ("s02", {"verdict": "rejected", "valid": False, "issues": [{"description": "bad"}], "summary": "b"})]
    out = runner._review_merge_envelopes(monitor, owners)
    assert out["verdict"] == "rejected" and out["valid"] is False and out["issues"] == [{"description": "bad"}]
    assert runner._review_merge_envelopes([("s01", {"verdict": "approved"}), ("s02", {"verdict": "unheard-of"})],
                                          owners)["verdict"] == "unheard-of"
    predictor = [("s01", {"risk_assessment": "low", "confidence": {"score": 0.9}, "bug_class": "none",
                          "predicted_state": {"affected_components": ["a"], "breaking_changes": [], "required_updates": []}}),
                 ("s02", {"risk_assessment": "high", "confidence": {"score": 0.4}, "bug_class": "race",
                          "predicted_state": {"affected_components": ["b"], "breaking_changes": [], "required_updates": ["u"]}})]
    out = runner._review_merge_envelopes(predictor, owners)
    assert out["risk_assessment"] == "high" and out["bug_class"] == "race" and out["confidence"]["score"] == 0.4
    assert out["predicted_state"]["affected_components"] == ["a", "b"] and out["predicted_state"]["required_updates"] == ["u"]
    evaluator = [("s01", {"scores": {"security": 9}, "overall_score": 9.0, "recommendation": "proceed"}),
                 ("s02", {"scores": {"security": 4}, "overall_score": 5.0, "recommendation": "improve"})]
    out = runner._review_merge_envelopes(evaluator, owners)
    assert out["scores"]["security"] == 4 and out["overall_score"] == 5.0 and out["recommendation"] == "improve"


def test_adversarial_shard_aggregates_merge_by_reaggregating_merged_reviewers():

    def receipt(name):
        return {"covered_files": [name], "skipped_files": [], "denied_access": [], "check_evidence": []}

    clear = with_paraphrase({"all_clear": True, "all_clear_rationale": "ok", "findings": [], "checks_performed": ["c"]})

    def aggregate(name, finding=None):
        hunter = json.dumps({**clear, "all_clear": finding is None,
                             "findings": [finding] if finding else []})
        roles = {role: json.dumps({**clear, "receipt": receipt(name), "context_receipt": {"session_id": name}})
                 for role in runner.BASE_ROLE_REVIEWERS}
        return runner.aggregate_adversarial_findings(hunter, json.dumps(clear), json.dumps(clear), roles)

    finding = {"id": "F-B-01", "severity": "CRITICAL", "category": "logic", "file_path": "b.py", "line_range": "1",
               "symbol": "f", "failure_mode": "boom", "evidence": "e", "recommendation": "r"}
    merged = runner._review_merge_shard_outputs("adversarial", [("s01", aggregate("a.py")), ("s02", aggregate("b.py", finding))],
                                                {"shards": [{"id": "s01", "files": ["a.py"]}, {"id": "s02", "files": ["b.py"]}]})
    assert merged["schema_version"] == runner.ADVERSARIAL_AGGREGATE_SCHEMA
    assert merged["reviewer_status"]["blind"]["all_clear"] is False
    assert merged["ledger_findings"], merged
    role = merged["reviewer_status"]["maintainer"]["raw"]
    assert role["receipt"]["covered_files"] == ["a.py", "b.py"]
    assert set(role["context_receipts"]) == {"s01", "s02"}


def test_codex_normal_review_reserves_room_for_inlined_role_rubrics(repo, monkeypatch):
    del repo
    write_changes()
    write_many(6)
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    claude = runner.begin_review_run(branch="feature", provider="claude", round_id="rubric", base_ref="main")
    assert claude["status"] == "success" and claude["shard_ids"], claude
    runner.abandon_review_round("rubric", reason="retry", branch="feature")
    codex = runner.begin_review_run(branch="feature", provider="codex", round_id="rubric-codex", base_ref="main")
    # The inlined rubrics alone (not any one file) overflow this small budget.
    assert codex["status"] == "error" and codex["reason"] == "fixed_overhead_too_large", codex
    assert codex["overhead_breakdown"]["role_rubric"] >= runner.REVIEW_ROLE_RUBRIC_RESERVE_BYTES
    assert codex["total"] >= runner.REVIEW_ROLE_RUBRIC_RESERVE_BYTES


def test_adversarial_round_captures_and_merges_per_shard(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial --quick",
                                      round_id="r", base_ref="main")
    assert admitted["status"] == "success" and admitted["shard_ids"], admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = current_row()
    reviewers = row["binding"]["scheduled_reviewers"]
    assert "blind" in reviewers and "monitor" not in reviewers
    for shard in row["shards"]:
        built = runner.build_adversarial_review_prompts(branch="feature", reviewers=reviewers, shard=shard["id"])
        assert built["status"] == "success", built
        raw = {}
        for name in reviewers:
            proof = deliver(built["prompts"][name], name, f"agent-{name}-{shard['id']}")
            raw[name] = json.dumps({"discarded_candidates": [], "paraphrase": PARAPHRASE, "all_clear": True, "all_clear_rationale": f"{name} {shard['id']} clean",
                                    "findings": [], "checks_performed": ["read"], "context_receipt": proof,
                                    "receipt": {"covered_files": shard["files"], "skipped_files": [],
                                                "denied_access": [], "check_evidence": []}})
        aggregate = runner.aggregate_adversarial_findings(
            raw.get("blind"), raw.get("edge_case"), raw.get("acceptance"),
            {role: raw.get(role) for role in runner.ROLE_REVIEWER_IDS})
        captured = runner.capture_review_output("adversarial", json.dumps(aggregate), "r", branch="feature",
                                                shard=shard["id"])
        assert captured["status"] == "success", captured
    merged = json.loads(Path(".map/feature/review-agent-adversarial.json").read_text())
    assert merged["schema_version"] == runner.ADVERSARIAL_AGGREGATE_SCHEMA
    assert set(merged["reviewer_status"]["blind"]["raw"]["context_receipts"]) == set(admitted["shard_ids"])
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "COMPLETE", result["completeness"]


@pytest.fixture
def sharded_predictor(repo, monkeypatch):
    """Sharded normal round; only monitor and predictor captures matter for these tests."""
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="r", base_ref="main")
    assert admitted["status"] == "success" and len(admitted["shard_ids"]) >= 3, admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    return current_row()["shards"]


def capture_predictor_round(shards, defects):
    """defects: shard index -> (risk, bug_class) or None for a clean low-risk prediction."""
    for index, shard in enumerate(shards):
        built = runner.build_review_prompts(branch="feature", shard=shard["id"])
        assert built["status"] == "success", built
        receipt = {"covered_files": shard["files"], "skipped_files": [], "denied_access": [], "check_evidence": []}
        proof = deliver(built["prompts"]["monitor"], "monitor", f"m-{shard['id']}")
        assert runner.capture_review_output("monitor", json.dumps(monitor_output(proof, shard["files"])), "r",
                                            branch="feature", shard=shard["id"])["status"] == "success"
        proof = deliver(built["prompts"]["predictor"], "predictor", f"p-{shard['id']}")
        defect = defects.get(index)
        output = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "evidence": [], "risk_assessment": defect[0] if defect else "low",
                  "predicted_state": {"affected_components": [], "breaking_changes": [], "required_updates": []},
                  "confidence": {"score": 0.8}, "context_receipt": proof, "receipt": receipt}
        if defect:
            output.update({"bug_class": defect[1], "cause": f"cause of {defect[1]}",
                           "failure_scenario": f"{defect[1]} breaks callers"})
        assert runner.capture_review_output("predictor", json.dumps(output), "r", branch="feature",
                                            shard=shard["id"])["status"] == "success"


def predictor_findings():
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    return [item for item in ledger["findings_registry"] if item["source_agent"] == "predictor"]


def test_distinct_predictor_defects_from_two_shards_both_reach_the_ledger(sharded_predictor):
    capture_predictor_round(sharded_predictor, {0: ("high", "race"), 1: ("medium", "leak")})
    merged = json.loads(Path(".map/feature/review-agent-predictor.json").read_text())
    assert merged["risk_assessment"] == "high" and merged["bug_class"] == "race"
    assert [item["bug_class"] for item in merged["additional_defects"]] == ["leak"]
    runner.write_review_verdict_ledger(current_run=True, branch="feature")
    findings = predictor_findings()
    assert sorted(item["bug_class"] for item in findings) == ["leak", "race"]
    assert len({item["id"] for item in findings}) == 2
    assert {item["bug_class"]: item["severity"] for item in findings}["race"] != \
        {item["bug_class"]: item["severity"] for item in findings}["leak"]


def test_identical_predictor_defect_from_two_shards_is_one_finding(sharded_predictor):
    capture_predictor_round(sharded_predictor, {0: ("high", "race"), 1: ("high", "race")})
    merged = json.loads(Path(".map/feature/review-agent-predictor.json").read_text())
    assert "additional_defects" not in merged
    runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert [item["bug_class"] for item in predictor_findings()] == ["race"]


def test_a_clean_shard_adds_no_predictor_defect(sharded_predictor):
    capture_predictor_round(sharded_predictor, {1: ("medium", "leak")})
    merged = json.loads(Path(".map/feature/review-agent-predictor.json").read_text())
    assert merged["bug_class"] == "leak" and "additional_defects" not in merged


@pytest.fixture
def strict_sharded(repo, monkeypatch):
    """Two shards under strict security gates with a sensitive (auth/) change."""
    del repo
    trust_on_main({".map/config.yaml": "review:\n  security_gates: strict\n"})
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 70_000))
    write_changes()
    write_many(4, directories=("auth", "auth_b"))
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="r", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert "security" in admitted["scheduled_reviewers"] and len(admitted["shard_ids"]) == 2, admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    return current_row()["shards"]


def capture_security(shard, covered, *, denied=()):
    built = runner.build_review_prompts(branch="feature", shard=shard["id"])
    assert built["status"] == "success", built
    proof = deliver(built["prompts"]["security"], "security", f"sec-{shard['id']}")
    output = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "reviewer": "security", "all_clear": True, "all_clear_rationale": "no issue", "findings": [],
              "checks_performed": ["read"], "context_receipt": proof,
              "receipt": {"covered_files": list(covered), "skipped_files": [], "denied_access": list(denied), "check_evidence": []}}
    result = runner.capture_review_output("security", json.dumps(output), "r", branch="feature", shard=shard["id"])
    assert result["status"] == "success", result
    return result


def security_gate():
    return runner._review_security_gate(current_row(), Path(".map/feature"))


def test_strict_security_gate_blocks_until_every_shard_has_covered_security_capture(strict_sharded):
    first, second = strict_sharded
    assert runner._review_gates_strict(current_row()["target"])
    capture_security(first, first["files"])
    gate = security_gate()
    assert gate["status"] == "INCOMPLETE", gate
    assert any("security receipt" in reason for reason in gate["reasons"]), gate["reasons"]
    capture_security(second, second["files"])
    assert security_gate()["status"] == "COMPLETE", security_gate()


@pytest.mark.parametrize("own_denial", [False, True])
def test_strict_security_denials_keep_reporting_shard_scope(strict_sharded, own_denial):
    first, second = strict_sharded
    denied = (first if own_denial else second)["files"][0]
    capture_security(first, first["files"], denied=[denied])
    capture_security(second, second["files"])
    gate = security_gate()
    assert gate["status"] == ("INCOMPLETE" if own_denial else "COMPLETE"), gate


def test_strict_security_gate_rejects_union_coverage_that_hides_an_unread_shard(strict_sharded):
    first, second = strict_sharded
    everything = [*first["files"], *second["files"]]
    capture_security(first, second["files"])
    capture_security(second, everything)
    gate = security_gate()
    assert gate["status"] == "INCOMPLETE", gate
    assert any("shard scope is unread or skipped" in reason and first["id"] in reason for reason in gate["reasons"]), gate["reasons"]


def test_every_new_round_is_planned_not_just_the_first(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    first = runner.begin_review_run(branch="feature", provider="claude", round_id="one", base_ref="main")
    assert first["status"] == "success" and first["shard_ids"], first
    assert runner.abandon_review_round("one", reason="retry", branch="feature")["status"] == "success"
    second = runner.begin_review_run(branch="feature", provider="claude", base_ref="main")
    assert second["status"] == "success" and second["shard_ids"] == first["shard_ids"], second
    row = current_row()
    assert row["round_id"] != "one" and [item["id"] for item in row["shards"]] == first["shard_ids"]


def test_resuming_the_pending_round_never_replans(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    write_many(6)
    first = runner.begin_review_run(branch="feature", provider="claude", round_id="one", base_ref="main")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "1")
    resumed = runner.begin_review_run(branch="feature", provider="claude", round_id="one", base_ref="main")
    assert resumed["status"] == "success" and resumed["resumed"] is True and resumed["shard_ids"] == first["shard_ids"]


def test_digest_ignores_shard_files_of_earlier_rounds(sharded_monitor):
    del sharded_monitor
    shards = current_row()["shards"]
    stale = Path(".map/feature/review-shards/ffff/default/s01")
    stale.mkdir(parents=True)
    (stale / "shard-monitor.json").write_text('{"old": true}')
    for shard in shards:
        capture_shard(current_row(), shard)
    first = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert first["completeness"]["status"] == "COMPLETE", first
    (stale / "shard-monitor.json").write_text('{"old": false}')
    again = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert again["status"] == "success", again


def write_cyrillic(count=3, repeat=3000):
    Path("docs").mkdir(exist_ok=True)
    for index in range(count):
        Path(f"docs/note_{index}.md").write_text("Привет, мир! \"кавычки\"\n" * repeat)


def exact_required(entry):
    manifest = shard_manifest(entry)
    return manifest["resources"]


def test_estimate_covers_the_json_encoded_source_resources(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    write_cyrillic()
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="enc", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    resources = exact_required(built["prompts"]["monitor"])
    exact = sum(item["bytes"] for key, item in resources.items() if key.startswith("source_") or key == "diff")
    estimate = sum(runner._review_required_bytes(admitted["target"], admitted["required_files"]).values())
    assert estimate >= exact, (estimate, exact)


def test_non_ascii_change_is_sharded_at_admission_instead_of_failing_at_prompt_build(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 130_000))
    write_changes()
    write_cyrillic(repeat=1500)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="enc", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    ids = admitted.get("shard_ids") or [""]
    for shard in ids:
        built = runner.build_review_prompts(branch="feature", shard=shard)
        assert built["status"] == "success", (shard, built)
    assert len(ids) >= 2, admitted


def serve_lazy(entry, resource, round_id, reviewer="monitor"):
    request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
               "resource_id": resource, "offset": 0}
    return runner.serve_review_context(reviewer, json.dumps(request), round_id, branch="feature")


def test_changed_generated_file_is_served_with_real_base_and_current(repo):
    del repo
    trust_on_main({"gen.pb.go": "OLD GENERATED\n"})
    git("merge", "-q", "main", "-m", "take generated file into the feature base")
    Path("gen.pb.go").write_text("NEW GENERATED\n")
    write_changes()
    admitted = runner.begin_review_run(branch="feature", provider="codex", mode="lightweight", round_id="gen", base_ref="main")
    assert admitted["status"] == "success" and [item["path"] for item in admitted["coverage_skips"]] == ["gen.pb.go"], admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    served = serve_lazy(entry, "repo:gen.pb.go", "gen")
    assert served["status"] == "context_response", served
    payload = json.loads(served["content"])
    assert payload["status"] == "changed_generated_skipped"
    assert payload["base_content"] == "OLD GENERATED\n" and payload["current_content"] == "NEW GENERATED\n"
    assert payload["baseline_known"] is True


def test_large_check_logs_are_stubbed_in_the_prompt_and_stay_retrievable(repo, monkeypatch):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", mode="lightweight", round_id="chk", base_ref="main")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    directory = Path(".map/feature")
    log = "".join(f"line {index} of a very long test log\n" for index in range(20_000))
    (directory / "check-big.txt").write_text(log)
    (directory / "check-small.txt").write_text("ok\n")
    ledger = runner._read_review_ledger(directory)
    ledger["execution_checks"] = {"big": {"output_artifact": "check-big.txt"}, "small": {"output_artifact": "check-small.txt"}}
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    monkeypatch.setattr(runner, "_review_check_valid", lambda *_: True)
    compact = runner._review_compact_bundle("feature")
    # One compact line per check: digest, size and a pointer; no log text in the prompt.
    assert len(compact) < 20_000 and "line 0 of" not in compact and "line 19999 of" not in compact
    assert '"output_resource": "check:big"' in compact and '"output_resource": "check:small"' in compact
    assert f'"output_chars": {len(log)}' in compact
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    chunks, offset = [], 0
    while True:
        request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
                   "resource_id": "check:big", "offset": offset}
        served = runner.serve_review_context("monitor", json.dumps(request), "chk", branch="feature")
        assert served["status"] == "context_response", served
        chunks.append(served["content"])
        if served["eof"]:
            break
        offset = served["next_offset"]
    assert "".join(chunks) == log
    unknown = serve_lazy(entry, "check:nope", "chk")
    assert unknown["status"] == "error"


@pytest.mark.parametrize("header,expected", [
    ("diff --git a/plain.py b/plain.py", ("plain.py", "plain.py")),
    ("diff --git a/dir with b/space.py b/dir with b/space.py", ("dir with b/space.py", "dir with b/space.py")),
    ('diff --git "a/caf\\303\\251.pb.go" "b/caf\\303\\251.pb.go"', ("café.pb.go", "café.pb.go")),
    ('diff --git "a/we\\"ird\\ttab.go" "b/we\\"ird\\ttab.go"', ('we"ird\ttab.go', 'we"ird\ttab.go')),
    ("diff --git a/old.py b/new.py", ("old.py", "new.py")),
    ('diff --git a/old.py "b/n\\303\\251w.py"', ("old.py", "néw.py")),
])
def test_diff_header_parser_handles_quoted_and_renamed_paths(header, expected):
    assert runner._review_diff_header_paths(header + "\n") == expected
    assert runner._review_diff_header_paths("+diff --git a/x b/x\n") is None


def test_non_ascii_and_quoted_generated_paths_are_stubbed_and_sharded_correctly(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget())
    write_changes()
    generated = ["api/café.pb.go", 'api/we"ird.pb.go']
    for name in generated:
        Path(name).parent.mkdir(exist_ok=True)
        Path(name).write_text("GENERATED_BODY\n" * 50)
    write_many(6)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="quoted", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert {item["path"] for item in admitted["coverage_skips"]} == set(generated)
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    for shard in admitted["shard_ids"]:
        entry = runner.build_review_prompts(branch="feature", shard=shard)["prompts"]["monitor"]
        diff = read_resource(Path(".map/feature"), entry, "diff")
        assert "GENERATED_BODY" not in diff
        assert diff.count("generated file omitted by review coverage policy") == len(generated)
        # Another shard's file is cut by its (non-ASCII-safe) header, so no body leaks into this shard.
        mine = set(next(item["files"] for item in current_row()["shards"] if item["id"] == shard))
        assert diff.count("added file omitted from diff") == len([name for name in mine if name.startswith("pkg_")])


@pytest.mark.parametrize("pattern,matches,misses", [
    ("/gen.go", ["gen.go"], ["sub/gen.go"]),
    ("gen.go", ["gen.go", "sub/gen.go", "a/b/gen.go"], ["gen.go.bak"]),
    ("*.dat", ["x.dat", "deep/er/x.dat"], ["x.dat.txt"]),
    ("internal/gen/*", ["internal/gen/a.py"], ["internal/gen/x/y.py", "other/internal/gen/a.py"]),
    ("**/zz.go", ["zz.go", "a/zz.go", "a/b/zz.go"], ["zz.go.x"]),
    ("a/**/b.go", ["a/b.go", "a/x/b.go", "a/x/y/b.go"], ["c/a/b.go"]),
    ("gen/**", ["gen/a.go", "gen/x/y.go"], ["gen"]),
    ("src/*/api.gen.ts", ["src/web/api.gen.ts"], ["src/web/deep/api.gen.ts"]),
    ("file[0-9].go", ["file3.go", "d/file9.go"], ["filea.go"]),
    ("a?c.go", ["abc.go"], ["a/c.go"]),
])
def test_pattern_semantics_match_gitattributes(pattern, matches, misses):
    regex = runner._review_gitattr_regex(pattern)
    assert all(regex.fullmatch(path) for path in matches), pattern
    assert not any(regex.fullmatch(path) for path in misses), pattern


def test_leading_slash_gitattribute_is_root_only_and_config_patterns_do_not_cross_directories(repo):
    del repo
    trust_on_main({".gitattributes": "/gen.go linguist-generated\n*.dat linguist-generated\n",
                   ".map/config.yaml": "review:\n  generated_patterns:\n    - 'internal/gen/*'\n    - 'api/**/v1.ts'\n"})
    write_changes("gen.go", "sub/gen.go", "deep/er/x.dat", "internal/gen/a.py", "internal/gen/x/y.py",
                  "api/web/v1.ts", "other/api/v1.ts")
    admitted = admit("patterns")
    skipped = {item["path"] for item in admitted["coverage_skips"]}
    assert skipped == {"gen.go", "deep/er/x.dat", "internal/gen/a.py", "api/web/v1.ts"}, skipped
    assert {"sub/gen.go", "internal/gen/x/y.py", "other/api/v1.ts"} <= set(admitted["required_files"])


def commit_base_and_branch():
    git("add", ".")
    git("commit", "-qm", "base files")
    git("branch", "-f", "main", "HEAD")


def interleaved(lines=3000):
    return ("".join(f"x{j} = {j}\n" for j in range(lines)).encode(),
            "".join(f"x{j} = {j}\n" if j % 2 else f"y{j} = {j}\n" for j in range(lines)).encode())


EDIT_PATTERNS = {
    "interleaved": interleaved,
    "append_only": lambda: (("".join(f"a{j}\n" for j in range(2000))).encode(),
                            ("".join(f"a{j}\n" for j in range(2000)) + "tail\n" * 500).encode()),
    "rewrite": lambda: (("old\n" * 1500).encode(), ("new line\n" * 1500).encode()),
    "cyrillic": lambda: (("Привет, мир!\n" * 1500).encode(), ("Привет, мир?\n" * 700 + "Привет, мир!\n" * 800).encode()),
    "binary": lambda: (bytes(range(256)) * 40, bytes(range(255, -1, -1)) * 40 + b"\0\1"),
}


def seed_pattern(name, count=3):
    before, after = EDIT_PATTERNS[name]()
    for index in range(count):
        Path(f"d{index}").mkdir()
        Path(f"d{index}/m.bin" if name == "binary" else f"d{index}/m.py").write_bytes(before)
    commit_base_and_branch()
    for index in range(count):
        Path(f"d{index}/m.bin" if name == "binary" else f"d{index}/m.py").write_bytes(after)


@pytest.mark.parametrize("pattern", sorted(EDIT_PATTERNS))
def test_estimate_is_never_below_the_exact_required_bytes(repo, monkeypatch, pattern):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    seed_pattern(pattern)
    admitted = runner.begin_review_run(branch="feature", provider="claude", base_ref="main", round_id="est")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    resources = shard_manifest(entry)["resources"]
    exact = sum(item["bytes"] for key, item in resources.items() if key.startswith("source_") or key == "diff")
    estimate = sum(runner._review_required_bytes(admitted["target"], admitted["required_files"]).values())
    assert estimate >= exact, (pattern, estimate, exact)


@pytest.mark.parametrize("pattern", ["interleaved", "cyrillic", "rewrite"])
def test_every_admitted_shard_builds_for_hard_edit_patterns(repo, monkeypatch, pattern):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 330_000))
    seed_pattern(pattern, count=5)
    admitted = runner.begin_review_run(branch="feature", provider="claude", base_ref="main", round_id="shards")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    for shard in admitted.get("shard_ids") or [""]:
        built = runner.build_review_prompts(branch="feature", shard=shard)
        assert built["status"] == "success", (pattern, shard, built)


def test_repo_and_check_resources_never_share_a_namespace(repo, monkeypatch):
    del monkeypatch
    del repo
    Path("check:pytest").write_text("FAKE: 0 failed, all tests passed\n")
    commit_base_and_branch()
    Path("first.py").write_text("value = 2\n")
    runner.begin_review_run(branch="feature", provider="claude", base_ref="main", round_id="ns", scheduled_reviewers=["monitor"])
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    served = serve_lazy(entry, "repo:check:pytest", "ns")
    assert served["status"] == "context_response", served
    assert json.loads(served["content"])["current_content"].startswith("FAKE")
    # The frozen repo file is not a runner-witnessed check log.
    forged = serve_lazy(entry, "check:pytest", "ns")
    assert forged["status"] == "error", forged
    row = current_row()
    assert "repo:check:pytest" in row["context_lazy"] and "check:pytest" not in row["context_lazy"]


def test_a_frozen_check_log_is_revalidated_on_every_serve(repo, monkeypatch):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="claude", base_ref="main", round_id="rv", scheduled_reviewers=["monitor"])
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    directory = Path(".map/feature")
    (directory / "check-ok.txt").write_text("all good\n")
    ledger = runner._read_review_ledger(directory)
    ledger["execution_checks"] = {"ok": {"output_artifact": "check-ok.txt"}}
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    valid = {"value": True}
    monkeypatch.setattr(runner, "_review_check_valid", lambda *_: valid["value"])
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    assert serve_lazy(entry, "check:ok", "rv")["status"] == "context_response"
    valid["value"] = False
    assert serve_lazy(entry, "check:ok", "rv")["status"] == "error"


def test_legacy_bare_path_lazy_entries_stay_readable(repo):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="claude", base_ref="main", round_id="lg", scheduled_reviewers=["monitor"])
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    assert serve_lazy(entry, "repo:dependency.py", "lg")["status"] == "context_response"
    directory = Path(".map/feature")
    ledger = runner._read_review_ledger(directory)
    row = ledger["convergence"]["rounds"][-1]
    row["context_lazy"] = {"dependency.py": row["context_lazy"]["repo:dependency.py"]}
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    assert serve_lazy(entry, "repo:dependency.py", "lg")["status"] == "context_response"
    assert list(current_row()["context_lazy"]) == ["dependency.py"]


def test_bracket_classes_never_match_the_path_separator():
    regex = runner._review_gitattr_regex("a[!x]c.go")
    assert regex.fullmatch("abc.go") and not regex.fullmatch("a/c.go")
    assert not runner._review_gitattr_regex("a[/]c.go").fullmatch("a/c.go")


@pytest.mark.parametrize("form", ["absolute", "resolved", "dot"])
def test_shard_receipt_paths_are_normalized_to_repo_relative(sharded_monitor, form):
    # #668: reviewers that list absolute or ./ paths still covered their shard.
    del sharded_monitor
    roots = {"absolute": os.getcwd() + "/", "resolved": str(Path.cwd().resolve()) + "/", "dot": "./"}
    for shard in current_row()["shards"]:
        capture_shard(current_row(), shard, covered=[roots[form] + name for name in shard["files"]])
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "COMPLETE", result["completeness"]["reasons"]


def test_receipt_path_outside_the_repository_does_not_cover_scope(sharded_monitor):
    del sharded_monitor
    for shard in current_row()["shards"]:
        capture_shard(current_row(), shard, covered=["/elsewhere/" + name for name in shard["files"]])
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == "INCOMPLETE", result
    assert any("shard scope is unread or skipped" in reason for reason in result["completeness"]["reasons"])


@pytest.mark.parametrize("skip", [False, True])
def test_unsharded_absolute_receipt_paths_cover_and_skip_required_scope(repo, skip):
    absolute = str(repo / "first.py")
    Path("first.py").write_text("value = 2\n")
    admitted = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"],
                                      provider="claude", round_id="scope", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    payload = {"discarded_candidates": [], "paraphrase": PARAPHRASE, "verdict": "approved", "issues": [], "receipt": {
        "covered_files": [absolute], "skipped_files": [absolute] if skip else [],
        "denied_access": [], "check_evidence": []}}
    assert runner.capture_review_output("monitor", json.dumps(payload), "scope", branch="feature")["status"] == "success"
    result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert result["completeness"]["status"] == ("INCOMPLETE" if skip else "COMPLETE"), result
    if not skip:
        stored = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
        assert stored["covered_files"] == ["first.py"]


def test_missing_repo_path_recovers_without_delivery_mutation(repo):
    del repo
    Path("helper_impl.go").write_text("package helper\n")
    commit_base_and_branch()
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", round_id="recovery")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "reader", "recovery", branch="feature")
    ledger = Path(".map/feature/review-verdict-ledger.json")
    before = ledger.read_bytes()
    rejected = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "repo:helper.go")),
        "recovery", branch="feature", session_id=state["session_id"], agent_id="reader")
    assert rejected["status"] == "context_request_rejected", rejected
    assert rejected["reason"] == "path_not_in_admitted_inventory"
    assert rejected["candidates"] == ["repo:helper_impl.go"]
    assert rejected["truncated"] is False
    assert ledger.read_bytes() == before
    served = serve_lazy(entry, rejected["candidates"][0], "recovery")
    assert served["status"] == "context_response", served
    assert json.loads(served["content"])["current_content"] == "package helper\n"


@pytest.mark.parametrize("delivery", ["chunk", "file"])
def test_embedded_ack_survives_missing_path_and_replay(repo, delivery):
    from tests.test_review_context_file_delivery import file_ack, read_nonce

    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", round_id="ack-miss")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "reader", "ack-miss", branch="feature")
    served = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "manifest")), "ack-miss",
        branch="feature", session_id=state["session_id"], agent_id="reader", delivery=delivery)
    assert served["status"] == "context_response", served
    ack = (file_ack(state, served, read_nonce(served)) if delivery == "file"
           else {**served, "type": "context_ack"})
    request = {**lazy_request(entry, "repo:dependency_guess.py"), "ack": ack}
    ledger = Path(".map/feature/review-verdict-ledger.json")
    before = ledger.read_bytes()
    durable = b""
    for attempt in range(2):
        rejected = runner.serve_review_context("monitor", json.dumps(request), "ack-miss",
            branch="feature", session_id=state["session_id"], agent_id="reader")
        assert rejected["status"] == "context_request_rejected", rejected
        recovered = runner.review_context_status(state["session_id"], "ack-miss", branch="feature")
        assert recovered["pending_chunk"] is None
        session = current_row()["context_sessions"][state["session_id"]]
        assert session["offsets"]["manifest"] == (served["next_offset"] if delivery == "chunk" else session["available"]["manifest"]["bytes"])
        assert "repo:dependency_guess.py" not in session["offsets"]
        assert ledger.read_bytes() != before
        if attempt == 0:
            durable = ledger.read_bytes()
        else:
            assert ledger.read_bytes() == durable


@pytest.mark.parametrize("fault", ["reviewer", "agent", "round", "manifest", "bundle", "snapshot", "fence"])
def test_missing_path_cannot_disclose_on_invalid_binding(repo, monkeypatch, fault):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", round_id="guard")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "reader", "guard", branch="feature")
    directory = Path(".map/feature")
    ledger = directory / "review-verdict-ledger.json"
    before = ledger.read_bytes()
    if fault == "manifest":
        (directory / "review-context-objects" / state["context_id"]).write_text("{}")
    elif fault == "bundle":
        (directory / current_row()["bundle_receipt"]["artifact"]).write_text("{}")
    elif fault == "snapshot":
        Path("dependency.py").write_text("changed\n")
    elif fault == "fence":
        def stale(*_args):
            del _args
            raise ValueError("freshness fence rejected")
        monkeypatch.setattr(runner, "_require_review_delivery_current", stale)
    result = runner.serve_review_context("unknown" if fault == "reviewer" else "monitor",
        json.dumps(lazy_request(entry, "repo:dependency_guess.py")), "wrong" if fault == "round" else "guard",
        branch="feature", session_id=state["session_id"], agent_id="wrong" if fault == "agent" else "reader")
    assert result["status"] == "error", result
    assert "candidates" not in result
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("name", ["", "../outside", "/absolute", "a/../b", "./dependency.py", "a//b", "a/", "a\x00b"])
def test_malformed_repo_paths_are_hard_denials(repo, name):
    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", round_id="invalid")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    result = serve_lazy(entry, "repo:" + name, "invalid")
    assert result["status"] == "error", result
    assert "candidates" not in result


def test_candidates_are_literal_deterministic_and_bounded():
    paths = {f"dir{i}/helper_impl.go" for i in range(12)} | {"unrelated.go"}
    candidates, truncated = runner._review_repo_path_candidates(paths, "helper.go")
    assert candidates == ["repo:" + p for p in sorted(paths) if "helper" in p][:8]
    assert truncated is True
    assert runner._review_repo_path_candidates(paths, "h[el]*.go") == ([], False)
    long_paths = {"é" * 800 + f"/helper_{i}.go" for i in range(2)}
    candidates, truncated = runner._review_repo_path_candidates(long_paths, "helper.go")
    assert len(json.dumps(candidates, ensure_ascii=True).encode()) <= 4096
    assert truncated is True


def test_shard_candidates_exclude_own_paths_and_cached_resources_stay_authorized(sharded, monkeypatch):
    _, row = sharded
    first, second = row["shards"][:2]
    built = runner.build_adversarial_review_prompts(branch="feature", shard=first["id"])
    entry = built["prompts"]["edge_case"]
    other = second["files"][0]
    assert serve_lazy(entry, "repo:" + other, "sharded", "edge_case")["status"] == "context_response"
    other_built = runner.build_adversarial_review_prompts(branch="feature", shard=second["id"])
    denied = serve_lazy(other_built["prompts"]["edge_case"], "repo:" + other, "sharded", "edge_case")
    assert denied["status"] == "error"
    def no_source(*_args):
        del _args
        raise AssertionError("recovery must not fetch candidate source")
    monkeypatch.setattr(runner, "_review_repo_source_entry", no_source)
    result = serve_lazy(entry, "repo:missing/module.py", "sharded", "edge_case")
    assert result["status"] == "context_request_rejected", result
    assert set(result["candidates"]) <= {"repo:" + p for p in row["target"]["context_files"] if p not in first["files"]}
    blind = serve_lazy(built["prompts"]["blind"], "repo:missing/module.py", "sharded", "blind")
    assert blind["status"] == "error" and "candidates" not in blind


@pytest.mark.parametrize("fault", ["hash", "bytes", "mixed", "file_as_chunk", "stale"])
def test_embedded_ack_rejects_forged_proofs_without_mutation(repo, fault):
    from tests.test_review_context_file_delivery import file_ack, read_nonce

    del repo
    write_changes()
    runner.begin_review_run(branch="feature", provider="codex", round_id="ack-guard")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    state = runner.bind_review_context("monitor", entry["context_transport"]["context_id"], "reader", "ack-guard", branch="feature")
    served = runner.serve_review_context("monitor", json.dumps(lazy_request(entry, "manifest")), "ack-guard",
        branch="feature", session_id=state["session_id"], agent_id="reader",
        delivery="file" if fault == "file_as_chunk" else "chunk")
    if fault == "file_as_chunk":
        ack = {**file_ack(state, served, read_nonce(served)), "chunk_sha256": "0" * 64}
    else:
        ack = {**served, "type": "context_ack"}
        if fault == "hash":
            ack["chunk_sha256"] = "0" * 64
        elif fault == "bytes":
            ack["content"] = "forged"
        elif fault == "mixed":
            ack["nonce"] = "forged"
        else:
            Path("dependency.py").write_text("stale\n")
    ledger = Path(".map/feature/review-verdict-ledger.json")
    before = ledger.read_bytes()
    result = runner.serve_review_context("monitor", json.dumps({**lazy_request(entry, "repo:missing.py"), "ack": ack}),
        "ack-guard", branch="feature", session_id=state["session_id"], agent_id="reader")
    assert result["status"] == "error", result
    assert "candidates" not in result
    assert ledger.read_bytes() == before
