"""Tests for mapify_cli.skills_eval.proposer — propose_description().

Coverage:
- VC2 [INV-2/HC-7]: MAP_INVOKED_BY is set (non-empty) in subprocess env.
- VC3 [INV-1]: argv is a list; no shell=True; untrusted record text is a
  discrete argv element (not interpolated into one shell string).
- VC4 [INV-1]: success returns .result text; returncode!=0 -> None;
  malformed JSON -> None; missing .result -> None; whitespace-only .result
  -> None; FileNotFoundError/OSError -> None; TimeoutExpired -> None.
"""
from __future__ import annotations

import json
import subprocess
import types
from typing import Any

import pytest

from mapify_cli.skills_eval.eval_schema import EvalResultRecord
from mapify_cli.skills_eval.proposer import _DEFAULT_MAX_CHARS, propose_description

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    prompt: str = "test prompt",
    assertions_failed: list[str] | None = None,
) -> EvalResultRecord:
    """Construct a minimal EvalResultRecord for test use."""
    return EvalResultRecord(
        cell_id="p0-v0-r0",
        prompt=prompt,
        triggered_skill=None,
        token_usage=None,
        duration_s=0.0,
        assertions_passed=[],
        assertions_failed=assertions_failed or ["should_trigger: map-debug"],
        raw_output="",
    )


def _fake_run(
    returncode: int,
    stdout: str,
    capture: dict[str, Any] | None = None,
    *,
    raise_exc: BaseException | None = None,
) -> Any:
    """Return a monkeypatch-compatible subprocess.run replacement.

    If ``raise_exc`` is provided, the fake raises it instead of returning a
    result.  ``capture`` dict is populated with the argv and kwargs received.
    """

    def run(argv: list[str], **kwargs: Any) -> types.SimpleNamespace:
        if capture is not None:
            capture["argv"] = argv
            capture["kwargs"] = kwargs
        if raise_exc is not None:
            raise raise_exc
        return types.SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )

    return run


# ---------------------------------------------------------------------------
# VC4 — success path
# ---------------------------------------------------------------------------


def test_vc4_success_returns_result_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: success path returns stripped .result text from JSON envelope."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "  improved description  "}), cap),
    )
    result = propose_description("old desc", [_make_record()])
    assert result == "improved description"


def test_vc4_result_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: leading/trailing whitespace is stripped from .result."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "\n  new desc\n\t"})),
    )
    result = propose_description("old desc", [_make_record()])
    assert result == "new desc"


# ---------------------------------------------------------------------------
# VC4 — failure paths
# ---------------------------------------------------------------------------


def test_vc4_nonzero_returncode_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: non-zero returncode -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(1, json.dumps({"result": "some output"})),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_malformed_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: malformed JSON in stdout -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, "this is not json"),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_missing_result_field_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: JSON envelope with no .result field -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"session_id": "abc123"})),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_whitespace_only_result_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: whitespace-only .result -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "   \n\t  "})),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_empty_result_string_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: empty string .result -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": ""})),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_non_dict_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: JSON that parses to a non-dict (e.g. a list) -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps(["result", "oops"])),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_file_not_found_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: FileNotFoundError (claude not on PATH) -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, "", raise_exc=FileNotFoundError("claude not found")),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_oserror_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: generic OSError -> None (FileNotFoundError is a subclass)."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, "", raise_exc=OSError("some OS error")),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_vc4_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC4: TimeoutExpired -> None."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(
            0,
            "",
            raise_exc=subprocess.TimeoutExpired(cmd=["claude"], timeout=120),
        ),
    )
    assert propose_description("old desc", [_make_record()]) is None


# ---------------------------------------------------------------------------
# VC2 — MAP_INVOKED_BY in subprocess env
# ---------------------------------------------------------------------------


def test_vc2_map_invoked_by_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC2 [INV-2/HC-7]: MAP_INVOKED_BY is present and non-empty in subprocess env."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "new desc"}), cap),
    )
    propose_description("old desc", [_make_record()])
    assert "MAP_INVOKED_BY" in cap["kwargs"]["env"], (
        "MAP_INVOKED_BY must be set in subprocess env"
    )
    assert cap["kwargs"]["env"]["MAP_INVOKED_BY"], (
        "MAP_INVOKED_BY must be non-empty"
    )


