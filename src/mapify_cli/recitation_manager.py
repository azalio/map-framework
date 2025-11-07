"""
Recitation Manager for MAP Framework

Implements the "Recitation" pattern from context engineering:
Periodically repeating main goals at the end of context to keep them "fresh"
in the model's attention window.

Based on: "Context Engineering for AI Agents: Lessons from Building Manus"
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from mapify_cli.workflow_logger import MapWorkflowLogger


@dataclass
class Subtask:
    """Represents a single subtask in the plan"""

    id: str
    description: str
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    acceptance_criteria: Optional[Union[str, List[str]]] = None
    estimated_complexity: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    iterations: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """Represents the overall task plan"""

    task_id: str
    goal: str
    subtasks: List[Subtask]
    current_subtask_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class RecitationManager:
    """
    Manages the current_plan.md file for keeping goals fresh in context.

    Key principles:
    1. Update plan before each subtask to add to end of context
    2. Keep format concise but informative
    3. Show progress clearly (✓, →, ☐)
    4. Highlight current focus
    """

    @staticmethod
    def _format_acceptance_criteria(
        criteria: Optional[Union[str, List[str]]],
    ) -> Optional[str]:
        """Format acceptance criteria as a string.

        Args:
            criteria: Acceptance criteria as string or list of strings

        Returns:
            - None if criteria is None or empty list (for consistency)
            - Original string if criteria is already a string
            - Formatted bulleted list if criteria is a non-empty list

        Examples:
            >>> _format_acceptance_criteria(None)
            None
            >>> _format_acceptance_criteria([])
            None
            >>> _format_acceptance_criteria("All tests pass")
            'All tests pass'
            >>> _format_acceptance_criteria(["Test A passes", "Test B passes"])
            '- Test A passes\\n- Test B passes'
        """
        if criteria is None:
            return None
        if isinstance(criteria, str):
            return criteria
        # If it's a list, return None for empty lists (consistency with None input)
        if not criteria:
            return None
        # For non-empty lists, join with newlines
        return "\n".join(f"- {item}" for item in criteria)

    def __init__(
        self, project_root: Path, logger: Optional["MapWorkflowLogger"] = None
    ):
        self.project_root = Path(project_root)
        self.map_dir = self.project_root / ".map"
        self.plan_file = self.map_dir / "current_plan.md"
        self.plan_json = self.map_dir / "current_plan.json"
        self.dev_docs_dir = self.map_dir / "dev_docs"
        self.context_file = self.dev_docs_dir / "context.md"
        self.tasks_file = self.dev_docs_dir / "tasks.md"
        self.logger = logger  # Optional logger for workflow tracking

        # Create directories if they don't exist
        self.map_dir.mkdir(exist_ok=True)
        self.dev_docs_dir.mkdir(exist_ok=True)

    def create_plan(
        self, task_id: str, goal: str, subtasks: List[dict], force: bool = False
    ) -> TaskPlan:
        """
        Create a new task plan from TaskDecomposer output.

        Args:
            task_id: Unique identifier for the task
            goal: Overall goal description
            subtasks: List of subtask dictionaries from TaskDecomposer
            force: If True, overwrite existing plan. If False (default), raise ValueError if plan exists.

        Returns:
            TaskPlan object

        Raises:
            ValueError: If a plan already exists and force=False
        """
        # Check for existing plan
        if self.plan_json.exists() and not force:
            raise ValueError(
                "A plan already exists. Use 'clear' to remove it first, or use --force to overwrite."
            )

        plan_subtasks = [
            Subtask(
                id=str(st["id"]),  # Convert ID to string for consistency
                description=st["description"],
                status="pending",
                acceptance_criteria=st.get("acceptance_criteria"),
                estimated_complexity=st.get("estimated_complexity"),
                depends_on=[
                    str(dep) for dep in st.get("depends_on", [])
                ],  # Convert dependencies to strings
            )
            for st in subtasks
        ]

        plan = TaskPlan(
            task_id=task_id,
            goal=goal,
            subtasks=plan_subtasks,
            current_subtask_id=plan_subtasks[0].id if plan_subtasks else None,
        )

        self._save_plan(plan)
        self._generate_markdown(plan)
        self._generate_tasks_md(plan)  # Auto-generate tasks.md

        # Log plan creation
        if self.logger:
            self.logger.log_event(
                event_type="recitation_plan_created",
                message=f"Created task plan: {task_id}",
                metadata={
                    "task_id": task_id,
                    "goal": goal,
                    "total_subtasks": len(plan_subtasks),
                    "forced": force,
                },
            )

        return plan

    def update_subtask_status(
        self, subtask_id: str, status: str, error: Optional[str] = None
    ) -> TaskPlan:
        """
        Update the status of a subtask.

        Args:
            subtask_id: ID of the subtask to update
            status: New status ('in_progress', 'completed', 'failed')
            error: Error message if status is 'failed'

        Returns:
            Updated TaskPlan

        Raises:
            ValueError: If no active plan exists
        """
        # Convert subtask_id to string for consistency and backward compatibility
        subtask_id = str(subtask_id)

        plan = self._load_plan()

        # Check if plan exists
        if plan is None:
            raise ValueError(
                "No active plan exists. Create a plan first using: "
                "'mapify recitation create <task_id> <goal> <subtasks_json>'"
            )

        # Find the target subtask up front so we can validate and log reliably
        target_subtask = next(
            (subtask for subtask in plan.subtasks if subtask.id == subtask_id), None
        )

        if target_subtask is None:
            raise ValueError(
                f"Subtask with id {subtask_id} was not found in the current plan"
            )

        target_subtask.status = status
        if status == "in_progress":
            plan.current_subtask_id = subtask_id
            target_subtask.iterations += 1
        if error:
            target_subtask.errors.append(error)

        plan.updated_at = datetime.now().isoformat()

        self._save_plan(plan)
        self._generate_markdown(plan)
        self._generate_tasks_md(plan)  # Auto-regenerate tasks.md on update

        # Log status update
        if self.logger:
            self.logger.log_event(
                event_type="recitation_subtask_updated",
                message=f"Subtask {subtask_id} updated to {status}",
                metadata={
                    "subtask_id": subtask_id,
                    "status": status,
                    "error": error,
                    "iterations": target_subtask.iterations,
                },
            )

        return plan

    def get_current_context(self) -> str:
        """
        Get the current plan as a markdown string for adding to context.

        This is the key recitation method - called before each Actor invocation
        to keep the goals fresh in the model's attention.

        Returns:
            Markdown formatted plan
        """
        if not self.plan_file.exists():
            return ""

        context = self.plan_file.read_text()

        # Log context retrieval
        if self.logger:
            plan = self._load_plan()
            self.logger.log_event(
                event_type="recitation_context_retrieved",
                message="Retrieved current plan context for Actor",
                metadata={
                    "current_subtask": plan.current_subtask_id if plan else None,
                    "context_length": len(context),
                },
            )

        return context

    def get_plan(self) -> Optional[TaskPlan]:
        """Get the current plan object"""
        return self._load_plan()

    def clear_plan(self):
        """Clear the current plan (e.g., when task is complete)"""
        if self.plan_file.exists():
            self.plan_file.unlink()
        if self.plan_json.exists():
            self.plan_json.unlink()

    def _save_plan(self, plan: TaskPlan):
        """Save plan to JSON file"""
        plan_dict = {
            "task_id": plan.task_id,
            "goal": plan.goal,
            "subtasks": [
                {
                    "id": st.id,
                    "description": st.description,
                    "status": st.status,
                    "acceptance_criteria": st.acceptance_criteria,
                    "estimated_complexity": st.estimated_complexity,
                    "depends_on": st.depends_on,
                    "iterations": st.iterations,
                    "errors": st.errors,
                }
                for st in plan.subtasks
            ],
            "current_subtask_id": plan.current_subtask_id,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }

        self.plan_json.write_text(json.dumps(plan_dict, indent=2))

    def _load_plan(self) -> Optional[TaskPlan]:
        """Load plan from JSON file"""
        if not self.plan_json.exists():
            return None

        plan_dict = json.loads(self.plan_json.read_text())

        subtasks = [
            Subtask(
                id=st["id"],
                description=st["description"],
                status=st["status"],
                acceptance_criteria=st.get("acceptance_criteria"),
                estimated_complexity=st.get("estimated_complexity"),
                depends_on=st.get("depends_on", []),
                iterations=st.get("iterations", 0),
                errors=st.get("errors", []),
            )
            for st in plan_dict["subtasks"]
        ]

        return TaskPlan(
            task_id=plan_dict["task_id"],
            goal=plan_dict["goal"],
            subtasks=subtasks,
            current_subtask_id=plan_dict.get("current_subtask_id"),
            created_at=plan_dict.get("created_at"),
            updated_at=plan_dict.get("updated_at"),
        )

    def _generate_markdown(self, plan: TaskPlan):
        """
        Generate the current_plan.md file for recitation.

        Format is optimized for model attention:
        - Clear visual markers (✓, →, ☐)
        - Current focus highlighted
        - Concise but complete
        """
        completed = sum(1 for st in plan.subtasks if st.status == "completed")
        total = len(plan.subtasks)

        # Find current subtask
        current_st = None
        if plan.current_subtask_id:
            current_st = next(
                (st for st in plan.subtasks if st.id == plan.current_subtask_id), None
            )

        md_lines = [
            f"# Current Task: {plan.task_id}",
            "",
            "## Overall Goal",
            plan.goal,
            "",
            f"## Progress: {completed}/{total} subtasks completed",
            "",
        ]

        # Add subtasks list
        md_lines.append("## Subtasks")
        for st in plan.subtasks:
            if st.status == "completed":
                marker = "✓"
            elif st.status == "in_progress":
                marker = "→"
            elif st.status == "failed":
                marker = "✗"
            else:
                marker = "☐"

            is_current = st.id == plan.current_subtask_id
            prefix = "**" if is_current else ""
            suffix = "** (CURRENT)" if is_current else ""

            md_lines.append(
                f"- [{marker}] {prefix}{st.id}/{total}: {st.description}{suffix}"
            )

            # Add iterations info if retrying
            if st.iterations > 1:
                md_lines.append(f"  - Iterations: {st.iterations}")

            # Add latest error if failed
            if st.errors:
                md_lines.append(f"  - Last error: {st.errors[-1][:100]}...")

        md_lines.append("")

        # Add current focus section
        if current_st:
            md_lines.extend(
                [
                    "## Current Focus",
                    f"**Subtask {current_st.id}:** {current_st.description}",
                    "",
                ]
            )

            if current_st.acceptance_criteria:
                formatted_criteria = self._format_acceptance_criteria(
                    current_st.acceptance_criteria
                )
                md_lines.extend(["**Acceptance Criteria:**", formatted_criteria, ""])

            if current_st.estimated_complexity:
                md_lines.append(f"**Complexity:** {current_st.estimated_complexity}")
                md_lines.append("")

            if current_st.iterations > 1:
                md_lines.append(
                    f"⚠️ **Retry attempt {current_st.iterations}** "
                    f"- carefully review previous errors"
                )
                md_lines.append("")

        # Add footer with timestamp
        md_lines.extend(
            [
                "---",
                f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
                "",
                "**Note:** This plan keeps goals fresh in context (Recitation pattern). "
                "Review before each subtask.",
            ]
        )

        self.plan_file.write_text("\n".join(md_lines))

    def get_statistics(self) -> dict:
        """Get statistics about the current plan"""
        plan = self._load_plan()
        if not plan:
            return {}

        return {
            "total_subtasks": len(plan.subtasks),
            "completed": sum(1 for st in plan.subtasks if st.status == "completed"),
            "in_progress": sum(1 for st in plan.subtasks if st.status == "in_progress"),
            "failed": sum(1 for st in plan.subtasks if st.status == "failed"),
            "pending": sum(1 for st in plan.subtasks if st.status == "pending"),
            "total_iterations": sum(st.iterations for st in plan.subtasks),
            "current_subtask": plan.current_subtask_id,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }

    def _generate_tasks_md(self, plan: TaskPlan):
        """
        Generate tasks.md file with current subtasks and their status.

        This file is auto-updated whenever the recitation plan changes.
        """
        lines = [
            f"# Tasks for: {plan.task_id}",
            "",
            f"**Overall Goal:** {plan.goal}",
            "",
            f"**Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Task List",
            "",
        ]

        # Group tasks by status
        pending = [st for st in plan.subtasks if st.status == "pending"]
        in_progress = [st for st in plan.subtasks if st.status == "in_progress"]
        completed = [st for st in plan.subtasks if st.status == "completed"]
        failed = [st for st in plan.subtasks if st.status == "failed"]

        # In Progress section (most important)
        if in_progress:
            lines.extend(["### 🔄 In Progress", ""])
            for st in in_progress:
                lines.append(f"- **[{st.id}]** {st.description}")
                if st.acceptance_criteria:
                    formatted_criteria = self._format_acceptance_criteria(
                        st.acceptance_criteria
                    )
                    lines.append(f"  - **Acceptance:** {formatted_criteria}")
                if st.estimated_complexity:
                    lines.append(f"  - **Complexity:** {st.estimated_complexity}")
                if st.depends_on:
                    lines.append(
                        f"  - **Depends on:** {', '.join(map(str, st.depends_on))}"
                    )
                if st.iterations > 1:
                    lines.append(f"  - ⚠️ **Retry #{st.iterations}**")
                if st.errors:
                    lines.append(f"  - **Last Error:** {st.errors[-1][:150]}...")
                lines.append("")

        # Pending section
        if pending:
            lines.extend(["### ☐ Pending", ""])
            for st in pending:
                lines.append(f"- **[{st.id}]** {st.description}")
                if st.depends_on:
                    lines.append(
                        f"  - **Depends on:** {', '.join(map(str, st.depends_on))}"
                    )
                lines.append("")

        # Completed section
        if completed:
            lines.extend(["### ✓ Completed", ""])
            for st in completed:
                lines.append(f"- ~~**[{st.id}]** {st.description}~~")
                lines.append("")

        # Failed section
        if failed:
            lines.extend(["### ✗ Failed", ""])
            for st in failed:
                lines.append(f"- **[{st.id}]** {st.description}")
                if st.errors:
                    lines.append(f"  - **Error:** {st.errors[-1][:150]}...")
                lines.append("")

        # Summary
        total = len(plan.subtasks)
        lines.extend(
            [
                "---",
                "",
                f"**Progress:** {len(completed)}/{total} completed, "
                f"{len(in_progress)} in progress, "
                f"{len(pending)} pending, "
                f"{len(failed)} failed",
            ]
        )

        self.tasks_file.write_text("\n".join(lines))

    def generate_context_md(self):
        """
        Generate context.md file with project metadata and conventions.

        This is typically run once or on-demand to capture project context.
        """
        lines = ["# Project Context", "", "## Project Information", ""]

        # Try to read project info from README
        readme_path = self.project_root / "README.md"
        if readme_path.exists():
            try:
                readme_content = readme_path.read_text(encoding="utf-8")
                # Extract title (first h1)
                for line in readme_content.split("\n"):
                    if line.startswith("# "):
                        project_name = line[2:].strip()
                        lines.append(f"**Project:** {project_name}")
                        break

                # Extract description (first paragraph after title)
                in_description = False
                description_lines = []
                for line in readme_content.split("\n"):
                    if line.startswith("# "):
                        in_description = True
                        continue
                    if in_description and line.strip() and not line.startswith("#"):
                        description_lines.append(line.strip())
                    if in_description and (
                        line.startswith("##") or len(description_lines) > 3
                    ):
                        break

                if description_lines:
                    lines.append(f"**Description:** {' '.join(description_lines[:3])}")

            except Exception as e:
                lines.append(f"**Project:** (Could not read README.md: {e})")
        else:
            lines.append(f"**Project:** {self.project_root.name}")

        lines.extend(
            ["", f"**Location:** `{self.project_root}`", "", "## Key Conventions", ""]
        )

        # Try to query playbook for high-quality patterns
        try:
            from mapify_cli.playbook_manager import PlaybookManager

            playbook_db_path = self.project_root / ".claude" / "playbook.db"
            playbook_json_path = self.project_root / ".claude" / "playbook.json"

            # Check if playbook exists (prefer .db, fall back to .json for backward compatibility)
            if playbook_db_path.exists() or playbook_json_path.exists():
                # Prefer .db if it exists, only pass playbook_path if .db doesn't exist yet
                playbook = PlaybookManager(
                    playbook_path=(
                        str(playbook_json_path)
                        if not playbook_db_path.exists() and playbook_json_path.exists()
                        else None
                    ),
                    db_path=str(playbook_db_path),
                )

                # Get high-quality bullets (quality_score >= 5)
                high_quality = playbook.get_bullets_for_sync(threshold=5)

                if high_quality:
                    lines.append("### Proven Patterns (from Playbook)")
                    lines.append("")

                    # Group by section and take top 3 per section
                    from collections import defaultdict

                    by_section = defaultdict(list)
                    for bullet in high_quality:
                        by_section[bullet["section"]].append(bullet)

                    # Sort each section by quality and take top 3
                    for section_name, bullets in sorted(by_section.items()):
                        bullets.sort(
                            key=lambda b: b.get("quality_score", 0), reverse=True
                        )
                        top_bullets = bullets[:3]

                        section_display = section_name.replace("_", " ").title()
                        lines.append(f"#### {section_display}")
                        lines.append("")

                        for bullet in top_bullets:
                            # Truncate content if too long
                            content = bullet["content"]
                            if len(content) > 200:
                                content = content[:200] + "..."
                            lines.append(f"- [{bullet['id']}] {content}")

                        lines.append("")
                else:
                    lines.append("*(No high-quality patterns in playbook yet)*")
                    lines.append("")

        except Exception as e:
            lines.append(f"*(Could not load playbook patterns: {e})*")
            lines.append("")

        # Add architecture section
        arch_path = self.project_root / "ARCHITECTURE.md"
        if arch_path.exists():
            lines.extend(
                [
                    "## Architecture Overview",
                    "",
                    f"See [ARCHITECTURE.md]({arch_path.relative_to(self.project_root)}) for details.",
                    "",
                ]
            )

        # Add common gotchas section
        lines.extend(
            [
                "## Common Gotchas",
                "",
                "*(This section should be manually updated as you discover pitfalls)*",
                "",
                "---",
                "",
                f"*Last generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            ]
        )

        self.context_file.write_text("\n".join(lines))

        return str(self.context_file)

    def get_dev_docs(self) -> dict:
        """
        Get all dev docs content for Claude injection.

        Returns a dict with plan, context, and tasks content.
        """
        result = {"plan": "", "context": "", "tasks": ""}

        # Read plan.md (current_plan.md)
        if self.plan_file.exists():
            result["plan"] = self.plan_file.read_text(encoding="utf-8")

        # Read context.md
        if self.context_file.exists():
            result["context"] = self.context_file.read_text(encoding="utf-8")
        else:
            result["context"] = (
                "# Context\n\n*(Not generated yet. Run `mapify recitation generate-context`)*"
            )

        # Read tasks.md
        if self.tasks_file.exists():
            result["tasks"] = self.tasks_file.read_text(encoding="utf-8")
        else:
            result["tasks"] = "# Tasks\n\n*(No active plan)*"

        return result


# CLI interface
if __name__ == "__main__":
    import sys

    # Detect --force flag before parsing positional arguments
    force_flag = "--force" in sys.argv
    if force_flag:
        sys.argv.remove("--force")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  mapify recitation create <task_id> <goal> <subtasks_json> [--force]")
        print("  mapify recitation update <subtask_id> <status> [error]")
        print("  mapify recitation get-context")
        print("  mapify recitation stats")
        print("  mapify recitation clear")
        print("  mapify recitation generate-context")
        print("  mapify recitation generate-tasks")
        print("  mapify recitation get-docs")
        print("\nExamples:")
        print("  # Create plan")
        print(
            '  mapify recitation create feat_auth "Add JWT auth" \'[{"id":1,"description":"Create model",...}]\''
        )
        print("  # Create plan (overwrite existing)")
        print(
            '  mapify recitation create feat_auth "Add JWT auth" \'[{"id":1,...}]\' --force'
        )
        print("\n  # Update status")
        print("  mapify recitation update 1 in_progress")
        print('  mapify recitation update 1 in_progress "Missing import"')
        print("  mapify recitation update 1 completed")
        print("\n  # Get context for Actor")
        print("  mapify recitation get-context")
        print("\n  # Get statistics")
        print("  mapify recitation stats")
        print("\n  # Clear plan")
        print("  mapify recitation clear")
        print("\n  # Generate dev docs")
        print(
            "  mapify recitation generate-context  # Generate context.md from README and playbook"
        )
        print(
            "  mapify recitation generate-tasks    # Regenerate tasks.md from current plan"
        )
        print(
            "  mapify recitation get-docs          # Get all dev docs (plan + context + tasks)"
        )
        sys.exit(1)

    command = sys.argv[1]

    # Handle --help and -h flags
    if command in ["--help", "-h", "help"]:
        print("Usage:")
        print("  mapify recitation create <task_id> <goal> <subtasks_json> [--force]")
        print("  mapify recitation update <subtask_id> <status> [error]")
        print("  mapify recitation get-context")
        print("  mapify recitation stats")
        print("  mapify recitation clear")
        print("  mapify recitation generate-context")
        print("  mapify recitation generate-tasks")
        print("  mapify recitation get-docs")
        print("\nOptions:")
        print("  --force    Overwrite existing plan when using 'create' command")
        print("\nExamples:")
        print("  # Create plan")
        print(
            '  mapify recitation create feat_auth "Add JWT auth" \'[{"id":1,"description":"Create model",...}]\''
        )
        print("  # Create plan (overwrite existing)")
        print(
            '  mapify recitation create feat_auth "Add JWT auth" \'[{"id":1,...}]\' --force'
        )
        print("\n  # Update status")
        print("  mapify recitation update 1 in_progress")
        print('  mapify recitation update 1 in_progress "Missing import"')
        print("  mapify recitation update 1 completed")
        print("\n  # Get context for Actor")
        print("  mapify recitation get-context")
        print("\n  # Get statistics")
        print("  mapify recitation stats")
        print("\n  # Clear plan")
        print("  mapify recitation clear")
        print("\n  # Generate dev docs")
        print(
            "  mapify recitation generate-context  # Generate context.md from README and playbook"
        )
        print(
            "  mapify recitation generate-tasks    # Regenerate tasks.md from current plan"
        )
        print(
            "  mapify recitation get-docs          # Get all dev docs (plan + context + tasks)"
        )
        sys.exit(0)

    manager = RecitationManager(Path.cwd())

    if command == "create":
        if len(sys.argv) < 5:
            print("Error: create requires <task_id> <goal> <subtasks_json>")
            sys.exit(1)

        task_id = sys.argv[2]
        goal = sys.argv[3]
        subtasks_json = sys.argv[4]

        try:
            subtasks = json.loads(subtasks_json)
            plan = manager.create_plan(task_id, goal, subtasks, force=force_flag)
            print(
                json.dumps(
                    {
                        "status": "success",
                        "message": "Plan created",
                        "plan_file": str(manager.plan_file),
                        "subtasks_count": len(plan.subtasks),
                    },
                    indent=2,
                )
            )
        except ValueError as e:
            print(json.dumps({"status": "error", "message": str(e)}, indent=2))
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(
                json.dumps(
                    {"status": "error", "message": f"Invalid JSON: {e}"}, indent=2
                )
            )
            sys.exit(1)

    elif command == "update":
        if len(sys.argv) < 4:
            print("Error: update requires <subtask_id> <status> [error]")
            sys.exit(1)

        subtask_id = sys.argv[2]
        status = sys.argv[3]
        error = sys.argv[4] if len(sys.argv) > 4 else None

        try:
            plan = manager.update_subtask_status(subtask_id, status, error)
            print(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"Subtask {subtask_id} updated to {status}",
                        "current_subtask": plan.current_subtask_id,
                        "updated_at": plan.updated_at,
                    },
                    indent=2,
                )
            )
        except Exception as e:
            print(json.dumps({"status": "error", "message": str(e)}, indent=2))
            sys.exit(1)

    elif command == "get-context":
        context = manager.get_current_context()
        if context:
            print(context)
        else:
            print("# No active plan\n\nNo recitation plan is currently active.")
            sys.exit(1)

    elif command == "stats":
        stats = manager.get_statistics()
        if stats:
            print(json.dumps(stats, indent=2))
        else:
            print(
                json.dumps({"status": "error", "message": "No active plan"}, indent=2)
            )
            sys.exit(1)

    elif command == "clear":
        manager.clear_plan()
        print(json.dumps({"status": "success", "message": "Plan cleared"}, indent=2))

    elif command == "generate-context":
        try:
            context_file = manager.generate_context_md()
            print(
                json.dumps(
                    {
                        "status": "success",
                        "message": "Generated context.md",
                        "file": context_file,
                    },
                    indent=2,
                )
            )
        except Exception as e:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "message": f"Failed to generate context.md: {str(e)}",
                    },
                    indent=2,
                )
            )
            sys.exit(1)

    elif command == "generate-tasks":
        try:
            plan = manager.get_plan()
            if not plan:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "message": "No active plan to generate tasks from",
                        },
                        indent=2,
                    )
                )
                sys.exit(1)

            manager._generate_tasks_md(plan)
            print(
                json.dumps(
                    {
                        "status": "success",
                        "message": "Generated tasks.md",
                        "file": str(manager.tasks_file),
                    },
                    indent=2,
                )
            )
        except Exception as e:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "message": f"Failed to generate tasks.md: {str(e)}",
                    },
                    indent=2,
                )
            )
            sys.exit(1)

    elif command == "get-docs":
        try:
            docs = manager.get_dev_docs()
            print(json.dumps({"status": "success", "docs": docs}, indent=2))
        except Exception as e:
            print(
                json.dumps(
                    {"status": "error", "message": f"Failed to get dev docs: {str(e)}"},
                    indent=2,
                )
            )
            sys.exit(1)

    else:
        print(f"Error: Unknown command '{command}'")
        print("Run without arguments to see usage")
        sys.exit(1)
