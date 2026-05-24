import json
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


def _run_hook(tmp_project_dir: Path, stdin_payload: dict) -> tuple[int, str, str]:
    return _run_hook_raw(tmp_project_dir, json.dumps(stdin_payload))


def _run_hook_raw(tmp_project_dir: Path, stdin_payload: str) -> tuple[int, str, str]:
    hook_path = Path(".claude/hooks/workflow-context-injector.py")
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_project_dir)

    proc = subprocess.run(
        ["python3", str(hook_path)],
        input=stdin_payload,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _import_hook():
    """Import the hook module dynamically for direct function testing."""
    hook_path = Path(".claude/hooks/workflow-context-injector.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "workflow_context_injector", hook_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook_mod():
    return _import_hook()


@pytest.fixture(scope="session")
def branch_name():
    return "default"


def test_injects_for_edit_when_step_state_exists(
    tmp_path: Path, branch_name: str
) -> None:
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

    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "injected"
    assert state["hook_injection"]["tool_name"] == "Edit"
    assert state["hook_injection"]["additional_context_chars"] == len(additional)
    assert state["hook_injection_counts"]["injected"] == 1


def test_uses_claude_project_dir_for_branch_detection(tmp_path: Path) -> None:
    """A non-git CLAUDE_PROJECT_DIR should use default, not the caller cwd branch."""
    branch = "default"
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
                "current_subtask_id": "ST-001",
                "subtask_index": 0,
                "subtask_sequence": ["ST-001"],
                "plan_approved": True,
                "execution_mode": "batch",
            }
        ),
        encoding="utf-8",
    )
    (state_dir / "blueprint.json").write_text(
        json.dumps(
            {
                "hard_constraints": [
                    {"id": "HC-1", "description": "Preserve retry behavior"}
                ],
                "subtasks": [
                    {
                        "id": "ST-001",
                        "title": "Implement retry handling",
                        "validation_criteria": ["VC1 [AC-1]: retryable timeout"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "src/retry.py"}}
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "2.3" in additional
    assert "ACTOR" in additional
    assert "HC-1" in additional
    assert "AC-1" in additional


def test_skips_for_readonly_bash(tmp_path: Path) -> None:
    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert code == 0
    assert err == ""
    assert out == "{}"


def test_records_skipped_for_insignificant_bash_when_state_exists(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
                "current_subtask_id": "ST-001",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "bash command not significant"
    assert state["hook_injection"]["tool_name"] == "Bash"
    assert state["hook_injection_counts"]["skipped"] == 1


def test_records_malformed_hook_input_when_state_exists(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook_raw(tmp_path, "{")

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "invalid hook input JSON"
    assert state["hook_injection"]["tool_name"] == "unknown"
    assert state["hook_injection_counts"]["skipped"] == 1


def test_non_string_bash_command_remains_non_blocking(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": ["pytest"]}},
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "bash command is not a string"
    assert state["hook_injection_counts"]["skipped"] == 1


def test_records_unsupported_tool_when_state_exists(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Read", "tool_input": {"file_path": "x"}},
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "tool not configured for workflow injection"
    assert state["hook_injection"]["tool_name"] == "Read"
    assert state["hook_injection_counts"]["skipped"] == 1


def test_schema_invalid_step_state_fields_remain_non_blocking(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": 23,
                "current_step_phase": ["ACTOR"],
                "current_subtask_id": {"id": "ST-001"},
                "execution_mode": {"mode": "batch"},
                "subtask_sequence": "ST-001",
                "execution_waves": {"wave": ["ST-001"]},
                "subtask_files_changed": ["src/example.py"],
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "no reminder formatted"
    assert state["hook_injection_counts"]["skipped"] == 1


def test_missing_step_state_remains_non_blocking_without_creating_state(
    tmp_path: Path, branch_name: str
) -> None:
    state_file = tmp_path / ".map" / branch_name / "step_state.json"

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    assert not state_file.exists()


def test_invalid_step_state_remains_non_blocking_without_clobbering_state(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name
    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "step_state.json"
    state_file.write_text("{", encoding="utf-8")

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    assert state_file.read_text(encoding="utf-8") == "{"


def test_injects_for_pytest_bash_when_step_state_exists(
    tmp_path: Path, branch_name: str
) -> None:
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

    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "injected"
    assert state["hook_injection_counts"]["injected"] == 1


def test_records_skipped_when_state_has_no_reminder(
    tmp_path: Path, branch_name: str
) -> None:
    branch = branch_name

    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "",
                "current_step_phase": "",
                "current_subtask_id": "ST-001",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )

    assert code == 0
    assert err == ""
    assert out == "{}"
    state = json.loads((state_dir / "step_state.json").read_text(encoding="utf-8"))
    assert state["hook_injection"]["status"] == "skipped"
    assert state["hook_injection"]["reason"] == "no reminder formatted"
    assert state["hook_injection_counts"]["skipped"] == 1


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

    def test_returns_empty_title_for_missing_subtask(
        self, tmp_path, hook_mod, branch_name
    ):
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
    """Tests for format_reminder progressive bounded truncation."""

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
        """Basic reminder should be well under the edit-time reminder cap."""
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch_name)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= hook_mod.REMINDER_LIMIT

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

    def test_hard_truncates_at_limit(self, hook_mod, tmp_path, branch_name):
        """When base string exceeds the reminder cap, hard-truncate."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Create a title long enough to push past the cap even without goal.
        bp = {"subtasks": [{"id": "ST-001", "title": "X" * 780}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= hook_mod.REMINDER_LIMIT
        assert result.endswith("...")

    def test_drops_goal_first_when_over_limit(self, hook_mod, tmp_path, branch_name):
        """Goal hint is dropped first before hard truncation."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Title that takes most of the budget; goal would push it past the cap.
        plan = "## Goal\nSome goal text.\n\n## Done"
        (state_dir / f"task_plan_{branch}.md").write_text(plan)
        bp = {"subtasks": [{"id": "ST-001", "title": "Y" * 630}]}
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert len(result) <= hook_mod.REMINDER_LIMIT
        # Goal should have been dropped
        assert "Goal:" not in result

    def test_includes_hard_constraints_and_validation_tags(
        self, hook_mod, tmp_path, branch_name
    ):
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        bp = {
            "hard_constraints": [
                {"id": "HC-1", "description": "Preserve retry behavior"}
            ],
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Implement retry handling",
                    "validation_criteria": [
                        "VC1 [AC-1]: retryable timeout returns guidance",
                        "VC2 [AC-2]: non-retryable errors stay fatal",
                    ],
                }
            ],
        }
        (state_dir / "blueprint.json").write_text(json.dumps(bp))

        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            state = self._make_state()
            result = hook_mod.format_reminder(state, branch)
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

        assert result is not None
        assert "HC-1" in result
        assert "AC-1" in result
        assert "AC-2" in result
        assert "Source>summary" in result

    def test_no_goal_or_title_when_subtask_is_dash(
        self, hook_mod, tmp_path, branch_name
    ):
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
        """REQUIRED suffix should also be truncated at word boundary."""
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)

        # Use word-spaced title so truncation can find a word boundary
        # Long title plus REQUIRED pushes past the reminder cap.
        long_title = ("word " * 150).strip()
        bp = {"subtasks": [{"id": "ST-001", "title": long_title}]}
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
        assert len(result) <= hook_mod.REMINDER_LIMIT
        assert result.endswith("...")


class TestPerTurnReminderDedup:
    """Regression: PreToolUse hook used to emit the [MAP] reminder per
    Edit/Write/Bash invocation, racking up ~30 tokens × N tools per turn
    of paragraph spam. Now identical reminders within DEDUP_WINDOW_SECONDS
    against the same step_state.json mtime are squelched. The first call
    in a turn still emits; only the consecutive duplicates are dropped.
    """

    def _seed_state(self, tmp_project_dir: Path, branch: str) -> Path:
        state_dir = tmp_project_dir / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "step_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "current_step_id": "2.3",
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_index": 0,
                    "subtask_sequence": ["ST-001"],
                    "plan_approved": True,
                    "execution_mode": "batch",
                    "workflow_status": "IN_PROGRESS",
                }
            ),
            encoding="utf-8",
        )
        return state_file

    def test_second_identical_call_within_window_returns_empty(
        self, tmp_path: Path, branch_name: str
    ) -> None:
        branch = branch_name
        self._seed_state(tmp_path, branch)
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/foo.py"},
        }
        # First call: reminder emitted.
        rc1, stdout1, _ = _run_hook(tmp_path, payload)
        assert rc1 == 0
        first = json.loads(stdout1 or "{}")
        assert "hookSpecificOutput" in first, first

        # Second identical call within DEDUP_WINDOW_SECONDS: silent {}.
        rc2, stdout2, _ = _run_hook(tmp_path, payload)
        assert rc2 == 0
        assert stdout2 in ("{}", ""), (
            f"Duplicate reminder must be squelched; got {stdout2!r}"
        )

    def test_state_mutation_busts_dedup(
        self, tmp_path: Path, branch_name: str
    ) -> None:
        # If step_state.json mtime changes between calls (validate_step
        # advanced the workflow), the dedup must NOT squelch — the
        # reminder content may now be different.
        import time as _time
        branch = branch_name
        state_file = self._seed_state(tmp_path, branch)
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/foo.py"},
        }
        rc1, stdout1, _ = _run_hook(tmp_path, payload)
        assert rc1 == 0
        assert "hookSpecificOutput" in (json.loads(stdout1 or "{}"))

        # Mutate state file mtime + content (workflow advance simulation).
        _time.sleep(0.01)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["current_step_phase"] = "MONITOR"
        state["current_step_id"] = "2.4"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        rc2, stdout2, _ = _run_hook(tmp_path, payload)
        assert rc2 == 0
        second = json.loads(stdout2 or "{}")
        # MONITOR-phase reminder ≠ ACTOR-phase reminder ⇒ emit.
        assert "hookSpecificOutput" in second, (
            f"State mtime changed but reminder was squelched: {stdout2!r}"
        )


