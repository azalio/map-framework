# Introduction to MAP Framework

## What is MAP?

**MAP** (Modular Agentic Planner) is a cognitive architecture for AI agents, inspired by functions of the prefrontal cortex.

**Scientific basis:**

- Based on the study **[Nature Communications (2025)](https://arxiv.org/pdf/2310.00194)**: up to **74%** improvement on planning tasks
- Extended by **[ACE](https://arxiv.org/abs/2510.04618v1)** (Agentic Context Engineering) from arXiv:2510.04618v1
- Optimized for **Claude Code CLI**

**Current version:** 2.2.0

## Core Concepts

### 8 Specialized Agents

MAP coordinates 8 agents via the Orchestrator:

1. **[TaskDecomposer](https://github.com/azalio/map-framework/blob/main/.claude/agents/task-decomposer.md)** — breaks goals into atomic subtasks
2. **[Actor](https://github.com/azalio/map-framework/blob/main/.claude/agents/actor.md)** — generates code and solutions
3. **[Monitor](https://github.com/azalio/map-framework/blob/main/.claude/agents/monitor.md)** — validates quality, safety, and correctness
4. **[Predictor](https://github.com/azalio/map-framework/blob/main/.claude/agents/predictor.md)** — analyzes the impact of changes on the codebase
5. **[Evaluator](https://github.com/azalio/map-framework/blob/main/.claude/agents/evaluator.md)** — assesses solution quality (functionality, security, testability)
6. **[Reflector](https://github.com/azalio/map-framework/blob/main/.claude/agents/reflector.md)** — extracts lessons from successes and failures
7. **[Curator](https://github.com/azalio/map-framework/blob/main/.claude/agents/curator.md)** — manages the knowledge base (playbook)
8. **[DocumentationReviewer](https://github.com/azalio/map-framework/blob/main/.claude/agents/documentation-reviewer.md)** — checks documentation completeness and correctness

The **Orchestrator** is the workflow coordination logic implemented in slash commands (`.claude/commands/map-*.md`), not a separate agent template.

### Integration with MCP Servers

MAP uses **6 MCP servers** to extend capabilities:

- **[cipher](https://github.com/campfirein/cipher)** — knowledge base for storing successful patterns
- **[claude-reviewer](https://github.com/rsokolowski/mcp-claude-reviewer)** — professional code review with security analysis
- **[sequential-thinking](https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking)** — chains of thought for complex tasks
- **[codex-bridge](https://github.com/elyin/codex-bridge)** — code generation via chatgtp (requires 10-minute timeout)
- **[context7](https://github.com/upstash/context7)** — up-to-date library documentation
- **[deepwiki](https://docs.devin.ai/work-with-devin/deepwiki-mcp)** — GitHub repository analysis

### ACE Playbook — Learning System

**Structure:**

- Stored at [.claude/playbook.json](https://github.com/azalio/map-framework/blob/main/.claude/playbook.json)
- **10 categories of patterns**: architecture, implementation, security, performance, errors, testing, code quality, tool usage, debugging, CLI tool patterns
- **top_k = 5**: returns only the 5 most relevant patterns to reduce cognitive load
- **Automatic learning**: Reflector extracts patterns from every task, Curator incrementally updates the playbook

## Benefits

### Cost Optimization

**Model allocation strategy:**

- Predictor, Evaluator: **haiku** (fast analysis)
- Actor, Monitor, TaskDecomposer, Reflector, Curator, DocumentationReviewer: **sonnet** (quality-critical)

### Agent Context Isolation

Using the Task tool for agent invocation provides:

- **Fresh context window:** Each agent gets an isolated context window without the main session’s history
- **No contamination:** Prior chat with the user does not bias the agent’s decisions
- **Task focus:** Agent sees only what’s relevant (subtask description, playbook bullets, feedback)

**Result:** More accurate and consistent agent decisions

### Context Engineering

**Recitation Pattern:**

- The **Orchestrator** creates `.map/current_plan.md` with visual progress markers (✓, →, ☐, ✗)
- Keeps goals “fresh” in context on long-running tasks

### Installation

**3 installation paths:**

1. **mapify CLI** (recommended):

   ```bash
   uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli
   mapify init my-project
   ```

2. **Clone Repository** — full repo clone
3. **Copy Agents** — copy agents into an existing project

**Requirements:** Python 3.11+
