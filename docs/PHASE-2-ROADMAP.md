# MAP Framework: Phase 2 Context Engineering - Roadmap

> **Status:** 📋 PLANNING
> **Start Date:** TBD (after Phase 1 completion on 2025-10-18)
> **Prerequisites:** Phase 1 Complete ✅
> **Estimated Duration:** 10 weeks (2.5 months)
> **Source:** [CONTEXT-ENGINEERING-IMPROVEMENTS.md](./CONTEXT-ENGINEERING-IMPROVEMENTS.md)

## Executive Summary

Phase 2 builds on Phase 1 foundation (Recitation, Logging, Playbook Limit, Template Optimization) to add stateful workflow management, performance optimization, and retrieval accuracy improvements.

### Phase 2 Goals

1. **Workflow Resilience**: Enable resumption from checkpoints after failures
2. **Performance**: Reduce MCP tool latency by 50-80% via caching
3. **Retrieval Accuracy**: Improve playbook pattern matching precision
4. **Few-Shot Bias Reduction**: Vary pattern presentation to prevent template imitation

### Priority Order (Impact × Complexity)

| Priority | Item | Impact | Complexity | Timeline |
|----------|------|--------|------------|----------|
| 1 | **Checkpoints (2.1)** | HIGH | Medium | 2-3 weeks |
| 2 | **MCP Caching (2.2)** | MEDIUM-HIGH | Low | 1-2 weeks |
| 3 | **Keyword+Semantic Search (2.4)** | MEDIUM | Low-Medium | 1-2 weeks |
| 4 | **Playbook Variation (2.3)** | LOW-MEDIUM | Medium | 2-3 weeks |

**Total**: ~10 weeks

---

## Phase 2.1: Checkpoints (Stateful Workflow Management)

### Priority: 🔴 HIGH IMPACT

**Why First:**
- Builds directly on RecitationManager architecture (workflow state already tracked)
- Solves critical pain point: workflow failures require full restart
- Enables debugging by reproducing exact state at failure point
- Prerequisite for Phase 3.2 (Enhanced Error Recovery)

### Problem Statement

**Current State (Phase 1):**
- RecitationManager tracks current workflow state in `.map/current_plan.json`
- State is volatile: cleared on workflow completion or failure
- Workflow failure at subtask 5/8 → must restart from subtask 1
- No historical state persistence for debugging or resumption

**Pain Points:**
- Long workflows (8+ subtasks) costly to restart from beginning
- Transient failures (API timeout, rate limit) waste progress
- Debugging difficult without historical state snapshots
- Cannot analyze "what state led to this failure"

### Solution: MapStateManager

**Component**: `src/mapify_cli/state_manager.py` (estimated 350-400 lines)

**Architecture**:
```python
class MapStateManager:
    """
    Manages workflow checkpoints for resumption and debugging.

    Key features:
    1. Automatic checkpoint creation after each subtask completion
    2. Checkpoint includes: subtask results, iteration history, timestamps, Actor/Monitor outputs
    3. Resume from last successful checkpoint on workflow restart
    4. Query historical checkpoints for debugging
    5. Integration with RecitationManager for seamless state restoration
    """

    def save_checkpoint(self, task_id: str, subtask_id: int, state: Dict) -> Path:
        """Save workflow checkpoint after subtask completion"""

    def load_checkpoint(self, task_id: str, subtask_id: Optional[int] = None) -> Dict:
        """Load checkpoint (defaults to latest if subtask_id not specified)"""

    def list_checkpoints(self, task_id: str) -> List[CheckpointMetadata]:
        """List all checkpoints for a task"""

    def resume_workflow(self, task_id: str) -> Tuple[int, Dict]:
        """Resume from last checkpoint, returns (subtask_id, state)"""
```

### Implementation Plan

#### Week 1: Core Checkpoint Infrastructure

**Tasks:**
1. Create `MapStateManager` class with save/load methods
2. Define checkpoint schema (JSON format)
3. Implement `.map/checkpoints/<task_id>/` directory structure
4. Add CLI interface: `python -m mapify_cli.state_manager save/load/resume`
5. Unit tests for checkpoint persistence

