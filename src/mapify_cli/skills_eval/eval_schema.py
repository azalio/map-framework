"""Shared data contracts for the skills_eval package.

All structures are defined EXACTLY ONCE here and imported by every eval
component (dispatcher, assertions, runner, aggregator).  This module is a
pure data layer — no dispatch logic, transcript parsing, assertion execution,
or I/O of any kind.

INV-3: No ``import anthropic`` and no ANTHROPIC_API_KEY access anywhere.
INV-6: Contract-first — producer and consumer both import from this module.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mapify_cli.token_budget import TokenUsage

# ---------------------------------------------------------------------------
# EvalSetEntry
# ---------------------------------------------------------------------------


@dataclass
class EvalSetEntry:
    """One row parsed from a JSON eval-set file.

    Built from externally supplied JSON, so field types are validated
    explicitly in ``__post_init__`` — Python type hints are documentation only.
    """

    prompt: str
    should_trigger: str | None
    should_not_trigger: str | None
    assertions: list[dict]  # type: ignore[type-arg]

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str):
            raise ValueError(
                f"EvalSetEntry.prompt must be str, got {type(self.prompt).__name__!r}"
            )
        if self.should_trigger is not None and not isinstance(self.should_trigger, str):
            raise ValueError(
                "EvalSetEntry.should_trigger must be str or None, "
                f"got {type(self.should_trigger).__name__!r}"
            )
        if self.should_not_trigger is not None and not isinstance(
            self.should_not_trigger, str
        ):
            raise ValueError(
                "EvalSetEntry.should_not_trigger must be str or None, "
                f"got {type(self.should_not_trigger).__name__!r}"
            )
        if not isinstance(self.assertions, list):
            raise ValueError(
                "EvalSetEntry.assertions must be list, "
                f"got {type(self.assertions).__name__!r}"
            )


# ---------------------------------------------------------------------------
# DispatchResult
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Result returned by the skill dispatcher for a single prompt.

    ``token_usage`` and ``error`` are optional — dispatcher sets ``error``
    when the API call fails and ``token_usage`` may be absent on failure.
    ``TokenUsage`` is imported from ``mapify_cli.token_budget``; it is NOT
    redefined here (INV-6).
    """

    raw_output: str
    triggered_skill: str | None
    token_usage: TokenUsage | None
    duration_s: float
    error: str | None = None


# ---------------------------------------------------------------------------
# EvalResultRecord  (append-only .jsonl row)
# ---------------------------------------------------------------------------

# Sentinel used in from_dict to distinguish «key absent» from «key present but None».
_MISSING: object = object()

