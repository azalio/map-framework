"""Fixed per-reviewer prompt overhead stays small on a realistic branch: checks, policy and risk (#642)."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.test_review_changed_scope import (
    read_resource,
    runner,
    shard_manifest,
    trust_on_main,
    write_changes,
)
from tests.test_review_changed_scope import repo as _base_repo

repo = _base_repo
__all__ = ["repo"]

POLICY_SENTENCE = "Всегда проверяйте обратную совместимость публичных интерфейсов."
CHECK_IDS = ("lint", "unit", "types", "integration")
SHARD = ""


def realistic_policy(size=9000):
    body = (POLICY_SENTENCE + " ") * 1
    filler = "Правило ревью: каждое изменение должно сопровождаться тестом и описанием рисков. "
    return "# REVIEW\n\n" + body + "\n" + filler * (size // len(filler.encode("utf-8")) + 1)


def admit_with_checks(monkeypatch, provider="claude", arguments=""):
    trust_on_main({"REVIEW.md": realistic_policy()})
    write_changes(*(f"auth/module_{index}.py" for index in range(25)))
    specs = {check_id: ["make", check_id] for check_id in CHECK_IDS}
    admitted = runner.begin_review_run(branch="feature", provider=provider, arguments=arguments, round_id="oh",
                                      base_ref="main", check_specs=specs, required_checks=list(CHECK_IDS))
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    directory = Path(".map/feature")
    ledger = runner._read_review_ledger(directory)
    row = ledger["convergence"]["rounds"][-1]
    checks = {}
    for check_id in CHECK_IDS:
        log = "".join(f"{check_id} output line {index} with a long diagnostic message\n" for index in range(450))
        (directory / f"check-{check_id}.txt").write_text(log)
        checks[check_id] = {"state": "finished", "passed": True, "exit_code": 0, "duration_seconds": 12.5,
                            "command": ["make", check_id], "before": row["target"], "after": row["target"],
                            "policy_hash": row["policy_hash"], "output_artifact": f"check-{check_id}.txt",
                            "output_sha256": hashlib.sha256(log.encode()).hexdigest()}
    ledger["execution_checks"] = checks
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    monkeypatch.setattr(runner, "_review_check_valid", lambda *_args: True)
    return admitted


def prompt_text(entry):
    return read_resource(Path(".map/feature"), entry, "prompt")


def resource_text(entry, name):
    return read_resource(Path(".map/feature"), entry, name)


def test_vc18_role_and_core_prompts_stay_small_with_four_checks_and_a_cyrillic_policy(repo, monkeypatch):
    del repo
    admit_with_checks(monkeypatch)
    prompts = runner.build_review_prompts(branch="feature", shard=SHARD)["prompts"]
    sizes = {role: len(prompt_text(entry).encode("utf-8")) for role, entry in prompts.items()}
    assert max(sizes.values()) < 75_000, sizes


def test_vc19_checks_are_one_compact_line_with_a_pointer_to_the_full_log(repo, monkeypatch):
    del repo
    admit_with_checks(monkeypatch)
    entry = runner.build_review_prompts(branch="feature", shard=SHARD)["prompts"]["monitor"]
    text = prompt_text(entry)
    for check_id in CHECK_IDS:
        assert f"check:{check_id}" in text
        assert f"{check_id} output line 0 with" not in text and f"{check_id} output line 449 with" not in text
    assert '"before"' not in text and '"after"' not in text
    # The full log stays retrievable through the lazy namespace.
    request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
               "resource_id": "check:lint", "offset": 0}
    served = runner.serve_review_context("monitor", json.dumps(request), "oh", branch="feature")
    assert served["status"] == "context_response" and "lint output line 0 with" in served["content"]


def test_vc20_policy_text_is_utf8_and_appears_once_per_prompt_and_not_in_the_inventory(repo, monkeypatch):
    del repo
    admit_with_checks(monkeypatch)
    prompts = runner.build_review_prompts(branch="feature", shard=SHARD)["prompts"]
    for role, entry in prompts.items():
        text = prompt_text(entry)
        assert text.count(POLICY_SENTENCE) == 1, (role, text.count(POLICY_SENTENCE))
        assert "\\u04" not in text, role
        inventory = resource_text(entry, "inventory")
        assert POLICY_SENTENCE not in inventory and "\\u04" not in inventory, role
        assert len(inventory.encode("utf-8")) < 40_000, role


def test_vc21_shadow_risk_detail_is_summarised_but_keeps_tier_and_count(repo, monkeypatch):
    del repo
    admit_with_checks(monkeypatch)
    entry = runner.build_review_prompts(branch="feature", shard=SHARD)["prompts"]["maintainer"]
    text = prompt_text(entry)
    assert '"tier": "sensitive"' in text and '"reasons_count"' in text
    assert text.count("Sensitive review/control path") <= 5


def test_vc22_blind_reviewer_still_receives_the_policy_text_once(repo, monkeypatch):
    del repo
    admit_with_checks(monkeypatch, arguments="--adversarial --quick")
    built = runner.build_adversarial_review_prompts(branch="feature", reviewers=["blind", "acceptance", "maintainer"], shard=SHARD)
    assert built["status"] == "success", built
    for role in ("blind", "acceptance", "maintainer"):
        text = prompt_text(built["prompts"][role])
        assert text.count(POLICY_SENTENCE) == 1, (role, text.count(POLICY_SENTENCE))


@pytest.mark.parametrize("arguments", ["", "--adversarial --quick"])
def test_vc23_measured_overhead_covers_the_exact_non_source_bytes(repo, monkeypatch, arguments):
    del repo
    admitted = admit_with_checks(monkeypatch, arguments=arguments)
    if arguments:
        built = runner.build_adversarial_review_prompts(branch="feature", reviewers=admitted["scheduled_reviewers"], shard=SHARD)
    else:
        built = runner.build_review_prompts(branch="feature", shard=SHARD)
    assert built["status"] == "success", built
    exact = 0
    for entry in built["prompts"].values():
        resources = shard_manifest(entry)["resources"]
        exact = max(exact, sum(item["bytes"] for key, item in resources.items()
                               if item.get("required", True) and not key.startswith("source_") and key != "diff"))
    target = admitted["target"]
    estimate = runner._review_fixed_overhead_bytes(
        target, "claude", admitted["scheduled_reviewers"], "feature", admitted["required_files"], [],
        {check_id: ["make", check_id] for check_id in CHECK_IDS})
    assert estimate >= exact, (estimate, exact)
    assert estimate < 120_000, estimate
