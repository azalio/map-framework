# Playbook System (LEGACY)

> **DEPRECATED:** As of v4.0, pattern storage has migrated from playbook.db to mem0 MCP with tiered namespaces. This document is retained for historical reference. For current implementation, use mem0 MCP tools:
> - `mcp__mem0__map_tiered_search` - Search patterns
> - `mcp__mem0__map_add_pattern` - Store patterns
> - `mcp__mem0__map_archive_pattern` - Deprecate patterns

The playbook was MAP's project-specific knowledge base. It stored patterns, gotchas, and best practices learned during development.

## Structure (Legacy)

### Database Schema (Legacy)

**Location:** `.claude/playbook.db` (SQLite) - **NO LONGER USED IN v4.0+**

**Tables:**
- `bullets` - Individual knowledge items
- `bullets_fts` - Full-text search index (FTS5)
- `embeddings` - Semantic vectors for similarity search

### Bullet Format

```json
{
  "id": "impl-0042",
  "section": "IMPLEMENTATION_PATTERNS",
  "content": "Use async/await for I/O operations to avoid blocking",
  "code_example": "async def fetch(): await client.get(url)",
  "tags": ["python", "async", "performance"],
  "helpful_count": 7,
  "harmful_count": 0,
  "quality_score": 7,
  "created_at": "2025-11-03T10:30:00",
  "updated_at": "2025-11-03T14:20:00"
}
```

---

## Sections

Playbook organizes knowledge into 6 sections:

### 1. IMPLEMENTATION_PATTERNS
General coding patterns and techniques
- Example: "Use dependency injection for testability"
- Example: "Lazy imports in CLI commands reduce startup time"

### 2. DEBUGGING_TECHNIQUES  
Debugging strategies and troubleshooting
- Example: "UV tool installation failures: check PATH, verify entry points"
- Example: "pytest fixtures - use scope='module' for expensive setup"

### 3. SECURITY_PATTERNS
Security best practices and vulnerabilities
- Example: "Bash auto-approval: add space after command name to prevent prefix attacks"
- Example: "SQL injection: use parameterized queries, never string concatenation"

### 4. TESTING_STRATEGIES
Testing approaches and patterns
- Example: "3-layer testing for CLI: unit, integration, end-to-end"
- Example: "Mock file system with tmp_path fixture in pytest"

### 5. ARCHITECTURE_PATTERNS
High-level design decisions
- Example: "Modular agent system: one agent per concern"
- Example: "Progressive disclosure: main file <500 lines, details in resources/"

### 6. PERFORMANCE_OPTIMIZATIONS
Performance improvements and profiling
- Example: "Batch cipher search queries to avoid N+1 problem"
- Example: "FTS5 search 10x faster than grep for large playbooks"

---

## Quality Scoring

### helpful_count & harmful_count

**Incremented by Curator based on Reflector feedback:**
- `helpful_count++` when pattern successfully applied
- `harmful_count++` when pattern caused issues or was incorrect

**Quality score formula:**
```
quality_score = helpful_count - harmful_count
```

**Usage:**
- Bullets with `quality_score >= 5` are high-quality → synced to cipher
- Bullets with `quality_score < 0` are deprecated → soft-deleted

---

## Search Capabilities

### 1. Tiered Search (mem0 MCP)

**Command:**
```bash
mcp__mem0__map_tiered_search(query="JWT authentication", limit=5)
```

**How it works:**
- Searches semantically similar patterns
- Searches across tiers (branch → project → org)
- Returns top matches ranked by relevance

**Use when:**
- You need relevant patterns quickly
- You want project-local patterns first, with org fallback

### 2. Semantic Search (mem0 MCP)

**Command:**
```bash
mcp__mem0__map_tiered_search(query="error handling patterns", limit=10)
```

**How it works:**
- Uses semantic search under the hood
- Returns conceptually similar patterns (not just keyword matches)

**Use when:**
- You want conceptual matches ("error handling" matches "exception management")
- Query doesn't match exact keywords

---

## Curator Operations

Curator updates playbook via delta operations:

### ADD Operation

