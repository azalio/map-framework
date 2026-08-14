"""
Pytest tests for .claude/hooks/safety-guardrails.py PreToolUse hook.

This hook replaces the old block-secrets.py and block-dangerous.sh hooks.
Tests file blocking and dangerous command blocking.
"""
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

# Path to the hook script
HOOK_PATH = (
    Path(__file__).parent.parent.parent / ".claude" / "hooks" / "safety-guardrails.py"
)


def run_hook_file(tool_name: str, file_path: str) -> tuple[int, str, str]:
    """Execute the hook with given tool and file path."""
    input_data = {"tool_name": tool_name, "tool_input": {"file_path": file_path}}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def run_hook_bash(command: str) -> tuple[int, str, str]:
    """Execute the hook with given bash command."""
    input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def run_hook_bash_in(command: str, project_dir: Path) -> tuple[int, str, str]:
    """Execute the hook with CLAUDE_PROJECT_DIR pointed at *project_dir*.

    Used to exercise the autonomy git-block, which keys on the
    ``mapify.autonomy`` sentinel in ``<project_dir>/.claude/settings.local.json``.
    """
    import os

    input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _write_autonomy_settings(project_dir: Path, enabled: bool) -> None:
    """Write .claude/settings.local.json with the autonomy sentinel set/cleared."""
    settings = project_dir / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "permissions": {"allow": ["Bash(*)"], "deny": ["Bash(git commit:*)"]}
    }
    if enabled:
        payload["mapify"] = {"autonomy": True}
    settings.write_text(json.dumps(payload))


def _parse_stdout(stdout: str) -> dict:
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _assert_denied(payload: dict) -> None:
    assert payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
    assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
    reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
    assert reason


# =============================================================================
# File Blocking Tests
# =============================================================================


class TestEnvFiles:
    """Test .env file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            ".env.test",
        ],
    )
    def test_env_variants_blocked(self, filename):
        exit_code, stdout, _ = run_hook_file("Read", filename)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("tool", ["Read", "Write", "Edit", "MultiEdit"])
    def test_env_blocked_all_file_tools(self, tool):
        exit_code, stdout, _ = run_hook_file(tool, ".env")
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


class TestCredentialFiles:
    """Test credential file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            "credentials.json",
            "aws-credentials",
            "gcp_credentials.yaml",
            "database-credentials.txt",
        ],
    )
    def test_credentials_blocked(self, filename):
        exit_code, stdout, _ = run_hook_file("Read", filename)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


