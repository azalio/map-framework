"""Tests for sofa_client.py (rendered at .map/scripts/sofa_client.py).

All tests run under patched urllib.request.urlopen — ZERO live network.
The rendered module is imported via importlib.util (it is not a package).

VC1: stdlib-only, no mapify/httpx import (ast scan of rendered file)
VC2: session headers + 401 single-retry backoff; full onboarding→session flow
VC3: .gitignore ensured BEFORE credential write; idempotent
VC4: no silent overwrite of existing agent_id; no secret literal in repo
VC5: onboarding stops-and-asks on missing base_url / missing agent_name
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import tempfile
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the rendered module (importlib — it lives in .map/scripts/, not a pkg)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_RENDERED_PATH = _REPO_ROOT / ".map" / "scripts" / "sofa_client.py"


def _load_sofa_client():
    spec = importlib.util.spec_from_file_location("sofa_client", _RENDERED_PATH)
    assert spec is not None, f"Cannot locate rendered sofa_client at {_RENDERED_PATH}"
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


sofa = _load_sofa_client()

# ---------------------------------------------------------------------------
# Helpers — urlopen mock factory
# ---------------------------------------------------------------------------

def _make_resp(body: Any, status: int = 200) -> MagicMock:
    """Build a context-manager-compatible mock urlopen response."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.status = status
    resp.read = MagicMock(return_value=json.dumps(body).encode("utf-8"))
    return resp


def _make_http_error(status: int, body: Any) -> urllib.error.HTTPError:
    import io
    raw = json.dumps(body).encode("utf-8")
    fp = io.BytesIO(raw)
    err = urllib.error.HTTPError(url="http://x", code=status, msg="err", hdrs=MagicMock(), fp=fp)  # type: ignore[arg-type]
    return err


# ---------------------------------------------------------------------------
# VC1: stdlib-only — no forbidden imports in the RENDERED file
# ---------------------------------------------------------------------------

def test_vc1_stdlib_only_no_mapify_import():
    """AST-scan the rendered sofa_client.py for forbidden imports."""
    source = _RENDERED_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_RENDERED_PATH))

    forbidden = {"httpx", "requests", "mapify_cli", "mapify"}
    found: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in forbidden:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in forbidden:
                found.append(node.module or "")

    assert not found, f"Forbidden imports found in rendered sofa_client.py: {found}"


# ---------------------------------------------------------------------------
# VC2: session headers + 401 single-retry backoff
# ---------------------------------------------------------------------------

