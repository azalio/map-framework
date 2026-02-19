"""
Tests for workflow-gate.py hook.

Run with: pytest tests/test_workflow_gate.py -v

This hook enforces MAP Framework workflow adherence by blocking Edit/Write/MultiEdit
until required workflow steps (actor + monitor) are completed.
"""

import json
import subprocess
from pathlib import Path
from typing import Tuple

import pytest

# Get the repository root directory (where this test file lives is tests/)
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
        assert payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
        assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
        reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
        assert reason
        return reason

    def run_hook(
        self, input_data: dict, tmp_path: Path, branch: str = "master"
    ) -> Tuple[int, str, str]:
        """Run workflow-gate.py hook with given input.

        Returns:
            (exit_code, stdout, stderr)
        """
        # Initialize real git repo in tmp_path (only if not already initialized)
        git_dir = tmp_path / ".git"
        if not git_dir.exists():
            subprocess.run(
                ["git", "init"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )

            # Configure git user for CI environments
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

            # Create initial commit (required for branch to exist)
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

        # Get current branch
        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Switch to target branch if different
        if current_branch != branch:
            # Check if branch exists
            branch_exists = (
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch],
                    cwd=tmp_path,
                    capture_output=True,
                ).returncode
                == 0
            )

            if branch_exists:
                # Switch to existing branch
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=True,
                )
            else:
                # Create and checkout new branch
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

    def test_allows_non_editing_tools(self, tmp_path: Path) -> None:
        """Read, Bash, and other non-editing tools should always be allowed."""
        for tool_name in ["Read", "Bash", "Grep", "Glob", "Task"]:
            code, stdout, _ = self.run_hook(
                {
                    "tool_name": tool_name,
                    "tool_input": {"file_path": "/test.py"},
                },
                tmp_path,
            )

            assert code == 0, f"{tool_name} should be allowed"
            self._assert_allowed(stdout)

    def test_allows_edit_when_no_workflow_state(self, tmp_path: Path) -> None:
        """Edit should be allowed when workflow_state.json doesn't exist (fail-open)."""
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_without_actor(self, tmp_path: Path) -> None:
        """Edit should be blocked if 'actor' step not completed."""
        # Create workflow_state.json with incomplete steps
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {
                        "ST-001": [
                            "xml_packet",
                        ]  # Missing actor and monitor
                    },
                    "pending_steps": {
                        "ST-001": ["actor", "monitor", "tests", "linter"]
                    },
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0  # Hook signals blocking via JSON decision
        reason = self._assert_denied(stdout)
        assert "actor" in reason.lower()
        assert "monitor" in reason.lower()

    def test_blocks_edit_without_monitor(self, tmp_path: Path) -> None:
        """Edit should be blocked if 'monitor' step not completed (even if actor done)."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {
                        "ST-001": [
                            "xml_packet",
                            "actor",
                        ]  # Missing monitor
                    },
                    "pending_steps": {"ST-001": ["monitor", "tests", "linter"]},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        reason = self._assert_denied(stdout)
        assert "monitor" in reason.lower()

    def test_allows_edit_after_actor_and_monitor(self, tmp_path: Path) -> None:
        """Edit should be allowed when both actor and monitor are completed."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {
                        "ST-001": ["xml_packet", "actor", "monitor"]
                    },
                    "pending_steps": {"ST-001": ["tests", "linter"]},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_write_without_required_steps(self, tmp_path: Path) -> None:
        """Write should be blocked like Edit."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {"ST-001": ["xml_packet"]},
                    "pending_steps": {"ST-001": ["actor", "monitor"]},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_multiedit_without_required_steps(self, tmp_path: Path) -> None:
        """MultiEdit should be blocked like Edit and Write."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {"ST-001": []},
                    "pending_steps": {"ST-001": ["actor", "monitor"]},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_when_no_current_subtask(self, tmp_path: Path) -> None:
        """Should block if current_subtask is null or missing."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": None,  # No active subtask
                    "completed_steps": {},
                    "pending_steps": {},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        reason = self._assert_denied(stdout)
        assert "current_subtask" in reason.lower()

    def test_handles_invalid_json_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open (allow) on invalid workflow_state.json."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text("not valid json {")

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0  # Fail-open
        self._assert_allowed(stdout)

    def test_handles_malformed_hook_input_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open (allow) on malformed hook input JSON."""
        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0  # Fail-open
        self._assert_allowed(result.stdout)

    def test_respects_branch_scoping(self, tmp_path: Path) -> None:
        """Workflow state should be branch-scoped (.map/<branch>/)."""
        # Create state for different branch
        map_dir = tmp_path / ".map" / "feature-foo"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {
                        "ST-001": ["actor", "monitor"]  # Complete on feature-foo
                    },
                    "pending_steps": {"ST-001": []},
                }
            )
        )

        # Try to edit on master branch (should allow - no state file for master)
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
            branch="master",
        )

        assert code == 0
        self._assert_allowed(stdout)

    def test_different_subtask_steps_independent(self, tmp_path: Path) -> None:
        """completed_steps should be tracked per subtask."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-002",  # Working on ST-002
                    "completed_steps": {
                        "ST-001": ["actor", "monitor"],  # ST-001 complete
                        "ST-002": ["xml_packet"],  # ST-002 incomplete
                    },
                    "pending_steps": {"ST-001": [], "ST-002": ["actor", "monitor"]},
                }
            )
        )

        # Should block because ST-002 (current) is incomplete
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        reason = self._assert_denied(stdout)
        assert "ST-002" in reason or "actor" in reason.lower()

    def test_error_message_includes_workflow_steps(self, tmp_path: Path) -> None:
        """Block message should explain required workflow steps."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {"ST-001": []},
                    "pending_steps": {"ST-001": ["actor", "monitor"]},
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        error_msg = self._assert_denied(stdout)

        # Should mention the workflow steps
        assert "actor" in error_msg.lower()
        assert "monitor" in error_msg.lower()
        assert "Task(subagent_type='actor')" in error_msg
        assert "Task(subagent_type='monitor')" in error_msg

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
        # Create state for sanitized branch name
        map_dir = tmp_path / ".map" / sanitized
        map_dir.mkdir(parents=True)
        state_file = map_dir / "workflow_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "workflow": "map-efficient",
                    "current_subtask": "ST-001",
                    "completed_steps": {"ST-001": ["actor", "monitor"]},
                    "pending_steps": {"ST-001": []},
                }
            )
        )

        # Hook should find state using sanitized branch name
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
            branch=branch_name,
        )

        assert code == 0
        self._assert_allowed(stdout)
