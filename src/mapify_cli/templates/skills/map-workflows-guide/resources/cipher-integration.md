# mem0 Integration

> **MIGRATION NOTE:** As of v4.0, pattern storage has migrated from cipher to mem0 MCP. This document describes the new mem0-based system.

mem0 is MAP's tiered knowledge system. It stores patterns across namespaces (branch → project → org) for both project-specific and cross-project knowledge sharing.

## What is mem0?

**mem0** = MCP (Model Context Protocol) server for tiered pattern storage

**Key Features:**
- **Tiered namespaces** - L1 (branch), L2 (project), L3 (org)
- **Semantic search** - Find patterns by meaning via tiered search
- **Fingerprint deduplication** - Prevents storing exact duplicates
- **Persistent storage** - Knowledge survives across sessions

---

## Tiered Memory System

### Tier Overview

| Tier | Namespace | Scope | Use Case |
|------|-----------|-------|----------|
| **L1 (Recent)** | Branch-scoped | Current work session | Patterns specific to current feature |
| **L2 (Frequent)** | Project-scoped | All project patterns | Shared project knowledge |
| **L3 (Semantic)** | Org-scoped | Cross-project patterns | Organizational best practices |

### Search Flow

Tiered search queries tiers in order: L1 → L2 → L3

```
mcp__mem0__map_tiered_search("async implementation")
  ↓
L1 (branch): Check recent patterns from current feature branch
  ↓
L2 (project): Check project-level patterns
  ↓
L3 (org): Check organizational patterns
  ↓
Return merged results (most specific first)
```

### Example Pattern Distribution

**L1 (Branch-specific):**
- "Using new auth middleware pattern for this feature"
- "This branch uses beta API version 2.1"

**L2 (Project-specific):**
- "Use FastAPI with uvicorn for this API service"
- "JWT secret stored in .env file (JWT_SECRET)"
- "Database migrations via Alembic in migrations/ folder"

**L3 (Org-wide):**
- "Use async/await for I/O operations to avoid blocking"
- "Validate JWT tokens before processing requests"
- "Database schema changes require migration scripts"

---

## MCP Tools

### 1. mcp__mem0__map_tiered_search

**Purpose:** Find existing patterns before implementing

**Used by:**
- Actor (before implementing)
- Reflector (before suggesting new patterns)
- Curator (before creating ADD operations)

**Example call:**
```python
mcp__mem0__map_tiered_search(
  query="JWT token validation best practices",
  category="security"  # optional filter
)
```

**Returns:**
```json
{
  "patterns": [
    {
      "id": "impl-0042",
      "content": "Always verify JWT signature before trusting claims",
      "tier": "project",
      "relevance": 0.89
    }
  ],
  "tiers_searched": ["branch", "project", "org"]
}
```

### 2. mcp__mem0__map_add_pattern

**Purpose:** Store new patterns

**Used by:**
- Curator (after validating patterns)

**Example call:**
```python
mcp__mem0__map_add_pattern(
  content="Use async/await for I/O operations",
  category="implementation",
  tier="project"  # default: project
)
```

**Returns:**
```json
{
  "created": true,
  "pattern_id": "impl-0043",
  "fingerprint": "abc123..."
}
```

**If duplicate exists:**
```json
{
  "created": false,
  "existing_id": "impl-0012",
  "reason": "Duplicate fingerprint"
}
```

### 3. mcp__mem0__map_archive_pattern

**Purpose:** Deprecate outdated patterns

**Used by:**
- Curator (when patterns become obsolete)

**Example call:**
```python
mcp__mem0__map_archive_pattern(
  pattern_id="impl-0042",
  reason="Superseded by new auth approach"
)
```

---

## Deduplication Strategy

### Fingerprint-Based Deduplication

Each pattern has a fingerprint (content hash). When adding:

```
Curator tries to add pattern
  ↓
map_add_pattern computes fingerprint
  ↓
Check if fingerprint exists in target tier
  ↓
If exists: Return created=false with existing_id
If not: Create new pattern, return created=true
```

### Why Fingerprint vs Similarity

| Approach | Pros | Cons |
|----------|------|------|
| Fingerprint (exact) | Fast, deterministic | Only catches exact duplicates |
| Similarity (semantic) | Catches near-duplicates | Slower, requires embeddings |

**MAP choice:** Fingerprint for deduplication (fast), semantic for search (smart)

---

## Knowledge Flow

### Adding New Patterns

```
1. Subtask completed successfully
2. Run /map-learn to trigger learning
3. Reflector extracts patterns
4. Reflector searches mem0 (check if similar exists)
5. Curator validates patterns
6. Curator calls map_add_pattern for each new pattern
7. Pattern stored in appropriate tier
```

### Searching Patterns

```
1. New subtask starts
2. Actor calls map_tiered_search(subtask_description)
3. Results from L1 → L2 → L3 merged
4. Actor applies most relevant patterns
5. Implementation benefits from accumulated knowledge
```

---

## Tier Promotion

Patterns can be promoted from project to org tier when:

1. Pattern used successfully across multiple projects
2. Manual review confirms universal applicability
3. Admin uses `mcp__mem0__map_promote_pattern`

```python
mcp__mem0__map_promote_pattern(
  pattern_id="impl-0042",
  from_tier="project",
  to_tier="org"
)
```

---

## Benefits

### 1. Scoped Knowledge

- Branch patterns don't pollute project scope
- Project patterns don't pollute org scope
- Clear boundaries for different concerns

### 2. Fast Local Access

- L1 (branch) = fastest access
- Most relevant patterns found first
- Cross-project patterns available when needed

### 3. Quality Through Tiers

- Experimental patterns stay in branch tier
- Validated patterns promote to project tier
- Universal patterns reach org tier

---

## Troubleshooting

### Patterns not found in search

**Check:**
1. Pattern exists in correct tier: Use `mcp__mem0__get_memories` to list
2. Query matches pattern content: Try more specific query
3. Category filter isn't too restrictive

### Duplicate patterns appearing

**Check:**
1. Content differs slightly (different fingerprints)
2. Patterns in different tiers (L1 vs L2)

**Solution:**
- Archive older duplicate
- Standardize pattern wording

### Pattern not saving

**Check:**
1. `created: false` in response = duplicate
2. Check `existing_id` to find the duplicate
3. Decide whether to update existing or archive it

---

## Best Practices

### For Workflows

1. **Always search before implementing** - Actor should search mem0 first
2. **Use appropriate tier** - Branch for experimental, project for validated
3. **Archive instead of delete** - Preserve history for auditing
4. **Include category** - Helps filtering and organization

### For Users

1. **Run /map-learn after workflows** - Extracts and stores patterns
2. **Review archived patterns periodically** - May have valuable history
3. **Promote good patterns** - Move validated patterns to higher tiers
4. **Query across tiers** - Don't limit to single tier

---

**See also:**
- [Playbook System (Legacy)](playbook-system.md) - Historical reference
- [Agent Architecture](agent-architecture.md) - Reflector/Curator roles
- [map-efficient Deep Dive](map-efficient-deep-dive.md) - Batched learning workflow
