# MAP Framework Improvement Done

## Clean-room retry and context quarantine for failed agent iterations [2605.08563]

- Date: 2026-05-20
- Added clean-room retry isolation to the Actor->Monitor failure path: the first Monitor rejection remains an ordinary feedback retry, while the second or later rejection for the same subtask marks `retry_isolation=clean_retry_required`, increments clean retry counters, and writes `.map/<branch>/retry_quarantine.json`.
- The quarantine artifact records the subtask, retry count, compact Monitor rejection summary, do-not-repeat guidance, preserved constraints, required evidence, and source artifact references so the next Actor attempt can change approach without dropping `blueprint.json` hard constraints, acceptance tags, or mutation boundaries.
- Extended `run_health_report.json` resiliency signals with `clean_retry_count`, `contaminated_retry_count`, and `retry_isolation_status`, plus retry-quarantine artifact inventory, so interrupted or blocked workflows expose whether a retry was isolated.
- Wired `/map-efficient`, `/map-task`, `/map-debug`, and `/map-resume` to validate or build retry quarantine artifacts before clean retries, and synced the shipped template copies so generated projects receive the same retry boundary.
- Added schema support for retry quarantine artifacts and focused regression coverage for serial retries, wave retries, run-health counters, quarantine validation, and source/template sync.

## Constraint-first provider rule templates [2604.040]

- Date: 2026-05-20
- Added `Mutation Boundary Constraints` to write-capable Claude provider surfaces: `.claude/agents/actor.md`, `/map-fast`, `/map-efficient`, `/map-task`, and `/map-debug`, plus the shipped template copies.
- Added matching Codex constraints to `.codex/AGENTS.md` and `$map-fast`, plus the shipped template copies, so installed Codex projects get the same unrelated-edit/dependency-change boundary.
- The constraints tell agents not to edit unrelated files, add/remove/upgrade dependencies, or refactor neighboring code unless the current task/subtask explicitly requires it; required scope expansion must be reported as a blocker/tradeoff instead of done silently.
- Added regression tests that scan source and generated Claude/Codex provider surfaces for the mutation-boundary section and required phrases before release.
- Updated README, usage, and architecture docs to describe the installed-user behavior and maintainer guardrail.
- Verified with focused mutation-boundary prompt tests, full skill/template-sync tests, generated Claude and Codex `mapify init` smokes that inspected installed provider files, Skill IR audit, `make lint`, `pytest -m "not slow"`, and no-LLM e2e artifact tests. Full `pytest` and the slow Claude SDK module were attempted, but each exceeded the 30-minute tool timeout without a deterministic failure message.

## Compact high-traffic workflow playbooks [2604.033-2]

- Date: 2026-05-20
- Compactified the high-traffic workflow skill bodies for `/map-plan`, `/map-efficient`, `/map-check`, and `/map-review`, reducing active `SKILL.md` sizes to 301, 295, 295, and 302 lines respectively while preserving required phase headings, state-machine commands, output contracts, run-health closeout, review bundle wiring, and handoff flows.
- Moved low-frequency examples, troubleshooting, detailed rationale, command matrices, wave details, and reference notes into bundled supporting files: `plan-reference.md`, `efficient-reference.md`, `check-reference.md`, and `review-reference.md`.
- Synced the `.claude/skills/` changes into shipped templates so generated projects receive the same compact active playbooks and bundled references.
- Added regression coverage that enforces active high-traffic workflow skill bodies stay under 500 lines, link their supporting reference, and ship source/template supporting files.
- External documentation checked: Claude Code skills docs, https://docs.anthropic.com/en/docs/claude-code/skills, accessed 2026-05-20; relevant constraints are that invoked `SKILL.md` content stays in context, compaction reattaches recent skill invocations within a limited token budget, supporting files should hold detailed reference material, and `SKILL.md` should stay focused.

## Compact `/map-resume` Recovery Skill Body [2604.033-1]

