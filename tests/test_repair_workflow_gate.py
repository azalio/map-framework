"""Provider hooks suspend parent writes without changing private workflow gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.delivery.template_renderer import get_environment

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "src/mapify_cli/templates_src"


@pytest.fixture(params=["hooks/workflow-gate.py.jinja", "codex/hooks/workflow-gate.py.jinja"])
def gate(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-b", "repair-test", str(project)], check=True,
                   capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Gate Test", "-c", "user.email=gate@example.invalid",
         "commit", "--allow-empty", "-m", "Fixture base"],
        cwd=project, check=True, capture_output=True, text=True,
    )
    hook = tmp_path / "workflow-gate.py"
    hook.write_text(get_environment(SOURCES).get_template(request.param).render(),
                    encoding="utf-8")
    return hook, project


def write_state(project: Path, phase: str = "ACTOR", *, interrupted: bool = True,
                marker: Any = None) -> Path:
    folder = project / ".map/repair-test"
    folder.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "current_step_phase": phase, "current_subtask_id": "ST-001",
        "workflow_status": "IN_PROGRESS", "pending_steps": ["2.3", "2.4"],
        "subtask_phases": {"ST-001": "2.3"},
    }
    if interrupted:
        state["active_interruption"] = marker if marker is not None else {
            "operation_id": "repair-one", "contract_digest": "pinned-contract",
        }
    path = folder / "step_state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    (folder / "blueprint.json").write_text(json.dumps({"subtasks": [{
        "id": "ST-001", "affected_files": ["src/app.py"],
    }]}), encoding="utf-8")
    return path


def invoke(gate: tuple[Path, Path], tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    hook, project = gate
    result = subprocess.run(
        [sys.executable, "-I", str(hook)], cwd=project,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
        input=json.dumps({"tool_name": tool, "tool_input": payload}),
        capture_output=True, text=True, check=True,
    )
    assert not result.stderr, result.stderr
    return json.loads(result.stdout)


def assert_denied(response: dict[str, Any]) -> None:
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("phase", ["ACTOR", "MONITOR", "COMPLETE", "RESEARCH", "PREDICTOR"])
@pytest.mark.parametrize("target", ["src/app.py", "unrelated.py", "docs/runbook.md"])
def test_suspension_overrides_phase_wave_and_exceptions(
    gate: tuple[Path, Path], phase: str, target: str,
) -> None:
    write_state(gate[1], phase)
    assert_denied(invoke(gate, "Edit", {"file_path": str(gate[1] / target)}))


@pytest.mark.parametrize("marker", [{}, [], False, "broken"])
def test_malformed_marker_stays_suspended(gate: tuple[Path, Path], marker: Any) -> None:
    write_state(gate[1], marker=marker)
    assert_denied(invoke(gate, "Write", {"file_path": "src/app.py"}))


def test_null_marker_is_inactive(gate: tuple[Path, Path]) -> None:
    path = write_state(gate[1])
    state = json.loads(path.read_text(encoding="utf-8"))
    state["active_interruption"] = None
    path.write_text(json.dumps(state), encoding="utf-8")
    assert invoke(gate, "Edit", {"file_path": "src/app.py"}) == {}


def test_mixed_artifact_application_write_is_denied(gate: tuple[Path, Path]) -> None:
    write_state(gate[1])
    assert_denied(invoke(gate, "MultiEdit", {"edits": [
        {"file_path": ".map/repair-test/research/findings.md"},
        {"file_path": "src/app.py"},
    ]}))


def test_artifacts_allowed_but_runner_state_protected(gate: tuple[Path, Path]) -> None:
    write_state(gate[1])
    assert invoke(gate, "Write", {"file_path": ".map/repair-test/research/findings.md"}) == {}
    assert_denied(invoke(gate, "Write", {"file_path": ".map/repair-test/step_state.json"}))


@pytest.mark.parametrize("command", [
    "git status --short", "git --no-pager diff --no-ext-diff --no-textconv -- src/app.py",
    "cat src/app.py", "git branch --show-current",
    "python3 .map/scripts/map_step_runner.py get_interruption_status repair-test",
    "python3 .map/scripts/map_step_runner.py begin_repair repair-test --reason lint",
    "python3 .map/scripts/map_step_runner.py finish_repair repair-test",
    "python3 .map/scripts/map_orchestrator.py get_interruption_status repair-test",
    "python3 .map/scripts/map_orchestrator.py verify_repair repair-one --monitor-file receipt.json",
    "python3 .map/scripts/map_orchestrator.py finish_repair repair-one --branch repair-test",
])
def test_read_check_and_canonical_runner_allowed(gate: tuple[Path, Path], command: str) -> None:
    write_state(gate[1])
    assert invoke(gate, "Bash", {"command": command}) == {}


@pytest.mark.parametrize("command", [
    "printf fixed > src/app.py", "touch src/app.py", "python3 -c 'open(\"app.py\",\"w\")'",
    "git reset --hard", "unknown-writer", "printf fixed > \"$FILE\"",
    "pytest -q", "python3 -m pytest tests/", "make check", "rg --pre touch pattern src/",
    "git diff", "git --no-pager diff --ext-diff", "cat app.py & touch app.py",
    "git --no-pager diff -- --no-ext-diff --no-textconv",
    "python3 .map/scripts/map_orchestrator.py scrub repair-test",
    "python3 .map/scripts/map_step_runner.py get_interruption_status repair-test; touch app.py",
    "git status\ntouch app.py", "cat $(touch app.py)",
    "python3 .map/scripts/map_step_runner.py get_interruption_status repair-test > app.py",
    "python3 other/.map/scripts/map_step_runner.py finish_repair repair-test",
])
def test_mutating_or_unknown_bash_denied(gate: tuple[Path, Path], command: str) -> None:
    write_state(gate[1])
    assert_denied(invoke(gate, "Bash", {"command": command}))


def test_private_checkout_ordinary_actor_edit_allowed(gate: tuple[Path, Path]) -> None:
    write_state(gate[1], interrupted=False)
    assert invoke(gate, "Edit", {"file_path": "src/app.py"}) == {}


@pytest.mark.parametrize("journal_content", ["broken-json", "{}", '{"branch":"repair-test","stage":"prepared"}'])
def test_durable_repair_evidence_survives_state_corruption(
    gate: tuple[Path, Path], journal_content: str,
) -> None:
    path = write_state(gate[1], interrupted=False)
    path.write_text("broken-json", encoding="utf-8")
    journal = gate[1] / ".git/map-repairs" / ("repair-" + "a" * 24) / "journal.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(journal_content, encoding="utf-8")
    assert_denied(invoke(gate, "Edit", {"file_path": "src/app.py"}))


def test_finished_journal_does_not_suspend(gate: tuple[Path, Path]) -> None:
    write_state(gate[1], interrupted=False)
    journal = gate[1] / ".git/map-repairs" / ("repair-" + "a" * 24) / "journal.json"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"branch": "repair-test", "stage": "done"}), encoding="utf-8")
    assert invoke(gate, "Edit", {"file_path": "src/app.py"}) == {}


def test_unrelated_corrupt_state_preserves_fail_open(gate: tuple[Path, Path]) -> None:
    path = write_state(gate[1], interrupted=False)
    path.write_text("not-json", encoding="utf-8")
    assert invoke(gate, "Edit", {"file_path": "src/app.py"}) == {}
