"""
Tests for dependency_graph.py - cascade invalidation logic.

Validates the three validation criteria from ST-004:
1. invalidate_cascade() returns all transitive dependents
2. Circular dependency detection raises error or returns empty set
3. get_dependents() returns immediate dependents only
"""

import pytest

from mapify_cli.dependency_graph import (
    DependencyGraph,
    LintFinding,
    SubtaskNode,
    lint_dependency_graph,
)
from tests.fixtures.wave_blueprints import conflict_split, linear_chain


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


class TestLintDependencyGraphLayerA:
    """ST-006: Layer A hard-error lint checks (always on)."""

    def test_layer_a_hard_errors(self):
        """Layer A detects self_loop, cycle, unknown_dep, duplicate_edge; valid DAG → zero errors."""
        # --- self_loop ---
        g = DependencyGraph()
        g.add_node(SubtaskNode(id="ST-001", dependencies=["ST-001"]))
        findings = lint_dependency_graph(g)
        codes = [f.code for f in findings if f.severity == "error"]
        assert "self_loop" in codes, f"Expected self_loop, got: {codes}"

        # --- cycle (2-node) ---
        g2 = DependencyGraph()
        g2.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
        g2.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        findings2 = lint_dependency_graph(g2)
        codes2 = [f.code for f in findings2 if f.severity == "error"]
        assert "cycle" in codes2, f"Expected cycle, got: {codes2}"
        # self_loop must NOT be reported for a pure 2-node cycle
        assert "self_loop" not in codes2, f"self_loop falsely reported for 2-node cycle: {codes2}"

        # --- unknown_dep ---
        g3 = DependencyGraph()
        g3.add_node(SubtaskNode(id="ST-001", dependencies=["ST-MISSING"]))
        findings3 = lint_dependency_graph(g3)
        codes3 = [f.code for f in findings3 if f.severity == "error"]
        assert "unknown_dep" in codes3, f"Expected unknown_dep, got: {codes3}"

        # --- duplicate_edge ---
        g4 = DependencyGraph()
        g4.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g4.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001", "ST-001"]))
        findings4 = lint_dependency_graph(g4)
        codes4 = [f.code for f in findings4 if f.severity == "error"]
        assert "duplicate_edge" in codes4, f"Expected duplicate_edge, got: {codes4}"

        # --- valid DAG → zero error-severity findings ---
        g5 = DependencyGraph()
        g5.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g5.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        g5.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001", "ST-002"]))
        findings5 = lint_dependency_graph(g5)
        errors5 = [f for f in findings5 if f.severity == "error"]
        assert errors5 == [], f"Valid DAG should produce no errors, got: {errors5}"

    def test_layer_a_always_on(self):
        """Layer A errors are emitted for all enforcement values (always on)."""
        # Graph with a self-loop — triggers a Layer A error regardless of enforcement
        for enforcement in ("off", "warn", "repair_once", "strict"):
            g = DependencyGraph()
            g.add_node(SubtaskNode(id="ST-001", dependencies=["ST-001"]))
            findings = lint_dependency_graph(g, enforcement=enforcement)
            errors = [f for f in findings if f.severity == "error" and f.code == "self_loop"]
            assert errors, (
                f"Layer A self_loop error must be emitted for enforcement={enforcement!r}, "
                f"but got: {findings}"
            )


