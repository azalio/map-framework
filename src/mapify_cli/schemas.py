"""
Schema definitions for MAP Framework.

Contains JSON Schema definitions for .map/ state artifacts (v3.0+).

These schemas are embedded in code to ensure they're available
in packaged installations (uv tool install, pip install).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


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
) -> tuple[Optional[dict[str, Any]], list[str]]:
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
                        "items": {"type": "string"},
                    },
                    "affected_files": {
                        "type": "array",
                        "description": "Files expected to be created or modified",
                        "items": {"type": "string"},
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "description": "Criteria that must be met for the subtask to be considered complete",
                        "items": {"type": "string"},
                    },
                    "risk": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Risk level of this subtask",
                    },
                },
                "required": ["id", "title", "dependencies", "affected_files"],
                "additionalProperties": True,
            },
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
    "required": ["subtasks"],
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
                    "pytest tests/test_template_sync.py -v",
                    "make sync-templates",
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
                "implementation": ARTIFACT_STAGE_SCHEMA,
                "review": ARTIFACT_STAGE_SCHEMA,
                "verification": ARTIFACT_STAGE_SCHEMA,
                "learn_handoff": ARTIFACT_STAGE_SCHEMA,
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
    ],
    "additionalProperties": False,
}
