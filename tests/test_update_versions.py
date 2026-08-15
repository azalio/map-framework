"""Tests for stable MAP update target discovery."""

from __future__ import annotations

import httpx

from mapify_cli.update_versions import (
    MAX_RELEASE_BODY_CHARS,
    PYPI_URL,
    StableVersion,
    fetch_release_highlights,
    fetch_version_targets,
    targets_from_pypi,
)


def test_stable_version_accepts_only_three_numeric_components() -> None:
    assert StableVersion.parse("3.25.1") == StableVersion(3, 25, 1)
    assert StableVersion.parse("v3.25.1") is None
    assert StableVersion.parse("3.25") is None
    assert StableVersion.parse("3.25.1rc1") is None


def test_targets_select_same_major_and_newest_higher_major() -> None:
    payload = {
        "releases": {
            "3.25.1": [{"yanked": False}],
            "3.26.0": [{"yanked": False}],
            "4.0.0": [{"yanked": False}],
            "5.1.0": [{"yanked": False}],
            "5.2.0rc1": [{"yanked": False}],
        }
    }
    result = targets_from_pypi(payload, StableVersion(3, 25, 0))
    assert result.same_major == StableVersion(3, 26, 0)
    assert result.next_major == StableVersion(5, 1, 0)


def test_fully_yanked_release_is_excluded() -> None:
    payload = {
        "releases": {"3.26.0": [{"yanked": True}], "3.25.1": [{"yanked": False}]}
    }
    result = targets_from_pypi(payload, StableVersion(3, 25, 0))
    assert result.same_major == StableVersion(3, 25, 1)


def test_fetch_version_targets_uses_official_pypi_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PYPI_URL
        return httpx.Response(200, json={"releases": {"3.26.0": [{"yanked": False}]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        targets = fetch_version_targets(StableVersion(3, 25, 0), client=client)

    assert targets.same_major == StableVersion(3, 26, 0)
    assert targets.next_major is None


def test_release_highlights_are_bounded_and_require_official_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/releases/tags/v4.0.0")
        return httpx.Response(
            200,
            json={
                "name": "MAP 4",
                "body": "x" * 20_000,
                "html_url": "https://github.com/azalio/map-framework/releases/tag/v4.0.0",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        highlights = fetch_release_highlights(StableVersion(4, 0, 0), client=client)

    assert highlights is not None
    assert highlights.title == "MAP 4"
    assert len(highlights.body) == MAX_RELEASE_BODY_CHARS


def test_release_highlights_missing_body_returns_none() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"name": "MAP 4", "body": "", "html_url": "https://example.test"},
        )
    )
    with httpx.Client(transport=transport) as client:
        assert fetch_release_highlights(StableVersion(4, 0, 0), client=client) is None


def test_release_highlights_reject_unofficial_url() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "name": "MAP 4",
                "body": "New planning engine",
                "html_url": "https://example.test/releases/tag/v4.0.0",
            },
        )
    )
    with httpx.Client(transport=transport) as client:
        assert fetch_release_highlights(StableVersion(4, 0, 0), client=client) is None
