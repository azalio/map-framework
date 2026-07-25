"""Tests for src/mapify_cli/memory/finalize.py.

Covers all validation criteria from the ST-003 contract:
  VC1 success path (atomic write, .finalized, scratch deleted, cost log)
  VC2 no SessionEnd dependency
  VC3 idempotency + concurrent double-checked-lock
  VC4 subprocess.run argv-list, env MAP_INVOKED_BY, timeout kwarg
  VC5 truncated trailing JSONL line
  VC6 empty scratch (no turn records)
  + timeout failure path
  + returncode != 0 failure path
  + redaction of secrets in model output
  + incoming_sid exclusion
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mapify_cli.memory.finalize import finalize_dirty

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BRANCH = "arroyo-switchback"
_SID = "session-abc123"
_INCOMING_SID = "session-incoming999"


def _make_git(project_dir: Path, branch: str = _BRANCH) -> None:
    """Create a minimal .git/HEAD so _resolve_branch returns *branch*."""
    git_dir = project_dir / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")


def _scratch_dir(project_dir: Path, branch: str = _BRANCH) -> Path:
    return project_dir / ".map" / branch / "sessions" / "scratch"


def _sessions_dir(project_dir: Path, branch: str = _BRANCH) -> Path:
    return project_dir / ".map" / branch / "sessions"


def _write_scratch(
    scratch_dir: Path,
    sid: str,
    turns: int = 2,
    extra_lines: list[str] | None = None,
) -> Path:
    """Write a minimal scratch JSONL with *turns* EVENT_TURN records."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    jsonl = scratch_dir / f"{sid}.jsonl"
    lines: list[str] = []
    for i in range(turns):
        rec = {
            "ts": "2026-06-02T10:00:00+00:00",
            "turn": i + 1,
            "session_id": sid,
            "files_touched": [f"src/foo_{i}.py"],
            "prompt_ref": "ST-003",
            "event": "turn",
        }
        lines.append(json.dumps(rec))
    if extra_lines:
        lines.extend(extra_lines)
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl


