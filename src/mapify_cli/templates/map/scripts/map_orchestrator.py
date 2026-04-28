#!/usr/bin/env python3
"""
MAP Workflow State Machine Orchestrator

Manages workflow step sequencing and state transitions for /map-efficient command.
This is the "OS" that coordinates agents (the "applications").

DESIGN PRINCIPLE:
  "State-Gated Prompting" - Each workflow invocation should see exactly ONE
  clear next action. State machine enforces sequencing, Python validates
  completion, hooks inject reminders.

ARCHITECTURE:
  ┌─────────────────────────────────────────────────────────────┐
  │  map-efficient.md (~540 lines)                               │
  │  ├─> 1. Call get_next_step() → returns step instruction    │
  │  ├─> 2. Execute step (Actor/Monitor/etc)                   │
  │  ├─> 3. Call validate_step() → checks completion           │
  │  ├─> 4. If more steps: recurse with fresh context          │
  │  └─> 5. Else: complete workflow                            │
  └─────────────────────────────────────────────────────────────┘

STATE FILE:
  Location: .map/<branch>/step_state.json
  Schema:
    {
      "workflow": "map-efficient",
      "started_at": "2026-01-27T10:30:00Z",
      "current_subtask_id": "ST-001",
      "subtask_index": 0,
      "subtask_sequence": ["ST-001", "ST-002", "ST-003"],
      "current_step_id": "2.2",
      "current_step_phase": "RESEARCH",
      "completed_steps": ["1.0", "1.5", "1.55", "1.56", "1.6"],
      "pending_steps": ["2.2", "2.3", "2.4"]
    }

STEP PHASES (10 total, 8 standard + 2 TDD):
  1.0  DECOMPOSE          - task-decomposer agent
  1.5  INIT_PLAN          - Generate task_plan.md
  1.55 REVIEW_PLAN        - User review + explicit approval checkpoint
  1.56 CHOOSE_MODE        - Auto-skipped (always batch mode)
  1.6  INIT_STATE         - Create step_state.json (single source of truth)
  2.2  RESEARCH           - research-agent (mandatory for all subtasks)
  2.25 TEST_WRITER        - TDD: write tests from spec (TDD mode only)
  2.26 TEST_FAIL_GATE     - TDD: verify tests fail without impl (TDD mode only)
  2.3  ACTOR              - Actor agent implementation
  2.4  MONITOR            - Monitor validation

  Per-wave gates (TESTS + LINTER) run once after all Monitor passes (in map-efficient.md).
  Predictor runs only in stuck recovery at retry 3 (not a pipeline phase).

CLI INTERFACE:
  python3 map_orchestrator.py get_next_step [--branch BRANCH]
    → Returns JSON with next step instruction

  python3 map_orchestrator.py validate_step STEP_ID [--branch BRANCH]
    → Returns JSON with validation result

  python3 map_orchestrator.py initialize TASK [--branch BRANCH]
    → Creates initial step_state.json

USAGE FROM map-efficient.md:
  ```bash
  # Get next step
  NEXT_STEP=$(python3 .map/scripts/map_orchestrator.py get_next_step)
  STEP_ID=$(echo "$NEXT_STEP" | jq -r '.step_id')
  INSTRUCTION=$(echo "$NEXT_STEP" | jq -r '.instruction')

  # Execute step based on phase...

  # Validate completion
  python3 .map/scripts/map_orchestrator.py validate_step "$STEP_ID"
  ```

TESTING:
  # Initialize
  python3 map_orchestrator.py initialize "Add user authentication"

  # Get first step
  python3 map_orchestrator.py get_next_step
  # → {"step_id": "1.0", "phase": "DECOMPOSE", "instruction": "..."}

  # Mark step complete and get next
  python3 map_orchestrator.py validate_step "1.0"
  python3 map_orchestrator.py get_next_step
  # → {"step_id": "1.5", "phase": "INIT_PLAN", "instruction": "..."}
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Step phase definitions with execution order
STEP_PHASES = {
    "1.0": "DECOMPOSE",
    "1.5": "INIT_PLAN",
    "1.55": "REVIEW_PLAN",
    "1.56": "CHOOSE_MODE",
    "1.6": "INIT_STATE",
    "2.2": "RESEARCH",
    "2.25": "TEST_WRITER",
    "2.26": "TEST_FAIL_GATE",
    "2.3": "ACTOR",
    "2.4": "MONITOR",
}

# Step execution order (standard — without TDD phases)
STEP_ORDER = [
    "1.0",
    "1.5",
    "1.55",
    "1.56",
    "1.6",
    "2.2",
    "2.3",
    "2.4",
]

# TDD step order — includes TEST_WRITER and TEST_FAIL_GATE before ACTOR
TDD_STEP_ORDER = [
    "1.0",
    "1.5",
    "1.55",
    "1.56",
    "1.6",
    "2.2",
    "2.25",
    "2.26",
    "2.3",
    "2.4",
]


def _utc_timestamp() -> str:
    """Return an unambiguous RFC3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text_if_exists(path: Path) -> str:
    """Return UTF-8 text content for a file when present."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_recent_markdown_section(content: str, max_lines: int = 12) -> str:
    """Return the most recent non-empty lines from markdown content."""
    if not content:
        return ""
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _latest_numbered_artifact(plan_dir: Path, prefix: str) -> Optional[Path]:
    """Return latest numbered artifact like review-003.md."""
    matches = sorted(plan_dir.glob(f"{prefix}-*.md"))
    numbered = []
    for path in matches:
        stem = path.stem
        suffix = stem.removeprefix(f"{prefix}-")
        if suffix.isdigit():
            numbered.append((int(suffix), path))
    if not numbered:
        return None
    return max(numbered, key=lambda item: item[0])[1]


def get_resume_briefing(branch: str) -> dict:
    """Collect human-readable artifact context for resume and handoff flows."""
    plan_dir = Path(f".map/{branch}")
    verification_summary = plan_dir / "verification-summary.md"
    latest_review = _latest_numbered_artifact(plan_dir, "code-review")
    latest_qa = _latest_numbered_artifact(plan_dir, "qa")

    review_content = _read_text_if_exists(latest_review) if latest_review else ""
    verification_content = _read_text_if_exists(verification_summary)

    verdict_match = None
    if verification_content:
        import re

        verdict_match = re.search(r"- Verdict:\s*(.+)", verification_content)

    fix_lines = []
    for line in review_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            fix_lines.append(stripped)
    fix_lines = fix_lines[:5]

    return {
        "branch": branch,
        "verification_summary_path": (
            str(verification_summary) if verification_summary.exists() else None
        ),
        "latest_review_path": str(latest_review) if latest_review else None,
        "latest_qa_path": str(latest_qa) if latest_qa else None,
        "latest_verification_verdict": (
            verdict_match.group(1).strip() if verdict_match else None
        ),
        "latest_review_summary": _extract_recent_markdown_section(review_content),
        "latest_verification_summary": _extract_recent_markdown_section(
            verification_content
        ),
        "suggested_fixes": fix_lines,
    }


def build_resume_briefing(branch: str) -> dict:
    """Build a concise next-action briefing from plan progress and artifacts."""
    plan_progress = get_plan_progress(branch)
    briefing = get_resume_briefing(branch)

    suggested_next = None
    completed_count = 0
    pending_count = 0
    current_subtask = None
    workflow_status = None
    if plan_progress.get("status") == "success":
        suggested_next = plan_progress.get("suggested_next")
        completed_count = plan_progress.get("completed_count", 0)
        pending_count = plan_progress.get("pending_count", 0)

    state_file = Path(f".map/{branch}/step_state.json")
    if state_file.exists():
        state = StepState.load(state_file)
        current_subtask = state.current_subtask_id
        current_phase = state.current_step_phase
        workflow_status = state.workflow_status
    else:
        current_phase = None

    next_action = []
    if workflow_status == "CONTRACT_READY" and current_subtask:
        next_action.append(
            f"Resume {current_subtask} implementation from the persisted test contract"
        )
    if briefing.get("latest_verification_verdict") == "NEEDS WORK":
        next_action.append(
            "Address issues from the latest verification before continuing"
        )
    if briefing.get("suggested_fixes"):
        next_action.append("Review requested fixes from latest review artifact")
    if current_subtask and current_phase:
        next_action.append(f"Resume {current_subtask} at phase {current_phase}")
    elif suggested_next:
        next_action.append(f"Start next pending subtask {suggested_next}")
    elif pending_count == 0 and completed_count > 0:
        next_action.append(
            "Workflow appears complete; review PR and verification artifacts"
        )

    return {
        "branch": branch,
        "current_subtask": current_subtask,
        "current_phase": current_phase,
        "workflow_status": workflow_status,
        "completed_count": completed_count,
        "pending_count": pending_count,
        "suggested_next": suggested_next,
        "resume_briefing": briefing,
        "next_action": next_action,
    }


@dataclass
class StepState:
    """Workflow step state tracking."""

    workflow: str = "map-efficient"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_subtask_id: Optional[str] = None
    subtask_index: int = 0
    subtask_sequence: list[str] = field(default_factory=list)
    current_step_id: str = "1.0"
    current_step_phase: str = "DECOMPOSE"
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=lambda: STEP_ORDER.copy())
    # retry_count is for SERIAL mode only (single-subtask execution).
    # subtask_retry_counts is for WAVE mode only (parallel wave execution).
    # These counters are independent: advance_wave resets subtask_retry_counts
    # but NOT retry_count, and get_next_step resets retry_count but NOT
    # subtask_retry_counts. Never mix serial and wave retry tracking.
    retry_count: int = 0
    max_retries: int = 5
    plan_approved: bool = False
    execution_mode: str = "batch"  # batch|step_by_step
    # TDD mode: inserts TEST_WRITER and TEST_FAIL_GATE before ACTOR
    tdd_mode: bool = False
    # Steps skipped (not executed) — tracked separately from completed_steps
    # so that re-enabling TDD can re-introduce skipped TDD steps
    skipped_steps: list[str] = field(default_factory=list)
    # Wave-based parallel execution fields
    execution_waves: list[list[str]] = field(default_factory=list)
    current_wave_index: int = 0
    subtask_phases: dict[str, str] = field(default_factory=dict)
    subtask_retry_counts: dict[str, int] = field(default_factory=dict)
    # Pipeline simplification fields
    workflow_status: str = "INITIALIZED"
    subtask_files_changed: dict[str, list[str]] = field(default_factory=dict)
    guard_rework_counts: dict[str, int] = field(default_factory=dict)
    constraints: Optional[dict] = None
    subtask_results: dict[str, dict] = field(default_factory=dict)
    last_subtask_commit_sha: Optional[str] = None
    contract_ready_subtasks: dict[str, dict] = field(default_factory=dict)

    def record_subtask_result(
        self,
        subtask_id: str,
        files_changed: list[str],
        status: str,
        summary: str = "",
        commit_sha: Optional[str] = None,
    ) -> None:
        """Record result of a completed subtask for context injection."""
        self.subtask_results[subtask_id] = {
            "files_changed": files_changed,
            "status": status,
            "summary": summary,
        }
        if commit_sha:
            self.last_subtask_commit_sha = commit_sha

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "workflow": self.workflow,
            "started_at": self.started_at,
            "current_subtask_id": self.current_subtask_id,
            "subtask_index": self.subtask_index,
            "subtask_sequence": self.subtask_sequence,
            "current_step_id": self.current_step_id,
            "current_step_phase": self.current_step_phase,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "plan_approved": self.plan_approved,
            "execution_mode": self.execution_mode,
            "tdd_mode": self.tdd_mode,
            "skipped_steps": self.skipped_steps,
            "execution_waves": self.execution_waves,
            "current_wave_index": self.current_wave_index,
            "subtask_phases": self.subtask_phases,
            "subtask_retry_counts": self.subtask_retry_counts,
            "workflow_status": self.workflow_status,
            "subtask_files_changed": self.subtask_files_changed,
            "guard_rework_counts": self.guard_rework_counts,
            "constraints": self.constraints,
            "subtask_results": self.subtask_results,
            "last_subtask_commit_sha": self.last_subtask_commit_sha,
            "contract_ready_subtasks": self.contract_ready_subtasks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StepState":
        """Deserialize from dictionary."""
        return cls(
            workflow=data.get("workflow", "map-efficient"),
            started_at=data.get("started_at", datetime.now().isoformat()),
            current_subtask_id=data.get("current_subtask_id"),
            subtask_index=data.get("subtask_index", 0),
            subtask_sequence=data.get("subtask_sequence", []),
            current_step_id=data.get("current_step_id", "1.0"),
            current_step_phase=data.get("current_step_phase", "DECOMPOSE"),
            completed_steps=data.get("completed_steps", []),
            pending_steps=data.get("pending_steps", STEP_ORDER.copy()),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 5),
            plan_approved=data.get("plan_approved", False),
            execution_mode=data.get("execution_mode", "batch"),
            tdd_mode=data.get("tdd_mode", False),
            skipped_steps=data.get("skipped_steps", []),
            execution_waves=data.get("execution_waves", []),
            current_wave_index=data.get("current_wave_index", 0),
            subtask_phases=data.get("subtask_phases", {}),
            subtask_retry_counts=data.get("subtask_retry_counts", {}),
            workflow_status=data.get("workflow_status", "INITIALIZED"),
            subtask_files_changed=data.get("subtask_files_changed", {}),
            guard_rework_counts=data.get("guard_rework_counts", {}),
            constraints=data.get("constraints"),
            subtask_results=data.get("subtask_results", {}),
            last_subtask_commit_sha=data.get("last_subtask_commit_sha"),
            contract_ready_subtasks=data.get("contract_ready_subtasks", {}),
        )

    @classmethod
    def load(cls, state_file: Path) -> "StepState":
        """Load state from file."""
        if not state_file.exists():
            return cls()
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return cls()

    def save(self, state_file: Path) -> None:
        """Save state to file."""
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        tmp_file.replace(state_file)


def _get_step_order(tdd_mode: bool = False) -> list[str]:
    """Return the appropriate step order based on TDD mode."""
    return TDD_STEP_ORDER if tdd_mode else STEP_ORDER


from map_utils import get_branch_name  # noqa: E402 — shared across .map/scripts/


def _actor_step_instruction(state: StepState) -> str:
    """Build instruction string for the ACTOR step, TDD-aware."""
    subtask = state.current_subtask_id
    if state.tdd_mode:
        context = (
            "TDD CODE_ONLY mode: pass <TDD_Mode>code_only</TDD_Mode>. "
            "Actor must make existing tests green without modifying test files. "
            "When present, read test_contract_<subtask>.md and "
            "test_handoff_<subtask>.json before editing. "
        )
    else:
        context = "Pass AAG contract and context. "
    return (
        f"Call Task(subagent_type='actor') to implement subtask {subtask}. "
        f"{context}"
    )


def get_step_instruction(step_id: str, state: StepState) -> str:
    """
    Get instruction for executing a specific step.

    Args:
        step_id: Step identifier (e.g., "2.3")
        state: Current workflow state

    Returns:
        Instruction string for the step
    """
    phase = STEP_PHASES.get(step_id, "UNKNOWN")
    instructions = {
        "1.0": (
            "Call Task(subagent_type='task-decomposer') to break down the task "
            "into ≤20 atomic subtasks with validation criteria."
        ),
        "1.5": (
            "Generate .map/<branch>/task_plan_<branch>.md from decomposer blueprint. "
            "Include Goal, Current Phase, and status for each subtask."
        ),
        "1.55": (
            "Present the generated plan to the user using a short standardized summary "
            "(goal + subtask titles + risks) and get explicit approval to proceed. "
            "Then persist approval in step_state.json: "
            "python3 .map/scripts/map_orchestrator.py set_plan_approved true"
        ),
        "1.56": (
            "Execution mode is batch (auto-set). No user action needed. "
            "Advance to next step: python3 .map/scripts/map_orchestrator.py get_next_step"
        ),
        "1.6": (
            "Create .map/<branch>/step_state.json with initial state. "
            "Single source of truth for workflow enforcement."
        ),
        "2.2": (
            "Call Task(subagent_type='research-agent') to research the subtask. "
            "MANDATORY for all subtasks. Pass findings to Actor."
        ),
        "2.25": (
            f"TDD TEST_WRITER: Call Task(subagent_type='actor') with "
            f"<TDD_Mode>test_writer</TDD_Mode> to write ONLY tests for subtask "
            f"{state.current_subtask_id}. Tests must be derived from spec/contract, "
            f"NOT from implementation."
        ),
        "2.26": (
            "TDD TEST_FAIL_GATE: Run tests written by TEST_WRITER. "
            "Tests MUST fail (no implementation exists yet). "
            "If tests pass → problem (trivial tests), go back to TEST_WRITER. "
            "If tests fail with assertion errors → proceed to ACTOR."
        ),
        "2.3": _actor_step_instruction(state),
        "2.4": (
            "Call Task(subagent_type='monitor') to validate Actor output. "
            "Check correctness, security, standards, and tests."
        ),
    }

    return instructions.get(step_id, f"Execute step {step_id} ({phase})")


def get_next_step(branch: str) -> dict:
    """
    Determine next step in workflow.

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with step_id, phase, instruction, is_complete
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if state.workflow_status == "CONTRACT_READY":
        if state.pending_steps != ["CONTRACT_READY"]:
            state.pending_steps = ["CONTRACT_READY"]
            state.save(state_file)
        return {
            "step_id": "CONTRACT_READY",
            "phase": "CONTRACT_READY",
            "instruction": (
                "Workflow paused at persisted test contract. "
                "Resume implementation with /map-task for this subtask."
            ),
            "is_complete": False,
            "current_subtask": state.current_subtask_id,
            "subtask_progress": f"{state.subtask_index + 1}/{len(state.subtask_sequence)}",
        }

    # Auto-skip CHOOSE_MODE: always batch, set mode automatically
    while state.pending_steps and state.pending_steps[0] == "1.56":
        state.execution_mode = "batch"
        state.completed_steps.append("1.56")
        state.pending_steps.pop(0)
        state.save(state_file)

    # Auto-skip TDD phases when tdd_mode is disabled
    while (
        state.pending_steps
        and state.pending_steps[0] in ("2.25", "2.26")
        and not state.tdd_mode
    ):
        skipped = state.pending_steps.pop(0)
        state.skipped_steps.append(skipped)
        state.save(state_file)

    # Check if workflow complete
    if not state.pending_steps:
        # Check if more subtasks remain
        if state.subtask_index + 1 < len(state.subtask_sequence):
            # Move to next subtask, reset steps
            state.subtask_index += 1
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            state.current_step_id = "2.2"
            state.current_step_phase = "RESEARCH"
            # Reset to subtask-level steps (skip global setup steps)
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]  # Start from 2.2
            state.completed_steps = []
            state.skipped_steps = []
            state.retry_count = 0
            state.save(state_file)
        else:
            return {
                "step_id": "COMPLETE",
                "phase": "COMPLETE",
                "instruction": "All subtasks complete. Run final verification.",
                "is_complete": True,
            }

    # Get next pending step
    next_step_id = state.pending_steps[0]
    phase = STEP_PHASES.get(next_step_id, "UNKNOWN")
    instruction = get_step_instruction(next_step_id, state)

    # Update current step in state
    state.current_step_id = next_step_id
    state.current_step_phase = phase
    state.save(state_file)

    return {
        "step_id": next_step_id,
        "phase": phase,
        "instruction": instruction,
        "is_complete": False,
        "current_subtask": state.current_subtask_id,
        "subtask_progress": f"{state.subtask_index + 1}/{len(state.subtask_sequence)}",
    }


