# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `/map-debate` command: Debate-based MAP workflow with Opus arbiter for multi-variant synthesis. Generates 3 Actor variants in parallel (security/performance/simplicity focus), validates with parallel Monitors, then uses `debate-arbiter` (Opus model) to cross-evaluate and synthesize optimal solution

### Changed
- Documentation cleanup: Remove deprecated `/map-feature` references, update learning workflow info

### Fixed
- Address reviewer feedback on map-debate documentation

## [2.1.0] - 2026-01-07

### Added
- External static analysis scripts for Monitor agent (`analyze.sh`, `lint-go.sh`, `lint-python.sh`)
- LLM Council recommended improvements to MAP workflow (context7 integration, parallel execution)

### Changed
- Optimize task-decomposer template with references to mapify init
- Extract common functions to shared module with tests
- Update README and sync templates with map-efficient improvements

### Fixed
- Security hardening per Copilot review
- Improve clarity per Copilot review comments (multiple rounds)
- Fix agent count documentation (8→10) and update template sync
- Fix black formatting issues

### Documentation
- Document map-efficient command template
- Sync map-efficient.md documentation with source template

## [2.0.0] - 2025-12-15

### Changed
- Parallelize Monitor, Predictor, Evaluator agents in `/map-review` workflow for improved performance
- Auto-create `.mcp.json` during `mapify init` for better MCP server integration

### Fixed
- Remove hooks-related CI job and test after hooks system removal
- Restore JSON validation in stop.sh hook for malformed input handling
- Address Copilot and LLM Council security review findings
- Clarify enforcement points and framework-level secret handling in documentation
- Handle malformed JSON in stop.sh hook with updated INPUT FORMAT docs
- Address PR #56 review comments
- Fix black formatting issues

### Added
- New research-agent for context isolation during research tasks

### BREAKING CHANGES

#### Hooks System Removed

The Claude Code hooks system has been completely removed from MAP Framework.

**Rationale:**
- Hooks added complexity without proportional value
- Core MAP workflows (`/map-efficient`, `/map-debug`, `/map-fast`) operate independently of hooks
- Maintenance burden outweighed benefits

**What was removed:**
- `.claude/hooks/` directory (13 hook scripts)
- `src/mapify_cli/__init__.py` functions: `load_settings_with_merge()`, `merge_hooks_settings()`, `install_hooks()`
- `src/mapify_cli/templates/hooks/` directory
- CLI option: `--with-hooks/--no-hooks` from `mapify init`
- 59 test cases (test_hooks_*.py, test_init_merge.py, test_inject_playbook_bullets.py)

**Migration guide:**

For existing projects with hooks installed:

1. **Hooks are now user-managed** - The `.claude/hooks/` directory (if present) will be ignored by MAP Framework
2. **No action required** - Your existing hooks will continue to work as Claude Code hooks
3. **Optional cleanup** - You can safely remove `.claude/hooks/` if you don't use custom hooks

**What continues to work:**
- ✅ All MAP workflows (`/map-efficient`, `/map-debug`, `/map-fast`, `/map-learn`, `/map-release`, `/map-review`)
- ✅ Agent orchestration via Task tool
- ✅ Playbook management via `mapify playbook` commands
- ✅ MCP server integration (cipher, context7, deepwiki, etc.)

**What no longer works:**
- ❌ `mapify init --with-hooks` / `--no-hooks` options (removed from CLI)
- ❌ Automatic hooks installation via `mapify init`
- ❌ Hooks template synchronization

**Upgrade path:**

```bash
# Upgrade MAP Framework to v2.0.0
uv tool upgrade mapify-cli

# (Optional) Remove hooks directory if you don't use custom hooks
rm -rf .claude/hooks/
```

## [1.7.0] - 2025-12-08

### Added
- **Optional Learning Command**: Added `/map-learn` command for optional post-workflow learning. Reflector and Curator agents are now invoked on-demand rather than automatically in workflows (cdc7e4e)
- **Auto-Approval Permissions**: `mapify init` now configures auto-approval rules for common readonly operations (cipher memory search, tracker queries, sequential-thinking) to reduce permission prompts (18f9532)

### Changed
- **Workflow Simplification**: Removed unused workflow commands (`/map-feature`, `/map-refactor`) to reduce maintenance burden. Use `/map-efficient` for feature work (cdc7e4e)
- **Permissions Merge**: Settings permissions now use additive merge strategy to preserve user-defined rules (b585173, 1978af8)

