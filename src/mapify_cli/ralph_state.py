"""
Ralph Loop State Management.

This module is SEPARATE from workflow_state.py to:
1. Maintain backwards compatibility with existing .map/progress.md
2. Keep branch-scoped state isolated
3. Allow independent versioning

State persisted to .map/<branch>/ralph_state.json
Circuit breaker config source: .claude/ralph-loop-config.json
"""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class RalphLoopPhase(Enum):
    """Ralph Loop execution phases with validated transitions."""

    INIT = "init"
    DECOMPOSITION = "decomposition"
    EXECUTION = "execution"
    FINAL_VERIFICATION = "final_verification"
    RE_DECOMPOSITION = "re_decomposition"
    COMPLETE = "complete"
    ESCALATE = "escalate"
    HARD_STOP = "hard_stop"
    RECOVERY = "recovery"  # manual resume after HARD_STOP
    WONT_DO = "wont_do"


# Valid state transitions (state machine)
VALID_TRANSITIONS: dict[RalphLoopPhase, list[RalphLoopPhase]] = {
    RalphLoopPhase.INIT: [RalphLoopPhase.DECOMPOSITION],
    RalphLoopPhase.DECOMPOSITION: [
        RalphLoopPhase.EXECUTION,
        RalphLoopPhase.ESCALATE,
    ],
    RalphLoopPhase.EXECUTION: [
        RalphLoopPhase.FINAL_VERIFICATION,
        RalphLoopPhase.ESCALATE,
    ],
    RalphLoopPhase.FINAL_VERIFICATION: [
        RalphLoopPhase.COMPLETE,
        RalphLoopPhase.RE_DECOMPOSITION,
        RalphLoopPhase.ESCALATE,
    ],
    RalphLoopPhase.RE_DECOMPOSITION: [
        RalphLoopPhase.EXECUTION,
        RalphLoopPhase.ESCALATE,
        RalphLoopPhase.HARD_STOP,
    ],
    RalphLoopPhase.ESCALATE: [
        RalphLoopPhase.COMPLETE,
        RalphLoopPhase.WONT_DO,
    ],
    RalphLoopPhase.HARD_STOP: [RalphLoopPhase.RECOVERY],
    RalphLoopPhase.RECOVERY: [
        RalphLoopPhase.DECOMPOSITION,
        RalphLoopPhase.EXECUTION,
    ],
    RalphLoopPhase.COMPLETE: [],  # terminal
    RalphLoopPhase.WONT_DO: [],  # terminal
}


