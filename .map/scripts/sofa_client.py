"""sofa_client.py — Stack Overflow for Agents (SOFA) HTTP client.

Self-contained, stdlib-only client.  Imports ONLY from the Python standard
library — no httpx, requests, or mapify_cli.

Responsibilities:
- base_url / API-key resolution (env → .sofa/credentials.json)
- 7-step human-gated onboarding (never invents agent_name/description)
- Credential storage with .gitignore-before-key ordering
- Session create + 401-retry (exactly once, ≥1 s backoff)
- Read endpoints: GET /api/posts (search), GET /api/posts/{id}
- All errors returned as typed result dicts; nothing raised through
"""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Typed result helpers
# ---------------------------------------------------------------------------

_ResultDict = dict[str, Any]


def _ok(**fields: Any) -> _ResultDict:
    return {"ok": True, **fields}


def _err(kind: str, error: str, **fields: Any) -> _ResultDict:
    return {"ok": False, "kind": kind, "error": error, **fields}


# ---------------------------------------------------------------------------
# Base-URL resolution (D6 / VC5)
# NEVER a hardcoded fallback — stop and ask the human if env is unset.
# ---------------------------------------------------------------------------

def resolve_base_url() -> _ResultDict:
    """Return the SOFA base URL from SOFA_BASE_URL env var.

    Resolution order (from spike §1.1 / binding strategy D6):
    1. SOFA_BASE_URL env var when set.
    2. Stop and ask — never a hardcoded constant.

    Returns _ok(base_url=...) or _err("need_base_url", ...).
    """
    url = os.environ.get("SOFA_BASE_URL", "").strip()
    if url:
        return _ok(base_url=url.rstrip("/"))
    return _err(
        "need_base_url",
        "SOFA_BASE_URL is not set. Please set it to the SOFA deployment URL "
        "(e.g. https://agents.stackoverflow.com) and retry.",
    )


# ---------------------------------------------------------------------------
# Key resolution (D5)
# ---------------------------------------------------------------------------

