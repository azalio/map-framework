## 2026-05-17 - LEARN as a philosophical requirement with soft runtime ergonomics [2604.035]

- Decision: `rejected`
- Branch: `codex/2604-035-close-learn-parent`
- Baseline: The parent item remained active in `docs/improvement-plan.md`, but its executable child slices `2604.035-1`, `2604.035-2`, and `2604.035-3` were already recorded as shipped and the runtime/docs evidence showed the soft-LEARN user payoff was live.
- Forward Change: Removed the stale active parent section and recorded the exact `[2604.035]` heading in `docs/improvement-done.md` with repo-grounded evidence instead of rebuilding the learning handoff, zero-argument `/map-learn`, metrics, or repeated-rule tracking behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused learning handoff regression tests, and repo evidence searches verified the parent is no longer active while shipped learning artifacts remain covered.
- Review Result: Diff review confirmed this is a ledger-only stale-parent closure with no runtime or template mutations.
- Next Trigger: Reuse this learning whenever an active umbrella item says to use child slices and all children are already shipped in `docs/*-done.md`.
- Reusable Learnings:
  - review-check: `Before selecting an active umbrella item, compare its proposed changes against shipped child slice ids in docs/*-done.md; if all value-bearing children are already complete, close the parent with evidence rather than executing it again.`

## 2026-05-17 - Detached reviewer context and worktree-assisted review [2604.037]

- Decision: `rejected`
- Branch: `codex/2604-037-close-detached-review-plan`
- Baseline: The idea remained active in `docs/improvement-plan.md`, but runtime, shipped template, docs, and tests showed `/map-review --detached` and the canonical review bundle had already shipped.
- Forward Change: Removed the stale active plan section, recorded the exact `[2604.037]` heading in `docs/improvement-done.md` with repo-grounded evidence, and changed `docs/roadmap.md` from open follow-up to shipped status instead of rebuilding existing behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused detached-review skill tests, focused `prepare_detached_review` tests, and a repo-built generated-project smoke verified the plan/done state and shipped review-isolation artifacts.
- Review Result: Diff review found `docs/roadmap.md` still listed `2604.037` as open; fixed by marking the review-independence iteration shipped and keeping contract-sized subtasks as the next active roadmap work.
- Next Trigger: Reuse this learning whenever an active plan item describes a workflow capability that may already be visible in skill prompts, generated templates, helper scripts, user docs, and focused regression tests.
- Reusable Learnings:
  - review-check: `Before implementing a review-workflow backlog item, inspect both the user-facing skill surface and generated template copy, then verify helper-script and focused-test coverage for the advertised flags/artifacts.`
  - review-check: `When closing stale plan items, reconcile secondary ledgers such as roadmap status tables, not only docs/improvement-plan.md and docs/improvement-done.md.`

## 2026-05-16 - Workflow fit classifier and explicit off-ramp for trivial work [2604.038]

- Decision: `rejected`
- Branch: `codex/2604-038-close-workflow-fit-plan`
- Baseline: The idea remained active in `docs/improvement-plan.md`, but runtime, schema, skill, docs, and test evidence showed workflow-fit routing had already shipped.
- Forward Change: Removed the stale active plan section and recorded the exact `[2604.038]` heading in `docs/improvement-done.md` with repo-grounded evidence instead of rebuilding existing behavior.
- Decisive Validation: the improvement-plan-loop idea indexer, focused workflow-fit regression tests, template sync tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke verified the plan/done state and shipped off-ramp artifacts.
- Validation Boundary: Full `pytest` was attempted and progressed through deterministic tests plus the first three live Claude SDK checks, then exceeded the tool timeout at `TestMapEfficientE2E::test_efficient_produces_code_changes`; rerunning that single live SDK test also exceeded 15 minutes without a deterministic assertion failure.
- Review Result: Diff review confirmed the change is documentation/ledger-only and does not alter runtime behavior.
- Next Trigger: Reuse this learning whenever an active plan item references behavior already visible in runtime code, generated templates, docs, and tests.
- Reusable Learnings:
  - review-check: `Before implementing an active idea, inspect active and done headings, then search runtime, shipped templates, docs, and tests for the core artifact/route names; close stale plan entries instead of rebuilding shipped behavior.`

