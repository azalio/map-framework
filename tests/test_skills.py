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
- Manual slash invocation metadata matches skill frontmatter
- Local supporting-file references and skill hook commands resolve
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

NEGATIVE_TRIGGER_FIXTURES = {
    "map-state": [
        "Fix the typo in README.md",
        "Explain what this helper function does",
        "Update package metadata",
    ],
    "map-learn": [
        "Implement a learning dashboard component",
        "Remember to update the changelog after the release",
        "Explain the implementation strategy for this function",
    ],
}

SUPPORTED_SKILL_CLASSES = {"reference", "task", "hybrid"}


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
        command_names = {path.stem for path in templates_commands_dir.glob("map-*.md")}
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

    def test_skill_rules_have_supported_skill_class(self, skill_rules):
        """Every skill must declare whether it is reference, task, or hybrid."""
        for name, rule in skill_rules.get("skills", {}).items():
            skill_class = rule.get("skillClass")
            assert skill_class in SUPPORTED_SKILL_CLASSES, (
                f"Skill '{name}' has unsupported skillClass {skill_class!r}. "
                f"Use one of: {', '.join(sorted(SUPPORTED_SKILL_CLASSES))}."
            )

    def test_task_skill_class_matches_manual_runtime_metadata(
        self, skills_dir, skill_folders, skill_rules
    ):
        """Task skills behave like slash workflows and must be cataloged as manual."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            rule = skill_rules.get("skills", {}).get(folder, {})
            skill_class = rule.get("skillClass")
            is_manual_rule = (
                rule.get("type") == "manual" or rule.get("enforcement") == "manual"
            )

            if fm.get("disable-model-invocation"):
                assert skill_class == "task", (
                    f"Skill '{folder}' disables model invocation for direct slash use, "
                    "so skill-rules.json must classify it as skillClass='task'."
                )

            if skill_class == "task":
                assert is_manual_rule, (
                    f"Skill '{folder}' is skillClass='task' but is not manual in "
                    "skill-rules.json."
                )

    def test_reference_skill_class_has_no_runtime_side_effects(
        self, skills_dir, skill_folders, skill_rules
    ):
        """Reference skills should remain guidance-only, not hidden workflows."""
        for folder in skill_folders:
            rule = skill_rules.get("skills", {}).get(folder, {})
            if rule.get("skillClass") != "reference":
                continue

            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            is_manual_rule = (
                rule.get("type") == "manual" or rule.get("enforcement") == "manual"
            )

            assert not is_manual_rule, (
                f"Reference skill '{folder}' is classified as manual in "
                "skill-rules.json; use skillClass='task' for slash workflows."
            )
            assert not fm.get("disable-model-invocation"), (
                f"Reference skill '{folder}' disables model invocation; use "
                "skillClass='task' for direct slash workflows."
            )
            assert not fm.get("hooks"), (
                f"Reference skill '{folder}' declares hooks; use skillClass='hybrid' "
                "and list runtimeEffects."
            )
            assert not rule.get("runtimeEffects"), (
                f"Reference skill '{folder}' declares runtimeEffects; use "
                "skillClass='hybrid' for operational side effects."
            )

    def test_hybrid_skills_document_runtime_effects(self, skill_rules):
        """Hybrid skills need explicit runtime-effect metadata so docs are not misleading."""
        for name, rule in skill_rules.get("skills", {}).items():
            if rule.get("skillClass") != "hybrid":
                continue
            effects = rule.get("runtimeEffects", [])
            assert effects, (
                f"Hybrid skill '{name}' must list runtimeEffects that distinguish "
                "operational side effects from reference guidance."
            )
            assert all(isinstance(effect, str) and effect for effect in effects), (
                f"Hybrid skill '{name}' has invalid runtimeEffects entries."
            )

    def test_manual_skill_rules_match_frontmatter(
        self, skills_dir, skill_folders, skill_rules
    ):
        """Manual slash skills must be classified consistently across metadata files."""
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            rule = skill_rules.get("skills", {}).get(folder, {})
            is_manual_rule = (
                rule.get("type") == "manual" or rule.get("enforcement") == "manual"
            )

            if fm.get("disable-model-invocation"):
                assert is_manual_rule, (
                    f"Skill '{folder}' disables model invocation for direct slash use, "
                    "but skill-rules.json does not classify it as manual."
                )

            if is_manual_rule:
                assert fm.get("argument-hint"), (
                    f"Skill '{folder}' is manual in skill-rules.json, but its "
                    "frontmatter does not advertise an argument-hint."
                )

    def test_manual_skills_have_direct_invocation_triggers(
        self, skill_folders, skill_rules
    ):
        """Manual slash skills need explicit direct invocation trigger coverage."""
        for folder in skill_folders:
            rule = skill_rules.get("skills", {}).get(folder, {})
            is_manual_rule = (
                rule.get("type") == "manual" or rule.get("enforcement") == "manual"
            )
            if not is_manual_rule:
                continue

            triggers = rule.get("promptTriggers", {})
            keywords = triggers.get("keywords", [])
            patterns = triggers.get("intentPatterns", [])

            assert folder in keywords, (
                f"Manual skill '{folder}' should list its direct invocation name "
                "as a trigger keyword."
            )
            assert any(folder in pattern for pattern in patterns), (
                f"Manual skill '{folder}' should list its direct invocation name "
                "in at least one intent pattern."
            )

    def test_selected_skills_do_not_match_negative_trigger_fixtures(
        self, skill_rules
    ):
        """Representative unrelated utterances should not trigger noisy skills."""

        def matches_rule(rule, utterance: str) -> bool:
            triggers = rule.get("promptTriggers", {})
            text = utterance.lower()
            for keyword in triggers.get("keywords", []):
                if keyword.lower() in text:
                    return True
            for pattern in triggers.get("intentPatterns", []):
                if re.search(pattern, utterance, flags=re.IGNORECASE):
                    return True
            return False

        for skill_name, utterances in NEGATIVE_TRIGGER_FIXTURES.items():
            rule = skill_rules.get("skills", {}).get(skill_name)
            assert rule, f"Missing skill-rules.json entry for {skill_name}"
            for utterance in utterances:
                assert not matches_rule(rule, utterance), (
                    f"Skill '{skill_name}' should not trigger for unrelated "
                    f"utterance: {utterance!r}"
                )

    def test_local_markdown_supporting_links_resolve(self, skills_dir, skill_folders):
        """Relative Markdown links inside SKILL.md should point to bundled files."""
        link_re = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
        external_prefixes = ("http://", "https://", "mailto:", "#")

        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            content = re.sub(r"```.*?```", "", skill_file.read_text(), flags=re.DOTALL)
            for href in link_re.findall(content):
                target = href.split("#", 1)[0].strip()
                if not target or target.startswith(external_prefixes):
                    continue
                if target.startswith("/") or "$" in target or "<" in target:
                    continue

                resolved = (skill_file.parent / target).resolve()
                assert resolved.exists(), (
                    f"Skill '{folder}' links to missing bundled supporting file: "
                    f"{href}"
                )

    def test_skill_hook_commands_reference_bundled_scripts(
        self, skills_dir, skill_folders
    ):
        """Hook commands using CLAUDE_PLUGIN_ROOT should resolve inside the skill."""

        def iter_hook_commands(value):
            if isinstance(value, dict):
                command = value.get("command")
                if isinstance(command, str):
                    yield command
                for nested in value.values():
                    yield from iter_hook_commands(nested)
            elif isinstance(value, list):
                for item in value:
                    yield from iter_hook_commands(item)

        marker = "${CLAUDE_PLUGIN_ROOT}/"
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            for command in iter_hook_commands(fm.get("hooks", {})):
                if marker not in command:
                    continue
                rel_path = command.split(marker, 1)[1].split()[0]
                script_path = skills_dir / folder / rel_path
                assert script_path.exists(), (
                    f"Skill '{folder}' hook command references missing bundled "
                    f"script: {rel_path}"
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

    def test_skill_supporting_files_in_sync(self, skills_dir, template_skills_dir):
        """Bundled skill supporting files should ship with mapify init."""
        if not template_skills_dir.exists():
            pytest.skip("Template skills directory doesn't exist")

        def supporting_files(root: Path) -> dict[Path, Path]:
            return {
                path.relative_to(root): path
                for path in root.rglob("*")
                if path.is_file()
                and path.name not in {"SKILL.md", "skill-rules.json"}
            }

        source_files = supporting_files(skills_dir)
        target_files = supporting_files(template_skills_dir)
        missing = sorted(source_files.keys() - target_files.keys())
        extra = sorted(target_files.keys() - source_files.keys())

        assert not missing, (
            "Skill supporting files missing from templates: "
            + ", ".join(str(path) for path in missing)
        )
        assert not extra, (
            "Skill supporting files present only in templates: "
            + ", ".join(str(path) for path in extra)
        )

        for rel_path, source in source_files.items():
            target = target_files[rel_path]
            assert source.read_bytes() == target.read_bytes(), (
                f"Skill supporting file '{rel_path}' differs between .claude/skills/ "
                "and templates/skills/. Run: make sync-templates"
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


class TestLightweightWorkflowSkillContracts:
    """Regression tests for action-first lightweight workflow prompts."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    def _section(self, content: str, start_heading: str, next_heading: str) -> str:
        assert start_heading in content, f"Missing section heading: {start_heading}"
        start = content.index(start_heading)
        assert next_heading in content[start:], (
            f"Missing section end marker after {start_heading}: {next_heading}"
        )
        end = content.index(next_heading, start)
        return content[start:end]

    @pytest.mark.parametrize("skill_name", ["map-fast", "map-debug"])
    def test_lightweight_actors_apply_changes_directly(self, project_root, skill_name):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text()
        if skill_name == "map-fast":
            actor_section = self._section(content, "### 2.1", "### 2.2")
        else:
            actor_section = self._section(content, "### Fix Steps", "### Monitor")

        assert "Apply" in actor_section and "Edit/Write tools" in actor_section
        assert "files_changed" in actor_section
        assert "tests_run" in actor_section
        assert "remaining_risks" in actor_section
        assert "code_changes" not in actor_section
        assert "Provide FULL file content" not in actor_section

    @pytest.mark.parametrize("skill_name", ["map-fast", "map-debug"])
    def test_lightweight_monitors_validate_written_repo_state(
        self, project_root, skill_name
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text()
        if skill_name == "map-fast":
            monitor_section = self._section(content, "### 2.2", "### 2.3")
        else:
            monitor_section = self._section(
                content,
                "### Monitor Validation",
                "### Predictor Impact Analysis",
            )

        assert "Written Files" in monitor_section
        assert "written files" in monitor_section.lower()
        assert "Actor Output" not in monitor_section
        assert "paste actor JSON" not in monitor_section

    @pytest.mark.parametrize("skill_name", ["map-fast", "map-debug"])
    def test_lightweight_workflows_do_not_have_post_review_apply_step(
        self, project_root, skill_name
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text()
        lower_content = content.lower()

        assert "apply code changes using write/edit tools" not in lower_content
        assert "accept and apply changes" not in lower_content
        assert "apply fix" not in lower_content
        assert "### apply" not in lower_content
        assert (
            "Changes are already applied by Actor" in content
            or "already-written changes" in content
        )


class TestMapReviewSkillBundleWiring:
    """Validate that map-review SKILL.md is wired to consume the persisted review bundle.

    AC-5: create_review_bundle is called before reviewer agents are spawned.
    AC-5: Agent prompts reference bundle artifacts as PRIMARY context.
    INV-7: Existing handoff flows remain documented and unchanged in behavior.
    """

    @pytest.fixture
    def skill_md(self):
        skills_dir = Path(__file__).parent.parent / ".claude" / "skills"
        path = skills_dir / "map-review" / "SKILL.md"
        assert path.exists(), "map-review/SKILL.md not found"
        return path.read_text()

    def test_map_review_skill_invokes_create_review_bundle(self, skill_md):
        """create_review_bundle must appear in SKILL.md before the first Task( call (AC-5)."""
        assert "create_review_bundle" in skill_md, (
            "map-review/SKILL.md does not reference create_review_bundle"
        )
        bundle_pos = skill_md.index("create_review_bundle")
        task_pos = skill_md.index("Task(")
        assert bundle_pos < task_pos, (
            "create_review_bundle invocation must appear BEFORE the first Task( call "
            f"(bundle at {bundle_pos}, first Task( at {task_pos})"
        )

    def test_map_review_skill_references_bundle_artifacts_in_agent_prompts(self, skill_md):
        """Agent prompts must reference both review-bundle.json and review-bundle.md (AC-5)."""
        assert "review-bundle.json" in skill_md, (
            "map-review/SKILL.md does not reference review-bundle.json in agent prompts"
        )
        assert "review-bundle.md" in skill_md, (
            "map-review/SKILL.md does not reference review-bundle.md in agent prompts"
        )

    def test_map_review_skill_preserves_handoff_flows(self, skill_md):
        """Existing review gate / active issues / PR draft / learning handoff flows must remain (INV-7)."""
        assert "write_stage_gate" in skill_md, (
            "map-review/SKILL.md is missing write_stage_gate — review gate flow was removed"
        )
        assert "active-issues" in skill_md, (
            "map-review/SKILL.md is missing active-issues reference — active issues flow was removed"
        )
        assert "pr-draft" in skill_md, (
            "map-review/SKILL.md is missing pr-draft reference — PR draft flow was removed"
        )
        assert "learning-handoff" in skill_md, (
            "map-review/SKILL.md is missing learning-handoff reference — learning handoff flow was removed"
        )

    def test_map_review_skill_documents_detached_flag(self, skill_md):
        """AC-6 part 1: --detached flag must be documented in SKILL.md."""
        assert "--detached" in skill_md, (
            "map-review/SKILL.md does not document the --detached flag (AC-6)"
        )

    def test_map_review_skill_documents_no_source_mutation(self, skill_md):
        """INV-6: SKILL.md must state that the source branch is not mutated."""
        lower = skill_md.lower()
        assert "does not mutate" in lower or "not mutate the source branch" in lower or (
            "never mutated" in lower
        ), (
            "map-review/SKILL.md must state that the source branch is never mutated (INV-6)"
        )

    def test_map_review_skill_docs_mention_bundle_in_user_facing_files(self):
        """AC-8: README.md, docs/USAGE.md, and docs/ARCHITECTURE.md must each contain
        the literal string 'review-bundle.json' so the review contract is publicly documented."""
        project_root = Path(__file__).parent.parent
        files_to_check = [
            project_root / "README.md",
            project_root / "docs" / "USAGE.md",
            project_root / "docs" / "ARCHITECTURE.md",
        ]
        for doc_path in files_to_check:
            assert doc_path.exists(), f"Expected doc file missing: {doc_path}"
            content = doc_path.read_text(encoding="utf-8")
            assert "review-bundle.json" in content, (
                f"{doc_path.name} does not mention 'review-bundle.json' — "
                "user-facing docs must describe the review bundle contract (AC-8)"
            )

    def test_map_review_skill_handles_unavailable_detached(self, skill_md):
        """AC-6 part 2: SKILL.md must document graceful degradation when detached prep is unavailable."""
        lower = skill_md.lower()
        has_degradation = (
            "still proceeds" in lower
            or "review still proceeds" in lower
            or "graceful degradation" in lower
            or ("continue" in lower and "unavailable" in lower)
        )
        assert has_degradation, (
            "map-review/SKILL.md must document that the review still proceeds when "
            "detached preparation is unavailable (graceful degradation, AC-6)"
        )


class TestMapReviewSkillOrderingWiring:
    """Validate ST-006 ordering/bias-hardening changes in map-review SKILL.md.

    AC-9:  argument-hint lists all four new flags; Step 0 parses each.
    AC-10: 'Recommended option is always listed first' absent; (Recommended) marker
           placed AFTER option label; CI auto-select uses marker, not position (INV-11).
    AC-11: Phase B iterates helper-returned order; 'Section N+1' phrasing replaced with
           'next section'.
    AC-12: --compare-orderings flow invokes agents twice, calls compare_review_runs,
           then record-review-ordering.
    EC-1/EC-17: mutual exclusion block present.
    EC-15:  prepare_detached_review called exactly once; EC-15 note present.
    EC-16:  --seed extraction uses grep/sed pattern; no $(...)-expansion of seed token.
    INV-6:  neutral option listing rule present; (Recommended) AFTER option label.
    INV-7:  default no-flag path unchanged (MODE_FLAG defaults to 'default').
    """

    @pytest.fixture
    def skill_md(self):
        skills_dir = Path(__file__).parent.parent / ".claude" / "skills"
        path = skills_dir / "map-review" / "SKILL.md"
        assert path.exists(), "map-review/SKILL.md not found"
        return path.read_text()

    # --- AC-9: argument-hint and Step 0 flag parsing ---

    def test_vc9_argument_hint_lists_new_flags(self, skill_md):
        """AC-9: argument-hint frontmatter must include all four new flags."""
        # Extract frontmatter argument-hint line
        hint_match = re.search(r'^argument-hint:\s*"([^"]+)"', skill_md, re.MULTILINE)
        assert hint_match, "argument-hint field not found in frontmatter"
        hint = hint_match.group(1)
        for flag in ("--reverse-sections", "--shuffle-sections", "--seed", "--compare-orderings"):
            assert flag in hint, (
                f"argument-hint missing '{flag}' (AC-9). Current hint: {hint!r}"
            )

    def test_vc9_step0_parses_reverse_sections(self, skill_md):
        """AC-9: Step 0 must contain bash parsing block for --reverse-sections."""
        assert "--reverse-sections" in skill_md, (
            "Step 0 does not parse --reverse-sections flag (AC-9)"
        )
        assert "REVERSE_FLAG" in skill_md, (
            "Step 0 does not set REVERSE_FLAG variable for --reverse-sections (AC-9)"
        )

    def test_vc9_step0_parses_shuffle_sections(self, skill_md):
        """AC-9: Step 0 must contain bash parsing block for --shuffle-sections."""
        assert "--shuffle-sections" in skill_md, (
            "Step 0 does not parse --shuffle-sections flag (AC-9)"
        )
        assert "SHUFFLE_FLAG" in skill_md, (
            "Step 0 does not set SHUFFLE_FLAG variable for --shuffle-sections (AC-9)"
        )

    def test_vc9_step0_parses_seed_flag(self, skill_md):
        """AC-9: Step 0 must parse --seed using grep/sed pattern (EC-16: no $(...)-expansion)."""
        assert "--seed" in skill_md, (
            "Step 0 does not parse --seed flag (AC-9)"
        )
        assert "SEED_RAW" in skill_md, (
            "Step 0 does not set SEED_RAW variable for --seed (AC-9 / EC-16)"
        )
        # EC-16: extraction must use sed pattern-match, not eval or bare $()
        assert "sed -nE" in skill_md or "sed -n" in skill_md, (
            "Step 0 --seed extraction must use sed for pattern-matched extraction (EC-16)"
        )
        # EC-16: the regex must constrain to digits only
        assert "[0-9]" in skill_md, (
            "Step 0 --seed sed pattern must constrain to [0-9]+ digits (EC-16)"
        )

    def test_vc9_step0_parses_compare_orderings(self, skill_md):
        """AC-9: Step 0 must contain bash parsing block for --compare-orderings."""
        assert "--compare-orderings" in skill_md, (
            "Step 0 does not parse --compare-orderings flag (AC-9)"
        )
        assert "COMPARE_FLAG" in skill_md, (
            "Step 0 does not set COMPARE_FLAG variable for --compare-orderings (AC-9)"
        )

    # --- AC-10 / INV-6: neutral option presentation; (Recommended) marker after label ---

    def test_vc10_anchoring_footgun_removed(self, skill_md):
        """AC-10 / INV-6: literal phrase 'Recommended option is always listed first' must be absent."""
        assert "Recommended option is always listed first" not in skill_md, (
            "AC-10/INV-6: anchoring phrase 'Recommended option is always listed first' "
            "must be removed from SKILL.md"
        )

    def test_vc10_neutral_listing_rule_present(self, skill_md):
        """INV-6: SKILL.md must describe neutral A/B/C listing with (Recommended) AFTER the label."""
        lower = skill_md.lower()
        # Must mention neutral listing
        has_neutral = "neutral" in lower or "a/b/c" in lower
        assert has_neutral, (
            "INV-6: SKILL.md must describe neutral option listing (A/B/C) — not found"
        )
        # (Recommended) marker must appear after option label, not before
        assert "(Recommended)" in skill_md, (
            "INV-6: '(Recommended)' marker text must be present in SKILL.md"
        )

    def test_vc10_ci_uses_marker_not_position(self, skill_md):
        """AC-10 / INV-11: CI auto-select must identify recommended option by (Recommended) marker,
        not by positional index (e.g., 'first option')."""
        lower = skill_md.lower()
        # Must mention marker-based selection
        has_marker_select = (
            "recommended) marker" in lower
            or "recommended) substring" in lower
            or "(recommended)" in lower and "scan" in lower
            or "(recommended)" in lower and "marker" in lower
        )
        assert has_marker_select, (
            "AC-10/INV-11: CI auto-select must use (Recommended) marker lookup, "
            "not positional index — explicit marker-based selection wording not found"
        )

    # --- AC-11: Phase B iterates helper-returned order; "next section" wording ---

    def test_vc11_phase_b_calls_shuffle_sections_helper(self, skill_md):
        """AC-11: Phase B must call shuffle-sections helper to determine section order."""
        assert "shuffle-sections" in skill_md, (
            "AC-11: Phase B must reference 'shuffle-sections' helper call to get section order"
        )
        assert "SECTIONS_JSON" in skill_md, (
            "AC-11: Phase B must capture result of shuffle-sections into SECTIONS_JSON variable"
        )

    def test_vc11_no_hardcoded_section_n_plus_1(self, skill_md):
        """AC-11: 'Section 2', 'Section 3', 'Section 4' hand-off phrasing must be absent."""
        for phrase in ("Section 2", "Section 3", "Section 4"):
            assert phrase not in skill_md, (
                f"AC-11: hardcoded '{phrase}' hand-off reference found — "
                "replace with 'next section' wording"
            )

    def test_vc11_next_section_wording_present(self, skill_md):
        """AC-11: 'next section' wording must appear in Phase B summaries."""
        assert "next section" in skill_md, (
            "AC-11: 'next section' wording must replace 'Section N+1' in Phase B hand-offs"
        )

    # --- AC-12: --compare-orderings flow ---

    def test_vc12_compare_mode_runs_agents_twice(self, skill_md):
        """AC-12: SKILL.md must describe launching agents with default order AND reverse order."""
        has_default_run = "ordering_label" in skill_md and "'default'" in skill_md
        has_reverse_run = "ordering_label" in skill_md and "'reverse'" in skill_md
        assert has_default_run, (
            "AC-12: compare-mode must document default-order agent run with ordering_label='default'"
        )
        assert has_reverse_run, (
            "AC-12: compare-mode must document reverse-order agent run with ordering_label='reverse'"
        )

    def test_vc12_compare_mode_calls_compare_review_runs(self, skill_md):
        """AC-12: SKILL.md must instruct calling compare-review-runs to aggregate drift."""
        assert "compare-review-runs" in skill_md, (
            "AC-12: SKILL.md must call compare-review-runs to aggregate compare-mode results"
        )

    def test_vc12_compare_mode_calls_record_review_ordering(self, skill_md):
        """AC-12: SKILL.md must instruct calling record-review-ordering to stage the payload."""
        assert "record-review-ordering" in skill_md, (
            "AC-12: SKILL.md must call record-review-ordering after compare aggregation"
        )

    # --- EC-1/EC-17: mutual exclusion ---

    def test_ec1_ec17_mutual_exclusion_block_present(self, skill_md):
        """EC-1/EC-17: SKILL.md must have a structured-error exit when both
        --compare-orderings and --shuffle-sections are set."""
        assert "EC-1/EC-17" in skill_md or (
            "cannot combine" in skill_md.lower() and "compare-orderings" in skill_md
        ), (
            "EC-1/EC-17: mutual exclusion error block for --compare-orderings + "
            "--shuffle-sections not found in SKILL.md"
        )
        # Must have an exit 1 path
        assert "exit 1" in skill_md, (
            "EC-1/EC-17: mutual exclusion block must contain 'exit 1' to abort the workflow"
        )

    # --- EC-15: prepare_detached_review called exactly once ---

    def test_ec15_detached_worktree_prepared_once(self, skill_md):
        """EC-15: the actual bash invocation of prepare_detached_review must appear
        exactly once in SKILL.md (prose mentions and comments don't count),
        and the EC-15 note about single-prep reuse must be present."""
        # Count only the actual CLI invocation line, not prose or comment mentions
        invocation_count = skill_md.count("map_step_runner.py prepare_detached_review")
        assert invocation_count == 1, (
            f"EC-15: 'map_step_runner.py prepare_detached_review' CLI invocation must "
            f"appear exactly once in SKILL.md (found {invocation_count} occurrences). "
            "EC-15 requires a single-prep shared across compare runs."
        )
        assert "EC-15" in skill_md, (
            "EC-15: a comment/note referencing EC-15 must be present near "
            "the prepare_detached_review call"
        )

    # --- INV-7: default no-flag path uses MODE_FLAG='default' ---

    def test_inv7_default_mode_flag_is_default(self, skill_md):
        """INV-7: MODE_FLAG must default to 'default' so no-flag invocation is unchanged."""
        assert 'MODE_FLAG="default"' in skill_md or "MODE_FLAG='default'" in skill_md, (
            "INV-7: Step 0 must set MODE_FLAG to 'default' as the base value so that "
            "plain /map-review (no flags) uses canonical section order"
        )
