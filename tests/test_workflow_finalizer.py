"""
Unit tests for src/mapify_cli/workflow_finalizer.py.
Tests all validation criteria from ST-006.
"""

import tempfile
from pathlib import Path

from mapify_cli.workflow_finalizer import finalize_workflow
from mapify_cli.workflow_state import WorkflowPhase, WorkflowState

# =============================================================================
# Validation Criteria Tests (ST-006)
# =============================================================================


class TestValidationCriteria:
    """Tests for the validation criteria from ST-006."""

    def test_criterion_1_sets_pending_to_wont_do(self):
        """VC1: finalize_workflow() sets all pending subtasks to won't_do status."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Pending subtask 1")
        state.add_subtask("ST-002", "Pending subtask 2")
        state.add_subtask("ST-003", "Pending subtask 3")

        # Verify initial state
        assert all(st.status == "pending" for st in state.subtasks)

        # Finalize workflow
        result = finalize_workflow(state, reason="User cancelled")

        # All pending subtasks should be won't_do
        assert all(st.status == "won't_do" for st in result.subtasks)

    def test_criterion_2_sets_in_progress_to_wont_do(self):
        """VC2: finalize_workflow() sets all in_progress subtasks to won't_do status."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "In progress subtask")
        state.add_subtask("ST-002", "Another in progress")
        state.mark_subtask_in_progress("ST-001")
        state.mark_subtask_in_progress("ST-002")

        # Verify initial state
        assert all(st.status == "in_progress" for st in state.subtasks)

        # Finalize workflow
        result = finalize_workflow(state, reason="Project cancelled")

        # All in_progress subtasks should be won't_do
        assert all(st.status == "won't_do" for st in result.subtasks)

    def test_criterion_3_preserves_complete_status(self):
        """VC3: finalize_workflow() preserves complete subtask statuses."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Completed subtask")
        state.add_subtask("ST-002", "Pending subtask")
        state.mark_subtask_complete("ST-001")

        # Verify initial state
        assert state.subtasks[0].status == "complete"
        assert state.subtasks[1].status == "pending"

        # Finalize workflow
        result = finalize_workflow(state, reason="Requirements changed")

        # Complete status preserved, pending changed to won't_do
        assert result.subtasks[0].status == "complete"
        assert result.subtasks[1].status == "won't_do"

    def test_criterion_3_preserves_failed_status(self):
        """VC3: finalize_workflow() preserves failed subtask statuses."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Failed subtask")
        state.add_subtask("ST-002", "Pending subtask")

        # Manually set failed status (no mark_subtask_failed method exists)
        state.subtasks[0].status = "failed"

        # Verify initial state
        assert state.subtasks[0].status == "failed"
        assert state.subtasks[1].status == "pending"

        # Finalize workflow
        result = finalize_workflow(state, reason="Blocking issue")

        # Failed status preserved, pending changed to won't_do
        assert result.subtasks[0].status == "failed"
        assert result.subtasks[1].status == "won't_do"

    def test_criterion_4_calls_mark_ended_early(self):
        """VC4: finalize_workflow() calls state.mark_ended_early with correct reason."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Subtask")

        result = finalize_workflow(state, reason="Custom termination reason")

        # Verify mark_ended_early was called correctly
        assert result.current_phase == WorkflowPhase.WONT_DO
        assert result.ended_early is not None
        assert result.ended_early["reason"] == "Custom termination reason"
        assert result.ended_early["by_user"] is True


# =============================================================================
# Contract Tests (ST-006)
# =============================================================================


class TestContracts:
    """Tests for postcondition contracts from ST-006."""

    def test_postcondition_pending_becomes_wont_do(self):
        """Postcondition: subtask.status == 'won't_do' WHEN original_status == 'pending'."""
        state = WorkflowState(task_plan="Test")
        state.add_subtask("ST-001", "Pending task")

        assert state.subtasks[0].status == "pending"

        result = finalize_workflow(state, reason="Test")

        assert result.subtasks[0].status == "won't_do"

    def test_postcondition_in_progress_becomes_wont_do(self):
        """Postcondition: subtask.status == 'won't_do' WHEN original_status == 'in_progress'."""
        state = WorkflowState(task_plan="Test")
        state.add_subtask("ST-001", "Active task")
        state.mark_subtask_in_progress("ST-001")

        assert state.subtasks[0].status == "in_progress"

        result = finalize_workflow(state, reason="Test")

        assert result.subtasks[0].status == "won't_do"

    def test_postcondition_terminal_status_wont_do(self):
        """Postcondition: state.current_phase == WorkflowPhase.WONT_DO AFTER finalize_workflow."""
        state = WorkflowState(task_plan="Test")
        state.set_phase(WorkflowPhase.IMPLEMENTATION)

        result = finalize_workflow(state, reason="Test")

        assert result.current_phase == WorkflowPhase.WONT_DO


