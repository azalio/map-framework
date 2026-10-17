"""Public installed-skill invocation contract (#529)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.skill_ir import parse_skill_file
from mapify_cli.skills_eval.dispatcher import _apply_temp_flip


@pytest.mark.parametrize("surface", ["dev", "bundled", "installed"])
def test_only_release_blocks_model_invocation(surface: str, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    if surface == "installed":
        project = tmp_path / "project"
        result = CliRunner().invoke(
            app, ["init", str(project), "--no-git", "--mcp", "none"]
        )
        assert result.exit_code == 0, result.output
        skills = project / ".claude/skills"
    else:
        skills = root / (".claude/skills" if surface == "dev" else "src/mapify_cli/templates/skills")
    files = sorted(skills.glob("map-*/SKILL.md"))
    assert files
    irs = [parse_skill_file(path, provider="claude") for path in files]
    assert {ir.name for ir in irs if ir.frontmatter.get("disable-model-invocation")} == {"map-release"}
    assert {ir.name for ir in irs if ir.invocation_mode == "manual"} == {"map-release"}
    rules = json.loads((skills / "skill-rules.json").read_text())["skills"]
    for ir in irs:
        if rules[ir.name]["skillClass"] == "task":
            assert rules[ir.name]["enforcement"] == "manual"
            assert ir.frontmatter.get("argument-hint")
    upgrade = (skills / "map-upgrade/SKILL.md").read_text()
    assert "Only after explicit permission for that version" in upgrade
    assert "--approve-major <validated major.version>" in upgrade
    assert "Model invocation is not consent" in upgrade


def test_eval_flip_preserves_current_skills_and_supports_legacy(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/skills"
    before = {}
    for path in source.glob("map-*/SKILL.md"):
        if path.parent.name == "map-release":
            continue  # Release remains manual-only; eval may flip its throwaway copy.
        target = tmp_path / "skills" / path.parent.name / "SKILL.md"
        target.parent.mkdir(parents=True)
        before[target] = path.read_text()
        target.write_text(before[target])
    legacy = tmp_path / "skills/user-legacy/SKILL.md"
    legacy.parent.mkdir()
    legacy.write_text("---\nname: user-legacy\ndisable-model-invocation: true\n---\nBody\n")
    _apply_temp_flip(tmp_path)
    for path, content in before.items():
        assert path.read_text() == content
    assert "disable-model-invocation: false" in legacy.read_text()
    flipped = legacy.read_text()
    _apply_temp_flip(tmp_path)
    assert legacy.read_text() == flipped
