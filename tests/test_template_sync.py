"""
Tests for template synchronization between .claude/agents/ and src/mapify_cli/templates/agents/.

This test ensures that agent templates are always in sync between the development
directory (.claude/agents/) and the distribution templates (src/mapify_cli/templates/agents/).

When templates are out of sync:
- New users running 'mapify init' get outdated templates
- Development and production behavior diverge
- This violates the project's template synchronization requirements

See .claude/CLAUDE.md for the template synchronization process.
"""

import filecmp
import json
import pytest
from pathlib import Path


DISALLOWED_TEMPLATE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
DISALLOWED_TEMPLATE_FILE_NAMES = {
    ".DS_Store",
    "agent_metrics.jsonl",
    "playbook.db",
    "session.log",
    "current_context.txt",
}
DISALLOWED_TEMPLATE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pkl",
}


def _is_disallowed_template_artifact(path: Path) -> bool:
    if any(part in DISALLOWED_TEMPLATE_DIR_NAMES for part in path.parts):
        return True
    if path.name in DISALLOWED_TEMPLATE_FILE_NAMES:
        return True
    return path.suffix in DISALLOWED_TEMPLATE_SUFFIXES


class TestTemplateArtifactHygiene:
    """Generated/cache artifacts must never ship through mapify templates."""

    @pytest.fixture
    def templates_root(self):
        return Path(__file__).parent.parent / "src" / "mapify_cli" / "templates"

    def test_shipped_templates_do_not_contain_generated_artifacts(
        self, templates_root
    ):
        offenders = [
            relative_path
            for path in templates_root.rglob("*")
            if _is_disallowed_template_artifact(
                relative_path := path.relative_to(templates_root)
            )
        ]

        assert not offenders, (
            "Generated/cache artifacts tracked in shipped templates: "
            + ", ".join(str(path) for path in sorted(offenders))
            + ". Run make sync-templates after cleaning template inputs."
        )


class TestTemplateSynchronization:
    """Test that agent templates are synchronized between .claude/ and templates/."""

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_agents_dir(self, project_root):
        """Get .claude/agents directory (development source)."""
        return project_root / ".claude" / "agents"

    @pytest.fixture
    def templates_agents_dir(self, project_root):
        """Get src/mapify_cli/templates/agents directory (distribution target)."""
        return project_root / "src" / "mapify_cli" / "templates" / "agents"

    @pytest.fixture
    def expected_agents(self):
        """List of expected agent template files (all 11 agents)."""
        return [
            "actor.md",
            "debate-arbiter.md",
            "documentation-reviewer.md",
            "evaluator.md",
            "final-verifier.md",
            "monitor.md",
            "predictor.md",
            "reflector.md",
            "research-agent.md",
            "synthesizer.md",
            "task-decomposer.md",
        ]

    def test_all_agents_exist_in_both_directories(
        self, claude_agents_dir, templates_agents_dir, expected_agents
    ):
        """Test that all expected agent files exist in both directories."""
        for agent in expected_agents:
            claude_file = claude_agents_dir / agent
            template_file = templates_agents_dir / agent

            assert claude_file.exists(), (
                f"{agent} missing from .claude/agents/. " f"Expected at: {claude_file}"
            )
            assert template_file.exists(), (
                f"{agent} missing from templates/agents/. "
                f"Run: cp .claude/agents/{agent} src/mapify_cli/templates/agents/"
            )

    def test_no_orphaned_files_in_templates(
        self, claude_agents_dir, templates_agents_dir
    ):
        """Test that templates/ doesn't have files that don't exist in .claude/agents/."""
        if not templates_agents_dir.exists():
            pytest.skip("Templates directory doesn't exist")

        claude_files = (
            {f.name for f in claude_agents_dir.glob("*.md")}
            if claude_agents_dir.exists()
            else set()
        )
        template_files = {f.name for f in templates_agents_dir.glob("*.md")}

        orphaned = template_files - claude_files
        assert not orphaned, (
            f"Orphaned files in templates/agents/ that don't exist in .claude/agents/: {orphaned}. "
            f"These files should be removed from src/mapify_cli/templates/agents/"
        )

    def test_no_missing_files_in_templates(
        self, claude_agents_dir, templates_agents_dir
    ):
        """Test that all files from .claude/agents/ exist in templates/."""
        if not claude_agents_dir.exists():
            pytest.skip(".claude/agents/ directory doesn't exist")

        claude_files = {f.name for f in claude_agents_dir.glob("*.md")}
        template_files = (
            {f.name for f in templates_agents_dir.glob("*.md")}
            if templates_agents_dir.exists()
            else set()
        )

        missing = claude_files - template_files
        assert not missing, (
            f"Files in .claude/agents/ missing from templates/agents/: {missing}. "
            f"Run: cp .claude/agents/{{file}} src/mapify_cli/templates/agents/"
        )

    @pytest.mark.parametrize(
        "agent",
        [
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "reflector.md",
            "task-decomposer.md",
            "documentation-reviewer.md",
        ],
    )
    def test_agent_content_matches(
        self, claude_agents_dir, templates_agents_dir, agent
    ):
        """Test that agent file content is identical between directories."""
        claude_file = claude_agents_dir / agent
        template_file = templates_agents_dir / agent

        if not claude_file.exists() or not template_file.exists():
            pytest.skip(f"{agent} doesn't exist in both directories")

        assert filecmp.cmp(claude_file, template_file, shallow=False), (
            f"{agent} content differs between .claude/agents/ and templates/agents/. "
            f"Run: cp .claude/agents/{agent} src/mapify_cli/templates/agents/"
        )

    def test_file_count_matches(self, claude_agents_dir, templates_agents_dir):
        """Test that both directories have the same number of .md files."""
        if not claude_agents_dir.exists() or not templates_agents_dir.exists():
            pytest.skip("One or both directories don't exist")

        claude_count = len(list(claude_agents_dir.glob("*.md")))
        template_count = len(list(templates_agents_dir.glob("*.md")))

        assert claude_count == template_count, (
            f"File count mismatch: .claude/agents/ has {claude_count} files, "
            f"templates/agents/ has {template_count} files. "
            f"Ensure all agents are synchronized."
        )

    def test_agent_frontmatter_no_deleted_changelog(
        self, claude_agents_dir, expected_agents
    ):
        """Test that agent frontmatter doesn't reference deleted CHANGELOG.md."""
        for agent in expected_agents:
            agent_file = claude_agents_dir / agent
            if not agent_file.exists():
                continue

            content = agent_file.read_text()
            # Check frontmatter (between first two ---)
            if content.startswith("---"):
                frontmatter_end = content.find("---", 4)
                if frontmatter_end > 0:
                    frontmatter = content[4:frontmatter_end]
                    assert "changelog:" not in frontmatter.lower(), (
                        f"{agent} has 'changelog:' in frontmatter pointing to deleted file. "
                        f"Remove the changelog field from the frontmatter."
                    )


