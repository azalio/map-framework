"""
Pytest tests for .claude/hooks/detect-clarification-triggers.py
UserPromptSubmit hook.

The hook detects two trigger classes in the user's prompt:
  1. Explicit clarification-invitation language (English + Russian)
  2. Long-running / async / durability language (English + Russian)

When matched, it emits hookSpecificOutput.additionalContext (non-blocking,
exit 0). When not matched, it stays silent (no stdout, exit 0).

These tests cover the original failure case from the user's feedback
(2026-04-28): "integrate me a tool that runs up to 5 minutes; ask if not
clear" — both signals must fire on that prompt.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).parent.parent.parent
    / ".claude"
    / "hooks"
    / "detect-clarification-triggers.py"
)


def run_hook(prompt: str) -> tuple[int, str, str]:
    """Execute the hook with a given user prompt."""
    payload = {"prompt": prompt}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def parse_output(stdout: str) -> dict:
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def get_context(stdout: str) -> str:
    payload = parse_output(stdout)
    return payload.get("hookSpecificOutput", {}).get("additionalContext", "")


# =============================================================================
# Original failure case (the prompt from the 2026-04-28 user feedback)
# =============================================================================


def test_original_failure_english_fires_both_triggers():
    code, stdout, _ = run_hook(
        "Integrate me a tool that runs up to 5 minutes. "
        "If something is not clear — ask. "
        "Do not assume anything by yourself."
    )
    assert code == 0
    ctx = get_context(stdout)
    assert "explicitly invited clarification" in ctx
    assert "long-running" in ctx or "async" in ctx
    assert "in-process memory" in ctx


def test_original_failure_russian_fires_both_triggers():
    code, stdout, _ = run_hook(
        "интегрируй мне внешний tool, может работать до 5 минут. "
        "если что-то непонятно - спрашивай"
    )
    assert code == 0
    ctx = get_context(stdout)
    assert "explicitly invited clarification" in ctx
    assert "in-process memory" in ctx


# =============================================================================
# Clarification trigger only
# =============================================================================


@pytest.mark.parametrize(
    "prompt",
    [
        "Refactor the auth module. Feel free to ask about edge cases.",
        "Add caching. Ask if anything is unclear.",
        "Don't assume the database driver — clarify which one we use.",
        "Поправь баг. Уточняй если что-то непонятно.",
        "Добавь логирование. Спрашивай по ходу дела.",
        "Сделай рефакторинг. Не предполагай, задавай вопросы.",
    ],
)
def test_clarification_trigger_fires(prompt):
    code, stdout, _ = run_hook(prompt)
    assert code == 0
    ctx = get_context(stdout)
    assert "explicitly invited clarification" in ctx


# =============================================================================
# Durability trigger only
# =============================================================================


@pytest.mark.parametrize(
    "prompt",
    [
        "Add a webhook handler for stripe events",
        "Build a long-running batch job for nightly processing",
        "Implement an async task queue using Celery",
        "Add a 60 second timeout for slow API calls",
        "Process this in the background worker",
        "Сделай асинхронный вызов внешнего API",
        "Запусти задачу в фоне",
        "Добавь обработчик вебхука",
        "Длительная операция: 10 минут",
    ],
)
def test_durability_trigger_fires(prompt):
    code, stdout, _ = run_hook(prompt)
    assert code == 0
    ctx = get_context(stdout)
    assert "long-running" in ctx or "async" in ctx


# =============================================================================
# Negative tests: no false positives
# =============================================================================


@pytest.mark.parametrize(
    "prompt",
    [
        "Add a button to the login page",
        "Fix the typo in the README",
        "Increase the timeout from 3 seconds to 5 seconds",  # small magnitudes
        "Update the package version to 1.2.3",
        "Поправь опечатку",
        "Добавь кнопку на страницу",
        "Обнови зависимости",
    ],
)
def test_no_false_positive(prompt):
    code, stdout, _ = run_hook(prompt)
    assert code == 0
    assert stdout.strip() == "", (
        f"Expected silent (no stdout), got: {stdout!r}"
    )


# =============================================================================
# Robustness: malformed input never blocks
# =============================================================================


def test_malformed_json_exits_zero_silently():
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json",
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_empty_prompt_exits_zero_silently():
    code, stdout, _ = run_hook("")
    assert code == 0
    assert stdout.strip() == ""


def test_missing_prompt_field_exits_zero_silently():
    payload = {"session_id": "abc", "cwd": "/"}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_prompt_under_alternate_field_names():
    """Hook accepts 'prompt', 'user_prompt', or 'userPrompt'."""
    for field in ("prompt", "user_prompt", "userPrompt"):
        payload = {field: "Add a webhook handler"}
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, f"failed for field {field}"
        ctx = get_context(result.stdout)
        assert "long-running" in ctx or "async" in ctx, (
            f"hook did not fire on field {field}: {result.stdout!r}"
        )