def validate_step(step_id: str, branch: str) -> dict:
    """
    Validate step completion and update state.

    Args:
        step_id: Step identifier to validate
        branch: Git branch name (sanitized)

    Returns:
        Dict with valid: bool, message: str
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    # Check if step is current
    if state.current_step_id != step_id:
        return {
            "valid": False,
            "message": f"Step mismatch: expected {state.current_step_id}, got {step_id}",
        }

    # Step-specific validation
    if step_id == "1.55" and not state.plan_approved:
        return {
            "valid": False,
            "message": "Plan not approved. Set approval first: python3 .map/scripts/map_orchestrator.py set_plan_approved true",
        }
    # CHOOSE_MODE is auto-skipped; execution_mode is always "batch"

    # Mark step complete
    state.completed_steps.append(step_id)
    if step_id in state.pending_steps:
        state.pending_steps.remove(step_id)

    # When transitioning from init phases to execution phases,
    # ensure the first subtask is selected
    if step_id == "1.6" and state.subtask_sequence and not state.current_subtask_id:
        state.current_subtask_id = state.subtask_sequence[0]
        state.subtask_index = 0

    # Advance current_step_id to next pending step
    if state.pending_steps:
        next_id = state.pending_steps[0]
        state.current_step_id = next_id
        state.current_step_phase = STEP_PHASES.get(next_id, "UNKNOWN")
    else:
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"

    # Save updated state
    state.save(state_file)

    return {
        "valid": True,
        "message": f"Step {step_id} completed successfully",
        "next_step": state.current_step_id,
    }


def initialize_workflow(task: str, branch: str) -> dict:
    """
    Initialize workflow state for new task.

    Args:
        task: Task description
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and state_file path
    """
    state_file = Path(f".map/{branch}/step_state.json")

    # Create fresh state
    state = StepState()
    state.save(state_file)

    return {
        "status": "initialized",
        "state_file": str(state_file),
        "task": task,
        "branch": branch,
    }


def set_plan_approved(value: str, branch: str) -> dict:
    """Persist explicit plan approval in step_state.json."""
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        state.plan_approved = True
    elif normalized in {"0", "false", "no", "n"}:
        state.plan_approved = False
    else:
        return {
            "status": "error",
            "message": f"Invalid value for plan approval: {value}",
        }
    state.save(state_file)
    return {"status": "success", "plan_approved": state.plan_approved}


def set_execution_mode(mode: str, branch: str) -> dict:
    """Persist execution mode in step_state.json."""
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    normalized = (mode or "").strip().lower()
    if normalized not in {"batch", "step_by_step"}:
        return {
            "status": "error",
            "message": f"Invalid execution_mode: {mode}. Use batch|step_by_step",
        }
    state.execution_mode = normalized
    state.save(state_file)
    return {"status": "success", "execution_mode": state.execution_mode}


def set_tdd_mode(value: str, branch: str) -> dict:
    """Enable or disable TDD mode (test-first workflow).

    When enabled, inserts TEST_WRITER (2.25) and TEST_FAIL_GATE (2.26)
    phases before ACTOR (2.3) in the step sequence.

    Args:
        value: "true" or "false"
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and tdd_mode value
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        state.tdd_mode = True
    elif normalized in {"0", "false", "no", "n"}:
        state.tdd_mode = False
    else:
        return {
            "status": "error",
            "message": f"Invalid value for tdd_mode: {value}",
        }

    # Rebuild pending_steps relative to current position (not from scratch)
    # to avoid re-introducing already-completed global steps (1.x)
    step_order = _get_step_order(state.tdd_mode)

    # When re-enabling TDD, remove 2.25/2.26 from skipped so they can run
    if state.tdd_mode:
        state.skipped_steps = [
            s for s in state.skipped_steps if s not in ("2.25", "2.26")
        ]

    done_and_skipped = set(state.completed_steps) | set(state.skipped_steps)

    if state.pending_steps:
        # Find position of first pending step in the new order
        first_pending = state.pending_steps[0]
        if first_pending in step_order:
            pos = step_order.index(first_pending)
            # When enabling TDD, also include TDD steps that come
            # just before the current position (2.25/2.26 before 2.3)
            if state.tdd_mode:
                # Find the earliest TDD step not yet done
                tdd_steps = {"2.25", "2.26"}
                earliest_tdd = None
                for i, s in enumerate(step_order):
                    if s in tdd_steps and s not in done_and_skipped and i < pos:
                        if earliest_tdd is None or i < earliest_tdd:
                            earliest_tdd = i
                if earliest_tdd is not None:
                    pos = earliest_tdd
            # Rebuild from position onwards, excluding done/skipped
            state.pending_steps = [
                s for s in step_order[pos:] if s not in done_and_skipped
            ]
        else:
            state.pending_steps = [s for s in step_order if s not in done_and_skipped]
    else:
        state.pending_steps = [s for s in step_order if s not in done_and_skipped]

    state.save(state_file)
    return {"status": "success", "tdd_mode": state.tdd_mode}


