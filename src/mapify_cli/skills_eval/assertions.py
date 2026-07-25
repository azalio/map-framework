"""Pure, deterministic assertion runner for skill eval cells.

No LLM, no subprocess, no file I/O, no network.  Same (spec, result)
always produces the same verdict (INV-3: no ``import anthropic``,
no ANTHROPIC_API_KEY).

Assertion types
---------------
- contains      – value in raw_output
- not_contains  – value not in raw_output
- regex         – re.search(pattern, raw_output) is not None
- valid_json    – raw_output.strip() parses via json.loads
- trigger       – triggered_skill == skill
- not_trigger   – triggered_skill != skill  (None-safe: SC-3)

Robustness
----------
- Unknown type  → FAIL, detail "unknown assertion type: <t>"
- Missing key   → FAIL, clear detail, no KeyError
- Invalid regex → FAIL, detail includes re.error message
- run_assertion never raises
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from mapify_cli.skills_eval.eval_schema import DispatchResult

# ---------------------------------------------------------------------------
# AssertionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssertionResult:
    """Immutable result of a single assertion evaluation."""

    passed: bool
    type: str
    detail: str


# ---------------------------------------------------------------------------
# Internal helpers — one per assertion type
# ---------------------------------------------------------------------------


def _assert_contains(spec: dict[str, object], result: DispatchResult) -> AssertionResult:
    """PASS iff spec["value"] is a substring of result.raw_output."""
    value = spec.get("value")
    if not isinstance(value, str):
        return AssertionResult(
            passed=False,
            type="contains",
            detail=f"contains: missing or non-string 'value' key (got {type(value).__name__!r})",
        )
    matched = value in result.raw_output
    verb = "found in" if matched else "not found in"
    return AssertionResult(
        passed=matched,
        type="contains",
        detail=f"contains {value!r} -> {'PASS' if matched else 'FAIL'} ({verb} raw_output)",
    )


def _assert_not_contains(spec: dict[str, object], result: DispatchResult) -> AssertionResult:
    """PASS iff spec["value"] is NOT a substring of result.raw_output."""
    value = spec.get("value")
    if not isinstance(value, str):
        return AssertionResult(
            passed=False,
            type="not_contains",
            detail=(
                f"not_contains: missing or non-string 'value' key "
                f"(got {type(value).__name__!r})"
            ),
        )
    matched = value in result.raw_output
    return AssertionResult(
        passed=not matched,
        type="not_contains",
        detail=(
            f"not_contains {value!r} -> {'PASS' if not matched else 'FAIL'} "
            f"({'absent from' if not matched else 'found in'} raw_output)"
        ),
    )


def _assert_regex(spec: dict[str, object], result: DispatchResult) -> AssertionResult:
    """PASS iff re.search(pattern, raw_output) is not None.

    Invalid regex pattern -> FAIL (detail includes re.error message).
    """
    pattern = spec.get("pattern")
    if not isinstance(pattern, str):
        return AssertionResult(
            passed=False,
            type="regex",
            detail=(
                f"regex: missing or non-string 'pattern' key "
                f"(got {type(pattern).__name__!r})"
            ),
        )
    try:
        match = re.search(pattern, result.raw_output)
    except re.error as exc:
        return AssertionResult(
            passed=False,
            type="regex",
            detail=f"regex {pattern!r} -> FAIL (invalid pattern: {exc})",
        )
    matched = match is not None
    return AssertionResult(
        passed=matched,
        type="regex",
        detail=(
            f"regex {pattern!r} -> {'PASS' if matched else 'FAIL'} "
            f"({'match found' if matched else 'no match'} in raw_output)"
        ),
    )


def _assert_valid_json(
    _spec: dict[str, object], result: DispatchResult
) -> AssertionResult:
    """PASS iff result.raw_output.strip() parses via json.loads."""
    try:
        json.loads(result.raw_output.strip())
        return AssertionResult(
            passed=True,
            type="valid_json",
            detail="valid_json -> PASS (raw_output is well-formed JSON)",
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return AssertionResult(
            passed=False,
            type="valid_json",
            detail=f"valid_json -> FAIL (JSON parse error: {exc})",
        )


def _assert_trigger(spec: dict[str, object], result: DispatchResult) -> AssertionResult:
    """PASS iff result.triggered_skill == spec["skill"]."""
    skill = spec.get("skill")
    if not isinstance(skill, str):
        return AssertionResult(
            passed=False,
            type="trigger",
            detail=(
                f"trigger: missing or non-string 'skill' key "
                f"(got {type(skill).__name__!r})"
            ),
        )
    matched = result.triggered_skill == skill
    return AssertionResult(
        passed=matched,
        type="trigger",
        detail=(
            f"trigger {skill!r} -> {'PASS' if matched else 'FAIL'} "
            f"(triggered_skill={result.triggered_skill!r})"
        ),
    )


def _assert_not_trigger(
    spec: dict[str, object], result: DispatchResult
) -> AssertionResult:
    """PASS iff result.triggered_skill != spec["skill"].

    SC-3: correctly handles triggered_skill is None —
    ``not_trigger {"skill": "map-x"}`` PASSES when triggered_skill is None.
    """
    skill = spec.get("skill")
    if not isinstance(skill, str):
        return AssertionResult(
            passed=False,
            type="not_trigger",
            detail=(
                f"not_trigger: missing or non-string 'skill' key "
                f"(got {type(skill).__name__!r})"
            ),
        )
    # None != skill is True, so this naturally satisfies SC-3.
    matched = result.triggered_skill != skill
    return AssertionResult(
        passed=matched,
        type="not_trigger",
        detail=(
            f"not_trigger {skill!r} -> {'PASS' if matched else 'FAIL'} "
            f"(triggered_skill={result.triggered_skill!r})"
        ),
    )


# ---------------------------------------------------------------------------
# Dispatcher table
# ---------------------------------------------------------------------------

# Intent: map assertion type string to its handler function.
# Using a dict avoids a long if/elif chain and makes type extension O(1).
_ASSERTION_HANDLERS = {
    "contains": _assert_contains,
    "not_contains": _assert_not_contains,
    "regex": _assert_regex,
    "valid_json": _assert_valid_json,
    "trigger": _assert_trigger,
    "not_trigger": _assert_not_trigger,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_assertion(spec: dict[str, object], result: DispatchResult) -> AssertionResult:
    """Evaluate a single assertion spec against a DispatchResult.

    Never raises — unknown types and missing keys produce FAIL results with
    human-debuggable ``detail`` strings.

    Parameters
    ----------
    spec:
        Dict with at least a ``"type"`` key and any type-specific keys.
    result:
        The DispatchResult from the dispatcher (ST-002).

    Returns
    -------
    AssertionResult
        Frozen dataclass; ``passed`` is the verdict, ``detail`` explains why.
    """
    assertion_type = spec.get("type")
    if not isinstance(assertion_type, str):
        return AssertionResult(
            passed=False,
            type=str(assertion_type),
            detail=(
                f"unknown assertion type: {assertion_type!r} "
                f"(must be str, got {type(assertion_type).__name__!r})"
            ),
        )

    handler = _ASSERTION_HANDLERS.get(assertion_type)
    if handler is None:
        return AssertionResult(
            passed=False,
            type=assertion_type,
            detail=f"unknown assertion type: {assertion_type!r}",
        )

    return handler(spec, result)


def run_assertions(
    specs: list[dict[str, object]],
    result: DispatchResult,
) -> tuple[list[str], list[str]]:
    """Run all assertions in *specs* against *result*.

    Returns
    -------
    tuple[list[str], list[str]]
        ``(passed_details, failed_details)`` — the ``detail`` strings of
        passing vs failing assertions, suitable for
        ``EvalResultRecord.assertions_passed`` /
        ``EvalResultRecord.assertions_failed``.
    """
    passed_details: list[str] = []
    failed_details: list[str] = []

    for spec in specs:
        ar = run_assertion(spec, result)
        if ar.passed:
            passed_details.append(ar.detail)
        else:
            failed_details.append(ar.detail)

    return passed_details, failed_details
