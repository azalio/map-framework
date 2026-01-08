# MAP Framework Usage Guide

Complete usage examples, best practices, and optimization strategies for the MAP Framework.

## Navigation

- [Usage Examples](#usage-examples)
  - [Feature Development](#feature-development)
  - [Bug Fixing](#bug-fixing)
  - [Refactoring](#refactoring)
  - [Library Integration](#library-integration)
  - [Learning from Open Source](#learning-from-open-source)
- [Self-MoA: Solution Synthesis](#self-moa-solution-synthesis)
  - [How Self-MoA Works](#how-self-moa-works)
  - [When to Use Self-MoA](#when-to-use-self-moa)
  - [Example Synthesis](#example-synthesis)
  - [Token Cost Considerations](#token-cost-considerations)
- [Playbook Commands](#playbook-commands)
- [Common CLI Mistakes](#-common-cli-mistakes)
  - [Wrong Command Names](#wrong-command-names)
  - [Wrong Parameter Names](#wrong-parameter-names)
  - [Wrong Approach](#wrong-approach-critical)
  - [Wrong Operation Field Name](#wrong-operation-field-name)
  - [Quick Reference Resources](#quick-reference-resources)
  - [Validation Tools](#validation-tools)
- [FTS5 Query Format Guidelines](#fts5-query-format-guidelines)
- [Dependency Validation](#dependency-validation)
  - [Basic Usage](#basic-usage)
  - [Visualization Mode](#visualization-mode)
  - [Exit Codes](#exit-codes)
  - [Integration with TaskDecomposer](#integration-with-taskdecomposer)
  - [Sample TaskDecomposer JSON](#sample-taskdecomposer-json)
  - [Validation Output Examples](#validation-output-examples)
  - [Command-Line Flags Reference](#command-line-flags-reference)
  - [Validation Best Practices](#validation-best-practices)
- [Best Practices](#best-practices)
  - [Clear Requirements](#1-clear-requirements)
  - [Incremental Approach](#2-incremental-approach)
  - [Provide Context](#3-provide-context)
- [Cost Optimization](#cost-optimization)
  - [Model Distribution Strategy](#model-distribution-strategy)
  - [Cost Savings](#cost-savings)
  - [How It Works](#how-it-works)
  - [Cost Comparison Example](#cost-comparison-example)
- [Hooks System](#-hooks-system)
  - [Prompt Clarification](#prompt-clarification-prompt-improver-hook)
  - [Sequential Hook Processing](#sequential-hook-processing)
  - [Disabling Prompt-Improver](#disabling-prompt-improver)
  - [Other Active Hooks](#other-active-hooks)
- [Additional Resources](#additional-resources)

---

## 📚 Usage Examples

### Feature Development

```bash
/map-feature implement user profile page with avatar upload.
Include validation, error handling, and tests.
```

### Bug Fixing

```bash
/map-debug debug why payment processing fails for amounts over $1000
```

### Refactoring

```bash
/map-refactor refactor OrderService to use dependency injection.
Maintain all existing functionality.
```

### Library Integration

```bash
/map-feature integrate Stripe payment processing.
Use context7 to get latest Stripe docs.
```

### Learning from Open Source

```bash
/map-feature implement rate limiter.
Study express-rate-limit via deepwiki, then create optimized version.
```

---

## 🧬 Self-MoA: Solution Synthesis

**Self-MoA** (Self-Mixture of Agents) is an advanced pattern that generates 3 implementation variants and **synthesizes** the best parts into an optimal combined solution.

### How Self-MoA Works

1. **Actor×3** generates variants with different optimization focuses:
   - **V1 (Security)**: Input validation, OWASP compliance, defensive coding
   - **V2 (Performance)**: Algorithm efficiency, caching, async patterns
   - **V3 (Simplicity)**: Readability, standard patterns, clear structure

2. **Monitor×3** validates each variant and extracts:
   - Key design decisions (3-8 per variant)
   - Compatibility features (error handling, concurrency model, etc.)
   - Strengths and weaknesses

3. **Synthesizer** combines the best parts:
   - Extracts all decisions from viable variants
   - Resolves conflicts using priority precedence
   - Generates **fresh unified code** (not copy-paste)

4. **Final Monitor** validates the synthesized solution

### Activation

**Explicit activation:**
```bash
/map-efficient --self-moa implement JWT authentication with refresh tokens
```

**Automatic activation:** When TaskDecomposer marks a subtask as:
- `complexity: high`
- `security_critical: true`

### When to Use Self-MoA

**Use Self-MoA for:**
- Security-critical implementations (auth, data validation, encryption)
- Complex algorithms with multiple valid approaches
- Tasks requiring balance of security, performance, and maintainability
- High-risk features where quality justifies higher token cost

**Skip Self-MoA for:**
- Simple CRUD operations
- Configuration changes
- Documentation updates
- Token-constrained workflows

### Example Synthesis

```
Input Variants:
  V1 (security): Strong input validation, comprehensive error handling
  V2 (performance): Efficient O(n) algorithm, smart caching
  V3 (simplicity): Clean structure, readable code

Synthesis Result:
  - Structure: from V3 (clearest separation of concerns)
  - Validation: from V1 (OWASP-compliant input checks)
  - Algorithm: from V2 (O(n) instead of O(n²))

Output: Clean, secure, AND fast (better than any single variant)
```

### Token Cost Considerations

Self-MoA uses ~4x tokens per subtask:
- 3 Actor calls (parallel)
- 3 Monitor calls (parallel)
- 1 Synthesizer call
- 1 Final Monitor call

**Recommendation:** Use Self-MoA selectively for critical subtasks, not for every task. The `/map-efficient` workflow automatically determines eligibility based on subtask complexity and security flags.

---

## 🛠️ Playbook Commands

The playbook manager CLI provides tools to analyze and manage learned patterns:

### Querying Playbook (NEW - FTS5 Full-Text Search)

**Recommended:** Use `mapify playbook query` instead of `mapify playbook search` for better performance with large playbooks.

```bash
# Basic query (local playbook only)
mapify playbook query "JWT authentication" --limit 5

# With cipher integration (broader knowledge)
mapify playbook query "error handling patterns" --mode hybrid --limit 10

# Filter by sections
mapify playbook query "API design" --section ARCHITECTURE_PATTERNS --section IMPLEMENTATION_PATTERNS

# Minimum quality filter
mapify playbook query "security patterns" --min-quality 3

# JSON output (for scripts)
mapify playbook query "testing strategies" --format json
```

**Query modes:**
- `--mode local` (default) - Search local playbook only (fast, <50ms)
- `--mode hybrid` - Intended for future standalone mode (in workflows, gracefully degrades to local-only search)
- `--mode cipher` - Reserved for future cipher backend

**IMPORTANT for MAP Workflows:**

⚠️ The `--mode hybrid` flag **does not work** in MAP workflows because:
- `mapify playbook query` runs as separate bash process
- Separate processes cannot invoke Claude MCP tools
- Cipher search returns empty list (graceful degradation)

**Correct approach for MAP workflows:**
1. Use `mapify playbook query` (local playbook via Bash)
2. Separately call `mcp__cipher__cipher_memory_search` (cross-project via MCP tool)
3. Agent combines both sources

See [PLAYBOOK-CIPHER-INTEGRATION.md](PLAYBOOK-CIPHER-INTEGRATION.md) for details.

**Why use `query` instead of `search`:**
- ✅ **Works with large playbooks** - Handles >256KB (current playbook: 270KB)
- ✅ **FTS5 full-text search** - 10x faster than grep
- ✅ **Relevance ranking** - Best patterns first
- ✅ **Quality scoring** - Prioritizes proven patterns (helpful_count - harmful_count)

### Apply Delta Operations (MAP Workflow Integration)

**Purpose:** Apply Curator agent output to update the playbook database.

```bash
# Apply operations from file
mapify playbook apply-delta curator_output.json

# Preview changes without applying (dry-run)
mapify playbook apply-delta operations.json --dry-run

# Pipe from Curator agent (recommended in MAP workflows)
cat curator_output.json | mapify playbook apply-delta
echo '{"operations": [{"type": "UPDATE", "bullet_id": "impl-0001", "increment_helpful": 1}]}' | mapify playbook apply-delta
```

**Operation Types:**

1. **ADD** - Add new bullet to playbook
   ```json
   {
     "type": "ADD",
     "section": "IMPLEMENTATION_PATTERNS",
     "content": "Use async/await for I/O operations",
     "code_example": "async def fetch(): ...",
     "tags": ["python", "async"]
   }
   ```

2. **UPDATE** - Increment helpful/harmful counters
   ```json
   {
     "type": "UPDATE",
     "bullet_id": "impl-0042",
     "increment_helpful": 1
   }
   ```

3. **DEPRECATE** - Mark bullet as deprecated
   ```json
   {
     "type": "DEPRECATE",
     "bullet_id": "impl-0099",
     "reason": "Superseded by impl-0105"
   }
   ```

**Input Format:**

```json
{
  "operations": [
    {"type": "ADD", "section": "...", "content": "..."},
    {"type": "UPDATE", "bullet_id": "...", "increment_helpful": 1},
    {"type": "DEPRECATE", "bullet_id": "...", "reason": "..."}
  ]
}
```

**When to Use:**

- ✅ **After Curator agent** in MAP workflows (/map-feature, /map-debug, etc.)
- ✅ **Batch updates** from CI/CD pipelines
- ✅ **Automated playbook maintenance**

**Exit Codes:**
- `0` - Success (operations applied or dry-run completed)
- `1` - Validation error or application failure

### Statistics

```bash
# Statistics
mapify playbook stats

# High-quality patterns ready for sync
mapify playbook sync
```

### Legacy Search (deprecated for large playbooks)

```bash
# Search patterns (works for small playbooks <256KB)
mapify playbook search "JWT authentication"
```

**Note:** `search` command uses simple keyword matching and may fail on large playbooks. Use `query` instead.

---

## ⚠️ Common CLI Mistakes

This section documents frequently encountered CLI command errors and their corrections. These validations are enforced by:
- Pre-commit hooks (`.git/hooks/pre-commit`)
- E2E tests (`tests/test_agent_cli_correctness.py`)
- Agent template CLI reference sections

### Wrong Command Names

| ❌ Incorrect | ✅ Correct | Explanation |
|-------------|-----------|-------------|
| `mapify playbook list --sections` | `mapify playbook stats` | Command `list` doesn't exist. Use `stats` to see section overview. |
| `mapify playbook get docu-0005` | `mapify playbook query "docu-0005"` | Command `get` doesn't exist. Use `query` with bullet ID as search text. |

### Wrong Parameter Names

| ❌ Incorrect | ✅ Correct | Explanation |
|-------------|-----------|-------------|
| `mapify playbook search --limit 3` | `mapify playbook search "query" --top-k 3` | `search` command uses `--top-k`, not `--limit` (different from `query` command). |
| `mapify playbook query --bullet-id test-0016` | `mapify playbook query "test-0016"` | Option `--bullet-id` doesn't exist. Use bullet ID as query text argument. |

### Wrong Approach (CRITICAL)

| ❌ NEVER DO THIS | ✅ ALWAYS USE THIS | Why |
|------------------|-------------------|-----|
| `sqlite3 .claude/playbook.db "UPDATE bullets SET..."` | `mapify playbook apply-delta ops.json` | Direct database access breaks integrity, bypasses validation, and corrupts FTS5 indexes. |
| `Edit(.claude/playbook.db, ...)` | `mapify playbook apply-delta ops.json` | Cannot edit binary SQLite database. Generate delta operations JSON and apply via CLI. |

### Wrong Operation Field Name

| ❌ Incorrect JSON | ✅ Correct JSON |
|------------------|----------------|
| `{"op": "ADD", "section": "...", "content": "..."}` | `{"type": "ADD", "section": "...", "content": "..."}` |
| `{"op": "UPDATE", "bullet_id": "..."}` | `{"type": "UPDATE", "bullet_id": "..."}` |
| `{"op": "DEPRECATE", "bullet_id": "..."}` | `{"type": "DEPRECATE", "bullet_id": "..."}` |

**Explanation:** Delta operations use the field name `"type"`, not `"op"`. This is validated by `mapify playbook apply-delta` and enforced in agent templates.

### Quick Reference Resources

For comprehensive CLI documentation, see:

- **Quick reference skill**: `.claude/skills/map-cli-reference/SKILL.md`
  - Auto-suggests when CLI errors occur
  - Provides immediate corrections
  - ~250 lines, follows 500-line skill rule

- **Complete CLI guide**: `docs/CLI_COMMAND_REFERENCE.md`
  - Full command reference with examples
  - FTS5 query syntax guide
  - Exit codes and troubleshooting

- **Machine-readable spec**: `docs/CLI_REFERENCE.json`
  - JSON schema for all commands
  - Parameter types and validation rules
  - Error pattern definitions

### Validation Tools

**Pre-commit hook** (`.git/hooks/pre-commit`):
- Blocks commits with incorrect CLI commands in agent templates
- Validates template variables aren't removed
- Runs automatically on `git commit`

**E2E test** (`tests/test_agent_cli_correctness.py`):
- 6 test cases covering common mistakes
- Runs in CI on every PR
- Validates agent templates use correct CLI syntax

**Skip validation** (if absolutely necessary):
```bash
git commit --no-verify  # NOT RECOMMENDED
```

---

## 🧠 Knowledge Graph Features

> **Added in v3.0** — Semantic knowledge extraction and querying for enhanced pattern discovery.

The Knowledge Graph (KG) layer automatically extracts entities (tools, patterns, concepts) and relationships (uses, depends-on, contradicts) from your playbook, enabling advanced queries and contradiction detection.

### What is the Knowledge Graph?

Instead of treating playbook bullets as plain text, the KG:
- **Extracts entities**: Identifies tools (pytest, Docker), patterns (retry-with-backoff), concepts (idempotency), etc.
- **Detects relationships**: Discovers "pytest USES Python", "race-condition CAUSES data-corruption", etc.
- **Tracks provenance**: Links each entity back to the bullet it came from
- **Finds contradictions**: Alerts you when new patterns conflict with existing knowledge

**Extraction happens automatically** during MAP workflows (Reflector/Curator agents), so you don't need to manually populate the graph.

### Entity Types (7)

| Type | Description | Examples |
|------|-------------|----------|
| TOOL | CLI tools, libraries, frameworks | pytest, Docker, SQLite, npm |
| PATTERN | Implementation patterns | retry-with-backoff, feature-flags, circuit-breaker |
| CONCEPT | Abstract ideas | idempotency, eventual-consistency, ACID |
| ERROR_TYPE | Error categories | race-condition, null-pointer, deadlock |
| TECHNOLOGY | Tech stack components | Python, Kubernetes, PostgreSQL, React |
| WORKFLOW | Process patterns | TDD, CI/CD, MAP-workflow |
| ANTIPATTERN | Known bad practices | generic-exception, magic-number, god-object |

### Relationship Types (9)

| Type | Meaning | Example |
|------|---------|---------|
| USES | X uses Y as dependency | pytest USES Python |
| DEPENDS_ON | X requires Y to function | retry-pattern DEPENDS_ON exponential-backoff |
| CONTRADICTS | X conflicts with Y | generic-exception CONTRADICTS specific-exceptions |
| SUPERSEDES | X replaces Y | SQLite SUPERSEDES JSON format |
| IMPLEMENTS | X implements pattern Y | retry-logic IMPLEMENTS resilience-pattern |
| CAUSES | X causes problem Y | race-condition CAUSES data-corruption |
| PREVENTS | X prevents problem Y | mutex-lock PREVENTS race-condition |
| ALTERNATIVE_TO | X is alternative to Y | pytest ALTERNATIVE_TO unittest |
| RELATED_TO | X and Y are semantically related | Testing RELATED_TO quality-assurance |

### Querying the Knowledge Graph (Python API)

```python
from mapify_cli.playbook_manager import PlaybookManager
from mapify_cli.entity_extractor import EntityType
from mapify_cli.relationship_detector import RelationshipType

# Initialize (auto-migrates to KG schema v3.0 if needed)
pm = PlaybookManager(db_path=".claude/playbook.db")
kg = pm.kg_query

# Example 1: Find all tools with high confidence
tools = kg.query_entities(entity_type=EntityType.TOOL, min_confidence=0.8)
print(f"High-confidence tools: {[t.name for t in tools]}")
# Output: ['pytest', 'Docker', 'SQLite', 'npm']

# Example 2: Find what pytest uses/depends on
neighbors = kg.get_neighbors('ent-pytest', direction='outgoing')
for entity, relationship in neighbors:
    print(f"pytest {relationship.type.value} {entity.name}")
# Output:
# pytest USES Python
# pytest DEPENDS_ON unittest

# Example 3: Find path between two entities
paths = kg.find_paths('ent-pytest', 'ent-python', max_depth=3)
if paths:
    path = paths[0]  # Shortest path
    print(f"Path: {' -> '.join(path.entities())} (length: {path.length})")
# Output: Path: ent-pytest -> ent-python (length: 1)

# Example 4: Find entities created in last 24 hours
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
recent = kg.entities_since(cutoff, min_confidence=0.7)
print(f"New entities (last 24h): {len(recent)}")

# Example 5: Find all dependencies in your playbook
deps = kg.query_relationships(relationship_type=RelationshipType.DEPENDS_ON)
for dep in deps:
    source = kg.query_entities()[0]  # Get entity details
    target = kg.query_entities()[0]
    print(f"{source.name} depends on {target.name}")
```

### Contradiction Detection

The KG automatically detects conflicting patterns and suggests resolutions.

#### Example: Detecting Contradictions

```python
from mapify_cli.contradiction_detector import ContradictionDetector

detector = ContradictionDetector()

# Find all contradictions in playbook
contradictions = detector.detect_contradictions(pm.db_conn, min_confidence=0.7)

for contra in contradictions:
    print(f"[{contra.severity.upper()}] {contra.entity_a.name} vs {contra.entity_b.name}")
    print(f"  Description: {contra.description}")
    print(f"  Resolution: {contra.resolution_suggestion}\n")
```

**Example Output:**
```
[HIGH] generic-exception vs specific-exceptions
  Description: Entity 'generic-exception' contradicts 'specific-exceptions'
  Resolution: Consider deprecating older entity 'generic-exception' in favor of newer higher-confidence entity 'specific-exceptions'

[MEDIUM] magic-numbers vs named-constants
  Description: Entity 'magic-numbers' contradicts 'named-constants'
  Resolution: Manual review recommended - similar confidence and timestamps
```

#### Severity Levels

| Severity | Criteria | Action |
|----------|----------|--------|
| **High** | Relationship confidence ≥0.8 AND both entities >0.8 | Immediate review required |
| **Medium** | Relationship 0.7-0.8 OR one entity 0.6-0.8 | Review when convenient |
| **Low** | Relationship <0.7 OR both entities <0.6 | Low priority |

#### Checking New Patterns for Conflicts (Curator Integration)

When adding new bullets to the playbook, the Curator agent automatically checks for contradictions:

```python
from mapify_cli.entity_extractor import extract_entities

# New pattern being added
new_pattern = "Always use generic exception handling for simplicity"
entities = extract_entities(new_pattern)

# Check for conflicts with existing knowledge
conflicts = detector.check_new_pattern_conflicts(pm.db_conn, new_pattern, entities)

if conflicts:
    print(f"⚠️  Warning: {len(conflicts)} conflicts found!")
    for conflict in conflicts:
        print(f"  - {conflict.description}")
        print(f"    Resolution: {conflict.resolution_suggestion}")
    # Curator will REJECT or REQUEST_REVIEW based on severity
else:
    print("✅ No conflicts - safe to add to playbook")
```

### Temporal Queries (Find Recent Knowledge)

```python
from datetime import datetime, timedelta, timezone

# Entities from last week
week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
recent_entities = kg.entities_since(week_ago, min_confidence=0.7)

print(f"Entities added in last week: {len(recent_entities)}")
for entity in recent_entities:
    print(f"  - {entity.name} ({entity.type.value})")
    print(f"    Confidence: {entity.confidence:.2f}")
    print(f"    First seen: {entity.first_seen_at}")
```

### Provenance Tracking (Find Source Bullets)

Every entity/relationship links back to the bullet it was extracted from:

```python
# Find which bullets mention 'pytest'
provenance = kg.get_entity_provenance('ent-pytest')

for record in provenance:
    print(f"Bullet: {record['bullet_id']}")
    print(f"  Extraction method: {record['extraction_method']}")
    print(f"  Confidence: {record['confidence']:.2f}")
    print(f"  Extracted at: {record['extracted_at']}")
```

### SQL Queries (Advanced)

For advanced users, you can query the KG directly via SQL:

```python
import sqlite3

conn = pm.db_conn

# Find all TOOL entities
tools = conn.execute("""
    SELECT name, confidence FROM entities
    WHERE type = 'TOOL' AND confidence > 0.8
    ORDER BY confidence DESC
""").fetchall()

# Find all USES relationships with details
uses_rels = conn.execute("""
    SELECT
        e1.name AS source,
        r.type,
        e2.name AS target,
        r.confidence
    FROM relationships r
    JOIN entities e1 ON r.source_entity_id = e1.id
    JOIN entities e2 ON r.target_entity_id = e2.id
    WHERE r.type = 'USES'
    ORDER BY r.confidence DESC
""").fetchall()

# Full-text search on entity names
search_results = conn.execute("""
    SELECT name, type, confidence
    FROM entities_fts
    WHERE entities_fts MATCH 'pytest OR testing'
    ORDER BY rank
    LIMIT 10
""").fetchall()
```

### Best Practices

#### When to Use Knowledge Graph Queries

✅ **Use KG when:**
- Finding relationships between tools/patterns ("What does X depend on?")
- Checking for contradictions before adding new patterns
- Analyzing technology stack evolution over time (temporal queries)
- Discovering implicit knowledge connections (path finding)
- Auditing antipatterns and their alternatives

❌ **Don't use KG when:**
- Searching for specific code examples (use playbook FTS5 search instead)
- Looking for human-readable best practices (use `mapify playbook query`)
- You need exact text matches (KG extracts semantic entities, not full text)

#### Confidence Thresholds

**Recommended `min_confidence` values:**

| Use Case | Recommended | Reasoning |
|----------|-------------|-----------|
| Production decisions | 0.8 | High confidence only (explicit mentions) |
| General queries | 0.7 | Balance of quality and coverage |
| Exploration | 0.5 | Include inferred relationships |
| Research/debugging | 0.0 | See all extractions (noisy) |

#### Performance Tips

- **Use type filters**: `query_entities(entity_type=EntityType.TOOL)` faster than scanning all entities
- **Limit path depth**: `find_paths(max_depth=3)` prevents expensive traversals
- **Filter by confidence**: `min_confidence=0.7` reduces result sets significantly
- **Use FTS5 for text search**: Full-text search on `entities_fts` is optimized
- **Batch queries**: Collect entity IDs first, then query details (reduces round trips)

### Migration from v2.1 to v3.0

**Migration is automatic** when you upgrade to MAP Framework v1.3.0+:
- Runs when `PlaybookManager` initializes
- Adds 4 new tables: `entities`, `relationships`, `provenance`, `entities_fts`
- **Zero data loss** (only adds tables, never modifies existing bullets)
- Takes <1 second (idempotent, safe to run multiple times)

**After migration:**
- Existing bullets remain unchanged (v2.1 schema)
- KG tables start empty (entities extracted incrementally via MAP workflows)
- All v2.1 queries continue to work

**See:** [Migration Guide](./knowledge_graph/MIGRATION_V2.1_TO_V3.0.md) for details.

### Opt-Out (If Needed)

Knowledge Graph extraction is opt-in (happens during MAP workflows, not on existing data). To disable KG features:

```python
# Disable KG extraction (not recommended - loses semantic benefits)
pm.db_conn.execute("UPDATE metadata SET value='0' WHERE key='kg_enabled'")
pm.db_conn.commit()
```

**Why you might disable:**
- Performance concerns on very large playbooks (>50K entities)
- You only need text-based search (FTS5), not semantic queries
- Debugging KG extraction issues

**Why you should keep it enabled:**
- Automatic contradiction detection prevents conflicting patterns
- Semantic queries discover implicit knowledge connections
- Temporal queries show knowledge evolution over time
- Minimal overhead (<100ms per extraction)

### Documentation

- **API Reference**: [`docs/knowledge_graph/API_REFERENCE.md`](./knowledge_graph/API_REFERENCE.md)
- **Schema ERD**: [`docs/knowledge_graph/ERD_v3.0.md`](./knowledge_graph/ERD_v3.0.md)
- **Architecture**: [ARCHITECTURE.md#knowledge-graph-layer](./ARCHITECTURE.md#knowledge-graph-layer)
- **Migration Guide**: [`docs/knowledge_graph/MIGRATION_V2.1_TO_V3.0.md`](./knowledge_graph/MIGRATION_V2.1_TO_V3.0.md)

---

## 🔍 FTS5 Query Format Guidelines

The `mapify playbook query` command uses SQLite's FTS5 (Full-Text Search version 5) for fast, accurate pattern matching. Understanding how FTS5 tokenizes and matches queries helps you write effective searches.

### How FTS5 Tokenization Works

**Key Concept:** FTS5 splits text into tokens (words) using the **porter unicode61** tokenizer. This tokenizer:
- Splits on whitespace, punctuation, and special characters
- **Applies Porter stemming** (e.g., "authentication" → "authent", matches "authenticate", "authenticated")
- **Splits hyphenated terms** into separate tokens (e.g., "auto-activation" → ["auto", "activation"])
- Normalizes Unicode characters (e.g., "café" → "cafe")
- Removes control characters

**Example Tokenization:**

| Original Text | Tokens Created |
|--------------|----------------|
| `auto-activation` | `["auto", "activation"]` |
| `session-start hook` | `["session", "start", "hook"]` |
| `multi-subtask workflow` | `["multi", "subtask", "workflow"]` |
| `FTS5 query builder` | `["FTS5", "query", "builder"]` |

### Query Format Best Practices

#### 1. Hyphenated Terms

**✨ Automatic Conversion (v2.1+):** The system automatically replaces hyphens with spaces in your queries, so both `"session-start"` and `"session start"` work identically. Understanding this behavior helps explain why hyphenated searches work seamlessly.

**Background:** FTS5 tokenizer splits hyphens at index time (e.g., "auto-activation" → ["auto", "activation"]), so queries are automatically converted to match.

```bash
# Both formats work (automatic conversion)
mapify playbook query "auto-activation"  # ✅ Auto-converted to "auto activation"
mapify playbook query "auto activation"  # ✅ Direct space-separated query

# Also matches variations:
# - "auto activation feature"
# - "automatic activation"
# - "auto-activation" (stored in content, tokenized as "auto" + "activation")
```

**More Examples:**

```bash
# Hyphenated terms
mapify playbook query "session start"        # ✅ finds "session-start hook"
mapify playbook query "multi subtask"        # ✅ finds "multi-subtask workflow"
mapify playbook query "context compaction"   # ✅ finds "context-compaction resilience"

# Technical terms
mapify playbook query "error handling"       # ✅ finds "error-handling patterns"
mapify playbook query "rate limiting"        # ✅ finds "rate-limiting algorithm"
```

#### 2. Phrase Matching

**Use quotes for exact phrases:**

```bash
# Match exact phrase (all words in order)
mapify playbook query '"JWT authentication"'

# Match phrase with spaces instead of hyphens
mapify playbook query '"session start hook"'  # Matches "session-start hook"
```

**Without quotes (matches any order):**

```bash
# Matches bullets containing both "JWT" and "authentication" (any order)
mapify playbook query "JWT authentication"

# Matches "authentication with JWT", "JWT-based authentication", etc.
```

#### 3. Boolean Operators

**AND (implicit by default):**

```bash
# Matches bullets containing both "error" AND "handling"
mapify playbook query "error handling"

# Explicit AND (same result)
mapify playbook query "error AND handling"
```

**OR (for alternatives):**

```bash
# Matches bullets containing "JWT" OR "OAuth"
mapify playbook query "JWT OR OAuth"

# Multiple alternatives
mapify playbook query "authentication OR authorization OR security"
```

**NOT (exclude terms):**

```bash
# Matches "authentication" but excludes results containing "OAuth"
mapify playbook query "authentication NOT OAuth"

# Exclude multiple terms
mapify playbook query "database NOT (PostgreSQL OR MySQL)"
```

#### 4. Prefix Matching

**Use `*` for wildcard suffix:**

```bash
# Matches "auth", "authentication", "authorize", "authorized"
mapify playbook query "auth*"

# Matches "test", "testing", "tester"
mapify playbook query "test*"

# Combined with other terms
mapify playbook query "auto* activation"  # Matches "auto", "automatic", "automated"
```

**Note:** FTS5 does NOT support infix or suffix wildcards (e.g., `*auth` or `te*st`).

#### 5. Complex Queries

**Combine operators for precise searches:**

```bash
# Authentication patterns excluding OAuth
mapify playbook query '(JWT OR session) AND authentication NOT OAuth'

# Error handling for specific languages
mapify playbook query 'error handling AND (Python OR Go)'

# Find caching patterns but not Redis-specific
mapify playbook query 'caching AND performance NOT Redis'
```

### Common Pitfalls and Solutions

#### Pitfall 1: Special Characters in Queries

**Problem:** FTS5 treats special characters as token separators.

```bash
# ❌ BAD: Hyphen splits query
mapify playbook query "session-start"

# ✅ GOOD: Replace with space
mapify playbook query "session start"
```

**Affected characters:** `-`, `.`, `,`, `/`, `@`, `#`, etc.

#### Pitfall 2: Case Sensitivity

**FTS5 is case-insensitive by default:**

```bash
# All equivalent (case doesn't matter)
mapify playbook query "JWT"
mapify playbook query "jwt"
mapify playbook query "Jwt"
```

#### Pitfall 3: Stop Words

**FTS5 does NOT remove stop words by default** (unlike some search engines).

```bash
# These words ARE indexed and searchable:
mapify playbook query "the authentication flow"  # "the" is included
mapify playbook query "a guide to testing"        # "a" and "to" are included
```

**Why this matters:** More precise matching, but longer queries may be less flexible.

#### Pitfall 4: Order Matters (without quotes)

**Without quotes, order doesn't matter:**

```bash
# These are equivalent:
mapify playbook query "JWT authentication"
mapify playbook query "authentication JWT"
```

**With quotes, order matters:**

```bash
# ✅ Matches: "JWT authentication flow"
mapify playbook query '"JWT authentication"'

# ❌ Does NOT match: "JWT authentication flow"
mapify playbook query '"authentication JWT"'
```

### Troubleshooting FTS5 Query Errors

#### Error: "fts5: syntax error near '-'"

**Cause:** Query contains hyphen, which FTS5 interprets as boolean NOT operator.

**Solution:** ✨ **As of v2.1, hyphens are automatically replaced with spaces to prevent this error.** If you still encounter this error, it may be from other special characters like unbalanced quotes or parentheses.

```bash
# Modern behavior (v2.1+) - both work
mapify playbook query "auto-activation"  # ✅ Auto-converted
mapify playbook query "auto activation"  # ✅ Also works

# If you still get this error, check for:
mapify playbook query "auto-(activation"  # ❌ Unbalanced parenthesis
mapify playbook query "auto \"activation"  # ❌ Unbalanced quote
```

**Root Cause:** FTS5 tokenizer splits "auto-activation" → ["auto", "activation"] at index time. The automatic hyphen replacement (v2.1+) prevents syntax errors for hyphenated terms.

#### Error: "no such column"

**Cause:** Query references column that doesn't exist in FTS5 index.

**Solution:** Use standard FTS5 query syntax (no column filters).

```bash
# ❌ ERROR: no such column: title
mapify playbook query "title:authentication"

# ✅ FIXED: Search all indexed columns
mapify playbook query "authentication"
```

**Note:** `mapify playbook query` searches all indexed columns (`content`, `code_example`, `tags`) automatically.

#### Error: "fts5: syntax error near '('"

**Cause:** Unmatched parentheses in boolean query.

**Solution:** Balance parentheses or remove them.

```bash
# ❌ ERROR: fts5: syntax error near '('
mapify playbook query "(JWT OR OAuth"

# ✅ FIXED: Balanced parentheses
mapify playbook query "(JWT OR OAuth)"

# ✅ ALTERNATIVE: Remove parentheses
mapify playbook query "JWT OR OAuth"
```

#### No Results Found (but pattern exists)

**Possible Causes:**

1. **Hyphen in query:**
   ```bash
   # ❌ No results
   mapify playbook query "session-start"

   # ✅ Fixed
   mapify playbook query "session start"
   ```

2. **Typo or misspelling:**
   ```bash
   # ❌ No results (typo: "authetication")
   mapify playbook query "authetication"

   # ✅ Fixed
   mapify playbook query "authentication"
   ```

3. **Too specific query:**
   ```bash
   # ❌ No results (too many required terms)
   mapify playbook query "JWT authentication with refresh tokens and Redis caching"

   # ✅ Broader query
   mapify playbook query "JWT refresh tokens"
   ```

4. **Pattern not in playbook:**
   ```bash
   # Verify pattern exists
   mapify playbook stats  # Check total bullets

   # Search with broader term
   mapify playbook query "authentication"  # Find related patterns
   ```

### Query Examples by Use Case

#### Finding Authentication Patterns

```bash
# Broad search
mapify playbook query "authentication"

# Specific technology
mapify playbook query "JWT authentication"
mapify playbook query "OAuth flow"
mapify playbook query "session management"

# With error handling
mapify playbook query "authentication error handling"
```

#### Finding Performance Optimizations

```bash
# General optimization
mapify playbook query "performance optimization"

# Specific techniques
mapify playbook query "caching strategy"
mapify playbook query "database query optimization"
mapify playbook query "async concurrency"

# Language-specific
mapify playbook query "Python async performance"
```

#### Finding Error Handling Patterns

```bash
# General error handling
mapify playbook query "error handling"

# Specific contexts
mapify playbook query "API error handling"
mapify playbook query "retry logic"
mapify playbook query "exponential backoff"

# Language-specific
mapify playbook query "Python exception handling"
mapify playbook query "Go error handling"
```

#### Finding Testing Patterns

```bash
# General testing
mapify playbook query "testing patterns"

# Specific test types
mapify playbook query "unit test"
mapify playbook query "integration test"
mapify playbook query "end to end test"

# Test automation
mapify playbook query "test automation CI CD"
```

### Best Practices Summary

✅ **DO:**
- Replace hyphens with spaces in queries
- Use quotes for exact phrase matching
- Use prefix wildcards (`auth*`) for variations
- Combine boolean operators for precise searches
- Start broad, refine if too many results

❌ **DON'T:**
- Use hyphens in queries (causes syntax errors)
- Expect infix/suffix wildcards (`*auth`, `te*st`)
- Use column filters (`title:auth`) - not supported
- Forget to balance parentheses in boolean queries
- Make queries too specific (may miss relevant results)

### Quick Reference

| Query Pattern | Example | Matches |
|--------------|---------|---------|
| Simple term | `authentication` | Bullets with "authentication" |
| Multiple terms (AND) | `JWT authentication` | Bullets with both "JWT" AND "authentication" |
| Exact phrase | `"JWT authentication"` | Exact phrase "JWT authentication" |
| OR operator | `JWT OR OAuth` | Bullets with "JWT" OR "OAuth" |
| NOT operator | `auth NOT OAuth` | "auth" but NOT "OAuth" |
| Prefix wildcard | `auth*` | "auth", "authentication", "authorize" |
| Complex boolean | `(JWT OR session) AND auth NOT OAuth` | "JWT" or "session", with "auth", without "OAuth" |
| Hyphenated terms | `session start` (not `session-start`) | Matches "session-start hook" |

## 🔄 Handling Context Compaction

MAP workflows automatically save progress to the `.map/` directory, which persists across context compactions. This ensures your work is never lost, even if the conversation context is cleared.

### What is Context Compaction?

Context compaction occurs when Claude's conversation memory reaches its limit. When this happens:
- The conversation history is cleared to free up space
- But your work files on disk remain intact
- MAP **automatically restores your workflow state** in the new session

### Automatic Recovery (Phase 2) ✨ NEW

**How it works:**

MAP Framework uses a **SessionStart hook** that automatically injects your checkpoint at the beginning of each new session. When you start a conversation:

1. **Hook triggers automatically** - No user action required
2. **Validates checkpoint file** - 4-layer security validation (see Security section below)
3. **Injects context seamlessly** - Claude receives your plan with a restoration header

**What you'll see:**

When starting a new session with an existing checkpoint (`.map/current_plan.md`), Claude will display:

```markdown
# 🔄 MAP Workflow Context Restored

This context was automatically restored from your previous session's checkpoint.
The plan below reflects your current task progress and helps maintain workflow
continuity after context compaction.

---

# Current Task: feat_auth_1730000000
## Goal: Implement JWT authentication
## Progress: 3/5 subtasks completed

- [✓] 1/5: Create User model
- [✓] 2/5: Implement login endpoint
- [✓] 3/5: Add token validation middleware
- [→] 4/5: Add refresh token logic (CURRENT)
- [☐] 5/5: Write integration tests
```

**Zero cognitive load** - You can immediately continue with:

```
User: continue with the current subtask

Claude: [already has context from auto-injected checkpoint]
        Continuing subtask 4: "Add refresh token logic"
        [implements solution]
```

**Benefits:**

- ✅ **Invisible recovery** - No manual file references needed
- ✅ **Always current** - Checkpoint auto-updates on every status change
- ✅ **Secure by design** - 4-layer validation prevents malicious files
- ✅ **Cross-session continuity** - Start new session, pick up exactly where you left off

### Security Validations

The SessionStart hook implements **defense-in-depth security** with 4 validation layers:

1. **Path Traversal Prevention**
   - Only allows files within `.map/` directory
   - Resolves symlinks and `../` paths to prevent escaping
   - Rejects absolute paths outside project

2. **Size Bomb Protection**
   - Maximum file size: **256KB** (prevents memory exhaustion)
   - Validates size **before reading** file content
   - Rejects oversized files with clear error message

3. **UTF-8 Encoding Validation**
   - Enforces strict UTF-8 encoding
   - Handles decoding errors gracefully
   - Prevents binary file injection

4. **Content Sanitization**
   - Strips control characters (terminal escape codes, NULL bytes)
   - Preserves newlines and tabs (formatting)
   - Removes: `\x00-\x08`, `\x0b-\x0d`, `\x0e-\x1f`, `\x7f` (DELETE), Unicode control chars

**Why this matters:**

- **Path traversal attacks** - Malicious checkpoint could try to inject `/etc/passwd` or `~/.ssh/id_rsa`
- **Size bombs** - Large files could exhaust memory, causing Claude Code to crash
- **Control character injection** - Terminal escape codes could manipulate Claude's output
- **Encoding exploits** - Binary data could contain executable payloads

**Implementation:**

```python
# .claude/hooks/helpers/validate_checkpoint_file.py
# All checks use AND logic - file must pass ALL layers to be valid

validate_path_security()      # Layer 1: .map/ only
validate_file_size()           # Layer 2: <256KB
read_and_validate_content()   # Layer 3: UTF-8
sanitize_content()             # Layer 4: Strip control chars
```

See [validate_checkpoint_file.py](.claude/hooks/helpers/validate_checkpoint_file.py) for implementation details.

### Manual Recovery (Fallback)

**When to use manual recovery:**

- **Hook fails** - SessionStart hook not working (see Troubleshooting)
- **Debugging** - Want to verify checkpoint contents before injecting
- **Explicit control** - Prefer to manually reference files

**Steps:**

1. **Locate checkpoint files** (auto-saved during workflow):

   ```
   .map/current_plan.md     - Human-readable plan
   .map/dev_docs/context.md - Project context
   .map/dev_docs/tasks.md   - Task checklist
   ```

2. **After compaction**, manually reference files:

   ```
   User: continue MAP workflow
         @.map/current_plan.md
         @.map/dev_docs/context.md
         @.map/dev_docs/tasks.md

   Claude: [reads files]
           Resuming subtask 4: "Add refresh token logic"
           [continues implementation from saved state]
   ```

### Before/After Comparison

| Phase 1 (Manual) | Phase 2 (Automatic) ✨ |
|------------------|----------------------|
| Notice context getting low | No monitoring needed |
| Check `.map/` files manually | Automatic on every update |
| Copy file paths | No action required |
| Paste paths with `@` prefix in new session | Hook auto-injects checkpoint |
| Claude reads files manually | Claude receives context automatically |
| **User action required** | **Zero user action** |

**Example Workflow:**

**Phase 1 (Manual):**
```
[Context gets low]
[Check .map/ files exist]
[Compaction happens]
[New session starts]
User: continue MAP workflow
      @.map/current_plan.md
      @.map/dev_docs/context.md
      @.map/dev_docs/tasks.md
Claude: [reads files] Resuming...
```

**Phase 2 (Automatic):**
```
[Context gets low]
[Compaction happens]
[New session starts - hook triggers automatically]
Claude: # 🔄 MAP Workflow Context Restored
        [checkpoint injected automatically]
User: continue with current subtask
Claude: [already has context] Continuing subtask 4...
```

### Troubleshooting

#### Hook not working?

**Symptoms:**
- New session starts WITHOUT checkpoint restoration header
- No "🔄 MAP Workflow Context Restored" message

**Diagnosis:**

1. **Check if checkpoint file exists:**
   ```bash
   ls -lh .map/current_plan.md
   ```
   - If missing: No checkpoint to restore (expected for new projects)
   - If exists: Proceed to step 2

2. **Check hook is installed:**
   ```bash
   ls -l .claude/hooks/session-start.sh
   ```
   - If missing: Run `mapify init` to install hooks
   - If exists: Proceed to step 3

3. **Check hook logs** (Claude Code stderr):
   - Look for: `[session-start] SessionStart hook triggered`
   - Look for: `[session-start] ✅ Successfully validated checkpoint`
   - If error: Check validation failure reason

4. **Manual validation test:**
   ```bash
   python3 .claude/hooks/helpers/validate_checkpoint_file.py \
       --file .map/current_plan.md
   ```
   - Should output: `{"valid": true, ...}`
   - If `valid: false`: Check error message for reason

**Common issues:**

| Issue | Cause | Solution |
|-------|-------|----------|
| Hook not executing | Hooks not enabled in Claude Code | Check Claude Code settings |
| File too large | Checkpoint >256KB | Reduce plan verbosity, split into subtasks |
| Path traversal error | Checkpoint outside `.map/` | Move checkpoint to `.map/current_plan.md` |
| UTF-8 decoding error | Binary or corrupted file | Delete and let workflow regenerate checkpoint |

**Fallback:**

If hook continues to fail, use [Manual Recovery](#manual-recovery-fallback) workflow.

#### Safe re-initialization with merge behavior

**Key Feature:** Running `mapify init` preserves your customizations when updating MAP Framework hooks.

**What gets preserved:**
- ✅ Your custom hooks (UserPromptSubmit, PreToolUse, Stop, etc.)
- ✅ Your permissions settings
- ✅ Your top-level configuration keys (description, customKey, etc.)

**What gets added:**
- ✅ New MAP Framework hooks (if they don't already exist)
- ✅ Updated hook scripts from templates

**How it works:**

```bash
# Safe to run multiple times - your customizations won't be lost
mapify init --force
```

**Deduplication strategy:**

MAP Framework uses the `matcher` field to identify duplicate hook groups:

| Hook Scenario | Behavior |
|---------------|----------|
| User has `matcher: "custom-pattern"` | Preserved (not in template) |
| Template has `matcher: "Bash\\(.*\\)"` | Added only if user doesn't have this matcher |
| Both have same `matcher: "Edit\\|Write"` | User's version preserved, template not added |
| Hook has no `matcher` or `matcher: ""` | Full JSON comparison used for deduplication |

**Example:**

Your existing `.claude/settings.json`:
```json
{
  "permissions": {
    "allow": ["Bash(git status:*)", "Bash(custom-command:*)"]
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "custom-pattern",
        "description": "User's custom hook",
        "hooks": [{"type": "command", "command": "python3 /custom/script.py"}]
      }
    ]
  }
}
```

After `mapify init`:
```json
{
  "permissions": {
    "allow": ["Bash(git status:*)", "Bash(custom-command:*)"]  // ✅ Preserved
  },
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "custom-pattern",  // ✅ Your custom hook preserved
        "description": "User's custom hook",
        "hooks": [{"type": "command", "command": "python3 /custom/script.py"}]
      },
      {
        "matcher": "",  // ✅ MAP Framework hook added
        "description": "Enhance prompts with clarification and playbook context",
        "hooks": [
          {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/improve-prompt.py"},
          {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/user-prompt-submit.sh"}
        ]
      }
    ],
    "SessionStart": [  // ✅ MAP Framework hook added
      {
        "matcher": "",
        "description": "Auto-inject MAP workflow context from checkpoint",
        "hooks": [{"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/session-start.sh"}]
      }
    ]
  }
}
```

**When to re-run `mapify init`:**
- ✅ After MAP Framework updates (to get new hooks)
- ✅ If hooks are not working (safe to repair)
- ✅ To update hook scripts without losing customizations
- ⚠️ Your customizations are ALWAYS preserved

#### How to verify auto-recovery is working

**Test sequence:**

1. **Create a test task:**
   ```bash
   /map-feature "add test function to app.py"
   ```

2. **Wait for first subtask completion** - Checkpoint should be created at `.map/current_plan.md`

3. **Start NEW conversation** (simulate compaction):
   - Open new chat or use "Clear conversation" (if available)

4. **Verify restoration:**
   - Look for "🔄 MAP Workflow Context Restored" header
   - Check plan shows correct progress (e.g., "1/3 completed")

5. **Continue workflow:**
   ```
   User: continue MAP workflow
   Claude: [should immediately continue from saved state]
   ```

**Expected behavior:**

- ✅ Hook triggers automatically on new session
- ✅ Checkpoint injected with restoration header
- ✅ Plan shows accurate progress (completed/current/pending subtasks)
- ✅ Can continue workflow immediately without manual file references

### Key Points

- ✅ **Automatic restoration** - SessionStart hook injects checkpoint on every new session
- ✅ **Progress auto-saves** - Every workflow step saves to disk
- ✅ **Secure by design** - 4-layer validation (path, size, UTF-8, sanitization)
- ✅ **No manual checkpointing required** - Files update automatically during workflow
- ✅ **Files persist forever** - They're on your filesystem, not in conversation memory
- ✅ **Cross-session recovery** - Resume in any new conversation seamlessly
- ✅ **Manual fallback available** - Reference `.map/` files directly if needed

### Architecture

MAP uses file-based persistence with automatic injection:

**Files:**
- `.map/current_plan.json` - Structured plan data
- `.map/current_plan.md` - Human-readable plan (auto-injected by SessionStart hook)
- `.map/dev_docs/context.md` - Project context
- `.map/dev_docs/tasks.md` - Task checklist

**Hooks:**
- `.claude/hooks/session-start.sh` - SessionStart hook (auto-injection logic)
- `.claude/hooks/helpers/validate_checkpoint_file.py` - Security validation

These files survive compaction because they're stored on disk, not in conversation memory.

**Technical Details:**

For implementation details on SessionStart hook, security validation, and compaction resilience architecture, see:
- [ARCHITECTURE.md - Context Engineering](ARCHITECTURE.md#context-engineering) - Recitation Pattern and Compaction Resilience
- [ARCHITECTURE.md - Context Engineering Roadmap](ARCHITECTURE.md#context-engineering-roadmap) - Phase 2 checkpoint implementation

## 🔍 Dependency Validation

The dependency validation utility (`scripts/validate-dependencies.py`) ensures TaskDecomposer output has valid dependency graphs before execution. It prevents workflow failures by detecting:

- **Circular dependencies** — Tasks that create impossible execution loops (A → B → C → A)
- **Forward references** — Dependencies on non-existent tasks
- **Self-dependencies** — Tasks that depend on themselves
- **Orphaned tasks** — Isolated tasks with no incoming or outgoing dependencies

### Basic Usage

**Recommended (after `pip install mapify-cli`):**

```bash
# Validate from file
mapify validate graph decomposer-output.json

# Output in text format (human-readable)
mapify validate graph decomposer-output.json -f text

# JSON format (default, for CI/CD)
mapify validate graph decomposer-output.json -f json

# Validate from stdin
cat decomposer-output.json | mapify validate graph
```

**For development (using script directly):**

```bash
# Validate from stdin
cat decomposer-output.json | python scripts/validate-dependencies.py

# Validate from file
python scripts/validate-dependencies.py decomposer-output.json

# Output in text format (human-readable)
python scripts/validate-dependencies.py -f text decomposer-output.json

# JSON format (default, for CI/CD)
python scripts/validate-dependencies.py -f json decomposer-output.json
```

### Visualization Mode

Display ASCII dependency tree to understand task execution order:

**Recommended (mapify CLI):**

```bash
# Show dependency tree with colors
mapify validate graph decomposer-output.json --visualize

# Show tree without colors (for logs/CI)
mapify validate graph decomposer-output.json --visualize --no-color
```

**For development (direct script):**

```bash
# Show dependency tree with colors
python scripts/validate-dependencies.py --visualize decomposer-output.json

# Show tree without colors (for logs/CI)
python scripts/validate-dependencies.py --visualize --no-color decomposer-output.json
```

**Example visualization output:**

```
Task Dependency Tree:
Task 1: Setup environment
├─ Task 2: Install dependencies
│  └─ Task 4: Run tests
└─ Task 3: Configure database
   └─ Task 4: Run tests
```

### Exit Codes

The validator uses standard exit codes for automation:

| Exit Code | Meaning | CI/CD Action |
|-----------|---------|--------------|
| `0` | Valid graph (no critical errors) | Continue workflow |
| `1` | Invalid graph (critical errors found) OR warnings with `--strict` flag | Fail build |
| `2` | Invalid input (malformed JSON or missing required fields) | Fix input format |

> **Note**: By default, **warnings** (e.g., orphaned tasks) result in exit code `0` and **do not** fail CI/CD builds. Only **critical errors** (circular dependencies, forward references, self-dependencies) cause exit code `1`. To enforce strict validation where warnings also fail the build, use the `--strict` flag. Use `--format text` to see issue severity levels.

**CI/CD Integration Examples:**

```bash
# Default mode: Only critical errors fail the build
mapify validate graph plan.json || exit 1
echo "✓ Task graph has no critical errors"

# Strict mode: Warnings also fail the build
mapify validate graph --strict plan.json || exit 1
echo "✓ Task graph is perfect (no warnings or errors)"

# Alternative: using direct script (for development/testing)
python scripts/validate-dependencies.py plan.json || exit 1
echo "✓ Task graph validated successfully"
```

### Integration with TaskDecomposer

Validate TaskDecomposer output before starting workflow:

```bash
# Step 1: Decompose task
/map-feature implement user authentication

# Step 2: Review TaskDecomposer output
# (orchestrator saves to .claude/decomposer-output.json)

# Step 3: Validate before execution (recommended)
mapify validate graph .claude/decomposer-output.json

# Alternative (for development): use direct script
python scripts/validate-dependencies.py .claude/decomposer-output.json

# Step 4: If valid, orchestrator proceeds automatically
```

**Note:** MAP Framework orchestrators can integrate this validation step to prevent execution of invalid task graphs.

### Sample TaskDecomposer JSON

```json
{
  "subtasks": [
    {
      "id": 1,
      "title": "Setup authentication middleware",
      "description": "Create Express middleware for JWT validation",
      "dependencies": []
    },
    {
      "id": 2,
      "title": "Implement login endpoint",
      "description": "POST /api/login with email/password",
      "dependencies": [1]
    },
    {
      "id": 3,
      "title": "Add refresh token logic",
      "description": "Implement token refresh endpoint",
      "dependencies": [1, 2]
    }
  ]
}
```

### Validation Output Examples

**Valid graph (JSON format):**

```json
{
  "valid": true,
  "issues": [],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 0,
    "warnings": 0
  }
}
```

**Invalid graph with circular dependency (JSON format):**

```json
{
  "valid": false,
  "issues": [
    {
      "type": "circular_dependency",
      "severity": "critical",
      "affected_tasks": [1, 2, 3],
      "message": "Circular dependency detected: 1 → 2 → 3 → 1"
    }
  ],
  "summary": {
    "total_tasks": 3,
    "critical_issues": 1,
    "warnings": 0
  }
}
```

**Text format output:**

```
⚠️  Validation Failed

Issues Found:
  [CRITICAL] Circular dependency detected: 1 → 2 → 3 → 1
    Affected tasks: 1, 2, 3

Summary:
  Total tasks: 3
  Critical issues: 1
  Warnings: 0
```

### Command-Line Flags Reference

| Flag | Short | Values | Default | Description |
|------|-------|--------|---------|-------------|
| `--format` | `-f` | `json`, `text` | `json` | Output format for validation results |
| `--visualize` | — | — | — | Display ASCII dependency tree |
| `--no-color` | — | — | — | Disable ANSI colors in visualization |
| `--strict` | — | — | — | Fail on warnings (e.g., orphaned tasks), not just critical errors |
| `--help` | `-h` | — | — | Show help message and examples |

### Validation Best Practices

1. **Always validate in CI/CD** — Add validation step before task execution
2. **Use JSON format for automation** — Machine-readable output for scripts
3. **Use text format for debugging** — Human-readable output for investigation
4. **Visualize complex graphs** — Use `--visualize` to understand execution order
5. **Check exit codes** — Use `$?` in shell scripts for automated validation

## 🔀 Workflow Variants

MAP Framework offers four workflow variants with different trade-offs between token usage, quality assurance, and learning:

### Comparison Table

| Feature | /map-feature | /map-efficient ⭐ | /map-debate | /map-fast ⚠️ |
|---------|--------------|-------------------|-------------|--------------|
| **Agents Used** | 8 (full pipeline) | 5-6 (optimized) | 7 (multi-variant) | 3 (minimal) |
| **Token Savings** | 0% (baseline) | **30-40%** | +200% (3x cost) | 40-50% |
| **Learning Enabled** | ✅ Per-subtask | ✅ Batched at end | ✅ Batched | ❌ None |
| **Quality Gates** | All agents | Essential agents | Opus arbiter | Basic only |
| **Impact Analysis** | ✅ Always (Predictor) | ✅ Conditional | ✅ Conditional | ❌ Never |
| **Quality Scoring** | ✅ Yes (Evaluator) | ❌ Skipped | ✅ Via arbiter | ❌ Never |
| **Multi-Variant** | ❌ Single | ⚠️ Conditional (Self-MoA) | ✅ **Always 3 variants** | ❌ Never |
| **Synthesis Model** | N/A | Synthesizer (sonnet) | **debate-arbiter (opus)** | N/A |
| **Playbook Updates** | ✅ Per-subtask | ✅ End of workflow | ✅ End of workflow | ❌ None |
| **Cipher Integration** | ✅ Per-subtask | ✅ End of workflow | ✅ End of workflow | ❌ None |
| **Best For** | Critical features | **Most tasks** | **Reasoning transparency** | Throwaway only |
| **Production Ready** | ✅ Maximum QA | ✅ Yes | ✅ Yes (expensive) | ❌ NO |

### Decision Guide: Which Workflow Should I Use?

#### Use `/map-efficient` (RECOMMENDED) ⭐

**When:**
- ✅ Production code where token costs matter
- ✅ Well-understood features with low-medium risk
- ✅ Iterative development with frequent workflows
- ✅ You want learning without excessive token usage
- ✅ Standard CRUD operations, UI components
- ✅ Refactoring with clear scope

**Why it's better than /map-fast:**
- Still preserves full learning (Reflector/Curator)
- Conditional Predictor catches high-risk issues
- Only 10% less token savings but much safer

**Example use cases:**
```bash
# Standard feature development
/map-efficient implement user profile editing with form validation

# API development
/map-efficient create REST API endpoints for product management

# UI components
/map-efficient build responsive navigation menu with mobile support
```

#### Use `/map-feature` (Full Workflow)

**When:**
- 🔒 Security-critical functionality (authentication, authorization)
- 🔒 First-time implementation of complex features
- 🔒 High-risk changes affecting many files/modules
- 🔒 Database schema migrations
- 🔒 Breaking API changes
- 🔒 You need maximum quality assurance

**Why it's worth the extra tokens:**
- Evaluator scores quality across 6 dimensions
- Predictor always analyzes breaking changes
- Per-subtask learning captures more nuanced patterns
- Maximum safety for critical code

**Example use cases:**
```bash
# Security-critical
/map-feature implement JWT authentication with refresh tokens

# Complex first-time feature
/map-feature build real-time chat system with WebSocket support

# High-risk refactoring
/map-refactor migrate entire codebase from REST to GraphQL
```

#### Use `/map-debate` (Multi-Variant with Reasoning)

**When:**
- 🧠 Decisions require explicit trade-off analysis
- 🧠 You need to understand WHY a solution was chosen
- 🧠 Stakeholders need documented reasoning for code review
- 🧠 Complex architectural decisions with multiple valid approaches
- 🧠 High-value features where reasoning transparency justifies cost

**What makes it different:**
- **ALWAYS generates 3 variants** (security/performance/simplicity focus)
- **Uses Opus model** for debate-arbiter (deeper reasoning than Sonnet)
- **Outputs explicit trade-offs** — what you gain AND what you lose
- **Produces comparison matrix** — scores each variant on 4 dimensions
- **Reasoning trace** — 8-step visible thinking process

**Key outputs:**
- `comparison_matrix` — variant × dimension scores (1-10)
- `decision_rationales` — for each decision: alternatives, winner, trade-off accepted
- `synthesis_reasoning` — step-by-step explanation of synthesis

**Cost consideration:**
- ~3-5x more expensive than `/map-efficient`
- Uses Opus model (higher reasoning capability, higher cost)
- Worth it when reasoning transparency is critical

**Example use cases:**
```bash
# Architectural decision with stakeholder review
/map-debate implement caching strategy for user sessions

# Complex algorithm with multiple valid approaches
/map-debate design rate limiting system for API endpoints

# Decision requiring documented justification
/map-debate implement authentication - JWT vs sessions vs OAuth
```

**Output example (decision_rationale):**
```json
{
  "decision_id": "dec-v1-001",
  "decision_statement": "Use Result type for explicit error handling",
  "alternatives_evaluated": [
    {"source_variant": "v2", "statement": "Raise exceptions", "why_rejected": "Less explicit"},
    {"source_variant": "v3", "statement": "Return tuple", "why_rejected": "Less type-safe"}
  ],
  "selection_reasoning": "Result type provides explicit error handling that caller cannot ignore...",
  "tradeoff_accepted": "Increased code verbosity"
}
```

---

#### Use `/map-fast` (Minimal) ⚠️

**ONLY when:**
- 🗑️ Creating throwaway prototypes you'll discard
- 🗑️ Quick experiments to test feasibility
- 🗑️ Learning/tutorial contexts where failure is acceptable
- 🗑️ Mockups for demonstrations

**⚠️ NEVER use for:**
- ❌ Production code
- ❌ Code you'll commit to repository
- ❌ Features that others will depend on
- ❌ Security-sensitive functionality

**Why it's dangerous:**
- No impact analysis → Breaking changes undetected
- No learning → Playbook stays empty, same mistakes repeated
- No quality scoring → Security/performance issues missed
- No cipher integration → Knowledge lost forever

**Example use cases (acceptable):**
```bash
# Quick prototype to show stakeholder
/map-fast prototype a dashboard layout with mock data

# Feasibility experiment
/map-fast test if library X can integrate with our stack

# Tutorial/learning
/map-fast follow the React tutorial to learn hooks
```

### Real-World Token Usage Examples

**Small Task (1-2 subtasks):**
- `/map-feature`: ~20-30K tokens
- `/map-efficient`: ~12-20K tokens (40% savings)
- `/map-fast`: ~10-15K tokens (50% savings)

**Medium Task (3-5 subtasks):**
- `/map-feature`: ~75-100K tokens
- `/map-efficient`: ~45-60K tokens (40% savings)
- `/map-fast`: ~30-40K tokens (60% savings)

**Large Task (6-8 subtasks):**
- `/map-feature`: ~150-200K tokens
- `/map-efficient`: ~90-120K tokens (40% savings)
- `/map-fast`: ~60-80K tokens (60% savings)

**Cost at $3/M input, $15/M output (Claude Sonnet 3.5):**

| Task Size | /map-feature | /map-efficient | Savings |
|-----------|--------------|----------------|---------|
| Small | $0.30-0.45 | $0.18-0.30 | $0.12-0.15 |
| Medium | $1.13-1.50 | $0.68-0.90 | $0.45-0.60 |
| Large | $2.25-3.00 | $1.35-1.80 | $0.90-1.20 |

**For teams running 10 workflows/day:**
- /map-feature: ~$22.50/day
- /map-efficient: ~$13.50/day
- **Monthly savings: $270** (12 fewer dollars/day × 30 days)

### How /map-efficient Works

**Key Optimizations:**

1. **Conditional Predictor** (5-10% savings)
   - TaskDecomposer assigns risk_level to each subtask
   - Predictor only called if risk_level='high' or Monitor flags issues
   - Low-risk tasks (simple CRUD, UI updates) skip impact analysis

2. **Batched Learning** (10-15% savings)
   - Reflector analyzes ALL subtasks together at end
   - Curator makes single playbook update
   - More holistic insights (sees patterns across subtasks)
   - Saves (N-1) × 3K tokens for N subtasks

3. **Evaluator Skipped** (8-12% savings)
   - Monitor provides sufficient validation for most tasks
   - Evaluator's 6-dimension scoring rarely changes decisions
   - Quality still ensured by Monitor's comprehensive checks

**What's Preserved:**
- ✅ Full learning cycle (Reflector + Curator)
- ✅ Playbook updates (batched but complete)
- ✅ Cipher integration (high-quality patterns stored)
- ✅ Essential quality gates (Monitor validation)
- ✅ Impact analysis (when needed)

### Workflow Selection Flowchart

```
START: I need to implement a feature
  |
  ├─ Is it throwaway/prototype code?
  |    └─ YES → /map-fast (but consider if learning would help)
  |    └─ NO → Continue
  |
  ├─ Is it security-critical or first-time complex feature?
  |    └─ YES → /map-feature (maximum QA)
  |    └─ NO → Continue
  |
  ├─ Do stakeholders need documented reasoning for decisions?
  |    └─ YES → /map-debate (explicit trade-offs, Opus reasoning)
  |    └─ NO → Continue
  |
  ├─ Do I care about token costs?
  |    └─ NO → /map-feature (best quality)
  |    └─ YES → /map-efficient ⭐ (RECOMMENDED)
```

### Migration Guide

**Switching from /map-feature to /map-efficient:**

No code changes needed! Just use `/map-efficient` instead:

```bash
# Old
/map-feature implement user dashboard

# New (saves 30-40% tokens, same learning)
/map-efficient implement user dashboard
```

**When to keep using /map-feature:**
- First implementation of authentication/authorization
- Database migrations affecting multiple tables
- Breaking API changes
- Any feature where failure is costly

### Common Misconceptions

**❌ Misconception:** "/map-fast is 50% cheaper, so it's always better for saving money"
**✅ Reality:** /map-fast defeats MAP's purpose (no learning = repeat mistakes = waste tokens long-term). Use /map-efficient instead.

**❌ Misconception:** "/map-efficient skips quality checks"
**✅ Reality:** Monitor still validates everything. Only Evaluator's scoring is skipped (rarely changes decisions).

**❌ Misconception:** "Batched learning in /map-efficient is inferior to per-subtask learning"
**✅ Reality:** Batched learning sees patterns ACROSS subtasks, often producing better insights than isolated per-subtask analysis.

## 🎯 Best Practices

### 1. Actor Quality Checklist (NEW in v2.3.0)

The Actor agent now includes a 10-item Quality Checklist for self-review before submitting implementations to Monitor. Using this checklist reduces iteration cycles by 30-40%.

**Benefits:**
- Catches common issues early (before Monitor validation)
- Reduces Monitor iterations from 2-3 down to 1
- Speeds up overall workflow completion
- Trains Actor to internalize quality criteria

**The checklist covers:**
1. Code style compliance (follows project standards)
2. Explicit error handling (no silent failures)
3. Security review (SQL injection, XSS, sensitive data)
4. Test case identification (happy path + edge cases)
5. MCP tools usage (cipher_memory_search, context7)
6. Template variable preservation (orchestration compatibility)
7. Trade-offs documentation (decision rationale)
8. Playbook bullet tracking (ACE feedback loop)
9. Complete implementations (no ellipsis or placeholders)
10. Dependency justification (no unnecessary libraries)

**How it works:**
- Actor performs self-review before submission
- Critical Reminders section references the checklist
- Monitor validation is faster (fewer common issues)

**Learn more:** See `.claude/agents/actor.md` lines 1102-1142 for the complete checklist.

### 2. Clear Requirements

Always provide specific, detailed requirements to get the best results.

```bash
# Good ✅
"Implement registration with email validation, password strength check (8+ chars, 1 number), send confirmation"

# Bad ❌
"Add registration"
```

**Why it matters:**

- Clear requirements lead to better task decomposition
- Reduces Actor-Monitor retry cycles
- Produces more maintainable code

### 2. Incremental Approach

Break large features into phases to maintain focus and quality:

- **Phase 1:** Core functionality
- **Phase 2:** Edge cases and error handling
- **Phase 3:** Optimization

**Example workflow:**

```bash
# Phase 1: Core implementation
/map-feature implement basic user authentication with login/logout

# Phase 2: Enhanced security
/map-feature add password reset and email verification to authentication

# Phase 3: Performance tuning
/map-refactor optimize authentication to use Redis session caching
```

### 3. Provide Context

Always specify relevant project context to improve solution quality:

**Include:**

- Technology stack (e.g., "using Express.js with TypeScript")
- Existing patterns (e.g., "follow the service-repository pattern used in UserService")
- Constraints (e.g., "must work with PostgreSQL 12+")
- Performance requirements (e.g., "handle 1000 requests/second")

**Example:**

```bash
/map-feature implement product search using Elasticsearch.
Stack: Node.js + Express + PostgreSQL.
Follow existing repository pattern in ProductRepository.
Must handle 500 concurrent searches with <200ms response time.
```

## 💰 Cost Optimization

MAP Framework supports intelligent model selection per agent to balance capability and cost.

### Model Distribution Strategy (Updated Nov 2025)

> **Note:** In v3.0+, Predictor and Evaluator were upgraded from `haiku` to `sonnet` for better analysis quality.

| Agent | Model | Reason | Cost Impact |
|-------|-------|--------|-------------|
| **Predictor** | sonnet | Impact analysis requires complex reasoning (upgraded from haiku) | ➡️ |
| **Evaluator** | sonnet | Evaluation requires nuanced judgment (upgraded from haiku) | ➡️ |
| **Actor** | sonnet | Code generation quality is critical | ➡️ |
| **Monitor** | sonnet | Quality validation requires thoroughness | ➡️ |
| **TaskDecomposer** | sonnet | Requires good understanding of requirements | ➡️ |
| **Reflector** | sonnet | Pattern extraction needs reasoning | ➡️ |
| **Curator** | sonnet | Knowledge management requires care | ➡️ |
| **DocumentationReviewer** | sonnet | Documentation analysis needs thoroughness | ➡️ |

### Cost Impact of Model Upgrades

The upgrade of Predictor and Evaluator from haiku to sonnet provides:

- **Better analysis quality**: More accurate impact predictions and quality evaluations
- **Higher costs**: ~12x increase per agent call for predictor/evaluator
  - Input tokens: $0.25/1M (haiku) → $3/1M (sonnet)
  - Output tokens: $1.25/1M (haiku) → $15/1M (sonnet)
- **Per-workflow impact**: ~$0.03 → ~$0.36 for typical 4-subtask feature

### Cost Mitigation Strategies

**1. Use `/map-efficient` workflow (RECOMMENDED)**
- Skips Evaluator per subtask (Monitor provides sufficient validation)
- Conditional Predictor (only called for high-risk changes)
- Batched Reflector/Curator at end
- **Token savings: 30-40%**

**2. Use `/map-fast` for throwaway code**
- Minimal agent sequence: TaskDecomposer → Actor → Monitor
- Skips: Predictor, Evaluator, Reflector, Curator
- **Token savings: 40-50%** (but no learning!)

### How It Works

Agents automatically use their configured model when invoked via slash commands:

```bash
# Full workflow - all agents use sonnet
/map-feature implement authentication

# Efficient workflow - conditional predictor, batched learning
/map-efficient implement authentication  # Recommended for most tasks

# Fast workflow - minimal agents, no learning
/map-fast prototype quick API mockup     # Throwaway code only
```

### Cost Comparison Example

**Scenario:** Implement a feature with 4 subtasks

| Workflow | TaskDecomposer | Actor (4x) | Monitor (4x) | Predictor | Evaluator | Reflector | Curator | Total Cost* |
|----------|----------------|------------|--------------|-----------|-----------|-----------|---------|-------------|
| `/map-feature` | sonnet | sonnet | sonnet | sonnet (4x) | sonnet (4x) | sonnet (4x) | sonnet (4x) | ~$0.36 |
| `/map-efficient` | sonnet | sonnet | sonnet | sonnet (0-2x) | skip | sonnet (1x) | sonnet (1x) | ~$0.22 |
| `/map-fast` | sonnet | sonnet | sonnet | skip | skip | skip | skip | ~$0.12 |

*Approximate costs based on typical token usage

**Savings:**
- `/map-efficient`: ~40% savings vs `/map-feature`, maintains learning
- `/map-fast`: ~67% savings vs `/map-feature`, but NO playbook updates

---

## Additional Resources

- **[README.md](README.md)** — Project overview and installation
- **[INSTALL.md](INSTALL.md)** — Detailed installation instructions
- **[Sequential Thinking Integration Guide](docs/SEQUENTIAL_THINKING_GUIDE.md)** — When and how MAP agents use structured reasoning for complex analysis
- **[Context Engineering Improvements](docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md)** — Advanced optimization techniques
- **[Agent Customization](.claude/agents/README.md)** — Customizing agent behavior

---

## 📚 Skills System

MAP includes interactive skills to help you navigate workflows and understand the framework.

### Available Skills

#### map-workflows-guide

Get help choosing the right workflow for your task.

**How to access:**
```
User: "Which workflow should I use?"
MAP: [Loads map-workflows-guide skill automatically]
```

**What you get:**
- **Quick decision tree** - Answer 5 questions to find your workflow
- **Comparison matrix** - Token cost, learning, agents, best-for columns
- **Detailed guides** - When to use each workflow, trade-offs, examples
- **8 deep-dive resources** - Progressive disclosure for comprehensive learning

**Skills vs Agents:**
- **Skills** provide passive guidance (documentation)
- **Agents** execute active tasks (code generation)
- Skills load via Skill tool, agents execute via Task tool

### Auto-Activation

Skills automatically suggest themselves when relevant:

**Keywords that trigger map-workflows-guide:**
- "which workflow"
- "difference between workflows"
- "when to use map-efficient"
- "workflow comparison"

**Example flow:**
```
User: "I need to add a feature"
MAP: 🎯 "Consider /map-efficient"

User: "What's the difference between efficient and feature?"
MAP: 📚 "Loading map-workflows-guide skill"
[Shows comparison: efficient = production, feature = critical]
```

### Progressive Disclosure

Skills follow the 500-line rule:
- **Main SKILL.md** (<500 lines) - High-level overview, quick decisions
- **Resources/** (8 files) - Deep-dive topics loaded on demand

**Benefits:**
- Fast scanning (5-10 min for main skill)
- Comprehensive when needed (25+ min with all resources)
- Prevents context limit issues

### Resources Available

**Workflow deep-dives:**
- `map-fast-deep-dive.md` - Skip conditions, when to avoid
- `map-efficient-deep-dive.md` - Optimization strategy, recommended default
- `map-feature-deep-dive.md` - Full validation, critical features
- `map-debug-deep-dive.md` - Debugging strategies, error analysis
- `map-refactor-deep-dive.md` - Dependency analysis, breaking changes

**System architecture:**
- `agent-architecture.md` - How 8 agents orchestrate
- `playbook-system.md` - Knowledge storage, quality scoring
- `cipher-integration.md` - Cross-project learning

### Creating Custom Skills

See `.claude/skills/README.md` for:
- Skill structure (SKILL.md + resources/)
- Trigger configuration (skill-rules.json)
- Integration with auto-activation
- Best practices and examples

---

## 🔌 Hooks System

MAP Framework uses Claude Code hooks to enhance your workflow experience.

### Prompt Clarification (Prompt-Improver Hook)

**Enabled by default** - Automatically disambiguates vague prompts before execution.

**What it does:**
1. **Evaluates prompt clarity** using conversation history
2. **For vague prompts** (e.g., "fix the bug"):
   - Creates research plan (TodoWrite)
   - Gathers context from codebase, docs, web
   - Asks 1-6 grounded questions with specific options
3. **For clear prompts**: Proceeds immediately

**Example flow:**
```
User: "fix the error"

MAP: [Prompt Improver Hook seeking clarification]
     [Research: Found 3 recent errors in logs]

     Which error needs fixing?
     ○ TypeError in src/components/Map.tsx (recent change)
     ○ API timeout in src/services/osmService.ts
     ○ Other (paste error message)

User: [Selects option]

MAP: [Proceeds with full context + playbook patterns]
```

**Bypass options:**
- `* your prompt` - Skip evaluation (remove `*` prefix)
- `/command` - Slash commands bypass automatically
- `# memorize` - Memorize feature bypasses automatically

**Token overhead:**
- ~300 tokens per wrapped prompt
- Only adds questions when genuinely needed
- Better outcomes on first try = overall efficiency

**Design philosophy:**
- **Rarely intervene** - Most prompts pass through
- **Trust user intent** - Research before asking
- **Transparent** - Evaluation visible in conversation
- **Max 1-6 questions** - Focused clarification

### Multi-Hook Processing

MAP uses **multiple UserPromptSubmit hooks** that run in parallel:

1. **Prompt-Improver** – Disambiguates vague prompts (wraps prompt with evaluation instructions)
2. **Playbook Injection** – Adds relevant patterns, and suggests workflows and skills

> **Note:** Claude Code executes all matching hooks in parallel. Each hook's `additionalContext` output is concatenated and added to the prompt. The order is not guaranteed, but both enhancements are applied.

> **Implementation detail:** Workflow and skill suggestions are handled within the Playbook Injection hook (`.claude/hooks/user-prompt-submit.sh`), not as separate hooks.

**Benefits:**
- Both hooks enhance the prompt with different types of context
- Prompt-Improver adds evaluation wrapper, Playbook adds patterns/workflows/skills
- Modular design (hooks can be disabled independently)
- Parallel execution (efficient)

### Disabling Prompt-Improver

If you prefer direct execution without clarification:

**Option 1: Use bypass prefix**
```bash
* implement user authentication  # Skips improvement
```

**Option 2: Remove from settings.hooks.json**
```json
{
  "hooks": {
    "UserPromptSubmit": [
      // Comment out or remove Prompt-Improver hook
      {
        "description": "Step 2: Inject playbook patterns and suggest workflows",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/user-prompt-submit.sh"
          }
        ]
      }
    ]
  }
}
```

### Other Active Hooks

MAP Framework includes additional hooks:

- **SessionStart** - Auto-injects checkpoint after compaction (see [Compaction Resilience](#-compaction-resilience))
- **PreToolUse** - Validates agent templates before modifications
- **Stop** - Quality gates after code modifications

See `.claude/hooks/README.md` for implementation details.

---
