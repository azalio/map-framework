# MAP Agent Templates Changelog

All notable changes to MAP agent templates will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2025-10-18

### Added
- **Recitation Pattern Integration** (Actor v2.1.0): Added `<recitation_plan>` section to Actor template
  - Displays current task plan with visual progress indicators (✓ completed, → in progress, ☐ pending)
  - Shows iteration count and previous errors for retry attempts
  - Maintains goal focus on long multi-step workflows (+20-30% success rate)
  - Conditional rendering: only shows when `{{plan_context}}` is provided by orchestrator
  - Based on "Context Engineering for AI Agents" (Manus.im, 2025)

### Changed
- **Actor Template**: Bumped version from 2.0.0 to 2.1.0
  - Added `{{plan_context}}` template variable support
  - Inserted recitation section between `<task>` and `<playbook_context>` for optimal attention placement
  - No breaking changes - gracefully handles missing plan_context

### Optimized
- **Monitor Template** (v2.0.0 → v2.1.0): Verbose output optimization for ~10% token savings (Phase 1.4)
  - Compressed MCP Integration section: 112 → 92 lines (20 saved)
  - Streamlined Documentation Consistency: 77 → 62 lines (15 saved)
  - Consolidated Example 3 (Documentation Inconsistency): 52 → 27 lines (25 saved)
  - Reduced Example 1 commentary: 63 → 55 lines (8 saved)
  - **Total reduction**: 1006 → 909 lines (-97 / 9.6%)
  - **Critical preservations**: Security Checklist, Severity Guidelines, Decision Rules, JSON Format (all intact)
  - **Validation**: Self-reviewed valid=true, scored 9.7/10 by Evaluator

- **Evaluator Template** (v2.0.0 → v2.1.0): Balanced optimization with teaching quality preservation (Phase 1.4)
  - Compressed Examples 2-6: Summaries with key features highlighted
  - Streamlined scoring guidelines and dimension explanations
  - **Partial rollback decision**: Restored Example 1 full code (52 lines) to maintain teaching quality
  - **Total reduction**: 934 → 844 lines (-90 / 9.6%)
  - **Final metrics**: 214% over-delivery (balanced vs aggressive 238%)
  - **Critical preservations**: 6-Dimensional Scoring Model, Weighted Calculation, Decision Tree, JSON Format (all intact)
  - **Validation**: Scored Monitor optimization 9.7/10

- **Playbook Growth**: +8 new patterns learned during Phase 1.4 implementation (3 → 11 total bullets)
  - impl-0001: Multi-Agent Workflow Documentation
  - impl-0002: Inter-Subtask Learning Propagation
  - impl-0003: Executable Specification for Code Transformations
  - impl-0004: Bounded Optimization Specifications
  - qual-0001: Analysis Document Completeness (WHAT/WHERE/HOW/WHY)
  - qual-0002: Template Purpose Classification (teaching vs validation)
  - test-0001: Iterative Refinement Based on Monitor Feedback
  - test-0002: Iteration Count as Learning Effectiveness Metric
  - test-0003: Over-Delivery Pattern Recognition
  - arch-0001: Workflow-Scoped Learning Context Architecture
  - arch-0002: Analysis-Implementation Pipeline Pattern

## [2.0.0] - 2025-10-17

### Added
- **Comprehensive MCP Integration Framework**: Systematic tool usage guidance with decision trees for cipher_memory_search, context7, codex-bridge, and deepwiki
- **XML-Style Semantic Structure**: Added `<mcp_integration>`, `<context>`, `<rationale>`, `<example>`, `<critical>` tags for better LLM parsing
- **Decision Frameworks**: IF/THEN/ELSE pseudocode logic for systematic decision-making
- **Extensive Examples**: 200-600 lines of examples per agent with good/bad comparisons
- **Rationale Sections**: Explicit "why" explanations for every major pattern
- **Template Variables**: Handlebars variables for Orchestrator integration ({{project_name}}, {{language}}, {{framework}}, etc.)
- **Critical Reminders**: Validation checklists at the end of each template
- **Template Versioning**: Added version, last_updated, and changelog metadata to YAML frontmatter

### Changed
- **Template Size**: Expanded from ~2,232 lines to 9,269 lines (+258% growth) for comprehensive guidance
- **Structure**: Evolved from simple markdown to XML-enhanced semantic formatting
- **Agent Count**: Reduced from 10 to 9 (orchestrator removed, functionality moved to slash commands)

### Removed
- **Orchestrator as Subagent**: Removed due to Claude Code limitation (subagents cannot call other subagents)
  - Functionality moved to slash commands: /map-feature, /map-debug, /map-review

### Fixed
- **Missing Fallback Generators**: Added fallback generators for reflector and curator in src/mapify_cli/__init__.py
- **Hook Cleanup**: Removed 4 non-functional MCP hooks (auto-store-knowledge, enrich-context, session-init, track-metrics)
- **Template Sync**: Synchronized .claude/agents/*.md with src/mapify_cli/templates/agents/*.md

### Migration Guide

#### From v1.x to v2.0

**Breaking Changes:**
1. **Orchestrator Workflow**: Replace direct orchestrator agent calls with slash commands:
   - Old: "Use orchestrator agent to implement feature X"
   - New: `/map-feature` command

2. **Template Structure**: If you have custom parsers, update to handle XML semantic tags

**Non-Breaking:**
- Existing projects are unaffected (templates are copied, not linked)
- Upgrade is opt-in via `mapify init . --force`

**Recommended Actions:**
1. Update your workflow to use slash commands instead of orchestrator agent
2. Review new MCP tool integration guidance in each agent template
3. Consider adopting decision frameworks for complex tasks

## [1.0.0] - 2025-01-15 (Baseline)

Initial release of MAP agent templates with basic structure:
- 8 core agents (actor, monitor, predictor, evaluator, task-decomposer, reflector, curator, documentation-reviewer)
- Basic markdown formatting
- Minimal examples (50-100 lines per agent)
- Simple tool specifications
