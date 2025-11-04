# /map-efficient Deep Dive

## Optimization Strategy

### Predictor: Conditional Execution

**Logic:**
```python
def should_run_predictor(subtask):
    # Run if ANY condition true:
    return (
        subtask.complexity == "high" or
        subtask.modifies_critical_files() or
        subtask.has_breaking_changes() or
        subtask.affects_dependencies()
    )
```

**Critical files patterns:**
- `**/auth/**` - Authentication
- `**/database/**` - Schema changes
- `**/api/**` - Public API
- `**/*.proto` - Service contracts

**Example:**
```
Subtask 1: Add validation helper (utils/validation.ts)
→ Predictor: ⏭️ SKIPPED (low risk, no dependencies)

Subtask 2: Update auth middleware (auth/middleware.ts)
→ Predictor: ✅ RAN (critical file detected)

Subtask 3: Add unit tests (tests/auth.test.ts)
→ Predictor: ⏭️ SKIPPED (test file, no side effects)
```

### Reflector/Curator: Batched Learning

**Standard workflow (/map-feature):**
```
Subtask 1 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 2 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 3 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
```
Result: 3 × Reflector/Curator cycles

**Optimized workflow (/map-efficient):**
```
Subtask 1 → Actor → Monitor → [Predictor?] → Evaluator
Subtask 2 → Actor → Monitor → [Predictor?] → Evaluator
Subtask 3 → Actor → Monitor → [Predictor?] → Evaluator
           ↓
        Reflector (analyzes ALL subtasks)
           ↓
        Curator (consolidates patterns)
```
Result: 1 × Reflector/Curator cycle

**Token savings:** 35-40% vs /map-feature

---

## When to Use /map-efficient

✅ **Use for:**
- Production features (moderate complexity)
- API endpoints
- UI components
- Database queries
- Business logic
- Most development work (80% of tasks)

❌ **Don't use for:**
- Critical infrastructure (use /map-feature)
- Throwaway prototypes (use /map-fast)
- Simple bug fixes (use /map-debug)

---

## Quality Preservation

**Myth:** "Optimized workflows sacrifice quality"

**Reality:** /map-efficient preserves all quality gates:
- ✅ Monitor validates every subtask
- ✅ Evaluator scores every implementation
- ✅ Predictor runs when needed (conditional)
- ✅ Reflector analyzes complete context
- ✅ Curator consolidates all patterns

**What's optimized:**
- Frequency (when agents run)
- NOT functionality (what agents do)

---

## Example Walkthrough

**Task:** "Implement blog post pagination API"

**Decomposition:**
- ST-1: Add pagination params to GET /posts endpoint
- ST-2: Update PostService to support offset/limit
- ST-3: Add integration tests

**Execution trace:**

```
TaskDecomposer:
├─ ST-1: Add pagination params (complexity: low)
├─ ST-2: Update service (complexity: medium, affects API)
└─ ST-3: Add tests (complexity: low)

ST-1: Pagination params
├─ Actor: Modify routes/posts.ts
├─ Monitor: ✅ Valid
├─ Predictor: ⏭️ SKIPPED (low risk)
└─ Evaluator: ✅ Approved (score: 8/10)

ST-2: Service update
├─ Actor: Modify services/PostService.ts
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (affects API contract)
│  └─ Impact: Breaking change if clients expect all posts
├─ Evaluator: ✅ Approved (score: 9/10)
└─ Note: "Add API versioning or deprecation notice"

ST-3: Integration tests
├─ Actor: Add tests/posts.integration.test.ts
├─ Monitor: ✅ Valid (tests pass)
├─ Predictor: ⏭️ SKIPPED (test file)
└─ Evaluator: ✅ Approved (score: 8/10)

Reflector (batched):
├─ Analyzed: 3 subtasks
├─ Searched cipher: Found similar pagination patterns
└─ Extracted:
   - Pagination parameter pattern (offset/limit)
   - API versioning consideration
   - Integration test structure

Curator (batched):
├─ Checked duplicates: 2 similar bullets found
├─ Added: 1 new bullet (API pagination pattern)
└─ Updated: 1 existing bullet (test coverage++)
```

**Token usage:**
- /map-feature: ~12k tokens
- /map-efficient: ~7.5k tokens
- **Savings: 37.5%**

**Quality: Identical**
- All validations passed
- Breaking change detected
- Tests written
- Patterns learned

---

## Configuration

Edit `.claude/commands/map-efficient.md` to customize:

**Predictor conditions:**
```python
# Add custom critical paths
CRITICAL_PATHS = [
    "auth/**",
    "database/**",
    "api/**",
    "config/**",  # Your addition
]
```

**Batch size:**
```python
# Default: Batch all subtasks
# Override: Batch every N subtasks
BATCH_SIZE = None  # or 5 for large tasks
```

---

## Troubleshooting

**Issue:** Predictor always skips
**Cause:** No critical file patterns matched
**Fix:** Review `subtask.modifies_critical_files()` logic

**Issue:** Learning not happening
**Cause:** Reflector/Curator not running
**Fix:** Check workflow completion (must finish all subtasks)

**Issue:** Token usage higher than expected
**Cause:** Predictor running too often
**Fix:** Review risk detection conditions

---

**See also:**
- [map-feature-deep-dive.md](map-feature-deep-dive.md) - Full validation approach
- [agent-architecture.md](agent-architecture.md) - How agents orchestrate
