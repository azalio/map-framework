# MAP Agent Architecture

This directory contains agent prompts for the MAP (Modular Agentic Planner) framework.

## ⚠️ CRITICAL: Template Variables

**DO NOT REMOVE Handlebars template syntax!**

Agent files use **Handlebars templating** (`{{variable}}`, `{{#if}}...{{/if}}`) for runtime context injection by the Orchestrator agent.

### Why Template Variables Exist

```
┌─────────────────┐
│   Orchestrator  │  Fills in context at runtime
└────────┬────────┘
         │ {{language}} = "python"
         │ {{project_name}} = "my-api"
         │ {{#if playbook_bullets}} = [patterns from Curator]
         │ {{#if feedback}} = [corrections from Monitor]
         ↓
┌─────────────────┐
│  Actor Agent    │  Receives fully-populated prompt
└─────────────────┘
```

### Template Variables by Category

#### Context Injection (Orchestrator → All Agents)
- `{{language}}` - Project programming language (python, go, javascript, etc.)
- `{{framework}}` - Framework in use (FastAPI, Django, React, etc.)
- `{{project_name}}` - Current project name
- `{{standards_url}}` - Link to coding standards
- `{{branch}}` - Current git branch
- `{{related_files}}` - Files relevant to the task

#### Task Specification (TaskDecomposer → Actor)
- `{{subtask_description}}` - The specific subtask to implement
- `{{allowed_scope}}` - Files/directories Actor is allowed to modify

#### ACE Learning System (Curator → Actor)
- `{{#if playbook_bullets}}...{{/if}}` - Proven patterns from past successes
- This is how the system learns and improves over time
- Curator analyzes successful implementations and adds to playbook
- Actor gets relevant patterns automatically injected

#### Feedback Loops (Monitor → Actor)
- `{{#if feedback}}...{{/if}}` - Corrections from Monitor after failed attempt
- Enables iterative refinement: Actor → Monitor → Actor (with feedback)
- Critical for quality assurance

### What Happens If You Remove Them

| Removed | Impact | Severity |
|---------|--------|----------|
| `{{language}}` | Actor doesn't know what language to use | 🔴 Critical |
| `{{project_name}}` | Generic code, doesn't match project style | 🟡 Major |
| `{{#if playbook_bullets}}` | **Breaks ACE learning system** | 🔴 Critical |
| `{{#if feedback}}` | **Breaks Monitor → Actor retry** | 🔴 Critical |
| `{{subtask_description}}` | Actor doesn't know what to implement | 🔴 Critical |

### How to Safely Customize Agents

✅ **Safe modifications:**
```markdown
# Add new MCP tools
6. **mcp__my-tool__my-function** - Custom functionality
   - Use for specific use cases
   - Example: my_tool(param="value")

# Add domain-specific instructions
# SECURITY REQUIREMENTS
- All inputs must be validated
- Use parameterized queries for SQL
- Never log sensitive data

# Adjust output format
# OUTPUT FORMAT (extended)
5. **Security Analysis**: List potential vulnerabilities
6. **Performance Impact**: Expected performance characteristics
```

❌ **Unsafe modifications:**
```markdown
# ❌ Removing template variables
-{{language}}  # DON'T DO THIS
-{{project_name}}  # DON'T DO THIS

# ❌ Removing conditional blocks
-{{#if playbook_bullets}}  # DON'T DO THIS
-{{/if}}

# ❌ Simplifying "verbose" sections
-# PLAYBOOK CONTEXT (ACE)  # This is critical infrastructure!
```

## Git Pre-commit Hook

A pre-commit hook at `.git/hooks/pre-commit` validates that critical template variables are present before allowing commits.

**Required patterns checked:**
- `{{language}}`
- `{{project_name}}`
- `{{#if playbook_bullets}}`
- `{{#if feedback}}`
- `{{subtask_description}}`

**To bypass (not recommended):**
```bash
git commit --no-verify
```

## Testing Agent Modifications

After modifying an agent, test the **full workflow**, not just the agent in isolation:

```bash
# ❌ Wrong: Test agent standalone
claude --agents '{"actor": {"prompt": "$(cat .claude/agents/actor.md)"}}' --print "implement feature"

# ✅ Right: Test via Orchestrator (full MAP workflow)
/map-feature implement simple calculator with add/subtract
```

The Orchestrator workflow ensures:
1. TaskDecomposer breaks down the task
2. Orchestrator fills in all template variables
3. Actor receives fully-populated prompt with context
4. Monitor validates the output
5. Feedback loops work correctly

## Understanding Handlebars Syntax

If you see these patterns in agent files, **they are NOT comments**:

```handlebars
{{variable}}              → Replaced with actual value
{{#if condition}}...{{/if}} → Conditional block (included if condition true)
{{#each items}}...{{/each}} → Loop over items
```

**Example:**

Before (in agent file):
```markdown
Project: {{project_name}}
Language: {{language}}

{{#if feedback}}
FEEDBACK FROM PREVIOUS ATTEMPT:
{{feedback}}
{{/if}}
```

After (when Orchestrator invokes Actor):
```markdown
Project: my-api
Language: python

FEEDBACK FROM PREVIOUS ATTEMPT:
The function is missing error handling for invalid inputs.
Please add try/except blocks.
```

## Need Help?

- **Question:** "Can I simplify this verbose agent prompt?"
  - **Answer:** Check if it contains `{{templates}}` first. If yes, **DO NOT remove**.

- **Question:** "Why is the playbook section so long?"
  - **Answer:** It's dynamically filled by Curator. It's empty initially, grows with learning.

- **Question:** "Can I remove unused template variables?"
  - **Answer:** No. They're used by Orchestrator even if they look unused in the file.

- **Question:** "The agent works fine without templates in my test."
  - **Answer:** You tested it standalone. Test via `/map-feature` (Orchestrator workflow).

## References

- [MAP Framework Paper](https://github.com/Shanka123/MAP)
- [ACE Framework Paper](https://arxiv.org/abs/2510.04618v1)
- [Handlebars Documentation](https://handlebarsjs.com/)