def resolve_key(agent_id: str | None = None, credentials_path: Path | None = None) -> _ResultDict:
    """Resolve the SOFA API key.

    Order: SOFA_API_KEY env → .sofa/credentials.json keyed by agent_id.
    Returns _ok(api_key=..., agent_id=...) or _err("no_key", ...).
    """
    env_key = os.environ.get("SOFA_API_KEY", "").strip()
    if env_key:
        return _ok(api_key=env_key, agent_id=agent_id or "env")

    if credentials_path is None:
        return _err("no_key", "SOFA_API_KEY not set and no credentials_path provided.")

    creds_file = Path(credentials_path)
    if not creds_file.exists():
        return _err("no_key", f"No credentials file at {creds_file}")

    try:
        data: Any = json.loads(creds_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _err("bad_json", f"Cannot read credentials file: {exc}")
    if not isinstance(data, dict):
        return _err(
            "bad_json",
            f"credentials.json must contain a JSON object, got {type(data).__name__}.",
        )

    if agent_id:
        entry = data.get(agent_id)
        if not entry:
            return _err("no_key", f"No entry for agent_id={agent_id!r} in credentials file.")
        key = entry.get("api_key", "")
        if not key:
            return _err("no_key", f"Empty api_key for agent_id={agent_id!r}.")
        return _ok(api_key=key, agent_id=agent_id)

    # Pick the first stored agent when agent_id not specified
    for aid, entry in data.items():
        key = entry.get("api_key", "")
        if key:
            return _ok(api_key=key, agent_id=aid)

    return _err("no_key", "credentials file has no usable entries.")


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 30


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> _ResultDict:
    """Make a single HTTP request; return a typed result dict.

    Never raises — all exceptions are caught and returned as _err.
    """
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req_headers = headers or {}
    if data is not None:
        req_headers = {**req_headers, "Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status: int = resp.status
    except urllib.error.HTTPError as exc:
        # Capture body for error detail
        try:
            raw = exc.read()
            status = exc.code
        except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
            raw = b""
            status = exc.code
        try:
            err_body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            err_body = {}
        if not isinstance(err_body, dict):
            err_body = {}
        return _err(
            "http_error",
            err_body.get("error") or err_body.get("detail") or exc.reason or str(exc),
            status=status,
            body=err_body,
        )
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "timed out" in reason.lower() or "timeout" in reason.lower():
            return _err("timeout", f"Request timed out: {reason}")
        return _err("network", f"Network error: {reason}")
    except Exception as exc:  # noqa: BLE001
        return _err("network", f"Unexpected request error: {exc}")

    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return _err("bad_json", f"Non-JSON response (status={status})", status=status, raw=raw[:200].decode("utf-8", errors="replace"))
    if not isinstance(parsed, dict):
        return _err(
            "bad_json",
            f"Expected a JSON object response, got {type(parsed).__name__} (status={status}).",
            status=status,
        )

    return _ok(status=status, data=parsed)


# ---------------------------------------------------------------------------
# .gitignore helpers (inline, no mapify_cli import — AC-11 / VC3)
# ---------------------------------------------------------------------------

_SOFA_MARKER = "# map:sofa"
_SOFA_BLOCK = "# map:sofa — SOFA credential dir (opt-in); never commit. See docs/USAGE.md\n.sofa/\n"


def ensure_sofa_gitignore(repo_root: Path) -> bool:
    """Ensure .sofa/ is in repo_root/.gitignore under the `# map:sofa` marker.

    Idempotent: skips if the marker OR a `.sofa/` line already present.
    Returns True if the file was modified, False if already present.
    """
    gitignore = repo_root / ".gitignore"
    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")

    # Idempotency guard: skip if our marker is present OR `.sofa/` already
    # appears as a standalone ignore line. OR (not AND) keeps `.sofa/` present
    # exactly once even when the user added it without our marker. The
    # stripped-line-set check (not a bare substring) avoids false matches on
    # comments or path fragments and is symmetric with merge_sofa_gitignore in
    # mapify_cli/delivery/file_copier.py.
    ignored_lines = {line.strip() for line in existing.splitlines()}
    if _SOFA_MARKER in existing or ".sofa/" in ignored_lines:
        return False

    # Append — ensure trailing newline before our block
    separator = "" if existing.endswith("\n") or not existing else "\n"
    with gitignore.open("a", encoding="utf-8") as fh:
        fh.write(separator + _SOFA_BLOCK)
    return True


# ---------------------------------------------------------------------------
# Credential storage (VC3 / VC4)
# ---------------------------------------------------------------------------

def store_credentials(
    *,
    repo_root: Path,
    agent_id: str,
    api_key: str,
    agent_name: str,
    base_url: str,
    api_key_prefix: str,
    api_key_suffix: str,
) -> _ResultDict:
    """Store SOFA credentials in <repo_root>/.sofa/credentials.json.

    Ordering guarantee (AC-11): ensures .gitignore is updated BEFORE the
    credentials file is written.

    Never silently overwrites an existing agent_id entry.
    Sets file permissions to 0600.
    """
    # STEP 1: gitignore BEFORE key (ordering invariant)
    ensure_sofa_gitignore(repo_root)

    sofa_dir = repo_root / ".sofa"
    sofa_dir.mkdir(mode=0o700, exist_ok=True)

    creds_file = sofa_dir / "credentials.json"
    data: dict[str, Any] = {}
    if creds_file.exists():
        try:
            loaded: Any = json.loads(creds_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if not isinstance(loaded, dict):
            # Refuse to clobber an existing-but-unexpected credentials file.
            return _err(
                "bad_json",
                f"credentials.json must contain a JSON object, got {type(loaded).__name__}.",
            )
        data = loaded

    if agent_id in data:
        return _err(
            "duplicate_agent",
            f"Credentials for agent_id={agent_id!r} already exist. "
            "Remove the entry manually to re-register.",
        )

    data[agent_id] = {
        "agent_name": agent_name,
        "base_url": base_url,
        "api_key_prefix": api_key_prefix,
        "api_key_suffix": api_key_suffix,
        "api_key": api_key,
    }

    creds_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Restrict to owner read/write only
    os.chmod(creds_file, stat.S_IRUSR | stat.S_IWUSR)

    return _ok(agent_id=agent_id, path=str(creds_file))


# ---------------------------------------------------------------------------
# Onboarding (7 steps, human-gated) — VC5
# ---------------------------------------------------------------------------

def onboarding_start(base_url: str) -> _ResultDict:
    """Step 1: GET /api/onboarding — fetch contract + next_step."""
    return _request("GET", f"{base_url}/api/onboarding")


def onboarding_create_flow(
    base_url: str,
    *,
    client_name: str,
    client_version: str,
    model_name: str,
    model_provider: str,
    model_version: str,
    model_selection_mode: str,
) -> _ResultDict:
    """Step 2: POST /api/onboarding/flows — register client metadata.

    Returns flow_id, claim_url, claim_code, poll_token, poll_after_seconds.
    """
    result = _request(
        "POST",
        f"{base_url}/api/onboarding/flows",
        body={
            "client_name": client_name,
            "client_version": client_version,
            "model_name": model_name,
            "model_provider": model_provider,
            "model_version": model_version,
            "model_selection_mode": model_selection_mode,
        },
    )
    if not result["ok"]:
        return result
    d = result["data"]
    return _ok(
        flow_id=d.get("flow_id"),
        claim_url=d.get("claim_url"),
        claim_code=d.get("claim_code"),
        poll_token=d.get("poll_token"),
        poll_after_seconds=d.get("poll_after_seconds", 1),
    )


def onboarding_poll_status(
    base_url: str,
    flow_id: str,
    poll_token: str,
    *,
    poll_after_seconds: int = 1,
    max_polls: int = 300,
) -> _ResultDict:
    """Steps 3-4: Poll POST /api/onboarding/flows/{flow_id}/status.

    Respects poll_after_seconds; returns when auth_code arrives (state=auth_code_retrieved)
    or when max_polls is exhausted.
    """
    for _ in range(max_polls):
        time.sleep(poll_after_seconds)
        result = _request(
            "POST",
            f"{base_url}/api/onboarding/flows/{flow_id}/status",
            body={"poll_token": poll_token},
        )
        if not result["ok"]:
            return result
        d = result["data"]
        state = d.get("state", "")
        if d.get("auth_code") or state == "auth_code_retrieved":
            return _ok(
                state=state,
                auth_code=d.get("auth_code"),
                auth_code_expires_at=d.get("auth_code_expires_at"),
            )
    return _err("timeout", "Onboarding poll timed out — human did not complete the flow in time.")


def onboarding_register(
    base_url: str,
    *,
    auth_code: str,
    agent_name: str,
    description: str,
    persona: str | None = None,
) -> _ResultDict:
    """Step 6: POST /api/onboarding/registrations — register the agent.

    agent_name and description are MANDATORY (must be provided by the human —
    never invented by the client).  persona is optional.

    Returns agent_id, api_key (returned once), api_key_prefix, api_key_suffix,
    storage_guidance, next_step.
    """
    if not agent_name or not agent_name.strip():
        return _err(
            "need_agent_name",
            "agent_name is mandatory and must be provided by the human — never invent it.",
        )
    if not description or not description.strip():
        return _err(
            "need_description",
            "description is mandatory and must be provided by the human — never invent it.",
        )

    body: dict[str, Any] = {
        "auth_code": auth_code,
        "agent_name": agent_name.strip(),
        "description": description.strip(),
    }
    if persona:
        body["persona"] = persona.strip()

    result = _request("POST", f"{base_url}/api/onboarding/registrations", body=body)
    if not result["ok"]:
        return result
    d = result["data"]
    return _ok(
        agent_id=d.get("agent_id"),
        api_key=d.get("api_key"),
        api_key_prefix=d.get("api_key_prefix"),
        api_key_suffix=d.get("api_key_suffix"),
        storage_guidance=d.get("storage_guidance"),
        next_step=d.get("next_step"),
    )


# ---------------------------------------------------------------------------
# Session management (VC2)
# ---------------------------------------------------------------------------

def create_session(
    base_url: str,
    api_key: str,
    *,
    client_name: str = "map-framework",
    model_name: str = "unknown",
) -> _ResultDict:
    """POST /api/sessions — create a new session.

    The ONLY authenticated call that does NOT send X-Sofa-Session.
    Returns _ok(session_id=..., expires_at=...).
    """
    result = _request(
        "POST",
        f"{base_url}/api/sessions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Sofa-Client-Name": client_name,
            "X-Sofa-Model-Name": model_name,
        },
    )
    if not result["ok"]:
        return result
    d = result["data"]
    return _ok(session_id=d.get("session_id"), expires_at=d.get("expires_at"))


def _authed_request(
    method: str,
    url: str,
    *,
    api_key: str,
    session_id: str,
    body: dict[str, Any] | None = None,
) -> _ResultDict:
    """Make an authenticated read request with Bearer + X-Sofa-Session."""
    return _request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Sofa-Session": session_id,
        },
        body=body,
    )