def _fake_completed_process(
    result_text: str = "Session summary body",
    input_tokens: int = 100,
    output_tokens: int = 50,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Return a fake CompletedProcess mimicking claude -p --output-format json."""
    payload = {
        "result": json.dumps({
            "title": "Test session summary title",
            "body": result_text,
            "decisions": ["used flock"],
            "findings": ["atomic write works"],
        }),
        "usage": {
            "input_tokens": input_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "output_tokens": output_tokens,
        },
    }
    return subprocess.CompletedProcess(
        args=["claude", "-p", "--output-format", "json"],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr="",
    )


# ---------------------------------------------------------------------------
# VC1 — success path
# ---------------------------------------------------------------------------


def test_vc1_success_digest_written(tmp_path: Path) -> None:
    """VC1: digest .md written, .finalized created, scratch deleted, cost log has 1 line."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        count = finalize_dirty(None, tmp_path)

    assert count == 1

    # .finalized marker must exist.
    assert (scratch_dir / f"{_SID}.finalized").exists()

    # scratch.jsonl must be deleted.
    assert not (scratch_dir / f"{_SID}.jsonl").exists()

    # No orphan .md.tmp.
    assert not (scratch_dir / f"{_SID}.md.tmp").exists()

    # Digest .md must exist in sessions/ (not scratch/).
    sessions = _sessions_dir(tmp_path)
    md_files = list(sessions.glob("*.md"))
    assert len(md_files) == 1, f"expected 1 digest .md, got {md_files}"
    assert md_files[0].parent == sessions

    # Cost log has exactly 1 JSONL line.
    cost_log = sessions / "memory-cost.log"
    assert cost_log.exists()
    lines = [ln for ln in cost_log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["session_id"] == _SID
    assert "input_tokens" in record
    assert "output_tokens" in record
    assert "duration_s" in record


def test_vc1_digest_content_has_frontmatter(tmp_path: Path) -> None:
    """VC1: written digest contains YAML frontmatter with known fields."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        finalize_dirty(None, tmp_path)

    sessions = _sessions_dir(tmp_path)
    md_files = list(sessions.glob("*.md"))
    content = md_files[0].read_text()
    assert content.startswith("---")
    assert "session_id" in content
    assert "branch" in content
    assert "slug" in content
    assert "files_touched" in content


# ---------------------------------------------------------------------------
# VC2 — no SessionEnd dependency
# ---------------------------------------------------------------------------


def test_vc2_no_session_end_still_finalizes(tmp_path: Path) -> None:
    """VC2: scratch with only turn records (no 'ended' marker) is finalized."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    # Write only turn records — no ended marker anywhere.
    _write_scratch(scratch_dir, _SID, turns=1)
    assert not (scratch_dir / f"{_SID}.finalized").exists()

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        count = finalize_dirty(None, tmp_path)

    assert count == 1
    assert (scratch_dir / f"{_SID}.finalized").exists()


# ---------------------------------------------------------------------------
# VC3 — idempotency
# ---------------------------------------------------------------------------


def test_vc3_idempotent_pre_created_finalized(tmp_path: Path) -> None:
    """VC3: if .finalized already exists, candidate is skipped entirely."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)
    (scratch_dir / f"{_SID}.finalized").touch()  # pre-create marker

    mock_run = MagicMock()
    with patch("mapify_cli.memory.finalize.subprocess.run", mock_run):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    mock_run.assert_not_called()

    # No digest should have been written.
    sessions = _sessions_dir(tmp_path)
    assert list(sessions.glob("*.md")) == []


def test_vc3_idempotent_double_call_writes_one_digest(tmp_path: Path) -> None:
    """VC3: calling finalize_dirty twice writes exactly one digest."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    call_count: list[int] = [0]
    real_proc = _fake_completed_process()

    def counting_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        call_count[0] += 1
        return real_proc

    with patch("mapify_cli.memory.finalize.subprocess.run", side_effect=counting_run):
        count1 = finalize_dirty(None, tmp_path)
        count2 = finalize_dirty(None, tmp_path)

    assert count1 == 1
    assert count2 == 0  # second call: .finalized exists → skipped
    assert call_count[0] == 1  # subprocess.run called exactly once

    sessions = _sessions_dir(tmp_path)
    assert len(list(sessions.glob("*.md"))) == 1


def test_vc3_concurrent_finalized_inside_lock(tmp_path: Path) -> None:
    """VC3: if .finalized appears between scan and the in-lock re-check, no digest written.

    Simulate by having flock_with_state create the marker on enter, which
    models a concurrent process that finalized the session just before we
    acquired the lock.
    """
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    import contextlib

    from mapify_cli._locking import LockState, StateWriter

    @contextlib.contextmanager  # type: ignore[misc]
    def fake_flock(name: str, *, timeout_s: float = 10.0, initial_state: LockState = LockState.IN_PROGRESS) -> Any:
        del timeout_s, initial_state  # signature-compat only; unused in this stub
        # Simulate: concurrent process created .finalized just as we entered lock.
        (scratch_dir / f"{_SID}.finalized").touch()
        from pathlib import Path as _Path
        writer = StateWriter(lock_root=_Path.home() / ".map" / "locks", name=name, pid=1)
        yield writer

    mock_run = MagicMock()
    with (
        patch("mapify_cli.memory.finalize.flock_with_state", fake_flock),
        patch("mapify_cli.memory.finalize.subprocess.run", mock_run),
    ):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    mock_run.assert_not_called()

    # No digest .md written.
    sessions = _sessions_dir(tmp_path)
    assert list(sessions.glob("*.md")) == []


# ---------------------------------------------------------------------------
# VC4 — subprocess argv, env, timeout
# ---------------------------------------------------------------------------


def test_vc4_subprocess_argv_env_timeout(tmp_path: Path) -> None:
    """VC4: subprocess.run called with correct argv list, env, and timeout kwarg."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    captured: list[dict[str, Any]] = []

    def capturing_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append({"args": args, "kwargs": kwargs})
        return _fake_completed_process()

    with patch("mapify_cli.memory.finalize.subprocess.run", side_effect=capturing_run):
        finalize_dirty(None, tmp_path, timeout=42)

    assert len(captured) == 1
    call_args = captured[0]["args"]
    call_kwargs = captured[0]["kwargs"]

    # argv must be a list — NOT a string, NOT shell=True.
    assert isinstance(call_args[0], list), "argv must be a list"
    assert call_args[0] == ["claude", "-p", "--output-format", "json"]
    assert call_kwargs.get("shell") is not True
    assert "shell" not in call_kwargs or call_kwargs["shell"] is False

    # env must carry MAP_INVOKED_BY=memory-finalize exactly.
    env = call_kwargs.get("env", {})
    assert env.get("MAP_INVOKED_BY") == "memory-finalize"

    # timeout kwarg must be present and == 42.
    assert "timeout" in call_kwargs
    assert call_kwargs["timeout"] == 42


# ---------------------------------------------------------------------------
# Timeout failure path
# ---------------------------------------------------------------------------


def test_timeout_leaves_scratch_unfinalized(tmp_path: Path) -> None:
    """On TimeoutExpired: no .finalized, scratch.jsonl still present, no digest, returns 0."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    jsonl = _write_scratch(scratch_dir, _SID)

    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        side_effect=subprocess.TimeoutExpired("claude", 60),
    ):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    # scratch.jsonl must still be present.
    assert jsonl.exists()
    # No .finalized marker.
    assert not (scratch_dir / f"{_SID}.finalized").exists()
    # No digest .md.
    sessions = _sessions_dir(tmp_path)
    assert list(sessions.glob("*.md")) == []
    # No orphan .md.tmp.
    assert not (scratch_dir / f"{_SID}.md.tmp").exists()


# ---------------------------------------------------------------------------
# returncode != 0 failure path
# ---------------------------------------------------------------------------


def test_returncode_nonzero_leaves_scratch_unfinalized(tmp_path: Path) -> None:
    """On returncode != 0: no .finalized, scratch kept, no digest."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    jsonl = _write_scratch(scratch_dir, _SID)

    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        return_value=_fake_completed_process(returncode=1),
    ):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    assert jsonl.exists()
    assert not (scratch_dir / f"{_SID}.finalized").exists()
    sessions = _sessions_dir(tmp_path)
    assert list(sessions.glob("*.md")) == []


def test_marker_touch_failure_after_replace_leaves_unfinalized_then_retry_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-4 critical path: os.replace succeeds but .finalized touch fails.

    The digest .md is written (orphan), but NO .finalized marker is created and
    the scratch WAL is kept — so the next SessionStart retries. The retry must
    converge to a complete, idempotent finalization (exactly one digest, marker
    present, scratch deleted). This is the riskiest failure mode of the
    transactional unit: a marker must never exist without a digest, and an
    orphan digest must be safely re-finalizable.
    """
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    jsonl = _write_scratch(scratch_dir, _SID)
    sessions = _sessions_dir(tmp_path)

    # First pass: force Path.touch to raise (the only .touch() on the post-replace
    # path is the .finalized marker), with subprocess.run mocked to succeed.
    real_touch = Path.touch

    def boom_touch(self: Path, *a: Any, **k: Any) -> None:
        del self, a, k
        raise OSError("simulated marker write failure")

    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        return_value=_fake_completed_process(),
    ):
        monkeypatch.setattr(Path, "touch", boom_touch)
        count1 = finalize_dirty(None, tmp_path)
        monkeypatch.setattr(Path, "touch", real_touch)

    # Unfinalized: orphan digest exists, but no marker and scratch kept.
    assert count1 == 0
    assert not (scratch_dir / f"{_SID}.finalized").exists()
    assert jsonl.exists()
    assert len(list(sessions.glob("*.md"))) == 1  # orphan digest from the os.replace
    assert list(scratch_dir.glob("*.md.tmp")) == []  # no orphan temp

    # Retry: marker write now works -> converges to a complete finalization.
    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        return_value=_fake_completed_process(),
    ):
        count2 = finalize_dirty(None, tmp_path)

    assert count2 == 1
    assert (scratch_dir / f"{_SID}.finalized").exists()
    assert not jsonl.exists()  # scratch deleted on successful finalize
    assert len(list(sessions.glob("*.md"))) == 1  # still exactly one digest (idempotent)


