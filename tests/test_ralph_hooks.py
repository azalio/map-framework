"""
Tests for Ralph Loop hooks.

Run with: pytest tests/test_ralph_hooks.py -v

IMPORTANT: Tests use branch-scoped paths (.map/<branch>/) matching hook implementation.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import Tuple

# Get the repository root directory (where this test file lives is tests/)
REPO_ROOT = Path(__file__).parent.parent


def get_mock_branch() -> str:
    """Return mock branch name for tests (git not available in tmp_path)."""
    return "default"


class TestCircuitBreaker:
    """Tests for ralph-circuit-breaker.py hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/ralph-circuit-breaker.py"

    def run_hook(
        self, input_data: dict, tmp_path: Path
    ) -> Tuple[int, str, str]:
        """Run hook with given input and return (exit_code, stdout, stderr)."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_allows_first_edit(self, tmp_path: Path) -> None:
        """First edit to a file should be allowed."""
        code, stdout, stderr = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": "/test.py"},
            },
            tmp_path,
        )

        assert code == 0
        # On allow: no stdout output (or empty JSON)

    def test_blocks_after_max_edits(self, tmp_path: Path) -> None:
        """Should block after MAX_SAME_FILE_EDITS to same file."""
        # Set lower limit for test
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["RALPH_MAX_FILE_EDITS"] = "3"

        # Create branch-scoped history with 3 edits
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        history_file = branch_dir / ".tool_history.jsonl"

        # Write history using atomic appends (matching hook behavior)
        with open(history_file, "a", encoding="utf-8") as f:
            for _ in range(3):
                f.write(json.dumps({"tool": "Edit", "file": "/test.py"}) + "\n")

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/test.py"},
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 2  # Blocked
        # Error output goes to stderr (following block-secrets.py pattern)
        stderr_json = json.loads(result.stderr.strip())
        assert (
            "Circuit Breaker" in stderr_json.get("hookSpecificOutput", {}).get("error", "")
        )

    def test_outputs_valid_json_on_error(self, tmp_path: Path) -> None:
        """Should output nothing on malformed input (allows through)."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            env=env,
        )

        # On parse error: allow through (exit 0)
        assert result.returncode == 0

    def test_different_files_not_counted_together(self, tmp_path: Path) -> None:
        """Edits to different files should be counted separately."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["RALPH_MAX_FILE_EDITS"] = "3"

        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        history_file = branch_dir / ".tool_history.jsonl"

        # Write edits to different files
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tool": "Edit", "file": "/file1.py"}) + "\n")
            f.write(json.dumps({"tool": "Edit", "file": "/file2.py"}) + "\n")
            f.write(json.dumps({"tool": "Edit", "file": "/file3.py"}) + "\n")

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/file4.py"},
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0  # Allowed - each file only edited once

    def test_blocks_total_iterations(self, tmp_path: Path) -> None:
        """Should block when total iterations reached."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["RALPH_MAX_ITERATIONS"] = "5"

        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        history_file = branch_dir / ".tool_history.jsonl"

        # Write 5 entries (at limit)
        with open(history_file, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(json.dumps({"tool": "Edit", "file": f"/file{i}.py"}) + "\n")

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/new_file.py"},
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 2  # Blocked

    def test_reset_marker_resets_limits(self, tmp_path: Path) -> None:
        """Reset marker should reset limits."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["RALPH_MAX_ITERATIONS"] = "5"

        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        history_file = branch_dir / ".tool_history.jsonl"
        reset_marker = branch_dir / ".ralph_reset_limits"

        # Write 5 entries (at limit)
        with open(history_file, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(json.dumps({"tool": "Edit", "file": f"/file{i}.py"}) + "\n")

        # Write reset marker
        reset_marker.write_text("reset\n")

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/new_file.py"},
                }
            ),
            capture_output=True,
            text=True,
            env=env,
        )

        # Should be allowed now
        assert result.returncode == 0
        # Marker should be removed
        assert not reset_marker.exists()


class TestIterationLogger:
    """Tests for ralph-iteration-logger.py hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/ralph-iteration-logger.py"

    def run_hook(
        self, input_data: dict, tmp_path: Path
    ) -> Tuple[int, str, str]:
        """Run hook with given input."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_logs_iteration(self, tmp_path: Path) -> None:
        """Should log iteration to branch-scoped iteration_log.jsonl."""
        code, _, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_response": {"success": True},
            },
            tmp_path,
        )

        assert code == 0

        # Check branch-scoped log file
        branch = get_mock_branch()
        log_file = tmp_path / ".map" / branch / "iteration_log.jsonl"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["tool"] == "Edit"
        assert entry["effectiveness"] == 1.0

    def test_detects_thrashing(self, tmp_path: Path) -> None:
        """Should detect thrashing after 3 low-effectiveness iterations."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        # Create history with low effectiveness using atomic appends
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"effectiveness": 0.3, "tool": "Edit", "file": ""}) + "\n")
            f.write(json.dumps({"effectiveness": 0.3, "tool": "Edit", "file": ""}) + "\n")

        code, _, stderr = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_response": {"error": "failed"},
            },
            tmp_path,
        )

        assert code == 0
        # Thrashing warning goes to stderr
        assert "low_effectiveness" in stderr.lower() or "0.3" in stderr.lower()

    def test_effectiveness_from_exit_code(self, tmp_path: Path) -> None:
        """Should calculate effectiveness from Bash exit_code, not string search."""
        # Bash with exit_code=0 should be effective
        code, _, _ = self.run_hook(
            {
                "tool_name": "Bash",
                "tool_response": {
                    "exit_code": 0,
                    "output": "error in output",
                },  # word "error" but success
            },
            tmp_path,
        )

        branch = get_mock_branch()
        log_file = tmp_path / ".map" / branch / "iteration_log.jsonl"
        entry = json.loads(log_file.read_text().strip())
        assert entry["effectiveness"] == 1.0  # Based on exit_code, not string search

    def test_always_exits_zero(self, tmp_path: Path) -> None:
        """PostToolUse hooks should always exit 0."""
        code, _, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_response": None,
            },
            tmp_path,
        )
        assert code == 0


class TestContextPruner:
    """Tests for ralph-context-pruner.py hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/ralph-context-pruner.py"

    def run_hook(
        self, tmp_path: Path, input_data: dict = None
    ) -> Tuple[int, str, str]:
        """Run hook with given input."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data or {}),
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_always_exits_zero(self, tmp_path: Path) -> None:
        """PreCompact hooks should always exit 0."""
        code, _, _ = self.run_hook(tmp_path)
        assert code == 0

    def test_prunes_large_files(self, tmp_path: Path) -> None:
        """Should truncate files over MAX_LINES."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        # Write 150 lines (over MAX_LINES=100)
        with open(log_file, "w") as f:
            for i in range(150):
                f.write(json.dumps({"iteration": i}) + "\n")

        code, _, stderr = self.run_hook(tmp_path)

        assert code == 0
        # Check that file was truncated
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) <= 100  # Truncated to MAX_LINES

    def test_outputs_empty_json(self, tmp_path: Path) -> None:
        """Should output empty JSON to stdout."""
        code, stdout, _ = self.run_hook(tmp_path)
        assert code == 0
        assert stdout.strip() == "{}"

    def test_no_map_dir_does_not_fail(self, tmp_path: Path) -> None:
        """Should not fail if .map directory doesn't exist."""
        # Don't create .map directory
        code, stdout, _ = self.run_hook(tmp_path)
        assert code == 0
        assert stdout.strip() == "{}"