**Checkpoint Schema:**
```json
{
  "task_id": "feat_auth_1234567890",
  "checkpoint_id": "checkpoint_003",
  "subtask_id": 3,
  "subtask_description": "Add JWT token generation",
  "status": "completed",
  "timestamp": "2025-10-25T14:35:00Z",
  "iteration_count": 1,
  "actor_output": {"approach": "...", "code_changes": [...]},
  "monitor_verdict": "approved",
  "predictor_analysis": {"affected_files": [...], "breaking_changes": []},
  "evaluator_scores": {"overall_score": 8.5, "recommendation": "proceed"},
  "files_modified": ["src/auth/jwt.py", "tests/test_jwt.py"],
  "duration_seconds": 45,
  "metadata": {
    "recitation_plan_snapshot": {...},  // Full current_plan.json at this point
    "playbook_patterns_used": ["impl-0001", "arch-0002"],
    "total_tokens_used": 15000
  }
}
```

**Acceptance Criteria:**
- ✅ Checkpoint saved to `.map/checkpoints/<task_id>/checkpoint_<subtask_id: integer>.json`
- ✅ Checkpoint includes all required fields (schema above)
- ✅ Load checkpoint returns exact state
- ✅ CLI commands work: `save`, `load`, `list`, `resume`

#### Week 2: Integration with /map-feature Workflow

**Tasks:**
1. Update `/map-feature.md` workflow to call `state_manager save` after each subtask
2. Add resume logic: check for existing checkpoints before starting workflow
3. Integrate with RecitationManager: restore plan state from checkpoint
4. Update Actor template to show "Resumed from checkpoint X" if applicable

**Workflow Integration Points:**

```bash
# Step 0 (NEW): Check for existing checkpoints
CHECKPOINTS=$(python -m mapify_cli.state_manager list "$TASK_ID")

if [ -n "$CHECKPOINTS" ]; then
  echo "Found existing checkpoints. Resume? (y/n)"
  read -r RESUME

  if [ "$RESUME" = "y" ]; then
    # Resume from last checkpoint
    RESUME_DATA=$(python -m mapify_cli.state_manager resume "$TASK_ID")
    START_SUBTASK=$(echo "$RESUME_DATA" | jq -r '.next_subtask_id')

    # Restore RecitationManager state
    mapify recitation restore "$TASK_ID" "$(echo "$RESUME_DATA" | jq -c '.recitation_plan')"

    echo "Resuming from subtask $START_SUBTASK"
  fi
fi

# ... TaskDecomposer, create plan (if not resuming) ...

# Execute subtasks (starting from START_SUBTASK if resuming)
for subtask_id in $(seq $START_SUBTASK $TOTAL_SUBTASKS); do
  # ... Actor, Monitor, Predictor, Evaluator loop ...

  # NEW: Save checkpoint after subtask completion
  python -m mapify_cli.state_manager save "$TASK_ID" "$subtask_id" '{
    "actor_output": '"$ACTOR_OUTPUT"',
    "monitor_verdict": '"$MONITOR_VERDICT"',
    "files_modified": '"$FILES_MODIFIED"'
  }'
done
```

**Acceptance Criteria:**
- ✅ Checkpoint automatically saved after each subtask completion
- ✅ User prompted to resume if checkpoints exist for task_id
- ✅ Resume loads correct subtask and restores RecitationManager state
- ✅ Actor sees "Resumed from checkpoint" notice in recitation plan

#### Week 3: Testing, Documentation, Edge Cases

**Tasks:**
1. Integration test: Full workflow with checkpoint save/resume
2. Edge case handling:
   - Checkpoint corruption (JSON parse error)
   - Checkpoint version mismatch (schema evolution)
   - Disk space issues
   - Permission errors
3. Documentation:
   - Update `PHASE-1-COMPLETION-SUMMARY.md` with Phase 2.1 progress
   - Add troubleshooting guide for checkpoint issues
   - CLI usage examples
4. Cleanup strategy: Auto-delete checkpoints older than 7 days

**Acceptance Criteria:**
- ✅ Integration test passes: workflow fails at subtask 4, resumes successfully from checkpoint
- ✅ Graceful error handling for all edge cases
- ✅ Documentation complete with examples
- ✅ Cleanup cron job/command: `python -m mapify_cli.state_manager cleanup --older-than 7d`

### Expected Benefits

**Before Phase 2.1:**
- Workflow failure at subtask 6/8 → restart from subtask 1
- Lost work: ~60-80% of progress
- Time waste: 30-45 minutes

**After Phase 2.1:**
- Workflow failure at subtask 6/8 → resume from checkpoint 5
- Lost work: ~12% (only current subtask)
- Time waste: 3-5 minutes (only retry subtask 6)

