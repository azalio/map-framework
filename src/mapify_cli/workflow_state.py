"""
Workflow State Management for MAP Framework

Implements auto-checkpointing to .map/progress.md for context rot mitigation.
Part of P0 Context rot mitigation from MAP Framework Improvement Plan.

The checkpoint file uses YAML frontmatter for machine-readable state
combined with human-readable markdown for progress visualization.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any


class WorkflowPhase(Enum):
    """Workflow phases for MAP Framework execution."""

    INIT = "init"
    DECOMPOSITION = "decomposition"
    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Subtask:
    """Represents a subtask in the workflow."""

    id: str
    description: str
    status: str = "pending"  # pending, in_progress, complete, failed
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowState:
    """
    Manages workflow state with auto-checkpointing to .map/progress.md.

    Key features:
    1. YAML frontmatter for machine-readable state
    2. Human-readable markdown progress visualization
    3. Automatic .map/ directory creation
    4. State restoration from checkpoint file

    Storage location: .map/progress.md
    """

    task_plan: str
    completed_subtasks: List[str] = field(default_factory=list)
    current_phase: WorkflowPhase = WorkflowPhase.INIT
    turn_count: int = 0
    branch_name: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    subtasks: List[Subtask] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize timestamps if not set."""
        now = datetime.now().isoformat()
        if self.started_at is None:
            self.started_at = now
        if self.updated_at is None:
            self.updated_at = now

    def save_checkpoint(self, project_root: Path) -> Path:
        """
        Save current state to .map/progress.md with YAML frontmatter.

        Args:
            project_root: Root directory of the project

        Returns:
            Path to the checkpoint file
        """
        map_dir = Path(project_root) / ".map"
        map_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_path = map_dir / "progress.md"

        # Update timestamp
        self.updated_at = datetime.now().isoformat()

        # Build YAML frontmatter
        frontmatter_lines = [
            "---",
            f"task_plan: {self._escape_yaml(self.task_plan)}",
            f"current_phase: {self.current_phase.value}",
            f"turn_count: {self.turn_count}",
            f"started_at: {self.started_at}",
            f"updated_at: {self.updated_at}",
        ]

        if self.branch_name:
            frontmatter_lines.append(f"branch_name: {self.branch_name}")

        # Completed subtasks as YAML list
        if self.completed_subtasks:
            frontmatter_lines.append("completed_subtasks:")
            for subtask_id in self.completed_subtasks:
                frontmatter_lines.append(f"  - {self._escape_yaml(subtask_id)}")
        else:
            # Use inline format for empty list
            frontmatter_lines.append("completed_subtasks: []")

        # Subtasks list
        if self.subtasks:
            frontmatter_lines.append("subtasks:")
            for subtask in self.subtasks:
                frontmatter_lines.append(f"  - id: {self._escape_yaml(subtask.id)}")
                frontmatter_lines.append(
                    f"    description: {self._escape_yaml(subtask.description)}"
                )
                frontmatter_lines.append(f"    status: {subtask.status}")
                if subtask.completed_at:
                    frontmatter_lines.append(
                        f"    completed_at: {subtask.completed_at}"
                    )
        else:
            # Use inline format for empty list
            frontmatter_lines.append("subtasks: []")

        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines)

        # Build human-readable markdown body
        body_lines = [
            "",
            "# MAP Workflow Progress",
            "",
            f"**Task:** {self.task_plan}",
            f"**Phase:** {self.current_phase.value}",
            f"**Turn:** {self.turn_count}",
            "",
            "## Progress",
            "",
        ]

        # Progress visualization
        total_subtasks = len(self.subtasks) if self.subtasks else 0
        completed_count = len(self.completed_subtasks)

        if total_subtasks > 0:
            progress_pct = (completed_count / total_subtasks) * 100
            body_lines.append(
                f"Progress: {completed_count}/{total_subtasks} ({progress_pct:.0f}%)"
            )
            body_lines.append("")

            # Subtask list with checkmarks
            for subtask in self.subtasks:
                if subtask.status == "complete":
                    body_lines.append(f"- [x] **{subtask.id}**: {subtask.description}")
                elif subtask.status == "in_progress":
                    body_lines.append(
                        f"- [ ] **{subtask.id}**: {subtask.description} *(in progress)*"
                    )
                elif subtask.status == "failed":
                    body_lines.append(
                        f"- [ ] **{subtask.id}**: {subtask.description} *(failed)*"
                    )
                else:
                    body_lines.append(f"- [ ] **{subtask.id}**: {subtask.description}")
        else:
            body_lines.append("No subtasks defined yet.")

        body_lines.extend(
            [
                "",
                "---",
                f"*Last updated: {self.updated_at}*",
            ]
        )

        body = "\n".join(body_lines)

        # Write checkpoint file
        content = frontmatter + body
        checkpoint_path.write_text(content, encoding="utf-8")

        return checkpoint_path

    @classmethod
    def load(cls, project_root: Path) -> Optional["WorkflowState"]:
        """
        Load workflow state from .map/progress.md checkpoint file.

        Args:
            project_root: Root directory of the project

        Returns:
            WorkflowState instance if checkpoint exists, None otherwise
        """
        checkpoint_path = Path(project_root) / ".map" / "progress.md"

        if not checkpoint_path.exists():
            return None

        content = checkpoint_path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return None

        frontmatter_text = frontmatter_match.group(1)

        # Parse frontmatter fields (simple YAML parsing)
        state_dict = cls._parse_yaml_frontmatter(frontmatter_text)

        if not state_dict.get("task_plan"):
            return None

        # Convert phase string to enum
        phase_str = state_dict.get("current_phase", "init")
        try:
            current_phase = WorkflowPhase(phase_str)
        except ValueError:
            current_phase = WorkflowPhase.INIT

        # Build subtasks list
        subtasks = []
        for st_dict in state_dict.get("subtasks", []):
            if isinstance(st_dict, dict):
                subtasks.append(
                    Subtask(
                        id=st_dict.get("id", ""),
                        description=st_dict.get("description", ""),
                        status=st_dict.get("status", "pending"),
                        completed_at=st_dict.get("completed_at"),
                    )
                )

        return cls(
            task_plan=state_dict["task_plan"],
            completed_subtasks=state_dict.get("completed_subtasks", []),
            current_phase=current_phase,
            turn_count=int(state_dict.get("turn_count", 0)),
            branch_name=state_dict.get("branch_name"),
            started_at=state_dict.get("started_at"),
            updated_at=state_dict.get("updated_at"),
            subtasks=subtasks,
        )

    @classmethod
    def _parse_yaml_frontmatter(cls, text: str) -> Dict[str, Any]:
        """
        Simple YAML frontmatter parser (handles basic key-value pairs and lists).

        Args:
            text: YAML frontmatter text (without --- delimiters)

        Returns:
            Dictionary of parsed values
        """
        result: Dict[str, Any] = {}
        current_key: Optional[str] = None
        current_list: Optional[List[Any]] = None
        current_object: Optional[Dict[str, Any]] = None
        in_subtasks: bool = False

        for line in text.split("\n"):
            stripped = line.strip()

            if not stripped:
                continue

            # Check for top-level key (line is guaranteed non-empty here due to stripped check above)
            if line and line[0] not in (" ", "\t") and ":" in stripped:
                # Save previous list/object if any
                if current_list is not None and current_key:
                    if current_object:
                        current_list.append(current_object)
                        current_object = None
                    result[current_key] = current_list
                    current_list = None

                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                current_key = key
                in_subtasks = key == "subtasks"

                if value == "[]":
                    result[key] = []
                    current_key = None
                elif value:
                    # Handle quoted strings
                    if value.startswith('"') and value.endswith('"'):
                        value = cls._unescape_yaml(value[1:-1])
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    result[key] = value
                else:
                    # Start of list or empty value
                    current_list = []

            # Check for list item
            elif stripped.startswith("- ") and current_list is not None:
                # Save previous object if in subtasks
                if in_subtasks and current_object:
                    current_list.append(current_object)
                    current_object = None

                item = stripped[2:].strip()

                if in_subtasks and ":" in item:
                    # Start of subtask object
                    current_object = {}
                    key, _, value = item.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = cls._unescape_yaml(value[1:-1])
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    current_object[key] = value
                else:
                    # Simple list item
                    if item.startswith('"') and item.endswith('"'):
                        item = cls._unescape_yaml(item[1:-1])
                    elif item.startswith("'") and item.endswith("'"):
                        item = item[1:-1]
                    current_list.append(item)

            # Check for object property (indented key: value)
            elif current_object is not None and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = cls._unescape_yaml(value[1:-1])
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                current_object[key] = value

        # Save final list/object
        if current_list is not None and current_key:
            if current_object:
                current_list.append(current_object)
            result[current_key] = current_list

        return result

    @staticmethod
    def _escape_yaml(value: str) -> str:
        """
        Escape a string value for YAML output.

        Args:
            value: String to escape

        Returns:
            Escaped string, quoted if necessary
        """
        if not value:
            return '""'

        # Check if quoting is needed
        needs_quotes = any(
            c in value for c in [":", "#", '"', "'", "\n", "[", "]", "{", "}"]
        )

        if needs_quotes:
            # Escape double quotes and wrap in double quotes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        return value

    @staticmethod
    def _unescape_yaml(value: str) -> str:
        """
        Unescape a YAML string value.

        Args:
            value: Escaped YAML string

        Returns:
            Unescaped string
        """
        # Unescape backslash sequences
        return value.replace('\\"', '"').replace("\\\\", "\\")

    def mark_subtask_complete(self, subtask_id: str) -> None:
        """
        Mark a subtask as complete.

        Args:
            subtask_id: ID of the subtask to mark complete
        """
        if subtask_id not in self.completed_subtasks:
            self.completed_subtasks.append(subtask_id)

        for subtask in self.subtasks:
            if subtask.id == subtask_id:
                subtask.status = "complete"
                subtask.completed_at = datetime.now().isoformat()
                break

    def mark_subtask_in_progress(self, subtask_id: str) -> None:
        """
        Mark a subtask as in progress.

        Args:
            subtask_id: ID of the subtask to mark in progress
        """
        for subtask in self.subtasks:
            if subtask.id == subtask_id:
                subtask.status = "in_progress"
                break

    def add_subtask(self, subtask_id: str, description: str) -> None:
        """
        Add a new subtask to the workflow.

        Args:
            subtask_id: Unique identifier for the subtask
            description: Human-readable description
        """
        self.subtasks.append(Subtask(id=subtask_id, description=description))

    def increment_turn(self) -> None:
        """Increment the turn counter."""
        self.turn_count += 1

    def set_phase(self, phase: WorkflowPhase) -> None:
        """
        Set the current workflow phase.

        Args:
            phase: New workflow phase
        """
        self.current_phase = phase

    def get_remaining_subtasks(self) -> List[Subtask]:
        """
        Get list of subtasks that are not yet complete.

        Returns:
            List of pending/in_progress subtasks
        """
        return [st for st in self.subtasks if st.status not in ("complete", "failed")]

    def is_complete(self) -> bool:
        """
        Check if the workflow is complete.

        Returns:
            True if all subtasks are complete
        """
        if not self.subtasks:
            return False
        return all(st.status == "complete" for st in self.subtasks)

    @classmethod
    def exists(cls, project_root: Path) -> bool:
        """
        Check if a checkpoint file exists.

        Args:
            project_root: Root directory of the project

        Returns:
            True if checkpoint exists
        """
        checkpoint_path = Path(project_root) / ".map" / "progress.md"
        return checkpoint_path.exists()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m mapify_cli.workflow_state test")
        print("  python -m mapify_cli.workflow_state show")
        print("  python -m mapify_cli.workflow_state clear")
        sys.exit(1)

    command = sys.argv[1]
    project_root = Path.cwd()

    if command == "test":
        # Create test state
        state = WorkflowState(
            task_plan="Implement user authentication feature",
            branch_name="feat/user-auth",
        )

        # Add subtasks
        state.add_subtask("ST-001", "Create User model with SQLite schema")
        state.add_subtask("ST-002", "Implement password hashing with bcrypt")
        state.add_subtask("ST-003", "Create login/logout API endpoints")
        state.add_subtask("ST-004", "Add JWT token generation")

        # Mark some progress
        state.set_phase(WorkflowPhase.IMPLEMENTATION)
        state.mark_subtask_complete("ST-001")
        state.mark_subtask_in_progress("ST-002")
        state.increment_turn()
        state.increment_turn()

        # Save checkpoint
        checkpoint_path = state.save_checkpoint(project_root)
        print(f"Checkpoint saved to: {checkpoint_path}")
        print("\nContents:")
        print(checkpoint_path.read_text())

        # Test load
        print("\n--- Testing load ---")
        loaded_state = WorkflowState.load(project_root)
        if loaded_state:
            print(f"Task: {loaded_state.task_plan}")
            print(f"Phase: {loaded_state.current_phase.value}")
            print(f"Turn: {loaded_state.turn_count}")
            print(f"Completed: {loaded_state.completed_subtasks}")
            print(
                f"Remaining: {[st.id for st in loaded_state.get_remaining_subtasks()]}"
            )

    elif command == "show":
        loaded_state = WorkflowState.load(project_root)
        if loaded_state:
            print(f"Task: {loaded_state.task_plan}")
            print(f"Phase: {loaded_state.current_phase.value}")
            print(f"Turn: {loaded_state.turn_count}")
            print(
                f"Completed: {len(loaded_state.completed_subtasks)}/{len(loaded_state.subtasks)}"
            )
            print("\nRemaining subtasks:")
            for st in loaded_state.get_remaining_subtasks():
                print(f"  - {st.id}: {st.description} ({st.status})")
        else:
            print("No workflow in progress")

    elif command == "clear":
        checkpoint_path = project_root / ".map" / "progress.md"
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            print("Checkpoint cleared")
        else:
            print("No checkpoint to clear")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
