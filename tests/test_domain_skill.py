"""Tests for mapify domain-skill init command and domain skill scaffold generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.delivery.domain_skill import (
    _extract_key_dirs,
    _extract_project_name,
    _extract_readme_summary,
    _extract_safe_commands,
    _make_skill_name,
    _resolve_skill_name,
    create_domain_skill,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestExtractProjectName:
    def test_from_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-cool-lib"\n')
        assert _extract_project_name(tmp_path) == "my-cool-lib"

    def test_from_pyproject_toml_with_tool_section(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[tool.poetry]\nname = 'poetry-project'\n"
        )
        assert _extract_project_name(tmp_path) == "poetry-project"

    def test_from_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "my-app", "version": "1.0.0"}')
        assert _extract_project_name(tmp_path) == "my-app"

    def test_from_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module github.com/org/my-service\n\ngo 1.21\n")
        assert _extract_project_name(tmp_path) == "my-service"

    def test_from_go_mod_simple(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module my-service\n")
        assert _extract_project_name(tmp_path) == "my-service"

    def test_fallback_to_dir_name(self, tmp_path: Path) -> None:
        result = _extract_project_name(tmp_path)
        assert result == tmp_path.name

    def test_prefers_pyproject_over_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "pyproject-name"\n')
        (tmp_path / "package.json").write_text('{"name": "pkg-name"}')
        assert _extract_project_name(tmp_path) == "pyproject-name"

    def test_invalid_package_json_falls_through(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("not json {")
        result = _extract_project_name(tmp_path)
        assert result == tmp_path.name


class TestExtractReadmeSummary:
    def test_extracts_first_paragraph(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# Title\n\nThis is the summary line.\n\nMore text."
        )
        assert _extract_readme_summary(tmp_path) == "This is the summary line."

    def test_no_readme(self, tmp_path: Path) -> None:
        assert _extract_readme_summary(tmp_path) is None

    def test_skips_headings(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Title\n## Sub\nActual summary.\n")
        assert _extract_readme_summary(tmp_path) == "Actual summary."

    def test_skips_badges(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text(
            "# Title\n[![badge](url)]\n\nActual summary.\n"
        )
        result = _extract_readme_summary(tmp_path)
        assert result == "Actual summary."

    def test_truncates_long_line(self, tmp_path: Path) -> None:
        long_line = "A" * 300
        (tmp_path / "README.md").write_text(f"# T\n{long_line}\n")
        result = _extract_readme_summary(tmp_path)
        assert result is not None
        assert len(result) <= 200


class TestExtractKeyDirs:
    def test_finds_src_and_tests(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        dirs = _extract_key_dirs(tmp_path)
        assert "src" in dirs
        assert "tests" in dirs

    def test_empty_project(self, tmp_path: Path) -> None:
        dirs = _extract_key_dirs(tmp_path)
        assert dirs == []

    def test_ignores_non_candidate_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "node_modules").mkdir()
        (tmp_path / ".git").mkdir()
        dirs = _extract_key_dirs(tmp_path)
        assert "node_modules" not in dirs
        assert ".git" not in dirs

    def test_limits_to_five(self, tmp_path: Path) -> None:
        for d in ("src", "lib", "pkg", "cmd", "app", "api"):
            (tmp_path / d).mkdir()
        dirs = _extract_key_dirs(tmp_path)
        assert len(dirs) <= 5


class TestExtractSafeCommands:
    def test_from_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            "test:\n\tpytest\ncheck:\n\truff check .\nlint:\n\truff .\ndeploy:\n\t./deploy.sh\n"
        )
        cmds = _extract_safe_commands(tmp_path)
        assert "make test" in cmds
        assert "make check" in cmds
        assert "make lint" in cmds
        assert "make deploy" not in cmds

    def test_from_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest", "build": "tsc", "deploy": "aws s3 sync"}})
        )
        cmds = _extract_safe_commands(tmp_path)
        assert "npm run test" in cmds
        assert "npm run build" in cmds
        assert "npm run deploy" not in cmds

    def test_adds_pytest_for_python_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        cmds = _extract_safe_commands(tmp_path)
        assert "pytest tests/" in cmds

    def test_empty_project(self, tmp_path: Path) -> None:
        cmds = _extract_safe_commands(tmp_path)
        assert isinstance(cmds, list)

    def test_limits_output(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            "check:\n\t:\ntest:\n\t:\nlint:\n\t:\nbuild:\n\t:\nrun:\n\t:\nfmt:\n\t:\n"
        )
        cmds = _extract_safe_commands(tmp_path)
        assert len(cmds) <= 6


class TestMakeSkillName:
    def test_kebab_case(self) -> None:
        assert _make_skill_name("My Project") == "my-project"

    def test_already_valid(self) -> None:
        assert _make_skill_name("my-skill") == "my-skill"

    def test_special_chars_replaced(self) -> None:
        assert _make_skill_name("org/my.project_v2") == "org-my-project-v2"

    def test_consecutive_separators_collapsed(self) -> None:
        result = _make_skill_name("my  project")
        assert "--" not in result

    def test_empty_input_fallback(self) -> None:
        assert _make_skill_name("") == "project-domain"

    def test_only_special_chars_fallback(self) -> None:
        assert _make_skill_name("!!!") == "project-domain"


class TestResolveSkillName:
    def test_user_name_takes_precedence(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "ignored"\n')
        assert _resolve_skill_name("custom-name", tmp_path) == "custom-name"

    def test_derives_from_project_name(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-lib"\n')
        result = _resolve_skill_name(None, tmp_path)
        assert result == "my-lib-domain"


# ---------------------------------------------------------------------------
# Unit tests: create_domain_skill
# ---------------------------------------------------------------------------


class TestCreateDomainSkill:
    def test_creates_skill_file_in_empty_project(self, tmp_path: Path) -> None:
        skill_file, created = create_domain_skill(tmp_path)
        assert created is True
        assert skill_file.exists()
        assert skill_file.name == "SKILL.md"

    def test_skill_placed_in_claude_skills(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        assert skill_file.parent.parent.name == "skills"
        assert skill_file.parent.parent.parent.name == ".claude"

    def test_frontmatter_has_name_and_description(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert content.startswith("---")
        assert "\nname:" in content
        assert "\ndescription:" in content

    def test_frontmatter_has_do_not_use_trigger(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "Do NOT" in content

    def test_skips_existing_without_overwrite(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        skill_file.write_text("sentinel content")
        _, created = create_domain_skill(tmp_path)
        assert created is False
        assert skill_file.read_text() == "sentinel content"

    def test_overwrite_replaces_existing(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        skill_file.write_text("old content")
        skill_file2, created = create_domain_skill(tmp_path, overwrite=True)
        assert created is True
        assert skill_file2.read_text() != "old content"
        assert "\nname:" in skill_file2.read_text()

    def test_includes_readme_summary(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# P\n\nA great project.\n")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "p"\n')
        skill_file, _ = create_domain_skill(tmp_path)
        assert "A great project." in skill_file.read_text()

    def test_includes_key_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "src/" in content
        assert "tests/" in content

    def test_includes_safe_commands(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("test:\n\tpytest\ncheck:\n\truff .\n")
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "make test" in content or "make check" in content

    def test_custom_skill_name(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path, skill_name="my-custom-skill")
        assert skill_file.parent.name == "my-custom-skill"
        assert "name: my-custom-skill" in skill_file.read_text()

    def test_no_secret_values_emitted(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text().lower()
        # The warning is present but no real secret values are in the output
        for token in ("password=", "api_key=", "secret=", "token=abc"):
            assert token not in content

    def test_placeholder_when_no_readme(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "TODO" in content

    def test_no_fabricated_dir_entries(self, tmp_path: Path) -> None:
        # When no candidate dirs exist, no layout block is emitted
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "## Repo Layout" not in content

    def test_has_map_learn_difference_section(self, tmp_path: Path) -> None:
        skill_file, _ = create_domain_skill(tmp_path)
        content = skill_file.read_text()
        assert "/map-learn" in content

    def test_full_project_docs_present_path(self, tmp_path: Path) -> None:
        """Full path: pyproject + README + Makefile + src/tests dirs."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "fullproject"\n')
        (tmp_path / "README.md").write_text("# Full\n\nFull project description.\n")
        (tmp_path / "Makefile").write_text("test:\n\tpytest\ncheck:\n\truff .\n")
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()

        skill_file, created = create_domain_skill(tmp_path)
        assert created is True
        content = skill_file.read_text()
        assert "fullproject" in content
        assert "Full project description." in content
        assert "src/" in content
        assert "tests/" in content
        assert "make test" in content or "make check" in content
        assert "## Domain Glossary" in content
        assert "## Safety Boundaries" in content


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestDomainSkillCliCommand:
    def test_init_creates_skill_in_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["domain-skill", "init"])
        assert result.exit_code == 0, result.output
        assert "Created" in result.output
        skills_dir = tmp_path / ".claude" / "skills"
        assert skills_dir.exists()
        skill_dirs = list(skills_dir.iterdir())
        assert len(skill_dirs) == 1
        assert (skill_dirs[0] / "SKILL.md").exists()

    def test_init_with_explicit_path(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Created" in result.output

    def test_init_with_custom_name(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["domain-skill", "init", str(tmp_path), "--name", "my-domain"]
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".claude" / "skills" / "my-domain" / "SKILL.md").exists()

    def test_init_skips_existing_by_default(self, tmp_path: Path) -> None:
        runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        result = runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Skipped" in result.output

    def test_init_overwrite_replaces(self, tmp_path: Path) -> None:
        runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        result = runner.invoke(
            app, ["domain-skill", "init", str(tmp_path), "--overwrite"]
        )
        assert result.exit_code == 0, result.output
        assert "Created" in result.output

    def test_init_nonexistent_path_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["domain-skill", "init", str(tmp_path / "nonexistent")]
        )
        assert result.exit_code == 1

    def test_init_output_mentions_placeholders(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "placeholder" in result.output.lower() or "Edit" in result.output

    def test_init_warns_about_secrets(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "secret" in result.output.lower() or "token" in result.output.lower()

    def test_init_produces_valid_frontmatter(self, tmp_path: Path) -> None:
        runner.invoke(app, ["domain-skill", "init", str(tmp_path)])
        skill_files = list((tmp_path / ".claude" / "skills").glob("*/SKILL.md"))
        assert len(skill_files) == 1
        content = skill_files[0].read_text()
        assert content.startswith("---\n")
        # Must have closing frontmatter delimiter
        assert "\n---\n" in content
