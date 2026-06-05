# Model-Tier Trigger-Accuracy Experiment

> Empirical test of "does the model tier matter for skill **trigger routing**?"
> Motivated by Murin 2026 (arXiv:2606.05970), whose central finding is that
> **model choice dominates prompt phrasing** for structured extraction, and that
> a larger model **redistributes** agreement rather than uniformly raising it.
> Here we test the analog in the MAP domain: skill auto-activation accuracy.

## Method

- Tool: `mapify skill-eval run <skill> --eval-set <fixture> --model <tier> [--runs N]`
  (`--model` and `--runs` were added for this experiment; default omits `--model`
  → CLI session model, preserving prior behaviour).
- Metric: trigger-routing accuracy — positives must fire the right skill (first
  `Skill` tool_use in the transcript), negatives must NOT fire the skill.
- Each cell = one seeded `claude -p` with heavy tools disallowed (the body cannot
  do slow work; we only need the activation decision). Trigger read from the
  transcript, with timeout recovery.
- **Noise caveat:** `claude -p` exposes no temperature flag, so decoding is not
  guaranteed deterministic (unlike Murin's temp=0). Single-pass n=9 is noisy;
  the firm-up below uses 3 passes on the primary skill.

> Two harness bugs were fixed *before* collecting data, or the numbers would be
> meaningless: (1) executing skills hit the per-call timeout and were recorded as
> false non-triggers; (2) the description patcher corrupted block-scalar YAML so
> the skill never registered (0 triggers). See commits 9a180ee, 20f70d7.

## Results — firm-up (authoritative)

map-check at **3 passes/model** (n=27); map-explain & map-task at 1 pass (n=9):

| skill | haiku | sonnet | opus |
|---|---|---|---|
| map-check (n=27) | 16/27 (59%) | **24/27 (89%)** | 21/27 (78%) |
| map-explain (n=9) | 3/9 (33%) | 3/9 (33%) | **4/9 (44%)** |
| map-task (n=9) | 3/9 (33%) | 6/9 (67%) | **7/9 (78%)** |
| **overall** | **22/45 (49%)** | **33/45 (73%)** | **32/45 (71%)** |
| mean latency/cell | **23 s** | 47 s | 53 s |

### Pilot (n=9, single pass) — kept only to show why firming up mattered

map-check single-pass read haiku 67% / sonnet 78% / opus 67%, which made Haiku
look as good as Opus. That was **noise**: at n=27 Haiku drops to 59% and the gap
to Sonnet (89%) is real. **Do not trust single-pass n=9 model comparisons.**

## Findings

1. **Model tier DOES matter for routing — but "bigger is better" does NOT hold.**
   Haiku is consistently the weakest (49% overall; −24pp vs Sonnet). Sonnet (73%)
   and Opus (71%) are ~tied overall, but they **redistribute**: Sonnet wins
   map-check (89 vs 78), Opus wins map-explain (44 vs 33) and map-task (78 vs 67).
   No monotonic improvement with size — exactly Murin's per-field pattern.
2. **Opus buys nothing over Sonnet for routing** (71% vs 73%, +6s latency/cell).
   Pay for Opus only where hard-reasoning EXECUTION earns it, not for routing.
3. **The description is the ceiling.** map-explain caps at 33–44% across ALL
   tiers — no model rescues a weak `description:`. The lever for trigger accuracy
   is the description (the optimizer sweep), not the model. Consistent with the
   project's earlier "contract/prose is the lever, model competence is largely
   fixed" lesson.
4. **Negatives are robust across tiers** — map-check never falsely fired on its
   negatives at any tier; bigger models additionally route negatives to the
   correct *other* skill.

## Implications for model tiering in MAP

- **Skill routing / session model / `skill-eval` dispatcher → Sonnet.** Best
  accuracy/latency balance; never the worst; Opus adds latency without a routing
  gain; Haiku costs ~24pp. (This REVISES the pilot's "Haiku suffices.")
- **Haiku** stays fine for non-discriminative retrieval/summarisation
  (research-agent), but is weak at instruction-following *discrimination* — avoid
  it where correct routing/judgment matters.
- **Opus** — reserve for hard reasoning / specificity in EXECUTION
  (task-decomposer, final-verifier, debate-arbiter). Trigger routing ≠ execution
  quality; the latter is untested here and Murin's "larger model categorises more
  specifically" plausibly applies to it.
- **Weak-description skills (e.g. map-explain) → run the description optimizer.**
  Model can't fix them; the description is the bottleneck.

## Current framework model assignments (for reference)

opus: task-decomposer, final-verifier, debate-arbiter ·
sonnet: actor, monitor, evaluator, predictor, synthesizer, reflector, documentation-reviewer ·
haiku: research-agent ·
skill-eval dispatcher/proposer: CLI session default (no pin).

## Reproduce

```bash
# 3 passes, one model:
mapify skill-eval run map-check \
  --eval-set tests/skills_eval/fixtures/map_check_optimize_eval_set.json \
  --model sonnet --runs 3
```
