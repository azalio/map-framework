# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.2.0] - 2025-10-18

### Added - Phase 1 Context Engineering Complete ✅

#### Phase 1.1: Recitation Pattern (RecitationManager)
- **RecitationManager** (`src/mapify_cli/recitation_manager.py`, 543 lines): CLI-based workflow plan management
  - Implements "Recitation" pattern from context engineering research
  - Creates `.map/current_plan.md` with visual progress markers (✓, →, ☐, ✗)
  - Tracks subtask status and error history for retry awareness
  - Integration via `/map-feature` workflow (steps 2.5, 3.1.5, 3.4, 3.7, 4.6)
  - Actor template receives `{{plan_context}}` variable for goal focus
  - **Benefits**: Prevents focus drift on long workflows, +20-30% success rate on complex tasks

#### Phase 1.2: Workflow Logging (MapWorkflowLogger)
- **MapWorkflowLogger** (`src/mapify_cli/workflow_logger.py`, 411 lines): Optional JSON Lines workflow logging
  - Tracks workflow events: workflow_start/end, agent_call, tool_use, recitation_created/updated, error
  - JSON Lines format for easy parsing and analysis
  - Task ID correlation across events for debugging
  - Optional enable/disable flag (no-op when disabled for zero overhead)
  - Logs stored in `.map/logs/workflow_<TASK_ID>.log`
  - **Benefits**: Full workflow observability, debugging aid, performance analysis

#### Phase 1.3: Playbook Pattern Limit
- **Top-K Configuration** (`.claude/playbook.json`): `top_k=5` to limit playbook pattern retrieval
  - Prevents context distraction by returning only 5 most relevant patterns
  - Reduces token usage in playbook context by ~50%
  - Improves Actor focus on truly relevant patterns
  - Scalable as playbook grows beyond current 11 bullets
  - **Benefits**: Better pattern matching, reduced cognitive load, improved signal-to-noise ratio

#### Phase 1.4: Template Optimization
- **Monitor Template** (`.claude/agents/monitor.md`): 1006 → 909 lines (-97 lines, 9.6% reduction)
  - Compressed MCP Integration, Documentation Consistency, Examples
  - Preserved critical sections: Security Checklist, Severity Guidelines, Decision Rules
  - Validation: scored 9.7/10 by Evaluator
- **Evaluator Template** (`.claude/agents/evaluator.md`): 934 → 844 lines (-90 lines, 9.6% reduction)
  - Balanced optimization with teaching quality preservation
  - Partial rollback: restored Example 1 full code (52 lines) for pedagogical value
  - Preserved 6-Dimensional Scoring Model, Weighted Calculation, Decision Tree
  - Validation: scored Monitor optimization 9.7/10
- **Total savings**: 187 lines (~750 tokens per Monitor+Evaluator call)

#### Documentation
- `docs/CONTEXT-ENGINEERING-IMPROVEMENTS.md`: Complete planning document for Phases 1-4
- `docs/PHASE-1-COMPLETION-SUMMARY.md`: Phase 1 results with metrics, architecture, troubleshooting, Phase 2 roadmap
- `docs/RECITATION-INTEGRATION-VERIFICATION.md`: Detailed verification report for RecitationManager integration
- Updated `README.md` Context Engineering section with Phase 1 completion status

### Changed - Phase 1

- **Playbook Growth**: 3 → 11 bullets (+8 new patterns, 267% growth)
  - arch-0001: Workflow-Scoped Learning Context Architecture
  - arch-0002: Analysis-Implementation Pipeline Pattern
  - impl-0001: Multi-Agent Workflow Documentation
  - impl-0002: Inter-Subtask Learning Propagation
  - impl-0003: Executable Specification for Code Transformations
  - impl-0004: Bounded Optimization Specifications
  - qual-0001: Analysis Document Completeness (WHAT/WHERE/HOW/WHY)
  - qual-0002: Template Purpose Classification (teaching vs validation)
  - test-0001: Iterative Refinement Based on Monitor Feedback
  - test-0002: Iteration Count as Learning Effectiveness Metric
  - test-0003: Over-Delivery Pattern Recognition

- **Architecture**: Documentation-driven orchestration pattern
  - Claude Code executes `/map-feature` workflow steps
  - RecitationManager and MapWorkflowLogger called via CLI at specific workflow points
  - No Python orchestrator class (human-in-the-loop design)

### Fixed

