# MAP Framework Improvement Done

## Learning handoff artifacts and zero-argument `/map-learn` [2604.035-1]

- Date: 2026-04-12
- Shipped branch-scoped `learning-handoff.md` / `.json` generation via `map_step_runner.py`, and recorded the result in the `learn_handoff` stage of `artifact_manifest.json`.
- Wired `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` to write the handoff artifact so the expensive learning step can be deferred without losing workflow context.
- Updated `/map-learn` and the `map-learn` skill to auto-load `.map/<branch>/learning-handoff.md` when invoked with no arguments, while still allowing explicit inline summaries or file paths.
- Updated `README.md`, `docs/USAGE.md`, and `docs/ARCHITECTURE.md` so MAP still presents `LEARN` as the philosophical closeout, but a soft runtime step.

## Learn adoption metrics and deferred-usage tracking [2604.035-2]

- Date: 2026-04-12
- Added branch-scoped `learning-metrics.json` tracking in `map_step_runner.py`, including handoff generation, handoff consumption, immediate vs deferred learn counters, never-used handoff counts, manual-summary counts, and pending handoff state.
- Emitted matching learning events to `.claude/metrics/agent_metrics.jsonl` so branch-local usage data also appears in the repo-wide metrics stream.
- Updated `write_learning_handoff` so every generated handoff records metrics immediately and surfaces the metrics artifact through the `learn_handoff` manifest stage.
- Updated `/map-learn` and the `map-learn` skill so successful runs record whether the resolved workflow summary came from an auto-loaded handoff, an explicit file handoff, or inline user text.
- Left repeated learned-rule violation detection to follow-up slice `2604.035-3`, since correlating findings to persisted rules is a separate problem from adoption/deferred-use instrumentation.
