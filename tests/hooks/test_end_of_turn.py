"""
Pytest tests for .claude/hooks/end-of-turn.sh Stop hook.

Tests the lightweight version that:
- Only runs if there are uncommitted changes
- Checks only changed files
- Auto-fixes what it can
- Only reports critical issues (secrets, .env files, syntax errors)
"""
import os
import subprocess
import tempfile
from pathlib import Path

# Path to the hook script
HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "end-of-turn.sh"


def run_hook(cwd: str | None = None, env: dict | None = None) -> tuple[int, str, str]:
    """Execute the hook in given directory."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        ["bash", str(HOOK_PATH)], capture_output=True, text=True, cwd=cwd, env=run_env,
        check=False,
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
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True,
                check=False,
            )
            # Create and commit a file
            (Path(tmpdir) / "file.txt").write_text("content\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True,
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
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True,
                check=False,
            )

            # Create file with secret
            secret_file = Path(tmpdir) / "config.py"
            secret_file.write_text('API_KEY = "sk_live_1234567890abcdef"\n')

            # Stage it
            subprocess.run(["git", "add", "config.py"], cwd=tmpdir, capture_output=True, check=False)

            # Run hook
            exit_code, _, stderr = run_hook(cwd=tmpdir)

            # Should detect secret and return exit 2
            assert exit_code == 2, f"Should exit 2 for secrets. stderr: {stderr}"
            assert "secret" in stderr.lower() or "config.py" in stderr

    def test_no_secret_in_clean_file(self):
        """No false positives for clean files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True,
                check=False,
            )

            clean_file = Path(tmpdir) / "clean.py"
            clean_file.write_text('print("Hello")\n')

            subprocess.run(["git", "add", "clean.py"], cwd=tmpdir, capture_output=True, check=False)

            exit_code, _, _ = run_hook(cwd=tmpdir)
            assert exit_code == 0, "Should exit 0 for clean file"


# =============================================================================
# Env File Detection Tests
# =============================================================================


class TestEnvFileDetection:
    """Test that .env files in staging are detected."""

    def test_detect_env_staged(self):
        """VC4: Warns if .env file is in git staging area."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True,
                check=False,
            )

            env_file = Path(tmpdir) / ".env"
            env_file.write_text("DATABASE_URL=postgres://localhost\n")

            subprocess.run(["git", "add", ".env"], cwd=tmpdir, capture_output=True, check=False)

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
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True,
                check=False,
            )
            (Path(tmpdir) / "file.txt").write_text("content\n")
            subprocess.run(["git", "add", "file.txt"], cwd=tmpdir, capture_output=True, check=False)

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
                ["git", "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "t"], cwd=tmp, capture_output=True,
                check=False,
            )
            (tmp / "seed.txt").write_text("seed\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            subprocess.run(
                ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True,
                check=False,
            )

            # Add a changed .py file with valid syntax to trigger the
            # syntax-check loop.
            py_file = tmp / "module_under_check.py"
            py_file.write_text("x = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)

            exit_code, _, _ = run_hook(cwd=str(tmp))
            assert exit_code == 0, "syntax-check must pass for valid .py"

            pycache_dirs = list(tmp.rglob("__pycache__"))
            pyc_files = list(tmp.rglob("*.pyc"))
            assert not pycache_dirs, (
                f"hook must not create __pycache__ next to changed files; "
                f"found: {pycache_dirs}"
            )
            assert not pyc_files, (
                f"hook must not create .pyc files; found: {pyc_files}"
            )

    def test_hook_still_catches_syntax_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=False)
            subprocess.run(
                ["git", "config", "user.email", "t@t.com"], cwd=tmp, capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.name", "t"], cwd=tmp, capture_output=True,
                check=False,
            )
            (tmp / "seed.txt").write_text("seed\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)
            subprocess.run(
                ["git", "commit", "-m", "init"], cwd=tmp, capture_output=True,
                check=False,
            )

            (tmp / "broken.py").write_text("def f(:\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=tmp, capture_output=True, check=False)

            exit_code, _, stderr = run_hook(cwd=str(tmp))
            assert exit_code == 2, (
                "broken Python must trigger critical-issue blocking exit"
            )
            assert "Python syntax error" in stderr, stderr