def set_waves(branch: str, blueprint_path: Optional[str] = None) -> dict:
    """Compute execution waves from blueprint DAG and store in step_state.json.

    Reads the blueprint JSON, builds a DependencyGraph, computes topological
    waves, and splits waves by file conflicts. Stores the result in
    step_state.execution_waves.

    Args:
        branch: Git branch name (sanitized)
        blueprint_path: Path to blueprint JSON (default: .map/<branch>/blueprint.json)

    Returns:
        Dict with status and computed waves
    """
    # Import here to avoid circular deps at module level
    try:
        from mapify_cli.dependency_graph import DependencyGraph, SubtaskNode
    except ImportError:
        # When running as a standalone script, dependency_graph.py may not be
        # importable from sys.path. Walk upward and look for src/mapify_cli/.
        import importlib.util

        dg_candidates = [Path("src/mapify_cli/dependency_graph.py")]
        for parent in Path(__file__).resolve().parents:
            dg_candidates.append(parent / "src" / "mapify_cli" / "dependency_graph.py")
        loaded = False
        for candidate in dg_candidates:
            if candidate.exists():
                spec = importlib.util.spec_from_file_location(
                    "dependency_graph", candidate
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    DependencyGraph = mod.DependencyGraph  # type: ignore[misc]  # noqa: N806
                    SubtaskNode = mod.SubtaskNode  # type: ignore[misc]  # noqa: N806
                    loaded = True
                    break
        if not loaded:
            return {
                "status": "error",
                "message": "Cannot import dependency_graph module",
            }

    if blueprint_path is None:
        blueprint_path = f".map/{branch}/blueprint.json"

    bp_file = Path(blueprint_path)
    if not bp_file.exists():
        return {
            "status": "error",
            "message": f"Blueprint not found: {blueprint_path}",
        }

    try:
        blueprint = json.loads(bp_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "message": f"Invalid blueprint: {exc}"}

    # Support both formats: full decomposer output (subtasks nested under
    # "blueprint" key) and flat format (subtasks at top level).
    if "blueprint" in blueprint and isinstance(blueprint["blueprint"], dict):
        subtasks = blueprint["blueprint"].get("subtasks", [])
    else:
        subtasks = blueprint.get("subtasks", [])
    if not subtasks:
        return {"status": "error", "message": "No subtasks in blueprint"}

    # Build graph
    graph = DependencyGraph()
    affected_files_map: dict[str, set] = {}
    for st in subtasks:
        st_id = st.get("id", "")
        deps = st.get("dependencies", [])
        graph.add_node(SubtaskNode(id=st_id, dependencies=deps))
        files = st.get("affected_files", [])
        affected_files_map[st_id] = set(files) if files else set()

    # Compute waves
    raw_waves = graph.compute_waves()
    if raw_waves is None:
        return {"status": "error", "message": "Cycle detected in dependency graph"}

    # Split each wave by file conflicts
    final_waves: list[list[str]] = []
    for wave in raw_waves:
        sub_waves = graph.split_wave_by_file_conflicts(wave, affected_files_map)
        final_waves.extend(sub_waves)

    # Store in state
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    state.execution_waves = final_waves
    state.current_wave_index = 0
    state.subtask_phases = {}
    state.subtask_retry_counts = {}
    state.save(state_file)

    return {
        "status": "success",
        "execution_waves": final_waves,
        "wave_count": len(final_waves),
    }


def get_wave_step(branch: str) -> dict:
    """Get the current wave's subtask batch and per-subtask phases.

    Returns JSON describing what to execute next in wave-based mode.

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with mode (parallel|sequential), wave_index, subtasks, is_complete
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if not state.execution_waves:
        return {
            "mode": "sequential",
            "wave_index": 0,
            "subtasks": [],
            "is_complete": True,
            "message": "No execution waves configured. Use sequential mode.",
        }

    if state.current_wave_index >= len(state.execution_waves):
        return {
            "mode": "sequential",
            "wave_index": state.current_wave_index,
            "subtasks": [],
            "is_complete": True,
        }

    wave = state.execution_waves[state.current_wave_index]
    mode = "sequential" if len(wave) == 1 else "parallel"

    # Build subtask info with current phases
    # Default start phase depends on TDD mode
    default_phase = "2.25" if state.tdd_mode else "2.3"
    subtask_infos = []
    for st_id in wave:
        phase = state.subtask_phases.get(st_id, default_phase)
        phase_name = STEP_PHASES.get(phase, "ACTOR")
        subtask_infos.append(
            {
                "subtask_id": st_id,
                "phase": phase_name,
                "step_id": phase,
            }
        )

    return {
        "mode": mode,
        "wave_index": state.current_wave_index,
        "wave_total": len(state.execution_waves),
        "subtasks": subtask_infos,
        "is_complete": False,
    }


def validate_wave_step(subtask_id: str, step_id: str, branch: str) -> dict:
    """Validate one subtask's step within a wave and advance its phase.

    Args:
        subtask_id: Subtask ID (e.g., "ST-002")
        step_id: Step ID completed (e.g., "2.3")
        branch: Git branch name (sanitized)

    Returns:
        Dict with validation result and next phase for this subtask
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    # Determine next phase for this subtask
    subtask_step_order = [
        s for s in _get_step_order(state.tdd_mode) if s.startswith("2.")
    ]
    current_idx = (
        subtask_step_order.index(step_id) if step_id in subtask_step_order else -1
    )

    if current_idx >= 0 and current_idx + 1 < len(subtask_step_order):
        next_phase = subtask_step_order[current_idx + 1]
    else:
        next_phase = "COMPLETE"

    state.subtask_phases[subtask_id] = next_phase
    state.save(state_file)

    return {
        "valid": True,
        "message": f"Step {step_id} for {subtask_id} completed",
        "next_phase": next_phase,
        "subtask_id": subtask_id,
    }


def advance_wave(branch: str) -> dict:
    """Advance to the next execution wave.

    Called when all subtasks in current wave have passed Monitor and per-wave gates.

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and new wave index
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if not state.execution_waves:
        return {"status": "error", "message": "No execution waves configured"}

    state.current_wave_index += 1
    # Reset per-subtask phases for the new wave
    state.subtask_phases = {}
    state.subtask_retry_counts = {}

    is_complete = state.current_wave_index >= len(state.execution_waves)

    # Update subtask_index and reset sequential state for next wave
    if not is_complete:
        next_wave = state.execution_waves[state.current_wave_index]
        if next_wave:
            state.current_subtask_id = next_wave[0]
            # Find the index in subtask_sequence
            if state.current_subtask_id in state.subtask_sequence:
                state.subtask_index = state.subtask_sequence.index(
                    state.current_subtask_id
                )
            # Reset sequential state so get_next_step works after advance_wave
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]
            state.completed_steps = []
            state.skipped_steps = []
            state.current_step_id = "2.2"
            state.current_step_phase = "RESEARCH"
            state.retry_count = 0

    state.save(state_file)

    return {
        "status": "success",
        "current_wave_index": state.current_wave_index,
        "is_complete": is_complete,
        "wave_total": len(state.execution_waves),
    }


def _write_feedback_file(
    branch: str, filename: str, header: str, feedback: str
) -> Optional[str]:
    """Write monitor feedback to a file if feedback is non-empty.

    Returns the file path string, or None if nothing was written.
    """
    if not feedback.strip():
        return None
    fb_path = Path(f".map/{branch}/{filename}")
    fb_path.parent.mkdir(parents=True, exist_ok=True)
    fb_path.write_text(f"# {header}\n\n{feedback}\n", encoding="utf-8")
    return str(fb_path)


def _check_retry_limit(
    current_retries: int, max_retries: int, context: dict
) -> Optional[dict]:
    """Return escalation dict if retry limit exceeded, else None.

    Shared by monitor_failed() and wave_monitor_failed() to avoid
    duplicating the limit-check + escalation-dict construction.

    Args:
        current_retries: Current retry count (already incremented).
        max_retries: Maximum allowed retries.
        context: Extra fields to include in the escalation dict
                 (e.g., subtask_id for wave mode).

    Returns:
        Escalation dict with status="max_retries" if limit exceeded,
        or None if still within limit.
    """
    if current_retries > max_retries:
        return {
            "status": "max_retries",
            "retry_count": current_retries,
            "max_retries": max_retries,
            **context,
        }
    return None


def monitor_failed(branch: str, feedback: str = "") -> dict:
    """Handle Monitor valid=false: requeue ACTOR+MONITOR, increment retry_count.

    Precondition: current_step_phase must be MONITOR. Called by map-efficient.md
    when Monitor returns valid=false. Switches phase back to ACTOR so
    workflow-gate allows edits. Persists monitor feedback to a file that Actor
    can read on next invocation.

    Args:
        branch: Git branch name (sanitized)
        feedback: Monitor's feedback_for_actor text (optional)

    Returns:
        Dict with status (retrying|max_retries), retry_count, feedback_file
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if state.current_step_phase != "MONITOR":
        return {
            "status": "error",
            "message": (
                f"monitor_failed() called from phase '{state.current_step_phase}', "
                "expected 'MONITOR'. Aborting to prevent state corruption."
            ),
        }

    state.retry_count += 1

    escalation = _check_retry_limit(
        state.retry_count,
        state.max_retries,
        {
            "message": (
                f"Monitor retry limit reached ({state.max_retries} attempts). "
                "Escalate to user."
            ),
        },
    )
    if escalation is not None:
        state.save(state_file)
        return escalation

    # Requeue only ACTOR (2.3) and MONITOR (2.4) on retry.
    # TDD pre-steps (2.25/2.26) are NOT re-run — tests were already written
    # and validated before the first Actor attempt.
    state.pending_steps = ["2.3", "2.4"]
    state.current_step_id = "2.3"
    state.current_step_phase = "ACTOR"

    # Persist feedback so Actor can read it (numbered to preserve history)
    feedback_file = _write_feedback_file(
        branch,
        f"monitor_feedback_retry{state.retry_count}.md",
        f"Monitor Feedback (retry {state.retry_count})",
        feedback,
    )

    state.save(state_file)

    return {
        "status": "retrying",
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
        "current_phase": "ACTOR",
        "feedback_file": feedback_file,
        "message": (
            f"Monitor failed. Retry {state.retry_count}/{state.max_retries}. "
            f"Phase reset to ACTOR for subtask {state.current_subtask_id}."
        ),
    }


def wave_monitor_failed(
    subtask_id: str, branch: str, feedback: str = ""
) -> dict:
    """Handle Monitor valid=false for a subtask within a wave.

    Resets the subtask's phase back to ACTOR and increments its retry count.

    Args:
        subtask_id: Subtask ID (e.g., "ST-002")
        branch: Git branch name (sanitized)
        feedback: Monitor's feedback_for_actor text (optional)

    Returns:
        Dict with status, retry_count for the subtask
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    # Increment per-subtask retry count
    current_retries = state.subtask_retry_counts.get(subtask_id, 0) + 1
    state.subtask_retry_counts[subtask_id] = current_retries

    escalation = _check_retry_limit(
        current_retries,
        state.max_retries,
        {
            "subtask_id": subtask_id,
            "message": (
                f"Monitor retry limit reached for {subtask_id} "
                f"({state.max_retries} attempts). Escalate to user."
            ),
        },
    )
    if escalation is not None:
        state.save(state_file)
        return escalation

    # Reset subtask phase back to ACTOR
    state.subtask_phases[subtask_id] = "2.3"

    # Persist feedback (numbered to preserve history)
    feedback_file = _write_feedback_file(
        branch,
        f"monitor_feedback_{subtask_id}_retry{current_retries}.md",
        f"Monitor Feedback for {subtask_id} (retry {current_retries})",
        feedback,
    )

    state.save(state_file)

    return {
        "status": "retrying",
        "subtask_id": subtask_id,
        "retry_count": current_retries,
        "max_retries": state.max_retries,
        "current_phase": "ACTOR",
        "feedback_file": feedback_file,
        "message": (
            f"Monitor failed for {subtask_id}. "
            f"Retry {current_retries}/{state.max_retries}. "
            f"Phase reset to ACTOR."
        ),
    }


def reopen_for_fixes(branch: str, feedback: str = "") -> dict:
    """Transition from COMPLETE back to ACTOR for post-review fixes.

    Called after /map-review finds issues in a completed workflow.
    The workflow gate blocks edits during COMPLETE phase; this function
    reopens the workflow so fixes can be applied.

    Args:
        branch: Git branch name (sanitized)
        feedback: Review feedback text describing what needs fixing

    Returns:
        Dict with status and new phase info
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": "No step_state.json found. Nothing to reopen.",
        }

    state = StepState.load(state_file)

    if state.current_step_phase != "COMPLETE":
        return {
            "status": "error",
            "message": (
                f"Workflow is in phase '{state.current_step_phase}', not COMPLETE. "
                "Use monitor_failed for non-COMPLETE retry."
            ),
        }

    # Reset to ACTOR+MONITOR cycle
    state.current_step_id = "2.3"
    state.current_step_phase = "ACTOR"
    state.pending_steps = ["2.3", "2.4"]
    state.retry_count = 0

    feedback_file = _write_feedback_file(
        branch,
        "review_feedback.md",
        "Review Feedback (post-COMPLETE reopen)",
        feedback,
    )

    state.save(state_file)

    return {
        "status": "reopened",
        "current_phase": "ACTOR",
        "feedback_file": feedback_file,
        "message": (
            "Workflow reopened from COMPLETE to ACTOR. "
            "Edit gate is now unlocked for review fixes."
        ),
    }


