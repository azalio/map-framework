"""Per-subtask git worktree isolation (#284) and parallel wave execution (#303).

Two layers:
- Config: the MapConfig fields, dotted-key YAML aliasing (`worktree.*` /
  `execution.*` -> snake_case), enum validation, backward-compat bool migration,
  and the generated default-config doc.
- Runtime: the step-runner lifecycle (create/merge/discard/status), the
  disabled no-op path, and every council-mandated safety guard, exercised
  against real throwaway git repos.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mapify_cli.config.project_config import (
    VALID_WAVE_MODE,
    VALID_WORKTREE_ISOLATION,
    MapConfig,
    generate_default_config,
    load_map_config,
)

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


# --------------------------------------------------------------------------- #
# Config layer
# --------------------------------------------------------------------------- #
def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


class TestWorktreeConfig:
    def test_defaults_auto(self) -> None:
        """Slice 6: worktree_isolation default flipped from 'off' to 'auto'."""
        cfg = MapConfig()
        assert cfg.worktree_isolation == "auto"
        assert cfg.worktree_max_deletions == 50

    def test_absent_config_uses_defaults(self, tmp_path: Path) -> None:
        """Slice 6: absent config → 'auto' (Slice 6 default, not 'off')."""
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "auto"
        assert cfg.worktree_max_deletions == 50

    def test_dotted_keys_alias_to_fields(self, tmp_path: Path) -> None:
        # YAML `true` is a bool in Python; the backward-compat migration maps it
        # to the enum string "required".
        _write_config(
            tmp_path, "worktree.isolation: true\nworktree.max_deletions: 7\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "required"
        assert cfg.worktree_max_deletions == 7

    def test_negative_max_deletions_falls_back(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "worktree.max_deletions: -3\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_max_deletions == 50

    def test_zero_max_deletions_preserved(self, tmp_path: Path) -> None:
        # 0 is a valid value (disables the guard) — must NOT fall back to 50.
        _write_config(tmp_path, "worktree.max_deletions: 0\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_max_deletions == 0

    def test_wrong_type_isolation_ignored(self, tmp_path: Path) -> None:
        # An unknown string is not a valid enum value -> falls back to "off".
        _write_config(tmp_path, "worktree.isolation: notanenum\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "off"

    def test_generated_config_documents_keys(self) -> None:
        body = generate_default_config(include_comments=True)
        assert "worktree.isolation: off" in body
        assert "worktree.max_deletions" in body

    # ------------------------------------------------------------------ #
    # Enum string values
    # ------------------------------------------------------------------ #
    @pytest.mark.parametrize("value", sorted(VALID_WORKTREE_ISOLATION))
    def test_valid_isolation_enum_values_accepted(
        self, tmp_path: Path, value: str
    ) -> None:
        _write_config(tmp_path, f"worktree.isolation: {value}\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == value

    # ------------------------------------------------------------------ #
    # Backward-compat: YAML bool -> string migration
    # ------------------------------------------------------------------ #
    def test_bool_false_migrates_to_off(self, tmp_path: Path) -> None:
        # YAML `false` is parsed as Python False by yaml.safe_load.
        # load_map_config migrates it to the new enum string "off".
        _write_config(tmp_path, "worktree.isolation: false\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "off"

    def test_bool_true_migrates_to_required(self, tmp_path: Path) -> None:
        # YAML `true` is parsed as Python True by yaml.safe_load.
        # load_map_config migrates it to "required" (the strict opt-in).
        _write_config(tmp_path, "worktree.isolation: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation == "required"


# --------------------------------------------------------------------------- #
# execution_wave_mode config (#303 Slice 0)
# --------------------------------------------------------------------------- #
class TestWaveModeConfig:
    def test_default_is_auto(self) -> None:
        cfg = MapConfig()
        assert cfg.execution_wave_mode == "auto"

    def test_absent_config_uses_default(self, tmp_path: Path) -> None:
        cfg = load_map_config(tmp_path)
        assert cfg.execution_wave_mode == "auto"

    @pytest.mark.parametrize("value", sorted(VALID_WAVE_MODE))
    def test_valid_wave_mode_values_accepted(
        self, tmp_path: Path, value: str
    ) -> None:
        _write_config(tmp_path, f"execution.wave_mode: {value}\n")
        cfg = load_map_config(tmp_path)
        assert cfg.execution_wave_mode == value

    def test_invalid_wave_mode_falls_back_to_auto(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "execution.wave_mode: superfast\n")
        cfg = load_map_config(tmp_path)
        assert cfg.execution_wave_mode == "auto"

    def test_yaml11_off_bool_migrates_to_string(self, tmp_path: Path) -> None:
        # YAML 1.1 parses bare `off` as Python False.  load_map_config must
        # coerce it back to the string "off" before the type-check loop.
        _write_config(tmp_path, "execution.wave_mode: off\n")
        cfg = load_map_config(tmp_path)
        assert cfg.execution_wave_mode == "off"

    def test_yaml11_on_bool_migrates_to_string(self, tmp_path: Path) -> None:
        # YAML 1.1 parses bare `on` as Python True.  load_map_config must
        # coerce it to "on".
        _write_config(tmp_path, "execution.wave_mode: on\n")
        cfg = load_map_config(tmp_path)
        assert cfg.execution_wave_mode == "on"

    def test_generated_config_documents_wave_mode(self) -> None:
        body = generate_default_config(include_comments=True)
        assert "execution.wave_mode: auto" in body


# --------------------------------------------------------------------------- #
# Runtime layer — real git repos
# --------------------------------------------------------------------------- #
def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _make_repo(tmp_path: Path, branch: str = "feat/x") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", branch], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "Tester"], repo)
    (repo / "a.txt").write_text("hello\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _enable(repo: Path, *, max_deletions: int = 50) -> None:
    (repo / ".map").mkdir(exist_ok=True)
    (repo / ".map" / "config.yaml").write_text(
        f"worktree.isolation: true\nworktree.max_deletions: {max_deletions}\n",
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = _make_repo(tmp_path)
    _enable(r)
    monkeypatch.chdir(r)
    return r


class TestWorktreeDisabled:
    def test_create_noops_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legacy bool 'false' maps to 'off' → create returns status='disabled'."""
        r = _make_repo(tmp_path)
        (r / ".map").mkdir()
        (r / ".map" / "config.yaml").write_text("worktree.isolation: false\n")
        monkeypatch.chdir(r)
        result = m.create_subtask_worktree("ST-001")
        assert result["status"] == "disabled"
        assert result["ok"] is False

    def test_create_noops_when_explicit_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit 'worktree.isolation: off' (per-repo opt-out) → status='disabled'.

        Slice 6: replaced the old 'no config → disabled' test — without config the
        default is now 'auto' (ON), so no-config produces a success (worktree created).
        The per-repo opt-out uses the explicit 'off' enum value.
        """
        r = _make_repo(tmp_path)
        (r / ".map").mkdir()
        (r / ".map" / "config.yaml").write_text("worktree.isolation: off\n")
        monkeypatch.chdir(r)
        result = m.create_subtask_worktree("ST-001")
        assert result["status"] == "disabled"
        assert result["ok"] is False


class TestWorktreeLifecycle:
    def test_create_merge_happy_path(self, repo: Path) -> None:
        created = m.create_subtask_worktree("ST-001")
        assert created["status"] == "success"
        wt = Path(str(created["worktree_path"]))
        assert wt.is_dir()
        assert str(created["worktree_branch"]) == "map-wt/ST-001-0"
        # worktree is stored OUT of the working tree (under the git common dir)
        assert ".git" in str(wt)
        assert "map-framework/worktrees" in str(wt).replace("\\", "/")

        (wt / "b.txt").write_text("world\n")
        (wt / "a.txt").write_text("hello-edited\n")

        merged = m.merge_subtask_worktree("ST-001", verify_cmds=[])
        assert merged["status"] == "success"
        assert merged["merged"] is True
        assert merged["no_changes"] is False
        # the change landed on the working branch as exactly ONE squash commit
        assert (repo / "b.txt").read_text().strip() == "world"
        count = _git(["rev-list", "--count", "HEAD"], repo).stdout.strip()
        assert count == "2"  # init + one squash commit
        # worktree removed + branch deleted
        assert not wt.exists()
        assert "map-wt/ST-001-0" not in _git(["branch"], repo).stdout

    @pytest.mark.usefixtures("repo")
    def test_pre_merge_verify_passes_in_worktree(self) -> None:
        created = m.create_subtask_worktree("ST-002")
        (Path(str(created["worktree_path"])) / "b.txt").write_text("x\n")
        merged = m.merge_subtask_worktree(
            "ST-002", verify_cmds=['bash -lc "test -f b.txt"']
        )
        assert merged["status"] == "success"
        verification = merged["verification"]
        assert isinstance(verification, dict)
        assert verification["status"] == "passed"

    @pytest.mark.usefixtures("repo")
    def test_status_reports_active_and_enabled(self) -> None:
        m.create_subtask_worktree("ST-003")
        st = m.worktree_isolation_status()
        assert st["enabled"] is True
        active = st["active_worktrees"]
        assert isinstance(active, list)
        assert any(w["subtask_id"] == "ST-003" for w in active)

    def test_discard_removes_worktree_without_touching_main(self, repo: Path) -> None:
        created = m.create_subtask_worktree("ST-004")
        wt = Path(str(created["worktree_path"]))
        (wt / "leak.txt").write_text("should-not-merge\n")
        head_before = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        result = m.discard_subtask_worktree("ST-004", save_patch=True)
        assert result["discarded"] is True
        assert result["patch_path"] is not None
        assert not wt.exists()
        assert not (repo / "leak.txt").exists()
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() == head_before

    @pytest.mark.usefixtures("repo")
    def test_discard_is_idempotent(self) -> None:
        result = m.discard_subtask_worktree("never-created")
        assert result["status"] == "success"
        assert result["discarded"] is False

    @pytest.mark.usefixtures("repo")
    def test_create_is_crash_safe_recreate(self) -> None:
        first = m.create_subtask_worktree("ST-005")
        wt = Path(str(first["worktree_path"]))
        (wt / "stale.txt").write_text("stale\n")
        # Re-create without discarding (simulates crash recovery): clean slate.
        second = m.create_subtask_worktree("ST-005")
        assert second["status"] == "success"
        assert not (Path(str(second["worktree_path"])) / "stale.txt").exists()


class TestWorktreeGuards:
    def test_verify_failure_leaves_main_untouched(self, repo: Path) -> None:
        created = m.create_subtask_worktree("ST-010")
        (Path(str(created["worktree_path"])) / "b.txt").write_text("x\n")
        head_before = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        result = m.merge_subtask_worktree("ST-010", verify_cmds=['bash -lc "exit 3"'])
        assert result["status"] == "error"
        assert result["kind"] == "VERIFY_FAILED"
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() == head_before
        assert not (repo / "b.txt").exists()

    def test_bulk_deletion_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = _make_repo(tmp_path)
        _enable(r, max_deletions=2)
        monkeypatch.chdir(r)
        for i in range(5):
            (r / f"f{i}.txt").write_text("x\n")
        _git(["add", "-A"], r)
        _git(["commit", "-q", "-m", "files"], r)
        created = m.create_subtask_worktree("ST-011")
        for i in range(5):
            (Path(str(created["worktree_path"])) / f"f{i}.txt").unlink()
        result = m.merge_subtask_worktree("ST-011", verify_cmds=[])
        assert result["kind"] == "BULK_DELETION"
        assert result["deleted_count"] == 5

    def test_bulk_deletion_threshold_zero_disables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = _make_repo(tmp_path)
        _enable(r, max_deletions=0)
        monkeypatch.chdir(r)
        for i in range(3):
            (r / f"f{i}.txt").write_text("x\n")
        _git(["add", "-A"], r)
        _git(["commit", "-q", "-m", "files"], r)
        created = m.create_subtask_worktree("ST-012")
        for i in range(3):
            (Path(str(created["worktree_path"])) / f"f{i}.txt").unlink()
        result = m.merge_subtask_worktree("ST-012", verify_cmds=[])
        assert result["status"] == "success"

    def test_base_divergence_blocks_merge(self, repo: Path) -> None:
        created = m.create_subtask_worktree("ST-013")
        (Path(str(created["worktree_path"])) / "b.txt").write_text("x\n")
        # main advances independently after the worktree was created
        (repo / "ext.txt").write_text("ext\n")
        _git(["add", "-A"], repo)
        _git(["commit", "-q", "-m", "external"], repo)
        result = m.merge_subtask_worktree("ST-013", verify_cmds=[])
        assert result["kind"] == "BASE_DIVERGED"

    def test_protected_ref_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = _make_repo(tmp_path, branch="main")
        _enable(r)
        monkeypatch.chdir(r)
        result = m.create_subtask_worktree("ST-014")
        assert result["kind"] == "PROTECTED_REF"

    def test_dirty_main_refused(self, repo: Path) -> None:
        (repo / "a.txt").write_text("uncommitted-edit\n")
        result = m.create_subtask_worktree("ST-015")
        assert result["kind"] == "DIRTY_MAIN"

    def test_dirty_main_allow_override(self, repo: Path) -> None:
        (repo / "a.txt").write_text("uncommitted-edit\n")
        result = m.create_subtask_worktree("ST-016", allow_dirty=True)
        assert result["status"] == "success"

    def test_runtime_state_does_not_count_as_dirty(self, repo: Path) -> None:
        # MAP's own state writes (.map/<branch>/...) must never trip dirty-main.
        branch_dir = repo / ".map" / "feat-x"
        branch_dir.mkdir(parents=True, exist_ok=True)
        (branch_dir / "step_state.json").write_text("{}\n")
        result = m.create_subtask_worktree("ST-017")
        assert result["status"] == "success"

    @pytest.mark.usefixtures("repo")
    @pytest.mark.parametrize("bad", ["../../evil", "a/b", "..", r"a\b", "HEAD"])
    def test_invalid_subtask_id_rejected(self, bad: str) -> None:
        assert m.create_subtask_worktree(bad)["kind"] == "INVALID_SUBTASK_ID"

    @pytest.mark.usefixtures("repo")
    def test_no_changes_when_actor_ignores_worktree(self) -> None:
        # Actor edited the main tree instead of the worktree -> empty worktree.
        m.create_subtask_worktree("ST-018")
        result = m.merge_subtask_worktree("ST-018", verify_cmds=[])
        assert result["status"] == "success"
        assert result["no_changes"] is True
        assert result["merged"] is False

    @pytest.mark.usefixtures("repo")
    def test_merge_without_create_errors(self) -> None:
        assert m.merge_subtask_worktree("ST-019", verify_cmds=[])["kind"] == "NO_WORKTREE"


# --------------------------------------------------------------------------- #
# Wave merge coordinator (#284 Phase 2 — parallel wave / DAG)
# --------------------------------------------------------------------------- #
def _wt_with_files(sid: str, files: dict[str, str]) -> Path:
    """Create a subtask worktree and write `files` (path -> content) into it."""
    created = m.create_subtask_worktree(sid)
    assert created["status"] == "success", created
    wt = Path(str(created["worktree_path"]))
    for rel, content in files.items():
        (wt / rel).write_text(content, encoding="utf-8")
    return wt


class TestWaveWorktreeMerge:
    def test_no_subtasks_errors(self, repo: Path) -> None:
        del repo
        assert m.merge_wave_worktrees([])["kind"] == "NO_SUBTASKS"

    def test_unknown_subtask_errors(self, repo: Path) -> None:
        del repo
        result = m.merge_wave_worktrees(["ST-404"])
        assert result["kind"] == "NO_WORKTREE"

    def test_happy_path_two_disjoint_subtasks(self, repo: Path) -> None:
        base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        _wt_with_files("ST-001", {"b.txt": "from-001\n"})
        _wt_with_files("ST-002", {"c.txt": "from-002\n"})

        result = m.merge_wave_worktrees(
            ["ST-002", "ST-001"], verify_cmds=[], post_wave_cmds=[]
        )
        assert result["status"] == "success", result
        # Deterministic sorted merge order regardless of input order.
        assert result["merged"] == ["ST-001", "ST-002"]
        assert result["merged_count"] == 2
        # Both disjoint files landed on the working branch.
        assert (repo / "b.txt").read_text().strip() == "from-001"
        assert (repo / "c.txt").read_text().strip() == "from-002"
        # Exactly TWO squash commits (one per subtask) on top of init.
        assert _git(["rev-list", "--count", "HEAD"], repo).stdout.strip() == "3"
        # Commit subjects carry the subtask ids in sorted order (newest first).
        subjects = _git(["log", "-2", "--format=%s"], repo).stdout.split("\n")
        assert subjects[0].startswith("ST-002:")
        assert subjects[1].startswith("ST-001:")
        # HEAD advanced past the wave base.
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() != base
        # Worktrees cleaned up + sidecar emptied.
        status = m.worktree_isolation_status()
        assert status["active_worktrees"] == []
        assert "map-wt/ST-001-0" not in _git(["branch"], repo).stdout
        assert "map-wt/ST-002-0" not in _git(["branch"], repo).stdout

    def test_conflict_rolls_whole_wave_back(self, repo: Path) -> None:
        base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        # Both subtasks rewrite the SAME line of a.txt differently -> real
        # textual conflict on the second squash-merge.
        _wt_with_files("ST-001", {"a.txt": "conflict-from-001\n"})
        _wt_with_files("ST-002", {"a.txt": "conflict-from-002\n"})

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
        )
        assert result["status"] == "error"
        assert result["kind"] == "WAVE_MERGE_CONFLICT"
        assert result["subtask_id"] == "ST-002"
        assert "a.txt" in result["conflict_files"]
        # Attribution names the culprits that touched a.txt.
        attributed = {a["subtask_id"] for a in result["attribution"]}
        assert "ST-002" in attributed
        # All-or-nothing: working branch is back at the wave base, tree clean.
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() == base
        porcelain = [
            ln
            for ln in _git(["status", "--porcelain"], repo).stdout.splitlines()
            if ln.strip() and ".map" not in ln
        ]
        assert porcelain == [], porcelain
        # No MERGE_HEAD left behind (squash merge has none; abort would error).
        assert not (repo / ".git" / "MERGE_HEAD").exists()
        # Worktrees left intact for retry.
        status = m.worktree_isolation_status()
        slugs = {w["subtask_id"] for w in status["active_worktrees"]}
        assert {"ST-001", "ST-002"} <= slugs

    def test_external_head_movement_refused(self, repo: Path) -> None:
        _wt_with_files("ST-001", {"b.txt": "x\n"})
        _wt_with_files("ST-002", {"c.txt": "y\n"})
        # An external commit advances HEAD past the wave base.
        (repo / "external.txt").write_text("outside the wave\n")
        _git(["add", "external.txt"], repo)
        _git(["commit", "-q", "-m", "external"], repo)

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
        )
        assert result["kind"] == "EXTERNAL_HEAD_MOVED"
        # No merge attempted: the external commit is still HEAD, files unmerged.
        assert not (repo / "b.txt").exists()

    def test_post_wave_gate_failure_rolls_back(self, repo: Path) -> None:
        base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        _wt_with_files("ST-001", {"b.txt": "x\n"})
        _wt_with_files("ST-002", {"c.txt": "y\n"})

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"],
            verify_cmds=[],
            post_wave_cmds=['bash -lc "exit 7"'],
        )
        assert result["kind"] == "WAVE_VERIFY_FAILED"
        assert result["returncode"] == 7
        # Atomic rollback: branch at base, no squash commits survived.
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() == base
        assert not (repo / "b.txt").exists()
        assert not (repo / "c.txt").exists()
        # Worktrees intact for retry.
        status = m.worktree_isolation_status()
        assert len(status["active_worktrees"]) == 2

    def test_post_wave_gate_pass_accepts(self, repo: Path) -> None:
        _wt_with_files("ST-001", {"b.txt": "x\n"})
        result = m.merge_wave_worktrees(
            ["ST-001"], verify_cmds=[], post_wave_cmds=['bash -lc "exit 0"']
        )
        assert result["status"] == "success"
        assert result["post_wave"]["status"] == "passed"
        assert (repo / "b.txt").read_text().strip() == "x"

    def test_per_worktree_verify_failure_aborts_before_merge(self, repo: Path) -> None:
        base = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        _wt_with_files("ST-001", {"b.txt": "x\n"})
        _wt_with_files("ST-002", {"c.txt": "y\n"})

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"], verify_cmds=['bash -lc "exit 5"']
        )
        assert result["kind"] == "VERIFY_FAILED"
        assert result["phase"] == "preflight"
        # Aborted at preflight: working branch never touched.
        assert _git(["rev-parse", "HEAD"], repo).stdout.strip() == base
        assert not (repo / "b.txt").exists()
        status = m.worktree_isolation_status()
        assert len(status["active_worktrees"]) == 2

    def test_no_change_subtask_counted_not_merged(self, repo: Path) -> None:
        # ST-002 has real changes; ST-001's worktree is left empty (actor
        # edited the main tree instead).
        m.create_subtask_worktree("ST-001")
        _wt_with_files("ST-002", {"c.txt": "y\n"})

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
        )
        assert result["status"] == "success"
        assert result["merged"] == ["ST-002"]
        assert result["no_changes"] == ["ST-001"]
        # Only ONE squash commit (ST-002); the no-op subtask added none.
        assert _git(["rev-list", "--count", "HEAD"], repo).stdout.strip() == "2"

    def test_overlap_reported_when_actual_files_auto_merge(self, repo: Path) -> None:
        # Both subtasks touch a.txt but in DIFFERENT hunks (one appends, one
        # prepends) -> git auto-merges, no textual conflict. The declared-disjoint
        # scheduler hint was wrong, so the overlap telemetry must surface a.txt
        # for attribution even though the merge succeeds.
        _wt_with_files("ST-001", {"a.txt": "hello\nappended-by-001\n"})
        _wt_with_files("ST-002", {"a.txt": "prepended-by-002\nhello\n"})

        result = m.merge_wave_worktrees(
            ["ST-001", "ST-002"], verify_cmds=[], post_wave_cmds=[]
        )
        assert result["status"] == "success", result
        overlap_files = {f for o in result["overlaps"] for f in o["files"]}
        assert "a.txt" in overlap_files
        merged_a = (repo / "a.txt").read_text()
        assert "appended-by-001" in merged_a
        assert "prepended-by-002" in merged_a

    def test_cli_wave_merge_happy_path(self, repo: Path) -> None:
        _wt_with_files("ST-001", {"b.txt": "x\n"})
        _wt_with_files("ST-002", {"c.txt": "y\n"})
        runner = SCRIPTS_PATH / "map_step_runner.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(runner),
                "merge_wave_worktrees",
                "ST-001",
                "ST-002",
                "--skip-verify",
                "--skip-post-wave",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "success"
        assert out["merged"] == ["ST-001", "ST-002"]
        assert (repo / "b.txt").exists() and (repo / "c.txt").exists()

    def test_cli_wave_merge_unknown_subtask_exits_nonzero(self, repo: Path) -> None:
        runner = SCRIPTS_PATH / "map_step_runner.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(runner),
                "merge_wave_worktrees",
                "ST-404",
                "--skip-verify",
                "--skip-post-wave",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["kind"] == "NO_WORKTREE"


# --------------------------------------------------------------------------- #
# concurrency_ready — coordinator-owned read-only readiness check (ST-003/AC-3)
# --------------------------------------------------------------------------- #
class TestConcurrencyReady:
    def test_vc1_concurrency_ready_all_clean(self, repo: Path) -> None:
        """VC1: returns ready=True when all worktrees exist, registered, HEAD==base, clean."""
        del repo
        _wt_with_files("ST-010", {})
        _wt_with_files("ST-011", {})
        result = m.concurrency_ready(["ST-010", "ST-011"])
        assert result["ready"] is True
        assert result["reason"] is None
        per = result["per_subtask"]
        assert isinstance(per, dict)
        assert per["ST-010"]["ok"] is True
        assert per["ST-011"]["ok"] is True

    def test_vc1_concurrency_ready_dirty_member(self, repo: Path) -> None:
        """VC1: returns ready=False with dirty reason when one worktree has uncommitted changes."""
        del repo
        created = m.create_subtask_worktree("ST-020")
        assert created["status"] == "success"
        wt = Path(str(created["worktree_path"]))
        # Write a real (non-runtime-state) file to make the worktree dirty.
        (wt / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

        m.create_subtask_worktree("ST-021")

        result = m.concurrency_ready(["ST-020", "ST-021"])
        assert result["ready"] is False
        per = result["per_subtask"]
        assert per["ST-020"]["ok"] is False
        assert per["ST-020"]["reason"] == "dirty"
        assert per["ST-021"]["ok"] is True
        assert result["reason"] == "dirty"

    def test_vc2_concurrency_ready_readonly(self, repo: Path) -> None:
        """VC2: calling concurrency_ready does NOT create/merge/remove worktrees or move HEAD."""
        _wt_with_files("ST-030", {})
        _wt_with_files("ST-031", {})

        wl_before = _git(["worktree", "list", "--porcelain"], repo).stdout
        head_before = _git(["rev-parse", "HEAD"], repo).stdout.strip()

        result = m.concurrency_ready(["ST-030", "ST-031"])
        assert result["ready"] is True

        wl_after = _git(["worktree", "list", "--porcelain"], repo).stdout
        head_after = _git(["rev-parse", "HEAD"], repo).stdout.strip()

        assert wl_before == wl_after, "concurrency_ready must not add/remove worktrees"
        assert head_before == head_after, "concurrency_ready must not move HEAD"

    def test_vc3_concurrency_ready_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VC3: when isolation is off / no worktrees recorded, returns structured result, never raises."""
        r = _make_repo(tmp_path)
        # No worktree.isolation config -> isolation is off, no worktrees recorded.
        monkeypatch.chdir(r)
        result = m.concurrency_ready(["ST-040"])
        # Must not raise; must return a structured dict with ready=False.
        assert isinstance(result, dict)
        assert result["ready"] is False
        assert "reason" in result
        assert "per_subtask" in result
