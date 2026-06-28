#!/usr/bin/env python3
"""Validate file:line citations inside a /map-plan spec.

Scans `.map/<branch>/spec_<branch>.md` for `<path>:<line>[-<line>]` patterns,
checks that each path exists, the line range is in bounds, and (when a nearby
backticked identifier is detected in the spec text) the cited line actually
contains that identifier. Prints a JSON verdict on stdout; exits non-zero on
any failure so /map-plan can gate decomposition.

Usage:
    python3 .map/scripts/validate_spec_citations.py [--branch BRANCH] \
        [--spec-path PATH] [--repo-root PATH]

The branch slug follows the same sanitization rule as the orchestrator
(`/` and other special chars replaced with `-`). Citations whose path looks
like a URL or starts with `http`/`/Users/` are skipped (out of repo scope).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Match `<path>:<line>` or `<path>:<start>-<end>`, where the path ends in a
# recognised extension. The negative lookbehind on `:` avoids matching the
# second half of an already-matched range, and the positive lookahead on
# `[\s,;)\]]` (or EOL) avoids gluing onto trailing punctuation.
_CITATION_RE = re.compile(
    r"""
    (?<![:\w])                  # not preceded by another colon-citation or word
    (?P<path>
        [\w./\-]+               # path component
        \.(?:py|md|sh|toml|yaml|yml|json|js|ts|go|rs|tsx|jsx)
    )
    :
    (?P<line>\d+)
    (?:-(?P<endline>\d+))?
    (?=[\s,.;)\]'`"]|$)
    """,
    re.VERBOSE | re.MULTILINE,
)

# Match a `\`identifier\`` adjacent to a citation; identifiers may be Python
# symbols, env-var names, or hyphen-cased module names.
_IDENT_RE = re.compile(r"`([A-Za-z_][\w./\-]{1,79})`")

# Citations whose path looks like one of these are skipped (not in-repo).
_SKIP_PREFIXES = ("http://", "https://", "/Users/", "/home/", "~/", "$HOME")

# Directories excluded from bare-basename searches to avoid false positives.
_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".tox", ".venv", "venv", ".mypy_cache",
})


def _find_by_basename(repo_root: Path, basename: str) -> list[Path]:
    """Return regular files whose name equals ``basename`` under ``repo_root``.

    Common non-source directories are skipped so results only reflect actual
    project files and the search stays fast on large repos.
    """
    results = []
    for p in repo_root.rglob(basename):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(repo_root).parts):
            continue
        results.append(p)
    return results


def _branch_slug() -> str:
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-zA-Z0-9_.-]", "-", raw)).strip("-")


def _resolve_repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _nearest_identifier(spec_text: str, citation_start: int, window: int = 80) -> str | None:
    """Return the closest backticked identifier within `window` chars of the citation."""
    left = spec_text[max(0, citation_start - window) : citation_start]
    right = spec_text[citation_start : citation_start + window]
    # Prefer the rightmost identifier on the LEFT of the citation
    # (e.g. ``MAP_DEBUG`` `src/mapify_cli/__init__.py:96`)
    left_matches = list(_IDENT_RE.finditer(left))
    if left_matches:
        return left_matches[-1].group(1)
    right_matches = _IDENT_RE.search(right)
    if right_matches:
        return right_matches.group(1)
    return None


def _check_citation(
    repo_root: Path,
    spec_text: str,
    match: re.Match[str],
) -> dict[str, object]:
    raw_path = match.group("path")
    if any(raw_path.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return {"path": raw_path, "status": "skipped", "reason": "out-of-repo path"}

    line_no = int(match.group("line"))
    end_no = int(match.group("endline")) if match.group("endline") else line_no

    target = (repo_root / raw_path).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError:
        return {
            "path": raw_path,
            "line": line_no,
            "status": "error",
            "reason": "resolved path escapes repo root",
        }

    resolved_from_basename: str | None = None
    if not target.is_file():
        # Bare filename (no path separator): try repo-wide basename search so a
        # citation like `api.ts:80` resolves to `web-review/src/api.ts:80` when
        # that is the only file with that name.  Full paths that simply don't
        # exist keep the original "file does not exist" error.
        is_bare = "/" not in raw_path and "\\" not in raw_path
        if is_bare:
            matches = _find_by_basename(repo_root, raw_path)
            if len(matches) == 1:
                target = matches[0]
                resolved_from_basename = str(target.relative_to(repo_root))
            elif len(matches) > 1:
                shown = sorted(str(m.relative_to(repo_root)) for m in matches)
                preview = ", ".join(shown[:3]) + (" …" if len(shown) > 3 else "")
                return {
                    "path": raw_path,
                    "line": line_no,
                    "status": "warning",
                    "reason": (
                        f"ambiguous bare basename: {len(matches)} files match "
                        f"({preview}) — use a repo-root-relative path"
                    ),
                }
            else:
                return {
                    "path": raw_path,
                    "line": line_no,
                    "status": "error",
                    "reason": (
                        f"file does not exist: {raw_path!r} not found anywhere in the repo "
                        "(consider a repo-root-relative path)"
                    ),
                }
        else:
            return {
                "path": raw_path,
                "line": line_no,
                "status": "error",
                "reason": f"file does not exist at {raw_path}",
            }

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {
            "path": raw_path,
            "line": line_no,
            "status": "error",
            "reason": f"could not read file: {exc}",
        }

    # Validate the line range against the file. The previous version only
    # checked `line_no < 1 or end_no > len(lines)`, which missed two cases:
    #   1. Reversed range (e.g. `file.py:20-10`) — end is below start.
    #   2. Out-of-bounds start where end happens to be in range
    #      (e.g. file has 10 lines, citation `file.py:50-5`: start=50 fails
    #      but end_no=5 passes the upper-bound check).
    # Validate every bound independently.
    if (
        line_no < 1
        or end_no < line_no
        or line_no > len(lines)
        or end_no > len(lines)
    ):
        reason_parts = [f"line out of range (file has {len(lines)} lines)"]
        if end_no < line_no:
            reason_parts.append(f"reversed range: end {end_no} < start {line_no}")
        return {
            "path": raw_path,
            "line": line_no,
            "end_line": end_no,
            "status": "error",
            "reason": "; ".join(reason_parts),
        }

    ident = _nearest_identifier(spec_text, match.start())
    _extra: dict[str, object] = (
        {"resolved_to": resolved_from_basename} if resolved_from_basename else {}
    )
    if ident is None:
        return {
            "path": raw_path,
            "line": line_no,
            "end_line": end_no,
            "status": "ok-no-identifier",
            "reason": "path/line valid; no adjacent identifier to cross-check",
            **_extra,
        }

    cited_block = "\n".join(lines[line_no - 1 : end_no])
    if ident in cited_block:
        return {
            "path": raw_path,
            "line": line_no,
            "end_line": end_no,
            "identifier": ident,
            "status": "ok",
            **_extra,
        }

    return {
        "path": raw_path,
        "line": line_no,
        "end_line": end_no,
        "identifier": ident,
        "status": "stale-citation",
        "reason": (
            f"identifier {ident!r} not found at line {line_no}"
            + (f"-{end_no}" if end_no != line_no else "")
            + "; cited block does not contain it"
        ),
        **_extra,
    }


def validate_spec(spec_path: Path, repo_root: Path) -> dict[str, object]:
    text = spec_path.read_text(encoding="utf-8", errors="replace")
    results = [
        _check_citation(repo_root, text, m) for m in _CITATION_RE.finditer(text)
    ]
    failures = [r for r in results if r["status"] in ("error", "stale-citation")]
    warnings = [r for r in results if r["status"] == "warning"]
    return {
        "spec_path": str(spec_path),
        "repo_root": str(repo_root),
        "total_citations": len(results),
        "failures": failures,
        "warnings": warnings,
        "passed": len(failures) == 0,
        "details": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0] or "Validate spec citations."
    )
    parser.add_argument("--branch", help="branch slug (default: current git HEAD)")
    parser.add_argument("--spec-path", help="explicit spec file path (overrides --branch)")
    parser.add_argument(
        "--repo-root", help="repo root path (default: `git rev-parse --show-toplevel`)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress per-citation details on success",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _resolve_repo_root()

    if args.spec_path:
        spec_path = Path(args.spec_path).resolve()
    else:
        branch = args.branch or _branch_slug()
        if not branch:
            print(
                json.dumps({"status": "error", "reason": "could not determine branch"}),
                file=sys.stderr,
            )
            return 2
        spec_path = repo_root / ".map" / branch / f"spec_{branch}.md"

    if not spec_path.is_file():
        print(
            json.dumps({"status": "error", "reason": f"spec not found: {spec_path}"}),
            file=sys.stderr,
        )
        return 2

    verdict = validate_spec(spec_path, repo_root)
    if args.quiet and verdict["passed"]:
        verdict.pop("details", None)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
