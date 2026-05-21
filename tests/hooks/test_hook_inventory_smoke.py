"""Smoke every configured Claude hook on both silent and active paths.

This is intentionally broader than the focused unit tests. It prevents a new
hook from being wired into `.claude/settings.json` without a realistic smoke
scenario that proves more than the silent `{}` path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"


@dataclass(frozen=True)
class HookRun:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HookCase:
    name: str
    payload: dict[str, object]
    assert_result: Callable[[HookRun, Path], None]
    cwd_factory: Callable[[Path], Path] | None = None
    env_extra: dict[str, str] | None = None


def _configured_hook_names() -> set[str]:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    names: set[str] = set()
    for event_entries in settings.get("hooks", {}).values():
        for entry in event_entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                if not isinstance(command, str):
                    continue
                for part in command.replace('"', "").split():
                    if ".claude/hooks/" in part:
                        names.add(Path(part).name)
    return names


def _run_hook(
    hook_name: str,
    payload: dict[str, object],
    project: Path,
    *,
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> HookRun:
    hook_path = HOOKS_DIR / hook_name
    command = ["bash", str(hook_path)] if hook_path.suffix == ".sh" else [sys.executable, str(hook_path)]
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(project),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=cwd or REPO_ROOT,
        env=env,
        check=False,
        timeout=20,
    )
    return HookRun(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def _json(stdout: str) -> dict[str, object]:
    return json.loads(stdout or "{}")


def _assert_noop(run: HookRun, _project: Path) -> None:
    assert run.returncode == 0
    assert run.stdout == "{}" or run.stdout == ""


def _assert_deny(run: HookRun, _project: Path) -> None:
    assert run.returncode == 0
    payload = _json(run.stdout)
    output = payload.get("hookSpecificOutput", {})
    assert isinstance(output, dict)
    assert output.get("permissionDecision") == "deny"


def _assert_contains(*needles: str) -> Callable[[HookRun, Path], None]:
    def _inner(run: HookRun, _project: Path) -> None:
        assert run.returncode == 0
        for needle in needles:
            assert needle in run.stdout

    return _inner


def _assert_iteration_logged(run: HookRun, project: Path) -> None:
    assert run.returncode == 0
    assert run.stdout == "{}"
    assert (project / ".map" / "default" / "iteration_log.jsonl").is_file()


def _assert_restore_point(run: HookRun, project: Path) -> None:
    assert run.returncode == 0
    assert run.stdout == "{}"
    assert (project / ".map" / "default" / "restore_point.json").is_file()


def _assert_transcript_saved(run: HookRun, project: Path) -> None:
    assert run.returncode == 0
    assert run.stdout == "{}"
    assert (project / ".map" / "default" / "last-transcript.txt").is_file()


def _assert_end_turn_blocks_syntax(run: HookRun, _project: Path) -> None:
    assert run.returncode == 2
    assert "Python syntax error" in run.stderr


def _make_dirty_git_repo(root: Path) -> Path:
    worktree = root / "dirty-git"
    worktree.mkdir()
    subprocess.run(["git", "init"], cwd=worktree, capture_output=True, text=True, check=True)
    (worktree / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    return worktree


@pytest.fixture
def hook_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    branch = project / ".map" / "default"
    branch.mkdir(parents=True)
    (project / ".claude").mkdir()
    (project / ".claude" / "ralph-loop-config.json").write_text(
        json.dumps(
            {
                "ralph_loop": {
                    "thrashing_detection": {
                        "window_size": 2,
                        "same_file_repeat_threshold": 2,
                        "effectiveness_threshold": 0.5,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (project / ".map" / "config.yaml").write_text(
        "compression_policy: aggressive\n"
        "compression_threshold_tokens: 1\n"
        "compression_focus: preserve MAP workflow state\n",
        encoding="utf-8",
    )
    (branch / "step_state.json").write_text(
        json.dumps(
            {
                "workflow": "map-efficient",
                "current_step_id": "2.3",
                "current_step_phase": "ACTOR",
                "current_subtask_id": "ST-001",
                "subtask_index": 0,
                "subtask_sequence": ["ST-001"],
                "plan_approved": True,
                "execution_mode": "batch",
                "constraints": {"scope_glob": "src/*"},
            }
        ),
        encoding="utf-8",
    )
    (branch / "blueprint.json").write_text(
        json.dumps(
            {
                "hard_constraints": [
                    {"id": "HC-1", "description": "Preserve retry behavior"}
                ],
                "subtasks": [
                    {
                        "id": "ST-001",
                        "title": "Implement retry handling",
                        "validation_criteria": ["VC1 [AC-1]: retry works"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (branch / "retry_quarantine.json").write_text(
        json.dumps(
            {
                "quarantines": [
                    {
                        "subtask_id": "ST-001",
                        "monitor_rejection_summary": "Actor forgot retry path.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (branch / "iteration_log.jsonl").write_text(
        json.dumps({"tool": "Edit", "file": "src/retry.py", "effectiveness": 1.0})
        + "\n",
        encoding="utf-8",
    )
    (project / "transcript.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 1000, "output_tokens": 1000},
                    "content": [{"type": "text", "text": "working"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return project


HOOK_CASES: dict[str, list[HookCase]] = {
    "safety-guardrails.py": [
        HookCase("deny-env", {"tool_name": "Edit", "tool_input": {"file_path": ".env"}}, _assert_deny),
        HookCase("allow-src", {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}, _assert_noop),
    ],
    "workflow-gate.py": [
        HookCase("allow-in-scope", {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}, _assert_noop),
        HookCase("deny-out-of-scope", {"tool_name": "Edit", "tool_input": {"file_path": "docs/readme.md"}}, _assert_contains("scope_glob")),
    ],
    "workflow-context-injector.py": [
        HookCase("inject-edit", {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}, _assert_contains("HC-1", "AC-1")),
        HookCase("skip-readonly-bash", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, _assert_noop),
    ],
    "ralph-iteration-logger.py": [
        HookCase("log-edit", {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": "src/retry.py"}, "tool_response": {"success": True}}, _assert_iteration_logged),
    ],
    "ralph-context-pruner.py": [
        HookCase("save-restore", {}, _assert_restore_point),
    ],
    "pre-compact-save-transcript.py": [
        HookCase("save-transcript", {"transcript_path": "__PROJECT__/transcript.jsonl", "session_id": "s1"}, _assert_transcript_saved),
        HookCase("missing-transcript", {"transcript_path": "__PROJECT__/missing.jsonl", "session_id": "s1"}, _assert_noop),
    ],
    "post-compact-context.py": [
        HookCase("reprime", {}, _assert_contains("MAP RE-PRIME", "HC-1", "AC-1")),
    ],
    "detect-clarification-triggers.py": [
        HookCase("inject", {"prompt": "Сделай webhook и уточняй если что-то непонятно"}, _assert_contains("additionalContext")),
        HookCase("skip", {"prompt": "Fix typo"}, _assert_noop),
    ],
    "context-meter.py": [
        HookCase("compact-nudge", {"transcript_path": "__PROJECT__/transcript.jsonl"}, _assert_contains("/compact"), env_extra={"PYTHONPATH": str(REPO_ROOT / "src")}),
        HookCase("skip-missing-transcript", {"transcript_path": ""}, _assert_noop, env_extra={"PYTHONPATH": str(REPO_ROOT / "src")}),
    ],
    "end-of-turn.sh": [
        HookCase("non-git-noop", {}, _assert_noop, cwd_factory=lambda project: project),
        HookCase("syntax-block", {}, _assert_end_turn_blocks_syntax, cwd_factory=_make_dirty_git_repo),
    ],
}


def _resolve_project_tokens(value: object, project: Path) -> object:
    if isinstance(value, str):
        return value.replace("__PROJECT__", str(project))
    if isinstance(value, dict):
        return {key: _resolve_project_tokens(val, project) for key, val in value.items()}
    if isinstance(value, list):
        return [_resolve_project_tokens(item, project) for item in value]
    return value


def test_every_configured_hook_has_smoke_cases() -> None:
    configured = _configured_hook_names()

    assert configured == set(HOOK_CASES), (
        "Every hook wired in .claude/settings.json needs explicit positive/no-op "
        f"smoke cases. missing={sorted(configured - set(HOOK_CASES))} "
        f"extra={sorted(set(HOOK_CASES) - configured)}"
    )


@pytest.mark.parametrize(
    ("hook_name", "case"),
    [
        (hook_name, case)
        for hook_name, cases in sorted(HOOK_CASES.items())
        for case in cases
    ],
    ids=lambda value: value.name if isinstance(value, HookCase) else value,
)
def test_configured_hook_smoke_case(
    hook_project: Path, hook_name: str, case: HookCase
) -> None:
    payload = _resolve_project_tokens(case.payload, hook_project)
    assert isinstance(payload, dict)
    cwd = case.cwd_factory(hook_project) if case.cwd_factory else None

    run = _run_hook(
        hook_name,
        payload,
        hook_project,
        cwd=cwd,
        env_extra=case.env_extra,
    )

    case.assert_result(run, hook_project)
