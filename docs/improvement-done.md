# MAP Framework Improvement Done

## Run health report artifact and hook injection status [2604.017-1]

- Date: 2026-05-15
- Added `write_run_health_report` to `.map/scripts/map_step_runner.py` and the shipped template copy so workflows can emit `.map/<branch>/run_health_report.json` with terminal status, step progress, artifact presence, retry counters, Predictor/final-verifier signals when present, and latest hook-injection state.
- Extended the branch `artifact_manifest.json` ledger with a `run_health` stage and added `RUN_HEALTH_REPORT_SCHEMA` plus manifest/review-bundle schema awareness for the new artifact.
- Updated `workflow-context-injector.py` in `.claude/hooks/` and templates to record non-blocking `hook_injection` and `hook_injection_counts` fields in `step_state.json` whenever it emits or skips a workflow reminder.
- Updated README, usage, architecture, and roadmap docs so `run_health_report.json` is documented as the compact diagnostic snapshot, while leaving automatic closeout wiring and broader analytics as child slices in `docs/improvement-plan.md`.
- Verified with focused step-runner/hook/schema/template tests, lint, `pytest -m "not slow"`, `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` through real `claude -p` commands, and a repo-built `uv run mapify init <temp-path> --no-git --mcp none` smoke that inspected the generated hook and map step runner.

## Auto-write run health reports from workflow closeout paths [2604.017-2]

- Date: 2026-05-16
- Wired `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` closeout prompts to write `.map/<branch>/run_health_report.json` via `write_run_health_report` after the terminal verdict is known.
- Required each closeout snippet to set `RUN_HEALTH_STATUS` from the workflow/review/debug verdict instead of defaulting to `complete`, preserving `pending`, `blocked`, `won't_do`, and `superseded` paths.
- Synced the shipped skill templates, updated README/usage/architecture docs, and added prompt-contract tests that reject hard-coded `complete` snippets and assert `map-efficient`/`map-debug` sequencing.
- Verified with focused skill/template tests, `make lint`, `pytest -m "not slow"`, a repo-built `uv run --no-sync mapify init <temp-path> --no-git --mcp none` generated-project smoke that inspected `run_health_report.json`, and a read-only review pass. Full unfiltered `pytest` and the slow Claude SDK suite were attempted, but live SDK tests exceeded tool timeouts after making progress; deterministic and no-LLM artifact checks passed.

## Expand hook degradation status coverage [2604.017-3]

- Date: 2026-05-16
- Added explicit skipped hook status recording for malformed hook input, non-object hook payloads, non-injected tools, and insignificant Bash commands when an existing branch `step_state.json` can be safely parsed and updated.
- Preserved the non-blocking hook contract for missing, invalid, non-object, or unreadable `step_state.json` by returning `{}` without creating or clobbering state.
- Synced the shipped hook template, updated README/usage/architecture/roadmap docs, and added regression tests for skipped Bash commands, malformed hook input, non-string Bash command payloads, missing `step_state.json`, and invalid `step_state.json` preservation.
- Verified with focused hook/template tests, run-health schema/writer tests, `make lint`, `pytest -m "not slow"`, and repo-built `uv run --no-sync mapify init <temp-path> --no-git --mcp none` generated-project smokes that executed the shipped hook and inspected the persisted skipped reason.

## Health report analytics and CI assertions [2604.017-4]

- Date: 2026-05-16
- Added `validate_run_health_report` to `.map/scripts/map_step_runner.py` and the shipped template copy so CI/operator flows can fail inconsistent `.map/<branch>/run_health_report.json` artifacts with a non-zero CLI exit.
- The validator checks package schema when available and also enforces built-in shape semantics for generated projects without `mapify_cli.schemas`: required fields, terminal-status enum, artifact inventory entries, resiliency signal types, complete-without-pending-steps, complete-without-verification, retry overflow, and hook degradation without a reason.
- Updated README, usage, and architecture docs with the validator command and failure boundaries.
- Verified with focused run-health writer/validator tests, template sync tests, `make lint`, `pytest -m "not slow"`, and repo-built generated-project pass/fail smoke. Full `pytest` and the slow Claude SDK suite were attempted, but live Claude SDK e2e timed out at `TestMapEfficientE2E::test_efficient_produces_code_changes` after earlier slow tests passed.

## Action-first tool use in lightweight workflows [2604.028]

- Date: 2026-05-15
- Rewrote `/map-fast` and `/map-debug` so write-capable Actor steps edit files directly with Edit/Write tools and return compact summaries (`files_changed`, `tests_run`, `remaining_risks`) instead of serialized full-file `code_changes`.
- Updated Monitor prompts in both lightweight workflows to validate written repo state from `Written Files`, and removed stale post-validation apply instructions from the workflow overviews and decision points.
- Synced the changed `.claude/skills/` prompts into `src/mapify_cli/templates/skills/`, updated `docs/USAGE.md` and `docs/ARCHITECTURE.md`, and added regression tests that reject any return to full-file serialization or post-review apply wording.
- Verified with focused skill/template tests, lint, the non-slow suite, and a repo-built `uv run mapify init <temp-path> --no-git --mcp none` smoke that inspected generated `map-fast` and `map-debug` skill files.

