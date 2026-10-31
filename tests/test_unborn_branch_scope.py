"""Real Git branch discovery before the first commit across installed surfaces."""

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/mapify_cli/templates/map/scripts"
HOOKS = [
    (name, "_get_branch" if name in {"context-meter", "map-token-meter", "scrub-internal-ids"} else "get_branch_name")
    for name in (
        "context-meter", "map-token-meter", "scrub-internal-ids",
        "pre-compact-save-transcript", "post-compact-context", "ralph-context-pruner",
        "ralph-iteration-logger", "workflow-context-injector", "workflow-gate",
    )
]
SURFACES = [
    (SCRIPTS / "map_utils.py", "get_branch_name"),
    (SCRIPTS / "diagnostics.py", "get_branch_name"),
    (SCRIPTS / "validate_spec_citations.py", "_branch_slug"),
] + [
    (ROOT / provider / "hooks" / f"{name}.py", function)
    for provider in (".claude", ".codex") for name, function in HOOKS
]


def git(root, *args):
    """Run literal Git commands against the isolated fixture repository."""
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Create an unborn branch; no baseline commit should be necessary for planning."""
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    git(tmp_path, "init", "-q", "-b", "feat/unborn_branch")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return tmp_path


@pytest.mark.parametrize(("path", "function"), SURFACES, ids=[f"{p.parent.parent.name}/{p.stem}" for p, _ in SURFACES])
@pytest.mark.parametrize("state", ["unborn", "committed", "detached", "not_git"])
def test_branch_discovery_preserves_scope_and_fallback(repo, path, function, state):
    """Symbolic unborn names work; committed, detached and non-repo semantics survive."""
    if state in {"committed", "detached"}:
        git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base")
    if state == "detached":
        git(repo, "checkout", "--detach", "-q")
    if state == "not_git":
        shutil.rmtree(repo / ".git")
    namespace = runpy.run_path(str(path))
    expected = "HEAD" if state == "detached" else "feat-unborn_branch"
    if state == "not_git":
        expected = "" if function == "_branch_slug" else "default"
    assert namespace[function]() == expected


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_plan_and_wayfind_manifest_use_unborn_branch(repo, provider):
    """Fresh installs must plan and register handoffs under the actual unborn branch."""
    installed = CliRunner().invoke(app, ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider])
    assert installed.exit_code == 0, installed.output
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True, check=False)
    assert head.returncode != 0  # installation must not hide the bug with an initial commit
    scripts = repo / ".map/scripts"

    def invoke(script, *args):
        result = subprocess.run([sys.executable, str(scripts / script), *args], cwd=repo,
                                capture_output=True, text=True, check=False, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    result = invoke("map_step_runner.py", "check_plan_resume")
    assert result["branch"] == "feat-unborn_branch"
    assert "/.map/feat-unborn_branch/" in result["plan_discovery"]["canonical_path"]
    created = invoke("wayfind_runner.py", "create_wayfind_map", "initial", "Initial", "Choose a direction")
    assert created["status"] == "success"
    ticket = invoke("wayfind_runner.py", "add_ticket", "initial", "Optional expansion", "task", "Expand scope?")
    invoke("wayfind_runner.py", "rule_out_of_scope", "initial", "Keep the initial scope", "--ticket-id", ticket["ticket_id"])
    handoff = invoke("wayfind_runner.py", "emit_wayfind_handoff", "initial")
    assert handoff["manifest"]["status"] == "success"
    manifest = repo / ".map/feat-unborn_branch/artifact_manifest.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text())["branch"] == "feat-unborn_branch"
    assert (repo / ".map/wayfind/initial/handoff.json").is_file()
    assert not (repo / ".map/default").exists()


@pytest.mark.parametrize("branch", ["feat/unborn_branch", "main", "map-wt/st-001-0"])
def test_unborn_worktree_guards_remain_fail_closed(repo, branch):
    """Branch discovery never invents a base commit or bypasses protected/nested guards."""
    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    runner = runpy.run_path(str(SCRIPTS / "map_step_runner.py"))
    discovered = runner["_wt_branch_ref"]()
    assert discovered.returncode == 0
    assert discovered.stdout.strip() == branch
    result = runner["create_subtask_worktree"]("ST-001", allow_dirty=True)
    expected = {"main": "PROTECTED_REF", "map-wt/st-001-0": "NESTED_WORKTREE"}.get(branch, "NO_HEAD")
    assert result["kind"] == expected, result
    assert not (repo / ".git/map-framework/worktrees").exists()


def test_worktree_branch_probe_uses_cwd_and_preserves_detached(repo):
    """A detached candidate remains detached, even when the caller is on a named branch."""
    other = repo / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "candidate")
    git(other, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base")
    git(other, "checkout", "--detach", "-q")
    runner = runpy.run_path(str(SCRIPTS / "map_step_runner.py"))
    result = runner["_wt_branch_ref"](cwd=other)
    assert result.returncode == 0
    assert result.stdout.strip() == "HEAD"
    assert runner["_wt_branch_ref"]().stdout.strip() == "feat/unborn_branch"


@pytest.mark.parametrize(("path", "function"), SURFACES)
@pytest.mark.parametrize("failure", [FileNotFoundError("git unavailable"), subprocess.TimeoutExpired("git", 1)])
def test_unavailable_git_retains_safe_fallback(repo, monkeypatch, path, function, failure):
    """Unavailable Git and timeouts remain best-effort discovery failures."""
    namespace = runpy.run_path(str(path))

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    assert namespace[function]() == ("" if function == "_branch_slug" else "default")


@pytest.mark.parametrize("provider", [".claude", ".codex"])
def test_logger_persists_to_unborn_scope(repo, provider):
    """A real hook must write its observation under the same branch as the runner."""
    result = subprocess.run(
        [sys.executable, str(ROOT / provider / "hooks/ralph-iteration-logger.py")],
        cwd=repo, env=os.environ.copy(), input=json.dumps({"tool_name": "Bash", "tool_response": "Success"}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    assert json.loads(result.stdout) == {}
    assert (repo / ".map/feat-unborn_branch/iteration_log.jsonl").is_file()
    assert not (repo / ".map/default").exists()
