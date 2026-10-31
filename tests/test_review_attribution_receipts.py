"""Public review bundles retain base evidence for shell-free attribution."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

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
    markdown = Path(result["bundle_path_md"]).read_text()
    assert '"diff":' not in markdown
    # A shell-free reviewer consumes the persisted bundle, not git commands.
    prompts = runner.build_review_prompts(branch="feature")
    prompt = prompts["prompts"]["monitor"]["prompt"]
    assert "return 10 / value" in prompt
    assert "base_content" in prompt
    assert "line_mapping" in prompt
    assert prompt.count("diff --git a/calculator.py b/calculator.py") == 1


def test_large_changed_files_keep_full_snapshot_without_bloating_prompts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n")
    large = "".join(f"LINE_{i:05d} = '{i:05d} unique source content'\n" for i in range(2500))
    for index in range(10):
        Path(f"file_{index}.py").write_text(large if index < 4 else f"VALUE = {index}\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    for index in range(10):
        path = Path(f"file_{index}.py")
        path.write_text(path.read_text().replace("LINE_00000", "LINE_00000_CHANGED") if index < 4
                        else f"VALUE = {index + 1}\n")
    git("commit", "-am", "change ten files")

    runner = cast(Any, map_step_runner)
    assert runner.begin_review_run(scheduled_reviewers=["monitor"], branch="feature")["status"] == "success"
    bundle = runner.create_review_bundle(branch="feature")
    source = json.loads(Path(bundle["bundle_path_json"]).read_text())["attribution"]["files"][0]
    assert source["base_content"] == large
    assert "LINE_00000_CHANGED" in source["current_content"]
    markdown = Path(bundle["bundle_path_md"]).read_text()
    assert '"full_source": "review-bundle.json attribution.files"' in markdown
    assert "LINE_02499" not in markdown
    prompts = runner.build_review_prompts(branch="feature")
    assert prompts["status"] == "success", prompts
    assert "LINE_00000_CHANGED" in prompts["prompts"]["monitor"]["prompt"]
    assert len(prompts["prompts"]["maintainer"]["prompt"].encode()) <= runner.REVIEW_PROMPT_MAX_BYTES
    adversarial = runner.build_adversarial_review_prompts(branch="feature", reviewers=["blind", "acceptance"])
    assert adversarial["status"] == "success", adversarial
    receipt = json.loads((tmp_path / ".map/feature/review-verdict-ledger.json").read_text())[
        "convergence"]["rounds"][-1]["bundle_receipt"]
    # Acceptance receives a parent-served source route without broader repository access.
    assert "Request parent-served source resources" in adversarial["prompts"]["acceptance"]["prompt"]
    assert receipt["artifact"] in adversarial["prompts"]["acceptance"]["prompt"]
    assert receipt["artifact"] not in adversarial["prompts"]["blind"]["prompt"]


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
    assert "calculator.py" in bundle["snapshot"]["required_files"]
    sources = {item["path"]: item for item in bundle["attribution"]["files"]}
    assert "calculator.py" in sources
    assert sources["calculator.py"]["base_content"] == base_source
    assert sources["calculator.py"]["current_content"] == ""
    assert sources["calculator.py"]["status"] == "deleted"
    assert sources["calculator.py"]["line_mapping"] == []


@pytest.mark.parametrize("rename", [False, True], ids=["deleted", "renamed"])
def test_review_receipt_requires_base_side_path(tmp_path, monkeypatch, rename):
    monkeypatch.chdir(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    Path(".gitignore").write_text(".map/\n")
    Path("guard.py").write_text("def authorize(user):\n    return user.is_admin\n")
    profile = Path(".claude/agents/review-reader.md")
    profile.parent.mkdir(parents=True)
    profile.write_text("---\nname: review-reader\ntools: Read, Glob, Grep\n---\nRead only.\n")
    git("add", ".")
    git("commit", "-m", "base with authorization guard")
    git("checkout", "-b", "feature")
    if rename:
        git("mv", "guard.py", "renamed_guard.py")
    else:
        git("rm", "guard.py")
    git("commit", "-m", "remove original guard path")
    runner = cast(Any, map_step_runner)
    admission = runner.begin_review_run(scheduled_reviewers=["monitor"], round_id="receipt",
                                        branch="feature", provider="claude")
    assert admission["status"] == "success"
    assert admission["capability"]["status"] == "verified"
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    receipt = {"covered_files": [name for name in admission["required_files"] if name != "guard.py"],
               "skipped_files": [], "denied_access": [], "check_evidence": []}
    envelope = {"verdict": "approved", "issues": [], "receipt": receipt}
    captured = runner.capture_review_output("monitor", json.dumps(envelope), "receipt", branch="feature")
    assert captured["status"] == "success"
    runner.write_review_verdict_ledger(current_run=True, branch="feature")
    ledger = json.loads(Path(".map/feature/review-verdict-ledger.json").read_text())
    assert ledger["completeness"]["status"] == "INCOMPLETE"
    assert ledger["code_approval"]["approved"] is False
    assert "guard.py" in admission["required_files"]
