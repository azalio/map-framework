"""
Test cases for incomplete plan scenarios

This module tests the behavior when a plan is not closed (incomplete subtasks).
It covers:
1. Commands behavior with incomplete plans (get-context, stats, update)
2. Creating new plans when one already exists
3. Commands behavior when no plan exists
4. Edge cases around plan lifecycle

Findings:
- CLI gracefully handles get-context and stats with incomplete plans
- Creating a new plan OVERWRITES existing plan without warning (potential issue)
- CLI crashes when updating non-existent plan (BUG)
- get-context returns exit code 1 when no plan exists (expected)
- stats returns exit code 1 when no plan exists (expected)
"""

import json
import subprocess
from pathlib import Path

import pytest

from mapify_cli.recitation_manager import RecitationManager


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def manager(temp_project):
    """Create a RecitationManager instance"""
    return RecitationManager(temp_project)


@pytest.fixture
def sample_subtasks():
    """Sample subtasks for testing"""
    return [
        {
            "id": 1,
            "description": "Create User model",
            "acceptance_criteria": "Model validates email",
            "estimated_complexity": "low",
            "depends_on": [],
        },
        {
            "id": 2,
            "description": "Implement login endpoint",
            "acceptance_criteria": "POST /auth/login returns JWT",
            "estimated_complexity": "medium",
            "depends_on": [1],
        },
        {
            "id": 3,
            "description": "Add token validation",
            "acceptance_criteria": "Middleware validates tokens",
            "estimated_complexity": "low",
            "depends_on": [2],
        },
    ]