```json
{
  "type": "ADD",
  "section": "IMPLEMENTATION_PATTERNS",
  "content": "Use context managers for resource cleanup",
  "code_example": "with open(file) as f: ...",
  "tags": ["python", "resources"],
  "initial_score": 1
}
```

**Result:** New bullet created with `helpful_count=1`, `harmful_count=0`

### UPDATE Operation

```json
{
  "type": "UPDATE",
  "bullet_id": "impl-0042",
  "increment_helpful": 1
}
```

**Result:** `helpful_count` incremented, `quality_score` recalculated, `updated_at` timestamp updated

### DEPRECATE Operation

```json
{
  "type": "DEPRECATE",
  "bullet_id": "impl-0099",
  "reason": "Pattern no longer applicable after refactor"
}
```

**Result:** Bullet marked as deprecated (soft delete), excluded from future searches

---

## Applying Changes (mem0 MCP)

As of v4.0, Curator applies changes directly via mem0 MCP tools (no `apply-delta` step).

**Process:**
1. Curator searches for duplicates via `mcp__mem0__map_tiered_search`
2. Curator stores new patterns via `mcp__mem0__map_add_pattern`
3. Curator archives outdated patterns via `mcp__mem0__map_archive_pattern`

---

## Promotion Across Scopes (mem0 MCP)

High-quality patterns can be promoted across tiers:
- branch → project
- project → org

Curator uses `mcp__mem0__map_promote_pattern` (or the workflow’s promotion rules) to broaden reuse.

---

## Playbook Lifecycle

### 1. Pattern Discovery (Reflector)

```
Subtask completed successfully
  ↓
Reflector analyzes: What worked? What patterns emerged?
  ↓
Calls map_tiered_search: Does this pattern already exist?
  ↓
Suggests new bullets or updates to existing ones
```

### 2. Pattern Validation (Curator)

```
Reflector insights
  ↓
Curator checks: Is this genuinely novel?
  ↓
Calls map_tiered_search again (double-check)
  ↓
Creates ADD/UPDATE operations
```

### 3. Pattern Application (Actor)

```
New subtask started
  ↓
Query mem0: `mcp__mem0__map_tiered_search(query="[subtask description]", limit=5)`
  ↓
Actor receives top 3-5 relevant bullets
  ↓
Applies patterns to implementation
  ↓
Tracks which bullets were helpful (used_bullets field)
```

### 4. Pattern Reinforcement (Curator)

```
Actor marks bullets as helpful
  ↓
Curator increments helpful_count
  ↓
If helpful_count reaches 5 → sync to cipher
  ↓
Pattern becomes cross-project knowledge
```

---

## Best Practices

### For Users

1. **Search before implementing** - Run `mcp__mem0__map_tiered_search` to find relevant patterns
2. **Prefer Curator for writes** - Use `Task(subagent_type="curator", ...)` to add/archive patterns
3. **Treat mem0 as source of truth** - Patterns are stored outside the repo via MCP
4. **Keep queries descriptive** - Include technology + intent for best relevance

### For Workflows

1. **Always search mem0** - Agents should retrieve patterns via `mcp__mem0__map_tiered_search`
2. **Track pattern usage** - Workflow should record which patterns were applied
3. **Batch operations** - Curator should batch mem0 writes when possible
4. **Promote proven patterns** - Use tier promotion rules to broaden reuse

---

## Troubleshooting

### Playbook too large (>1MB)

**Symptom:** Slow queries, high memory usage

**Solution:** 
- Use FTS5 search exclusively (`--mode local`)
- Archive old bullets: Export to JSON, delete from DB
- Split playbook by project phase

### Duplicate bullets

**Symptom:** Similar patterns with slight wording differences

**Solution:**
- Manually deprecate duplicates
- Improve Curator deduplication threshold
- Use semantic search to find similar bullets before adding

### No playbook context in prompts

**Symptom:** Agents don't receive playbook bullets

**Solution:**
- Verify `mapify` CLI is in PATH
- Check `.claude/playbook.db` exists
- Enable debug logging in workflows

---

**See also:**
- [Agent Architecture](agent-architecture.md) - How Reflector/Curator work
- [Cipher Integration](cipher-integration.md) - Cross-project knowledge sync
- [map-efficient Deep Dive](map-efficient-deep-dive.md) - Batched Curator updates
