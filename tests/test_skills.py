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
- Non-release workflow prompts avoid blanket all-caps prohibition blocks
"""

import json
import re
import shlex
from pathlib import Path
from typing import ClassVar

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

WORKFLOW_EFFORT_PROFILES = {
    "map-fast": "low/direct",
    "map-check": "low/direct",
    "map-resume": "low/direct",
    "map-efficient": "medium/adaptive",
    "map-task": "medium/adaptive",
    "map-debug": "medium/adaptive",
    "map-tdd": "medium/adaptive",
    "map-learn": "medium/adaptive",
    "map-explain": "medium/adaptive",
    "map-understand": "medium/adaptive",
    "map-wayfind": "medium/adaptive",
    "map-architecture": "medium/adaptive",
    "map-plan": "high/adaptive",
    "map-review": "high/adaptive",
    "map-release": "high/adaptive",
}

PROMPT_TONE_EXEMPT_SKILLS = {"map-release"}

BLANKET_PROHIBITION_PHRASES = [
    "ABSOLUTELY FORBIDDEN",
    "STRICTLY PROHIBITED",
    "NO ADDITIONAL OPTIMIZATION ALLOWED",
    "CRITICAL INSTRUCTION",
    "YOU MUST:",
]

SCOPE_CONTROL_SKILLS = ["map-fast", "map-check", "map-resume", "map-task"]

HIGH_TRAFFIC_COMPACT_SKILL_REFS = {
    "map-plan": "plan-reference.md",
    "map-efficient": "efficient-reference.md",
    "map-review": "review-reference.md",
    "map-check": "check-reference.md",
}

# Per-skill active-body line budget for the always-loaded SKILL.md (it costs
# context on every invocation). Default history: 500→502→504→508→515 (see the
# justification comment at the assertion). `map-review` carries THREE review
# modes in one body — the default 4-section walkthrough PLUS the `--adversarial`
# phase PLUS the `--cross-ai` (#288) phase — so it gets a deliberately higher cap
# than the single-mode skills. Per the learned 'always-loaded skill body line
# budget' rule: bump the budget, do NOT gut active control flow to fit (the
# cross-AI status protocol and egress rationale already live in
# review-reference.md; what remains is the irreducible flag/dispatch/branch flow).
# Budget bumped from 508 → 515 (#284): the opt-in worktree-isolation wiring adds
# the irreducible active branches in map-efficient/SKILL.md — create-before-Actor,
# the merge_subtask_worktree accept branch replacing the per-subtask commit, and
# the discard_subtask_worktree reject branch on valid=false. The full recipe
# (bash, guard `kind`s, Actor path instruction) lives in efficient-reference.md.
# Budget bumped from 560 → 630 (#406): the ledger is a gate, so its active steps
# have to live in the invoked body — Step A.2c writes each reviewer envelope to
# .map/<branch>/review-agent-<role>.json (the ledger reads nothing else) and
# needs a literal mkdir plus one quoted-heredoc example, or an agent following
# the step produces no envelopes at all; and the closeout builds the mode-aware
# argument list and takes FINAL_VERDICT from the ledger output instead of letting
# the model pick one. The status table, the objection channels, the
# self-attestation rationale and the MAP_REVIEW_LEDGER_ENFORCE hatch all live in
# review-reference.md § Verdict Ledger and are NOT counted here.
_DEFAULT_SKILL_BODY_BUDGET = 515
HIGH_TRAFFIC_SKILL_BODY_BUDGETS = {
    "map-review": 630,
    # map-tdd carries Iron Law enforcement (rationalization table, Red Flags,
    # RED-GREEN-REFACTOR cycle), spec compliance reviewer dispatch, and code
    # quality reviewer dispatch — all irreducible active control flow (#285).
    "map-tdd": 545,
}

CLAUDE_MUTATION_BOUNDARY_SURFACES = [
    Path("agents") / "actor.md",
    Path("skills") / "map-fast" / "SKILL.md",
    Path("skills") / "map-efficient" / "SKILL.md",
    Path("skills") / "map-task" / "SKILL.md",
    Path("skills") / "map-debug" / "SKILL.md",
]

CODEX_MUTATION_BOUNDARY_SURFACES = [
    Path("AGENTS.md"),
    Path("skills") / "map-fast" / "SKILL.md",
    Path("skills") / "map-efficient" / "SKILL.md",
]

MUTATION_BOUNDARY_REQUIRED_PHRASES = [
    "Do not edit unrelated files",
    "Do not add, remove, or upgrade dependencies",
    "refactor neighboring code",
    "report it as a blocker/tradeoff",
]

MUTATION_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:Apply changes directly|Use Edit/Write|Implement exactly|"
    r"Implement this subtask|Implement a fix|Apply the fix directly|make changes)\b",
    re.IGNORECASE,
)

PROMPT_TONE_SKILL_ROOTS = [
    Path(".claude") / "skills",
    Path("src") / "mapify_cli" / "templates" / "skills",
]

CLAUDE_SKILL_EFFORT_LEVELS = {
    skill_name: profile.split("/", maxsplit=1)[0]
    for skill_name, profile in WORKFLOW_EFFORT_PROFILES.items()
}

JSON_OUTPUT_PATTERN = re.compile(r"\bOutput JSON with:\*?", re.IGNORECASE)
JSON_CONTRACT_REFERENCE_PATTERN = re.compile(
    r"JSON contract reference: \[[^\]]+\]"
    r"\(\.\./\.\./references/map-json-output-contracts\.md#[^)]+\)"
)
EVIDENCE_FIRST_JSON_PATTERN = re.compile(
    r"(?:evidence|quotes): array of \{[^\n]+(?:quote|relevance)[^\n]+\}"
    r".*(?:before|cite|quote|include)",
    re.IGNORECASE | re.DOTALL,
)


def _json_output_contract_contexts(content: str) -> list[tuple[int, str]]:
    lines = content.splitlines()
    contexts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if JSON_OUTPUT_PATTERN.search(line):
            start = max(0, index - 5)
            end = min(len(lines), index + 8)
            contexts.append((index + 1, "\n".join(lines[start:end])))
    return contexts


def _has_json_contract_backing(context: str) -> bool:
    return bool(
        JSON_CONTRACT_REFERENCE_PATTERN.search(context)
        or EVIDENCE_FIRST_JSON_PATTERN.search(context)
    )


def _shell_invocations(content: str, subcommand: str) -> list[list[str]]:
    """Return the positional args of every shell call to ``subcommand``.

    Joins backslash-continued lines so multi-line runner invocations are parsed
    as one command; returns the tokens that follow ``subcommand``.
    """
    invocations: list[list[str]] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if f" {subcommand}" not in line:
            index += 1
            continue
        command = line
        while command.rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            command = command.rstrip().removesuffix("\\") + " " + lines[index].strip()
        tokens = shlex.split(command, comments=True)
        invocations.append(tokens[tokens.index(subcommand) + 1 :])
        index += 1
    return invocations


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
        """Descriptions must fit the Agent Skills `description` spec limit (1024 chars).

        The 1024-char cap is the documented Agent Skills maximum for the
        `description` field (the official skill-creator validates against it too).
        It is NOT the old 250-char number: Claude Code truncated descriptions at
        250 in v2.1.86, raised the cap to 1536 in v2.1.105, then removed the
        per-description cap in v2.1.129+ (usage-ranked listing budget). So 250 was
        a transient version cap; current Claude Code loads the full description
        (up to the spec's 1024) for triggering.
        Refs: github.com/anthropics/claude-code issues #40121 / #47627;
        code.claude.com/docs/en/skills.
        """
        for folder in skill_folders:
            skill_file = skills_dir / folder / "SKILL.md"
            fm = self._parse_frontmatter(skill_file)
            desc = fm.get("description", "")
            assert len(desc) <= 1024, (
                f"Skill '{folder}' description is {len(desc)} chars; "
                "keep it at or under the 1024-char Agent Skills spec limit."
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

    def test_task_skills_have_effort_and_parallelism_policy(
        self, skills_dir, template_skills_dir
    ):
        """Manual workflow skills should calibrate reasoning and parallel fan-out."""
        for base_dir in (skills_dir, template_skills_dir):
            for skill_name, profile in WORKFLOW_EFFORT_PROFILES.items():
                skill_file = base_dir / skill_name / "SKILL.md"
                assert skill_file.exists(), f"Missing skill file: {skill_file}"
                content = skill_file.read_text()
                frontmatter = self._parse_frontmatter(skill_file)
                expected_effort = CLAUDE_SKILL_EFFORT_LEVELS[skill_name]

                assert "## Effort and Parallelism Policy" in content, (
                    f"{skill_file} must define an effort/parallelism policy so "
                    "provider prompts do not overthink or over-parallelize."
                )
                assert frontmatter.get("effort") == expected_effort, (
                    f"{skill_file} should set Claude Code effort: "
                    f"{expected_effort}"
                )
                assert f"thinking_policy: {profile}" in content, (
                    f"{skill_file} should declare thinking_policy: {profile}"
                )
                assert "parallel_tool_policy:" in content, (
                    f"{skill_file} should declare a parallel_tool_policy."
                )

    def test_map_resume_keeps_recovery_skill_body_compact(
        self, skills_dir, template_skills_dir
    ):
        """Resume is used after context loss, so its invoked body must stay lean."""
        for base_dir in (skills_dir, template_skills_dir):
            skill_file = base_dir / "map-resume" / "SKILL.md"
            reference_file = base_dir / "map-resume" / "resume-reference.md"
            content = skill_file.read_text()

            assert len(content.splitlines()) <= 350, (
                f"{skill_file} should keep the active recovery flow compact; "
                "move low-frequency examples or troubleshooting to supporting files."
            )
            assert "[resume-reference.md](resume-reference.md)" in content, (
                f"{skill_file} should point to the bundled supporting reference."
            )
            assert reference_file.exists(), (
                f"{reference_file} should hold detailed resume examples and troubleshooting."
            )
            reference = reference_file.read_text()
            assert "## Examples" in reference
            assert "## Troubleshooting" in reference

    def test_high_traffic_workflow_skills_keep_active_bodies_compact(
        self, skills_dir, template_skills_dir
    ):
        """Common workflows should keep invoked bodies lean and navigate to references."""
        for base_dir in (skills_dir, template_skills_dir):
            for skill_name, reference_name in HIGH_TRAFFIC_COMPACT_SKILL_REFS.items():
                skill_file = base_dir / skill_name / "SKILL.md"
                reference_file = base_dir / skill_name / reference_name
                content = skill_file.read_text(encoding="utf-8")

                # Budget bumped from 500 → 502: C2 fence addition (ST-011) added
                # <!-- map:start --> and <!-- map:end --> (2 lines) to every SKILL.md.
                # Budget bumped from 502 → 504 (#236): one persistent recover-from-
                # offloaded-sidecar line was added to each of the Actor and Monitor
                # dispatched <task> prompts in map-efficient/SKILL.md. These are the
                # actual agent prompt bodies, so they cannot move to the reference file.
                # Budget bumped from 504 → 508 (#253): the intra-run failure-memory
                # wiring adds one MANDATORY `record_failure_signature` bullet on the
                # valid=false path and a `set_anti_repeat_subtask_status succeeded`
                # clause on the clean-pass record — both are the active retry-loop
                # control flow (full recipe lives in efficient-reference.md, not here).
                # Do NOT remove content to fit — bump the budget instead (per learned rule
                # 'always-loaded skill body line budget'). The cap is per-skill:
                # single-mode skills stay at the 508 default; map-review's higher cap
                # is justified at HIGH_TRAFFIC_SKILL_BODY_BUDGETS (three review modes).
                budget = HIGH_TRAFFIC_SKILL_BODY_BUDGETS.get(
                    skill_name, _DEFAULT_SKILL_BODY_BUDGET
                )
                assert len(content.splitlines()) <= budget, (
                    f"{skill_file} should keep the active workflow path compact "
                    f"(budget {budget} lines); move examples, rationale, and "
                    "troubleshooting into supporting files."
                )
                assert f"[{reference_name}]({reference_name})" in content, (
                    f"{skill_file} should point to its bundled supporting reference."
                )
                assert "supporting files are not assumed to be in context automatically" in content, (
                    f"{skill_file} should make supporting-reference loading explicit."
                )
                assert reference_file.exists(), (
                    f"{reference_file} should hold low-frequency workflow material."
                )
                reference = reference_file.read_text(encoding="utf-8")
                assert "## Examples" in reference
                assert "## Troubleshooting" in reference

    def test_write_capable_claude_surfaces_have_constraint_first_boundaries(
        self, project_root
    ):
        """Write-capable Claude surfaces must block silent scope expansion."""
        for root in (
            project_root / ".claude",
            project_root / "src" / "mapify_cli" / "templates",
        ):
            for relative_path in CLAUDE_MUTATION_BOUNDARY_SURFACES:
                surface = root / relative_path
                content = surface.read_text(encoding="utf-8")

                assert "## Mutation Boundary Constraints" in content, (
                    f"{surface} must declare mutation boundary constraints before "
                    "write-capable instructions."
                )
                for phrase in MUTATION_BOUNDARY_REQUIRED_PHRASES:
                    assert phrase in content, (
                        f"{surface} must include constraint-first guardrail: {phrase}"
                    )

                constraint_index = content.index("## Mutation Boundary Constraints")
                directive_match = MUTATION_DIRECTIVE_PATTERN.search(content)
                assert directive_match is None or constraint_index < directive_match.start(), (
                    f"{surface} should present scope/dependency constraints before "
                    "broad write directives."
                )

    def test_write_capable_codex_surfaces_have_mutation_boundaries(
        self, project_root
    ):
        """Installed Codex scaffolds need the same unrelated-edit/dependency guardrail."""
        codex_root = project_root / "src" / "mapify_cli" / "templates" / "codex"
        for relative_path in CODEX_MUTATION_BOUNDARY_SURFACES:
            surface = codex_root / relative_path
            content = surface.read_text(encoding="utf-8")

            assert "## Mutation Boundary Constraints" in content, (
                f"{surface} must declare mutation boundary constraints."
            )
            for phrase in MUTATION_BOUNDARY_REQUIRED_PHRASES:
                assert phrase in content, (
                    f"{surface} must include constraint-first guardrail: {phrase}"
                )

            constraint_index = content.index("## Mutation Boundary Constraints")
            directive_match = MUTATION_DIRECTIVE_PATTERN.search(content)
            assert directive_match is None or constraint_index < directive_match.start(), (
                f"{surface} should present scope/dependency constraints before "
                "broad write directives."
            )

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

    def test_vc1_vc2_map_so_search_hybrid_runtimeeffects(self, skill_rules):
        """VC1/VC2 [AC-5]: map-so-search is registered as skillClass=hybrid with
        runtimeEffects EXACTLY {network-http-read, filesystem-sofa-credentials}."""
        entry = skill_rules.get("skills", {}).get("map-so-search")
        assert entry is not None, "map-so-search missing from skill-rules.json"
        assert entry.get("skillClass") == "hybrid", (
            f"map-so-search skillClass must be 'hybrid', got {entry.get('skillClass')!r}"
        )
        assert sorted(entry.get("runtimeEffects", [])) == [
            "filesystem-sofa-credentials",
            "network-http-read",
        ], (
            "map-so-search runtimeEffects must be exactly "
            "['network-http-read', 'filesystem-sofa-credentials'] (no extras, no omissions); "
            f"got {entry.get('runtimeEffects')!r}"
        )

    def test_map_understand_is_transient_task_skill(self, skill_rules):
        """Issue #221: the understanding quiz surface is opt-in and has no runtime effects."""
        entry = skill_rules.get("skills", {}).get("map-understand")
        assert entry is not None, "map-understand missing from skill-rules.json"
        assert entry.get("type") == "manual"
        assert entry.get("skillClass") == "task"
        assert entry.get("enforcement") == "manual"
        assert not entry.get("runtimeEffects")

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
                    f"Run: make render-templates"
                )
            assert source.read_text() == target.read_text(), (
                f"Skill '{folder}/SKILL.md' differs between .claude/skills/ and templates/skills/. "
                f"Run: make render-templates"
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
            "Run: make render-templates"
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
                # Python bytecode caches are generated artifacts (a test that
                # imports a rendered skill script writes them into .claude/),
                # never shipped supporting files — exclude them from the sync.
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
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
                "and templates/skills/. Run: make render-templates"
            )

    # --- Validation script tests ---

    def test_validation_scripts_are_executable(self, skills_dir, skill_folders):
        """Scripts in skill scripts/ directories should be executable."""
        for folder in skill_folders:
            scripts_dir = skills_dir / folder / "scripts"
            if not scripts_dir.exists():
                continue
            for script in scripts_dir.iterdir():
                # Check file has executable permission or is a python script
                if script.is_file() and script.suffix in (".sh", ".py") and script.suffix == ".sh":
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


