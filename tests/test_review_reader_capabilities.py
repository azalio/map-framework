"""Installed reviewer contracts; config checks are not runtime enforcement proof."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

import pytest
import yaml
from typer.testing import CliRunner

from mapify_cli import app
from mapify_cli.delivery.managed_file_copier import extract_metadata


@pytest.fixture(params=["claude", "codex"])
def installed_reader(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["init", ".", "--provider", request.param, "--no-git", "--force", "--mcp", "none"]
    )
    assert result.exit_code == 0, result.output
    return tmp_path, request.param


def test_installed_reader_capability_configuration(installed_reader):
    root, provider = installed_reader
    if provider == "claude":
        text = (root / ".claude/agents/review-reader.md").read_text()
        metadata = yaml.safe_load(text.split("---", 2)[1])
        assert metadata["name"] == "review-reader"
        assert set(metadata["tools"]) == {"Read", "Glob", "Grep"}
        assert metadata["mcpServers"] == []
        forbidden = {"Bash", "Write", "Edit", "Agent", "Task", "Skill", "WebFetch"}
        assert not forbidden.intersection(metadata["tools"])
        assert not (root / ".codex").exists()
    else:
        text = (root / ".codex/agents/review-reader.toml").read_text()
        profile = tomllib.loads(text)
        config = tomllib.loads((root / ".codex/config.toml").read_text())
        assert config["agents"]["review-reader"]["config_file"] == "agents/review-reader.toml"
        assert profile["sandbox_mode"] == "read-only"
        assert profile["features"]["shell_tool"] is False
        assert profile["features"]["multi_agent_v2"] is False
        assert profile["agents"]["enabled"] is False
        assert "unverified" in text and "INCOMPLETE" in text
        assert not (root / ".claude").exists()
    for field in ("covered_files", "skipped_files", "denied_access", "check_evidence"):
        assert field in text
    assert "self_reported" in text


def test_managed_refresh_restores_capabilities_and_preserves_user_tail(installed_reader):
    root, provider = installed_reader
    profile = root / (".claude/agents/review-reader.md" if provider == "claude"
                      else ".codex/agents/review-reader.toml")
    original = profile.read_text()
    tail = "\n# Local reviewer guidance: cite concrete source evidence.\n"
    stale = original.replace("  - Grep", "  - Bash") if provider == "claude" else original.replace(
        "shell_tool = false", "shell_tool = true"
    )
    assert stale != original
    profile.write_text(stale + tail)
    result = CliRunner().invoke(
        app, ["init", ".", "--provider", provider, "--no-git", "--force", "--mcp", "none"]
    )
    assert result.exit_code == 0, result.output
    refreshed = profile.read_text()
    assert refreshed.endswith(tail)
    if provider == "claude":
        metadata = yaml.safe_load(refreshed.split("---", 2)[1])
        assert set(metadata["tools"]) == {"Read", "Glob", "Grep"}
        assert metadata["mcpServers"] == []
    else:
        settings = tomllib.loads(refreshed)
        assert settings["features"]["shell_tool"] is False
        assert settings["features"]["multi_agent_v2"] is False
        assert settings["agents"]["enabled"] is False


def test_installed_check_supervisor_refresh_and_execution(installed_reader):
    root, provider = installed_reader
    helper = root / ".map/scripts/review_check_supervisor.py"
    assert helper.exists()
    original_metadata, original_payload = extract_metadata(helper.read_text(), ".py")
    assert original_metadata is not None
    assert original_metadata["generated_by"] == "mapify-cli"
    helper.write_text("# stale helper\n")
    refreshed = CliRunner().invoke(app, ["init", ".", "--provider", provider, "--no-git", "--force", "--mcp", "none"])
    assert refreshed.exit_code == 0, refreshed.output
    refreshed_metadata, refreshed_payload = extract_metadata(helper.read_text(), ".py")
    assert refreshed_metadata is not None
    assert refreshed_payload == original_payload
    for key in ("generated_by", "mapify_version", "template_hash"):
        assert refreshed_metadata[key] == original_metadata[key]
    assert refreshed_metadata["installed_at"]  # Refresh legitimately changes this timestamp.
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    (root / "writer.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "writer.py"], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    runner = [sys.executable, str(root / ".map/scripts/map_step_runner.py")]
    admission = subprocess.run([*runner, "begin_review_run", "--mode", "lightweight", "--required-check", "smoke",
                                "--check-specs-json", json.dumps({"smoke": [sys.executable, "-c", "print('ok')"]})],
                               capture_output=True, text=True, check=True)
    assert json.loads(admission.stdout)["status"] == "success", admission.stdout
    check = subprocess.run([*runner, "run_test_gate", "--check-id", "smoke"],
                           capture_output=True, text=True, check=True)
    assert json.loads(check.stdout)["passed"] is True, check.stdout


def test_all_installed_review_dispatches_use_reader(installed_reader):
    root, provider = installed_reader
    skill_root = root / (".claude/skills/map-review" if provider == "claude" else ".agents/skills/map-review")
    texts = [(skill_root / name).read_text() for name in ("SKILL.md", "adversarial-reference.md", "review-reference.md")]
    dispatches = re.findall(r'(?:subagent_type|agent_type)="([^"]+)"', "\n".join(texts))
    assert len(dispatches) >= 11
    assert set(dispatches) == {"review-reader"}
    skill = texts[0]
    assert f'"--provider", "{provider}", "--capability-profile", "review-reader"' in skill
    assert "run_test_gate" in skill
    assert "make -k test" not in skill
    assert "receipt" in skill and "self_reported" in skill
    if provider == "codex":
        assert "capability_enforcement=unverified" in skill
        assert "INCOMPLETE" in skill
        assert "finding publication" in skill


@pytest.mark.skipif(
    os.environ.get("MAP_LIVE_REVIEW_READER") != "1" or not shutil.which("claude"),
    reason="Explicit opt-in required for a live host/model capability probe",
)
def test_installed_claude_reader_host_inventory_and_discovery(tmp_path, monkeypatch):
    """Use the discovered installed profile, not a synthetic --agents definition."""
    monkeypatch.chdir(tmp_path)
    install = CliRunner().invoke(app, ["init", ".", "--no-git", "--force", "--mcp", "none"])
    assert install.exit_code == 0, install.output
    marker = tmp_path / "reader-probe.txt"
    marker.write_text("read-only discovery marker\n")
    result = subprocess.run(
        ["claude", "-p", "--permission-mode", "dontAsk",
         "--no-session-persistence", "--agent", "review-reader", "--verbose", "--output-format", "stream-json",
         "Read reader-probe.txt using Read. Report honestly whether shell, writes, delegation or MCP tools are available; do not modify files."],
        cwd=tmp_path, capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    init = next(event for event in events if event.get("type") == "system" and event.get("subtype") == "init")
    assert set(init["tools"]) == {"Read", "Glob", "Grep"}
    # Host MCP connections may exist; the exact tool allowlist denies invocation.
    uses = [block for event in events for block in event.get("message", {}).get("content", [])
            if isinstance(block, dict) and block.get("type") == "tool_use"]
    assert any(block["name"] == "Read" for block in uses)
    assert all(block["name"] in {"Read", "Glob", "Grep"} for block in uses)
    assert marker.read_text() == "read-only discovery marker\n"
