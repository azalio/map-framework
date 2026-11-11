"""Behavioral oracles and scoring boundaries for paired review evaluation."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.skills_eval import review_quality as quality

CORPUS = Path(__file__).parent / "skills_eval/review_quality/corpus.json"


def _function(case, name, revision="head"):
    namespace: dict[str, Any] = {}
    # Only execute repository-owned fixture code, never submitted review/model output.
    exec(compile(case["input"][revision], "paired-review-fixture", "exec"), namespace)  # noqa: S102 -- trusted repository fixtures
    return namespace[name]


def test_pair_oracles_preserve_causal_failure_sequences():
    cases = quality.load_corpus(CORPUS)["cases"]
    for case in cases[:2]:
        renewal = _function(case, "renew")
        base = _function(case, "renew", "base")
        deadline, acquired = 10, False
        baseline_deadline, baseline_acquired = 10, False
        for tick in range(1, 31):
            deadline = renewal(deadline, tick, False)
            baseline_deadline = base(baseline_deadline, tick, False)
            acquired |= tick >= deadline
            baseline_acquired |= tick >= baseline_deadline
        assert baseline_acquired
        assert acquired == (case["targets"][0]["truth"] == "safe")
        assert renewal(10, 5, True) == 25
    for case in cases[2:4]:
        next_cursor = _function(case, "next_cursor")
        cursor, recovered = 7, False
        for _ in range(5):
            accepted = cursor != 7  # server outcome depends on the actual request
            recovered |= accepted
            cursor = next_cursor(cursor, accepted)
        assert recovered == (case["targets"][0]["truth"] == "safe")
    for case in cases[4:6]:
        metric = _function(case, "metric_name")
        names = {metric(f"request{i}") for i in range(1000)}
        assert (len(names) <= 3) == (case["targets"][0]["truth"] == "safe")


def _run(tmp_path):
    corpus = quality.load_corpus(CORPUS)
    text = "Raw reviewer report retained for independent adjudication.\n"
    (tmp_path / "report.txt").write_text(text)
    report = {"path": "report.txt", "sha256": hashlib.sha256(text.encode()).hexdigest(), "complete": True}
    results = {"schema_version": 1, "corpus_sha256": quality.digest(corpus), "runs": [{
        "run_id": "repeat-1", "model": "test-fixture", "prompt_sha256": "a" * 64, "cases": []}]}
    for case in corpus["cases"]:
        truth = case["targets"][0]["truth"]
        results["runs"][0]["cases"].append({
            "case_id": case["id"], "before_report": report.copy(), "after_report": report.copy(), "candidates": [{
                "candidate_id": "candidate-1", "target_id": "primary", "reviewer_claimed": truth == "defect",
                "verdict": quality.EXPECTED[truth], "adjudication": "Independent cause/scenario match to the primary target."}]})
    return corpus, results


def test_scoring_reports_lost_and_recovered_true_defects_separately(tmp_path):
    corpus, results = _run(tmp_path)
    cases = results["runs"][0]["cases"]
    cases[0]["candidates"][0]["verdict"] = "refuted"
    cases[2]["candidates"][0]["reviewer_claimed"] = False
    metrics = quality.score(corpus, results, tmp_path)["runs"][0]
    assert metrics["before"]["recall"] == 2 / 3
    assert metrics["after"]["recall"] == 2 / 3
    assert metrics["lost_true_defects"] == [("r001", "primary")]
    assert metrics["recovered_true_defects"] == [("r003", "primary")]
    assert metrics["loss_rate"] == 0.5
    assert metrics["recall_by_priority"]["P1"]["after"] == 2 / 3
    assert metrics["recall_by_priority"]["P0"]["after"] is None


def test_duplicates_unknown_and_unclaimed_hypotheses_do_not_inflate_metrics(tmp_path):
    corpus, results = _run(tmp_path)
    cases = results["runs"][0]["cases"]
    duplicate = copy.deepcopy(cases[0]["candidates"][0])
    duplicate["candidate_id"] = "duplicate"
    cases[0]["candidates"].append(duplicate)
    # One rejected false positive plus another hypothesis never asserted as a defect.
    cases[1]["candidates"].extend([
        {"candidate_id": "fp", "target_id": "false-positive:style", "reviewer_claimed": True,
         "verdict": "refuted", "adjudication": "No behavioral consequence."},
        {"candidate_id": "discarded", "target_id": "false-positive:other", "reviewer_claimed": False,
         "verdict": "refuted", "adjudication": "Abandoned hypothesis, never an accusation."},
    ])
    cases[6]["candidates"][0].update(reviewer_claimed=True, verdict="refuted")
    metrics = quality.score(corpus, results, tmp_path)["runs"][0]
    assert metrics["before"] == {"true_positive": 3, "false_positive": 1, "precision": 0.75, "recall": 1.0}
    assert metrics["after"]["precision"] == 1.0
    assert metrics["excluded_unknown"] == 1
    assert metrics["verdict_accuracy"] == 7 / 8


def test_missing_hypotheses_are_not_correct_verdicts_and_zero_denominator_is_null(tmp_path):
    corpus, results = _run(tmp_path)
    for case in results["runs"][0]["cases"]:
        case["candidates"] = []
    metrics = quality.score(corpus, results, tmp_path)["runs"][0]
    assert metrics["before"]["precision"] is None
    assert metrics["before"]["recall"] == 0
    assert metrics["loss_rate"] is None
    assert metrics["verdict_accuracy"] is None
    assert metrics["target_coverage"] == 0
    assert len(metrics["missing_targets"]) == 8


@pytest.mark.parametrize("problem", ["stale", "missing", "duplicate", "incomplete", "tampered", "unknown_target", "invalid_bool"])
def test_bad_run_is_rejected_instead_of_scored_as_clean(tmp_path, problem):
    corpus, results = _run(tmp_path)
    cases = results["runs"][0]["cases"]
    if problem == "stale":
        results["corpus_sha256"] = "old"
    elif problem == "missing":
        cases.pop()
    elif problem == "duplicate":
        cases.append(cases[0])
    elif problem == "incomplete":
        cases[0]["after_report"]["complete"] = False
    elif problem == "tampered":
        (tmp_path / "report.txt").write_text("changed")
    elif problem == "unknown_target":
        cases[0]["candidates"][0]["target_id"] = "another-real-bug"
    else:
        cases[0]["candidates"][0]["reviewer_claimed"] = "false"
    with pytest.raises(ValueError):
        quality.score(corpus, results, tmp_path)


def test_export_has_only_neutral_inputs_and_refuses_reuse(tmp_path):
    corpus = quality.load_corpus(CORPUS)
    output = tmp_path / "inputs"
    manifest = quality.prepare(corpus, output)
    for case in manifest["cases"]:
        payload = json.loads((output / case["input"]).read_text())
        assert set(payload) == {"base", "head", "contract"}
        assert "pair_id" not in payload and "targets" not in payload
    with pytest.raises(FileExistsError):
        quality.prepare(corpus, output)


def test_cli_score_reads_persisted_reports(tmp_path, monkeypatch, capsys):
    corpus, results = _run(tmp_path)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results))
    monkeypatch.setattr("sys.argv", ["review_quality", "score", "--corpus", str(CORPUS), "--results", str(path)])
    assert quality.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["corpus_sha256"] == quality.digest(corpus)
    assert report["runs"][0]["after"]["recall"] == 1.0
