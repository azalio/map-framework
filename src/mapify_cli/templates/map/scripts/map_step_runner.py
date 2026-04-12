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

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Keep in sync with workflow-context-injector.py GOAL_HEADING_RE
GOAL_HEADING_RE = r"## (?:Goal|Overview)\n(.*?)(?=\n##|\Z)"


HUMAN_ARTIFACT_DEFAULTS = {
    "qa-001.md": "# QA 001\n\n",
    "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Follow-up\n",
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


def artifact_manifest_path(branch: Optional[str] = None) -> Path:
    """Return the branch-scoped artifact manifest path."""
    return get_branch_dir(branch) / "artifact_manifest.json"


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
            for stage in ARTIFACT_STAGE_NAMES:
                stage_payload = loaded_stages.get(stage, _default_stage_payload())
                if isinstance(stage_payload, dict):
                    manifest["stages"][stage] = {
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
    return {
        "status": "success",
        "manifest_path": manifest_result["path"],
        "spec_status": manifest["stages"]["spec"]["status"],
        "plan_status": manifest["stages"]["plan"]["status"],
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
    """Remove control characters (U+0000-U+001F except \\n \\r \\t) that break JSON consumers.

    Python's json.dumps escapes these correctly, but downstream tools
    (jq via bash pipes, shell variable expansion) can corrupt them.
    """
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def build_handoff_bundle(branch: Optional[str] = None) -> dict:
    """Build a compact handoff bundle from branch-scoped human artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    ensure_human_artifacts(branch_name)

    def read(name: str) -> str:
        path = branch_dir / name
        if not path.exists():
            return ""
        try:
            return _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

    verification = read("verification-summary.md")
    qa = read("qa-001.md")
    active_issues = read("active-issues.json")
    verification_gate = read("verification-gate.json")
    review_path = next_numbered_artifact_path("code-review", branch_name)
    latest_review_index = max(0, review_path["index"] - 1)
    latest_review_name = (
        f"code-review-{latest_review_index:03d}.md" if latest_review_index > 0 else ""
    )
    latest_review = read(latest_review_name) if latest_review_name else ""

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

    def read(name: str) -> str:
        path = branch_dir / name
        if not path.exists():
            return ""
        try:
            return _sanitize_for_json(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

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
        "plan_review": read(latest_plan_review_name)
        if latest_plan_review_name
        else None,
        "code_review": read(latest_code_review_name)
        if latest_code_review_name
        else None,
        "verification_summary": read("verification-summary.md"),
        "qa": read("qa-001.md"),
        "pr_draft": read("pr-draft.md"),
        "active_issues": read("active-issues.json") or None,
    }
    return payload


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
            "artifact_manifest.json" if manifest else "",
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
    _write_json_file(json_path, payload)

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
    markdown_path.write_text(markdown, encoding="utf-8")

    manifest_payload = load_artifact_manifest(branch_name)
    _set_manifest_stage(
        manifest_payload,
        "learn_handoff",
        "ready",
        artifacts=[
            _artifact_ref(markdown_path, "learning-handoff-markdown"),
            _artifact_ref(json_path, "learning-handoff-json"),
        ],
        metadata={
            "workflow": workflow_name,
            "task_title": goal,
            "outcome": outcome_text,
            "next_action": next_action_text,
            "git_ref": code_state.get("git_ref", "unknown"),
        },
    )
    manifest_result = save_artifact_manifest(manifest_payload, branch_name)

    return {
        "status": "success",
        "branch": branch_name,
        "workflow": workflow_name,
        "task_title": goal,
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "manifest_path": manifest_result["path"],
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


from map_utils import get_branch_name  # noqa: E402 — shared across .map/scripts/


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


def snapshot_code_state(branch: Optional[str] = None) -> dict:
    """Capture current git state for artifact-to-code verification.

    Records git ref, changed files, and diff stat so review artifacts
    can be tied to actual code state. Populates subtask_files_changed.
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

    return {
        "status": "success",
        "git_ref": git_ref[:12] if git_ref else "unknown",
        "files_changed": files_changed,
        "diff_stat": diff_stat,
        "branch": branch_name,
    }


def load_blueprint(
    branch: Optional[str] = None, project_dir: Optional[Path] = None
) -> Optional[dict]:
    """Load blueprint.json for current branch."""
    if branch is None:
        branch = get_branch_name()
    base = project_dir or Path(".")
    blueprint_path = base / ".map" / branch / "blueprint.json"
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
        from map_orchestrator import StepState
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

    else:
        print(f"Unknown function: {func_name}")
        sys.exit(1)
