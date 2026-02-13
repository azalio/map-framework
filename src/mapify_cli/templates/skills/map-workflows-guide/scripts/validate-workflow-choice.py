#!/usr/bin/env python3
"""Validate that a workflow choice matches task characteristics.

Usage:
    python validate-workflow-choice.py --workflow <name> --risk <level> --size <size> --type <type>

Example:
    python validate-workflow-choice.py --workflow map-efficient --risk medium --size medium --type feature
    python validate-workflow-choice.py --workflow map-fast --risk high --size large --type security

Exit codes:
    0 - Workflow choice is appropriate
    1 - Workflow choice is suboptimal (warning)
    2 - Workflow choice is inappropriate (error)
"""

import argparse
import json
import sys

# Workflow appropriateness rules
WORKFLOW_RULES = {
    "map-fast": {
        "allowed_risk": ["low"],
        "allowed_size": ["small"],
        "allowed_types": ["fix", "tweak", "maintenance", "docs"],
        "forbidden_types": ["security", "auth", "payment", "database-schema"],
    },
    "map-efficient": {
        "allowed_risk": ["low", "medium", "high"],
        "allowed_size": ["small", "medium", "large"],
        "allowed_types": [
            "feature",
            "enhancement",
            "fix",
            "tweak",
            "maintenance",
            "docs",
            "security",
            "auth",
            "payment",
            "database-schema",
            "infrastructure",
            "refactor",
            "restructure",
            "rename",
            "extract",
            "cleanup",
        ],
        "forbidden_types": [],
    },
    "map-debug": {
        "allowed_risk": ["low", "medium", "high"],
        "allowed_size": ["small", "medium", "large"],
        "allowed_types": ["bug", "fix", "test-failure", "error", "regression"],
        "forbidden_types": ["feature", "refactor"],
    },
}

# Recommendations for risky combinations
RISK_OVERRIDES = {
    ("map-fast", "high"): "map-efficient",
    ("map-fast", "medium"): "map-efficient",
}


def validate(workflow: str, risk: str, size: str, task_type: str) -> dict:
    """Validate workflow choice against task characteristics.

    Returns dict with:
        valid: bool
        level: "ok" | "warning" | "error"
        message: str
        recommendation: str | None
    """
    if workflow not in WORKFLOW_RULES:
        return {
            "valid": False,
            "level": "error",
            "message": f"Unknown workflow: {workflow}",
            "recommendation": "map-efficient",
        }

    rules = WORKFLOW_RULES[workflow]
    issues = []

    # Check risk level
    if risk not in rules["allowed_risk"]:
        issues.append(f"Risk level '{risk}' is too high for {workflow}")

    # Check size
    if size not in rules["allowed_size"]:
        issues.append(f"Size '{size}' is not suitable for {workflow}")

    # Check forbidden types
    if task_type in rules["forbidden_types"]:
        issues.append(f"Task type '{task_type}' is forbidden for {workflow}")

    # Check risk overrides
    override_key = (workflow, risk)
    recommendation = RISK_OVERRIDES.get(override_key)

    if issues:
        level = "error" if any("forbidden" in i for i in issues) else "warning"
        return {
            "valid": False,
            "level": level,
            "message": "; ".join(issues),
            "recommendation": recommendation or "map-efficient",
        }

    return {
        "valid": True,
        "level": "ok",
        "message": f"Workflow '{workflow}' is appropriate for {risk}-risk {size} {task_type} task",
        "recommendation": None,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate MAP workflow choice")
    parser.add_argument(
        "--workflow",
        required=True,
        choices=list(WORKFLOW_RULES.keys()),
        help="Chosen workflow",
    )
    parser.add_argument(
        "--risk",
        required=True,
        choices=["low", "medium", "high"],
        help="Task risk level",
    )
    parser.add_argument(
        "--size",
        required=True,
        choices=["small", "medium", "large"],
        help="Task size",
    )
    parser.add_argument("--type", required=True, dest="task_type", help="Task type")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    result = validate(args.workflow, args.risk, args.size, args.task_type)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = {"ok": "OK", "warning": "WARNING", "error": "ERROR"}[result["level"]]
        print(f"[{status}] {result['message']}")
        if result["recommendation"]:
            print(f"  Recommendation: Use {result['recommendation']} instead")

    exit_codes = {"ok": 0, "warning": 1, "error": 2}
    sys.exit(exit_codes[result["level"]])


if __name__ == "__main__":
    main()
