# MCP Tool Usage Examples for Task Decomposition

Reference examples for task-decomposer agent. Loaded on demand for complex decompositions.

---

## sequential-thinking for Reasoning Examples

**When to use**: After finding similar features in existing codebase

**Key Difference from Pattern Search**:
- Pattern search → **Output**: "Here are the 5 subtasks for authentication"
- Sequential thinking → **Process**: "I considered user model first because... then password hashing because..."

**Example: Decomposing "Add real-time notifications"**

**Step 1 - Search for similar implementations (WHAT worked)**:
```
Query: "feature implementation notifications"
Result: Found 3 past implementations with subtask lists:
  1. WebSocket infrastructure setup
  2. Notification database models
  3. User authentication integration
  4. Notification delivery service
  5. UI components for displaying notifications

Gap: Why this order? What dependency reasoning led to this sequence?
```

**Step 2 - sequential-thinking (WHY/HOW to reason through it)**:
```
Query via mcp__sequential-thinking__sequentialthinking:

  Thought: Real-time features need persistent connection mechanism
    → Must set up WebSocket infrastructure FIRST (foundation)

  Thought: Notifications need to be stored for offline users
    → Database models come BEFORE delivery logic (data prerequisite)

  Thought: Delivery must know WHO to send to
    → User authentication integration is a DEPENDENCY for delivery

  Decision: Critical path is infrastructure → data → auth → delivery → UI
  Reasoning: Each layer depends on previous layer being stable
```

**Value**: Structured thinking EXPLAINS the dependency logic. Meta-knowledge generalizes beyond specific features.

---

## sequential-thinking Examples

**USE for**:
- "Implement real-time notifications" (many moving parts: WebSocket, message queue, persistence, UI updates)
- "Migrate database from SQL to NoSQL" (affects every data access layer, requires careful sequencing)
- "Add multi-tenancy support" (touches auth, data isolation, routing, configuration)

**DON'T USE for**:
- "Add validation to email field" (straightforward, well-understood)
- "Update button color" (trivial, no hidden complexity)
- "Fix typo in error message" (atomic, no decomposition needed)

---

## sequential-thinking for Multi-step Setup Examples

**Critical Use Case: Multi-step library setup**

Many libraries require specific initialization order:
- Database ORMs: connection → models → migrations → queries
- Auth libraries: config → middleware → routes
- Testing frameworks: setup → fixtures → tests

**Example: Decomposing "Add Stripe payment processing"**

❌ **Wrong order (without reasoning through dependencies)**:
```
1. Create payment endpoint
2. Handle webhooks
3. Initialize Stripe SDK
4. Add API keys
→ Result: Can't implement endpoint (step 1) without SDK (step 3)
```

✅ **Correct order (reasoned from initialization requirements)**:
```
1. Add Stripe SDK dependency
2. Configure API keys
3. Initialize Stripe client
4. Create payment intent endpoint
5. Handle webhook callbacks
6. Test with Stripe CLI
```

Always reason through a library's initialization requirements before sequencing subtasks.
