#!/usr/bin/env python3
"""
Ralph Loop Iteration Logger - PostToolUse Hook.

Logs structured iteration metrics and detects thrashing patterns.

OBSERVABILITY ONLY - does not block.

Exit codes:
  0 - Always (PostToolUse hooks don't block)
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# Paths - BRANCH-SCOPED
PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
MAP_DIR = PROJECT_DIR / ".map"

# Debug mode
DEBUG_MODE = os.environ.get("RALPH_DEBUG", "").lower() in ("1", "true", "yes")


def load_thrashing_config(project_dir: Path) -> tuple[int, int, float]:
    """
    Load thrashing detection config from ralph-loop-config.json.

    Returns (window_size, same_file_repeat_threshold, effectiveness_threshold).
    Environment variables override config values (for tests/debug).
    """
    defaults = (3, 3, 0.5)
    config_file = project_dir / ".claude" / "ralph-loop-config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text()).get("ralph_loop", {})
            td = cfg.get("thrashing_detection", {})
            defaults = (
                int(td.get("window_size", defaults[0])),
                int(td.get("same_file_repeat_threshold", defaults[1])),
                float(td.get("effectiveness_threshold", defaults[2])),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            # Ignore invalid config and fall back to default thrashing detection settings
            pass

    # Override via env vars if present (for tests)
    # Clamp to minimum 1 to prevent division by zero and always-true conditions
    window_size = max(
        1, int(os.environ.get("RALPH_THRASHING_WINDOW", str(defaults[0])))
    )
    same_file_threshold = max(
        1, int(os.environ.get("RALPH_SAME_FILE_THRESHOLD", str(defaults[1])))
    )
    effectiveness_threshold = float(
        os.environ.get("RALPH_EFFECTIVENESS_THRESHOLD", str(defaults[2]))
    )
    return window_size, same_file_threshold, effectiveness_threshold


# Load configuration (single source of truth = .claude/ralph-loop-config.json)
THRASHING_WINDOW, SAME_FILE_REPEAT_THRESHOLD, EFFECTIVENESS_THRESHOLD = (
    load_thrashing_config(PROJECT_DIR)
)


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for safe filesystem paths."""
    sanitized = branch.replace("/", "-")
    sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = sanitized.strip("-")
    if ".." in sanitized or sanitized.startswith("."):
        return "default"
    return sanitized or "default"


