# /map-fast Deep Dive

## When to Use (and When NOT to Use)

### ✅ Acceptable Use Cases

**ONLY for small, low-risk changes:**
- Localized bug fixes with clear acceptance criteria
- Small UI/text tweaks
- Narrow refactors confined to a single module/file
- Maintenance changes where impact is easy to validate

### ❌ NEVER Use For

**High-risk code paths:**
- Features that will be maintained
- Critical infrastructure
- Security-sensitive functionality
- Code that others will build on

**Why?** No learning means:
- Patterns not captured → team doesn't learn
- Knowledge base not updated → knowledge lost
- Patterns not synced → other projects don't benefit
- Technical debt accumulates

---

## What Gets Skipped

### Agents NOT Called

**Evaluator (Quality Scoring)**
- No quality scoring (0-10 scale)
- No approval/rejection gate
- Monitor handles basic correctness only

**Predictor (Impact Analysis)**
- No dependency analysis
- Breaking changes undetected
- Side effects not predicted

**Reflector (Pattern Extraction)**
- Successful patterns not captured
- Failures not documented
- Knowledge not extracted

- No pattern synchronization
- No cross-project learning

### What Remains

**Actor + Monitor:**
- Basic implementation ✅
- Correctness validation ✅

**Result:** Functional code, but zero learning and no quality scoring

---

## Token Savings Breakdown

| Agent | Tokens | Status |
|-------|--------|--------|
| TaskDecomposer | ~1.5K | ✅ Runs |
| Actor | ~2-3K | ✅ Runs |
| Monitor | ~1K | ✅ Runs |
| Evaluator | ~0.8K | ❌ Skipped |
| Predictor | ~1.5K | ❌ Skipped |
| Reflector | ~2K | ❌ Skipped |
| Curator | ~1.5K | ❌ Skipped |

**Total saved:** ~5.8K per subtask
**Percentage:** 40-50% vs full pipeline

---

## Example: When map-fast Makes Sense

**Scenario:** "Fix a nil/None check in a request handler"

**Why map-fast is acceptable:**
```
Goal: Small, localized fix
Timeline: Short
Outcome: Production-quality fix with tests
Next step: If scope grows, switch to /map-efficient
```

**Execution:**
```
TaskDecomposer: 2 subtasks
ST-1: Setup React Query client
  Actor → Monitor → Apply
ST-2: Test with one API endpoint
  Actor → Monitor → Apply
Done. No Evaluator, no Reflector, no Curator, no patterns learned.
```

**Appropriate because:**
- Low blast radius
- Easy to verify with targeted tests
- Requirements are clear

---

## Example: When map-fast is WRONG

**Scenario:** "Implement user authentication"

**Why map-fast is wrong:**
```
Goal: Production authentication (critical!)
Timeline: Doesn't matter
Outcome: Must be secure, maintainable
Risk: High (security, breaking changes)
```

**Problems with using map-fast:**
1. No Predictor → Breaking changes undetected
2. No Reflector → Security patterns not learned
3. No Curator → Team doesn't learn from mistakes
4. High risk for under-validation mindset

**Correct choice:** `/map-efficient` (critical infrastructure)

---

## Common Pitfalls

### Pitfall 1: "I'll make it quick, then refactor"

**Problem:** Refactoring rarely happens
**Reality:** Technical debt accumulates
**Solution:** Use /map-efficient from the start

### Pitfall 2: "This is just a quick change"

**Problem:** Under-validated changes become long-lived
**Reality:** "Quick" changes often stick around
**Solution:** Default to production-quality standards

### Pitfall 3: "I don't need learning for simple tasks"

**Problem:** Simple patterns are most valuable
**Reality:** Basic patterns repeated most often
**Solution:** Use /map-efficient (batched learning, minimal overhead)

---

## Decision Flowchart

```
Is the change small and low-risk?
│
├─ YES → /map-fast acceptable
│   Examples:
│   - Localized bug fix with existing tests
│   - Small UI tweak
│   - Narrow refactor within a single file
│
└─ NO, or uncertain → Use /map-efficient instead
    Why?
    - Same speed (only ~10% slower)
    - Full learning preserved
    - Better safe than sorry
```

---

## When Scope Grows

If a task starts small but grows in scope or risk, switch to `/map-efficient` for the remainder.

Why?
- Impact analysis (conditional Predictor)
- Learning preserved
- Stronger guardrails for multi-file work

---

## Alternatives to Consider

### Instead of /map-fast, consider:

**1. /map-efficient (recommended)**
- Only ~10-15% slower than /map-fast
- Full learning preserved
- Suitable for production

**2. Manual implementation**
- No agents at all
- Faster for tiny tasks (<50 lines)
- Use when MAP overhead doesn't make sense

**3. /map-efficient or /map-debate**
- For high-risk changes
- Security or infrastructure work

---

## Best Practices

### When using /map-fast:

1. **Document reduced analysis** - Note that /map-fast was used and why
2. **Run tests** - Ensure relevant unit/integration tests pass
3. **Keep changes small** - Avoid scope creep; switch workflows if needed
4. **Review critical paths** - Error handling, input validation, and security

### General guidance:

**Ask yourself:**
- Will anyone build on this code? → Don't use /map-fast
- Is this security-related? → Don't use /map-fast
- Will this integrate with production? → Don't use /map-fast
- Am I uncertain about rewrites? → Don't use /map-fast

**If all answers are "No" → /map-fast is acceptable**

---

## Troubleshooting

**Issue:** Team keeps using /map-fast for production
**Solution:** Code review policy: Reject PRs with /map-fast code

**Issue:** Low-analysis workflow used for risky changes
**Solution:** Team policy: use /map-efficient for anything beyond low-risk/localized

**Issue:** No learning happening on the project
**Solution:** Audit workflow usage, reduce /map-fast usage to <5%

---

**See also:**
- [map-efficient-deep-dive.md](map-efficient-deep-dive.md) - Better alternative for most tasks
- [map-feature-deep-dive.md](map-feature-deep-dive.md) - For critical features
