"""Tests for durable approval-hold artifacts (#344)."""

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

import map_step_runner  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def branch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a fake git repo so get_branch_name() doesn't fail."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Minimal git structure so get_branch_name can resolve HEAD
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/test-branch\n", encoding="utf-8")
    refs = git_dir / "refs" / "heads"
    refs.mkdir(parents=True)
    monkeypatch.chdir(repo)
    return repo


def _map_dir(branch_dir: Path) -> Path:
    """Return the .map/<branch> directory."""
    return branch_dir / ".map" / "test-branch"


# ---------------------------------------------------------------------------
# create_approval_hold
# ---------------------------------------------------------------------------


class TestCreateApprovalHold:
    def test_creates_hold_with_required_fields(self, branch_dir: Path) -> None:
        result = map_step_runner.create_approval_hold(
            kind="safety_guardrail",
            reason="Hook denied rm -rf",
            request_summary="Actor attempted to remove .map/ directory",
            branch="test-branch",
        )
        assert result["status"] == "ok"
        assert result["hold_id"] == "hold-001"
        hold = result["hold"]
        assert hold["kind"] == "safety_guardrail"
        assert hold["state"] == "pending"
        assert hold["reason"] == "Hook denied rm -rf"
        assert hold["request_summary"] == "Actor attempted to remove .map/ directory"
        assert hold["decision"] is None
        assert hold["decided_at"] is None
        assert not result["idempotent"]

    def test_writes_json_artifact(self, branch_dir: Path) -> None:
        map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Plan requires approval",
            request_summary="Approve the generated plan",
            branch="test-branch",
        )
        store_path = _map_dir(branch_dir) / "approval_holds.json"
        assert store_path.exists()
        store = json.loads(store_path.read_text(encoding="utf-8"))
        assert store["branch"] == "test-branch"
        assert "hold-001" in store["holds"]
        assert store["holds"]["hold-001"]["state"] == "pending"

    def test_writes_markdown_report(self, branch_dir: Path) -> None:
        map_step_runner.create_approval_hold(
            kind="dangerous_action",
            reason="Risky shell command",
            request_summary="Run cleanup script",
            source="safety-guardrails.py",
            safe_continuation="Review the script before approving",
            branch="test-branch",
        )
        report = _map_dir(branch_dir) / "approval_hold_hold-001.md"
        assert report.exists()
        content = report.read_text(encoding="utf-8")
        assert "# Approval Hold: hold-001" in content
        assert "dangerous_action" in content
        assert "Risky shell command" in content
        assert "Review the script before approving" in content
        assert "safety-guardrails.py" in content

    def test_sequential_ids_increment(self, branch_dir: Path) -> None:
        r1 = map_step_runner.create_approval_hold(
            kind="plan_approval", reason="A", request_summary="S1", branch="test-branch"
        )
        r2 = map_step_runner.create_approval_hold(
            kind="dangerous_action", reason="B", request_summary="S2", branch="test-branch"
        )
        assert r1["hold_id"] == "hold-001"
        assert r2["hold_id"] == "hold-002"

    def test_idempotent_for_same_pending_hold(self, branch_dir: Path) -> None:
        first = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Same reason",
            request_summary="Identical summary",
            branch="test-branch",
        )
        second = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Same reason",
            request_summary="Identical summary",
            branch="test-branch",
        )
        assert first["hold_id"] == "hold-001"
        assert second["hold_id"] == "hold-001"
        assert second["idempotent"] is True
        # Only one hold should exist in the store
        store = json.loads(
            (_map_dir(branch_dir) / "approval_holds.json").read_text(encoding="utf-8")
        )
        assert len(store["holds"]) == 1

    def test_error_on_invalid_kind(self, branch_dir: Path) -> None:
        result = map_step_runner.create_approval_hold(
            kind="invalid_kind",
            reason="Some reason",
            request_summary="Some summary",
            branch="test-branch",
        )
        assert result["status"] == "error"
        assert any("invalid_kind" in r for r in result["reasons"])

    def test_error_on_empty_reason(self, branch_dir: Path) -> None:
        result = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="   ",
            request_summary="Some summary",
            branch="test-branch",
        )
        assert result["status"] == "error"
        assert any("reason" in r for r in result["reasons"])

    def test_error_on_empty_request_summary(self, branch_dir: Path) -> None:
        result = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Some reason",
            request_summary="",
            branch="test-branch",
        )
        assert result["status"] == "error"
        assert any("request_summary" in r for r in result["reasons"])

    def test_strips_whitespace_from_fields(self, branch_dir: Path) -> None:
        result = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="  reason with spaces  ",
            request_summary="  summary  ",
            branch="test-branch",
        )
        hold = result["hold"]
        assert hold["reason"] == "reason with spaces"
        assert hold["request_summary"] == "summary"

    def test_updates_artifact_manifest(self, branch_dir: Path) -> None:
        map_step_runner.create_approval_hold(
            kind="autonomy_posture",
            reason="Push blocked",
            request_summary="Push to origin",
            branch="test-branch",
        )
        manifest_path = _map_dir(branch_dir) / "artifact_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stage = manifest["stages"].get("approval_hold", {})
        assert stage.get("status") == "pending"

    def test_all_valid_kinds_accepted(self, branch_dir: Path) -> None:
        kinds = list(map_step_runner.APPROVAL_HOLD_KINDS)
        for i, kind in enumerate(kinds):
            result = map_step_runner.create_approval_hold(
                kind=kind,
                reason=f"Reason {i}",
                request_summary=f"Summary {i}",
                branch="test-branch",
            )
            assert result["status"] == "ok", f"kind {kind!r} rejected: {result}"