**Impact:** 80-90% reduction in rework time for failed workflows

### Dependencies

- ✅ RecitationManager (Phase 1.1) - provides workflow state structure
- ✅ MapWorkflowLogger (Phase 1.2) - checkpoint saves can log events
- ⏸️ Phase 3.2 (Enhanced Error Recovery) - will use checkpoints for smart retry

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Checkpoint size bloat (large Actor outputs) | Compress JSON, limit Actor output storage to summary |
| Disk space usage | Auto-cleanup after 7 days, configurable retention |
| State restoration bugs | Extensive integration tests, schema versioning |
| Resume confusion (which checkpoint?) | Clear CLI output, default to latest, allow manual selection |

---

## Phase 2.2: MCP Tool Caching

### Priority: 🟠 MEDIUM-HIGH IMPACT

**Why Second:**
- No dependencies on other Phase 2 items (can implement independently)
- Measurable performance improvement (latency reduction)
- Low complexity (simple caching layer)
- Improves user experience immediately

### Problem Statement

**Current State:**
- Every `context7.get-library-docs` call → HTTP request to external service
- Every `deepwiki.read_wiki_contents` call → Network round-trip
- Repeated documentation lookups (e.g., "Next.js routing" asked 3 times in workflow)
- Latency: 2-5 seconds per MCP call
- Offline development impossible (requires network)

**Pain Points:**
- Slow workflow execution when using MCP tools repeatedly
- Wasted API quota for identical queries
- Cannot work offline (plane, coffee shop, etc.)
- Cost: external API calls may have usage fees

### Solution: MCPCacheManager

**Component**: `src/mapify_cli/mcp_cache_manager.py` (estimated 200-250 lines)

**Architecture:**
```python
class MCPCacheManager:
    """
    Caching layer for MCP tool calls (context7, deepwiki, cipher).

    Key features:
    1. Hash-based cache keys (query + tool + version)
    2. TTL-based expiration (default: session lifetime or 24h)
    3. Optional persistent cache (across sessions)
    4. Cache hit/miss logging via MapWorkflowLogger
    5. CLI interface for cache management
    """

    def get_cached(self, tool: str, query: str) -> Optional[Dict]:
        """Retrieve from cache if available and not expired"""

    def store(self, tool: str, query: str, response: Dict, ttl_hours: int = 24):
        """Store MCP response in cache"""

    def invalidate(self, tool: Optional[str] = None, pattern: Optional[str] = None):
        """Invalidate cache entries (by tool or query pattern)"""

    def stats(self) -> CacheStats:
        """Return cache hit rate, size, entries"""
```

### Implementation Plan

#### Week 1: Core Caching Infrastructure

**Tasks:**
1. Create `MCPCacheManager` class with get/store/invalidate methods
2. Implement cache key hashing (SHA256 of tool + query)
3. Directory structure: `.map/cache/<tool>/<hash>.json`
4. TTL implementation (store timestamp, check on retrieval)
5. Unit tests for cache hit/miss scenarios

**Cache Entry Schema:**
```json
{
  "cache_key": "sha256_hash_of_tool_and_query",
  "tool": "context7",
  "query": {
    "context7CompatibleLibraryID": "/vercel/next.js",
    "topic": "routing"
  },
  "response": {
    "documentation": "Next.js routing documentation...",
    "code_examples": [...]
  },
  "cached_at": "2025-10-26T10:00:00Z",
  "expires_at": "2025-10-27T10:00:00Z",
  "hits": 3,
  "last_accessed": "2025-10-26T14:30:00Z"
}
```

**Acceptance Criteria:**
- ✅ Cache hit returns stored response
- ✅ Cache miss returns None
- ✅ Expired entries not returned (TTL respected)
- ✅ CLI works: `python -m mapify_cli.mcp_cache_manager stats/clear`

#### Week 2: MCP Tool Integration

**Tasks:**
1. Create wrapper functions for MCP calls:
   - `call_context7_cached(library_id, topic)`
   - `call_deepwiki_cached(repo_name, query)`
   - `call_cipher_cached(query)`
2. Update workflow documentation to use cached variants
3. Logging: log cache hits/misses via MapWorkflowLogger
4. Configuration: `.map/cache_config.json` for TTL, enable/disable

**Integration Example:**

