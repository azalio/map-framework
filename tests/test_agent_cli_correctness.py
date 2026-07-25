"""E2E test for validating CLI command correctness in agent templates.

This test ensures that agent templates use correct mapify CLI commands,
preventing common mistakes like:
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
            f
            for f in agents_dir.glob("*.md")
            if f.name not in ["README.md", "CHANGELOG.md", "MCP-PATTERNS.md"]
        ]

        return agent_files

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
                    if "❌" not in context and "**WRONG**" not in context:
                        errors.append(
                            f"{agent_file.name}: Using '\"op\":' field, should be '\"type\":' "
                            f"in delta operations"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_agents_have_cli_reference(self, agent_files):
        """Test that agents have CLI reference section."""
        warnings = []

        # Agents that should have CLI guidance
        cli_heavy_agents = ["actor.md", "reflector.md"]

        for agent_file in agent_files:
            if agent_file.name in cli_heavy_agents:
                content = agent_file.read_text()

                # Check if agent has CLI reference section
                has_cli_reference = "<mapify_cli_reference>" in content

                if not has_cli_reference:
                    warnings.append(
                        f"{agent_file.name}: No CLI reference found. "
                        f"Consider adding <mapify_cli_reference> section."
                    )

        # Warnings don't fail the test, but are printed
        if warnings:
            print("\nCLI Reference Warnings:")
            for warning in warnings:
                print(f"  - {warning}")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
