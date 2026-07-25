"""
Tests for YAML frontmatter validation in agent templates.

This test ensures that all agent template files have valid YAML frontmatter with:
- Proper YAML syntax that parses without errors
- Required 'name' field that is non-empty
- Unique 'name' values across all agents (no duplicates)

Frontmatter is the section between the first two '---' delimiters at the top of each .md file.

See docs/ARCHITECTURE.md for agent template structure requirements.
"""

import re
from pathlib import Path

import pytest
import yaml


class TestAgentFrontmatter:
    """Test that agent templates have valid YAML frontmatter."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def agent_directories(self, project_root):
        """Get both agent template directories to validate."""
        directories = []

        # .claude/agents/ (development source)
        claude_agents = project_root / ".claude" / "agents"
        if claude_agents.exists():
            directories.append(claude_agents)

        # src/mapify_cli/templates/agents/ (distribution target)
        template_agents = project_root / "src" / "mapify_cli" / "templates" / "agents"
        if template_agents.exists():
            directories.append(template_agents)

        return directories

    @pytest.fixture
    def all_agent_files(self, agent_directories):
        """Get all .md files from both agent directories."""
        agent_files = []
        for directory in agent_directories:
            agent_files.extend(directory.glob("*.md"))
        return agent_files

    def extract_frontmatter(self, file_path: Path) -> tuple[str | None, str | None]:
        """
        Extract YAML frontmatter from markdown file.

        Returns:
            Tuple of (frontmatter_content, error_message)
            - If successful: (yaml_string, None)
            - If failed: (None, error_message)
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
            return None, f"Failed to read file: {e}"

        # Match frontmatter: ^---\n(content)\n---
        # Using DOTALL to match across newlines
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)

        if not match:
            return (
                None,
                "No frontmatter found (expected '---' delimiters at start of file)",
            )

        return match.group(1), None

    def test_agent_frontmatter_valid(self, agent_directories):
        """
        Test that all agent templates have valid YAML frontmatter.

        Validates:
        1. Frontmatter exists and is parseable YAML
        2. 'name' field exists and is non-empty string
        3. 'name' values are unique within each directory

        Note: Checks each directory independently since .claude/agents/ and
        src/mapify_cli/templates/agents/ are synchronized mirrors.
        """
        if not agent_directories:
            pytest.skip("No agent template directories found")

        all_errors = []

        # Check each directory independently for duplicates
        for directory in agent_directories:
            agent_files = list(directory.glob("*.md"))
            if not agent_files:
                continue

            errors = []
            name_registry = (
                {}
            )  # Maps name -> file_path for duplicate detection within this directory

            for agent_file in agent_files:
                file_path_str = str(
                    agent_file.relative_to(agent_file.parent.parent.parent)
                )

                # Step 1: Extract frontmatter
                frontmatter_content, extract_error = self.extract_frontmatter(
                    agent_file
                )
                if extract_error:
                    errors.append(f"{file_path_str}: {extract_error}")
                    continue

                # Step 2: Parse YAML
                assert frontmatter_content is not None
                try:
                    frontmatter_data = yaml.safe_load(frontmatter_content)
                except yaml.YAMLError as e:
                    errors.append(f"{file_path_str}: YAML parsing failed - {e}")
                    continue

                # Ensure frontmatter parsed to a dict
                if not isinstance(frontmatter_data, dict):
                    errors.append(
                        f"{file_path_str}: Frontmatter must be a YAML object/dict, "
                        f"got {type(frontmatter_data).__name__}"
                    )
                    continue

                # Step 3: Validate 'name' field exists
                if "name" not in frontmatter_data:
                    errors.append(
                        f"{file_path_str}: Missing required 'name' field in frontmatter"
                    )
                    continue

                name_value = frontmatter_data["name"]

                # Step 4: Validate 'name' is non-empty string
                if not isinstance(name_value, str) or not name_value.strip():
                    errors.append(
                        f"{file_path_str}: 'name' field must be a non-empty string, "
                        f"got {name_value!r}"
                    )
                    continue

                name_normalized = name_value.strip()

                # Step 5: Check for duplicate names within this directory
                if name_normalized in name_registry:
                    previous_file = name_registry[name_normalized]
                    previous_path = str(
                        previous_file.relative_to(previous_file.parent.parent.parent)
                    )
                    errors.append(
                        f"{file_path_str}: Duplicate 'name' value '{name_normalized}' "
                        f"already used in {previous_path}"
                    )
                else:
                    name_registry[name_normalized] = agent_file

            all_errors.extend(errors)

        # Report all errors at once for better debugging
        if all_errors:
            error_report = "\n\nFrontmatter validation failures:\n" + "\n".join(
                f"  - {error}" for error in all_errors
            )
            pytest.fail(error_report)

    def test_frontmatter_extraction_logic(self):
        """
        Test the frontmatter extraction regex works correctly.

        This is a unit test for the extraction logic itself.
        """
        # Valid frontmatter
        valid_content = """---
name: test-agent
description: Test description
---

# Content here
"""
        match = re.match(r"^---\n(.*?)\n---", valid_content, re.DOTALL)
        assert match is not None
        frontmatter = match.group(1)
        assert "name: test-agent" in frontmatter
        assert "description: Test description" in frontmatter

        # No frontmatter
        no_frontmatter = """# Just a heading

Some content
"""
        match = re.match(r"^---\n(.*?)\n---", no_frontmatter, re.DOTALL)
        assert match is None

        # Malformed frontmatter (only one delimiter)
        malformed = """---
name: test
# Missing closing delimiter
"""
        match = re.match(r"^---\n(.*?)\n---", malformed, re.DOTALL)
        assert match is None


