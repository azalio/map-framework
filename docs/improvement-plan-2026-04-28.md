# MAP Framework — Improvement Plan (2026-04-28)

**Trigger:** User feedback comparing MAP to Superpowers/Codex on a "integrate
external tool that runs up to 5 minutes" task. MAP produced a structurally
better plan (acceptance criteria vs code chunks) but missed two issues:

1. Storing long-running call state in an in-memory variable instead of durable
   storage — a real architectural defect for any 5-minute operation.
2. Not asking clarifying questions despite the user explicitly writing
   "If something is not clear — ask. Do not assume anything by yourself."

**Goal of this plan:** lift those two failures and harvest the relevant
Claude Code features the framework currently underuses, ranked by impact.

---

## 1. Diagnosis (already verified)

### 1.1 Durability blind spot

`grep` across `.claude/agents/`, `.claude/commands/`, and
`.claude/rules/learned/` for `durab|persist|long.running|background|in-memory|
ephemeral|survives.*restart` returns **no content-bearing matches** in the
planning surface. Trivial matches only ("persists normalized email" in an
example, "database persistence" in a test_strategy example).

Two safety nets exist, both skipped for short prompts:

- `.claude/commands/map-plan.md` **Step 2 (Deep Interview)** — skipped
  when "task is well-defined" (heuristic, line 161-164).
