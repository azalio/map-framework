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
        check=False,
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
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, capture_output=True, check=False)
    (root / ".seed").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=False)
    subprocess.run(["git", "checkout", "-b", branch], cwd=root, capture_output=True, check=False)


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


# ── token_report output mode tests ──


def _setup_token_report_project(tmp_path: Path, branch: str) -> Path:
    """Create a project with token accounting data and git branch."""
    scripts_dir = tmp_path / ".map" / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(SHIPPED_RUNNER, scripts_dir / "map_step_runner.py")
    shutil.copy(SHIPPED_SCRIPTS / "map_utils.py", scripts_dir / "map_utils.py")
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True)

    # Write token_log.jsonl with two subtask entries
    log = branch_dir / "token_log.jsonl"
    log.write_text(
        json.dumps({
            "ts": "2026-06-26T10:00:00Z",
            "subtask_id": "ST-001",
            "phase": "ACTOR",
            "agent": "actor",
            "model": "claude-sonnet-4-6",
            "msg_id": "msg_A",
            "input": 5000,
            "output": 2000,
            "cache_creation": 1000,
            "cache_read": 30000,
        }) + "\n" +
        json.dumps({
            "ts": "2026-06-26T10:05:00Z",
            "subtask_id": "ST-001",
            "phase": "ACTOR",
            "agent": "actor",
            "model": "claude-sonnet-4-6",
            "msg_id": "msg_B",
            "input": 3000,
            "output": 800,
            "cache_creation": 0,
            "cache_read": 15000,
        }) + "\n" +
        json.dumps({
            "ts": "2026-06-26T10:10:00Z",
            "subtask_id": "ST-002",
            "phase": "MONITOR",
            "agent": "monitor",
            "model": "claude-haiku-4-5",
            "msg_id": "msg_C",
            "input": 1000,
            "output": 400,
            "cache_creation": 500,
            "cache_read": 5000,
        }) + "\n"
    )

    # Write step_state.json
    (branch_dir / "step_state.json").write_text(
        json.dumps({"current_subtask_id": "ST-002", "current_step_phase": "MONITOR"})
    )
    _init_git_branch(tmp_path, branch)
    return branch_dir


def _run_report_command(tmp_path: Path, branch: str, *flags: str) -> str:
    """Run token_report via the shipped runner for a given branch and flags."""
    r = subprocess.run(
        [sys.executable, str(SHIPPED_RUNNER), "token_report", branch, *flags],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    return r.stdout


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_json_export(tmp_path):
    """--json exports valid JSON with aggregate, by_subtask, by_agent."""
    branch = "feat-json"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch, "--json")
    payload = json.loads(out)
    assert payload["branch"] == branch
    assert payload["aggregate"]["input"] == 9000
    assert "ST-001" in payload["by_subtask"]
    assert "ST-002" in payload["by_subtask"]
    assert "actor" in payload["by_agent"]
    assert "monitor" in payload["by_agent"]


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_csv_export(tmp_path):
    """--csv exports CSV with aggregate, subtask, agent, phase rows."""
    branch = "feat-csv"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch, "--csv")
    lines = out.strip().splitlines()
    assert len(lines) >= 4  # header + aggregate + subtasks + agents
    assert lines[0].startswith("dimension,key,")
    assert any("aggregate" in line for line in lines)
    assert any("ST-001" in line for line in lines)


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_dashboard(tmp_path):
    """--dashboard renders box-drawing visual output."""
    branch = "feat-dash"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch, "--dashboard")
    assert "MAP Token Report" in out
    assert "feat-dash" in out
    assert "Per-subtask" in out
    assert "By agent" in out
    assert "By model" in out
    assert "█" in out or "░" in out  # bar chart characters
    assert "$" in out


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_history_no_snapshots(tmp_path):
    """--history with no recorded snapshots shows guidance message."""
    branch = "feat-hist-empty"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch, "--history")
    assert "No session history" in out


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_snapshot_and_history(tmp_path):
    """record_session_snapshot writes history; --history shows trends."""
    branch = "feat-hist"
    _setup_token_report_project(tmp_path, branch)

    # Record two snapshots
    r1 = subprocess.run(
        [sys.executable, str(SHIPPED_RUNNER), "token_report", branch, "--finalize"],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert json.loads(r1.stdout)["status"] == "success"

    r2 = subprocess.run(
        [sys.executable, str(SHIPPED_RUNNER), "token_report", branch, "--finalize"],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert json.loads(r2.stdout)["status"] == "success"

    # History file should have two lines
    hist = tmp_path / ".map" / branch / "token_history.jsonl"
    lines = [line for line in hist.read_text().splitlines() if line.strip()]
    assert len(lines) == 2

    out = _run_report_command(tmp_path, branch, "--history")
    assert "Token history" in out
    assert "feat-hist" in out
    assert "—" in out  # vs-prev baseline marker
    assert "Trend" in out
    assert "Cost:" in out
    assert "Cache:" in out


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_estimate_no_history(tmp_path):
    """--estimate with no history shows fallback guidance."""
    branch = "feat-est-empty"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch, "--estimate")
    assert "No session history" in out
    assert "Spent so far" in out


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_estimate_with_history(tmp_path):
    """--estimate with history shows weighted avg, range, median, remaining."""
    branch = "feat-est"
    _setup_token_report_project(tmp_path, branch)

    # Record one snapshot, then run estimate
    subprocess.run(
        [sys.executable, str(SHIPPED_RUNNER), "token_report", branch, "--finalize"],
        capture_output=True, text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    out = _run_report_command(tmp_path, branch, "--estimate")
    assert "Cost estimate" in out
    assert "Weighted avg" in out
    assert "Range" in out
    assert "Median" in out
    assert "Spent so far" in out
    assert "Remaining est" in out


@pytest.mark.skipif(not SHIPPED_RUNNER.is_file(), reason="shipped runner missing")
def test_token_report_default_still_works(tmp_path):
    """Default mode (no flags) still renders classic text table."""
    branch = "feat-default"
    _setup_token_report_project(tmp_path, branch)
    out = _run_report_command(tmp_path, branch)
    assert "Token accounting" in out
    assert "feat-default" in out
    assert "subtask" in out or "ST-001" in out  # table header or subtask id
    assert "cache hit ratio" in out.lower()
    assert "est cost" in out.lower()
