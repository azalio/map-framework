"""Diff coverage is distinct from the immutable context inventory."""

import importlib
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
    assert "dependency.py" not in row.get("context_lazy", {})
    request["resource_id"] = resource
    response = runner.serve_review_context("monitor", json.dumps(request), "scope", branch="feature",
                                         session_id=state["session_id"], agent_id="reader")
    assert json.loads(response["content"])["current_content"] == "value = 1\n"
    ack = runner.ack_review_context(state["session_id"], "reader", json.dumps(response), "scope", branch="feature")
    assert ack["status"] == "context_pending"
    row = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    assert row["context_lazy"]["dependency.py"]["required"] is False
    assert row["context_sessions"][state["session_id"]]["offsets"][resource] > 0
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
    payload = {"verdict": "approved", "issues": [], "receipt": {
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
    for denied in ("repo:first.py", "repo:not-tracked.py", "repo:", "repo:../outside"):
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
    assert "UNTRACKED_DIFF_MARKER" in diff
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
