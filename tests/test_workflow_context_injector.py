import json
import os
import subprocess
from pathlib import Path


def _run_hook(tmp_project_dir: Path, stdin_payload: dict) -> tuple[int, str, str]:
    hook_path = Path(".claude/hooks/workflow-context-injector.py")
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_project_dir)

    proc = subprocess.run(
        ["python3", str(hook_path)],
        input=json.dumps(stdin_payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def test_injects_for_edit_when_step_state_exists(tmp_path: Path) -> None:
    branch = (
        subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        .stdout.strip()
        .replace("/", "-")
    )

    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "1.55",
                "current_step_phase": "REVIEW_PLAN",
                "current_subtask_id": "ST-001",
                "subtask_index": 0,
                "subtask_sequence": ["ST-001", "ST-002"],
                "plan_approved": False,
                "execution_mode": "batch",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "[MAP]" in additional
    assert "1.55" in additional
    assert "REVIEW_PLAN" in additional
    assert "ST-001" in additional
    assert "REQUIRED" in additional


def test_skips_for_readonly_bash(tmp_path: Path) -> None:
    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert code == 0
    assert err == ""
    assert out == "{}"


def test_injects_for_pytest_bash_when_step_state_exists(tmp_path: Path) -> None:
    branch = (
        subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        .stdout.strip()
        .replace("/", "-")
    )

    state_dir = tmp_path / ".map" / branch
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "step_state.json").write_text(
        json.dumps(
            {
                "current_step_id": "2.8",
                "current_step_phase": "TESTS_GATE",
                "current_subtask_id": "ST-002",
                "subtask_index": 1,
                "subtask_sequence": ["ST-001", "ST-002"],
                "plan_approved": True,
                "execution_mode": "step_by_step",
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(
        tmp_path,
        {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}},
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "2.8" in additional
    assert "TESTS_GATE" in additional
    assert "ST-002" in additional
