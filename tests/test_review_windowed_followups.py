"""Follow-ups to windowed review sources: renames, causes, risk record, mapping, namespaces, env rules (#642)."""

import json
from pathlib import Path

import pytest

from tests.test_review_changed_scope import (
    git,
    read_resource,
    runner,
    shard_manifest,
    write_changes,
)
from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_roster_budget import required_bytes
from tests.test_review_windowed_sources import (
    admit_and_build,
    big_lines,
    seed_big,
    source_resource,
    sparse_edit,
)

repo = _base_repo
__all__ = ["repo"]


def serve_all(entry, resource, round_id="w", reviewer="monitor"):
    chunks, offset = [], 0
    while True:
        request = {"type": "context_request", "context_id": entry["context_transport"]["context_id"],
                   "resource_id": resource, "offset": offset}
        served = runner.serve_review_context(reviewer, json.dumps(request), round_id, branch="feature")
        assert served["status"] == "context_response", served
        chunks.append(served["content"])
        if served["eof"]:
            return "".join(chunks)
        offset = served["next_offset"]


def resource_key(entry, path):
    return next(key for key, item in shard_manifest(entry)["resources"].items() if item.get("path") == path)


def seed_rename():
    lines = big_lines()
    Path("pkg").mkdir()
    Path("pkg/big.py").write_text("".join(lines))
    git("add", ".")
    git("commit", "-qm", "big")
    git("branch", "-f", "main", "HEAD")
    git("mv", "pkg/big.py", "pkg/big2.py")
    edited = list(lines)
    edited[3000] = "  CHANGED_AFTER_MOVE: 1\n"
    Path("pkg/big2.py").write_text("".join(edited))
    return "".join(lines)


def test_vc24_renamed_large_file_with_a_small_edit_admits_windowed_against_the_old_blob(repo):
    del repo
    original = seed_rename()
    admitted, entry = admit_and_build("mv")
    assert "shard_ids" not in admitted
    meta = source_resource(entry, "pkg/big2.py")
    assert meta["windowed"] is True and meta["bytes"] < 80_000
    payload = json.loads(read_resource(Path(".map/feature"), entry, resource_key(entry, "pkg/big2.py")))
    assert payload["status"] == "renamed" and payload["renamed_from"] == "pkg/big.py"
    assert "CHANGED_AFTER_MOVE" in json.dumps(payload["hunks"])
    old = json.loads(read_resource(Path(".map/feature"), entry, resource_key(entry, "pkg/big.py")))
    assert old["status"] == "renamed_to" and old["renamed_to"] == "pkg/big2.py" and old["base_content"] == ""
    # The old base is the lazy "base" side of the new path, with the full mapping.
    full = json.loads(serve_all(entry, "base:pkg/big2.py", "mv"))
    assert full["content"] == original and full["renamed_from"] == "pkg/big.py"
    resources = shard_manifest(entry)["resources"]
    exact = sum(item["bytes"] for key, item in resources.items() if key.startswith("source_") or key == "diff")
    estimate = sum(runner._review_required_bytes(admitted["target"], admitted["required_files"]).values())
    assert estimate >= exact, (estimate, exact)


def test_vc25_file_too_large_hint_names_the_actual_cause(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(runner.REVIEW_CONTEXT_RESERVE_BYTES + 60_000))
    Path("added.txt").write_text("".join(big_lines(3000)))
    Path("blob.bin").write_bytes(bytes(range(256)) * 400)
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="c", base_ref="main")
    assert result["reason"] == "file_too_large", result
    assert result["oversized_causes"] == {"added.txt": "added", "blob.bin": "binary"}
    hints = " ".join(result["hints"])
    assert "newly added" in hints and "binary" in hints and "changed hunks" not in hints


def test_vc26_full_shadow_risk_is_a_lazy_resource_and_hidden_from_blind_reviewers(repo):
    del repo
    write_changes(*(f"auth/module_{index}.py" for index in range(12)))
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="w", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    entry = runner.build_review_prompts(branch="feature")["prompts"]["maintainer"]
    text = read_resource(Path(".map/feature"), entry, "prompt")
    assert '"full_record_resource": "risk:shadow"' in text
    full = json.loads(serve_all(entry, "risk:shadow", reviewer="maintainer"))["shadow_risk"]
    assert full["reasons"] == admitted["target"]["shadow_risk"]["reasons"] and len(full["reasons"]) > 5
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert row["context_lazy"]["risk:shadow"]["kind"] == "risk"
    other = runner.build_review_prompts(branch="feature")["prompts"]["monitor"]
    assert runner.serve_review_context("monitor", json.dumps({
        "type": "context_request", "context_id": other["context_transport"]["context_id"],
        "resource_id": "risk:other", "offset": 0}), "w", branch="feature")["status"] == "error"


