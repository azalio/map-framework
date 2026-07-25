"""Regression tests for the code-review fixes on the memory subsystem.

Each test pins a specific bug found in review so it cannot silently reappear:

  #1 finalize  — slug disambiguation must not clobber another session's digest
  #3 finalize  — slug derived from `title`; ```json-fenced output still parses
  #4 finalize  — long/identifier session_id is NOT redacted in frontmatter
  #5 recall    — cap is rank-monotonic (no lower-ranked block jumps a dropped one)
  #6 schema    — fine-grained github_pat_ tokens are redacted
  #7 schema    — pure-hex git SHAs are NOT over-redacted (mixed-case still is)
  #8 capture   — transcript offset advances only AFTER the record write
  #9 capture   — unidentified sessions key off the transcript stem, not "unknown"
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mapify_cli.memory.capture import append_turn
from mapify_cli.memory.digest_schema import REDACTION_TOKEN, redact_text
from mapify_cli.memory.finalize import finalize_dirty
from mapify_cli.memory.recall import build_recall

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_git(project_dir: Path, branch: str = "review-branch") -> None:
    git_dir = project_dir / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")


def _scratch_dir(project_dir: Path, branch: str = "review-branch") -> Path:
    return project_dir / ".map" / branch / "sessions" / "scratch"


def _sessions_dir(project_dir: Path, branch: str = "review-branch") -> Path:
    return project_dir / ".map" / branch / "sessions"


def _write_scratch(scratch_dir: Path, sid: str, turns: int = 1) -> Path:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    jsonl = scratch_dir / f"{sid}.jsonl"
    lines = [
        json.dumps(
            {
                "ts": "2026-06-02T10:00:00+00:00",
                "turn": i + 1,
                "session_id": sid,
                "files_touched": ["src/foo.py"],
                "prompt_ref": "ST-XXX",
                "event": "turn",
            }
        )
        for i in range(turns)
    ]
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl


def _proc(
    *,
    title: str = "Test digest title",
    body: str = "body text",
    decisions: list[str] | None = None,
    findings: list[str] | None = None,
    fence: bool = False,
) -> subprocess.CompletedProcess[str]:
    inner = json.dumps(
        {
            "title": title,
            "body": body,
            "decisions": decisions or [],
            "findings": findings or [],
        }
    )
    if fence:
        inner = "```json\n" + inner + "\n```"
    payload = {
        "result": inner,
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "output_tokens": 5,
        },
    }
    return subprocess.CompletedProcess(
        args=["claude", "-p"], returncode=0, stdout=json.dumps(payload), stderr=""
    )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


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


# ---------------------------------------------------------------------------
# #6 / #7 — digest_schema redaction
# ---------------------------------------------------------------------------


def test_fine_grained_github_pat_is_redacted() -> None:
    """#6: github_pat_ fine-grained tokens (underscores in body) are redacted."""
    secret = "github_pat_11ABCDEFG0aZ_" + "abcdABCD1234" * 4
    out = redact_text(secret)
    assert REDACTION_TOKEN in out
    assert "github_pat_11ABCDEFG0aZ" not in out


def test_lowercase_hex_sha_not_over_redacted() -> None:
    """#7: a 40-char lowercase-hex run (a git SHA) is left intact."""
    sha = "a1b2c3d4e5f6" * 3 + "a1b2"  # 40 lowercase hex chars
    assert len(sha) == 40
    assert redact_text(sha) == sha


def test_mixed_case_base64_blob_still_redacted() -> None:
    """#7 guard: a genuine mixed-case 40+ char blob is still redacted."""
    secret = "ABCDEFGHIJKLMNOPQRSTuvwxyzABCDEFGHIJ1234"  # 40 chars, mixed
    assert REDACTION_TOKEN in redact_text(secret)


# ---------------------------------------------------------------------------
# #1 — slug disambiguation must not clobber another session's digest
# ---------------------------------------------------------------------------


