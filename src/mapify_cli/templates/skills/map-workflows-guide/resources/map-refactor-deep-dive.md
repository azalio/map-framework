# /map-refactor Deep Dive

## When to Use

**Code restructuring without behavior changes:**
- Improving code organization
- Renaming for clarity
- Extracting common logic
- Cleaning up technical debt
- Simplifying complex functions
- Reorganizing file structure

**Why /map-refactor?**
- Focus on dependency analysis
- Breaking change detection
- Migration planning
- Preserving functionality

---

## Refactoring Workflow

### Key Principle: Behavior Preservation

```
Refactoring = Changing structure WITHOUT changing behavior
```

**Verification:**
- All existing tests must pass
- No new features added
- API contracts preserved (or versioned)

### Standard Pipeline

```
1. TaskDecomposer: Break refactoring into safe steps
   - Identify dependencies
   - Plan incremental changes
   - Define rollback points

2. For each subtask:
   - Actor refactors code
   - Monitor validates (tests MUST pass)
   - Predictor analyzes impact (CRITICAL)
   - Evaluator checks completeness

3. Reflector extracts:
   - What patterns emerged?
   - What dependencies were discovered?
   - What risks were mitigated?

4. Curator documents:
   - Refactoring techniques
   - Dependency patterns
   - Migration strategies
```

---

## Dependency Impact Analysis

### Predictor's Role in Refactoring

**Always runs for refactoring** (high priority):

**What Predictor tracks:**
1. **Direct dependencies:**
   - Files that import refactored module
   - Functions that call refactored functions
   - Types that extend refactored types

2. **Indirect dependencies:**
   - Services that depend on direct dependencies
   - Tests that rely on behavior
   - Configuration that references paths

3. **Breaking changes:**
   - Renamed exports
   - Changed function signatures
   - Moved files

**Example output:**
```json
{
  "affected_files": [
    {"path": "services/user.service.ts", "impact": "high", "reason": "imports renamed function"},
    {"path": "tests/user.test.ts", "impact": "medium", "reason": "tests old API"},
    {"path": "api/routes.ts", "impact": "low", "reason": "indirect dependency"}
  ],
  "breaking_changes": [
    {
      "type": "rename",
      "from": "getUserData",
      "to": "fetchUserProfile",
      "affected": 12 файлов
    }
  ],
  "migration_steps": [
    "1. Update imports in user.service.ts",
    "2. Update function calls (12 locations)",
    "3. Update tests to use new name",
    "4. Run full test suite"
  ]
}
```

---

## Example: Extract Service Pattern

**Task:** "Refactor auth logic into separate service"

**Current state:**
```typescript
// controllers/auth.controller.ts (300 lines, mixed concerns)
class AuthController {
  login(req, res) {
    // JWT generation logic
    // Database queries
    // Response formatting
    // All mixed together
  }
}
```

**Goal:**
```typescript
// services/auth.service.ts (clean separation)
class AuthService {
  generateToken(user) { ... }
  validateCredentials(email, password) { ... }
}

// controllers/auth.controller.ts (thin controller)
class AuthController {
  constructor(private authService: AuthService) {}
  
  login(req, res) {
    const user = await this.authService.validateCredentials(...);
    const token = this.authService.generateToken(user);
    res.json({ token });
  }
}
```

**Decomposition:**
```
ST-1: Create AuthService class skeleton
ST-2: Extract token generation logic
ST-3: Extract credential validation logic
ST-4: Update AuthController to use AuthService
ST-5: Update dependency injection
ST-6: Update all tests
```

**Execution:**

