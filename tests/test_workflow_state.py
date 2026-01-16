#!/usr/bin/env python3
"""
Pytest tests for src/mapify_cli/workflow_state.py.
Tests all validation criteria from ST-006.
"""
import tempfile
from pathlib import Path

import pytest

from mapify_cli.workflow_state import WorkflowState, WorkflowPhase, Subtask


# =============================================================================
# Validation Criteria Tests
# =============================================================================

class TestValidationCriteria:
    """Tests for the validation criteria from task decomposition."""

    def test_criterion_1_create_with_task_plan(self):
        """VC1: WorkflowState instance can be created with initial task_plan."""
        state = WorkflowState(task_plan="Implement feature X")

        assert state.task_plan == "Implement feature X"
        assert state.completed_subtasks == []
        assert state.current_phase == WorkflowPhase.INIT
        assert state.turn_count == 0
        assert state.started_at is not None
        assert state.updated_at is not None

    def test_criterion_2_save_checkpoint_creates_yaml_frontmatter(self):
        """VC2: save_checkpoint() creates .map/progress.md with valid YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Test task")
            state.add_subtask("ST-001", "First subtask")
            state.mark_subtask_complete("ST-001")

            checkpoint_path = state.save_checkpoint(Path(tmpdir))

            assert checkpoint_path.exists()
            content = checkpoint_path.read_text()

            # Check YAML frontmatter structure
            assert content.startswith("---\n")
            assert "\n---" in content
            assert "task_plan:" in content
            assert "current_phase:" in content
            assert "turn_count:" in content
            assert "completed_subtasks:" in content
            assert "subtasks:" in content

    def test_criterion_3_load_restores_state(self):
        """VC3: load() restores state from .map/progress.md correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and save state
            original = WorkflowState(
                task_plan="Test task with quotes: \"example\"",
                branch_name="feat/test",
            )
            original.add_subtask("ST-001", "First subtask")
            original.add_subtask("ST-002", "Second subtask")
            original.mark_subtask_complete("ST-001")
            original.set_phase(WorkflowPhase.IMPLEMENTATION)
            original.turn_count = 5
            original.save_checkpoint(Path(tmpdir))

            # Load and verify
            loaded = WorkflowState.load(Path(tmpdir))

            assert loaded is not None
            assert loaded.task_plan == original.task_plan
            assert loaded.branch_name == original.branch_name
            assert loaded.current_phase == WorkflowPhase.IMPLEMENTATION
            assert loaded.turn_count == 5
            assert "ST-001" in loaded.completed_subtasks
            assert len(loaded.subtasks) == 2
            assert loaded.subtasks[0].id == "ST-001"
            assert loaded.subtasks[0].status == "complete"
            assert loaded.subtasks[1].id == "ST-002"
            assert loaded.subtasks[1].status == "pending"

    def test_criterion_4_handles_missing_map_directory(self):
        """VC4: Handles missing .map/ directory by creating it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            map_dir = Path(tmpdir) / ".map"
            assert not map_dir.exists()

            state = WorkflowState(task_plan="Test task")
            checkpoint_path = state.save_checkpoint(Path(tmpdir))

            assert map_dir.exists()
            assert checkpoint_path.exists()

    def test_criterion_5_state_includes_required_fields(self):
        """VC5: State includes: task_plan, completed_subtasks list, current_phase enum, turn_count int."""
        state = WorkflowState(task_plan="Test")

        # task_plan is string
        assert isinstance(state.task_plan, str)

        # completed_subtasks is list
        assert isinstance(state.completed_subtasks, list)

        # current_phase is enum
        assert isinstance(state.current_phase, WorkflowPhase)

        # turn_count is int
        assert isinstance(state.turn_count, int)

    def test_criterion_6_checkpoint_is_human_readable(self):
        """VC6: Checkpoint file is human-readable markdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Implement authentication")
            state.add_subtask("ST-001", "Create user model")
            state.add_subtask("ST-002", "Add password hashing")
            state.mark_subtask_complete("ST-001")
            state.mark_subtask_in_progress("ST-002")
            state.set_phase(WorkflowPhase.IMPLEMENTATION)

            checkpoint_path = state.save_checkpoint(Path(tmpdir))
            content = checkpoint_path.read_text()

            # Check human-readable elements
            assert "# MAP Workflow Progress" in content
            assert "**Task:**" in content
            assert "**Phase:**" in content
            assert "## Progress" in content
            assert "- [x]" in content  # Completed checkbox
            assert "- [ ]" in content  # Incomplete checkbox
            assert "*(in progress)*" in content
            assert "*Last updated:" in content