- Date: 2026-05-20
- Moved `/map-resume` low-frequency example transcripts, integration notes, state-file shape examples, token-budget notes, and troubleshooting into bundled `resume-reference.md` so the invoked recovery `SKILL.md` stays focused on checkpoint detection, briefing, confirmation, and state-machine continuation.
- Reduced the active `/map-resume` skill body from 504 lines to 305 lines while preserving required Examples and Troubleshooting navigation sections plus links to the supporting reference.
- Added regression coverage that scans both `.claude/skills/map-resume/` and the shipped template copy so recovery skill growth and missing supporting references fail before release.
- External documentation checked: Claude Code skills docs, https://docs.anthropic.com/en/docs/claude-code/skills, accessed 2026-05-20; relevant constraints are that invoked `SKILL.md` content stays in context, compaction reattaches recent skill invocations within a limited token budget, supporting files should hold detailed reference material, and `SKILL.md` should stay focused.
- Updated README, usage, and architecture docs to describe the compact recovery surface, and updated the active plan parent with follow-up slices for high-traffic workflow playbooks and retained-body linting.

## Budget Decision Artifact for Active Prompt Paths [2604.023-3]

- Date: 2026-05-20
- Added `.map/<branch>/token_budget.json` generation to the two active budgeted prompt paths: `/map-efficient` Actor `<map_context>` building and `/map-review` Monitor/Predictor/Evaluator prompt fan-out.
- Each decision records the prompt path name, configured budget, estimated tokens before/after enforcement, budget action, clipped section labels, source artifact references, and path-specific metadata such as role, current subtask, and budget environment variable.
- Added a `token_budget` artifact-manifest stage and `TOKEN_BUDGET_REPORT_SCHEMA` so generated projects have a machine-readable operator breadcrumb for deciding whether to continue, raise `MAP_CONTEXT_BLOCK_BUDGET_TOKENS` / `MAP_REVIEW_PROMPT_BUDGET_TOKENS`, or split the workflow.
- Updated README, usage, and architecture docs to describe the operator flow while keeping the artifact limited to already-active prompt builders, not dormant REGISTRY/FOCUS mechanisms.
- Verified with focused Actor/review prompt budget tests, token-budget schema tests, template-sync coverage, and a generated-project smoke that created both Actor and review prompt decisions from real branch artifacts plus a real git diff.

## Reviewer Prompt Budget Enforcement [2604.023-2]

- Date: 2026-05-19
- Added `build_review_prompts` to `.map/scripts/map_step_runner.py` and the shipped template copy so `/map-review` builds separate bounded Monitor, Predictor, and Evaluator prompts from the persisted review bundle, review preferences, and raw `git diff` before fan-out.
- Each reviewer prompt now defaults to a 12,000 estimated-token cap via `MAP_REVIEW_PROMPT_BUDGET_TOKENS`, preserves reviewer task/instruction/output-contract XML envelope sections, keeps `.map/<branch>/review-bundle.md` as the primary context, clips lower-priority raw diff context first, and emits a `Review Prompt Budget` diagnostic document when clipping occurs.
- Updated `/map-review` skill wiring and shipped template copy to call the prompt builder before Task fan-out, plus README, usage, architecture, and roadmap docs so installed projects expose the new review budget boundary.
- Verified with focused prompt-builder tests, a synthetic old/new reviewer A/B test proving the new prompt stays under budget while the old inline prompt exceeds it, skill/template-sync tests, lint, and a generated-project smoke that created an oversized review bundle and raw diff then confirmed the installed helper preserved the primary bundle sentinel while clipping the diff tail.

## Actor Context Block Token Budget Enforcement [2604.023-1]