```python
# Before (direct MCP call)
result = mcp__context7__get_library_docs(library_id="/vercel/next.js", topic="routing")

# After (with caching)
from mapify_cli.mcp_cache_manager import call_context7_cached

result = call_context7_cached(library_id="/vercel/next.js", topic="routing")
# If cached: returns immediately (0.1s)
# If not cached: calls MCP, stores result, returns (2-5s)
```

**Acceptance Criteria:**
- ✅ Wrapper functions check cache before MCP call
- ✅ Cache misses call actual MCP tool and store result
- ✅ Cache hits logged: `{"event": "cache_hit", "tool": "context7", "latency_ms": 5}`
- ✅ Cache config respected: TTL, enable/disable

---

## Phase 2.3: Playbook Pattern Variation

### Priority: 🟡 LOW-MEDIUM IMPACT

**Why Fourth:**
- More valuable when playbook grows (currently 11 bullets, target 30+)
- Complex implementation (pattern reformulation logic)
- Lower urgency than checkpoints/caching

### Problem Statement

**Current State (Phase 1.3):**
- PlaybookManager returns top-5 most relevant patterns
- Patterns always shown in same format (content + code_example)
- LLM may develop few-shot bias: imitate pattern style rather than learn concept
- All patterns use similar structure (problem → solution → code)

**Few-Shot Bias Example:**
```markdown
# Pattern shown to Actor (always same format):

## Pattern impl-0001: Multi-Agent Workflow Documentation

**Content:** When documenting analysis findings...

**Code Example:**
```python
analysis = {
    "findings": [...],
    "implementation_plan": {...}
}
```

# Actor starts imitating this exact structure:
actor_output = {
    "findings": [...],  # Copied structure, not learned concept
    "implementation_plan": {...}
}
```

### Solution: Pattern Format Randomization

**Enhancement**: Modify `PlaybookManager.get_relevant_bullets()` to vary pattern presentation

**Randomization Strategies:**

1. **Format Variation:**
   - Code example (current default)
   - Pseudocode abstraction
   - Natural language advice
   - Checklist format

2. **Order Randomization:**
   - Shuffle pattern order (prevent position bias)
   - Alternate "positive examples" and "anti-patterns"

3. **Emphasis Variation:**
   - Sometimes emphasize "why" (rationale)
   - Sometimes emphasize "how" (implementation)
   - Sometimes emphasize "when" (use cases)

### Implementation Plan

**Week 1-2: Format Reformulation Logic**

**Tasks:**
1. Add `format_pattern()` method to PlaybookManager
2. Implement 4 format types:
   - `code_example` (current default)
   - `pseudocode` (abstract algorithm)
   - `natural_language` (plain English advice)
   - `checklist` (step-by-step verification)
3. Random format selection per pattern
4. Unit tests for each format type

**Example Reformulations:**

```python
# Original (code_example):
{
  "content": "Multi-Agent Workflow Documentation: Include implementation plans...",
  "code_example": "analysis = {'findings': [...], 'implementation_plan': {...}}"
}

# Reformulated (pseudocode):
{
  "content": "Multi-Agent Workflow Documentation",
  "format": "pseudocode",
  "presentation": """
    FOR EACH analysis_finding:
      IF finding lacks implementation_details:
        ADD implementation_plan WITH:
          - Current state (file paths, line numbers)
          - Proposed changes (specific code modifications)
          - Verification criteria
  """
}

# Reformulated (natural_language):
{
  "content": "Multi-Agent Workflow Documentation",
  "format": "advice",
  "presentation": """
    When documenting findings, always pair each problem with a concrete solution.
    Monitors need actionable plans to verify completion, not just abstract recommendations.
    Include WHERE to change (file paths), WHAT to change (before/after code), and
    HOW to verify (test criteria).
  """
}

# Reformulated (checklist):
{
  "content": "Multi-Agent Workflow Documentation",
  "format": "checklist",
  "presentation": """
    Before finalizing analysis document:
    ☐ Each finding has specific file path and line numbers
    ☐ Proposed changes include before/after code examples
    ☐ Verification criteria are testable
    ☐ Rationale explains why this approach was chosen
  """
}
```

**Week 3: Integration and A/B Testing**

**Tasks:**
1. Update Actor template to handle varied formats
2. A/B test: Same workflow with/without variation
3. Measure few-shot bias via Monitor feedback analysis
4. Documentation: explain pattern variation in README

