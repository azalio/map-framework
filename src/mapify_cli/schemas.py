"""
Schema definitions for MAP Framework.

Contains JSON Schema definitions for .map/ state artifacts (v3.0+).

These schemas are embedded in code to ensure they're available
in packaged installations (uv tool install, pip install).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_artifact(
    data: dict[str, Any],
    schema: dict[str, Any],
    *,
    raise_on_error: bool = False,
) -> tuple[bool, list[str]]:
    """Validate a MAP artifact dict against a JSON Schema.

    Uses jsonschema if available, falls back to required-field checking.

    Args:
        data: The artifact data to validate.
        schema: A JSON Schema dict (one of *_SCHEMA constants).
        raise_on_error: If True, raise ValueError on first error.

    Returns:
        (is_valid, list_of_error_messages)
    """
    try:
        import jsonschema  # type: ignore[import-untyped]

        # Use best available validator (prefer 2020-12, fall back to Draft7/4)
        validator_cls = getattr(
            jsonschema,
            "Draft202012Validator",
            getattr(
                jsonschema,
                "Draft7Validator",
                getattr(jsonschema, "Draft4Validator", None),
            ),
        )
        if validator_cls is None:
            raise ImportError("No suitable jsonschema validator found")
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        messages = [
            f"{'.'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors
        ]
        if raise_on_error and messages:
            raise ValueError(f"Schema validation failed: {messages[0]}")
        return (len(messages) == 0, messages)
    except ImportError:
        # Fallback: check required fields only
        messages = []
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                messages.append(f"<root>: '{field}' is a required property")
        if raise_on_error and messages:
            raise ValueError(f"Schema validation failed: {messages[0]}")
        return (len(messages) == 0, messages)


def load_and_validate(
    path: Path,
    schema: dict[str, Any],
    *,
    raise_on_error: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Load a JSON file and validate it against a schema.

    Args:
        path: Path to the JSON file.
        schema: A JSON Schema dict.
        raise_on_error: If True, raise on file/parse/validation errors.

    Returns:
        (parsed_data_or_None, list_of_error_messages)
    """
    if not path.exists():
        msg = f"File not found: {path}"
        if raise_on_error:
            raise FileNotFoundError(msg)
        return (None, [msg])

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        msg = f"Cannot read {path}: {exc}"
        if raise_on_error:
            raise ValueError(msg) from exc
        return (None, [msg])

    is_valid, errors = validate_artifact(data, schema, raise_on_error=raise_on_error)
    return (data if is_valid else None, errors)


# ============================================================================
# JSON SCHEMA DEFINITIONS FOR .map/ STATE ARTIFACTS
# ============================================================================
# These schemas define the structure of machine-readable state files
# created by MAP workflows in the .map/ directory.
# Format: JSON Schema Draft 2020-12

STATE_ARTIFACT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/state-artifact.json",
    "title": "MAP Workflow State Artifact",
    "description": "State artifact for MAP workflows stored in .map/state_<branch>.json",
    "type": "object",
    "properties": {
        "workflow": {
            "type": "string",
            "description": "Type of MAP workflow (e.g., 'map-efficient', 'map-debug', 'map-fast')",
            "examples": ["map-efficient", "map-debug", "map-fast"],
        },
        "terminal_status": {
            "type": "string",
            "enum": ["pending", "complete", "blocked", "won't_do", "superseded"],
            "description": "Terminal status of the workflow. 'pending' = in progress, 'complete' = successfully finished, 'blocked' = cannot proceed, 'won't_do' = intentionally not completed (e.g., user ended early), 'superseded' = replaced by another workflow",
        },
        "active_subtask_id": {
            "type": ["string", "null"],
            "description": "ID of currently active subtask, or null if no subtask is active",
            "examples": ["ST-001", "ST-042"],
        },
        "subtasks": {
            "type": "array",
            "description": "List of subtasks in this workflow",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique subtask identifier",
                        "examples": ["ST-001", "ST-042"],
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable subtask title",
                        "examples": [
                            "Create JSON schema definitions",
                            "Implement validation logic",
                        ],
                    },
                    "status": {
                        "type": "string",
                        "enum": [
                            "pending",
                            "in_progress",
                            "complete",
                            "blocked",
                            "won't_do",
                        ],
                        "description": "Current status of this subtask",
                    },
                    "validation_criteria": {
                        "type": "array",
                        "description": "List of validation criteria for this subtask",
                        "items": {
                            "type": "string",
                            "description": "A single validation criterion",
                        },
                    },
                },
                "required": ["id", "title", "status"],
                "additionalProperties": True,
            },
        },
        "ended_early": {
            "type": ["object", "null"],
            "description": "Information about early workflow termination, or null if workflow was not ended early",
            "properties": {
                "by_user": {
                    "type": "boolean",
                    "description": "True if user explicitly requested early termination (e.g., 'закончили', 'stop', 'enough')",
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for early termination",
                    "examples": [
                        "User requested stop",
                        "Blocked by external dependency",
                        "Requirements changed",
                    ],
                },
                "at_subtask_id": {
                    "type": ["string", "null"],
                    "description": "ID of subtask where workflow was terminated, or null if terminated before any subtask",
                    "examples": ["ST-003"],
                },
            },
            "required": ["by_user", "reason"],
            "additionalProperties": False,
        },
        "verification": {
            "type": ["object", "null"],
            "description": "Aggregated verification results from last verification run, or null if no verification has been performed",
            "properties": {
                "overall": {
                    "type": "string",
                    "enum": ["pass", "fail", "unknown"],
                    "description": "Overall verification status. 'pass' = all checks passed, 'fail' = one or more checks failed, 'unknown' = verification not run or inconclusive",
                },
                "recipes": {
                    "type": "array",
                    "description": "List of verification recipes (checks) that were run",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique identifier for this verification recipe",
                                "examples": ["lint", "test", "type-check"],
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pass", "fail", "skipped"],
                                "description": "'pass' = check succeeded, 'fail' = check failed, 'skipped' = check not run (e.g., missing toolchain)",
                            },
                            "summary": {
                                "type": "string",
                                "description": "Human-readable summary of verification result",
                            },
                            "duration_ms": {
                                "type": ["number", "null"],
                                "description": "Duration of check in milliseconds, or null if not measured",
                                "minimum": 0,
                            },
                        },
                        "required": ["id", "status"],
                        "additionalProperties": True,
                    },
                },
            },
            "required": ["overall"],
            "additionalProperties": False,
        },
        "repo_insight": {
            "type": ["object", "null"],
            "description": "Repository insights detected at workflow start, or null if insights not generated",
            "properties": {
                "language": {
                    "type": ["string", "null"],
                    "description": "Primary programming language detected (e.g., 'python', 'javascript', 'go', 'rust')",
                    "examples": [
                        "python",
                        "javascript",
                        "go",
                        "rust",
                        "typescript",
                        "unknown",
                    ],
                },
                "suggested_checks": {
                    "type": "array",
                    "description": "List of suggested verification commands based on detected toolchain",
                    "items": {
                        "type": "string",
                        "description": "A suggested command to run",
                    },
                    "examples": [
                        ["make check", "pytest tests/"],
                        ["npm test", "npm run lint"],
                    ],
                },
                "key_dirs": {
                    "type": "array",
                    "description": "Key directories detected in repository (e.g., source code, tests, docs)",
                    "items": {
                        "type": "string",
                        "description": "A key directory path (relative to repo root)",
                    },
                    "examples": [
                        ["src/", "tests/", "docs/"],
                        ["lib/", "spec/", "bin/"],
                    ],
                },
            },
            "additionalProperties": True,
        },
    },
    "required": ["workflow", "terminal_status"],
    "additionalProperties": True,
}


