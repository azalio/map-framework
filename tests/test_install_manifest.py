"""Tests for the install manifest/lock (issue #313).

Covers:
  VC1: Claude install writes manifest with correct entries.
  VC2: Codex install writes manifest with correct entries.
  VC3: Re-init (write twice) is idempotent — second manifest overwrites first.
  VC4: check_installed detects missing files.
  VC5: check_installed detects drifted files (template_hash changed).
  VC6: check_installed detects orphaned files.
  VC7: read_manifest returns None for missing/corrupt manifest.
  VC8: management_mode is inferred correctly (fenced vs full vs hooks-merge).
  VC9: Local-only paths are excluded from the committed manifest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.delivery.managed_file_copier import (
    compute_hash,
    inject_metadata,
)
from mapify_cli.install_manifest import (
    MANIFEST_FILENAME,
    InstallManifest,
    _build_entry_from_file,
    _infer_management_mode,
    build_manifest,
    check_installed,
    read_manifest,
    write_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERSION = "3.21.0"


def _write_managed_file(
    path: Path,
    body: str,
    *,
    fenced: bool = True,
    version: str = VERSION,
    template_hash: str | None = None,
) -> None:
    """Write a minimal MAP-managed file at *path*.

    If *template_hash* is not given, it is computed from *body*.
    """
    ext = path.suffix.lower()
    th = template_hash if template_hash is not None else compute_hash(body)
    injected = inject_metadata(body, ext, version, th)

    if fenced and ext in (".md", ".py", ".sh", ".toml", ".yaml", ".yml"):
        fence_tokens = {
            ".md": ("<!-- map:start -->", "<!-- map:end -->"),
            ".py": ("# map:start", "# map:end"),
            ".sh": ("# map:start", "# map:end"),
            ".toml": ("# map:start", "# map:end"),
            ".yaml": ("# map:start", "# map:end"),
            ".yml": ("# map:start", "# map:end"),
        }
        start, end = fence_tokens[ext]
        # Find the metadata line end in injected
        meta_line_end = injected.index("\n") + 1
        meta_line = injected[:meta_line_end]
        rest_body = injected[meta_line_end:]
        content = meta_line + start + "\n" + rest_body + end + "\n"
    else:
        content = injected

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json_managed(path: Path, body: dict[str, Any], version: str = VERSION) -> None:
    """Write a MAP-managed JSON file at *path*."""
    raw = json.dumps(body, indent=2)
    managed = inject_metadata(raw, ".json", version, compute_hash(raw))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(managed, encoding="utf-8")


def _setup_claude_install(project: Path) -> list[str]:
    """Create a minimal Claude-provider install layout.

    Returns list of relative paths that should appear in the manifest.
    """
    installed: list[str] = []

    # .claude/agents/actor.md (fenced)
    p = project / ".claude" / "agents" / "actor.md"
    _write_managed_file(p, "# Actor\n\nAct.\n", fenced=True)
    installed.append(".claude/agents/actor.md")

    # .claude/skills/map-plan/SKILL.md (fenced)
    p = project / ".claude" / "skills" / "map-plan" / "SKILL.md"
    _write_managed_file(p, "# map-plan\n\nPlan.\n", fenced=True)
    installed.append(".claude/skills/map-plan/SKILL.md")

    # .claude/references/bash-guidelines.md (fenced)
    p = project / ".claude" / "references" / "bash-guidelines.md"
    _write_managed_file(p, "# Bash Guidelines\n\nContent.\n", fenced=True)
    installed.append(".claude/references/bash-guidelines.md")

    # .claude/hooks/workflow-gate.py (fenced)
    p = project / ".claude" / "hooks" / "workflow-gate.py"
    _write_managed_file(p, "# workflow-gate\npass\n", fenced=True)
    installed.append(".claude/hooks/workflow-gate.py")

    # .claude/settings.json (full JSON)
    p = project / ".claude" / "settings.json"
    _write_json_managed(p, {"theme": "dark"})
    installed.append(".claude/settings.json")

    # .map/scripts/map_step_runner.py (fenced=False, full mode)
    p = project / ".map" / "scripts" / "map_step_runner.py"
    _write_managed_file(p, "# runner\npass\n", fenced=False)
    installed.append(".map/scripts/map_step_runner.py")

    return sorted(installed)


def _setup_codex_install(project: Path) -> list[str]:
    """Create a minimal Codex-provider install layout.

    Returns list of relative paths that should appear in the manifest.
    """
    installed: list[str] = []

    # .agents/skills/map-plan/SKILL.md (fenced)
    p = project / ".agents" / "skills" / "map-plan" / "SKILL.md"
    _write_managed_file(p, "# map-plan\n\nPlan.\n", fenced=True)
    installed.append(".agents/skills/map-plan/SKILL.md")

    # .codex/agents/actor.toml (fenced)
    p = project / ".codex" / "agents" / "actor.toml"
    _write_managed_file(p, "[agent]\nname = \"actor\"\n", fenced=True)
    installed.append(".codex/agents/actor.toml")

    # .codex/config.toml (fenced)
    p = project / ".codex" / "config.toml"
    _write_managed_file(p, "[map]\nenabled = true\n", fenced=True)
    installed.append(".codex/config.toml")

    # .codex/hooks/workflow-gate.py (fenced)
    p = project / ".codex" / "hooks" / "workflow-gate.py"
    _write_managed_file(p, "# gate\npass\n", fenced=True)
    installed.append(".codex/hooks/workflow-gate.py")

    # .codex/hooks.json (hooks-merge, no MAP metadata)
    p = project / ".codex" / "hooks.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"hooks": {}}, indent=2) + "\n", encoding="utf-8")
    installed.append(".codex/hooks.json")

    # .map/scripts/map_step_runner.py (fenced=False)
    p = project / ".map" / "scripts" / "map_step_runner.py"
    _write_managed_file(p, "# runner\npass\n", fenced=False)
    installed.append(".map/scripts/map_step_runner.py")

    return sorted(installed)


# ---------------------------------------------------------------------------
# VC1: Claude install writes manifest with correct entries
# ---------------------------------------------------------------------------

class TestVC1ClaudeManifest:
    def test_build_manifest_claude_collects_all_managed_files(
        self, tmp_path: Path
    ) -> None:
        expected = _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)

        assert manifest.provider == "claude"
        assert manifest.mapify_version == VERSION
        assert manifest.installed_at != ""

        actual_dests = sorted(e.dest for e in manifest.entries)
        assert actual_dests == expected, (
            f"Expected {expected}, got {actual_dests}"
        )

    def test_build_and_write_manifest_roundtrip(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        manifest_path = write_manifest(tmp_path, manifest)

        assert manifest_path.exists()
        assert manifest_path == tmp_path / ".map" / MANIFEST_FILENAME

        loaded = read_manifest(tmp_path)
        assert loaded is not None
        assert loaded.provider == "claude"
        assert len(loaded.entries) == len(manifest.entries)
        loaded_dests = sorted(e.dest for e in loaded.entries)
        written_dests = sorted(e.dest for e in manifest.entries)
        assert loaded_dests == written_dests

    def test_manifest_entries_have_hashes(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)

        for entry in manifest.entries:
            if entry.management_mode == "hooks-merge":
                continue  # hooks-merge entries have empty template_hash
            assert entry.template_hash != "", f"{entry.dest} missing template_hash"
            assert entry.content_hash != "", f"{entry.dest} missing content_hash"

    def test_manifest_entries_have_correct_management_mode(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)

        by_dest = {e.dest: e for e in manifest.entries}

        # Fenced .md file
        agent = by_dest[".claude/agents/actor.md"]
        assert agent.management_mode == "fenced"

        # JSON file — always "full"
        settings = by_dest[".claude/settings.json"]
        assert settings.management_mode == "full"

        # .py installed with fenced=False — should be "full" (no fence markers)
        runner = by_dest[".map/scripts/map_step_runner.py"]
        assert runner.management_mode == "full"


# ---------------------------------------------------------------------------
# VC2: Codex install writes manifest with correct entries
# ---------------------------------------------------------------------------

class TestVC2CodexManifest:
    def test_build_manifest_codex_collects_all_managed_files(
        self, tmp_path: Path
    ) -> None:
        expected = _setup_codex_install(tmp_path)
        manifest = build_manifest(tmp_path, "codex", VERSION)

        assert manifest.provider == "codex"
        actual_dests = sorted(e.dest for e in manifest.entries)
        assert actual_dests == expected, (
            f"Expected {expected}, got {actual_dests}"
        )

    def test_codex_hooks_json_recorded_as_hooks_merge(self, tmp_path: Path) -> None:
        _setup_codex_install(tmp_path)
        manifest = build_manifest(tmp_path, "codex", VERSION)
        by_dest = {e.dest: e for e in manifest.entries}

        hooks_json = by_dest[".codex/hooks.json"]
        assert hooks_json.management_mode == "hooks-merge"
        assert hooks_json.committed is True

    def test_codex_managed_toml_recorded_as_fenced(self, tmp_path: Path) -> None:
        _setup_codex_install(tmp_path)
        manifest = build_manifest(tmp_path, "codex", VERSION)
        by_dest = {e.dest: e for e in manifest.entries}

        config = by_dest[".codex/config.toml"]
        assert config.management_mode == "fenced"
        assert config.template_hash != ""


# ---------------------------------------------------------------------------
# VC3: Re-init idempotency — writing manifest twice overwrites the first
# ---------------------------------------------------------------------------

class TestVC3Idempotency:
    def test_write_manifest_twice_overwrites(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)

        manifest1 = build_manifest(tmp_path, "claude", "3.21.0")
        write_manifest(tmp_path, manifest1)

        # Simulate a file being removed (orphan after re-init)
        (tmp_path / ".claude" / "agents" / "actor.md").unlink()

        manifest2 = build_manifest(tmp_path, "claude", "3.22.0")
        write_manifest(tmp_path, manifest2)

        loaded = read_manifest(tmp_path)
        assert loaded is not None
        assert loaded.mapify_version == "3.22.0", (
            "Second manifest write must overwrite the first"
        )
        # actor.md was removed, so manifest2 shouldn't contain it
        dests2 = {e.dest for e in manifest2.entries}
        assert ".claude/agents/actor.md" not in dests2


# ---------------------------------------------------------------------------
# VC4: check_installed detects missing files
# ---------------------------------------------------------------------------

class TestVC4MissingDetection:
    def test_missing_file_is_reported(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # Delete one managed file
        (tmp_path / ".claude" / "agents" / "actor.md").unlink()

        result = check_installed(tmp_path)
        assert ".claude/agents/actor.md" in result.missing
        assert ".claude/agents/actor.md" not in result.ok

    def test_all_ok_when_no_files_missing(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        result = check_installed(tmp_path)
        assert result.missing == []
        assert result.drifted == []
        assert result.orphaned == []
        assert len(result.ok) == len(manifest.entries)

    def test_missing_hooks_json_reported(self, tmp_path: Path) -> None:
        _setup_codex_install(tmp_path)
        manifest = build_manifest(tmp_path, "codex", VERSION)
        write_manifest(tmp_path, manifest)

        (tmp_path / ".codex" / "hooks.json").unlink()

        result = check_installed(tmp_path)
        assert ".codex/hooks.json" in result.missing


# ---------------------------------------------------------------------------
# VC5: check_installed detects drifted files
# ---------------------------------------------------------------------------

class TestVC5DriftDetection:
    def test_drifted_template_hash_reported(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # Simulate template update by overwriting with a new template_hash
        agent_path = tmp_path / ".claude" / "agents" / "actor.md"
        new_body = "# Actor\n\nNew template content.\n"
        _write_managed_file(
            agent_path,
            new_body,
            fenced=True,
            template_hash=compute_hash("new-template-body"),
        )

        result = check_installed(tmp_path)
        assert ".claude/agents/actor.md" in result.drifted
        assert ".claude/agents/actor.md" not in result.ok

    def test_same_hash_is_ok(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # Read the installed template_hash for actor.md
        by_dest = {e.dest: e for e in manifest.entries}
        recorded_hash = by_dest[".claude/agents/actor.md"].template_hash

        # Reinstall with the SAME template_hash (same template, re-install)
        _write_managed_file(
            tmp_path / ".claude" / "agents" / "actor.md",
            "# Actor\n\nAct.\n",
            fenced=True,
            template_hash=recorded_hash,
        )

        result = check_installed(tmp_path)
        assert ".claude/agents/actor.md" not in result.drifted
        assert ".claude/agents/actor.md" in result.ok

    def test_stripped_metadata_reported_as_drifted(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # User strips the MAP-MANAGED metadata from the file
        agent_path = tmp_path / ".claude" / "agents" / "actor.md"
        agent_path.write_text("# Actor\n\nAct.\n", encoding="utf-8")

        result = check_installed(tmp_path)
        assert ".claude/agents/actor.md" in result.drifted


# ---------------------------------------------------------------------------
# VC6: check_installed detects orphaned files
# ---------------------------------------------------------------------------

class TestVC6OrphanDetection:
    def test_orphaned_file_detected_after_manifest_written_without_it(
        self, tmp_path: Path
    ) -> None:
        # Write manifest before adding a new MAP-managed file
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # A new MAP-managed file appears (e.g., from a new template that was
        # installed manually but not re-manifested)
        orphan_path = tmp_path / ".claude" / "agents" / "new-agent.md"
        _write_managed_file(orphan_path, "# New Agent\n\nContent.\n", fenced=True)

        result = check_installed(tmp_path)
        assert ".claude/agents/new-agent.md" in result.orphaned

    def test_no_orphans_when_manifest_is_current(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        result = check_installed(tmp_path)
        assert result.orphaned == []


# ---------------------------------------------------------------------------
# VC7: read_manifest returns None for missing/corrupt
# ---------------------------------------------------------------------------

class TestVC7ReadManifestEdgeCases:
    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        result = read_manifest(tmp_path)
        assert result is None

    def test_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".map" / MANIFEST_FILENAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("not valid json{{{", encoding="utf-8")

        result = read_manifest(tmp_path)
        assert result is None

    def test_wrong_type_returns_none(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".map" / MANIFEST_FILENAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("[1, 2, 3]", encoding="utf-8")  # array, not object

        result = read_manifest(tmp_path)
        assert result is None

    def test_empty_manifest_returns_empty_entries(self, tmp_path: Path) -> None:
        manifest = InstallManifest(
            mapify_version="3.21.0",
            provider="claude",
            installed_at="2026-07-05T00:00:00Z",
            entries=[],
        )
        write_manifest(tmp_path, manifest)
        loaded = read_manifest(tmp_path)
        assert loaded is not None
        assert loaded.entries == []


# ---------------------------------------------------------------------------
# VC8: management_mode inference
# ---------------------------------------------------------------------------

class TestVC8ManagementModeInference:
    def test_md_with_fence_marker_is_fenced(self, tmp_path: Path) -> None:
        p = tmp_path / "test.md"
        content = "<!-- MAP-MANAGED: {} -->\n<!-- map:start -->\nbody\n<!-- map:end -->\n"
        assert _infer_management_mode(p, content, ".md") == "fenced"

    def test_md_without_fence_marker_is_full(self, tmp_path: Path) -> None:
        p = tmp_path / "test.md"
        content = "<!-- MAP-MANAGED: {} -->\nbody\n"
        assert _infer_management_mode(p, content, ".md") == "full"

    def test_py_with_fence_is_fenced(self, tmp_path: Path) -> None:
        p = tmp_path / "test.py"
        content = "# MAP-MANAGED: {}\n# map:start\npass\n# map:end\n"
        assert _infer_management_mode(p, content, ".py") == "fenced"

    def test_json_is_always_full(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        assert _infer_management_mode(p, "{}", ".json") == "full"

    def test_toml_with_fence_is_fenced(self, tmp_path: Path) -> None:
        p = tmp_path / "test.toml"
        content = "# MAP-MANAGED: {}\n# map:start\n[x]\n# map:end\n"
        assert _infer_management_mode(p, content, ".toml") == "fenced"


# ---------------------------------------------------------------------------
# VC9: Local-only paths excluded from the committed manifest
# ---------------------------------------------------------------------------

class TestVC9LocalOnlyExclusion:
    def test_settings_local_json_excluded(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)

        # Create a settings.local.json (machine-local, should be excluded)
        local_settings = tmp_path / ".claude" / "settings.local.json"
        _write_json_managed(local_settings, {"statusLine": {"type": "command", "command": "x"}})

        manifest = build_manifest(tmp_path, "claude", VERSION)
        dests = {e.dest for e in manifest.entries}
        assert ".claude/settings.local.json" not in dests, (
            "settings.local.json is machine-local and must not appear in the committed manifest"
        )

    def test_symlink_excluded(self, tmp_path: Path) -> None:
        _setup_codex_install(tmp_path)

        # Create a symlink at AGENTS.md (as the Codex provider does when CLAUDE.md exists)
        agents_md = tmp_path / "AGENTS.md"
        agents_md.symlink_to("CLAUDE.md")

        entry = _build_entry_from_file(tmp_path, agents_md)
        assert entry is None, "Symlinks must be excluded from the manifest"


# ---------------------------------------------------------------------------
# Integration: check_installed returns empty CheckResult when no manifest
# ---------------------------------------------------------------------------

class TestCheckInstalledNoManifest:
    def test_no_manifest_returns_empty_check_result(self, tmp_path: Path) -> None:
        result = check_installed(tmp_path)
        assert result.missing == []
        assert result.orphaned == []
        assert result.drifted == []
        assert result.ok == []