def get_branch_name() -> str:
    """Get current git branch name (sanitized) for branch-scoped artifacts."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
            timeout=1,
            check=False,
        )
        if result.returncode == 0:
            return sanitize_branch_name(result.stdout.strip())
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        # If git is unavailable or not a repo, fall back to default branch name
        pass
    return "default"


def get_log_file() -> Path:
    """Get branch-scoped iteration log file path."""
    branch = get_branch_name()
    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    return branch_dir / "iteration_log.jsonl"


def get_alerts_file() -> Path:
    """Get branch-scoped alerts file path."""
    branch = get_branch_name()
    branch_dir = MAP_DIR / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    return branch_dir / "thrashing_alerts.jsonl"


def get_exit_code(tool_response: dict) -> int | None:
    """Extract exit code with tolerance for different key names."""
    # Try multiple possible key names
    for key in ("exit_code", "exitCode", "status", "returnCode", "return_code"):
        value = tool_response.get(key)
        if value is not None:
            try:
                return int(value)
            except (ValueError, TypeError):
                pass
    return None


def calculate_effectiveness(tool_name: str, tool_response: dict | None) -> float:
    """
    Calculate effectiveness score based on STRUCTURED indicators, not string search.

    For Bash: use exit_code if available (tolerant of key name variations)
    For Edit/Write: use success indicator
    """
    if not tool_response:
        return 1.0

    # Bash tool: check exit code (most reliable)
    if tool_name == "Bash":
        exit_code = get_exit_code(tool_response)
        if exit_code is not None:
            return 1.0 if exit_code == 0 else 0.3
        # Fallback: check for explicit error field
        if tool_response.get("error"):
            return 0.3

    # Edit/Write: check for explicit success/error fields
    if tool_name in ("Edit", "Write"):
        if tool_response.get("error"):
            return 0.3
        if tool_response.get("success") is False:
            return 0.3

    # Default: assume success
    return 1.0


def detect_thrashing(log_file: Path) -> dict | None:
    """
    Detect thrashing patterns:
    1. Same file edited repeatedly
    2. Low effectiveness over window
    """
    try:
        if not log_file.exists():
            return None

        lines = log_file.read_text().strip().split("\n")
        recent = []
        for line in lines[-THRASHING_WINDOW:]:
            if line:
                try:
                    recent.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if len(recent) < THRASHING_WINDOW:
            return None

        # Check 1: Same file edited repeatedly
        files = [
            r.get("file")
            for r in recent
            if r.get("file") and r.get("tool") in ("Edit", "Write")
        ]
        if files:
            file_counts = Counter(files)
            most_common_file, count = file_counts.most_common(1)[0]
            if count >= SAME_FILE_REPEAT_THRESHOLD:
                return {
                    "type": "file_thrashing",
                    "file": most_common_file,
                    "count": count,
                }

        # Check 2: Low effectiveness
        effectiveness_values = [r.get("effectiveness", 1.0) for r in recent]
        avg_effectiveness = sum(effectiveness_values) / len(effectiveness_values)
        if avg_effectiveness < EFFECTIVENESS_THRESHOLD:
            return {
                "type": "low_effectiveness",
                "avg_effectiveness": avg_effectiveness,
            }

        return None
    except (OSError, json.JSONDecodeError):
        return None


def main() -> None:
    """Main hook execution logic."""
    if os.environ.get("MAP_INVOKED_BY"):
        sys.exit(0)
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    # Debug mode: log raw input for schema verification
    if DEBUG_MODE:
        debug_file = MAP_DIR / get_branch_name() / "raw_hook_inputs.jsonl"
        debug_file.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_file, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"hook": "iteration-logger", "input": input_data}, ensure_ascii=True
                )
                + "\n"
            )

    tool_name = input_data.get("tool_name", "unknown")
    tool_input = input_data.get("tool_input", {})
    tool_response = input_data.get("tool_response")
    session_id = input_data.get("session_id", "")

    log_file = get_log_file()
    alerts_file = get_alerts_file()

    # Extract file path for Edit/Write tools
    file_path = ""
    if tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    # Calculate effectiveness using structured approach
    effectiveness = calculate_effectiveness(tool_name, tool_response)

    # Count iterations
    try:
        if log_file.exists():
            lines = log_file.read_text().strip().split("\n")
            iteration_count = len([line for line in lines if line]) + 1
        else:
            iteration_count = 1
    except OSError:
        iteration_count = 1

    # Log iteration (atomic write)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "iteration": iteration_count,
        "tool": tool_name,
        "file": file_path,
        "effectiveness": effectiveness,
        "session_id": session_id,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        # Best-effort logging: failures must not block tool execution
        pass

    # Check for thrashing
    thrashing = detect_thrashing(log_file)
    if thrashing:
        alert = {
            "ts": datetime.now(UTC).isoformat(),
            "alert_type": thrashing["type"],
            **thrashing,
            "message": "Thrashing detected: consider different approach",
        }

        try:
            with open(alerts_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(alert, ensure_ascii=True) + "\n")
        except OSError:
            # Best-effort alerting: failures must not block tool execution
            pass

        # Output warning to stderr (informational only)
        if thrashing["type"] == "file_thrashing":
            print(
                f"[ralph-logger] File '{thrashing['file']}' edited {thrashing['count']} times "
                f"in last {THRASHING_WINDOW} operations",
                file=sys.stderr,
            )
        else:
            print(
                f"[ralph-logger] Low effectiveness ({thrashing['avg_effectiveness']:.2f}) "
                f"over last {THRASHING_WINDOW} operations",
                file=sys.stderr,
            )

    # Derive iteration summary (best-effort, never blocks)
    try:
        derive_summary(log_file)
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass

    print("{}")
    sys.exit(0)


def derive_summary(log_file: Path) -> None:
    """Derive iteration_summary.json from iteration_log.jsonl.

    Reads only the last 100 lines (via deque) to keep O(1) memory and fast I/O.
    Aggregates per-file stats, skips entries without a file path.
    """
    if not log_file.exists():
        return

    from collections import deque

    # Stream only last 100 lines — O(N) read but O(1) memory
    total_lines = 0
    last_lines: deque[str] = deque(maxlen=100)
    with open(log_file, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                total_lines += 1
                last_lines.append(stripped)

    entries = []
    for line in last_lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return

    dropped_count = max(0, total_lines - len(entries))

    # Aggregate per-file stats — skip entries without a concrete file path
    file_data: dict[str, list[float]] = {}
    file_thrashing: Counter[str] = Counter()
    for entry in entries:
        f = (entry.get("file") or "").strip()
        if not f:
            continue
        eff = entry.get("effectiveness", 0.0)
        file_data.setdefault(f, []).append(eff)
        file_thrashing[f] += 1

    file_stats: list[dict[str, object]] = []
    thrashing_alert_count = 0
    for f, effs in sorted(file_data.items(), key=lambda x: -len(x[1])):
        is_thrashing = file_thrashing[f] >= THRASHING_WINDOW
        if is_thrashing:
            thrashing_alert_count += 1
        file_stats.append(
            {
                "file": f,
                "iterations": len(effs),
                "avg_effectiveness": round(sum(effs) / len(effs), 3) if effs else 0.0,
                "is_thrashing": is_thrashing,
            }
        )

    all_effs = [
        e.get("effectiveness", 0.0) for e in entries if (e.get("file") or "").strip()
    ]
    summary: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "entry_count": len(entries),
        "total_entries_seen": total_lines,
        "dropped_count": dropped_count,
        "file_stats": file_stats,
        "aggregate": {
            "total_iterations": total_lines,
            "avg_effectiveness": (
                round(sum(all_effs) / len(all_effs), 3) if all_effs else 0.0
            ),
            "total_thrashing_alerts": thrashing_alert_count,
        },
    }

    summary_file = log_file.parent / "iteration_summary.json"
    with open(summary_file, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=True)


if __name__ == "__main__":
    main()
