"""The default project settings leave file access policy to the host and project."""

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("settings", [".claude/settings.json", "src/mapify_cli/templates/settings.json"])
def test_no_filename_deny_rules(settings):
    root = Path(__file__).resolve().parents[1]
    rules = json.loads((root / settings).read_text())["permissions"]["deny"]
    assert not any(rule.startswith(("Read(", "Edit(", "Write(", "MultiEdit(")) for rule in rules)