## Official-frontmatter hygiene for MAP skills [2604.031]

- Date: 2026-04-13
- Shortened the shipped `map-planning` and `map-learn` skill descriptions to stay under Claude's 250-character listing limit, while removing stale references to non-shipped `map-*` surfaces from frontmatter.
- Added `argument-hint: "[workflow-summary]"` to the skill-backed `/map-learn` surface so manual invocation now advertises its optional workflow summary input without changing zero-argument handoff loading.
- Added focused metadata lint coverage in `tests/test_skills.py` for description length, supported frontmatter keys, broken `map-*` description references, and manual-skill argument hints.
- Synced the `.claude/skills/` changes into `src/mapify_cli/templates/skills/`, updated `README.md` and `docs/USAGE.md`, and confirmed the repo-built `uv run mapify init ...` flow emits the new skill frontmatter.

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

## Repeated learned-rule violation tracking [2604.035-3]

- Date: 2026-04-13
- Added a lightweight correlation pass in `map_step_runner.py` that compares branch findings from `active-issues.json`, `verification-summary.md`, and the latest code-review artifact against learned-rule bullets in `.claude/rules/learned/*.md`.
- Updated `write_learning_handoff` to record repeated learned-rule violation summaries in both `learning-handoff.json` and `learning-metrics.json`, including per-run match details and cumulative repeated-violation counters.
- Emitted `learning_repeated_violation_detected` events to `.claude/metrics/agent_metrics.jsonl` whenever current findings overlap an existing learned rule, so repo-wide metrics can distinguish “we wrote rules” from “the same issue still came back”.
- Added focused regression coverage for one repeated-issue match, one non-match, and a CLI smoke flow that exercises `python map_step_runner.py write_learning_handoff ...` end to end.

## Skill-first slash command consolidation [2604.030]

- Date: 2026-04-13
- Removed the duplicate `.claude/commands/map-learn.md` and `src/mapify_cli/templates/commands/map-learn.md` files so `/map-learn` now has a single canonical implementation in `.claude/skills/map-learn/SKILL.md`.
- Updated template sync and regression tests to treat `/map-learn` as a skill-backed slash surface while keeping the rest of the command template suite intact.
- Updated `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, and `docs/roadmap.md` to document the skill-first migration and the new installed project structure.
- Updated `src/mapify_cli/delivery/file_copier.py` so fresh installs advertise `/map-learn` under skill-backed surfaces instead of command files, and the fallback inline command set no longer recreates the duplicate command.

## Skill trigger and invocation regression testing [2604.034]

- Date: 2026-05-15
- Added skill-catalog regression tests that assert manual slash skill classification matches frontmatter, direct invocation names are present in trigger keywords/patterns, selected negative-trigger fixtures do not match noisy skills, local Markdown supporting-file links resolve, hook commands using `CLAUDE_PLUGIN_ROOT` point at bundled scripts, and non-`SKILL.md` supporting files stay synced into templates.
- Reclassified `map-learn` in `.claude/skills/skill-rules.json` and the shipped template copy from suggested domain skill to manual slash skill, matching its `disable-model-invocation` and `argument-hint` frontmatter.
- Verified template sync and generated-project behavior with `pytest tests/test_skills.py tests/test_template_sync.py -v`, `pytest -m "not slow"`, and a repo-built `uv run mapify init <temp-dir> --no-git --mcp none` smoke that inspected the emitted `.claude/skills/skill-rules.json` and `map-learn` supporting templates.

## Explicit reference-vs-task skill architecture [2604.032]

- Date: 2026-05-15
- Added explicit `skillClass` metadata to `.claude/skills/skill-rules.json` and the shipped template copy: MAP slash workflows are `task`, while `map-state` is `hybrid` with declared hook and `.map` artifact runtime effects.
- Rewrote the shipped skills README and user-facing docs so skills are no longer described as passive-only documentation; the docs now distinguish task, reference, and hybrid skill runtime boundaries.
- Added skill-catalog regression tests that require supported `skillClass` values, enforce task/manual consistency, prevent future reference skills from silently becoming hook-backed/manual workflows, and require hybrid skills to declare `runtimeEffects`.
- Removed stale docs that pointed users at non-existent `map-workflows-guide` and `map-cli-reference` skill paths.
- Verified with `pytest tests/test_skills.py tests/test_template_sync.py -v`, `pytest -m "not slow"`, `make lint`, and a repo-built `uv run mapify init <temp-dir> --no-git --mcp none` smoke that inspected generated `skillClass` metadata.
