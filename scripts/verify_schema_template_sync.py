#!/usr/bin/env python3
"""
Verify JSON Schema fields match Handlebars template variables.

This script detects bidirectional schema-template drift before runtime:
1. Schema fields that templates don't consume (dead fields)
2. Template variables that schemas don't define (runtime failures)

Usage:
    python scripts/verify_schema_template_sync.py --all
    python scripts/verify_schema_template_sync.py actor monitor
    python scripts/verify_schema_template_sync.py --agent=actor
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def extract_schema_fields(schema_path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Extract required and optional fields from JSON Schema.

    Returns:
        Tuple of (required_fields, optional_fields)
    """
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    schema = json.loads(schema_path.read_text())

    # Get all properties
    properties = schema.get("properties", {})
    all_fields = set(properties.keys())

    # Get required fields
    required = set(schema.get("required", []))

    # Optional = all fields - required
    optional = all_fields - required

    return required, optional


def extract_template_vars(template_path: Path) -> Set[str]:
    """
    Extract {{variables}} from Handlebars template.

    Matches:
    - {{variable}}
    - {{#if variable}}
    - {{#unless variable}}
    - {{#each variable}}

    Does NOT match:
    - {{else}} (control flow)
    - {{/if}}, {{/unless}}, {{/each}} (closing tags)
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    content = template_path.read_text()

    # Match {{variable}} and {{#if variable}} but not {{else}}, {{/if}}
    pattern = r'\{\{(?:#(?:if|unless|each)\s+)?(\w+)'
    matches = re.findall(pattern, content)

    # Filter out control flow keywords
    control_flow = {'else', 'if', 'unless', 'each'}
    return {m for m in matches if m not in control_flow}


def verify_sync(
    agent_name: str,
    schema_dir: Path,
    template_dir: Path
) -> Dict[str, List[str]]:
    """
    Check bidirectional sync for one agent.

    Returns:
        Dict with 'missing_in_template', 'missing_in_schema', 'unused_optional'
    """
    # Handle different naming conventions
    schema_path = schema_dir / f"{agent_name}_input.json"
    if not schema_path.exists():
        schema_path = schema_dir / f"{agent_name}.json"

    template_path = template_dir / f"{agent_name}.md"

    try:
        required_fields, optional_fields = extract_schema_fields(schema_path)
        template_vars = extract_template_vars(template_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    # Detect issues
    all_schema_fields = required_fields | optional_fields

    # Critical: Required fields not used in template
    missing_in_template = list(required_fields - template_vars)

    # Critical: Template uses variables not in schema
    missing_in_schema = list(template_vars - all_schema_fields)

    # Warning: Optional fields not used (not critical but indicates bloat)
    unused_optional = list(optional_fields - template_vars)

    return {
        "missing_in_template": missing_in_template,
        "missing_in_schema": missing_in_schema,
        "unused_optional": unused_optional,
        "required_fields": list(required_fields),
        "optional_fields": list(optional_fields),
        "template_vars": list(template_vars)
    }


def print_agent_status(agent_name: str, issues: Dict[str, List[str]]) -> bool:
    """
    Print verification status for one agent.

    Returns:
        True if no critical issues, False otherwise
    """
    if "error" in issues:
        print(f"{Colors.YELLOW}⚠️  {agent_name}: {issues['error']}{Colors.RESET}")
        return False

    has_critical = (
        len(issues["missing_in_template"]) > 0 or
        len(issues["missing_in_schema"]) > 0
    )

    if not has_critical and len(issues["unused_optional"]) == 0:
        print(f"{Colors.GREEN}✅ {agent_name}: Schema and template in sync{Colors.RESET}")
        return True

    # Print header
    if has_critical:
        print(f"{Colors.RED}❌ {agent_name}: Schema-template mismatch!{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}⚠️  {agent_name}: Minor issues found{Colors.RESET}")

    # Print critical issues
    if issues["missing_in_template"]:
        print(f"   {Colors.RED}CRITICAL:{Colors.RESET} Schema requires but template doesn't use:")
        for field in sorted(issues["missing_in_template"]):
            print(f"      - {field}")

    if issues["missing_in_schema"]:
        print(f"   {Colors.RED}CRITICAL:{Colors.RESET} Template uses but schema doesn't define:")
        for var in sorted(issues["missing_in_schema"]):
            print(f"      - {var}")

    # Print warnings
    if issues["unused_optional"]:
        print(f"   {Colors.YELLOW}WARNING:{Colors.RESET} Schema defines optional fields unused in template:")
        for field in sorted(issues["unused_optional"]):
            print(f"      - {field}")

    return not has_critical


def main():
    parser = argparse.ArgumentParser(
        description="Verify schema-template synchronization for MAP agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/verify_schema_template_sync.py --all
  python scripts/verify_schema_template_sync.py actor monitor predictor
  python scripts/verify_schema_template_sync.py --agent=actor --verbose
        """
    )

    parser.add_argument(
        "agents",
        nargs="*",
        help="Specific agents to verify (e.g., actor monitor)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all 8 agents"
    )
    parser.add_argument(
        "--agent",
        help="Verify single agent (alternative to positional argument)"
    )
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path("schemas"),
        help="Directory containing JSON schemas (default: schemas/)"
    )
    parser.add_argument(
        "--template-dir",
        type=Path,
        default=Path(".claude/agents"),
        help="Directory containing agent templates (default: .claude/agents/)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all fields and variables, not just mismatches"
    )

    args = parser.parse_args()

    # Determine which agents to verify
    all_agents = [
        "actor",
        "monitor",
        "predictor",
        "evaluator",
        "reflector",
        "curator",
        "task-decomposer",
        "documentation-reviewer"
    ]

    if args.all:
        agents_to_verify = all_agents
    elif args.agent:
        agents_to_verify = [args.agent]
    elif args.agents:
        agents_to_verify = args.agents
    else:
        print(f"{Colors.RED}Error: Specify --all, --agent=NAME, or provide agent names{Colors.RESET}")
        parser.print_help()
        sys.exit(1)

    # Verify each agent
    print(f"\n{Colors.BOLD}Checking schema-template synchronization...{Colors.RESET}\n")

    results = {}
    for agent in agents_to_verify:
        issues = verify_sync(agent, args.schema_dir, args.template_dir)
        results[agent] = issues

        print_agent_status(agent, issues)

        # Verbose output
        if args.verbose and "error" not in issues:
            print(f"   {Colors.BLUE}Schema required:{Colors.RESET} {', '.join(sorted(issues['required_fields'])) or 'none'}")
            print(f"   {Colors.BLUE}Schema optional:{Colors.RESET} {', '.join(sorted(issues['optional_fields'])) or 'none'}")
            print(f"   {Colors.BLUE}Template uses:{Colors.RESET} {', '.join(sorted(issues['template_vars'])) or 'none'}")

        print()  # Blank line between agents

    # Summary
    total = len(agents_to_verify)
    errors = sum(1 for r in results.values() if "error" in r)
    critical_issues = sum(
        1 for r in results.values()
        if "error" not in r and (
            len(r["missing_in_template"]) > 0 or
            len(r["missing_in_schema"]) > 0
        )
    )
    warnings_only = sum(
        1 for r in results.values()
        if "error" not in r and
        len(r["missing_in_template"]) == 0 and
        len(r["missing_in_schema"]) == 0 and
        len(r["unused_optional"]) > 0
    )
    success = total - errors - critical_issues - warnings_only

    print(f"{Colors.BOLD}Summary:{Colors.RESET}")
    print(f"  ✅ In sync: {success}/{total}")
    if warnings_only > 0:
        print(f"  ⚠️  Warnings only: {warnings_only}/{total}")
    if critical_issues > 0:
        print(f"  ❌ Critical issues: {critical_issues}/{total}")
    if errors > 0:
        print(f"  ⚠️  Errors (missing files): {errors}/{total}")

    # Exit code
    if critical_issues > 0 or errors > 0:
        print(f"\n{Colors.RED}❌ Verification FAILED - fix issues before implementation{Colors.RESET}")
        sys.exit(1)
    elif warnings_only > 0:
        print(f"\n{Colors.YELLOW}⚠️  Verification passed with warnings{Colors.RESET}")
        sys.exit(0)
    else:
        print(f"\n{Colors.GREEN}✅ All agents verified successfully{Colors.RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
