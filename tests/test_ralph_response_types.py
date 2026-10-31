"""Both generated providers tolerate unstructured PostToolUse responses."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[".claude", ".codex"])
def logger(request, monkeypatch, tmp_path):
    """Load the generated provider hook against an isolated project."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    path = ROOT / request.param / "hooks/ralph-iteration-logger.py"
    return path, runpy.run_path(str(path))


@pytest.mark.parametrize("tool", ["Bash", "apply_patch", "Edit", "Write"])
@pytest.mark.parametrize("response", ["command completed", "Success", ["output"], 42, True, None, {}])
def test_unstructured_responses_use_default_score(logger, tool, response):
    """Missing structured indicators must not crash or infer failure from text."""
    _, module = logger
    assert module["calculate_effectiveness"](tool, response) == 1.0


@pytest.mark.parametrize(("tool", "response", "expected"), [
    ("Bash", {"exit_code": 0, "output": "error"}, 1.0),
    ("Bash", {"exitCode": 2}, 0.3),
    ("Bash", {"status": "3"}, 0.3),
    ("Bash", {"returnCode": 4}, 0.3),
    ("Bash", {"return_code": 5}, 0.3),
    ("Bash", {"error": "failed"}, 0.3),
    ("apply_patch", {"success": False}, 0.3),
    ("apply_patch", {"error": "failed"}, 0.3),
    ("Edit", {"success": False}, 0.3),
    ("Write", {"success": True}, 1.0),
])
def test_structured_response_semantics_are_preserved(logger, tool, response, expected):
    """Structured success and failure indicators retain their existing scores."""
    _, module = logger
    assert module["calculate_effectiveness"](tool, response) == expected


@pytest.mark.parametrize(("tool", "response"), [("Bash", "command completed"), ("apply_patch", "Success")])
def test_string_response_hook_logs_iteration_and_summary(logger, tmp_path, tool, response):
    """Real hook execution must exit cleanly and persist its observation."""
    path, _ = logger
    env = os.environ.copy()
    env.pop("MAP_INVOKED_BY", None)
    env.pop("RALPH_DEBUG", None)
    result = subprocess.run(
        [sys.executable, str(path)], cwd=tmp_path, env=env,
        input=json.dumps({"tool_name": tool, "tool_response": response, "tool_input": {}, "session_id": "test"}),
        text=True, capture_output=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}
    assert "Traceback" not in result.stderr
    logs = list((tmp_path / ".map").glob("*/iteration_log.jsonl"))
    assert len(logs) == 1
    entry = json.loads(logs[0].read_text())
    assert entry["tool"] == tool
    assert entry["effectiveness"] == 1.0
    assert entry["session_id"] == "test"
    summary = json.loads(logs[0].with_name("iteration_summary.json").read_text())
    assert summary["entry_count"] == 1
    assert summary["aggregate"]["total_iterations"] == 1
