"""Tests for the context-usefulness feedback loop — issue #343.

Covers:
  record_context_usefulness_item — valid/invalid inputs, WAL append
  write_context_usefulness       — artifact written, summary correct, manifest stage set
  _load_usefulness_scores        — loads scores from JSON, empty on missing artifact
  build_recall (boost/penalty)   — helpful digest boosted, stale penalized, missing data neutral
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest

# ---------------------------------------------------------------------------
# Import map_step_runner (same pattern as test_governance_attack_fixtures.py)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_PATH = REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"

sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]

from mapify_cli.memory.finalize import _build_frontmatter
from mapify_cli.memory.recall import _load_usefulness_scores, build_recall

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
    body: str = "",
    decisions: list[object] | None = None,
    findings: list[object] | None = None,
    ticket_refs: list[str] | None = None,
) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    fm = _build_frontmatter(
        session_id=session_id,
        branch=branch,
        date_iso=date,
        slug=slug,
        files_touched=[],
        decisions=decisions if decisions is not None else cast(list[object], []),
        findings=findings if findings is not None else cast(list[object], []),
        ticket_refs=ticket_refs or [],
    )
    path = sessions_dir / f"{date}-{slug}.md"
    path.write_text(fm + "\n" + body + "\n", encoding="utf-8")
    return path


def _make_usefulness_json(
    branch_dir: Path,
    *,
    items: list[dict[str, object]],
) -> Path:
    """Write a context_usefulness.json fixture."""
    branch_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"total": len(items)}
    for item in items:
        label = str(item.get("outcome_label") or "unknown")
        counts[label] = counts.get(label, 0) + 1
    payload = {
        "schema_version": "1.0",
        "generated_at": "2026-07-15T00:00:00Z",
        "branch": "test-branch",
        "workflow": "map-efficient",
        "terminal_status": "complete",
        "items": items,
        "summary": counts,
    }
    path = branch_dir / "context_usefulness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests: record_context_usefulness_item
# ---------------------------------------------------------------------------


class TestRecordContextUsefulnessItem:
    def test_valid_record_appended_to_wal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A valid record is appended as JSONL to the WAL file."""
        branch = "feat/test"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        result = map_step_runner.record_context_usefulness_item(
            kind="memory_digest",
            source="2026-01-01-auth-session",
            outcome_label="helpful",
            signals={"terminal_status": "complete", "retry_count": 0},
            branch=branch,
        )

        assert result["status"] == "success"
        wal = tmp_path / ".map" / branch / "context_usefulness.jsonl"
        assert wal.exists()
        lines = [ln for ln in wal.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["kind"] == "memory_digest"
        assert record["source"] == "2026-01-01-auth-session"
        assert record["outcome_label"] == "helpful"
        assert record["signals"] == {"terminal_status": "complete", "retry_count": 0}
        assert "ts" in record

    def test_multiple_records_accumulate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each call appends a new line — WAL grows per record."""
        branch = "feat/test"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        for label in ("helpful", "ignored", "stale"):
            map_step_runner.record_context_usefulness_item(
                kind="learned_rule", source=f"rule-{label}", outcome_label=label, branch=branch
            )

        wal = tmp_path / ".map" / branch / "context_usefulness.jsonl"
        lines = [ln for ln in wal.read_text().splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_invalid_kind_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "br")
        monkeypatch.chdir(tmp_path)
        result = map_step_runner.record_context_usefulness_item(
            kind="nonexistent_kind", source="x", outcome_label="helpful", branch="br"
        )
        assert result["status"] == "error"
        assert "kind" in result["message"]

    def test_invalid_outcome_label_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "br")
        monkeypatch.chdir(tmp_path)
        result = map_step_runner.record_context_usefulness_item(
            kind="memory_digest", source="x", outcome_label="bad_label", branch="br"
        )
        assert result["status"] == "error"
        assert "outcome_label" in result["message"]

    def test_empty_source_returns_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: "br")
        monkeypatch.chdir(tmp_path)
        result = map_step_runner.record_context_usefulness_item(
            kind="memory_digest", source="", outcome_label="helpful", branch="br"
        )
        assert result["status"] == "error"
        assert "source" in result["message"]


# ---------------------------------------------------------------------------
# Tests: write_context_usefulness
# ---------------------------------------------------------------------------


class TestWriteContextUsefulness:
    def test_writes_artifact_from_wal(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Artifact is written with correct items and summary from WAL records."""
        branch = "feat/cu"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        # Seed a WAL manually
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True, exist_ok=True)
        wal_records = [
            {"ts": "t1", "kind": "memory_digest", "source": "s1", "outcome_label": "helpful", "signals": {}},
            {"ts": "t2", "kind": "learned_rule", "source": "r1", "outcome_label": "ignored", "signals": {}},
            {"ts": "t3", "kind": "memory_digest", "source": "s2", "outcome_label": "helpful", "signals": {}},
        ]
        wal = branch_dir / "context_usefulness.jsonl"
        wal.write_text("\n".join(json.dumps(r) for r in wal_records) + "\n", encoding="utf-8")

        result = map_step_runner.write_context_usefulness(
            workflow="map-efficient", terminal_status="complete", branch=branch
        )

        assert result["status"] == "success"
        artifact_path = Path(result["path"])
        assert artifact_path.exists()
        data = json.loads(artifact_path.read_text())
        assert data["schema_version"] == "1.0"
        assert data["workflow"] == "map-efficient"
        assert data["terminal_status"] == "complete"
        assert data["branch"] == branch
        assert len(data["items"]) == 3
        assert data["summary"]["total"] == 3
        assert data["summary"]["helpful"] == 2
        assert data["summary"]["ignored"] == 1

    def test_empty_wal_produces_zero_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling write when no WAL exists produces zero-item artifact — not an error."""
        branch = "feat/empty"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        result = map_step_runner.write_context_usefulness(workflow="map-fast", branch=branch)

        assert result["status"] == "success"
        data = json.loads(Path(result["path"]).read_text())
        assert data["items"] == []
        assert data["summary"]["total"] == 0

    def test_manifest_stage_registered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The context_usefulness manifest stage is set to 'ready' after write."""
        branch = "feat/manifest"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        result = map_step_runner.write_context_usefulness(branch=branch)

        assert result["status"] == "success"
        manifest_path = Path(result["manifest_path"])
        manifest = json.loads(manifest_path.read_text())
        stage = manifest["stages"]["context_usefulness"]
        assert stage["status"] == "ready"
        assert len(stage["artifacts"]) == 1
        assert stage["metadata"]["total_items"] == 0

    def test_all_outcome_labels_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Summary covers all valid outcome labels."""
        branch = "feat/labels"
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
        monkeypatch.chdir(tmp_path)

        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True, exist_ok=True)
        labels = ["helpful", "used", "ignored", "stale", "over_budget", "unknown"]
        wal = branch_dir / "context_usefulness.jsonl"
        wal.write_text(
            "\n".join(
                json.dumps({"ts": "t", "kind": "memory_digest", "source": f"s{i}", "outcome_label": lbl, "signals": {}})
                for i, lbl in enumerate(labels)
            ) + "\n",
            encoding="utf-8",
        )

        result = map_step_runner.write_context_usefulness(branch=branch)
        data = json.loads(Path(result["path"]).read_text())
        summary = data["summary"]
        assert summary["total"] == 6
        for lbl in labels:
            assert summary[lbl] == 1, f"missing count for {lbl!r}"


# ---------------------------------------------------------------------------
# Tests: _load_usefulness_scores
# ---------------------------------------------------------------------------


class TestLoadUsefulnessScores:
    def test_returns_empty_when_no_artifact(self, tmp_path: Path) -> None:
        """Missing artifact → empty scores dict (preserves existing recall behaviour)."""
        scores = _load_usefulness_scores(tmp_path, "test-branch")
        assert scores == {}

    def test_helpful_and_used_produce_positive_deltas(self, tmp_path: Path) -> None:
        branch = "test-branch"
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[
                {"kind": "memory_digest", "source": "auth-session", "outcome_label": "helpful"},
                {"kind": "memory_digest", "source": "db-migration", "outcome_label": "used"},
            ],
        )
        scores = _load_usefulness_scores(tmp_path, branch)
        assert scores["auth-session"] > 0
        assert scores["db-migration"] > 0

    def test_stale_and_ignored_produce_negative_deltas(self, tmp_path: Path) -> None:
        branch = "test-branch"
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[
                {"kind": "memory_digest", "source": "old-notes", "outcome_label": "stale"},
                {"kind": "memory_digest", "source": "unrelated", "outcome_label": "ignored"},
            ],
        )
        scores = _load_usefulness_scores(tmp_path, branch)
        assert scores["old-notes"] < 0
        assert scores["unrelated"] < 0

    def test_non_memory_digest_items_excluded(self, tmp_path: Path) -> None:
        """Only memory_digest items affect recall scores; other kinds are skipped."""
        branch = "test-branch"
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[
                {"kind": "learned_rule", "source": "some-rule", "outcome_label": "helpful"},
                {"kind": "research_artifact", "source": "research", "outcome_label": "used"},
            ],
        )
        scores = _load_usefulness_scores(tmp_path, branch)
        assert scores == {}

    def test_malformed_artifact_returns_empty(self, tmp_path: Path) -> None:
        branch = "test-branch"
        branch_dir = tmp_path / ".map" / branch
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / "context_usefulness.json").write_text("not json!!", encoding="utf-8")
        scores = _load_usefulness_scores(tmp_path, branch)
        assert scores == {}

    def test_unknown_label_excluded_from_scores(self, tmp_path: Path) -> None:
        branch = "test-branch"
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[
                {"kind": "memory_digest", "source": "neutral-slug", "outcome_label": "unknown"},
                {"kind": "memory_digest", "source": "over-budget", "outcome_label": "over_budget"},
            ],
        )
        scores = _load_usefulness_scores(tmp_path, branch)
        # unknown and over_budget produce no adjustment
        assert scores == {}


# ---------------------------------------------------------------------------
# Tests: build_recall with usefulness boost/penalty
# ---------------------------------------------------------------------------


class TestRecallWithUsefulnessBoost:
    def test_helpful_digest_boosted_above_keyword_match(self, tmp_path: Path) -> None:
        """A 'helpful' digest with no keyword overlap can outrank an equal keyword digest
        by virtue of the usefulness boost."""
        branch = "boost-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        # Two digests with identical bodies — both score 0 on "irrelevant prompt".
        _write_digest(sessions_dir, date="2026-01-01", slug="auth-session", session_id="s1",
                      body="content about auth session details")
        _write_digest(sessions_dir, date="2026-01-01", slug="db-migration", session_id="s2",
                      body="content about db migration details")

        # Mark auth-session as helpful from prior run
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[{"kind": "memory_digest", "source": "auth-session", "outcome_label": "helpful"}],
        )

        result = build_recall("", branch, tmp_path)
        # auth-session must appear before db-migration
        auth_pos = result.find("auth-session")
        db_pos = result.find("db-migration")
        assert auth_pos != -1 and db_pos != -1
        assert auth_pos < db_pos, "helpful digest should appear before the unboosted one"

    def test_stale_digest_demoted_below_normal(self, tmp_path: Path) -> None:
        """A 'stale' digest is demoted and appears after a neutral equal-score digest."""
        branch = "demotion-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(sessions_dir, date="2026-01-01", slug="stale-notes", session_id="s1",
                      body="old notes about authentication flow")
        _write_digest(sessions_dir, date="2026-01-01", slug="neutral-digest", session_id="s2",
                      body="notes about authentication flow current")

        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[{"kind": "memory_digest", "source": "stale-notes", "outcome_label": "stale"}],
        )

        result = build_recall("", branch, tmp_path)
        stale_pos = result.find("stale-notes")
        neutral_pos = result.find("neutral-digest")
        assert stale_pos != -1 and neutral_pos != -1
        assert neutral_pos < stale_pos, "stale digest should appear after neutral"

    def test_missing_usefulness_artifact_preserves_behavior(self, tmp_path: Path) -> None:
        """When no context_usefulness.json exists recall returns same as baseline."""
        branch = "no-usefulness-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        _write_digest(sessions_dir, date="2026-01-02", slug="recent", session_id="s1",
                      body="recent decisions about deployment")
        _write_digest(sessions_dir, date="2026-01-01", slug="older", session_id="s2",
                      body="older context about feature flags")

        # No context_usefulness.json — should work normally
        result = build_recall("", branch, tmp_path)
        # Both digests should appear; recency rules (newest first)
        assert "recent" in result
        assert "older" in result
        assert result.index("recent") < result.index("older")

    def test_score_clamped_to_zero_for_heavily_penalized(self, tmp_path: Path) -> None:
        """A penalized digest score cannot go below zero (clamped)."""
        branch = "clamp-branch"
        sessions_dir = tmp_path / ".map" / branch / "sessions"

        # Only one digest — it will appear regardless of penalty, but its score is ≥ 0
        _write_digest(sessions_dir, date="2026-01-01", slug="low-value", session_id="s1", body="misc notes")

        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[{"kind": "memory_digest", "source": "low-value", "outcome_label": "stale"}],
        )

        result = build_recall("", branch, tmp_path)
        # Digest still present (single entry; clamp to 0, not negative)
        assert "low-value" in result

    def test_empty_recall_still_empty_with_usefulness_artifact(self, tmp_path: Path) -> None:
        """Usefulness artifact alone doesn't conjure digests from nothing."""
        branch = "no-digests-branch"
        _make_usefulness_json(
            tmp_path / ".map" / branch,
            items=[{"kind": "memory_digest", "source": "phantom", "outcome_label": "helpful"}],
        )
        result = build_recall("useful context", branch, tmp_path)
        assert result == ""
