"""Tests for src/mapify_cli/parallelism_observability.py.

Pre-ST-003 coverage (original):
  - VC1: writer is no-op by default (no file created, returns False)
  - VC2: schema and reason-code constants are importable; ALL_REASON_CODES has
         all 9 codes; a sample ParallelismReport dict conforms to the TypedDict.
  - Parity: worktree reason-code constants match runner's _WT_REASON_* values.

ST-003 additions (5b.2 classify_dispatch + record_dispatch_actual):
  - VC1 [AC-3-TELEMETRY]: classify_dispatch truth table — all 6 outcomes.
  - VC2 [AC-3-TELEMETRY]: max_in_flight replay from sorted lifecycle events is
      deterministic; NO wall-clock involved.
  - VC3 [AC-3-TELEMETRY]: record_dispatch_actual writes exactly ONE
      ParallelismReport on concurrent path; emits NOTHING on no-op path.
  - VC4 [AC-3-TELEMETRY]: isolation_violation when >1 distinct base_sha;
      skill self-report never authoritative for positive concurrency claim.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Suppress bytecode pollution in the generated runner tree (learned rule:
# Test-Induced Bytecode Cache Pollution in Generated Trees).
# ---------------------------------------------------------------------------
sys.dont_write_bytecode = True

from mapify_cli.parallelism_observability import (
    ALL_DISPATCH_OUTCOMES,
    ALL_REASON_CODES,
    DISPATCH_OUTCOME_CONCURRENT_OBSERVED,
    DISPATCH_OUTCOME_ISOLATION_VIOLATION,
    DISPATCH_OUTCOME_PHANTOM_PARALLEL,
    DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL,
    DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED,
    DISPATCH_OUTCOME_UNKNOWN,
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
    classify_dispatch,
    record_dispatch_actual,
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

    def _stub_branch_name(*_a: object, **_kw: object) -> str:
        del _a, _kw  # del is valid in a def body (illegal in a lambda)
        return "stub"

    stub.get_branch_name = _stub_branch_name  # type: ignore[attr-defined]
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


# ---------------------------------------------------------------------------
# ST-003 (5b.2): classify_dispatch + record_dispatch_actual
# ---------------------------------------------------------------------------


class TestClassifyDispatch:
    """Truth-table tests for the evidence-hierarchy classifier (VC1, VC4)."""

    # VC4: isolation_violation when >1 distinct base_sha (rule 1, highest priority)
    def test_vc4_isolation_violation_two_distinct_shas(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=2,
            max_in_flight=2,
            base_shas=["sha-aaa", "sha-bbb"],  # >1 distinct SHA
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_ISOLATION_VIOLATION

    def test_vc4_isolation_violation_three_distinct_shas(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=3,
            max_in_flight=3,
            base_shas=["sha-aaa", "sha-bbb", "sha-ccc"],
            skill_reported_concurrent=True,
        )
        assert outcome == DISPATCH_OUTCOME_ISOLATION_VIOLATION

    # VC1: concurrent_observed when same-turn ≥2 AND max_in_flight ≥2 (rule 2)
    def test_vc1_concurrent_observed_n2(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=2,
            max_in_flight=2,
            base_shas=["sha-aaa", "sha-aaa"],  # all same — no isolation violation
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_CONCURRENT_OBSERVED

    def test_vc1_concurrent_observed_n5(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=5,
            max_in_flight=3,
            base_shas=["sha-aaa"] * 5,
            skill_reported_concurrent=True,
        )
        assert outcome == DISPATCH_OUTCOME_CONCURRENT_OBSERVED

    def test_vc1_concurrent_observed_large_n(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=10,
            max_in_flight=10,
            base_shas=["sha-xxx"] * 10,
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_CONCURRENT_OBSERVED

    # VC1: same_turn_but_host_sequential when same-turn ≥2 AND max_in_flight ≤1 (rule 3)
    def test_vc1_same_turn_but_host_sequential_n2(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=2,
            max_in_flight=1,
            base_shas=["sha-aaa", "sha-aaa"],
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL

    def test_vc1_same_turn_but_host_sequential_n3_zero_inflight(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=3,
            max_in_flight=0,
            base_shas=[],
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL

    # VC4: skill self-report NOT authoritative for positive concurrency (phantom path)
    def test_vc4_phantom_parallel_skill_reported_but_same_turn_one(self) -> None:
        # skill self-reported concurrent but same_turn_task_count ≤1 (rule 4)
        outcome = classify_dispatch(
            same_turn_task_count=1,
            max_in_flight=0,
            base_shas=["sha-aaa"],
            skill_reported_concurrent=True,  # self-report present but NOT authoritative
        )
        assert outcome == DISPATCH_OUTCOME_PHANTOM_PARALLEL

    def test_vc4_phantom_parallel_skill_reported_but_same_turn_zero(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=0,
            max_in_flight=0,
            base_shas=[],
            skill_reported_concurrent=True,
        )
        assert outcome == DISPATCH_OUTCOME_PHANTOM_PARALLEL

    def test_vc4_phantom_parallel_requires_both_signals_low(self) -> None:
        # F1 guard: skill_reported=True, same_turn<=1, BUT max_in_flight>=2.
        # Both objective signals must confirm ≤1 for phantom_parallel; contradictory
        # evidence (skill_reported + same_turn<=1 BUT max_in_flight>=2) → unknown.
        outcome = classify_dispatch(
            same_turn_task_count=1,
            max_in_flight=2,
            base_shas=["sha-aaa"],
            skill_reported_concurrent=True,
        )
        assert outcome == DISPATCH_OUTCOME_UNKNOWN, (
            f"Contradictory evidence (skill_reported + same_turn<=1 + max_in_flight>=2) "
            f"must resolve to unknown, not phantom_parallel; got {outcome!r}"
        )

    # sequential_observed when same-turn ≤1 AND max_in_flight ≤1 (rule 5)
    def test_vc3_sequential_observed_single_task(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=1,
            max_in_flight=1,
            base_shas=["sha-aaa"],
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED

    def test_vc3_sequential_observed_zero_tasks(self) -> None:
        outcome = classify_dispatch(
            same_turn_task_count=0,
            max_in_flight=0,
            base_shas=[],
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED

    # No-op subtask (no commit/no events) must NOT trigger phantom_parallel (VC3)
    def test_vc3_noop_subtask_no_phantom_alarm(self) -> None:
        # No lifecycle events recorded → same_turn=0, max_in_flight=0,
        # skill_reported=False → should be sequential_observed, not phantom_parallel.
        outcome = classify_dispatch(
            same_turn_task_count=0,
            max_in_flight=0,
            base_shas=[],
            skill_reported_concurrent=False,
        )
        assert outcome == DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED
        assert outcome != DISPATCH_OUTCOME_PHANTOM_PARALLEL

    # ALL_DISPATCH_OUTCOMES completeness — all 6 outcomes present
    def test_all_dispatch_outcomes_completeness(self) -> None:
        expected = {
            DISPATCH_OUTCOME_CONCURRENT_OBSERVED,
            DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL,
            DISPATCH_OUTCOME_PHANTOM_PARALLEL,
            DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED,
            DISPATCH_OUTCOME_ISOLATION_VIOLATION,
            DISPATCH_OUTCOME_UNKNOWN,
        }
        assert ALL_DISPATCH_OUTCOMES == expected
        assert len(ALL_DISPATCH_OUTCOMES) == 6


class TestMaxInFlightReplay:
    """VC2: max_in_flight derived from sorted lifecycle events — NO wall-clock (HC-5)."""

    def _compute_max_in_flight(self, events: list[dict]) -> int:
        """Mirror the runner's deterministic sweep: sort by seq, count started/finished."""
        sorted_evs = sorted(events, key=lambda e: int(e.get("seq", 0)))
        in_flight = 0
        max_in_flight = 0
        for ev in sorted_evs:
            ev_type = ev.get("event", "")
            if ev_type == "started":
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            elif ev_type == "finished":
                in_flight = max(0, in_flight - 1)
        return max_in_flight

    def test_vc2_two_concurrent_tasks_max_inflight_2(self) -> None:
        # Two tasks: both start before either finishes → max_in_flight = 2.
        events = [
            {"seq": 1, "event": "started", "ts": 0.0},
            {"seq": 2, "event": "started", "ts": 0.0},  # ts irrelevant — seq only
            {"seq": 3, "event": "finished", "ts": 0.0},
            {"seq": 4, "event": "finished", "ts": 0.0},
        ]
        assert self._compute_max_in_flight(events) == 2

    def test_vc2_sequential_tasks_max_inflight_1(self) -> None:
        # Two tasks serially: start/finish/start/finish → max_in_flight = 1.
        events = [
            {"seq": 1, "event": "started", "ts": 999.0},  # ts must be ignored
            {"seq": 2, "event": "finished", "ts": 999.1},
            {"seq": 3, "event": "started", "ts": 999.2},
            {"seq": 4, "event": "finished", "ts": 999.3},
        ]
        assert self._compute_max_in_flight(events) == 1

    def test_vc2_out_of_order_delivery_still_deterministic(self) -> None:
        # Events delivered out of seq order — sort by seq must normalise.
        events = [
            {"seq": 4, "event": "finished", "ts": 0.0},
            {"seq": 1, "event": "started", "ts": 0.0},
            {"seq": 3, "event": "started", "ts": 0.0},
            {"seq": 2, "event": "finished", "ts": 0.0},
        ]
        # seq order: started(1), finished(2), started(3), finished(4) → serial → 1
        assert self._compute_max_in_flight(events) == 1

    def test_vc2_three_concurrent_tasks_max_inflight_3(self) -> None:
        events = [
            {"seq": 1, "event": "started", "ts": 0.0},
            {"seq": 2, "event": "started", "ts": 0.0},
            {"seq": 3, "event": "started", "ts": 0.0},
            {"seq": 4, "event": "finished", "ts": 0.0},
            {"seq": 5, "event": "finished", "ts": 0.0},
            {"seq": 6, "event": "finished", "ts": 0.0},
        ]
        assert self._compute_max_in_flight(events) == 3

    def test_vc2_no_events_zero_max_inflight(self) -> None:
        assert self._compute_max_in_flight([]) == 0

    def test_vc2_classify_concurrent_after_replay(self) -> None:
        """Full integration: replay → max_in_flight → classify → concurrent_observed."""
        events = [
            {"seq": 1, "event": "started", "ts": 0.0},
            {"seq": 2, "event": "started", "ts": 0.0},
            {"seq": 3, "event": "finished", "ts": 0.0},
            {"seq": 4, "event": "finished", "ts": 0.0},
        ]
        max_in_flight = self._compute_max_in_flight(events)
        outcome = classify_dispatch(
            same_turn_task_count=2,
            max_in_flight=max_in_flight,
            base_shas=["sha-abc", "sha-abc"],
            skill_reported_concurrent=False,
        )
        assert max_in_flight == 2
        assert outcome == DISPATCH_OUTCOME_CONCURRENT_OBSERVED


