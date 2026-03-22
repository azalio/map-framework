"""Shared utilities for MAP workflow scripts."""

import re
import subprocess


def get_branch_name() -> str:
    """Get sanitized git branch name.

    Returns the current git branch with unsafe characters replaced by hyphens.
    Falls back to 'default' on any error (not in a git repo, git not installed, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            sanitized = branch.replace("/", "-")
            sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
            sanitized = re.sub(r"-+", "-", sanitized).strip("-")
            if ".." in sanitized or sanitized.startswith("."):
                return "default"
            return sanitized or "default"
        return "default"
    except Exception:
        return "default"
