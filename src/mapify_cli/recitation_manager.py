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
from typing import List, Optional


@dataclass
class Subtask:
    """Represents a single subtask in the plan"""
    id: int
    description: str
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
    acceptance_criteria: Optional[str] = None
    estimated_complexity: Optional[str] = None
    depends_on: List[int] = field(default_factory=list)
    iterations: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    """Represents the overall task plan"""
    task_id: str
    goal: str
    subtasks: List[Subtask]
    current_subtask_id: Optional[int] = None
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

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.map_dir = self.project_root / ".map"
        self.plan_file = self.map_dir / "current_plan.md"
        self.plan_json = self.map_dir / "current_plan.json"

        # Create .map directory if it doesn't exist
        self.map_dir.mkdir(exist_ok=True)

    def create_plan(self, task_id: str, goal: str, subtasks: List[dict]) -> TaskPlan:
        """
        Create a new task plan from TaskDecomposer output.

        Args:
            task_id: Unique identifier for the task
            goal: Overall goal description
            subtasks: List of subtask dictionaries from TaskDecomposer

        Returns:
            TaskPlan object
        """
        plan_subtasks = [
            Subtask(
                id=st['id'],
                description=st['description'],
                status='pending',
                acceptance_criteria=st.get('acceptance_criteria'),
                estimated_complexity=st.get('estimated_complexity'),
                depends_on=st.get('depends_on', [])
            )
            for st in subtasks
        ]

        plan = TaskPlan(
            task_id=task_id,
            goal=goal,
            subtasks=plan_subtasks,
            current_subtask_id=plan_subtasks[0].id if plan_subtasks else None
        )

        self._save_plan(plan)
        self._generate_markdown(plan)

        return plan

    def update_subtask_status(
        self,
        subtask_id: int,
        status: str,
        error: Optional[str] = None
    ) -> TaskPlan:
        """
        Update the status of a subtask.

        Args:
            subtask_id: ID of the subtask to update
            status: New status ('in_progress', 'completed', 'failed')
            error: Error message if status is 'failed'

        Returns:
            Updated TaskPlan
        """
        plan = self._load_plan()

        for subtask in plan.subtasks:
            if subtask.id == subtask_id:
                subtask.status = status
                if status == 'in_progress':
                    plan.current_subtask_id = subtask_id
                    subtask.iterations += 1
                if error:
                    subtask.errors.append(error)
                break

        plan.updated_at = datetime.now().isoformat()

        self._save_plan(plan)
        self._generate_markdown(plan)

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

        return self.plan_file.read_text()

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
            'task_id': plan.task_id,
            'goal': plan.goal,
            'subtasks': [
                {
                    'id': st.id,
                    'description': st.description,
                    'status': st.status,
                    'acceptance_criteria': st.acceptance_criteria,
                    'estimated_complexity': st.estimated_complexity,
                    'depends_on': st.depends_on,
                    'iterations': st.iterations,
                    'errors': st.errors
                }
                for st in plan.subtasks
            ],
            'current_subtask_id': plan.current_subtask_id,
            'created_at': plan.created_at,
            'updated_at': plan.updated_at
        }

        self.plan_json.write_text(json.dumps(plan_dict, indent=2))

    def _load_plan(self) -> Optional[TaskPlan]:
        """Load plan from JSON file"""
        if not self.plan_json.exists():
            return None

        plan_dict = json.loads(self.plan_json.read_text())

        subtasks = [
            Subtask(
                id=st['id'],
                description=st['description'],
                status=st['status'],
                acceptance_criteria=st.get('acceptance_criteria'),
                estimated_complexity=st.get('estimated_complexity'),
                depends_on=st.get('depends_on', []),
                iterations=st.get('iterations', 0),
                errors=st.get('errors', [])
            )
            for st in plan_dict['subtasks']
        ]

        return TaskPlan(
            task_id=plan_dict['task_id'],
            goal=plan_dict['goal'],
            subtasks=subtasks,
            current_subtask_id=plan_dict.get('current_subtask_id'),
            created_at=plan_dict.get('created_at'),
            updated_at=plan_dict.get('updated_at')
        )

    def _generate_markdown(self, plan: TaskPlan):
        """
        Generate the current_plan.md file for recitation.

        Format is optimized for model attention:
        - Clear visual markers (✓, →, ☐)
        - Current focus highlighted
        - Concise but complete
        """
        completed = sum(1 for st in plan.subtasks if st.status == 'completed')
        total = len(plan.subtasks)

        # Find current subtask
        current_st = None
        if plan.current_subtask_id:
            current_st = next(
                (st for st in plan.subtasks if st.id == plan.current_subtask_id),
                None
            )

        md_lines = [
            f"# Current Task: {plan.task_id}",
            "",
            "## Overall Goal",
            plan.goal,
            "",
            f"## Progress: {completed}/{total} subtasks completed",
            ""
        ]

        # Add subtasks list
        md_lines.append("## Subtasks")
        for st in plan.subtasks:
            if st.status == 'completed':
                marker = "✓"
            elif st.status == 'in_progress':
                marker = "→"
            elif st.status == 'failed':
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
            md_lines.extend([
                "## Current Focus",
                f"**Subtask {current_st.id}:** {current_st.description}",
                ""
            ])

            if current_st.acceptance_criteria:
                md_lines.extend([
                    "**Acceptance Criteria:**",
                    current_st.acceptance_criteria,
                    ""
                ])

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
        md_lines.extend([
            "---",
            f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
            "",
            "**Note:** This plan keeps goals fresh in context (Recitation pattern). "
            "Review before each subtask."
        ])

        self.plan_file.write_text("\n".join(md_lines))

    def get_statistics(self) -> dict:
        """Get statistics about the current plan"""
        plan = self._load_plan()
        if not plan:
            return {}

        return {
            'total_subtasks': len(plan.subtasks),
            'completed': sum(1 for st in plan.subtasks if st.status == 'completed'),
            'in_progress': sum(1 for st in plan.subtasks if st.status == 'in_progress'),
            'failed': sum(1 for st in plan.subtasks if st.status == 'failed'),
            'pending': sum(1 for st in plan.subtasks if st.status == 'pending'),
            'total_iterations': sum(st.iterations for st in plan.subtasks),
            'current_subtask': plan.current_subtask_id,
            'created_at': plan.created_at,
            'updated_at': plan.updated_at
        }


