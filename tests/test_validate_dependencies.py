"""
Comprehensive test suite for validate-dependencies.py

Tests both DependencyValidator and ASCIIGraphRenderer classes:
- Validation logic (cycles, forward refs, orphaned tasks)
- Graph rendering (colors, tree structure, edge cases)
- CLI integration (input handling, exit codes)
"""

import json
from io import StringIO
from unittest import mock

import pytest

# Import from mapify_cli.tools.validate_dependencies
from mapify_cli.tools.validate_dependencies import (
    ANSIColors,
    ASCIIGraphRenderer,
    DependencyValidator,
    IssueSeverity,
    load_input,
    main,
)

# ============================================================================
# Test Fixtures - Sample Task Graphs
# ============================================================================


@pytest.fixture
def simple_linear_chain():
    """Simple linear dependency chain: 1 -> 2 -> 3"""
    return {
        "subtasks": [
            {"id": 1, "title": "First task", "dependencies": []},
            {"id": 2, "title": "Second task", "dependencies": [1]},
            {"id": 3, "title": "Third task", "dependencies": [2]},
        ]
    }


@pytest.fixture
def valid_dag():
    """Valid DAG with multiple dependency paths"""
    return {
        "subtasks": [
            {"id": 1, "title": "Root task", "dependencies": []},
            {"id": 2, "title": "Task 2", "dependencies": [1]},
            {"id": 3, "title": "Task 3", "dependencies": [1]},
            {"id": 4, "title": "Task 4", "dependencies": [2, 3]},
        ]
    }


@pytest.fixture
def cyclic_dependencies():
    """Graph with circular dependency: 1 -> 2 -> 3 -> 1"""
    return {
        "subtasks": [
            {"id": 1, "title": "Task 1", "dependencies": [3]},
            {"id": 2, "title": "Task 2", "dependencies": [1]},
            {"id": 3, "title": "Task 3", "dependencies": [2]},
        ]
    }


@pytest.fixture
def self_dependency():
    """Task that depends on itself"""
    return {"subtasks": [{"id": 1, "title": "Self-referencing", "dependencies": [1]}]}


@pytest.fixture
def forward_reference():
    """Task depends on non-existent task"""
    return {
        "subtasks": [
            {"id": 1, "title": "Valid task", "dependencies": []},
            {"id": 2, "title": "Invalid deps", "dependencies": [1, 99]},
        ]
    }


@pytest.fixture
def orphaned_tasks():
    """Isolated tasks with no connections"""
    return {
        "subtasks": [
            {"id": 1, "title": "Connected task", "dependencies": []},
            {"id": 2, "title": "Depends on 1", "dependencies": [1]},
            {"id": 3, "title": "Orphaned task", "dependencies": []},
            {"id": 4, "title": "Another orphan", "dependencies": []},
        ]
    }


@pytest.fixture
def disconnected_graphs():
    """Multiple disconnected dependency chains"""
    return {
        "subtasks": [
            {"id": 1, "title": "Chain 1 root", "dependencies": []},
            {"id": 2, "title": "Chain 1 child", "dependencies": [1]},
            {"id": 3, "title": "Chain 2 root", "dependencies": []},
            {"id": 4, "title": "Chain 2 child", "dependencies": [3]},
        ]
    }


@pytest.fixture
def large_graph():
    """Large graph with 100+ tasks for performance testing"""
    subtasks = []
    # Create a deep chain
    for i in range(1, 101):
        deps = [i - 1] if i > 1 else []
        subtasks.append({"id": i, "title": f"Task {i}", "dependencies": deps})
    return {"subtasks": subtasks}


# ============================================================================
# DependencyValidator Tests
# ============================================================================


