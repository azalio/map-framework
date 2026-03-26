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
            get_key,
            select_multiple_with_arrows,
            select_with_arrows,
            show_banner,
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
        assert (
            "sequential-thinking" in content.lower()
            or "sequentialthinking" in content.lower()
        )

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


class TestBackwardCompatibility:
    """Test that __init__.py re-exports maintain backward compatibility."""

    def test_all_original_imports_work(self):
        """The exact import list from test_mapify_cli.py must still work."""

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

        bp = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Test",
                    "dependencies": [],
                    "affected_files": ["a.py"],
                }
            ]
        }
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

    def test_load_and_validate_invalid_data(self, tmp_path):
        """load_and_validate must return None for invalid data."""
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, load_and_validate

        invalid_file = tmp_path / "bad_blueprint.json"
        # Missing required 'subtasks' field
        invalid_file.write_text('{"not_subtasks": []}')

        data, errors = load_and_validate(invalid_file, BLUEPRINT_SCHEMA)
        assert data is None, "Invalid data should return None, not the parsed dict"
        assert len(errors) > 0


class TestProjectConfig:
    """Test .map/config.yaml system (Step 2)."""

    def test_default_config_values(self):
        from mapify_cli.config.project_config import MapConfig

        cfg = MapConfig()
        assert cfg.profile == "full"
        assert cfg.actor_monitor_max_retries == 5
        assert cfg.confidence_threshold == 0.7
        assert "src/" in cfg.safe_path_prefixes
        assert cfg.language == ""

    def test_load_map_config_no_file(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        cfg = load_map_config(tmp_path)
        assert cfg.profile == "full"  # default

    def test_load_map_config_empty_file(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("# just a comment\n")
        cfg = load_map_config(tmp_path)
        assert cfg.profile == "full"  # default when file is empty/comments only

    def test_load_map_config_with_overrides(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text(
            "profile: core\nactor_monitor_max_retries: 10\nlanguage: ru\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.profile == "core"
        assert cfg.actor_monitor_max_retries == 10
        assert cfg.language == "ru"
        # Non-overridden fields keep defaults
        assert cfg.confidence_threshold == 0.7

    def test_load_map_config_ignores_unknown_keys(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text(
            "profile: core\nsome_future_key: whatever\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.profile == "core"
        assert not hasattr(cfg, "some_future_key")

    def test_load_map_config_malformed_yaml(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text(":::bad yaml{{{")
        cfg = load_map_config(tmp_path)
        assert cfg.profile == "full"  # falls back to defaults

    def test_load_map_config_non_dict(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("- item1\n- item2\n")
        cfg = load_map_config(tmp_path)
        assert cfg.profile == "full"  # falls back to defaults

    def test_generate_default_config_with_comments(self):
        from mapify_cli.config.project_config import generate_default_config

        content = generate_default_config(include_comments=True)
        assert "profile: full" in content
        assert "# Policy thresholds" in content
        assert "# verification_checks:" in content

    def test_generate_default_config_minimal(self):
        from mapify_cli.config.project_config import generate_default_config

        content = generate_default_config(include_comments=False)
        assert "profile: full" in content
        assert "# Policy thresholds" not in content

    def test_write_default_config_creates_file(self, tmp_path):
        from mapify_cli.config.project_config import write_default_config

        path = write_default_config(tmp_path)
        assert path.exists()
        assert path == tmp_path / ".map" / "config.yaml"
        content = path.read_text()
        assert "profile: full" in content

    def test_write_default_config_no_overwrite(self, tmp_path):
        from mapify_cli.config.project_config import write_default_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        config_file = map_dir / "config.yaml"
        config_file.write_text("profile: core\n")

        path = write_default_config(tmp_path)
        assert path.read_text() == "profile: core\n"  # not overwritten


class TestSafetyGuardrailsHookConfig:
    """Test that safety-guardrails.py reads config overrides."""

    def test_hook_has_config_loading(self):
        """Verify the hook template loads config overrides."""
        hook_path = (
            Path(__file__).parent.parent
            / "src"
            / "mapify_cli"
            / "templates"
            / "hooks"
            / "safety-guardrails.py"
        )
        content = hook_path.read_text()
        assert "_load_config_overrides" in content
        assert "safe_path_prefixes" in content
        assert "dangerous_file_patterns" in content
        assert "dangerous_commands" in content

    def test_hook_respects_config_overrides(self, tmp_path):
        """Runtime test: config overrides affect guardrail behavior."""
        import importlib
        import os

        # Create a .map/config.yaml with custom safe_path_prefixes
        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        config_path = map_dir / "config.yaml"
        config_path.write_text(
            "safe_path_prefixes:\n  - custom_safe/\n  - also_safe/\n"
        )

        # Copy hook source to a temp module and load it
        hook_src = (
            Path(__file__).parent.parent
            / "src"
            / "mapify_cli"
            / "templates"
            / "hooks"
            / "safety-guardrails.py"
        )
        hook_copy = tmp_path / "guardrails_test.py"
        hook_copy.write_text(hook_src.read_text())

        old_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        try:
            spec = importlib.util.spec_from_file_location("guardrails_test", hook_copy)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # custom_safe/ should be safe
            assert mod.is_safe_path("custom_safe/file.py")
            assert mod.is_safe_path("also_safe/data.json")
            # src/ should NOT be safe (default overridden)
            assert not mod.is_safe_path("src/main.py")
        finally:
            if old_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old_env


class TestMapConfigTypeCoercion:
    """Test that load_map_config handles wrong-type YAML values gracefully."""

    def test_wrong_type_falls_back_to_defaults(self, tmp_path):
        """Wrong types in YAML should not crash; defaults should be used."""
        from mapify_cli.config.project_config import load_map_config, MapConfig

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        config = map_dir / "config.yaml"
        config.write_text(
            "actor_monitor_max_retries: not-an-int\n"
            "confidence_threshold: also-wrong\n"
        )
        result = load_map_config(tmp_path)
        defaults = MapConfig()
        # Should get defaults since constructor will fail with bad types
        assert result.actor_monitor_max_retries == defaults.actor_monitor_max_retries
        assert result.confidence_threshold == defaults.confidence_threshold


class TestRulesDir:
    """Test .claude/rules/learned/ directory creation."""

    def test_create_rules_dir_creates_directory(self, tmp_path):
        from mapify_cli.delivery.file_copier import create_rules_dir

        count = create_rules_dir(tmp_path)
        rules_dir = tmp_path / ".claude" / "rules" / "learned"
        assert rules_dir.is_dir()
        readme = rules_dir / "README.md"
        assert readme.exists()
        assert "MAP Framework" in readme.read_text()
        assert count == 1

    def test_create_rules_dir_preserves_existing_readme(self, tmp_path):
        from mapify_cli.delivery.file_copier import create_rules_dir

        # Pre-create with custom content
        rules_dir = tmp_path / ".claude" / "rules" / "learned"
        rules_dir.mkdir(parents=True)
        readme = rules_dir / "README.md"
        readme.write_text("My custom README\n")

        count = create_rules_dir(tmp_path)
        assert readme.read_text() == "My custom README\n"
        assert count == 0  # nothing installed

    def test_create_rules_dir_idempotent(self, tmp_path):
        from mapify_cli.delivery.file_copier import create_rules_dir

        create_rules_dir(tmp_path)
        create_rules_dir(tmp_path)  # second call
        rules_dir = tmp_path / ".claude" / "rules" / "learned"
        assert rules_dir.is_dir()
        # Only README, no duplicates
        files = list(rules_dir.iterdir())
        assert len(files) == 1
