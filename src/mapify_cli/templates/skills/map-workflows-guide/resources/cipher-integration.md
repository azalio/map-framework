# Cipher Integration

Cipher is MAP's cross-project knowledge system. While playbook stores project-specific patterns, cipher stores universal knowledge shared across all your projects.

## What is Cipher?

**Cipher** = MCP (Model Context Protocol) server for semantic memory

**Key Features:**
- **Cross-project knowledge** - Learn once, apply everywhere
- **Semantic search** - Find patterns by meaning, not keywords
- **Automatic deduplication** - Prevents storing duplicate knowledge
- **Persistent storage** - Knowledge survives across sessions

---

## Dual Memory System

### Playbook vs Cipher

| Aspect | Playbook | Cipher |
|--------|----------|--------|
| **Scope** | Project-specific | Cross-project |
| **Storage** | `.claude/playbook.db` (SQLite) | MCP server (external) |
| **Search** | FTS5 + embeddings | Semantic embeddings |
| **Size** | Hundreds of bullets | Thousands of memories |
| **Updates** | Curator agent | MCP tool calls |
| **When to use** | Project patterns | Universal patterns |

### Example Split

**Playbook** (project-specific):
- "Use FastAPI with uvicorn for this API service"
- "JWT secret stored in .env file (JWT_SECRET)"
- "Database migrations via Alembic in migrations/ folder"

**Cipher** (universal):
- "Use async/await for I/O operations to avoid blocking"
- "Validate JWT tokens before processing requests"
- "Database schema changes require migration scripts"

---

## Sync Conditions

### When Bullets Sync to Cipher

Playbook bullets sync to cipher when **ALL** conditions met:

1. **Quality threshold:** `helpful_count >= 5`
2. **Curator decision:** Marked in `sync_to_cipher` array
3. **Uniqueness check:** Not already in cipher (similarity < 0.85)

### Curator Sync Process

```
Curator evaluates bullet quality
  ↓
If helpful_count >= 5:
  ↓
  Call cipher_memory_search(bullet_content)
  ↓
  If no similar memories (similarity < 0.85):
    ↓
    Add to sync_to_cipher array
  ↓
mapify playbook apply-delta reads sync_to_cipher
  ↓
For each entry:
  Call cipher_extract_and_operate_memory(content, metadata)
```

---

## MCP Tools Used

### 1. cipher_memory_search

**Purpose:** Find existing knowledge before adding duplicates

**Used by:**
- Reflector (before suggesting new bullets)
- Curator (before creating ADD operations)

**Example call:**
```python
mcp__cipher__cipher_memory_search(
  query="JWT token validation best practices",
  top_k=5,
  similarity_threshold=0.3
)
```

**Returns:**
```json
{
  "results": [
    {
      "id": "mem-12345",
      "text": "Always verify JWT signature before trusting claims",
      "score": 0.89,
      "metadata": {"projectId": "map-framework", "helpful_count": 8}
    }
  ]
}
```

### 2. cipher_extract_and_operate_memory

**Purpose:** Store new knowledge in cipher

**Used by:**
- `mapify playbook apply-delta` (after applying Curator operations)

**Example call:**
```python
mcp__cipher__cipher_extract_and_operate_memory(
  interaction="Use async/await for I/O operations",
  memoryMetadata={
    "projectId": "map-framework",
    "source": "curator",
    "helpful_count": 5,
    "tags": ["python", "async", "performance"]
  }
)
```

**Operation:** Extracts knowledge, creates embedding, stores in cipher database

---

## Deduplication Strategy

### Why Deduplication Matters

Without deduplication:
- Playbook grows indefinitely with redundant bullets
- Cipher accumulates duplicate memories
- Search results have redundant entries
- Knowledge management becomes chaotic

### How Deduplication Works

**Step 1: Reflector checks cipher**
```
Reflector: "I noticed we used async/await successfully"
  ↓
Call cipher_memory_search("async await I/O operations")
  ↓
Found similar memory: "Use async for I/O" (similarity: 0.91)
  ↓
Reflector: "Pattern already exists, skip new bullet"
```

**Step 2: Curator double-checks**
```
Curator receives Reflector insights
  ↓
Before ADD operation:
  Call cipher_memory_search(proposed_content)
  ↓
If similarity > 0.85 with existing memory:
  ↓
  Skip ADD or UPDATE existing bullet instead
```