VERIFICATION_RESULTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/verification-results.json",
    "title": "MAP Verification Results",
    "description": "Verification results artifact stored in .map/verification_results_<branch>.json",
    "type": "object",
    "properties": {
        "overall": {
            "type": "string",
            "enum": ["pass", "fail", "unknown"],
            "description": "Overall verification status. 'pass' = all checks passed, 'fail' = one or more checks failed, 'unknown' = verification not run or inconclusive",
        },
        "recipes": {
            "type": "array",
            "description": "List of verification recipes (checks) that were run",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique identifier for this verification recipe",
                        "examples": ["lint", "test", "type-check", "security-scan"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pass", "fail", "skipped"],
                        "description": "'pass' = check succeeded, 'fail' = check failed, 'skipped' = check not run (e.g., missing toolchain, timeout, no configuration)",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Human-readable summary of verification result",
                        "examples": [
                            "All tests passed",
                            "3 linting errors found",
                            "Type checking skipped: mypy not installed",
                        ],
                    },
                    "duration_ms": {
                        "type": ["number", "null"],
                        "description": "Duration of check in milliseconds, or null if not measured",
                        "minimum": 0,
                    },
                },
                "required": ["id", "status", "summary"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["overall", "recipes"],
    "additionalProperties": True,
}


BLUEPRINT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/blueprint.json",
    "title": "MAP Blueprint",
    "description": "Blueprint artifact produced by /map-plan, stored in .map/<branch>/blueprint.json",
    "type": "object",
    "properties": {
        "subtasks": {
            "type": "array",
            "description": "Ordered list of subtasks with dependency information",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique subtask identifier (e.g., ST-001)",
                        "pattern": "^ST-\\d{3,}$",
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable subtask title",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed subtask description",
                    },
                    "dependencies": {
                        "type": "array",
                        "description": "List of subtask IDs this task depends on",
                        "items": {"type": "string", "pattern": "^ST-\\d{3,}$"},
                    },
                    "affected_files": {
                        "type": "array",
                        "description": "Files expected to be created or modified",
                        "items": {"type": "string"},
                    },
                    "creates_files": {
                        "type": "array",
                        "description": (
                            "Optional subset of affected_files this subtask creates "
                            "from scratch (expected-absent on disk); the prose-free "
                            "create-vs-modify signal used by "
                            "validate_blueprint_contract instead of description phrases"
                        ),
                        "items": {"type": "string"},
                    },
                    "requiredness": {
                        "type": "string",
                        "enum": [
                            "explicit",
                            "implied_by_acceptance",
                            "repo_required",
                            "safety_required",
                            "optional",
                            "omitted_yagni",
                            "ambiguous",
                        ],
                        "description": (
                            "Planner classification for whether this work is required. "
                            "Active subtasks should not use omitted_yagni; put omitted "
                            "items in blueprint.deferred_yagni instead."
                        ),
                    },
                    "pruneable": {
                        "type": "boolean",
                        "description": (
                            "True only when the subtask is safe to recommend for user-approved "
                            "YAGNI pruning; explicit, acceptance-critical, repo-required, "
                            "safety-required, and ambiguous work is never pruneable."
                        ),
                    },
                    "prune_rationale": {
                        "type": "string",
                        "description": "Why this subtask is or is not pruneable.",
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "description": "Criteria that must be met for the subtask to be considered complete",
                        "items": {"type": "string"},
                    },
                    "validation_criteria": {
                        "type": "array",
                        "description": (
                            "Commands or checks that prove the subtask contract is complete; "
                            "each owned coverage_map requirement should be cited as "
                            "[AC-1], [INV-1], etc."
                        ),
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "examples": [
                                "VC1 [AC-1]: invalid artifacts return actionable errors",
                            ],
                        },
                        "minItems": 1,
                    },
                    "aag_contract": {
                        "type": "string",
                        "description": "Actor -> Action(params) -> Goal contract for the subtask",
                    },
                    "risk": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Risk level of this subtask",
                    },
                    "expected_diff_size": {
                        "type": "string",
                        "enum": ["tiny", "small", "medium", "large"],
                        "description": "Expected implementation size for this subtask, used to catch oversized plan slices before execution",
                    },
                    "concern_type": {
                        "type": "string",
                        "enum": [
                            "api",
                            "config",
                            "data",
                            "docs",
                            "infra",
                            "observability",
                            "refactor",
                            "release",
                            "runtime",
                            "security",
                            "tests",
                            "ui",
                            "mixed",
                        ],
                        "description": "Primary concern owned by this subtask; mixed requires explicit justification in MAP validation",
                    },
                    "one_logical_step": {
                        "type": "boolean",
                        "description": "True when the subtask has one reviewable logical purpose",
                    },
                    "split_rationale": {
                        "type": "string",
                        "description": "Required by MAP validation when expected_diff_size is large",
                    },
                    "concern_justification": {
                        "type": "string",
                        "description": "Required by MAP validation when concern_type is mixed",
                    },
                },
                "required": [
                    "id",
                    "title",
                    "dependencies",
                    "affected_files",
                    "aag_contract",
                    "expected_diff_size",
                    "concern_type",
                    "one_logical_step",
                    "validation_criteria",
                ],
                "additionalProperties": True,
            },
        },
        # Forward-coverage source-of-truth: the authoritative list of requirement
        # IDs lives in the spec's Requirements Index (the mapify:requirements-index:v1
        # block, parsed by parse_requirements_index in map_step_runner). The
        # decomposition-completeness gate diffs that index against these coverage_map
        # keys. Acceptance criteria are deliberately NOT stored as a blueprint field
        # (the decomposer cannot be trusted to declare the set it is checked against);
        # coverage_map remains a mapping of those spec IDs to owning subtasks only.
        "coverage_map": {
            "type": "object",
            "description": (
                "Maps spec acceptance criteria, invariants, and cross-cutting "
                "requirements, including every hard_constraint id, to owning subtask IDs; each key must appear as a "
                "bracketed tag in the owning subtask's validation_criteria"
            ),
            "minProperties": 1,
            "additionalProperties": {"type": "string", "pattern": "^ST-\\d{3,}$"},
        },
        "deferred_yagni": {
            "type": "array",
            "description": (
                "User-visible parking lot of speculative work recommended for omission. "
                "These items are never silently deleted: REVIEW_PLAN must show them and "
                "receive explicit user approval before execution proceeds."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "pattern": "^YG-\\d{3,}$"},
                    "title": {"type": "string", "minLength": 1},
                    "rationale": {"type": "string", "minLength": 1},
                    "restore_hint": {"type": "string", "minLength": 1},
                    "source_subtask_id": {"type": "string", "pattern": "^ST-\\d{3,}$"},
                },
                "required": ["id", "title", "rationale", "restore_hint"],
                "additionalProperties": True,
            },
        },
        "hard_constraints": {
            "type": "array",
            "description": (
                "Non-negotiable requirements that block planning or implementation when omitted; "
                "each id must appear in coverage_map and as a bracketed validation_criteria tag"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1, "examples": ["HC-1"]},
                    "description": {"type": "string", "minLength": 1},
                    "source": {"type": "string"},
                },
                "required": ["id", "description"],
                "additionalProperties": True,
            },
        },
        "soft_constraints": {
            "type": "array",
            "description": (
                "Negotiable preferences or quality goals; include the id in coverage_map when satisfied, "
                "or add tradeoff_rationale when consciously deferred or traded off"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1, "examples": ["SC-1"]},
                    "description": {"type": "string", "minLength": 1},
                    "source": {"type": "string"},
                    "tradeoff_rationale": {"type": "string"},
                },
                "required": ["id", "description"],
                "additionalProperties": True,
            },
        },
        "blueprint": {
            "type": "object",
            "description": "Wrapped TaskDecomposer blueprint body",
            "properties": {
                "subtasks": {"$ref": "#/properties/subtasks"},
                "coverage_map": {"$ref": "#/properties/coverage_map"},
                "deferred_yagni": {"$ref": "#/properties/deferred_yagni"},
                "hard_constraints": {"$ref": "#/properties/hard_constraints"},
                "soft_constraints": {"$ref": "#/properties/soft_constraints"},
                "metadata": {"$ref": "#/properties/metadata"},
            },
            "required": ["subtasks", "coverage_map", "hard_constraints", "soft_constraints"],
            "additionalProperties": True,
        },
        "metadata": {
            "type": "object",
            "description": "Blueprint metadata",
            "properties": {
                "created_at": {"type": "string", "format": "date-time"},
                "workflow": {"type": "string"},
                "goal": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
    "anyOf": [
        {"required": ["subtasks", "coverage_map", "hard_constraints", "soft_constraints"]},
        {"required": ["blueprint"]},
    ],
    "additionalProperties": True,
}


REPO_INSIGHT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/repo-insight.json",
    "title": "MAP Repository Insight",
    "description": "Repository insights artifact stored in .map/repo_insight_<branch>.json",
    "type": "object",
    "properties": {
        "language": {
            "type": ["string", "null"],
            "description": "Primary programming language detected by marker files (e.g., pyproject.toml -> 'python', package.json -> 'javascript', go.mod -> 'go', Cargo.toml -> 'rust')",
            "examples": [
                "python",
                "javascript",
                "go",
                "rust",
                "typescript",
                "java",
                "kotlin",
                "unknown",
            ],
        },
        "suggested_checks": {
            "type": "array",
            "description": "List of suggested verification commands based on detected toolchain and conventions",
            "items": {
                "type": "string",
                "description": "A suggested command to run (e.g., 'make check', 'pytest tests/', 'npm test')",
            },
            "examples": [
                [
                    "make check",
                    "pytest tests/test_template_render.py -v",
                    "make render-templates",
                ]
            ],
        },
        "key_dirs": {
            "type": "array",
            "description": "Key directories detected in repository structure (e.g., source code, tests, documentation)",
            "items": {
                "type": "string",
                "description": "A key directory path relative to repository root",
            },
            "examples": [
                ["src/", "tests/", "docs/"],
                ["lib/", "spec/", "bin/", "config/"],
            ],
        },
    },
    "required": ["language", "suggested_checks", "key_dirs"],
    "additionalProperties": True,
}


