"""Real Git branch discovery before the first commit across installed surfaces."""

import hashlib
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
def test_branch_discovery_preserves_scope_and_fallback(repo, path, function, state, capsys):
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
    captured = capsys.readouterr()
    assert captured.out == ""
    if state == "not_git" and function != "_branch_slug":
        assert "MAP warning:" in captured.err
        assert "using .map/default/" in captured.err
    else:
        assert captured.err == ""


@pytest.mark.parametrize(("path", "function"), SURFACES, ids=[f"{p.parent.parent.name}/{p.stem}" for p, _ in SURFACES])
@pytest.mark.parametrize("branch", ["ветка", "日本語", "!!!", "default"])
@pytest.mark.parametrize("committed", [False, True])
def test_resolved_branch_never_loses_its_scope(repo, path, function, branch, committed, capsys):
    """Fully stripped names have stable distinct scopes; a literal default branch stays quiet."""
    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    if committed:
        git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base")
    expected = "default" if branch == "default" else "branch-" + hashlib.sha256(branch.encode("utf-8")).hexdigest()
    namespace = runpy.run_path(str(path))
    assert namespace[function]() == expected
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("branch", ["ветка", "日本語", "!!!", "default"])
def test_scope_encoding_matches_runtime_and_statusline(repo, branch):
    """Other artifact producers and the statusline must locate the same branch directory."""
    from mapify_cli import get_branch_workspace_status, initialize_branch_workspace
    from mapify_cli.ralph_state import sanitize_branch_name
    from mapify_cli.verification_recorder import _sanitize_branch_name

    expected = "default" if branch == "default" else "branch-" + hashlib.sha256(branch.encode("utf-8")).hexdigest()
    assert sanitize_branch_name(branch) == expected
    assert _sanitize_branch_name(branch) == expected
    assert runpy.run_path(str(SCRIPTS / "map_step_runner.py"))["_sanitize_branch"](branch) == expected
    assert runpy.run_path(str(ROOT / ".claude/hooks/map-statusline.py"))["_sanitize_branch"](branch) == expected
    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    assert initialize_branch_workspace(repo) == repo / ".map" / expected
    assert get_branch_workspace_status(repo)["branch"] == expected


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_plan_and_wayfind_manifest_use_unborn_branch(repo, provider):
    """Fresh installs must plan and register handoffs under the actual unborn branch."""
    installed = CliRunner().invoke(app, ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider])
    assert installed.exit_code == 0, installed.output
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True, check=False)
    assert head.returncode != 0  # installation must not hide the bug with an initial commit
    scripts = repo / ".map/scripts"

    def invoke(script, *args):
        """Run the installed CLI and preserve diagnostics on a failed assertion."""
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
def test_unavailable_git_retains_safe_fallback(repo, monkeypatch, path, function, failure, capsys):
    """Unavailable Git and timeouts remain best-effort discovery failures."""
    namespace = runpy.run_path(str(path))

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    assert namespace[function]() == ("" if function == "_branch_slug" else "default")
    captured = capsys.readouterr()
    assert captured.out == ""
    if function != "_branch_slug":
        assert "MAP warning:" in captured.err
        assert "using .map/default/" in captured.err
    else:
        assert captured.err == ""


