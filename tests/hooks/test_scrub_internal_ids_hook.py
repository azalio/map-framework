"""End-to-end gating + active-path tests for the scrub-internal-ids Stop hook.

The hook is strictly gated: it must no-op unless a MAP run actually completed
(``workflow_status == WORKFLOW_COMPLETE``), it must run exactly once (marker),
honor ``MAP_INVOKED_BY`` and the ``scrub_internal_ids`` opt-out, and on the
active path it must scrub the run-changed code and commit the cleanup.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "scrub-internal-ids.py"
ENGINE_SRC = (
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "scrub_internal_ids.py"
)

LEAKED = (
    "def test_vc1_login():\n"
    "    pass\n"
    "\n"
    "\n"
    "# The rule (INV-7) is enforced here\n"
    "value = 1  # AC-3 reference\n"
)


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
        env={**os.environ,
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )
    return res.stdout.strip()


def _make_project(tmp_path: Path, *, complete: bool, leaked: bool = True,
                  config: str | None = None) -> tuple[Path, str]:
    """Build a git project with a completed (or not) MAP run state."""
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-b", "main")
    # Configure a repo-local identity so the hook's own `git commit` (which runs
    # under ambient identity, not GIT_* env) succeeds — a real user repo always
    # has one; CI runners do not set a global identity.
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "t")
    (project / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-m", "base")
    _git(project, "checkout", "-b", "feature")
    branch = "feature"

    if leaked:
        (project / "app.py").write_text(LEAKED, encoding="utf-8")
        _git(project, "add", "-A")
        _git(project, "commit", "-m", "subtask work")

    # Ship the engine into the project's .map/scripts (generated-project shape).
    scripts = project / ".map" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "scrub_internal_ids.py").write_text(
        ENGINE_SRC.read_text(encoding="utf-8"), encoding="utf-8"
    )

    branch_dir = project / ".map" / branch
    branch_dir.mkdir(parents=True)
    branch_dir.joinpath("step_state.json").write_text(
        json.dumps({
            "workflow": "map-efficient",
            "workflow_status": "WORKFLOW_COMPLETE" if complete else "IN_PROGRESS",
        }),
        encoding="utf-8",
    )
    if config is not None:
        (project / ".map" / "config.yaml").write_text(config, encoding="utf-8")
    return project, branch


def _run_hook(project: Path, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env.pop("MAP_INVOKED_BY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(HOOK)], input="{}", text=True,
        capture_output=True, cwd=project, env=env, timeout=60, check=False,
    )


def _commit_subjects(project: Path) -> list[str]:
    return _git(project, "log", "--format=%s").splitlines()


# --------------------------------------------------------------------------- #
# Gating: no-op paths
# --------------------------------------------------------------------------- #
def test_noop_without_step_state(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-b", "main")
    run = _run_hook(project)
    assert run.returncode == 0
    assert run.stdout.strip() in ("{}", "")


def test_noop_when_workflow_not_complete(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path, complete=False)
    run = _run_hook(project)
    assert run.returncode == 0
    assert run.stdout.strip() in ("{}", "")
    assert "INV-7" in (project / "app.py").read_text(encoding="utf-8")  # untouched
    assert "chore(map): strip internal workflow IDs" not in _commit_subjects(project)


def test_noop_when_map_invoked_by_set(tmp_path: Path) -> None:
    project, branch = _make_project(tmp_path, complete=True)
    run = _run_hook(project, env_extra={"MAP_INVOKED_BY": "actor"})
    assert run.returncode == 0
    assert "INV-7" in (project / "app.py").read_text(encoding="utf-8")  # untouched
    assert not (project / ".map" / branch / ".scrub_done").exists()  # no marker


def test_noop_when_disabled_in_config(tmp_path: Path) -> None:
    project, branch = _make_project(
        tmp_path, complete=True, config="scrub_internal_ids: false\n"
    )
    run = _run_hook(project)
    assert run.returncode == 0
    assert "INV-7" in (project / "app.py").read_text(encoding="utf-8")  # untouched
    assert (project / ".map" / branch / ".scrub_done").exists()  # marked done (opt-out)


# --------------------------------------------------------------------------- #
# Active path + run-once
# --------------------------------------------------------------------------- #
def test_active_path_scrubs_and_commits(tmp_path: Path) -> None:
    project, branch = _make_project(tmp_path, complete=True)
    run = _run_hook(project)
    assert run.returncode == 0

    content = (project / "app.py").read_text(encoding="utf-8")
    assert "INV-7" not in content
    assert "AC-3" not in content
    assert "test_vc1_login" not in content
    assert "def test_login" in content  # renamed, not deleted
    assert "value = 1" in content  # code preserved

    assert "chore(map): strip internal workflow IDs" in _commit_subjects(project)
    assert (project / ".map" / branch / ".scrub_done").exists()


def test_runs_only_once(tmp_path: Path) -> None:
    project, _ = _make_project(tmp_path, complete=True)
    _run_hook(project)
    commits_after_first = len(_commit_subjects(project))
    # Second Stop after completion must be a pure no-op (marker present).
    run = _run_hook(project)
    assert run.returncode == 0
    assert len(_commit_subjects(project)) == commits_after_first  # no extra commit
