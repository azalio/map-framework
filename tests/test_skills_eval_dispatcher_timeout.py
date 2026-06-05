"""Dispatcher hardening for EXECUTING-skill trigger eval.

Trigger-accuracy eval only needs the first ``Skill`` tool_use — not the skill
*body* running. Two mechanisms keep executing skills (``map-check`` running the
test suite, ``map-task``/``map-efficient`` dispatching sub-agents) from being
mis-measured:

1. ``--disallowed-tools`` on the ``claude -p`` argv — the body cannot perform
   slow / mutating / network work, so it returns instead of overrunning, while
   the skill still TRIGGERS (description-driven, recorded in the transcript).
2. Timeout recovery — if a slow body still overruns the per-call timeout, the
   trigger is recovered from the transcript (located by cwd slug) rather than
   mis-recorded as a false non-trigger.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mapify_cli.skills_eval import dispatcher as disp_mod
from mapify_cli.skills_eval.dispatcher import (
    _EVAL_DISALLOWED_TOOLS,
    ClaudeSubprocessDispatcher,
    _cwd_to_project_slug,
    _locate_transcript_by_cwd,
)

_SKILL_LINE = (
    '{"message": {"content": [{"type": "tool_use", "name": "Skill", '
    '"input": {"skill": "map-check"}}]}}\n'
)
_NO_SKILL_LINE = (
    '{"message": {"content": [{"type": "text", "text": "just a plain answer"}]}}\n'
)


def _noop_sleep(_seconds: float) -> None:
    """Stand-in for ``time.sleep`` so the settle-poll adds no real delay in tests."""
    del _seconds


def _seed_transcript(home: Path, cwd: Path, line: str) -> Path:
    """Create a transcript JSONL under the project-slug dir below *home*.

    Uses Claude Code's real slug transform (``_cwd_to_project_slug``) so the
    seeded location matches where Claude would actually write it.
    """
    slug_dir = home / ".claude" / "projects" / _cwd_to_project_slug(cwd)
    slug_dir.mkdir(parents=True, exist_ok=True)
    transcript = slug_dir / "session-abc.jsonl"
    transcript.write_text(line, encoding="utf-8")
    return transcript


# ---------------------------------------------------------------------------
# 1. --disallowed-tools is passed to claude -p
# ---------------------------------------------------------------------------


def test_disallowed_tools_constant_blocks_heavy_tools() -> None:
    """The block-list must cover execution, mutation, sub-agents, and network —
    but never ``Skill`` (the signal we measure) nor read-only tools."""
    for tool in ("Bash", "Edit", "Write", "Task", "Agent", "WebFetch", "WebSearch"):
        assert tool in _EVAL_DISALLOWED_TOOLS
    assert "Skill" not in _EVAL_DISALLOWED_TOOLS
    for read_only in ("Read", "Grep", "Glob"):
        assert read_only not in _EVAL_DISALLOWED_TOOLS


def test_dispatch_argv_includes_disallowed_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_seed(_src: Path) -> Path:
        del _src
        return tmp_path

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        captured["argv"] = argv
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout='{"result": "", "session_id": ""}', stderr=""
        )

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    ClaudeSubprocessDispatcher().dispatch("do a thing")

    argv = captured["argv"]
    assert "--disallowed-tools" in argv
    flag_index = argv.index("--disallowed-tools")
    passed = argv[flag_index + 1 : flag_index + 1 + len(_EVAL_DISALLOWED_TOOLS)]
    assert passed == list(_EVAL_DISALLOWED_TOOLS)
    # No --model flag unless one is pinned (preserve CLI session default).
    assert "--model" not in argv


def test_dispatch_argv_includes_model_when_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pinned model is passed as ``--model <alias>`` so trigger accuracy can be
    measured per tier (model choice dominates prompt phrasing)."""
    captured: dict[str, list[str]] = {}

    def fake_seed(_src: Path) -> Path:
        del _src
        return tmp_path

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        captured["argv"] = argv
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout='{"result": "", "session_id": ""}', stderr=""
        )

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    ClaudeSubprocessDispatcher(model="haiku").dispatch("do a thing")

    argv = captured["argv"]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "haiku"


# ---------------------------------------------------------------------------
# 2. Timeout recovery from the transcript
# ---------------------------------------------------------------------------


def test_locate_transcript_by_cwd_finds_slug_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-xyz"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    transcript = _seed_transcript(home, cwd, _SKILL_LINE)

    assert _locate_transcript_by_cwd(cwd) == transcript


