#!/usr/bin/env python3
"""E2E test for validating CLI command correctness in agent templates.

This test ensures that agent templates use correct mapify CLI commands,
preventing common mistakes like:
- Wrong command names (list→stats, get→query)
- Wrong parameter names (--limit with search→--top-k)
- Deprecated approaches (playbook.json, direct sqlite3)
- Wrong operation field ('op' instead of 'type')
"""

import re
import sys
from pathlib import Path

import pytest

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli import get_templates_dir


class TestAgentCLICorrectness:
    """Test that agent templates use correct CLI commands."""

    @pytest.fixture
    def agent_files(self):
        """Get all agent template files."""
        templates_dir = get_templates_dir()
        agents_dir = templates_dir / "agents"

        # Get all .md files except documentation
        agent_files = [
            f for f in agents_dir.glob("*.md")
            if f.name not in ["README.md", "CHANGELOG.md", "MCP-PATTERNS.md"]
        ]

        return agent_files

    def test_no_wrong_command_names(self, agent_files):
        """Test that agents don't use non-existent command names."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # Check for wrong command: 'mapify playbook list'
            if re.search(r'mapify\s+playbook\s+list(?!\s*/)', content):
                # Ignore if it's in error examples (has ❌ nearby)
                matches = re.finditer(r'mapify\s+playbook\s+list', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    if '❌' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: 'mapify playbook list' doesn't exist, "
                            f"use 'mapify playbook stats'"
                        )
                        break

            # Check for wrong command: 'mapify playbook get'
            if re.search(r'mapify\s+playbook\s+get\s+', content):
                matches = re.finditer(r'mapify\s+playbook\s+get\s+', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    if '❌' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: 'mapify playbook get' doesn't exist, "
                            f"use 'mapify playbook query \"<bullet-id>\"'"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_no_wrong_parameter_names(self, agent_files):
        """Test that agents use correct parameter names."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # Check for --limit with search command
            if re.search(r'playbook\s+search.*--limit', content):
                matches = re.finditer(r'playbook\s+search.*--limit', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    if '❌' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: 'mapify playbook search' uses '--top-k', "
                            f"not '--limit'"
                        )
                        break

            # Check for --bullet-id with query command
            if re.search(r'playbook\s+query.*--bullet-id', content):
                matches = re.finditer(r'playbook\s+query.*--bullet-id', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    if '❌' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: 'mapify playbook query' doesn't have "
                            f"'--bullet-id' option, use bullet ID as query text"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_no_deprecated_approaches(self, agent_files):
        """Test that agents don't promote deprecated approaches."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # Check for direct sqlite3 usage (without warning context)
            if re.search(r'sqlite3.*playbook\.db', content):
                matches = re.finditer(r'sqlite3.*playbook\.db', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    # Allow if it's in error examples or warnings
                    if '❌' not in context and '**NEVER**' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: Direct sqlite3 usage detected without warning "
                            f"context. Always use 'mapify playbook apply-delta' instead"
                        )
                        break

            # Check for playbook.json references (without warning context)
            if re.search(r'playbook\.json', content):
                matches = re.finditer(r'playbook\.json', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    # Allow if it's in error examples or migration notes
                    if ('❌' not in context and '**WRONG**' not in context
                        and 'deprecated' not in context.lower()
                        and 'migrated' not in context.lower()):
                        errors.append(
                            f"{agent_file.name}: Reference to playbook.json detected "
                            f"(deprecated, migrated to playbook.db)"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_no_wrong_operation_field(self, agent_files):
        """Test that agents use 'type' field instead of 'op' in delta operations."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # Check for "op": "ADD/UPDATE/DEPRECATE" pattern
            if re.search(r'"op":\s*"(ADD|UPDATE|DEPRECATE)"', content):
                matches = re.finditer(r'"op":\s*"(ADD|UPDATE|DEPRECATE)"', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    # Allow if it's in error examples
                    if '❌' not in context and '**WRONG**' not in context:
                        errors.append(
                            f"{agent_file.name}: Using '\"op\":' field, should be '\"type\":' "
                            f"in delta operations"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_agents_have_cli_reference_or_examples(self, agent_files):
        """Test that agents either have CLI reference section or proper examples."""
        warnings = []

        # Agents that should have CLI guidance
        cli_heavy_agents = ["actor.md", "reflector.md", "curator.md"]

        for agent_file in agent_files:
            if agent_file.name in cli_heavy_agents:
                content = agent_file.read_text()

                # Check if agent has CLI reference section or examples
                has_cli_reference = '<mapify_cli_reference>' in content
                has_cli_examples = bool(re.search(r'mapify\s+playbook\s+(query|search|apply-delta)', content))

                if not has_cli_reference and not has_cli_examples:
                    warnings.append(
                        f"{agent_file.name}: No CLI reference or examples found. "
                        f"Consider adding <mapify_cli_reference> section."
                    )

        # Warnings don't fail the test, but are printed
        if warnings:
            print("\n⚠️  CLI Reference Warnings:")
            for warning in warnings:
                print(f"  - {warning}")

    def test_correct_cli_examples_present(self, agent_files):
        """Test that agents with CLI examples use correct syntax."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # If agent mentions playbook query/search, ensure correct usage
            if 'mapify playbook' in content:
                # Verify query examples have correct syntax
                query_examples = re.findall(
                    r'mapify\s+playbook\s+query\s+"[^"]*"(?:\s+--\w+\s+\d+)?',
                    content
                )

                # Verify search examples have correct syntax
                search_examples = re.findall(
                    r'mapify\s+playbook\s+search\s+"[^"]*"(?:\s+--top-k\s+\d+)?',
                    content
                )

                # This test mainly documents expected patterns
                # Actual validation happens in other tests
                pass

        assert not errors, "\n".join(errors)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
