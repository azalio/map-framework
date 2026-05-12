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
import json
import os
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
    "learn_handoff",
)
WORKFLOW_FIT_ROUTES = {
    "direct-edit",
    "map-fast",
    "map-efficient",
    "map-tdd",
    "map-plan",
}
DIFF_SIZE_LEVELS = {"tiny", "small", "medium", "large"}
LEARNING_CONSUMPTION_SOURCES = {"auto-handoff", "file-handoff", "inline-summary"}
LEARNING_IMMEDIATE_WINDOW_SECONDS = 30 * 60

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
    summary_file.write_text(content, encoding="utf-8")
    return {"status": "success", "path": str(summary_file)}


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
        }
        stage_status = "warn" if "schema_validation_error" in result else "ready"
        _set_manifest_stage(
            manifest, "review", stage_status, artifacts=artifacts_list, metadata=metadata
        )
        save_result = save_artifact_manifest(manifest, branch_name)
        result["manifest_status"] = {"status": stage_status, "path": save_result["path"]}
    except Exception as exc:
        result["manifest_status"] = {"status": "error", "reason": str(exc)}

    return result


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
        return json.loads(blueprint_path.read_text(encoding="utf-8"))
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


def build_context_block(branch: str, current_subtask_id: str) -> str:
    """Build structured context block for Actor prompt.

    Returns formatted string with:
    - Goal (from task_plan.md)
    - Current subtask full details (from blueprint)
    - Plan overview (all subtasks as ID + title + status one-liners)
    - Upstream results (from step_state.json subtask_results)
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
    files = current.get("affected_files", [])
    if files:
        current_details.append(f"Affected files: {', '.join(files)}")
    criteria = current.get("validation_criteria", [])
    if criteria:
        current_details.append("Validation criteria:")
        for c in criteria:
            current_details.append(f"  - {c}")

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
            fc = result.get("files_changed", [])
            status = result.get("status", "unknown")
            summary = result.get("summary", "")
            line = f"  {up_id}: files={fc}, status={status}"
            if summary:
                line += f", summary={summary}"
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
    parts.append("")
    parts.append(f"# Plan Overview ({len(blueprint.get('subtasks', []))} subtasks):")
    parts.extend(overview_lines)

    if upstream_lines:
        parts.append("")
        parts.append(f"# Upstream Results (dependencies of {current_subtask_id}):")
        parts.extend(upstream_lines)

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

    return "\n".join(parts)


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

    elif func_name == "create_review_bundle":
        result = create_review_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_handoff_bundle":
        result = build_handoff_bundle()
        print(json.dumps(result, indent=2, ensure_ascii=True))

    elif func_name == "build_review_handoff":
        result = build_review_handoff()
        print(json.dumps(result, indent=2, ensure_ascii=True))

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

    else:
        print(f"Unknown function: {func_name}")
        sys.exit(1)