class TestDependencyValidator:
    """Test validation logic"""

    def test_valid_linear_chain(self, simple_linear_chain):
        """Linear chain passes all validations"""
        validator = DependencyValidator(simple_linear_chain)
        assert validator.validate_all() is True
        assert len(validator.issues) == 0

    def test_valid_dag(self, valid_dag):
        """Valid DAG passes all validations"""
        validator = DependencyValidator(valid_dag)
        assert validator.validate_all() is True
        assert len(validator.issues) == 0

    def test_detect_circular_dependencies(self, cyclic_dependencies):
        """Detects cycles in dependency graph"""
        validator = DependencyValidator(cyclic_dependencies)
        assert validator.validate_circular_dependencies() is False

        # Should have exactly one cycle issue
        cycle_issues = [
            i for i in validator.issues if i.issue_type == "circular_dependency"
        ]
        assert len(cycle_issues) == 1

        # Cycle should involve tasks 1, 2, 3
        cycle = cycle_issues[0]
        assert set(cycle.affected_tasks).issubset({1, 2, 3})
        assert cycle.severity == IssueSeverity.CRITICAL

    def test_detect_self_dependency(self, self_dependency):
        """Detects task depending on itself"""
        validator = DependencyValidator(self_dependency)
        assert validator.validate_self_dependencies() is False

        self_dep_issues = [
            i for i in validator.issues if i.issue_type == "self_dependency"
        ]
        assert len(self_dep_issues) == 1
        assert self_dep_issues[0].affected_tasks == [1]
        assert self_dep_issues[0].severity == IssueSeverity.CRITICAL

    def test_detect_forward_reference(self, forward_reference):
        """Detects dependencies on non-existent tasks"""
        validator = DependencyValidator(forward_reference)
        assert validator.validate_forward_references() is False

        fwd_ref_issues = [
            i for i in validator.issues if i.issue_type == "forward_reference"
        ]
        assert len(fwd_ref_issues) == 1
        assert 99 in fwd_ref_issues[0].affected_tasks
        assert fwd_ref_issues[0].severity == IssueSeverity.CRITICAL

    def test_detect_orphaned_tasks(self, orphaned_tasks):
        """Detects isolated tasks with no connections"""
        validator = DependencyValidator(orphaned_tasks)
        assert validator.validate_orphaned_tasks() is False

        orphan_issues = [
            i for i in validator.issues if i.issue_type == "orphaned_tasks"
        ]
        assert len(orphan_issues) == 1

        # Tasks 3 and 4 are orphaned (no connections)
        orphaned_ids = orphan_issues[0].affected_tasks
        assert set(orphaned_ids) == {3, 4}
        assert orphan_issues[0].severity == IssueSeverity.WARNING

    def test_disconnected_graphs_not_orphans(self, disconnected_graphs):
        """Disconnected chains aren't orphans (they have connections)"""
        validator = DependencyValidator(disconnected_graphs)
        # Should pass orphan check (all tasks have edges)
        assert validator.validate_orphaned_tasks() is True
        # But may have issues rendering as single tree
        assert len(validator.issues) == 0

    def test_invalid_input_no_subtasks(self):
        """Raises error for missing 'subtasks' field"""
        with pytest.raises(ValueError, match="Missing required field 'subtasks'"):
            DependencyValidator({"tasks": []})

    def test_invalid_input_not_dict(self):
        """Raises error for non-dict input"""
        with pytest.raises(ValueError, match="Input must be a JSON object"):
            DependencyValidator([1, 2, 3])  # pyright: ignore[reportArgumentType]  # intentional invalid input for validation test

    def test_invalid_task_missing_id(self):
        """Raises error for task without ID"""
        with pytest.raises(ValueError, match="Task missing 'id' field"):
            DependencyValidator({"subtasks": [{"title": "No ID"}]})

    def test_invalid_task_id_not_integer(self):
        """Raises error for non-integer task ID"""
        with pytest.raises(ValueError, match="Task ID must be integer"):
            DependencyValidator({"subtasks": [{"id": "1", "title": "String ID"}]})

    def test_invalid_dependencies_not_list(self):
        """Raises error for non-list dependencies"""
        with pytest.raises(ValueError, match="dependencies must be a list"):
            DependencyValidator({"subtasks": [{"id": 1, "dependencies": "not a list"}]})

    def test_validation_report_structure(self, simple_linear_chain):
        """Report has correct structure and counts"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        report = validator.get_report()

        assert "valid" in report
        assert "total_tasks" in report
        assert "total_issues" in report
        assert "critical_issues" in report
        assert "warnings" in report
        assert "issues" in report

        assert report["valid"] is True
        assert report["total_tasks"] == 3
        assert report["total_issues"] == 0

    def test_validation_report_with_issues(self, cyclic_dependencies):
        """Report correctly categorizes critical vs warning issues"""
        validator = DependencyValidator(cyclic_dependencies)
        validator.validate_all()
        report = validator.get_report()

        assert report["valid"] is False
        assert report["critical_issues"] >= 1
        assert all(isinstance(issue, dict) for issue in report["issues"])

    def test_get_task_title(self, simple_linear_chain):
        """Can retrieve task titles by ID"""
        validator = DependencyValidator(simple_linear_chain)
        assert validator.get_task_title(1) == "First task"
        assert validator.get_task_title(2) == "Second task"
        assert validator.get_task_title(99) == ""  # Non-existent

    def test_large_graph_performance(self, large_graph):
        """Large graph (100 tasks) validates in reasonable time"""
        import time

        start = time.time()
        validator = DependencyValidator(large_graph)
        validator.validate_all()
        elapsed = time.time() - start

        # Should complete in < 1 second
        assert elapsed < 1.0
        assert validator.validate_all() is True


# ============================================================================
# ASCIIGraphRenderer Tests
# ============================================================================


class TestASCIIGraphRenderer:
    """Test graph visualization rendering"""

    def test_render_simple_chain(self, simple_linear_chain):
        """Renders linear chain correctly"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # Check header
        assert "Task Dependency Graph" in output
        assert "Total Tasks: 3" in output

        # Check all tasks appear
        assert "Task 1" in output
        assert "Task 2" in output
        assert "Task 3" in output

    def test_color_coding_valid_tasks(self, simple_linear_chain):
        """Valid tasks get green color"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        # All tasks should be green (no issues)
        for task_id in [1, 2, 3]:
            color = renderer._get_task_color(task_id)
            assert color == ANSIColors.GREEN

    def test_color_coding_critical_issues(self, cyclic_dependencies):
        """Tasks with critical issues get red color"""
        validator = DependencyValidator(cyclic_dependencies)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        # All tasks in cycle should be red
        for task_id in [1, 2, 3]:
            color = renderer._get_task_color(task_id)
            assert color == ANSIColors.RED

    def test_color_coding_warnings(self, orphaned_tasks):
        """Tasks with warnings get yellow color"""
        validator = DependencyValidator(orphaned_tasks)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        # Orphaned tasks should be yellow
        color_3 = renderer._get_task_color(3)
        color_4 = renderer._get_task_color(4)
        assert color_3 == ANSIColors.YELLOW
        assert color_4 == ANSIColors.YELLOW

        # Connected tasks should be green
        assert renderer._get_task_color(1) == ANSIColors.GREEN

    def test_no_color_mode(self, simple_linear_chain):
        """--no-color strips ANSI codes"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # Check that ANSI codes are disabled
        # When use_colors=False, ANSIColors attributes become empty strings
        assert "\033[" not in output  # No ANSI escape sequences

    def test_box_drawing_characters(self, simple_linear_chain):
        """Uses correct Unicode tree characters"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # Check for tree structure characters
        assert "└──" in output or "├──" in output  # Branch connectors
        # May also have │ (vertical line) in deeper trees

    def test_disconnected_graphs_section(self, disconnected_graphs):
        """Shows disconnected components separately"""
        validator = DependencyValidator(disconnected_graphs)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # Should show all 4 tasks
        assert "Task 1" in output
        assert "Task 2" in output
        assert "Task 3" in output
        assert "Task 4" in output

    def test_cyclic_tasks_section(self, cyclic_dependencies):
        """Cyclic tasks shown in special section if not visited"""
        validator = DependencyValidator(cyclic_dependencies)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # All tasks should be visible
        assert "Task 1" in output
        assert "Task 2" in output
        assert "Task 3" in output

    def test_dependency_info_displayed(self, valid_dag):
        """Shows dependency information in node labels"""
        validator = DependencyValidator(valid_dag)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # Task 4 depends on [2, 3]
        assert "depends on" in output

    def test_get_root_nodes(self, valid_dag):
        """Correctly identifies root nodes (no dependencies)"""
        validator = DependencyValidator(valid_dag)
        renderer = ASCIIGraphRenderer(validator)

        roots = renderer._get_root_nodes()
        # Task 1 is the only root
        assert roots == [1]

    def test_get_root_nodes_multiple_roots(self, disconnected_graphs):
        """Handles multiple root nodes"""
        validator = DependencyValidator(disconnected_graphs)
        renderer = ASCIIGraphRenderer(validator)

        roots = renderer._get_root_nodes()
        # Tasks 1 and 3 are roots
        assert set(roots) == {1, 3}

    def test_topological_sort_valid_dag(self, valid_dag):
        """Topological sort returns all tasks in valid dependency order"""
        validator = DependencyValidator(valid_dag)
        renderer = ASCIIGraphRenderer(validator)

        sorted_order = renderer._topological_sort()

        # Should return all 4 tasks
        assert len(sorted_order) == 4
        assert set(sorted_order) == {1, 2, 3, 4}

        # Build a map of task positions
        position = {task_id: idx for idx, task_id in enumerate(sorted_order)}

        # Verify topological order: for each task, all its dependencies appear before it
        # Task 2 depends on [1], so 1 must appear before 2
        # Task 3 depends on [1], so 1 must appear before 3
        # Task 4 depends on [2, 3], so both 2 and 3 must appear before 4
        for subtask in valid_dag["subtasks"]:
            task_id = subtask["id"]
            for dep in subtask.get("dependencies", []):
                assert (
                    position[dep] < position[task_id]
                ), f"Dependency {dep} should appear before {task_id} in topological order"

    def test_topological_sort_with_cycle(self, cyclic_dependencies):
        """Topological sort handles cycles gracefully"""
        validator = DependencyValidator(cyclic_dependencies)
        renderer = ASCIIGraphRenderer(validator)

        sorted_order = renderer._topological_sort()

        # Should return all tasks (partial order)
        assert len(sorted_order) == 3
        assert set(sorted_order) == {1, 2, 3}

    def test_legend_displayed(self, simple_linear_chain):
        """Legend shows color meanings"""
        validator = DependencyValidator(simple_linear_chain)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        assert "Legend:" in output
        assert "Valid task" in output
        assert "warnings" in output
        assert "critical issues" in output

    def test_issue_summary_displayed(self, cyclic_dependencies):
        """Shows issue counts in header"""
        validator = DependencyValidator(cyclic_dependencies)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        assert "Issues:" in output
        assert "critical" in output

    def test_max_depth_prevents_deep_recursion(self, large_graph):
        """max_depth parameter limits rendering depth"""
        validator = DependencyValidator(large_graph)
        renderer = ASCIIGraphRenderer(validator)

        # Render with low max_depth
        output_shallow = renderer.render(use_colors=False, max_depth=5)
        output_deep = renderer.render(use_colors=False, max_depth=50)

        # Shallow should be shorter
        assert len(output_shallow) < len(output_deep)

    def test_large_graph_rendering_performance(self, large_graph):
        """Large graph renders in reasonable time"""
        import time

        validator = DependencyValidator(large_graph)
        renderer = ASCIIGraphRenderer(validator)

        start = time.time()
        output = renderer.render(use_colors=False)
        elapsed = time.time() - start

        # Should complete in < 2 seconds
        assert elapsed < 2.0
        assert len(output) > 0

    def test_orphaned_tasks_displayed(self, orphaned_tasks):
        """Orphaned tasks appear in visualization"""
        validator = DependencyValidator(orphaned_tasks)
        validator.validate_all()
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False)

        # All tasks should be visible
        assert "Task 1" in output
        assert "Task 2" in output
        assert "Task 3" in output
        assert "Task 4" in output

    def test_max_width_truncates_long_lines(self):
        """max_width parameter truncates lines exceeding limit"""
        # Create task with very long title
        data = {
            "subtasks": [
                {"id": 1, "title": "A" * 200, "dependencies": []},
                {"id": 2, "title": "Short", "dependencies": [1]},
            ]
        }
        validator = DependencyValidator(data)
        renderer = ASCIIGraphRenderer(validator)

        output = renderer.render(use_colors=False, max_width=50)

        # Check that lines are truncated
        for line in output.split("\n"):
            # Strip ANSI codes to measure visible length
            visible_line = renderer._strip_ansi(line)
            # Allow for "..." suffix
            assert len(visible_line) <= 53  # 50 + 3 for "..."

    def test_max_width_preserves_short_lines(self):
        """max_width doesn't affect lines shorter than limit"""
        data = {"subtasks": [{"id": 1, "title": "Short", "dependencies": []}]}
        validator = DependencyValidator(data)
        renderer = ASCIIGraphRenderer(validator)

        output_default = renderer.render(use_colors=False)
        output_limited = renderer.render(use_colors=False, max_width=200)

        # Short lines should be identical
        assert output_default == output_limited


