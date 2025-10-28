# Sequential Thinking Integration Guide

## Overview

Sequential thinking is an MCP (Model Context Protocol) tool that enables systematic, reflective problem-solving through structured reasoning chains. MAP Framework agents use this tool to break down complex problems, discover hidden dependencies, trace multi-layer impacts, and evaluate competing trade-offs through iterative hypothesis-verification cycles.

**Key Benefits**:
- **Progressive refinement**: Start with initial hypothesis, discover new evidence, revise conclusions
- **Explicit reasoning**: Every step documented with justification, creating audit trail
- **Dynamic adaptation**: Adjust thought count as complexity emerges, branch to explore alternatives
- **Evidence-based**: Cite specific line numbers, code patterns, metrics in each thought

**Core Use Cases**:
- **Monitor**: Validating complex logic, analyzing race conditions, enumerating edge cases
- **Predictor**: Tracing transitive dependencies, mapping impact cascades, discovering non-obvious affected systems
- **Evaluator**: Balancing competing quality dimensions, assessing trade-offs, validating research completeness

## When to Use Sequential-Thinking

Sequential-thinking adds value when problems require multi-step reasoning that benefits from hypothesis formation, progressive discovery, and conclusion revision. Use decision criteria tailored to each agent's role.

### Monitor Agent

**Triggers for Sequential-Thinking**:

1. **Complex Logic Validation** (≥3 nested conditionals)
   - State machines with multiple transitions
   - Multi-step workflows with branching paths
   - Nested error handling with recovery logic
   - **Decision threshold**: IF nested depth ≥3 OR state count ≥5 → invoke sequential-thinking

2. **Race Condition Analysis** (concurrent/async code)
   - Shared resource access without locks
   - Read-modify-write sequences
   - Timing-dependent logic ("X always happens before Y")
   - **Decision threshold**: IF async/threading used OR shared state modified → invoke sequential-thinking

3. **Edge Case Enumeration** (≥3 input parameters OR critical workflows)
   - Financial transactions (precision, rollback, idempotency)
   - Security-sensitive operations (auth, data access, encryption)
   - Data transformations with multiple optional fields
   - **Decision threshold**: IF parameter count ≥3 OR domain critical (financial/security) → invoke sequential-thinking

### Predictor Agent

**Triggers for Sequential-Thinking**:

1. **Transitive Dependency Analysis** (model/type changes)
   - Type migrations (string → enum, int → UUID, dict → TypedDict)
   - Shared models with >5 consumers (User, Product, Order)
   - Core domain objects crossing architectural boundaries
   - **Decision threshold**: IF type/semantics change OR import count >5 → invoke sequential-thinking

2. **Impact Cascade Tracing** (API contract breaking changes)
   - Response structure changes (flat → nested, single → array)
   - External consumers (mobile apps, third-party integrations)
   - Deployment coordination requirements
   - **Decision threshold**: IF API contract change OR external consumers exist → invoke sequential-thinking

**Value Proposition**: Simple grep finds syntactic references ("where code appears"). Sequential-thinking discovers semantic dependencies ("how code uses data"), revealing transitive impacts that span architectural layers.

### Evaluator Agent

**Triggers for Sequential-Thinking**:

1. **Competing Performance vs Security Trade-offs**
   - Caching sensitive data (speed vs PII exposure)
   - Input validation depth (security vs latency)
   - Authentication mechanisms (security vs response time)
   - **Decision threshold**: IF optimization impacts security OR security measure impacts performance → invoke sequential-thinking

2. **Testability vs Simplicity Trade-offs**
   - Hardcoded dependencies (simplicity vs mocking)
   - Dependency injection frameworks (testability vs boilerplate)
   - Tight coupling (direct calls vs isolation)
   - **Decision threshold**: IF testability score ≤6 OR code_quality ≤6 due to design tension → invoke sequential-thinking

3. **Completeness Assessment with Research Requirements**
   - Post-cutoff library features (Next.js 14+, React 18+)
   - Complex algorithms (rate limiting, distributed consensus)
   - Security-critical implementations (auth, encryption)
   - **Decision threshold**: IF unfamiliar tech OR post-cutoff features OR security-critical → check research completeness via sequential-thinking

## How to Use Sequential-Thinking

### Invocation Pattern

