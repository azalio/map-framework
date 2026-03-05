"""
Schema definitions for MAP Framework.

Contains JSON Schema definitions for .map/ state artifacts (v3.0+).

These schemas are embedded in code to ensure they're available
in packaged installations (uv tool install, pip install).
"""

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
