"""
Tests for Ralph Loop State Management.

Run with: pytest tests/test_ralph_state.py -v
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mapify_cli.ralph_state import (
    VALID_TRANSITIONS,
    CircuitBreakerConfig,
    FinalVerificationResult,
    InvalidTransitionError,
    IterationMetrics,
    RalphLoopPhase,
    RalphLoopState,
    RootCauseAnalysis,
    check_circuit_breaker,
    get_improvement_rate,
    is_thrashing,
    prune_failure_history,
    sanitize_branch_name,
    summarize_failure,
)


class TestRalphLoopPhase:
    """Tests for RalphLoopPhase enum."""

    def test_all_phases_defined(self) -> None:
        """Verify all expected phases exist."""
        expected_phases = {
            "init",
            "decomposition",
            "execution",
            "final_verification",
            "re_decomposition",
            "complete",
            "escalate",
            "hard_stop",
            "recovery",
            "wont_do",
        }
        actual_phases = {phase.value for phase in RalphLoopPhase}
        assert actual_phases == expected_phases

    def test_terminal_states_have_no_transitions(self) -> None:
        """Terminal states (complete, wont_do) should have no valid transitions."""
        assert VALID_TRANSITIONS[RalphLoopPhase.COMPLETE] == []
        assert VALID_TRANSITIONS[RalphLoopPhase.WONT_DO] == []


class TestRalphLoopState:
    """Tests for RalphLoopState dataclass."""

    def test_default_state(self) -> None:
        """New state should start in INIT phase."""
        state = RalphLoopState()
        assert state.phase == RalphLoopPhase.INIT
        assert state.plan_iteration == 1
        assert state.total_tool_calls == 0
        assert state.schema_version == 1
        assert state.failure_summaries == []

    def test_valid_transition(self) -> None:
        """Valid transitions should succeed."""
        state = RalphLoopState()
        state.transition(RalphLoopPhase.DECOMPOSITION)
        assert state.phase == RalphLoopPhase.DECOMPOSITION

        state.transition(RalphLoopPhase.EXECUTION)
        assert state.phase == RalphLoopPhase.EXECUTION

    def test_invalid_transition_raises_error(self) -> None:
        """Invalid transitions should raise InvalidTransitionError."""
        state = RalphLoopState()
        # Cannot go directly from INIT to COMPLETE
        with pytest.raises(InvalidTransitionError) as exc_info:
            state.transition(RalphLoopPhase.COMPLETE)
        assert "Cannot transition from init to complete" in str(exc_info.value)
        assert "Valid transitions:" in str(exc_info.value)

    def test_transition_updates_timestamp(self) -> None:
        """Transitions should update updated_at timestamp."""
        state = RalphLoopState()
        original_time = state.updated_at
        state.transition(RalphLoopPhase.DECOMPOSITION)
        # Updated time should be different (or same if very fast)
        assert state.updated_at >= original_time

    def test_reset_limits(self) -> None:
        """reset_limits should reset tool call counter."""
        state = RalphLoopState(total_tool_calls=100)
        state.reset_limits()
        assert state.total_tool_calls == 0

    def test_to_dict(self) -> None:
        """to_dict should serialize state correctly."""
        state = RalphLoopState(
            phase=RalphLoopPhase.EXECUTION,
            plan_iteration=2,
            total_tool_calls=15,
            failure_summaries=["failure 1"],
        )
        data = state.to_dict()
        assert data["phase"] == "execution"
        assert data["plan_iteration"] == 2
        assert data["total_tool_calls"] == 15
        assert data["failure_summaries"] == ["failure 1"]
        assert data["schema_version"] == 1

    def test_from_dict(self) -> None:
        """from_dict should deserialize state correctly."""
        data = {
            "phase": "execution",
            "plan_iteration": 2,
            "total_tool_calls": 15,
            "failure_summaries": ["failure 1"],
            "started_at": "2025-01-26T10:00:00",
            "updated_at": "2025-01-26T10:15:00",
        }
        state = RalphLoopState.from_dict(data)
        assert state.phase == RalphLoopPhase.EXECUTION
        assert state.plan_iteration == 2
        assert state.total_tool_calls == 15
        assert state.failure_summaries == ["failure 1"]

    def test_from_dict_with_defaults(self) -> None:
        """from_dict should use defaults for missing fields."""
        data = {"phase": "init"}
        state = RalphLoopState.from_dict(data)
        assert state.phase == RalphLoopPhase.INIT
        assert state.plan_iteration == 1
        assert state.total_tool_calls == 0

    def test_save_and_load(self, tmp_path: Path) -> None:
        """State should round-trip through save/load."""
        state_file = tmp_path / ".map" / "test-branch" / "ralph_state.json"

        state = RalphLoopState(
            phase=RalphLoopPhase.EXECUTION,
            plan_iteration=2,
            total_tool_calls=15,
            failure_summaries=["Iteration 1: failed"],
        )

        state.save(state_file)
        assert state_file.exists()

        loaded = RalphLoopState.load(state_file)
        assert loaded.phase == RalphLoopPhase.EXECUTION
        assert loaded.plan_iteration == 2
        assert loaded.total_tool_calls == 15
        assert loaded.failure_summaries == ["Iteration 1: failed"]

    def test_load_missing_file_returns_default(self, tmp_path: Path) -> None:
        """Loading non-existent file should return fresh state."""
        state_file = tmp_path / "nonexistent.json"
        state = RalphLoopState.load(state_file)
        assert state.phase == RalphLoopPhase.INIT

    def test_load_invalid_json_returns_default(self, tmp_path: Path) -> None:
        """Loading invalid JSON should return fresh state."""
        state_file = tmp_path / "invalid.json"
        state_file.write_text("not valid json")
        state = RalphLoopState.load(state_file)
        assert state.phase == RalphLoopPhase.INIT

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """save should create parent directories if missing."""
        state_file = tmp_path / "deep" / "nested" / "path" / "ralph_state.json"
        state = RalphLoopState()
        state.save(state_file)
        assert state_file.exists()

    def test_save_atomic_write(self, tmp_path: Path) -> None:
        """save should use atomic write (tmp file + replace)."""
        state_file = tmp_path / "ralph_state.json"
        state = RalphLoopState()
        state.save(state_file)
        # Verify no .tmp file left behind
        tmp_file = state_file.with_suffix(".tmp")
        assert not tmp_file.exists()


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_values(self) -> None:
        """Default config should have expected values."""
        config = CircuitBreakerConfig()
        assert config.max_total_iterations == 50
        assert config.max_same_file_edits == 5
        assert config.max_wall_time_minutes == 60
        assert config.behavior_on_breach == "hard_stop"

    def test_load_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        """Loading from missing file should return defaults."""
        config = CircuitBreakerConfig.load(tmp_path / "nonexistent.json")
        assert config.max_total_iterations == 50

    def test_load_from_file(self, tmp_path: Path) -> None:
        """Loading from valid config file should work."""
        config_file = tmp_path / "ralph-loop-config.json"
        config_file.write_text(
            json.dumps(
                {
                    "ralph_loop": {
                        "circuit_breaker": {
                            "max_total_iterations": 100,
                            "max_same_file_edits": 10,
                        }
                    }
                }
            )
        )
        config = CircuitBreakerConfig.load(config_file)
        assert config.max_total_iterations == 100
        assert config.max_same_file_edits == 10

    def test_load_invalid_json_returns_defaults(self, tmp_path: Path) -> None:
        """Loading invalid JSON should return defaults."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json")
        config = CircuitBreakerConfig.load(config_file)
        assert config.max_total_iterations == 50