class TestCommandTemplateSynchronization:
    """Sync invariants for `.claude/commands/` and `templates/commands/`.

    MAP slash commands now ship as Skills (`.claude/skills/map-*/SKILL.md`),
    not as `.claude/commands/map-*.md` files. The `commands/` directory is
    preserved for user-custom commands. These tests therefore enforce two
    invariants:

      1. NO `map-*.md` should exist in either commands directory — they're
         a regression of the skills migration if they reappear.
      2. ANY non-map `.md` files in `.claude/commands/` (user customs)
         must be byte-identical to their `templates/commands/` mirrors.
    """

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_commands_dir(self, project_root):
        return project_root / ".claude" / "commands"

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    def test_no_map_command_files_remain(
        self, claude_commands_dir, templates_commands_dir
    ):
        """MAP commands moved to skills; map-*.md must not exist in commands/."""
        offenders = []
        if claude_commands_dir.exists():
            offenders.extend(str(p) for p in claude_commands_dir.glob("map-*.md"))
        if templates_commands_dir.exists():
            offenders.extend(str(p) for p in templates_commands_dir.glob("map-*.md"))
        assert not offenders, (
            "MAP slash commands have been migrated to Skills "
            "(.claude/skills/map-*/SKILL.md). Found stray map-*.md command "
            f"files: {offenders}. Delete them or move the content into the "
            "matching skill."
        )

    def test_non_map_commands_in_sync(
        self, claude_commands_dir, templates_commands_dir
    ):
        """Any user-custom command in .claude/commands/ must match the template mirror."""
        if not claude_commands_dir.exists() or not templates_commands_dir.exists():
            pytest.skip("commands/ directory missing in source or templates")

        claude_files = {p.name for p in claude_commands_dir.glob("*.md")}
        template_files = {p.name for p in templates_commands_dir.glob("*.md")}

        # Compare the union — any file present in either side must exist in
        # both and have identical content.
        for name in sorted(claude_files | template_files):
            claude_file = claude_commands_dir / name
            template_file = templates_commands_dir / name
            assert claude_file.exists(), (
                f"{name} present in templates/commands/ but missing from "
                ".claude/commands/. Run: make sync-templates"
            )
            assert template_file.exists(), (
                f"{name} present in .claude/commands/ but missing from "
                "templates/commands/. Run: make sync-templates"
            )
            assert filecmp.cmp(claude_file, template_file, shallow=False), (
                f"{name} differs between .claude/commands/ and "
                "templates/commands/. Run: make sync-templates"
            )


