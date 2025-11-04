# /map-feature Deep Dive

## When to Use

**Critical features requiring maximum confidence:**
- Authentication and authorization systems
- Payment processing
- Database schema migrations
- Security-sensitive functionality
- First-time complex features
- High-risk refactoring

**Why /map-feature?**
- Maximum validation (all agents, all subtasks)
- Per-subtask learning (immediate feedback)
- Full impact analysis (Predictor always runs)
- Highest quality assurance

---

## Full Pipeline

### Per-Subtask Cycle

```
For each subtask:
  1. Actor implements
  2. Monitor validates
  3. Predictor analyzes impact (ALWAYS)
  4. Evaluator scores quality
  5. If approved:
     5a. Reflector extracts patterns
     5b. Curator updates playbook
     5c. Apply changes
  6. If not approved: Return to Actor
```

**Key difference from /map-efficient:**
- Predictor runs EVERY subtask (not conditional)
- Reflector/Curator run AFTER EVERY subtask (not batched)

---

## Per-Subtask Learning Rationale

### Why Learn Per-Subtask?

**Immediate feedback loop:**
```
Subtask 1: Implement JWT generation
  ↓ completed
Reflector: "JWT secret storage pattern"
Curator: Add bullet "impl-0099: Store secrets in env vars"
  ↓ playbook updated
Subtask 2: Implement JWT validation
  ↓ starts
Actor queries playbook: Finds "impl-0099"
  ↓ applies pattern
Uses env vars (learned from Subtask 1)
```

**Benefit:** Each subtask benefits from previous subtask learnings

### Trade-off vs Batched Learning

**Per-subtask (/map-feature):**
- ✅ Immediate pattern application
- ✅ Error correction within workflow
- ❌ Higher token cost (N × Reflector/Curator)

**Batched (/map-efficient):**
- ✅ Lower token cost (1 × Reflector/Curator)
- ⚠️ Patterns applied in next workflow
- ✅ Holistic insights (sees all subtasks together)

**When per-subtask matters:**
- Complex multi-step features
- Interdependent subtasks
- Learning applies immediately

---

## Example: Critical Authentication System

**Task:** "Implement OAuth2 authentication"

**Why /map-feature:**
- Security-critical (high risk)
- Complex (multiple components)
- First-time implementation

**Execution:**

```
TaskDecomposer:
├─ ST-1: Setup OAuth2 provider config
├─ ST-2: Implement authorization code flow
├─ ST-3: Secure token storage
├─ ST-4: Add refresh token rotation
└─ ST-5: Implement logout

ST-1: OAuth2 provider config
├─ Actor: Create config/oauth.ts
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (security-sensitive)
│  └─ Impact: Config must not be committed
├─ Evaluator: ✅ Approved (score: 9/10)
├─ Reflector: Pattern "Store OAuth secrets in env"
└─ Curator: ADD "sec-0042: OAuth secrets in .env"

ST-2: Authorization code flow
├─ Actor: Implement auth/oauth.ts
│  └─ Queries playbook: Finds "sec-0042"
│  └─ Uses .env for secrets (learned from ST-1!)
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (affects auth flow)
│  └─ Impact: All protected routes need update
├─ Evaluator: ✅ Approved (score: 9/10)
├─ Reflector: Pattern "PKCE for public clients"
└─ Curator: ADD "sec-0043: Use PKCE extension"

[ST-3, ST-4, ST-5 continue with same pattern]
```

**Token usage:** ~18K tokens (full pipeline, 5 subtasks)

**Quality achieved:**
- Zero security vulnerabilities
- All patterns documented
- Team learned OAuth2 best practices

---

## Predictor: Always-On Analysis

### What Predictor Catches

**Breaking changes:**
- API signature modifications
- Database schema changes
- Configuration format updates

**Dependencies:**
- Affected services
- Required migrations
- Client updates needed

**Risks:**
- Backward compatibility issues
- Performance impacts
- Security implications

### Example Output

```json
{
  "affected_files": [
    {"path": "api/auth.ts", "impact": "high"},
    {"path": "database/users.sql", "impact": "medium"}
  ],
  "breaking_changes": [
    {
      "type": "API",
      "description": "User model no longer returns password field",
      "mitigation": "Update all API clients to not expect password"
    }
  ],
  "required_updates": [
    "Update client SDK to v2.0",
    "Run migration: add_oauth_tokens_table"
  ],
  "risk_level": "high"
}
```

---

## When map-feature is Overkill

**Don't use for:**
- Simple CRUD operations → Use /map-efficient
- Bug fixes → Use /map-debug
- Non-critical features → Use /map-efficient
- Code you understand well → Use /map-efficient

**Cost vs benefit:**
- /map-feature: 100% token cost
- /map-efficient: 60-70% token cost
- **Savings: 30-40% by using /map-efficient**

**Rule of thumb:**
- Critical/security = /map-feature
- Production/moderate = /map-efficient
- Everything else = /map-efficient

---

## Quality Metrics

### Success Indicators

**All features implemented:**
- ✅ All acceptance criteria met
- ✅ All tests passing
- ✅ No security vulnerabilities

**Knowledge captured:**
- ✅ Playbook bullets created (N subtasks → N+ bullets)
- ✅ High-quality bullets synced to cipher
- ✅ Team can apply patterns immediately

**Impact understood:**
- ✅ All breaking changes documented
- ✅ Migration path clear
- ✅ Dependencies updated

---

## Troubleshooting

**Issue:** Workflow taking too long
**Cause:** Per-subtask learning overhead
**Solution:** Consider /map-efficient for next similar task

**Issue:** Too many playbook bullets created
**Cause:** Reflector suggesting redundant patterns
**Solution:** Curator should check cipher more aggressively

**Issue:** Predictor always says "high risk"
**Cause:** Overly conservative risk assessment
**Solution:** Tune Predictor thresholds in `.claude/agents/predictor.md`

---

**See also:**
- [map-efficient-deep-dive.md](map-efficient-deep-dive.md) - Optimized alternative
- [agent-architecture.md](agent-architecture.md) - Understanding all agents
- [playbook-system.md](playbook-system.md) - How knowledge is stored
