#!/usr/bin/env python3
"""
MAP Workflow Step Execution Utilities

Provides deterministic step executors for /map-efficient workflow.
These handle the mechanical parts of workflow steps that don't require LLM reasoning.

DESIGN PRINCIPLE:
  Separate deterministic operations (file I/O, state updates) from LLM work.
  Python handles the boring stuff, Claude focuses on creative problem-solving.

USAGE:
  Called by map-efficient.md command to handle:
  - State file updates
  - Plan file parsing/updates
  - Checkpoint validation
  - Progress tracking

FUNCTIONS:
  - update_step_state: Mark step complete in step_state.json
  - update_plan_status: Update subtask status in task_plan.md
  - validate_checkpoint: Check if required steps completed
  - create_xml_packet: Build AI-friendly subtask packet

TESTING:
  python3 -c "from map_step_runner import update_step_state; \\
    update_step_state('ST-001', 'actor', 'ACTOR_CALLED')"
"""

import fnmatch
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, cast

# Keep in sync with workflow-context-injector.py GOAL_HEADING_RE
GOAL_HEADING_RE = r"## (?:Goal|Overview)\n(.*?)(?=\n##|\Z)"


HUMAN_ARTIFACT_DEFAULTS = {
    "qa-001.md": "# QA 001\n\n",
    "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Follow-up\n",
    "verification-summary.md": "# Verification Summary\n\n",
}


KNOWN_ISSUES_DEFAULT: dict[str, list[dict[str, object]]] = {"issues": []}
ACTIVE_ISSUES_DEFAULT: dict[str, object] = {"updated_at": "", "issues": []}

GATE_VERDICTS = {"ready", "needs-revision", "blocked"}
ARTIFACT_STAGE_NAMES = (
    "workflow_fit",
    "spec",
    "plan",
    "test_contract",
    "implementation",
    "review",
    "verification",
    "run_health",
    "learn_handoff",
)
RUN_HEALTH_TERMINAL_STATUSES = {
    "pending",
    "complete",
    "blocked",
    "won't_do",
    "superseded",
}
RUN_HEALTH_REQUIRED_KEYS = {
    "schema_version",
    "generated_at",
    "workflow",
    "branch",
    "terminal_status",
    "completed_step_count",
    "pending_step_count",
    "artifacts",
    "resiliency_signals",
}
RUN_HEALTH_ARTIFACT_KEYS = {
    "step_state",
    "artifact_manifest",
    "verification_summary",
    "qa",
    "pr_draft",
    "review_bundle",
    "learning_handoff",
    "task_plan",
    "blueprint",
    "active_issues",
    "known_issues",
}
RUN_HEALTH_SIGNAL_KEYS = {
    "hook_injection",
    "hook_injection_counts",
    "retry_count",
    "max_retries",
    "subtask_retry_counts",
    "max_subtask_retry_count",
    "guard_rework_counts",
    "predictor_called",
    "predictor_skipped",
    "final_verifier_executed",
}
PRIOR_STAGE_CONSUMPTION_STAGES = {"implementation", "review"}
WORKFLOW_FIT_ROUTES = {
    "direct-edit",
    "map-fast",
    "map-efficient",
    "map-tdd",
    "map-plan",
}
DIFF_SIZE_LEVELS = {"tiny", "small", "medium", "large"}
SUBTASK_CONCERN_TYPES = {
    "api",
    "config",
    "data",
    "docs",
    "infra",
    "observability",
    "refactor",
    "release",
    "runtime",
    "security",
    "tests",
    "ui",
    "mixed",
}
LEARNING_CONSUMPTION_SOURCES = {"auto-handoff", "file-handoff", "inline-summary"}
REVIEW_SECTION_IDS: tuple[str, ...] = ("architecture", "code_quality", "tests", "performance")
REVIEW_VALID_MODES: tuple[str, ...] = ("default", "reverse-sections", "shuffle-sections")
LEARNING_IMMEDIATE_WINDOW_SECONDS = 30 * 60
ACCEPTANCE_TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*-\d+[A-Za-z0-9_-]*)\]")
CONTEXT_BLOCK_DEFAULT_BUDGET_TOKENS = 4_000
CONTEXT_BLOCK_MIN_BUDGET_TOKENS = 128
CONTEXT_BLOCK_BUDGET_ENV = "MAP_CONTEXT_BLOCK_BUDGET_TOKENS"
REVIEW_PROMPT_DEFAULT_BUDGET_TOKENS = 12_000
REVIEW_PROMPT_MIN_BUDGET_TOKENS = 1_024
REVIEW_PROMPT_BUDGET_ENV = "MAP_REVIEW_PROMPT_BUDGET_TOKENS"

try:
    from mapify_cli.token_budget import (
        estimate_tokens as _estimate_tokens,
        truncate_to_token_budget as _truncate_to_token_budget,
    )
except ImportError:
    ESTIMATED_CHARS_PER_TOKEN = 4

    def _estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(
            1,
            (len(text) + ESTIMATED_CHARS_PER_TOKEN - 1) // ESTIMATED_CHARS_PER_TOKEN,
        )

    def _truncate_to_token_budget(
        text: str, budget_tokens: int, suffix: str = "..."
    ) -> str:
        if budget_tokens <= 0 or not text:
            return ""
        if _estimate_tokens(text) <= budget_tokens:
            return text
        char_limit = budget_tokens * ESTIMATED_CHARS_PER_TOKEN
        if char_limit <= len(suffix):
            return suffix[:char_limit]
        cut = text[: char_limit - len(suffix)].rstrip()
        last_space = cut.rfind(" ")
        if last_space > len(cut) // 2:
            cut = cut[:last_space].rstrip()
        return cut + suffix

LEARNING_METRICS_COUNTER_DEFAULTS = {
    "handoff_generated_count": 0,
    "handoff_consumed_count": 0,
    "immediate_learn_count": 0,
    "deferred_learn_count": 0,
    "never_used_handoff_count": 0,
    "manual_summary_count": 0,
    "pending_handoff_count": 0,
    "repeated_violation_scan_count": 0,
    "repeated_violation_match_count": 0,
}
LEARNING_MATCH_STOPWORDS = {
    "after",
    "always",
    "before",
    "branch",
    "because",
    "between",
    "could",
    "failed",
    "failure",
    "false",
    "file",
    "files",
    "from",
    "have",
    "into",
    "issue",
    "just",
    "later",
    "must",
    "needs",
    "none",
    "only",
    "path",
    "paths",
    "return",
    "should",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "this",
    "true",
    "when",
    "with",
    "workflow",
}
LEARNED_RULE_BULLET_RE = re.compile(
    r"^- \*\*(?P<title>.+?)\*\* \((?P<date>\d{4}-\d{2}-\d{2})\): (?P<body>.+?)(?: \[workflow: .+?\])?$"
)
SECTION_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")

# Module-level singleton kept for in-process pytest paths only. The durable staging
# path is the file ``.map/<branch>/pending-ordering.json`` — see
# record_review_ordering() / create_review_bundle() — because the SKILL.md workflow
# calls them across separate ``python3 ...`` subprocesses, and a module-level dict
# evaporates between processes. The in-memory singleton supplements the file for
# tests that mutate it directly with ``map_step_runner._PENDING_REVIEW_ORDERING = ...``.
_PENDING_REVIEW_ORDERING: dict[str, object] | None = None

PENDING_ORDERING_FILENAME = "pending-ordering.json"
PATH_HINT_RE = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)(?::\d+)?"
)
TOKEN_RE = re.compile(r"[a-z0-9]{4,}")


def _utc_timestamp() -> str:
    """Return an unambiguous RFC3339 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_boolish(value: object) -> bool:
    """Convert common truthy/falsy string forms to bool."""
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y"}


def _write_json_file(path: Path, payload: dict) -> None:
    """Atomically write JSON payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    tmp_file.replace(path)


def _read_json_file(path: Path) -> Optional[dict[str, object]]:
    """Read a JSON object from disk, returning None on invalid or missing files."""
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def artifact_manifest_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped artifact manifest path."""
    return get_branch_dir(branch) / "artifact_manifest.json"


def learning_metrics_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped learning metrics path."""
    return get_branch_dir(branch) / "learning-metrics.json"


def _default_stage_payload() -> dict[str, object]:
    """Return an empty stage payload for artifact_manifest.json."""
    return {
        "status": "not_started",
        "updated_at": "",
        "artifacts": [],
        "metadata": {},
    }


def default_artifact_manifest(branch: str) -> dict[str, object]:
    """Return a fresh artifact manifest for a branch."""
    return {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "stages": {stage: _default_stage_payload() for stage in ARTIFACT_STAGE_NAMES},
    }


def load_artifact_manifest(branch: Optional[str] = None) -> dict[str, object]:
    """Load artifact_manifest.json, filling missing stages with defaults."""
    branch_name = branch or get_branch_name()
    manifest_path = artifact_manifest_path(branch_name)
    manifest = default_artifact_manifest(branch_name)

    if not manifest_path.exists():
        return manifest

    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return manifest

    if isinstance(loaded, dict):
        manifest.update(
            {
                "schema_version": loaded.get("schema_version", manifest["schema_version"]),
                "branch": branch_name,
                "updated_at": loaded.get("updated_at", manifest["updated_at"]),
            }
        )
        loaded_stages = loaded.get("stages", {})
        if isinstance(loaded_stages, dict):
            stages = cast(dict[str, dict[str, object]], manifest["stages"])
            for stage in ARTIFACT_STAGE_NAMES:
                stage_payload = loaded_stages.get(stage, _default_stage_payload())
                if isinstance(stage_payload, dict):
                    stages[stage] = {
                        "status": stage_payload.get("status", "not_started"),
                        "updated_at": stage_payload.get("updated_at", ""),
                        "artifacts": stage_payload.get("artifacts", []),
                        "metadata": stage_payload.get("metadata", {}),
                    }

    return manifest


def save_artifact_manifest(
    manifest: dict[str, object], branch: Optional[str] = None
) -> dict[str, object]:
    """Persist artifact_manifest.json and return status metadata."""
    branch_name = branch or get_branch_name()
    manifest["branch"] = branch_name
    manifest["updated_at"] = _utc_timestamp()
    path = artifact_manifest_path(branch_name)
    _write_json_file(path, manifest)
    return {"status": "success", "path": str(path), "manifest": manifest}


def _set_manifest_stage(
    manifest: dict[str, object],
    stage: str,
    status: str,
    *,
    artifacts: Optional[list[dict[str, str]]] = None,
    metadata: Optional[dict[str, object]] = None,
) -> None:
    """Update one stage entry inside a manifest payload."""
    if stage not in ARTIFACT_STAGE_NAMES:
        raise ValueError(f"Unknown artifact stage: {stage}")
    stages = manifest.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise ValueError("artifact manifest stages payload is invalid")
    stages[stage] = {
        "status": status,
        "updated_at": _utc_timestamp(),
        "artifacts": artifacts or [],
        "metadata": metadata or {},
    }


def _artifact_ref(path: Path, kind: str) -> dict[str, str]:
    """Create a manifest artifact reference payload."""
    return {"path": str(path), "kind": kind}


def _prior_stage_file_entry(
    key: str,
    label: str,
    path: Path,
    *,
    required: bool = True,
) -> dict[str, object]:
    """Return one prior-stage artifact consumption entry."""
    present = path.exists() and path.is_file()
    return {
        "key": key,
        "label": label,
        "kind": "file",
        "path": str(path),
        "required": required,
        "present": present,
        "consumed": present,
        "count": 1 if present else 0,
        "reason": "" if present else f"missing required artifact: {path}",
    }


def _prior_stage_glob_entry(
    key: str,
    label: str,
    branch_dir: Path,
    pattern: str,
    *,
    required: bool = True,
) -> dict[str, object]:
    """Return one prior-stage glob artifact consumption entry."""
    try:
        paths = sorted(
            path for path in branch_dir.glob(pattern) if path.exists() and path.is_file()
        )
    except OSError:
        paths = []
    present = bool(paths)
    return {
        "key": key,
        "label": label,
        "kind": "glob",
        "path": str(branch_dir / pattern),
        "paths": [str(path) for path in paths],
        "required": required,
        "present": present,
        "consumed": present,
        "count": len(paths),
        "reason": "" if present else f"missing required artifact matching: {branch_dir / pattern}",
    }


def _prior_stage_diff_entry(
    code_state: Mapping[str, object], *, required: bool = True
) -> dict[str, object]:
    """Return the current diff snapshot as a prior-stage consumption entry."""
    files_changed = code_state.get("files_changed")
    file_count = len(files_changed) if isinstance(files_changed, list) else 0
    diff_stat = code_state.get("diff_stat")
    present = code_state.get("status") == "success" and (file_count > 0 or bool(diff_stat))
    return {
        "key": "code_diff",
        "label": "code diff",
        "kind": "git-diff",
        "path": "git diff --stat HEAD",
        "required": required,
        "present": present,
        "consumed": present,
        "count": file_count,
        "reason": "" if present else "missing code diff snapshot; no changed files were visible against HEAD",
    }


def build_prior_stage_consumption_report(
    stage: str = "review",
    branch: Optional[str] = None,
    code_state: Optional[Mapping[str, object]] = None,
) -> dict[str, object]:
    """Report whether closeout consumed the prior-stage artifacts it depends on."""
    normalized_stage = (stage or "review").strip().lower().replace("-", "_")
    if normalized_stage not in PRIOR_STAGE_CONSUMPTION_STAGES:
        return {
            "status": "error",
            "valid": False,
            "stage": normalized_stage,
            "branch": branch or get_branch_name(),
            "errors": [
                "stage must be one of: "
                + ", ".join(sorted(PRIOR_STAGE_CONSUMPTION_STAGES))
            ],
            "required_artifacts": [],
            "summary": {"required": 0, "consumed": 0, "missing": 0},
        }

    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    current_code_state = code_state or snapshot_code_state(branch_name)
    required_artifacts = [
        _prior_stage_file_entry(
            "spec", "specification", branch_dir / f"spec_{branch_name}.md"
        ),
        _prior_stage_file_entry(
            "task_plan", "task plan", branch_dir / f"task_plan_{branch_name}.md"
        ),
        _prior_stage_file_entry("blueprint", "blueprint", branch_dir / "blueprint.json"),
        _prior_stage_glob_entry(
            "test_contract", "test contract", branch_dir, "test_contract_*.md"
        ),
        _prior_stage_diff_entry(current_code_state),
    ]
    if normalized_stage == "review":
        required_artifacts.append(
            _prior_stage_file_entry(
                "verification_summary",
                "verification summary",
                branch_dir / "verification-summary.md",
            )
        )

    missing = [
        item for item in required_artifacts if item.get("required") and not item.get("consumed")
    ]
    errors = [str(item.get("reason")) for item in missing if item.get("reason")]
    summary = {
        "required": sum(1 for item in required_artifacts if item.get("required")),
        "consumed": sum(
            1
            for item in required_artifacts
            if item.get("required") and item.get("consumed")
        ),
        "missing": len(missing),
    }
    return {
        "status": "ready" if not missing else "blocked",
        "valid": not missing,
        "stage": normalized_stage,
        "branch": branch_name,
        "required_artifacts": required_artifacts,
        "summary": summary,
        "errors": errors,
    }


def _render_prior_stage_consumption_markdown(report: Mapping[str, object]) -> str:
    """Render prior-stage consumption as reviewer-readable Markdown."""
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    required = summary.get("required", 0) if isinstance(summary, Mapping) else 0
    consumed = summary.get("consumed", 0) if isinstance(summary, Mapping) else 0
    missing = summary.get("missing", 0) if isinstance(summary, Mapping) else 0
    lines = [
        "## Prior-Stage Consumption",
        f"- Stage: {report.get('stage') or 'unknown'}",
        f"- Status: {report.get('status') or 'unknown'}",
        f"- Consumed required inputs: {consumed}/{required}",
    ]
    for item in report.get("required_artifacts", []):
        if not isinstance(item, Mapping):
            continue
        status = "consumed" if item.get("consumed") else "missing"
        label = item.get("label") or item.get("key") or "artifact"
        path = item.get("path") or ""
        count = item.get("count", 0)
        reason = item.get("reason") or ""
        detail = f"; {reason}" if reason else ""
        lines.append(f"- [{status}] {label}: `{path}` ({count}){detail}")
    if missing:
        lines.append("- Action: create or refresh the missing prior-stage artifacts before claiming the workflow is ready.")
    return "\n".join(lines) + "\n"


def _metrics_event_log_path() -> Path:
    """Return the append-only metrics JSONL path."""
    return Path(".claude/metrics/agent_metrics.jsonl")


def _append_metrics_event(event: dict[str, object]) -> None:
    """Append one metrics event to .claude/metrics/agent_metrics.jsonl."""
    path = _metrics_event_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def _parse_rfc3339_timestamp(value: object) -> Optional[datetime]:
    """Parse RFC3339 timestamps, accepting a trailing Z."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _default_learning_metrics(branch: str) -> dict[str, object]:
    """Return an empty learning metrics payload for a branch."""
    return {
        "schema_version": "1.0",
        "branch": branch,
        "updated_at": _utc_timestamp(),
        "counters": dict(LEARNING_METRICS_COUNTER_DEFAULTS),
        "current_handoff": None,
        "events": [],
    }


def _refresh_learning_metrics_counters(metrics: dict[str, object]) -> None:
    """Recompute derived counters for the learning metrics payload."""
    counters = metrics.setdefault("counters", {})
    if not isinstance(counters, dict):
        counters = {}
        metrics["counters"] = counters
    for key, value in LEARNING_METRICS_COUNTER_DEFAULTS.items():
        counters[key] = int(counters.get(key, value) or 0)

    current_handoff = metrics.get("current_handoff")
    counters["pending_handoff_count"] = (
        1
        if isinstance(current_handoff, dict) and not current_handoff.get("consumed_at")
        else 0
    )


def load_learning_metrics(branch: Optional[str] = None) -> dict[str, object]:
    """Load branch-scoped learning metrics, filling missing defaults."""
    branch_name = branch or get_branch_name()
    metrics_path = learning_metrics_path(branch_name)
    metrics = _default_learning_metrics(branch_name)

    if metrics_path.exists():
        try:
            loaded = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}

        if isinstance(loaded, dict):
            metrics["updated_at"] = loaded.get("updated_at", metrics["updated_at"])
            counters = loaded.get("counters")
            if isinstance(counters, dict):
                cast(dict[str, int], metrics["counters"]).update(counters)
            current_handoff = loaded.get("current_handoff")
            if isinstance(current_handoff, dict):
                metrics["current_handoff"] = current_handoff
            events = loaded.get("events")
            if isinstance(events, list):
                metrics["events"] = [item for item in events if isinstance(item, dict)][
                    -25:
                ]

    _refresh_learning_metrics_counters(metrics)
    return metrics


def save_learning_metrics(
    metrics: dict[str, object], branch: Optional[str] = None
) -> dict[str, object]:
    """Persist learning metrics and return status metadata."""
    branch_name = branch or get_branch_name()
    metrics["branch"] = branch_name
    metrics["updated_at"] = _utc_timestamp()
    _refresh_learning_metrics_counters(metrics)
    path = learning_metrics_path(branch_name)
    _write_json_file(path, metrics)
    return {"status": "success", "path": str(path), "metrics": metrics}


def _append_learning_metrics_event(
    metrics: dict[str, object], event: dict[str, object]
) -> None:
    """Append a learning metrics event to the branch summary payload."""
    events = metrics.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        metrics["events"] = events
    events.append(event)
    del events[:-25]


def _classify_learning_consumption_mode(
    generated_at: object, consumed_at: object
) -> str:
    """Classify a learn invocation as immediate or deferred based on handoff age."""
    generated_dt = _parse_rfc3339_timestamp(generated_at)
    consumed_dt = _parse_rfc3339_timestamp(consumed_at)
    if not generated_dt or not consumed_dt:
        return "deferred"
    delta_seconds = (consumed_dt - generated_dt).total_seconds()
    if delta_seconds <= LEARNING_IMMEDIATE_WINDOW_SECONDS:
        return "immediate"
    return "deferred"


def _record_learning_handoff_generation_metrics(
    workflow: str,
    generated_at: str,
    markdown_path: Path,
    json_path: Path,
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Update branch/global metrics when a new learning handoff is generated."""
    branch_name = branch or get_branch_name()
    metrics = load_learning_metrics(branch_name)
    counters = cast(dict[str, int], metrics["counters"])
    current_handoff = metrics.get("current_handoff")

    if isinstance(current_handoff, dict) and not current_handoff.get("consumed_at"):
        counters["never_used_handoff_count"] += 1
        abandoned_event: dict[str, object] = {
            "event": "learning_handoff_abandoned",
            "timestamp": generated_at,
            "branch": branch_name,
            "workflow": current_handoff.get("workflow"),
            "generated_at": current_handoff.get("generated_at"),
            "handoff_json_path": current_handoff.get("handoff_json_path"),
        }
        _append_learning_metrics_event(metrics, abandoned_event)
        _append_metrics_event(
            {
                "event": "learning_handoff_abandoned",
                "category": "learning",
                "timestamp": generated_at,
                "branch": branch_name,
                "workflow": current_handoff.get("workflow"),
                "generated_at": current_handoff.get("generated_at"),
                "handoff_json_path": current_handoff.get("handoff_json_path"),
            }
        )

    counters["handoff_generated_count"] += 1
    metrics["current_handoff"] = {
        "workflow": workflow,
        "generated_at": generated_at,
        "consumed_at": "",
        "consumption_mode": "",
        "consumption_source": "",
        "handoff_markdown_path": str(markdown_path),
        "handoff_json_path": str(json_path),
    }
    generation_event: dict[str, object] = {
        "event": "learning_handoff_generated",
        "timestamp": generated_at,
        "branch": branch_name,
        "workflow": workflow,
        "handoff_markdown_path": str(markdown_path),
        "handoff_json_path": str(json_path),
    }
    _append_learning_metrics_event(metrics, generation_event)
    metrics_result = save_learning_metrics(metrics, branch_name)
    _append_metrics_event(
        {
            "event": "learning_handoff_generated",
            "category": "learning",
            "timestamp": generated_at,
            "branch": branch_name,
            "workflow": workflow,
            "handoff_markdown_path": str(markdown_path),
            "handoff_json_path": str(json_path),
            "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
        }
    )
    return metrics_result


