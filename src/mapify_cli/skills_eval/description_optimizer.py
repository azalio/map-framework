"""Anti-overfit skill description optimizer.

Runs N iterations of description proposal + evaluation, selects the candidate
that maximises held-out TEST pass-rate without overfitting to training data.

Invariants enforced by this module
-----------------------------------
INV-3 / no-anthropic:  no ``import anthropic``, no ANTHROPIC_API_KEY access.
INV-2 / no-datetime:   no ``import datetime``; caller supplies ``run_ts``.
INV-2 / no-random:     no ``import random``; split uses hashlib (deterministic).
INV-2 / clock-free:    timestamp comes from caller (``run_ts`` param), never
                       from ``time.time()`` or ``datetime.now()`` here.
INV-5 / source-untouched:  production .claude/ and templates_src/ are NEVER
                            modified.  Each iteration seeds a throwaway temp dir
                            and cleans it up in a ``finally`` block.
VC1 / anti-overfit:    a candidate with train_pass_rate > baseline.train_pass_rate
                       AND test_pass_rate < baseline.test_pass_rate is flagged
                       ``overfit=True`` and is NEVER selected as the winner.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from mapify_cli.skills_eval.aggregator import aggregate
from mapify_cli.skills_eval.dispatcher import (
    ClaudeSubprocessDispatcher,
    VariantDispatcher,
)
from mapify_cli.skills_eval.eval_schema import (
    EvalResultRecord,
    EvalSetEntry,
    OptimizeIterationRecord,
    OptimizeResult,
    ProposerFn,
)
from mapify_cli.skills_eval.runner import run_eval

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SEED: int = 1337


# ---------------------------------------------------------------------------
# Deterministic train/test split  (VC2 / INV-2 / HC-8)
# ---------------------------------------------------------------------------


def split_train_test(
    entries: list[EvalSetEntry],
    seed: int,
) -> tuple[list[EvalSetEntry], list[EvalSetEntry]]:
    """Return a deterministic (train, test) split.

    Pure function: given identical ``entries`` and ``seed`` the result is
    always the same.  Uses ``hashlib.sha256`` — no ``random``, no ``datetime``.

    Test fraction is ``max(1, round(n * 0.4))`` entries; remainder is train.
    """
    n = len(entries)
    n_test = max(1, round(n * 0.4))
    # Sort indices by hash so the assignment is deterministic and seed-sensitive.
    order = sorted(
        range(n),
        key=lambda i: hashlib.sha256(f"{seed}:{i}".encode()).digest(),
    )
    test_idx: set[int] = set(order[:n_test])
    train = [e for i, e in enumerate(entries) if i not in test_idx]
    test = [e for i, e in enumerate(entries) if i in test_idx]
    return train, test


# ---------------------------------------------------------------------------
# Candidate SKILL.md patching helpers  (VC6 / INV-5)
# ---------------------------------------------------------------------------


def _set_frontmatter_description(content: str, new_desc: str) -> str:
    """Replace the ``description:`` line in YAML frontmatter with ``new_desc``.

    Rules:
    - File MUST start with ``---\\n`` (YAML frontmatter).
    - Frontmatter MUST contain a line starting with ``description:``.
    - The ``description:`` key AND any block-scalar / indented continuation
      lines belonging to it are replaced; all other keys and the body are
      preserved unchanged.
    - ``new_desc`` is serialised as a double-quoted YAML scalar so that
      embedded colons, quotes, and newlines parse back correctly.

    Block-scalar awareness is essential: most shipped skills declare
    ``description: |`` followed by an indented paragraph. Replacing only the
    ``description:`` line (the original behaviour) left the indented body
    orphaned below a now-quoted scalar — invalid YAML that silently unregistered
    the skill, so it never triggered and every eval cell mis-read as a
    non-trigger. We therefore also consume the continuation lines (those indented
    deeper than the key) before substituting the single replacement line.

    Raises ``ValueError`` if the preconditions are not met (fail-loud).
    """
    if not content.startswith("---\n"):
        raise ValueError(
            "SKILL.md content does not start with YAML frontmatter ('---\\n')"
        )

    # Locate the closing --- of the frontmatter block.
    close_idx = content.find("\n---", 4)
    if close_idx == -1:
        raise ValueError("SKILL.md frontmatter has no closing '---'")

    frontmatter = content[4:close_idx]  # between opening and closing ---
    body_after = content[close_idx:]    # from \n--- onward (inclusive)

    # Find the description line inside the frontmatter.
    fm_lines = frontmatter.split("\n")
    desc_line_idx: int | None = None
    for idx, line in enumerate(fm_lines):
        if line.startswith("description:"):
            desc_line_idx = idx
            break

    if desc_line_idx is None:
        raise ValueError(
            "SKILL.md frontmatter does not contain a 'description:' key"
        )

    # Consume the description value's continuation lines: a block scalar
    # (``description: |`` / ``>``) or any plain multi-line value spans the
    # following lines indented deeper than the key. Stop at the next same-or-less
    # indented key (e.g. ``effort:``) or a blank line.
    key_line = fm_lines[desc_line_idx]
    key_indent = len(key_line) - len(key_line.lstrip())
    end_idx = desc_line_idx + 1
    while end_idx < len(fm_lines):
        cont = fm_lines[end_idx]
        if cont.strip() == "":
            break
        cont_indent = len(cont) - len(cont.lstrip())
        if cont_indent <= key_indent:
            break
        end_idx += 1

    # Serialise new_desc as a double-quoted YAML scalar so round-trip is safe.
    escaped = new_desc.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    new_line = f'{" " * key_indent}description: "{escaped}"'
    # Replace the key line + its consumed continuation lines with the single line.
    fm_lines[desc_line_idx:end_idx] = [new_line]

    new_frontmatter = "\n".join(fm_lines)
    return "---\n" + new_frontmatter + body_after


def _patch_candidate_skill_md(
    cand_claude_dir: Path,
    skill: str,
    new_desc: str,
) -> None:
    """Overwrite the ``description:`` in the candidate's ``SKILL.md``.

    Intent: mutate the throwaway copy only; production files are never touched.
    Raises ``FileNotFoundError`` if the skill's SKILL.md is absent.
    """
    skill_md = cand_claude_dir / "skills" / skill / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"Candidate SKILL.md not found at {skill_md}; "
            "source_claude_dir may be missing the skill."
        )
    original = skill_md.read_text(encoding="utf-8")
    patched = _set_frontmatter_description(original, new_desc)
    skill_md.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------------------
# Token total helper
# ---------------------------------------------------------------------------


def _sum_tokens(records: list[EvalResultRecord]) -> int:
    """Sum ``token_usage.total`` over records that have token_usage."""
    return sum(r.token_usage.total for r in records if r.token_usage is not None)


# ---------------------------------------------------------------------------
# Baseline failing record loader (proposer input helper)
# ---------------------------------------------------------------------------


def _load_baseline_failing(
    baseline_rec: OptimizeIterationRecord,
) -> list[EvalResultRecord]:
    """Load train records from the baseline's .jsonl and return only failing ones.

    Returns an empty list if the path is empty or the file cannot be read
    (fail-soft: the proposer receives an empty list rather than crashing).
    """
    path_str = baseline_rec.train_jsonl_path
    if not path_str:
        return []

    path = Path(path_str)
    if not path.exists():
        return []

    records: list[EvalResultRecord] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    rec = EvalResultRecord.from_dict(d)
                    if rec.assertions_failed:
                        records.append(rec)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
    except OSError:
        pass

    return records


# ---------------------------------------------------------------------------
# Single-iteration runner
# ---------------------------------------------------------------------------


def _run_one_iteration(
    *,
    iteration: int,
    candidate_description: str,
    skill: str,
    train: list[EvalSetEntry],
    test: list[EvalSetEntry],
    dispatcher: VariantDispatcher | None,
    source_claude_dir: Path,
    out_dir: Path,
    run_ts: str,
) -> OptimizeIterationRecord:
    """Seed a throwaway temp dir, patch the description, run train+test.

    Always cleans up the temp dir in ``finally`` (INV-5).
    VC3: writes to distinct paths per (iteration, split); resume=False always.
    """
    # VC3: distinct paths per (iteration, split)
    train_path = out_dir / f"{run_ts}-optimize-iter{iteration}-train.jsonl"
    test_path = out_dir / f"{run_ts}-optimize-iter{iteration}-test.jsonl"

    cand_root = Path(tempfile.mkdtemp(prefix="mapeval-candidate-"))
    try:
        # Seed the candidate .claude/ tree from production source
        cand_claude = cand_root / ".claude"
        shutil.copytree(source_claude_dir, cand_claude)

        # Patch the description in the throwaway copy only (INV-5)
        _patch_candidate_skill_md(cand_claude, skill, candidate_description)

        # Dispatcher: injected (tests) or fresh production dispatcher
        if dispatcher is not None:
            iter_dispatcher: VariantDispatcher = dispatcher
        else:
            iter_dispatcher = ClaudeSubprocessDispatcher(
                source_claude_dir=cand_claude,
            )

        # VC3: resume=False — always write fresh cells, never resume
        train_records = run_eval(
            skill=skill,
            entries=train,
            dispatcher=iter_dispatcher,
            runs=1,
            out_path=train_path,
            resume=False,
        )
        test_records = run_eval(
            skill=skill,
            entries=test,
            dispatcher=iter_dispatcher,
            runs=1,
            out_path=test_path,
            resume=False,
        )
    finally:
        shutil.rmtree(cand_root, ignore_errors=True)

    train_summary = aggregate(train_records)
    test_summary = aggregate(test_records)

    return OptimizeIterationRecord(
        iteration=iteration,
        candidate_description=candidate_description,
        train_pass_rate=train_summary.pass_rate,
        test_pass_rate=test_summary.pass_rate,
        train_tokens_total=_sum_tokens(train_records),
        test_tokens_total=_sum_tokens(test_records),
        train_jsonl_path=str(train_path),
        test_jsonl_path=str(test_path),
    )


# ---------------------------------------------------------------------------
# Overfit flagging and selection  (VC1 / D4 / INV-4)
# ---------------------------------------------------------------------------


def _flag_overfit(
    record: OptimizeIterationRecord,
    baseline: OptimizeIterationRecord,
) -> None:
    """Set ``overfit=True`` in-place when the anti-overfit condition holds.

    Overfit iff: iter > 0, not proposal_failed,
    train improved vs baseline AND test regressed vs baseline.
    """
    if (
        record.iteration != 0
        and not record.proposal_failed
        and record.train_pass_rate > baseline.train_pass_rate
        and record.test_pass_rate < baseline.test_pass_rate
    ):
        record.overfit = True


def _select_winner(
    iteration_records: list[OptimizeIterationRecord],
) -> tuple[OptimizeIterationRecord, bool]:
    """Return ``(winner, no_improvement)`` from the completed iteration list.

    Selection rules (D4):
    1. Strict candidates: non-baseline, not proposal_failed, test_pass_rate
       strictly greater than baseline.test_pass_rate.
    2. If no strict candidates: winner = baseline (iter 0), no_improvement=True.
    3. Tie-break: (-test_pass_rate, total_tokens, iteration) ascending.
    4. Full-tie across all iterations: baseline wins, no_improvement=True.
    """
    baseline = iteration_records[0]
    strict = [
        it
        for it in iteration_records[1:]
        if not it.proposal_failed and it.test_pass_rate > baseline.test_pass_rate
    ]
    if not strict:
        return baseline, True

    winner = min(
        strict,
        key=lambda it: (
            -it.test_pass_rate,
            it.train_tokens_total + it.test_tokens_total,
            it.iteration,
        ),
    )
    return winner, False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimize(
    *,
    skill: str,
    entries: list[EvalSetEntry],
    current_description: str,
    proposer: ProposerFn,
    dispatcher: VariantDispatcher | None = None,
    source_claude_dir: Path,
    out_dir: Path,
    run_ts: str,
    iterations: int = 5,
    seed: int = _DEFAULT_SEED,
) -> OptimizeResult:
    """Run N-iteration description optimization; return the best candidate.

    Parameters
    ----------
    skill:
        Name of the skill whose SKILL.md ``description:`` is being optimised.
    entries:
        Full entry list; split internally into train/test via ``split_train_test``.
    current_description:
        Baseline description (iteration 0).
    proposer:
        Callable receiving (current_description, baseline_failing_train_records)
        and returning a new candidate string or ``None`` on exhaustion/failure.
    dispatcher:
        Optional injected dispatcher.  ``None`` => production subprocess path.
    source_claude_dir:
        Production ``.claude/`` directory to seed throwaway candidates from.
    out_dir:
        Directory for per-iteration ``.jsonl`` result files.
    run_ts:
        Caller-supplied timestamp string (clock-free invariant: never generated here).
    iterations:
        Total iterations including baseline (iter 0).  Must be >= 1.
    seed:
        Integer seed for the deterministic split.

    Returns
    -------
    OptimizeResult
        Full result.  ``eval_set_path`` is ``""`` — the CLI owns that field.

    Raises
    ------
    ValueError
        If ``iterations < 1`` (there must be at least the baseline iteration).
    """
    if iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations}")

    out_dir.mkdir(parents=True, exist_ok=True)
    train, test = split_train_test(entries, seed)

    iteration_records: list[OptimizeIterationRecord] = []
    # Baseline failing train records fed to the proposer from iteration 1 onward.
    baseline_failing: list[EvalResultRecord] = []

    for i in range(iterations):
        if i == 0:
            # Baseline: patch for uniformity; description = current_description
            candidate_description: str = current_description
        else:
            proposed = proposer(current_description, baseline_failing)
            if not proposed:
                # VC4: proposal_failed iteration; no run_eval call; loop continues
                failed_rec = OptimizeIterationRecord(
                    iteration=i,
                    candidate_description=None,
                    train_pass_rate=0.0,
                    test_pass_rate=0.0,
                    proposal_failed=True,
                )
                iteration_records.append(failed_rec)
                continue
            candidate_description = proposed

        rec = _run_one_iteration(
            iteration=i,
            candidate_description=candidate_description,
            skill=skill,
            train=train,
            test=test,
            dispatcher=dispatcher,
            source_claude_dir=source_claude_dir,
            out_dir=out_dir,
            run_ts=run_ts,
        )

        if i == 0:
            # Capture baseline failing train records for proposer input
            baseline_failing = _load_baseline_failing(rec)

        iteration_records.append(rec)

    # Flag overfit candidates against the baseline
    if iteration_records:
        baseline_rec = iteration_records[0]
        for rec in iteration_records[1:]:
            _flag_overfit(rec, baseline_rec)

    winner, no_improvement = _select_winner(iteration_records)
    winner.selected = True

    if winner.iteration == 0 or winner.candidate_description is None:
        winning_description = current_description
    else:
        winning_description = winner.candidate_description

    return OptimizeResult(
        skill=skill,
        eval_set_path="",
        seed=seed,
        n_train=len(train),
        n_test=len(test),
        baseline_description=current_description,
        winning_description=winning_description,
        winning_iteration=winner.iteration,
        no_improvement=no_improvement,
        iterations=iteration_records,
    )
