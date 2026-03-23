"""Tests for the __init__.py decomposition (platform refactor Step 1).

Verifies that:
1. New submodules export the same functions as the original __init__.py
2. Re-exports in __init__.py maintain backward compatibility
3. New schemas validate correctly
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestCliUiModule:
    """Test that cli_ui module exports all expected symbols."""

    def test_imports(self):
        from mapify_cli.cli_ui import (
            BANNER,
            TAGLINE,
            BannerGroup,
            StepTracker,
            get_key,
            select_multiple_with_arrows,
            select_with_arrows,
            show_banner,
            console,
        )
        assert BANNER is not None
        assert TAGLINE is not None
        assert callable(show_banner)
        assert callable(get_key)
        assert callable(select_with_arrows)
        assert callable(select_multiple_with_arrows)

    def test_step_tracker_basic(self):
        from mapify_cli.cli_ui import StepTracker

        tracker = StepTracker("Test")
        tracker.add("step1", "Step 1")
        tracker.start("step1", "working")
        tracker.complete("step1", "done")

        rendered = tracker.render()
        assert rendered is not None


class TestDeliveryModule:
    """Test that delivery module exports all expected symbols."""

    def test_agent_generator_imports(self):
        from mapify_cli.delivery.agent_generator import (
            create_actor_content,
            create_documentation_reviewer_content,
            create_evaluator_content,
            create_monitor_content,
            create_predictor_content,
            create_reflector_content,
            create_task_decomposer_content,
        )
        # All should be callable
        for fn in [
            create_task_decomposer_content,
            create_actor_content,
            create_monitor_content,
            create_predictor_content,
            create_evaluator_content,
            create_reflector_content,
            create_documentation_reviewer_content,
        ]:
            assert callable(fn)

    def test_agent_generator_produces_content(self):
        from mapify_cli.delivery.agent_generator import create_actor_content

        content = create_actor_content([])
        assert "---" in content
        assert "name: actor" in content

    def test_agent_generator_with_mcp(self):
        from mapify_cli.delivery.agent_generator import create_task_decomposer_content

        content = create_task_decomposer_content(["sequential-thinking", "deepwiki"])
        assert "sequential-thinking" in content.lower() or "sequentialthinking" in content.lower()

    def test_file_copier_imports(self):
        from mapify_cli.delivery.file_copier import (
            create_agent_files,
            create_command_files,
            create_commands_dir,
            create_config_files,
            create_hook_files,
            create_map_tools,
            create_reference_files,
            create_skill_files,
        )
        for fn in [
            create_agent_files,
            create_reference_files,
            create_command_files,
            create_skill_files,
            create_hook_files,
            create_config_files,
            create_commands_dir,
            create_map_tools,
        ]:
            assert callable(fn)

    def test_delivery_package_reexports(self):
        """Verify delivery __init__ re-exports everything."""
        from mapify_cli.delivery import (
            create_actor_content,
            create_agent_files,
            create_command_files,
            create_commands_dir,
            create_config_files,
            create_documentation_reviewer_content,
            create_evaluator_content,
            create_hook_files,
            create_map_tools,
            create_monitor_content,
            create_predictor_content,
            create_reference_files,
            create_reflector_content,
            create_skill_files,
            create_task_decomposer_content,
        )


class TestConfigModule:
    """Test that config module exports all expected symbols."""

    def test_settings_imports(self):
        from mapify_cli.config.settings import (
            configure_global_permissions,
            create_or_merge_project_settings_local,
        )
        assert callable(configure_global_permissions)
        assert callable(create_or_merge_project_settings_local)

    def test_mcp_imports(self):
        from mapify_cli.config.mcp import (
            build_standard_mcp_servers,
            create_mcp_config,
            create_or_merge_project_mcp_json,
            merge_mcp_json,
            read_project_mcp_json,
            write_project_mcp_json,
        )
        for fn in [
            create_mcp_config,
            build_standard_mcp_servers,
            read_project_mcp_json,
            write_project_mcp_json,
            merge_mcp_json,
            create_or_merge_project_mcp_json,
        ]:
            assert callable(fn)

    def test_build_standard_mcp_servers(self):
        from mapify_cli.config.mcp import build_standard_mcp_servers

        servers = build_standard_mcp_servers()
        assert "sequential-thinking" in servers
        assert "deepwiki" in servers

    def test_merge_mcp_json(self):
        from mapify_cli.config.mcp import merge_mcp_json

        existing = {"mcpServers": {"existing-server": {"url": "http://example.com"}}}
        new_servers = {"new-server": {"url": "http://new.com"}}
        result = merge_mcp_json(existing, new_servers)
        assert "existing-server" in result["mcpServers"]
        assert "new-server" in result["mcpServers"]

    def test_config_package_reexports(self):
        """Verify config __init__ re-exports everything."""
        from mapify_cli.config import (
            build_standard_mcp_servers,
            configure_global_permissions,
            create_mcp_config,
            create_or_merge_project_mcp_json,
            create_or_merge_project_settings_local,
            merge_mcp_json,
            read_project_mcp_json,
            write_project_mcp_json,
        )


class TestBackwardCompatibility:
    """Test that __init__.py re-exports maintain backward compatibility."""

    def test_all_original_imports_work(self):
        """The exact import list from test_mapify_cli.py must still work."""
        from mapify_cli import (
            app,
            build_standard_mcp_servers,
            count_agent_templates,
            count_command_templates,
            create_agent_files,
            create_command_files,
            create_commands_dir,
            create_map_tools,
            create_or_merge_project_mcp_json,
            create_ssl_context,
            get_branch_artifact_templates,
            get_latest_release,
            get_templates_dir,
            init_git_repo,
            is_command,
            is_git_repo,
            merge_mcp_json,
            read_project_mcp_json,
            write_project_mcp_json,
        )

    def test_step_tracker_from_init(self):
        """StepTracker must be importable from mapify_cli (backward compat)."""
        from mapify_cli import StepTracker

        tracker = StepTracker("Test")
        assert tracker is not None

    def test_show_banner_from_init(self):
        from mapify_cli import show_banner
        assert callable(show_banner)

    def test_configure_global_permissions_from_init(self):
        from mapify_cli import configure_global_permissions
        assert callable(configure_global_permissions)


class TestBlueprintSchema:
    """Test the new BLUEPRINT_SCHEMA."""

    def test_schema_exists(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA
        assert BLUEPRINT_SCHEMA["title"] == "MAP Blueprint"
        assert "subtasks" in BLUEPRINT_SCHEMA["properties"]

    def test_validate_valid_blueprint(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Add schema validation",
                    "dependencies": [],
                    "affected_files": ["src/schemas.py"],
                }
            ]
        }
        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_invalid_blueprint(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {"metadata": {"goal": "test"}}  # missing required 'subtasks'
        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        assert any("subtasks" in e for e in errors)


class TestValidateArtifact:
    """Test the validate_artifact utility."""

    def test_validate_state_artifact(self):
        from mapify_cli.schemas import STATE_ARTIFACT_SCHEMA, validate_artifact

        artifact = {"workflow": "map-efficient", "terminal_status": "pending"}
        is_valid, errors = validate_artifact(artifact, STATE_ARTIFACT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_missing_required(self):
        from mapify_cli.schemas import STATE_ARTIFACT_SCHEMA, validate_artifact

        artifact = {"workflow": "map-efficient"}  # missing terminal_status
        is_valid, errors = validate_artifact(artifact, STATE_ARTIFACT_SCHEMA)
        assert not is_valid

    def test_validate_raise_on_error(self):
        from mapify_cli.schemas import STATE_ARTIFACT_SCHEMA, validate_artifact

        artifact = {}
        with pytest.raises(ValueError, match="Schema validation failed"):
            validate_artifact(artifact, STATE_ARTIFACT_SCHEMA, raise_on_error=True)

    def test_load_and_validate(self, tmp_path):
        import json
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, load_and_validate

        bp = {"subtasks": [{"id": "ST-001", "title": "Test", "dependencies": [], "affected_files": ["a.py"]}]}
        path = tmp_path / "blueprint.json"
        path.write_text(json.dumps(bp))

        data, errors = load_and_validate(path, BLUEPRINT_SCHEMA)
        assert data is not None
        assert errors == []

    def test_load_and_validate_missing_file(self, tmp_path):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, load_and_validate

        data, errors = load_and_validate(tmp_path / "nope.json", BLUEPRINT_SCHEMA)
        assert data is None
        assert len(errors) == 1
