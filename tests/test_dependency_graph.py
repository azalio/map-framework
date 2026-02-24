"""
Tests for dependency_graph.py - cascade invalidation logic.

Validates the three validation criteria from ST-004:
1. invalidate_cascade() returns all transitive dependents
2. Circular dependency detection raises error or returns empty set
3. get_dependents() returns immediate dependents only
"""

import pytest
from mapify_cli.dependency_graph import DependencyGraph, SubtaskNode


class TestGetDependentsImmediate:
    """Criterion 3: get_dependents() returns immediate dependents only."""

    def test_immediate_dependents_only_one_hop(self):
        """get_dependents() should return only direct dependents, not transitive."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-003"]))

        # ST-001 has immediate dependent ST-002, but NOT ST-003 or ST-004
        dependents = graph.get_dependents("ST-001")
        assert dependents == [
            "ST-002"
        ], f"Expected only immediate dependent ST-002, got {dependents}"

    def test_get_dependents_multiple_immediate(self):
        """get_dependents() returns all immediate dependents (multiple children)."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-001"]))

        dependents = graph.get_dependents("ST-001")
        assert set(dependents) == {"ST-002", "ST-003", "ST-004"}

    def test_get_dependents_no_dependents(self):
        """get_dependents() returns empty list if no dependents."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        # ST-002 has no dependents (leaf node)
        dependents = graph.get_dependents("ST-002")
        assert dependents == []

    def test_get_dependents_node_not_in_graph(self):
        """get_dependents() returns empty list if node not in graph."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))

        dependents = graph.get_dependents("ST-999")
        assert dependents == []


class TestInvalidateCascadeTransitive:
    """Criterion 1: invalidate_cascade() returns all transitive dependents."""

    def test_invalidate_cascade_linear_chain(self):
        """invalidate_cascade() returns all transitive dependents in linear chain."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-003"]))

        # Invalidating ST-001 should cascade to ST-002, ST-003, ST-004
        invalidated = graph.invalidate_cascade("ST-001")
        assert set(invalidated) == {"ST-001", "ST-002", "ST-003", "ST-004"}

    def test_invalidate_cascade_diamond_shape(self):
        """invalidate_cascade() handles diamond-shaped dependencies."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-002", "ST-003"]))

        # Invalidating ST-001 should cascade through both branches to ST-004
        invalidated = graph.invalidate_cascade("ST-001")
        assert set(invalidated) == {"ST-001", "ST-002", "ST-003", "ST-004"}

    def test_invalidate_cascade_partial_tree(self):
        """invalidate_cascade() only invalidates affected subtree."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-003"]))

        # Invalidating ST-001 should NOT affect ST-003 or ST-004
        invalidated = graph.invalidate_cascade("ST-001")
        assert set(invalidated) == {"ST-001", "ST-002"}

    def test_invalidate_cascade_includes_self(self):
        """invalidate_cascade() includes the invalidated node itself."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))

        invalidated = graph.invalidate_cascade("ST-001")
        assert "ST-001" in invalidated

    def test_invalidate_cascade_node_not_in_graph(self):
        """invalidate_cascade() returns single-element list if node not found."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))

        invalidated = graph.invalidate_cascade("ST-999")
        assert invalidated == ["ST-999"]


class TestCircularDependencyDetection:
    """Criterion 2: Circular dependency detection raises error or returns empty set."""

    def test_invalidate_cascade_handles_circular_dependencies(self):
        """invalidate_cascade() handles circular dependencies without infinite loop."""
        graph = DependencyGraph()
        # Create cycle: ST-001 -> ST-002 -> ST-003 -> ST-001
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-003"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))

        # Should terminate and return all nodes in cycle
        invalidated = graph.invalidate_cascade("ST-001")
        assert set(invalidated) == {"ST-001", "ST-002", "ST-003"}

    def test_invalidate_cascade_self_dependency_ignored(self):
        """invalidate_cascade() ignores self-dependencies."""
        graph = DependencyGraph()
        # Self-dependency should be ignored in traversal
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        invalidated = graph.invalidate_cascade("ST-001")
        assert set(invalidated) == {"ST-001", "ST-002"}

    def test_has_cycle_detects_simple_cycle(self):
        """has_cycle() detects simple two-node cycle."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        assert graph.has_cycle() is True

    def test_has_cycle_detects_long_cycle(self):
        """has_cycle() detects multi-node cycle."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-003"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-004"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-001"]))

        assert graph.has_cycle() is True

    def test_has_cycle_no_cycle_in_dag(self):
        """has_cycle() returns False for valid DAG."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001", "ST-002"]))

        assert graph.has_cycle() is False


class TestEdgeCases:
    """Additional edge case validation."""

    def test_empty_graph(self):
        """Operations on empty graph return sensible defaults."""
        graph = DependencyGraph()

        assert graph.get_dependents("ST-001") == []
        assert graph.invalidate_cascade("ST-001") == ["ST-001"]
        assert graph.has_cycle() is False
        assert graph.get_root_nodes() == []

    def test_topological_sort_returns_none_on_cycle(self):
        """topological_sort() returns None if cycle detected."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        assert graph.topological_sort() is None

    def test_topological_sort_valid_dag(self):
        """topological_sort() returns valid ordering for DAG."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001", "ST-002"]))

        result = graph.topological_sort()
        assert result is not None
        # ST-001 must come before ST-002 and ST-003
        assert result.index("ST-001") < result.index("ST-002")
        assert result.index("ST-001") < result.index("ST-003")
        # ST-002 must come before ST-003 (since ST-003 depends on ST-002)
        assert result.index("ST-002") < result.index("ST-003")


