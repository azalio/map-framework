"""Public review bundles retain base evidence for shell-free attribution."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

SCRIPTS_PATH = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner  # type: ignore[import-not-found]


def test_read_only_review_bundle_preserves_pre_existing_defect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n")
    base_source = "def divide(value):\n    return 10 / value\n\nLABEL = 'old'\n"
    Path("calculator.py").write_text(base_source)
    git("add", ".")
    git("commit", "-m", "base with existing zero division")
    base = git("rev-parse", "HEAD")
    git("checkout", "-b", "feature")
    Path("calculator.py").write_text(base_source.replace("'old'", "'new'"))
    git("commit", "-am", "change display label only")
    runner = cast(Any, map_step_runner)
    admitted = runner.begin_review_run(scheduled_reviewers=["monitor"], branch="feature")
    assert admitted["status"] == "success"
    result = runner.create_review_bundle(branch="feature")
    assert result["status"] == "success"
    bundle = json.loads(Path(result["bundle_path_json"]).read_text())
    attribution = bundle["attribution"]
    assert attribution["base"] == base
    assert attribution["status"] == "available"
    source = next(item for item in attribution["files"] if item["path"] == "calculator.py")
    # Both complete function bodies prove unchanged behavior, not merely an old line.
    assert source["base_content"] == base_source
    assert source["current_content"] == base_source.replace("'old'", "'new'")
    assert any(
        item["base_start"] == 1 and item["current_start"] == 1 and item["length"] >= 2
        for item in source["line_mapping"]
    )
    assert "-LABEL = 'old'" in attribution["diff"]
    assert "+LABEL = 'new'" in attribution["diff"]
    # A shell-free reviewer consumes the persisted bundle, not git commands.
    prompts = runner.build_review_prompts(branch="feature")
    prompt = prompts["prompts"]["monitor"]["prompt"]
    assert "return 10 / value" in prompt
    assert "base_content" in prompt
    assert "line_mapping" in prompt


def test_create_review_bundle_preserves_committed_deleted_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n")
    base_source = "def divide(value):\n    return 10 / value\n\nLABEL = 'old'\n"
    Path("calculator.py").write_text(base_source)
    git("add", ".")
    git("commit", "-m", "base with calculator")
    git("checkout", "-b", "feature")
    git("rm", "calculator.py")
    git("commit", "-m", "remove calculator")
    runner = cast(Any, map_step_runner)
    admitted = runner.begin_review_run(scheduled_reviewers=["monitor"], branch="feature")
    assert admitted["status"] == "success"
    result = runner.create_review_bundle(branch="feature")
    assert result["status"] == "success"
    bundle = json.loads(Path(result["bundle_path_json"]).read_text())
    assert "calculator.py" not in bundle["snapshot"]["required_files"]
    sources = {item["path"]: item for item in bundle["attribution"]["files"]}
    assert "calculator.py" in sources
    assert sources["calculator.py"]["base_content"] == base_source
    assert sources["calculator.py"]["current_content"] == ""
    assert sources["calculator.py"]["status"] == "deleted"
    assert sources["calculator.py"]["line_mapping"] == []
