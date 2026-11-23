"""Workflow write permissions for verifier roles and the local autonomy posture."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

# Path to the hook script
HOOK_PATH = (
    Path(__file__).parent.parent.parent / ".claude" / "hooks" / "workflow-gate.py"
)


def test_registered_git_check_allows_entering_repair_checkout(tmp_path):
    state = tmp_path / ".map" / "default" / "step_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"active_interruption": "repair"}))
    settings = json.loads((HOOK_PATH.parents[1] / "settings.json").read_text())
    registration = next(
        hook["command"] for group in settings["hooks"]["PreToolUse"]
        if group.get("matcher") == "Bash" for hook in group["hooks"]
        if "workflow-gate.py" in hook["command"]
    )
    args = shlex.split(registration.replace("$CLAUDE_PROJECT_DIR", str(HOOK_PATH.parents[2])))
    for command, role, should_deny in [
        ("cd /tmp/repair-checkout", None, False),
        ("git commit -m unexpected", "monitor", True),
    ]:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "agent_type": role}
        result = subprocess.run(
            [sys.executable, *args], input=json.dumps(payload), text=True, capture_output=True,
            cwd=tmp_path, env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}, check=True,
        )
        decision = json.loads(result.stdout).get("hookSpecificOutput", {}).get("permissionDecision")
        assert (decision == "deny") == should_deny


@pytest.mark.parametrize("payload_type", ["raw_patch", "wrapped_patch", "bash"])
@pytest.mark.parametrize("target,denied", [("src/app.py", True), (".map/feature/report.md", False)])
def test_codex_verifier_write_scope(tmp_path, payload_type, target, denied):
    hook = HOOK_PATH.parents[2] / ".codex" / "hooks" / "workflow-gate.py"
    patch = f"*** Begin Patch\n*** Add File: {target}\n+test\n*** End Patch"
    tool = "Bash" if payload_type == "bash" else "apply_patch"
    if payload_type == "bash":
        tool_input = {"command": f"printf ok > {target}"}
    elif payload_type == "wrapped_patch":
        tool_input = {"command": patch}
    else:
        tool_input = patch
    payload = {"tool_name": tool, "tool_input": tool_input, "agent_type": "monitor"}
    result = subprocess.run(
        [sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
        text=True, cwd=tmp_path, env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}, check=True,
    )
    verdict = json.loads(result.stdout).get("hookSpecificOutput", {}).get("permissionDecision")
    assert (verdict == "deny") == denied


def run_hook_bash_in(command: str, project_dir: Path) -> tuple[int, str, str]:
    """Execute the hook with CLAUDE_PROJECT_DIR pointed at *project_dir*.

    Used to exercise the autonomy git-block, which keys on the
    ``mapify.autonomy`` sentinel in ``<project_dir>/.claude/settings.local.json``.
    """
    input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _write_autonomy_settings(project_dir: Path, enabled: bool) -> None:
    """Write .claude/settings.local.json with the autonomy sentinel set/cleared."""
    settings = project_dir / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "permissions": {"allow": ["Bash(*)"], "deny": ["Bash(git commit:*)"]}
    }
    if enabled:
        payload["mapify"] = {"autonomy": True}
    settings.write_text(json.dumps(payload))


def _parse_stdout(stdout: str) -> dict:
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _assert_denied(payload: dict) -> None:
    assert payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
    assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
    reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
    assert reason


class TestAutonomyGitBlock:
    """git commit/push hard-block, gated on the mapify.autonomy sentinel."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit",
            'git commit -m "wip"',
            "git push",
            "git push origin main",
            "git push --force origin feature",  # not main/master, but autonomy blocks all push
            "bash -c 'git commit'",  # wrapper bypass of permission-deny — hook catches it
            "git status && git commit -m x",  # chained
            "git -C /repo commit -m x",  # -C <path> before subcommand
        ],
    )
    def test_git_write_blocked_when_autonomy_on(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=True)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff",
            "git log --oneline",
            "git add .",
            "echo committing",  # 'commit' substring, not a git subcommand
            "pytest -q",
        ],
    )
    def test_read_only_git_allowed_when_autonomy_on(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=True)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    @pytest.mark.parametrize("command", ["git commit -m x", "git push origin main"])
    def test_git_write_allowed_when_autonomy_off(self, command, tmp_path):
        _write_autonomy_settings(tmp_path, enabled=False)
        exit_code, stdout, _ = run_hook_bash_in(command, tmp_path)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_git_write_allowed_when_no_settings_file(self, command="git commit -m x"):
        # No .claude/settings.local.json at all → autonomy off → not blocked.
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            exit_code, stdout, _ = run_hook_bash_in(command, Path(d))
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}


