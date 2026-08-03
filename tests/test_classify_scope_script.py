"""Tests for the standalone .map/scripts/classify_scope.py script (#287).

The script is rendered from templates_src/map/scripts/classify_scope.py.jinja
and ships with 'mapify init' so it must work without importing mapify_cli.

Covers:
  SC1 — default thresholds (no config file) produce correct brackets
  SC2 — config file with dotted-key overrides is read correctly
  SC3 — boundary conditions (at-ceiling vs one-over)
  SC4 — auto_enabled flag respected from config
  SC5 — subprocess CLI invocation returns valid JSON (exit 0)
  SC6 — subprocess CLI rejects negative inputs (exit 1)
  SC7 — rendered script exists in all three output paths
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

# Locate the rendered script under the dev tree (.map/scripts/)
_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / ".map" / "scripts" / "classify_scope.py"


def _run(files: int, lines: int, project_dir: Path | None = None) -> dict:
    """Invoke the script as a subprocess and return parsed JSON."""
    cmd = [sys.executable, str(_SCRIPT), "--files", str(files), "--lines", str(lines)]
    if project_dir is not None:
        cmd += ["--project-dir", str(project_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"script failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# SC1 — default thresholds
# ---------------------------------------------------------------------------


class TestSc1DefaultThresholds:
    def test_zero_zero_is_trivial(self):
        result = _run(0, 0)
        assert result["bracket"] == "trivial"
        assert result["recommended_workflow"] == "map-fast"

    def test_trivial_at_ceiling(self):
        result = _run(3, 50)
        assert result["bracket"] == "trivial"

    def test_small_exceeds_trivial_files(self):
        result = _run(4, 10)
        assert result["bracket"] == "small"
        assert result["recommended_workflow"] == "map-plan-light"

    def test_small_at_ceiling(self):
        result = _run(10, 200)
        assert result["bracket"] == "small"

    def test_medium_exceeds_small_files(self):
        result = _run(11, 10)
        assert result["bracket"] == "medium"
        assert result["recommended_workflow"] == "map-efficient"

    def test_medium_at_ceiling(self):
        result = _run(30, 1000)
        assert result["bracket"] == "medium"

    def test_large_exceeds_medium(self):
        result = _run(31, 10)
        assert result["bracket"] == "large"
        assert result["recommended_workflow"] == "map-efficient+map-tdd"

    def test_large_lines_exceed_medium(self):
        result = _run(1, 1001)
        assert result["bracket"] == "large"


# ---------------------------------------------------------------------------
# SC2 — dotted-key config overrides
# ---------------------------------------------------------------------------


class TestSc2ConfigOverrides:
    def test_trivial_max_files_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_files: 1\n")
        assert _run(1, 10, tmp_path)["bracket"] == "trivial"
        assert _run(2, 10, tmp_path)["bracket"] == "small"

    def test_trivial_max_lines_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_lines: 20\n")
        assert _run(1, 20, tmp_path)["bracket"] == "trivial"
        assert _run(1, 21, tmp_path)["bracket"] == "small"

    def test_small_max_files_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.small.max_files: 5\n")
        assert _run(5, 10, tmp_path)["bracket"] == "small"
        assert _run(6, 10, tmp_path)["bracket"] == "medium"

    def test_medium_max_files_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.medium.max_files: 20\n")
        assert _run(20, 100, tmp_path)["bracket"] == "medium"
        assert _run(21, 100, tmp_path)["bracket"] == "large"

    def test_absent_config_uses_defaults(self, tmp_path: Path):
        result = _run(3, 50, tmp_path)
        assert result["bracket"] == "trivial"

    def test_multiple_overrides(self, tmp_path: Path):
        _write_config(
            tmp_path,
            "scale.thresholds.trivial.max_files: 2\n"
            "scale.thresholds.trivial.max_lines: 30\n"
        )
        assert _run(2, 30, tmp_path)["bracket"] == "trivial"
        assert _run(3, 30, tmp_path)["bracket"] == "small"
        assert _run(2, 31, tmp_path)["bracket"] == "small"


# ---------------------------------------------------------------------------
# SC3 — boundary conditions
# ---------------------------------------------------------------------------


class TestSc3BoundaryConditions:
    @pytest.mark.parametrize(
        "files, lines, expected",
        [
            (3, 50, "trivial"),
            (4, 50, "small"),
            (3, 51, "small"),
            (10, 200, "small"),
            (11, 200, "medium"),
            (10, 201, "medium"),
            (30, 1000, "medium"),
            (31, 1000, "large"),
            (30, 1001, "large"),
        ],
    )
    def test_boundary(self, files: int, lines: int, expected: str):
        assert _run(files, lines)["bracket"] == expected


# ---------------------------------------------------------------------------
# SC4 — auto_enabled flag
# ---------------------------------------------------------------------------


class TestSc4AutoEnabled:
    def test_auto_true_by_default(self):
        assert _run(1, 10)["auto_enabled"] is True

    def test_auto_false_from_config(self, tmp_path: Path):
        _write_config(tmp_path, "scale.auto: false\n")
        assert _run(1, 10, tmp_path)["auto_enabled"] is False

    def test_auto_true_explicit_in_config(self, tmp_path: Path):
        _write_config(tmp_path, "scale.auto: true\n")
        assert _run(1, 10, tmp_path)["auto_enabled"] is True


# ---------------------------------------------------------------------------
# SC5 — subprocess JSON output contract
# ---------------------------------------------------------------------------


class TestSc5JsonOutput:
    def test_required_fields_present(self):
        result = _run(5, 100)
        for key in ("bracket", "recommended_workflow", "estimated_files", "estimated_lines", "auto_enabled"):
            assert key in result, f"missing key: {key}"

    def test_estimated_fields_echo_inputs(self):
        result = _run(7, 123)
        assert result["estimated_files"] == 7
        assert result["estimated_lines"] == 123

    def test_recommended_workflow_nonempty_string(self):
        for files, lines in [(1, 10), (5, 100), (15, 400), (50, 2000)]:
            r = _run(files, lines)
            assert isinstance(r["recommended_workflow"], str) and r["recommended_workflow"]


# ---------------------------------------------------------------------------
# SC6 — invalid input rejected
# ---------------------------------------------------------------------------


class TestSc6InvalidInput:
    def test_negative_files_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--files", "-1", "--lines", "10"],
            capture_output=True, text=True,
            check=False,
        )
        assert proc.returncode != 0

    def test_negative_lines_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--files", "1", "--lines", "-1"],
            capture_output=True, text=True,
            check=False,
        )
        assert proc.returncode != 0

    def test_missing_files_arg_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--lines", "10"],
            capture_output=True, text=True,
            check=False,
        )
        assert proc.returncode != 0

    def test_missing_lines_arg_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--files", "5"],
            capture_output=True, text=True,
            check=False,
        )
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# SC7 — rendered script exists in all output paths
# ---------------------------------------------------------------------------


class TestSc7RenderedScriptExists:
    _EXPECTED_PATHS: ClassVar[list] = [
        _REPO_ROOT / ".map" / "scripts" / "classify_scope.py",
        _REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "classify_scope.py",
    ]

    @pytest.mark.parametrize("script_path", _EXPECTED_PATHS)
    def test_script_exists(self, script_path: Path):
        assert script_path.exists(), f"rendered script missing: {script_path}"

    def test_rendered_script_is_executable_python(self):
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--help"],
            capture_output=True, text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "--files" in proc.stdout or "--files" in proc.stderr


# ---------------------------------------------------------------------------
# SC8 — snake_case aliases accepted alongside dotted-key form
# ---------------------------------------------------------------------------


class TestSc8SnakeCaseAliases:
    """Config keys may be written as snake_case (scale_trivial_max_files) instead of
    the canonical dotted form (scale.thresholds.trivial.max_files); both must work."""

    def test_snake_trivial_max_files_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale_trivial_max_files: 1\n")
        assert _run(1, 10, tmp_path)["bracket"] == "trivial"
        assert _run(2, 10, tmp_path)["bracket"] == "small"

    def test_snake_trivial_max_lines_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale_trivial_max_lines: 20\n")
        assert _run(1, 20, tmp_path)["bracket"] == "trivial"
        assert _run(1, 21, tmp_path)["bracket"] == "small"

    def test_snake_small_max_files_override(self, tmp_path: Path):
        _write_config(tmp_path, "scale_small_max_files: 5\n")
        assert _run(5, 10, tmp_path)["bracket"] == "small"
        assert _run(6, 10, tmp_path)["bracket"] == "medium"

    def test_snake_auto_false(self, tmp_path: Path):
        _write_config(tmp_path, "scale_auto: false\n")
        assert _run(1, 10, tmp_path)["auto_enabled"] is False

    def test_dotted_takes_precedence_over_snake(self, tmp_path: Path):
        # Both forms present: dotted wins (written first, snake is not applied)
        _write_config(
            tmp_path,
            "scale.thresholds.trivial.max_files: 2\nscale_trivial_max_files: 10\n"
        )
        # With max_files=2 (from dotted), files=3 must be "small", not "trivial"
        assert _run(3, 10, tmp_path)["bracket"] == "small"


# ---------------------------------------------------------------------------
# SC9 — invalid config integer value falls back to default, does not crash
# ---------------------------------------------------------------------------


class TestSc9InvalidConfigValue:
    def test_non_integer_config_value_uses_default(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_files: many\n")
        # Must not crash; falls back to default (3), so 3 files → trivial
        result = _run(3, 10, tmp_path)
        assert result["bracket"] == "trivial"
        assert result["bracket"] in {"trivial", "small", "medium", "large"}

    def test_float_config_value_uses_default(self, tmp_path: Path):
        _write_config(tmp_path, "scale.thresholds.trivial.max_lines: 50.5\n")
        # int("50.5") raises ValueError; must fall back to default 50
        result = _run(3, 50, tmp_path)
        assert result["bracket"] == "trivial"
