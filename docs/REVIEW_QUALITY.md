# Review quality before and after verification

The offline evaluator measures both false alarms removed and real defects lost
at Step A.3. It does not dispatch models, change review policy or infer semantic
matches from wording or line numbers. Independent adjudication supplies the mapping.

The initial corpus has eight cases: three defective/correct counterfactual pairs
(lease renewal after failure, recovery from a rejected cursor, and metric-name
cardinality), one unknown caller contract and one pre-existing defect.
`tests/test_review_quality.py` executes deterministic behavioral oracles for the
pairs. These tests validate the fixtures and scorer, not any model's review quality.
The historical corpus and bounded subscription pilot remain available separately.

## Prepare neutral contexts

```bash
uv run python -m mapify_cli.skills_eval.review_quality validate \
  --corpus tests/skills_eval/review_quality/corpus.json
uv run python -m mapify_cli.skills_eval.review_quality prepare \
  --corpus tests/skills_eval/review_quality/corpus.json --out /tmp/review-quality-inputs
```

The output directory must be new. Each input contains only base source, head
source and the applicable contract. The manifest binds their bytes and the corpus
hash. Keep target labels, rationales and pair identities away from reviewers.
Give each case a separate fresh context; do not show its counterpart. Preserve
raw reports from before and after verification, including discarded hypotheses.
Use identical inputs across configurations and repeat each configuration.

## Adjudicate then score

Match each candidate to a corpus target by its cause, triggering path and
consequence. A line or keyword overlap is insufficient. Record a short rationale.
`reviewer_claimed` is true only when the first-stage reviewer actually asserted a
PR defect; a discarded hypothesis, question or pre-existing note is not an accusation.
The final `verdict` is `confirmed`, `refuted`, `insufficient_evidence` or `pre_existing`.
Normalize the final semantic outcome: a supported introduced defect remains
`confirmed` after rewording or a priority downgrade; established baseline attribution
becomes `pre_existing`; an unresolved contract becomes `insufficient_evidence`.
Do not copy a citation-validation status while ignoring baseline attribution.

Results use this structure (include every corpus case exactly once in each run):

```json
{
  "schema_version": 1,
  "corpus_sha256": "<hash from prepare>",
  "runs": [{
    "run_id": "configuration-a-repeat-1",
    "model": "<actual model/configuration>",
    "prompt_sha256": "<64-character sha256 of the full prompt configuration>",
    "cases": [{
      "case_id": "r001",
      "before_report": {"path": "reports/r001-before.txt", "sha256": "<file sha256>", "complete": true},
      "after_report": {"path": "reports/r001-after.txt", "sha256": "<file sha256>", "complete": true},
      "candidates": [{
        "candidate_id": "C-1",
        "target_id": "primary",
        "reviewer_claimed": true,
        "verdict": "refuted",
        "adjudication": "<independent mapping of cause, path and consequence>"
      }]
    }]
  }]
}
```

Paths are relative to the results file. Reports must exist, be nonempty, match
hashes and be marked complete. `candidates: []` means a completed review found
no candidates; never encode a missing or interrupted stage this way. For an
independently adjudicated false alarm outside the target list use a stable
`false-positive:<id>`; semantic duplicates share that identity. A newly discovered
real defect requires correcting the corpus and its binding before comparison.

```bash
uv run python -m mapify_cli.skills_eval.review_quality score \
  --corpus tests/skills_eval/review_quality/corpus.json --results /tmp/review-results/results.json
```

Each run reports before/after precision and recall, recall by priority, lost and
recovered true defects, and loss rate among defects found before verification.
Equal overall recall can hide a lost defect replaced by a different discovery;
the separate identity lists expose that tradeoff. Duplicate targets do not inflate
counts. Unknown contracts are excluded from precision/recall denominators; a DROP
is not credited as correct uncertainty handling. Pre-existing defects count as
false alarms when asserted as introduced PR defects. Empty denominators are null.
Verdict accuracy is over observed unique known targets, with coverage and missing
targets reported separately. An absent question never counts as a correct verdict.

Do not treat removed hypotheses as removed false positives. Compare the same
corpus hash, input evidence and prompt/model configuration; preserve each repeat.
This small synthetic corpus supports regression analysis, not a claim of general
quality improvement. No live-model evaluation is bundled with this change.
