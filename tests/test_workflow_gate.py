"""
Tests for workflow-gate.py hook.

Run with: pytest tests/test_workflow_gate.py -v

This hook enforces MAP Framework workflow adherence by blocking Edit/Write/MultiEdit
outside of Actor-related phases. Uses step_state.json as source of truth.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Tuple

import pytest

REPO_ROOT = Path(__file__).parent.parent


class TestWorkflowGate:
    """Tests for workflow-gate.py PreToolUse hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/workflow-gate.py"

    def _parse_stdout(self, stdout: str) -> dict:
        stdout = (stdout or "").strip()
        if not stdout:
            return {}
        return json.loads(stdout)

    def _assert_allowed(self, stdout: str) -> None:
        assert self._parse_stdout(stdout) == {}

    def _assert_denied(self, stdout: str) -> str:
        payload = self._parse_stdout(stdout)
        assert (
            payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
        )
        assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
        reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
        assert reason
        return reason

    def run_hook(
        self, input_data: dict, tmp_path: Path, branch: str = "master"
    ) -> Tuple[int, str, str]:
        """Run workflow-gate.py hook with given input."""
        git_dir = tmp_path / ".git"
        if not git_dir.exists():
            subprocess.run(
                ["git", "init"], cwd=tmp_path, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            (tmp_path / "README.md").write_text("test\n")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )

        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if current_branch != branch:
            branch_exists = (
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch],
                    cwd=tmp_path,
                    capture_output=True,
                ).returncode
                == 0
            )
            if branch_exists:
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=True,
                )
            else:
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=True,
                )

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        return result.returncode, result.stdout, result.stderr

    def run_hook_with_project_dir(
        self, input_data: dict, project_dir: Path
    ) -> Tuple[int, str, str]:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def _setup_step_state(
        self,
        tmp_path: Path,
        branch: str,
        phase: str,
        subtask_id: str = "ST-001",
        subtask_phases: dict | None = None,
    ) -> None:
        """Create step_state.json with given phase."""
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "current_step_phase": phase,
            "current_subtask_id": subtask_id,
            "subtask_phases": subtask_phases or {},
        }
        (map_dir / "step_state.json").write_text(json.dumps(state))

    # --- Non-editing tools ---

    def test_allows_non_editing_tools(self, tmp_path: Path) -> None:
        """Read, Bash, and other non-editing tools should always be allowed."""
        for tool_name in ["Read", "Bash", "Grep", "Glob", "Task"]:
            code, stdout, _ = self.run_hook(
                {"tool_name": tool_name, "tool_input": {"file_path": "/test.py"}},
                tmp_path,
            )
            assert code == 0, f"{tool_name} should be allowed"
            self._assert_allowed(stdout)

    # --- Fail-open behavior ---

    def test_allows_edit_when_no_state_files(self, tmp_path: Path) -> None:
        """Edit allowed when no step_state.json exists."""
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_handles_invalid_json_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open on invalid step_state.json."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        (map_dir / "step_state.json").write_text("not valid json {")

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_handles_malformed_hook_input_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open on malformed hook input JSON."""
        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0
        self._assert_allowed(result.stdout)

    # --- Phase-based enforcement ---

    def test_blocks_edit_during_monitor_phase(self, tmp_path: Path) -> None:
        """Edit blocked during MONITOR phase."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MONITOR" in reason
        assert "ACTOR" in reason  # Should mention allowed phases

    def test_blocks_edit_during_decompose_phase(self, tmp_path: Path) -> None:
        """Edit blocked during DECOMPOSE phase."""
        self._setup_step_state(tmp_path, "master", "DECOMPOSE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_edit_during_predictor_phase(self, tmp_path: Path) -> None:
        """Edit blocked during PREDICTOR phase."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_allows_edit_during_actor_phase(self, tmp_path: Path) -> None:
        """Edit allowed during ACTOR phase."""
        self._setup_step_state(tmp_path, "master", "ACTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_during_apply_phase(self, tmp_path: Path) -> None:
        """Edit allowed during APPLY phase."""
        self._setup_step_state(tmp_path, "master", "APPLY")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_during_test_writer_phase(self, tmp_path: Path) -> None:
        """Edit allowed during TEST_WRITER phase (TDD mode)."""
        self._setup_step_state(tmp_path, "master", "TEST_WRITER")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_write_during_non_editing_phase(self, tmp_path: Path) -> None:
        """Write blocked like Edit during non-editing phases."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_multiedit_during_non_editing_phase(self, tmp_path: Path) -> None:
        """MultiEdit blocked like Edit during non-editing phases."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "MultiEdit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- Parallel wave mode (subtask_phases) ---

    def test_allows_edit_when_any_subtask_in_actor_phase(self, tmp_path: Path) -> None:
        """In parallel mode, allow if ANY subtask is in an editing phase."""
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "MONITOR", "ST-002": "ACTOR"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_when_no_subtask_in_editing_phase(self, tmp_path: Path) -> None:
        """In parallel mode, block if NO subtask is in an editing phase."""
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "MONITOR", "ST-002": "PREDICTOR"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- Step ID translation (subtask_phases stores step IDs, not phase names) ---

    def test_allows_edit_when_subtask_has_step_id_actor(self, tmp_path: Path) -> None:
        """Step ID '2.3' must translate to ACTOR (editing phase) and allow."""
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "2.3"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_when_subtask_has_step_id_test_writer(
        self, tmp_path: Path
    ) -> None:
        """Step ID '2.25' must translate to TEST_WRITER (editing phase) and allow."""
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "2.25"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_when_subtask_has_step_id_research(
        self, tmp_path: Path
    ) -> None:
        """Step ID '2.2' must translate to RESEARCH (non-editing) and block."""
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "2.2"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_phase_message_has_actionable_recovery_commands(
        self, tmp_path: Path
    ) -> None:
        """Regression for friction #11: when Edit is blocked during
        RESEARCH (2.2), the deny message must name the save_research
        command and the validate_step 2.2 follow-up — not a generic
        "phase 'RESEARCH' is not allowed" string. First-time operators
        forget the transition; the gate's message is their only hint.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "RESEARCH" in reason
        assert "save_research" in reason, reason
        assert "validate_step 2.2" in reason, reason

    def test_monitor_phase_message_mentions_hotfix_escape(
        self, tmp_path: Path
    ) -> None:
        """Edit during MONITOR is blocked, but the deny message must
        explicitly document the MAP_MONITOR_HOTFIX=1 opt-in escape and
        the monitor_failed path so operators don't bypass via state
        editing.
        """
        self._setup_step_state(tmp_path, "master", "MONITOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MAP_MONITOR_HOTFIX" in reason, reason
        assert "monitor_failed" in reason, reason

    # --- Exempt paths ---

    def test_allows_map_dir_edits_always(self, tmp_path: Path) -> None:
        """Edits under .map/ always allowed (prevents deadlocks)."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        map_file = str(tmp_path / ".map" / "master" / "state.json")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": map_file}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    # --- Branch scoping ---

    def test_respects_branch_scoping(self, tmp_path: Path) -> None:
        """Step state should be branch-scoped."""
        # Create state for feature-foo only
        self._setup_step_state(tmp_path, "feature-foo", "ACTOR")

        # On master (no state) → fail-open → allow
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
            branch="master",
        )
        assert code == 0
        self._assert_allowed(stdout)

    @pytest.mark.parametrize(
        "branch_name,sanitized",
        [
            ("feature/authentication", "feature-authentication"),
            ("feat/add-users", "feat-add-users"),
            ("main", "main"),
            ("bugfix/issue-123", "bugfix-issue-123"),
        ],
    )
    def test_branch_name_sanitization(
        self, tmp_path: Path, branch_name: str, sanitized: str
    ) -> None:
        """Branch names with slashes should be sanitized to dashes."""
        self._setup_step_state(tmp_path, sanitized, "ACTOR")

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
            branch=branch_name,
        )
        assert code == 0
        self._assert_allowed(stdout)

    # --- Constraint enforcement ---

    def test_scope_glob_blocks_outside_scope(self, tmp_path: Path) -> None:
        """scope_glob constraint blocks edits outside allowed pattern."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "tests" / "foo.py")},
            },
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "scope_glob" in reason

    def test_scope_glob_allows_within_scope(self, tmp_path: Path) -> None:
        """scope_glob constraint allows edits matching the pattern."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )
        (tmp_path / "src").mkdir(exist_ok=True)

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "foo.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_uses_claude_project_dir_for_state_and_scope(
        self, tmp_path: Path
    ) -> None:
        """Generated-project hooks must read state relative to CLAUDE_PROJECT_DIR."""
        map_dir = tmp_path / ".map" / "default"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "MONITOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                }
            )
        )

        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/foo.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MONITOR" in reason

        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                }
            )
        )
        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "docs/foo.md"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "scope_glob" in reason

        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/foo.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_no_constraints_allows_all(self, tmp_path: Path) -> None:
        """When constraints is null, all edits are allowed."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": None,
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/anywhere/foo.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)
    def test_scope_glob_brace_expansion_bypassed(self, tmp_path: Path) -> None:
        """scope_glob containing '{' is bypassed (fail-open) with stderr warning."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "{src,tests}/**/*.py"},
                }
            )
        )

        code, stdout, stderr = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/outside/scope.rb"}},
            tmp_path,
        )
        assert code == 0
        # Should be allowed (fail-open) because brace glob is unsupported
        self._assert_allowed(stdout)
        assert "WARNING" in stderr
        assert "Brace expansion" in stderr

    def test_allows_edit_when_phase_is_complete(self, tmp_path: Path) -> None:
        """Edit allowed after workflow completes (current_step_phase == 'COMPLETE')."""
        self._setup_step_state(tmp_path, "master", "COMPLETE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_to_claude_rules_learned_during_monitor(
        self, tmp_path: Path
    ) -> None:
        """Path exemption beats phase block: .claude/rules/learned/ is always allowed."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "error-patterns.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# existing\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_to_claude_skills_during_monitor(self, tmp_path: Path) -> None:
        """Exemption is narrow: .claude/skills/ is NOT exempt, still gated by phase."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        target = tmp_path / ".claude" / "skills" / "map-review" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# skill\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MONITOR" in reason

    def test_allows_edit_when_subtask_phase_is_complete(self, tmp_path: Path) -> None:
        """Parallel-wave mode: COMPLETE subtask phase counts as an ALLOWED_PHASE.

        Matches the sequential ``test_allows_edit_when_phase_is_complete`` contract,
        but exercises the ``subtask_phases`` dict path used by parallel waves.
        """
        self._setup_step_state(
            tmp_path,
            "master",
            "MONITOR",
            subtask_phases={"ST-001": "COMPLETE"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_learned_rules_exemption_only_covers_markdown(self, tmp_path: Path) -> None:
        """Non-markdown files under .claude/rules/learned/ are NOT exempt."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# python\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MONITOR" in reason

    def test_learned_rules_exemption_allows_nested_markdown(
        self, tmp_path: Path
    ) -> None:
        """Markdown files in subdirectories under .claude/rules/learned/ are exempt."""
        self._setup_step_state(tmp_path, "master", "MONITOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "deep" / "nested.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# learned\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)
