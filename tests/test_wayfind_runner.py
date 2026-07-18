"""Tests for wayfind_runner — /map-wayfind decision-frontier map operations."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

import wayfind_runner as wr  # noqa: E402  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scope every test's .map/wayfind/ to an isolated tmp cwd."""
    monkeypatch.chdir(tmp_path)


# Pytest finds fixtures via module-namespace lookup, which Pylance/Pyright
# can't see — without this sentinel the IDE flags `_chdir` as "not accessed".
# The reference is a no-op at runtime (mirrors tests/conftest.py).
_ = _chdir


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The tmp cwd, for tests that assert on written files."""
    return tmp_path


def _write_resolution(slug: str, ticket_id: str, text: str = "The decision prose.") -> str:
    """Write a prose resolution and return its MAP-DIR-relative path (runner contract)."""
    rel = f"resolutions/{ticket_id}.md"
    path = Path(".map/wayfind") / slug / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


def _write_human_input(slug: str, ticket_id: str, text: str = "Human says: option B.") -> str:
    rel = f"resolutions/{ticket_id}.human.md"
    path = Path(".map/wayfind") / slug / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel


def _create(slug: str = "checkout", **kw: Any) -> dict[str, Any]:
    return wr.create_wayfind_map(
        slug,
        kw.get("title", "Checkout v2"),
        kw.get("destination", "Ship a redesigned checkout flow."),
        kw.get("notes", ""),
        kw.get("fog_json", "[]"),
    )


def _resolve(slug: str, ticket_id: str, session: str, gist: str = "decided") -> dict[str, Any]:
    """Claim + resolve a non-HITL ticket (task/research) in one shot."""
    wr.claim_ticket(slug, ticket_id, session)
    path = _write_resolution(slug, ticket_id)
    return wr.resolve_ticket(slug, ticket_id, session, gist, path)


# ---------------------------------------------------------------------------
# 1. Map creation
# ---------------------------------------------------------------------------


class TestMapCreation:
    def test_creates_state_and_views(self, repo: Path) -> None:
        result = _create(fog_json='["how does auth interact?"]')
        assert result["status"] == "success"
        state_file = repo / ".map" / "wayfind" / "checkout" / "state.json"
        map_file = repo / ".map" / "wayfind" / "checkout" / "map.md"
        assert state_file.exists()
        assert map_file.exists()
        state = json.loads(state_file.read_text())
        assert state["slug"] == "checkout"
        assert state["backend"] == "local"
        assert state["map_id"]
        assert state["revision"] == 1
        assert state["status"] == "charting"
        assert len(state["fog"]) == 1
        assert state["fog"][0]["id"] == "F-1"

    def test_map_md_has_all_sections_and_banner(self, repo: Path) -> None:
        _create()
        content = (repo / ".map" / "wayfind" / "checkout" / "map.md").read_text()
        assert "DO NOT EDIT" in content
        for heading in (
            "## Destination",
            "## Notes",
            "## Decisions so far",
            "## Frontier",
            "## Fog of war",
            "## Out of scope",
        ):
            assert heading in content, f"missing section {heading!r}"

    @pytest.mark.parametrize("bad", ["", "Has Space", "UPPER", "a" * 51, "bad/slug"])
    def test_rejects_invalid_slug(self, bad: str) -> None:
        assert _create(slug=bad)["status"] == "error"

    def test_duplicate_slug_rejected(self) -> None:
        assert _create()["status"] == "success"
        dup = _create()
        assert dup["status"] == "error"
        assert dup["code"] == "duplicate"

    def test_empty_destination_rejected(self) -> None:
        assert _create(destination="")["status"] == "error"


# ---------------------------------------------------------------------------
# 2. Claiming
# ---------------------------------------------------------------------------


class TestClaiming:
    def test_claim_sets_fields(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Pick a store", "task", "Which store?")["ticket_id"]
        result = wr.claim_ticket("checkout", tid, "sess-1")
        assert result["status"] == "success"
        assert result["hitl_pending"] is False
        state = wr._load_state("checkout")
        assert state["tickets"][tid]["claimed_by"] == "sess-1"
        assert state["tickets"][tid]["claimed_at"]
        assert state["status"] == "active"

    def test_double_claim_rejected(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "T", "task", "Q?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        again = wr.claim_ticket("checkout", tid, "sess-2")
        assert again["status"] == "error"
        assert again["code"] == "already_claimed"

    def test_claim_blocked_ticket_rejected(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "task", "Qb?", blocked_by_json=json.dumps([a]))["ticket_id"]
        result = wr.claim_ticket("checkout", b, "sess-1")
        assert result["status"] == "error"
        assert result["code"] == "blocked"

    def test_resolve_without_claim_rejected(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "T", "task", "Q?")["ticket_id"]
        path = _write_resolution("checkout", tid)
        result = wr.resolve_ticket("checkout", tid, "sess-1", "g", path)
        assert result["status"] == "error"
        assert result["code"] == "not_owner"

    def test_release_restores_claimability(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "T", "task", "Q?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        assert wr.release_ticket("checkout", tid, "sess-2")["status"] == "error"  # not owner
        assert wr.release_ticket("checkout", tid, "sess-1")["status"] == "success"
        assert wr.claim_ticket("checkout", tid, "sess-2")["status"] == "success"

    def test_claim_hitl_returns_pending(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Grill me", "grilling", "What exactly?")["ticket_id"]
        result = wr.claim_ticket("checkout", tid, "sess-1")
        assert result["status"] == "success"
        assert result["hitl_pending"] is True
        assert "human" in result["message"].lower()

    def test_resolve_clears_claim(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "T", "research", "Q?")["ticket_id"]
        _resolve("checkout", tid, "sess-1")
        ticket = wr._load_state("checkout")["tickets"][tid]
        assert ticket["claimed_by"] is None
        assert ticket["claimed_at"] is None


# ---------------------------------------------------------------------------
# 3. Frontier
# ---------------------------------------------------------------------------


class TestFrontier:
    def test_blocked_excluded_until_blocker_resolved(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "research", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "task", "Qb?", blocked_by_json=json.dumps([a]))["ticket_id"]
        frontier = [t["ticket_id"] for t in wr.wayfind_frontier("checkout")["frontier"]]
        assert frontier == [a]
        _resolve("checkout", a, "sess-1")
        frontier = [t["ticket_id"] for t in wr.wayfind_frontier("checkout")["frontier"]]
        assert b in frontier

    def test_cycle_rejected(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "task", "Qb?", blocked_by_json=json.dumps([a]))["ticket_id"]
        result = wr.wire_blocking("checkout", a, json.dumps([b]))
        assert result["status"] == "error"
        assert result["code"] == "cycle"

    def test_unknown_blocker_rejected(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        assert wr.wire_blocking("checkout", a, json.dumps(["T-999"]))["status"] == "error"
        assert wr.add_ticket(
            "checkout", "B", "task", "Qb?", blocked_by_json=json.dumps(["T-999"])
        )["status"] == "error"

    def test_claimed_excluded_from_frontier(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        wr.claim_ticket("checkout", a, "sess-1")
        frontier = [t["ticket_id"] for t in wr.wayfind_frontier("checkout")["frontier"]]
        assert a not in frontier

    def test_self_block_rejected(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        assert wr.wire_blocking("checkout", a, json.dumps([a]))["status"] == "error"


# ---------------------------------------------------------------------------
# 4. Fog graduation
# ---------------------------------------------------------------------------


class TestFogGraduation:
    def test_graduate_creates_ticket_and_marks_fog(self, repo: Path) -> None:
        _create(fog_json='["auth interplay unclear"]')
        result = wr.graduate_fog("checkout", "F-1", "Resolve auth", "grilling", "How does auth interact?")
        assert result["status"] == "success"
        tid = result["ticket_id"]
        state = wr._load_state("checkout")
        assert state["tickets"][tid]["from_fog"] == "F-1"
        assert state["fog"][0]["status"] == "graduated"
        content = (repo / ".map" / "wayfind" / "checkout" / "map.md").read_text()
        fog_section = content.split("## Fog of war")[1].split("## Out of scope")[0]
        assert "auth interplay unclear" not in fog_section

    def test_double_graduation_rejected(self) -> None:
        _create(fog_json='["x"]')
        wr.graduate_fog("checkout", "F-1", "T", "task", "Q?")
        again = wr.graduate_fog("checkout", "F-1", "T2", "task", "Q2?")
        assert again["status"] == "error"
        assert again["code"] == "already_graduated"

    def test_add_fog_mints_incrementing_ids(self) -> None:
        _create()
        assert wr.add_fog("checkout", "first")["fog_id"] == "F-1"
        assert wr.add_fog("checkout", "second")["fog_id"] == "F-2"


# ---------------------------------------------------------------------------
# 5. Out of scope
# ---------------------------------------------------------------------------


class TestOutOfScope:
    def test_ticket_ruled_out_leaves_frontier_and_records_reason(self, repo: Path) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Maybe later", "task", "Support legacy?")["ticket_id"]
        result = wr.rule_out_of_scope("checkout", "Legacy is EOL", ticket_id=tid)
        assert result["status"] == "success"
        frontier = [t["ticket_id"] for t in wr.wayfind_frontier("checkout")["frontier"]]
        assert tid not in frontier
        content = (repo / ".map" / "wayfind" / "checkout" / "map.md").read_text()
        oos_section = content.split("## Out of scope")[1]
        assert "Legacy is EOL" in oos_section
        decisions_section = content.split("## Decisions so far")[1].split("## Frontier")[0]
        assert tid not in decisions_section

    def test_retire_fog(self) -> None:
        _create(fog_json='["speculative idea"]')
        result = wr.rule_out_of_scope("checkout", "Not this quarter", fog_id="F-1")
        assert result["status"] == "success"
        state = wr._load_state("checkout")
        assert state["fog"][0]["status"] == "retired"

    def test_requires_exactly_one_target(self) -> None:
        _create()
        assert wr.rule_out_of_scope("checkout", "r")["status"] == "error"
        assert wr.rule_out_of_scope("checkout", "r", ticket_id="T-1", fog_id="F-1")["status"] == "error"


# ---------------------------------------------------------------------------
# 6. Handoff
# ---------------------------------------------------------------------------


class TestHandoff:
    def test_open_items_block_handoff(self) -> None:
        _create()
        wr.add_ticket("checkout", "Open", "task", "Q?")
        result = wr.emit_wayfind_handoff("checkout", branch="test-branch")
        assert result["status"] == "error"
        assert result["code"] == "not_terminal"
        assert result["open_items"]

    def test_clean_emit_writes_artifacts_and_manifest(self, repo: Path) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Pick DB", "research", "Which DB?")["ticket_id"]
        _resolve("checkout", tid, "sess-1", gist="Use Postgres")
        result = wr.emit_wayfind_handoff("checkout", branch="test-branch")
        assert result["status"] == "success", result
        assert (repo / ".map" / "wayfind" / "checkout" / "handoff.md").exists()
        handoff = json.loads((repo / ".map" / "wayfind" / "checkout" / "handoff.json").read_text())
        assert handoff["decisions"][0]["gist"] == "Use Postgres"
        assert wr._load_state("checkout")["status"] == "handed_off"
        assert result["manifest"]["status"] == "success"
        manifest = json.loads((repo / ".map" / "test-branch" / "artifact_manifest.json").read_text())
        assert manifest["stages"]["wayfind_handoff"]["status"] == "ready"

    def test_early_requires_confirmation_and_folds_open_items(self, repo: Path) -> None:
        _create()
        wr.add_ticket("checkout", "Still open", "task", "Q?")
        assert wr.emit_wayfind_handoff("checkout", early=True, branch="test-branch")["status"] == "error"
        result = wr.emit_wayfind_handoff(
            "checkout", early=True, confirmed_by_user=True, branch="test-branch"
        )
        assert result["status"] == "success"
        handoff = json.loads((repo / ".map" / "wayfind" / "checkout" / "handoff.json").read_text())
        assert any("UNRESOLVED" in r for r in handoff["remaining_risks"])

    def test_list_handoffs_finds_completed(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Pick DB", "research", "Which DB?")["ticket_id"]
        _resolve("checkout", tid, "sess-1")
        wr.emit_wayfind_handoff("checkout", branch="test-branch")
        result = wr.list_handoffs()
        assert result["count"] == 1
        assert result["handoffs"][0]["slug"] == "checkout"

    def test_mutation_after_handoff_rejected(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Pick DB", "research", "Which DB?")["ticket_id"]
        _resolve("checkout", tid, "sess-1")
        assert wr.emit_wayfind_handoff("checkout", branch="test-branch")["status"] == "success"
        # any ticket/fog mutation after handoff must be rejected (frozen handoff)
        blocked = wr.add_ticket("checkout", "Late idea", "task", "too late?")
        assert blocked["status"] == "error"
        assert blocked["code"] == "handed_off"
        assert wr.add_fog("checkout", "late fog")["code"] == "handed_off"

    def test_emit_stale_revision_rejected(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Pick DB", "research", "Which DB?")["ticket_id"]
        _resolve("checkout", tid, "sess-1")
        stale = wr.emit_wayfind_handoff("checkout", branch="test-branch", expected_revision=0)
        assert stale["status"] == "error"
        assert stale["code"] == "stale_revision"


# ---------------------------------------------------------------------------
# 6b. Evidence-path containment
# ---------------------------------------------------------------------------


class TestEvidencePathContainment:
    def _claimed_ticket(self) -> str:
        _create()
        tid = wr.add_ticket("checkout", "T", "task", "Q?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        return tid

    def test_absolute_resolution_path_rejected(self, repo: Path) -> None:
        tid = self._claimed_ticket()
        outside = repo / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        result = wr.resolve_ticket("checkout", tid, "sess-1", "g", str(outside))
        assert result["status"] == "error"
        assert result["code"] == "missing_resolution"

    def test_parent_escape_resolution_rejected(self) -> None:
        tid = self._claimed_ticket()
        escape = Path(".map/wayfind") / "escape.md"
        escape.write_text("x", encoding="utf-8")  # real file OUTSIDE the map dir
        result = wr.resolve_ticket("checkout", tid, "sess-1", "g", "../escape.md")
        assert result["status"] == "error"
        assert result["code"] == "missing_resolution"

    def test_directory_resolution_rejected(self) -> None:
        tid = self._claimed_ticket()
        adir = Path(".map/wayfind/checkout/resolutions/adir")
        adir.mkdir(parents=True, exist_ok=True)
        result = wr.resolve_ticket("checkout", tid, "sess-1", "g", "resolutions/adir")
        assert result["status"] == "error"
        assert result["code"] == "missing_resolution"

    def test_absolute_human_input_path_rejected(self, repo: Path) -> None:
        _create()
        tid = wr.add_ticket("checkout", "G", "grilling", "Q?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        outside = repo / "human.md"
        outside.write_text("hi", encoding="utf-8")
        result = wr.record_human_input("checkout", tid, "sess-1", str(outside))
        assert result["status"] == "error"
        assert result["code"] == "missing_input"


# ---------------------------------------------------------------------------
# 7. Session guardrail + HITL gate
# ---------------------------------------------------------------------------


class TestSessionGuardrail:
    def test_second_non_research_resolve_blocked(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "task", "Qb?")["ticket_id"]
        assert _resolve("checkout", a, "sess-1")["status"] == "success"
        second = _resolve("checkout", b, "sess-1")
        assert second["status"] == "error"
        assert second["code"] == "session_limit"

    def test_two_research_resolves_allowed(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "research", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "research", "Qb?")["ticket_id"]
        assert _resolve("checkout", a, "sess-1")["status"] == "success"
        assert _resolve("checkout", b, "sess-1")["status"] == "success"

    def test_new_session_can_resolve_again(self) -> None:
        _create()
        a = wr.add_ticket("checkout", "A", "task", "Qa?")["ticket_id"]
        b = wr.add_ticket("checkout", "B", "task", "Qb?")["ticket_id"]
        assert _resolve("checkout", a, "sess-1")["status"] == "success"
        assert _resolve("checkout", b, "sess-2")["status"] == "success"

    def test_hitl_resolve_without_human_input_blocked(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Grill", "grilling", "What exactly?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        path = _write_resolution("checkout", tid)
        blocked = wr.resolve_ticket("checkout", tid, "sess-1", "g", path)
        assert blocked["status"] == "error"
        assert blocked["code"] == "awaiting_human"
        human = _write_human_input("checkout", tid)
        assert wr.record_human_input("checkout", tid, "sess-1", human)["status"] == "success"
        assert wr.resolve_ticket("checkout", tid, "sess-1", "g", path)["status"] == "success"

    def test_record_human_input_requires_nonempty_file(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Grill", "grilling", "What?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        empty_rel = f"resolutions/{tid}.human.md"
        empty = Path(".map/wayfind/checkout") / empty_rel
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("   \n", encoding="utf-8")
        result = wr.record_human_input("checkout", tid, "sess-1", empty_rel)
        assert result["status"] == "error"
        assert result["code"] == "missing_input"


# ---------------------------------------------------------------------------
# 8. Views / files
# ---------------------------------------------------------------------------


class TestViews:
    def test_empty_resolution_file_blocks_resolve(self) -> None:
        _create()
        tid = wr.add_ticket("checkout", "T", "task", "Q?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        empty_rel = f"resolutions/{tid}.md"
        empty = Path(".map/wayfind/checkout") / empty_rel
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("", encoding="utf-8")
        result = wr.resolve_ticket("checkout", tid, "sess-1", "g", empty_rel)
        assert result["status"] == "error"
        assert result["code"] == "missing_resolution"

    def test_one_decision_line_per_resolved_ticket(self, repo: Path) -> None:
        _create()
        a = wr.add_ticket("checkout", "Alpha", "research", "Qa?")["ticket_id"]
        _resolve("checkout", a, "sess-1", gist="Chose alpha")
        content = (repo / ".map" / "wayfind" / "checkout" / "map.md").read_text()
        decisions_section = content.split("## Decisions so far")[1].split("## Frontier")[0]
        assert decisions_section.count(f"**{a}**") == 1
        assert "Chose alpha" in decisions_section

    def test_ticket_view_written(self, repo: Path) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Alpha", "task", "Qa?")["ticket_id"]
        assert (repo / ".map" / "wayfind" / "checkout" / "tickets" / f"{tid}.md").exists()

    def test_awaiting_human_badge_in_map(self, repo: Path) -> None:
        _create()
        tid = wr.add_ticket("checkout", "Grill", "grilling", "What?")["ticket_id"]
        wr.claim_ticket("checkout", tid, "sess-1")
        content = (repo / ".map" / "wayfind" / "checkout" / "map.md").read_text()
        assert "AWAITING HUMAN" in content


# ---------------------------------------------------------------------------
# 9. Revision guard
# ---------------------------------------------------------------------------


class TestRevisionGuard:
    def test_stale_expected_revision_rejected(self) -> None:
        _create()
        current = wr._load_state("checkout")["revision"]
        good = wr.add_ticket("checkout", "T", "task", "Q?", expected_revision=current)
        assert good["status"] == "success"
        stale = wr.add_ticket("checkout", "T2", "task", "Q2?", expected_revision=current)
        assert stale["status"] == "error"
        assert stale["code"] == "stale_revision"


# ---------------------------------------------------------------------------
# 10. CLI smoke
# ---------------------------------------------------------------------------


class TestCli:
    def _run(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_PATH / "wayfind_runner.py"), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )

    def test_create_and_status_via_cli(self, repo: Path) -> None:
        created = self._run(repo, "create_wayfind_map", "cli-map", "T", "Dest")
        assert created.returncode == 0, created.stderr
        assert json.loads(created.stdout)["status"] == "success"
        status = self._run(repo, "wayfind_status", "--slug", "cli-map")
        assert status.returncode == 0, status.stdout
        payload = json.loads(status.stdout)
        assert payload["status"] == "success"
        assert payload["slug"] == "cli-map"

    def test_error_status_exits_nonzero(self, repo: Path) -> None:
        result = self._run(repo, "wayfind_status", "--slug", "nope")
        assert result.returncode == 1
        assert json.loads(result.stdout)["status"] == "error"

    def test_unknown_subcommand_exits_nonzero(self, repo: Path) -> None:
        result = self._run(repo, "bogus_command")
        assert result.returncode != 0
