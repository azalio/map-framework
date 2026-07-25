"""Parallel-aware test harness for merge_wave_worktrees Q6 landmines (#303 Slice 5a).

Drives the REAL merge_wave_worktrees function against real tmp git repos and real
worktrees. Distinct from the sequential tests in test_worktree_isolation.py.

Coverage (five scenarios mapped to VCs):
- VC1: no orphan / unmanaged worktrees after partial failure
- VC2: generated-file conflict rolls back the whole wave (no subset merged)
- VC3: post-wave gate failure rolls back inside the transaction (HC-4)
- VC4a: no-op subtask classified as no_changes, excluded from merge
- VC4b: deterministic merge order by sorted subtask id
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Mirror the import pattern used by test_worktree_isolation.py
SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner as m  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_worktree_isolation.py conventions)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _make_repo(tmp_path: Path, branch: str = "feat/x") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", branch], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "Tester"], repo)
    (repo / "a.txt").write_text("line1\nline2\nline3\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _enable(repo: Path) -> None:
    (repo / ".map").mkdir(exist_ok=True)
    (repo / ".map" / "config.yaml").write_text(
        "worktree.isolation: true\nworktree.max_deletions: 50\n",
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real tmp git repo with worktree isolation enabled; cwd monkeypatched."""
    r = _make_repo(tmp_path)
    _enable(r)
    monkeypatch.chdir(r)
    return r


def _wt_with_files(sid: str, files: dict[str, str]) -> Path:
    """Create a subtask worktree and write files (path -> content) into it."""
    created = m.create_subtask_worktree(sid)
    assert created["status"] == "success", created
    wt = Path(str(created["worktree_path"]))
    for rel, content in files.items():
        (wt / rel).write_text(content, encoding="utf-8")
    return wt


def _live_worktree_paths(repo: Path) -> list[str]:
    """Return all paths reported by 'git worktree list' (includes the main checkout)."""
    result = _git(["worktree", "list", "--porcelain"], repo)
    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(line[len("worktree "):].strip())
    return paths


def _managed_worktree_paths() -> set[str]:
    """Return paths of worktrees recorded in the MAP sidecar (active_worktrees).

    Reads via ``m.worktree_isolation_status()``, which resolves the sidecar from
    the current working directory (the ``repo`` fixture has already chdir'd into
    the tmp repo), so no repo path argument is needed.
    """
    status = m.worktree_isolation_status()
    active = status.get("active_worktrees", [])
    assert isinstance(active, list)
    return {str(w["path"]) for w in active if isinstance(w, dict) and "path" in w}


# ---------------------------------------------------------------------------
# VC1 — no orphan/unmanaged worktrees after partial failure
# ---------------------------------------------------------------------------


def test_vc1_no_orphan_worktrees_on_partial_failure(repo: Path) -> None:
    """After a mid-wave conflict, git worktree list must show NO paths outside the
    main checkout that are not recorded in the MAP sidecar (no stray/unmanaged
    worktrees). The conflicting worktrees are intentionally kept for retry — that
    is correct. HC-4: working branch is rolled back to wave base.
    """
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    # Two subtasks that conflict on a.txt -> mid-wave failure after ST-001 merges
    _wt_with_files("ST-001", {"a.txt": "conflict-from-001\n"})
    _wt_with_files("ST-002", {"a.txt": "conflict-from-002\n"})

    result = m.merge_wave_worktrees(
        ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
    )

    # Function returned an error
    assert result["status"] == "error", result
    assert result["kind"] == "WAVE_MERGE_CONFLICT"

    # HC-4: working branch rolled back to wave base
    head_after = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    assert head_after == base, (
        f"HC-4 violated: working branch head {head_after!r} != base {base!r}"
    )

    # No orphan / unmanaged worktrees: every live worktree (except main checkout)
    # must be registered in the MAP sidecar.
    live_paths = _live_worktree_paths(repo)
    managed_paths = _managed_worktree_paths()
    main_checkout = str(repo.resolve())

    stray = [
        p for p in live_paths
        if p != main_checkout and p not in managed_paths
    ]
    assert stray == [], (
        f"VC1 violated: stray unmanaged worktrees after failure: {stray}. "
        f"Live: {live_paths}. Managed: {managed_paths}"
    )

    # Worktrees kept for retry (both subtasks still registered)
    status = m.worktree_isolation_status()
    active_ids = {w["subtask_id"] for w in status["active_worktrees"]}
    assert "ST-001" in active_ids or "ST-002" in active_ids, (
        "Expected at least one worktree kept for retry, got none"
    )


