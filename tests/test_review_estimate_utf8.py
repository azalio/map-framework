"""Admission estimate tracks UTF-8 bytes, stubbed added files and per-role/per-shard carried findings (#666)."""

import json
from pathlib import Path
from typing import Any

from tests.test_review_carried_findings import FILES, seed_carried
from tests.test_review_changed_scope import (
    read_resource,
    runner,
    shard_manifest,
    write_changes,
)
from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_roster_budget import required_bytes

repo = _base_repo
__all__ = ["repo"]

RUSSIAN_LINE = "Привет, мир! Это строка документации про SCIM и \"кавычки\" для проверки оценки.\n"


def write_russian(name="docs/scim.md", target_bytes=39_000):
    Path(name).parent.mkdir(parents=True, exist_ok=True)
    text = RUSSIAN_LINE * (target_bytes // len(RUSSIAN_LINE.encode("utf-8")) + 1)
    Path(name).write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def source_and_diff_bytes(entry):
    resources = shard_manifest(entry)["resources"]
    return sum(item["bytes"] for key, item in resources.items() if key.startswith("source_") or key == "diff")


def test_vc1_cyrillic_file_estimate_is_utf8_bytes_and_not_below_exact(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    size = write_russian()
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="ru", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    exact = source_and_diff_bytes(entry)
    estimate = runner._review_required_bytes(admitted["target"], ["docs/scim.md"])["docs/scim.md"]
    assert estimate >= exact, (estimate, exact)
    # Literal UTF-8, not 6-byte \uXXXX escapes: the estimate stays near the file size.
    assert estimate < size * 1.4 + 6000, (estimate, size)
    assert exact < size * 1.4 + 6000, (exact, size)


def test_vc1_source_resource_keeps_cyrillic_literal_and_frozen_digest_matches_stored_bytes(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    write_russian(target_bytes=2000)
    assert runner.begin_review_run(branch="feature", provider="claude", round_id="ru", base_ref="main")["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    directory = Path(".map/feature")
    manifest = shard_manifest(entry)
    sources = [item for key, item in manifest["resources"].items() if key.startswith("source_") and item["path"] == "docs/scim.md"]
    assert sources
    raw = runner._review_context_read(directory, sources[0])
    assert "Привет".encode() in raw and b"\\u041f" not in raw
    assert json.loads(raw)["current_content"].startswith("Привет")


def test_vc1_json_text_escapes_only_controls_and_line_breaks():
    text = "a\x0cb\x7fc\u0085d e f\"g\\h Привет\n"
    dumped = runner._review_json_text({"k": text})
    assert json.loads(dumped) == {"k": text}
    assert "Привет" in dumped
    assert not any(ord(char) < 0x20 or char in "\x7f\x85  " for char in dumped), repr(dumped)
    assert runner._review_json_size({"k": text}) == len(dumped.encode("utf-8"))
    # A lone surrogate cannot be UTF-8 encoded: fall back to escapes instead of failing.
    assert runner._review_json_text({"k": "\ud800"}).isascii()


def test_vc1_control_characters_in_a_source_stay_one_line_in_the_stored_resource(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    Path("notes.md").write_text("Привет\x0c мир\u0085!\n", encoding="utf-8")
    assert runner.begin_review_run(branch="feature", provider="claude", round_id="ctl", base_ref="main")["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    manifest = shard_manifest(entry)
    item = next(value for key, value in manifest["resources"].items() if key.startswith("source_") and value["path"] == "notes.md")
    text = runner._review_context_read(Path(".map/feature"), item).decode("utf-8")
    assert len(text.splitlines()) == 1, repr(text)
    assert json.loads(text)["current_content"] == "Привет\x0c мир\u0085!\n"


def test_vc2_added_file_estimate_does_not_count_a_full_diff_for_source_readers(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    Path("big_added.py").write_text("".join(f"value_{index} = {index}  # padding\n" for index in range(1500)))
    size = Path("big_added.py").stat().st_size
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="add", base_ref="main")
    assert admitted["status"] == "success", admitted
    estimate = runner._review_required_bytes(admitted["target"], ["big_added.py"])["big_added.py"]
    assert size < estimate < size * 1.5 + 3000, (estimate, size)
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    exact = source_and_diff_bytes(runner.build_review_prompts(branch="feature")["prompts"]["monitor"])
    assert estimate >= exact, (estimate, exact)


def test_vc2_diff_only_readers_keep_the_full_added_diff_in_the_estimate(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    Path("big_added.py").write_text("".join(f"value_{index} = {index}  # padding\n" for index in range(1500)))
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial",
                                      round_id="addadv", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_adversarial_review_prompts(branch="feature")
    assert built["status"] == "success", {k: v for k, v in built.items() if k != "prompts"}
    estimate = runner._review_required_bytes(admitted["target"], admitted["required_files"])
    blind_diff = len(read_resource(Path(".map/feature"), built["prompts"]["blind"], "diff").encode("utf-8"))
    assert sum(estimate.values()) >= blind_diff, (sum(estimate.values()), blind_diff)


def seed_wide_round(monkeypatch, count=120):
    write_changes()
    for index, name in enumerate(FILES):
        Path(name).parent.mkdir(exist_ok=True)
        Path(name).write_text("".join(f"line_{index}_{n} = {n}  # padding text here\n" for n in range(900)))
    return seed_carried(count)


def test_vc3_per_shard_overhead_is_below_the_global_worst_case_and_covers_exact(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 330_000))
    rows = seed_wide_round(monkeypatch)
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial",
                                      round_id="shard", base_ref="main")
    assert admitted["status"] == "success", {k: v for k, v in admitted.items() if k in ("reason", "hints", "overhead_breakdown")}
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    ledger = runner._read_review_ledger(Path(".map/feature"))
    row = ledger["convergence"]["rounds"][-1]
    shards = row.get("shards") or [{"id": "", "files": row["required_files"]}]
    assert len(shards) >= 2
    carried = [item for item in ledger["findings_registry"] if item["status"] in {"active", "downgraded"}]
    assert len(carried) == len(rows) >= 100
    sizes = runner._review_required_bytes(row["target"], row["required_files"])
    cmd: dict[str, Any] = {"target": row["target"], "provider": "claude", "scheduled_reviewers": row["binding"]["scheduled_reviewers"],
                              "branch_name": "feature", "required_paths": row["required_files"], "coverage_skips": [],
                              "check_specs": None, "carried_findings": carried}
    global_total = runner._review_fixed_overhead(**cmd)["total"]
    for shard in shards:
        built = runner.build_adversarial_review_prompts(branch="feature", shard=shard["id"])
        assert built["status"] == "success", (shard["id"], {k: v for k, v in built.items() if k != "prompts"})
        per_shard = runner._review_fixed_overhead(**cmd, shard_files=set(shard["files"]))
        assert per_shard["total"] < global_total, shard["id"]
        estimate = sum(sizes[name] for name in shard["files"]) + per_shard["total"]
        for role, entry in built["prompts"].items():
            assert estimate >= required_bytes(entry), (shard["id"], role, estimate, required_bytes(entry))


def test_vc3_admission_plans_against_per_shard_overhead_not_the_global_worst_case(repo, monkeypatch):
    del repo
    rows = seed_wide_round(monkeypatch)
    assert len(rows) >= 100
    target = runner._review_target({"base_ref": "main"})
    required = list(target["required_files"])
    carried = [item for item in runner._read_review_ledger(Path(".map/feature"))["findings_registry"]]
    roles = list(runner.ADVERSARIAL_REVIEWERS)
    cmd: dict[str, Any] = {"target": target, "provider": "claude", "scheduled_reviewers": roles, "branch_name": "feature",
                              "required_paths": required, "coverage_skips": [], "check_specs": None, "carried_findings": carried}
    global_total = runner._review_fixed_overhead(**cmd)["total"]
    sizes = runner._review_required_bytes(target, required)
    biggest = max(sizes.values())
    # Capacity (budget - global overhead) fits one file; the per-shard overhead lets files share a shard.
    budget = global_total + int(biggest * 1.5)
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(budget))
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial",
                                      round_id="plan", base_ref="main")
    assert admitted["status"] == "success", {k: v for k, v in admitted.items() if k in ("reason", "hints", "overhead_breakdown")}
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    for shard in row["shards"]:
        built = runner.build_adversarial_review_prompts(branch="feature", shard=shard["id"])
        assert built["status"] == "success", (shard["id"], {k: v for k, v in built.items() if k != "prompts"})
        for role, entry in built["prompts"].items():
            assert required_bytes(entry) <= budget, (shard["id"], role)
    global_plan = runner._review_plan_shards(sizes, budget - max(runner.REVIEW_CONTEXT_RESERVE_BYTES, global_total))
    assert len(row["shards"]) < len(global_plan), (len(row["shards"]), len(global_plan))


def test_vc4_file_too_large_reports_the_fixed_overhead_and_its_breakdown(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    write_changes()
    Path("huge.txt").write_text("".join(f"unique row {index} {index * 7919 % 10007}\n" for index in range(9000)))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="big", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded" and result["reason"] == "file_too_large", result
    assert isinstance(result["fixed_overhead"], int) and result["fixed_overhead"] > 0
    assert result["overhead_breakdown"]["role_prompt"] > 0 and "margin" in result["overhead_breakdown"]


def test_vc4_too_many_shards_reports_the_fixed_overhead_and_its_breakdown(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "2")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    write_changes()
    for index in range(8):
        Path(f"pkg_{index % 2}").mkdir(exist_ok=True)
        Path(f"pkg_{index % 2}/m_{index}.py").write_text("".join(f"value_{n} = {n}\n" for n in range(900)))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="many", base_ref="main")
    assert result["reason"] == "too_many_shards", result
    assert result["fixed_overhead"] > 0 and result["overhead_breakdown"]["role_prompt"] > 0
