# MAP Framework for Claude Code CLI

A production-ready implementation of the **Modular Agentic Planner (MAP)** framework, inspired by prefrontal cortex functions, designed specifically for Claude Code CLI. This framework orchestrates 6 specialized AI agents to deliver high-quality software development with built-in validation and quality gates.

## 🧠 What is MAP?

MAP is a cognitive architecture that mimics how the human prefrontal cortex plans and executes complex tasks. Based on [Nature Communications research (2025)](https://github.com/Shanka123/MAP), it shows **74% performance improvement** in planning tasks by using specialized modules that work together.

### 🚀 Enhanced with MCP Integration

This implementation supercharges the original MAP framework with **MCP (Model Context Protocol) servers**, providing:

- **Persistent Knowledge**: Learn from every task and reuse successful patterns
- **Professional Code Review**: Automated security and quality analysis via claude-reviewer
- **Deep Reasoning**: Chain-of-thought problem solving with sequential-thinking
- **Code Generation**: Advanced algorithm implementation with codex-bridge

The combination of MAP's cognitive architecture + MCP's specialized tools creates an AI development system that continuously improves with use.

## 🚀 Quick Start

```bash
# Feature Development
claude "Use the orchestrator agent to implement user authentication with JWT tokens"

# Bug Fixing
claude "Use orchestrator to debug and fix the API 500 error on login endpoint"

# Refactoring
claude "Use orchestrator to refactor UserService class with dependency injection"

# Code Review
claude "Use monitor and evaluator agents to review the recent changes in auth.py"
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

The MAP framework consists of 6 specialized agents, each with a specific role:

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

4. **codex-bridge** - AI code generation
   - Advanced algorithm implementation
   - Multi-language support
   - Batch processing capabilities

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
| **Evaluator** | sequential-thinking, claude-reviewer, byterover, context7, deepwiki | Compare to industry standards |
| **Orchestrator** | byterover, sequential-thinking, claude-reviewer, context7, deepwiki | Documentation-driven workflow |

### Benefits of MCP Integration

- **🧠 Knowledge Persistence**: Solutions and patterns are automatically stored and retrieved
- **🔍 Enhanced Review**: Professional code review with security and performance analysis
- **🔄 Continuous Learning**: Each workflow improves future performance
- **⚡ Faster Development**: Reuse proven patterns and solutions
- **📊 Quality Metrics**: Track review history and quality trends

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
   - **Orchestrator** decides to proceed or iterate

### MCP-Enhanced Workflows

#### Example 1: Knowledge-Driven Development

```bash
claude "Use orchestrator to implement a caching layer for API responses.
The system should first search byterover for existing caching patterns,
use claude-reviewer for validation, and store the successful solution."
```

The MCP enhancement:

- **Byterover** retrieves proven caching patterns from past implementations
- **Codex-bridge** generates optimized cache invalidation logic
- **Claude-reviewer** provides security analysis for cache poisoning risks
- **Byterover** stores the validated solution for future reuse

#### Example 2: Learning from Past Reviews

```bash
claude "Use orchestrator to fix the authentication bug reported in issue #234.
Check claude-reviewer history for similar security issues and their resolutions."
```

The MCP enhancement:

- **Claude-reviewer history** reveals past authentication vulnerabilities
- **Byterover** retrieves successful security fixes
- **Sequential-thinking** ensures all edge cases are covered
- Solution is stored for future security audits

#### Example 3: Complex Refactoring with Impact Analysis

```bash
claude "Use orchestrator to refactor the database layer from ORM to raw SQL.
Use codex-bridge for query optimization and byterover for migration patterns."
```

The MCP enhancement:

- **Byterover** finds successful ORM → SQL migration patterns
- **Codex-bridge** generates optimized SQL queries
- **Sequential-thinking** plans the migration strategy
- **Claude-reviewer** validates performance improvements

#### Example 4: Library Integration with Current Documentation

```bash
claude "Use orchestrator to integrate Stripe payment processing.
First use context7 to get the latest Stripe API documentation,
then check deepwiki for how popular e-commerce repos handle payments."
```

The MCP enhancement:

- **Context7** provides up-to-date Stripe API documentation
- **Deepwiki** analyzes how repos like Shopify/Medusa handle payments
- **Actor** generates code using correct API versions
- **Monitor** validates against Stripe security best practices

#### Example 5: Learning from Open Source Projects

```bash
claude "Use orchestrator to implement a rate limiter.
Study how express-rate-limit and fastify repos implement this,
then create our own optimized version."
```

The MCP enhancement:

- **Deepwiki** reads rate limiting implementations from popular repos
- **Context7** gets documentation for Redis/memory store options
- **Sequential-thinking** designs optimal algorithm for our use case
- **Byterover** stores the pattern for future API endpoints

#### Example 6: Migration with Version-Specific Documentation

```bash
claude "Use orchestrator to migrate from React 17 to React 18.
Use context7 to check breaking changes and migration guide,
deepwiki to see how major projects handled the migration."
```

The MCP enhancement:

- **Context7** retrieves React 18 migration guide and breaking changes
- **Deepwiki** analyzes how Next.js, Gatsby migrated to React 18
- **Predictor** identifies all components needing updates
- **Monitor** validates concurrent features are properly implemented

### Common Use Cases

#### 1. Feature Development

```bash
claude "Use the orchestrator agent to implement a user profile page with avatar upload.
Include proper validation, error handling, and tests."
```

The orchestrator will:

- Decompose into subtasks (API endpoint, frontend component, image handling, tests)
- Iterate through each subtask with validation
- Ensure quality standards are met

#### 2. Bug Fixing

```bash
claude "Use orchestrator to debug why the payment processing fails for amounts over $1000.
Start by reproducing the issue, then trace and fix."
```

The framework will:

- Break down debugging steps (reproduce → trace → identify → fix → test)
- Validate each fix doesn't break other functionality
- Ensure comprehensive testing

#### 3. Refactoring

```bash
claude "Use orchestrator to refactor the OrderService to use dependency injection.
Maintain all existing functionality and tests."
```

MAP ensures:

- No behavior changes during refactoring
- All tests continue passing
- Code quality improvements are validated

#### 4. Code Review

```bash
claude "Use the monitor agent to review the changes in the auth module.
Then use predictor to analyze potential impacts and evaluator to score the quality."
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
claude "Use task-decomposer agent to break down: Add real-time notifications feature"

# Just code review
claude "Use monitor agent to review this code: [paste code]"

# Just impact analysis
claude "Use predictor agent to analyze impact of changing the User model schema"

# Just quality evaluation
claude "Use evaluator agent to score this implementation: [describe solution]"
```

#### Providing Context

Enhance agent responses with context:

```bash
claude "Use orchestrator to implement OAuth2 login.
Context: We use FastAPI, PostgreSQL, and already have a User model.
Constraints: Must support Google and GitHub providers."
```

#### Iterative Development

For complex features, work incrementally:

```bash
# Phase 1: Backend
claude "Use orchestrator to implement the backend API for todo list management"

# Phase 2: Frontend
claude "Use orchestrator to create React components for the todo list UI"

# Phase 3: Integration
claude "Use orchestrator to integrate frontend with backend and add tests"
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
claude "Use predictor to analyze impact before refactoring the database schema"
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

### Productivity Metrics

- **Subtask completion:** 90%+ without escalation
- **Time to feature:** 40-60% faster than manual
- **Bug rate:** 70% reduction with Monitor validation

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
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [Original Prefrontal Cortex Research](https://nature.com/articles/s41467-024-54941-4)

## 💡 Tips for Success

1. **Start Simple:** Begin with Actor + Monitor for basic tasks
2. **Add Complexity Gradually:** Introduce other agents as needed
3. **Learn Patterns:** Study successful workflows and adapt
4. **Track Metrics:** Monitor quality scores and iteration counts
5. **Iterate on Prompts:** Refine agent prompts based on results

---

*Remember: MAP is not just about automation—it's about achieving higher quality through structured validation and iterative improvement. The goal is not to replace developers but to augment their capabilities with AI-powered quality gates and systematic planning.*