# ---------------------------------------------------------------------------
# decide_approval_hold
# ---------------------------------------------------------------------------


class TestDecideApprovalHold:
    def _make_hold(self, branch_dir: Path, kind: str = "plan_approval") -> str:
        del branch_dir
        r = map_step_runner.create_approval_hold(
            kind=kind,
            reason="Needs approval",
            request_summary="Approve the plan",
            branch="test-branch",
        )
        return str(r["hold_id"])

    def test_approved_transition(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        result = map_step_runner.decide_approval_hold(
            hold_id, "approved", note="LGTM", branch="test-branch"
        )
        assert result["status"] == "ok"
        hold = result["hold"]
        assert hold["state"] == "approved"
        assert hold["decision"] == "approved"
        assert hold["decision_note"] == "LGTM"
        assert hold["decided_at"] is not None
        assert not result["idempotent"]

    def test_denied_transition(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        result = map_step_runner.decide_approval_hold(
            hold_id, "denied", note="Too risky", branch="test-branch"
        )
        assert result["hold"]["state"] == "denied"

    def test_expired_transition(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        result = map_step_runner.decide_approval_hold(
            hold_id, "expired", branch="test-branch"
        )
        assert result["hold"]["state"] == "expired"

    def test_cancelled_transition(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        result = map_step_runner.decide_approval_hold(
            hold_id, "cancelled", branch="test-branch"
        )
        assert result["hold"]["state"] == "cancelled"

    def test_persists_decision_to_json(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.decide_approval_hold(
            hold_id, "approved", note="ok", branch="test-branch"
        )
        store = json.loads(
            (_map_dir(branch_dir) / "approval_holds.json").read_text(encoding="utf-8")
        )
        hold = store["holds"][hold_id]
        assert hold["state"] == "approved"
        assert hold["decision_note"] == "ok"

    def test_updates_markdown_report_with_decision(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.decide_approval_hold(
            hold_id, "approved", note="All clear", branch="test-branch"
        )
        report = _map_dir(branch_dir) / f"approval_hold_{hold_id}.md"
        content = report.read_text(encoding="utf-8")
        assert "## Decision" in content
        assert "approved" in content
        assert "All clear" in content

    def test_idempotent_same_decision(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.decide_approval_hold(hold_id, "approved", branch="test-branch")
        second = map_step_runner.decide_approval_hold(
            hold_id, "approved", branch="test-branch"
        )
        assert second["status"] == "ok"
        assert second["idempotent"] is True

    def test_error_on_re_decide_with_different_decision(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.decide_approval_hold(hold_id, "approved", branch="test-branch")
        result = map_step_runner.decide_approval_hold(
            hold_id, "denied", branch="test-branch"
        )
        assert result["status"] == "error"
        assert any("terminal" in r for r in result["reasons"])

    def test_error_on_invalid_decision(self, branch_dir: Path) -> None:
        hold_id = self._make_hold(branch_dir)
        result = map_step_runner.decide_approval_hold(
            hold_id, "pending", branch="test-branch"
        )
        assert result["status"] == "error"
        assert any("pending" in r for r in result["reasons"])

    def test_error_on_unknown_hold_id(self, branch_dir: Path) -> None:
        result = map_step_runner.decide_approval_hold(
            "hold-999", "approved", branch="test-branch"
        )
        assert result["status"] == "error"
        assert any("not found" in r for r in result["reasons"])

    def test_manifest_stage_becomes_decided_when_no_pending_remain(
        self, branch_dir: Path
    ) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.decide_approval_hold(hold_id, "approved", branch="test-branch")
        manifest = json.loads(
            (_map_dir(branch_dir) / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["stages"]["approval_hold"]["status"] == "decided"

    def test_manifest_stage_stays_pending_when_more_holds_remain(
        self, branch_dir: Path
    ) -> None:
        hold_id = self._make_hold(branch_dir)
        map_step_runner.create_approval_hold(
            kind="dangerous_action",
            reason="Another reason",
            request_summary="Another action",
            branch="test-branch",
        )
        map_step_runner.decide_approval_hold(hold_id, "approved", branch="test-branch")
        manifest = json.loads(
            (_map_dir(branch_dir) / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["stages"]["approval_hold"]["status"] == "pending"


# ---------------------------------------------------------------------------
# list_approval_holds
# ---------------------------------------------------------------------------


class TestListApprovalHolds:
    def _populate(self, branch_dir: Path) -> list[str]:
        del branch_dir
        ids = []
        r1 = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="R1",
            request_summary="S1",
            branch="test-branch",
        )
        ids.append(r1["hold_id"])
        r2 = map_step_runner.create_approval_hold(
            kind="dangerous_action",
            reason="R2",
            request_summary="S2",
            branch="test-branch",
        )
        ids.append(r2["hold_id"])
        map_step_runner.decide_approval_hold(r2["hold_id"], "approved", branch="test-branch")
        return ids

    def test_lists_all_holds(self, branch_dir: Path) -> None:
        self._populate(branch_dir)
        result = map_step_runner.list_approval_holds(branch="test-branch")
        assert result["status"] == "ok"
        assert result["count"] == 2

    def test_filters_by_pending(self, branch_dir: Path) -> None:
        self._populate(branch_dir)
        result = map_step_runner.list_approval_holds(branch="test-branch", state="pending")
        assert result["count"] == 1
        assert result["holds"][0]["state"] == "pending"

    def test_filters_by_approved(self, branch_dir: Path) -> None:
        self._populate(branch_dir)
        result = map_step_runner.list_approval_holds(branch="test-branch", state="approved")
        assert result["count"] == 1
        assert result["holds"][0]["state"] == "approved"

    def test_empty_store_returns_zero_count(self, branch_dir: Path) -> None:
        result = map_step_runner.list_approval_holds(branch="test-branch")
        assert result["count"] == 0
        assert result["holds"] == []

    def test_error_on_invalid_state_filter(self, branch_dir: Path) -> None:
        result = map_step_runner.list_approval_holds(
            branch="test-branch", state="invalid"
        )
        assert result["status"] == "error"

    def test_holds_sorted_by_created_at(self, branch_dir: Path) -> None:
        self._populate(branch_dir)
        result = map_step_runner.list_approval_holds(branch="test-branch")
        timestamps = [h["created_at"] for h in result["holds"]]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# get_pending_holds
# ---------------------------------------------------------------------------


class TestGetPendingHolds:
    def test_resume_blocked_true_when_pending_exists(self, branch_dir: Path) -> None:
        map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Needs approval",
            request_summary="Approve plan",
            branch="test-branch",
        )
        result = map_step_runner.get_pending_holds(branch="test-branch")
        assert result["status"] == "ok"
        assert result["has_pending"] is True
        assert result["pending_count"] == 1
        assert result["resume_blocked"] is True

    def test_resume_not_blocked_when_no_pending(self, branch_dir: Path) -> None:
        result = map_step_runner.get_pending_holds(branch="test-branch")
        assert result["has_pending"] is False
        assert result["pending_count"] == 0
        assert result["resume_blocked"] is False

    def test_resume_not_blocked_after_decision(self, branch_dir: Path) -> None:
        r = map_step_runner.create_approval_hold(
            kind="plan_approval",
            reason="Needs approval",
            request_summary="Approve plan",
            branch="test-branch",
        )
        map_step_runner.decide_approval_hold(r["hold_id"], "approved", branch="test-branch")
        result = map_step_runner.get_pending_holds(branch="test-branch")
        assert result["resume_blocked"] is False


# ---------------------------------------------------------------------------
# Constants / schema
# ---------------------------------------------------------------------------


class TestConstants:
    def test_approval_hold_in_artifact_stage_names(self) -> None:
        assert "approval_hold" in map_step_runner.ARTIFACT_STAGE_NAMES

    def test_all_kinds_are_strings(self) -> None:
        for kind in map_step_runner.APPROVAL_HOLD_KINDS:
            assert isinstance(kind, str) and kind, f"invalid kind: {kind!r}"

    def test_terminal_states_disjoint_from_pending(self) -> None:
        assert "pending" not in map_step_runner.APPROVAL_HOLD_TERMINAL_STATES

    def test_all_states_includes_pending(self) -> None:
        assert "pending" in map_step_runner.APPROVAL_HOLD_ALL_STATES

    def test_all_states_includes_all_terminal(self) -> None:
        assert map_step_runner.APPROVAL_HOLD_TERMINAL_STATES.issubset(
            map_step_runner.APPROVAL_HOLD_ALL_STATES
        )


# ---------------------------------------------------------------------------
# CLI subprocess tests
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> tuple[int, dict[str, Any]]:
    """Run map_step_runner.py CLI and return (returncode, parsed_stdout)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_PATH / "map_step_runner.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = {"_raw_stdout": proc.stdout, "_stderr": proc.stderr}
    return proc.returncode, parsed


class TestCLI:
    def test_create_approval_hold_cli_success(
        self, branch_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del monkeypatch
        code, result = _run_cli(
            "create_approval_hold",
            "--kind", "plan_approval",
            "--reason", "CLI test reason",
            "--request-summary", "CLI test summary",
            "--branch", "test-branch",
        )
        assert code == 0, f"stderr: {result.get('_stderr')}"
        assert result.get("status") == "ok"
        assert result.get("hold_id") == "hold-001"

    def test_create_approval_hold_cli_invalid_kind_exits_nonzero(
        self, branch_dir: Path
    ) -> None:
        del branch_dir
        code, result = _run_cli(
            "create_approval_hold",
            "--kind", "not_a_kind",
            "--reason", "R",
            "--request-summary", "S",
            "--branch", "test-branch",
        )
        assert code != 0
        assert result.get("status") == "error"

    def test_decide_approval_hold_cli(
        self, branch_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del monkeypatch
        # First create a hold
        _run_cli(
            "create_approval_hold",
            "--kind", "plan_approval",
            "--reason", "R",
            "--request-summary", "S",
            "--branch", "test-branch",
        )
        code, result = _run_cli(
            "decide_approval_hold",
            "hold-001",
            "approved",
            "--note", "LGTM",
            "--branch", "test-branch",
        )
        assert code == 0, f"stderr: {result.get('_stderr')}"
        assert result["hold"]["state"] == "approved"

    def test_list_approval_holds_cli_empty(
        self, branch_dir: Path
    ) -> None:
        del branch_dir
        code, result = _run_cli(
            "list_approval_holds",
            "--branch", "test-branch",
        )
        assert code == 0
        assert result.get("count") == 0

    def test_get_pending_holds_cli(self, branch_dir: Path) -> None:
        del branch_dir
        code, result = _run_cli(
            "get_pending_holds",
            "--branch", "test-branch",
        )
        assert code == 0
        assert result.get("resume_blocked") is False

    def test_get_pending_holds_cli_with_pending(
        self, branch_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del monkeypatch
        _run_cli(
            "create_approval_hold",
            "--kind", "safety_guardrail",
            "--reason", "Hook blocked",
            "--request-summary", "Risky delete",
            "--branch", "test-branch",
        )
        code, result = _run_cli(
            "get_pending_holds",
            "--branch", "test-branch",
        )
        assert code == 0
        assert result.get("resume_blocked") is True
        assert result.get("pending_count") == 1
