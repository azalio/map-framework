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
- [Pattern Storage & Retrieval (mem0 MCP)](#-pattern-storage--retrieval-mem0-mcp)
- [Common CLI Mistakes](#-common-cli-mistakes)
    - [Wrong Approach](#wrong-approach-critical)
  - [Wrong Operation Field Name](#wrong-operation-field-name)
  - [Quick Reference Resources](#quick-reference-resources)
  - [Validation Tools](#validation-tools)
- [Pattern Search Tips (mem0 MCP)](#-pattern-search-tips-mem0-mcp)
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
- [Verification Results and Early Termination](#-verification-results-and-early-termination)
  - [Verification Results Tracking](#verification-results-tracking)
  - [Recipe Status Values](#recipe-status-values)
  - [Skipped Status Explained](#skipped-status-explained)
  - [Hooks Contract: When Hooks Block](#hooks-contract-when-hooks-block)
  - [Early Termination with won't_do](#early-termination-with-wont_do-status)
  - [Troubleshooting Verification Issues](#troubleshooting-verification-issues)
- [Additional Resources](#additional-resources)

---

## 📚 Usage Examples

### Feature Development

```bash
/map-efficient implement user profile page with avatar upload.
Include validation, error handling, and tests.
```

### Bug Fixing

```bash
/map-debug debug why payment processing fails for amounts over $1000
```

### Refactoring

```bash
/map-efficient refactor OrderService to use dependency injection.
Maintain all existing functionality.
```

### Library Integration

```bash
/map-efficient integrate Stripe payment processing.
Use context7 to get latest Stripe docs.
```

### Learning from Open Source

```bash
/map-efficient implement rate limiter.
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

## 🧠 Pattern Storage & Retrieval (mem0 MCP)

As of v4.0, patterns are stored and retrieved via the mem0 MCP server. There is no local playbook CLI workflow for pattern search/update.

### Tiered Pattern Search

Use `mcp__mem0__map_tiered_search` to search across scopes (branch → project → org):

```bash
# Basic search
mcp__mem0__map_tiered_search(query="JWT authentication", limit=5)

# Narrow search by section (example)
mcp__mem0__map_tiered_search(query="error handling", section_filter="ERROR_HANDLING_PATTERNS", limit=10)
```

### Adding / Archiving Patterns

Patterns should be written through the Curator agent (deduplication + fingerprinting):

```bash
Task(subagent_type="curator", ...)

# Curator uses mem0 MCP tools:
# - mcp__mem0__map_add_pattern
# - mcp__mem0__map_archive_pattern
# - mcp__mem0__map_promote_pattern
```

---

## ⚠️ Common CLI Mistakes

This section documents frequently encountered CLI command errors and their corrections. These validations are enforced by:
- Pre-commit hooks (`.git/hooks/pre-commit`)
- E2E tests (`tests/test_agent_cli_correctness.py`)
- Agent template CLI reference sections

### Common Mistakes (v4.0+)

| ❌ Incorrect | ✅ Correct | Explanation |
|-------------|-----------|-------------|
| Using legacy playbook commands (`mapify playbook ...`) | Use `mcp__mem0__map_tiered_search` | Playbook CLI is not used for patterns in v4.0+ |
| Calling mem0 tools directly from workflow docs | Use `Task(subagent_type="curator", ...)` for writes | Curator handles dedupe + quality scoring |

### Wrong Approach (CRITICAL)

| ❌ NEVER DO THIS | ✅ ALWAYS USE THIS | Why |
|------------------|-------------------|-----|
| Direct mem0 MCP calls without Curator | `Task(subagent_type="curator", ...)` | Curator validates quality, checks duplicates via tiered search |
| Manually creating patterns | `mcp__mem0__map_add_pattern` via Curator | Fingerprint-based deduplication prevents duplicates |

> **Note (v4.0+):** Pattern storage migrated from playbook.db to mem0 MCP. Use mem0 tools: `mcp__mem0__map_tiered_search`, `mcp__mem0__map_add_pattern`, `mcp__mem0__map_archive_pattern`.

### Wrong Operation Field Name

| ❌ Incorrect JSON | ✅ Correct JSON |
|------------------|----------------|
| `{"op": "ADD", "section": "...", "content": "..."}` | `{"type": "ADD", "section": "...", "content": "..."}` |
| `{"op": "UPDATE", "bullet_id": "..."}` | `{"type": "UPDATE", "bullet_id": "..."}` |
| `{"op": "DEPRECATE", "bullet_id": "..."}` | `{"type": "DEPRECATE", "bullet_id": "..."}` |

**Explanation:** Delta operations use the field name `"type"`, not `"op"`. This is enforced in agent templates and validated by workflow contracts.

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

> **Note (v4.0+):** As of v4.0, primary pattern storage has migrated to mem0 MCP. The Knowledge Graph API below is retained for entity/relationship queries on legacy data. For pattern retrieval, use `mcp__mem0__map_tiered_search`.

```python
import sqlite3

from mapify_cli.graph_query import KnowledgeGraphQuery
from mapify_cli.entity_extractor import EntityType
from mapify_cli.relationship_detector import RelationshipType

# Initialize Knowledge Graph for entity queries (LEGACY - patterns now in mem0)
db_conn = sqlite3.connect(".claude/playbook.db")
kg = KnowledgeGraphQuery(db_conn)

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
- Searching for human-readable best practices (use mem0 pattern search instead)
- You need semantic patterns rather than entities/relationships (use `mcp__mem0__map_tiered_search`)
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

Migration is handled automatically by the framework.

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

- **Architecture**: [ARCHITECTURE.md](./ARCHITECTURE.md) — Technical architecture including Knowledge Graph layer

---

## 🔍 Pattern Search Tips (mem0 MCP)

As of v4.0, pattern search is provided by mem0 MCP. Unlike the legacy FTS5-based playbook search, mem0 search is semantic and works best with descriptive queries.

### Practical Query Guidelines

- Include the concrete technology and intent (e.g. "JWT refresh tokens", "Go error handling")
- Add qualifiers when results are too broad (e.g. "PostgreSQL", "FastAPI", "rate limiting")
- Prefer natural language for conceptual lookups (e.g. "how to handle retries with jitter")

```bash
# Basic search (tiered: branch → project → org)
mcp__mem0__map_tiered_search(query="JWT authentication", limit=5)

# More specific query
mcp__mem0__map_tiered_search(query="retry with exponential backoff and jitter", limit=5)

# Section-filtered search (when you know the category)
mcp__mem0__map_tiered_search(query="input validation", section_filter="SECURITY_PATTERNS", limit=10)
```

## 🔄 Handling Context Compaction

MAP workflows automatically save progress to the `.map/` directory, which persists across context compactions. This ensures your work is never lost, even if the conversation context is cleared.

### What is Context Compaction?

Context compaction occurs when Claude's conversation memory reaches its limit. When this happens:
- The conversation history is cleared to free up space
- But your work files on disk remain intact
- MAP **automatically restores your workflow state** in the new session

### Checkpoint Recovery with /map-resume

**How it works:**

MAP Framework uses a `/map-resume` command to recover interrupted workflows. When you start a new session after context exhaustion:

1. **Run `/map-resume`** - Simple command to check for incomplete workflow
2. **View progress summary** - Shows completed and remaining subtasks
3. **Confirm Y/n** - Resume workflow or clear checkpoint and start fresh

**What you'll see:**

When running `/map-resume` with an existing checkpoint (`.map/progress.md`):

```markdown
## Found Incomplete Workflow

**Task:** Implement JWT authentication
**Current Phase:** implementation
**Turn Count:** 12

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks ✅
- [x] **ST-001**: Create User model
- [x] **ST-002**: Implement login endpoint
- [x] **ST-003**: Add token validation middleware

### Remaining Subtasks 📋
- [ ] **ST-004**: Add refresh token logic
- [ ] **ST-005**: Write integration tests

Resume from last checkpoint? [Y/n]
```

**Simple recovery** - Press Y to continue:

```
User: Y

Claude: Resuming workflow from ST-004...
        [continues Actor→Monitor loop for remaining subtasks]
```

**Benefits:**

- ✅ **Explicit recovery** - User controls when to resume
- ✅ **Progress visibility** - See exactly what's done and remaining
- ✅ **Simple Y/n prompt** - No complex options
- ✅ **Cross-session continuity** - Resume in any new conversation

### Security Design

The checkpoint format (`.map/progress.md`) is designed with security in mind:

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

**Mitigation:**

The checkpoint format (`.map/progress.md`) is designed with security in mind:
- YAML frontmatter with simple key-value pairs (no code execution)
- Human-readable markdown body (can be visually inspected)
- Small file sizes (workflow state only, not code)
- `/map-resume` command validates checkpoint before resuming

### Manual Recovery (Fallback)

**When to use manual recovery:**

- **Corrupted checkpoint** - `/map-resume` can't parse checkpoint
- **Debugging** - Want to verify checkpoint contents before resuming
- **Explicit control** - Prefer to manually reference files

**Steps:**

1. **Locate checkpoint files** (auto-saved during workflow):

   ```
   .map/progress.md         - Workflow state (YAML frontmatter + markdown)
   .map/task_plan_*.md      - Task decomposition with validation criteria
   ```

2. **After compaction**, manually reference files:

   ```
   User: continue MAP workflow
         @.map/progress.md
         @.map/task_plan_map-to-enchance.md

   Claude: [reads files]
           Resuming subtask 4: "Add refresh token logic"
           [continues implementation from saved state]
   ```

### Before/After Comparison

| Without MAP Recovery | With /map-resume ✨ |
|---------------------|---------------------|
| Lose all workflow context | Context preserved in checkpoint |
| Start over from scratch | Resume from last completed subtask |
| Copy file paths manually | Single command recovery |
| Paste paths with `@` prefix | Simple Y/n confirmation |
| **Workflow abandoned** | **Workflow continues** |

**Example Workflow:**

**Without MAP Recovery:**
```
[Context gets low]
[Compaction happens]
[New session starts]
User: what was I working on?
Claude: I don't have context from your previous session...
[User has to explain everything again]
```

**With /map-resume:**
```
[Context gets low]
[Compaction happens]
[New session starts]
User: /map-resume
Claude: ## Found Incomplete Workflow
        3/5 subtasks completed (60%)
        Resume from last checkpoint? [Y/n]
User: Y
Claude: Resuming workflow from ST-004...
        [continues Actor→Monitor loop]
```

### Troubleshooting

#### /map-resume not working?

**Symptoms:**
- `/map-resume` says "No Workflow in Progress"
- Checkpoint exists but won't load

**Diagnosis:**

1. **Check if checkpoint file exists:**
   ```bash
   ls -lh .map/progress.md
   ```
   - If missing: No checkpoint to restore (expected for new projects)
   - If exists: Proceed to step 2

2. **Check checkpoint file contents:**
   ```bash
   head -20 .map/progress.md
   ```
   - Should contain valid YAML frontmatter with `task_plan:`, `current_phase:`, etc.
   - If malformed: Delete and start fresh with `/map-efficient`

3. **Resume workflow:**
   ```bash
   /map-resume
   ```
   - Shows progress summary and asks for confirmation
   - Y to resume, n to clear checkpoint and start fresh

**Common issues:**

| Issue | Cause | Solution |
|-------|-------|----------|
| No checkpoint found | Workflow not started or completed | Start new workflow with `/map-efficient` |
| YAML parse error | Corrupted checkpoint | Delete `.map/progress.md` and start fresh |
| Missing task plan | Task plan file deleted | Delete checkpoint and restart workflow |

**Fallback:**

If `/map-resume` continues to fail, use [Manual Recovery](#manual-recovery-fallback) workflow.

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
          {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/improve-prompt.py"}
        ]
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
   /map-efficient "add test function to app.py"
   ```

2. **Wait for first subtask completion** - Checkpoint should be created at `.map/progress.md`

3. **Start NEW conversation** (simulate compaction):
   - Open new chat or use "Clear conversation" (if available)

4. **Run recovery command:**
   ```bash
   /map-resume
   ```

5. **Verify restoration:**
   - Look for "Found Incomplete Workflow" header
   - Check plan shows correct progress (e.g., "1/3 completed")
   - Press Y to continue

**Expected behavior:**

- ✅ `/map-resume` detects checkpoint file
- ✅ Progress summary shows completed/remaining subtasks
- ✅ Y/n prompt allows user control
- ✅ Workflow continues from last incomplete subtask

### Key Points

- ✅ **Explicit recovery** - `/map-resume` command to restore workflow state
- ✅ **Progress auto-saves** - Every workflow step saves to disk
- ✅ **Simple checkpoint format** - YAML frontmatter + markdown body
- ✅ **No manual checkpointing required** - Files update automatically during workflow
- ✅ **Files persist forever** - They're on your filesystem, not in conversation memory
- ✅ **Cross-session recovery** - Resume in any new conversation with `/map-resume`
- ✅ **Manual fallback available** - Reference `.map/` files directly if needed

### Architecture

MAP uses file-based persistence with automatic injection:

**Files:**
- `.map/progress.md` - Workflow checkpoint with YAML frontmatter (machine-readable) + markdown body (human-readable)
- `.map/task_plan_*.md` - Task decomposition with validation criteria
- `.map/dev_docs/context.md` - Project context
- `.map/dev_docs/tasks.md` - Task checklist

**Recovery command:**
- `/map-resume` - Detects checkpoint and offers to resume incomplete workflow

These files survive compaction because they're stored on disk, not in conversation memory.

**Technical Details:**

For implementation details on checkpoint format and compaction resilience architecture, see:
- [ARCHITECTURE.md - Context Engineering](ARCHITECTURE.md#context-engineering) - Recitation Pattern and Compaction Resilience
- `src/mapify_cli/workflow_state.py` - WorkflowState class with auto-checkpointing

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
/map-efficient implement user authentication

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

MAP Framework offers three workflow variants with different trade-offs between token usage, quality assurance, and learning:

### Comparison Table

| Feature | /map-efficient ⭐ | /map-debate | /map-fast ⚠️ |
|---------|-------------------|-------------|--------------|
| **Agents Used** | 5-6 (optimized) | 7 (multi-variant) | 3 (minimal) |
| **Token Cost** | **Baseline** | 3x (Opus model) | 40-50% less |
| **Learning** | Via `/map-learn` | Via `/map-learn` | ❌ None |
| **Quality Gates** | Essential agents | Opus arbiter | Basic only |
| **Impact Analysis** | ✅ Conditional | ✅ Conditional | ❌ Never |
| **Multi-Variant** | ⚠️ Conditional (Self-MoA) | ✅ **Always 3 variants** | ❌ Never |
| **Synthesis Model** | Synthesizer (sonnet) | **debate-arbiter (opus)** | N/A |
| **Playbook Updates** | Via `/map-learn` | Via `/map-learn` | ❌ None |
| **Cipher Integration** | Via `/map-learn` | Via `/map-learn` | ❌ None |
| **Best For** | **Most tasks** | **Reasoning transparency** | Throwaway only |
| **Production Ready** | ✅ Yes | ✅ Yes (expensive) | ❌ NO |

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

#### Use `/map-efficient --self-moa` (High-Quality Mode)

**When:**
- 🔒 Security-critical functionality (authentication, authorization)
- 🔒 Complex features with multiple valid approaches
- 🔒 High-risk changes affecting many files/modules

**What `--self-moa` adds:**
- Generates 3 variants (security/performance/simplicity focus)
- Synthesizes best parts from each variant
- Higher quality for critical code

**Example use cases:**
```bash
# Security-critical
/map-efficient --self-moa implement JWT authentication with refresh tokens

# Complex feature
/map-efficient --self-moa build real-time chat system with WebSocket support
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
- ✅ Small, low-risk changes with clear acceptance criteria
- ✅ Localized fixes with minimal blast radius
- ✅ Time-sensitive changes where you still require production-quality output

**⚠️ AVOID for:**
- ❌ Security-sensitive functionality
- ❌ Broad refactors or multi-module changes
- ❌ Ambiguous requirements or high uncertainty
- ❌ Changes requiring careful impact analysis

**Why it's dangerous:**
- No impact analysis → Breaking changes undetected
- No learning → Playbook stays empty, same mistakes repeated
- No quality scoring → Security/performance issues missed
- No cipher integration → Knowledge lost forever

**Example use cases (acceptable):**
```bash
# Small UI tweak
/map-fast Adjust button spacing in settings page

# Localized bug fix
/map-fast Fix nil check in request handler

# Minor docs automation
/map-fast Update CLI help text formatting
```

### Real-World Token Usage Examples

**Small Task (1-2 subtasks):**
- `/map-efficient`: ~12-20K tokens (baseline)
- `/map-efficient --self-moa`: ~25-35K tokens (3 variants)
- `/map-debate`: ~40-60K tokens (Opus arbiter)
- `/map-fast`: ~8-12K tokens (minimal)

**Medium Task (3-5 subtasks):**
- `/map-efficient`: ~45-60K tokens (baseline)
- `/map-efficient --self-moa`: ~100-130K tokens (3 variants)
- `/map-debate`: ~150-200K tokens (Opus arbiter)
- `/map-fast`: ~25-35K tokens (minimal)

**Large Task (6-8 subtasks):**
- `/map-efficient`: ~90-120K tokens (baseline)
- `/map-efficient --self-moa`: ~200-260K tokens (3 variants)
- `/map-debate`: ~300-400K tokens (Opus arbiter)
- `/map-fast`: ~50-70K tokens (minimal)

**Cost at $3/M input, $15/M output (Claude Sonnet) + Opus for debate:**

| Task Size | /map-efficient | /map-debate | /map-fast |
|-----------|----------------|-------------|-----------|
| Small | $0.18-0.30 | $0.60-0.90 | $0.12-0.18 |
| Medium | $0.68-0.90 | $2.25-3.00 | $0.38-0.53 |
| Large | $1.35-1.80 | $4.50-6.00 | $0.75-1.05 |

**For teams running 10 workflows/day with /map-efficient:**
- Daily cost: ~$13.50
- /map-fast would save ~40% but loses learning
- /map-debate costs ~3x more but provides reasoning transparency

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
  ├─ Is it a small, low-risk change?
  |    └─ YES → /map-fast
  |    └─ NO → Continue
  |
  ├─ Is it security-critical or first-time complex feature?
  |    └─ YES → /map-efficient (maximum QA)
  |    └─ NO → Continue
  |
  ├─ Do stakeholders need documented reasoning for decisions?
  |    └─ YES → /map-debate (explicit trade-offs, Opus reasoning)
  |    └─ NO → Continue
  |
  ├─ Do I care about token costs?
  |    └─ NO → /map-efficient (best quality)
  |    └─ YES → /map-efficient ⭐ (RECOMMENDED)
```

### When to Use `--self-moa` Flag

**Add `--self-moa` to /map-efficient for:**
- First implementation of authentication/authorization
- Database migrations affecting multiple tables
- Breaking API changes
- Any feature where failure is costly

```bash
# Standard feature
/map-efficient implement user dashboard

# High-risk feature (use --self-moa for 3-variant synthesis)
/map-efficient --self-moa implement user dashboard with role-based access
```

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
5. MCP tools usage (mcp__mem0__map_tiered_search, context7)
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
/map-efficient implement basic user authentication with login/logout

# Phase 2: Enhanced security
/map-efficient add password reset and email verification to authentication

# Phase 3: Performance tuning
/map-efficient optimize authentication to use Redis session caching
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
/map-efficient implement product search using Elasticsearch.
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

**2. Use `/map-fast` for small, low-risk changes**
- Minimal agent sequence: TaskDecomposer → Actor → Monitor
- Skips: Predictor, Evaluator, Reflector, Curator
- **Token savings: 40-50%** (but no learning!)

### How It Works

Agents automatically use their configured model when invoked via slash commands:

```bash
# Standard workflow - conditional predictor, optional learning via /map-learn
/map-efficient implement authentication  # Recommended for most tasks

# Multi-variant with explicit reasoning
/map-debate design caching strategy      # Complex decisions

# Fast workflow - minimal agents, no learning
/map-fast Update error message wording
```

### Cost Comparison Example

**Scenario:** Implement a feature with 4 subtasks

| Workflow | TaskDecomposer | Actor | Monitor | Predictor | Synthesizer | Total Cost* |
|----------|----------------|-------|---------|-----------|-------------|-------------|
| `/map-efficient` | sonnet | sonnet (4x) | sonnet (4x) | sonnet (0-2x) | skip | ~$0.22 |
| `/map-efficient --self-moa` | sonnet | sonnet (12x) | sonnet (12x) | sonnet (0-2x) | sonnet (4x) | ~$0.45 |
| `/map-debate` | sonnet | sonnet (12x) | sonnet (12x) | sonnet (0-2x) | opus (4x) | ~$0.75 |
| `/map-fast` | sonnet | sonnet (4x) | sonnet (4x) | skip | skip | ~$0.12 |

*Approximate costs based on typical token usage. Learning via `/map-learn` adds ~$0.05-0.10.

**Key differences:**
- `/map-efficient`: Standard workflow, conditional Self-MoA
- `/map-efficient --self-moa`: Forces 3-variant generation + synthesis
- `/map-debate`: 3 variants + Opus arbiter with explicit reasoning
- `/map-fast`: Minimal, NO learning support

---

## Additional Resources

- **[README.md](../README.md)** — Project overview and installation
- **[INSTALL.md](INSTALL.md)** — Detailed installation instructions
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Technical architecture details

---

## 📚 Skills System

MAP includes interactive skills to help you navigate workflows and understand the framework.

### Available Skills

#### map-planning

Persistent session state for MAP workflows using file-based planning.

**When to use planning:**
- 📋 **Long workflows** — Tasks with 50+ tool calls where context may reset
- 📋 **Multi-phase projects** — Work spanning multiple sessions or days
- 📋 **Complex features** — 5+ subtasks that need explicit tracking
- 📋 **Team handoffs** — When another person may need to continue your work
- 📋 **Compliance/audit** — When you need documented decision trail

**When NOT to use:**
- Quick bug fixes (1-3 subtasks)
- Single-session tasks that complete in <30 minutes
- Exploratory work where the goal may change frequently

**How it works:**
- Creates `.map/` directory with branch-scoped plan files
- Files: `task_plan_<branch>.md`, `findings_<branch>.md`, `progress_<branch>.md`
- Prevents goal drift in long workflows (50+ tool calls)
- Enables resumption after context reset

**Initialization:**
```bash
.claude/skills/map-planning/scripts/init-session.sh
```

**Plan file structure:**
```markdown
# Task Plan: [goal]

## Goal
[One sentence describing end state]

## Current Phase
ST-001

## Phases

### ST-001: [title]
**Status:** in_progress
Risk: low|medium|high
Complexity: 1-10
Files: [paths]

Validation:
- [ ] [criterion]

## Terminal State
**Status:** pending
```

**Terminal states:** `complete`, `blocked`, `won't_do`, `superseded`

**Note:** MAP workflows (`/map-efficient`, etc.) automatically use this skill. The `.map/` directory is gitignored.

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
- `map-debate-deep-dive.md` - Multi-variant synthesis, Opus reasoning
- `map-debug-deep-dive.md` - Debugging strategies, error analysis
- `map-learn-deep-dive.md` - Lesson extraction, playbook updates
- `map-release-deep-dive.md` - Release workflow, validation gates

**System architecture:**
- `agent-architecture.md` - How 11 agents orchestrate
- `playbook-system.md` - Knowledge storage, quality scoring
- `cipher-integration.md` - Cross-project learning

### Creating Custom Skills

See `.claude/skills/README.md` for:
- Skill structure (SKILL.md + resources/)
- Trigger configuration (skill-rules.json)
- Integration with auto-activation
- Best practices and examples

---

## 🔒 Security Model: Three-Layer Defense

MAP Framework implements defense-in-depth security via three complementary layers.

### Layer 1: Behavioral Rules (CLAUDE.md)

Guidelines in `.claude/CLAUDE.md` that guide agent behavior:
- NEVER skip mem0 deduplication checks
- NEVER write code as orchestrator
- NEVER commit .env files

**Enforcement:** Soft (relies on agent compliance)

### Layer 2: Permissions (settings.json)

Access control rules in `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "Write(./.env*)",
      "Write(**/*credentials*)",
      "Write(**/*secret*)",
      "Bash(rm:-rf)",
      "Bash(git:push:--force:origin:main)"
    ],
    "allow": [
      "Bash(mapify:*)",
      "Bash(pytest:*)",
      "Bash(make:lint)"
    ]
  }
}
```

**Enforcement:** Medium (tool-level blocking with bypass risk)

### Layer 3: Hooks (Deterministic Enforcement)

PreToolUse and Stop hooks that run before/after tool execution:

| Hook | Type | Purpose |
|------|------|---------|
| `block-secrets.py` | PreToolUse | Blocks access to .env, credentials, private keys |
| `block-dangerous.sh` | PreToolUse | Blocks rm -rf, force push to main, git reset --hard |
| `end-of-turn.sh` | Stop | Lints code, scans for secrets in staging |

**Enforcement:** Hard (deterministic exit codes)

### How the Layers Work Together

```
User: "Edit .env file"

Layer 1 (CLAUDE.md): Agent should know not to edit .env
    ↓ (but agent might miss this)
Layer 2 (settings.json): permissions.deny blocks Edit(./.env*)
    ↓ (but might be bypassed via path traversal)
Layer 3 (block-secrets.py): Hook intercepts, returns exit 2
    → BLOCKED with clear error message
```

### Security Hooks in Detail

#### block-secrets.py (PreToolUse)

Blocks Read/Edit/Write operations on sensitive files:

**Blocked patterns:**
- `.env`, `.env.local`, `.env.production`
- `credentials.json`, `secrets.yaml`
- Private keys (`id_rsa`, `*_private.key`)
- AWS credentials, GCP service accounts

**Example:**
```bash
# Attempting to read .env
Read('.env')
→ Exit 2: "Blocked: sensitive file detected (.env)"
```

#### block-dangerous.sh (PreToolUse)

Blocks dangerous Bash commands:

**Blocked patterns:**
- `rm -rf /` or `rm -rf *`
- `git push --force origin main`
- `git push --force origin master`
- `git reset --hard`

**Allowed:**
- `rm -rf ./node_modules` (scoped deletion)
- `git push --force origin feature-branch` (non-main branch)
- `git reset --soft` (non-hard reset)

#### end-of-turn.sh (Stop)

Quality gate that runs after Claude finishes responding:

**Checks performed:**
1. **Language-specific linting:**
   - Python: runs `ruff` if available
   - Node.js: runs `npm run lint` if available
   - Go: runs `go vet` and `staticcheck`
   - Rust: runs `cargo clippy`

2. **Secret scanning:** Detects hardcoded secrets in staged files
3. **.env check:** Warns if .env files are staged for commit

**Exit codes:**
- `0` = No issues
- `1` = Warnings (non-blocking)
- `2` = Critical issues (blocks and feeds to Claude)

### Customizing Security

**Per-project customization:**

Edit `.claude/settings.json` for project-specific rules:
```json
{
  "permissions": {
    "allow": [
      "Bash(docker:*)",  // Allow docker commands
      "Edit(./config/*)" // Allow editing config
    ]
  }
}
```

**User overrides:**

Create `.claude/settings.local.json` (gitignored) for personal overrides.

---

## 📊 Verification Results and Early Termination

MAP Framework tracks verification results from hooks and supports early workflow termination with the `won't_do` status.

### Verification Results Tracking

The end-of-turn hook (`end-of-turn.sh`) records verification results to `.map/verification_results_<branch>.json`. This provides machine-readable verification status for CI/CD integration.

**File location:** `.map/verification_results_<branch>.json`

**Example content:**
```json
{
  "overall": "pass",
  "recipes": [
    {
      "id": "check_ruff",
      "status": "pass",
      "summary": "ruff passed",
      "duration_ms": 1200
    },
    {
      "id": "check_secrets",
      "status": "skipped",
      "summary": "No staged files to check",
      "duration_ms": 50,
      "skip_reason": "No staged files"
    },
    {
      "id": "check_mypy",
      "status": "fail",
      "summary": "mypy failed",
      "duration_ms": 3500
    }
  ]
}
```

### Recipe Status Values

| Status | Meaning | Example |
|--------|---------|---------|
| `pass` | Check completed successfully | Linter found no issues |
| `fail` | Check found problems | Type errors detected |
| `skipped` | Check was intentionally skipped | No staged files to scan |

### Overall Status Aggregation

The `overall` field follows strict aggregation rules:

| Condition | Overall Status |
|-----------|----------------|
| ANY recipe is `fail` | `fail` |
| ALL recipes are `pass` | `pass` |
| Otherwise (mixed, empty, all skipped) | `unknown` |

### Skipped Status Explained

Checks return `skipped` when they cannot run due to missing prerequisites:

**Common skip scenarios:**
- `check_secrets`: No staged files to check
- `check_mypy`: No mypy configuration found
- `npm lint`: `node_modules` directory missing
- `cargo clippy`: Not in a Rust project

**Example skipped result:**
```json
{
  "id": "check_secrets",
  "status": "skipped",
  "summary": "No staged files to check",
  "duration_ms": 50,
  "skip_reason": "No files were staged for commit"
}
```

### Hooks Contract: When Hooks Block

**Critical:** Hooks only return exit code 2 (blocking) for **security-critical issues**:

| Blocking (Exit 2) | Non-Blocking (Exit 0-1) |
|-------------------|-------------------------|
| Hardcoded secrets in staged files | Linting failures |
| `.env` file staged for commit | Type errors |
| Dangerous commands (rm -rf /, force push main) | Formatting issues |
| Access to credential files | Test failures |

**Why this matters:**
- Exit 2 stops Claude and feeds stderr back for correction
- Exit 1 shows warning but continues
- Exit 0 passes silently

**Design principle:** Quality checks (linting, types) should inform, not block. Only security violations warrant blocking.

### Early Termination with `won't_do` Status

When a user decides to end a workflow early (before all subtasks complete), MAP Framework uses the `won't_do` terminal status.

**Trigger phrases (Russian):**
- "закончили" (finished)
- "остановимся" (let's stop)
- "хватит" (enough)
- "дальше не делай" (don't continue)
- "прекращай" (stop it)
- "закрываем" (we're closing)

> **Note:** Currently only Russian trigger phrases are implemented in `intent_detector.py`. English equivalents are planned for a future release.

**What happens:**
1. All `pending` and `in_progress` subtasks are marked `won't_do`
2. Workflow state records `ended_early` metadata
3. Completed subtasks remain `complete`

### ended_early Structure

When a workflow terminates early, the state file includes:

```json
{
  "terminal_status": "won't_do",
  "ended_early": {
    "by_user": true,
    "reason": "User requested early termination",
    "at_subtask_id": "ST-004"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `by_user` | boolean | Whether user initiated termination |
| `reason` | string | Human-readable reason for termination |
| `at_subtask_id` | string | ID of subtask that was active when terminated |

### Troubleshooting Verification Issues

#### Enable Verbose Hook Logging

```bash
export CLAUDE_HOOK_VERBOSE=true
```

This enables detailed logging from hooks, showing:
- Which checks are running
- Pass/fail status of each check
- Duration of each check
- Skip reasons for skipped checks

#### Artifact Locations

| Artifact | Path | Purpose |
|----------|------|---------|
| Verification results | `.map/verification_results_<branch>.json` | Machine-readable check results |
| Workflow state | `.map/state_<branch>.json` | Current workflow status |
| Repo insight | `.map/repo_insight_<branch>.json` | Project language and suggested checks |
| Task plan | `.map/task_plan_<branch>.md` | Subtask breakdown with validation |
| Progress checkpoint | `.map/progress.md` | Resume checkpoint for context recovery |

#### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Hook not recording results | verification_recorder not installed | Run `pip install mapify-cli` |
| Missing duration_ms | SECONDS variable not working | Ensure bash 4.0+ |
| Wrong branch in filename | Git not initialized | Initialize git or results go to `_default.json` |
| `overall: unknown` unexpectedly | All checks skipped | Run checks manually to verify setup |

#### Manual Verification Recording

For testing or debugging, you can record results manually:

```bash
python -m mapify_cli.verification_recorder <branch> <recipe_id> <status> <summary> [duration_ms]

# Example:
python -m mapify_cli.verification_recorder main check_custom pass "Custom check passed" 1500
```

---

## ⏸️ Workflow Recovery: /map-resume

Resume interrupted MAP workflows from the last checkpoint.

### When to Use

- After context window exhaustion mid-workflow
- After accidental session termination
- After `/clear` that interrupted a workflow
- When returning to an unfinished task

### How It Works

1. **Detects checkpoint:** Checks for `.map/progress.md`
2. **Shows progress:** Displays completed and remaining subtasks
3. **Asks confirmation:** "Resume from last checkpoint?"
4. **Continues workflow:** Resumes Actor→Monitor loop

### Usage Example

```bash
/map-resume
```

**Output:**
```markdown
## Found Incomplete Workflow

**Task:** Implement user authentication with JWT tokens
**Current Phase:** implementation
**Turn Count:** 12

### Progress Overview
3/5 subtasks completed (60%)

### Completed Subtasks ✅
- [x] **ST-001**: Create User model with SQLite schema
- [x] **ST-002**: Implement password hashing with bcrypt
- [x] **ST-003**: Create login API endpoint

### Remaining Subtasks 📋
- [ ] **ST-004**: Implement JWT token generation
- [ ] **ST-005**: Add logout and token refresh endpoints

How would you like to proceed?
[Continue (Recommended)] [View Details] [Abandon]
```

### Auto-Checkpointing

MAP workflows automatically save progress to `.map/progress.md`:

- After decomposition phase
- After each subtask completion
- Before each Actor call

**Checkpoint format:**
```yaml
---
task_plan: "Implement authentication"
current_phase: implementation
turn_count: 12
completed_subtasks:
  - ST-001
  - ST-002
subtasks:
  - id: ST-001
    description: Create User model
    status: complete
  - id: ST-003
    description: Create login endpoint
    status: in_progress
---

# MAP Workflow Progress
[Human-readable markdown body]
```

### Integration with /clear

If you run `/clear` during a workflow:
- Checkpoint is preserved in `.map/progress.md`
- Fresh context starts from checkpoint state
- Use `/map-resume` to continue

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

> **Implementation detail:** Prompt improvement, playbook injection, and workflow suggestions are handled within the `improve-prompt.py` hook (`.claude/hooks/improve-prompt.py`).

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
        "description": "Enhance prompts with clarification and playbook context",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/improve-prompt.py"
          }
        ]
      }
    ]
  }
}
```

### Other Active Hooks

MAP Framework includes additional hooks for security and quality:

| Hook | Event | Purpose |
|------|-------|---------|
| `improve-prompt.py` | UserPromptSubmit | Prompt clarification and enhancement |
| `block-secrets.py` | PreToolUse | Block access to sensitive files |
| `block-dangerous.sh` | PreToolUse | Block dangerous shell commands |
| `end-of-turn.sh` | Stop | Quality gates (linting, secret scanning) |

**Configuration:** See `.claude/settings.hooks.json` for hook configuration.

**Security hooks:** See [Security Model: Three-Layer Defense](#-security-model-three-layer-defense) for details.

---
