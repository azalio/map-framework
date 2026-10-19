"""Explicit admission cannot be downgraded to the no-admission legacy override."""

from pathlib import Path

import pytest

from tests.test_review_explicit_base import admit, fresh, git
from tests.test_review_explicit_base import stack as stack  # noqa: PLC0414 -- expose pytest fixture


@pytest.fixture
def shadow_stack(stack, monkeypatch):
    git("checkout", "main")
    config = Path(".map/config.yaml")
    config.parent.mkdir(exist_ok=True)
    config.write_text("review:\n  security_gates: shadow\n")
    git("add", "-f", str(config))
    git("commit", "-m", "operator trusted shadow policy")
    git("checkout", "product")
    monkeypatch.setenv("MAP_REVIEW_LEDGER_ENFORCE", "0")
    return stack


@pytest.mark.parametrize("damage", [
    "missing-mode", "corrupt-mode", "corrupt-ledger", "corrupt-ledger-and-mode",
    "moved-target", "deleted-target", "policy-movement",
])
def test_explicit_admission_cannot_fall_back_to_legacy_override(shadow_stack, damage):
    del shadow_stack
    admitted = admit(base_ref="runtime")
    assert admitted["target"]["security_gate_policy"]["mode"] == "shadow"
    mode = Path(".map/product/review-mode.json")
    ledger = Path(".map/product/review-verdict-ledger.json")
    if damage == "missing-mode":
        mode.unlink()
    elif damage == "corrupt-mode":
        mode.write_text("{broken mode")
    elif damage in {"corrupt-ledger", "corrupt-ledger-and-mode"}:
        ledger.write_text("{broken ledger")
        if damage == "corrupt-ledger-and-mode":
            mode.write_text("{broken mode")
    elif damage == "deleted-target":
        git("branch", "-D", "runtime")
    elif damage == "moved-target":
        git("branch", "-f", "runtime", "HEAD")
    else:
        git("checkout", "main")
        Path("REVIEW.md").write_text("MAIN_POLICY: newly required validation.\n")
        git("commit", "-am", "operator updates review policy")
        git("checkout", "product")
    before = {p: p.read_bytes() for p in (mode, ledger) if p.exists()}
    result = fresh("write_stage_gate", stage="review", verdict="ready", branch="product")
    assert result["status"] == "error", result
    assert not Path(".map/product/review-gate.json").exists()
    assert {p: p.read_bytes() for p in (mode, ledger) if p.exists()} == before


@pytest.mark.parametrize("corrupt_ledger", [False, True])
def test_trusted_shadow_without_admission_retains_legacy_override(shadow_stack, corrupt_ledger):
    del shadow_stack
    directory = Path(".map/product")
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / "review-verdict-ledger.json"
    if corrupt_ledger:
        ledger.write_text("{broken legacy ledger")
    assert not (directory / "review-mode.json").exists()
    result = fresh("write_stage_gate", stage="review", verdict="ready", branch="product")
    assert result["status"] == "success", result
    assert (directory / "review-gate.json").is_file()
    if corrupt_ledger:
        assert ledger.read_text() == "{broken legacy ledger"
