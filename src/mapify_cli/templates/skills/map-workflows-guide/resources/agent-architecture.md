# Agent Architecture

MAP Framework orchestrates 12 specialized agents in a coordinated workflow.

## Agent Categories

### Execution & Validation (Core Pipeline)

**1. TaskDecomposer**
- **Role:** Breaks complex goals into atomic subtasks
- **Input:** User's high-level request
- **Output:** JSON with subtasks, dependencies, acceptance criteria
- **When it runs:** First step in every workflow

**2. Actor**
- **Role:** Implements code changes
- **Input:** Subtask description, acceptance criteria, playbook context
- **Output:** Code changes, rationale, test strategy
- **When it runs:** For each subtask (multiple times if revisions needed)

**3. Monitor**
- **Role:** Validates correctness and standards compliance
- **Input:** Actor's implementation
- **Output:** Pass/fail verdict with specific issues
- **When it runs:** After every Actor output
- **Feedback loop:** Returns to Actor if validation fails (max 3-5 iterations)

**4. Evaluator**
- **Role:** Quality scoring and final approval
- **Input:** Actor + Monitor results
- **Output:** Quality score (0-10), approve/reject decision
- **When it runs:** /map-debug, /map-review
- **Skipped in:** /map-efficient, /map-fast (Monitor provides sufficient validation)

### Analysis

**5. Predictor**
- **Role:** Impact analysis and dependency tracking
- **Input:** Planned changes
- **Output:** Affected files, breaking changes, risk assessment
- **When it runs:**
  - /map-efficient: Conditional (only if Monitor flags high risk)
  - /map-debug: Always (focused analysis)
  - /map-debate: Conditional (same as /map-efficient)
  - /map-fast: Never (skipped)

### Learning

**6. Reflector**
- **Role:** Extracts patterns and lessons learned
- **Input:** All agent outputs for subtask(s)
- **Output:** Insights, patterns discovered, pattern updates
- **When it runs:**
  - /map-efficient, /map-debug, /map-debate: Batched (once at end, via /map-learn)
  - /map-fast: Never (skipped)
- **MCP Tool:** Uses `mcp__mem0__map_tiered_search` to check for existing patterns

**7. Curator**
- **Role:** Updates memory with validated patterns
- **Input:** Reflector insights
- **Output:** Delta operations (ADD/UPDATE/ARCHIVE patterns)
- **When it runs:** After Reflector
- **MCP Tools:**
  - `mcp__mem0__map_tiered_search` to deduplicate
  - `mcp__mem0__map_add_pattern` to store new patterns

### Optional

**8. Documentation-Reviewer**
- **Role:** Validates documentation completeness
- **Input:** Documentation files
- **Output:** Completeness assessment, dependency analysis
- **When it runs:** On-demand (not part of standard workflows)

### Synthesis

**9. Debate-Arbiter**
- **Role:** Cross-evaluates Actor variants with explicit reasoning
- **Input:** Multiple Actor outputs (variants)
- **Output:** Synthesized optimal solution with reasoning trace
- **When it runs:** /map-debate (per subtask, uses Opus model)

**10. Synthesizer**
- **Role:** Extracts decisions from variants and generates unified code (Self-MoA)
- **Input:** Multiple Actor outputs
- **Output:** Merged implementation combining best elements
- **When it runs:** /map-efficient with --self-moa flag

### Discovery & Verification

**11. Research-Agent**
- **Role:** Heavy codebase reading with compressed output
- **Input:** Research question or exploration goal
- **Output:** Compressed context for implementation agents
- **When it runs:** /map-plan, /map-efficient, /map-debug (before Actor)

**12. Final-Verifier**
- **Role:** Adversarial verification with Root Cause Analysis (Ralph Loop)
- **Input:** Complete implementation after all other agents
- **Output:** Verification verdict, regression analysis
- **When it runs:** /map-check, /map-efficient (terminal verification)

---

## Orchestration Patterns

### Linear Pipeline (map-fast)

```
TaskDecomposer → Actor → Monitor → Apply → Done
(No Evaluator, no Predictor, no learning)
```

### Conditional Pipeline (map-efficient)

