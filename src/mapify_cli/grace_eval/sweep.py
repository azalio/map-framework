"""Contract sweep / stale-anchor audit for GRACE eval.

Pure, deterministic, no I/O, no subprocess, no clock/random.
Detects contradictions or stale contracts in annotated source text.

A GRACE contract anchor is a comment matching the pattern:

    # CONTRACT: <claim>
    # ANCHOR: <claim>

The sweep extracts these anchors and checks whether the immediately-following
code lines contradict the claim in a few heuristic ways (see ``_CONTRADICTION_PATTERNS``).
This is intentionally lightweight — the goal is to find obviously wrong
contracts quickly, not to verify semantic correctness.

For the ``lie`` fixture variant, stale/false anchors are injected
intentionally; the sweep should detect them.  For all other variants the
sweep acts as a quality gate: if contracts exist but are clearly wrong,
``SweepFinding`` objects with ``severity="critical"`` are returned.
"""

from __future__ import annotations

import re
from typing import Any

from mapify_cli.grace_eval.schema import VARIANT_NAMES, SweepFinding

# Lines we recognise as contract anchor comments.
_ANCHOR_RE = re.compile(
    r"^\s*#\s*(?:CONTRACT|ANCHOR):\s*(.+)$",
    re.IGNORECASE,
)

# Heuristic contradiction signals: (anchor_keyword, code_counter_pattern)
# If the anchor claim contains `anchor_keyword` and the following N lines
# match `code_counter_pattern`, we flag a likely contradiction.
_CONTRADICTION_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("never returns none", re.compile(r"\breturn\s+None\b")),
    ("always raises", re.compile(r"\breturn\b(?!\s+None)")),
    ("idempotent", re.compile(r"\bappend\s*\(|\.extend\s*\(")),
    ("no side effect", re.compile(r"\bself\.\w+\s*=")),
    ("thread.safe", re.compile(r"\bself\.\w+\s*\+?=|list\b|dict\b")),
    ("returns true", re.compile(r"\breturn\s+False\b")),
    ("returns false", re.compile(r"\breturn\s+True\b")),
)

_LOOKAHEAD_LINES = 8


def _extract_anchors(
    lines: list[str],
) -> list[tuple[int, str]]:
    """Return (line_number_1indexed, claim) pairs for each anchor found."""
    found = []
    for i, line in enumerate(lines, start=1):
        m = _ANCHOR_RE.match(line)
        if m:
            found.append((i, m.group(1).strip()))
    return found


def _check_claim_vs_lookahead(
    claim: str,
    lookahead: list[str],
) -> str | None:
    """Return a contradiction description or None if none detected."""
    claim_lower = claim.lower()
    for keyword, pattern in _CONTRADICTION_SIGNALS:
        if keyword in claim_lower:
            for line in lookahead:
                if pattern.search(line):
                    return (
                        f"anchor claims '{keyword}' but code contains '{line.strip()}'"
                    )
    return None


def sweep_source(
    source: str,
    *,
    variant: str,
    location_prefix: str = "",
) -> list[SweepFinding]:
    """Sweep a single source file's text for stale/contradictory contracts.

    ``variant`` is stored on each finding.  ``location_prefix`` is a
    human-readable path prefix prepended to the line-range in
    ``SweepFinding.location`` (e.g. ``"src/utils.py"``).
    Returns a (possibly empty) list of ``SweepFinding`` objects.
    """
    if variant not in VARIANT_NAMES:
        raise ValueError(
            f"sweep_source: variant must be one of {VARIANT_NAMES}, got {variant!r}"
        )
    lines = source.splitlines()
    anchors = _extract_anchors(lines)
    findings: list[SweepFinding] = []

    for lineno, claim in anchors:
        lookahead_start = lineno  # lines is 0-indexed, lineno is 1-indexed
        lookahead_end = min(lineno + _LOOKAHEAD_LINES, len(lines))
        lookahead = lines[lookahead_start:lookahead_end]
        contradiction = _check_claim_vs_lookahead(claim, lookahead)
        if contradiction:
            loc = f"{location_prefix}:L{lineno}" if location_prefix else f"L{lineno}"
            findings.append(
                SweepFinding(
                    severity="critical",
                    location=loc,
                    detail=f"Contract '{claim}' — {contradiction}",
                    variant=variant,
                )
            )

    return findings


def sweep_variant_sources(
    variant_sources: dict[str, Any],
    *,
    variant: str,
) -> list[SweepFinding]:
    """Sweep all source files in a variant dict.

    ``variant_sources`` maps ``location_prefix`` → ``source_text`` (str).
    Returns the union of findings across all files.
    """
    all_findings: list[SweepFinding] = []
    for location, source in variant_sources.items():
        if not isinstance(source, str):
            continue
        all_findings.extend(
            sweep_source(source, variant=variant, location_prefix=location)
        )
    return all_findings
