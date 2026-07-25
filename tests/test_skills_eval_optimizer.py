"""Tests for description_optimizer.py — VC1, VC4, VC5, VC6.

All tests use:
- A stateful ScriptedDispatcher (subclasses VariantDispatcher) for zero subprocess calls.
- A function proposer (no claude subprocess).
- A minimal real source tree: tmp/.claude/skills/<skill>/SKILL.md with valid frontmatter.

Scenarios covered
-----------------
VC1:  overfit candidate (train up, test down vs baseline) → overfit=True, selected=False
VC1:  strict-better candidate (test > baseline) → selected=True, no_improvement=False
VC1:  full-tie across all iterations → baseline (iter 0) wins, no_improvement=True
VC4:  proposer returning None → proposal_failed iteration recorded, loop continues,
       baseline still eligible as winner
VC5:  OptimizeResult fields populated: candidate_description, pass-rates, token totals,
       selected flag; TokenUsage.total verified
VC6:  production source .claude/ is never modified; temp dirs cleaned up after optimize
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from mapify_cli.skills_eval.description_optimizer import (
    _set_frontmatter_description,
    optimize,
    split_train_test,
)
from mapify_cli.skills_eval.dispatcher import VariantDispatcher
from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
    EvalResultRecord,
    EvalSetEntry,
    OptimizeResult,
)
from mapify_cli.token_budget import TokenUsage

# ---------------------------------------------------------------------------
# Helpers: source tree fixture
# ---------------------------------------------------------------------------

SKILL_NAME = "test-skill"
_BASE_DESC = "base desc"


def _make_source_tree(tmp: Path, desc: str = _BASE_DESC) -> Path:
    """Create a minimal .claude/skills/<skill>/SKILL.md under tmp."""
    skill_dir = tmp / ".claude" / "skills" / SKILL_NAME
    skill_dir.mkdir(parents=True)
    content = f'---\nname: {SKILL_NAME}\ndescription: "{desc}"\n---\n# body\n'
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return tmp / ".claude"


def _make_entries(n: int, skill: str = SKILL_NAME) -> list[EvalSetEntry]:
    """Create n EvalSetEntry rows that should_trigger the given skill."""
    return [
        EvalSetEntry(
            prompt=f"prompt-{i}",
            should_trigger=skill,
            should_not_trigger=None,
            assertions=[],
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Stateful scripted dispatcher
# ---------------------------------------------------------------------------


class ScriptedDispatcher(VariantDispatcher):
    """Returns DispatchResults from a pre-built call script (list pop order).

    Each element in ``script`` is a tuple (triggered_skill, token_total).
    When the script is exhausted, returns a passing result for SKILL_NAME.
    """

    def __init__(self, script: Sequence[tuple[str | None, int]]) -> None:
        self._script = list(script)
        self._call_count = 0

    def dispatch(self, prompt: str) -> DispatchResult:
        del prompt  # intentionally unused; scripted mock
        if self._script:
            triggered, tokens = self._script.pop(0)
        else:
            triggered = SKILL_NAME
            tokens = 10
        self._call_count += 1
        return DispatchResult(
            raw_output="",
            triggered_skill=triggered,
            token_usage=TokenUsage(input_tokens=tokens),
            duration_s=0.0,
            error=None,
        )


# ---------------------------------------------------------------------------
# Proposer helpers
# ---------------------------------------------------------------------------


def _make_fixed_proposer(description: str):
    """Return a proposer that always returns the given description."""
    def proposer(current_desc: str, failing: list[EvalResultRecord]) -> str:
        del current_desc, failing  # unused in fixed proposer
        return description
    return proposer


def _make_none_proposer():
    """Return a proposer that always returns None (proposal_failed)."""
    def proposer(current_desc: str, failing: list[EvalResultRecord]) -> None:
        del current_desc, failing  # unused
    return proposer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_src(tmp_path: Path) -> Path:
    """tmp_path/.claude/ with a valid SKILL.md."""
    return _make_source_tree(tmp_path / "src")


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """Separate output directory for .jsonl files."""
    d = tmp_path / "out"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# VC1: overfit candidate — train up, test down → overfit=True, selected=False
# ---------------------------------------------------------------------------


def test_vc1_overfit_candidate_not_selected(tmp_src: Path, out_dir: Path) -> None:
    """VC1 [AC-1][INV-4][HC-4]: overfit=True candidate must NOT be selected."""
    # 5 entries: split_train_test with default seed → 3 train, 2 test (n=5, n_test=2)
    entries = _make_entries(5)

    # Dispatcher script design:
    # iter 0 (baseline): ALL dispatch calls return triggered=None (no trigger)
    #   → 3 train fail, 2 test fail → train_pass_rate=0.0, test_pass_rate=0.0
    # iter 1 (candidate): train calls return triggered=SKILL_NAME (pass),
    #                     test calls return triggered=None (fail)
    #   → train_pass_rate=1.0, test_pass_rate=0.0
    #   Overfit: train(1.0) > baseline(0.0) AND test(0.0) < baseline(0.0) is FALSE
    #   Wait — 0.0 is NOT strictly less than 0.0; overfit needs test < baseline.
    # Fix: baseline test = 0.5 (1 of 2 pass), candidate test = 0.0
    # baseline: 3 train=None(fail), 2 test: 1 pass + 1 fail → test=0.5
    # candidate: 3 train=SKILL(pass), 2 test: both None(fail) → test=0.0

    # We need to figure out the split to know which are train vs test indices.
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # baseline iter 0: n_train fails, (n_test-1) test pass + 1 test fail
    # baseline_script is a list of (triggered_skill, token_total) tuples
    baseline_script = (
        [(None, 5)] * n_train                        # train: all fail
        + [(SKILL_NAME, 5)] * (n_test - 1)           # test: n_test-1 pass
        + [(None, 5)]                                # test: 1 fail
    )
    # candidate iter 1: all train pass, all test fail
    candidate_script = (
        [(SKILL_NAME, 8)] * n_train                  # train: all pass
        + [(None, 5)] * n_test                       # test: all fail
    )

    # Combine: baseline first, then candidate
    full_script = baseline_script + candidate_script

    dispatcher = ScriptedDispatcher(full_script)

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_fixed_proposer("better desc attempt"),
        dispatcher=dispatcher,
        source_claude_dir=tmp_src,
        out_dir=out_dir,
        run_ts="20260101T000000Z",
        iterations=2,
        seed=1337,
    )

    assert isinstance(result, OptimizeResult)
    assert len(result.iterations) == 2

    baseline = result.iterations[0]
    candidate = result.iterations[1]

    # Baseline should have partial test pass-rate
    assert baseline.test_pass_rate > 0.0, "baseline test_pass_rate should be > 0"

    # Candidate: train improved, test did NOT improve (0.0 < baseline)
    assert candidate.train_pass_rate > baseline.train_pass_rate
    assert candidate.test_pass_rate < baseline.test_pass_rate

    # VC1: overfit flagged
    assert candidate.overfit is True, "overfit candidate must be flagged overfit=True"
    assert candidate.selected is False, "overfit candidate must NOT be selected"

    # VC1: baseline is selected (no strict improvement)
    assert baseline.selected is True
    assert result.no_improvement is True
    assert result.winning_iteration == 0
    assert result.winning_description == _BASE_DESC


# ---------------------------------------------------------------------------
# VC1: strict-better candidate → selected=True, no_improvement=False
# ---------------------------------------------------------------------------


def test_vc1_strict_better_candidate_selected(tmp_src: Path, out_dir: Path) -> None:
    """VC1: candidate with test_pass_rate > baseline → selected=True, no_improvement=False."""
    entries = _make_entries(5)
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # baseline: all fail → 0.0 train, 0.0 test
    baseline_script = [(None, 5)] * (n_train + n_test)
    # candidate: all pass → 1.0 train, 1.0 test (strictly > 0.0)
    candidate_script = [(SKILL_NAME, 12)] * (n_train + n_test)

    dispatcher = ScriptedDispatcher(baseline_script + candidate_script)

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_fixed_proposer("improved desc"),
        dispatcher=dispatcher,
        source_claude_dir=tmp_src,
        out_dir=out_dir,
        run_ts="20260101T000001Z",
        iterations=2,
        seed=1337,
    )

    assert len(result.iterations) == 2
    candidate = result.iterations[1]

    assert candidate.selected is True
    assert result.no_improvement is False
    assert result.winning_iteration == 1
    assert result.winning_description == "improved desc"
    # VC5: check token totals
    assert candidate.train_tokens_total > 0
    assert candidate.test_tokens_total > 0
    # VC5: candidate_description populated
    assert candidate.candidate_description == "improved desc"


# ---------------------------------------------------------------------------
# VC1 / VC5: full tie across all iterations → baseline wins, no_improvement=True
# ---------------------------------------------------------------------------


def test_vc1_full_tie_baseline_wins(tmp_src: Path, out_dir: Path) -> None:
    """VC5 [AC-2]: full-tie across all iterations -> baseline selected, no_improvement=True."""
    entries = _make_entries(5)
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # 3 iterations; all produce same result: all fail
    per_iter = [(None, 5)] * (n_train + n_test)
    dispatcher = ScriptedDispatcher(per_iter * 3)

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_fixed_proposer("same rate desc"),
        dispatcher=dispatcher,
        source_claude_dir=tmp_src,
        out_dir=out_dir,
        run_ts="20260101T000002Z",
        iterations=3,
        seed=1337,
    )

    assert result.no_improvement is True
    assert result.winning_iteration == 0
    assert result.winning_description == _BASE_DESC
    # Baseline is selected
    baseline = result.iterations[0]
    assert baseline.selected is True
    # Others are not selected
    for rec in result.iterations[1:]:
        assert rec.selected is False, f"iter {rec.iteration} should not be selected"


# ---------------------------------------------------------------------------
# VC4: proposer returning None → proposal_failed recorded, baseline eligible
# ---------------------------------------------------------------------------


def test_vc4_proposal_failed_continues(tmp_src: Path, out_dir: Path) -> None:
    """VC4 [INV-6][HC-3]: proposer returning None => proposal_failed iter; loop continues."""
    entries = _make_entries(4)
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # Only baseline gets dispatched (iter 1 and 2 will be proposal_failed)
    baseline_script = [(None, 5)] * (n_train + n_test)
    dispatcher = ScriptedDispatcher(baseline_script)

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_none_proposer(),
        dispatcher=dispatcher,
        source_claude_dir=tmp_src,
        out_dir=out_dir,
        run_ts="20260101T000003Z",
        iterations=3,
        seed=1337,
    )

    # 3 iterations: iter 0 (baseline) + iter 1 and 2 (proposal_failed)
    assert len(result.iterations) == 3

    baseline = result.iterations[0]
    assert not baseline.proposal_failed

    for rec in result.iterations[1:]:
        assert rec.proposal_failed is True, f"iter {rec.iteration} should be proposal_failed"
        assert rec.candidate_description is None
        assert rec.train_pass_rate == 0.0
        assert rec.test_pass_rate == 0.0
        assert rec.train_jsonl_path == ""
        assert rec.test_jsonl_path == ""

    # Baseline wins (no strict improvement)
    assert result.winning_iteration == 0
    assert result.no_improvement is True


# ---------------------------------------------------------------------------
# VC5: OptimizeResult fields populated correctly
# ---------------------------------------------------------------------------


def test_vc5_result_fields_populated(tmp_src: Path, out_dir: Path) -> None:
    """VC5 [AC-2]: verify all OptimizeResult and OptimizeIterationRecord fields."""
    entries = _make_entries(5)
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # Baseline fails; candidate passes everything
    baseline_script = [(None, 3)] * (n_train + n_test)
    candidate_script = [(SKILL_NAME, 7)] * (n_train + n_test)
    dispatcher = ScriptedDispatcher(baseline_script + candidate_script)

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_fixed_proposer("new candidate"),
        dispatcher=dispatcher,
        source_claude_dir=tmp_src,
        out_dir=out_dir,
        run_ts="20260101T000004Z",
        iterations=2,
        seed=1337,
    )

    # Top-level fields
    assert result.skill == SKILL_NAME
    assert result.seed == 1337
    assert result.n_train == n_train
    assert result.n_test == n_test
    assert result.baseline_description == _BASE_DESC
    assert result.winning_description == "new candidate"
    assert result.winning_iteration == 1
    assert result.no_improvement is False

    # Per-iteration record fields (VC5)
    candidate = result.iterations[1]
    assert candidate.candidate_description == "new candidate"
    assert candidate.train_pass_rate == 1.0
    assert candidate.test_pass_rate == 1.0
    # Token totals: n_train * 7 for train, n_test * 7 for test
    assert candidate.train_tokens_total == n_train * 7
    assert candidate.test_tokens_total == n_test * 7
    assert candidate.selected is True
    assert candidate.overfit is False
    assert candidate.proposal_failed is False

    # TokenUsage.total check via explicit construction
    tu = TokenUsage(input_tokens=5, cache_read_input_tokens=3, cache_creation_input_tokens=2)
    assert tu.total == 10


# ---------------------------------------------------------------------------
# VC6: production source SKILL.md is never modified; temp dirs cleaned up
# ---------------------------------------------------------------------------


def test_vc6_production_source_untouched(tmp_path: Path, out_dir: Path) -> None:
    """VC6 [INV-7]: source .claude/ is NEVER modified; temp dirs removed after optimize."""
    src_root = tmp_path / "prod_src"
    source_claude = _make_source_tree(src_root)

    # Record original state
    skill_md = source_claude / "skills" / SKILL_NAME / "SKILL.md"
    original_content = skill_md.read_text(encoding="utf-8")
    original_mtime = skill_md.stat().st_mtime

    entries = _make_entries(4)
    train_entries, test_entries = split_train_test(entries, 1337)
    n_train = len(train_entries)
    n_test = len(test_entries)

    # Run 2 iterations with a dispatcher that always passes
    dispatcher = ScriptedDispatcher(
        [(SKILL_NAME, 10)] * (n_train + n_test) * 2
    )

    import glob
    import os
    tmpdir = tempfile.gettempdir()

    # Snapshot mapeval-candidate dirs before
    before = set(glob.glob(os.path.join(tmpdir, "mapeval-candidate-*")))

    result = optimize(
        skill=SKILL_NAME,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_make_fixed_proposer("new desc"),
        dispatcher=dispatcher,
        source_claude_dir=source_claude,
        out_dir=out_dir,
        run_ts="20260101T000005Z",
        iterations=2,
        seed=1337,
    )

    # After: mapeval-candidate dirs should all be removed
    after = set(glob.glob(os.path.join(tmpdir, "mapeval-candidate-*")))
    new_dirs = after - before
    assert not new_dirs, (
        f"Leftover mapeval-candidate-* dirs after optimize: {new_dirs}"
    )

    # VC6: source SKILL.md content is byte-identical
    assert skill_md.read_text(encoding="utf-8") == original_content, (
        "Source SKILL.md was modified by optimize()!"
    )
    # VC6: mtime unchanged (file was not touched)
    assert skill_md.stat().st_mtime == original_mtime, (
        "Source SKILL.md mtime changed — file was written!"
    )

    # Sanity check: optimization ran
    assert len(result.iterations) == 2


# ---------------------------------------------------------------------------
# VC6: fail-loud frontmatter patch — raise paths (no partial write)
# ---------------------------------------------------------------------------


def test_set_frontmatter_description_raises_without_opening_fence() -> None:
    """VC6 fail-loud: content not starting with '---\\n' raises ValueError."""
    with pytest.raises(ValueError):
        _set_frontmatter_description("name: x\ndescription: y\n", "new desc")


def test_set_frontmatter_description_raises_without_closing_fence() -> None:
    """VC6 fail-loud: frontmatter with no closing '---' raises ValueError."""
    with pytest.raises(ValueError):
        _set_frontmatter_description("---\nname: x\ndescription: y\n", "new desc")


def test_set_frontmatter_description_raises_without_description_key() -> None:
    """VC6 fail-loud: frontmatter lacking a 'description:' line raises ValueError."""
    with pytest.raises(ValueError):
        _set_frontmatter_description("---\nname: x\n---\n# body\n", "new desc")


def test_set_frontmatter_description_roundtrips_tricky_value() -> None:
    """VC6: a value with quotes/colon/newline survives a YAML round-trip."""
    tricky = 'has "quotes": a colon\nand a newline'
    patched = _set_frontmatter_description(
        '---\nname: x\ndescription: "old"\n---\n# body\n', tricky
    )
    # The body and other keys are preserved; description re-parses to `tricky`.
    assert "name: x" in patched
    assert "# body" in patched
    fm = patched.split("---\n", 2)[1]
    desc_line = next(ln for ln in fm.splitlines() if ln.startswith("description:"))
    parsed = json.loads(desc_line[len("description: "):])  # double-quoted YAML == JSON string
    assert parsed == tricky


def test_set_frontmatter_description_replaces_block_scalar() -> None:
    """The bug that shipped: a ``description: |`` block scalar must be FULLY
    replaced — leaving its indented body orphaned below the new quoted scalar
    produces invalid YAML that silently unregisters the skill (0 triggers).

    Every shipped map-* skill (except the single-line map-plan) uses a block
    scalar, so this is the common case, not an edge case.
    """
    from mapify_cli.skill_ir import parse_frontmatter

    original = (
        "---\n"
        "name: map-check\n"
        "description: |\n"
        "  Run quality gates and verify completion. Use when asked to run checks.\n"
        "  Do NOT use to plan; use map-plan instead.\n"
        "effort: low\n"
        "disable-model-invocation: true\n"
        "argument-hint: \"[focus area]\"\n"
        "---\n"
        "# /map-check body\n"
    )
    new = "Tuned: trigger on quality-gate requests. Do not plan."
    patched = _set_frontmatter_description(original, new)

    # No orphaned continuation line survives.
    assert "Run quality gates and verify completion" not in patched
    assert "Do NOT use to plan; use map-plan instead." not in patched
    # The body and every sibling key are preserved.
    assert "# /map-check body" in patched
    for key in ("name: map-check", "effort: low", "disable-model-invocation: true"):
        assert key in patched
    # The frontmatter re-parses as valid YAML with exactly the new description.
    close = patched.find("\n---", 4)
    fm = parse_frontmatter(patched[4:close])
    assert fm["description"].strip() == new
    assert fm["disable-model-invocation"] is True
    assert fm["effort"] == "low"


def test_set_frontmatter_description_replaces_folded_scalar() -> None:
    """Same handling for a folded (``>``) block scalar."""
    from mapify_cli.skill_ir import parse_frontmatter

    original = (
        "---\n"
        "name: map-x\n"
        "description: >\n"
        "  First line of folded text\n"
        "  continues here.\n"
        "effort: low\n"
        "---\n"
        "# body\n"
    )
    patched = _set_frontmatter_description(original, "new single-line desc")
    assert "First line of folded text" not in patched
    assert "effort: low" in patched
    close = patched.find("\n---", 4)
    fm = parse_frontmatter(patched[4:close])
    assert fm["description"].strip() == "new single-line desc"


def test_optimize_rejects_zero_iterations(tmp_path: Path) -> None:
    """Latent-crash guard: iterations < 1 raises ValueError, not IndexError."""
    source_claude = _make_source_tree(tmp_path / "src")

    def _never_called(_cur: str, _recs: list[EvalResultRecord]) -> str | None:
        del _cur, _recs
        return None

    with pytest.raises(ValueError):
        optimize(
            skill=SKILL_NAME,
            entries=_make_entries(5),
            current_description=_BASE_DESC,
            proposer=_never_called,
            dispatcher=ScriptedDispatcher([]),
            source_claude_dir=source_claude,
            out_dir=tmp_path / "out",
            run_ts="20260101T120000Z",
            iterations=0,
        )