class TestCheckCircuitBreaker:
    """Tests for check_circuit_breaker function."""

    def test_within_limits_returns_none(self) -> None:
        """Should return None when within limits."""
        state = RalphLoopState(total_tool_calls=10)
        config = CircuitBreakerConfig(max_total_iterations=50)
        result = check_circuit_breaker(state, config)
        assert result is None

    def test_exceeds_iterations_returns_reason(self) -> None:
        """Should return reason when iterations exceeded."""
        state = RalphLoopState(total_tool_calls=51)
        config = CircuitBreakerConfig(max_total_iterations=50)
        result = check_circuit_breaker(state, config)
        assert result is not None
        assert "50" in result
        assert "exceeded" in result.lower()

    def test_exceeds_wall_time_returns_reason(self) -> None:
        """Should return reason when wall time exceeded."""
        # Set started_at to 2 hours ago
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        state = RalphLoopState(started_at=old_time, total_tool_calls=10)
        config = CircuitBreakerConfig(max_wall_time_minutes=60)
        result = check_circuit_breaker(state, config)
        assert result is not None
        assert "wall time" in result.lower()

    def test_invalid_timestamp_skips_wall_time_check(self) -> None:
        """Invalid timestamp should skip wall time check."""
        state = RalphLoopState(started_at="invalid-timestamp", total_tool_calls=10)
        config = CircuitBreakerConfig(max_total_iterations=50)
        # Should not raise, just skip wall time check
        result = check_circuit_breaker(state, config)
        assert result is None


