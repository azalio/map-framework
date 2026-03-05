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

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from collections import deque


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
    dependencies: List[str] = field(default_factory=list)
    outputs: Optional[List[str]] = None
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
        self.nodes: Dict[str, SubtaskNode] = {}

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

    def get_dependents(self, subtask_id: str) -> List[str]:
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

    def invalidate_cascade(self, subtask_id: str) -> List[str]:
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
        invalidated: Set[str] = {subtask_id}
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

    def get_root_nodes(self) -> List[str]:
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

        colors: Dict[str, int] = {node_id: WHITE for node_id in self.nodes}

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
                    if colors[dep_id] == WHITE:
                        if dfs(dep_id):
                            return True

            colors[node_id] = BLACK
            return False

        # Try DFS from each unvisited node
        for node_id in self.nodes:
            if colors[node_id] == WHITE:
                if dfs(node_id):
                    return True

        return False

    def topological_sort(self) -> Optional[List[str]]:
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

        visited: Set[str] = set()
        result: List[str] = []

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

    def compute_waves(self) -> Optional[List[List[str]]]:
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
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        for nid, node in self.nodes.items():
            for dep_id in node.dependencies:
                if dep_id in self.nodes:
                    in_degree[nid] += 1

        # Collect initial zero-in-degree nodes as wave 0
        waves: List[List[str]] = []
        current_wave = sorted([nid for nid, deg in in_degree.items() if deg == 0])

        processed = 0
        while current_wave:
            waves.append(current_wave)
            processed += len(current_wave)
            next_wave_set: Set[str] = set()

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
        self, wave: List[str], affected_files_map: Dict[str, Set[str]]
    ) -> List[List[str]]:
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

        sub_waves: List[List[str]] = []
        sub_wave_files: List[Set[str]] = []

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
