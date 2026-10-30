"""Installed runtime privacy boundaries, exercised with Git's actual matcher."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.delivery.file_copier import merge_update_runtime_gitignore


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("existing_install", [False, True])
def test_init_keeps_session_data_and_bytecode_out_of_index(
    tmp_path: Path,
    provider: str,
    existing_install: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True)

    git("init", "-q")
    if existing_install:
        (tmp_path / ".gitignore").write_text(
            "# map:update-runtime — local MAP runtime state; never commit.\n"
            ".map/update-state.json\n.map/update.lock\ncustom-cache/\n"
        )
    result = CliRunner().invoke(
        app,
        [
            "init",
            ".",
            "--force",
            "--no-git",
            "--mcp",
            "none",
            "--provider",
            provider,
        ],
    )
    assert result.exit_code == 0, result.output

    private = [
        ".map/main/sessions/scratch/example.jsonl",
        ".map/feat-example/sessions/scratch/example.offset",
        ".map/feat-example/sessions/current-session",
        ".map/feat-example/sessions/2026-10-30-summary.md",
        ".map/scripts/__pycache__/map_utils.cpython-312.pyc",
        ".claude/hooks/__pycache__/helper.cpython-312.pyc",
        "src/__pycache__/module.cpython-312.pyc",
    ]
    shareable = [
        ".map/feat-example/blueprint.json",
        ".map/feat-example/spec.md",
        "src/module.py",
    ]
    for name in private + shareable:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture\n")

    git("add", "-A")
    staged = set(git("ls-files").splitlines())
    assert not staged.intersection(private)
    assert set(shareable) <= staged
    assert merge_update_runtime_gitignore(tmp_path) == 0
    if existing_install:
        assert "custom-cache/" in (tmp_path / ".gitignore").read_text()
