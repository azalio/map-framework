# Common MCP Tool Patterns Reference

This document provides reference implementations of common MCP tool usage patterns used across MAP agent templates.

## Purpose

Agent templates intentionally duplicate certain MCP tool descriptions because:
1. **Agent Independence**: Each agent is invoked independently and needs complete context
2. **Self-Containment**: Agents cannot access external includes during invocation
3. **Context Clarity**: Full descriptions in each template prevent ambiguity

## Common MCP Tools

### 1. cipher_memory_search

**Purpose**: Search for existing patterns, solutions, and knowledge

**Query Patterns**:
- `"implementation pattern [feature_type]"` - Find similar implementations
- `"error solution [error_type]"` - Learn from past error fixes
- `"best practice [technology]"` - Get established patterns
- `"code review issue [pattern_type]"` - Find common review issues
- `"security vulnerability [code_pattern]"` - Security-specific searches

**When to Use**:
- Before implementing new features (Actor, Monitor)
- When curating knowledge (Curator)
- During reflection analysis (Reflector)
- Before adding playbook bullets (avoid duplicates)

**Typical Usage**:
```
mcp__cipher__cipher_memory_search({
  query: "implementation pattern JWT authentication",
  top_k: 5,
  similarity_threshold: 0.3
})
```

### 2. context7 (resolve-library-id + get-library-docs)

**Purpose**: Get current, up-to-date library/framework documentation

**Two-Step Process**:
1. `resolve-library-id`: Find the Context7-compatible library ID
2. `get-library-docs`: Retrieve documentation for specific topics

**When to Use**:
- Implementing features with external libraries (Actor)
- Verifying API usage in code review (Monitor)
- Creating TOOL_USAGE playbook bullets (Curator)
- Testing library-dependent code (Test Generator)

**Query Examples**:
- Library names: "Next.js", "React", "Django", "FastAPI", "SQLAlchemy"
- Topics: "hooks", "routing", "authentication", "error handling", "testing"

**Typical Usage**:
```
# Step 1: Resolve library ID
mcp__context7__resolve-library-id({
  libraryName: "Next.js"
})
# Returns: "/vercel/next.js"

# Step 2: Get docs
mcp__context7__get-library-docs({
  context7CompatibleLibraryID: "/vercel/next.js",
  topic: "routing",
  tokens: 5000
})
```

**Rationale**: Training data may be outdated. Current docs prevent using deprecated APIs.

### 3. codex-bridge (consult_codex)

**Purpose**: Generate optimized code for complex algorithms

**Query Format**: `"Generate [language] code for [specific_task]"`

**When to Use**:
- Complex algorithm implementation (Actor)
- Unfamiliar API usage
- Batch processing logic
- Advanced async patterns

**Query Examples**:
- "Generate Python code for batch processing with exponential backoff"
- "Generate TypeScript code for debounced search input with cancellation"
- "Generate Python code for LRU cache with TTL expiration"

**Typical Usage**:
```
mcp__codex-bridge__consult_codex({
  query: "Generate Python code for batch processing with exponential backoff",
  directory: "/path/to/project",
  format: "code",
  timeout: 60
})
```

### 4. deepwiki (read_wiki_structure + ask_question)

**Purpose**: Learn from production code in popular repositories

**Two-Step Process**:
1. `read_wiki_structure`: See available documentation topics
2. `ask_question`: Query specific implementation patterns

**When to Use**:
- Learning architectural patterns (Actor, Monitor)
- Validating security approaches (Monitor)
- Understanding production best practices (Curator)
- Researching testing strategies (Test Generator)

**Query Examples**:
- "How does [popular_repo] handle authentication?"
- "What are common mistakes when implementing websockets?"
- "How do production systems prevent N+1 queries?"

**Typical Usage**:
```
# Step 1: Read structure
mcp__deepwiki__read_wiki_structure({
  repoName: "facebook/react"
})

# Step 2: Ask question
mcp__deepwiki__ask_question({
  repoName: "facebook/react",
  question: "How does React handle error boundaries in production?"
})
```

### 5. claude-reviewer (request_review)

**Purpose**: Get professional AI code review

**When to Use**:
- After Actor implementation (Monitor)
- Before marking code as valid (Monitor)
- Systematic quality baseline (Monitor)

**Focus Areas**: "security", "performance", "testing", "architecture", "error-handling"

**Typical Usage**:
```
mcp__claude-reviewer__request_review({
  summary: "User authentication endpoint with JWT token generation",
  focus_areas: ["security", "error-handling", "testing"],
  test_command: "pytest tests/auth/"
})
```

### 6. cipher_extract_and_operate_memory

**Purpose**: Store successful patterns for future reference

**When to Use**:
- AFTER Monitor validates solution (Actor)
- After successful task completion (all agents)
- When reflecting on outcomes (Reflector)

**What to Store**:
- Pattern name
- Code snippet (working implementation)
- Context (when to use, prerequisites)
- Trade-offs (pros/cons vs alternatives)