WORKFLOW_FIT_DECISION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/workflow-fit-decision.json",
    "title": "MAP Workflow Fit Decision",
    "description": "Preflight workflow-fit decision stored in .map/<branch>/workflow-fit.json",
    "type": "object",
    "properties": {
        "version": {"type": "string"},
        "recommended_workflow": {
            "type": "string",
            "enum": [
                "direct-edit",
                "map-fast",
                "map-efficient",
                "map-tdd",
                "map-plan",
            ],
        },
        "needs_map": {"type": "boolean"},
        "decision_summary": {"type": "string"},
        "signals": {
            "type": "object",
            "properties": {
                "expected_diff_size": {
                    "type": "string",
                    "enum": ["tiny", "small", "medium", "large"],
                },
                "has_new_invariants": {"type": "boolean"},
                "needs_independent_review": {"type": "boolean"},
                "has_clear_acceptance_criteria": {"type": "boolean"},
                "test_first_required": {"type": "boolean"},
                # Optional (not required): pre-existing workflow-fit.json files
                # written before this signal existed must still validate. New
                # writes always emit it (record_workflow_fit defaults it False).
                "depends_on_runtime_state": {"type": "boolean"},
            },
            "required": [
                "expected_diff_size",
                "has_new_invariants",
                "needs_independent_review",
                "has_clear_acceptance_criteria",
                "test_first_required",
            ],
            "additionalProperties": False,
        },
        "updated_at": {"type": "string", "format": "date-time"},
    },
    "required": [
        "version",
        "recommended_workflow",
        "needs_map",
        "decision_summary",
        "signals",
        "updated_at",
    ],
    "additionalProperties": False,
}


SKILL_REQUIREMENTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/skill-requirements.json",
    "title": "MAP Skill Requirements",
    "description": (
        "Runtime-dependency sub-block for a MAP skill entry in skill-rules.json. "
        "All four requires-* fields are optional; omit any that are not needed."
    ),
    "type": "object",
    "properties": {
        "requires-env": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Environment variable names that must be set at pre-install check time.",
        },
        "requires-pip": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Python packages that must be importable. "
                "Values are Python IMPORT names (e.g. 'yaml', not 'PyYAML')."
            ),
        },
        "requires-cmd": {
            "type": "array",
            "items": {"type": "string"},
            "description": "CLI commands that must be available on PATH.",
        },
        "requires-skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Other skill names this skill depends on.",
        },
    },
    "required": [],
    "additionalProperties": False,
}

