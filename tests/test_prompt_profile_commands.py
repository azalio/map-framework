"""Tests for mapify prompt-profile sub-commands (#353).

Covers:
  PP1 — empty project list behavior
  PP2 — installed profiles appear in output
  PP3 — missing/malformed manifest graceful degradation
  PP4 — --json flag on list
  PP5 — active profile marker from active.json
  PP6 — stale active pointer warning
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mapify_cli import app

runner = CliRunner()


def _profiles_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".map" / "prompt-profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_profile(profiles_root: Path, profile_id: str, manifest: dict) -> Path:
    profile_dir = profiles_root / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return profile_dir


def _set_active(profiles_root: Path, profile_id: str | None) -> None:
    (profiles_root / "active.json").write_text(
        json.dumps({"active": profile_id}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# PP1 — empty project list behavior
# ---------------------------------------------------------------------------


class TestPp1EmptyList:
    def test_no_profiles_dir_shows_message(self, tmp_path: Path):
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No prompt profiles found" in result.output

    def test_empty_profiles_dir_shows_message(self, tmp_path: Path):
        _profiles_dir(tmp_path)
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No prompt profiles found" in result.output

    def test_empty_message_includes_creation_hint(self, tmp_path: Path):
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "manifest.json" in result.output


# ---------------------------------------------------------------------------
# PP2 — installed profiles appear in output
# ---------------------------------------------------------------------------


class TestPp2InstalledProfiles:
    def test_single_profile_shows_id(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "efficiency-v2", {"id": "efficiency-v2", "title": "Efficiency v2", "version": "1.0.0"})
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "efficiency-v2" in result.output

    def test_single_profile_shows_title(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "my-profile", {"id": "my-profile", "title": "My Profile Title", "version": "0.1.0"})
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "My Profile Title" in result.output

    def test_multiple_profiles_shown(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "alpha", {"id": "alpha", "title": "Alpha", "version": "1.0.0"})
        _make_profile(root, "beta", {"id": "beta", "title": "Beta", "version": "2.0.0"})
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" in result.output

    def test_optional_description_shown(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "p1", {
            "id": "p1", "title": "Profile 1", "version": "1.0.0",
            "description": "Improves actor token efficiency"
        })
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Improves actor token efficiency" in result.output


# ---------------------------------------------------------------------------
# PP3 — missing/malformed manifest graceful degradation
# ---------------------------------------------------------------------------


class TestPp3MalformedManifest:
    def test_dir_without_manifest_json_skipped(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        (root / "orphan-dir").mkdir()
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "orphan-dir" not in result.output

    def test_invalid_json_manifest_skipped(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        bad_dir = root / "broken"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "broken" not in result.output

    def test_manifest_missing_required_keys_skipped(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "incomplete", {"id": "incomplete", "title": "No version"})
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "incomplete" not in result.output

    def test_valid_profile_still_shown_when_invalid_sibling(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "good", {"id": "good", "title": "Good", "version": "1.0.0"})
        (root / "bad").mkdir()
        (root / "bad" / "manifest.json").write_text("{bad}", encoding="utf-8")
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "good" in result.output


# ---------------------------------------------------------------------------
# PP4 — --json flag on list
# ---------------------------------------------------------------------------


class TestPp4JsonOutput:
    def test_json_output_empty(self, tmp_path: Path):
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["profiles"] == []
        assert data["active"] is None

    def test_json_output_contains_profiles(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "p1", {"id": "p1", "title": "P1", "version": "1.0.0"})
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["profiles"]) == 1
        assert data["profiles"][0]["id"] == "p1"

    def test_json_required_fields_present(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "x", {"id": "x", "title": "X", "version": "2.0.0", "description": "test"})
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        profile = data["profiles"][0]
        for key in ("id", "title", "version", "description", "targets", "active"):
            assert key in profile, f"missing key: {key}"

    def test_json_active_field_null_when_no_active(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "x", {"id": "x", "title": "X", "version": "1.0.0"})
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["active"] is None
        assert data["profiles"][0]["active"] is False


# ---------------------------------------------------------------------------
# PP5 — active profile marker from active.json
# ---------------------------------------------------------------------------


class TestPp5ActiveProfile:
    def test_active_profile_marked_in_table(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "p1", {"id": "p1", "title": "P1", "version": "1.0.0"})
        _make_profile(root, "p2", {"id": "p2", "title": "P2", "version": "1.0.0"})
        _set_active(root, "p1")
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "active" in result.output

    def test_active_profile_json_flag(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "p1", {"id": "p1", "title": "P1", "version": "1.0.0"})
        _set_active(root, "p1")
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["active"] == "p1"
        assert data["profiles"][0]["active"] is True

    def test_inactive_profile_not_marked_active(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "p1", {"id": "p1", "title": "P1", "version": "1.0.0"})
        _make_profile(root, "p2", {"id": "p2", "title": "P2", "version": "1.0.0"})
        _set_active(root, "p1")
        result = runner.invoke(app, ["prompt-profile", "list", "--json", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        profiles_by_id = {p["id"]: p for p in data["profiles"]}
        assert profiles_by_id["p1"]["active"] is True
        assert profiles_by_id["p2"]["active"] is False


# ---------------------------------------------------------------------------
# PP6 — stale active pointer warning
# ---------------------------------------------------------------------------


class TestPp6StaleActivePointer:
    def test_stale_pointer_shows_warning(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "real", {"id": "real", "title": "Real", "version": "1.0.0"})
        _set_active(root, "deleted-profile")
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "stale" in result.output.lower() or "Warning" in result.output

    def test_stale_pointer_still_shows_real_profiles(self, tmp_path: Path):
        root = _profiles_dir(tmp_path)
        _make_profile(root, "real", {"id": "real", "title": "Real", "version": "1.0.0"})
        _set_active(root, "ghost")
        result = runner.invoke(app, ["prompt-profile", "list", "--project-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "real" in result.output
