"""Monitor must not pass checks that could not execute; decomposer must plan the repo lint target."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "mapify_cli" / "templates_src"
MONITORS = [ROOT / "agents" / "monitor.md.jinja", ROOT / "codex" / "agents" / "monitor.toml.jinja"]
DECOMPOSERS = [
    ROOT / "agents" / "task-decomposer.md.jinja",
    ROOT / "codex" / "agents" / "decomposer.toml.jinja",
]


@pytest.mark.parametrize("path", MONITORS, ids=lambda p: p.name)
def test_monitor_unrun_check_is_not_a_pass(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "VERIFICATION EXECUTION GATE" in text
    assert "verification not executed: <tool> (<reason>)" in text
    assert "`unavailable`" in text and "`skipped`" in text
    assert text.count("VERIFICATION EXECUTION GATE") >= 2  # gate + final checklist


@pytest.mark.parametrize("path", DECOMPOSERS, ids=lambda p: p.name)
def test_decomposer_requires_repo_lint_target(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "repo's lint/type target" in text