class TestIncompletePlanBehavior:
    """Test behavior when plan exists with incomplete subtasks"""

    def test_get_context_with_incomplete_plan(self, manager, sample_subtasks):
        """Test get-context returns valid content when plan has pending subtasks"""
        # Create plan
        manager.create_plan("feat_test", "Test feature", sample_subtasks)

        # Mark one as in progress but don't complete all
        manager.update_subtask_status(1, "in_progress")

        # get_current_context should work fine
        context = manager.get_current_context()

        assert context != ""
        assert "# Current Task:" in context
        assert "Progress: 0/3" in context
        assert "→" in context  # in_progress marker
        assert "☐" in context  # pending marker

    def test_stats_with_incomplete_plan(self, manager, sample_subtasks):
        """Test stats returns valid data when plan has pending subtasks"""
        manager.create_plan("feat_test", "Test feature", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        stats = manager.get_statistics()

        assert stats is not None
        assert stats["total_subtasks"] == 3
        assert stats["completed"] == 0
        assert stats["in_progress"] == 1
        assert stats["pending"] == 2

    def test_update_with_incomplete_plan(self, manager, sample_subtasks):
        """Test updating subtask status works with incomplete plan"""
        manager.create_plan("feat_test", "Test feature", sample_subtasks)

        # Start first task
        manager.update_subtask_status(1, "in_progress")

        # Complete first task while others are pending
        plan = manager.update_subtask_status(1, "completed")

        assert plan.subtasks[0].status == "completed"
        assert plan.subtasks[1].status == "pending"
        assert plan.subtasks[2].status == "pending"

    def test_partial_completion_context(self, manager, sample_subtasks):
        """Test context shows correct state with partially completed plan"""
        manager.create_plan("feat_test", "Test feature", sample_subtasks)

        # Complete first task
        manager.update_subtask_status(1, "in_progress")
        manager.update_subtask_status(1, "completed")

        # Start second task
        manager.update_subtask_status(2, "in_progress")

        context = manager.get_current_context()

        assert "✓" in context  # completed marker
        assert "→" in context  # in_progress marker
        assert "☐" in context  # pending marker
        assert "Progress: 1/3" in context

    def test_retry_with_incomplete_plan(self, manager, sample_subtasks):
        """Test that retries work correctly with incomplete plan"""
        manager.create_plan("feat_test", "Test feature", sample_subtasks)

        # Start and retry first task multiple times
        manager.update_subtask_status(1, "in_progress")
        manager.update_subtask_status(1, "in_progress", error="First error")
        plan = manager.update_subtask_status(1, "in_progress", error="Second error")

        assert plan.subtasks[0].iterations == 3
        assert len(plan.subtasks[0].errors) == 2

        # Other tasks still pending
        assert plan.subtasks[1].status == "pending"
        assert plan.subtasks[2].status == "pending"


class TestCreatePlanWhenPlanExists:
    """Test behavior when creating a new plan while one exists"""

    def test_create_overwrites_existing_plan(self, manager, sample_subtasks):
        """Test that creating new plan with force=True overwrites existing incomplete plan"""
        # Create first plan
        plan1 = manager.create_plan("feat_auth", "Auth feature", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        # Create second plan with force=True - should overwrite
        new_subtasks = [{"id": 1, "description": "New task", "depends_on": []}]
        plan2 = manager.create_plan("feat_new", "New feature", new_subtasks, force=True)

        # Verify new plan replaced old one
        loaded_plan = manager.get_plan()
        assert loaded_plan.task_id == "feat_new"
        assert loaded_plan.goal == "New feature"
        assert len(loaded_plan.subtasks) == 1

        # Old plan data is gone
        assert loaded_plan.task_id != "feat_auth"

    def test_create_loses_progress_of_incomplete_plan(self, manager, sample_subtasks):
        """Test that creating new plan with force=True loses all progress from incomplete plan"""
        # Create plan and make progress
        manager.create_plan("feat_test", "Test", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")
        manager.update_subtask_status(1, "completed")
        manager.update_subtask_status(2, "in_progress")

        stats_before = manager.get_statistics()
        assert stats_before["completed"] == 1
        assert stats_before["total_iterations"] == 2

        # Create new plan with force=True
        new_subtasks = [{"id": 1, "description": "Brand new task", "depends_on": []}]
        manager.create_plan("feat_new", "New", new_subtasks, force=True)

        # All old progress is lost
        stats_after = manager.get_statistics()
        assert stats_after["completed"] == 0
        assert stats_after["total_iterations"] == 0
        assert stats_after["total_subtasks"] == 1

    def test_overwrite_requires_force_flag(self, manager, sample_subtasks):
        """Document that overwriting plans now requires force flag (BUG FIXED)"""
        # This test documents NEW correct behavior (prevents accidental data loss)
        manager.create_plan("feat_old", "Old", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        # Exception raised when overwriting without force
        with pytest.raises(ValueError, match="A plan already exists"):
            manager.create_plan("feat_new", "New", sample_subtasks)

        # Old plan still exists
        plan = manager.get_plan()
        assert plan.task_id == "feat_old"

        # With force=True, overwrite succeeds
        manager.create_plan("feat_new", "New", sample_subtasks, force=True)
        plan = manager.get_plan()
        assert plan.task_id == "feat_new"


class TestNoPlanExists:
    """Test behavior when no plan file exists"""

    def test_get_context_when_no_plan(self, manager):
        """Test get_current_context returns empty string when no plan"""
        context = manager.get_current_context()

        assert context == ""

    def test_get_plan_when_no_plan(self, manager):
        """Test get_plan returns None when no plan exists"""
        plan = manager.get_plan()

        assert plan is None

    def test_stats_when_no_plan(self, manager):
        """Test get_statistics returns empty dict when no plan exists"""
        stats = manager.get_statistics()

        assert stats == {}

    def test_update_when_no_plan_raises_error(self, manager):
        """Test updating subtask when no plan exists raises clear error"""
        # BUG FIXED: Now raises ValueError with helpful message instead of AttributeError
        with pytest.raises(ValueError, match="No active plan exists"):
            manager.update_subtask_status(1, "completed")

    def test_clear_when_no_plan_succeeds(self, manager):
        """Test clearing non-existent plan doesn't raise error"""
        # Should be idempotent
        manager.clear_plan()

        # No exception raised


class TestCLIBehaviorWithIncompletePlan:
    """Test CLI commands with incomplete plans"""

    def test_cli_get_context_incomplete_plan(self, temp_project, sample_subtasks):
        """Test CLI get-context command with incomplete plan"""
        manager = RecitationManager(temp_project)
        manager.create_plan("feat_test", "Test", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        result = subprocess.run(
            ["python", "-m", "mapify_cli.recitation_manager", "get-context"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "# Current Task:" in result.stdout
        assert "Progress: 0/3" in result.stdout

    def test_cli_stats_incomplete_plan(self, temp_project, sample_subtasks):
        """Test CLI stats command with incomplete plan"""
        manager = RecitationManager(temp_project)
        manager.create_plan("feat_test", "Test", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        result = subprocess.run(
            ["python", "-m", "mapify_cli.recitation_manager", "stats"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        stats = json.loads(result.stdout)
        assert stats["total_subtasks"] == 3
        assert stats["in_progress"] == 1

    def test_cli_update_incomplete_plan(self, temp_project, sample_subtasks):
        """Test CLI update command with incomplete plan"""
        manager = RecitationManager(temp_project)
        manager.create_plan("feat_test", "Test", sample_subtasks)

        result = subprocess.run(
            [
                "python",
                "-m",
                "mapify_cli.recitation_manager",
                "update",
                "1",
                "in_progress",
            ],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["status"] == "success"


class TestCLIBehaviorWithNoPlan:
    """Test CLI commands when no plan exists"""

    def test_cli_get_context_no_plan(self, temp_project):
        """Test CLI get-context when no plan exists"""
        result = subprocess.run(
            ["python", "-m", "mapify_cli.recitation_manager", "get-context"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "No active plan" in result.stdout

    def test_cli_stats_no_plan(self, temp_project):
        """Test CLI stats when no plan exists"""
        result = subprocess.run(
            ["python", "-m", "mapify_cli.recitation_manager", "stats"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        response = json.loads(result.stdout)
        assert response["status"] == "error"
        assert "No active plan" in response["message"]

    def test_cli_update_no_plan_crashes(self, temp_project):
        """Test CLI update when no plan exists - DOCUMENTS BUG"""
        result = subprocess.run(
            [
                "python",
                "-m",
                "mapify_cli.recitation_manager",
                "update",
                "1",
                "completed",
            ],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        # BUG: CLI should return graceful error, not crash
        assert result.returncode == 1
        response = json.loads(result.stdout)
        assert response["status"] == "error"
        # Error message contains Python exception - not user-friendly
        assert (
            "NoneType" in response["message"] or "No active plan" in response["message"]
        )

    def test_cli_clear_no_plan_succeeds(self, temp_project):
        """Test CLI clear when no plan exists"""
        result = subprocess.run(
            ["python", "-m", "mapify_cli.recitation_manager", "clear"],
            cwd=temp_project,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        response = json.loads(result.stdout)
        assert response["status"] == "success"


class TestClosedFeatureDefinition:
    """Test and document what 'closed feature' means"""

    def test_closed_means_all_subtasks_completed(self, manager, sample_subtasks):
        """Define: Feature is 'closed' when all subtasks are completed"""
        manager.create_plan("feat_test", "Test", sample_subtasks)

        # Not closed: some pending
        stats = manager.get_statistics()
        assert stats["completed"] < stats["total_subtasks"]

        # Complete all subtasks
        for i in [1, 2, 3]:
            manager.update_subtask_status(i, "in_progress")
            manager.update_subtask_status(i, "completed")

        # Now closed: all completed
        stats = manager.get_statistics()
        assert stats["completed"] == stats["total_subtasks"]

    def test_closed_means_explicitly_cleared(self, manager, sample_subtasks):
        """Define: Feature is also 'closed' when plan is explicitly cleared"""
        manager.create_plan("feat_test", "Test", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        # Plan exists
        assert manager.get_plan() is not None

        # Explicitly clear (close) the plan
        manager.clear_plan()

        # Plan is closed (doesn't exist)
        assert manager.get_plan() is None
        assert manager.get_current_context() == ""

    def test_two_definitions_of_closed(self, manager, sample_subtasks):
        """Document that 'closed' has two meanings"""
        # Meaning 1: All subtasks done (plan still exists but work is complete)
        manager.create_plan("feat_test", "Test", sample_subtasks)
        for i in [1, 2, 3]:
            manager.update_subtask_status(i, "in_progress")
            manager.update_subtask_status(i, "completed")

        stats = manager.get_statistics()
        is_work_complete = stats["completed"] == stats["total_subtasks"]
        plan_exists = manager.get_plan() is not None

        assert is_work_complete  # Work complete
        assert plan_exists  # But plan still exists

        # Meaning 2: Plan explicitly cleared (plan doesn't exist)
        manager.clear_plan()
        plan_exists_after_clear = manager.get_plan() is not None

        assert not plan_exists_after_clear  # Plan is gone


class TestForceFlagBehavior:
    """Test force flag behavior when creating plans"""

    def test_create_with_force_overwrites_existing(self, manager, sample_subtasks):
        """Test create with force=True overwrites existing plan"""
        # Create first plan and make progress
        manager.create_plan("feat_old", "Old Goal", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        # Verify first plan exists
        plan1 = manager.get_plan()
        assert plan1.task_id == "feat_old"

        # Create second plan with force=True (should overwrite)
        new_subtasks = [{"id": 1, "description": "New task", "depends_on": []}]
        plan2 = manager.create_plan("feat_new", "New Goal", new_subtasks, force=True)

        # Verify second plan replaced first
        assert plan2.task_id == "feat_new"
        assert plan2.goal == "New Goal"

        # Verify only second plan exists
        loaded_plan = manager.get_plan()
        assert loaded_plan.task_id == "feat_new"
        assert loaded_plan.goal == "New Goal"
        assert len(loaded_plan.subtasks) == 1

    def test_create_without_force_raises_error(self, manager, sample_subtasks):
        """Test create without force raises clear error when plan exists"""
        # Create first plan
        manager.create_plan("feat_old", "Old Goal", sample_subtasks)

        # Try to create second plan without force (should fail)
        new_subtasks = [{"id": 1, "description": "New task", "depends_on": []}]
        with pytest.raises(ValueError, match="A plan already exists"):
            manager.create_plan("feat_new", "New Goal", new_subtasks, force=False)

        # Verify first plan still exists
        plan = manager.get_plan()
        assert plan.task_id == "feat_old"

    def test_force_flag_works_when_no_plan_exists(self, manager, sample_subtasks):
        """Test that force=True works correctly when no plan exists"""
        # Verify no plan exists
        assert manager.get_plan() is None

        # Create plan with force=True when no existing plan
        plan = manager.create_plan(
            "feat_test", "Test Goal", sample_subtasks, force=True
        )

        # Should succeed normally
        assert plan.task_id == "feat_test"
        assert plan.goal == "Test Goal"
        assert len(plan.subtasks) == 3
        assert manager.plan_json.exists()


class TestExpectedWorkflow:
    """Test expected workflow patterns"""

    def test_typical_workflow_complete_all_then_clear(self, manager, sample_subtasks):
        """Document typical workflow: complete all subtasks then clear"""
        # 1. Create plan
        manager.create_plan("feat_test", "Test", sample_subtasks)

        # 2. Complete all subtasks
        for i in [1, 2, 3]:
            manager.update_subtask_status(i, "in_progress")
            manager.update_subtask_status(i, "completed")

        # 3. Get final stats
        stats = manager.get_statistics()
        assert stats["completed"] == 3

        # 4. Clear plan when done
        manager.clear_plan()

        # 5. Ready for next feature
        assert manager.get_plan() is None

    def test_abandoned_workflow_incomplete_then_new_plan(
        self, manager, sample_subtasks
    ):
        """Document workflow: abandon incomplete plan by starting new one with force"""
        # Start first feature
        manager.create_plan("feat_old", "Old feature", sample_subtasks)
        manager.update_subtask_status(1, "in_progress")

        # User decides to abandon and start new feature (requires force)
        new_subtasks = [{"id": 1, "description": "New task", "depends_on": []}]
        manager.create_plan("feat_new", "New feature", new_subtasks, force=True)

        # Old plan is gone (implicitly closed by overwrite)
        plan = manager.get_plan()
        assert plan.task_id == "feat_new"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
