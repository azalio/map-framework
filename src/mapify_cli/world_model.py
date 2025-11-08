"""World Model for MAP Framework

Manages workflow-level context accumulation across subtasks.
Implements Phase 1.1 of Kosmos implementation plan.

The WorldModel provides:
1. Persistent storage of workflow context in JSON format
2. Accumulation of findings and patterns across subtasks
3. Impact tracking and quality metrics calculation
4. Context generation for agent prompts

Storage location: .map/dev_docs/world_model.json
"""

from typing import List, Dict, Optional, Any
from pathlib import Path
import json
from datetime import datetime
import os

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class WorldModelError(Exception):
    """Base exception for WorldModel errors"""
    pass


class WorldModelJSONError(WorldModelError):
    """Raised when JSON file is invalid or corrupted"""
    pass


class WorldModelSubtaskNotFoundError(WorldModelError):
    """Raised when subtask ID is not found in world model"""
    pass


class WorldModel:
    """Manages workflow-level context accumulation across subtasks"""

    def __init__(self, workflow_id: str, workflow_type: str):
        """
        Initialize WorldModel for a specific workflow.

        Args:
            workflow_id: Unique identifier for the workflow (e.g., kosmos_phase1_1762593902)
            workflow_type: Type of workflow (e.g., 'feature', 'debug', 'refactor')

        Raises:
            WorldModelJSONError: If existing JSON file is corrupted
        """
        self.workflow_id = workflow_id
        self.workflow_type = workflow_type
        self.file_path = Path(".map/dev_docs/world_model.json")
        self.schema = self._load_schema()
        self.data = self._load_or_create()

    def _load_schema(self) -> Optional[Dict[str, Any]]:
        """
        Load JSON schema for validation.

        Returns:
            Dictionary containing JSON schema, or None if schema file not found
        """
        schema_path = Path(__file__).parent / "world_model_schema.json"
        if schema_path.exists():
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError, IOError):
                # Schema file corrupted or unreadable, continue without validation
                return None
        return None

    def _validate_data(self, data: Dict[str, Any]) -> None:
        """
        Validate world model data against JSON schema.

        Args:
            data: Dictionary to validate

        Raises:
            WorldModelJSONError: If validation fails
        """
        if not HAS_JSONSCHEMA:
            # jsonschema not installed, skip validation
            return

        if self.schema is None:
            # Schema not available, skip validation
            return

        try:
            jsonschema.validate(instance=data, schema=self.schema)
        except jsonschema.ValidationError as e:
            raise WorldModelJSONError(
                f"World model data failed schema validation: {e.message}\n"
                f"Path: {'.'.join(str(p) for p in e.path)}"
            ) from e
        except jsonschema.SchemaError as e:
            raise WorldModelJSONError(
                f"World model schema is invalid: {e.message}"
            ) from e

    def _load_or_create(self) -> Dict[str, Any]:
        """
        Load existing world model or create new one.

        Returns:
            Dictionary containing world model data

        Raises:
            WorldModelJSONError: If JSON file exists but is invalid
        """
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Validate basic structure
                    if not isinstance(data, dict):
                        raise WorldModelJSONError(
                            f"World model file {self.file_path} contains invalid data: "
                            f"expected dict, got {type(data).__name__}"
                        )
                    # Validate against JSON schema
                    self._validate_data(data)
                    return data
            except json.JSONDecodeError as e:
                raise WorldModelJSONError(
                    f"Failed to parse world model JSON file {self.file_path}: {e}"
                ) from e
            except (OSError, IOError) as e:
                raise WorldModelError(
                    f"Failed to read world model file {self.file_path}: {e}"
                ) from e
        else:
            # Create new world model structure
            data = {
                "workflow_id": self.workflow_id,
                "workflow_type": self.workflow_type,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "subtasks": [],
                "cumulative_metrics": {
                    "total_files_changed": 0,
                    "total_lines_added": 0,
                    "total_lines_removed": 0,
                    "average_quality_score": 0.0,
                    "total_patterns_discovered": 0,
                    "total_security_issues": 0
                }
            }
            # Validate newly created data
            self._validate_data(data)
            return data

    def add_subtask(self, subtask_id: str, name: str, status: str = "pending") -> None:
        """
        Add new subtask to world model.

        Args:
            subtask_id: Unique identifier for the subtask (e.g., 'ST-001')
            name: Human-readable name/description of the subtask
            status: Initial status (default: 'pending'). Valid values:
                    'pending', 'in_progress', 'completed', 'failed'

        Raises:
            WorldModelError: If save operation fails
        """
        subtask = {
            "id": subtask_id,
            "name": name,
            "status": status,
            "findings": [],
            "patterns_discovered": [],
            "impact_analysis": {
                "files_changed": 0,
                "risk_level": "low",
                "dependencies_affected": [],
                "breaking_changes": False
            },
            "quality_score": 0.0,
            "validation_results": {},
            "agent_outputs": {}
        }
        self.data["subtasks"].append(subtask)
        self._save()

    def update_subtask(self, subtask_id: str, **kwargs) -> None:
        """
        Update subtask with new data.

        Special handling for list fields:
        - 'findings': extends existing list instead of replacing
        - 'patterns_discovered': extends existing list instead of replacing

        Args:
            subtask_id: ID of the subtask to update
            **kwargs: Fields to update (e.g., status="completed", quality_score=8.5)

        Raises:
            WorldModelSubtaskNotFoundError: If subtask_id is not found
            WorldModelError: If save operation fails

        Example:
            world_model.update_subtask(
                "ST-001",
                status="completed",
                findings=["All tests passed"],
                quality_score=9.0
            )
        """
        subtask_found = False
        for subtask in self.data["subtasks"]:
            if subtask["id"] == subtask_id:
                subtask_found = True
                for key, value in kwargs.items():
                    # Special handling for list fields - extend instead of replace
                    if key == "findings" and isinstance(value, list):
                        subtask["findings"].extend(value)
                    elif key == "patterns_discovered" and isinstance(value, list):
                        subtask["patterns_discovered"].extend(value)
                    else:
                        subtask[key] = value
                break

        if not subtask_found:
            raise WorldModelSubtaskNotFoundError(
                f"Subtask '{subtask_id}' not found in world model. "
                f"Available subtasks: {[st['id'] for st in self.data['subtasks']]}"
            )

        self.data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._recalculate_metrics()
        self._save()

    def add_finding(self, subtask_id: str, finding: str) -> None:
        """
        Add finding to specific subtask.

        Args:
            subtask_id: ID of the subtask
            finding: Finding text to add

        Raises:
            WorldModelSubtaskNotFoundError: If subtask_id is not found
            WorldModelError: If save operation fails
        """
        subtask_found = False
        for subtask in self.data["subtasks"]:
            if subtask["id"] == subtask_id:
                subtask_found = True
                subtask["findings"].append(finding)
                break

        if not subtask_found:
            raise WorldModelSubtaskNotFoundError(
                f"Subtask '{subtask_id}' not found in world model"
            )

        self._save()

    def add_pattern(self, subtask_id: str, pattern: str) -> None:
        """
        Add discovered pattern to subtask.

        Patterns are deduplicated automatically - adding the same pattern
        twice will only increment the total_patterns_discovered counter once.

        Args:
            subtask_id: ID of the subtask
            pattern: Pattern description to add

        Raises:
            WorldModelSubtaskNotFoundError: If subtask_id is not found
            WorldModelError: If save operation fails
        """
        subtask_found = False
        for subtask in self.data["subtasks"]:
            if subtask["id"] == subtask_id:
                subtask_found = True
                if pattern not in subtask["patterns_discovered"]:
                    subtask["patterns_discovered"].append(pattern)
                    self.data["cumulative_metrics"]["total_patterns_discovered"] += 1
                break

        if not subtask_found:
            raise WorldModelSubtaskNotFoundError(
                f"Subtask '{subtask_id}' not found in world model"
            )

        self._save()

    def set_quality_score(self, subtask_id: str, score: float) -> None:
        """
        Set quality score for subtask.

        Updates the subtask's quality_score and recalculates average_quality_score
        in cumulative_metrics.

        Args:
            subtask_id: ID of the subtask
            score: Quality score (typically 0.0 to 10.0)

        Raises:
            WorldModelSubtaskNotFoundError: If subtask_id is not found
            WorldModelError: If save operation fails
        """
        subtask_found = False
        for subtask in self.data["subtasks"]:
            if subtask["id"] == subtask_id:
                subtask_found = True
                subtask["quality_score"] = score
                break

        if not subtask_found:
            raise WorldModelSubtaskNotFoundError(
                f"Subtask '{subtask_id}' not found in world model"
            )

        self._recalculate_metrics()
        self._save()

    def update_impact_analysis(self, subtask_id: str, **impact_data) -> None:
        """
        Update impact analysis for subtask.

        Args:
            subtask_id: ID of the subtask
            **impact_data: Impact fields to update (e.g., files_changed=5, risk_level="medium")

        Raises:
            WorldModelSubtaskNotFoundError: If subtask_id is not found
            WorldModelError: If save operation fails

        Example:
            world_model.update_impact_analysis(
                "ST-001",
                files_changed=3,
                risk_level="medium",
                dependencies_affected=["requests", "pytest"],
                breaking_changes=True
            )
        """
        subtask_found = False
        for subtask in self.data["subtasks"]:
            if subtask["id"] == subtask_id:
                subtask_found = True
                subtask["impact_analysis"].update(impact_data)
                break

        if not subtask_found:
            raise WorldModelSubtaskNotFoundError(
                f"Subtask '{subtask_id}' not found in world model"
            )

        self._recalculate_metrics()
        self._save()

    def get_context_for_agent(self, current_subtask_id: Optional[str] = None) -> str:
        """
        Generate context summary for agent prompts.

        Creates a markdown-formatted summary of completed subtasks, their findings,
        patterns, and cumulative workflow metrics. Excludes the current subtask
        to avoid circular context.

        Args:
            current_subtask_id: ID of current subtask to exclude from context (optional)

        Returns:
            Markdown-formatted context string
        """
        completed_subtasks = [
            st for st in self.data["subtasks"]
            if st["status"] == "completed" and st["id"] != current_subtask_id
        ]

        if not completed_subtasks:
            return "No previous subtasks completed yet."

        context_lines = ["## Context from Previous Subtasks\n"]

        for st in completed_subtasks:
            context_lines.append(f"### {st['name']} (Quality: {st['quality_score']:.2f})")
            context_lines.append(f"**Status:** {st['status']}")

            if st["findings"]:
                context_lines.append("\n**Key Findings:**")
                for finding in st["findings"]:
                    context_lines.append(f"- {finding}")

            if st["patterns_discovered"]:
                context_lines.append("\n**Patterns Discovered:**")
                for pattern in st["patterns_discovered"]:
                    context_lines.append(f"- {pattern}")

            impact = st["impact_analysis"]
            context_lines.append(
                f"\n**Impact:** {impact['risk_level']} risk, "
                f"{impact['files_changed']} files changed"
            )
            context_lines.append("")

        # Add cumulative metrics
        metrics = self.data["cumulative_metrics"]
        context_lines.append("### Cumulative Workflow Metrics")
        context_lines.append(f"- Total files changed: {metrics['total_files_changed']}")
        context_lines.append(f"- Average quality score: {metrics['average_quality_score']:.2f}")
        context_lines.append(f"- Patterns discovered: {metrics['total_patterns_discovered']}")
        context_lines.append(f"- Security issues: {metrics['total_security_issues']}")

        return "\n".join(context_lines)

    def _recalculate_metrics(self) -> None:
        """
        Recalculate cumulative metrics based on completed subtasks.

        Updates:
        - total_files_changed: sum of files_changed across completed subtasks
        - average_quality_score: mean quality_score of completed subtasks
        - total_security_issues: sum of security_issues from validation_results

        Note: total_patterns_discovered is maintained incrementally in add_pattern()
        """
        completed = [st for st in self.data["subtasks"] if st["status"] == "completed"]

        if completed:
            self.data["cumulative_metrics"]["total_files_changed"] = sum(
                st["impact_analysis"]["files_changed"] for st in completed
            )

            avg_score = sum(st["quality_score"] for st in completed) / len(completed)
            self.data["cumulative_metrics"]["average_quality_score"] = round(avg_score, 3)

            self.data["cumulative_metrics"]["total_security_issues"] = sum(
                st["validation_results"].get("security_issues", 0) for st in completed
            )

    def _save(self) -> None:
        """
        Save world model to disk.

        Creates parent directory if it doesn't exist.
        Writes JSON with 2-space indentation for readability.

        Raises:
            WorldModelError: If directory creation or file write fails
            WorldModelJSONError: If data fails schema validation before save
        """
        try:
            # Validate data before saving
            self._validate_data(self.data)

            # Create parent directory if it doesn't exist
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write JSON atomically using temp file + rename
            temp_path = self.file_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

            # Atomic rename (on POSIX systems)
            temp_path.replace(self.file_path)

        except (OSError, IOError) as e:
            raise WorldModelError(
                f"Failed to save world model to {self.file_path}: {e}"
            ) from e