# ---------------------------------------------------------------------------
# VC2 — generated-file conflict rolls back the WHOLE wave
# ---------------------------------------------------------------------------


def test_vc2_generated_file_conflict_rolls_back_whole_wave(repo: Path) -> None:
    """Two subtasks with disjoint declared affected_files both write conflicting
    content to the same file -> merge conflict -> the function rolls the WHOLE
    wave back (no subset merged) and returns kind=WAVE_MERGE_CONFLICT with
    attribution naming the culprit subtasks.
    """
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    # Both subtasks rewrite the same file with conflicting content.
    # ST-001 goes first (sorted order), ST-002 creates the conflict.
    _wt_with_files("ST-001", {"a.txt": "written-by-001\n"})
    _wt_with_files("ST-002", {"a.txt": "written-by-002\n"})

    result = m.merge_wave_worktrees(
        ["ST-002", "ST-001"], verify_cmds=[], post_wave_cmds=[]
    )

    # Real kind/reason from _wt_error for a merge conflict:
    assert result["status"] == "error"
    assert result["kind"] == "WAVE_MERGE_CONFLICT"
    assert "conflict_files" in result
    assert isinstance(result["conflict_files"], list)
    assert "a.txt" in result["conflict_files"], (
        f"Expected a.txt in conflict_files, got: {result['conflict_files']}"
    )

    # HC-4: NO subset merged — branch back at wave base, no new commits
    head_after = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    assert head_after == base, (
        f"HC-4 violated: subset was merged; head {head_after!r} != base {base!r}"
    )

    # a.txt must not hold either subtask's conflicting content (clean rollback)
    a_content = (repo / "a.txt").read_text()
    assert "written-by-001" not in a_content
    assert "written-by-002" not in a_content

    # Attribution (AC-8): the conflict must be attributed to BOTH culprit
    # subtasks. Both wrote a.txt and both pass PHASE-1 preflight, so both land
    # in `prepared` with a.txt in changed_files -> _wt_attribute_conflict names
    # both. Asserted unconditionally (no `if` guard) so a regression that drops
    # attribution fails the test rather than silently skipping it.
    attribution = result.get("attribution")
    assert isinstance(attribution, list) and attribution, (
        f"Expected non-empty attribution list, got: {attribution!r}"
    )
    attributed_ids = {
        a["subtask_id"] for a in attribution if isinstance(a, dict) and "subtask_id" in a
    }
    assert {"ST-001", "ST-002"} <= attributed_ids, (
        f"AC-8: attribution must name both culprit subtasks; got {attributed_ids}"
    )

    # Worktrees intact for retry
    status = m.worktree_isolation_status()
    slugs = {w["subtask_id"] for w in status["active_worktrees"]}
    assert {"ST-001", "ST-002"} <= slugs, (
        f"Expected both worktrees kept for retry, got: {slugs}"
    )


# ---------------------------------------------------------------------------
# VC3 — post-wave gate failure rolls back inside the transaction (HC-4)
# ---------------------------------------------------------------------------


def test_vc3_post_wave_gate_failure_rolls_back(repo: Path) -> None:
    """Members pass per-worktree verify, the post-wave gate (false) exits non-zero.
    The function rolls the WHOLE wave back to base (HC-4: post-wave gate runs
    INSIDE the transaction, no partial merge survives).
    """
    base = _git(["rev-parse", "HEAD"], repo).stdout.strip()

    _wt_with_files("ST-001", {"b.txt": "from-001\n"})
    _wt_with_files("ST-002", {"c.txt": "from-002\n"})

    # verify_cmds=[] -> per-worktree verify passes; post_wave_cmds=["false"] -> fails
    result = m.merge_wave_worktrees(
        ["ST-001", "ST-002"],
        verify_cmds=[],
        post_wave_cmds=["false"],
    )

    # Real kind from _wt_error for post-wave gate failure:
    assert result["status"] == "error"
    assert result["kind"] == "WAVE_VERIFY_FAILED"

    # HC-4: working branch at wave base — no partial merge survived
    head_after = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    assert head_after == base, (
        f"HC-4 violated: partial merge survived post-wave gate failure; "
        f"head {head_after!r} != base {base!r}"
    )

    # No squash-committed files on the working branch
    assert not (repo / "b.txt").exists(), "b.txt must not exist after rollback"
    assert not (repo / "c.txt").exists(), "c.txt must not exist after rollback"

    # Worktrees intact for retry
    status = m.worktree_isolation_status()
    assert len(status["active_worktrees"]) == 2, (
        f"Expected 2 worktrees kept for retry, got: {status['active_worktrees']}"
    )


