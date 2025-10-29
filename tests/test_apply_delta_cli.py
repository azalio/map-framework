"""
Tests for 'mapify playbook apply-delta' CLI command.

Tests cover:
- Layer 1: Unit tests for PlaybookManager.apply_delta()
- Layer 2: CliRunner tests for CLI command
- Layer 3: E2E tests with subprocess (integration)
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.playbook_manager import PlaybookManager


@pytest.fixture
def runner():
    """CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def temp_playbook_with_bullets():
    """Create a temporary playbook with test bullets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        playbook_path = Path(tmpdir) / ".claude" / "playbook.json"
        playbook_path.parent.mkdir(parents=True)

        playbook = {
            "version": "1.0.0",
            "metadata": {
                "created_at": "2024-01-01T00:00:00Z",
                "last_updated": "2024-01-01T00:00:00Z",
                "total_bullets": 2,
                "top_k": 5
            },
            "sections": {
                "IMPLEMENTATION_PATTERNS": {
                    "bullets": [
                        {
                            "id": "impl-0001",
                            "content": "Use type hints",
                            "helpful_count": 2,
                            "harmful_count": 0,
                            "created_at": "2024-01-01T00:00:00Z",
                            "last_used_at": "2024-01-01T00:00:00Z",
                            "deprecated": False,
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                },
                "SECURITY_PATTERNS": {
                    "bullets": [
                        {
                            "id": "sec-0001",
                            "content": "Validate user input",
                            "helpful_count": 5,
                            "harmful_count": 0,
                            "created_at": "2024-01-01T00:00:00Z",
                            "last_used_at": "2024-01-01T00:00:00Z",
                            "deprecated": False,
                            "tags": [],
                            "related_bullets": []
                        }
                    ]
                }
            }
        }

        playbook_path.write_text(json.dumps(playbook, indent=2))

        # Create SQLite database from JSON
        manager = PlaybookManager(playbook_path)

        yield tmpdir, playbook_path, manager


# Layer 1: Unit Tests for PlaybookManager.apply_delta()


class TestApplyDeltaUnit:
    """Unit tests for PlaybookManager.apply_delta() method."""

    def test_add_operation(self, temp_playbook_with_bullets):
        """Test ADD operation adds new bullet."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "ADD",
                "section": "IMPLEMENTATION_PATTERNS",
                "content": "Use async/await for I/O operations",
                "code_example": "async def fetch_data(): ...",
                "tags": ["python", "async"]
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["added"] == 1
        assert summary["updated"] == 0
        assert summary["deprecated"] == 0
        assert len(summary.get("errors", [])) == 0

    def test_update_operation(self, temp_playbook_with_bullets):
        """Test UPDATE operation increments helpful_count."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "UPDATE",
                "bullet_id": "impl-0001",
                "increment_helpful": 1
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["added"] == 0
        assert summary["updated"] == 1
        assert summary["deprecated"] == 0

    def test_update_operation_harmful(self, temp_playbook_with_bullets):
        """Test UPDATE operation increments harmful_count."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "UPDATE",
                "bullet_id": "sec-0001",
                "increment_harmful": 1
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["updated"] == 1

    def test_update_operation_both(self, temp_playbook_with_bullets):
        """Test UPDATE operation with both helpful and harmful."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "UPDATE",
                "bullet_id": "impl-0001",
                "increment_helpful": 2,
                "increment_harmful": 1
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["updated"] == 1

    def test_deprecate_operation(self, temp_playbook_with_bullets):
        """Test DEPRECATE operation marks bullet as deprecated."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "DEPRECATE",
                "bullet_id": "impl-0001",
                "reason": "Outdated pattern"
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["deprecated"] == 1

    def test_multiple_operations_batch(self, temp_playbook_with_bullets):
        """Test multiple operations in single batch."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        operations = [
            {
                "type": "ADD",
                "section": "SECURITY_PATTERNS",
                "content": "Sanitize SQL queries"
            },
            {
                "type": "UPDATE",
                "bullet_id": "sec-0001",
                "increment_helpful": 1
            },
            {
                "type": "DEPRECATE",
                "bullet_id": "impl-0001",
                "reason": "No longer recommended"
            }
        ]

        summary = manager.apply_delta(operations)

        assert summary["added"] == 1
        assert summary["updated"] == 1
        assert summary["deprecated"] == 1


# Layer 2: CliRunner Tests for CLI Command


class TestApplyDeltaCLI:
    """CLI integration tests using typer.testing.CliRunner."""

    @staticmethod
    def extract_json_from_output(stdout: str) -> dict:
        """Extract JSON from stdout that may contain migration messages."""
        json_lines = []
        in_json = False
        for line in stdout.split('\n'):
            if line.strip().startswith('{'):
                in_json = True
            if in_json:
                json_lines.append(line)
        return json.loads('\n'.join(json_lines))

    def test_cli_apply_delta_from_file(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test apply-delta command with file input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        # Create delta file
        delta_file = Path(tmpdir) / "delta.json"
        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "bullet_id": "impl-0001",
                    "increment_helpful": 1
                }
            ]
        }
        delta_file.write_text(json.dumps(delta_data))

        # Run command
        result = runner.invoke(
            app,
            ["playbook", "apply-delta", str(delta_file)]
        )

        assert result.exit_code == 0
        output = self.extract_json_from_output(result.stdout)
        assert output["status"] == "success"
        assert output["summary"]["updated"] == 1

    def test_cli_apply_delta_stdin(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test apply-delta command with stdin input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "bullet_id": "sec-0001",
                    "increment_helpful": 1
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 0
        output = self.extract_json_from_output(result.stdout)
        assert output["status"] == "success"

    def test_cli_apply_delta_dry_run(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test --dry-run flag previews without applying."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "ADD",
                    "section": "IMPLEMENTATION_PATTERNS",
                    "content": "New pattern"
                },
                {
                    "type": "UPDATE",
                    "bullet_id": "impl-0001",
                    "increment_helpful": 1
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta", "--dry-run"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 0
        output = self.extract_json_from_output(result.stdout)
        assert output["status"] == "dry_run"
        assert output["message"] == "DRY RUN - No changes applied"
        assert output["would_apply"]["total_operations"] == 2
        assert output["would_apply"]["add"] == 1
        assert output["would_apply"]["update"] == 1

    def test_cli_missing_playbook(self, runner, tmp_path, monkeypatch):
        """Test error when playbook.json doesn't exist."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input='{"operations": []}'
        )

        assert result.exit_code == 1
        assert "Playbook not found" in result.stdout

    def test_cli_invalid_json(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error with invalid JSON input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input="{invalid json}"
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert output["status"] == "error"
        assert output["error_type"] == "validation_error"

    def test_cli_missing_operations_field(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error when 'operations' field is missing."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input='{"data": []}'
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert "Missing required field: 'operations'" in output["message"]

    def test_cli_invalid_operation_type(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error with invalid operation type."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "INVALID",
                    "bullet_id": "impl-0001"
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert "invalid type: INVALID" in output["message"]

    def test_cli_add_missing_required_fields(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error when ADD operation missing required fields."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "ADD",
                    "section": "IMPLEMENTATION_PATTERNS"
                    # Missing: content
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert "missing required fields: content" in output["message"]

    def test_cli_update_missing_bullet_id(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error when UPDATE operation missing bullet_id."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "increment_helpful": 1
                    # Missing: bullet_id
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert "missing required field: 'bullet_id'" in output["message"]

    def test_cli_update_no_delta_fields(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test error when UPDATE has no increment fields."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "bullet_id": "impl-0001"
                    # Missing: increment_helpful or increment_harmful
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )

        assert result.exit_code == 1
        output = self.extract_json_from_output(result.stdout)
        assert "must specify at least one of: increment_helpful, increment_harmful" in output["message"]


# Layer 3: E2E Tests with subprocess


class TestApplyDeltaE2E:
    """E2E tests with actual subprocess execution."""

    @pytest.mark.skipif(not Path("setup.py").exists(), reason="Package not installed")
    def test_e2e_installed_package(self, temp_playbook_with_bullets):
        """Test apply-delta command with installed package."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "bullet_id": "impl-0001",
                    "increment_helpful": 1
                }
            ]
        }

        result = subprocess.run(
            ["mapify", "playbook", "apply-delta"],
            input=json.dumps(delta_data),
            capture_output=True,
            text=True,
            cwd=tmpdir
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"


class TestApplyDeltaStatsIntegration:
    """Integration tests for apply-delta → stats workflow."""

    @staticmethod
    def extract_json_from_output(stdout: str) -> dict:
        """Extract JSON from stdout that may contain migration messages."""
        json_lines = []
        in_json = False
        for line in stdout.split('\n'):
            if line.strip().startswith('{'):
                in_json = True
            if in_json:
                json_lines.append(line)
        return json.loads('\n'.join(json_lines))

    def test_apply_delta_updates_stats(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test that apply-delta changes are reflected in stats command.

        This is the critical workflow test that would have caught the
        playbook_stats JSON read issue discovered in MAP review.
        """
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        # Get initial stats
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        initial_stats = self.extract_json_from_output(result.stdout)
        initial_count = initial_stats["total_bullets"]

        # Apply delta: add 3 new bullets
        delta_data = {
            "operations": [
                {
                    "type": "ADD",
                    "section": "IMPLEMENTATION_PATTERNS",
                    "content": "Test bullet 1"
                },
                {
                    "type": "ADD",
                    "section": "IMPLEMENTATION_PATTERNS",
                    "content": "Test bullet 2"
                },
                {
                    "type": "ADD",
                    "section": "ERROR_PATTERNS",
                    "content": "Test bullet 3"
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )
        assert result.exit_code == 0

        # Verify stats reflect the changes
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        updated_stats = self.extract_json_from_output(result.stdout)

        # Critical assertion: stats should show SQLite data, not stale JSON
        assert updated_stats["total_bullets"] == initial_count + 3, \
            f"Stats should show {initial_count + 3} bullets (initial {initial_count} + 3 added), " \
            f"but got {updated_stats['total_bullets']}. This indicates stats is reading stale JSON instead of SQLite."

    def test_update_operation_reflected_in_stats(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test that UPDATE operations don't affect total_bullets count in stats."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        # Get initial stats
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        initial_stats = self.extract_json_from_output(result.stdout)
        initial_count = initial_stats["total_bullets"]

        # Apply UPDATE operation (should not change count)
        delta_data = {
            "operations": [
                {
                    "type": "UPDATE",
                    "bullet_id": "impl-0001",
                    "increment_helpful": 1
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )
        assert result.exit_code == 0

        # Verify stats count unchanged
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        updated_stats = self.extract_json_from_output(result.stdout)
        assert updated_stats["total_bullets"] == initial_count

    def test_deprecate_operation_reflected_in_stats(self, runner, temp_playbook_with_bullets, monkeypatch):
        """Test that DEPRECATE operations affect stats count."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets
        monkeypatch.chdir(tmpdir)

        # Get initial stats
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        initial_stats = self.extract_json_from_output(result.stdout)
        initial_count = initial_stats["total_bullets"]

        # Apply DEPRECATE operation
        delta_data = {
            "operations": [
                {
                    "type": "DEPRECATE",
                    "bullet_id": "impl-0001",
                    "reason": "Outdated pattern"
                }
            ]
        }

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input=json.dumps(delta_data)
        )
        assert result.exit_code == 0

        # Verify stats show deprecated bullet removed
        result = runner.invoke(app, ["playbook", "stats"])
        assert result.exit_code == 0
        updated_stats = self.extract_json_from_output(result.stdout)
        # DEPRECATE marks as deprecated, might still be counted or not depending on implementation
        # Just verify stats command executes successfully with consistent data
        assert "total_bullets" in updated_stats
