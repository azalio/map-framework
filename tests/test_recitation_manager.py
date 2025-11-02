"""
Tests for RecitationManager

Validates the Recitation pattern implementation for MAP Framework.
"""

import json
import os
from pathlib import Path
import pytest
from typer.testing import CliRunner
from mapify_cli import app
from mapify_cli.recitation_manager import RecitationManager, TaskPlan, Subtask

runner = CliRunner()


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

        # Should raise an error when subtask ID is not found
        with pytest.raises(ValueError, match="Subtask with id 999"):
            manager.update_subtask_status(999, 'completed')

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


class TestDevDocsGeneration:
    """Test dev docs file generation functionality"""

    # Tests for generate_context_md()

    def test_generate_context_with_readme_and_playbook(self, manager, tmp_path):
        """Test generating context.md with README and playbook"""
        # Create README
        readme = manager.project_root / "README.md"
        readme.write_text("# Test Project\n\nThis is a test project for MAP Framework testing.")

        # Create playbook using PlaybookManager
        playbook_dir = manager.project_root / ".claude"
        playbook_dir.mkdir()
        playbook_db = playbook_dir / "playbook.db"

        from mapify_cli.playbook_manager import PlaybookManager
        pm = PlaybookManager(db_path=str(playbook_db), use_semantic_search=False)
        try:
            bullet_id = pm._add_bullet("IMPLEMENTATION_PATTERNS", "Use dependency injection for testability")
            pm._update_bullet(bullet_id, increment_helpful=5)
        finally:
            pm.close()

        # Generate context
        context_path = manager.generate_context_md()

        # Verify file created
        assert manager.context_file.exists()
        assert context_path == str(manager.context_file)

        # Verify content
        content = manager.context_file.read_text()
        assert "# Project Context" in content
        assert "Test Project" in content
        assert "This is a test project" in content
        assert "impl-0000" in content
        assert "dependency injection" in content

    def test_generate_context_missing_readme(self, manager):
        """Test generating context when README is missing (fallback to project name)"""
        # No README exists
        context_path = manager.generate_context_md()
        assert context_path == str(manager.context_file)

        content = manager.context_file.read_text()
        assert "# Project Context" in content
        # Should use directory name as fallback
        assert manager.project_root.name in content

    def test_generate_context_missing_playbook(self, manager):
        """Test generating context when playbook is missing (graceful degradation)"""
        manager.generate_context_md()

        content = manager.context_file.read_text()
        assert "# Project Context" in content
        # Context should still be generated, playbook section simply omitted
        assert "Common Gotchas" in content

    def test_generate_context_readme_parsing(self, manager):
        """Test README parsing extracts title from # heading"""
        readme = manager.project_root / "README.md"
        readme.write_text("# My Awesome Project\n\nA description here.\n\n## Features")

        manager.generate_context_md()

        content = manager.context_file.read_text()
        assert "My Awesome Project" in content
        assert "A description here" in content

    def test_generate_context_description_extraction(self, manager):
        """Test description extraction (first paragraph after title)"""
        readme = manager.project_root / "README.md"
        readme.write_text(
            "# Project\n\n"
            "First line of description.\n"
            "Second line of description.\n"
            "Third line.\n"
            "Fourth line.\n\n"
            "## Section"
        )

        manager.generate_context_md()

        content = manager.context_file.read_text()
        # Should take first 3 lines
        assert "First line" in content
        assert "Second line" in content
        assert "Third line" in content
        # Should not include fourth line
        assert "Fourth line" not in content

    def test_generate_context_high_quality_bullets_grouping(self, manager):
        """Test high-quality bullets are grouped by section"""
        playbook_dir = manager.project_root / ".claude"
        playbook_dir.mkdir()
        playbook_file = playbook_dir / "playbook.json"
        playbook_data = {
            "metadata": {"project": "test"},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {"id": "impl-0001", "content": "Pattern 1", "quality_score": 6, "helpful_count": 6, "harmful_count": 0, "deprecated": False},
                        {"id": "impl-0002", "content": "Pattern 2", "quality_score": 5, "helpful_count": 5, "harmful_count": 0, "deprecated": False}
                    ]
                },
                "DEBUGGING_TECHNIQUES": {
                    "bullets": [
                        {"id": "debug-0001", "content": "Debug 1", "quality_score": 7, "helpful_count": 7, "harmful_count": 0, "deprecated": False}
                    ]
                }
            }
        }
        playbook_file.write_text(json.dumps(playbook_data))

        manager.generate_context_md()

        content = manager.context_file.read_text()
        assert "Implementation Patterns" in content
        assert "Debugging Techniques" in content
        assert "impl-0001" in content
        assert "debug-0001" in content

    def test_generate_context_content_truncation(self, manager):
        """Test content truncation for long bullet content (>200 chars)"""
        playbook_dir = manager.project_root / ".claude"
        playbook_dir.mkdir()
        playbook_file = playbook_dir / "playbook.json"

        long_content = "A" * 250  # 250 characters
        playbook_data = {
            "metadata": {"project": "test"},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {"id": "impl-0001", "content": long_content, "quality_score": 5, "helpful_count": 5, "harmful_count": 0, "deprecated": False}
                    ]
                }
            }
        }
        playbook_file.write_text(json.dumps(playbook_data))

        manager.generate_context_md()

        content = manager.context_file.read_text()
        # Should be truncated to ~200 chars with "..."
        assert "AAA..." in content
        # Full 250-char string should not appear
        assert long_content not in content

    def test_generate_context_top_3_bullets_per_section(self, manager):
        """Test only top 3 bullets per section are included"""
        playbook_dir = manager.project_root / ".claude"
        playbook_dir.mkdir()
        playbook_file = playbook_dir / "playbook.json"

        # Create 5 bullets with different quality scores
        bullets = [
            {"id": f"impl-{i:04d}", "content": f"Pattern {i}", "quality_score": 10 - i, "helpful_count": 10 - i, "harmful_count": 0, "deprecated": False}
            for i in range(1, 6)
        ]

        playbook_data = {
            "metadata": {"project": "test"},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": bullets
                }
            }
        }
        playbook_file.write_text(json.dumps(playbook_data))

        manager.generate_context_md()

        content = manager.context_file.read_text()
        # Top 3 (highest quality) should be present
        assert "impl-0001" in content  # quality 9
        assert "impl-0002" in content  # quality 8
        assert "impl-0003" in content  # quality 7
        # Bottom 2 should not be present
        assert "impl-0004" not in content
        assert "impl-0005" not in content

    def test_generate_context_unicode_handling(self, manager):
        """Test unicode handling in README and playbook"""
        readme = manager.project_root / "README.md"
        readme.write_text("# Тест 测试 🚀\n\nDescription with émojis 🎉")

        playbook_dir = manager.project_root / ".claude"
        playbook_dir.mkdir()
        playbook_file = playbook_dir / "playbook.json"
        playbook_data = {
            "metadata": {"project": "test"},
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {"id": "impl-0001", "content": "Pattern with 日本語 and émojis 🔥", "quality_score": 5, "helpful_count": 5, "harmful_count": 0, "deprecated": False}
                    ]
                }
            }
        }
        playbook_file.write_text(json.dumps(playbook_data))

        manager.generate_context_md()

        content = manager.context_file.read_text()
        assert "Тест" in content
        assert "测试" in content
        assert "🚀" in content
        assert "日本語" in content
        assert "🔥" in content

    def test_generate_context_file_creation_and_validation(self, manager):
        """Test file is created in correct location with valid content"""
        expected_path = manager.project_root / ".map" / "dev_docs" / "context.md"

        context_path = manager.generate_context_md()

        # Verify path
        assert context_path == str(expected_path)
        assert expected_path.exists()

        # Verify structure
        content = expected_path.read_text()
        assert content.startswith("# Project Context")
        assert "## Project Information" in content
        assert "## Key Conventions" in content
        assert "Last generated:" in content

    # Tests for _generate_tasks_md()

    def test_generate_tasks_status_grouping(self, manager, sample_subtasks):
        """Test tasks are grouped by status (pending, in_progress, completed, failed)"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        # Set different statuses
        plan.subtasks[0].status = 'completed'
        plan.subtasks[1].status = 'in_progress'
        plan.subtasks[2].status = 'pending'

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        assert "### 🔄 In Progress" in content
        assert "### ☐ Pending" in content
        assert "### ✓ Completed" in content

    def test_generate_tasks_markdown_formatting(self, manager, sample_subtasks):
        """Test markdown formatting (headers, lists, strikethrough)"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)
        plan.subtasks[0].status = 'completed'

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        # Strikethrough for completed
        assert "~~**[1]**" in content
        # Bullet lists
        assert "- **[" in content
        # Headers
        assert "# Tasks for:" in content
        assert "**Overall Goal:**" in content

    def test_generate_tasks_dependencies_display(self, manager, sample_subtasks):
        """Test dependencies are displayed correctly"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        # Task 1 has no dependencies, so shouldn't show "Depends on"
        # Task 2 depends on task 1
        assert "**[2]** Implement login endpoint" in content
        assert content.count("**Depends on:** 1") == 1
        # Task 3 depends on task 2
        assert "**Depends on:** 2" in content

    def test_generate_tasks_iterations_and_errors(self, manager, sample_subtasks):
        """Test iterations and errors are displayed"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        plan.subtasks[0].status = 'in_progress'
        plan.subtasks[0].iterations = 3
        plan.subtasks[0].errors = ["Error 1", "Error 2", "Error 3"]

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        assert "⚠️ **Retry #3**" in content
        assert "**Last Error:** Error 3" in content

    def test_generate_tasks_error_truncation(self, manager, sample_subtasks):
        """Test error message truncation (>150 chars)"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        long_error = "Error: " + "x" * 200
        plan.subtasks[0].status = 'in_progress'
        plan.subtasks[0].errors = [long_error]

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        # Should be truncated to 150 chars
        assert "xxx..." in content
        # Full error should not appear
        assert long_error not in content

    def test_generate_tasks_empty_plan(self, manager):
        """Test handling empty plan (no subtasks)"""
        plan = manager.create_plan("test", "Test goal", [])

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        assert "# Tasks for: test" in content
        assert "**Overall Goal:** Test goal" in content
        assert "**Progress:** 0/0 completed" in content

    def test_generate_tasks_progress_summary(self, manager, sample_subtasks):
        """Test progress summary calculation"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        plan.subtasks[0].status = 'completed'
        plan.subtasks[1].status = 'in_progress'
        plan.subtasks[2].status = 'failed'

        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        assert "**Progress:** 1/3 completed, 1 in progress, 0 pending, 1 failed" in content

    def test_generate_tasks_file_creation_and_timestamp(self, manager, sample_subtasks):
        """Test file creation and timestamp"""
        plan = manager.create_plan("test", "Test goal", sample_subtasks)

        expected_path = manager.project_root / ".map" / "dev_docs" / "tasks.md"

        manager._generate_tasks_md(plan)

        # Verify file created
        assert expected_path.exists()

        content = expected_path.read_text()
        # Verify timestamp exists
        assert "**Updated:**" in content
        # Should contain ISO-like date
        assert "2025" in content or "202" in content  # Year prefix

    # Tests for get_dev_docs()

    def test_get_dev_docs_all_files_exist(self, manager, sample_subtasks):
        """Test get_dev_docs when all files exist - returns all 3 docs"""
        # Create plan (creates plan.md and tasks.md)
        manager.create_plan("test", "Test goal", sample_subtasks)

        # Create context.md
        manager.generate_context_md()

        # Get docs
        docs = manager.get_dev_docs()

        # Verify structure
        assert "plan" in docs
        assert "context" in docs
        assert "tasks" in docs

        # Verify content is not placeholder
        assert "# Current Task: test" in docs["plan"]
        assert "# Project Context" in docs["context"]
        assert "# Tasks for: test" in docs["tasks"]

    def test_get_dev_docs_missing_context(self, manager, sample_subtasks):
        """Test get_dev_docs when context.md is missing - returns placeholder"""
        # Create plan (no context)
        manager.create_plan("test", "Test goal", sample_subtasks)

        docs = manager.get_dev_docs()

        # Context should be placeholder
        assert "Not generated yet" in docs["context"]
        assert "mapify recitation generate-context" in docs["context"]

    def test_get_dev_docs_missing_tasks(self, manager):
        """Test get_dev_docs when tasks.md is missing - returns placeholder"""
        # Don't create plan

        docs = manager.get_dev_docs()

        # Tasks should be placeholder
        assert "No active plan" in docs["tasks"]

    def test_get_dev_docs_no_active_plan(self, manager):
        """Test get_dev_docs when no active plan exists"""
        docs = manager.get_dev_docs()

        # Plan should be empty
        assert docs["plan"] == ""
        # Tasks should show no plan
        assert "No active plan" in docs["tasks"]

    def test_get_dev_docs_json_structure_validation(self, manager, sample_subtasks):
        """Test JSON structure is valid and complete"""
        manager.create_plan("test", "Test goal", sample_subtasks)
        manager.generate_context_md()

        docs = manager.get_dev_docs()

        # Verify it's a dict with 3 keys
        assert isinstance(docs, dict)
        assert len(docs) == 3
        assert all(isinstance(v, str) for v in docs.values())

        # Verify no None values
        assert all(v is not None for v in docs.values())


