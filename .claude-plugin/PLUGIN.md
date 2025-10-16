# MAP Framework Plugin

Official Claude Code plugin for MAP Framework - Modular Agentic Planner with cognitive architecture inspired by prefrontal cortex functions.

## What is MAP Framework?

MAP (Modular Agentic Planner) is a cognitive architecture that orchestrates 9 specialized agents to improve code quality through systematic validation and iterative refinement.

**Based on research:**
- [MAP Paper - Nature Communications (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1) — continuous learning from experience

## Features

### 9 Specialized Agents

1. **TaskDecomposer** — breaks goals into atomic subtasks
2. **Actor** — generates code and solutions
3. **Monitor** — validates quality, security, correctness
4. **Predictor** — analyzes change impact across codebase
5. **Evaluator** — scores solution quality (functionality, security, testability)
6. **Reflector** — extracts lessons from successes and failures
7. **Curator** — manages knowledge base (playbook)
8. **Orchestrator** — coordinates all agents
9. **DocumentationReviewer** — checks documentation completeness

### Claude Code Integration

**5 Automated Hooks:**
- `validate-agent-templates` — prevents accidental removal of template variables
- `auto-store-knowledge` — automatically saves successful patterns to cipher
- `enrich-context` — enriches prompts with relevant knowledge
- `session-init` — loads ACE playbook at session start
- `track-metrics` — tracks agent performance

**4 Slash Commands:**
- `/map-feature` — implement new features with full MAP workflow
- `/map-debug` — debug issues using MAP analysis
- `/map-refactor` — refactor code with impact analysis
- `/map-review` — comprehensive review of changes

### ACE Learning System

- **Persistent Knowledge** — solutions saved and reused via cipher MCP
- **Semantic Search** — find patterns by meaning (optional)
- **Quality Tracking** — monitor pattern effectiveness
- **Continuous Learning** — each workflow improves future ones

### Cost Optimization

Intelligent model selection per agent:
- **Haiku** for analysis (Predictor, Evaluator) — fast and cheap
- **Sonnet** for implementation (Actor, Monitor) — balanced quality
- **Opus** for orchestration — critical decisions

**Result:** 40-60% cost reduction vs using sonnet everywhere

## Installation

### Option 1: Via Plugin Marketplace (Recommended)

```bash
# In Claude Code:
/plugin marketplace add https://raw.githubusercontent.com/azalio/map-framework/main/.claude-plugin/marketplace.json
/plugin install map-framework
```

### Option 2: Via mapify CLI

```bash
# Install mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Initialize in your project
cd your-project
mapify init

# Note: Copy .mcp.json.example to .mcp.json and adjust for your setup if needed
```

### Option 3: Manual Installation

```bash
# Clone repository
git clone https://github.com/azalio/map-framework.git

# Copy agents, commands, and hooks
cp -r map-framework/.claude/agents your-project/.claude/
cp -r map-framework/.claude/commands your-project/.claude/
cp -r map-framework/.claude/hooks your-project/.claude/
cp map-framework/.claude/settings.hooks.json your-project/.claude/
```

## Requirements

- **Claude Code CLI** — installed and configured
- **MCP Servers** (essential):
  - `cipher` — knowledge management
  - `claude-reviewer` — professional code review
  - `sequential-thinking` — chain-of-thought reasoning

**Recommended MCP Servers:**
- `codex-bridge` — AI code generation
- `context7` — library documentation
- `deepwiki` — GitHub repository analysis

## Quick Start

```bash
# Feature development
/map-feature implement user authentication with JWT tokens

# Debugging
/map-debug fix the API 500 error on login endpoint

# Refactoring
/map-refactor refactor UserService class with dependency injection

# Code review
/map-review review the recent changes in auth.py
```

## Architecture

```
┌──────────────────────────────────────────┐
│          ORCHESTRATOR                    │
│    (coordinates entire workflow)         │
└───────────────┬──────────────────────────┘
                │
    ┌───────────▼────────────┐
    │   TASK DECOMPOSER      │
    │   (breaks into tasks)   │
    └───────────┬────────────┘
                │
    ┌───────────▼─────────────────────┐
    │   For each subtask:             │
    │                                  │
    │  ┌──────────────────────┐       │
    │  │  ACTOR ←→ MONITOR    │       │
    │  │  (code ←→ validate)  │       │
    │  └──────────┬───────────┘       │
    │             │                    │
    │  ┌──────────▼───────────┐       │
    │  │ PREDICTOR→EVALUATOR  │       │
    │  │ (impact → quality)   │       │
    │  └──────────┬───────────┘       │
    │             │                    │
    │  ┌──────────▼───────────┐       │
    │  │ REFLECTOR → CURATOR  │       │
    │  │ (learn → knowledge)  │       │
    │  └──────────────────────┘       │
    └──────────────────────────────────┘
```

## Documentation

- **Main README:** [github.com/azalio/map-framework](https://github.com/azalio/map-framework)
- **Hooks Documentation:** [.claude/hooks/README.md](https://github.com/azalio/map-framework/blob/main/.claude/hooks/README.md)
- **Agent Templates:** [.claude/agents/](https://github.com/azalio/map-framework/tree/main/.claude/agents)

## Support

- **Issues:** [github.com/azalio/map-framework/issues](https://github.com/azalio/map-framework/issues)
- **Discussions:** [github.com/azalio/map-framework/discussions](https://github.com/azalio/map-framework/discussions)

## License

MIT License — see [LICENSE](https://github.com/azalio/map-framework/blob/main/LICENSE) file for details.
