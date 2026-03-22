# MAP Framework for Claude Code

[![PyPI version](https://badge.fury.io/py/mapify-cli.svg)](https://pypi.org/project/mapify-cli/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> Structured AI development workflows that replace ad-hoc prompting with **plan → execute → validate** loops.

Based on [MAP cognitive architecture](https://github.com/Shanka123/MAP) (Nature Communications, 2025) — 74% improvement in planning tasks.

## Why MAP?

- **Structured workflows** — 11 specialized agents instead of single-prompt chaos
- **Quality gates** — automatic validation catches errors before they compound
- **40-60% cost savings** — prevents circular reasoning and scope creep
- **Learning system** — captures patterns for reuse across projects
- **Persistent artifacts** — `/map-plan`, `/map-efficient`, and `/map-check` keep branch-scoped research, session, review, QA, and verification artifacts inside `.map/<branch>/`

## Quick Start

**1. Install**
```bash
uv tool install mapify-cli

# or with pip
pip install mapify-cli
```

**2. Initialize** (in your project)
```bash
cd your-project
mapify init
```

**3. Start Claude Code and run your first workflow**
```bash
claude
```
```
/map-efficient implement user authentication with JWT tokens
```

**You'll know it's working when:** Claude spawns specialized agents (TaskDecomposer → Actor → Monitor) with structured output instead of freeform responses.

## Core Commands

| Command | Use For |
|---------|---------|
| `/map-efficient` | Production features, refactoring, complex tasks (recommended) |
| `/map-debug` | Bug fixes and debugging |
| `/map-fast` | Small, low-risk changes |
| `/map-debate` | Complex decisions with multi-variant synthesis |
| `/map-review` | Pre-commit code review |
| `/map-check` | Quality gates and verification |
| `/map-plan` | Task decomposition without implementation |
| `/map-task` | Execute a single subtask from an existing plan |
| `/map-tdd` | Test-first implementation workflow |
| `/map-release` | Package release workflow |
| `/map-resume` | Resume interrupted workflows |
| `/map-learn` | Extract lessons after workflow completion |

[Detailed usage and options →](docs/USAGE.md)

Canonical MAP flows:

- Standard: `/map-plan` -> `/map-efficient` -> `/map-check` -> `/map-review`
- Full TDD: `/map-plan` -> `/map-tdd` -> `/map-check` -> `/map-review`
- Targeted subtask TDD: `/map-plan` -> `/map-tdd ST-001` -> `/map-task ST-001` -> ... -> `/map-check` -> `/map-review`

These workflows maintain branch-scoped artifacts like `code-review-001.md`, `qa-001.md`, `verification-summary.md`, `pr-draft.md`, and run dossiers under `.map/<branch>/`.

## How It Works

MAP orchestrates specialized agents through slash commands:

```
TaskDecomposer → breaks goal into subtasks
     ↓
   Actor → generates code
     ↓
  Monitor → validates quality (loop if needed)
     ↓
 Predictor → analyzes impact (for risky changes)
```

The orchestration lives in `.claude/commands/map-*.md` prompts created by `mapify init`.

[Architecture deep-dive →](docs/ARCHITECTURE.md)

## Documentation

| Guide | Description |
|-------|-------------|
| [Installation](docs/INSTALL.md) | All install methods, PATH setup, troubleshooting |
| [Usage Guide](docs/USAGE.md) | Workflows, examples, cost optimization, playbook |
| [Architecture](docs/ARCHITECTURE.md) | Agents, MCP integration, customization |

## Trouble?

- **Command not found** → Run `mapify init` in your project first
- **Agent errors** → Check `.claude/agents/` has all 11 shipped agent `.md` files
- [More help →](docs/INSTALL.md#troubleshooting)

## Contributing

Improvements welcome: prompts for specific languages, new agents, CI/CD integrations.

## License

MIT

---

**MAP brings structure to AI-assisted development.** Start with `/map-efficient` and see the difference.
