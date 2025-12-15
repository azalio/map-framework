# Gap Analysis: Scenario vs. Implementation

This document outlines the discrepancies between the proposed scenario in `docs/scenario/yc.md` and the current codebase implementation of the MAP Framework.

## 1. Missing Commands

### `map-plan`
- **Scenario:** Described as the starting point for tasks (Phase 0), producing phased decomposition, risk areas, and control points.
- **Implementation:** No `map-plan.md` command template exists in `src/mapify_cli/templates/commands/`.
- **Current State:** Task decomposition happens implicitly within `map-efficient` and `map-feature` via the `task-decomposer` agent, but there is no dedicated planning phase command.
- **Recommendation:** Create `src/mapify_cli/templates/commands/map-plan.md` to implement Phase 0 as a standalone step.

## 2. Missing Roles/Patterns

### `llm-counsul`
- **Scenario:** Described as a "decision validation pattern" involving multiple independent LLM evaluations for controlled divergence.
- **Implementation:** No agent, tool, or pattern named `llm-counsul` exists in the codebase.
- **Current State:** Validation is handled by the `Monitor` and `Evaluator` agents, which appear to be single-pass or sequential, not the multi-perspective "council" described.
- **Recommendation:** Define `llm-counsul` either as a new agent type (e.g., `council-member`) or a specific orchestration pattern within `map-plan` or `map-feature` that invokes multiple personas.

### `ChunkHound`
- **Scenario:** Described as a "semantic memory layer" used by Research to navigate codebases.
- **Implementation:** Referenced in `research-agent.md` as an MCP tool (`mcp__ChunkHound__search_semantic`), but no local implementation of a ChunkHound server exists in the repo. It appears to be an external dependency or a placeholder name for a semantic search capability.
- **Current State:** The `research-agent` has fallback logic ("DEGRADED_MODE") if ChunkHound is missing.
- **Recommendation:** Clarify if ChunkHound is a proprietary internal tool or if it should be replaced/aliased to `cipher` or another semantic search implementation available in the open-source version.

## 3. Workflow Discrepancies

### Explicit Phase 0 (Planning)
- **Scenario:** Explicit "Phase 0" before implementation.
- **Implementation:** Workflows jump straight to decomposition and implementation (`/map-efficient`, `/map-feature`).
- **Recommendation:** If the video scenario is the target state, the CLI commands should be refactored to support a `map-plan` -> `map-implement` workflow, or `map-plan` should be integrated as an optional first step that saves state for subsequent commands.

### Parallelism
- **Scenario:** Mentions "Parallel execution is achieved through explicit user coordination".
- **Implementation:** Current commands enforce sequential execution ("automated sequential workflow").
- **Recommendation:** This aligns with the scenario's note that parallelism is *user-coordinated* (running multiple terminals), so no code change is strictly required, but documentation could clarify this pattern.

## Summary of Action Items

1.  **Create `map-plan` command:** Implement the planning phase command template.
2.  **Implement `llm-counsul`:** Design the prompt/orchestration for the council pattern, likely as a step within `map-plan` or a standalone check.
3.  **Clarify `ChunkHound`:** Update documentation or configuration to define how users should satisfy this dependency (or replace it with `cipher` semantic search).