### Fixed
- **Map-Review Command**: Restored `/map-review` command that was accidentally removed and updated stale agent references (1394935)
- **Stop Hook**: Restored malformed JSON handling in `stop.sh` quality gates hook for robustness (41b96c9)
- **README Accuracy**: Updated README to reflect actual available commands, fixed playbook bullet ID generation for consistent identifiers (af2d5d3)
- **Documentation Consistency**: Fixed Next Steps sections across commands to show actual available commands (c0a257d)
- **Map-Learn References**: Removed stale references to deleted commands in `/map-learn` template (3fcf8fc)
- **Agent Instructions**: Removed misleading 'orchestrator directly' instruction from agent templates (ea75b21)
- **Type Safety**: Resolved 39 mypy type errors across 11 files, improving code quality (fe474dd)

### Removed
- **Recitation Functionality**: Removed `mapify recitation` commands and related functionality. This feature was underutilized and added maintenance complexity (a1be4f8)
- **MCP Server: codex-bridge**: Removed codex-bridge MCP server from the framework (7a7e363)
  - Removed from `INDIVIDUAL_MCP_SERVERS` constant
  - Removed from agent template generators (actor, predictor)
  - Removed from `agent_mcp_mappings` configuration
  - Updated all agent templates to remove codex-bridge references
  - Updated documentation (README, ARCHITECTURE, presentations)
  - Updated `.mcp.json.example` and plugin configuration
  - Updated tests to expect 5 MCP servers instead of 6
  - **Rationale**: Simplify MCP server dependencies; codex-bridge functionality can be achieved through other tools

## [1.6.2] - 2025-11-29

### Fixed
- **MAP Efficient Workflow**: Fixed incorrect `subagent_type` parameters in `/map-efficient` command template. Changed from deprecated `type` parameter to correct `subagent_type` for all Task tool invocations (reflector, curator, monitor, predictor, evaluator) (e05793a)

## [1.6.1] - 2025-11-28

### Fixed
- **Playbook Migration**: Fixed migration from `playbook.json` to `playbook.db` when using `mapify init --force`. The migration now properly detects and removes invalid/incomplete `playbook.db` files before attempting migration, and cleans up stale `playbook.json` files after successful migration (7cfa82e)
- **Playbook References**: Removed all `playbook.json` references from codebase (except CHANGELOG history). Updated CLAUDE.md, agent templates, skills, and documentation to reference `playbook.db` only. Added clarifying comments to migration code and tests (fbe6bd3)

## [1.6.0] - 2025-11-27

### Changed
- **Agent Model Upgrades**: Upgraded `predictor.md` and `evaluator.md` from `haiku` to `sonnet` model
  - **Predictor** (v2.4.0 → v3.3.0): Impact analysis now uses sonnet for complex reasoning
  - **Evaluator** (v2.4.0 → v3.0.0): Quality evaluation now uses sonnet for nuanced judgment
  - **Cost Impact**: ~12x increase per agent call ($0.25→$3/1M input tokens, $1.25→$15/1M output tokens)
  - **Per-workflow impact**: ~$0.03 → ~$0.36 for typical 4-subtask feature
  - **Mitigation**: Use `/map-efficient` workflow (conditional Predictor, 30-40% token savings)
  - **Rationale**: Better analysis quality justifies cost for production code

- **Agent Template Rewrites**: Major rewrites of all 8 agent templates with LLM Council validation
  - **actor.md** (v2.5.0 → v3.1.0): Added Quick Reference box, enhanced MCP integration
  - **monitor.md** (v2.5.0 → v2.9.0): Added execution workflow, template configuration
  - **predictor.md** (v2.4.0 → v3.3.0): Added input schema, tool definitions, MAP integration
  - **evaluator.md** (v2.4.0 → v3.0.0): New Six-Dimensional Quality Model, score calibration
  - **curator.md** (v2.3.0 → v3.1.0): Simplified execution flow, canonical JSON shape
  - **reflector.md** (v2.5.0 → v3.0.0): Quick start paths, framework execution order
  - **task-decomposer.md**: Major rewrite with enhanced complexity scoring
  - **documentation-reviewer.md** (v3.0.0 → v3.1.0): Improved review workflow

### Removed
- **Agent Documentation Files**: Removed `.claude/agents/CHANGELOG.md`, `MCP-PATTERNS.md`, `README.md`
  - Version info now in agent frontmatter (`version:`, `last_updated:`)
  - MCP patterns consolidated into individual agents