- Date: 2026-05-19
- Added deterministic estimated-token helpers to `src/mapify_cli/token_budget.py` and wired generated `.map/scripts/map_step_runner.py` `build_context_block()` output through a hard budget gate.
- The generated Actor `<map_context>` path now defaults to a `4000` estimated-token cap, honors `MAP_CONTEXT_BLOCK_BUDGET_TOKENS` for explicit override, keeps current-subtask identity and dependency summaries ahead of broad plan overview text, and emits a `# Context Budget` truncation note while preserving a closed `</map_context>` tag.
- Field check against `/Users/azalio/gitroot/src.yandex.cloud` found 8 current-format MAP runs and 63 sampled subtask contexts; the largest generated Actor `<map_context>` was ~1,255 estimated tokens, while raw artifacts in the same tree reached ~16,013-token `blueprint.json`, ~13,240-token review bundle, and ~11,819-token task plan sizes. This confirms the shipped Actor path is compact on real runs and that remaining risk sits in other prompt paths that may consume raw artifacts.
- Synced the shipped template helper copy, updated README, usage, architecture, and roadmap docs, and split the remaining umbrella budget work into active child slices for review prompt budgeting and budget-decision artifacts only after active prompt paths need them.
- Verified with focused token-budget and context-block tests plus template-sync coverage; generated-project smoke and broader validation are recorded in the PR evidence.

## Clean-session TEST->CODE handoff for TDD workflows [2604.036]

- Date: 2026-05-19
- Decision: rejected as an active-plan item because the clean-session TDD handoff path is already implemented for the targeted TDD workflow where it has the strongest user payoff.
- Repo evidence: `.claude/skills/map-tdd/SKILL.md` and the shipped template copy define targeted TDD as `DECOMPOSE -> TEST_WRITER -> TEST_FAIL_GATE -> CONTRACT_HANDOFF -> STOP`, write `.map/${BRANCH}/test_contract_${SUBTASK_ID}.md`, call `record_test_contract_handoff`, mark the contract ready, and tell the user to resume implementation with `/map-task ST-001`.
- Repo evidence: `.claude/skills/map-task/SKILL.md` and the shipped template copy detect `test_handoff_<subtask>.json` plus `test_contract_<subtask>.md` and call `resume_from_test_contract` so Actor starts from the persisted red-phase contract instead of re-running research or test authoring.
- Repo evidence: `.map/scripts/map_orchestrator.py` and the shipped template copy implement `mark_contract_ready` and `resume_from_test_contract`; Actor instructions in TDD mode require code-only implementation and tell Actor to read the persisted contract artifacts before editing.
- Repo evidence: `.map/scripts/map_step_runner.py` and the shipped template copy implement `record_test_contract_handoff`, write `test_handoff_<subtask>.json`, and record the `test_contract` stage in `artifact_manifest.json`.
- Repo evidence: `tests/test_map_orchestrator.py::TestResumeFromTestContract`, `tests/test_map_step_runner.py::test_record_test_contract_handoff_creates_json_and_manifest`, README, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, and `docs/roadmap.md` all cover or document the targeted clean-session handoff behavior.
- No runtime change was needed; this loop removed the stale active backlog section so future loops do not rebuild the shipped targeted TDD contract handoff.

## Compile-time skill IR and anti-injection audit for provider surfaces [2605.221]

- Date: 2026-05-19
- Added `src/mapify_cli/skill_ir.py`, a typed static audit layer that lowers shipped Claude and Codex `SKILL.md` files into `SkillIR` records with provider, name, invocation mode, allowed tools, supporting-file references, extracted safety constraints, and SHA-256 content hashes.
- The audit exits non-zero for unsupported frontmatter, frontmatter/folder name mismatch, missing descriptions, unresolved bundled Markdown references, links escaping the provider bundle root, and hidden instruction-override phrases such as “ignore previous instructions.”
- Added `python -m mapify_cli.skill_ir src/mapify_cli/templates/skills src/mapify_cli/templates/codex/skills` as the release validation command for hand-authored provider skill surfaces until a full generator is worth the migration.
- Updated README, usage, architecture, and roadmap docs so maintainers know the Skill IR audit protects provider surfaces before `mapify init` installs them into user repos.
- Verified with focused Skill IR tests, ruff on the new module/tests, focused skill/template regression tests, the Skill IR audit CLI, `make lint`, `pytest -m "not slow"`, and repo-built generated-project smokes that emitted both Claude and Codex skill trees. Full `pytest` was attempted after the final code changes and reached the live `/map-review` SDK boundary before the 30-minute tool timeout; the exact boundary test passed on rerun.