**Acceptance Criteria:**
- ✅ Patterns randomized each retrieval
- ✅ Actor handles all 4 format types correctly
- ✅ A/B test shows reduced template imitation

---

## Phase 2.4: Keyword + Semantic Search

### Priority: 🟢 MEDIUM IMPACT

**Why Third:**
- Improves Phase 1.3 (playbook retrieval accuracy)
- Low-Medium complexity
- Measurable metric: retrieval precision/recall

### Problem Statement

**Current State (Phase 1.3):**
- PlaybookManager uses pure semantic search (embeddings + cosine similarity)
- Query: "error handling" → may return patterns about "exception logging", "retry logic", "circuit breakers" (all somewhat similar)
- No keyword filtering → off-topic results may rank high if semantically similar

**Example:**
```python
# Query: "JWT token validation"

# Pure semantic results (top-5):
1. impl-0005: API authentication (similarity: 0.85) ← relevant
2. sec-0012: Token expiration handling (similarity: 0.82) ← relevant
3. impl-0008: Session management (similarity: 0.78) ← somewhat relevant
4. arch-0004: Service communication (similarity: 0.75) ← off-topic (but mentions "tokens")
5. test-0009: Integration testing (similarity: 0.72) ← off-topic

# Desired: Only results mentioning "JWT" or "validation" keywords
```

### Solution: Hybrid Retrieval (Keyword + Semantic)

**Enhancement**: Combine keyword matching with semantic search for better precision

**Algorithm:**
```python
def hybrid_search(query: str, top_k: int = 5):
    # 1. Keyword filter (pre-filter)
    keywords = extract_keywords(query)  # ["JWT", "token", "validation"]
    candidates = filter_by_keywords(all_patterns, keywords, min_matches=1)

    # 2. Semantic ranking (on filtered candidates)
    semantic_scores = compute_similarity(query, candidates)

    # 3. Hybrid score (weighted combination)
    for pattern in candidates:
        keyword_score = keyword_match_ratio(pattern, keywords)  # 0.0-1.0
        semantic_score = semantic_scores[pattern.id]  # 0.0-1.0

        pattern.hybrid_score = (
            KEYWORD_WEIGHT * keyword_score +
            SEMANTIC_WEIGHT * semantic_score
        )

    # 4. Return top-k by hybrid score
    return sorted(candidates, key=lambda p: p.hybrid_score, reverse=True)[:top_k]
```

### Implementation Plan

**Week 1: Keyword Extraction and Matching**

**Tasks:**
1. Add keyword extraction: tokenize, lowercase, remove stopwords
2. Keyword matching: exact match, partial match, stem matching
3. Keyword scoring: ratio of matched keywords to total
4. Configuration: keyword/semantic weights (default 0.3/0.7)

**Week 2: Hybrid Search Integration**

**Tasks:**
1. Modify `PlaybookManager.get_relevant_bullets()` to use hybrid search
2. A/B testing: compare pure semantic vs hybrid retrieval
3. Tune weights based on retrieval precision metrics
4. Add logging: which patterns matched on keywords vs semantics

**Acceptance Criteria:**
- ✅ Hybrid search returns more relevant patterns than pure semantic
- ✅ Keyword filter reduces off-topic results
- ✅ Weights configurable in `.claude/playbook.db`

---

## Success Metrics - Phase 2

### Performance Metrics

| Metric | Before Phase 2 | After Phase 2 | Target |
|--------|----------------|---------------|--------|
| **Workflow Resume Time** | Full restart (100%) | Resume from checkpoint | 80-90% reduction |
| **MCP Call Latency** | 2-5s per call | 0.1s (cache hit) | 50-80% reduction |
| **Playbook Retrieval Precision** | ~70% (pure semantic) | ~85% (hybrid) | +15% improvement |
| **Few-Shot Bias** | Moderate (template imitation) | Low (varied formats) | Qualitative improvement |

### Workflow Quality Metrics

| Metric | Phase 1 | Phase 2 Target |
|--------|---------|----------------|
| **Monitor Approval Rate** | 80% first attempt | 85-90% (better patterns) |
| **Average Iterations per Subtask** | ~2-3 | ~1.5-2 (checkpoints prevent rework) |
| **Token Usage** | 9.6% reduction (Phase 1) | Additional 5-10% (caching, variation) |
| **Workflow Success Rate** | 70-80% | 85-90% (resumption from failures) |

