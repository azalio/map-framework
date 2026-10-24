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
        assert "Actor must fix every error reported by the gate" not in contract
