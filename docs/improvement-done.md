# MAP Framework Improvement Done

## Learning handoff artifacts and zero-argument `/map-learn` [2604.035-1]

- Date: 2026-04-12
- Shipped branch-scoped `learning-handoff.md` / `.json` generation via `map_step_runner.py`, and recorded the result in the `learn_handoff` stage of `artifact_manifest.json`.
- Wired `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` to write the handoff artifact so the expensive learning step can be deferred without losing workflow context.
- Updated `/map-learn` and the `map-learn` skill to auto-load `.map/<branch>/learning-handoff.md` when invoked with no arguments, while still allowing explicit inline summaries or file paths.
- Updated `README.md`, `docs/USAGE.md`, and `docs/ARCHITECTURE.md` so MAP still presents `LEARN` as the philosophical closeout, but a soft runtime step.