# =============================================================================
# WorkflowState Creation Tests
# =============================================================================

class TestWorkflowStateCreation:
    """Test WorkflowState initialization."""

    def test_minimal_creation(self):
        """Create state with only required field."""
        state = WorkflowState(task_plan="Task")
        assert state.task_plan == "Task"
        assert state.subtasks == []

    def test_creation_with_all_fields(self):
        """Create state with all optional fields."""
        state = WorkflowState(
            task_plan="Full task",
            completed_subtasks=["ST-001"],
            current_phase=WorkflowPhase.VALIDATION,
            turn_count=10,
            branch_name="feat/test",
            started_at="2025-01-01T00:00:00",
            updated_at="2025-01-01T12:00:00",
        )

        assert state.task_plan == "Full task"
        assert state.completed_subtasks == ["ST-001"]
        assert state.current_phase == WorkflowPhase.VALIDATION
        assert state.turn_count == 10
        assert state.branch_name == "feat/test"
        assert state.started_at == "2025-01-01T00:00:00"
        assert state.updated_at == "2025-01-01T12:00:00"


# =============================================================================
# Subtask Management Tests
# =============================================================================

class TestSubtaskManagement:
    """Test subtask operations."""

    def test_add_subtask(self):
        """Adding subtasks."""
        state = WorkflowState(task_plan="Task")
        state.add_subtask("ST-001", "First subtask")
        state.add_subtask("ST-002", "Second subtask")

        assert len(state.subtasks) == 2
        assert state.subtasks[0].id == "ST-001"
        assert state.subtasks[0].description == "First subtask"
        assert state.subtasks[0].status == "pending"

    def test_mark_subtask_complete(self):
        """Marking subtask as complete."""
        state = WorkflowState(task_plan="Task")
        state.add_subtask("ST-001", "First subtask")
        state.mark_subtask_complete("ST-001")

        assert "ST-001" in state.completed_subtasks
        assert state.subtasks[0].status == "complete"
        assert state.subtasks[0].completed_at is not None

    def test_mark_subtask_in_progress(self):
        """Marking subtask as in progress."""
        state = WorkflowState(task_plan="Task")
        state.add_subtask("ST-001", "First subtask")
        state.mark_subtask_in_progress("ST-001")

        assert state.subtasks[0].status == "in_progress"

    def test_get_remaining_subtasks(self):
        """Getting remaining subtasks."""
        state = WorkflowState(task_plan="Task")
        state.add_subtask("ST-001", "First")
        state.add_subtask("ST-002", "Second")
        state.add_subtask("ST-003", "Third")
        state.mark_subtask_complete("ST-001")

        remaining = state.get_remaining_subtasks()
        assert len(remaining) == 2
        assert remaining[0].id == "ST-002"
        assert remaining[1].id == "ST-003"

    def test_is_complete(self):
        """Checking if workflow is complete."""
        state = WorkflowState(task_plan="Task")
        state.add_subtask("ST-001", "First")
        state.add_subtask("ST-002", "Second")

        assert not state.is_complete()

        state.mark_subtask_complete("ST-001")
        assert not state.is_complete()

        state.mark_subtask_complete("ST-002")
        assert state.is_complete()


# =============================================================================
# Phase and Turn Management Tests
# =============================================================================

class TestPhaseManagement:
    """Test phase and turn operations."""

    def test_set_phase(self):
        """Setting workflow phase."""
        state = WorkflowState(task_plan="Task")

        assert state.current_phase == WorkflowPhase.INIT

        state.set_phase(WorkflowPhase.DECOMPOSITION)
        assert state.current_phase == WorkflowPhase.DECOMPOSITION

        state.set_phase(WorkflowPhase.IMPLEMENTATION)
        assert state.current_phase == WorkflowPhase.IMPLEMENTATION

    def test_increment_turn(self):
        """Incrementing turn counter."""
        state = WorkflowState(task_plan="Task")

        assert state.turn_count == 0
        state.increment_turn()
        assert state.turn_count == 1
        state.increment_turn()
        state.increment_turn()
        assert state.turn_count == 3


