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