class TestAgentCapabilityHardening:
    """Regression guard for issue #378: disallowedTools frontmatter on non-writer agents.

    Agents that never legitimately edit code must declare disallowedTools at the
    harness level, not rely on prompt-text alone. This test pins those contracts
    so they cannot be silently removed.
    """

    _REPO_ROOT = Path(__file__).parent.parent
    _AGENTS_DIR = _REPO_ROOT / ".claude" / "agents"

    def _load_frontmatter(self, agent_name: str) -> dict:
        path = self._AGENTS_DIR / f"{agent_name}.md"
        assert path.exists(), f"Agent file not found: {path}"
        content = path.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert match, f"No frontmatter in {path}"
        return yaml.safe_load(match.group(1))

    def test_monitor_has_edit_in_disallowed_tools(self):
        fm = self._load_frontmatter("monitor")
        disallowed = fm.get("disallowedTools", [])
        assert "Edit" in disallowed, (
            "monitor must deny Edit — it is a READ-ONLY reviewer"
        )

    def test_monitor_has_agent_in_disallowed_tools(self):
        fm = self._load_frontmatter("monitor")
        disallowed = fm.get("disallowedTools", [])
        assert "Agent" in disallowed, (
            "monitor must deny Agent — it must not spawn sub-agents"
        )

    def test_monitor_write_not_denied(self):
        """monitor IS allowed to Write — it writes .map/ evidence artifacts."""
        fm = self._load_frontmatter("monitor")
        disallowed = fm.get("disallowedTools", [])
        assert "Write" not in disallowed, (
            "monitor needs Write for .map/ evidence artifacts — do not deny it"
        )

    def test_research_agent_has_edit_in_disallowed_tools(self):
        fm = self._load_frontmatter("research-agent")
        disallowed = fm.get("disallowedTools", [])
        assert "Edit" in disallowed, (
            "research-agent must deny Edit — it is a read-only context scanner"
        )

    def test_research_agent_has_agent_in_disallowed_tools(self):
        fm = self._load_frontmatter("research-agent")
        disallowed = fm.get("disallowedTools", [])
        assert "Agent" in disallowed, (
            "research-agent must deny Agent — it must not spawn sub-agents"
        )

    def test_research_agent_write_not_denied(self):
        """research-agent IS allowed to Write — MAP-planning integration appends to research artifact."""
        fm = self._load_frontmatter("research-agent")
        disallowed = fm.get("disallowedTools", [])
        assert "Write" not in disallowed, (
            "research-agent needs Write for MAP-planning research artifact append"
        )

    def test_predictor_has_edit_in_disallowed_tools(self):
        fm = self._load_frontmatter("predictor")
        disallowed = fm.get("disallowedTools", [])
        assert "Edit" in disallowed, (
            "predictor must deny Edit — it is an analysis-only agent"
        )

    def test_predictor_has_write_in_disallowed_tools(self):
        fm = self._load_frontmatter("predictor")
        disallowed = fm.get("disallowedTools", [])
        assert "Write" in disallowed, (
            "predictor must deny Write — it is an analysis-only agent"
        )

    def test_predictor_has_agent_in_disallowed_tools(self):
        fm = self._load_frontmatter("predictor")
        disallowed = fm.get("disallowedTools", [])
        assert "Agent" in disallowed, (
            "predictor must deny Agent — it must not spawn sub-agents"
        )

    def test_evaluator_has_edit_in_disallowed_tools(self):
        fm = self._load_frontmatter("evaluator")
        disallowed = fm.get("disallowedTools", [])
        assert "Edit" in disallowed, (
            "evaluator must deny Edit — it is a scoring-only agent"
        )

    def test_evaluator_has_write_in_disallowed_tools(self):
        fm = self._load_frontmatter("evaluator")
        disallowed = fm.get("disallowedTools", [])
        assert "Write" in disallowed, (
            "evaluator must deny Write — it is a scoring-only agent"
        )

    def test_evaluator_has_agent_in_disallowed_tools(self):
        fm = self._load_frontmatter("evaluator")
        disallowed = fm.get("disallowedTools", [])
        assert "Agent" in disallowed, (
            "evaluator must deny Agent — it must not spawn sub-agents"
        )

    def test_task_decomposer_has_permission_mode_plan(self):
        fm = self._load_frontmatter("task-decomposer")
        assert fm.get("permissionMode") == "plan", (
            "task-decomposer must keep permissionMode: plan"
        )

    def test_actor_has_no_disallowed_tools(self):
        """actor is a legitimate writer and must NOT be capability-restricted."""
        fm = self._load_frontmatter("actor")
        assert "disallowedTools" not in fm, (
            "actor is a legitimate writer — do not add disallowedTools"
        )

    def test_final_verifier_has_no_disallowed_tools(self):
        """final-verifier is a legitimate writer and must NOT be capability-restricted."""
        fm = self._load_frontmatter("final-verifier")
        assert "disallowedTools" not in fm, (
            "final-verifier is a legitimate writer — do not add disallowedTools"
        )
