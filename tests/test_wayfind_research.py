"""Public research protocol and fresh-process recovery checks."""

import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "src/mapify_cli/templates_src/map/scripts/wayfind_runner.py.jinja")
loader = importlib.machinery.SourceFileLoader("wayfind_research_runner", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
wr = importlib.util.module_from_spec(spec)
loader.exec_module(wr)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


_ = isolated


def cli(*args: str) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(SOURCE), *args], capture_output=True, text=True, check=False)
    assert proc.stderr == "", proc.stderr
    result = json.loads(proc.stdout)
    assert proc.returncode == (0 if result["status"] == "success" else 1)
    return result


def write_artifact(ticket: str, name: str, payload: Any) -> str:
    rel = f"research/{ticket}/{name}"
    path = Path(".map/wayfind/demo") / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
    return rel


def research_ticket(mode: str = "direct") -> str:
    assert cli("create_wayfind_map", "demo", "Demo", "Decide safely")["status"] == "success"
    ticket = cli("add_ticket", "demo", "Lookup", "research", "What is present?")["ticket_id"]
    assert cli("claim_ticket", "demo", ticket, "owner")["status"] == "success"
    assert cli("configure_research", "demo", ticket, "owner", mode, "Inspectable factual lookup")["status"] == "success"
    return ticket


def brief(ticket: str, name: str = "brief.json", target: Any = None) -> str:
    context = cli("research_context", "demo", ticket)["context"]
    return write_artifact(ticket, name, {
        "protocol_version": 1, "ticket_id": ticket, "question": context["question"],
        "constraints": ["Read-only"], "settling_criteria": ["Inspect source"],
        "dependency_bindings": context["dependency_bindings"], "verification_target": target,
    })


def reserve(ticket: str, request: str = "request-1", phase: str = "initial", investigator: str = "worker-a", path: str | None = None) -> dict[str, Any]:
    return cli("reserve_research_attempt", "demo", ticket, "owner", request, phase, investigator, path or brief(ticket))


def test_default_on_research_cannot_resolve_without_assessment() -> None:
    ticket = research_ticket()
    resolution = write_artifact(ticket, "resolution.md", "A source-backed decision")
    result = cli("resolve_ticket", "demo", ticket, "owner", "Present", resolution)
    assert result["code"] == "research_assessment_required"
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert ledger["protocol_version"] == 1
    assert ledger["budget_limit"] is None


@pytest.mark.parametrize("outcome", ["failed", "unknown", "cancelled"])
def test_explicit_budget_is_configured_before_work_and_cannot_be_replaced(outcome: str) -> None:
    ticket = research_ticket()
    command = ("configure_research", "demo", ticket, "owner", "direct", "Task budget", "--budget-limit", "2")
    assert cli(*command)["status"] == "success"
    assert cli(*command)["created"] is False
    assert cli("research_context", "demo", ticket)["context"]["budget_limit"] == 2
    assert cli(*command[:-1], "3")["status"] == "error"
    for index in range(2):
        attempt = reserve(ticket, f"bounded-{index}")
        assert attempt["status"] == "success"
        assert cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], outcome, "--reason", "Unavailable")["status"] == "success"
    assert reserve(ticket, "over-limit")["code"] == "research_budget_exhausted"
    assert cli("configure_research", "demo", ticket, "owner", "independent", "Escalate")["status"] == "success"
    assert cli("research_context", "demo", ticket)["context"]["budget_limit"] == 2


@pytest.mark.parametrize("limit", [0, -1, True, False, 2.5, "4", [], {}])
def test_invalid_budget_does_not_mutate_state(limit: Any) -> None:
    ticket = research_ticket()
    path = Path(".map/wayfind/demo/state.json")
    before = path.read_bytes()
    result = wr.configure_research("demo", ticket, "owner", "direct", "Task cap", budget_limit=limit)
    assert result["status"] == "error"
    assert path.read_bytes() == before


