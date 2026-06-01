# TRIZ Cheatsheet (MAP-anchored)

> Living index of the 40 classical TRIZ inventive principles, each tied to a concrete location in MAP where the principle is applied (or could be applied). Used by `/map-plan` (Contradiction section) and the Reflector agent (`triz_principle` output field).

## Why this lives in MAP

TRIZ (Altshuller, 1956) is a method for finding strong solutions by first naming the **contradiction** a system must hold — "must `<X>` AND NOT `<X>`" — and then reaching for one of ~40 named moves that historically resolve such tensions. The principles are a shared vocabulary, not rules.

MAP already encodes several of these implicitly (workflow-fit off-ramp, parallel review, learned rules). The cheatsheet makes them explicit so that:

1. `/map-plan` can frame each spec around a real tension instead of "make X happen".
2. The Reflector can label each learned rule with the principle it embodies, so the same shape becomes visible across unrelated bugs.
3. Future architectural changes can be evaluated as "which contradiction does this resolve?" instead of "is this nice?".

## How to use it

When stuck on a design choice, follow the five-step loop:

1. **Formulate the contradiction.** Restate the goal as `<X> AND NOT <X>`. If the second half is hard to write, the task probably isn't a real contradiction — and `/map-plan` should have off-ramped to `direct-edit`.
2. **Describe the Ideal Final Result.** The function exists; the mechanism that delivers it appears absent. ("Cache as if always warm." "Agent as if it already knows what to do.")
3. **Sweep candidate principles.** Skim the table for principles whose essence matches one side of the tension.
4. **Look for free resources.** What does the system already produce that is currently discarded? (Prior session logs as a fine-tune dataset, idle GPU time, KV-cache between calls, the diff itself as a Monitor input.)
5. **Test for "ideality".** Did the solution reduce moving parts or add them? If parts increased, it's engineering scaffolding, not a TRIZ resolution — keep looking.

## The 40 principles

Each row gives the principle name, a short essence in MAP-relevant language, and a **MAP locator** — concrete file or concept where this principle currently lives, or where it is the natural place to look first if you want to apply it.

### Group 1 — Separation and combination

| # | Principle | Essence | MAP locator |
|---|-----------|---------|-------------|
| 1 | Segmentation | Split one thing into independent parts. | `task-decomposer` agent: one user goal → N ST-XXX subtasks. |
| 2 | Extraction | Pull the bothersome part out into a side service. | `research-agent` extracted from Actor; Reflector extracted from execution loop. |
| 3 | Local quality | Different properties for different parts. | Per-agent prompts (`actor.md` vs `monitor.md` vs `evaluator.md`) — each tuned to its job. |
| 4 | Asymmetry | Where symmetry implies symmetric cost, break it. | Future: cheap deterministic pre-monitor (lint/diff parsers) catches 80%, LLM Monitor only on disputed cases. |
| 5 | Merging | Bring homogeneous operations together. | `/map-review` runs Monitor+Predictor+Evaluator in parallel, one round-trip. |
| 6 | Universality | One object with many functions. | `MCP` as the single tool-call protocol; `step_state.json` as the single workflow state. |
| 7 | Nesting | Object inside object. | Sub-agents called by agents (research-agent inside `/map-plan`); skills inside skills. |
| 8 | Anti-weight | Compensate a load with an opposing load. | `.map/<branch>/` snapshot artifacts as a counterweight to destructive edits; worktrees as rollback-able copies. |

### Group 2 — Preliminary and anticipatory action

| # | Principle | Essence | MAP locator |
|---|-----------|---------|-------------|
| 9 | Preliminary anti-action | Neutralise the bad outcome before it happens. | Devil's Advocate spec review (`/map-plan` Step 2b) and `workflow-gate.py` hook. |
| 10 | Preliminary action | Do the work before it is needed. | Pre-flight resume detection in `/map-plan`; prompt caching via map_step_runner. |
| 11 | Cushion (beforehand) | Insure against failure. | `map-resume`, durable `step_state.json`, retry-on-Monitor-fail loop, learned-rules cache. |
| 12 | Equipotentiality | Don't move things you don't have to. | Workflow-fit gate keeps trivial work as `direct-edit`; `.map/` lives next to the code, not on a server. |
| 13 | Inversion | Do it the other way around. | Reflector could push pattern candidates to the user instead of waiting for `/map-learn` (proposed). |
| 14 | Spheroidality | Replace linear with cyclic. | `ralph-loop-config.json` and the improvement-loop run repeatedly, not once. |
| 15 | Dynamicity | Make parameters change at runtime. | Planned REGISTRY/FOCUS mode switch in orchestrator (`improvement-plan.md` 2604.019/020). |
| 16 | Partial / excessive action | Do it in pieces, or with deliberate overshoot. | Wave-based execution in `/map-efficient`; token budget per subtask. |

### Group 3 — Dimensions, time, feedback

