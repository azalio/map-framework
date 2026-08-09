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
  2.2  RESEARCH           - persisted research artifact (mandatory; research-agent conditional)
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
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _shorten_text(text: str, max_chars: int = 1_200) -> str:
    """Return compact, artifact-safe text without preserving full failed context."""
    compact = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 15].rstrip() + "\n[truncated]"


_SUBTASK_ID_FULL_RE = re.compile(r"ST-\d+\Z")


def _dedupe_subtask_ids(subtask_ids: list[str]) -> list[str]:
    """Return subtask IDs in first-seen order without duplicates."""
    seen: set[str] = set()
    unique: list[str] = []
    for subtask_id in subtask_ids:
        if subtask_id in seen:
            continue
        seen.add(subtask_id)
        unique.append(subtask_id)
    return unique


def _extract_subtask_ids_from_blueprint(blueprint_file: Path) -> list[str]:
    """Extract ordered subtask IDs from blueprint.json when available."""
    if not blueprint_file.exists():
        return []
    try:
        data = json.loads(blueprint_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    subtasks = data.get("subtasks")
    if not isinstance(subtasks, list):
        return []

    subtask_ids: list[str] = []
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        subtask_id = subtask.get("id")
        if isinstance(subtask_id, str) and _SUBTASK_ID_FULL_RE.fullmatch(
            subtask_id.strip()
        ):
            subtask_ids.append(subtask_id.strip())
    return _dedupe_subtask_ids(subtask_ids)


def _extract_subtask_ids_from_plan_markdown(plan_content: str) -> list[str]:
    """Extract ordered subtask IDs from supported task_plan.md layouts."""
    subtask_ids: list[str] = []
    for line in plan_content.splitlines():
        heading_match = re.match(r"\s{0,3}#{1,6}\s+(ST-\d+)\b", line)
        if heading_match:
            subtask_ids.append(heading_match.group(1))
            continue

        table_match = re.match(r"\s*\|\s*(ST-\d+)\s*\|", line)
        if table_match:
            subtask_ids.append(table_match.group(1))
            continue

        bullet_match = re.match(r"\s*[-*]\s+(?:\[[ xX]\]\s*)?(ST-\d+)\b", line)
        if bullet_match:
            subtask_ids.append(bullet_match.group(1))

    return _dedupe_subtask_ids(subtask_ids)


def _extract_subtask_ids_from_plan_artifacts(
    plan_content: str,
    blueprint_file: Path,
) -> list[str]:
    """Prefer structured blueprint IDs, falling back to human plan markdown."""
    blueprint_ids = _extract_subtask_ids_from_blueprint(blueprint_file)
    if blueprint_ids:
        return blueprint_ids
    return _extract_subtask_ids_from_plan_markdown(plan_content)


AGGRESSIVE_COMPRESSION_MULTIPLIER = 0.4

# Slice 3: sequential-inside wave-loop. Slice 5 flips this to True when
# concurrent Task dispatch is actually implemented and safe to enable.
WAVE_CONCURRENCY_ENABLED = False

# Stable reason codes for get_wave_step return sites (ST-002).
WAVE_REASON_NO_WAVES = "no_waves"
WAVE_REASON_WAVE_COMPLETE = "wave_complete"
WAVE_REASON_DISPATCH_SEQUENTIAL = "dispatch_sequential_5a"
# Stable reason codes for compute_dispatch_gate (ST-001, Slice 5b).
WAVE_REASON_CONCURRENT_GATED = "concurrent_gated"
WAVE_REASON_GATE_NOT_PARALLELIZABLE = "gate_not_parallelizable"
# Current wave is width-1 even though a later wave is parallel; dispatch sequentially
# for this wave — not an error, just the natural plan structure.
WAVE_REASON_CURRENT_WAVE_SEQUENTIAL = "current_wave_sequential"
# Kill-switch reason: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 forces the full legacy sequential path.
WAVE_REASON_SEQUENTIAL_ONLY_ENV = "sequential_only_env"

# Truthy string values for MAP_EFFICIENT_SEQUENTIAL_ONLY env kill-switch.
_SEQUENTIAL_ONLY_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _sequential_only_env() -> bool:
    """Return True when MAP_EFFICIENT_SEQUENTIAL_ONLY is set to a truthy value.

    Truthy: {"1", "true", "yes", "y", "on"} (case-insensitive).
    When True, forces the full legacy sequential path regardless of config —
    no wave-loop, no worktrees, no concurrent dispatch.  This is the global
    kill-switch / off-ramp introduced in Slice 6 (byte-identical to pre-5a legacy).
    Never raises.
    """
    val = os.environ.get("MAP_EFFICIENT_SEQUENTIAL_ONLY", "")
    return val.strip().lower() in _SEQUENTIAL_ONLY_TRUTHY


class DispatchGateError(RuntimeError):
    """Raised when concurrent_dispatch=true but a required prerequisite is missing.

    HC-3: never silent-degrade — callers must handle explicitly.
    """


def _read_map_config_scalars(project_dir: Path) -> dict[str, str]:
    """Read top-level scalar values from .map/config.yaml without dependencies."""
    config_path = project_dir / ".map" / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            continue
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _map_config_str(project_dir: Path, key: str, default: str) -> str:
    value = _read_map_config_scalars(project_dir).get(key)
    return default if value is None else value


def _map_config_int(project_dir: Path, key: str, default: int) -> int:
    value = _read_map_config_scalars(project_dir).get(key)
    if value is None:
        return default
    try:
        parsed = int(value.replace("_", ""))
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _extract_transcript_usage(entry: dict) -> int | None:
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    entry_type = entry.get("type")
    if role != "assistant" and entry_type != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
    except (TypeError, ValueError):
        return None


def _count_last_turn_tokens(transcript_path: Path) -> int:
    if not transcript_path.is_file():
        return 0
    try:
        lines = transcript_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            usage = _extract_transcript_usage(entry)
            if usage is not None:
                return usage
    return 0


def _effective_compression_threshold(policy: str, threshold: int) -> int | None:
    if policy == "never" or threshold <= 0:
        return None
    if policy == "aggressive":
        return max(1, int(threshold * AGGRESSIVE_COMPRESSION_MULTIPLIER))
    return threshold


def _should_nudge(used: int, threshold: int | None) -> bool:
    return threshold is not None and used >= threshold


def _format_compact_instruction(used: int, threshold: int, focus: str) -> str:
    pct = round(100 * used / threshold) if threshold > 0 else 0
    focus_clean = (focus or "").strip() or (
        "MAP step state, last 2 monitor verdicts, pending subtasks; "
        "drop tool-result bodies older than 3 turns"
    )
    return (
        f"[MAP context-meter] Context is at {used:,} / {threshold:,} tokens "
        f"({pct}% of MAP threshold). Before continuing, run:\n"
        f"/compact {focus_clean}"
    )


BLOCKER_FEEDBACK_TERMS = (
    "blocker",
    "critical",
    "contract",
    "acceptance",
    "build",
    "compile",
    "syntax",
    "test failure",
    "test failed",
    "failing test",
    "type mismatch",
    "security",
    "injection",
    "secret",
    "credential",
    "data loss",
    "data-loss",
    "missing required",
    "missing test",
    "missing",
    "silent failure",
    "crash",
    "exception",
)

NON_BLOCKING_FEEDBACK_TERMS = (
    "non-blocking",
    "nonblocking",
    "nice-to-have",
    "nice to have",
    "cosmetic",
    "style",
    "elegance",
    "volume",
    "alternative abstraction",
    "extra test category",
    "extra tests",
    "documentation",
    "docs",
    "docstring",
)


def _is_blocker_feedback_line(line: str) -> bool:
    """Return True when a feedback line may justify Actor expansion."""
    lowered = line.lower()
    severity_prefixes = ("high:", "high -", "high severity", "severity: high")
    has_blocker_term = any(term in lowered for term in BLOCKER_FEEDBACK_TERMS)
    has_high_severity = lowered.strip().startswith(severity_prefixes)
    if not has_blocker_term:
        return has_high_severity
    has_non_blocking_term = any(
        term in lowered for term in NON_BLOCKING_FEEDBACK_TERMS
    )
    has_explicit_blocker = any(
        term in lowered
        for term in (
            "blocker",
            "critical",
            "security",
            "build",
            "compile",
            "contract",
            "data loss",
            "test failure",
            "test failed",
        )
    ) or has_high_severity
    return has_explicit_blocker or not has_non_blocking_term


def _filter_blocker_retry_feedback(feedback: str) -> str:
    """Forward Monitor feedback into the next Actor retry.

    Uses the keyword filter as a ranking hint only: lines matching BLOCKER terms
    are surfaced first, but the complete original text is always preserved so
    non-English or differently-phrased feedback is never silently dropped.
    """
    if not feedback.strip():
        return ""

    kept_lines = [
        line.rstrip()
        for line in feedback.splitlines()
        if line.strip() and _is_blocker_feedback_line(line)
    ]
    if kept_lines:
        return "\n".join(
            [
                "BLOCKER feedback forwarded to Actor retry:",
                *kept_lines,
                "",
                "Actor may re-add or expand code only by naming the BLOCKER item it addresses.",
                "",
                "Full Monitor feedback:",
                feedback.rstrip(),
            ]
        )

    # No BLOCKER keywords matched (may be non-English or use non-standard phrasing).
    # Forward the complete original text so the defect description is never lost.
    _header = (
        "Monitor returned valid=false. Forwarding complete feedback"
        " (keyword classification did not match — may be non-English"
        " or use non-standard phrasing):"
    )
    _footer = (
        "Re-check the contract, build/test output, security, data-loss paths,"
        " and required behavior before expanding scope. Do not add code for style,"
        " volume, docs-only, cosmetic, or nice-to-have feedback."
    )
    return f"{_header}\n\n{feedback.rstrip()}\n\n{_footer}"


def _latest_numbered_artifact(plan_dir: Path, prefix: str) -> Path | None:
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
        retry_quarantine_path = state.retry_quarantine_paths.get(str(current_subtask or ""))
        retry_isolation = state.retry_isolation_status.get(str(current_subtask or ""))
    else:
        current_phase = None
        retry_quarantine_path = None
        retry_isolation = None

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
    if retry_isolation == "clean_retry_required" and retry_quarantine_path:
        next_action.append(
            f"Resume clean retry from {retry_quarantine_path}; do not rehydrate raw failed context"
        )
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
        "retry_isolation": retry_isolation,
        "retry_quarantine_path": retry_quarantine_path,
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
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    current_subtask_id: str | None = None
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
    constraints: dict | None = None
    subtask_results: dict[str, dict] = field(default_factory=dict)
    last_subtask_commit_sha: str | None = None
    contract_ready_subtasks: dict[str, dict] = field(default_factory=dict)
    clean_retry_count: int = 0
    contaminated_retry_count: int = 0
    # Subtask IDs already nudged once for a (non-strict) scope warning. The
    # warn->actor-feedback gate (validate_step 2.4) fires at most ONCE per
    # subtask, so a persistent false positive (affected_files drift) cannot
    # burn the retry budget — after the single nudge the gate passes.
    scope_feedback_subtasks: list[str] = field(default_factory=list)
    # Subtask IDs already nudged once for a false-progress warning (MONITOR
    # approved but the subtask changed NOTHING despite declaring affected_files).
    # Same once-per-subtask bound as scope_feedback_subtasks.
    progress_feedback_subtasks: list[str] = field(default_factory=list)
    retry_isolation_status: dict[str, str] = field(default_factory=dict)
    retry_quarantine_paths: dict[str, str] = field(default_factory=dict)
    completed_at: str | None = None
    # Audit ledger for mark_subtask_complete: per-subtask
    # {kind: done|noop|deferred|stub|prior_pr, reason: str, recorded_at}
    # Added 2026-05-25 so post-run audits can tell intent apart instead
    # of squinting at synthetic "no-op" summaries.
    subtask_completion_reasons: dict[str, dict] = field(default_factory=dict)

    def record_subtask_result(
        self,
        subtask_id: str,
        files_changed: list[str],
        status: str,
        summary: str = "",
        commit_sha: str | None = None,
    ) -> None:
        """Record result of a completed subtask for context injection.

        The entry stores a redundant ``subtask_id`` field even though the
        outer key already carries it: downstream reporters / log shippers
        repeatedly want to forward entries individually and used to receive
        ``{"subtask_id": null, ...}`` because the producer never set it.
        Keeping the field self-describing closes that gap; the matching
        ``backfill_subtask_ids`` helper exists for old states.
        """
        self.subtask_results[subtask_id] = {
            "subtask_id": subtask_id,
            "files_changed": files_changed,
            "status": status,
            "summary": summary,
        }
        if commit_sha:
            self.subtask_results[subtask_id]["commit_sha"] = commit_sha
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
            "clean_retry_count": self.clean_retry_count,
            "contaminated_retry_count": self.contaminated_retry_count,
            "scope_feedback_subtasks": self.scope_feedback_subtasks,
            "progress_feedback_subtasks": self.progress_feedback_subtasks,
            "retry_isolation_status": self.retry_isolation_status,
            "retry_quarantine_paths": self.retry_quarantine_paths,
            "completed_at": self.completed_at,
            "subtask_completion_reasons": self.subtask_completion_reasons,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StepState":
        """Deserialize from dictionary."""
        return cls(
            workflow=data.get("workflow", "map-efficient"),
            started_at=data.get("started_at", datetime.now(UTC).isoformat()),
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
            clean_retry_count=data.get("clean_retry_count", 0),
            contaminated_retry_count=data.get("contaminated_retry_count", 0),
            scope_feedback_subtasks=data.get("scope_feedback_subtasks", []),
            progress_feedback_subtasks=data.get("progress_feedback_subtasks", []),
            retry_isolation_status=data.get("retry_isolation_status", {}),
            retry_quarantine_paths=data.get("retry_quarantine_paths", {}),
            completed_at=data.get("completed_at"),
            subtask_completion_reasons=data.get(
                "subtask_completion_reasons", {}
            ),
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


from map_utils import (  # pyright: ignore[reportMissingImports]
    get_branch_name,
    sanitize_branch_name,
)


def _actor_step_instruction(state: StepState) -> str:
    """Build instruction string for the ACTOR step, TDD-aware."""
    subtask = state.current_subtask_id
    isolation = state.retry_isolation_status.get(str(subtask or ""))
    quarantine_path = state.retry_quarantine_paths.get(str(subtask or ""))
    clean_retry = ""
    if isolation == "clean_retry_required" and quarantine_path:
        clean_retry = (
            f" CLEAN_RETRY mode is required: read {quarantine_path}, rebuild context "
            "only from durable artifacts named there, preserve hard constraints and "
            "acceptance tags, and do not reuse the rejected approach unless the "
            "quarantine artifact explicitly preserves it."
        )
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
        f"{context}{clean_retry}"
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
            "Include Goal, Current Phase, status for each subtask, and any "
            "deferred_yagni parking-lot items as a visible restore-or-approve section."
        ),
        "1.55": (
            "Present the generated plan to the user using a short standardized summary "
            "(goal + subtask titles + risks + any deferred_yagni omissions) and get "
            "explicit approval to proceed. If the user restores a deferred_yagni item, "
            "run `python3 .map/scripts/map_orchestrator.py restore_deferred_yagni "
            "YG-NNN` before approval. "
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
            "Persist RESEARCH findings for the subtask via "
            "`python3 .map/scripts/map_step_runner.py save_research <branch> "
            "<subtask_id>`. The artifact is MANDATORY for every non-no-op "
            "subtask (validate_step 2.2 rejects when none exists); "
            "Task(subagent_type='research-agent') is conditional for broad, "
            "high-risk, or unclear discovery. If the target file/symbol is "
            "already known, save direct current-session findings instead. "
            "Short-circuit hint: if this subtask is already done in a prior "
            "PR or is a pure no-op, skip the cycle with "
            "`python3 .map/scripts/map_orchestrator.py mark_subtask_complete "
            "<subtask_id> --reason \"...\"` instead of running research."
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


DEFERRED_FOR_DEPS_PHASE = "deferred_for_deps"
DEFERRED_NONDETERMINISTIC_STATUS = "deferred_nondeterministic"
FLAKY_TEST_TRIAGE_MONITOR_POLICY = "not_valid_without_explicit_triage"

# Single source of truth for the non-binary Monitor verdict outcomes and how
# the verdict path routes each one. Consumed by validate_step's disposition
# branch, the CLI --disposition choices, and the drift-guard test (which
# asserts the Monitor prompt names every key here). A flat constants/policy
# dict is deliberate for this bounded slice; Pydantic-driven prompt/parser
# schema generation is the principled long-term target, out of scope here.
#
# Routing contract for a deferral:
#   - Monitor MUST emit valid:false (a deferred flaky run is NOT green); the
#     "defer, don't retry" decision is a *routing* decision separate from the
#     verdict, so validate_step returns valid:false + deferred:true and the
#     state machine advances on `deferred`, never on `valid`.
#   - allowed_recommendations rejects a contradictory verdict (e.g.
#     recommendation=revise says "Actor must fix" while a defer says "don't
#     fix, it's flaky").
MONITOR_DISPOSITIONS: dict[str, dict[str, object]] = {
    DEFERRED_NONDETERMINISTIC_STATUS: {
        "requires_valid_false": True,            # Monitor must emit valid:false
        "requires_check_id": True,
        "requires_sidecar": True,
        "requires_non_empty_failed_checks": True,
        "non_green_outcome": True,
        # None (omitted) or "needs_investigation" only — revise/block contradict.
        "allowed_recommendations": (None, "needs_investigation"),
        "monitor_verdict_policy": FLAKY_TEST_TRIAGE_MONITOR_POLICY,
        "route_action": "defer_flaky_subtask",
    },
}


def _completed_subtask_ids_for_deps(state: "StepState") -> set[str]:
    """Return subtask IDs that count as "done" for dependency-resolution.

    Combines four signals (any one is sufficient):
      - subtask_results[sid] has any non-empty entry: that ID has been
        processed at least once (record_subtask_result was called on
        ACTOR/Monitor success, OR mark_subtask_complete wrote a synthetic
        no-op result). Cursor MUST treat these as done — even when
        subtask_phases didn't get updated due to case mismatch or
        legacy state. This was the root cause of the "cursor stuck on
        ST-033 stub" friction.
      - subtask_results[sid].status ∈ {valid, completed, done, skipped, no-op,
        deferred_nondeterministic}
      - subtask_phases[sid] ∈ {completed, skipped, COMPLETE, SKIPPED, no-op}
        (case-insensitive match; mark_subtask_complete writes "COMPLETE"
        in upper, validate_step writes lowercase)
      - linear-walk past: subtask at index < state.subtask_index is
        treated as done UNLESS it carries the deferred_for_deps marker
        (those were intentionally skipped and owe a revisit).
    """
    done: set[str] = set()
    DONE_RESULT_STATUSES = {
        "valid",
        "completed",
        "done",
        "skipped",
        "no-op",
        DEFERRED_NONDETERMINISTIC_STATUS,
    }
    DONE_PHASE_STATUSES = {"completed", "skipped", "no-op", "complete"}
    for sid, entry in (state.subtask_results or {}).items():
        if not isinstance(entry, dict):
            continue
        # Any recorded result (Monitor success OR mark_subtask_complete
        # no-op) is enough — entries always exist with at least
        # files_changed/status; missing-status entries also count as
        # "this id was processed" so cursor never re-visits them.
        status_value = entry.get("status")
        if not isinstance(status_value, str) or status_value.lower() in DONE_RESULT_STATUSES:
            done.add(sid)
    phases = state.subtask_phases or {}
    for sid, phase in phases.items():
        if isinstance(phase, str) and phase.lower() in DONE_PHASE_STATUSES:
            done.add(sid)
    for idx, sid in enumerate(state.subtask_sequence or []):
        if idx >= state.subtask_index:
            break
        if phases.get(sid) == DEFERRED_FOR_DEPS_PHASE:
            # Explicitly deferred — do NOT count as done; we owe a revisit.
            continue
        done.add(sid)
    return done


def _find_next_ready_subtask_index(
    state: "StepState",
    branch: str,
    *,
    start_after_index: int,
    treat_current_as_done: bool = True,
) -> tuple[int | None, list[str]]:
    """Walk subtask_sequence and return the index of the next ready subtask.

    "Ready" means: not yet completed AND every entry in its blueprint
    `dependencies` array is in the completed set.

    Walk order is forward-biased with wrap-around:
        start_after_index + 1, ..., len - 1, 0, 1, ..., start_after_index
    so dependents whose deps got satisfied LATER in the sequence (an
    edge case if the planning sort missed a forward dep) are still picked
    up on a later pass.

    Returns ``(idx, skipped)`` where ``skipped`` lists subtask IDs that
    were considered but had unmet deps in this pass — useful for
    diagnostics. Returns ``(None, blocked_ids)`` if no ready subtask
    exists. ``blocked_ids`` then represents the surviving unprocessed
    subtasks whose deps are still unmet (i.e., the workflow is stuck on
    a deadlock unless the user intervenes).

    ``treat_current_as_done=True`` (default): the just-finished current
    subtask is assumed done for dep resolution. Use False when caller is
    only inspecting and hasn't yet marked the current subtask complete.
    """
    deps_map = _load_blueprint_deps_for_runtime(branch)
    completed = _completed_subtask_ids_for_deps(state)
    if treat_current_as_done and state.current_subtask_id:
        completed.add(state.current_subtask_id)

    n = len(state.subtask_sequence)
    if n == 0:
        return None, []

    skipped_for_deps: list[str] = []
    order = list(range(start_after_index + 1, n)) + list(
        range(max(start_after_index + 1, 0))
    )
    for idx in order:
        if idx < 0 or idx >= n:
            continue
        sid = state.subtask_sequence[idx]
        if sid in completed:
            continue
        required = deps_map.get(sid, [])
        if all(dep in completed for dep in required):
            return idx, skipped_for_deps
        skipped_for_deps.append(sid)
    return None, skipped_for_deps


def _load_blueprint_deps_for_runtime(branch: str) -> dict[str, list[str]]:
    """Same shape as _load_blueprint_deps (planning side) but lives in the
    orchestrator module so runtime advance code doesn't have to import
    from set_subtasks scope (avoids a forward reference)."""
    bp_path = Path(f".map/{branch}/blueprint.json")
    if not bp_path.exists():
        return {}
    try:
        payload = json.loads(bp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    body = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    subtasks = body.get("subtasks") if isinstance(body, dict) else None
    deps: dict[str, list[str]] = {}
    if not isinstance(subtasks, list):
        return deps
    for st in subtasks:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if not isinstance(sid, str):
            continue
        raw = st.get("dependencies", [])
        if isinstance(raw, list):
            deps[sid] = [d for d in raw if isinstance(d, str)]
        else:
            deps[sid] = []
    return deps


def peek_current_step(branch: str) -> dict:
    """Return the current step descriptor WITHOUT mutating state.

    Recovery escape hatch for the case where ``validate_step X`` fails with
    ``Step mismatch: expected Y, got X`` after a double-advance: callers can
    ``peek_current_step`` to learn the canonical Y instead of guessing.
    Returns the same shape as ``get_next_step`` but never saves the state.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    if state.workflow_status == "WORKFLOW_COMPLETE":
        return {
            "step_id": "COMPLETE",
            "phase": "COMPLETE",
            "is_complete": True,
            "current_subtask": state.current_subtask_id,
        }

    if state.workflow_status == "CONTRACT_READY":
        return {
            "step_id": "CONTRACT_READY",
            "phase": "CONTRACT_READY",
            "is_complete": False,
            "current_subtask": state.current_subtask_id,
        }

    next_id = state.pending_steps[0] if state.pending_steps else state.current_step_id
    phase = STEP_PHASES.get(next_id, state.current_step_phase or "UNKNOWN")
    return {
        "step_id": next_id,
        "phase": phase,
        "is_complete": False,
        "current_subtask": state.current_subtask_id,
        "subtask_progress": f"{state.subtask_index + 1}/{max(len(state.subtask_sequence), 1)}",
    }


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

    # WORKFLOW_COMPLETE is authoritative — short-circuit even if pending_steps
    # got repopulated by a partial recovery path. Otherwise the function walks
    # the per-subtask branches and returns a stale "2.2 RESEARCH" instruction
    # for a workflow that already closed out.
    if state.workflow_status == "WORKFLOW_COMPLETE":
        return {
            "step_id": "COMPLETE",
            "phase": "COMPLETE",
            "instruction": "All subtasks complete. Run final verification.",
            "is_complete": True,
        }

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
        # Deps-aware advance: pick the next subtask whose dependencies are
        # all satisfied, skipping over subtasks whose deps are unmet (in
        # case the planning sort missed a forward dep). Backward compat:
        # only enter the dep-aware branch when there are unprocessed
        # subtasks (forward index or deferred markers); otherwise treat as
        # completion so linear-walk flows finish cleanly.
        has_forward_slot = state.subtask_index + 1 < len(state.subtask_sequence)
        has_deferred = any(
            state.subtask_phases.get(sid) == DEFERRED_FOR_DEPS_PHASE
            for sid in state.subtask_sequence
        )
        if not has_forward_slot and not has_deferred:
            return {
                "step_id": "COMPLETE",
                "phase": "COMPLETE",
                "instruction": "All subtasks complete. Run final verification.",
                "is_complete": True,
            }
        ready_idx, skipped_for_deps = _find_next_ready_subtask_index(
            state, branch, start_after_index=state.subtask_index,
            treat_current_as_done=True,
        )
        for skipped_sid in skipped_for_deps:
            state.subtask_phases[skipped_sid] = DEFERRED_FOR_DEPS_PHASE
        if ready_idx is not None:
            state.subtask_index = ready_idx
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            if state.subtask_phases.get(state.current_subtask_id) == DEFERRED_FOR_DEPS_PHASE:
                state.subtask_phases.pop(state.current_subtask_id, None)
            state.current_step_id = "2.2"
            state.current_step_phase = "RESEARCH"
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]  # Start from 2.2
            state.completed_steps = []
            state.skipped_steps = []
            state.retry_count = 0
            state.save(state_file)
        else:
            # No ready subtask. Distinguish completion from deadlock by
            # checking whether ANY subtask remains unprocessed.
            completed = _completed_subtask_ids_for_deps(state)
            if state.current_subtask_id:
                completed.add(state.current_subtask_id)
            remaining = [
                sid for sid in state.subtask_sequence if sid not in completed
            ]
            if not remaining:
                return {
                    "step_id": "COMPLETE",
                    "phase": "COMPLETE",
                    "instruction": "All subtasks complete. Run final verification.",
                    "is_complete": True,
                }
            # Deadlock: subtasks remain but every one of them has an
            # unmet dep. Surface BLOCKED_ON_DEPS so the caller doesn't
            # silently spin or report COMPLETE prematurely.
            state.current_step_id = "BLOCKED_ON_DEPS"
            state.current_step_phase = "BLOCKED_ON_DEPS"
            state.save(state_file)
            return {
                "step_id": "BLOCKED_ON_DEPS",
                "phase": "BLOCKED_ON_DEPS",
                "instruction": (
                    "No subtask can run: every remaining subtask has an "
                    "unmet dependency. Inspect blueprint deps + "
                    "subtask_results, then either record missing results "
                    "or fix the dep graph."
                ),
                "is_complete": False,
                "blocked_subtasks": remaining,
                "skipped_for_deps": skipped_for_deps,
            }

    # Get next pending step
    next_step_id = state.pending_steps[0]

    # Defensive RESEARCH-skip warning (added 2026-05-27): if get_next_step
    # is about to return 2.3 (ACTOR) for the current subtask but 2.2
    # (RESEARCH) was never completed for it AND no research artifact
    # exists on disk AND TDD pre-phases (2.25/2.26) weren't the path
    # by which 2.2 got skipped, emit a soft warning. Catches the silent
    # skip without breaking the documented TDD auto-skip path (which
    # legitimately bypasses 2.2 in the auto_skip_tdd_phases test).
    research_skip_warning: str | None = None
    if (
        next_step_id == "2.3"
        and "2.2" not in state.completed_steps
        and "2.2" not in state.skipped_steps
        and "2.25" not in state.skipped_steps
        and "2.26" not in state.skipped_steps
        and state.current_subtask_id
    ):
        research_dir = Path(f".map/{branch}/research")
        artifact_present = research_dir.is_dir() and any(
            research_dir.glob(f"{state.current_subtask_id}__*.md")
        )
        if not artifact_present:
            research_skip_warning = (
                f"WARNING: about to return ACTOR (2.3) for "
                f"{state.current_subtask_id} but RESEARCH (2.2) is not in "
                "completed_steps AND no research artifact exists at "
                f".map/{branch}/research/{state.current_subtask_id}__*.md. "
                "Likely a state-drift skip. Run save_research + "
                "validate_step 2.2 before ACTOR, or document this as an "
                "intentional research-skip in the subtask description."
            )

    phase = STEP_PHASES.get(next_step_id, "UNKNOWN")
    instruction = get_step_instruction(next_step_id, state)

    # Update current step in state
    state.current_step_id = next_step_id
    state.current_step_phase = phase
    state.save(state_file)

    response: dict[str, object] = {
        "step_id": next_step_id,
        "phase": phase,
        "instruction": instruction,
        "is_complete": False,
        "current_subtask": state.current_subtask_id,
        "subtask_progress": f"{state.subtask_index + 1}/{len(state.subtask_sequence)}",
    }
    if research_skip_warning:
        response["warning"] = research_skip_warning
    return response


REJECT_RECOMMENDATIONS = {"revise", "block", "needs_investigation"}
_MONITOR_REQUIRED_KEYS = ("valid", "summary", "issues")


def _parse_monitor_envelope_json(
    monitor_text: str,
) -> tuple[dict | None, str | None]:
    """Parse a Monitor JSON envelope, with fenced ```json {...}``` recovery.

    Returns ``(parsed_dict, None)`` on success or ``(None, error_message)`` on
    failure. Shared by ``_validate_monitor_envelope`` (the structural 2.4 gate)
    and ``_validate_monitor_disposition_binding`` (the anti-gaming defer gate)
    so both see identical parse semantics — one parser, no drift.
    """
    if not monitor_text or not monitor_text.strip():
        return None, "Monitor envelope is empty (prose-only response or truncation)"
    stripped = monitor_text.strip()
    if not stripped.endswith(("}", "]")):
        return None, (
            "Monitor response ends mid-sentence (no closing `}`/`]`) — "
            "likely truncated; re-prompt with 'emit ONLY the JSON object'"
        )
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        # Try fenced ```json {...} ``` recovery before giving up.
        import re as _re
        match = _re.search(r"\{(?:.|\n)*\}", stripped)
        if not match:
            return None, f"Monitor response does not parse as JSON: {exc}"
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, f"Monitor response does not parse as JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "Monitor response parsed but is not an object"
    return parsed, None


def _validate_monitor_envelope(monitor_text: str) -> str | None:
    """Return None when monitor_text is a complete Monitor JSON envelope.

    Returns an error message string when the envelope is broken — used
    by validate_step 2.4 to reject prose-instead-of-JSON Monitor
    responses orchestrator-side instead of relying on the operator to
    eyeball it. Three failure modes match the skill's documented gate:
    (a) doesn't parse as JSON, (b) missing required keys, (c) ends
    mid-sentence (no closing `}`).
    """
    parsed, error = _parse_monitor_envelope_json(monitor_text)
    if parsed is None:
        return error
    missing = [k for k in _MONITOR_REQUIRED_KEYS if k not in parsed]
    if missing:
        return (
            f"Monitor JSON missing required keys {missing!r} — likely "
            "truncated; re-prompt for complete envelope"
        )
    return None


def _validate_monitor_disposition_binding(
    monitor_text: str, kind: str, check_id: str
) -> str | None:
    """Verify a Monitor envelope structurally authorizes a deferral verdict.

    Anti-gaming gate for validate_step's disposition path: a deferral is the
    THIRD Monitor outcome (not a pass, not Actor-retry), so the verdict must
    come from Monitor's own structured output, never a bare caller claim.
    Returns None when the envelope authorizes the deferral, else an error.

    On `check_id` vs `failed_checks`: the Monitor schema's ``failed_checks`` is
    the list of failed quality *dimensions* (correctness, testability, …) — a
    different namespace from a flaky test/check id — so the binding cannot be
    "check_id in failed_checks". Instead it requires (a) Monitor admits the run
    is non-green (``valid:false``) AND at least one dimension failed
    (``failed_checks`` non-empty), and (b) Monitor's own structured
    ``disposition`` names the same kind + check_id the caller is deferring. The
    deterministic-vs-flaky defense lives in the sidecar (mixed pass/fail
    evidence), which ``defer_flaky_subtask`` re-validates from disk.
    """
    parsed, error = _parse_monitor_envelope_json(monitor_text)
    if parsed is None:
        return error
    if parsed.get("valid") is not False:
        return (
            "deferral requires Monitor valid:false (a deferred flaky run is not "
            f"a clean pass); envelope has valid={parsed.get('valid')!r}"
        )
    failed_checks = parsed.get("failed_checks")
    if not isinstance(failed_checks, list) or not failed_checks:
        return (
            "deferral requires a non-empty failed_checks list — Monitor must "
            "admit a real dimension failure, not defer a green review"
        )
    disposition = parsed.get("disposition")
    if not isinstance(disposition, dict):
        return (
            "Monitor envelope has no structured `disposition` object; the "
            "deferral verdict must come from Monitor, not the caller"
        )
    env_kind = str(disposition.get("kind") or "").strip().lower()
    if env_kind != kind:
        return (
            f"Monitor disposition.kind={env_kind!r} does not match the "
            f"requested --disposition {kind!r}"
        )
    env_check = str(disposition.get("check_id") or "").strip()
    if env_check != check_id.strip():
        return (
            f"Monitor disposition.check_id={env_check!r} does not match the "
            f"requested --check-id {check_id.strip()!r}"
        )
    return None


def validate_step(
    step_id: str,
    branch: str,
    *,
    recommendation: str | None = None,
    monitor_envelope: str | None = None,
    disposition: str | None = None,
    check_id: str | None = None,
    files_changed: list[str] | None = None,
    summary: str = "",
    commit_sha: str | None = None,
) -> dict:
    """
    Validate step completion and update state.

    Args:
        step_id: Step identifier to validate
        branch: Git branch name (sanitized)
        recommendation: For step_id="2.4" (Monitor close), REQUIRED
            Monitor verdict field — omitting it returns valid=false
            (recommendation_required) rather than closing the phase. When
            set to ``revise``, ``block``, or ``needs_investigation``,
            validate_step refuses to close the phase and returns valid=false
            — so the recommendation contract (skill rule: "valid=true +
            recommendation∈{revise, block, needs_investigation} = fail") is
            enforced orchestrator-side, not just by-convention.

    Returns:
        Dict with valid: bool, message: str
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    # Idempotency: validating a step already in completed_steps is a no-op
    # success. Re-running validate_step after a double-advance no longer
    # explodes with "Step mismatch: expected Y, got X" — callers can safely
    # retry without first calling peek_current_step.
    if step_id in state.completed_steps and state.current_step_id != step_id:
        return {
            "valid": True,
            "message": f"Step {step_id} already completed (idempotent no-op)",
            "next_step": state.current_step_id,
            "idempotent": True,
        }

    # Transactional MONITOR pass: validate_step("2.4") implicitly closes
    # 2.3 (ACTOR) if it's still pending. Caller convenience — Monitor
    # approval logically means Actor work was accepted, so requiring a
    # separate validate_step("2.3") before validate_step("2.4") is just
    # ceremony that produces "Step mismatch: expected 2.3" errors.
    if (
        step_id == "2.4"
        and state.current_step_id == "2.3"
        and "2.3" in state.pending_steps
    ):
        state.completed_steps.append("2.3")
        state.pending_steps.remove("2.3")
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"

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
    # INIT_STATE invariant (issue #386): when a non-empty valid blueprint exists
    # but subtask_sequence is empty, auto-populate from blueprint.json (or task
    # plan markdown fallback) before closing the step. Return valid=false only
    # when no subtask IDs can be derived from any artifact.
    if step_id == "1.6" and not state.subtask_sequence:
        plan_dir = Path(f".map/{branch}")
        blueprint_file = plan_dir / "blueprint.json"
        plan_file = plan_dir / f"task_plan_{branch}.md"
        plan_content = plan_file.read_text(encoding="utf-8") if plan_file.exists() else ""
        subtask_ids = _extract_subtask_ids_from_plan_artifacts(plan_content, blueprint_file)
        if not subtask_ids:
            return {
                "valid": False,
                "message": (
                    "INIT_STATE (step 1.6) requires a non-empty subtask_sequence. "
                    "No subtask IDs found in blueprint.json or task plan. "
                    "Run: python3 .map/scripts/map_orchestrator.py resume_from_plan"
                ),
                "hint": "resume_from_plan",
            }
        # Apply topological sort to respect declared dependencies.
        deps_map = _load_blueprint_deps(branch)
        if deps_map:
            sorted_ids, _cycle = _topological_sort_subtasks(subtask_ids, deps_map)
            if sorted_ids is not None:
                subtask_ids = sorted_ids
        state.subtask_sequence = subtask_ids
        state.current_subtask_id = subtask_ids[0]
        state.subtask_index = 0
    # Monitor envelope check: when --monitor-envelope is supplied,
    # reject 2.4 close if the envelope text is truncated / not JSON /
    # missing required keys. Moves the prose-response gate from skill
    # guidance to structural enforcement so a forgetful operator can't
    # close on a truncated Monitor output.
    if step_id == "2.4" and monitor_envelope is not None:
        envelope_error = _validate_monitor_envelope(monitor_envelope)
        if envelope_error:
            return {
                "valid": False,
                "message": (
                    f"Monitor envelope validation failed: {envelope_error}. "
                    "Re-invoke Monitor with 'retry and emit ONLY the JSON "
                    "object'; if it stays truncated, stop with "
                    "CLARIFICATION_NEEDED — do NOT close 2.4 on a "
                    "prose-only response."
                ),
                "envelope_error": envelope_error,
            }

    # Non-binary disposition route — the THIRD Monitor outcome. When Monitor
    # confirms a check is flaky/nondeterministic (not a deterministic
    # regression), it emits a structured `disposition` and the caller pipes it
    # here via --disposition/--check-id. We route to the existing
    # defer_flaky_subtask (the single owner of the close+advance transaction),
    # which re-validates the sidecar from disk. This branch sits BEFORE the
    # recommendation gates so a defer carrying recommendation=needs_investigation
    # routes to deferral instead of a hard-stop. Anti-gaming: the deferral is
    # honored ONLY when the Monitor envelope structurally backs it (valid:false,
    # non-empty failed_checks, matching disposition) AND the sidecar holds mixed
    # pass/fail evidence — a Monitor cannot dodge a real deterministic failure
    # by merely claiming "flaky". A deferred run is NOT green: this returns
    # valid:false + deferred:true; the state machine routes on `deferred`.
    if step_id == "2.4" and disposition:
        norm_disposition = disposition.strip().lower()
        policy = MONITOR_DISPOSITIONS.get(norm_disposition)
        if policy is None:
            return {
                "valid": False,
                "message": (
                    f"Unknown Monitor disposition {norm_disposition!r}. "
                    f"Supported: {sorted(MONITOR_DISPOSITIONS)}."
                ),
            }
        if policy.get("requires_check_id") and not (check_id and check_id.strip()):
            return {
                "valid": False,
                "message": (
                    f"disposition {norm_disposition!r} requires --check-id "
                    "(the flaky check id matching the triage sidecar)."
                ),
            }
        # Contradiction guard: a defer verdict must not also tell the Actor to
        # fix. recommendation may be omitted or needs_investigation only.
        allowed_recs = policy.get("allowed_recommendations", (None,))
        norm_rec = recommendation.strip().lower() if recommendation else None
        if not isinstance(allowed_recs, (tuple, list)) or norm_rec not in allowed_recs:
            return {
                "valid": False,
                "message": (
                    f"Contradictory verdict: recommendation={norm_rec!r} with "
                    f"disposition={norm_disposition!r}. A deferral must not also "
                    "request an Actor fix — use recommendation=needs_investigation "
                    "or omit it."
                ),
            }
        # The deferral verdict must come from Monitor's structured output, not a
        # bare caller claim — require and verify the full envelope.
        if monitor_envelope is None:
            return {
                "valid": False,
                "message": (
                    "disposition route requires --monitor-envelope so the "
                    "deferral verdict can be verified against Monitor's "
                    "structured output (valid:false, non-empty failed_checks, "
                    "matching disposition)."
                ),
            }
        binding_error = _validate_monitor_disposition_binding(
            monitor_envelope, norm_disposition, check_id or ""
        )
        if binding_error:
            return {
                "valid": False,
                "message": f"Monitor disposition binding failed: {binding_error}",
            }
        # Delegate to defer_flaky_subtask: it re-validates the sidecar (check_id
        # match + mixed pass/fail evidence + branch), records the non-green
        # outcome, and closes 2.3+2.4 + advances. It is the single writer of
        # this transition; validate_step's in-memory transactional 2.3->2.4
        # close above is intentionally NOT persisted on this path.
        if policy.get("route_action") == "defer_flaky_subtask":
            defer_result = defer_flaky_subtask(
                state.current_subtask_id or "",
                branch,
                check_id or "",
                files_changed=files_changed,
                summary=summary,
                commit_sha=commit_sha,
            )
            if defer_result.get("status") != "success":
                detail = defer_result.get("message", "deferral failed")
                return {
                    "valid": False,
                    "message": f"Flaky deferral rejected: {detail}",
                    "deferral": defer_result,
                }
            return {
                "valid": False,
                "deferred": True,
                "non_green_outcome": True,
                "disposition": norm_disposition,
                "subtask_id": defer_result.get("subtask_id"),
                "next_step": defer_result.get("next_step"),
                "subtask_advanced_from": defer_result.get("subtask_advanced_from"),
                "subtask_advanced_to": defer_result.get("subtask_advanced_to"),
                "triage_path": defer_result.get("triage_path"),
                "message": (
                    f"Subtask {defer_result.get('subtask_id')} deferred "
                    f"(disposition={norm_disposition}, check_id={check_id}). "
                    "Non-green outcome recorded; workflow advanced."
                ),
                "deferral": defer_result,
            }

    # Recommendation-required gate: closing 2.4 without --recommendation
    # makes the verdict-consistency enforcement impossible. Hard-fail so
    # the operator is forced to pipe Monitor's recommendation through.
    if step_id == "2.4" and not recommendation:
        return {
            "valid": False,
            "message": (
                "validate_step 2.4 requires --recommendation (Monitor's "
                "verdict). Without it the verdict-consistency gate cannot "
                "enforce 'valid=true + recommendation in {revise,block,"
                "needs_investigation} = fail'. Re-run: validate_step 2.4 "
                "--recommendation \"$MONITOR_RECOMMENDATION\"."
            ),
            "recommendation_required": True,
        }

    # Monitor recommendation enforcement: when closing 2.4 (MONITOR) and
    # the caller passed a recommendation, refuse to close on revise /
    # block / needs_investigation. The skill rule was prose-only ("valid
    # +recommendation∈{revise,block,needs_investigation} = fail"); this
    # makes it a structural gate so the contract can't be bypassed by
    # forgetting to read the recommendation field.
    if step_id == "2.4" and recommendation:
        normalized_rec = recommendation.strip().lower()
        if normalized_rec in REJECT_RECOMMENDATIONS:
            return {
                "valid": False,
                "message": (
                    f"Monitor recommendation={normalized_rec!r} rejects "
                    "this subtask. Address the issue, re-run Actor, then "
                    "re-invoke Monitor. (Do NOT call validate_step 2.4 "
                    "until Monitor returns proceed/approve.)"
                ),
                "recommendation": normalized_rec,
            }
    # RESEARCH (2.2) requires a persisted artifact for every non-no-op subtask.
    # The artifact can come from research-agent or direct current-session
    # findings; enforce the machine-checkable contract before Actor proceeds.
    # Without this check, "MANDATORY" was prompt-text only and malformed
    # markdown could be silently passed downstream.
    if step_id == "2.2" and state.current_subtask_id:
        try:
            from map_step_runner import (  # pyright: ignore[reportMissingImports]
                validate_research,
            )
            research_report = validate_research(branch, state.current_subtask_id)
        except ImportError:
            research_report = {
                "valid": False,
                "errors": ["map_step_runner.validate_research could not be imported"],
            }
        if not research_report.get("valid"):
            research_errors = research_report.get("errors")
            if isinstance(research_errors, list) and research_errors:
                detail = "; ".join(str(err) for err in research_errors[:3])
            else:
                detail = "research artifact is missing or invalid"
            return {
                "valid": False,
                "message": (
                    f"RESEARCH artifact invalid for {state.current_subtask_id}: "
                    f"{detail}. "
                    "Use research-agent for broad/high-risk/unclear discovery, "
                    "or save direct current-session findings when the target is known. "
                    f"Run: python3 .map/scripts/map_step_runner.py save_research "
                    f"<branch> {state.current_subtask_id} (defaults kind=actor), "
                    "then validate_research before validate_step 2.2. If this "
                    "subtask needs no Actor/Monitor, use mark_subtask_complete "
                    "--reason instead."
                ),
                "research_report": research_report,
            }
        # Auto-snapshot per-subtask baseline at RESEARCH-complete so the
        # MONITOR-side validate_mutation_boundary check only flags files
        # CHANGED during this subtask, not the cumulative branch diff.
        try:
            from map_step_runner import (  # pyright: ignore[reportMissingImports]
                record_subtask_baseline,
            )
            record_subtask_baseline(branch, state.current_subtask_id)
        except ImportError:
            pass
    # MONITOR gate auto-runs validate_mutation_boundary so scope leaks can't
    # silently slip past. The check is warn-only by default; only
    # MAP_STRICT_SCOPE=1 escalates a "violation" to a hard reject. Best-effort:
    # if blueprint or git aren't available (e.g., unit tests that exercise
    # just the orchestrator), skip silently rather than block the gate.
    _scope_warning_meta: dict | None = None
    if step_id == "2.4" and state.current_subtask_id:
        blueprint_present = Path(f".map/{branch}/blueprint.json").exists()
        if blueprint_present:
            try:
                from map_step_runner import (  # pyright: ignore[reportMissingImports]
                    validate_mutation_boundary,
                )
                scope_report = validate_mutation_boundary(
                    branch, state.current_subtask_id
                )
                scope_status = scope_report.get("status")
                # "error" (git failure, unknown subtask) is non-blocking by
                # default — strict mode still treats violation as a hard
                # reject.
                if scope_status == "violation" and scope_report.get("strict"):
                    return {
                        "valid": False,
                        "message": (
                            "Mutation-boundary violation in MAP_STRICT_SCOPE mode. "
                            f"Unexpected files: {scope_report.get('unexpected', [])}"
                        ),
                    }
                # warn->actor-feedback: a non-strict scope leak does NOT hard-fail
                # the subtask, but the FIRST time it is seen we route it back to
                # the Actor as feedback so it self-corrects (revert the
                # out-of-scope edits, or escalate for a contract update). Bounded
                # to once per subtask (scope_feedback_subtasks guard) so a
                # persistent false positive (affected_files drift) cannot burn the
                # retry budget — after the single nudge the gate passes.
                if (
                    scope_status == "warning"
                    and state.current_subtask_id not in state.scope_feedback_subtasks
                ):
                    state.scope_feedback_subtasks.append(state.current_subtask_id)
                    state.save(state_file)
                    unexpected = scope_report.get("unexpected", [])
                    hint = scope_report.get("diagnostic_hint", "")
                    _scope_warning_meta = {
                        "unexpected": unexpected,
                        "subtask_id": state.current_subtask_id,
                        **({"hint": hint} if hint else {}),
                    }
                    # Advisory-only: do NOT block the gate. The warning is surfaced
                    # as scope_warning metadata in the success response so callers
                    # can log or display it without a double-call being required.
                # false-progress (correctness): MONITOR is approving, but the
                # subtask changed NOTHING despite declaring affected_files. Same
                # warn->actor-feedback trick (once per subtask via
                # progress_feedback_subtasks): nudge the Actor to implement the
                # change or report a blocker, rather than silently closing a
                # subtask that did nothing.
                _st_result = state.subtask_results.get(state.current_subtask_id) or {}
                _has_recorded_commit = bool(
                    isinstance(_st_result, dict) and _st_result.get("commit_sha")
                )
                if (
                    scope_status != "error"
                    and scope_report.get("expected")
                    and not scope_report.get("actual")
                    and not _has_recorded_commit
                    and state.current_subtask_id not in state.progress_feedback_subtasks
                ):
                    state.progress_feedback_subtasks.append(state.current_subtask_id)
                    state.save(state_file)
                    return {
                        "valid": False,
                        "message": (
                            "False-progress (mutation-boundary): MONITOR is closing "
                            f"{state.current_subtask_id} but NO files changed, though "
                            "its contract declares affected_files="
                            f"{scope_report.get('expected')}. Implement the change "
                            "with Edit/Write; OR if it is already satisfied or not "
                            "needed, STOP and report a blocker for a contract update "
                            "— do not close a subtask that did nothing."
                        ),
                    }
            except ImportError:
                pass
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
    advanced_from_subtask: str | None = None
    advanced_to_subtask: str | None = None
    blocked_remaining: list[str] = []
    skipped_for_deps: list[str] = []
    if state.pending_steps:
        next_id = state.pending_steps[0]
        state.current_step_id = next_id
        state.current_step_phase = STEP_PHASES.get(next_id, "UNKNOWN")
        next_step_signal = state.current_step_id
    elif state.subtask_index + 1 < len(state.subtask_sequence) or any(
        state.subtask_phases.get(sid) == DEFERRED_FOR_DEPS_PHASE
        for sid in state.subtask_sequence
    ):
        # Inter-subtask boundary: deps-aware atomic advance. Use the
        # runtime safety net to find the next subtask whose dependencies
        # are all satisfied — skips over forward-dep violations that
        # slipped past the planning gate, and wraps around to pick up
        # earlier subtasks marked deferred_for_deps once their deps clear.
        ready_idx, skipped_for_deps = _find_next_ready_subtask_index(
            state, branch, start_after_index=state.subtask_index,
            treat_current_as_done=True,
        )
        # Persist the deferral marker on every subtask we skipped over —
        # so the next advance can find them on wrap-around once their
        # deps land. Without this, _completed_subtask_ids_for_deps would
        # treat them as already-done (linear-walk past).
        for skipped_sid in skipped_for_deps:
            state.subtask_phases[skipped_sid] = DEFERRED_FOR_DEPS_PHASE
        if ready_idx is not None:
            advanced_from_subtask = state.current_subtask_id
            state.subtask_index = ready_idx
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            advanced_to_subtask = state.current_subtask_id
            # The chosen subtask is no longer deferred — it's now active.
            if state.subtask_phases.get(state.current_subtask_id) == DEFERRED_FOR_DEPS_PHASE:
                state.subtask_phases.pop(state.current_subtask_id, None)
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]
            state.completed_steps = []
            state.skipped_steps = []
            state.retry_count = 0
            state.current_step_id = state.pending_steps[0]
            state.current_step_phase = STEP_PHASES.get(
                state.current_step_id, "RESEARCH"
            )
            next_step_signal = state.current_step_id
        else:
            # All remaining subtasks blocked on unmet deps. Distinguish
            # from "all done" by checking what's still unprocessed.
            completed = _completed_subtask_ids_for_deps(state)
            if state.current_subtask_id:
                completed.add(state.current_subtask_id)
            blocked_remaining = [
                sid for sid in state.subtask_sequence if sid not in completed
            ]
            if not blocked_remaining:
                # Atomic terminal transition: set workflow_status + completed_at
                # together with the phase, the same invariant that
                # mark_workflow_complete / mark_subtask_complete enforce. Omitting
                # them left sequential runs at workflow_status=IN_PROGRESS while
                # phase=COMPLETE, silently disabling every WORKFLOW_COMPLETE-gated
                # hook (scrub-internal-ids, teardown/archival) for the most common
                # completion path.
                state.current_step_id = "COMPLETE"
                state.current_step_phase = "COMPLETE"
                state.workflow_status = "WORKFLOW_COMPLETE"
                state.completed_at = _utc_timestamp()
                next_step_signal = "COMPLETE"
            else:
                state.current_step_id = "BLOCKED_ON_DEPS"
                state.current_step_phase = "BLOCKED_ON_DEPS"
                next_step_signal = "BLOCKED_ON_DEPS"
    else:
        # Atomic terminal transition (see the blocked_remaining branch above):
        # workflow_status + completed_at must land together with phase=COMPLETE.
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.completed_at = _utc_timestamp()
        next_step_signal = "COMPLETE"

    # Save updated state
    state.save(state_file)

    response: dict = {
        "valid": True,
        "message": f"Step {step_id} completed successfully",
        "next_step": next_step_signal,
    }
    if advanced_to_subtask is not None:
        response["subtask_advanced_from"] = advanced_from_subtask
        response["subtask_advanced_to"] = advanced_to_subtask
    if skipped_for_deps:
        response["skipped_for_deps"] = skipped_for_deps
    if next_step_signal == "BLOCKED_ON_DEPS":
        response["blocked_subtasks"] = blocked_remaining
    if _scope_warning_meta is not None:
        response["scope_warning"] = _scope_warning_meta
    return response


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

    # Auto-archive a previously COMPLETED workflow on this branch so a reused
    # branch starts clean (see archive_completed_workflow). Only a terminal
    # workflow is retired here — an in-flight run is never clobbered; that
    # stays an explicit operator decision.
    archived_prior = None
    if state_file.exists():
        prior = StepState.load(state_file)
        if _is_workflow_complete(prior):
            archive_result = archive_completed_workflow(branch)
            if archive_result.get("status") == "archived":
                archived_prior = archive_result.get("archive_file")

    # Create fresh state
    state = StepState()
    state.save(state_file)

    result = {
        "status": "initialized",
        "state_file": str(state_file),
        "task": task,
        "branch": branch,
    }
    if archived_prior:
        result["archived_prior"] = archived_prior
    return result


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


def _blueprint_body(payload: dict) -> dict:
    """Return the mutable blueprint body for wrapped or plain payloads."""
    body = payload.get("blueprint")
    return body if isinstance(body, dict) else payload


def _next_restored_subtask_id(subtasks: list[object]) -> str:
    max_seen = 0
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        subtask_id = subtask.get("id")
        if not isinstance(subtask_id, str):
            continue
        match = re.fullmatch(r"ST-(\d{3,})", subtask_id)
        if match:
            max_seen = max(max_seen, int(match.group(1)))
    return f"ST-{max_seen + 1:03d}"


def _restored_subtask_from_deferred(item: dict, subtask_id: str) -> dict:
    title = str(item.get("title") or "Restored deferred YAGNI item").strip()
    rationale = str(item.get("rationale") or "No rationale recorded").strip()
    restore_hint = str(item.get("restore_hint") or "No restore hint recorded").strip()
    item_id = str(item.get("id") or "YG-???").strip()
    return {
        "id": subtask_id,
        "title": title,
        "description": (
            f"Restored from deferred_yagni {item_id}. Original rationale: "
            f"{rationale}. Restore hint: {restore_hint}"
        ),
        "dependencies": [],
        "affected_files": [],
        "requiredness": "optional",
        "pruneable": False,
        "prune_rationale": (
            "Restored after user request; keep active unless the user explicitly "
            "moves it back to deferred_yagni."
        ),
        "validation_criteria": [
            f"VC1: Implement or re-plan restored scope from {item_id}: {restore_hint}"
        ],
        "aag_contract": (
            f"Actor -> Restore deferred scope {item_id} using the recorded hint -> "
            f"{title} is implemented or explicitly re-planned with user approval"
        ),
        "expected_diff_size": "small",
        "concern_type": "runtime",
        "one_logical_step": True,
        "restored_from_deferred_yagni": item_id,
    }


def _append_restored_subtask_to_plan(
    plan_file: Path, subtask: dict, item: dict
) -> bool:
    if not plan_file.exists():
        return False
    content = plan_file.read_text(encoding="utf-8")
    subtask_id = str(subtask.get("id"))
    if re.search(rf"^###\s+{re.escape(subtask_id)}\b", content, re.MULTILINE):
        return False
    item_id = str(item.get("id") or "YG-???")
    title = str(subtask.get("title") or "Restored deferred YAGNI item")
    rationale = str(item.get("rationale") or "No rationale recorded")
    restore_hint = str(item.get("restore_hint") or "No restore hint recorded")
    addition = (
        "\n\n## Restored Deferred YAGNI\n\n"
        f"### {subtask_id}: {title}\n"
        "- **Status:** pending\n"
        f"- **Restored from:** {item_id}\n"
        "- **Requiredness:** optional\n"
        f"- **Rationale:** {rationale}\n"
        f"- **Restore hint:** {restore_hint}\n"
        "- **Validation:** Implement this restored scope or re-plan it before "
        "approving execution.\n"
    )
    plan_file.write_text(content.rstrip() + addition, encoding="utf-8")
    return True


def restore_deferred_yagni(
    item_id: str, branch: str, new_subtask_id: str | None = None
) -> dict:
    """Move one deferred_yagni item into active subtasks before plan approval."""
    normalized_item_id = (item_id or "").strip()
    if not re.fullmatch(r"YG-\d{3,}", normalized_item_id):
        return {
            "status": "error",
            "message": f"deferred_yagni id must match YG-NNN: {item_id}",
        }

    plan_dir = Path(f".map/{branch}")
    blueprint_path = plan_dir / "blueprint.json"
    if not blueprint_path.exists():
        return {
            "status": "error",
            "message": f"blueprint.json not found at {blueprint_path}",
        }

    try:
        payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "message": f"cannot read blueprint.json: {exc}",
        }
    if not isinstance(payload, dict):
        return {"status": "error", "message": "blueprint.json must contain an object"}

    body = _blueprint_body(payload)
    subtasks = body.get("subtasks")
    deferred_yagni = body.get("deferred_yagni")
    if not isinstance(subtasks, list):
        return {"status": "error", "message": "blueprint.subtasks must be an array"}
    if not isinstance(deferred_yagni, list):
        return {
            "status": "error",
            "message": "blueprint.deferred_yagni must be an array",
        }

    match_index = None
    match_item: dict | None = None
    for index, candidate in enumerate(deferred_yagni):
        if isinstance(candidate, dict) and candidate.get("id") == normalized_item_id:
            match_index = index
            match_item = candidate
            break
    if match_item is None or match_index is None:
        return {
            "status": "error",
            "message": f"{normalized_item_id} not found in deferred_yagni",
        }

    existing_ids = {
        subtask.get("id")
        for subtask in subtasks
        if isinstance(subtask, dict) and isinstance(subtask.get("id"), str)
    }
    subtask_id = new_subtask_id or _next_restored_subtask_id(subtasks)
    if not re.fullmatch(r"ST-\d{3,}", subtask_id):
        return {
            "status": "error",
            "message": f"restored subtask id must match ST-NNN: {subtask_id}",
        }
    if subtask_id in existing_ids:
        return {
            "status": "error",
            "message": f"restored subtask id already exists: {subtask_id}",
        }

    restored_subtask = _restored_subtask_from_deferred(match_item, subtask_id)
    del deferred_yagni[match_index]
    subtasks.append(restored_subtask)

    tmp_path = blueprint_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(blueprint_path)

    plan_file = plan_dir / f"task_plan_{branch}.md"
    task_plan_updated = _append_restored_subtask_to_plan(
        plan_file, restored_subtask, match_item
    )

    state_file = plan_dir / "step_state.json"
    plan_approved_reset = False
    if state_file.exists():
        state = StepState.load(state_file)
        if state.plan_approved:
            plan_approved_reset = True
        state.plan_approved = False
        state.save(state_file)

    return {
        "status": "success",
        "restored_item_id": normalized_item_id,
        "subtask_id": subtask_id,
        "blueprint_path": str(blueprint_path),
        "task_plan_updated": task_plan_updated,
        "plan_approved_reset": plan_approved_reset,
        "message": (
            f"Restored {normalized_item_id} as {subtask_id}. Review the updated "
            "plan and run set_plan_approved true only after the user approves it."
        ),
    }


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
                    if s in tdd_steps and s not in done_and_skipped and i < pos and (earliest_tdd is None or i < earliest_tdd):
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


def set_waves(branch: str, blueprint_path: str | None = None) -> dict:
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
        # importable from sys.path.  Try in order:
        #   1. Source-checkout layout: src/mapify_cli/ relative to this file or cwd.
        #   2. Installed-package layout: uv tool install / pipx venv locations
        #      (~/.local/share/uv/tools/mapify-cli/... or
        #       ~/.local/pipx/venvs/mapify-cli/...).
        import importlib.util

        dg_candidates: list[Path] = [Path("src/mapify_cli/dependency_graph.py")]
        for parent in Path(__file__).resolve().parents:
            dg_candidates.append(parent / "src" / "mapify_cli" / "dependency_graph.py")

        # Common installed-package locations (uv tool install, pipx install).
        _home = Path.home()
        for _tool_dir in [
            _home / ".local" / "share" / "uv" / "tools" / "mapify-cli",
            _home / ".local" / "pipx" / "venvs" / "mapify-cli",
        ]:
            if _tool_dir.exists():
                for _py_dir in sorted(_tool_dir.glob("lib/python3.*"), reverse=True)[:1]:
                    dg_candidates.append(
                        _py_dir / "site-packages" / "mapify_cli" / "dependency_graph.py"
                    )

        loaded = False
        for candidate in dg_candidates:
            if candidate.exists():
                spec = importlib.util.spec_from_file_location(
                    "dependency_graph", candidate
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    DependencyGraph = mod.DependencyGraph  # type: ignore[misc]
                    SubtaskNode = mod.SubtaskNode  # type: ignore[misc]
                    loaded = True
                    break
        if not loaded:
            return {
                "status": "error",
                "message": (
                    "Cannot import dependency_graph module. "
                    "If mapify-cli was installed via 'uv tool install', invoke this "
                    "script with the uv-tool Python interpreter directly: "
                    "~/.local/share/uv/tools/mapify-cli/bin/python3 "
                    ".map/scripts/map_orchestrator.py ..."
                ),
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

    # Build graph. The DependencyGraph / SubtaskNode symbols are bound either
    # by the top-level `from mapify_cli.dependency_graph import ...` in the try
    # block above OR by the importlib-spec fallback in the except block. Pyright
    # cannot follow the dynamic spec path so the names look possibly-unbound;
    # the except branch returns early when neither import succeeds.
    graph = DependencyGraph()  # pyright: ignore[reportPossiblyUnboundVariable]
    affected_files_map: dict[str, set] = {}
    for st in subtasks:
        st_id = st.get("id", "")
        deps = st.get("dependencies", [])
        graph.add_node(SubtaskNode(id=st_id, dependencies=deps))  # pyright: ignore[reportPossiblyUnboundVariable]
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
    # Populate subtask_sequence from flattened wave order when empty, ensuring
    # sequential execution state is consistent with the computed wave plan (#386).
    if not state.subtask_sequence:
        flat_seq = [sid for wave in final_waves for sid in wave]
        if flat_seq:
            state.subtask_sequence = flat_seq
            state.current_subtask_id = flat_seq[0]
            state.subtask_index = 0
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

    # Compute structured dispatch signal via config-driven gate (ST-001, Slice 5b).
    # compute_dispatch_gate short-circuits to sequential on the first line when
    # concurrent_dispatch=false (default), touching no new code/probe/import (HC-1).
    gate = compute_dispatch_gate(branch, Path("."))
    dispatch_mode = gate["dispatch_mode"]
    dispatch_reason = gate["reason"]
    # concurrency_enabled alias: True iff dispatch_mode resolved to "concurrent".
    # WAVE_CONCURRENCY_ENABLED is kept as a dormant unused const (backward compat).
    concurrency_enabled = dispatch_mode == "concurrent"

    try:
        from map_step_runner import (  # pyright: ignore[reportMissingImports]
            _worktree_isolation_mode,
        )
        isolation_active = _worktree_isolation_mode(Path(".")) != "off"
    except ImportError:
        isolation_active = False

    if not state.execution_waves:
        return {
            "mode": "sequential",
            "wave_index": 0,
            "subtasks": [],
            "is_complete": True,
            "concurrency_enabled": concurrency_enabled,
            "dispatch_mode": "sequential",
            "isolation_active": isolation_active,
            "reason": WAVE_REASON_NO_WAVES,
            "message": "No execution waves configured. Use sequential mode.",
        }

    if state.current_wave_index >= len(state.execution_waves):
        return {
            "mode": "sequential",
            "wave_index": state.current_wave_index,
            "subtasks": [],
            "is_complete": True,
            "concurrency_enabled": concurrency_enabled,
            "dispatch_mode": "sequential",
            "isolation_active": isolation_active,
            "reason": WAVE_REASON_WAVE_COMPLETE,
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
        info = {
            "subtask_id": st_id,
            "phase": phase_name,
            "step_id": phase,
        }
        if phase_name == "ACTOR":
            isolation = state.retry_isolation_status.get(st_id)
            quarantine_path = state.retry_quarantine_paths.get(st_id)
            if isolation == "clean_retry_required" and quarantine_path:
                info["retry_isolation"] = isolation
                info["retry_quarantine_path"] = quarantine_path
                info["instruction"] = (
                    f"CLEAN_RETRY mode is required for {st_id}: read {quarantine_path}, "
                    "rebuild context from durable artifacts only, and do not reuse the "
                    "rejected approach unless preserved there."
                )
        subtask_infos.append(info)

    return {
        "mode": mode,
        "wave_index": state.current_wave_index,
        "wave_total": len(state.execution_waves),
        "subtasks": subtask_infos,
        "is_complete": False,
        "concurrency_enabled": concurrency_enabled,
        "dispatch_mode": dispatch_mode,
        "isolation_active": isolation_active,
        "reason": dispatch_reason,
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


def select_execution_strategy(
    branch: str, project_dir: Path | None = None
) -> dict:
    """Determine whether to use wave_loop or legacy sequential walker.

    Predicate: wave_loop IFF wave_mode in {on, auto} AND worktree.isolation != 'off'
    AND any color-group has width >= 2.

    Slice 6: worktree.isolation defaults to 'auto' and concurrent_dispatch defaults
    to True, so a parallel-ready plan now selects the wave-loop by default.

    Kill-switch: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (checked FIRST) forces the full
    legacy sequential path regardless of config — byte-identical to pre-5a legacy.
    Per-repo opt-out: set `worktree.isolation: off` in .map/config.yaml.

    Args:
        branch: Git branch name (sanitized)
        project_dir: Project root containing .map/config.yaml.
                     Defaults to Path('.') consistent with other helpers.

    Returns:
        {
          "strategy": "wave_loop" | "sequential",
          "wave_mode": "off" | "auto" | "on",
          "worktree_isolation": "off" | "auto" | "required",
          "has_parallel_groups": bool,
          "reason": str,
          "concurrency_allowed": bool,
        }
    """
    if project_dir is None:
        project_dir = Path(".")

    # Kill-switch: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 forces legacy sequential regardless of config.
    if _sequential_only_env():
        return {
            "strategy": "sequential",
            "wave_mode": "off",
            "worktree_isolation": "off",
            "has_parallel_groups": False,
            "reason": WAVE_REASON_SEQUENTIAL_ONLY_ENV,
            "concurrency_allowed": False,
        }

    try:
        from map_step_runner import (  # pyright: ignore[reportMissingImports]
            _execution_wave_mode,
            _worktree_isolation_mode,
        )
        wave_mode = _execution_wave_mode(project_dir)
        isolation_mode = _worktree_isolation_mode(project_dir)
    except ImportError:
        wave_mode = "off"
        isolation_mode = "off"

    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    has_parallel_groups = any(len(g) >= 2 for g in state.execution_waves)

    if wave_mode in {"on", "auto"} and isolation_mode != "off" and has_parallel_groups:
        strategy = "wave_loop"
        reason = (
            f"wave_mode={wave_mode!r}, worktree.isolation={isolation_mode!r}, "
            "and execution_waves has width>=2 group"
        )
    else:
        if wave_mode not in {"on", "auto"}:
            reason = f"wave_mode={wave_mode!r} (not on/auto) → legacy sequential"
        elif isolation_mode == "off":
            reason = "worktree.isolation='off' → legacy sequential (no isolation, no parallel)"
        else:
            reason = "no color-group with width>=2 → sequential (all width-1 waves)"
        strategy = "sequential"

    concurrency_allowed = (
        strategy == "wave_loop"
        and isolation_mode in {"auto", "required"}
        and has_parallel_groups
    )
    return {
        "strategy": strategy,
        "wave_mode": wave_mode,
        "worktree_isolation": isolation_mode,
        "has_parallel_groups": has_parallel_groups,
        "reason": reason,
        "concurrency_allowed": concurrency_allowed,
    }


def compute_dispatch_gate(
    branch: str, project_dir: Path | None = None
) -> dict:
    """Compute the dispatch mode for the current wave, fail-closed on config contradiction.

    Gate logic (evaluated in order):

    1. If concurrent_dispatch is False (default): return sequential immediately.
       FIRST executable line — no probe, no select_execution_strategy call, no import
       of any concurrency primitive (HC-1 byte-identity).

    2. If concurrent_dispatch is True AND worktree.isolation == 'off':
       raise DispatchGateError — config contradiction, HC-3 never silent-degrade.

    3. If concurrent_dispatch is True AND isolation != 'off' AND NOT concurrency_allowed:
       return sequential with WAVE_REASON_GATE_NOT_PARALLELIZABLE (not an error —
       the plan has no parallelizable groups).

    4. If concurrent_dispatch is True AND isolation != 'off' AND concurrency_allowed
       AND the CURRENT wave (execution_waves[current_wave_index]) has width < 2:
       return sequential with WAVE_REASON_CURRENT_WAVE_SEQUENTIAL (not an error —
       the current wave is width-1 even though a later wave is parallel).

    5. If concurrent_dispatch is True AND isolation != 'off' AND concurrency_allowed
       AND the CURRENT wave has width >= 2:
       return concurrent with WAVE_REASON_CONCURRENT_GATED.

    Args:
        branch: Git branch name (sanitized).
        project_dir: Project root containing .map/config.yaml.
                     Defaults to Path('.').

    Returns:
        {"dispatch_mode": "sequential" | "concurrent", "reason": <stable code>}

    Raises:
        DispatchGateError: When concurrent_dispatch=true but worktree.isolation='off'
                           (HC-3: config contradiction must never be silently degraded).
    """
    if project_dir is None:
        project_dir = Path(".")

    # Kill-switch FIRST: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 forces legacy sequential path.
    # No concurrency probe, no config read, no import of any concurrency primitive.
    if _sequential_only_env():
        return {
            "dispatch_mode": "sequential",
            "reason": WAVE_REASON_SEQUENTIAL_ONLY_ENV,
        }

    # Step 1: short-circuit on flag=false — first gate check after kill-switch and
    # parameter normalization. No concurrency probe, no select_execution_strategy call,
    # no _worktree_isolation_mode/concurrency_ready call, no dispatcher import runs on
    # this path. The project_dir None-guard above is a safe default-arg normalization,
    # not a concurrency primitive.
    try:
        from map_step_runner import (  # pyright: ignore[reportMissingImports]
            _concurrent_dispatch_enabled,
        )
        flag_on = _concurrent_dispatch_enabled(project_dir)
    except ImportError:
        flag_on = True  # default ON (Slice 6) when runner unavailable

    if not flag_on:
        return {
            "dispatch_mode": "sequential",
            "reason": WAVE_REASON_DISPATCH_SEQUENTIAL,
        }

    # Step 2: flag is on — check isolation config.
    try:
        from map_step_runner import (  # pyright: ignore[reportMissingImports]
            _worktree_isolation_mode as _wt_iso,
        )
        isolation = _wt_iso(project_dir)
    except ImportError:
        isolation = "off"

    if isolation == "off":
        raise DispatchGateError(
            "concurrent_dispatch=true requires worktree.isolation != 'off', "
            f"but worktree.isolation is 'off' in {project_dir}. "
            "Set worktree.isolation to 'auto' or 'required' to enable concurrent dispatch."
        )

    # Step 3: check whether the plan is actually parallelizable (any wave has width>=2).
    strategy_result = select_execution_strategy(branch, project_dir)
    concurrency_allowed = strategy_result.get("concurrency_allowed", False)

    if not concurrency_allowed:
        return {
            "dispatch_mode": "sequential",
            "reason": WAVE_REASON_GATE_NOT_PARALLELIZABLE,
        }

    # Step 4: plan has at least one parallel wave, but gate on the ACTIVE wave.
    # select_execution_strategy checks any wave (has_parallel_groups), not the
    # current wave index. A width-1 current wave must dispatch sequentially even
    # if a later wave is parallel — dispatch_mode is per-wave, not per-plan.
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)
    waves = state.execution_waves
    idx = state.current_wave_index
    if idx >= len(waves) or len(waves[idx]) < 2:
        return {
            "dispatch_mode": "sequential",
            "reason": WAVE_REASON_CURRENT_WAVE_SEQUENTIAL,
        }

    return {
        "dispatch_mode": "concurrent",
        "reason": WAVE_REASON_CONCURRENT_GATED,
    }


def _write_feedback_file(
    branch: str, filename: str, header: str, feedback: str
) -> str | None:
    """Write monitor feedback to a file if feedback is non-empty.

    Returns the file path string, or None if nothing was written.
    """
    if not feedback.strip():
        return None
    fb_path = Path(f".map/{branch}/{filename}")
    fb_path.parent.mkdir(parents=True, exist_ok=True)
    fb_path.write_text(f"# {header}\n\n{feedback}\n", encoding="utf-8")
    return str(fb_path)


def _task_plan_path(branch: str) -> str:
    return f".map/{branch}/task_plan_{branch}.md"


def _source_artifact_refs(
    branch: str, feedback_file: str | None
) -> list[dict[str, str]]:
    refs = [
        {"path": f".map/{branch}/step_state.json", "kind": "step-state"},
        {"path": f".map/{branch}/blueprint.json", "kind": "blueprint"},
        {"path": _task_plan_path(branch), "kind": "task-plan"},
    ]
    if feedback_file:
        refs.append({"path": feedback_file, "kind": "monitor-feedback"})
    return refs


def _write_retry_quarantine(
    branch: str,
    subtask_id: str,
    retry_count: int,
    feedback_file: str | None,
    feedback: str,
) -> str:
    """Write compact clean-retry context that excludes raw failed reasoning."""
    path = Path(f".map/{branch}/retry_quarantine.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = _shorten_text(feedback) or "See latest Monitor feedback artifact."
    existing: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            existing = {}

    quarantines = existing.get("quarantines")
    if not isinstance(quarantines, list):
        quarantines = []
    quarantines = [
        item
        for item in quarantines
        if not (
            isinstance(item, dict)
            and item.get("subtask_id") == subtask_id
            and item.get("retry_count") == retry_count
        )
    ]
    quarantines.append(
        {
            "subtask_id": subtask_id,
            "retry_count": retry_count,
            "isolation_mode": "clean_retry",
            "failed_attempt": f"retry_{retry_count}",
            "monitor_rejection_summary": summary,
            "rejected_assumptions": [],
            "do_not_repeat": [summary],
            "preserved_constraints": [
                "Preserve current blueprint hard_constraints, coverage_map tags, validation_criteria, and mutation boundaries."
            ],
            "required_evidence": [
                "Read blueprint.json for the subtask contract before editing.",
                "Read the latest Monitor feedback artifact before choosing a new approach.",
                "Cite passing focused checks or explain the blocker before returning to Monitor.",
            ],
            "source_artifacts": _source_artifact_refs(branch, feedback_file),
        }
    )

    payload = {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "quarantines": quarantines,
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    tmp_path.replace(path)
    return str(path)


def _record_retry_isolation(
    branch: str,
    state: StepState,
    subtask_id: str | None,
    retry_count: int,
    feedback_file: str | None,
    feedback: str,
) -> tuple[str, str | None]:
    """Update retry isolation counters and write quarantine when required."""
    subtask_key = subtask_id or "workflow"
    if retry_count >= 2:
        quarantine_path = _write_retry_quarantine(
            branch, subtask_key, retry_count, feedback_file, feedback
        )
        state.clean_retry_count += 1
        state.retry_isolation_status[subtask_key] = "clean_retry_required"
        state.retry_quarantine_paths[subtask_key] = quarantine_path
        return "clean_retry_required", quarantine_path

    state.contaminated_retry_count += 1
    state.retry_isolation_status[subtask_key] = "normal_retry"
    return "normal_retry", None


def _check_retry_limit(
    current_retries: int, max_retries: int, context: dict
) -> dict | None:
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

    # Accept call from MONITOR (the canonical path) OR ACTOR (the common
    # mistake: operator notices Monitor's verdict was valid=false while
    # cursor is technically still at 2.3 because they skipped
    # validate_step("2.3") on the way through). "monitor_failed" already
    # implies the failure happened — fighting the phase check is just
    # ceremony. Reject only from clearly-wrong phases (DECOMPOSE /
    # INIT_STATE / COMPLETE) where the call doesn't make sense.
    if state.current_step_phase not in ("MONITOR", "ACTOR", "APPLY", "TEST_WRITER"):
        return {
            "status": "error",
            "message": (
                f"monitor_failed() called from phase '{state.current_step_phase}', "
                "expected MONITOR or ACTOR/APPLY/TEST_WRITER. Aborting to "
                "prevent state corruption."
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

    # Persist only BLOCKER-class feedback so Actor retries do not re-bloat the
    # implementation for style, volume, docs-only, or nice-to-have comments.
    retry_feedback = _filter_blocker_retry_feedback(feedback)
    feedback_file = _write_feedback_file(
        branch,
        f"monitor_feedback_retry{state.retry_count}.md",
        f"Monitor Feedback (retry {state.retry_count})",
        retry_feedback,
    )
    retry_isolation, quarantine_path = _record_retry_isolation(
        branch,
        state,
        state.current_subtask_id,
        state.retry_count,
        feedback_file,
        retry_feedback,
    )

    state.save(state_file)

    return {
        "status": "retrying",
        "retry_count": state.retry_count,
        "max_retries": state.max_retries,
        "current_phase": "ACTOR",
        "feedback_file": feedback_file,
        "retry_isolation": retry_isolation,
        "retry_quarantine_path": quarantine_path,
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

    # Persist only BLOCKER-class feedback so Actor retries do not re-bloat the
    # implementation for style, volume, docs-only, or nice-to-have comments.
    retry_feedback = _filter_blocker_retry_feedback(feedback)
    feedback_file = _write_feedback_file(
        branch,
        f"monitor_feedback_{subtask_id}_retry{current_retries}.md",
        f"Monitor Feedback for {subtask_id} (retry {current_retries})",
        retry_feedback,
    )
    retry_isolation, quarantine_path = _record_retry_isolation(
        branch, state, subtask_id, current_retries, feedback_file, retry_feedback
    )

    state.save(state_file)

    return {
        "status": "retrying",
        "subtask_id": subtask_id,
        "retry_count": current_retries,
        "max_retries": state.max_retries,
        "current_phase": "ACTOR",
        "feedback_file": feedback_file,
        "retry_isolation": retry_isolation,
        "retry_quarantine_path": quarantine_path,
        "message": (
            f"Monitor failed for {subtask_id}. "
            f"Retry {current_retries}/{state.max_retries}. "
            f"Phase reset to ACTOR."
        ),
    }


def mark_workflow_complete(branch: str) -> dict:
    """Atomically mark the workflow as complete.

    Sets every canonical completion field in a single save:
      - workflow_status   = "WORKFLOW_COMPLETE"
      - current_step_id   = "COMPLETE"
      - current_step_phase = "COMPLETE"
      - completed_at      = ISO-8601 UTC timestamp

    Replaces ad-hoc ``jq`` mutations that left ``current_step_phase`` stale on
    "ACTOR" and broke ``reopen_for_fixes``. Refuses if any work is still
    pending so callers cannot prematurely close an in-flight workflow.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": f"No step_state.json at {state_file}",
        }

    state = StepState.load(state_file)

    if state.pending_steps:
        return {
            "status": "error",
            "message": (
                f"Cannot mark complete: {len(state.pending_steps)} pending "
                f"step(s) remain: {state.pending_steps}"
            ),
        }

    state.workflow_status = "WORKFLOW_COMPLETE"
    state.current_step_id = "COMPLETE"
    state.current_step_phase = "COMPLETE"
    state.completed_at = _utc_timestamp()
    state.save(state_file)

    return {
        "status": "success",
        "workflow_status": state.workflow_status,
        "current_step_id": state.current_step_id,
        "current_step_phase": state.current_step_phase,
        "completed_at": state.completed_at,
    }


def record_subtask_result(
    subtask_id: str,
    branch: str,
    files_changed: list[str],
    status: str,
    summary: str = "",
    commit_sha: str | None = None,
) -> dict:
    """CLI wrapper around StepState.record_subtask_result.

    The skill text used to advise "record files changed in step_state.json"
    without a public command — callers had to either reach into Python or
    rely on the indirect record happening inside validate_step. This exposes
    the canonical write path so /map-efficient's ACTOR-done step has a
    deterministic dispatch.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": f"No step_state.json at {state_file}",
        }
    state = StepState.load(state_file)
    # Warn-only file-exists check: catches typos / drift between --files arg
    # and the actual diff without blocking on legitimate file deletions or
    # renames. Caller sees the missing list and decides; record proceeds.
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()

    def _is_cross_repo_path(p: str) -> bool:
        """Return True if ``p`` is a cross-repo (sibling) path.

        Two detection modes (any one match = cross-repo):
          (a) Path escapes project_dir via ``..`` (``../LLM-memory/...``).
          (b) Path's first segment matches a sibling directory at
              ``../<segment>/``, i.e. ``LLM-memory/foo.go`` from a
              cwd-parent shared with ``LLM-memory``. Catches the common
              case where the operator writes the sibling repo name
              without the ``..`` prefix (the path doesn't exist under
              project_dir but DOES exist as a sibling).

        Cross-repo paths are legitimate but MAP can't verify their
        existence; validate_blueprint_contract already warns about
        cross-repo affected_files at planning time. Suppress the "typo"
        warning for both forms.
        """
        # Mode (a): path escapes project_dir via .. or absolute.
        try:
            resolved = (project_dir / p).resolve()
            resolved.relative_to(project_dir)
        except (ValueError, OSError):
            return True
        # Mode (b): first path segment matches a sibling directory.
        # Path looks local relative to project_dir, but project_dir/<seg>
        # doesn't exist while project_dir.parent/<seg> does — that's a
        # sibling repo the operator named without ../ prefix.
        first_segment = p.split("/", 1)[0]
        if first_segment and first_segment not in (".", ".."):
            local_candidate = project_dir / first_segment
            sibling_candidate = project_dir.parent / first_segment
            if (
                not local_candidate.exists()
                and sibling_candidate.is_dir()
            ):
                return True
        return False

    cross_repo_files: list[str] = []
    missing_files: list[str] = []
    for p in (files_changed or []):
        if not isinstance(p, str) or not p:
            continue
        if _is_cross_repo_path(p):
            cross_repo_files.append(p)
            continue
        if not (project_dir / p).exists():
            missing_files.append(p)
    import subprocess as _sp
    # Auto-detect commit_sha from `git log -1 --format=%H` when caller
    # didn't pass one — closes the "commit_sha always null in
    # subtask_results" gap that weakened downstream provenance.
    auto_commit_sha = commit_sha
    auto_detected_sha = False
    if not auto_commit_sha:
        try:
            proc = _sp.run(
                ["git", "log", "-1", "--format=%H"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                candidate = proc.stdout.strip()
                if candidate:
                    auto_commit_sha = candidate
                    auto_detected_sha = True
        except (OSError, _sp.TimeoutExpired):
            pass
    # Stale-SHA detection: when auto-detect grabbed the same commit as
    # the prior subtask's recorded SHA, the operator didn't make a new
    # commit for THIS subtask — silently writing the prior SHA into the
    # current entry makes the audit trail lie. Flag the duplicate so
    # caller can decide (commit per-subtask, OR record without --commit-sha
    # for the "intentionally bundled" case, OR pass --commit-sha
    # explicitly to acknowledge the shared SHA).
    sha_is_stale_duplicate = (
        auto_detected_sha
        and auto_commit_sha is not None
        and state.last_subtask_commit_sha == auto_commit_sha
    )

    # Actor-output verification (added 2026-05-25): cross-check that the
    # files Actor CLAIMED to change actually show up in the worktree —
    # either in the most recent commit (if commit_sha resolved) OR in
    # the uncommitted diff. Catches the "Actor truncated mid-flight and
    # reported files it never wrote" failure mode where record_subtask_result
    # used to accept anything. The check is WARN-only by default so legit
    # cases (file recreated then deleted, etc.) don't block. The next-level
    # gate is the operator reading the response — they SHOULD reject when
    # files_not_in_diff is non-empty.
    declared = [p for p in (files_changed or []) if isinstance(p, str) and p]
    files_not_in_diff: list[str] = []
    if declared:
        diff_paths: set[str] = set()
        try:
            if auto_commit_sha:
                # Files in the latest commit's diff.
                cproc = _sp.run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", auto_commit_sha],
                    cwd=project_dir, capture_output=True, text=True, timeout=5, check=False,
                )
                if cproc.returncode == 0:
                    diff_paths.update(
                        line.strip() for line in cproc.stdout.splitlines() if line.strip()
                    )
            # Uncommitted (worktree + index) via porcelain.
            sproc = _sp.run(
                ["git", "status", "--porcelain"],
                cwd=project_dir, capture_output=True, text=True, timeout=5, check=False,
            )
            if sproc.returncode == 0:
                for raw in sproc.stdout.splitlines():
                    if len(raw) >= 4:
                        path = raw[3:].strip()
                        if " -> " in path:
                            path = path.split(" -> ", 1)[1]
                        if path:
                            diff_paths.add(path)
        except (OSError, _sp.TimeoutExpired):
            diff_paths = set()
        if diff_paths:
            files_not_in_diff = [p for p in declared if p not in diff_paths]
        # Gitignored deliverables (e.g. .map/ workflow artifacts like spike
        # docs or eval-run .jsonl) never appear in git diff/status by design —
        # that is NOT Actor truncation. Drop any declared path that
        # `git check-ignore` reports as ignored so it does not raise a false
        # "Possible Actor truncation" warning. A gitignored file that is also
        # missing from disk is still flagged separately via missing_files.
        if files_not_in_diff:
            try:
                igproc = _sp.run(
                    ["git", "check-ignore", "--", *files_not_in_diff],
                    cwd=project_dir, capture_output=True, text=True, timeout=5, check=False,
                )
                ignored = {
                    line.strip()
                    for line in igproc.stdout.splitlines()
                    if line.strip()
                }
                if ignored:
                    files_not_in_diff = [
                        p for p in files_not_in_diff if p not in ignored
                    ]
            except (OSError, _sp.TimeoutExpired):
                pass

    state.record_subtask_result(
        subtask_id,
        files_changed=files_changed,
        status=status,
        summary=summary,
        commit_sha=auto_commit_sha,
    )
    state.save(state_file)
    response: dict = {
        "status": "success",
        "subtask_id": subtask_id,
        "recorded": state.subtask_results[subtask_id],
    }
    if missing_files:
        response["warning"] = (
            "Some recorded files do not exist on disk — possible typo or "
            "stale --files arg."
        )
        response["missing_files"] = missing_files
    if cross_repo_files:
        # Surface (don't warn) cross-repo paths so the audit trail shows
        # MAP knew about them. validate_blueprint_contract already warns
        # at planning time; record_subtask_result should not repeat the
        # "typo" message — the paths are legitimate, just unverifiable
        # from THIS project's CLAUDE_PROJECT_DIR.
        response["cross_repo_files"] = cross_repo_files
    if files_not_in_diff:
        existing_warning = response.get("warning", "")
        suffix = (
            f"Actor-claimed files not present in commit/diff "
            f"({len(files_not_in_diff)}/{len(declared)}): "
            f"{files_not_in_diff!r}. Possible Actor truncation — verify "
            "before advancing to MONITOR / next subtask."
        )
        response["warning"] = (
            f"{existing_warning}\n{suffix}".strip()
            if existing_warning
            else suffix
        )
        response["files_not_in_diff"] = files_not_in_diff
    if sha_is_stale_duplicate and auto_commit_sha:
        stale_sha_short = auto_commit_sha[:12]
        existing_warning = response.get("warning", "")
        suffix = (
            f"Auto-detected commit_sha {stale_sha_short} matches the "
            "prior subtask's last_subtask_commit_sha — you almost certainly "
            "did NOT commit between subtasks, so the audit trail will record "
            "the same SHA for both. Either (a) commit per-subtask BEFORE "
            "record_subtask_result (recommended; see map-efficient SKILL.md), "
            "or (b) pass --commit-sha <SHA> explicitly to acknowledge a "
            "shared commit (bundled-PR mode)."
        )
        response["warning"] = (
            f"{existing_warning}\n{suffix}".strip()
            if existing_warning
            else suffix
        )
        response["sha_is_stale_duplicate"] = True
    return response


def _load_deferred_flaky_triage(
    branch: str,
    check_id: str,
    triage_path: str = "",
) -> tuple[dict | None, dict]:
    """Return a validated deferred_nondeterministic triage for check_id."""
    path = Path(triage_path) if triage_path else Path(f".map/{branch}/flaky_test_triage.json")
    try:
        from map_step_runner import (  # pyright: ignore[reportMissingImports]
            validate_flaky_test_triage,
        )
    except ImportError:
        return None, {
            "valid": False,
            "errors": ["map_step_runner.validate_flaky_test_triage could not be imported"],
            "path": str(path),
        }

    validation = validate_flaky_test_triage(str(path), branch)
    if not validation.get("valid"):
        return None, validation

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return None, {
            "valid": False,
            "errors": [f"cannot read flaky test triage after validation: {exc}"],
            "path": str(path),
        }
    triages = payload.get("triages") if isinstance(payload, dict) else None
    if not isinstance(triages, list):
        return None, {
            "valid": False,
            "errors": ["flaky test triage must contain a triages array"],
            "path": str(path),
        }
    matches = [
        item
        for item in triages
        if isinstance(item, dict)
        and item.get("check_id") == check_id
        and item.get("disposition") == DEFERRED_NONDETERMINISTIC_STATUS
    ]
    if not matches:
        return None, {
            "valid": False,
            "errors": [
                f"no {DEFERRED_NONDETERMINISTIC_STATUS} triage found for check_id {check_id!r}"
            ],
            "path": str(path),
            "validation": validation,
        }
    return matches[-1], {"valid": True, "path": str(path), "validation": validation}


def _advance_after_terminal_current_subtask(state: StepState, branch: str) -> dict:
    """Advance from a terminal current subtask to next ready subtask or COMPLETE."""
    advanced_from_subtask: str | None = None
    advanced_to_subtask: str | None = None
    blocked_remaining: list[str] = []
    skipped_for_deps: list[str] = []

    if state.subtask_index + 1 < len(state.subtask_sequence) or any(
        state.subtask_phases.get(sid) == DEFERRED_FOR_DEPS_PHASE
        for sid in state.subtask_sequence
    ):
        ready_idx, skipped_for_deps = _find_next_ready_subtask_index(
            state, branch, start_after_index=state.subtask_index,
            treat_current_as_done=True,
        )
        for skipped_sid in skipped_for_deps:
            state.subtask_phases[skipped_sid] = DEFERRED_FOR_DEPS_PHASE
        if ready_idx is not None:
            advanced_from_subtask = state.current_subtask_id
            state.subtask_index = ready_idx
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            advanced_to_subtask = state.current_subtask_id
            if state.subtask_phases.get(state.current_subtask_id) == DEFERRED_FOR_DEPS_PHASE:
                state.subtask_phases.pop(state.current_subtask_id, None)
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]
            state.completed_steps = []
            state.skipped_steps = []
            state.retry_count = 0
            state.current_step_id = state.pending_steps[0]
            state.current_step_phase = STEP_PHASES.get(
                state.current_step_id, "RESEARCH"
            )
            next_step_signal = state.current_step_id
        else:
            completed = _completed_subtask_ids_for_deps(state)
            if state.current_subtask_id:
                completed.add(state.current_subtask_id)
            blocked_remaining = [
                sid for sid in state.subtask_sequence if sid not in completed
            ]
            if not blocked_remaining:
                state.pending_steps = []
                state.workflow_status = "WORKFLOW_COMPLETE"
                state.current_step_id = "COMPLETE"
                state.current_step_phase = "COMPLETE"
                state.completed_at = _utc_timestamp()
                next_step_signal = "COMPLETE"
            else:
                state.current_step_id = "BLOCKED_ON_DEPS"
                state.current_step_phase = "BLOCKED_ON_DEPS"
                next_step_signal = "BLOCKED_ON_DEPS"
    else:
        state.pending_steps = []
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.completed_at = _utc_timestamp()
        next_step_signal = "COMPLETE"

    result: dict[str, object] = {"next_step": next_step_signal}
    if advanced_to_subtask is not None:
        result["subtask_advanced_from"] = advanced_from_subtask
        result["subtask_advanced_to"] = advanced_to_subtask
    if skipped_for_deps:
        result["skipped_for_deps"] = skipped_for_deps
    if next_step_signal == "BLOCKED_ON_DEPS":
        result["blocked_subtasks"] = blocked_remaining
    return result


def defer_flaky_subtask(
    subtask_id: str,
    branch: str,
    check_id: str,
    *,
    triage_path: str = "",
    files_changed: list[str] | None = None,
    summary: str = "",
    commit_sha: str | None = None,
) -> dict:
    """Record an explicit flaky-test Monitor defer and advance the workflow.

    This is the third Monitor outcome for confirmed nondeterminism: it is not a
    clean pass, and it is not Actor retry feedback. The command only succeeds
    after validating a sidecar triage whose matching check has mixed pass/fail
    evidence and disposition=deferred_nondeterministic.
    """
    check = check_id.strip()
    if not check:
        return {"status": "error", "message": "--check-id is required"}

    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": f"No step_state.json at {state_file}",
        }
    state = StepState.load(state_file)
    if subtask_id not in state.subtask_sequence:
        return {
            "status": "error",
            "message": (
                f"Unknown subtask_id {subtask_id!r}. "
                f"Known: {state.subtask_sequence}"
            ),
        }
    if subtask_id != state.current_subtask_id:
        return {
            "status": "error",
            "message": (
                f"defer_flaky_subtask only advances the current subtask; "
                f"current is {state.current_subtask_id!r}, got {subtask_id!r}"
            ),
        }
    if state.current_step_phase not in ("MONITOR", "ACTOR"):
        return {
            "status": "error",
            "message": (
                f"defer_flaky_subtask must be called from MONITOR/ACTOR phase, "
                f"got {state.current_step_phase!r}"
            ),
        }

    triage, validation = _load_deferred_flaky_triage(branch, check, triage_path)
    if triage is None:
        errors = validation.get("errors")
        detail = "; ".join(str(err) for err in errors) if isinstance(errors, list) else "invalid flaky triage"
        return {
            "status": "error",
            "message": (
                f"Cannot defer {subtask_id}: {detail}. Run "
                "run_flaky_test_triage/record_flaky_test_triage and "
                "validate_flaky_test_triage first."
            ),
            "validation": validation,
        }

    run_count = triage.get("run_count")
    pass_count = triage.get("pass_count")
    fail_count = triage.get("fail_count")
    reason = str(triage.get("reason") or "Recorded mixed pass/fail repeated-run evidence.")
    summary_text = summary.strip() or (
        f"Deferred nondeterministic check {check}: {reason} "
        f"({pass_count} pass / {fail_count} fail over {run_count} runs)."
    )

    record_result = record_subtask_result(
        subtask_id,
        branch,
        files_changed=files_changed or [],
        status=DEFERRED_NONDETERMINISTIC_STATUS,
        summary=summary_text,
        commit_sha=commit_sha,
    )
    if record_result.get("status") != "success":
        return record_result

    state = StepState.load(state_file)
    recorded = state.subtask_results.get(subtask_id)
    if not isinstance(recorded, dict):
        recorded = {}
        state.subtask_results[subtask_id] = recorded
    recorded["monitor_verdict_policy"] = FLAKY_TEST_TRIAGE_MONITOR_POLICY
    recorded["non_green_outcome"] = True
    recorded["flaky_test_triage"] = {
        "path": validation.get("path"),
        "check_id": check,
        "disposition": DEFERRED_NONDETERMINISTIC_STATUS,
        "run_count": run_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "reason": reason,
        "command": triage.get("command", ""),
    }
    state.subtask_phases[subtask_id] = "COMPLETE"
    if "2.3" in state.pending_steps:
        state.pending_steps.remove("2.3")
    if "2.3" not in state.completed_steps:
        state.completed_steps.append("2.3")
    if "2.4" in state.pending_steps:
        state.pending_steps.remove("2.4")
    if "2.4" not in state.completed_steps:
        state.completed_steps.append("2.4")
    if not isinstance(getattr(state, "subtask_completion_reasons", None), dict):
        state.subtask_completion_reasons = {}  # type: ignore[attr-defined]
    state.subtask_completion_reasons[subtask_id] = {  # type: ignore[attr-defined]
        "kind": DEFERRED_NONDETERMINISTIC_STATUS,
        "reason": reason,
        "recorded_at": _utc_timestamp(),
        "check_id": check,
    }

    advance = _advance_after_terminal_current_subtask(state, branch)
    state.save(state_file)

    return {
        "status": "success",
        "disposition": DEFERRED_NONDETERMINISTIC_STATUS,
        "subtask_id": subtask_id,
        "check_id": check,
        "monitor_verdict_policy": FLAKY_TEST_TRIAGE_MONITOR_POLICY,
        "non_green_outcome": True,
        "triage_path": validation.get("path"),
        "recorded": state.subtask_results[subtask_id],
        "record_result": record_result,
        **advance,
    }


def backfill_subtask_ids(branch: str) -> dict:
    """Populate the redundant ``subtask_id`` field on legacy subtask_results.

    Older versions of record_subtask_result wrote entries without a
    self-describing ``subtask_id`` field, so downstream reporters that
    forward entries individually saw ``{"subtask_id": null, ...}``. This
    helper walks step_state.json and writes the field for every entry
    that's missing it (or has it set to null). Idempotent: entries
    already carrying the correct id are left untouched.

    Returns:
        Dict with status, ``updated`` count, and the list of updated ids.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": f"No step_state.json at {state_file}",
        }
    state = StepState.load(state_file)
    updated: list[str] = []
    for sid, entry in (state.subtask_results or {}).items():
        if not isinstance(entry, dict):
            continue
        existing = entry.get("subtask_id")
        if existing == sid:
            continue
        entry["subtask_id"] = sid
        updated.append(sid)
    if updated:
        state.save(state_file)
    return {
        "status": "success",
        "branch": branch,
        "updated": len(updated),
        "updated_ids": updated,
    }


def finalize_plan(branch: str) -> dict:
    """Bump the artifact_manifest plan stage to "complete" when artifacts exist.

    Closes the gap where /map-plan leaves stage=plan: partial in
    artifact_manifest.json even after blueprint+task_plan+spec are written.
    No-op safe: returns status="noop" if blueprint+task_plan aren't both
    present.
    """
    plan_dir = Path(f".map/{branch}")
    blueprint = plan_dir / "blueprint.json"
    plan_file = plan_dir / f"task_plan_{branch}.md"
    if not (blueprint.exists() and plan_file.exists()):
        return {
            "status": "noop",
            "message": "blueprint.json + task_plan_<branch>.md required",
        }
    manifest_path = plan_dir / "artifact_manifest.json"
    if not manifest_path.exists():
        return {
            "status": "noop",
            "message": "artifact_manifest.json not found",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "message": f"unreadable artifact_manifest.json: {exc}",
        }
    stages = manifest.get("stages", {})
    if not isinstance(stages, dict):
        return {"status": "error", "message": "manifest.stages malformed"}
    plan_stage = stages.get("plan")
    if not isinstance(plan_stage, dict):
        plan_stage = {}
    plan_stage["status"] = "complete"
    plan_stage["updated_at"] = _utc_timestamp()
    stages["plan"] = plan_stage
    manifest["stages"] = stages
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"status": "success", "plan_stage": plan_stage}


VALID_MARK_COMPLETE_KINDS = {
    "done",
    "noop",
    "deferred",
    "stub",
    "prior_pr",
}


def mark_subtask_complete(
    subtask_id: str,
    branch: str,
    reason: str = "no-op",
    *,
    kind: str | None = None,
) -> dict:
    """Short-circuit a subtask as already-done without running its phases.

    Use cases: a subtask whose intended change was already made historically
    (rename done in a prior PR), a docs-only subtask that doesn't need the
    research/actor/monitor cycle, or any other no-op detected up-front.

    ``kind`` (added 2026-05-25) classifies the short-circuit so future
    audits can tell intent apart. One of:
      - ``done``: the work IS finished, just not via this workflow
      - ``noop``: nothing to do (auto-detected no-op)
      - ``deferred``: intentionally skipped for THIS iteration, expected
        to come back later (stub placeholder)
      - ``stub``: empty placeholder created during planning, expected to
        be implemented in a follow-up subtask/PR
      - ``prior_pr``: this work was completed in a prior PR (rename,
        infra change already merged)
    Default ``None`` falls back to ``noop`` for backward compatibility.

    Effects:
      - Records a synthetic subtask_result with status set to the kind
        (``no-op``/``deferred``/``stub``/...) and the reason in summary,
        so reports can group by intent.
      - Marks subtask_phases[subtask_id] = "COMPLETE".
      - Stores subtask_completion_reasons[subtask_id] = {kind, reason,
        recorded_at} for audit.
      - If subtask_id is the current subtask, advances to the next one and
        resets pending_steps to the canonical start (2.2). When it was the
        last subtask, transitions to WORKFLOW_COMPLETE atomically.

    Refuses to operate on an unknown subtask_id to avoid silently corrupting
    the sequence.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "error",
            "message": f"No step_state.json at {state_file}",
        }

    state = StepState.load(state_file)

    if subtask_id not in state.subtask_sequence:
        return {
            "status": "error",
            "message": (
                f"Unknown subtask_id {subtask_id!r}. "
                f"Known: {state.subtask_sequence}"
            ),
        }

    # Normalize kind. Legacy callers pass no kind — keep backward
    # compatibility by mapping to "noop".
    normalized_kind = (kind or "noop").strip().lower()
    if normalized_kind not in VALID_MARK_COMPLETE_KINDS:
        return {
            "status": "error",
            "message": (
                f"Invalid kind {kind!r}. Must be one of "
                f"{sorted(VALID_MARK_COMPLETE_KINDS)}."
            ),
        }

    # Status field on the synthetic entry: keep "no-op" for the legacy
    # default so existing reporters that filter by status="no-op" don't
    # break. For other kinds the explicit name is stored so groupings
    # like "show me all deferred stubs" work without parsing the summary.
    status_value = "no-op" if normalized_kind == "noop" else normalized_kind
    state.record_subtask_result(
        subtask_id,
        files_changed=[],
        status=status_value,
        summary=f"Marked {normalized_kind} via mark_subtask_complete: {reason}",
    )
    state.subtask_phases[subtask_id] = "COMPLETE"
    # Audit ledger lives outside subtask_results so reporters can render
    # a "WHY was this short-circuited?" column without re-parsing summary
    # text. Single source of truth for the (kind, reason) pair.
    if not isinstance(
        getattr(state, "subtask_completion_reasons", None), dict
    ):
        state.subtask_completion_reasons = {}  # type: ignore[attr-defined]
    state.subtask_completion_reasons[subtask_id] = {  # type: ignore[attr-defined]
        "kind": normalized_kind,
        "reason": reason,
        "recorded_at": _utc_timestamp(),
    }

    advanced = False
    closed = False
    if state.current_subtask_id == subtask_id:
        if state.subtask_index + 1 < len(state.subtask_sequence):
            state.subtask_index += 1
            state.current_subtask_id = state.subtask_sequence[state.subtask_index]
            state.current_step_id = "2.2"
            state.current_step_phase = "RESEARCH"
            step_order = _get_step_order(state.tdd_mode)
            research_idx = step_order.index("2.2")
            state.pending_steps = step_order[research_idx:]
            state.completed_steps = []
            state.skipped_steps = []
            state.retry_count = 0
            advanced = True
        else:
            state.pending_steps = []
            state.workflow_status = "WORKFLOW_COMPLETE"
            state.current_step_id = "COMPLETE"
            state.current_step_phase = "COMPLETE"
            state.completed_at = _utc_timestamp()
            closed = True

    state.save(state_file)

    return {
        "status": "success",
        "subtask_id": subtask_id,
        "reason": reason,
        "kind": normalized_kind,
        "advanced_to": state.current_subtask_id if advanced else None,
        "workflow_complete": closed,
    }


def _is_workflow_complete(state: "StepState") -> bool:
    """Return True if any canonical completion signal is set.

    The canonical signal is ``workflow_status == "WORKFLOW_COMPLETE"`` (set
    by ``mark_workflow_complete``). The fallbacks accept legacy state files
    that were marked complete via partial mutations (e.g., the historical
    ``jq`` line in ``map-check`` that bypassed this API) AND — added 2026-05-25
    — the case where every subtask in ``subtask_sequence`` has a corresponding
    entry in ``subtask_results``. Truthiness used to be cursor-only, so a
    stuck cursor (ST-033 case) made write_run_health_report report ``pending``
    even when 51/51 entries were already recorded.
    """
    if (
        state.workflow_status == "WORKFLOW_COMPLETE"
        or state.current_step_id == "COMPLETE"
        or state.current_step_phase == "COMPLETE"
    ):
        return True
    sequence = state.subtask_sequence or []
    if not sequence:
        return False
    completed = _completed_subtask_ids_for_deps(state)
    return all(sid in completed for sid in sequence)


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

    if not _is_workflow_complete(state):
        return {
            "status": "error",
            "message": (
                f"Workflow is in phase '{state.current_step_phase}' "
                f"(workflow_status='{state.workflow_status}'), not COMPLETE. "
                "Use monitor_failed for non-COMPLETE retry."
            ),
        }

    # Reset to ACTOR+MONITOR cycle. Reset every completion field atomically —
    # the same rule that ``mark_workflow_complete`` enforces in the forward
    # direction. Leaving ``workflow_status="WORKFLOW_COMPLETE"`` here would
    # leave the very inconsistency we are trying to eradicate.
    state.current_step_id = "2.3"
    state.current_step_phase = "ACTOR"
    state.pending_steps = ["2.3", "2.4"]
    state.retry_count = 0
    state.workflow_status = "IN_PROGRESS"
    state.completed_at = None

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


def archive_completed_workflow(branch: str) -> dict:
    """Retire a COMPLETED workflow so the branch returns to a clean state.

    Renames ``.map/<branch>/step_state.json`` to
    ``step_state.completed-<utc-timestamp>.json``. Once the active state file is
    gone, ``workflow-gate.py`` fail-opens (edits allowed) and
    ``workflow-context-injector.py`` stops surfacing workflow context — so a
    later session, a quick follow-up edit, or a new unrelated task on the same
    branch no longer trips the gate or misleads the agent into "fixing" a
    workflow that is already done.

    Deferred by design: archival does NOT fire automatically the instant a
    workflow reaches COMPLETE, because ``/map-review`` -> ``reopen_for_fixes``
    needs the active state file present to reopen the run for post-review
    fixes. Archival happens only on an explicit call to this command, or
    automatically when a NEW workflow is initialised on the branch
    (``initialize_workflow``).

    Idempotent and safe:
      - no active state file -> ``status="noop"`` (nothing to archive)
      - active workflow not terminal -> ``status="error"`` (refuses to archive
        an in-flight run; finish or abandon it first)
      - terminal -> renamed, ``status="archived"``
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "noop",
            "message": (
                f"No active step_state.json at {state_file}; nothing to archive."
            ),
        }

    state = StepState.load(state_file)
    if not _is_workflow_complete(state):
        return {
            "status": "error",
            "message": (
                f"Refusing to archive an in-flight workflow "
                f"(phase='{state.current_step_phase}', "
                f"workflow_status='{state.workflow_status}'). Finish it "
                "(mark_workflow_complete) or abandon it before archiving."
            ),
        }

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_file = state_file.with_name(f"step_state.completed-{timestamp}.json")
    # Guard against a same-second second archive clobbering the first.
    if archive_file.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        archive_file = state_file.with_name(
            f"step_state.completed-{timestamp}.json"
        )
    state_file.rename(archive_file)

    return {
        "status": "archived",
        "archive_file": str(archive_file),
        "message": (
            "Workflow archived. Branch is now clean: the edit gate fail-opens "
            "and no workflow context is injected. Start a new /map-* workflow "
            "or edit freely."
        ),
    }


def abandon_workflow(branch: str) -> dict:
    """Forcibly retire any workflow, including stuck/in-flight ones.

    Unlike ``archive_completed_workflow`` (which refuses non-terminal states),
    ``abandon_workflow`` provides an escape hatch for workflows that cannot
    complete normally — e.g. a blueprint stuck in INITIALIZED with an empty
    subtask_sequence, or an in-flight run that can't be finished.

    Behaviour:
      - No active state file → ``status="noop"`` (idempotent).
      - Workflow is already terminal → delegates to ``archive_completed_workflow``
        (gets the ``.completed-`` suffix, same as a normal archive).
      - Workflow is in-flight → renames ``step_state.json`` to
        ``step_state.abandoned-<utc-timestamp>.json``.

    After either path the gate fail-opens and no workflow context is injected.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    if not state_file.exists():
        return {
            "status": "noop",
            "message": (
                f"No active step_state.json at {state_file}; nothing to abandon."
            ),
        }

    state = StepState.load(state_file)
    if _is_workflow_complete(state):
        # Already terminal — use the normal archive path for a clean suffix.
        return archive_completed_workflow(branch)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    abandon_file = state_file.with_name(f"step_state.abandoned-{timestamp}.json")
    if abandon_file.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        abandon_file = state_file.with_name(f"step_state.abandoned-{timestamp}.json")
    state_file.rename(abandon_file)

    return {
        "status": "abandoned",
        "abandon_file": str(abandon_file),
        "phase_at_abandon": state.current_step_phase,
        "message": (
            "Workflow abandoned. Branch is now clean: the edit gate fail-opens "
            "and no workflow context is injected. Start a new /map-* workflow "
            "or edit freely. The abandoned state is preserved for audit."
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


def _load_blueprint_deps(branch: str) -> dict[str, list[str]]:
    """Return {subtask_id: [dep_ids]} from blueprint.json, or empty if absent.

    Tolerates both the flat blueprint shape (subtasks at top level) and the
    decomposer's nested shape (subtasks under blueprint.subtasks). Returns
    empty dict on any read/parse failure — callers fall back to caller-
    provided order (no deps known means no topology to enforce).
    """
    bp_path = Path(f".map/{branch}/blueprint.json")
    if not bp_path.exists():
        return {}
    try:
        payload = json.loads(bp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    body = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    subtasks = body.get("subtasks") if isinstance(body, dict) else None
    deps: dict[str, list[str]] = {}
    if not isinstance(subtasks, list):
        return deps
    for st in subtasks:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if not isinstance(sid, str):
            continue
        raw = st.get("dependencies", [])
        if isinstance(raw, list):
            deps[sid] = [d for d in raw if isinstance(d, str)]
        else:
            deps[sid] = []
    return deps


def _topological_sort_subtasks(
    subtask_ids: list[str], deps_map: dict[str, list[str]]
) -> tuple[list[str] | None, str | None]:
    """Stable topological sort of subtask_ids honoring deps_map.

    Stability: when multiple nodes are simultaneously ready (no remaining
    deps), they emerge in the order they appear in ``subtask_ids``. So a
    decomposer that already wrote subtasks in correct order gets a
    no-op pass; only forward-dep violations move.

    Returns ``(sorted_ids, None)`` on success, or ``(None, cycle_reason)``
    when the graph contains a cycle.

    deps that reference subtasks NOT in ``subtask_ids`` are ignored — the
    blueprint contract validator already rejects unknown deps, so this
    function should never see them in normal flow, but it must not crash
    in pathological cases (e.g., blueprint mid-write).
    """
    known = set(subtask_ids)
    # Filter deps to in-set only and pre-compute incoming-edge counts.
    incoming: dict[str, int] = {sid: 0 for sid in subtask_ids}
    children: dict[str, list[str]] = {sid: [] for sid in subtask_ids}
    for sid in subtask_ids:
        for dep in deps_map.get(sid, []):
            if dep in known and dep != sid:
                incoming[sid] += 1
                children[dep].append(sid)

    # Kahn's algorithm with stable iteration in original input order so a
    # decomposer that already wrote subtasks correctly sees no reorder.
    ready: list[str] = [sid for sid in subtask_ids if incoming[sid] == 0]
    sorted_ids: list[str] = []
    emitted: set[str] = set()
    while ready:
        # Emit in input order (stable). Pop the smallest-index ready node.
        ready.sort(key=lambda s: subtask_ids.index(s))
        node = ready.pop(0)
        sorted_ids.append(node)
        emitted.add(node)
        for child in children[node]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)

    if len(sorted_ids) != len(subtask_ids):
        unresolved = [sid for sid in subtask_ids if sid not in emitted]
        return None, f"dependency cycle involving: {unresolved}"
    return sorted_ids, None


def _normalize_subtask_ids(raw_subtask_ids: list[str]) -> tuple[list[str], str | None]:
    """Split shell-joined arguments and reject malformed subtask IDs."""
    subtask_ids: list[str] = []
    for raw_subtask_id in raw_subtask_ids:
        subtask_ids.extend(raw_subtask_id.split())

    invalid = [
        subtask_id
        for subtask_id in subtask_ids
        if not _SUBTASK_ID_FULL_RE.fullmatch(subtask_id)
    ]
    if invalid:
        return [], (
            "Invalid subtask ID(s): "
            + ", ".join(invalid)
            + ". Expected IDs like ST-001."
        )
    return subtask_ids, None


def set_subtasks(subtask_ids: list[str], branch: str) -> dict:
    """Set subtask sequence after decomposition and select the first subtask.

    Topological invariant (added 2026-05-24): if a blueprint.json exists in
    .map/<branch>/, its declared dependencies are honored — ``subtask_ids``
    is stably topologically sorted so deps always precede their dependents.
    The user-facing friction this addresses: decomposer occasionally emits
    ST-012 with deps=[ST-027]; the linear walker hit ST-012 long before
    ST-027 finished, producing a deadlock the operator had to break by
    hand. Now the sequence is corrected at induction time. If a cycle is
    detected, set_subtasks returns ``status=error`` rather than persisting
    a broken sequence.

    Args:
        subtask_ids: List of subtask IDs (e.g., ["ST-001", "ST-002", "ST-003"])
        branch: Git branch name (sanitized)

    Returns:
        Dict with status, subtask info, and an optional ``reordered`` flag
        when the input order had to be permuted to satisfy deps.
    """
    state_file = Path(f".map/{branch}/step_state.json")
    state = StepState.load(state_file)

    subtask_ids, validation_error = _normalize_subtask_ids(subtask_ids)
    if validation_error:
        return {"status": "error", "message": validation_error}

    if not subtask_ids:
        return {"status": "error", "message": "At least one subtask ID is required"}

    deps_map = _load_blueprint_deps(branch)
    reordered = False
    original = list(subtask_ids)
    if deps_map:
        sorted_ids, cycle = _topological_sort_subtasks(subtask_ids, deps_map)
        if sorted_ids is None:
            return {
                "status": "error",
                "message": (
                    "Cannot set subtask sequence: " + (cycle or "unknown topology error")
                ),
            }
        if sorted_ids != original:
            reordered = True
        subtask_ids = sorted_ids

    state.subtask_sequence = subtask_ids
    state.current_subtask_id = subtask_ids[0]
    state.subtask_index = 0
    state.save(state_file)

    response: dict[str, object] = {
        "status": "success",
        "subtask_sequence": subtask_ids,
        "current_subtask_id": subtask_ids[0],
    }
    if reordered:
        response["reordered"] = True
        response["original_sequence"] = original
    return response


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
    blueprint_file = plan_dir / "blueprint.json"
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

    plan_content = plan_file.read_text(encoding="utf-8")
    all_subtask_ids = _extract_subtask_ids_from_plan_artifacts(
        plan_content, blueprint_file
    )
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

    blueprint_file = plan_dir / "blueprint.json"

    # Prefer blueprint.json as the machine-readable contract; fall back to
    # task_plan markdown for older or partial artifacts.
    plan_content = plan_file.read_text(encoding="utf-8")
    subtask_ids = _extract_subtask_ids_from_plan_artifacts(
        plan_content, blueprint_file
    )

    if not subtask_ids:
        return {
            "status": "error",
            "message": f"No subtask IDs (ST-XXX) found in {plan_file}.",
        }

    # Extract AAG contracts from step_state.json or blueprint.json if present
    aag_contracts: dict[str, str] = {}
    step_state_file = plan_dir / "step_state.json"
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

    # Auto-compute execution waves so /map-efficient doesn't have to dispatch
    # set_waves manually after every resume. Best-effort: missing or invalid
    # blueprint just leaves execution_waves empty; the sequential fallback in
    # get_next_step / get_wave_step still works.
    waves_status: str = "skipped"
    if blueprint_file.exists():
        try:
            wave_result = set_waves(branch)
            waves_status = wave_result.get("status", "error")
        except Exception:  # noqa: BLE001
            waves_status = "error"

    briefing = get_resume_briefing(branch)

    return {
        "status": "success",
        "message": "Resumed from /map-plan. Skipped DECOMPOSE, INIT_PLAN, REVIEW_PLAN, CHOOSE_MODE. Mode: batch.",
        "subtask_sequence": subtask_ids,
        "current_subtask_id": subtask_ids[0],
        "aag_contracts_found": len(aag_contracts),
        "next_phase": "INIT_STATE",
        "waves_computed": waves_status,
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
    blueprint_file = plan_dir / "blueprint.json"

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
        ids = _extract_subtask_ids_from_plan_artifacts(content, blueprint_file)
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
    blueprint_file = plan_dir / "blueprint.json"

    if not plan_file.exists():
        return {
            "status": "error",
            "message": f"No plan found at {plan_file}. Run /map-plan first.",
        }

    plan_content = plan_file.read_text(encoding="utf-8")
    all_subtask_ids = _extract_subtask_ids_from_plan_artifacts(
        plan_content, blueprint_file
    )

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


def _emit_context_budget_warning(branch: str, transcript_path: str | None) -> None:
    """Print a /compact recommendation to stderr when the budget is crossed.

    Provider-agnostic: works for any caller that can supply ``transcript_path``
    (Claude Code via env, Codex via CLI flag, future providers similarly).
    Designed to fail closed and never raise — orchestrator dispatch must not
    be blocked by a missing transcript or a missing mapify_cli install.
    """
    if not transcript_path:
        return
    path = Path(transcript_path)
    if not path.is_file():
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    policy = _map_config_str(project_dir, "compression_policy", "never")
    configured_threshold = _map_config_int(
        project_dir, "compression_threshold_tokens", 120_000
    )
    threshold = _effective_compression_threshold(
        policy, configured_threshold
    )
    if threshold is None:
        return

    # Same cooldown semantic as context-meter.py: skip if a compaction
    # marker has been touched in the last 5 minutes.
    marker = project_dir / ".map" / branch / "last-compact.marker"
    if marker.is_file():
        try:
            if (time.time() - marker.stat().st_mtime) < 5 * 60:
                return
        except OSError:
            pass

    used = _count_last_turn_tokens(path)
    if not _should_nudge(used, threshold):
        return

    message = _format_compact_instruction(
        used=used,
        threshold=threshold,
        focus=_map_config_str(project_dir, "compression_focus", ""),
    )

    # Offload large tool-result bodies before the (recommended) compaction drops
    # them, then point the operator/agent at the sidecars (#232). Provider-
    # agnostic: reuses the same transcript this warning already read. Lazy import
    # with graceful fallback — never block the warning on a missing mapify_cli.
    branch_dir = project_dir / ".map" / branch
    try:
        from mapify_cli.tool_output_offload import (
            offload_transcript_tool_outputs,
            recovery_pointer_text,
        )

        offload_transcript_tool_outputs(path, branch_dir)
        pointer = recovery_pointer_text(branch, branch_dir)
        if pointer:
            message = f"{message}\n\n{pointer}"
    except Exception:  # noqa: BLE001, S110 — warning must never raise
        pass

    # stderr keeps stdout clean for JSON consumers (the orchestrator's
    # contract is JSON-on-stdout for every command).
    print(message, file=sys.stderr)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MAP Workflow State Machine Orchestrator"
    )
    parser.add_argument(
        "command",
        choices=[
            "get_next_step",
            "peek_current_step",
            "validate_step",
            "initialize",
            "set_plan_approved",
            "restore_deferred_yagni",
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
            "select_execution_strategy",
            "resume_single_subtask",
            "get_plan_progress",
            "monitor_failed",
            "wave_monitor_failed",
            "defer_flaky_subtask",
            "reopen_for_fixes",
            "mark_workflow_complete",
            "mark_subtask_complete",
            "record_subtask_result",
            "backfill_subtask_ids",
            "finalize_plan",
            "archive",
            "abandon",
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
    parser.add_argument(
        "--reason",
        help="Free-form reason (e.g. for mark_subtask_complete no-op records)",
    )
    parser.add_argument(
        "--files",
        help="Comma-separated list of files (for record_subtask_result)",
    )
    parser.add_argument(
        "--summary",
        help="One-line summary (for record_subtask_result)",
    )
    parser.add_argument(
        "--commit-sha",
        dest="commit_sha",
        help="Commit SHA (for record_subtask_result / defer_flaky_subtask)",
    )
    parser.add_argument(
        "--check-id",
        dest="check_id",
        help="Flaky check id (for defer_flaky_subtask)",
    )
    parser.add_argument(
        "--flaky-triage-path",
        dest="flaky_triage_path",
        help=(
            "Optional flaky_test_triage.json path (for defer_flaky_subtask). "
            "Defaults to .map/<branch>/flaky_test_triage.json."
        ),
    )
    parser.add_argument(
        "--recommendation",
        help=(
            "Monitor recommendation (for validate_step 2.4). Values "
            "revise|block|needs_investigation make validate_step return "
            "valid=false even when the step would otherwise close. "
            "Closes the 'Monitor says needs_revision but skill called "
            "validate_step without surfacing it' footgun. Optional — "
            "back-compat callers that omit it get legacy behavior."
        ),
    )
    parser.add_argument(
        "--monitor-envelope",
        dest="monitor_envelope",
        help=(
            "Path to Monitor's JSON response (for validate_step 2.4). "
            "When provided, the orchestrator validates the envelope "
            "(parses as JSON, has valid/summary/issues, ends with `}`) "
            "before closing the step. Use `-` to read from stdin."
        ),
    )
    parser.add_argument(
        "--disposition",
        help=(
            "Non-binary Monitor disposition (for validate_step 2.4). "
            "Currently only 'deferred_nondeterministic': routes a confirmed "
            "flaky check to deferral instead of a hard-stop retry. Requires "
            "--check-id and --monitor-envelope, and a validated "
            "flaky_test_triage sidecar with mixed pass/fail evidence. A "
            "deferred run is non-green (valid:false + deferred:true), not a "
            "clean pass."
        ),
    )
    parser.add_argument(
        "--kind",
        help=(
            "Subtask completion kind (for mark_subtask_complete): one of "
            "done|noop|deferred|stub|prior_pr. Default noop preserves "
            "backward compatibility with callers that don't pass it."
        ),
    )
    parser.add_argument(
        "--subtask-id",
        dest="subtask_id",
        help=(
            "Optional ST-NNN id for restore_deferred_yagni. When omitted, "
            "the next available ST-NNN is assigned."
        ),
    )
    parser.add_argument(
        "--mechanical",
        action="store_true",
        help=(
            "Shorthand for mark_subtask_complete deterministic-edit "
            "short-circuit (skip research-agent for trivial subtasks)."
        ),
    )
    parser.add_argument(
        "--transcript-path",
        default=os.environ.get("MAPIFY_TRANSCRIPT_PATH"),
        help=(
            "Optional path to the LLM transcript JSONL. When provided, the "
            "orchestrator emits a /compact recommendation to stderr if the "
            "compression policy threshold is crossed. Falls back to env "
            "MAPIFY_TRANSCRIPT_PATH."
        ),
    )

    args = parser.parse_args()

    # Resolve the project root before any state lookup or branch detection.
    # Priority (highest first):
    #   1. CLAUDE_PROJECT_DIR env var (explicit operator intent)
    #   2. git rev-parse --show-toplevel from the *caller's* cwd (handles
    #      git worktrees: the worktree root is the correct anchor, not the
    #      main clone where the script file lives — issue #328)
    #   3. Path(__file__).resolve().parents[2] — script-anchored fallback
    #      (legacy behaviour for the normal case where the caller's cwd is
    #      not a git repo, or git is unavailable)
    import subprocess as _sp

    script_anchored_root = Path(__file__).resolve().parents[2]
    caller_cwd = Path.cwd()
    project_root: Path | None = None

    # 1. CLAUDE_PROJECT_DIR
    env_project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env_project_dir:
        try:
            candidate = Path(env_project_dir).resolve()
            if candidate.is_dir():
                project_root = candidate
            else:
                print(
                    f"WARNING: CLAUDE_PROJECT_DIR={env_project_dir!r} is not a "
                    "directory; falling back to git/script-anchored root resolution.",
                    file=sys.stderr,
                )
        except OSError:
            pass

    # 2. git toplevel from the caller's cwd
    if project_root is None:
        try:
            _git = _sp.run(
                ["git", "-C", str(caller_cwd), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if _git.returncode == 0:
                project_root = Path(_git.stdout.strip()).resolve()
        except Exception:  # noqa: BLE001, S110 — best-effort git detection
            pass

    # 3. Script-anchored fallback
    if project_root is None:
        project_root = script_anchored_root

    # Inform (never block) when operating from a different root than where
    # the script file lives — expected and correct for git worktrees.
    if project_root != script_anchored_root:
        print(
            f"INFO: orchestrator resolved project root to {project_root} "
            f"(script lives in {script_anchored_root}). "
            "Operating on the resolved root — expected for git worktrees.",
            file=sys.stderr,
        )

    os.chdir(project_root)

    # Get branch. ``--branch`` arrives unsanitized from the CLI; route it
    # through the same sanitiser used by ``get_branch_name()`` so the value
    # cannot escape the ``.map/<branch>/`` directory via ``..`` or differ
    # from the auto-detected directory for the same logical branch
    # (``feature/foo`` vs ``feature-foo``).
    branch = sanitize_branch_name(args.branch) if args.branch else get_branch_name()

    # Provider-agnostic context-budget warning. No-op when no transcript is
    # available (Codex without explicit --transcript-path, etc.) or when the
    # mapify_cli package is not importable from this script's environment.
    _emit_context_budget_warning(branch, args.transcript_path)

    try:
        if args.command == "get_next_step":
            result = get_next_step(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "peek_current_step":
            result = peek_current_step(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "validate_step":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "step_id required for validate_step"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            # `--recommendation <verdict>` enforces the Monitor verdict
            # contract on the 2.4 close: revise/block/needs_investigation
            # makes validate_step fail. Registered as a real argparse
            # option above so `--recommendation proceed` is no longer
            # rejected with "unrecognized arguments" (regression: the
            # earlier extras-scan implementation was bypassed by
            # argparse's strict-mode rejection of unknown -- flags).
            # We also accept the legacy extras placement for backward
            # compat with callers stuck on the old scrape pattern.
            recommendation_arg: str | None = args.recommendation
            if recommendation_arg is None:
                extras = list(args.extra_args or [])
                if "--recommendation" in extras:
                    rec_idx = extras.index("--recommendation")
                    if rec_idx + 1 < len(extras):
                        recommendation_arg = extras[rec_idx + 1]
            # --monitor-envelope <path>: validate the envelope before
            # closing 2.4. Path "-" reads from stdin so shell pipelines
            # can stream Monitor's response without an intermediate file.
            monitor_envelope_text: str | None = None
            if args.monitor_envelope:
                if args.monitor_envelope == "-":
                    monitor_envelope_text = sys.stdin.read()
                else:
                    try:
                        monitor_envelope_text = Path(args.monitor_envelope).read_text(
                            encoding="utf-8"
                        )
                    except OSError as exc:
                        print(
                            json.dumps({
                                "error": f"--monitor-envelope read failed: {exc}",
                            }),
                            file=sys.stderr,
                        )
                        sys.exit(1)
            # --disposition routes a confirmed-flaky 2.4 close to deferral
            # (the third Monitor outcome). It reuses --check-id/--files/
            # --summary/--commit-sha (already parsed for defer_flaky_subtask).
            validate_files_list: list[str] | None = None
            if args.files:
                validate_files_list = [
                    chunk.strip()
                    for chunk in re.split(r"[,\s]+", args.files)
                    if chunk.strip()
                ]
            result = validate_step(
                args.task_or_step,
                branch,
                recommendation=recommendation_arg,
                monitor_envelope=monitor_envelope_text,
                disposition=args.disposition,
                check_id=args.check_id,
                files_changed=validate_files_list,
                summary=args.summary or "",
                commit_sha=args.commit_sha,
            )
            print(json.dumps(result, indent=2))
            # A deferral is a deliberate non-green-but-not-failed routing
            # outcome (valid:false + deferred:true) — exit 0 so the skill does
            # NOT treat it as a hard-stop. Only a true invalid verdict exits 1.
            if not result.get("valid", False) and not result.get("deferred"):
                sys.exit(1)

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

        elif args.command == "restore_deferred_yagni":
            value = args.task_or_step
            if value is None:
                print(
                    json.dumps({"error": "YG-NNN id required for restore_deferred_yagni"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            result = restore_deferred_yagni(value, branch, args.subtask_id)
            print(json.dumps(result, indent=2))
            if result.get("status") != "success":
                sys.exit(1)

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

        elif args.command == "select_execution_strategy":
            result = select_execution_strategy(branch)
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

        elif args.command == "defer_flaky_subtask":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "subtask_id required for defer_flaky_subtask"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            if not args.check_id:
                print(
                    json.dumps({"error": "--check-id required for defer_flaky_subtask"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            files_list = []
            if args.files:
                for chunk in re.split(r"[,\s]+", args.files):
                    chunk = chunk.strip()
                    if chunk:
                        files_list.append(chunk)
            result = defer_flaky_subtask(
                args.task_or_step,
                branch,
                args.check_id,
                triage_path=args.flaky_triage_path or "",
                files_changed=files_list,
                summary=args.summary or "",
                commit_sha=args.commit_sha,
            )
            print(json.dumps(result, indent=2))
            if result.get("status") != "success":
                sys.exit(1)

        elif args.command == "reopen_for_fixes":
            feedback = args.feedback or ""
            result = reopen_for_fixes(branch, feedback)
            print(json.dumps(result, indent=2))

        elif args.command == "mark_workflow_complete":
            result = mark_workflow_complete(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "archive":
            result = archive_completed_workflow(branch)
            print(json.dumps(result, indent=2))
            # Exit nonzero on a refusal (in-flight run) so `set -e` / exit-code
            # callers detect it. A "noop" (nothing to archive) is not a failure.
            if result.get("status") == "error":
                sys.exit(1)

        elif args.command == "abandon":
            result = abandon_workflow(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "mark_subtask_complete":
            if not args.task_or_step:
                print(
                    json.dumps({"error": "subtask_id required for mark_subtask_complete"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            # `--mechanical` is shorthand for a deterministic short-circuit
            # without the full research→actor→monitor cycle for trivial
            # subtasks (DB schema bump, dependency pin, etc.) where deep
            # research is overhead. The reason text auto-flags the path
            # for audit.
            # Real argparse options take precedence over the legacy
            # extras-scan (same reason as --recommendation above:
            # extras-scan never sees -- flags in argparse strict mode).
            extra = list(args.extra_args or [])
            mechanical = bool(args.mechanical) or ("--mechanical" in extra)
            # `--kind <done|noop|deferred|stub|prior_pr>` classifies the
            # short-circuit so audits can group by intent. Default falls
            # back to noop for backward compat with existing callers.
            kind_arg: str | None = args.kind
            if kind_arg is None and "--kind" in extra:
                kind_idx = extra.index("--kind")
                if kind_idx + 1 < len(extra):
                    kind_arg = extra[kind_idx + 1]
            if args.reason:
                reason = args.reason
            elif mechanical:
                reason = (
                    "mechanical subtask short-circuit (skip research-agent): "
                    "deterministic edit, no design surface to explore"
                )
            else:
                reason = "no-op"
            result = mark_subtask_complete(
                args.task_or_step, branch, reason, kind=kind_arg
            )
            if mechanical:
                result["mechanical"] = True
            print(json.dumps(result, indent=2))
            if isinstance(result, dict) and result.get("status") == "error":
                sys.exit(1)

        elif args.command == "record_subtask_result":
            # CLI: record_subtask_result <ST-ID> <status> [--files a.py,b.py]
            # [--summary "..."] [--commit-sha SHA]
            if not args.task_or_step:
                print(
                    json.dumps({"error": "subtask_id required"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            extra_args = list(args.extra_args or [])
            if not extra_args:
                print(
                    json.dumps({"error": "status required (valid|invalid|no-op)"}),
                    file=sys.stderr,
                )
                sys.exit(1)
            status_value = extra_args[0]
            # Accept BOTH "--files a.py,b.py" (legacy/documented) AND
            # "--files 'a.py b.py'" (intuitive). The space form was a
            # silent footgun: pre-2026-05-26 the whole string was
            # treated as one path, producing "file does not exist"
            # warnings on every multi-file subtask whose operator
            # forgot the comma syntax.
            files_list = []
            if args.files:
                for chunk in re.split(r"[,\s]+", args.files):
                    chunk = chunk.strip()
                    if chunk:
                        files_list.append(chunk)
            result = record_subtask_result(
                args.task_or_step,
                branch,
                files_changed=files_list,
                status=status_value,
                summary=args.summary or "",
                commit_sha=args.commit_sha,
            )
            print(json.dumps(result, indent=2))

        elif args.command == "backfill_subtask_ids":
            result = backfill_subtask_ids(branch)
            print(json.dumps(result, indent=2))

        elif args.command == "finalize_plan":
            result = finalize_plan(branch)
            print(json.dumps(result, indent=2))

    except Exception as e:  # noqa: BLE001 — CLI top-level error handler
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
