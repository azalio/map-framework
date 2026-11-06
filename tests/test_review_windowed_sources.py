"""Large changed files are delivered as hunk-bounded windows with lazy full content (#642)."""

import json
from pathlib import Path

import pytest

from tests.test_review_changed_scope import (
    commit_base_and_branch,
    git,
    read_resource,
    runner,
    shard_manifest,
)
from tests.test_review_changed_scope import repo as _base_repo

repo = _base_repo
__all__ = ["repo"]  # pytest discovers the fixture by module attribute; exporting marks it as used

BIG = ".sourcecraft/ci.yaml"


def big_lines(count=6000):
    return [f"  step_{index:05d}: run the pipeline stage number {index} with some padding\n" for index in range(count)]


def seed_big(edit, path=BIG, count=6000, config=""):
    lines = big_lines(count)
    if config:
        Path(".map").mkdir(exist_ok=True)
        Path(".map/config.yaml").write_text(config)
        git("add", "-f", ".map/config.yaml")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(lines))
    commit_base_and_branch()
    Path(path).write_text("".join(edit(list(lines))))
    return "".join(lines)


def sparse_edit(lines):
    for start in (100, 1100, 2100, 4100, 5100):
        for index in range(start, start + 8):
            lines[index] = f"  step_{index:05d}: CHANGED\n"
    lines.insert(3000, "".join(f"  added_{index}: new\n" for index in range(7)))
    return lines


def source_resource(entry, path):
    manifest = shard_manifest(entry)
    return next(item for item in manifest["resources"].values() if item.get("path") == path)


def admit_and_build(round_id="w"):
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id=round_id, base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", built
    return admitted, built["prompts"]["monitor"]


def test_vc1_large_file_with_small_change_admits_with_a_windowed_required_resource(repo):
    del repo
    base = seed_big(sparse_edit)
    assert len(base) > 300_000
    admitted, entry = admit_and_build()
    assert "shard_ids" not in admitted
    meta = source_resource(entry, BIG)
    assert meta["required"] is True and meta["windowed"] is True
    payload = json.loads(read_resource(Path(".map/feature"), entry, next(
        key for key, item in shard_manifest(entry)["resources"].items() if item is meta or item == meta)))
    assert payload["windowed"] is True and "full" in payload["window_note"].lower()
    text = json.dumps(payload["hunks"])
    assert "step_00100: CHANGED" in text and "added_6" in text
    assert "step_05900" not in text
    assert meta["bytes"] < 120_000


def test_vc2_full_base_and_current_are_lazy_frozen_and_complete(repo):
    del repo
    base = seed_big(sparse_edit)
    current = Path(BIG).read_text()
    _, entry = admit_and_build()
    context_id = entry["context_transport"]["context_id"]
    for side, expected in (("base", base), ("current", current)):
        chunks, offset = [], 0
        while True:
            request = {"type": "context_request", "context_id": context_id,
                       "resource_id": f"{side}:{BIG}", "offset": offset}
            served = runner.serve_review_context("monitor", json.dumps(request), "w", branch="feature")
            assert served["status"] == "context_response", served
            chunks.append(served["content"])
            if served["eof"]:
                break
            offset = served["next_offset"]
        assert json.loads("".join(chunks))["content"] == expected
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert row["context_lazy"][f"base:{BIG}"]["required"] is False
    assert f"repo:{BIG}" not in row["context_lazy"]
    # A path that was not windowed is not available through the full-source namespace.
    request = {"type": "context_request", "context_id": context_id, "resource_id": "base:first.py", "offset": 0}
    assert runner.serve_review_context("monitor", json.dumps(request), "w", branch="feature")["status"] == "error"


def test_vc3_full_source_is_refused_after_the_working_tree_changes(repo):
    del repo
    seed_big(sparse_edit)
    _, entry = admit_and_build()
    Path(BIG).write_text("changed after admission\n")
    request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
               "resource_id": f"current:{BIG}", "offset": 0}
    assert runner.serve_review_context("monitor", json.dumps(request), "w", branch="feature")["status"] == "error"


def test_vc4_small_files_keep_full_content(repo):
    del repo
    seed_big(sparse_edit)
    Path("first.py").write_text("value = 2\n")
    _, entry = admit_and_build()
    meta = source_resource(entry, "first.py")
    assert not meta.get("windowed")
    payload = json.loads(read_resource(Path(".map/feature"), entry, next(
        key for key, item in shard_manifest(entry)["resources"].items() if item.get("path") == "first.py")))
    assert payload["base_content"] == "value = 1\n" and payload["current_content"] == "value = 2\n"
    assert "hunks" not in payload


def dense_edit(lines):
    return [f"  step_{index:05d}: DENSE\n" if index % 3 == 0 else line for index, line in enumerate(lines)]


def cyrillic_edit(lines):
    for index in range(50, 5900, 97):
        lines[index] = f"  шаг_{index}: Привет, мир! \"кавычки\"\n"
    return lines


def append_edit(lines):
    return lines + [f"  tail_{index}: x\n" for index in range(200)]


def delete_edit(lines):
    return lines[:2000] + lines[2100:]