# Single authority for the four requires-* field names; consumers DERIVE from this
# rather than hardcoding the list (see architecture-patterns: Single-Source Schema Dict).
_skill_req_props = SKILL_REQUIREMENTS_SCHEMA["properties"]
assert isinstance(_skill_req_props, dict)  # runtime guard; schema is always a dict
SKILL_REQUIREMENTS_KEYS: tuple[str, ...] = tuple(_skill_req_props)


ARTIFACT_STAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/artifact-stage.json",
    "title": "MAP Artifact Stage",
    "description": "One stage entry inside artifact_manifest.json",
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
        "artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["path", "kind"],
                "additionalProperties": False,
            },
        },
        "metadata": {"type": "object"},
    },
    "required": ["status", "updated_at", "artifacts", "metadata"],
    "additionalProperties": False,
}


ARTIFACT_MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/artifact-manifest.json",
    "title": "MAP Artifact Manifest",
    "description": "Branch-scoped artifact manifest stored in .map/<branch>/artifact_manifest.json",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
        "stages": {
            "type": "object",
            "properties": {
                "workflow_fit": ARTIFACT_STAGE_SCHEMA,
                "spec": ARTIFACT_STAGE_SCHEMA,
                "plan": ARTIFACT_STAGE_SCHEMA,
                "test_contract": ARTIFACT_STAGE_SCHEMA,
                "repro_probe": ARTIFACT_STAGE_SCHEMA,
                "implementation": ARTIFACT_STAGE_SCHEMA,
                "review": ARTIFACT_STAGE_SCHEMA,
                "verification": ARTIFACT_STAGE_SCHEMA,
                "retry_quarantine": ARTIFACT_STAGE_SCHEMA,
                "flaky_test_triage": ARTIFACT_STAGE_SCHEMA,
                "qualitative_convergence": ARTIFACT_STAGE_SCHEMA,
                "anti_repeat": ARTIFACT_STAGE_SCHEMA,
                "escalation": ARTIFACT_STAGE_SCHEMA,
                "token_budget": ARTIFACT_STAGE_SCHEMA,
                "run_health": ARTIFACT_STAGE_SCHEMA,
                "learn_handoff": ARTIFACT_STAGE_SCHEMA,
                "implementer_readiness": ARTIFACT_STAGE_SCHEMA,
                # Stages previously missing from this schema though present in
                # ARTIFACT_STAGE_NAMES (documentary only — the manifest schema has
                # no runtime validator; kept in sync to match the stage authority).
                "approval_hold": ARTIFACT_STAGE_SCHEMA,
                "worktree": ARTIFACT_STAGE_SCHEMA,
                "context_usefulness": ARTIFACT_STAGE_SCHEMA,
                "wayfind_handoff": ARTIFACT_STAGE_SCHEMA,
            },
            "required": [
                "workflow_fit",
                "spec",
                "plan",
                "test_contract",
                "implementation",
                "review",
                "verification",
                "learn_handoff",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["schema_version", "branch", "updated_at", "stages"],
    "additionalProperties": False,
}


IMPLEMENTER_READINESS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/implementer-readiness.json",
    "title": "MAP Implementer Readiness Review",
    "description": (
        "Pre-implementation readiness artifact stored in "
        ".map/<branch>/implementation-readiness.json"
    ),
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "verdict": {
            "type": "string",
            "enum": [
                "ready",
                "needs_clarification",
                "needs_spec_revision",
                "accepted_with_risk",
            ],
        },
        "blocking_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "spec_reference": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "api_contract",
                            "nfr",
                            "edge_case",
                            "ownership",
                            "rationale",
                        ],
                    },
                },
                "required": ["question", "category"],
                "additionalProperties": False,
            },
        },
        "non_blocking_risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "acceptance_rationale": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": [
        "schema_version",
        "branch",
        "generated_at",
        "verdict",
        "blocking_questions",
        "non_blocking_risks",
        "summary",
    ],
    "additionalProperties": False,
}


TOKEN_BUDGET_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "recorded_at": {"type": "string", "format": "date-time"},
        "path_name": {"type": "string"},
        "configured_budget_tokens": {"type": "integer", "minimum": 0},
        "estimated_tokens_before": {"type": "integer", "minimum": 0},
        "estimated_tokens_after": {"type": "integer", "minimum": 0},
        "budget_action": {"type": "string", "enum": ["none", "truncated"]},
        "clipped_sections": {"type": "array", "items": {"type": "string"}},
        "artifact_references": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["path", "kind"],
                "additionalProperties": False,
            },
        },
        "metadata": {"type": "object"},
    },
    "required": [
        "recorded_at",
        "path_name",
        "configured_budget_tokens",
        "estimated_tokens_before",
        "estimated_tokens_after",
        "budget_action",
        "clipped_sections",
        "artifact_references",
    ],
    "additionalProperties": False,
}


TOKEN_BUDGET_REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/token-budget-report.json",
    "title": "MAP Token Budget Report",
    "description": "Branch-scoped prompt budget decisions stored in .map/<branch>/token_budget.json",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
        "decisions": {
            "type": "array",
            "items": TOKEN_BUDGET_DECISION_SCHEMA,
        },
    },
    "required": ["schema_version", "branch", "updated_at", "decisions"],
    "additionalProperties": False,
}


RETRY_QUARANTINE_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "subtask_id": {"type": "string"},
        "retry_count": {"type": "integer", "minimum": 2},
        "isolation_mode": {"type": "string", "enum": ["clean_retry"]},
        "failed_attempt": {"type": "string"},
        "monitor_rejection_summary": {"type": "string"},
        "rejected_assumptions": {"type": "array", "items": {"type": "string"}},
        "do_not_repeat": {"type": "array", "items": {"type": "string"}},
        "preserved_constraints": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "required_evidence": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "source_artifacts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["path", "kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "subtask_id",
        "retry_count",
        "isolation_mode",
        "failed_attempt",
        "monitor_rejection_summary",
        "rejected_assumptions",
        "do_not_repeat",
        "preserved_constraints",
        "required_evidence",
        "source_artifacts",
    ],
    "additionalProperties": False,
}


RETRY_QUARANTINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/retry-quarantine.json",
    "title": "MAP Retry Quarantine",
    "description": "Compact clean-room retry context stored in .map/<branch>/retry_quarantine.json",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
        "quarantines": {
            "type": "array",
            "items": RETRY_QUARANTINE_ENTRY_SCHEMA,
            "minItems": 1,
        },
    },
    "required": ["schema_version", "branch", "updated_at", "quarantines"],
    "additionalProperties": False,
}