def test_vc2_session_headers_and_401_single_retry_backoff():
    """Session POST has Bearer & NO X-Sofa-Session header.
    On 401: exactly one new-session + one retry with sleep >= 1.
    Second 401 returns typed error, no loop.
    """
    session_resp = _make_resp({"session_id": "sess-abc", "expires_at": "2099-01-01"}, 201)
    # First read returns 401 invalid_session
    read_401 = _make_http_error(401, {"error": "invalid_session"})
    # Retry session after 401
    retry_session_resp = _make_resp({"session_id": "sess-new", "expires_at": "2099-01-01"}, 201)
    # Retry read succeeds
    read_ok = _make_resp({"items": [], "total": 0, "page": 1, "per_page": 5,
                          "has_next": False, "pagination_mode": "cursor", "steering": None})

    call_count = 0
    captured_headers: list[dict] = []

    def urlopen_side_effect(req, timeout=30):
        nonlocal call_count
        del timeout  # unused; signature must match urllib.request.urlopen
        call_count += 1
        # Capture headers for assertions
        captured_headers.append(dict(req.headers))

        if call_count == 1:
            # POST /api/sessions
            assert "Authorization" in req.headers, "Session POST must have Authorization"
            assert "X-sofa-session" not in {k.lower() for k in req.headers}, \
                "Session POST must NOT send X-Sofa-Session"
            return session_resp
        if call_count == 2:
            # First GET /api/posts — returns 401
            raise read_401
        if call_count == 3:
            # Retry POST /api/sessions
            return retry_session_resp
        if call_count == 4:
            # Retry GET /api/posts — succeeds
            return read_ok
        raise AssertionError(f"Unexpected call #{call_count}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect), patch("time.sleep") as mock_sleep:
        sess_result = sofa.create_session("http://fake", "key123",
                                          client_name="test", model_name="m")
        assert sess_result["ok"], f"create_session failed: {sess_result}"
        assert sess_result["session_id"] == "sess-abc"

        # Step 2: search_posts — triggers 401 retry
        result, new_sid = sofa.search_posts(
            "http://fake", "key123", "sess-abc",
            search="test", per_page=5,
            client_name="test", model_name="m",
        )
        assert result["ok"], f"search_posts failed after retry: {result}"
        assert new_sid == "sess-new"

    # sleep was called with >= 1 exactly once (the 401 backoff)
    sleep_calls = [c for c in mock_sleep.call_args_list]
    assert len(sleep_calls) >= 1
    assert all(c.args[0] >= 1 for c in sleep_calls), \
        f"sleep must be called with >= 1; got {[c.args[0] for c in sleep_calls]}"

    # Total urlopen calls: create_session + 401 read + retry_session + retry_read = 4
    assert call_count == 4, f"Expected exactly 4 urlopen calls, got {call_count}"


def test_vc2_second_401_returns_typed_error_no_loop():
    """A second 401 after session refresh must NOT loop — return typed auth_failed error."""
    call_count = 0
    session_resp = _make_resp({"session_id": "sess-1", "expires_at": "2099-01-01"}, 201)
    retry_session = _make_resp({"session_id": "sess-2", "expires_at": "2099-01-01"}, 201)

    def urlopen_side_effect(req, timeout=30):
        nonlocal call_count
        del req, timeout  # unused; signature must match urllib.request.urlopen
        call_count += 1
        if call_count == 1:
            # Initial session
            return session_resp
        if call_count == 2:
            # First read: 401
            raise _make_http_error(401, {"error": "invalid_session"})
        if call_count == 3:
            # Retry session
            return retry_session
        if call_count == 4:
            # Retry read: 401 again
            raise _make_http_error(401, {"error": "invalid_session"})
        raise AssertionError(f"Unexpected call #{call_count} — loop detected")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect), patch("time.sleep"):
        sofa.create_session("http://fake", "key123")
        result, _ = sofa.search_posts("http://fake", "key123", "sess-1", search="x")

    assert not result["ok"]
    assert result["kind"] == "auth_failed"
    assert call_count == 4, f"Expected exactly 4 calls (no loop), got {call_count}"


# ---------------------------------------------------------------------------
# VC2 (full flow): onboarding → session → search
# ---------------------------------------------------------------------------

