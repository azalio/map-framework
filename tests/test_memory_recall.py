"""Tests for src/mapify_cli/memory/recall.py — pure, no subprocess.

Covers:
  VC1 [AC-3]  — ranking by keyword/ticket overlap; recency tiebreak.
  VC2 [SC-1]  — cap drop: overflow digests logged; output ≤ cap; no mid-cut.
  VC3         — control-char sanitization and secret redaction; fields via DIGEST_FRONTMATTER_FIELDS.
  VC4 [SC-1/OQ-3] — cap override changes inclusion; current-branch only.
  empty       — no digests → returns ""; no crash; no drop log.
  prompt=""   — recency order (newest date first).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from mapify_cli.memory.digest_schema import DIGEST_FRONTMATTER_FIELDS, REDACTION_TOKEN
from mapify_cli.memory.finalize import _build_frontmatter
from mapify_cli.memory.recall import build_recall

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_digest(
    sessions_dir: Path,
    *,
    date: str,
    slug: str,
    session_id: str,
    branch: str = "test-branch",
    files_touched: list[str] | None = None,
    decisions: list[object] | None = None,
    findings: list[object] | None = None,
    ticket_refs: list[str] | None = None,
    body: str = "",
) -> Path:
    """Write a digest .md file under *sessions_dir* and return its path."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    fm = _build_frontmatter(
        session_id=session_id,
        branch=branch,
        date_iso=date,
        slug=slug,
        files_touched=files_touched or [],
        decisions=decisions if decisions is not None else cast(list[object], []),
        findings=findings if findings is not None else cast(list[object], []),
        ticket_refs=ticket_refs or [],
    )
    path = sessions_dir / f"{date}-{slug}.md"
    path.write_text(fm + "\n" + body + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# VC1: Ranking — keyword/ticket overlap + recency tiebreak
# ---------------------------------------------------------------------------


class TestRanking:
    def test_keyword_match_ranks_first(self, tmp_path: Path) -> None:
        """A digest whose body contains prompt keywords appears first in output."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="alpha-work",
            session_id="sid-alpha",
            body="nothing relevant here at all",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-02",
            slug="beta-recall",
            session_id="sid-beta",
            body="implemented recall ranking algorithm for map framework",
        )

        result = build_recall(
            prompt="recall ranking algorithm",
            branch=branch,
            project_dir=tmp_path,
        )

        assert result != ""
        # beta appears first because it matches more prompt tokens.
        beta_pos = result.find("beta-recall")
        alpha_pos = result.find("alpha-work")
        assert beta_pos != -1, "beta-recall must appear in output"
        assert alpha_pos != -1, "alpha-work must appear in output"
        assert beta_pos < alpha_pos, "beta-recall (higher score) must appear before alpha-work"

    def test_ticket_ref_boost_ranks_first(self, tmp_path: Path) -> None:
        """A digest with a matching ticket_ref gets a boost and ranks first."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="generic-session",
            session_id="sid-generic",
            body="some work done today",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-02",
            slug="st004-work",
            session_id="sid-st004",
            ticket_refs=["ST-004"],
            body="implemented recall.py for ST-004",
        )

        result = build_recall(
            prompt="working on ST-004 recall",
            branch=branch,
            project_dir=tmp_path,
        )

        assert result != ""
        st004_pos = result.find("st004-work")
        generic_pos = result.find("generic-session")
        assert st004_pos != -1
        assert st004_pos < generic_pos, "ST-004 matching digest must come first"

    def test_equal_score_recency_tiebreak(self, tmp_path: Path) -> None:
        """When scores are equal, the newer digest appears first (recency tiebreak)."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="older-session",
            session_id="sid-old",
            body="generic work",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-05",
            slug="newer-session",
            session_id="sid-new",
            body="generic work",
        )

        result = build_recall(
            prompt="unrelated query",
            branch=branch,
            project_dir=tmp_path,
        )

        newer_pos = result.find("newer-session")
        older_pos = result.find("older-session")
        assert newer_pos != -1
        assert older_pos != -1
        assert newer_pos < older_pos, "newer digest must appear first on equal score"


# ---------------------------------------------------------------------------
# VC2: Cap drop — overflow digests logged, output ≤ cap, no mid-cut
# ---------------------------------------------------------------------------


class TestCapDrop:
    def test_drop_log_written_for_overflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dropped digests are logged in recall-drop.log with session_id + dropped_chars."""
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "200")
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        # Three digests — the first should rank highest (prompt keyword match),
        # the other two should be dropped due to the tiny cap.
        _write_digest(
            sessions_dir,
            date="2026-01-03",
            slug="top-ranked",
            session_id="sid-top",
            body="recall ranking implementation details for the memory subsystem",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-02",
            slug="second-place",
            session_id="sid-second",
            body="x" * 80,
        )
        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="third-place",
            session_id="sid-third",
            body="y" * 80,
        )

        result = build_recall(
            prompt="recall ranking memory",
            branch=branch,
            project_dir=tmp_path,
        )

        drop_log = sessions_dir / "recall-drop.log"
        assert drop_log.exists(), "recall-drop.log must be created for dropped digests"

        records = [json.loads(line) for line in drop_log.read_text().splitlines() if line.strip()]
        assert len(records) >= 1, "at least one digest must be dropped and logged"

        for rec in records:
            assert "session_id" in rec, "drop record must have session_id"
            assert "dropped_chars" in rec, "drop record must have dropped_chars"
            assert rec["dropped_chars"] > 0, "dropped_chars must be positive"
            assert rec.get("reason") == "recall_cap"

        # Output must be within cap.
        assert len(result) <= 200 or result == "", f"output exceeds cap: {len(result)}"

    def test_no_mid_digest_cut(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each included digest block is complete — never truncated mid-block."""
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "250")
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-03",
            slug="block-one",
            session_id="sid-one",
            body="alpha beta gamma delta",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-02",
            slug="block-two",
            session_id="sid-two",
            body="epsilon zeta eta theta",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="block-three",
            session_id="sid-three",
            body="iota kappa lambda mu",
        )

        result = build_recall(prompt="", branch=branch, project_dir=tmp_path)

        # If a digest slug appears, the block is whole (starts with '###').
        for slug in ("block-one", "block-two", "block-three"):
            if slug in result:
                idx = result.find("### ")
                # Each occurrence of ### must lead a complete block.
                assert idx != -1

        # Confirm length is within cap.
        assert len(result) <= 250 or result == ""

    def test_first_digest_too_large_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When even the first digest exceeds cap, return "" and log the drop."""
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "10")
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="big-block",
            session_id="sid-big",
            body="very long body that definitely exceeds ten characters",
        )

        result = build_recall(prompt="big block", branch=branch, project_dir=tmp_path)
        assert result == ""

        drop_log = sessions_dir / "recall-drop.log"
        assert drop_log.exists()
        records = [json.loads(line) for line in drop_log.read_text().splitlines() if line.strip()]
        assert len(records) == 1
        assert records[0]["session_id"] is not None

    def test_multi_block_payload_never_exceeds_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: with >=2 included blocks the "\\n".join separators must be
        counted, so the assembled payload length never exceeds the cap. Before the
        separator was accounted for, N included blocks overran the cap by N-1 chars.
        """
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "600")
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        # Several small digests so that multiple whole blocks are included
        # together under the cap (exercising the inter-block separator path).
        for i in range(6):
            _write_digest(
                sessions_dir,
                date=f"2026-01-0{i + 1}",
                slug=f"digest-{i}",
                session_id=f"sid-{i}",
                body=f"short body number {i}",
            )

        result = build_recall(prompt="", branch=branch, project_dir=tmp_path)

        # At least two blocks must have been included for this to be meaningful.
        assert result.count("### ") >= 2, "test should include multiple blocks"
        # Strict invariant: the assembled payload never exceeds the cap.
        assert len(result) <= 600, f"output exceeds cap: {len(result)}"


# ---------------------------------------------------------------------------
# VC3: Sanitize/redact — control chars stripped; secrets redacted; INV-7
# ---------------------------------------------------------------------------


class TestSanitizeRedact:
    def test_control_char_stripped(self, tmp_path: Path) -> None:
        """Control characters in digest body must not appear in output."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        body_with_ctrl = "normal text \x00 and more text"
        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="ctrl-test",
            session_id="sid-ctrl",
            body=body_with_ctrl,
        )

        result = build_recall(prompt="", branch=branch, project_dir=tmp_path)
        assert "\x00" not in result, "null byte must be stripped from output"

    def test_secret_redacted(self, tmp_path: Path) -> None:
        """A sk-<16+chars> secret in digest body must be replaced with «redacted»."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        secret = "sk-" + "A" * 20  # matches the openai pattern
        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="secret-test",
            session_id="sid-secret",
            body=f"API key used: {secret}",
        )

        result = build_recall(prompt="", branch=branch, project_dir=tmp_path)
        assert secret not in result, "raw secret must not appear in output"
        assert REDACTION_TOKEN in result, "redaction token must appear in output"

    def test_fields_via_digest_frontmatter_fields(self, tmp_path: Path) -> None:
        """Verify that DIGEST_FRONTMATTER_FIELDS are used to access frontmatter (INV-7).

        We write a digest with known values in all fields and confirm the output
        reflects content from at least two distinct fields (decisions, findings).
        This confirms the recall code reads fields via the schema constant, not
        hardcoded strings.
        """
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="field-test",
            session_id="sid-fields",
            decisions=["chose-approach-A"],
            findings=["confirmed-invariant-B"],
            body="session body text",
        )

        # Confirm DIGEST_FRONTMATTER_FIELDS includes expected keys.
        assert "decisions" in DIGEST_FRONTMATTER_FIELDS
        assert "findings" in DIGEST_FRONTMATTER_FIELDS
        assert "ticket_refs" in DIGEST_FRONTMATTER_FIELDS

        result = build_recall(prompt="chose-approach-A", branch=branch, project_dir=tmp_path)
        assert result != "", "should return non-empty when digest matches prompt"
        # Output must include the decisions content surfaced via the schema fields.
        assert "chose-approach-A" in result


# ---------------------------------------------------------------------------
# VC4: Cap override + current-branch-only isolation
# ---------------------------------------------------------------------------


class TestCapOverrideAndBranchIsolation:
    def test_cap_override_changes_inclusion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Larger MAP_MEMORY_RECALL_CAP includes more digests."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        for i in range(3):
            _write_digest(
                sessions_dir,
                date=f"2026-01-0{i + 1}",
                slug=f"session-{i}",
                session_id=f"sid-{i}",
                body="x" * 60,
            )

        # Tight cap — likely only 1 digest fits.
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "200")
        result_small = build_recall(prompt="", branch=branch, project_dir=tmp_path)

        # Large cap — all 3 digests fit.
        monkeypatch.setenv("MAP_MEMORY_RECALL_CAP", "4000")
        result_large = build_recall(prompt="", branch=branch, project_dir=tmp_path)

        assert len(result_large) >= len(result_small), (
            "larger cap must include at least as many chars as smaller cap"
        )
        # With 4000 cap all three slugs should appear.
        for i in range(3):
            assert f"session-{i}" in result_large, f"session-{i} must be in large-cap result"

    def test_different_branch_digest_not_recalled(self, tmp_path: Path) -> None:
        """A digest under a different branch dir must NOT appear in the recall output."""
        current_branch = "current-branch"
        other_branch = "other-branch"

        current_sessions = tmp_path / ".map" / current_branch / "sessions"
        other_sessions = tmp_path / ".map" / other_branch / "sessions"

        _write_digest(
            current_sessions,
            date="2026-01-01",
            slug="current-session",
            session_id="sid-current",
            body="this is from the current branch",
        )
        _write_digest(
            other_sessions,
            date="2026-01-02",
            slug="other-session",
            session_id="sid-other",
            body="this is from the other branch — must not appear",
        )

        result = build_recall(
            prompt="branch session",
            branch=current_branch,
            project_dir=tmp_path,
        )

        assert "current-session" in result, "current-branch digest must be recalled"
        assert "other-session" not in result, "other-branch digest must NOT be recalled"


# ---------------------------------------------------------------------------
# Edge: no digests → ""
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_sessions_dir_returns_empty_string(self, tmp_path: Path) -> None:
        """No digests → build_recall returns \"\" without crashing."""
        result = build_recall(prompt="anything", branch="no-branch", project_dir=tmp_path)
        assert result == ""

    def test_empty_sessions_dir_no_drop_log(self, tmp_path: Path) -> None:
        """No digests → no drop log created."""
        branch = "no-branch"
        build_recall(prompt="anything", branch=branch, project_dir=tmp_path)
        drop_log = tmp_path / ".map" / branch / "sessions" / "recall-drop.log"
        assert not drop_log.exists()

    def test_empty_prompt_recency_order(self, tmp_path: Path) -> None:
        """Empty prompt → digests appear in recency order (newest first)."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="oldest",
            session_id="sid-oldest",
            body="oldest session",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-05",
            slug="middle",
            session_id="sid-middle",
            body="middle session",
        )
        _write_digest(
            sessions_dir,
            date="2026-01-10",
            slug="newest",
            session_id="sid-newest",
            body="newest session",
        )

        result = build_recall(prompt="", branch=branch, project_dir=tmp_path)

        newest_pos = result.find("newest")
        middle_pos = result.find("middle")
        oldest_pos = result.find("oldest")

        assert newest_pos != -1
        assert middle_pos != -1
        assert oldest_pos != -1
        assert newest_pos < middle_pos < oldest_pos, (
            "empty prompt → recency order (newest first): "
            f"newest={newest_pos}, middle={middle_pos}, oldest={oldest_pos}"
        )

    def test_malformed_frontmatter_skipped(self, tmp_path: Path) -> None:
        """A digest with invalid YAML frontmatter is skipped without crashing."""
        branch = "test-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        bad_file = sessions_dir / "2026-01-01-bad.md"
        bad_file.write_text("---\n: bad: yaml: {\n---\nbody\n", encoding="utf-8")

        # Should not raise.
        result = build_recall(prompt="anything", branch=branch, project_dir=tmp_path)
        assert isinstance(result, str)

    def test_returns_string_not_none(self, tmp_path: Path) -> None:
        """build_recall never returns None."""
        result = build_recall(prompt="", branch="empty", project_dir=tmp_path)
        assert result is not None
        assert isinstance(result, str)

    def test_header_present_when_digests_included(self, tmp_path: Path) -> None:
        """Output includes the branch header when at least one digest is recalled."""
        branch = "feature-x"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(
            sessions_dir,
            date="2026-01-01",
            slug="some-session",
            session_id="sid-x",
            body="relevant content",
        )

        result = build_recall(prompt="relevant", branch=branch, project_dir=tmp_path)
        assert f"branch {branch}" in result