```
ST-1: Create skeleton
├─ Actor: Create services/auth.service.ts
├─ Monitor: ✅ Valid (compiles, tests pass)
├─ Predictor: ⏭️ Low risk (new file, no impact)
└─ Apply

ST-2: Extract token generation
├─ Actor: Move generateToken() to AuthService
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN (affects auth flow)
│  └─ Impact: AuthController must be updated
└─ Migration: Update imports

ST-3: Extract validation
├─ Actor: Move validateCredentials() to AuthService
├─ Monitor: ✅ Valid
├─ Predictor: ✅ RAN
│  └─ Impact: 3 files import this function
└─ Migration: Update all imports

ST-4: Update AuthController
├─ Actor: Inject AuthService, call methods
├─ Monitor: ✅ Valid (all tests pass)
├─ Predictor: ✅ RAN
│  └─ Impact: DI container must provide AuthService
└─ Migration: Update DI config

ST-5: Update DI
├─ Actor: Register AuthService in container
├─ Monitor: ✅ Valid
└─ Apply

ST-6: Update tests
├─ Actor: Mock AuthService in controller tests
├─ Monitor: ✅ All tests pass
└─ Done

Reflector:
├─ Pattern: "Separate business logic from controllers"
├─ Pattern: "Use dependency injection for services"
└─ Technique: "Incremental refactoring (6 safe steps)"

Curator:
├─ ADD "arch-0042: Controller-Service pattern"
└─ ADD "refactor-0099: Incremental extraction technique"
```

**Token usage:** ~9K tokens (6 subtasks, Predictor always runs)
**Risk:** Low (tests pass at each step)
**Result:** Clean separation, no behavior changes

---

## Breaking Change Detection

### What Counts as Breaking

**API changes:**
- Function renamed
- Parameters added/removed/reordered
- Return type changed

**Module changes:**
- File moved
- Export renamed
- Public interface modified

**Behavior changes:**
- Performance characteristics
- Error handling
- Side effects

### Migration Planning

**Predictor generates:**
1. **List of affected files** (with impact level)
2. **Migration checklist** (step-by-step)
3. **Rollback strategy** (if migration fails)
4. **Testing plan** (what to verify)

---

## Refactoring Patterns

### 1. Extract Function

**Before:**
```typescript
function processOrder(order) {
  // 50 lines of complex logic
  const total = order.items.reduce((sum, item) => sum + item.price * item.qty, 0);
  const tax = total * 0.08;
  const shipping = total > 50 ? 0 : 5;
  return total + tax + shipping;
}
```

**After:**
```typescript
function calculateTotal(items) {
  return items.reduce((sum, item) => sum + item.price * item.qty, 0);
}

function calculateTax(total) {
  return total * 0.08;
}

function calculateShipping(total) {
  return total > 50 ? 0 : 5;
}

function processOrder(order) {
  const total = calculateTotal(order.items);
  const tax = calculateTax(total);
  const shipping = calculateShipping(total);
  return total + tax + shipping;
}
```

**Predictor impact:** Low (internal refactoring, API unchanged)

### 2. Rename for Clarity

**Before:**
```typescript
function getData(id) { ... }  // Vague
function updateInfo(data) { ... }  // Unclear
```

**After:**
```typescript
function fetchUserProfile(userId) { ... }  // Clear
function updateUserEmail(email) { ... }  // Specific
```

**Predictor impact:** High (breaking change, all callers must update)

### 3. Move to Shared Module

**Before:**
```
utils/helpers.ts (500 lines, mixed utilities)
```

**After:**
```
utils/string-helpers.ts (string functions)
utils/date-helpers.ts (date functions)
utils/array-helpers.ts (array functions)
```

**Predictor impact:** Medium (import paths change, but behavior same)

---

## Troubleshooting

**Issue:** Tests fail after refactoring
**Cause:** Behavior inadvertently changed
**Solution:** Revert, refactor in smaller steps

**Issue:** Too many breaking changes
**Cause:** Refactoring too aggressive
**Solution:** Use adapter pattern for backward compatibility

**Issue:** Predictor didn't catch dependency
**Cause:** Indirect/runtime dependency
**Solution:** Improve static analysis, add integration tests

---

**See also:**
- [agent-architecture.md](agent-architecture.md) - Predictor's dependency analysis
- [map-feature-deep-dive.md](map-feature-deep-dive.md) - When refactoring is risky
