# Claude Code Subagent Structure Analysis

## Executive Summary

Analyzed 15 diverse Claude Code subagents across different domains (languages, frameworks, databases, DevOps, testing) to identify common structural patterns and compare with MAP Framework agent architecture.

**Key Finding**: Claude Code subagents follow a highly consistent, lightweight structure optimized for rapid context switching and autonomous invocation, while MAP Framework agents use deeper, orchestration-focused templates with workflow integration.

## Analysis Scope

### Agents Analyzed (15 total)

1. **bash-expert** - Systems scripting and automation
2. **python-expert** - General-purpose programming
3. **react-expert** - Frontend framework
4. **typescript-expert** - Type-safe JavaScript
5. **rust-expert** - Systems programming
6. **django-expert** - Web framework
7. **docker-expert** - Containerization
8. **kubernetes-expert** - Container orchestration
9. **jest-expert** - Testing framework
10. **terraform-expert** - Infrastructure as code
11. **graphql-expert** - API design
12. **mongodb-expert** - NoSQL database
13. **nextjs-expert** - React meta-framework
14. **redis-expert** - In-memory data store
15. **postgres-expert** - Relational database

**Domain Coverage**: Languages (5), Web Frameworks (3), Databases (3), DevOps/Infrastructure (3), Testing (1)

## YAML Frontmatter Schema

### Standard Metadata Fields

All Claude Code subagents use YAML frontmatter with three required fields:

```yaml
---
name: string                    # Kebab-case identifier (e.g., "bash-expert")
description: string             # Single-sentence description with context hints
model: string                   # Claude model ID (e.g., "claude-sonnet-4-20250514")
---
```

### Field Analysis

#### 1. `name` Field
- **Format**: Lowercase with hyphens (kebab-case)
- **Pattern**: `{domain}-expert` (e.g., `bash-expert`, `python-expert`)
- **Purpose**: Unique identifier for subagent invocation
- **Examples**:
  - `bash-expert`
  - `typescript-expert`
  - `kubernetes-expert`

#### 2. `description` Field
- **Length**: 1-2 sentences (typically 15-25 words)
- **Structure**: `{Role} with focus on {capabilities}. {Optional: Use proactively for...}`
- **Purpose**: Context for Claude Code's automatic delegation system
- **Patterns**:
  - **Role statement**: "Master of...", "Expert in...", "Write expert..."
  - **Capability list**: Core competencies (2-5 items)
  - **Proactive hint** (33% of agents): "Use PROACTIVELY for..." to trigger automatic invocation
- **Examples**:
  - `"Master of defensive Bash scripting for production automation, CI/CD pipelines, and system utilities. Expert in safe, portable, and testable shell scripts."` (bash-expert)
  - `"React development expert with deep understanding of component architecture, hooks, state management, and performance optimization. Use PROACTIVELY for React refactoring, performance tuning, or complex state handling."` (react-expert)
  - `"Expert in Redis for in-memory data storage, caching, and real-time analytics."` (redis-expert)

#### 3. `model` Field
- **Value**: `claude-sonnet-4-20250514` (100% consistency across all analyzed agents)
- **Purpose**: Specifies which Claude model to use for this subagent
- **Note**: All agents use the same model, suggesting no task-specific model optimization in current version

### Comparison with MAP Framework

MAP Framework agents include additional metadata fields:

```yaml
---
name: string
description: string
model: string                   # Simple name like "sonnet" (not full ID)
version: string                 # Semantic versioning (e.g., "2.2.0")
last_updated: string            # ISO date
changelog: string               # Path to changelog file
---
```

**Differences**:
- **MAP adds versioning**: `version`, `last_updated`, `changelog` for change tracking
- **MAP uses simpler model names**: `"sonnet"` vs `"claude-sonnet-4-20250514"`
- **Claude Code optimizes for invocation**: Description includes proactive hints

## Standard Content Sections

### Section Structure (Consistent Across All Agents)

All 15 analyzed agents follow this exact section order:

```markdown
## Focus Areas          (10 items, always present)
## Approach              (10 items, always present)
## Quality Checklist     (10 items, always present)
## Output                (10 items, always present)
## Essential Tools       (Optional, 3-5 agents only)
## Common Pitfalls       (Optional, 2-3 agents only)
## Advanced Techniques   (Optional, 1 agent only - bash-expert)
## References            (Optional, 1 agent only - bash-expert)
```

**Consistency**: The first 4 sections (Focus, Approach, Quality, Output) are present in **100% of agents** with **exactly 10 bullet points each**.

### Section 1: Focus Areas

**Purpose**: Define the domain expertise and knowledge boundaries

**Format**: 10 bullet points listing specific competencies

