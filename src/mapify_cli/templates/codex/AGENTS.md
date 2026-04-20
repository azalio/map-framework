# MAP Framework Agents

This project uses the MAP (Monitor-Actor-Predictor) Framework for structured development.

## Prerequisites

**Important:** You must trust this project in Codex settings for project-scoped
configuration to take effect. Without trust, `.codex/` files are ignored.

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
| $map-fast | Quick implementation for small changes |
| $map-check | Quality gates and verification |

## Hooks

MAP uses a workflow gate hook that restricts file-modifying commands during
research and review phases. This prevents accidental edits while exploring.

**Note:** Hooks require `codex_hooks = true` in config.toml and are not
supported on Windows.

## Getting Started

1. Trust this project in Codex settings
2. Type `$map-plan <your task>` to start planning
3. Follow the guided workflow
