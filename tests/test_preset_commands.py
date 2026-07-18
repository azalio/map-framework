"""Tests for 'mapify preset' commands (#291 — Slice 1).

Covers:
  PC1 — preset list: empty project, no presets installed
  PC2 — preset list: one or more valid presets
  PC3 — preset list: preset with missing manifest (graceful degradation)
  PC4 — preset list: --json flag
  PC5 — preset add --from: valid preset installed correctly
  PC6 — preset add --from: invalid source (not a dir, missing manifest, bad id)
  PC7 — preset add --from: --force overwrites existing preset
  PC8 — preset add --from: refused without --force when preset already exists
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mapify_cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preset_dir(tmp_path: Path, name: str, manifest: dict) -> Path:
    """Create a preset source directory with a manifest.json."""
    src = tmp_path / f"_src_{name}"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return src


def _installed_preset(project: Path, preset_id: str) -> Path:
    return project / ".map" / "presets" / preset_id


# ---------------------------------------------------------------------------
# PC1 — preset list: empty project
# ---------------------------------------------------------------------------


class TestPc1PresetListEmpty:
    def test_no_presets_dir_exits_zero(self, tmp_path: Path):
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0

    def test_no_presets_dir_prints_guidance(self, tmp_path: Path):
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert "No presets installed" in result.output

    def test_empty_presets_dir_exits_zero(self, tmp_path: Path):
        (tmp_path / ".map" / "presets").mkdir(parents=True)
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0

    def test_empty_presets_dir_prints_guidance(self, tmp_path: Path):
        (tmp_path / ".map" / "presets").mkdir(parents=True)
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert "No presets installed" in result.output


# ---------------------------------------------------------------------------
# PC2 — preset list: installed presets appear in output
# ---------------------------------------------------------------------------


class TestPc2PresetListWithPresets:
    def _install(self, project: Path, name: str, manifest: dict) -> None:
        dest = project / ".map" / "presets" / name
        dest.mkdir(parents=True)
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_single_preset_shown(self, tmp_path: Path):
        self._install(tmp_path, "lean", {"id": "lean", "title": "Lean Workflow", "version": "1.0.0"})
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0
        assert "lean" in result.output
        assert "Lean Workflow" in result.output
        assert "1.0.0" in result.output

    def test_multiple_presets_all_shown(self, tmp_path: Path):
        for pid in ("lean", "enterprise", "security"):
            self._install(tmp_path, pid, {"id": pid, "title": pid.title(), "version": "0.1.0"})
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0
        for pid in ("lean", "enterprise", "security"):
            assert pid in result.output

    def test_description_shown_when_present(self, tmp_path: Path):
        self._install(tmp_path, "lean", {
            "id": "lean", "title": "Lean", "version": "1.0.0",
            "description": "Simplified workflow for small teams",
        })
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert "Simplified workflow" in result.output


# ---------------------------------------------------------------------------
# PC3 — preset list: directory without manifest (graceful degradation)
# ---------------------------------------------------------------------------


class TestPc3PresetListMissingManifest:
    def test_dir_without_manifest_still_listed(self, tmp_path: Path):
        (tmp_path / ".map" / "presets" / "orphan").mkdir(parents=True)
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0
        assert "orphan" in result.output

    def test_dir_with_invalid_manifest_still_listed(self, tmp_path: Path):
        dest = tmp_path / ".map" / "presets" / "broken"
        dest.mkdir(parents=True)
        (dest / "manifest.json").write_text("not json {", encoding="utf-8")
        result = runner.invoke(app, ["preset", "list", str(tmp_path)])
        assert result.exit_code == 0
        assert "broken" in result.output


# ---------------------------------------------------------------------------
# PC4 — preset list --json
# ---------------------------------------------------------------------------


class TestPc4PresetListJson:
    def test_empty_returns_valid_json(self, tmp_path: Path):
        result = runner.invoke(app, ["preset", "list", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"presets": []}

    def test_installed_preset_appears_in_json(self, tmp_path: Path):
        dest = tmp_path / ".map" / "presets" / "lean"
        dest.mkdir(parents=True)
        (dest / "manifest.json").write_text(
            json.dumps({"id": "lean", "title": "Lean", "version": "1.2.3"}), encoding="utf-8"
        )
        result = runner.invoke(app, ["preset", "list", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["presets"]) == 1
        assert data["presets"][0]["id"] == "lean"
        assert data["presets"][0]["version"] == "1.2.3"

    def test_json_output_has_required_keys(self, tmp_path: Path):
        dest = tmp_path / ".map" / "presets" / "enterprise"
        dest.mkdir(parents=True)
        (dest / "manifest.json").write_text(
            json.dumps({"id": "enterprise", "title": "Enterprise", "version": "2.0.0",
                        "description": "Full gates"}), encoding="utf-8"
        )
        result = runner.invoke(app, ["preset", "list", str(tmp_path), "--json"])
        data = json.loads(result.output)
        preset = data["presets"][0]
        for key in ("id", "title", "version", "description"):
            assert key in preset, f"missing key: {key}"


# ---------------------------------------------------------------------------
# PC5 — preset add --from: valid install
# ---------------------------------------------------------------------------


class TestPc5PresetAddValid:
    def test_installs_to_correct_path(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        result = runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert result.exit_code == 0
        assert _installed_preset(project, "lean").is_dir()

    def test_manifest_copied_to_dest(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "sec", {"id": "sec", "title": "Security", "version": "0.5.0"})
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        manifest_path = _installed_preset(project, "sec") / "manifest.json"
        assert manifest_path.is_file()
        data = json.loads(manifest_path.read_text())
        assert data["id"] == "sec"

    def test_extra_files_copied(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        (src / "templates").mkdir()
        (src / "templates" / "custom.md").write_text("# Custom", encoding="utf-8")
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert (_installed_preset(project, "lean") / "templates" / "custom.md").is_file()

    def test_success_message_contains_preset_id(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        result = runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert "lean" in result.output

    def test_creates_presets_dir_if_absent(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        presets_root = project / ".map" / "presets"
        assert not presets_root.exists()
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert presets_root.is_dir()


# ---------------------------------------------------------------------------
# PC6 — preset add --from: invalid inputs
# ---------------------------------------------------------------------------


class TestPc6PresetAddInvalid:
    def test_nonexistent_source_exits_nonzero(self, tmp_path: Path):
        result = runner.invoke(app, ["preset", "add", "--from", "/no/such/path"])
        assert result.exit_code != 0

    def test_file_not_dir_source_exits_nonzero(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = runner.invoke(app, ["preset", "add", "--from", str(f)])
        assert result.exit_code != 0

    def test_missing_manifest_exits_nonzero(self, tmp_path: Path):
        src = tmp_path / "no_manifest"
        src.mkdir()
        result = runner.invoke(app, ["preset", "add", "--from", str(src)])
        assert result.exit_code != 0

    def test_invalid_json_manifest_exits_nonzero(self, tmp_path: Path):
        src = tmp_path / "bad_manifest"
        src.mkdir()
        (src / "manifest.json").write_text("not json", encoding="utf-8")
        result = runner.invoke(app, ["preset", "add", "--from", str(src)])
        assert result.exit_code != 0

    def test_missing_required_key_exits_nonzero(self, tmp_path: Path):
        src = _make_preset_dir(tmp_path, "x", {"id": "x", "title": "X"})
        result = runner.invoke(app, ["preset", "add", "--from", str(src)])
        assert result.exit_code != 0

    def test_invalid_preset_id_with_slash_exits_nonzero(self, tmp_path: Path):
        src = tmp_path / "bad_id"
        src.mkdir()
        (src / "manifest.json").write_text(
            json.dumps({"id": "a/b", "title": "Bad", "version": "1.0"}), encoding="utf-8"
        )
        result = runner.invoke(app, ["preset", "add", "--from", str(src)])
        assert result.exit_code != 0

    def test_invalid_preset_id_dotdot_exits_nonzero(self, tmp_path: Path):
        src = tmp_path / "dotdot"
        src.mkdir()
        (src / "manifest.json").write_text(
            json.dumps({"id": "..", "title": "Bad", "version": "1.0"}), encoding="utf-8"
        )
        result = runner.invoke(app, ["preset", "add", "--from", str(src)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# PC7 — preset add --force: overwrites existing preset
# ---------------------------------------------------------------------------


class TestPc7PresetAddForce:
    def test_force_overwrites_existing(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()

        src_v1 = _make_preset_dir(tmp_path, "lean_v1", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        runner.invoke(app, ["preset", "add", "--from", str(src_v1), str(project)])
        assert (_installed_preset(project, "lean") / "manifest.json").is_file()

        src_v2 = _make_preset_dir(tmp_path, "lean_v2", {"id": "lean", "title": "Lean", "version": "2.0.0"})
        result = runner.invoke(app, ["preset", "add", "--from", str(src_v2), str(project), "--force"])
        assert result.exit_code == 0

        data = json.loads((_installed_preset(project, "lean") / "manifest.json").read_text())
        assert data["version"] == "2.0.0"

    def test_force_with_nonexistent_preset_still_works(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        result = runner.invoke(app, ["preset", "add", "--from", str(src), str(project), "--force"])
        assert result.exit_code == 0
        assert _installed_preset(project, "lean").is_dir()


# ---------------------------------------------------------------------------
# PC8 — preset add: conflict without --force
# ---------------------------------------------------------------------------


class TestPc8PresetAddConflict:
    def test_duplicate_without_force_exits_nonzero(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        result = runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert result.exit_code != 0

    def test_duplicate_without_force_suggests_force(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        result = runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])
        assert "--force" in result.output or "force" in result.output.lower()

    def test_duplicate_does_not_corrupt_existing_preset(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        src = _make_preset_dir(tmp_path, "lean", {"id": "lean", "title": "Lean", "version": "1.0.0"})
        runner.invoke(app, ["preset", "add", "--from", str(src), str(project)])

        src2 = tmp_path / "_src2"
        src2.mkdir()
        (src2 / "manifest.json").write_text(
            json.dumps({"id": "lean", "title": "Lean", "version": "2.0.0"}), encoding="utf-8"
        )
        runner.invoke(app, ["preset", "add", "--from", str(src2), str(project)])
        data = json.loads((_installed_preset(project, "lean") / "manifest.json").read_text())
        assert data["version"] == "1.0.0"
