#!/usr/bin/env python3
"""MAP Context Statusline - Claude Code ``statusLine`` command.

Claude Code pipes a JSON session object on stdin and renders this command's
single-line stdout in its own status row (above the built-in footer badges).
The harness PRE-COMPUTES context-window usage and hands it to us
(``context_window.used_percentage`` / ``context_window_size`` /
``total_input_tokens``), so this hook does NO transcript parsing, NO token
counting, and NO network - it only formats already-available numbers plus the
git branch and the active MAP subtask.

Wired via the ``statusLine`` key in ``.claude/settings.local.json`` at install
time, and ONLY when no statusLine already exists in any scope MAP must respect
(see ``ensure_map_statusline``) - so it never clobbers a user's own status line.

Output contract:
    * Exactly ONE line to stdout.
    * Never blank and never raises: any error degrades to a minimal safe line
      so the status row never goes dark (an empty/non-zero statusLine command
      blanks the row in Claude Code).

Why synchronous is justified here (the project mandates async for long-running
hooks): Claude Code invokes this command on each render and its stdout IS the
rendered line, so a detached status line is architecturally impossible. The
work is only small bounded reads (stdin JSON + one ``.git/HEAD`` + one small
``step_state.json``) with no network, so it stays well under the render budget.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Fallback window when the harness omits context_window_size. We bias LOW (200k)
# on purpose: an underestimate shows a falsely-HIGH % that self-corrects (the
# user investigates), whereas an overestimate hides a real context blowup. The
# trailing "?" marks the value as a guess so a wrong % is never shown silently.
_FALLBACK_WINDOW_LABEL = "200k?"


def _fmt_tokens(value: object) -> str:
    """Render a token count compactly: 94000 -> '94k', 1000000 -> '1.0M'."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "?"
    n = int(value)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def _sanitize_branch(branch: str) -> str:
    """Mirror the branch-dir sanitisation used by the other MAP hooks."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def _git_branch(project_dir: Path) -> str | None:
    """Return the current branch from ``.git/HEAD`` WITHOUT shelling out to git.

    Handles the linked-worktree case where ``.git`` is a file pointing at the
    real gitdir via ``gitdir: <path>``. Returns a branch name, a short detached
    SHA, or ``None`` when the directory is not a git repository.
    """
    git_path = project_dir / ".git"
    try:
        if git_path.is_file():
            pointer = git_path.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            gitdir = Path(pointer[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (project_dir / gitdir).resolve()
            head_file = gitdir / "HEAD"
        else:
            head_file = git_path / "HEAD"
        head = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    marker = "ref: refs/heads/"
    if head.startswith(marker):
        return head[len(marker):].strip() or None
    if head:
        return head[:7]  # detached HEAD -> short SHA
    return None


def _map_step(project_dir: Path, branch: str) -> str | None:
    """Best-effort 'ST-003 ACTOR' label from ``.map/<branch>/step_state.json``.

    A single bounded read; returns ``None`` on any problem so the segment is
    simply omitted rather than breaking the line.
    """
    state_file = project_dir / ".map" / _sanitize_branch(branch) / "step_state.json"
    try:
        if not state_file.is_file():
            return None
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    sid = data.get("current_subtask_id")
    phase = data.get("current_step_phase")
    parts = [str(p).strip() for p in (sid, phase) if p]
    return " ".join(parts) or None


def _project_dir(data: dict) -> Path:
    workspace = data.get("workspace")
    if isinstance(workspace, dict) and workspace.get("current_dir"):
        return Path(str(workspace["current_dir"]))
    cwd = data.get("cwd")
    if cwd:
        return Path(str(cwd))
    return Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))


def _model_prefix(data: dict) -> str:
    model = data.get("model")
    if isinstance(model, dict):
        name = str(model.get("display_name") or model.get("id") or "").strip()
        if name:
            return f"[{name}] "
    return ""


def _build_line(data: dict) -> str:
    prefix = _model_prefix(data)
    project_dir = _project_dir(data)

    context = data.get("context_window")
    context = context if isinstance(context, dict) else {}

    # No context numbers yet (e.g. before the first API response provides a
    # context_window block): degrade to a never-blank neutral line.
    if not context:
        tail = project_dir.name or "MAP"
        return f"{prefix}MAP · {tail}"

    pct = context.get("used_percentage")
    if pct is None:
        pct_str = "--%"
    else:
        try:
            pct_str = f"{round(float(pct))}%"
        except (TypeError, ValueError):
            pct_str = "--%"

    used_str = _fmt_tokens(context.get("total_input_tokens"))
    window = context.get("context_window_size")
    window_str = _fmt_tokens(window) if window else _FALLBACK_WINDOW_LABEL

    segments = [f"MAP ctx {pct_str} ({used_str}/{window_str})"]

    branch = _git_branch(project_dir)
    if branch:
        segments.append(branch)
        step = _map_step(project_dir, branch)
        if step:
            segments.append(step)

    return prefix + " · ".join(segments)


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, ValueError):
        data = {}
    try:
        line = _build_line(data)
    except Exception:  # noqa: BLE001 - a status line must never crash to blank
        line = "[MAP]"
    sys.stdout.write(line + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