class TestSanitizeBranchName:
    """Tests for sanitize_branch_name function."""

    def test_simple_branch(self) -> None:
        """Simple branch names should pass through."""
        assert sanitize_branch_name("main") == "main"
        assert sanitize_branch_name("feature") == "feature"

    def test_slash_replaced_with_dash(self) -> None:
        """Slashes should be replaced with dashes."""
        assert sanitize_branch_name("feature/foo") == "feature-foo"
        assert sanitize_branch_name("fix/bug/issue") == "fix-bug-issue"

    def test_special_chars_replaced(self) -> None:
        """Special characters should be replaced with dashes."""
        assert sanitize_branch_name("fix/bug#123") == "fix-bug-123"
        assert sanitize_branch_name("feature@user") == "feature-user"

    def test_underscores_preserved(self) -> None:
        """Underscores should be preserved."""
        assert sanitize_branch_name("my_branch") == "my_branch"

    def test_multiple_dashes_collapsed(self) -> None:
        """Multiple consecutive dashes should be collapsed."""
        assert sanitize_branch_name("a--b---c") == "a-b-c"

    def test_leading_trailing_dashes_stripped(self) -> None:
        """Leading/trailing dashes should be stripped."""
        assert sanitize_branch_name("-feature-") == "feature"

    def test_path_traversal_returns_default(self) -> None:
        """Path traversal attempts should return 'default'."""
        assert sanitize_branch_name("../etc/passwd") == "default"
        assert sanitize_branch_name("..") == "default"

    def test_hidden_dir_returns_default(self) -> None:
        """Hidden directory names should return 'default'."""
        assert sanitize_branch_name(".hidden") == "default"

    def test_empty_returns_default(self) -> None:
        """Empty string should return 'default'."""
        assert sanitize_branch_name("") == "default"
        assert sanitize_branch_name("---") == "default"


class TestIterationMetrics:
    """Tests for IterationMetrics dataclass."""

    def test_create_metrics(self) -> None:
        """Should create metrics with all fields."""
        metrics = IterationMetrics(
            iteration=1,
            issues_before=10,
            issues_after=8,
            issues_resolved=3,
            issues_new=1,
            confidence_score=0.7,
            timestamp="2025-01-26T10:00:00",
        )
        assert metrics.iteration == 1
        assert metrics.issues_resolved == 3


class TestIsThrashing:
    """Tests for is_thrashing function."""

    def test_returns_false_for_insufficient_data(self) -> None:
        """Should return False if not enough iterations."""
        metrics = [
            IterationMetrics(1, 10, 8, 2, 0, 0.7, "t1"),
            IterationMetrics(2, 8, 6, 2, 0, 0.8, "t2"),
        ]
        assert is_thrashing(metrics, window=3) is False

    def test_returns_false_for_progress(self) -> None:
        """Should return False when making progress."""
        metrics = [
            IterationMetrics(1, 10, 8, 2, 0, 0.7, "t1"),
            IterationMetrics(2, 8, 6, 2, 0, 0.8, "t2"),
            IterationMetrics(3, 6, 4, 2, 0, 0.9, "t3"),
        ]
        assert is_thrashing(metrics, window=3) is False

    def test_returns_true_for_no_net_progress(self) -> None:
        """Should return True when no net progress."""
        metrics = [
            IterationMetrics(1, 10, 8, 2, 2, 0.7, "t1"),  # resolved 2, new 2
            IterationMetrics(2, 8, 8, 1, 1, 0.7, "t2"),  # resolved 1, new 1
            IterationMetrics(3, 8, 8, 0, 0, 0.7, "t3"),  # no change
        ]
        assert is_thrashing(metrics, window=3) is True

    def test_returns_true_for_confidence_oscillation(self) -> None:
        """Should return True when confidence oscillates."""
        metrics = [
            IterationMetrics(1, 10, 8, 2, 0, 0.9, "t1"),
            IterationMetrics(2, 8, 6, 2, 0, 0.4, "t2"),  # big drop
            IterationMetrics(3, 6, 4, 2, 0, 0.8, "t3"),
        ]
        # Variance is 0.9 - 0.4 = 0.5 > 0.3
        assert is_thrashing(metrics, window=3) is True


class TestGetImprovementRate:
    """Tests for get_improvement_rate function."""

    def test_empty_returns_zero(self) -> None:
        """Empty metrics should return 0.0."""
        assert get_improvement_rate([]) == 0.0

    def test_calculates_rate(self) -> None:
        """Should calculate average issues resolved per iteration."""
        metrics = [
            IterationMetrics(1, 10, 8, 2, 0, 0.7, "t1"),
            IterationMetrics(2, 8, 6, 3, 0, 0.8, "t2"),
            IterationMetrics(3, 6, 4, 1, 0, 0.9, "t3"),
        ]
        # Total resolved: 2 + 3 + 1 = 6, iterations: 3
        assert get_improvement_rate(metrics) == 2.0