# ---------------------------------------------------------------------------
# VC4a — no-op subtask classified as no_changes, excluded from merge
# ---------------------------------------------------------------------------


def test_vc4_noop_classified(repo: Path) -> None:
    """A wave member that produces no commit (no changes in its worktree) is
    classified as no_changes and excluded from the merge, while remaining
    members still merge successfully.
    """
    # ST-001 worktree left empty (no files written) -> no_changes
    m.create_subtask_worktree("ST-001")
    # ST-002 has real changes
    _wt_with_files("ST-002", {"d.txt": "from-002\n"})

    result = m.merge_wave_worktrees(
        ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
    )

    assert result["status"] == "success", result

    # Real field names from merge_wave_worktrees return dict:
    # "merged" -> list[str] of merged subtask ids
    # "no_changes" -> list[str] of no-op subtask ids
    merged_ids = result["merged"]
    no_change_ids = result["no_changes"]

    assert isinstance(merged_ids, list)
    assert isinstance(no_change_ids, list)

    assert "ST-002" in merged_ids, f"ST-002 must be in merged: {merged_ids}"
    assert "ST-001" not in merged_ids, f"ST-001 must NOT be in merged (no-op): {merged_ids}"
    assert "ST-001" in no_change_ids, f"ST-001 must be in no_changes: {no_change_ids}"

    # d.txt landed on the working branch (ST-002 merged successfully)
    assert (repo / "d.txt").exists(), "d.txt must be present after ST-002 merged"

    # Only one squash commit (ST-002); the no-op added none.
    commit_count = _git(["rev-list", "--count", "HEAD"], repo).stdout.strip()
    assert commit_count == "2", (
        f"Expected 2 commits (init + ST-002), got {commit_count}"
    )


# ---------------------------------------------------------------------------
# VC4b — deterministic squash-merge order by sorted subtask id
# ---------------------------------------------------------------------------


def test_vc4_deterministic_merge_order(repo: Path) -> None:
    """The squash-merge order is by SORTED subtask id regardless of the input list
    order. Confirm by checking commit subjects and the "merged" field ordering.
    """
    _wt_with_files("ST-003", {"e.txt": "from-003\n"})
    _wt_with_files("ST-001", {"f.txt": "from-001\n"})
    _wt_with_files("ST-002", {"g.txt": "from-002\n"})

    # Supply ids in reverse order; function must sort before merging.
    result = m.merge_wave_worktrees(
        ["ST-003", "ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
    )
    assert result["status"] == "success", result

    # "merged" field must be in sorted order
    merged_ids = result["merged"]
    assert isinstance(merged_ids, list)
    assert merged_ids == sorted(merged_ids), (
        f"VC4b violated: merged ids are not sorted: {merged_ids}"
    )
    assert merged_ids == ["ST-001", "ST-002", "ST-003"], (
        f"Expected sorted ids, got: {merged_ids}"
    )

    # Commit subjects: newest commit = ST-003 (last merged), oldest new commit = ST-001
    subjects = _git(["log", "-3", "--format=%s"], repo).stdout.strip().splitlines()
    assert subjects[0].startswith("ST-003:"), f"Newest commit should be ST-003, got: {subjects[0]}"
    assert subjects[1].startswith("ST-002:"), f"Second commit should be ST-002, got: {subjects[1]}"
    assert subjects[2].startswith("ST-001:"), f"Third commit should be ST-001, got: {subjects[2]}"