# ---------------------------------------------------------------------------
# VC5 — truncated trailing JSONL line
# ---------------------------------------------------------------------------


def test_vc5_truncated_trailing_line_is_ignored(tmp_path: Path) -> None:
    """VC5: scratch with a valid turn + truncated trailing line finalizes without crash."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)

    valid_turn = json.dumps({
        "ts": "2026-06-02T10:00:00+00:00",
        "turn": 1,
        "session_id": _SID,
        "files_touched": ["src/foo.py"],
        "prompt_ref": "ST-003",
        "event": "turn",
    })
    # Truncated: missing closing brace.
    truncated_line = '{"event": "turn"'

    scratch_dir.mkdir(parents=True, exist_ok=True)
    (scratch_dir / f"{_SID}.jsonl").write_text(
        valid_turn + "\n" + truncated_line + "\n", encoding="utf-8"
    )

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        count = finalize_dirty(None, tmp_path)

    # Should succeed using only the valid turn.
    assert count == 1
    sessions = _sessions_dir(tmp_path)
    assert len(list(sessions.glob("*.md"))) == 1
    assert (scratch_dir / f"{_SID}.finalized").exists()


# ---------------------------------------------------------------------------
# VC6 — empty scratch
# ---------------------------------------------------------------------------


def test_vc6_empty_scratch_no_digest_but_finalized(tmp_path: Path) -> None:
    """VC6: scratch with zero turn records → no digest, .finalized created, scratch deleted."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # Write only an 'ended' marker — no turn records.
    ended_record = json.dumps({
        "event": "ended",
        "ts": "2026-06-02T10:00:00+00:00",
        "session_id": _SID,
    })
    jsonl = scratch_dir / f"{_SID}.jsonl"
    jsonl.write_text(ended_record + "\n", encoding="utf-8")

    mock_run = MagicMock()
    with patch("mapify_cli.memory.finalize.subprocess.run", mock_run):
        count = finalize_dirty(None, tmp_path)

    assert count == 0  # empty → no digest counted
    # subprocess.run must NOT have been called.
    mock_run.assert_not_called()
    # .finalized created.
    assert (scratch_dir / f"{_SID}.finalized").exists()
    # scratch.jsonl deleted.
    assert not jsonl.exists()
    # No digest .md.
    sessions = _sessions_dir(tmp_path)
    assert list(sessions.glob("*.md")) == []


