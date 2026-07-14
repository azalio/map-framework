"""Trajectory-level outcome evaluator for MAP workflows (issue #351).

Promotes the whole-skill outcome-eval spike
(``tests/skills_eval/whole_skill/spike_runner.py``) into a maintained,
shipped, evidence-linked trajectory regression surface.

Compared to the trigger-only ``skills_eval`` engine, this package scores the
OUTCOME of a full interactive agent run: deterministic formal gates plus
component LLM-judge dimensions over a normalized trajectory bundle.

Invariants (inherited from skills_eval):
- INV-2: clock-free / random-free pure modules; callers supply timestamps.
- INV-3: no ``import anthropic`` / no ANTHROPIC_API_KEY access.
- INV-5: production ``.claude/`` / ``.map/`` / ``templates_src/`` never mutated.
- VC4: per-run errors recorded, never raised; matrix continues.
"""

from __future__ import annotations

from mapify_cli.skills_eval.trajectory.eval_schema import (
    COMPONENT_NAMES,
    ComponentScore,
    EvidenceLine,
    JudgeMeta,
    TrajectoryBundle,
    TrajectoryEvalRecord,
    compute_composite,
    is_hard_pass,
    make_run_id,
)

__all__: list[str] = [
    "COMPONENT_NAMES",
    "ComponentScore",
    "EvidenceLine",
    "JudgeMeta",
    "TrajectoryBundle",
    "TrajectoryEvalRecord",
    "compute_composite",
    "is_hard_pass",
    "make_run_id",
]
