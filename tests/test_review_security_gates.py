"""Sensitive review cannot trade security or human consent for fast execution."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_review_trusted_policy import git, runner
from tests.test_review_trusted_policy import policy_repo as _policy_repo

policy_repo = _policy_repo


def test_admission_reads_source_inventory_once_and_rechecks_live_changes(policy_repo, monkeypatch):
    del policy_repo
    calls = []
    original = runner._review_git_bytes

    def record(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(runner, "_review_git_bytes", record)
    admitted = runner.begin_review_run(branch="feature")
    assert admitted["status"] == "success", admitted
    inventories = [args for args in calls if args[:3] == ("ls-files", "-z", "--cached")]
    assert len(inventories) == 1, inventories
    Path("old/code.py").write_text("value = 3\n")
    resumed = runner.begin_review_run(branch="feature")
    assert resumed["status"] == "error", resumed


@pytest.fixture
def strict_repo(policy_repo):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text("review:\n  security_gates: strict\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "operator enables strict gates")
    git("checkout", "feature")


@pytest.fixture
def sensitive_repo(strict_repo):
    del strict_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    git("commit", "-am", "sensitive change")


@pytest.mark.parametrize("arguments,mode,roster", [
    ("--auto --quick", "lightweight", None),
    ("--auto", "full", ["monitor"]),
    ("--adversarial --quick", "lightweight", None),
])
def test_sensitive_forces_full_security_roster(sensitive_repo, arguments, mode, roster):
    del sensitive_repo
    result = runner.begin_review_run(branch="feature", arguments=arguments, mode=mode,
                                     scheduled_reviewers=roster)
    assert result["status"] == "success", result
    assert "security" in result["scheduled_reviewers"]
    expected = runner.ADVERSARIAL_REVIEWERS if "--adversarial" in arguments else runner.NORMAL_REVIEWERS
    assert set(result["scheduled_reviewers"]) == set(expected) | {"security"}


def test_unknown_forces_full_security_roster(strict_repo):
    del strict_repo
    Path("opaque.bin").write_bytes(b"\x00\xff")
    result = runner.begin_review_run(branch="feature", mode="lightweight")
    assert result["target"]["shadow_risk"]["tier"] == "unknown"
    assert set(result["scheduled_reviewers"]) == set(runner.NORMAL_REVIEWERS) | {"security"}
    assert "security" in result["scheduled_reviewers"]


def test_consent_is_durable_bound_and_never_agent_decidable(sensitive_repo):
    del sensitive_repo
    admitted = runner.begin_review_run(branch="feature")
    store_path = Path(".map/feature/approval_holds.json")
    store = json.loads(store_path.read_text())
    hold = next(iter(store["holds"].values()))
    assert hold["kind"] == "review_consent"
    assert hold["review_binding"] == {"target": admitted["target"], "policy_hash": admitted["policy_hash"],
                                      "action": "review-ready"}
    before = store_path.read_bytes()
    for decision in ("approved", "cancelled", "expired", "denied"):
        assert runner.decide_approval_hold(hold["id"], decision, branch="feature")["status"] == "error"
    runner.auto_decide_holds(branch="feature")
    assert store_path.read_bytes() == before
    assert runner.begin_review_run(branch="feature")["resumed"]
    assert store_path.read_bytes() == before


def test_sensitive_ready_gate_cannot_disable_consent(sensitive_repo, monkeypatch):
    del sensitive_repo
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    result = runner.write_stage_gate("review", "ready", branch="feature")
    assert result["status"] == "error"
    assert not Path(".map/feature/review-gate.json").exists()


def test_corrupt_holds_cannot_be_replaced_by_admission(sensitive_repo):
    del sensitive_repo
    path = Path(".map/feature/approval_holds.json")
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    assert path.read_text() == "{broken"


def test_security_evidence_cannot_be_normal_execution_checks(sensitive_repo):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    row["security_gate"] = {"status": "COMPLETE"}
    row["execution_checks"] = {"security": {"passed": True}}
    gate = runner._review_security_gate(row, Path(".map/feature"))
    assert gate["status"] == "INCOMPLETE"
    assert gate["reasons"]


def test_security_capture_passes_independently_but_consent_stays_pending(sensitive_repo):
    """Complete security evidence does not substitute for verified human consent."""
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admitted = runner.begin_review_run(branch="feature", provider="claude")
    payload = {"reviewer": "security", "all_clear": True, "findings": [],
               "all_clear_rationale": "Read all admitted source paths and checked their security boundaries",
               "receipt": {"covered_files": admitted["required_files"], "skipped_files": [],
                           "denied_access": [], "check_evidence": []}}
    capture = runner.capture_review_output("security", json.dumps(payload), admitted["round_id"], branch="feature")
    assert capture["status"] == "success", capture
    directory = Path(".map/feature")
    row = json.loads((directory / "review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    assert runner._review_security_gate(row, directory)["status"] == "COMPLETE"
    holds = runner.list_approval_holds(branch="feature")["holds"]
    assert holds[0]["state"] == "pending"
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"
    Path("old/code.py").write_text("changed snapshot\n")
    assert runner._review_security_gate(row, directory)["status"] == "INCOMPLETE"
    assert runner.capture_review_output("security", json.dumps(payload), admitted["round_id"],
                                        branch="feature")["status"] == "error"


@pytest.mark.parametrize("gap", [None, "skipped_files", "denied_access", "unexplained_verdict"])
def test_security_findings_consume_complete_rounds_but_missing_coverage_stays_pending(sensitive_repo, gap):
    """Separate collected security findings from missing security evidence."""
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\n")
    directory = Path(".map/feature")
    previous_capture = None
    previous_receipt = None
    for number in range(1, 4 if gap is None else 2):
        admission = runner.begin_review_run(branch="feature", provider="claude", round_id=str(number))
        assert admission["status"] == "success", admission
        if previous_capture is not None:
            archive = Path(admission["archive_path"])
            for name in ("review-agent-security.json", "adversarial-security.json"):
                assert not (directory / name).exists()
                assert (archive / name).read_bytes() == previous_capture
            assert previous_receipt is not None
            assert hashlib.sha256(previous_capture).hexdigest() == previous_receipt["sha256"]
        assert runner.create_review_bundle(branch="feature")["status"] == "success"
        receipt = {"covered_files": admission["required_files"], "skipped_files": [],
                   "denied_access": [], "check_evidence": []}
        for role in admission["scheduled_reviewers"]:
            payload = {"all_clear": True, "findings": [], "receipt": dict(receipt)}
            if role == "monitor":
                payload.update(verdict="approved", issues=[])
            elif role == "predictor":
                payload.update(risk_assessment="low", predicted_state={"breaking_changes": []})
            elif role == "evaluator":
                payload.update(overall_score=10, recommendation="proceed")
            elif role == "security":
                payload["all_clear_rationale"] = f"Security collection in attempt {number}"
                # A minor finding alone may leave the findings verdict PROCEED;
                # the independent strict security gate must still reject approval.
                payload.update(all_clear=False, findings=[{
                    "severity": "minor", "category": "security", "claim": "Review shell invocation",
                    "proof": "old/code.py uses shell=True", "cost": "unsafe input handling",
                    "counterfactual": "argv avoids shell interpretation", "failure_mode": "input interpreted by shell",
                    "anchor": "old/code.py:2", "proposed_code": "subprocess.run(argv)",
                    "bug_class": "shell_interpretation", "cause": "shell enabled for command",
                    "failure_scenario": "invoke the command through a shell",
                    "evidence_refs": [{"file_path": "old/code.py", "revision": "current",
                                       "quote": "subprocess.run(command, shell=True)"}],
                    "reachability": {"status": "reachable", "reason": "top-level shell invocation",
                        "evidence_refs": [{"file_path": "old/code.py", "revision": "current",
                                           "quote": "subprocess.run(command, shell=True)"}]},
                    "baseline_attribution": {"status": "introduced", "reason": "base contains no shell invocation",
                        "evidence_refs": [{"file_path": "old/code.py", "revision": "baseline", "quote": "value = 1"},
                                          {"file_path": "old/code.py", "revision": "current",
                                           "quote": "subprocess.run(command, shell=True)"}]}}])
                if gap == "unexplained_verdict":
                    payload["findings"] = []
                elif gap:
                    payload["receipt"][gap] = ["old/code.py"]
            assert runner.capture_review_output(role, json.dumps(payload), str(number), branch="feature")["status"] == "success"
        current_capture = (directory / "review-agent-security.json").read_bytes()
        if previous_capture is not None:
            assert current_capture != previous_capture
            assert (Path(admission["archive_path"]) / "review-agent-security.json").read_bytes() == previous_capture
        previous_capture = current_capture
        (directory / "adversarial-security.json").write_bytes(previous_capture)
        result = runner.write_review_verdict_ledger(current_run=True, branch="feature")
        assert result["status"] == "success", result
        ledger = json.loads((directory / "review-verdict-ledger.json").read_text())
        previous_receipt = ledger["convergence"]["rounds"][-1]["receipts"]["default:security"]
        assert ledger["code_approval"]["approved"] is False
        assert ledger["computed_verdict"] != "PROCEED"
        assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"
        if gap:
            assert ledger["completeness"]["status"] == ("BLOCKED" if gap == "denied_access" else "INCOMPLETE")
            assert ledger["convergence"]["attempted_rounds"] == 0
            assert "completed_at" not in ledger["convergence"]["rounds"][-1]
        else:
            assert ledger["completeness"]["status"] == "COMPLETE"
            assert ledger["findings_verdict"] == "PROCEED"
            assert ledger["security_gate"]["status"] == "BLOCKED"
            assert ledger["security_gate"]["collection_reasons"] == []
            assert ledger["convergence"]["completed_rounds"] == number
            assert runner.capture_review_output("security", "{}", str(number), branch="feature")["status"] == "error"
    if gap is None:
        assert ledger["convergence"]["outcome"] == "capped"
        assert runner.begin_review_run(branch="feature", provider="claude", round_id="4")["stop_reason"] == "reconsider_approach"


@pytest.mark.parametrize("receipt", [None, [], "invalid", {"covered_files": [{}]}, {"covered_files": [[]]}])
def test_security_capture_rejects_malformed_receipt_before_persistence(sensitive_repo, receipt):
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admitted = runner.begin_review_run(branch="feature", provider="claude")
    payload = {"reviewer": "security", "all_clear": True, "findings": [], "receipt": receipt}
    ledger_path = Path(".map/feature/review-verdict-ledger.json")
    before = ledger_path.read_bytes()
    capture = runner.capture_review_output("security", json.dumps(payload), admitted["round_id"], branch="feature")
    assert capture["status"] == "error", capture
    assert "coverage receipt" in capture["message"]
    assert ledger_path.read_bytes() == before
    assert not Path(".map/feature/review-agent-security.json").exists()
    directory = Path(".map/feature")
    row = json.loads((directory / "review-verdict-ledger.json").read_text())["convergence"]["rounds"][-1]
    gate = runner._review_security_gate(row, directory)
    assert gate["status"] == "INCOMPLETE", gate
    assert gate["reasons"]


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("defect", ["corrupt", "wrong_branch"])
def test_route_task_blocks_on_invalid_hold_store(policy_repo, dry_run, defect):
    del policy_repo
    path = Path(".map/feature/approval_holds.json")
    path.parent.mkdir(parents=True)
    content = "{broken" if defect == "corrupt" else json.dumps({
        "branch": "other-branch", "holds": {}, "next_id": 1, "updated_at": "",
    })
    path.write_text(content)
    pending = runner.get_pending_holds(branch="feature")
    assert pending["status"] == "error"
    result = runner.route_task("recommend a workflow", branch="feature", dry_run=dry_run)
    assert result["status"] == "blocked", result
    assert result["executed"] is False
    artifact = json.loads(Path(".map/feature/auto-route.json").read_text())
    assert artifact["chain_status"] == "blocked"
    assert artifact["executed"] is False
    assert pending["message"] in artifact["block_reason"]
    assert path.read_text() == content


@pytest.mark.parametrize("strict", [False, True])
def test_normal_prompt_builder_matches_security_admission(policy_repo, strict):
    del policy_repo
    if strict:
        git("checkout", "main")
        Path(".map").mkdir(exist_ok=True)
        Path(".map/config.yaml").write_text("review:\n  security_gates: strict\n")
        git("add", "-f", ".map/config.yaml")
        git("commit", "-m", "strict security admission")
        git("checkout", "feature")
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    admission = runner.begin_review_run(branch="feature")
    assert admission["status"] == "success", admission
    prompts = runner.build_review_prompts(branch="feature", review_bundle_text="BUNDLE", git_diff_text="DIFF")["prompts"]
    assert ("security" in prompts) == ("security" in admission["scheduled_reviewers"])
    assert set(admission["scheduled_reviewers"]) <= set(prompts)


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_review_skill_capture_and_quick_dispatch_follow_admitted_roster(provider):
    root = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates"
    skill = root / ("skills" if provider == "claude" else "codex/skills") / "map-review/SKILL.md"
    text = skill.read_text()
    capture = text.split("Repeat for `predictor`,", 1)[1].split("In adversarial", 1)[0]
    assert "`maintainer` and `security`" not in capture
    assert "security" in capture and "only when" in capture and "admitted roster" in capture
    assert "`user_experience`, `maintainer`, `security`; plus" not in text
    fanout = text.split("2. Fan-out:", 1)[1].split("3. Validate:", 1)[0]
    assert "for every role in the admitted roster" in fanout
    aggregate = text.split("4. Aggregate:", 1)[1].splitlines()[0]
    assert "[--edge-case <path> when admitted]" in aggregate
    assert "[--security <path> when admitted]" in aggregate


@pytest.mark.parametrize("document", [
    "README.md", "docs/ARCHITECTURE.md",
    "src/mapify_cli/templates_src/skills/map-review/review-reference.md.jinja",
])
def test_strict_gate_documentation_uses_nested_yaml_example(document):
    text = (Path(__file__).resolve().parents[1] / document).read_text()
    assert "`review.security_gates: strict`" not in text
    assert "`review: {security_gates: strict}`" in text


@pytest.mark.parametrize("control", [".map/config.yaml", ".map/scripts/control.py"])
@pytest.mark.parametrize("operation", ["modify", "delete", "rename"])
def test_tracked_map_control_changes_are_bound_and_security_reviewed(policy_repo, control, operation):
    del policy_repo
    git("checkout", "main")
    Path(".map/scripts").mkdir(parents=True)
    Path(".map/config.yaml").write_text("review:\n  security_gates: strict\n")
    Path(".map/scripts/control.py").write_text("value = 1\n")
    git("add", "-f", ".map/config.yaml", ".map/scripts/control.py")
    git("commit", "-m", "trusted control files")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    expected = {control}
    if operation == "modify":
        with Path(control).open("a") as stream:
            stream.write("# changed control\n")
    elif operation == "delete":
        git("rm", control)
    else:
        destination = ".map/scripts/renamed-control.py"
        git("mv", control, destination)
        expected.add(destination)
    admitted = runner.begin_review_run(branch="feature")
    assert admitted["status"] == "success", admitted
    assert admitted["target"]["security_gate_policy"]["mode"] == "strict"
    assert admitted["target"]["shadow_risk"]["tier"] == "sensitive"
    assert "security" in admitted["scheduled_reviewers"]
    assert expected <= set(admitted["required_files"])
    attribution = runner._review_attribution(admitted["target"])
    assert expected <= {entry["path"] for entry in attribution["files"]}
    for name in expected:
        assert name in attribution["diff"]
    assert attribution["diff_sha256"] == admitted["target"]["diff_digest"]
    before = runner._review_target()
    runtime = Path(".map/feature/runtime-noise.json")
    runtime.write_text('{"runtime": true}')
    git("add", "-f", str(runtime))
    # Even accidentally tracked runtime evidence is not control-plane source.
    assert runner._review_target() == before
    # Existing policy separately fingerprints executable Python/shell runtime;
    # ordinary untracked control-directory noise must not enter source scope.
    Path(".map/scripts").mkdir(parents=True, exist_ok=True)
    Path(".map/scripts/untracked-notes.txt").write_text("untracked notes\n")
    assert runner._review_target() == before
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    row = ledger["convergence"]["rounds"][-1]
    assert runner._review_binding_current(row)
    Path(".map/scripts/untracked-control.py").write_text("untracked = True\n")
    after = runner._review_target()
    assert after["required_files"] == before["required_files"]
    assert after["diff_digest"] == before["diff_digest"]
    assert after["local_digest"] == before["local_digest"]
    assert after["policy_hash"] != before["policy_hash"]
    assert not runner._review_binding_current(row)


def test_review_target_and_bundle_use_bounded_git_argv(policy_repo, monkeypatch):
    del policy_repo
    import errno
    import os

    # A small supported argv ceiling models E2BIG without stressing the OS.
    # Each ordinary Git call fits; expanding the inventory into argv does not.
    names = [f"source_{index:03d}_with_a_long_descriptive_name.py" for index in range(48)]
    git("checkout", "main")
    for name in names:
        Path(name).write_text("value = 1\n")
    Path("large_unchanged.bin").write_bytes(b"\0" + b"x" * 2_000_000)
    git("add", ".")
    git("commit", "-m", "ordinary source inventory")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    Path(names[0]).write_text("value = 2\n")
    real_run = subprocess.run
    limit = 1024
    oversized_calls = []

    def bounded_run(args, *positional, **kwargs):
        if not isinstance(args, str):
            size = sum(len(os.fsencode(argument)) + 1 for argument in args)
            if size > limit:
                oversized_calls.append(size)
                raise OSError(errno.E2BIG, "simulated supported argv limit")
        return real_run(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "run", bounded_run)
    admitted = runner.begin_review_run(branch="feature")
    assert admitted["status"] == "success", admitted
    assert "unverified_reason" not in admitted["target"], admitted["target"]
    assert set(names) | {"large_unchanged.bin"} <= set(admitted["required_files"])
    bundle = runner.create_review_bundle(branch="feature")
    assert bundle["status"] == "success", bundle
    persisted = json.loads(Path(".map/feature/review-bundle.json").read_text())
    assert persisted["snapshot"]["target"] == admitted["target"]
    assert persisted["attribution"]["diff_sha256"] == admitted["target"]["diff_digest"]
    attributed = {entry["path"] for entry in persisted["attribution"]["files"]}
    assert names[0] in attributed
    assert not (set(names[1:]) | {"large_unchanged.bin"}) & attributed
    markdown = Path(bundle["bundle_path_md"]).read_text()
    assert "large_unchanged.bin" not in markdown
    assert "snapshot_sha256" in markdown
    prompts = runner.build_review_prompts(branch="feature")
    assert prompts["status"] == "success", prompts
    assert max(len(entry["prompt"].encode()) for entry in prompts["prompts"].values()) < 100_000
    assert not oversized_calls


def test_oversized_review_prompt_cli_exits_nonzero_with_byte_counts(policy_repo):
    del policy_repo
    admitted = runner.begin_review_run(branch="feature")
    assert admitted["status"] == "success", admitted
    branch_dir = Path(".map/feature")
    (branch_dir / "review-bundle.md").write_text("x" * (runner.REVIEW_PROMPT_MAX_BYTES + 1))
    result = subprocess.run(
        [sys.executable, str(Path(runner.__file__).resolve()), "build_review_prompts", "--branch", "feature"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["oversized_prompt_bytes"]["monitor"] > payload["max_prompt_bytes"]


@pytest.mark.parametrize("name", ["plain.py", "space tab\tnewline\ndiff --git [*].py"])
def test_review_diff_preserves_cross_control_rename_identity(policy_repo, name):
    del policy_repo
    git("checkout", "main")
    Path(name).write_text("value = 1\n" * 20)
    git("add", "--", name)
    git("commit", "-m", "rename source")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    Path(".map/scripts").mkdir(parents=True)
    destination = ".map/scripts/" + name
    git("mv", "--", name, destination)
    target = runner._review_target()
    assert "unverified_reason" not in target, target
    attribution = runner._review_attribution(target)
    assert "similarity index 100%" in attribution["diff"]
    assert "rename from " in attribution["diff"] and "rename to " in attribution["diff"]
    assert {name, destination} <= set(target["required_files"])
    assert attribution["diff_sha256"] == target["diff_digest"]


def test_review_diff_binary_and_mode_changes_ignore_runtime_noise(policy_repo):
    del policy_repo
    git("checkout", "main")
    Path("data.bin").write_bytes(b"\x00before\xff")
    git("add", "data.bin")
    git("commit", "-m", "binary base")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    Path("data.bin").write_bytes(b"\x00after\xfe")
    Path("old/code.py").chmod(0o755)
    target = runner._review_target()
    assert "unverified_reason" not in target, target
    attribution = runner._review_attribution(target)
    assert "GIT binary patch" in attribution["diff"]
    assert "old mode 100644" in attribution["diff"]
    assert "new mode 100755" in attribution["diff"]
    runtime = Path(".map/feature/noise.txt")
    runtime.parent.mkdir(parents=True)
    runtime.write_text("diff --git fake header\n")
    git("add", "-f", str(runtime))
    assert runner._review_target() == target
    assert runner._review_attribution(target) == attribution


def test_review_positive_pathspec_filters_before_rename(policy_repo):
    del policy_repo
    # Proposal only: prove Git's pathname/glob semantics before production use.
    positive = (
        ":(top,glob)*", ":(top,glob)[!.]*/**", ":(top,glob).[!m]*/**",
        ":(top,glob).m[!a]*/**", ":(top,glob).ma[!p]*/**",
        ":(top,glob).map?*/**", ":(top,glob).m/**", ":(top,glob).ma/**",
        ":(top,literal).map/config.yaml", ":(top,glob).map/scripts/**",
    )
    selected = {
        "root.txt", ".root", ".m/short.txt", ".ma/short.txt", ".mapX/long.txt",
        ".github/workflows/check.yml", "ordinary/deep/code.py", "ordinary/.map/nested.txt",
        "odd space\ttab\nline[*].txt", ".map/config.yaml", ".map/scripts/control.py",
        "rename-source.py",
    }
    runtime = ".map/feature/runtime.txt"
    git("checkout", "main")
    for name in selected | {runtime}:
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("same rename content\n" * 20 if name == "rename-source.py" else f"original {name}\n")
    git("add", "-f", "--", *sorted(selected | {runtime}))
    git("commit", "-m", "pathspec oracle base")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    base = git("rev-parse", "HEAD")

    def output(*args):
        return subprocess.run(["git", *args], check=True, capture_output=True).stdout

    root_matches = set(output("ls-files", "-z", "--", ":(top,glob)*").split(b"\0")) - {b""}
    assert runtime.encode() not in root_matches, "root glob must not recursively include .map runtime"
    assert b"root.txt" in root_matches and b".root" in root_matches
    assert b".map/scripts/control.py" not in root_matches
    inventory = set(output("ls-files", "-z").split(b"\0")) - {b""}
    expected = {name for name in inventory if not name.startswith(b".map/")
                or name == b".map/config.yaml" or name.startswith(b".map/scripts/")}
    actual = set(output("ls-files", "-z", "--", *positive).split(b"\0")) - {b""}
    assert actual == expected
    production = runner._review_source_pathspec([name.decode() for name in sorted(expected)])
    assert output("ls-files", "-z", "--", *production) == output("ls-files", "-z", "--", *positive)

    destination = ".map/scripts/renamed.py"
    git("mv", "rename-source.py", destination)
    # An equally good excluded candidate must not compete for the rename.
    excluded = Path(".map/feature/identical-candidate.py")
    excluded.write_text("same rename content\n" * 20)
    git("add", "-f", str(excluded))
    Path(runtime).write_text("changed runtime\n")
    Path("root.txt").write_text("changed source\n")
    oracle_names = expected | {destination.encode()}
    oracle = [f":(top,literal){name.decode()}" for name in sorted(oracle_names)]
    actual_diff = output("diff", "--binary", "--find-renames", base, "--", *positive)
    oracle_diff = output("diff", "--binary", "--find-renames", base, "--", *oracle)
    assert actual_diff == oracle_diff
    assert output("diff", "--binary", "--find-renames", base, "--", *production) == oracle_diff
    assert output("ls-files", "--stage", "-z", "--", *production) == output(
        "ls-files", "--stage", "-z", "--", *oracle,
    )
    assert b"similarity index 100%" in actual_diff
    assert b"rename from rename-source.py" in actual_diff
    assert b"rename to .map/scripts/renamed.py" in actual_diff
    assert b"identical-candidate" not in actual_diff and runtime.encode() not in actual_diff
    assert output("ls-files", "--stage", "-z", "--", *positive) == output(
        "ls-files", "--stage", "-z", "--", *oracle,
    )

    untracked = Path(".map/scripts/untracked.txt")
    untracked.write_text("untracked noise\n")
    git("config", "status.renames", "true")
    # .map is ignored by the fixture; force enumeration to exercise ?? filtering.
    with Path(".gitignore").open("a") as stream:
        stream.write("!.map/\n!.map/scripts/\n!.map/scripts/untracked.txt\n")
    status = output("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *positive)
    assert b"?? .map/scripts/untracked.txt\0" in status
    filtered = []
    records = status.split(b"\0")
    index = 0
    while index < len(records) - 1:
        record = records[index]
        index += 1
        group = [record]
        if b"R" in record[:2] or b"C" in record[:2]:
            group.append(records[index])
            index += 1
        if record[:2] == b"??" and record[3:] not in oracle_names:
            continue
        filtered.extend(group)
    expected_status = output("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *oracle)
    assert b"".join(record + b"\0" for record in filtered) == expected_status
    assert runner._review_source_status([name.decode() for name in sorted(oracle_names)]) == expected_status


def test_review_config_directory_is_not_a_control_subtree(policy_repo):
    del policy_repo
    directory = Path(".map/config.yaml")
    directory.mkdir(parents=True)
    (directory / "not-config.txt").write_text("excluded subtree\n")
    git("add", "-f", str(directory))
    paths = runner._review_source_paths("HEAD")
    assert ".map/config.yaml/not-config.txt" not in paths
    pathspec = runner._review_source_pathspec(paths)
    for args in [("ls-files", "-z"), ("ls-files", "--stage", "-z"), ("diff", "--binary", "HEAD")]:
        output = subprocess.run(["git", *args, "--", *pathspec], check=True, capture_output=True).stdout
        assert b"not-config.txt" not in output
    target = runner._review_target()
    assert "unverified_reason" not in target, target
    assert ".map/config.yaml/not-config.txt" not in target["required_files"]


@pytest.mark.parametrize("to_runtime", [False, True])
def test_review_pathspec_excluded_rename_endpoints_match_literal_oracle(policy_repo, to_runtime):
    del policy_repo
    selected = "ordinary/source.txt"
    excluded = ".map/feature/runtime.txt"
    git("checkout", "main")
    original = selected if to_runtime else excluded
    destination = excluded if to_runtime else selected
    Path(original).parent.mkdir(parents=True)
    Path(original).write_text("identical content\n" * 20)
    git("add", "-f", original)
    git("commit", "-m", "boundary rename source")
    git("checkout", "feature")
    git("merge", "--ff-only", "main")
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    git("mv", original, destination)
    names = runner._review_source_paths("HEAD")
    actual = runner._review_git_bytes("diff", "--binary", "--find-renames", "HEAD", "--",
                                    *runner._review_source_pathspec(names))
    oracle = runner._review_git_bytes("diff", "--binary", "--find-renames", "HEAD", "--",
                                    *(f":(top,literal){name}" for name in names))
    assert actual == oracle
    assert excluded.encode() not in actual
    assert selected.encode() in actual


def test_generic_hold_creation_rejects_reserved_review_consent(policy_repo):
    del policy_repo
    result = runner.create_approval_hold(
        "review_consent", "operator selected reserved kind", "unbound consent", branch="feature",
    )
    assert result["status"] == "error", result
    assert not Path(".map/feature/approval_holds.json").exists()
    assert runner.get_pending_holds(branch="feature")["resume_blocked"] is False


def test_hold_restart_and_changed_snapshot_preserve_pending_history(sensitive_repo):
    del sensitive_repo
    admitted = runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    before = path.read_bytes()
    script = ("import sys,json; sys.path.insert(0,sys.argv[1]); import map_step_runner as r; "
              "print(json.dumps(r.begin_review_run(branch='feature')))")
    scripts = str(Path(runner.__file__).parent)
    child = subprocess.run([sys.executable, "-I", "-c", script, scripts],
                           check=True, capture_output=True, text=True)
    assert json.loads(child.stdout)["resumed"]
    assert path.read_bytes() == before
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(other, shell=True)\n")
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    holds = json.loads(path.read_text())["holds"]
    assert len(holds) == 2
    assert holds["hold-001"]["review_binding"]["target"] == admitted["target"]
    assert holds["hold-001"]["review_binding"] != holds["hold-002"]["review_binding"]
    assert all(hold["state"] == "pending" for hold in holds.values())


@pytest.mark.parametrize("rationale", ["Read all required paths and checked security boundaries", "missing", None, "", "  ", [], 42])
def test_complete_review_waits_without_spending_rounds(sensitive_repo, rationale):
    """Require a clear security explanation before sealing and waiting for consent."""
    del sensitive_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    admitted = runner.begin_review_run(branch="feature", provider="claude")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    receipt = {"covered_files": admitted["required_files"], "skipped_files": [],
               "denied_access": [], "check_evidence": []}
    outputs = {"monitor": {"verdict": "approved", "issues": []},
               "predictor": {"risk_assessment": "low", "predicted_state": {"breaking_changes": []}},
               "evaluator": {"overall_score": 10, "recommendation": "proceed"}}
    assert "security" in admitted["scheduled_reviewers"]
    security_output = {}
    for role in admitted["scheduled_reviewers"]:
        output = {**outputs.get(role, {"all_clear": True, "findings": []}), "receipt": receipt}
        if role == "security":
            if rationale != "missing":
                output["all_clear_rationale"] = rationale
            security_output = output
        assert runner.capture_review_output(role, json.dumps(output), admitted["round_id"],
                                            branch="feature")["status"] == "success"
    final = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    if not isinstance(rationale, str) or not rationale.strip() or rationale == "missing":
        assert final["code_approval"]["approved"] is False
        assert final["completeness"]["status"] == "INCOMPLETE"
        assert final["convergence"]["attempted_rounds"] == 0
        assert "completed_at" not in final["convergence"]["rounds"][-1]
        security_output["all_clear_rationale"] = "Read admitted paths; no security findings survived validation"
        assert runner.capture_review_output("security", json.dumps(security_output), admitted["round_id"],
                                            branch="feature")["status"] == "success"
        final = runner.write_review_verdict_ledger(current_run=True, branch="feature")
    assert final["code_approval"]["approved"], final
    assert final["convergence"]["outcome"] == "awaiting_human"
    ledger_path = Path(".map/feature/review-verdict-ledger.json")
    before = ledger_path.read_bytes()
    for _ in range(4):
        resumed = runner.begin_review_run(branch="feature", provider="claude")
        assert resumed["stop_reason"] == "human_consent_pending"
        assert resumed["round_id"] == admitted["round_id"]
    assert ledger_path.read_bytes() == before


def test_untracked_profile_never_lowers_strict_review(strict_repo):
    del strict_repo
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\n")
    result = runner.begin_review_run(branch="feature", scheduled_reviewers=["monitor"])
    assert result["target"]["shadow_risk"]["tier"] == "sensitive"
    assert set(result["scheduled_reviewers"]) == set(runner.NORMAL_REVIEWERS) | {"security"}


@pytest.mark.parametrize("head_mode", ["shadow", "strict"])
def test_default_shadow_cannot_be_changed_by_pr_config(policy_repo, head_mode):
    del policy_repo
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {head_mode}\n")
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    result = runner.begin_review_run(branch="feature", mode="lightweight", arguments="--auto --quick")
    assert result["status"] == "success", result
    assert result["scheduled_reviewers"] == ["monitor"]
    assert result["target"]["security_gate_policy"]["mode"] == "shadow"
    holds = runner.list_approval_holds(branch="feature")["holds"]
    assert len(holds) == 1 and holds[0]["state"] == "pending"
    assert holds[0]["enforcement"] == "shadow"
    assert not runner.get_pending_holds(branch="feature")["resume_blocked"]
    runner.auto_decide_holds(branch="feature")
    assert runner.list_approval_holds(branch="feature")["holds"] == holds


@pytest.mark.parametrize("defect", ["corrupt", "write_failure", "terminal"])
def test_shadow_consent_errors_are_nonblocking_diagnostics(policy_repo, monkeypatch, defect):
    del policy_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    path = Path(".map/feature/approval_holds.json")
    path.parent.mkdir(parents=True)
    if defect == "corrupt":
        path.write_text("{broken")
    elif defect == "terminal":
        assert runner.begin_review_run(branch="feature")["status"] == "success"
        store = json.loads(path.read_text())
        next(iter(store["holds"].values()))["state"] = "approved"
        path.write_text(json.dumps(store))
    else:
        original = runner._write_json_file

        def fail_hold_write(destination, data):
            if destination.name == "approval_holds.json":
                raise OSError("hold store unavailable")
            return original(destination, data)

        monkeypatch.setattr(runner, "_write_json_file", fail_hold_write)
    before = path.read_bytes() if path.exists() else None
    result = runner.begin_review_run(branch="feature")
    assert result["status"] == "success", result
    assert result["human_consent"]["status"] == "error"
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    assert ledger["human_consent"] == result["human_consent"]
    assert (path.read_bytes() if path.exists() else None) == before
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "success"
    if defect == "corrupt":
        assert runner.get_pending_holds(branch="feature")["resume_blocked"] is True


def test_shadow_resume_reports_unwritable_diagnostic_ledger(policy_repo, monkeypatch):
    del policy_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    assert runner.begin_review_run(branch="feature")["status"] == "success"
    Path(".map/feature/approval_holds.json").write_text("{broken")
    original = runner._write_json_file

    def fail_ledger_write(destination, data):
        if destination.name == "review-verdict-ledger.json":
            raise OSError("diagnostic ledger unavailable")
        return original(destination, data)

    monkeypatch.setattr(runner, "_write_json_file", fail_ledger_write)
    result = runner.begin_review_run(branch="feature")
    assert result["status"] == "success", result
    assert result["human_consent"]["status"] == "error"
    assert result["human_consent"]["persistence_error"] == "diagnostic ledger unavailable"


@pytest.mark.parametrize("policy_path", ["REVIEW.md", "old/REVIEW.md"])
@pytest.mark.parametrize("defect", ["symlink", "nontext"])
@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_invalid_policy_content_cannot_downgrade_trusted_gate_config(
    policy_repo, monkeypatch, policy_path, defect, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    path = Path(policy_path)
    path.unlink()
    if defect == "symlink":
        path.symlink_to("missing-policy")
    else:
        path.write_bytes(b"\xff\xfe")
    git("add", "-f", ".map/config.yaml", policy_path)
    git("commit", "-m", "invalid policy content with explicit gate config")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    # First ready attempt: there is no earlier round to preserve strict mode.
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    gate = runner.write_stage_gate("review", "ready", branch="feature")
    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    admitted = runner.begin_review_run(branch="feature", mode="lightweight")
    assert admitted["status"] == "success", admitted
    assert admitted["target"]["trusted_policy"]["status"] == "unverified"
    assert admitted["target"]["security_gate_policy"]["mode"] == mode
    # Existing policy protection remains active without the legacy override.
    monkeypatch.delenv("MAP_REVIEW_LEDGER_ENFORCE")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"


@pytest.mark.parametrize("config", ["review: [", "review: {security_gates: other}"])
def test_invalid_trusted_gate_config_fails_closed_before_first_round(policy_repo, monkeypatch, config):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(config)
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "invalid trusted gate configuration")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"


@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_snapshot_failure_preserves_trusted_gate_mode_before_first_round(
    policy_repo, monkeypatch, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "trusted gate mode")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    assert not Path(".map/feature/review-verdict-ledger.json").exists()
    file_entry = runner._review_file_entry
    failed_paths = []

    def fail_tracked_snapshot(name):
        if name == "old/code.py":
            failed_paths.append(name)
            raise OSError("snapshot unavailable")
        return file_entry(name)

    monkeypatch.setattr(runner, "_review_file_entry", fail_tracked_snapshot)
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert failed_paths, "the tracked-file snapshot failure must be exercised"
    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    assert Path(".map/feature/review-gate.json").exists() is (mode == "shadow")
    if mode == "strict":
        target = runner._review_target()
        assert target["security_gate_policy"]["mode"] == "strict"


@pytest.mark.parametrize("mode", ["strict", "shadow"])
def test_corrupt_prior_ledger_respects_trusted_mode_with_legacy_override(
    policy_repo, monkeypatch, mode,
):
    del policy_repo
    git("checkout", "main")
    Path(".map").mkdir(exist_ok=True)
    Path(".map/config.yaml").write_text(f"review:\n  security_gates: {mode}\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "trusted gate mode")
    git("checkout", "feature")
    Path("old/code.py").write_text("value = 2\n")
    ledger = Path(".map/feature/review-verdict-ledger.json")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")

    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert gate["status"] == ("error" if mode == "strict" else "success"), gate
    assert Path(".map/feature/review-gate.json").exists() is (mode == "shadow")
    assert ledger.read_text(encoding="utf-8") == "{broken"


def test_shadow_legacy_override_still_blocks_retained_strict_round(strict_repo, monkeypatch):
    del strict_repo
    Path("old/code.py").write_text("import subprocess\nsubprocess.run(command, shell=True)\n")
    admission = runner.begin_review_run(branch="feature")
    assert admission["status"] == "success", admission
    assert admission["target"]["security_gate_policy"]["mode"] == "strict"
    git("checkout", "main")
    Path(".map/config.yaml").write_text("review:\n  security_gates: shadow\n")
    git("add", "-f", ".map/config.yaml")
    git("commit", "-m", "operator switches current policy to shadow")
    git("checkout", "feature")
    assert runner._review_target()["security_gate_policy"]["mode"] == "shadow"
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")

    gate = runner.write_stage_gate("review", "ready", branch="feature")

    assert gate["status"] == "error", gate
    assert not Path(".map/feature/review-gate.json").exists()


@pytest.mark.parametrize("failure", ["head", "merge_base"])
def test_early_snapshot_failure_retains_resolved_strict_authority(strict_repo, monkeypatch, failure):
    del strict_repo
    original_git = runner._review_git

    def fail_snapshot_git(*args):
        if ((failure == "head" and args == ("rev-parse", "HEAD"))
                or (failure == "merge_base" and args[0] == "merge-base")):
            raise OSError("snapshot ancestry unavailable")
        return original_git(*args)

    monkeypatch.setattr(runner, "_review_git", fail_snapshot_git)
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    target = runner._review_target()
    assert target["security_gate_policy"]["mode"] == "strict"
    gate = runner.write_stage_gate("review", "ready", branch="feature")
    assert gate["status"] == "error", gate
    assert not Path(".map/feature/review-gate.json").exists()


def test_corrupt_sequence_cannot_overwrite_consent_via_generic_hold(sensitive_repo):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    store = json.loads(path.read_text())
    store["next_id"] = 1
    path.write_text(json.dumps(store))
    before = path.read_bytes()
    result = runner.create_approval_hold("dangerous_action", "reason", "another action", branch="feature")
    assert result["status"] == "error"
    assert path.read_bytes() == before


@pytest.mark.parametrize("state", ["approved", "cancelled", "expired", "denied"])
def test_forged_terminal_consent_is_rejected(sensitive_repo, state):
    del sensitive_repo
    runner.begin_review_run(branch="feature")
    path = Path(".map/feature/approval_holds.json")
    store = json.loads(path.read_text())
    hold = next(iter(store["holds"].values()))
    hold.update(state=state, approved_by="human", tool_name="AskUserQuestion")
    path.write_text(json.dumps(store))
    before = path.read_bytes()
    assert runner.begin_review_run(branch="feature")["status"] == "error"
    assert runner.write_stage_gate("review", "ready", branch="feature")["status"] == "error"
    assert path.read_bytes() == before