def record_learning_consumption(
    summary_source: str = "inline-summary",
    workflow: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Record a completed /map-learn invocation for adoption/deferred-use metrics."""
    branch_name = branch or get_branch_name()
    source = (summary_source or "").strip().lower()
    if source not in LEARNING_CONSUMPTION_SOURCES:
        return {"status": "error", "message": f"Invalid summary_source: {summary_source}"}

    metrics = load_learning_metrics(branch_name)
    counters = cast(dict[str, int], metrics["counters"])
    timestamp = _utc_timestamp()
    current_handoff = metrics.get("current_handoff")
    workflow_name = workflow.strip() or ""

    result: dict[str, object] = {
        "status": "success",
        "branch": branch_name,
        "summary_source": source,
    }

    if source in {"auto-handoff", "file-handoff"} and isinstance(current_handoff, dict):
        workflow_name = current_handoff.get("workflow") or workflow_name
        result["workflow"] = workflow_name
        if current_handoff.get("consumed_at"):
            event: dict[str, object] = {
                "event": "learning_handoff_reused",
                "timestamp": timestamp,
                "branch": branch_name,
                "workflow": workflow_name,
                "summary_source": source,
                "consumption_mode": current_handoff.get("consumption_mode") or "",
            }
            _append_learning_metrics_event(metrics, event)
            metrics_result = save_learning_metrics(metrics, branch_name)
            _append_metrics_event(
                {
                    "event": "learning_handoff_reused",
                    "category": "learning",
                    "timestamp": timestamp,
                    "branch": branch_name,
                    "workflow": workflow_name,
                    "summary_source": source,
                    "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
                }
            )
            result["usage_status"] = "already_recorded"
            result["consumption_mode"] = current_handoff.get("consumption_mode") or ""
            result["metrics_path"] = metrics_result["path"]
            return result

        consumption_mode = _classify_learning_consumption_mode(
            current_handoff.get("generated_at"), timestamp
        )
        current_handoff["consumed_at"] = timestamp
        current_handoff["consumption_mode"] = consumption_mode
        current_handoff["consumption_source"] = source
        counters["handoff_consumed_count"] += 1
        counters[f"{consumption_mode}_learn_count"] += 1
        event = {
            "event": "learning_handoff_consumed",
            "timestamp": timestamp,
            "branch": branch_name,
            "workflow": workflow_name,
            "summary_source": source,
            "consumption_mode": consumption_mode,
            "generated_at": current_handoff.get("generated_at"),
        }
        _append_learning_metrics_event(metrics, event)
        metrics_result = save_learning_metrics(metrics, branch_name)
        _append_metrics_event(
            {
                "event": "learning_handoff_consumed",
                "category": "learning",
                "timestamp": timestamp,
                "branch": branch_name,
                "workflow": workflow_name,
                "summary_source": source,
                "consumption_mode": consumption_mode,
                "generated_at": current_handoff.get("generated_at"),
                "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
            }
        )
        result["usage_status"] = "recorded"
        result["consumption_mode"] = consumption_mode
        result["metrics_path"] = metrics_result["path"]
        return result

    counters["manual_summary_count"] += 1
    event = {
        "event": "learning_manual_summary_recorded",
        "timestamp": timestamp,
        "branch": branch_name,
        "workflow": workflow_name or None,
        "summary_source": source,
    }
    _append_learning_metrics_event(metrics, event)
    metrics_result = save_learning_metrics(metrics, branch_name)
    _append_metrics_event(
        {
            "event": "learning_manual_summary_recorded",
            "category": "learning",
            "timestamp": timestamp,
            "branch": branch_name,
            "workflow": workflow_name or None,
            "summary_source": source,
            "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
        }
    )
    result["usage_status"] = "manual_summary"
    result["metrics_path"] = metrics_result["path"]
    if workflow_name:
        result["workflow"] = workflow_name
    return result


def _normalize_learning_token(token: str) -> str:
    """Normalize lightweight text tokens for repeated-violation matching."""
    normalized = token.lower()
    if normalized.endswith("ies") and len(normalized) > 5:
        normalized = normalized[:-3] + "y"
    elif normalized.endswith("es") and len(normalized) > 5:
        normalized = normalized[:-2]
    elif normalized.endswith("s") and len(normalized) > 4:
        normalized = normalized[:-1]
    return normalized


def _tokenize_learning_text(text: str) -> set[str]:
    """Extract normalized non-trivial tokens from free-form learning text."""
    tokens = {
        _normalize_learning_token(match.group(0))
        for match in TOKEN_RE.finditer((text or "").lower())
    }
    return {
        token
        for token in tokens
        if token and token not in LEARNING_MATCH_STOPWORDS
    }


def _slugify_learning_text(text: str) -> str:
    """Build a stable slug for lightweight identifiers."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug or "rule"


def _parse_rule_paths(content: str) -> list[str]:
    """Extract optional paths frontmatter globs from a learned-rule markdown file."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    paths: list[str] = []
    in_paths = False
    for raw_line in lines[1:]:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if stripped.startswith("- "):
            candidate = stripped[2:].strip().strip("\"'")
            if candidate:
                paths.append(candidate)
            continue
        if stripped:
            in_paths = False
    return paths


def _load_learned_rules() -> list[dict[str, object]]:
    """Load learned-rule bullets plus their optional path scopes."""
    rules_dir = Path(".claude/rules/learned")
    if not rules_dir.exists():
        return []

    rules: list[dict[str, object]] = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        if rule_file.name == "README.md":
            continue
        try:
            content = rule_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rule_paths = _parse_rule_paths(content)
        for raw_line in content.splitlines():
            match = LEARNED_RULE_BULLET_RE.match(raw_line.strip())
            if not match:
                continue
            title = match.group("title").strip()
            body = match.group("body").strip()
            rules.append(
                {
                    "rule_id": f"{rule_file.stem}:{_slugify_learning_text(title)}",
                    "title": title,
                    "body": body,
                    "file": str(rule_file),
                    "paths": rule_paths,
                    "title_tokens": _tokenize_learning_text(title),
                    "body_tokens": _tokenize_learning_text(body),
                }
            )
    return rules


def _normalize_section_title(title: str) -> str:
    """Normalize markdown section headings for comparison."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _extract_section_bullets(content: str, headings: set[str]) -> list[str]:
    """Extract bullet items from selected markdown sections."""
    allowed = {_normalize_section_title(item) for item in headings}
    bullets: list[str] = []
    current_heading = ""

    for raw_line in content.splitlines():
        heading_match = SECTION_HEADING_RE.match(raw_line.strip())
        if heading_match:
            current_heading = _normalize_section_title(heading_match.group("title"))
            continue

        stripped = raw_line.strip()
        if current_heading not in allowed or not stripped.startswith("- "):
            continue

        bullet = stripped[2:].strip()
        if bullet.lower() in {"(none)", "[not recorded]"}:
            continue
        bullets.append(bullet)

    return bullets


def _extract_path_hints(text: str) -> list[str]:
    """Extract likely repo-relative file paths from finding text."""
    hints: list[str] = []
    seen: set[str] = set()
    for match in PATH_HINT_RE.finditer(text or ""):
        candidate = match.group("path").strip("`'\"").rstrip(".,)]")
        normalized = candidate.lstrip("./")
        if not normalized or normalized in seen:
            continue
        hints.append(normalized)
        seen.add(normalized)
    return hints


def _collect_repeated_violation_findings(branch: str) -> list[dict[str, object]]:
    """Collect findings from branch artifacts that can be correlated with learned rules."""
    branch_dir = get_branch_dir(branch)
    findings: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def append_finding(source: str, text: str, source_artifact: str = "") -> None:
        normalized_text = (text or "").strip()
        if not normalized_text:
            return
        dedupe_key = (source, normalized_text)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        findings.append(
            {
                "source": source,
                "source_artifact": source_artifact or source,
                "text": normalized_text,
                "path_hints": _extract_path_hints(normalized_text),
            }
        )

    active_issues_payload = _read_json_file(branch_dir / "active-issues.json") or {}
    active_issues = active_issues_payload.get("issues", [])
    if isinstance(active_issues, list):
        for issue in active_issues:
            if not isinstance(issue, dict):
                continue
            append_finding(
                "active-issues.json",
                str(issue.get("summary") or issue.get("title") or ""),
                str(issue.get("source_artifact") or "active-issues.json"),
            )

    verification_summary = _read_branch_artifact_text(branch_dir, "verification-summary.md")
    for bullet in _extract_section_bullets(verification_summary, {"Findings"}):
        append_finding("verification-summary.md", bullet)

    review_handoff = build_review_handoff(branch)
    code_review = str(review_handoff.get("code_review") or "")
    code_review_path = str(review_handoff.get("code_review_path") or "code-review")
    for bullet in _extract_section_bullets(
        code_review, {"High", "Medium", "Low", "Open Concerns"}
    ):
        append_finding(code_review_path, bullet, code_review_path)

    return findings


def _paths_match_rule_scope(rule_paths: list[str], path_hints: list[str]) -> bool:
    """Return True when a finding path fits at least one learned-rule glob."""
    for path_hint in path_hints:
        for pattern in rule_paths:
            if fnmatch.fnmatch(path_hint, pattern) or fnmatch.fnmatch(
                f"./{path_hint}", pattern
            ):
                return True
    return False


def _match_finding_to_learned_rule(
    finding: dict[str, object], learned_rules: list[dict[str, object]]
) -> Optional[dict[str, object]]:
    """Find the best learned-rule match for one finding, if any."""
    finding_text = str(finding.get("text") or "")
    finding_tokens = _tokenize_learning_text(finding_text)
    if not finding_tokens:
        return None

    path_hints = [
        str(path)
        for path in cast(list[object], finding.get("path_hints", []))
        if isinstance(path, str) and path.strip()
    ]
    best_match: Optional[dict[str, object]] = None

    for rule in learned_rules:
        rule_paths = [
            str(path)
            for path in cast(list[object], rule.get("paths", []))
            if isinstance(path, str) and path.strip()
        ]
        path_match = _paths_match_rule_scope(rule_paths, path_hints) if path_hints else False
        if rule_paths and path_hints and not path_match:
            continue

        title_tokens = set(cast(Iterable[str], rule.get("title_tokens", set())))
        body_tokens = set(cast(Iterable[str], rule.get("body_tokens", set())))
        title_overlap = sorted(finding_tokens & title_tokens)
        body_overlap = sorted((finding_tokens & body_tokens) - set(title_overlap))
        score = len(title_overlap) * 3 + len(body_overlap)
        if path_match:
            score += 2

        qualifies = len(title_overlap) >= 2 or score >= 4
        if not qualifies:
            continue

        match: dict[str, object] = {
            "rule_id": str(rule["rule_id"]),
            "rule_title": str(rule["title"]),
            "rule_file": str(rule["file"]),
            "rule_paths": rule_paths,
            "finding_source": str(finding.get("source") or ""),
            "finding_source_artifact": str(finding.get("source_artifact") or ""),
            "finding_text": finding_text,
            "finding_path_hints": path_hints,
            "matched_tokens": title_overlap + body_overlap,
            "score": score,
            "path_match": path_match,
        }
        if not best_match or int(cast(int, match["score"])) > int(cast(int, best_match["score"])):
            best_match = match

    return best_match


def record_repeated_learning_violations(
    branch: Optional[str] = None, metrics: Optional[dict[str, object]] = None
) -> dict[str, object]:
    """Correlate current findings with learned rules and persist a summary."""
    branch_name = branch or get_branch_name()
    learned_rules = _load_learned_rules()
    findings = _collect_repeated_violation_findings(branch_name)
    matches = []
    for finding in findings:
        match = _match_finding_to_learned_rule(finding, learned_rules)
        if match:
            matches.append(match)

    summary = {
        "checked_at": _utc_timestamp(),
        "finding_count": len(findings),
        "learned_rule_count": len(learned_rules),
        "matched_count": len(matches),
        "matches": matches[:10],
    }

    metrics_payload = metrics if isinstance(metrics, dict) else load_learning_metrics(branch_name)
    counters = metrics_payload.setdefault("counters", {})
    if not isinstance(counters, dict):
        counters = {}
        metrics_payload["counters"] = counters
    counters["repeated_violation_scan_count"] = (
        int(counters.get("repeated_violation_scan_count", 0) or 0) + 1
    )
    counters["repeated_violation_match_count"] = (
        int(counters.get("repeated_violation_match_count", 0) or 0) + len(matches)
    )
    metrics_payload["repeated_violation_summary"] = summary

    if matches:
        event = {
            "event": "learning_repeated_violation_detected",
            "timestamp": summary["checked_at"],
            "branch": branch_name,
            "match_count": len(matches),
            "matches": matches[:5],
        }
        _append_learning_metrics_event(metrics_payload, event)

    metrics_result = save_learning_metrics(metrics_payload, branch_name)
    if matches:
        _append_metrics_event(
            {
                "event": "learning_repeated_violation_detected",
                "category": "learning",
                "timestamp": summary["checked_at"],
                "branch": branch_name,
                "match_count": len(matches),
                "matches": matches[:5],
                "counters": dict(cast(Mapping[str, int], cast(Mapping[str, Mapping[str, int]], metrics_result["metrics"])["counters"])),
            }
        )

    return {
        "status": "success",
        "summary": summary,
        "metrics": metrics_result["metrics"],
        "path": metrics_result["path"],
    }


def record_workflow_fit(
    recommended_workflow: str,
    expected_diff_size: str = "medium",
    has_new_invariants: object = False,
    needs_independent_review: object = False,
    has_clear_acceptance_criteria: object = True,
    test_first_required: object = False,
    decision_summary: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Persist workflow-fit decision and update the artifact manifest."""
    branch_name = branch or get_branch_name()
    route = (recommended_workflow or "").strip().lower()
    diff_size = (expected_diff_size or "").strip().lower()

    if route not in WORKFLOW_FIT_ROUTES:
        return {
            "status": "error",
            "message": f"Invalid recommended_workflow: {recommended_workflow}",
        }
    if diff_size not in DIFF_SIZE_LEVELS:
        return {
            "status": "error",
            "message": f"Invalid expected_diff_size: {expected_diff_size}",
        }

    signals = {
        "expected_diff_size": diff_size,
        "has_new_invariants": _parse_boolish(has_new_invariants),
        "needs_independent_review": _parse_boolish(needs_independent_review),
        "has_clear_acceptance_criteria": _parse_boolish(
            has_clear_acceptance_criteria
        ),
        "test_first_required": _parse_boolish(test_first_required),
    }
    needs_map = route != "direct-edit"
    payload = {
        "version": "1.0",
        "recommended_workflow": route,
        "needs_map": needs_map,
        "decision_summary": decision_summary or "No decision summary provided.",
        "signals": signals,
        "updated_at": _utc_timestamp(),
    }

    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    decision_path = branch_dir / "workflow-fit.json"
    _write_json_file(decision_path, payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "workflow_fit",
        "recorded",
        artifacts=[_artifact_ref(decision_path, "workflow-fit-decision")],
        metadata={
            "recommended_workflow": route,
            "needs_map": needs_map,
            "signals": signals,
            "decision_summary": payload["decision_summary"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)

    return {
        "status": "success",
        "path": str(decision_path),
        "recommended_workflow": route,
        "needs_map": needs_map,
        "manifest_path": manifest_result["path"],
    }


def record_plan_artifacts(branch: Optional[str] = None) -> dict[str, object]:
    """Persist spec/plan artifact presence into artifact_manifest.json."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)

    spec_path = branch_dir / f"spec_{branch_name}.md"
    task_plan_path = branch_dir / f"task_plan_{branch_name}.md"
    blueprint_path = branch_dir / "blueprint.json"
    step_state_path = branch_dir / "step_state.json"

    manifest = load_artifact_manifest(branch_name)

    spec_artifacts = []
    if spec_path.exists():
        spec_artifacts.append(_artifact_ref(spec_path, "spec"))
    _set_manifest_stage(
        manifest,
        "spec",
        "ready" if spec_artifacts else "missing",
        artifacts=spec_artifacts,
        metadata={},
    )

    plan_artifacts = []
    if task_plan_path.exists():
        plan_artifacts.append(_artifact_ref(task_plan_path, "task-plan"))
    if blueprint_path.exists():
        plan_artifacts.append(_artifact_ref(blueprint_path, "blueprint"))
    if step_state_path.exists():
        plan_artifacts.append(_artifact_ref(step_state_path, "step-state"))

    if task_plan_path.exists() and blueprint_path.exists() and step_state_path.exists():
        plan_status = "ready"
    elif plan_artifacts:
        plan_status = "partial"
    else:
        plan_status = "missing"

    _set_manifest_stage(
        manifest,
        "plan",
        plan_status,
        artifacts=plan_artifacts,
        metadata={
            "has_task_plan": task_plan_path.exists(),
            "has_blueprint": blueprint_path.exists(),
            "has_step_state": step_state_path.exists(),
        },
    )

    manifest_result = save_artifact_manifest(manifest, branch_name)
    stages = cast(dict[str, dict[str, object]], manifest["stages"])
    return {
        "status": "success",
        "manifest_path": manifest_result["path"],
        "spec_status": stages["spec"]["status"],
        "plan_status": stages["plan"]["status"],
    }


def validate_blueprint_contract(
    blueprint_path: str = "", branch: Optional[str] = None
) -> dict[str, object]:
    """Validate that a blueprint is executable as contract-sized subtasks.

    This is stricter than BLUEPRINT_SCHEMA because it is a user/operator gate:
    plans should fail before implementation when subtasks are oversized,
    mixed-concern without rationale, or impossible to trace back to acceptance
    criteria.
    """
    branch_name = branch or get_branch_name()
    path = Path(blueprint_path) if blueprint_path else get_branch_dir(branch_name) / "blueprint.json"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "valid": False,
            "errors": [f"blueprint not found: {path}"],
            "warnings": [],
            "path": str(path),
        }
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "valid": False,
            "errors": [f"cannot read blueprint {path}: {exc}"],
            "warnings": [],
            "path": str(path),
        }

    blueprint_body = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    subtasks = blueprint_body.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        return {
            "valid": False,
            "errors": ["blueprint must contain at least one subtask"],
            "warnings": [],
            "path": str(path),
        }

    hard_constraints = blueprint_body.get("hard_constraints")
    soft_constraints = blueprint_body.get("soft_constraints")
    if not isinstance(hard_constraints, list):
        errors.append("hard_constraints is required and must be an array")
        hard_constraints = []
    if not isinstance(soft_constraints, list):
        errors.append("soft_constraints is required and must be an array")
        soft_constraints = []

    hard_constraint_ids: list[str] = []
    for index, constraint in enumerate(hard_constraints):
        label = f"hard_constraints[{index}]"
        if not isinstance(constraint, dict):
            errors.append(f"{label}: must be an object with id and description")
            continue
        constraint_id = str(constraint.get("id") or "").strip()
        description = str(constraint.get("description") or "").strip()
        if not constraint_id:
            errors.append(f"{label}: missing id")
            continue
        if not description:
            errors.append(f"{label}: missing description")
        hard_constraint_ids.append(constraint_id)

    for index, constraint in enumerate(soft_constraints):
        label = f"soft_constraints[{index}]"
        if not isinstance(constraint, dict):
            errors.append(f"{label}: must be an object with id and description")
            continue
        constraint_id = str(constraint.get("id") or "").strip()
        description = str(constraint.get("description") or "").strip()
        if not constraint_id:
            errors.append(f"{label}: missing id")
            continue
        if not description:
            errors.append(f"{label}: missing description")

    subtask_id_counts: dict[str, int] = {}
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        raw_subtask_id = subtask.get("id")
        if isinstance(raw_subtask_id, str) and re.fullmatch(r"ST-\d{3,}", raw_subtask_id):
            subtask_id_counts[raw_subtask_id] = subtask_id_counts.get(raw_subtask_id, 0) + 1

    subtask_ids = set(subtask_id_counts)
    duplicate_subtask_ids = {
        subtask_id for subtask_id, count in subtask_id_counts.items() if count > 1
    }
    oversized_subtasks: list[str] = []
    mixed_concern_subtasks: list[str] = []

    for index, subtask in enumerate(subtasks):
        label = f"subtasks[{index}]"
        if not isinstance(subtask, dict):
            errors.append(f"{label}: must be an object")
            continue

        raw_subtask_id = subtask.get("id")
        if not isinstance(raw_subtask_id, str) or not re.fullmatch(r"ST-\d{3,}", raw_subtask_id):
            errors.append(f"{label}: id must match ST-NNN")
            subtask_id = label
        elif raw_subtask_id in duplicate_subtask_ids:
            errors.append(f"{raw_subtask_id}: duplicate subtask id")
            subtask_id = raw_subtask_id
        else:
            subtask_id = raw_subtask_id
        label = subtask_id

        dependencies = subtask.get("dependencies")
        if not isinstance(dependencies, list):
            errors.append(f"{label}: dependencies must be an array")
        else:
            for dependency in dependencies:
                if not isinstance(dependency, str) or not re.fullmatch(r"ST-\d{3,}", dependency):
                    errors.append(f"{label}: dependency {dependency!r} must match ST-NNN")
                elif dependency not in subtask_ids:
                    errors.append(f"{label}: dependency {dependency!r} points to unknown subtask")

        expected_diff_size = str(subtask.get("expected_diff_size") or "").strip().lower()
        concern_type = str(subtask.get("concern_type") or "").strip().lower()
        validation_criteria = subtask.get("validation_criteria")

        if expected_diff_size not in DIFF_SIZE_LEVELS:
            errors.append(
                f"{label}: expected_diff_size must be one of {sorted(DIFF_SIZE_LEVELS)}"
            )
        elif expected_diff_size == "large":
            split_rationale = str(subtask.get("split_rationale") or "").strip()
            if not split_rationale:
                errors.append(
                    f"{label}: large subtasks require split_rationale or must be decomposed"
                )
            oversized_subtasks.append(subtask_id)

        if concern_type not in SUBTASK_CONCERN_TYPES:
            errors.append(
                f"{label}: concern_type must be one of {sorted(SUBTASK_CONCERN_TYPES)}"
            )
        elif concern_type == "mixed":
            concern_justification = str(subtask.get("concern_justification") or "").strip()
            if not concern_justification:
                errors.append(
                    f"{label}: mixed concern_type requires concern_justification"
                )
            mixed_concern_subtasks.append(subtask_id)

        one_logical_step = subtask.get("one_logical_step")
        if one_logical_step is not True:
            errors.append(f"{label}: one_logical_step must be true")

        if not str(subtask.get("aag_contract") or "").strip():
            errors.append(f"{label}: missing aag_contract")

        if not isinstance(validation_criteria, list) or not validation_criteria:
            errors.append(f"{label}: validation_criteria must contain at least one item")
        elif not all(
            isinstance(item, str) and item.strip() for item in validation_criteria
        ):
            errors.append(f"{label}: validation_criteria items must be non-empty strings")
        elif len(validation_criteria) > 6:
            warnings.append(
                f"{label}: has {len(validation_criteria)} validation criteria; consider splitting if ownership is unclear"
            )

        affected_files = subtask.get("affected_files")
        if isinstance(affected_files, list) and len(affected_files) > 8:
            warnings.append(
                f"{label}: touches {len(affected_files)} files; verify this is still one reviewable concern"
            )

    coverage_map = payload.get("coverage_map") or blueprint_body.get("coverage_map")
    if not isinstance(coverage_map, dict) or not coverage_map:
        errors.append(
            "coverage_map is required and must map each spec AC/invariant to an owning subtask"
        )
    else:
        for constraint_id in hard_constraint_ids:
            if constraint_id not in coverage_map:
                errors.append(
                    f"hard_constraints requirement {constraint_id!r} must appear in coverage_map"
                )
        for constraint in soft_constraints:
            if not isinstance(constraint, dict):
                continue
            constraint_id = str(constraint.get("id") or "").strip()
            if not constraint_id or constraint_id in coverage_map:
                continue
            tradeoff_rationale = str(constraint.get("tradeoff_rationale") or "").strip()
            if not tradeoff_rationale:
                errors.append(
                    f"soft_constraints requirement {constraint_id!r} must either appear in coverage_map "
                    "or include tradeoff_rationale"
                )

        requirement_owners: dict[str, list[str]] = {}
        for requirement_id, owner in coverage_map.items():
            if not isinstance(owner, str):
                errors.append(
                    f"coverage_map[{requirement_id!r}] must point to a single ST-NNN subtask id"
                )
                continue
            if owner not in subtask_ids:
                errors.append(
                    f"coverage_map[{requirement_id!r}] points to unknown subtask {owner!r}"
                )
                continue
            requirement_owners.setdefault(owner, []).append(str(requirement_id))

        subtasks_by_id = {
            subtask.get("id"): subtask
            for subtask in subtasks
            if isinstance(subtask, dict) and isinstance(subtask.get("id"), str)
        }
        for owner, requirement_ids in requirement_owners.items():
            owner_subtask = subtasks_by_id.get(owner)
            validation_criteria = (
                owner_subtask.get("validation_criteria")
                if isinstance(owner_subtask, dict)
                else None
            )
            criterion_texts = [
                item for item in validation_criteria or [] if isinstance(item, str)
            ]
            for requirement_id in requirement_ids:
                lineage_tag = f"[{requirement_id}]"
                if not any(lineage_tag in item for item in criterion_texts):
                    errors.append(
                        f"{owner}: validation_criteria must cite coverage_map requirement "
                        f"{requirement_id!r} as {lineage_tag}"
                    )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "path": str(path),
        "subtask_count": len(subtasks),
        "oversized_subtasks": oversized_subtasks,
        "mixed_concern_subtasks": mixed_concern_subtasks,
    }


