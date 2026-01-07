# Task Decomposition Examples

Reference examples for task-decomposer agent. Load dynamically based on task complexity.

---

## Example B: Cross-Cutting Concern (Complex)

**Goal**: "Add audit logging to all admin actions"

**Why this is tricky**: Touches many files, needs consistent pattern, architectural decision

**Full JSON Output**:
```json
{
  "schema_version": "2.0",
  "analysis": {
    "assumptions": ["Celery worker is configured and running", "Admin endpoints use @admin_required decorator"],
    "open_questions": []
  },
  "blueprint": {
    "id": "admin-audit-logging",
    "summary": "Async audit logging system for admin actions with sensitive data filtering and queryable log storage",
    "subtasks": [
      {
        "id": "ST-001",
        "title": "Create AuditLog database model",
        "description": "Create AuditLog model in models/audit_log.py with fields: id, admin_user_id, action, resource_type, resource_id, old_values (JSON), new_values (JSON), ip_address, user_agent, created_at. Add indexes on admin_user_id and created_at.",
        "dependencies": [],
        "risk_level": "low",
        "risks": [],
        "security_critical": true,
        "complexity_score": 4,
        "complexity_rationale": "Score 4: Base(1) + Novelty(+1) + Deps(+0) + Scope(+2) + Risk(+0) = 4",
        "validation_criteria": [
          "AuditLog model exists with all specified fields",
          "JSON fields can store arbitrary dict data",
          "Indexes exist on admin_user_id and created_at",
          "Migration runs without errors on existing data"
        ],
        "test_strategy": {
          "unit": "Test model validation, test JSON field serialization",
          "integration": "Test indexes are created, test FK to users",
          "e2e": "N/A"
        },
        "affected_files": [
          "models/audit_log.py",
          "migrations/versions/create_audit_logs_table.py"
        ]
      },
      {
        "id": "ST-002",
        "title": "Implement async audit logging service with sensitive field filtering",
        "description": "Create AuditService in services/audit_service.py with log_action() that queues via Celery. Filter sensitive fields (password, token, secret, key) from old/new values.",
        "dependencies": ["ST-001"],
        "risk_level": "medium",
        "risks": [],
        "security_critical": true,
        "complexity_score": 5,
        "complexity_rationale": "Score 5: Base(1) + Novelty(+1) + Deps(+1) + Scope(+2) + Risk(+0) = 5",
        "validation_criteria": [
          "log_action() queues background task (does not block request)",
          "Fields containing 'password', 'token', 'secret', 'key' are redacted as '[REDACTED]'",
          "Audit log persists to database within 5 seconds of action"
        ],
        "implementation_hint": "Use Celery @shared_task with retry policy for queue failures",
        "test_strategy": {
          "unit": "Test sensitive field filtering, test payload creation",
          "integration": "Test async task queued, test DB persistence",
          "e2e": "N/A"
        },
        "affected_files": [
          "services/audit_service.py",
          "tasks/audit_tasks.py",
          "utils/sensitive_filter.py"
        ]
      },
      {
        "id": "ST-003",
        "title": "Create @audit_admin_action decorator with before/after state capture",
        "description": "Create decorator in decorators/audit.py that wraps admin endpoints, captures resource state before/after action, calls AuditService. Support both sync and async endpoints.",
        "dependencies": ["ST-002"],
        "risk_level": "medium",
        "risks": [],
        "security_critical": false,
        "complexity_score": 6,
        "complexity_rationale": "Score 6: Base(1) + Novelty(+3) + Deps(+1) + Scope(+1) + Risk(+0) = 6",
        "validation_criteria": [
          "Decorator captures admin user from request context",
          "Decorator captures resource state before action execution",
          "Decorator captures resource state after action execution",
          "Works with both sync and async view functions"
        ],
        "implementation_hint": "Use functools.wraps and inspect.iscoroutinefunction for async detection",
        "test_strategy": {
          "unit": "Test context capture, test before/after state diff",
          "integration": "Test decorator with real endpoints",
          "e2e": "N/A"
        },
        "affected_files": [
          "decorators/audit.py"
        ]
      },
      {
        "id": "ST-004",
        "title": "Apply @audit_admin_action to all admin endpoints",
        "description": "Add decorator to all endpoints with @admin_required in api/routes/admin/. Covers: users, roles, settings, moderation modules.",
        "dependencies": ["ST-003"],
        "risk_level": "low",
        "risks": [],
        "security_critical": false,
        "complexity_score": 4,
        "complexity_rationale": "Score 4: Base(1) + Novelty(+0) + Deps(+1) + Scope(+2) + Risk(+0) = 4",
        "validation_criteria": [
          "All @admin_required endpoints have @audit_admin_action",
          "User CRUD operations create audit logs",
          "Role assignments create audit logs",
          "Settings changes create audit logs"
        ],
        "test_strategy": {
          "unit": "N/A",
          "integration": "Test each admin endpoint creates audit log",
          "e2e": "Full admin action flow creates audit entry"
        },
        "affected_files": [
          "api/routes/admin/users.py",
          "api/routes/admin/roles.py",
          "api/routes/admin/settings.py",
          "api/routes/admin/moderation.py"
        ]
      },
      {
        "id": "ST-005",
        "title": "Add GET /admin/audit-logs query endpoint",
        "description": "Create endpoint in api/routes/admin/audit.py with filtering by admin_user, action, resource_type, date range. Paginated. Super-admin only access.",
        "dependencies": ["ST-001"],
        "risk_level": "low",
        "risks": [],
        "security_critical": true,
        "complexity_score": 5,
        "complexity_rationale": "Score 5: Base(1) + Novelty(+1) + Deps(+1) + Scope(+2) + Risk(+0) = 5",
        "validation_criteria": [
          "GET /admin/audit-logs returns paginated JSON array",
          "Supports ?admin_user_id, ?action, ?resource_type query params",
          "Supports ?from_date and ?to_date for date range",
          "Returns 403 for non-super-admin users"
        ],
        "test_strategy": {
          "unit": "Test filter logic, test pagination math",
          "integration": "Test endpoint returns correct logs",
          "e2e": "Test super-admin can query audit logs"
        },
        "affected_files": [
          "api/routes/admin/audit.py",
          "api/schemas/audit.py"
        ]
      }
    ]
  }
}
```

