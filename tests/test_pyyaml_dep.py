"""Regression tests for #245: PyYAML must be a hard runtime dependency.

`mapify` is a config-driven CLI: ``project_config.load_map_config`` parses
``.map/config.yaml`` via PyYAML on every config-dependent path. If PyYAML is
declared only in the ``test``/``dev`` optional groups (as it was before #245),
a normal install (``uv tool install`` / ``pipx`` / ``pip install mapify-cli``
without extras) ships without yaml, hits ``ImportError``, and silently falls
back to default config — the user's ``.map/config.yaml`` is ignored.

CI never caught this because the dev/test groups *do* include pyyaml, so the
guarding test here asserts on the declared dependency table, not on the import.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import yaml

from mapify_cli.config.project_config import load_map_config

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _runtime_dependencies() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def test_pyyaml_is_a_runtime_dependency() -> None:
    """pyyaml must be in [project].dependencies, not only the dev/test extras.

    Fails before #245 (pyyaml only in optional-dependencies); passes after.
    """
    runtime = _runtime_dependencies()
    assert any(
        req.lower().replace("_", "-").startswith("pyyaml") for req in runtime
    ), (
        "pyyaml missing from [project].dependencies — a normal install would "
        f"ship without PyYAML and silently ignore .map/config.yaml (#245). "
        f"Declared runtime deps: {runtime}"
    )


def test_pyyaml_importable_and_version_floor() -> None:
    """PyYAML is installed and meets the >=6.0 floor declared in pyproject."""
    assert tuple(int(x) for x in yaml.__version__.split(".")[:2]) >= (6, 0)


def test_load_map_config_reads_non_default_value(tmp_path: Path) -> None:
    """With PyYAML present, a non-default config value is actually loaded.

    This is the behavioral half of #245: proves the config-driven CLI path
    reads ``.map/config.yaml`` instead of degrading to defaults. The default
    profile is ``full``; assert an explicit override round-trips.
    """
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    (map_dir / "config.yaml").write_text(
        "profile: core\nminimality: full\n", encoding="utf-8"
    )

    cfg = load_map_config(tmp_path)

    assert cfg.profile == "core"
    assert cfg.minimality == "full"


def test_load_map_config_falls_back_when_yaml_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """The ImportError fallback path is intact: yaml=None -> defaults.

    Simulates the broken-install state (no PyYAML) to lock in the documented
    degradation: a missing yaml module yields defaults rather than crashing.
    This guards the warn-and-default branch the runtime dep is meant to avoid
    in production.
    """
    map_dir = tmp_path / ".map"
    map_dir.mkdir()
    (map_dir / "config.yaml").write_text("profile: core\n", encoding="utf-8")

    monkeypatch.setattr("mapify_cli.config.project_config.yaml", None)

    cfg = load_map_config(tmp_path)

    # yaml unavailable -> default profile, config silently ignored
    assert cfg.profile == "full"


if __name__ == "__main__":  # pragma: no cover - manual debugging convenience
    sys.exit(__import__("pytest").main([__file__, "-v"]))