def record_test_contract_handoff(
    subtask_id: str,
    failing_test_command: str = "",
    test_files_csv: str = "",
    contract_summary: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Create test_handoff_<subtask>.json from an existing test_contract file."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    contract_path = branch_dir / f"test_contract_{subtask_id}.md"
    if not contract_path.exists():
        return {
            "status": "error",
            "message": f"Missing test contract: {contract_path}",
        }

    test_files = [
        item.strip()
        for item in (test_files_csv or "").split(",")
        if item.strip()
    ]
    handoff_payload = {
        "subtask_id": subtask_id,
        "status": "contract_ready",
        "contract_path": str(contract_path),
        "failing_test_command": failing_test_command or None,
        "test_files": test_files,
        "contract_summary": contract_summary or "No contract summary provided.",
        "notes": notes or "",
        "updated_at": _utc_timestamp(),
    }
    handoff_path = branch_dir / f"test_handoff_{subtask_id}.json"
    _write_json_file(handoff_path, handoff_payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "test_contract",
        "contract_ready",
        artifacts=[
            _artifact_ref(contract_path, "test-contract"),
            _artifact_ref(handoff_path, "test-handoff"),
        ],
        metadata={
            "subtask_id": subtask_id,
            "failing_test_command": handoff_payload["failing_test_command"],
            "test_files": test_files,
            "contract_summary": handoff_payload["contract_summary"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)

    return {
        "status": "success",
        "contract_path": str(contract_path),
        "handoff_path": str(handoff_path),
        "manifest_path": manifest_result["path"],
        "subtask_id": subtask_id,
    }


def get_branch_dir(branch: Optional[str] = None) -> Path:
    """Return .map/<branch> directory, auto-detecting branch when omitted."""
    if branch is None:
        branch = get_branch_name()
    return Path(f".map/{branch}")


def ensure_human_artifacts(branch: Optional[str] = None) -> dict:
    """Ensure core human-readable workflow artifacts exist for the branch."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)

    created = []
    existing = []
    for file_name, content in HUMAN_ARTIFACT_DEFAULTS.items():
        path = branch_dir / file_name
        if path.exists():
            existing.append(file_name)
            continue
        path.write_text(content, encoding="utf-8")
        created.append(file_name)

    return {
        "status": "success",
        "branch_dir": str(branch_dir),
        "created": created,
        "existing": existing,
    }


def next_numbered_artifact_path(
    prefix: str, branch: Optional[str] = None, extension: str = ".md"
) -> dict:
    """Return the next numbered artifact path like review-002.md."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)

    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}}){re.escape(extension)}$")
    next_index = 1
    for path in branch_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            next_index = max(next_index, int(match.group(1)) + 1)

    file_name = f"{prefix}-{next_index:03d}{extension}"
    return {
        "status": "success",
        "path": str(branch_dir / file_name),
        "file_name": file_name,
        "index": next_index,
    }


def append_session_log(
    phase: str,
    outcome: str,
    subtask_id: str = "",
    details: str = "",
    artifact_refs: Optional[list[str]] = None,
    branch: Optional[str] = None,
) -> dict:
    """Deprecated: session-log.md removed in pipeline simplification.

    Returns {"status": "deprecated", "path": "", "deprecated": True}.
    Kept for CLI backward compatibility — callers should stop using this function.
    """
    del phase, outcome, subtask_id, details, artifact_refs, branch
    return {"status": "deprecated", "path": "", "deprecated": True}


def _load_blueprint_for_coverage(branch_dir: Path) -> tuple[dict[str, object] | None, str]:
    """Load blueprint.json and normalize nested blueprint payloads for coverage reporting."""
    blueprint_path = branch_dir / "blueprint.json"
    try:
        payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "blueprint.json not found"
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"cannot read blueprint.json: {exc}"
    if not isinstance(payload, dict):
        return None, "blueprint.json must contain an object"
    blueprint = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload
    blueprint = cast(dict[str, object], blueprint)
    if "coverage_map" not in blueprint and isinstance(payload.get("coverage_map"), dict):
        blueprint = dict(blueprint)
        blueprint["coverage_map"] = payload["coverage_map"]
    return blueprint, ""


def _extract_acceptance_tags(text: object) -> set[str]:
    """Return bracketed acceptance/invariant tags found in artifact text."""
    if not isinstance(text, str) or not text:
        return set()
    return {match.group(1) for match in ACCEPTANCE_TAG_RE.finditer(text)}


def _collect_acceptance_evidence_texts(
    branch_dir: Path,
    branch_name: str,
    extra_artifacts: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Collect review/verification artifact text that can prove acceptance tags."""
    evidence: dict[str, str] = {}
    for label, name in (
        ("verification_summary", "verification-summary.md"),
        ("qa", "qa-001.md"),
        ("pr_draft", "pr-draft.md"),
    ):
        text = _read_branch_artifact_text(branch_dir, name)
        if text:
            evidence[label] = text

    for prefix, label in (("code-review", "latest_code_review"),):
        latest = _collect_numbered_artifact(branch_dir, prefix)
        text = latest.get("sanitized_text") if isinstance(latest, dict) else None
        if isinstance(text, str) and text:
            evidence[label] = text

    for pattern, label_prefix in (
        ("test_contract_*.md", "test_contract"),
        ("test_handoff_*.json", "test_handoff"),
    ):
        try:
            matches = sorted(branch_dir.glob(pattern))
        except OSError:
            matches = []
        for path in matches:
            if not path.is_file():
                continue
            try:
                text = _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if text:
                evidence[f"{label_prefix}:{path.name}"] = text

    for label, text in (extra_artifacts or {}).items():
        if text:
            evidence[label] = _sanitize_for_json(text)
    return evidence


def build_acceptance_coverage_report(
    branch: Optional[str] = None,
    extra_artifacts: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """Summarize which blueprint acceptance tags have downstream evidence."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    blueprint, reason = _load_blueprint_for_coverage(branch_dir)
    if blueprint is None:
        return {
            "status": "missing_blueprint",
            "branch": branch_name,
            "reason": reason,
            "requirements": [],
            "summary": {"total": 0, "covered": 0, "missing": 0},
        }

    coverage_map = blueprint.get("coverage_map")
    subtasks = blueprint.get("subtasks")
    if not isinstance(coverage_map, dict) or not isinstance(subtasks, list):
        return {
            "status": "invalid_blueprint",
            "branch": branch_name,
            "reason": "blueprint requires coverage_map and subtasks for acceptance coverage",
            "requirements": [],
            "summary": {"total": 0, "covered": 0, "missing": 0},
        }

    subtasks_by_id = {
        subtask.get("id"): subtask
        for subtask in subtasks
        if isinstance(subtask, dict) and isinstance(subtask.get("id"), str)
    }
    evidence_texts = _collect_acceptance_evidence_texts(
        branch_dir, branch_name, extra_artifacts=extra_artifacts
    )
    evidence_tags_by_source = {
        source: _extract_acceptance_tags(text)
        for source, text in evidence_texts.items()
    }

    requirements: list[dict[str, object]] = []
    for requirement_id, owner in sorted(coverage_map.items(), key=lambda item: str(item[0])):
        requirement = str(requirement_id)
        owner_id = str(owner) if isinstance(owner, str) else None
        owner_subtask = subtasks_by_id.get(owner_id) if owner_id else None
        criteria = (
            owner_subtask.get("validation_criteria")
            if isinstance(owner_subtask, dict)
            else []
        )
        criterion_texts = [item for item in criteria if isinstance(item, str)]
        validation_criteria_cited = any(
            f"[{requirement}]" in item for item in criterion_texts
        )
        evidence_artifacts = sorted(
            source
            for source, tags in evidence_tags_by_source.items()
            if requirement in tags
        )
        requirements.append(
            {
                "id": requirement,
                "owner": owner_id,
                "validation_criteria_cited": validation_criteria_cited,
                "evidence_artifacts": evidence_artifacts,
                "status": "covered" if evidence_artifacts else "missing_evidence",
            }
        )

    covered = sum(1 for item in requirements if item["status"] == "covered")
    missing = len(requirements) - covered
    tagged_evidence_sources = sorted(
        source for source, tags in evidence_tags_by_source.items() if tags
    )
    return {
        "status": "success",
        "branch": branch_name,
        "blueprint_path": str(branch_dir / "blueprint.json"),
        "evidence_sources": tagged_evidence_sources,
        "requirements": requirements,
        "summary": {"total": len(requirements), "covered": covered, "missing": missing},
    }


def _render_acceptance_coverage_markdown(report: Mapping[str, object]) -> str:
    """Render an acceptance coverage report into a compact Markdown section."""
    if report.get("status") != "success":
        reason = report.get("reason", "not available")
        return "## Acceptance Coverage\n- Status: not available\n- Reason: " + str(reason) + "\n"

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    total = summary.get("total", 0) if isinstance(summary, dict) else 0
    covered = summary.get("covered", 0) if isinstance(summary, dict) else 0
    missing = summary.get("missing", 0) if isinstance(summary, dict) else 0
    lines = [
        "## Acceptance Coverage",
        f"- Covered tags: {covered}/{total}",
        f"- Missing evidence: {missing}",
    ]
    requirements = report.get("requirements")
    if isinstance(requirements, list) and requirements:
        for item in requirements:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence_artifacts")
            if isinstance(evidence, list) and evidence:
                evidence_text = ", ".join(str(source) for source in evidence)
            else:
                evidence_text = "missing"
            lines.append(
                f"- [{item.get('status', 'unknown')}] {item.get('id', 'unknown')} "
                f"owned by {item.get('owner') or 'unknown'}; evidence: {evidence_text}"
            )
    return "\n".join(lines) + "\n"


def write_verification_summary(
    verdict: str,
    task_title: str = "",
    checks_run: str = "",
    findings: str = "",
    next_action: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a compact human-readable verification summary."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    summary_file = branch_dir / "verification-summary.md"

    content = (
        "# Verification Summary\n\n"
        f"- Branch: {branch_name}\n"
        f"- Task: {task_title or '[not provided]'}\n"
        f"- Verdict: {verdict}\n\n"
        "## Checks Run\n"
        f"{checks_run or '- [not recorded]'}\n\n"
        "## Findings\n"
        f"{findings or '- [not recorded]'}\n\n"
        "## Next Action\n"
        f"{next_action or '- [not recorded]'}\n"
    )
    coverage_report = build_acceptance_coverage_report(
        branch_name, extra_artifacts={"verification_summary": content}
    )
    content += "\n" + _render_acceptance_coverage_markdown(coverage_report)
    prior_stage_report = build_prior_stage_consumption_report(
        "implementation", branch_name
    )
    content += "\n" + _render_prior_stage_consumption_markdown(prior_stage_report)
    summary_file.write_text(content, encoding="utf-8")
    return {
        "status": "success",
        "path": str(summary_file),
        "acceptance_coverage": coverage_report,
        "prior_stage_consumption": prior_stage_report,
    }


def _count_step_entries(value: object) -> int:
    """Count step entries across legacy list and per-subtask dict shapes."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        total = 0
        for item in value.values():
            total += len(item) if isinstance(item, list) else 1
        return total
    return 0


def _as_dict(value: object) -> dict[str, object]:
    """Return value when it is a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    """Best-effort integer coercion for counters loaded from JSON artifacts."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _derive_terminal_status(state: dict[str, object]) -> str:
    """Derive a stable terminal status from step_state.json when not explicit."""
    existing = str(state.get("terminal_status") or "").strip().lower()
    if existing in RUN_HEALTH_TERMINAL_STATUSES:
        return existing

    workflow_status = str(state.get("workflow_status") or "").strip().upper()
    current_phase = str(state.get("current_step_phase") or "").strip().upper()
    if (
        workflow_status in {"COMPLETE", "COMPLETED", "WORKFLOW_COMPLETE"}
        or current_phase == "COMPLETE"
    ):
        return "complete"
    if workflow_status in {"BLOCKED", "MAX_RETRIES"}:
        return "blocked"
    if workflow_status in {"SUPERSEDED"}:
        return "superseded"
    if workflow_status in {"WONT_DO", "WON'T_DO"}:
        return "won't_do"
    return "pending"


def _artifact_health_entry(path: Path, kind: str) -> dict[str, object]:
    """Return compact presence metadata for a workflow artifact."""
    try:
        size_bytes = path.stat().st_size
        present = True
    except OSError:
        size_bytes = 0
        present = False

    return {
        "kind": kind,
        "path": str(path),
        "present": present,
        "size_bytes": size_bytes,
    }


def _run_health_artifact_inventory(
    branch_dir: Path, branch: str
) -> dict[str, dict[str, object]]:
    """Collect the artifact set that proves workflow resumability/reviewability."""
    return {
        "step_state": _artifact_health_entry(branch_dir / "step_state.json", "state"),
        "artifact_manifest": _artifact_health_entry(
            branch_dir / "artifact_manifest.json", "manifest"
        ),
        "verification_summary": _artifact_health_entry(
            branch_dir / "verification-summary.md", "verification"
        ),
        "qa": _artifact_health_entry(branch_dir / "qa-001.md", "qa"),
        "pr_draft": _artifact_health_entry(branch_dir / "pr-draft.md", "pr-draft"),
        "review_bundle": _artifact_health_entry(
            branch_dir / "review-bundle.json", "review-bundle"
        ),
        "learning_handoff": _artifact_health_entry(
            branch_dir / "learning-handoff.json", "learning-handoff"
        ),
        "task_plan": _artifact_health_entry(
            branch_dir / f"task_plan_{branch}.md", "task-plan"
        ),
        "blueprint": _artifact_health_entry(branch_dir / "blueprint.json", "blueprint"),
        "active_issues": _artifact_health_entry(
            branch_dir / "active-issues.json", "active-issues"
        ),
        "known_issues": _artifact_health_entry(
            branch_dir / "known-issues.json", "known-issues"
        ),
    }


def write_run_health_report(
    workflow: str = "map-efficient",
    terminal_status: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Write a machine-readable workflow health report for diagnosis/resume.

    The report intentionally summarizes existing branch artifacts instead of
    inventing a new workflow state source. Callers can run it at normal closeout,
    after a blocked run, or during resume diagnostics.
    """
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    step_state_path = branch_dir / "step_state.json"
    state = _read_json_file(step_state_path) or {}

    status = (terminal_status or "").strip().lower() or _derive_terminal_status(state)
    if status not in RUN_HEALTH_TERMINAL_STATUSES:
        return {
            "status": "error",
            "message": f"Invalid terminal_status: {terminal_status}",
        }

    completed_steps = state.get("completed_steps")
    pending_steps = state.get("pending_steps")
    retry_count = _as_int(state.get("retry_count"))
    subtask_retry_counts = _as_dict(state.get("subtask_retry_counts"))
    guard_rework_counts = _as_dict(state.get("guard_rework_counts"))
    hook_injection = _as_dict(state.get("hook_injection"))
    artifact_inventory = _run_health_artifact_inventory(branch_dir, branch_name)

    payload: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": _utc_timestamp(),
        "workflow": (workflow or state.get("workflow") or "map-workflow"),
        "branch": branch_name,
        "terminal_status": status,
        "current_step_id": state.get("current_step_id") or None,
        "current_step_phase": state.get("current_step_phase") or None,
        "current_subtask_id": state.get("current_subtask_id") or None,
        "completed_step_count": _count_step_entries(completed_steps),
        "pending_step_count": _count_step_entries(pending_steps),
        "artifacts": artifact_inventory,
        "resiliency_signals": {
            "hook_injection": hook_injection
            or {"status": "unknown", "reason": "not recorded"},
            "hook_injection_counts": _as_dict(state.get("hook_injection_counts")),
            "retry_count": retry_count,
            "max_retries": _as_int(state.get("max_retries")),
            "subtask_retry_counts": subtask_retry_counts,
            "max_subtask_retry_count": max(
                [_as_int(value) for value in subtask_retry_counts.values()] or [0]
            ),
            "guard_rework_counts": guard_rework_counts,
            "predictor_called": bool(state.get("predictor_called")),
            "predictor_skipped": bool(state.get("predictor_skipped")),
            "final_verifier_executed": bool(
                state.get("final_verifier_executed")
                or artifact_inventory["verification_summary"]["present"]
            ),
        },
    }

    report_path = branch_dir / "run_health_report.json"
    _write_json_file(report_path, payload)

    manifest = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest,
        "run_health",
        "ready",
        artifacts=[_artifact_ref(report_path, "run-health-report")],
        metadata={
            "terminal_status": status,
            "workflow": payload["workflow"],
            "current_step_phase": payload["current_step_phase"],
            "hook_injection_status": cast(
                Mapping[str, object],
                payload["resiliency_signals"],
            )["hook_injection"],
        },
    )
    manifest_result = save_artifact_manifest(manifest, branch_name)
    return {
        "status": "success",
        "path": str(report_path),
        "manifest_path": manifest_result["path"],
        "terminal_status": status,
    }