class TestSecretFiles:
    """Test secret file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            "secrets.yaml",
            "secrets.json",
            "secret.toml",
        ],
    )
    def test_secrets_blocked(self, filename):
        exit_code, stdout, _ = run_hook_file("Read", filename)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


class TestPrivateKeys:
    """Test private key file blocking."""

    @pytest.mark.parametrize(
        "filename",
        [
            "server.pem",
            "private.pem",
            "cert.PEM",
            "id_rsa",
            "id_ed25519",
            "server.key",
            "app.key",
            "passwords.json",
            "passwords.yaml",
            "tokens.json",
            "tokens.txt",
        ],
    )
    def test_key_files_blocked(self, filename):
        exit_code, stdout, _ = run_hook_file("Read", filename)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


# =============================================================================
# Safe Path Prefix Tests
# =============================================================================


class TestSafePathPrefixes:
    """Test that files in known safe directories are allowed even if name matches."""

    @pytest.mark.parametrize(
        "path",
        [
            "src/config/secrets.yaml",
            "tests/fixtures/credentials.json",
            ".claude/hooks/safety-guardrails.py",
        ],
    )
    def test_safe_prefix_allowed(self, path):
        exit_code, stdout, _ = run_hook_file("Read", path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


# =============================================================================
# Allowed File Tests (False Positive Prevention)
# =============================================================================


class TestNormalFilesAllowed:
    """Test that normal development files are allowed."""

    @pytest.mark.parametrize(
        "filename",
        [
            "app.py",
            "main.go",
            "index.ts",
            "README.md",
            "package.json",
            "Dockerfile",
            "config.yaml",
            "settings.json",
        ],
    )
    def test_normal_files_allowed(self, filename):
        exit_code, stdout, _ = run_hook_file("Read", filename)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


class TestNonFileToolsPassThrough:
    """Test that non-file, non-bash tools pass through."""

    def test_grep_passes_through(self):
        exit_code, stdout, _ = run_hook_file("Grep", ".env")
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_glob_passes_through(self):
        exit_code, stdout, _ = run_hook_file("Glob", ".env")
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


# =============================================================================
# Dangerous Command Blocking Tests
# =============================================================================


class TestRmRfBlocking:
    """Test rm -rf variants are blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf /home/user",
            "rm -rf /etc",
            "rm -rf /var",
            "rm -rf /tmp",  # the temp ROOT itself stays blocked (no trailing /child)
            "rm -rf /*",
            "rm -rf *",
            "rm -rf ..",
        ],
    )
    def test_rm_rf_blocked(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /tmp/map-spike-abc123",
            "rm -rf /tmp/pytest-of-user/run0",
            "rm -rf /private/tmp/map-spike-WOi8Pq",  # macOS mktemp
            "rm -rf /var/folders/ab/cd1234/T/scratch",  # macOS $TMPDIR
            "rm -rf /var/tmp/build-cache",
        ],
    )
    def test_rm_rf_temp_subpath_allowed(self, command):
        """Deleting a subpath UNDER a temp root is legitimate scratch cleanup
        and must not be blocked (regression: the bare ``rm -rf /`` pattern used
        to flag every absolute path, including temp dirs and any command that
        merely mentioned one)."""
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_rm_single_file_allowed(self):
        exit_code, stdout, _ = run_hook_bash("rm file.txt")
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