# =============================================================================
# Active Subtask Detection Tests
# =============================================================================


class TestActiveSubtaskDetection:
    """Test that finalize_workflow correctly identifies the active subtask."""

    def test_finds_in_progress_subtask(self):
        """Should identify in_progress subtask as active."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Completed")
        state.add_subtask("ST-002", "In progress")
        state.add_subtask("ST-003", "Pending")

        state.mark_subtask_complete("ST-001")
        state.mark_subtask_in_progress("ST-002")

        result = finalize_workflow(state, reason="Cancellation")

        # Should identify ST-002 as active
        assert result.ended_early is not None
        assert result.ended_early["at_subtask_id"] == "ST-002"

    def test_no_active_subtask_when_all_pending(self):
        """Should return empty string when no subtask is in_progress."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "Pending 1")
        state.add_subtask("ST-002", "Pending 2")

        result = finalize_workflow(state, reason="Early termination")

        # No active subtask, should be None
        assert result.ended_early is not None
        assert result.ended_early["at_subtask_id"] is None

    def test_first_in_progress_selected_when_multiple(self):
        """Should select first in_progress subtask if multiple exist."""
        state = WorkflowState(task_plan="Test task")
        state.add_subtask("ST-001", "First active")
        state.add_subtask("ST-002", "Second active")

        state.mark_subtask_in_progress("ST-001")
        state.mark_subtask_in_progress("ST-002")

        result = finalize_workflow(state, reason="Test")

        # Should select first in_progress subtask
        assert result.ended_early is not None
        assert result.ended_early["at_subtask_id"] == "ST-001"


# =============================================================================
# Mixed Status Tests
# =============================================================================


class TestMixedSubtaskStatuses:
    """Test finalize_workflow with various combinations of subtask statuses."""

    def test_mixed_statuses_transitions_correctly(self):
        """Test with complete, in_progress, and pending subtasks."""
        state = WorkflowState(task_plan="Complex workflow")
        state.add_subtask("ST-001", "Already complete")
        state.add_subtask("ST-002", "Currently active")
        state.add_subtask("ST-003", "Not started")
        state.add_subtask("ST-004", "Also not started")

        state.mark_subtask_complete("ST-001")
        state.mark_subtask_in_progress("ST-002")
        # ST-003 and ST-004 remain pending

        result = finalize_workflow(state, reason="Project pivot")

        # Verify each subtask's final status
        assert result.subtasks[0].status == "complete"  # ST-001 preserved
        assert result.subtasks[1].status == "won't_do"  # ST-002 transitioned
        assert result.subtasks[2].status == "won't_do"  # ST-003 transitioned
        assert result.subtasks[3].status == "won't_do"  # ST-004 transitioned

    def test_all_complete_subtasks_preserved(self):
        """Test that all-complete workflow doesn't change subtask statuses."""
        state = WorkflowState(task_plan="Completed workflow")
        state.add_subtask("ST-001", "Done")
        state.add_subtask("ST-002", "Also done")

        state.mark_subtask_complete("ST-001")
        state.mark_subtask_complete("ST-002")

        result = finalize_workflow(state, reason="Post-completion cleanup")

        # All subtasks remain complete
        assert all(st.status == "complete" for st in result.subtasks)
        # But workflow is still marked as won't_do (ended early)
        assert result.current_phase == WorkflowPhase.WONT_DO

    def test_empty_subtasks_list(self):
        """Test finalize_workflow with no subtasks."""
        state = WorkflowState(task_plan="Empty workflow")

        result = finalize_workflow(state, reason="No work to do")

        assert result.subtasks == []
        assert result.current_phase == WorkflowPhase.WONT_DO
        assert result.ended_early is not None
        assert result.ended_early["at_subtask_id"] is None


# =============================================================================
# Reason String Tests
# =============================================================================


class TestReasonHandling:
    """Test that reason strings are handled correctly."""

    def test_simple_reason_string(self):
        """Test simple reason string."""
        state = WorkflowState(task_plan="Test")
        state.add_subtask("ST-001", "Task")

        result = finalize_workflow(state, reason="User cancelled workflow")

        assert result.ended_early is not None
        assert result.ended_early["reason"] == "User cancelled workflow"

    def test_reason_with_special_characters(self):
        """Test reason with quotes, colons, and other special characters."""
        state = WorkflowState(task_plan="Test")
        state.add_subtask("ST-001", "Task")

        special_reason = 'Requirements changed: feature "X" no longer needed'
        result = finalize_workflow(state, reason=special_reason)

        assert result.ended_early is not None
        assert result.ended_early["reason"] == special_reason

    def test_empty_reason_string(self):
        """Test with empty reason string."""
        state = WorkflowState(task_plan="Test")
        state.add_subtask("ST-001", "Task")

        result = finalize_workflow(state, reason="")

        assert result.ended_early is not None
        assert result.ended_early["reason"] == ""


