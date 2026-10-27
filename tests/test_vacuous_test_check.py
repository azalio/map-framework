"""The vacuous-test rule shipped to Actor/Monitor/Evaluator and /map-tdd.

The rule: a test is vacuous when it stays green against a do-nothing
implementation. The examples in the shared partial are executed here against
both a real and a do-nothing implementation, so a misclassified example in the
prompt text fails this suite.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
PARTIAL = REPO / "src/mapify_cli/templates_src/_partials/vacuous-test-check.md.jinja"
RULE_HEADING = "Vacuous-test check (do-nothing implementation)"


def _real_impl(tmp_path: Path) -> SimpleNamespace:
    def process(data: list[int]) -> None:
        data.append(len(data))

    def save(path: Path, text: str) -> None:
        path.write_text(text)

    def validate(value: int) -> int:
        if value < 0:
            raise ValueError("negative")
        return value

    return SimpleNamespace(
        parse=lambda text: text.split(","),
        load=lambda raw: dict(raw),
        process=process,
        save=save,
        validate=validate,
        target=tmp_path / "real.txt",
    )


def _do_nothing_impl(tmp_path: Path) -> SimpleNamespace:
    """Every function returns the empty value of its return type, no side effect."""
    return SimpleNamespace(
        parse=lambda _text: [],
        load=lambda _raw: {},
        process=lambda _data: None,
        save=lambda _path, _text: None,
        validate=lambda _value: 0,
        target=tmp_path / "do-nothing.txt",
    )


# Vacuous shapes named in the partial.
def vacuous_no_assertion(impl: SimpleNamespace) -> None:
    impl.process([1, 2])


def vacuous_type_only(impl: SimpleNamespace) -> None:
    assert isinstance(impl.parse("a,b"), list)


def vacuous_not_none(impl: SimpleNamespace) -> None:
    assert impl.load({"x": 1}) is not None


def vacuous_checks_own_setup(impl: SimpleNamespace) -> None:
    del impl  # never calls the code under test
    repo = mock.Mock()
    item = object()
    repo.get.return_value = item
    assert repo.get(1) == item


def vacuous_exception_raised_by_test(impl: SimpleNamespace) -> None:
    with pytest.raises(KeyError):
        impl.load({"x": 1})["missing"]  # the test's own indexing raises


# Shapes the partial names as NOT vacuous.
def behavioral_value(impl: SimpleNamespace) -> None:
    assert impl.parse("a,b") == ["a", "b"]


def behavioral_expected_exception(impl: SimpleNamespace) -> None:
    with pytest.raises(ValueError):
        impl.validate(-1)


def behavioral_side_effect(impl: SimpleNamespace) -> None:
    impl.save(impl.target, "hello")
    assert impl.target.read_text() == "hello"


VACUOUS: list[Callable[[SimpleNamespace], None]] = [
    vacuous_no_assertion,
    vacuous_type_only,
    vacuous_not_none,
    vacuous_checks_own_setup,
    vacuous_exception_raised_by_test,
]
BEHAVIORAL: list[Callable[[SimpleNamespace], None]] = [
    behavioral_value,
    behavioral_expected_exception,
    behavioral_side_effect,
]


@pytest.mark.parametrize("case", VACUOUS, ids=lambda f: f.__name__)
def test_vacuous_shapes_stay_green_against_do_nothing_implementation(
    case: Callable[[SimpleNamespace], None], tmp_path: Path
) -> None:
    case(_real_impl(tmp_path))
    case(_do_nothing_impl(tmp_path))  # green on empty code: verifies nothing


@pytest.mark.parametrize("case", BEHAVIORAL, ids=lambda f: f.__name__)
def test_behavioral_shapes_fail_against_do_nothing_implementation(
    case: Callable[[SimpleNamespace], None], tmp_path: Path
) -> None:
    case(_real_impl(tmp_path))
    with pytest.raises((AssertionError, FileNotFoundError, pytest.fail.Exception)):
        case(_do_nothing_impl(tmp_path))


def test_partial_examples_match_the_executed_fixtures() -> None:
    text = PARTIAL.read_text()
    for example in (
        "process(data)",
        'assert isinstance(parse("a,b"), list)',
        'assert load({"x": 1}) is not None',
        "repo.get.return_value = item; assert repo.get(1) == item",
        'with pytest.raises(KeyError): load({"x": 1})["missing"]',
        "whose exception is raised by the code\nunder test",
        'assert parse("a,b") == ["a", "b"]',
        "pytest.raises",
    ):
        assert example in text, f"partial example drifted from fixtures: {example}"


@pytest.mark.parametrize(
    "rendered",
    [
        "src/mapify_cli/templates/agents/actor.md",
        "src/mapify_cli/templates/agents/evaluator.md",
        "src/mapify_cli/templates/agents/monitor.md",
        "src/mapify_cli/templates/codex/agents/actor.toml",
        "src/mapify_cli/templates/codex/agents/evaluator.toml",
        "src/mapify_cli/templates/codex/agents/monitor.toml",
    ],
)
def test_rule_ships_once_in_each_review_and_actor_prompt(rendered: str) -> None:
    assert (REPO / rendered).read_text().count(RULE_HEADING) == 1


def test_monitor_treats_vacuous_tests_as_missing_coverage() -> None:
    for rendered in (
        "src/mapify_cli/templates/agents/monitor.md",
        "src/mapify_cli/templates/codex/agents/monitor.toml",
    ):
        text = (REPO / rendered).read_text()
        assert "only\nby vacuous tests has `test_coverage != PASS`" in text
        assert "`Vacuous test: <test id>`" in text


@pytest.mark.parametrize(
    "rendered",
    [
        "src/mapify_cli/templates/skills/map-tdd/SKILL.md",
        "src/mapify_cli/templates/codex/skills/map-tdd/SKILL.md",
    ],
)
def test_map_tdd_quality_gate_rejects_any_vacuous_test(rendered: str) -> None:
    text = (REPO / rendered).read_text()
    assert "the test is vacuous: rewrite or drop it" in text
    assert "**Vacuous** — stays green against a do-nothing implementation" in text