## 2026-05-16 - Health report analytics and CI assertions [2604.017-4]

- Decision: `implemented`
- Branch: `2604.017-4-health-report-validation`
- Baseline: `run_health_report.json` was written during workflow closeout, but teams had no deterministic command to fail inconsistent reports in CI or operator handoff.
- Forward Change: Added `validate_run_health_report` with schema checks when available plus built-in shape and semantic checks for generated projects, synced the shipped script template, documented the command, and added regressions for valid reports, complete-with-pending steps, missing verification evidence, retry overflow, unexplained hook degradation, invalid terminal status, and CLI non-zero exit.
- Decisive Validation: `pytest tests/test_map_step_runner.py::test_write_run_health_report_creates_report_and_manifest tests/test_map_step_runner.py::test_validate_run_health_report_accepts_valid_complete tests/test_map_step_runner.py::test_validate_run_health_report_rejects_inconsistent_complete tests/test_map_step_runner.py::test_validate_run_health_report_rejects_retry_and_hook_degradation tests/test_map_step_runner.py::test_validate_run_health_report_rejects_schema_drift_without_package_schema tests/test_map_step_runner.py::test_map_step_runner_cli_validate_run_health_report_exits_nonzero tests/test_template_sync.py -v`, `make lint`, `pytest -m "not slow"`, and generated-project pass/fail smoke passed.
- Validation Boundary: Full `pytest` and `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` were attempted, but live Claude SDK e2e timed out at `TestMapEfficientE2E::test_efficient_produces_code_changes`; no deterministic failure surfaced before the timeout.
- Review Result: Diff review found schema drift could pass when package schema/jsonschema was unavailable; fixed by adding built-in run-health shape checks and a regression that disables package schema loading.
- Next Trigger: Reuse this learning whenever adding generated-project validators that must fail CI without optional package dependencies.
- Reusable Learnings:
  - command: `python3 .map/scripts/map_step_runner.py validate_run_health_report [path]`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Generated-project validators must enforce critical schema shape locally, not only through optional package imports or optional jsonschema behavior.`
  - review-check: `When documenting a validator as CI-failing schema enforcement, test the dependency-unavailable path and at least one malformed-but-semantically-benign artifact.`

## 2026-05-16 - Expand hook degradation status coverage [2604.017-3]

- Decision: `implemented`
- Branch: `2604.017-3-hook-degradation-status`
- Baseline: The PreToolUse hook wrote `hook_injection` for emitted reminders and no-reminder formatting skips, but malformed hook input and insignificant Bash commands were silent when safe branch state existed.
- Forward Change: Added safe state reads with explicit degradation reasons, persisted skipped outcomes for malformed hook payloads and insignificant Bash commands when `step_state.json` is parseable, preserved non-blocking/no-clobber behavior for missing or invalid state, synced the shipped hook template, and documented the new diagnostic signal.
- Decisive Validation: `pytest tests/test_workflow_context_injector.py tests/test_template_sync.py -v`, `pytest tests/test_map_step_runner.py::test_write_run_health_report_creates_report_and_manifest tests/test_artifact_schemas.py::test_validate_run_health_report_schema -v`, `make lint`, `pytest -m "not slow"`, and generated-project `uv run --no-sync mapify init <new-dir> --no-git --mcp none` hook smokes passed.
- Review Result: Diff-scoped review found a malformed payload gap where non-string Bash commands could still raise; fixed by normalizing `tool_name` and `command` before classification and added a regression test.
- Next Trigger: Reuse this learning whenever hook code accepts JSON from Claude/tooling before deciding whether to mutate branch state.
- Reusable Learnings:
  - command: `pytest tests/test_workflow_context_injector.py tests/test_template_sync.py -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Hook inputs are untrusted even after JSON parsing; normalize field types before calling string-specific helpers.`
  - invariant: `Hook degradation status may update only parseable existing branch state; missing or invalid state must not be created or clobbered by a diagnostic write.`
  - review-check: `When adding a skipped/degraded hook path, test both the persisted reason and the non-blocking/no-state-mutation failure path.`

## 2026-05-16 - Auto-write run health reports from workflow closeout paths [2604.017-2]

- Decision: `implemented`
- Branch: `2604.017-2-run-health-closeout`
- Baseline: `write_run_health_report` existed and had schema/writer tests, but `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` closeout prompts did not call it, so `run_health_report.json` was optional/manual.
- Forward Change: Added closeout prompt wiring in the four workflow skills, required `RUN_HEALTH_STATUS` to be set from the final verdict before invoking the helper, synced templates, and documented automatic closeout-time report generation.
- Decisive Validation: `pytest tests/test_skills.py::TestRunHealthCloseoutWiring -v`, `pytest tests/test_template_sync.py tests/test_skills.py::TestSkillStructure::test_skill_templates_in_sync -v`, `make lint`, `pytest -m "not slow"`, and a repo-built `uv run --no-sync mapify init <new-dir> --no-git --mcp none` smoke that wrote and inspected `.map/default/run_health_report.json` passed. Read-only review found and then confirmed fixes for prompt sequencing/status-default issues.
- Validation Boundary: Unfiltered `pytest` and `pytest tests/integration/test_e2e_claude_sdk.py -v -m slow` were attempted against live Claude SDK tests, but both exceeded tool timeouts after partial progress. This slice's no-LLM artifact contract was validated directly in a generated project.
- Next Trigger: Reuse this learning whenever adding prompt-level closeout commands whose arguments depend on workflow verdicts or terminal states.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestRunHealthCloseoutWiring -v`
  - command: `uv run --no-sync mapify init <new-dir> --no-git --mcp none`
  - invariant: `Prompt closeout snippets that write terminal artifacts must appear after the section that determines the final verdict/status.`
  - review-check: `Tests must reject both direct hard-coded happy-path arguments and variable defaults such as RUN_HEALTH_STATUS="complete" when non-happy terminal statuses are valid.`

