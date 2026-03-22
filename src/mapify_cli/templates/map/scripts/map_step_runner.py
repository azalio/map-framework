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
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


HUMAN_ARTIFACT_DEFAULTS = {
    "qa-001.md": "# QA 001\n\n",
    "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Follow-up\n",
}


KNOWN_ISSUES_DEFAULT: dict[str, list[dict[str, object]]] = {"issues": []}
ACTIVE_ISSUES_DEFAULT: dict[str, object] = {"updated_at": "", "issues": []}

GATE_VERDICTS = {"ready", "needs-revision", "blocked"}


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


def build_handoff_bundle(branch: Optional[str] = None) -> dict:
    """Build a compact handoff bundle from branch-scoped human artifacts."""
    branch_name = branch or get_branch_name()
    branch_dir = get_branch_dir(branch_name)
    ensure_human_artifacts(branch_name)

    def read(name: str) -> str:
        path = branch_dir / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

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
        return path.read_text(encoding="utf-8") if path.exists() else ""

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
        match = re.search(r"## Goal\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
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

    elif func_name == "build_handoff_bundle":
        result = build_handoff_bundle()
        print(json.dumps(result, indent=2))

    elif func_name == "build_review_handoff":
        result = build_review_handoff()
        print(json.dumps(result, indent=2))

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

    else:
        print(f"Unknown function: {func_name}")
        sys.exit(1)
