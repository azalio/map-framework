"""Focused independent review coverage supplementing frozen #555 gate proofs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_acceptance_additive_revision import _cli, _revise
from tests.test_acceptance_additive_revision import (
    frozen_workspace as _frozen_workspace,
)

gate_workspace = _frozen_workspace


def test_timeout_increase_does_not_weaken_additive_proof(gate_workspace: dict[str, Any]) -> None:
    revised = _revise(gate_workspace, timeout=60)
    assert revised["status"] == "success", revised
    assert _cli("verify_acceptance_contracts")["allowed"] is True


@pytest.mark.parametrize("path", ["test_original.py", "auxiliary.txt", "test_added.py"])
def test_live_changed_proof_blocks_verify_and_handoff(gate_workspace: dict[str, Any], path: str) -> None:
    revised = _revise(gate_workspace)
    assert revised["status"] == "success", revised
    assert _cli("verify_acceptance_contracts")["allowed"] is True
    Path(path).write_text(Path(path).read_text() + "# changed after revision\n")
    assert _cli("verify_acceptance_contracts")["allowed"] is False
    Path(".map/main/test_contract_ST-001.md").write_text("Independent proof handoff\n")
    handoff = _cli("record_test_contract_handoff", subtask_id="ST-001",
                   test_files_csv="test_original.py,test_added.py", authoring_result="red")
    assert handoff.get("allowed") is False or handoff.get("status") == "error", handoff
    assert not Path(".map/main/test_handoff_ST-001.json").exists()


@pytest.mark.parametrize("target", ["other/test_added.py", "other/test_original.py", "test_added.py::test_added"])
def test_new_target_cannot_expand_discovery_or_select_nodes(gate_workspace: dict[str, Any], target: str) -> None:
    file_path = target.split("::", 1)[0]
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    if file_path.startswith("other/"):
        Path(file_path).write_text("def test_new():\n    assert True\n")
    revised = _revise(gate_workspace, command=[*gate_workspace["command"], target],
                      proof_files=["test_original.py", "auxiliary.txt", file_path])
    if revised.get("status") == "success":
        assert _cli("verify_acceptance_contracts")["allowed"] is False, revised
    else:
        assert revised.get("status") == "error", revised


@pytest.mark.parametrize("entrypoint", ["revision", "assessment"])
@pytest.mark.parametrize("corruption", ["missing", "inconsistent"])
def test_persisted_additive_proof_evidence_is_revalidated(
    gate_workspace: dict[str, Any], corruption: str, entrypoint: str,
) -> None:
    revised = _revise(gate_workspace, assessment="unknown" if entrypoint == "assessment" else "additive")
    assert revised["status"] == "success", revised
    if entrypoint == "assessment":
        assessed = _cli("assess_acceptance_revision", ac_id="AC-1", revision=2,
                        author="independent-reviewer", assessment="additive", reason="Check strict superset")
        assert assessed["status"] == "success", assessed
    assert _cli("verify_acceptance_contracts")["allowed"] is True
    # External persisted-store corruption is the tested boundary, as in existing acceptance tests.
    store_path = Path(".map/main/acceptance-proofs.json")
    store = json.loads(store_path.read_text())
    revision = store["revisions"][-1]
    if entrypoint == "assessment":
        revision = revision["assessments"][-1]
    assert "additive_evidence" in revision
    if corruption == "missing":
        revision.pop("additive_evidence")
    else:
        revision["additive_evidence"] = {"status": "unverified-corrupt-evidence"}
    store["integrity"] = hashlib.sha256(json.dumps(
        {key: value for key, value in store.items() if key != "integrity"}, sort_keys=True,
    ).encode()).hexdigest()
    store_path.write_text(json.dumps(store))
    assert _cli("verify_acceptance_contracts")["allowed"] is False
    assert _cli("evaluate_acceptance")["allowed"] is False