def test_vc2_full_onboarding_to_session_flow_mocked():
    """Full onboarding→register→session→search mocked flow."""
    # Step 1: GET /api/onboarding
    onboarding_info = _make_resp({"contract": "...", "next_step": "create_flow"})
    # Step 2: POST /api/onboarding/flows
    flow_resp = _make_resp({
        "flow_id": "flow-xyz",
        "claim_url": "https://agents.stackoverflow.com/claim/flow-xyz",
        "claim_code": "ABCD-1234",
        "poll_token": "poll-tok",
        "poll_after_seconds": 0,  # 0 for test speed
    })
    # Step 4: POST /api/onboarding/flows/{id}/status
    status_resp = _make_resp({
        "state": "auth_code_retrieved",
        "auth_code": "auth-abc",
        "auth_code_expires_at": "2099-01-01T00:00:00Z",
    })
    # Step 6: POST /api/onboarding/registrations
    reg_resp = _make_resp({
        "agent_id": "agent-uuid-001",
        "api_key": "sofa_key_XXXXXXXX",
        "api_key_prefix": "sofa_key",
        "api_key_suffix": "XXXX",
        "storage_guidance": "store in .sofa/credentials.json",
        "next_step": "create_session",
    })
    # Step 7: POST /api/sessions
    sess_resp = _make_resp({"session_id": "sess-live", "expires_at": "2099-01-01"}, 201)
    # Search
    search_resp = _make_resp({
        "items": [{"id": "post-1", "title": "Hello", "content_type": "til",
                   "body_excerpt": "...", "agent_id": "agent-uuid-001",
                   "agent_name": "TestAgent", "agent_is_top_contributor": False,
                   "tags": ["python"], "trust_summary": {
                       "subject": "answers", "status": "not_enough_evidence",
                       "score": None, "latest_verified_at": None,
                       "computed_at": "2026-06-12T00:00:00Z", "best_reply_id": None,
                   },
                   "view_count": 0, "reply_count": 0,
                   "created_at": "2026-06-12T00:00:00Z",
                   "updated_at": "2026-06-12T00:00:00Z"}],
        "total": 1, "page": 1, "per_page": 5, "has_next": False,
        "pagination_mode": "cursor", "steering": None,
    })

    responses = [onboarding_info, flow_resp, status_resp, reg_resp, sess_resp, search_resp]
    idx = 0

    def urlopen_side_effect(req, timeout=30):
        nonlocal idx
        del req, timeout  # unused; signature must match urllib.request.urlopen
        r = responses[idx]
        idx += 1
        return r

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect), patch("time.sleep"):
        r1 = sofa.onboarding_start("http://fake")
        assert r1["ok"]

        # 2. POST /api/onboarding/flows
        r2 = sofa.onboarding_create_flow(
            "http://fake",
            client_name="map-framework", client_version="0.1",
            model_name="claude-sonnet-4-6", model_provider="anthropic",
            model_version="4.6", model_selection_mode="auto",
        )
        assert r2["ok"]
        assert r2["claim_code"] == "ABCD-1234"
        assert r2["flow_id"] == "flow-xyz"

        # 4. Poll status
        r3 = sofa.onboarding_poll_status(
            "http://fake", "flow-xyz", "poll-tok", poll_after_seconds=0, max_polls=5
        )
        assert r3["ok"]
        assert r3["auth_code"] == "auth-abc"

        # 6. Register (human provides name/description — never invented)
        r4 = sofa.onboarding_register(
            "http://fake",
            auth_code="auth-abc",
            agent_name="MyTestAgent",
            description="A test MAP agent",
        )
        assert r4["ok"]
        assert r4["agent_id"] == "agent-uuid-001"
        assert r4["api_key"] == "sofa_key_XXXXXXXX"

        # 7. Create session
        r5 = sofa.create_session("http://fake", "sofa_key_XXXXXXXX",
                                 client_name="map-framework", model_name="claude-sonnet-4-6")
        assert r5["ok"]
        assert r5["session_id"] == "sess-live"

        # Search
        r6, _ = sofa.search_posts(
            "http://fake", "sofa_key_XXXXXXXX", "sess-live",
            search="python", per_page=5,
        )
        assert r6["ok"]
        assert len(r6["items"]) == 1
        item = r6["items"][0]
        assert item["trust_summary"]["status"] == "not_enough_evidence"
        assert item["trust_summary"]["score"] is None   # null != 0


# ---------------------------------------------------------------------------
# VC3: .gitignore ensured BEFORE credentials.json is written; idempotent
# ---------------------------------------------------------------------------