FLAKY_TEST_TRIAGE_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "run": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "enum": ["passed", "failed"]},
        "exit_code": {"type": "integer"},
        "summary": {"type": "string"},
        "timed_out": {"type": "boolean"},
        "duration_seconds": {"type": "number", "minimum": 0},
        "stdout_tail": {"type": "string"},
        "stderr_tail": {"type": "string"},
    },
    "required": ["run", "status", "exit_code", "summary"],
    "additionalProperties": False,
}


FLAKY_TEST_TRIAGE_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "check_id": {"type": "string"},
        "command": {"type": "string"},
        "reason": {"type": "string"},
        "run_count": {"type": "integer", "minimum": 1},
        "pass_count": {"type": "integer", "minimum": 0},
        "fail_count": {"type": "integer", "minimum": 0},
        "outcome_sequence": {
            "type": "array",
            "items": {"type": "string", "enum": ["passed", "failed"]},
            "minItems": 1,
        },
        "disposition": {
            "type": "string",
            "enum": [
                "deferred_nondeterministic",
                "deterministic_failure",
                "not_reproduced",
                "insufficient_evidence",
            ],
        },
        "recommended_next_action": {"type": "string"},
        "monitor_verdict_policy": {
            "type": "string",
            "enum": ["not_valid_without_explicit_triage"],
        },
        "operator_requirements": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "evidence": {
            "type": "array",
            "items": FLAKY_TEST_TRIAGE_EVIDENCE_SCHEMA,
            "minItems": 1,
        },
    },
    "required": [
        "check_id",
        "command",
        "reason",
        "run_count",
        "pass_count",
        "fail_count",
        "outcome_sequence",
        "disposition",
        "recommended_next_action",
        "monitor_verdict_policy",
        "operator_requirements",
        "evidence",
    ],
    "additionalProperties": False,
}


FLAKY_TEST_TRIAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/flaky-test-triage.json",
    "title": "MAP Flaky Test Triage",
    "description": "Repeated check evidence stored in .map/<branch>/flaky_test_triage.json",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
        "triages": {
            "type": "array",
            "items": FLAKY_TEST_TRIAGE_ENTRY_SCHEMA,
            "minItems": 1,
        },
    },
    "required": ["schema_version", "branch", "updated_at", "triages"],
    "additionalProperties": False,
}


TEST_HANDOFF_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/test-handoff.json",
    "title": "MAP Test Handoff",
    "description": "Persisted TDD handoff stored in .map/<branch>/test_handoff_<subtask>.json",
    "type": "object",
    "properties": {
        "subtask_id": {"type": "string"},
        "status": {"type": "string", "enum": ["contract_ready"]},
        "contract_path": {"type": "string"},
        "failing_test_command": {"type": ["string", "null"]},
        "test_files": {
            "type": "array",
            "items": {"type": "string"},
        },
        "contract_summary": {"type": "string"},
        "notes": {"type": "string"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
    "required": [
        "subtask_id",
        "status",
        "contract_path",
        "failing_test_command",
        "test_files",
        "contract_summary",
        "notes",
        "updated_at",
    ],
    "additionalProperties": False,
}


_RUN_HEALTH_ARTIFACT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "path": {"type": "string"},
        "present": {"type": "boolean"},
        "size_bytes": {"type": "integer", "minimum": 0},
    },
    "required": ["kind", "path", "present", "size_bytes"],
    "additionalProperties": False,
}

_RUN_HEALTH_ARTIFACT_KEYS = [
    "step_state",
    "artifact_manifest",
    "verification_summary",
    "qa",
    "pr_draft",
    "review_bundle",
    "learning_handoff",
    "task_plan",
    "blueprint",
    "active_issues",
    "known_issues",
]


_RUN_HEALTH_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "artifact_count": {"type": "integer", "minimum": 0},
        "valid_artifact_count": {"type": "integer", "minimum": 0},
        "invalid_artifact_count": {"type": "integer", "minimum": 0},
        "low_confidence_artifact_count": {"type": "integer", "minimum": 0},
        "location_count": {"type": "integer", "minimum": 0},
        "research_tokens": {"type": "integer", "minimum": 0},
        "research_est_cost_usd": {"type": "number", "minimum": 0},
        "actor_monitor_tokens": {"type": "integer", "minimum": 0},
        "actor_monitor_est_cost_usd": {"type": "number", "minimum": 0},
        "research_token_share": {"type": "number", "minimum": 0},
        "by_subtask": {"type": "object"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "schema_version",
        "artifact_count",
        "valid_artifact_count",
        "invalid_artifact_count",
        "low_confidence_artifact_count",
        "location_count",
        "research_tokens",
        "research_est_cost_usd",
        "actor_monitor_tokens",
        "actor_monitor_est_cost_usd",
        "research_token_share",
        "by_subtask",
        "warnings",
    ],
    "additionalProperties": False,
}


RUN_HEALTH_REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/run-health-report.json",
    "title": "MAP Run Health Report",
    "description": "Branch-scoped workflow observability report stored in .map/<branch>/run_health_report.json",
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "workflow": {"type": "string"},
        "branch": {"type": "string"},
        "minimality": {"type": "string", "enum": ["off", "lite", "full", "ultra"]},
        "terminal_status": {
            "type": "string",
            "enum": ["pending", "complete", "blocked", "won't_do", "superseded"],
        },
        "current_step_id": {"type": ["string", "null"]},
        "current_step_phase": {"type": ["string", "null"]},
        "current_subtask_id": {"type": ["string", "null"]},
        "completed_step_count": {"type": "integer", "minimum": 0},
        "pending_step_count": {"type": "integer", "minimum": 0},
        "artifacts": {
            "type": "object",
            "properties": {
                key: _RUN_HEALTH_ARTIFACT_ENTRY_SCHEMA
                for key in _RUN_HEALTH_ARTIFACT_KEYS
            },
            "required": _RUN_HEALTH_ARTIFACT_KEYS,
            "additionalProperties": _RUN_HEALTH_ARTIFACT_ENTRY_SCHEMA,
        },
        "research": _RUN_HEALTH_RESEARCH_SCHEMA,
        "resiliency_signals": {
            "type": "object",
            "properties": {
                "hook_injection": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": True,
                },
                "hook_injection_counts": {"type": "object"},
                "retry_count": {"type": "integer", "minimum": 0},
                "max_retries": {"type": "integer", "minimum": 0},
                "subtask_retry_counts": {"type": "object"},
                "max_subtask_retry_count": {"type": "integer", "minimum": 0},
                "clean_retry_count": {"type": "integer", "minimum": 0},
                "contaminated_retry_count": {"type": "integer", "minimum": 0},
                "retry_isolation_status": {"type": "object"},
                "guard_rework_counts": {"type": "object"},
                "predictor_called": {"type": "boolean"},
                "predictor_skipped": {"type": "boolean"},
                "final_verifier_executed": {"type": "boolean"},
            },
            "required": [
                "hook_injection",
                "hook_injection_counts",
                "retry_count",
                "max_retries",
                "subtask_retry_counts",
                "max_subtask_retry_count",
                "guard_rework_counts",
                "predictor_called",
                "predictor_skipped",
                "final_verifier_executed",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "schema_version",
        "generated_at",
        "workflow",
        "branch",
        "terminal_status",
        "completed_step_count",
        "pending_step_count",
        "artifacts",
        "resiliency_signals",
    ],
    "additionalProperties": False,
}

