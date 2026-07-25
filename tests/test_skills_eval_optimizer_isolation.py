"""Isolation tests for description_optimizer.py — VC2 and VC3.

VC2 [INV-3][HC-8]:
  - split_train_test is pure/deterministic (same inputs -> identical split).
  - Module source contains NO ``import random``, ``import datetime``,
    ``datetime.now``, ``time.time``.

VC3 [INV-8][HC-11][AC-12]:
  - An N-iteration run produces N distinct <ts>-optimize-iter<N>-{train,test}.jsonl
    paths (2*N files).
  - Every run_eval call uses resume=False.
  - cell_ids from different iterations NEVER share a .jsonl file.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

from mapify_cli.skills_eval.description_optimizer import (
    _DEFAULT_SEED,
    optimize,
    split_train_test,
)
from mapify_cli.skills_eval.dispatcher import VariantDispatcher
from mapify_cli.skills_eval.eval_schema import (
    DispatchResult,
    EvalResultRecord,
    EvalSetEntry,
)
from mapify_cli.token_budget import TokenUsage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKILL = "test-skill"
_BASE_DESC = "base desc"
_SRC_ROOT = Path(__file__).parent.parent / "src" / "mapify_cli" / "skills_eval"
_OPTIMIZER_SRC = _SRC_ROOT / "description_optimizer.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entries(n: int) -> list[EvalSetEntry]:
    return [
        EvalSetEntry(
            prompt=f"p{i}",
            should_trigger=_SKILL,
            should_not_trigger=None,
            assertions=[],
        )
        for i in range(n)
    ]


def _make_source_tree(tmp: Path) -> Path:
    """Create minimal tmp/.claude/skills/<skill>/SKILL.md."""
    skill_dir = tmp / ".claude" / "skills" / _SKILL
    skill_dir.mkdir(parents=True)
    content = f'---\nname: {_SKILL}\ndescription: "{_BASE_DESC}"\n---\n# body\n'
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return tmp / ".claude"


def _stub_proposer(current: str, failing: list[EvalResultRecord]) -> str | None:
    """Proposer stub for isolation tests — returns a fixed non-None candidate.

    These tests exercise jsonl path isolation and resume=False, not the
    candidate text itself, so the inputs are intentionally unused.
    """
    del current, failing
    return "candidate desc"


class _PassDispatcher(VariantDispatcher):
    """Dispatcher that always triggers _SKILL."""

    def dispatch(self, prompt: str) -> DispatchResult:
        del prompt
        return DispatchResult(
            raw_output="",
            triggered_skill=_SKILL,
            token_usage=TokenUsage(input_tokens=5),
            duration_s=0.0,
            error=None,
        )


# ---------------------------------------------------------------------------
# VC2: split determinism
# ---------------------------------------------------------------------------


def test_vc2_split_deterministic_same_seed() -> None:
    """VC2: identical inputs and seed → identical split on every call."""
    entries = _make_entries(10)
    seed = 42

    train_a, test_a = split_train_test(entries, seed)
    train_b, test_b = split_train_test(entries, seed)

    # Compare by prompt (EvalSetEntry equality is by identity, so compare fields)
    assert [e.prompt for e in train_a] == [e.prompt for e in train_b]
    assert [e.prompt for e in test_a] == [e.prompt for e in test_b]


def test_vc2_split_different_seeds_produce_different_splits() -> None:
    """VC2: different seeds should (very likely) produce different splits."""
    entries = _make_entries(10)
    train_a, _ = split_train_test(entries, seed=1)
    train_b, _ = split_train_test(entries, seed=9999)
    # With 10 items it is astronomically unlikely both seeds give the same split
    prompts_a = [e.prompt for e in train_a]
    prompts_b = [e.prompt for e in train_b]
    assert prompts_a != prompts_b, (
        "Different seeds produced identical splits — seeding is broken"
    )


def test_vc2_split_sizes() -> None:
    """VC2: n_test = max(1, round(n * 0.4)); all entries accounted for."""
    for n in range(1, 15):
        entries = _make_entries(n)
        train, test = split_train_test(entries, 1337)
        expected_test = max(1, round(n * 0.4))
        assert len(test) == expected_test, f"n={n}: expected n_test={expected_test}, got {len(test)}"
        assert len(train) + len(test) == n
        # No duplicates
        all_prompts = [e.prompt for e in train] + [e.prompt for e in test]
        assert len(set(all_prompts)) == n


# ---------------------------------------------------------------------------
# VC2: module source scan — no forbidden imports
# ---------------------------------------------------------------------------


def test_vc2_no_import_random() -> None:
    """VC2 [INV-3]: description_optimizer.py must not import random."""
    source = _OPTIMIZER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "random", (
                    "description_optimizer.py has 'import random' — violates INV-3"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "random", (
                "description_optimizer.py has 'from random import ...' — violates INV-3"
            )


def test_vc2_no_import_datetime() -> None:
    """VC2 [INV-3]: description_optimizer.py must not import datetime."""
    source = _OPTIMIZER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "datetime", (
                    "description_optimizer.py has 'import datetime' — violates INV-3"
                )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "datetime", (
                "description_optimizer.py has 'from datetime import ...' — violates INV-3"
            )


def test_vc2_no_datetime_now_call() -> None:
    """VC2: description_optimizer.py must not call datetime.now() (AST check).

    Uses AST walk over Call nodes so docstring/comment prose is not flagged.
    """
    source = _OPTIMIZER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "now":
            continue
        # datetime.now(...) or datetime.datetime.now(...)
        val = func.value
        if isinstance(val, ast.Name) and val.id == "datetime":
            raise AssertionError(
                "description_optimizer.py calls datetime.now() — "
                "violates clock-free invariant"
            )
        if isinstance(val, ast.Attribute) and val.attr == "datetime":
            raise AssertionError(
                "description_optimizer.py calls datetime.datetime.now() — "
                "violates clock-free invariant"
            )


def test_vc2_no_time_time_call() -> None:
    """VC2: description_optimizer.py must not call time.time() (AST check).

    Uses AST walk over Call nodes so docstring/comment prose is not flagged.
    """
    source = _OPTIMIZER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "time"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            raise AssertionError(
                "description_optimizer.py calls time.time() — "
                "violates clock-free invariant"
            )


# ---------------------------------------------------------------------------
# VC3: N distinct iter paths, resume=False, no intra-file cell_id duplication
# ---------------------------------------------------------------------------


def test_vc3_distinct_jsonl_paths_and_resume_false(
    tmp_path: Path,
) -> None:
    """VC3 [INV-8][HC-11][AC-12]: N iterations → 2*N distinct files; resume=False always."""
    source_claude = _make_source_tree(tmp_path / "src")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    entries = _make_entries(5)
    n_iters = 3
    run_ts = "20260101T120000Z"

    # Track run_eval calls to verify resume=False
    run_eval_calls: list[dict] = []

    import mapify_cli.skills_eval.description_optimizer as opt_module

    original_run_eval = opt_module.run_eval

    def capturing_run_eval(**kwargs) -> list:
        run_eval_calls.append(
            {"out_path": kwargs["out_path"], "resume": kwargs.get("resume", False)}
        )
        return original_run_eval(**kwargs)

    dispatcher = _PassDispatcher()

    with patch.object(opt_module, "run_eval", side_effect=capturing_run_eval):
        result = optimize(
            skill=_SKILL,
            entries=entries,
            current_description=_BASE_DESC,
            proposer=_stub_proposer,
            dispatcher=dispatcher,
            source_claude_dir=source_claude,
            out_dir=out_dir,
            run_ts=run_ts,
            iterations=n_iters,
            seed=_DEFAULT_SEED,
        )

    # VC3: N iterations × 2 splits = 2*N run_eval calls
    assert len(run_eval_calls) == n_iters * 2, (
        f"Expected {n_iters * 2} run_eval calls, got {len(run_eval_calls)}"
    )

    # VC3: all resume=False
    for c in run_eval_calls:
        assert c["resume"] is False, (
            f"run_eval called with resume=True for path {c['out_path']}"
        )

    # VC3: all out_paths are distinct
    paths = [c["out_path"] for c in run_eval_calls]
    assert len({str(p) for p in paths}) == n_iters * 2, (
        f"Duplicate out_paths detected: {paths}"
    )

    # VC3: paths follow the naming convention
    for i in range(n_iters):
        train_name = f"{run_ts}-optimize-iter{i}-train.jsonl"
        test_name = f"{run_ts}-optimize-iter{i}-test.jsonl"
        assert any(str(p).endswith(train_name) for p in paths), (
            f"Missing expected file: {train_name}"
        )
        assert any(str(p).endswith(test_name) for p in paths), (
            f"Missing expected file: {test_name}"
        )

    # VC3: files exist on disk
    for rec in result.iterations:
        if not rec.proposal_failed:
            assert rec.train_jsonl_path != ""
            assert rec.test_jsonl_path != ""
            assert Path(rec.train_jsonl_path).exists(), (
                f"train jsonl missing: {rec.train_jsonl_path}"
            )
            assert Path(rec.test_jsonl_path).exists(), (
                f"test jsonl missing: {rec.test_jsonl_path}"
            )


def test_vc3_no_intra_file_cell_id_duplication(tmp_path: Path) -> None:
    """VC3: no single .jsonl file contains a duplicated cell_id."""
    source_claude = _make_source_tree(tmp_path / "src")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    entries = _make_entries(6)
    n_iters = 3

    dispatcher = _PassDispatcher()

    result = optimize(
        skill=_SKILL,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_stub_proposer,
        dispatcher=dispatcher,
        source_claude_dir=source_claude,
        out_dir=out_dir,
        run_ts="20260101T130000Z",
        iterations=n_iters,
        seed=_DEFAULT_SEED,
    )

    # For each iter jsonl file, assert no duplicated cell_id
    for rec in result.iterations:
        if rec.proposal_failed:
            continue
        for path_str in [rec.train_jsonl_path, rec.test_jsonl_path]:
            path = Path(path_str)
            assert path.exists()
            cell_ids: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                cell_ids.append(row["cell_id"])
            assert len(cell_ids) == len(set(cell_ids)), (
                f"Duplicate cell_ids in {path}: {cell_ids}"
            )


def test_vc3_different_iters_use_different_files(tmp_path: Path) -> None:
    """VC3 [AC-12]: each (iter, split) pair writes to a UNIQUE file path.

    Note: cell_ids legitimately repeat across iterations (same prompt evaluated
    again in each iteration).  The VC3 invariant is about file path uniqueness,
    not cell_id uniqueness across files.
    """
    source_claude = _make_source_tree(tmp_path / "src")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    entries = _make_entries(5)
    n_iters = 3

    dispatcher = _PassDispatcher()

    result = optimize(
        skill=_SKILL,
        entries=entries,
        current_description=_BASE_DESC,
        proposer=_stub_proposer,
        dispatcher=dispatcher,
        source_claude_dir=source_claude,
        out_dir=out_dir,
        run_ts="20260101T140000Z",
        iterations=n_iters,
        seed=_DEFAULT_SEED,
    )

    # Collect all file paths from non-failed iterations
    all_paths: list[str] = []
    for rec in result.iterations:
        if rec.proposal_failed:
            continue
        all_paths.append(rec.train_jsonl_path)
        all_paths.append(rec.test_jsonl_path)

    # Every (iter, split) pair must produce a distinct file path
    assert len(all_paths) == len(set(all_paths)), (
        f"Duplicate file paths across iterations: {all_paths}"
    )

    # Each file path must encode its iteration number and split label
    for rec in result.iterations:
        if rec.proposal_failed:
            continue
        assert f"iter{rec.iteration}-train" in rec.train_jsonl_path, (
            f"train path missing iter{rec.iteration}: {rec.train_jsonl_path}"
        )
        assert f"iter{rec.iteration}-test" in rec.test_jsonl_path, (
            f"test path missing iter{rec.iteration}: {rec.test_jsonl_path}"
        )
