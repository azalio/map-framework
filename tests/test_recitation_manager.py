"""
Tests for RecitationManager

Validates the Recitation pattern implementation for MAP Framework.
"""

import json
from pathlib import Path
import pytest
from mapify_cli.recitation_manager import RecitationManager, TaskPlan, Subtask


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
            'id': 1,
            'description': 'Create User model',
            'acceptance_criteria': 'Model validates email and hashes password',
            'estimated_complexity': 'low',
            'depends_on': []
        },
        {
            'id': 2,
            'description': 'Implement login endpoint',
            'acceptance_criteria': 'POST /auth/login returns JWT token',
            'estimated_complexity': 'medium',
            'depends_on': [1]
        },
        {
            'id': 3,
            'description': 'Add token validation',
            'acceptance_criteria': 'Middleware validates tokens',
            'estimated_complexity': 'low',
            'depends_on': [2]
        }
    ]


class TestRecitationManagerCreation:
    """Test plan creation functionality"""

    def test_create_plan(self, manager, sample_subtasks):
        """Test creating a new plan"""
        plan = manager.create_plan(
            task_id='feat_auth',
            goal='Implement JWT authentication',
            subtasks=sample_subtasks
        )

        assert plan.task_id == 'feat_auth'
        assert plan.goal == 'Implement JWT authentication'
        assert len(plan.subtasks) == 3
        assert plan.current_subtask_id == 1
        assert plan.subtasks[0].status == 'pending'

    def test_plan_files_created(self, manager, sample_subtasks):
        """Test that plan files are created"""
        manager.create_plan(
            task_id='test_task',
            goal='Test goal',
            subtasks=sample_subtasks
        )

        assert manager.plan_file.exists()
        assert manager.plan_json.exists()
        assert manager.map_dir.exists()

    def test_plan_json_structure(self, manager, sample_subtasks):
        """Test JSON plan structure"""
        manager.create_plan(
            task_id='test_task',
            goal='Test goal',
            subtasks=sample_subtasks
        )

        plan_data = json.loads(manager.plan_json.read_text())

        assert 'task_id' in plan_data
        assert 'goal' in plan_data
        assert 'subtasks' in plan_data
        assert 'current_subtask_id' in plan_data
        assert 'created_at' in plan_data
        assert 'updated_at' in plan_data

    def test_markdown_generated(self, manager, sample_subtasks):
        """Test that markdown is generated"""
        manager.create_plan(
            task_id='test_task',
            goal='Test goal',
            subtasks=sample_subtasks
        )

        md_content = manager.plan_file.read_text()

        assert '# Current Task: test_task' in md_content
        assert 'Test goal' in md_content
        assert 'Progress: 0/3' in md_content
        assert '☐' in md_content  # Pending marker

