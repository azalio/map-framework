"""
Tests for role-local persistent memory for learning agents (#379).

Covers:
  AC1 - VALID_AGENT_MEMORY_LEVELS frozenset contains exactly {"off","local","project"}
  AC2 - MapConfig.claude_agents_persistent_memory defaults to "off"
  AC3 - load_map_config honours dotted key claude_agents.persistent_memory
  AC4 - load_map_config rejects invalid values and falls back to "off"
  AC5 - apply_agent_memory_overrides writes the key into config.yaml
  AC6 - apply_reflector_memory_field injects memory: into reflector.md frontmatter
  AC7 - merge_agent_memory_gitignore idempotently adds agent-memory-local to .gitignore
  AC8 - workflow-gate is_exempt_path allows *.md writes in agent-memory dirs
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


def _write_config(tmp_path: Path, body: str) -> Path:
    """Write a minimal .map/config.yaml and return its path."""
    map_dir = tmp_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    cfg = map_dir / "config.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _minimal_reflector(tmp_path: Path, extra_frontmatter: str = "") -> Path:
    """Write a minimal reflector.md in the installed location and return its path."""
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / "reflector.md"
    fm = f"name: reflector\ndescription: Test reflector\n{extra_frontmatter}".strip()
    path.write_text(f"---\n{fm}\n---\n\n# Body\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# AC1: frozenset definition
# ---------------------------------------------------------------------------

class TestValidAgentMemoryLevels:
    def test_frozenset_exact_members(self):
        from mapify_cli.config.project_config import VALID_AGENT_MEMORY_LEVELS

        assert VALID_AGENT_MEMORY_LEVELS == frozenset({"off", "local", "project"})

    def test_frozenset_is_frozenset(self):
        from mapify_cli.config.project_config import VALID_AGENT_MEMORY_LEVELS

        assert isinstance(VALID_AGENT_MEMORY_LEVELS, frozenset)


# ---------------------------------------------------------------------------
# AC2: MapConfig default
# ---------------------------------------------------------------------------

class TestMapConfigDefault:
    def test_default_is_off(self):
        from mapify_cli.config.project_config import MapConfig

        cfg = MapConfig()
        assert cfg.claude_agents_persistent_memory == "off"

    def test_load_no_file_returns_default(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "off"


# ---------------------------------------------------------------------------
# AC3: load_map_config dotted alias
# ---------------------------------------------------------------------------

class TestLoadMapConfigAlias:
    def test_dotted_key_local(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents.persistent_memory: local\n")
        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "local"

    def test_dotted_key_project(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents.persistent_memory: project\n")
        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "project"

    def test_dotted_key_off(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents.persistent_memory: 'off'\n")
        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "off"

    def test_flat_key_also_works(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents_persistent_memory: local\n")
        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "local"


# ---------------------------------------------------------------------------
# AC4: invalid value falls back to "off"
# ---------------------------------------------------------------------------

class TestLoadMapConfigValidation:
    def test_invalid_value_falls_back_to_off(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents.persistent_memory: global\n")
        cfg = load_map_config(tmp_path)
        assert cfg.claude_agents_persistent_memory == "off"

    def test_empty_string_invalid_falls_back(self, tmp_path: Path):
        from mapify_cli.config.project_config import load_map_config

        _write_config(tmp_path, "claude_agents.persistent_memory: ''\n")
        cfg = load_map_config(tmp_path)
        # Empty string is not in VALID_AGENT_MEMORY_LEVELS → fallback
        assert cfg.claude_agents_persistent_memory == "off"


# ---------------------------------------------------------------------------
# AC5: apply_agent_memory_overrides
# ---------------------------------------------------------------------------

class TestApplyAgentMemoryOverrides:
    def test_writes_local_into_config(self, tmp_path: Path):
        from mapify_cli.config.project_config import (
            apply_agent_memory_overrides,
            generate_default_config,
        )

        cfg_path = _write_config(tmp_path, generate_default_config())
        apply_agent_memory_overrides(cfg_path, "local")
        text = cfg_path.read_text()
        assert "claude_agents.persistent_memory: local" in text

    def test_writes_project_into_config(self, tmp_path: Path):
        from mapify_cli.config.project_config import (
            apply_agent_memory_overrides,
            generate_default_config,
        )

        cfg_path = _write_config(tmp_path, generate_default_config())
        apply_agent_memory_overrides(cfg_path, "project")
        text = cfg_path.read_text()
        assert "claude_agents.persistent_memory: project" in text

    def test_idempotent_same_value(self, tmp_path: Path):
        from mapify_cli.config.project_config import (
            apply_agent_memory_overrides,
            generate_default_config,
        )

        cfg_path = _write_config(tmp_path, generate_default_config())
        apply_agent_memory_overrides(cfg_path, "local")
        apply_agent_memory_overrides(cfg_path, "local")
        text = cfg_path.read_text()
        assert text.count("claude_agents.persistent_memory: local") == 1

    def test_replace_existing_active_entry(self, tmp_path: Path):
        from mapify_cli.config.project_config import apply_agent_memory_overrides

        cfg_path = _write_config(
            tmp_path,
            "claude_agents.persistent_memory: local\n",
        )
        apply_agent_memory_overrides(cfg_path, "project")
        text = cfg_path.read_text()
        assert "claude_agents.persistent_memory: project" in text
        assert "claude_agents.persistent_memory: local" not in text

    def test_no_file_is_noop(self, tmp_path: Path):
        from mapify_cli.config.project_config import apply_agent_memory_overrides

        nonexistent = tmp_path / "nonexistent.yaml"
        apply_agent_memory_overrides(nonexistent, "local")  # must not raise


# ---------------------------------------------------------------------------
# AC6: apply_reflector_memory_field
# ---------------------------------------------------------------------------

class TestApplyReflectorMemoryField:
    def test_local_injects_user_local(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        _minimal_reflector(tmp_path)
        result = apply_reflector_memory_field(tmp_path, "local")
        assert result == 1
        text = (tmp_path / ".claude" / "agents" / "reflector.md").read_text()
        assert "memory: user_local" in text

    def test_project_injects_project(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        _minimal_reflector(tmp_path)
        result = apply_reflector_memory_field(tmp_path, "project")
        assert result == 1
        text = (tmp_path / ".claude" / "agents" / "reflector.md").read_text()
        assert "memory: project" in text

    def test_memory_inside_frontmatter(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        _minimal_reflector(tmp_path)
        apply_reflector_memory_field(tmp_path, "local")
        text = (tmp_path / ".claude" / "agents" / "reflector.md").read_text()
        # memory: line must appear inside the frontmatter block (before closing ---)
        fm_end = text.index("\n---", 4)
        frontmatter = text[:fm_end]
        assert "memory: user_local" in frontmatter

    def test_replaces_existing_memory_field(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        _minimal_reflector(tmp_path, extra_frontmatter="memory: user_local")
        result = apply_reflector_memory_field(tmp_path, "project")
        assert result == 1
        text = (tmp_path / ".claude" / "agents" / "reflector.md").read_text()
        assert "memory: project" in text
        assert "memory: user_local" not in text

    def test_idempotent_same_value(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        _minimal_reflector(tmp_path, extra_frontmatter="memory: user_local")
        result = apply_reflector_memory_field(tmp_path, "local")
        assert result == 0  # already up-to-date

    def test_missing_reflector_returns_zero(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import apply_reflector_memory_field

        result = apply_reflector_memory_field(tmp_path, "local")
        assert result == 0


# ---------------------------------------------------------------------------
# AC7: merge_agent_memory_gitignore
# ---------------------------------------------------------------------------

class TestMergeAgentMemoryGitignore:
    def test_creates_gitignore_if_absent(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import merge_agent_memory_gitignore

        result = merge_agent_memory_gitignore(tmp_path)
        assert result == 1
        assert (tmp_path / ".gitignore").exists()
        text = (tmp_path / ".gitignore").read_text()
        assert ".claude/agent-memory-local/" in text

    def test_appends_to_existing_gitignore(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import merge_agent_memory_gitignore

        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n")
        result = merge_agent_memory_gitignore(tmp_path)
        assert result == 1
        text = gi.read_text()
        assert "*.pyc" in text
        assert ".claude/agent-memory-local/" in text

    def test_idempotent_marker_present(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import merge_agent_memory_gitignore

        gi = tmp_path / ".gitignore"
        gi.write_text("# map:agent-memory-local\n.claude/agent-memory-local/\n")
        result = merge_agent_memory_gitignore(tmp_path)
        assert result == 0
        assert gi.read_text().count(".claude/agent-memory-local/") == 1

    def test_idempotent_line_present_without_marker(self, tmp_path: Path):
        from mapify_cli.delivery.file_copier import merge_agent_memory_gitignore

        gi = tmp_path / ".gitignore"
        gi.write_text(".claude/agent-memory-local/\n")
        result = merge_agent_memory_gitignore(tmp_path)
        assert result == 0
        assert gi.read_text().count(".claude/agent-memory-local/") == 1


# ---------------------------------------------------------------------------
# AC8: workflow-gate is_exempt_path exemptions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def is_exempt_path():
    import importlib.util
    import sys as _sys

    gate_path = _PROJECT_ROOT / ".claude" / "hooks" / "workflow-gate.py"
    assert gate_path.exists(), f"workflow-gate.py not found at {gate_path}"

    prev = _sys.dont_write_bytecode
    _sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("workflow_gate", gate_path)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        _sys.dont_write_bytecode = prev

    return mod.is_exempt_path


class TestWorkflowGateExemptions:
    """Load the rendered workflow-gate.py and test is_exempt_path directly."""

    def test_agent_memory_project_md_is_exempt(self, is_exempt_path):
        p = str(_PROJECT_ROOT / ".claude" / "agent-memory" / "lessons.md")
        assert is_exempt_path(p) is True

    def test_agent_memory_local_md_is_exempt(self, is_exempt_path):
        p = str(_PROJECT_ROOT / ".claude" / "agent-memory-local" / "lessons.md")
        assert is_exempt_path(p) is True

    def test_agent_memory_non_md_not_exempt(self, is_exempt_path):
        p = str(_PROJECT_ROOT / ".claude" / "agent-memory" / "script.py")
        assert is_exempt_path(p) is False

    def test_agent_memory_local_non_md_not_exempt(self, is_exempt_path):
        p = str(_PROJECT_ROOT / ".claude" / "agent-memory-local" / "config.json")
        assert is_exempt_path(p) is False

    def test_random_claude_dir_not_exempt(self, is_exempt_path):
        p = str(_PROJECT_ROOT / ".claude" / "some-dir" / "file.md")
        # only agent-memory and agent-memory-local are exempt; other dirs are not
        # (unless covered by an existing exemption like rules/learned)
        assert is_exempt_path(p) is False