---

## Example C: Anti-Pattern Gallery (DO NOT DO THIS)

**Goal**: "Add user authentication"

**BAD Decomposition** (multiple violations):

```json
{
  "analysis": {
    "complexity": "medium",
    "estimated_hours": 20,
    "risks": [],
    "dependencies": []
  },
  "subtasks": [
    {
      "id": 1,
      "title": "Add authentication",
      "description": "Make the API secure",
      "dependencies": [],
      "estimated_complexity": "high",
      "complexity_score": 8,
      "complexity_rationale": "High complexity",
      "test_strategy": {
        "unit": "Test it works",
        "integration": "N/A",
        "e2e": "N/A"
      },
      "affected_files": ["backend"],
      "acceptance": ["It works", "Users can login"]
    },
    {
      "id": 2,
      "title": "Add tests",
      "description": "Write tests for auth",
      "dependencies": [],
      "estimated_complexity": "low",
      "complexity_score": 2,
      "test_strategy": {
        "unit": "Write tests",
        "integration": "N/A",
        "e2e": "N/A"
      },
      "affected_files": ["tests"],
      "acceptance": ["Tests pass"]
    }
  ]
}
```

**What's Wrong** (annotated):

| Issue | Violation | How to Fix |
|-------|-----------|------------|
| `"title": "Add authentication"` | ❌ NOT ATOMIC - encompasses 5+ subtasks | Split into: User model, Password hashing, Login endpoint, Session management, Auth middleware |
| `"description": "Make the API secure"` | ❌ VAGUE - no implementation guidance | Specify: "Create User model with email, hashed_password fields using bcrypt" |
| `"dependencies": []` for both | ❌ MISSING DEPS - tests depend on implementation | Subtask 2 should have `"dependencies": ["ST-001"]` |
| `"risks": []` for medium complexity | ❌ EMPTY RISKS - auth always has risks | Add: "Password hashing algorithm choice", "Session hijacking", "Token expiration handling" |
| `"complexity_rationale": "High complexity"` | ❌ NO CALCULATION - just restates category | Use framework: "Score X: factor (+N), factor (+N)..." |
| `"affected_files": ["backend"]"` | ❌ VAGUE PATHS - not actionable | Use: "models/user.py", "services/auth_service.py", "api/routes/auth.py" |
| `"acceptance": ["It works"]"` | ❌ NOT TESTABLE - subjective | Use: "POST /login returns JWT token with valid credentials" |

**CORRECT Decomposition** would have 5-7 subtasks:
1. Create User model with authentication fields
2. Implement password hashing service
3. Create login/logout endpoints
4. Implement JWT token generation
5. Add authentication middleware
6. Write integration tests for auth flow
7. Document authentication API

---

## Example D: Ambiguous Goal Handling

**Goal**: "Improve performance"

**Problem**: Goal is too vague - multiple valid interpretations

**How to Handle**:

1. **Use sequentialthinking** to explore interpretations
2. **Return empty subtasks with open_questions**
3. **Request clarification before decomposing**

**Decomposition Response**:

```json
{
  "schema_version": "2.0",
  "analysis": {
    "assumptions": [],
    "open_questions": [
      "Which system component is experiencing performance issues?",
      "What metrics indicate the current performance problem?",
      "What is the target performance improvement (latency, throughput, resource usage)?",
      "Is this about backend, frontend, database, or all of the above?"
    ]
  },
  "blueprint": {
    "id": "pending-clarification",
    "summary": "Decomposition blocked pending requirement clarification",
    "subtasks": []
  }
}
```

**Note**: For ambiguous goals, it's BETTER to return empty subtasks with clear questions than to guess wrong.

**After Clarification** ("Database queries are slow - reduce average query time from 500ms to 50ms"):

The decomposition would then include specific subtasks:
1. Profile and identify slowest queries
2. Add missing database indexes
3. Optimize N+1 query patterns
4. Implement query result caching
5. Add query performance monitoring