## Context-first XML envelopes for slash commands [2604.026]

- Date: 2026-05-19
- Added a shared `.claude/references/map-xml-prompt-envelopes.md` reference, with the shipped template copy, documenting the artifact-first XML envelope pattern from Anthropic long-context/XML prompt guidance.
- Updated `/map-plan`, `/map-efficient`, `/map-debug`, and `/map-review` high-context subagent prompts so long artifacts are wrapped in `<documents>` before `<task>`, workflow instructions, and `<expected_output>`.
- Refactored `/map-review` reviewer fan-out prompts so the persisted review bundle, review preferences, and git diff are separate tagged documents, with the bundle explicitly primary and the diff secondary.
- Updated README, usage, architecture, and roadmap docs, and added regression tests that scan both `.claude/skills/` and `src/mapify_cli/templates/skills/` for the XML envelope reference and required tags.
- Verified with focused XML envelope/template-sync tests, `make lint`, `pytest -m "not slow"`, a repo-built `mapify init` smoke that inspected generated skill/reference output, the timed-out live SDK boundary test rerun, live `/map-review` E2E, and live full-flow E2E. Full `pytest` and the full live SDK module were attempted but exceeded the 30-minute tool timeout at the same cumulative live boundary without a deterministic failure; the exact boundary test passed individually.

## Claude 4.6 command simplification and verb calibration [2604.025]

- Date: 2026-05-18
- Recalibrated shipped MAP skill prompts so non-release workflows use targeted guardrails and normal wording instead of blanket all-caps prohibition blocks. `/map-release` keeps explicit hard-stop language because tag pushes and PyPI publication are irreversible.
- Added explicit `When Not To Expand Scope` clauses to `/map-fast`, `/map-check`, `/map-resume`, and `/map-task` so lightweight/resume/single-subtask flows stop at their intended boundary instead of adding extra research, planning, agents, or polish.
- Tightened `/map-debug`, `/map-efficient`, `/map-tdd`, and `/map-plan` wording around required phases while preserving real gates for research, Monitor validation, blueprint metadata, TDD read-only test boundaries, and state-machine operations.
- Synced `.claude/skills/` into shipped templates, updated README/usage/architecture/roadmap docs, and added prompt-tone regression coverage that rejects blanket prohibition blocks in non-release task skills.
- Verified with focused prompt-tone/template-sync tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke that inspected emitted skill prompts. Full `pytest` was attempted and exceeded the 30-minute tool timeout at the live Claude SDK review boundary after plan/efficient live tests passed; the timed-out review test passed on rerun and the full `TestMapReviewE2E` class passed separately.

## Command-specific thinking and parallelism profiles [2604.029]

- Date: 2026-05-18
- Added `## Effort and Parallelism Policy` blocks to all shipped MAP task skills and synced the generated template copies so installed projects receive the same calibration.
- Lightweight workflows (`/map-fast`, `/map-check`, `/map-resume`) now declare `thinking_policy: low/direct`; implementation and learning workflows declare `medium/adaptive`; planning, review, and release declare `high/adaptive`.
- Each skill also declares a concrete `parallel_tool_policy`, such as independent checks only, guarded `/map-efficient` waves only, or the single `/map-review` reviewer fan-out, so provider prompts have workflow-specific limits instead of generic “parallel where possible” wording. The top-level `workflow-rules.json` also records execution policies for workflow-triggered `/map-fast`, `/map-efficient`, and `/map-debug` suggestions.
- Updated README, usage, and architecture docs, and added regression coverage that scans both `.claude/skills/` and `src/mapify_cli/templates/skills/` for the policy blocks.
- Verified with focused skill policy tests, full skill/template sync tests, `make lint`, `pytest -m "not slow"`, and a generated-project `mapify init` smoke that inspected emitted policy lines. Full `pytest` was attempted; the live Claude SDK boundary reached review E2E after earlier live plan/efficient tests passed, timed out at 30 minutes, and the exact first boundary test passed separately in 7:01. A subsequent full slow SDK rerun was stopped by the user while another live review test was still running.

