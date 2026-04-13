"""
Tests for MAP Framework skill structure, frontmatter, and trigger compliance.

Validates that shipped skills keep a clean, Claude-compatible metadata surface:
- Valid YAML frontmatter with --- delimiters
- Descriptions include trigger phrases ("Use when")
- Descriptions include negative triggers ("Do NOT use")
- Descriptions stay within the Claude skill listing truncation limit
- Frontmatter only uses the MAP-supported key set
- map-* references in descriptions resolve to shipped commands or skills
- Skill folder names use kebab-case
- No README.md inside skill folders (per Anthropic guide)
- skill-rules.json has entries for all skills
- Required sections (Examples, Troubleshooting) present
"""

import json
import re
from pathlib import Path

import pytest
import yaml

SUPPORTED_FRONTMATTER_FIELDS = {
    "allowed-tools",
    "argument-hint",
    "context",
    "description",
    "disable-model-invocation",
    "effort",
    "hooks",
    "metadata",
    "model",
    "name",
    "paths",
    "user-invocable",
    "version",
}


class TestSkillStructure:
    """Test that all skill directories follow the expected structure."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture
    def skills_dir(self, project_root):
        return project_root / ".claude" / "skills"

    @pytest.fixture
    def template_skills_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "skills"

    @pytest.fixture
    def templates_commands_dir(self, project_root):
        return project_root / "src" / "mapify_cli" / "templates" / "commands"

    @pytest.fixture
    def skill_folders(self, skills_dir):
        """Return list of skill folder names (excluding files)."""
        if not skills_dir.exists():
            pytest.skip(".claude/skills/ directory doesn't exist")
        return [
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    @pytest.fixture
    def skill_rules(self, skills_dir):
        rules_file = skills_dir / "skill-rules.json"
        if not rules_file.exists():
            pytest.skip("skill-rules.json doesn't exist")
        return json.loads(rules_file.read_text())

    @pytest.fixture
    def known_map_surfaces(self, skill_folders, templates_commands_dir):
        command_names = {
            path.stem for path in templates_commands_dir.glob("map-*.md")
        }
        return set(skill_folders) | command_names

    def _parse_frontmatter(self, skill_md_path: Path) -> dict:
        """Parse YAML frontmatter from a SKILL.md file."""
        content = skill_md_path.read_text()
        if not content.startswith("---"):
            return {}
        end = content.find("---", 3)
        if end == -1:
            return {}
        frontmatter_str = content[3:end].strip()
        return yaml.safe_load(frontmatter_str) or {}

    # --- Structural tests ---

    def test_all_skills_have_skill_md(self, skills_dir, skill_folders):
        """All skill folders must contain a SKILL.md file."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            assert skill_file.exists(), f"Skill '{folder}' is missing SKILL.md"

    def test_skill_names_are_kebab_case(self, skill_folders):
        """Skill folder names must use kebab-case only."""
        kebab_re = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
        for folder in skill_folders:
            assert kebab_re.match(folder), (
                f"Skill folder '{folder}' is not kebab-case. "
                f"Use lowercase letters, numbers, and hyphens only."
            )

    def test_no_readme_in_skill_folders(self, skills_dir, skill_folders):
        """Skill folders should not contain README.md (per Anthropic guide)."""
        for folder in skill_folders:
            readme = skills_dir / folder / "README.md"
            assert not readme.exists(), (
                f"Skill '{folder}' has a README.md inside the skill folder. "
                f"Per Anthropic guide, use SKILL.md as the main file."
            )

    # --- Frontmatter tests ---

    def test_all_skills_have_valid_frontmatter(self, skills_dir, skill_folders):
        """All SKILL.md files must have valid YAML frontmatter between --- delimiters."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            content = skill_file.read_text()
            assert content.startswith(
                "---"
            ), f"Skill '{folder}/SKILL.md' is missing opening '---' delimiter"
            # Find closing delimiter (skip the opening one)
            end = content.find("---", 3)
            assert (
                end > 3
            ), f"Skill '{folder}/SKILL.md' is missing closing '---' delimiter"
            # Parse YAML
            frontmatter = self._parse_frontmatter(skill_file)
            assert (
                frontmatter
            ), f"Skill '{folder}/SKILL.md' has empty or invalid YAML frontmatter"

    def test_frontmatter_has_required_fields(self, skills_dir, skill_folders):
        """Frontmatter must include 'name' and 'description' fields."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            assert "name" in fm, f"Skill '{folder}' frontmatter is missing 'name' field"
            assert (
                "description" in fm
            ), f"Skill '{folder}' frontmatter is missing 'description' field"
            # Name should match folder
            assert (
                fm["name"] == folder
            ), f"Skill '{folder}' frontmatter name '{fm['name']}' doesn't match folder name"

    def test_descriptions_include_trigger_phrases(self, skills_dir, skill_folders):
        """Descriptions must mention 'Use when' or trigger conditions."""
        trigger_patterns = [
            r"[Uu]se when",
            r"[Uu]se this when",
            r"[Uu]se for",
        ]
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            desc = fm.get("description", "")
            has_trigger = any(re.search(p, desc) for p in trigger_patterns)
            assert has_trigger, (
                f"Skill '{folder}' description doesn't include trigger phrases. "
                f"Add 'Use when ...' to the description."
            )

    def test_descriptions_include_negative_triggers(self, skills_dir, skill_folders):
        """Descriptions must mention 'Do NOT use' exclusions."""
        negative_patterns = [
            r"[Dd]o [Nn][Oo][Tt] use",
            r"[Dd]on't use",
            r"[Nn]ot for",
        ]
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            desc = fm.get("description", "")
            has_negative = any(re.search(p, desc) for p in negative_patterns)
            assert has_negative, (
                f"Skill '{folder}' description doesn't include negative triggers. "
                f"Add 'Do NOT use for ...' to the description."
            )

    def test_descriptions_fit_claude_skill_listing_limit(
        self, skills_dir, skill_folders
    ):
        """Descriptions should stay under the 250-char Claude listing limit."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            desc = fm.get("description", "")
            assert len(desc) <= 250, (
                f"Skill '{folder}' description is {len(desc)} chars; "
                "keep it at or under 250 chars to avoid UI truncation."
            )

    def test_frontmatter_uses_supported_fields(self, skills_dir, skill_folders):
        """Skill frontmatter should stay within MAP's supported key set."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            unsupported = sorted(set(fm) - SUPPORTED_FRONTMATTER_FIELDS)
            assert not unsupported, (
                f"Skill '{folder}' uses unsupported frontmatter fields: "
                f"{', '.join(unsupported)}"
            )

    def test_description_map_references_resolve(
        self, skills_dir, skill_folders, known_map_surfaces
    ):
        """map-* references in descriptions should point at shipped surfaces."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            desc = fm.get("description", "")
            referenced = set(re.findall(r"\b(map-[a-z0-9-]+)\b", desc))
            unknown = sorted(referenced - known_map_surfaces)
            assert not unknown, (
                f"Skill '{folder}' references non-shipped MAP surfaces in its "
                f"description: {', '.join(unknown)}"
            )

    def test_manual_skills_advertise_argument_hint(self, skills_dir, skill_folders):
        """Manual slash skills should expose an argument hint for the UI."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            if not fm.get("disable-model-invocation"):
                continue
            hint = fm.get("argument-hint", "")
            assert hint, (
                f"Skill '{folder}' disables model invocation but has no "
                "argument-hint for manual use."
            )
            assert hint.startswith("[") and hint.endswith("]"), (
                f"Skill '{folder}' argument-hint '{hint}' should document the "
                "manual invocation shape."
            )

    # --- Content section tests ---

    def test_skills_have_examples_section(self, skills_dir, skill_folders):
        """All skills should have an Examples section."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            content = skill_file.read_text()
            assert re.search(
                r"^## Examples", content, re.MULTILINE
            ), f"Skill '{folder}' is missing '## Examples' section"

    def test_skills_have_troubleshooting_section(self, skills_dir, skill_folders):
        """All skills should have a Troubleshooting section."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            content = skill_file.read_text()
            assert re.search(
                r"^## Troubleshooting", content, re.MULTILINE
            ), f"Skill '{folder}' is missing '## Troubleshooting' section"

    # --- skill-rules.json tests ---

    def test_skill_rules_json_is_valid(self, skills_dir):
        """skill-rules.json must be valid JSON."""
        rules_file = skills_dir / "skill-rules.json"
        assert rules_file.exists(), "skill-rules.json not found"
        content = rules_file.read_text()
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            pytest.fail(f"skill-rules.json is not valid JSON: {e}")

    def test_all_skills_have_trigger_rules(self, skill_folders, skill_rules):
        """All skill folders should have corresponding entries in skill-rules.json."""
        skills_in_rules = set(skill_rules.get("skills", {}).keys())
        for folder in skill_folders:
            assert folder in skills_in_rules, (
                f"Skill '{folder}' has no trigger rules in skill-rules.json. "
                f"Add a '{folder}' entry with promptTriggers."
            )

    def test_trigger_rules_have_keywords(self, skill_rules):
        """Each skill's trigger rules should have keywords defined."""
        for name, rule in skill_rules.get("skills", {}).items():
            triggers = rule.get("promptTriggers", {})
            keywords = triggers.get("keywords", [])
            assert len(keywords) >= 3, (
                f"Skill '{name}' has fewer than 3 keywords in skill-rules.json. "
                f"Add more keywords for reliable triggering."
            )

    def test_trigger_rules_have_intent_patterns(self, skill_rules):
        """Each skill's trigger rules should have intent patterns."""
        for name, rule in skill_rules.get("skills", {}).items():
            triggers = rule.get("promptTriggers", {})
            patterns = triggers.get("intentPatterns", [])
            assert len(patterns) >= 2, (
                f"Skill '{name}' has fewer than 2 intent patterns in skill-rules.json. "
                f"Add more patterns for reliable triggering."
            )

    # --- Template sync tests ---

    def test_skill_templates_in_sync(
        self, skills_dir, template_skills_dir, skill_folders
    ):
        """Skill SKILL.md files should be in sync between .claude/ and templates/."""
        if not template_skills_dir.exists():
            pytest.skip("Template skills directory doesn't exist")

        for folder in skill_folders:
            source = skills_dir / folder / "SKILL.md"
            target = template_skills_dir / folder / "SKILL.md"
            if not target.exists():
                pytest.fail(
                    f"Skill '{folder}/SKILL.md' missing from templates. "
                    f"Run: make sync-templates"
                )
            assert source.read_text() == target.read_text(), (
                f"Skill '{folder}/SKILL.md' differs between .claude/skills/ and templates/skills/. "
                f"Run: make sync-templates"
            )

    def test_skill_rules_in_sync(self, skills_dir, template_skills_dir):
        """skill-rules.json should be in sync between .claude/ and templates/."""
        if not template_skills_dir.exists():
            pytest.skip("Template skills directory doesn't exist")

        source = skills_dir / "skill-rules.json"
        target = template_skills_dir / "skill-rules.json"
        if not source.exists() or not target.exists():
            pytest.skip("skill-rules.json missing from one location")
        assert source.read_text() == target.read_text(), (
            "skill-rules.json differs between .claude/skills/ and templates/skills/. "
            "Run: make sync-templates"
        )

    # --- Validation script tests ---

    def test_validation_scripts_are_executable(self, skills_dir, skill_folders):
        """Scripts in skill scripts/ directories should be executable."""
        for folder in skill_folders:
            scripts_dir = skills_dir / folder / "scripts"
            if not scripts_dir.exists():
                continue
            for script in scripts_dir.iterdir():
                if script.is_file() and script.suffix in (".sh", ".py"):
                    # Check file has executable permission or is a python script
                    if script.suffix == ".sh":
                        import os

                        assert os.access(script, os.X_OK), (
                            f"Script '{script}' is not executable. "
                            f"Run: chmod +x {script}"
                        )
