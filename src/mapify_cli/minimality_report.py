"""Minimality rollout telemetry for the Phase 3 default flip gate."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mapify_cli.config.project_config import VALID_MINIMALITY, load_map_config

OPT_IN_MINIMALITY_LEVELS = frozenset({"lite", "full", "ultra"})
MANUAL_REVIEW_CHECKLIST = (
    ("Compare each opt-in run against the original user request for dropped "
    "explicit or implied requirements."),
    "Inspect simplifications for terse or cryptic code that hurts maintainability.",
    ("Confirm Actor retries addressed only BLOCKER feedback, not NON-BLOCKING "
    "scope expansion."),
    "Verify map:simplification markers name a real ceiling and safe upgrade path.",
)


def _utc_timestamp() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _sum_int_values(value: object) -> int:
    return sum(_as_int(item) for item in _as_mapping(value).values())


def _derive_terminal_status(
    run_health: Mapping[str, object], step_state: Mapping[str, object]
) -> str:
    status = run_health.get("terminal_status")
    if isinstance(status, str) and status:
        return status
    if step_state.get("workflow_status") == "WORKFLOW_COMPLETE":
        return "complete"
    if step_state.get("current_step_phase") == "COMPLETE":
        return "complete"
    return "pending"


def _branch_minimality(
    run_health: Mapping[str, object], current_config_minimality: str
) -> tuple[str, str]:
    level = run_health.get("minimality")
    if isinstance(level, str) and level in VALID_MINIMALITY:
        return level, "run_health_report"
    return current_config_minimality, "current_config"


def _blueprint_body(payload: Mapping[str, object]) -> Mapping[str, object]:
    body = payload.get("blueprint")
    return body if isinstance(body, Mapping) else payload


def _blueprint_counts(blueprint_payload: Mapping[str, object]) -> dict[str, int]:
    body = _blueprint_body(blueprint_payload)
    subtasks = _as_list(body.get("subtasks"))
    deferred_yagni = _as_list(body.get("deferred_yagni"))
    restored_yagni_count = 0
    active_pruneable_count = 0

    for item in subtasks:
        if not isinstance(item, Mapping):
            continue
        if isinstance(item.get("restored_from_deferred_yagni"), str):
            restored_yagni_count += 1
        if item.get("pruneable") is True:
            active_pruneable_count += 1

    return {
        "deferred_yagni_count": len(deferred_yagni),
        "restored_yagni_count": restored_yagni_count,
        "active_pruneable_count": active_pruneable_count,
        "total_yagni_recommendations": len(deferred_yagni) + restored_yagni_count,
    }


def _branch_sample(
    branch_dir: Path, current_config_minimality: str
) -> dict[str, object] | None:
    run_health_path = branch_dir / "run_health_report.json"
    step_state_path = branch_dir / "step_state.json"
    blueprint_path = branch_dir / "blueprint.json"

    if not (
        run_health_path.is_file()
        or step_state_path.is_file()
        or blueprint_path.is_file()
    ):
        return None

    run_health = _read_json_object(run_health_path)
    step_state = _read_json_object(step_state_path)
    blueprint = _read_json_object(blueprint_path)
    signals = _as_mapping(run_health.get("resiliency_signals"))
    if not signals:
        signals = step_state

    minimality, minimality_source = _branch_minimality(
        run_health, current_config_minimality
    )
    retry_events = _as_int(signals.get("retry_count")) + _sum_int_values(
        signals.get("subtask_retry_counts")
    )
    counts = _blueprint_counts(blueprint)
    total_recommendations = counts["total_yagni_recommendations"]
    reversal_rate = (
        counts["restored_yagni_count"] / total_recommendations
        if total_recommendations
        else None
    )

    return {
        "branch": branch_dir.name,
        "workflow": str(run_health.get("workflow") or step_state.get("workflow") or ""),
        "terminal_status": _derive_terminal_status(run_health, step_state),
        "minimality": minimality,
        "minimality_source": minimality_source,
        "has_run_health_report": bool(run_health),
        "retry_events": retry_events,
        "max_subtask_retry_count": _as_int(signals.get("max_subtask_retry_count")),
        "guard_rework_events": _sum_int_values(signals.get("guard_rework_counts")),
        "deferred_yagni_count": counts["deferred_yagni_count"],
        "restored_yagni_count": counts["restored_yagni_count"],
        "active_pruneable_count": counts["active_pruneable_count"],
        "total_yagni_recommendations": total_recommendations,
        "user_reversal_rate": reversal_rate,
    }


def _branch_dirs(map_dir: Path) -> list[Path]:
    if not map_dir.is_dir():
        return []
    return sorted(
        path for path in map_dir.iterdir() if path.is_dir() and path.name != "scripts"
    )


def _average(samples: Sequence[Mapping[str, object]], key: str) -> float:
    if not samples:
        return 0.0
    return sum(_as_int(sample.get(key)) for sample in samples) / len(samples)


def _summarize(
    samples: list[dict[str, object]], min_complete_runs: int
) -> dict[str, object]:
    complete = [
        sample for sample in samples if sample.get("terminal_status") == "complete"
    ]
    historical = [
        sample
        for sample in complete
        if sample.get("minimality_source") == "run_health_report"
    ]
    complete_off = [
        sample for sample in historical if sample.get("minimality") == "off"
    ]
    complete_opt_in = [
        sample
        for sample in historical
        if sample.get("minimality") in OPT_IN_MINIMALITY_LEVELS
    ]
    inferred_level_samples = [
        sample
        for sample in complete
        if sample.get("minimality_source") != "run_health_report"
    ]
    complete_off_branches = [str(sample.get("branch", "")) for sample in complete_off]
    complete_opt_in_branches = [
        str(sample.get("branch", "")) for sample in complete_opt_in
    ]
    missing_historical_minimality_branches = [
        str(sample.get("branch", "")) for sample in inferred_level_samples
    ]

    restored_total = sum(
        _as_int(sample.get("restored_yagni_count")) for sample in complete_opt_in
    )
    recommendation_total = sum(
        _as_int(sample.get("total_yagni_recommendations")) for sample in complete_opt_in
    )
    reversal_rate = (
        restored_total / recommendation_total if recommendation_total else None
    )
    avg_retry_off = _average(complete_off, "retry_events")
    avg_retry_opt_in = _average(complete_opt_in, "retry_events")
    avg_guard_off = _average(complete_off, "guard_rework_events")
    avg_guard_opt_in = _average(complete_opt_in, "guard_rework_events")
    opt_in_gap = max(0, min_complete_runs - len(complete_opt_in))
    off_gap = max(0, min_complete_runs - len(complete_off))

    reasons: list[str] = []
    next_actions: list[str] = []
    decision = "candidate"

    if not samples:
        decision = "insufficient_data"
        reasons.append("No branch workspaces found under .map/.")
        next_actions.append(
            "Run MAP workflows with minimality off and opt-in levels so .map/ "
            "contains run-health samples."
        )
    if inferred_level_samples:
        decision = "insufficient_data"
        reasons.append(
            "Some complete reports lack historical minimality; regenerate run_health_report.json with this version."
        )
        next_actions.append(
            "Regenerate complete run_health_report.json files with this mapify "
            "version so each sample records historical minimality."
        )
    if len(complete_opt_in) < min_complete_runs:
        decision = "insufficient_data"
        reasons.append(
            f"Need at least {min_complete_runs} complete opt-in runs; found {len(complete_opt_in)}."
        )
        next_actions.append(
            f"Collect {opt_in_gap} more complete run(s) with minimality lite, "
            "full, or ultra."
        )
    if len(complete_off) < min_complete_runs:
        decision = "insufficient_data"
        reasons.append(
            f"Need at least {min_complete_runs} complete off-baseline runs; found {len(complete_off)}."
        )
        next_actions.append(
            f"Collect {off_gap} more complete baseline run(s) with minimality off."
        )

    if decision == "candidate":
        if reversal_rate is not None and reversal_rate > 0.2:
            decision = "hold"
            reasons.append(
                f"User reversal rate is {reversal_rate:.1%}, above the 20% Phase 4 guardrail."
            )
            next_actions.append(
                "Review restored deferred-YAGNI items and narrow pruning rules "
                "before considering the default flip."
            )
        if avg_retry_opt_in > avg_retry_off:
            decision = "hold"
            reasons.append(
                f"Average retry events regressed ({avg_retry_opt_in:.2f} opt-in vs {avg_retry_off:.2f} off)."
            )
            next_actions.append(
                "Inspect opt-in retry feedback for BLOCKER/NON-BLOCKING "
                "oscillation before collecting more samples."
            )
        if avg_guard_opt_in > avg_guard_off:
            decision = "hold"
            reasons.append(
                f"Average guard rework regressed ({avg_guard_opt_in:.2f} opt-in vs {avg_guard_off:.2f} off)."
            )
            next_actions.append(
                "Inspect guard rework events from opt-in runs and fix the "
                "recurring guard failure before promotion."
            )

    if decision == "candidate":
        reasons.append(
            "Local telemetry is compatible with a Phase 3 default-flip candidate."
        )
        next_actions.append(
            "Sample the candidate opt-in runs for clarity/underscope "
            "regressions before flipping the global default."
        )

    manual_review_required = decision == "candidate"

    return {
        "decision": decision,
        "ready_for_phase3": decision == "candidate",
        "reasons": reasons,
        "next_actions": next_actions,
        "branch_count": len(samples),
        "complete_run_count": len(complete),
        "complete_off_runs": len(complete_off),
        "complete_opt_in_runs": len(complete_opt_in),
        "complete_runs_missing_historical_minimality": len(inferred_level_samples),
        "sample_gaps": {
            "off_baseline_runs": off_gap,
            "opt_in_runs": opt_in_gap,
            "historical_minimality_runs": len(inferred_level_samples),
        },
        "cohort_branches": {
            "off_baseline": complete_off_branches,
            "opt_in": complete_opt_in_branches,
            "missing_historical_minimality": missing_historical_minimality_branches,
        },
        "avg_retry_events_off": avg_retry_off,
        "avg_retry_events_opt_in": avg_retry_opt_in,
        "avg_guard_rework_off": avg_guard_off,
        "avg_guard_rework_opt_in": avg_guard_opt_in,
        "user_reversal_rate": reversal_rate,
        "manual_review_gate": {
            "required": manual_review_required,
            "candidate_branches": [
                str(sample.get("branch", "")) for sample in complete_opt_in
            ],
            "checklist": (
                list(MANUAL_REVIEW_CHECKLIST) if manual_review_required else []
            ),
        },
    }


def build_minimality_rollout_report(
    project_path: Path, min_complete_runs: int = 3
) -> dict[str, Any]:
    """Build a local telemetry report for the minimality Phase 3 gate.

    The report is read-only. It treats run-health reports that carry their own
    ``minimality`` field as historical truth. Older reports are still listed,
    but the Phase 3 decision stays ``insufficient_data`` until enough complete
    off and opt-in runs have historical levels recorded.
    """
    project_root = Path(project_path).resolve()
    current_config_minimality = load_map_config(project_root).minimality
    min_runs = max(1, min_complete_runs)
    samples = [
        sample
        for branch_dir in _branch_dirs(project_root / ".map")
        if (sample := _branch_sample(branch_dir, current_config_minimality)) is not None
    ]

    return {
        "schema_version": "1.0",
        "generated_at": _utc_timestamp(),
        "project_path": str(project_root),
        "current_config_minimality": current_config_minimality,
        "min_complete_runs": min_runs,
        "summary": _summarize(samples, min_runs),
        "branches": samples,
    }