def test_vc6_truly_empty_file_no_digest(tmp_path: Path) -> None:
    """VC6: completely empty scratch file → no digest, .finalized created, scratch deleted."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    jsonl = scratch_dir / f"{_SID}.jsonl"
    jsonl.write_text("", encoding="utf-8")

    mock_run = MagicMock()
    with patch("mapify_cli.memory.finalize.subprocess.run", mock_run):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    mock_run.assert_not_called()
    assert (scratch_dir / f"{_SID}.finalized").exists()
    assert not jsonl.exists()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redaction_of_secrets_in_model_output(tmp_path: Path) -> None:
    """Secret in model body is redacted in the written digest file."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    secret = "sk-" + "A" * 20  # matches openai redaction pattern
    body_with_secret = f"Session summary. Token: {secret}. End."

    proc = _fake_completed_process(result_text=body_with_secret)
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=proc):
        finalize_dirty(None, tmp_path)

    sessions = _sessions_dir(tmp_path)
    md_files = list(sessions.glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert secret not in content, "raw secret key must not appear in digest"
    assert "«redacted»" in content, "redaction token must appear in digest"


# ---------------------------------------------------------------------------
# incoming_sid exclusion
# ---------------------------------------------------------------------------


def test_incoming_sid_not_finalized(tmp_path: Path) -> None:
    """A scratch named <incoming_sid>.jsonl is NOT finalized."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    jsonl = _write_scratch(scratch_dir, _INCOMING_SID)

    mock_run = MagicMock()
    with patch("mapify_cli.memory.finalize.subprocess.run", mock_run):
        count = finalize_dirty(_INCOMING_SID, tmp_path)

    assert count == 0
    mock_run.assert_not_called()
    # incoming scratch must remain intact.
    assert jsonl.exists()
    assert not (scratch_dir / f"{_INCOMING_SID}.finalized").exists()


def test_incoming_sid_excluded_but_other_finalized(tmp_path: Path) -> None:
    """incoming_sid is excluded; a different prior sid IS finalized."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)
    incoming_jsonl = _write_scratch(scratch_dir, _INCOMING_SID)

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        count = finalize_dirty(_INCOMING_SID, tmp_path)

    assert count == 1
    assert (scratch_dir / f"{_SID}.finalized").exists()
    # incoming remains untouched.
    assert incoming_jsonl.exists()
    assert not (scratch_dir / f"{_INCOMING_SID}.finalized").exists()


# ---------------------------------------------------------------------------
# No scratch directory
# ---------------------------------------------------------------------------


def test_no_scratch_dir_returns_zero(tmp_path: Path) -> None:
    """finalize_dirty returns 0 when scratch/ does not exist."""
    _make_git(tmp_path)
    count = finalize_dirty(None, tmp_path)
    assert count == 0


# ---------------------------------------------------------------------------
# Cost log shape
# ---------------------------------------------------------------------------


def test_cost_log_record_shape(tmp_path: Path) -> None:
    """Cost log JSONL record has all required fields with correct types."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    _write_scratch(scratch_dir, _SID)

    proc = _fake_completed_process(input_tokens=200, output_tokens=75)
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=proc):
        finalize_dirty(None, tmp_path)

    cost_log = _sessions_dir(tmp_path) / "memory-cost.log"
    lines = [ln for ln in cost_log.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])

    assert rec["session_id"] == _SID
    assert isinstance(rec["input_tokens"], int)
    assert isinstance(rec["cache_read_input_tokens"], int)
    assert isinstance(rec["cache_creation_input_tokens"], int)
    assert isinstance(rec["output_tokens"], int)
    assert isinstance(rec["duration_s"], float)
    assert isinstance(rec["ts"], str)


# ---------------------------------------------------------------------------
# Multiple candidates
# ---------------------------------------------------------------------------


def test_multiple_candidates_all_finalized(tmp_path: Path) -> None:
    """All dirty prior scratches are finalized in a single call."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    sids = ["sid-alpha", "sid-beta", "sid-gamma"]
    for sid in sids:
        _write_scratch(scratch_dir, sid)

    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_fake_completed_process()):
        count = finalize_dirty(None, tmp_path)

    assert count == 3
    for sid in sids:
        assert (scratch_dir / f"{sid}.finalized").exists()
        assert not (scratch_dir / f"{sid}.jsonl").exists()

    sessions = _sessions_dir(tmp_path)
    md_files = list(sessions.glob("*.md"))
    assert len(md_files) == 3


# ---------------------------------------------------------------------------
# Lock timeout: skip candidate, no crash
# ---------------------------------------------------------------------------


def test_lock_timeout_skips_candidate_no_crash(tmp_path: Path) -> None:
    """LockTimeoutError causes candidate to be skipped; function returns 0, no exception."""
    _make_git(tmp_path)
    scratch_dir = _scratch_dir(tmp_path)
    jsonl = _write_scratch(scratch_dir, _SID)

    from mapify_cli._locking import LockTimeoutError as _LTE

    def raising_flock(*args: Any, **kwargs: Any) -> Any:
        # `with flock_with_state(...)` evaluates this call first; raising here
        # models lock-acquisition timeout before the context is ever entered.
        del args, kwargs
        raise _LTE("simulated timeout")

    mock_run = MagicMock()
    with (
        patch("mapify_cli.memory.finalize.flock_with_state", raising_flock),
        patch("mapify_cli.memory.finalize.subprocess.run", mock_run),
    ):
        count = finalize_dirty(None, tmp_path)

    assert count == 0
    mock_run.assert_not_called()
    # scratch must remain for retry.
    assert jsonl.exists()
    assert not (scratch_dir / f"{_SID}.finalized").exists()
