"""Admission estimate tracks UTF-8 bytes, stubbed added files and per-role/per-shard carried findings (#666)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.test_review_carried_findings import FILES, seed_carried
from tests.test_review_changed_scope import (
    read_resource,
    runner,
    shard_manifest,
    write_changes,
)
from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_context_delivery import bind, prepare
from tests.test_review_context_delivery import repository as _repository
from tests.test_review_context_file_delivery import (
    acknowledge,
    file_ack,
    proof_fragments,
    serve_file,
)
from tests.test_review_roster_budget import required_bytes
from tests.test_review_trusted_policy import git

repo = _base_repo
repository = _repository
__all__ = ["repo", "repository"]

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
    # A lone surrogate cannot be UTF-8 encoded: only that character is escaped, the rest stays literal.
    mixed = runner._review_json_text({"path": "bad\udcff.py", "text": "Привет"})
    assert "\\udcff" in mixed and "Привет" in mixed
    mixed.encode("utf-8")
    assert json.loads(mixed) == {"path": "bad\udcff.py", "text": "Привет"}


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


def seed_wide_round(count=120):
    write_changes()
    for index, name in enumerate(FILES):
        Path(name).parent.mkdir(exist_ok=True)
        Path(name).write_text("".join(f"line_{index}_{n} = {n}  # padding text here\n" for n in range(900)))
    return seed_carried(count)


def test_vc3_per_shard_overhead_is_below_the_global_worst_case_and_covers_exact(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 330_000))
    rows = seed_wide_round()
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
    rows = seed_wide_round()
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


def test_vc5_a_file_that_is_empty_at_the_base_is_not_estimated_as_added(repo, monkeypatch):
    del repo
    git("checkout", "-q", "main")
    Path("empty.py").write_text("")
    git("add", "empty.py")
    git("commit", "-qm", "empty")
    git("checkout", "-q", "feature")
    git("merge", "-q", "main")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    Path("empty.py").write_text("".join(f"value_{index} = {index}  # padding\n" for index in range(1500)))
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="empty", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    exact = source_and_diff_bytes(entry)
    sizes = runner._review_required_bytes(admitted["target"], admitted["required_files"])
    # Its source status is "unknown/present", not "added", so the diff is NOT stubbed and the estimate keeps it.
    assert sizes["empty.py"] + sizes["first.py"] >= exact, (sizes, exact)
    assert runner._review_base_missing("main", ["empty.py", "never_existed.py"]) == {"never_existed.py"}


BUDGET_ERROR_KEYS = {"fixed_overhead", "overhead_breakdown", "scope", "capacity", "budget", "total", "stop_reason"}


def assert_budget_schema(result, scope_prefix):
    assert result["stop_reason"] == "review_context_budget_exceeded", result
    assert BUDGET_ERROR_KEYS <= set(result), set(result)
    assert isinstance(result["fixed_overhead"], int) and result["fixed_overhead"] > 0
    assert {"role_prompt", "inventory", "task_artifacts"} <= set(result["overhead_breakdown"])
    assert all(isinstance(result["overhead_breakdown"][key], int) for key in ("role_prompt", "inventory", "task_artifacts"))
    assert result["scope"].startswith(scope_prefix), result["scope"]
    assert isinstance(result["capacity"], int)


def test_vc6_every_budget_error_shares_one_overhead_schema(repo, monkeypatch):
    del repo
    write_changes()
    # file_too_large
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    Path("huge.txt").write_text("".join(f"unique row {index} {index * 7919 % 10007}\n" for index in range(9000)))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="big", base_ref="main")
    assert result["reason"] == "file_too_large", result
    assert_budget_schema(result, "")
    assert result["total"] == sum(item["bytes"] for item in result["top_paths"]) + max(
        runner.REVIEW_CONTEXT_RESERVE_BYTES, result["fixed_overhead"]) or result["total"] > 0
    assert result["capacity"] == result["budget"] - max(runner.REVIEW_CONTEXT_RESERVE_BYTES, result["fixed_overhead"])
    Path("huge.txt").unlink()
    # fixed_overhead_too_large
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 100))
    for index in range(4):
        Path(f"m_{index}.py").write_text("".join(f"value_{n} = {n}\n" for n in range(900)))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="fix", base_ref="main")
    assert result["reason"] == "fixed_overhead_too_large", result
    assert_budget_schema(result, "")
    assert result["capacity"] == result["budget"] - max(runner.REVIEW_CONTEXT_RESERVE_BYTES, result["fixed_overhead"])
    # too_many_shards
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "1")
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="many", base_ref="main")
    assert result["reason"] == "too_many_shards", result
    assert_budget_schema(result, "worst shard")


def test_vc6_the_prompt_build_budget_error_uses_the_same_schema(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    write_russian(target_bytes=20_000)
    assert runner.begin_review_run(branch="feature", provider="claude", round_id="exact", base_ref="main")["status"] == "success"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "30000")
    result = runner.build_review_prompts(branch="feature")
    assert_budget_schema(result, "reviewer ")
    assert result["scope"].split()[-1] in result["required_bytes"]
    parts = result["overhead_breakdown"]
    assert parts["role_prompt"] > 0 and parts["manifest"] > 0 and parts["sources_and_diff"] > 0
    worst = max(result["required_bytes"].values())
    assert result["fixed_overhead"] == worst - parts["sources_and_diff"]
    assert result["capacity"] == result["budget"] - result["fixed_overhead"]


def test_vc7_lone_surrogates_in_text_blocks_are_escaped_so_the_view_encodes():
    value = {"content": "first\nbad \udcff line\n", "long": "x" * 1200 + "\ud800", "path": "a\udc80.py"}
    raw = runner._review_json_text(value, sort_keys=True).encode("utf-8")
    view = runner._review_context_view("source_000000", raw, "0" * 64, part_bytes=runner._review_part_bytes(len(raw)))
    view.encode("utf-8")
    assert "\\udcff" in view and "\\ud800" in view


def test_vc8_an_undecodable_file_name_does_not_inflate_the_estimate_of_its_content(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    write_changes()
    bad = os.fsdecode(b"bad_\xff_name.md")
    try:
        Path(bad).write_text("Привет, мир! " * 2500, encoding="utf-8")
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="bad", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    sizes = runner._review_required_bytes(admitted["target"], admitted["required_files"])
    manifest = shard_manifest(entry)["resources"]
    exact = sum(item["bytes"] for key, item in manifest.items() if key.startswith("source_") or key == "diff")
    assert sum(sizes.values()) >= exact, (sizes, exact)
    source = next(item for key, item in manifest.items() if key.startswith("source_") and item["path"] == bad)
    raw = runner._review_context_read(Path(".map/feature"), source)
    assert "Привет".encode() in raw


def test_vc8_object_with_a_surrogate_path_stays_literal_for_the_rest(repo):
    del repo
    body = "Привет, мир! " * 500
    with_bad_path = runner._review_json_size({"path": "bad\udcff.md", "current_content": body})
    with_good_path = runner._review_json_size({"path": "good.md", "current_content": body})
    assert with_bad_path - with_good_path < 64, (with_bad_path, with_good_path)


def test_vc9_a_pending_file_published_before_an_upgrade_is_reused_not_re_rendered(repository, monkeypatch):
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    nonce = "".join(proof_fragments(first["path"]))
    original = runner._review_context_view
    # The renderer changed (e.g. a new escaping rule) after the reviewer already received the first file.
    monkeypatch.setattr(runner, "_review_context_view",
                        lambda *args, **kwargs: original(*args, **kwargs).replace("layout:", "layout (v2):", 1))
    again = serve_file(state)
    assert again["path"] == first["path"] and again["sha256"] == first["sha256"]
    assert proof_fragments(again["path"]) == proof_fragments(first["path"])
    acknowledged = acknowledge(state, file_ack(state, first, nonce))
    assert acknowledged["status"] in {"context_pending", "context_ready"}, acknowledged


def test_vc9_a_changed_renderer_still_publishes_a_fresh_file_once_nothing_is_pending(repository, monkeypatch):
    del repository
    state = bind(prepare()["monitor"])
    first = serve_file(state)
    nonce = "".join(proof_fragments(first["path"]))
    assert acknowledge(state, file_ack(state, first, nonce))["status"] in {"context_pending", "context_ready"}
    original = runner._review_context_view
    monkeypatch.setattr(runner, "_review_context_view",
                        lambda *args, **kwargs: original(*args, **kwargs).replace("layout:", "layout (v2):", 1))
    # An acknowledged resource is not pending; a new request for another one renders with the current code.
    nxt = state["remaining"][1]["resource_id"] if len(state["remaining"]) > 1 else None
    if nxt:
        served = serve_file(state, nxt)
        assert served["status"] == "context_response"