## Prior-stage artifact consumption gates [2604.039-followup-3]

- Date: 2026-05-18
- Added `build_prior_stage_consumption_report` and `validate_prior_stage_consumption <implementation|review>` to `.map/scripts/map_step_runner.py` and the shipped template copy so MAP closeout can prove whether spec, task plan, blueprint, test contract, code diff, and review-time verification summary were consumed.
- Extended `write_verification_summary` and `create_review_bundle` so human Markdown and machine-readable review bundles include `prior_stage_consumption`; review manifest status now downgrades to `warn` when required prior-stage inputs are missing instead of hiding stage skipping.
- Updated `REVIEW_BUNDLE_SCHEMA`, `/map-efficient`, `/map-review`, README, usage, and architecture docs so generated projects expose the same validator-backed artifact pipeline.
- Verified with helper/schema/skill/template tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke that passed both implementation and review validators with real branch artifacts plus a git diff.

## Acceptance coverage in review and verification artifacts [2604.039-followup-4]

- Date: 2026-05-18
- Added acceptance coverage reporting to `.map/scripts/map_step_runner.py` and the shipped template copy so `write_verification_summary` and `create_review_bundle` summarize every `blueprint.json` `coverage_map` tag.
- Marked each tag as `covered` only when bracketed evidence such as `[AC-1]` or `[INV-1]` appears in downstream verification, QA, test contract, handoff, PR draft, or review artifacts; otherwise the Markdown and JSON outputs show `missing_evidence`.
- Extended `REVIEW_BUNDLE_SCHEMA`, review-bundle Markdown, manifest review-stage metadata, and user/architecture docs so reviewers get both human-readable and machine-readable acceptance evidence before approval.
- Verified with focused acceptance-coverage, review-bundle, schema, and artifact tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke for the shipped helper copy.

## Hard/soft constraint typing in spec and blueprint gates [2604.039-followup-2]

- Date: 2026-05-18
- Added `hard_constraints` and `soft_constraints` to the blueprint schema and planner/decomposer prompts so MAP plans explicitly separate blocking requirements from negotiable preferences before implementation starts.
- Updated `validate_blueprint_contract` in `.map/scripts/map_step_runner.py` and the shipped template copy so every hard constraint id must appear in `coverage_map` and in the owning subtask's bracketed `validation_criteria`; soft constraints can be left out only with `tradeoff_rationale`.
- Synced Claude and Codex provider surfaces, decomposition examples, and docs so generated projects ask for and validate the same constraint contract.
- Verified with focused schema/validator/prompt/template-sync tests, `make lint`, `pytest -m "not slow"`, and a repo-built generated-project smoke that accepted a covered hard constraint and exited nonzero for missing hard coverage plus unexplained soft tradeoff.
- Full unfiltered `pytest` was attempted and reached live Claude SDK e2e, then exceeded tool timeout at `TestMapEfficientE2E::test_efficient_produces_code_changes`; rerunning that single live test with a longer timeout also exceeded the limit without a deterministic assertion failure.

## Acceptance-criteria lineage tags in blueprint validation [2604.039-followup-1]

