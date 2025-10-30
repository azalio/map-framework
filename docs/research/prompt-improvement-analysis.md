# Claude Code Prompt Patterns - Analysis for MAP Framework

## Date: 2025-10-17
## Source: sonnet-4.5.md (2752 lines), opus-4.1-thinking.md (1306 lines)

---

## STRUCTURAL PATTERNS EXTRACTED

### 1. Hierarchical XML Tag Structure
**Pattern**: Use semantic XML tags for clear section boundaries and parsing
- `<section_name>`, `<critical_notes>`, `<examples>`, `<code_example>`
- Nested structure with clear parent-child relationships
- Makes LLM parsing unambiguous

**Application to MAP**:
- Wrap major sections: `<MCP_INTEGRATION>`, `<CONSTRAINTS>`, `<OUTPUT_FORMAT>`
- Use `<critical>`, `<example>`, `<rationale>` for subsections

### 2. Critical Instructions Emphasis
**Pattern**: Multiple reinforcement of safety-critical rules
- Use `CRITICAL:`, `IMPORTANT:`, `NEVER`, `ALWAYS` prefixes
- Repeat at: section start, within context, final reminders
- ALL CAPS for frequently-violated rules

**Application to MAP**:
- Repeat constraints in:
  - Initial CONSTRAINTS section
  - Inline with relevant instructions
  - Final CRITICAL_REMINDERS section
- Example: "NEVER modify files outside scope" appears 3+ times

### 3. Decision Framework Pattern
**Pattern**: Explicit IF-THEN-ELSE logic for common decisions
```
IF condition1 → action1
ELSE IF condition2 → action2
ELSE → default_action
```

**Application to MAP**:
- **Actor**: When to use which MCP tool
- **Monitor**: Validation severity levels (accept/feedback/reject)
- **Orchestrator**: Proceed/iterate/escalate logic
- **Predictor**: Impact severity assessment

### 4. Good/Bad Example Pattern
**Pattern**: Show both correct and incorrect approaches
- Format: `Bad: [approach]` / `Good: [approach]`
- Or: `✅ USE` vs `❌ DON'T USE`
- Or: `<good_example>` / `<bad_example>` tags

**Application to MAP**:
- **Actor**: Good/bad code examples
- **Monitor**: Good/bad validation responses
- **Task-Decomposer**: Good/bad subtask breakdowns

### 5. Rationale Blocks
**Pattern**: Explain WHY rules exist, not just WHAT
```xml
<rationale>
Explanation of intent and reasoning behind the rule.
This helps LLMs generalize to novel situations.
</rationale>
```

**Application to MAP**:
- Add rationale for non-obvious constraints
- Explain why certain MCP tools are preferred
- Justify workflow patterns (e.g., why max 3-5 iterations)

### 6. Comprehensive Constraint Lists
**Pattern**: Explicit "Do NOT" sections
- List common mistakes/pitfalls
- Negative constraints as important as positive
- Grouped by category (safety, performance, correctness)

**Application to MAP**:
- Add "NEVER" section to all agents
- Group: file scope, dependencies, error handling, deprecated APIs

### 7. Tool Selection Logic
**Pattern**: Explicit trigger patterns for when to use each tool
```xml
<tool_selection>
**tool_name**: Use when...
- Trigger pattern 1
- Trigger pattern 2
- Priority: Use this BEFORE tool_x
</tool_selection>
```

**Application to MAP**:
- Add to Actor's MCP section
- Priority ordering: cipher_search → codex → context7 → deepwiki

---

## TOOL USAGE & CONSTRAINT PATTERNS

### 8. Parameter Validation
**Pattern**: Require description/rationale for all tool calls
- Example: `bash_tool` requires both `command` and `description`
- Forces explicit thinking before action
- Helps with debugging and audit trails

**Application to MAP**:
- Require actors to explain MCP tool queries
- Monitor should explain validation reasoning
- Evaluator should justify scores

### 9. Safety Boundaries
**Pattern**: Multiple layers of safety enforcement
- File access restrictions (allowed paths)
- Operation constraints (no destructive ops without confirmation)
- Output constraints (no copyrighted content)

**Application to MAP**:
- Actor: File scope boundaries, no breaking changes
- Monitor: Must check security implications
- Orchestrator: Iteration limits, escalation triggers

### 10. Error Handling Requirements
**Pattern**: Explicit error handling in examples
```javascript
try {
  // operation
} catch (error) {
  // handle gracefully
}
```

