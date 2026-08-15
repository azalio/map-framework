"""Tests for the install manifest/lock (issues #313 and #314).

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
  VC10 (#314): Config entries for MCP servers are detected and recorded.
  VC11 (#314): Config entries for statusline are detected and recorded.
  VC12 (#314): User-modified MCP servers are NOT recorded as MAP-owned.
  VC13 (#314): reconcile_config removes MAP-owned MCP server entry.
  VC14 (#314): reconcile_config preserves user-modified MCP server.
  VC15 (#314): reconcile_config removes MAP-owned statusline.
  VC16 (#314): reconcile_config refuses to remove user-defined statusline.
  VC17 (#314): read_manifest backward-compat — old manifest without config_entries.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import mapify_cli.install_manifest as install_manifest_module
from mapify_cli.delivery.managed_file_copier import (
    compute_hash,
    inject_metadata,
)
from mapify_cli.install_manifest import (
    MANIFEST_FILENAME,
    InstallManifest,
    ReconcileResult,
    _build_entry_from_file,
    _infer_management_mode,
    _scan_mcp_config_entries,
    _scan_statusline_config_entry,
    build_manifest,
    check_installed,
    normalize_providers,
    read_manifest,
    reconcile_config,
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


def test_write_manifest_fsyncs_a_same_directory_tempfile_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = InstallManifest(
        mapify_version=VERSION,
        provider="claude",
        installed_at="2026-08-13T00:00:00Z",
        providers=["claude"],
    )
    events: list[tuple[str, Path | None, Path | None]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(fd: int) -> None:
        events.append(("fsync", None, None))
        real_fsync(fd)

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        events.append(("replace", Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)

    manifest_path = write_manifest(tmp_path, manifest)

    assert [event[0] for event in events] == ["fsync", "replace"]
    _, temp_path, replacement_path = events[1]
    assert temp_path is not None
    assert replacement_path == manifest_path
    assert temp_path.parent == manifest_path.parent
    assert temp_path != manifest_path
    assert not temp_path.exists()
    assert read_manifest(tmp_path) == manifest


def test_write_manifest_replace_failure_preserves_old_file_and_cleans_tempfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = InstallManifest(
        mapify_version="3.25.0",
        provider="claude",
        installed_at="2026-08-13T00:00:00Z",
        providers=["claude"],
    )
    replacement = InstallManifest(
        mapify_version="3.26.0",
        provider="claude",
        installed_at="2026-08-14T00:00:00Z",
        providers=["claude"],
    )
    manifest_path = write_manifest(tmp_path, original)
    original_bytes = manifest_path.read_bytes()
    replace_error = OSError("replace failed")

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        del source, destination
        raise replace_error

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError) as caught:
        write_manifest(tmp_path, replacement)

    assert caught.value is replace_error
    assert manifest_path.read_bytes() == original_bytes
    assert read_manifest(tmp_path) == original
    assert list(manifest_path.parent.glob(f".{manifest_path.name}.*.tmp")) == []


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


def _valid_raw_manifest() -> dict[str, Any]:
    """Return a complete persisted manifest fixture with literal values."""
    return {
        "mapify_version": VERSION,
        "provider": "claude",
        "installed_at": "2026-07-05T00:00:00Z",
        "entries": [
            {
                "dest": ".claude/skills/map-plan/SKILL.md",
                "content_hash": "content-sha256",
                "template_hash": "template-sha256",
                "management_mode": "fenced",
                "committed": True,
                "mapify_version": VERSION,
                "installed_at": "2026-07-05T00:00:00Z",
            }
        ],
        "config_entries": [
            {
                "file": ".mcp.json",
                "key_path": "mcpServers.sequential-thinking",
                "installed_at": "2026-07-05T00:00:00Z",
                "mapify_version": VERSION,
            }
        ],
        "providers": ["claude"],
    }


def _write_raw_manifest(project_path: Path, payload: object) -> None:
    manifest_path = project_path / ".map" / MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


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
            providers=["claude"],
        )
        write_manifest(tmp_path, manifest)
        loaded = read_manifest(tmp_path)
        assert loaded is not None
        assert loaded.entries == []

    @pytest.mark.parametrize(
        "missing_field",
        ["mapify_version", "provider", "installed_at", "entries"],
    )
    def test_missing_required_manifest_field_returns_none(
        self,
        tmp_path: Path,
        missing_field: str,
    ) -> None:
        raw = _valid_raw_manifest()
        del raw[missing_field]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        ("field", "invalid_value"),
        [
            pytest.param("mapify_version", None, id="mapify-version-null"),
            pytest.param("mapify_version", 321, id="mapify-version-number"),
            pytest.param("installed_at", [], id="installed-at-array"),
            pytest.param("installed_at", {}, id="installed-at-object"),
            pytest.param("provider", [], id="legacy-provider-array"),
            pytest.param("provider", None, id="legacy-provider-null"),
        ],
    )
    def test_wrong_typed_manifest_metadata_returns_none(
        self,
        tmp_path: Path,
        field: str,
        invalid_value: object,
    ) -> None:
        raw = _valid_raw_manifest()
        raw[field] = invalid_value
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        "invalid_providers",
        [
            pytest.param("claude", id="string-not-array"),
            pytest.param({}, id="object-not-array"),
            pytest.param(None, id="null-not-array"),
            pytest.param([], id="empty-array"),
            pytest.param(["claude", 7], id="non-string-element"),
            pytest.param(["unknown"], id="unknown-provider"),
            pytest.param(["codex", "claude"], id="non-canonical-order"),
            pytest.param(["claude", "claude"], id="duplicate-provider"),
            pytest.param(["codex"], id="disagrees-with-legacy-provider"),
        ],
    )
    def test_malformed_providers_returns_none(
        self,
        tmp_path: Path,
        invalid_providers: object,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["providers"] = invalid_providers
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_wrong_typed_legacy_provider_without_providers_returns_none(
        self,
        tmp_path: Path,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["provider"] = []
        del raw["providers"]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        ("field", "invalid_value"),
        [
            pytest.param("entries", {}, id="entries-object"),
            pytest.param("entries", "entry", id="entries-string"),
            pytest.param("entries", None, id="entries-null"),
            pytest.param("config_entries", {}, id="config-entries-object"),
            pytest.param("config_entries", "entry", id="config-entries-string"),
            pytest.param("config_entries", None, id="config-entries-null"),
        ],
    )
    def test_non_list_record_collections_return_none(
        self,
        tmp_path: Path,
        field: str,
        invalid_value: object,
    ) -> None:
        raw = _valid_raw_manifest()
        raw[field] = invalid_value
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        "invalid_entry",
        [
            pytest.param("entry", id="not-an-object"),
            pytest.param({}, id="missing-fields"),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "unexpected": "field",
                },
                id="extra-field",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "dest": [],
                },
                id="dest-array",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "content_hash": None,
                },
                id="content-hash-null",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "template_hash": 12,
                },
                id="template-hash-number",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "management_mode": "partial",
                },
                id="invalid-management-mode",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "committed": "yes",
                },
                id="committed-string",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "mapify_version": [],
                },
                id="entry-mapify-version-array",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["entries"][0],
                    "installed_at": False,
                },
                id="entry-installed-at-boolean",
            ),
        ],
    )
    def test_malformed_manifest_entry_returns_none(
        self,
        tmp_path: Path,
        invalid_entry: object,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["entries"] = [invalid_entry]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        "invalid_config_entry",
        [
            pytest.param(7, id="not-an-object"),
            pytest.param({}, id="missing-fields"),
            pytest.param(
                {
                    **_valid_raw_manifest()["config_entries"][0],
                    "unexpected": "field",
                },
                id="extra-field",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["config_entries"][0],
                    "file": [],
                },
                id="file-array",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["config_entries"][0],
                    "key_path": None,
                },
                id="key-path-null",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["config_entries"][0],
                    "installed_at": 1,
                },
                id="installed-at-number",
            ),
            pytest.param(
                {
                    **_valid_raw_manifest()["config_entries"][0],
                    "mapify_version": {},
                },
                id="mapify-version-object",
            ),
        ],
    )
    def test_malformed_config_entry_returns_none(
        self,
        tmp_path: Path,
        invalid_config_entry: object,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["config_entries"] = [invalid_config_entry]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_invalid_utf8_returns_none(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".map" / MANIFEST_FILENAME
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(b"\xff\xfe")

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        "unsafe_dest",
        [
            pytest.param("", id="empty"),
            pytest.param(".claude/skills/\x00", id="nul-byte"),
            pytest.param(".", id="current-directory"),
            pytest.param("/tmp/x", id="posix-absolute"),
            pytest.param("../x", id="parent-traversal"),
            pytest.param(".claude/skills/../../x", id="nested-parent-traversal"),
            pytest.param(r"C:\tmp\x", id="windows-drive-backslashes"),
            pytest.param("C:/tmp/x", id="windows-drive-slashes"),
            pytest.param("C:relative", id="windows-drive-relative"),
            pytest.param(r"\rooted", id="windows-rooted"),
            pytest.param(r"\\server\share\x", id="windows-unc"),
            pytest.param(r".claude\skills\map-plan\SKILL.md", id="backslashes"),
            pytest.param(
                r".claude\skills\..\outside.md",
                id="backslash-traversal",
            ),
            pytest.param(
                ".claude//skills/map-plan/SKILL.md",
                id="redundant-separator",
            ),
            pytest.param(
                ".claude/./skills/map-plan/SKILL.md",
                id="dot-segment",
            ),
            pytest.param(
                ".claude/skills/map-plan/SKILL.md/",
                id="trailing-separator",
            ),
            pytest.param("README.md", id="outside-managed-roots"),
            pytest.param(
                ".claude/settings.local.json",
                id="machine-local-file",
            ),
        ],
    )
    def test_unsafe_or_unmanaged_dest_returns_none(
        self,
        tmp_path: Path,
        unsafe_dest: str,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["entries"][0]["dest"] = unsafe_dest
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_dest_must_belong_to_a_manifest_provider(self, tmp_path: Path) -> None:
        raw = _valid_raw_manifest()
        raw["entries"][0]["dest"] = ".codex/config.toml"
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        "unsafe_file",
        [
            pytest.param("", id="empty"),
            pytest.param("/tmp/settings.json", id="posix-absolute"),
            pytest.param("../settings.json", id="parent-traversal"),
            pytest.param(r"C:\tmp\settings.json", id="windows-drive-backslashes"),
            pytest.param("C:/tmp/settings.json", id="windows-drive-slashes"),
            pytest.param("C:settings.json", id="windows-drive-relative"),
            pytest.param(r"\settings.json", id="windows-rooted"),
            pytest.param(r"\\server\share\settings.json", id="windows-unc"),
            pytest.param(r"..\settings.json", id="backslash-traversal"),
            pytest.param(".claude//settings.local.json", id="redundant-separator"),
            pytest.param(".claude/./settings.local.json", id="dot-segment"),
        ],
    )
    def test_unsafe_config_file_returns_none(
        self,
        tmp_path: Path,
        unsafe_file: str,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["config_entries"][0]["file"] = unsafe_file
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    @pytest.mark.parametrize(
        ("file", "key_path"),
        [
            pytest.param(
                ".mcp.json",
                "statusLine",
                id="statusline-in-mcp-config",
            ),
            pytest.param(
                ".claude/settings.local.json",
                "mcpServers.sequential-thinking",
                id="mcp-server-in-statusline-config",
            ),
            pytest.param(
                ".mcp.json",
                "mcpServers.custom-server",
                id="unknown-mcp-server",
            ),
            pytest.param(
                ".mcp.json",
                "mcpServers.",
                id="empty-mcp-server-name",
            ),
        ],
    )
    def test_unowned_config_pair_returns_none(
        self,
        tmp_path: Path,
        file: str,
        key_path: str,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["config_entries"][0]["file"] = file
        raw["config_entries"][0]["key_path"] = key_path
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_config_entry_requires_claude_provider(self, tmp_path: Path) -> None:
        raw = _valid_raw_manifest()
        raw["provider"] = "codex"
        raw["providers"] = ["codex"]
        raw["entries"][0]["dest"] = ".codex/config.toml"
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_reconcile_rejects_outside_statusline_without_mutating_it(
        self,
        tmp_path: Path,
    ) -> None:
        outside_path = tmp_path.parent / f"{tmp_path.name}-outside-settings.json"
        original = (
            b'{"statusLine":{"type":"command",'
            b'"command":"map-statusline.py"},"keep":true}\n'
        )
        outside_path.write_bytes(original)
        raw = _valid_raw_manifest()
        raw["config_entries"] = [
            {
                "file": str(outside_path),
                "key_path": "statusLine",
                "installed_at": "2026-07-05T00:00:00Z",
                "mapify_version": VERSION,
            }
        ]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None
        assert reconcile_config(tmp_path) == ReconcileResult()
        assert outside_path.read_bytes() == original

    def test_reconcile_rejects_unknown_mcp_owner_without_mutating_config(
        self,
        tmp_path: Path,
    ) -> None:
        mcp_path = tmp_path / ".mcp.json"
        original = b'{"mcpServers":{"custom-server":null},"keep":true}\n'
        mcp_path.write_bytes(original)
        raw = _valid_raw_manifest()
        raw["config_entries"] = [
            {
                "file": ".mcp.json",
                "key_path": "mcpServers.custom-server",
                "installed_at": "2026-07-05T00:00:00Z",
                "mapify_version": VERSION,
            }
        ]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None
        assert reconcile_config(tmp_path) == ReconcileResult()
        assert mcp_path.read_bytes() == original

    def test_read_rejects_statusline_through_symlinked_claude_directory(
        self,
        tmp_path: Path,
    ) -> None:
        outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-claude"
        outside_dir.mkdir()
        outside_settings = outside_dir / "settings.local.json"
        original = b'{"statusLine":{"command":"map-statusline.py"},"keep":true}\n'
        outside_settings.write_bytes(original)
        (tmp_path / ".claude").symlink_to(outside_dir, target_is_directory=True)
        raw = _valid_raw_manifest()
        raw["entries"] = []
        raw["config_entries"] = [
            {
                "file": ".claude/settings.local.json",
                "key_path": "statusLine",
                "installed_at": "2026-07-05T00:00:00Z",
                "mapify_version": VERSION,
            }
        ]
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None
        assert reconcile_config(tmp_path) == ReconcileResult()
        assert outside_settings.read_bytes() == original

    def test_read_rejects_mcp_config_final_symlink(
        self,
        tmp_path: Path,
    ) -> None:
        outside_mcp = tmp_path.parent / f"{tmp_path.name}-outside-mcp.json"
        original = json.dumps(
            {"mcpServers": {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG}, "keep": True}
        ).encode()
        outside_mcp.write_bytes(original)
        (tmp_path / ".mcp.json").symlink_to(outside_mcp)
        raw = _valid_raw_manifest()
        raw["entries"] = []
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None
        assert reconcile_config(tmp_path) == ReconcileResult()
        assert outside_mcp.read_bytes() == original

    def test_read_rejects_managed_dest_through_symlinked_ancestor(
        self,
        tmp_path: Path,
    ) -> None:
        outside_skills = tmp_path.parent / f"{tmp_path.name}-outside-skills"
        outside_skill = outside_skills / "map-plan" / "SKILL.md"
        _write_managed_file(outside_skill, "outside\n")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "skills").symlink_to(
            outside_skills,
            target_is_directory=True,
        )
        raw = _valid_raw_manifest()
        raw["config_entries"] = []
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_read_rejects_managed_dest_final_symlink(self, tmp_path: Path) -> None:
        outside_skill = tmp_path.parent / f"{tmp_path.name}-outside-skill.md"
        _write_managed_file(outside_skill, "outside\n")
        managed_skill = tmp_path / ".claude" / "skills" / "map-plan" / "SKILL.md"
        managed_skill.parent.mkdir(parents=True)
        managed_skill.symlink_to(outside_skill)
        raw = _valid_raw_manifest()
        raw["config_entries"] = []
        _write_raw_manifest(tmp_path, raw)

        assert read_manifest(tmp_path) is None

    def test_check_revalidates_ancestor_symlinks_after_manifest_load(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw = _valid_raw_manifest()
        raw["config_entries"] = []
        _write_raw_manifest(tmp_path, raw)
        accepted_manifest = read_manifest(tmp_path)
        assert accepted_manifest is not None

        outside_skills = tmp_path.parent / f"{tmp_path.name}-late-skills"
        outside_skill = outside_skills / "map-plan" / "SKILL.md"
        _write_managed_file(
            outside_skill,
            "outside\n",
            template_hash="template-sha256",
        )
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "skills").symlink_to(
            outside_skills,
            target_is_directory=True,
        )
        monkeypatch.setattr(
            install_manifest_module,
            "read_manifest",
            lambda project_path: accepted_manifest,
        )

        result = check_installed(tmp_path)

        assert ".claude/skills/map-plan/SKILL.md" in result.missing
        assert ".claude/skills/map-plan/SKILL.md" not in result.ok

    def test_reconcile_revalidates_statusline_ancestor_before_mutation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        settings.write_text('{"statusLine":{"command":"map-statusline.py"}}\n')
        raw = _valid_raw_manifest()
        raw["entries"] = []
        raw["config_entries"] = [
            {
                "file": ".claude/settings.local.json",
                "key_path": "statusLine",
                "installed_at": "2026-07-05T00:00:00Z",
                "mapify_version": VERSION,
            }
        ]
        _write_raw_manifest(tmp_path, raw)
        accepted_manifest = read_manifest(tmp_path)
        assert accepted_manifest is not None

        safe_claude = tmp_path / ".claude-safe"
        settings.parent.rename(safe_claude)
        outside_claude = tmp_path.parent / f"{tmp_path.name}-late-claude"
        outside_claude.mkdir()
        outside_settings = outside_claude / "settings.local.json"
        original = b'{"statusLine":{"command":"map-statusline.py"},"keep":true}\n'
        outside_settings.write_bytes(original)
        (tmp_path / ".claude").symlink_to(
            outside_claude,
            target_is_directory=True,
        )
        monkeypatch.setattr(
            install_manifest_module,
            "read_manifest",
            lambda project_path: accepted_manifest,
        )

        result = reconcile_config(tmp_path)

        assert result.removed == []
        assert outside_settings.read_bytes() == original

    def test_reconcile_revalidates_mcp_final_symlink_before_mutation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(
            json.dumps({"mcpServers": {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG}}),
            encoding="utf-8",
        )
        raw = _valid_raw_manifest()
        raw["entries"] = []
        _write_raw_manifest(tmp_path, raw)
        accepted_manifest = read_manifest(tmp_path)
        assert accepted_manifest is not None

        safe_mcp = tmp_path / ".mcp.safe.json"
        mcp_path.rename(safe_mcp)
        outside_mcp = tmp_path.parent / f"{tmp_path.name}-late-mcp.json"
        original = json.dumps(
            {"mcpServers": {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG}, "keep": True}
        ).encode()
        outside_mcp.write_bytes(original)
        mcp_path.symlink_to(outside_mcp)
        monkeypatch.setattr(
            install_manifest_module,
            "read_manifest",
            lambda project_path: accepted_manifest,
        )

        result = reconcile_config(tmp_path)

        assert result.removed == []
        assert outside_mcp.read_bytes() == original

    def test_read_rejects_symlinked_manifest_file(self, tmp_path: Path) -> None:
        outside_manifest = tmp_path.parent / f"{tmp_path.name}-manifest.json"
        outside_manifest.write_text(json.dumps(_valid_raw_manifest()), encoding="utf-8")
        manifest_path = tmp_path / ".map" / MANIFEST_FILENAME
        manifest_path.parent.mkdir()
        manifest_path.symlink_to(outside_manifest)

        assert read_manifest(tmp_path) is None

    def test_write_rejects_symlinked_map_directory(self, tmp_path: Path) -> None:
        outside_map = tmp_path.parent / f"{tmp_path.name}-outside-map"
        outside_map.mkdir()
        (tmp_path / ".map").symlink_to(outside_map, target_is_directory=True)
        manifest = InstallManifest(
            mapify_version=VERSION,
            provider="claude",
            installed_at="2026-07-05T00:00:00Z",
            providers=["claude"],
        )

        with pytest.raises(OSError, match="symlink"):
            write_manifest(tmp_path, manifest)

        assert not (outside_map / MANIFEST_FILENAME).exists()

    def test_write_rejects_symlinked_manifest_file(self, tmp_path: Path) -> None:
        outside_manifest = tmp_path.parent / f"{tmp_path.name}-write-target.json"
        original = b"outside sentinel\n"
        outside_manifest.write_bytes(original)
        manifest_path = tmp_path / ".map" / MANIFEST_FILENAME
        manifest_path.parent.mkdir()
        manifest_path.symlink_to(outside_manifest)
        manifest = InstallManifest(
            mapify_version=VERSION,
            provider="claude",
            installed_at="2026-07-05T00:00:00Z",
            providers=["claude"],
        )

        with pytest.raises(OSError, match="symlink"):
            write_manifest(tmp_path, manifest)

        assert outside_manifest.read_bytes() == original


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


# ---------------------------------------------------------------------------
# VC10: Config entries for MCP servers are detected
# ---------------------------------------------------------------------------

_MAP_SERVER_NAME = "sequential-thinking"
_MAP_SERVER_CONFIG = {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
}
_TIMESTAMP = "2026-07-05T00:00:00Z"


def _write_mcp_json(project: Path, servers: dict) -> None:
    """Write .mcp.json with the given mcpServers dict."""
    (project / ".mcp.json").write_text(
        __import__("json").dumps({"mcpServers": servers}, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_statusline_local(project: Path, command: str) -> None:
    """Write .claude/settings.local.json with the given statusLine command."""
    settings = project / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        __import__("json").dumps(
            {"statusLine": {"type": "command", "command": command}}, indent=2
        ) + "\n",
        encoding="utf-8",
    )


class TestVC10McpConfigEntries:
    def test_map_server_detected_when_value_matches(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        assert len(entries) == 1
        e = entries[0]
        assert e.file == ".mcp.json"
        assert e.key_path == f"mcpServers.{_MAP_SERVER_NAME}"
        assert e.installed_at == _TIMESTAMP
        assert e.mapify_version == VERSION

    def test_no_mcp_json_returns_empty(self, tmp_path: Path) -> None:
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        assert entries == []

    def test_empty_mcp_servers_returns_empty(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {})
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        assert entries == []

    def test_build_manifest_includes_mcp_config_entries(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        manifest = build_manifest(tmp_path, "claude", VERSION)
        assert len(manifest.config_entries) >= 1
        keys = [e.key_path for e in manifest.config_entries]
        assert f"mcpServers.{_MAP_SERVER_NAME}" in keys

    def test_config_entries_empty_for_codex_provider(self, tmp_path: Path) -> None:
        _setup_codex_install(tmp_path)
        # Even if .mcp.json exists, codex provider doesn't own MCP entries
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        manifest = build_manifest(tmp_path, "codex", VERSION)
        assert manifest.config_entries == []

    def test_config_entry_has_no_absolute_paths(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        for e in entries:
            assert not e.file.startswith("/"), "file must be relative"
            assert not e.key_path.startswith("/"), "key_path must not contain absolute path"


# ---------------------------------------------------------------------------
# VC11: Config entries for statusline are detected
# ---------------------------------------------------------------------------

class TestVC11StatuslineConfigEntry:
    def test_map_statusline_detected(self, tmp_path: Path) -> None:
        _write_statusline_local(tmp_path, '"/abs/path/to/.claude/hooks/map-statusline.py"')
        entry = _scan_statusline_config_entry(tmp_path, VERSION, _TIMESTAMP)
        assert entry is not None
        assert entry.file == ".claude/settings.local.json"
        assert entry.key_path == "statusLine"
        assert entry.installed_at == _TIMESTAMP
        assert entry.mapify_version == VERSION

    def test_no_settings_local_returns_none(self, tmp_path: Path) -> None:
        entry = _scan_statusline_config_entry(tmp_path, VERSION, _TIMESTAMP)
        assert entry is None

    def test_user_defined_statusline_returns_none(self, tmp_path: Path) -> None:
        _write_statusline_local(tmp_path, "my-custom-statusline.sh")
        entry = _scan_statusline_config_entry(tmp_path, VERSION, _TIMESTAMP)
        assert entry is None

    def test_missing_statusline_key_returns_none(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"theme": "dark"}\n', encoding="utf-8")
        entry = _scan_statusline_config_entry(tmp_path, VERSION, _TIMESTAMP)
        assert entry is None

    def test_statusline_not_a_dict_returns_none(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"statusLine": "some-string"}\n', encoding="utf-8")
        entry = _scan_statusline_config_entry(tmp_path, VERSION, _TIMESTAMP)
        assert entry is None

    def test_build_manifest_includes_statusline_config_entry(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        _write_statusline_local(tmp_path, '"/path/to/map-statusline.py"')
        manifest = build_manifest(tmp_path, "claude", VERSION)
        keys = [e.key_path for e in manifest.config_entries]
        assert "statusLine" in keys


# ---------------------------------------------------------------------------
# VC12: User-modified MCP servers are NOT recorded as MAP-owned
# ---------------------------------------------------------------------------

class TestVC12UserModifiedMcp:
    def test_user_modified_server_not_recorded(self, tmp_path: Path) -> None:
        user_config = {"command": "npx", "args": ["-y", "my-custom-version"]}
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: user_config})
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        assert entries == [], "user-modified config must not be recorded as MAP-owned"

    def test_extra_user_server_not_recorded(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {
            _MAP_SERVER_NAME: _MAP_SERVER_CONFIG,
            "user-custom-server": {"command": "node", "args": ["server.js"]},
        })
        entries = _scan_mcp_config_entries(tmp_path, VERSION, _TIMESTAMP)
        keys = [e.key_path for e in entries]
        assert f"mcpServers.{_MAP_SERVER_NAME}" in keys
        assert "mcpServers.user-custom-server" not in keys


# ---------------------------------------------------------------------------
# VC13: reconcile_config removes MAP-owned MCP server entry
# ---------------------------------------------------------------------------

class TestVC13ReconcileMcpRemove:
    def test_removes_map_owned_server(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        result = reconcile_config(tmp_path)
        assert f".mcp.json:mcpServers.{_MAP_SERVER_NAME}" in result.removed

        # Verify the server was actually removed from disk
        mcp_json = __import__("json").loads(
            (tmp_path / ".mcp.json").read_text(encoding="utf-8")
        )
        assert _MAP_SERVER_NAME not in mcp_json.get("mcpServers", {})

    def test_preserves_other_top_level_keys(self, tmp_path: Path) -> None:
        (tmp_path / ".mcp.json").write_text(
            __import__("json").dumps({
                "mcpServers": {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG},
                "globalShortcut": "Cmd+Shift+.",
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        reconcile_config(tmp_path)

        mcp_json = __import__("json").loads(
            (tmp_path / ".mcp.json").read_text(encoding="utf-8")
        )
        assert "globalShortcut" in mcp_json, "user top-level keys must be preserved"

    def test_no_manifest_returns_empty_result(self, tmp_path: Path) -> None:
        result = reconcile_config(tmp_path)
        assert result.removed == []
        assert result.skipped == []
        assert result.missing == []

    def test_already_absent_server_is_missing(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # Remove the server before reconciling
        (tmp_path / ".mcp.json").write_text(
            '{"mcpServers": {}}\n', encoding="utf-8"
        )

        result = reconcile_config(tmp_path)
        assert f".mcp.json:mcpServers.{_MAP_SERVER_NAME}" in result.missing
        assert result.removed == []


# ---------------------------------------------------------------------------
# VC14: reconcile_config preserves user-modified MCP server
# ---------------------------------------------------------------------------

class TestVC14ReconcilePreservesUserModified:
    def test_user_modified_server_skipped(self, tmp_path: Path) -> None:
        # Install with MAP config
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # User later modifies the server config
        user_modified = {"command": "npx", "args": ["-y", "my-custom-version"]}
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: user_modified})

        result = reconcile_config(tmp_path)
        assert f".mcp.json:mcpServers.{_MAP_SERVER_NAME}" in result.skipped
        assert result.removed == []

        # Verify the user's config is still on disk
        mcp_json = __import__("json").loads(
            (tmp_path / ".mcp.json").read_text(encoding="utf-8")
        )
        assert mcp_json["mcpServers"][_MAP_SERVER_NAME] == user_modified


# ---------------------------------------------------------------------------
# VC15: reconcile_config removes MAP-owned statusline
# ---------------------------------------------------------------------------

class TestVC15ReconcileStatuslineRemove:
    def test_removes_map_owned_statusline(self, tmp_path: Path) -> None:
        _setup_claude_install(tmp_path)
        _write_statusline_local(tmp_path, '"/path/to/map-statusline.py"')
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        result = reconcile_config(tmp_path)
        assert ".claude/settings.local.json:statusLine" in result.removed

        # Verify the statusLine key was removed from disk
        settings = __import__("json").loads(
            (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
        )
        assert "statusLine" not in settings

    def test_preserves_other_settings_keys(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            __import__("json").dumps({
                "statusLine": {"type": "command", "command": '"/path/map-statusline.py"'},
                "permissions": {"allow": ["Bash"]},
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        reconcile_config(tmp_path)

        remaining = __import__("json").loads(
            settings.read_text(encoding="utf-8")
        )
        assert "permissions" in remaining, "user settings keys must be preserved"
        assert "statusLine" not in remaining


# ---------------------------------------------------------------------------
# VC16: reconcile_config refuses to remove user-defined statusline
# ---------------------------------------------------------------------------

class TestVC16ReconcileRefusesUserStatusline:
    def test_user_defined_statusline_skipped(self, tmp_path: Path) -> None:
        # Build manifest with MAP statusline
        _write_statusline_local(tmp_path, '"/path/to/map-statusline.py"')
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # User replaces the statusline with their own
        _write_statusline_local(tmp_path, "my-custom-status-command")

        result = reconcile_config(tmp_path)
        assert ".claude/settings.local.json:statusLine" in result.skipped
        assert result.removed == []

    def test_no_statusline_key_is_missing(self, tmp_path: Path) -> None:
        # Build manifest that expects a statusLine
        _write_statusline_local(tmp_path, '"/path/to/map-statusline.py"')
        manifest = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, manifest)

        # User removes the key manually
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.write_text('{"theme": "dark"}\n', encoding="utf-8")

        result = reconcile_config(tmp_path)
        assert ".claude/settings.local.json:statusLine" in result.missing
        assert result.removed == []


# ---------------------------------------------------------------------------
# VC17: read_manifest backward compatibility — old manifest without config_entries
# ---------------------------------------------------------------------------

class TestVC17BackwardCompat:
    def test_old_manifest_without_config_entries_readable(self, tmp_path: Path) -> None:
        old_manifest = {
            "mapify_version": "3.10.0",
            "provider": "claude",
            "installed_at": "2026-01-01T00:00:00Z",
            "entries": [],
            # config_entries deliberately absent (old format)
        }
        map_dir = tmp_path / ".map"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "mapify.lock.json").write_text(
            __import__("json").dumps(old_manifest, indent=2) + "\n",
            encoding="utf-8",
        )

        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.mapify_version == "3.10.0"
        assert manifest.config_entries == [], "old manifests must deserialize with empty config_entries"

    def test_idempotent_build_does_not_duplicate_config_entries(self, tmp_path: Path) -> None:
        _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
        _write_statusline_local(tmp_path, '"/path/map-statusline.py"')

        m1 = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, m1)

        m2 = build_manifest(tmp_path, "claude", VERSION)
        write_manifest(tmp_path, m2)

        m_read = read_manifest(tmp_path)
        assert m_read is not None
        config_keys = [e.key_path for e in m_read.config_entries]
        assert len(config_keys) == len(set(config_keys)), "no duplicate config entries"


# ---------------------------------------------------------------------------
# Provider-aware manifests: legacy compatibility and dual-provider auditing
# ---------------------------------------------------------------------------


def test_old_single_provider_manifest_populates_providers(tmp_path: Path) -> None:
    raw = {
        "mapify_version": VERSION,
        "provider": "claude",
        "installed_at": _TIMESTAMP,
        "entries": [],
    }
    path = tmp_path / ".map" / MANIFEST_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = read_manifest(tmp_path)

    assert loaded is not None
    assert loaded.provider == "claude"
    assert loaded.providers == ["claude"]


def test_provider_normalization_orders_and_deduplicates_requested_providers() -> None:
    assert normalize_providers(["codex", "claude", "codex"]) == ["claude", "codex"]


def test_legacy_dual_provider_manifest_populates_both_providers(tmp_path: Path) -> None:
    raw = {
        "mapify_version": VERSION,
        "provider": "claude+codex",
        "installed_at": _TIMESTAMP,
        "entries": [],
    }
    path = tmp_path / ".map" / MANIFEST_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = read_manifest(tmp_path)

    assert loaded is not None
    assert loaded.providers == ["claude", "codex"]


def test_dual_provider_manifest_contains_union_without_duplicate_shared_files(
    tmp_path: Path,
) -> None:
    _setup_claude_install(tmp_path)
    _setup_codex_install(tmp_path)

    manifest = build_manifest(tmp_path, ["claude", "codex"], VERSION)

    assert manifest.providers == ["claude", "codex"]
    destinations = [entry.dest for entry in manifest.entries]
    assert len(destinations) == len(set(destinations))
    assert any(dest.startswith(".claude/") for dest in destinations)
    assert any(
        dest.startswith((".codex/", ".agents/"))
        for dest in destinations
    )


def test_dual_provider_manifest_serializes_legacy_provider_field(tmp_path: Path) -> None:
    _setup_claude_install(tmp_path)
    _setup_codex_install(tmp_path)

    manifest = build_manifest(tmp_path, ["claude", "codex"], VERSION)

    assert manifest.provider == "claude+codex"


def test_dual_provider_manifest_preserves_claude_config_entries(tmp_path: Path) -> None:
    _setup_claude_install(tmp_path)
    _setup_codex_install(tmp_path)
    _write_mcp_json(tmp_path, {_MAP_SERVER_NAME: _MAP_SERVER_CONFIG})
    _write_statusline_local(tmp_path, '"/path/to/map-statusline.py"')

    manifest = build_manifest(tmp_path, ["claude", "codex"], VERSION)

    assert {entry.key_path for entry in manifest.config_entries} == {
        f"mcpServers.{_MAP_SERVER_NAME}",
        "statusLine",
    }


def test_check_installed_scans_both_provider_roots(tmp_path: Path) -> None:
    _setup_claude_install(tmp_path)
    _setup_codex_install(tmp_path)
    write_manifest(tmp_path, build_manifest(tmp_path, ["claude", "codex"], VERSION))
    extra = tmp_path / ".agents" / "skills" / "map-extra" / "SKILL.md"
    _write_managed_file(extra, "# Extra\n", fenced=True)

    assert ".agents/skills/map-extra/SKILL.md" in check_installed(tmp_path).orphaned
