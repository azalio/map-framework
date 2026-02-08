#!/usr/bin/env python3
"""diagnostics.py

Small helper for recording structured diagnostics from test/lint commands.

This is intentionally best-effort: store a parsed list of file:line messages when
present and always keep a raw tail excerpt for debugging.

Output:
  .map/<branch>/diagnostics.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_branch_name() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/", "-")
    except Exception:
        pass
    return "default"


def default_output_path(branch: str) -> Path:
    return Path(f".map/{branch}/diagnostics.json")


@dataclass
class Issue:
    path: str | None
    line: int | None
    col: int | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "message": self.message,
        }


FILE_LINE_RE = re.compile(
    r"^(?P<path>[^:\s][^:]*):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<msg>.+)$"
)


def parse_issues(text: str, limit: int = 50) -> list[Issue]:
    issues: list[Issue] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\n")
        if not line:
            continue

        m = FILE_LINE_RE.match(line)
        if not m:
            continue

        path = m.group("path")
        line_no = int(m.group("line"))
        col_raw = m.group("col")
        col_no = int(col_raw) if col_raw is not None else None
        msg = m.group("msg").strip()
        issues.append(Issue(path=path, line=line_no, col=col_no, message=msg))
        if len(issues) >= limit:
            break

    return issues


def tail_text(text: str, max_lines: int = 80) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[-max_lines:])


def cmd_parse(args: argparse.Namespace) -> int:
    branch = args.branch or get_branch_name()
    out_path = Path(args.out) if args.out else default_output_path(branch)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log_path = Path(args.log)
    text = log_path.read_text(encoding="utf-8", errors="replace")

    issues = parse_issues(text)
    payload = {
        "updated_at": utc_now(),
        "branch": branch,
        "tool": args.tool,
        "command": args.command,
        "exit_code": args.exit_code,
        "log_path": str(log_path),
        "issues": [i.to_dict() for i in issues],
        "raw_tail": tail_text(text),
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record parsed diagnostics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parse = sub.add_parser("parse", help="Parse a command log into diagnostics.json")
    p_parse.add_argument(
        "--tool", required=True, help="Tool name (tests|lint|ruff|mypy|tsc|...) "
    )
    p_parse.add_argument(
        "--log", required=True, help="Path to captured stdout/stderr log"
    )
    p_parse.add_argument("--command", default="", help="Command that produced the log")
    p_parse.add_argument(
        "--exit-code", type=int, default=0, help="Exit code of the command"
    )
    p_parse.add_argument(
        "--out",
        default="",
        help="Output path (default: .map/<branch>/diagnostics.json)",
    )
    p_parse.add_argument("--branch", default="", help="Branch override")
    p_parse.set_defaults(func=cmd_parse)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