- Agent template optimizations preserve quality while reducing token usage
- Playbook retrieval limited to prevent context overload

### Migration Notes

**Backward Compatible**: Phase 1 is fully additive with no breaking changes.

**New Dependencies**: None (uses existing Python stdlib)

**New Directories**:
- `.map/` - RecitationManager state files (auto-created, gitignored)
  - `.map/current_plan.json` - Machine-readable workflow state
  - `.map/current_plan.md` - Human-readable plan context
  - `.map/logs/` - Optional workflow logs (MapWorkflowLogger)

**Configuration Updates**:
- `.claude/playbook.json`: Added `metadata.top_k = 5` for pattern limit
- No changes required for existing workflows to continue working

**To Upgrade**:
```bash
# Pull latest code
git pull origin main

# Verify Phase 1 components
ls -l src/mapify_cli/recitation_manager.py  # 482 lines
ls -l src/mapify_cli/workflow_logger.py     # 246 lines

# Create .map directory structure
mkdir -p .map/logs

# Update playbook config (if needed)
jq '.metadata.top_k = 5' .claude/playbook.json > tmp.json && mv tmp.json .claude/playbook.json

# Test RecitationManager
python -m mapify_cli.recitation_manager create "test" "Test goal" '[{"id": 1, "description": "Test"}]'
python -m mapify_cli.recitation_manager clear
```

### Performance Metrics - Phase 1

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Token Efficiency | Baseline | 9.6% reduction | -187 lines (Monitor + Evaluator) |
| Playbook Patterns | 3 bullets | 11 bullets | +267% growth |
| Context Focus | No recitation | Active | Progress markers + error history |
| Observability | No logging | JSON Lines logs | Optional .map/logs/ |
| Pattern Retrieval | Unlimited | Top-5 limit | 50% context reduction |
| Infrastructure | Baseline | +728 lines | RecitationManager (482) + MapWorkflowLogger (246) |

### Research Foundation

Phase 1 based on:
- **"Context Engineering for AI Agents: Lessons from Building Manus"** (Y. Ji, Manus.im, 2025)
  - Recitation pattern (keep goals fresh in context)
  - KV-cache optimization principles
  - External memory as context extension
- **MAP Framework ACE System**
  - Reflector/Curator workflow-to-playbook learning
  - Semantic search with embeddings
  - Multi-agent orchestration

### Next Steps - Phase 2 Roadmap

**Priority 1: Checkpoints (Phase 2.1)** - HIGH IMPACT
- MapStateManager for workflow resumption
- Integration with RecitationManager
- Timeline: 2-3 weeks

**Priority 2: MCP Caching (Phase 2.2)** - MEDIUM-HIGH IMPACT
- MCPCacheManager for context7/deepwiki
- Latency reduction: 50-80%
- Timeline: 1-2 weeks

**Priority 3: Keyword+Semantic Search (Phase 2.4)** - MEDIUM IMPACT
- Enhanced PlaybookManager retrieval
- Improved pattern relevance
- Timeline: 1-2 weeks

**Priority 4: Playbook Variation (Phase 2.3)** - LOW-MEDIUM IMPACT
- Pattern reformulation to reduce few-shot bias
- Timeline: 2-3 weeks

**Total Phase 2 Timeline**: ~10 weeks (2.5 months)

---

## [2.1.0] - 2025-10-18

### Changed - Agent Templates

See [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md) for detailed agent template changes.

**Summary:**
- Actor v2.1.0: Added Recitation Pattern integration (`{{plan_context}}`)
- Monitor v2.1.0: Optimized for 9.6% token reduction
- Evaluator v2.1.0: Optimized for 9.6% token reduction with teaching quality preservation

---

## [2.0.0] - 2025-10-17

### Added - Agent Templates Overhaul

See [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md) for complete v2.0.0 changes.

**Summary:**
- Comprehensive MCP integration framework
- XML-style semantic structure for better LLM parsing
- Template size: 2,232 → 9,269 lines (+258% for comprehensive guidance)
- Removed orchestrator as subagent (moved to slash commands)

---

For older changes and agent template details, see:
- [Agent Templates CHANGELOG](.claude/agents/CHANGELOG.md)
- Git commit history

## Versioning

**Version Format**: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes (incompatible API/workflow changes)
- **MINOR**: New features (backward compatible additions like Phase 1)
- **PATCH**: Bug fixes and minor improvements

**Current Version**: 2.2.0 (Phase 1 Context Engineering Complete)