def _load_run_health_schema_validator() -> tuple[object, object] | tuple[None, None]:
    """Return optional package schema validator for generated-project installs."""
    try:
        import importlib as _importlib

        _schemas_mod = sys.modules.get("mapify_cli.schemas")
        if _schemas_mod is None:
            _schemas_mod = _importlib.import_module("mapify_cli.schemas")
        return (
            getattr(_schemas_mod, "RUN_HEALTH_REPORT_SCHEMA", None),
            getattr(_schemas_mod, "validate_artifact", None),
        )
    except ImportError:
        return (None, None)


def _artifact_present(report: Mapping[str, object], key: str) -> bool:
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return False
    entry = artifacts.get(key)
    return isinstance(entry, Mapping) and bool(entry.get("present"))


def _validate_run_health_report_shape(report: Mapping[str, object]) -> list[str]:
    """Validate the stable run-health contract without optional dependencies."""
    errors: list[str] = []
    unexpected_keys = set(report) - RUN_HEALTH_REQUIRED_KEYS - {
        "current_step_id",
        "current_step_phase",
        "current_subtask_id",
    }
    for key in sorted(RUN_HEALTH_REQUIRED_KEYS - set(report)):
        errors.append(f"missing required field: {key}")
    for key in sorted(unexpected_keys):
        errors.append(f"unexpected field: {key}")

    terminal_status = str(report.get("terminal_status") or "").strip().lower()
    if terminal_status not in RUN_HEALTH_TERMINAL_STATUSES:
        errors.append(f"invalid terminal_status: {terminal_status or '[missing]'}")

    for key in ("schema_version", "generated_at", "workflow", "branch"):
        if key in report and not isinstance(report.get(key), str):
            errors.append(f"{key} must be a string")
    for key in ("completed_step_count", "pending_step_count"):
        value = report.get(key)
        if key in report and (not isinstance(value, int) or value < 0):
            errors.append(f"{key} must be a non-negative integer")

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, Mapping):
        errors.append("artifacts must be an object")
    else:
        for key in sorted(RUN_HEALTH_ARTIFACT_KEYS - set(artifacts)):
            errors.append(f"artifacts.{key} is required")
        for key, value in artifacts.items():
            if not isinstance(value, Mapping):
                errors.append(f"artifacts.{key} must be an object")
                continue
            for field in ("kind", "path"):
                if not isinstance(value.get(field), str):
                    errors.append(f"artifacts.{key}.{field} must be a string")
            if not isinstance(value.get("present"), bool):
                errors.append(f"artifacts.{key}.present must be a boolean")
            size_bytes = value.get("size_bytes")
            if not isinstance(size_bytes, int) or size_bytes < 0:
                errors.append(f"artifacts.{key}.size_bytes must be a non-negative integer")

    signals = report.get("resiliency_signals")
    if not isinstance(signals, Mapping):
        errors.append("resiliency_signals must be an object")
    else:
        for key in sorted(RUN_HEALTH_SIGNAL_KEYS - set(signals)):
            errors.append(f"resiliency_signals.{key} is required")
        hook = signals.get("hook_injection")
        if not isinstance(hook, Mapping):
            errors.append("resiliency_signals.hook_injection must be an object")
        elif not isinstance(hook.get("status"), str):
            errors.append("resiliency_signals.hook_injection.status must be a string")
        for key in ("hook_injection_counts", "subtask_retry_counts", "guard_rework_counts"):
            if key in signals and not isinstance(signals.get(key), Mapping):
                errors.append(f"resiliency_signals.{key} must be an object")
        for key in ("retry_count", "max_retries", "max_subtask_retry_count"):
            value = signals.get(key)
            if key in signals and (not isinstance(value, int) or value < 0):
                errors.append(f"resiliency_signals.{key} must be a non-negative integer")
        for key in ("predictor_called", "predictor_skipped", "final_verifier_executed"):
            if key in signals and not isinstance(signals.get(key), bool):
                errors.append(f"resiliency_signals.{key} must be a boolean")

    return errors


def validate_run_health_report(
    report_path: str = "",
    branch: Optional[str] = None,
) -> dict[str, object]:
    """Validate run_health_report.json for CI/operator closeout checks."""
    branch_name = branch or get_branch_name()
    path = Path(report_path) if report_path else get_branch_dir(branch_name) / "run_health_report.json"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"run health report not found: {path}"],
            "warnings": [],
        }
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": [f"cannot read run health report: {exc}"],
            "warnings": [],
        }

    if not isinstance(report, dict):
        return {
            "status": "error",
            "valid": False,
            "path": str(path),
            "errors": ["run health report must be a JSON object"],
            "warnings": [],
        }

    errors.extend(_validate_run_health_report_shape(report))

    schema, validate_artifact = _load_run_health_schema_validator()
    if schema is not None and validate_artifact is not None:
        is_valid, schema_errors = validate_artifact(report, schema)
        if not is_valid:
            errors.extend(f"schema: {error}" for error in schema_errors)
    else:
        warnings.append("schema validator unavailable; semantic checks only")

    terminal_status = str(report.get("terminal_status") or "").strip().lower()
    pending_step_count = _as_int(report.get("pending_step_count"))
    signals = _as_dict(report.get("resiliency_signals"))
    hook_injection = _as_dict(signals.get("hook_injection"))
    hook_status = str(hook_injection.get("status") or "").strip().lower()
    hook_reason = str(hook_injection.get("reason") or "").strip()
    retry_count = _as_int(signals.get("retry_count"))
    max_retries = _as_int(signals.get("max_retries"))
    max_subtask_retry_count = _as_int(signals.get("max_subtask_retry_count"))
    final_verifier_executed = bool(signals.get("final_verifier_executed"))
    verification_present = _artifact_present(report, "verification_summary")

    if terminal_status == "complete":
        if pending_step_count:
            errors.append("complete report must not have pending steps")
        if not (final_verifier_executed or verification_present):
            errors.append(
                "complete report must include a final verifier signal or verification summary artifact"
            )

    if max_retries > 0 and retry_count > max_retries:
        errors.append(f"retry_count {retry_count} exceeds max_retries {max_retries}")
    if max_retries > 0 and max_subtask_retry_count > max_retries:
        errors.append(
            f"max_subtask_retry_count {max_subtask_retry_count} exceeds max_retries {max_retries}"
        )

    if hook_status in {"", "unknown", "skipped", "degraded", "error"} and not hook_reason:
        errors.append(
            "hook_injection degradation must include a reason when status is unknown, skipped, degraded, or error"
        )

    if terminal_status == "pending" and pending_step_count == 0:
        warnings.append("pending report has no pending steps")
    if terminal_status in {"blocked", "superseded"} and not _artifact_present(report, "step_state"):
        warnings.append(f"{terminal_status} report has no step_state artifact")

    valid = not errors
    return {
        "status": "success" if valid else "error",
        "valid": valid,
        "path": str(path),
        "terminal_status": terminal_status,
        "errors": errors,
        "warnings": warnings,
    }


