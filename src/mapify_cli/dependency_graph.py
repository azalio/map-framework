"""
Dependency Graph for MAP Framework subtask cascade invalidation.

Tracks dependencies between subtasks and computes transitive invalidation
when a subtask fails or changes. Used in re-decomposition logic to identify
which completed subtasks become invalid when an upstream dependency fails.

Performance targets:
- invalidate_cascade(): O(V+E) BFS traversal, <10ms for typical workflows (<50 subtasks)
- get_dependents(): O(V) linear scan, <5ms
- add_node(): O(1), <1ms

Example:
    >>> graph = DependencyGraph()
    >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[], status="completed"))
    >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"], status="completed"))
    >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"], status="completed"))
    >>> invalidated = graph.invalidate_cascade("ST-001")
    >>> invalidated
    ['ST-001', 'ST-002', 'ST-003']
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LintFinding:
    """
    A single finding from lint_dependency_graph.

    Attributes:
        severity: "error" | "warning" | "info"
        code: Machine-readable finding code (e.g. "self_loop", "cycle")
        message: Human-readable description
        subtask_id: The subtask this finding relates to, if applicable
        edge: The (from, to) edge this finding relates to, if applicable
    """

    severity: str
    code: str
    message: str
    subtask_id: str | None = None
    edge: tuple[str, str] | None = None


@dataclass
class SubtaskNode:
    """
    Represents a subtask node in the dependency graph.

    Attributes:
        id: Unique subtask identifier (e.g., 'ST-001', 'ST-042')
        dependencies: List of subtask IDs this subtask depends on
        outputs: Optional list of outputs produced by this subtask (for provenance tracking)
        status: Current status of subtask ('pending', 'completed', 'invalidated', 'preserved')
    """

    id: str
    dependencies: list[str] = field(default_factory=list)
    outputs: list[str] | None = None
    status: str = "pending"


class DependencyGraph:
    """
    Directed graph for tracking subtask dependencies and cascade invalidation.

    Maintains a forward dependency graph where edges point from dependency to dependent.
    Provides efficient cascade invalidation using BFS to find all transitive dependents.

    Edge case handling:
    - Circular dependencies: Detected via visited set in BFS (prevents infinite loops)
    - Missing nodes: invalidate_cascade() returns only the provided ID if not found
    - Self-dependencies: Ignored (subtask cannot depend on itself)
    - Empty dependencies: Valid (root nodes)

    Example workflow:
        1. Task decomposer creates subtasks with dependencies
        2. Add all subtasks to graph via add_node()
        3. If ST-002 fails, call invalidate_cascade("ST-002")
        4. Returns all subtasks that transitively depend on ST-002
        5. Re-decomposition logic can preserve subtasks not in invalidated set
    """

    def __init__(self):
        """Initialize empty dependency graph."""
        self.nodes: dict[str, SubtaskNode] = {}

    def add_node(self, node: SubtaskNode) -> None:
        """
        Add a subtask node to the graph.

        Args:
            node: SubtaskNode to add

        Edge cases:
            - Duplicate ID: Overwrites existing node (allows status updates)
            - Dependencies not yet added: Valid (dependencies can be added later)
            - Self-dependency in node.dependencies: Ignored in traversal

        Performance: O(1)

        Example:
            >>> graph = DependencyGraph()
            >>> node = SubtaskNode(id="ST-001", dependencies=[], status="completed")
            >>> graph.add_node(node)
        """
        self.nodes[node.id] = node

    def get_dependents(self, subtask_id: str) -> list[str]:
        """
        Get immediate dependents of a subtask (one hop only).

        Args:
            subtask_id: Subtask ID to find dependents for

        Returns:
            List of subtask IDs that directly depend on given subtask
            Returns empty list if subtask not in graph or has no dependents

        Edge cases:
            - Subtask not in graph: returns empty list
            - No dependents: returns empty list
            - Circular dependencies: returns only immediate dependents (no cycles)

        Performance: O(V) where V = number of nodes (linear scan)

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
            >>> graph.get_dependents("ST-001")
            ['ST-002', 'ST-003']
        """
        if subtask_id not in self.nodes:
            return []

        dependents = []
        for node_id, node in self.nodes.items():
            if node_id == subtask_id:
                continue
            if subtask_id in node.dependencies:
                dependents.append(node_id)

        return dependents

    def invalidate_cascade(self, subtask_id: str) -> list[str]:
        """
        Find all subtasks that must be invalidated when given subtask changes.

        Uses breadth-first search to find transitive closure of dependents.
        Handles circular dependencies via visited set (prevents infinite loops).

        Args:
            subtask_id: Subtask ID that was invalidated (failed or changed)

        Returns:
            List of all subtask IDs that transitively depend on given subtask,
            including the subtask itself. Order is arbitrary (not topological).

        Edge cases:
            - Subtask not in graph: returns [subtask_id] (single-element list)
            - No dependents: returns [subtask_id] (only the invalidated node)
            - Circular dependencies: terminates via visited set, returns all reachable nodes
            - Self-dependency: ignored (not followed in traversal)

        Performance: O(V+E) where V = nodes, E = edges (BFS traversal)

        Postcondition:
            invalidate_cascade(node) returns SET containing all nodes reachable via forward edges
            (matches contract from SUBTASK_ST_004__CONTRACTS)

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))
            >>> graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-001"]))
            >>> invalidated = graph.invalidate_cascade("ST-001")
            >>> set(invalidated)
            {'ST-001', 'ST-002', 'ST-003', 'ST-004'}

        Example (circular dependency):
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-003"]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-002"]))
            >>> invalidated = graph.invalidate_cascade("ST-001")
            >>> set(invalidated)
            {'ST-001', 'ST-002', 'ST-003'}
        """
        # Edge case: subtask not in graph
        if subtask_id not in self.nodes:
            return [subtask_id]

        # BFS to find all transitive dependents
        invalidated: set[str] = {subtask_id}
        queue = deque([subtask_id])

        while queue:
            current_id = queue.popleft()

            # Find all immediate dependents
            immediate_dependents = self.get_dependents(current_id)

            for dependent_id in immediate_dependents:
                # Skip if already processed (prevents cycles)
                if dependent_id in invalidated:
                    continue

                # Mark as invalidated and queue for processing
                invalidated.add(dependent_id)
                queue.append(dependent_id)

        # Return as list (order arbitrary, not topological)
        return list(invalidated)

    def get_root_nodes(self) -> list[str]:
        """
        Get all root nodes (subtasks with no dependencies).

        Returns:
            List of subtask IDs that have empty dependencies list

        Performance: O(V) where V = number of nodes

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.get_root_nodes()
            ['ST-001']
        """
        roots = []
        for node_id, node in self.nodes.items():
            if not node.dependencies:
                roots.append(node_id)
        return roots

    def has_cycle(self) -> bool:
        """
        Detect if graph contains any cycles.

        Uses DFS with color marking (white/gray/black):
        - White: unvisited
        - Gray: visiting (on current DFS path)
        - Black: visited (all descendants explored)

        Returns:
            True if cycle detected, False otherwise

        Performance: O(V+E) where V = nodes, E = edges (DFS traversal)

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=["ST-002"]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.has_cycle()
            True
        """
        # Color marking for DFS
        WHITE = 0  # Unvisited
        GRAY = 1  # Visiting (on current path)
        BLACK = 2  # Visited (fully explored)

        colors: dict[str, int] = {node_id: WHITE for node_id in self.nodes}

        def dfs(node_id: str) -> bool:
            """DFS helper. Returns True if cycle detected."""
            colors[node_id] = GRAY

            # Visit all nodes this one depends on
            node = self.nodes.get(node_id)
            if node:
                for dep_id in node.dependencies:
                    # Skip if dependency not in graph (dangling reference)
                    if dep_id not in colors:
                        continue

                    # Back edge (cycle detected)
                    if colors[dep_id] == GRAY:
                        return True

                    # Explore if unvisited
                    if colors[dep_id] == WHITE and dfs(dep_id):
                        return True

            colors[node_id] = BLACK
            return False

        # Try DFS from each unvisited node
        for node_id in self.nodes:
            if colors[node_id] == WHITE and dfs(node_id):
                return True

        return False

    def topological_sort(self) -> list[str] | None:
        """
        Return topological ordering of subtasks (dependencies first).

        Returns:
            List of subtask IDs in topological order, or None if cycle detected

        Performance: O(V+E) where V = nodes, E = edges (DFS-based)

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001", "ST-002"]))
            >>> graph.topological_sort()
            ['ST-001', 'ST-002', 'ST-003']
        """
        # Detect cycles first
        if self.has_cycle():
            return None

        visited: set[str] = set()
        result: list[str] = []

        def dfs(node_id: str) -> None:
            """DFS helper for topological sort."""
            if node_id in visited:
                return

            visited.add(node_id)

            # Visit dependencies first
            node = self.nodes.get(node_id)
            if node:
                for dep_id in node.dependencies:
                    if dep_id in self.nodes:
                        dfs(dep_id)

            # Add to result after all dependencies processed
            result.append(node_id)

        # Visit all nodes
        for node_id in self.nodes:
            dfs(node_id)

        return result

    def compute_waves(self) -> list[list[str]] | None:
        """
        Compute execution waves from the dependency DAG using Kahn's algorithm.

        Each wave contains subtasks whose dependencies are all satisfied by
        prior waves. Within a wave, subtasks can execute in parallel.

        Returns:
            List of waves (each wave is a list of subtask IDs), or None if
            cycle detected. Empty graph returns [].

        Performance: O(V+E) where V = nodes, E = edges

        Example:
            >>> graph = DependencyGraph()
            >>> graph.add_node(SubtaskNode(id="ST-001", dependencies=[]))
            >>> graph.add_node(SubtaskNode(id="ST-002", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-003", dependencies=["ST-001"]))
            >>> graph.add_node(SubtaskNode(id="ST-004", dependencies=["ST-002", "ST-003"]))
            >>> graph.compute_waves()
            [['ST-001'], ['ST-002', 'ST-003'], ['ST-004']]
        """
        if not self.nodes:
            return []

        # Compute in-degree for each node (only count edges to nodes in graph)
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    in_degree[nid] += 1

        # Collect initial zero-in-degree nodes as wave 0
        waves: list[list[str]] = []
        current_wave = sorted([nid for nid, deg in in_degree.items() if deg == 0])

        processed = 0
        while current_wave:
            waves.append(current_wave)
            processed += len(current_wave)
            next_wave_set: set[str] = set()

            for nid in current_wave:
                # Decrement in-degree for all dependents
                for dependent_id in self.get_dependents(nid):
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_wave_set.add(dependent_id)

            current_wave = sorted(next_wave_set)

        # If not all nodes processed, there's a cycle
        if processed != len(self.nodes):
            return None

        return waves

    def split_wave_by_file_conflicts(
        self, wave: list[str], affected_files_map: dict[str, set[str]]
    ) -> list[list[str]]:
        """
        Split a single wave into sub-waves where no two subtasks share files.

        Uses greedy coloring: each subtask is placed in the first sub-wave
        that has no file overlap. Subtasks with empty/unknown affected_files
        are treated as conflicting with all others (placed alone).

        Args:
            wave: List of subtask IDs in one wave
            affected_files_map: Dict mapping subtask_id -> set of affected file paths

        Returns:
            List of sub-waves where no two subtasks in the same sub-wave share files

        Example:
            >>> graph = DependencyGraph()
            >>> wave = ["ST-002", "ST-003", "ST-004"]
            >>> files = {"ST-002": {"a.py"}, "ST-003": {"b.py"}, "ST-004": {"a.py"}}
            >>> graph.split_wave_by_file_conflicts(wave, files)
            [['ST-002', 'ST-003'], ['ST-004']]
        """
        if len(wave) <= 1:
            return [wave] if wave else []

        sub_waves: list[list[str]] = []
        sub_wave_files: list[set[str]] = []

        for subtask_id in wave:
            files = affected_files_map.get(subtask_id, set())

            # Empty/unknown files = conflict with everything, place alone
            if not files:
                sub_waves.append([subtask_id])
                sub_wave_files.append(set())  # placeholder
                continue

            placed = False
            for i, sw_files in enumerate(sub_wave_files):
                # Skip sub-waves that contain an "unknown files" subtask
                # (those have empty sw_files but exist in sub_waves)
                if not sw_files and sub_waves[i]:
                    # This sub-wave has a subtask with unknown files
                    continue
                # Check for file overlap
                if not files & sw_files:
                    sub_waves[i].append(subtask_id)
                    sub_wave_files[i] |= files
                    placed = True
                    break

            if not placed:
                sub_waves.append([subtask_id])
                sub_wave_files.append(set(files))

        return sub_waves

    def clear(self) -> None:
        """
        Remove all nodes from graph.

        Performance: O(1) (dict clear is constant time)
        """
        self.nodes.clear()

    def size(self) -> int:
        """
        Get number of nodes in graph.

        Returns:
            Number of subtask nodes in graph

        Performance: O(1)
        """
        return len(self.nodes)


_SOFT_PHRASES = (
    "logical ordering",
    "do this first",
    "natural order",
    "for safety",
)


def soft_phrase_findings(
    justifications: dict[tuple[str, str], str],
) -> list[LintFinding]:
    """
    Flag edge justifications containing soft/vague ordering phrases.

    Args:
        justifications: mapping of (from_id, to_id) -> justification text

    Returns:
        LintFinding list with severity 'info' or 'warning' for flagged edges.
    """
    results: list[LintFinding] = []
    for edge, text in justifications.items():
        lower = text.lower()
        for phrase in _SOFT_PHRASES:
            if phrase in lower:
                results.append(
                    LintFinding(
                        severity="warning",
                        code="soft_phrase",
                        message=(
                            f"Edge {edge[0]!r} -> {edge[1]!r} justification contains "
                            f"vague ordering phrase {phrase!r}: {text!r}"
                        ),
                        edge=edge,
                    )
                )
                break  # one finding per edge
    return results


def _transitive_deps(graph: "DependencyGraph", node_id: str) -> set[str]:
    """Return set of all nodes reachable from node_id via dependency edges (BFS)."""
    visited: set[str] = set()
    queue = list(graph.nodes.get(node_id, SubtaskNode(id=node_id)).dependencies)
    while queue:
        dep = queue.pop()
        if dep in visited or dep not in graph.nodes:
            continue
        visited.add(dep)
        queue.extend(graph.nodes[dep].dependencies)
    return visited


def lint_dependency_graph(
    graph: "DependencyGraph",
    *,
    affected_files_map: dict[str, set[str]] | None = None,
    node_io: dict[str, dict[str, Any]] | None = None,
    enforcement: str = "warn",
    auto_prune: bool = False,
) -> list[LintFinding]:
    """
    Lint a DependencyGraph and return structured findings.

    Layer A (always on, severity='error', regardless of enforcement):
      - self_loop       : a subtask lists its own id in dependencies
      - cycle           : a real cycle among >=2 distinct nodes
      - unknown_dep     : a dependency id not present in graph.nodes
      - duplicate_edge  : the same dependency id listed more than once

    Layer B (warn-only; skipped when enforcement=='off'):
      - thin_edge            : edge A->B with empty io-overlap AND empty file-overlap (warning)
      - same_file_coloring   : two subtasks in same wave share a file (info)
      - fully_serialized     : N>=4 nodes and max wave width==1 (warning)
      - redundant_edge       : A->B where A is transitively reachable via other deps of B (info)
      - soft_phrase          : justification text contains vague ordering phrases (warning)

    auto_prune performs NO mutation in this slice (warn-only).

    Args:
        graph: DependencyGraph to lint
        affected_files_map: (Layer B) subtask_id -> set of affected file paths
        node_io: (Layer B) subtask_id -> {"inputs": set, "outputs": set,
                  optionally "dep_justifications": {dep_id: text}}
        enforcement: "off" suppresses Layer B; "warn"/"repair_once"/"strict" emit Layer B
        auto_prune: accepted but performs no mutation in this slice

    Returns:
        List of LintFinding instances.
    """
    # auto_prune is accepted but intentionally performs no mutation in this slice.
    del auto_prune

    findings: list[LintFinding] = []

    # --- Layer A: hard errors, always on ---

    # Pass 1: self-loops and duplicate edges (per-node, no graph-wide traversal needed)
    self_loop_nodes: set[str] = set()
    for node_id, node in graph.nodes.items():
        seen: set[str] = set()
        for dep in node.dependencies:
            if dep == node_id:
                # Report self-loop once per node even if listed multiple times
                if node_id not in self_loop_nodes:
                    self_loop_nodes.add(node_id)
                    findings.append(
                        LintFinding(
                            severity="error",
                            code="self_loop",
                            message=f"Subtask '{node_id}' lists itself as a dependency.",
                            subtask_id=node_id,
                            edge=(node_id, node_id),
                        )
                    )
            elif dep in seen:
                findings.append(
                    LintFinding(
                        severity="error",
                        code="duplicate_edge",
                        message=(
                            f"Subtask '{node_id}' lists dependency '{dep}' more than once."
                        ),
                        subtask_id=node_id,
                        edge=(node_id, dep),
                    )
                )
            else:
                seen.add(dep)

            # unknown_dep check (applies to self-loop deps too, but self-loop is primary)
            if dep != node_id and dep not in graph.nodes:
                findings.append(
                    LintFinding(
                        severity="error",
                        code="unknown_dep",
                        message=(
                            f"Subtask '{node_id}' depends on '{dep}' which is not in the graph."
                        ),
                        subtask_id=node_id,
                        edge=(node_id, dep),
                    )
                )

    # Pass 2: cycle detection on a self-loop-free view to avoid double-reporting.
    # Build a temporary graph excluding self-loop edges, then check has_cycle().
    if not self_loop_nodes or any(
        dep != node_id
        for node_id, node in graph.nodes.items()
        for dep in node.dependencies
        if dep in graph.nodes
    ):
        # Build a view with self-loop edges stripped
        clean_graph = DependencyGraph()
        for node_id, node in graph.nodes.items():
            clean_deps = [d for d in node.dependencies if d != node_id]
            clean_graph.add_node(
                SubtaskNode(
                    id=node_id,
                    dependencies=clean_deps,
                    outputs=node.outputs,
                    status=node.status,
                )
            )
        if clean_graph.has_cycle():
            findings.append(
                LintFinding(
                    severity="error",
                    code="cycle",
                    message="Dependency graph contains a cycle among 2 or more distinct nodes.",
                )
            )

    # --- Layer B: warn-only metrics; skipped when enforcement is "off" ---
    if enforcement == "off":
        return findings

    afm = affected_files_map or {}
    io = node_io or {}

    # thin_edge: edge A->B where A.outputs ∩ B.inputs == ∅ AND files(A) ∩ files(B) == ∅
    # Conservative: if data is absent for either node, do NOT flag (avoid false positives).
    for node_id, node in graph.nodes.items():
        b_io = io.get(node_id, {})
        b_inputs: set[str] = b_io.get("inputs", set()) or set()
        b_files: set[str] = afm.get(node_id, set()) or set()
        for dep_id in node.dependencies:
            if dep_id == node_id or dep_id not in graph.nodes:
                continue  # skip self-loops and unknown deps (Layer A already handles these)
            a_io = io.get(dep_id, {})
            a_outputs: set[str] = a_io.get("outputs", set()) or set()
            a_files: set[str] = afm.get(dep_id, set()) or set()
            # Conservative: if any side lacks io AND files data, skip
            if not (a_outputs or b_inputs) and not (a_files or b_files):
                continue  # both sides are empty — no data at all, skip
            # Real data-flow check: non-empty intersection on either dimension → not thin
            io_overlap = a_outputs & b_inputs
            file_overlap = a_files & b_files
            if io_overlap or file_overlap:
                continue  # real edge, not thin
            # Both intersections empty → candidate thin edge. Be conservative:
            # only flag when BOTH nodes have io data, otherwise an empty
            # intersection is just unknown io on one side (false positive).
            if not (a_io and b_io):
                continue
            findings.append(
                LintFinding(
                    severity="warning",
                    code="thin_edge",
                    message=(
                        f"Edge '{dep_id}' -> '{node_id}' has no io-overlap and no "
                        f"file-overlap; dependency may be ordering-only."
                    ),
                    edge=(dep_id, node_id),
                )
            )

    # same_file_coloring: two subtasks in the same wave share an affected file → INFO
    waves = graph.compute_waves()
    if waves and afm:
        for wave in waves:
            if len(wave) < 2:
                continue
            for i in range(len(wave)):
                for j in range(i + 1, len(wave)):
                    sid_a, sid_b = wave[i], wave[j]
                    fa = afm.get(sid_a, set()) or set()
                    fb = afm.get(sid_b, set()) or set()
                    if fa & fb:
                        findings.append(
                            LintFinding(
                                severity="info",
                                code="same_file_coloring",
                                message=(
                                    f"Subtasks '{sid_a}' and '{sid_b}' in the same wave "
                                    f"share affected files: {sorted(fa & fb)!r}. "
                                    f"Consider coloring (split_wave_by_file_conflicts)."
                                ),
                                edge=(sid_a, sid_b),
                            )
                        )

    # fully_serialized: N>=4 AND every wave has width==1 → one warning
    if waves is not None:
        n = len(graph.nodes)
        if n >= 4 and waves and max(len(w) for w in waves) == 1:
            findings.append(
                LintFinding(
                    severity="warning",
                    code="fully_serialized",
                    message=(
                        f"All {n} subtasks are fully serialized (every wave has width 1). "
                        f"Consider whether some can run in parallel."
                    ),
                )
            )

    # redundant_edge: A->B where A is also reachable transitively via other deps of B → INFO
    for node_id, node in graph.nodes.items():
        for dep_id in node.dependencies:
            if dep_id == node_id or dep_id not in graph.nodes:
                continue
            # Other deps of node_id (excluding dep_id itself)
            other_deps = [d for d in node.dependencies if d != dep_id and d in graph.nodes]
            # Check if dep_id is reachable transitively from any other dep
            for other in other_deps:
                if dep_id in _transitive_deps(graph, other):
                    findings.append(
                        LintFinding(
                            severity="info",
                            code="redundant_edge",
                            message=(
                                f"Edge '{dep_id}' -> '{node_id}' is redundant: "
                                f"'{dep_id}' is already reachable transitively via '{other}'."
                            ),
                            edge=(dep_id, node_id),
                        )
                    )
                    break  # one finding per edge

    # soft_phrase: scan dep_justifications in node_io if present
    justifications: dict[tuple[str, str], str] = {}
    for node_id, node_data in io.items():
        dep_justs = node_data.get("dep_justifications", {})
        if dep_justs:
            for dep_id, text in dep_justs.items():
                if isinstance(text, str):
                    justifications[(dep_id, node_id)] = text
    if justifications:
        findings.extend(soft_phrase_findings(justifications))

    return findings
