# MCP Tool Usage Examples for Task Decomposition

Reference examples for task-decomposer agent. Loaded on demand for complex decompositions.

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
