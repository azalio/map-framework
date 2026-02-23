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
      "current_step_id": "2.1",
      "current_step_phase": "CONTEXT_SEARCH",
      "completed_steps": ["1.0_DECOMPOSE", "1.5_INIT_PLAN", "2.0_XML_PACKET"],
      "pending_steps": ["2.1_CONTEXT_SEARCH", "2.3_ACTOR", "2.4_MONITOR", ...]
    }

STEP PHASES (16 total):
  1.0  DECOMPOSE          - task-decomposer agent
  1.5  INIT_PLAN          - Generate task_plan.md
  1.55 REVIEW_PLAN        - User review + explicit approval checkpoint
  1.56 CHOOSE_MODE        - Choose execution mode (step_by_step|batch)
  1.6  INIT_STATE         - Create workflow_state.json
  2.0  XML_PACKET         - Build AI-friendly subtask packet
  2.1  CONTEXT_SEARCH     - Context search
  2.2  RESEARCH           - research-agent (conditional)
  2.3  ACTOR              - Actor agent implementation
  2.4  MONITOR            - Monitor validation
  2.6  PREDICTOR          - Impact analysis (conditional)
  2.7  UPDATE_STATE       - Mark subtask progress
  2.8  TESTS_GATE         - Run tests
  2.9  LINTER_GATE        - Run linter
  2.10 VERIFY_ADHERENCE   - Self-audit checkpoint
  2.11 SUBTASK_APPROVAL   - Optional pause between subtasks (step_by_step)

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
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Step phase definitions with execution order
STEP_PHASES = {
    "1.0": "DECOMPOSE",
    "1.5": "INIT_PLAN",
    "1.55": "REVIEW_PLAN",
    "1.56": "CHOOSE_MODE",
    "1.6": "INIT_STATE",
    "2.0": "XML_PACKET",
    "2.1": "CONTEXT_SEARCH",
    "2.2": "RESEARCH",
    "2.3": "ACTOR",
    "2.4": "MONITOR",
    "2.6": "PREDICTOR",
    "2.7": "UPDATE_STATE",
    "2.8": "TESTS_GATE",
    "2.9": "LINTER_GATE",
    "2.10": "VERIFY_ADHERENCE",
    "2.11": "SUBTASK_APPROVAL",
}

# Step execution order
STEP_ORDER = [
    "1.0",
    "1.5",
    "1.55",
    "1.56",
    "1.6",
    "2.0",
    "2.1",
    "2.2",
    "2.3",
    "2.4",
    "2.6",
    "2.7",
    "2.8",
    "2.9",
    "2.10",
    "2.11",
]

# Steps that require evidence files from agents before validation.
# Format: step_id -> (agent_phase, always_required)
# If always_required is False, evidence is only checked when the step
# appears in pending_steps (i.e., it wasn't skipped).
EVIDENCE_REQUIRED = {
    "2.3": ("actor", True),      # Always required
    "2.4": ("monitor", True),    # Always required
    "2.6": ("predictor", False), # Only when 2.6 is in pending_steps
}


@dataclass
class StepState:
    """Workflow step state tracking."""

    workflow: str = "map-efficient"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_subtask_id: Optional[str] = None
    subtask_index: int = 0
    subtask_sequence: List[str] = field(default_factory=list)
    current_step_id: str = "1.0"
    current_step_phase: str = "DECOMPOSE"
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=lambda: STEP_ORDER.copy())
    retry_count: int = 0
    max_retries: int = 5
    plan_approved: bool = False
    execution_mode: str = "batch"  # batch|step_by_step

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