def test_same_long_title_two_sessions_no_clobber(tmp_path: Path) -> None:
    """#1: two sessions whose 32-char slug collides must yield TWO digests.

    The buggy `f"{slug}-{sid[:8]}"[:32]` chopped the disambiguating suffix back
    off when the slug was already 32 chars, so os.replace overwrote the first
    session's digest.  Both digests must survive.
    """
    _make_git(tmp_path)
    scratch = _scratch_dir(tmp_path)
    sid_a = "sid-alpha-0000000000000000"
    sid_b = "sid-bravo-1111111111111111"
    _write_scratch(scratch, sid_a)
    _write_scratch(scratch, sid_b)

    # First 4 words slug to exactly 32 chars after truncation.
    title = "implementing comprehensive memory subsystem architecture rewrite"
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_proc(title=title)):
        count = finalize_dirty(None, tmp_path)

    assert count == 2
    mds = list(_sessions_dir(tmp_path).glob("*.md"))
    assert len(mds) == 2, f"clobber: expected 2 digests, got {[p.name for p in mds]}"
    joined = "\n".join(p.read_text(encoding="utf-8") for p in mds)
    assert sid_a in joined and sid_b in joined


# ---------------------------------------------------------------------------
# #3 — slug from title; fenced claude output still parses decisions/findings
# ---------------------------------------------------------------------------


def test_slug_derived_from_title(tmp_path: Path) -> None:
    """#3: the digest filename slug comes from the `title` key, not the body."""
    _make_git(tmp_path)
    scratch = _scratch_dir(tmp_path)
    _write_scratch(scratch, "sid-title")
    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        return_value=_proc(title="fix recall cap", body="## Summary\nlong body"),
    ):
        finalize_dirty(None, tmp_path)
    mds = list(_sessions_dir(tmp_path).glob("*.md"))
    assert len(mds) == 1
    assert mds[0].name == f"{_today()}-fix-recall-cap.md"


def test_fenced_claude_output_parses_decisions_and_findings(tmp_path: Path) -> None:
    """#3: a ```json-fenced model response still yields decisions/findings + slug."""
    _make_git(tmp_path)
    scratch = _scratch_dir(tmp_path)
    _write_scratch(scratch, "sid-fence")
    with patch(
        "mapify_cli.memory.finalize.subprocess.run",
        return_value=_proc(
            title="parse fenced output",
            body="B",
            decisions=["chose-WAL"],
            findings=["fence-handled"],
            fence=True,
        ),
    ):
        finalize_dirty(None, tmp_path)
    md = next(iter(_sessions_dir(tmp_path).glob("*.md")))
    content = md.read_text(encoding="utf-8")
    assert "chose-WAL" in content
    assert "fence-handled" in content
    assert md.name == f"{_today()}-parse-fenced-output.md"
    # The literal fence line must NOT have become the slug.
    assert "json" != md.name.split("-", 3)[-1].removesuffix(".md")


# ---------------------------------------------------------------------------
# #4 — identifier session_id is not redacted in frontmatter
# ---------------------------------------------------------------------------


def test_mixed_case_session_id_not_redacted_in_frontmatter(tmp_path: Path) -> None:
    """#4: session_id is an identifier — it must survive verbatim, not «redacted».

    A 48-char mixed-case sid matches the base64 blob pattern, but redaction is
    applied per-field and identifier fields are excluded, so the owner-line
    dedup check keeps working.
    """
    _make_git(tmp_path)
    scratch = _scratch_dir(tmp_path)
    sid = "Aa1Bb2Cc3Dd4" * 4  # 48 chars, mixed case
    _write_scratch(scratch, sid)
    with patch("mapify_cli.memory.finalize.subprocess.run", return_value=_proc()):
        finalize_dirty(None, tmp_path)
    content = next(iter(_sessions_dir(tmp_path).glob("*.md"))).read_text(encoding="utf-8")
    assert f'session_id: "{sid}"' in content
    assert REDACTION_TOKEN not in content.splitlines()[1]  # the session_id line


# ---------------------------------------------------------------------------
# #5 — recall cap is rank-monotonic
# ---------------------------------------------------------------------------


