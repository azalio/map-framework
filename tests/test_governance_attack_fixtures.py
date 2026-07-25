"""
Adversarial governance violation fixtures — issue #350.

Each test demonstrates that a specific MAP Framework enforcement surface
REJECTS a concrete violation scenario.  The matrix spans six distinct
enforcing surfaces so no single surface is the sole gatekeeper.

Surfaces covered
----------------
1. Orchestrator state machine  — mark_workflow_complete with pending steps
2. Mutation-boundary gate      — validate_step("2.4") strict-mode scope leak
3. False-progress gate         — validate_step("2.4") no affected_files changed
4. Wave lifecycle              — verify_group_clean with an open group
5. Safety-guardrails hook      — autonomy-mode git commit blocked
6. Workflow-gate hook          — Edit during DECOMPOSE phase blocked
7. Run-health schema           — validate_run_health_report rejects missing fields

Run: uv run pytest tests/test_governance_attack_fixtures.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared import paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

ORCHESTRATOR_PATH = (
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"
)
SCRIPTS_PATH = ORCHESTRATOR_PATH  # same dir; alias for clarity

sys.path.insert(0, str(ORCHESTRATOR_PATH))

import map_orchestrator  # pyright: ignore[reportMissingImports]
import map_step_runner  # pyright: ignore[reportMissingImports]

WORKFLOW_GATE_HOOK = REPO_ROOT / ".claude" / "hooks" / "workflow-gate.py"
SAFETY_HOOK = REPO_ROOT / ".claude" / "hooks" / "safety-guardrails.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(stdout: str) -> dict[str, Any]:
    txt = (stdout or "").strip()
    return json.loads(txt) if txt else {}


def _assert_hook_denied(stdout: str) -> str:
    payload = _parse(stdout)
    hso = payload.get("hookSpecificOutput", {})
    assert hso.get("permissionDecision") == "deny", f"expected deny, got: {payload}"
    reason = hso.get("permissionDecisionReason", "")
    assert reason, "deny must include a reason"
    return reason


def _run_workflow_gate(input_data: dict, cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(WORKFLOW_GATE_HOOK)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _run_safety_hook(input_data: dict, env: dict | None = None) -> tuple[int, str, str]:
    import os

    result = subprocess.run(
        [sys.executable, str(SAFETY_HOOK)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _init_git(tmp_path: Path, branch: str = "main") -> None:
    """Create a minimal git repo with an initial commit."""
    for cmd in [
        ["git", "init", "-b", branch],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
    ]:
        subprocess.run(cmd, cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )


def _init_git_compat(tmp_path: Path) -> None:
    """Create a minimal git repo, compatible with older git that lacks -b."""
    subprocess.run(
        ["git", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    (tmp_path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "seed.txt"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
    )


def _write_step_state(tmp_path: Path, branch: str, state: map_orchestrator.StepState) -> Path:
    state_file = tmp_path / ".map" / branch / "step_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state.save(state_file)
    return state_file


# ---------------------------------------------------------------------------
# Surface 1 — Orchestrator state machine
# ---------------------------------------------------------------------------


class TestAttackWorkflowCompleteWithPendingSteps:
    """VIOLATION: completing a workflow while steps are still pending must fail."""

    def test_mark_complete_rejected_when_pending_steps_remain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-branch"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)

        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.pending_steps = ["2.3", "2.4"]  # two steps still open
        state.current_step_id = "2.2"
        _write_step_state(tmp_path, branch, state)

        result = map_orchestrator.mark_workflow_complete(branch)

        assert result["status"] == "error", f"expected error, got: {result}"
        assert "pending" in result.get("message", "").lower(), result

    def test_mark_complete_rejected_when_single_pending_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-branch-2"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)

        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.pending_steps = ["2.4"]  # exactly one pending
        _write_step_state(tmp_path, branch, state)

        result = map_orchestrator.mark_workflow_complete(branch)

        assert result["status"] == "error", result
        # Confirm it is NOT incorrectly completing the workflow.
        import json as _json

        reloaded_raw = (tmp_path / ".map" / branch / "step_state.json").read_text()
        reloaded = _json.loads(reloaded_raw)
        assert reloaded.get("workflow_status") != "WORKFLOW_COMPLETE", reloaded


# ---------------------------------------------------------------------------
# Surface 2 — Mutation-boundary gate (strict mode)
# ---------------------------------------------------------------------------


class TestAttackMutationBoundaryStrictMode:
    """VIOLATION: Actor writes a file outside affected_files with MAP_STRICT_SCOPE=1."""

    def test_strict_scope_rejects_out_of_scope_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-mutation"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)

        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        _write_step_state(tmp_path, branch, state)

        # Blueprint declares only a.py as the expected mutation target.
        (map_dir / "blueprint.json").write_text(
            json.dumps({
                "subtasks": [
                    {"id": "ST-001", "title": "fix", "affected_files": ["a.py"]}
                ]
            })
        )

        _init_git_compat(tmp_path)
        # Actor wrote leak.py — NOT in affected_files.
        (tmp_path / "leak.py").write_text("# oops\n")
        subprocess.run(["git", "add", "leak.py"], cwd=tmp_path, capture_output=True, check=False)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")

        result = map_orchestrator.validate_step(
            "2.4", branch, recommendation="proceed"
        )

        assert result["valid"] is False, f"expected valid=False, got: {result}"
        assert "Mutation-boundary violation" in result.get("message", ""), result

    def test_strict_scope_accepts_in_scope_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: in-scope edit following the documented commit→record→validate sequence
        must NOT be blocked even in strict mode.

        Documented order (#162): commit → record_subtask_result --commit-sha → validate_step 2.4
        """
        branch = "atk-mutation-ok"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)

        (map_dir / "blueprint.json").write_text(
            json.dumps({
                "subtasks": [
                    {"id": "ST-001", "title": "fix", "affected_files": ["a.py"]}
                ]
            })
        )

        _init_git_compat(tmp_path)
        # Write a.py — the declared affected file — then commit.
        (tmp_path / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "ST-001: add a.py"],
            cwd=tmp_path, capture_output=True, check=True
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Mimic `record_subtask_result --commit-sha <SHA>` (the documented middle step).
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        state.record_subtask_result("ST-001", ["a.py"], "valid", commit_sha=sha)
        _write_step_state(tmp_path, branch, state)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")

        result = map_orchestrator.validate_step(
            "2.4", branch, recommendation="proceed"
        )

        assert result.get("valid") is True, f"expected valid=True, got: {result}"