**Application to MAP**:
- Actor code examples must include error handling
- Monitor validates error handling exists
  

---

## OUTPUT FORMATTING PATTERNS

### 11. Structured Output Templates
**Pattern**: Provide exact JSON schema with examples
```json
{
  "field1": "description",
  "field2": 123,
  "nested": { "key": "value" }
}
```
- Use type hints: `"string"`, `number`, `boolean`
- Show complete structure, not partial

**Application to MAP**:
- Task-Decomposer: Already has good JSON schema
- Monitor: Add explicit JSON structure for issues
- Reflector/Curator: Improve JSON templates

### 12. Example-Driven Formatting
**Pattern**: Show complete examples of good outputs
- Not just schema, but realistic filled-in examples
- Multiple examples showing variations

**Application to MAP**:
- Each agent needs 2-3 complete output examples
- Show: simple case, complex case, edge case

---

## EXAMPLE PATTERNS

### 13. Multi-Level Examples
**Pattern**: Examples at different complexity levels
- Simple: Basic happy path
- Medium: With common variations
- Complex: Edge cases and error handling

**Application to MAP**:
- Actor: Simple function, complex service, edge case handling
- Task-Decomposer: 2-subtask, 8-subtask decompositions

### 14. Annotated Examples
**Pattern**: Include explanatory comments in examples
```python
# GOOD: Explicit error handling
try:
    result = risky_operation()
except ValueError as e:
    # Fail safely with clear error message
    return {"error": str(e)}

# BAD: Silent failure
result = risky_operation() or None
```

**Application to MAP**:
- Add inline annotations to all code examples
- Explain WHY the example is good/bad

---

## WORKFLOW PATTERNS

### 15. Iterative Refinement
**Pattern**: Explicit loop structure with exit conditions
```
REPEAT up to N times:
  attempt = ACTION()
  review = VALIDATE(attempt)
  if review.passed: BREAK
  if iteration >= N: ESCALATE
```

**Application to MAP**:
- Already present in orchestrator
- Make exit conditions more explicit
- Add metrics for iteration tracking

### 16. Context Management
**Pattern**: Explicit state tracking
- What information must be preserved across steps?
- What context must be passed to sub-agents?

**Application to MAP**:
- Orchestrator tracks: current subtask, iteration count, feedback history
- Agents return: used_bullets, decisions_made, next_steps

---

## PRIORITY IMPROVEMENTS FOR MAP AGENTS

### High Priority (Apply to all agents):
1. ✅ Add XML tag structure for major sections
2. ✅ Add CRITICAL/NEVER emphasis to constraints
3. ✅ Add decision frameworks where agents make choices
4. ✅ Add good/bad examples
5. ✅ Add rationale blocks for non-obvious rules

### Medium Priority (Apply to key agents):
6. Tool selection logic (Actor, Orchestrator)
7. Comprehensive constraint lists (Actor, Monitor)
8. Structured output templates (Monitor, Evaluator, Reflector)
9. Multiple example levels (Actor, Task-Decomposer)

### Low Priority (Nice to have):
10. Parameter validation requirements
11. Annotated examples with inline comments
12. Context management documentation

---

## NEXT STEPS

1. ✅ Create this analysis document
2. Apply improvements to core agents:
   - actor.md
   - monitor.md
   - predictor.md
3. Apply improvements to quality agents:
   - evaluator.md
   - test-generator.md
   - documentation-reviewer.md
4. Apply improvements to learning agents:
   - reflector.md
   - curator.md
5. Apply improvements to orchestration agents:
   - orchestrator.md
   - task-decomposer.md
6. Test improved prompts
7. Document patterns in playbook

---

## PATTERNS TO AVOID

Based on Claude Code analysis, these patterns should NOT be adopted:

1. **Overly long prompts**: Claude Code prompts are 2752+ lines. MAP agents should stay focused (200-400 lines max per agent)
2. **Context-specific instructions**: Claude Code has user preferences, timezone handling - MAP agents don't need this
3. **Multi-modal handling**: Claude Code handles images, PDFs - MAP agents work with code only
4. **Copyright restrictions**: Claude Code has extensive copyright rules - not applicable to MAP framework
5. **Web search logic**: Complex search decision trees - MAP uses MCP tools instead

Keep MAP agents:
- Focused on their specific role
- Streamlined for code development workflows
- Compatible with MAP/ACE architecture
- Using MCP tools, not raw web access
