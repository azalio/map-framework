"""
Pytest tests for src/mapify_cli/workflow_state.py.
Tests all validation criteria from ST-006.
"""
import tempfile
from pathlib import Path

from mapify_cli.workflow_state import WorkflowPhase, WorkflowState

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
                task_plan='Test task with quotes: "example"',
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
            assert loaded is not None
            assert loaded.subtasks[0].completed_at == original_completed_at


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and special characters."""

    def test_task_plan_with_special_chars(self):
        """Task plan with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            special_task = 'Task with: colon, "quotes", and newline\\n'
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
            assert loaded is not None
            assert loaded.subtasks == []

    def test_empty_lists_use_inline_yaml_format(self):
        """Empty lists must use inline YAML format: 'key: []' not 'key:\\n  []'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Task with empty lists")
            # Don't add any subtasks - both lists should be empty
            state.save_checkpoint(Path(tmpdir))

            content = (Path(tmpdir) / ".map" / "progress.md").read_text()

            # Must use inline format (single line)
            assert (
                "completed_subtasks: []" in content
            ), "Empty completed_subtasks must use inline format 'completed_subtasks: []'"
            assert (
                "subtasks: []" in content
            ), "Empty subtasks must use inline format 'subtasks: []'"

            # Must NOT use multi-line format
            assert (
                "completed_subtasks:\n  []" not in content
            ), "Must not use multi-line format for empty completed_subtasks"
            assert (
                "subtasks:\n  []" not in content
            ), "Must not use multi-line format for empty subtasks"

    def test_non_empty_lists_use_multiline_yaml_format(self):
        """Non-empty lists must use multi-line YAML format with proper indentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Task with items")
            state.add_subtask("ST-001", "First subtask")
            state.mark_subtask_complete("ST-001")
            state.save_checkpoint(Path(tmpdir))

            content = (Path(tmpdir) / ".map" / "progress.md").read_text()

            # completed_subtasks should be multi-line with items
            assert "completed_subtasks:" in content
            assert (
                "  - ST-001" in content
            ), "Non-empty completed_subtasks must use multi-line format"

            # subtasks should be multi-line with object items
            assert "subtasks:" in content
            assert (
                "  - id: ST-001" in content
            ), "Non-empty subtasks must use multi-line format"

    def test_yaml_format_round_trip(self):
        """Save → Load → Save should produce consistent YAML format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First save with empty lists
            state1 = WorkflowState(task_plan="Round trip test")
            state1.save_checkpoint(Path(tmpdir))
            content1 = (Path(tmpdir) / ".map" / "progress.md").read_text()

            # Load and save again
            state2 = WorkflowState.load(Path(tmpdir))
            assert state2 is not None
            state2.save_checkpoint(Path(tmpdir))
            content2 = (Path(tmpdir) / ".map" / "progress.md").read_text()

            # Extract YAML frontmatter only (between --- markers), excluding timestamps
            def get_frontmatter_without_timestamps(content):
                import re

                match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if not match:
                    return ""
                frontmatter = match.group(1)
                # Remove timestamp lines
                lines = [
                    line
                    for line in frontmatter.split("\n")
                    if not any(ts in line for ts in ["started_at:", "updated_at:"])
                ]
                return "\n".join(lines)

            fm1 = get_frontmatter_without_timestamps(content1)
            fm2 = get_frontmatter_without_timestamps(content2)

            assert (
                fm1 == fm2
            ), f"Round-trip should produce identical frontmatter.\nFirst:\n{fm1}\n\nSecond:\n{fm2}"

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
            assert loaded is not None
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
                assert loaded is not None
                assert loaded.current_phase == phase, f"Failed for phase: {phase}"


# =============================================================================
# WONT_DO Terminal Status Tests (ST-005)
# =============================================================================


class TestWontDoTerminalStatus:
    """Test won't_do terminal status functionality from ST-005."""

    def test_wont_do_phase_in_enum(self):
        """WorkflowPhase enum includes WONT_DO value."""
        assert hasattr(WorkflowPhase, "WONT_DO")
        assert WorkflowPhase.WONT_DO.value == "won't_do"

    def test_mark_ended_early_sets_phase(self):
        """mark_ended_early() sets current_phase to WONT_DO."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "First subtask")
        state.add_subtask("ST-002", "Second subtask")

        state.mark_ended_early(reason="User cancelled workflow", subtask_id="ST-001")

        assert state.current_phase == WorkflowPhase.WONT_DO

    def test_mark_ended_early_populates_ended_early(self):
        """mark_ended_early() populates ended_early with all required fields."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "First subtask")

        state.mark_ended_early(
            reason="Requirements changed, feature no longer needed",
            subtask_id="ST-001",
        )

        assert state.ended_early is not None
        assert state.ended_early["by_user"] is True
        assert (
            state.ended_early["reason"]
            == "Requirements changed, feature no longer needed"
        )
        assert state.ended_early["at_subtask_id"] == "ST-001"

    def test_mark_ended_early_without_subtask_id(self):
        """mark_ended_early() works without subtask_id."""
        state = WorkflowState(task_plan="Test task")

        state.mark_ended_early(reason="Project cancelled")

        assert state.current_phase == WorkflowPhase.WONT_DO
        assert state.ended_early is not None
        assert state.ended_early["by_user"] is True
        assert state.ended_early["reason"] == "Project cancelled"
        assert state.ended_early["at_subtask_id"] is None

    def test_save_checkpoint_includes_ended_early(self):
        """save_checkpoint() writes ended_early to YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Test task")
            state.add_subtask("ST-001", "First subtask")
            state.mark_ended_early(
                reason="User requested cancellation", subtask_id="ST-001"
            )

            checkpoint_path = state.save_checkpoint(Path(tmpdir))
            content = checkpoint_path.read_text()

            # Check YAML frontmatter contains ended_early
            assert "ended_early:" in content
            assert "by_user: true" in content
            assert "reason:" in content
            assert "User requested cancellation" in content
            assert "at_subtask_id:" in content
            assert "ST-001" in content

    def test_load_restores_ended_early(self):
        """load() restores ended_early from YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and save state with ended_early
            original = WorkflowState(task_plan="Test task")
            original.add_subtask("ST-001", "First subtask")
            original.add_subtask("ST-002", "Second subtask")
            original.mark_subtask_in_progress("ST-002")
            original.mark_ended_early(
                reason="Blocking dependency unavailable", subtask_id="ST-002"
            )
            original.save_checkpoint(Path(tmpdir))

            # Load and verify
            loaded = WorkflowState.load(Path(tmpdir))

            assert loaded is not None
            assert loaded.current_phase == WorkflowPhase.WONT_DO
            assert loaded.ended_early is not None
            assert loaded.ended_early["by_user"] is True
            assert loaded.ended_early["reason"] == "Blocking dependency unavailable"
            assert loaded.ended_early["at_subtask_id"] == "ST-002"

    def test_ended_early_with_special_characters(self):
        """ended_early handles special characters in reason."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Test task")
            state.mark_ended_early(
                reason='User said: "This is no longer needed"', subtask_id="ST-001"
            )

            state.save_checkpoint(Path(tmpdir))
            loaded = WorkflowState.load(Path(tmpdir))

            assert loaded is not None
            assert loaded.ended_early is not None
            assert (
                loaded.ended_early["reason"] == 'User said: "This is no longer needed"'
            )

    def test_ended_early_round_trip(self):
        """ended_early persists correctly through save/load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create state with ended_early
            state1 = WorkflowState(task_plan="Round trip test")
            state1.add_subtask("ST-001", "First")
            state1.add_subtask("ST-002", "Second")
            state1.mark_subtask_complete("ST-001")
            state1.mark_ended_early(
                reason="Test cancellation with: special chars", subtask_id="ST-002"
            )
            state1.save_checkpoint(Path(tmpdir))

            # Load and save again
            state2 = WorkflowState.load(Path(tmpdir))
            assert state2 is not None
            state2.save_checkpoint(Path(tmpdir))

            # Load final state
            state3 = WorkflowState.load(Path(tmpdir))
            assert state3 is not None

            # Verify all fields preserved
            assert state3.current_phase == WorkflowPhase.WONT_DO
            assert state3.ended_early is not None
            assert state3.ended_early["by_user"] is True
            assert state1.ended_early is not None
            assert state3.ended_early["reason"] == state1.ended_early["reason"]
            assert state3.ended_early["at_subtask_id"] == "ST-002"

    def test_state_without_ended_early(self):
        """State without ended_early loads correctly (backward compatibility)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create normal state without ended_early
            state = WorkflowState(task_plan="Normal workflow")
            state.add_subtask("ST-001", "First")
            state.set_phase(WorkflowPhase.IMPLEMENTATION)
            state.save_checkpoint(Path(tmpdir))

            # Verify no ended_early in saved file
            content = (Path(tmpdir) / ".map" / "progress.md").read_text()
            assert "ended_early:" not in content

            # Load and verify
            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded is not None
            assert loaded.current_phase == WorkflowPhase.IMPLEMENTATION
            assert loaded.ended_early is None

    def test_wont_do_phase_saves_and_loads(self):
        """WONT_DO phase can be saved and loaded directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="Test")
            state.set_phase(WorkflowPhase.WONT_DO)
            state.save_checkpoint(Path(tmpdir))

            loaded = WorkflowState.load(Path(tmpdir))
            assert loaded is not None
            assert loaded.current_phase == WorkflowPhase.WONT_DO


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

    def test_parse_empty_list_multiline(self):
        """Parse empty list in multi-line format (legacy)."""
        text = """completed_subtasks:
  []"""

        result = WorkflowState._parse_yaml_frontmatter(text)
        assert result["completed_subtasks"] == []

    def test_parse_empty_list_inline(self):
        """Parse empty list in inline format (new standard)."""
        text = """completed_subtasks: []"""

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