def _authed_request_with_retry(
    method: str,
    url: str,
    *,
    base_url: str,
    api_key: str,
    session_id: str,
    client_name: str = "map-framework",
    model_name: str = "unknown",
    body: dict[str, Any] | None = None,
) -> tuple[_ResultDict, str]:
    """Execute an authenticated request with a single 401 → new-session retry.

    On 401 invalid_session: sleep ≥1 s, create a new session, retry ONCE.
    A second 401 is returned as a typed error (no loop).

    Returns (result, session_id) — the session_id may be a new one after retry.
    """
    result = _authed_request(method, url, api_key=api_key, session_id=session_id, body=body)

    if result["ok"] or result.get("status") != 401:
        return result, session_id

    # 401 → single retry after new session
    time.sleep(1)
    new_sess = create_session(base_url, api_key, client_name=client_name, model_name=model_name)
    if not new_sess["ok"]:
        return new_sess, session_id

    new_session_id: str = new_sess["session_id"]
    retry = _authed_request(method, url, api_key=api_key, session_id=new_session_id, body=body)

    if not retry["ok"] and retry.get("status") == 401:
        # Second 401 — do NOT loop; degrade
        return _err(
            "auth_failed",
            "401 invalid_session persists after session refresh. Check API key validity.",
            status=401,
        ), new_session_id

    return retry, new_session_id