@pytest.mark.parametrize("limit", [4, 7])
def test_persisted_budget_remains_binding(limit: int) -> None:
    ticket = research_ticket()
    path = Path(".map/wayfind/demo/state.json")
    state = json.loads(path.read_text())
    state["tickets"][ticket]["research"]["budget_limit"] = limit
    path.write_text(json.dumps(state))  # Pre-upgrade persisted protocol-v1 fixture.
    assert cli("configure_research", "demo", ticket, "owner", "direct", "Resume")["status"] == "success"
    assert cli("configure_research", "demo", ticket, "owner", "direct", "Replace", "--budget-limit", str(limit + 1))["status"] == "error"
    for index in range(limit):
        assert reserve(ticket, f"legacy-{index}")["status"] == "success"
    assert reserve(ticket, "legacy-extra")["code"] == "research_budget_exhausted"
    assert cli("research_context", "demo", ticket)["context"]["budget_limit"] == limit


def test_budget_cannot_be_added_after_unbounded_work_starts() -> None:
    ticket = research_ticket()
    assert reserve(ticket)["status"] == "success"
    before = Path(".map/wayfind/demo/state.json").read_bytes()
    assert cli("configure_research", "demo", ticket, "owner", "direct", "Late cap", "--budget-limit", "8")["status"] == "error"
    assert Path(".map/wayfind/demo/state.json").read_bytes() == before


def test_unbounded_research_rejects_budget_extension_cleanly() -> None:
    ticket = research_ticket()
    result = cli("extend_research_budget", "demo", ticket, "owner", "extra", "2", "missing.json", "More")
    assert result["code"] == "research_budget_not_bounded"


def test_default_research_continues_past_four_attempts() -> None:
    ticket = research_ticket()
    for index in range(6):
        attempt = reserve(ticket, f"request-{index}")
        assert attempt["status"] == "success", attempt
        assert cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], "failed", "--reason", "Source unavailable")["status"] == "success"
    context = cli("research_context", "demo", ticket)["context"]
    assert context["budget_limit"] is None
    assert context["spent_attempts"] == 6


def test_reservations_are_durable_idempotent_and_spent_after_reclaim() -> None:
    ticket = research_ticket()
    assert cli("configure_research", "demo", ticket, "owner", "direct", "Task cap", "--budget-limit", "4")["status"] == "success"
    path = brief(ticket)
    first = reserve(ticket, path=path)
    assert first["created"] is True
    replay = reserve(ticket, path=path)
    assert replay["created"] is False
    assert replay["attempt_id"] == first["attempt_id"]
    assert reserve(ticket, investigator="other", path=path)["code"] == "conflicting_replay"
    assert cli("record_research_attempt", "demo", ticket, "owner", first["attempt_id"], "unknown", "--reason", "Dispatch interrupted")["status"] == "success"
    assert cli("release_ticket", "demo", ticket, "owner")["status"] == "success"
    assert cli("claim_ticket", "demo", ticket, "owner")["status"] == "success"
    for index in range(2, 5):
        assert reserve(ticket, f"request-{index}", path=path)["created"] is True
    assert reserve(ticket, "request-5", path=path)["code"] == "research_budget_exhausted"
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 4


def completed(ticket: str, request: str = "request-1", investigator: str = "worker-a", phase: str = "initial", target: Any = None, source: str = "Present") -> dict[str, Any]:
    path = brief(ticket, f"{request}.brief.json", target)
    attempt = reserve(ticket, request, phase, investigator, path)["attempt"]
    Path("answer.txt").write_text(source)
    report = {
        "protocol_version": 1, "ticket_id": ticket, "attempt_id": attempt["attempt_id"],
        "brief_sha256": attempt["brief_sha256"], "answer": "Present",
        "claims": [{"id": "present", "text": "Present", "evidence": ["source"]}],
        "sources": [{"id": "source", "kind": "local_code", "path": "answer.txt", "sha256": hashlib.sha256(source.encode()).hexdigest()}],
        "decisive_assumptions": [], "falsification_conditions": ["Source absent"], "uncertainty": [],
    }
    report_path = write_artifact(ticket, f"{attempt['attempt_id']}/report.json", report)
    result = cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], "completed", "--result-path", report_path)
    assert result["status"] == "success", result
    return cli("show_ticket", "demo", ticket)["ticket"]["research"]["attempts"][-1]


def assessment(ticket: str, attempts: list[dict[str, Any]], name: str = "assessment-1", disputes: Any = None, gist: str = "Present", verdict: str = "sufficient") -> str:
    resolution_path = write_artifact(ticket, f"{name}.resolution.md", gist)
    return write_artifact(ticket, f"{name}.json", {
        "protocol_version": 1, "ticket_id": ticket, "assessment_id": name,
        "attempt_bindings": [{"attempt_id": a["attempt_id"], "report_sha256": a["report_sha256"]} for a in attempts],
        "verdict": verdict, "gist": gist, "resolution_path": resolution_path,
        "resolution_sha256": hashlib.sha256(gist.encode()).hexdigest(),
        "material_disputes": disputes or [], "remaining_uncertainty": [],
        "no_further_verification_rationale": "Decisive source inspected",
    })


def accept(ticket: str, attempts: list[dict[str, Any]], name: str = "assessment-1", gist: str = "Present") -> dict[str, Any]:
    path = assessment(ticket, attempts, name, gist=gist)
    result = cli("record_research_assessment", "demo", ticket, "owner", path)
    assert result["status"] == "success", result
    return cli("resolve_ticket", "demo", ticket, "owner", gist, f"research/{ticket}/{name}.resolution.md")


def test_direct_resolution_requires_current_evidence_and_exact_assessment() -> None:
    ticket = research_ticket()
    attempt = completed(ticket)
    assert accept(ticket, [attempt])["status"] == "success"
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    assert cli("validate_wayfind_handoff", "demo")["evidence_status"] == "recorded"
    before = Path(".map/wayfind/demo/state.json").read_bytes()
    Path("answer.txt").write_text("Changed")
    assert cli("validate_wayfind_handoff", "demo")["status"] == "error"
    assert Path(".map/wayfind/demo/state.json").read_bytes() == before


def test_failed_initial_does_not_complete_independent_pair() -> None:
    ticket = research_ticket("independent")
    first = completed(ticket)
    second = reserve(ticket, "request-2", investigator="worker-b")["attempt_id"]
    cli("record_research_attempt", "demo", ticket, "owner", second, "failed", "--reason", "Unavailable")
    path = assessment(ticket, [first])
    assert cli("record_research_assessment", "demo", ticket, "owner", path)["status"] == "error"


def test_independent_pair_can_converge_without_forced_disagreement() -> None:
    ticket = research_ticket("independent")
    first = completed(ticket)
    second = completed(ticket, "request-2", "worker-b")
    assert accept(ticket, [first, second])["status"] == "success"


def test_human_authorization_is_one_use_even_with_different_extension_id() -> None:
    ticket = research_ticket()
    assert cli("configure_research", "demo", ticket, "owner", "direct", "Task cap", "--budget-limit", "4")["status"] == "success"
    approval = {"protocol_version": 1, "ticket_id": ticket, "extension_id": "extra-1", "additional_attempts": 2, "current_budget_limit": 4, "human_approval": "Yes, authorize exactly two more attempts", "reason": "Verify conflict"}
    path = write_artifact(ticket, "approval.json", approval)
    command = ("extend_research_budget", "demo", ticket, "owner", "extra-1", "2", path, "Verify conflict")
    assert cli(*command)["budget_limit"] == 6
    assert cli(*command)["created"] is False
    assert cli("extend_research_budget", "demo", ticket, "owner", "extra-2", "2", path, "Verify conflict")["budget_limit"] == 6
    approval["extension_id"] = "extra-3"
    path2 = write_artifact(ticket, "approval-copy.json", approval)
    assert cli("extend_research_budget", "demo", ticket, "owner", "extra-3", "2", path2, "Verify conflict")["status"] == "error"
    assert wr.extend_research_budget("demo", ticket, "owner", "bad", True, path, "Verify conflict")["status"] == "error"


def test_post_handoff_correction_owns_session_and_early_omits_old_decision() -> None:
    ticket = research_ticket()
    first = completed(ticket)
    assert accept(ticket, [first])["status"] == "success"
    cli("emit_wayfind_handoff", "demo", "--remaining-risks-json", '["Operational risk"]')
    result = cli("begin_research_correction", "demo", ticket, "owner", "Decision changed")
    assert result["created"] is True
    assert cli("begin_research_correction", "demo", ticket, "stranger", "Steal")["status"] == "error"
    assert cli("emit_wayfind_handoff", "demo")["code"] == "active_research_correction"
    assert cli("emit_wayfind_handoff", "demo", "--early", "--confirmed-by-user")["status"] == "success"
    payload = json.loads(Path(".map/wayfind/demo/handoff.json").read_text())
    assert payload["decisions"] == []
    assert "Operational risk" in payload["remaining_risks"]
    assert cli("emit_wayfind_handoff", "demo", "--early", "--confirmed-by-user")["status"] == "success"
    assert json.loads(Path(".map/wayfind/demo/handoff.json").read_text())["remaining_risks"] == payload["remaining_risks"]
    assert cli("validate_wayfind_handoff", "demo")["status"] == "success"
    assert cli("release_research_correction", "demo", ticket, "owner")["status"] == "success"
    assert cli("claim_research_correction", "demo", ticket, "owner")["status"] == "success"
    second = completed(ticket, "correction-1")
    path = assessment(ticket, [second], "corrected", gist="Corrected")
    result = cli("amend_resolution", "demo", ticket, "--gist", "Corrected", "--resolution-path", f"research/{ticket}/corrected.resolution.md", "--assessment-path", path, "--session", "owner")
    assert result["status"] == "success", result
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert len(ledger["attempts"]) == 2
    assert ledger["budget_limit"] is None
    assert ledger["correction"]["active"] is False
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    assert json.loads(Path(".map/wayfind/demo/handoff.json").read_text())["remaining_risks"] == ["Operational risk"]
    assert cli("validate_wayfind_handoff", "demo")["status"] == "success"


def test_unrelated_verification_cannot_settle_material_dispute() -> None:
    ticket = research_ticket("independent")
    first, second = completed(ticket), completed(ticket, "request-2", "worker-b")
    check = completed(ticket, "verify", "worker-c", "verification", {"dispute_id": "other", "claim": "Other", "falsification_condition": "Absent"})
    disputes = [{"id": "d1", "claim": "Present", "falsification_condition": "Source absent", "disposition": "verified", "verification_attempt_ids": [check["attempt_id"]], "rationale": "Checked"}]
    path = assessment(ticket, [first, second, check], disputes=disputes)
    assert cli("record_research_assessment", "demo", ticket, "owner", path)["status"] == "error"


@pytest.mark.parametrize("boundary", ["before_replace", "after_replace", "views"])
def test_reservation_restart_recovers_atomic_commit(boundary: str) -> None:
    ticket = research_ticket()
    path = brief(ticket)
    injection = {
        "before_replace": "wr.Path.replace = lambda self, target: (_ for _ in ()).throw(OSError('interrupted before replace'))",
        "after_replace": "original = wr.Path.replace\ndef replace(self, target):\n original(self, target)\n raise OSError('interrupted after replace')\nwr.Path.replace = replace",
        "views": "wr._render_views = lambda state: (_ for _ in ()).throw(OSError('view failure'))",
    }[boundary]
    code = "import runpy, types\nwr=types.SimpleNamespace(**runpy.run_path(" + repr(str(SOURCE)) + "))\n" + injection + "\ntry:\n wr.reserve_research_attempt('demo', '" + ticket + "', 'owner', 'request-1', 'initial', 'worker-a', '" + path + "')\nexcept OSError:\n pass\n"
    # runpy functions retain their globals; patch those rather than the namespace for views.
    if boundary == "views":
        code = code.replace("wr._render_views =", "wr.reserve_research_attempt.__wrapped__.__globals__['_render_views'] =")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    replay = reserve(ticket, path=path)
    assert replay["created"] is (boundary == "before_replace")
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 1


@pytest.mark.parametrize("tamper", ["report", "brief", "assessment", "resolution", "missing_report"])
def test_bound_artifact_tampering_blocks_resolution(tamper: str) -> None:
    ticket = research_ticket()
    attempt = completed(ticket)
    path = assessment(ticket, [attempt])
    assert cli("record_research_assessment", "demo", ticket, "owner", path)["status"] == "success"
    rel = {"report": attempt["report_path"], "missing_report": attempt["report_path"], "brief": attempt["brief_path"], "assessment": path, "resolution": f"research/{ticket}/assessment-1.resolution.md"}[tamper]
    artifact = Path(".map/wayfind/demo") / rel
    if tamper == "missing_report":
        artifact.unlink()
    else:
        artifact.write_bytes(artifact.read_bytes() + b" ")
    assert cli("resolve_ticket", "demo", ticket, "owner", "Present", f"research/{ticket}/assessment-1.resolution.md")["code"] == "research_reassessment_required"


def test_editorial_correction_reuses_current_evidence_without_spending() -> None:
    ticket = research_ticket()
    first = completed(ticket)
    assert accept(ticket, [first])["status"] == "success"
    assert cli("begin_research_correction", "demo", ticket, "owner", "Clarify wording")["status"] == "success"
    path = assessment(ticket, [first], "editorial", gist="Present, clarified")
    result = cli("amend_resolution", "demo", ticket, "--gist", "Present, clarified", "--resolution-path", f"research/{ticket}/editorial.resolution.md", "--assessment-path", path, "--session", "owner")
    assert result["status"] == "success", result
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 1
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    assert cli("validate_wayfind_handoff", "demo")["status"] == "success"


def test_independent_initials_cannot_use_different_settling_criteria() -> None:
    ticket = research_ticket("independent")
    first = completed(ticket)
    path = brief(ticket, "different.brief.json")
    full_path = Path(".map/wayfind/demo") / path
    data = json.loads(full_path.read_text())
    data["settling_criteria"] = ["Choose preferred option"]
    full_path.write_text(json.dumps(data))
    attempt = reserve(ticket, "request-2", investigator="worker-b", path=path)["attempt"]
    source_report = json.loads((Path(".map/wayfind/demo") / first["report_path"]).read_text())
    source_report.update(attempt_id=attempt["attempt_id"], brief_sha256=attempt["brief_sha256"])
    report_path = write_artifact(ticket, f"{attempt['attempt_id']}/report.json", source_report)
    assert cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], "completed", "--result-path", report_path)["status"] == "success"
    second = cli("show_ticket", "demo", ticket)["ticket"]["research"]["attempts"][-1]
    assert cli("record_research_assessment", "demo", ticket, "owner", assessment(ticket, [first, second]))["status"] == "error"


def test_dependency_amendment_invalidates_only_dependent_evidence() -> None:
    ticket = research_ticket()
    dependency = cli("add_ticket", "demo", "Prerequisite", "task", "What prerequisite?")["ticket_id"]
    cli("claim_ticket", "demo", dependency, "owner")
    rel = write_artifact(dependency, "resolution.md", "Before")
    assert cli("resolve_ticket", "demo", dependency, "owner", "Before", rel)["status"] == "success"
    assert cli("wire_blocking", "demo", ticket, json.dumps([dependency]))["status"] == "success"
    attempt = completed(ticket)
    path = assessment(ticket, [attempt])
    assert cli("record_research_assessment", "demo", ticket, "owner", path)["status"] == "success"
    Path("unrelated.txt").write_text("Unrelated dirty change")
    cli("add_fog", "demo", "Unrelated map revision")
    assert cli("resolve_ticket", "demo", ticket, "owner", "Present", f"research/{ticket}/assessment-1.resolution.md")["status"] == "success"
    assert cli("amend_resolution", "demo", dependency, "--gist", "After")["status"] == "success"
    assert cli("emit_wayfind_handoff", "demo", "--early", "--confirmed-by-user")["code"] == "research_reassessment_required"


def test_handoff_bytes_commitment_rejects_interrupted_publication() -> None:
    ticket = research_ticket()
    assert accept(ticket, [completed(ticket)])["status"] == "success"
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    for filename in ("handoff.json", "handoff.md"):
        path = Path(".map/wayfind/demo") / filename
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        assert cli("validate_wayfind_handoff", "demo")["status"] == "error"
        assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
        assert cli("validate_wayfind_handoff", "demo")["status"] == "success"


def test_legacy_reads_do_not_initialize_research() -> None:
    ticket = research_ticket()
    state_path = Path(".map/wayfind/demo/state.json")
    state = json.loads(state_path.read_text())
    state["tickets"][ticket].pop("research")
    state["tickets"][ticket].update(status="resolved", claimed_by=None, resolution={"gist": "Legacy", "path": "old.md"})
    state["status"] = "handed_off"
    state_path.write_text(json.dumps(state))
    Path(".map/wayfind/demo/handoff.json").write_text(json.dumps({"slug": "demo", "map_id": state["map_id"], "decisions": []}))
    Path(".map/wayfind/demo/handoff.md").write_text("Legacy handoff")
    before = state_path.read_bytes()
    assert cli("validate_wayfind_handoff", "demo")["evidence_status"] == "legacy_unrecorded"
    assert cli("show_ticket", "demo", ticket)["status"] == "success"
    assert state_path.read_bytes() == before