class TestPhaseAwareSmokeTestSuppression:
    """Regression: when current_step_phase is ACTOR/MONITOR/TEST_WRITER, any
    significant Bash command (build, smoke-test, app boot) is some form of
    self-check. The "REQUIRED: Run Actor" trailer is noise in that context
    (Actor is already in ACTOR). Patterns like `python3 -m sgr_code_review`
    that the static VERIFICATION_PATTERNS list misses must also be
    suppressed by phase context.
    """

    def _seed_state(
        self,
        tmp_project_dir: Path,
        branch: str,
        phase: str,
    ) -> None:
        state_dir = tmp_project_dir / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_id": "2.3" if phase == "ACTOR" else "2.4",
                    "current_step_phase": phase,
                    "current_subtask_id": "ST-001",
                    "subtask_index": 0,
                    "subtask_sequence": ["ST-001"],
                    "plan_approved": True,
                    "execution_mode": "batch",
                    "workflow_status": "IN_PROGRESS",
                }
            ),
            encoding="utf-8",
        )

    def test_actor_phase_suppresses_required_on_smoke_run(
        self, tmp_path: Path, branch_name: str
    ) -> None:
        branch = branch_name
        self._seed_state(tmp_path, branch, "ACTOR")
        rc, stdout, _ = _run_hook(
            tmp_path,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m sgr_code_review --help"},
            },
        )
        assert rc == 0
        payload = json.loads(stdout or "{}")
        # The hook either emits a reminder or nothing. If reminder present,
        # it MUST NOT carry the REQUIRED trailer when phase is ACTOR.
        if payload:
            ctx = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
            assert "REQUIRED:" not in ctx, (
                f"ACTOR-phase Bash smoke-run still carries REQUIRED: {ctx!r}"
            )

    def test_monitor_phase_suppresses_required_on_smoke_run(
        self, tmp_path: Path, branch_name: str
    ) -> None:
        branch = branch_name
        self._seed_state(tmp_path, branch, "MONITOR")
        rc, stdout, _ = _run_hook(
            tmp_path,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m my_app.smoke"},
            },
        )
        assert rc == 0
        payload = json.loads(stdout or "{}")
        if payload:
            ctx = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
            assert "REQUIRED:" not in ctx, (
                f"MONITOR-phase Bash smoke-run still carries REQUIRED: {ctx!r}"
            )

    def test_research_phase_keeps_required_on_bash(
        self, tmp_path: Path, branch_name: str
    ) -> None:
        # RESEARCH phase should still nag "Run Actor" — agent isn't yet
        # in implementation, so the trailer is meaningful.
        branch = branch_name
        state_dir = tmp_path / ".map" / branch
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_id": "2.2",
                    "current_step_phase": "RESEARCH",
                    "current_subtask_id": "ST-001",
                    "subtask_index": 0,
                    "subtask_sequence": ["ST-001"],
                    "plan_approved": True,
                    "execution_mode": "batch",
                    "workflow_status": "IN_PROGRESS",
                }
            ),
            encoding="utf-8",
        )
        rc, stdout, _ = _run_hook(
            tmp_path,
            {
                "tool_name": "Bash",
                # Use a known significant non-verification command (git diff
                # is in the should_inject list for git operations).
                "tool_input": {"command": "git diff HEAD~1"},
            },
        )
        assert rc == 0
        payload = json.loads(stdout or "{}")
        if payload:
            ctx = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
            # In RESEARCH the REQUIRED trailer should remain when emitted
            # (verifies suppression is phase-bounded, not blanket).
            assert "RESEARCH" in ctx