class TestRecordDispatchActual:
    """VC3: record_dispatch_actual writes exactly ONE report on concurrent path;
    emits NOTHING on any other outcome (no file created, returns False)."""

    def _make_report(self, run_id: str = "test-run-001") -> ParallelismReport:
        group: ColorGroupDecision = {
            "group_id": "ST-X|ST-Y",
            "planned_mode": "concurrent",
            "actual_mode": "concurrent_observed",
            "worktree_status": "ok",
            "reason_code": None,
            "dispatch_count": 2,
        }
        report: ParallelismReport = {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "generated_at": "2026-06-29T00:00:00Z",
            "total_subtasks": 2,
            "total_edges": 0,
            "total_waves": 1,
            "max_wave_width": 2,
            "color_group_breakdown": [group],
        }
        return report

    # Concurrent path: one file written, returns True
    def test_vc3_concurrent_path_writes_exactly_one_file(self, tmp_path: Path) -> None:
        out = tmp_path / "parallelism.json"
        result = record_dispatch_actual(self._make_report(), out, DISPATCH_OUTCOME_CONCURRENT_OBSERVED)
        assert result is True
        assert out.exists(), "parallelism.json must be written on concurrent path"
        data = json.loads(out.read_text())
        assert data["run_id"] == "test-run-001"
        assert data["schema_version"] == "1.0.0"

    # No-op paths: no file, returns False for every non-concurrent outcome
    @pytest.mark.parametrize("outcome", [
        DISPATCH_OUTCOME_SAME_TURN_BUT_HOST_SEQUENTIAL,
        DISPATCH_OUTCOME_PHANTOM_PARALLEL,
        DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED,
        DISPATCH_OUTCOME_ISOLATION_VIOLATION,
        DISPATCH_OUTCOME_UNKNOWN,
    ])
    def test_vc3_noop_on_non_concurrent_outcome(self, tmp_path: Path, outcome: str) -> None:
        out = tmp_path / "parallelism.json"
        result = record_dispatch_actual(self._make_report(), out, outcome)
        assert result is False, f"Expected no-op for outcome={outcome!r}"
        assert not out.exists(), (
            f"parallelism.json must NOT be created for outcome={outcome!r}"
        )

    # Sequential no-op path explicitly named (HC-1 dormancy contract)
    def test_vc3_sequential_default_emits_nothing(self, tmp_path: Path) -> None:
        out = tmp_path / "runs" / "r1" / "parallelism.json"
        result = record_dispatch_actual(
            self._make_report(), out, DISPATCH_OUTCOME_SEQUENTIAL_OBSERVED
        )
        assert result is False
        assert not out.exists()
        # Parent dir must also not be created (truly no-op)
        assert not (tmp_path / "runs").exists()

    # Calling twice on concurrent path must not duplicate content (idempotent overwrite)
    def test_vc3_concurrent_path_second_write_overwrites(self, tmp_path: Path) -> None:
        out = tmp_path / "parallelism.json"
        record_dispatch_actual(self._make_report("run-A"), out, DISPATCH_OUTCOME_CONCURRENT_OBSERVED)
        record_dispatch_actual(self._make_report("run-B"), out, DISPATCH_OUTCOME_CONCURRENT_OBSERVED)
        data = json.loads(out.read_text())
        assert data["run_id"] == "run-B"  # last write wins; one file still present