## [1.5.0] - 2025-11-14

### Added
- **Non-Interactive Init**: `mapify init` now defaults to non-interactive mode, installing all MCP servers without prompts for better CI/CD compatibility (1ad6dd6)
- **Agent MCP Integration**: Integrated 18 Cipher MCP tools across all 8 MAP agents (task-decomposer, actor, monitor, predictor, evaluator, reflector, curator, documentation-reviewer) for enhanced knowledge management and reasoning capabilities (aaded8a)
- **Release Validation**: Added CHANGELOG completeness validation to Gate 12 in release workflow, preventing releases with incomplete documentation (6541511)

### Changed
- **Playbook Migration**: Migrated all playbook.json references to playbook.db SQLite format throughout codebase, agents, documentation, and configuration (0332cdf)
- **Agent Optimization**: Optimized actor.md template for better performance and fixed variable inconsistency (2bc4b52)
- **Cleanup**: Removed unused files to reduce repository size (09a5b4d)

### Fixed
- **Pre-Release Validation**: Fixed undefined click references in init command, removed unused test variables, and resolved test isolation issue (f5cdb17)
- **Documentation**: Corrected commands in docs to use playbook.json after export (not playbook.db) (0c9fb38)
- **Documentation**: Fixed swapped filenames in playbook mistake example (5bfca90)
- **Playbook Error**: Corrected error message for playbook.json migration failure (4834574)
- **Agent Quality**: Addressed Copilot reviewer feedback improving code maintainability (c5a7dcc)

### Documentation
- **Playbook Access**: Updated documentation to use mapify CLI commands instead of Python API for playbook operations (ac56459)

## [1.4.0] - 2025-11-11

### Changed
- **Agent Optimization**: Optimized MAP agent prompts with stable prefix positioning and concrete quality rubrics for more consistent output (d5b76b0)
- **Agent Efficiency**: Reduced Reflector agent template size by 61.2% (from 5.3KB to 2.0KB) to mitigate token-induced brevity bias while maintaining functionality (2cadcbb)

### Fixed
- **Release Automation**: Fixed `bump-version.sh` script to automatically update `__version__` in `src/mapify_cli/__init__.py`. This prevents version mismatch between package metadata (pyproject.toml) and runtime version display (`mapify --version`).
- **Release Workflow**: Added critical verification step in `.claude/commands/map-release.md` to check `__version__` matches before pushing tags, preventing PyPI packages with incorrect version strings.
- **Code Quality**: Addressed 7 Copilot review comments improving code maintainability and type safety (620c1aa)

## [1.3.2] - 2025-11-07

### Fixed
- **PyPI Package Version**: Fix v1.3.1 PyPI package which was built before final commit amendment, resulting in package containing `__version__ = "1.3.0"` instead of "1.3.1". The v1.3.1 git tag points to correct code, but the PyPI package was built from an earlier state. This release ensures PyPI package matches git tag.

## [1.3.1] - 2025-11-07

### Fixed
- **Version Display**: Updated `__version__` in `__init__.py` to match package version (1.3.0). Previous release v1.3.0 had mismatched versions: pyproject.toml showed 1.3.0 but `mapify --version` displayed 1.0.4 due to missed update in bump-version.sh script.

## [1.3.0] - 2025-11-07

### Added

- **CLI Validation and Agent Guidance** (f8ce250, 0c71566)
  - Added MAP CLI reference skill for correcting mapify command errors
  - Documented actual CLI structure in machine-readable format
  - Updated Actor, Reflector, and Curator agent templates with CLI guidance
  - Added E2E tests for CLI command correctness validation
  - Updated documentation with CLI best practices

- **Cipher Infrastructure Enhancements** (fd505ce, 30b0947, c7a3fa4, 59cbe7f)
  - Added Neo4j to Cipher Docker Compose infrastructure for Knowledge Graph support
  - Comprehensive Cipher + Qdrant + PostgreSQL setup documentation
  - Knowledge Graph configuration documentation
  - Refactored Cipher setup docs into modular quick-start guides (condensed from 76KB to ~15KB)
  - Added infrastructure examples with docker-compose.yml and .env.example

- **Claude Code Hooks Integration** (1ffedbc, d27bfb9, ba43d1b)
  - Integrated claude-code-prompt-improver with sequential hooks
  - Use CLAUDE_PROJECT_DIR for absolute hook paths
  - Added git hooks testing to CI pipeline