def get_branch_name() -> str:
    """Get sanitized git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            import re

            sanitized = branch.replace("/", "-")
            sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
            sanitized = re.sub(r"-+", "-", sanitized).strip("-")
            if ".." in sanitized or sanitized.startswith("."):
                return "default"
            return sanitized or "default"
        return "default"
    except Exception:
        return "default"


def get_step_instruction(step_id: str, state: StepState) -> str:
    """
    Get instruction for executing a specific step.

    Args:
        step_id: Step identifier (e.g., "2.1")
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
            "Ask user to choose execution mode: step_by_step (pause between subtasks) "
            "or batch (run through). Persist choice in step_state.json: "
            "python3 .map/scripts/map_orchestrator.py set_execution_mode step_by_step|batch"
        ),
        "1.6": (
            "Create .map/<branch>/workflow_state.json with initial state. "
            "Required for workflow-gate.py enforcement."
        ),
        "2.0": (
            f"Build XML packet for subtask {state.current_subtask_id}. "
            "Include ID, title, description, risk_level, affected_files, "
            "validation_criteria, and test_strategy."
        ),
        "2.1": (
            "Search for relevant patterns and context. "
            "Re-rank by relevance and pass top 3 to Actor."
        ),
        "2.2": (
            "Call Task(subagent_type='research-agent') if refactoring or "
            "touching 3+ files. Pass findings to Actor."
        ),
        "2.3": (
            f"Call Task(subagent_type='actor') to implement subtask "
            f"{state.current_subtask_id}. Pass XML packet and context patterns. "
            f"Actor MUST write evidence file: "
            f".map/<branch>/evidence/actor_{state.current_subtask_id}.json"
        ),
        "2.4": (
            "Call Task(subagent_type='monitor') to validate Actor output. "
            "Check correctness, security, standards, and tests. "
            f"Monitor MUST write evidence file: "
            f".map/<branch>/evidence/monitor_{state.current_subtask_id}.json"
        ),
        "2.6": (
            "Call Task(subagent_type='predictor') for impact analysis "
            "(required for medium/high risk subtasks). "
            f"Predictor MUST write evidence file: "
            f".map/<branch>/evidence/predictor_{state.current_subtask_id}.json"
        ),
        "2.7": (
            "Update workflow state to mark subtask progress. "
            "Code was already applied by Actor and validated by Monitor."
        ),
        "2.8": (
            "Run tests using pytest/npm test/go test/cargo test. "
            "Skip if no tests available."
        ),
        "2.9": (
            "Run linter using ruff/eslint/golangci-lint/cargo clippy. "
            "Skip if not configured."
        ),
        "2.10": (
            "Output workflow adherence self-audit. "
            "Verify all required steps completed before marking subtask done."
        ),
        "2.11": (
            "If execution_mode == step_by_step: show a brief checkpoint for the completed subtask "
            "and AskUserQuestion to continue to the next subtask or abort. "
            "If execution_mode == batch: this step is auto-skipped by orchestrator."
        ),
    }

    return instructions.get(step_id, f"Execute step {step_id} ({phase})")


def get_next_step(branch: str) -> Dict:
    """
    Determine next step in workflow.

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with step_id, phase, instruction, is_complete
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    # Auto-skip steps that are conditional in batch mode
    while (
        state.pending_steps
        and state.pending_steps[0] == "2.11"
        and state.execution_mode == "batch"
    ):
        state.completed_steps.append("2.11")
        state.pending_steps.pop(0)
        state.save(state_file)

    # Check if workflow complete
    if not state.pending_steps:
        # Check if more subtasks remain
        if state.subtask_index + 1 < len(state.subtask_sequence):
            # Move to next subtask, reset steps
            state.subtask_index += 1
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            state.current_step_id = "2.0"
            state.current_step_phase = "XML_PACKET"
            # Reset to subtask-level steps (skip global setup steps)
            xml_packet_idx = STEP_ORDER.index("2.0")
            state.pending_steps = STEP_ORDER[xml_packet_idx:]  # Start from 2.0
            state.completed_steps = []
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


def validate_step(step_id: str, branch: str) -> Dict:
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
    if step_id == "1.56" and state.execution_mode not in {"batch", "step_by_step"}:
        return {
            "valid": False,
            "message": "Invalid execution_mode. Set mode first: python3 .map/scripts/map_orchestrator.py set_execution_mode step_by_step|batch",
        }

    # Evidence-gated validation: require agent evidence files for key steps
    if step_id in EVIDENCE_REQUIRED:
        phase_name, always_required = EVIDENCE_REQUIRED[step_id]
        evidence_dir = Path(f".map/{branch}/evidence")
        if not evidence_dir.is_dir():
            return {
                "valid": False,
                "message": (
                    f"Evidence directory missing: {evidence_dir}. "
                    f"Run initialize or resume_from_plan first."
                ),
            }
        subtask_id = state.current_subtask_id or "unknown"
        evidence_file = evidence_dir / f"{phase_name}_{subtask_id}.json"
        if not evidence_file.exists():
            return {
                "valid": False,
                "message": (
                    f"Evidence file missing: {evidence_file}. "
                    f"The {phase_name} agent must write this file before "
                    f"validate_step can accept step {step_id}."
                ),
            }
        # Validate JSON structure
        try:
            evidence_data = json.loads(
                evidence_file.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "valid": False,
                "message": (
                    f"Evidence file {evidence_file} is not valid JSON: {exc}"
                ),
            }
        # Check required fields
        for required_field in ("phase", "subtask_id", "timestamp"):
            if required_field not in evidence_data:
                return {
                    "valid": False,
                    "message": (
                        f"Evidence file {evidence_file} missing required "
                        f"field: '{required_field}'. "
                        f"Required fields: phase, subtask_id, timestamp."
                    ),
                }
        # Validate subtask_id matches current subtask
        if evidence_data.get("subtask_id") != subtask_id:
            return {
                "valid": False,
                "message": (
                    f"Evidence file subtask_id mismatch: "
                    f"expected '{subtask_id}', "
                    f"got '{evidence_data.get('subtask_id')}'."
                ),
            }

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


def initialize_workflow(task: str, branch: str) -> Dict:
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

    # Create evidence directory for artifact-gated validation
    evidence_dir = Path(f".map/{branch}/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    return {
        "status": "initialized",
        "state_file": str(state_file),
        "task": task,
        "branch": branch,
    }


def set_plan_approved(value: str, branch: str) -> Dict:
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


def set_execution_mode(mode: str, branch: str) -> Dict:
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


SKIPPABLE_STEPS = {"2.2", "2.6", "2.11"}


def skip_step(step_id: str, branch: str) -> Dict:
    """Skip a conditional step without executing it.

    Only steps that are defined as conditional can be skipped:
      - 2.2 (RESEARCH): conditional on refactoring or 3+ files
      - 2.6 (PREDICTOR): conditional on medium/high risk
      - 2.11 (SUBTASK_APPROVAL): conditional on step_by_step mode

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


