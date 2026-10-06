"""wayfind_runner.py — deterministic operations for /map-wayfind decision maps.

Self-contained, stdlib-only runner.  Owns EVERY mutation to
``.map/wayfind/<slug>/state.json`` (the canonical store) and regenerates the
human-readable views (``map.md``, ``tickets/T-00N.md``) after each mutation.

Design contract (mirrors the wider MAP conventions):
  * state.json is the single source of truth; map.md / tickets/*.md are derived
    projections carrying a DO-NOT-EDIT banner and are never parsed back.
  * The LLM never edits state.json by hand — it calls these operations and
    writes only prose resolution files under ``resolutions/``.
  * Every function returns a typed result dict: ``{"status": "success", ...}``
    or ``{"status": "error", "message": ...}``.  Nothing is raised through the
    public API; the CLI turns a non-success status into exit code 1.
  * Invariants (cycle-freedom, HITL gate, terminal-handoff condition, plus the
    opt-in one-non-research-resolve-per-session cap) live ABOVE persistence so a
    future non-local backend cannot bypass them.

The only cross-module dependency is a LAZY import of ``map_step_runner`` inside
:func:`emit_wayfind_handoff`, used solely to register the ``wayfind_handoff``
artifact-manifest stage on the current branch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# Vocabulary / constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

WAYFIND_TICKET_TYPES = frozenset({"research", "prototype", "grilling", "task"})
# Human-in-the-loop ticket types: resolving one requires a recorded verbatim
# human response (see record_human_input / resolve_ticket).
HITL_TYPES = frozenset({"prototype", "grilling"})
# Ticket statuses that count as "closed" for frontier / terminal computations.
TERMINAL_TICKET_STATUSES = frozenset({"resolved", "out_of_scope"})

# Max non-research ticket resolves allowed per session. 0 (the default) means
# unlimited — the one-per-session cap is an opt-in workflow discipline, not a
# hard gate. Set WAYFIND_MAX_NONRESEARCH_RESOLVES_PER_SESSION=N (N>=1) to
# re-enable a cap. The session ledger still records every resolve regardless,
# so the audit trail is preserved either way.
_ENV_MAX_NONRESEARCH_PER_SESSION = "WAYFIND_MAX_NONRESEARCH_RESOLVES_PER_SESSION"


def _max_nonresearch_per_session() -> int:
    """Resolve the per-session non-research cap; 0 = unlimited (default)."""
    try:
        n = int(os.environ.get(_ENV_MAX_NONRESEARCH_PER_SESSION, "0"))
    except (TypeError, ValueError):
        return 0
    return max(0, n)


_SLUG_RE = re.compile(r"^[a-z0-9-]{1,50}$")

_DO_NOT_EDIT_BANNER = (
    "<!-- DO NOT EDIT — regenerated from state.json by wayfind_runner.py. "
    "Manual edits will be overwritten. -->"
)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------


def _ok(**fields: Any) -> dict[str, Any]:
    return {"status": "success", **fields}


def _err(message: str, **fields: Any) -> dict[str, Any]:
    return {"status": "error", "message": message, **fields}


def _now() -> str:
    """Return an RFC3339 UTC timestamp (matches map_step_runner._utc_timestamp)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _oneline(text: str) -> str:
    """Collapse whitespace/newlines so untrusted prose stays on one Markdown line."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


# ---------------------------------------------------------------------------
# Path helpers (repo-level, resolved against cwd like .map/<branch>)
# ---------------------------------------------------------------------------


def _wayfind_root() -> Path:
    return Path(".map/wayfind")


def _map_dir(slug: str) -> Path:
    return _wayfind_root() / slug


def _state_path(slug: str) -> Path:
    return _map_dir(slug) / "state.json"


def _resolve_evidence_path(slug: str, rel: str) -> Path | None:
    """Resolve an evidence file (resolution / human-input) path under the map dir.

    Returns the resolved Path only when *rel* names a regular file contained in
    the map directory. Absolute paths, ``..`` escapes, directories, and missing
    files all return None — so a caller cannot use the provenance gate to read
    (or claim provenance over) a file outside its own map.
    """
    if not isinstance(rel, str) or not rel:
        return None
    # Reject absolute paths BEFORE constructing candidate. On POSIX,
    # Path(base) / "/absolute/path" evaluates to the absolute path, discarding
    # base — so an absolute path pointing inside the map dir would pass the
    # containment check below and be stored verbatim in state.json, breaking
    # all markdown link targets in map.md, handoff.md, and ticket files.
    if Path(rel).is_absolute():
        return None
    base = _map_dir(slug).resolve()
    candidate = (base / rel).resolve()
    if candidate != base and base not in candidate.parents:
        return None  # ../ escape left the map dir
    if not candidate.is_file():
        return None  # missing, or a directory
    return candidate


def _safe_read(path: Path) -> str:
    """Read a file's text, returning empty string on OSError."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# State load / save + derived views
# ---------------------------------------------------------------------------


def _load_state(slug: str) -> dict[str, Any] | None:
    path = _state_path(slug)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _save_state(state: dict[str, Any]) -> None:
    """Bump revision, atomically persist state.json, and regenerate all views."""
    slug = state["slug"]
    state["revision"] = int(state.get("revision", 0)) + 1
    map_dir = _map_dir(slug)
    map_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(slug)
    # Per-process-unique temp name so two writers never share (and corrupt) one
    # scratch file. NB: this makes the write atomic, not the read-modify-write —
    # see _revision_guard for the (best-effort, single-operator) staleness check.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    _render_views(state)


def _revision_guard(
    state: dict[str, Any], expected_revision: int | None
) -> dict[str, Any] | None:
    """Best-effort stale-write detection: reject a mutation whose caller read an
    older revision than the map now holds.

    This is a friction/audit aid for a single-operator, sequential tool — NOT a
    true compare-and-swap. It closes the common "I read, then something else
    advanced the map, then I wrote" window, but does not lock: two processes that
    both read the same revision before either writes can still lose an update.
    Concurrent multi-process writers to one map are out of scope by design (a map
    is charted and worked by one operator at a time)."""
    if expected_revision is None:
        return None
    current = int(state.get("revision", 0))
    if current != int(expected_revision):
        return _err(
            f"stale revision: expected {expected_revision}, map is at {current}. "
            "Re-read the map before mutating.",
            code="stale_revision",
            revision=current,
        )
    return None


def _mutation_guard(
    state: dict[str, Any], expected_revision: int | None
) -> dict[str, Any] | None:
    """Pre-mutation gate for ticket/fog operations.

    Rejects any mutation once the map is handed off (its handoff artifact is
    frozen, so a further edit would leave a discoverable handoff that omits the
    new state), then applies the optimistic staleness check. Not used by
    emit_wayfind_handoff, which may idempotently re-emit a handed-off map."""
    if state.get("status") == "handed_off":
        return _err(
            f"map {state.get('slug')!r} is already handed off; its handoff artifact "
            "is frozen. Start a follow-up map (or a new session) rather than mutating "
            "a handed-off map.",
            code="handed_off",
        )
    return _revision_guard(state, expected_revision)


# ---------------------------------------------------------------------------
# Id minting
# ---------------------------------------------------------------------------


def _next_ticket_id(state: dict[str, Any]) -> str:
    nums = [
        int(m.group(1))
        for tid in state.get("tickets", {})
        if (m := re.match(r"^T-(\d+)$", tid))
    ]
    return f"T-{(max(nums) + 1) if nums else 1:03d}"


def _next_fog_id(state: dict[str, Any]) -> str:
    nums = [
        int(m.group(1))
        for f in state.get("fog", [])
        if (m := re.match(r"^F-(\d+)$", str(f.get("id", ""))))
    ]
    return f"F-{(max(nums) + 1) if nums else 1}"


# ---------------------------------------------------------------------------
# Invariant helpers
# ---------------------------------------------------------------------------


def _ticket_blocked(state: dict[str, Any], ticket: dict[str, Any]) -> bool:
    """True if any blocker is not yet terminal (resolved / out_of_scope)."""
    tickets = state.get("tickets", {})
    for bid in ticket.get("blocked_by", []):
        blocker = tickets.get(bid)
        if blocker is None or blocker.get("status") not in TERMINAL_TICKET_STATUSES:
            return True
    return False


def _detect_cycle(graph: dict[str, list[str]]) -> bool:
    """Return True if the directed graph (node -> blockers) contains a cycle."""
    white, gray, black = 0, 1, 2
    color: dict[str, int] = {node: white for node in graph}

    def visit(node: str) -> bool:
        color[node] = gray
        for nxt in graph.get(node, []):
            if nxt not in color:
                continue
            if color[nxt] == gray:
                return True
            if color[nxt] == white and visit(nxt):
                return True
        color[node] = black
        return False

    return any(color[node] == white and visit(node) for node in list(graph))


def _blocking_graph(
    state: dict[str, Any], override: tuple[str, list[str]] | None = None
) -> dict[str, list[str]]:
    """Build a {ticket_id: blocked_by[]} graph, optionally overriding one node."""
    graph = {
        tid: list(t.get("blocked_by", [])) for tid, t in state.get("tickets", {}).items()
    }
    if override is not None:
        tid, blockers = override
        graph[tid] = list(blockers)
    return graph


def _active_claims(state: dict[str, Any]) -> list[str]:
    """Ticket ids that are claimed and not yet terminal."""
    return [
        tid
        for tid, t in state.get("tickets", {}).items()
        if t.get("claimed_by") and t.get("status") not in TERMINAL_TICKET_STATUSES
    ]


def _open_fog(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in state.get("fog", []) if f.get("status") == "open"]


def _is_terminal(state: dict[str, Any]) -> bool:
    """Terminal (handoff-eligible) condition.

    Fog empty AND no active claims AND at least one ticket AND every ticket in
    {resolved, out_of_scope}.  A naive ``len(frontier) == 0`` would wrongly fire
    on a map whose tickets are merely claimed or blocked.
    """
    tickets = state.get("tickets", {})
    if not tickets:
        return False
    if any(t.get("status") not in TERMINAL_TICKET_STATUSES for t in tickets.values()):
        return False
    if _open_fog(state):
        return False
    return not _active_claims(state)


def _recompute_status(state: dict[str, Any]) -> None:
    """Keep status accurate on every mutation (never mutated by a read)."""
    if state.get("status") == "handed_off":
        return
    if _is_terminal(state):
        state["status"] = "exhausted"
    elif state.get("status") == "exhausted":
        # A previously-terminal map became non-terminal again (e.g. new fog).
        state["status"] = "active"


def _ensure_session(state: dict[str, Any], session: str) -> dict[str, Any]:
    sessions = state.setdefault("sessions", {})
    if session not in sessions:
        sessions[session] = {
            "started_at": _now(),
            "non_research_resolved": 0,
            "claimed": [],
        }
    return sessions[session]


