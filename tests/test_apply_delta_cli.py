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

    def test_cli_apply_delta_from_file(self, runner, temp_playbook_with_bullets):
        """Test apply-delta command with file input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            ["playbook", "apply-delta", str(delta_file)],
            cwd=tmpdir
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"
        assert output["summary"]["updated"] == 1

    def test_cli_apply_delta_stdin(self, runner, temp_playbook_with_bullets):
        """Test apply-delta command with stdin input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "success"

    def test_cli_apply_delta_dry_run(self, runner, temp_playbook_with_bullets):
        """Test --dry-run flag previews without applying."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["status"] == "dry_run"
        assert output["message"] == "DRY RUN - No changes applied"
        assert output["would_apply"]["total_operations"] == 2
        assert output["would_apply"]["add"] == 1
        assert output["would_apply"]["update"] == 1

    def test_cli_missing_playbook(self, runner, tmp_path):
        """Test error when playbook.json doesn't exist."""
        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input='{"operations": []}',
            cwd=str(tmp_path)
        )

        assert result.exit_code == 1
        assert "Playbook not found" in result.stdout

    def test_cli_invalid_json(self, runner, temp_playbook_with_bullets):
        """Test error with invalid JSON input."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input="{invalid json}",
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert output["status"] == "error"
        assert output["error_type"] == "validation_error"

    def test_cli_missing_operations_field(self, runner, temp_playbook_with_bullets):
        """Test error when 'operations' field is missing."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

        result = runner.invoke(
            app,
            ["playbook", "apply-delta"],
            input='{"data": []}',
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert "Missing required field: 'operations'" in output["message"]

    def test_cli_invalid_operation_type(self, runner, temp_playbook_with_bullets):
        """Test error with invalid operation type."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert "invalid type: INVALID" in output["message"]

    def test_cli_add_missing_required_fields(self, runner, temp_playbook_with_bullets):
        """Test error when ADD operation missing required fields."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert "missing required fields: content" in output["message"]

    def test_cli_update_missing_bullet_id(self, runner, temp_playbook_with_bullets):
        """Test error when UPDATE operation missing bullet_id."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
        assert "missing required field: 'bullet_id'" in output["message"]

    def test_cli_update_no_delta_fields(self, runner, temp_playbook_with_bullets):
        """Test error when UPDATE has no increment fields."""
        tmpdir, playbook_path, manager = temp_playbook_with_bullets

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
            input=json.dumps(delta_data),
            cwd=tmpdir
        )

        assert result.exit_code == 1
        output = json.loads(result.stdout)
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
