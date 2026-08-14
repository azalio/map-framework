"""Guard against the `echo "$VAR" | jq` bug class (#425).

zsh's builtin ``echo`` interprets backslash escapes without ``-E``.  Piping a
captured JSON blob through it turns the ``\\n``/``\\t`` escapes inside JSON string
values into raw C0 control bytes, and ``jq`` aborts with

    control characters from U+0000 through U+001F must be escaped

Because shipped skill recipes capture the result in ``$(...)``, the failure is
swallowed and the variable silently lands EMPTY — downstream artifacts are then
written with empty fields and exit 0 (observed: an empty-bodied ``pr-draft.md``).

Repo-wide convention: ``printf '%s' "$VAR" | jq ...`` (and ``printf '%s\\n'``
when the consumer is a ``while read`` loop, so the final line is preserved).
This test is the gate that keeps the pattern from relanding.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# `echo "$VAR" |` feeding a JSON/text consumer.  Matches the quoted-variable form
# only — that is the one that carries a captured payload; bare `echo foo | grep`
# literals are not affected by escape interpretation.  `python3`/`node` consumers
# belong to the same class: mangled escapes there surface as a JSON decode error
# (or, worse, silently wrong values) instead of jq's loud abort.
BANNED_RE = re.compile(
    r"""echo\s+"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"\s*\|\s*(?:jq|while|python3?|node)\b"""
)

# Source of truth plus every generated tree, so a direct edit to a generated copy
# is caught even before `make check-render` notices the drift.
SCAN_PREFIXES = (
    "src/mapify_cli/templates_src/",
    "src/mapify_cli/templates/",
    ".claude/",
    ".codex/",
    ".agents/",
)

SCAN_SUFFIXES = (".jinja", ".md", ".sh", ".py", ".json")

# The guideline doc documents the bug class, so it necessarily quotes the banned
# form as a ❌ counter-example.  Exempt it by basename across every tree.
EXEMPT_BASENAMES = frozenset({"bash-guidelines.md", "bash-guidelines.md.jinja"})


def _scan_files() -> list[Path]:
    """Git-tracked shipped files only.

    ``git ls-files`` keeps scratch checkouts out of the scan — the worktree
    storage root lives under ``.claude/worktrees/`` and holds full copies of the
    repo at older revisions, which would otherwise re-report every historical
    offender forever.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", *SCAN_PREFIXES],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        REPO_ROOT / rel
        for rel in out.split("\0")
        if rel
        and rel.endswith(SCAN_SUFFIXES)
        and Path(rel).name not in EXEMPT_BASENAMES
    ]


def test_scan_roots_are_present() -> None:
    """Fail loudly if the gate is scanning nothing (moved/renamed trees)."""
    assert _scan_files(), "no files matched SCAN_ROOTS/SCAN_SUFFIXES — gate is inert"


def test_no_echo_pipe_into_jq_or_read_loop() -> None:
    """No shipped recipe may pipe a captured variable through `echo` (#425)."""
    offenders: list[str] = []
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if BANNED_RE.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "`echo \"$VAR\" | jq` mangles JSON escapes under zsh (#425).\n"
        "Use `printf '%s' \"$VAR\" | jq ...` "
        "(or `printf '%s\\n'` for a `while read` consumer).\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    ("line", "banned"),
    [
        ('STEP_ID=$(echo "$NEXT_STEP" | jq -r \'.step_id\')', True),
        ('NORM=$(echo "$OUT" | while IFS= read -r line; do', True),
        ('COUNT=$(echo "${ALL}" | jq length)', True),
        ('P=$(echo "$BUNDLE_JSON" | python3 -c "import sys,json; ...")', True),
        ("STEP_ID=$(printf '%s' \"$NEXT_STEP\" | jq -r '.step_id')", False),
        ("NORM=$(printf '%s\\n' \"$OUT\" | while IFS= read -r line; do", False),
        ('echo "done" | grep -q done', False),
    ],
)
def test_banned_pattern_detection(line: str, banned: bool) -> None:
    """The detector itself must catch the bug class and not the safe forms."""
    assert bool(BANNED_RE.search(line)) is banned