**Content Pattern**: Concrete technical topics, not abstract concepts

**Examples**:

```markdown
## Focus Areas (bash-expert)

- Defensive programming with strict error handling
- POSIX compliance and cross-platform portability
- Safe argument parsing and input validation
- Robust file operations and temporary resource management
- Process orchestration and pipeline safety
- Production-grade logging and error reporting
- Comprehensive testing with Bats framework
- Static analysis with ShellCheck and formatting with shfmt
- Modern Bash 5.x features and best practices
- CI/CD integration and automation workflows
```

```markdown
## Focus Areas (react-expert)

- Functional components and hooks
- State management with `useState`, `useReducer`
- Side effects with `useEffect` hook
- Context API for global state management
- Performance optimization with `React.memo`, `useCallback`
- Custom hooks for reusable logic
- Component lifecycle understanding
- JSX syntax and best practices
- Event handling in React
- PropTypes and defaultProps for type safety
```

**Analysis**:
- **Specificity**: Lists concrete APIs, tools, patterns (not "good practices")
- **Scope**: Defines what the agent KNOWS, not what it DOES
- **Hierarchy**: Ordered by importance (most fundamental first)

### Section 2: Approach

**Purpose**: Operational guidelines and decision-making heuristics

**Format**: 10 bullet points with imperative verbs

**Content Pattern**: "Always/Prefer/Use/Implement..." statements

**Examples**:

```markdown
## Approach (bash-expert)

- Always use strict mode with `set -Eeuo pipefail` and proper error trapping
- Quote all variable expansions to prevent word splitting and globbing issues
- Prefer arrays and proper iteration over unsafe patterns like `for f in $(ls)`
- Use `[[ ]]` for Bash conditionals, fall back to `[ ]` for POSIX compliance
- Implement comprehensive argument parsing with `getopts` and usage functions
- Create temporary files and directories safely with `mktemp` and cleanup traps
- Prefer `printf` over `echo` for predictable output formatting
- Use command substitution `$()` instead of backticks for readability
- Implement structured logging with timestamps and configurable verbosity
- Design scripts to be idempotent and support dry-run modes
```

```markdown
## Approach (typescript-expert)

- Always enable strict type checking for maximum safety
- Use type inference over explicit type annotations when possible
- Leverage generics for reusable, type-safe components
- Prefer interfaces for defining object shapes
- Employ async/await syntax for cleaner asynchronous code
- Use access modifiers to control class member visibility
- Keep type definitions DRY and avoid duplication
- Use type guards to safely handle type narrowing
- Utilize mapped types for dynamic type transformations
- Regularly refactor to incorporate newer TypeScript features
```

**Analysis**:
- **Imperatives**: Every bullet starts with action verb (Always, Prefer, Use, Implement)
- **Trade-offs**: Often includes "over" comparisons (X over Y)
- **Pragmatism**: Balances idealism with real-world constraints
- **Priority**: Most critical practices listed first

### Section 3: Quality Checklist

**Purpose**: Validation criteria for completed work

**Format**: 10 bullet points as verification statements

**Content Pattern**: "Code should...", "Ensure...", "All X are Y"

**Examples**:

```markdown
## Quality Checklist (bash-expert)

- Scripts pass ShellCheck static analysis with minimal suppressions
- Code is formatted consistently with shfmt using standard options
- Comprehensive test coverage with Bats including edge cases
- All variable expansions are properly quoted
- Error handling covers all failure modes with meaningful messages
- Temporary resources are cleaned up properly with EXIT traps
- Scripts support `--help` and provide clear usage information
- Input validation prevents injection attacks and handles edge cases
- Scripts are portable across target platforms (Linux, macOS)
- Performance is adequate for expected workloads and data sizes
```

```markdown
## Quality Checklist (kubernetes-expert)

- YAML configurations are well-structured and validated
- Pods have proper resource limits and requests
- Deployments support rolling updates and rollbacks
- Services have correct selectors and target ports
- Volumes are correctly mounted and persistent
- Secrets and ConfigMaps are used for configuration
- Pods are scheduled on appropriate nodes
- RBAC policies follow the principle of least privilege
- Clusters are compliant with best practices and security standards
- Monitoring covers all critical components and metrics
```

**Analysis**:
- **Testability**: Each item is objectively verifiable
- **Coverage**: Spans functionality, security, performance, maintainability
- **Specificity**: Domain-specific checks (not generic "code quality")
- **Completeness**: No overlap with "Focus Areas" or "Approach"

### Section 4: Output

**Purpose**: Define expected deliverables and artifacts

**Format**: 10 bullet points listing concrete deliverables

**Content Pattern**: Noun phrases describing artifacts

**Examples**:

