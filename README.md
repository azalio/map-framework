# MAP Framework

[![PyPI version](https://badge.fury.io/py/mapify-cli.svg)](https://pypi.org/project/mapify-cli/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> A structured AI development workflow for engineers who need control, not just generated code.

MAP turns Claude Code and Codex CLI from ad-hoc coding assistants into a repeatable engineering loop with explicit artifacts, review points, and project memory.

Without MAP:

```text
idea -> prompt -> code -> hope
```

With MAP:

```text
SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN
```

AI already writes code quickly. MAP helps you keep the architecture, scope, tests, and review process under control while it does.

## Why MAP Exists

Ad-hoc prompting feels fast on simple tasks. On complex systems, it often creates a different problem: code appears quickly, but the engineering process disappears.

Common failure modes:

- AI silently makes architecture decisions you did not approve.
- One prompt produces a large diff that is hard to review.
- Tests are written around the generated implementation, including its mistakes.
- The output compiles, but you cannot explain why the design is correct.
- The next session forgets the gotchas you already paid to discover.

MAP is a lightweight workflow for moving engineering judgment earlier: write down the behavior, split the work into small contracts, verify each stage, review against the spec, and save lessons for the next run.

## When To Use MAP

| Good fits | Poor fits |
|-----------|-----------|
| Complex backend features | Typos and tiny edits |
| Kubernetes controllers and operators | Small one-off scripts |
| Internal platform tooling | Product ideas where the desired behavior is still unknown |
| API, CRD, or domain-model changes with invariants | Broad rewrites without clear boundaries |
| Refactoring with a meaningful test harness | Tasks cheaper to do directly than to plan |

## Quick Start

**1. Install**

```bash
uv tool install mapify-cli

# or with pip
pip install mapify-cli
```

**2. Initialize your project**

Claude Code is the default provider:

```bash
cd your-project
mapify init
claude
```

Codex CLI is also supported:

```bash
cd your-project
mapify init . --provider codex
codex
```

Then enable the Codex hook manually: run `/hooks`, select `PreToolUse`, press `t` to toggle it on, then press `Esc`.

If your Codex version does not support the `hooks` feature key yet, either start it with `codex --enable codex_hooks` or upgrade Codex first. Upgrading is recommended.

Pick a context-compression policy if you want non-default behaviour
(`auto` is the default; see [docs/USAGE.md#context-budget-policy](docs/USAGE.md)):

```bash
mapify init . --compression never                 # quality > cost
mapify init . --compression aggressive            # cost > quality
mapify init . --compression-threshold 250000      # Opus 1M project
```

Generated `/map-efficient` Actor context blocks are also bounded before they
enter prompts. Override the default 4,000 estimated-token cap with
`MAP_CONTEXT_BLOCK_BUDGET_TOKENS` only when a large plan genuinely needs more
context; values below the 128-token minimum fall back to the default so the
block can still include its required wrapper and truncation note.

**3. Use the golden path for serious work**

When a task has unclear behavior, multiple files, or real review risk, run the full loop:

```text
/map-plan define the behavior and split the task
/map-efficient implement the approved plan
/map-check
/map-review
/map-learn
```

Direct `/map-efficient` is for already-scoped tasks. If you are unsure, start with `/map-plan`.

Codex users should invoke MAP skills with `$`: type `$map-plan`, `$map-fast`, or `$map-check` instead of `/map-plan`, `/map-fast`, or `/map-check`. See the [Usage Guide](docs/USAGE.md#codex-cli-provider) for provider details.

## What Success Looks Like

After a good first workflow, you should see:

- a written plan or spec before implementation starts;
- small implementation contracts instead of one giant AI diff;
- verification and review artifacts under `.map/<branch>/`;
- review comments focused on correctness and semantics, not formatting noise;
- `/map-learn` preserving project rules, gotchas, and handoffs for future sessions.

MAP review is useful, but it is not a replacement for engineering judgment. Serious changes still need human review. The goal is to make that review smaller, earlier, and better grounded.

## Why Engineers Stick With It

- **Daily-driver speed** - optimized for repeated use, not occasional demo workflows.
- **Low overhead** - structured enough to prevent chaos, lightweight enough to keep token and time cost under control.
- **Calibrated workflow effort** - each shipped slash skill declares a `thinking_policy` and `parallel_tool_policy`, so lightweight commands stay direct while planning, review, and release workflows reserve deeper reasoning and parallel fan-out for the stages that benefit from it. Non-release prompts use targeted guardrails instead of blanket all-caps prohibition blocks, reducing over-triggered agents and tool calls while keeping true hard stops explicit.
- **Context-first prompt envelopes** - high-context `/map-plan`, `/map-efficient`, `/map-debug`, and `/map-review` agent prompts wrap branch artifacts in XML-style `<documents>`, then state the `<task>` and `<expected_output>`, so specs, review bundles, diffs, logs, and schemas stay visually and machine-semantically separated.
- **Skill IR audit** - release checks can lower shipped Claude and Codex `SKILL.md` files into a typed `SkillIR`, verify content hashes, catch unsupported frontmatter, reject missing supporting-file links, and block injection-like instructions before `mapify init` copies provider surfaces into user repos.
- **Reviewable diffs** - planning and task contracts keep changes small enough to inspect.
- **Contract-sized subtasks** - `/map-plan` and `/map-efficient` require per-subtask `expected_diff_size`, `concern_type`, `one_logical_step`, `hard_constraints`, `soft_constraints`, and `coverage_map` metadata, then validate `blueprint.json` before implementation so oversized, mixed-concern, untraceable, or hard-constraint-dropping plans fail early instead of surprising reviewers later. Soft constraints can be consciously traded off only with explicit rationale.
- **Useful quality gates** - `/map-check` and `/map-review` validate against the plan instead of just asking whether code "looks fine".
- **Review bundle** - `/map-review` auto-generates `.map/<branch>/review-bundle.json` and `.map/<branch>/review-bundle.md` before launching reviewer agents, bundling spec, plan, tests, verification, latest code review, `coverage_map` acceptance-tag evidence, and prior-stage consumption status into a single durable input contract. Reviewers read the bundle first; raw diff is secondary. Use `/map-review --detached` to open an isolated read-only git worktree at `.map/<branch>/detached-review/` for clean-room inspection without touching the source branch. Bundle generation records the `review` stage in `.map/<branch>/artifact_manifest.json`; `python3 .map/scripts/map_step_runner.py validate_prior_stage_consumption review` can fail missing spec/blueprint/test/diff inputs before review. Section-order flags reduce anchoring bias: `--reverse-sections` (invert order), `--shuffle-sections [--seed N]` (seeded random order), `--compare-orderings` (run default + reverse, aggregate via strict-wins, surface drift).
- **Run health report** - `/map-efficient`, `/map-debug`, `/map-check`, and `/map-review` write `.map/<branch>/run_health_report.json` during closeout via `.map/scripts/map_step_runner.py write_run_health_report`. The report is a machine-readable snapshot of terminal status, step progress, retry counters, artifact presence, and latest hook-injection status, including explicit skipped reasons for malformed hook input or insignificant Bash commands when branch state can be safely updated. CI or operators can fail inconsistent closeouts with `python3 .map/scripts/map_step_runner.py validate_run_health_report`.
- **Project memory** - `/map-learn` turns hard-won fixes and gotchas into reusable context for the next session.

## Core Commands

| Command | Use For |
|---------|---------|
| `/map-plan` | Start here for non-trivial work; clarify behavior and decompose tasks |
| `/map-efficient` | Implement an approved plan or already-scoped task |
| `/map-fast` | Small, low-risk changes where full planning would be overhead |
| `/map-check` | Quality gates, verification, and artifact checks |
| `/map-review` | Pre-commit semantic review against the plan, tests, and diff |
| `/map-learn` | Capture project memory and reusable lessons |
| `/map-debug` | Bug fixes and debugging |
| `/map-task` | Execute a single subtask from an existing plan |
| `/map-tdd` | Test-first implementation workflow |
| `/map-release` | Package release workflow |
| `/map-resume` | Resume interrupted workflows |

[Detailed usage and options ->](docs/USAGE.md)

Canonical MAP flows:

- Standard: `/map-plan` -> `/map-efficient` -> `/map-check` -> `/map-review` -> `/map-learn`
- Full TDD: `/map-plan` -> `/map-tdd` -> `/map-check` -> `/map-review` -> `/map-learn`
- Targeted subtask TDD: `/map-plan` -> `/map-tdd ST-001` -> `/map-task ST-001` -> ... -> `/map-check` -> `/map-review` -> `/map-learn`

`/map-plan` records a workflow-fit decision first, so trivial work can exit early with a direct edit or `/map-fast` recommendation instead of forcing full MAP planning.

These workflows maintain branch-scoped artifacts like `blueprint.json` with subtask size/concern contracts, `code-review-001.md`, `qa-001.md`, `verification-summary.md` with acceptance coverage and prior-stage consumption, `pr-draft.md`, `artifact_manifest.json`, `run_health_report.json` diagnostics, and run dossiers under `.map/<branch>/`. Targeted TDD flows also persist `test_contract_ST-00N.md` and `test_handoff_ST-00N.json` so `/map-task` can resume implementation from a clean red-phase handoff.

`LEARN` is the memory step of the MAP cycle. After implementation, checks, or review, MAP writes a learning handoff under `.map/<branch>/` so `/map-learn` can run later without reconstructing context. Pass `/map-learn [workflow-summary]` when you want to provide an explicit summary.

## Case Study

The DevOpsConf 2026 case study applies this process to a production Kubernetes Project Operator, not a toy CRUD app:

- human estimate: 90 days;
- MAP-style delivery: 7 days;
- workflow: `SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN`;
- small reviewable PRs instead of one giant generated diff;
- tests before implementation for critical pieces;
- semantic bugs caught in review before merge.

[DevOpsConf 2026 case study ->](https://github.com/azalio/devopsconf-ai-develop)

## How It Works

MAP orchestrates specialized roles through slash commands and skills:

```text
TaskDecomposer -> breaks goals into subtasks
Actor          -> implements scoped tasks
Monitor        -> validates quality and blocks invalid output
Predictor      -> analyzes impact for risky changes
Learner        -> captures reusable project memory
```

For Claude Code, MAP slash surfaces live in `.claude/skills/map-*/SKILL.md` files created by `mapify init`. The `.claude/commands/` directory is reserved for user-custom commands and a README that points back to the skill-backed MAP surfaces. The shipped skill catalog classifies skills with `skillClass`: MAP slash workflows are `task` skills, while `map-state` is a `hybrid` skill because it combines planning guidance with hooks/scripts that manage `.map/<branch>/` focus artifacts.

For Codex CLI, `mapify init . --provider codex` creates `.codex/skills/`, `.codex/agents/`, `.codex/config.toml`, hooks, and shared `.map/scripts/`.

Maintainers can audit both provider skill trees with `python -m mapify_cli.skill_ir src/mapify_cli/templates/skills src/mapify_cli/templates/codex/skills`. The command exits non-zero if a shipped skill has unsupported frontmatter, unresolved bundled references, or hidden prompt-injection-like text.

MAP is inspired by [MAP cognitive architecture](https://github.com/Shanka123/MAP) (Nature Communications, 2025), which reported a 74% improvement in planning tasks. The CLI turns that idea into a practical software development workflow.

[Architecture deep-dive ->](docs/ARCHITECTURE.md)

## Documentation

| Guide | Description |
|-------|-------------|
| [Installation](docs/INSTALL.md) | All install methods, PATH setup, troubleshooting |
| [Usage Guide](docs/USAGE.md) | Workflows, examples, cost optimization, playbook |
| [Architecture](docs/ARCHITECTURE.md) | Agents, MCP integration, customization |
| [Platform Spec](docs/MAP_PLATFORM_SPEC.md) | Platform refactor roadmap, codebase analysis |

## Trouble?

- **Command not found** -> Run `mapify init` in your project first.
- **Agent errors** -> Check `.claude/agents/` has all shipped agent `.md` files, or run `mapify doctor`.
- **Poor output on a complex task** -> Start with `/map-plan` and feed `/map-efficient` the approved plan instead of asking it to infer the architecture.
- [More help ->](docs/INSTALL.md#troubleshooting)

## Contributing

Improvements welcome: prompts for specific languages, new agents, provider integrations, and CI/CD workflow support.

## License

MIT

---

Start with `/map-plan`. Keep the model inside your engineering process, not the other way around.