## 2026-05-15 - Action-first tool use in lightweight workflows [2604.028]

- Decision: `implemented`
- Branch: `codex/2604-028-action-first-lightweight`
- Baseline: `map-fast` and `map-debug` asked Actor to return `code_changes` with full file content, then told the orchestrator to apply changes after validation, while `map-efficient` already used direct Actor Edit/Write behavior.
- Forward Change: Converted the lightweight Actor prompts to apply edits directly, changed Monitor prompts to read written files from the repo, removed stale post-validation apply steps, synced templates, and documented the action-first behavior.
- Decisive Validation: `pytest tests/test_skills.py::TestLightweightWorkflowSkillContracts tests/test_template_sync.py -v`, `make lint`, `pytest -m "not slow"`, and `uv run mapify init <temp-path> --no-git --mcp none` with generated-file inspection passed. Unfiltered `pytest` was attempted twice but timed out in real Claude SDK slow e2e tests.
- Next Trigger: Reuse this learning whenever changing workflow prompts that describe Actor output, Monitor validation inputs, or generated skill templates.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py::TestLightweightWorkflowSkillContracts tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `If Actor applies edits directly, no workflow overview, decision point, or post-review step may still describe a separate apply phase.`
  - review-check: `Prompt regression tests should reject both old schema terms like code_changes and natural-language leftovers such as "Apply fix" or "ACCEPT and apply changes".`

## 2026-04-13 - Official-frontmatter hygiene for MAP skills [2604.031]

