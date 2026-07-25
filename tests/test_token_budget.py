"""Tests for src/mapify_cli/token_budget.py."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from mapify_cli.token_budget import (
    AGGRESSIVE_MULTIPLIER,
    TokenUsage,
    count_last_turn_tokens,
    effective_threshold,
    estimate_tokens,
    format_compact_instruction,
    should_nudge,
    truncate_to_token_budget,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write the given dicts as a JSONL file and return the path."""
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return path


def _assistant_entry(
    *,
    input_tokens: int = 0,
    cache_read: int = 0,
    cache_create: int = 0,
    output_tokens: int = 0,
    text: str = "ok",
) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_create,
                "output_tokens": output_tokens,
            },
        },
    }


def _user_entry(text: str = "hi") -> dict:
    return {
        "type": "human",
        "message": {"role": "user", "content": text},
    }


# ---------------------------------------------------------------------------
# count_last_turn_tokens
# ---------------------------------------------------------------------------


class TestCountLastTurnTokens:
    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        assert count_last_turn_tokens(tmp_path / "nope.jsonl") == 0

    def test_empty_file_returns_zero(self, tmp_path: Path) -> None:
        f = tmp_path / "t.jsonl"
        f.write_text("", encoding="utf-8")
        assert count_last_turn_tokens(f) == 0

    def test_only_user_entries_returns_zero(self, tmp_path: Path) -> None:
        f = _write_jsonl(
            tmp_path / "t.jsonl",
            [_user_entry("hi"), _user_entry("again")],
        )
        assert count_last_turn_tokens(f) == 0

    def test_single_assistant_sums_three_fields(self, tmp_path: Path) -> None:
        f = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _user_entry(),
                _assistant_entry(
                    input_tokens=1000, cache_read=500, cache_create=200
                ),
            ],
        )
        # output_tokens is intentionally not part of the next-turn input cost.
        assert count_last_turn_tokens(f) == 1700

    def test_picks_most_recent_assistant(self, tmp_path: Path) -> None:
        f = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _user_entry(),
                _assistant_entry(input_tokens=100),
                _user_entry(),
                _assistant_entry(input_tokens=50_000, cache_read=20_000),
                _user_entry("most recent user"),
            ],
        )
        # Last assistant is the second one with 50k+20k=70k.
        assert count_last_turn_tokens(f) == 70_000

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "t.jsonl"
        f.write_text(
            json.dumps(_assistant_entry(input_tokens=42))
            + "\n"
            + "this is not json\n"
            + "{}\n"  # empty dict, no usage
            + "\n",
            encoding="utf-8",
        )
        # Walking from the end: skip blank, skip {}, skip non-JSON, hit assistant.
        assert count_last_turn_tokens(f) == 42

    def test_assistant_without_usage_falls_back(self, tmp_path: Path) -> None:
        # If the latest assistant entry lacks usage, walk further back.
        no_usage = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "no usage"}],
            },
        }
        f = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_entry(input_tokens=999),
                _user_entry(),
                no_usage,
            ],
        )
        assert count_last_turn_tokens(f) == 999

    def test_string_usage_values_are_coerced(self, tmp_path: Path) -> None:
        # Defensive: some stored transcripts have ints serialised as strings.
        entry = _assistant_entry(input_tokens=10)
        entry["message"]["usage"]["input_tokens"] = "10"
        entry["message"]["usage"]["cache_read_input_tokens"] = "5"
        f = _write_jsonl(tmp_path / "t.jsonl", [entry])
        assert count_last_turn_tokens(f) == 15

    def test_no_usage_anywhere_returns_zero(self, tmp_path: Path) -> None:
        no_usage = {
            "type": "assistant",
            "message": {"role": "assistant", "content": "x"},
        }
        f = _write_jsonl(tmp_path / "t.jsonl", [no_usage, no_usage])
        assert count_last_turn_tokens(f) == 0


