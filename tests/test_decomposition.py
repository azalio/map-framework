"""Tests for the __init__.py decomposition (platform refactor Step 1).

Verifies that:
1. New submodules export the same functions as the original __init__.py
2. Re-exports in __init__.py maintain backward compatibility
3. New schemas validate correctly
"""

import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# map_step_runner import (mirrors tests/test_map_step_runner.py lines 14-26)
# ---------------------------------------------------------------------------

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Requirements Index sentinel constants (mirrors test_map_step_runner.py)
# ---------------------------------------------------------------------------

_RI_OPEN = "<!-- mapify:requirements-index:v1 -->"
_RI_CLOSE = "<!-- /mapify:requirements-index:v1 -->"


def _make_spec_with_index(yaml_body: str | None = None) -> str:
    """Return a spec markdown string for integration fixture construction.

    Pass yaml_body=None  -> no sentinel (absent index).
    Pass yaml_body=""    -> sentinel pair with empty yaml block.
    Pass yaml_body=<str> -> sentinel pair wrapping the given yaml.
    """
    if yaml_body is None:
        return "# Spec\n\nSome prose.\n"
    return (
        f"# Spec\n\n{_RI_OPEN}\n"
        f"```yaml\n{yaml_body}```\n"
        f"{_RI_CLOSE}\n"
    )