- Decision: `implemented`
- Branch: `codex/2604-031-skill-frontmatter`
- Baseline: `map-planning` shipped with a 371-character description that referenced non-existent `map-workflows-guide` and `map-cli-reference` surfaces, `map-learn` had no argument hint for manual invocation, and no test failed on those metadata regressions.
- Forward Change: Shortening the two shipped skill descriptions, adding `argument-hint: "[workflow-summary]"` to `map-learn`, and adding dedicated metadata lint tests closed the actual UX gaps without pulling the whole stale skill taxonomy into scope.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py tests/test_command_templates.py -v` passed, and `uv run mapify init <new-dir> --no-git --mcp none` generated the updated skill frontmatter in a throwaway project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/`, `src/mapify_cli/templates/skills/`, or the installer copy path and you need to prove the generated project reflects the branch state.
- Reusable Learnings:
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `When changing shipped skill metadata, keep descriptions under 250 characters and make every map-* reference resolve to a real shipped command or skill.`
  - gotcha: `The globally installed mapify binary can lag behind the branch under test and show stale templates even when the repo diff is correct.`
  - review-check: `For manual slash skills, always verify the frontmatter exposes an argument hint before shipping catalog changes.`

## 2026-05-15 - Skill trigger and invocation regression testing [2604.034]

- Decision: `implemented`
- Branch: `codex/2604-034-skill-invocation-tests`
- Baseline: `test_skills.py` validated basic skill frontmatter and sync, but did not prove `skill-rules.json` manual invocation metadata matched `SKILL.md`, did not require direct slash names in trigger rules, did not test selected negative-trigger fixtures, and did not verify relative supporting links, supporting-file template sync, or `CLAUDE_PLUGIN_ROOT` hook commands.
- Forward Change: Added those catalog integrity checks and corrected `map-learn` from suggested domain skill to manual slash skill in both development and shipped template metadata.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v` passed, `pytest -m "not slow"` passed, and `uv run mapify init <temp-dir> --no-git --mcp none` emitted manual `map-learn` metadata plus bundled rule templates in a generated project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/skill-rules.json`, skill frontmatter, hook metadata, or Markdown links to files bundled under a skill directory.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `A skill with manual slash invocation must have an argument-hint and its direct map-* name in skill-rules keywords and intent patterns.`
  - invariant: `Relative Markdown links, non-SKILL supporting files, and CLAUDE_PLUGIN_ROOT hook commands must resolve and stay synced before template release.`
  - gotcha: `When linting Markdown links in skill bodies, strip fenced code blocks first so regex snippets like [ =]([0-9]+) are not mistaken for Markdown links.`

## 2026-05-15 - Explicit reference-vs-task skill architecture [2604.032]

- Decision: `implemented`
- Branch: `codex/2604-032-skill-taxonomy`
- Baseline: The shipped skills README still said skills were passive documentation only, referenced non-existent `map-workflows-guide`, and `skill-rules.json` had no machine-readable way to distinguish task workflows from reference guidance or `map-state` hook side effects.
- Forward Change: Added `skillClass` metadata, classified MAP slash workflows as `task`, classified `map-state` as `hybrid` with `runtimeEffects`, rewrote skill taxonomy docs, removed stale skill references, and added regression tests for task/reference/hybrid boundaries.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v`, `pytest -m "not slow"`, and `make lint` passed. `uv run mapify init <new-dir> --no-git --mcp none` emitted `map-state` as `hybrid`, `map-learn` as `task`, and the generated skills README included the taxonomy.
- Next Trigger: Reuse this learning whenever a change adds, removes, or reclassifies a shipped skill, especially if it changes manual invocation, hooks, scripts, or file-writing behavior.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every shipped skill-rules.json entry must declare skillClass as reference, task, or hybrid.`
  - invariant: `Task skills must be manual slash workflows; reference skills must not hide manual invocation, hooks, or runtime effects; hybrid skills must declare runtimeEffects.`
  - gotcha: `Docs can retain stale skill names even after catalog tests pass; grep for removed/non-shipped skill names such as map-workflows-guide and map-cli-reference when changing skill taxonomy.`