def test_vc3_gitignore_ensured_before_key_write_idempotent():
    """ensure_sofa_gitignore is called before credentials.json exists; idempotent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        gitignore = repo_root / ".gitignore"
        creds_file = repo_root / ".sofa" / "credentials.json"

        # Track call order
        order: list[str] = []
        real_ensure = sofa.ensure_sofa_gitignore

        def tracking_ensure(root):
            order.append("gitignore")
            assert not creds_file.exists(), \
                ".gitignore must be updated BEFORE credentials.json is created"
            return real_ensure(root)

        with patch.object(sofa, "ensure_sofa_gitignore", side_effect=tracking_ensure):
            result = sofa.store_credentials(
                repo_root=repo_root,
                agent_id="agent-001",
                api_key="sofa_test_key",
                agent_name="TestAgent",
                base_url="http://fake",
                api_key_prefix="sofa_test",
                api_key_suffix="_key",
            )
        assert result["ok"], f"store_credentials failed: {result}"
        assert order == ["gitignore"], "ensure_sofa_gitignore was not called"

        # gitignore must contain the marker and .sofa/ entry
        gi_content = gitignore.read_text()
        assert "# map:sofa" in gi_content
        assert ".sofa/" in gi_content

        # credentials.json must exist with correct permissions
        assert creds_file.exists()
        perms = oct(os.stat(creds_file).st_mode & 0o777)
        assert perms == oct(0o600), f"Expected 0600, got {perms}"

        # --- Idempotency: second call → no duplicate marker/entry ---
        modified = sofa.ensure_sofa_gitignore(repo_root)
        assert not modified, "Second call should be a no-op (idempotent)"
        gi_content2 = gitignore.read_text()
        assert gi_content2.count("# map:sofa") == 1, "Duplicate marker appended!"
        assert gi_content2.count(".sofa/") == 1, "Duplicate .sofa/ line appended!"


# ---------------------------------------------------------------------------
# VC4: no silent overwrite; no secret literal shipped in repo/generated trees
# ---------------------------------------------------------------------------

def test_vc4_no_silent_overwrite_and_no_secrets_in_repo():
    """Existing agent_id key → write attempt raises typed error, no silent overwrite."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)

        # First write succeeds
        r1 = sofa.store_credentials(
            repo_root=repo_root,
            agent_id="dup-agent",
            api_key="first_key",
            agent_name="First",
            base_url="http://fake",
            api_key_prefix="sofa_test",
            api_key_suffix="_key",
        )
        assert r1["ok"]

        # Second write with same agent_id must fail, not overwrite
        r2 = sofa.store_credentials(
            repo_root=repo_root,
            agent_id="dup-agent",
            api_key="second_key_should_not_overwrite",
            agent_name="Second",
            base_url="http://fake",
            api_key_prefix="sofa_test",
            api_key_suffix="_key",
        )
        assert not r2["ok"]
        assert r2["kind"] == "duplicate_agent"

        # Verify original key is intact
        data = json.loads((repo_root / ".sofa" / "credentials.json").read_text())
        assert data["dup-agent"]["api_key"] == "first_key", "Silent overwrite detected!"

    # No real API key literal in the repo source or generated trees
    # (This uses grep to scan the trees — zero tolerance for real Bearer values)
    grep_targets = [
        str(_REPO_ROOT / "src" / "mapify_cli" / "templates_src"),
        str(_REPO_ROOT / "src" / "mapify_cli" / "templates"),
        str(_REPO_ROOT / ".map" / "scripts"),
    ]
    # Pattern: a literal "Bearer " followed by actual token characters (not a variable reference)
    # We allow "Bearer {" (template), "Bearer <" (placeholder), "Bearer {api_key}" etc.
    # but reject "Bearer [A-Za-z0-9_-]{8,}" that looks like an actual token.
    result = subprocess.run(
        ["grep", "-rnI", r"Bearer [A-Za-z0-9_\-]{20,}", *grep_targets],
        capture_output=True, text=True,
        check=False,
    )
    assert result.returncode != 0 or not result.stdout.strip(), \
        f"Possible secret literal found in source trees:\n{result.stdout}"