def test_local_source_alias_cannot_hash_secret_target() -> None:
    ticket = research_ticket()
    Path(".env").write_text("sensitive")
    Path("alias.txt").symlink_to(".env")
    assert cli("research_artifact_hash", "demo", "alias.txt", "--scope", "local_code")["status"] == "error"
    revision = cli("wayfind_status", "--slug", "demo")["revision"]
    assert wr.configure_research("demo", ticket, "owner", "direct", "Reason", expected_revision=revision - 1)["code"] == "stale_revision"


@pytest.mark.parametrize("field,value", [("resolution_path", 17), ("material_disputes", [{}]), ("attempt_bindings", [None]), ("attempt_bindings", [{"attempt_id": []}]), ("verdict", []), ("material_disputes", [{"id": "d", "claim": "Claim", "falsification_condition": "Absent", "rationale": "Reason", "disposition": [], "verification_attempt_ids": []}])])
def test_malformed_assessment_returns_error_not_traceback(field: str, value: Any) -> None:
    ticket = research_ticket()
    first = completed(ticket)
    path = assessment(ticket, [first])
    full_path = Path(".map/wayfind/demo") / path
    data = json.loads(full_path.read_text())
    data[field] = value
    full_path.write_text(json.dumps(data))
    assert cli("record_research_assessment", "demo", ticket, "owner", path)["status"] == "error"


def test_unknown_recovers_original_result_and_replays_without_dispatch() -> None:
    ticket = research_ticket()
    first = completed(ticket)
    state_path = Path(".map/wayfind/demo/state.json")
    state = json.loads(state_path.read_text())
    state["tickets"][ticket]["research"]["attempts"][0].update(outcome="unknown", reason="Interrupted before result registration")
    state["tickets"][ticket]["research"]["attempts"][0].pop("report_path")
    state["tickets"][ticket]["research"]["attempts"][0].pop("report_sha256")
    state_path.write_text(json.dumps(state))
    command = ("record_research_attempt", "demo", ticket, "owner", first["attempt_id"], "completed", "--result-path", first["report_path"])
    assert cli(*command)["created"] is True
    assert cli(*command)["created"] is False
    assert reserve(ticket, path=first["brief_path"])["created"] is False
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 1


@pytest.mark.parametrize("boundary", ["json", "markdown", "state"])
def test_handoff_publication_crashes_are_rejected_and_reemittable(boundary: str) -> None:
    ticket = research_ticket()
    assert accept(ticket, [completed(ticket)])["status"] == "success"
    injection = "original = wr.Path.replace\ndef replace(self, target):\n original(self, target)\n if self.name.startswith('.handoff.json'):\n  raise OSError('json committed, markdown absent')\nwr.Path.replace = replace" if boundary == "json" else "original = wr.Path.write_text\ndef write(self, *args, **kwargs):\n result = original(self, *args, **kwargs)\n if self.name == 'handoff.md':\n  raise OSError('markdown committed, state absent')\n return result\nwr.Path.write_text = write" if boundary == "markdown" else "original = wr.Path.replace\ndef replace(self, target):\n original(self, target)\n if self.name.startswith('.state.json'):\n  raise OSError('state committed, response absent')\nwr.Path.replace = replace"
    code = "import runpy, types\nwr=types.SimpleNamespace(**runpy.run_path(" + repr(str(SOURCE)) + "))\n" + injection + "\nwr.emit_wayfind_handoff('demo')\n"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    assert cli("validate_wayfind_handoff", "demo")["status"] == ("success" if boundary == "state" else "error")
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    assert cli("validate_wayfind_handoff", "demo")["status"] == "success"