### Infrastructure Metrics

| Component | Lines of Code | Complexity | Maintenance |
|-----------|---------------|------------|-------------|
| MapStateManager | 350-400 | Medium | Low (stable API) |
| MCPCacheManager | 200-250 | Low | Low (simple caching) |
| PlaybookManager (enhanced) | +100-150 | Medium | Medium (format logic) |
| **Total Phase 2** | ~650-800 lines | Medium | Low-Medium |

---

## Timeline & Resource Allocation

### Week-by-Week Plan

**Weeks 1-3: Phase 2.1 (Checkpoints)**
- Week 1: Core infrastructure
- Week 2: Workflow integration
- Week 3: Testing and documentation

**Weeks 4-5: Phase 2.2 (MCP Caching)**
- Week 4: Caching layer
- Week 5: MCP integration

**Weeks 6-7: Phase 2.4 (Keyword+Semantic)**
- Week 6: Keyword extraction and matching
- Week 7: Hybrid search integration

**Weeks 8-10: Phase 2.3 (Playbook Variation)**
- Weeks 8-9: Format reformulation logic
- Week 10: Integration and A/B testing

### Dependencies & Parallelization

```
Phase 1 ✅ (Complete)
    ↓
Phase 2.1 (Checkpoints) ← Must go first (builds on RecitationManager)
    ↓
Phase 2.2 (Caching) ← Can run in parallel with 2.3/2.4
Phase 2.4 (Keyword Search) ← Can run in parallel with 2.2
Phase 2.3 (Variation) ← Can run in parallel with 2.2/2.4
```

**Parallelization Opportunity**: After Phase 2.1 complete, can run 2.2, 2.3, 2.4 simultaneously if multiple contributors available.

---

## Risks & Mitigation Strategies

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Checkpoint state bloat | Medium | Medium | Compression, retention policy, summary storage |
| Cache invalidation bugs | Medium | Low | TTL expiration, manual invalidation CLI, version keys |
| Pattern variation degrades quality | High | Low | A/B testing, Monitor evaluation, rollback capability |
| Hybrid search slower than semantic | Low | Medium | Cache keyword extractions, optimize matching algorithm |
| Scope creep (additional features) | Medium | High | Strict adherence to roadmap, defer Phase 3 items |

---

## Success Criteria - Phase 2 Complete

Phase 2 is considered complete when:

- ✅ **All 4 items implemented**: 2.1, 2.2, 2.3, 2.4
- ✅ **Unit tests pass**: >80% coverage for new components
- ✅ **Integration tests pass**: Full workflow with checkpoints, caching, hybrid retrieval
- ✅ **Documentation complete**: README updated, troubleshooting guide added
- ✅ **Performance targets met**: Metrics table above shows >= target values
- ✅ **No regressions**: Phase 1 features still work, playbook growth continues
- ✅ **User acceptance**: At least 2 real workflows tested with Phase 2 features

---

## Next Steps After Phase 2

### Phase 3 Preview

**Phase 3.1: Reflector/Curator Parallelism**
- Background workflow learning (non-blocking)
- Async playbook updates
- Timeline: 3-4 weeks

**Phase 3.2: Enhanced Error Recovery**
- Smart retry strategies using checkpoint analysis
- Automatic error pattern detection
- Timeline: 2-3 weeks

**Phase 3.3: Temperature Configuration**
- Per-agent temperature tuning
- Determinism vs creativity trade-offs
- Timeline: 1-2 weeks

**Phase 3.4: Monitoring Dashboard**
- Real-time workflow visualization
- Metrics dashboard for token usage, latency, success rate
- Timeline: 2-3 weeks

**Total Phase 3**: ~8-12 weeks

---

## References

- [CONTEXT-ENGINEERING-IMPROVEMENTS.md](./CONTEXT-ENGINEERING-IMPROVEMENTS.md) - Complete roadmap (Phases 1-4)
- [PHASE-1-COMPLETION-SUMMARY.md](./PHASE-1-COMPLETION-SUMMARY.md) - Phase 1 results and lessons
- [RECITATION-INTEGRATION-VERIFICATION.md](./RECITATION-INTEGRATION-VERIFICATION.md) - Architecture patterns from Phase 1

---

**Document Status:** 📋 Planning
**Last Updated:** 2025-10-18
**Author:** MAP Framework Team
**Next Review:** After Phase 2.1 completion (checkpoint milestone)
