"""Tests for skill eval optimizer fixtures (ST-007).

Validates:
- VC1: the 3 new optimizer fixtures each have >= 8 entries loadable via load_eval_set.
- VC2: each fixture is 60/40-splittable with n_test >= 3.
- VC3: the existing 3-entry smoke fixture is unchanged; README.md exists and
       documents the >= 8 sizing rationale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mapify_cli.skills_eval.description_optimizer import _DEFAULT_SEED, split_train_test
from mapify_cli.skills_eval.runner import load_eval_set

_FIXTURES_DIR = Path(__file__).parent / "skills_eval" / "fixtures"

_NEW_FIXTURES = [
    _FIXTURES_DIR / "map_plan_optimize_eval_set.json",
    _FIXTURES_DIR / "map_efficient_optimize_eval_set.json",
    _FIXTURES_DIR / "map_debug_optimize_eval_set.json",
]

_SMOKE_FIXTURE = _FIXTURES_DIR / "map_debug_eval_set.json"


# ---------------------------------------------------------------------------
# Discovery guard (fail loudly on path typos before parametrized tests run)
# ---------------------------------------------------------------------------


def test_new_fixture_discovery_non_empty() -> None:
    """All 3 new fixture paths must exist — catches path typos before parametrize."""
    assert len(_NEW_FIXTURES) == 3, f"Expected 3 fixtures, got {len(_NEW_FIXTURES)}"
    missing = [str(p) for p in _NEW_FIXTURES if not p.exists()]
    assert not missing, f"Missing fixture files: {missing}"


# ---------------------------------------------------------------------------
# VC1: each new fixture has >= 8 entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_path", _NEW_FIXTURES, ids=[p.name for p in _NEW_FIXTURES])
def test_vc1_new_fixture_has_at_least_8_entries(fixture_path: Path) -> None:
    entries = load_eval_set(fixture_path)
    assert len(entries) >= 8, (
        f"{fixture_path.name} has only {len(entries)} entries; optimizer requires >= 8"
    )


# ---------------------------------------------------------------------------
# VC2: each new fixture is 60/40-splittable with n_test >= 3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_path", _NEW_FIXTURES, ids=[p.name for p in _NEW_FIXTURES])
def test_vc2_new_fixture_split_yields_n_test_ge_3(fixture_path: Path) -> None:
    entries = load_eval_set(fixture_path)
    train, test = split_train_test(entries, _DEFAULT_SEED)
    assert len(test) >= 3, (
        f"{fixture_path.name}: n_test={len(test)}, expected >= 3 for a meaningful held-out set"
    )
    assert len(train) + len(test) == len(entries), (
        f"{fixture_path.name}: split sizes {len(train)}+{len(test)} != total {len(entries)}"
    )


# ---------------------------------------------------------------------------
# VC3: smoke fixture unchanged; README.md exists and documents >= 8 rationale
# ---------------------------------------------------------------------------


def test_vc3_smoke_fixture_has_exactly_3_entries() -> None:
    """The 3-entry smoke fixture must remain untouched."""
    assert _SMOKE_FIXTURE.exists(), f"Smoke fixture missing: {_SMOKE_FIXTURE}"
    entries = load_eval_set(_SMOKE_FIXTURE)
    assert len(entries) == 3, (
        f"Smoke fixture {_SMOKE_FIXTURE.name} must have exactly 3 entries "
        f"(got {len(entries)}); do not modify it"
    )


def test_vc3_readme_exists_and_documents_sizing_rationale() -> None:
    """README.md must exist and mention the >= 8 sizing rationale."""
    readme = _FIXTURES_DIR / "README.md"
    assert readme.exists(), f"README.md not found at {readme}"
    content = readme.read_text(encoding="utf-8")
    assert ">= 8" in content or "8 entries" in content or "≥ 8" in content, (
        "README.md must document the >= 8 (or '8 entries' / '≥ 8') optimizer sizing rationale"
    )