class TestGitForcePushBlocking:
    """Test git force push to main/master is blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "git push --force origin main",
            "git push -f origin main",
            "git push --force origin master",
            "git push -f origin master",
        ],
    )
    def test_force_push_protected_blocked(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize(
        "command",
        [
            "git push --force origin feature-branch",
            "git push -f origin my-feature",
            "git push origin main",  # regular push (no --force)
        ],
    )
    def test_force_push_feature_allowed(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


class TestGitResetHardBlocking:
    """Test git reset --hard is blocked."""

    @pytest.mark.parametrize(
        "command",
        [
            "git reset --hard",
            "git reset --hard HEAD",
            "git reset --hard HEAD~1",
            "git reset --hard origin/main",
        ],
    )
    def test_reset_hard_blocked(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize(
        "command",
        [
            "git reset --soft HEAD~1",
            "git reset --mixed HEAD~1",
            "git reset HEAD~1",
        ],
    )
    def test_reset_soft_allowed(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


class TestOtherDangerousCommands:
    """Test other dangerous command patterns."""

    def test_chmod_777_root_blocked(self):
        exit_code, stdout, _ = run_hook_bash("chmod -R 777 /")
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    def test_write_to_device_blocked(self):
        exit_code, stdout, _ = run_hook_bash("> /dev/sda")
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


class TestLegitimateCommands:
    """Test that safe commands are allowed."""

    @pytest.mark.parametrize(
        "command",
        [
            "pytest",
            "pytest -v tests/",
            "make lint",
            "make test",
            "git status",
            "git diff",
            "git log --oneline",
            "git add .",
            "ls -la",
        ],
    )
    def test_safe_commands_allowed(self, command):
        exit_code, stdout, _ = run_hook_bash(command)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


# =============================================================================
# Autonomy git-block Tests
# =============================================================================


class TestAutonomyGitBlock:
    """git commit/push hard-block, gated on the mapify.autonomy sentinel."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit",
            'git commit -m "wip"',
            "git push",
            "git push origin main",
            "git push --force origin feature",  # not main/master, but autonomy blocks all push
            "bash -c 'git commit'",  # wrapper bypass of permission-deny — hook catches it
            "git status && git commit -m x",  # chained
            "git -C /repo commit -m x",  # -C <path> before subcommand
        ],
    )
    def test_git_write_blocked_when_autonomy_on(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=True)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff",
            "git log --oneline",
            "git add .",
            "echo committing",  # 'commit' substring, not a git subcommand
            "pytest -q",
        ],
    )
    def test_read_only_git_allowed_when_autonomy_on(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=True)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    @pytest.mark.parametrize("command", ["git commit -m x", "git push origin main"])
    def test_git_write_allowed_when_autonomy_off(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=False)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_git_write_allowed_when_no_settings_file(self, command="git commit -m x"):
        # No .claude/settings.local.json at all → autonomy off → not blocked.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            exit_code, stdout, _ = run_hook_bash_in(command, Path(d))
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_force_push_still_blocked_when_autonomy_off(self, tmp_path):
        # The baseline force-push guard is independent of autonomy mode.
        _write_autonomy_settings(tmp_path, enabled=False)
        exit_code, stdout, _ = run_hook_bash_in(
            "git push --force origin main", tmp_path
        )
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test edge cases and error handling."""

    def test_empty_file_path(self):
        exit_code, stdout, _ = run_hook_file("Read", "")
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_empty_command(self):
        exit_code, stdout, _ = run_hook_bash("")
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_invalid_json(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert _parse_stdout(result.stdout) == {}

    def test_empty_input(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)], input="", capture_output=True, text=True,
            check=False,
        )
        assert result.returncode == 0
        assert _parse_stdout(result.stdout) == {}


# =============================================================================
# Regression Tests — Bug #321: Directory Name False Positives
# =============================================================================


class TestDirectoryNameFalsePositives:
    """Regression tests for bug #321.

    Files with safe names inside directories with security-related names
    (e.g. 'secrets-injector', 'stackland-secrets-webhook') must NOT be blocked.
    The pattern check must match against the file basename only, never the full path.
    """

    @pytest.mark.parametrize(
        "path",
        [
            # Directory contains 'secret' but the FILE is a plain config file.
            "deploy/secrets-injector/values.yaml",
            "k8s/stackland-secrets-webhook/config.json",
            "infra/secrets-manager/deployment.yaml",
            # Directory contains 'credential' but the file is not a credential file.
            "apps/credential-service/main.py",
            # Directory contains 'token' but the file is not a token store.
            "services/token-validator/handler.go",
            # Directory contains 'key' but the file is not a private key.
            "apps/api-key-service/schema.sql",
            # Directory contains 'password' but the file is documentation.
            "docs/password-policy/README.md",
            # Directory contains 'private' but the file is a public module.
            "libs/private-utils/public_api.py",
        ],
    )
    def test_safe_file_in_dangerous_directory_not_blocked(self, path):
        """A file with a safe basename must not be blocked even if its parent
        directory name matches a dangerous pattern (regression for bug #321)."""
        exit_code, stdout, _ = run_hook_file("Read", path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}, (
            f"Path '{path}' was incorrectly blocked — basename is safe; "
            "only the directory name contains a dangerous-looking word"
        )

    @pytest.mark.parametrize(
        "path",
        [
            # The FILE itself is dangerous — must still be blocked.
            "deploy/secrets-injector/secrets.yaml",
            "k8s/app/.env",
            "infra/deploy/credentials.json",
        ],
    )
    def test_dangerous_file_in_any_directory_still_blocked(self, path):
        """A file with a dangerous basename must be blocked regardless of where it lives."""
        exit_code, stdout, _ = run_hook_file("Read", path)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))


# =============================================================================
# Verifier-class capability boundary (#424)
# =============================================================================


def run_hook_as_agent(
    tool_name: str, tool_input: dict, agent_type: str | None
) -> tuple[int, str, str]:
    """Execute the hook with an explicit `agent_type` (subagent context)."""
    input_data: dict[str, object] = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if agent_type is not None:
        input_data["agent_type"] = agent_type
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


