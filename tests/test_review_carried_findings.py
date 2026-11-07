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
    # The originating reviewer's section is complete by design; it is far below the full ledger rows.
    assert overhead["breakdown"]["carried_findings"] < len(json.dumps(rows, ensure_ascii=True)) / 2


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


def parse_entries(section):
    """The JSON objects of an originating-reviewer section, in order."""
    decoder = json.JSONDecoder()
    body = section[section.index("\n{") + 1:]
    body = body.split("\n</carried_findings_for_this_reviewer>")[0]
    entries, position = [], 0
    while position < len(body):
        if body[position].isspace():
            position += 1
            continue
        value, position = decoder.raw_decode(body, position)
        entries.append(value)
    return entries


def joined(value):
    return "".join(value["parts"]) if isinstance(value, dict) else value


LONG_PATH = "deep/" + "segment/" * 24 + "module.py"


def five_file_row():
    files = ["pkg_a/one.py", "pkg_a/two.py", "pkg_b/three.py", "pkg_b/four.py", LONG_PATH]
    assert len(LONG_PATH) > 160
    return {"id": "RVF-500", "status": "active", "severity": "important", "category": "correctness",
            "source_agent": "role", "originating_reviewer": "maintainer", "affected_files": files,
            "claim": "Retry loses writes when the queue is flushed twice. " * 20, "line_range": "10-12",
            "bug_class": "lost-write", "cause": "flush ignores the pending marker " * 5,
            "failure_scenario": "two flushes race and the second drops the first batch " * 3,
            "evidence": [{"source": "finding_location", "quote": json.dumps({"file": files[0], "line": 10})}]}


def test_vc7_originating_section_is_complete_untruncated_and_short_lined():
    row = five_file_row()
    prompt = runner._review_resolution_request("base", {"unresolved_findings": [row]}, "maintainer")
    section = prompt.split("<carried_findings_for_this_reviewer>")[1].split("</carried_findings_for_this_reviewer>")[0]
    (entry,) = parse_entries(section)
    # Resolution needs every affected file inside searched_scope, so none may be cut or omitted.
    assert [joined(name) for name in entry["affected_files"]] == row["affected_files"]
    assert joined(entry["claim"]) == row["claim"] and len(row["claim"]) > 200
    assert joined(entry["bug_class"]) == row["bug_class"] and joined(entry["cause"]) == row["cause"]
    assert joined(entry["failure_scenario"]) == row["failure_scenario"]
    assert "EVERY path" in section and "affected_files" in section
    assert max_line(prompt) <= SAFE_LINE_CHARS
    assert runner._review_resolution_request("base", {"unresolved_findings": [row]}, "predictor") == "base"


def test_vc7_very_long_values_wrap_instead_of_being_cut():
    row = five_file_row()
    row["cause"] = "cause text " * 600
    row["affected_files"] = ["x/" + "d" * 4000 + ".py"]
    prompt = runner._review_resolution_request("base", {"unresolved_findings": [row]}, "maintainer")
    section = prompt.split("<carried_findings_for_this_reviewer>")[1]
    (entry,) = parse_entries(section)
    assert joined(entry["cause"]) == row["cause"] and isinstance(entry["cause"], dict)
    assert joined(entry["affected_files"][0]) == row["affected_files"][0]
    assert max_line(prompt) <= SAFE_LINE_CHARS


def test_vc7_the_compact_listing_marks_what_it_shortens():
    row = five_file_row()
    row["affected_files"] = [LONG_PATH, *row["affected_files"][:4]]
    entry = json.loads(runner._review_compact_finding(row))
    assert LONG_PATH not in json.dumps(entry)
    assert "file" in entry["shortened"] and "claim" in entry["shortened"]
    assert entry["files_total"] == 5
    short = json.loads(runner._review_compact_finding({**row, "affected_files": ["a.py"], "claim": "short"}))
    assert "shortened" not in short and short["file"] == "a.py:10-12"


def test_vc7_the_incremental_trailer_uses_short_lines_and_a_bounded_reason():
    rows = [five_file_row()]
    scope = {"kind": "incremental", "reason": "r" * 5000, "affected_files": [f"p/{n}.py" for n in range(300)],
             "delta_base": "0" * 40, "head": "1" * 40}
    trailer = runner._review_scope_trailer(scope, rows)
    assert max_line(trailer) <= SAFE_LINE_CHARS and "r" * 401 not in trailer


