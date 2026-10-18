"""Public install/repair coverage for the missing map-debug references (#505)."""

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

import mapify_cli
from mapify_cli import app
from mapify_cli.delivery.managed_file_copier import extract_metadata
from mapify_cli.install_manifest import read_manifest

REFERENCE_NAMES = {
    "map-output-examples.md",
    "map-xml-prompt-envelopes.md",
    "map-json-output-contracts.md",
}


def _debug_references(project: Path, root: str) -> list[Path]:
    skill = project / root / "skills/map-debug/SKILL.md"
    targets = re.findall(r"\]\((\.\./\.\./references/[^)#]+)", skill.read_text())
    assert {Path(target).name for target in targets} == REFERENCE_NAMES
    return sorted({(skill.parent / target).resolve() for target in targets})


@pytest.mark.parametrize("provider,root", [("claude", ".claude"), ("codex", ".agents")])
@pytest.mark.parametrize("legacy_missing", [False, True], ids=["fresh", "legacy-repair"])
def test_debug_reference_install_and_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    root: str,
    legacy_missing: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mapify_cli, "configure_global_permissions", Mock())
    clock = Mock(wraps=datetime)
    clock.now.return_value = datetime(2026, 10, 18, tzinfo=UTC)
    monkeypatch.setattr("mapify_cli.delivery.managed_file_copier.datetime", clock)
    runner = CliRunner()
    args = ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider]
    installed = runner.invoke(app, args)
    assert installed.exit_code == 0, installed.output
    references = _debug_references(tmp_path, root)
    originals = {
        path.name: extract_metadata(path.read_text(), ".md")[1] for path in references
    }
    reference_entries: dict[str, dict[str, object]] = {}
    reference_metadata: dict[str, dict[str, object]] = {}

    if legacy_missing:
        # Reproduce the reported 3.20.0 layout, not a fake missing package source:
        # the skill exists, but its shared references were never installed/owned.
        skill = tmp_path / root / "skills/map-debug/SKILL.md"
        skill.write_text(
            re.sub(r'"mapify_version":"[^"]+"', '"mapify_version":"3.20.0"', skill.read_text())
        )
        metadata, _ = extract_metadata(skill.read_text(), ".md")
        assert metadata is not None and metadata["mapify_version"] == "3.20.0"
        for path in references:
            path.unlink()
        manifest_path = tmp_path / ".map/mapify.lock.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["entries"] = [
            entry for entry in manifest["entries"]
            if entry["dest"] not in {str(path.relative_to(tmp_path)) for path in references}
        ]
        manifest_path.write_text(json.dumps(manifest))
        for path in _debug_references(tmp_path, root):
            with pytest.raises(FileNotFoundError):
                path.read_text()

    user_file = tmp_path / root / "references/team-notes.md"
    user_file.write_text("User-owned debugging notes.\n")
    user_bytes = user_file.read_bytes()
    for tick in (1, 2):
        clock.now.return_value = datetime(2026, 10, 18, tzinfo=UTC) + timedelta(seconds=tick)
        refreshed = runner.invoke(app, [*args, "--refresh-existing"])
        assert refreshed.exit_code == 0, refreshed.output
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        owned = {entry.dest: entry for entry in manifest.entries}
        for path in _debug_references(tmp_path, root):
            metadata, body = extract_metadata(path.read_text(), ".md")
            assert body == originals[path.name]
            assert metadata is not None
            # Refresh deliberately stamps every managed write, even without drift.
            expected_stamp = clock.now.return_value.strftime("%Y-%m-%dT%H:%M:%SZ")
            assert metadata.pop("installed_at") == expected_stamp
            entry = asdict(owned[path.relative_to(tmp_path).as_posix()])
            assert entry.pop("installed_at") == expected_stamp
            if path.name in reference_entries:
                assert entry == reference_entries[path.name]
                assert metadata == reference_metadata[path.name]
            reference_entries[path.name] = entry
            reference_metadata[path.name] = metadata
        assert user_file.read_bytes() == user_bytes
        assert user_file.relative_to(tmp_path).as_posix() not in owned
        assert not list((tmp_path / root / "references").glob("*.bak*"))

    if provider == "codex":
        assert not (tmp_path / ".claude").exists()
    else:
        assert not (tmp_path / ".agents").exists()
        assert not (tmp_path / ".codex").exists()
