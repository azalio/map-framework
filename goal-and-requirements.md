---
id: map-product
type: goal-and-requirements
status: draft
title: MAP Framework product goals and requirements
---

# MAP Framework

## Goal and audience

MAP helps engineers use Claude Code and Codex CLI for repeatable, reviewable engineering work in an existing Git repository. Its Python CLI, `mapify`, installs provider-specific workflows and deterministic helpers; the provider runtime performs the agent work.

The problem is not generating more code, but keeping agent changes scoped, verifiable and recoverable across a long-running task. MAP combines small reviewable contracts with durable evidence and independent review rather than treating an agent's claim of completion as proof.

## Capabilities

- Install, refresh, configure, audit and remove managed provider surfaces while distinguishing managed content from user-owned content.
- Guide planning, implementation, test-first work, debugging, verification and review through skill-backed workflows.
- Persist branch-scoped plans, checkpoints, acceptance evidence, approval holds and learning handoffs so interrupted work can resume.
- Apply deterministic workflow and safety gates, with provider-specific adapters around shared intent.
- Capture and recall cross-session memory, report token use, and evaluate skill triggering and workflow outcomes.

## Product principles

Reviewable changes, artifact traceability, provider portability, deterministic guardrails, minimality without underbuilding and low daily overhead are the documented quality goals. A subtask is bounded by cohesive responsibilities and approved scope, not a fixed line count.

Execution uses local provider CLIs and filesystem artifacts. Temporary directories and Git worktrees are not OS security sandboxes; executing an agent remains an explicit trust decision.

## Non-goals

MAP is not a hosted multi-tenant agent platform, an implementation of Claude Code or Codex CLI, or a distributor/maintainer of third-party MCP servers. Optional MCP support configures client integration only.

## Contract ownership

The architecture node `map-architecture` ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) owns system topology and cross-cutting contracts. Module nodes describe implementation boundaries; evaluation nodes distinguish trigger accuracy from end-to-end outcomes. Repository specs are distinct from the task specifications generated under `.map/`.

This initial graph is a draft extracted from repository documentation and code, pending user review. It describes current capabilities, not acceptance of the proposed platform redesign in `docs/MAP_PLATFORM_SPEC.md`.
