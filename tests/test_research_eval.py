from __future__ import annotations

import json
from pathlib import Path

import pytest

from mapify_cli.research_eval import (
    ResearchLocation,
    parse_research_locations,
    score_research_output,
)


def _write_file(repo: Path, path: str, line_count: int = 80) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(f"line {index}\n" for index in range(1, line_count + 1)),
        encoding="utf-8",
    )


def _research_json(*locations: dict[str, object]) -> str:
    return json.dumps(
        {
            "status": "OK",
            "confidence": 0.9,
            "search_stats": {
                "files_scanned": 1,
                "total_matches_found": len(locations),
                "results_truncated": False,
            },
            "relevant_locations": list(locations),
        }
    )


def test_scores_exact_json_research_locations(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py")
    output = _research_json(
        {
            "path": "src/service.py",
            "lines": [2, 3],
            "relevance": "Primary implementation.",
        }
    )

    score = score_research_output(
        output,
        [ResearchLocation("src/service.py", 2, 3)],
        repo_root=tmp_path,
    )

    assert score.expected_count == 1
    assert score.predicted_count == 1
    assert score.exact_match_count == 1
    assert score.file_level.precision == 1.0
    assert score.file_level.recall == 1.0
    assert score.line_level.f1 == 1.0
    assert score.malformed_count == 0


def test_scores_partial_line_overlap(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py")
    output = _research_json(
        {
            "path": "src/service.py",
            "lines": [2, 4],
            "relevance": "Near the expected implementation.",
        }
    )

    score = score_research_output(
        output,
        [ResearchLocation("src/service.py", 3, 5)],
        repo_root=tmp_path,
    )

    assert score.exact_match_count == 0
    assert score.partial_match_count == 1
    assert score.line_level.precision == pytest.approx(2 / 3)
    assert score.line_level.recall == pytest.approx(2 / 3)


def test_scores_missing_expected_location(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py")
    output = _research_json()

    score = score_research_output(
        output,
        [ResearchLocation("src/service.py", 10, 12)],
        repo_root=tmp_path,
    )

    assert score.predicted_count == 0
    assert score.file_level.recall == 0.0
    assert score.line_level.recall == 0.0
    assert score.missing_locations == (ResearchLocation("src/service.py", 10, 12),)


def test_penalizes_over_broad_text_citation(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py")

    score = score_research_output(
        "The important code is src/service.py:1-60.",
        [ResearchLocation("src/service.py", 20, 22)],
        repo_root=tmp_path,
        overbroad_line_threshold=20,
    )

    assert score.file_level.precision == 1.0
    assert score.file_level.recall == 1.0
    assert score.line_level.precision == pytest.approx(3 / 60)
    assert score.line_level.recall == 1.0
    assert score.overbroad_count == 1


def test_deduplicates_repeated_text_citations(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py")

    parsed = parse_research_locations(
        "src/service.py:10-12 and again src/service.py:10-12",
        repo_root=tmp_path,
    )
    score = score_research_output(
        "src/service.py:10-12 and again src/service.py:10-12",
        [ResearchLocation("src/service.py", 10, 12)],
        repo_root=tmp_path,
    )

    assert parsed.locations == (ResearchLocation("src/service.py", 10, 12),)
    assert parsed.duplicates == (ResearchLocation("src/service.py", 10, 12),)
    assert score.predicted_count == 1
    assert score.duplicate_count == 1
    assert score.line_level.f1 == 1.0


def test_reports_malformed_paths_and_ranges(tmp_path: Path) -> None:
    _write_file(tmp_path, "src/service.py", line_count=5)
    output = _research_json(
        {"path": "../secret.py", "lines": [1, 1], "relevance": "unsafe"},
        {"path": "src/missing.py", "lines": [1, 1], "relevance": "absent"},
        {"path": "src/service.py", "lines": [8, 9], "relevance": "stale"},
    )

    score = score_research_output(
        output,
        [ResearchLocation("src/service.py", 1, 1)],
        repo_root=tmp_path,
    )
    parsed = parse_research_locations(output, repo_root=tmp_path)

    assert score.predicted_count == 0
    assert score.malformed_count == 3
    assert score.file_level.recall == 0.0
    assert {item.reason for item in parsed.malformed} == {
        "path is not safe relative",
        "file does not exist",
        "line range exceeds file length (5)",
    }
