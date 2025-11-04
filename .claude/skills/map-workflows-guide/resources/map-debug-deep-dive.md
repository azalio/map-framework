# /map-debug Deep Dive

## When to Use

**Bug fixes and error investigation:**
- Fixing failing tests
- Resolving runtime errors
- Investigating unexpected behavior
- Root cause analysis
- Performance debugging

**Why /map-debug?**
- Focused on error analysis
- Root cause identification
- Pattern recognition for similar bugs

---

## Debugging Workflow

### Standard Pipeline

```
1. TaskDecomposer: Break down debugging into steps
   - Reproduce the issue
   - Identify root cause
   - Implement fix
   - Verify resolution
   - Add regression tests

2. For each subtask:
   - Actor implements (with error context)
   - Monitor validates (tests must pass)
   - Predictor analyzes (impact of fix)
   - Evaluator scores (completeness)

3. Reflector extracts lessons:
   - What caused the bug?
   - How was it fixed?
   - How to prevent similar bugs?

4. Curator documents:
   - Debugging techniques used
   - Common pitfalls
   - Prevention strategies
```

---

## Error Analysis Strategies

### 1. Stack Trace Interpretation

**Actor receives:**
```
Error: TypeError: Cannot read property 'name' of undefined
  at UserService.getDisplayName (user.service.ts:42)
  at ProfileController.show (profile.controller.ts:18)
```

**Analysis:**
- Line 42: `user.name` but `user` is undefined
- Line 18: Called without null check
- Root cause: Missing user validation

**Fix:**
```typescript
// Before
getDisplayName(user) {
  return user.name;
}

// After
getDisplayName(user) {
  if (!user) {
    throw new Error("User not found");
  }
  return user.name;
}
```

### 2. Test Failure Diagnosis

**Failed test:**
```
Expected: 200 OK
Received: 404 Not Found
```

**Actor investigates:**
1. Check route configuration
2. Verify request format
3. Debug middleware chain
4. Check database state

**Findings:**
- Route expects `/users/:id` (number)
- Test sends `/users/abc` (string)
- No type validation middleware

**Fix:** Add parameter validation

---

## Example: Debugging Race Condition

**Task:** "Fix intermittent test failures in async code"

**Decomposition:**
```
ST-1: Reproduce the race condition reliably
ST-2: Identify critical section
ST-3: Implement synchronization
ST-4: Verify fix under load
ST-5: Add regression tests
```

**Execution:**

```
ST-1: Reproduce reliably
├─ Actor: Add test that fails consistently
│  └─ Strategy: Increase concurrency, reduce delays
├─ Monitor: ✅ Test fails reliably (good!)
└─ Predictor: Low risk (test code)

ST-2: Identify critical section
├─ Actor: Add logging, trace execution order
│  └─ Finding: Two async operations modify same state
├─ Monitor: ✅ Issue identified
└─ Predictor: Medium risk (affects core logic)

ST-3: Implement synchronization
├─ Actor: Add mutex/lock to critical section
├─ Monitor: ✅ Valid (tests pass)
├─ Predictor: ✅ RAN (affects async behavior)
│  └─ Impact: May reduce throughput
└─ Evaluator: ✅ Approved (score: 8/10)

ST-4: Verify under load
├─ Actor: Run stress test (1000x concurrency)
├─ Monitor: ✅ All tests pass
└─ Evaluator: ✅ Approved

ST-5: Regression tests
├─ Actor: Add concurrent test to test suite
├─ Monitor: ✅ Tests pass
└─ Evaluator: ✅ Approved

Reflector:
├─ Pattern: "Race conditions in async state updates"
├─ Solution: "Use mutex for critical sections"
└─ Prevention: "Design for immutability"

Curator:
├─ ADD "debug-0042: Async race condition patterns"
└─ ADD "impl-0099: Use immutable state updates"
```

---

## Root Cause Analysis

### 5 Whys Technique

**Problem:** "Users can't log in"

```
Why 1: Login fails with 500 error
  → Database query failing

Why 2: Database query failing
  → Connection pool exhausted

Why 3: Connection pool exhausted
  → Connections not being released

Why 4: Connections not being released
  → Missing finally block in async function

Why 5: Missing finally block
  → Copy-pasted code from old example

Root cause: Improper async error handling
```

**Fix:** Add proper resource cleanup

---

## Debugging Patterns Learned

### Common Bug Categories

**1. Null/Undefined Errors**
- Pattern: Missing validation
- Fix: Add null checks, use optional chaining
- Prevention: TypeScript strict mode

**2. Async/Await Issues**
- Pattern: Unhandled promise rejections
- Fix: Add try/catch, .catch() handlers
- Prevention: ESLint rules for promises

**3. State Management Bugs**
- Pattern: Race conditions, stale closures
- Fix: Immutable updates, proper locking
- Prevention: Use state management libraries

**4. Off-by-One Errors**
- Pattern: Array indexing, loop bounds
- Fix: Use array methods (map, filter)
- Prevention: Code review, unit tests

---

## Prevention Strategies

**After debugging, Reflector asks:**
1. How could this bug have been prevented?
2. What test was missing?
3. What pattern should we follow?

**Curator documents:**
```json
{
  "type": "TESTING_STRATEGY",
  "content": "Add integration test for async operations",
  "code_example": "test('handles concurrent requests', async () => { ... })",
  "tags": ["async", "testing", "race-conditions"]
}
```

---

## Troubleshooting the Debugger

**Issue:** Can't reproduce bug consistently
**Solution:**
- Add extensive logging
- Use debugger breakpoints
- Increase test iterations
- Test in production-like environment

**Issue:** Root cause unclear
**Solution:**
- Simplify reproduction case
- Remove variables one by one
- Use git bisect to find regression commit

**Issue:** Fix introduces new bugs
**Solution:**
- Predictor should catch this
- Run full test suite
- Check Predictor impact analysis

---

**See also:**
- [map-efficient-deep-dive.md](map-efficient-deep-dive.md) - For implementing fixes
- [agent-architecture.md](agent-architecture.md) - Predictor's impact analysis
