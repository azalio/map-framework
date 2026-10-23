"""
Pytest tests for .claude/hooks/end-of-turn.sh Stop hook.

Tests the lightweight version that:
- Only runs if there are uncommitted changes
- Checks only changed files
- Never rewrites changed source files
- Only reports critical issues (secrets, .env files, syntax errors)
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

# Path to the hook script
HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "end-of-turn.sh"


def run_hook(
    cwd: str | None = None,
    env: dict | None = None,
    input_text: str = "",
) -> tuple[int, str, str]:
    """Execute the hook in given directory.

    ``input_text`` is piped to the hook's stdin (Claude Code passes the hook
    input JSON there, e.g. with ``stop_hook_active``); empty by default so the
    hook never blocks on an inherited terminal.
    """
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=run_env,
        check=False,
        input=input_text,
    )
    return result.returncode, result.stdout, result.stderr


# =============================================================================
# Validation Criteria Tests
# =============================================================================


class TestValidationCriteria:
    """Tests for the validation criteria from task decomposition."""

    def test_criterion_5_timeout(self):
        """VC5: Completes execution within 30 seconds."""
        import time

        start = time.time()
        run_hook()
        elapsed = time.time() - start
        assert elapsed < 30, f"Hook took {elapsed:.2f}s, expected <30s"

    def test_criterion_6_exit_codes(self):
        """VC6: Exits with code 0 if no issues."""
        # Run in a clean temp directory with no project files
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, _, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0, "Should exit 0 in clean directory"


# =============================================================================
# Early Exit Tests (Lightweight behavior)
# =============================================================================


class TestEarlyExit:
    """Test that hook exits early when no changes detected."""

    def test_exits_early_no_git(self):
        """Should exit 0 immediately in non-git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, stderr = run_hook(cwd=tmpdir)
            del stderr
            assert exit_code == 0
            assert stdout.strip() == "{}"

    def test_exits_early_clean_repo(self):
        """Should exit 0 if git repo has no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init git repo with a commit
            subprocess.run(
                ["git", "init"], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            # Create and commit a file
            (Path(tmpdir) / "file.txt").write_text("content\n")
            subprocess.run(
                ["git", "add", "."], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )

            # Now repo is clean
            exit_code, stdout, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0
            assert stdout.strip() == "{}"


# =============================================================================
# Secret Detection Tests
# =============================================================================


class TestSecretDetection:
    """Test that secrets are detected in staged files."""

    def test_detect_api_key_in_staged(self):
        """VC3: Secret scanning finds 'API_KEY=abc123' pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize git repo
            subprocess.run(
                ["git", "init"], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )

            # Create file with secret
            secret_file = Path(tmpdir) / "config.py"
            secret_file.write_text('API_KEY = "sk_live_1234567890abcdef"\n')

            # Stage it
            subprocess.run(
                ["git", "add", "config.py"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )

            # Run hook
            exit_code, _, stderr = run_hook(cwd=tmpdir)

            # Should detect secret and return exit 2
            assert exit_code == 2, f"Should exit 2 for secrets. stderr: {stderr}"
            assert "secret" in stderr.lower() or "config.py" in stderr

    def test_no_secret_in_clean_file(self):
        """No false positives for clean files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                ["git", "init"], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )

            clean_file = Path(tmpdir) / "clean.py"
            clean_file.write_text('print("Hello")\n')

            subprocess.run(
                ["git", "add", "clean.py"], cwd=tmpdir, capture_output=True, check=False
            )

            exit_code, _, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0, "Should exit 0 for clean file"


def _git(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=tmp, capture_output=True, text=True, check=True,
    )


def _committed_repo(tmp: Path) -> None:
    _git(tmp, "init")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    (tmp / "seed.txt").write_text("seed\n")
    _git(tmp, "add", "seed.txt")
    _git(tmp, "commit", "-m", "base")


def _merge_with_upstream_files(tmp: Path) -> None:
    _committed_repo(tmp)
    base_branch = _git(tmp, "branch", "--show-current").stdout.strip()
    _git(tmp, "checkout", "-b", "upstream")
    (tmp / "upstream.py").write_text('API_KEY = "upstream_secret_12345"\n')
    (tmp / "upstream.go").write_text("package upstream\n")
    _git(tmp, "add", "upstream.py", "upstream.go")
    _git(tmp, "commit", "-m", "upstream files")
    _git(tmp, "checkout", base_branch)
    (tmp / "local.txt").write_text("local\n")
    _git(tmp, "add", "local.txt")
    _git(tmp, "commit", "-m", "local work")
    _git(tmp, "merge", "--no-commit", "--no-ff", "upstream")


class TestStagedOwnership:
    """The index and MERGE_HEAD determine what this turn actually staged."""

    def test_preexisting_secret_in_changed_file_does_not_block(self, tmp_path):
        _committed_repo(tmp_path)
        target = tmp_path / "config.py"
        target.write_text('API_KEY = "preexisting_secret_12345"\n')
        _git(tmp_path, "add", "config.py")
        _git(tmp_path, "commit", "-m", "existing secret")
        target.write_text('API_KEY = "preexisting_secret_12345"\nvalue = 1\n')
        _git(tmp_path, "add", "config.py")
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 0, stderr

    def test_upstream_only_secret_during_merge_does_not_block(self, tmp_path):
        _merge_with_upstream_files(tmp_path)
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 0, stderr

    def test_local_head_secret_in_two_parent_merge_does_not_block(self, tmp_path):
        _committed_repo(tmp_path)
        target = tmp_path / "config.py"
        base_lines = [f"value_{i} = {i}\n" for i in range(30)]
        target.write_text("".join(base_lines))
        _git(tmp_path, "add", "config.py")
        _git(tmp_path, "commit", "-m", "shared file")
        base_branch = _git(tmp_path, "branch", "--show-current").stdout.strip()
        _git(tmp_path, "checkout", "-b", "upstream")
        target.write_text("".join(base_lines + ["upstream_value = 1\n"]))
        _git(tmp_path, "add", "config.py")
        _git(tmp_path, "commit", "-m", "harmless upstream addition")
        _git(tmp_path, "checkout", base_branch)
        target.write_text(
            "".join(base_lines[:2] + ['TOKEN = "existing_local_12345"\n'] + base_lines[2:])
        )
        _git(tmp_path, "add", "config.py")
        _git(tmp_path, "commit", "-m", "existing local secret")
        _git(tmp_path, "merge", "--no-commit", "--no-ff", "upstream")
        assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.strip() == "config.py"

        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 0, stderr

    def test_local_staged_secret_survives_unstaged_worktree_removal(self, tmp_path):
        _committed_repo(tmp_path)
        target = tmp_path / "config.py"
        target.write_text('TOKEN = "local_secret_123456"\n')
        _git(tmp_path, "add", "config.py")
        target.write_text("value = 1\n")
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 2, stderr
        assert "Possible hardcoded secret in staged file: config.py" in stderr

    def test_added_line_resembling_diff_header_still_blocks(self, tmp_path):
        _committed_repo(tmp_path)
        target = tmp_path / "config.txt"
        target.write_text('++ API_KEY = "local_secret_123456"\n')
        _git(tmp_path, "add", "config.txt")
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 2, stderr
        assert "Possible hardcoded secret in staged file: config.txt" in stderr

    def test_color_diff_config_cannot_hide_staged_secret(self, tmp_path):
        _committed_repo(tmp_path)
        _git(tmp_path, "config", "color.diff", "always")
        target = tmp_path / "config.txt"
        target.write_text('API_KEY = "local_secret_123456"\n')
        _git(tmp_path, "add", "config.txt")
        assert "\x1b[" in _git(tmp_path, "diff", "--cached", "--unified=0").stdout
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 2, stderr
        assert "Possible hardcoded secret in staged file: config.txt" in stderr

    def test_rename_preserves_secret_ownership_but_new_secret_blocks(self, tmp_path):
        _committed_repo(tmp_path)
        source = tmp_path / "old_config.txt"
        source.write_text(
            'API_KEY = "preexisting_secret_12345"\n'
            'TOKEN = "preexisting_token_12345"\n'
            'PASSWORD = "preexisting_password_12345"\n'
        )
        _git(tmp_path, "add", "old_config.txt")
        _git(tmp_path, "commit", "-m", "existing secret")
        _git(tmp_path, "mv", "old_config.txt", "new_config.txt")

        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 0, stderr

        destination = tmp_path / "new_config.txt"
        destination.write_text(
            destination.read_text() + 'TOKEN = "new_local_secret_12345"\n'
        )
        _git(tmp_path, "add", "new_config.txt")
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 2, stderr
        assert "Possible hardcoded secret in staged file: new_config.txt" in stderr

    def test_local_staged_secret_during_merge_still_blocks(self, tmp_path):
        _merge_with_upstream_files(tmp_path)
        target = tmp_path / "upstream.py"
        target.write_text(target.read_text() + 'TOKEN = "local_secret_123456"\n')
        _git(tmp_path, "add", "upstream.py")
        code, _, stderr = run_hook(cwd=str(tmp_path))
        assert code == 2, stderr
        assert "Possible hardcoded secret in staged file: upstream.py" in stderr

    def test_stop_does_not_run_source_writing_formatters_during_merge(self, tmp_path):
        _merge_with_upstream_files(tmp_path)
        local_py = tmp_path / "local.py"
        local_go = tmp_path / "local.go"
        local_py.write_text("value = 1\n")
        local_go.write_text("package local\n")
        _git(tmp_path, "add", "local.py", "local.go")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "formatter.log"
        for name in ("ruff", "gofmt"):
            tool = bin_dir / name
            tool.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                "with open(os.environ['FORMAT_LOG'], 'a') as out:\n"
                "    out.write(sys.argv[0].split('/')[-1] + ':' + sys.argv[-1] + '\\n')\n"
                "with open(sys.argv[-1], 'a') as out:\n"
                "    out.write('\\n')\n"
            )
            tool.chmod(0o755)
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FORMAT_LOG": str(log),
        }
        code, _, stderr = run_hook(cwd=str(tmp_path), env=env)
        assert code == 0, stderr
        assert not log.exists()
        assert local_py.read_text() == "value = 1\n"
        assert local_go.read_text() == "package local\n"
        assert (tmp_path / "upstream.py").read_text() == 'API_KEY = "upstream_secret_12345"\n'
        assert (tmp_path / "upstream.go").read_text() == "package upstream\n"
        assert not _git(tmp_path, "diff", "--name-only").stdout.strip()

    def test_stop_does_not_format_peer_session_dirty_files(self, tmp_path):
        _committed_repo(tmp_path)
        peer_py = tmp_path / "peer.py"
        peer_go = tmp_path / "peer.go"
        peer_py.write_text("value=  1\n")
        peer_go.write_text("package peer\n\nvar Value=1\n")
        before = {path: path.read_bytes() for path in (peer_py, peer_go)}
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "formatter.log"
        for name in ("ruff", "gofmt"):
            tool = bin_dir / name
            tool.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                "pathlib.Path(os.environ['FORMAT_LOG']).write_text(sys.argv[0])\n"
                "pathlib.Path(sys.argv[-1]).write_text('rewritten\\n')\n"
            )
            tool.chmod(0o755)
        code, _, stderr = run_hook(cwd=str(tmp_path), env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FORMAT_LOG": str(log),
        })
        assert code == 0, stderr
        assert not log.exists()
        assert {path: path.read_bytes() for path in before} == before


# =============================================================================
# Env File Detection Tests
# =============================================================================


class TestEnvFileDetection:
    """Test that .env files in staging are detected."""

    def test_detect_env_staged(self):
        """VC4: Warns if .env file is in git staging area."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                ["git", "init"], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )

            env_file = Path(tmpdir) / ".env"
            env_file.write_text("DATABASE_URL=postgres://localhost\n")

            subprocess.run(
                ["git", "add", ".env"], cwd=tmpdir, capture_output=True, check=False
            )

            exit_code, _, stderr = run_hook(cwd=tmpdir)

            assert exit_code == 2, f"Should exit 2 for .env staged. stderr: {stderr}"
            assert ".env" in stderr


# =============================================================================
# Non-Git Directory Tests
# =============================================================================


class TestNonGitDirectory:
    """Test behavior in non-git directories."""

    def test_non_git_directory_passes(self):
        """Hook should pass in non-git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, _, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0, "Should exit 0 in non-git directory"


# =============================================================================
# Verbose Mode Tests
# =============================================================================


class TestVerboseMode:
    """Test verbose logging."""

    def test_verbose_logging_with_changes(self):
        """CLAUDE_HOOK_VERBOSE=true enables logging when changes exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init repo with uncommitted file
            subprocess.run(
                ["git", "init"], cwd=tmpdir, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            (Path(tmpdir) / "file.txt").write_text("content\n")
            subprocess.run(
                ["git", "add", "file.txt"], cwd=tmpdir, capture_output=True, check=False
            )

            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            del exit_code
            assert (
                "[end-of-turn]" in stderr
            ), f"Should have verbose logs. stderr: {stderr}"
            assert "Changes detected" in stderr

    def test_quiet_by_default(self):
        """No verbose logs by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, _, stderr = run_hook(cwd=tmpdir)
            del exit_code
            assert (
                "[end-of-turn]" not in stderr
            ), "Should not have verbose logs by default"


# =============================================================================
# Output Format Tests
# =============================================================================


class TestOutputFormat:
    """Test that hook outputs valid JSON."""

    def test_outputs_empty_json_on_success(self):
        """Should output {} on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, stdout, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0
            assert stdout.strip() == "{}"


def _setup_git_repo(tmp: Path) -> None:
    """Initialise a bare git repo with one commit in *tmp*."""
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True, check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp, capture_output=True, check=False,
    )
    (tmp / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True, check=False,
    )


# =============================================================================
# Go Build Config Tests
# =============================================================================

GO_AVAILABLE = shutil.which("go") is not None


class TestGoCheckConfig:
    """Tests for .map/config.yaml checks.go.* knobs (issue #435)."""

    def _make_go_project(self, tmp: Path) -> None:
        """Write a minimal Go project with a compile error into *tmp*."""
        (tmp / "go.mod").write_text("module example.com/hook_test\n\ngo 1.21\n")
        # This file references an undefined symbol so 'go build ./...' fails.
        (tmp / "main.go").write_text(
            "package main\n\nfunc main() { undefinedSymbolThatDoesNotExist() }\n"
        )

    def _make_map_config(self, tmp: Path, content: str) -> None:
        map_dir = tmp / ".map"
        map_dir.mkdir(exist_ok=True)
        (map_dir / "config.yaml").write_text(content)

    def test_read_map_config_value_no_file(self):
        """Helper returns default when .map/config.yaml is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _setup_git_repo(tmp)
            # No .map/config.yaml — write a trivial untracked file to keep
            # the hook from exiting early on 'no changes'.
            (tmp / "touch.txt").write_text("x\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            # Hook must still pass (no go.mod present).
            exit_code, _, _ = run_hook(cwd=str(tmp))
            assert exit_code == 0

    def test_go_build_disabled_via_config(self):
        """checks.go.build: false skips the Go build check entirely."""
        if not GO_AVAILABLE:
            import pytest
            pytest.skip("go not in PATH")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _setup_git_repo(tmp)
            self._make_go_project(tmp)
            self._make_map_config(tmp, "checks.go.build: false\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            exit_code, _, stderr = run_hook(cwd=str(tmp))
            assert exit_code == 0, (
                f"build check disabled via config but hook still failed; stderr: {stderr}"
            )
            assert "Go build errors" not in stderr

    def test_go_build_enabled_by_default_catches_errors(self):
        """Without config, a broken Go project is still caught."""
        if not GO_AVAILABLE:
            import pytest
            pytest.skip("go not in PATH")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _setup_git_repo(tmp)
            self._make_go_project(tmp)
            # No .map/config.yaml — default behaviour must report the error.
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            exit_code, _, stderr = run_hook(cwd=str(tmp))
            assert exit_code == 2, (
                f"broken Go project should exit 2 by default; stderr: {stderr}"
            )
            assert "Go build errors" in stderr

    def test_go_goos_from_env_respected(self):
        """GOOS env var is forwarded to go build (existing behaviour preserved)."""
        if not GO_AVAILABLE:
            import pytest
            pytest.skip("go not in PATH")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _setup_git_repo(tmp)
            # A valid, portable Go project.
            (tmp / "go.mod").write_text("module example.com/hook_env_test\n\ngo 1.21\n")
            (tmp / "main.go").write_text("package main\n\nfunc main() {}\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            # Should succeed with an explicit GOOS that matches the current platform.
            import platform
            host_os = platform.system().lower()
            exit_code, _, stderr = run_hook(cwd=str(tmp), env={"GOOS": host_os})
            assert exit_code == 0, f"valid Go project should pass; stderr: {stderr}"

    def test_go_goos_from_config(self):
        """checks.go.goos in config sets the GOOS used by go build."""
        if not GO_AVAILABLE:
            import pytest
            pytest.skip("go not in PATH")
        import platform
        host_os = platform.system().lower()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _setup_git_repo(tmp)
            (tmp / "go.mod").write_text("module example.com/hook_cfg_test\n\ngo 1.21\n")
            (tmp / "main.go").write_text("package main\n\nfunc main() {}\n")
            # Set checks.go.goos to the host OS so the build succeeds.
            self._make_map_config(tmp, f"checks.go.goos: {host_os}\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            exit_code, _, stderr = run_hook(cwd=str(tmp))
            assert exit_code == 0, (
                f"valid project with matching checks.go.goos should pass; stderr: {stderr}"
            )

    def test_go_build_disabled_case_insensitive(self):
        """checks.go.build accepts False/No/Off/0 spellings."""
        if not GO_AVAILABLE:
            import pytest
            pytest.skip("go not in PATH")
        for value in ("False", "No", "Off", "0"):
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                _setup_git_repo(tmp)
                self._make_go_project(tmp)
                self._make_map_config(tmp, f"checks.go.build: {value}\n")
                subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
                exit_code, _, stderr = run_hook(cwd=str(tmp))
                assert exit_code == 0, (
                    f"checks.go.build: {value!r} should disable check; stderr: {stderr}"
                )


class TestGoBuildTags:
    """Observe the real Stop hook at the go process boundary (#489)."""

    @pytest.mark.parametrize("goos", ["", "linux"])
    def test_configured_tags_reach_go_build(self, tmp_path, goos):
        exit_code, _, stderr, call = self._run_build(
            tmp_path, "checks.go.tags: integration,netgo\n", goos=goos,
        )
        assert call == {
            "argv": ["build", "-tags", "integration,netgo", "-o", "/dev/null", "./..."],
            "goos": goos,
        }
        assert exit_code == 0, stderr

    @pytest.mark.parametrize("goos", ["", "linux"])
    @pytest.mark.parametrize("config", ["", "checks.go.tags:\n"])
    def test_default_build_has_no_tags_argument(self, tmp_path, goos, config):
        exit_code, _, stderr, call = self._run_build(tmp_path, config, goos=goos)
        assert call == {
            "argv": ["build", "-o", "/dev/null", "./..."], "goos": goos,
        }
        assert exit_code == 0, stderr

    def test_env_goos_still_overrides_config_with_tags(self, tmp_path):
        exit_code, _, stderr, call = self._run_build(
            tmp_path, "checks.go.tags: netgo\n", goos="linux", env_goos="darwin",
        )
        assert call == {
            "argv": ["build", "-tags", "netgo", "-o", "/dev/null", "./..."],
            "goos": "darwin",
        }
        assert exit_code == 0, stderr

    @pytest.mark.parametrize("goos", ["", "linux"])
    def test_tagged_build_errors_still_block(self, tmp_path, goos):
        exit_code, _, stderr, call = self._run_build(
            tmp_path, "checks.go.tags: netgo\n", goos=goos, fail=True,
        )
        assert call is not None
        assert exit_code == 2
        assert "Go build errors detected" in stderr

    def test_disabled_build_does_not_invoke_go_even_with_tags(self, tmp_path):
        exit_code, _, stderr, call = self._run_build(
            tmp_path, "checks.go.build: false\nchecks.go.tags: netgo\n", fail=True,
        )
        assert call is None
        assert exit_code == 0, stderr

    @pytest.mark.parametrize("goos", ["", "linux"])
    def test_tags_are_literal_not_shell_syntax(self, tmp_path, goos):
        tags = "netgo,$(touch${IFS}injected);`touch${IFS}backtick`,$HOME,*"
        exit_code, _, stderr, call = self._run_build(
            tmp_path, f"checks.go.tags: {tags}\n", goos=goos,
        )
        assert call == {
            "argv": ["build", "-tags", tags, "-o", "/dev/null", "./..."],
            "goos": goos,
        }
        assert not (tmp_path / "injected").exists()
        assert not (tmp_path / "backtick").exists()
        assert exit_code == 0, stderr

    def _run_build(self, tmp, config, *, goos="", env_goos="", fail=False):
        _setup_git_repo(tmp)
        (tmp / "go.mod").write_text("module example.com/hook_tags\n\ngo 1.21\n")
        (tmp / "main.go").write_text("package main\n\nfunc main() {}\n")
        (tmp / ".map").mkdir()
        (tmp / ".map" / "config.yaml").write_text(
            config + f"checks.go.goos: {goos}\n",
        )
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        capture = tmp / "go-call.json"
        go = bin_dir / "go"
        go.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['GO_CAPTURE']).write_text(json.dumps({\n"
            "    'argv': sys.argv[1:], 'goos': os.environ.get('GOOS', '')}))\n"
            "sys.exit(int(os.environ['GO_FAIL']))\n",
        )
        go.chmod(0o755)
        # Keep formatting deterministic and independent of a local Go installation.
        gofmt = bin_dir / "gofmt"
        gofmt.write_text("#!/bin/sh\nexit 0\n")
        gofmt.chmod(0o755)
        subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=True)
        exit_code, stdout, stderr = run_hook(cwd=str(tmp), env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GO_CAPTURE": str(capture), "GO_FAIL": "1" if fail else "0",
            "GOOS": env_goos, "MAP_INVOKED_BY": "",
        })
        call = json.loads(capture.read_text()) if capture.exists() else None
        return exit_code, stdout, stderr, call


class TestSyntaxCheckHygiene:
    """Regression: the syntax-check pass must not leave __pycache__/*.pyc.

    Before this hardening the hook called ``python3 -m py_compile <file>``,
    which writes ``__pycache__/*.pyc`` next to the source even with ``-B``
    (emitting bytecode is py_compile's entire job). Touching any .py under
    ``.map/scripts/`` or ``src/mapify_cli/templates/`` then left a tracked
    ``__pycache__/`` directory that the template-hygiene gate rejects.
    The replacement uses ``ast.parse`` which only parses, never writes.
    """

    def test_hook_does_not_write_pycache_next_to_changed_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "t@t.com"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "t"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )
            (tmp / "seed.txt").write_text("seed\n")
            subprocess.run(
                ["git", "add", "."], cwd=tmp, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )

            # Add a changed .py file with valid syntax to trigger the
            # syntax-check loop.
            py_file = tmp / "module_under_check.py"
            py_file.write_text("x = 1\n")
            subprocess.run(
                ["git", "add", "."], cwd=tmp, capture_output=True, check=False
            )

            exit_code, _, _ = run_hook(cwd=str(tmp))
            assert exit_code == 0, "syntax-check must pass for valid .py"

            pycache_dirs = list(tmp.rglob("__pycache__"))
            pyc_files = list(tmp.rglob("*.pyc"))
            assert not pycache_dirs, (
                f"hook must not create __pycache__ next to changed files; "
                f"found: {pycache_dirs}"
            )
            assert not pyc_files, f"hook must not create .pyc files; found: {pyc_files}"

    def test_hook_still_catches_syntax_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "t@t.com"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "t"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )
            (tmp / "seed.txt").write_text("seed\n")
            subprocess.run(
                ["git", "add", "."], cwd=tmp, capture_output=True, check=False
            )
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=tmp,
                capture_output=True,
                check=False,
            )

            (tmp / "broken.py").write_text("def f(:\n    pass\n")
            subprocess.run(
                ["git", "add", "."], cwd=tmp, capture_output=True, check=False
            )

            exit_code, _, stderr = run_hook(cwd=str(tmp))
            assert (
                exit_code == 2
            ), "broken Python must trigger critical-issue blocking exit"
            assert "Python syntax error" in stderr, stderr


