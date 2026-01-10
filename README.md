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

## Quick Start

**1. Install**
```bash
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
| `/map-efficient` | Production features (recommended) |
| `/map-debug` | Bug fixes and debugging |
| `/map-review` | Pre-commit code review |
| `/map-fast` | Throwaway prototypes only |

[All commands and options →](docs/USAGE.md)

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
- **Agent errors** → Check `.claude/agents/` has all 11 `.md` files
- [More help →](docs/INSTALL.md#troubleshooting)

## Contributing

Improvements welcome: prompts for specific languages, new agents, CI/CD integrations.

## License

MIT

---

**MAP brings structure to AI-assisted development.** Start with `/map-efficient` and see the difference.