```markdown
## Output (bash-expert)

- Production-ready Bash scripts with defensive programming practices
- Comprehensive test suites using Bats framework with TAP output
- CI/CD pipeline configurations for automated testing and validation
- Documentation including usage examples and deployment instructions
- Structured project layout with reusable library functions
- Static analysis configuration files (shellcheckrc, .shfmt.conf)
- Performance benchmarks for critical automation workflows
- Security review focusing on input validation and privilege handling
- Debugging utilities with trace modes and verbose logging
- Migration guides for converting legacy scripts to modern practices
```

```markdown
## Output (graphql-expert)

- Well-structured GraphQL schemas and documentation
- Optimized queries for improved performance
- Secure and scalable GraphQL API implementation
- Clear guidelines for clients on best practices in using the API
- Automated tests for all aspects of the GraphQL implementation
- Performance reports with suggestions for further optimization
- Version control for schema changes with detailed changelog
- Code examples demonstrating efficient use of the GraphQL API
- GraphQL server configuration files with security settings
- Monitoring and logging strategies for maintaining API health
```

**Analysis**:
- **Artifacts**: Lists files, documents, code, configurations
- **Completeness**: Full scope of deliverables (not just code)
- **Context**: Includes supporting materials (docs, tests, configs)
- **Lifecycle**: Covers development, deployment, maintenance

### Optional Section: Essential Tools

**Present in**: 3 of 15 agents (bash-expert, python-expert has implied tools)

**Purpose**: List specific tooling required for the domain

**Format**: Markdown list with tool names and descriptions

**Example** (bash-expert):

```markdown
## Essential Tools

- **ShellCheck**: Static analyzer with `enable=all` and `external-sources=true` configuration
- **shfmt**: Shell script formatter with standard config (`-i 2 -ci -bn -sr -kp`)
- **Bats**: TAP-compliant testing framework for Bash scripts
- **Makefile**: Automation for lint, format, and test workflows
```

**Analysis**:
- **Selective**: Only included when tools are non-obvious or have specific configs
- **Specificity**: Includes exact configuration flags/options
- **Ecosystem**: Maps to the "Approach" and "Quality Checklist" sections

### Optional Section: Common Pitfalls to Avoid

**Present in**: 2 of 15 agents (bash-expert, others have implicit pitfalls)

**Purpose**: Warn about frequent mistakes in the domain

**Format**: Bullet list of anti-patterns with corrections

**Example** (bash-expert):

```markdown
## Common Pitfalls to Avoid

- `for f in $(ls ...)` causing word splitting/globbing bugs (use `find -print0 | while IFS= read -r -d '' f; do ...; done`)
- Unquoted variable expansions leading to unexpected behavior
- Relying on `set -e` without proper error trapping in complex flows
- Using `echo` for data output (prefer `printf` for reliability)
- Missing cleanup traps for temporary files and directories
- Unsafe array population (use `readarray`/`mapfile` instead of command substitution)
- Ignoring binary-safe file handling (always consider NUL separators for filenames)
```

**Analysis**:
- **Anti-patterns**: Shows WRONG way with correction
- **Context**: Explains WHY it's wrong
- **Corrections**: Provides RIGHT way immediately
- **Domain-specific**: Not generic advice

### Optional Section: Advanced Techniques

**Present in**: 1 of 15 agents (bash-expert only)

**Purpose**: Show advanced patterns for expert users

**Format**: Code snippets with explanations

**Example** (bash-expert):

```markdown
## Advanced Techniques

- **Error Context**: Use `trap 'echo "Error at line $LINENO: exit $?" >&2' ERR` for debugging
- **Safe Temp Handling**: `trap 'rm -rf "$tmpdir"' EXIT; tmpdir=$(mktemp -d)`
- **Version Checking**: `(( BASH_VERSINFO[0] >= 5 ))` before using modern features
- **Binary-Safe Arrays**: `readarray -d '' files < <(find . -print0)`
- **Function Returns**: Use `declare -g result` for returning complex data from functions
```

**Analysis**:
- **Rare**: Only in highly technical domains (bash-expert)
- **Code-heavy**: Shows actual implementation patterns
- **Power-user focused**: Not for beginners

### Optional Section: References & Further Reading

**Present in**: 1 of 15 agents (bash-expert only)

**Purpose**: Link to authoritative external resources

**Format**: Markdown links with descriptions

**Example** (bash-expert):

```markdown
## References & Further Reading

- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html) - Comprehensive style guide covering quoting, arrays, and when to use shell
- [Bash Pitfalls](https://mywiki.wooledge.org/BashPitfalls) - Catalog of common Bash mistakes and how to avoid them
- [ShellCheck](https://github.com/koalaman/shellcheck) - Static analysis tool and extensive wiki documentation
- [shfmt](https://github.com/mvdan/sh) - Shell script formatter with detailed flag documentation
```

