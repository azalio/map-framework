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
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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

_SAFE_SOFA_GITIGNORE = "# map:sofa\n.sofa/\n"

_CONCURRENCY_WORKER = r"""from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

operation = sys.argv[1]
project = Path(sys.argv[2])
sofa_source = Path(sys.argv[3])
attempted = Path(sys.argv[4])
ready = Path(sys.argv[5])
release = Path(sys.argv[6])
done = Path(sys.argv[7])
pause = sys.argv[8] == "1"
agent_id = sys.argv[9]


def load_sofa():
    spec = importlib.util.spec_from_file_location("worker_sofa_client", sofa_source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pause_after_read(module, attribute: str) -> None:
    original = getattr(module, attribute)

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        ready.write_text("ready", encoding="utf-8")
        deadline = time.monotonic() + 10
        while not release.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("release marker was not created")
            time.sleep(0.01)
        return result

    setattr(module, attribute, wrapped)


attempted.write_text("attempted", encoding="utf-8")
if operation == "gitignore-cli":
    from mapify_cli.delivery import file_copier

    if pause:
        pause_after_read(file_copier, "_read_safe_gitignore")
    changed = file_copier.merge_update_runtime_gitignore(project)
    result = {"changed": changed}
elif operation == "gitignore-sofa":
    sofa = load_sofa()
    if pause:
        pause_after_read(sofa, "_read_safe_gitignore")
    changed = sofa.ensure_sofa_gitignore(project)
    result = {"changed": changed}
elif operation == "credential":
    sofa = load_sofa()
    if pause:
        pause_after_read(sofa, "_read_credentials_bytes")
    result = sofa.store_credentials(
        repo_root=project,
        agent_id=agent_id,
        api_key=f"secret-{agent_id}",
        agent_name=f"Agent {agent_id}",
        base_url="https://sofa.invalid",
        api_key_prefix="secret",
        api_key_suffix=agent_id,
    )
else:
    raise AssertionError(operation)

done.write_text(json.dumps(result), encoding="utf-8")
"""

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


def _store_test_credentials(
    repo_root: Path,
    *,
    api_key: str = "sofa_test_private_key",
    agent_id: str = "agent-test",
):
    return sofa.store_credentials(
        repo_root=repo_root,
        agent_id=agent_id,
        api_key=api_key,
        agent_name="Test Agent",
        base_url="http://fake",
        api_key_prefix="sofa_test",
        api_key_suffix="key",
    )


def _wait_for_path(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _start_concurrency_worker(
    tmp_path: Path,
    *,
    name: str,
    operation: str,
    project: Path,
    pause: bool,
    agent_id: str = "agent",
    temp_dir: Path | None = None,
) -> tuple[subprocess.Popen[str], Path, Path, Path, Path]:
    script = tmp_path / "concurrency-worker.py"
    script.write_text(_CONCURRENCY_WORKER, encoding="utf-8")
    attempted = tmp_path / f"{name}.attempted"
    ready = tmp_path / f"{name}.ready"
    release = tmp_path / f"{name}.release"
    done = tmp_path / f"{name}.done"
    worker_env = None
    if temp_dir is not None:
        temp_dir.mkdir()
        worker_env = {**os.environ, "TMPDIR": str(temp_dir), "TMP": str(temp_dir)}
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            operation,
            str(project),
            str(_RENDERED_PATH),
            str(attempted),
            str(ready),
            str(release),
            str(done),
            "1" if pause else "0",
            agent_id,
        ],
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=worker_env,
    )
    return process, attempted, ready, release, done


