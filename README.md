# MAP Framework for Claude Code CLI

A production-ready implementation of the **Modular Agentic Planner (MAP)** framework, inspired by prefrontal cortex functions, designed specifically for Claude Code CLI. This framework orchestrates 8 specialized AI agents to deliver high-quality software development with built-in validation and quality gates.

## 🧠 What is MAP?

MAP is a cognitive architecture that mimics how the human prefrontal cortex plans and executes complex tasks. Based on [Nature Communications research (2025)](https://github.com/Shanka123/MAP), it shows **74% performance improvement** in planning tasks by using specialized modules that work together.

### 🚀 Enhanced with MCP Integration

This implementation supercharges the original MAP framework with **MCP (Model Context Protocol) servers**, providing:

- **Persistent Knowledge**: Learn from every task and reuse successful patterns
- **Professional Code Review**: Automated security and quality analysis via claude-reviewer
- **Deep Reasoning**: Chain-of-thought problem solving with sequential-thinking
- **Code Generation**: Advanced algorithm implementation with codex-bridge

### 🎓 Enhanced with ACE (Agentic Context Engineering)

This implementation also integrates **ACE (Agentic Context Engineering)** based on [arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1), providing:

- **Continuous Learning**: Reflector agent extracts lessons from successes and failures
- **Knowledge Playbook**: Curator agent maintains structured, evolving knowledge base
- **Semantic Search**: Find relevant patterns by meaning, not just keywords
- **Delta Updates**: Incremental playbook updates prevent context collapse

The combination of MAP's cognitive architecture + MCP's specialized tools + ACE's learning system creates an AI that improves with every task.

## 🚀 Quick Start

### Inside Claude Code (Recommended)
```bash
# Use slash commands:
/map-feature implement user authentication with JWT tokens
/map-debug fix the API 500 error on login endpoint
/map-refactor refactor UserService class with dependency injection
/map-review review the recent changes in auth.py
```

### From Command Line
```bash
# Feature Development (using custom agents)
claude --agents '{"orchestrator": {"prompt": "$(cat .claude/agents/orchestrator.md)"}}' \
  --print "implement user authentication with JWT tokens"

# Code Review
claude --agents '{"monitor": {"prompt": "$(cat .claude/agents/monitor.md)"}}' \
  --print "review the recent changes in auth.py"
```

## 📋 Prerequisites

1. **Claude Code CLI** installed and configured
2. This repository cloned to your local machine
3. Claude Code running in the project directory

```bash
# Clone the repository
git clone <repository-url>
cd map-framework

# Start Claude Code in this directory
claude
```

## 🏗️ Architecture

The MAP framework consists of 8 specialized agents, each with a specific role:

```bash
┌─────────────────────────────────────────────────────┐
│                 ORCHESTRATOR                         │
│         (Coordinates entire workflow)                │
└────────────────┬─────────────────────────────────────┘
                 │
     ┌───────────▼────────────┐
     │   TASK DECOMPOSER      │
     │   (Breaks down goals)   │
     └───────────┬────────────┘
                 │
     ┌───────────▼────────────────────────────┐
     │         For Each Subtask:              │
     │                                         │
     │  ┌─────────────────────────────┐       │
     │  │   ACTOR ←→ MONITOR Loop     │       │
     │  │  (Generate ←→ Validate)     │       │
     │  └──────────┬──────────────────┘       │
     │             │                           │
     │  ┌──────────▼──────────────────┐       │
     │  │  PREDICTOR → EVALUATOR      │       │
     │  │  (Impact → Quality Score)   │       │
     │  └──────────┬──────────────────┘       │
     │             │                           │
     │  ┌──────────▼──────────────────┐       │
     │  │  REFLECTOR → CURATOR        │       │
     │  │  (Learn → Update Playbook)  │       │
     │  └─────────────────────────────┘       │
     └─────────────────────────────────────────┘
```

## 🔌 MCP Integration

The MAP framework now **actively leverages MCP (Model Context Protocol) servers** for enhanced capabilities:

### Available MCP Servers

1. **claude-reviewer** - Professional code review with AI
   - Automated security and quality analysis
   - Historical review tracking
   - Focused review on specific areas

2. **sequential-thinking** - Chain-of-thought reasoning
   - Complex problem decomposition
   - Iterative refinement of solutions
   - Edge case discovery

3. **byterover** - Knowledge management system
   - Stores successful patterns and solutions
   - Retrieves relevant past implementations
   - Builds institutional knowledge over time

4. **codex-bridge** - AI code generation (⚠️ Requires 10-minute timeout)
   - Advanced algorithm implementation
   - Multi-language support
   - Batch processing capabilities
   - **Note**: Operations may take up to 10 minutes for complex tasks

5. **context7** - Up-to-date library documentation
   - Current API references for any library
   - Version-specific documentation
   - Best practices and code examples
   - Migration guides and deprecation notices

6. **deepwiki** - GitHub repository intelligence
   - Read documentation from any GitHub repo
   - Analyze architectural patterns
   - Learn from production implementations
   - Ask questions about repository structure

### How Agents Use MCP

| Agent | MCP Servers Used | Purpose |
|-------|-----------------|---------|
| **TaskDecomposer** | byterover, sequential-thinking, deepwiki, context7 | Find similar decompositions, learn from repos, check library docs |
| **Actor** | byterover, codex-bridge, context7, deepwiki | Retrieve patterns, generate code, use correct APIs |
| **Monitor** | claude-reviewer, byterover, sequential-thinking, context7, deepwiki | Professional review, validate library usage |
| **Predictor** | byterover, codex-bridge, deepwiki, context7 | Analyze impacts, check compatibility |
| **Evaluator** | sequential-thinking, claude-reviewer, cipher, context7, deepwiki | Compare to industry standards |
| **Reflector** | sequential-thinking, cipher, context7, deepwiki | Root cause analysis, verify correct approaches |
| **Curator** | cipher, context7, deepwiki | Check for duplicate patterns, verify API usage |
| **Orchestrator** | cipher, sequential-thinking, claude-reviewer, context7, deepwiki | Documentation-driven workflow |
| **DocumentationReviewer** | cipher, context7, deepwiki | Verify external dependencies, check CRDs, validate integrations |

### Benefits of MCP Integration

- **🧠 Knowledge Persistence**: Solutions and patterns are automatically stored and retrieved
- **🔍 Enhanced Review**: Professional code review with security and performance analysis
- **🔄 Continuous Learning**: Each workflow improves future performance
- **⚡ Faster Development**: Reuse proven patterns and solutions
- **📊 Quality Metrics**: Track review history and quality trends

### ACE Playbook Integration

The MAP framework now includes an **ACE-style knowledge playbook** that:

- **Learns from every task**: Reflector extracts patterns, Curator updates playbook
- **Semantic search**: Finds relevant patterns by meaning using sentence-transformers
- **Quality tracking**: Helpful/harmful counters validate patterns over time
- **Delta updates**: Incremental changes prevent context collapse

#### Semantic Search (Optional)

Install semantic search for meaning-based pattern retrieval:

```bash
pip install -r requirements-semantic.txt
```

**Benefits:**
- 🎯 Search by meaning, not keywords
- 🧠 Understands synonyms: "JWT signature" ≈ "token verification"
- ⚡ Auto-deduplication of similar patterns (90% similarity threshold)
- 💾 Embedding cache for fast retrieval

**Technical Details:**
- Model: `all-MiniLM-L6-v2` (80MB, 384 dimensions)
- Speed: ~3000 sentences/second on CPU
- Cache: `.claude/embeddings_cache/embeddings.pkl`

If not installed, playbook falls back to keyword matching automatically.

See [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md) for setup details and troubleshooting.

## 🤖 Agent Descriptions

### 1. **TaskDecomposer** (`task-decomposer`)

Breaks complex requirements into atomic, testable subtasks.

**Capabilities:**

- Analyzes feature requirements and codebase structure
- Creates logical task sequences with dependencies
- Outputs structured JSON with acceptance criteria
- Limits to ~8 subtasks for manageable scope

**Output:** JSON with subtasks, dependencies, and acceptance criteria

### 2. **Actor** (`actor`)

Generates production-ready code implementations.

**Capabilities:**

- Creates multiple solution approaches
- Writes clean, testable code
- Includes error handling and edge cases
- Follows project patterns and standards

**Output:** Code implementation with approach explanation and trade-offs

### 3. **Monitor** (`monitor`)

Reviews code for bugs, security issues, and violations.

**Capabilities:**

- Validates correctness and completeness
- Checks security vulnerabilities
- Ensures code quality and standards
- Provides actionable feedback

**Output:** JSON with validation results and specific issues

### 4. **Predictor** (`predictor`)

Analyzes change impact across the codebase.

**Capabilities:**

- Traces dependencies and side effects
- Identifies breaking changes
- Finds affected tests and documentation
- Assesses risk levels

**Output:** JSON with affected components and required updates

### 5. **Evaluator** (`evaluator`)

Scores solution quality across multiple dimensions.

**Capabilities:**

- Scores: functionality, quality, performance, security, testability, completeness
- Provides objective quality metrics
- Recommends: proceed, improve, or reconsider
- Estimates distance to goal

**Output:** JSON with scores and recommendations

### 6. **Orchestrator** (`orchestrator`)

Manages the entire MAP workflow.

**Capabilities:**

- Coordinates all agents in proper sequence
- Manages iteration loops with caps (3-5 max)
- Makes progression decisions
- Handles blockers and escalations

**Output:** Status updates and workflow management

### 7. **Reflector** (`reflector`)

Extracts structured lessons from successes and failures.

**Capabilities:**

- Performs root cause analysis using chain-of-thought reasoning
- Identifies patterns from both successful and failed implementations
- Creates actionable insights with code examples
- Tags existing playbook bullets as helpful or harmful

**Output:** JSON with root cause analysis, correct approaches, and playbook updates

### 8. **Curator** (`curator`)

Manages evolving knowledge playbook with incremental updates.

**Capabilities:**

- Applies delta operations (ADD, UPDATE, DEPRECATE) to playbook
- Prevents duplicate patterns with semantic deduplication
- Maintains quality scores for each pattern
- Syncs high-quality patterns to byterover MCP

**Output:** JSON with delta operations applied to playbook

### 9. **DocumentationReviewer** (`documentation-reviewer`)

Reviews technical documentation for completeness, external dependencies, and integration requirements.

**Capabilities:**

- Automatically fetches and verifies all external URLs mentioned in documentation
- Detects CRDs (Custom Resource Definitions) and installation requirements
- Identifies integration adapters and configuration needs
- Validates consistency between architecture documents and implementation specs
- Checks for missing external dependencies before implementation

**Output:** JSON with external dependencies checked, missing requirements, and validation score

## 📚 Usage Guide

### Basic Workflow

The typical MAP workflow follows this pattern:

1. **Orchestrator** receives your goal
2. **TaskDecomposer** breaks it into subtasks
3. For each subtask:
   - **Actor** generates implementation
   - **Monitor** validates (loop if invalid)
   - **Predictor** analyzes impact
   - **Evaluator** scores quality
   - **Reflector** extracts lessons learned
   - **Curator** updates knowledge playbook
   - **Orchestrator** decides to proceed or iterate

### MCP-Enhanced Workflows

#### Example 1: Knowledge-Driven Development

```bash
# Inside Claude Code:
/map-feature implement a caching layer for API responses

# Or from CLI:
claude --agents '{"orchestrator": {"prompt": "$(cat .claude/agents/orchestrator.md)"}}' \
  --print "implement a caching layer for API responses"
```

The MCP enhancement:

- **Byterover** retrieves proven caching patterns from past implementations
- **Codex-bridge** generates optimized cache invalidation logic (10-min timeout for complex analysis)
- **Claude-reviewer** provides security analysis for cache poisoning risks
- **Byterover** stores the validated solution for future reuse

#### Example 2: Learning from Past Reviews

```bash
# Inside Claude Code:
/map-debug fix the authentication bug reported in issue #234

# Or from CLI:
claude --agents '{"orchestrator": {"prompt": "$(cat .claude/agents/orchestrator.md)"}}' \
  --print "fix the authentication bug reported in issue #234"
```

The MCP enhancement:

- **Claude-reviewer history** reveals past authentication vulnerabilities
- **Byterover** retrieves successful security fixes
- **Sequential-thinking** ensures all edge cases are covered
- Solution is stored for future security audits

#### Example 3: Complex Refactoring with Impact Analysis

```bash
# Inside Claude Code:
/map-refactor refactor the database layer from ORM to raw SQL

# Or from CLI:
claude --agents '{"orchestrator": {"prompt": "$(cat .claude/agents/orchestrator.md)"}}' \
  --print "refactor the database layer from ORM to raw SQL"
```

The MCP enhancement:

- **Byterover** finds successful ORM → SQL migration patterns
- **Codex-bridge** generates optimized SQL queries (allows up to 10 minutes for complex migrations)
- **Sequential-thinking** plans the migration strategy
- **Claude-reviewer** validates performance improvements

#### Example 4: Library Integration with Current Documentation

```bash
/map-feature integrate Stripe payment processing.
First use context7 to get the latest Stripe API documentation,
then check deepwiki for how popular e-commerce repos handle payments.
```

The MCP enhancement:

- **Context7** provides up-to-date Stripe API documentation
- **Deepwiki** analyzes how repos like Shopify/Medusa handle payments
- **Actor** generates code using correct API versions
- **Monitor** validates against Stripe security best practices

#### Example 5: Learning from Open Source Projects

```bash
/map-feature implement a rate limiter.
Study how express-rate-limit and fastify repos implement this,
then create our own optimized version.
```

The MCP enhancement:

- **Deepwiki** reads rate limiting implementations from popular repos
- **Context7** gets documentation for Redis/memory store options
- **Sequential-thinking** designs optimal algorithm for our use case
- **Byterover** stores the pattern for future API endpoints

#### Example 6: Migration with Version-Specific Documentation

```bash
/map-feature migrate from React 17 to React 18.
Use context7 to check breaking changes and migration guide,
deepwiki to see how major projects handled the migration.
```

The MCP enhancement:

- **Context7** retrieves React 18 migration guide and breaking changes
- **Deepwiki** analyzes how Next.js, Gatsby migrated to React 18
- **Predictor** identifies all components needing updates
- **Monitor** validates concurrent features are properly implemented

### Common Use Cases

#### 1. Feature Development

```bash
/map-feature implement a user profile page with avatar upload.
Include proper validation, error handling, and tests.
```

The orchestrator will:

- Decompose into subtasks (API endpoint, frontend component, image handling, tests)
- Iterate through each subtask with validation
- Ensure quality standards are met

#### 2. Bug Fixing

```bash
/map-debug debug why the payment processing fails for amounts over $1000.
Start by reproducing the issue, then trace and fix.
```

The framework will:

- Break down debugging steps (reproduce → trace → identify → fix → test)
- Validate each fix doesn't break other functionality
- Ensure comprehensive testing

#### 3. Refactoring

```bash
/map-refactor refactor the OrderService to use dependency injection.
Maintain all existing functionality and tests.
```

MAP ensures:

- No behavior changes during refactoring
- All tests continue passing
- Code quality improvements are validated

#### 4. Code Review

```bash
/map-review review the changes in the auth module.
Then use predictor to analyze potential impacts and evaluator to score the quality.
```

This provides:

- Detailed security and quality review
- Impact analysis across codebase
- Objective quality scoring

### Advanced Usage

#### Using Individual Agents

While the orchestrator manages the full workflow, you can use agents individually:

```bash
# Just decomposition
# Use Task tool in Claude Code with subagent_type="task-decomposer"
# Or: claude --agents \'{"decomposer": {"prompt": "$(cat .claude/agents/task-decomposer.md)"}}\' --print "break down: Add real-time notifications feature"

# Just code review
/map-review review this code: [paste code]

# Just impact analysis
# Use Task tool in Claude Code with subagent_type="predictor"
# Or: claude --agents \'{"predictor": {"prompt": "$(cat .claude/agents/predictor.md)"}}\' --print "analyze impact of changing the User model schema"

# Just quality evaluation
# Use Task tool in Claude Code with subagent_type="evaluator"
# Or: claude --agents \'{"evaluator": {"prompt": "$(cat .claude/agents/evaluator.md)"}}\' --print "score this implementation: [describe solution]"
```

#### Providing Context

Enhance agent responses with context:

```bash
/map-feature implement OAuth2 login.
Context: We use FastAPI, PostgreSQL, and already have a User model.
Constraints: Must support Google and GitHub providers.
```

#### Iterative Development

For complex features, work incrementally:

```bash
# Phase 1: Backend
/map-feature implement the backend API for todo list management

# Phase 2: Frontend
/map-feature create React components for the todo list UI

# Phase 3: Integration
/map-feature integrate frontend with backend and add tests
```

#### Inspecting the Playbook

Check what MAP has learned:

```bash
# View playbook statistics
python -m mapify_cli.playbook_manager stats

# Search for relevant patterns
python -m mapify_cli.playbook_manager search "JWT authentication"

# View high-quality patterns ready for sync
python -m mapify_cli.playbook_manager sync
```

## 🎯 Best Practices

### 1. **Clear Requirements**

Provide specific, measurable requirements:

```bash
# Good ✅
"Implement user registration with email validation, password strength check (8+ chars, 1 number, 1 special), and send confirmation email"

# Vague ❌
"Add user registration"
```

### 2. **Incremental Approach**

Break large features into phases:

- Phase 1: Core functionality
- Phase 2: Edge cases and error handling
- Phase 3: Optimization and polish

### 3. **Context Matters**

Always provide relevant context:

- Technology stack
- Existing patterns
- Constraints
- Performance requirements

### 4. **Review Loops**

Use Monitor after Actor for quality:

```bash
claude "First use actor to implement the cache layer,
then use monitor to review for thread safety and memory leaks"
```

### 5. **Impact Analysis**

Always run Predictor before major changes:

```bash
/map-feature analyze impact before refactoring the database schema  # (predictor runs automatically in workflow)
```

## 🛠️ Troubleshooting

### Issue: Agent Not Found

```
Error: Agent 'orchestrator' not found
```

**Solution:** Ensure you're in the map-framework directory with `.claude/agents/` subdirectory.

### Issue: JSON Parse Errors

```
Error: Invalid JSON in agent response
```

**Solution:** Agents output strict JSON. Ensure prompts request JSON format explicitly.

### Issue: Infinite Loops

```
Actor-Monitor loop exceeding iterations
```

**Solution:** The orchestrator caps at 3-5 iterations. If stuck, provide more specific requirements or constraints.

### Issue: Conflicting Changes

```
Multiple subtasks modifying same file
```

**Solution:** TaskDecomposer should sequence dependent tasks. Use orchestrator to reorder if needed.

### Issue: Semantic Search Not Working

```
Warning: sentence-transformers not installed
```

**Solution:** Install semantic search dependencies:
```bash
pip install -r requirements-semantic.txt
```

See [SEMANTIC_SEARCH_SETUP.md](SEMANTIC_SEARCH_SETUP.md) for detailed troubleshooting.

## 📊 Performance Tips

### 1. **Model Selection**

Currently all agents use `sonnet`. For cost optimization, consider:

- `haiku` for Predictor/Evaluator (faster, cheaper)
- `opus` for Orchestrator (critical decisions only)
- `sonnet` for Actor/Monitor/TaskDecomposer (balanced)

### 2. **Iteration Limits**

Set reasonable iteration caps:

- Simple tasks: 1-2 iterations
- Complex tasks: 3-5 iterations
- Blocked after 5: needs human input

### 3. **Subtask Sizing**

Keep subtasks small and focused:

- Each subtask: 2-4 hours of work
- Clear acceptance criteria
- Minimal dependencies

## 🔧 Customization

### Configuring MCP Servers

To enable MCP integration, ensure these servers are configured in your Claude Code setup:

```bash
# Install MCP servers (if not already available)
npm install -g @anthropic/claude-reviewer
npm install -g @anthropic/sequential-thinking
npm install -g @anthropic/byterover-mcp
npm install -g @anthropic/codex-bridge

# Configure in Claude Code settings
claude config add-mcp claude-reviewer
claude config add-mcp sequential-thinking
claude config add-mcp byterover-mcp
claude config add-mcp codex-bridge
```

#### Important: Codex-Bridge Timeout Configuration

**CRITICAL**: The codex-bridge MCP server requires a **10-minute timeout** for complex operations. The MAP framework automatically configures this in the MCP config, but when using codex-bridge directly:

```python
# Always specify timeout=600 (10 minutes) for complex operations
result = mcp__codex-bridge__consult_codex(
    query="your complex query",
    directory=".",
    timeout=600  # 10 minutes in seconds
)
```

This extended timeout is necessary for:
- Complex algorithm generation
- Large-scale code analysis
- Multi-file dependency tracing
- Thorough impact prediction

### Modifying Agent Prompts

Edit agents in `.claude/agents/`:

```bash
# Example: Make monitor stricter on security
edit .claude/agents/monitor.md
# Add to SECURITY section:
# - OWASP Top 10 compliance required
# - All inputs must be sanitized
# - Authentication required for all endpoints
```

### Adding Project Context

Use template variables in agent prompts:

- `{{project_name}}`
- `{{language}}`
- `{{framework}}`
- `{{standards_url}}`

These can be injected when calling agents.

## 📈 Metrics & Success Indicators

### Quality Metrics

- **Monitor approval rate:** >80% first-try approval
- **Evaluator scores:** Average >7.0/10
- **Iteration count:** <3 per subtask
- **Playbook growth:** Steady increase in high-quality patterns

### Productivity Metrics

- **Subtask completion:** 90%+ without escalation
- **Time to feature:** 40-60% faster than manual
- **Bug rate:** 70% reduction with Monitor validation
- **Pattern reuse:** Increasing retrieval of existing solutions

## 🤝 Contributing

Improvements welcome! Consider:

- Enhanced prompts for specific languages/frameworks
- Additional specialized agents
- Integration scripts for CI/CD
- Success story examples

## 📄 License

MIT License - See LICENSE file for details.

## 🔗 References

- [MAP Paper - Nature Communications](https://github.com/Shanka123/MAP)
- [ACE Paper - arXiv:2510.04618v1](https://arxiv.org/abs/2510.04618v1)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [Original Prefrontal Cortex Research](https://nature.com/articles/s41467-024-54941-4)

## 💡 Tips for Success

1. **Start Simple:** Begin with Actor + Monitor for basic tasks
2. **Add Complexity Gradually:** Introduce other agents as needed
3. **Learn Patterns:** Study successful workflows and adapt
4. **Track Metrics:** Monitor quality scores and iteration counts
5. **Iterate on Prompts:** Refine agent prompts based on results
6. **Use the Playbook:** Let ACE learn and reuse successful patterns

---

*Remember: MAP is not just about automation—it's about achieving higher quality through structured validation and iterative improvement. The goal is not to replace developers but to augment their capabilities with AI-powered quality gates and systematic planning.*
