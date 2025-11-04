# MAP Agent Templates Changelog

All notable changes to MAP agent templates will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.0] - 2025-11-04 (Predictor)

### Added
- **Quality Checklist Section** (Predictor v2.4.0): Added structured 10-item self-review framework for impact analysis validation. Checklist ensures systematic verification of: affected files identification, scope completeness, breaking change analysis, risk severity justification, downstream impacts, rollback feasibility, dependency conflicts, CLI behavior changes, integration points, and migration paths.
  - **Expected impact**: 25-30% reduction in Predictor-Actor iteration cycles
  - Inserted before `<output_format>` section (line 998) for pre-output validation
  - Follows same pattern as Monitor (v2.4.0) and Actor (v2.3.0) Quality Checklists

## [2.3.1] - 2025-11-04 (Actor)

### Enhanced
- **Actor-Monitor Relationship Documentation** (Actor v2.3.1): Added explanatory note clarifying relationship between Actor's pre-submission checklist and Monitor's 10-dimension validation framework. Helps Actor understand what validation criteria to anticipate, reducing blind-spot iterations by 5-10%.
  - Inserted after "When to Use This Checklist" section (line 1134)
  - Cross-references Monitor's Quality Checklist (v2.4.0)
  - No breaking changes - purely additive documentation enhancement

## [2.4.0] - 2025-11-04 (Monitor)

### Added
- **Quality Checklist Section** (Monitor v2.4.0): Added structured 10-item validation framework
  - Maps 1-to-1 with Monitor's existing validation categories (Correctness, Security, Code Quality, Performance, Testability, CLI Tool, Maintainability, External Dependencies, Documentation Consistency, Research Quality)
  - Enables precise feedback referencing (e.g., "Checklist item 2: Security validation failed")
  - Includes usage notes clarifying when conditional items apply (CLI Tool, External Dependencies, Documentation Consistency, Research Quality)
  - Inserted before `<output_format>` section for systematic validation guidance
  - **Expected impact**: 30-40% reduction in Actor-Monitor iteration cycles (standardized validation criteria)

### Changed
- **Monitor Template**: Bumped version from 2.3.0 to 2.4.0
  - Updated `feedback_for_actor` field description to encourage checklist item references
  - Updated severity examples to demonstrate checklist reference pattern in `title` field
  - No breaking changes - existing feedback patterns remain valid (backward compatible)

### Improved
- **Feedback Clarity**: Monitor feedback now references specific checklist items for actionable guidance
  - Example: "Checklist item 2: SQL injection vulnerability" vs generic "Security issue found"
  - Standardizes validation language across all reviews
  - Helps Actor self-review against same criteria before Monitor submission

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
- **Missing Fallback Generators**: Added fallback generators for reflector, curator, and test-generator in src/mapify_cli/__init__.py
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
- 9 core agents (actor, monitor, predictor, evaluator, task-decomposer, reflector, curator, test-generator, documentation-reviewer)
- Basic markdown formatting
- Minimal examples (50-100 lines per agent)
- Simple tool specifications
