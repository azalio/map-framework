"""Tests for the map-token-meter SubagentStop/Stop hook.

The hook is a thin shell over ``map_step_runner.py record_token_event``: it
reads the transcript_path Claude Code hands it and asks the runner to attribute
that transcript's token usage to the active subtask. We test both the silent
no-op paths (CLAUDE_PROJECT_DIR rules) and a realistic positive path that
proves the side-effect artifacts get written (per the repo rule that a hook
returning ``{}`` only proves the silent path).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "map-token-meter.py"
SHIPPED_SCRIPTS = REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"
SHIPPED_RUNNER = SHIPPED_SCRIPTS / "map_step_runner.py"

TRANSCRIPT = (
    '{"type":"assistant","uuid":"u1","message":{"role":"assistant","id":"msg_1",'
    '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
    '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
    '{"type":"assistant","uuid":"u2","message":{"role":"assistant","id":"msg_2",'
    '"model":"claude-opus-4-7","usage":{"input_tokens":300,"output_tokens":50,'
    '"cache_creation_input_tokens":0,"cache_read_input_tokens":9000}}}\n'
)


def _run_hook(stdin_text: str, project_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=str(project_dir),
        env=env,
    )


def test_malformed_stdin_is_silent(tmp_path):
    result = _run_hook("not json", tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "{}"


def test_missing_transcript_path_is_silent(tmp_path):
    result = _run_hook(json.dumps({"session_id": "s1"}), tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "{}"
    assert not (tmp_path / ".map").exists(), "no-op must not create accounting artifacts"


def _init_git_branch(root: Path, branch: str) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, capture_output=True)
    (root / ".seed").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)
    subprocess.run(["git", "checkout", "-b", branch], cwd=root, capture_output=True)


def _setup_project(tmp_path: Path, branch: str) -> Path:
    """Lay out a generated-project shape: .map/scripts/ runner (+ its map_utils
    sibling) + branch state + a git branch. Returns the branch artifact dir."""
    scripts_dir = tmp_path / ".map" / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SHIPPED_RUNNER, scripts_dir / "map_step_runner.py")
    shutil.copy(SHIPPED_SCRIPTS / "map_utils.py", scripts_dir / "map_utils.py")
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps({"current_subtask_id": "ST-005", "current_step_phase": "MONITOR"})
    )
    _init_git_branch(tmp_path, branch)
    return branch_dir


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_subagentstop_meters_agent_transcript(tmp_path):
    """On SubagentStop the hook must read agent_transcript_path (the sub-agent's
    own transcript) and attribute to agent_type — NOT re-sweep the parent
    transcript_path. We point the two paths at different files and prove only
    the agent transcript's tokens are recorded under the agent_type."""
    branch = "feat-meter"
    branch_dir = _setup_project(tmp_path, branch)
    agent_transcript = tmp_path / "agent.jsonl"
    agent_transcript.write_text(TRANSCRIPT)  # input 1300 total
    # Decoy parent transcript the hook must IGNORE on SubagentStop.
    parent_transcript = tmp_path / "parent.jsonl"
    parent_transcript.write_text(
        '{"type":"assistant","uuid":"p1","message":{"role":"assistant","id":"msg_parent",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":99999,"output_tokens":1}}}\n'
    )

    result = _run_hook(
        json.dumps(
            {
                "agent_transcript_path": str(agent_transcript),
                "transcript_path": str(parent_transcript),
                "agent_type": "monitor",
            }
        ),
        tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "{}"

    payload = json.loads((branch_dir / "token_accounting.json").read_text())
    assert payload["aggregate"]["input"] == 1300, "must meter the agent transcript only"
    assert "monitor" in payload["by_agent"], "must attribute to agent_type"
    assert "msg_parent" not in (branch_dir / "token_log.jsonl").read_text()


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_stop_meters_main_transcript_as_orchestrator(tmp_path):
    """On Stop (no agent_transcript_path) the hook sweeps the main transcript
    and labels those driving turns as the orchestrator."""
    branch = "feat-meter"
    branch_dir = _setup_project(tmp_path, branch)
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(TRANSCRIPT)

    result = _run_hook(json.dumps({"transcript_path": str(transcript)}), tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "{}"

    payload = json.loads((branch_dir / "token_accounting.json").read_text())
    assert payload["aggregate"]["input"] == 1300
    assert "ST-005" in payload["by_subtask"]
    assert "orchestrator" in payload["by_agent"]


# Claude Code writes ONE assistant turn as several JSONL lines (one per
# content / tool_use block), all sharing the same message.id and the same
# cumulative usage. The meter must count such a turn exactly once.
_REPEATED_TURN = (
    '{"type":"assistant","uuid":"u1a","message":{"role":"assistant","id":"msg_R",'
    '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
    '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
    '{"type":"assistant","uuid":"u1b","message":{"role":"assistant","id":"msg_R",'
    '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
    '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
    '{"type":"assistant","uuid":"u1c","message":{"role":"assistant","id":"msg_R",'
    '"model":"claude-opus-4-7","usage":{"input_tokens":1000,"output_tokens":200,'
    '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
)


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_repeated_msgid_in_window_counted_once(tmp_path):
    """A turn split across 3 JSONL lines (same msg_id) must be metered ONCE.

    Regression: dedup against the persisted seen_ids only let every repeated
    line through, doubling/tripling est_cost on real sessions."""
    branch = "feat-meter"
    branch_dir = _setup_project(tmp_path, branch)
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(_REPEATED_TURN)

    result = _run_hook(json.dumps({"transcript_path": str(transcript)}), tmp_path)
    assert result.returncode == 0

    payload = json.loads((branch_dir / "token_accounting.json").read_text())
    agg = payload["aggregate"]
    assert agg["input"] == 1000, "repeated msg_id counted >1x (input)"
    assert agg["output"] == 200, "repeated msg_id counted >1x (output)"
    assert agg["cache_read"] == 8000, "repeated msg_id counted >1x (cache_read)"
    assert payload["event_count"] == 1, "one logical turn must be one event"
    # token_log holds exactly one row for the turn.
    rows = [
        line for line in (branch_dir / "token_log.jsonl").read_text().splitlines() if line.strip()
    ]
    assert len(rows) == 1


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_repeated_msgid_keeps_most_complete_copy(tmp_path):
    """When repeated lines for one msg_id disagree (a streaming partial vs the
    final line), the meter keeps the copy with the most total tokens."""
    branch = "feat-meter"
    branch_dir = _setup_project(tmp_path, branch)
    transcript = tmp_path / "main.jsonl"
    transcript.write_text(
        # Partial line first (small usage), then the final cumulative line.
        '{"type":"assistant","uuid":"p1","message":{"role":"assistant","id":"msg_P",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":100,"output_tokens":10,'
        '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n'
        '{"type":"assistant","uuid":"p2","message":{"role":"assistant","id":"msg_P",'
        '"model":"claude-opus-4-7","usage":{"input_tokens":100,"output_tokens":200,'
        '"cache_creation_input_tokens":500,"cache_read_input_tokens":8000}}}\n'
    )

    result = _run_hook(json.dumps({"transcript_path": str(transcript)}), tmp_path)
    assert result.returncode == 0

    agg = json.loads((branch_dir / "token_accounting.json").read_text())["aggregate"]
    assert agg["output"] == 200, "must keep the most complete copy, not the partial"
    assert agg["cache_read"] == 8000