def _write_digest(sessions_dir: Path, *, date: str, slug: str, sid: str, body: str) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    fm = (
        "---\n"
        f'session_id: "{sid}"\n'
        'branch: "review-branch"\n'
        f'date: "{date}"\n'
        f'slug: "{slug}"\n'
        "files_touched: []\n"
        "decisions: []\n"
        "findings: []\n"
        "ticket_refs: []\n"
        "---\n"
    )
    (sessions_dir / f"{date}-{slug}.md").write_text(fm + "\n" + body + "\n", encoding="utf-8")


def test_recall_cap_is_rank_monotonic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#5: when the top-ranked digest does not fit, a smaller lower-ranked one
    must NOT be injected in its place (dropped set is a clean suffix of rank).
    """
    monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "120")
    branch = "review-branch"
    sessions = tmp_path / ".map" / branch / "sessions"

    # Rank 1 (keyword match → high score) but large; rank 2 small, no match.
    _write_digest(
        sessions,
        date="2026-01-02",
        slug="top",
        sid="sid-top",
        body="recall ranking memory " * 20,  # large, matches prompt
    )
    _write_digest(
        sessions, date="2026-01-01", slug="small", sid="sid-small", body="tiny"
    )

    result = build_recall(prompt="recall ranking memory", branch=branch, project_dir=tmp_path)

    # Top-ranked overflowed → nothing lower-ranked may sneak in.
    assert result == "", f"lower-ranked block jumped a dropped higher-ranked one: {result!r}"
    drop_log = sessions / "recall-drop.log"
    records = [json.loads(ln) for ln in drop_log.read_text().splitlines() if ln.strip()]
    assert len(records) == 2  # both dropped, both logged


# ---------------------------------------------------------------------------
# #8 — transcript offset advances only AFTER the record write
# ---------------------------------------------------------------------------


def test_offset_not_advanced_when_record_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#8: if the scratch record write fails, the <sid>.offset must NOT advance.

    Otherwise a crash between offset-write and record-write permanently skips
    that transcript range, losing its files_touched.
    """
    _make_git(tmp_path)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_edit_line("src/a.py") + "\n", encoding="utf-8")

    import mapify_cli.memory.capture as cap

    def boom(*_a: Any, **_k: Any) -> str:
        del _a, _k
        raise ValueError("simulated record-write failure")

    # Only the record serialization uses json.dumps in append_turn.
    monkeypatch.setattr(cap.json, "dumps", boom)
    append_turn({"session_id": "s1", "transcript_path": str(transcript)}, tmp_path)

    offset = _scratch_dir(tmp_path) / "s1.offset"
    assert not offset.exists(), "offset must not advance when the record write failed"


def test_offset_persisted_after_successful_write(tmp_path: Path) -> None:
    """#8 positive: offset is written (== transcript line count) after success."""
    _make_git(tmp_path)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_edit_line("src/a.py") + "\n", encoding="utf-8")
    append_turn({"session_id": "s1", "transcript_path": str(transcript)}, tmp_path)
    offset = _scratch_dir(tmp_path) / "s1.offset"
    assert offset.exists()
    assert offset.read_text(encoding="utf-8").strip() == "1"


# ---------------------------------------------------------------------------
# #9 — unidentified sessions key off the transcript stem, not "unknown"
# ---------------------------------------------------------------------------


def test_fallback_sid_uses_transcript_stem(tmp_path: Path) -> None:
    """#9: with no session_id/pointer, scratch is named after the transcript stem."""
    _make_git(tmp_path)
    transcript = tmp_path / "session-XYZ.jsonl"
    transcript.write_text(_edit_line("src/a.py") + "\n", encoding="utf-8")
    append_turn({"transcript_path": str(transcript), "hook_event_name": "Stop"}, tmp_path)

    scratch = _scratch_dir(tmp_path)
    assert (scratch / "session-XYZ.jsonl").exists()
    assert not (scratch / "unknown.jsonl").exists()