class TestPromptTokenEstimates:
    def test_estimate_tokens_uses_deterministic_ceiling(self) -> None:
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcde") == 2

    def test_truncate_to_token_budget_preserves_estimated_budget(self) -> None:
        result = truncate_to_token_budget("alpha beta gamma delta epsilon", 4)

        assert result.endswith("...")
        assert estimate_tokens(result) <= 4

    def test_truncate_to_zero_budget_returns_empty(self) -> None:
        assert truncate_to_token_budget("alpha", 0) == ""


# ---------------------------------------------------------------------------
# effective_threshold
# ---------------------------------------------------------------------------


class TestEffectiveThreshold:
    def test_never_returns_none(self) -> None:
        assert effective_threshold("never", 120_000) is None

    def test_auto_returns_threshold(self) -> None:
        assert effective_threshold("auto", 120_000) == 120_000

    def test_aggressive_applies_multiplier(self) -> None:
        # 120_000 * 0.4 == 48_000, exact integer.
        assert effective_threshold("aggressive", 120_000) == int(
            120_000 * AGGRESSIVE_MULTIPLIER
        )
        assert effective_threshold("aggressive", 120_000) == 48_000

    def test_unknown_policy_treated_as_auto(self) -> None:
        # Misconfiguration should not silently disable the nudge for non-empty
        # threshold; behave like 'auto'. (See module docstring rationale.)
        assert effective_threshold("paranoid", 100_000) == 100_000

    def test_zero_threshold_disables_nudge(self) -> None:
        assert effective_threshold("auto", 0) is None
        assert effective_threshold("aggressive", 0) is None

    def test_negative_threshold_disables_nudge(self) -> None:
        assert effective_threshold("auto", -1) is None


# ---------------------------------------------------------------------------
# should_nudge
# ---------------------------------------------------------------------------


class TestShouldNudge:
    def test_none_threshold_never_nudges(self) -> None:
        assert should_nudge(10**9, None) is False

    def test_below_threshold(self) -> None:
        assert should_nudge(99_999, 100_000) is False

    def test_at_threshold_triggers(self) -> None:
        # Boundary equality should fire — "we have hit the limit".
        assert should_nudge(100_000, 100_000) is True

    def test_above_threshold(self) -> None:
        assert should_nudge(150_000, 100_000) is True


# ---------------------------------------------------------------------------
# format_compact_instruction
# ---------------------------------------------------------------------------


class TestFormatCompactInstruction:
    def test_contains_used_threshold_and_focus(self) -> None:
        msg = format_compact_instruction(
            used=120_000,
            threshold=120_000,
            focus="MAP step state, monitor verdicts",
        )
        assert "120,000" in msg  # thousands separator for readability
        assert "100%" in msg
        assert "/compact MAP step state, monitor verdicts" in msg
        assert msg.startswith("[MAP context-meter]")

    def test_blank_focus_falls_back_to_default(self) -> None:
        msg = format_compact_instruction(used=130_000, threshold=120_000, focus="")
        # Default focus must match the Defaults table in
        # docs/context-compression-plan.md verbatim — keep this assertion
        # tight so doc/code drift trips a test, not a Copilot review.
        assert (
            "/compact MAP step state, last 2 monitor verdicts, "
            "pending subtasks; drop tool-result bodies older than 3 turns"
        ) in msg

    def test_zero_threshold_does_not_divide(self) -> None:
        # Defensive: format must not crash even if a bad threshold reaches it.
        msg = format_compact_instruction(used=10, threshold=0, focus="x")
        assert "0%" in msg


# ---------------------------------------------------------------------------
# TokenUsage dataclass
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_total_sums_three_fields(self) -> None:
        u = TokenUsage(
            input_tokens=10,
            cache_read_input_tokens=20,
            cache_creation_input_tokens=30,
        )
        assert u.total == 60

    def test_default_zero(self) -> None:
        assert TokenUsage().total == 0

    def test_is_frozen(self) -> None:
        u = TokenUsage()
        with pytest.raises(dataclasses.FrozenInstanceError):
            u.input_tokens = 5  # type: ignore[misc]
