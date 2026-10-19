"""Contract tests for the review-pilot module's test-only accelerator."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from mapify_cli.skills_eval import review_corpus
from tests.review_pilot_git_cache import (
    REPO,
    historical_commands,
    historical_git_cache,
)


@pytest.mark.parametrize("payload", [b"historical bytes", b""])
def test_successes_including_empty_bytes_are_shared(payload: bytes) -> None:
    command = min(historical_commands())
    delegate = Mock(return_value=payload)
    with historical_git_cache(delegate) as cached:
        assert cached(REPO, *command) == payload
        assert cached(REPO / "tests/..", *command) == payload
    assert delegate.call_count == 1


def test_complete_argv_and_repository_do_not_alias(tmp_path: Path) -> None:
    first, second = sorted(historical_commands())[:2]
    delegate = Mock(side_effect=[b"first", b"second", b"other", b"other again"])
    with historical_git_cache(delegate) as cached:
        assert cached(REPO, *first) == b"first"
        assert cached(REPO, *second) == b"second"
        assert cached(REPO, *first) == b"first"
        assert cached(tmp_path, *first) == b"other"
        assert cached(tmp_path, *first) == b"other again"
    assert delegate.call_count == 4


def test_failure_is_retried_not_cached() -> None:
    command = min(historical_commands())
    delegate = Mock(side_effect=[ValueError("missing object"), b"recovered"])
    with historical_git_cache(delegate) as cached:
        with pytest.raises(ValueError, match="missing object"):
            cached(REPO, *command)
        assert cached(REPO, *command) == b"recovered"
        assert cached(REPO, *command) == b"recovered"
    assert delegate.call_count == 2


@pytest.mark.parametrize("command", [
    ("status", "--porcelain"),
    ("rev-parse", "HEAD"),
    ("cat-file", "blob", "HEAD:README.md"),
    ("cat-file", "blob", "0" * 40),
    ("show", "-s", "--format=%P", "main"),
    ("diff", "HEAD", "--", "README.md"),
    ("config", "--get", "core.bare"),
    (*min(historical_commands()), "--unknown-option"),
])
def test_unknown_mutable_or_unpinned_commands_bypass(command: tuple[str, ...]) -> None:
    delegate = Mock(side_effect=[b"old", b"new"])
    with historical_git_cache(delegate) as cached:
        assert cached(REPO, *command) == b"old"
        assert cached(REPO, *command) == b"new"
    assert delegate.call_count == 2


def test_teardown_restores_seam_and_discards_cache() -> None:
    original = review_corpus._git
    command = min(historical_commands())
    delegate = Mock(side_effect=[b"first module", b"next module"])
    with (
        pytest.raises(RuntimeError, match="test failed"),
        historical_git_cache(delegate) as cached,
        pytest.MonkeyPatch.context() as patch,
    ):
        patch.setattr(review_corpus, "_git", cached)
        assert review_corpus._git(REPO, *command) == b"first module"
        raise RuntimeError("test failed")
    assert review_corpus._git is original
    with historical_git_cache(delegate) as cached:
        assert cached(REPO, *command) == b"next module"
    assert delegate.call_count == 2
