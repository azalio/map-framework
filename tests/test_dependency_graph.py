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
        assert dependents == ["ST-002"], f"Expected only immediate dependent ST-002, got {dependents}"

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