- Date: 2026-05-18
- Split the broad artifact-lineage follow-up into executable child slices and shipped the first reviewer-visible slice: every `coverage_map` key in `blueprint.json` must now appear as a bracketed tag in the owning subtask's `validation_criteria`, for example `VC1 [AC-1]: ...`.
- Updated `validate_blueprint_contract` in `.map/scripts/map_step_runner.py` and the shipped template copy so untagged validation criteria fail before Actor starts, with an actionable error naming the missing tag.
- Updated Claude and Codex planner/decomposer surfaces plus the package schema and user docs so generated plans ask for bracketed requirement lineage instead of only assigning ownership in `coverage_map`.
- Verified with focused blueprint validator/schema/prompt/template-sync tests and a repo-built generated-project smoke where a tagged blueprint passed and an untagged blueprint exited nonzero.

## Few-shot command examples and evidence-quoted outputs [2604.027]

- Date: 2026-05-17
- Added a shared `.claude/references/map-output-examples.md` evidence-first examples file and synced it into shipped templates so MAP prompts have compact review, debug, and spec-review JSON examples.
- Updated `/map-review` Monitor, Predictor, and Evaluator prompts to require `evidence[]` before verdict, risk, or score fields, with HIGH/CRITICAL issues, high-risk claims, breaking changes, and sub-7 scores tied to concrete quotes.
- Updated `/map-debug` investigation, Monitor, Predictor, and Evaluator prompts to quote logs, test output, changed code, or similar issue evidence before root-cause, verdict, risk, or score fields.
- Updated `/map-plan` spec-review and decomposition prompts to cite exact spec/source evidence for findings and decomposition boundaries.
- Added regression tests that fail if the high-risk prompts lose their evidence-first contracts or the shared examples stop covering review, debug, and spec-review workflows.
- Left generic linting for future JSON prompt contracts as active follow-up `2604.027-1`; this entry closes the user-visible evidence-output slice, not every possible prompt-lint rule.

## Generic JSON prompt-contract lint for future MAP skills [2604.027-1]

- Date: 2026-05-17
- Added `.claude/references/map-json-output-contracts.md` and the shipped template copy as the reusable backing reference for non-evidence JSON prompt sections.
- Annotated existing `/map-fast`, `/map-debug`, and `/map-learn` non-evidence `Output JSON with:` sections with explicit contract references while leaving evidence-first review/debug/plan judgment outputs backed by evidence or quotes.
- Extended `tests/test_skills.py::TestEvidenceFirstPromptContracts` with valid reference-backed, valid evidence-backed, and invalid vague prompt fixtures, plus a generic scanner over both `.claude/skills/**/SKILL.md` and `src/mapify_cli/templates/skills/**/SKILL.md`.
- Updated user and architecture docs so maintainers know the prompt-contract lint is the release guardrail for future JSON output sections.
- Verified with focused skill/template tests, `make lint`, `pytest -m "not slow"`, and a repo-built `uv run --no-sync mapify init <temp-path> --no-git --mcp none` smoke that inspected the generated reference and skill links.

## Contract-sized subtask guardrails [2604.039]

- Date: 2026-05-17
- Added `validate_blueprint_contract` to `.map/scripts/map_step_runner.py` and the shipped template copy so `/map-plan` and `/map-efficient` can fail oversized, mixed-concern, untraceable, duplicate-ID, dangling-dependency, or non-logical subtasks before implementation starts.
- Extended blueprint contracts with `expected_diff_size`, `concern_type`, `one_logical_step`, `aag_contract`, `validation_criteria`, and `coverage_map`, including nested TaskDecomposer output support in `BLUEPRINT_SCHEMA`.
- Updated Claude and Codex planner/decomposer surfaces plus Monitor and FinalVerifier prompts so contract metadata is generated, carried into Actor context, and checked for scope drift after planning.
- Synced `.claude/`, `.codex/`, and `.map/scripts/` changes into `src/mapify_cli/templates/`, updated README/usage/architecture/roadmap docs, and added regression coverage for weak blueprint contracts, template sync, schema alignment, nested decomposer output, bad coverage owners, duplicate IDs, and unknown dependencies.
- Verified with focused contract/template tests, `make lint`, `pytest -m "not slow"`, generated-project `mapify init` smoke tests for valid and invalid blueprints, and two independent review passes. Remaining artifact lineage and hard/soft constraint typing are tracked as follow-up work.