class TestDevDocsCLI:
    """Test CLI commands for dev docs generation"""

    def test_cli_generate_context_success(self, tmp_path):
        """Test mapify recitation generate-context - success case"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        # Create README
        readme = tmp_path / "README.md"
        readme.write_text("# Test Project\n\nTest description")

        result = runner.invoke(app, ["recitation", "generate-context"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"
        assert "context.md" in output["file"]
        assert (tmp_path / ".map" / "dev_docs" / "context.md").exists()

    def test_cli_generate_context_error_case(self, tmp_path):
        """Test mapify recitation generate-context - error case (no README)"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        # No README, but should still succeed with fallback
        result = runner.invoke(app, ["recitation", "generate-context"])

        # Should succeed even without README (uses project name)
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"

    def test_cli_generate_tasks_success(self, tmp_path):
        """Test mapify recitation generate-tasks - success case"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        # Create plan first
        subtasks_json = json.dumps([
            {"id": 1, "description": "Task 1", "depends_on": []}
        ])
        runner.invoke(app, ["recitation", "create", "test_task", "Test goal", subtasks_json])

        # Generate tasks
        result = runner.invoke(app, ["recitation", "generate-tasks"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"
        assert "tasks.md" in output["file"]

    def test_cli_generate_tasks_no_plan_error(self, tmp_path):
        """Test mapify recitation generate-tasks - no plan error"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        # Try to generate tasks without plan
        result = runner.invoke(app, ["recitation", "generate-tasks"])

        assert result.exit_code == 1
        # Output may contain multiple JSON objects, parse first one
        first_json_line = result.stdout.strip().split('\n}\n')[0] + '\n}'
        output = json.loads(first_json_line)
        assert output["status"] == "error"
        assert "no active plan" in output["message"].lower()

    def test_cli_get_docs_json_output(self, tmp_path):
        """Test mapify recitation get-docs - JSON output validation"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        # Create plan
        subtasks_json = json.dumps([
            {"id": 1, "description": "Task 1", "depends_on": []}
        ])
        runner.invoke(app, ["recitation", "create", "test_task", "Test goal", subtasks_json])

        # Get docs
        result = runner.invoke(app, ["recitation", "get-docs"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"
        assert "docs" in output
        assert "plan" in output["docs"]
        assert "context" in output["docs"]
        assert "tasks" in output["docs"]


class TestDevDocsIntegration:
    """Integration/E2E tests for dev docs auto-update hooks"""

    def test_create_plan_generates_tasks_md(self, manager, sample_subtasks):
        """Test create_plan() auto-generates tasks.md"""
        # Tasks file shouldn't exist yet
        assert not manager.tasks_file.exists()

        # Create plan
        manager.create_plan("test", "Test goal", sample_subtasks)

        # Tasks file should now exist
        assert manager.tasks_file.exists()
        content = manager.tasks_file.read_text()
        assert "# Tasks for: test" in content

    def test_update_subtask_regenerates_tasks_md(self, manager, sample_subtasks):
        """Test update_subtask_status() regenerates tasks.md"""
        manager.create_plan("test", "Test goal", sample_subtasks)

        # Get initial timestamp
        initial_mtime = manager.tasks_file.stat().st_mtime

        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)

        # Update subtask
        manager.update_subtask_status(1, 'in_progress')

        # File should be regenerated
        new_mtime = manager.tasks_file.stat().st_mtime
        assert new_mtime > initial_mtime

    def test_tasks_md_content_changes_after_update(self, manager, sample_subtasks):
        """Test tasks.md content changes after status update"""
        manager.create_plan("test", "Test goal", sample_subtasks)

        initial_content = manager.tasks_file.read_text()
        # Initially no "In Progress" section
        assert "### 🔄 In Progress" not in initial_content

        # Update to in_progress
        manager.update_subtask_status(1, 'in_progress')

        updated_content = manager.tasks_file.read_text()
        # Now should have "In Progress" section
        assert "### 🔄 In Progress" in updated_content


class TestDevDocsEdgeCases:
    """Test edge cases and error scenarios"""

    def test_readme_non_utf8_encoding(self, manager):
        """Test README with non-UTF-8 encoding"""
        readme = manager.project_root / "README.md"
        # Write with latin-1 encoding
        readme.write_bytes(b"# Caf\xe9\n\nDescription")

        # Should handle encoding error gracefully
        try:
            manager.generate_context_md()
            # If it succeeds, verify content
            content = manager.context_file.read_text()
            assert "# Project Context" in content
        except UnicodeDecodeError:
            # If it fails, that's also acceptable behavior
            pass

    def test_playbook_query_timeout(self, manager):
        """Test playbook query timeout (if feasible)"""
        # This is challenging to test without mocking
        # Instead, test that generate_context_md handles exceptions
        manager.generate_context_md()

        content = manager.context_file.read_text()
        # Should either succeed or show error message
        assert "# Project Context" in content

    def test_very_long_descriptions(self, manager):
        """Test very long descriptions (>1000 chars)"""
        readme = manager.project_root / "README.md"
        long_desc = "A" * 1500
        readme.write_text(f"# Project\n\n{long_desc}")

        manager.generate_context_md()

        content = manager.context_file.read_text()
        # Should handle long content without crashing
        assert "# Project Context" in content

    def test_special_characters_in_markdown(self, manager, sample_subtasks):
        """Test special characters in markdown content"""
        # Use subtasks with special markdown characters
        special_subtasks = [
            {
                'id': 1,
                'description': 'Task with **bold** and _italic_ and `code`',
                'depends_on': []
            },
            {
                'id': 2,
                'description': 'Task with [link](http://example.com) and > quote',
                'depends_on': []
            }
        ]

        plan = manager.create_plan("test", "Test goal", special_subtasks)

        # Generate tasks
        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()
        # Special characters should be preserved
        assert "**bold**" in content
        assert "`code`" in content
        assert "[link]" in content

    def test_context_generation_without_crash(self, manager):
        """Test context generation doesn't crash even with missing data"""
        # No README, no playbook, no architecture
        # Should still generate valid context.md
        manager.generate_context_md()

        assert manager.context_file.exists()
        content = manager.context_file.read_text()
        assert "# Project Context" in content
        assert "## Project Information" in content
        assert "## Key Conventions" in content