def _frontier_tickets(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Open, unblocked, unclaimed tickets in creation (id) order."""
    frontier: list[dict[str, Any]] = []
    for tid in sorted(state.get("tickets", {})):
        ticket = state["tickets"][tid]
        if ticket.get("status") != "open":
            continue
        if ticket.get("claimed_by"):
            continue
        if _ticket_blocked(state, ticket):
            continue
        frontier.append({"ticket_id": tid, **ticket})
    return frontier


def _mint_ticket(
    state: dict[str, Any],
    title: str,
    ticket_type: str,
    question: str,
    blocked_by: list[str],
    from_fog: str | None,
) -> str:
    ticket_id = _next_ticket_id(state)
    state.setdefault("tickets", {})[ticket_id] = {
        "title": _oneline(title),
        "type": ticket_type,
        "question": _oneline(question),
        "status": "open",
        "blocked_by": list(blocked_by),
        "claimed_by": None,
        "claimed_at": None,
        "created_at": _now(),
        "resolved_at": None,
        "human_input_path": None,
        "resolution": None,
        "from_fog": from_fog or None,
    }
    if ticket_type == "research":
        _ensure_research(state["tickets"][ticket_id])
    return ticket_id


# ---------------------------------------------------------------------------
# View rendering
# ---------------------------------------------------------------------------


def _ticket_badge(state: dict[str, Any], ticket: dict[str, Any]) -> str:
    if (
        ticket.get("status") == "open"
        and ticket.get("claimed_by")
        and ticket.get("type") in HITL_TYPES
        and not ticket.get("human_input_path")
    ):
        return " — 🔴 AWAITING HUMAN"
    return ""


def _render_map_md(state: dict[str, Any]) -> str:
    tickets = state.get("tickets", {})
    lines: list[str] = [
        _DO_NOT_EDIT_BANNER,
        f"# Wayfinding Map: {_oneline(state.get('title', state['slug']))}",
        "",
        f"- **Slug:** `{state['slug']}`",
        f"- **Status:** {state.get('status', 'active')}",
        f"- **Map ID:** `{state.get('map_id', '')}`",
        f"- **Revision:** {state.get('revision', 0)}",
        "",
        "## Destination",
        "",
        _oneline(state.get("destination", "")) or "_Not stated._",
        "",
        "## Notes",
        "",
        _oneline(state.get("notes", "")) or "_None._",
        "",
        "## Decisions so far",
        "",
    ]

    resolved = [
        (tid, tickets[tid])
        for tid in sorted(tickets)
        if tickets[tid].get("status") == "resolved"
    ]
    if resolved:
        for tid, ticket in resolved:
            resolution = ticket.get("resolution") or {}
            gist = _oneline(resolution.get("gist", ""))
            path = resolution.get("path", "")
            link = f"  ([resolution]({path}))" if path else ""
            lines.append(f"- **{tid}** {_oneline(ticket.get('title', ''))} — {gist}{link}")
    else:
        lines.append("_None yet._")

    lines += ["", "## Frontier (resolve next, one non-research at a time)", ""]
    frontier = _frontier_tickets(state)
    if frontier:
        for ticket in frontier:
            lines.append(
                f"- **{ticket['ticket_id']}** [{ticket['type']}] "
                f"{_oneline(ticket.get('title', ''))} — {_oneline(ticket.get('question', ''))}"
            )
    else:
        lines.append("_Empty._")

    lines += ["", "## Blocked / claimed", ""]
    pending: list[str] = []
    for tid in sorted(tickets):
        ticket = tickets[tid]
        if ticket.get("status") != "open":
            continue
        blocked = _ticket_blocked(state, ticket)
        claimed = bool(ticket.get("claimed_by"))
        if not blocked and not claimed:
            continue
        detail_parts: list[str] = []
        if blocked:
            detail_parts.append(
                "blocked by " + ", ".join(ticket.get("blocked_by", []))
            )
        if claimed:
            detail_parts.append(f"claimed by `{ticket['claimed_by']}`")
        detail = "; ".join(detail_parts)
        badge = _ticket_badge(state, ticket)
        pending.append(
            f"- **{tid}** [{ticket['type']}] {_oneline(ticket.get('title', ''))}"
            f" — {detail}{badge}"
        )
    lines += pending if pending else ["_None._"]

    lines += ["", "## Fog of war (too vague to ticket yet)", ""]
    open_fog = _open_fog(state)
    if open_fog:
        for fog in open_fog:
            lines.append(f"- **{fog.get('id')}** {_oneline(fog.get('text', ''))}")
    else:
        lines.append("_None._")

    lines += ["", "## Out of scope", ""]
    out_of_scope = state.get("out_of_scope", [])
    if out_of_scope:
        for entry in out_of_scope:
            ref = entry.get("ticket_id") or entry.get("fog_id") or ""
            ref_text = f" (from {ref})" if ref else ""
            lines.append(
                f"- {_oneline(entry.get('gist', ''))} — "
                f"{_oneline(entry.get('reason', ''))}{ref_text}"
            )
    else:
        lines.append("_None._")

    lines.append("")
    return "\n".join(lines)


def _render_ticket_md(state: dict[str, Any], ticket_id: str) -> str:
    ticket = state["tickets"][ticket_id]
    resolution = ticket.get("resolution") or {}
    lines = [
        _DO_NOT_EDIT_BANNER,
        f"# {ticket_id}: {_oneline(ticket.get('title', ''))}",
        "",
        f"- **Type:** {ticket.get('type')}",
        f"- **Status:** {ticket.get('status')}",
        f"- **Blocked by:** {', '.join(ticket.get('blocked_by', [])) or '—'}",
        f"- **Claimed by:** {ticket.get('claimed_by') or '—'}",
        f"- **From fog:** {ticket.get('from_fog') or '—'}",
        f"- **Created:** {ticket.get('created_at')}",
        f"- **Resolved:** {ticket.get('resolved_at') or '—'}",
        "",
        "## Question",
        "",
        _oneline(ticket.get("question", "")),
        "",
    ]
    if resolution:
        lines += [
            "## Resolution",
            "",
            _oneline(resolution.get("gist", "")),
            "",
            f"See `{resolution.get('path', '')}`.",
            "",
        ]
    if ticket.get("human_input_path"):
        lines += [f"Human input recorded at `{ticket['human_input_path']}`.", ""]
    return "\n".join(lines)


def _render_views(state: dict[str, Any]) -> None:
    map_dir = _map_dir(state["slug"])
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "map.md").write_text(_render_map_md(state), encoding="utf-8")
    tickets_dir = map_dir / "tickets"
    tickets_dir.mkdir(parents=True, exist_ok=True)
    for ticket_id in state.get("tickets", {}):
        (tickets_dir / f"{ticket_id}.md").write_text(
            _render_ticket_md(state, ticket_id), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Research protocol — durable ticket-local ledger, one coordinator
# ---------------------------------------------------------------------------


class ResearchBrief(TypedDict):
    protocol_version: Literal[1]
    ticket_id: str
    question: str
    constraints: list[str]
    settling_criteria: list[str]
    dependency_bindings: dict[str, str]
    verification_target: dict[str, str] | None


class ResearchReport(TypedDict):
    protocol_version: Literal[1]
    ticket_id: str
    attempt_id: str
    brief_sha256: str
    answer: str
    claims: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    decisive_assumptions: list[str]
    falsification_conditions: list[str]
    uncertainty: list[str]


class ResearchAssessment(TypedDict):
    protocol_version: Literal[1]
    ticket_id: str
    assessment_id: str
    attempt_bindings: list[dict[str, str]]
    verdict: Literal["sufficient", "needs_verification", "blocked"]
    gist: str
    resolution_path: str
    resolution_sha256: str
    material_disputes: list[dict[str, Any]]
    remaining_uncertainty: list[str]
    no_further_verification_rationale: str


class ResearchInputError(ValueError):
    """Invalid or changed external evidence; never a successful verdict."""

    def __init__(self, message: str, code: str = "invalid_research_evidence") -> None:
        super().__init__(message)
        self.code = code


def _research_api(function: Any) -> Any:
    @wraps(function)
    def invoke(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)
        except (ResearchInputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            return _err(f"research evidence rejected: {exc}", code=exc.code if isinstance(exc, ResearchInputError) else "invalid_research_evidence")
    return invoke


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ResearchInputError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: Any, nonempty: bool = False) -> bool:
    return isinstance(value, list) and (bool(value) or not nonempty) and all(_text(v) for v in value)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _research_file(slug: str, ticket_id: str, rel: str) -> Path:
    _require(isinstance(rel, str), "artifact path must be a string")
    path = _resolve_evidence_path(slug, rel)
    _require(path is not None, "artifact must be a contained regular file")
    assert path is not None
    parts = Path(rel).parts
    _require(".." not in parts and len(parts) >= 3 and parts[:2] == ("research", ticket_id), "artifact belongs to another ticket")
    _require(path.is_relative_to(_map_dir(slug).resolve()) and path.relative_to(_map_dir(slug).resolve()).parts[:2] == ("research", ticket_id), "cross-ticket symlink")
    return path


def _source_file(rel: str) -> Path:
    _require(isinstance(rel, str) and not Path(rel).is_absolute(), "source must be repo-relative")
    parts = Path(rel).parts
    _require(".." not in parts and not any(p.startswith(".env") or any(s in p.lower() for s in ("secret", "credential", "token", "private-key")) for p in parts), "secret or escaping source path")
    root = Path.cwd().resolve()
    path = (root / rel).resolve()
    _require(path.is_relative_to(root) and path.is_file(), "source must be contained in repo")
    _require(not any(p.startswith(".env") or any(s in p.lower() for s in ("secret", "credential", "token", "private-key")) for p in path.relative_to(root).parts), "resolved source path names secret material")
    _require(not path.is_relative_to((root / ".map").resolve()), "map-generated artifacts are not local sources")
    return path


def _artifact_json(slug: str, ticket_id: str, rel: str) -> tuple[dict[str, Any], str]:
    path = _research_file(slug, ticket_id, rel)
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    _require(isinstance(data, dict) and type(data.get("protocol_version")) is int and data["protocol_version"] == 1, "unsupported research schema")
    _require(data.get("ticket_id") == ticket_id, "foreign ticket artifact")
    return data, hashlib.sha256(raw).hexdigest()


def _research_resolution_gate(state: dict[str, Any], ticket_id: str, gist: str, resolution_path: str) -> dict[str, Any] | None:
    research = state["tickets"][ticket_id].get("research") or {}
    accepted = next((a for a in research.get("assessments", []) if a["assessment_id"] == research.get("accepted_assessment_id")), None)
    if accepted is None:
        return _err("source-backed sufficient assessment required", code="research_assessment_required")
    try:
        data, digest = _artifact_json(state["slug"], ticket_id, accepted["path"])
        _require(digest == accepted["sha256"], "accepted assessment changed")
        _validate_assessment(state, ticket_id, data)
        _require(data["verdict"] == "sufficient" and data["gist"] == _oneline(gist) and data["resolution_path"] == resolution_path, "resolution does not match sufficient assessment")
    except (ResearchInputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _err(f"research reassessment required: {exc}", code="research_reassessment_required")
    return None


def _ensure_research(ticket: dict[str, Any]) -> dict[str, Any]:
    return ticket.setdefault("research", {"protocol_version": 1, "mode": "independent", "mode_reason": "Ambiguous until classified by coordinator", "budget_limit": 4, "extensions": [], "attempts": [], "assessments": [], "accepted_assessment_id": None})


def _dependency_bindings(state: dict[str, Any], ticket: dict[str, Any]) -> dict[str, str]:
    bindings = {}
    for tid in ticket.get("blocked_by", []):
        dependency = state["tickets"][tid]
        resolution = dependency.get("resolution") or {}
        path = _resolve_evidence_path(state["slug"], resolution.get("path", ""))
        bindings[tid] = _json_digest({"status": dependency.get("status"), "resolution": resolution, "content": _digest(path) if path else None, "accepted_assessment_id": (dependency.get("research") or {}).get("accepted_assessment_id"), "correction": (dependency.get("research") or {}).get("correction")})
    return bindings


@_research_api
def research_context(slug: str, ticket_id: str) -> dict[str, Any]:
    state = _load_state(slug)
    if state is None or ticket_id not in state.get("tickets", {}):
        return _err("map or ticket not found", code="not_found")
    ticket = state["tickets"][ticket_id]
    research = ticket.get("research") or {}
    return _ok(context={"protocol_version": 1, "ticket_id": ticket_id, "question": ticket["question"], "dependency_bindings": _dependency_bindings(state, ticket), "mode": research.get("mode"), "budget_limit": research.get("budget_limit", 4), "spent_attempts": len(research.get("attempts", [])), "correction": research.get("correction")})


@_research_api
def research_artifact_hash(slug: str, path: str, scope: str = "map") -> dict[str, Any]:
    if scope == "local_code":
        source = _source_file(path)
    else:
        source = _resolve_evidence_path(slug, path)
        _require(source is not None, "missing or escaping artifact")
        assert source is not None
    return _ok(path=path, sha256=_digest(source))


def _research_owner(slug: str, ticket_id: str, session: str, expected_revision: int | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = _load_state(slug)
    _require(state is not None and ticket_id in state.get("tickets", {}), "map or ticket not found")
    assert state is not None
    guard = _revision_guard(state, expected_revision)
    if guard:
        raise ResearchInputError(guard["message"], guard["code"])
    ticket = state["tickets"][ticket_id]
    _require(ticket.get("type") == "research", "only research tickets have research ledgers")
    correction = (ticket.get("research") or {}).get("correction")
    if correction and correction.get("active"):
        _require(bool(session) and correction.get("owner_session") == session, "not correction owner")
    else:
        _require(ticket.get("status") == "open" and state.get("status") != "handed_off", "research ticket is not open")
        _require(bool(session) and ticket.get("claimed_by") == session, "not ticket owner")
    return state, ticket, _ensure_research(ticket)


@_research_api
def configure_research(slug: str, ticket_id: str, session: str, mode: str, reason: str, expected_revision: int | None = None) -> dict[str, Any]:
    state, _ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    _require(mode in {"direct", "independent"} and _text(reason), "mode and route rationale required")
    _require(not research["attempts"] or mode == research["mode"] or (research["mode"] == "direct" and mode == "independent"), "research mode is frozen")
    if research["mode"] == mode and research["mode_reason"] == reason:
        return _ok(created=False, mode=mode)
    research.update(mode=mode, mode_reason=reason)
    _save_state(state)
    return _ok(mode=mode, revision=state["revision"])


@_research_api
def reserve_research_attempt(slug: str, ticket_id: str, session: str, request_id: str, phase: str, investigator_id: str, brief_path: str, expected_revision: int | None = None) -> dict[str, Any]:
    state, ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    _require(_text(request_id) and _text(investigator_id) and phase in {"initial", "verification"}, "invalid reservation identity or phase")
    data, digest = _artifact_json(slug, ticket_id, brief_path)
    _require(data.get("question") == ticket["question"] and data.get("dependency_bindings") == _dependency_bindings(state, ticket), "stale brief question or dependencies")
    _require(_strings(data.get("constraints")) and _strings(data.get("settling_criteria"), True), "brief requires constraints and settling criteria")
    target = data.get("verification_target")
    _require((phase == "initial" and target is None) or (phase == "verification" and isinstance(target, dict) and all(_text(target.get(k)) for k in ("dispute_id", "claim", "falsification_condition"))), "verification requires a specific falsifiable target")
    payload = {"phase": phase, "investigator_id": investigator_id, "brief_path": brief_path, "brief_sha256": digest}
    for attempt in research["attempts"]:
        if attempt["request_id"] == request_id:
            if any(attempt[k] != v for k, v in payload.items()):
                return _err("request reused with different payload", code="conflicting_replay")
            return _ok(created=False, attempt_id=attempt["attempt_id"], attempt=attempt)
    if len(research["attempts"]) >= research["budget_limit"]:
        return _err("research budget exhausted; obtain bounded human authorization", code="research_budget_exhausted")
    attempt = {"attempt_id": uuid.uuid4().hex, "request_id": request_id, "generation": research.get("evidence_generation", 0), "session": session, "reserved_at": _now(), "outcome": "reserved", "context": {"question": data["question"], "constraints": data["constraints"], "settling_criteria": data["settling_criteria"], "dependency_bindings": data["dependency_bindings"], "verification_target": target}, **payload}
    research["attempts"].append(attempt)
    _save_state(state)
    return _ok(created=True, attempt_id=attempt["attempt_id"], attempt=attempt, revision=state["revision"])


def _validate_report(slug: str, ticket_id: str, attempt: dict[str, Any], data: dict[str, Any]) -> None:
    _require(data.get("attempt_id") == attempt["attempt_id"] and data.get("brief_sha256") == attempt["brief_sha256"], "report does not bind original dispatch")
    _require(_text(data.get("answer")), "report requires answer")
    for field in ("decisive_assumptions", "falsification_conditions", "uncertainty"):
        _require(_strings(data.get(field)), f"invalid report {field}")
    sources = data.get("sources")
    _require(isinstance(sources, list) and bool(sources), "report needs sources")
    assert isinstance(sources, list)
    ids = set()
    observed = set()
    for source in sources:
        _require(isinstance(source, dict) and _text(source.get("id")) and source["id"] not in ids, "invalid or duplicate source")
        ids.add(source["id"])
        kind = source.get("kind")
        _require(isinstance(kind, str), "source kind must be string")
        if kind in ("local_code", "experiment"):
            source_path = source.get("path")
            _require(isinstance(source_path, str), "source path required")
            assert isinstance(source_path, str)
            path = _source_file(source_path) if kind == "local_code" else _research_file(slug, ticket_id, source_path)
            _require(_digest(path) == source.get("sha256"), "source content changed")
            observed.add(source["id"])
        elif kind == "documentation":
            _require(all(_text(source.get(k)) for k in ("url", "version", "observed_at", "freshness_limit")) and source["url"].startswith(("https://", "http://")), "documentation provenance required")
            observed.add(source["id"])
        else:
            _require(kind == "inference" and _text(source.get("rationale")), "unknown source kind or missing inference rationale")
    claims = data.get("claims")
    _require(isinstance(claims, list) and bool(claims), "report requires claims")
    assert isinstance(claims, list)
    claim_ids = set()
    for claim in claims:
        _require(isinstance(claim, dict) and _text(claim.get("id")) and claim["id"] not in claim_ids and _text(claim.get("text")) and _strings(claim.get("evidence"), True), "invalid claim")
        claim_ids.add(claim["id"])
        _require(set(claim["evidence"]).issubset(ids), "claim cites unknown evidence")
    _require(any(set(claim["evidence"]) & observed for claim in claims), "inference alone cannot support answer")


@_research_api
def record_research_attempt(slug: str, ticket_id: str, session: str, attempt_id: str, outcome: str, result_path: str | None = None, reason: str | None = None, expected_revision: int | None = None, dispatch_id: str | None = None) -> dict[str, Any]:
    state, _ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    attempt = next((a for a in research["attempts"] if a["attempt_id"] == attempt_id), None)
    _require(attempt is not None, "unknown attempt")
    assert attempt is not None
    _require(outcome in {"completed", "failed", "unknown", "cancelled"}, "invalid attempt outcome")
    payload: dict[str, Any] = {"outcome": outcome}
    if outcome == "completed":
        _require(result_path is not None, "completed attempt needs result")
        assert result_path is not None
        data, digest = _artifact_json(slug, ticket_id, result_path)
        _validate_report(slug, ticket_id, attempt, data)
        _require(_digest(_research_file(slug, ticket_id, attempt["brief_path"])) == attempt["brief_sha256"], "brief changed")
        payload.update(report_path=result_path, report_sha256=digest)
    else:
        _require(_text(reason) and result_path is None, "negative outcome needs reason, not result")
        payload["reason"] = reason
    if dispatch_id is not None:
        _require(_text(dispatch_id), "dispatch id must be nonempty")
        payload["dispatch_id"] = dispatch_id
    if attempt["outcome"] != "reserved":
        if all(attempt.get(k) == v for k, v in payload.items()):
            return _ok(created=False, attempt_id=attempt_id, outcome=outcome)
        if not (attempt["outcome"] == "unknown" and outcome in {"completed", "failed", "cancelled"}):
            return _err("terminal attempt result conflicts", code="conflicting_replay")
    attempt.update(payload, recorded_at=_now())
    _save_state(state)
    return _ok(created=True, attempt_id=attempt_id, outcome=outcome, revision=state["revision"])


@_research_api
def extend_research_budget(slug: str, ticket_id: str, session: str, extension_id: str, additional_attempts: int, approval_path: str, reason: str, expected_revision: int | None = None) -> dict[str, Any]:
    state, _ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    _require(type(additional_attempts) is int and additional_attempts > 0 and _text(extension_id) and _text(reason), "finite positive integer extension and reason required")
    approval, digest = _artifact_json(slug, ticket_id, approval_path)
    _require(_text(approval.get("human_approval")), "actual verbatim human approval required")
    for extension in research["extensions"]:
        if extension["approval_sha256"] == digest or extension["extension_id"] == extension_id:
            if extension["approval_sha256"] == digest and extension["additional_attempts"] == additional_attempts and extension["reason"] == reason:
                return _ok(created=False, extension_id=extension["extension_id"], budget_limit=research["budget_limit"])
            return _err("authorization conflicts", code="conflicting_replay")
    _require(approval.get("extension_id") == extension_id and type(approval.get("additional_attempts")) is int and approval["additional_attempts"] == additional_attempts and type(approval.get("current_budget_limit")) is int and approval["current_budget_limit"] == research["budget_limit"] and approval.get("reason") == reason, "approval must bind exact ticket, extension, increment, budget and reason")
    authorization = _json_digest({k: approval[k] for k in ("ticket_id", "additional_attempts", "current_budget_limit", "human_approval", "reason")})
    _require(not any(e["authorization"] == authorization for e in research["extensions"]), "authorization already consumed")
    research["extensions"].append({"extension_id": extension_id, "additional_attempts": additional_attempts, "approval_path": approval_path, "approval_sha256": digest, "authorization": authorization, "reason": reason, "session": session, "recorded_at": _now()})
    research["budget_limit"] += additional_attempts
    _save_state(state)
    return _ok(created=True, extension_id=extension_id, budget_limit=research["budget_limit"], revision=state["revision"])


def _current_report(state: dict[str, Any], ticket_id: str, attempt: dict[str, Any]) -> dict[str, Any]:
    slug = state["slug"]
    data, digest = _artifact_json(slug, ticket_id, attempt["report_path"])
    _require(digest == attempt["report_sha256"], "registered report changed")
    brief, brief_digest = _artifact_json(slug, ticket_id, attempt["brief_path"])
    ticket = state["tickets"][ticket_id]
    _require(brief_digest == attempt["brief_sha256"] and brief["question"] == ticket["question"] and brief["dependency_bindings"] == _dependency_bindings(state, ticket), "brief or dependency evidence stale")
    _validate_report(slug, ticket_id, attempt, data)
    return data


def _validate_assessment(state: dict[str, Any], ticket_id: str, data: dict[str, Any]) -> None:
    research = state["tickets"][ticket_id]["research"]
    _require(_text(data.get("assessment_id")) and data.get("verdict") in ("sufficient", "needs_verification", "blocked"), "invalid assessment identity or verdict")
    _require(_strings(data.get("remaining_uncertainty")) and isinstance(data.get("no_further_verification_rationale"), str), "assessment requires uncertainty and rationale")
    bindings = data.get("attempt_bindings")
    _require(isinstance(bindings, list), "assessment bindings must be list")
    assert isinstance(bindings, list)
    generation = research.get("evidence_generation", 0)
    current_attempts = [a for a in research["attempts"] if a.get("generation", 0) == generation]
    if not current_attempts:
        current_attempts = [a for a in research["attempts"] if a.get("generation", 0) == research.get("accepted_generation", 0)]
    completed = {a["attempt_id"]: a for a in current_attempts if a["outcome"] == "completed"}
    seen = set()
    for binding in bindings:
        _require(isinstance(binding, dict) and _text(binding.get("attempt_id")) and binding.get("attempt_id") in completed and binding["attempt_id"] not in seen, "invalid or duplicate assessment binding")
        attempt = completed[binding["attempt_id"]]
        _require(binding.get("report_sha256") == attempt["report_sha256"], "report hash mismatch")
        _current_report(state, ticket_id, attempt)
        seen.add(attempt["attempt_id"])
    _require(seen == set(completed), "assessment must cover every completed report")
    disputes = data.get("material_disputes")
    _require(isinstance(disputes, list), "material disputes must be list")
    assert isinstance(disputes, list)
    dispute_ids = set()
    for dispute in disputes:
        _require(isinstance(dispute, dict) and all(_text(dispute.get(k)) for k in ("id", "claim", "falsification_condition", "rationale")) and dispute["id"] not in dispute_ids, "invalid dispute")
        dispute_ids.add(dispute["id"])
        _require(dispute.get("disposition") in ("unresolved", "verified", "non_material") and _strings(dispute.get("verification_attempt_ids")), "invalid dispute disposition")
        if dispute["disposition"] == "verified":
            _require(bool(dispute["verification_attempt_ids"]), "verified dispute needs targeted check")
            for aid in dispute["verification_attempt_ids"]:
                attempt = completed.get(aid)
                target = (attempt or {}).get("context", {}).get("verification_target") or {}
                _require(attempt is not None and attempt["phase"] == "verification" and target == {"dispute_id": dispute["id"], "claim": dispute["claim"], "falsification_condition": dispute["falsification_condition"]}, "unrelated verification cannot settle dispute")
        if data["verdict"] == "sufficient":
            _require(dispute["disposition"] != "unresolved", "material dispute remains unresolved")
    # Intent: unresolved outcomes may be recorded without pretending a failed pair is sufficient.
    if data["verdict"] != "sufficient":
        return
    _require(not any(a["outcome"] in {"reserved", "unknown"} for a in research["attempts"]), "in-flight or unknown work cannot resolve")
    initials = [a for a in completed.values() if a["phase"] == "initial"]
    _require(bool(initials), "completed source-backed initial report required")
    if research["mode"] == "independent":
        _require(len({a["investigator_id"] for a in initials}) >= 2, "two completed independent initials required")
        _require(len({_json_digest(a["context"]) for a in initials}) == 1, "independent initials must share neutral context")
    _require(_text(data.get("no_further_verification_rationale")), "sufficient assessment needs stopping rationale")
    _require(_text(data.get("gist")) and data["gist"] == _oneline(data["gist"]), "assessment gist must be normalized")
    resolution = _resolve_evidence_path(state["slug"], data.get("resolution_path", ""))
    _require(resolution is not None, "missing assessment resolution")
    assert resolution is not None
    _require(resolution.read_bytes().strip() != b"" and _digest(resolution) == data.get("resolution_sha256"), "resolution content mismatch")


@_research_api
def record_research_assessment(slug: str, ticket_id: str, session: str, assessment_path: str, expected_revision: int | None = None) -> dict[str, Any]:
    state, _ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    data, digest = _artifact_json(slug, ticket_id, assessment_path)
    for existing in research["assessments"]:
        if existing["assessment_id"] == data.get("assessment_id"):
            if existing["sha256"] != digest or existing["path"] != assessment_path:
                return _err("assessment replay conflicts", code="conflicting_replay")
            _validate_assessment(state, ticket_id, data)
            return _ok(created=False, assessment_id=existing["assessment_id"], verdict=data["verdict"])
    _validate_assessment(state, ticket_id, data)
    research["assessments"].append({"assessment_id": data["assessment_id"], "path": assessment_path, "sha256": digest, "verdict": data["verdict"], "recorded_at": _now(), "session": session})
    research["accepted_assessment_id"] = data["assessment_id"] if data["verdict"] == "sufficient" else None
    if data["verdict"] == "sufficient":
        bound_ids = {b["attempt_id"] for b in data["attempt_bindings"]}
        research["accepted_generation"] = next(a.get("generation", 0) for a in research["attempts"] if a["attempt_id"] in bound_ids)
    _save_state(state)
    return _ok(created=True, assessment_id=data["assessment_id"], verdict=data["verdict"], revision=state["revision"])


@_research_api
def begin_research_correction(slug: str, ticket_id: str, session: str, reason: str, expected_revision: int | None = None) -> dict[str, Any]:
    state = _load_state(slug)
    _require(state is not None and ticket_id in state.get("tickets", {}), "map or ticket missing")
    assert state is not None
    guard = _revision_guard(state, expected_revision)
    if guard:
        return guard
    ticket = state["tickets"][ticket_id]
    _require(ticket.get("status") == "resolved" and bool(ticket.get("research")) and _text(session) and _text(reason), "managed resolved research, owner and reason required")
    research = ticket["research"]
    correction = research.get("correction")
    if correction and correction.get("active"):
        _require(correction["owner_session"] == session, "not correction owner")
        return _ok(created=False, correction=correction)
    correction = {"correction_id": uuid.uuid4().hex, "owner_session": session, "reason": reason, "active": True, "started_at": _now(), "prior_resolution": dict(ticket["resolution"]), "prior_accepted_assessment_id": research["accepted_assessment_id"]}
    research.setdefault("correction_history", []).append(correction)
    research["correction"] = correction
    research["evidence_generation"] = research.get("evidence_generation", 0) + 1
    _save_state(state)
    return _ok(created=True, correction=correction, revision=state["revision"])


@_research_api
def release_research_correction(slug: str, ticket_id: str, session: str, expected_revision: int | None = None) -> dict[str, Any]:
    state, _ticket, research = _research_owner(slug, ticket_id, session, expected_revision)
    correction = research.get("correction")
    _require(correction is not None and correction.get("active"), "no active correction")
    assert correction is not None
    correction["owner_session"] = None
    _save_state(state)
    return _ok(correction=correction, revision=state["revision"])


@_research_api
def claim_research_correction(slug: str, ticket_id: str, session: str, expected_revision: int | None = None) -> dict[str, Any]:
    state = _load_state(slug)
    _require(state is not None and ticket_id in state.get("tickets", {}), "map or ticket missing")
    assert state is not None
    guard = _revision_guard(state, expected_revision)
    if guard:
        return guard
    correction = (state["tickets"][ticket_id].get("research") or {}).get("correction")
    _require(correction is not None and correction.get("active") and correction.get("owner_session") is None and _text(session), "correction must be explicitly released before reclaim")
    assert correction is not None
    correction["owner_session"] = session
    _save_state(state)
    return _ok(correction=correction, revision=state["revision"])


# ---------------------------------------------------------------------------
# Operations — map lifecycle
# ---------------------------------------------------------------------------


def create_wayfind_map(
    slug: str,
    title: str,
    destination: str,
    notes: str = "",
    fog_json: str = "[]",
) -> dict[str, Any]:
    """Create a new decision map at .map/wayfind/<slug>/."""
    if not _SLUG_RE.match(slug or ""):
        return _err(
            f"invalid slug {slug!r}: must match [a-z0-9-] and be 1-50 chars."
        )
    if not _oneline(title):
        return _err("title must be a non-empty string.")
    if not _oneline(destination):
        return _err("destination must be a non-empty string (name where you are headed).")
    if _state_path(slug).exists():
        return _err(f"a map with slug {slug!r} already exists.", code="duplicate")

    try:
        parsed_fog = json.loads(fog_json or "[]")
    except json.JSONDecodeError as exc:
        return _err(f"invalid fog JSON: {exc}")
    if not isinstance(parsed_fog, list):
        return _err("fog must be a JSON array of strings.")

    fog: list[dict[str, Any]] = []
    for i, text in enumerate(parsed_fog, 1):
        if not isinstance(text, str) or not text.strip():
            return _err(f"fog[{i - 1}] must be a non-empty string.")
        fog.append({"id": f"F-{i}", "text": _oneline(text), "status": "open"})

    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "backend": "local",
        "revision": 0,
        "map_id": uuid.uuid4().hex,
        "slug": slug,
        "title": _oneline(title),
        "status": "charting",
        "destination": _oneline(destination),
        "notes": _oneline(notes),
        "fog": fog,
        "out_of_scope": [],
        "tickets": {},
        "sessions": {},
    }
    _save_state(state)
    return _ok(
        slug=slug,
        map_id=state["map_id"],
        state_path=str(_state_path(slug)),
        map_path=str(_map_dir(slug) / "map.md"),
        fog_count=len(fog),
    )


def wayfind_status(slug: str | None = None) -> dict[str, Any]:
    """Without slug: list all maps. With slug: counts + handoff eligibility."""
    if slug is None:
        root = _wayfind_root()
        maps: list[dict[str, Any]] = []
        if root.exists():
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                state = _load_state(child.name)
                if state is None:
                    continue
                maps.append(_status_summary(state))
        return _ok(maps=maps, count=len(maps))

    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    return _ok(**_status_summary(state))


def _status_summary(state: dict[str, Any]) -> dict[str, Any]:
    tickets = state.get("tickets", {})
    open_ids = [tid for tid, t in tickets.items() if t.get("status") == "open"]
    blocked = [tid for tid in open_ids if _ticket_blocked(state, tickets[tid])]
    claimed = _active_claims(state)
    resolved = [tid for tid, t in tickets.items() if t.get("status") == "resolved"]
    out_of_scope = [
        tid for tid, t in tickets.items() if t.get("status") == "out_of_scope"
    ]
    return {
        "slug": state["slug"],
        "title": state.get("title", ""),
        "map_status": state.get("status", "active"),
        "revision": state.get("revision", 0),
        "counts": {
            "open": len(open_ids),
            "blocked": len(blocked),
            "claimed": len(claimed),
            "resolved": len(resolved),
            "out_of_scope": len(out_of_scope),
            "open_fog": len(_open_fog(state)),
            "frontier": len(_frontier_tickets(state)),
        },
        "handoff_eligible": _is_terminal(state),
    }


def list_handoffs() -> dict[str, Any]:
    """Return completed handoffs — the read-only source for /map-plan's offer."""
    root = _wayfind_root()
    handoffs: list[dict[str, Any]] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            handoff_path = child / "handoff.json"
            state = _load_state(child.name)
            if state is None or not handoff_path.exists():
                continue
            try:
                payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            handoffs.append(
                {
                    "slug": state["slug"],
                    "title": state.get("title", ""),
                    "handoff_path": str(child / "handoff.md"),
                    "decisions_count": len(payload.get("decisions", [])),
                    "generated_at": payload.get("generated_at", ""),
                }
            )
    return _ok(handoffs=handoffs, count=len(handoffs))


def show_ticket(slug: str, ticket_id: str) -> dict[str, Any]:
    """Read-only zoom into a single ticket."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    return _ok(ticket_id=ticket_id, ticket=ticket)


# ---------------------------------------------------------------------------
# Operations — tickets
# ---------------------------------------------------------------------------


def _parse_blocked_by(
    state: dict[str, Any], blocked_by_json: str
) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Parse + validate a blocked_by list. Returns (list, None) or (None, error)."""
    try:
        parsed = json.loads(blocked_by_json or "[]")
    except json.JSONDecodeError as exc:
        return None, _err(f"invalid blocked_by JSON: {exc}")
    if not isinstance(parsed, list):
        return None, _err("blocked_by must be a JSON array of ticket ids.")
    tickets = state.get("tickets", {})
    seen: list[str] = []
    for bid in parsed:
        if not isinstance(bid, str) or bid not in tickets:
            return None, _err(f"unknown blocker ticket id: {bid!r}.")
        if bid not in seen:
            seen.append(bid)
    return seen, None


def add_ticket(
    slug: str,
    title: str,
    ticket_type: str,
    question: str,
    blocked_by_json: str = "[]",
    from_fog: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Add a decision ticket with a single sharp question."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    if ticket_type not in WAYFIND_TICKET_TYPES:
        return _err(
            f"invalid ticket type {ticket_type!r}. "
            f"Must be one of: {sorted(WAYFIND_TICKET_TYPES)}."
        )
    if not _oneline(title):
        return _err("title must be a non-empty string.")
    if not _oneline(question):
        return _err(
            "question must be a single, sharply-stated question. "
            "If you cannot state it sharply now, keep it as fog (add_fog) instead."
        )
    blocked_by, error = _parse_blocked_by(state, blocked_by_json)
    if error is not None:
        return error
    assert blocked_by is not None
    if from_fog and not any(
        f.get("id") == from_fog and f.get("status") == "open"
        for f in state.get("fog", [])
    ):
        return _err(f"fog entry {from_fog!r} is unknown or not open.")

    ticket_id = _mint_ticket(state, title, ticket_type, question, blocked_by, from_fog)
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, ticket_id=ticket_id, revision=state["revision"])


def wire_blocking(
    slug: str,
    ticket_id: str,
    blocked_by_json: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Replace a ticket's blocked_by set; rejects unknown ids and cycles."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    if ticket_id not in state.get("tickets", {}):
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    blocked_by, error = _parse_blocked_by(state, blocked_by_json)
    if error is not None:
        return error
    assert blocked_by is not None
    if ticket_id in blocked_by:
        return _err("a ticket cannot block itself.")

    graph = _blocking_graph(state, override=(ticket_id, blocked_by))
    if _detect_cycle(graph):
        return _err(
            f"wiring {ticket_id!r} to block on {blocked_by} would create a cycle.",
            code="cycle",
        )

    state["tickets"][ticket_id]["blocked_by"] = blocked_by
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, ticket_id=ticket_id, blocked_by=blocked_by, revision=state["revision"])


def claim_ticket(
    slug: str,
    ticket_id: str,
    session: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Claim a frontier ticket before working it (claim-before-work invariant)."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    if not session:
        return _err("session id is required to claim a ticket.")
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    if ticket.get("status") != "open":
        return _err(
            f"ticket {ticket_id!r} is {ticket.get('status')!r}; only open tickets "
            "can be claimed.",
            code="not_open",
        )
    if ticket.get("claimed_by"):
        return _err(
            f"ticket {ticket_id!r} is already claimed by {ticket['claimed_by']!r}.",
            code="already_claimed",
        )
    if _ticket_blocked(state, ticket):
        return _err(
            f"ticket {ticket_id!r} is blocked by unresolved tickets "
            f"{ticket.get('blocked_by', [])}.",
            code="blocked",
        )

    if ticket.get("type") == "research":
        _ensure_research(ticket)
    ticket["claimed_by"] = session
    ticket["claimed_at"] = _now()
    ledger = _ensure_session(state, session)
    if ticket_id not in ledger["claimed"]:
        ledger["claimed"].append(ticket_id)
    if state.get("status") == "charting":
        state["status"] = "active"
    _recompute_status(state)
    _save_state(state)

    hitl_pending = ticket.get("type") in HITL_TYPES
    result = _ok(
        slug=slug,
        ticket_id=ticket_id,
        session=session,
        hitl_pending=hitl_pending,
        revision=state["revision"],
    )
    if hitl_pending:
        result["message"] = (
            f"{ticket['type']} ticket claimed. Ask the human the question verbatim, "
            "STOP generating, and hand control back. When the human answers, save "
            "their verbatim words to a file and call record_human_input before "
            "resolve_ticket."
        )
    return result


def release_ticket(
    slug: str,
    ticket_id: str,
    session: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Release a ticket claimed by this session (crash / interruption recovery)."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    if ticket.get("claimed_by") != session:
        return _err(
            f"ticket {ticket_id!r} is not claimed by session {session!r} "
            f"(claimed by {ticket.get('claimed_by')!r}).",
            code="not_owner",
        )
    ticket["claimed_by"] = None
    ticket["claimed_at"] = None
    ledger = state.get("sessions", {}).get(session)
    if ledger and ticket_id in ledger.get("claimed", []):
        ledger["claimed"].remove(ticket_id)
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, ticket_id=ticket_id, revision=state["revision"])


def record_human_input(
    slug: str,
    ticket_id: str,
    session: str,
    path: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Register a verbatim human response file — required before a HITL resolve."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    if ticket.get("claimed_by") != session:
        return _err(
            f"ticket {ticket_id!r} must be claimed by session {session!r} to record "
            f"human input (claimed by {ticket.get('claimed_by')!r}).",
            code="not_owner",
        )
    # Paths are relative to the map dir (.map/wayfind/<slug>/) so the value stored
    # in state.json doubles as a correct link target from the co-located views;
    # containment is enforced so absolute/../ paths cannot claim provenance.
    input_path = _resolve_evidence_path(slug, path)
    if input_path is None or not _safe_read(input_path).strip():
        return _err(
            f"human input file {path!r} must be a non-empty regular file INSIDE the map "
            "dir (.map/wayfind/<slug>/). Save the human's verbatim answer there first.",
            code="missing_input",
        )
    ticket["human_input_path"] = path
    _save_state(state)
    return _ok(slug=slug, ticket_id=ticket_id, human_input_path=path, revision=state["revision"])


def resolve_ticket(
    slug: str,
    ticket_id: str,
    session: str,
    gist: str,
    resolution_path: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Close a claimed ticket with a one-line gist + a prose resolution file."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    if ticket.get("claimed_by") != session:
        return _err(
            f"ticket {ticket_id!r} must be claimed by session {session!r} to resolve "
            f"(claimed by {ticket.get('claimed_by')!r}).",
            code="not_owner",
        )
    if ticket.get("status") != "open":
        return _err(
            f"ticket {ticket_id!r} is already {ticket.get('status')!r}.",
            code="not_open",
        )
    if not _oneline(gist):
        return _err("gist must be a non-empty one-line summary of the decision.")
    # resolution_path is relative to the map dir (.map/wayfind/<slug>/) so the stored
    # value is a correct link target from the co-located map.md / handoff.md views;
    # containment is enforced so absolute/../ paths cannot stand in as a resolution.
    resolution_file = _resolve_evidence_path(slug, resolution_path)
    if resolution_file is None or not _safe_read(resolution_file).strip():
        return _err(
            f"resolution file {resolution_path!r} must be a non-empty regular file INSIDE "
            "the map dir (.map/wayfind/<slug>/). Write the prose resolution first.",
            code="missing_resolution",
        )

    if ticket.get("type") == "research":
        research_error = _research_resolution_gate(state, ticket_id, gist, resolution_path)
        if research_error is not None:
            return research_error

    is_hitl = ticket.get("type") in HITL_TYPES
    if is_hitl and not ticket.get("human_input_path"):
        return _err(
            f"ticket {ticket_id!r} is a {ticket.get('type')} (human-in-the-loop) "
            "ticket awaiting a human response. Call record_human_input first.",
            code="awaiting_human",
        )

    is_non_research = ticket.get("type") != "research"
    ledger = _ensure_session(state, session)
    cap = _max_nonresearch_per_session()
    if is_non_research and cap > 0 and int(ledger.get("non_research_resolved", 0)) >= cap:
        return _err(
            f"this session has already resolved {cap} non-research ticket(s); the cap "
            f"is set via {_ENV_MAX_NONRESEARCH_PER_SESSION}. Start a new session to "
            "continue, or raise/unset the cap.",
            code="session_limit",
        )

    ticket["status"] = "resolved"
    ticket["resolved_at"] = _now()
    ticket["resolution"] = {"gist": _oneline(gist), "path": resolution_path}
    # Clear the active claim on close (consistent with rule_out_of_scope); the
    # resolver of record is captured in the resolution/git history, not claimed_by.
    ticket["claimed_by"] = None
    ticket["claimed_at"] = None
    if ticket_id in ledger.get("claimed", []):
        ledger["claimed"].remove(ticket_id)
    if is_non_research:
        ledger["non_research_resolved"] = int(ledger.get("non_research_resolved", 0)) + 1

    _recompute_status(state)
    _save_state(state)
    return _ok(
        slug=slug,
        ticket_id=ticket_id,
        ticket_status="resolved",
        handoff_eligible=_is_terminal(state),
        revision=state["revision"],
    )


def amend_resolution(
    slug: str,
    ticket_id: str,
    gist: str | None = None,
    resolution_path: str | None = None,
    expected_revision: int | None = None,
    assessment_path: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Correct the one-line gist and/or resolution path of an already-resolved
    ticket, without reopening it. The gist is baked into the resolution at
    resolve time; a later realization that the summary is wrong or misleading
    would otherwise be uncorrectable through the deterministic interface. This
    touches only free-text resolution metadata — it changes no structural
    invariant: status, claims, blocking, and ledger counts all stay put.

    Unlike structural mutations, this is allowed on a handed-off map (it uses the
    pure staleness check, not _mutation_guard): spotting a wrong/misleading gist
    in the frozen handoff is exactly when you need it. When the map is already
    handed off, re-run emit_wayfind_handoff afterwards so the frozen artifact
    picks up the corrected gist — the response flags this via
    handoff_refresh_needed."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    # Pure staleness check (not _mutation_guard): amending free-text metadata is
    # the one correction that legitimately applies to a handed-off map.
    guard = _revision_guard(state, expected_revision)
    if guard is not None:
        return guard
    ticket = state.get("tickets", {}).get(ticket_id)
    if ticket is None:
        return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
    if ticket.get("status") != "resolved":
        return _err(
            f"ticket {ticket_id!r} is {ticket.get('status')!r}, not resolved; only a "
            "resolved ticket's gist/resolution can be amended.",
            code="not_resolved",
        )
    if gist is None and resolution_path is None:
        return _err("nothing to amend: pass --gist and/or --resolution-path.")

    resolution = dict(ticket.get("resolution") or {})
    if gist is not None:
        if not _oneline(gist):
            return _err("gist must be a non-empty one-line summary of the decision.")
        resolution["gist"] = _oneline(gist)
    if resolution_path is not None:
        resolution_file = _resolve_evidence_path(slug, resolution_path)
        if resolution_file is None or not _safe_read(resolution_file).strip():
            return _err(
                f"resolution file {resolution_path!r} must be a non-empty regular file "
                "INSIDE the map dir (.map/wayfind/<slug>/).",
                code="missing_resolution",
            )
        resolution["path"] = resolution_path
    if ticket.get("research"):
        research = ticket["research"]
        correction = research.get("correction")
        if correction and correction.get("active") and correction.get("owner_session") != session:
            return _err("correction belongs to another session", code="not_owner")
        try:
            if assessment_path is not None:
                data, digest = _artifact_json(slug, ticket_id, assessment_path)
                _validate_assessment(state, ticket_id, data)
                _require(data["verdict"] == "sufficient" and data["gist"] == resolution["gist"] and data["resolution_path"] == resolution["path"], "amendment needs matching sufficient reassessment")
                existing = next((a for a in research["assessments"] if a["assessment_id"] == data["assessment_id"]), None)
                _require(existing is None or (existing["sha256"] == digest and existing["path"] == assessment_path), "assessment ID replay conflict")
                if existing is None:
                    research["assessments"].append({"assessment_id": data["assessment_id"], "path": assessment_path, "sha256": digest, "verdict": data["verdict"], "recorded_at": _now(), "session": session})
                research["accepted_assessment_id"] = data["assessment_id"]
                bound_ids = {b["attempt_id"] for b in data["attempt_bindings"]}
                research["accepted_generation"] = next(a.get("generation", 0) for a in research["attempts"] if a["attempt_id"] in bound_ids)
            gate = _research_resolution_gate(state, ticket_id, resolution["gist"], resolution["path"])
            if gate:
                return gate
        except (ResearchInputError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            return _err(f"research reassessment required: {exc}", code="research_reassessment_required")
        if correction and correction.get("active"):
            correction.update(active=False, completed_at=_now())
    ticket["resolution"] = resolution

    _recompute_status(state)
    _save_state(state)
    return _ok(
        slug=slug,
        ticket_id=ticket_id,
        gist=resolution.get("gist"),
        path=resolution.get("path"),
        handoff_refresh_needed=state.get("status") == "handed_off",
        revision=state["revision"],
    )


def amend_out_of_scope(
    slug: str,
    ticket_id: str = "",
    fog_id: str = "",
    reason: str | None = None,
    gist: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Correct the free-text reason and/or gist of an existing out-of-scope
    entry (keyed by the ticket_id or fog_id it was ruled out under). Same
    rationale and post-handoff semantics as amend_resolution: an exclusion's
    stated reason is baked at rule_out_of_scope time and surfaces in the frozen
    handoff, so it needs an in-place correction path that touches no structural
    invariant. Re-emit the handoff afterwards when handoff_refresh_needed."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _revision_guard(state, expected_revision)
    if guard is not None:
        return guard
    if bool(ticket_id) == bool(fog_id):
        return _err("provide exactly one of --ticket-id or --fog-id.")
    if reason is None and gist is None:
        return _err("nothing to amend: pass --reason and/or --gist.")

    key = "ticket_id" if ticket_id else "fog_id"
    ref = ticket_id or fog_id
    entry = next(
        (e for e in state.get("out_of_scope", []) if e.get(key) == ref), None
    )
    if entry is None:
        return _err(
            f"no out-of-scope entry for {ref!r} in map {slug!r}.", code="not_found"
        )
    if reason is not None:
        if not _oneline(reason):
            return _err("reason must be a non-empty one-line string.")
        entry["reason"] = _oneline(reason)
    if gist is not None:
        if not _oneline(gist):
            return _err("gist must be a non-empty one-line string.")
        entry["gist"] = _oneline(gist)

    _recompute_status(state)
    _save_state(state)
    return _ok(
        slug=slug,
        ref=ref,
        reason=entry.get("reason"),
        gist=entry.get("gist"),
        handoff_refresh_needed=state.get("status") == "handed_off",
        revision=state["revision"],
    )


def wayfind_frontier(slug: str) -> dict[str, Any]:
    """Return open + unblocked + unclaimed tickets (creation order)."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    frontier = [
        {
            "ticket_id": t["ticket_id"],
            "title": t.get("title", ""),
            "type": t.get("type"),
            "question": t.get("question", ""),
        }
        for t in _frontier_tickets(state)
    ]
    return _ok(slug=slug, frontier=frontier, count=len(frontier))


# ---------------------------------------------------------------------------
# Operations — fog & out-of-scope
# ---------------------------------------------------------------------------


def add_fog(
    slug: str, text: str, expected_revision: int | None = None
) -> dict[str, Any]:
    """Record a still-too-vague concern that cannot yet be a sharp ticket."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    if not _oneline(text):
        return _err("fog text must be a non-empty string.")
    fog_id = _next_fog_id(state)
    state.setdefault("fog", []).append(
        {"id": fog_id, "text": _oneline(text), "status": "open"}
    )
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, fog_id=fog_id, revision=state["revision"])


def graduate_fog(
    slug: str,
    fog_id: str,
    title: str,
    ticket_type: str,
    question: str,
    blocked_by_json: str = "[]",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Atomically graduate a fog entry into a sharp ticket."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    fog_entry = next((f for f in state.get("fog", []) if f.get("id") == fog_id), None)
    if fog_entry is None:
        return _err(f"no fog entry {fog_id!r} in map {slug!r}.", code="not_found")
    if fog_entry.get("status") != "open":
        return _err(
            f"fog {fog_id!r} is already {fog_entry.get('status')!r}; cannot graduate "
            "it again.",
            code="already_graduated",
        )
    if ticket_type not in WAYFIND_TICKET_TYPES:
        return _err(
            f"invalid ticket type {ticket_type!r}. "
            f"Must be one of: {sorted(WAYFIND_TICKET_TYPES)}."
        )
    if not _oneline(title):
        return _err("title must be a non-empty string.")
    if not _oneline(question):
        return _err("question must be a single, sharply-stated question.")
    blocked_by, error = _parse_blocked_by(state, blocked_by_json)
    if error is not None:
        return error
    assert blocked_by is not None

    ticket_id = _mint_ticket(state, title, ticket_type, question, blocked_by, fog_id)
    fog_entry["status"] = "graduated"
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, ticket_id=ticket_id, fog_id=fog_id, revision=state["revision"])


def rule_out_of_scope(
    slug: str,
    reason: str,
    ticket_id: str = "",
    fog_id: str = "",
    gist: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Permanently rule a ticket (or fog entry) out of scope.

    Out-of-scope items are recorded separately and never appear in Decisions so
    far — an exclusion is not a decision that graduates into the plan.
    """
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    guard = _mutation_guard(state, expected_revision)
    if guard is not None:
        return guard
    if not _oneline(reason):
        return _err("reason must be a non-empty string.")
    if bool(ticket_id) == bool(fog_id):
        return _err("provide exactly one of ticket_id or fog_id.")

    entry: dict[str, Any] = {"reason": _oneline(reason), "ruled_at": _now()}
    if ticket_id:
        ticket = state.get("tickets", {}).get(ticket_id)
        if ticket is None:
            return _err(f"no ticket {ticket_id!r} in map {slug!r}.", code="not_found")
        if ticket.get("status") in TERMINAL_TICKET_STATUSES:
            return _err(
                f"ticket {ticket_id!r} is already {ticket.get('status')!r}.",
                code="not_open",
            )
        ticket["status"] = "out_of_scope"
        session = ticket.get("claimed_by")
        ticket["claimed_by"] = None
        ticket["claimed_at"] = None
        ledger = state.get("sessions", {}).get(session) if session else None
        if ledger and ticket_id in ledger.get("claimed", []):
            ledger["claimed"].remove(ticket_id)
        entry["ticket_id"] = ticket_id
        entry["gist"] = _oneline(gist) or _oneline(ticket.get("title", ""))
    else:
        fog_entry = next(
            (f for f in state.get("fog", []) if f.get("id") == fog_id), None
        )
        if fog_entry is None:
            return _err(f"no fog entry {fog_id!r} in map {slug!r}.", code="not_found")
        if fog_entry.get("status") != "open":
            return _err(
                f"fog {fog_id!r} is already {fog_entry.get('status')!r}.",
                code="not_open",
            )
        fog_entry["status"] = "retired"
        entry["fog_id"] = fog_id
        entry["gist"] = _oneline(gist) or _oneline(fog_entry.get("text", ""))

    state.setdefault("out_of_scope", []).append(entry)
    _recompute_status(state)
    _save_state(state)
    return _ok(slug=slug, ruled=ticket_id or fog_id, revision=state["revision"])


# ---------------------------------------------------------------------------
# Operations — handoff
# ---------------------------------------------------------------------------


def _open_item_labels(state: dict[str, Any]) -> list[str]:
    """Human-readable list of items blocking a clean (non-early) handoff."""
    labels: list[str] = []
    for tid in sorted(state.get("tickets", {})):
        ticket = state["tickets"][tid]
        if ticket.get("status") in TERMINAL_TICKET_STATUSES:
            continue
        state_word = "claimed" if ticket.get("claimed_by") else "open"
        labels.append(f"{tid} ({ticket.get('type')}, {state_word}): {ticket.get('title', '')}")
    for fog in _open_fog(state):
        labels.append(f"{fog.get('id')} (fog): {fog.get('text', '')}")
    return labels


def _handoff_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {"map_id": state.get("map_id"), "slug": state["slug"], "title": state.get("title"), "destination": state.get("destination"), "tickets": {tid: {"status": ticket.get("status"), "title": ticket.get("title"), "type": ticket.get("type"), "question": ticket.get("question"), "resolution": ticket.get("resolution"), "accepted_assessment_id": (ticket.get("research") or {}).get("accepted_assessment_id"), "correction": (ticket.get("research") or {}).get("correction")} for tid, ticket in state.get("tickets", {}).items()}, "out_of_scope": state.get("out_of_scope", []), "fog": state.get("fog", [])}


@_research_api
def validate_wayfind_handoff(slug: str) -> dict[str, Any]:
    state = _load_state(slug)
    if state is None:
        return _err("map missing", code="not_found")
    json_path = _resolve_evidence_path(slug, "handoff.json")
    md_path = _resolve_evidence_path(slug, "handoff.md")
    _require(json_path is not None and md_path is not None, "handoff publication incomplete")
    assert json_path is not None and md_path is not None
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict) and payload.get("slug") == slug and payload.get("map_id") == state.get("map_id"), "handoff identity mismatch")
    managed = any(t.get("research") for t in state.get("tickets", {}).values())
    commitment = state.get("handoff_commitment")
    if not commitment:
        _require(not managed, "managed research requires handoff commitment")
        return _ok(evidence_status="legacy_unrecorded", warnings=["Legacy handoff has unrecorded evidence provenance."])
    _require(commitment["json_sha256"] == _digest(json_path) and commitment["markdown_sha256"] == _digest(md_path), "handoff bytes changed or publication incomplete")
    _require(commitment["semantic_sha256"] == _json_digest(_handoff_snapshot(state)), "handoff semantic state stale")
    for decision in payload.get("decisions", []):
        ticket_id = decision["ticket_id"]
        ticket = state["tickets"][ticket_id]
        correction = (ticket.get("research") or {}).get("correction")
        _require(not correction or not correction.get("active"), "correction decision cannot seed planning")
        if ticket.get("research"):
            gate = _research_resolution_gate(state, ticket_id, decision["gist"], decision["resolution_path"])
            _require(gate is None, (gate or {}).get("message", "stale research"))
    return _ok(evidence_status="recorded" if managed else "legacy_unrecorded", warnings=[] if managed else ["Research provenance was not recorded."])


@_research_api
def emit_wayfind_handoff(
    slug: str,
    remaining_risks_json: str = "[]",
    early: bool = False,
    confirmed_by_user: bool = False,
    branch: str | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Write the handoff artifact consumed by /map-plan and mark the map handed off."""
    state = _load_state(slug)
    if state is None:
        return _err(f"no map with slug {slug!r}.", code="not_found")
    # Pure staleness check (not _mutation_guard): a handed-off map may be
    # idempotently re-emitted, so we do not reject on status == "handed_off".
    guard = _revision_guard(state, expected_revision)
    if guard is not None:
        return guard

    try:
        remaining_risks = json.loads(remaining_risks_json or "[]")
    except json.JSONDecodeError as exc:
        return _err(f"invalid remaining_risks JSON: {exc}")
    if not isinstance(remaining_risks, list) or not all(
        isinstance(r, str) for r in remaining_risks
    ):
        return _err("remaining_risks must be a JSON array of strings.")
    remaining_risks = [_oneline(r) for r in remaining_risks]
    if not remaining_risks and state.get("handoff_commitment"):
        remaining_risks = list(state["handoff_commitment"].get("caller_risks", []))
    caller_risks = list(dict.fromkeys(remaining_risks))
    remaining_risks = list(caller_risks)
    corrections = [tid for tid, t in state.get("tickets", {}).items() if ((t.get("research") or {}).get("correction") or {}).get("active")]
    if corrections and not (early and confirmed_by_user):
        return _err("active research correction blocks normal handoff", code="active_research_correction")
    remaining_risks += [f"UNRESOLVED CORRECTION: {tid}" for tid in corrections]

    open_items = _open_item_labels(state)
    if not _is_terminal(state):
        if not (early and confirmed_by_user):
            return _err(
                "map is not exhausted: fog, claimed, or unresolved tickets remain. "
                "Resolve or rule out every item, or pass --early with "
                "--confirmed-by-user to hand off with open items as remaining risks.",
                code="not_terminal",
                open_items=open_items,
            )
        # Early handoff: fold open items into remaining risks so nothing is lost.
        remaining_risks = remaining_risks + [f"UNRESOLVED: {label}" for label in open_items]

    decisions = []
    for tid in sorted(state.get("tickets", {})):
        ticket = state["tickets"][tid]
        if ticket.get("status") != "resolved" or tid in corrections:
            continue
        resolution = ticket.get("resolution") or {}
        if ticket.get("research"):
            gate = _research_resolution_gate(state, tid, resolution.get("gist", ""), resolution.get("path", ""))
            if gate:
                return gate
        decisions.append(
            {
                "ticket_id": tid,
                "title": ticket.get("title", ""),
                "type": ticket.get("type"),
                "question": ticket.get("question", ""),
                "gist": resolution.get("gist", ""),
                "resolution_path": resolution.get("path", ""),
                "evidence_status": "recorded" if ticket.get("research") else "legacy_unrecorded",
                "evidence_protocol": 1 if ticket.get("research") else None,
                "accepted_assessment": next((a for a in (ticket.get("research") or {}).get("assessments", []) if a["assessment_id"] == (ticket.get("research") or {}).get("accepted_assessment_id")), None),
            }
        )

    out_of_scope = [
        {
            "gist": entry.get("gist", ""),
            "reason": entry.get("reason", ""),
            "ref": entry.get("ticket_id") or entry.get("fog_id") or "",
        }
        for entry in state.get("out_of_scope", [])
    ]

    generated_at = _now()
    map_dir = _map_dir(slug)
    handoff_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "map_id": state.get("map_id", ""),
        "title": state.get("title", ""),
        "destination": state.get("destination", ""),
        "generated_at": generated_at,
        "early": bool(early and (not _is_terminal(state) or corrections)),
        "evidence_protocol": 1,
        "decisions": decisions,
        "out_of_scope": out_of_scope,
        "remaining_risks": remaining_risks,
    }
    json_path = map_dir / "handoff.json"
    md_path = map_dir / "handoff.md"
    tmp_json = json_path.with_name(f".{json_path.name}.{os.getpid()}.tmp")
    tmp_json.write_text(
        json.dumps(handoff_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    tmp_json.replace(json_path)
    md_path.write_text(_render_handoff_md(handoff_payload), encoding="utf-8")

    state["status"] = "handed_off"
    state["handoff_commitment"] = {"protocol_version": 1, "json_sha256": _digest(json_path), "markdown_sha256": _digest(md_path), "semantic_sha256": _json_digest(_handoff_snapshot(state)), "remaining_risks": remaining_risks, "caller_risks": caller_risks}
    _save_state(state)

    manifest_info = _register_handoff_manifest(slug, json_path, md_path, decisions, branch)

    return _ok(
        slug=slug,
        handoff_path=str(md_path),
        handoff_json=str(json_path),
        decisions_count=len(decisions),
        remaining_risks_count=len(remaining_risks),
        manifest=manifest_info,
        revision=state["revision"],
    )


def _render_handoff_md(payload: dict[str, Any]) -> str:
    lines = [
        f"# Wayfinding Handoff: {_oneline(payload.get('title', ''))}",
        "",
        f"- **Slug:** `{payload.get('slug', '')}`",
        f"- **Generated:** {payload.get('generated_at', '')}",
        f"- **Early handoff:** {'yes' if payload.get('early') else 'no'}",
        "",
        "## Destination",
        "",
        _oneline(payload.get("destination", "")) or "_Not stated._",
        "",
        "## Decisions Made",
        "",
        "| # | Question | Decision | Resolution |",
        "|---|----------|----------|------------|",
    ]
    if payload.get("decisions"):
        for i, decision in enumerate(payload["decisions"], 1):
            path = decision.get("resolution_path", "")
            link = f"[{decision.get('ticket_id', '')}]({path})" if path else decision.get("ticket_id", "")
            lines.append(
                f"| {i} | {_oneline(decision.get('question', ''))} | "
                f"{_oneline(decision.get('gist', ''))} | {link} |"
            )
    else:
        lines.append("| — | _No decisions resolved._ | | |")

    lines += ["", "## Out of Scope", ""]
    if payload.get("out_of_scope"):
        for entry in payload["out_of_scope"]:
            ref = entry.get("ref", "")
            ref_text = f" (from {ref})" if ref else ""
            lines.append(
                f"- {_oneline(entry.get('gist', ''))} — "
                f"{_oneline(entry.get('reason', ''))}{ref_text}"
            )
    else:
        lines.append("_None._")

    lines += ["", "## Open Questions / Remaining Risks", ""]
    if payload.get("remaining_risks"):
        for risk in payload["remaining_risks"]:
            lines.append(f"- {_oneline(risk)}")
    else:
        lines.append("_None._")

    lines += [
        "",
        "---",
        "",
        "Feed this into planning with "
        "`/map-plan --wayfind " + str(payload.get("slug", "")) + "` on a feature branch.",
        "",
    ]
    return "\n".join(lines)


def _register_handoff_manifest(
    slug: str,
    json_path: Path,
    md_path: Path,
    decisions: list[dict[str, Any]],
    branch: str | None,
) -> dict[str, Any]:
    """Register the wayfind_handoff manifest stage on the current branch.

    LAZY import of map_step_runner — the ONLY cross-module coupling. A manifest
    failure is reported but never loses the already-written handoff artifact.
    """
    try:
        import map_step_runner  # pyright: ignore[reportMissingImports]

        manifest = map_step_runner.load_artifact_manifest(branch)
        map_step_runner._set_manifest_stage(
            manifest,
            "wayfind_handoff",
            "ready",
            artifacts=[
                map_step_runner._artifact_ref(md_path, "wayfind-handoff"),
                map_step_runner._artifact_ref(json_path, "wayfind-handoff-json"),
            ],
            metadata={"slug": slug, "decisions_count": len(decisions)},
        )
        result = map_step_runner.save_artifact_manifest(manifest, branch)
        return {"status": "success", "path": result.get("path")}
    except Exception as exc:  # noqa: BLE001 — manifest is best-effort, never fatal
        return {"status": "skipped", "reason": f"manifest registration failed: {exc}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(result: dict[str, Any]) -> int:
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result.get("status") == "success" else 1


def _add_revision_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expected-revision",
        type=int,
        default=None,
        help="optimistic-concurrency guard: fail if the map is not at this revision",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wayfind_runner.py",
        description="Deterministic operations for /map-wayfind decision maps.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    types = sorted(WAYFIND_TICKET_TYPES)

    p = sub.add_parser("create_wayfind_map", help="create a new decision map")
    p.add_argument("slug")
    p.add_argument("title")
    p.add_argument("destination")
    p.add_argument("--notes", default="")
    p.add_argument("--fog-json", default="[]")

    p = sub.add_parser("wayfind_status", help="list maps or show one map's status")
    p.add_argument("--slug", default=None)

    sub.add_parser("list_handoffs", help="list completed handoffs")

    p = sub.add_parser("show_ticket", help="show one ticket")
    p.add_argument("slug")
    p.add_argument("ticket_id")

    p = sub.add_parser("add_ticket", help="add a decision ticket")
    p.add_argument("slug")
    p.add_argument("title")
    p.add_argument("ticket_type", choices=types)
    p.add_argument("question")
    p.add_argument("--blocked-by-json", default="[]")
    p.add_argument("--from-fog", default="")
    _add_revision_arg(p)

    p = sub.add_parser("wire_blocking", help="set a ticket's blocked_by set")
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("blocked_by_json")
    _add_revision_arg(p)

    p = sub.add_parser("claim_ticket", help="claim a frontier ticket")
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("session")
    _add_revision_arg(p)

    p = sub.add_parser("release_ticket", help="release a claimed ticket")
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("session")
    _add_revision_arg(p)

    p = sub.add_parser("record_human_input", help="register a verbatim human response")
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("session")
    p.add_argument("path")
    _add_revision_arg(p)

    p = sub.add_parser("resolve_ticket", help="resolve a claimed ticket")
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("session")
    p.add_argument("gist")
    p.add_argument("resolution_path")
    _add_revision_arg(p)

    p = sub.add_parser(
        "amend_resolution",
        help="correct a resolved ticket's one-line gist and/or resolution path",
    )
    p.add_argument("slug")
    p.add_argument("ticket_id")
    p.add_argument("--gist", default=None)
    p.add_argument("--resolution-path", dest="resolution_path", default=None)
    p.add_argument("--assessment-path", default=None)
    p.add_argument("--session", default=None)
    _add_revision_arg(p)

    p = sub.add_parser(
        "amend_out_of_scope",
        help="correct an out-of-scope entry's reason and/or gist",
    )
    p.add_argument("slug")
    p.add_argument("--ticket-id", dest="ticket_id", default="")
    p.add_argument("--fog-id", dest="fog_id", default="")
    p.add_argument("--reason", default=None)
    p.add_argument("--gist", default=None)
    _add_revision_arg(p)

    p = sub.add_parser("wayfind_frontier", help="list open+unblocked+unclaimed tickets")
    p.add_argument("slug")

    p = sub.add_parser("add_fog", help="record a still-vague concern")
    p.add_argument("slug")
    p.add_argument("text")
    _add_revision_arg(p)

    p = sub.add_parser("graduate_fog", help="turn a fog entry into a ticket")
    p.add_argument("slug")
    p.add_argument("fog_id")
    p.add_argument("title")
    p.add_argument("ticket_type", choices=types)
    p.add_argument("question")
    p.add_argument("--blocked-by-json", default="[]")
    _add_revision_arg(p)

    p = sub.add_parser("rule_out_of_scope", help="rule a ticket or fog out of scope")
    p.add_argument("slug")
    p.add_argument("reason")
    p.add_argument("--ticket-id", default="")
    p.add_argument("--fog-id", default="")
    p.add_argument("--gist", default="")
    _add_revision_arg(p)

    p = sub.add_parser("emit_wayfind_handoff", help="write the handoff artifact")
    p.add_argument("slug")
    p.add_argument("--remaining-risks-json", default="[]")
    p.add_argument("--early", action="store_true")
    p.add_argument("--confirmed-by-user", action="store_true")
    p.add_argument("--branch", default=None)
    _add_revision_arg(p)

    research_commands = {
        "configure_research": ("slug", "ticket_id", "session", "mode", "reason"),
        "reserve_research_attempt": ("slug", "ticket_id", "session", "request_id", "phase", "investigator_id", "brief_path"),
        "record_research_attempt": ("slug", "ticket_id", "session", "attempt_id", "outcome"),
        "extend_research_budget": ("slug", "ticket_id", "session", "extension_id", "additional_attempts", "approval_path", "reason"),
        "record_research_assessment": ("slug", "ticket_id", "session", "assessment_path"),
        "begin_research_correction": ("slug", "ticket_id", "session", "reason"),
        "release_research_correction": ("slug", "ticket_id", "session"),
        "claim_research_correction": ("slug", "ticket_id", "session"),
        "research_context": ("slug", "ticket_id"),
        "research_artifact_hash": ("slug", "path"),
        "validate_wayfind_handoff": ("slug",),
    }
    for command, arguments in research_commands.items():
        p = sub.add_parser(command)
        for argument in arguments:
            p.add_argument(argument, type=int if argument == "additional_attempts" else str)
        if command == "record_research_attempt":
            p.add_argument("--result-path", default=None)
            p.add_argument("--reason", default=None)
            p.add_argument("--dispatch-id", default=None)
        if command == "research_artifact_hash":
            p.add_argument("--scope", choices=("map", "local_code"), default="map")
        if command not in {"research_context", "research_artifact_hash", "validate_wayfind_handoff"}:
            _add_revision_arg(p)
    return parser


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
    research_dispatch = {
        "configure_research": configure_research,
        "reserve_research_attempt": reserve_research_attempt,
        "record_research_attempt": record_research_attempt,
        "extend_research_budget": extend_research_budget,
        "record_research_assessment": record_research_assessment,
        "begin_research_correction": begin_research_correction,
        "release_research_correction": release_research_correction,
        "claim_research_correction": claim_research_correction,
        "validate_wayfind_handoff": validate_wayfind_handoff,
        "research_context": research_context,
        "research_artifact_hash": research_artifact_hash,
    }
    if command in research_dispatch:
        return research_dispatch[command](**{k: v for k, v in vars(args).items() if k != "command"})
    if command == "create_wayfind_map":
        return create_wayfind_map(
            args.slug, args.title, args.destination, args.notes, args.fog_json
        )
    if command == "wayfind_status":
        return wayfind_status(args.slug)
    if command == "list_handoffs":
        return list_handoffs()
    if command == "show_ticket":
        return show_ticket(args.slug, args.ticket_id)
    if command == "add_ticket":
        return add_ticket(
            args.slug,
            args.title,
            args.ticket_type,
            args.question,
            args.blocked_by_json,
            args.from_fog,
            args.expected_revision,
        )
    if command == "wire_blocking":
        return wire_blocking(
            args.slug, args.ticket_id, args.blocked_by_json, args.expected_revision
        )
    if command == "claim_ticket":
        return claim_ticket(
            args.slug, args.ticket_id, args.session, args.expected_revision
        )
    if command == "release_ticket":
        return release_ticket(
            args.slug, args.ticket_id, args.session, args.expected_revision
        )
    if command == "record_human_input":
        return record_human_input(
            args.slug, args.ticket_id, args.session, args.path, args.expected_revision
        )
    if command == "resolve_ticket":
        return resolve_ticket(
            args.slug,
            args.ticket_id,
            args.session,
            args.gist,
            args.resolution_path,
            args.expected_revision,
        )
    if command == "amend_resolution":
        return amend_resolution(
            args.slug,
            args.ticket_id,
            args.gist,
            args.resolution_path,
            args.expected_revision,
            args.assessment_path,
            args.session,
        )
    if command == "amend_out_of_scope":
        return amend_out_of_scope(
            args.slug,
            args.ticket_id,
            args.fog_id,
            args.reason,
            args.gist,
            args.expected_revision,
        )
    if command == "wayfind_frontier":
        return wayfind_frontier(args.slug)
    if command == "add_fog":
        return add_fog(args.slug, args.text, args.expected_revision)
    if command == "graduate_fog":
        return graduate_fog(
            args.slug,
            args.fog_id,
            args.title,
            args.ticket_type,
            args.question,
            args.blocked_by_json,
            args.expected_revision,
        )
    if command == "rule_out_of_scope":
        return rule_out_of_scope(
            args.slug,
            args.reason,
            args.ticket_id,
            args.fog_id,
            args.gist,
            args.expected_revision,
        )
    if command == "emit_wayfind_handoff":
        return emit_wayfind_handoff(
            args.slug,
            args.remaining_risks_json,
            args.early,
            args.confirmed_by_user,
            args.branch,
            args.expected_revision,
        )
    return _err(f"unknown command: {command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _print(_dispatch(args))


if __name__ == "__main__":
    sys.exit(main())
