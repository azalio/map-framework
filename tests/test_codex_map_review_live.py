"""Live Codex install checks for the shared map-review skill.

Installs Codex in-process (no `uv run mapify` subprocess: a second clone's
editable install could otherwise answer instead of this worktree), then drives
the INSTALLED hook and the rendered envelope -> ledger -> gate shell blocks.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from tests.review_process_lifecycle import ReviewProcessLifecycle

REPO_ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feat/x"
BRANCH_DIR_NAME = "feat-x"
REVIEW_FILES = ("SKILL.md", "review-reference.md", "adversarial-reference.md")


def test_concurrent_review_admission_counts_once_and_fences_stale_capture(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    script = REPO_ROOT / "src/mapify_cli/templates/map/scripts/map_step_runner.py"
    command = ["python3", str(script), "begin_review_run", "--mode", "lightweight", "--branch", "test"]
    processes = [subprocess.Popen(command, cwd=tmp_path, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) for _ in range(3)]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout))
    assert {item["round_id"] for item in outputs} == {"round-1"}
    ledger = json.loads((tmp_path / ".map/test/review-verdict-ledger.json").read_text())
    assert len(ledger["convergence"]["rounds"]) == 1
    rejected = subprocess.run(
        ["python3", str(script), "capture_review_output", "--reviewer", "monitor", "--round-id", "stale", "--branch", "test"],
        input='{"issues":[]}', cwd=tmp_path, text=True, capture_output=True, check=False,
    )
    assert rejected.returncode == 1
    assert not (tmp_path / ".map/test/review-agent-monitor.json").exists()


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_review_round_cli_restart_cap_and_rejected_admission_preserve_inputs(tmp_path, provider):
    """Count explicit abandonment across CLI restarts without losing captures."""
    project_dir = tmp_path / provider
    project_dir.mkdir()
    previous_cwd = os.getcwd()
    os.chdir(project_dir)
    try:
        installed = CliRunner().invoke(app, ["init", ".", "--provider", provider, "--no-git", "--force"])
    finally:
        os.chdir(previous_cwd)
    assert installed.exit_code == 0, installed.output
    _git(project_dir, "init", "-b", "main")
    script = project_dir / ".map/scripts/map_step_runner.py"

    def call(*args):
        result = subprocess.run(
            ["python3", str(script), *args, "--branch", "test"], cwd=project_dir,
            text=True, capture_output=True, check=False,
        )
        return result.returncode, json.loads(result.stdout)

    workspace = project_dir / ".map/test"
    capture = workspace / "review-agent-monitor.json"
    for number in range(1, 4):
        code, admitted = call("begin_review_run", "--mode", "lightweight", "--round-id", str(number))
        assert code == 0, admitted
        payload = {"issues": [{"severity": "CRITICAL", "category": "correctness", "description": "loss",
                               "reach_evidence": "reproducer", "was_present_before_pr": False}]}
        capture = workspace / "review-agent-monitor.json"
        capture.write_text(json.dumps(payload))
        code, retry = call("begin_review_run", "--mode", "lightweight", "--round-id", str(number))
        assert code == 0 and retry["resumed"]
        code, completed = call("write_review_verdict_ledger", "--current-run", "--round-id", str(number))
        assert code == 0, completed
        assert completed["convergence"]["completed_rounds"] == 0
        assert completed["convergence"]["attempted_rounds"] == number - 1
        assert completed["code_approval"]["approved"] is False
        code, abandoned = call("abandon_review_round", str(number), "--reason", "Explicitly cancel incomplete collection")
        assert code == 0 and abandoned["convergence"]["attempted_rounds"] == number
    before = capture.read_bytes()
    code, rejected = call("begin_review_run", "--mode", "lightweight", "--round-id", "4")
    assert code == 1 and rejected["stop_reason"] == "reconsider_approach"
    assert capture.read_bytes() == before
    assert json.loads((workspace / "review-verdict-ledger.json").read_text())["convergence"]["outcome"] == "capped"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def codex_install(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("codex_live")
    previous_cwd = os.getcwd()
    os.chdir(root)
    try:
        result = CliRunner().invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
    finally:
        os.chdir(previous_cwd)
    assert result.exit_code == 0, result.output
    _git(root, "init")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    _git(root, "checkout", "-b", BRANCH)
    return root


@pytest.fixture()
def project(codex_install, tmp_path):
    """Fresh install whose detached check owners must finish before teardown."""
    dest = tmp_path / "proj"
    shutil.copytree(codex_install, dest, symlinks=True)
    with ReviewProcessLifecycle(dest):
        yield dest


def _bash_blocks(text: str, heading: str) -> list[str]:
    """Return the ```bash blocks under the first heading starting with `heading`."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(heading))
    blocks: list[str] = []
    current: list[str] | None = None
    for line in lines[start + 1 :]:
        if current is None:
            if re.match(r"^#{1,3} ", line):
                break
            if line.strip() == "```bash":
                current = []
        elif line.strip() == "```":
            blocks.append("\n".join(current))
            current = None
        else:
            current.append(line)
    return blocks