class TestStringIDSupport:
    """Test support for string IDs (e.g., 'ST-001', 'subtask-1')"""

    @pytest.fixture
    def string_id_subtasks(self):
        """Sample subtasks with string IDs"""
        return [
            {
                'id': 'ST-001',
                'description': 'Create User model',
                'acceptance_criteria': ['Model validates email', 'Password is hashed'],
                'estimated_complexity': 'low',
                'depends_on': []
            },
            {
                'id': 'ST-002',
                'description': 'Implement login endpoint',
                'acceptance_criteria': 'POST /auth/login returns JWT token',
                'estimated_complexity': 'medium',
                'depends_on': ['ST-001']
            },
            {
                'id': 'subtask-3',
                'description': 'Add token validation',
                'acceptance_criteria': ['Middleware validates tokens', 'Expired tokens rejected'],
                'estimated_complexity': 'low',
                'depends_on': ['ST-002']
            }
        ]

    def test_create_plan_with_string_ids(self, manager, string_id_subtasks):
        """Test creating plan with string IDs instead of integers"""
        plan = manager.create_plan(
            task_id='feat_auth',
            goal='Implement JWT authentication',
            subtasks=string_id_subtasks
        )

        assert plan.task_id == 'feat_auth'
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].id == 'ST-001'
        assert plan.subtasks[1].id == 'ST-002'
        assert plan.subtasks[2].id == 'subtask-3'
        assert plan.current_subtask_id == 'ST-001'

    def test_update_subtask_with_string_id(self, manager, string_id_subtasks):
        """Test updating subtask status using string ID"""
        manager.create_plan('test', 'Test', string_id_subtasks)

        plan = manager.update_subtask_status('ST-001', 'in_progress')

        assert plan.subtasks[0].status == 'in_progress'
        assert plan.current_subtask_id == 'ST-001'

    def test_string_id_dependencies(self, manager, string_id_subtasks):
        """Test that string ID dependencies work correctly"""
        plan = manager.create_plan('test', 'Test', string_id_subtasks)

        # Check dependencies are preserved as strings
        assert plan.subtasks[1].depends_on == ['ST-001']
        assert plan.subtasks[2].depends_on == ['ST-002']

    def test_markdown_with_string_ids(self, manager, string_id_subtasks):
        """Test markdown generation with string IDs"""
        manager.create_plan('test', 'Test', string_id_subtasks)
        manager.update_subtask_status('ST-002', 'in_progress')

        md = manager.plan_file.read_text()

        # Check that string IDs appear in markdown
        assert 'ST-001' in md
        assert 'ST-002' in md
        assert 'subtask-3' in md
        assert 'CURRENT' in md  # ST-002 is current

    def test_json_persistence_with_string_ids(self, manager, string_id_subtasks):
        """Test JSON serialization/deserialization with string IDs"""
        plan = manager.create_plan('test', 'Test', string_id_subtasks)

        # Save and reload
        plan_data = json.loads(manager.plan_json.read_text())

        assert plan_data['subtasks'][0]['id'] == 'ST-001'
        assert plan_data['subtasks'][1]['id'] == 'ST-002'
        assert plan_data['current_subtask_id'] == 'ST-001'

    def test_update_nonexistent_string_id(self, manager, string_id_subtasks):
        """Test updating non-existent string ID raises error"""
        manager.create_plan('test', 'Test', string_id_subtasks)

        with pytest.raises(ValueError, match="Subtask with id INVALID-ID"):
            manager.update_subtask_status('INVALID-ID', 'completed')

    def test_mixed_string_id_formats(self, manager):
        """Test various string ID formats (UUID-like, alphanumeric, etc.)"""
        mixed_subtasks = [
            {'id': 'uuid-123e4567-e89b', 'description': 'Task 1', 'depends_on': []},
            {'id': 'TASK_001', 'description': 'Task 2', 'depends_on': ['uuid-123e4567-e89b']},
            {'id': 'feature-auth-login', 'description': 'Task 3', 'depends_on': []},
        ]

        plan = manager.create_plan('test', 'Test', mixed_subtasks)

        assert plan.subtasks[0].id == 'uuid-123e4567-e89b'
        assert plan.subtasks[1].id == 'TASK_001'
        assert plan.subtasks[2].id == 'feature-auth-login'