# =============================================================================
# Integration Tests (with save_checkpoint)
# =============================================================================


class TestIntegrationWithCheckpoint:
    """Integration tests: finalize_workflow → save_checkpoint → load."""

    def test_finalized_state_saves_and_loads_correctly(self):
        """Test that finalized state persists through save/load cycle."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and finalize workflow
            state = WorkflowState(task_plan="Integration test")
            state.add_subtask("ST-001", "Complete task")
            state.add_subtask("ST-002", "Active task")
            state.add_subtask("ST-003", "Pending task")

            state.mark_subtask_complete("ST-001")
            state.mark_subtask_in_progress("ST-002")

            finalized = finalize_workflow(state, reason="Testing save/load integration")

            # Save checkpoint
            finalized.save_checkpoint(Path(tmpdir))

            # Load and verify
            loaded = WorkflowState.load(Path(tmpdir))

            assert loaded is not None
            assert loaded.current_phase == WorkflowPhase.WONT_DO
            assert loaded.subtasks[0].status == "complete"
            assert loaded.subtasks[1].status == "won't_do"
            assert loaded.subtasks[2].status == "won't_do"
            assert loaded.ended_early is not None
            assert loaded.ended_early["reason"] == "Testing save/load integration"
            assert loaded.ended_early["at_subtask_id"] == "ST-002"

    def test_checkpoint_file_valid_yaml_format(self):
        """Test that checkpoint file has valid YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(task_plan="YAML test")
            state.add_subtask("ST-001", "Task")
            state.mark_subtask_in_progress("ST-001")

            finalized = finalize_workflow(state, reason="YAML validation")
            checkpoint_path = finalized.save_checkpoint(Path(tmpdir))

            content = checkpoint_path.read_text()

            # Check YAML structure
            assert content.startswith("---\n")
            assert "\n---" in content

            # Check won't_do phase is written
            assert "current_phase: won't_do" in content

            # Check ended_early section
            assert "ended_early:" in content
            assert "by_user: true" in content
            assert "reason:" in content
            assert "YAML validation" in content
            assert "at_subtask_id: ST-001" in content

    def test_multiple_finalize_calls_idempotent(self):
        """Test that calling finalize_workflow multiple times is safe."""
        state = WorkflowState(task_plan="Idempotency test")
        state.add_subtask("ST-001", "Task 1")
        state.add_subtask("ST-002", "Task 2")
        state.mark_subtask_in_progress("ST-001")

        # First finalization
        result1 = finalize_workflow(state, reason="First call")

        # Second finalization (on already-finalized state)
        result2 = finalize_workflow(result1, reason="Second call")

        # Status should remain won't_do
        assert all(st.status == "won't_do" for st in result2.subtasks)
        assert result2.current_phase == WorkflowPhase.WONT_DO

        # Reason should be updated to latest
        assert result2.ended_early is not None
        assert result2.ended_early["reason"] == "Second call"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_large_number_of_subtasks(self):
        """Test finalize_workflow with many subtasks."""
        state = WorkflowState(task_plan="Large workflow")

        # Add 100 subtasks
        for i in range(100):
            state.add_subtask(f"ST-{i:03d}", f"Subtask {i}")

        # Mark some as complete, some in progress
        for i in range(20):
            state.mark_subtask_complete(f"ST-{i:03d}")
        for i in range(20, 25):
            state.mark_subtask_in_progress(f"ST-{i:03d}")

        result = finalize_workflow(state, reason="Cleanup large workflow")

        # Verify counts
        complete_count = sum(1 for st in result.subtasks if st.status == "complete")
        wont_do_count = sum(1 for st in result.subtasks if st.status == "won't_do")

        assert complete_count == 20  # Preserved
        assert wont_do_count == 80  # Transitioned (75 pending + 5 in_progress)

    def test_subtask_with_completed_at_timestamp(self):
        """Test that completed_at timestamp is preserved for complete subtasks."""
        state = WorkflowState(task_plan="Timestamp test")
        state.add_subtask("ST-001", "Completed task")
        state.mark_subtask_complete("ST-001")

        original_completed_at = state.subtasks[0].completed_at

        result = finalize_workflow(state, reason="Test")

        # Timestamp should be preserved
        assert result.subtasks[0].completed_at == original_completed_at

    def test_return_value_is_same_state_object(self):
        """Test that finalize_workflow returns the same state object (mutated)."""
        state = WorkflowState(task_plan="Mutation test")
        state.add_subtask("ST-001", "Task")

        result = finalize_workflow(state, reason="Test")

        # Should be the same object (mutated in place)
        assert result is state
