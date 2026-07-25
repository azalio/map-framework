#!/usr/bin/env python3
"""
Post-Compact Context Injector - SessionStart Hook (matcher: compact).

After context compaction, injects a pointer to the saved transcript
so Claude knows where to find the full pre-compaction conversation.

Also reads restore_point.json if available (from ralph-context-pruner).

Exit codes:
  0 - Always
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
MAP_DIR = PROJECT_DIR / ".map"
REPRIME_LIMIT = 1200

STEP_REQUIRED_ACTIONS = {
    "1.55": "Approve plan before execution state is initialized.",
    "1.56": "Choose execution mode before implementation.",
    "2.2": "Persist a RESEARCH artifact before Actor; delegate only when broad discovery is required.",
    "2.3": "Implement only the current subtask, then run Monitor.",
    "2.4": "Run Monitor and treat valid=false as a hard stop.",
}


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def truncate_text(text: str, limit: int) -> str:
    """Return a single-line string bounded to *limit* characters."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def state_string(state: dict, key: str, default: str = "") -> str:
    value = state.get(key)
    if isinstance(value, str):
        return value.strip()
    return default


def load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def constraint_label(item: object) -> str | None:
    if isinstance(item, str):
        return truncate_text(item, 90)
    if not isinstance(item, dict):
        return None
    cid = item.get("id")
    desc = item.get("description")
    if isinstance(cid, str) and isinstance(desc, str):
        return truncate_text(f"{cid}: {desc}", 90)
    if isinstance(cid, str):
        return truncate_text(cid, 90)
    if isinstance(desc, str):
        return truncate_text(desc, 90)
    return None


def extract_coverage_tags(criteria: list[object]) -> list[str]:
    tags: list[str] = []
    for criterion in criteria:
        if not isinstance(criterion, str):
            continue
        for tag in re.findall(r"\[([A-Z]+-\d+)\]", criterion):
            if tag not in tags:
                tags.append(tag)
    return tags


def load_blueprint_reprime(branch_dir: Path, subtask_id: str) -> list[str]:
    blueprint = load_json(branch_dir / "blueprint.json")
    if not blueprint:
        return []

    parts: list[str] = []
    hard_constraints = blueprint.get("hard_constraints")
    if isinstance(hard_constraints, list):
        labels = [label for item in hard_constraints if (label := constraint_label(item))]
        if labels:
            parts.append("Hard constraints: " + "; ".join(labels[:4]))

    subtasks = blueprint.get("subtasks")
    if isinstance(subtasks, list) and subtask_id:
        for item in subtasks:
            if not isinstance(item, dict) or item.get("id") != subtask_id:
                continue
            title = item.get("title")
            if isinstance(title, str) and title.strip():
                parts.append(f"Current subtask: {subtask_id} - {truncate_text(title, 120)}")
            criteria = item.get("validation_criteria")
            if isinstance(criteria, list):
                tags = extract_coverage_tags(criteria)
                if tags:
                    parts.append("Acceptance tags: " + ", ".join(tags[:8]))
            break

    return parts


def load_retry_reprime(branch_dir: Path, subtask_id: str) -> str | None:
    retry = load_json(branch_dir / "retry_quarantine.json")
    if not retry:
        return None
    quarantines = retry.get("quarantines")
    if not isinstance(quarantines, list):
        return None
    matches = [
        item
        for item in quarantines
        if isinstance(item, dict)
        and (not subtask_id or item.get("subtask_id") == subtask_id)
    ]
    if not matches:
        return None
    latest = matches[-1]
    summary = latest.get("monitor_rejection_summary")
    if isinstance(summary, str) and summary.strip():
        return "Last Monitor rejection: " + truncate_text(summary, 180)
    return None


def build_reprime(branch: str, branch_dir: Path) -> str | None:
    state = load_json(branch_dir / "step_state.json")
    if not state:
        return None

    workflow = state_string(state, "workflow") or state_string(state, "workflow_name")
    phase = state_string(state, "current_step_phase") or state_string(
        state, "current_state"
    )
    step_id = state_string(state, "current_step_id")
    subtask_id = state_string(state, "current_subtask_id")

    lines = ["MAP RE-PRIME after compaction:"]
    state_bits = []
    if workflow:
        state_bits.append(f"workflow={workflow}")
    if step_id:
        state_bits.append(f"step={step_id}")
    if phase:
        state_bits.append(f"phase={phase}")
    if subtask_id:
        state_bits.append(f"subtask={subtask_id}")
    if state_bits:
        lines.append("State: " + ", ".join(state_bits))

    required = STEP_REQUIRED_ACTIONS.get(step_id)
    if required:
        lines.append("Required next action: " + required)

    lines.extend(load_blueprint_reprime(branch_dir, subtask_id))
    retry_line = load_retry_reprime(branch_dir, subtask_id)
    if retry_line:
        lines.append(retry_line)

    lines.append(
        "Authority: source files, tests, schemas, and configs beat transcripts, summaries, commit messages, and stale docs."
    )
    lines.append(f"Workflow state: .map/{branch}/step_state.json")
    return truncate_text("\n".join(lines), REPRIME_LIMIT)


def offloaded_outputs_pointer(branch: str, branch_dir: Path) -> str | None:
    """Pointer to tool outputs offloaded before compaction, if any (#232).

    Rebuilds the manifest from the append-only index and returns the recovery
    line. Lazy-imports mapify_cli and degrades to ``None`` (silent) when it is
    unavailable or nothing was offloaded.
    """
    try:
        sys.path.insert(0, str(PROJECT_DIR / "src"))
        try:
            from mapify_cli.tool_output_offload import (
                build_manifest,
                recovery_pointer_text,
            )
        except ImportError:
            return None
        build_manifest(branch_dir / "compacted")
        return recovery_pointer_text(branch, branch_dir)
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        return None


def main() -> None:
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass

    branch = get_branch_name()
    branch_dir = MAP_DIR / branch

    parts = []

    reprime = build_reprime(branch, branch_dir)
    if reprime:
        parts.append(reprime)

    # Check for saved transcript pointer
    pointer = branch_dir / "last-transcript.txt"
    if pointer.exists():
        try:
            transcript_path = pointer.read_text(encoding="utf-8").strip()
            if transcript_path:
                parts.append(
                    f"The full transcript of the previous conversation "
                    f"(before compaction) was saved to {transcript_path}. "
                    f"Read that file if you need details from before compaction."
                )
        except OSError:
            pass

    # Point at any tool outputs offloaded before compaction (#232) so the agent
    # re-reads a sidecar instead of re-running broad discovery.
    offload_pointer = offloaded_outputs_pointer(branch, branch_dir)
    if offload_pointer:
        parts.append(offload_pointer)

    # Check for workflow restore point
    restore = branch_dir / "restore_point.json"
    if restore.exists():
        try:
            data = json.loads(restore.read_text(encoding="utf-8"))
            state = data.get("workflow_state", {})
            workflow = state.get("workflow", "")
            phase = state.get("current_step", {}).get("phase", "") or state.get(
                "current_state", ""
            )
            if workflow or phase:
                parts.append(
                    f"MAP workflow state before compaction: "
                    f"workflow={workflow}, phase={phase}. "
                    f"Full state: .map/{branch}/step_state.json"
                )
        except (json.JSONDecodeError, OSError):
            pass

    if not parts:
        print("{}")
        sys.exit(0)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(parts),
        }
    }
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