@dataclass
class EvalResultRecord:
    """One completed eval result, serialisable to/from a JSON object.

    Used for the append-only ``.jsonl`` result file written by the runner
    (ST-005).  ``to_dict`` / ``from_dict`` provide a stable round-trip.
    ``TokenUsage`` is a flat 3-int frozen dataclass; it is serialised as a
    nested dict (via ``dataclasses.asdict``) and reconstructed in
    ``from_dict``.
    """

    cell_id: str
    prompt: str
    triggered_skill: str | None
    token_usage: TokenUsage | None
    duration_s: float
    assertions_passed: list[str] = field(default_factory=list)
    assertions_failed: list[str] = field(default_factory=list)
    raw_output: str = ""

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict for this record.

        ``token_usage`` is either a nested dict (3 keys) or ``None``.
        """
        return {
            "cell_id": self.cell_id,
            "prompt": self.prompt,
            "triggered_skill": self.triggered_skill,
            "token_usage": (
                dataclasses.asdict(self.token_usage)
                if self.token_usage is not None
                else None
            ),
            "duration_s": self.duration_s,
            "assertions_passed": list(self.assertions_passed),
            "assertions_failed": list(self.assertions_failed),
            "raw_output": self.raw_output,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalResultRecord:
        """Reconstruct an ``EvalResultRecord`` from a plain dict (JSON parse).

        Tolerates ``token_usage=None`` and missing keys for
        ``assertions_passed``, ``assertions_failed``, and ``raw_output``
        (backward compatibility with older .jsonl rows).
        """
        raw_tu = d.get("token_usage", _MISSING)
        if raw_tu is _MISSING or raw_tu is None:
            token_usage: TokenUsage | None = None
        else:
            token_usage = TokenUsage(
                input_tokens=int(raw_tu.get("input_tokens", 0)),
                cache_read_input_tokens=int(raw_tu.get("cache_read_input_tokens", 0)),
                cache_creation_input_tokens=int(
                    raw_tu.get("cache_creation_input_tokens", 0)
                ),
            )
        return cls(
            cell_id=d["cell_id"],
            prompt=d["prompt"],
            triggered_skill=d.get("triggered_skill"),
            token_usage=token_usage,
            duration_s=float(d["duration_s"]),
            assertions_passed=list(d.get("assertions_passed", [])),
            assertions_failed=list(d.get("assertions_failed", [])),
            raw_output=d.get("raw_output", ""),
        )


# ---------------------------------------------------------------------------
# OptimizeIterationRecord  (one iteration row in an optimization run)
# ---------------------------------------------------------------------------


@dataclass
class OptimizeIterationRecord:
    """One iteration of a skill-description optimization run.

    ``to_dict`` / ``from_dict`` provide a stable round-trip compatible with the
    ``_MISSING``-tolerant pattern used by ``EvalResultRecord``.  Token totals
    are flat ``int`` fields — no ``TokenUsage`` object here (the optimizer
    aggregates per-iteration totals from multiple eval runs).
    """

    # --- required (no default) ---
    iteration: int
    candidate_description: str | None
    train_pass_rate: float
    test_pass_rate: float
    # --- optional / defaulted ---
    train_tokens_total: int = 0
    test_tokens_total: int = 0
    selected: bool = False
    proposal_failed: bool = False
    overfit: bool = False
    train_jsonl_path: str = ""
    test_jsonl_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "candidate_description": self.candidate_description,
            "train_pass_rate": self.train_pass_rate,
            "test_pass_rate": self.test_pass_rate,
            "train_tokens_total": self.train_tokens_total,
            "test_tokens_total": self.test_tokens_total,
            "selected": self.selected,
            "proposal_failed": self.proposal_failed,
            "overfit": self.overfit,
            "train_jsonl_path": self.train_jsonl_path,
            "test_jsonl_path": self.test_jsonl_path,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OptimizeIterationRecord:
        """Reconstruct from a plain dict; tolerates absent optional keys."""
        raw_desc = d.get("candidate_description", _MISSING)
        candidate_description: str | None = (
            None if (raw_desc is _MISSING or raw_desc is None) else str(raw_desc)
        )
        return cls(
            iteration=int(d["iteration"]),
            candidate_description=candidate_description,
            train_pass_rate=float(d["train_pass_rate"]),
            test_pass_rate=float(d["test_pass_rate"]),
            train_tokens_total=int(d.get("train_tokens_total", 0)),
            test_tokens_total=int(d.get("test_tokens_total", 0)),
            selected=bool(d.get("selected", False)),
            proposal_failed=bool(d.get("proposal_failed", False)),
            overfit=bool(d.get("overfit", False)),
            train_jsonl_path=str(d.get("train_jsonl_path", "")),
            test_jsonl_path=str(d.get("test_jsonl_path", "")),
        )


# ---------------------------------------------------------------------------
# OptimizeResult  (summary of a full optimization run)
# ---------------------------------------------------------------------------


@dataclass
class OptimizeResult:
    """Aggregated result of a multi-iteration skill-description optimization.

    ``iterations`` holds the per-iteration records; ``winning_description``
    and ``winning_iteration`` identify the best candidate found.
    ``no_improvement`` is ``True`` when no candidate beat the baseline.
    """

    skill: str
    eval_set_path: str
    seed: int
    n_train: int
    n_test: int
    baseline_description: str
    winning_description: str
    winning_iteration: int
    no_improvement: bool
    iterations: list[OptimizeIterationRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "eval_set_path": self.eval_set_path,
            "seed": self.seed,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "baseline_description": self.baseline_description,
            "winning_description": self.winning_description,
            "winning_iteration": self.winning_iteration,
            "no_improvement": self.no_improvement,
            "iterations": [it.to_dict() for it in self.iterations],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OptimizeResult:
        """Reconstruct from a plain dict; tolerates absent ``iterations``."""
        raw_iters = d.get("iterations", [])
        iterations = [OptimizeIterationRecord.from_dict(x) for x in raw_iters]
        return cls(
            skill=str(d["skill"]),
            eval_set_path=str(d["eval_set_path"]),
            seed=int(d["seed"]),
            n_train=int(d["n_train"]),
            n_test=int(d["n_test"]),
            baseline_description=str(d["baseline_description"]),
            winning_description=str(d["winning_description"]),
            winning_iteration=int(d["winning_iteration"]),
            no_improvement=bool(d["no_improvement"]),
            iterations=iterations,
        )


# ---------------------------------------------------------------------------
# ProposerFn  (type alias for skill-description proposal callables)
# ---------------------------------------------------------------------------

# A proposer takes the current description and the list of train eval records,
# and returns a new candidate description (or None to signal exhaustion/failure).
ProposerFn = Callable[["str", "list[EvalResultRecord]"], "str | None"]


# ---------------------------------------------------------------------------
# make_cell_id
# ---------------------------------------------------------------------------


def make_cell_id(prompt_index: int, variant_id: int, run_number: int) -> str:
    """Return a deterministic, human-readable cell identifier.

    The format is stable so ``--resume`` can match present cell_ids across
    runs without relying on randomness or wall-clock time.

    Example: ``make_cell_id(0, 1, 2)`` → ``"p0-v1-r2"``
    """
    return f"p{prompt_index}-v{variant_id}-r{run_number}"
