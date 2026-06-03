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
    def from_dict(cls, d: dict[str, Any]) -> "EvalResultRecord":
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
# make_cell_id
# ---------------------------------------------------------------------------


def make_cell_id(prompt_index: int, variant_id: int, run_number: int) -> str:
    """Return a deterministic, human-readable cell identifier.

    The format is stable so ``--resume`` can match present cell_ids across
    runs without relying on randomness or wall-clock time.

    Example: ``make_cell_id(0, 1, 2)`` → ``"p0-v1-r2"``
    """
    return f"p{prompt_index}-v{variant_id}-r{run_number}"
