"""Offline paired review evaluation with independently adjudicated before/after claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.review_corpus import _path, _read_json, _record

VERDICTS = {"confirmed", "refuted", "insufficient_evidence", "pre_existing"}
EXPECTED = {"defect": "confirmed", "safe": "refuted", "unknown": "insufficient_evidence", "pre_existing": "pre_existing"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_corpus(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    _record(data, {"schema_version": int, "cases": list})
    if data["schema_version"] != 1 or not data["cases"]:
        raise ValueError("unsupported or empty quality corpus")
    seen = set()
    pairs: dict[str, list[str]] = {}
    for case in data["cases"]:
        _record(case, {"id": str, "input": dict, "targets": list})
        _path(case["id"])
        if "/" in case["id"] or case["id"] in seen:
            raise ValueError("duplicate or unsafe case id")
        seen.add(case["id"])
        _record(case["input"], {"base": str, "head": str, "contract": str})
        targets = set()
        for target in case["targets"]:
            _record(target, {"id": str, "truth": str, "priority": str, "rationale": str})
            if target["id"] in targets or target["truth"] not in EXPECTED or target["priority"] not in {"P0", "P1", "P2", "P3"}:
                raise ValueError("invalid or duplicate target")
            targets.add(target["id"])
        if not targets:
            raise ValueError("case needs an adjudicated target")
        if "pair_id" in case:
            _record(case, {"pair_id": str})
            if len(case["targets"]) != 1:
                raise ValueError("paired cases require one primary target")
            pairs.setdefault(case["pair_id"], []).append(case["targets"][0]["truth"])
    if any(sorted(truths) != ["defect", "safe"] for truths in pairs.values()):
        raise ValueError("each pair requires exactly one defective and one safe case")
    return data


def prepare(corpus: dict[str, Any], output: Path) -> dict[str, Any]:
    """Export neutral inputs only; keep adjudication and pair labels out of reviewer context."""
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {"schema_version": 1, "corpus_sha256": digest(corpus), "cases": []}
    for index, case in enumerate(corpus["cases"], 1):
        name = f"case-{index:03d}.json"
        content = json.dumps(case["input"], indent=2) + "\n"
        (output / name).write_text(content)
        manifest["cases"].append({"case_id": case["id"], "input": name,
                                  "sha256": hashlib.sha256(content.encode()).hexdigest()})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _evidence(value: Any, root: Path) -> None:
    _record(value, {"path": str, "sha256": str, "complete": bool})
    relative = _path(value["path"])
    path = root / relative
    if value["complete"] is not True or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("incomplete or unsafe report evidence")
    raw = path.read_bytes()
    if not raw.strip() or hashlib.sha256(raw).hexdigest() != value["sha256"]:
        raise ValueError("missing, empty or changed report evidence")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score(corpus: dict[str, Any], results: dict[str, Any], evidence_root: Path) -> dict[str, Any]:
    """Compute metrics from explicit semantic adjudication, never string-match findings."""
    _record(results, {"schema_version": int, "corpus_sha256": str, "runs": list})
    if results["schema_version"] != 1 or results["corpus_sha256"] != digest(corpus) or not results["runs"]:
        raise ValueError("missing runs or stale corpus binding")
    cases = {case["id"]: case for case in corpus["cases"]}
    truths = {(case["id"], target["id"]): target for case in cases.values() for target in case["targets"]}
    defects = {key for key, target in truths.items() if target["truth"] == "defect"}
    output = []
    run_ids = set()
    for run in results["runs"]:
        _record(run, {"run_id": str, "model": str, "prompt_sha256": str, "cases": list})
        if run["run_id"] in run_ids or not re.fullmatch(r"[0-9a-f]{64}", run["prompt_sha256"]):
            raise ValueError("duplicate run or invalid prompt fingerprint")
        run_ids.add(run["run_id"])
        observed_cases = set()
        before: set[tuple[str, str]] = set()
        after: set[tuple[str, str]] = set()
        covered: set[tuple[str, str]] = set()
        verdicts: dict[tuple[str, str], str] = {}
        unknown = set()
        for result in run["cases"]:
            _record(result, {"case_id": str, "candidates": list, "before_report": dict, "after_report": dict})
            case_id = result["case_id"]
            if case_id in observed_cases or case_id not in cases:
                raise ValueError("duplicate or unknown case")
            observed_cases.add(case_id)
            _evidence(result["before_report"], evidence_root)
            _evidence(result["after_report"], evidence_root)
            ids = set()
            for candidate in result["candidates"]:
                _record(candidate, {"candidate_id": str, "target_id": str, "reviewer_claimed": bool,
                                    "verdict": str, "adjudication": str})
                if candidate["candidate_id"] in ids or candidate["verdict"] not in VERDICTS:
                    raise ValueError("duplicate candidate or invalid verdict")
                ids.add(candidate["candidate_id"])
                key = (case_id, candidate["target_id"])
                target = truths.get(key)
                # Unknown real defects must be adjudicated into the corpus before scoring.
                if target is None and not candidate["target_id"].startswith("false-positive:"):
                    raise ValueError("unknown target; correct the corpus before scoring")
                if target is None and not candidate["target_id"].removeprefix("false-positive:").strip():
                    raise ValueError("false-positive target needs a stable adjudicated identity")
                if key in verdicts and verdicts[key] != candidate["verdict"]:
                    raise ValueError("conflicting verdicts for one adjudicated target")
                verdicts[key] = candidate["verdict"]
                if target:
                    covered.add(key)
                if target and target["truth"] == "unknown":
                    unknown.add(key)
                    continue
                if candidate["reviewer_claimed"]:
                    before.add(key)
                if candidate["verdict"] == "confirmed":
                    after.add(key)
        if observed_cases != set(cases):
            raise ValueError("incomplete run; missing cases are not clean reviews")
        before_true, after_true = before & defects, after & defects
        metrics: dict[str, Any] = {"run_id": run["run_id"], "model": run["model"],
                                   "prompt_sha256": run["prompt_sha256"], "known_defects": len(defects)}
        for stage, predictions in (("before", before), ("after", after)):
            true = predictions & defects
            metrics[stage] = {"true_positive": len(true), "false_positive": len(predictions - defects),
                              "precision": _ratio(len(true), len(predictions)), "recall": _ratio(len(true), len(defects))}
        lost = sorted(before_true - after_true)
        metrics.update(lost_true_defects=lost, loss_rate=_ratio(len(lost), len(before_true)),
                       recovered_true_defects=sorted(after_true - before_true),
                       target_coverage=_ratio(len(covered), len(truths)), missing_targets=sorted(set(truths) - covered),
                       excluded_unknown=len(unknown),
                       verdict_accuracy=_ratio(sum(verdicts[key] == EXPECTED[truths[key]["truth"]] for key in covered), len(covered)))
        metrics["recall_by_priority"] = {}
        for priority in ("P0", "P1", "P2", "P3"):
            selected = {key for key in defects if truths[key]["priority"] == priority}
            metrics["recall_by_priority"][priority] = {
                "before": _ratio(len(before_true & selected), len(selected)),
                "after": _ratio(len(after_true & selected), len(selected))}
        output.append(metrics)
    return {"schema_version": 1, "corpus_sha256": digest(corpus), "runs": output,
            "limitations": "Manual semantic adjudication; synthetic pairs and correlated repeats do not prove general review quality."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "prepare", "score"):
        command = commands.add_parser(name)
        command.add_argument("--corpus", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--out", type=Path, required=True)
        if name == "score":
            command.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.corpus)
        if args.command == "prepare":
            result = prepare(corpus, args.out)
        elif args.command == "score":
            result = score(corpus, _read_json(args.results), args.results.parent)
        else:
            result = {"cases": len(corpus["cases"]), "corpus_sha256": digest(corpus)}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