def write_pr_draft(
    summary: str = "",
    validation: str = "",
    risks_follow_up: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a compact PR draft artifact for the current branch."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    pr_file = branch_dir / "pr-draft.md"

    content = (
        "# PR Draft\n\n"
        "## Summary\n"
        f"{summary or '- [not recorded]'}\n\n"
        "## Validation\n"
        f"{validation or '- [not recorded]'}\n\n"
        "## Risks / Follow-up\n"
        f"{risks_follow_up or '- [not recorded]'}\n"
    )
    pr_file.write_text(content, encoding="utf-8")
    return {"status": "success", "path": str(pr_file)}


def write_plan_review(
    summary: str = "",
    high: str = "",
    medium: str = "",
    low: str = "",
    resolved_since_previous: str = "",
    open_concerns: str = "",
    recommendation: str = "needs-revision",
    branch: Optional[str] = None,
) -> dict:
    """Write the next staged planning review artifact."""
    recommendation = recommendation.strip().lower()
    if recommendation not in GATE_VERDICTS:
        return {
            "status": "error",
            "message": f"Invalid recommendation: {recommendation}",
        }

    artifact = next_numbered_artifact_path("plan-review", branch)
    review_file = Path(artifact["path"])
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_number = artifact["index"]

    content = (
        f"# Plan Review {review_number:03d}\n\n"
        "## Summary\n"
        f"{summary or '- [not recorded]'}\n\n"
        "## High\n"
        f"{high or '(None)'}\n\n"
        "## Medium\n"
        f"{medium or '(None)'}\n\n"
        "## Low\n"
        f"{low or '(None)'}\n\n"
        "## Resolved Since Previous Review\n"
        f"{resolved_since_previous or '(None)'}\n\n"
        "## Open Concerns\n"
        f"{open_concerns or '(None)'}\n\n"
        "## Recommendation\n"
        f"- {recommendation}\n"
    )
    review_file.write_text(content, encoding="utf-8")
    return {
        "status": "success",
        "path": str(review_file),
        "file_name": review_file.name,
        "index": review_number,
    }


def write_stage_gate(
    stage: str,
    verdict: str,
    source_artifact: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a machine-readable gate artifact for a workflow stage."""
    verdict = verdict.strip().lower()
    if verdict not in GATE_VERDICTS:
        return {"status": "error", "message": f"Invalid verdict: {verdict}"}

    normalized_stage = stage.strip().lower().replace("_", "-")
    gate_file = get_branch_dir(branch) / f"{normalized_stage}-gate.json"
    gate_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": normalized_stage,
        "verdict": verdict,
        "source_artifact": source_artifact or None,
        "updated_at": datetime.now().isoformat(),
        "notes": notes or "",
    }
    gate_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {"status": "success", "path": str(gate_file), "verdict": verdict}


def ensure_active_issues_file(branch: Optional[str] = None) -> dict:
    """Ensure active-issues.json exists for current unresolved issue set."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    issues_file = branch_dir / "active-issues.json"
    if not issues_file.exists():
        payload = {**ACTIVE_ISSUES_DEFAULT, "updated_at": datetime.now().isoformat()}
        issues_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        return {"status": "success", "path": str(issues_file), "created": True}
    return {"status": "success", "path": str(issues_file), "created": False}


def replace_active_issues(
    stage: str,
    source_artifact: str,
    issues_text: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Replace active unresolved issue set from newline-delimited bullets/text."""
    ensure_active_issues_file(branch)
    issues_file = get_branch_dir(branch) / "active-issues.json"

    issue_lines = []
    for raw in issues_text.splitlines():
        line = raw.strip()
        if not line or line in {"(None)", "- (None)"}:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        issue_lines.append(line)

    issues = [
        {
            "id": f"{stage[:3].upper()}-{index:03d}",
            "stage": stage,
            "source_artifact": source_artifact,
            "status": "open",
            "summary": line,
        }
        for index, line in enumerate(issue_lines, start=1)
    ]
    payload = {
        "updated_at": datetime.now().isoformat(),
        "issues": issues,
    }
    issues_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {"status": "success", "path": str(issues_file), "count": len(issues)}


def _sanitize_for_json(text: str) -> str:
    """Remove every C0 control character (U+0000-U+001F) and U+007F from text.

    Python's ``json.dumps`` does escape these correctly for strict JSON
    output, but the bundle is then piped through bash command substitution
    (``BUNDLE=$(... step_runner ...)``) and consumed by ``jq``. Bash
    expansion does not preserve byte-perfect roundtrip for embedded
    literal control characters in all locales, so jq receives a string
    with raw controls and rejects it with::

        jq: parse error: Invalid string: control characters from U+0000
        through U+001F must be escaped at line N, column M

    Stripping at source is the only robust fix. We additionally
    normalise newline variants (``\\r\\n``, ``\\r``) into spaces to keep
    word boundaries when multi-line artifact bodies are flattened into a
    single bundle field.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", " ").replace("\t", " ")
    return re.sub(r"[\x00-\x1f\x7f]", "", text)


def get_review_section_order(mode: str, seed: int | None = None) -> list[str]:
    """Return canonical/reverse/seeded-shuffle section list for /map-review.

    AC-1: 'default' returns canonical; 'reverse-sections' returns reversed;
    'shuffle-sections' uses random.Random(seed).
    AC-2: Same seed -> identical order; different seeds may differ.
    EC-9: Unknown mode -> ValueError listing allowed modes.
    """
    if mode not in REVIEW_VALID_MODES:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {REVIEW_VALID_MODES}"
        )
    sections = list(REVIEW_SECTION_IDS)
    if mode == "default":
        return sections
    if mode == "reverse-sections":
        return list(reversed(sections))
    # shuffle-sections
    if seed is not None and seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    rng = random.Random(seed)
    rng.shuffle(sections)
    return sections


def default_shuffle_seed(branch: str, commit_sha: str | None) -> int:
    """Derive a stable per-branch shuffle seed.

    AC-3: stable for fixed inputs across processes and machines. Uses sha256
    (not built-in hash() — which is randomized per process via PYTHONHASHSEED
    and breaks reproducibility). commit_sha=None falls back to
    sha256(branch + '|detached').
    """
    key = f"{branch}|detached" if commit_sha is None else f"{branch}|{commit_sha}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def compare_review_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    """Aggregate ordering-variant review runs with strict-wins verdict + drift detection.

    INV-4 strict-wins: final_verdict = max over runs of rank BLOCK>REVISE>PROCEED.
    INV-5: drift NEVER auto-escalates beyond the strictest individual verdict.
    EC-10: intra-run issue order irrelevant (set-based overlap).
    EC-11 partial-failure: len(runs)==1 -> compare_status='partial_failure', drift_detected=True.
    EC-13: drift_summary truncated to 2000 chars then sanitized (INV-8).
    """
    _RANK: dict[str, int] = {"PROCEED": 0, "REVISE": 1, "BLOCK": 2}

    if not isinstance(runs, list) or len(runs) == 0:
        raise ValueError("runs must be a non-empty list")

    # Partial failure (EC-11): exactly one run survived
    if len(runs) == 1:
        only = runs[0]
        verdict = only.get("verdict", "PROCEED")
        if verdict not in _RANK:
            raise ValueError(f"unknown verdict {verdict!r}; expected one of {list(_RANK)}")
        raw_issues: Iterable[object] = cast(Iterable[object], only.get("primary_issues") or [])
        issues = [str(i) for i in raw_issues]
        summary_raw = (
            "one ordering run failed; drift could not be confirmed; verdict is provisional"
        )
        return {
            "drift_detected": True,
            "verdicts": [verdict],
            "shared_primary_issues": issues,
            "unique_primary_issues": {str(only.get("ordering_label", "run_0")): []},
            "drift_summary": _sanitize_for_json(summary_raw[:2000]),
            "final_verdict": verdict,
            "compare_status": "partial_failure",
        }

    # Multi-run path
    verdicts: list[str] = []
    issue_sets: list[set[str]] = []
    labels: list[str] = []
    for idx, run in enumerate(runs):
        v = run.get("verdict")
        if v not in _RANK:
            raise ValueError(f"unknown verdict {v!r}; expected one of {list(_RANK)}")
        verdicts.append(str(v))
        run_issues: Iterable[object] = cast(Iterable[object], run.get("primary_issues") or [])
        issue_sets.append({str(i) for i in run_issues})
        labels.append(str(run.get("ordering_label", f"run_{idx}")))

    # Strict-wins (AC-7, INV-4)
    final_verdict = max(verdicts, key=lambda x: _RANK[x])

    # Shared / unique issue computation (EC-10: set-based, order-agnostic)
    shared_set: set[str] = set.intersection(*issue_sets) if issue_sets else set()
    shared_primary_issues = sorted(shared_set)
    unique_primary_issues: dict[str, list[str]] = {}
    for label, s in zip(labels, issue_sets):
        unique_primary_issues[label] = sorted(s - shared_set)

    # Drift detection (AC-6): verdict mismatch OR Jaccard overlap < 0.5
    verdict_mismatch = len(set(verdicts)) > 1
    union_set: set[str] = set.union(*issue_sets) if issue_sets else set()
    overlap = (len(shared_set) / len(union_set)) if union_set else 1.0
    overlap_low = overlap < 0.5
    drift_detected = verdict_mismatch or overlap_low

    # Drift summary (EC-13: truncate BEFORE sanitize; INV-8: sanitize after)
    summary_raw_opt: str | None
    if drift_detected:
        reasons: list[str] = []
        if verdict_mismatch:
            reasons.append(f"verdicts disagree: {verdicts}")
        if overlap_low:
            reasons.append(f"primary-issue overlap {overlap:.2f} < 0.50")
        summary_raw_opt = "; ".join(reasons)
    else:
        summary_raw_opt = None

    drift_summary: str | None = (
        _sanitize_for_json(summary_raw_opt[:2000]) if summary_raw_opt is not None else None
    )

    return {
        "drift_detected": drift_detected,
        "verdicts": verdicts,
        "shared_primary_issues": shared_primary_issues,
        "unique_primary_issues": unique_primary_issues,
        "drift_summary": drift_summary,
        "final_verdict": final_verdict,
        "compare_status": None,
    }


# Modes accepted by record_review_ordering (broader than REVIEW_VALID_MODES because
# 'compare-orderings' is set at the SKILL.md aggregator layer, not the helper layer).
_ORDERING_RECORD_MODES: tuple[str, ...] = (
    "default",
    "reverse-sections",
    "shuffle-sections",
    "compare-orderings",
)


def record_review_ordering(
    mode: str,
    seed: int | None = None,
    runs: list[dict[str, object]] | None = None,
    drift: dict[str, object] | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    """Stage an ordering payload for the next create_review_bundle call (INV-10).

    Stores the payload in the module-level ``_PENDING_REVIEW_ORDERING`` singleton,
    which create_review_bundle() consumes and clears in a single atomic read.

    CRITICAL: this function MUST NOT call ``_set_manifest_stage``,
    ``save_artifact_manifest``, ``load_artifact_manifest``, or ``_write_json_file``.
    The single-writer rule (INV-10) reserves all manifest writes for
    create_review_bundle().
    """
    global _PENDING_REVIEW_ORDERING

    if mode not in _ORDERING_RECORD_MODES:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {_ORDERING_RECORD_MODES}"
        )

    runs_payload: list[dict[str, object]] = (
        [dict(run) for run in runs] if runs is not None else []
    )

    # Drift sub-payload: pull fields from the compare_review_runs result dict
    drift_detected = bool((drift or {}).get("drift_detected", False))
    drift_summary_raw = (drift or {}).get("drift_summary")
    final_verdict = (drift or {}).get("final_verdict")
    compare_status = (drift or {}).get("compare_status")

    # Sanitize string fields (INV-8). Truncate drift_summary to 2000 chars first (EC-13).
    drift_summary: str | None
    if drift_summary_raw is None:
        drift_summary = None
    else:
        drift_summary = _sanitize_for_json(str(drift_summary_raw)[:2000])

    final_verdict_str: str | None = (
        _sanitize_for_json(str(final_verdict)) if final_verdict is not None else None
    )
    compare_status_str: str | None = (
        _sanitize_for_json(str(compare_status)) if compare_status is not None else None
    )

    payload: dict[str, object] = {
        "mode": mode,
        "seed": seed,
        "runs": runs_payload,
        "drift_detected": drift_detected,
        "drift_summary": drift_summary,
        "final_verdict": final_verdict_str,
        "compare_status": compare_status_str,
    }

    # Stage to BOTH the module-level dict (for in-process pytest tests) AND a
    # branch-scoped file (for the real cross-subprocess SKILL.md workflow).
    # See PENDING_ORDERING_FILENAME comment.
    _PENDING_REVIEW_ORDERING = payload
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    pending_path: Path | None = None
    if branch_name:
        try:
            branch_dir = get_branch_dir(branch_name)
            branch_dir.mkdir(parents=True, exist_ok=True)
            pending_path = branch_dir / PENDING_ORDERING_FILENAME
            pending_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pending_path = None

    return {
        "status": "ok",
        "staged": True,
        "mode": mode,
        "branch": branch_name,
        "pending_path": str(pending_path) if pending_path else None,
        # legacy field for callers that referenced the old API
        "branch_in": branch,
    }


def _read_branch_artifact_text(branch_dir: Path, name: str) -> str:
    """Read a branch artifact, treating untouched managed placeholders as empty."""
    path = branch_dir / name
    if not path.exists():
        return ""
    try:
        content = _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""

    default_content = HUMAN_ARTIFACT_DEFAULTS.get(name)
    if default_content and content.strip() == default_content.strip():
        return ""
    return content


def build_handoff_bundle(branch: Optional[str] = None) -> dict:
    """Build a compact handoff bundle from branch-scoped human artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    ensure_human_artifacts(branch_name)

    verification = _read_branch_artifact_text(branch_dir, "verification-summary.md")
    qa = _read_branch_artifact_text(branch_dir, "qa-001.md")
    active_issues = _read_branch_artifact_text(branch_dir, "active-issues.json")
    verification_gate = _read_branch_artifact_text(branch_dir, "verification-gate.json")
    review_path = next_numbered_artifact_path("code-review", branch_name)
    latest_review_index = max(0, review_path["index"] - 1)
    latest_review_name = (
        f"code-review-{latest_review_index:03d}.md" if latest_review_index > 0 else ""
    )
    latest_review = (
        _read_branch_artifact_text(branch_dir, latest_review_name)
        if latest_review_name
        else ""
    )

    summary = []
    if verification:
        summary.append("- Verification summary available")
    if verification_gate:
        summary.append("- Verification gate recorded")
    if latest_review:
        summary.append(f"- Latest review: {latest_review_name}")
    if latest_review:
        summary.append("- Code review history available")
    if active_issues:
        summary.append("- Active unresolved issues tracked")

    validation = []
    if verification:
        validation.append(verification.strip())
    if qa:
        validation.append(qa.strip())
    if verification_gate:
        validation.append(verification_gate.strip())

    risks = []
    if latest_review:
        risks.append(latest_review.strip())
    if active_issues:
        risks.append(active_issues.strip())

    return {
        "status": "success",
        "branch": branch_name,
        "summary": "\n".join(summary) or "- [not recorded]",
        "validation": "\n\n".join(validation) or "- [not recorded]",
        "risks_follow_up": "\n\n".join(risks) or "- [not recorded]",
    }


def build_review_handoff(branch: Optional[str] = None) -> dict:
    """Build final review context from planning, execution, and verification artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)

    plan_review_next = next_numbered_artifact_path("plan-review", branch_name)
    latest_plan_review_index = max(0, plan_review_next["index"] - 1)
    latest_plan_review_name = (
        f"plan-review-{latest_plan_review_index:03d}.md"
        if latest_plan_review_index > 0
        else ""
    )
    code_review_next = next_numbered_artifact_path("code-review", branch_name)
    latest_code_review_index = max(0, code_review_next["index"] - 1)
    latest_code_review_name = (
        f"code-review-{latest_code_review_index:03d}.md"
        if latest_code_review_index > 0
        else ""
    )

    payload = {
        "status": "success",
        "branch": branch_name,
        "plan_review_path": latest_plan_review_name or None,
        "code_review_path": latest_code_review_name or None,
        "verification_summary_path": "verification-summary.md"
        if (branch_dir / "verification-summary.md").exists()
        else None,
        "qa_path": "qa-001.md" if (branch_dir / "qa-001.md").exists() else None,
        "pr_draft_path": "pr-draft.md"
        if (branch_dir / "pr-draft.md").exists()
        else None,
        "active_issues_path": "active-issues.json"
        if (branch_dir / "active-issues.json").exists()
        else None,
        "plan_review": _read_branch_artifact_text(branch_dir, latest_plan_review_name)
        if latest_plan_review_name
        else None,
        "code_review": _read_branch_artifact_text(branch_dir, latest_code_review_name)
        if latest_code_review_name
        else None,
        "verification_summary": _read_branch_artifact_text(
            branch_dir, "verification-summary.md"
        ),
        "qa": _read_branch_artifact_text(branch_dir, "qa-001.md"),
        "pr_draft": _read_branch_artifact_text(branch_dir, "pr-draft.md"),
        "active_issues": _read_branch_artifact_text(branch_dir, "active-issues.json")
        or None,
    }

    # Surface ordering metadata for /map-learn consumers (AC-13).
    # Read review-bundle.json if present; fall back to safe defaults (EC-7)
    # when the file is absent, unreadable, or from a legacy bundle without
    # the "ordering" key.  No exception must escape — handoff must always
    # succeed regardless of ordering availability.
    bundle_path = branch_dir / "review-bundle.json"
    ordering: dict[str, object] = {}
    if bundle_path.exists():
        try:
            with bundle_path.open(encoding="utf-8") as fh:
                bundle_data = json.load(fh)
            if isinstance(bundle_data, dict):
                raw_ordering = bundle_data.get("ordering")
                if isinstance(raw_ordering, dict):
                    ordering = raw_ordering
        except (OSError, ValueError):
            ordering = {}

    payload["review_order_mode"] = str(ordering.get("mode", "default")) if ordering else "default"
    payload["review_order_seed"] = ordering.get("seed") if ordering else None
    payload["drift_detected"] = bool(ordering.get("drift_detected", False)) if ordering else False
    payload["compare_status"] = ordering.get("compare_status") if ordering else None

    return payload


_REVIEW_BUNDLE_TRUNCATE_CHARS = 4000
"""Max sanitized characters to embed per artifact text field.

Reviewers need enough context to assess the artifact, not a full copy.
Files larger than this threshold are truncated; ``truncated: true`` is
recorded so the reviewer knows to open the full file on disk.
"""


def _collect_numbered_artifact(
    branch_dir: Path,
    prefix: str,
) -> dict:
    """Scan branch_dir for ``<prefix>-NNN.md`` files and return the highest one.

    Returns a dict with keys: ``present``, ``path`` (str or None),
    ``index`` (int or None), ``sanitized_text`` (str or None),
    ``truncated`` (bool, omitted when not applicable), ``reason`` (str or None).
    """
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}})\.md$")
    best_index = 0
    best_name = ""
    try:
        for dir_entry in branch_dir.iterdir():
            m = pattern.match(dir_entry.name)
            if m:
                idx = int(m.group(1))
                if idx > best_index:
                    best_index = idx
                    best_name = dir_entry.name
    except OSError:
        pass

    if not best_name:
        return {
            "present": False,
            "path": None,
            "index": None,
            "sanitized_text": None,
            "reason": "none recorded",
        }

    full_path = branch_dir / best_name
    raw = _read_branch_artifact_text(branch_dir, best_name)
    entry: dict = {
        "present": True,
        "path": str(full_path),
        "index": best_index,
    }
    if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
        entry["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
        entry["truncated"] = True
    else:
        entry["sanitized_text"] = raw or None
        entry["truncated"] = False
    entry["reason"] = None
    return entry


def _collect_multi_artifacts(
    branch_dir: Path,
    glob_pattern: str,
) -> list[dict]:
    """Collect all files matching glob_pattern and return a list of artifact entries.

    Each entry: ``{path, sanitized_text, truncated}``.
    Returns an empty list when no files match.
    """
    results = []
    try:
        for entry in sorted(branch_dir.glob(glob_pattern)):
            if not entry.is_file():
                continue
            raw = _sanitize_for_json(
                entry.read_text(encoding="utf-8", errors="replace")
            )
            item: dict = {"path": str(entry)}
            if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
                item["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
                item["truncated"] = True
            else:
                item["sanitized_text"] = raw or None
                item["truncated"] = False
            results.append(item)
    except OSError:
        pass
    return results


def _is_soft_stub_text(name: str, text: str) -> bool:
    """Detect whether artifact text is a soft stub (writer output with no real data).

    Differs from the strict ``HUMAN_ARTIFACT_DEFAULTS`` byte-match: this catches the case
    where ``write_verification_summary`` / ``write_pr_draft`` were called with empty args,
    which produces section bodies of ``- [not recorded]`` while the branch name and/or
    verdict line are dynamically interpolated. Reviewers should treat such artifacts as
    absent (``present=false``) rather than as filled content.

    Note: the input ``text`` has been flattened by ``_sanitize_for_json`` (newlines and
    tabs collapsed to spaces), so the section markers are matched in their post-sanitize
    form (e.g., ``## Summary - [not recorded]`` rather than ``## Summary\n- [not recorded]``).
    """
    if not text:
        return False
    if name == "pr-draft.md":
        return (
            text.lstrip().startswith("# PR Draft")
            and "## Summary - [not recorded]" in text
            and "## Validation - [not recorded]" in text
            and "## Risks / Follow-up - [not recorded]" in text
        )
    if name == "verification-summary.md":
        return (
            text.lstrip().startswith("# Verification Summary")
            and "## Checks Run - [not recorded]" in text
            and "## Findings - [not recorded]" in text
            and "## Next Action - [not recorded]" in text
        )
    return False


def _fixed_artifact_entry(branch_dir: Path, name: str, kind: str) -> dict:
    """Return a single artifact entry for a fixed-name file.

    Keys: ``present``, ``path``, ``sanitized_text`` (or None), ``truncated``
    (omitted if not applicable), ``reason`` (or None), ``kind``.
    """
    full_path = branch_dir / name
    if not full_path.exists():
        return {
            "present": False,
            "path": None,
            "sanitized_text": None,
            "kind": kind,
            "reason": "not found",
        }
    raw = _read_branch_artifact_text(branch_dir, name)
    # Stub detection: ``raw`` is "" when content matches ``HUMAN_ARTIFACT_DEFAULTS[name]``
    # (initial stub from ``ensure_human_artifacts``). ``_is_soft_stub_text`` catches the
    # case where the writer was called with empty args, producing a placeholder body.
    if not raw and HUMAN_ARTIFACT_DEFAULTS.get(name) is not None:
        return {
            "present": False,
            "path": str(full_path),
            "sanitized_text": None,
            "kind": kind,
            "reason": "stub: matches initial placeholder",
        }
    if raw and _is_soft_stub_text(name, raw):
        return {
            "present": False,
            "path": str(full_path),
            "sanitized_text": None,
            "kind": kind,
            "reason": "stub: writer emitted placeholder body",
        }
    entry: dict = {
        "present": True,
        "path": str(full_path),
        "kind": kind,
        "reason": None,
    }
    if len(raw) > _REVIEW_BUNDLE_TRUNCATE_CHARS:
        entry["sanitized_text"] = raw[:_REVIEW_BUNDLE_TRUNCATE_CHARS]
        entry["truncated"] = True
    else:
        entry["sanitized_text"] = raw or None
        entry["truncated"] = False
    return entry


def _bundle_review_handoff_text_fields(handoff: dict) -> dict:
    """Extract only the sanitized text content fields from build_review_handoff output."""
    return {
        "plan_review": handoff.get("plan_review"),
        "code_review": handoff.get("code_review"),
        "verification_summary": handoff.get("verification_summary") or None,
        "qa": handoff.get("qa") or None,
        "pr_draft": handoff.get("pr_draft") or None,
        "active_issues": handoff.get("active_issues"),
    }


def _bundle_pr_handoff_fields(bundle: dict) -> dict:
    """Extract PR handoff summary fields from build_handoff_bundle output."""
    return {
        "summary": bundle.get("summary", "- [not recorded]"),
        "validation": bundle.get("validation", "- [not recorded]"),
        "risks_follow_up": bundle.get("risks_follow_up", "- [not recorded]"),
    }


def _render_bundle_markdown(result: dict) -> str:
    """Render the review bundle as a human-readable Markdown document."""
    branch = result.get("branch", "unknown")
    generated_at = result.get("generated_at", "")
    artifacts = result.get("artifacts", {})
    code_state = result.get("code_state", {})
    review_handoff = result.get("review_handoff", {})
    pr_handoff = result.get("pr_handoff", {})
    acceptance_coverage = result.get("acceptance_coverage", {})
    prior_stage_consumption = result.get("prior_stage_consumption", {})

    lines = [
        f"# Review Bundle — `{branch}`",
        "",
        f"Generated: {generated_at}",
        f"Bundle JSON: `{result.get('bundle_path_json', '')}`",
        "",
    ]

    # Missing artifacts section (INV-4: every absent artifact listed)
    missing = []
    for key, val in artifacts.items():
        if key in ("test_handoffs", "test_contracts"):
            if isinstance(val, list) and not val:
                missing.append(f"- `{key}`: none recorded")
        elif isinstance(val, dict) and not val.get("present", True):
            reason = val.get("reason", "not found")
            missing.append(f"- `{key}`: {reason}")

    if missing:
        lines += ["## Missing Artifacts", ""]
        lines += missing
        lines += [""]

    # Artifact inventory
    lines += ["## Artifact Inventory", ""]
    for key, val in artifacts.items():
        if key in ("test_handoffs", "test_contracts"):
            count = len(val) if isinstance(val, list) else 0
            lines.append(f"- **{key}**: {count} file(s)")
        elif isinstance(val, dict):
            status = "present" if val.get("present") else "MISSING"
            path = val.get("path") or "—"
            lines.append(f"- **{key}** [{status}]: `{path}`")
    lines += [""]

    # Code state
    lines += ["## Code State", ""]
    cs_status = code_state.get("status", "unknown")
    if cs_status == "success":
        lines.append(f"- Git ref: `{code_state.get('git_ref', 'unknown')}`")
        lines.append(f"- Branch: `{code_state.get('branch', 'unknown')}`")
        files = code_state.get("files_changed", [])
        lines.append(f"- Files changed: {len(files)}")
        diff_stat = code_state.get("diff_stat", "")
        if diff_stat:
            lines.append(f"- Diff stat: {diff_stat[:200]}")
    else:
        lines.append(f"- Status: {cs_status}")
        reason = code_state.get("reason", "")
        if reason:
            lines.append(f"- Reason: {reason}")
    lines += [""]

    # Review handoff text summaries
    lines += ["## Review Handoff Context", ""]
    for field in ("plan_review", "code_review", "verification_summary", "qa", "pr_draft", "active_issues"):
        val = review_handoff.get(field)
        if val:
            label = field.replace("_", " ").title()
            lines.append(f"### {label}")
            lines.append("")
            lines.append(val[:500] + ("…" if len(val) > 500 else ""))
            lines.append("")

    # Acceptance coverage
    if isinstance(acceptance_coverage, dict):
        lines.append(_render_acceptance_coverage_markdown(acceptance_coverage).rstrip())
        lines.append("")

    # Prior-stage consumption
    if isinstance(prior_stage_consumption, dict):
        lines.append(_render_prior_stage_consumption_markdown(prior_stage_consumption).rstrip())
        lines.append("")

    # PR handoff
    lines += ["## PR Handoff Summary", ""]
    lines.append(pr_handoff.get("summary", "- [not recorded]"))
    lines += [""]

    return "\n".join(lines)


def create_review_bundle(branch: Optional[str] = None) -> dict:
    """Write a durable reviewer-facing bundle under .map/<branch>/.

    Collects all branch-scoped artifacts into a structured inventory,
    sanitizes text content, and writes both ``review-bundle.json`` and
    ``review-bundle.md``.  Missing optional artifacts are recorded
    explicitly (INV-4) rather than silently omitted.  Control characters
    are stripped via ``_sanitize_for_json`` so the JSON file remains
    parseable by downstream tools (INV-8).
    """
    # ``get_branch_name`` already sanitizes; explicit ``branch`` callers must be
    # sanitized too so e.g. ``feat/foo`` lands at ``.map/feat-foo/`` instead of a
    # nested ``.map/feat/foo/`` directory.
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_timestamp()

    bundle_json_path = branch_dir / "review-bundle.json"
    bundle_md_path = branch_dir / "review-bundle.md"

    # --- Artifact inventory ---
    fixed_artifacts: dict[str, dict] = {
        "spec": _fixed_artifact_entry(
            branch_dir, f"spec_{branch_name}.md", "spec"
        ),
        "task_plan": _fixed_artifact_entry(
            branch_dir, f"task_plan_{branch_name}.md", "task_plan"
        ),
        "blueprint": _fixed_artifact_entry(
            branch_dir, "blueprint.json", "blueprint"
        ),
        "verification_summary": _fixed_artifact_entry(
            branch_dir, "verification-summary.md", "verification_summary"
        ),
        "qa": _fixed_artifact_entry(
            branch_dir, "qa-001.md", "qa"
        ),
        "pr_draft": _fixed_artifact_entry(
            branch_dir, "pr-draft.md", "pr_draft"
        ),
        "active_issues": _fixed_artifact_entry(
            branch_dir, "active-issues.json", "active_issues"
        ),
        "artifact_manifest": _fixed_artifact_entry(
            branch_dir, "artifact_manifest.json", "artifact_manifest"
        ),
        "run_health_report": _fixed_artifact_entry(
            branch_dir, "run_health_report.json", "run_health_report"
        ),
    }

    latest_plan_review = _collect_numbered_artifact(branch_dir, "plan-review")
    latest_code_review = _collect_numbered_artifact(branch_dir, "code-review")

    test_handoffs = _collect_multi_artifacts(branch_dir, "test_handoff_*.json")
    test_contracts = _collect_multi_artifacts(branch_dir, "test_contract_*.md")

    artifacts: dict = {}
    artifacts.update(fixed_artifacts)
    artifacts["latest_plan_review"] = latest_plan_review
    artifacts["latest_code_review"] = latest_code_review
    artifacts["test_handoffs"] = test_handoffs
    artifacts["test_contracts"] = test_contracts

    # --- Code state ---
    try:
        code_state = snapshot_code_state(branch_name)
    except Exception as exc:
        code_state = {"status": "unavailable", "reason": str(exc)}

    # --- Review handoff context (text fields only) ---
    try:
        review_handoff_raw = build_review_handoff(branch_name)
        review_handoff = _bundle_review_handoff_text_fields(review_handoff_raw)
    except Exception as exc:
        review_handoff = {
            "plan_review": None,
            "code_review": None,
            "verification_summary": None,
            "qa": None,
            "pr_draft": None,
            "active_issues": None,
            "_error": str(exc),
        }

    # --- PR handoff summary ---
    try:
        pr_bundle_raw = build_handoff_bundle(branch_name)
        pr_handoff = _bundle_pr_handoff_fields(pr_bundle_raw)
    except Exception as exc:
        pr_handoff = {
            "summary": "- [not recorded]",
            "validation": "- [not recorded]",
            "risks_follow_up": "- [not recorded]",
            "_error": str(exc),
        }

    acceptance_coverage = build_acceptance_coverage_report(branch_name)
    prior_stage_consumption = build_prior_stage_consumption_report(
        "review", branch_name, code_state=code_state
    )

    # --- Ordering payload (INV-10 single-writer staging) ---
    # Consume from BOTH the file (cross-subprocess durable path) and the module
    # dict (in-process pytest path), preferring whichever is present. Clear both
    # immediately to prevent stale reuse on a second call.
    global _PENDING_REVIEW_ORDERING
    pending_in_memory = _PENDING_REVIEW_ORDERING
    _PENDING_REVIEW_ORDERING = None

    pending_file_path = branch_dir / PENDING_ORDERING_FILENAME
    pending_from_file: dict[str, object] | None = None
    if pending_file_path.exists():
        try:
            with pending_file_path.open(encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                pending_from_file = loaded
        except (OSError, ValueError):
            pending_from_file = None
        finally:
            # Delete unconditionally — staging is one-shot per AC-4 / EC-11 semantics
            try:
                pending_file_path.unlink()
            except OSError:
                pass

    pending = pending_in_memory or pending_from_file
    if pending is None:
        # EC-7 default: normal single-pass review with no ordering staged
        ordering_payload: dict[str, object] = {
            "mode": "default",
            "seed": None,
            "runs": [],
            "drift_detected": False,
            "drift_summary": None,
            "final_verdict": None,
            "compare_status": None,
        }
    else:
        ordering_payload = pending

    result: dict = {
        "status": "success",
        "branch": branch_name,
        "bundle_path_json": str(bundle_json_path),
        "bundle_path_md": str(bundle_md_path),
        "generated_at": generated_at,
        "artifacts": artifacts,
        "code_state": code_state,
        "review_handoff": review_handoff,
        "pr_handoff": pr_handoff,
        "acceptance_coverage": acceptance_coverage,
        "prior_stage_consumption": prior_stage_consumption,
        "ordering": ordering_payload,
    }

    # Soft schema validation: warn on drift but still write the bundle.
    # Uses optional ``mapify_cli.schemas`` import (graceful fallback if the package is
    # absent in a standalone .map/ install). On validation failure the errors are recorded
    # on the result under ``schema_validation_error`` and the manifest stage status is
    # downgraded from "ready" to "warn" below.
    try:
        import importlib as _importlib

        _schemas_mod = sys.modules.get("mapify_cli.schemas")
        if _schemas_mod is None:
            _schemas_mod = _importlib.import_module("mapify_cli.schemas")
        _review_bundle_schema = getattr(_schemas_mod, "REVIEW_BUNDLE_SCHEMA", None)
        _validate_artifact_fn = getattr(_schemas_mod, "validate_artifact", None)
        if _review_bundle_schema is not None and _validate_artifact_fn is not None:
            _is_valid, _errors = _validate_artifact_fn(result, _review_bundle_schema)
            if not _is_valid:
                result["schema_validation_error"] = _errors
    except ImportError:
        pass

    # Write JSON bundle (ensure_ascii=True for jq-safe output per INV-8)
    bundle_json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    # Write human-readable Markdown bundle
    bundle_md_path.write_text(
        _render_bundle_markdown(result),
        encoding="utf-8",
    )

    # --- Manifest integration (AC-4 / INV-5) ---
    # Both bundle files are written; now record them in artifact_manifest.json.
    # Failure here must NOT prevent the caller from receiving the bundle result.
    try:
        manifest = load_artifact_manifest(branch_name)
        artifacts_list = [
            _artifact_ref(bundle_json_path, "review-bundle"),
            _artifact_ref(bundle_md_path, "review-bundle"),
        ]

        # Count present/missing entries from the inventory already built above.
        present_count = 0
        missing_count = 0
        for key, val in artifacts.items():
            if key in ("test_handoffs", "test_contracts"):
                present_count += len(val) if isinstance(val, list) else 0
            elif isinstance(val, dict):
                if val.get("present"):
                    present_count += 1
                else:
                    missing_count += 1

        metadata: dict = {
            "bundle_status": result["status"],
            "selected_artifacts": present_count,
            "missing_artifacts": missing_count,
            "branch": branch_name,
            "generated_at": result["generated_at"],
            "ordering": ordering_payload,
            "acceptance_coverage": acceptance_coverage.get("summary")
            if isinstance(acceptance_coverage, dict)
            else {},
            "prior_stage_consumption": prior_stage_consumption.get("summary")
            if isinstance(prior_stage_consumption, dict)
            else {},
        }
        stage_status = (
            "warn"
            if "schema_validation_error" in result
            or not prior_stage_consumption.get("valid", False)
            else "ready"
        )
        _set_manifest_stage(
            manifest, "review", stage_status, artifacts=artifacts_list, metadata=metadata
        )
        save_result = save_artifact_manifest(manifest, branch_name)
        result["manifest_status"] = {"status": stage_status, "path": save_result["path"]}
    except Exception as exc:
        result["manifest_status"] = {"status": "error", "reason": str(exc)}

    return result


REVIEW_PROMPT_SPECS: dict[str, dict[str, str]] = {
    "monitor": {
        "subagent_type": "monitor",
        "description": "Review code changes",
        "task": "Review code correctness, standards, security, tests, and performance.",
        "instructions": """Check for:
- Code correctness and logic errors
- Security vulnerabilities (OWASP top 10)
- Standards compliance
- Test coverage gaps
- Performance issues""",
        "expected_output": """Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before verdict fields and include at least one item for every HIGH/CRITICAL issue
- valid: boolean
- summary: string
- verdict: 'approved' | 'needs_revision' | 'rejected'
- issues: array of {severity, category, description, file_path, line_range, suggestion}
- passed_checks: array of strings
- failed_checks: array of strings""",
    },
    "predictor": {
        "subagent_type": "predictor",
        "description": "Analyze change impact",
        "task": "Analyze the impact and risk of the change.",
        "instructions": """Analyze:
- Affected components and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment (low/medium/high/critical)
- Integration points affected""",
        "expected_output": """Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before risk_assessment and include evidence for each breaking change or high-risk claim
- risk_assessment: 'low' | 'medium' | 'high' | 'critical'
- predicted_state:
    affected_components: array of affected files/modules
    breaking_changes: array of {type, description, mitigation}
    required_updates: array of strings
- confidence:
    score: float 0.0-1.0""",
    },
    "evaluator": {
        "subagent_type": "evaluator",
        "description": "Score change quality",
        "task": "Score the change quality using the review bundle and diff evidence.",
        "instructions": """Provide quality assessment using 1-10 scoring:
- Functionality score (1-10)
- Code quality score (1-10)
- Performance score (1-10)
- Security score (1-10)
- Testability score (1-10)
- Completeness score (1-10)""",
        "expected_output": """Output JSON with:
- evidence: array of {file_path, line_range, quote, relevance}; populate this before scores and include evidence for any score below 7
- scores: {functionality, code_quality, performance, security, testability, completeness}
- overall_score: weighted float (1.0-10.0)
- recommendation: 'proceed' | 'improve' | 'reconsider'
- strengths: array of strings
- weaknesses: array of strings
- next_steps: array of strings""",
    },
}


def _review_prompt_budget_tokens(explicit_budget: Optional[int] = None) -> int:
    """Return the hard estimated-token budget for each review fan-out prompt."""
    if explicit_budget is not None and explicit_budget >= REVIEW_PROMPT_MIN_BUDGET_TOKENS:
        return explicit_budget

    raw = os.environ.get(REVIEW_PROMPT_BUDGET_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= REVIEW_PROMPT_MIN_BUDGET_TOKENS:
                return value
        except ValueError:
            pass
    return REVIEW_PROMPT_DEFAULT_BUDGET_TOKENS


def _read_review_bundle_markdown(branch_name: str) -> str:
    bundle_path = get_branch_dir(branch_name) / "review-bundle.md"
    try:
        return bundle_path.read_text(encoding="utf-8")
    except OSError:
        return "[review-bundle.md missing; run create_review_bundle before launching reviewers]"


def _read_git_diff_for_review() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return f"[git diff unavailable: {exc}]"
    if result.returncode != 0:
        reason = result.stderr.strip() or "git diff exited non-zero"
        return f"[git diff unavailable: {reason}]"
    return result.stdout.strip() or "[no git diff output]"


def _render_review_prompt(
    spec: dict[str, str],
    review_bundle: str,
    review_preferences: str,
    git_diff: str,
    budget_note: str = "",
) -> str:
    preferences = review_preferences.strip() or "[no additional review preferences]"
    documents = [
        "<documents>",
        "  <document source='.map/<branch>/review-bundle.md' priority='primary'>",
        "    <document_content>",
        review_bundle,
        "    </document_content>",
        "  </document>",
        "  <document source='review-preferences'>",
        "    <document_content>",
        preferences,
        "    </document_content>",
        "  </document>",
        "  <document source='git diff' priority='secondary'>",
        "    <document_content>",
        git_diff,
        "    </document_content>",
        "  </document>",
    ]
    if budget_note:
        documents.extend(
            [
                "  <document source='review-prompt-budget' priority='diagnostic'>",
                "    <document_content>",
                budget_note,
                "    </document_content>",
                "  </document>",
            ]
        )
    documents.append("</documents>")

    return "\n\n".join(
        [
            "\n".join(documents),
            f"<task>\n{spec['task']}\n</task>",
            "<workflow_policy>\n"
            "Read the persisted review bundle first. Use the raw diff only to "
            "confirm or expand specific findings the bundle surfaces.\n"
            "</workflow_policy>",
            f"<instructions>\n{spec['instructions']}\n</instructions>",
            f"<expected_output>\n{spec['expected_output']}\n</expected_output>",
        ]
    )


def _budget_review_prompt(
    spec: dict[str, str],
    review_bundle: str,
    review_preferences: str,
    git_diff: str,
    budget_tokens: int,
) -> dict[str, object]:
    full_prompt = _render_review_prompt(
        spec, review_bundle, review_preferences, git_diff
    )
    full_estimate = _estimate_tokens(full_prompt)
    if full_estimate <= budget_tokens:
        return {
            "prompt": full_prompt,
            "estimated_tokens": full_estimate,
            "budget_tokens": budget_tokens,
            "truncated": False,
            "clipped_sections": [],
        }

    budget_note = (
        f"Review Prompt Budget: truncated to <= {budget_tokens} estimated tokens. "
        "The persisted review bundle remains primary; lower-priority raw diff "
        f"context is clipped first. Increase {REVIEW_PROMPT_BUDGET_ENV} if a "
        "larger review prompt is required."
    )

    clipped_sections: list[str] = []
    base_prompt = _render_review_prompt(spec, "", review_preferences, "", budget_note)
    remaining_for_documents = budget_tokens - _estimate_tokens(base_prompt)
    bundle_budget = max(0, remaining_for_documents)
    budgeted_bundle = review_bundle
    if _estimate_tokens(review_bundle) > bundle_budget:
        budgeted_bundle = _truncate_to_token_budget(review_bundle, bundle_budget)
        clipped_sections.append("review-bundle.md")

    prompt_without_diff = _render_review_prompt(
        spec, budgeted_bundle, review_preferences, "", budget_note
    )
    remaining_for_diff = budget_tokens - _estimate_tokens(prompt_without_diff)
    diff_budget = max(0, remaining_for_diff)
    budgeted_diff = git_diff
    if _estimate_tokens(git_diff) > diff_budget:
        budgeted_diff = _truncate_to_token_budget(git_diff, diff_budget)
        clipped_sections.append("git diff")

    prompt = _render_review_prompt(
        spec, budgeted_bundle, review_preferences, budgeted_diff, budget_note
    )
    if _estimate_tokens(prompt) > budget_tokens:
        # Guard against note/rounding drift: drop secondary diff, then tighten primary text.
        budgeted_diff = ""
        prompt_without_docs = _render_review_prompt(spec, "", review_preferences, "", budget_note)
        bundle_budget = max(0, budget_tokens - _estimate_tokens(prompt_without_docs))
        budgeted_bundle = _truncate_to_token_budget(review_bundle, bundle_budget)
        prompt = _render_review_prompt(
            spec, budgeted_bundle, review_preferences, budgeted_diff, budget_note
        )
        for section in ("git diff", "review-bundle.md"):
            if section not in clipped_sections:
                clipped_sections.append(section)

    return {
        "prompt": prompt,
        "estimated_tokens": _estimate_tokens(prompt),
        "budget_tokens": budget_tokens,
        "truncated": True,
        "clipped_sections": clipped_sections,
        "full_estimated_tokens": full_estimate,
    }


def build_review_prompts(
    branch: Optional[str] = None,
    review_preferences: str = "",
    budget_tokens: Optional[int] = None,
    review_bundle_text: Optional[str] = None,
    git_diff_text: Optional[str] = None,
) -> dict:
    """Build bounded `/map-review` fan-out prompts for Monitor/Predictor/Evaluator."""
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    budget = _review_prompt_budget_tokens(budget_tokens)
    review_bundle = (
        review_bundle_text
        if review_bundle_text is not None
        else _read_review_bundle_markdown(branch_name)
    )
    git_diff = git_diff_text if git_diff_text is not None else _read_git_diff_for_review()

    prompts: dict[str, dict[str, object]] = {}
    for role, spec in REVIEW_PROMPT_SPECS.items():
        prompt_result = _budget_review_prompt(
            spec, review_bundle, review_preferences, git_diff, budget
        )
        prompts[role] = {
            "subagent_type": spec["subagent_type"],
            "description": spec["description"],
            **prompt_result,
        }

    return {
        "status": "success",
        "branch": branch_name,
        "budget_tokens": budget,
        "budget_env": REVIEW_PROMPT_BUDGET_ENV,
        "prompts": prompts,
    }


def write_learning_handoff(
    workflow: str,
    task_title: str = "",
    outcome: str = "",
    next_action: str = "",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Write a reusable learning handoff artifact for deferred /map-learn runs."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    branch_dir.mkdir(parents=True, exist_ok=True)

    def read(name: str) -> str:
        path = branch_dir / name
        if not path.exists():
            return ""
        try:
            return _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

    def read_json(name: str) -> Optional[dict[str, object]]:
        raw = read(name)
        if not raw:
            return None
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None

    workflow_name = workflow.strip() or "map-workflow"
    goal = task_title.strip() or read_current_goal(branch_name) or "Workflow summary"
    outcome_text = outcome.strip() or "Learning handoff generated"
    next_action_text = (
        next_action.strip()
        or "Run /map-learn now, or batch it later when you want to pay the learning cost."
    )
    notes_text = notes.strip()
    generated_at = _utc_timestamp()

    review_handoff = build_review_handoff(branch_name)
    bundle = build_handoff_bundle(branch_name)
    code_state = snapshot_code_state(branch_name)
    workflow_fit = read_json("workflow-fit.json")
    manifest = read_json("artifact_manifest.json")
    run_health_report = read_json("run_health_report.json")
    known_issues = read_json("known-issues.json")
    active_issues = read_json("active-issues.json")

    markdown_path = branch_dir / "learning-handoff.md"
    json_path = branch_dir / "learning-handoff.json"

    files_changed = code_state.get("files_changed") or []
    if isinstance(files_changed, list):
        files_section = "\n".join(f"- {path}" for path in files_changed) or "- [not recorded]"
    else:
        files_section = "- [not recorded]"

    artifact_paths = [
        path
        for path in [
            "workflow-fit.json" if workflow_fit else "",
            "artifact_manifest.json",
            "run_health_report.json" if run_health_report else "",
            review_handoff.get("plan_review_path") or "",
            review_handoff.get("code_review_path") or "",
            review_handoff.get("verification_summary_path") or "",
            review_handoff.get("qa_path") or "",
            review_handoff.get("pr_draft_path") or "",
            review_handoff.get("active_issues_path") or "",
            "known-issues.json" if known_issues else "",
        ]
        if path
    ]
    artifacts_section = "\n".join(f"- {path}" for path in artifact_paths) or "- [not recorded]"

    payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "workflow": workflow_name,
        "branch": branch_name,
        "task_title": goal,
        "outcome": outcome_text,
        "next_action": next_action_text,
        "notes": notes_text,
        "git_ref": code_state.get("git_ref", "unknown"),
        "files_changed": files_changed if isinstance(files_changed, list) else [],
        "summary": bundle.get("summary", "- [not recorded]"),
        "validation": bundle.get("validation", "- [not recorded]"),
        "risks_follow_up": bundle.get("risks_follow_up", "- [not recorded]"),
        "artifacts": {
            "workflow_fit": workflow_fit,
            "artifact_manifest": manifest,
            "run_health_report": run_health_report,
            "review_handoff": review_handoff,
            "known_issues": known_issues,
            "active_issues": active_issues,
        },
        "documents": {
            "plan_review": review_handoff.get("plan_review"),
            "code_review": review_handoff.get("code_review"),
            "verification_summary": review_handoff.get("verification_summary"),
            "qa": review_handoff.get("qa"),
            "pr_draft": review_handoff.get("pr_draft"),
        },
    }

    markdown = (
        "# Learning Handoff\n\n"
        f"- Workflow: `{workflow_name}`\n"
        f"- Branch: `{branch_name}`\n"
        f"- Task: {goal}\n"
        f"- Outcome: {outcome_text}\n"
        f"- Generated: {generated_at}\n"
        f"- Git ref: `{code_state.get('git_ref', 'unknown')}`\n"
        f"- Next action: {next_action_text}\n\n"
        "## Recommended Invocation\n\n"
        "Run `/map-learn` with no arguments to auto-load this handoff.\n\n"
        "If you want to pass the artifact explicitly:\n\n"
        f"`/map-learn .map/{branch_name}/learning-handoff.md`\n\n"
        "## Summary\n\n"
        f"{bundle.get('summary', '- [not recorded]')}\n\n"
        "## Validation\n\n"
        f"{bundle.get('validation', '- [not recorded]')}\n\n"
        "## Risks / Follow-up\n\n"
        f"{bundle.get('risks_follow_up', '- [not recorded]')}\n\n"
        "## Files Changed\n\n"
        f"{files_section}\n\n"
        "## Source Artifacts\n\n"
        f"{artifacts_section}\n"
    )
    if notes_text:
        markdown += f"\n## Notes\n\n{notes_text}\n"

    metrics_result = _record_learning_handoff_generation_metrics(
        workflow_name, generated_at, markdown_path, json_path, branch_name
    )
    repeated_violation_result = record_repeated_learning_violations(
        branch_name, cast(dict[str, object], metrics_result["metrics"])
    )
    repeated_violation_summary = cast(dict[str, object], repeated_violation_result["summary"])
    rvr_path = str(repeated_violation_result["path"])
    rvr_metrics = cast(dict[str, object], repeated_violation_result["metrics"])

    repeated_violation_lines = [
        f"- Findings checked: {repeated_violation_summary['finding_count']}",
        f"- Learned rules considered: {repeated_violation_summary['learned_rule_count']}",
        f"- Repeated-rule matches: {repeated_violation_summary['matched_count']}",
    ]
    for match in cast(list[dict[str, object]], repeated_violation_summary["matches"]):
        repeated_violation_lines.append(
            f"- {match['rule_title']} <= {match['finding_text']}"
        )

    manifest_payload = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest_payload,
        "learn_handoff",
        "ready",
        artifacts=[
            _artifact_ref(markdown_path, "learning-handoff-markdown"),
            _artifact_ref(json_path, "learning-handoff-json"),
            _artifact_ref(
                Path(rvr_path), "learning-handoff-metrics"
            ),
        ],
        metadata={
            "workflow": workflow_name,
            "task_title": goal,
            "outcome": outcome_text,
            "next_action": next_action_text,
            "git_ref": code_state.get("git_ref", "unknown"),
            "learning_metrics_path": rvr_path,
            "learning_metrics_counters": dict(
                cast(Mapping[str, int], rvr_metrics["counters"])
            ),
            "repeated_violation_summary": repeated_violation_summary,
        },
    )
    manifest_result = save_artifact_manifest(manifest_payload, branch_name)
    payload["artifacts"]["artifact_manifest"] = manifest_result["manifest"]
    payload["artifacts"]["learning_metrics"] = repeated_violation_result["metrics"]
    payload["artifacts"]["repeated_violation_summary"] = repeated_violation_summary
    _write_json_file(json_path, payload)
    markdown += (
        "\n## Learning Effectiveness Signals\n\n"
        f"{chr(10).join(repeated_violation_lines)}\n"
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    return {
        "status": "success",
        "branch": branch_name,
        "workflow": workflow_name,
        "task_title": goal,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "manifest_path": manifest_result["path"],
        "learning_metrics_path": repeated_violation_result["path"],
        "generated_at": generated_at,
    }


def ensure_known_issues_file(branch: Optional[str] = None) -> dict:
    """Ensure known-issues.json exists for accepted blockers / known limitations."""
    branch_dir = get_branch_dir(branch)
    branch_dir.mkdir(parents=True, exist_ok=True)
    issues_file = branch_dir / "known-issues.json"
    if not issues_file.exists():
        issues_file.write_text(
            json.dumps(KNOWN_ISSUES_DEFAULT, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return {"status": "success", "path": str(issues_file), "created": True}
    return {"status": "success", "path": str(issues_file), "created": False}


def add_known_issue(
    title: str,
    status: str = "accepted",
    notes: str = "",
    branch: Optional[str] = None,
) -> dict:
    """Append a known issue / accepted blocker entry."""
    ensure_known_issues_file(branch)
    issues_file = get_branch_dir(branch) / "known-issues.json"
    payload = json.loads(issues_file.read_text(encoding="utf-8"))
    payload.setdefault("issues", []).append(
        {
            "title": title,
            "status": status,
            "notes": notes,
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    issues_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "success",
        "path": str(issues_file),
        "count": len(payload["issues"]),
    }


from map_utils import get_branch_name  # noqa: E402  # type: ignore[import-not-found]


def update_step_state(
    subtask_id: str,
    step_name: str,
    new_state: str,
    branch: Optional[str] = None,
) -> dict:
    """
    Update step_state.json after step completion.

    Args:
        subtask_id: Subtask ID (e.g., "ST-001")
        step_name: Step name (e.g., "actor", "monitor")
        new_state: New state (e.g., "ACTOR_CALLED", "MONITOR_PASSED")
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and updated state
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {"status": "error", "message": "step_state.json not found"}

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))

        # Initialize completed_steps dict if missing
        if "completed_steps" not in state:
            state["completed_steps"] = {}

        # Initialize list for this subtask if missing
        if subtask_id not in state["completed_steps"]:
            state["completed_steps"][subtask_id] = []

        # Append step to completed list
        if step_name not in state["completed_steps"][subtask_id]:
            state["completed_steps"][subtask_id].append(step_name)

        # Update current state
        state["current_state"] = new_state
        state["current_subtask"] = subtask_id

        # Write back atomically
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_file.replace(state_file)

        return {
            "status": "success",
            "message": f"Updated {subtask_id}: {step_name} -> {new_state}",
            "completed_steps": state["completed_steps"][subtask_id],
        }

    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": str(e)}


def update_step_state_batch(
    updates: list[dict],
    branch: Optional[str] = None,
) -> dict:
    """
    Update step_state.json for multiple subtasks in one call.

    Used in wave-based parallel execution to update all subtasks in a wave
    after their actors/monitors complete.

    Args:
        updates: List of dicts, each with:
            - subtask_id: Subtask ID (e.g., "ST-002")
            - step_name: Step name (e.g., "actor", "monitor")
            - new_state: New state (e.g., "ACTOR_CALLED", "MONITOR_PASSED")
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and per-subtask results
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {"status": "error", "message": "step_state.json not found"}

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))

        if "completed_steps" not in state:
            state["completed_steps"] = {}

        results = []
        active_subtasks = []

        for update in updates:
            subtask_id = update.get("subtask_id", "")
            step_name = update.get("step_name", "")
            new_state = update.get("new_state", "")

            if subtask_id not in state["completed_steps"]:
                state["completed_steps"][subtask_id] = []

            if step_name not in state["completed_steps"][subtask_id]:
                state["completed_steps"][subtask_id].append(step_name)

            active_subtasks.append(subtask_id)
            results.append(
                {
                    "subtask_id": subtask_id,
                    "step_name": step_name,
                    "new_state": new_state,
                }
            )

        # Set active_subtasks list for wave mode (used by workflow-gate.py)
        state["active_subtasks"] = active_subtasks
        if active_subtasks:
            state["current_subtask"] = active_subtasks[0]
            state["current_state"] = updates[-1].get("new_state", "UPDATED")

        # Write back atomically
        tmp_file = state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp_file.replace(state_file)

        return {
            "status": "success",
            "message": f"Batch updated {len(updates)} subtasks",
            "results": results,
        }

    except (json.JSONDecodeError, OSError) as e:
        return {"status": "error", "message": str(e)}


def update_plan_status(
    subtask_id: str,
    new_status: str,
    branch: Optional[str] = None,
) -> dict:
    """
    Update subtask status in task_plan.md.

    Args:
        subtask_id: Subtask ID (e.g., "ST-001")
        new_status: New status (pending|in_progress|complete|blocked)
        branch: Git branch (auto-detected if None)

    Returns:
        dict with status and message
    """
    if branch is None:
        branch = get_branch_name()

    plan_file = Path(f".map/{branch}/task_plan_{branch}.md")

    if not plan_file.exists():
        return {"status": "error", "message": f"Plan file not found: {plan_file}"}

    try:
        content = plan_file.read_text(encoding="utf-8")

        # Find subtask section (### ST-XXX: Title)
        pattern = rf"(### {re.escape(subtask_id)}:.*?\n- \*\*Status:\*\*\s+)\w+"
        replacement = rf"\g<1>{new_status}"

        updated_content = re.sub(pattern, replacement, content)

        if updated_content == content:
            return {
                "status": "warning",
                "message": f"Subtask {subtask_id} not found in plan",
            }

        # Write back
        plan_file.write_text(updated_content, encoding="utf-8")

        return {
            "status": "success",
            "message": f"Updated {subtask_id} status to {new_status}",
        }

    except (OSError, re.error) as e:
        return {"status": "error", "message": str(e)}


def validate_checkpoint(
    subtask_id: str,
    required_steps: list[str],
    branch: Optional[str] = None,
) -> dict:
    """
    Validate that required steps are completed for subtask.

    Args:
        subtask_id: Subtask ID to check
        required_steps: List of step names that must be completed
        branch: Git branch (auto-detected if None)

    Returns:
        dict with valid: bool, missing_steps: list[str]
    """
    if branch is None:
        branch = get_branch_name()

    state_file = Path(f".map/{branch}/step_state.json")

    if not state_file.exists():
        return {
            "valid": False,
            "missing_steps": required_steps,
            "message": "step_state.json not found",
        }

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        completed = state.get("completed_steps", {}).get(subtask_id, [])

        missing = [step for step in required_steps if step not in completed]

        return {
            "valid": len(missing) == 0,
            "missing_steps": missing,
            "completed_steps": completed,
            "message": (
                "All required steps completed"
                if not missing
                else f"Missing steps: {', '.join(missing)}"
            ),
        }

    except (json.JSONDecodeError, OSError) as e:
        return {
            "valid": False,
            "missing_steps": required_steps,
            "message": str(e),
        }


def create_xml_packet(subtask: dict) -> str:
    """
    Create AI-friendly XML packet for subtask.

    Args:
        subtask: dict with subtask data from decomposer blueprint

    Returns:
        XML packet string
    """
    subtask_id = subtask.get("id", "ST-XXX")
    # Convert ST-001 to ST_001 for XML tag safety
    tag_id = subtask_id.replace("-", "_")

    title = subtask.get("title", "Untitled")
    description = subtask.get("description", "")
    risk_level = subtask.get("risk_level", "low")
    security_critical = subtask.get("security_critical", False)
    complexity_score = subtask.get("complexity_score", 1)
    expected_diff_size = subtask.get("expected_diff_size", "medium")
    concern_type = subtask.get("concern_type", "runtime")
    one_logical_step = subtask.get("one_logical_step", "unknown")
    affected_files = ";".join(subtask.get("affected_files", []))
    validation_criteria = "\n".join(
        f"- {c}" for c in subtask.get("validation_criteria", [])
    )
    contracts = subtask.get("contracts", "")
    test_strategy = json.dumps(subtask.get("test_strategy", {}))

    packet = f"""<SUBTASK_{tag_id}>
  <SUBTASK_{tag_id}__ID>{subtask_id}</SUBTASK_{tag_id}__ID>
  <SUBTASK_{tag_id}__TITLE>{title}</SUBTASK_{tag_id}__TITLE>
  <SUBTASK_{tag_id}__DESCRIPTION>{description}</SUBTASK_{tag_id}__DESCRIPTION>
  <SUBTASK_{tag_id}__RISK_LEVEL>{risk_level}</SUBTASK_{tag_id}__RISK_LEVEL>
  <SUBTASK_{tag_id}__SECURITY_CRITICAL>{str(security_critical).lower()}</SUBTASK_{tag_id}__SECURITY_CRITICAL>
  <SUBTASK_{tag_id}__COMPLEXITY_SCORE>{complexity_score}</SUBTASK_{tag_id}__COMPLEXITY_SCORE>
  <SUBTASK_{tag_id}__EXPECTED_DIFF_SIZE>{expected_diff_size}</SUBTASK_{tag_id}__EXPECTED_DIFF_SIZE>
  <SUBTASK_{tag_id}__CONCERN_TYPE>{concern_type}</SUBTASK_{tag_id}__CONCERN_TYPE>
  <SUBTASK_{tag_id}__ONE_LOGICAL_STEP>{one_logical_step}</SUBTASK_{tag_id}__ONE_LOGICAL_STEP>

  <SUBTASK_{tag_id}__AFFECTED_FILES>{affected_files}</SUBTASK_{tag_id}__AFFECTED_FILES>
  <SUBTASK_{tag_id}__VALIDATION_CRITERIA>
{validation_criteria}
  </SUBTASK_{tag_id}__VALIDATION_CRITERIA>
  <SUBTASK_{tag_id}__CONTRACTS>{contracts}</SUBTASK_{tag_id}__CONTRACTS>
  <SUBTASK_{tag_id}__TEST_STRATEGY>{test_strategy}</SUBTASK_{tag_id}__TEST_STRATEGY>
</SUBTASK_{tag_id}>"""

    return packet


def get_plan_path(branch: Optional[str] = None) -> Path:
    """
    Get path to task_plan file for current branch.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Path to task_plan_<branch>.md
    """
    if branch is None:
        branch = get_branch_name()
    return Path(f".map/{branch}/task_plan_{branch}.md")


def read_current_goal(branch: Optional[str] = None) -> Optional[str]:
    """
    Read Goal section from task_plan.md.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Goal text or None if not found
    """
    plan_file = get_plan_path(branch)

    if not plan_file.exists():
        return None

    try:
        content = plan_file.read_text(encoding="utf-8")
        match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    except OSError:
        pass

    return None


def get_current_phase(branch: Optional[str] = None) -> Optional[str]:
    """
    Read Current Phase from task_plan.md.

    Args:
        branch: Git branch (auto-detected if None)

    Returns:
        Current phase ID (e.g., "ST-001") or None
    """
    plan_file = get_plan_path(branch)

    if not plan_file.exists():
        return None

    try:
        content = plan_file.read_text(encoding="utf-8")
        match = re.search(r"## Current Phase\n(\S+)", content)
        if match:
            return match.group(1).strip()
    except OSError:
        pass

    return None


def run_test_gate() -> dict:
    """Run project test suite as a deterministic verification gate.

    Detects the test runner (pytest/npm/go/cargo) and executes it.
    Returns structured result with pass/fail, output, and exit code.
    Called AFTER Monitor returns valid=true, BEFORE validate_step advances state.
    """

    # Detect test runner
    runners = [
        (["pytest.ini", "pyproject.toml", "setup.py", "setup.cfg"], ["pytest", "--tb=short", "-q"]),
        (["package.json"], ["npm", "test"]),
        (["go.mod"], ["go", "test", "./..."]),
        (["Cargo.toml"], ["cargo", "test"]),
    ]

    test_cmd = None
    for markers, cmd in runners:
        for marker in markers:
            if Path(marker).exists():
                # For pyproject.toml, check it actually has pytest config or is a Python project
                if marker == "pyproject.toml":
                    try:
                        content = Path(marker).read_text(encoding="utf-8")
                        if "pytest" not in content and "tool.pytest" not in content:
                            continue
                    except OSError:
                        continue
                test_cmd = cmd
                break
        if test_cmd:
            break

    if not test_cmd:
        return {
            "status": "skipped",
            "passed": True,
            "reason": "No test runner detected",
            "output": "",
            "exit_code": 0,
        }

    try:
        result = subprocess.run(
            test_cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        # Truncate to avoid huge JSON
        if len(output) > 5000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-2000:]

        return {
            "status": "success",
            "passed": passed,
            "output": output,
            "exit_code": result.returncode,
            "test_cmd": " ".join(test_cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "passed": False,
            "output": "Test execution timed out after 300s",
            "exit_code": -1,
            "test_cmd": " ".join(test_cmd),
        }
    except OSError as e:
        return {
            "status": "error",
            "passed": False,
            "output": str(e),
            "exit_code": -1,
            "test_cmd": " ".join(test_cmd),
        }


_DIFF_STAT_MAX_CHARS = 65_536
_FILES_CHANGED_MAX_ENTRIES = 500


def snapshot_code_state(branch: Optional[str] = None) -> dict:
    """Capture current git state for artifact-to-code verification.

    Records git ref, changed files, and diff stat so review artifacts
    can be tied to actual code state. Populates subtask_files_changed.

    Very large repos can produce huge ``diff_stat`` and ``files_changed`` outputs that
    bloat the bundle JSON. Both are capped here (``_DIFF_STAT_MAX_CHARS`` /
    ``_FILES_CHANGED_MAX_ENTRIES``) with a ``diff_truncated=True`` marker so reviewers
    can see at a glance that the snapshot was clipped.
    """

    branch_name = branch or get_branch_name()

    def _run_git(args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    git_ref = _run_git(["rev-parse", "HEAD"])
    diff_stat = _run_git(["diff", "--stat", "HEAD"])
    diff_names = _run_git(["diff", "--name-only", "HEAD"])
    files_changed = [f for f in diff_names.splitlines() if f.strip()] if diff_names else []

    diff_truncated = False
    if len(diff_stat) > _DIFF_STAT_MAX_CHARS:
        diff_stat = diff_stat[:_DIFF_STAT_MAX_CHARS] + "\n... [truncated]"
        diff_truncated = True
    if len(files_changed) > _FILES_CHANGED_MAX_ENTRIES:
        files_changed = files_changed[:_FILES_CHANGED_MAX_ENTRIES]
        diff_truncated = True

    return {
        "status": "success",
        "git_ref": git_ref[:12] if git_ref else "unknown",
        "files_changed": files_changed,
        "diff_stat": diff_stat,
        "branch": branch_name,
        "diff_truncated": diff_truncated,
    }


def load_blueprint(
    branch: Optional[str] = None, project_dir: Optional[Path] = None
) -> Optional[dict]:
    """Load blueprint.json for current branch."""
    branch_name: str = branch if branch is not None else get_branch_name()
    base = project_dir or Path(".")
    blueprint_path = base / ".map" / branch_name / "blueprint.json"
    if not blueprint_path.exists():
        return None
    try:
        payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
        if isinstance(payload.get("blueprint"), dict):
            blueprint = dict(payload["blueprint"])
            if "coverage_map" not in blueprint and isinstance(payload.get("coverage_map"), dict):
                blueprint["coverage_map"] = payload["coverage_map"]
            return blueprint
        return payload
    except (json.JSONDecodeError, OSError):
        return None


def get_subtask_from_blueprint(blueprint: dict, subtask_id: str) -> Optional[dict]:
    """Extract single subtask from blueprint by ID."""
    for subtask in blueprint.get("subtasks", []):
        if subtask.get("id") == subtask_id:
            return subtask
    return None


def get_upstream_ids(blueprint: dict, subtask_id: str) -> list[str]:
    """Get dependency subtask IDs for a given subtask."""
    subtask = get_subtask_from_blueprint(blueprint, subtask_id)
    if not subtask:
        return []
    return subtask.get("dependencies", [])


def _sanitize_branch(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths.

    Keep in sync with sanitize_branch_name() in workflow-context-injector.py.
    """
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def _context_block_budget_tokens() -> int:
    """Return the hard estimated-token budget for Actor map_context blocks."""
    raw = os.environ.get(CONTEXT_BLOCK_BUDGET_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
            if value >= CONTEXT_BLOCK_MIN_BUDGET_TOKENS:
                return value
        except ValueError:
            pass
    return CONTEXT_BLOCK_DEFAULT_BUDGET_TOKENS


def _truncate_context_value(value: object, budget_tokens: int = 80) -> str:
    """Render a persisted value without letting one field consume the context."""
    text = value if isinstance(value, str) else str(value)
    return _truncate_to_token_budget(text, budget_tokens)


def _context_block_text(parts: list[str]) -> str:
    return "\n".join(parts)


def _enforce_context_block_budget(parts: list[str], budget_tokens: int) -> str:
    """Keep generated map_context under budget while preserving valid XML shape."""
    full_text = _context_block_text(parts)
    if _estimate_tokens(full_text) <= budget_tokens:
        return full_text

    closing = "</map_context>"
    truncation_note = (
        f"# Context Budget: truncated to <= {budget_tokens} estimated tokens; "
        "rerun with a larger MAP_CONTEXT_BLOCK_BUDGET_TOKENS if more plan "
        "overview is required."
    )
    output: list[str] = []

    for line in parts:
        if line == closing:
            continue
        candidate = _context_block_text(output + [line, truncation_note, closing])
        if _estimate_tokens(candidate) <= budget_tokens:
            output.append(line)
            continue

        remaining = budget_tokens - _estimate_tokens(
            _context_block_text(output + [truncation_note, closing])
        )
        truncated_line = _truncate_to_token_budget(line, remaining)
        if truncated_line:
            candidate = _context_block_text(
                output + [truncated_line, truncation_note, closing]
            )
            if _estimate_tokens(candidate) <= budget_tokens:
                output.append(truncated_line)
        break

    output.extend([truncation_note, closing])
    return _context_block_text(output)


def build_context_block(branch: str, current_subtask_id: str) -> str:
    """Build structured context block for Actor prompt.

    Returns formatted string with:
    - Goal (from task_plan.md)
    - Current subtask full details (from blueprint)
    - Upstream results (from step_state.json subtask_results)
    - Plan overview (all subtasks as ID + title + status one-liners)
    - Repo delta (differential insight, if last_subtask_commit_sha available)

    Returns empty string if blueprint not found (graceful fallback).
    """
    branch = _sanitize_branch(branch)
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    blueprint = load_blueprint(branch, project_dir=project_dir)
    if not blueprint:
        return ""

    # Goal — read directly via project_dir for consistency
    goal = None
    plan_file = project_dir / ".map" / branch / f"task_plan_{branch}.md"
    try:
        if plan_file.exists():
            content = plan_file.read_text(encoding="utf-8")
            match = re.search(GOAL_HEADING_RE, content, re.DOTALL)
            if match:
                goal = match.group(1).strip()
    except OSError:
        pass
    goal = goal or "No goal found"
    # Truncate to first sentence
    if ". " in goal:
        goal = goal[: goal.index(". ") + 1]
    if len(goal) > 200:
        goal = goal[:197] + "..."

    # Current subtask full details
    current = get_subtask_from_blueprint(blueprint, current_subtask_id)
    if not current:
        return ""

    current_details = []
    current_details.append(f"AAG Contract: {current.get('aag_contract', 'N/A')}")
    current_details.append(
        f"Subtask contract: expected_diff_size={current.get('expected_diff_size', 'unknown')}, "
        f"concern_type={current.get('concern_type', 'unknown')}, "
        f"one_logical_step={current.get('one_logical_step', 'unknown')}"
    )
    files_value = current.get("affected_files", [])
    files = files_value if isinstance(files_value, list) else []
    if files:
        shown_files = [str(f) for f in files[:8]]
        file_text = ", ".join(shown_files)
        if len(files) > 8:
            file_text += f", ... +{len(files) - 8} more"
        current_details.append(f"Affected files: {file_text}")
    criteria_value = current.get("validation_criteria", [])
    criteria = criteria_value if isinstance(criteria_value, list) else []
    if criteria:
        current_details.append("Validation criteria:")
        for c in criteria[:10]:
            current_details.append(f"  - {_truncate_context_value(c, 120)}")
        if len(criteria) > 10:
            current_details.append(f"  ... +{len(criteria) - 10} more criteria")

    # Plan overview with statuses from step_state.json
    state_path = project_dir / ".map" / branch / "step_state.json"
    subtask_phases: dict = {}
    subtask_results: dict = {}
    last_sha: Optional[str] = None
    try:
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            subtask_phases = state.get("subtask_phases", {})
            subtask_results = state.get("subtask_results", {})
            last_sha = state.get("last_subtask_commit_sha")
    except (json.JSONDecodeError, OSError):
        pass

    overview_lines = []
    for st in blueprint.get("subtasks", []):
        st_id = st.get("id", "?")
        st_title = st.get("title", "Untitled")
        if st_id == current_subtask_id:
            overview_lines.append(
                f"  [>>] {st_id}: {st_title} (IN PROGRESS) <- current"
            )
        elif st_id in subtask_results:
            status = subtask_results[st_id].get("status", "done")
            overview_lines.append(f"  [x] {st_id}: {st_title} ({status})")
        else:
            phase = subtask_phases.get(st_id, "pending")
            overview_lines.append(f"  [ ] {st_id}: {st_title} ({phase})")

    # Upstream results (only for dependencies)
    upstream_ids = get_upstream_ids(blueprint, current_subtask_id)
    upstream_lines = []
    for up_id in upstream_ids:
        if up_id in subtask_results:
            result = subtask_results[up_id]
            fc_value = result.get("files_changed", [])
            fc = fc_value if isinstance(fc_value, list) else []
            status = result.get("status", "unknown")
            summary = result.get("summary", "")
            shown_files = fc[:4]
            file_suffix = f", +{len(fc) - 4} more" if len(fc) > 4 else ""
            line = f"  {up_id}: files={shown_files}{file_suffix}, status={status}"
            if summary:
                line += f", summary={_truncate_context_value(summary, 120)}"
            upstream_lines.append(line)
        else:
            upstream_lines.append(f"  {up_id}: (not yet completed)")

    # Assemble block
    parts = [
        "<map_context>",
        f"# Goal: {goal}",
        "",
        f"# Current Subtask: {current_subtask_id} — {current.get('title', 'Untitled')}",
    ]
    parts.extend(current_details)
    if upstream_lines:
        parts.append("")
        parts.append(f"# Upstream Results (dependencies of {current_subtask_id}):")
        parts.extend(upstream_lines)

    parts.append("")
    parts.append(f"# Plan Overview ({len(blueprint.get('subtasks', []))} subtasks):")
    parts.extend(overview_lines)

    # Repo Delta (via compute_differential_insight from repo_insight)
    if last_sha:
        try:
            import sys
            import importlib

            repo_insight = sys.modules.get("mapify_cli.repo_insight")
            if repo_insight is None:
                repo_insight = importlib.import_module("mapify_cli.repo_insight")
            compute_differential_insight = getattr(
                repo_insight, "compute_differential_insight", None
            )
            if compute_differential_insight is None:
                raise ImportError("compute_differential_insight not available")

            insight = compute_differential_insight(project_dir, last_sha)
            if insight.get("error"):
                insight = {}
            changed = insight.get("changed_files") or []
            deleted = insight.get("deleted_files") or []
            if changed or deleted:
                parts.append("")
                parts.append("# Repo Delta (files changed since last subtask):")
                for f in changed[:20]:
                    parts.append(f"  {f}")
                if len(changed) > 20:
                    parts.append(f"  ... +{len(changed) - 20} more")
                if deleted:
                    parts.append("# Deleted since last subtask:")
                    for f in deleted[:10]:
                        parts.append(f"  (deleted) {f}")
                    if len(deleted) > 10:
                        parts.append(f"  ... +{len(deleted) - 10} more")
        except ImportError:
            # Fallback: repo_insight not available in standalone .map/ context
            pass

    parts.append("</map_context>")

    return _enforce_context_block_budget(parts, _context_block_budget_tokens())


def prepare_detached_review(
    bundle_path: Optional[str] = None,
    *,
    branch: Optional[str] = None,
    commit: Optional[str] = None,
    target_dir: Optional[str] = None,
) -> dict[str, object]:
    """Prepare a clean review context via git worktree add --detach.

    Returns a dict with:
      status: "success" | "unavailable" | "error"
      reason: human-readable explanation
      worktree_path: absolute str path (only on success, else None)
      commit: short SHA used (only on success, else None)
      bundle_path: input bundle path echoed back if provided
      mutated_source: bool — MUST be False; the source branch is never mutated
    """
    _base: dict[str, object] = {
        "bundle_path": bundle_path,
        "worktree_path": None,
        "commit": None,
        "reason": "",
        "mutated_source": False,
    }

    # Resolve target directory
    # ``get_branch_name`` already sanitizes; explicit ``branch`` callers must be
    # sanitized too (same rationale as ``create_review_bundle``).
    branch_name = _sanitize_branch(branch) if branch else get_branch_name()
    if target_dir is not None:
        resolved_target = Path(target_dir).resolve()
    else:
        resolved_target = get_branch_dir(branch_name).resolve() / "detached-review"

    # Path-traversal guard: resolved_target MUST stay under .map/<branch>/ or the .map/
    # root. A user-supplied target_dir like "../../tmp/evil" resolves outside both and is
    # rejected to keep the worktree mutation contained to MAP-owned scope.
    branch_dir_resolved = get_branch_dir(branch_name).resolve()
    map_root_resolved = (Path.cwd().resolve() / ".map").resolve()
    if not (
        resolved_target.is_relative_to(branch_dir_resolved)
        or resolved_target.is_relative_to(map_root_resolved)
    ):
        return {
            **_base,
            "status": "error",
            "reason": "target_dir escapes .map/<branch>/ scope",
        }

    # Edge Case 6 + INV-6: never overwrite an existing path
    if resolved_target.exists():
        return {
            **_base,
            "status": "unavailable",
            "reason": f"Detached worktree path already exists: {resolved_target}",
        }

    # Resolve commit SHA (short) — abort if not in a git repo
    if commit is not None:
        short_sha = commit
    else:
        try:
            rev_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except OSError as e:
            return {
                **_base,
                "status": "unavailable",
                "reason": f"git rev-parse failed: {e}",
            }
        if rev_result.returncode != 0:
            return {
                **_base,
                "status": "unavailable",
                "reason": f"git rev-parse failed: {rev_result.stderr.strip()}",
            }
        short_sha = rev_result.stdout.strip()

    # Create the detached worktree — the only git mutation is a new worktree entry
    try:
        wt_result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(resolved_target), short_sha],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except OSError as e:
        return {
            **_base,
            "status": "error",
            "reason": f"git worktree add failed: {e}",
        }

    if wt_result.returncode != 0:
        return {
            **_base,
            "status": "error",
            "reason": f"git worktree add failed: {wt_result.stderr.strip()}",
        }

    return {
        **_base,
        "status": "success",
        "worktree_path": str(resolved_target),
        "commit": short_sha,
        "reason": "",
    }


if __name__ == "__main__":
    # Simple CLI interface for testing
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 map_step_runner.py <function> [args...]")
        sys.exit(1)

    func_name = sys.argv[1]

    if func_name == "update_step_state_batch" and len(sys.argv) >= 3:
        updates_json = sys.argv[2]
        try:
            updates = json.loads(updates_json)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON: {e}"}))
            sys.exit(1)
        result = update_step_state_batch(updates)
        print(json.dumps(result, indent=2))

    elif func_name == "update_step_state" and len(sys.argv) >= 5:
        result = update_step_state(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif func_name == "update_plan_status" and len(sys.argv) >= 4:
        result = update_plan_status(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif func_name == "validate_checkpoint" and len(sys.argv) >= 4:
        required = sys.argv[3].split(",")
        result = validate_checkpoint(sys.argv[2], required)
        print(json.dumps(result, indent=2))

    elif func_name == "read_current_goal":
        goal = read_current_goal()
        print(goal or "Goal not found")

    elif func_name == "get_current_phase":
        phase = get_current_phase()
        print(phase or "Phase not found")

    elif func_name == "ensure_human_artifacts":
        result = ensure_human_artifacts()
        print(json.dumps(result, indent=2))

    elif func_name == "next_numbered_artifact_path" and len(sys.argv) >= 3:
        result = next_numbered_artifact_path(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif func_name == "append_session_log" and len(sys.argv) >= 4:
        # Deprecated — kept for backward compatibility, returns {"status": "deprecated"}
        result = append_session_log(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    elif func_name == "write_verification_summary" and len(sys.argv) >= 3:
        verdict = sys.argv[2]
        task_title = sys.argv[3] if len(sys.argv) >= 4 else ""
        checks_run = sys.argv[4] if len(sys.argv) >= 5 else ""
        findings = sys.argv[5] if len(sys.argv) >= 6 else ""
        next_action = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = write_verification_summary(
            verdict, task_title, checks_run, findings, next_action
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_pr_draft":
        summary = sys.argv[2] if len(sys.argv) >= 3 else ""
        validation = sys.argv[3] if len(sys.argv) >= 4 else ""
        risks_follow_up = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = write_pr_draft(summary, validation, risks_follow_up)
        print(json.dumps(result, indent=2))

    elif func_name == "write_plan_review":
        summary = sys.argv[2] if len(sys.argv) >= 3 else ""
        high = sys.argv[3] if len(sys.argv) >= 4 else ""
        medium = sys.argv[4] if len(sys.argv) >= 5 else ""
        low = sys.argv[5] if len(sys.argv) >= 6 else ""
        resolved = sys.argv[6] if len(sys.argv) >= 7 else ""
        open_concerns = sys.argv[7] if len(sys.argv) >= 8 else ""
        recommendation = sys.argv[8] if len(sys.argv) >= 9 else "needs-revision"
        result = write_plan_review(
            summary, high, medium, low, resolved, open_concerns, recommendation
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_stage_gate" and len(sys.argv) >= 4:
        stage = sys.argv[2]
        verdict = sys.argv[3]
        source_artifact = sys.argv[4] if len(sys.argv) >= 5 else ""
        notes = sys.argv[5] if len(sys.argv) >= 6 else ""
        result = write_stage_gate(stage, verdict, source_artifact, notes)
        print(json.dumps(result, indent=2))

    elif func_name == "load_artifact_manifest":
        result = load_artifact_manifest()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "record_workflow_fit" and len(sys.argv) >= 8:
        recommended_workflow = sys.argv[2]
        expected_diff_size = sys.argv[3]
        has_new_invariants = sys.argv[4]
        needs_independent_review = sys.argv[5]
        has_clear_acceptance_criteria = sys.argv[6]
        test_first_required = sys.argv[7]
        decision_summary = sys.argv[8] if len(sys.argv) >= 9 else ""
        result = record_workflow_fit(
            recommended_workflow,
            expected_diff_size,
            has_new_invariants,
            needs_independent_review,
            has_clear_acceptance_criteria,
            test_first_required,
            decision_summary,
        )
        print(json.dumps(result, indent=2))

    elif func_name == "record_plan_artifacts":
        result = record_plan_artifacts()
        print(json.dumps(result, indent=2))

    elif func_name == "validate_blueprint_contract":
        blueprint_path = sys.argv[2] if len(sys.argv) >= 3 else ""
        result = validate_blueprint_contract(blueprint_path)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "record_test_contract_handoff" and len(sys.argv) >= 3:
        subtask_id = sys.argv[2]
        failing_test_command = sys.argv[3] if len(sys.argv) >= 4 else ""
        test_files_csv = sys.argv[4] if len(sys.argv) >= 5 else ""
        contract_summary = sys.argv[5] if len(sys.argv) >= 6 else ""
        notes = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = record_test_contract_handoff(
            subtask_id,
            failing_test_command,
            test_files_csv,
            contract_summary,
            notes,
        )
        print(json.dumps(result, indent=2))

    elif func_name == "write_run_health_report":
        workflow = sys.argv[2] if len(sys.argv) >= 3 else "map-efficient"
        terminal_status = sys.argv[3] if len(sys.argv) >= 4 else ""
        result = write_run_health_report(workflow, terminal_status)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "validate_run_health_report":
        report_path = sys.argv[2] if len(sys.argv) >= 3 else ""
        result = validate_run_health_report(report_path)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "create_review_bundle":
        result = create_review_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_review_prompts":
        import argparse as _ap

        _p = _ap.ArgumentParser(prog="map_step_runner.py build_review_prompts")
        _p.add_argument("--branch", default=None)
        _p.add_argument("--budget-tokens", type=int, default=None)
        _p.add_argument("--review-preferences", default="")
        _args = _p.parse_args(sys.argv[2:])
        result = build_review_prompts(
            branch=_args.branch,
            review_preferences=_args.review_preferences,
            budget_tokens=_args.budget_tokens,
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_handoff_bundle":
        result = build_handoff_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_review_handoff":
        result = build_review_handoff()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_acceptance_coverage_report":
        result = build_acceptance_coverage_report()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_prior_stage_consumption_report":
        stage = sys.argv[2] if len(sys.argv) >= 3 else "review"
        result = build_prior_stage_consumption_report(stage)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "validate_prior_stage_consumption":
        stage = sys.argv[2] if len(sys.argv) >= 3 else "review"
        result = build_prior_stage_consumption_report(stage)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if not result.get("valid"):
            sys.exit(1)

    elif func_name == "write_learning_handoff":
        workflow = sys.argv[2] if len(sys.argv) >= 3 else ""
        task_title = sys.argv[3] if len(sys.argv) >= 4 else ""
        outcome = sys.argv[4] if len(sys.argv) >= 5 else ""
        next_action = sys.argv[5] if len(sys.argv) >= 6 else ""
        notes = sys.argv[6] if len(sys.argv) >= 7 else ""
        result = write_learning_handoff(
            workflow, task_title, outcome, next_action, notes
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "record_learning_consumption":
        summary_source = sys.argv[2] if len(sys.argv) >= 3 else "inline-summary"
        workflow = sys.argv[3] if len(sys.argv) >= 4 else ""
        result = record_learning_consumption(summary_source, workflow)
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "ensure_known_issues_file":
        result = ensure_known_issues_file()
        print(json.dumps(result, indent=2))

    elif func_name == "ensure_active_issues_file":
        result = ensure_active_issues_file()
        print(json.dumps(result, indent=2))

    elif func_name == "replace_active_issues" and len(sys.argv) >= 4:
        stage = sys.argv[2]
        source_artifact = sys.argv[3]
        issues_text = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = replace_active_issues(stage, source_artifact, issues_text)
        print(json.dumps(result, indent=2))

    elif func_name == "add_known_issue" and len(sys.argv) >= 3:
        title = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) >= 4 else "accepted"
        notes = sys.argv[4] if len(sys.argv) >= 5 else ""
        result = add_known_issue(title, status, notes)
        print(json.dumps(result, indent=2))

    elif func_name == "run_test_gate":
        result = run_test_gate()
        print(json.dumps(result, indent=2))

    elif func_name == "snapshot_code_state":
        result = snapshot_code_state()
        print(json.dumps(result, indent=2))

    elif func_name == "record_subtask_result":
        # Read JSON from stdin to avoid shell injection: {"files": [...], "status": "...", "summary": "...", "commit_sha": "..."}
        import sys as _sys
        try:
            data = json.loads(_sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON on stdin: {e}"}))
            _sys.exit(1)
        branch_name = get_branch_name()
        state_path = Path(f".map/{branch_name}/step_state.json")
        if not state_path.exists():
            print(json.dumps({"status": "error", "message": "step_state.json not found"}))
            _sys.exit(1)
        from map_orchestrator import StepState  # type: ignore[import-not-found]
        st = StepState.load(state_path)
        subtask_id = data.get("subtask_id") or st.current_subtask_id or ""
        if not subtask_id:
            print(json.dumps({"status": "skipped", "message": "No subtask_id"}))
            _sys.exit(0)
        st.record_subtask_result(
            subtask_id=subtask_id,
            files_changed=data.get("files", []),
            status=data.get("status", "valid"),
            summary=data.get("summary", ""),
            commit_sha=data.get("commit_sha"),
        )
        st.save(state_path)
        print(json.dumps({"status": "success", "subtask_id": subtask_id}))

    elif func_name == "build_context_block" and len(sys.argv) >= 4:
        result = build_context_block(sys.argv[2], sys.argv[3])
        print(result)

    elif func_name == "shuffle-sections":
        # CLI: shuffle-sections <mode> [seed]
        # Empty string seed is treated as "unset" (None) so SKILL.md can pass "" unconditionally.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: shuffle-sections <mode> [seed]"}))
            sys.exit(1)
        mode_arg = sys.argv[2]
        seed_arg: int | None = None
        if len(sys.argv) >= 4 and sys.argv[3] != "":
            try:
                seed_arg = int(sys.argv[3])  # EC-16: int() rejects non-int via ValueError
            except ValueError as exc:
                print(json.dumps({"status": "error", "message": f"invalid seed: {exc}"}))
                sys.exit(1)
        try:
            order = get_review_section_order(mode_arg, seed_arg)
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            sys.exit(1)
        print(json.dumps({"status": "ok", "mode": mode_arg, "seed": seed_arg, "order": order}))

    elif func_name == "default-shuffle-seed":
        # CLI: default-shuffle-seed <branch> [commit_sha]
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: default-shuffle-seed <branch> [commit_sha]"}))
            sys.exit(1)
        branch_arg = sys.argv[2]
        commit_sha_arg = sys.argv[3] if len(sys.argv) >= 4 and sys.argv[3] else None
        seed_val = default_shuffle_seed(branch_arg, commit_sha_arg)
        print(json.dumps({"status": "ok", "branch": branch_arg, "commit_sha": commit_sha_arg, "seed": seed_val}))

    elif func_name == "prepare_detached_review":
        import argparse as _ap

        _p = _ap.ArgumentParser(prog="map_step_runner.py prepare_detached_review")
        _p.add_argument("bundle_path", nargs="?", default=None)
        _p.add_argument("--commit", default=None)
        _p.add_argument("--target-dir", default=None)
        _p.add_argument("--branch", default=None)
        _args = _p.parse_args(sys.argv[2:])
        result = prepare_detached_review(
            _args.bundle_path,
            branch=_args.branch,
            commit=_args.commit,
            target_dir=_args.target_dir,
        )
        print(json.dumps(result, indent=2))

    elif func_name == "compare-review-runs":
        # CLI: compare-review-runs <runs_json|->
        # runs_json: JSON-encoded list of run dicts. Pass "-" to read from stdin.
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: compare-review-runs <runs_json|->"}))
            sys.exit(1)
        raw = sys.stdin.read() if sys.argv[2] == "-" else sys.argv[2]
        try:
            runs_payload = json.loads(raw)
        except (ValueError, TypeError) as exc:
            print(json.dumps({"status": "error", "message": f"invalid JSON: {exc}"}))
            sys.exit(1)
        try:
            cmp_result = compare_review_runs(runs_payload)
        except (ValueError, AttributeError, TypeError) as exc:
            print(json.dumps({"status": "error", "message": f"compare-review-runs: {exc}"}))
            sys.exit(1)
        print(json.dumps({"status": "ok", **cmp_result}))

    elif func_name == "record-review-ordering":
        # CLI: record-review-ordering <mode> [seed] [<json: {runs, drift}>|"-" for stdin]
        if len(sys.argv) < 3:
            print(json.dumps({"status": "error", "message": "usage: record-review-ordering <mode> [seed] [runs_drift_json|-]"}))
            sys.exit(1)
        mode_arg = sys.argv[2]
        seed_arg: int | None = None
        if len(sys.argv) >= 4 and sys.argv[3] != "":
            try:
                seed_arg = int(sys.argv[3])
            except ValueError as exc:
                print(json.dumps({"status": "error", "message": f"invalid seed: {exc}"}))
                sys.exit(1)
        runs_arg: list[dict[str, object]] | None = None
        drift_arg: dict[str, object] | None = None
        if len(sys.argv) >= 5:
            raw_ord = sys.stdin.read() if sys.argv[4] == "-" else sys.argv[4]
            try:
                ord_payload = json.loads(raw_ord)
            except (ValueError, TypeError) as exc:
                print(json.dumps({"status": "error", "message": f"invalid JSON: {exc}"}))
                sys.exit(1)
            if not isinstance(ord_payload, dict):
                print(json.dumps({"status": "error", "message": "JSON payload must be an object"}))
                sys.exit(1)
            runs_field = ord_payload.get("runs")
            if runs_field is not None and not isinstance(runs_field, list):
                print(json.dumps({"status": "error", "message": "payload.runs must be a list"}))
                sys.exit(1)
            runs_arg = cast(list[dict[str, object]], runs_field) if runs_field is not None else None
            drift_field = ord_payload.get("drift")
            if drift_field is not None and not isinstance(drift_field, dict):
                print(json.dumps({"status": "error", "message": "payload.drift must be a dict"}))
                sys.exit(1)
            drift_arg = cast(dict[str, object], drift_field) if drift_field is not None else None
        try:
            ord_result = record_review_ordering(mode_arg, seed_arg, runs_arg, drift_arg, branch=None)
        except ValueError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            sys.exit(1)
        print(json.dumps(ord_result))

    else:
        print(f"Unknown function: {func_name}")
        sys.exit(1)