```python
# Example: Monitor validating complex conditional logic
mcp__sequential_thinking__sequentialthinking({
    "thought": "Thought 1: Identify entry points and initial conditions. Code has 3 entry paths: authenticated user, guest user, admin override.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 1,
    "totalThoughts": 7,  # Initial estimate
    "isRevision": False
})

# Subsequent thoughts trace execution paths...

mcp__sequential_thinking__sequentialthinking({
    "thought": "Thought 4: DISCOVERY - Found unreachable else clause at line 45. Auth check on line 38 always returns before this point.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 4,
    "totalThoughts": 8,  # Adjusted estimate (found issue, need more analysis)
    "isRevision": False
})

# Revision of earlier conclusion
mcp__sequential_thinking__sequentialthinking({
    "thought": "Thought 6: REVISION of Thought 2 - Initial hypothesis was 'all paths covered'. Actually missing timeout handling for external API call (line 52). This is HIGH severity.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 6,
    "totalThoughts": 9,
    "isRevision": True,
    "revisesThought": 2
})

# Final consolidated analysis
mcp__sequential_thinking__sequentialthinking({
    "thought": "Thought 9: CONCLUSION - Found 3 critical issues: unreachable code (line 45), missing timeout (line 52), race condition (line 67). Recommend valid=false with HIGH severity feedback.",
    "nextThoughtNeeded": False,
    "thoughtNumber": 9,
    "totalThoughts": 9
})
```

### Thought Structure Best Practices

**Effective Thought Patterns**:

1. **Hypothesis Formation → Discovery → Revision**
   - Start with initial estimate/hypothesis
   - Search for evidence systematically
   - Revise when new information contradicts hypothesis
   - Example: "Initial hypothesis: 2 files affected" → "Discovery: 18+ files affected after tracing serializers and tests" → "Revised impact: HIGH instead of LOW"

2. **Progressive Refinement**
   - Begin with coarse-grained analysis
   - Zoom into specific areas when issues detected
   - Adjust `totalThoughts` dynamically using `needsMoreThoughts`
   - Example: Start with 5 thoughts for high-level review → Detect complex concurrency issue → Increase to 8 thoughts to analyze race conditions thoroughly

3. **Evidence-Based Reasoning**
   - Cite specific line numbers, file paths, code snippets
   - Reference concrete metrics (response time, test coverage %)
   - Quote exact error messages or API signatures
   - Example: "Line 67 uses `cache.get() → modify → cache.set()` pattern without lock. This creates read-modify-write race condition."

4. **Explicit Uncertainty**
   - Mark low-confidence conclusions
   - Identify gaps in available information
   - Suggest additional validation steps
   - Example: "Confidence: 0.75 (medium-high). May miss dynamic imports using string variables. Recommend manual Grep for 'importlib.*module_name'."

**Anti-Patterns to Avoid**:

- ❌ **Linear thinking**: "Thought 1 → Thought 2 → Thought 3 → Done" without considering alternatives
- ❌ **Vague thoughts**: "This looks problematic" (no specifics, no evidence)
- ❌ **Ignoring discoveries**: Find critical issue in Thought 3 but don't adjust total thoughts
- ❌ **Premature conclusion**: Set `nextThoughtNeeded=false` before exploring all dimensions
- ❌ **Over-thinking trivial**: Using 15 thoughts for simple validation (wastes tokens)

## Agent-Specific Patterns

### Monitor: Validation Patterns

#### Pattern 1: Complex Conditional Logic Trace

**Scenario**: Validating authentication flow with multiple conditional branches (authenticated, guest, admin override, API key).

**Thought Structure**:
```
Thought 1: Identify entry points (4 paths: user auth, guest, admin, API key)
Thought 2: Trace authenticated user path - validates JWT, checks expiration, SUCCESS
Thought 3: Trace guest path - creates anonymous session, MISSING rate limiting
Thought 4: Trace admin override - checks admin role, SUCCESS BUT skips audit logging
Thought 5: Trace API key path - validates key, checks scope, SUCCESS
Thought 6: Cross-check error handling - JWT expired returns 401, API key invalid returns 403, CONSISTENT
Thought 7: DISCOVERY - Admin override path (line 78) doesn't log access for compliance (HIGH severity issue)
Thought 8: CONCLUSION - 2 issues found: missing rate limit (guest), missing audit log (admin). Recommend valid=false.
```