class TestReferenceTemplateSynchronization:
    """Sync invariants for shared references consumed by shipped skills."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def claude_references_dir(self, project_root):
        return project_root / ".claude" / "references"

    @pytest.fixture
    def templates_references_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "references"

    def test_reference_files_in_sync(
        self, claude_references_dir, templates_references_dir
    ):
        """Shared reference files should ship exactly as authored."""
        if not claude_references_dir.exists():
            pytest.skip(".claude/references/ directory doesn't exist")

        source_files = {
            path.relative_to(claude_references_dir): path
            for path in claude_references_dir.rglob("*")
            if path.is_file()
        }
        target_files = (
            {
                path.relative_to(templates_references_dir): path
                for path in templates_references_dir.rglob("*")
                if path.is_file()
            }
            if templates_references_dir.exists()
            else {}
        )

        missing = sorted(source_files.keys() - target_files.keys())
        extra = sorted(target_files.keys() - source_files.keys())

        assert not missing, (
            "Reference files missing from templates: "
            + ", ".join(str(path) for path in missing)
        )
        assert not extra, (
            "Reference files present only in templates: "
            + ", ".join(str(path) for path in extra)
        )

        for rel_path, source in source_files.items():
            target = target_files[rel_path]
            assert source.read_bytes() == target.read_bytes(), (
                f"Reference file '{rel_path}' differs between .claude/references/ "
                "and templates/references/. Run: make sync-templates"
            )


class TestRootTemplateSynchronization:
    """Sync invariants for top-level Claude configuration templates."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    def test_workflow_rules_in_sync(self, project_root):
        source = project_root / ".claude" / "workflow-rules.json"
        target = project_root / "src" / "mapify_cli" / "templates" / "workflow-rules.json"

        assert source.exists(), ".claude/workflow-rules.json is missing"
        assert target.exists(), "templates/workflow-rules.json is missing"
        assert source.read_bytes() == target.read_bytes(), (
            "workflow-rules.json differs between .claude/ and templates/. "
            "Run: make sync-templates"
        )

    def test_workflow_rules_declare_execution_policies(self, project_root):
        rules_file = project_root / ".claude" / "workflow-rules.json"
        rules = json.loads(rules_file.read_text())

        expected = {
            "map-fast": "low/direct",
            "map-efficient": "medium/adaptive",
            "map-debug": "medium/adaptive",
        }
        for workflow, thinking_policy in expected.items():
            policy = rules["workflows"][workflow].get("executionPolicy", {})
            assert policy.get("thinking_policy") == thinking_policy
            assert policy.get("parallel_tool_policy"), (
                f"{workflow} should declare parallel_tool_policy"
            )


