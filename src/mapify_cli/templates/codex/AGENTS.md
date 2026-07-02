# MAP Framework Agents

This project uses the MAP (Monitor-Actor-Predictor) Framework for structured development.

## Prerequisites

**Important:** You must trust this project in Codex settings for project-scoped
configuration to take effect. Without trust, `.codex/` config, hooks, and
agent files are ignored. Codex skills are installed under `.agents/skills`.

## Available Agents

| Agent | Role | Invoked By |
|-------|------|-----------|
| researcher | Codebase exploration and context gathering | $map-plan Step 0 |
| decomposer | Task decomposition into atomic subtasks | $map-plan Step 4 |
| monitor | Code review and validation | $map-plan SPEC_REVIEW, $map-efficient |

## Available Skills

| Skill | Purpose |
|-------|---------|
| $map-plan | Plan and decompose complex tasks |
| $map-efficient | Execute approved MAP plans end to end |
| $map-fast | Quick implementation for small changes |
| $map-check | Quality gates and verification |
| $map-review | Pre-landing code review (normal, adversarial, cross-AI) |

## Hooks

MAP uses a workflow gate hook that restricts file-modifying commands during
research and review phases. This prevents accidental edits while exploring.

**Note:** Hooks require `hooks = true` in config.toml and are not
supported on Windows.

## Mutation Boundary Constraints

For write-capable MAP skills and agents:

- Do not edit unrelated files, even if they are nearby or easy to clean up.
- Do not add, remove, or upgrade dependencies unless the current task or subtask explicitly names that dependency change.
- Do not refactor neighboring code unless the acceptance criteria cannot pass without that exact refactor.
- If a dependency change, broad refactor, or scope expansion seems necessary, report it as a blocker/tradeoff instead of doing it silently.

## Getting Started

1. Trust this project in Codex settings
2. Type `$map-plan <your task>` to start planning
3. Type `$map-efficient` to execute an approved plan
