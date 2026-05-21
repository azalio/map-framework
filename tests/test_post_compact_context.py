import json
import os
import subprocess
from pathlib import Path


def _run_hook(tmp_project_dir: Path, stdin_payload: dict) -> tuple[int, str, str]:
    hook_path = Path(".claude/hooks/post-compact-context.py")
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


def test_post_compact_reprime_includes_state_constraints_and_authority(
    tmp_path: Path,
) -> None:
    # post-compact-context.py resolves branches relative to CLAUDE_PROJECT_DIR;
    # a temp project without git metadata intentionally falls back to default.
    branch = "default"
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
                "current_subtask_id": "ST-001",
            }
        ),
        encoding="utf-8",
    )
    (branch_dir / "blueprint.json").write_text(
        json.dumps(
            {
                "hard_constraints": [
                    {"id": "HC-1", "description": "Preserve retry behavior"}
                ],
                "subtasks": [
                    {
                        "id": "ST-001",
                        "title": "Implement retry handling",
                        "validation_criteria": ["VC1 [AC-1]: retryable timeout"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (branch_dir / "retry_quarantine.json").write_text(
        json.dumps(
            {
                "quarantines": [
                    {
                        "subtask_id": "ST-001",
                        "monitor_rejection_summary": "Forgot the retryable timeout path.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    code, out, err = _run_hook(tmp_path, {})

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    additional = payload["hookSpecificOutput"]["additionalContext"]
    assert "MAP RE-PRIME" in additional
    assert "workflow=map-efficient" in additional
    assert "phase=ACTOR" in additional
    assert "Required next action" in additional
    assert "HC-1" in additional
    assert "AC-1" in additional
    assert "Last Monitor rejection" in additional
    assert "source files, tests, schemas, and configs beat" in additional


def test_post_compact_reprime_remains_silent_without_artifacts(tmp_path: Path) -> None:
    code, out, err = _run_hook(tmp_path, {})

    assert code == 0
    assert err == ""
    assert out == "{}"
