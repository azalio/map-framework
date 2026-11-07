"""Carried findings are delivered compactly, per shard, with full rows as a lazy resource (#664)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.review_context_helpers import fetch_review_resource, original_review_prompt
from tests.test_review_changed_scope import (
    read_resource,
    runner,
    shard_budget,
    shard_manifest,
    write_changes,
    write_many,
)
from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_roster_budget import required_bytes

repo = _base_repo
__all__ = ["repo"]

FINDING_COUNT = 132
SAFE_LINE_CHARS = 2000
BULK = "evidence bulk that only the full ledger row carries. " * 60
FILES = [f"pkg_{'abc'[index % 3]}/module_{index:02d}.py" for index in range(6)]


def seed_carried(count: int = FINDING_COUNT, files: list[str] | None = None) -> list[dict[str, Any]]:
    """Round-1 ledger: ``count`` active findings spread over ``files`` plus two findings without a file."""
    targets = files or FILES
    directory = Path(".map/feature")
    directory.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, Any] = runner._read_review_ledger(directory) or {"schema_version": "review_verdict_ledger.v1"}
    rows: list[dict[str, Any]] = []
    for index in range(count):
        rows.append({
            "id": f"RVF-{index:03d}", "status": "active", "severity": "important",
            "source_agent": "role", "originating_reviewer": "maintainer",
            "claim": f"Carried claim number {index}. " + "It must be rechecked. " * 40,
            "affected_files": [targets[index % len(targets)]] if index < count - 2 else [],
            "line_range": "10-12", "bug_class": "logic", "cause": "c" * 80, "failure_scenario": "f" * 80,
            "evidence": [{"source": "evidence", "quote": BULK}],
            "validation": {"notes": BULK}, "reachability": {"status": "reachable", "reason": BULK}})
    ledger["findings_registry"] = rows
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    return rows


@pytest.fixture
def carried_shards(repo, monkeypatch):
    """A sharded adversarial round admitted on top of 132 carried findings."""
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", shard_budget(260_000))
    write_changes()
    write_many(6)
    rows = seed_carried()
    admitted = runner.begin_review_run(branch="feature", provider="claude", arguments="--adversarial",
                                      round_id="carry", base_ref="main")
    assert admitted["status"] == "success", {k: v for k, v in admitted.items() if k in ("reason", "hints", "overhead_breakdown")}
    assert len(admitted.get("shard_ids", [])) >= 2, admitted.get("shard_ids")
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    return admitted, row, rows


def build_shard(shard_id):
    built = runner.build_adversarial_review_prompts(branch="feature", shard=shard_id)
    assert built["status"] == "success", {k: v for k, v in built.items() if k != "prompts"}
    return built


def max_line(text):
    return max((len(line) for line in text.split("\n")), default=0)


def test_vc1_per_reviewer_context_is_bounded_and_every_line_is_short(carried_shards):
    _, row, rows = carried_shards
    full_rows = len(json.dumps(rows, ensure_ascii=True))
    assert full_rows > 600_000
    directory = Path(".map/feature")
    for shard in row["shards"]:
        built = build_shard(shard["id"])
        for reviewer, entry in built["prompts"].items():
            resources = shard_manifest(entry)["resources"]
            assert resources["diff"]["bytes"] < 150_000, (reviewer, shard["id"], resources["diff"]["bytes"])
            assert required_bytes(entry) < 400_000, (reviewer, shard["id"])
            assert len(entry["prompt"]) < 150_000
            for name in ("prompt", "diff"):
                raw = runner._review_context_read(directory, resources[name])
                view = runner._review_context_view(name, raw, resources[name]["sha256"],
                                                   part_bytes=runner._review_part_bytes(len(raw)))
                assert max_line(raw.decode()) <= SAFE_LINE_CHARS, (reviewer, name, max_line(raw.decode()))
                assert max_line(view) <= SAFE_LINE_CHARS, (reviewer, name, "view")


def test_vc2_each_shard_receives_only_the_findings_of_its_files(carried_shards):
    _, row, rows = carried_shards
    directory = Path(".map/feature")
    by_file = {}
    for finding in rows:
        for name in finding["affected_files"]:
            by_file.setdefault(name, set()).add(finding["id"])
    fileless = {finding["id"] for finding in rows if not finding["affected_files"]}
    assert fileless and by_file
    for shard in row["shards"]:
        entry = build_shard(shard["id"])["prompts"]["blind"]
        diff = read_resource(directory, entry, "diff")
        own = set().union(*(by_file.get(name, set()) for name in shard["files"]))
        others = set().union(*by_file.values()) - own
        assert own and others
        assert all(f'"{identifier}"' in diff for identifier in own), shard["id"]
        assert not any(f'"{identifier}"' in diff for identifier in others), shard["id"]
        assert all(f'"{identifier}"' in diff for identifier in fileless)
        assert BULK[:40] not in diff
        assert "finding:<id>" in diff


def test_vc3_full_rows_are_a_lazy_frozen_resource(carried_shards):
    _, row, rows = carried_shards
    shard = row["shards"][0]
    target = next(finding for finding in rows if set(finding["affected_files"]) & set(shard["files"]))
    built = build_shard(shard["id"])
    maintainer = built["prompts"]["maintainer"]
    text = fetch_review_resource(runner, maintainer, "maintainer", f"finding:{target['id']}", branch="feature")
    assert json.loads(text)["evidence"] == target["evidence"]
    ledger_row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert ledger_row["context_lazy"][f"finding:{target['id']}"]["kind"] == "finding"
    with pytest.raises(AssertionError):
        fetch_review_resource(runner, maintainer, "maintainer", "finding:RVF-9999", branch="feature")
    # A blind (diff-only) reviewer did not originate the finding and cannot fetch its evidence.
    blind = built["prompts"]["blind"]
    with pytest.raises(AssertionError):
        fetch_review_resource(runner, blind, "blind", f"finding:{target['id']}", branch="feature")


def test_vc4_the_originating_reviewer_sees_and_can_resolve_its_findings(carried_shards):
    _, row, rows = carried_shards
    for shard in row["shards"]:
        entry = build_shard(shard["id"])["prompts"]["maintainer"]
        prompt = original_review_prompt(runner, entry, "maintainer", branch="feature")
        mine = [finding for finding in rows if set(finding["affected_files"]) & set(shard["files"])]
        assert mine
        section = prompt.split("<carried_findings_for_this_reviewer>")[1].split("</carried_findings_for_this_reviewer>")[0]
        assert all(f'"{finding["id"]}"' in section for finding in mine), shard["id"]
        assert "finding:<id>" in section and "resolved_findings" in section
        assert len(section) < 60_000
        # Resolution still goes through the structured resolved_findings object (#659).
        assert "structured object in resolved_findings" in section


def test_vc5_admission_estimate_covers_the_exact_compact_rendering(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "420000")
    write_changes("a.py", "b.py")
    rows = seed_carried(files=["a.py", "b.py"])
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert admitted["status"] == "success", {k: admitted.get(k) for k in ("reason", "overhead_breakdown")}
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", {k: v for k, v in built.items() if k != "prompts"}
    exact = max(shard_manifest(entry)["resources"]["prompt"]["bytes"] + shard_manifest(entry)["resources"]["diff"]["bytes"]
                for entry in built["prompts"].values())
    overhead = runner._review_fixed_overhead(
        admitted["target"], "claude", admitted["scheduled_reviewers"], "feature", admitted["required_files"], [], {}, rows)
    assert overhead["total"] >= exact, (overhead["total"], exact)
    assert overhead["breakdown"]["carried_findings"] < 150_000


def test_vc6_a_plan_that_cannot_fit_fails_fast_with_a_breakdown(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "420000")
    write_changes("a.py", "b.py")
    seed_carried(1500, files=["a.py", "b.py"])
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded", result
    assert result["reason"] == "fixed_overhead_too_large"
    assert result["overhead_breakdown"]["carried_findings"] > 0
    assert not runner._read_review_ledger(Path(".map/feature")).get("convergence", {}).get("rounds")