# Example usage
if __name__ == "__main__":
    # Example: Create a plan from TaskDecomposer output
    manager = RecitationManager(Path.cwd())

    example_subtasks = [
        {
            'id': 1,
            'description': 'Create User model with password hashing',
            'acceptance_criteria': 'Model validates email, hashes password with bcrypt',
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
            'description': 'Add JWT token generation',
            'acceptance_criteria': 'Tokens expire after 1h, use HS256',
            'estimated_complexity': 'low',
            'depends_on': [2]
        },
        {
            'id': 4,
            'description': 'Implement token validation middleware',
            'acceptance_criteria': 'Middleware checks token on protected routes',
            'estimated_complexity': 'medium',
            'depends_on': [3]
        },
        {
            'id': 5,
            'description': 'Add refresh token mechanism',
            'acceptance_criteria': 'POST /auth/refresh returns new access token',
            'estimated_complexity': 'high',
            'depends_on': [4]
        }
    ]

    # Create plan
    plan = manager.create_plan(
        task_id='feat_auth',
        goal='Implement JWT-based authentication with email/password',
        subtasks=example_subtasks
    )

    print("Created plan:", manager.plan_file)
    print("\nPlan markdown:\n")
    print(manager.get_current_context())

    # Simulate progress
    print("\n\n--- Starting subtask 1 ---")
    manager.update_subtask_status(1, 'in_progress')

    print("\n\n--- Completing subtask 1 ---")
    manager.update_subtask_status(1, 'completed')

    print("\n\n--- Starting subtask 2 ---")
    manager.update_subtask_status(2, 'in_progress')

    print("\n\n--- Failing subtask 2 (first attempt) ---")
    manager.update_subtask_status(2, 'in_progress', error='Missing import for JWT library')

    print("\n\nCurrent plan:\n")
    print(manager.get_current_context())

    print("\n\nStatistics:")
    print(json.dumps(manager.get_statistics(), indent=2))