class TestLintDependencyGraphLayerB:
    """ST-007: Layer B warn-only mechanical edge check + INFO metrics."""

    def test_layer_b_thin_edge_and_samefile_info(self):
        """
        VC1: thin edge (empty io∩ AND empty files∩) → warning;
             real data-flow edge → no thin_edge warning;
             same-file pair in one wave → INFO (not error).

        Uses two_wave_parallel (for thin/real edge checks) and
        conflict_split (for same-file coloring in a wave).
        """
        # ---- thin_edge: build a graph with a deliberate ordering-only edge ----
        # ST-A -> ST-B: no shared io, no shared files → thin
        g = DependencyGraph()
        g.add_node(SubtaskNode(id="ST-A", dependencies=[]))
        g.add_node(SubtaskNode(id="ST-B", dependencies=["ST-A"]))
        afm = {
            "ST-A": {"src/alpha.py"},
            "ST-B": {"src/beta.py"},  # disjoint files
        }
        # io that also have no overlap
        io = {
            "ST-A": {"inputs": set(), "outputs": {"out_a.txt"}},
            "ST-B": {"inputs": {"in_b.txt"}, "outputs": {"out_b.txt"}},  # in_b ≠ out_a
        }
        findings = lint_dependency_graph(g, affected_files_map=afm, node_io=io)
        assert all(isinstance(f, LintFinding) for f in findings)
        thin = [f for f in findings if f.code == "thin_edge"]
        assert thin, f"Expected thin_edge warning, got: {[f.code for f in findings]}"
        assert thin[0].severity == "warning"
        assert thin[0].edge == ("ST-A", "ST-B")

        # ---- real data-flow edge: shared output/input → NOT flagged as thin ----
        g2 = DependencyGraph()
        g2.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g2.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        # outputs config.yaml; inputs config.yaml (real data-flow)
        io2 = {
            "ST-001": {"inputs": set(), "outputs": {"config.yaml"}},
            "ST-002": {"inputs": {"config.yaml"}, "outputs": {"service_a.py"}},
        }
        afm2 = {"ST-001": {"config.yaml"}, "ST-002": {"src/service_a.py"}}
        findings2 = lint_dependency_graph(g2, affected_files_map=afm2, node_io=io2)
        thin2 = [f for f in findings2 if f.code == "thin_edge"]
        assert not thin2, f"Real data-flow edge must NOT be flagged thin; got: {thin2}"

        # ---- same_file_coloring: two subtasks in same wave share a file → INFO ----
        fix2 = conflict_split()
        g3 = fix2.build_graph()
        # and share src/shared.py in wave 1
        findings3 = lint_dependency_graph(g3, affected_files_map=fix2.affected_files_map)
        coloring = [f for f in findings3 if f.code == "same_file_coloring"]
        assert coloring, (
            f"Expected same_file_coloring INFO for ST-002/ST-004 sharing src/shared.py; "
            f"codes: {[f.code for f in findings3]}"
        )
        assert all(f.severity == "info" for f in coloring), (
            f"same_file_coloring must be severity='info', got: {coloring}"
        )
        # must NOT be severity='error'
        errors = [f for f in findings3 if f.severity == "error"]
        assert not errors, f"No errors expected for valid conflict_split DAG; got: {errors}"

    def test_fully_serialized_and_redundant_and_default_warn(self):
        """
        VC2: linear_chain (N=4, all width-1) → fully_serialized warning;
             redundant edge (A->C where A->B->C) → INFO;
             enforcement='off' → Layer B silent (only Layer A);
             auto_prune=True performs NO mutation (graph unchanged);
             default enforcement='warn' emits Layer B findings.
        """
        # ---- fully_serialized: linear_chain has N=4 and max wave width=1 ----
        fix = linear_chain()
        g = fix.build_graph()
        findings = lint_dependency_graph(
            g, affected_files_map=fix.affected_files_map, enforcement="warn"
        )
        assert all(isinstance(f, LintFinding) for f in findings)
        serialized = [f for f in findings if f.code == "fully_serialized"]
        assert serialized, (
            f"Expected fully_serialized warning for 4-node linear chain; "
            f"codes: {[f.code for f in findings]}"
        )
        assert serialized[0].severity == "warning"

        # ---- redundant_edge: A->B->C AND A->C → A->C is redundant ----
        g2 = DependencyGraph()
        g2.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g2.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        # depends on directly AND via → -> is redundant
        g2.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002", "ST-001"]))
        findings2 = lint_dependency_graph(g2)
        redundant = [f for f in findings2 if f.code == "redundant_edge"]
        assert redundant, (
            f"Expected redundant_edge INFO for ST-001->ST-003 (also reachable via ST-002); "
            f"codes: {[f.code for f in findings2]}"
        )
        assert all(f.severity == "info" for f in redundant)

        # ---- enforcement='off' → Layer B silent; Layer A still runs ----
        g3 = DependencyGraph()
        g3.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g3.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        g3.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002", "ST-001"]))
        findings_off = lint_dependency_graph(g3, enforcement="off")
        layer_b_off = [
            f for f in findings_off
            if f.code in ("thin_edge", "same_file_coloring", "fully_serialized", "redundant_edge")
        ]
        assert not layer_b_off, (
            f"enforcement='off' must suppress ALL Layer B findings; got: {layer_b_off}"
        )

        # ---- auto_prune=True performs NO mutation: graph unchanged after lint ----
        g4 = DependencyGraph()
        g4.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g4.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        g4.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002", "ST-001"]))
        node_ids_before = set(g4.nodes.keys())
        deps_before = {nid: list(n.dependencies) for nid, n in g4.nodes.items()}
        lint_dependency_graph(g4, auto_prune=True)
        assert set(g4.nodes.keys()) == node_ids_before, "auto_prune must not remove nodes"
        for nid in node_ids_before:
            assert g4.nodes[nid].dependencies == deps_before[nid], (
                f"auto_prune must not mutate dependencies of {nid}"
            )

        # ---- default enforcement='warn' emits Layer B (redundant_edge case) ----
        g5 = DependencyGraph()
        g5.add_node(SubtaskNode(id="ST-001", dependencies=[]))
        g5.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
        g5.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002", "ST-001"]))
        findings_default = lint_dependency_graph(g5)  # default enforcement='warn'
        layer_b_default = [
            f for f in findings_default
            if f.code in ("thin_edge", "same_file_coloring", "fully_serialized", "redundant_edge")
        ]
        assert layer_b_default, (
            f"Default enforcement='warn' must emit Layer B findings; "
            f"codes: {[f.code for f in findings_default]}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