### Fixed

- **Code Quality and Linting** (251e5dd, 5b166d3, ce41dde)
  - Applied black formatting to 53 Python files for consistent code style
  - Fixed 38 ruff linting issues (removed unused imports, f-string prefixes, unused variables)
  - Added missing datetime import in CLI module
  - Resolved unittest.mock import issues in tests
  - Added noqa comments for intentional unused variables in test fixtures

- **Hooks System Improvements** (2f91b05, d35c954, ae22179, 67fdc49)
  - Removed redundant PreToolUse hook for template validation (d0c4d88, c35c12d)
  - Resolved JSON parsing errors in Claude Code hooks (manual JSON → jq-based generation)
  - Separated stdout/stderr in E2E tests for proper JSON parsing
  - Preserved user settings during hooks installation (merge strategy)

- **mapify init Command Fixes** (1aee890, 7d264ef, 956ef96)
  - Fixed mapify init to copy Python hooks and settings.hooks.json correctly
  - Corrected settings file location (.claude/ not .claude/hooks/)
  - Restored SessionStart hook functionality

- **Documentation Corrections** (d998100, cc572b0, 62f4626, 3b8b492, b62bea7, 5e5ee62)
  - Fixed Claude Desktop → Claude Code references in Cipher setup
  - Addressed Copilot review comments across multiple PRs
  - Aligned with official Claude Code hooks documentation

### Changed

- **Documentation Organization** (1b8846e, 841c2d3)
  - Replaced programming-focused prompts with MAP Framework system prompt
  - Removed redundant hooks-json-parsing-errors.md documentation

### Removed

- **Cleanup** (cd93cfe, 4c0602b, cf0573c)
  - Removed obsolete Cipher example files and curator outputs
  - Removed generated curator_output.json file

## [1.2.3] - 2025-11-05

### Added

**P0 Improvement - Quality Checklist for Actor Agent (R1):**
- **Added Quality Checklist section to Actor agent template** (Implementation Plan P0 R1)
  - **New section**: 10-item self-review checklist following Claude Code "Rule of 10" pattern
  - **Location**: Inserted after `</examples>` section (line 1102-1142) in `.claude/agents/actor.md`
  - **Template variables**: Integrated `{{standards_url}}` for dynamic style guide reference
  - **Checklist items cover**:
    1. Code style compliance ({{standards_url}})
    2. Explicit error handling (no silent failures)
    3. Security review (SQL injection, XSS, sensitive data logging)
    4. Test case identification (happy path + edge cases)
    5. MCP tools usage (cipher_memory_search, context7)
    6. Template variable preservation (orchestration compatibility)
    7. Trade-offs documentation
    8. Playbook bullet tracking (ACE feedback loop)
    9. Complete implementations (no ellipsis)
    10. Dependency justification
  - **Updated Critical Reminders**: Added reference to Quality Checklist at line 1148-1149
  - **Synchronized**: Template copied to `src/mapify_cli/templates/agents/actor.md`
  - **Expected impact**: 30-40% reduction in Monitor iteration cycles (from 2-3 to 1 iteration)
  - **Rationale**: Enables Actor self-review before Monitor submission, catching common rejection reasons early
  - **Reference**: Based on analysis in `docs/map-framework-improvement-plan.md` (P0 R1) and `analysis/claude-code-subagent-structure-analysis.md`

## [1.2.2] - 2025-11-03

### Fixed

**CRITICAL: Template Synchronization Bugfix:**
- **Fixed `mapify init --force` deleting user's custom files** (Critical Bug)
  - **Problem**: `install_hooks()` used `shutil.rmtree()` to delete entire `.claude/hooks/helpers/` directory before copying templates, destroying all user's custom helper scripts
  - **Solution**: Changed to individual file copying with `shutil.copy2()` - only updates template files, preserves user files
  - **Impact**: Users can now safely run `mapify init --force` to update templates without losing their custom scripts
  - **Files affected**: `src/mapify_cli/__init__.py` (lines 1118-1140)
  - **Test coverage**: Added comprehensive regression test `test_init_force_preserves_user_files` in `tests/test_mapify_cli.py`
  - **Verified**: Test creates user files in `.claude/hooks/helpers/`, runs `--force`, confirms files still exist with original content
  - **Related fix**: Added `validate_checkpoint_file.py` to templates (was missing, causing deletion during `--force`)

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