def run_hook_as_agent(
    tool_name: str, tool_input: dict, agent_type: str | None
) -> tuple[int, str, str]:
    """Execute the hook with an explicit `agent_type` (subagent context)."""
    input_data: dict[str, object] = {
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if agent_type is not None:
        input_data["agent_type"] = agent_type
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


class TestVerifierAgentBoundary:
    """A final-verifier run created and committed `3c6a7db` mid-audit, hand-editing
    generated trees and renaming a blueprint-named test, despite an
    APPROVED/REJECTED-only prompt contract. Prompt text is not a capability
    boundary — these tests pin the mechanical one."""

    VERIFIERS: ClassVar[list[str]] = [
        "final-verifier",
        "monitor",
        "evaluator",
        "predictor",
    ]

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'chore(map): strip internal workflow IDs'",
            "git add -A",
            "git push origin HEAD",
            "git reset --soft HEAD~1",
            "git checkout -- src/",
            "git restore .claude/hooks/workflow-gate.py",
            "git -C /repo commit --no-verify -m x",
            "bash -c 'git commit -m sneaky'",
            "make check && git commit -am wip",
            # Ref-moving commands change the very branch under audit.
            "git pull --rebase origin main",
            "git fetch origin",
            "git submodule update --init",
            "git update-ref refs/heads/main HEAD",
            "git symbolic-ref HEAD refs/heads/other",
            "git config user.email x@y.z",
        ],
    )
    def test_git_mutation_blocked_for_verifiers(self, agent, command):
        exit_code, stdout, _ = run_hook_as_agent("Bash", {"command": command}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff origin/main...HEAD",
            "git log -n 5",
            "git show HEAD",
            "git rev-parse HEAD",
            "git ls-files src/",
            "make check",
            "pytest tests/ -q",
        ],
    )
    def test_read_only_evidence_gathering_still_allowed(self, agent, command):
        """The verifier must keep every read/verify capability it needs."""
        exit_code, stdout, _ = run_hook_as_agent("Bash", {"command": command}, agent)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}, f"{command!r} was wrongly blocked"

    def test_git_mutation_allowed_on_main_thread(self):
        """Negative proof: without agent_type the boundary must not engage —
        the orchestrating session owns commits."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m 'ST-001: real work'"}, None
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_git_mutation_allowed_for_actor(self):
        """actor is a legitimate writer — it must keep committing its subtask."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m 'ST-001: real work'"}, "actor"
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
    @pytest.mark.parametrize(
        "path",
        [
            ".claude/hooks/workflow-gate.py",
            "src/mapify_cli/templates/map/scripts/map_step_runner.py",
            "tests/test_workflow_gate.py",
            "README.md",
            "   ",
        ],
    )
    def test_source_writes_blocked_for_verifiers(self, agent, tool, path):
        exit_code, stdout, _ = run_hook_as_agent(tool, {"file_path": path}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "path",
        [
            ".map/feat-x/final_verification.json",
            "./.map/feat-x/progress_feat-x.md",
            str(HOOK_PATH.parent.parent.parent / ".map" / "feat-x" / "code-review-001.md"),
        ],
    )
    def test_map_artifact_writes_allowed_for_verifiers(self, agent, path):
        """final-verifier legitimately writes its own verdict artifacts, whether it
        names them relative to the project root or by absolute path."""
        exit_code, stdout, _ = run_hook_as_agent("Write", {"file_path": path}, agent)
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}, f"{path!r} was wrongly blocked"

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "path",
        [
            # A nested `.map/` is not the project's artifact tree.
            "src/.map/payload.py",
            "src/mapify_cli/.map/cli.py",
            # Another project's `.map/` is out of bounds too.
            "/tmp/other-repo/.map/feat-x/anything.py",
            "../sibling-repo/.map/feat-x/anything.py",
        ],
    )
    def test_foreign_or_nested_map_dirs_are_blocked(self, agent, path):
        """Containment is decided on the RESOLVED path against CLAUDE_PROJECT_DIR —
        a substring check on `/.map/` accepts all of these."""
        exit_code, stdout, _ = run_hook_as_agent("Write", {"file_path": path}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    @pytest.mark.parametrize(
        "path",
        [
            ".map/../src/mapify_cli/cli.py",
            ".map/feat-x/../../.claude/hooks/workflow-gate.py",
            "./.map/../README.md",
        ],
    )
    def test_traversal_out_of_map_is_blocked(self, agent, path):
        """A raw prefix check accepts `.map/../src/...`; normalize before matching."""
        exit_code, stdout, _ = run_hook_as_agent("Write", {"file_path": path}, agent)
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    @pytest.mark.parametrize("agent", VERIFIERS)
    def test_reads_are_never_restricted(self, agent):
        exit_code, stdout, _ = run_hook_as_agent(
            "Read", {"file_path": "src/mapify_cli/cli.py"}, agent
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}

    def test_plugin_scoped_agent_type_is_normalized(self):
        """`plugin:pkg:monitor` must resolve to the monitor boundary."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Bash", {"command": "git commit -m x"}, "plugin:some-pkg:monitor"
        )
        assert exit_code == 0
        _assert_denied(_parse_stdout(stdout))

    def test_source_write_allowed_on_main_thread(self):
        """Negative proof for the path boundary: no agent_type → no confinement."""
        exit_code, stdout, _ = run_hook_as_agent(
            "Write", {"file_path": "src/mapify_cli/cli.py"}, None
        )
        assert exit_code == 0
        assert _parse_stdout(stdout) == {}