class TestRootCauseAnalysis:
    """Tests for RootCauseAnalysis dataclass."""

    def test_create_root_cause(self) -> None:
        """Should create RootCauseAnalysis with all fields."""
        rc = RootCauseAnalysis(
            unmet_requirements=["Req 1", "Req 2"],
            error_files=["src/a.py:10", "src/b.py:20"],
            fix_type="code_fix",
            invalidated_subtasks=["ST-002"],
            suggested_action="Fix the bug",
        )
        assert rc.unmet_requirements == ["Req 1", "Req 2"]
        assert rc.fix_type == "code_fix"


class TestFinalVerificationResult:
    """Tests for FinalVerificationResult dataclass."""

    def test_create_result(self) -> None:
        """Should create result with all fields."""
        result = FinalVerificationResult(
            passed=True,
            verification_method="tests",
            timestamp="2025-01-26T10:00:00",
            confidence=0.9,
        )
        assert result.passed is True
        assert result.confidence == 0.9

    def test_from_json_file(self, tmp_path: Path) -> None:
        """Should load result from JSON file."""
        json_file = tmp_path / "final_verification.json"
        json_file.write_text(
            json.dumps(
                {
                    "passed": False,
                    "verification_method": "tests",
                    "timestamp": "2025-01-26T10:00:00",
                    "issues": ["Issue 1", "Issue 2"],
                    "confidence": 0.45,
                    "iteration": 2,
                    "root_cause": {
                        "unmet_requirements": ["Req 1"],
                        "error_files": ["src/a.py:10"],
                        "fix_type": "code_fix",
                        "invalidated_subtasks": ["ST-002"],
                        "suggested_action": "Fix bug",
                    },
                }
            )
        )

        result = FinalVerificationResult.from_json_file(json_file)
        assert result.passed is False
        assert result.verification_method == "tests"
        assert result.issues == ["Issue 1", "Issue 2"]
        assert result.confidence == 0.45
        assert result.iteration == 2
        assert result.root_cause is not None
        assert result.root_cause.fix_type == "code_fix"

    def test_from_json_file_missing_optional_fields(self, tmp_path: Path) -> None:
        """Should handle missing optional fields."""
        json_file = tmp_path / "final_verification.json"
        json_file.write_text(
            json.dumps(
                {
                    "passed": True,
                    "verification_method": "manual",
                }
            )
        )

        result = FinalVerificationResult.from_json_file(json_file)
        assert result.passed is True
        assert result.issues == []
        assert result.confidence == 1.0
        assert result.iteration == 1
        assert result.root_cause is None


class TestStateTransitionValidations:
    """Tests for valid state transitions."""

    def test_all_states_covered_in_transitions(self) -> None:
        """All phases should be covered in VALID_TRANSITIONS."""
        for phase in RalphLoopPhase:
            assert phase in VALID_TRANSITIONS

    def test_recovery_transitions(self) -> None:
        """RECOVERY should transition to DECOMPOSITION or EXECUTION."""
        state = RalphLoopState()
        state.phase = RalphLoopPhase.HARD_STOP
        state.transition(RalphLoopPhase.RECOVERY)
        assert state.phase == RalphLoopPhase.RECOVERY

        # Can continue to EXECUTION
        state.transition(RalphLoopPhase.EXECUTION)
        assert state.phase == RalphLoopPhase.EXECUTION

    def test_re_decomposition_can_go_to_hard_stop(self) -> None:
        """RE_DECOMPOSITION should be able to go to HARD_STOP."""
        state = RalphLoopState()
        state.phase = RalphLoopPhase.RE_DECOMPOSITION
        state.transition(RalphLoopPhase.HARD_STOP)
        assert state.phase == RalphLoopPhase.HARD_STOP

    def test_escalate_to_complete_or_wont_do(self) -> None:
        """ESCALATE should be able to go to COMPLETE or WONT_DO."""
        state1 = RalphLoopState()
        state1.phase = RalphLoopPhase.ESCALATE
        state1.transition(RalphLoopPhase.COMPLETE)
        assert state1.phase == RalphLoopPhase.COMPLETE

        state2 = RalphLoopState()
        state2.phase = RalphLoopPhase.ESCALATE
        state2.transition(RalphLoopPhase.WONT_DO)
        assert state2.phase == RalphLoopPhase.WONT_DO


