"""
Agent contract validation using JSON Schema.

This module provides validation functions for agent inputs and outputs
against their JSON schema contracts.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from jsonschema import Draft7Validator, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of contract validation."""

    valid: bool
    errors: List[str]
    warnings: List[str]

    def __str__(self) -> str:
        if self.valid:
            return "✓ Validation passed"
        else:
            error_msg = "\n".join(f"  - {err}" for err in self.errors)
            return f"✗ Validation failed:\n{error_msg}"


class AgentContractValidator:
    """Validates agent inputs/outputs against JSON schemas."""

    def __init__(self, schemas_dir: Path = None):
        """
        Initialize validator with schema directory.

        Args:
            schemas_dir: Path to schemas directory. If None, uses packaged schemas.
        """
        if schemas_dir is None:
            # Default to packaged schemas in src/mapify_cli/schemas
            schemas_dir = Path(__file__).parent.parent / "schemas"

        self.schemas_dir = schemas_dir
        self._input_schemas = self._load_all_schemas("input")
        self._output_schemas = self._load_all_schemas("output")

    def _load_all_schemas(self, schema_type: str) -> Dict[str, Dict]:
        """
        Load all agent schemas of given type (input or output).

        Args:
            schema_type: "input" or "output"

        Returns:
            Dict mapping agent names to schemas
        """
        schemas = {}

        if not self.schemas_dir.exists():
            logger.warning(f"Schema directory not found: {self.schemas_dir}")
            return schemas

        # Agent names (with hyphens as in file names)
        agent_names = [
            "actor",
            "monitor",
            "predictor",
            "evaluator",
            "reflector",
            "curator",
            "task-decomposer",
            "documentation-reviewer",
        ]

        for agent_name in agent_names:
            schema_path = self.schemas_dir / f"{agent_name}_{schema_type}.json"

            if not schema_path.exists():
                logger.warning(f"Schema file not found: {schema_path}")
                continue

            try:
                with open(schema_path) as f:
                    schema = json.load(f)

                # Store with underscored name for normalization
                normalized_name = agent_name.replace("-", "_")
                schemas[normalized_name] = schema

                # Also store with original hyphenated name
                if "-" in agent_name:
                    schemas[agent_name] = schema

            except Exception as e:
                logger.error(f"Failed to load schema {schema_path}: {e}")
                continue

        return schemas

    def validate_agent_input(
        self,
        agent_name: str,
        input_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate agent input against its contract.

        Args:
            agent_name: Name of the agent (e.g., "actor", "monitor", "task-decomposer")
            input_data: Input data dictionary to validate

        Returns:
            ValidationResult with validation status and errors
        """
        # Normalize agent name (hyphens to underscores)
        normalized_name = agent_name.replace("-", "_")

        if normalized_name not in self._input_schemas:
            return ValidationResult(
                valid=False,
                errors=[f"Unknown agent: {agent_name}"],
                warnings=[]
            )

        schema = self._input_schemas[normalized_name]
        validator = Draft7Validator(schema)

        errors = []
        warnings = []

        try:
            # Validate against schema
            for error in validator.iter_errors(input_data):
                # Format error message with field path
                field_path = ".".join(str(p) for p in error.path) or "root"
                errors.append(
                    f"Field '{field_path}': {error.message}"
                )

            # Additional validation warnings (not errors)
            if not errors:
                # Check for unexpected additional properties
                if not schema.get('additionalProperties', True):
                    expected_props = set(schema.get('properties', {}).keys())
                    actual_props = set(input_data.keys())
                    extra_props = actual_props - expected_props

                    if extra_props:
                        warnings.append(
                            f"Unexpected properties: {', '.join(extra_props)}"
                        )

            valid = len(errors) == 0

            if valid:
                logger.info(f"✓ {agent_name} input validation passed")
            else:
                logger.warning(
                    f"✗ {agent_name} input validation failed: {len(errors)} error(s)"
                )

            return ValidationResult(
                valid=valid,
                errors=errors,
                warnings=warnings
            )

        except Exception as e:
            logger.error(f"Validation error for {agent_name}: {e}")
            return ValidationResult(
                valid=False,
                errors=[f"Validation exception: {str(e)}"],
                warnings=[]
            )

    def validate_agent_output(
        self,
        agent_name: str,
        output_data: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate agent output against its contract.

        Args:
            agent_name: Name of the agent
            output_data: Output data dictionary to validate

        Returns:
            ValidationResult with validation status and errors
        """
        # Normalize agent name
        normalized_name = agent_name.replace("-", "_")

        if normalized_name not in self._output_schemas:
            return ValidationResult(
                valid=False,
                errors=[f"Unknown agent: {agent_name}"],
                warnings=[]
            )

        schema = self._output_schemas[normalized_name]
        validator = Draft7Validator(schema)

        errors = []
        warnings = []

        try:
            for error in validator.iter_errors(output_data):
                field_path = ".".join(str(p) for p in error.path) or "root"
                errors.append(
                    f"Field '{field_path}': {error.message}"
                )

            valid = len(errors) == 0

            if valid:
                logger.info(f"✓ {agent_name} output validation passed")
            else:
                logger.warning(
                    f"✗ {agent_name} output validation failed: {len(errors)} error(s)"
                )

            return ValidationResult(
                valid=valid,
                errors=errors,
                warnings=warnings
            )

        except Exception as e:
            logger.error(f"Validation error for {agent_name}: {e}")
            return ValidationResult(
                valid=False,
                errors=[f"Validation exception: {str(e)}"],
                warnings=[]
            )


# Convenience functions for direct use
_validator = None


def validate_agent_input(agent_name: str, input_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate agent input (convenience function).

    Args:
        agent_name: Agent name (actor, monitor, etc.)
        input_data: Input dictionary

    Returns:
        ValidationResult
    """
    global _validator
    if _validator is None:
        _validator = AgentContractValidator()

    return _validator.validate_agent_input(agent_name, input_data)


def validate_agent_output(agent_name: str, output_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate agent output (convenience function).

    Args:
        agent_name: Agent name
        output_data: Output dictionary

    Returns:
        ValidationResult
    """
    global _validator
    if _validator is None:
        _validator = AgentContractValidator()

    return _validator.validate_agent_output(agent_name, output_data)