**Key Principles**:
- Systematically trace EVERY execution path (don't assume symmetry)
- Check error handling for EACH path independently
- Look for security/compliance gaps (audit logging, rate limiting)
- Cite exact line numbers for issues found

#### Pattern 2: Race Condition Discovery

**Scenario**: Validating cache update logic using Redis in async environment.

**Thought Structure**:
```
Thought 1: Initial hypothesis - single cache.set() call, seems safe
Thought 2: Identify shared resource (Redis cache key 'user:profile:{id}')
Thought 3: Map write operations - cache.get() → modify data → cache.set() (3-step pattern)
Thought 4: DISCOVERY - Read-modify-write without atomic operation! Scenario: Thread A reads, Thread B reads, A writes, B writes → B overwrites A's changes (lost update)
Thought 5: Check if Redis atomic operations used - NO, using separate get/set calls
Thought 6: Evaluate impact - profile updates during concurrent requests will lose data (HIGH severity)
Thought 7: CONCLUSION - Race condition at line 67. Recommend using Redis WATCH/MULTI for atomic read-modify-write OR use Lua script.
```

**Key Principles**:
- Identify ALL shared resources (database, cache, files, global state)
- Map read-modify-write sequences explicitly
- Simulate concurrent execution scenarios (interleaving)
- Validate atomic operations or locks are used

### Predictor: Impact Analysis Patterns

#### Pattern 1: Transitive Dependency Tracing (Type Change)

**Scenario**: Developer changed `User.status` from `string` to `StatusEnum`. Initial hypothesis: 2 files affected.

**Thought Structure**:
```
Thought 1: Initial hypothesis - 2 direct import sites affected (user_service.py, admin.py)
Thought 2: Search for direct references - Grep finds 6 service files importing User model
Thought 3: DISCOVERY - Services don't just import, they COMPARE status with strings (e.g., if user.status == "active")
Thought 4: Trace service layer - 6 files need enum comparison updates (user.status == StatusEnum.ACTIVE)
Thought 5: Check serialization boundaries - API serializer needs backward-compatible config (return "active" string for clients)
Thought 6: Analyze test layer - 23 test files use hardcoded status strings in fixtures
Thought 7: Database migration - Need migration with data quality validation (existing "active" → StatusEnum.ACTIVE)
Thought 8: REVISED IMPACT - 18+ files affected (6x initial estimate): 6 services + 1 serializer + 23 tests + 1 migration. Classification: HIGH IMPACT, not LOW.
```

**Key Principles**:
- Start with hypothesis, validate with systematic search
- Trace HOW code uses data (not just where it imports)
- Check ALL architectural layers (service → API → tests → database)
- Quantify impact (2 files vs 18+ files changes severity classification)

#### Pattern 2: API Contract Breaking Change Cascade

**Scenario**: Developer changed `GET /api/users/{id}` response from flat object to paginated structure `{data: User, pagination: {...}}`.

**Thought Structure**:
```
Thought 1: Initial hypothesis - frontend needs update (1 consumer)
Thought 2: Discover client systems - React app, iOS app, Android app (3 deployed applications)
Thought 3: CRITICAL DISCOVERY - No API versioning! All clients break immediately on deployment.
Thought 4: Check internal consumers - 5 internal scripts, monitoring dashboard parse response
Thought 5: Analyze test migration - 35 test files assert response structure, need updates
Thought 6: Documentation sprawl - OpenAPI spec, Postman collection, 3 blog posts with examples
Thought 7: CRITICAL - Mobile apps have 1-2 week release cycle, can't update immediately
Thought 8: REVISED APPROACH - Actor MUST create /api/v2/ endpoint, not modify v1. Requires multi-week coordinated rollout. Impact: CRITICAL (not HIGH).
```

**Key Principles**:
- Identify ALL consumers (internal + external + documentation)
- Check deployment constraints (mobile release cycles)
- Versioning presence determines breaking change severity
- Non-obvious affected systems (CI/CD, monitoring, docs)

### Evaluator: Quality Assessment Patterns

#### Pattern 1: Performance vs Security Trade-off

**Scenario**: Actor implements Redis caching for user profile API. Cache stores plaintext PII (email, phone) for 5 minutes.

**Thought Structure**:
```
Thought 1: Initial hypothesis - Performance 9/10 (fast cache), Security 8/10 (Redis secured)
Thought 2: Evaluate security - Cache stores PII unencrypted. If Redis compromised (memory dump, unauthorized access), PII exposed. Security REVISED to 6/10.
Thought 3: Quantify performance gain - Response time 20ms (cached) vs 200ms (database). 10x improvement.
Thought 4: Assess alternatives - (A) Encrypt cache values: adds 5ms overhead, 95% of performance gain retained. (B) Exclude sensitive fields: cache only non-PII, partial gain.
Thought 5: Evaluate testability - Tests don't mock cache failures. Missing error handling test. Testability: 7/10.
Thought 6: Check completeness - No cache invalidation on user profile update! Stale data served for 5 minutes. Completeness: 7/10.
Thought 7: Calculate weighted scores - Performance 9/10, Security 6/10 (PII exposure), Testability 7/10, Completeness 7/10.
Thought 8: RECOMMENDATION - "improve" verdict. Encrypt cached PII (minor performance cost for major security gain) + add cache invalidation on updates.
```

**Key Principles**:
- Identify tension between dimensions explicitly
- Quantify trade-offs (10x performance gain vs PII exposure risk)
- Evaluate alternatives systematically (encrypted cache, selective caching)
- Multi-dimensional scoring (performance, security, testability, completeness)

#### Pattern 2: Testability vs Simplicity Trade-off

**Scenario**: Actor implements email notification service that directly instantiates `SMTPClient()` inside `send_notification()` method.

**Thought Structure**:
```
Thought 1: Initial hypothesis - Code_quality 8/10 (simple, clear), Testability 9/10 (can test, right?)
Thought 2: DISCOVERY - Cannot mock SMTPClient because it's hardcoded inside method. Tests require real SMTP server. Testability REVISED to 4/10.
Thought 3: Evaluate code quality - Simple BUT creates tight coupling. Switching email providers (SendGrid → AWS SES) requires changing method internals. Code_quality REVISED to 6/10 (maintainability suffers).
Thought 5: Analyze test completeness - Existing tests use real SMTP → flaky (network dependency), slow (3s per test), incomplete (no error case tests because mocking impossible). Testability further REVISED to 3/10, Completeness 5/10.
Thought 6: Assess alternative - Inject email client as parameter: `send_notification(client, ...)`. Adds 1 line of complexity, enables full testability + flexibility.
Thought 7: COST-BENEFIT - Slight increase in code complexity (6→7 code_quality) for major gains in testability (3→9) and completeness (5→9).
Thought 8: RECOMMENDATION - "improve" verdict. Inject SMTPClient dependency to enable mocking + add comprehensive error case tests.
```

**Key Principles**:
- Challenge initial assumptions (testability 9 → 3 after analysis)
- Evaluate cascading impacts (tight coupling → hard to test → incomplete tests)
- Quantify trade-offs (1 line of complexity for 6-point testability gain)
- Assess alternatives with cost-benefit analysis

## Best Practices

### 1. Start with Hypothesis

**Why**: Aimless exploration wastes tokens. Hypothesis gives direction.

**Good Example**:
```
Thought 1: Initial hypothesis - DB query performance issue. Expected: N+1 queries. Will trace query patterns in loop.
```

**Bad Example**:
```
Thought 1: Let me look at the code... there's a loop... and database calls... hmm...
```

### 2. Cite Evidence

**Why**: Vague analysis is unusable. Specifics enable action.

**Good Example**:
```
Thought 3: Line 67 uses `cache.get(key) → modify → cache.set(key, value)` without lock. This read-modify-write race causes lost updates under concurrent access.
```

**Bad Example**:
```
Thought 3: The cache code might have some concurrency issues.
```

### 3. Adjust Thought Count Dynamically

**Why**: Complex problems reveal themselves. Don't artificially constrain analysis.

**Pattern**:
```python
# Initial estimate
{"thoughtNumber": 1, "totalThoughts": 5}

# Discovery of complexity
{"thoughtNumber": 3, "totalThoughts": 8, "needsMoreThoughts": True}
# Rationale: Found race condition, need deeper analysis

# Final thought
{"thoughtNumber": 8, "totalThoughts": 8, "nextThoughtNeeded": False}
```

### 4. Mark Revisions Explicitly

**Why**: Shows reasoning evolution, explains why conclusions changed.

**Pattern**:
```python
{"thought": "Thought 2: All execution paths covered.", ...}

# Later discovery
{
    "thought": "Thought 5: REVISION of Thought 2 - Missed timeout path. Not all paths covered.",
    "isRevision": True,
    "revisesThought": 2
}
```

### 5. Use Branches for Alternatives

**Why**: Compare approaches systematically without losing main thread.

**Pattern**:
```python
# Main thread
{"thought": "Thought 3: Option A - Encrypt cache", "thoughtNumber": 3}

# Branch to explore alternative
{
    "thought": "Branch 1, Thought 1: Option B - Exclude sensitive fields. Pros: simpler, faster. Cons: partial caching benefit.",
    "branchId": "option_b",
    "branchFromThought": 3
}

# Return to main thread with comparison
{"thought": "Thought 4: Comparison - Option A provides full caching + security. Option B trades security for simplicity. Recommend A."}
```

## Anti-Patterns

### 1. Skipping Sequential-Thinking for "Simple" Tasks

**Problem**: Tasks that appear simple reveal complexity during implementation.

**Example**: "Just rename this function" → Discovers 18 affected files, config files, documentation, CI/CD scripts.

**Solution**: Use decision thresholds. For Monitor: ≥3 conditionals. For Predictor: ≥5 import sites. For Evaluator: competing dimensions.

### 2. Linear Thinking Without Revision

**Problem**: Initial assumptions go unchallenged.

**Example**:
```
Thought 1: 2 files affected (hypothesis)
Thought 2: Updated file A
Thought 3: Updated file B
Thought 4: Done (ignored evidence of more affected files)
```

**Solution**: Actively search for contradicting evidence. Use `isRevision` when hypothesis fails.

### 3. Vague Thoughts Without Specifics

**Problem**: Analysis is too abstract to be actionable.

**Example**: "Thought 3: The security might be problematic in some scenarios."

**Solution**: Cite line numbers, specific vulnerabilities, concrete scenarios. "Thought 3: Line 45 uses SQL concatenation (f'SELECT * FROM users WHERE id={user_id}'), enabling SQL injection. Attacker can inject `1 OR 1=1`."

### 4. Over-Thinking Trivial Decisions

**Problem**: Using 15 thoughts to validate simple assignment statement.

**Example**: 15-thought sequence analyzing `x = 5` (overkill).

**Solution**: Use thresholds. Monitor: only for ≥3 conditionals. Predictor: only for type changes or >5 import sites. Evaluator: only for competing dimensions (security vs performance).

## Examples

### Full Example 1: Monitor Validating Complex Logic

**Scenario**: Validate authentication flow with 4 entry paths (authenticated user, guest, admin override, API key) and nested error handling.

**Sequential-Thinking Execution**:

```python
# Thought 1
{
    "thought": "Thought 1: Identify all entry points. Code has 4 authentication paths: (1) JWT auth (line 20), (2) Guest/anonymous (line 45), (3) Admin override (line 78), (4) API key (line 102). Will trace each path systematically.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 1,
    "totalThoughts": 7
}

# Thought 2
{
    "thought": "Thought 2: Trace JWT authentication path (lines 20-40). Flow: extract token → validate signature → check expiration → load user. Error handling: missing token returns 401, invalid signature returns 401, expired returns 401. Logic correct.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 2,
    "totalThoughts": 7
}

# Thought 3
{
    "thought": "Thought 3: Trace guest path (lines 45-60). Flow: create anonymous session → assign temp ID → set guest=true flag. ISSUE FOUND: No rate limiting for guest sessions. Vulnerability: unlimited anonymous sessions can exhaust resources. Severity: MEDIUM (DoS risk).",
    "nextThoughtNeeded": True,
    "thoughtNumber": 3,
    "totalThoughts": 8  # Increased estimate
}

# Thought 4
{
    "thought": "Thought 4: Trace admin override path (lines 78-95). Flow: check admin role → bypass normal auth → load user. Logic works BUT CRITICAL DISCOVERY: No audit logging for admin overrides (compliance requirement). Line 92 proceeds directly to user context without logging event. Severity: HIGH.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 4,
    "totalThoughts": 9  # Increased again
}

# Thought 5
{
    "thought": "Thought 5: Trace API key path (lines 102-120). Flow: extract key from header → validate against database → check scope permissions. Error handling: missing key returns 401, invalid key returns 403, insufficient scope returns 403. Logic correct.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 5,
    "totalThoughts": 9
}

# Thought 6
{
    "thought": "Thought 6: Cross-check error handling consistency. JWT expired → 401, API key invalid → 403, admin check fail → 403. Consistent use of HTTP status codes. Error messages don't leak implementation details (no SQL errors exposed). Good security posture.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 6,
    "totalThoughts": 9
}

# Thought 7
{
    "thought": "Thought 7: Check for unreachable code. All paths properly structured with clear exit points. No dead code detected.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 7,
    "totalThoughts": 9
}

# Thought 8
{
    "thought": "Thought 8: Review edge cases. Concurrent login attempts: handled by session locking. Multiple API keys for same user: correctly scoped. Token rotation: implemented (line 130). Edge cases covered.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 8,
    "totalThoughts": 9
}

# Thought 9 - Conclusion
{
    "thought": "Thought 9: CONCLUSION - Found 2 issues: (1) Missing rate limiting for guest sessions (line 45, MEDIUM severity, DoS risk), (2) Missing audit logging for admin overrides (line 78, HIGH severity, compliance violation). Recommend valid=false. Actor must add rate limiter to guest path + audit log to admin path before approval.",
    "nextThoughtNeeded": False,
    "thoughtNumber": 9,
    "totalThoughts": 9
}
```

**Outcome**: Monitor marks `valid=false` with 2 specific issues (line numbers, severity, explanation). Actor fixes in next iteration.

**Key Techniques Demonstrated**:
- Systematic path-by-path tracing (no path assumed safe)
- Dynamic thought count adjustment (7→8→9 as issues discovered)
- Specific evidence (line numbers, exact vulnerability descriptions)
- Severity classification with justification (MEDIUM DoS risk, HIGH compliance violation)

---

### Full Example 2: Predictor Tracing Breaking Change

**Scenario**: Developer proposes changing `GET /api/users/{id}` response structure from flat User object to paginated structure `{data: User, pagination: {total, page}}`.

**Sequential-Thinking Execution**:

```python
# Thought 1
{
    "thought": "Thought 1: Initial hypothesis - This API contract change affects frontend (React app). Estimate: 1-2 components need updates. Will search for API consumers systematically.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 1,
    "totalThoughts": 6
}

# Thought 2
{
    "thought": "Thought 2: DISCOVERY - Found 3 deployed client applications, not just frontend: (1) React web app, (2) iOS app, (3) Android app. All parse response and expect flat object. Breaking change impacts 3 platforms.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 2,
    "totalThoughts": 8  # More complex than initial estimate
}

# Thought 3
{
    "thought": "Thought 3: CRITICAL DISCOVERY - Grep for versioning in API routes: NO /api/v1/ or /api/v2/ endpoints found. API has NO versioning strategy. Breaking change will break ALL deployed applications IMMEDIATELY on deployment. This is CRITICAL severity.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 3,
    "totalThoughts": 10  # Major architectural issue discovered
}

# Thought 4
{
    "thought": "Thought 4: Check internal API consumers. Found: (1) Admin dashboard (JavaScript fetch), (2) Monitoring dashboard (parses JSON), (3) 5 internal scripts (Python requests). Total: 8+ API consumers identified.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 4,
    "totalThoughts": 10
}

# Thought 5
{
    "thought": "Thought 5: Analyze test migration complexity. Grep for response assertions: 35 test files assert response structure. Example: `assert response['email']` now fails (expects `response['data']['email']`). Large-scale test updates required.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 5,
    "totalThoughts": 10
}

# Thought 6
{
    "thought": "Thought 6: Documentation sprawl check. Found: (1) OpenAPI spec (schema definition), (2) Postman collection (example requests), (3) 3 blog posts with code examples, (4) Developer onboarding guide. All show old response structure. Extensive docs updates required.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 6,
    "totalThoughts": 10
}

# Thought 7
{
    "thought": "Thought 7: Check non-obvious affected systems. Found: (1) CI/CD smoke tests parse response, (2) Monitoring dashboard alerts check response fields, (3) Log analysis scripts parse JSON structure. These will break silently if not updated.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 7,
    "totalThoughts": 10
}

# Thought 8
{
    "thought": "Thought 8: CRITICAL - Mobile app release cycles. iOS/Android have 1-2 week App Store review process. Cannot force-update all users immediately. Requires versioned endpoint (/api/v2/) with gradual migration strategy. Actor CANNOT modify existing /api/users/{id} endpoint.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 8,
    "totalThoughts": 10
}

# Thought 9
{
    "thought": "Thought 9: Calculate full impact scope. Affected systems: 3 mobile apps + 1 web app + 1 admin dashboard + 1 monitoring dashboard + 5 scripts + 35 test files + CI/CD + 7 documentation files = 50+ touch points. Initial estimate was 1-2 components. Actual: 25x larger.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 9,
    "totalThoughts": 10
}

# Thought 10 - Conclusion
{
    "thought": "Thought 10: CONCLUSION - Risk assessment: CRITICAL (not HIGH). Breaking change with NO versioning strategy + mobile app deployment constraints + 50+ affected systems. Recommendation: Actor MUST create /api/v2/users/{id} endpoint (not modify v1). Coordinate 4-6 week rollout: (1) Deploy v2, (2) Update internal systems, (3) Submit mobile app updates, (4) Monitor v1 usage, (5) Deprecate v1 after mobile adoption. Provide migration guide. Confidence: 0.85 (high - systematic search, may miss dynamic imports).",
    "nextThoughtNeeded": False,
    "thoughtNumber": 10,
    "totalThoughts": 10
}
```

**Outcome**: Predictor classifies as CRITICAL IMPACT with explicit recommendation to create versioned endpoint (not modify existing). Prevents production outage.

**Key Techniques Demonstrated**:
- Hypothesis revision (1-2 components → 50+ touch points)
- Progressive discovery (versioning gap, mobile constraints, hidden systems)
- Multi-layer tracing (apps → scripts → tests → docs → CI/CD → monitoring)
- Confidence scoring with uncertainty (0.85 - acknowledged dynamic imports gap)

---

### Full Example 3: Evaluator Balancing Trade-offs

**Scenario**: Actor implements Redis caching for user profile API. Cache stores plaintext PII (email, phone) for 5 minutes. No cache invalidation on profile updates.

**Sequential-Thinking Execution**:

```python
# Thought 1
{
    "thought": "Thought 1: Initial scoring hypothesis. Performance: 9/10 (Redis fast, 20ms response vs 200ms DB). Security: 8/10 (Redis password-protected). Will validate these scores systematically.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 1,
    "totalThoughts": 6
}

# Thought 2
{
    "thought": "Thought 2: Evaluate security dimension deeply. Cache stores email and phone (PII) in plaintext Redis keys. If Redis compromised (memory dump attack, unauthorized access via misconfigured network), PII fully exposed. GDPR/compliance risk. Security score REVISED: 6/10 (plaintext PII storage is significant vulnerability).",
    "nextThoughtNeeded": True,
    "thoughtNumber": 2,
    "totalThoughts": 8  # Trade-off complexity discovered
}

# Thought 3
{
    "thought": "Thought 3: Quantify performance gain. Without cache: avg 200ms (DB query + serialization). With cache: avg 20ms (Redis GET). 10x speedup. 90% cache hit rate per logs. Performance gain is substantial and real.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 3,
    "totalThoughts": 8
}

# Thought 4
{
    "thought": "Thought 4: Evaluate alternative approaches. Option A: Encrypt cache values (AES-256). Adds ~5ms per request (encrypt/decrypt). Performance: 25ms (still 8x faster than DB). Security: 9/10 (encrypted at rest). Option B: Exclude PII from cache (cache only username, avatar URL). Performance: partial benefit (still query DB for email/phone). Security: 9/10. Trade-off: slight performance cost for major security gain.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 4,
    "totalThoughts": 8
}

# Thought 5
{
    "thought": "Thought 5: Check testability dimension. Tests provided for cache hit/miss scenarios. BUT no tests for cache failure (Redis down). Error handling: code falls back to DB on cache miss (good) but doesn't handle Redis connection timeout (bad). Testability: 7/10 (missing error case tests).",
    "nextThoughtNeeded": True,
    "thoughtNumber": 5,
    "totalThoughts": 9  # Found additional issue
}

# Thought 6
{
    "thought": "Thought 6: DISCOVERY - Check completeness dimension. No cache invalidation on user profile update! If user changes email, cached value served for 5 minutes (stale data). Line 120: update_profile() doesn't call cache.delete(). Completeness: 7/10 (missing invalidation logic).",
    "nextThoughtNeeded": True,
    "thoughtNumber": 6,
    "totalThoughts": 9
}

# Thought 7
{
    "thought": "Thought 7: Calculate weighted overall score. Functionality: 8/10 (works, solves problem), Code_quality: 8/10 (clear, maintainable), Performance: 9/10 (excellent), Security: 6/10 (plaintext PII), Testability: 7/10 (missing error tests), Completeness: 7/10 (no invalidation). Overall: (8*0.25 + 8*0.20 + 9*0.15 + 6*0.20 + 7*0.10 + 7*0.10) = 7.45. Threshold: ≥7.0 → 'proceed', but security 6/10 is borderline.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 7,
    "totalThoughts": 9
}

# Thought 8
{
    "thought": "Thought 8: Assess trade-off severity. Performance vs Security: Encrypting cache (Option A) retains 80% of performance gain while fixing security vulnerability. Cost-benefit strongly favors encryption. Completeness issue (cache invalidation) is independent fix, must add regardless.",
    "nextThoughtNeeded": True,
    "thoughtNumber": 8,
    "totalThoughts": 9
}

# Thought 9 - Conclusion
{
    "thought": "Thought 9: FINAL RECOMMENDATION - 'improve' verdict (not 'proceed'). Reasoning: Overall score 7.45 meets proceed threshold BUT security 6/10 for PII exposure is unacceptable risk. Next steps: (1) Encrypt cached PII (AES-256, adds 5ms, Security → 9/10), (2) Add cache invalidation in update_profile() (Completeness → 9/10), (3) Add error handling tests for Redis timeout (Testability → 9/10). Revised overall: 8.3. Estimated iterations: 1.0 (straightforward fixes).",
    "nextThoughtNeeded": False,
    "thoughtNumber": 9,
    "totalThoughts": 9
}
```

**Outcome**: Evaluator scores 7.45 overall but recommends "improve" due to security/completeness gaps. Provides 3 concrete actions with score impact predictions.

**Key Techniques Demonstrated**:
- Hypothesis revision (Security 8→6, Completeness discovered gap)
- Multi-dimensional scoring with explicit weights
- Alternative evaluation (encrypt vs exclude PII)
- Cost-benefit analysis (5ms overhead for 3-point security gain)
- Actionable recommendations with predicted score improvements

## Integration with Other MCP Tools

Sequential-thinking enhances other MCP tools by providing structured reasoning over their outputs.

### Sequential-Thinking + cipher_memory_search

**Use Case**: Learning from past similar problems to guide current analysis.

**Pattern**:
1. **Before sequential-thinking**: Search cipher for relevant patterns
2. **During sequential-thinking**: Reference past solutions as evidence
3. **After sequential-thinking**: Validate conclusions against historical outcomes

**Example**:
```
cipher_memory_search("breaking change API rename")
→ Finds: "Past API renames required 10-20 file updates + docs + CI/CD"

Thought 1: Based on cipher pattern (API rename), hypothesis: 10-20 files affected.
Thought 4: DISCOVERY - Found 35 files (higher than historical 10-20). More widespread usage than past cases.
```

### Sequential-Thinking + codex_bridge

**Use Case**: Automating exhaustive dependency discovery, then reasoning about implications.

**Pattern**:
1. **Before sequential-thinking**: Use codex to list all usages/imports
2. **During sequential-thinking**: Analyze HOW each usage will break (not just WHERE)
3. **After sequential-thinking**: Classify dependencies by type and update priority

**Example**:
```
codex("Find all usages of get_weather function")
→ Returns: 8 call sites

Thought 2: Codex found 8 direct call sites. But need to check HOW they use it.
Thought 3: Analyzed usage patterns - 5 sites pass positional args (will break), 3 use kwargs (safe).
```

### Sequential-Thinking + context7

**Use Case**: Validating implementation against current library best practices.

**Pattern**:
1. **Before sequential-thinking**: Fetch current library docs for feature
2. **During sequential-thinking**: Compare Actor implementation against docs
3. **After sequential-thinking**: Score completeness based on best practice adherence

**Example**:
```
get-library-docs("/vercel/next.js", topic="server actions")
→ Returns: Best practices (async functions, 'use server' directive, revalidatePath)

Thought 3: Compare against Next.js 14 docs. Actor uses async function ✓, 'use server' ✓, BUT missing revalidatePath.
Thought 5: Completeness score reduced from 8/10 to 6/10 for missing cache invalidation (Next.js best practice).
```

## Metrics and Outcomes

### Quantified Benefits

Based on examples in agent templates:

**Monitor Agent**:
- **Reduced false negatives**: Systematic path tracing catches 2-3x more edge cases than single-pass review
- **Specific issue identification**: 100% of issues include line numbers + severity + explanation (vs vague "needs improvement")

**Predictor Agent**:
- **Accuracy improvements**: Initial estimates revised by 2-6x after discovery (Example 1: 2 files → 18 files, Example 2: 2 components → 50+ systems)
- **Hidden system discovery**: Finds 3-5 non-obvious affected systems (CI/CD, monitoring, docs) that grep misses

**Evaluator Agent**:
- **Trade-off justification**: 100% of competing dimensions include quantified analysis (e.g., "5ms overhead for 3-point security gain")
- **Actionable recommendations**: Scores include "For 8/10: add X" guidance (not just final score)

### Process Improvements

**Fewer Iterations Needed**:
- Catching issues earlier (Monitor systematic validation) reduces Actor rework loops
- Accurate impact prediction (Predictor transitive analysis) prevents surprises during implementation
- Clear improvement paths (Evaluator trade-off analysis) guide Actor to correct fixes faster

**Better Documentation**:
- Sequential-thinking creates audit trail (why decisions made, what was considered)
- Explicit reasoning helps future implementations learn from past analyses
- Thought progression shows edge cases to consider for similar problems

**Knowledge Transfer**:
- Systematic reasoning patterns (path tracing, hypothesis revision) become reusable playbook content
- Evidence-based analysis (line numbers, metrics) enables knowledge extraction by Reflector agent
- Dimension interaction discoveries (security vs performance) captured for future Evaluator use

### Success Criteria

**When Sequential-Thinking Adds Value**:
- ✅ Problem complexity exceeds decision threshold (≥3 conditionals, >5 import sites, competing dimensions)
- ✅ Initial hypothesis gets revised during analysis (learning happened)
- ✅ Specific evidence cited (line numbers, metrics, concrete examples)
- ✅ Final conclusion is actionable (not vague "looks problematic")

**When Sequential-Thinking is Overkill**:
- ❌ Problem is trivial (simple validation, single file change)
- ❌ Analysis is linear without discoveries (no hypothesis revision needed)
- ❌ Thoughts are vague without evidence (wasting tokens for no insight)
- ❌ Same conclusion reached in 2 thoughts stretched to 10 (artificial padding)

## Conclusion

Sequential-thinking is a powerful tool for structured reasoning when agents face complex multi-step problems. Key takeaways:

1. **Use Decision Thresholds**: Don't invoke for trivial tasks (wastes tokens), do invoke for complexity triggers (nested logic, type changes, trade-offs)
2. **Hypothesis-Driven**: Start with hypothesis, search for evidence, revise when contradicted
3. **Cite Evidence**: Every thought should reference specific code (line numbers), metrics, or concrete examples
4. **Dynamic Adaptation**: Adjust thought count as complexity emerges, branch to explore alternatives
5. **Agent-Specific Patterns**: Monitor traces execution paths, Predictor traces impact layers, Evaluator traces dimension interactions

When used correctly, sequential-thinking transforms vague analysis ("might have issues") into concrete, actionable insights ("line 67 race condition, use Redis WATCH/MULTI, HIGH severity").