class TestComputeWaves:
    """Tests for compute_waves() - topological wave computation."""

    def test_linear_chain_produces_single_subtask_waves(self):
        """Linear chain: each subtask in its own wave."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))

        waves = graph.compute_waves()
        assert waves == [["ST-001"], ["ST-002"], ["ST-003"]]

    def test_fan_out_produces_parallel_wave(self):
        """Fan-out: root node then all dependents in one wave."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-001"]))

        waves = graph.compute_waves()
        assert waves == [["ST-001"], ["ST-002", "ST-003", "ST-004"]]

    def test_diamond_produces_three_waves(self):
        """Diamond DAG: root, two parallel, then merge node."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
        graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-002", "ST-003"]))

        waves = graph.compute_waves()
        assert waves == [["ST-001"], ["ST-002", "ST-003"], ["ST-004"]]

    def test_cycle_returns_none(self):
        """Cycle in graph should return None."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        assert graph.compute_waves() is None

    def test_empty_graph_returns_empty_list(self):
        """Empty graph returns empty list."""
        graph = DependencyGraph()
        assert graph.compute_waves() == []

    def test_single_node_returns_single_wave(self):
        """Single node returns one wave with one element."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))

        assert graph.compute_waves() == [["ST-001"]]

    def test_multiple_roots_in_first_wave(self):
        """Multiple independent roots all appear in wave 0."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=[]))
        graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001", "ST-002"]))

        waves = graph.compute_waves()
        assert waves == [["ST-001", "ST-002"], ["ST-003"]]

    def test_dangling_dependency_treated_as_root(self):
        """Node with dependency not in graph is treated as having no deps."""
        graph = DependencyGraph()
        graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-MISSING"]))
        graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))

        waves = graph.compute_waves()
        assert waves == [["ST-001"], ["ST-002"]]


class TestSplitWaveByFileConflicts:
    """Tests for split_wave_by_file_conflicts()."""

    def test_no_overlap_single_sub_wave(self):
        """No file overlap: all subtasks in one sub-wave."""
        graph = DependencyGraph()
        wave = ["ST-002", "ST-003", "ST-004"]
        files = {
            "ST-002": {"a.py"},
            "ST-003": {"b.py"},
            "ST-004": {"c.py"},
        }
        result = graph.split_wave_by_file_conflicts(wave, files)
        assert result == [["ST-002", "ST-003", "ST-004"]]

    def test_partial_overlap_splits_into_sub_waves(self):
        """Partial overlap: conflicting subtasks in separate sub-waves."""
        graph = DependencyGraph()
        wave = ["ST-002", "ST-003", "ST-004"]
        files = {
            "ST-002": {"a.py"},
            "ST-003": {"b.py"},
            "ST-004": {"a.py"},
        }
        result = graph.split_wave_by_file_conflicts(wave, files)
        assert result == [["ST-002", "ST-003"], ["ST-004"]]

    def test_all_overlap_each_in_own_sub_wave(self):
        """All subtasks share files: each in its own sub-wave."""
        graph = DependencyGraph()
        wave = ["ST-001", "ST-002", "ST-003"]
        files = {
            "ST-001": {"shared.py"},
            "ST-002": {"shared.py"},
            "ST-003": {"shared.py"},
        }
        result = graph.split_wave_by_file_conflicts(wave, files)
        assert result == [["ST-001"], ["ST-002"], ["ST-003"]]

    def test_empty_affected_files_placed_alone(self):
        """Subtasks with empty affected_files are placed in their own sub-wave."""
        graph = DependencyGraph()
        wave = ["ST-001", "ST-002", "ST-003"]
        files = {
            "ST-001": {"a.py"},
            "ST-002": set(),  # empty = unknown
            "ST-003": {"b.py"},
        }
        result = graph.split_wave_by_file_conflicts(wave, files)
        # ST-002 should be alone, ST-001 and ST-003 can be together
        assert ["ST-002"] in result
        assert ["ST-001", "ST-003"] in result

    def test_missing_from_map_treated_as_empty(self):
        """Subtask not in affected_files_map treated as empty (placed alone)."""
        graph = DependencyGraph()
        wave = ["ST-001", "ST-002"]
        files = {"ST-001": {"a.py"}}  # ST-002 missing
        result = graph.split_wave_by_file_conflicts(wave, files)
        assert ["ST-002"] in result

    def test_single_subtask_wave(self):
        """Single subtask wave returns as-is."""
        graph = DependencyGraph()
        result = graph.split_wave_by_file_conflicts(["ST-001"], {"ST-001": {"a.py"}})
        assert result == [["ST-001"]]

    def test_empty_wave(self):
        """Empty wave returns empty list."""
        graph = DependencyGraph()
        assert graph.split_wave_by_file_conflicts([], {}) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
