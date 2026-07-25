"""Tests for src/mapify_cli/memory/capture.py — ST-002.

All assertions are on observable side effects (files on disk), not return values.
Tests are subprocess-free: fake git repos are created by writing .git/HEAD directly.

Coverage map:
  VC1  [AC-1][INV-1]  append_turn writes well-formed JSONL; turn counter increments;
                       ZERO subprocess calls (monkeypatched to raise).
  VC2  [HC-1]         session resolution: stdin sid wins; pointer fallback works;
                       no SessionEnd/PreCompact key ever consulted.
  VC3  [security]     .env / *.pem paths become "<redacted-secret-path>";
                       normal paths are preserved; control chars are stripped.
  VC4  [AC-1]         append_turn creates/updates current-session pointer;
                       append_end_marker writes {event:"ended",...} and updates pointer.
  ROB  [robustness]   append_turn with malformed/empty stdin does not raise.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.memory.capture import (
    append_end_marker,
    append_turn,
    on_session_end,
    resolve_session_id,
    write_current_session,
)
from mapify_cli.memory.digest_schema import (
    EVENT_ENDED,
    EVENT_TURN,
    SCRATCH_ENDED_FIELDS,
    SCRATCH_TURN_FIELDS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_git(project_dir: Path, branch: str = "test-branch") -> None:
    """Create a minimal .git directory so _resolve_branch works without subprocess.

    Writes .git/HEAD with ref: refs/heads/<branch>.
    """
    git_dir = project_dir / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")


def _scratch_dir(project_dir: Path, branch: str = "test-branch") -> Path:
    return project_dir / ".map" / branch / "sessions" / "scratch"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all non-blank JSONL lines from *path*."""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            lines.append(json.loads(raw))
    return lines


# ---------------------------------------------------------------------------
# VC1 [AC-1][INV-1] — well-formed JSONL, turn counter, zero subprocess
# ---------------------------------------------------------------------------


class TestVC1WellFormedJSONL:
    def test_vc1_single_turn_writes_one_line(self, tmp_path: Path) -> None:
        """append_turn writes exactly ONE JSONL line per call."""
        _make_fake_git(tmp_path)
        append_turn({"session_id": "s1"}, tmp_path)

        scratch = _scratch_dir(tmp_path)
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1, "Expected exactly one JSONL file"
        lines = _read_jsonl(jsonl_files[0])
        assert len(lines) == 1

    def test_vc1_all_scratch_turn_fields_present(self, tmp_path: Path) -> None:
        """The written record contains all fields listed in SCRATCH_TURN_FIELDS."""
        _make_fake_git(tmp_path)
        append_turn({"session_id": "s1"}, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        for field in SCRATCH_TURN_FIELDS:
            assert field in record, f"Missing field: {field}"

    def test_vc1_event_field_is_turn(self, tmp_path: Path) -> None:
        """event field must equal EVENT_TURN ('turn')."""
        _make_fake_git(tmp_path)
        append_turn({"session_id": "s1"}, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        assert record["event"] == EVENT_TURN

    def test_vc1_turn_counter_increments(self, tmp_path: Path) -> None:
        """Second call must produce turn==2 (line count based, resilient to restart)."""
        _make_fake_git(tmp_path)
        stdin = {"session_id": "s1"}
        append_turn(stdin, tmp_path)
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        records = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))
        assert len(records) == 2
        assert records[0]["turn"] == 1
        assert records[1]["turn"] == 2

    def test_vc1_inv1_zero_subprocess_append_turn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INV-1: append_turn must NOT call subprocess.run or subprocess.Popen."""
        _make_fake_git(tmp_path)

        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            del _args, _kwargs
            raise AssertionError("subprocess must not be called on the hot path")

        monkeypatch.setattr(subprocess, "run", _raise)
        monkeypatch.setattr(subprocess, "Popen", _raise)

        # Must complete without raising (best-effort wraps exceptions, but
        # subprocess.AssertionError would bubble before the except catches it
        # only if the module calls subprocess — so if this passes, no subprocess was used).
        append_turn({"session_id": "s1"}, tmp_path)

        # Also verify a record was actually written (not silently no-op'd).
        scratch = _scratch_dir(tmp_path)
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        assert len(_read_jsonl(jsonl_files[0])) == 1

    def test_vc1_inv1_zero_subprocess_append_end_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INV-1: append_end_marker must NOT call subprocess.run or subprocess.Popen."""
        _make_fake_git(tmp_path)

        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            del _args, _kwargs
            raise AssertionError("subprocess must not be called on the hot path")

        monkeypatch.setattr(subprocess, "run", _raise)
        monkeypatch.setattr(subprocess, "Popen", _raise)

        append_end_marker({"session_id": "s1"}, tmp_path)

        scratch = _scratch_dir(tmp_path)
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        records = _read_jsonl(jsonl_files[0])
        assert len(records) == 1
        assert records[0]["event"] == EVENT_ENDED