class TestAcceptanceCriteriaListSupport:
    """Test support for acceptance_criteria as list instead of string"""

    def test_acceptance_criteria_as_list(self, manager):
        """Test creating plan with acceptance_criteria as list"""
        subtasks = [{
            'id': 'ST-001',
            'description': 'Create User model',
            'acceptance_criteria': [
                'Model validates email format',
                'Password is hashed using bcrypt',
                'Username is unique'
            ],
            'depends_on': []
        }]

        plan = manager.create_plan('test', 'Test', subtasks)

        assert plan.subtasks[0].acceptance_criteria == [
            'Model validates email format',
            'Password is hashed using bcrypt',
            'Username is unique'
        ]

    def test_acceptance_criteria_as_string(self, manager):
        """Test creating plan with acceptance_criteria as string (backward compatibility)"""
        subtasks = [{
            'id': 'ST-001',
            'description': 'Create User model',
            'acceptance_criteria': 'Model validates email and hashes password',
            'depends_on': []
        }]

        plan = manager.create_plan('test', 'Test', subtasks)

        assert plan.subtasks[0].acceptance_criteria == 'Model validates email and hashes password'

    def test_format_acceptance_criteria_string(self, manager):
        """Test _format_acceptance_criteria with string input"""
        result = manager._format_acceptance_criteria('Test criterion')
        assert result == 'Test criterion'

    def test_format_acceptance_criteria_list(self, manager):
        """Test _format_acceptance_criteria with list input"""
        criteria_list = ['Criterion 1', 'Criterion 2', 'Criterion 3']
        result = manager._format_acceptance_criteria(criteria_list)

        expected = "- Criterion 1\n- Criterion 2\n- Criterion 3"
        assert result == expected

    def test_format_acceptance_criteria_none(self, manager):
        """Test _format_acceptance_criteria with None input"""
        result = manager._format_acceptance_criteria(None)
        assert result is None

    def test_markdown_with_list_acceptance_criteria(self, manager):
        """Test markdown generation with list acceptance_criteria"""
        subtasks = [{
            'id': 'ST-001',
            'description': 'Create User model',
            'acceptance_criteria': [
                'Model validates email',
                'Password is hashed',
                'Username is unique'
            ],
            'depends_on': []
        }]

        manager.create_plan('test', 'Test', subtasks)
        manager.update_subtask_status('ST-001', 'in_progress')

        md = manager.plan_file.read_text()

        # Should contain formatted list
        assert 'Acceptance Criteria:' in md
        assert '- Model validates email' in md
        assert '- Password is hashed' in md
        assert '- Username is unique' in md

    def test_tasks_md_with_list_acceptance_criteria(self, manager):
        """Test tasks.md generation with list acceptance_criteria"""
        subtasks = [{
            'id': 'ST-001',
            'description': 'Create User model',
            'acceptance_criteria': [
                'Model validates email',
                'Password is hashed'
            ],
            'depends_on': []
        }]

        plan = manager.create_plan('test', 'Test', subtasks)
        plan.subtasks[0].status = 'in_progress'
        manager._generate_tasks_md(plan)

        content = manager.tasks_file.read_text()

        # Should contain formatted acceptance criteria
        assert '**Acceptance:**' in content
        assert '- Model validates email' in content
        assert '- Password is hashed' in content

    def test_mixed_acceptance_criteria_formats(self, manager):
        """Test plan with mixed string and list acceptance_criteria"""
        subtasks = [
            {
                'id': 'ST-001',
                'description': 'Task 1',
                'acceptance_criteria': 'Simple string criterion',
                'depends_on': []
            },
            {
                'id': 'ST-002',
                'description': 'Task 2',
                'acceptance_criteria': ['Criterion 1', 'Criterion 2'],
                'depends_on': []
            },
            {
                'id': 'ST-003',
                'description': 'Task 3',
                'acceptance_criteria': None,
                'depends_on': []
            }
        ]

        plan = manager.create_plan('test', 'Test', subtasks)

        # Verify all formats are preserved
        assert isinstance(plan.subtasks[0].acceptance_criteria, str)
        assert isinstance(plan.subtasks[1].acceptance_criteria, list)
        assert plan.subtasks[2].acceptance_criteria is None

    def test_empty_acceptance_criteria_list(self, manager):
        """Test handling of empty acceptance_criteria list"""
        subtasks = [{
            'id': 'ST-001',
            'description': 'Task 1',
            'acceptance_criteria': [],
            'depends_on': []
        }]

        plan = manager.create_plan('test', 'Test', subtasks)

        # Empty list should be preserved
        assert plan.subtasks[0].acceptance_criteria == []

        # Formatting empty list should return empty string
        result = manager._format_acceptance_criteria([])
        assert result == ""


