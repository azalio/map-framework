#!/usr/bin/env python3
"""
Dependency Validation Script for TaskDecomposer Output

Validates task decomposition JSON for:
- Circular dependencies (DFS cycle detection)
- Orphaned tasks (isolated nodes with no edges)
- Forward references (dependencies on non-existent tasks)
- Self-dependencies (task depends on itself)

Usage:
    # Via mapify CLI (recommended for pip install users)
    mapify validate graph <file> [--visualize] [--no-color] [-f json|text] [--strict]

    # Via Python script (for development)
    python scripts/validate-dependencies.py decomposer-output.json

Exit Codes:
    0: Valid task graph (no issues)
    1: Invalid task graph (issues detected)
    2: Invalid input (malformed JSON, missing fields)
"""

import sys
import json
import argparse
from typing import Dict, List, Set
from collections import defaultdict, deque
from enum import Enum


class IssueSeverity(Enum):
    """Issue severity levels."""

    CRITICAL = "critical"  # Blocks execution
    WARNING = "warning"  # May cause issues


class ANSIColors:
    """ANSI color codes for terminal output."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class ValidationIssue:
    """Represents a validation issue found in the task graph."""

    def __init__(
        self,
        issue_type: str,
        severity: IssueSeverity,
        affected_tasks: List[int],
        message: str,
    ):
        self.issue_type = issue_type
        self.severity = severity
        self.affected_tasks = affected_tasks
        self.message = message

    def to_dict(self) -> dict:
        """Convert issue to dictionary for JSON output."""
        return {
            "type": self.issue_type,
            "severity": self.severity.value,
            "affected_tasks": self.affected_tasks,
            "message": self.message,
        }


class DependencyValidator:
    """Validates task dependency graphs for common issues."""

    def __init__(self, tasks_data: dict):
        """
        Initialize validator with TaskDecomposer JSON output.

        Args:
            tasks_data: Dict with 'subtasks' key containing task list

        Raises:
            ValueError: If input data is malformed
        """
        if not isinstance(tasks_data, dict):
            raise ValueError("Input must be a JSON object")

        if "subtasks" not in tasks_data:
            raise ValueError("Missing required field 'subtasks'")

        self.subtasks = tasks_data["subtasks"]
        self.issues: List[ValidationIssue] = []

        # Build task ID mapping and adjacency list
        self.task_ids: Set[int] = set()
        self.adjacency: Dict[int, List[int]] = defaultdict(list)
        self.reverse_adjacency: Dict[int, List[int]] = defaultdict(list)

        self._build_graph()

    def _build_graph(self):
        """Build graph representation from subtasks."""
        for task in self.subtasks:
            if "id" not in task:
                raise ValueError(f"Task missing 'id' field: {task}")

            task_id = task["id"]
            if not isinstance(task_id, int):
                raise ValueError(f"Task ID must be integer, got: {task_id}")

            self.task_ids.add(task_id)

            # Get dependencies (default to empty list if missing)
            dependencies = task.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise ValueError(f"Task {task_id} dependencies must be a list")

            for dep_id in dependencies:
                if not isinstance(dep_id, int):
                    raise ValueError(f"Dependency ID must be integer: {dep_id}")

                self.adjacency[task_id].append(dep_id)
                self.reverse_adjacency[dep_id].append(task_id)

    def validate_forward_references(self) -> bool:
        """
        Check for forward references (dependencies on non-existent tasks).

        Returns:
            True if no forward references found
        """
        found_issues = False

        for task_id, deps in self.adjacency.items():
            invalid_deps = [dep for dep in deps if dep not in self.task_ids]

            if invalid_deps:
                found_issues = True
                self.issues.append(
                    ValidationIssue(
                        issue_type="forward_reference",
                        severity=IssueSeverity.CRITICAL,
                        affected_tasks=[task_id] + invalid_deps,
                        message=f"Task {task_id} depends on non-existent tasks: {invalid_deps}",
                    )
                )

        return not found_issues

    def validate_self_dependencies(self) -> bool:
        """
        Check for self-dependencies (task depends on itself).

        Returns:
            True if no self-dependencies found
        """
        found_issues = False

        for task_id, deps in self.adjacency.items():
            if task_id in deps:
                found_issues = True
                self.issues.append(
                    ValidationIssue(
                        issue_type="self_dependency",
                        severity=IssueSeverity.CRITICAL,
                        affected_tasks=[task_id],
                        message=f"Task {task_id} depends on itself",
                    )
                )

        return not found_issues

    def validate_circular_dependencies(self) -> bool:
        """
        Detect circular dependencies using DFS with recursion stack.

        Returns:
            True if no cycles found
        """
        visited: Set[int] = set()
        recursion_stack: Set[int] = set()
        path_stack: List[int] = []

        def dfs(node: int) -> bool:
            """
            DFS traversal with cycle detection.

            Returns:
                True if cycle detected in this path
            """
            visited.add(node)
            recursion_stack.add(node)
            path_stack.append(node)

            for neighbor in self.adjacency[node]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    # Found cycle - extract cycle path
                    cycle_start_idx = path_stack.index(neighbor)
                    cycle_path = path_stack[cycle_start_idx:] + [neighbor]

                    self.issues.append(
                        ValidationIssue(
                            issue_type="circular_dependency",
                            severity=IssueSeverity.CRITICAL,
                            affected_tasks=cycle_path,
                            message=f"Circular dependency detected: {' → '.join(map(str, cycle_path))}",
                        )
                    )
                    return True

            path_stack.pop()
            recursion_stack.remove(node)
            return False

        # Check all nodes (graph may be disconnected)
        found_cycles = False
        for task_id in self.task_ids:
            if task_id not in visited:
                if dfs(task_id):
                    found_cycles = True

        return not found_cycles

    def validate_orphaned_tasks(self) -> bool:
        """
        Find orphaned tasks (isolated nodes with no incoming/outgoing edges).

        Returns:
            True if no orphaned tasks found
        """
        orphaned = []

        for task_id in self.task_ids:
            has_outgoing = len(self.adjacency[task_id]) > 0
            has_incoming = len(self.reverse_adjacency[task_id]) > 0

            # Task is orphaned if it has no edges at all
            if not has_outgoing and not has_incoming:
                orphaned.append(task_id)

        if orphaned:
            self.issues.append(
                ValidationIssue(
                    issue_type="orphaned_tasks",
                    severity=IssueSeverity.WARNING,
                    affected_tasks=orphaned,
                    message=f"Tasks with no dependencies or dependents (isolated): {orphaned}",
                )
            )
            return False

        return True

    def validate_all(self) -> bool:
        """
        Run all validation checks.

        Returns:
            True if all validations pass
        """
        results = [
            self.validate_forward_references(),
            self.validate_self_dependencies(),
            self.validate_circular_dependencies(),
            self.validate_orphaned_tasks(),
        ]

        return all(results)

    def get_report(self) -> dict:
        """
        Generate validation report.

        Returns:
            Dict with validation results and issues
        """
        critical_issues = [
            i for i in self.issues if i.severity == IssueSeverity.CRITICAL
        ]
        warning_issues = [i for i in self.issues if i.severity == IssueSeverity.WARNING]

        return {
            "valid": len(critical_issues) == 0,
            "total_tasks": len(self.task_ids),
            "total_issues": len(self.issues),
            "critical_issues": len(critical_issues),
            "warnings": len(warning_issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def get_task_title(self, task_id: int) -> str:
        """
        Get task title by ID.

        Args:
            task_id: Task ID to look up

        Returns:
            Task title or empty string if not found
        """
        for task in self.subtasks:
            if task["id"] == task_id:
                return task.get("title", "")
        return ""


class ASCIIGraphRenderer:
    """Renders task dependency graph as ASCII tree visualization."""

    def __init__(self, validator: DependencyValidator):
        """
        Initialize renderer with validated task graph.

        Args:
            validator: DependencyValidator instance with validated graph
        """
        self.validator = validator
        self.task_ids = validator.task_ids
        self.adjacency = validator.adjacency
        self.reverse_adjacency = validator.reverse_adjacency
        self.issues = validator.issues

        # Build issue lookup for color coding
        self.task_issues: Dict[int, List[ValidationIssue]] = defaultdict(list)
        for issue in self.issues:
            for task_id in issue.affected_tasks:
                self.task_issues[task_id].append(issue)

    def _get_task_color(self, task_id: int, use_colors: bool = True) -> str:
        """
        Determine color for task based on validation status.

        Args:
            task_id: Task ID to check
            use_colors: Whether to use ANSI color codes

        Returns:
            ANSI color code or empty string if use_colors=False
        """
        if not use_colors:
            return ""

        if task_id not in self.task_issues:
            return ANSIColors.GREEN  # Valid task

        # Check severity of issues
        has_critical = any(
            issue.severity == IssueSeverity.CRITICAL
            for issue in self.task_issues[task_id]
        )

        return ANSIColors.RED if has_critical else ANSIColors.YELLOW

    def _get_root_nodes(self) -> List[int]:
        """
        Find root nodes (tasks with no dependencies).

        Returns:
            List of task IDs that are roots (no incoming edges in dependency graph)
        """
        roots = []
        for task_id in sorted(self.task_ids):
            # Root nodes are those that don't depend on anything
            if len(self.adjacency[task_id]) == 0:
                roots.append(task_id)
        return roots

    def _topological_sort(self) -> List[int]:
        """
        Perform topological sort using Kahn's algorithm.

        Returns:
            List of task IDs in topological order (or partial order if cycles exist)
        """
        # Calculate "in-degree" for each task (how many dependencies each task has)
        # adjacency[A] = [B] means "A depends on B"
        # in_degree[A] = number of dependencies task A has (outgoing edges from A in dependency graph)
        # Note: In graph theory terms, these are outgoing edges, but we call it "in-degree"
        # because it counts incoming dependencies that must be satisfied before A can execute
        in_degree: Dict[int, int] = {
            task_id: len(self.adjacency.get(task_id, [])) for task_id in self.task_ids
        }

        # Start with root nodes (tasks that have no dependencies)
        queue = deque([tid for tid in self.task_ids if in_degree[tid] == 0])
        sorted_order = []

        while queue:
            current = queue.popleft()
            sorted_order.append(current)

            # For each task that depends on current task (has current in its dependencies)
            # When we process current, we can "remove" it from dependents' dependency lists
            for dependent in self.reverse_adjacency[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Add remaining nodes (those in cycles) in sorted order
        remaining = sorted([tid for tid in self.task_ids if in_degree[tid] > 0])
        sorted_order.extend(remaining)

        return sorted_order

    def _render_tree_node(
        self,
        task_id: int,
        prefix: str,
        is_last: bool,
        visited: Set[int],
        max_depth: int,
        current_depth: int = 0,
        use_colors: bool = True,
    ) -> List[str]:
        """
        Recursively render a task node and its dependents.

        Args:
            task_id: Task ID to render
            prefix: Current line prefix for tree structure
            is_last: Whether this is the last child of its parent
            visited: Set of already visited tasks (to prevent infinite loops)
            max_depth: Maximum depth to render (prevents deep recursion)
            current_depth: Current recursion depth
            use_colors: Whether to use ANSI color codes

        Returns:
            List of formatted lines for this node and its children
        """
        if current_depth > max_depth or task_id in visited:
            return []

        visited.add(task_id)
        lines = []

        # Create color mapping
        gray = ANSIColors.GRAY if use_colors else ""
        reset = ANSIColors.RESET if use_colors else ""

        # Get task info
        title = self.validator.get_task_title(task_id)
        color = self._get_task_color(task_id, use_colors)

        # Build node label
        node_label = f"Task {task_id}"
        if title:
            node_label += f": {title}"

        # Add dependency info
        deps = self.adjacency.get(task_id, [])
        if deps:
            dep_list = ", ".join(map(str, deps))
            node_label += f" {gray}(depends on {dep_list}){reset}"

        # Format current node
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{color}{node_label}{reset}")

        # Prepare prefix for children
        child_prefix = prefix + ("    " if is_last else "│   ")

        # Get tasks that depend on this one (children in the tree)
        dependents = sorted(self.reverse_adjacency.get(task_id, []))

        # Render children
        for i, dep_task_id in enumerate(dependents):
            is_last_child = i == len(dependents) - 1
            child_lines = self._render_tree_node(
                dep_task_id,
                child_prefix,
                is_last_child,
                visited,
                max_depth,
                current_depth + 1,
                use_colors,
            )
            lines.extend(child_lines)

        return lines

    def render(
        self, use_colors: bool = True, max_depth: int = 20, max_width: int = 120
    ) -> str:
        """
        Render complete dependency graph as ASCII tree.

        Args:
            use_colors: Whether to use ANSI color codes
            max_depth: Maximum tree depth to render
            max_width: Maximum line width (truncate longer lines to prevent terminal overflow)

        Returns:
            Formatted ASCII tree string
        """
        # Create instance-level color mapping to avoid mutating class attributes
        if use_colors:
            C = ANSIColors  # Use actual colors
        else:
            # Create empty color mapping for no-color mode
            class NoColors:
                GREEN = RED = YELLOW = GRAY = BOLD = RESET = ""

            C = NoColors

        lines = []

        # Header
        total_issues = len(self.issues)
        critical_count = sum(
            1 for i in self.issues if i.severity == IssueSeverity.CRITICAL
        )
        warning_count = sum(
            1 for i in self.issues if i.severity == IssueSeverity.WARNING
        )

        status_color = C.GREEN if critical_count == 0 else C.RED
        lines.append(f"{C.BOLD}Task Dependency Graph{C.RESET}")
        lines.append(f"{C.GRAY}{'=' * 60}{C.RESET}")
        lines.append(f"Total Tasks: {len(self.task_ids)}")
        lines.append(
            f"Issues: {status_color}{total_issues}{C.RESET} "
            f"({C.RED}{critical_count} critical{C.RESET}, "
            f"{C.YELLOW}{warning_count} warnings{C.RESET})"
        )
        lines.append("")

        # Legend
        lines.append(f"{C.BOLD}Legend:{C.RESET}")
        lines.append(f"  {C.GREEN}●{C.RESET} Valid task")
        lines.append(f"  {C.YELLOW}●{C.RESET} Task with warnings")
        lines.append(f"  {C.RED}●{C.RESET} Task with critical issues")
        lines.append(f"  {C.GRAY}(depends on X){C.RESET} Dependency information")
        lines.append("")

        # Get root nodes and render trees
        roots = self._get_root_nodes()

        if not roots:
            # All tasks have dependencies - likely a cycle or complex graph
            # Use topological sort to find best starting points
            sorted_tasks = self._topological_sort()
            roots = [sorted_tasks[0]] if sorted_tasks else list(self.task_ids)[:1]

        lines.append(f"{C.BOLD}Dependency Tree:{C.RESET}")
        lines.append(f"{C.GRAY}{'─' * 60}{C.RESET}")

        visited: Set[int] = set()

        for i, root_id in enumerate(roots):
            is_last_root = i == len(roots) - 1

            # Render root and its subtree
            root_lines = self._render_tree_node(
                root_id, "", is_last_root, visited, max_depth, use_colors=use_colors
            )
            lines.extend(root_lines)

        # Check for unvisited nodes (disconnected components or cycles)
        unvisited = self.task_ids - visited
        if unvisited:
            lines.append("")
            lines.append(f"{C.YELLOW}Disconnected/Cyclic Tasks:{C.RESET}")
            for task_id in sorted(unvisited):
                title = self.validator.get_task_title(task_id)
                color = self._get_task_color(task_id, use_colors)
                node_label = f"Task {task_id}"
                if title:
                    node_label += f": {title}"

                deps = self.adjacency.get(task_id, [])
                if deps:
                    dep_list = ", ".join(map(str, deps))
                    node_label += f" {C.GRAY}(depends on {dep_list}){C.RESET}"

                lines.append(f"  • {color}{node_label}{C.RESET}")

        # Apply max_width truncation if specified
        if max_width > 0:
            truncated_lines = []
            for line in lines:
                # Calculate visible length (excluding ANSI codes)
                visible_line = self._strip_ansi(line)
                if len(visible_line) > max_width:
                    # Find position to truncate (accounting for ANSI codes)
                    truncated = self._truncate_line(line, max_width)
                    truncated_lines.append(truncated + "...")
                else:
                    truncated_lines.append(line)
            lines = truncated_lines

        return "\n".join(lines)

    def _strip_ansi(self, text: str) -> str:
        """
        Remove ANSI escape codes from text.

        Args:
            text: Text with potential ANSI codes

        Returns:
            Text with ANSI codes removed
        """
        import re

        ansi_escape = re.compile(r"\033\[[0-9;]*m")
        return ansi_escape.sub("", text)

    def _truncate_line(self, line: str, max_length: int) -> str:
        """
        Truncate line to max_length visible characters, preserving ANSI codes.

        Args:
            line: Line with potential ANSI codes
            max_length: Maximum visible character length

        Returns:
            Truncated line with ANSI codes preserved
        """
        import re

        ansi_escape = re.compile(r"\033\[[0-9;]*m")

        result = []
        visible_count = 0
        pos = 0

        while pos < len(line) and visible_count < max_length:
            # Check for ANSI code
            match = ansi_escape.match(line, pos)
            if match:
                # Add ANSI code without counting it
                result.append(match.group(0))
                pos = match.end()
            else:
                # Add regular character and count it
                result.append(line[pos])
                visible_count += 1
                pos += 1

        return "".join(result)


def load_input(file_path: str = None) -> dict:
    """
    Load JSON input from file or stdin.

    Args:
        file_path: Path to JSON file, or None to read from stdin

    Returns:
        Parsed JSON data

    Raises:
        ValueError: If JSON is invalid
    """
    try:
        if file_path:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON input: {e}")
    except FileNotFoundError:
        raise ValueError(f"File not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error reading input: {e}")


def print_report(report: dict, output_format: str = "json"):
    """
    Print validation report.

    Args:
        report: Validation report dictionary
        output_format: Output format ('json' or 'text')
    """
    if output_format == "json":
        print(json.dumps(report, indent=2))
    else:
        # Text format for human readability
        print("Validation Report")
        print("=" * 60)
        print(f"Total Tasks: {report['total_tasks']}")
        print(f"Total Issues: {report['total_issues']}")
        print(f"  Critical: {report['critical_issues']}")
        print(f"  Warnings: {report['warnings']}")
        print(f"Status: {'✅ VALID' if report['valid'] else '❌ INVALID'}")

        if report["issues"]:
            print("\nIssues Found:")
            print("-" * 60)
            for issue in report["issues"]:
                severity_icon = "🔴" if issue["severity"] == "critical" else "🟡"
                print(
                    f"\n{severity_icon} {issue['type'].upper()} ({issue['severity']})"
                )
                print(f"   Affected tasks: {issue['affected_tasks']}")
                print(f"   {issue['message']}")


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Validate TaskDecomposer JSON output for dependency issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate from stdin
  cat decomposer-output.json | python scripts/validate-dependencies.py

  # Validate from file
  python scripts/validate-dependencies.py decomposer-output.json

  # Output in text format
  python scripts/validate-dependencies.py -f text decomposer-output.json

  # Visualize dependency tree
  python scripts/validate-dependencies.py --visualize decomposer-output.json

  # Visualize without colors (for piping/logging)
  python scripts/validate-dependencies.py --visualize --no-color decomposer-output.json

Exit Codes:
  0: Valid task graph (no critical issues)
  1: Invalid task graph (critical issues found)
  2: Invalid input (malformed JSON or missing fields)
        """,
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to TaskDecomposer JSON output (default: stdin)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Display ASCII dependency tree visualization",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable color output in visualization"
    )

    args = parser.parse_args()

    try:
        # Load and validate input
        data = load_input(args.input_file)
        validator = DependencyValidator(data)

        # Run validation
        is_valid = validator.validate_all()
        report = validator.get_report()

        # Print report
        print_report(report, args.format)

        # Display visualization if requested
        if args.visualize:
            print()  # Add blank line separator
            renderer = ASCIIGraphRenderer(validator)
            visualization = renderer.render(use_colors=not args.no_color)
            print(visualization)

        # Exit with appropriate code
        sys.exit(0 if is_valid else 1)

    except ValueError as e:
        # Input validation error
        error_report = {
            "valid": False,
            "error": str(e),
            "error_type": "input_validation",
        }
        print(json.dumps(error_report, indent=2), file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        # Unexpected error
        error_report = {"valid": False, "error": str(e), "error_type": "unexpected"}
        print(json.dumps(error_report, indent=2), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