# Sub-schema reused for each fixed-name artifact entry in REVIEW_BUNDLE_SCHEMA.
_ARTIFACT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "present": {"type": "boolean"},
        "path": {"type": ["string", "null"]},
        "sanitized_text": {"type": ["string", "null"]},
        "truncated": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
        "kind": {"type": "string"},
        "index": {"type": ["integer", "null"]},
    },
    "required": ["present", "path", "sanitized_text"],
}

# Sub-schema for each entry in the test_handoffs / test_contracts arrays.
_MULTI_ARTIFACT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "sanitized_text": {"type": ["string", "null"]},
        "truncated": {"type": "boolean"},
    },
    "required": ["path", "sanitized_text"],
}

_PRIOR_STAGE_CONSUMPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready", "blocked", "error"]},
        "valid": {"type": "boolean"},
        "stage": {"type": "string"},
        "branch": {"type": "string"},
        "required_artifacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "kind": {"type": "string"},
                    "path": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "required": {"type": "boolean"},
                    "present": {"type": "boolean"},
                    "consumed": {"type": "boolean"},
                    "count": {"type": "integer", "minimum": 0},
                    "reason": {"type": "string"},
                },
                "required": [
                    "key",
                    "label",
                    "kind",
                    "path",
                    "required",
                    "present",
                    "consumed",
                    "count",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
        "summary": {
            "type": "object",
            "properties": {
                "required": {"type": "integer", "minimum": 0},
                "consumed": {"type": "integer", "minimum": 0},
                "missing": {"type": "integer", "minimum": 0},
            },
            "required": ["required", "consumed", "missing"],
            "additionalProperties": False,
        },
        "errors": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "valid",
        "stage",
        "branch",
        "required_artifacts",
        "summary",
        "errors",
    ],
    "additionalProperties": False,
}

REVIEW_BUNDLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/review-bundle.json",
    "title": "MAP Review Bundle",
    "description": (
        "Durable reviewer-facing bundle written to .map/<branch>/review-bundle.json. "
        "Collects all branch-scoped artifacts, sanitized text, and code-state metadata "
        "so /map-review can run from a fresh context without implementer session memory."
    ),
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "error"]},
        "branch": {"type": "string"},
        "bundle_path_json": {"type": "string"},
        "bundle_path_md": {"type": "string"},
        "generated_at": {"type": "string"},
        "artifacts": {
            "type": "object",
            "properties": {
                "spec": _ARTIFACT_ENTRY_SCHEMA,
                "task_plan": _ARTIFACT_ENTRY_SCHEMA,
                "blueprint": _ARTIFACT_ENTRY_SCHEMA,
                "verification_summary": _ARTIFACT_ENTRY_SCHEMA,
                "qa": _ARTIFACT_ENTRY_SCHEMA,
                "pr_draft": _ARTIFACT_ENTRY_SCHEMA,
                "active_issues": _ARTIFACT_ENTRY_SCHEMA,
                "artifact_manifest": _ARTIFACT_ENTRY_SCHEMA,
                "run_health_report": _ARTIFACT_ENTRY_SCHEMA,
                "latest_plan_review": _ARTIFACT_ENTRY_SCHEMA,
                "latest_code_review": _ARTIFACT_ENTRY_SCHEMA,
                "test_handoffs": {
                    "type": "array",
                    "items": _MULTI_ARTIFACT_ENTRY_SCHEMA,
                },
                "test_contracts": {
                    "type": "array",
                    "items": _MULTI_ARTIFACT_ENTRY_SCHEMA,
                },
            },
            "required": [
                "spec",
                "task_plan",
                "blueprint",
                "verification_summary",
                "qa",
                "pr_draft",
                "active_issues",
                "artifact_manifest",
                "latest_plan_review",
                "latest_code_review",
                "test_handoffs",
                "test_contracts",
            ],
        },
        "code_state": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "git_ref": {"type": "string"},
                "files_changed": {"type": "array", "items": {"type": "string"}},
                "diff_stat": {"type": "string"},
                "branch": {"type": "string"},
                "reason": {"type": "string"},
                "diff_truncated": {"type": "boolean"},
            },
            "required": ["status"],
        },
        "review_handoff": {
            "type": "object",
            "properties": {
                "plan_review": {"type": ["string", "null"]},
                "code_review": {"type": ["string", "null"]},
                "verification_summary": {"type": ["string", "null"]},
                "qa": {"type": ["string", "null"]},
                "pr_draft": {"type": ["string", "null"]},
                "active_issues": {"type": ["string", "null"]},
            },
            "required": [
                "plan_review",
                "code_review",
                "verification_summary",
                "qa",
                "pr_draft",
                "active_issues",
            ],
        },
        "pr_handoff": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "validation": {"type": "string"},
                "risks_follow_up": {"type": "string"},
            },
            "required": ["summary", "validation", "risks_follow_up"],
        },
        "acceptance_coverage": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "branch": {"type": "string"},
                "reason": {"type": "string"},
                "blueprint_path": {"type": "string"},
                "evidence_sources": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "owner": {"type": ["string", "null"]},
                            "validation_criteria_cited": {"type": "boolean"},
                            "evidence_artifacts": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "status": {
                                "type": "string",
                                "enum": ["covered", "missing_evidence"],
                            },
                        },
                        "required": [
                            "id",
                            "owner",
                            "validation_criteria_cited",
                            "evidence_artifacts",
                            "status",
                        ],
                        "additionalProperties": False,
                    },
                },
                "summary": {
                    "type": "object",
                    "properties": {
                        "total": {"type": "integer", "minimum": 0},
                        "covered": {"type": "integer", "minimum": 0},
                        "missing": {"type": "integer", "minimum": 0},
                    },
                    "required": ["total", "covered", "missing"],
                    "additionalProperties": False,
                },
            },
            "required": ["status", "branch", "requirements", "summary"],
            "additionalProperties": True,
        },
        "prior_stage_consumption": _PRIOR_STAGE_CONSUMPTION_SCHEMA,
        "manifest_status": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "path": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["status"],
        },
        "schema_validation_error": {
            "type": "array",
            "items": {"type": "string"},
        },
        "ordering": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "default",
                        "reverse-sections",
                        "shuffle-sections",
                        "compare-orderings",
                    ],
                },
                "seed": {"type": ["integer", "null"]},
                "runs": {"type": "array"},
                "drift_detected": {"type": "boolean"},
                "drift_summary": {"type": ["string", "null"]},
                "final_verdict": {"type": ["string", "null"]},
                "compare_status": {"type": ["string", "null"]},
            },
            "required": [
                "mode",
                "seed",
                "runs",
                "drift_detected",
                "drift_summary",
                "final_verdict",
                "compare_status",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "status",
        "branch",
        "bundle_path_json",
        "bundle_path_md",
        "generated_at",
        "artifacts",
        "code_state",
        "review_handoff",
        "pr_handoff",
        "acceptance_coverage",
        "prior_stage_consumption",
    ],
    "additionalProperties": False,
}


