"""Tests for repository insight generation."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mapify_cli.repo_insight import (
    compute_differential_insight,
    create_repo_insight,
    detect_language,
    generate_key_dirs,
    generate_suggested_checks,
)


class TestDetectLanguage:
    """Tests for detect_language function (ST-007)."""

    def test_detects_python_from_pyproject(self):
        """Should return 'python' when pyproject.toml exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()

            result = detect_language(project_root)
            assert result == "python"

    def test_detects_python_from_setup_py(self):
        """Should return 'python' when setup.py exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "setup.py").touch()

            result = detect_language(project_root)
            assert result == "python"

    def test_detects_python_from_requirements(self):
        """Should return 'python' when requirements.txt exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "requirements.txt").touch()

            result = detect_language(project_root)
            assert result == "python"

    def test_detects_typescript_over_javascript(self):
        """Should return 'typescript' when both tsconfig.json and package.json exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "tsconfig.json").touch()
            (project_root / "package.json").touch()

            result = detect_language(project_root)
            assert result == "typescript"

    def test_detects_javascript(self):
        """Should return 'javascript' when only package.json exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "package.json").touch()

            result = detect_language(project_root)
            assert result == "javascript"

    def test_detects_go(self):
        """Should return 'go' when go.mod exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "go.mod").touch()

            result = detect_language(project_root)
            assert result == "go"

    def test_detects_rust(self):
        """Should return 'rust' when Cargo.toml exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "Cargo.toml").touch()

            result = detect_language(project_root)
            assert result == "rust"

    def test_returns_unknown_when_no_markers(self):
        """Should return 'unknown' when no marker files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = detect_language(project_root)
            assert result == "unknown"

    def test_priority_order_typescript_before_python(self):
        """Should prioritize TypeScript over Python."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "tsconfig.json").touch()
            (project_root / "pyproject.toml").touch()

            result = detect_language(project_root)
            assert result == "typescript"


class TestGenerateSuggestedChecks:
    """Tests for generate_suggested_checks function (ST-008)."""

    def test_python_commands_with_makefile(self):
        """Should return Python-specific commands when language='python' and Makefile exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "Makefile").touch()

            result = generate_suggested_checks("python", project_root)

            assert "make check" in result
            assert "pytest tests/test_template_render.py -v" in result
            assert "make render-templates" in result

    def test_python_filters_make_without_makefile(self):
        """Should filter out 'make' commands when Makefile doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("python", project_root)

            # Should not include make commands
            assert not any(cmd.startswith("make ") for cmd in result)
            # Should still include pytest
            assert "pytest tests/test_template_render.py -v" in result

    def test_javascript_commands(self):
        """Should return JavaScript-specific commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("javascript", project_root)

            assert "npm run lint" in result
            assert "npm test" in result
            assert len(result) >= 1

    def test_typescript_commands(self):
        """Should return TypeScript-specific commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("typescript", project_root)

            assert "npm run lint" in result
            assert "npm test" in result

    def test_go_commands(self):
        """Should return Go-specific commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("go", project_root)

            assert "go test ./..." in result
            assert "go vet ./..." in result
            assert len(result) >= 1

    def test_rust_commands(self):
        """Should return Rust-specific commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("rust", project_root)

            assert "cargo test" in result
            assert "cargo clippy" in result
            assert len(result) >= 1

    def test_unknown_language_with_makefile(self):
        """Should suggest 'make check' for unknown language when Makefile exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "Makefile").touch()

            result = generate_suggested_checks("unknown", project_root)

            assert result == ["make check"]

    def test_unknown_language_without_makefile(self):
        """Should return empty list for unknown language when no Makefile exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_suggested_checks("unknown", project_root)

            assert result == []