def check_circuit_breaker(branch: str) -> Dict:
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
    max_iterations = len(state.subtask_sequence) * len(STEP_ORDER)

    return {
        "tool_count": tool_count,
        "max_iterations": max_iterations,
        "triggered": tool_count >= max_iterations,
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
    }


def set_subtasks(subtask_ids: List[str], branch: str) -> Dict:
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


def resume_from_plan(branch: str) -> Dict:
    """Resume workflow from an existing /map-plan output, skipping init phases.

    Detects task_plan_<branch>.md and workflow_state.json created by /map-plan.
    Extracts subtask IDs from the plan, marks init phases as completed, and
    starts execution from CHOOSE_MODE (user still picks step_by_step vs batch).

    Args:
        branch: Git branch name (sanitized)

    Returns:
        Dict with status and skipped phases
    """
    plan_dir = Path(f".map/{branch}")
    plan_file = plan_dir / f"task_plan_{branch}.md"
    workflow_state_file = plan_dir / "workflow_state.json"

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

    # Extract AAG contracts if present in workflow_state.json
    aag_contracts = {}
    if workflow_state_file.exists():
        try:
            ws_data = json.loads(workflow_state_file.read_text(encoding="utf-8"))
            aag_contracts = ws_data.get("aag_contracts", {})
        except (json.JSONDecodeError, KeyError):
            pass

    # Create state that skips DECOMPOSE, INIT_PLAN, REVIEW_PLAN (plan already approved)
    # Start from CHOOSE_MODE so user can still pick execution mode
    skipped_phases = ["1.0", "1.5", "1.55"]
    execution_start = [s for s in STEP_ORDER if s not in skipped_phases]

    state_file = plan_dir / "step_state.json"
    state = StepState(
        current_subtask_id=subtask_ids[0],
        subtask_index=0,
        subtask_sequence=subtask_ids,
        current_step_id="1.56",
        current_step_phase="CHOOSE_MODE",
        completed_steps=skipped_phases,
        pending_steps=execution_start,
        plan_approved=True,
    )
    state.save(state_file)

    # Create evidence directory for artifact-gated validation
    evidence_dir = plan_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    return {
        "status": "success",
        "message": "Resumed from /map-plan. Skipped DECOMPOSE, INIT_PLAN, REVIEW_PLAN.",
        "subtask_sequence": subtask_ids,
        "current_subtask_id": subtask_ids[0],
        "aag_contracts_found": len(aag_contracts),
        "next_phase": "CHOOSE_MODE",
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
            "skip_step",
            "set_subtasks",
            "resume_from_plan",
            "check_circuit_breaker",
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

        elif args.command == "resume_from_plan":
            result = resume_from_plan(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "check_circuit_breaker":
            result = check_circuit_breaker(branch)
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