def test_vc27_carried_findings_are_measured_at_admission(repo, monkeypatch):
    del repo
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", "420000")
    write_changes("a.py", "b.py")
    directory = Path(".map/feature")
    directory.mkdir(parents=True, exist_ok=True)
    ledger: dict = runner._read_review_ledger(directory) or {"schema_version": "review_verdict_ledger.v1"}
    ledger["findings_registry"] = [
        {"id": f"F-M-{index:03d}", "status": "active", "source_agent": "maintainer", "originating_reviewer": "maintainer",
         "claim": "A carried claim that must be rechecked. " * 12, "affected_files": ["a.py"],
         "bug_class": "logic", "cause": "c" * 80, "failure_scenario": "f" * 80} for index in range(120)]
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", {k: v for k, v in built.items() if k != "prompts"}
    carried = len(json.dumps(ledger["findings_registry"], ensure_ascii=True))
    exact = max(shard_manifest(entry)["resources"]["prompt"]["bytes"] + shard_manifest(entry)["resources"]["diff"]["bytes"]
                for entry in built["prompts"].values())
    overhead = runner._review_fixed_overhead_bytes(
        admitted["target"], "claude", admitted["scheduled_reviewers"], "feature", admitted["required_files"], [], {},
        ledger["findings_registry"])
    assert overhead >= exact and overhead > carried, (overhead, exact, carried)


def test_vc28_windowed_mapping_is_correct_inside_windows_and_full_in_the_lazy_resource(repo):
    del repo
    base_text = seed_big(sparse_edit)
    current_text = Path(".sourcecraft/ci.yaml").read_text()
    _, entry = admit_and_build("map")
    payload = json.loads(read_resource(Path(".map/feature"), entry, resource_key(entry, ".sourcecraft/ci.yaml")))
    assert payload["line_mapping_scope"] == "windowed" and payload["line_mapping"], "empty mapping reads as all-new"
    base_lines, current_lines = base_text.splitlines(), current_text.splitlines()
    covered_current = set()
    for hunk in payload["hunks"]:
        covered_current.update(range(hunk["current_start"], hunk["current_start"] + len(hunk["current"].splitlines())))
    for block in payload["line_mapping"]:
        for offset in range(block["length"]):
            assert base_lines[block["base_start"] - 1 + offset] == current_lines[block["current_start"] - 1 + offset]
            assert block["current_start"] + offset in covered_current
    full = json.loads(serve_all(entry, "current:.sourcecraft/ci.yaml", "map"))
    assert full["line_mapping_scope"] == "full"
    assert full["line_mapping"] == runner._review_line_mapping(base_text, current_text)
    assert len(payload["line_mapping"]) <= len(full["line_mapping"]) * 3


def test_vc29_a_repo_file_named_like_a_full_source_id_is_not_shadowed(repo):
    del repo
    Path("base:foo").write_text("literal repo file\n")
    seed_big(sparse_edit, path="foo")
    _, entry = admit_and_build("ns")
    frozen = json.loads(serve_all(entry, "base:foo", "ns"))
    assert frozen["content"].startswith("  step_00000")
    literal = json.loads(serve_all(entry, "repo:base:foo", "ns"))
    assert literal["current_content"] == "literal repo file\n"
    row = runner._read_review_ledger(Path(".map/feature"))["convergence"]["rounds"][-1]
    assert row["context_lazy"]["base:foo"]["kind"] == "full_source"
    assert row["context_lazy"]["repo:base:foo"]["path"] == "base:foo"


@pytest.mark.parametrize("raw", ["1_0", "²", "１０", "-3", "0", "1e1", " ", "0x10", "10 0"])
def test_vc30_max_shards_env_accepts_only_plain_ascii_decimals(monkeypatch, raw):
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", raw)
    assert runner._review_max_shards({}) == runner.REVIEW_MAX_SHARDS
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", raw)
    assert runner._review_context_budget({}) == runner.REVIEW_CONTEXT_BUDGET_BYTES


def test_vc30_plain_decimals_are_accepted(monkeypatch):
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", " 12 ")
    assert runner._review_max_shards({}) == 12