SKIPPABLE_STEPS = {"2.25", "2.26"}


def skip_step(step_id: str, branch: str) -> dict:
    """Skip a conditional step without executing it.

    Only steps that are defined as conditional can be skipped:
      - 2.25 (TEST_WRITER): TDD mode only, auto-skipped otherwise
      - 2.26 (TEST_FAIL_GATE): TDD mode only, auto-skipped otherwise

    Note: RESEARCH (2.2) is NOT skippable — it is mandatory for all subtasks.

    Args:
        step_id: Step identifier to skip
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and next step info
    """
    if step_id not in SKIPPABLE_STEPS:
        return {
            "status": "error",
            "message": (
                f"Step {step_id} cannot be skipped. "
                f"Only conditional steps can be skipped: "
                f"{', '.join(sorted(SKIPPABLE_STEPS))}"
            ),
        }

    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if state.current_step_id != step_id:
        return {
            "status": "error",
            "message": f"Step mismatch: current is {state.current_step_id}, cannot skip {step_id}",
        }

    # Mark step as completed (skipped) and advance
    state.completed_steps.append(step_id)
    if step_id in state.pending_steps:
        state.pending_steps.remove(step_id)

    # Advance to next pending step
    if state.pending_steps:
        next_id = state.pending_steps[0]
        state.current_step_id = next_id
        state.current_step_phase = STEP_PHASES.get(next_id, "UNKNOWN")
    else:
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"

    state.save(state_file)

    return {
        "status": "success",
        "message": f"Step {step_id} skipped",
        "next_step": state.current_step_id,
    }