## Workflow fit classifier and explicit off-ramp for trivial work [2604.038]

- Date: 2026-05-16
- Decision: rejected as an active-plan item because the requested capability is already implemented in the repo.
- Repo evidence: `.map/scripts/map_step_runner.py` and the shipped template copy define `WORKFLOW_FIT_ROUTES`, persist `.map/<branch>/workflow-fit.json` through `record_workflow_fit`, and mark `direct-edit` as `needs_map=false`.
- Repo evidence: `src/mapify_cli/schemas.py` includes `WORKFLOW_FIT_DECISION_SCHEMA` with `direct-edit`, `map-fast`, `map-efficient`, `map-tdd`, and `map-plan` routes.
- Repo evidence: `.claude/skills/map-plan/SKILL.md` and shipped template copies require the workflow-fit gate before planning and explicitly stop on `direct-edit` or `map-fast` off-ramp outcomes.
- Repo evidence: README, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, `docs/roadmap.md`, and e2e prompt coverage already document the off-ramp behavior; this loop added a focused checked-in regression for `direct-edit` recording `needs_map=false`.
- No runtime change was needed; this loop removed the stale active backlog section so future loops do not rebuild the same shipped route.

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

## LEARN as a philosophical requirement with soft runtime ergonomics [2604.035]

- Date: 2026-05-17
- Decision: rejected as an active-plan parent because every executable child slice needed for the promised soft-LEARN payoff is already implemented and recorded below.
- Repo evidence: `docs/improvement-done.md` records `2604.035-1`, `2604.035-2`, and `2604.035-3` as shipped child slices for learning handoff artifacts, zero-argument `/map-learn`, learning adoption metrics, deferred-usage tracking, and repeated learned-rule violation tracking.
- Repo evidence: `.map/scripts/map_step_runner.py` writes `.map/<branch>/learning-handoff.md`, `.json`, and `learning-metrics.json`, records handoff generation/consumption metrics, and records repeated learned-rule violation summaries during `write_learning_handoff`.
- Repo evidence: `.claude/skills/map-efficient/SKILL.md`, `.claude/skills/map-debug/SKILL.md`, `.claude/skills/map-check/SKILL.md`, and `.claude/skills/map-review/SKILL.md` already write learning handoffs at closeout, while `.claude/skills/map-learn/SKILL.md` already documents zero-argument handoff loading.
- Repo evidence: README, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, and `docs/roadmap.md` already document soft runtime learning, learning handoff artifacts, learning metrics, and repeated-rule signals.
- No runtime change was needed; this loop removed the stale parent section so future improvement-plan loops do not reselect the already-shipped LEARN ergonomics bundle.

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

## Detached reviewer context and worktree-assisted review [2604.037]

- Date: 2026-05-17
- Decision: rejected as an active-plan item because the requested review-isolation capability is already implemented in the repo.
- Repo evidence: `.claude/skills/map-review/SKILL.md` and the shipped template copy expose `/map-review --detached`, document graceful degradation, and tell reviewer agents to use the detached worktree read-only when available.
- Repo evidence: `.map/scripts/map_step_runner.py` and the shipped template copy define `create_review_bundle` plus `prepare_detached_review`, producing `.map/<branch>/review-bundle.json`, `.map/<branch>/review-bundle.md`, and an optional `.map/<branch>/detached-review/` worktree without mutating the source branch.
- Repo evidence: `tests/test_skills.py` and `tests/test_map_step_runner.py` cover review bundle wiring, detached flag documentation, no-source-mutation guarantees, unavailable detached fallback, path traversal rejection, and worktree-add failures.
- Repo evidence: README, `docs/USAGE.md`, `docs/ARCHITECTURE.md`, and `docs/roadmap.md` already document the review bundle and detached review path for users and maintainers.
- No runtime change was needed; this loop removed the stale active backlog section so future loops do not rebuild shipped detached-review behavior.
