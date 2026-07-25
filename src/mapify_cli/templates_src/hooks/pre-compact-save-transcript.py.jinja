#!/usr/bin/env python3
"""
Pre-Compact Transcript Saver - PreCompact Hook.

Before context compaction, saves the full conversation transcript
to .map/<branch>/transcript-YYYY-MM-DD-HH-MM-SS.md as readable markdown.

This preserves the full context for later review.

Exit codes:
  0 - Always (PreCompact hooks don't block)
"""
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
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
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def extract_text_from_content(content):
    """Extract readable text from message content (string or list)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            item_type = item.get("type", "")
            if item_type == "text":
                parts.append(item.get("text", ""))
            elif item_type == "tool_use":
                name = item.get("name", "unknown")
                tool_input = item.get("input", {})
                input_str = json.dumps(tool_input, ensure_ascii=False)
                # Truncate long tool inputs
                if len(input_str) > 500:
                    input_str = input_str[:500] + "..."
                parts.append(f"**Tool:** `{name}`\n```json\n{input_str}\n```")
            elif item_type == "tool_result":
                result_content = item.get("content", "")
                if isinstance(result_content, list):
                    for rc in result_content:
                        if isinstance(rc, dict) and rc.get("type") == "text":
                            text = rc.get("text", "")
                            if len(text) > 1000:
                                text = text[:1000] + "...[truncated]"
                            parts.append(text)
                elif isinstance(result_content, str):
                    if len(result_content) > 1000:
                        result_content = result_content[:1000] + "...[truncated]"
                    parts.append(result_content)
    return "\n".join(parts)


def parse_transcript(transcript_path: Path) -> str:
    """Parse JSONL transcript into readable markdown."""
    lines = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                message = entry.get("message", {})
                role = message.get("role", "")
                content = message.get("content", "")

                if entry_type == "human" or role == "user":
                    text = extract_text_from_content(content)
                    if text.strip():
                        lines.append(f"## User\n\n{text}\n")
                elif entry_type == "assistant" or role == "assistant":
                    text = extract_text_from_content(content)
                    if text.strip():
                        lines.append(f"## Assistant\n\n{text}\n")
                elif entry_type == "tool_result":
                    text = extract_text_from_content(content)
                    if text.strip():
                        lines.append(
                            f"<details><summary>Tool result</summary>\n\n"
                            f"```\n{text}\n```\n</details>\n"
                        )
    except OSError as e:
        lines.append(f"Error reading transcript: {e}\n")

    return "\n".join(lines)


def maybe_offload_tool_outputs(transcript_path: str, branch_dir: Path) -> None:
    """Offload large tool-result bodies before compaction drops them (#232).

    Only runs when ``compression_policy != never`` so a default install never
    creates ``.map/<branch>/compacted/``. Lazy-imports mapify_cli and degrades
    to a silent no-op if it is not importable. Never raises — a PreCompact hook
    must not break compaction.
    """
    try:
        sys.path.insert(0, str(PROJECT_DIR / "src"))
        try:
            from mapify_cli.config.project_config import load_map_config
            from mapify_cli.tool_output_offload import (
                offload_transcript_tool_outputs,
            )
        except ImportError:
            return
        config = load_map_config(PROJECT_DIR)
        if config.compression_policy == "never":
            return
        summary = offload_transcript_tool_outputs(Path(transcript_path), branch_dir)
        if summary.written:
            print(
                f"[pre-compact-save] Offloaded {summary.written} tool output(s) "
                f"to {branch_dir / 'compacted'}",
                file=sys.stderr,
            )
    except Exception:  # never break compaction  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass


def main() -> None:
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        input_data = {}

    transcript_path = input_data.get("transcript_path", "")
    session_id = input_data.get("session_id", "unknown")

    if not transcript_path or not Path(transcript_path).is_file():
        print("{}")
        sys.exit(0)

    branch = get_branch_name()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M-%S")

    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    outfile = branch_dir / f"transcript-{timestamp}.md"

    header = (
        f"# Conversation snapshot before compact\n\n"
        f"- **Branch:** {branch}\n"
        f"- **Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **Session:** {session_id}\n\n"
        f"---\n\n"
    )

    body = parse_transcript(Path(transcript_path))

    try:
        outfile.write_text(header + body, encoding="utf-8")
        print(f"[pre-compact-save] Saved transcript to {outfile}", file=sys.stderr)
    except OSError as e:
        print(f"[pre-compact-save] Failed to save: {e}", file=sys.stderr)
        print("{}")
        sys.exit(0)

    # Write a pointer file so the context-pruner (or compact summary) can reference it
    pointer = branch_dir / "last-transcript.txt"
    try:
        pointer.write_text(str(outfile.relative_to(PROJECT_DIR)), encoding="utf-8")
    except OSError:
        pass

    # Cooldown marker for context-meter.py - prevents the meter from injecting
    # a fresh /compact nudge immediately after Claude Code's built-in
    # auto-compact (~83.5%) has just run. mtime is what the meter compares
    # against, so the file content is informational only — written in UTC
    # RFC3339 so cross-machine debugging is unambiguous.
    marker = branch_dir / "last-compact.marker"
    try:
        marker.write_text(
            datetime.now(UTC).isoformat(timespec="seconds"),
            encoding="utf-8",
        )
    except OSError:
        pass

    # Offload full-resolution tool-result bodies so dropped outputs stay
    # recoverable instead of forcing a re-run of broad discovery (#232).
    maybe_offload_tool_outputs(transcript_path, branch_dir)

    print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