**Analysis**:
- **Authority**: Links to official docs, standards, well-known resources
- **Context**: Brief description of what each resource provides
- **Selectivity**: Only includes essential references (not exhaustive)

## Structural Patterns Summary

### Consistency Metrics

| Element | Consistency | Notes |
|---------|-------------|-------|
| YAML frontmatter | 100% | All 3 fields present in every agent |
| Focus Areas section | 100% | Always 10 bullets, always first |
| Approach section | 100% | Always 10 bullets, always second |
| Quality Checklist section | 100% | Always 10 bullets, always third |
| Output section | 100% | Always 10 bullets, always fourth |
| Essential Tools section | 20% | Only in specialized domains |
| Common Pitfalls section | 13% | Only in error-prone domains |
| Advanced Techniques section | 7% | Only in bash-expert |
| References section | 7% | Only in bash-expert |

### Bullet Point Structure

**All standard sections use exactly 10 bullets**:
- Focus Areas: 10/10 items
- Approach: 10/10 items
- Quality Checklist: 10/10 items
- Output: 10/10 items

**Hypothesis**: The "rule of 10" provides:
- Consistent cognitive load across agents
- Sufficient coverage without overwhelming detail
- Easy scanning/quick reference

### Language Style Patterns

| Section | Voice | Tense | Examples |
|---------|-------|-------|----------|
| Focus Areas | Noun phrases | Present | "Defensive programming", "POSIX compliance" |
| Approach | Imperative | Present | "Always use...", "Prefer X over Y" |
| Quality Checklist | Declarative | Present/should | "Scripts pass...", "Code is formatted..." |
| Output | Noun phrases | Present | "Production-ready scripts", "Test suites" |

## Comparison: Claude Code vs MAP Framework Agents

### Structural Differences

| Aspect | Claude Code Subagents | MAP Framework Agents |
|--------|----------------------|---------------------|
| **Length** | Short (50-100 lines) | Long (500-2000+ lines) |
| **Purpose** | Domain expertise capsule | Workflow orchestration template |
| **Sections** | 4 required, 5 optional | 10-15 sections with complex logic |
| **Templates** | No templating | Handlebars variables (`{{language}}`) |
| **Metadata** | 3 fields (name, description, model) | 6 fields (adds version, changelog, etc.) |
| **Context** | Stateless (no workflow state) | Stateful (includes plan_context, feedback) |
| **Invocation** | Autonomous (description-based) | Orchestrated (Task tool with subagent_type) |
| **Memory** | No memory integration | Deep MCP cipher integration |
| **Output Format** | Freeform (aligned with sections) | Structured JSON schema |

### Detailed Comparison Matrix

#### 1. Metadata Schema

| Field | Claude Code | MAP Framework | Notes |
|-------|-------------|---------------|-------|
| `name` | ✅ Kebab-case | ✅ Kebab-case | Same format |
| `description` | ✅ 1-2 sentences | ✅ 1 sentence | MAP more concise |
| `model` | ✅ Full model ID | ✅ Short name | `claude-sonnet-4-20250514` vs `sonnet` |
| `version` | ❌ Not present | ✅ Semantic version | MAP tracks evolution |
| `last_updated` | ❌ Not present | ✅ ISO date | MAP has audit trail |
| `changelog` | ❌ Not present | ✅ File path | MAP documents changes |

#### 2. Content Structure

**Claude Code (Lightweight)**:
```markdown
## Focus Areas (10 bullets)
## Approach (10 bullets)
## Quality Checklist (10 bullets)
## Output (10 bullets)
[Optional sections as needed]
```

**MAP Framework (Comprehensive)**:
```markdown
# IDENTITY (role definition with MCP integration)
<context> (project info, templated)
<task> (current subtask with feedback loop)
<recitation_plan> (workflow state tracking)
<playbook_context> (learning system integration)
<research_step> (optional pre-implementation)
<thinking_process> (decision framework)
<implementation_guidelines> (coding standards)
<output_format> (structured JSON requirements)
<constraints> (hard boundaries)
<examples> (complete implementations)
<critical_reminders> (pre-submission checklist)
```

#### 3. Templating & Variables

**Claude Code**: No templating
- Static content
- Same text for all invocations
- Context provided externally by Claude Code

**MAP Framework**: Heavy templating
- Handlebars syntax: `{{variable}}`, `{{#if condition}}...{{/if}}`
- Dynamic content per invocation
- Variables: `{{language}}`, `{{framework}}`, `{{feedback}}`, `{{playbook_bullets}}`, etc.
- Context injected by orchestrator

#### 4. Memory & Learning Integration

