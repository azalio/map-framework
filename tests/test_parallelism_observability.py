"""Tests for src/mapify_cli/parallelism_observability.py (ST-011).

Covers:
  - VC1: writer is no-op by default (no file created, returns False)
  - VC2: schema and reason-code constants are importable; ALL_REASON_CODES has
         all 9 codes; a sample ParallelismReport dict conforms to the TypedDict.
  - Parity: worktree reason-code constants match runner's _WT_REASON_* values.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Suppress bytecode pollution in the generated runner tree (learned rule:
# Test-Induced Bytecode Cache Pollution in Generated Trees).
# ---------------------------------------------------------------------------
sys.dont_write_bytecode = True

from mapify_cli.parallelism_observability import (  # noqa: E402
    ALL_REASON_CODES,
    REASON_DIRTY_MERGE_TARGET,
    REASON_DISPATCH_SERIAL,
    REASON_MERGE_CONFLICT,
    REASON_MONITOR_REJECTED_SUBTASK,
    REASON_NOT_GIT_REPO,
    REASON_PARALLEL_CAPPED_BY_MAX_ACTORS,
    REASON_POST_WAVE_GATE_FAILED,
    REASON_WORKTREE_CREATE_FAILED,
    REASON_WORKTREE_UNSUPPORTED,
    ColorGroupDecision,
    ParallelismReport,
    write_parallelism_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUNNER_SCRIPT = (
    Path(__file__).parent.parent
    / "src/mapify_cli/templates/map/scripts/map_step_runner.py"
)


def _sample_report(run_id: str = "run-test-001") -> ParallelismReport:
    """Return a minimal conformant ParallelismReport dict for shape tests."""
    group: ColorGroupDecision = {
        "group_id": "wave-1-group-A",
        "planned_mode": "sequential",
        "actual_mode": "sequential",
        "worktree_status": "skipped",
        "reason_code": None,
        "dispatch_count": 2,
    }
    report: ParallelismReport = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "generated_at": "2026-06-29T23:40:00Z",
        "total_subtasks": 4,
        "total_edges": 3,
        "total_waves": 2,
        "max_wave_width": 1,
        "color_group_breakdown": [group],
    }
    return report


# ---------------------------------------------------------------------------
# writer is no-op by default
# ---------------------------------------------------------------------------


def test_writer_noop_by_default(tmp_path: Path) -> None:
    """Calling write_parallelism_report with default enabled=False must not
    create the output file and must return False."""
    out_path = tmp_path / "parallelism.json"
    result = write_parallelism_report(_sample_report(), out_path)

    assert result is False, "write_parallelism_report must return False when disabled"
    assert not out_path.exists(), (
        "write_parallelism_report must NOT create the file when enabled=False"
    )


def test_writer_noop_explicit_false(tmp_path: Path) -> None:
    """Explicit enabled=False also keeps writer dormant."""
    out_path = tmp_path / "runs" / "r1" / "parallelism.json"
    result = write_parallelism_report(_sample_report(), out_path, enabled=False)

    assert result is False
    assert not out_path.exists()


def test_writer_active_when_enabled(tmp_path: Path) -> None:
    """Sanity: enabled=True actually writes the file (gates work both ways)."""
    out_path = tmp_path / "runs" / "r2" / "parallelism.json"
    result = write_parallelism_report(_sample_report("r2"), out_path, enabled=True)

    assert result is True
    assert out_path.exists(), "File must be created when enabled=True"


# ---------------------------------------------------------------------------
# schema and reason-code constants importable; ALL_REASON_CODES complete
# ---------------------------------------------------------------------------


def test_schema_and_reason_codes_importable() -> None:
    """ParallelismReport, ColorGroupDecision, and all reason-code constants
    import cleanly; ALL_REASON_CODES contains exactly the 9 canonical codes;
    a sample dict conforms to the TypedDict shape."""
    # ALL_REASON_CODES completeness
    expected_codes = {
        REASON_NOT_GIT_REPO,
        REASON_WORKTREE_UNSUPPORTED,
        REASON_WORKTREE_CREATE_FAILED,
        REASON_DIRTY_MERGE_TARGET,
        REASON_DISPATCH_SERIAL,
        REASON_PARALLEL_CAPPED_BY_MAX_ACTORS,
        REASON_MONITOR_REJECTED_SUBTASK,
        REASON_MERGE_CONFLICT,
        REASON_POST_WAVE_GATE_FAILED,
    }
    assert len(expected_codes) == 9, "Should have exactly 9 reason codes"
    assert ALL_REASON_CODES == expected_codes, (
        f"ALL_REASON_CODES mismatch.\n"
        f"Missing: {expected_codes - ALL_REASON_CODES}\n"
        f"Extra: {ALL_REASON_CODES - expected_codes}"
    )

    # Sample dict conforms to ParallelismReport TypedDict shape
    report = _sample_report()
    required_fields = {
        "schema_version",
        "run_id",
        "generated_at",
        "total_subtasks",
        "total_edges",
        "total_waves",
        "max_wave_width",
        "color_group_breakdown",
    }
    missing = required_fields - set(report.keys())
    assert not missing, f"Sample report missing fields: {missing}"

    # ColorGroupDecision shape
    group = report["color_group_breakdown"][0]
    group_required = {
        "group_id",
        "planned_mode",
        "actual_mode",
        "worktree_status",
        "reason_code",
        "dispatch_count",
    }
    missing_group = group_required - set(group.keys())
    assert not missing_group, f"ColorGroupDecision missing fields: {missing_group}"


def test_detection_not_implemented() -> None:
    """Detection-by-tool-call-count must NOT be present in the module."""
    import mapify_cli.parallelism_observability as mod

    for attr in dir(mod):
        assert "tool_call" not in attr.lower(), (
            f"Unexpected tool-call-count detection attribute found: {attr!r}. "
            "Detection is Slice 5 only."
        )


# ---------------------------------------------------------------------------
# Parity test: worktree reason codes match runner's _WT_REASON_* constants
# ---------------------------------------------------------------------------


def _load_runner_module() -> object:
    """Import the rendered runner script as a module (bytecode-free).

    The runner does ``from map_utils import get_branch_name`` at module level,
    which fails outside an installed MAP project.  We inject a stub into
    sys.modules before exec so the import resolves without a real map_utils.
    The stub is cleaned up after exec to avoid polluting the test session.
    """
    if not _RUNNER_SCRIPT.exists():
        pytest.skip(f"Runner script not found: {_RUNNER_SCRIPT}")

    import types

    # Stub out map_utils so the runner's top-level import doesn't abort.
    stub = types.ModuleType("map_utils")
    stub.get_branch_name = lambda *a, **kw: "stub"  # type: ignore[attr-defined]
    injected = "map_utils" not in sys.modules
    if injected:
        sys.modules["map_utils"] = stub

    try:
        spec = importlib.util.spec_from_file_location(
            "_map_step_runner_parity", _RUNNER_SCRIPT
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Suppress bytecode in the generated tree (learned rule)
        if mod.__spec__ is not None:
            mod.__spec__.cached = None
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except SystemExit:
            pass  # runner may call sys.exit at module level in some guard paths
        return mod
    finally:
        if injected:
            sys.modules.pop("map_utils", None)


def test_worktree_reason_codes_match_runner() -> None:
    """The observability module's worktree reason-code constants must equal the
    runner's _WT_REASON_* constants to prevent silent drift (contract-first)."""
    runner = _load_runner_module()

    parity_pairs = [
        (REASON_NOT_GIT_REPO, "_WT_REASON_NOT_GIT_REPO"),
        (REASON_WORKTREE_UNSUPPORTED, "_WT_REASON_UNSUPPORTED"),
        (REASON_WORKTREE_CREATE_FAILED, "_WT_REASON_CREATE_FAILED"),
        (REASON_DIRTY_MERGE_TARGET, "_WT_REASON_DIRTY_MERGE_TARGET"),
    ]

    for obs_value, runner_attr in parity_pairs:
        runner_value = getattr(runner, runner_attr, None)
        assert runner_value is not None, (
            f"Runner is missing constant {runner_attr!r} — "
            "was ST-009 merged correctly?"
        )
        assert obs_value == runner_value, (
            f"Reason-code drift detected!\n"
            f"  observability.{obs_value!r}\n"
            f"  runner.{runner_attr} = {runner_value!r}\n"
            "Update the observability module or the runner to restore parity."
        )
