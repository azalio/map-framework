"""Smoke test: jinja2 runtime dependency is installed and meets the version floor."""

import jinja2


def test_jinja2_importable_and_version_floor() -> None:
    assert tuple(int(x) for x in jinja2.__version__.split(".")[:2]) >= (3, 1)