@dataclass
class RalphLoopState:
    """
    Branch-scoped Ralph Loop state.
    Persisted to .map/<branch>/ralph_state.json

    Tracks iteration counts, circuit breaker limits, and failure history.
    """

    # Current phase
    phase: RalphLoopPhase = RalphLoopPhase.INIT

    # Iteration tracking
    plan_iteration: int = 1
    total_tool_calls: int = 0

    # Timestamps
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Failure tracking
    failure_summaries: list[str] = field(default_factory=list)

    # Schema version for migrations
    schema_version: int = 1

    def transition(self, to_phase: RalphLoopPhase) -> None:
        """
        Validate and execute state transition.

        Args:
            to_phase: Target phase to transition to

        Raises:
            InvalidTransitionError: If transition is not allowed by state machine
        """
        valid_targets = VALID_TRANSITIONS.get(self.phase, [])
        if to_phase not in valid_targets:
            raise InvalidTransitionError(
                f"Cannot transition from {self.phase.value} to {to_phase.value}. "
                f"Valid transitions: {[p.value for p in valid_targets]}"
            )
        self.phase = to_phase
        self.updated_at = datetime.now(UTC).isoformat()

    def reset_limits(self) -> None:
        """Reset iteration counters for recovery from HARD_STOP."""
        self.total_tool_calls = 0
        self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict:
        """
        Serialize state to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "plan_iteration": self.plan_iteration,
            "total_tool_calls": self.total_tool_calls,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "failure_summaries": self.failure_summaries,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RalphLoopState":
        """
        Deserialize state from dictionary.

        Args:
            data: Dictionary with state data

        Returns:
            RalphLoopState instance
        """
        return cls(
            schema_version=data.get("schema_version", 1),
            phase=RalphLoopPhase(data.get("phase", "init")),
            plan_iteration=data.get("plan_iteration", 1),
            total_tool_calls=data.get("total_tool_calls", 0),
            started_at=data.get("started_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
            failure_summaries=data.get("failure_summaries", []),
        )

    @classmethod
    def load(cls, state_file: Path) -> "RalphLoopState":
        """
        Load state from file, return new state if file doesn't exist.

        Args:
            state_file: Path to ralph_state.json

        Returns:
            RalphLoopState instance (new if file missing or invalid)
        """
        if not state_file.exists():
            return cls()
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            # Return fresh state on any parsing error
            return cls()

    def save(self, state_file: Path) -> None:
        """
        Save state to file using atomic write.

        Uses tmp file + replace pattern to prevent partial writes on crash.

        Args:
            state_file: Path to ralph_state.json
        """
        # Ensure parent directory exists
        state_file.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8"
        )

        # Atomic replace (POSIX guarantee)
        tmp_file.replace(state_file)


@dataclass
class CircuitBreakerConfig:
    """
    Configuration for circuit breaker limits.

    Source of truth: .claude/ralph-loop-config.json
    """

    max_total_iterations: int = 50  # SINGLE SOURCE OF TRUTH
    max_same_file_edits: int = 5
    max_wall_time_minutes: int = 60
    behavior_on_breach: str = "hard_stop"  # hard_stop | escalate

    @classmethod
    def load(cls, config_file: Path) -> "CircuitBreakerConfig":
        """
        Load config from ralph-loop-config.json.

        Args:
            config_file: Path to .claude/ralph-loop-config.json

        Returns:
            CircuitBreakerConfig with values from file or defaults if missing
        """
        if not config_file.exists():
            return cls()  # Use defaults

        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            cb_config = data.get("ralph_loop", {}).get("circuit_breaker", {})
            return cls(
                max_total_iterations=cb_config.get("max_total_iterations", 50),
                max_same_file_edits=cb_config.get("max_same_file_edits", 5),
                max_wall_time_minutes=cb_config.get("max_wall_time_minutes", 60),
                behavior_on_breach=cb_config.get("behavior_on_breach", "hard_stop"),
            )
        except (json.JSONDecodeError, KeyError):
            # Return defaults on any parsing error
            return cls()


def check_circuit_breaker(
    state: RalphLoopState, config: CircuitBreakerConfig
) -> str | None:
    """
    Check if circuit breaker should trigger.

    Args:
        state: Current Ralph Loop state
        config: Circuit breaker configuration

    Returns:
        Breach reason string if limit exceeded, None if OK
    """
    # Check total iterations limit
    if state.total_tool_calls >= config.max_total_iterations:
        return f"Max iterations ({config.max_total_iterations}) exceeded"

    # Check wall time limit
    try:
        started = datetime.fromisoformat(state.started_at)
        elapsed_minutes = (datetime.now(UTC) - started).total_seconds() / 60
        if elapsed_minutes >= config.max_wall_time_minutes:
            return f"Max wall time ({config.max_wall_time_minutes}min) exceeded"
    except ValueError:
        # Invalid timestamp format, skip wall time check
        pass

    return None


def sanitize_branch_name(branch: str) -> str:
    """
    Sanitize branch name for safe filesystem paths.

    Converts:
        feature/foo -> feature-foo
        fix/bug#123 -> fix-bug-123
        my_branch   -> my_branch (unchanged)

    Args:
        branch: Raw git branch name

    Returns:
        Sanitized branch name safe for filesystem paths
    """
    # Replace / with -
    sanitized = branch.replace("/", "-")
    # Replace other problematic chars with -
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    # Collapse multiple dashes
    sanitized = re.sub(r"-+", "-", sanitized)
    # Strip leading/trailing dashes
    sanitized = sanitized.strip("-")
    # Prevent path traversal attempts
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


@dataclass
class IterationMetrics:
    """Metrics for detecting diminishing returns / thrashing at plan level."""

    iteration: int
    issues_before: int
    issues_after: int
    issues_resolved: int
    issues_new: int
    confidence_score: float
    timestamp: str


def is_thrashing(metrics: list[IterationMetrics], window: int = 3) -> bool:
    """
    Detect thrashing: oscillating between states without progress.
    Returns True if last N iterations show no net improvement.

    Called by orchestrator (map-efficient.md) after final verification.

    Args:
        metrics: List of iteration metrics
        window: Number of recent iterations to analyze (default: 3)

    Returns:
        True if thrashing detected (net progress <= 0 or high confidence variance)
    """
    if len(metrics) < window:
        return False

    recent = metrics[-window:]
    net_progress = sum(m.issues_resolved - m.issues_new for m in recent)

    # Also check for confidence oscillation
    confidences = [m.confidence_score for m in recent]
    confidence_variance = max(confidences) - min(confidences)

    return net_progress <= 0 or confidence_variance > 0.3


def get_improvement_rate(metrics: list[IterationMetrics]) -> float:
    """
    Calculate issues resolved per iteration.

    Args:
        metrics: List of iteration metrics

    Returns:
        Average number of issues resolved per iteration, or 0.0 if no metrics
    """
    if not metrics:
        return 0.0
    total_resolved = sum(m.issues_resolved for m in metrics)
    return total_resolved / len(metrics)


@dataclass
class RootCauseAnalysis:
    """Structured analysis of verification failure."""

    unmet_requirements: list[str]
    error_files: list[str]
    fix_type: str  # "code_fix" | "plan_change" | "both"
    invalidated_subtasks: list[str]  # "completed" subtasks that may need redo
    suggested_action: str


@dataclass
class FinalVerificationResult:
    """Result from final-verifier agent, parsed from JSON output."""

    passed: bool
    verification_method: str  # "tests" | "mcp_tool" | "manual" | "combined"
    timestamp: str
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0
    iteration: int = 1
    root_cause: RootCauseAnalysis | None = None  # REQUIRED if passed=False

    @classmethod
    def from_json_file(cls, path: Path) -> "FinalVerificationResult":
        """Load from .map/<branch>/final_verification.json"""
        data = json.loads(path.read_text(encoding="utf-8"))
        passed = data["passed"]
        root_cause = None
        if data.get("root_cause"):
            root_cause = RootCauseAnalysis(**data["root_cause"])
        # Enforce contract: root_cause is REQUIRED when passed=false
        if not passed and root_cause is None:
            raise ValueError(
                "root_cause is required when passed=false " f"(file: {path})"
            )
        return cls(
            passed=passed,
            verification_method=data["verification_method"],
            timestamp=data.get("timestamp", datetime.now(UTC).isoformat()),
            issues=data.get("issues", []),
            confidence=data.get("confidence", 1.0),
            iteration=data.get("iteration", 1),
            root_cause=root_cause,
        )


# ============================================================================
# Context Pruning Functions (Phase 4.1)
# ============================================================================


def summarize_failure(verification_result: FinalVerificationResult) -> str:
    """
    Create condensed summary of failure for context preservation.

    Designed to preserve key information while minimizing token usage
    when storing failure history in RalphLoopState.failure_summaries.

    Args:
        verification_result: Failed verification result to summarize

    Returns:
        Condensed summary string suitable for failure_summaries list
    """
    summary = f"Iteration {verification_result.iteration}: "
    summary += f"Failed with {len(verification_result.issues)} issues. "

    if verification_result.root_cause:
        rc = verification_result.root_cause
        # Limit to first 2 unmet requirements to save tokens
        reqs = rc.unmet_requirements[:2]
        reqs_str = str(reqs) if reqs else "[]"
        summary += f"Root cause: {rc.fix_type} needed for {reqs_str}. "
        # Limit to first 3 error files
        files = rc.error_files[:3]
        files_str = str(files) if files else "[]"
        summary += f"Files: {files_str}."

    return summary.strip()


def prune_failure_history(state: RalphLoopState, max_summaries: int = 3) -> None:
    """
    Keep only recent failure summaries to preserve token budget.

    When failure_summaries exceeds max_summaries, older entries are
    combined into a single condensed entry to reduce context size
    while preserving some historical information.

    Args:
        state: RalphLoopState to prune (modified in-place)
        max_summaries: Maximum number of detailed summaries to keep (default: 3)
    """
    if len(state.failure_summaries) <= max_summaries:
        return

    # Split into old (to combine) and recent (to keep)
    old = state.failure_summaries[:-max_summaries]
    recent = state.failure_summaries[-max_summaries:]

    # Combine old summaries into one condensed entry
    # Take first 2 old summaries as samples, truncate if too long
    samples = old[:2]
    samples_str = "; ".join(s[:100] for s in samples)  # Limit each sample to 100 chars
    if len(old) > 2:
        samples_str += "..."

    combined = f"[{len(old)} earlier failures summarized]: {samples_str}"

    # Replace state's failure_summaries with combined + recent
    state.failure_summaries = [combined] + recent