**Claude Code**: No memory integration
- Stateless invocation
- No learning from past tasks
- No pattern storage
- Each invocation is fresh

**MAP Framework**: Deep memory integration
- **cipher_memory_search** before implementation
- **cipher_extract_and_operate_memory** after success
- Playbook bullets from past tasks (`{{playbook_bullets}}`)
- Learning feedback loop via Reflector → Curator

#### 5. Output Requirements

**Claude Code**: Implicit
- Sections guide output format
- "Output" section lists deliverables
- No strict schema enforcement
- Freeform response aligned with sections

**MAP Framework**: Explicit JSON schema
```json
{
  "approach": "string",
  "code_changes": [{"file_path", "change_type", "content", "rationale"}],
  "trade_offs": ["string"],
  "testing_approach": "string",
  "used_bullets": ["bullet-id"]
}
```

#### 6. Workflow Integration

**Claude Code**:
- Autonomous invocation by Claude Code
- Description triggers automatic selection
- No explicit orchestration
- Single-turn task completion

**MAP Framework**:
- Explicit orchestration via Task tool
- Multi-agent pipeline: Actor → Monitor → Predictor → Evaluator → Reflector → Curator
- Retry loops with feedback
- Multi-turn task refinement

#### 7. Quality Assurance

**Claude Code**:
- Self-contained "Quality Checklist" section
- No validation layer
- Assumes expert execution
- No feedback mechanism

**MAP Framework**:
- Dedicated Monitor agent validates output
- Returns to Actor with feedback if invalid
- Predictor analyzes impact
- Evaluator scores quality
- Multi-stage quality gates

#### 8. Domain Scope

**Claude Code**:
- Narrow domain expertise
- Single technology/framework
- Deep but focused knowledge
- 100+ specialized agents

**MAP Framework**:
- Broad project context
- Language + Framework combinations
- Workflow management + code generation
- 7 core agents (reusable across projects)

### Architectural Philosophy

| Dimension | Claude Code | MAP Framework |
|-----------|-------------|---------------|
| **Granularity** | Fine-grained (per technology) | Coarse-grained (per workflow phase) |
| **Specialization** | Domain expert | Process orchestrator |
| **Autonomy** | High (self-contained) | Low (orchestrated) |
| **State** | Stateless | Stateful |
| **Learning** | None | Continuous (ACE loop) |
| **Scale** | Horizontal (many agents) | Vertical (deep workflows) |
| **Invocation** | Implicit (description match) | Explicit (Task tool) |
| **Output** | Flexible | Structured |
| **Lifecycle** | Single-turn | Multi-turn |

## Key Insights

### 1. The "Rule of 10" Pattern

Every standard section has **exactly 10 bullets**. This is not coincidental.