def check_circuit_breaker(branch: str) -> dict:
    """Check circuit breaker status based on completed steps count.

    Returns tool_count (total completed steps) and max_iterations threshold.
    If tool_count >= max_iterations, the workflow should ask the user to continue or abort.

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with tool_count, max_iterations, triggered flag
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    tool_count = len(state.completed_steps)
    max_iterations = len(state.subtask_sequence) * len(_get_step_order(state.tdd_mode))

    return {
        "tool_count": tool_count,
        "max_iterations": max_iterations,
        "triggered": tool_count >= max_iterations,
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
    }


def set_subtasks(subtask_ids: list[str], branch: str) -> dict:
    """Set subtask sequence after decomposition and select the first subtask.

    Args:
        subtask_ids: List of subtask IDs (e.g., ["ST-001", "ST-002", "ST-003"])
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and subtask info
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if not subtask_ids:
        return {"status": "error", "message": "At least one subtask ID is required"}

    state.subtask_sequence = subtask_ids
    state.current_subtask_id = subtask_ids[0]
    state.subtask_index = 0
    state.save(state_file)

    return {
        "status": "success",
        "subtask_sequence": subtask_ids,
        "current_subtask_id": subtask_ids[0],
    }


def _contract_artifact_paths(branch: str, subtask_id: str) -> tuple[Path, Path]:
    """Return the expected persisted TDD contract artifact paths."""
    plan_dir = Path(f".map/{branch}")
    return (
        plan_dir / f"test_contract_{subtask_id}.md",
        plan_dir / f"test_handoff_{subtask_id}.json",
    )