class TestCodexTemplateSynchronization:
    """Test that Codex templates are synchronized between .codex/ and templates/codex/."""

    # Each tuple: (source relative to .codex/, template relative to templates/codex/)
    CODEX_FILES = [
        ("skills/map-plan/SKILL.md", "skills/map-plan/SKILL.md"),
        ("skills/map-fast/SKILL.md", "skills/map-fast/SKILL.md"),
        ("skills/map-check/SKILL.md", "skills/map-check/SKILL.md"),
        ("skills/map-explain/SKILL.md", "skills/map-explain/SKILL.md"),
        ("agents/researcher.toml", "agents/researcher.toml"),
        ("agents/decomposer.toml", "agents/decomposer.toml"),
        ("agents/monitor.toml", "agents/monitor.toml"),
        ("config.toml", "config.toml"),
        ("hooks.json", "hooks.json"),
        ("hooks/workflow-gate.py", "hooks/workflow-gate.py"),
        ("AGENTS.md", "AGENTS.md"),
    ]

    @pytest.fixture
    def project_root(self):
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def codex_source_dir(self, project_root):
        """Get .codex/ directory (development source)."""
        return project_root / ".codex"

    @pytest.fixture
    def codex_templates_dir(self, project_root):
        """Get src/mapify_cli/templates/codex/ directory (distribution target)."""
        return project_root / "src" / "mapify_cli" / "templates" / "codex"

    @pytest.mark.parametrize("source_rel,template_rel", CODEX_FILES)
    def test_codex_template_exists(
        self, codex_source_dir, codex_templates_dir, source_rel, template_rel
    ):
        """Test that each Codex template file exists in the templates/codex/ directory."""
        source_file = codex_source_dir / source_rel
        template_file = codex_templates_dir / template_rel

        assert source_file.exists(), (
            f"Source file missing from .codex/: {source_rel}. "
            f"Expected at: {source_file}"
        )
        assert template_file.exists(), (
            f"Template file missing from templates/codex/: {template_rel}. "
            f"Run 'make sync-templates' to fix"
        )

    @pytest.mark.parametrize("source_rel,template_rel", CODEX_FILES)
    def test_codex_template_content_identical(
        self, codex_source_dir, codex_templates_dir, source_rel, template_rel
    ):
        """Test that each Codex source file and its template copy are byte-identical."""
        source_file = codex_source_dir / source_rel
        template_file = codex_templates_dir / template_rel

        if not source_file.exists() or not template_file.exists():
            pytest.skip(f"{source_rel} doesn't exist in both locations")

        assert filecmp.cmp(source_file, template_file, shallow=False), (
            f"Content mismatch between .codex/{source_rel} and "
            f"templates/codex/{template_rel}. "
            f"Run 'make sync-templates' to fix"
        )

    def test_workflow_gate_parity_claude_codex(self, project_root):
        """workflow-gate.py must be identical between .claude/hooks/ and .codex/hooks/."""
        claude_gate = project_root / ".claude" / "hooks" / "workflow-gate.py"
        codex_gate = project_root / ".codex" / "hooks" / "workflow-gate.py"

        if not claude_gate.exists() or not codex_gate.exists():
            pytest.skip("Both .claude/ and .codex/ hooks must exist")

        assert filecmp.cmp(claude_gate, codex_gate, shallow=False), (
            "workflow-gate.py differs between .claude/hooks/ and .codex/hooks/. "
            "Run 'make sync-templates' to fix"
        )


class TestCodexAgentTomlFormat:
    """Validate that Codex agent TOMLs parse correctly and have the schema Codex expects.

    Codex CLI rejects agent files where developer_instructions is a table
    instead of a string (e.g., [developer_instructions] + content = '...'
    vs developer_instructions = '...'). This test catches the issue in CI.
    """

    AGENT_FILES = [
        "decomposer.toml",
        "monitor.toml",
        "researcher.toml",
    ]

    @pytest.fixture
    def codex_agents_dir(self):
        return Path(__file__).parent.parent / ".codex" / "agents"

    @pytest.fixture
    def template_agents_dir(self):
        return (
            Path(__file__).parent.parent
            / "src"
            / "mapify_cli"
            / "templates"
            / "codex"
            / "agents"
        )

    @pytest.mark.parametrize("filename", AGENT_FILES)
    def test_agent_toml_parses(self, codex_agents_dir, filename):
        """Each agent TOML must be valid TOML."""
        import tomllib

        agent_file = codex_agents_dir / filename
        if not agent_file.exists():
            pytest.skip(f"{filename} not found")
        data = tomllib.loads(agent_file.read_text(encoding="utf-8"))
        assert "name" in data, f"{filename} must have 'name' field"
        assert "description" in data, f"{filename} must have 'description' field"

    @pytest.mark.parametrize("filename", AGENT_FILES)
    def test_developer_instructions_is_string(self, codex_agents_dir, filename):
        """developer_instructions must be a plain string, not a table.

        Codex CLI error: 'invalid type: map, expected a string' when
        developer_instructions is defined as [developer_instructions] table.
        """
        import tomllib

        agent_file = codex_agents_dir / filename
        if not agent_file.exists():
            pytest.skip(f"{filename} not found")
        data = tomllib.loads(agent_file.read_text(encoding="utf-8"))
        di = data.get("developer_instructions")
        assert di is not None, f"{filename} must have 'developer_instructions' field"
        assert isinstance(di, str), (
            f"{filename}: developer_instructions must be a string, "
            f"got {type(di).__name__}. Use 'developer_instructions = "
            f'"""..."""'
            "' not '[developer_instructions]\\ncontent = ...' "
        )
        assert (
            len(di) > 50
        ), f"{filename}: developer_instructions too short ({len(di)} chars)"

    @pytest.mark.parametrize("filename", AGENT_FILES)
    def test_template_agent_matches_source(
        self, codex_agents_dir, template_agents_dir, filename
    ):
        """Template copy must be byte-identical to .codex/ source."""
        source = codex_agents_dir / filename
        template = template_agents_dir / filename
        if not source.exists() or not template.exists():
            pytest.skip(f"{filename} not in both locations")
        assert filecmp.cmp(source, template, shallow=False), (
            f"{filename} differs between .codex/agents/ and templates/codex/agents/. "
            f"Run 'make sync-templates' to fix"
        )