# ============================================================================
# CLI Integration Tests
# ============================================================================


class TestCLIIntegration:
    """Test command-line interface"""

    def test_load_input_from_file(self, tmp_path, simple_linear_chain):
        """Loads JSON from file path"""
        test_file = tmp_path / "test.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        data = load_input(str(test_file))
        assert data == simple_linear_chain

    def test_load_input_from_stdin(self, simple_linear_chain):
        """Loads JSON from stdin"""
        stdin_data = json.dumps(simple_linear_chain)
        with mock.patch("sys.stdin", StringIO(stdin_data)):
            data = load_input(None)
            assert data == simple_linear_chain

    def test_load_input_invalid_json(self, tmp_path):
        """Raises error for malformed JSON"""
        test_file = tmp_path / "invalid.json"
        with open(test_file, "w") as f:
            f.write("not valid json {")

        with pytest.raises(ValueError, match="Invalid JSON input"):
            load_input(str(test_file))

    def test_load_input_file_not_found(self):
        """Raises error for non-existent file"""
        with pytest.raises(ValueError, match="File not found"):
            load_input("/nonexistent/file.json")

    def test_main_valid_input_exit_0(self, tmp_path, simple_linear_chain):
        """Valid input exits with code 0"""
        test_file = tmp_path / "valid.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        with mock.patch("sys.argv", ["validate-dependencies.py", str(test_file)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_invalid_graph_exit_1(self, tmp_path, cyclic_dependencies):
        """Invalid graph exits with code 1"""
        test_file = tmp_path / "cyclic.json"
        with open(test_file, "w") as f:
            json.dump(cyclic_dependencies, f)

        with mock.patch("sys.argv", ["validate-dependencies.py", str(test_file)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_main_malformed_input_exit_2(self, tmp_path):
        """Malformed input exits with code 2"""
        test_file = tmp_path / "malformed.json"
        with open(test_file, "w") as f:
            f.write("{invalid json}")

        with mock.patch("sys.argv", ["validate-dependencies.py", str(test_file)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2

    def test_main_visualize_flag(self, tmp_path, simple_linear_chain, capsys):
        """--visualize flag displays ASCII tree"""
        test_file = tmp_path / "test.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        with mock.patch(
            "sys.argv", ["validate-dependencies.py", "--visualize", str(test_file)]
        ), pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        assert "Task Dependency Graph" in captured.out
        assert "Task 1" in captured.out

    def test_main_no_color_flag(self, tmp_path, simple_linear_chain, capsys):
        """--no-color flag removes ANSI codes"""
        test_file = tmp_path / "test.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        with mock.patch(
            "sys.argv",
            ["validate-dependencies.py", "--visualize", "--no-color", str(test_file)],
        ), pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        # No ANSI escape sequences
        assert "\033[" not in captured.out

    def test_main_text_format(self, tmp_path, simple_linear_chain, capsys):
        """--format text outputs human-readable report"""
        test_file = tmp_path / "test.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        with mock.patch(
            "sys.argv", ["validate-dependencies.py", "-f", "text", str(test_file)]
        ), pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        assert "Validation Report" in captured.out
        assert "Total Tasks:" in captured.out

    def test_main_json_format(self, tmp_path, simple_linear_chain, capsys):
        """--format json outputs structured JSON"""
        test_file = tmp_path / "test.json"
        with open(test_file, "w") as f:
            json.dump(simple_linear_chain, f)

        with mock.patch(
            "sys.argv", ["validate-dependencies.py", "-f", "json", str(test_file)]
        ), pytest.raises(SystemExit):
            main()

        captured = capsys.readouterr()
        # Should be valid JSON
        output_data = json.loads(captured.out)
        assert "valid" in output_data
        assert "total_tasks" in output_data


# ============================================================================
# Edge Cases and Regression Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_empty_task_list(self):
        """Handles empty subtasks list"""
        data = {"subtasks": []}
        validator = DependencyValidator(data)
        assert validator.validate_all() is True
        assert len(validator.issues) == 0

    def test_single_task_no_deps(self):
        """Single task with no dependencies is valid (but triggers orphan warning)"""
        data = {"subtasks": [{"id": 1, "title": "Solo", "dependencies": []}]}
        validator = DependencyValidator(data)
        # Single isolated task has no edges, so it's considered orphaned (WARNING)
        # This is still technically "valid" (no CRITICAL issues), but has warnings
        is_valid = validator.validate_all()
        # validate_all returns True only if ALL validations pass
        # Orphan check returns False (warning found)
        assert is_valid is False  # Has orphan warning
        # But no CRITICAL issues
        report = validator.get_report()
        assert report["critical_issues"] == 0
        assert report["warnings"] == 1  # One orphan warning

    def test_task_without_title(self):
        """Tasks without titles are handled gracefully"""
        data = {"subtasks": [{"id": 1, "dependencies": []}]}
        validator = DependencyValidator(data)
        assert validator.get_task_title(1) == ""

    def test_multiple_cycles(self):
        """Detects multiple independent cycles"""
        data = {
            "subtasks": [
                # Cycle 1: 1 -> 2 -> 1
                {"id": 1, "dependencies": [2]},
                {"id": 2, "dependencies": [1]},
                # Cycle 2: 3 -> 4 -> 3
                {"id": 3, "dependencies": [4]},
                {"id": 4, "dependencies": [3]},
            ]
        }
        validator = DependencyValidator(data)
        assert validator.validate_circular_dependencies() is False
        # Should detect at least one cycle (may detect both)
        cycle_issues = [
            i for i in validator.issues if i.issue_type == "circular_dependency"
        ]
        assert len(cycle_issues) >= 1

    def test_complex_cycle_detection(self):
        """Detects cycle in complex graph"""
        data = {
            "subtasks": [
                {"id": 1, "dependencies": []},
                {"id": 2, "dependencies": [1]},
                {"id": 3, "dependencies": [2]},
                {"id": 4, "dependencies": [3]},
                # Task 5 depends on 4 and 2
                # This creates two paths to node 5: (1->2->3->4->5) and (1->2->5)
                # Multiple paths to the same node do NOT create a cycle in a DAG
                # This is valid: 5 depends on both 2 and 4 (diamond dependency pattern)
                # A cycle would only exist if 2 depended on 5 (closing the loop)
                {"id": 5, "dependencies": [4, 2]},
            ]
        }
        validator = DependencyValidator(data)
        # This is actually a valid DAG, not a cycle
        # Task 5 has two dependencies (2 and 4), both reachable without cycles
        assert (
            validator.validate_circular_dependencies() is True
        )  # Valid DAG - no cycle detected

        # To create an actual cycle, we need to introduce a dependency from a descendant back to an ancestor (creates a cycle):
        cyclic_data = {
            "subtasks": [
                {"id": 1, "dependencies": []},
                {"id": 2, "dependencies": [1, 5]},  # 2 depends on 5 - creates cycle!
                {"id": 3, "dependencies": [2]},
                {"id": 4, "dependencies": [3]},
                {"id": 5, "dependencies": [4]},
            ]
        }
        cyclic_validator = DependencyValidator(cyclic_data)
        assert cyclic_validator.validate_circular_dependencies() is False

    def test_non_integer_dependency_id(self):
        """Raises error for string dependency IDs"""
        data = {"subtasks": [{"id": 1, "dependencies": ["2"]}]}  # String instead of int
        with pytest.raises(ValueError, match="Dependency ID must be integer"):
            DependencyValidator(data)

    def test_duplicate_task_ids(self):
        """Handles duplicate task IDs (last one wins)"""
        data = {
            "subtasks": [
                {"id": 1, "title": "First", "dependencies": []},
                {"id": 1, "title": "Duplicate", "dependencies": []},  # Duplicate ID
            ]
        }
        # Should not crash, but behavior is undefined
        # In practice, _build_graph will process both, title lookup may return either
        validator = DependencyValidator(data)
        # At least validate it doesn't crash
        assert validator.task_ids == {1}