**Typical Usage**:
```
mcp__cipher__cipher_extract_and_operate_memory({
  interaction: "Implemented JWT authentication with refresh tokens. Pattern: [description]. Trade-offs: [analysis].",
  memoryMetadata: {
    projectId: "project-123",
    domain: "security"
  },
  options: {
    useLLMDecisions: false,        // Use predictable similarity-based logic
    similarityThreshold: 0.85,     // Only 85%+ similar memories trigger UPDATE
    confidenceThreshold: 0.7       // Minimum confidence for operations
  }
})
```

## Decision Framework Template

Use this template for systematic MCP tool selection:

```
BEFORE [task], ask yourself:

1. Have we solved something similar before?
   → Use cipher_memory_search

2. Do I need current library/framework docs?
   → Use context7 (resolve-library-id → get-library-docs)

3. Is this a complex algorithm I'm unfamiliar with?
   → Use codex-bridge (consult_codex)

4. How do popular projects handle this?
   → Use deepwiki (read_wiki_structure → ask_question)

5. Do I need professional code review?
   → Use claude-reviewer (request_review)

6. Did my solution work successfully?
   → Use cipher_extract_and_operate_memory (store pattern)
```

## Agent-Specific MCP Usage

### Actor (Implementation)
- **Primary**: cipher_memory_search (find patterns), context7 (verify APIs)
- **Secondary**: codex-bridge (complex algorithms), deepwiki (architectural patterns)
- **Always**: cipher_extract_and_operate_memory (after Monitor approval)

### Monitor (Code Review)
- **Primary**: claude-reviewer (baseline review), cipher_memory_search (known issues)
- **Secondary**: context7 (verify library usage), deepwiki (compare with production patterns)

### Curator (Knowledge Management)
- **Primary**: cipher_memory_search (avoid duplicates)
- **Required**: context7 (verify TOOL_USAGE bullets)
- **Recommended**: deepwiki (ground recommendations in production code)

### Task Decomposer
- **Primary**: cipher_memory_search (find similar decompositions)
- **Recommended**: deepwiki (learn task breakdown patterns)

### Evaluator
- **Primary**: cipher_memory_search (find quality metrics)
- **Recommended**: context7 (verify scoring criteria)

### Predictor
- **Primary**: cipher_memory_search (find similar impact patterns)
- **Recommended**: deepwiki (learn dependency patterns)

### Reflector
- **Primary**: cipher_memory_search (find similar reflections)
- **Always**: Store insights via cipher_extract_and_operate_memory

### Test Generator
- **Primary**: cipher_memory_search (find test patterns)
- **Required**: context7 (verify test framework APIs)
- **Recommended**: deepwiki (learn testing strategies)

### Documentation Reviewer
- **Primary**: Fetch (validate external URLs/dependencies)
- **Required**: Read/Glob (find source of truth documents)
- **Recommended**: cipher_memory_search (find documentation anti-patterns)

## Best Practices

### 1. Search Before Implementing
Always search cipher before creating new code or knowledge:
```
Before: cipher_memory_search
During: Implementation
After: cipher_extract_and_operate_memory (if successful)
```

### 2. Verify Library APIs
Training data may be outdated. Always use context7 for external libraries:
```
Actor uses context7 → Gets current API
Monitor verifies → Catches deprecated usage
Curator references → Adds to playbook with current syntax
```

### 3. Learn from Production
Don't rely on theoretical examples. Use deepwiki to see battle-tested code:
```
Architectural decision needed → deepwiki
Security pattern needed → deepwiki (compare multiple repos)
Testing strategy needed → deepwiki (see what works in production)
```

### 4. Store Successful Patterns
Build institutional memory by storing what works:
```
Pattern works (Monitor approved) → cipher_extract_and_operate_memory
Future task similar → cipher_memory_search finds it
Avoid reinventing → Reuse proven pattern
```

## Common Anti-Patterns

### ❌ Don't: Skip cipher_memory_search
```
Actor: "Let me implement JWT authentication..."
(implements from scratch, misses existing pattern)
```

### ✅ Do: Search first
```
Actor: "Let me search for JWT patterns..."
cipher_memory_search("implementation pattern JWT authentication")
(finds existing pattern with security best practices)
```

### ❌ Don't: Assume training data is current
```
Actor: "I'll use jwt.encode(payload, secret)..."
(uses deprecated API from training data)
```

### ✅ Do: Verify with context7
```
Actor: "Let me verify JWT API..."
context7.resolve-library-id("PyJWT")
context7.get-library-docs("/pyjwt/pyjwt", "authentication")
(discovers algorithm parameter is now required)
```

### ❌ Don't: Store patterns without validation
```
Actor: "I'll store this pattern..."
(stores before Monitor review, pattern may be flawed)
```

### ✅ Do: Store only validated patterns
```
Monitor: valid=true (approved)
Actor: cipher_extract_and_operate_memory(pattern)
(stores only proven, reviewed patterns)
```

## Template Maintenance

When updating agent templates:
1. Keep MCP sections consistent with this reference
2. Update this file when adding new tools
3. Use linter to verify MCP descriptions include expected keywords
4. Maintain agent independence (don't assume includes)

## See Also

- `.claude/agents/CHANGELOG.md` - Template version history
- `scripts/lint-agent-templates.py` - Consistency validation
- `README.md` - MAP framework overview