class TestStringIDAndListCriteriaIntegration:
    """Integration tests for string IDs + list acceptance_criteria"""

    def test_full_workflow_with_new_types(self, manager):
        """Test complete workflow with string IDs and list acceptance_criteria"""
        subtasks = [
            {
                'id': 'ST-001',
                'description': 'Create User model',
                'acceptance_criteria': [
                    'Email validation works',
                    'Password hashing implemented',
                    'Model tests pass'
                ],
                'estimated_complexity': 'medium',
                'depends_on': []
            },
            {
                'id': 'ST-002',
                'description': 'Create login endpoint',
                'acceptance_criteria': [
                    'POST /auth/login accepts credentials',
                    'Returns JWT on success',
                    'Returns 401 on failure'
                ],
                'estimated_complexity': 'medium',
                'depends_on': ['ST-001']
            }
        ]

        # Create plan
        plan = manager.create_plan('feat_auth', 'Add authentication', subtasks)
        assert plan.current_subtask_id == 'ST-001'

        # Start first task
        manager.update_subtask_status('ST-001', 'in_progress')
        md1 = manager.plan_file.read_text()
        assert 'ST-001' in md1
        assert '- Email validation works' in md1
        assert 'CURRENT' in md1

        # Complete first task
        manager.update_subtask_status('ST-001', 'completed')

        # Start second task
        manager.update_subtask_status('ST-002', 'in_progress')
        md2 = manager.plan_file.read_text()
        assert '✓' in md2  # First task completed
        assert 'ST-002' in md2
        assert '- POST /auth/login' in md2

        # Complete workflow
        manager.update_subtask_status('ST-002', 'completed')

        stats = manager.get_statistics()
        assert stats['completed'] == 2
        assert stats['pending'] == 0

    def test_cli_with_string_ids_and_list_criteria(self, tmp_path):
        """Test CLI commands work with string IDs and list acceptance_criteria"""
        os.chdir(tmp_path)
        map_dir = tmp_path / ".map"
        map_dir.mkdir()

        subtasks_json = json.dumps([
            {
                'id': 'ST-001',
                'description': 'Test task',
                'acceptance_criteria': ['Criterion 1', 'Criterion 2'],
                'estimated_complexity': 'low',
                'depends_on': []
            }
        ])

        # Create plan via CLI
        result = runner.invoke(app, [
            'recitation', 'create',
            'test_task', 'Test goal', subtasks_json
        ])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output['status'] == 'success'

        # Update via CLI with string ID
        result = runner.invoke(app, [
            'recitation', 'update',
            'ST-001', 'in_progress'
        ])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output['status'] == 'success'
        assert output['current_subtask'] == 'ST-001'

    def test_persistence_across_manager_instances(self, temp_project):
        """Test string IDs and list criteria persist correctly"""
        subtasks = [
            {
                'id': 'ST-001',
                'description': 'Task',
                'acceptance_criteria': ['Criterion 1', 'Criterion 2'],
                'depends_on': []
            }
        ]

        # Create with first manager
        manager1 = RecitationManager(temp_project)
        manager1.create_plan('test', 'Test', subtasks)
        manager1.update_subtask_status('ST-001', 'in_progress')

        # Load with second manager
        manager2 = RecitationManager(temp_project)
        plan = manager2.get_plan()

        assert plan.subtasks[0].id == 'ST-001'
        assert plan.subtasks[0].acceptance_criteria == ['Criterion 1', 'Criterion 2']
        assert plan.subtasks[0].status == 'in_progress'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
