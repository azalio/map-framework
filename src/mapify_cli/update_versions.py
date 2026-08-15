"""Discover strictly stable MAP update versions and official release metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import httpx

_STABLE_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

PYPI_URL = "https://pypi.org/pypi/mapify-cli/json"
GITHUB_RELEASE_URL = (
    "https://api.github.com/repos/azalio/map-framework/releases/tags/v{version}"
)
MAX_RELEASE_TITLE_CHARS = 200
MAX_RELEASE_BODY_CHARS = 6_000


@dataclass(frozen=True, order=True)
class StableVersion:
    """A strictly parsed ``MAJOR.MINOR.PATCH`` version."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> StableVersion | None:
        """Return a stable version only when *value* has exactly three numeric parts."""
        match = _STABLE_RE.fullmatch(value)
        if match is None:
            return None
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class VersionTargets:
    """The newest applicable stable release in each update policy tier."""

    same_major: StableVersion | None
    next_major: StableVersion | None


@dataclass(frozen=True)
class ReleaseHighlights:
    """Bounded release notes from MAP's official GitHub release page."""

    version: StableVersion
    title: str
    body: str
    url: str


def targets_from_pypi(
    payload: Mapping[str, object], current: StableVersion
) -> VersionTargets:
    """Select eligible stable targets from a PyPI JSON payload.

    A release is eligible only when it has at least one non-yanked mapping in a
    non-empty file list.  Versions at or below ``current`` are not targets.
    """
    releases = payload.get("releases")
    if not isinstance(releases, Mapping):
        return VersionTargets(same_major=None, next_major=None)

    candidates: list[StableVersion] = []
    for release_name, files in releases.items():
        if not isinstance(release_name, str) or not isinstance(files, list) or not files:
            continue
        version = StableVersion.parse(release_name)
        if version is None or version <= current:
            continue
        if any(isinstance(file, Mapping) and file.get("yanked") is not True for file in files):
            candidates.append(version)

    same_major = [version for version in candidates if version.major == current.major]
    higher_major = [version for version in candidates if version.major > current.major]
    return VersionTargets(
        same_major=max(same_major, default=None),
        next_major=max(higher_major, default=None),
    )


def fetch_version_targets(current: StableVersion, client: httpx.Client) -> VersionTargets:
    """Fetch stable update targets from the official mapify-cli PyPI endpoint."""
    response = client.get(PYPI_URL, timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ValueError("PyPI metadata must be a JSON object")
    return targets_from_pypi(cast(Mapping[str, object], payload), current)


def fetch_release_highlights(
    version: StableVersion, client: httpx.Client
) -> ReleaseHighlights | None:
    """Fetch bounded release highlights for an official GitHub MAP release."""
    response = client.get(GITHUB_RELEASE_URL.format(version=version), timeout=5.0)
    if response.status_code == 404:
        return None
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, Mapping):
        return None

    title = payload.get("name")
    body = payload.get("body")
    url = payload.get("html_url")
    expected_url = f"https://github.com/azalio/map-framework/releases/tag/v{version}"
    if (
        not isinstance(title, str)
        or not title
        or not isinstance(body, str)
        or not body
        or not isinstance(url, str)
        or url != expected_url
    ):
        return None

    return ReleaseHighlights(
        version=version,
        title=title[:MAX_RELEASE_TITLE_CHARS],
        body=body[:MAX_RELEASE_BODY_CHARS],
        url=url,
    )
