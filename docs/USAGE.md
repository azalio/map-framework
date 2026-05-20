# MAP Framework Usage Guide

Complete usage examples, best practices, and optimization strategies for the MAP Framework.

For long-running work, the canonical MAP flows maintain branch-scoped artifacts directly inside `.map/<branch>/`, so research, code-review lineage, verification summaries, PR drafts, and run dossiers survive context resets.

`/map-plan` now performs a workflow-fit preflight before full planning. If the task is truly tiny, it can explicitly off-ramp to a direct edit or `/map-fast` instead of forcing `SPEC + PLAN`.

## Canonical Flows

### Standard flow

```bash
/map-plan clarify scope and decompose the task
/map-efficient implement the approved plan
/map-check
/map-review
/map-learn [workflow-summary]   # optional; omit to auto-load the generated handoff
```

### Full TDD flow

```bash
/map-plan define the behavior and subtasks
/map-tdd implement with test-first phases enabled
/map-check
/map-review
/map-learn
```

### Targeted subtask TDD flow

```bash
/map-plan decompose work into subtasks
/map-tdd ST-001
/map-task ST-001
/map-tdd ST-002
/map-task ST-002
/map-check
/map-review
/map-learn
```

The full TDD flow is the primary test-first path. The targeted subtask flow is the fine-grained variant when you want to drive one subtask at a time.

In targeted TDD, `/map-tdd ST-001` now stops after the red phase once it has written `test_contract_ST-001.md` and `test_handoff_ST-001.json`. `/map-task ST-001` detects those artifacts and resumes at implementation time instead of re-running research or test authoring.

Philosophically, MAP still ends with `LEARN`. Runtime keeps that step soft and token-aware by auto-writing `.map/<branch>/learning-handoff.md` and `.json` after `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review`, so `/map-learn` can auto-load the workflow context with no manual reconstruction. The same handoff write also updates `learning-metrics.json` with repeated learned-rule violation signals when current findings overlap existing rules, so teams can tell whether saved lessons are actually reducing repeat mistakes.

For workflow diagnosis, `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` now call `python3 .map/scripts/map_step_runner.py write_run_health_report <workflow> [terminal_status]` during closeout. This writes `.map/<branch>/run_health_report.json` and records the `run_health` stage in `artifact_manifest.json`. The report captures terminal status, current step/subtask, completed and pending step counts, artifact presence, retry counters, latest hook-injection status, skipped hook reasons for malformed input or insignificant Bash commands when state can be updated safely, Predictor skip/call flags when present, and final-verifier evidence when a verification summary exists. To assert the report in CI or during operator handoff, run `python3 .map/scripts/map_step_runner.py validate_run_health_report [path]`; it exits non-zero when a complete report still has pending steps, lacks verification evidence, exceeds retry thresholds, has schema drift, or records hook degradation without a reason.

When active prompt builders enforce a context budget, they also append a compact decision to `.map/<branch>/token_budget.json`. `/map-efficient` Actor `<map_context>` generation records the configured `MAP_CONTEXT_BLOCK_BUDGET_TOKENS`, estimated tokens before/after enforcement, clipped section labels such as `plan_overview` or `repo_delta`, and references to the blueprint, task plan, and step state artifacts. `/map-review` reviewer prompt generation records the configured `MAP_REVIEW_PROMPT_BUDGET_TOKENS`, per-role before/after estimates, clipped sections such as `git diff`, and references to the review bundle plus raw diff source. Use this report when a workflow appears to have missing context: if only low-priority sections were clipped, continue; if required evidence was clipped, either raise the relevant budget or split the workflow before rerunning.

Planning artifacts distinguish blocking requirements from negotiable preferences. `/map-plan` and `/map-efficient` blueprint validation now require top-level `hard_constraints` and `soft_constraints`: every hard constraint id must be owned in `coverage_map` and cited in the owning subtask's `validation_criteria`, while a soft constraint can be omitted only when it includes `tradeoff_rationale`. This lets reviewers see whether a requirement was implemented, blocked, or intentionally traded off before Actor starts.

Implementation note: `/map-learn` is now maintained skill-first. The canonical slash surface lives in `.claude/skills/map-learn/SKILL.md`; MAP no longer ships a duplicate `.claude/commands/map-learn.md`, so there is only one place to update the learning workflow. The slash surface now advertises an optional `[workflow-summary]` argument, but zero-argument mode still auto-loads `.map/<branch>/learning-handoff.md` when present.

## Review Workflow: Context Persistence and Detached Mode

`/map-review` auto-generates `.map/<branch>/review-bundle.json` (machine-readable) and `.map/<branch>/review-bundle.md` (human-readable) before launching reviewer agents. The bundle consolidates spec, task plan, test contracts, verification summary, QA results, latest code review artifacts, prior-stage consumption status, and `coverage_map` acceptance-tag evidence into a single durable input contract. This decouples review from implementer session context — reviewer agents read the bundle first; raw diff is used only to confirm or expand bundle findings. When an artifact is absent, the bundle records an explicit `present: false` entry so generation always succeeds regardless of workflow stage.

Before launching Monitor, Predictor, and Evaluator, `/map-review` now runs `python3 .map/scripts/map_step_runner.py build_review_prompts` to assemble bounded fan-out prompts from the persisted bundle, review preferences, and raw `git diff`. Each prompt defaults to a 12,000 estimated-token cap, configurable with `MAP_REVIEW_PROMPT_BUDGET_TOKENS`. If clipping is required, the helper preserves the primary review bundle and reviewer instructions/output contract, clips the secondary raw diff first, and inserts a `Review Prompt Budget` diagnostic document.

The same helper writes per-role decisions into `.map/<branch>/token_budget.json`. Inspect that file after a suspicious review result to confirm whether only the secondary raw diff was clipped or whether the primary review bundle/preference context also hit the cap.

`verification-summary.md` and review bundles now include an **Acceptance Coverage** section derived from `blueprint.json`. Every `coverage_map` tag is marked `covered` only when the tag appears in downstream verification, QA, test-contract, handoff, PR draft, or review artifacts; otherwise reviewers see `missing_evidence` before approving.

`verification-summary.md` and review bundles also include **Prior-Stage Consumption**. This records whether closeout could consume the branch spec, task plan, blueprint, test contract, code diff, and for reviews the verification summary. To enforce the full artifact pipeline in CI or an operator handoff, run `python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption implementation` or `python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption review`; the command exits non-zero with actionable missing-artifact messages.

Reviewer agents now use evidence-first output contracts: Monitor, Predictor, and Evaluator quote concrete file paths, line ranges, and relevant source/diff text before verdict, risk, or score fields. The same evidence-first pattern is used by `/map-debug` root-cause and validation prompts and by `/map-plan` spec-review/decomposition prompts, making failures easier to audit instead of asking users to trust unsupported summaries.

High-context agent prompts now use a shared XML envelope pattern documented in `.claude/references/map-xml-prompt-envelopes.md`. `/map-plan`, `/map-efficient`, `/map-debug`, and `/map-review` put long artifacts such as specs, review bundles, diffs, logs, and current-subtask context in `<documents>` before the `<task>`, workflow instructions, and `<expected_output>`. This preserves the same artifact-first order in generated projects and reduces ambiguity when prompts mix requirements, policy, and schemas.

Maintainer guardrail: every skill prompt section that says `Output JSON with:` must now either include evidence/quotes before judgment fields or cite `.claude/references/map-json-output-contracts.md`. `tests/test_skills.py::TestEvidenceFirstPromptContracts` scans both `.claude/skills/` and shipped template skills so vague JSON contracts fail before release.

Maintainer prompt-tone guardrail: non-release MAP skills should use targeted workflow guardrails and explicit off-ramps instead of blanket all-caps prohibition blocks. `tests/test_skills.py::TestPromptToneCalibration` keeps `/map-fast`, `/map-check`, `/map-resume`, and `/map-task` focused on their intended scope and reserves aggressive hard-stop wording for release safety and irreversible operations.

Maintainer provider-surface guardrail: shipped Claude and Codex skills can be audited as typed `SkillIR` records before release. Run `python -m mapify_cli.skill_ir src/mapify_cli/templates/skills src/mapify_cli/templates/codex/skills` to parse every `SKILL.md`, print deterministic content hashes, and fail unsupported frontmatter, missing bundled Markdown references, or injection-like phrases such as “ignore previous instructions.”

**Optional detached mode:**

```bash
/map-review --detached
```

Creates an isolated read-only git worktree at `.map/<branch>/detached-review/` via `git worktree add --detach` so reviewers can inspect the change in a clean sandbox without touching the source branch. If detached preparation is unavailable (path already exists, no HEAD commit, or git error), the review still proceeds using the persisted bundle. The `review` stage in `.map/<branch>/artifact_manifest.json` is updated on every `/map-review` run regardless of detached mode.

**Cleanup between detached runs.** The detached worktree is intentionally left in place so reviewers can re-open it. Remove it before re-running `/map-review --detached` on the same branch:

```bash
git worktree remove .map/<branch>/detached-review/
```

If `git worktree remove` reports the path is missing or already pruned, delete the directory manually with `rm -rf .map/<branch>/detached-review/`.

**Optional section-order flags:**

Long-context LLM reviewers are susceptible to anchoring: sections presented early receive more attention and can disproportionately influence the final verdict. The following flags let you vary section presentation order to probe verdict stability without changing any section content.