- `.claude/commands/map-plan.md` **Step 2b (Devil's Advocate)** — skipped
  when "source <200 lines AND <5 subtasks AND no cross-cutting concerns"
  (line 308-312). For "integrate this 5-minute tool" all three skip
  conditions match, even though the task IS a concurrency/recovery task.

### 1.2 Ignored "ask if not clear"

`task-decomposer.md` exposes `analysis.open_questions` and an "Ambiguous Goal
Output Format" (line 327-348). Both treat ambiguity as a binary — return
plan OR return only questions. There is no rule that says "user explicitly
invited clarification → must surface at least one question regardless of
heuristic confidence." `/map-plan` Step 1 picks interview depth from a
heuristic that can override the user's explicit instruction.

This is the same family as the existing learned rule
`Agentic Prompt Emphasis Uniformity` (2026-04-11): selective emphasis
implicitly downgrades unmarked guidance. Here heuristic skip conditions
implicitly downgrade explicit user instruction.

---

## 2. What the Claude Code docs add

Read from `https://code.claude.com/docs/en/{sub-agents,skills,hooks,tools-reference}.md`:

**Sub-agent frontmatter has more knobs than MAP uses.** All 11 MAP agents
declare only `model: sonnet` (debate-arbiter is `opus`, research-agent is
`inherit`). Available but unused: `effort: low|medium|high|xhigh|max`,
`permissionMode: plan|acceptEdits|...`, `isolation: worktree`, `skills: [...]`
(injects full skill content at startup), `disallowedTools`,
`initialPrompt`. The user noted Codex was running on "high effort" — MAP
has the field but doesn't use it.

**`AskUserQuestion` is a built-in tool** (not something MAP can implement,
but something to invoke directly). It accepts 1–4 multiple-choice
questions. `/map-plan` Step 2 already uses it — good. No agent-level prompt
explicitly invokes it.

**Hooks list is much richer than MAP uses.** Currently MAP uses
`PreToolUse`, `Stop`, `PreCompact`, `PostCompact`. Available and unused:
`UserPromptSubmit`, `SessionStart`, `InstructionsLoaded`, `SubagentStart`,
`SubagentStop`, `TaskCreated`, `TaskCompleted`, `Elicitation`. The
`UserPromptSubmit` hook can inspect every user message before Claude sees
it and inject `additionalContext` — exactly the lever needed to lift the
two diagnosed gaps reactively.

**Hook exit codes:** only exit code 2 blocks. Any other non-zero is
non-blocking. MAP's Python hooks should use `sys.exit(2)` when intent is
to block, otherwise behavior is silently ignored. Worth auditing existing
hooks.

**Slash commands merged into Skills.** Quote: "Custom commands have been
merged into skills. A file at `.claude/commands/deploy.md` and a skill at
`.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same
way." Existing `.claude/commands/map-*.md` keep working — no urgency, but
worth noting for future architecture decisions.

**Sub-agents cannot spawn other sub-agents.** Several MAP agent prompts
contain `Task(subagent_type=...)` instructions (e.g., `actor.md` invokes
`research-agent`). If those are reached from inside a subagent context,
they fail silently. Needs verification — flagged in §4 below as a
diagnostic, not a fix.

---

## 3. The plan, by priority

Each item: **what / where / why / effort / impact**. Effort is S (≤30 min),
M (~2 h), L (>4 h). Impact reflects how much it lifts the two diagnosed
failures or prevents the same class.

Every change to `.claude/` MUST be mirrored to
`src/mapify_cli/templates/` per the repo's template-sync invariant.
Run `make render-templates` then `pytest tests/test_template_render.py -v`
to verify.

### P0 — direct fixes for the diagnosed failures

**P0.1 — Override interview-skip when user invites clarification.**
*Effort: S, Impact: high.*
In `.claude/commands/map-plan.md`, **Step 1** ("Assess Scope and Decide
Interview Depth"), add this rule **before** the existing skip heuristics:

> **Override (always wins):** If the user prompt contains explicit
> clarification-invitation language — English or Russian patterns such as
> "ask if unclear", "do not assume", "clarify", "если что-то непонятно",
> "спрашивай" — the interview is REQUIRED regardless of any other signal.
> The user has explicitly opened the door; not walking through it is a
> bug, not a judgment call.

Two-line check, three-line override block. Lifts the second diagnosed
failure structurally rather than by hoping the LLM "feels" the cue.

**P0.2 — Drop the length component of the Devil's Advocate skip.**
*Effort: S, Impact: high.*
In `.claude/commands/map-plan.md`, **Step 2b**, current skip condition is
`<200 lines AND <5 subtasks AND no cross-cutting concerns`. Remove the
length and subtask-count clauses — keep only "no cross-cutting concerns".
And expand the cross-cutting list:

> Cross-cutting concerns include: observability, security, **concurrency,
> recovery, durability, asynchronous operations longer than 30 seconds,
> multi-service coordination, retry/backoff logic, queueing, webhook
> delivery, polling**.

Currently a 50-line task that needs durable state skips review entirely.
After this, any prompt mentioning long-running / async / background /
poll / webhook semantics will trigger Devil's Advocate.

**P0.3 — Add "Durability & State Lifecycle" interview dimension.**
*Effort: S, Impact: high.*
In `.claude/commands/map-plan.md`, **Step 2** "Interview dimensions
checklist" (currently 7 numbered items, line 178-185), add an 8th:

> 8. **Durability & State Lifecycle:** For any operation longer than a
>    request-response cycle (>5 s), where does state live? Does it
>    survive process restart, redeploy, host migration? What is the
>    recovery contract on crash? What identifier lets a caller resume?

This is the question Codex asked and MAP didn't.

**P0.4 — Decomposer checklist gains a durability audit pass.**
*Effort: S, Impact: medium.*
In `.claude/agents/task-decomposer.md`, the
`<Decomposer_Checklist_v2_4>` section gains a new sub-checklist next to
"Risk & Assumptions Validation":

> **Durability Audit (CRITICAL when subtask describes async/long-running):**
> - [ ] Identified state owned by the operation (request, response, intermediate)
> - [ ] Documented where each state element lives (in-memory, file, DB, queue)
> - [ ] Confirmed in-memory state cannot outlive a single request
> - [ ] Recovery semantics defined for crash mid-operation
> - [ ] Caller has a resume identifier when applicable

Trigger: any subtask whose description matches the async/long-running
language list from P0.2.

**P0.5 — New learned rule: long-running ops need durable state.**
*Effort: S, Impact: medium (compounds across future runs).*
Append to `.claude/rules/learned/architecture-patterns.md`:

```markdown
- **Long-Running Operations Need Durable State by Default** (2026-04-28):
  Any operation lasting longer than a request-response cycle (>5 s)
  MUST persist its state to durable storage (DB, queue, KV with
  persistence) — never to in-process memory or class attributes. Process
  restart, redeploy, autoscaler eviction, and crash all happen during a
  5-minute call in production. The default question for any async API
  is "what survives a kill -9 mid-call?" not "where is this convenient
  to put?". Provide a resume identifier (run_id) so callers can recover
  results across the boundary. [workflow: map-learn-improvement]
  ```python
  # WRONG — state evaporates on restart
  class ToolRunner:
      _runs: dict[str, Result] = {}  # in-memory, lost on redeploy

  # CORRECT — state lives outside the process
  class ToolRunner:
      def run(self) -> str:
          run_id = uuid4().hex
          db.insert(run_id, status="running", started_at=now())
          return run_id  # caller can poll get_result(run_id)
  ```
```

This makes the durability check stick across MAP runs even if the prompts
above are weakened in future edits.

### P1 — use Claude Code features the framework currently ignores

**P1.1 — `UserPromptSubmit` hook for explicit-clarification trigger
detection.**
*Effort: M, Impact: high (structural belt-and-suspenders for P0.1).*

Create `.claude/hooks/detect-clarification-triggers.py`. On every user
prompt, run two regex passes:

- Clarification-invitation patterns (case-insensitive, English + Russian)
- Long-running / async patterns (`5\s*min(ute)?s?`, `long.running`,
  `background\s+(job|task)`, `webhook`, `\basync\b`, `polling`, etc.)

If either matches, emit JSON to stdout:

```json
{
  "hookSpecificOutput": {
    "additionalContext": "[MAP framework] User prompt indicates: <reasons>. Recommended posture: deep interview (Step 2 mandatory) and durability audit on any planned subtask."
  }
}
```

Wire it into `.claude/settings.json` under
`hooks.UserPromptSubmit`. The hook MUST exit 0 — this is informational,
not blocking. (Per docs: only exit 2 blocks.)

This catches the case where the user invokes `/map-plan` indirectly or
from a custom slash command, and where the in-prompt P0.1 rule is the
weaker mechanism.

**P1.2 — Decomposer uses `AskUserQuestion` directly for durability when
ambiguous.**
*Effort: M, Impact: medium.*

Currently `task-decomposer.md` has only two paths: produce plan OR refuse
with `open_questions`. Add a third for durability specifically. In the
agent prompt, append a section:

> ### When to call AskUserQuestion mid-decomposition
>
> If you are mid-decomposition and discover a durability question that
> changes the architecture (e.g., is this state in-memory or DB?), you
> may invoke `AskUserQuestion` with a single question rather than
> guessing or returning the full ambiguous-goal response. Restrict
> mid-decomposition AskUserQuestion calls to architecturally-load-bearing
> questions only — do not ask about styling, naming, or anything that
> can be deferred to implementation.

Verify subagents can call `AskUserQuestion` (docs say foreground
subagents pass it through to the user; background subagents fail). MAP
runs decomposer in foreground, so it should work. **Verification step:**
write a one-shot test that invokes the decomposer on an intentionally-
underspecified async task, confirm AskUserQuestion fires.

### P2 — model and effort hygiene

**P2.1 — Bump model and effort for the high-leverage agents.**
*Effort: S per agent, Impact: medium (the user observed Codex on "high"
beat MAP on default-Sonnet).*

Set explicit model/effort frontmatter:

| Agent | Current | Proposed |
|-------|---------|----------|
| `task-decomposer.md` | `model: sonnet` | `model: opus`, `effort: high` |
| `final-verifier.md` | `model: sonnet` | `model: opus`, `effort: high` |
| `monitor.md` | `model: sonnet` | `model: sonnet`, `effort: high` |
| `predictor.md` | `model: sonnet` | unchanged |
| `actor.md` | `model: sonnet` | unchanged (volume of code generation favors sonnet) |
| `evaluator.md` | `model: sonnet` | `model: sonnet`, `effort: high` |
| `research-agent.md` | `model: inherit` | `model: haiku` (read-mostly, parallelism friendly) |

Rationale: spend tokens on the agents whose decisions are load-bearing
(decompose, final-verify, monitor). Save tokens on read-mostly research.
The user explicitly noted that Codex on `medium` produced a more
durable design than Claude on default — a model/effort gap is part of
the explanation.

**P2.2 — `permissionMode: plan` on `task-decomposer`.**
*Effort: S, Impact: low.*
The decomposer should never write code. Adding `permissionMode: plan`
encodes the intent as configuration rather than relying on the agent's
prompt to refuse Edits. Cheap insurance.

**P2.3 — Audit hook exit codes.**
*Effort: S, Impact: low.*
`.claude/hooks/*.py` — confirm any hook intended to BLOCK uses
`sys.exit(2)` not `sys.exit(1)`. Per docs: "only exit code 2 blocks the
action; exit 1 is a non-blocking error." If any current hook uses 1 to
block, it is silently failing.

### P3 — defer / discuss before doing

**P3.1 — `.claude/commands/` → `.claude/skills/` migration.**
*Effort: L, Impact: low for now.*
Slash commands and skills are functionally merged per the docs.
Migrating buys progressive disclosure (descriptions in context, body
loaded on demand) which would shrink the orchestrator's prompt budget.
**But** — `.claude/commands/` still works, the migration touches every
file in `src/mapify_cli/templates/commands/`, and the win is token
budget, not behavior. Defer until separately motivated.

**P3.2 — Verify subagent-can't-spawn-subagent claim against MAP flow.**
*Effort: M, Impact: unknown until measured.*
Several MAP agent prompts contain `Task(subagent_type=...)` instructions.
If those are reached from inside a subagent context, the docs say they
fail. Need to confirm whether MAP's orchestrator routes these calls
through the parent (which would make them work) or directly (which
would silently break them). One clean test: trace an `actor.md` run
where it would reach `Task(subagent_type="research-agent")` and check
whether research-agent actually fires.

If broken: rewrite `actor.md` to assume research is run upstream by the
orchestrator (which the prompt already partly says: "Research is run by
the orchestrator BEFORE Actor is invoked"). The vestigial `Task(...)`
instructions should be removed or marked as orchestrator-only.

---

## 4. Anti-list (don't do as part of this batch)

These are tempting but premature given the trigger:

- Don't add new agents (durability-auditor, etc.). The existing agents
  can host the durability check via P0.4 and P0.5. Adding agents has
  high overhead and competes for prompt budget.
- Don't touch `.claude/commands/` → `.claude/skills/` now (P3.1). Wait
  for a separate token-budget motivation.
- Don't redesign `step_state.json` schema. The state machine completeness
  rule already has a learned entry (2026-04-11) — leave it alone.
- Don't add `isolation: worktree` to actor. The actor's `allowed_scope`
  already constrains it. Worktree isolation has setup cost that doesn't
  buy enough until we hit a concrete cross-task contamination bug.
- Don't promote `AskUserQuestion` everywhere. It's a tool, not a
  strategy. Use it at decomposer-level (P1.2) and at the command-level
  interview (already in /map-plan); don't sprinkle it across every
  agent.

---

## 5. Execution order

1. Land **P0.1, P0.2, P0.3, P0.4, P0.5** as one PR. Each is a small
   text edit, all in `.claude/` plus the matching `src/mapify_cli/templates/`
   files. Verify with `make render-templates` and
   `pytest tests/test_template_render.py -v`.
2. **P2.1, P2.2, P2.3** — frontmatter and hook-exit-code hygiene. Same
   PR or a follow-up of the same shape; small mechanical edits.
3. **P1.1** — new `UserPromptSubmit` hook. Standalone PR. Includes the
   hook script, settings.json wiring, a test that invokes it with a
   sample async-language prompt and asserts `additionalContext` is
   produced.
4. **P1.2** — decomposer mid-decomposition `AskUserQuestion`. Standalone
   PR; includes the verification step (subagent-foreground passthrough).
5. **P3.2** — investigation only. Write a short report; do not act
   without confirmation.

## 6. Acceptance criteria for this plan

This plan is "done" when, on a fresh repro of the original failure
(prompt: "integrate me a tool that runs up to 5 minutes; ask if not
clear"):

- `/map-plan` runs Step 2 (deep interview), driven by P0.1's override.
- Step 2b (Devil's Advocate) runs because the prompt matches the
  expanded cross-cutting list (P0.2).
- One of the interview dimensions surfaces a durability question
  (P0.3).
- The decomposer produces at least one subtask whose
  `validation_criteria` references durable storage / `run_id` /
  resumeability (P0.4 + P0.5).
- The `UserPromptSubmit` hook logs a context-injection event for that
  prompt (P1.1).
- `task-decomposer` runs at `model: opus` with `effort: high` (P2.1).

If all six are observable on the repro, the failure mode is structurally
addressed — not just patched in one place.

---

## 7. Open questions (defer to user)

Before starting any of P0–P2, please confirm:

1. **Model bump scope.** P2.1 routes the decomposer to Opus. Are you OK
   with the cost increase, or should this be gated on an environment
   variable / setting? (Codex/OpenAI was a personal subscription per
   your note — Claude is corporate, so cost may be a sensitivity.)
2. **Russian + English clarification triggers.** P0.1 and P1.1 detect
   both. Is there a project-language bias I should respect, or
   bilingual is correct?
3. **P3.2 priority.** Is verifying the subagent-can't-spawn-subagent
   claim something to do as part of this work, or schedule separately?
   It changes how aggressive we should be about removing
   `Task(subagent_type=...)` patterns from agent prompts.

Answers to these change the order and aggressiveness of P0/P1/P2 but
not the structure.