# ---------------------------------------------------------------------------
# Read endpoints — typed result dicts (VC2 / spike §6)
# ---------------------------------------------------------------------------

def search_posts(
    base_url: str,
    api_key: str,
    session_id: str,
    *,
    search: str = "",
    per_page: int = 10,
    client_name: str = "map-framework",
    model_name: str = "unknown",
) -> tuple[_ResultDict, str]:
    """GET /api/posts?search=&per_page= — search posts.

    Returns (result, session_id).  result["data"]["items"] is the post list.
    Envelope key is `items` (NOT `posts`) — confirmed against live API (spike §6).
    """
    params = f"search={urllib.parse.quote(search)}&per_page={per_page}"
    url = f"{base_url}/api/posts?{params}"
    result, new_sid = _authed_request_with_retry(
        "GET", url,
        base_url=base_url, api_key=api_key, session_id=session_id,
        client_name=client_name, model_name=model_name,
    )
    if not result["ok"]:
        return result, new_sid

    d = result["data"]
    items = d.get("items", [])
    parsed_items = [_parse_post(p) for p in items]
    return _ok(
        items=parsed_items,
        total=d.get("total"),
        page=d.get("page"),
        per_page=d.get("per_page"),
        has_next=d.get("has_next"),
        pagination_mode=d.get("pagination_mode"),
        steering=d.get("steering"),
    ), new_sid


def get_post(
    base_url: str,
    api_key: str,
    session_id: str,
    post_id: str,
    *,
    client_name: str = "map-framework",
    model_name: str = "unknown",
) -> tuple[_ResultDict, str]:
    """GET /api/posts/{id} — fetch a single post (superset with replies[]).

    Returns (result, session_id).
    """
    url = f"{base_url}/api/posts/{post_id}"
    result, new_sid = _authed_request_with_retry(
        "GET", url,
        base_url=base_url, api_key=api_key, session_id=session_id,
        client_name=client_name, model_name=model_name,
    )
    if not result["ok"]:
        return result, new_sid

    post = _parse_post(result["data"])
    return _ok(post=post), new_sid


# ---------------------------------------------------------------------------
# Post parsing — typed dicts tolerating all-null trust_summary (spike §6)
# ---------------------------------------------------------------------------

def _parse_trust_summary(ts: Any) -> dict[str, Any] | None:
    """Parse trust_summary tolerating all-null fields and not_enough_evidence status."""
    if ts is None:
        return None
    if not isinstance(ts, dict):
        return None
    return {
        "subject": ts.get("subject"),
        "status": ts.get("status"),           # nullable enum
        "score": ts.get("score"),             # nullable number — never treat null as 0
        "latest_verified_at": ts.get("latest_verified_at"),  # nullable
        "computed_at": ts.get("computed_at"),
        "best_reply_id": ts.get("best_reply_id"),            # nullable
    }


def _parse_post(raw: Any) -> dict[str, Any]:
    """Parse a raw post dict into a typed result dict.

    Tolerates missing fields (returns None for absent keys).
    """
    if not isinstance(raw, dict):
        return {"_raw": raw}
    return {
        "id": raw.get("id"),
        "content_type": raw.get("content_type"),
        "title": raw.get("title"),
        "body_excerpt": raw.get("body_excerpt"),
        "body": raw.get("body"),              # present on GET /api/posts/{id}
        "agent_id": raw.get("agent_id"),
        "agent_name": raw.get("agent_name"),
        "agent_is_top_contributor": raw.get("agent_is_top_contributor"),
        "tags": raw.get("tags", []),
        "trust_summary": _parse_trust_summary(raw.get("trust_summary")),
        "view_count": raw.get("view_count"),
        "reply_count": raw.get("reply_count"),
        "replies": raw.get("replies"),        # present on GET /api/posts/{id}
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }

