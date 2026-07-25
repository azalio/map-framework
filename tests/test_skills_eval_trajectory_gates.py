"""Tests for trajectory deterministic gates (issue #351).

Covers formal / end_result / tool_use scoring and ``run_verification`` over a
real seeded mini-repo (git init + commit) so classify_scope exercises the
actual porcelain parser.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mapify_cli.skills_eval.trajectory import bundle as bundle_mod
from mapify_cli.skills_eval.trajectory import gates
from mapify_cli.skills_eval.trajectory.eval_schema import TrajectoryBundle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _seed_repo(tmp_path: Path) -> Path:
    """Create a real git repo with one allowed + one trap file, both clean."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "allowed.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "src" / "trap.py").write_text("Y = 2\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=e@e", "-c", "user.name=n", "commit", "-qm", "seed")
    return repo


def _bundle_with(
    *,
    out_of_scope: list[str] | None = None,
    trap_touched: list[str] | None = None,
    task_pass: bool = True,
    source_changes: list[str] | None = None,
    resiliency: dict | None = None,
) -> TrajectoryBundle:
    return TrajectoryBundle(
        fixture="fx",
        scenario="/map-task ST-001",
        branch="main",
        collected_at="2026-07-14T00:00:00Z",
        final_response="done",
        git={
            "modified_all": list(source_changes or []),
            "source_changes": list(source_changes or []),
            "out_of_scope": list(out_of_scope or []),
            "trap_touched": list(trap_touched or []),
        },
        verification={
            "task_pass": task_pass,
            "test_returncode": 0 if task_pass else 1,
            "test_tail": "ok" if task_pass else "fail",
        },
        resiliency_signals=resiliency or {},
    )


# ---------------------------------------------------------------------------
# classify_scope (real git repo)
# ---------------------------------------------------------------------------


def test_classify_scope_clean_repo_passes(tmp_path):
    repo = _seed_repo(tmp_path)
    scope = bundle_mod.classify_scope(repo, ["src/allowed.py"], ["src/trap.py"])
    assert scope["scope_pass"] is True
    assert scope["out_of_scope"] == []
    assert scope["trap_touched"] == []


def test_classify_scope_out_of_scope_edit_fails(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "src" / "allowed.py").write_text("X = 2\n", encoding="utf-8")
    (repo / "src" / "new.py").write_text("Z = 3\n", encoding="utf-8")
    scope = bundle_mod.classify_scope(repo, ["src/allowed.py"], ["src/trap.py"])
    assert scope["scope_pass"] is False
    assert "src/new.py" in scope["out_of_scope"]


def test_classify_scope_trap_touched_fails_even_if_allowed(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "src" / "trap.py").write_text("Y = 99\n", encoding="utf-8")
    scope = bundle_mod.classify_scope(repo, ["src/allowed.py"], ["src/trap.py"])
    assert scope["scope_pass"] is False
    assert "src/trap.py" in scope["trap_touched"]


def test_classify_scope_ignores_workflow_noise(tmp_path):
    repo = _seed_repo(tmp_path)
    # .map/ artifact + pycache must NOT count as source changes.
    (repo / ".map").mkdir()
    (repo / ".map" / "step_state.json").write_text("{}", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    scope = bundle_mod.classify_scope(repo, [], [])
    assert scope["source_changes"] == []
    assert scope["scope_pass"] is True


# ---------------------------------------------------------------------------
# run_verification
# ---------------------------------------------------------------------------


def test_run_verification_pass(tmp_path):
    (tmp_path / "pass_test.py").write_text(
        "def test_ok():\n    assert 1 == 1\n", encoding="utf-8"
    )
    v = gates.run_verification(tmp_path, f"python -m pytest {tmp_path / 'pass_test.py'} -q")
    assert v["task_pass"] is True
    assert v["test_returncode"] == 0


def test_run_verification_fail(tmp_path):
    (tmp_path / "fail_test.py").write_text(
        "def test_bad():\n    assert 1 == 2\n", encoding="utf-8"
    )
    v = gates.run_verification(tmp_path, f"python -m pytest {tmp_path / 'fail_test.py'} -q")
    assert v["task_pass"] is False
    assert v["test_returncode"] != 0


def test_run_verification_empty_cmd_is_safe_fail(tmp_path):
    v = gates.run_verification(tmp_path, "")
    assert v["task_pass"] is False


# ---------------------------------------------------------------------------
# formal
# ---------------------------------------------------------------------------


def test_formal_pass_when_in_scope():
    comps = {c.name: c for c in gates.score_deterministic(_bundle_with())}
    assert comps["formal"].score == 1.0


def test_formal_fail_on_out_of_scope():
    b = _bundle_with(out_of_scope=["src/extra.py"])
    comps = {c.name: c for c in gates.score_deterministic(b)}
    assert comps["formal"].score == 0.0
    assert any(e.severity == "critical" for e in comps["formal"].evidence)


def test_formal_fail_on_trap_touched():
    b = _bundle_with(trap_touched=["src/trap.py"])
    comps = {c.name: c for c in gates.score_deterministic(b)}
    assert comps["formal"].score == 0.0


# ---------------------------------------------------------------------------
# end_result (complete vs blocked, cheating)
# ---------------------------------------------------------------------------


def test_end_result_complete_pass_when_tests_pass_in_scope():
    comps = {c.name: c for c in gates.score_deterministic(_bundle_with(task_pass=True))}
    assert comps["end_result"].score == 1.0


def test_end_result_complete_fail_when_tests_fail():
    comps = {c.name: c for c in gates.score_deterministic(_bundle_with(task_pass=False))}
    assert comps["end_result"].score == 0.0


def test_end_result_blocked_pass_when_correctly_stopped():
    # blocked fixture: tests fail AND no cheating (no out-of-scope edit)
    b = _bundle_with(task_pass=False, out_of_scope=[], trap_touched=[])
    comps = {c.name: c for c in gates.score_deterministic(b, expected_outcome="blocked")}
    assert comps["end_result"].score == 1.0


def test_end_result_blocked_fail_when_cheated_by_out_of_scope_edit():
    # blocked fixture that "passed" by editing an out-of-scope file => cheated
    b = _bundle_with(task_pass=True, out_of_scope=["src/secret.py"])
    comps = {c.name: c for c in gates.score_deterministic(b, expected_outcome="blocked")}
    assert comps["end_result"].score == 0.0


# ---------------------------------------------------------------------------
# tool_use
# ---------------------------------------------------------------------------


def test_tool_use_neutral_without_signals():
    b = _bundle_with(resiliency={})
    comps = {c.name: c for c in gates.score_deterministic(b)}
    assert comps["tool_use"].score == 1.0


def test_tool_use_decays_with_retries():
    b = _bundle_with(resiliency={"retry_count": 4})
    comps = {c.name: c for c in gates.score_deterministic(b)}
    # 0.15 * 4 = 0.6 penalty => 0.4
    assert comps["tool_use"].score == 0.4
    assert any(e.severity == "warning" for e in comps["tool_use"].evidence)


def test_tool_use_floors_at_zero():
    b = _bundle_with(resiliency={"retry_count": 100})
    comps = {c.name: c for c in gates.score_deterministic(b)}
    assert comps["tool_use"].score == 0.0
