# MAP Framework Plugin

Official Claude Code plugin for MAP Framework - Modular Agentic Planner with cognitive architecture inspired by prefrontal cortex functions.

## What is MAP Framework?

MAP (Modular Agentic Planner) is a cognitive architecture that orchestrates 11 specialized agents to improve code quality through systematic validation and iterative refinement.

**Based on research:**
- [MAP Paper - Nature Communications (2025)](https://github.com/Shanka123/MAP) — 74% improvement in planning tasks


## Features

### 9 Specialized Agents

1. **TaskDecomposer** — breaks goals into atomic subtasks
2. **Actor** — generates code and solutions
3. **Monitor** — validates quality, security, correctness
4. **Predictor** — analyzes change impact across codebase
5. **Evaluator** — scores solution quality (functionality, security, testability)
6. **Reflector** — extracts lessons from successes and failures
7. **DocumentationReviewer** — checks documentation completeness
8. **Research-Agent** — isolated codebase research
9. **Final-Verifier** — adversarial verification (Ralph Loop)

### Claude Code Integration

**5 Automated Hooks:**
- `validate-agent-templates` — prevents accidental removal of template variables
- `enrich-context` — enriches prompts with relevant knowledge
- `session-init` — loads workflow context at session start
- `track-metrics` — tracks agent performance
- `workflow-gate` — enforces workflow step sequencing

**12 Slash Commands:**
- `/map-efficient` — implement features, refactor code, complex tasks with full MAP workflow
- `/map-debug` — debug issues using MAP analysis
- `/map-fast` — small, low-risk changes with minimal overhead
- `/map-review` — comprehensive review of changes
- `/map-check` — quality gates and verification
- `/map-plan` — architecture decomposition
- `/map-task` — execute one planned subtask
- `/map-tdd` — test-first implementation workflow
- `/map-release` — release workflow with validation gates
- `/map-resume` — resume interrupted workflows
- `/map-learn` — extract and preserve lessons
- `/map-understand` — teach and quiz until a target makes sense

### Cost Optimization

Intelligent model selection per agent:
- **Haiku** for analysis (Predictor, Evaluator) — fast and cheap
- **Sonnet** for implementation (Actor, Monitor) — balanced quality
- **Opus** for orchestration — critical decisions

**Result:** 40-60% cost reduction vs using sonnet everywhere

## Installation

### Option 1: Via mapify CLI

```bash
# Install mapify
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli

# Initialize in your project
cd your-project
mapify init

# Note: Copy .mcp.json.example to .mcp.json and adjust for your setup if needed
```

### Option 2: Manual Installation

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

**Recommended MCP Servers:**
- `sequential-thinking` — chain-of-thought reasoning

## Quick Start

```bash
# Feature development / refactoring / complex tasks
/map-efficient implement user authentication with JWT tokens

# Debugging
/map-debug fix the API 500 error on login endpoint

# Small, low-risk changes
/map-fast add environment variable for API timeout

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
    │  │ REFLECTOR             │       │
    │  │ (learn → patterns)   │       │
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