class TestGenerateKeyDirs:
    """Tests for generate_key_dirs function (ST-009)."""

    def test_returns_only_existing_directories(self):
        """Should return only directories that exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()

            result = generate_key_dirs(project_root)

            assert "src" in result
            assert "tests" in result
            assert "lib" not in result  # Doesn't exist

    def test_returns_relative_paths(self):
        """All returned paths should be relative (no leading /)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "src").mkdir()

            result = generate_key_dirs(project_root)

            for path in result:
                assert not path.startswith("/")

    def test_maximum_5_directories(self):
        """Should return maximum 5 directories even if more exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            # Create more than 5 directories
            for dirname in [
                "src",
                "tests",
                "lib",
                "pkg",
                "cmd",
                "internal",
                ".claude",
                ".map",
            ]:
                (project_root / dirname).mkdir()

            result = generate_key_dirs(project_root)

            assert len(result) <= 5

    def test_empty_list_when_no_standard_dirs(self):
        """Should return empty list when no standard directories exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = generate_key_dirs(project_root)

            assert result == []

    def test_ignores_files(self):
        """Should only return directories, not files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "src").touch()  # File, not directory
            (project_root / "tests").mkdir()  # Directory

            result = generate_key_dirs(project_root)

            assert "src" not in result
            assert "tests" in result


class TestCreateRepoInsight:
    """Tests for create_repo_insight function (ST-010)."""

    def test_writes_valid_json_file(self):
        """Should write valid JSON to .map/repo_insight_<branch>.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()
            (project_root / "src").mkdir()

            output_path = create_repo_insight(project_root, "main")

            assert output_path.exists()
            assert output_path.name == "repo_insight_main.json"

            # Verify valid JSON
            with output_path.open() as f:
                data = json.load(f)

            assert isinstance(data, dict)

    def test_validates_against_schema(self):
        """Created JSON should validate against repo_insight schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()
            (project_root / "Makefile").touch()
            (project_root / "src").mkdir()

            output_path = create_repo_insight(project_root, "feature-x")

            with output_path.open() as f:
                data = json.load(f)

            # Check schema fields
            assert "language" in data
            assert "suggested_checks" in data
            assert "key_dirs" in data

            # Check types
            assert isinstance(data["language"], str)
            assert isinstance(data["suggested_checks"], list)
            assert isinstance(data["key_dirs"], list)

            # Check constraints
            assert len(data["key_dirs"]) <= 5
            for dir_path in data["key_dirs"]:
                assert not dir_path.startswith("/")

    def test_creates_map_directory_if_missing(self):
        """Should create .map/ directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()

            map_dir = project_root / ".map"
            assert not map_dir.exists()

            create_repo_insight(project_root, "test-branch")

            assert map_dir.exists()
            assert map_dir.is_dir()

    def test_returns_path_to_created_file(self):
        """Should return Path object pointing to created file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").touch()

            result = create_repo_insight(project_root, "dev")

            assert isinstance(result, Path)
            assert result.exists()
            assert result.parent.name == ".map"

    def test_integration_with_all_functions(self):
        """Correctly integrates detect_language, generate_suggested_checks, generate_key_dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            # Setup Python project
            (project_root / "pyproject.toml").touch()
            (project_root / "Makefile").touch()
            (project_root / "src").mkdir()
            (project_root / "tests").mkdir()

            output_path = create_repo_insight(project_root, "main")

            with output_path.open() as f:
                data = json.load(f)

            # Verify integration
            assert data["language"] == "python"
            assert "make check" in data["suggested_checks"]
            assert "src" in data["key_dirs"]
            assert "tests" in data["key_dirs"]

    def test_unknown_language_still_produces_valid_json(self):
        """Unknown language should still pass validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = create_repo_insight(project_root, "test")

            with result.open() as f:
                data = json.load(f)

            # Unknown language should still pass validation
            assert data["language"] == "unknown"


class TestComputeDifferentialInsight:
    """Tests for compute_differential_insight function."""

    def test_none_sha_returns_note(self):
        """Should return empty lists with note when since_sha is None."""
        result = compute_differential_insight(Path("/tmp"), None)
        assert result["changed_files"] == []
        assert result["deleted_files"] == []
        assert "note" in result

    def test_valid_diff_returns_files(self):
        """Should return changed and deleted files on successful git diff."""
        mock_changed = MagicMock(returncode=0, stdout="a.py\nb.py\n")
        mock_deleted = MagicMock(returncode=0, stdout="old.py\n")
        mock_head = MagicMock(returncode=0, stdout="abc123\n")

        with patch(
            "subprocess.run", side_effect=[mock_changed, mock_deleted, mock_head]
        ):
            result = compute_differential_insight(Path("/tmp"), "def456")

        assert result["changed_files"] == ["a.py", "b.py"]
        assert result["deleted_files"] == ["old.py"]
        assert result["since_sha"] == "def456"
        assert result["current_sha"] == "abc123"

    def test_git_failure_returns_error(self):
        """Should return error dict when git diff fails."""
        mock_fail = MagicMock(returncode=1, stderr="fatal: bad object")

        with patch("subprocess.run", return_value=mock_fail):
            result = compute_differential_insight(Path("/tmp"), "badsha")

        assert result["changed_files"] == []
        assert result["deleted_files"] == []
        assert "error" in result

    def test_timeout_returns_error(self):
        """Should return error dict on subprocess timeout."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 2)):
            result = compute_differential_insight(Path("/tmp"), "abc123")

        assert result["changed_files"] == []
        assert "error" in result

    def test_file_not_found_returns_error(self):
        """Should return error dict when git is not available."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            result = compute_differential_insight(Path("/tmp"), "abc123")

        assert result["changed_files"] == []
        assert "error" in result
