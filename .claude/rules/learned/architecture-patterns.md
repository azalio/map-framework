# Architecture Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Contract-First Inter-Component JSON Schemas** (2026-03-26): When two components share a JSON data format (file, IPC, API), always define the schema once as a Python TypedDict or dataclass and import it in both producer and consumer, because organic field names cause silent KeyError failures that only surface in production. [workflow: map-learn-improvement]
  ```python
  from typing import TypedDict

  class StepState(TypedDict):
      current_step_phase: str  # canonical name, one definition
      current_subtask_id: str | None

  # Producer and consumer both import StepState
  ```

- **Monolith Decomposition: Extract Shared Helpers First** (2026-03-26): When decomposing a large Python module into submodules, always identify helpers shared by multiple extraction targets and extract them to a utility module FIRST, because copy-pasting helpers creates DRY violations that diverge silently. Re-export all extracted symbols from the original module to preserve backward compatibility. [workflow: map-learn-improvement]
