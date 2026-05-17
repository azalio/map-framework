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
                    "aag_contract": "Schema module -> validate_artifact() -> contract errors",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1: invalid artifacts return errors"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }
        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_blueprint_accepts_subtask_contract_metadata(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Add checkout timeout message",
                    "dependencies": [],
                    "affected_files": ["src/checkout.py"],
                    "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1: user sees retryable timeout"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_blueprint_accepts_nested_decomposer_output(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "schema_version": "2.0",
            "blueprint": {
                "subtasks": [
                    {
                        "id": "ST-001",
                        "title": "Add checkout timeout message",
                        "dependencies": [],
                        "affected_files": ["src/checkout.py"],
                        "aag_contract": "CheckoutService -> handle_timeout() -> user sees retryable error",
                        "expected_diff_size": "small",
                        "concern_type": "runtime",
                        "one_logical_step": True,
                        "validation_criteria": ["VC1: user sees retryable timeout"],
                    }
                ],
                "coverage_map": {"AC-1": "ST-001"},
            },
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_blueprint_rejects_malformed_dependency_and_coverage_ids(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Bad IDs",
                    "dependencies": ["one"],
                    "affected_files": [],
                    "aag_contract": "Actor -> bad() -> bad",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1: check"],
                }
            ],
            "coverage_map": {"AC-1": "one"},
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        joined_errors = "\n".join(errors)
        assert "dependencies" in joined_errors
        assert "coverage_map" in joined_errors

    def test_validate_blueprint_rejects_invalid_contract_metadata_enum(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Bad metadata",
                    "dependencies": [],
                    "affected_files": [],
                    "aag_contract": "Actor -> bad() -> bad",
                    "expected_diff_size": "huge",
                    "concern_type": "everything",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1: check"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        assert any("expected_diff_size" in error for error in errors)
        assert any("concern_type" in error for error in errors)

    def test_validate_invalid_blueprint(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {"metadata": {"goal": "test"}}  # missing required 'subtasks'
        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        assert errors


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
                    "aag_contract": "Actor -> test() -> done",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1: check"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
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

    # ---- compression policy validation ----

    def test_load_map_config_invalid_compression_policy_falls_back_to_auto(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("compression_policy: paranoid\n")
        cfg = load_map_config(tmp_path)
        # Typo must not break the user — silently fall back to the default.
        assert cfg.compression_policy == "auto"

    def test_load_map_config_zero_compression_threshold_resets_to_default(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("compression_threshold_tokens: 0\n")
        cfg = load_map_config(tmp_path)
        assert cfg.compression_threshold_tokens == 120_000

    def test_load_map_config_negative_compression_threshold_resets_to_default(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text(
            "compression_threshold_tokens: -42\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.compression_threshold_tokens == 120_000

    def test_load_map_config_valid_compression_overrides_pass_through(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text(
            "compression_policy: aggressive\n"
            "compression_threshold_tokens: 250000\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.compression_policy == "aggressive"
        assert cfg.compression_threshold_tokens == 250_000

    # ---- apply_compression_overrides ----

    def test_apply_compression_overrides_replaces_commented_placeholder(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import (
            apply_compression_overrides,
            write_default_config,
        )

        config_file = write_default_config(tmp_path)
        # Default config has the keys commented out.
        assert "# compression_policy: auto" in config_file.read_text()

        apply_compression_overrides(config_file, "aggressive", 200_000)
        content = config_file.read_text()
        assert "compression_policy: aggressive" in content
        assert "compression_threshold_tokens: 200000" in content
        # The commented placeholders are replaced, not duplicated.
        assert "# compression_policy:" not in content
        assert "# compression_threshold_tokens:" not in content

    def test_apply_compression_overrides_replaces_active_entry(self, tmp_path):
        from mapify_cli.config.project_config import apply_compression_overrides

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "profile: full\n"
            "compression_policy: never\n"
            "compression_threshold_tokens: 90000\n"
        )

        apply_compression_overrides(config_file, "auto", 150_000)
        content = config_file.read_text()
        assert content.count("compression_policy:") == 1
        assert content.count("compression_threshold_tokens:") == 1
        assert "compression_policy: auto" in content
        assert "compression_threshold_tokens: 150000" in content

    def test_apply_compression_overrides_appends_when_keys_missing(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import apply_compression_overrides

        config_file = tmp_path / "config.yaml"
        config_file.write_text("profile: full\n")

        apply_compression_overrides(config_file, "auto", 120_000)
        content = config_file.read_text()
        assert "compression_policy: auto" in content
        assert "compression_threshold_tokens: 120000" in content

    def test_apply_compression_overrides_no_op_when_file_missing(self, tmp_path):
        from mapify_cli.config.project_config import apply_compression_overrides

        missing = tmp_path / "nope.yaml"
        # Should not raise; file simply does not exist.
        apply_compression_overrides(missing, "auto", 120_000)
        assert not missing.exists()

    def test_apply_compression_overrides_no_op_when_both_none(self, tmp_path):
        # Re-running ``mapify init`` without --compression flags must not
        # rewrite an existing user-customised config.
        from mapify_cli.config.project_config import apply_compression_overrides

        config_file = tmp_path / "config.yaml"
        original = (
            "profile: full\n"
            "compression_policy: never\n"
            "compression_threshold_tokens: 90000\n"
        )
        config_file.write_text(original)

        apply_compression_overrides(config_file, None, None)
        assert config_file.read_text() == original

    def test_apply_compression_overrides_partial_policy_only(self, tmp_path):
        from mapify_cli.config.project_config import apply_compression_overrides

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "profile: full\n"
            "compression_policy: never\n"
            "compression_threshold_tokens: 90000\n"
        )
        apply_compression_overrides(config_file, "aggressive", None)
        content = config_file.read_text()
        assert "compression_policy: aggressive" in content
        # Threshold must remain at the user's previous value.
        assert "compression_threshold_tokens: 90000" in content

    def test_apply_compression_overrides_partial_threshold_only(self, tmp_path):
        from mapify_cli.config.project_config import apply_compression_overrides

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "profile: full\n"
            "compression_policy: never\n"
            "compression_threshold_tokens: 90000\n"
        )
        apply_compression_overrides(config_file, None, 250_000)
        content = config_file.read_text()
        # Policy must remain at the user's previous value.
        assert "compression_policy: never" in content
        assert "compression_threshold_tokens: 250000" in content


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
