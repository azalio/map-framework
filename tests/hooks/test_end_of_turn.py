#!/usr/bin/env python3
"""
Pytest tests for .claude/hooks/end-of-turn.sh Stop hook.
Tests all validation criteria and edge cases.
"""
import subprocess
import tempfile
import os
from pathlib import Path

# Path to the hook script
HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "end-of-turn.sh"


def run_hook(cwd: str = None, env: dict = None) -> tuple[int, str, str]:
    """Execute the hook in given directory."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        ["bash", str(HOOK_PATH)], capture_output=True, text=True, cwd=cwd, env=run_env
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
# Project Detection Tests
# =============================================================================


class TestProjectDetection:
    """Test that project types are correctly detected."""

    def test_detect_python_pyproject(self):
        """VC1: Detects Python project via pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pyproject.toml
            (Path(tmpdir) / "pyproject.toml").write_text("[project]\nname='test'\n")
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "Detected Python project" in stderr

    def test_detect_python_requirements(self):
        """Detects Python project via requirements.txt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "requirements.txt").write_text("pytest\n")
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "Detected Python project" in stderr

    def test_detect_nodejs(self):
        """VC2: Detects Node.js project via package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "package.json").write_text('{"name": "test"}\n')
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "Detected Node.js project" in stderr

    def test_detect_go(self):
        """Detects Go project via go.mod."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "go.mod").write_text("module test\n")
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "Detected Go project" in stderr

    def test_detect_rust(self):
        """Detects Rust project via Cargo.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "Cargo.toml").write_text("[package]\nname='test'\n")
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "Detected Rust project" in stderr


# =============================================================================
# Secret Detection Tests
# =============================================================================


class TestSecretDetection:
    """Test that secrets are detected in staged files."""

    def test_detect_api_key_in_staged(self):
        """VC3: Secret scanning finds 'API_KEY=abc123' pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True
            )

            # Create file with secret
            secret_file = Path(tmpdir) / "config.py"
            secret_file.write_text('API_KEY = "sk_live_1234567890abcdef"\n')

            # Stage it
            subprocess.run(["git", "add", "config.py"], cwd=tmpdir, capture_output=True)

            # Run hook
            exit_code, _, stderr = run_hook(cwd=tmpdir)

            # Should detect secret and return exit 2
            assert exit_code == 2, f"Should exit 2 for secrets. stderr: {stderr}"
            assert "secret" in stderr.lower() or "config.py" in stderr

    def test_no_secret_in_clean_file(self):
        """No false positives for clean files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True
            )

            clean_file = Path(tmpdir) / "clean.py"
            clean_file.write_text('print("Hello")\n')

            subprocess.run(["git", "add", "clean.py"], cwd=tmpdir, capture_output=True)

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
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True
            )

            env_file = Path(tmpdir) / ".env"
            env_file.write_text("DATABASE_URL=postgres://localhost\n")

            subprocess.run(["git", "add", ".env"], cwd=tmpdir, capture_output=True)

            exit_code, _, stderr = run_hook(cwd=tmpdir)

            assert exit_code == 2, f"Should exit 2 for .env staged. stderr: {stderr}"
            assert ".env" in stderr

    def test_env_local_staged(self):
        """Warns if .env.local is staged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=tmpdir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True
            )

            env_file = Path(tmpdir) / ".env.local"
            env_file.write_text("SECRET=value\n")

            subprocess.run(
                ["git", "add", ".env.local"], cwd=tmpdir, capture_output=True
            )

            exit_code, _, stderr = run_hook(cwd=tmpdir)

            assert exit_code == 2, "Should exit 2 for .env.local staged"


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

    def test_verbose_logging(self):
        """CLAUDE_HOOK_VERBOSE=true enables logging."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, _, stderr = run_hook(
                cwd=tmpdir, env={"CLAUDE_HOOK_VERBOSE": "true"}
            )
            assert "[end-of-turn]" in stderr, "Should have verbose logs"
            assert "Starting end-of-turn checks" in stderr

    def test_quiet_by_default(self):
        """No verbose logs by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code, _, stderr = run_hook(cwd=tmpdir)
            assert (
                "[end-of-turn]" not in stderr
            ), "Should not have verbose logs by default"
