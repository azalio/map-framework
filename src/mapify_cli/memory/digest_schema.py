"""Single-source schema contract for the MAP Framework memory subsystem.

This module is the ONE authority for:
  - Scratch JSONL field names (per-turn Stop hook records, LLM-free)
  - Finalized digest frontmatter field names (LLM-produced at finalize time)
  - Redaction patterns and the redact_text() function
  - Secret-path glob matching via redact_secret_path()
  - Control-character sanitization via sanitize_value()

All consumers (capture hook, finalize, recall, tests) import from here.
No I/O, no harness dependencies — pure stdlib (re, fnmatch) only.

INV-7 / Phase-A Contract-First rule: field names are defined ONCE here and
derived by all consumers; never hardcode field names at call sites.
"""

from __future__ import annotations

import fnmatch
import os
import re

# ---------------------------------------------------------------------------
# Scratch JSONL field names
# ---------------------------------------------------------------------------
# Per-turn Stop hook record (written LLM-free by the capture hook).
# IMPORTANT: decisions/findings must NOT appear here — they are LLM-inferred
# only at finalize time (spec:118).
SCRATCH_TURN_FIELDS: tuple[str, ...] = (
    "ts",
    "turn",
    "session_id",
    "files_touched",
    "prompt_ref",
    "event",
)

# Minimal "session ended" marker record.
SCRATCH_ENDED_FIELDS: tuple[str, ...] = (
    "event",
    "ts",
    "session_id",
)

# Event-type literals for the "event" field.
EVENT_TURN: str = "turn"
EVENT_ENDED: str = "ended"

# ---------------------------------------------------------------------------
# Finalized digest frontmatter field names (LLM-produced)
# ---------------------------------------------------------------------------
# decisions and findings are intentionally ONLY here, not in SCRATCH_* tuples.
DIGEST_FRONTMATTER_FIELDS: tuple[str, ...] = (
    "session_id",
    "branch",
    "date",
    "slug",
    "files_touched",
    "decisions",
    "findings",
    "ticket_refs",
)

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
# Token used as the replacement for all matched secrets.
REDACTION_TOKEN: str = "«redacted»"  # «redacted»

# Regex patterns keyed by name.
# Order matters for dict-iteration (Python 3.7+): sk-ant- must be tried
# before the generic sk- pattern so the longer variant wins.  Both are in
# the same "openai" key via alternation — the ant variant is the first
# branch in the alternation group.
REDACTION_PATTERNS: dict[str, str] = {
    # Anthropic/OpenAI API keys.
    # sk-ant-... first (longer, more specific), then generic sk-...
    "openai": r"sk-ant-[A-Za-z0-9-]+|sk-[A-Za-z0-9]{16,}",
    # GitHub tokens. The classic prefixes (ghp_/gho_/ghu_/ghs_/ghr_) AND the
    # fine-grained PAT format `github_pat_<...>` (which carries underscores in
    # its body and so is NOT matched by the gh[pousr]_ branch). The fine-grained
    # branch is listed first because `github_pat_` also starts with "gh".
    "github": r"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}",
    # High-entropy base64/hex blobs (≥40 chars).  The leading lookahead requires
    # at least one non-hex letter ([g-zG-Z]) or base64-only char (+/) somewhere
    # in the run, so a pure-hexadecimal run (a git SHA / content hash, either
    # case) is left intact — those are benign identifiers a dev memory digest
    # legitimately mentions, not secrets.  Real base64 tokens almost always
    # contain such a character.
    "base64_blob": r"(?=[A-Za-z0-9+/]*[g-zG-Z+/])[A-Za-z0-9+/]{40,}={0,2}",
    # AWS access key ID.
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
}


def redact_text(text: str) -> str:
    """Apply all REDACTION_PATTERNS to *text*, replacing matches with REDACTION_TOKEN.

    Redaction and sanitization are separate, composable steps.
    Call sanitize_value() independently if control-char stripping is also needed.

    Returns the redacted string (original returned unchanged if no patterns match).
    """
    for pattern in REDACTION_PATTERNS.values():
        text = re.sub(pattern, REDACTION_TOKEN, text)
    return text


# ---------------------------------------------------------------------------
# Secret-path redaction
# ---------------------------------------------------------------------------
SECRET_PATH_GLOBS: tuple[str, ...] = (
    "**/.env*",
    "**/*.pem",
    "**/*.key",
    "**/credentials*",
    "**/secrets*",
)

_REDACTED_PATH_TOKEN = "<redacted-secret-path>"


def redact_secret_path(path: str) -> str:
    """Return *_REDACTED_PATH_TOKEN* if *path* matches any SECRET_PATH_GLOBS.

    Matching is performed on BOTH the full path and the basename so that
    a bare filename like ".env" (no directory component) is caught in the
    same way as "config/.env.local" or "deploy/server.pem".

    Returns *path* unchanged when no glob matches.
    """
    basename = os.path.basename(path)
    for glob in SECRET_PATH_GLOBS:
        # Match against the full path (covers directory-qualified paths).
        if fnmatch.fnmatch(path, glob):
            return _REDACTED_PATH_TOKEN
        # Derive a basename-only pattern: take the part after the last "/"
        # in the glob (e.g. "**/*.pem" -> "*.pem", "**/.env*" -> ".env*").
        # This robustly handles bare filenames like "server.pem" or ".env".
        basename_glob = glob.rsplit("/", 1)[-1]
        if fnmatch.fnmatch(basename, basename_glob):
            return _REDACTED_PATH_TOKEN
    return path


# ---------------------------------------------------------------------------
# Control-character sanitization
# ---------------------------------------------------------------------------


def sanitize_value(text: str) -> str:
    """Remove every C0 control character (U+0000-U+001F) and U+007F from *text*.

    Python's ``json.dumps`` escapes these correctly for strict JSON output,
    but the bundle is then piped through bash command substitution
    (``BUNDLE=$(... map_step_runner ...)``) and consumed by ``jq``.  Bash
    expansion does not preserve byte-perfect roundtrip for embedded literal
    control characters in all locales, so jq receives a string with raw
    controls and rejects it with::

        jq: parse error: Invalid string: control characters from U+0000
        through U+001F must be escaped at line N, column M

    Stripping at source is the only robust fix.  We additionally normalise
    newline variants (``\\r\\n``, ``\\r``) into spaces to keep word
    boundaries when multi-line artifact bodies are flattened into a single
    bundle field.

    Implementation matches the proven reference at
    ``src/mapify_cli/templates/map/scripts/map_step_runner.py`` (function
    ``_sanitize_for_json``) — do not alter the ordering of the three steps.
    """
    # Step 1: normalise Windows / old-Mac newline variants first so that
    # the subsequent replace("\n", " ") catches them all.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Step 2: flatten newlines and tabs into spaces (preserves word boundaries).
    text = text.replace("\n", " ").replace("\t", " ")
    # Step 3: strip the entire C0 range U+0000-U+001F plus DEL U+007F.
    return re.sub(r"[\x00-\x1f\x7f]", "", text)
