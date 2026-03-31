import json
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


def _run_hook(tmp_project_dir: Path, stdin_payload: dict) -> tuple[int, str, str]:
    hook_path = Path(".claude/hooks/workflow-context-injector.py")
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_project_dir)

    proc = subprocess.run(
        ["python3", str(hook_path)],
        input=json.dumps(stdin_payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _import_hook():
    """Import the hook module dynamically for direct function testing."""
    hook_path = Path(".claude/hooks/workflow-context-injector.py").resolve()
    spec = importlib.util.spec_from_file_location("workflow_context_injector", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook_mod():
    return _import_hook()


@pytest.fixture
def branch_name():
    return (
        subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        .stdout.strip()
        .replace("/", "-")
    )


def test_injects_for_edit_when_step_state_exists(tmp_path: Path, branch_name: str) -> None:
    branch = branch_name

    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "1.55",
                "current_step_phase": "REVIEW_PLAN",
                "current_subtask_id": "ST-001",
                "subtask_index": 0,
                "subtask_sequence": ["ST-001", "ST-002"],
                "plan_approved": False,
                "execution_mode": "batch",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "[MAP]" in additional
    assert "1.55" in additional
    assert "REVIEW_PLAN" in additional
    assert "ST-001" in additional
    assert "REQUIRED" in additional


def test_skips_for_readonly_bash(tmp_path: Path) -> None:
    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert code == 0
    assert err == ""
    assert out == "{}"


def test_injects_for_pytest_bash_when_step_state_exists(tmp_path: Path, branch_name: str) -> None:
    branch = branch_name

    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.8",
                "current_step_phase": "TESTS_GATE",
                "current_subtask_id": "ST-002",
                "subtask_index": 1,
                "subtask_sequence": ["ST-001", "ST-002"],
                "plan_approved": True,
                "execution_mode": "step_by_step",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}},
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "2.8" in additional
    assert "TESTS_GATE" in additional
    assert "ST-002" in additional


class TestLoadGoalAndTitle:
    """Tests for load_goal_and_title function."""

    def test_returns_goal_and_title(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        plan = "## Goal\nImplement the feature. More details here.\n\n## Subtasks\n..."
        (state_dir / f"task_plan_{branch}.md").write_text(plan)

        bp = {"subtasks": [{"id": "ST-001", "title": "First task"}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            goal, title = hook_mod.load_goal_and_title(branch, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert goal == "Implement the feature."
        assert title == "First task"

    def test_returns_empty_when_no_files(self, tmp_path, hook_mod, branch_name):
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            goal, title = hook_mod.load_goal_and_title(branch_name, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert goal == ""
        assert title == ""

    def test_truncates_goal_at_80_chars(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        long_goal = "A" * 100
        plan = f"## Goal\n{long_goal}\n\n## Done"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            goal, _ = hook_mod.load_goal_and_title(branch, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert len(goal) == 80
        assert goal.endswith("...")

    def test_truncates_goal_at_first_sentence(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        plan = "## Goal\nFirst sentence. Second sentence. Third.\n\n## Done"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            goal, _ = hook_mod.load_goal_and_title(branch, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert goal == "First sentence."

    def test_returns_empty_title_for_missing_subtask(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        bp = {"subtasks": [{"id": "ST-001", "title": "Only task"}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            _, title = hook_mod.load_goal_and_title(branch, "ST-999")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert title == ""

    def test_handles_invalid_json_blueprint(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        (state_dir / "blueprint.json").write_text("not json")

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            _, title = hook_mod.load_goal_and_title(branch, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert title == ""

    def test_matches_overview_heading(self, tmp_path, hook_mod, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        plan = "## Overview\nThe overview text.\n\n## Details"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            goal, _ = hook_mod.load_goal_and_title(branch, "ST-001")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert goal == "The overview text."


class TestFormatReminderTruncation:
    """Tests for format_reminder progressive 500-char truncation."""

    def _make_state(self, **overrides):
        base = {
            "current_step_id": "2.3",
            "current_step_phase": "ACTOR",
            "current_subtask_id": "ST-001",
            "subtask_index": 0,
            "subtask_sequence": ["ST-001"],
            "plan_approved": True,
            "execution_mode": "batch",
        }
        base.update(overrides)
        return base

    def test_result_within_500_chars(self, hook_mod, tmp_path, branch_name):
        """Basic reminder should be well under 500 chars."""
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch_name)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= 500

    def test_includes_goal_when_plan_exists(self, hook_mod, tmp_path, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        plan = "## Goal\nShort goal.\n\n## Done"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert "Goal: Short goal." in result

    def test_includes_subtask_title(self, hook_mod, tmp_path, branch_name):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        bp = {"subtasks": [{"id": "ST-001", "title": "My task title"}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert "My task title" in result

    def test_hard_truncates_at_500(self, hook_mod, tmp_path, branch_name):
        """When base string exceeds 500 chars even after dropping goal, hard-truncate."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Create a title long enough to push past 500 chars even without goal
        bp = {"subtasks": [{"id": "ST-001", "title": "X" * 480}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= 500
        assert result.endswith("...")

    def test_drops_goal_first_when_over_500(self, hook_mod, tmp_path, branch_name):
        """Goal hint is dropped first before hard truncation."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Title that takes ~430 chars, goal that would push it past 500
        plan = "## Goal\nSome goal text.\n\n## Done"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)
        bp = {"subtasks": [{"id": "ST-001", "title": "Y" * 430}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= 500
        # Goal should have been dropped
        assert "Goal:" not in result

    def test_no_goal_or_title_when_subtask_is_dash(self, hook_mod, tmp_path, branch_name):
        """When subtask_id is '-', skip goal/title loading entirely."""
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state(current_subtask_id="-")
            result = hook_mod.format_reminder(state, branch_name)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert "Goal:" not in result

    def test_required_suffix_truncated(self, hook_mod, tmp_path, branch_name):
        """REQUIRED suffix should also be truncated to 500 chars total."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Long title + required action pushes past 500
        bp = {"subtasks": [{"id": "ST-001", "title": "Z" * 350}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            # Use step_id "1.55" which triggers "Review and approve plan" required action
            state = self._make_state(
                current_step_id="1.55",
                current_step_phase="REVIEW_PLAN",
            )
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= 500