class TestSummarizeFailure:
    """Tests for summarize_failure function."""

    def test_summarize_failure_basic(self) -> None:
        """Should create summary with basic info."""
        result = FinalVerificationResult(
            passed=False,
            verification_method="tests",
            timestamp="2025-01-26T10:00:00",
            issues=["Issue 1", "Issue 2", "Issue 3"],
            iteration=2,
        )

        summary = summarize_failure(result)
        assert "Iteration 2" in summary
        assert "3 issues" in summary

    def test_summarize_failure_with_root_cause(self) -> None:
        """Should include root cause info when present."""
        result = FinalVerificationResult(
            passed=False,
            verification_method="tests",
            timestamp="2025-01-26T10:00:00",
            issues=["Issue 1"],
            iteration=1,
            root_cause=RootCauseAnalysis(
                unmet_requirements=["Req 1", "Req 2", "Req 3"],
                error_files=[
                    "src/a.py:10",
                    "src/b.py:20",
                    "src/c.py:30",
                    "src/d.py:40",
                ],
                fix_type="code_fix",
                invalidated_subtasks=["ST-002"],
                suggested_action="Fix bug",
            ),
        )

        summary = summarize_failure(result)
        assert "code_fix" in summary
        # Should limit to first 2 requirements
        assert "Req 1" in summary
        assert "Req 2" in summary
        # Should limit to first 3 files
        assert "src/a.py:10" in summary
        assert "src/c.py:30" in summary
        # Should NOT include the 4th file
        assert "src/d.py:40" not in summary

    def test_summarize_failure_empty_root_cause(self) -> None:
        """Should handle empty root cause lists."""
        result = FinalVerificationResult(
            passed=False,
            verification_method="tests",
            timestamp="2025-01-26T10:00:00",
            issues=[],
            iteration=1,
            root_cause=RootCauseAnalysis(
                unmet_requirements=[],
                error_files=[],
                fix_type="plan_change",
                invalidated_subtasks=[],
                suggested_action="Revise plan",
            ),
        )

        summary = summarize_failure(result)
        assert "plan_change" in summary
        assert "[]" in summary  # Empty lists shown


class TestPruneFailureHistory:
    """Tests for prune_failure_history function."""

    def test_prune_no_action_when_under_limit(self) -> None:
        """Should not modify state when under limit."""
        state = RalphLoopState()
        state.failure_summaries = ["f1", "f2", "f3"]

        prune_failure_history(state, max_summaries=3)
        assert state.failure_summaries == ["f1", "f2", "f3"]

    def test_prune_combines_old_summaries(self) -> None:
        """Should combine old summaries into one."""
        state = RalphLoopState()
        state.failure_summaries = ["f1", "f2", "f3", "f4", "f5"]

        prune_failure_history(state, max_summaries=3)

        # Should have 1 combined + 3 recent = 4 entries
        assert len(state.failure_summaries) == 4
        # First entry should be combined
        assert "[2 earlier failures summarized]" in state.failure_summaries[0]
        assert "f1" in state.failure_summaries[0]
        assert "f2" in state.failure_summaries[0]
        # Recent 3 should be preserved
        assert state.failure_summaries[1:] == ["f3", "f4", "f5"]

    def test_prune_truncates_long_summaries(self) -> None:
        """Should truncate very long individual summaries."""
        state = RalphLoopState()
        long_summary = "x" * 200  # Longer than 100 char limit
        state.failure_summaries = [long_summary, "f2", "f3", "f4"]

        prune_failure_history(state, max_summaries=3)

        # Combined summary should not contain full long_summary
        combined = state.failure_summaries[0]
        assert len(combined) < 200  # Should be truncated

    def test_prune_handles_many_old_summaries(self) -> None:
        """Should add ellipsis when more than 2 old summaries."""
        state = RalphLoopState()
        state.failure_summaries = ["f1", "f2", "f3", "f4", "f5", "f6"]

        prune_failure_history(state, max_summaries=3)

        combined = state.failure_summaries[0]
        assert "[3 earlier failures summarized]" in combined
        # Should have ellipsis for >2 old summaries
        assert "..." in combined

    def test_prune_preserves_recent_summaries(self) -> None:
        """Should always preserve the most recent summaries unchanged."""
        state = RalphLoopState()
        state.failure_summaries = ["old1", "old2", "recent1", "recent2", "recent3"]

        prune_failure_history(state, max_summaries=3)

        # Recent 3 should be exactly preserved
        assert state.failure_summaries[-3:] == ["recent1", "recent2", "recent3"]