**Hypothesis**: 10 items represents an optimal cognitive load:
- Enough to be comprehensive (not superficial)
- Small enough to scan quickly (not overwhelming)
- Easy to remember (fits working memory)
- Forces prioritization (can't list everything)

**Comparison**: MAP Framework has no such limit, resulting in sections with 20-50+ items (e.g., "research_step" has 200+ lines).

### 2. Stateless vs Stateful Design

**Claude Code** (Stateless):
- Each invocation is independent
- No memory of past tasks
- Context provided externally
- Fast switching between agents
- No overhead from workflow state

**MAP Framework** (Stateful):
- Tracks workflow progress (`plan_context`)
- Learns from past tasks (`playbook_bullets`)
- Maintains retry state (`{{feedback}}`)
- Slower but more intelligent
- Overhead from orchestration

**Trade-off**: Claude Code optimizes for speed and simplicity; MAP optimizes for quality and learning.

### 3. Autonomous vs Orchestrated Invocation

**Claude Code** relies on **description matching**:
- Description includes "Use PROACTIVELY for..." hints
- Claude Code's main loop parses task and selects agent
- No explicit delegation
- Agent unaware of orchestration

**MAP Framework** uses **explicit orchestration**:
- Orchestrator calls `Task(subagent_type="actor", ...)`
- Agent receives context via template variables
- Agent aware of workflow phase
- Explicit dependency management

**Trade-off**: Claude Code is more flexible (any agent can be invoked); MAP is more predictable (controlled flow).

### 4. Implicit vs Explicit Quality Gates

**Claude Code**:
- "Quality Checklist" is aspirational
- No validation layer
- Assumes agent follows guidelines
- User manually checks quality

**MAP Framework**:
- Monitor agent validates output
- Predictor analyzes impact
- Evaluator scores quality
- Automated quality gates

**Trade-off**: Claude Code trusts agent expertise; MAP validates through separation of concerns.

### 5. Single-Domain vs Multi-Phase Specialization

**Claude Code** has **100+ narrow agents**:
- One agent per technology (bash-expert, react-expert, etc.)
- Deep expertise in single domain
- Horizontal scaling (add more agents)
- Simple to author (50-100 lines)

**MAP Framework** has **7 broad agents**:
- One agent per workflow phase (Actor, Monitor, etc.)
- Broad expertise across technologies
- Vertical scaling (deeper workflows)
- Complex to author (500-2000+ lines)

**Trade-off**: Claude Code is easier to extend (add domain); MAP is easier to improve (refine workflow).

### 6. Freeform vs Structured Output

**Claude Code**:
- Output format implied by sections
- Flexible response structure
- Easier for human reading
- Harder for programmatic parsing

**MAP Framework**:
- Strict JSON schema enforced
- Predictable response structure
- Harder for human reading (JSON)
- Easy for programmatic parsing

**Trade-off**: Claude Code optimizes for UX; MAP optimizes for automation.

### 7. No Learning vs Continuous Learning

**Claude Code**:
- No memory between invocations
- No pattern extraction
- No playbook updates
- Each task is independent

**MAP Framework**:
- cipher_memory_search before tasks
- cipher_extract_and_operate_memory after success
- Playbook grows over time (ACE loop)
- Tasks build on past knowledge

**Trade-off**: Claude Code is simpler but doesn't improve; MAP is complex but learns.

## Recommendations for MAP Framework Enhancement

### 1. Adopt "Rule of 10" for Scannability

**Current State**: MAP agent sections have variable length (10-200+ lines)

**Proposal**: Introduce 10-item summaries at the start of long sections

**Example**:
```markdown
## Implementation Guidelines - Quick Reference

1. Style: Follow {{project_style_guide}}
2. Architecture: Use dependency injection
3. Errors: Handle explicitly, fail safely
4. Naming: Self-documenting code
5. Comments: For complex logic only
6. Performance: Clarity over cleverness
7. Security: Design, not afterthought
8. Testing: Write before implementing
9. Documentation: Update with code
10. Review: Use checklist before submit

[Full guidelines with examples follow below...]
```

### 2. Add Optional "Common Pitfalls" Section to Actor

**Rationale**: bash-expert's pitfalls section is highly valuable

**Proposal**: Allow playbook to contribute anti-patterns

**Example**:
```markdown
{{#if common_pitfalls}}
## Common Pitfalls to Avoid in {{language}}

{{#each common_pitfalls}}
- **{{this.pattern}}**: {{this.why_wrong}} (use {{this.correct_pattern}} instead)
{{/each}}

{{/if}}
```

### 3. Separate "Essential Tools" into Dedicated Section

**Current State**: Tools scattered throughout implementation guidelines

**Proposal**: Add dedicated tools section to Actor

**Example**:
```markdown
## Essential Tools for {{language}}

{{#if essential_tools}}
{{#each essential_tools}}
- **{{this.name}}**: {{this.purpose}}
  - Configuration: `{{this.config}}`
  - When to use: {{this.use_case}}
{{/each}}
{{/if}}
```

### 4. Create Lightweight "Domain Expert" Variant Agents

**Proposal**: Add Claude Code-style domain agents to MAP Framework

**Use Case**: When MAP workflow needs deep domain knowledge (e.g., Kubernetes specifics)

**Structure**:
```yaml
---
name: kubernetes-domain-expert
description: Kubernetes deep-dive for MAP workflows (invoked by Actor when needed)
model: sonnet
type: domain_expert  # New type
---

## Focus Areas
[10 bullets on Kubernetes]

## Approach
[10 bullets on K8s best practices]

## Quality Checklist
[10 bullets on K8s validation]

## Output
[10 bullets on K8s deliverables]
```

**Invocation**: Actor can call domain expert via Task tool when hitting knowledge limits

**Benefit**: Combine MAP's learning/workflow with Claude Code's domain depth

### 5. Add "References" Section to Playbook

**Current State**: Playbook stores patterns but not external resources

**Proposal**: Curator can add authoritative references when storing patterns

**Example**:
```json
{
  "bullet_id": "impl-0042",
  "content": "Use Kubernetes StatefulSets for databases...",
  "references": [
    {
      "title": "Kubernetes StatefulSets Documentation",
      "url": "https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/",
      "relevance": "Official guide for StatefulSet configuration"
    }
  ]
}
```

### 6. Introduce "Advanced Techniques" to Playbook

**Current State**: Playbook stores basic patterns

**Proposal**: Flag advanced patterns for expert users

**Example**:
```json
{
  "bullet_id": "impl-0123",
  "content": "Use Kubernetes Operators for complex stateful apps...",
  "difficulty": "advanced",
  "prerequisites": ["impl-0042", "impl-0098"],
  "example_code": "..."
}
```

### 7. Add Description Hints for Proactive Invocation

**Current State**: MAP agents invoked explicitly by orchestrator

**Proposal**: Add "proactive hints" to agent descriptions for autonomous selection

**Example**:
```yaml
---
name: actor
description: Generates production-ready implementation proposals (MAP). Use PROACTIVELY when user requests feature implementation, bug fixes, or code refactoring.
---
```

**Benefit**: Allow Claude Code to auto-select MAP agents when appropriate

### 8. Standardize Output Section Format

**Current State**: MAP agents have varying output structures

**Proposal**: Unify around Claude Code's "Output" pattern (10 concrete deliverables)

**Example** (Actor):
```markdown
## Output Deliverables

1. Complete implementation code with error handling
2. Comprehensive test suite covering edge cases
3. Documentation updates for new functionality
4. Configuration changes with rationale
5. Database migrations (if applicable)
6. API contract updates (if applicable)
7. Security review notes
8. Performance impact analysis
9. Deployment instructions
10. Rollback procedures
```

### 9. Create Comparison Matrix for Agent Selection

**Proposal**: Document when to use Claude Code agents vs MAP agents

**Example**:

| Task Type | Use Claude Code Agents | Use MAP Agents |
|-----------|------------------------|----------------|
| Quick domain question | ✅ Fast, stateless | ❌ Overhead |
| One-off code snippet | ✅ Simple output | ❌ Over-engineered |
| Production feature | ❌ No quality gates | ✅ Multi-phase validation |
| Complex refactoring | ❌ No learning | ✅ Learns patterns |
| Legacy code migration | ❌ No planning | ✅ Decomposition + tracking |

### 10. Hybrid Approach: MAP + Claude Code Agents

**Proposal**: MAP Framework can delegate to Claude Code agents for domain expertise

**Workflow**:
```
User: "Add Kubernetes autoscaling"
  → MAP: /map-feature invoked
  → Task Decomposer: Creates subtasks
  → Actor (subtask 1): "Configure HPA"
    → Actor recognizes K8s domain
    → Actor delegates to kubernetes-expert (Claude Code agent)
    → kubernetes-expert returns K8s-specific guidance
    → Actor integrates into MAP output format
  → Monitor: Validates K8s config
  → [Continue MAP workflow...]
```

**Benefit**: Best of both worlds - MAP's workflow + Claude Code's depth

## Conclusion

### Key Findings Summary

1. **Structural Consistency**: Claude Code subagents follow a rigid 4-section structure (Focus, Approach, Quality, Output) with exactly 10 bullets each, plus optional domain-specific sections.

2. **Metadata Minimalism**: Only 3 YAML fields (name, description, model) vs MAP's 6 fields (adds version, changelog, last_updated).

3. **Stateless Design**: No workflow state, memory, or learning - optimized for fast, autonomous invocation.

4. **Domain Specialization**: 100+ narrow experts vs MAP's 7 broad orchestrators.

5. **Implicit Quality**: "Quality Checklist" is aspirational guidance vs MAP's explicit validation via Monitor agent.

6. **Freeform Output**: Flexible response structure vs MAP's strict JSON schema.

7. **Proactive Hints**: Descriptions include "Use PROACTIVELY for..." to trigger autonomous selection.

8. **No Templating**: Static content vs MAP's dynamic Handlebars templates.

9. **Single-Turn**: Each invocation is complete vs MAP's multi-turn retry loops.

10. **Horizontal Scaling**: Easy to add new domain experts (just create new .md file) vs MAP's vertical scaling (add phases to workflow).

### Architectural Differences

**Claude Code** is optimized for:
- **Speed**: Stateless, lightweight, fast switching
- **Simplicity**: 50-100 lines per agent, no orchestration
- **Autonomy**: Description-based automatic selection
- **Breadth**: 100+ domains covered
- **UX**: Freeform output, human-friendly

**MAP Framework** is optimized for:
- **Quality**: Multi-agent validation, quality gates
- **Learning**: cipher memory, playbook, ACE loop
- **Control**: Explicit orchestration, predictable flow
- **Depth**: 500-2000+ lines per agent, comprehensive guidance
- **Automation**: Structured JSON output, programmatic parsing

### Integration Potential

The two approaches are **complementary, not competing**:

1. **MAP as orchestrator** + **Claude Code agents as domain experts**
2. **MAP for production workflows** + **Claude Code for quick tasks**
3. **MAP learns patterns** → **Store in Claude Code agent format for reuse**

### Next Steps for MAP Framework

Based on this analysis, consider:

1. **Adopt "Rule of 10"** for scannability in long sections
2. **Add domain expert agents** in Claude Code format for deep specialization
3. **Introduce "Common Pitfalls"** sections to Actor (learn from playbook anti-patterns)
4. **Create hybrid workflows** where MAP delegates to Claude Code agents for domain depth
5. **Document agent selection** criteria (when to use MAP vs Claude Code)
6. **Add proactive hints** to MAP agent descriptions for autonomous invocation
7. **Standardize output deliverables** format (10-item "Output" section)
8. **Extract references** from playbook and surface in "Further Reading" sections
9. **Flag advanced patterns** in playbook with difficulty levels and prerequisites
10. **Build comparison matrix** for users to choose the right agent type

## Appendix: Complete Agent Structure Templates

### Claude Code Subagent Template

```markdown
---
name: {domain}-expert
description: {Role statement with capabilities}. {Optional: Use PROACTIVELY for...}
model: claude-sonnet-4-20250514
---

## Focus Areas

- {Competency 1}
- {Competency 2}
- {Competency 3}
- {Competency 4}
- {Competency 5}
- {Competency 6}
- {Competency 7}
- {Competency 8}
- {Competency 9}
- {Competency 10}

## Approach

- {Guideline 1 with imperative verb}
- {Guideline 2 with imperative verb}
- {Guideline 3 with imperative verb}
- {Guideline 4 with imperative verb}
- {Guideline 5 with imperative verb}
- {Guideline 6 with imperative verb}
- {Guideline 7 with imperative verb}
- {Guideline 8 with imperative verb}
- {Guideline 9 with imperative verb}
- {Guideline 10 with imperative verb}

## Quality Checklist

- {Validation criterion 1}
- {Validation criterion 2}
- {Validation criterion 3}
- {Validation criterion 4}
- {Validation criterion 5}
- {Validation criterion 6}
- {Validation criterion 7}
- {Validation criterion 8}
- {Validation criterion 9}
- {Validation criterion 10}

## Output

- {Deliverable 1}
- {Deliverable 2}
- {Deliverable 3}
- {Deliverable 4}
- {Deliverable 5}
- {Deliverable 6}
- {Deliverable 7}
- {Deliverable 8}
- {Deliverable 9}
- {Deliverable 10}

## Essential Tools (Optional)

- **{Tool 1}**: {Purpose and configuration}
- **{Tool 2}**: {Purpose and configuration}
- **{Tool 3}**: {Purpose and configuration}

## Common Pitfalls to Avoid (Optional)

- {Anti-pattern 1} (use {correct pattern} instead)
- {Anti-pattern 2} (use {correct pattern} instead)
- {Anti-pattern 3} (use {correct pattern} instead)

## Advanced Techniques (Optional)

- **{Technique 1}**: {Code example}
- **{Technique 2}**: {Code example}
- **{Technique 3}**: {Code example}

## References & Further Reading (Optional)

- [{Resource 1 Title}]({URL}) - {Description}
- [{Resource 2 Title}]({URL}) - {Description}
- [{Resource 3 Title}]({URL}) - {Description}
```

### MAP Framework Agent Template (Simplified)

```markdown
---
name: {agent-role}
description: {Workflow phase responsibility}
model: sonnet
version: {semantic-version}
last_updated: {ISO-date}
changelog: .claude/agents/CHANGELOG.md
---

# IDENTITY

You are {role description with expertise}.

<mcp_integration>
{MCP tool integration guidelines}
</mcp_integration>

<context>
{Templated project context: {{project_name}}, {{language}}, {{framework}}}
</context>

<task>
{Templated task description: {{subtask_description}}, {{feedback}}}
</task>

<recitation_plan>
{Templated workflow state: {{plan_context}}}
</recitation_plan>

<playbook_context>
{Templated learning: {{playbook_bullets}}}
</playbook_context>

<thinking_process>
{Decision frameworks and heuristics}
</thinking_process>

<implementation_guidelines>
{Coding standards and best practices}
</implementation_guidelines>

<output_format>
{Structured JSON schema requirements}
</output_format>

<constraints>
{Hard boundaries and safety rails}
</constraints>

<examples>
{Complete implementation examples}
</examples>

<critical_reminders>
{Pre-submission checklist}
</critical_reminders>
```

## Analysis Metadata

- **Date**: 2025-11-04
- **Agents Analyzed**: 15 (bash, python, react, typescript, rust, django, docker, kubernetes, jest, terraform, graphql, mongodb, nextjs, redis, postgres)
- **Total Agent Files Available**: 138
- **Analysis Method**: Manual review of structure, content, patterns
- **MAP Agent Comparison**: Actor agent (v2.2.0)
- **Key Findings**: 10 architectural differences, 10 enhancement recommendations