def mark_contract_ready(subtask_id: str, branch: str) -> dict:
    """Stop execution after TEST_FAIL_GATE and mark the test contract ready."""
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": "No step_state.json found. Initialize TDD workflow first.",
        }

    contract_path, handoff_path = _contract_artifact_paths(branch, subtask_id)
    missing = [
        str(path)
        for path in (contract_path, handoff_path)
        if not path.exists()
    ]
    if missing:
        return {
            "status": "error",
            "message": "Missing persisted TDD artifacts: " + ", ".join(missing),
        }

    state = StepState.load(state_file)
    if state.current_subtask_id and state.current_subtask_id != subtask_id:
        return {
            "status": "error",
            "message": (
                f"Current subtask is {state.current_subtask_id}, not {subtask_id}. "
                "Refusing to mark the wrong contract ready."
            ),
        }

    state.contract_ready_subtasks[subtask_id] = {
        "contract_path": str(contract_path),
        "handoff_path": str(handoff_path),
        "ready_at": _utc_timestamp(),
    }
    state.workflow_status = "CONTRACT_READY"
    state.current_step_id = "CONTRACT_READY"
    state.current_step_phase = "CONTRACT_READY"
    state.pending_steps = ["CONTRACT_READY"]
    state.save(state_file)

    return {
        "status": "success",
        "workflow_status": state.workflow_status,
        "subtask_id": subtask_id,
        "contract_path": str(contract_path),
        "handoff_path": str(handoff_path),
        "message": (
            f"Persisted TDD contract ready for {subtask_id}. "
            "Resume implementation with /map-task for a clean ACTOR session."
        ),
    }