```
TaskDecomposer
  ↓
  For each subtask:
    Actor → Monitor → [Predictor if high risk] → Tests → Linter → Apply
  ↓
  Final-Verifier (adversarial verification of entire goal)
  ↓
  Done! Optional: /map-learn → Reflector → Curator
```

### Multi-Variant Pipeline (map-debate)

```
TaskDecomposer
  ↓
  For each subtask:
    Actor×3 → Monitor×3 → debate-arbiter (Opus)
      ↓ synthesized
    Monitor → [Predictor if high risk] → Apply changes
  ↓
  Batch learning (via /map-learn):
    Reflector (all subtasks) → Curator → Done
```

---

## Feedback Loops

### Actor ← Monitor Loop

```
Actor creates code
  ↓
Monitor validates
  ↓
Issues found? → YES → Feedback to Actor (iterate, max 3-5 times)
  ↓ NO
Continue pipeline
```

### Actor ← Evaluator Loop

```
Monitor approved
  ↓
Evaluator scores quality
  ↓
Score < threshold? → YES → Feedback to Actor (revise)
  ↓ NO
Proceed to next stage
```

---

## Conditional Execution Logic

### Predictor Conditions (map-efficient)

Predictor runs if ANY of:
- Subtask modifies critical files (`auth/**`, `database/**`, `api/**`)
- Breaking API changes detected by Monitor
- High complexity score (≥8) from TaskDecomposer
- Multiple file modifications (>3 files)

Otherwise: Skipped (token savings)

---

## State Management

### Per-Subtask State
- Actor output
- Monitor verdict
- Predictor analysis (if ran)
- Evaluator score (if ran)

### Workflow State
- All subtask results
- Aggregated patterns (Reflector)
- Playbook delta operations (Curator)

---

## Communication Protocol

Agents communicate via structured JSON:

```json
{
  "agent": "Actor",
  "subtask_id": "ST-001",
  "output": {
    "approach": "...",
    "code_changes": [...],
    "trade_offs": [...],
    "used_bullets": [...]
  }
}
```

---

## Error Handling

### Actor Failures
- Monitor provides specific feedback
- Actor iterates (max 3-5 attempts)
- If still failing: Mark subtask as failed, continue with others

### MCP Tool Failures
- Reflector/Curator gracefully degrade
- Learning skipped but implementation continues
- Logged to stderr for debugging

---

## Performance Optimization

### Token Usage by Agent

| Agent | Avg Tokens | Frequency | Workflow Impact |
|-------|------------|-----------|-----------------|
| TaskDecomposer | ~1.5K | Once | All workflows |
| Actor | ~2-3K | Per subtask | All workflows |
| Monitor | ~1K | Per Actor output | All workflows |
| Evaluator | ~0.8K | Per subtask | map-debug, map-review |
| Predictor | ~1.5K | Per subtask or conditional | Varies |
| Reflector | ~2K | Per subtask or batched | Varies |
| Curator | ~1.5K | After Reflector | Varies |
| Debate-Arbiter | ~3-4K | Per subtask | map-debate only |
| Synthesizer | ~2K | Per subtask | map-efficient (--self-moa) |
| Research-Agent | ~2-3K | Once (before Actor) | map-plan, map-efficient, map-debug |
| Final-Verifier | ~2K | Once (terminal) | map-check, map-efficient |

**map-efficient savings:**
- Skip Evaluator: ~0.8K per subtask
- Conditional Predictor: ~1.5K per low-risk subtask
- Batch Reflector/Curator: ~(N-1) × 3.5K for N subtasks

---

## Extension Points

### Adding New Agents

To add a custom agent:
1. Create `.claude/agents/my-agent.md` with prompt template
2. Add to workflow command (e.g., `.claude/commands/map-efficient.md`)
3. Define when it runs (before/after which agents)
4. Specify input/output format

### Custom Workflows

Create `.claude/commands/map-custom.md`:
- Define agent sequence
- Specify conditional logic
- Document token cost and use cases

---

**See also:**
- [Playbook System](playbook-system.md) - How knowledge is structured
- [map-efficient Deep Dive](map-efficient-deep-dive.md) - Conditional execution example
