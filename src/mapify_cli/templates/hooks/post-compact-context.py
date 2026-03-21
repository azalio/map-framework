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
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:
        pass
    return "default"


def main() -> None:
    try:
        json.load(sys.stdin)
    except json.JSONDecodeError:
        pass

    branch = get_branch_name()
    branch_dir = MAP_DIR / branch

    parts = []

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
        except (IOError, OSError):
            pass

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
        except (json.JSONDecodeError, IOError, OSError):
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
