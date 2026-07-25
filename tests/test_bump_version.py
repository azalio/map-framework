"""Regression tests for the release version bump script."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUMP_SCRIPT = ROOT / "scripts" / "bump-version.sh"


def run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )


def make_release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    scripts_dir = repo / "scripts"
    package_dir = repo / "src" / "mapify_cli"
    scripts_dir.mkdir(parents=True)
    package_dir.mkdir(parents=True)

    script_copy = scripts_dir / "bump-version.sh"
    shutil.copy2(BUMP_SCRIPT, script_copy)
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IXUSR)

    (repo / "pyproject.toml").write_text(
        '[project]\nname = "mapify-cli"\nversion = "1.1.0"\n',
        encoding="utf-8",
    )
    (package_dir / "__init__.py").write_text(
        '__version__ = "1.1.0"\n',
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n"
        "- Added feature A.\n\n"
        "### Fixed\n"
        "- Fixed bug B.\n\n"
        "## [1.1.0] - 2026-06-01\n\n"
        "### Fixed\n"
        "- Previous release.\n",
        encoding="utf-8",
    )

    run(["git", "init"], cwd=repo)
    run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    run(["git", "config", "user.name", "Test User"], cwd=repo)
    run(["git", "add", "."], cwd=repo)
    run(["git", "commit", "-m", "initial release state"], cwd=repo)
    return repo


def test_bump_version_tag_annotation_uses_versioned_changelog(tmp_path: Path) -> None:
    repo = make_release_repo(tmp_path)

    result = run(
        [str(repo / "scripts" / "bump-version.sh"), "1.2.0"],
        cwd=repo,
        input_text="y",
    )

    output = result.stdout + result.stderr
    assert "No content found in [Unreleased] section" not in output

    tag = run(["git", "tag", "-l", "-n50", "v1.2.0"], cwd=repo).stdout
    assert "Added feature A." in tag
    assert "Fixed bug B." in tag
    assert "Release version 1.2.0" not in tag
