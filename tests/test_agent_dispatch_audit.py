"""
Enforces the Agent-Boundary Doctrine (issue #230).

Every shipped agent must either:
  - be dispatched by at least one skill (a ``subagent_type="<name>"`` site in a
    skill ``*.jinja`` source), OR
  - be explicitly listed as a documented, user-dispatchable / optional agent.

This prevents a future agent from silently shipping with no caller (a "silent
orphan") — the dead-weight class removed in PR #240 (the Self-MoA ``synthesizer``
and ``debate-arbiter`` relays). It also pins ``documentation-reviewer`` as a
*deliberate* keep: it emits a unique, non-relay verdict but has no skill dispatch,
so it is retained as an optional agent and must carry a visible annotation.

See docs/ARCHITECTURE.md → "Agent-Boundary Doctrine".
"""

import re
from pathlib import Path

REPO = Path(__file__).parent.parent
AGENTS_SRC = REPO / "src" / "mapify_cli" / "templates_src" / "agents"
SKILLS_SRC = REPO / "src" / "mapify_cli" / "templates_src" / "skills"
ARCHITECTURE = REPO / "docs" / "ARCHITECTURE.md"

# Agents that intentionally have NO skill-initiated dispatch site. Retained per the
# Agent-Boundary Doctrine because they emit a unique, non-relay verdict and are
# invocable manually via Task(subagent_type="<name>"). Each MUST carry a
# "Dispatch status:" annotation in its template so the undispatched state is deliberate.
DOCUMENTED_OPTIONAL_AGENTS = {"documentation-reviewer"}

_DISPATCH_RE = re.compile(r'subagent_type=["\']([a-z0-9-]+)["\']')


def _shipped_agent_names() -> set[str]:
    suffix = ".md.jinja"
    return {p.name[: -len(suffix)] for p in AGENTS_SRC.glob("*.md.jinja")}


def _dispatched_agent_names() -> set[str]:
    names: set[str] = set()
    for jinja in SKILLS_SRC.rglob("*.jinja"):
        names.update(_DISPATCH_RE.findall(jinja.read_text(encoding="utf-8")))
    return names


def test_agent_and_dispatch_discovery_non_empty():
    """Guard against a vacuous pass from a glob/path typo (silent empty discovery)."""
    agents = _shipped_agent_names()
    assert len(agents) >= 8, f"agent discovery looks empty/short: {sorted(agents)}"
    dispatched = _dispatched_agent_names()
    assert dispatched, "no subagent_type dispatch sites discovered — glob/path typo?"


def test_every_agent_is_dispatched_or_documented_optional():
    """No agent may ship without a caller unless explicitly marked optional."""
    agents = _shipped_agent_names()
    dispatched = _dispatched_agent_names()
    silent_orphans = sorted(
        a
        for a in agents
        if a not in dispatched and a not in DOCUMENTED_OPTIONAL_AGENTS
    )
    assert not silent_orphans, (
        f"Silent orphan agent(s) shipped with no dispatch site and not marked "
        f"optional: {silent_orphans}. Per the Agent-Boundary Doctrine, either "
        f"dispatch them from a skill, add them to DOCUMENTED_OPTIONAL_AGENTS with a "
        f"'Dispatch status:' annotation, or remove them (see PR #240)."
    )


def test_documented_optional_agents_exist_and_are_annotated():
    """Optional-agent registry must have no stale entries and each must self-declare."""
    agents = _shipped_agent_names()
    for name in DOCUMENTED_OPTIONAL_AGENTS:
        assert name in agents, (
            f"DOCUMENTED_OPTIONAL_AGENTS lists {name!r} but no template "
            f"{name}.md.jinja exists — stale entry."
        )
        text = (AGENTS_SRC / f"{name}.md.jinja").read_text(encoding="utf-8")
        assert "Dispatch status:" in text, (
            f"{name}.md.jinja must carry a 'Dispatch status:' annotation so its "
            f"undispatched state is deliberate and visible."
        )


def test_doctrine_documented_in_architecture():
    """The doctrine itself must stay documented (issue #230 deliverable)."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "Agent-Boundary Doctrine" in text, (
        "docs/ARCHITECTURE.md must document the Agent-Boundary Doctrine (issue #230)."
    )
