# README Positioning Rewrite Design

## Goal

Update `README.md` so new users quickly understand why MAP Framework exists, when to use it, and how to run a first successful workflow.

The README should make the product more attractive without becoming vague marketing copy. It should connect the product to the DevOpsConf 2026 narrative in `docs/devopsconf_2026_ai_operator_presentation_rewrite-v2.md`: LLMs create speed only when they are embedded in an engineering process with explicit artifacts, constraints, and checks.

## Primary Audiences

1. Individual engineers using Claude Code or Codex CLI for complex tasks who want less chaos and more control.
2. Tech leads or platform leads introducing AI-assisted development who are worried about large, hard-to-review AI pull requests.

The README should lead with the individual engineer's pain, while giving leads enough process language to see team value.

## Core Message

AI already writes code fast. MAP helps engineers keep control.

Bad flow:

```text
idea -> prompt -> code -> hope
```

MAP flow:

```text
SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN
```

The product promise is not "better prompts". It is a reproducible development loop where every stage has inputs, outputs, artifacts, and review points.

## README Structure

### First View

- H1 should be product-first: `MAP Framework`.
- Supporting line should explain the job-to-be-done: a structured AI development workflow for engineers who need control, not just generated code.
- Keep badges, but do not let them dominate the opening.
- Show the bad flow versus MAP flow near the top.
- Mention Claude Code and Codex CLI support in the first screen.

### Why This Exists

Describe the failure mode:

- On simple work, ad-hoc prompting feels fast.
- On complex systems, AI can silently make architecture decisions, generate huge diffs, write tests around its own implementation, and create the illusion of progress.
- MAP solves this by forcing explicit specs, small plans, separate test/review phases, and project memory.

### When To Use It

Add a short section for good and poor fits.

Good fits:

- complex backend features
- Kubernetes controllers and operators
- platform tooling
- API or domain-model changes with invariants
- refactors with a meaningful test harness

Poor fits:

- typo fixes
- tiny scripts
- unclear product ideas where desired behavior is not known yet
- broad rewrites without boundaries

### Quick Start

Keep installation concise, then show both providers:

```bash
uv tool install mapify-cli
mapify init
```

and:

```bash
mapify init . --provider codex
```

The first workflow should be framed as a real task:

```text
/map-plan define the behavior and split the task
/map-efficient implement the approved plan
/map-check
/map-review
/map-learn
```

For Codex, mention the corresponding `$map-plan`, `$map-fast`, and `$map-check` skills without making the README a full command reference.

### What Success Looks Like

Show what the user should expect after the first workflow:

- MAP asks for or creates an explicit plan before coding.
- Work is decomposed into small contracts.
- Verification and review artifacts are written under `.map/<branch>/`.
- The user reviews decisions at stage boundaries instead of reviewing one giant AI diff.

### Case Study

Include a compact case-study block from the DevOpsConf narrative:

- production Kubernetes Project Operator
- human estimate: 90 days
- MAP-style process result: 7 days
- small reviewable PRs
- tests before implementation for critical pieces
- semantic bugs caught in review

This section should support credibility, not replace the quick start.

### Commands And Docs

Keep the command table, but move it after the product explanation and quick start. Link to `docs/USAGE.md` for exhaustive workflows and options.

## Tone

- Direct, engineering-first, not hype-heavy.
- Avoid claiming that AI replaces engineers.
- Emphasize that MAP moves engineering judgment left into spec, decomposition, test contracts, and review.
- Avoid over-indexing on the academic MAP architecture in the opening. It can stay as supporting credibility below the main product promise.

## Non-Goals

- Do not rewrite detailed usage docs in the README.
- Do not add a full tutorial for every slash command.
- Do not remove existing docs links or PyPI/Python install information.
- Do not change runtime behavior.

## Acceptance Criteria

- A new individual engineer can understand in under two minutes:
  - what MAP does
  - when it is worth using
  - how to install it
  - what first workflow to run
- A tech lead can see why the workflow reduces review risk from AI-generated code.
- The README reflects the DevOpsConf thesis: LLM speed is useful only inside an explicit engineering process.
- The command reference remains available but no longer dominates the top of the page.
- The README mentions both Claude Code and Codex CLI provider paths.

## Verification Plan

- Review `README.md` manually against this design.
- Check that all links still point to existing files.
- Run markdown or repository checks if available after implementation.