def resume_from_test_contract(subtask_id: str, branch: str) -> dict:
    """Resume a single subtask at ACTOR using a persisted TDD handoff."""
    plan_dir = Path(f".map/{branch}")
    plan_file = plan_dir / f"task_plan_{branch}.md"
    if not plan_file.exists():
        return {
            "status": "error",
            "message": f"No plan found at {plan_file}. Run /map-plan first.",
        }

    contract_path, handoff_path = _contract_artifact_paths(branch, subtask_id)
    missing = [
        str(path)
        for path in (contract_path, handoff_path)
        if not path.exists()
    ]
    if missing:
        return {
            "status": "error",
            "message": "Missing persisted TDD artifacts: " + ", ".join(missing),
        }

    import re

    plan_content = plan_file.read_text(encoding="utf-8")
    all_subtask_ids = re.findall(r"###\s+(ST-\d+)", plan_content)
    if subtask_id not in all_subtask_ids:
        return {
            "status": "error",
            "message": (
                f"Subtask {subtask_id} not found in plan. "
                f"Available: {', '.join(all_subtask_ids)}"
            ),
        }

    previous_state = StepState.load(plan_dir / "step_state.json")
    contract_entry = previous_state.contract_ready_subtasks.get(
        subtask_id,
        {
            "contract_path": str(contract_path),
            "handoff_path": str(handoff_path),
            "ready_at": _utc_timestamp(),
        },
    )

    state = StepState(
        current_subtask_id=subtask_id,
        subtask_index=0,
        subtask_sequence=[subtask_id],
        current_step_id="2.3",
        current_step_phase="ACTOR",
        completed_steps=["1.0", "1.5", "1.55", "1.56", "1.6", "2.2", "2.25", "2.26"],
        pending_steps=["2.3", "2.4"],
        plan_approved=True,
        execution_mode="batch",
        tdd_mode=True,
        workflow_status="IN_PROGRESS",
        contract_ready_subtasks={subtask_id: contract_entry},
    )
    state.save(plan_dir / "step_state.json")

    briefing = get_resume_briefing(branch)
    return {
        "status": "success",
        "message": (
            f"Resuming {subtask_id} from persisted test contract. "
            "Starting at ACTOR."
        ),
        "subtask_id": subtask_id,
        "next_phase": "ACTOR",
        "contract_path": str(contract_path),
        "handoff_path": str(handoff_path),
        "resume_briefing": briefing,
    }


def resume_from_plan(branch: str) -> dict:
    """Resume workflow from an existing /map-plan output, skipping init phases.

    Detects task_plan_<branch>.md and step_state.json created by /map-plan.
    Extracts subtask IDs from the plan, marks init phases as completed, and
    starts execution from INIT_STATE (batch mode auto-set).

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and skipped phases
    """
    plan_dir = Path(f".map/{branch}")
    plan_file = plan_dir / f"task_plan_{branch}.md"

    # Verify plan artifacts exist
    if not plan_file.exists():
        return {
            "status": "error",
            "message": f"No plan found at {plan_file}. Run /map-plan first.",
        }

    # Extract subtask IDs from plan file (ST-XXX pattern)
    import re

    plan_content = plan_file.read_text(encoding="utf-8")
    subtask_ids = re.findall(r"###\s+(ST-\d+)", plan_content)

    if not subtask_ids:
        return {
            "status": "error",
            "message": f"No subtask IDs (ST-XXX) found in {plan_file}.",
        }

    # Extract AAG contracts from step_state.json or blueprint.json if present
    aag_contracts: dict[str, str] = {}
    step_state_file = plan_dir / "step_state.json"
    blueprint_file = plan_dir / "blueprint.json"
    for source_file in [step_state_file, blueprint_file]:
        if source_file.exists() and not aag_contracts:
            try:
                src_data = json.loads(source_file.read_text(encoding="utf-8"))
                aag_contracts = src_data.get("aag_contracts", {})
            except (json.JSONDecodeError, KeyError):
                pass

    # Create state that skips DECOMPOSE, INIT_PLAN, REVIEW_PLAN, CHOOSE_MODE
    # (plan already approved, execution mode is always batch)
    skipped_phases = ["1.0", "1.5", "1.55", "1.56"]
    execution_start = [s for s in STEP_ORDER if s not in skipped_phases]

    state_file = plan_dir / "step_state.json"
    state = StepState(
        current_subtask_id=subtask_ids[0],
        subtask_index=0,
        subtask_sequence=subtask_ids,
        current_step_id=execution_start[0] if execution_start else "1.6",
        current_step_phase=(
            STEP_PHASES.get(execution_start[0], "INIT_STATE")
            if execution_start
            else "INIT_STATE"
        ),
        completed_steps=skipped_phases,
        pending_steps=execution_start,
        plan_approved=True,
        execution_mode="batch",
        workflow_status="IN_PROGRESS",
    )
    state.save(state_file)

    briefing = get_resume_briefing(branch)

    return {
        "status": "success",
        "message": "Resumed from /map-plan. Skipped DECOMPOSE, INIT_PLAN, REVIEW_PLAN, CHOOSE_MODE. Mode: batch.",
        "subtask_sequence": subtask_ids,
        "current_subtask_id": subtask_ids[0],
        "aag_contracts_found": len(aag_contracts),
        "next_phase": "INIT_STATE",
        "resume_briefing": briefing,
    }


def get_plan_progress(branch: str) -> dict:
    """Return status of all subtasks from the task plan.

    Reads task_plan_<branch>.md and extracts subtask IDs with their statuses.
    Identifies the next pending subtask (respecting dependency order from blueprint).

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with subtask statuses, completed/pending counts, and suggested next
    """
    import re

    plan_dir = Path(f".map/{branch}")
    plan_file = plan_dir / f"task_plan_{branch}.md"

    if not plan_file.exists():
        return {"status": "error", "message": f"No plan found at {plan_file}."}

    content = plan_file.read_text(encoding="utf-8")

    # Extract subtask IDs and statuses: ### ST-XXX ... \n- **Status:** <status>
    subtasks = []
    for match in re.finditer(
        r"###\s+(ST-\d+)[^\n]*\n(?:.*?\n)*?- \*\*Status:\*\*\s+(\w+)",
        content,
    ):
        subtasks.append({"id": match.group(1), "status": match.group(2)})

    if not subtasks:
        # Fallback: just extract IDs without status
        ids = re.findall(r"###\s+(ST-\d+)", content)
        subtasks = [{"id": sid, "status": "unknown"} for sid in ids]

    completed = [s for s in subtasks if s["status"] == "complete"]
    pending = [s for s in subtasks if s["status"] != "complete"]

    # Determine suggested next subtask (first pending in plan order)
    suggested_next = pending[0]["id"] if pending else None

    briefing = get_resume_briefing(branch)

    return {
        "status": "success",
        "total": len(subtasks),
        "completed_count": len(completed),
        "pending_count": len(pending),
        "subtasks": subtasks,
        "completed": [s["id"] for s in completed],
        "pending": [s["id"] for s in pending],
        "suggested_next": suggested_next,
        "resume_briefing": briefing,
    }


