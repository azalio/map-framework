"""End-to-end smoke for the memory hook pipeline (ST-008 / AC-12).

Flow: capture×2 → finalize(new sid, NO SessionEnd) → recall

A fake `claude` executable is injected onto PATH so finalize can call
`claude -p` without needing the real CLI.  The test is unconditional —
no skipif on the real claude binary.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"

# Recognizable body text that the fake claude will emit; asserted in recall output.
FAKE_BODY = "Chose WAL+lazy checkpoint; recall verified."


def _build_fake_claude(tmp_bin: Path) -> Path:
    """Write a fake `claude` executable that emits the memory envelope."""
    inner = json.dumps(
        {
            "title": "Memory smoke digest",
            "body": FAKE_BODY,
            "decisions": ["WAL over flush-on-end"],
            "findings": ["finalize is atomic"],
        }
    )
    envelope = json.dumps(
        {
            "result": inner,
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 40,
            },
        }
    )
    fake = tmp_bin / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdin.read()  # consume any piped prompt\n"
        f"print({envelope!r})\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _make_env(project: Path, tmp_bin: Path) -> dict[str, str]:
    """Build the subprocess environment with fake claude on PATH."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PATH"] = str(tmp_bin) + os.pathsep + env.get("PATH", "")
    # Ensure we do NOT inherit an existing MAP_INVOKED_BY that would silence hooks.
    env.pop("MAP_INVOKED_BY", None)
    return env


def _run_hook(
    hook_name: str,
    payload: Mapping[str, object],
    project: Path,
    tmp_bin: Path,
) -> subprocess.CompletedProcess[str]:
    """Invoke a repo hook binary as a subprocess."""
    hook_path = HOOKS_DIR / hook_name
    cmd = [sys.executable, str(hook_path)]
    return subprocess.run(
        cmd,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=_make_env(project, tmp_bin),
        timeout=20,
        check=False,
    )


@pytest.fixture()
def smoke_project(tmp_path: Path) -> Path:
    """Minimal project skeleton: .git/HEAD + .map/<branch>/sessions/."""
    project = tmp_path / "project"
    project.mkdir()
    git_dir = project / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/smoke-branch\n", encoding="utf-8")
    (project / ".map" / "smoke-branch" / "sessions").mkdir(parents=True)
    return project