```bash
# Invert the canonical section order (Performance → Tests → Code Quality → Architecture)
claude /map-review --reverse-sections

# Seeded random order — same seed always produces the same order
claude /map-review --shuffle-sections --seed 42

# Run review twice (default order + reverse), aggregate via strict-wins, surface drift
claude /map-review --compare-orderings

# Compare-orderings with a clean-room detached worktree (prepared once, shared across both runs)
claude /map-review --compare-orderings --detached
```

- `--reverse-sections` — inverts the canonical Architecture → Code Quality → Tests → Performance order.
- `--shuffle-sections` — applies a seeded random permutation. If `--seed N` is omitted, a deterministic per-branch seed is derived from `sha256(branch + "|" + commit_sha)` (stable across machines and processes) so the same commit always shuffles identically.
- `--seed N` — explicit integer seed; companion to `--shuffle-sections`. Accepts any non-negative integer.
- `--compare-orderings` — runs the review twice (default order, then reverse), then aggregates results using strict-wins (BLOCK > REVISE > PROCEED). Records `drift_detected`, `drift_summary`, and `final_verdict` in the `ordering` object of `.map/<branch>/review-bundle.json`.

**EC-1 / EC-17 precedence:** `--compare-orderings` always uses `default + reverse-sections`. Combining `--compare-orderings` with `--shuffle-sections` is rejected with a structured error at parse time.

**EC-15 detached interaction:** When `--compare-orderings` is combined with `--detached`, `prepare_detached_review` is called once before the compare loop; both runs reuse the same detached worktree path. Detached preparation is a bundle-collection concern, not a per-run concern.

**Default behavior unchanged:** A plain `/map-review` invocation (no flags) continues to work exactly as before — section order is Architecture → Code Quality → Tests → Performance, single run, same verdict surface. The only unconditional change in all modes is neutral option presentation (options listed as A/B/C with the recommendation marker placed after the list, not first).

## Codex CLI Provider

MAP Framework supports OpenAI's Codex CLI as an alternative to Claude Code.

### Initializing with Codex

```bash
mapify init . --provider codex
```

After starting Codex, enable the installed hook manually:

```text
/hooks
PreToolUse
t
Esc
```

This toggles the `PreToolUse` hook on so MAP's workflow gate can run before tool calls.

If your Codex version does not support the `hooks` feature key yet, either start Codex with the deprecated hooks feature alias enabled:

```bash
codex --enable codex_hooks
```

or upgrade Codex first. Upgrading is recommended.

This creates a `.codex/` layout instead of `.claude/`:
- `.codex/skills/map-plan/SKILL.md` — main planning skill
- `.codex/skills/map-fast/SKILL.md` — quick implementation
- `.codex/skills/map-check/SKILL.md` — quality gates
- `.codex/agents/*.toml` — agent definitions (researcher, decomposer, monitor)
- `.codex/config.toml` — project configuration
- `.codex/hooks.json` + `.codex/hooks/workflow-gate.py` — edit gate enforcement
- `.map/scripts/` — shared orchestrator scripts (same as Claude provider)

### Using MAP with Codex

```bash
$map-plan    # Plan and decompose complex tasks
$map-fast    # Quick implementation with minimal validation
$map-check   # Quality gates and verification
```

Codex MAP skills do not start with `/`. Type `$map-plan`, not `/map-plan`.

### Diagnostics

All diagnostic commands auto-detect the active provider:

```bash
mapify check    # Shows codex-specific tool checks
mapify doctor   # Validates .codex/ structure
mapify upgrade  # Guides re-init for codex projects
```

### Provider coexistence

Both `.claude/` and `.codex/` can exist in the same project. When both are present, `mapify check`/`doctor`/`upgrade` operate in codex mode. The default provider (without `--provider` flag) remains Claude Code.

## Navigation