def resume_single_subtask(subtask_id: str, branch: str, tdd_mode: bool = False) -> dict:
    """Set up state to execute a single subtask from an existing plan.

    Requires task_plan_<branch>.md to exist (created by /map-plan or decomposer).
    Validates that the requested subtask ID exists in the plan.
    Creates state starting from RESEARCH (2.2) for just that one subtask.

    Args:
        subtask_id: The subtask to execute (e.g., "ST-001")
        branch: Git branch name (sanitized)
        tdd_mode: Whether to enable TDD mode for this subtask

    Returns:
        Dict with status and state info
    """
    plan_dir = Path(f".map/{branch}")
    plan_file = plan_dir / f"task_plan_{branch}.md"

    if not plan_file.exists():
        return {
            "status": "error",
            "message": f"No plan found at {plan_file}. Run /map-plan first.",
        }

    import re

    plan_content = plan_file.read_text(encoding="utf-8")
    all_subtask_ids = re.findall(r"###\s+(ST-\d+)", plan_content)

    if not all_subtask_ids:
        return {
            "status": "error",
            "message": f"No subtask IDs (ST-XXX) found in {plan_file}.",
        }

    if subtask_id not in all_subtask_ids:
        return {
            "status": "error",
            "message": (
                f"Subtask {subtask_id} not found in plan. "
                f"Available: {', '.join(all_subtask_ids)}"
            ),
        }

    # Build state for single subtask execution
    step_order = _get_step_order(tdd_mode)
    research_idx = step_order.index("2.2")
    subtask_steps = step_order[research_idx:]

    state_file = plan_dir / "step_state.json"
    state = StepState(
        current_subtask_id=subtask_id,
        subtask_index=0,
        subtask_sequence=[subtask_id],  # Only this one subtask
        current_step_id="2.2",
        current_step_phase="RESEARCH",
        completed_steps=["1.0", "1.5", "1.55", "1.56", "1.6"],
        pending_steps=subtask_steps,
        plan_approved=True,
        execution_mode="batch",
        tdd_mode=tdd_mode,
        workflow_status="IN_PROGRESS",
    )
    state.save(state_file)

    briefing = get_resume_briefing(branch)

    return {
        "status": "success",
        "message": (
            f"Single subtask mode: {subtask_id}. "
            f"TDD: {'enabled' if tdd_mode else 'disabled'}. "
            f"Starting from RESEARCH."
        ),
        "subtask_id": subtask_id,
        "tdd_mode": tdd_mode,
        "all_subtasks_in_plan": all_subtask_ids,
        "next_phase": "RESEARCH",
        "resume_briefing": briefing,
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MAP Workflow State Machine Orchestrator"
    )
    parser.add_argument(
        "command",
        choices=[
            "get_next_step",
            "validate_step",
            "initialize",
            "set_plan_approved",
            "set_execution_mode",
            "set_tdd_mode",
            "skip_step",
            "set_subtasks",
            "mark_contract_ready",
            "resume_from_plan",
            "resume_from_test_contract",
            "check_circuit_breaker",
            "set_waves",
            "get_wave_step",
            "validate_wave_step",
            "advance_wave",
            "resume_single_subtask",
            "get_plan_progress",
            "monitor_failed",
            "wave_monitor_failed",
            "reopen_for_fixes",
        ],
        help="Command to execute",
    )
    parser.add_argument(
        "task_or_step", nargs="?", help="Task description, step ID, or subtask IDs"
    )
    parser.add_argument(
        "extra_args", nargs="*", help="Additional arguments (e.g., more subtask IDs)"
    )
    parser.add_argument("--branch", help="Git branch (auto-detected if omitted)")
    parser.add_argument(
        "--blueprint", help="Path to blueprint JSON (for set_waves command)"
    )
    parser.add_argument(
        "--tdd", action="store_true", help="Enable TDD mode (for resume_single_subtask)"
    )
    parser.add_argument(
        "--feedback",
        help="Monitor feedback text (for monitor_failed / wave_monitor_failed)",
    )

    args = parser.parse_args()

    # Get branch
    branch = args.branch if args.branch else get_branch_name()

    try:
        if args.command == "get_next_step":
            result = get_next_step(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "validate_step":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "step_id required for validate_step"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = validate_step(args.task_or_step, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "initialize":
            task = args.task_or_step or "MAP workflow task"
            result = initialize_workflow(task, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "set_plan_approved":
            value = args.task_or_step
            if value is None:
                print(
                    json.dumps({"error": "value required for set_plan_approved"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = set_plan_approved(value, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "set_execution_mode":
            mode = args.task_or_step
            if mode is None:
                print(
                    json.dumps({"error": "mode required for set_execution_mode"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = set_execution_mode(mode, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "set_tdd_mode":
            value = args.task_or_step
            if value is None:
                print(
                    json.dumps({"error": "value required for set_tdd_mode"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = set_tdd_mode(value, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "skip_step":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "step_id required for skip_step"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = skip_step(args.task_or_step, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "set_subtasks":
            if not args.task_or_step:
                print(
                    json.dumps(
                        {
                            "error": "At least one subtask ID required. "
                            "Usage: set_subtasks ST-001 ST-002 ST-003"
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            subtask_ids = [args.task_or_step] + (args.extra_args or [])
            result = set_subtasks(subtask_ids, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "mark_contract_ready":
            if not args.task_or_step:
                print(
                    json.dumps(
                        {
                            "error": (
                                "subtask_id required. "
                                "Usage: mark_contract_ready ST-001"
                            )
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = mark_contract_ready(args.task_or_step, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "resume_from_plan":
            result = resume_from_plan(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "resume_from_test_contract":
            if not args.task_or_step:
                print(
                    json.dumps(
                        {
                            "error": (
                                "subtask_id required. "
                                "Usage: resume_from_test_contract ST-001"
                            )
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = resume_from_test_contract(args.task_or_step, branch)
            print(json.dumps(result, indent=2))

        elif args.command == "check_circuit_breaker":
            result = check_circuit_breaker(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "set_waves":
            blueprint_path = (
                args.blueprint or args.task_or_step
            )  # --blueprint or positional
            result = set_waves(branch, blueprint_path)
            print(json.dumps(result, indent=2))

        elif args.command == "get_wave_step":
            result = get_wave_step(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "validate_wave_step":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "subtask_id required for validate_wave_step"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            extra = args.extra_args or []
            if not extra:
                print(
                    json.dumps({"error": "step_id required as second argument"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = validate_wave_step(args.task_or_step, extra[0], branch)
            print(json.dumps(result, indent=2))

        elif args.command == "advance_wave":
            result = advance_wave(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "resume_single_subtask":
            if not args.task_or_step:
                print(
                    json.dumps(
                        {
                            "error": "subtask_id required. Usage: resume_single_subtask ST-001 [--tdd]"
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = resume_single_subtask(args.task_or_step, branch, tdd_mode=args.tdd)
            print(json.dumps(result, indent=2))

        elif args.command == "get_plan_progress":
            result = get_plan_progress(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "monitor_failed":
            feedback = args.feedback or ""
            result = monitor_failed(branch, feedback)
            print(json.dumps(result, indent=2))

        elif args.command == "wave_monitor_failed":
            if not args.task_or_step:
                print(
                    json.dumps(
                        {"error": "subtask_id required. Usage: wave_monitor_failed ST-001 --feedback 'text'"}
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            feedback = args.feedback or ""
            result = wave_monitor_failed(args.task_or_step, branch, feedback)
            print(json.dumps(result, indent=2))

        elif args.command == "reopen_for_fixes":
            feedback = args.feedback or ""
            result = reopen_for_fixes(branch, feedback)
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
