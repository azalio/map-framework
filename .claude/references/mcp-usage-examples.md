# MCP Tool Usage Examples for Task Decomposition

Reference examples for task-decomposer agent. Loaded on demand for complex decompositions.

---

## cipher_memory_search Examples

**Good Example - Decomposing "Add user authentication"**:
```
Search: "feature implementation authentication" → find past auth implementations
Search: "task decomposition auth flow" → learn typical subtask breakdown
Result: Discover pattern:
  1. User model (foundation)
  2. Password hashing (depends on user model)
  3. Login/logout endpoints (depends on password hashing)
  4. Session management (depends on endpoints)
  5. Auth middleware (depends on session)
  6. Protected routes (depends on middleware)

Use this proven order instead of guessing.
```

**Bad Example - Decomposing without historical context**:
```
Jump directly to listing subtasks
→ Miss critical dependency order (e.g., try to implement middleware before session management exists)
→ Overlook edge cases that past implementations revealed
→ Create subtasks that are too coarse or too granular
```

---

## cipher_search_reasoning_patterns Examples

**When to use**: After cipher_memory_search finds similar features

**Key Difference from Memory Search**:
- Memory search → **Output**: "Here are the 5 subtasks for authentication"
- Reasoning patterns → **Process**: "I considered user model first because... then password hashing because..."

**Example: Decomposing "Add real-time notifications"**

**Step 1 - cipher_memory_search (WHAT worked)**:
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

**Step 2 - cipher_search_reasoning_patterns (WHY/HOW it worked)**:
```
Query: "successful task decomposition real-time features"
Result: Found reasoning trace:

  Thought: Real-time features need persistent connection mechanism
    → Must set up WebSocket infrastructure FIRST (foundation)

  Thought: Notifications need to be stored for offline users
    → Database models come BEFORE delivery logic (data prerequisite)

  Thought: Delivery must know WHO to send to
    → User authentication integration is a DEPENDENCY for delivery

  Decision: Critical path is infrastructure → data → auth → delivery → UI
  Reasoning: Each layer depends on previous layer being stable
```

**Value**: Reasoning trace EXPLAINS the dependency logic. Meta-knowledge generalizes beyond specific features.

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

## get-library-docs Examples

**Critical Use Case: Multi-step library setup**

Many libraries require specific initialization order:
- Database ORMs: connection → models → migrations → queries
- Auth libraries: config → middleware → routes
- Testing frameworks: setup → fixtures → tests

**Example: Decomposing "Add Stripe payment processing"**

❌ **Wrong order (without checking docs)**:
```
1. Create payment endpoint
2. Handle webhooks
3. Initialize Stripe SDK
4. Add API keys
→ Result: Can't implement endpoint (step 1) without SDK (step 3)
```

✅ **Correct order (from Stripe docs)**:
```
1. Add Stripe SDK dependency
2. Configure API keys
3. Initialize Stripe client
4. Create payment intent endpoint
5. Handle webhook callbacks
6. Test with Stripe CLI
```

Always check library docs for initialization requirements.

---

## deepwiki Examples

**Example: Decomposing "Add API rate limiting" for unfamiliar project**

```
Ask deepwiki: "How does Express.js handle rate limiting?"
Learn common pattern:
  1. Rate limiter middleware (foundation)
  2. Storage backend (Redis/in-memory)
  3. Route-specific limits configuration
  4. Error responses for exceeded limits
  5. Admin bypass logic (optional)

Apply this proven structure to your decomposition.
```
