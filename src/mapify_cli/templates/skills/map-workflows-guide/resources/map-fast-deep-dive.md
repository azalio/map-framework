# /map-fast Deep Dive

## When to Use (and When NOT to Use)

### ✅ Acceptable Use Cases

**ONLY for code you will throw away:**
- Quick feasibility experiments ("Can this library do X?")
- Spike solutions for architecture exploration
- Throwaway scripts for one-time data migration
- Prototypes for stakeholder demos (will be rewritten)

### ❌ NEVER Use For

**Production code:**
- Features that will be maintained
- Critical infrastructure
- Security-sensitive functionality
- Code that others will build on

**Why?** No learning means:
- Patterns not captured → team doesn't learn
- Playbook not updated → knowledge lost
- Cipher not synced → other projects don't benefit
- Technical debt accumulates

---

## What Gets Skipped

### Agents NOT Called

**Predictor (Impact Analysis)**
- No dependency analysis
- Breaking changes undetected
- Side effects not predicted

**Reflector (Pattern Extraction)**
- Successful patterns not captured
- Failures not documented
- Knowledge not extracted

**Curator (Playbook Updates)**
- No playbook bullets created
- No cipher synchronization
- No cross-project learning

### What Remains

**Actor + Monitor + Evaluator:**
- Basic implementation ✅
- Correctness validation ✅
- Quality check ✅

**Result:** Functional code, but zero learning

---

## Token Savings Breakdown

| Agent | Tokens | Status |
|-------|--------|--------|
| TaskDecomposer | ~1.5K | ✅ Runs |
| Actor | ~2-3K | ✅ Runs |
| Monitor | ~1K | ✅ Runs |
| Evaluator | ~0.8K | ✅ Runs |
| Predictor | ~1.5K | ❌ Skipped |
| Reflector | ~2K | ❌ Skipped |
| Curator | ~1.5K | ❌ Skipped |

**Total saved:** ~5K per subtask
**Percentage:** 40-50% vs /map-feature

---

## Example: When map-fast Makes Sense

**Scenario:** "Test if React Query works with our API"

**Why map-fast is acceptable:**
```
Goal: Quick experiment, will be rewritten
Timeline: 1 hour
Outcome: Yes/no answer, not production code
Next step: Use /map-efficient to implement properly
```

**Execution:**
```
TaskDecomposer: 2 subtasks
ST-1: Setup React Query client
  Actor → Monitor → Evaluator → Apply
ST-2: Test with one API endpoint
  Actor → Monitor → Evaluator → Apply
Done. No Reflector, no Curator, no patterns learned.
```

**Appropriate because:**
- Code will be thrown away (experiment only)
- Not building on this implementation
- Rapid answer is the goal

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
4. High risk for throwaway mindset

**Correct choice:** `/map-feature` (critical infrastructure)

---

## Common Pitfalls

### Pitfall 1: "I'll make it quick, then refactor"

**Problem:** Refactoring rarely happens
**Reality:** Technical debt accumulates
**Solution:** Use /map-efficient from the start

### Pitfall 2: "This is just a prototype"

**Problem:** Prototypes become production
**Reality:** "Temporary" code lasts years
**Solution:** Assume code will be maintained

### Pitfall 3: "I don't need learning for simple tasks"

**Problem:** Simple patterns are most valuable
**Reality:** Basic patterns repeated most often
**Solution:** Use /map-efficient (batched learning, minimal overhead)

---

## Decision Flowchart

```
Will this code be rewritten?
│
├─ YES, 100% certain → /map-fast acceptable
│   Examples:
│   - Spike solution for RFC
│   - One-time migration script
│   - Feasibility experiment
│
└─ NO, or uncertain → Use /map-efficient instead
    Why?
    - Same speed (only ~10% slower)
    - Full learning preserved
    - Better safe than sorry
```

---

## Transitioning from Prototype to Production

**If you used /map-fast and need production version:**

1. **Don't refactor in place** - Rewrite from scratch
2. **Use /map-efficient** or /map-feature for rewrite
3. **Document lessons learned** from prototype
4. **Reference prototype** as "what not to do" example

**Why rewrite?**
- Fresh perspective
- Proper validation (Predictor)
- Knowledge captured (Reflector/Curator)
- Clean architecture

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

**3. /map-feature**
- For high-risk experiments
- When prototype might become production
- Security or infrastructure experiments

---

## Best Practices

### When using /map-fast:

1. **Document it's throwaway** - Add comment: "// PROTOTYPE - DO NOT USE IN PRODUCTION"
2. **Set deadline** - "This code expires on [date]"
3. **Plan rewrite** - Schedule /map-efficient rewrite immediately
4. **Review before deleting** - Extract any useful insights manually

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

**Issue:** Prototypes becoming production code
**Solution:** Require /map-efficient rewrite before production deployment

**Issue:** No learning happening on the project
**Solution:** Audit workflow usage, reduce /map-fast usage to <5%

---

**See also:**
- [map-efficient-deep-dive.md](map-efficient-deep-dive.md) - Better alternative for most tasks
- [map-feature-deep-dive.md](map-feature-deep-dive.md) - For critical features