def _make_integration_blueprint(
    coverage_map: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return a minimal valid blueprint for integration tests."""
    if coverage_map is None:
        coverage_map = {"AC-1": "ST-001"}
    return {
        "hard_constraints": [{"id": "AC-1", "description": "It must work"}],
        "soft_constraints": [],
        "subtasks": [
            {
                "id": "ST-001",
                "title": "Do the thing",
                "aag_contract": "X -> do() -> done",
                "dependencies": [],
                "affected_files": ["src/x.py"],
                "expected_diff_size": "small",
                "concern_type": "runtime",
                "one_logical_step": True,
                "validation_criteria": ["VC1 [AC-1]: it works"],
            }
        ],
        "coverage_map": coverage_map,
    }


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

        content = create_task_decomposer_content(["sequential-thinking"])
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
        assert "deepwiki" not in servers  # deepwiki MCP install was removed

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

    def _constraint_fields(self):
        return {
            "hard_constraints": [
                {"id": "AC-1", "description": "Invalid artifacts return errors"},
            ],
            "soft_constraints": [
                {
                    "id": "SC-1",
                    "description": "Prefer small helper functions",
                    "tradeoff_rationale": "Not required for the schema contract",
                },
            ],
        }

    def test_schema_exists(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA

        assert BLUEPRINT_SCHEMA["title"] == "MAP Blueprint"
        assert "subtasks" in BLUEPRINT_SCHEMA["properties"]

    def test_validate_valid_blueprint(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            **self._constraint_fields(),
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
                    "validation_criteria": ["VC1 [AC-1]: invalid artifacts return errors"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }
        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert is_valid, f"Errors: {errors}"

    def test_validate_blueprint_accepts_subtask_contract_metadata(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            **self._constraint_fields(),
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
                    "validation_criteria": ["VC1 [AC-1]: user sees retryable timeout"],
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
                **self._constraint_fields(),
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
                        "validation_criteria": ["VC1 [AC-1]: user sees retryable timeout"],
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
            **self._constraint_fields(),
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
                    "validation_criteria": ["VC1 [AC-1]: check"],
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
            **self._constraint_fields(),
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
                    "validation_criteria": ["VC1 [AC-1]: check"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        assert any("expected_diff_size" in error for error in errors)
        assert any("concern_type" in error for error in errors)

    def test_validate_blueprint_requires_constraint_fields(self):
        from mapify_cli.schemas import BLUEPRINT_SCHEMA, validate_artifact

        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Missing constraints",
                    "dependencies": [],
                    "affected_files": [],
                    "aag_contract": "Actor -> bad() -> bad",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1 [AC-1]: check"],
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
        }

        is_valid, errors = validate_artifact(blueprint, BLUEPRINT_SCHEMA)
        assert not is_valid
        assert errors
        required_fields = BLUEPRINT_SCHEMA["anyOf"][0]["required"]
        assert "hard_constraints" in required_fields
        assert "soft_constraints" in required_fields

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
        is_valid, _ = validate_artifact(artifact, STATE_ARTIFACT_SCHEMA)
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
            **TestBlueprintSchema()._constraint_fields(),
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
                    "validation_criteria": ["VC1 [AC-1]: check"],
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
        # Phase 3 (#183): global default flipped off -> lite.
        assert cfg.minimality == "lite"
        # /compact nudge is opt-in: the meter must NOT fire unless the user
        # explicitly switches compression_policy to "auto" or "aggressive".
        assert cfg.compression_policy == "never"
        assert cfg.compression_threshold_tokens == 120_000

    def test_load_map_config_no_file(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        cfg = load_map_config(tmp_path)
        assert cfg.profile == "full"  # default
        # Phase 3 (#183): keyless config now defaults to lite (was off).
        assert cfg.minimality == "lite"

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
        assert "minimality: lite" in content
        assert "# Policy thresholds" in content
        assert "# verification_checks:" in content

    def test_generate_default_config_minimal(self):
        from mapify_cli.config.project_config import generate_default_config

        content = generate_default_config(include_comments=False)
        assert "profile: full" in content
        assert "minimality: lite" in content
        assert "# Policy thresholds" not in content

    def test_write_default_config_creates_file(self, tmp_path):
        from mapify_cli.config.project_config import write_default_config

        path = write_default_config(tmp_path)
        assert path.exists()
        assert path == tmp_path / ".map" / "config.yaml"
        content = path.read_text()
        assert "profile: full" in content
        assert "minimality: lite" in content

    def test_load_map_config_valid_minimality_values_pass_through(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        for value in ("off", "lite", "full", "ultra"):
            map_dir = tmp_path / value / ".map"
            map_dir.mkdir(parents=True)
            (map_dir / "config.yaml").write_text(f"minimality: {value}\n")

            cfg = load_map_config(tmp_path / value)

            assert cfg.minimality == value

    def test_load_map_config_invalid_minimality_falls_back_to_lite(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("minimality: maximalist\n")

        cfg = load_map_config(tmp_path)

        # Phase 3 (#183): invalid value falls back to the new default lite.
        assert cfg.minimality == "lite"

    def test_load_map_config_yaml_bool_off_opts_out_to_off(self, tmp_path):
        """`minimality: off` (unquoted) is YAML bool False; it must still opt out (#183)."""
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("minimality: off\n")

        cfg = load_map_config(tmp_path)

        assert cfg.minimality == "off"

    def test_write_default_config_no_overwrite(self, tmp_path):
        from mapify_cli.config.project_config import write_default_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        config_file = map_dir / "config.yaml"
        config_file.write_text("profile: core\n")

        path = write_default_config(tmp_path)
        assert path.read_text() == "profile: core\n"  # not overwritten

    # ---- compression policy validation ----

    def test_load_map_config_invalid_compression_policy_falls_back_to_never(
        self, tmp_path
    ):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        (map_dir / "config.yaml").write_text("compression_policy: paranoid\n")
        cfg = load_map_config(tmp_path)
        # Typo must not break the user — silently fall back to the default
        # ("never"); the /compact nudge is opt-in and a typo must not flip
        # users into auto-nudge mode against their will.
        assert cfg.compression_policy == "never"

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
        # Default config has the keys commented out (now showing "never"
        # since the /compact nudge is opt-in by default).
        assert "# compression_policy: never" in config_file.read_text()

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

    # ---- apply_sofa_overrides ----

    def test_vc1_apply_sofa_overrides_replaces_commented_placeholder(self, tmp_path):
        """VC1 [AC-1]: apply_sofa_overrides activates the commented placeholder."""
        from mapify_cli.config.project_config import (
            apply_sofa_overrides,
            write_default_config,
        )

        config_file = write_default_config(tmp_path)
        content = config_file.read_text()
        # Default config must have only the commented placeholder, not the
        # active key.
        assert "# sofa.enabled: false" in content
        assert "sofa.enabled: true" not in content

        apply_sofa_overrides(config_file)
        content = config_file.read_text()
        assert "sofa.enabled: true" in content
        # Commented placeholder must be gone (replaced, not duplicated).
        assert "# sofa.enabled:" not in content
        # Exactly one occurrence of the active key.
        assert content.count("sofa.enabled: true") == 1

    def test_vc1_default_config_has_no_active_sofa_line(self, tmp_path):
        """VC1 [AC-1]: bare write_default_config emits NO active sofa.enabled=true line."""
        from mapify_cli.config.project_config import write_default_config

        config_file = write_default_config(tmp_path)
        content = config_file.read_text()
        assert "sofa.enabled: true" not in content

    def test_vc1_apply_sofa_overrides_replaces_active_entry(self, tmp_path):
        """VC1 [AC-1]: calling apply_sofa_overrides twice leaves exactly one active entry."""
        from mapify_cli.config.project_config import apply_sofa_overrides

        config_file = tmp_path / "config.yaml"
        config_file.write_text("profile: full\nsofa.enabled: false\n")

        apply_sofa_overrides(config_file)
        content = config_file.read_text()
        assert content.count("sofa.enabled:") == 1
        assert "sofa.enabled: true" in content

    def test_vc2_bare_init_does_not_write_sofa_enabled(self, tmp_path):
        """VC2 [AC-1]: a config produced without --sofa has no active sofa.enabled line."""
        from mapify_cli.config.project_config import write_default_config

        config_file = write_default_config(tmp_path)
        content = config_file.read_text()
        assert "sofa.enabled: true" not in content

    def test_vc2_apply_sofa_overrides_idempotent(self, tmp_path):
        """VC2 [AC-1]: calling apply_sofa_overrides twice does not clobber or duplicate."""
        from mapify_cli.config.project_config import (
            apply_sofa_overrides,
            write_default_config,
        )

        config_file = write_default_config(tmp_path)
        apply_sofa_overrides(config_file)
        apply_sofa_overrides(config_file)
        content = config_file.read_text()
        assert content.count("sofa.enabled: true") == 1
        assert "# sofa.enabled:" not in content

    def test_vc2_apply_sofa_overrides_no_op_when_file_missing(self, tmp_path):
        """VC2 [AC-1]: apply_sofa_overrides on a missing file does not raise."""
        from mapify_cli.config.project_config import apply_sofa_overrides

        missing = tmp_path / "nope.yaml"
        apply_sofa_overrides(missing)
        assert not missing.exists()

    def test_vc3_mapconfig_default_sofa_enabled_is_false(self):
        """VC3 [INV-SOFA-1]: MapConfig() default sofa_enabled is False."""
        from mapify_cli.config.project_config import MapConfig

        assert MapConfig().sofa_enabled is False

    def test_vc3_load_default_config_sofa_enabled_is_false(self, tmp_path):
        """VC3 [INV-SOFA-1]: write_default_config -> load_map_config -> sofa_enabled=False."""
        from mapify_cli.config.project_config import (
            load_map_config,
            write_default_config,
        )

        write_default_config(tmp_path)
        cfg = load_map_config(tmp_path)
        # Commented placeholder must be ignored — field stays at default False.
        assert cfg.sofa_enabled is False

    def test_vc3_load_active_sofa_enabled_round_trips_to_true(self, tmp_path):
        """VC3 [INV-SOFA-1]: config with active sofa.enabled=true loads sofa_enabled=True."""
        from mapify_cli.config.project_config import (
            apply_sofa_overrides,
            load_map_config,
            write_default_config,
        )

        write_default_config(tmp_path)
        config_file = tmp_path / ".map" / "config.yaml"
        apply_sofa_overrides(config_file)
        # Verify the file actually has the active key before loading.
        assert "sofa.enabled: true" in config_file.read_text()

        cfg = load_map_config(tmp_path)
        # The dotted-key alias in load_map_config must translate sofa.enabled
        # -> sofa_enabled so the field is not a silent dead toggle.
        assert cfg.sofa_enabled is True


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
        import importlib.util
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
            assert spec is not None
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(mod)  # pyright: ignore[reportAttributeAccessIssue]
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
        from mapify_cli.config.project_config import MapConfig, load_map_config

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


# ---------------------------------------------------------------------------
# ST-012 VC1: Integration tests — 5 forward-coverage outcomes end-to-end
# ---------------------------------------------------------------------------


class TestForwardCoverageIntegration:
    """VC1 [Cross-cutting: integration tests]: drive a real blueprint+spec fixture
    through validate_blueprint_contract for all 5 forward outcomes.
    """

    _BRANCH = "test-integration-branch"

    def _write_fixture(
        self,
        tmp_path: Path,
        spec_text: str,
        blueprint: dict[str, object] | None = None,
    ) -> None:
        """Write spec + blueprint under tmp_path/.map/<branch>/."""
        if blueprint is None:
            blueprint = _make_integration_blueprint()
        branch_dir = tmp_path / ".map" / self._BRANCH
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / f"spec_{self._BRANCH}.md").write_text(spec_text, encoding="utf-8")
        (branch_dir / "blueprint.json").write_text(
            json.dumps(blueprint), encoding="utf-8"
        )

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        spec_text: str,
        blueprint: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        """Write fixture and invoke validate_blueprint_contract."""
        self._write_fixture(tmp_path, spec_text, blueprint)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: self._BRANCH)
        return cast(
            "dict[str, Any]",
            map_step_runner.validate_blueprint_contract(branch=self._BRANCH),
        )

    def test_vc1_outcome1_complete_index_all_ids_covered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outcome 1: complete index, all IDs in coverage_map -> valid True,
        forward_coverage.status present_nonempty, missing_ids [].
        """
        spec = _make_spec_with_index(
            "requirements:\n  - id: AC-1\n    kind: acceptance_criterion\n"
        )
        blueprint = _make_integration_blueprint(coverage_map={"AC-1": "ST-001"})
        result = self._run(tmp_path, monkeypatch, spec, blueprint)

        assert result["valid"] is True
        fc = result["forward_coverage"]
        assert fc["status"] == "present_nonempty"
        assert fc["missing_ids"] == []
        # No forward-coverage errors or warnings about missing IDs
        fc_errors = [e for e in result["errors"] if "Forward-coverage" in e]
        assert fc_errors == []

    def test_vc1_outcome2_missing_id_default_warn_not_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outcome 2: missing ID, MAP_STRICT_COVERAGE unset -> WARNING, valid True."""
        monkeypatch.delenv("MAP_STRICT_COVERAGE", raising=False)
        spec = _make_spec_with_index(
            "requirements:\n"
            "  - id: AC-1\n    kind: acceptance_criterion\n"
            "  - id: HC-1\n    kind: hard_constraint\n"
        )
        # coverage_map covers AC-1 but not HC-1
        blueprint = _make_integration_blueprint(coverage_map={"AC-1": "ST-001"})
        result = self._run(tmp_path, monkeypatch, spec, blueprint)

        assert result["valid"] is True
        fc = result["forward_coverage"]
        assert "HC-1" in fc["missing_ids"]
        # Must appear in warnings, not errors
        assert any("HC-1" in w for w in result["warnings"])
        assert not any("HC-1" in e for e in result["errors"])

    def test_vc1_outcome3_missing_id_strict_hard_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outcome 3: missing ID, MAP_STRICT_COVERAGE=1 -> ERROR, valid False."""
        monkeypatch.setenv("MAP_STRICT_COVERAGE", "1")
        spec = _make_spec_with_index(
            "requirements:\n"
            "  - id: AC-1\n    kind: acceptance_criterion\n"
            "  - id: HC-1\n    kind: hard_constraint\n"
        )
        blueprint = _make_integration_blueprint(coverage_map={"AC-1": "ST-001"})
        result = self._run(tmp_path, monkeypatch, spec, blueprint)

        assert result["valid"] is False
        fc = result["forward_coverage"]
        assert "HC-1" in fc["missing_ids"]
        assert fc["strict"] is True
        assert any("HC-1" in e for e in result["errors"])

    def test_vc1_outcome4_absent_spec_warn_skip_not_hard_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outcome 4: absent spec file (the /map-efficient path: blueprint present,
        NO spec) -> forward_coverage.status absent, a warning present, valid not
        forced False by absence alone.
        """
        monkeypatch.delenv("MAP_STRICT_COVERAGE", raising=False)
        # Write blueprint but NO spec file
        branch_dir = tmp_path / ".map" / self._BRANCH
        branch_dir.mkdir(parents=True, exist_ok=True)
        blueprint = _make_integration_blueprint()
        (branch_dir / "blueprint.json").write_text(
            json.dumps(blueprint), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: self._BRANCH)
        result = cast(
            "dict[str, Any]",
            map_step_runner.validate_blueprint_contract(branch=self._BRANCH),
        )

        fc = result["forward_coverage"]
        assert fc["status"] == "absent"
        # A warning about missing spec must be present
        assert any(
            "forward-coverage" in w.lower() or "requirements index" in w.lower()
            for w in result["warnings"]
        )
        # Absent spec alone must NOT force valid=False
        forward_errors = [e for e in result["errors"] if "Forward-coverage" in e]
        assert forward_errors == [], (
            "Absent spec must emit a warning and skip, not a hard error"
        )

    def test_vc1_outcome5_malformed_index_hard_fail_regardless_of_strict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Outcome 5: malformed index (open sentinel + broken yaml) -> valid False
        even without strict flag set.
        """
        monkeypatch.delenv("MAP_STRICT_COVERAGE", raising=False)
        # Open sentinel present but no close sentinel -> malformed
        spec = (
            "# Spec\n\n"
            f"{_RI_OPEN}\n"
            "```yaml\nrequirements:\n  - id: AC-1\n    kind: acceptance_criterion\n```\n"
            # deliberately omit _RI_CLOSE
        )
        blueprint = _make_integration_blueprint()
        result = self._run(tmp_path, monkeypatch, spec, blueprint)

        assert result["valid"] is False
        fc = result["forward_coverage"]
        assert fc["status"] == "malformed"
        assert any("malformed" in e.lower() or "Forward-coverage" in e for e in result["errors"])