class TestSubtaskStatusUpdates:
    """Test subtask status update functionality"""

    def test_update_to_in_progress(self, manager, sample_subtasks):
        """Test updating subtask to in_progress"""
        manager.create_plan('test', 'Test', sample_subtasks)

        plan = manager.update_subtask_status(1, 'in_progress')

        assert plan.subtasks[0].status == 'in_progress'
        assert plan.subtasks[0].iterations == 1
        assert plan.current_subtask_id == 1

    def test_update_to_completed(self, manager, sample_subtasks):
        """Test updating subtask to completed"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(1, 'in_progress')

        plan = manager.update_subtask_status(1, 'completed')

        assert plan.subtasks[0].status == 'completed'

    def test_retry_increments_iterations(self, manager, sample_subtasks):
        """Test that retries increment iteration count"""
        manager.create_plan('test', 'Test', sample_subtasks)

        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'in_progress')  # Retry
        plan = manager.update_subtask_status(1, 'in_progress')  # Another retry

        assert plan.subtasks[0].iterations == 3

    def test_error_recording(self, manager, sample_subtasks):
        """Test that errors are recorded"""
        manager.create_plan('test', 'Test', sample_subtasks)

        manager.update_subtask_status(1, 'in_progress')
        plan = manager.update_subtask_status(
            1,
            'in_progress',
            error='Missing import for JWT library'
        )

        assert len(plan.subtasks[0].errors) == 1
        assert 'JWT library' in plan.subtasks[0].errors[0]

    def test_multiple_errors_recorded(self, manager, sample_subtasks):
        """Test that multiple errors are tracked"""
        manager.create_plan('test', 'Test', sample_subtasks)

        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'in_progress', error='Error 1')
        plan = manager.update_subtask_status(1, 'in_progress', error='Error 2')

        assert len(plan.subtasks[0].errors) == 2

    def test_progress_through_all_subtasks(self, manager, sample_subtasks):
        """Test progressing through all subtasks"""
        manager.create_plan('test', 'Test', sample_subtasks)

        # Complete subtask 1
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'completed')

        # Complete subtask 2
        manager.update_subtask_status(2, 'in_progress')
        manager.update_subtask_status(2, 'completed')

        # Start subtask 3
        plan = manager.update_subtask_status(3, 'in_progress')

        assert plan.subtasks[0].status == 'completed'
        assert plan.subtasks[1].status == 'completed'
        assert plan.subtasks[2].status == 'in_progress'
        assert plan.current_subtask_id == 3


class TestMarkdownGeneration:
    """Test markdown generation for recitation"""

    def test_pending_marker(self, manager, sample_subtasks):
        """Test that pending subtasks show ☐"""
        manager.create_plan('test', 'Test', sample_subtasks)

        md = manager.plan_file.read_text()
        assert '☐' in md

    def test_in_progress_marker(self, manager, sample_subtasks):
        """Test that in-progress subtasks show →"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(1, 'in_progress')

        md = manager.plan_file.read_text()
        assert '→' in md
        assert 'CURRENT' in md

    def test_completed_marker(self, manager, sample_subtasks):
        """Test that completed subtasks show ✓"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'completed')

        md = manager.plan_file.read_text()
        assert '✓' in md

    def test_current_focus_section(self, manager, sample_subtasks):
        """Test that current focus section is generated"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(2, 'in_progress')

        md = manager.plan_file.read_text()
        assert '## Current Focus' in md
        assert 'Subtask 2' in md
        assert 'Implement login endpoint' in md

    def test_acceptance_criteria_shown(self, manager, sample_subtasks):
        """Test that acceptance criteria is shown for current task"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(1, 'in_progress')

        md = manager.plan_file.read_text()
        assert 'Acceptance Criteria:' in md
        assert 'Model validates email' in md

    def test_complexity_shown(self, manager, sample_subtasks):
        """Test that complexity is shown"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(2, 'in_progress')

        md = manager.plan_file.read_text()
        assert 'Complexity:' in md
        assert 'medium' in md

    def test_retry_warning(self, manager, sample_subtasks):
        """Test that retry warning is shown"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'in_progress')  # Retry

        md = manager.plan_file.read_text()
        assert '⚠️' in md
        assert 'Retry attempt 2' in md

    def test_error_shown_in_markdown(self, manager, sample_subtasks):
        """Test that errors are shown in markdown"""
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(
            1,
            'in_progress',
            error='Test error message'
        )

        md = manager.plan_file.read_text()
        assert 'Test error' in md

    def test_progress_counter(self, manager, sample_subtasks):
        """Test that progress counter is accurate"""
        manager.create_plan('test', 'Test', sample_subtasks)

        # Initially 0/3
        md = manager.plan_file.read_text()
        assert 'Progress: 0/3' in md

        # Complete one
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'completed')
        md = manager.plan_file.read_text()
        assert 'Progress: 1/3' in md

        # Complete two
        manager.update_subtask_status(2, 'in_progress')
        manager.update_subtask_status(2, 'completed')
        md = manager.plan_file.read_text()
        assert 'Progress: 2/3' in md


class TestContextRetrieval:
    """Test getting context for recitation"""

    def test_get_current_context(self, manager, sample_subtasks):
        """Test getting current context"""
        manager.create_plan('test', 'Test', sample_subtasks)

        context = manager.get_current_context()

        assert isinstance(context, str)
        assert len(context) > 0
        assert '# Current Task:' in context

    def test_get_context_when_no_plan(self, manager):
        """Test getting context when no plan exists"""
        context = manager.get_current_context()

        assert context == ""

    def test_get_plan_object(self, manager, sample_subtasks):
        """Test getting plan object"""
        manager.create_plan('test', 'Test', sample_subtasks)

        plan = manager.get_plan()

        assert isinstance(plan, TaskPlan)
        assert plan.task_id == 'test'


class TestStatistics:
    """Test statistics API"""

    def test_statistics_structure(self, manager, sample_subtasks):
        """Test statistics dictionary structure"""
        manager.create_plan('test', 'Test', sample_subtasks)

        stats = manager.get_statistics()

        assert 'total_subtasks' in stats
        assert 'completed' in stats
        assert 'in_progress' in stats
        assert 'failed' in stats
        assert 'pending' in stats
        assert 'total_iterations' in stats
        assert 'current_subtask' in stats
        assert 'created_at' in stats
        assert 'updated_at' in stats

    def test_statistics_counts(self, manager, sample_subtasks):
        """Test that statistics counts are accurate"""
        manager.create_plan('test', 'Test', sample_subtasks)

        stats = manager.get_statistics()
        assert stats['total_subtasks'] == 3
        assert stats['pending'] == 3
        assert stats['completed'] == 0

        # Complete one
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'completed')

        stats = manager.get_statistics()
        assert stats['completed'] == 1
        assert stats['pending'] == 2

    def test_total_iterations(self, manager, sample_subtasks):
        """Test total iterations count"""
        manager.create_plan('test', 'Test', sample_subtasks)

        # First task: 2 iterations
        manager.update_subtask_status(1, 'in_progress')
        manager.update_subtask_status(1, 'in_progress')

        # Second task: 3 iterations
        manager.update_subtask_status(2, 'in_progress')
        manager.update_subtask_status(2, 'in_progress')
        manager.update_subtask_status(2, 'in_progress')

        stats = manager.get_statistics()
        assert stats['total_iterations'] == 5

    def test_statistics_when_no_plan(self, manager):
        """Test statistics when no plan exists"""
        stats = manager.get_statistics()

        assert stats == {}


class TestPlanClearing:
    """Test plan clearing functionality"""

    def test_clear_plan(self, manager, sample_subtasks):
        """Test clearing the plan"""
        manager.create_plan('test', 'Test', sample_subtasks)

        assert manager.plan_file.exists()
        assert manager.plan_json.exists()

        manager.clear_plan()

        assert not manager.plan_file.exists()
        assert not manager.plan_json.exists()

    def test_clear_when_no_plan(self, manager):
        """Test clearing when no plan exists (should not error)"""
        # Should not raise exception
        manager.clear_plan()


class TestPersistence:
    """Test plan persistence across manager instances"""

    def test_plan_persists(self, temp_project, sample_subtasks):
        """Test that plan persists across manager instances"""
        # Create plan with first manager
        manager1 = RecitationManager(temp_project)
        manager1.create_plan('test', 'Test', sample_subtasks)
        manager1.update_subtask_status(1, 'in_progress')

        # Load with second manager
        manager2 = RecitationManager(temp_project)
        plan = manager2.get_plan()

        assert plan is not None
        assert plan.task_id == 'test'
        assert plan.subtasks[0].status == 'in_progress'

    def test_statistics_after_reload(self, temp_project, sample_subtasks):
        """Test statistics work after reload"""
        manager1 = RecitationManager(temp_project)
        manager1.create_plan('test', 'Test', sample_subtasks)
        manager1.update_subtask_status(1, 'completed')

        manager2 = RecitationManager(temp_project)
        stats = manager2.get_statistics()

        assert stats['completed'] == 1


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_subtasks_list(self, manager):
        """Test creating plan with no subtasks"""
        plan = manager.create_plan('test', 'Test', [])

        assert plan.current_subtask_id is None
        assert len(plan.subtasks) == 0

    def test_update_nonexistent_subtask(self, manager, sample_subtasks):
        """Test updating a subtask that doesn't exist"""
        manager.create_plan('test', 'Test', sample_subtasks)

        # Should not raise error, but also shouldn't update anything
        plan = manager.update_subtask_status(999, 'completed')

        # No subtask should be completed
        assert all(st.status == 'pending' for st in plan.subtasks)

    def test_long_error_message(self, manager, sample_subtasks):
        """Test that long error messages are truncated in markdown"""
        manager.create_plan('test', 'Test', sample_subtasks)

        long_error = 'Error: ' + 'x' * 200
        manager.update_subtask_status(1, 'in_progress', error=long_error)

        md = manager.plan_file.read_text()
        # Check that error is truncated to ~100 chars
        assert 'xxx...' in md
        assert len(long_error) > 100

    def test_unicode_in_description(self, manager):
        """Test that unicode characters work in descriptions"""
        subtasks = [{
            'id': 1,
            'description': 'Добавить аутентификацию 🔐',
            'depends_on': []
        }]

        plan = manager.create_plan('test', 'Test 测试', subtasks)
        md = manager.get_current_context()

        assert 'Добавить' in md
        assert '🔐' in md
        assert '测试' in md