# ---------------------------------------------------------------------------
# VC2 [HC-1] — session resolution without SessionEnd/PreCompact
# ---------------------------------------------------------------------------


class TestVC2SessionResolution:
    def test_vc2_stdin_session_id_used(self, tmp_path: Path) -> None:
        """When stdin contains session_id, it is used as the active session."""
        _make_fake_git(tmp_path)
        sid = resolve_session_id({"session_id": "from-stdin"}, tmp_path)
        assert sid == "from-stdin"

    def test_vc2_pointer_fallback(self, tmp_path: Path) -> None:
        """When stdin has no session_id, the current-session pointer is consulted."""
        _make_fake_git(tmp_path)
        # Write a pointer file directly.
        scratch = _scratch_dir(tmp_path)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "current-session").write_text("from-pointer", encoding="utf-8")

        sid = resolve_session_id({}, tmp_path)
        assert sid == "from-pointer"

    def test_vc2_none_when_no_source(self, tmp_path: Path) -> None:
        """Returns None when neither stdin nor pointer file provides a session."""
        _make_fake_git(tmp_path)
        sid = resolve_session_id({}, tmp_path)
        assert sid is None

    def test_vc2_stdin_wins_over_pointer(self, tmp_path: Path) -> None:
        """stdin session_id takes priority over the pointer file."""
        _make_fake_git(tmp_path)
        scratch = _scratch_dir(tmp_path)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "current-session").write_text("from-pointer", encoding="utf-8")

        sid = resolve_session_id({"session_id": "from-stdin"}, tmp_path)
        assert sid == "from-stdin"

    def test_vc2_no_sessionend_precompact_key_consulted(self, tmp_path: Path) -> None:
        """HC-1: session resolution must NOT read SessionEnd or PreCompact keys.

        This is structural: we pass only those keys and verify the function does
        NOT incorrectly use them as a session_id source — only 'session_id' is valid.
        """
        _make_fake_git(tmp_path)
        stdin_with_wrong_keys = {
            "SessionEnd": "should-not-be-used",
            "PreCompact": "should-not-be-used",
            "hook_event_name": "Stop",
        }
        sid = resolve_session_id(stdin_with_wrong_keys, tmp_path)
        # No valid source -> None (not "should-not-be-used")
        assert sid is None

    def test_vc2_append_turn_uses_pointer_when_stdin_empty(
        self, tmp_path: Path
    ) -> None:
        """append_turn uses the pointer-based sid when stdin has no session_id."""
        _make_fake_git(tmp_path)
        # Prime the pointer
        scratch = _scratch_dir(tmp_path)
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "current-session").write_text("pointer-sid", encoding="utf-8")

        append_turn({}, tmp_path)

        # The JSONL file should be named after the pointer sid.
        jsonl = scratch / "pointer-sid.jsonl"
        assert jsonl.exists()
        record = _read_jsonl(jsonl)[0]
        assert record["session_id"] == "pointer-sid"