def _init_git(tmp: Path) -> None:
    """Init a git repo with identity configured (no commits made)."""
    subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=tmp,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp,
        capture_output=True,
        check=False,
    )


class TestRegressionStopHookAndNoCommit:
    """Regression tests for the Stop-hook livelock (#437) and the no-commit
    changed-file false positives (#438)."""

    def test_stop_hook_active_lets_turn_end(self):
        """A blocked Stop hook is re-invoked with stop_hook_active=true; the
        hook must exit 0 so the turn can end instead of livelocking (#437)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _init_git(tmp)
            (tmp / "broken.py").write_text("def f(:\n    pass\n")

            # Without the flag the finding blocks.
            code, _, stderr = run_hook(cwd=str(tmp))
            assert code == 2, stderr

            # With stop_hook_active=true the hook lets the turn end.
            payload = json.dumps({"session_id": "s1", "stop_hook_active": True})
            code, stdout, _ = run_hook(cwd=str(tmp), input_text=payload)
            assert code == 0, "stop_hook_active=true must exit 0"
            assert stdout.strip() == "{}"

    def test_self_cap_stops_blocking_persistent_finding(self):
        """A finding that persists across turns must stop blocking after the
        cap (default 3), downgrading to a non-blocking warning (#437)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _init_git(tmp)
            broken = tmp / "broken.py"
            broken.write_text("def f(:\n    pass\n")

            # The no-commit snapshot (#438) stops re-gating untouched files, so
            # simulate the real re-fire scenario (the file is touched again each
            # turn while the error persists) by bumping the mtime.
            for _ in range(3):
                os.utime(broken, (time.time() + 60, time.time() + 60))
                code, _, stderr = run_hook(cwd=str(tmp))
                assert code == 2, stderr

            os.utime(broken, (time.time() + 60, time.time() + 60))
            code, _, stderr = run_hook(cwd=str(tmp))
            assert code == 1, f"expected downgraded warning, got {code}: {stderr}"
            assert "self-capped" in stderr

    def test_self_cap_resets_when_finding_changes(self):
        """The cap counts consecutive identical findings only; a different
        finding starts a fresh count and blocks again (#437)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _init_git(tmp)
            broken = tmp / "broken.py"
            broken.write_text("def f(:\n    pass\n")

            for _ in range(3):
                os.utime(broken, (time.time() + 60, time.time() + 60))
                code, _, _ = run_hook(cwd=str(tmp))
                assert code == 2

            # Different finding: fix broken.py and break another file.
            broken.write_text("x = 1\n")
            broken2 = tmp / "broken2.py"
            broken2.write_text("def g(:\n    pass\n")
            os.utime(broken, (time.time() + 60, time.time() + 60))
            os.utime(broken2, (time.time() + 60, time.time() + 60))

            code, _, stderr = run_hook(cwd=str(tmp))
            assert code == 2, f"new finding must block again: {stderr}"

    def test_no_commit_repo_gates_only_current_turn_files(self):
        """#438: before the first commit every file is untracked; the
        per-language gates must not re-fire on files from previous turns, so a
        docs-only turn is not gated on unrelated sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _init_git(tmp)
            (tmp / "broken.py").write_text("def f(:\n    pass\n")

            # Turn 1: broken.py is new -> the gate blocks.
            code, _, stderr = run_hook(cwd=str(tmp))
            assert code == 2, stderr

            # Turn 2: only docs touched; broken.py unchanged -> no block.
            (tmp / "README.md").write_text("# Docs\n")
            code, _, stderr = run_hook(cwd=str(tmp))
            assert code == 0, f"docs-only turn must pass: {stderr}"