class TestPromptToneCalibration:
    """Regression tests for Claude 4.6+ prompt overtriggering calibration."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    @pytest.mark.parametrize("skill_name", sorted(WORKFLOW_EFFORT_PROFILES))
    def test_non_release_skills_avoid_blanket_prohibition_blocks(
        self, project_root, skill_name, skills_root
    ):
        if skill_name in PROMPT_TONE_EXEMPT_SKILLS:
            pytest.skip("Release keeps explicit hard-stop language for tag/PyPI safety")

        skill_md = project_root / skills_root / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        for phrase in BLANKET_PROHIBITION_PHRASES:
            assert phrase not in content, (
                f"{skill_name} should use targeted workflow guardrails instead of "
                f"blanket prompt language: {phrase!r}"
            )

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    @pytest.mark.parametrize("skill_name", SCOPE_CONTROL_SKILLS)
    def test_lightweight_and_resume_skills_have_scope_control_clause(
        self, project_root, skill_name, skills_root
    ):
        skill_md = project_root / skills_root / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "## When Not To Expand Scope" in content
        scope_section = content.split("## When Not To Expand Scope", maxsplit=1)[1]
        scope_section = scope_section.split("\n## ", maxsplit=1)[0]

        assert "Do not" in scope_section
        assert any(
            marker in scope_section
            for marker in ("switch to", "hand off", "current checkpoint", "selected subtask")
        ), f"{skill_name} scope clause should name the correct off-ramp or boundary"


class TestXMLPromptEnvelopeContracts:
    """Regression tests for long-context MAP subagent prompt structure."""

    XML_ENVELOPE_SKILLS: ClassVar[list] = ["map-plan", "map-efficient", "map-debug", "map-review"]

    def _map_review_prompt_source(self, project_root, skills_root):
        if str(skills_root).startswith(".claude"):
            return project_root / ".map" / "scripts" / "map_step_runner.py"
        return (
            project_root
            / "src"
            / "mapify_cli"
            / "templates"
            / "map"
            / "scripts"
            / "map_step_runner.py"
        )

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    @pytest.mark.parametrize("skill_name", XML_ENVELOPE_SKILLS)
    def test_high_context_skills_link_xml_envelope_reference(
        self, project_root, skills_root, skill_name
    ):
        skill_md = project_root / skills_root / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "../../references/map-xml-prompt-envelopes.md" in content, (
            f"{skill_name} should link the shared XML envelope reference so "
            "maintainers preserve the prompt layout in generated skills."
        )

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    @pytest.mark.parametrize("skill_name", XML_ENVELOPE_SKILLS)
    def test_high_context_subagent_prompts_use_xml_envelope_tags(
        self, project_root, skills_root, skill_name
    ):
        skill_md = project_root / skills_root / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        prompt_content = content
        if skill_name == "map-review":
            prompt_content = self._map_review_prompt_source(
                project_root, skills_root
            ).read_text(encoding="utf-8")

        for tag in ("<documents>", "<task>", "<expected_output>"):
            assert tag in prompt_content, (
                f"{skill_name} should use {tag} in long subagent prompts "
                "so artifacts, task, and output schema stay unambiguous."
            )

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    def test_map_review_reviewer_prompts_put_bundle_before_instructions(
        self, project_root, skills_root
    ):
        skill_md = project_root / skills_root / "map-review" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        launch_section = content.split("### Step A.2: Launch all parallel calls", maxsplit=1)[1]
        launch_section = launch_section.split("### Hard Stop Check", maxsplit=1)[0]
        prompt_source = self._map_review_prompt_source(
            project_root, skills_root
        ).read_text(encoding="utf-8")

        assert "build_review_prompts" in launch_section
        assert launch_section.index("build_review_prompts") < launch_section.index("Task(")
        assert prompt_source.count('"subagent_type"') >= 3
        assert "priority='primary'" in prompt_source
        assert "<workflow_policy>" in prompt_source
        assert prompt_source.index("<documents>") < prompt_source.index("<instructions>")

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    def test_map_efficient_actor_and_monitor_put_artifacts_before_task(
        self, project_root, skills_root
    ):
        skill_md = project_root / skills_root / "map-efficient" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        for start_heading, end_heading in (
            ("### Phase: ACTOR (2.3)", "### Phase: MONITOR (2.4)"),
            ("### Phase: MONITOR (2.4)", "# After Monitor returns:"),
        ):
            section = content.split(start_heading, maxsplit=1)[1]
            section = section.split(end_heading, maxsplit=1)[0]
            assert section.index("<documents>") < section.index("<task>"), (
                f"{start_heading} should put context artifacts before the task "
                "so long-context inputs are read before instructions."
            )

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    def test_map_efficient_actor_expected_output_instructs_json_envelope(
        self, project_root, skills_root
    ):
        """Regression for #227: the ACTOR <expected_output> must instruct a
        strict JSON envelope so the prompt AGREES with the actor-mode
        truncation gate (`detect_truncated_agent_output --agent actor`), which
        requires a JSON object with the AGENT_OUTPUT_SCHEMAS["actor"] keys. The
        prior prose form ("Return files_changed, tests_run, validation_notes,
        and any blocker.") parsed as non-JSON, so the gate false-flagged every
        clean Actor response as truncated and forced needless re-invokes.
        """
        import sys

        scripts_path = (
            project_root
            / "src"
            / "mapify_cli"
            / "templates"
            / "map"
            / "scripts"
        )
        if str(scripts_path) not in sys.path:
            sys.path.insert(0, str(scripts_path))
        import map_step_runner  # type: ignore[import-not-found]

        actor_required = tuple(
            map_step_runner.AGENT_OUTPUT_SCHEMAS["actor"]["required_keys"]
        )

        skill_md = project_root / skills_root / "map-efficient" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        actor_section = content.split("### Phase: ACTOR (2.3)", maxsplit=1)[1]
        actor_section = actor_section.split(
            "### Actor truncated-response gate", maxsplit=1
        )[0]
        expected_output = actor_section.split("<expected_output>", maxsplit=1)[1]
        expected_output = expected_output.split("</expected_output>", maxsplit=1)[0]

        # Must instruct a strict JSON object (mirrors the MONITOR contract), so
        # the truncation detector's JSON parse succeeds on a complete response.
        assert "JSON" in expected_output, (
            "ACTOR <expected_output> must instruct a JSON envelope so it agrees "
            "with detect_truncated_agent_output --agent actor (requires JSON)."
        )
        assert "ONLY" in expected_output, (
            "ACTOR <expected_output> must require ONLY a JSON object (no prose "
            "before/after) so the truncation detector parses it cleanly."
        )
        # Every detector-required actor key must be named in the prompt — this
        # is the single-source contract the gate enforces.
        for key in actor_required:
            assert key in expected_output, (
                f"ACTOR <expected_output> must name the '{key}' field required "
                "by AGENT_OUTPUT_SCHEMAS['actor']."
            )

    @pytest.mark.parametrize("skills_root", PROMPT_TONE_SKILL_ROOTS)
    def test_map_efficient_actor_monitor_recover_offloaded_outputs(
        self, project_root, skills_root
    ):
        """Regression for #236: the Actor and Monitor dispatched <task> prompts
        must carry persistent guidance to recover offloaded tool outputs from the
        compaction manifest (#232) instead of re-running broad discovery, while
        still defaulting to live source/tests for current correctness. The
        post-compact hook pointer is ephemeral (re-primes the next turn only);
        without these prompt lines the recover-before-rediscover behavior does
        not survive across turns.
        """
        skill_md = project_root / skills_root / "map-efficient" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        def _task_block(section_start: str, section_end: str) -> str:
            section = content.split(section_start, maxsplit=1)[1]
            section = section.split(section_end, maxsplit=1)[0]
            task = section.split("<task>", maxsplit=1)[1]
            return task.split("</task>", maxsplit=1)[0]

        actor_task = _task_block(
            "### Phase: ACTOR (2.3)", "### Actor truncated-response gate"
        )
        # Recovery entry point is scoped to "re-running broad discovery" — not an
        # unconditional "always check the manifest first".
        assert "compacted/MANIFEST.md" in actor_task, (
            "ACTOR <task> must point at .map/<branch>/compacted/MANIFEST.md so the "
            "agent can recover offloaded tool outputs instead of re-running broad "
            "discovery (#236)."
        )
        # The staleness guard must DEFAULT to sidecar reuse and re-run only on a
        # concrete positive signal — guards against over-trust AND over-rediscovery.
        assert "re-run the tool only when" in actor_task, (
            "ACTOR <task> must gate re-running on a concrete staleness signal so "
            "the default is sidecar reuse, not over-eager re-discovery (#236)."
        )

        monitor_task = _task_block(
            "### Phase: MONITOR (2.4)", "# After Monitor returns:"
        )
        assert "never as sole proof of correctness" in monitor_task, (
            "MONITOR <task> must forbid basing a verdict solely on an offloaded "
            "sidecar (#236)."
        )
        assert "live source and a current test run" in monitor_task, (
            "MONITOR <task> must ground every verdict in live source and a current "
            "test run — not a stale snapshot (#236)."
        )


class TestContractSizedSubtaskSkillContracts:
    """Regression tests for user-visible subtask size and concern guardrails."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize("skill_name", ["map-plan", "map-efficient"])
    def test_planning_prompts_require_contract_size_metadata(
        self, project_root, skill_name
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "expected_diff_size" in content
        assert "concern_type" in content
        assert "one_logical_step" in content
        assert "split_rationale" in content
        assert "concern_justification" in content
        assert "coverage_map" in content
        assert "hard_constraints" in content
        assert "soft_constraints" in content

    @pytest.mark.parametrize("skill_name", ["map-plan", "map-efficient"])
    def test_planning_prompts_run_blueprint_contract_validator(
        self, project_root, skill_name
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "validate_blueprint_contract" in content

    @pytest.mark.parametrize("skill_name", ["map-plan", "map-efficient"])
    def test_planning_prompts_require_coverage_ids_in_validation_criteria(
        self, project_root, skill_name
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "coverage_map" in content
        assert "validation_criteria" in content
        assert "[AC-1]" in content
        assert "bracket" in content.lower()
        assert "hard_constraints" in content
        assert "tradeoff_rationale" in content

    def test_map_plan_human_plan_surfaces_scope_metadata(self, project_root):
        skill_md = project_root / ".claude" / "skills" / "map-plan" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "**Expected Diff Size:**" in content
        assert "**Concern Type:**" in content
        assert "**One Logical Step:**" in content

    @pytest.mark.parametrize(
        "relative_path",
        [
            Path(".claude/agents/task-decomposer.md"),
            Path(".codex/agents/decomposer.toml"),
        ],
    )
    def test_decomposer_agent_schema_matches_blueprint_contract(
        self, project_root, relative_path
    ):
        content = (project_root / relative_path).read_text(encoding="utf-8")

        assert "coverage_map" in content
        assert "expected_diff_size" in content
        assert "concern_type" in content
        assert "one_logical_step" in content
        assert "split_rationale" in content
        assert "concern_justification" in content
        assert "[AC-1]" in content
        assert "hard_constraints" in content
        assert "soft_constraints" in content


class TestRunHealthCloseoutWiring:
    """Regression tests for auto-written run health reports in closeout prompts."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize(
        ("skill_name", "status_markers"),
        [
            (
                "map-efficient",
                ["complete", "pending", "blocked", "won't_do", "superseded"],
            ),
            (
                "map-debug",
                ["complete", "pending", "blocked", "won't_do", "superseded"],
            ),
            (
                "map-check",
                ["READY FOR REVIEW -> complete", "NEEDS WORK -> pending", "blocked"],
            ),
            (
                "map-review",
                ["PROCEED -> complete", "REVISE -> pending", "BLOCK -> blocked"],
            ),
        ],
    )
    def test_closeout_prompts_write_run_health_report(
        self, project_root, skill_name, status_markers
    ):
        skill_md = project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "write_run_health_report" in content
        # Accept both single-line and backslash-continued invocations (map-efficient
        # is line-budget-gated and uses the compact single-line form), but still
        # require the status variable rather than a hardcoded literal in either form.
        token_gap = r"\s+\\?\s*"
        assert re.search(
            "write_run_health_report" + token_gap + re.escape(skill_name)
            + token_gap + r'"\$RUN_HEALTH_STATUS"',
            content,
        ), f"{skill_name} must invoke write_run_health_report with $RUN_HEALTH_STATUS"
        assert not re.search(
            "write_run_health_report" + token_gap + re.escape(skill_name)
            + token_gap + r"""["']?(?:complete|pending|blocked|won't_do|superseded)\b""",
            content,
        ), f"{skill_name} must not hardcode a literal status into write_run_health_report"
        assert "run_health_report.json" in content
        assert "run_health" in content
        assert "RUN_HEALTH_STATUS" in content
        assert 'RUN_HEALTH_STATUS="complete"' not in content
        assert 'RUN_HEALTH_STATUS="${RUN_HEALTH_STATUS:?' in content
        for marker in status_markers:
            assert marker in content

    def test_map_efficient_writes_run_health_after_final_decision(self, project_root):
        skill_md = project_root / ".claude" / "skills" / "map-efficient" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert content.index("### 3.3 Evaluate Results") < content.index(
            "write_run_health_report"
        )

    def test_map_debug_writes_run_health_after_verification(self, project_root):
        skill_md = project_root / ".claude" / "skills" / "map-debug" / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert content.index("## Step 4: Verification") < content.index(
            "write_run_health_report"
        )


class TestEvidenceFirstVerdictContracts:
    """Regression tests for source-backed dismissal verdict requirements."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize(
        "relative_path",
        [
            Path(".claude/agents/monitor.md"),
            Path(".claude/agents/evaluator.md"),
            Path(".claude/agents/predictor.md"),
            Path(".claude/agents/documentation-reviewer.md"),
            Path(".claude/agents/final-verifier.md"),
            Path(".claude/skills/map-review/SKILL.md"),
            Path(".claude/skills/map-check/SKILL.md"),
        ],
    )
    def test_verdict_dismissals_require_source_evidence(
        self, project_root, relative_path
    ):
        content = (project_root / relative_path).read_text(encoding="utf-8")

        for term in (
            "false_positive",
            "covered",
            "out_of_scope",
            "pre_existing",
            "no_tests_needed",
            "safe_to_skip",
            "not_applicable",
        ):
            assert term in content
        assert "path:line" in content
        assert "confidence" in content
        assert "needs_investigation" in content

    @pytest.mark.parametrize(
        "relative_path",
        [
            Path(".claude/agents/monitor.md"),
            Path(".claude/agents/evaluator.md"),
            Path(".claude/agents/predictor.md"),
            Path(".claude/agents/documentation-reviewer.md"),
            Path(".claude/agents/final-verifier.md"),
            Path(".claude/skills/map-review/SKILL.md"),
            Path(".claude/skills/map-check/SKILL.md"),
        ],
    )
    def test_source_artifacts_are_authoritative(self, project_root, relative_path):
        content = (project_root / relative_path).read_text(encoding="utf-8").lower()

        assert "source" in content
        assert "tests" in content
        assert "configs" in content
        assert "transcripts" in content
        assert "summaries" in content


class TestMonitorMispruneGuardContracts:
    """Regression tests for issue #184 Monitor misprune guard context."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize(
        "relative_path",
        [
            Path(".claude/agents/monitor.md"),
            Path(".codex/agents/monitor.toml"),
        ],
    )
    def test_monitor_prompts_compare_against_approved_blueprint(
        self, project_root, relative_path
    ):
        content = (project_root / relative_path).read_text(encoding="utf-8")

        assert "Misprune guard" in content
        assert "Approved Blueprint Snapshot" in content
        assert "Active approved plan scope" in content
        assert "Rejected removals / Deferred YAGNI parking lot" in content
        assert "misprune" in content


class TestEvidenceFirstPromptContracts:
    """Regression tests for evidence-grounded agent outputs.

    These protect the user-visible review/debug/planning payoff from regressing
    back to unsupported verdicts or vague root-cause claims.
    """

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.mark.parametrize(
        ("skill_name", "required_terms"),
        [
            (
                "map-review",
                [
                    "Evidence-First Output Examples",
                    "evidence: array of {file_path, line_range, quote, relevance}",
                    "populate this before verdict fields",
                    "populate this before risk_assessment",
                    "populate this before scores",
                ],
            ),
            (
                "map-debug",
                [
                    "Evidence-First Output Examples",
                    "quotes: array of {source, locator, quote, relevance}",
                    "quote exact logs, test output, or code fragments before root_cause",
                    "cite the changed code or failing/passing test before verdict fields",
                    "include support for each similar issue or high-risk claim",
                ],
            ),
            (
                "map-plan",
                [
                    "Evidence-First Output Examples",
                    "Evidence first: for every finding",
                    "HIGH-severity findings must cite the exact spec section",
                    "Include an `evidence` array before `subtasks`",
                ],
            ),
        ],
    )
    def test_high_risk_agent_prompts_require_evidence_first_outputs(
        self, project_root, skill_name, required_terms
    ):
        content = (
            project_root / ".claude" / "skills" / skill_name / "SKILL.md"
        ).read_text(encoding="utf-8")
        if skill_name == "map-review":
            content += (
                project_root / ".map" / "scripts" / "map_step_runner.py"
            ).read_text(encoding="utf-8")

        for term in required_terms:
            assert term in content

    def test_shared_evidence_examples_cover_core_workflows(self, project_root):
        examples = (
            project_root / ".claude" / "references" / "map-output-examples.md"
        ).read_text(encoding="utf-8")

        assert "## Review Finding" in examples
        assert "## Debug Root Cause" in examples
        assert "## Spec Review Finding" in examples
        assert '"evidence"' in examples
        assert '"quotes"' in examples

    @pytest.mark.parametrize(
        "prompt_context",
        [
            """
JSON contract reference: [Decomposition Output](../../references/map-json-output-contracts.md#decomposition-output).

Output JSON with:
- subtasks: array of {id, description, acceptance_criteria, depends_on}
""",
            """
Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before verdict fields
- valid: boolean
""",
        ],
    )
    def test_json_contract_lint_accepts_backed_contracts(self, prompt_context):
        assert _has_json_contract_backing(prompt_context)

    def test_json_contract_lint_rejects_vague_contracts(self):
        prompt_context = """
Output JSON with:
- verdict: string
- summary: string
- risks: array of strings
"""

        assert not _has_json_contract_backing(prompt_context)

    @pytest.mark.parametrize(
        "skills_root",
        [
            Path(".claude") / "skills",
            Path("src") / "mapify_cli" / "templates" / "skills",
        ],
    )
    def test_every_json_prompt_contract_is_evidence_or_reference_backed(
        self, project_root, skills_root
    ):
        failures: list[str] = []
        for skill_file in sorted((project_root / skills_root).glob("*/SKILL.md")):
            content = skill_file.read_text(encoding="utf-8")
            for line_number, context in _json_output_contract_contexts(content):
                if not _has_json_contract_backing(context):
                    failures.append(
                        f"{skill_file.relative_to(project_root)}:{line_number}"
                    )

        assert not failures, (
            "Every `Output JSON with:` prompt contract must cite "
            "map-json-output-contracts.md or include evidence/quotes before "
            f"judgment fields. Missing backing: {', '.join(failures)}"
        )

    def test_shared_json_contract_reference_covers_non_evidence_contracts(
        self, project_root
    ):
        reference = (
            project_root / ".claude" / "references" / "map-json-output-contracts.md"
        ).read_text(encoding="utf-8")

        assert "## Decomposition Output" in reference
        assert "## Actor Change Summary" in reference
        assert "## Monitor Verdict" in reference
        assert "## Learning Summary" in reference


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

    def test_map_review_skill_builds_budgeted_prompts_before_agents(self, skill_md):
        """Review fan-out must use budgeted prompts before launching Task calls."""
        assert "build_review_prompts" in skill_md, (
            "map-review/SKILL.md must build bounded reviewer prompts"
        )
        prompt_pos = skill_md.index("build_review_prompts")
        task_pos = skill_md.index("Task(")
        assert prompt_pos < task_pos, (
            "build_review_prompts invocation must appear BEFORE the first Task( call "
            f"(prompt builder at {prompt_pos}, first Task( at {task_pos})"
        )
        assert "MAP_REVIEW_PROMPT_BUDGET_TOKENS" in skill_md
        assert "Review Prompt Budget" in skill_md
        assert "clips lower-priority raw diff" in skill_md

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

    def test_map_review_skill_stage_gate_calls_use_consistent_arg_positions(
        self, skill_md
    ):
        """Regression #388: every write_stage_gate call passes 4 positional args.

        The gate-unlock call used to pass the summary as the THIRD argument, so
        it silently landed in ``source_artifact`` instead of ``notes``.
        """
        calls = _shell_invocations(skill_md, "write_stage_gate")
        assert calls, "map-review/SKILL.md has no write_stage_gate invocation"
        for args in calls:
            assert len(args) == 4, (
                "write_stage_gate must be called as "
                f"<stage> <verdict> <source_artifact> <notes>; got {args}"
            )

    def test_map_review_skill_documents_verdict_normalization(self, skill_md):
        """Regression #388: SKILL.md must state how PROCEED/REVISE/BLOCK map to gates."""
        assert "needs-revision" in skill_md, (
            "map-review/SKILL.md must document the runner's gate verdict spellings"
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


class TestMapReviewComplexityLensWiring:
    """Regression tests for issue #182: advisory what-to-delete review lens."""

    @pytest.fixture
    def project_root(self):
        return Path(__file__).parent.parent

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-review/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-review/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_md(self, project_root, request):
        path = project_root / request.param
        assert path.exists(), f"{request.param} not found"
        return path.read_text(encoding="utf-8")

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-review/review-reference.md"),
            Path("src/mapify_cli/templates/skills/map-review/review-reference.md"),
        ],
        ids=["dev-ref", "template-ref"],
    )
    def reference_md(self, project_root, request):
        path = project_root / request.param
        assert path.exists(), f"{request.param} not found"
        return path.read_text(encoding="utf-8")

    def test_skill_runs_complexity_lens_only_as_advisory(self, skill_md):
        for token in (
            "COMPLEXITY_LENS_ENABLED",
            "minimality != off",
            "delete:",
            "stdlib:",
            "native:",
            "yagni:",
            "shrink:",
            "net: -<N> lines possible.",
            "Lean already. Ship.",
            "map:simplification:",
            "never feeds Actor retries or verdict gates",
        ):
            assert token in skill_md

    def test_reference_documents_complexity_lens_boundaries(self, reference_md):
        for token in (
            "What-To-Delete Lens",
            "minimality: off",
            "Correctness, security, and performance findings stay in the normal",
            "single smoke test or assert-based self-check is the minimum",
            "`net: -N` is post-hoc and advisory only",
            "do not feed it into Actor retry context",
        ):
            assert token in reference_md


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


class TestTaskDecomposerWaveParallelismGuidance:
    """Regression: task-decomposer must steer Actor away from over-serializing
    waves. Without explicit guidance, decomposer agents emit linear deps
    (B depends on A, C on B, ...) that collapse the wave planner into 15
    single-subtask waves even when files are disjoint.
    """

    @pytest.fixture(
        params=[
            Path(".claude/agents/task-decomposer.md"),
            Path("src/mapify_cli/templates/agents/task-decomposer.md"),
        ],
        ids=["dev", "template"],
    )
    def doc_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_minimize_dependencies_section_present(self, doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        assert "Minimize Dependencies for Parallelism" in content, (
            f"{doc_path} must include 'Minimize Dependencies for Parallelism' "
            "guidance — the wave planner serializes every false dependency edge."
        )

    def test_logical_ordering_anti_pattern_called_out(self, doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        assert "Logical ordering" in content or "logical ordering" in content
        assert "Risk hedging" in content or "risk hedging" in content, (
            f"{doc_path} must explicitly forbid risk-hedging dependencies."
        )

    def test_checklist_includes_load_bearing_edge_check(self, doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        assert "load-bearing" in content, (
            f"{doc_path} checklist must include 'each dependency edge is "
            "load-bearing' item so the gate catches over-serialization."
        )

    def test_affected_files_population_required(self, doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        assert "`affected_files` populated for every subtask" in content, (
            f"{doc_path} must require affected_files for every subtask — "
            "split_wave_by_file_conflicts treats empty as 'alone'."
        )


class TestPlanDiscoveryResearchNamespace:
    """Plan discovery and per-subtask research must share the research/ namespace.

    Regression coverage for issue #199: Claude and Codex planning surfaces used
    to write `.map/<branch>/findings_<branch>.md` while execution read
    `.map/<branch>/research/<subtask>__<kind>.md`.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-plan/SKILL.md"),
            Path(".agents/skills/map-plan/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-plan/SKILL.md"),
            Path("src/mapify_cli/templates/codex/skills/map-plan/SKILL.md"),
        ],
        ids=["claude-dev", "codex-dev", "claude-template", "codex-template"],
    )
    def map_plan_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_map_plan_uses_plan_discovery_research_artifact(
        self, map_plan_path: Path
    ) -> None:
        content = map_plan_path.read_text(encoding="utf-8")
        assert "research/plan__discovery.md" in content, (
            f"{map_plan_path} must document canonical plan discovery under research/."
        )
        assert 'save_research "$BRANCH" plan discovery' in content, (
            f"{map_plan_path} must save new discovery through the shared research API."
        )

    def test_map_plan_documents_runtime_state_gate(
        self, map_plan_path: Path
    ) -> None:
        """Every map-plan surface (Claude + Codex) must ship the Step 0.6 gate (#243)."""
        content = map_plan_path.read_text(encoding="utf-8")
        assert "depends_on_runtime_state" in content, (
            f"{map_plan_path} must document the depends_on_runtime_state signal."
        )
        assert "Step 0.6" in content, (
            f"{map_plan_path} must define the Step 0.6 runtime-state gate."
        )
        assert "Verify Live/Runtime State" in content, (
            f"{map_plan_path} must name the Verify Live/Runtime State gate."
        )

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-plan/plan-reference.md"),
            Path("src/mapify_cli/templates/skills/map-plan/plan-reference.md"),
        ],
        ids=["claude-dev", "claude-template"],
    )
    def plan_reference_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_plan_reference_details_runtime_state_gate(
        self, plan_reference_path: Path
    ) -> None:
        """The reference must hold the Step 0.6 detail the compact SKILL body points to."""
        content = plan_reference_path.read_text(encoding="utf-8")
        assert "## Verify Live/Runtime State" in content, (
            f"{plan_reference_path} must hold the Verify Live/Runtime State section "
            "the SKILL body links to (#verify-liveruntime-state anchor)."
        )
        assert "Unverified Runtime Assumption" in content, (
            f"{plan_reference_path} must document the record-the-check contract."
        )

    def test_codex_map_plan_no_longer_writes_legacy_findings(self) -> None:
        path = (
            Path(__file__).parent.parent
            / "src/mapify_cli/templates/codex/skills/map-plan/SKILL.md"
        )
        content = path.read_text(encoding="utf-8")
        assert "cat > .map/${BRANCH}/findings_${BRANCH}.md" not in content

    def test_claude_map_plan_documents_wayfind_offramp(self) -> None:
        """Claude /map-plan must expose the map-wayfind Workflow-Fit off-ramp (#362).

        map-wayfind is Claude-only, so the Codex surface intentionally omits it.
        """
        root = Path(__file__).parent.parent
        for rel in (
            ".claude/skills/map-plan/SKILL.md",
            "src/mapify_cli/templates/skills/map-plan/SKILL.md",
        ):
            content = (root / rel).read_text(encoding="utf-8")
            assert "map-wayfind" in content, f"{rel} must document the map-wayfind route"
            assert "record_workflow_fit" in content
            # the too-foggy off-ramp must recommend charting a map, not just mention it
            assert "/map-wayfind chart" in content, (
                f"{rel} must recommend `/map-wayfind chart` when too foggy to specify"
            )

    @pytest.fixture(
        params=[
            Path(".claude/agents/actor.md"),
            Path("src/mapify_cli/templates/agents/actor.md"),
        ],
        ids=["dev", "template"],
    )
    def actor_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_actor_guidance_uses_research_namespace(self, actor_path: Path) -> None:
        content = actor_path.read_text(encoding="utf-8")
        assert "research/" in content
        assert "plan__discovery.md" in content
        assert "findings_<branch>.md" not in content

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path(".agents/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/codex/skills/map-efficient/SKILL.md"),
        ],
        ids=["claude-dev", "codex-dev", "claude-template", "codex-template"],
    )
    def map_efficient_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_map_efficient_documents_plan_to_subtask_flow(
        self, map_efficient_path: Path
    ) -> None:
        content = map_efficient_path.read_text(encoding="utf-8")
        assert "research/plan__discovery.md" in content
        assert "research/<subtask_id>__actor.md" in content


class TestMapEfficientNoInterSubtaskPause:
    """Regression: /map-efficient must chain subtasks without per-subtask
    "summary report + wait for user" pauses. A downstream run paused
    between ST-004 and ST-005, doubling round-trips; the skill defaulted
    to the conservative interpretation because no rule forbade pausing."""

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_skill_explicitly_forbids_inter_subtask_pause(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Do NOT pause between subtasks" in content, (
            f"{skill_path} must include 'Do NOT pause between subtasks' "
            "rule so models don't default to per-subtask checkpoints."
        )

    def test_skill_enumerates_legitimate_stop_conditions(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # The 4-of-4 stop list — anything else is the "wrong default"
        # the user explicitly complained about.
        for marker in (
            "next_step: \"COMPLETE\"",
            "retry_quarantine",
            "User explicitly interrupts",
            "Circuit-breaker",
        ):
            assert marker in content, (
                f"{skill_path} stop-condition list missing: {marker!r}"
            )


class TestMapEfficientPerSubtaskCommitAllowance:
    """Regression: /map-efficient must explicitly permit (and encourage)
    per-subtask commits after Monitor clean-close, without asking the
    user. Operators were unsure whether they could commit per subtask
    or had to bundle everything; the default needs to be "commit per
    subtask" so PR review and last_subtask_commit_sha baseline both
    work.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_skill_permits_per_subtask_commit(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Commit on clean Monitor close" in content, (
            f"{skill_path} must explicitly permit per-subtask commit "
            "after Monitor clean-close — operators were unsure if it "
            "was allowed and either bundled everything or asked first."
        )
        # Must signal "without asking" so the model doesn't pause.
        assert "without asking the" in content, skill_path

    def test_skill_recommends_per_subtask_commit_workflow(
        self, skill_path: Path
    ) -> None:
        # The bash recipe is in efficient-reference.md (moved 2026-05-25 to
        # keep SKILL.md under 500 lines). Verify the recipe still has the
        # correct stage → commit → record → validate order on the
        # reference side, and that SKILL.md points to it.
        skill_content = skill_path.read_text(encoding="utf-8")
        assert "efficient-reference.md" in skill_content, (
            f"{skill_path}: must point to efficient-reference.md for the full recipe."
        )
        reference = skill_path.parent / "efficient-reference.md"
        ref_content = reference.read_text(encoding="utf-8")
        commit_pos = ref_content.find("git commit -m \"ST-NNN")
        record_pos = ref_content.find("record_subtask_result \\")
        # The clean-pass close is the FIRST validate_step 2.4 at/after the
        # record step in the commit recipe. Search from record_pos so an
        # earlier, unrelated validate_step 2.4 (e.g. the flaky-defer
        # `--disposition` route in the triage section above) does not match.
        validate_pos = ref_content.find("validate_step 2.4", record_pos)
        assert 0 <= commit_pos < record_pos, (
            f"{reference}: commit must precede record_subtask_result so "
            "--commit-sha gets the real SHA, not the prior one."
        )
        assert record_pos < validate_pos, (
            f"{reference}: record_subtask_result must precede validate_step 2.4."
        )

    def test_skill_warns_against_no_verify_and_amend(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "--no-verify" in content, skill_path
        assert "amend" in content.lower(), skill_path


class TestMapEfficientTruncatedMonitorResponseGate:
    """Regression: when Monitor truncates mid-execution and emits prose
    instead of JSON ("All tests pass. Now run ruff..."), /map-efficient
    must treat it as needs_investigation, NOT silently advance. The skill
    rule sits BEFORE the verdict-contract check so prose can't sneak
    through on a recommendation default.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_skill_has_truncated_response_gate(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Truncated-response gate" in content, (
            f"{skill_path} missing the truncated-Monitor-response gate."
        )
        # Gate must be MANDATORY and ordered before the verdict-contract
        # rule, so prose responses don't sneak past on a default recommendation.
        gate_pos = content.find("Truncated-response gate")
        verdict_pos = content.find("Verdict contract (MANDATORY)")
        assert 0 <= gate_pos < verdict_pos, (
            f"{skill_path}: truncated-response gate must appear BEFORE "
            "verdict-contract rule so prose-output is rejected first."
        )

    def test_skill_describes_retry_then_clarify_protocol(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Retry via the detect->log->retry triplet, then stop.
        assert "detect_truncated_agent_output" in content, (
            f"{skill_path} must reference detect_truncated_agent_output"
        )
        assert "log_agent_failure" in content, (
            f"{skill_path} must reference log_agent_failure"
        )
        assert "build_json_retry_prompt" in content, (
            f"{skill_path} must reference build_json_retry_prompt"
        )
        assert "CLARIFICATION_NEEDED" in content, skill_path
        # Three diagnostic signs must be enumerated.
        # Whitespace-tolerant check: SKILL.md uses backtick-formatted markdown
        # which may re-flow. Match on substrings independent of fence style.
        for sign in (
            "doesn't parse as JSON",
            "valid`/`summary`/`issues",
            "ends mid-sentence",
        ):
            assert sign in content, (
                f"{skill_path} truncated-response diagnosis must list: {sign!r}"
            )


class TestRetryTripletCoverage:
    """VC1/VC3: All three skill files reference the detect->log->retry triplet
    and contain none of the banned 'emit ONLY' prose literals."""

    TRIPLET_FNS = (
        "detect_truncated_agent_output",
        "log_agent_failure",
        "build_json_retry_prompt",
    )
    BANNED_LITERALS = (
        "emit ONLY the JSON envelope",
        "emit ONLY the JSON object",
    )

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
            Path(".claude/skills/map-efficient/efficient-reference.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/efficient-reference.md"),
            Path(".claude/skills/map-review/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-review/SKILL.md"),
        ],
        ids=[
            "map-efficient/SKILL.md-dev",
            "map-efficient/SKILL.md-template",
            "efficient-reference.md-dev",
            "efficient-reference.md-template",
            "map-review/SKILL.md-dev",
            "map-review/SKILL.md-template",
        ],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_references_all_triplet_fns(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        for fn in self.TRIPLET_FNS:
            assert fn in content, (
                f"{skill_path} must reference runtime fn: {fn!r}"
            )

    def test_no_banned_emit_only_literals(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        for literal in self.BANNED_LITERALS:
            assert literal not in content, (
                f"{skill_path} must not contain banned literal: {literal!r}"
            )


class TestMapReviewSourceNote:
    """VC2/SC-1: map-review SKILL.md must note that the output schema is
    generated by build_review_prompts (AGENT_OUTPUT_SCHEMAS single source)."""

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-review/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-review/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_schema_source_note_present(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "build_review_prompts" in content, (
            f"{skill_path} must note that output schema is generated by build_review_prompts"
        )
        assert "AGENT_OUTPUT_SCHEMAS" in content, (
            f"{skill_path} must reference AGENT_OUTPUT_SCHEMAS as the single source of truth"
        )


class TestMapEfficientEmptyArgsResumeGuard:
    """Regression: /map-efficient must resume from existing plan / state when
    $TASK_ARGS is empty, NOT bail with "needs a task description". A prior
    model invocation took an early shortcut and refused to run against a repo
    that had a complete task_plan_<branch>.md ready for resume.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_skill_states_empty_args_alone_is_not_a_stop_condition(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Empty $TASK_ARGS is NOT a stop condition" in content, (
            f"{skill_path} must explicitly tell the model that empty "
            "$TASK_ARGS alone does not justify exiting — Step 0 resume must "
            "run first."
        )

    def test_skill_lists_three_required_conditions_for_exit(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # The 3-of-3 contract: empty args, missing state, missing plan.
        assert "step_state.json` does NOT exist" in content
        assert "task_plan_<branch>.md` does NOT exist" in content

    def test_step_zero_checks_state_before_plan(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # state check must precede plan check inside Step 0 so an in-flight
        # workflow takes priority over a stale plan resume.
        state_idx = content.find("Existing step_state.json found")
        plan_idx = content.find("Resumed from /map-plan artifacts")
        assert 0 < state_idx < plan_idx, (
            f"{skill_path} Step 0 must check existing step_state.json BEFORE "
            "falling through to resume_from_plan."
        )


class TestMapEfficientSaveResearchWiring:
    """Regression: map-efficient must show the save_research / load_research API.

    Before this wiring, the .map/<branch>/research/ folder was discipline-only:
    Actor and Monitor had no canonical path to write/read research findings, so
    the {research_findings} prompt placeholder lived as untracked tribal lore.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_research_phase_invokes_save_research_cli(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert (
            "python3 .map/scripts/map_step_runner.py save_research" in content
        ), (
            f"{skill_path} must show the save_research CLI for the RESEARCH phase. "
            "Without it, .map/<branch>/research/ remains discipline-only."
        )

    def test_research_phase_invokes_load_research_cli(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert (
            "python3 .map/scripts/map_step_runner.py load_research" in content
        ), (
            f"{skill_path} must show the load_research CLI so downstream phases "
            "read findings through the canonical path."
        )

    def test_research_phase_invokes_validate_research_cli(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert (
            "python3 .map/scripts/map_step_runner.py validate_research" in content
        ), (
            f"{skill_path} must show the validate_research CLI before "
            "validate_step 2.2 so malformed research cannot reach Actor."
        )

    def test_research_phase_states_exact_contract_and_points_to_schema(
        self, skill_path: Path
    ) -> None:
        """#228: the documented hand-author path must name the exact enum/types
        and point to the authoritative schema so the first save validates."""
        content = skill_path.read_text(encoding="utf-8")
        # Exact status enum (the prose used to imply free text).
        assert "OK, PARTIAL_RESULTS, NO_RESULTS, SEARCH_FAILED" in content, (
            f"{skill_path} must name the exact research status enum."
        )
        # Pointer to the authoritative schema + the self-correcting skeleton.
        assert "RESEARCH artifact schema" in content
        assert "[efficient-reference.md](efficient-reference.md)" in content
        assert "`skeleton`" in content

    def test_research_policy_distinguishes_artifact_from_subagent(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Persist a RESEARCH artifact" in content
        assert "`research-agent` is conditional" in content
        assert "Call `research-agent` for the current subtask" not in content

    def test_map_efficient_requires_research_consumption_before_broad_search(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Actor must consume high-confidence research before re-exploring" in content
        assert "`confidence >= 0.7`" in content
        assert "first read 1-3 cited ranges" in content
        assert "detect_research_consumption_drift" in content

    def test_codex_research_policy_matches_claude_contract(self) -> None:
        project_root = Path(__file__).parent.parent
        for relative_path in [
            Path(".agents/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/codex/skills/map-efficient/SKILL.md"),
        ]:
            content = (project_root / relative_path).read_text(encoding="utf-8")
            assert "Persist a RESEARCH artifact" in content
            assert "Use" in content
            assert "`researcher`" in content
            assert "when independent exploration is useful" in content
            assert "If the subtask truly needs no Actor/Monitor" in content
            assert "Actor must consume high-confidence research before re-exploring" in content
            assert "detect_research_consumption_drift" in content

    def test_hook_hint_mentions_required_artifact_not_required_subagent(self) -> None:
        project_root = Path(__file__).parent.parent
        for relative_path in [
            Path(".claude/hooks/workflow-context-injector.py"),
            Path("src/mapify_cli/templates/hooks/workflow-context-injector.py"),
        ]:
            content = (project_root / relative_path).read_text(encoding="utf-8")
            assert "Persist RESEARCH artifact" in content
            assert "Run research-agent (conditional" not in content

    def test_orchestrator_error_offers_delegated_and_direct_research_paths(self) -> None:
        project_root = Path(__file__).parent.parent
        for relative_path in [
            Path(".map/scripts/map_orchestrator.py"),
            Path("src/mapify_cli/templates/map/scripts/map_orchestrator.py"),
        ]:
            content = (project_root / relative_path).read_text(encoding="utf-8")
            assert "research-agent conditional" in content
            assert "Use research-agent for broad/high-risk/unclear discovery" in content
            assert "save direct current-session findings" in content

    def test_actor_prompt_requires_narrow_reads_for_high_confidence_research(self) -> None:
        project_root = Path(__file__).parent.parent
        for relative_path in [
            Path(".claude/agents/actor.md"),
            Path("src/mapify_cli/templates/agents/actor.md"),
        ]:
            content = (project_root / relative_path).read_text(encoding="utf-8")
            assert "Read cited code before broad search" in content
            assert "For confidence >= 0.7 with `relevant_locations`" in content
            assert "repository-wide `rg`/`grep`/`find`/`git grep`" in content


class TestResearchArtifactSchemaDocumented:
    """#228: the exact hand-author research contract must be documented (not prose).

    Before this, the documented `save_research` path cost 2-3 `validate_research`
    rejects because the exact field names/types/enum lived only in the validator.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/efficient-reference.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/efficient-reference.md"),
            Path(".agents/skills/map-efficient/efficient-reference.md"),
            Path(
                "src/mapify_cli/templates/codex/skills/map-efficient/efficient-reference.md"
            ),
        ],
        ids=["claude-dev", "claude-template", "codex-dev", "codex-template"],
    )
    def reference_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_reference_documents_exact_research_contract(
        self, reference_path: Path
    ) -> None:
        content = reference_path.read_text(encoding="utf-8")
        assert "## RESEARCH artifact schema" in content, (
            f"{reference_path} must document the exact research artifact schema."
        )
        # Exact enum + field names the validator enforces (the values the issue
        # reported guessing wrong: 'complete'/'high'/'files_examined').
        for token in (
            "OK", "PARTIAL_RESULTS", "NO_RESULTS", "SEARCH_FAILED",
            "files_scanned", "total_matches_found", "results_truncated",
            "relevant_locations", "skeleton",
        ):
            assert token in content, f"{reference_path} schema missing {token!r}"

    def test_reference_skeleton_is_a_valid_artifact(self, reference_path: Path) -> None:
        """The copy-pasteable skeleton in the docs must parse and match the
        validator's contract, so it never drifts into a shape that gets rejected."""
        content = reference_path.read_text(encoding="utf-8")
        block = content.split("```json", 1)[1].split("```", 1)[0]
        skeleton = json.loads(block)
        assert skeleton["status"] in {
            "OK", "PARTIAL_RESULTS", "NO_RESULTS", "SEARCH_FAILED",
        }
        assert 0 <= skeleton["confidence"] <= 1
        assert set(skeleton["search_stats"]) == {
            "files_scanned", "total_matches_found", "results_truncated",
        }
        assert len(skeleton["relevant_locations"]) <= 5
        loc = skeleton["relevant_locations"][0]
        assert set(loc) == {"path", "lines", "relevance"}
        start, end = loc["lines"]
        assert 1 <= start <= end and end - start + 1 <= 200


class TestResearchProviderParity:
    """Regression tests for the shared Claude/Codex ResearchEvidence contract."""

    @pytest.fixture(
        params=[
            Path(".claude/agents/research-agent.md"),
            Path("src/mapify_cli/templates/agents/research-agent.md"),
            Path(".codex/agents/researcher.toml"),
            Path("src/mapify_cli/templates/codex/agents/researcher.toml"),
        ],
        ids=["claude-dev", "claude-template", "codex-dev", "codex-template"],
    )
    def researcher_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_researcher_templates_share_core_evidence_fields(
        self, researcher_path: Path
    ) -> None:
        content = researcher_path.read_text(encoding="utf-8")

        for field in [
            '"confidence"',
            '"status"',
            '"search_method"',
            '"search_stats"',
            '"files_scanned"',
            '"total_matches_found"',
            '"results_truncated"',
            '"executive_summary"',
            '"relevant_locations"',
            '"path"',
            '"lines"',
            '"signature"',
            '"relevance"',
            '"relevance_score"',
            '"has_intent"',
            '"patterns_discovered"',
        ]:
            assert field in content, f"{researcher_path} missing {field}"

    def test_researcher_templates_keep_bounded_file_line_evidence(
        self, researcher_path: Path
    ) -> None:
        content = researcher_path.read_text(encoding="utf-8")

        assert "at most 5" in content.lower() or "max 5" in content.lower()
        assert "inclusive" in content.lower()
        assert "line" in content.lower()
        assert (
            "safe relative" in content.lower()
            or "relative to project root" in content.lower()
        )

    def test_codex_researcher_uses_provider_neutral_search_contract(self) -> None:
        project_root = Path(__file__).parent.parent
        for relative_path in [
            Path(".codex/agents/researcher.toml"),
            Path("src/mapify_cli/templates/codex/agents/researcher.toml"),
        ]:
            content = (project_root / relative_path).read_text(encoding="utf-8")
            assert "ResearchEvidence contract" in content
            assert "same downstream semantics" in content
            assert "Glob-equivalent" in content
            assert "Grep-equivalent" in content
            assert "Read-equivalent" in content
            assert "find . -type f" not in content
            assert "rg -l" not in content

    def test_usage_docs_explain_provider_parity(self) -> None:
        docs = (Path(__file__).parent.parent / "docs/USAGE.md").read_text(
            encoding="utf-8"
        )

        assert "Claude `research-agent` and Codex `researcher`" in docs
        assert "ResearchEvidence JSON" in docs
        assert "downstream Actor/Monitor semantics" in docs


class TestMapEfficientBuildContextBlockCli:
    """Regression: map-efficient must show the build_context_block CLI form.

    map_step_runner.py exposes `build_context_block <branch> <subtask_id>` as a
    proper CLI subcommand. The skill used to tell agents to use the `python -c
    "import sys; sys.path.insert(0, '.map/scripts'); ..."` workaround, which is
    fragile and noisy. The CLI form is canonical — the skill must surface it.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-efficient/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-efficient/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_cli_invocation_is_documented(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert (
            "python3 .map/scripts/map_step_runner.py build_context_block"
            in content
        ), (
            f"{skill_path} must document the CLI form "
            "`python3 .map/scripts/map_step_runner.py build_context_block "
            "<branch> <subtask_id>` for build_context_block."
        )

    def test_no_python_dash_c_workaround(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Catch the historical "python -c \"import sys; sys.path.insert..."
        # workaround that the CLI form replaces.
        offending_patterns = [
            'python -c "import sys; sys.path.insert',
            "python3 -c \"import sys; sys.path.insert",
        ]
        hits = [p for p in offending_patterns if p in content]
        assert not hits, (
            f"{skill_path} still contains the python -c sys.path.insert "
            f"workaround for build_context_block: {hits!r}. Use the CLI form "
            "instead."
        )


class TestMapCheckPendingStepsSchema:
    """Regression: map-check must treat step_state.pending_steps as a flat list[str].

    The canonical schema (see map_orchestrator.WorkflowState.pending_steps) is a
    list of workflow phase ids (e.g. "2.2", "2.3"), NOT a dict keyed by subtask id.
    A prior version of map-check/SKILL.md indexed it as `.pending_steps["ST-001"]`,
    which crashes jq at runtime with:
        Cannot index array with string "ST-001"
    Both the dev copy under .claude/ and the shipped template copy must avoid this
    pattern.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-check/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-check/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_skill_does_not_index_pending_steps_as_dict(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Only inspect executable bash code fences — prose that warns about the
        # anti-pattern (in inline backticks) is legitimate and must stay.
        bash_blocks = re.findall(r"```bash\n(.*?)```", content, re.DOTALL)
        offenders: list[tuple[int, str]] = []
        for idx, block in enumerate(bash_blocks):
            for hit in re.findall(r'\.pending_steps\[\\?"[^\]]+\\?"\]', block):
                offenders.append((idx, hit))
        assert not offenders, (
            f"{skill_path} indexes .pending_steps as a dict inside bash blocks "
            f"(e.g. {offenders[0][1]!r}); the canonical schema makes pending_steps "
            "a flat list[str] of workflow phase ids — keyed access crashes jq at "
            "runtime with 'Cannot index array with string'."
        )

    def test_skill_completion_check_uses_flat_schema(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # A valid check needs to inspect either workflow_status or pending_steps
        # as a flat array. Without one of these the schema-aware check is gone.
        has_flat_pending = (
            ".pending_steps | length" in content
            or ".pending_steps[]" in content
        )
        has_workflow_status = "workflow_status" in content
        assert has_flat_pending or has_workflow_status, (
            f"{skill_path} must verify workflow completion via either "
            "`.pending_steps | length` / `.pending_steps[]` (flat-array form) "
            "or `.workflow_status` — neither was found."
        )


class TestMapReviewWalkthroughHardening:
    """Regression: after a walkthrough that filtered 9 reviewer findings
    down to 3 (with HIGH severities downgraded), the skill must:
      - precheck lint/test BEFORE reviewer agents,
      - detect lightweight (empty bundle) and sibling-aware modes,
      - require evidence (reach_evidence) for severity≥MEDIUM,
      - tag findings was_present_before_pr to filter pre-existing,
      - run a verification gate before publication,
      - force cross-agent challenge when Monitor and Evaluator diverge.
    """

    @pytest.fixture(
        params=[
            Path(".claude/skills/map-review/SKILL.md"),
            Path("src/mapify_cli/templates/skills/map-review/SKILL.md"),
        ],
        ids=["dev", "template"],
    )
    def skill_path(self, request: pytest.FixtureRequest) -> Path:
        return Path(__file__).parent.parent / request.param

    def test_lint_test_precheck_runs_first(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Precheck section exists.
        assert "Step A.0: Lint / test precheck" in content, (
            f"{skill_path} missing Step A.0 lint/test precheck — "
            "reviewer findings the linter already catches must NOT "
            "become walkthrough items."
        )
        # Precheck appears BEFORE the first Task( call.
        precheck_pos = content.find("Step A.0: Lint / test precheck")
        first_task = content.find("Task(")
        assert 0 <= precheck_pos < first_task, (
            f"{skill_path}: precheck must run before reviewer agents."
        )

    def test_mode_detection_step_present(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Step A.0b: Detect review mode" in content, skill_path
        for needle in ("lightweight", "sibling-aware", "review-mode.json"):
            assert needle in content, (
                f"{skill_path} mode detection missing: {needle!r}"
            )

    def test_evidence_required_on_agent_schemas(self, skill_path: Path) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Monitor issues must carry reach_evidence + was_present_before_pr.
        assert "`reach_evidence`" in content, skill_path
        assert "`was_present_before_pr`" in content, skill_path
        # Predictor landmine claims require landmine_evidence.
        assert "`landmine_evidence`" in content, skill_path
        # Evaluator audits Monitor's severity.
        assert "`monitor_severity_audit`" in content, skill_path

    def test_verification_gate_present_with_six_checks(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "Step A.3: Verification gate" in content, skill_path
        # Six numbered checks: Evidence, Pre-existing, Sibling, Precheck dup,
        # Reachability, Cross-agent challenge.
        for check in (
            "Evidence check",
            "Pre-existing check",
            "Sibling check",
            "Precheck duplication check",
            "Reachability check",
            "Cross-agent challenge",
        ):
            assert check in content, (
                f"{skill_path} verification gate missing: {check!r}"
            )

    def test_hard_stop_no_longer_immediate_publication(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # The legacy "report findings immediately and skip Phase B" line
        # must be gone — replaced with verification-gated publication.
        assert (
            "report findings immediately and skip Phase B" not in content
        ), (
            f"{skill_path}: hard-stop must require verification before "
            "publication (legacy unconditional dump is gone)."
        )
        # Surviving findings (post-verification) gate is documented.
        # Whitespace-tolerant: the phrase may wrap across lines.
        flat = " ".join(content.split())
        assert "survives the verification gate" in flat, skill_path

    def test_sibling_aware_reads_sibling_before_findings(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        assert "sibling-aware" in content
        assert "Read the sibling's" in content, (
            f"{skill_path}: sibling-aware mode must require reading the "
            "sibling reference BEFORE reviewers search for differences."
        )

    def test_lightweight_mode_drops_to_monitor_only(
        self, skill_path: Path
    ) -> None:
        content = skill_path.read_text(encoding="utf-8")
        # Lightweight = monitor only, two sections, stricter evidence.
        assert "lightweight" in content
        assert "Monitor only" in content, (
            f"{skill_path}: lightweight mode must drop Predictor / Evaluator "
            "to keep speculation off an empty bundle."
        )