def test_locate_transcript_by_cwd_resolves_symlinked_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude Code derives the slug from the RESOLVED cwd (macOS ``/var`` ->
    ``/private/var``). The locator must find the transcript when handed the
    unresolved (symlinked) cwd, or executing-skill recovery silently fails and
    retries 3x — the exact bug observed live with ``map-efficient``."""
    home = tmp_path / "home"
    real_cwd = tmp_path / "real-mapeval"
    real_cwd.mkdir()
    link_cwd = tmp_path / "link-mapeval"
    link_cwd.symlink_to(real_cwd, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    # Transcript is written under the RESOLVED path's slug (what Claude Code uses).
    _seed_transcript(home, real_cwd, _SKILL_LINE)

    # ...but the dispatcher only knows the unresolved symlink path.
    found = _locate_transcript_by_cwd(link_cwd)
    assert found is not None
    assert found.read_text(encoding="utf-8") == _SKILL_LINE


def test_cwd_to_project_slug_replaces_underscore_and_separators() -> None:
    """Claude Code replaces ``/``, ``.`` AND ``_`` (any non-alnum/non-dash) with
    ``-``. The underscore is the one a naive transform misses — ``mkdtemp`` emits
    names like ``mapeval-s_u5zv32`` and the project dir is ``…-mapeval-s-u5zv32``."""
    assert (
        _cwd_to_project_slug(Path("/private/tmp/x/mapeval-s_u5zv32"))
        == "-private-tmp-x-mapeval-s-u5zv32"
    )
    assert "_" not in _cwd_to_project_slug(Path("/a/b_c.d/e_f"))


def test_locate_transcript_by_cwd_handles_underscore_in_temp_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A temp cwd whose mkdtemp suffix contains ``_`` must still be located —
    the live sweep hit ``no transcript located`` (false non-trigger) on exactly
    these dispatches before the slug transform was fixed."""
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-s_u5zv32"  # underscore, as mkdtemp produces
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    transcript = _seed_transcript(home, cwd, _SKILL_LINE)  # seeded under the '-' slug

    # cwd still carries the underscore; the locator must reconcile it.
    assert "_" in str(cwd)
    assert "_" not in transcript.parent.name
    assert _locate_transcript_by_cwd(cwd) == transcript


def test_locate_transcript_by_cwd_returns_none_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert _locate_transcript_by_cwd(tmp_path / "mapeval-none") is None


def test_timeout_recovers_trigger_from_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An EXECUTING skill that overruns the timeout is recorded by its REAL
    trigger (from the transcript), not as a false non-trigger — and is NOT
    retried (timeout recovery is a valid verdict)."""
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-exec"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _seed_transcript(home, cwd, _SKILL_LINE)

    calls = {"n": 0}

    def fake_seed(_src: Path) -> Path:
        del _src
        return cwd

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd=argv, timeout=90)

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    result = ClaudeSubprocessDispatcher().dispatch("run the full test suite")

    assert result.triggered_skill == "map-check"
    assert result.error is None
    assert calls["n"] == 1  # recovery is a valid verdict — no retry


def test_timeout_with_transcript_but_no_skill_records_non_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transcript exists but no skill fired by kill-time → non-trigger verdict
    (the correct reading for a slow negative case), still no retry/error."""
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-neg"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _seed_transcript(home, cwd, _NO_SKILL_LINE)

    def fake_seed(_src: Path) -> Path:
        del _src
        return cwd

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        raise subprocess.TimeoutExpired(cmd=argv, timeout=90)

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    result = ClaudeSubprocessDispatcher().dispatch("what is 2 + 2?")

    assert result.triggered_skill is None
    assert result.error is None


def test_timeout_is_terminal_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is TERMINAL — never retried. Even with no transcript to recover,
    the dispatcher records a single attempt as a non-trigger (error=None), rather
    than re-running the same expensive call ``1 + max_retries`` times. Retrying a
    90 s overrun turned every executing-skill positive into ~3x the wall-clock."""
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-hang"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))  # no transcript seeded
    monkeypatch.setattr(disp_mod.time, "sleep", _noop_sleep)  # skip settle-poll wait

    calls = {"n": 0}

    def fake_seed(_src: Path) -> Path:
        del _src
        return cwd

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd=argv, timeout=90)

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    result = ClaudeSubprocessDispatcher().dispatch("anything")

    assert result.triggered_skill is None
    assert result.error is None  # terminal non-trigger verdict, not an error
    assert calls["n"] == 1  # NOT retried


def test_timeout_recovery_settle_poll_retries_locate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript may not be visible at the exact instant of the timeout kill;
    the settle-poll retries the lookup so a just-written transcript is still
    recovered (defeats the flush/visibility race seen live)."""
    home = tmp_path / "home"
    cwd = tmp_path / "mapeval-race"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(disp_mod.time, "sleep", _noop_sleep)

    locate_calls = {"n": 0}
    real_locate = disp_mod._locate_transcript_by_cwd

    def flaky_locate(target: Path) -> Path | None:
        locate_calls["n"] += 1
        if locate_calls["n"] < 3:  # invisible on the first two polls
            return None
        return real_locate(target)

    _seed_transcript(home, cwd, _SKILL_LINE)

    def fake_seed(_src: Path) -> Path:
        del _src
        return cwd

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        del _kwargs
        raise subprocess.TimeoutExpired(cmd=argv, timeout=90)

    monkeypatch.setattr(disp_mod, "_seed_temp_cwd", fake_seed)
    monkeypatch.setattr(disp_mod, "_locate_transcript_by_cwd", flaky_locate)
    monkeypatch.setattr(disp_mod.subprocess, "run", fake_run)

    result = ClaudeSubprocessDispatcher().dispatch("run the suite")

    assert result.triggered_skill == "map-check"
    assert result.error is None
    assert locate_calls["n"] >= 3  # polled past the transient misses