def test_vc31_a_failing_report_never_aborts_admission(repo, monkeypatch):
    del repo
    write_changes("a.py")

    def broken(*_args, **_kwargs):
        raise RuntimeError("coverage report exploded")

    monkeypatch.setattr(runner, "build_acceptance_coverage_report", broken)
    monkeypatch.setattr(runner, "build_prior_stage_consumption_report", broken)
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="boom", base_ref="main")
    assert admitted["status"] == "success", admitted


def seed_findings(count, who="maintainer"):
    directory = Path(".map/feature")
    directory.mkdir(parents=True, exist_ok=True)
    ledger: dict = runner._read_review_ledger(directory) or {"schema_version": "review_verdict_ledger.v1"}
    ledger["findings_registry"] = [
        {"id": f"F-{index:04d}", "status": "active", "source_agent": who, "originating_reviewer": who,
         "claim": "A carried claim that must be rechecked. " * 10, "affected_files": ["a.py"],
         "bug_class": "logic", "cause": "c" * 100, "failure_scenario": "f" * 100,
         # Registry-only bulk that the per-reviewer section does not render.
         "evidence_log": "e" * 700} for index in range(count)]
    runner._write_json_file(directory / "review-verdict-ledger.json", ledger)
    return ledger["findings_registry"]


def commit_big_base(name="big.py"):
    Path(name).write_text("".join(big_lines()))
    git("add", ".")
    git("commit", "-qm", "big")
    git("branch", "-f", "main", "HEAD")


def test_vc32_rename_to_a_skipped_generated_file_leaves_a_stub_for_the_old_side(repo):
    del repo
    commit_big_base()
    git("mv", "big.py", "zz_generated_big.go")
    Path("zz_generated_big.go").write_text("".join(big_lines()).replace("step_03000", "step_CHANGED"))
    admitted, entry = admit_and_build("gen")
    assert [item["path"] for item in admitted["coverage_skips"]] == ["zz_generated_big.go"]
    old = json.loads(read_resource(Path(".map/feature"), entry, resource_key(entry, "big.py")))
    assert old["status"] == "renamed_to" and old["renamed_to"] == "zz_generated_big.go" and old["base_content"] == ""


def test_vc33_unstaged_move_reports_deleted_and_added_causes(repo):
    del repo
    commit_big_base()
    Path("big.py").rename("big2.py")
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="mv", base_ref="main")
    assert result["reason"] == "file_too_large", result
    assert result["oversized_causes"] == {"big.py": "deleted", "big2.py": "added"}
    hints = " ".join(result["hints"])
    assert "deleted file" in hints and "newly added" in hints and "changed hunks" not in hints


def test_vc34_many_carried_findings_admit_when_the_exact_bytes_fit(repo):
    del repo
    write_changes("a.py", "b.py")
    rows = seed_findings(110)
    # Old rule charged twice the full registry JSON (> budget); the rendered section is smaller than the rows.
    assert 2 * len(json.dumps(rows)) > runner.REVIEW_CONTEXT_BUDGET_BYTES - 90_000
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert admitted["status"] == "success", {k: admitted.get(k) for k in ("reason", "oversized_paths", "total", "budget")}
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    built = runner.build_review_prompts(branch="feature")
    assert built["status"] == "success", {k: v for k, v in built.items() if k != "prompts"}
    exact = max(required_bytes(entry) for entry in built["prompts"].values())
    sizes = runner._review_required_bytes(admitted["target"], admitted["required_files"])
    reserve = runner._review_fixed_overhead_bytes(
        admitted["target"], "claude", admitted["scheduled_reviewers"], "feature", admitted["required_files"], [], {}, rows)
    assert sum(sizes.values()) + reserve >= exact, (sum(sizes.values()) + reserve, exact)


def test_vc35_overhead_alone_over_budget_is_reported_as_fixed_overhead(repo):
    del repo
    write_changes("a.py", "b.py")
    seed_findings(1500)
    result = runner.begin_review_run(branch="feature", provider="claude", round_id="carry", base_ref="main")
    assert result["stop_reason"] == "review_context_budget_exceeded", result
    assert result["reason"] == "fixed_overhead_too_large" and "oversized_paths" not in result
    breakdown = result["overhead_breakdown"]
    assert breakdown["worst_role"] == "maintainer" and breakdown["carried_findings"] > 1_000_000
    assert {"role_prompt", "execution_checks_in_prompt", "trusted_policy_in_prompt"} <= set(breakdown)
    assert any("carried findings" in hint for hint in result["hints"])