# ---------------------------------------------------------------------------
# VC3 [security] — redaction + sanitization
# ---------------------------------------------------------------------------


class TestVC3SecurityRedaction:
    def test_vc3_env_file_is_redacted(self, tmp_path: Path) -> None:
        """A .env file_path in tool_input is stored as '<redacted-secret-path>'."""
        _make_fake_git(tmp_path)
        stdin: dict[str, Any] = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": ".env"},
        }
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        assert record["files_touched"] == ["<redacted-secret-path>"]

    def test_vc3_pem_file_is_redacted(self, tmp_path: Path) -> None:
        """A *.pem path is stored as '<redacted-secret-path>'."""
        _make_fake_git(tmp_path)
        stdin: dict[str, Any] = {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": "deploy/server.pem"},
        }
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        assert record["files_touched"] == ["<redacted-secret-path>"]

    def test_vc3_normal_path_not_redacted(self, tmp_path: Path) -> None:
        """A normal source path is stored unchanged."""
        _make_fake_git(tmp_path)
        stdin: dict[str, Any] = {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/app.py"},
        }
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        assert record["files_touched"] == ["src/app.py"]

    def test_vc3_control_char_in_value_is_stripped(self, tmp_path: Path) -> None:
        """Control characters in a session_id value are stripped before writing."""
        _make_fake_git(tmp_path)
        # Embed a tab and a newline inside the session id.
        dirty_sid = "sess\x00with\x01control\x1fchars"
        stdin: dict[str, Any] = {"session_id": dirty_sid, "tool_name": "Bash"}
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        # The file will be named after the sanitized sid.
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1
        # Verify no raw control chars survived in the serialised JSON line.
        raw_line = jsonl_files[0].read_text(encoding="utf-8").strip()
        for ch in ["\x00", "\x01", "\x1f"]:
            assert ch not in raw_line, f"Control char {ch!r} found in written line"

    def test_vc3_env_local_variant_is_redacted(self, tmp_path: Path) -> None:
        """config/.env.local is also redacted (full-path glob match)."""
        _make_fake_git(tmp_path)
        stdin: dict[str, Any] = {
            "session_id": "s1",
            "tool_name": "Write",
            "tool_input": {"file_path": "config/.env.local"},
        }
        append_turn(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        record = _read_jsonl(next(iter(scratch.glob("*.jsonl"))))[0]
        assert record["files_touched"] == ["<redacted-secret-path>"]


# ---------------------------------------------------------------------------
# VC4 [AC-1] — current-session pointer + end marker
# ---------------------------------------------------------------------------


class TestVC4PointerAndEndMarker:
    def test_vc4_append_turn_creates_pointer(self, tmp_path: Path) -> None:
        """After append_turn, current-session pointer exists and matches the sid."""
        _make_fake_git(tmp_path)
        append_turn({"session_id": "myses"}, tmp_path)

        pointer = _scratch_dir(tmp_path) / "current-session"
        assert pointer.exists()
        assert pointer.read_text(encoding="utf-8").strip() == "myses"

    def test_vc4_append_turn_updates_pointer(self, tmp_path: Path) -> None:
        """Pointer is updated on every append_turn call (idempotent write)."""
        _make_fake_git(tmp_path)
        append_turn({"session_id": "first"}, tmp_path)
        append_turn({"session_id": "second"}, tmp_path)

        pointer = _scratch_dir(tmp_path) / "current-session"
        # Latest call wins.
        assert pointer.read_text(encoding="utf-8").strip() == "second"

    def test_vc4_append_end_marker_writes_ended_record(self, tmp_path: Path) -> None:
        """append_end_marker writes exactly the SCRATCH_ENDED_FIELDS record."""
        _make_fake_git(tmp_path)
        append_end_marker({"session_id": "endsess"}, tmp_path)

        scratch = _scratch_dir(tmp_path)
        jsonl = scratch / "endsess.jsonl"
        assert jsonl.exists()
        records = _read_jsonl(jsonl)
        assert len(records) == 1
        record = records[0]
        for field in SCRATCH_ENDED_FIELDS:
            assert field in record, f"Missing field in end marker: {field}"
        assert record["event"] == EVENT_ENDED
        assert record["session_id"] == "endsess"

    def test_vc4_append_end_marker_updates_pointer(self, tmp_path: Path) -> None:
        """append_end_marker also writes/updates the current-session pointer (VC4)."""
        _make_fake_git(tmp_path)
        append_end_marker({"session_id": "finalsess"}, tmp_path)

        pointer = _scratch_dir(tmp_path) / "current-session"
        assert pointer.exists()
        assert pointer.read_text(encoding="utf-8").strip() == "finalsess"

    def test_vc4_end_marker_appends_after_turns(self, tmp_path: Path) -> None:
        """append_end_marker appends to existing scratch file (does not clobber)."""
        _make_fake_git(tmp_path)
        stdin = {"session_id": "combo"}
        append_turn(stdin, tmp_path)
        append_turn(stdin, tmp_path)
        append_end_marker(stdin, tmp_path)

        scratch = _scratch_dir(tmp_path)
        records = _read_jsonl(scratch / "combo.jsonl")
        assert len(records) == 3
        assert records[0]["event"] == EVENT_TURN
        assert records[1]["event"] == EVENT_TURN
        assert records[2]["event"] == EVENT_ENDED


# ---------------------------------------------------------------------------
# Robustness — empty/malformed stdin must not raise
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_rob_empty_stdin_does_not_raise(self, tmp_path: Path) -> None:
        """append_turn with an empty dict must not raise (best-effort no-op or write)."""
        _make_fake_git(tmp_path)
        # Should not raise; may write a record with sid "unknown".
        append_turn({}, tmp_path)

    def test_rob_malformed_stdin_does_not_raise(self, tmp_path: Path) -> None:
        """append_turn with unexpected non-dict values in keys must not raise."""
        _make_fake_git(tmp_path)
        bad_stdin: dict[str, Any] = {
            "session_id": None,
            "tool_name": 42,
            "tool_input": "not-a-dict",
        }
        append_turn(bad_stdin, tmp_path)

    def test_rob_end_marker_empty_stdin_does_not_raise(self, tmp_path: Path) -> None:
        """append_end_marker with an empty dict must not raise."""
        _make_fake_git(tmp_path)
        append_end_marker({}, tmp_path)

    def test_rob_missing_git_falls_back_to_default_branch(
        self, tmp_path: Path
    ) -> None:
        """Without a .git directory, branch resolution falls back to 'default'."""
        # No .git written — _resolve_branch should return "default".
        append_turn({"session_id": "s1"}, tmp_path)

        default_scratch = tmp_path / ".map" / "default" / "sessions" / "scratch"
        # If branch resolved to "default", the file should be there.
        assert default_scratch.exists(), "Expected fallback to 'default' branch dir"

    def test_rob_worktree_git_file_resolves_branch(self, tmp_path: Path) -> None:
        """Branch resolution handles git worktree .git files correctly."""
        # Simulate a worktree: .git is a file pointing to a gitdir.
        gitdir = tmp_path / "gitdir"
        gitdir.mkdir()
        (gitdir / "HEAD").write_text(
            "ref: refs/heads/worktree-branch\n", encoding="utf-8"
        )
        (tmp_path / ".git").write_text(
            f"gitdir: {gitdir}\n", encoding="utf-8"
        )

        append_turn({"session_id": "wt-sess"}, tmp_path)

        scratch = tmp_path / ".map" / "worktree-branch" / "sessions" / "scratch"
        assert scratch.exists()
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1

    def test_rob_detached_head_uses_short_sha(self, tmp_path: Path) -> None:
        """Detached HEAD (.git/HEAD holds a raw SHA, no 'ref:') -> short-sha branch dir."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        # Detached HEAD: HEAD is a bare commit SHA, not a 'ref: refs/heads/...' line.
        (git_dir / "HEAD").write_text(
            "abc123def4567890abc123def4567890abc123de\n", encoding="utf-8"
        )

        append_turn({"session_id": "detached-sess"}, tmp_path)

        # _resolve_branch truncates the SHA to its first 12 chars for the branch segment.
        scratch = tmp_path / ".map" / "abc123def456" / "sessions" / "scratch"
        assert scratch.exists()
        jsonl_files = list(scratch.glob("*.jsonl"))
        assert len(jsonl_files) == 1

    def test_rob_write_current_session_creates_dirs(self, tmp_path: Path) -> None:
        """write_current_session creates parent directories as needed."""
        _make_fake_git(tmp_path)
        # scratch dir does not exist yet.
        write_current_session("test-sid", tmp_path)

        scratch = _scratch_dir(tmp_path)
        pointer = scratch / "current-session"
        assert pointer.exists()
        assert pointer.read_text(encoding="utf-8") == "test-sid"

    def test_rob_branch_slash_becomes_dash(self, tmp_path: Path) -> None:
        """feat/my-feature branch name is sanitized to feat-my-feature in the path."""
        _make_fake_git(tmp_path, branch="feat/my-feature")
        append_turn({"session_id": "s1"}, tmp_path)

        expected_dir = tmp_path / ".map" / "feat-my-feature" / "sessions" / "scratch"
        assert expected_dir.exists()


# ---------------------------------------------------------------------------
# ST-005: SessionEnd best-effort 'ended' marker (on_session_end) — AC-4 / EC-6
# ---------------------------------------------------------------------------


class TestSessionEndMarker:
    def test_vc1_endmark_record_only(self, tmp_path: Path) -> None:
        """AC-4: on_session_end appends ONLY an 'ended' record — no finalize/LLM artifacts."""
        _make_fake_git(tmp_path)
        on_session_end(
            {"session_id": "endsid", "reason": "clear"}, tmp_path
        )

        scratch = _scratch_dir(tmp_path)
        jsonl = scratch / "endsid.jsonl"
        records = _read_jsonl(jsonl)
        assert len(records) == 1
        record = records[0]
        for field in SCRATCH_ENDED_FIELDS:
            assert field in record
        assert record["event"] == EVENT_ENDED
        assert record["session_id"] == "endsid"
        # No finalize side effects: no digest, no .finalized marker.
        sessions = tmp_path / ".map" / "test-branch" / "sessions"
        assert list(sessions.glob("*.md")) == []
        assert list(scratch.glob("*.finalized")) == []

    def test_vc2_endmark_swallows_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4: on_session_end never raises — an injected failure is swallowed."""
        _make_fake_git(tmp_path)

        def _boom(*_a: Any, **_k: Any) -> None:
            del _a, _k
            raise OSError("injected end-marker failure")

        # Patch the end-marker in the capture module's namespace.
        monkeypatch.setattr("mapify_cli.memory.capture.append_end_marker", _boom)

        # Must NOT raise.
        on_session_end({"session_id": "s1", "reason": "logout"}, tmp_path)

    def test_vc3_endmark_reason_agnostic(self, tmp_path: Path) -> None:
        """EC-6: all SessionEnd reasons produce an identical 'ended' record."""
        scratch = _scratch_dir(tmp_path)
        for reason, sid in (("clear", "r-clear"), ("resume", "r-resume"), ("logout", "r-logout")):
            _make_fake_git(tmp_path)
            on_session_end({"session_id": sid, "reason": reason}, tmp_path)
            records = _read_jsonl(scratch / f"{sid}.jsonl")
            assert len(records) == 1
            assert records[0]["event"] == EVENT_ENDED
            assert records[0]["session_id"] == sid
            # The reason value never appears in the record (reason-agnostic).
            assert "reason" not in records[0]
