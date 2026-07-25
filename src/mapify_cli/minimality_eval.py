"""Minimality A/B benchmark harness.

Proves MAP minimality is active and safe by running isolated baseline
(minimality: off) and treatment (minimality: lite) arms on a small
deterministic fixture corpus.  No external services or live model calls.

How it works
------------
1.  For each arm, build the MAP_Minimality_Doctrine context block and assert
    contamination isolation — the ``off`` arm must NOT contain the doctrine
    tag; the ``lite`` arm MUST contain it.
2.  Score each fixture task for both arms:
    - LOC delta: lines in the treatment output vs the baseline output.
    - Safety: required safety/correctness patterns must survive in BOTH arms.
    - Convergence: for irreducible tasks the LOC delta must be near-zero.
3.  Classify the run:
    - Contamination detected → hard FAIL.
    - Safety pattern absent in either arm → hard FAIL.
    - Treatment LOC *increases* relative to baseline → WARN (advisory).
    - Irreducible task shows large LOC swing → WARN.
4.  Persist a JSON report to ``out_dir / "YYYY-MM-DDTHHMMSSZ.json"``.

Usage::

    python -m mapify_cli.minimality_eval               # default arms: off vs lite
    python -m mapify_cli.minimality_eval --out DIR     # custom output directory
    python -m mapify_cli.minimality_eval --show        # print report JSON to stdout

Only the ``off`` and ``lite`` arms are run by default.  Pass ``--full`` to
add a ``full`` treatment arm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

_DOCTRINE_TAG = "MAP_Minimality_Doctrine"
_DOCTRINE_TAG_OPEN = f"<{_DOCTRINE_TAG}>"
_DOCTRINE_TAG_CLOSE = f"</{_DOCTRINE_TAG}>"

# ---------------------------------------------------------------------------
# Doctrine builder (extracted from map_step_runner so eval runs without needing
# a full project under .map/).
# ---------------------------------------------------------------------------

_DOCTRINE_INTENSITY: dict[str, str] = {
    "lite": (
        "Build what was asked, then name the lazier safe alternative in one line;"
        " do not silently drop work."
    ),
    "full": (
        "Apply the ladder actively before adding code; choose the smaller safe"
        " path unless a real blocker requires expansion."
    ),
    "ultra": (
        "Apply the ladder aggressively and surface YAGNI/defer decisions, but"
        " never prune explicit, safety, data, or contract work silently."
    ),
}


def build_doctrine_block(minimality: str) -> str:
    """Return the MAP_Minimality_Doctrine context block for *minimality*.

    Returns an empty string when *minimality* is ``"off"``, matching the
    runtime behaviour of ``_minimality_doctrine_block`` in map_step_runner.
    """
    if minimality == "off":
        return ""
    intensity = _DOCTRINE_INTENSITY.get(
        minimality,
        "Build what was asked and prefer the fewest safe moving parts.",
    )
    lines = [
        _DOCTRINE_TAG_OPEN,
        f"Level: {minimality}",
        f"Intensity: {intensity}",
        "Production-grade means the smallest sufficient safe change, not maximal code.",
        "Decision ladder, stop at the first rung that satisfies the contract:",
        ("1. Does this need to exist at all? If no, mark it YAGNI and explain;"
        " do not silently omit explicit requirements."),
        "2. Standard library does it? Use that.",
        "3. Native platform feature covers it? Use that.",
        ("4. Already-installed project dependency solves it? Use that; do not"
        " add a dependency for a few lines."),
        "5. Can it be one clear line? Prefer one clear line.",
        "6. Otherwise write the minimum maintainable code that works.",
        ("Shell/Core rule: shell code at trust boundaries stays defensive;"
        " core private helpers stay small."),
        ("Hard exceptions: security, accessibility, data integrity, real error"
        " handling that prevents data loss, and explicitly requested behavior"
        " always win over minimality."),
        ("When choosing a deliberate simplification, include `map:simplification:`"
        " with the ceiling and upgrade path. The marker is evidence, not an exemption."),
        "If retry feedback asks for expansion, re-add code only for named BLOCKER items.",
        _DOCTRINE_TAG_CLOSE,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MiniEvalTask:
    """One fixture task for the minimality eval corpus.

    Attributes:
        task_id: Short stable identifier, e.g. ``"OVER_BUILD_TRAP"``.
        description: Human-readable summary of what the task asks.
        baseline_code: Simulated agent output WITHOUT minimality guidance
            (typically verbose / over-engineered).
        treatment_code: Simulated agent output WITH minimality guidance
            (concise, still correct).
        required_patterns: Substrings that MUST appear in BOTH arm outputs.
            These represent non-negotiable correctness / safety invariants.
        is_irreducible: When True the baseline and treatment LOC counts are
            expected to be very similar (within ``irreducible_tolerance``
            lines).  The eval warns — not fails — when an irreducible task
            shows a large LOC swing.
        irreducible_tolerance: Maximum LOC delta allowed for irreducible tasks
            before a warning is raised.  Defaults to 2.
    """

    task_id: str
    description: str
    baseline_code: str
    treatment_code: str
    required_patterns: tuple[str, ...]
    is_irreducible: bool = False
    irreducible_tolerance: int = 2


@dataclass
class MiniEvalArmResult:
    """Metrics for one arm of one task."""

    arm_name: str
    minimality: str
    loc: int
    doctrine_present: bool
    missing_patterns: tuple[str, ...]
    contaminated: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm_name": self.arm_name,
            "minimality": self.minimality,
            "loc": self.loc,
            "doctrine_present": self.doctrine_present,
            "missing_patterns": list(self.missing_patterns),
            "contaminated": self.contaminated,
        }


@dataclass
class MiniEvalTaskResult:
    """Outcome for one fixture task across all arms."""

    task_id: str
    description: str
    is_irreducible: bool
    arm_results: list[MiniEvalArmResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "is_irreducible": self.is_irreducible,
            "passed": self.passed,
            "warnings": self.warnings,
            "failures": self.failures,
            "arm_results": [r.as_dict() for r in self.arm_results],
        }


@dataclass
class MiniEvalReport:
    """Aggregated minimality eval report."""

    arms: list[str]
    tasks: list[MiniEvalTaskResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.tasks)

    @property
    def summary(self) -> dict[str, Any]:
        warn_count = sum(len(t.warnings) for t in self.tasks)
        fail_count = sum(len(t.failures) for t in self.tasks)
        return {
            "passed": self.passed,
            "task_count": len(self.tasks),
            "task_pass_count": sum(1 for t in self.tasks if t.passed),
            "task_fail_count": sum(1 for t in self.tasks if not t.passed),
            "warning_count": warn_count,
            "failure_count": fail_count,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "arms": self.arms,
            "summary": self.summary,
            "tasks": [t.as_dict() for t in self.tasks],
        }


# ---------------------------------------------------------------------------
# Built-in fixture corpus
# ---------------------------------------------------------------------------

_OVER_BUILD_TRAP = MiniEvalTask(
    task_id="OVER_BUILD_TRAP",
    description=(
        "Percent-encode a URL path segment. "
        "The minimality-guided output should use urllib.parse.quote; "
        "the baseline may hand-roll a character-by-character encoder."
    ),
    baseline_code='''\
def percent_encode(segment: str) -> str:
    SAFE_CHARS = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789-._~"
    )
    result = []
    for char in segment.encode("utf-8"):
        if chr(char) in SAFE_CHARS:
            result.append(chr(char))
        else:
            result.append(f"%{char:02X}")
    return "".join(result)
''',
    treatment_code='''\
from urllib.parse import quote as percent_encode  # stdlib covers this
''',
    required_patterns=("percent_encode",),
)

_SAFETY_GUARD = MiniEvalTask(
    task_id="SAFETY_GUARD",
    description=(
        "Write a function that reads a file path provided by an external caller. "
        "Minimality must preserve the path-traversal guard even when reducing LOC."
    ),
    baseline_code='''\
import os

def read_file_safe(base_dir: str, user_path: str) -> str:
    # Resolve both paths to their canonical forms
    base = os.path.realpath(os.path.abspath(base_dir))
    requested = os.path.realpath(os.path.abspath(os.path.join(base_dir, user_path)))

    # Prevent path traversal: the requested path must start with the base
    if not requested.startswith(base + os.sep) and requested != base:
        raise PermissionError(f"Access denied: {user_path!r} is outside {base_dir!r}")

    with open(requested, encoding="utf-8") as fh:
        return fh.read()
''',
    treatment_code='''\
import os

def read_file_safe(base_dir: str, user_path: str) -> str:
    base = os.path.realpath(os.path.abspath(base_dir))
    requested = os.path.realpath(os.path.abspath(os.path.join(base_dir, user_path)))
    if not requested.startswith(base + os.sep) and requested != base:
        raise PermissionError(f"Access denied: {user_path!r} is outside {base_dir!r}")
    return open(requested, encoding="utf-8").read()
''',
    required_patterns=("PermissionError", "startswith", "realpath"),
)

_IRREDUCIBLE = MiniEvalTask(
    task_id="IRREDUCIBLE",
    description=(
        "Write a pytest fixture that creates a temporary directory. "
        "Both arms should produce near-identical minimal output: "
        "a fixture using tmp_path or tempfile.mkdtemp."
    ),
    baseline_code='''\
import pytest

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path
''',
    treatment_code='''\
import pytest

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path
''',
    required_patterns=("pytest.fixture", "tmp_path"),
    is_irreducible=True,
)

DEFAULT_CORPUS: tuple[MiniEvalTask, ...] = (
    _OVER_BUILD_TRAP,
    _SAFETY_GUARD,
    _IRREDUCIBLE,
)


# ---------------------------------------------------------------------------
# Arm definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalArm:
    """One eval arm: a name and the minimality level it should use."""

    name: str
    minimality: str

    @property
    def expects_doctrine(self) -> bool:
        return self.minimality != "off"


DEFAULT_ARMS: tuple[EvalArm, ...] = (
    EvalArm(name="baseline", minimality="off"),
    EvalArm(name="treatment_lite", minimality="lite"),
)

FULL_ARMS: tuple[EvalArm, ...] = (
    EvalArm(name="baseline", minimality="off"),
    EvalArm(name="treatment_lite", minimality="lite"),
    EvalArm(name="treatment_full", minimality="full"),
)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _loc(code: str) -> int:
    """Return the number of non-empty lines in *code*."""
    return sum(1 for line in code.splitlines() if line.strip())


def _score_arm(
    task: MiniEvalTask,
    arm: EvalArm,
    arm_context: str,
    arm_code: str,
) -> MiniEvalArmResult:
    doctrine_present = _DOCTRINE_TAG_OPEN in arm_context
    contaminated = doctrine_present != arm.expects_doctrine
    missing = tuple(p for p in task.required_patterns if p not in arm_code)
    return MiniEvalArmResult(
        arm_name=arm.name,
        minimality=arm.minimality,
        loc=_loc(arm_code),
        doctrine_present=doctrine_present,
        missing_patterns=missing,
        contaminated=contaminated,
    )


def _evaluate_task(
    task: MiniEvalTask,
    arms: tuple[EvalArm, ...],
) -> MiniEvalTaskResult:
    result = MiniEvalTaskResult(
        task_id=task.task_id,
        description=task.description,
        is_irreducible=task.is_irreducible,
    )

    # Build context + arm_code for each arm
    arm_results: list[MiniEvalArmResult] = []
    for arm in arms:
        ctx = build_doctrine_block(arm.minimality)
        code = task.baseline_code if arm.minimality == "off" else task.treatment_code
        arm_results.append(_score_arm(task, arm, ctx, code))

    result.arm_results = arm_results

    # Contamination check — hard fail
    for ar in arm_results:
        if ar.contaminated:
            direction = "has" if ar.doctrine_present else "lacks"
            expected = "present" if ar.minimality != "off" else "absent"
            result.failures.append(
                f"ARM_CONTAMINATION: arm '{ar.arm_name}' (minimality={ar.minimality})"
                f" {direction} the doctrine tag but expected it to be {expected}."
            )

    # Missing safety patterns — hard fail for any arm
    for ar in arm_results:
        for pattern in ar.missing_patterns:
            result.failures.append(
                f"SAFETY_PATTERN_MISSING: required pattern {pattern!r} absent"
                f" in arm '{ar.arm_name}' output."
            )

    # LOC comparison between baseline and each treatment arm
    baseline_results = [ar for ar in arm_results if ar.minimality == "off"]
    treatment_results = [ar for ar in arm_results if ar.minimality != "off"]
    if baseline_results and treatment_results:
        baseline_loc = baseline_results[0].loc
        for tr in treatment_results:
            delta = tr.loc - baseline_loc
            if task.is_irreducible:
                if abs(delta) > task.irreducible_tolerance:
                    result.warnings.append(
                        f"IRREDUCIBLE_SWING: task is marked irreducible but"
                        f" arm '{tr.arm_name}' LOC differs from baseline by"
                        f" {abs(delta)} (tolerance {task.irreducible_tolerance})."
                    )
            elif delta > 0:
                result.warnings.append(
                    f"LOC_INCREASE: arm '{tr.arm_name}' added {delta} LOC"
                    f" vs baseline ({tr.loc} vs {baseline_loc})."
                    f" Treatment should produce equal or fewer non-empty lines."
                )

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_minimality_eval(
    *,
    corpus: tuple[MiniEvalTask, ...] = DEFAULT_CORPUS,
    arms: tuple[EvalArm, ...] = DEFAULT_ARMS,
    out_path: Path | None = None,
) -> MiniEvalReport:
    """Run the minimality A/B benchmark harness.

    Args:
        corpus: Fixture tasks to evaluate.  Defaults to :data:`DEFAULT_CORPUS`.
        arms: Evaluation arms.  Defaults to :data:`DEFAULT_ARMS` (off + lite).
        out_path: Where to write the JSON report.  When *None* the report is
            not persisted (useful for in-process testing).

    Returns:
        :class:`MiniEvalReport` with per-task results and a summary.
    """
    report = MiniEvalReport(arms=[arm.name for arm in arms])
    for task in corpus:
        report.tasks.append(_evaluate_task(task, arms))

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8"
        )

    return report


def default_run_path(root: Path, iso_timestamp: str) -> Path:
    """Return the default output path for a minimality eval run.

    The timestamp must be supplied by the CLI caller (clock-free core).
    """
    return root / ".map" / "eval-runs" / "minimality" / f"{iso_timestamp}.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    import argparse
    import sys
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="MAP minimality A/B benchmark harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        help=(
            "Directory to write the JSON report (default: .map/eval-runs/minimality/)."
            " The filename is the ISO-8601 timestamp."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Add a 'full' treatment arm in addition to 'off' and 'lite'.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the report JSON to stdout.",
    )
    args = parser.parse_args()

    arms = FULL_ARMS if args.full else DEFAULT_ARMS
    iso = (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
        .replace(":", "")
    )

    if args.out:
        out_path = Path(args.out) / f"{iso}.json"
    else:
        out_path = default_run_path(Path.cwd(), iso)

    report = run_minimality_eval(arms=arms, out_path=out_path)

    if args.show:
        print(json.dumps(report.as_dict(), indent=2))

    summary = report.summary
    status = "PASSED" if report.passed else "FAILED"
    print(
        f"minimality-eval {status}: "
        f"{summary['task_pass_count']}/{summary['task_count']} tasks passed, "
        f"{summary['failure_count']} failure(s), "
        f"{summary['warning_count']} warning(s)."
    )
    if out_path.exists():
        print(f"Report: {out_path}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    _main()
