"""Per-subtask git worktree isolation (#284).

Two layers:
- Config: the MapConfig fields, dotted-key YAML aliasing (`worktree.*` ->
  snake_case), bounds-validation fallback, and the generated default-config doc.
- Runtime: the step-runner lifecycle (create/merge/discard/status), the
  disabled no-op path, and every council-mandated safety guard, exercised
  against real throwaway git repos.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mapify_cli.config.project_config import (
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

import map_step_runner as m  # noqa: E402  # type: ignore[import-not-found]


# --------------------------------------------------------------------------- #
# Config layer
# --------------------------------------------------------------------------- #
def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


class TestWorktreeConfig:
    def test_defaults_off(self) -> None:
        cfg = MapConfig()
        assert cfg.worktree_isolation is False
        assert cfg.worktree_max_deletions == 50

    def test_absent_config_uses_defaults(self, tmp_path: Path) -> None:
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation is False
        assert cfg.worktree_max_deletions == 50

    def test_dotted_keys_alias_to_fields(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path, "worktree.isolation: true\nworktree.max_deletions: 7\n"
        )
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation is True
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
        _write_config(tmp_path, "worktree.isolation: notabool\n")
        cfg = load_map_config(tmp_path)
        assert cfg.worktree_isolation is False

    def test_generated_config_documents_keys(self) -> None:
        body = generate_default_config(include_comments=True)
        assert "worktree.isolation: false" in body
        assert "worktree.max_deletions" in body


# --------------------------------------------------------------------------- #
# Runtime layer — real git repos
# --------------------------------------------------------------------------- #
def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


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
        r = _make_repo(tmp_path)
        (r / ".map").mkdir()
        (r / ".map" / "config.yaml").write_text("worktree.isolation: false\n")
        monkeypatch.chdir(r)
        result = m.create_subtask_worktree("ST-001")
        assert result["status"] == "disabled"
        assert result["ok"] is False

    def test_create_noops_when_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = _make_repo(tmp_path)
        monkeypatch.chdir(r)
        assert m.create_subtask_worktree("ST-001")["status"] == "disabled"


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
