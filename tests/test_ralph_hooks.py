"""
Tests for Ralph Loop hooks.

Run with: pytest tests/test_ralph_hooks.py -v

IMPORTANT: Tests use branch-scoped paths (.map/<branch>/) matching hook implementation.
"""

import json
import os
import subprocess
from pathlib import Path

# Get the repository root directory (where this test file lives is tests/)
REPO_ROOT = Path(__file__).parent.parent


def get_mock_branch() -> str:
    """Return mock branch name for tests (git not available in tmp_path)."""
    return "default"


# NOTE: TestCircuitBreaker removed - ralph-circuit-breaker.py was deleted
# Circuit breaker was too restrictive and RESET_LIMITS wasn't user-friendly


class TestIterationLogger:
    """Tests for ralph-iteration-logger.py hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/ralph-iteration-logger.py"

    def run_hook(self, input_data: dict, tmp_path: Path) -> tuple[int, str, str]:
        """Run hook with given input."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            env=env,
            check=False,
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
            f.write(
                json.dumps({"effectiveness": 0.3, "tool": "Edit", "file": ""}) + "\n"
            )
            f.write(
                json.dumps({"effectiveness": 0.3, "tool": "Edit", "file": ""}) + "\n"
            )

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
        _, _, _ = self.run_hook(
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

    def test_derive_summary_creates_file(self, tmp_path: Path) -> None:
        """derive_summary should create iteration_summary.json."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(
                        {
                            "ts": "2026-01-01T00:00:00",
                            "iteration": i + 1,
                            "tool": "Edit",
                            "file": "/src/foo.py",
                            "effectiveness": 0.8,
                        }
                    )
                    + "\n" for i in range(5))

        # Run hook to trigger derive_summary
        code, _, _ = self.run_hook(
            {"tool_name": "Edit", "tool_response": {"success": True}},
            tmp_path,
        )
        assert code == 0

        summary_file = branch_dir / "iteration_summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text())
        assert summary["entry_count"] == 6  # 5 pre-existing + 1 from hook
        assert len(summary["file_stats"]) >= 1
        assert summary["aggregate"]["avg_effectiveness"] > 0

    def test_derive_summary_is_thrashing_field_is_bool(self, tmp_path: Path) -> None:
        """is_thrashing field in file_stats should be a boolean."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        # Write enough entries to trigger thrashing (>= THRASHING_WINDOW for one file)
        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(
                        {
                            "ts": "2026-01-01T00:00:00",
                            "iteration": i + 1,
                            "tool": "Edit",
                            "file": "/src/foo.py",
                            "effectiveness": 0.5,
                        }
                    )
                    + "\n" for i in range(5))

        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["RALPH_THRASHING_WINDOW"] = "3"

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps({"tool_name": "Edit", "tool_response": {"success": True}}),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0

        summary_file = branch_dir / "iteration_summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text())
        for fs in summary["file_stats"]:
            assert isinstance(
                fs["is_thrashing"], bool
            ), f"is_thrashing should be bool, got {type(fs['is_thrashing'])}"

    def test_derive_summary_dropped_count(self, tmp_path: Path) -> None:
        """dropped_count should be non-zero when total lines exceed deque maxlen."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        # Write 110 lines — deque keeps last 100
        with open(log_file, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(
                        {
                            "ts": "2026-01-01T00:00:00",
                            "iteration": i + 1,
                            "tool": "Edit",
                            "file": "/src/foo.py",
                            "effectiveness": 1.0,
                        }
                    )
                    + "\n" for i in range(110))

        code, _, _ = self.run_hook(
            {"tool_name": "Edit", "tool_response": {"success": True}},
            tmp_path,
        )
        assert code == 0

        summary_file = branch_dir / "iteration_summary.json"
        summary = json.loads(summary_file.read_text())
        assert summary["dropped_count"] > 0, "Should have dropped entries beyond 100"
        assert summary["total_entries_seen"] == 111  # 110 pre-existing + 1 from hook

    def test_derive_summary_empty_file_field_skipped(self, tmp_path: Path) -> None:
        """Entries without a file path should be excluded from file_stats."""
        branch = get_mock_branch()
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True)
        log_file = branch_dir / "iteration_log.jsonl"

        with open(log_file, "w", encoding="utf-8") as f:
            # Entry with no file
            f.write(
                json.dumps(
                    {
                        "ts": "2026-01-01T00:00:00",
                        "iteration": 1,
                        "tool": "Bash",
                        "file": "",
                        "effectiveness": 1.0,
                    }
                )
                + "\n"
            )
            # Entry with file
            f.write(
                json.dumps(
                    {
                        "ts": "2026-01-01T00:00:00",
                        "iteration": 2,
                        "tool": "Edit",
                        "file": "/src/bar.py",
                        "effectiveness": 0.9,
                    }
                )
                + "\n"
            )

        code, _, _ = self.run_hook(
            {"tool_name": "Bash", "tool_response": {"exit_code": 0}},
            tmp_path,
        )
        assert code == 0

        summary_file = branch_dir / "iteration_summary.json"
        summary = json.loads(summary_file.read_text())
        file_names = [fs["file"] for fs in summary["file_stats"]]
        assert "" not in file_names
        assert "/src/bar.py" in file_names


class TestContextPruner:
    """Tests for ralph-context-pruner.py hook."""

    HOOK_PATH = REPO_ROOT / ".claude/hooks/ralph-context-pruner.py"

    def run_hook(self, tmp_path: Path, input_data: dict | None = None) -> tuple[int, str, str]:
        """Run hook with given input."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data or {}),
            capture_output=True,
            text=True,
            env=env,
            check=False,
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
            f.writelines(json.dumps({"iteration": i}) + "\n" for i in range(150))

        code, _, _ = self.run_hook(tmp_path)

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