def test_correction_restart_after_commit_preserves_owner_and_budget() -> None:
    ticket = research_ticket()
    assert accept(ticket, [completed(ticket)])["status"] == "success"
    code = "import runpy, types\nwr=types.SimpleNamespace(**runpy.run_path(" + repr(str(SOURCE)) + "))\noriginal=wr.Path.replace\ndef replace(self, target):\n original(self,target)\n raise OSError('after correction commit')\nwr.Path.replace=replace\nwr.begin_research_correction('demo','" + ticket + "','owner','Correct')\n"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    context = cli("research_context", "demo", ticket)["context"]
    assert context["correction"]["owner_session"] == "owner"
    assert context["spent_attempts"] == 1
    assert cli("begin_research_correction", "demo", ticket, "owner", "Correct")["created"] is False


def test_unknown_can_be_explicitly_cancelled_without_resetting_spend() -> None:
    ticket = research_ticket()
    attempt = reserve(ticket)["attempt"]
    assert cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], "unknown", "--reason", "No response")["status"] == "success"
    assert cli("record_research_attempt", "demo", ticket, "owner", attempt["attempt_id"], "cancelled", "--reason", "Confirmed abandoned")["status"] == "success"
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 1


@pytest.mark.parametrize("bounded", [True, False])
def test_open_research_refresh_after_exhaustion_preserves_history_and_budget(bounded: bool) -> None:
    ticket = research_ticket("independent")
    if bounded:
        assert cli("configure_research", "demo", ticket, "owner", "independent", "Task cap", "--budget-limit", "4")["status"] == "success"
    attempts = [completed(ticket, f"old-{i}", f"worker-{i}") for i in range(4)]
    blocked = assessment(ticket, attempts, "stale-blocked", verdict="blocked")
    Path("answer.txt").write_text("Changed")
    state_path = Path(".map/wayfind/demo/state.json")
    before = state_path.read_bytes()
    assert "source content changed" in cli("record_research_assessment", "demo", ticket, "owner", blocked)["message"]
    assert cli("begin_research_correction", "demo", ticket, "owner", "Refresh stale source")["status"] == "error"
    assert state_path.read_bytes() == before
    artifacts = {p: p.read_bytes() for p in state_path.parent.rglob("*") if p.is_file() and "research" in p.parts}
    refreshed = cli("refresh_open_research", "demo", ticket, "owner", "Source evolved")
    assert refreshed["status"] == "success", refreshed
    assert refreshed["spent_attempts"] == 4
    assert refreshed["budget_limit"] == (4 if bounded else None)
    entry = refreshed["refresh"]
    assert entry["from_generation"] == 0 and entry["to_generation"] == 1
    assert {a["attempt_id"] for a in entry["stale_attempts"]} == {a["attempt_id"] for a in attempts}
    assert all("source content changed" in a["error"] for a in entry["stale_attempts"])
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert ledger["attempts"] == attempts
    assert ledger["evidence_refresh_history"] == [entry]
    assert all(p.read_bytes() == contents for p, contents in artifacts.items())
    if bounded:
        assert reserve(ticket, "fresh-0")["code"] == "research_budget_exhausted"
    blocked = assessment(ticket, [], "fresh-blocked", verdict="blocked")
    assert cli("record_research_assessment", "demo", ticket, "owner", blocked)["status"] == "success"
    assert cli("resolve_ticket", "demo", ticket, "owner", "Present", f"research/{ticket}/fresh-blocked.resolution.md")["code"] == "research_assessment_required"
    approval = write_artifact(ticket, "refresh-approval.json", {"protocol_version": 1, "ticket_id": ticket, "extension_id": "refresh-extra", "additional_attempts": 2, "current_budget_limit": 4, "human_approval": "Yes, authorize two fresh investigations", "reason": "Source evolved"})
    if bounded:
        assert cli("extend_research_budget", "demo", ticket, "owner", "refresh-extra", "2", approval, "Source evolved")["budget_limit"] == 6
    fresh = [completed(ticket, f"fresh-{i}", f"fresh-worker-{i}", source="Changed") for i in range(2)]
    assert accept(ticket, fresh, "fresh-accepted")["status"] == "success"
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert ledger["attempts"][:4] == attempts
    assert len(ledger["attempts"]) == 6
    assert ledger["budget_limit"] == (6 if bounded else None)
    assert all(a["generation"] == 1 for a in ledger["attempts"][4:])
    assert cli("emit_wayfind_handoff", "demo")["status"] == "success"
    assert cli("validate_wayfind_handoff", "demo")["status"] == "success"