@pytest.mark.parametrize("provider", [".claude", ".codex"])
@pytest.mark.parametrize("state", ["unborn", "not_git"])
def test_logger_persists_to_discovered_scope(repo, provider, state):
    """A real hook preserves JSON stdout and makes default-scope fallback visible."""
    if state == "not_git":
        shutil.rmtree(repo / ".git")
    result = subprocess.run(
        [sys.executable, str(ROOT / provider / "hooks/ralph-iteration-logger.py")],
        cwd=repo, env=os.environ.copy(), input=json.dumps({"tool_name": "Bash", "tool_response": "Success"}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    assert json.loads(result.stdout) == {}
    branch = "default" if state == "not_git" else "feat-unborn_branch"
    assert (repo / f".map/{branch}/iteration_log.jsonl").is_file()
    if state == "not_git":
        assert "MAP warning:" in result.stderr
        assert "using .map/default/" in result.stderr
    else:
        assert result.stderr == ""
        assert not (repo / ".map/default").exists()


def test_plan_cli_default_scope_warning_keeps_json_stdout(repo):
    """A non-Git caller receives both the usable JSON response and an explicit warning."""
    shutil.rmtree(repo / ".git")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "map_step_runner.py"), "check_plan_resume"],
        cwd=repo, text=True, capture_output=True, check=True, timeout=20,
    )
    assert json.loads(result.stdout)["branch"] == "default"
    assert "MAP warning:" in result.stderr
    assert "using .map/default/" in result.stderr


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("state", ["unborn", "unicode", "detached", "not_git"])
def test_installed_skill_commands_and_plan_scripts_share_runner_scope(repo, provider, state):
    """Execute installed skill assignments and planning scripts, not only their Python helper."""
    installed = CliRunner().invoke(app, ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider])
    assert installed.exit_code == 0, installed.output
    if state == "unicode":
        git(repo, "symbolic-ref", "HEAD", "refs/heads/ветка")
    elif state == "detached":
        git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base")
        git(repo, "checkout", "--detach", "-q")
    elif state == "not_git":
        shutil.rmtree(repo / ".git")
    branch = {"unborn": "feat-unborn_branch", "unicode": "branch-" + hashlib.sha256("ветка".encode()).hexdigest(),
              "detached": "HEAD", "not_git": "default"}[state]
    skills = repo / (".claude/skills" if provider == "claude" else ".agents/skills")
    plan_text = (skills / "map-plan/SKILL.md").read_text()
    assert any(line.strip().startswith("BRANCH=$(") for line in plan_text.splitlines())
    assignments = {
        line.strip() for path in skills.rglob("*.md") for line in path.read_text().splitlines()
        if line.strip().startswith("BRANCH=$(")
    }
    for command in sorted(assignments):
        result = subprocess.run(
            ["bash", "-c", command + '\nprintf "%s\\n" "$BRANCH"'],
            cwd=repo, text=True, capture_output=True, check=True, timeout=10,
        )
        assert result.stdout.strip() == branch, (command, result.stdout, result.stderr)
        assert ("MAP warning:" in result.stderr) == (state == "not_git")

    if state != "not_git":
        explanation = (skills / "map-explain/SKILL.md").read_text()
        current_lines = [line.strip() for line in explanation.splitlines()
                         if line.strip().startswith(("CURRENT=$(", 'echo "CURRENT=$('))]
        assert current_lines
        for command in current_lines:
            if command.startswith("CURRENT="):
                command += '\nprintf "CURRENT=%s\\n" "$CURRENT"'
            result = subprocess.run(["bash", "-c", command], cwd=repo, text=True,
                                    capture_output=True, check=True, timeout=10)
            expected_current = {"detached": "HEAD", "unicode": "ветка", "unborn": "feat/unborn_branch"}[state]
            assert result.stdout.strip() == f"CURRENT={expected_current}"

    scripts = skills / "map-state/scripts"
    path_result = subprocess.run(["bash", str(scripts / "get-plan-path.sh")], cwd=repo,
                                 text=True, capture_output=True, check=True, timeout=10)
    expected = f".map/{branch}/task_plan_{branch}.md"
    assert path_result.stdout.strip() == expected
    initialized = subprocess.run(["bash", str(scripts / "init-session.sh")], cwd=repo,
                                 text=True, capture_output=True, check=True, timeout=10)
    assert (repo / expected).is_file()
    assert (repo / f".map/{branch}/research/plan__discovery.md").is_file()
    assert ("MAP warning:" in path_result.stderr) == (state == "not_git")
    assert ("MAP warning:" in initialized.stderr) == (state == "not_git")
    if provider == "claude":
        rules = json.loads((skills / "skill-rules.json").read_text())
        assert "python3" in rules["skills"]["map-state"]["requires-cmd"]
    if state == "unicode":
        spec = repo / f".map/{branch}/spec_{branch}.md"
        spec.write_text("# Specification\nNo source citations required.\n")
        validated = subprocess.run([sys.executable, str(repo / ".map/scripts/validate_spec_citations.py")],
                                   cwd=repo, text=True, capture_output=True, check=True, timeout=10)
        assert json.loads(validated.stdout)["passed"] is True


@pytest.mark.parametrize(("argument", "exit_code"), [("--help", 0), ("unknown", 2)])
def test_branch_utility_cli_validates_command_without_side_effects(repo, argument, exit_code):
    """Help and invalid command handling must not create workflow artifacts."""
    result = subprocess.run([sys.executable, str(SCRIPTS / "map_utils.py"), argument],
                            cwd=repo, text=True, capture_output=True, check=False, timeout=10)
    assert result.returncode == exit_code
    assert "MAP warning:" not in result.stderr
    assert not (repo / ".map").exists()