@pytest.fixture()
def tmp_bin(tmp_path: Path) -> Path:
    """Temporary bin directory with the fake claude executable."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _build_fake_claude(bin_dir)
    return bin_dir


# ---------------------------------------------------------------------------
# AC-12: full pipeline smoke
# ---------------------------------------------------------------------------


def test_memory_pipeline_capture_finalize_recall(
    smoke_project: Path,
    tmp_bin: Path,
) -> None:
    """capture×2 → finalize(new sid, no SessionEnd) → recall: end-to-end smoke."""
    sessions_dir = smoke_project / ".map" / "smoke-branch" / "sessions"

    # ------------------------------------------------------------------
    # Step 1: capture × 2 for sid-1 via REALISTIC Stop payloads.
    # A real Stop event carries transcript_path (NOT tool_name/tool_input), so
    # the capture hook must recover edited files from the transcript JSONL. The
    # offset sidecar scopes each turn record to the edits made since the prior
    # Stop, so turn 1 sees src/x.py and turn 2 sees src/y.py.
    # ------------------------------------------------------------------
    transcript = smoke_project / "transcript.jsonl"

    def _edit_line(path: str) -> str:
        return json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "Edit", "input": {"file_path": path}}
                    ],
                },
            }
        )

    stop_payload = {
        "session_id": "sid-1",
        "hook_event_name": "Stop",
        "transcript_path": str(transcript),
    }

    # Turn 1: transcript has one edit (src/x.py).
    transcript.write_text(_edit_line("src/x.py") + "\n", encoding="utf-8")
    run1 = _run_hook("map-memory-capture.py", stop_payload, smoke_project, tmp_bin)
    assert run1.returncode == 0, f"capture #1 failed:\n{run1.stderr}"
    assert run1.stdout.strip() in ("{}", ""), f"capture #1 unexpected stdout: {run1.stdout!r}"

    # Turn 2: transcript grows by one edit (src/y.py).
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(_edit_line("src/y.py") + "\n")
    run2 = _run_hook("map-memory-capture.py", stop_payload, smoke_project, tmp_bin)
    assert run2.returncode == 0, f"capture #2 failed:\n{run2.stderr}"
    assert run2.stdout.strip() in ("{}", ""), f"capture #2 unexpected stdout: {run2.stdout!r}"

    # Verify scratch file has 2 "turn" records, each scoped to its turn's edit.
    scratch_file = sessions_dir / "scratch" / "sid-1.jsonl"
    assert scratch_file.is_file(), "capture must create sid-1.jsonl in scratch/"
    records = [json.loads(line) for line in scratch_file.read_text().splitlines() if line.strip()]
    turn_records = [r for r in records if r.get("event") == "turn"]
    assert len(turn_records) == 2, f"expected 2 turn records, got: {records}"
    # files_touched must be recovered from the transcript (regression guard for
    # the Stop-event-carries-no-tool-fields bug).
    assert turn_records[0]["files_touched"] == ["src/x.py"], turn_records
    assert turn_records[1]["files_touched"] == ["src/y.py"], turn_records

    # ------------------------------------------------------------------
    # Step 2: finalize with a NEW sid (sid-2), NO SessionEnd marker
    # VC2/AC-9/HC-2: finalize must handle no SessionEnd gracefully.
    # ------------------------------------------------------------------
    finalize_payload = {"session_id": "sid-2"}
    runf = _run_hook("map-memory-finalize.py", finalize_payload, smoke_project, tmp_bin)
    assert runf.returncode == 0, f"finalize failed:\n{runf.stderr}"
    assert runf.stdout.strip() in ("{}", ""), f"finalize unexpected stdout: {runf.stdout!r}"

    # Exactly one digest .md (NOT under scratch/).
    digests = list(sessions_dir.glob("*.md"))
    assert len(digests) == 1, (
        f"expected exactly 1 digest .md outside scratch/, found: {[str(d) for d in digests]}"
    )
    digest_text = digests[0].read_text(encoding="utf-8")
    assert FAKE_BODY in digest_text, (
        f"digest {digests[0].name} does not contain expected body:\n{digest_text[:400]}"
    )
    # files_touched must survive the capture→finalize→frontmatter chain end to
    # end (both transcript-derived paths land in the digest's frontmatter).
    assert "src/x.py" in digest_text and "src/y.py" in digest_text, (
        f"digest does not carry transcript-derived files_touched:\n{digest_text[:400]}"
    )

    # sid-1.finalized marker must exist; sid-1.jsonl must be deleted.
    finalized_marker = sessions_dir / "scratch" / "sid-1.finalized"
    assert finalized_marker.is_file(), "sid-1.finalized marker must be written by finalize"
    assert not scratch_file.exists(), "sid-1.jsonl must be deleted after finalization"

    # VC4: memory-cost.log must exist with ≥1 JSONL line containing input_tokens.
    cost_log = sessions_dir / "memory-cost.log"
    assert cost_log.is_file(), "memory-cost.log must be written by finalize"
    cost_lines = [line for line in cost_log.read_text().splitlines() if line.strip()]
    assert len(cost_lines) >= 1, "memory-cost.log must have at least one record"
    cost_record = json.loads(cost_lines[0])
    assert "input_tokens" in cost_record, (
        f"cost record missing input_tokens: {cost_record}"
    )

    # ------------------------------------------------------------------
    # Step 3: recall — digest must surface in additionalContext
    # ------------------------------------------------------------------
    recall_payload = {
        "hook_event_name": "SessionStart",
        "prompt": "wal checkpoint recall",
    }
    runr = _run_hook("map-memory-recall.py", recall_payload, smoke_project, tmp_bin)
    assert runr.returncode == 0, f"recall failed:\n{runr.stderr}"

    recall_out = json.loads(runr.stdout)
    additional_context = recall_out["hookSpecificOutput"]["additionalContext"]
    assert FAKE_BODY in additional_context, (
        f"recall additionalContext does not contain expected body.\n"
        f"additionalContext[:400]: {additional_context[:400]}"
    )