# ============================================================================
# Trajectory-level outcome eval (AgentLens-style, issue #351)
# ============================================================================
# Two schemas:
# - TRAJECTORY_BUNDLE_SCHEMA  : normalized snapshot of ONE completed run's
#   trajectory evidence (git diff + MAP artifacts + verification + response).
# - TRAJECTORY_EVAL_SCHEMA    : one scored eval row (components + composite),
#   one object per JSONL line written by the trajectory runner.
# Both follow the plain-dict JSON Schema pattern used by every *_SCHEMA above.

_EVIDENCE_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
        "ref": {"type": "string"},
        "detail": {"type": "string"},
    },
    "required": ["severity", "ref", "detail"],
    "additionalProperties": False,
}

_COMPONENT_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "enum": [
                "formal",
                "end_result",
                "tool_use",
                "instruction_compliance",
                "pitfalls",
                "reporting_trust",
            ],
        },
        "kind": {"type": "string", "enum": ["deterministic", "judge"]},
        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "evidence": {
            "type": "array",
            "items": _EVIDENCE_LINE_SCHEMA,
        },
    },
    "required": ["name", "kind", "score", "evidence"],
    "additionalProperties": False,
}

TRAJECTORY_BUNDLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/trajectory-bundle.json",
    "title": "MAP Trajectory Bundle",
    "description": (
        "Normalized snapshot of one completed MAP run's trajectory evidence, "
        "captured by the trajectory outcome evaluator. Bundles git diff, MAP "
        ".map/<branch>/ artifacts, verification output, and final response so a "
        "later reviewer or side-by-side comparator can inspect the run without "
        "the throwaway cwd. See issue #351."
    ),
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "fixture": {"type": "string"},
        "scenario": {"type": "string"},
        "branch": {"type": "string"},
        "collected_at": {"type": "string"},
        "final_response": {"type": "string"},
        "git": {
            "type": "object",
            "properties": {
                "modified_all": {"type": "array", "items": {"type": "string"}},
                "source_changes": {"type": "array", "items": {"type": "string"}},
                "out_of_scope": {"type": "array", "items": {"type": "string"}},
                "trap_touched": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "modified_all",
                "source_changes",
                "out_of_scope",
                "trap_touched",
            ],
            "additionalProperties": False,
        },
        "verification": {
            "type": "object",
            "properties": {
                "task_pass": {"type": "boolean"},
                "test_returncode": {"type": "integer"},
                "test_tail": {"type": "string"},
            },
            "required": ["task_pass", "test_returncode", "test_tail"],
            "additionalProperties": False,
        },
        "map_artifacts": {
            "type": "object",
            "description": (
                "Best-effort loaded slices of .map/<branch>/ artifacts the "
                "evaluator consumes (never creates). Missing files yield {}."
            ),
            "additionalProperties": True,
        },
        "resiliency_signals": {
            "type": "object",
            "description": (
                "Distilled retry/quarantine/guard signals used by the tool_use "
                "metric. Derived from run_health_report where available."
            ),
            "additionalProperties": True,
        },
        "run_meta": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "returncode": {"type": ["integer", "null"]},
                "duration_s": {"type": ["number", "null"]},
                "error": {"type": ["string", "null"]},
            },
            "additionalProperties": True,
        },
    },
    "required": [
        "schema_version",
        "fixture",
        "scenario",
        "branch",
        "collected_at",
        "final_response",
        "git",
        "verification",
        "map_artifacts",
        "run_meta",
    ],
    "additionalProperties": False,
}

TRAJECTORY_EVAL_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/trajectory-eval.json",
    "title": "MAP Trajectory Eval Record",
    "description": (
        "One scored trajectory outcome-eval row. Appended as a single JSON "
        "object per line to .map/eval-runs/trajectory/<skill>/<ts>.jsonl by "
        "the trajectory runner. Composite is a normalized 0..1 quality index "
        "across component metrics; hard_pass marks formal+end_result success "
        "plus a passing composite. See issue #351."
    ),
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "run_id": {"type": "string"},
        "fixture": {"type": "string"},
        "run": {"type": "integer", "minimum": 0},
        "ts": {"type": "string"},
        "components": {
            "type": "array",
            "items": _COMPONENT_SCORE_SCHEMA,
            "minItems": 1,
        },
        "composite": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "hard_pass": {"type": "boolean"},
        "expected_outcome": {
            "type": "string",
            "enum": ["complete", "blocked"],
        },
        "judge_meta": {
            "type": "object",
            "properties": {
                "model": {"type": ["string", "null"]},
                "prompt_version": {"type": "string"},
                "ordering": {"type": "string"},
                "skipped": {"type": "boolean"},
                "caveats": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["prompt_version", "ordering", "skipped"],
            "additionalProperties": False,
        },
        "bundle_summary": {
            "type": "object",
            "description": (
                "Compact projection of the trajectory bundle (git scope + "
                "verification result). The full bundle is persisted alongside "
                "the JSONL; this lets a reader scan a run without loading it."
            ),
            "additionalProperties": True,
        },
        "error": {"type": ["string", "null"]},
    },
    "required": [
        "schema_version",
        "run_id",
        "fixture",
        "run",
        "ts",
        "components",
        "composite",
        "hard_pass",
        "expected_outcome",
        "judge_meta",
        "error",
    ],
    "additionalProperties": False,
}