@pytest.mark.parametrize("edit", [sparse_edit, dense_edit, cyrillic_edit, append_edit, delete_edit])
def test_vc5_estimate_is_never_below_the_exact_windowed_bytes(repo, monkeypatch, edit):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "100000000")
    seed_big(edit)
    admitted, entry = admit_and_build("est")
    resources = shard_manifest(entry)["resources"]
    exact = sum(item["bytes"] for key, item in resources.items() if key.startswith("source_") or key == "diff")
    estimate = sum(runner._review_required_bytes(admitted["target"], admitted["required_files"]).values())
    assert estimate >= exact, (edit.__name__, estimate, exact)


def test_vc6_estimate_of_the_reported_shape_fits_the_default_budget(repo):
    del repo
    seed_big(sparse_edit)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="est", base_ref="main")
    assert admitted["status"] == "success", admitted
    estimate = sum(runner._review_required_bytes(admitted["target"], admitted["required_files"]).values())
    assert estimate < runner.REVIEW_CONTEXT_BUDGET_BYTES // 2


def test_vc7_window_size_and_threshold_come_from_trusted_config(repo):
    del repo
    seed_big(sparse_edit, config="review:\n  full_source_max_bytes: 1000000\n  context_budget_bytes: 5000000\n")
    _, entry = admit_and_build("cfg")
    assert not source_resource(entry, BIG).get("windowed")


def test_vc8_hunk_context_lines_bounds_the_window(repo):
    del repo
    seed_big(lambda lines: [*lines[:3000], "  only_change: 1\n", *lines[3001:]],
             config="review:\n  hunk_context_lines: 2\n")
    _, entry = admit_and_build("ctx")
    key = next(key for key, item in shard_manifest(entry)["resources"].items() if item.get("path") == BIG)
    payload = json.loads(read_resource(Path(".map/feature"), entry, key))
    assert len(payload["hunks"]) == 1
    hunk = payload["hunks"][0]
    assert "step_02998" in hunk["base"] and "step_02997" not in hunk["base"]
    assert "step_03003" not in hunk["current"]
    assert "3001: " in hunk["current"] and "only_change" in hunk["current"]


def test_vc9_pathological_hunks_still_fail_fast_with_a_split_hint(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    seed_big(lambda lines: [f"  rewritten_{index}: everything differs here\n" for index in range(len(lines))])
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="big", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded" and result["reason"] == "file_too_large"
    assert any("single file" in hint.lower() and "hunks" in hint.lower() for hint in result["hints"])


def test_vc10_codex_pack_sources_carries_the_windowed_entry(repo):
    del repo
    seed_big(sparse_edit)
    admitted = runner.begin_review_run(branch="feature", provider="codex", round_id="w", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature", pack_sources=True)
    assert built["status"] == "success", built
    entry = built["prompts"]["monitor"]
    manifest = shard_manifest(entry)
    pack = json.loads(read_resource(Path(".map/feature"), entry, "source_pack"))
    big = next(item for item in pack["files"] if item["path"] == BIG)
    assert big["windowed"] is True and "base_content" not in big
    assert manifest["resources"]["source_pack"]["required"] is True


def test_vc11_blind_diff_only_reviewers_cannot_fetch_full_sources(repo):
    del repo
    seed_big(sparse_edit)
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial --quick",
                                      round_id="w", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_adversarial_review_prompts(branch="feature", reviewers=["blind"])
    assert built["status"] == "success", built
    entry = built["prompts"]["blind"]
    request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
               "resource_id": f"current:{BIG}", "offset": 0}
    assert runner.serve_review_context("blind", json.dumps(request), "w", branch="feature")["status"] == "error"


def many_files(count=30, lines=900):
    for index in range(count):
        directory = Path(f"pkg_{index % 3}")
        directory.mkdir(exist_ok=True)
        (directory / f"module_{index:02d}.py").write_text("".join(f"value_{n} = {n}\n" for n in range(lines)))


def test_vc12_max_shards_env_overrides_default(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    many_files()
    failed = runner.begin_review_run(branch="feature", provider="claude", round_id="m", base_ref="main")
    assert failed["reason"] == "too_many_shards" and failed["max_shards"] == runner.REVIEW_MAX_SHARDS
    needed = failed["shards_needed"]
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "1")
    capped = runner.begin_review_run(branch="feature", provider="claude", round_id="m", base_ref="main")
    assert capped["reason"] == "too_many_shards" and capped["max_shards"] == 1
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", str(needed))
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="m", base_ref="main")
    assert admitted["status"] == "success" and len(admitted["shard_ids"]) == needed, admitted


@pytest.mark.parametrize("bad", ["0", "-3", "many", ""])
def test_vc13_invalid_max_shards_env_is_ignored(monkeypatch, bad):
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", bad)
    assert runner._review_max_shards({}) == runner.REVIEW_MAX_SHARDS
    assert runner._review_max_shards({"max_shards": 3}) == 3


def test_vc13_env_wins_over_trusted_config(monkeypatch):
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "12")
    assert runner._review_max_shards({"max_shards": 3}) == 12


def test_vc14_too_many_shards_hint_names_the_needed_count_and_env(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    many_files()
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="h", base_ref="main")
    assert result["reason"] == "too_many_shards", result
    hint = " ".join(result["hints"])
    assert "MAP_REVIEW_MAX_SHARDS" in hint and str(result["shards_needed"]) in hint
