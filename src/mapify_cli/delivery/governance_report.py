"""Governance report for MAP behavior-shaping assets.

Inventories installed skills, hooks, references, and learned rules in a
.claude/ directory and classifies each asset under six governance categories:
Charter, Policy, Context, Harness, Oversight, Learning.

Distinguishes enforced controls (hooks that run at the harness layer) from
prompt-only guidance (skills, references, learned rules).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Governance categories
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    "charter",
    "policy",
    "context",
    "harness",
    "oversight",
    "learning",
]

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "charter": "Defines why workflows exist, where they apply, and where they must not be used",
    "policy": "Non-negotiable constraints enforced at the harness or credential level",
    "context": "Controls what the agent can see and what it is optimizing for",
    "harness": "Permissions, checks, proof requirements, and recovery paths",
    "oversight": "Accountability, escalation thresholds, pause/stop authority, and risk ownership",
    "learning": "Mechanisms that turn repeated failures into rules, skills, controls, or evals",
}

# ---------------------------------------------------------------------------
# Static classification tables
# ---------------------------------------------------------------------------

#: Default descriptions for known hooks (enforcement = "enforced")
_HOOK_META: dict[str, tuple[str, str]] = {
    # name -> (category, description)
    "safety-guardrails.py": (
        "policy",
        "Denies dangerous commands and sensitive-file access at the shell level",
    ),
    "workflow-gate.py": (
        "harness",
        "Returns permissionDecision=deny for out-of-phase or out-of-scope edits",
    ),
    "context-meter.py": (
        "context",
        "Measures context window utilization and emits a usage signal",
    ),
    "workflow-context-injector.py": (
        "context",
        "Injects branch-scoped workflow artifacts into the agent context",
    ),
    "map-memory-capture.py": (
        "learning",
        "Captures per-turn scratch memory for end-of-session finalization",
    ),
    "map-memory-recall.py": (
        "context",
        "Injects recalled session memory and learned rules into context at session start",
    ),
    "map-memory-finalize.py": (
        "learning",
        "Finalizes and persists session memory digests to .map/<branch>/",
    ),
    "map-memory-endmark.py": (
        "learning",
        "Emits end-of-session marker for memory boundary detection",
    ),
    "end-of-turn.sh": (
        "oversight",
        "Runs end-of-turn housekeeping and token accounting summary",
    ),
    "map-statusline.py": (
        "oversight",
        "Renders the MAP workflow status line in the terminal",
    ),
    "map-token-meter.py": (
        "oversight",
        "Records per-turn token usage for cost accounting and budget enforcement",
    ),
    "post-compact-context.py": (
        "context",
        "Restores essential MAP context after a conversation compaction event",
    ),
    "pre-compact-save-transcript.py": (
        "learning",
        "Saves the pre-compaction transcript for future session recall",
    ),
    "ralph-context-pruner.py": (
        "context",
        "Prunes low-value context entries to preserve budget for high-value signals",
    ),
    "ralph-iteration-logger.py": (
        "oversight",
        "Logs each RALPH iteration attempt for escalation and recovery audit",
    ),
    "detect-clarification-triggers.py": (
        "harness",
        "Detects prompts that should trigger clarification instead of silent assumption",
    ),
    "scrub-internal-ids.py": (
        "policy",
        "Strips internal IDs and private platform details from emitted content",
    ),
}

#: Default categories for known skills (enforcement = "prompt-only")
_SKILL_META: dict[str, tuple[str, str]] = {
    # name -> (category, description from skill-rules.json or best-known)
    "map-state": (
        "charter",
        "File-based planning with branch-scoped task tracking",
    ),
    "map-plan": (
        "charter",
        "ARCHITECT phase: decompose a complex task into atomic subtasks",
    ),
    "map-efficient": (
        "harness",
        "Token-efficient MAP workflow with state-machine orchestration",
    ),
    "map-fast": (
        "harness",
        "Minimal MAP workflow for small low-risk changes (no Predictor/Reflector)",
    ),
    "map-tdd": (
        "harness",
        "TDD MAP workflow: spec-driven tests written before implementation",
    ),
    "map-check": (
        "harness",
        "Run quality gates (lint, types, tests) and verify MAP workflow completion",
    ),
    "map-debug": (
        "harness",
        "Structured MAP debugging via task-decomposer, actor, monitor agents",
    ),
    "map-task": (
        "harness",
        "Execute a single subtask from an existing MAP plan",
    ),
    "map-review": (
        "harness",
        "Interactive code review using Monitor, Predictor, Evaluator agents",
    ),
    "map-learn": (
        "learning",
        "Extract and persist workflow lessons to .claude/rules/learned/",
    ),
    "map-memory-now": (
        "learning",
        "On-demand finalize of session memory (current scratch + --finalize-all sweep)",
    ),
    "map-skill-eval": (
        "learning",
        "Evaluate a skill's trigger accuracy and cost, or optimize its description",
    ),
    "map-tokenreport": (
        "oversight",
        "Render per-subtask/agent token accounting for the current branch",
    ),
    "map-resume": (
        "oversight",
        "Resume an interrupted MAP workflow from step_state.json checkpoint",
    ),
    "map-release": (
        "oversight",
        "Execute mapify-cli package release workflow with validation gates",
    ),
    "map-explain": (
        "context",
        "Deep code/PR explanation that builds a complete mental model",
    ),
    "map-understand": (
        "context",
        "Interactive deep-understanding and quiz mode for incremental teaching",
    ),
    "map-so-search": (
        "context",
        "Opt-in read-only prior-art search against Stack Overflow for Agents (SOFA)",
    ),
    "map-wayfind": (
        "oversight",
        "Decision-frontier wayfinding: resolve open design decisions on a durable map before /map-plan",
    ),
    "map-architecture": (
        "context",
        "Opt-in proactive architecture-deepening report: rank codebase hotspots by design friction",
    ),
}

#: Default categories for known references (enforcement = "prompt-only")
_REFERENCE_META: dict[str, tuple[str, str]] = {
    "bash-guidelines.md": ("policy", "Safe bash command patterns for MAP workflow scripts"),
    "decomposition-examples.md": ("context", "Reference examples for task decomposition"),
    "escalation-matrix.md": ("oversight", "Escalation paths and thresholds for MAP workflows"),
    "hook-patterns.md": ("harness", "Canonical patterns for MAP hook authoring"),
    "host-paths.md": ("harness", "Authoritative host paths for MAP-managed directories"),
    "map-json-output-contracts.md": (
        "harness",
        "JSON schema contracts for agent output validation",
    ),
    "map-output-examples.md": ("context", "Canonical output examples for MAP agents"),
    "map-xml-prompt-envelopes.md": ("harness", "XML prompt envelope schemas and usage"),
    "mcp-usage-examples.md": ("context", "MCP server usage examples for MAP workflows"),
    "step-state-schema.md": ("harness", "Schema for step_state.json workflow state file"),
    "workflow-state-schema.md": ("harness", "Schema for MAP workflow state artifacts"),
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GovernanceAsset:
    """A single behavior-shaping asset with its governance metadata."""

    name: str
    kind: str  # "hook" | "skill" | "reference" | "learned-rule" | "config"
    category: str
    enforcement: str  # "enforced" | "prompt-only"
    description: str
    path: str  # relative to project root

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "kind": self.kind,
            "category": self.category,
            "enforcement": self.enforcement,
            "description": self.description,
            "path": self.path,
        }


@dataclass
class GovernanceReport:
    """Compiled governance inventory for a MAP installation."""

    project_path: Path
    assets: list[GovernanceAsset] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    skill_rules_version: str | None = None

    # ------------------------------------------------------------------ #
    # Derived views                                                        #
    # ------------------------------------------------------------------ #

    def by_category(self) -> dict[str, list[GovernanceAsset]]:
        result: dict[str, list[GovernanceAsset]] = {c: [] for c in CATEGORIES}
        for asset in self.assets:
            result.setdefault(asset.category, []).append(asset)
        return result

    def enforced_count(self) -> int:
        return sum(1 for a in self.assets if a.enforcement == "enforced")

    def prompt_only_count(self) -> int:
        return sum(1 for a in self.assets if a.enforcement == "prompt-only")

    # ------------------------------------------------------------------ #
    # JSON export                                                          #
    # ------------------------------------------------------------------ #

    def as_json(self) -> str:
        by_cat = {cat: len(assets) for cat, assets in self.by_category().items()}
        return json.dumps(
            {
                "version": "1.0",
                "project": str(self.project_path),
                "skill_rules_version": self.skill_rules_version,
                "summary": {
                    "total": len(self.assets),
                    "by_category": by_cat,
                    "enforced": self.enforced_count(),
                    "prompt_only": self.prompt_only_count(),
                    "gap_count": len(self.gaps),
                },
                "assets": [a.as_dict() for a in self.assets],
                "gaps": self.gaps,
            },
            indent=2,
        )

    # ------------------------------------------------------------------ #
    # Markdown export                                                      #
    # ------------------------------------------------------------------ #

    def as_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# MAP Governance Report\n")
        lines.append(f"**Project:** `{self.project_path}`  ")
        if self.skill_rules_version:
            lines.append(f"**skill-rules version:** {self.skill_rules_version}  ")
        lines.append(
            f"**Assets:** {len(self.assets)} total "
            f"({self.enforced_count()} enforced, "
            f"{self.prompt_only_count()} prompt-only)  "
        )
        lines.append("")

        lines.append("## Summary\n")
        lines.append(
            f"{len(self.assets)} behavior-shaping assets found across "
            f"{len(CATEGORIES)} governance categories."
        )
        lines.append(
            f"- **{self.enforced_count()} enforced** controls (runtime hooks that "
            f"block or modify behavior deterministically)"
        )
        lines.append(
            f"- **{self.prompt_only_count()} prompt-only** assets (skills, references, "
            f"and learned rules that shape behavior through context injection)"
        )
        lines.append("")

        by_cat = self.by_category()
        for category in CATEGORIES:
            assets = by_cat.get(category, [])
            title = category.capitalize()
            lines.append(f"## {title}\n")
            lines.append(f"*{CATEGORY_DESCRIPTIONS[category]}*\n")
            if not assets:
                lines.append("*(no assets in this category)*\n")
            else:
                for a in assets:
                    badge = "**enforced**" if a.enforcement == "enforced" else "prompt-only"
                    lines.append(f"- `[{a.kind}]` **{a.name}** — {badge}")
                    lines.append(f"  {a.description}  ")
                    lines.append(f"  `{a.path}`")
                lines.append("")

        if self.gaps:
            lines.append("## Gaps\n")
            lines.append(
                "The following prompt-only controls lack a backing enforced hook or permission "
                "gate. Consider adding a harness-level check or documenting the accepted risk.\n"
            )
            for gap in self.gaps:
                lines.append(f"- {gap}")
            lines.append("")

        lines.append("## Evidence Artifacts\n")
        lines.append(
            "The following MAP artifacts are available for audit in the installed `.claude/` "
            "directory:\n"
        )
        lines.append("| Artifact | Purpose |")
        lines.append("|---|---|")
        lines.append(
            "| `.claude/skills/skill-rules.json` | Complete skill catalog with trigger "
            "patterns, enforcement levels, and runtime effects |"
        )
        lines.append(
            "| `.claude/hooks/` | All installed hook scripts (runtime enforced controls) |"
        )
        lines.append(
            "| `.claude/references/` | Reference documentation injected into agent context |"
        )
        lines.append(
            "| `.claude/rules/learned/` | Accumulated project-specific lessons from MAP "
            "workflows |"
        )
        lines.append("")
        lines.append(
            "> **Note:** This report inventories prompt-only guidance and enforced hooks "
            "separately. Prompt-only controls are advice; they do not block execution without "
            "a backing hook or credential boundary. Review the Gap section to identify "
            "policy claims that rely solely on text instructions."
        )

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _read_skill_rules(claude_dir: Path) -> tuple[str | None, dict[str, dict[str, object]]]:
    """Read skill-rules.json and return (version, skills_dict)."""
    rules_path = claude_dir / "skills" / "skill-rules.json"
    if not rules_path.exists():
        return None, {}
    try:
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        version = str(data.get("version", "unknown")) if isinstance(data, dict) else None
        skills = data.get("skills", {}) if isinstance(data, dict) else {}
        return version, skills if isinstance(skills, dict) else {}
    except (json.JSONDecodeError, OSError):
        return None, {}


def _scan_hooks(claude_dir: Path) -> list[GovernanceAsset]:
    hooks_dir = claude_dir / "hooks"
    if not hooks_dir.is_dir():
        return []
    assets: list[GovernanceAsset] = []
    for hook_path in sorted(hooks_dir.iterdir()):
        if hook_path.name == "README.md":
            continue
        if hook_path.suffix not in (".py", ".sh"):
            continue
        meta = _HOOK_META.get(hook_path.name)
        if meta:
            category, description = meta
        else:
            category = "harness"
            description = "Hook script (category not classified in governance table)"
        assets.append(
            GovernanceAsset(
                name=hook_path.name,
                kind="hook",
                category=category,
                enforcement="enforced",
                description=description,
                path=str(hook_path.relative_to(claude_dir.parent)),
            )
        )
    return assets


def _scan_skills(
    claude_dir: Path,
    skills_dict: dict[str, dict[str, object]],
) -> list[GovernanceAsset]:
    skills_dir = claude_dir / "skills"
    if not skills_dir.is_dir():
        return []
    assets: list[GovernanceAsset] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        skill_file = skill_dir / "SKILL.md"

        # Description: prefer skill-rules.json, fall back to static table, then generic
        rules_entry = skills_dict.get(skill_name)
        if isinstance(rules_entry, dict) and rules_entry.get("description"):
            description = str(rules_entry["description"])
        else:
            description = _SKILL_META.get(skill_name, ("", ""))[1] or (
                "Skill (description not found in skill-rules.json)"
            )

        # Category: prefer static table, fall back to skill-rules type
        static = _SKILL_META.get(skill_name)
        if static:
            category = static[0]
        elif isinstance(rules_entry, dict):
            skill_type = str(rules_entry.get("type", ""))
            category = "context" if skill_type == "domain" else "harness"
        else:
            category = "harness"

        assets.append(
            GovernanceAsset(
                name=skill_name,
                kind="skill",
                category=category,
                enforcement="prompt-only",
                description=description,
                path=str(skill_file.relative_to(claude_dir.parent))
                if skill_file.exists()
                else str(skill_dir.relative_to(claude_dir.parent)),
            )
        )
    return assets


def _scan_references(claude_dir: Path) -> list[GovernanceAsset]:
    refs_dir = claude_dir / "references"
    if not refs_dir.is_dir():
        return []
    assets: list[GovernanceAsset] = []
    for ref_path in sorted(refs_dir.iterdir()):
        if ref_path.suffix != ".md":
            continue
        meta = _REFERENCE_META.get(ref_path.name)
        if meta:
            category, description = meta
        else:
            category = "context"
            description = "Reference document (category not classified in governance table)"
        assets.append(
            GovernanceAsset(
                name=ref_path.name,
                kind="reference",
                category=category,
                enforcement="prompt-only",
                description=description,
                path=str(ref_path.relative_to(claude_dir.parent)),
            )
        )
    return assets


def _scan_learned_rules(claude_dir: Path) -> list[GovernanceAsset]:
    learned_dir = claude_dir / "rules" / "learned"
    if not learned_dir.is_dir():
        return []
    assets: list[GovernanceAsset] = []
    for rule_path in sorted(learned_dir.iterdir()):
        if rule_path.suffix != ".md":
            continue
        # Extract first heading as description
        description = _first_heading(rule_path) or "Accumulated project-specific lessons"
        assets.append(
            GovernanceAsset(
                name=rule_path.name,
                kind="learned-rule",
                category="learning",
                enforcement="prompt-only",
                description=description,
                path=str(rule_path.relative_to(claude_dir.parent)),
            )
        )
    return assets


def _first_heading(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^#+\s+(.+)", line.strip())
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return None


def _derive_gaps(assets: list[GovernanceAsset]) -> list[str]:
    """Identify prompt-only policy/harness controls lacking a backing enforced hook."""
    enforced_names = {a.name for a in assets if a.enforcement == "enforced"}
    gaps: list[str] = []

    # Policy skills with no parallel enforced hook covering the same concern
    _POLICY_SKILLS_WITHOUT_HOOKS = {
        # map-plan has no gate enforcing plan quality — it's all prompt guidance
        "map-plan": (
            "map-plan: decomposition quality is prompt guidance; "
            "no harness gate enforces subtask structure or completeness"
        ),
        # map-check invokes quality gates but cannot block LLM from skipping the invocation
        "map-check": (
            "map-check: quality gates are prompt-driven invocation; "
            "no hook enforces map-check is called before a commit"
        ),
    }
    for skill_name, gap_msg in _POLICY_SKILLS_WITHOUT_HOOKS.items():
        if any(a.name == skill_name for a in assets) and skill_name not in enforced_names:
            gaps.append(gap_msg)

    # If no workflow-gate hook is present, flag it
    if "workflow-gate.py" not in enforced_names and any(
        a.kind == "skill" for a in assets
    ):
        gaps.append(
            "workflow-gate.py not found: no harness-level hook is enforcing "
            "phase-scoped edit permissions"
        )

    # If no safety-guardrails hook is present, flag it
    if "safety-guardrails.py" not in enforced_names and any(
        a.kind == "skill" for a in assets
    ):
        gaps.append(
            "safety-guardrails.py not found: no harness-level hook is blocking "
            "dangerous shell commands"
        )

    return gaps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_governance_report(project_path: Path) -> GovernanceReport:
    """Scan an installed MAP project and return a GovernanceReport.

    Looks for a `.claude/` directory inside *project_path*. If none exists,
    returns an empty report (no assets found).

    Args:
        project_path: Root of the target project (must exist).

    Returns:
        GovernanceReport with all discovered assets classified.
    """
    claude_dir = project_path / ".claude"
    report = GovernanceReport(project_path=project_path.resolve())

    if not claude_dir.is_dir():
        return report

    version, skills_dict = _read_skill_rules(claude_dir)
    report.skill_rules_version = version

    report.assets.extend(_scan_hooks(claude_dir))
    report.assets.extend(_scan_skills(claude_dir, skills_dict))
    report.assets.extend(_scan_references(claude_dir))
    report.assets.extend(_scan_learned_rules(claude_dir))

    report.gaps = _derive_gaps(report.assets)
    return report
