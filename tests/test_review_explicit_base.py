"""Issue #557: stacked review scope is durable and separate from policy authority."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from tests.review_context_helpers import original_review_prompt

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"
sys.path.insert(0, str(SCRIPTS))
import map_step_runner  # type: ignore[import-not-found]

runner = cast(Any, map_step_runner)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "absent-gitconfig"))
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    git("init", "-b", "main")
    git("config", "user.email", "review-test@example.invalid")
    git("config", "user.name", "Review Test")
    git("config", "commit.gpgsign", "false")
    Path(".gitignore").write_text(".map/\n")
    Path("REVIEW.md").write_text("MAIN_POLICY: preserve validation.\n")
    Path("product.py").write_text("PRODUCT = 0\n")
    Path("dirty.py").write_text("DIRTY = 0\n")
    git("add", ".")
    git("commit", "-m", "main foundation")
    main = git("rev-parse", "HEAD")
    git("checkout", "-b", "runtime")
    Path("runtime.py").write_text("PARENT_ONLY = 1701\n")
    Path("REVIEW.md").write_text("FEATURE_POLICY: skip validation.\n")
    git("add", ".")
    git("commit", "-m", "runtime parent change")
    runtime = git("rev-parse", "HEAD")
    git("checkout", "-b", "product")
    Path("product.py").write_text("PRODUCT = 557\n")
    git("commit", "-am", "product child change")
    return {"main": main, "runtime": runtime, "root": tmp_path}


def fresh(function: str, **kwargs: Any) -> Any:
    code = (
        "import json,sys; sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); "
        "import map_step_runner as r; "
        "print(json.dumps(getattr(r,sys.argv[2])(**json.loads(sys.argv[3]))))"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code, str(SCRIPTS), function, json.dumps(kwargs)],
        check=False, capture_output=True, text=True, timeout=45,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPTS / "map_step_runner.py"), *args],
        check=False, capture_output=True, text=True, timeout=45,
    )


def ledger_path() -> Path:
    return Path(".map/product/review-verdict-ledger.json")


def row() -> dict[str, Any]:
    return json.loads(ledger_path().read_text())["convergence"]["rounds"][-1]


def admit(**kwargs: Any) -> dict[str, Any]:
    result = runner.begin_review_run(branch="product", round_id="stack", **kwargs)
    assert result["status"] == "success", result
    return result


def assert_rejected(call):
    try:
        result = call()
    except (ValueError, RuntimeError):
        return
    assert result.get("status") == "error", result
    assert "unexpected keyword argument" not in result.get("message", ""), result


def artifacts() -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in Path(".map").rglob("*")
            if p.is_file() and not p.name.endswith(".lock")}


def test_default_control_retains_parent_diff_and_main_policy(stack):
    admission = admit()
    assert admission["target"]["base"] == stack["main"]
    snapshot = fresh("snapshot_code_state", branch="product")
    assert {"runtime.py", "product.py"} <= set(snapshot["files_changed"])
    assert admission["target"]["trusted_policy"]["revision"] == stack["main"]


def test_learning_handoff_after_review_fix_commit_records_base_drift(stack):
    admit(base_ref="runtime")
    Path(".map/product/verification-summary.md").write_text("ADMITTED VALIDATION\n")
    assert runner.create_review_bundle(branch="product")["status"] == "success"
    bundle_path = Path(".map/product/review-bundle.json")
    admitted_bundle = bundle_path.read_bytes()
    admitted_pr_handoff = json.loads(admitted_bundle)["pr_handoff"]
    admitted_review_handoff = json.loads(admitted_bundle)["review_handoff"]
    assert "ADMITTED VALIDATION" in admitted_pr_handoff["validation"]
    assert "ADMITTED VALIDATION" in admitted_review_handoff["verification_summary"]

    Path("product.py").write_text("PRODUCT = 575\n")
    git("commit", "-am", "review fix")
    fixed_head = git("rev-parse", "HEAD")
    git("branch", "-f", "runtime", "HEAD")
    Path(".map/product/verification-summary.md").write_text("POST-FIX VALIDATION\n")
    bundle_path.write_text(json.dumps({"pr_handoff": {"summary": "REPLACED"}}))

    strict_snapshot = runner.snapshot_code_state(branch="product")
    assert strict_snapshot["status"] == "error"
    result = runner.write_learning_handoff(
        "map-review", outcome="REVISE", next_action="Resume review",
        notes="Record the review fix", branch="product",
    )
    assert result["status"] == "success", result
    payload = json.loads(Path(".map/product/learning-handoff.json").read_text())
    assert payload["git_ref"] == fixed_head[:12]
    assert payload["review_binding_drift"] == runner._REVIEW_BASE_DRIFT
    assert payload["validation"] == admitted_pr_handoff["validation"]
    assert payload["documents"]["verification_summary"] == admitted_review_handoff["verification_summary"]
    assert "POST-FIX VALIDATION" not in payload["validation"]
    assert "product.py" in payload["files_changed"]
    assert "Review Binding Drift" in Path(".map/product/learning-handoff.md").read_text()
    assert json.loads(bundle_path.read_text())["pr_handoff"]["summary"] == "REPLACED"


def test_learning_handoff_requires_admitted_bundle_after_base_drift(stack):
    admit(base_ref="runtime")
    assert runner.create_review_bundle(branch="product")["status"] == "success"
    (Path(".map/product") / row()["bundle_receipt"]["artifact"]).unlink()
    git("branch", "-f", "runtime", "HEAD")
    result = runner.write_learning_handoff("map-review", branch="product")
    assert result["status"] == "error"
    assert "Admitted review bundle" in result["message"]
    assert not Path(".map/product/learning-handoff.json").exists()
    command = cli("write_learning_handoff", "map-review")
    assert command.returncode != 0
    assert json.loads(command.stdout)["status"] == "error"


def test_learning_handoff_rejects_changed_admitted_bundle_object(stack):
    admit(base_ref="runtime")
    assert runner.create_review_bundle(branch="product")["status"] == "success"
    object_path = Path(".map/product") / row()["bundle_receipt"]["artifact"]
    object_path.write_text(object_path.read_text() + " ")
    git("branch", "-f", "runtime", "HEAD")
    result = runner.write_learning_handoff("map-review", branch="product")
    assert result["status"] == "error"
    assert "Admitted review bundle" in result["message"]
    assert not Path(".map/product/learning-handoff.json").exists()


def test_incomplete_admitted_target_is_not_treated_as_base_drift(stack):
    del stack
    admit()
    ledger = json.loads(ledger_path().read_text())
    ledger["convergence"]["rounds"][-1]["target"] = {}
    ledger_path().write_text(json.dumps(ledger))
    snapshot = runner.snapshot_code_state(branch="product", allow_review_drift=True)
    assert snapshot["status"] == "error"
    assert "target is incomplete" in snapshot["message"]
    result = runner.write_learning_handoff("map-review", branch="product")
    assert result["status"] == "error"
    assert "target is incomplete" in result["message"]


def test_learning_handoff_returns_structured_error_for_corrupt_review_admission(stack):
    del stack
    admit()
    mode_path = Path(".map/product/review-mode.json")
    mode_path.write_text("{invalid")
    result = runner.write_learning_handoff("map-review", branch="product")
    assert result["status"] == "error"
    assert "Review mode" in result["message"]


def test_explicit_api_scope_snapshot_bundle_prompts_and_policy(stack):
    admission = admit(base_ref="runtime")
    target = admission["target"]
    assert target["base"] == target["base_tip"] == stack["runtime"]
    assert target["trusted_policy"]["revision"] == stack["main"]
    assert "FEATURE_POLICY" not in json.dumps(target["trusted_policy"])
    assert "runtime.py" in admission["required_files"], "Full inventory must not be narrowed to diff paths"
    snapshot = fresh("snapshot_code_state", branch="product")
    assert snapshot["diff_base"] == stack["runtime"][:12]
    assert snapshot["files_changed"] == ["product.py"]
    bundle_result = fresh("create_review_bundle", branch="product")
    bundle = json.loads(Path(bundle_result["bundle_path_json"]).read_text())
    assert bundle["snapshot"]["target"] == target
    assert bundle["attribution"]["base"] == stack["runtime"]
    assert "+PRODUCT = 557" in bundle["attribution"]["diff"]
    assert "+PARENT_ONLY = 1701" not in bundle["attribution"]["diff"]
    for function in ("build_review_prompts", "build_adversarial_review_prompts"):
        prompts = fresh(function, branch="product")["prompts"]
        assert prompts
        for name, entry in prompts.items():
            prompt = original_review_prompt(runner, entry, name, branch="product")
            assert "+PARENT_ONLY = 1701" not in prompt, name
            assert "+PRODUCT = 557" in prompt, name


def test_cli_admission_persists_scope_for_fresh_consumers(stack):
    proc = cli("begin_review_run", "--base-ref", "runtime", "--round-id", "cli-stack")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    admitted = json.loads(proc.stdout)
    assert admitted["status"] == "success", admitted
    assert row()["binding"]["base_ref"] == "runtime"
    before = ledger_path().read_bytes()
    resumed = fresh("begin_review_run", base_ref="runtime", round_id="cli-stack")
    assert resumed["resumed"] is True
    assert ledger_path().read_bytes() == before
    assert fresh("snapshot_code_state")["diff_base"] == stack["runtime"][:12]


def test_explicit_diff_keeps_staged_and_unstaged_work(stack):
    del stack
    Path("dirty.py").write_text("DIRTY = 91\n")
    git("add", "dirty.py")
    Path("product.py").write_text("PRODUCT = 558\n")
    admit(base_ref="runtime")
    bundle_result = fresh("create_review_bundle")
    diff = json.loads(Path(bundle_result["bundle_path_json"]).read_text())["attribution"]["diff"]
    assert "+DIRTY = 91" in diff and "+PRODUCT = 558" in diff
    assert "+PARENT_ONLY = 1701" not in diff
    snapshot = fresh("snapshot_code_state")
    assert {"dirty.py", "product.py"} <= set(snapshot["uncommitted_files_changed"])


@pytest.mark.parametrize("base", ["", "missing-ref", "--not-a-ref", "unrelated"])
def test_invalid_explicit_ref_rejected_without_admission_mutation(stack, base):
    del stack
    if base == "unrelated":
        tree = git("rev-parse", "HEAD^{tree}")
        commit = git("commit-tree", tree, "-m", "unrelated root")
        git("update-ref", "refs/heads/unrelated", commit)
    directory = Path(".map/product")
    directory.mkdir(parents=True)
    (directory / "monitor-review.json").write_text('{"sentinel":"preserve"}')
    before = artifacts()
    assert_rejected(lambda: runner.begin_review_run(branch="product", base_ref=base))
    assert artifacts() == before


@pytest.mark.parametrize("mutation", ["move", "delete", "policy"])
def test_explicit_binding_stales_on_target_or_independent_policy_change(stack, mutation):
    admission = admit(base_ref="runtime")
    assert runner._review_binding_current(row()) is True
    if mutation == "delete":
        git("branch", "-D", "runtime")
    else:
        branch = "runtime" if mutation == "move" else "main"
        git("checkout", branch)
        if mutation == "policy":
            Path("REVIEW.md").write_text("MAIN_POLICY: stricter validation.\n")
        git("commit", "-am", "advance authority", "--allow-empty")
        git("checkout", "product")
        if mutation == "move":
            assert git("merge-base", "runtime", "HEAD") == stack["runtime"]
    assert runner._review_binding_current(row()) is False
    before = ledger_path().read_bytes()
    assert_rejected(lambda: runner.begin_review_run(branch="product", round_id="stack", base_ref="runtime"))
    assert ledger_path().read_bytes() == before
    assert admission["target"]["base"] == stack["runtime"]


def test_historical_binding_uses_own_target_and_new_default_does_not_inherit(stack):
    admit(base_ref="runtime")
    historical = row()
    runner.abandon_review_round("stack", "different review scope", branch="product")
    default = runner.begin_review_run(branch="product", round_id="default")
    assert default["status"] == "success", default
    assert default["target"]["base"] == stack["main"]
    assert "base_ref" not in row()["binding"]
    assert runner._review_binding_current(historical) is True
    git("branch", "-D", "runtime")
    assert runner._review_binding_current(historical) is False
    assert runner._review_binding_current(row()) is True


@pytest.mark.parametrize("corruption", ["malformed", "wrong-round", "wrong-binding", "pending"])
@pytest.mark.parametrize("consumer", ["snapshot_code_state", "build_review_prompts", "create_review_bundle"])
def test_consumers_fail_closed_on_incoherent_admission(stack, corruption, consumer):
    del stack
    admit()
    mode_path = Path(".map/product/review-mode.json")
    mode = json.loads(mode_path.read_text())
    if corruption == "malformed":
        mode_path.write_text("{invalid")
    elif corruption == "pending":
        ledger = json.loads(ledger_path().read_text())
        ledger["convergence"]["rounds"][-1]["prepared"] = False
        ledger_path().write_text(json.dumps(ledger))
    else:
        mode["round_id" if corruption == "wrong-round" else "arguments"] = "not-admitted"
        mode_path.write_text(json.dumps(mode))
    assert_rejected(lambda: getattr(runner, consumer)(branch="product"))


@pytest.mark.parametrize("outcome", ["passed", "awaiting_human"])
@pytest.mark.parametrize("change", ["roster", "checks", "base"])
def test_terminal_resume_compares_complete_request_before_shortcuts(stack, outcome, change):
    del stack
    admit(scheduled_reviewers=["monitor"])
    ledger = json.loads(ledger_path().read_text())
    ledger["convergence"]["outcome"] = outcome
    ledger["convergence"]["rounds"][-1].update({"completed_at": 1, "verdict": "PROCEED"})
    ledger_path().write_text(json.dumps(ledger))
    same = runner.begin_review_run(branch="product", round_id="stack", scheduled_reviewers=["monitor"])
    assert same["status"] == "success" and same["resumed"] is True, same
    changed: dict[str, Any] = {"scheduled_reviewers": ["monitor"]}
    if change == "roster":
        changed["scheduled_reviewers"] = list(runner.NORMAL_REVIEWERS)
    elif change == "checks":
        changed.update(required_checks=["suite"], check_specs={"suite": [sys.executable, "-c", "pass"]})
    else:
        changed["base_ref"] = "runtime"
    assert_rejected(lambda: runner.begin_review_run(branch="product", round_id="stack", **changed))


@pytest.mark.parametrize("function", ["build_review_prompts", "build_adversarial_review_prompts"])
def test_role_code_baseline_uses_admitted_merge_base_even_without_explicit_flag(stack, function):
    # Diverge main: its tip is NOT the pre-change version of product.
    git("checkout", "main")
    Path("product.py").write_text("PRODUCT = 999\n")
    git("commit", "-am", "independent main change")
    git("checkout", "product")
    admit()
    prompts = getattr(runner, function)(branch="product")["prompts"]
    for role in ("user_experience", "maintainer"):
        prompt = prompts[role]["prompt"]
        assert "git show <default-branch>:<file>" not in prompt
        assert f"git show {stack['main']}:" in prompt


@pytest.mark.parametrize("publication", ["before-mode", "after-mode"])
def test_explicit_preparation_replays_after_process_restart(stack, monkeypatch, publication):
    write = runner._write_json_file

    def interrupted(path, data):
        if path.name == "review-mode.json" and publication == "before-mode":
            raise OSError("injected interruption before mode publication")
        if path.name == "review-verdict-ledger.json" and publication == "after-mode":
            rounds = data.get("convergence", {}).get("rounds", [])
            if rounds and rounds[-1].get("prepared"):
                raise OSError("injected interruption after mode publication")
        return write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(runner, "_write_json_file", interrupted)
        result = runner.begin_review_run(branch="product", round_id="recover", base_ref="runtime")
        assert result["status"] == "error", result
    assert row()["prepared"] is False
    resumed = fresh("begin_review_run", branch="product", round_id="recover", base_ref="runtime")
    assert resumed["status"] == "success" and resumed["resumed"] is True
    assert row()["prepared"] is True
    assert len(json.loads(ledger_path().read_text())["convergence"]["rounds"]) == 1
    assert fresh("snapshot_code_state")["diff_base"] == stack["runtime"][:12]


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("flag", ["--base-ref runtime", "--base-ref=runtime", "--base-ref", "--base-ref=",
                                  "--base-ref runtime --base-ref main", "--base-ref runtime --base-ref runtime"])
def test_rendered_skill_admission_extracts_base_without_parsing_free_prose(provider, flag, monkeypatch):
    relative = "skills/map-review/SKILL.md" if provider == "claude" else "codex/skills/map-review/SKILL.md"
    text = (ROOT / "src/mapify_cli/templates" / relative).read_text()
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", text, flags=re.DOTALL)
    blocks = [block for block in blocks if '"begin_review_run"' in block]
    assert len(blocks) == 1, "Expected one executable admission heredoc"
    prose = f"review user's path, don't change wording {flag}"
    calls = []

    def capture(argv, **kwargs):
        del kwargs
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, '{"status":"success"}', "")

    monkeypatch.setattr(sys, "argv", ["-", "{}", "full", prose, "", "{}"])
    monkeypatch.setattr(subprocess, "run", capture)
    invalid = flag not in {"--base-ref runtime", "--base-ref=runtime"}
    try:
        exec(compile(blocks[0], f"{provider}-admission", "exec"), {})  # noqa: S102 -- execute owned rendered fixture
    except (ValueError, SystemExit):
        assert invalid and not calls, "Reject malformed flags before invoking admission"
        return
    assert not invalid, "Malformed/repeated base flags were not rejected"
    assert len(calls) == 1
    argv = calls[0]
    assert "--base-ref" in argv or "--base-ref=runtime" in argv, argv
    if "--base-ref" in argv:
        assert argv[argv.index("--base-ref") + 1] == "runtime"
    assert "--arguments=" + prose in argv


def test_explicit_execution_check_and_gate_keep_row_provenance(stack):
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    command = [sys.executable, "-I", "-c", "print('check witnessed')"]
    admission = admit(base_ref="runtime", scheduled_reviewers=["monitor"], provider="claude",
                      required_checks=["suite"], check_specs={"suite": command},
                      check_timeouts={"suite": 10})
    assert admission["capability"]["status"] == "verified", admission
    assert runner.create_review_bundle(branch="product")["status"] == "success"
    result = fresh("run_test_gate", check_id="suite", branch="product")
    assert result["passed"] is True, result
    assert result["before"] == result["after"] == admission["target"]
    assert result["after"]["base"] == stack["runtime"]
    envelope = {"issues": [], "receipt": {"covered_files": admission["required_files"],
                "skipped_files": [], "denied_access": [], "check_evidence": []}}
    runner.capture_review_output("monitor", json.dumps(envelope), "stack", branch="product")
    finalized = runner.write_review_verdict_ledger(current_run=True, branch="product")
    assert finalized["findings_verdict"] == "PROCEED", finalized
    gate = cli("write_stage_gate", "review", "ready", "review.md", "stack")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert json.loads(gate.stdout)["status"] == "success"
    git("branch", "-D", "runtime")
    rejected = cli("write_stage_gate", "review", "ready", "review.md", "stack")
    assert rejected.returncode != 0 or json.loads(rejected.stdout)["status"] == "error"


def test_explicit_target_diff_digest_is_runtime_not_policy_base(stack):
    del stack
    admitted = admit(base_ref="runtime")
    expected = subprocess.run(
        ["git", "diff", "--binary", "runtime", "--", "."],
        check=True, capture_output=True, timeout=15,
    ).stdout
    assert admitted["target"]["diff_digest"] == hashlib.sha256(expected).hexdigest()