@pytest.mark.parametrize("condition", ["current", "empty", "stranger", "reserved", "unknown", "resolved", "correction", "revision", "reason"])
def test_open_research_refresh_rejects_without_mutation(condition: str) -> None:
    ticket = research_ticket()
    attempt = completed(ticket) if condition != "empty" else None
    if condition in {"resolved", "correction"}:
        assert attempt is not None
        assert accept(ticket, [attempt])["status"] == "success"
        if condition == "correction":
            assert cli("begin_research_correction", "demo", ticket, "owner", "Correct")["status"] == "success"
    if condition not in {"current", "empty"}:
        Path("answer.txt").write_text("Changed")
    if condition in {"reserved", "unknown"}:
        pending = reserve(ticket, "pending")["attempt_id"]
        if condition == "unknown":
            assert cli("record_research_attempt", "demo", ticket, "owner", pending, "unknown", "--reason", "No response")["status"] == "success"
    state_path = Path(".map/wayfind/demo/state.json")
    before = state_path.read_bytes()
    result = wr.refresh_open_research("demo", ticket, "stranger" if condition == "stranger" else "owner", " " if condition == "reason" else "Changed", expected_revision=-1 if condition == "revision" else None)
    assert result["status"] == "error", result
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("boundary", ["before_replace", "after_replace", "views"])
def test_open_research_refresh_restart_is_atomic_and_replay_cannot_advance(boundary: str) -> None:
    ticket = research_ticket()
    original = completed(ticket)
    Path("answer.txt").write_text("Changed")
    injection = {
        "before_replace": "wr.Path.replace = lambda self, target: (_ for _ in ()).throw(OSError('before replace'))",
        "after_replace": "original = wr.Path.replace\ndef replace(self, target):\n original(self, target)\n raise OSError('after replace')\nwr.Path.replace = replace",
        "views": "wr.refresh_open_research.__wrapped__.__globals__['_render_views'] = lambda state: (_ for _ in ()).throw(OSError('views'))",
    }[boundary]
    code = "import runpy, types\nwr=types.SimpleNamespace(**runpy.run_path(" + repr(str(SOURCE)) + "))\n" + injection + "\nwr.refresh_open_research('demo', '" + ticket + "', 'owner', 'Changed')\n"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    replay = cli("refresh_open_research", "demo", ticket, "owner", "Changed")
    assert replay["status"] == ("success" if boundary == "before_replace" else "error")
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert ledger["evidence_generation"] == 1
    assert len(ledger["evidence_refresh_history"]) == 1
    assert ledger["attempts"] == [original]
    assert ledger["budget_limit"] is None
    before = Path(".map/wayfind/demo/state.json").read_bytes()
    assert cli("refresh_open_research", "demo", ticket, "owner", "Changed again")["status"] == "error"
    assert Path(".map/wayfind/demo/state.json").read_bytes() == before


def test_open_research_refresh_revokes_acceptance_and_cannot_reuse_retired_generation() -> None:
    ticket = research_ticket()
    attempt = completed(ticket)
    old_path = assessment(ticket, [attempt], "old-accepted")
    assert cli("record_research_assessment", "demo", ticket, "owner", old_path)["status"] == "success"
    Path("answer.txt").write_text("Changed")
    assert cli("refresh_open_research", "demo", ticket, "owner", "Changed")["status"] == "success"
    Path("answer.txt").write_text("Present")
    before = Path(".map/wayfind/demo/state.json").read_bytes()
    assert cli("record_research_assessment", "demo", ticket, "owner", old_path)["status"] == "error"
    assert cli("resolve_ticket", "demo", ticket, "owner", "Present", f"research/{ticket}/old-accepted.resolution.md")["code"] == "research_assessment_required"
    assert Path(".map/wayfind/demo/state.json").read_bytes() == before
    ledger = cli("show_ticket", "demo", ticket)["ticket"]["research"]
    assert ledger["assessments"][0]["assessment_id"] == "old-accepted"
    assert ledger["evidence_refresh_history"][0]["prior_accepted_assessment_id"] == "old-accepted"
    assert ledger["accepted_assessment_id"] is None
    assert reserve(ticket, path=attempt["brief_path"])["attempt"] == attempt
    assert cli("research_context", "demo", ticket)["context"]["spent_attempts"] == 1
