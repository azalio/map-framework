# Getting Started with MAP Framework

## Prerequisites

**Python 3.11+** — minimum version required to install MAP Framework

**Optional:**

- **sentence-transformers** — semantic search over the playbook (`requirements-semantic.txt`)
- **Model:** all-MiniLM-L6-v2 (80MB, 384 dimensions)
- **Cache:** `.claude/embeddings_cache/` for faster repeated searches

## 3 Installation Options

MAP Framework supports **3 installation paths** depending on your use case:

### 1. mapify CLI (Recommended)

Use the official CLI tool to initialize projects:

**Install via UV:**

```bash
uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli
```

**Update PATH (if needed):**

After install, ensure `~/.local/bin` is on your PATH:

```bash
# Check installation
which mapify

# If not found, add to PATH:
# Zsh (default on macOS/Linux):
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# Bash:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Or use UV’s automatic shell update:
uv tool update-shell
```

**Create a new project:**

```bash
mapify init my-project
```

**Initialize an existing project:**

```bash
mapify init .
```

**Initialize in the current directory:**

```bash
mapify init .
```

**Benefits:**

- Automatic project structure setup
- Copies all 8 agents and 4 slash commands
- Creates `.claude/playbook.db` with a starter structure
- Best choice for new projects

### 2. Clone Repository

Full repository clone (for customization):

```bash
git clone https://github.com/azalio/map-framework.git
cd map-framework
```

**Benefits:**

- Full access to source code
- Ability to customize agents
- Explore internals and architecture
- Good for contributors

### 3. Copy Agents (Manual Integration)

Copy selected components into an existing project:

**Structure to copy:**

```bash
.claude/
├── agents/           # 8 agent template files
│   ├── task-decomposer.md
│   ├── actor.md
│   ├── monitor.md
│   ├── predictor.md
│   ├── evaluator.md
│   ├── reflector.md
│   ├── curator.md
│   └── documentation-reviewer.md
├── commands/         # 4 slash commands
│   ├── map-feature.md
│   ├── map-debug.md
│   ├── map-refactor.md
│   └── map-review.md
└── playbook.db       # ACE knowledge base (SQLite)
```

**Benefits:**

- Maximum control over integration
- Pick-and-choose components
- Fits projects with unique structure

## First Commands

After installation, you have **4 core workflow commands**:

### /map-feature — Implement New Features

```bash
/map-feature Implement user authentication with JWT tokens
```

Automatically decomposes the task, implements, validates, and extracts reusable patterns for future work.

### /map-debug — Debug Issues

```bash
/map-debug Fix authentication middleware returning 401 for valid tokens
```

Diagnoses and fixes issues with detailed analysis and impact prediction.

### /map-refactor — Refactor Code

```bash
/map-refactor Extract database queries into repository pattern
```

Refactors with impact prediction and quality assessment.

### /map-review — Review Documentation

```bash
/map-review Check API documentation for completeness
```

Comprehensive technical documentation review for completeness and correctness.

## Configuration

### Playbook Structure

Installation creates `.claude/playbook.db` with a starter structure:

**Metadata:**

```json
{
  "metadata": {
    "total_bullets": 21,
    "sections_count": 10,
    "top_k": 5
  }
}
```

**10 Pattern Categories:**

1. ARCHITECTURE_PATTERNS
2. IMPLEMENTATION_PATTERNS
3. SECURITY_PATTERNS
4. PERFORMANCE_PATTERNS
5. ERROR_PATTERNS
6. TESTING_STRATEGIES
7. CODE_QUALITY_RULES
8. TOOL_USAGE
9. DEBUGGING_TECHNIQUES
10. CLI_TOOL_PATTERNS

**top_k = 5:** Actor receives only the 5 most relevant patterns per task (reduces cognitive load)

### MCP Servers Integration

MAP requires **6 MCP servers** for full functionality:

**Required:**

- **cipher** — knowledge base for storing successful patterns
- **claude-reviewer** — professional code review with security analysis

**Optional (recommended):**

- **sequential-thinking** — chains of thought for complex tasks
- **codex-bridge** — code generation (requires 10-minute timeout)
- **context7** — up-to-date library documentation
- **deepwiki** — GitHub repository analysis

**Configuration:**
Create `.claude/mcp_config.json` (or configure via Claude Code settings) to connect MCP servers.

### Template Variables

**Critical:** Do NOT remove Handlebars variables from agent templates:

**Required variables:**

- `{{language}}` — programming language of the project
- `{{project_name}}` — project name
- `{{framework}}` — framework in use
- `{{#if playbook_bullets}}` — playbook integration
- `{{#if feedback}}` — retry loop integration
- `{{subtask_description}}` — description of the current subtask

**Validation tool:** `scripts/lint-agent-templates.py` to validate templates

## Next Steps

After installation:

1. **Run your first workflow:**

   ```bash
   /map-feature Implement hello world endpoint
   ```

2. **Inspect the generated plan:**
   - Open `.map/current_plan.md`
   - Watch progress markers

3. **Review results:**
   - Check `.map/logs/workflow_*.log` for event tracking
   - Open `.claude/playbook.db` for automatically extracted patterns

4. **Configure MCP servers:**
   - Connect cipher for cross-project knowledge
   - Add context7 for up-to-date library docs

5. **Customize agents:**
   - Adapt templates to your coding style
   - Add project-specific constraints

---
