"""Prompt contract for user-approved, proven baseline gate deferrals."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_actor_requires_exact_user_approval_and_keeps_full_gate_failed():
    for relative in ("src/mapify_cli/templates_src/agents/actor.md.jinja",
                     "src/mapify_cli/templates/agents/actor.md", ".claude/agents/actor.md"):
        contract = (ROOT / relative).read_text()
        assert "specific failure outside {{allowed_scope}}" in contract
        assert "user explicitly approves that exact diagnostic" in contract
        assert "baseline output" in contract and "source-versus-HEAD evidence" in contract
        assert "new, unknown, in-scope" in contract
        assert "full gate as failing" in contract
        assert "be fixed even on pre-existing code" not in contract


def test_monitor_separates_scoped_verdict_from_full_gate_evidence():
    for relative in ("src/mapify_cli/templates_src/agents/monitor.md.jinja",
                     "src/mapify_cli/templates/agents/monitor.md", ".claude/agents/monitor.md"):
        contract = (ROOT / relative).read_text()
        assert "specific** diagnostic" in contract
        assert "approved mutation boundary" in contract
        assert "baseline output and the current full-gate output" in contract
        assert "Security and correctness defects always block" in contract
        assert "approved_baseline_gate_failures" in contract
        assert "full_gate_status: failed" in contract
        assert "`valid: true` then means only that the scoped subtask passed" in contract
        assert "If any required proof is\nmissing, return `valid: false`" in contract
        assert "introduced-only build, tests, static analysis" in contract
        assert "report the full static-analysis gate as failed" in contract
        assert "An exact approved historical diagnostic does not short-circuit" in contract
        assert "if build/compile fails, set `valid: false` immediately" not in contract
        assert "Actor must fix every error reported by the gate" not in contract


def test_efficient_dispatch_passes_user_decision_to_both_agents():
    for relative in ("src/mapify_cli/templates_src/skills/map-efficient/SKILL.md.jinja",
                     "src/mapify_cli/templates/skills/map-efficient/SKILL.md",
                     ".claude/skills/map-efficient/SKILL.md"):
        contract = (ROOT / relative).read_text()
        assert ".map/<branch>/approved-baseline-gates.md" in contract
        assert "(or `[none]`)" in contract
        assert contract.count('source="approved_baseline_gate_evidence"') == 2
        assert contract.count("{exact_user_approval_and_record_path_or_none}") == 2
    for relative in ("src/mapify_cli/templates/codex/skills/map-efficient/SKILL.md",
                     ".agents/skills/map-efficient/SKILL.md"):
        contract = (ROOT / relative).read_text()
        assert "Resolve `APPROVED_BASELINE_GATE_EVIDENCE` before dispatch" in contract
        assert "Actor and Monitor" in contract
        assert contract.count("Approved baseline gate evidence: <exact_user_approval_and_record_path_or_none>") == 2
        assert 'agent_type="monitor"' in contract
        assert "with the same `APPROVED_BASELINE_GATE_EVIDENCE` passed to Actor" in contract
    for relative in ("src/mapify_cli/templates_src/skills/map-efficient/efficient-reference.md.jinja",
                     "src/mapify_cli/templates/skills/map-efficient/efficient-reference.md",
                     "src/mapify_cli/templates/codex/skills/map-efficient/efficient-reference.md"):
        reference = (ROOT / relative).read_text()
        assert ".map/<branch>/approved-baseline-gates.md" in reference
        assert "full gate as failed" in reference
        assert "normalized-text digests" in reference