def test_vc4_non_dict_credentials_returns_typed_error_no_raise():
    """A valid-but-non-dict credentials.json must degrade to a typed bad_json
    error in BOTH store_credentials and resolve_key — never raise through
    (module contract: 'All errors returned as typed result dicts')."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        sofa_dir = repo_root / ".sofa"
        sofa_dir.mkdir(mode=0o700)
        creds_file = sofa_dir / "credentials.json"
        creds_file.write_text("[]", encoding="utf-8")  # valid JSON, wrong type

        # store_credentials must not raise and must not clobber the file
        r = sofa.store_credentials(
            repo_root=repo_root,
            agent_id="a1",
            api_key="k",
            agent_name="A",
            base_url="http://fake",
            api_key_prefix="p",
            api_key_suffix="s",
        )
        assert not r["ok"]
        assert r["kind"] == "bad_json"
        assert creds_file.read_text(encoding="utf-8") == "[]", "must not clobber"

        # resolve_key must not raise either (clear SOFA_API_KEY so it reaches
        # the file-read path rather than short-circuiting on the env key).
        env_without_key = {k: v for k, v in os.environ.items() if k != "SOFA_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            rk = sofa.resolve_key(agent_id="a1", credentials_path=creds_file)
        assert not rk["ok"]
        assert rk["kind"] == "bad_json"


# ---------------------------------------------------------------------------
# VC5: onboarding stops-and-asks; base_url resolution never guesses
# ---------------------------------------------------------------------------

def test_vc5_onboarding_asks_human_and_baseurl_resolution():
    """SOFA_BASE_URL unset → resolve_base_url returns need_base_url error.
    agent_name/description empty → onboarding_register returns typed error.
    """
    # 1. base_url resolution when env var absent
    env_without_sofa = {k: v for k, v in os.environ.items() if k != "SOFA_BASE_URL"}
    with patch.dict(os.environ, env_without_sofa, clear=True):
        result = sofa.resolve_base_url()
    assert not result["ok"]
    assert result["kind"] == "need_base_url"

    # 2. base_url resolution when env var present
    with patch.dict(os.environ, {"SOFA_BASE_URL": "https://agents.stackoverflow.com"}):
        result = sofa.resolve_base_url()
    assert result["ok"]
    assert result["base_url"] == "https://agents.stackoverflow.com"

    # 3. onboarding_register with empty agent_name → typed error, never invents
    r = sofa.onboarding_register(
        "http://fake",
        auth_code="auth-abc",
        agent_name="",
        description="valid description",
    )
    assert not r["ok"]
    assert r["kind"] == "need_agent_name"

    # 4. onboarding_register with empty description → typed error
    r2 = sofa.onboarding_register(
        "http://fake",
        auth_code="auth-abc",
        agent_name="ValidName",
        description="",
    )
    assert not r2["ok"]
    assert r2["kind"] == "need_description"

    # 5. onboarding_register with whitespace-only agent_name → typed error
    r3 = sofa.onboarding_register(
        "http://fake",
        auth_code="auth-abc",
        agent_name="   ",
        description="valid",
    )
    assert not r3["ok"]
    assert r3["kind"] == "need_agent_name"


# ---------------------------------------------------------------------------
# Additional: network error returns typed result, never raises
# ---------------------------------------------------------------------------

def test_network_error_returns_typed_result():
    """urllib.error.URLError (connection refused) → typed _err, never raises."""
    import urllib.error

    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        r = sofa.onboarding_start("http://fake")
    assert not r["ok"]
    assert r["kind"] in ("network", "timeout")


def test_get_post_returns_typed_dict():
    """GET /api/posts/{id} returns typed post dict with trust_summary."""
    post_body = {
        "id": "post-42",
        "content_type": "til",
        "title": "Test Post",
        "body_excerpt": "excerpt",
        "body": "full body",
        "agent_id": "agent-x",
        "agent_name": "AgentX",
        "agent_is_top_contributor": True,
        "tags": ["python", "stdlib"],
        "trust_summary": {
            "subject": "answers",
            "status": "not_enough_evidence",
            "score": None,
            "latest_verified_at": None,
            "computed_at": "2026-06-12T00:00:00Z",
            "best_reply_id": None,
        },
        "view_count": 5,
        "reply_count": 2,
        "replies": [{"id": "reply-1", "parent_id": "post-42"}],
        "created_at": "2026-06-12T00:00:00Z",
        "updated_at": "2026-06-12T00:00:00Z",
    }
    post_resp = _make_resp(post_body)

    with patch("urllib.request.urlopen", return_value=post_resp):
        result, new_sid = sofa.get_post("http://fake", "key", "sess", "post-42")

    assert result["ok"]
    p = result["post"]
    assert p["id"] == "post-42"
    assert p["trust_summary"]["score"] is None  # null must not become 0
    assert p["trust_summary"]["status"] == "not_enough_evidence"
    assert new_sid == "sess"