def _finish_worker(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(f"concurrency worker timed out: {stdout}\n{stderr}")
    assert process.returncode == 0, f"worker failed: {stdout}\n{stderr}"
    return stdout, stderr


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
    session_resp = _make_resp(
        {"session_id": "sess-abc", "expires_at": "2099-01-01"}, 201
    )
    # First read returns 401 invalid_session
    read_401 = _make_http_error(401, {"error": "invalid_session"})
    # Retry session after 401
    retry_session_resp = _make_resp(
        {"session_id": "sess-new", "expires_at": "2099-01-01"}, 201
    )
    # Retry read succeeds
    read_ok = _make_resp(
        {
            "items": [],
            "total": 0,
            "page": 1,
            "per_page": 5,
            "has_next": False,
            "pagination_mode": "cursor",
            "steering": None,
        }
    )

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
            assert (
                "Authorization" in req.headers
            ), "Session POST must have Authorization"
            assert "X-sofa-session" not in {
                k.lower() for k in req.headers
            }, "Session POST must NOT send X-Sofa-Session"
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

    with (
        patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
        patch("time.sleep") as mock_sleep,
    ):
        sess_result = sofa.create_session(
            "http://fake", "key123", client_name="test", model_name="m"
        )
        assert sess_result["ok"], f"create_session failed: {sess_result}"
        assert sess_result["session_id"] == "sess-abc"

        # Step 2: search_posts — triggers 401 retry
        result, new_sid = sofa.search_posts(
            "http://fake",
            "key123",
            "sess-abc",
            search="test",
            per_page=5,
            client_name="test",
            model_name="m",
        )
        assert result["ok"], f"search_posts failed after retry: {result}"
        assert new_sid == "sess-new"

    # sleep was called with >= 1 exactly once (the 401 backoff)
    sleep_calls = [c for c in mock_sleep.call_args_list]
    assert len(sleep_calls) >= 1
    assert all(
        c.args[0] >= 1 for c in sleep_calls
    ), f"sleep must be called with >= 1; got {[c.args[0] for c in sleep_calls]}"

    # Total urlopen calls: create_session + 401 read + retry_session + retry_read = 4
    assert call_count == 4, f"Expected exactly 4 urlopen calls, got {call_count}"


def test_vc2_second_401_returns_typed_error_no_loop():
    """A second 401 after session refresh must NOT loop — return typed auth_failed error."""
    call_count = 0
    session_resp = _make_resp({"session_id": "sess-1", "expires_at": "2099-01-01"}, 201)
    retry_session = _make_resp(
        {"session_id": "sess-2", "expires_at": "2099-01-01"}, 201
    )

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

    with (
        patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
        patch("time.sleep"),
    ):
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
    flow_resp = _make_resp(
        {
            "flow_id": "flow-xyz",
            "claim_url": "https://agents.stackoverflow.com/claim/flow-xyz",
            "claim_code": "ABCD-1234",
            "poll_token": "poll-tok",
            "poll_after_seconds": 0,  # 0 for test speed
        }
    )
    # Step 4: POST /api/onboarding/flows/{id}/status
    status_resp = _make_resp(
        {
            "state": "auth_code_retrieved",
            "auth_code": "auth-abc",
            "auth_code_expires_at": "2099-01-01T00:00:00Z",
        }
    )
    # Step 6: POST /api/onboarding/registrations
    reg_resp = _make_resp(
        {
            "agent_id": "agent-uuid-001",
            "api_key": "sofa_key_XXXXXXXX",
            "api_key_prefix": "sofa_key",
            "api_key_suffix": "XXXX",
            "storage_guidance": "store in .sofa/credentials.json",
            "next_step": "create_session",
        }
    )
    # Step 7: POST /api/sessions
    sess_resp = _make_resp({"session_id": "sess-live", "expires_at": "2099-01-01"}, 201)
    # Search
    search_resp = _make_resp(
        {
            "items": [
                {
                    "id": "post-1",
                    "title": "Hello",
                    "content_type": "til",
                    "body_excerpt": "...",
                    "agent_id": "agent-uuid-001",
                    "agent_name": "TestAgent",
                    "agent_is_top_contributor": False,
                    "tags": ["python"],
                    "trust_summary": {
                        "subject": "answers",
                        "status": "not_enough_evidence",
                        "score": None,
                        "latest_verified_at": None,
                        "computed_at": "2026-06-12T00:00:00Z",
                        "best_reply_id": None,
                    },
                    "view_count": 0,
                    "reply_count": 0,
                    "created_at": "2026-06-12T00:00:00Z",
                    "updated_at": "2026-06-12T00:00:00Z",
                }
            ],
            "total": 1,
            "page": 1,
            "per_page": 5,
            "has_next": False,
            "pagination_mode": "cursor",
            "steering": None,
        }
    )

    responses = [
        onboarding_info,
        flow_resp,
        status_resp,
        reg_resp,
        sess_resp,
        search_resp,
    ]
    idx = 0

    def urlopen_side_effect(req, timeout=30):
        nonlocal idx
        del req, timeout  # unused; signature must match urllib.request.urlopen
        r = responses[idx]
        idx += 1
        return r

    with (
        patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
        patch("time.sleep"),
    ):
        r1 = sofa.onboarding_start("http://fake")
        assert r1["ok"]

        # 2. POST /api/onboarding/flows
        r2 = sofa.onboarding_create_flow(
            "http://fake",
            client_name="map-framework",
            client_version="0.1",
            model_name="claude-sonnet-4-6",
            model_provider="anthropic",
            model_version="4.6",
            model_selection_mode="auto",
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
        r5 = sofa.create_session(
            "http://fake",
            "sofa_key_XXXXXXXX",
            client_name="map-framework",
            model_name="claude-sonnet-4-6",
        )
        assert r5["ok"]
        assert r5["session_id"] == "sess-live"

        # Search
        r6, _ = sofa.search_posts(
            "http://fake",
            "sofa_key_XXXXXXXX",
            "sess-live",
            search="python",
            per_page=5,
        )
        assert r6["ok"]
        assert len(r6["items"]) == 1
        item = r6["items"][0]
        assert item["trust_summary"]["status"] == "not_enough_evidence"
        assert item["trust_summary"]["score"] is None  # null != 0


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
        real_ensure = sofa._ensure_sofa_gitignore_locked

        def tracking_ensure(
            root: Path,
            directory_fd: int | None,
            project_original: os.stat_result,
        ) -> bool:
            order.append("gitignore")
            assert (
                not creds_file.exists()
            ), ".gitignore must be updated BEFORE credentials.json is created"
            return real_ensure(root, directory_fd, project_original)

        with patch.object(
            sofa, "_ensure_sofa_gitignore_locked", side_effect=tracking_ensure
        ):
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


@pytest.mark.parametrize(
    "original",
    [
        "# map:sofa\n",
        "# map:sofa\n.sofa/\n!.sofa/\n",
        "# map:sofa\n.sofa/\n!.sofa/**\n",
        "# map:sofa\n.sofa/\n!unrelated/**\n",
        "user-rule/\n  .sofa/\n",
    ],
)
def test_vc3_repairs_marker_only_leading_space_and_later_negations(
    tmp_path: Path,
    original: str,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(original, encoding="utf-8")
    gitignore.chmod(0o640)

    assert sofa.ensure_sofa_gitignore(tmp_path) is True
    repaired = gitignore.read_text(encoding="utf-8")
    repaired_lines = repaired.splitlines()

    assert repaired.startswith(original)
    assert sum(line.startswith("# map:sofa") for line in repaired_lines) == 1
    assert repaired_lines.count(".sofa/") == original.splitlines().count(".sofa/") + 1
    negation_indexes = [
        index for index, line in enumerate(repaired_lines) if line.startswith("!")
    ]
    if negation_indexes:
        assert max(
            index for index, line in enumerate(repaired_lines) if line == ".sofa/"
        ) > max(negation_indexes)
    assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640

    assert sofa.ensure_sofa_gitignore(tmp_path) is False
    assert gitignore.read_text(encoding="utf-8") == repaired


def test_vc3_secure_merge_preserves_readonly_mode_and_content(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX read-only mode contract")
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"user-rule/\n")
    gitignore.chmod(0o444)

    assert sofa.ensure_sofa_gitignore(tmp_path) is True

    assert gitignore.read_bytes().startswith(b"user-rule/\n")
    assert b".sofa/\n" in gitignore.read_bytes()
    assert stat.S_IMODE(gitignore.stat().st_mode) == 0o444


@pytest.mark.parametrize("attack", ["symlink", "hardlink"])
def test_vc3_secure_merge_rejects_linked_gitignore(
    tmp_path: Path,
    attack: str,
) -> None:
    if attack == "hardlink" and os.name == "nt":
        pytest.skip("POSIX hardlink security contract")
    outside = tmp_path / "outside-gitignore"
    outside.write_bytes(b"outside-sentinel\n")
    outside.chmod(0o640)
    gitignore = tmp_path / ".gitignore"
    if attack == "symlink":
        gitignore.symlink_to(outside)
    else:
        try:
            os.link(outside, gitignore)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"hardlinks unavailable: {exc}")

    with pytest.raises(sofa.SofaGitignoreSecurityError):
        sofa.ensure_sofa_gitignore(tmp_path)

    assert outside.read_bytes() == b"outside-sentinel\n"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o640


def test_vc3_secure_merge_rejects_nonregular_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").mkdir()

    with pytest.raises(sofa.SofaGitignoreSecurityError):
        sofa.ensure_sofa_gitignore(tmp_path)

    assert (tmp_path / ".gitignore").is_dir()


def test_vc3_cli_and_standalone_share_private_persistent_lock(tmp_path: Path) -> None:
    from mapify_cli.delivery import file_copier

    if os.name == "nt":
        pytest.skip("Windows uses a named mutex with no lock file")
    project_root = tmp_path.resolve(strict=True)
    assert sofa._gitignore_lock_path(project_root) == file_copier._gitignore_lock_path(
        project_root
    )

    assert sofa.ensure_sofa_gitignore(project_root) is True

    lock_path = sofa._gitignore_lock_path(project_root)
    lock_stat = os.lstat(lock_path)
    assert stat.S_ISREG(lock_stat.st_mode)
    assert lock_stat.st_nlink == 1
    if os.name != "nt":
        assert stat.S_IMODE(lock_stat.st_mode) == 0o600


def test_vc3_cli_and_standalone_share_windows_mutex_identity(tmp_path: Path) -> None:
    from mapify_cli.delivery import file_copier

    project_stat = os.stat(tmp_path, follow_symlinks=False)
    name = sofa._windows_gitignore_mutex_name(project_stat)
    assert name == file_copier._windows_gitignore_mutex_name(project_stat)
    assert name.startswith("Global\\MapifyGitignore-")


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    [
        (0o666, 0o600, True),
        (0o444, 0o400, True),
        (0o444, 0o600, False),
    ],
)
def test_vc3_descriptor_mode_checks_preserve_windows_readonly_semantics(
    monkeypatch: pytest.MonkeyPatch,
    actual: int,
    expected: int,
    matches: bool,
) -> None:
    from mapify_cli.delivery import file_copier

    opened = os.stat_result((stat.S_IFREG | actual, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(file_copier.os, "name", "nt")
    monkeypatch.setattr(file_copier.os, "fstat", lambda _descriptor: opened)

    assert file_copier._descriptor_mode_matches(17, expected) is matches
    assert sofa._descriptor_mode_matches(17, expected) is matches


def test_vc3_windows_failure_never_leaves_unignored_project_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mapify_cli.delivery import file_copier

    @contextmanager
    def fake_mutex(_project_stat: os.stat_result):
        yield

    monkeypatch.setattr(file_copier, "_uses_windows_gitignore_mutex", lambda: True)
    monkeypatch.setattr(file_copier, "_windows_project_gitignore_mutex", fake_mutex)

    with (
        patch.object(file_copier.os, "replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        file_copier.merge_update_runtime_gitignore(tmp_path)

    assert not (tmp_path / ".map-gitignore.lock").exists()


@pytest.mark.parametrize("writer", ["cli", "standalone"])
@pytest.mark.parametrize("replacement_kind", ["directory", "outside-symlink"])
def test_vc3_project_root_swap_cannot_mutate_replacement_or_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    replacement_kind: str,
) -> None:
    from mapify_cli.delivery import file_copier

    project = tmp_path / "project"
    project.mkdir()
    moved_project = tmp_path / "moved-project"
    outside = tmp_path / "outside-project"
    outside.mkdir()
    outside_sentinel = outside / "sentinel"
    outside_sentinel.write_bytes(b"outside-sentinel\n")

    if writer == "cli":
        module = file_copier
        operation = lambda: file_copier.merge_update_runtime_gitignore(project)
        error = file_copier.UpdateRuntimeGitignoreSecurityError
    else:
        module = sofa
        operation = lambda: sofa.ensure_sofa_gitignore(project)
        error = sofa.SofaGitignoreSecurityError

    real_read = module._read_safe_gitignore

    def read_then_swap(path: Path, directory_fd: int | None):
        result = real_read(path, directory_fd)
        project.rename(moved_project)
        if replacement_kind == "directory":
            project.mkdir()
        else:
            project.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(module, "_read_safe_gitignore", read_then_swap)

    with pytest.raises(error):
        operation()

    assert not (project / ".gitignore").exists()
    assert not (moved_project / ".gitignore").exists()
    assert not (outside / ".gitignore").exists()
    assert outside_sentinel.read_bytes() == b"outside-sentinel\n"


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_platform_without_project_dir_fd_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    if writer == "cli":
        monkeypatch.setattr(file_copier, "_CAN_USE_PROJECT_DIRECTORY_FD", False)
        operation = lambda: file_copier.merge_update_runtime_gitignore(tmp_path)
        error = file_copier.UpdateRuntimeGitignoreSecurityError
    else:
        monkeypatch.setattr(sofa, "_CAN_USE_PROJECT_DIRECTORY_FD", False)
        operation = lambda: sofa.ensure_sofa_gitignore(tmp_path)
        error = sofa.SofaGitignoreSecurityError

    with pytest.raises(error, match="cannot pin project-relative"):
        operation()

    assert not (tmp_path / ".gitignore").exists()


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_windows_mutex_timeout_is_bounded_and_closes_handle(
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    error = (
        file_copier.UpdateRuntimeGitignoreSecurityError
        if writer == "cli"
        else sofa.SofaGitignoreSecurityError
    )
    create_mutex = MagicMock(return_value=17)
    wait_for_single_object = MagicMock(return_value=0x00000102)
    release_mutex = MagicMock(return_value=True)
    close_handle = MagicMock(return_value=True)
    kernel32 = MagicMock(
        CreateMutexW=create_mutex,
        WaitForSingleObject=wait_for_single_object,
        ReleaseMutex=release_mutex,
        CloseHandle=close_handle,
    )
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32
    fake_ctypes.get_last_error.return_value = 1460
    fake_wintypes = MagicMock()
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_stat = os.stat_result((stat.S_IFDIR | 0o755, 1, 2, 1, 0, 0, 0, 0, 0, 0))

    with (
        pytest.raises(error, match="timed out"),
        module._windows_project_gitignore_mutex(project_stat),
    ):
        pytest.fail("a timed-out mutex must not enter the transaction")

    wait_for_single_object.assert_called_once_with(
        17, module._WINDOWS_GITIGNORE_MUTEX_TIMEOUT_MS
    )
    release_mutex.assert_not_called()
    close_handle.assert_called_once_with(17)


@pytest.mark.parametrize("writer", ["cli", "standalone"])
@pytest.mark.parametrize("wait_result", [0x00000000, 0x00000080])
def test_vc3_windows_mutex_success_and_abandonment_release_and_close(
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    wait_result: int,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    create_mutex = MagicMock(return_value=23)
    wait_for_single_object = MagicMock(return_value=wait_result)
    release_mutex = MagicMock(return_value=True)
    close_handle = MagicMock(return_value=True)
    kernel32 = MagicMock(
        CreateMutexW=create_mutex,
        WaitForSingleObject=wait_for_single_object,
        ReleaseMutex=release_mutex,
        CloseHandle=close_handle,
    )
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32
    fake_wintypes = MagicMock()
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_stat = os.stat_result((stat.S_IFDIR | 0o755, 1, 2, 1, 0, 0, 0, 0, 0, 0))

    with module._windows_project_gitignore_mutex(project_stat):
        pass

    wait_for_single_object.assert_called_once_with(
        23, module._WINDOWS_GITIGNORE_MUTEX_TIMEOUT_MS
    )
    release_mutex.assert_called_once_with(23)
    close_handle.assert_called_once_with(23)


@pytest.mark.parametrize("writer", ["cli", "standalone"])
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("wait", "WaitForSingleObject failed (WinError 111)"),
        ("release", "ReleaseMutex failed (WinError 222)"),
        ("close", "CloseHandle failed (WinError 333)"),
    ],
)
def test_vc3_windows_mutex_failures_capture_error_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    failure: str,
    expected: str,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    error = (
        file_copier.UpdateRuntimeGitignoreSecurityError
        if writer == "cli"
        else sofa.SofaGitignoreSecurityError
    )
    create_mutex = MagicMock(return_value=29)
    wait_for_single_object = MagicMock(
        return_value=0xFFFFFFFF if failure == "wait" else 0x00000000
    )
    release_mutex = MagicMock(return_value=failure != "release")
    close_handle = MagicMock(return_value=failure != "close")
    kernel32 = MagicMock(
        CreateMutexW=create_mutex,
        WaitForSingleObject=wait_for_single_object,
        ReleaseMutex=release_mutex,
        CloseHandle=close_handle,
    )
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32
    fake_ctypes.get_last_error.return_value = {
        "wait": 111,
        "release": 222,
        "close": 333,
    }[failure]
    fake_wintypes = MagicMock()
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_stat = os.stat_result((stat.S_IFDIR | 0o755, 1, 2, 1, 0, 0, 0, 0, 0, 0))

    with (
        pytest.raises(error, match=re.escape(expected)),
        module._windows_project_gitignore_mutex(project_stat),
    ):
        if failure == "wait":
            pytest.fail("a failed wait must not enter the transaction")

    if failure == "wait":
        release_mutex.assert_not_called()
    else:
        release_mutex.assert_called_once_with(29)
    close_handle.assert_called_once_with(29)


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_windows_mutex_create_failure_refuses_session_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    error = (
        file_copier.UpdateRuntimeGitignoreSecurityError
        if writer == "cli"
        else sofa.SofaGitignoreSecurityError
    )
    create_mutex = MagicMock(return_value=0)
    wait_for_single_object = MagicMock()
    release_mutex = MagicMock()
    close_handle = MagicMock()
    kernel32 = MagicMock(
        CreateMutexW=create_mutex,
        WaitForSingleObject=wait_for_single_object,
        ReleaseMutex=release_mutex,
        CloseHandle=close_handle,
    )
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32
    fake_ctypes.get_last_error.return_value = 5
    fake_wintypes = MagicMock()
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_stat = os.stat_result((stat.S_IFDIR | 0o755, 1, 2, 1, 0, 0, 0, 0, 0, 0))

    with (
        pytest.raises(error, match="refusing a session-local fallback"),
        module._windows_project_gitignore_mutex(project_stat),
    ):
        pytest.fail("a missing global mutex must fail closed")

    wait_for_single_object.assert_not_called()
    release_mutex.assert_not_called()
    close_handle.assert_not_called()


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_windows_mutex_reports_release_and_close_failures_in_order(
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    error = (
        file_copier.UpdateRuntimeGitignoreSecurityError
        if writer == "cli"
        else sofa.SofaGitignoreSecurityError
    )
    kernel32 = MagicMock()
    kernel32.CreateMutexW.return_value = 37
    kernel32.WaitForSingleObject.return_value = 0x00000000
    kernel32.ReleaseMutex.return_value = False
    kernel32.CloseHandle.return_value = False
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32
    fake_ctypes.get_last_error.side_effect = [222, 333]
    fake_wintypes = MagicMock()
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_stat = os.stat_result((stat.S_IFDIR | 0o755, 1, 2, 1, 0, 0, 0, 0, 0, 0))

    with (
        pytest.raises(
            error,
            match=(
                "ReleaseMutex failed \\(WinError 222\\); "
                "CloseHandle failed \\(WinError 333\\)"
            ),
        ),
        module._windows_project_gitignore_mutex(project_stat),
    ):
        pass

    assert fake_ctypes.get_last_error.call_count == 2
    kernel32.CloseHandle.assert_called_once_with(37)


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_windows_project_pin_denies_delete_sharing_and_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    module = file_copier if writer == "cli" else sofa
    create_file = MagicMock(return_value=41)
    close_handle = MagicMock(return_value=True)
    kernel32 = MagicMock(CreateFileW=create_file, CloseHandle=close_handle)
    fake_ctypes = MagicMock()
    fake_ctypes.WinDLL.return_value = kernel32

    class FakeHandle:
        def __init__(self, value: int):
            self.value = (2**64 - 1) if value == -1 else value

    fake_wintypes = MagicMock()
    fake_wintypes.HANDLE = FakeHandle
    real_import_module = module.importlib.import_module

    def fake_import_module(name: str):
        if name == "ctypes":
            return fake_ctypes
        if name == "ctypes.wintypes":
            return fake_wintypes
        return real_import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import_module)
    project_original = os.stat(tmp_path, follow_symlinks=False)

    with module._windows_pinned_project_root(tmp_path, project_original):
        pass

    args = create_file.call_args.args
    assert args[2] == 0x00000003
    assert args[2] & 0x00000004 == 0
    assert args[5] == 0x02200000
    close_handle.assert_called_once_with(41)


@pytest.mark.parametrize("writer", ["cli", "standalone"])
@pytest.mark.parametrize("attack", ["symlink", "hardlink", "nonregular"])
def test_vc3_gitignore_writer_rejects_unsafe_shared_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
    attack: str,
) -> None:
    from mapify_cli.delivery import file_copier

    if os.name == "nt":
        pytest.skip("Windows uses a named mutex with no lock file")
    lock_path = tmp_path / "shared-gitignore.lock"
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"outside-sentinel")
    if attack == "symlink":
        lock_path.symlink_to(outside)
    elif attack == "hardlink":
        try:
            os.link(outside, lock_path)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"hardlinks unavailable: {exc}")
    else:
        lock_path.mkdir()

    if writer == "cli":
        monkeypatch.setattr(
            file_copier,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        operation = lambda: file_copier.merge_update_runtime_gitignore(tmp_path)
        error = file_copier.UpdateRuntimeGitignoreSecurityError
    else:
        monkeypatch.setattr(
            sofa,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        operation = lambda: sofa.ensure_sofa_gitignore(tmp_path)
        error = sofa.SofaGitignoreSecurityError

    with pytest.raises(error):
        operation()

    assert not (tmp_path / ".gitignore").exists()
    assert outside.read_bytes() == b"outside-sentinel"


def test_vc3_secure_merge_replace_failure_preserves_file(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"user-rule/\n")
    gitignore.chmod(0o640)

    with (
        patch.object(sofa.os, "replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        sofa.ensure_sofa_gitignore(tmp_path)

    assert gitignore.read_bytes() == b"user-rule/\n"
    assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640
    assert list(tmp_path.glob(".gitignore.*.tmp")) == []


def test_vc3_secure_merge_supports_platform_without_fchmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(sofa.os, "fchmod", raising=False)

    with patch.object(sofa.os, "chmod") as path_chmod:
        assert sofa.ensure_sofa_gitignore(tmp_path) is True

    path_chmod.assert_not_called()
    assert (
        ".sofa/" in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    )


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_no_fchmod_lock_swap_cannot_chmod_outside_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    lock_path = tmp_path / "controlled.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o644)
    outside = tmp_path / "outside-mode"
    outside.write_bytes(b"outside")
    outside.chmod(0o644)
    real_chmod = os.chmod

    def swap_then_chmod(path: str | Path, mode: int) -> None:
        target = Path(path)
        if target == lock_path:
            target.unlink()
            target.symlink_to(outside)
        real_chmod(target, mode)

    if writer == "cli":
        monkeypatch.delattr(file_copier.os, "fchmod", raising=False)
        monkeypatch.setattr(
            file_copier,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        monkeypatch.setattr(file_copier.os, "chmod", swap_then_chmod)
        operation = lambda: file_copier.merge_update_runtime_gitignore(tmp_path)
        error = file_copier.UpdateRuntimeGitignoreSecurityError
    else:
        monkeypatch.delattr(sofa.os, "fchmod", raising=False)
        monkeypatch.setattr(
            sofa,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        monkeypatch.setattr(sofa.os, "chmod", swap_then_chmod)
        operation = lambda: sofa.ensure_sofa_gitignore(tmp_path)
        error = sofa.SofaGitignoreSecurityError

    with pytest.raises(error):
        operation()

    assert stat.S_IMODE(outside.stat().st_mode) == 0o644


@pytest.mark.parametrize("writer", ["cli", "standalone"])
def test_vc3_no_fchmod_gitignore_temp_swap_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    from mapify_cli.delivery import file_copier

    lock_path = tmp_path / "controlled.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    gitignore = tmp_path / ".gitignore"
    original = b"user-rule/\n"
    gitignore.write_bytes(original)
    gitignore.chmod(0o640)
    outside = tmp_path / "outside-mode"
    outside.write_bytes(b"outside")
    outside.chmod(0o644)
    real_chmod = os.chmod

    def swap_temp_then_chmod(path: str | Path, mode: int) -> None:
        target = Path(path)
        if target.name.startswith(".gitignore."):
            target.unlink()
            target.symlink_to(outside)
        real_chmod(target, mode)

    if writer == "cli":
        monkeypatch.delattr(file_copier.os, "fchmod", raising=False)
        monkeypatch.setattr(
            file_copier,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        monkeypatch.setattr(file_copier.os, "chmod", swap_temp_then_chmod)
        operation = lambda: file_copier.merge_update_runtime_gitignore(tmp_path)
        error = file_copier.UpdateRuntimeGitignoreSecurityError
    else:
        monkeypatch.delattr(sofa.os, "fchmod", raising=False)
        monkeypatch.setattr(
            sofa,
            "_gitignore_lock_path_for_stat",
            lambda _root, _stat: lock_path,
        )
        monkeypatch.setattr(sofa.os, "chmod", swap_temp_then_chmod)
        operation = lambda: sofa.ensure_sofa_gitignore(tmp_path)
        error = sofa.SofaGitignoreSecurityError

    with pytest.raises(error):
        operation()

    assert gitignore.read_bytes() == original
    assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644


def test_vc3_secure_merge_closes_temp_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_create_temporary = sofa._create_gitignore_temporary
    real_replace = sofa.os.replace
    captured_descriptor: dict[str, int] = {}

    def tracking_create_temporary(
        gitignore: Path,
        directory_fd: int | None,
    ) -> tuple[int, str | Path]:
        descriptor, temporary_name = real_create_temporary(gitignore, directory_fd)
        captured_descriptor["value"] = descriptor
        return descriptor, temporary_name

    def replace_after_close(*args: object, **kwargs: object) -> None:
        with pytest.raises(OSError):
            os.fstat(captured_descriptor["value"])
        real_replace(*args, **kwargs)

    monkeypatch.setattr(sofa, "_create_gitignore_temporary", tracking_create_temporary)
    monkeypatch.setattr(sofa.os, "replace", replace_after_close)

    assert sofa.ensure_sofa_gitignore(tmp_path) is True
    assert (tmp_path / ".gitignore").is_file()


def test_vc3_secure_merge_noop_rejects_post_read_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    real_read = sofa._read_safe_gitignore

    def read_then_swap(path: Path, directory_fd: int | None):
        existing, original = real_read(path, directory_fd)
        replacement = path.with_name("replacement.gitignore")
        replacement.write_bytes(existing)
        os.replace(replacement, path)
        return existing, original

    monkeypatch.setattr(sofa, "_read_safe_gitignore", read_then_swap)

    with pytest.raises(sofa.SofaGitignoreSecurityError):
        sofa.ensure_sofa_gitignore(tmp_path)


def test_vc3_gitignore_failure_blocks_credential_write_without_secret_exposure(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-gitignore"
    outside.write_bytes(b"outside-sentinel\n")
    (tmp_path / ".gitignore").symlink_to(outside)
    api_key = "sofa_private_key_must_not_escape"

    result = sofa.store_credentials(
        repo_root=tmp_path,
        agent_id="agent-private",
        api_key=api_key,
        agent_name="Private Agent",
        base_url="http://fake",
        api_key_prefix="sofa_private",
        api_key_suffix="escape",
    )

    assert result["ok"] is False
    assert result["kind"] == "gitignore_error"
    assert api_key not in json.dumps(result)
    assert not (tmp_path / ".sofa" / "credentials.json").exists()
    assert outside.read_bytes() == b"outside-sentinel\n"


def test_vc3_root_swap_after_ignore_blocks_credential_write_without_secret_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    moved_project = tmp_path / "moved-project"
    secret = "sofa_boundary_secret_must_not_escape"
    real_open_sofa_directory = sofa._open_sofa_directory

    def swap_then_open(
        repo_root: Path,
        *,
        create: bool,
        **kwargs: object,
    ):
        project.rename(moved_project)
        project.mkdir()
        (project / ".gitignore").write_text("replacement-without-sofa-ignore\n")
        return real_open_sofa_directory(
            repo_root,
            create=create,
            **kwargs,
        )

    monkeypatch.setattr(sofa, "_open_sofa_directory", swap_then_open)

    result = sofa.store_credentials(
        repo_root=project,
        agent_id="boundary-agent",
        api_key=secret,
        agent_name="Boundary Agent",
        base_url="https://sofa.invalid",
        api_key_prefix="sofa_boundary",
        api_key_suffix="escape",
    )

    assert result["ok"] is False
    assert result["kind"] in {"gitignore_error", "credential_storage_error"}
    assert secret not in json.dumps(result)
    assert not (project / ".sofa" / "credentials.json").exists()
    assert not (moved_project / ".sofa" / "credentials.json").exists()


@pytest.mark.parametrize("existing_credentials", [False, True])
def test_vc3_root_swap_during_credential_replace_rolls_back_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_credentials: bool,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    moved_project = tmp_path / "moved-project"
    prior_content = b'{"existing": {"api_key": "keep"}}'
    if existing_credentials:
        sofa_dir = project / ".sofa"
        sofa_dir.mkdir()
        credentials_file = sofa_dir / "credentials.json"
        credentials_file.write_bytes(prior_content)
        credentials_file.chmod(0o640)
    secret = "sofa_replace_boundary_secret_must_not_persist"
    real_replace = sofa.os.replace
    swapped = False

    def replace_then_swap(*args: object, **kwargs: object) -> None:
        nonlocal swapped
        real_replace(*args, **kwargs)
        destination = args[1]
        if not swapped and str(destination).endswith("credentials.json"):
            swapped = True
            project.rename(moved_project)
            project.mkdir()
            (project / ".gitignore").write_text("replacement-without-sofa-ignore\n")

    monkeypatch.setattr(sofa.os, "replace", replace_then_swap)

    result = sofa.store_credentials(
        repo_root=project,
        agent_id="boundary-agent",
        api_key=secret,
        agent_name="Boundary Agent",
        base_url="https://sofa.invalid",
        api_key_prefix="sofa_boundary",
        api_key_suffix="persist",
    )

    assert swapped is True
    assert result["ok"] is False
    assert result["kind"] == "gitignore_error"
    assert secret not in json.dumps(result)
    moved_credentials = moved_project / ".sofa" / "credentials.json"
    if existing_credentials:
        assert moved_credentials.read_bytes() == prior_content
        assert stat.S_IMODE(moved_credentials.stat().st_mode) == 0o640
        assert (
            list(moved_credentials.parent.glob(".credentials.json.rollback.*.tmp"))
            == []
        )
    else:
        assert not moved_credentials.exists()
    assert not (project / ".sofa" / "credentials.json").exists()
    for root in (project, moved_project):
        for candidate in root.rglob("*"):
            if candidate.is_file():
                assert secret.encode() not in candidate.read_bytes()


def test_vc3_failed_restore_removes_newly_installed_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = project / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    prior_content = b'{"existing": {"api_key": "keep"}}'
    credentials_file.write_bytes(prior_content)
    credentials_file.chmod(0o640)
    moved_project = tmp_path / "moved-project"
    secret = "sofa_failed_restore_secret_must_not_persist"
    real_replace = sofa.os.replace
    credential_replace_count = 0

    def replace_swap_then_fail_restore(*args: object, **kwargs: object) -> None:
        nonlocal credential_replace_count
        destination = args[1]
        if str(destination).endswith("credentials.json"):
            credential_replace_count += 1
            if credential_replace_count == 2:
                raise OSError("rollback replace failed")
        real_replace(*args, **kwargs)
        if credential_replace_count == 1:
            project.rename(moved_project)
            project.mkdir()
            (project / ".gitignore").write_text("replacement-without-sofa-ignore\n")

    monkeypatch.setattr(sofa.os, "replace", replace_swap_then_fail_restore)

    result = sofa.store_credentials(
        repo_root=project,
        agent_id="boundary-agent",
        api_key=secret,
        agent_name="Boundary Agent",
        base_url="https://sofa.invalid",
        api_key_prefix="sofa_boundary",
        api_key_suffix="persist",
    )

    assert credential_replace_count == 2
    assert result["ok"] is False
    assert result["kind"] == "gitignore_error"
    assert secret not in json.dumps(result)
    restored = moved_project / ".sofa" / "credentials.json"
    assert restored.read_bytes() == prior_content
    assert stat.S_IMODE(restored.stat().st_mode) == 0o640
    assert list(restored.parent.glob(".credentials.json.rollback.*.tmp")) == []
    for root in (project, moved_project):
        for candidate in root.rglob("*"):
            if candidate.is_file():
                assert secret.encode() not in candidate.read_bytes()


def test_vc3_failed_restore_and_fallback_retains_only_recovery_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = project / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    prior_content = b'{"existing": {"api_key": "keep"}}'
    credentials_file.write_bytes(prior_content)
    credentials_file.chmod(0o640)
    moved_project = tmp_path / "moved-project"
    secret = "sofa_failed_fallback_secret_must_not_persist"
    real_replace = sofa.os.replace
    real_rename = sofa.os.rename
    credential_replace_count = 0

    def replace_swap_then_fail_restore(*args: object, **kwargs: object) -> None:
        nonlocal credential_replace_count
        destination = args[1]
        if str(destination).endswith("credentials.json"):
            credential_replace_count += 1
            if credential_replace_count == 2:
                raise OSError("rollback replace failed")
        real_replace(*args, **kwargs)
        if credential_replace_count == 1:
            project.rename(moved_project)
            project.mkdir()
            (project / ".gitignore").write_text("replacement-without-sofa-ignore\n")

    def fail_rollback_rename(*args: object, **kwargs: object) -> None:
        if str(args[0]).startswith(".credentials.json.rollback."):
            raise OSError("rename failed")
        real_rename(*args, **kwargs)

    monkeypatch.setattr(sofa.os, "replace", replace_swap_then_fail_restore)
    monkeypatch.setattr(sofa.os, "rename", fail_rollback_rename)

    result = sofa.store_credentials(
        repo_root=project,
        agent_id="boundary-agent",
        api_key=secret,
        agent_name="Boundary Agent",
        base_url="https://sofa.invalid",
        api_key_prefix="sofa_boundary",
        api_key_suffix="persist",
    )

    assert credential_replace_count == 2
    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert secret not in json.dumps(result)
    assert not (moved_project / ".sofa" / "credentials.json").exists()
    recoveries = list(
        (moved_project / ".sofa").glob(".credentials.json.rollback.*.tmp")
    )
    assert len(recoveries) == 1
    assert recoveries[0].read_bytes() == prior_content
    assert stat.S_IMODE(recoveries[0].stat().st_mode) == 0o640
    for root in (project, moved_project):
        for candidate in root.rglob("*"):
            if candidate.is_file() and candidate not in recoveries:
                assert secret.encode() not in candidate.read_bytes()


@pytest.mark.parametrize(
    ("first_operation", "second_operation"),
    [
        ("gitignore-cli", "gitignore-sofa"),
        ("gitignore-sofa", "gitignore-cli"),
    ],
)
def test_vc3_cli_and_standalone_gitignore_merges_serialize_across_processes(
    tmp_path: Path,
    first_operation: str,
    second_operation: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(
        "user-rule/\n!.map/**\n!.sofa/**\n", encoding="utf-8"
    )
    first, _, first_ready, first_release, first_done = _start_concurrency_worker(
        tmp_path,
        name="first",
        operation=first_operation,
        project=project,
        pause=True,
        temp_dir=tmp_path / "first-process-tmp",
    )
    assert _wait_for_path(first_ready), "first writer never reached its protected read"

    second, second_attempted, _, _, second_done = _start_concurrency_worker(
        tmp_path,
        name="second",
        operation=second_operation,
        project=project,
        pause=False,
        temp_dir=tmp_path / "second-process-tmp",
    )
    assert _wait_for_path(second_attempted), "second writer never attempted its merge"
    second_returned_while_first_was_paused = _wait_for_path(second_done, timeout=0.75)

    first_release.write_text("release", encoding="utf-8")
    _finish_worker(first)
    _finish_worker(second)

    assert not second_returned_while_first_was_paused
    assert first_done.is_file()
    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in (
        ".map/update-state.json",
        ".map/update.lock",
        ".map/provider-refresh.lock",
        ".map/installer.lock",
        ".sofa/",
    ):
        assert lines.count(required) >= 1


@pytest.mark.parametrize(
    ("first_operation", "second_operation"),
    [
        ("gitignore-cli", "gitignore-sofa"),
        ("gitignore-sofa", "gitignore-cli"),
    ],
)
def test_vc3_gitignore_lock_identity_uses_samefile_across_case_aliases(
    tmp_path: Path,
    first_operation: str,
    second_operation: str,
) -> None:
    project = tmp_path / "MapProject"
    project.mkdir()
    alias = tmp_path / "mAPpROJECT"
    if not alias.exists() or not os.path.samefile(project, alias):
        pytest.skip("case-insensitive filesystem required for samefile alias coverage")
    (project / ".gitignore").write_text(
        "user-rule/\n!.map/**\n!.sofa/**\n", encoding="utf-8"
    )

    first, _, first_ready, first_release, first_done = _start_concurrency_worker(
        tmp_path,
        name="first-case-alias",
        operation=first_operation,
        project=project,
        pause=True,
    )
    assert _wait_for_path(first_ready), "first alias writer never reached its read"

    second, second_attempted, _, _, second_done = _start_concurrency_worker(
        tmp_path,
        name="second-case-alias",
        operation=second_operation,
        project=alias,
        pause=False,
    )
    assert _wait_for_path(second_attempted), "second alias writer never attempted"
    second_returned_while_first_was_paused = _wait_for_path(second_done, timeout=0.75)

    first_release.write_text("release", encoding="utf-8")
    _finish_worker(first)
    _finish_worker(second)

    assert not second_returned_while_first_was_paused
    assert first_done.is_file()
    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in (
        ".map/update-state.json",
        ".map/update.lock",
        ".map/provider-refresh.lock",
        ".map/installer.lock",
        ".sofa/",
    ):
        assert lines.count(required) >= 1


# ---------------------------------------------------------------------------
# VC4: no silent overwrite; no secret literal shipped in repo/generated trees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("agent_id", None),
        ("agent_id", 42),
        ("agent_id", ""),
        ("agent_id", "   "),
        ("api_key", None),
        ("api_key", 42),
        ("api_key", ""),
        ("api_key", "   "),
        ("agent_name", None),
        ("agent_name", 42),
        ("base_url", None),
        ("base_url", 42),
        ("api_key_prefix", None),
        ("api_key_prefix", 42),
        ("api_key_suffix", None),
        ("api_key_suffix", 42),
    ],
)
def test_vc4_store_rejects_invalid_inputs_before_any_filesystem_write(
    tmp_path: Path,
    field: str,
    invalid: object,
) -> None:
    secret = "must_not_be_persisted"
    arguments: dict[str, object] = {
        "repo_root": tmp_path,
        "agent_id": "agent-valid",
        "api_key": secret,
        "agent_name": "Agent",
        "base_url": "https://sofa.invalid",
        "api_key_prefix": "prefix",
        "api_key_suffix": "suffix",
    }
    arguments[field] = invalid

    result = sofa.store_credentials(**arguments)

    assert result["ok"] is False
    assert result["kind"] == "invalid_input"
    assert secret not in json.dumps(result)
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / ".sofa").exists()


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
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode != 0 or not result.stdout.strip()
    ), f"Possible secret literal found in source trees:\n{result.stdout}"


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


@pytest.mark.parametrize(
    "payload",
    [
        {"agent": ["not", "an", "object"]},
        {"agent": {"api_key": 42}},
    ],
)
def test_vc4_malformed_nested_credentials_return_typed_error(
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    original = json.dumps(payload).encode()
    credentials_file.write_bytes(original)
    env_without_key = {
        key: value for key, value in os.environ.items() if key != "SOFA_API_KEY"
    }

    with patch.dict(os.environ, env_without_key, clear=True):
        resolved = sofa.resolve_key(
            agent_id="agent",
            credentials_path=credentials_file,
        )
    stored = _store_test_credentials(tmp_path, api_key="must_not_be_written")

    assert resolved["ok"] is False
    assert resolved["kind"] == "bad_json"
    assert stored["ok"] is False
    assert stored["kind"] == "bad_json"
    assert credentials_file.read_bytes() == original


@pytest.mark.parametrize(
    "attack", ["sofa-symlink", "credential-symlink", "credential-hardlink"]
)
def test_vc4_store_rejects_linked_credential_paths_without_secret_exposure(
    tmp_path: Path,
    attack: str,
) -> None:
    if attack == "credential-hardlink" and os.name == "nt":
        pytest.skip("POSIX hardlink security contract")
    outside_dir = tmp_path / "outside-sofa"
    outside_dir.mkdir()
    outside_file = outside_dir / "credentials.json"
    outside_file.write_bytes(b"{}")
    sofa_dir = tmp_path / ".sofa"
    credentials_file = sofa_dir / "credentials.json"
    if attack == "sofa-symlink":
        sofa_dir.symlink_to(outside_dir, target_is_directory=True)
    else:
        sofa_dir.mkdir()
        if attack == "credential-symlink":
            credentials_file.symlink_to(outside_file)
        else:
            try:
                os.link(outside_file, credentials_file)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")
    api_key = "sofa_link_attack_secret"

    result = _store_test_credentials(tmp_path, api_key=api_key)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert api_key not in json.dumps(result)
    assert outside_file.read_bytes() == b"{}"


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_vc4_store_rejects_nonregular_credentials_path(
    tmp_path: Path,
    kind: str,
) -> None:
    if kind == "fifo" and (os.name == "nt" or not hasattr(os, "mkfifo")):
        pytest.skip("FIFO unavailable")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    if kind == "directory":
        credentials_file.mkdir()
    else:
        os.mkfifo(credentials_file)

    result = _store_test_credentials(tmp_path, api_key="sofa_nonregular_secret")

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert credentials_file.exists()


@pytest.mark.parametrize("contents", [b"{broken-json", b"[]"])
def test_vc4_store_does_not_clobber_invalid_existing_credentials(
    tmp_path: Path,
    contents: bytes,
) -> None:
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    credentials_file.write_bytes(contents)
    credentials_file.chmod(0o640)

    result = _store_test_credentials(tmp_path, api_key="sofa_invalid_json_secret")

    assert result["ok"] is False
    assert result["kind"] == "bad_json"
    assert credentials_file.read_bytes() == contents
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o640


def test_vc4_store_does_not_clobber_unreadable_credentials(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX unreadable-file contract")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    credentials_file.write_bytes(b'{"existing": {"api_key": "keep"}}')
    credentials_file.chmod(0o000)

    try:
        result = _store_test_credentials(tmp_path, api_key="sofa_unreadable_secret")
    finally:
        credentials_file.chmod(0o600)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert credentials_file.read_bytes() == b'{"existing": {"api_key": "keep"}}'


def test_vc4_credential_replace_failure_is_atomic_and_redacted(
    tmp_path: Path,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    credentials_file = sofa_dir / "credentials.json"
    original = b'{"existing": {"api_key": "keep"}}'
    credentials_file.write_bytes(original)
    credentials_file.chmod(0o640)
    api_key = "sofa_atomic_failure_secret"

    with patch.object(sofa.os, "replace", side_effect=OSError("replace failed")):
        result = _store_test_credentials(tmp_path, api_key=api_key)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert api_key not in json.dumps(result)
    assert credentials_file.read_bytes() == original
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o640
    assert list(sofa_dir.glob(".credentials.json.*.tmp")) == []


def test_vc4_fallback_revalidates_sofa_before_allocating_secret_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    moved_sofa = tmp_path / "moved-sofa"
    outside = tmp_path / "outside-sofa"
    outside.mkdir()
    real_read = sofa._read_credentials_bytes

    def read_then_swap(*args: object, **kwargs: object):
        result = real_read(*args, **kwargs)
        sofa_dir.rename(moved_sofa)
        sofa_dir.symlink_to(outside, target_is_directory=True)
        return result

    def forbidden_mkstemp(*args: object, **kwargs: object):
        pytest.fail("unsafe .sofa must be rejected before allocating a temp file")

    monkeypatch.setattr(sofa, "_CAN_USE_DIRECTORY_FD", False)
    monkeypatch.setattr(sofa, "_read_credentials_bytes", read_then_swap)
    monkeypatch.setattr(sofa.tempfile, "mkstemp", forbidden_mkstemp)

    result = _store_test_credentials(
        tmp_path,
        api_key="sofa_fallback_preallocation_secret",
    )

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert not list(outside.iterdir())


def test_vc4_fallback_revalidates_sofa_after_temp_allocation_before_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    moved_sofa = tmp_path / "moved-sofa"
    outside = tmp_path / "outside-sofa"
    outside.mkdir()
    real_mkstemp = sofa.tempfile.mkstemp
    real_fsync = sofa.os.fsync
    secret = "sofa_fallback_allocation_secret"

    def swap_during_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        sofa_dir.rename(moved_sofa)
        sofa_dir.symlink_to(outside, target_is_directory=True)
        return real_mkstemp(*args, **kwargs)

    def reject_secret_write(descriptor: int) -> None:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        os.lseek(descriptor, 0, os.SEEK_SET)
        content = os.read(descriptor, 65536)
        os.lseek(descriptor, position, os.SEEK_SET)
        assert secret.encode() not in content
        real_fsync(descriptor)

    monkeypatch.setattr(sofa, "_CAN_USE_DIRECTORY_FD", False)
    monkeypatch.setattr(sofa.tempfile, "mkstemp", swap_during_mkstemp)
    monkeypatch.setattr(sofa.os, "fsync", reject_secret_write)

    result = _store_test_credentials(tmp_path, api_key=secret)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert not list(outside.iterdir())


def test_vc4_fallback_sanitizes_temp_if_sofa_swaps_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    moved_sofa = tmp_path / "moved-sofa"
    outside = tmp_path / "outside-sofa"
    outside.mkdir()
    real_fsync = sofa.os.fsync
    swapped = False
    secret = "sofa_fallback_prereplace_secret"

    def swap_after_secret_flush(descriptor: int) -> None:
        nonlocal swapped
        real_fsync(descriptor)
        if not swapped:
            swapped = True
            sofa_dir.rename(moved_sofa)
            sofa_dir.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(sofa, "_CAN_USE_DIRECTORY_FD", False)
    monkeypatch.setattr(sofa.os, "fsync", swap_after_secret_flush)

    result = _store_test_credentials(tmp_path, api_key=secret)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert secret not in json.dumps(result)
    assert all(
        secret.encode() not in path.read_bytes() for path in moved_sofa.iterdir()
    )
    assert not list(outside.iterdir())


def test_vc4_directory_fd_capability_checks_replace_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def replace_without_directory_fds(source: object, destination: object) -> None:
        raise AssertionError((source, destination))

    monkeypatch.setattr(sofa.os, "replace", replace_without_directory_fds)

    assert sofa._replace_supports_directory_fds() is False


@pytest.mark.parametrize(
    "attack", ["sofa-symlink", "credential-symlink", "credential-hardlink"]
)
def test_vc4_resolve_key_rejects_linked_credential_paths(
    tmp_path: Path,
    attack: str,
) -> None:
    if attack == "credential-hardlink" and os.name == "nt":
        pytest.skip("POSIX hardlink security contract")
    outside_dir = tmp_path / "outside-sofa"
    outside_dir.mkdir()
    outside_file = outside_dir / "credentials.json"
    outside_file.write_text(
        '{"external": {"api_key": "outside_secret"}}', encoding="utf-8"
    )
    sofa_dir = tmp_path / ".sofa"
    credentials_file = sofa_dir / "credentials.json"
    if attack == "sofa-symlink":
        sofa_dir.symlink_to(outside_dir, target_is_directory=True)
    else:
        sofa_dir.mkdir()
        if attack == "credential-symlink":
            credentials_file.symlink_to(outside_file)
        else:
            try:
                os.link(outside_file, credentials_file)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")
    env_without_key = {
        key: value for key, value in os.environ.items() if key != "SOFA_API_KEY"
    }

    with patch.dict(os.environ, env_without_key, clear=True):
        result = sofa.resolve_key(credentials_path=credentials_file)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert "outside_secret" not in json.dumps(result)


def test_vc4_safe_atomic_store_and_resolve_preserve_entries(tmp_path: Path) -> None:
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir(mode=0o700)
    credentials_file = sofa_dir / "credentials.json"
    credentials_file.write_text('{"existing": {"api_key": "keep"}}', encoding="utf-8")
    credentials_file.chmod(0o640)

    stored = _store_test_credentials(
        tmp_path,
        api_key="sofa_new_safe_key",
        agent_id="new-agent",
    )
    env_without_key = {
        key: value for key, value in os.environ.items() if key != "SOFA_API_KEY"
    }
    with patch.dict(os.environ, env_without_key, clear=True):
        resolved = sofa.resolve_key(
            agent_id="new-agent",
            credentials_path=credentials_file,
        )

    assert stored["ok"] is True
    assert resolved == {
        "ok": True,
        "api_key": "sofa_new_safe_key",
        "agent_id": "new-agent",
    }
    data = json.loads(credentials_file.read_text(encoding="utf-8"))
    assert data["existing"]["api_key"] == "keep"
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(sofa_dir.stat().st_mode) == 0o700
    if os.name != "nt":
        assert stat.S_IMODE((sofa_dir / "credentials.lock").stat().st_mode) == 0o600


def test_vc4_no_fchmod_credentials_flow_never_uses_path_chmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    monkeypatch.delattr(sofa.os, "fchmod", raising=False)
    monkeypatch.setattr(sofa, "_CAN_USE_DIRECTORY_FD", False)

    with patch.object(sofa.os, "chmod") as path_chmod:
        result = _store_test_credentials(tmp_path)

    assert result["ok"] is True
    path_chmod.assert_not_called()
    credentials_file = tmp_path / ".sofa" / "credentials.json"
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600


def test_vc4_no_fchmod_credentials_lock_swap_cannot_chmod_outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    lock_file = sofa_dir / "credentials.lock"
    lock_file.write_bytes(b"")
    lock_file.chmod(0o644)
    outside = tmp_path / "outside-mode"
    outside.write_bytes(b"outside")
    outside.chmod(0o644)
    real_chmod = os.chmod

    def swap_then_chmod(path: str | Path, mode: int) -> None:
        target = Path(path)
        if target == lock_file:
            target.unlink()
            target.symlink_to(outside)
        real_chmod(target, mode)

    monkeypatch.delattr(sofa.os, "fchmod", raising=False)
    monkeypatch.setattr(sofa.os, "chmod", swap_then_chmod)

    result = _store_test_credentials(tmp_path)

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644
    assert not (sofa_dir / "credentials.json").exists()


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "nonregular"])
def test_vc4_store_rejects_unsafe_credentials_transaction_lock(
    tmp_path: Path,
    attack: str,
) -> None:
    if attack == "hardlink" and os.name == "nt":
        pytest.skip("POSIX hardlink security contract")
    (tmp_path / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    sofa_dir = tmp_path / ".sofa"
    sofa_dir.mkdir()
    lock_file = sofa_dir / "credentials.lock"
    outside = tmp_path / "outside-credentials-lock"
    outside.write_bytes(b"outside-sentinel")
    if attack == "symlink":
        lock_file.symlink_to(outside)
    elif attack == "hardlink":
        try:
            os.link(outside, lock_file)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"hardlinks unavailable: {exc}")
    else:
        lock_file.mkdir()
    api_key = "secret-must-not-leak"

    result = sofa.store_credentials(
        repo_root=tmp_path,
        agent_id="agent",
        api_key=api_key,
        agent_name="Agent",
        base_url="https://sofa.invalid",
        api_key_prefix="prefix",
        api_key_suffix="suffix",
    )

    assert result["ok"] is False
    assert result["kind"] == "credential_storage_error"
    assert api_key not in json.dumps(result)
    assert not (sofa_dir / "credentials.json").exists()
    assert outside.read_bytes() == b"outside-sentinel"


@pytest.mark.parametrize(
    ("first_agent", "second_agent", "expected_successes"),
    [
        ("agent-a", "agent-b", 2),
        ("same-agent", "same-agent", 1),
    ],
)
def test_vc4_credential_transactions_serialize_across_processes(
    tmp_path: Path,
    first_agent: str,
    second_agent: str,
    expected_successes: int,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text(_SAFE_SOFA_GITIGNORE, encoding="utf-8")
    first, _, first_ready, first_release, first_done = _start_concurrency_worker(
        tmp_path,
        name="first-credential",
        operation="credential",
        project=project,
        pause=True,
        agent_id=first_agent,
    )
    assert _wait_for_path(first_ready), "first credential writer never reached read"

    second, second_attempted, _, _, second_done = _start_concurrency_worker(
        tmp_path,
        name="second-credential",
        operation="credential",
        project=project,
        pause=False,
        agent_id=second_agent,
    )
    assert _wait_for_path(second_attempted), "second credential writer never attempted"
    second_returned_while_first_was_paused = _wait_for_path(second_done, timeout=0.75)

    first_release.write_text("release", encoding="utf-8")
    _finish_worker(first)
    _finish_worker(second)

    assert not second_returned_while_first_was_paused
    results = [
        json.loads(first_done.read_text(encoding="utf-8")),
        json.loads(second_done.read_text(encoding="utf-8")),
    ]
    assert sum(result["ok"] is True for result in results) == expected_successes
    credentials = json.loads(
        (project / ".sofa" / "credentials.json").read_text(encoding="utf-8")
    )
    assert set(credentials) == {first_agent, second_agent}
    assert (
        stat.S_IMODE((project / ".sofa" / "credentials.json").stat().st_mode) == 0o600
    )


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


@pytest.mark.parametrize(
    ("field", "invalid", "expected_kind"),
    [
        ("base_url", None, "invalid_input"),
        ("base_url", 42, "invalid_input"),
        ("base_url", "   ", "invalid_input"),
        ("auth_code", None, "invalid_input"),
        ("auth_code", 42, "invalid_input"),
        ("auth_code", "", "invalid_input"),
        ("agent_name", None, "need_agent_name"),
        ("agent_name", 42, "need_agent_name"),
        ("agent_name", "", "need_agent_name"),
        ("description", None, "need_description"),
        ("description", 42, "need_description"),
        ("description", "", "need_description"),
        ("persona", 42, "invalid_input"),
    ],
)
def test_vc5_registration_rejects_invalid_inputs_before_network_call(
    field: str,
    invalid: object,
    expected_kind: str,
) -> None:
    arguments: dict[str, object] = {
        "base_url": "https://sofa.invalid",
        "auth_code": "auth-code",
        "agent_name": "Agent",
        "description": "Description",
        "persona": None,
    }
    arguments[field] = invalid

    with patch.object(sofa, "_request") as request:
        result = sofa.onboarding_register(**arguments)

    assert result["ok"] is False
    assert result["kind"] == expected_kind
    request.assert_not_called()


@pytest.mark.parametrize(
    "registration_data",
    [
        {"agent_id": None, "api_key": "secret"},
        {"agent_id": 42, "api_key": "secret"},
        {"agent_id": "", "api_key": "secret"},
        {"agent_id": "agent", "api_key": None},
        {"agent_id": "agent", "api_key": 42},
        {"agent_id": "agent", "api_key": ""},
        {
            "agent_id": "agent",
            "api_key": "secret",
            "api_key_prefix": [],
        },
    ],
)
def test_vc5_registration_rejects_malformed_success_payload(
    registration_data: dict[str, object],
) -> None:
    with patch.object(
        sofa,
        "_request",
        return_value={"ok": True, "status": 201, "data": registration_data},
    ):
        result = sofa.onboarding_register(
            "https://sofa.invalid",
            auth_code="auth-code",
            agent_name="Agent",
            description="Description",
        )

    assert result["ok"] is False
    assert result["kind"] == "invalid_registration"
    assert "secret" not in json.dumps(result)


# ---------------------------------------------------------------------------
# Additional: network error returns typed result, never raises
# ---------------------------------------------------------------------------


def test_network_error_returns_typed_result():
    """urllib.error.URLError (connection refused) → typed _err, never raises."""
    import urllib.error

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
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