# ---------------------------------------------------------------------------
# VC3 — argv is a list, no shell=True, untrusted text is a discrete element
# ---------------------------------------------------------------------------


def test_vc3_argv_is_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC3 [INV-1]: argv passed to subprocess.run must be a list (not a string)."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "ok"}), cap),
    )
    propose_description("old desc", [_make_record()])
    assert isinstance(cap["argv"], list), (
        f"argv must be a list, got {type(cap['argv']).__name__!r}"
    )


def test_vc3_no_shell_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """VC3 [INV-1]: shell=True must NOT be passed to subprocess.run."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "ok"}), cap),
    )
    propose_description("old desc", [_make_record()])
    assert cap["kwargs"].get("shell") is not True, (
        "shell=True must not be used — it enables shell injection"
    )


def test_vc3_untrusted_text_is_discrete_argv_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VC3 [INV-1]: record .prompt content appears as a discrete argv element.

    The full argv must be a list where the prompt string is a distinct element,
    not interpolated together with the claude binary and flags into one string.
    This guards against shell-injection via untrusted eval-set content.
    """
    untrusted_prompt = "rm -rf /; echo injected"
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "new desc"}), cap),
    )
    propose_description("old desc", [_make_record(prompt=untrusted_prompt)])

    argv: list[str] = cap["argv"]
    # argv must be a list — not a single joined string
    assert isinstance(argv, list), "argv must be a list"
    # The untrusted text must NOT be concatenated with the claude binary in one element
    for element in argv:
        assert not (
            "claude" in element and untrusted_prompt in element
        ), (
            f"Untrusted text was interpolated into a combined argv element: {element!r}"
        )
    # The argv list must contain at least one element that contains the untrusted text
    assert any(untrusted_prompt in element for element in argv), (
        "Untrusted record text must appear somewhere in argv (as a discrete element)"
    )


def test_vc3_assertions_failed_text_appears_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VC3: assertions_failed content from failing records is included in the prompt."""
    failing_assertion = "should_trigger: map-special"
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "new desc"}), cap),
    )
    propose_description(
        "old desc",
        [_make_record(assertions_failed=[failing_assertion])],
    )
    argv: list[str] = cap["argv"]
    combined = " ".join(argv)
    assert failing_assertion in combined, (
        "assertions_failed content must be included in the prompt"
    )


# ---------------------------------------------------------------------------
# Empty failing records list — edge case
# ---------------------------------------------------------------------------


def test_empty_failing_records_still_calls_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge case: empty failing_train_records list — subprocess still called."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "improved"}), cap),
    )
    result = propose_description("current desc", [])
    assert result == "improved"
    assert "argv" in cap, "subprocess.run must be called even with no failing records"


# ---------------------------------------------------------------------------
# Length cap — proposals must fit the skill `description` spec limit
# ---------------------------------------------------------------------------


def test_default_max_chars_is_spec_limit() -> None:
    """The default cap is the Agent Skills `description` spec maximum (1024)."""
    assert _DEFAULT_MAX_CHARS == 1024


def test_over_limit_proposal_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proposal longer than max_chars is rejected (None) — never shipped."""
    too_long = "x" * (_DEFAULT_MAX_CHARS + 1)
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": too_long})),
    )
    assert propose_description("old desc", [_make_record()]) is None


def test_at_limit_proposal_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proposal exactly at max_chars is accepted (boundary is inclusive)."""
    at_limit = "y" * _DEFAULT_MAX_CHARS
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": at_limit})),
    )
    result = propose_description("old desc", [_make_record()])
    assert result == at_limit


def test_custom_max_chars_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit max_chars overrides the default for both accept and reject."""
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "z" * 60})),
    )
    assert propose_description("old", [_make_record()], max_chars=50) is None
    assert propose_description("old", [_make_record()], max_chars=100) == "z" * 60


def test_prompt_states_the_char_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The improvement prompt tells claude the hard character limit."""
    cap: dict[str, Any] = {}
    monkeypatch.setattr(
        "mapify_cli.skills_eval.proposer.subprocess.run",
        _fake_run(0, json.dumps({"result": "short desc"}), cap),
    )
    propose_description("old desc", [_make_record()], max_chars=250)
    # argv = ["claude", "-p", <prompt>, "--output-format", "json"]
    prompt = cap["argv"][2]
    assert "250" in prompt
    assert "character" in prompt.lower()