@pytest.mark.parametrize("value", [
    {"log": "\x1b[0m" * 250}, {"path": "\\" * 999}, {"k" * 5000: 1}, {"nested": {"k" * 3000: ["v" * 900] * 4}},
    {"emoji": "\U0001F600" * 990}, {"text": "a" * 10000}])
def test_vc3_the_published_view_never_exceeds_the_line_cap(value):
    raw = json.dumps(value).encode()
    with_parts = runner._review_context_view("x", raw, "0" * 64, part_bytes=runner._review_part_bytes(len(raw)))
    plain = runner._review_context_view("x", raw, "0" * 64)
    assert max_line(with_parts) <= SAFE_LINE_CHARS, max_line(with_parts)
    assert max_line(plain) <= SAFE_LINE_CHARS, max_line(plain)


def test_vc3_a_compact_line_with_wide_text_stays_within_its_budget():
    row = {"id": "F-" + "1" * 60, "severity": "high", "affected_files": ["\U0001F600" * 300] * 5, "status": "active",
           "claim": "\U0001F600" * 300, "line_range": "\U0001F600" * 40}
    assert len(runner._review_compact_finding(row)) <= runner.REVIEW_CARRIED_LINE_BUDGET


def test_vc4_the_estimate_counts_the_incremental_trailer_and_a_long_reason(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "420000")
    write_changes("a.py", "b.py")
    rows = seed_carried(40, files=["a.py", "b.py"])
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert admitted["status"] == "success", {k: admitted.get(k) for k in ("reason", "overhead_breakdown")}
    overhead = runner._review_fixed_overhead(
        admitted["target"], "claude", admitted["scheduled_reviewers"], "feature", admitted["required_files"], [], {}, rows)
    scope = {"kind": "incremental", "reason": "r" * 5000, "affected_files": admitted["required_files"],
             "delta_base": "0" * 40, "head": "1" * 40}
    exact = len(("\n\n" + runner.REVIEW_INCREMENTAL_NOTE + runner._review_scope_trailer(scope, rows)).encode())
    assert overhead["breakdown"]["carried_findings"] >= exact


def test_vc5_a_re_reported_finding_keeps_its_identity_from_the_inline_section():
    row = five_file_row()
    prompt = runner._review_resolution_request("base", {"unresolved_findings": [row]}, "maintainer")
    (entry,) = parse_entries(prompt.split("<carried_findings_for_this_reviewer>")[1])
    report = {"source_agent": "role", "originating_reviewer": "maintainer", "category": entry["category"],
              "claim": joined(entry["claim"]), "bug_class": joined(entry["bug_class"]), "cause": joined(entry["cause"]),
              "failure_scenario": joined(entry["failure_scenario"]),
              "evidence": [{"source": "finding_location",
                            "quote": json.dumps({"file": joined(entry["affected_files"][0]), "line": 99})}]}
    assert runner._review_finding_key(report) == runner._review_finding_key(row)
    drop = {"bug_class", "cause", "failure_scenario"}
    incomplete = {key: value for key, value in row.items() if key not in drop}
    report_incomplete = {key: value for key, value in report.items() if key not in drop}
    assert runner._review_finding_key(report_incomplete) == runner._review_finding_key(incomplete)


def test_vc6_a_blind_co_reporter_cannot_fetch_evidence_authored_by_others(carried_shards):
    _, ledger_row, _rows = carried_shards
    shard = ledger_row["shards"][0]
    directory = Path(".map/feature")
    ledger = runner._read_review_ledger(directory)
    merged = {"id": "RVF-900", "status": "active", "severity": "important", "source_agent": "adversarial",
              "reported_by": ["acceptance", "blind"], "originating_reviewer": "acceptance",
              "claim": "merged", "affected_files": [shard["files"][0]],
              "evidence": [{"source": "spec", "quote": "SPEC-ONLY-EVIDENCE"}]}
    ledger["findings_registry"] = [*ledger["findings_registry"], merged]
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    built = build_shard(shard["id"])
    with pytest.raises(AssertionError):
        fetch_review_resource(runner, built["prompts"]["blind"], "blind", "finding:RVF-900", branch="feature")
    text = fetch_review_resource(runner, built["prompts"]["acceptance"], "acceptance", "finding:RVF-900", branch="feature")
    assert "SPEC-ONLY-EVIDENCE" in text
