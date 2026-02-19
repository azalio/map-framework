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

**Full pipeline (theoretical baseline):**
```
Subtask 1 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 2 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
Subtask 3 → Actor → Monitor → Predictor → Evaluator → Reflector → Curator
```
Result: 3 × (Predictor + Evaluator + Reflector + Curator) cycles

**Optimized workflow (/map-efficient):**
```
Subtask 1 → Actor → Monitor → [Predictor if high risk] → Apply
Subtask 2 → Actor → Monitor → [Predictor if high risk] → Apply
Subtask 3 → Actor → Monitor → [Predictor if high risk] → Apply
           ↓
        Final-Verifier (adversarial verification)
           ↓
        Done! Optionally run /map-learn:
           Reflector (analyzes ALL subtasks) → Curator (consolidates patterns)
```
Result: No Evaluator, no per-subtask Reflector/Curator. Learning decoupled to /map-learn.

**Token savings:** 35-40% vs full pipeline

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
- Critical infrastructure (use /map-efficient with --self-moa or /map-debate)
- Small, low-risk changes (use /map-fast)
- Simple bug fixes (use /map-debug)

---

## Quality Preservation

**Myth:** "Optimized workflows sacrifice quality"

**Reality:** /map-efficient preserves essential quality gates:
- ✅ Monitor validates every subtask (correctness gate)
- ✅ Predictor runs when needed (conditional impact analysis)
- ✅ Tests gate and linter gate run per subtask
- ✅ Final-Verifier checks entire goal at end (adversarial verification)
- ✅ Learning available via /map-learn after workflow completes

**What's optimized (intentionally omitted per-subtask):**
- Evaluator — Monitor validates correctness directly
- Reflector/Curator — decoupled to /map-learn (optional, run after workflow)

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
├─ Tests gate: ✅ Passed
└─ Linter gate: ✅ Passed

ST-2: Service update
├─ Actor: Modify services/PostService.ts
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (affects API contract)
│  └─ Impact: Breaking change if clients expect all posts
├─ Tests gate: ✅ Passed
└─ Note: "Add API versioning or deprecation notice"

ST-3: Integration tests
├─ Actor: Add tests/posts.integration.test.ts
├─ Monitor: ✅ Valid (tests pass)
├─ Predictor: ⏭️ SKIPPED (test file)
├─ Tests gate: ✅ Passed
└─ Linter gate: ✅ Passed

Final-Verifier: ✅ All subtasks verified, goal achieved

Optional /map-learn:
  Reflector (batched):
  ├─ Analyzed: 3 subtasks
  └─ Extracted: pagination pattern, API versioning, test structure

  Curator (batched):
  ├─ Checked duplicates: 2 similar bullets found
  ├─ Added: 1 new bullet (API pagination pattern)
  └─ Updated: 1 existing bullet (test coverage++)
```

**Token usage:**
- Full pipeline: ~12k tokens
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
