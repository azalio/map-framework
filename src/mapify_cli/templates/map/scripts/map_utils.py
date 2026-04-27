"""Shared utilities for MAP workflow scripts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional


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


def parse_numeric_constraint(raw_value: str) -> Optional[int]:
    """Parse integer constraint values, accepting quoted ints/floats like 3.0."""
    normalized = raw_value.strip().strip('"\'')
    if normalized in {"", "null", "None"}:
        return None

    try:
        numeric = float(normalized)
    except ValueError:
        return None

    if not numeric.is_integer():
        return None
    return int(numeric)


def strip_yaml_comment(raw_line: str) -> str:
    """Strip YAML comments while preserving # characters inside quotes."""
    in_single = False
    in_double = False
    escaped = False
    result: list[str] = []

    for ch in raw_line:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_double:
            result.append(ch)
            escaped = True
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            result.append(ch)
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            result.append(ch)
            continue
        if ch == "#" and not in_single and not in_double:
            break
        result.append(ch)

    return "".join(result).rstrip()


def load_constraints_from_spec(plan_dir: Path, branch: str) -> Optional[dict]:
    """Parse the optional YAML-like constraints block from spec_<branch>.md."""
    spec_path = plan_dir / f"spec_{branch}.md"
    if not spec_path.exists():
        return None

    content = spec_path.read_text(encoding="utf-8", errors="replace")
    if not content:
        return None

    match = re.search(
        r"## Constraints\n\n```yaml\nconstraints:\n(?P<body>.*?)```",
        content,
        re.DOTALL,
    )
    if not match:
        return None

    parsed: dict[str, object] = {}
    for raw_line in match.group("body").splitlines():
        line = strip_yaml_comment(raw_line)
        if not line.strip() or ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        normalized = value.strip()
        if normalized in {"null", "None", ""}:
            parsed[key] = None
        elif key in {"max_files", "max_subtasks"}:
            parsed[key] = parse_numeric_constraint(normalized)
        else:
            parsed[key] = normalized.strip('"\'')

    return parsed or None
