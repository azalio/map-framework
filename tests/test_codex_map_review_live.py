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
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
BRANCH = "feat/x"
BRANCH_DIR_NAME = "feat-x"
REVIEW_FILES = ("SKILL.md", "review-reference.md", "adversarial-reference.md")


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
def project(codex_install, tmp_path) -> Path:
    """Fresh copy of the install so ledger/gate artifacts never leak between tests."""
    dest = tmp_path / "proj"
    shutil.copytree(codex_install, dest, symlinks=True)
    return dest


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


def test_vc1_shell_expansion_blocks_allowed_in_supported_states(project):
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
    }


# case id -> (role -> envelope, expected ledger verdict, expected gate verdict)
ROSTERS = {
    "PROCEED": ({"monitor": MONITOR_CLEAN}, "PROCEED", "ready"),
    "REVISE": ({"monitor": MONITOR_FINDING}, "REVISE", "needs-revision"),
    "full_roster_PROCEED": (
        {
            "monitor": MONITOR_CLEAN,
            "predictor": PREDICTOR_LOW_RISK,
            "evaluator": EVALUATOR_HIGH,
            "user_experience": _role_clear("user_experience"),
            "maintainer": _role_clear("maintainer"),
        },
        "PROCEED",
        "ready",
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
    first_cat = next(i for i, ln in enumerate(lines) if ln.startswith("cat > "))
    header = "\n".join(lines[:first_cat])
    template = "\n".join(lines[first_cat:])
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
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert '"status": "error"' not in proc.stdout + proc.stderr, proc.stdout
    return proc.stdout


@pytest.mark.parametrize("case", list(ROSTERS))
def test_vc2_envelope_ledger_gate_fresh_shell(project, case):
    envelopes, expected_ledger, expected_gate = ROSTERS[case]
    text = _skill_text(project)

    capture = _bash_blocks(text, "### Step A.2c")[0]
    ledger = _bash_blocks(text, "## Write Review Verdict Ledger")[0]
    gate = _bash_blocks(text, "## Handoff Artifact Update")[0]

    # Each rendered block runs in its own fresh shell, in order.
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
    if "evaluator" in envelopes:
        # Only an ingested Evaluator envelope populates evaluator_scores, so this
        # proves the rendered ledger loop passed --evaluator-file through.
        assert _find_key(ledger_doc, "evaluator_scores") == envelopes["evaluator"]


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