- [Usage Examples](#usage-examples)
  - [Feature Development](#feature-development)
  - [Bug Fixing](#bug-fixing)
  - [Refactoring](#refactoring)
  - [Library Integration](#library-integration)
  - [Learning from Open Source](#learning-from-open-source)
- [Self-MoA: Solution Synthesis](#self-moa-solution-synthesis)
  - [How Self-MoA Works](#how-self-moa-works)
  - [When to Use Self-MoA](#when-to-use-self-moa)
  - [Example Synthesis](#example-synthesis)
  - [Token Cost Considerations](#token-cost-considerations)
- [Common CLI Mistakes](#-common-cli-mistakes)
  - [Wrong Operation Field Name](#wrong-operation-field-name)
  - [Quick Reference Resources](#quick-reference-resources)
  - [Validation Tools](#validation-tools)
- [Dependency Validation](#dependency-validation)
  - [Basic Usage](#basic-usage)
  - [Visualization Mode](#visualization-mode)
  - [Exit Codes](#exit-codes)
  - [Integration with TaskDecomposer](#integration-with-taskdecomposer)
  - [Sample TaskDecomposer JSON](#sample-taskdecomposer-json)
  - [Validation Output Examples](#validation-output-examples)
  - [Command-Line Flags Reference](#command-line-flags-reference)
  - [Validation Best Practices](#validation-best-practices)
- [Best Practices](#best-practices)
  - [Clear Requirements](#1-clear-requirements)
  - [Incremental Approach](#2-incremental-approach)
  - [Provide Context](#3-provide-context)
- [Cost Optimization](#cost-optimization)
  - [Model Distribution Strategy](#model-distribution-strategy)
  - [Cost Savings](#cost-savings)
  - [How It Works](#how-it-works)
  - [Cost Comparison Example](#cost-comparison-example)
- [Hooks System](#-hooks-system)
  - [Prompt Clarification](#prompt-clarification-prompt-improver-hook)
  - [Sequential Hook Processing](#sequential-hook-processing)
  - [Disabling Prompt-Improver](#disabling-prompt-improver)
  - [Other Active Hooks](#other-active-hooks)
- [Verification Results and Early Termination](#-verification-results-and-early-termination)
  - [Verification Results Tracking](#verification-results-tracking)
  - [Recipe Status Values](#recipe-status-values)
  - [Skipped Status Explained](#skipped-status-explained)
  - [Hooks Contract: When Hooks Block](#hooks-contract-when-hooks-block)
  - [Early Termination with won't_do](#early-termination-with-wont_do-status)
  - [Troubleshooting Verification Issues](#troubleshooting-verification-issues)
- [Additional Resources](#additional-resources)

---

## 📚 Usage Examples

### Feature Development

```bash
/map-efficient implement user profile page with avatar upload.
Include validation, error handling, and tests.
```

### Bug Fixing

```bash
/map-debug debug why payment processing fails for amounts over $1000
```

### Refactoring

```bash
/map-efficient refactor OrderService to use dependency injection.
Maintain all existing functionality.
```

### Library Integration

```bash
/map-efficient integrate Stripe payment processing.
Use deepwiki to get latest Stripe docs.
```

### Learning from Open Source

```bash
/map-efficient implement rate limiter.
Study express-rate-limit via deepwiki, then create optimized version.
```

---

## 🧬 Self-MoA: Solution Synthesis

**Self-MoA** (Self-Mixture of Agents) is an advanced pattern that generates 3 implementation variants and **synthesizes** the best parts into an optimal combined solution.

### How Self-MoA Works

1. **Actor×3** generates variants with different optimization focuses:
   - **V1 (Security)**: Input validation, OWASP compliance, defensive coding
   - **V2 (Performance)**: Algorithm efficiency, caching, async patterns
   - **V3 (Simplicity)**: Readability, standard patterns, clear structure

2. **Monitor×3** validates each variant and extracts:
   - Key design decisions (3-8 per variant)
   - Compatibility features (error handling, concurrency model, etc.)
   - Strengths and weaknesses

3. **Synthesizer** combines the best parts:
   - Extracts all decisions from viable variants
   - Resolves conflicts using priority precedence
   - Generates **fresh unified code** (not copy-paste)

4. **Final Monitor** validates the synthesized solution

### Activation

**Explicit activation:**
```bash
/map-efficient --self-moa implement JWT authentication with refresh tokens
```

**Automatic activation:** When TaskDecomposer marks a subtask as:
- `complexity: high`
- `security_critical: true`

### When to Use Self-MoA

**Use Self-MoA for:**
- Security-critical implementations (auth, data validation, encryption)
- Complex algorithms with multiple valid approaches
- Tasks requiring balance of security, performance, and maintainability
- High-risk features where quality justifies higher token cost

**Skip Self-MoA for:**
- Simple CRUD operations
- Configuration changes
- Documentation updates
- Token-constrained workflows

### Example Synthesis

```
Input Variants:
  V1 (security): Strong input validation, comprehensive error handling
  V2 (performance): Efficient O(n) algorithm, smart caching
  V3 (simplicity): Clean structure, readable code

Synthesis Result:
  - Structure: from V3 (clearest separation of concerns)
  - Validation: from V1 (OWASP-compliant input checks)
  - Algorithm: from V2 (O(n) instead of O(n²))

Output: Clean, secure, AND fast (better than any single variant)
```

### Token Cost Considerations

Self-MoA uses ~4x tokens per subtask:
- 3 Actor calls (parallel)
- 3 Monitor calls (parallel)
- 1 Synthesizer call
- 1 Final Monitor call

**Recommendation:** Use Self-MoA selectively for critical subtasks, not for every task. The `/map-efficient` workflow automatically determines eligibility based on subtask complexity and security flags.

---

## ⚠️ Common CLI Mistakes

This section documents frequently encountered CLI command errors and their corrections. These validations are enforced by:
- Pre-commit hooks (`.git/hooks/pre-commit`)
- E2E tests (`tests/test_agent_cli_correctness.py`)
- Agent template CLI reference sections

### Wrong Operation Field Name

| ❌ Incorrect JSON | ✅ Correct JSON |
|------------------|----------------|
| `{"op": "ADD", "section": "...", "content": "..."}` | `{"type": "ADD", "section": "...", "content": "..."}` |
| `{"op": "UPDATE", "bullet_id": "..."}` | `{"type": "UPDATE", "bullet_id": "..."}` |
| `{"op": "DEPRECATE", "bullet_id": "..."}` | `{"type": "DEPRECATE", "bullet_id": "..."}` |

**Explanation:** Delta operations use the field name `"type"`, not `"op"`. This is enforced in agent templates and validated by workflow contracts.

### Quick Reference Resources

For comprehensive CLI documentation, see:

- **Complete CLI guide**: `docs/CLI_COMMAND_REFERENCE.md`
  - Full command reference with examples and immediate corrections for MAP CLI command syntax
  - FTS5 query syntax guide
  - Exit codes and troubleshooting
  - Use this as the canonical reference; MAP no longer ships a `map-cli-reference` skill

- **Machine-readable spec**: `docs/CLI_REFERENCE.json`
  - JSON schema for all commands
  - Parameter types and validation rules
  - Error pattern definitions

### Validation Tools

**Pre-commit hook** (`.git/hooks/pre-commit`):
- Blocks commits with incorrect CLI commands in agent templates
- Validates template variables aren't removed
- Runs automatically on `git commit`

**E2E test** (`tests/test_agent_cli_correctness.py`):
- 6 test cases covering common mistakes
- Runs in CI on every PR
- Validates agent templates use correct CLI syntax

**Skip validation** (if absolutely necessary):
```bash
git commit --no-verify  # NOT RECOMMENDED
```

---

## 🔄 Handling Context Compaction

MAP workflows automatically save progress to the `.map/` directory, which persists across context compactions. This ensures your work is never lost, even if the conversation context is cleared.

### Context budget policy

MAP ships a token-aware nudge that tells Claude to run `/compact` *before* quality
starts to degrade — well below Claude Code's built-in 83.5% auto-compact floor.
Pick a policy at `mapify init` time, or edit `.map/config.yaml` later.

| Policy       | When the nudge fires                              | Use this when                          |
| ------------ | ------------------------------------------------- | -------------------------------------- |
| `never`      | never                                             | quality matters more than token cost   |
| `auto`       | last assistant turn input ≥ threshold (default)   | balanced (recommended)                 |
| `aggressive` | last assistant turn input ≥ 0.4 × threshold       | minimise cost on long sessions         |

Default threshold: `120000` tokens (~60% of a 200k Sonnet window). For Opus 1M
projects raise it to `~250000`.

```bash
# At init time:
mapify init my-project --compression auto --compression-threshold 120000
mapify init my-project --compression never           # quality mode
mapify init my-project --compression aggressive      # cost mode

# Or edit .map/config.yaml afterwards:
# compression_policy: auto
# compression_threshold_tokens: 120000
# compression_focus: ""   # appended to the generated /compact command
```

When the threshold is crossed, the `context-meter` hook injects a
`[MAP context-meter] ...` notice with a ready-to-run `/compact` line. The
five-minute cooldown via `.map/<branch>/last-compact.marker` prevents
double-firing right after a built-in auto-compact has already run. For Codex
sessions the same recommendation is emitted to stderr by `map_orchestrator.py`
when invoked with `--transcript-path` (or env `MAPIFY_TRANSCRIPT_PATH`).

Actor prompts built by `build_context_block` enforce a separate hard budget for
the generated `<map_context>` block before it enters the model. The default is
`4000` estimated tokens and keeps current-subtask details plus dependency
summaries ahead of broad plan overview text. If a long workflow genuinely needs
more injected context, set `MAP_CONTEXT_BLOCK_BUDGET_TOKENS=<positive integer>`
for that run; malformed, non-positive, or too-small values fall back to the
default. The minimum accepted override is 128 estimated tokens, which reserves
enough space for the `<map_context>` wrapper and truncation note.

### What is Context Compaction?

Context compaction occurs when Claude's conversation memory reaches its limit. When this happens:
- The conversation history is cleared to free up space
- But your work files on disk remain intact
- MAP **automatically restores your workflow state** in the new session

### Checkpoint Recovery with /map-resume

**How it works:**

MAP Framework uses a `/map-resume` command to recover interrupted workflows. When you start a new session after context exhaustion:

1. **Run `/map-resume`** - Simple command to check for incomplete workflow
2. **View progress summary** - Shows completed and remaining subtasks
3. **Confirm Y/n** - Resume workflow or clear checkpoint and start fresh

**What you'll see:**

When running `/map-resume` with an existing checkpoint (`.map/progress.md`):

```markdown
## Found Incomplete Workflow

**Task:** Implement JWT authentication
**Current Phase:** implementation
**Turn Count:** 12

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks ✅
- [x] **ST-001**: Create User model
- [x] **ST-002**: Implement login endpoint
- [x] **ST-003**: Add token validation middleware

### Remaining Subtasks 📋
- [ ] **ST-004**: Add refresh token logic
- [ ] **ST-005**: Write integration tests

Resume from last checkpoint? [Y/n]
```

**Simple recovery** - Press Y to continue:

```
User: Y

Claude: Resuming workflow from ST-004...
        [continues Actor→Monitor loop for remaining subtasks]
```

**Benefits:**

- ✅ **Explicit recovery** - User controls when to resume
- ✅ **Progress visibility** - See exactly what's done and remaining
- ✅ **Simple Y/n prompt** - No complex options
- ✅ **Cross-session continuity** - Resume in any new conversation

### Security Design

The checkpoint format (`.map/progress.md`) is designed with security in mind:

1. **Path Traversal Prevention**
   - Only allows files within `.map/` directory
   - Resolves symlinks and `../` paths to prevent escaping
   - Rejects absolute paths outside project

2. **Size Bomb Protection**
   - Maximum file size: **256KB** (prevents memory exhaustion)
   - Validates size **before reading** file content
   - Rejects oversized files with clear error message

3. **UTF-8 Encoding Validation**
   - Enforces strict UTF-8 encoding
   - Handles decoding errors gracefully
   - Prevents binary file injection

4. **Content Sanitization**
   - Strips control characters (terminal escape codes, NULL bytes)
   - Preserves newlines and tabs (formatting)
   - Removes: `\x00-\x08`, `\x0b-\x0d`, `\x0e-\x1f`, `\x7f` (DELETE), Unicode control chars

**Why this matters:**

- **Path traversal attacks** - Malicious checkpoint could try to inject `/etc/passwd` or `~/.ssh/id_rsa`
- **Size bombs** - Large files could exhaust memory, causing Claude Code to crash
- **Control character injection** - Terminal escape codes could manipulate Claude's output
- **Encoding exploits** - Binary data could contain executable payloads

**Mitigation:**

The checkpoint format (`.map/progress.md`) is designed with security in mind:
- YAML frontmatter with simple key-value pairs (no code execution)
- Human-readable markdown body (can be visually inspected)
- Small file sizes (workflow state only, not code)
- `/map-resume` command validates checkpoint before resuming

### Manual Recovery (Fallback)

**When to use manual recovery:**

- **Corrupted checkpoint** - `/map-resume` can't parse checkpoint
- **Debugging** - Want to verify checkpoint contents before resuming
- **Explicit control** - Prefer to manually reference files

**Steps:**

1. **Locate checkpoint files** (auto-saved during workflow):

   ```
   .map/progress.md         - Workflow state (YAML frontmatter + markdown)
   .map/*/task_plan_*.md    - Task decomposition with validation criteria
   .map/*/blueprint.json    - Machine-readable subtasks with size/concern contracts
   ```

2. **After compaction**, manually reference files:

   ```
   User: continue MAP workflow
         @.map/progress.md
           @.map/map-to-enchance/task_plan_map-to-enchance.md

   Claude: [reads files]
           Resuming subtask 4: "Add refresh token logic"
           [continues implementation from saved state]
```

### Contract-Sized Subtask Validation

Before implementation starts, MAP validates `.map/<branch>/blueprint.json` with:

```bash
python3 .map/scripts/map_step_runner.py validate_blueprint_contract
```

Each subtask must carry `expected_diff_size`, `concern_type`, `one_logical_step: true`, an `aag_contract`, and testable `validation_criteria`. The blueprint also needs a top-level `coverage_map` that assigns spec acceptance criteria, invariants, and cross-cutting requirements to owner subtasks. Every mapped requirement key must appear as a bracket tag in the owning subtask's `validation_criteria`, for example `VC1 [AC-1]: timeout shows a retryable message`. `large` subtasks require `split_rationale`, and `mixed` concern subtasks require `concern_justification`; otherwise planning stops before Actor can start. This makes oversized, mixed-scope, or untraceable work visible while the plan is cheap to fix, instead of after a reviewer receives an unreviewable diff.

### Before/After Comparison

| Without MAP Recovery | With /map-resume ✨ |
|---------------------|---------------------|
| Lose all workflow context | Context preserved in checkpoint |
| Start over from scratch | Resume from last completed subtask |
| Copy file paths manually | Single command recovery |
| Paste paths with `@` prefix | Simple Y/n confirmation |
| **Workflow abandoned** | **Workflow continues** |

**Example Workflow:**

**Without MAP Recovery:**
```
[Context gets low]
[Compaction happens]
[New session starts]
User: what was I working on?
Claude: I don't have context from your previous session...
[User has to explain everything again]
```

**With /map-resume:**
```
[Context gets low]
[Compaction happens]
[New session starts]
User: /map-resume
Claude: ## Found Incomplete Workflow
        3/5 subtasks completed (60%)
        Resume from last checkpoint? [Y/n]
User: Y
Claude: Resuming workflow from ST-004...
        [continues Actor→Monitor loop]
```

### Troubleshooting

#### /map-resume not working?

**Symptoms:**
- `/map-resume` says "No Workflow in Progress"
- Checkpoint exists but won't load

**Diagnosis:**

1. **Check if checkpoint file exists:**
   ```bash
   ls -lh .map/progress.md
   ```
   - If missing: No checkpoint to restore (expected for new projects)
   - If exists: Proceed to step 2

2. **Check checkpoint file contents:**
   ```bash
   head -20 .map/progress.md
   ```
   - Should contain valid YAML frontmatter with `task_plan:`, `current_phase:`, etc.
   - If malformed: Delete and start fresh with `/map-efficient`

3. **Resume workflow:**
   ```bash
   /map-resume
   ```
   - Shows progress summary and asks for confirmation
   - Y to resume, n to clear checkpoint and start fresh

**Common issues:**

| Issue | Cause | Solution |
|-------|-------|----------|
| No checkpoint found | Workflow not started or completed | Start new workflow with `/map-efficient` |
| YAML parse error | Corrupted checkpoint | Delete `.map/progress.md` and start fresh |
| Missing task plan | Task plan file deleted | Delete checkpoint and restart workflow |

**Fallback:**

If `/map-resume` continues to fail, use [Manual Recovery](#manual-recovery-fallback) workflow.

#### Safe re-initialization with merge behavior

**Key Feature:** Running `mapify init` preserves your customizations when updating MAP Framework hooks.

**What gets preserved:**
- ✅ Your custom hooks (UserPromptSubmit, PreToolUse, Stop, etc.)
- ✅ Your permissions settings
- ✅ Your top-level configuration keys (description, customKey, etc.)

**What gets added:**
- ✅ New MAP Framework hooks (if they don't already exist)
- ✅ Updated hook scripts from templates

**How it works:**

```bash
# Safe to run multiple times - your customizations won't be lost
mapify init --force
```

**Deduplication strategy:**

MAP Framework uses the `matcher` field to identify duplicate hook groups:

| Hook Scenario | Behavior |
|---------------|----------|
| User has `matcher: "custom-pattern"` | Preserved (not in template) |
| Template has `matcher: "Bash\\(.*\\)"` | Added only if user doesn't have this matcher |
| Both have same `matcher: "Edit\\|Write"` | User's version preserved, template not added |
| Hook has no `matcher` or `matcher: ""` | Full JSON comparison used for deduplication |

**Example:**

Your existing `.claude/settings.json`:
```json
{
  "permissions": {
    "allow": ["Bash(git status:*)", "Bash(custom-command:*)"]
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "custom-pattern",
        "description": "User's custom hook",
        "hooks": [{"type": "command", "command": "python3 /custom/script.py"}]
      }
    ]
  }
}
```

After `mapify init`:
```json
{
  "permissions": {
    "allow": ["Bash(git status:*)", "Bash(custom-command:*)"]  // ✅ Preserved
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "custom-pattern",  // ✅ Your custom hook preserved
        "description": "User's custom hook",
        "hooks": [{"type": "command", "command": "python3 /custom/script.py"}]
      },
      {
        "matcher": "",  // ✅ MAP Framework hook added
        "description": "Enhance prompts with clarification and pattern context",
        "hooks": [
          {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/improve-prompt.py"}
        ]
      }
    ]
  }
}
```

**When to re-run `mapify init`:**
- ✅ After MAP Framework updates (to get new hooks)
- ✅ If hooks are not working (safe to repair)
- ✅ To update hook scripts without losing customizations
- ⚠️ Your customizations are ALWAYS preserved

#### How to verify auto-recovery is working

**Test sequence:**

1. **Create a test task:**
   ```bash
   /map-efficient "add test function to app.py"
   ```

2. **Wait for first subtask completion** - Checkpoint should be created at `.map/progress.md`

3. **Start NEW conversation** (simulate compaction):
   - Open new chat or use "Clear conversation" (if available)

4. **Run recovery command:**
   ```bash
   /map-resume
   ```

5. **Verify restoration:**
   - Look for "Found Incomplete Workflow" header
   - Check plan shows correct progress (e.g., "1/3 completed")
   - Press Y to continue

**Expected behavior:**

- ✅ `/map-resume` detects checkpoint file
- ✅ Progress summary shows completed/remaining subtasks
- ✅ Y/n prompt allows user control
- ✅ Workflow continues from last incomplete subtask

### Key Points

- ✅ **Explicit recovery** - `/map-resume` command to restore workflow state
- ✅ **Progress auto-saves** - Every workflow step saves to disk
- ✅ **Simple checkpoint format** - YAML frontmatter + markdown body
- ✅ **No manual checkpointing required** - Files update automatically during workflow
- ✅ **Files persist forever** - They're on your filesystem, not in conversation memory
- ✅ **Cross-session recovery** - Resume in any new conversation with `/map-resume`
- ✅ **Manual fallback available** - Reference `.map/` files directly if needed

### Architecture

MAP uses file-based persistence with automatic injection:

**Files:**
- `.map/progress.md` - Workflow checkpoint with YAML frontmatter (machine-readable) + markdown body (human-readable)
- `.map/*/task_plan_*.md` - Task decomposition with validation criteria
- `.map/dev_docs/context.md` - Project context
- `.map/dev_docs/tasks.md` - Task checklist

**Recovery command:**
- `/map-resume` - Detects checkpoint and offers to resume incomplete workflow

These files survive compaction because they're stored on disk, not in conversation memory.

**Technical Details:**

For implementation details on checkpoint format and compaction resilience architecture, see:
- [ARCHITECTURE.md - Context Engineering](ARCHITECTURE.md#context-engineering) - Recitation Pattern and Compaction Resilience
- `src/mapify_cli/templates/map/scripts/map_orchestrator.py` - StepState class with step_state.json persistence

## 🔍 Dependency Validation

The dependency validation utility (`scripts/validate-dependencies.py`) ensures TaskDecomposer output has valid dependency graphs before execution. It prevents workflow failures by detecting:

- **Circular dependencies** — Tasks that create impossible execution loops (A → B → C → A)
- **Forward references** — Dependencies on non-existent tasks
- **Self-dependencies** — Tasks that depend on themselves
- **Orphaned tasks** — Isolated tasks with no incoming or outgoing dependencies

### Basic Usage

**Recommended (after `pip install mapify-cli`):**

```bash
# Validate from file
mapify validate graph decomposer-output.json

# Output in text format (human-readable)
mapify validate graph decomposer-output.json -f text

# JSON format (default, for CI/CD)
mapify validate graph decomposer-output.json -f json

# Validate from stdin
cat decomposer-output.json | mapify validate graph
```

**For development (using script directly):**

```bash
# Validate from stdin
cat decomposer-output.json | python scripts/validate-dependencies.py

# Validate from file
python scripts/validate-dependencies.py decomposer-output.json

# Output in text format (human-readable)
python scripts/validate-dependencies.py -f text decomposer-output.json

# JSON format (default, for CI/CD)
python scripts/validate-dependencies.py -f json decomposer-output.json
```

### Visualization Mode

Display ASCII dependency tree to understand task execution order:

**Recommended (mapify CLI):**

```bash
# Show dependency tree with colors
mapify validate graph decomposer-output.json --visualize

# Show tree without colors (for logs/CI)
mapify validate graph decomposer-output.json --visualize --no-color
```

**For development (direct script):**

```bash
# Show dependency tree with colors
python scripts/validate-dependencies.py --visualize decomposer-output.json

# Show tree without colors (for logs/CI)
python scripts/validate-dependencies.py --visualize --no-color decomposer-output.json
```

**Example visualization output:**

```
Task Dependency Tree:
Task 1: Setup environment
├─ Task 2: Install dependencies
│  └─ Task 4: Run tests
└─ Task 3: Configure database
   └─ Task 4: Run tests
```

### Exit Codes

The validator uses standard exit codes for automation:

| Exit Code | Meaning | CI/CD Action |
|-----------|---------|--------------|
| `0` | Valid graph (no critical errors) | Continue workflow |
| `1` | Invalid graph (critical errors found) OR warnings with `--strict` flag | Fail build |
| `2` | Invalid input (malformed JSON or missing required fields) | Fix input format |

> **Note**: By default, **warnings** (e.g., orphaned tasks) result in exit code `0` and **do not** fail CI/CD builds. Only **critical errors** (circular dependencies, forward references, self-dependencies) cause exit code `1`. To enforce strict validation where warnings also fail the build, use the `--strict` flag. Use `--format text` to see issue severity levels.

**CI/CD Integration Examples:**

```bash
# Default mode: Only critical errors fail the build
mapify validate graph plan.json || exit 1
echo "✓ Task graph has no critical errors"

# Strict mode: Warnings also fail the build
mapify validate graph --strict plan.json || exit 1
echo "✓ Task graph is perfect (no warnings or errors)"

# Alternative: using direct script (for development/testing)
python scripts/validate-dependencies.py plan.json || exit 1
echo "✓ Task graph validated successfully"
```

### Integration with TaskDecomposer

Validate TaskDecomposer output before starting workflow:

```bash
# Step 1: Decompose task
/map-efficient implement user authentication

# Step 2: Review TaskDecomposer output
# (orchestrator saves to .claude/decomposer-output.json)

# Step 3: Validate before execution (recommended)
mapify validate graph .claude/decomposer-output.json

# Alternative (for development): use direct script
python scripts/validate-dependencies.py .claude/decomposer-output.json

# Step 4: If valid, orchestrator proceeds automatically
```

**Note:** MAP Framework orchestrators can integrate this validation step to prevent execution of invalid task graphs.

### Sample TaskDecomposer JSON

```json
{
  "subtasks": [
    {
      "id": 1,
      "title": "Setup authentication middleware",
      "description": "Create Express middleware for JWT validation",
      "dependencies": []
    },
    {
      "id": 2,
      "title": "Implement login endpoint",
      "description": "POST /api/login with email/password",
      "dependencies": [1]
    },
    {
      "id": 3,
      "title": "Add refresh token logic",
      "description": "Implement token refresh endpoint",
      "dependencies": [1, 2]
    }
  ]
}
```

### Validation Output Examples

**Valid graph (JSON format):**

```json
{
  "valid": true,
  "issues": [],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 0,
    "warnings": 0
  }
}
```

**Invalid graph with circular dependency (JSON format):**

```json
{
  "valid": false,
  "issues": [
    {
      "type": "circular_dependency",
      "severity": "critical",
      "affected_tasks": [1, 2, 3],
      "message": "Circular dependency detected: 1 → 2 → 3 → 1"
    }
  ],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 1,
    "warnings": 0
  }
}
```

**Text format output:**

```
⚠️  Validation Failed

Issues Found:
  [CRITICAL] Circular dependency detected: 1 → 2 → 3 → 1
    Affected tasks: 1, 2, 3

Summary:
  Total tasks: 3
  Critical issues: 1
  Warnings: 0
```

### Command-Line Flags Reference

| Flag | Short | Values | Default | Description |
|------|-------|--------|---------|-------------|
| `--format` | `-f` | `json`, `text` | `json` | Output format for validation results |
| `--visualize` | — | — | — | Display ASCII dependency tree |
| `--no-color` | — | — | — | Disable ANSI colors in visualization |
| `--strict` | — | — | — | Fail on warnings (e.g., orphaned tasks), not just critical errors |
| `--help` | `-h` | — | — | Show help message and examples |

### Validation Best Practices

1. **Always validate in CI/CD** — Add validation step before task execution
2. **Use JSON format for automation** — Machine-readable output for scripts
3. **Use text format for debugging** — Human-readable output for investigation
4. **Visualize complex graphs** — Use `--visualize` to understand execution order
5. **Check exit codes** — Use `$?` in shell scripts for automated validation

## 🔀 Workflow Variants

MAP Framework offers three primary implementation workflows with different trade-offs between token usage, quality assurance, and learning. A fourth workflow (`/map-tdd`) adds test-first development. A fifth (`/map-task`) executes a single subtask from an existing plan. Additional supporting workflows (`/map-debug`, `/map-review`, `/map-check`, `/map-plan`, `/map-release`, `/map-resume`, `/map-learn`) are documented in their respective sections.

Each shipped task skill now declares an explicit effort and parallelism policy near the top of its `SKILL.md` body. Lightweight workflows (`/map-fast`, `/map-check`, `/map-resume`) use `thinking_policy: low/direct`; implementation and learning workflows use `medium/adaptive`; planning, review, and release use `high/adaptive`. The paired `parallel_tool_policy` tells the provider when fan-out is safe, for example independent checks only, guarded `/map-efficient` waves only, or the single `/map-review` reviewer fan-out. This keeps simple commands from overthinking while preserving deeper analysis where it protects correctness or release safety.

### Comparison Table

| Feature | /map-efficient ⭐ | /map-fast ⚠️ |
|---------|-------------------|--------------|
| **Agents Used** | 3-4 (task-decomposer, actor, monitor, final-verifier)) | 3 (minimal) |
| **Token Cost** | **Baseline** | 40-50% less |
| **Learning** | Via `/map-learn` | ❌ None |
| **Quality Gates** | Essential agents + Final-Verifier | Basic only |
| **Impact Analysis** | ✅ Conditional (Predictor) | ❌ Never |
| **Multi-Variant** | ⚠️ Conditional (Self-MoA) | ❌ Never |
| **Synthesis Model** | Synthesizer (sonnet) | N/A |
| **Knowledge Updates** | Via `/map-learn` | ❌ None |
| **Best For** | **Most tasks** | Throwaway only |
| **Production Ready** | ✅ Yes | ❌ NO |

### Decision Guide: Which Workflow Should I Use?

#### Use `/map-efficient` (RECOMMENDED) ⭐

**When:**
- ✅ Production code where token costs matter
- ✅ Well-understood features with low-medium risk
- ✅ Iterative development with frequent workflows
- ✅ You want learning without excessive token usage
- ✅ Standard CRUD operations, UI components
- ✅ Refactoring with clear scope

**Why it's better than /map-fast:**
- Learning available via `/map-learn` after workflow (Reflector)
- Conditional Predictor catches high-risk issues
- Final-Verifier provides adversarial verification
- Only 10% less token savings but much safer

**Example use cases:**
```bash
# Standard feature development
/map-efficient implement user profile editing with form validation

# API development
/map-efficient create REST API endpoints for product management

# UI components
/map-efficient build responsive navigation menu with mobile support
```

#### Use `/map-efficient --self-moa` (High-Quality Mode)

**When:**
- 🔒 Security-critical functionality (authentication, authorization)
- 🔒 Complex features with multiple valid approaches
- 🔒 High-risk changes affecting many files/modules

**What `--self-moa` adds:**
- Generates 3 variants (security/performance/simplicity focus)
- Synthesizes best parts from each variant
- Higher quality for critical code

**Example use cases:**
```bash
# Security-critical
/map-efficient --self-moa implement JWT authentication with refresh tokens

# Complex feature
/map-efficient --self-moa build real-time chat system with WebSocket support
```

#### Use `/map-fast` (Minimal) ⚠️

**ONLY when:**
- ✅ Small, low-risk changes with clear acceptance criteria
- ✅ Localized fixes with minimal blast radius
- ✅ Time-sensitive changes where you still require production-quality output

**⚠️ AVOID for:**
- ❌ Security-sensitive functionality
- ❌ Broad refactors or multi-module changes
- ❌ Ambiguous requirements or high uncertainty
- ❌ Changes requiring careful impact analysis

**Why it's dangerous:**
- No impact analysis → Breaking changes undetected
- No learning → Knowledge base stays empty, same mistakes repeated
- No quality scoring → Security/performance issues missed
- No knowledge integration → Knowledge lost forever

**Execution model:** Actor edits files directly with Edit/Write tools and returns a compact summary (`files_changed`, `tests_run`, `remaining_risks`). Monitor then reads the written files from the repo; `/map-fast` no longer asks Actor to serialize full file contents for a separate apply step.

**Example use cases (acceptable):**
```bash
# Small UI tweak
/map-fast Adjust button spacing in settings page

# Localized bug fix
/map-fast Fix nil check in request handler

# Minor docs automation
/map-fast Update CLI help text formatting
```

#### Use `/map-tdd` (Test-Driven Development)

**When:** Correctness-critical features where you need tests to validate behavior independently of implementation.

**Key insight:** When AI writes tests alongside code, tests tend to confirm the implementation (including its bugs) rather than validate the specification. TDD mode separates test authoring from implementation.

**Flow:**
```
DECOMPOSE → TEST_WRITER (tests from spec) → TEST_FAIL_GATE (verify Red) → ACTOR (code only) → MONITOR
```

**Usage:**
```bash
# Standalone TDD workflow
/map-tdd Add payment processing with refund support

# Or via --tdd flag on /map-efficient
/map-efficient --tdd Add JWT authentication with refresh tokens
```

**Best for:**
- Auth, payments, data integrity features
- Features with clear acceptance criteria in the spec
- When previous AI-generated tests missed real bugs

**Token cost:** ~20-30% higher than /map-efficient (extra Actor call for test-writing phase).

#### Use `/map-task` (Single Subtask Execution)

**When:** You have a plan from `/map-plan` and want to execute just one specific subtask.

**Prerequisites:** Run `/map-plan` first to create a task decomposition.

**Usage:**
```bash
# Execute a single subtask from the plan
/map-task ST-001

# Write TDD tests for a specific subtask
/map-tdd ST-001

# Typical workflow: plan first, then pick subtasks
/map-plan Add user authentication
/map-task ST-001   # implement first subtask
/map-tdd ST-002    # TDD for second subtask
/map-task ST-003   # implement third subtask
```

**Best for:**
- Fine-grained control over execution order
- Parallelizing subtasks across multiple sessions
- Resuming work on a specific subtask after context reset
- Cherry-picking which subtasks to implement now vs. later

### Real-World Token Usage Examples

**Small Task (1-2 subtasks):**
- `/map-efficient`: ~12-20K tokens (baseline)
- `/map-efficient --self-moa`: ~25-35K tokens (3 variants)
- `/map-fast`: ~8-12K tokens (minimal)

**Medium Task (3-5 subtasks):**
- `/map-efficient`: ~45-60K tokens (baseline)
- `/map-efficient --self-moa`: ~100-130K tokens (3 variants)
- `/map-fast`: ~25-35K tokens (minimal)

**Large Task (6-8 subtasks):**
- `/map-efficient`: ~90-120K tokens (baseline)
- `/map-efficient --self-moa`: ~200-260K tokens (3 variants)
- `/map-fast`: ~50-70K tokens (minimal)

**Cost at $3/M input, $15/M output (Claude Sonnet):**

| Task Size | /map-efficient | /map-fast |
|-----------|----------------|-----------|
| Small | $0.18-0.30 | $0.12-0.18 |
| Medium | $0.68-0.90 | $0.38-0.53 |
| Large | $1.35-1.80 | $0.75-1.05 |

**For teams running 10 workflows/day with /map-efficient:**
- Daily cost: ~$13.50
- /map-fast would save ~40% but loses learning

### How /map-efficient Works

**Key Optimizations:**

1. **Conditional Predictor** (5-10% savings)
   - TaskDecomposer assigns risk_level to each subtask
   - Predictor only called if risk_level='high' or Monitor flags issues
   - Low-risk tasks (simple CRUD, UI updates) skip impact analysis

2. **Learning Decoupled to /map-learn** (token savings during main workflow)
   - Reflector is NOT called during /map-efficient execution
   - Run `/map-learn` after workflow completes to extract patterns
   - Reflector then analyzes ALL subtasks together (batched, more holistic insights)

3. **Evaluator Not Invoked** (8-12% savings)
   - Monitor provides sufficient validation for most tasks
   - The Evaluator agent is skipped entirely (not just its scoring)
   - Evaluator only runs in `/map-debug` and `/map-review`
   - Quality still ensured by Monitor's comprehensive checks

**What's Preserved:**
- ✅ Learning available via `/map-learn` (Reflector, optional after workflow)
- ✅ Tests gate + Linter gate per subtask
- ✅ Final-Verifier (adversarial verification at end)
- ✅ Essential quality gates (Monitor validation)
- ✅ Impact analysis (conditional Predictor when needed)

### Workflow Selection Flowchart

```
START: I need to implement a feature
  |
  ├─ Is it a small, low-risk change?
  |    └─ YES → /map-fast
  |    └─ NO → Continue
  |
  ├─ Is it security-critical or first-time complex feature?
  |    └─ YES → /map-efficient (maximum QA)
  |    └─ NO → Continue
  |
  ├─ Do I care about token costs?
  |    └─ NO → /map-efficient (best quality)
  |    └─ YES → /map-efficient ⭐ (RECOMMENDED)
```

### When to Use `--self-moa` Flag

**Add `--self-moa` to /map-efficient for:**
- First implementation of authentication/authorization
- Database migrations affecting multiple tables
- Breaking API changes
- Any feature where failure is costly

```bash
# Standard feature
/map-efficient implement user dashboard

# High-risk feature (use --self-moa for 3-variant synthesis)
/map-efficient --self-moa implement user dashboard with role-based access
```

### Common Misconceptions

**❌ Misconception:** "/map-fast is 50% cheaper, so it's always better for saving money"
**✅ Reality:** /map-fast defeats MAP's purpose (no learning = repeat mistakes = waste tokens long-term). Use /map-efficient instead.

**❌ Misconception:** "/map-efficient skips quality checks"
**✅ Reality:** Monitor still validates every subtask. Evaluator is not invoked (it only runs in /map-debug and /map-review), but Tests gate, Linter gate, and Final-Verifier ensure quality.

**❌ Misconception:** "Learning via /map-learn is inferior to per-subtask learning"
**✅ Reality:** /map-learn runs Reflector after the workflow completes, analyzing ALL subtasks together. This batched approach sees patterns ACROSS subtasks, often producing better insights than isolated per-subtask analysis.

## 🎯 Best Practices

### 1. Actor Quality Checklist (NEW in v2.3.0)

The Actor agent now includes a 10-item Quality Checklist for self-review before submitting implementations to Monitor. Using this checklist reduces iteration cycles by 30-40%.

**Benefits:**
- Catches common issues early (before Monitor validation)
- Reduces Monitor iterations from 2-3 down to 1
- Speeds up overall workflow completion
- Trains Actor to internalize quality criteria

**The checklist covers:**
1. Code style compliance (follows project standards)
2. Explicit error handling (no silent failures)
3. Security review (SQL injection, XSS, sensitive data)
4. Test case identification (happy path + edge cases)
5. MCP tools usage (deepwiki, sequential-thinking)
6. Template variable preservation (orchestration compatibility)
7. Trade-offs documentation (decision rationale)
8. Complete implementations (no ellipsis or placeholders)
9. Dependency justification (no unnecessary libraries)

**How it works:**
- Actor performs self-review before submission
- Critical Reminders section references the checklist
- Monitor validation is faster (fewer common issues)

**Learn more:** See `.claude/agents/actor.md` lines 1102-1142 for the complete checklist.

### 2. Clear Requirements

Always provide specific, detailed requirements to get the best results.

```bash
# Good ✅
"Implement registration with email validation, password strength check (8+ chars, 1 number), send confirmation"

# Bad ❌
"Add registration"
```

**Why it matters:**

- Clear requirements lead to better task decomposition
- Reduces Actor-Monitor retry cycles
- Produces more maintainable code

### 2. Incremental Approach

Break large features into phases to maintain focus and quality:

- **Phase 1:** Core functionality
- **Phase 2:** Edge cases and error handling
- **Phase 3:** Optimization

**Example workflow:**

```bash
# Phase 1: Core implementation
/map-efficient implement basic user authentication with login/logout

# Phase 2: Enhanced security
/map-efficient add password reset and email verification to authentication

# Phase 3: Performance tuning
/map-efficient optimize authentication to use Redis session caching
```

### 3. Provide Context

Always specify relevant project context to improve solution quality:

**Include:**

- Technology stack (e.g., "using Express.js with TypeScript")
- Existing patterns (e.g., "follow the service-repository pattern used in UserService")
- Constraints (e.g., "must work with PostgreSQL 12+")
- Performance requirements (e.g., "handle 1000 requests/second")

**Example:**

```bash
/map-efficient implement product search using Elasticsearch.
Stack: Node.js + Express + PostgreSQL.
Follow existing repository pattern in ProductRepository.
Must handle 500 concurrent searches with <200ms response time.
```

## 💰 Cost Optimization

MAP Framework supports intelligent model selection per agent to balance capability and cost.

### Model Distribution Strategy (Updated Nov 2025)

> **Note:** In v3.0+, Predictor and Evaluator were upgraded from `haiku` to `sonnet` for better analysis quality.

| Agent | Model | Reason | Cost Impact |
|-------|-------|--------|-------------|
| **Predictor** | sonnet | Impact analysis requires complex reasoning (upgraded from haiku) | ➡️ |
| **Evaluator** | sonnet | Evaluation requires nuanced judgment (upgraded from haiku) | ➡️ |
| **Actor** | sonnet | Code generation quality is critical | ➡️ |
| **Monitor** | sonnet | Quality validation requires thoroughness | ➡️ |
| **TaskDecomposer** | sonnet | Requires good understanding of requirements | ➡️ |
| **Reflector** | sonnet | Pattern extraction needs reasoning | ➡️ |
| **DocumentationReviewer** | sonnet | Documentation analysis needs thoroughness | ➡️ |

### Cost Impact of Model Upgrades

The upgrade of Predictor and Evaluator from haiku to sonnet provides:

- **Better analysis quality**: More accurate impact predictions and quality evaluations
- **Higher costs**: ~12x increase per agent call for predictor/evaluator
  - Input tokens: $0.25/1M (haiku) → $3/1M (sonnet)
  - Output tokens: $1.25/1M (haiku) → $15/1M (sonnet)
- **Per-workflow impact**: ~$0.03 → ~$0.36 for typical 4-subtask feature

### Cost Mitigation Strategies

**1. Use `/map-efficient` workflow (RECOMMENDED)**
- Skips Evaluator per subtask (Monitor provides sufficient validation)
- Conditional Predictor (only called for high-risk changes)
- Reflector available via `/map-learn` after workflow
- **Token savings: 30-40%**

**2. Use `/map-fast` for small, low-risk changes**
- Minimal agent sequence: TaskDecomposer → Actor → Monitor
- Skips: Predictor, Evaluator, Reflector
- **Token savings: 40-50%** (but no learning!)

### How It Works

Agents automatically use their configured model when invoked via slash commands:

```bash
# Standard workflow - conditional predictor, optional learning via /map-learn
/map-efficient implement authentication  # Recommended for most tasks

# Fast workflow - minimal agents, no learning
/map-fast Update error message wording
```

### Cost Comparison Example

**Scenario:** Implement a feature with 4 subtasks

| Workflow | TaskDecomposer | Actor | Monitor | Predictor | Synthesizer | Total Cost* |
|----------|----------------|-------|---------|-----------|-------------|-------------|
| `/map-efficient` | sonnet | sonnet (4x) | sonnet (4x) | sonnet (0-2x) | skip | ~$0.22 |
| `/map-efficient --self-moa` | sonnet | sonnet (12x) | sonnet (12x) | sonnet (0-2x) | sonnet (4x) | ~$0.45 |
| `/map-fast` | sonnet | sonnet (4x) | sonnet (4x) | skip | skip | ~$0.12 |

*Approximate costs based on typical token usage. Learning via `/map-learn` adds ~$0.05-0.10.

**Key differences:**
- `/map-efficient`: Standard workflow, conditional Self-MoA
- `/map-efficient --self-moa`: Forces 3-variant generation + synthesis
- `/map-fast`: Minimal, NO learning support

---

## Additional Resources

- **[README.md](../README.md)** — Project overview and installation
- **[INSTALL.md](INSTALL.md)** — Detailed installation instructions
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Technical architecture details

---

## Skills System

MAP's Claude Code slash surfaces are implemented as skills under `.claude/skills/map-*/SKILL.md`. Skills are not agents, but they can be more than passive documentation: task skills define slash workflows that call agents, run validation, and write artifacts.

### Skill Classes

`skill-rules.json` declares a `skillClass` for every shipped skill:

| Class | Use For | Runtime Boundary |
|-------|---------|------------------|
| `reference` | Conventions, heuristics, examples, and decision support | Loads knowledge only; does not own mutation workflows |
| `task` | Manual slash workflows such as `/map-efficient`, `/map-review`, and `/map-learn` | May orchestrate agents, run checks, and write branch artifacts when invoked |
| `hybrid` | Reference guidance plus installed runtime helpers, currently `map-state` | Must list `runtimeEffects` so hook/script side effects are explicit |

Current MAP installs classify all slash workflows as `task` skills. `map-state` is `hybrid` because its `SKILL.md` explains branch-scoped planning while its bundled hooks/scripts surface focus and completion checks around `.map/<branch>/` artifacts.

### map-state

`map-state` provides persistent session state for MAP workflows using file-based planning.

Use it for long workflows, multi-phase projects, complex features, team handoffs, and audit trails. Do not use it for trivial one-shot edits or short single-session fixes.

Runtime effects:

- Creates and reads branch-scoped `.map/<branch>/` planning artifacts when its scripts are invoked.
- Installs hooks that display current focus before write/edit/bash actions and check terminal state before exit.
- Keeps workflow state in files such as `task_plan_<branch>.md`, `findings_<branch>.md`, `progress_<branch>.md`, and `step_state.json`.

Initialization script:

```bash
.claude/skills/map-state/scripts/init-session.sh
```

Terminal states are `complete`, `blocked`, `won't_do`, and `superseded`.

### Task Skills

Task skills behave like MAP slash workflows. They are manually invoked by the user and normally advertise an `argument-hint` in frontmatter so the provider UI shows the invocation shape.

Examples:

- `/map-plan` decomposes non-trivial work and records workflow fit.
- `/map-efficient` implements scoped work through Actor/Monitor loops.
- `/map-review` builds a review bundle and launches reviewer agents.
- `/map-learn` consumes a workflow handoff and writes reusable learned rules.

### Skills vs Agents

| Skills | Agents |
|--------|--------|
| Define provider-facing slash surfaces, instructions, policies, hooks, scripts, and supporting files | Perform specialized analysis, implementation, review, or learning work |
| May call agents when the skill is a task workflow | Are launched by skills or commands through the Task tool |
| Live under `.claude/skills/` in Claude installs | Live under `.claude/agents/` |

### Creating Custom Skills

See `.claude/skills/README.md` for:

- Skill structure (`SKILL.md` plus supporting files)
- `skillClass` taxonomy and `runtimeEffects` guidance
- Trigger configuration in `skill-rules.json`
- Template sync and validation commands

### Provider Skill IR Audit

MAP's shipped provider skills remain hand-authored, but maintainers can validate their release shape through a compile-time intermediate representation:

```bash
python -m mapify_cli.skill_ir \
  src/mapify_cli/templates/skills \
  src/mapify_cli/templates/codex/skills
```

The audit reads Claude and Codex `SKILL.md` files, records provider, name, invocation mode, allowed tools, bundled supporting-file links, extracted safety constraints, and a SHA-256 content hash. It exits non-zero when a template introduces unsupported frontmatter, links to a missing bundled reference, or contains hidden instruction-override wording. This catches provider-surface drift before `mapify init` installs the skills into user repositories.

---

## 🔒 Security Model: Three-Layer Defense

MAP Framework implements defense-in-depth security via three complementary layers.

### Layer 1: Behavioral Rules (CLAUDE.md)

Guidelines in `.claude/CLAUDE.md` that guide agent behavior:
- NEVER write code as orchestrator
- NEVER commit .env files

**Enforcement:** Soft (relies on agent compliance)

### Layer 2: Permissions (settings.json)

Access control rules in `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "Write(./.env*)",
      "Write(**/*credentials*)",
      "Write(**/*secret*)",
      "Bash(rm:-rf)",
      "Bash(git:push:--force:origin:main)"
    ],
    "allow": [
      "Bash(mapify:*)",
      "Bash(pytest:*)",
      "Bash(make:lint)"
    ]
  }
}
```

**Enforcement:** Medium (tool-level blocking with bypass risk)

### Layer 3: Hooks (Deterministic Enforcement)

PreToolUse and Stop hooks that run before/after tool execution:

| Hook | Type | Purpose |
|------|------|---------|
| `block-secrets.py` | PreToolUse | Blocks access to .env, credentials, private keys |
| `block-dangerous.sh` | PreToolUse | Blocks rm -rf, force push to main, git reset --hard |
| `end-of-turn.sh` | Stop | Lints code, scans for secrets in staging |

**Enforcement:** Hard (deterministic exit codes)

### How the Layers Work Together

```
User: "Edit .env file"

Layer 1 (CLAUDE.md): Agent should know not to edit .env
    ↓ (but agent might miss this)
Layer 2 (settings.json): permissions.deny blocks Edit(./.env*)
    ↓ (but might be bypassed via path traversal)
Layer 3 (block-secrets.py): Hook intercepts, returns exit 2
    → BLOCKED with clear error message
```

### Security Hooks in Detail

#### block-secrets.py (PreToolUse)

Blocks Read/Edit/Write operations on sensitive files:

**Blocked patterns:**
- `.env`, `.env.local`, `.env.production`
- `credentials.json`, `secrets.yaml`
- Private keys (`id_rsa`, `*_private.key`)
- AWS credentials, GCP service accounts

**Example:**
```bash
# Attempting to read .env
Read('.env')
→ Exit 2: "Blocked: sensitive file detected (.env)"
```

#### block-dangerous.sh (PreToolUse)

Blocks dangerous Bash commands:

**Blocked patterns:**
- `rm -rf /` or `rm -rf *`
- `git push --force origin main`
- `git push --force origin master`
- `git reset --hard`

**Allowed:**
- `rm -rf ./node_modules` (scoped deletion)
- `git push --force origin feature-branch` (non-main branch)
- `git reset --soft` (non-hard reset)

#### end-of-turn.sh (Stop)

Quality gate that runs after Claude finishes responding:

**Checks performed:**
1. **Language-specific linting:**
   - Python: runs `ruff` if available
   - Node.js: runs `npm run lint` if available
   - Go: runs `go vet` and `staticcheck`
   - Rust: runs `cargo clippy`

2. **Secret scanning:** Detects hardcoded secrets in staged files
3. **.env check:** Warns if .env files are staged for commit

**Exit codes:**
- `0` = No issues
- `1` = Warnings (non-blocking)
- `2` = Critical issues (blocks and feeds to Claude)

### Customizing Security

**Per-project customization:**

Edit `.claude/settings.json` for project-specific rules:
```json
{
  "permissions": {
    "allow": [
      "Bash(docker:*)",  // Allow docker commands
      "Edit(./config/*)" // Allow editing config
    ]
  }
}
```

**User overrides:**

Create `.claude/settings.local.json` (gitignored) for personal overrides.

---

## 📊 Verification Results and Early Termination

MAP Framework tracks verification results from hooks and supports early workflow termination with the `won't_do` status.

### Verification Results Tracking

The end-of-turn hook (`end-of-turn.sh`) records verification results to `.map/verification_results_<branch>.json`. This provides machine-readable verification status for CI/CD integration.

**File location:** `.map/verification_results_<branch>.json`

**Example content:**
```json
{
  "overall": "pass",
  "recipes": [
    {
      "id": "check_ruff",
      "status": "pass",
      "summary": "ruff passed",
      "duration_ms": 1200
    },
    {
      "id": "check_secrets",
      "status": "skipped",
      "summary": "No staged files to check",
      "duration_ms": 50,
      "skip_reason": "No staged files"
    },
    {
      "id": "check_mypy",
      "status": "fail",
      "summary": "mypy failed",
      "duration_ms": 3500
    }
  ]
}
```

### Recipe Status Values

| Status | Meaning | Example |
|--------|---------|---------|
| `pass` | Check completed successfully | Linter found no issues |
| `fail` | Check found problems | Type errors detected |
| `skipped` | Check was intentionally skipped | No staged files to scan |

### Overall Status Aggregation

The `overall` field follows strict aggregation rules:

| Condition | Overall Status |
|-----------|----------------|
| ANY recipe is `fail` | `fail` |
| ALL recipes are `pass` | `pass` |
| Otherwise (mixed, empty, all skipped) | `unknown` |

### Skipped Status Explained

Checks return `skipped` when they cannot run due to missing prerequisites:

**Common skip scenarios:**
- `check_secrets`: No staged files to check
- `check_mypy`: No mypy configuration found
- `npm lint`: `node_modules` directory missing
- `cargo clippy`: Not in a Rust project

**Example skipped result:**
```json
{
  "id": "check_secrets",
  "status": "skipped",
  "summary": "No staged files to check",
  "duration_ms": 50,
  "skip_reason": "No files were staged for commit"
}
```

### Hooks Contract: When Hooks Block

**Critical:** Hooks only return exit code 2 (blocking) for **security-critical issues**:

| Blocking (Exit 2) | Non-Blocking (Exit 0-1) |
|-------------------|-------------------------|
| Hardcoded secrets in staged files | Linting failures |
| `.env` file staged for commit | Type errors |
| Dangerous commands (rm -rf /, force push main) | Formatting issues |
| Access to credential files | Test failures |

**Why this matters:**
- Exit 2 stops Claude and feeds stderr back for correction
- Exit 1 shows warning but continues
- Exit 0 passes silently

**Design principle:** Quality checks (linting, types) should inform, not block. Only security violations warrant blocking.

### Early Termination with `won't_do` Status

When a user decides to end a workflow early (before all subtasks complete), MAP Framework uses the `won't_do` terminal status.

**Trigger phrases (Russian):**
- "закончили" (finished)
- "остановимся" (let's stop)
- "хватит" (enough)
- "дальше не делай" (don't continue)
- "прекращай" (stop it)
- "закрываем" (we're closing)

> **Note:** Currently only Russian trigger phrases are implemented in `intent_detector.py`. English equivalents are planned for a future release.

**What happens:**
1. All `pending` and `in_progress` subtasks are marked `won't_do`
2. Workflow state records `ended_early` metadata
3. Completed subtasks remain `complete`

### ended_early Structure

When a workflow terminates early, the state file includes:

```json
{
  "terminal_status": "won't_do",
  "ended_early": {
    "by_user": true,
    "reason": "User requested early termination",
    "at_subtask_id": "ST-004"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `by_user` | boolean | Whether user initiated termination |
| `reason` | string | Human-readable reason for termination |
| `at_subtask_id` | string | ID of subtask that was active when terminated |

### Troubleshooting Verification Issues

#### Enable Verbose Hook Logging

```bash
export CLAUDE_HOOK_VERBOSE=true
```

This enables detailed logging from hooks, showing:
- Which checks are running
- Pass/fail status of each check
- Duration of each check
- Skip reasons for skipped checks

#### Artifact Locations

| Artifact | Path | Purpose |
|----------|------|---------|
| Verification results | `.map/verification_results_<branch>.json` | Machine-readable check results |
| Workflow state | `.map/state_<branch>.json` | Current workflow status |
| Repo insight | `.map/repo_insight_<branch>.json` | Project language and suggested checks |
| Task plan | `.map/<branch>/task_plan_<branch>.md` | Subtask breakdown with validation |
| Progress checkpoint | `.map/progress.md` | Resume checkpoint for context recovery |

#### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Hook not recording results | verification_recorder not installed | Run `pip install mapify-cli` |
| Missing duration_ms | SECONDS variable not working | Ensure bash 4.0+ |
| Wrong branch in filename | Git not initialized | Initialize git or results go to `_default.json` |
| `overall: unknown` unexpectedly | All checks skipped | Run checks manually to verify setup |

#### Manual Verification Recording

For testing or debugging, you can record results manually:

```bash
python -m mapify_cli.verification_recorder <branch> <recipe_id> <status> <summary> [duration_ms]

# Example:
python -m mapify_cli.verification_recorder main check_custom pass "Custom check passed" 1500
```

---

## ⏸️ Workflow Recovery: /map-resume

Resume interrupted MAP workflows from the last checkpoint.

### When to Use

- After context window exhaustion mid-workflow
- After accidental session termination
- After `/clear` that interrupted a workflow
- When returning to an unfinished task

### How It Works

1. **Detects checkpoint:** Checks for `.map/progress.md`
2. **Shows progress:** Displays completed and remaining subtasks
3. **Asks confirmation:** "Resume from last checkpoint?"
4. **Continues workflow:** Resumes Actor→Monitor loop

### Usage Example

```bash
/map-resume
```

**Output:**
```markdown
## Found Incomplete Workflow

**Task:** Implement user authentication with JWT tokens
**Current Phase:** implementation
**Turn Count:** 12

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks ✅
- [x] **ST-001**: Create User model with SQLite schema
- [x] **ST-002**: Implement password hashing with bcrypt
- [x] **ST-003**: Create login API endpoint

### Remaining Subtasks 📋
- [ ] **ST-004**: Implement JWT token generation
- [ ] **ST-005**: Add logout and token refresh endpoints

How would you like to proceed?
[Continue (Recommended)] [View Details] [Abandon]
```

### Auto-Checkpointing

MAP workflows automatically save progress to `.map/progress.md`:

- After decomposition phase
- After each subtask completion
- Before each Actor call

**Checkpoint format:**
```yaml
---
task_plan: "Implement authentication"
current_phase: implementation
turn_count: 12
completed_subtasks:
  - ST-001
  - ST-002
subtasks:
  - id: ST-001
    description: Create User model
    status: complete
  - id: ST-003
    description: Create login endpoint
    status: in_progress
---

# MAP Workflow Progress
[Human-readable markdown body]
```

### Integration with /clear

If you run `/clear` during a workflow:
- Checkpoint is preserved in `.map/progress.md`
- Fresh context starts from checkpoint state
- Use `/map-resume` to continue

---

## 🔌 Hooks System

MAP Framework uses Claude Code hooks to enhance your workflow experience.

### Prompt Clarification (Prompt-Improver Hook)

**Enabled by default** - Automatically disambiguates vague prompts before execution.

**What it does:**
1. **Evaluates prompt clarity** using conversation history
2. **For vague prompts** (e.g., "fix the bug"):
   - Creates research plan (TodoWrite)
   - Gathers context from codebase, docs, web
   - Asks 1-6 grounded questions with specific options
3. **For clear prompts**: Proceeds immediately

**Example flow:**
```
User: "fix the error"

MAP: [Prompt Improver Hook seeking clarification]
     [Research: Found 3 recent errors in logs]

     Which error needs fixing?
     ○ TypeError in src/components/Map.tsx (recent change)
     ○ API timeout in src/services/osmService.ts
     ○ Other (paste error message)

User: [Selects option]

MAP: [Proceeds with full context]
```

**Bypass options:**
- `* your prompt` - Skip evaluation (remove `*` prefix)
- `/command` - Slash commands bypass automatically
- `# memorize` - Memorize feature bypasses automatically

**Token overhead:**
- ~300 tokens per wrapped prompt
- Only adds questions when genuinely needed
- Better outcomes on first try = overall efficiency

**Design philosophy:**
- **Rarely intervene** - Most prompts pass through
- **Trust user intent** - Research before asking
- **Transparent** - Evaluation visible in conversation
- **Max 1-6 questions** - Focused clarification

### Multi-Hook Processing

MAP uses **multiple UserPromptSubmit hooks** that run in parallel:

1. **Prompt-Improver** – Disambiguates vague prompts (wraps prompt with evaluation instructions)
2. **Pattern Injection** – Adds relevant patterns, and suggests workflows and skills

> **Note:** Claude Code executes all matching hooks in parallel. Each hook's `additionalContext` output is concatenated and added to the prompt. The order is not guaranteed, but both enhancements are applied.

> **Implementation detail:** Prompt improvement, pattern injection, and workflow suggestions are handled within the `improve-prompt.py` hook (`.claude/hooks/improve-prompt.py`).

**Benefits:**
- Both hooks enhance the prompt with different types of context
- Prompt-Improver adds evaluation wrapper, Pattern Injection adds patterns/workflows/skills
- Modular design (hooks can be disabled independently)
- Parallel execution (efficient)

### Disabling Prompt-Improver

If you prefer direct execution without clarification:

**Option 1: Use bypass prefix**
```bash
* implement user authentication  # Skips improvement
```

**Option 2: Remove from `.claude/settings.json`**
```json
{
  "hooks": {
    "UserPromptSubmit": [
      // Comment out or remove Prompt-Improver hook
      {
        "description": "Enhance prompts with clarification and pattern context",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/improve-prompt.py"
          }
        ]
      }
    ]
  }
}
```

### Other Active Hooks

MAP Framework includes additional hooks for security and quality:

| Hook | Event | Purpose |
|------|-------|---------|
| `improve-prompt.py` | UserPromptSubmit | Prompt clarification and enhancement |
| `block-secrets.py` | PreToolUse | Block access to sensitive files |
| `block-dangerous.sh` | PreToolUse | Block dangerous shell commands |
| `end-of-turn.sh` | Stop | Quality gates (linting, secret scanning) |

**Configuration:** See `.claude/settings.json` for hook configuration (or manage via `/hooks`).

**Security hooks:** See [Security Model: Three-Layer Defense](#-security-model-three-layer-defense) for details.

---