class TestRecitationPattern:
    """Integration tests for the recitation pattern"""

    def test_full_workflow(self, manager, sample_subtasks):
        """Test a complete workflow with recitation"""
        # Create plan
        manager.create_plan(
            'feat_auth',
            'Implement authentication',
            sample_subtasks
        )

        # Simulate Actor working on subtask 1
        manager.update_subtask_status(1, 'in_progress')
        context1 = manager.get_current_context()
        assert '→' in context1
        assert 'Subtask 1' in context1

        # Monitor approves, complete subtask 1
        manager.update_subtask_status(1, 'completed')

        # Actor starts subtask 2
        manager.update_subtask_status(2, 'in_progress')
        context2 = manager.get_current_context()
        assert '✓' in context2  # Subtask 1 completed
        assert '→' in context2  # Subtask 2 in progress
        assert 'Subtask 2' in context2

        # Monitor rejects, Actor retries
        manager.update_subtask_status(2, 'in_progress', error='Missing validation')
        context3 = manager.get_current_context()
        assert 'Retry attempt 2' in context3
        assert 'Missing validation' in context3

        # Second attempt succeeds
        manager.update_subtask_status(2, 'completed')

        # Final statistics
        stats = manager.get_statistics()
        assert stats['completed'] == 2
        assert stats['total_iterations'] == 3  # 1 + 2

    def test_context_grows_appropriately(self, manager):
        """Test that context size doesn't explode with many subtasks"""
        # Create plan with 10 subtasks
        many_subtasks = [
            {
                'id': i,
                'description': f'Task {i}',
                'depends_on': []
            }
            for i in range(1, 11)
        ]

        manager.create_plan('test', 'Test', many_subtasks)

        context = manager.get_current_context()

        # Context should be reasonable size (~30-50 lines for 10 tasks)
        line_count = len(context.split('\n'))
        assert 20 < line_count < 80  # Reasonable bounds

    def test_recitation_improves_focus(self, manager, sample_subtasks):
        """
        Conceptual test: Demonstrate how recitation keeps goals fresh.

        In actual use, this would be an A/B test showing that Actor with
        recitation has higher success rate than without.
        """
        manager.create_plan('test', 'Test', sample_subtasks)
        manager.update_subtask_status(2, 'in_progress')

        context = manager.get_current_context()

        # Key elements that keep model focused:
        assert '## Current Focus' in context  # Clear current objective
        assert 'Subtask 2' in context  # Which subtask we're on
        assert 'Progress: 0/3' in context  # Where we are overall
        assert 'Implement login endpoint' in context  # Specific task

        # All of these are in recent tokens → high attention weight


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
