"""diagnostics.py

Small helper for recording structured diagnostics from test/lint commands.

This is intentionally best-effort: store a parsed list of file:line messages when
present and always keep a raw tail excerpt for debugging.

Output:
  .map/<branch>/diagnostics.json
  .map/<branch>/run-summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            branch = result.stdout.strip()
            sanitized = branch.replace("/", "-")
            sanitized = re.sub(r"[^a-zA-Z0-9_.-]", "-", sanitized)
            sanitized = re.sub(r"-+", "-", sanitized).strip("-")
            if ".." in sanitized or sanitized.startswith("."):
                return "default"
            return sanitized or "default"
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return "default"


def default_output_path(branch: str) -> Path:
    return Path(f".map/{branch}/diagnostics.json")


def default_run_summary_path(branch: str) -> Path:
    return Path(f".map/{branch}/run-summary.json")


def default_runs_dir(branch: str) -> Path:
    return Path(f".map/{branch}/runs")


def make_run_dir(branch: str, base_time: str | None = None) -> Path:
    """Create a unique timestamped run dossier directory."""
    stamp = base_time or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    runs_dir = default_runs_dir(branch)
    runs_dir.mkdir(parents=True, exist_ok=True)

    candidate = runs_dir / stamp
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    counter = 1
    while True:
        alt = runs_dir / f"{stamp}-{counter:02d}"
        if not alt.exists():
            alt.mkdir(parents=True, exist_ok=False)
            return alt
        counter += 1


def write_run_dossier(
    branch: str,
    tool: str,
    command: str,
    status: str,
    summary: str,
    diagnostics_payload: dict[str, Any],
    accepted_issue_count: int,
    deferred_issue_count: int,
    notes: str = "",
) -> dict[str, str]:
    """Write a timestamped run dossier with RESULTS.md and optional NOTES.md."""
    run_dir = make_run_dir(branch)
    results_file = run_dir / "RESULTS.md"
    notes_file = run_dir / "NOTES.md"

    issues = diagnostics_payload.get("issues", [])
    diagnostics_path = diagnostics_payload.get(
        "diagnostics_path"
    ) or diagnostics_payload.get("log_path")
    issue_lines = "\n".join(
        f"- `{issue.get('path', '[unknown]')}:{issue.get('line', '?')}` — {issue.get('message', '')}"
        for issue in issues[:10]
    )
    if not issue_lines:
        issue_lines = "- (None)"

    content = (
        "# Run Results\n\n"
        "## Setup\n"
        f"- Branch: {branch}\n"
        f"- Tool: {tool}\n"
        f"- Command: `{command or '[not recorded]'}`\n\n"
        "## Summary\n"
        f"- Status: {status.upper()}\n"
        f"- Summary: {summary}\n\n"
        "## Check Matrix\n"
        "| Tool | Result | Notes |\n"
        "|---|---|---|\n"
        f"| {tool} | {status.upper()} | {summary} |\n\n"
        "## Detailed Results\n"
        f"- Issue count: {len(issues)}\n"
        f"- Accepted issue count: {accepted_issue_count}\n"
        f"- Deferred issue count: {deferred_issue_count}\n"
        f"- Diagnostics source: {diagnostics_path or '[not recorded]'}\n\n"
        "## Bugs / Blockers Found\n"
        f"{issue_lines}\n\n"
        "## Accepted / Deferred Issues\n"
        + (
            f"- {accepted_issue_count} accepted and {deferred_issue_count} deferred issue(s) recorded in known-issues.json\n"
            if accepted_issue_count or deferred_issue_count
            else "- (None)\n"
        )
    )
    results_file.write_text(content, encoding="utf-8")

    if notes.strip():
        notes_file.write_text(f"# Notes\n\n{notes.strip()}\n", encoding="utf-8")

    return {
        "run_dir": str(run_dir),
        "results_path": str(results_file),
        "notes_path": str(notes_file) if notes.strip() else "",
    }


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


def cmd_summarize(args: argparse.Namespace) -> int:
    branch = args.branch or get_branch_name()
    out_path = Path(args.out) if args.out else default_run_summary_path(branch)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    diagnostics_path = (
        Path(args.diagnostics) if args.diagnostics else default_output_path(branch)
    )
    diagnostics_payload: dict[str, Any] = {}
    if diagnostics_path.exists():
        try:
            diagnostics_payload = json.loads(
                diagnostics_path.read_text(encoding="utf-8", errors="replace")
            )
        except json.JSONDecodeError:
            diagnostics_payload = {}

    known_issues = []
    if args.known_issues:
        known_path = Path(args.known_issues)
        if known_path.exists():
            try:
                known_payload = json.loads(
                    known_path.read_text(encoding="utf-8", errors="replace")
                )
                known_issues = known_payload.get("issues", [])
            except json.JSONDecodeError:
                known_issues = []

    issues = diagnostics_payload.get("issues", [])
    status = "passed" if args.exit_code == 0 else "failed"
    accepted_issue_count = sum(
        1 for issue in known_issues if issue.get("status") == "accepted"
    )
    deferred_issue_count = sum(
        1 for issue in known_issues if issue.get("status") == "deferred"
    )

    payload = {
        "updated_at": utc_now(),
        "branch": branch,
        "tool": args.tool,
        "command": args.command,
        "exit_code": args.exit_code,
        "status": status,
        "issue_count": len(issues),
        "accepted_issue_count": accepted_issue_count,
        "summary": args.summary
        or ("No blocking issues" if status == "passed" else "Blocking issues detected"),
        "diagnostics_path": str(diagnostics_path)
        if diagnostics_path.exists()
        else None,
    }

    dossier = write_run_dossier(
        branch=branch,
        tool=args.tool,
        command=args.command,
        status=status,
        summary=payload["summary"],
        diagnostics_payload={
            **diagnostics_payload,
            "diagnostics_path": payload["diagnostics_path"],
        },
        accepted_issue_count=accepted_issue_count,
        deferred_issue_count=deferred_issue_count,
        notes=args.notes,
    )
    payload.update(dossier)

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

    p_summary = sub.add_parser("summarize", help="Write compact run summary")
    p_summary.add_argument("--tool", required=True, help="Tool name")
    p_summary.add_argument("--command", default="", help="Executed command")
    p_summary.add_argument("--exit-code", type=int, default=0, help="Exit code")
    p_summary.add_argument("--summary", default="", help="Short human-readable summary")
    p_summary.add_argument(
        "--diagnostics",
        default="",
        help="Diagnostics JSON path (default: .map/<branch>/diagnostics.json)",
    )
    p_summary.add_argument("--known-issues", default="", help="Known issues JSON path")
    p_summary.add_argument("--notes", default="", help="Optional NOTES.md content")
    p_summary.add_argument("--out", default="", help="Output path")
    p_summary.add_argument("--branch", default="", help="Branch override")
    p_summary.set_defaults(func=cmd_summarize)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
