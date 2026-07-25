"""Strip MAP-internal workflow IDs from code the framework wrote.

During a MAP run the planning artifacts use internal identifiers — subtask
``ST-001``, acceptance criteria ``AC-3``, verification criteria ``VC1``,
invariants ``INV-7``, hard constraints ``HC-1`` — and an Actor can leak them
into the shipped code as comments (``// The rule (INV-7) is:``) or test names
(``test_vc1_register``). These are workflow scaffolding, not something the user
should review in their PR.

This module is the deterministic *engine*. It is invoked at workflow close by
the ``scrub-internal-ids.py`` Stop hook (Claude provider). It is stdlib-only on
purpose: in an installed project ``mapify_cli`` is not importable, so all logic
must live here under ``.map/scripts/`` (same rationale as ``map_step_runner``).

Safety model — conservative, hard-scoped, corruption-averse:

1. SCOPE. Only files the *run* changed (git diff vs the run base) are touched,
   and within each file only the *lines the run added* (new-side line numbers of
   the diff; the whole file for run-created untracked files). A pre-existing
   ``INV-7`` the user wrote on an untouched line is never modified.
2. FILE TYPE. Only recognized source files are scrubbed, using that language's
   comment syntax (``#`` for Python/shell/YAML, ``//``+``/* */`` for C-likes,
   ``<!-- -->`` for markdown/HTML, ...). Data files (``.json``, ``.lock``, ...)
   and unknown types are skipped entirely — never blanked.
3. EDIT. Only inside COMMENTS:
     - a comment whose payload is only an ID marker  -> delete the line;
     - an ID token inside a larger comment           -> strip the token and tidy
       adjacent decoration (``()`` / ``[]`` / stray ``:``), keep the line.
   Test identifiers carrying ``vc<n>`` are renamed (``test_vc1_foo`` ->
   ``test_foo``) with a collision guard. IDs in code, string literals, or
   docstrings are LEFT IN PLACE and reported (stripping a string substring would
   corrupt legitimate values, e.g. ``"INV-7-special-sku"`` or a JSON value).
4. RE-SCAN. After cleaning, scope is scanned again; anything not removed is
   reported as ``residual`` rather than corrupted.

CLI::

    scrub_internal_ids.py scan  [--base REF] [--branch NAME]   # report only
    scrub_internal_ids.py clean [--base REF] [--branch NAME]   # mutate + report

Always exits 0 — the scrub is advisory and must never block the close. The
caller (hook) decides whether to commit the resulting working-tree changes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# --- ID token patterns -------------------------------------------------------
# Dashed family (ST-/AC-/INV-/HC-/VC-) plus the documented dash-less ``VC1``.
# A leading letter covers ``INV-A1``. We deliberately do NOT match dash-less
# ``AC1``/``HC1``/``ST1`` to avoid clobbering legitimate user tokens (register
# names, enum values); the framework writes the dashed form for those families.
ID_TOKEN = re.compile(r"\b(?:ST|AC|INV|HC|VC)-[A-Za-z]?\d+\b|\bVC\d+\b")

# Test identifier carrying a ``vc<n>`` segment (case-insensitive). Matches the
# documented naming convention ``test_vc1_*`` / ``TestVC1*``.
_VC_SEGMENT = re.compile(r"(?i)vc\d+")

# Definition lines whose function/class identifier is a test name.
_PY_DEF = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
_GO_DEF = re.compile(r"^(\s*)func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)")


# --- per-language comment syntax --------------------------------------------
# Each syntax records which line-comment leaders and block-comment openers apply.
# String literals are always tracked (so a ``#`` inside a string is not a
# comment) but are never eligible for stripping.
_HASH = {"line": ("#",), "block": ()}
_SLASH = {"line": ("//",), "block": ("/*",)}
_DASH = {"line": ("--",), "block": ()}
_HTML = {"line": (), "block": ("<!--",)}  # markdown/HTML: `#` is a heading, NOT a comment
_CSS = {"line": (), "block": ("/*",)}

_EXT_SYNTAX: dict[str, dict] = {
    ".py": _HASH, ".pyi": _HASH, ".sh": _HASH, ".bash": _HASH, ".zsh": _HASH,
    ".yaml": _HASH, ".yml": _HASH, ".toml": _HASH, ".ini": _HASH, ".cfg": _HASH,
    ".conf": _HASH, ".rb": _HASH, ".pl": _HASH, ".r": _HASH, ".tf": _HASH,
    ".go": _SLASH, ".js": _SLASH, ".jsx": _SLASH, ".ts": _SLASH, ".tsx": _SLASH,
    ".mjs": _SLASH, ".cjs": _SLASH, ".rs": _SLASH, ".c": _SLASH, ".h": _SLASH,
    ".cc": _SLASH, ".cpp": _SLASH, ".cxx": _SLASH, ".hpp": _SLASH, ".java": _SLASH,
    ".kt": _SLASH, ".kts": _SLASH, ".swift": _SLASH, ".scala": _SLASH, ".php": _SLASH,
    ".sql": _DASH, ".lua": _DASH, ".hs": _DASH,
    ".html": _HTML, ".htm": _HTML, ".xml": _HTML, ".vue": _HTML, ".svelte": _HTML, ".md": _HTML,
    ".css": _CSS, ".scss": _CSS, ".less": _CSS,
}
_NAME_SYNTAX: dict[str, dict] = {"Dockerfile": _HASH, "Makefile": _HASH}


def syntax_for_ext(ext: str) -> dict | None:
    return _EXT_SYNTAX.get(ext.lower())


def _syntax_for_path(path: Path) -> dict | None:
    return _EXT_SYNTAX.get(path.suffix.lower()) or _NAME_SYNTAX.get(path.name)


# --- pure text helpers (unit-tested without git) -----------------------------
def _line_regions(line: str, syntax: dict | None) -> list[tuple[int, int, str]]:
    """Split a line into (start, end, kind) regions; kind in code/string/comment.

    Comment leaders are taken from ``syntax`` so that, e.g., a markdown ``#``
    heading is NOT treated as a comment. Strings are tracked but never eligible.
    """
    line_leaders = syntax["line"] if syntax else ()
    block_starts = syntax["block"] if syntax else ()
    regions: list[tuple[int, int, str]] = []
    i, n = 0, len(line)
    code_start = 0

    def flush_code(upto: int) -> None:
        if upto > code_start:
            regions.append((code_start, upto, "code"))

    while i < n:
        ch = line[i]
        # Line comment -> runs to EOL.
        if any(line.startswith(leader, i) for leader in line_leaders):
            flush_code(i)
            regions.append((i, n, "comment"))
            code_start = n
            i = n
            break
        # Block comment /* ... */ (single line; to EOL if unterminated).
        if "/*" in block_starts and line.startswith("/*", i):
            flush_code(i)
            end = line.find("*/", i + 2)
            end = n if end == -1 else end + 2
            regions.append((i, end, "comment"))
            code_start = end
            i = end
            continue
        # HTML/XML/markdown comment <!-- ... -->.
        if "<!--" in block_starts and line.startswith("<!--", i):
            flush_code(i)
            end = line.find("-->", i + 4)
            end = n if end == -1 else end + 3
            regions.append((i, end, "comment"))
            code_start = end
            i = end
            continue
        # String literal (tracked so a leader inside it is not a comment).
        if ch in ("'", '"'):
            flush_code(i)
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == ch:
                    break
                j += 1
            end = min(j + 1, n)
            regions.append((i, end, "string"))
            code_start = end
            i = end
            continue
        i += 1

    flush_code(n)
    return regions


def _region_kind(regions: list[tuple[int, int, str]], pos: int) -> str:
    for start, end, kind in regions:
        if start <= pos < end:
            return kind
    return "code"


def _tidy_comment_payload(text: str) -> str:
    """Remove empty brackets and collapse whitespace left by token removal."""
    text = re.sub(r"[(\[{]\s*[)\]}]", "", text)  # empty () [] {}
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    text = text.lstrip(":;,- \t")
    return text.strip()


def _comment_leader(comment_text: str) -> tuple[str, str]:
    """Split a comment region into (leader, payload)."""
    for leader in ("//", "--", "<!--", "/*", "#", ";"):
        if comment_text.lstrip().startswith(leader):
            stripped = comment_text.lstrip()
            payload = stripped[len(leader) :]
            if leader == "/*" and payload.rstrip().endswith("*/"):
                payload = payload.rstrip()[:-2]
            if leader == "<!--" and payload.rstrip().endswith("-->"):
                payload = payload.rstrip()[:-3]
            return leader, payload
    return "", comment_text


def scrub_line(line: str, syntax: dict | None) -> tuple[str | None, list[str], list[str]]:
    """Strip ID tokens that sit INSIDE a comment on one line.

    Returns ``(new_line | None, removed_tokens, residual_tokens)``. ``None``
    means delete the line (a comment that became empty). Tokens outside comments
    (code, string literals, docstrings) are left in place and reported.
    """
    matches = list(ID_TOKEN.finditer(line))
    if not matches:
        return line, [], []

    regions = _line_regions(line, syntax)
    removed: list[str] = []
    residual: list[str] = []
    eligible_spans: list[tuple[int, int]] = []
    for m in matches:
        if _region_kind(regions, m.start()) == "comment":
            eligible_spans.append((m.start(), m.end()))
            removed.append(m.group(0))
        else:
            residual.append(m.group(0))

    if not eligible_spans:
        return line, removed, residual

    # Remove eligible spans right-to-left so indices stay valid.
    new_line = line
    for start, end in sorted(eligible_spans, reverse=True):
        new_line = new_line[:start] + new_line[end:]

    # If the comment is now an empty marker, delete the line (or just the comment
    # if there is meaningful code before it).
    new_regions = _line_regions(new_line, syntax)
    new_comment = [r for r in new_regions if r[2] == "comment"]
    if new_comment:
        cstart, cend, _ = new_comment[0]
        leader, payload = _comment_leader(new_line[cstart:cend])
        tidied = _tidy_comment_payload(payload)
        head = new_line[:cstart]
        if not tidied:
            if head.strip() == "":
                return None, removed, residual
            new_line = head.rstrip()
        else:
            closer = " -->" if leader == "<!--" else (" */" if leader == "/*" else "")
            new_line = f"{head}{leader} {tidied}{closer}"

    return new_line, removed, residual


def renamed_test_identifier(name: str) -> str | None:
    """Drop the ``vc<n>`` segment from a test identifier; None if unchanged.

    ``test_vc1_register`` -> ``test_register``; ``TestVC1Foo`` -> ``TestFoo``.
    """
    if not _VC_SEGMENT.search(name):
        return None
    new = _VC_SEGMENT.sub("", name)
    new = re.sub(r"__+", "_", new)
    new = re.sub(r"_+$", "", new)
    new = re.sub(r"(?<=[A-Za-z])_(?=[A-Z])", "", new)  # Test_Foo -> TestFoo (Go/class)
    if not new or new in ("test", "test_", "Test"):
        return None
    if new == name:
        return None
    return new


def _is_test_def(line: str) -> tuple[str, str] | None:
    """Return (kind, identifier) if the line defines a test, else None."""
    m = _PY_DEF.match(line)
    if m:
        ident = m.group(3)
        if ident.startswith(("test", "Test")):
            return ("py", ident)
    m = _GO_DEF.match(line)
    if m:
        ident = m.group(2)
        if ident.startswith("Test"):
            return ("go", ident)
    return None


def scrub_text(
    text: str, scope: set[int] | None, syntax: dict | None
) -> tuple[str, dict]:
    """Scrub ``text`` (a whole file). ``scope`` = 1-based line numbers to act on
    (``None`` = every line, used for run-created untracked files). ``syntax`` =
    the file's comment syntax (``None`` -> only test renames apply).

    Returns ``(new_text, report)`` where report has ``removed`` (count),
    ``deleted`` (count), ``renames`` ([{old,new}]), ``residual`` ([{line,token}]).
    """
    original_lines = text.splitlines(keepends=True)

    def in_scope(idx0: int) -> bool:
        return scope is None or (idx0 + 1) in scope

    # --- Pass 1: collect test renames (triggered by in-scope def lines) -------
    rename_map: dict[str, str] = {}
    residual: list[dict] = []
    for idx0, raw in enumerate(original_lines):
        if not in_scope(idx0):
            continue
        info = _is_test_def(raw.rstrip("\n"))
        if not info:
            continue
        _kind, ident = info
        new_ident = renamed_test_identifier(ident)
        if new_ident is None:
            continue
        if re.search(rf"\b{re.escape(new_ident)}\b", text):  # collision guard
            residual.append({"line": idx0 + 1, "token": ident, "reason": "rename_collision"})
            continue
        rename_map[ident] = new_ident

    working = text
    renames: list[dict] = []
    for old, new in rename_map.items():
        working = re.sub(rf"\b{re.escape(old)}\b", new, working)
        renames.append({"old": old, "new": new})

    # --- Pass 2: per-line comment token strip / pure-marker deletion ----------
    lines = working.splitlines(keepends=True)
    out: list[str] = []
    removed_count = 0
    deleted_count = 0
    for idx0, raw in enumerate(lines):
        if not in_scope(idx0):
            out.append(raw)
            continue
        body = raw.rstrip("\n")
        newline = raw[len(body):]  # preserve original EOL ("" or "\n")
        new_body, removed, line_residual = scrub_line(body, syntax)
        removed_count += len(removed)
        for tok in line_residual:
            residual.append({"line": idx0 + 1, "token": tok, "reason": "outside_comment"})
        if new_body is None:
            deleted_count += 1
            continue
        out.append(new_body + newline)

    new_text = "".join(out)
    report = {
        "removed": removed_count,
        "deleted": deleted_count,
        "renames": renames,
        "residual": residual,
    }
    return new_text, report


# --- git-facing helpers ------------------------------------------------------
def _git(project_dir: Path, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _default_branch(project_dir: Path) -> str:
    probe = _git(project_dir, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if probe.returncode == 0 and probe.stdout.strip():
        return probe.stdout.strip().split("/")[-1]
    for cand in ("main", "master"):
        if _git(project_dir, "rev-parse", "--verify", cand).returncode == 0:
            return cand
    return "main"


def resolve_run_base(project_dir: Path, explicit: str | None) -> str | None:
    """Resolve the commit the run forked from (scope floor for the scrub).

    Order: explicit ``--base`` -> merge-base(HEAD, default branch) -> None.
    Returns ``None`` when no base can be determined (engine then no-ops, never
    scrubs the whole tree blindly).
    """
    if explicit:
        if _git(project_dir, "rev-parse", "--verify", explicit).returncode == 0:
            return explicit
        return None
    default = _default_branch(project_dir)
    mb = _git(project_dir, "merge-base", "HEAD", default)
    if mb.returncode == 0 and mb.stdout.strip():
        return mb.stdout.strip()
    return None


def _changed_files(project_dir: Path, base: str) -> list[str]:
    files: set[str] = set()
    for args in (
        ("diff", "--name-only", base),  # base vs working tree (committed + unstaged)
        ("diff", "--name-only", "--cached", base),  # staged
    ):
        res = _git(project_dir, *args)
        if res.returncode == 0:
            files.update(p for p in res.stdout.splitlines() if p.strip())
    untracked = _git(project_dir, "ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        files.update(p for p in untracked.stdout.splitlines() if p.strip())
    return sorted(files)


def _added_line_numbers(project_dir: Path, base: str, rel: str) -> set[int] | None:
    """New-side line numbers added/modified vs base for ``rel``.

    ``None`` means "whole file" (a run-created untracked file with no base side).
    """
    tracked = _git(project_dir, "ls-files", "--error-unmatch", rel).returncode == 0
    in_base = _git(project_dir, "cat-file", "-e", f"{base}:{rel}").returncode == 0
    if not in_base and not tracked:
        return None  # new untracked file -> all lines are run-introduced
    diff = _git(project_dir, "diff", "--unified=0", base, "--", rel)
    if diff.returncode != 0:
        return set()
    added: set[int] = set()
    new_ln = 0
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    for line in diff.stdout.splitlines():
        if line.startswith("@@"):
            m = hunk.match(line)
            if m:
                new_ln = int(m.group(1))
            continue
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added.add(new_ln)
            new_ln += 1
        elif line.startswith(" "):
            new_ln += 1
        # deletions ("-") do not advance the new-side counter
    return added


def _affected_files(project_dir: Path, branch: str | None) -> set[str] | None:
    """Blueprint affected_files (narrows scope); None if unavailable."""
    if not branch:
        return None
    bp = project_dir / ".map" / branch / "blueprint.json"
    if not bp.exists():
        return None
    try:
        data = json.loads(bp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    files: set[str] = set()
    subtasks = data.get("subtasks", {})
    if isinstance(subtasks, dict):
        for st in subtasks.values():
            if isinstance(st, dict):
                for p in st.get("affected_files", []) or []:
                    if isinstance(p, str):
                        files.add(p)
    return files or None


# --- driver ------------------------------------------------------------------
def run(project_dir: Path, *, mode: str, base: str | None, branch: str | None) -> dict:
    resolved_base = resolve_run_base(project_dir, base)
    if resolved_base is None:
        return {"status": "no_base", "base": None, "files_modified": [],
                "tokens_removed": 0, "lines_deleted": 0, "tests_renamed": [],
                "residual": [], "reason": "could not resolve a run base; nothing scrubbed"}

    affected = _affected_files(project_dir, branch)
    changed = _changed_files(project_dir, resolved_base)
    if affected is not None:
        changed = [f for f in changed if f in affected]

    files_modified: list[str] = []
    tokens_removed = 0
    lines_deleted = 0
    tests_renamed: list[dict] = []
    residual: list[dict] = []

    for rel in changed:
        path = project_dir / rel
        if not path.is_file():
            continue
        syntax = _syntax_for_path(path)
        if syntax is None:
            continue  # unsupported / data file -> never scrub (avoid corruption)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # skip binary / unreadable
        scope = _added_line_numbers(project_dir, resolved_base, rel)
        if scope is not None and not scope:
            continue  # nothing this run added in this file
        new_text, report = scrub_text(text, scope, syntax)
        for r in report["residual"]:
            residual.append({"file": rel, **r})
        if new_text != text:
            tokens_removed += report["removed"]
            lines_deleted += report["deleted"]
            for rn in report["renames"]:
                tests_renamed.append({"file": rel, **rn})
            files_modified.append(rel)
            if mode == "clean":
                path.write_text(new_text, encoding="utf-8")

    status = "modified" if files_modified else "clean"
    return {
        "status": status,
        "mode": mode,
        "base": resolved_base,
        "files_modified": files_modified,
        "tokens_removed": tokens_removed,
        "lines_deleted": lines_deleted,
        "tests_renamed": tests_renamed,
        "residual": residual,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strip MAP-internal workflow IDs from run-changed code.")
    parser.add_argument("mode", choices=("scan", "clean"))
    parser.add_argument("--base", default=None, help="Run base ref (default: merge-base with the default branch).")
    parser.add_argument("--branch", default=None, help="MAP branch for blueprint affected_files narrowing.")
    args = parser.parse_args(argv)

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    try:
        report = run(project_dir, mode=args.mode, base=args.base, branch=args.branch)
    except (OSError, subprocess.SubprocessError) as exc:
        report = {"status": "error", "message": str(exc)}
    print(json.dumps(report, indent=2))
    return 0  # advisory: never block the close


if __name__ == "__main__":
    sys.exit(main())