# =============================================================================
# Checkpoint Load Tests
# =============================================================================

class TestCheckpointLoad:
    """Test loading from checkpoint."""

    def test_load_nonexistent(self):
        """Loading from non-existent checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded is None

    def test_exists_method(self):
        """Checking if checkpoint exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            assert not WorkflowState.exists(Path(tmpdir))

            state = WorkflowState(task_plan="Task")
            state.save_checkpoint(Path(tmpdir))

            assert WorkflowState.exists(Path(tmpdir))

    def test_load_preserves_all_subtask_data(self):
        """Load preserves subtask completed_at."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Task")
            state.add_subtask("ST-001", "First")
            state.mark_subtask_complete("ST-001")
            original_completed_at = state.subtasks[0].completed_at
            state.save_checkpoint(Path(tmpdir))

            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded.subtasks[0].completed_at == original_completed_at


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Test edge cases and special characters."""

    def test_task_plan_with_special_chars(self):
        """Task plan with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            special_task = "Task with: colon, \"quotes\", and newline\\n"
            state = WorkflowState(task_plan=special_task)
            state.save_checkpoint(Path(tmpdir))

            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded is not None
            assert loaded.task_plan == special_task

    def test_empty_subtasks_list(self):
        """Handle empty subtasks list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Task")
            state.save_checkpoint(Path(tmpdir))

            content = (Path(tmpdir) / ".map" / "progress.md").read_text()
            assert "subtasks:" in content

            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded.subtasks == []

    def test_multiple_saves(self):
        """Multiple saves update the file correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Task")
            state.add_subtask("ST-001", "First")
            state.save_checkpoint(Path(tmpdir))

            state.mark_subtask_complete("ST-001")
            state.add_subtask("ST-002", "Second")
            state.save_checkpoint(Path(tmpdir))

            loaded = WorkflowState.load(Path(tmpdir))
            assert len(loaded.subtasks) == 2
            assert "ST-001" in loaded.completed_subtasks

    def test_all_phases(self):
        """All workflow phases can be saved and loaded."""
        for phase in WorkflowPhase:
            with tempfile.TemporaryDirectory() as tmpdir:
                state = WorkflowState(task_plan="Task")
                state.set_phase(phase)
                state.save_checkpoint(Path(tmpdir))

                loaded = WorkflowState.load(Path(tmpdir))
                assert loaded.current_phase == phase, f"Failed for phase: {phase}"


# =============================================================================
# YAML Parsing Tests
# =============================================================================

class TestYamlParsing:
    """Test YAML frontmatter parsing."""

    def test_parse_simple_values(self):
        """Parse simple key-value pairs."""
        text = """task_plan: My task
current_phase: implementation
turn_count: 5"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert result["task_plan"] == "My task"
        assert result["current_phase"] == "implementation"
        assert result["turn_count"] == "5"

    def test_parse_quoted_values(self):
        """Parse quoted string values."""
        text = """task_plan: "Task with: colon"
branch_name: 'single quotes'"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert result["task_plan"] == "Task with: colon"
        assert result["branch_name"] == "single quotes"

    def test_parse_simple_list(self):
        """Parse simple list."""
        text = """completed_subtasks:
  - ST-001
  - ST-002"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert result["completed_subtasks"] == ["ST-001", "ST-002"]

    def test_parse_empty_list(self):
        """Parse empty list."""
        text = """completed_subtasks:
  []"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert result["completed_subtasks"] == []

    def test_parse_object_list(self):
        """Parse list of objects (subtasks)."""
        text = """subtasks:
  - id: ST-001
    description: First task
    status: complete
  - id: ST-002
    description: Second task
    status: pending"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert len(result["subtasks"]) == 2
        assert result["subtasks"][0]["id"] == "ST-001"
        assert result["subtasks"][0]["description"] == "First task"
        assert result["subtasks"][0]["status"] == "complete"
        assert result["subtasks"][1]["id"] == "ST-002"