class TestVerifierAgentBoundary:
    """A final-verifier run created and committed `3c6a7db` mid-audit, hand-editing
    generated trees and renaming a blueprint-named test, despite an
    APPROVED/REJECTED-only prompt contract. Prompt text is not a capability
    boundary — these tests pin the mechanical one."""

    VERIFIERS: ClassVar[list[str]] = [
        "final-verifier",
        "monitor",
        "evaluator",
        "predictor",
    ]

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'chore(map): strip internal workflow IDs'",
            "git add -A",
            "git push origin HEAD",
            "git reset --soft HEAD~1",
            "git checkout -- src/",
            "git restore .claude/hooks/workflow-gate.py",
            "git -C /repo commit --no-verify -m x",
            "bash -c 'git commit -m sneaky'",
            "make check && git commit -am wip",
            # Ref-moving commands change the very branch under audit.
            "git pull --rebase origin main",
            "git fetch origin",
            "git submodule update --init",
            "git update-ref refs/heads/main HEAD",
            "git symbolic-ref HEAD refs/heads/other",
            "git config user.email x@y.z",
        ],
    )
    def test_git_mutation_blocked_for_verifiers(self, agent, command):
        exit_code, stdout, _ = run_hook_as_agent("Bash", {"command": command}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff origin/main...HEAD",
            "git log -n 5",
            "git show HEAD",
            "git rev-parse HEAD",
            "git ls-files src/",
            "make check",
            "pytest tests/ -q",
        ],
    )
    def test_read_only_evidence_gathering_still_allowed(self, agent, command):
        """The verifier must keep every read/verify capability it needs."""
        exit_code, stdout, _ = run_hook_as_agent("Bash", {"command": command}, agent)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}, f"{command!r} was wrongly blocked"

    def test_git_mutation_allowed_on_main_thread(self):
        """Negative proof: without agent_type the boundary must not engage —
        the orchestrating session owns commits."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m 'ST-001: real work'"}, None
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_git_mutation_allowed_for_actor(self):
        """actor is a legitimate writer — it must keep committing its subtask."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m 'ST-001: real work'"}, "actor"
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
    @pytest.mark.parametrize(
        "path",
        [
            ".claude/hooks/workflow-gate.py",
            "src/mapify_cli/templates/map/scripts/map_step_runner.py",
            "tests/test_workflow_gate.py",
            "README.md",
        ],
    )
    def test_source_writes_blocked_for_verifiers(self, agent, tool, path):
        exit_code, stdout, _ = run_hook_as_agent(tool, {"file_path": path}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "path",
        [
            ".map/feat-x/final_verification.json",
            "./.map/feat-x/progress_feat-x.md",
            "/abs/repo/.map/feat-x/code-review-001.md",
        ],
    )
    def test_map_artifact_writes_allowed_for_verifiers(self, agent, path):
        """final-verifier legitimately writes its own verdict artifacts."""
        exit_code, stdout, _ = run_hook_as_agent("Write", {"file_path": path}, agent)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}, f"{path!r} was wrongly blocked"

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "path",
        [
            ".map/../src/mapify_cli/cli.py",
            ".map/feat-x/../../.claude/hooks/workflow-gate.py",
            "./.map/../README.md",
        ],
    )
    def test_traversal_out_of_map_is_blocked(self, agent, path):
        """A raw prefix check accepts `.map/../src/...`; normalize before matching."""
        exit_code, stdout, _ = run_hook_as_agent("Write", {"file_path": path}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    def test_reads_are_never_restricted(self, agent):
        exit_code, stdout, _ = run_hook_as_agent(
            "Read", {"file_path": "src/mapify_cli/cli.py"}, agent
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_plugin_scoped_agent_type_is_normalized(self):
        """`plugin:pkg:monitor` must resolve to the monitor boundary."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m x"}, "plugin:some-pkg:monitor"
        )
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    def test_source_write_allowed_on_main_thread(self):
        """Negative proof for the path boundary: no agent_type → no confinement."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Write", {"file_path": "src/mapify_cli/cli.py"}, None
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Test hook performance."""

    def test_execution_under_100ms(self):
        iterations = 10
        total_time = 0
        for _ in range(iterations):
            start = time.perf_counter()
            run_hook_file("Read", "app.py")
            total_time += time.perf_counter() - start
        avg_ms = (total_time / iterations) * 1000
        assert avg_ms < 100, f"Average {avg_ms:.2f}ms exceeds 100ms target"