CONTEXT_USEFULNESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/context-usefulness.json",
    "title": "MAP Context Usefulness Report",
    "description": (
        "Records which recalled/injected context items were useful in a completed "
        "workflow run, enabling future recall ranking to be boosted or demoted based "
        "on prior usefulness evidence."
    ),
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "generated_at": {"type": "string"},
        "branch": {"type": "string"},
        "workflow": {"type": "string"},
        "terminal_status": {"type": "string"},
        "items": {
            "type": "array",
            "description": "Injected/recalled context items and their observed outcome labels.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "memory_digest",
                            "learned_rule",
                            "research_artifact",
                            "learning_handoff",
                            "review_bundle",
                            "other",
                        ],
                        "description": "Category of context item.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Path, slug, or identifier of the context item.",
                    },
                    "outcome_label": {
                        "type": "string",
                        "enum": ["helpful", "used", "ignored", "stale", "over_budget", "unknown"],
                        "description": "Observed usefulness outcome for this item.",
                    },
                    "signals": {
                        "type": "object",
                        "description": "Deterministic signals that informed the outcome label.",
                        "additionalProperties": True,
                    },
                },
                "required": ["kind", "source", "outcome_label"],
                "additionalProperties": True,
            },
        },
        "summary": {
            "type": "object",
            "description": "Aggregate counts of each outcome label.",
            "properties": {
                "total": {"type": "integer"},
                "helpful": {"type": "integer"},
                "used": {"type": "integer"},
                "ignored": {"type": "integer"},
                "stale": {"type": "integer"},
                "over_budget": {"type": "integer"},
                "unknown": {"type": "integer"},
            },
            "additionalProperties": True,
        },
    },
    "required": ["schema_version", "branch", "workflow", "items", "summary"],
    "additionalProperties": True,
}


REVIEW_VERDICT_LEDGER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://mapframework.dev/schemas/review-verdict-ledger.json",
    "title": "MAP Review Verdict Ledger",
    "description": (
        "Durable normalized finding registry and computed verdict for a /map-review run. "
        "Written before write_stage_gate so the reasoning surface is reproducible from "
        "a closed decision table, not assigned ad hoc. See issue #406."
    ),
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "generated_at": {"type": "string"},
        "branch": {"type": "string"},
        "criteria_version": {"type": "string"},
        "input_classification": {
            "type": "object",
            "properties": {
                "review_mode": {
                    "type": "string",
                    "enum": ["normal", "adversarial", "cross_ai", "compare_orderings", "unknown"],
                },
                "destination": {
                    "type": "string",
                    "enum": ["pre_commit", "pr_review", "ci", "unknown"],
                },
                "evidence_mode": {
                    "type": "string",
                    "enum": ["structural", "self_executed", "independent_run", "mixed", "unknown"],
                },
                "executor_class": {"type": "string"},
            },
            "required": ["review_mode"],
            "additionalProperties": True,
        },
        "findings_registry": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "source_agent": {
                        "type": "string",
                        "enum": [
                            "monitor", "predictor", "evaluator",
                            "adversarial", "ordering", "operator",
                        ],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "correctness", "security", "tests", "performance",
                            "maintainability", "workflow", "unknown",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "important", "minor", "needs_investigation"],
                    },
                    "claim": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "line_range": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "tombstoned", "downgraded"],
                    },
                    "transition_reason": {
                        "type": ["string", "null"],
                        "enum": [
                            "new_evidence", "quote_absent", "wrong_category",
                            "different_version", "pre_existing_backlog",
                            "human_escalation", "pressure_without_new_fact",
                            "input_integrity", "not_applicable", None,
                        ],
                    },
                    "transition_evidence": {"type": ["string", "null"]},
                    "was_present_before_pr": {"type": ["boolean", "null"]},
                    "downgraded_from": {
                        "type": "string",
                        "enum": ["critical", "important", "minor", "needs_investigation"],
                        "description": (
                            "Severity the finding carried before it was downgraded. "
                            "Present only on downgraded rows."
                        ),
                    },
                },
                "required": ["id", "source_agent", "severity", "claim", "status"],
                "additionalProperties": True,
            },
        },
        "not_verified": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concerns that could not be verified against source evidence.",
        },
        "evaluator_scores": {
            "type": ["object", "null"],
            "description": "Raw Evaluator scores — advisory signal, cannot override active findings.",
            "additionalProperties": True,
        },
        "verdict_table": {"type": "string"},
        "computed_verdict": {
            "type": "string",
            "enum": ["PROCEED", "REVISE", "BLOCK"],
        },
        "verdict_basis": {
            "type": "string",
            "description": "Human-readable explanation of why the decision table chose this verdict.",
        },
        "journal": {
            "type": "object",
            "properties": {
                "previous_verdict": {
                    "type": ["string", "null"],
                    "enum": ["PROCEED", "REVISE", "BLOCK", None],
                },
                "current_verdict": {
                    "type": "string",
                    "enum": ["PROCEED", "REVISE", "BLOCK"],
                },
                "matches_previous": {"type": ["boolean", "null"]},
                "repeated_verbatim": {
                    "type": "boolean",
                    "description": (
                        "True when an objection carried no new fact, so the prior "
                        "verdict stands rather than being re-argued."
                    ),
                },
                "basis": {"type": "string"},
            },
            "required": ["current_verdict"],
            "additionalProperties": True,
        },
        "escalation_required": {
            "type": "boolean",
            "description": (
                "True when a human must decide. PROCEED is unavailable while this is set."
            ),
        },
        "escalation_reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
        # active_count counts what the decision table consumed: active AND
        # downgraded rows. tombstoned_count counts only rows that left the table.
        "active_count": {"type": "integer", "minimum": 0},
        "downgraded_count": {"type": "integer", "minimum": 0},
        "tombstoned_count": {"type": "integer", "minimum": 0},
    },
    "required": [
        "schema_version",
        "branch",
        "generated_at",
        "findings_registry",
        "not_verified",
        "computed_verdict",
        "verdict_table",
        "journal",
    ],
    "additionalProperties": True,
}

PRD_REVIEW_SCHEMA: dict[str, Any] = {
    "$id": "prd-review.json",
    "type": "object",
    "description": "PRD/requirements-quality review artifact written by write_prd_review.",
    "properties": {
        "schema_version": {"type": "string"},
        "branch": {"type": "string"},
        "generated_at": {"type": "string", "description": "ISO-8601 UTC timestamp"},
        "prd_source": {"type": "string", "description": "Path or label of the reviewed PRD"},
        "verdict": {
            "type": "string",
            "enum": [
                "ready_for_plan",
                "needs_prd_revision",
                "needs_user_decision",
                "route_to_wayfind",
            ],
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "major", "minor", "info"],
                    },
                    "description": {"type": "string"},
                    "suggested_revision": {"type": "string"},
                },
                "required": ["dimension", "severity", "description"],
                "additionalProperties": False,
            },
        },
        "blocking_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["question", "category"],
                "additionalProperties": False,
            },
        },
        "suggested_revisions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "route_recommendation": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": [
        "schema_version",
        "branch",
        "generated_at",
        "verdict",
        "findings",
        "blocking_questions",
        "suggested_revisions",
        "summary",
    ],
    "additionalProperties": True,
}