# ---------------------------------------------------------------------------
# Surface 3 — False-progress gate
# ---------------------------------------------------------------------------


class TestAttackFalseProgressGate:
    """VIOLATION: MONITOR tries to advance a subtask that changed nothing."""

    def test_false_progress_blocks_when_no_files_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-false-progress"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)

        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        _write_step_state(tmp_path, branch, state)

        # Blueprint expects a.py to be modified.
        (map_dir / "blueprint.json").write_text(
            json.dumps({
                "subtasks": [
                    {"id": "ST-001", "title": "add a.py", "affected_files": ["a.py"]}
                ]
            })
        )

        _init_git_compat(tmp_path)
        # Actor never created a.py — false progress.

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)

        result = map_orchestrator.validate_step(
            "2.4", branch, recommendation="proceed"
        )

        assert result["valid"] is False, f"expected False-progress rejection, got: {result}"
        assert "False-progress" in result.get("message", ""), result


# ---------------------------------------------------------------------------
# Surface 4 — Wave lifecycle (verify_group_clean)
# ---------------------------------------------------------------------------


class TestAttackWaveGroupNotClosed:
    """VIOLATION: verify_group_clean returns clean=False when groups are open."""

    def test_open_group_blocks_next_wave(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-wave"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)

        _init_git_compat(tmp_path)

        # begin_wave_group opens a group in the worktree sidecar.
        result = map_step_runner.begin_wave_group(["ST-001", "ST-002"], branch=branch)
        assert result.get("ok") is True, f"begin_wave_group failed: {result}"

        # Without merge/close, verify_group_clean must report not-clean.
        verdict = map_step_runner.verify_group_clean(branch=branch)

        assert verdict["clean"] is False, f"expected clean=False, got: {verdict}"
        assert verdict.get("reason") is not None

    def test_clean_after_no_groups(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: clean repo with no groups should be clean."""
        branch = "atk-wave-ok"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)

        _init_git_compat(tmp_path)

        verdict = map_step_runner.verify_group_clean(branch=branch)
        assert verdict["clean"] is True, f"expected clean=True, got: {verdict}"


# ---------------------------------------------------------------------------
# Surface 5 — Safety-guardrails hook (autonomy-mode git commit blocked)
# ---------------------------------------------------------------------------


class TestAttackAutonomyModeGitCommit:
    """VIOLATION: git commit during autonomy mode must be denied."""

    def _write_autonomy_settings(self, project_dir: Path, enabled: bool) -> None:
        settings = project_dir / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "permissions": {"allow": ["Bash(*)"], "deny": ["Bash(git commit:*)"]}
        }
        if enabled:
            payload["mapify"] = {"autonomy": True}
        settings.write_text(json.dumps(payload))

    def test_git_commit_denied_in_autonomy_mode(self, tmp_path: Path) -> None:
        self._write_autonomy_settings(tmp_path, enabled=True)
        input_data = {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'sneaky'"}}
        _, stdout, _ = _run_safety_hook(input_data, env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
        _assert_hook_denied(stdout)

    def test_git_commit_allowed_without_autonomy(self, tmp_path: Path) -> None:
        """Control: git commit is NOT blocked when autonomy is off."""
        self._write_autonomy_settings(tmp_path, enabled=False)
        input_data = {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'normal'"}}
        _, stdout, _ = _run_safety_hook(input_data, env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
        parsed = _parse(stdout)
        # Allowed = empty JSON or no deny decision.
        deny = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
        assert deny != "deny", f"unexpected deny without autonomy: {parsed}"

    def test_env_file_always_blocked_regardless_of_autonomy(self, tmp_path: Path) -> None:
        """Control: secret file blocking is independent of autonomy mode."""
        self._write_autonomy_settings(tmp_path, enabled=False)
        input_data = {"tool_name": "Read", "tool_input": {"file_path": ".env"}}
        _, stdout, _ = _run_safety_hook(input_data, env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
        _assert_hook_denied(stdout)


# ---------------------------------------------------------------------------
# Surface 6 — Workflow-gate hook (Edit during non-editing phase blocked)
# ---------------------------------------------------------------------------


class TestAttackWorkflowGateDuringDecompose:
    """VIOLATION: Edit/Write during DECOMPOSE phase must be denied."""

    def _setup_step_state(self, tmp_path: Path, phase: str, branch: str = "main") -> None:
        """Write a minimal step_state.json for the workflow-gate hook to read."""
        # workflow-gate reads from <CWD>/.map/<branch>/step_state.json
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True)
        state = {
            "current_step_phase": phase,
            "current_step_id": "1.0",
            "workflow_status": "IN_PROGRESS",
        }
        (state_dir / "step_state.json").write_text(json.dumps(state))

    def _make_git_repo(self, tmp_path: Path, branch: str = "main") -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        (tmp_path / "README.md").write_text("x\n")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True
        )
        # Rename default branch if needed.
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=tmp_path, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if current != branch:
            subprocess.run(
                ["git", "checkout", "-b", branch],
                cwd=tmp_path, capture_output=True,
                check=False,
            )

    def test_edit_denied_during_decompose(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        self._setup_step_state(tmp_path, "DECOMPOSE")
        input_data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/foo.py", "old_string": "x", "new_string": "y"},
        }
        _, stdout, _ = _run_workflow_gate(input_data, cwd=tmp_path)
        _assert_hook_denied(stdout)

    def test_write_denied_during_predictor(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        self._setup_step_state(tmp_path, "PREDICTOR")
        input_data = {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/new.py", "content": "x = 1"},
        }
        _, stdout, _ = _run_workflow_gate(input_data, cwd=tmp_path)
        _assert_hook_denied(stdout)

    def test_edit_allowed_during_actor(self, tmp_path: Path) -> None:
        """Control: Edit IS allowed during the ACTOR phase."""
        self._make_git_repo(tmp_path)
        self._setup_step_state(tmp_path, "ACTOR")
        input_data = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/foo.py", "old_string": "x", "new_string": "y"},
        }
        _, stdout, _ = _run_workflow_gate(input_data, cwd=tmp_path)
        parsed = _parse(stdout)
        deny = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
        assert deny != "deny", f"ACTOR edit should be allowed, got: {parsed}"


# ---------------------------------------------------------------------------
# Surface 7 — Run-health schema validation
# ---------------------------------------------------------------------------


class TestAttackRunHealthReportSchema:
    """VIOLATION: run_health_report.json with missing required fields is rejected."""

    def test_missing_terminal_status_is_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-health"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)

        # Intentionally omit 'terminal_status'.
        incomplete_report: dict[str, object] = {
            "workflow_id": "wf-001",
            "resiliency_signals": {},
        }
        report_path = branch_dir / "run_health_report.json"
        report_path.write_text(json.dumps(incomplete_report))

        result = map_step_runner.validate_run_health_report(
            report_path=str(report_path), branch=branch
        )

        assert result.get("valid") is False, f"expected invalid, got: {result}"
        errors = result.get("errors", [])
        assert errors, f"expected validation errors, got none: {result}"

    def test_missing_report_file_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-health-missing"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        # No report file written at all.

        result = map_step_runner.validate_run_health_report(branch=branch)

        assert result.get("valid") is False, result
        assert result.get("status") == "error", result

    def test_non_dict_report_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        branch = "atk-health-bad"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)

        report_path = branch_dir / "run_health_report.json"
        report_path.write_text(json.dumps(["not", "a", "dict"]))

        result = map_step_runner.validate_run_health_report(
            report_path=str(report_path), branch=branch
        )

        assert result.get("valid") is False, result
        assert result.get("status") == "error", result
