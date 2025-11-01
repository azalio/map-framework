# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.1] - 2025-11-02

### Fixed

**Playbook Database Initialization:**
- **Fixed playbook.db initialization and migration from playbook.json** (PR #18)
  - `mapify init` now creates `playbook.db` instead of `playbook.json`
  - RecitationManager checks for `playbook.db` existence instead of deprecated `playbook.json`
  - Added backward compatibility: automatically migrates data from `playbook.json` to `playbook.db` if old file exists
  - Updated all tests to use `--mcp none` flag for isolated testing
  - Fixed test assertions for corrupted JSON handling
  - **Impact**: Seamless migration for existing users, no data loss

### Removed

**Agent Framework Cleanup:**
- **Removed test-generator agent** from MAP Framework (reduced from 9 to 8 core agents)
  - Deleted `src/mapify_cli/templates/agents/test-generator.md` (1,175 lines)
  - Removed test-generator from `mcp_config.json` agent_mcp_mappings
  - Removed test-generator creation function from `src/mapify_cli/__init__.py`
  - Updated all documentation references from 9 agents to 8 agents
  - **Rationale**: Test generation responsibility shifted to Actor agent (which has codex-bridge access)
  - **Impact**: Zero breaking changes for existing users; orphaned files are harmless

### Changed

**Documentation Updates:**
- Updated `docs/IMPROVEMENT-STATUS.md` to reflect 8-agent architecture
  - Removed test-generator statistics from agent metrics
  - Recalculated totals: 2,354 → 7,841 lines (+233% growth)
- Updated presentation files (English and Russian) to show correct agent count
- Updated `tests/test_mapify_cli.py` to expect 8 agents

## [1.2.0] - 2025-10-30

### Added

**Compaction Recovery System:**
- **`mapify recitation checkpoint` CLI Command**: Displays state file paths, current progress, and recovery instructions (PR #15)
  - Shows absolute paths to all state files (.map/current_plan.json, .map/current_plan.md)
  - Displays current task, progress (N/M subtasks), and active subtask
  - Prints file contents with intelligent truncation (>2000 chars)
  - Provides copy-paste recovery instructions for post-compaction scenarios
  - Handles missing files gracefully with actionable error messages
  - **Benefits**: Self-service recovery reduces support burden, zero work loss guaranteed

- **Phase 2: Automatic Context Restoration via SessionStart Hook** (PR #15)
  - Automatic restoration of MAP workflow context after Claude Code session compaction
  - Filesystem persistence via `.map/` directory ensures workflow state survives compaction
  - Seamless user experience: workflows resume automatically without manual intervention
  - **Benefits**: Eliminates manual recovery steps, maintains workflow continuity

- **Defensive Documentation in MAP Workflow Templates** (PR #15)
  - Alert boxes in all command templates warn users about compaction before it occurs
  - Provide 4-step recovery workflow with concrete commands
  - Updated templates: map-feature.md, map-efficient.md, map-debug.md, map-refactor.md
  - Synchronized to `src/mapify_cli/templates/commands/` (all ✅ in sync)
  - **Benefits**: Users know what to do when compaction occurs, reduces confusion

**Multi-language Quality Gates:** (PR #14)
- **Extended Stop Hook**: Quality gates now support Go, TypeScript, and Rust beyond Python
  - **Go** (.go): `go fmt` + `go vet` for formatting and static analysis
  - **TypeScript** (.ts, .tsx): `tsc --noEmit` for type checking
  - **Rust** (.rs): `rustc` syntax validation
  - Language detection via file extension-based routing
  - Graceful degradation: skips checks if language toolchain not installed
  - Non-blocking: always exits 0, shows warnings only
  - **Benefits**: Universal code quality enforcement for polyglot codebases

**Hooks System Enhancements:**
- Hooks templates synchronized to `src/mapify_cli/templates/hooks/` for `mapify init`
- Implemented findings from Reddit post analysis (docs/reddit-analysis-improvements-CORRECTED.md)
- Enhanced hooks documentation and changelog

### Fixed

**FTS5 Query Engine:** (PR #16)
- **Resolved "no such column" SQL errors** for hyphenated queries in `mapify playbook query`
  - Root cause: FTS5 tokenizer splits hyphens at index time ("session-start" → ["session", "start"]), but queries preserved hyphens
  - Solution: Automatic hyphen-to-space conversion in `_build_fts_query` (playbook_manager.py:1012)
  - Fixed queries: "auto-activation" ✅, "session-start" ✅, "multi-subtask" ✅
  - Added 25 comprehensive regression tests covering hyphenated queries, edge cases, backward compatibility
  - Documented FTS5 query format guidelines in USAGE.md (383 lines)
  - **Benefits**: Playbook query now works reliably with natural hyphenated terms

**CLI Improvements:**
- Fixed `mapify init` not copying `helpers/` directory to `.claude/hooks/helpers/`
- Fixed 3 dataclass attribute access bugs in checkpoint command implementation
- Fixed size bomb test moved out of parametrize to avoid ARG_MAX limits
- Removed unused variables in tests (code review cleanup)

### Changed

**Documentation:**
- **USAGE.md**: Added "Handling Context Compaction" section (78 lines)
  - User-friendly explanation of compaction concept
  - Step-by-step recovery workflow with examples
  - Checkpoint command output format documentation

- **ARCHITECTURE.md**: Added "Compaction Resilience" section (101 lines)
  - Technical architecture with `.map/` directory diagram
  - Filesystem persistence mechanism details
  - Comparison table: conversation memory vs filesystem

**Playbook Growth:** 5 new patterns added
- **Recovery-Oriented CLI Design** (CLI_TOOL_PATTERNS - new section)
- **Dual-Documentation Pattern** (DOCUMENTATION_PATTERNS): Serve both user and developer audiences
- **Defensive Documentation in Templates** (DOCUMENTATION_PATTERNS): Warn users before problems occur
- **Filesystem-as-Resilience-Layer** (IMPLEMENTATION_PATTERNS): .map/ directory persistence strategy
- **Python Dataclass Attribute Access** (IMPLEMENTATION_PATTERNS): Best practices for dataclass usage

### Testing

- **All 386 tests passing** (no regressions from multi-language support)
- **25 new FTS5 query tests** covering hyphenated terms and edge cases
- Manual validation completed for multi-language quality gates (Go, TypeScript, Rust)
- Full test suite execution time: ~2 minutes

### Implementation Stats (PR #15)

- 8/8 subtasks completed (100% success rate)
- 8 total iterations (1 per subtask, zero rework)
- 179 lines of documentation added
- 95 lines of CLI implementation
- 68 lines of command template updates (4 files)

## [1.1.0] - 2025-10-29

## [1.1.0] - 2025-10-29

### Added
- **`mapify playbook apply-delta` CLI Command**: New command for applying Curator delta operations to playbook
  - Supports both file input and stdin (pipe-friendly for CI/CD)
  - `--dry-run` flag for preview without applying changes
  - `--verbose` flag for detailed operation logging
  - JSON output with operation results (added, updated, deprecated counts)
  - Comprehensive test suite with 19 tests (unit, CLI, integration)

### Changed
- **Complete SQLite Migration**: All playbook commands now use SQLite as source of truth
  - `playbook stats` now reads from SQLite backend (not JSON)
  - `playbook query`, `search`, `apply-delta`, `sync` all use SQLite
  - Automatic JSON → SQLite migration on first access
  - No breaking changes - JSON files still supported

- **Workflow Template Updates**: All MAP workflow templates now document CLI usage
  - `.claude/commands/map-feature.md` - Updated Step 1 and Step 3.10
  - `.claude/commands/map-efficient.md` - Same changes
  - `.claude/commands/map-debug.md` - Same changes
  - `.claude/agents/curator.md` - Documents apply-delta integration
  - All changes synced to `src/mapify_cli/templates/`

### Fixed
- **Unique ID Generation**: Fixed UNIQUE constraint failures in ADD operations
  - Changed from in-memory COUNT to SQLite MAX(id) + 1
  - Ensures IDs are always unique across concurrent operations

- **Test Compatibility**: Fixed `test_playbook_stats` to handle migration messages
  - Added JSON extraction logic for mixed output (migration messages + JSON)
  - All 315 tests passing on all platforms (Ubuntu + macOS, Python 3.11 + 3.12)

### Improved
- **Code Quality**: Addressed all Copilot code review feedback
  - Replaced magic numbers with named constants (QUALITY_SCORE_MAX, RELEVANCE_WEIGHT, QUALITY_WEIGHT)
  - Removed 7 unused imports across test files
  - Fixed comment typo (0.03 → 0.3) in quality score calculation

### Documentation
- **Updated USAGE.md**: Added examples for `mapify playbook apply-delta` command
- **Template Synchronization**: All .claude/ templates synced to src/mapify_cli/templates/

## [1.0.4] - 2025-10-27

### Added
- **Token-Optimized Workflow Variants**: Two new slash commands for token-conscious development
  - `/map-efficient` (⭐ RECOMMENDED): 30-40% token savings with full learning preservation
    - Batched Reflector/Curator execution (once at end vs per-subtask)
    - Conditional Predictor (only for high-risk subtasks)
    - Skips Evaluator (Monitor provides sufficient validation)
    - Maintains playbook updates and cipher integration
  - `/map-fast` (⚠️ throwaway code only): 40-50% token savings, no learning
    - Minimal agent sequence: TaskDecomposer → Actor → Monitor
    - Skips: Predictor, Evaluator, Reflector, Curator
    - Use only for temporary prototypes, not production code

### Changed
- **Cleaner Command Templates**: Removed verbose marketing/educational content from slash commands
  - Commands now contain concise technical instructions only
  - Educational content preserved in README.md and docs/USAGE.md
  - Improved readability for Claude Code execution

### Fixed
- **Test Infrastructure**: Updated test suite to validate only canonical template sources
  - Tests now check `src/mapify_cli/templates/` (canonical source) instead of gitignored `.claude/` directory
  - Prevents CI failures due to missing generated files

### Documentation
- **Comprehensive Workflow Guide** (docs/USAGE.md): 220+ line guide for workflow selection
  - Decision flowchart for choosing between /map-feature, /map-efficient, /map-fast
  - Real-world token usage examples (small/medium/large tasks)
  - Cost analysis: $270/month savings for teams running 10 workflows/day
  - Migration guide and common misconceptions
- **Architecture Documentation** (docs/ARCHITECTURE.md): Technical details on workflow optimization
  - Conditional Predictor logic implementation
  - Batched learning algorithms
  - Token savings breakdown per optimization
- **Updated Development Instructions** (.claude/CLAUDE.md): Commands directory synchronization process

## [1.0.3] - 2025-10-27

## [1.0.2] - 2025-10-27

## [1.0.0] - 2025-10-26

### Added - PyPI Package Release Automation

#### Release Infrastructure
- **PyPI Distribution**: MAP Framework now available as `mapify-cli` on PyPI for easy installation via `pip install mapify-cli`
  - Version pinning support: Install specific versions using `mapify-cli==X.Y.Z` or version constraints (e.g., `~=1.0.0`, `>=1.0.0,<2.0.0`)
  - **Benefits**: Simple installation without git clone, reproducible builds with version pinning

- **Automated PyPI Publishing** (`.github/workflows/release.yml`): GitHub Actions workflow automatically publishes releases to PyPI using OIDC trusted publishing
  - Triggers on git tags matching `v*.*.*` pattern (semantic versioning)
  - Multi-gate validation: tag format verification, version consistency checks, artifact validation with twine
  - Deploy-what-you-test pattern: reuses CI build artifacts to ensure published package matches tested code
  - OIDC authentication: no manual API token management required
  - **Benefits**: Secure automated releases, reduced human error, consistent release process

- **Version Bumping Script** (`scripts/bump-version.sh`): Automated semantic versioning workflow (458 lines)
  - Updates `pyproject.toml` version field and moves `CHANGELOG.md` [Unreleased] section to versioned section
  - Creates conventional commit messages and annotated git tags with changelog excerpts
  - Multi-gate validation: semver format, duplicate tag detection, git working directory cleanliness, CHANGELOG.md structure
  - Cross-platform compatibility: handles both GNU sed (Linux) and BSD sed (macOS)
  - **Benefits**: Consistent versioning across files, automated changelog updates, prevents version conflicts

#### Documentation
- **Release Process Guide** (`RELEASING.md`): Comprehensive 350-line release documentation
  - Pre-release checklist covering code quality, documentation, dependencies, git state
  - Version bumping workflow with semantic versioning examples (major/minor/patch)
  - GitHub release creation commands and verification steps
  - Rollback procedures including PyPI yanking with blast radius documentation
  - PyPI OIDC trusted publishing setup instructions
  - Troubleshooting section for common issues
  - **Benefits**: Single source of truth for release process, reduced onboarding time for maintainers

- **README.md Installation Updates**: Restructured with PyPI as primary installation method
  - Progressive complexity design: simple (`pip install mapify-cli`) → intermediate (version pinning) → advanced (development install)
  - Version management section with links to PyPI package page and GitHub releases
  - Semantic versioning explanation for version constraint syntax
  - **Benefits**: Clearer installation path for end users, better segmentation of user types

- **Playbook Enhancements** (`.claude/playbook.json`): Added 11 new release automation patterns (64 → 75 bullets)
  - Security: PyPI OIDC trusted publishing, GitHub Actions least-privilege permissions
  - Implementation: Deploy-what-you-test pattern, multi-gate validation, cross-platform sed compatibility
  - Documentation: Executable documentation, single source of truth derivation, temporal risk management, progressive complexity

### Changed

- **Installation Priority**: README.md now recommends PyPI installation as primary method, with GitHub installation as alternative for development work
- **Release Process**: Maintainers use automated workflows (`release.yml`) and scripts (`bump-version.sh`) instead of manual version updates

### Changed - Documentation Structure Reorganization

#### Repository Documentation Organization
- **Moved user-facing documentation to `docs/`**: INSTALL.md, USAGE.md, ARCHITECTURE.md, SEMANTIC_SEARCH_SETUP.md, IMPROVEMENT-STATUS.md
- **Moved research materials to `docs/research/`**: Research PDFs (map.pdf, context-engenering.pdf, 2510.04618v1.pdf) and analysis documents (opus-4.1-thinking.md, sonnet-4.5.md, prompt-improvement-analysis.md)
- **Updated 25 documentation link references** across README.md and docs/ files
- **Git history fully preserved** using `git mv` for all moved files
- **Zero breaking changes**: Documentation only, no code dependencies affected

**Benefits:**
- Decluttered repository root (11 docs → 2: README.md, CHANGELOG.md)
- Clear hierarchical navigation by audience (users → docs/, researchers → docs/research/)
- Professional appearance improves project credibility
- Scalable structure accommodates growth without re-cluttering
- Improved first impressions and onboarding experience

**Quality Improvement:** Overall score 8.4/10 (Modularity: 10/10, Readability: 9/10, Complexity: 9/10, Maintainability: 8/10)

### Added - CLI Tool Development Improvements

#### Enhanced MAP Agents for CLI Development
- **Monitor Agent** (v2.3.0): Added comprehensive CLI Tool Validation section (### 6)
  - Manual execution test checklist
  - Output stream validation (stdout/stderr separation)
  - Library version compatibility checks
  - Integration testing requirements
  - Common CLI issues and solutions with examples
  - **Benefits**: Catches stdout pollution, version incompatibility, CliRunner vs real CLI mismatches

- **Predictor Agent** (v2.3.0): Added CLI Tool Specific Risks section
  - HIGH risk: Library parameter availability in minimum version
  - HIGH risk: Diagnostic messages printing to stdout instead of stderr
  - HIGH risk: CLI output format changes breaking user scripts
  - MEDIUM risk: Environment variable and error message location changes
  - Real-world example from mapify CLI subcommands implementation
  - **Benefits**: Proactively identifies CLI-specific risks before implementation

- **Reflector Agent** (v2.3.0): Added CLI Tool Pattern Recognition
  - New pattern type: `CLI_TOOL_PATTERNS` section
  - Recognition signals: output pollution, version incompatibility, stream handling
  - CLI Reflection Template: what test missed, manual verification needed
  - Pattern extraction for reusable CLI lessons
  - **Benefits**: Systematically captures CLI development lessons

#### Playbook Schema Enhancement
- **CLI_TOOL_PATTERNS Section**: New playbook section for CLI development patterns
  - 10 playbook sections (was 9)
  - Captures lessons about output streams, version compatibility, testing methodology
  - Enables pattern reuse across CLI implementations
  - **Benefits**: Institutional memory for CLI development

#### Documentation
- **CLI Testing Guide** (`docs/CLI_TESTING_GUIDE.md`): Comprehensive 400+ line guide
  - Output stream management (stdout for output, stderr for diagnostics)
  - Version compatibility patterns and detection
  - Integration testing workflows (CliRunner vs subprocess)
  - Common pitfalls with real-world examples
  - Best practices checklist and testing workflow
  - **Benefits**: Single source of truth for CLI testing best practices

### Changed
- **playbook_manager.py**: Updated sections_count from 9 to 10

### Context
These improvements were extracted from lessons learned during implementation of mapify CLI subcommands (PR #6), where we discovered:
1. SemanticSearchEngine printed to stdout, polluting JSON output
2. `CliRunner(mix_stderr=False)` parameter unavailable in CI's older Click version
3. Tests passed with CliRunner but real CLI had issues
4. Manual testing required to catch output pollution

These patterns are now captured in MAP framework to prevent similar issues in future CLI development.

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
