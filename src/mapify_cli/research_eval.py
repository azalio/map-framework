"""Deterministic localization-quality scoring for research-agent output.

The research-agent is only useful when it returns compact, actionable
file/line evidence. This module intentionally has no provider dependency: tests
and maintainers can score saved ResearchEvidence JSON, or markdown-like text
with ``path:line[-end]`` citations, against known fixture targets.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_CITATION_RE = re.compile(
    r"""
    (?<![:\w])
    (?P<path>
        [\w./\-]+
        \.(?:py|md|sh|toml|yaml|yml|json|js|ts|go|rs|tsx|jsx)
    )
    :
    (?P<line>\d+)
    (?:-(?P<endline>\d+))?
    (?=[\s,.;)\]'`"]|$)
    """,
    re.VERBOSE | re.MULTILINE,
)

_SKIP_PREFIXES = ("http://", "https://", "/Users/", "/home/", "~/", "$HOME")


@dataclass(frozen=True)
class ResearchLocation:
    """A normalized inclusive repo-relative file range."""

    path: str
    start_line: int
    end_line: int

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True)
class MalformedLocation:
    raw: str
    reason: str


@dataclass(frozen=True)
class ParsedResearchLocations:
    locations: tuple[ResearchLocation, ...]
    duplicates: tuple[ResearchLocation, ...]
    malformed: tuple[MalformedLocation, ...]


@dataclass(frozen=True)
class MetricScore:
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class ResearchLocalizationScore:
    expected_count: int
    predicted_count: int
    exact_match_count: int
    partial_match_count: int
    duplicate_count: int
    malformed_count: int
    overbroad_count: int
    file_level: MetricScore
    line_level: MetricScore
    missing_locations: tuple[ResearchLocation, ...]
    extra_locations: tuple[ResearchLocation, ...]


def parse_research_locations(
    output: str,
    *,
    repo_root: Path | None = None,
) -> ParsedResearchLocations:
    """Parse research output into normalized file/range citations.

    Strict ResearchEvidence JSON with ``relevant_locations`` is preferred. If the
    output is not that JSON shape, the parser falls back to markdown/text
    ``path:line[-end]`` citations. Malformed citations are reported instead of
    raising so eval runs can score bad outputs deterministically.
    """

    candidates, malformed = _extract_candidates(output)
    locations: list[ResearchLocation] = []
    duplicates: list[ResearchLocation] = []
    seen: set[ResearchLocation] = set()

    for raw_path, start_line, end_line in candidates:
        location, error = _normalize_location(
            raw_path,
            start_line,
            end_line,
            repo_root=repo_root,
        )
        if error is not None:
            malformed.append(error)
            continue
        if location is None:
            malformed.append(
                MalformedLocation(raw=raw_path, reason="location normalization failed")
            )
            continue
        if location in seen:
            duplicates.append(location)
            continue
        seen.add(location)
        locations.append(location)

    return ParsedResearchLocations(
        locations=tuple(locations),
        duplicates=tuple(duplicates),
        malformed=tuple(malformed),
    )


def score_research_output(
    output: str,
    expected_locations: Sequence[ResearchLocation | Mapping[str, Any]],
    *,
    repo_root: Path | None = None,
    overbroad_line_threshold: int = 50,
) -> ResearchLocalizationScore:
    """Parse and score research output against expected target locations."""

    parsed = parse_research_locations(output, repo_root=repo_root)
    return score_research_locations(
        expected_locations,
        parsed.locations,
        duplicate_count=len(parsed.duplicates),
        malformed_count=len(parsed.malformed),
        overbroad_line_threshold=overbroad_line_threshold,
    )


def score_research_locations(
    expected_locations: Sequence[ResearchLocation | Mapping[str, Any]],
    predicted_locations: Sequence[ResearchLocation | Mapping[str, Any]],
    *,
    duplicate_count: int = 0,
    malformed_count: int = 0,
    overbroad_line_threshold: int = 50,
) -> ResearchLocalizationScore:
    """Score normalized predictions against expected repo locations."""

    expected = tuple(_coerce_location(location) for location in expected_locations)
    predicted = tuple(_coerce_location(location) for location in predicted_locations)

    expected_set = set(expected)
    predicted_set = set(predicted)
    exact_match_count = len(expected_set & predicted_set)

    missing: list[ResearchLocation] = []
    partial_match_count = 0
    for target in expected:
        if target in predicted_set:
            continue
        if any(_overlaps(target, candidate) for candidate in predicted):
            partial_match_count += 1
        else:
            missing.append(target)

    extra = tuple(
        candidate
        for candidate in predicted
        if not any(_overlaps(candidate, target) for target in expected)
    )
    overbroad_count = sum(
        1 for candidate in predicted if candidate.line_count > overbroad_line_threshold
    )

    file_level = _score_file_level(expected, predicted)
    line_level = _score_line_level(expected, predicted)

    return ResearchLocalizationScore(
        expected_count=len(expected),
        predicted_count=len(predicted),
        exact_match_count=exact_match_count,
        partial_match_count=partial_match_count,
        duplicate_count=duplicate_count,
        malformed_count=malformed_count,
        overbroad_count=overbroad_count,
        file_level=file_level,
        line_level=line_level,
        missing_locations=tuple(missing),
        extra_locations=extra,
    )


def load_expected_locations(path: Path) -> list[dict[str, Any]]:
    """Load expected research localization targets from a JSON file.

    Accepted shapes:
    - ``[{"path": "src/x.py", "lines": [1, 3]}]``
    - ``{"expected_locations": [{"path": "src/x.py", "lines": [1, 3]}]}``
    """

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected locations JSON is malformed: {exc.msg}") from exc

    if isinstance(raw, Mapping):
        raw = raw.get("expected_locations")
    if not isinstance(raw, list):
        raise ValueError("expected locations must be a list or expected_locations object")
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"expected_locations[{index}] must be an object")
    return raw


def score_to_dict(score: ResearchLocalizationScore) -> dict[str, Any]:
    return asdict(score)


def _extract_candidates(
    output: str,
) -> tuple[list[tuple[str, int, int]], list[MalformedLocation]]:
    stripped = output.strip()
    malformed: list[MalformedLocation] = []
    if not stripped:
        return [], [MalformedLocation(raw="", reason="output is empty")]

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, Mapping):
        raw_locations = parsed.get("relevant_locations")
        if isinstance(raw_locations, list):
            return _extract_json_candidates(raw_locations)
        malformed.append(
            MalformedLocation(
                raw="relevant_locations",
                reason="JSON output has no relevant_locations list",
            )
        )

    candidates: list[tuple[str, int, int]] = []
    for match in _CITATION_RE.finditer(output):
        start_line = int(match.group("line"))
        end_line = int(match.group("endline") or start_line)
        candidates.append((match.group("path"), start_line, end_line))
    return candidates, malformed


def _extract_json_candidates(
    raw_locations: Sequence[object],
) -> tuple[list[tuple[str, int, int]], list[MalformedLocation]]:
    candidates: list[tuple[str, int, int]] = []
    malformed: list[MalformedLocation] = []
    for index, raw_location in enumerate(raw_locations):
        prefix = f"relevant_locations[{index}]"
        if not isinstance(raw_location, Mapping):
            malformed.append(
                MalformedLocation(raw=prefix, reason="location must be an object")
            )
            continue

        path_value = raw_location.get("path")
        if not isinstance(path_value, str):
            malformed.append(
                MalformedLocation(raw=f"{prefix}.path", reason="path must be a string")
            )
            continue

        raw_lines = raw_location.get("lines", raw_location.get("line_range"))
        if _is_int_not_bool(raw_location.get("line")):
            line = int(raw_location["line"])
            candidates.append((path_value, line, line))
        elif (
            isinstance(raw_lines, list)
            and len(raw_lines) == 2
            and all(_is_int_not_bool(part) for part in raw_lines)
        ):
            candidates.append((path_value, int(raw_lines[0]), int(raw_lines[1])))
        else:
            malformed.append(
                MalformedLocation(
                    raw=f"{prefix}.lines",
                    reason="lines must be [start, end] positive integers",
                )
            )
    return candidates, malformed


def _normalize_location(
    raw_path: str,
    start_line: int,
    end_line: int,
    *,
    repo_root: Path | None,
) -> tuple[ResearchLocation | None, MalformedLocation | None]:
    path_text = raw_path.strip()
    if not path_text:
        return None, MalformedLocation(raw=raw_path, reason="path is empty")
    if any(path_text.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return None, MalformedLocation(raw=path_text, reason="path is outside repo")

    pure_path = PurePosixPath(path_text)
    if (
        pure_path.is_absolute()
        or path_text.startswith("~")
        or "\\" in path_text
        or any(part == ".." for part in pure_path.parts)
    ):
        return None, MalformedLocation(raw=path_text, reason="path is not safe relative")

    if start_line < 1 or end_line < start_line:
        return None, MalformedLocation(raw=path_text, reason="line range is invalid")

    normalized_path = "/".join(pure_path.parts)
    if repo_root is not None:
        target = repo_root / Path(*pure_path.parts)
        if not target.is_file():
            return None, MalformedLocation(raw=path_text, reason="file does not exist")
        try:
            line_count = len(target.read_text(encoding="utf-8").splitlines())
        except OSError as exc:
            return None, MalformedLocation(raw=path_text, reason=f"could not read file: {exc}")
        if end_line > line_count:
            return None, MalformedLocation(
                raw=f"{path_text}:{start_line}-{end_line}",
                reason=f"line range exceeds file length ({line_count})",
            )

    return ResearchLocation(normalized_path, start_line, end_line), None


def _coerce_location(location: ResearchLocation | Mapping[str, Any]) -> ResearchLocation:
    if isinstance(location, ResearchLocation):
        return location
    if not isinstance(location, Mapping):
        raise TypeError("location must be ResearchLocation or mapping")

    path = location.get("path")
    raw_lines = location.get("lines", location.get("line_range"))
    if _is_int_not_bool(location.get("line")):
        start_line = int(location["line"])
        end_line = start_line
    elif (
        isinstance(raw_lines, list)
        and len(raw_lines) == 2
        and all(_is_int_not_bool(part) for part in raw_lines)
    ):
        start_line = int(raw_lines[0])
        end_line = int(raw_lines[1])
    else:
        raise ValueError("location must include line or lines=[start, end]")

    if not isinstance(path, str):
        raise ValueError("location path must be a string")
    normalized, error = _normalize_location(
        path,
        start_line,
        end_line,
        repo_root=None,
    )
    if error is not None or normalized is None:
        reason = error.reason if error is not None else "invalid location"
        raise ValueError(reason)
    return normalized


def _score_file_level(
    expected: Sequence[ResearchLocation],
    predicted: Sequence[ResearchLocation],
) -> MetricScore:
    expected_files = {location.path for location in expected}
    predicted_files = {location.path for location in predicted}
    true_positive = len(expected_files & predicted_files)
    return _metric(
        true_positive=true_positive,
        predicted_total=len(predicted_files),
        expected_total=len(expected_files),
    )


def _score_line_level(
    expected: Sequence[ResearchLocation],
    predicted: Sequence[ResearchLocation],
) -> MetricScore:
    expected_ranges = _ranges_by_path(expected)
    predicted_ranges = _ranges_by_path(predicted)
    expected_total = sum(_range_length(ranges) for ranges in expected_ranges.values())
    predicted_total = sum(_range_length(ranges) for ranges in predicted_ranges.values())
    overlap = 0
    for path, ranges in predicted_ranges.items():
        overlap += _intersection_length(ranges, expected_ranges.get(path, ()))
    return _metric(
        true_positive=overlap,
        predicted_total=predicted_total,
        expected_total=expected_total,
    )


def _metric(
    *,
    true_positive: int,
    predicted_total: int,
    expected_total: int,
) -> MetricScore:
    if predicted_total == 0:
        precision = 1.0 if expected_total == 0 else 0.0
    else:
        precision = true_positive / predicted_total
    recall = 1.0 if expected_total == 0 else true_positive / expected_total
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return MetricScore(precision=precision, recall=recall, f1=f1)


def _ranges_by_path(
    locations: Sequence[ResearchLocation],
) -> dict[str, tuple[tuple[int, int], ...]]:
    grouped: dict[str, list[tuple[int, int]]] = {}
    for location in locations:
        grouped.setdefault(location.path, []).append(
            (location.start_line, location.end_line)
        )
    return {path: _merge_ranges(ranges) for path, ranges in grouped.items()}


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return tuple(merged)


def _range_length(ranges: Sequence[tuple[int, int]]) -> int:
    return sum(end - start + 1 for start, end in ranges)


def _intersection_length(
    left: Sequence[tuple[int, int]],
    right: Sequence[tuple[int, int]],
) -> int:
    total = 0
    for left_start, left_end in left:
        for right_start, right_end in right:
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            if start <= end:
                total += end - start + 1
    return total


def _overlaps(left: ResearchLocation, right: ResearchLocation) -> bool:
    return (
        left.path == right.path
        and left.start_line <= right.end_line
        and right.start_line <= left.end_line
    )


def _is_int_not_bool(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
