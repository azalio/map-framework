"""Tests for the shipped docs-vs-code drift pre-pass (.map/scripts/docs_drift.py, #671)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".map" / "scripts" / "docs_drift.py"
SHIPPED_COPIES = (
    SCRIPT,
    REPO_ROOT
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
    / "docs_drift.py",
)

CLI_SOURCE = """\
import argparse

def build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--verbose", action="store_true")
    return parser

def load_config(data: dict) -> dict:
    return {"cache_ttl": data.get("cache_ttl", 60)}
"""

DRIFTED_DOC = """\
# Tool

Run `src/missing_module.py` to start.
Pass `--retries` (default: 3) to control retries.
Use `--dry-run` to preview.
Set `legacy_mode` in the config to opt out.

```bash
tool --not-checked-inside-fences src/also_missing.py
```
"""

CLEAN_DOC = """\
# Clean

The entry point is `src/cli.py`; `load_config` reads `cache_ttl`.
Pass `--retries` (default: 5) or `--verbose`. See [the drifted doc](drifted.md).
Placeholders like `<path>`, globs like `*.py`, URLs like `https://x.y/a.py` are skipped.
`~/home.py` and plain words like `true` are not claims.
"""


@pytest.fixture(scope="module")
def drift() -> ModuleType:
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("docs_drift", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


def _repo(tmp_path: Path, docs: dict[str, str]) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "cli.py").write_text(CLI_SOURCE, encoding="utf-8")
    for rel, body in docs.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def _doc(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(d for d in result["docs"] if d["doc"] == name)


def test_shipped_copies_are_identical() -> None:
    assert all(p.is_file() for p in SHIPPED_COPIES), SHIPPED_COPIES
    assert len({p.read_bytes() for p in SHIPPED_COPIES}) == 1


def test_reports_missing_file_wrong_default_and_removed_key(
    drift: ModuleType, tmp_path: Path
) -> None:
    root = _repo(tmp_path, {"docs/drifted.md": DRIFTED_DOC})
    result = drift.run(root, [], tmp_path / "out", "2026-11-08")

    doc = _doc(result, "docs/drifted.md")
    by_kind = {f["kind"]: f for f in doc["findings"]}
    assert result["status"] == "drift"
    assert by_kind["missing_path"]["claim"] == "src/missing_module.py"
    assert by_kind["missing_path"]["line"] == 3
    assert by_kind["flag_default_mismatch"]["line"] == 4
    assert by_kind["flag_default_mismatch"]["source"] == "src/cli.py:5"
    assert "`3`" in by_kind["flag_default_mismatch"]["reason"]
    assert "`5`" in by_kind["flag_default_mismatch"]["reason"]
    assert by_kind["unknown_flag"]["claim"] == "--dry-run"
    assert by_kind["unknown_flag"]["line"] == 5
    assert by_kind["undefined_symbol"]["claim"] == "legacy_mode"
    assert by_kind["undefined_symbol"]["line"] == 6
    # Fenced code blocks are not claims.
    assert len(doc["findings"]) == 4

    markdown = (tmp_path / "out" / "2026-11-08.md").read_text(encoding="utf-8")
    assert "## docs/drifted.md" in markdown
    assert "`docs/drifted.md:3`" in markdown
    assert "`src/cli.py:5`" in markdown
    saved = json.loads(
        (tmp_path / "out" / "2026-11-08.json").read_text(encoding="utf-8")
    )
    assert saved["summary"] == {"docs": 1, "findings": 4}


def test_clean_doc_reports_no_drift_detected(drift: ModuleType, tmp_path: Path) -> None:
    root = _repo(tmp_path, {"README.md": CLEAN_DOC, "drifted.md": DRIFTED_DOC})
    result = drift.run(root, ["README.md"], tmp_path / "out", "2026-11-08")

    readme = _doc(result, "README.md")
    assert result["status"] == "clean"
    assert readme["findings"] == []
    assert readme["checked_claims"] >= 6
    markdown = (tmp_path / "out" / "2026-11-08.md").read_text(encoding="utf-8")
    assert "## README.md\n\nNo drift detected" in markdown


def test_drift_ignore_marker_and_broken_link(drift: ModuleType, tmp_path: Path) -> None:
    doc = (
        "See [gone](./gone.md) and [ok](other.md#part).\n"
        "Legacy `old_flag_name` <!-- drift-ignore -->\n"
        "<!-- drift-ignore -->\n"
        "Also `another_removed_key`.\n"
    )
    root = _repo(tmp_path, {"docs/a.md": doc, "docs/other.md": "x\n"})
    result = drift.run(root, ["docs/a.md"], None, "2026-11-08")

    findings = _doc(result, "docs/a.md")["findings"]
    assert [(f["kind"], f["claim"], f["line"]) for f in findings] == [
        ("missing_link", "./gone.md", 1)
    ]


def test_no_docs_is_a_noop(drift: ModuleType, tmp_path: Path) -> None:
    root = _repo(tmp_path, {})
    result = drift.run(root, [], tmp_path / "out", "2026-11-08")

    assert result["status"] == "no_docs"
    assert result["docs"] == []
    assert not (tmp_path / "out").exists()


def test_cli_writes_report_under_map_drift(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"README.md": DRIFTED_DOC})
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--repo-root",
            str(root),
            "--date",
            "2026-11-08",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "drift"
    assert (root / ".map" / "drift" / "2026-11-08.md").is_file()
    assert (root / ".map" / "drift" / "2026-11-08.json").is_file()
    # Read-only: the doc itself is untouched.
    assert (root / "README.md").read_text(encoding="utf-8") == DRIFTED_DOC


def test_cli_no_docs_exit_zero(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--repo-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "no_docs"
    assert not (tmp_path / ".map").exists()


def test_typer_defaults_none_skip_and_per_flag_window(
    drift: ModuleType, tmp_path: Path
) -> None:
    root = _repo(tmp_path, {})
    (root / "src" / "app.py").write_text(
        "import typer\n\n"
        "def main(\n"
        "    count: int = typer.Option(\n"
        "        5,\n"
        '        "--count",\n'
        "    ),\n"
        '    mode: str | None = typer.Option(None, "--mode"),\n'
        "):\n"
        "    pass\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "cli.md").write_text(
        "Use `--count` (default: `3`).\n"
        "Use `--mode` (default: `fast`).\n"
        "Use `--verbose` or `--retries` (default: 5).\n",
        encoding="utf-8",
    )
    result = drift.run(root, ["docs"], None, "2026-11-08")

    findings = _doc(result, "docs/cli.md")["findings"]
    assert [(f["kind"], f["line"], f["source"]) for f in findings] == [
        ("flag_default_mismatch", 1, "src/app.py:6")
    ]


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_mapify_init_installs_docs_drift_script(
    provider: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from mapify_cli import app

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["init", ".", "--provider", provider, "--no-git", "--force", "--mcp", "none"],
    )
    assert result.exit_code == 0, result.output
    installed = tmp_path / ".map" / "scripts" / "docs_drift.py"
    # The installer stamps a managed-file header; the body is the shipped script.
    assert "def check_doc(" in installed.read_text(encoding="utf-8")
    assert os.access(installed, os.X_OK)
    skill_root = (
        tmp_path / (".claude" if provider == "claude" else ".agents") / "skills"
    )
    skill = (skill_root / "map-check" / "SKILL.md").read_text(encoding="utf-8")
    assert "python3 .map/scripts/docs_drift.py" in skill
    assert "map-check --docs" in skill