**Step 3: Sync check**
```
Bullet reaches helpful_count = 5
  ↓
Curator considers syncing to cipher
  ↓
Call cipher_memory_search(bullet_content)
  ↓
If no close match (similarity < 0.85):
  ↓
  Add to sync_to_cipher array
```

### Similarity Thresholds

- **< 0.3** - Unrelated knowledge
- **0.3 - 0.7** - Related but distinct patterns
- **0.7 - 0.85** - Similar patterns (consider merging)
- **> 0.85** - Duplicate (skip ADD)

---

## Knowledge Flow

### Project → Cipher (Learning)

```
1. Subtask completed successfully
2. Reflector extracts pattern
3. Reflector searches cipher (check if exists)
4. Curator validates pattern
5. Curator searches cipher again (double-check)
6. Pattern added to playbook (helpful_count = 1)
7. Pattern applied successfully multiple times (helpful_count → 5)
8. Curator marks for cipher sync
9. mapify apply-delta calls cipher_extract_and_operate_memory
10. Pattern now in cipher for all projects
```

### Cipher → Project (Applying)

```
1. New subtask starts in different project
2. Actor searches playbook (finds local patterns)
3. Reflector searches cipher (finds cross-project patterns)
4. Combined context: local + universal knowledge
5. Implementation uses best of both
```

---

## Configuration

### Cipher MCP Server Setup

**Location:** `.mcp/settings.json` or similar (project-specific)

**Example config:**
```json
{
  "mcpServers": {
    "cipher": {
      "command": "node",
      "args": ["/path/to/cipher-mcp/dist/index.js"],
      "env": {
        "CIPHER_DB_PATH": "~/.cipher/memory.db"
      }
    }
  }
}
```

### Metadata Fields

When syncing to cipher, include:
```json
{
  "projectId": "map-framework",
  "source": "curator",
  "helpful_count": 5,
  "tags": ["python", "async"],
  "created_at": "2025-11-03T10:30:00"
}
```

---

## Benefits

### 1. Accelerated Learning

**Without cipher:**
- Project A learns: "Use async for I/O"
- Project B starts from scratch
- Same pattern learned twice

**With cipher:**
- Project A learns: "Use async for I/O" → synced to cipher
- Project B: Reflector finds pattern in cipher immediately
- Instant knowledge transfer

### 2. Consistency

All projects benefit from validated patterns:
- Security best practices
- Performance optimizations
- Architecture decisions

### 3. Quality Filtering

Only high-quality patterns sync (`helpful_count >= 5`):
- Experimental patterns stay local
- Proven patterns go global
- Noise filtered out

---

## Troubleshooting

### Cipher not receiving updates

**Check:**
1. MCP server running: `ps aux | grep cipher`
2. Correct path in config: `.mcp/settings.json`
3. Curator output has `sync_to_cipher` entries
4. `mapify playbook apply-delta` executed successfully

**Debug:**
```bash
# Check Curator output
cat curator_output.json | jq '.sync_to_cipher'

# Verify MCP connection
# (Test cipher_memory_search manually)
```

### Duplicate memories in cipher

**Cause:** Deduplication threshold too low

**Solution:**
- Increase similarity threshold to 0.9
- Manually clean cipher database
- Improve pattern wording to be more distinct

### Playbook bullets not syncing

**Check:**
1. `helpful_count >= 5` for bullet
2. Curator marked bullet in `sync_to_cipher`
3. `mapify playbook apply-delta` called after Curator

**Fix:**
- Manually increment helpful_count: `mapify playbook update <id> --increment-helpful`
- Re-run Curator workflow

---

## Best Practices

### For Workflows

1. **Always search cipher first** - Reflector should check cipher before suggesting new bullets
2. **Sync selectively** - Only high-quality patterns (`helpful_count >= 5`)
3. **Include rich metadata** - Tags, project context, helpful_count help future searches
4. **Validate before sync** - Double-check similarity to avoid duplicates

### For Users

1. **Review cipher periodically** - Understand what universal patterns exist
2. **Trust quality scoring** - Patterns with `helpful_count >= 5` are battle-tested
3. **Don't bypass deduplication** - Let Reflector/Curator check cipher first
4. **Query cipher for new projects** - Start with universal knowledge, add project-specific

---

**See also:**
- [Playbook System](playbook-system.md) - How project knowledge is structured
- [Agent Architecture](agent-architecture.md) - Reflector/Curator roles
- [map-efficient Deep Dive](map-efficient-deep-dive.md) - Batched learning workflow
