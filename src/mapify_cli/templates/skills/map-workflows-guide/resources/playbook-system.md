# Playbook System

The playbook is MAP's project-specific knowledge base. It stores patterns, gotchas, and best practices learned during development.

## Structure

### Database Schema

**Location:** `.claude/playbook.db` (SQLite)

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

### 1. FTS5 Full-Text Search (Fast)

**Command:**
```bash
mapify playbook query "JWT authentication" --limit 5
```

**How it works:**
- Tokenizes query into terms
- Searches `content`, `code_example`, `tags` columns
- Ranks by BM25 relevance score
- Returns top N matches

**Speed:** ~10-50ms for playbooks up to 1MB

**Use when:**
- Exact keyword matching needed
- Speed is critical
- Playbook is large (>256KB)

### 2. Semantic Search (Comprehensive)

**Command:**
```bash
mapify playbook query "error handling patterns" --mode hybrid
```

**How it works:**
- Generates embedding for query (sentence-transformers)
- Computes cosine similarity against all bullet embeddings
- Ranks by semantic similarity
- Combines with FTS5 results (hybrid mode)

**Speed:** ~200-500ms (model load + embedding generation + similarity)

**Use when:**
- Conceptual matching needed ("error handling" matches "exception management")
- Query doesn't match exact keywords
- High-quality results more important than speed

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

## Applying Delta Operations

**Command:**
```bash
mapify playbook apply-delta curator_output.json
```

**Curator output format:**
```json
{
  "operations": [
    {"type": "ADD", "section": "...", "content": "...", ...},
    {"type": "UPDATE", "bullet_id": "...", "increment_helpful": 1}
  ],
  "sync_to_cipher": [
    {"bullet_id": "impl-0042", "content": "...", "helpful_count": 5}
  ]
}
```

**Process:**
1. Apply operations to `.claude/playbook.db`
2. Regenerate embeddings for new/updated bullets
3. If `sync_to_cipher` has entries → call `cipher_extract_and_operate_memory`

---

## Cipher Integration

### Sync Conditions

Bullets sync to cipher when:
- `helpful_count >= 5` (high-quality threshold)
- Content is sufficiently unique (not duplicating existing cipher knowledge)

### Deduplication

**Before ADD:**
1. Curator calls `cipher_memory_search` with new bullet content
2. If similar patterns exist (similarity > 0.85) → skip ADD or merge
3. Prevents duplicate knowledge in playbook

**Benefit:** Cleaner playbook, no redundant bullets

---

## Playbook Lifecycle

### 1. Pattern Discovery (Reflector)

```
Subtask completed successfully
  ↓
Reflector analyzes: What worked? What patterns emerged?
  ↓
Calls cipher_memory_search: Does this pattern already exist?
  ↓
Suggests new bullets or updates to existing ones
```

### 2. Pattern Validation (Curator)

```
Reflector insights
  ↓
Curator checks: Is this genuinely novel?
  ↓
Calls cipher_memory_search again (double-check)
  ↓
Creates ADD/UPDATE operations
```

### 3. Pattern Application (Actor)

```
New subtask started
  ↓
Query playbook: "mapify playbook query '[subtask description]'"
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

1. **Query before implementing** - Run `mapify playbook query` to find relevant patterns
2. **Review playbook growth** - Run `mapify playbook stats` periodically
3. **Curate manually** - Remove obsolete bullets: `mapify playbook deprecate <id>`
4. **Backup regularly** - `.claude/playbook.db` is your project knowledge

### For Workflows

1. **Always query playbook** - TaskDecomposer and Actor should always search playbook
2. **Track bullet usage** - Actor's `used_bullets` field enables quality scoring
3. **Batch operations** - Curator should batch multiple operations in single `apply-delta` call
4. **Validate before sync** - Only sync high-quality bullets (`helpful_count >= 5`) to cipher

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