| # | Principle | Essence | MAP locator |
|---|-----------|---------|-------------|
| 17 | Another dimension | Lift from a list into a graph or surface. | Architecture Graph block in spec; `dependency_graph.py` as a richer view of the subtask list. |
| 18 | Mechanical oscillation | Periodic ping. | Heartbeat hooks — currently absent; natural fit for long-running workflows. |
| 19 | Periodic action | Replace continuous load with pulses. | Batched template render via `make render-templates` instead of per-edit copy; nightly playbook compaction (potential). |
| 20 | Continuity of useful action | No idle time. | `MapWorkflowLogger` streams structured events as work happens; `/map-resume` keeps no gap on session boundary. |
| 21 | Skipping | Move through the dangerous phase fast. | Workflow-fit off-ramp: `direct-edit` and `map-fast` skip the long path when MAP overhead isn't justified. |
| 22 | Harm into benefit | Turn the failure mode into a useful signal. | Pre-existing surfaced failures → CLARIFICATION_NEEDED (rather than silent suppression); Monitor rejections logged for Reflector. |
| 23 | Feedback | Close the loop. | Reflector → `learned/*.md` → next Actor run reads them as context. |
| 24 | Mediator | Intermediate layer. | `map_orchestrator.py` mediates between slash commands and agents; MCP servers as mediators. |
| 25 | Self-service | The system maintains and repairs itself. | Auto-categorization of learned rules into sections (security/architecture/error); potential: rules promoted into skills automatically. |
| 26 | Copying | Work on a copy, not the original. | `.claude/worktrees/` for isolated experiments; spec/plan as a copy of the user's intent that can be revised without touching code. |
| 27 | Cheap, short-lived | Many disposable replacements for one expensive permanent thing. | `.map/<branch>/` artifacts are per-branch and disposable; embedding cache rebuilt as needed. |
| 28 | Replace mechanical | Imperative → declarative; manual → automated. | SKILL.md describes intent, not procedure; AAG contracts (`Actor -> Action(params) -> Goal`) replace step-by-step instructions. |

### Group 4 — Materials, states, environments

| # | Principle | Essence | MAP locator |
|---|-----------|---------|-------------|
| 29 | Pneumatic / hydraulic | Replace rigid with flowing. | Token streaming in agent responses; structured workflow logs as an event stream. |
| 30 | Flexible shells / thin membranes | Thin adapter beats heavy layer. | Hooks (`PreToolUse`, `PostToolUse`) as thin adapters; provider-specific delivery shims in `src/mapify_cli/delivery/`. |
| 31 | Porous materials | Useful emptiness inside the dense thing. | Optional spec fields ("Security Boundaries" included only when relevant); "skip" branches in `/map-plan` interview. |
| 32 | Change visibility | Adjust what's visible vs hidden. | Planned REGISTRY/FOCUS context modes; PII redaction before LLM call. |
| 33 | Homogeneity | One stack, fewer seams. | Monorepo; one templated `skills/` format shared by Claude Code and (in skill-form) Codex CLI. |
| 34 | Rejection and regeneration | Discard old, regenerate fresh. | Context compaction; `.map/<branch>/` may be rebuilt from `task_plan` + `blueprint.json`. |
| 35 | Parameter change | Switch the aggregate state of the data. | Summarisation of old context in compaction; agent prompt distillation. |
| 36 | Phase transition | Use the transition itself, not the state. | Explicit `INITIALIZED → IN_PROGRESS → SUBTASK_COMPLETE → WORKFLOW_COMPLETE` in `step_state.json` — events fire on transitions, not on steady state. |
| 37 | Thermal expansion | Grow or shrink in response to load. | Context budget enforcer adapts to subtask complexity; planned dynamic token budget (2604.023). |
| 38 | Strong oxidants / accelerators | Speed up the reaction without changing inputs. | `embeddings_cache/`, `playbook.db`, vector indexes; rerankers in research-agent. |
| 39 | Inert environment | Isolate from outside disturbance. | Worktrees as sandboxes; planned code-execution sandbox for Actor; allowlist/blocklist hooks. |
| 40 | Composite materials | Assemble from heterogeneous parts. | A subtask's artifact bundle: spec + plan + blueprint + manifest + findings, each tracked separately. |

## Live catalog (populated by Reflector)

When Reflector identifies a learned pattern, it tags it with one or more `triz_principle` IDs (1–40). Aggregate entries land here as evidence of which principles MAP relies on most — and which are blind spots.

| Principle | Learned rule | First seen | Workflow |
|-----------|--------------|-----------|----------|
| _empty until Reflector starts emitting `triz_principle` fields_ | | | |

To populate this table, append a row when reviewing `.claude/rules/learned/*.md` — match the rule's "Why" against the principle whose essence it most directly applies. A rule may legitimately reference 2–3 principles.

## Notes on cross-domain transfer

A pattern often clusters under 2–3 principles at once. Speculative decoding is simultaneously anti-weight (8), copying (26), and skipping (21). The state-machine `advance_wave` reset rule (learned 2026-04-11) is simultaneously phase transition (36) and continuity (20). This is expected — the principles are overlapping descriptions, not a partition.

The point is not to memorise 40 labels but to be in the habit of asking "what tension is this code trying to hold?" before "what code should I write?". The principle catalog is what reminds you the question has been asked before, often in a domain that looks nothing like yours.

## Source

The 40 principles and the contradiction-matrix idea trace to G. S. Altshuller's *To Find an Idea* (1986) and earlier works. The principle list itself is in the public domain; the MAP-anchored essences and locators in this file are written for this codebase.