def _skill_text(root: Path) -> str:
    return (root / ".agents/skills/map-review/SKILL.md").read_text(encoding="utf-8")


def _load_hook(root: Path):
    spec = importlib.util.spec_from_file_location(
        "installed_codex_workflow_gate", root / ".codex/hooks/workflow-gate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_call(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _write_state(root: Path, **state: str) -> None:
    path = root / ".map" / BRANCH_DIR_NAME / "step_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "current_subtask_id": "ST-001",
        "current_step_id": "2.3",
        "subtask_phases": {},
        "workflow_status": "IN_PROGRESS",
        **state,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_hook(root: Path, tool_call: dict) -> str:
    env = {k: v for k, v in os.environ.items() if k != "MAP_MONITOR_HOTFIX"}
    env["CLAUDE_PROJECT_DIR"] = str(root)
    proc = subprocess.run(
        ["python3", str(root / ".codex/hooks/workflow-gate.py")],
        input=json.dumps(tool_call),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0 and proc.stderr == "", (proc.returncode, proc.stderr)
    decision = json.loads(proc.stdout or "{}")
    return decision.get("hookSpecificOutput", {}).get("permissionDecision", "allow")


def _selected_blocks(root: Path, hook) -> list[str]:
    selected: list[str] = []
    for name in REVIEW_FILES:
        text = (root / ".agents/skills/map-review" / name).read_text(encoding="utf-8")
        for block in re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL):
            paths = hook.extract_target_file_paths(_bash_call(block))
            if hook.has_unresolved_shell_target(paths):
                selected.append(block)
    return selected


def test_shell_expansion_blocks_allowed_in_supported_states(project):
    hook = _load_hook(project)
    blocks = _selected_blocks(project, hook)
    assert blocks, "no map-review block has a shell-expanded write target (vacuous)"

    state_dir = project / ".map" / BRANCH_DIR_NAME
    supported = {
        "none": None,
        "WORKFLOW_COMPLETE": {
            "workflow_status": "WORKFLOW_COMPLETE",
            "current_step_phase": "COMPLETE",
        },
        "MONITOR": {"current_step_phase": "MONITOR"},
    }
    for label, state in supported.items():
        (state_dir / "step_state.json").unlink(missing_ok=True)
        if state is not None:
            _write_state(project, **state)
        for block in blocks:
            assert _run_hook(project, _bash_call(block)) == "allow", (
                label,
                block[:80],
            )

    # Documented limitation: outside the supported states the hook cannot
    # resolve `$VAR` targets and denies. Invert this when the #488 hook
    # follow-up lands.
    _write_state(project, current_step_phase="DECOMPOSE")
    for block in blocks:
        assert _run_hook(project, _bash_call(block)) == "deny", block[:80]


MONITOR_CLEAN = {"verdict": "approved", "issues": []}
MONITOR_FINDING = {
    "verdict": "needs_revision",
    "issues": [
        {
            "severity": "HIGH",
            "category": "performance",
            "description": "N+1 query on hot path",
            "was_present_before_pr": False,
            "reach_evidence": "Hits DB on every page load",
        }
    ],
}
PREDICTOR_LOW_RISK = {
    "risk_assessment": "low",
    "evidence": [{"source": "test_coverage", "quote": "100% coverage"}],
    "predicted_state": {"breaking_changes": []},
}
EVALUATOR_HIGH = {
    "overall_score": 9,
    "recommendation": "proceed",
    "scores": {"correctness": 9, "clarity": 8},
}


def _role_clear(role: str) -> dict:
    return {
        "reviewer": role,
        "all_clear": True,
        "all_clear_rationale": "old path unchanged; no new mandatory flag",
        "findings": [],
        "checks_performed": ["old path", "flag names"],
        "receipt": {
            "covered_files": [],
            "skipped_files": [],
            "denied_access": [],
            "check_evidence": [],
        },
    }


# case id -> (role -> envelope, expected ledger verdict, expected gate verdict)
ROSTERS = {
    "PROCEED": ({"monitor": MONITOR_CLEAN}, "REVISE", "needs-revision"),
    "REVISE": ({"monitor": MONITOR_FINDING}, "REVISE", "needs-revision"),
    "full_roster_PROCEED": (
        {
            "monitor": MONITOR_CLEAN,
            "predictor": PREDICTOR_LOW_RISK,
            "evaluator": EVALUATOR_HIGH,
            "user_experience": _role_clear("user_experience"),
            "maintainer": _role_clear("maintainer"),
        },
        "REVISE",
        "needs-revision",
    ),
    "partial_roster_REVISE": (
        {
            "monitor": MONITOR_CLEAN,
            "user_experience": _role_clear("user_experience"),
        },
        "REVISE",
        "needs-revision",
    ),
}


def _capture_script(capture: str, envelopes: dict[str, dict]) -> str:
    """Expand the rendered A.2c block: one heredoc per role, same form as the prose."""
    lines = capture.splitlines()
    first_capture = next(i for i, ln in enumerate(lines) if " capture_review_output " in ln)
    header = "\n".join(lines[:first_capture])
    template = "\n".join(lines[first_capture:])
    placeholder = "<paste the Monitor JSON envelope verbatim>"
    assert placeholder in template
    parts = [header]
    for role, envelope in envelopes.items():
        parts.append(
            template.replace("monitor", role)
            .replace("MONITOR_EOF", f"{role.upper()}_EOF")
            .replace(placeholder, json.dumps(envelope))
        )
    return "\n".join(parts)


def _run_block(root: Path, script: str) -> str:
    proc = ReviewProcessLifecycle(root / ".map").run(["bash", "-c", script], cwd=root)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert '"status": "error"' not in proc.stdout + proc.stderr, proc.stdout
    return proc.stdout


@pytest.mark.parametrize("case", list(ROSTERS))
def test_envelope_ledger_gate_fresh_shell(project, case):
    envelopes, expected_ledger, expected_gate = ROSTERS[case]
    text = _skill_text(project)

    capture = _bash_blocks(text, "### Step A.2c")[0]
    ledger = _bash_blocks(text, "## Write Review Verdict Ledger")[0]
    gate = _bash_blocks(text, "## Handoff Artifact Update")[0]

    # Each rendered block runs in its own fresh shell, in order.
    _start_review(project, "", lightweight=case in {"PROCEED", "REVISE"})
    _run_block(project, _capture_script(capture, envelopes))
    branch_dir = project / ".map" / BRANCH_DIR_NAME
    for role in envelopes:
        assert (branch_dir / f"review-agent-{role}.json").is_file(), role
    _run_block(project, ledger)
    _run_block(project, gate)

    ledger_doc = json.loads((branch_dir / "review-verdict-ledger.json").read_text())
    computed = ledger_doc["computed_verdict"]
    gate_verdict = json.loads((branch_dir / "review-gate.json").read_text())["verdict"]
    assert computed == expected_ledger
    assert gate_verdict == expected_gate
    # Clean findings cannot approve a Codex review with unverified capabilities.
    assert ledger_doc["completeness"]["status"] == "INCOMPLETE"
    assert ledger_doc["code_approval"]["approved"] is False
    if case in {"PROCEED", "full_roster_PROCEED"}:
        assert ledger_doc["findings_verdict"] == "PROCEED"
    if "evaluator" in envelopes:
        # Only an ingested Evaluator envelope populates evaluator_scores, so this
        # proves the rendered ledger loop passed --evaluator-file through.
        assert _find_key(ledger_doc, "evaluator_scores") == envelopes["evaluator"]


def _adversarial_report(root: Path, findings: list[dict]) -> dict:
    branch_dir = root / ".map" / BRANCH_DIR_NAME
    clean = {"all_clear": True, "findings": [], "checks_performed": ["changed paths"],
             "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}}
    roles = ("blind", "edge_case", "acceptance", "user_experience", "maintainer")
    flags = []
    for role in roles:
        payload = {**clean, "all_clear": False, "findings": findings} if role == "blind" and findings else clean
        path = branch_dir / f"adversarial-{role}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        flags.extend([f"--{role.replace('_', '-')}", str(path)])
    output = _run_block(root, shlex.join([
        "python3", ".map/scripts/map_step_runner.py", "aggregate_adversarial_findings", *flags,
    ]))
    return json.loads(output)


def _start_review(root: Path, arguments: str, *, lightweight: bool = False) -> None:
    branch_dir = root / ".map" / BRANCH_DIR_NAME
    branch_dir.mkdir(parents=True, exist_ok=True)
    (branch_dir / "review-bundle.md").write_text(
        "MISSING\n" if lightweight else "## Review bundle\nChanged paths and requirements\n",
        encoding="utf-8",
    )
    text = _skill_text(root)
    blocks = [
        _bash_blocks(text, "## Step 0")[0],
        _bash_blocks(text, "### Step A.0b")[0],
    ]
    for block in re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL):
        if re.search(r"map_step_runner\.py begin_review_run\b", block) and block not in blocks:
            blocks.append(block)
    check_specs = json.dumps({
        "tests": ["python3", "-c", "print('fixture test check')"],
        "lint": ["python3", "-c", "print('fixture lint check')"],
    })
    _run_block(root, f"ARGUMENTS={shlex.quote(arguments)}\n"
               f"CHECK_SPECS_JSON={shlex.quote(check_specs)}\n"
               "CHECK_TIMEOUTS_JSON='{\"tests\": 5, \"lint\": 5}'\n" + "\n".join(blocks))


def _abandon_incomplete_review(root: Path) -> None:
    """Explicitly end an unverified Codex collection before changing its inputs."""
    run = json.loads((root / ".map" / BRANCH_DIR_NAME / "review-mode.json").read_text())
    _run_block(root, shlex.join([
        "python3", ".map/scripts/map_step_runner.py", "abandon_review_round", run["round_id"],
        "--reason", "Continue findings review in a new attempt",
    ]))


def test_rendered_resume_keeps_lightweight_mode_after_bundle_creation(project):
    """A real bundle must not change the inferred mode of a pending admission."""
    _start_review(project, "", lightweight=True)
    directory = project / ".map" / BRANCH_DIR_NAME
    before = json.loads((directory / "review-mode.json").read_text())
    _run_block(project, "python3 .map/scripts/map_step_runner.py create_review_bundle")
    bundle = (directory / "review-bundle.md").read_bytes()
    assert b"##" in bundle
    capture = _bash_blocks(_skill_text(project), "### Step A.2c")[0]
    _run_block(project, _capture_script(capture, {"monitor": MONITOR_CLEAN}))
    captured = (directory / "review-agent-monitor.json").read_bytes()
    _run_block(project, _bash_blocks(_skill_text(project), "## Write Review Verdict Ledger")[0])
    detect = _bash_blocks(_skill_text(project), "### Step A.0b")[0]
    _run_block(project, "ARGUMENTS=''\n"
               f"CHECK_SPECS_JSON={shlex.quote(json.dumps(before['check_specs']))}\n"
               f"CHECK_TIMEOUTS_JSON={shlex.quote(json.dumps(before['check_timeouts']))}\n" + detect)
    assert json.loads((directory / "review-mode.json").read_text()) == before
    assert (directory / "review-agent-monitor.json").read_bytes() == captured
    assert (directory / "review-bundle.md").read_bytes() == bundle


@pytest.mark.parametrize(
    ("previous", "mode", "arguments", "current", "expected"),
    [
        ("blocked", "adversarial", "--adversarial", "minor", "BLOCK"),
        ("blocked", "compare_orderings", "--adversarial --compare-orderings", "minor", "BLOCK"),
        ("adversarial", "normal", "", "monitor", "BLOCK"),
        ("blocked", "normal", "", "peers", "BLOCK"),
    ],
    ids=["normal-to-adversarial", "compare-orderings", "adversarial-to-lightweight",
         "same-mode-missing-blocked-monitor"],
)
def test_current_review_closeout_does_not_consume_previous_run(
    project, previous, mode, arguments, current, expected,
):
    """Archive prior inputs while retaining unresolved findings across review modes."""
    branch_dir = project / ".map" / BRANCH_DIR_NAME
    capture = _bash_blocks(_skill_text(project), "### Step A.2c")[0]
    ledger_block = _bash_blocks(_skill_text(project), "## Write Review Verdict Ledger")[0]
    gate_block = _bash_blocks(_skill_text(project), "## Handoff Artifact Update")[0]
    blocked_monitor = {**MONITOR_FINDING, "issues": [
        {**MONITOR_FINDING["issues"][0], "category": "correctness"},
    ]}
    minor = [{"severity": "minor", "category": "tests", "claim": "Naming nit"}]
    _start_review(project, "", lightweight=True)
    _run_block(project, _capture_script(capture, {
        "monitor": blocked_monitor,
    }))
    _run_block(project, ledger_block)
    _run_block(project, gate_block)
    if previous == "adversarial":
        _abandon_incomplete_review(project)
        _start_review(project, "--adversarial")
        (branch_dir / "review-agent-adversarial.json").write_text(
            json.dumps(_adversarial_report(project, [{
                "severity": "critical", "category": "correctness", "claim": "Old bug",
            }])), encoding="utf-8",
        )
        _run_block(project, ledger_block)
        _run_block(project, gate_block)
    prior = json.loads((branch_dir / "review-verdict-ledger.json").read_text())["computed_verdict"]

    _abandon_incomplete_review(project)
    _start_review(project, arguments, lightweight=current == "monitor")
    if current == "minor":
        report = _adversarial_report(project, minor)
        directories = [branch_dir] if mode != "compare_orderings" else [
            branch_dir / "review-collections" / label for label in ("default", "reverse")
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "review-agent-adversarial.json").write_text(json.dumps(report), encoding="utf-8")
    else:
        envelopes = {"monitor": MONITOR_CLEAN} if current == "monitor" else {
            "predictor": PREDICTOR_LOW_RISK, "evaluator": EVALUATOR_HIGH,
            "user_experience": _role_clear("user_experience"), "maintainer": _role_clear("maintainer"),
        }
        _run_block(project, _capture_script(capture, envelopes))
    _run_block(project, ledger_block)
    _run_block(project, gate_block)

    ledger = json.loads((branch_dir / "review-verdict-ledger.json").read_text())
    assert ledger["computed_verdict"] == expected
    assert ledger["input_classification"]["review_mode"] == mode
    assert ledger["journal"]["previous_verdict"] == prior
    gate = json.loads((branch_dir / "review-gate.json").read_text())
    assert gate["verdict"] == {"PROCEED": "ready", "REVISE": "needs-revision", "BLOCK": "blocked"}[expected]


@pytest.mark.parametrize("content", [None, "", "{}", '{"unrelated":true}'],
                         ids=["missing", "empty", "empty-object", "unrelated-object"])
def test_missing_or_empty_scheduled_monitor_cannot_be_masked_by_clean_peers(project, content):
    _start_review(project, "")
    text = _skill_text(project)
    capture = _bash_blocks(text, "### Step A.2c")[0]
    peers = {role: envelope for role, envelope in ROSTERS["full_roster_PROCEED"][0].items()
             if role != "monitor"}
    _run_block(project, _capture_script(capture, peers))
    branch_dir = project / ".map" / BRANCH_DIR_NAME
    if content is not None:
        (branch_dir / "review-agent-monitor.json").write_text(content, encoding="utf-8")
    _run_block(project, _bash_blocks(text, "## Write Review Verdict Ledger")[0])
    ledger = json.loads((branch_dir / "review-verdict-ledger.json").read_text())
    assert ledger["computed_verdict"] == "REVISE"
    assert any("monitor" in row["claim"] for row in ledger["findings_registry"]
               if row["transition_reason"] == "input_integrity")


def test_quick_adversarial_capture_uses_persisted_roster_in_a_fresh_shell(project):
    _start_review(project, "--adversarial --quick")
    branch_dir = project / ".map" / BRANCH_DIR_NAME
    (branch_dir / "adversarial-edge.json").write_text("stale edge", encoding="utf-8")
    reference = (project / ".agents/skills/map-review/adversarial-reference.md").read_text()
    capture = _bash_blocks(reference, "## Step B.adversarial.3")[0]
    clean = json.dumps({"all_clear": True, "findings": [], "checks_performed": ["diff"],
                        "receipt": {"covered_files": [], "skipped_files": [], "denied_access": [], "check_evidence": []}})
    capture = re.sub(r"<paste [^>]*JSON[^>]*>", clean, capture)
    _run_block(project, capture)
    assert not (branch_dir / "adversarial-edge.json").exists()
    for role in ("blind", "acceptance", "user-experience", "maintainer"):
        raw = json.loads((branch_dir / f"adversarial-{role}.json").read_text())
        assert raw["all_clear"] is True
        assert raw["findings"] == []
    mode = json.loads((branch_dir / "review-mode.json").read_text())
    assert mode["review_mode"] == "adversarial"
    assert mode["scheduled_reviewers"] == ["blind", "acceptance", "user_experience", "maintainer"]


def test_current_run_closeout_without_mode_fails_loudly(project):
    text = _skill_text(project)
    proc = subprocess.run(
        ["bash", "-c", _bash_blocks(text, "## Write Review Verdict Ledger")[0]],
        cwd=project, capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0
    assert "review-mode.json" in proc.stderr + proc.stdout
    assert not (project / ".map" / BRANCH_DIR_NAME / "review-verdict-ledger.json").exists()


def _find_key(node: object, key: str) -> object:
    """Return the first value stored under ``key`` anywhere in a JSON tree."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None
