"""
Tests for workflow-gate.py hook.

Run with: pytest tests/test_workflow_gate.py -v

This hook enforces MAP Framework workflow adherence by blocking Edit/Write/MultiEdit
outside of Actor-related phases. Uses step_state.json as source of truth.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# Real runner (+ its map_utils dependency) used to give the state-tamper
# detector's best-effort create_approval_hold subprocess call a working
# target in tests that need to observe a real hold being written.
_RUNNER_SRC_DIR = (
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"
)


class _WorkflowGateTestHelpers:
    """Shared subprocess-harness helpers for workflow-gate.py tests.

    Holds no test methods itself — TestWorkflowGate and
    TestStateTamperDetector both inherit from this so they reuse the same
    hook-invocation plumbing without pytest re-collecting each other's
    test methods (which plain test-class inheritance would cause).
    """

    HOOK_PATH = REPO_ROOT / ".claude/hooks/workflow-gate.py"

    def _parse_stdout(self, stdout: str) -> dict:
        stdout = (stdout or "").strip()
        if not stdout:
            return {}
        return json.loads(stdout)

    def _assert_allowed(self, stdout: str) -> None:
        assert self._parse_stdout(stdout) == {}

    def _assert_denied(self, stdout: str) -> str:
        payload = self._parse_stdout(stdout)
        assert (
            payload.get("hookSpecificOutput", {}).get("hookEventName") == "PreToolUse"
        )
        assert payload["hookSpecificOutput"].get("permissionDecision") == "deny"
        reason = payload["hookSpecificOutput"].get("permissionDecisionReason", "")
        assert reason
        return reason

    def run_hook(
        self, input_data: dict, tmp_path: Path, branch: str = "master"
    ) -> tuple[int, str, str]:
        """Run workflow-gate.py hook with given input."""
        git_dir = tmp_path / ".git"
        if not git_dir.exists():
            subprocess.run(
                ["git", "init"], cwd=tmp_path, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            (tmp_path / "README.md").write_text("test\n")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )

        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if current_branch != branch:
            branch_exists = (
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            )
            if branch_exists:
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=True,
                )
            else:
                subprocess.run(
                    ["git", "checkout", "-b", branch],
                    cwd=tmp_path,
                    capture_output=True,
                    check=True,
                )

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def run_hook_with_project_dir(
        self, input_data: dict, project_dir: Path, extra_env: dict | None = None
    ) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        # Don't let an inherited MAP_MONITOR_HOTFIX leak into tests that
        # assert default behaviour; callers opt in explicitly via extra_env.
        env.pop("MAP_MONITOR_HOTFIX", None)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def _setup_step_state(
        self,
        tmp_path: Path,
        branch: str,
        phase: str,
        subtask_id: str = "ST-001",
        subtask_phases: dict | None = None,
    ) -> None:
        """Create step_state.json with given phase."""
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "current_step_phase": phase,
            "current_subtask_id": subtask_id,
            "subtask_phases": subtask_phases or {},
        }
        (map_dir / "step_state.json").write_text(json.dumps(state))

    def _install_runner(self, tmp_path: Path) -> None:
        """Copy the real map_step_runner.py (+ map_utils.py dependency) into
        tmp_path/.map/scripts/ so the state-tamper detector's best-effort
        create_approval_hold subprocess call has a working target.
        """
        dest = tmp_path / ".map" / "scripts"
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("map_step_runner.py", "map_utils.py"):
            shutil.copy(_RUNNER_SRC_DIR / name, dest / name)

    def _setup_blueprint(
        self,
        tmp_path: Path,
        branch: str,
        subtasks: list[dict],
        nested: bool = False,
    ) -> None:
        """Create blueprint.json with the given subtasks.

        ``nested=True`` wraps the body in a ``{"blueprint": {...}}`` envelope to
        exercise the same nested-payload handling map_step_runner.load_blueprint
        performs.
        """
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True, exist_ok=True)
        body = {"subtasks": subtasks}
        payload = {"blueprint": body} if nested else body
        (map_dir / "blueprint.json").write_text(json.dumps(payload))

class TestWorkflowGate(_WorkflowGateTestHelpers):
    """Tests for workflow-gate.py PreToolUse hook."""

    # --- Terminal / end-of-flow behavior ---

    def test_allows_edit_when_workflow_status_complete_despite_stale_phase(
        self, tmp_path: Path
    ) -> None:
        """A finished workflow (workflow_status=WORKFLOW_COMPLETE) must fail-open
        the gate even if current_step_phase is a non-editing label (a legacy
        state, or a run that stalled before the phase was updated). Prevents the
        post-completion hard-block the end-of-MAP-flow work fixes.
        """
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "DECOMPOSE",
                    "current_subtask_id": "ST-001",
                    "workflow_status": "WORKFLOW_COMPLETE",
                }
            )
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}},
            tmp_path,
            branch="master",
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_block_message_guides_to_archive_not_actor_when_done(
        self, tmp_path: Path
    ) -> None:
        """The non-terminal block message must never tell the agent to blindly
        'Call the Actor agent first', and must point at the clean exits
        (archive / review) with an explicit STOP-and-report — the anti-thrash
        guidance that replaces the old misleading message.
        """
        self._setup_step_state(tmp_path, "master", "DECOMPOSE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}},
            tmp_path,
            branch="master",
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "Call the Actor agent first" not in reason
        assert "map_orchestrator.py archive" in reason
        assert "STOP" in reason
        assert "/map-review" in reason

    # --- Non-editing tools ---

    def test_allows_non_editing_tools(self, tmp_path: Path) -> None:
        """Read, Bash, and other non-editing tools should always be allowed."""
        for tool_name in ["Read", "Bash", "Grep", "Glob", "Task"]:
            code, stdout, _ = self.run_hook(
                {"tool_name": tool_name, "tool_input": {"file_path": "test.py"}},
                tmp_path,
            )
            assert code == 0, f"{tool_name} should be allowed"
            self._assert_allowed(stdout)

    # --- Fail-open behavior ---

    def test_allows_edit_when_no_state_files(self, tmp_path: Path) -> None:
        """Edit allowed when no step_state.json exists."""
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_handles_invalid_json_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open on invalid step_state.json."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True)
        (map_dir / "step_state.json").write_text("not valid json {")

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_handles_malformed_hook_input_gracefully(self, tmp_path: Path) -> None:
        """Should fail-open on malformed hook input JSON."""
        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input="not valid json",
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode == 0
        self._assert_allowed(result.stdout)

    # --- Phase-based enforcement ---

    def test_allows_edit_during_monitor_phase_by_default(self, tmp_path: Path) -> None:
        """MONITOR allows edits BY DEFAULT (MAP_MONITOR_HOTFIX defaults on).

        Actor routinely lands a test/nit while the Monitor verdict is being
        captured; see test_monitor_strict_mode_blocks_edit for the opt-out.
        """
        self._setup_step_state(tmp_path, "master", "MONITOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_during_decompose_phase(self, tmp_path: Path) -> None:
        """Edit blocked during DECOMPOSE phase."""
        self._setup_step_state(tmp_path, "master", "DECOMPOSE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_edit_during_predictor_phase(self, tmp_path: Path) -> None:
        """Edit blocked during PREDICTOR phase."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_allows_edit_during_actor_phase(self, tmp_path: Path) -> None:
        """Edit allowed during ACTOR phase."""
        self._setup_step_state(tmp_path, "master", "ACTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_during_apply_phase(self, tmp_path: Path) -> None:
        """Edit allowed during APPLY phase."""
        self._setup_step_state(tmp_path, "master", "APPLY")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_during_test_writer_phase(self, tmp_path: Path) -> None:
        """Edit allowed during TEST_WRITER phase (TDD mode)."""
        self._setup_step_state(tmp_path, "master", "TEST_WRITER")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_write_during_non_editing_phase(self, tmp_path: Path) -> None:
        """Write blocked like Edit during non-editing phases."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_blocks_multiedit_during_non_editing_phase(self, tmp_path: Path) -> None:
        """MultiEdit blocked like Edit during non-editing phases."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        code, stdout, _ = self.run_hook(
            {"tool_name": "MultiEdit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- Parallel wave mode (subtask_phases) ---

    def test_allows_edit_when_any_subtask_in_actor_phase(self, tmp_path: Path) -> None:
        """In parallel mode, allow if ANY subtask is in an editing phase."""
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "PREDICTOR", "ST-002": "ACTOR"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_when_no_subtask_in_editing_phase(self, tmp_path: Path) -> None:
        """In parallel mode, block if NO subtask is in an editing phase."""
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "PREDICTOR", "ST-002": "DECOMPOSE"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- Step ID translation (subtask_phases stores step IDs, not phase names) ---

    def test_allows_edit_when_subtask_has_step_id_actor(self, tmp_path: Path) -> None:
        """Step ID '2.3' must translate to ACTOR (editing phase) and allow."""
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "2.3"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_when_subtask_has_step_id_test_writer(
        self, tmp_path: Path
    ) -> None:
        """Step ID '2.25' must translate to TEST_WRITER (editing phase) and allow."""
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "2.25"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_when_subtask_has_step_id_research(
        self, tmp_path: Path
    ) -> None:
        """Step ID '2.2' must translate to RESEARCH (non-editing) and block."""
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "2.2"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_phase_allows_docs_only_edit(
        self, tmp_path: Path
    ) -> None:
        """Regression #7: docs-only subtasks (runbook update, README tweak)
        don't need research-agent. Editing a .md path during RESEARCH
        must NOT be blocked — operators were saving empty research stubs
        just to pass the gate.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH")
        for docs_path in (
            str(tmp_path / "docs" / "runbook.md"),
            str(tmp_path / "README.md"),
            str(tmp_path / "CHANGELOG.md"),
            str(tmp_path / "docs" / "guide.rst"),
        ):
            code, stdout, _ = self.run_hook(
                {"tool_name": "Edit", "tool_input": {"file_path": docs_path}},
                tmp_path,
            )
            assert code == 0, f"hook crashed for {docs_path}"
            self._assert_allowed(stdout)

    def test_research_phase_still_blocks_code_edit(
        self, tmp_path: Path
    ) -> None:
        """Counter-test: code paths during RESEARCH still get blocked.
        Otherwise the docs exemption would degenerate into a free pass.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_phase_mixed_paths_still_blocks(
        self, tmp_path: Path
    ) -> None:
        """When MultiEdit targets BOTH docs and code, the docs exemption
        must NOT apply — otherwise code sneaks in under a docs umbrella.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH")
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": "src/app.py",
                    "edits": [
                        {"file_path": "docs/runbook.md"},
                        {"file_path": "src/app.py"},
                    ],
                },
            },
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_phase_message_has_actionable_recovery_commands(
        self, tmp_path: Path
    ) -> None:
        """Regression for friction #11: when Edit is blocked during
        RESEARCH (2.2), the deny message must name the save_research
        command, validate_research, and the validate_step 2.2 follow-up — not a generic
        "phase 'RESEARCH' is not allowed" string. First-time operators
        forget the transition; the gate's message is their only hint.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "RESEARCH" in reason
        assert "save_research" in reason, reason
        assert "validate_research" in reason, reason
        assert "validate_step 2.2" in reason, reason

    # --- RESEARCH scoped to current subtask's affected_files (#164) ---

    def test_research_allows_orthogonal_edit_outside_affected_files(
        self, tmp_path: Path
    ) -> None:
        """#164: RESEARCH blocks only the CURRENT subtask's affected_files.

        An edit to a file orthogonal to ST-001's declared surface (an
        out-of-band hotfix, repo-root config, an unrelated failing test) must
        be allowed via Edit/Write — operators were forced to smuggle these
        through Bash heredocs.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "other.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_research_blocks_edit_inside_affected_files(
        self, tmp_path: Path
    ) -> None:
        """Counter-test: a file IN the current subtask's affected_files is still
        blocked during RESEARCH — research-before-code is the protected
        contract for exactly those files. The message names the scoping.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "app.py")},
            },
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "RESEARCH" in reason
        assert "affected_files" in reason, reason

    def test_research_mixed_affected_and_orthogonal_blocks(
        self, tmp_path: Path
    ) -> None:
        """A batch touching BOTH an affected file and an orthogonal file is
        blocked — a single in-scope target defeats the orthogonal relief, so
        code can't sneak in alongside an orthogonal path.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(tmp_path / "src" / "app.py"),
                    "edits": [
                        {"file_path": str(tmp_path / "src" / "other.py")},
                        {"file_path": str(tmp_path / "src" / "app.py")},
                    ],
                },
            },
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_no_blueprint_blocks_code_edit(self, tmp_path: Path) -> None:
        """Conservative fallback: with a current_subtask_id but no blueprint to
        derive affected_files, the mutation surface is unknown — keep the
        strict block rather than widening it on incomplete information.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "other.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_empty_affected_files_blocks(self, tmp_path: Path) -> None:
        """A subtask whose affected_files is empty cannot be scoped — fall back
        to the strict block (cannot prove the target orthogonal).
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path, "master", [{"id": "ST-001", "affected_files": []}]
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "other.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_research_orthogonal_still_respects_scope_glob(
        self, tmp_path: Path
    ) -> None:
        """The orthogonal relief lifts the phase block but does NOT bypass
        scope_glob: an orthogonal file outside an explicit scope_glob is still
        denied by the constraint check.
        """
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "RESEARCH",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                }
            )
        )
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "tests" / "foo.py")},
            },
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "scope_glob" in reason

    def test_research_orthogonal_out_of_repo_allowed(self, tmp_path: Path) -> None:
        """#164 (second report): a path outside the repo entirely is
        unconditionally orthogonal — no subtask's affected_files can ever
        legitimately name a path outside the repo tree it was declared in,
        so there's no "current subtask context" for it to belong to. Allowed
        during RESEARCH regardless of the subtask's declared affected_files.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/etc/hosts"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_research_orthogonal_handles_nested_blueprint(
        self, tmp_path: Path
    ) -> None:
        """The blueprint reader handles the wrapped {"blueprint": {...}} envelope
        identically to the flat form when scoping orthogonal edits.
        """
        self._setup_step_state(tmp_path, "master", "RESEARCH", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
            nested=True,
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "other.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    # --- Orthogonal relief generalized to ALL blocking phases (#164 second report) ---

    def test_init_state_allows_orthogonal_edit_outside_affected_files(
        self, tmp_path: Path
    ) -> None:
        """#164 (second report): the orthogonal-file relief originally shipped
        RESEARCH-only. The identical block recurred during INIT_STATE — an
        edit outside ST-001's affected_files must be allowed there too, not
        just during RESEARCH.
        """
        self._setup_step_state(tmp_path, "master", "INIT_STATE", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "other.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_init_state_blocks_edit_inside_affected_files(self, tmp_path: Path) -> None:
        """Counter-test: INIT_STATE still blocks a file IN the current
        subtask's affected_files — the relief only lifts the block for
        orthogonal files, not for the subtask's own protected surface.
        """
        self._setup_step_state(tmp_path, "master", "INIT_STATE", subtask_id="ST-001")
        self._setup_blueprint(
            tmp_path,
            "master",
            [{"id": "ST-001", "affected_files": ["src/app.py"]}],
        )
        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "app.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_init_state_out_of_repo_path_allowed(self, tmp_path: Path) -> None:
        """#164 (second report) repro: a MAP session mid-INIT_STATE blocked an
        Edit to a path entirely outside the repo (``~/.claude/CLAUDE.md``
        while a session in a *different* repo was active). An out-of-repo
        path is unconditionally orthogonal regardless of phase.
        """
        self._setup_step_state(tmp_path, "master", "INIT_STATE", subtask_id="ST-001")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/etc/hosts"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_decompose_out_of_repo_path_allowed_without_blueprint(
        self, tmp_path: Path
    ) -> None:
        """The out-of-repo relief needs no blueprint/affected_files at all —
        it is decided purely by path resolution — so it also fires during
        DECOMPOSE, before any subtask work has been scoped.
        """
        self._setup_step_state(tmp_path, "master", "DECOMPOSE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/etc/hosts"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_decompose_in_repo_edit_still_blocked_without_blueprint(
        self, tmp_path: Path
    ) -> None:
        """Counter-test: an in-repo path during DECOMPOSE with no blueprint to
        derive affected_files stays blocked (conservative default) — only
        paths that resolve entirely outside the repo get an unconditional
        pass.
        """
        self._setup_step_state(tmp_path, "master", "DECOMPOSE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/other.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_monitor_strict_mode_blocks_edit(self, tmp_path: Path) -> None:
        """MAP_MONITOR_HOTFIX=0 restores strict read-only MONITOR. The deny
        message must document the opt-out and the monitor_failed path so
        operators don't bypass via state editing.
        """
        map_dir = tmp_path / ".map" / "default"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "MONITOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                }
            )
        )
        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
            extra_env={"MAP_MONITOR_HOTFIX": "0"},
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "MONITOR" in reason
        assert "MAP_MONITOR_HOTFIX" in reason, reason
        assert "monitor_failed" in reason, reason

    # --- Exempt paths ---

    def test_allows_map_dir_edits_always(self, tmp_path: Path) -> None:
        """Edits under .map/ always allowed (prevents deadlocks)."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        map_file = str(tmp_path / ".map" / "master" / "state.json")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": map_file}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    # --- Branch scoping ---

    def test_respects_branch_scoping(self, tmp_path: Path) -> None:
        """Step state should be branch-scoped."""
        # Create state for feature-foo only
        self._setup_step_state(tmp_path, "feature-foo", "ACTOR")

        # On master (no state) → fail-open → allow
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
            branch="master",
        )
        assert code == 0
        self._assert_allowed(stdout)

    @pytest.mark.parametrize(
        "branch_name,sanitized",
        [
            ("feature/authentication", "feature-authentication"),
            ("feat/add-users", "feat-add-users"),
            ("main", "main"),
            ("bugfix/issue-123", "bugfix-issue-123"),
        ],
    )
    def test_branch_name_sanitization(
        self, tmp_path: Path, branch_name: str, sanitized: str
    ) -> None:
        """Branch names with slashes should be sanitized to dashes."""
        self._setup_step_state(tmp_path, sanitized, "ACTOR")

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
            branch=branch_name,
        )
        assert code == 0
        self._assert_allowed(stdout)

    # --- Constraint enforcement ---

    def test_scope_glob_blocks_outside_scope(self, tmp_path: Path) -> None:
        """scope_glob constraint blocks edits outside allowed pattern."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "tests" / "foo.py")},
            },
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "scope_glob" in reason

    def test_scope_glob_allows_within_scope(self, tmp_path: Path) -> None:
        """scope_glob constraint allows edits matching the pattern."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )
        (tmp_path / "src").mkdir(exist_ok=True)

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(tmp_path / "src" / "foo.py")},
            },
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_uses_claude_project_dir_for_state_and_scope(
        self, tmp_path: Path
    ) -> None:
        """Generated-project hooks must read state relative to CLAUDE_PROJECT_DIR."""
        map_dir = tmp_path / ".map" / "default"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "PREDICTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                }
            )
        )

        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/foo.py"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "PREDICTOR" in reason

        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "src/*"},
                }
            )
        )
        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "docs/foo.md"}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "scope_glob" in reason

        code, stdout, _ = self.run_hook_with_project_dir(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/foo.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_no_constraints_allows_all(self, tmp_path: Path) -> None:
        """When constraints is null, all edits are allowed."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": None,
                    "started_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/anywhere/foo.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)
    def test_scope_glob_brace_expansion_bypassed(self, tmp_path: Path) -> None:
        """scope_glob containing '{' is bypassed (fail-open) with stderr warning."""
        map_dir = tmp_path / ".map" / "master"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "ACTOR",
                    "current_subtask_id": "ST-001",
                    "subtask_phases": {},
                    "constraints": {"scope_glob": "{src,tests}/**/*.py"},
                }
            )
        )

        code, stdout, stderr = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "/outside/scope.rb"}},
            tmp_path,
        )
        assert code == 0
        # Should be allowed (fail-open) because brace glob is unsupported
        self._assert_allowed(stdout)
        assert "WARNING" in stderr
        assert "Brace expansion" in stderr

    def test_allows_edit_when_phase_is_complete(self, tmp_path: Path) -> None:
        """Edit allowed after workflow completes (current_step_phase == 'COMPLETE')."""
        self._setup_step_state(tmp_path, "master", "COMPLETE")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_allows_edit_to_claude_rules_learned_during_monitor(
        self, tmp_path: Path
    ) -> None:
        """Path exemption beats phase block: .claude/rules/learned/ is always allowed."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "error-patterns.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# existing\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_blocks_edit_to_claude_skills_when_phase_gated(self, tmp_path: Path) -> None:
        """Exemption is narrow: .claude/skills/ is NOT exempt, still gated by phase."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        target = tmp_path / ".claude" / "skills" / "map-review" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# skill\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "PREDICTOR" in reason

    def test_allows_edit_when_subtask_phase_is_complete(self, tmp_path: Path) -> None:
        """Parallel-wave mode: COMPLETE subtask phase counts as an ALLOWED_PHASE.

        Matches the sequential ``test_allows_edit_when_phase_is_complete`` contract,
        but exercises the ``subtask_phases`` dict path used by parallel waves.
        """
        self._setup_step_state(
            tmp_path,
            "master",
            "PREDICTOR",
            subtask_phases={"ST-001": "COMPLETE"},
        )
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)

    def test_learned_rules_exemption_only_covers_markdown(self, tmp_path: Path) -> None:
        """Non-markdown files under .claude/rules/learned/ are NOT exempt."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "foo.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# python\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "PREDICTOR" in reason

    def test_learned_rules_exemption_allows_nested_markdown(
        self, tmp_path: Path
    ) -> None:
        """Markdown files in subdirectories under .claude/rules/learned/ are exempt."""
        self._setup_step_state(tmp_path, "master", "PREDICTOR")
        target = tmp_path / ".claude" / "rules" / "learned" / "deep" / "nested.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# learned\n", encoding="utf-8")
        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
        )
        assert code == 0
        self._assert_allowed(stdout)


class TestStateTamperDetector(_WorkflowGateTestHelpers):
    """State-tamper detector (D3): runner-owned MAP state is never
    hand-editable while a MAP workflow is active, even though the blanket
    `.map/` exemption would otherwise allow it. A denied attempt records a
    pending `safety_guardrail` approval hold.
    """

    def _read_holds(self, tmp_path: Path, branch: str) -> dict:
        holds_file = tmp_path / ".map" / branch / "approval_holds.json"
        return json.loads(holds_file.read_text())

    def _pending_safety_guardrail_holds(self, tmp_path: Path, branch: str) -> list[dict]:
        store = self._read_holds(tmp_path, branch)
        return [
            h
            for h in store.get("holds", {}).values()
            if h.get("kind") == "safety_guardrail" and h.get("state") == "pending"
        ]

    # --- VC1: protected path classes denied + hold recorded ---

    @pytest.mark.parametrize(
        "rel_template",
        [
            ".map/{branch}/step_state.json",
            ".map/{branch}/approval_holds.json",
            ".map/{branch}/auto-route.json",
            ".map/{branch}/artifact_manifest.json",
            ".map/scripts/map_step_runner.py",
            ".map/scripts/lib/helper.py",
        ],
    )
    def test_denies_protected_path_and_creates_safety_guardrail_hold(
        self, tmp_path: Path, rel_template: str
    ) -> None:
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        self._install_runner(tmp_path)
        rel = rel_template.format(branch=branch)
        target = tmp_path / rel

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        reason = self._assert_denied(stdout)
        assert "map_step_runner.py" in reason
        assert rel in reason

        matches = self._pending_safety_guardrail_holds(tmp_path, branch)
        assert len(matches) == 1, matches
        hold = matches[0]
        assert hold["source"] == "workflow-gate"
        assert rel in hold["request_summary"]

    def test_denies_and_dedups_hold_on_repeated_attempt(self, tmp_path: Path) -> None:
        """Idempotency: the same protected-path attempt twice must not
        create a second pending hold — the stable request_summary dedups.
        """
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        self._install_runner(tmp_path)
        target = tmp_path / ".map" / branch / "step_state.json"

        for _ in range(2):
            code, stdout, _ = self.run_hook(
                {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
                tmp_path,
                branch=branch,
            )
            assert code == 0
            self._assert_denied(stdout)

        matches = self._pending_safety_guardrail_holds(tmp_path, branch)
        assert len(matches) == 1, matches

    # --- VC4: evaluated BEFORE is_exempt_path; Write denied like Edit ---

    def test_tamper_check_precedes_exempt_allow_in_source_order(self) -> None:
        source = self.HOOK_PATH.read_text(encoding="utf-8")
        tamper_line = None
        exempt_line = None
        for lineno, line in enumerate(source.splitlines(), start=1):
            if "if is_state_tamper_path(p)" in line and tamper_line is None:
                tamper_line = lineno
            if "all(is_exempt_path(p) for p in target_paths)" in line and exempt_line is None:
                exempt_line = lineno
        assert tamper_line is not None, "tamper-path filter not found in main()"
        assert exempt_line is not None, "is_exempt_path allow not found in main()"
        assert tamper_line < exempt_line, (
            f"state-tamper check (line {tamper_line}) must precede the "
            f"is_exempt_path allow (line {exempt_line})"
        )

    def test_display_path_resolution_inside_producer_try(self) -> None:
        """INV-4 hardening (PR #427 review): the display-path resolution
        (`_to_repo_relative(...)`) on the tamper deny path must sit INSIDE
        the best-effort try block, after a plain fallback assignment — so
        even an exotic exception out of path resolution reaches deny()
        instead of escaping to the fail-open outer handler.
        """
        source = self.HOOK_PATH.read_text(encoding="utf-8")
        fallback_line = None
        try_line = None
        resolve_line = None
        for lineno, line in enumerate(source.splitlines(), start=1):
            if "attempted = tamper_paths[0]" in line and fallback_line is None:
                fallback_line = lineno
            if fallback_line is not None and try_line is None and line.strip() == "try:":
                try_line = lineno
            if (
                "_to_repo_relative(tamper_paths[0]) or tamper_paths[0]" in line
                and resolve_line is None
            ):
                resolve_line = lineno
        assert fallback_line is not None, "plain fallback assignment not found"
        assert try_line is not None, "producer try block not found after fallback"
        assert resolve_line is not None, "display-path resolution not found"
        assert fallback_line < try_line < resolve_line, (
            f"display-path resolution (line {resolve_line}) must sit inside the "
            f"try block (line {try_line}) that follows the plain fallback "
            f"assignment (line {fallback_line})"
        )

    def test_write_to_protected_state_denied_despite_map_exemption(
        self, tmp_path: Path
    ) -> None:
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        self._install_runner(tmp_path)
        target = tmp_path / ".map" / branch / "step_state.json"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)

    def test_mixed_batch_with_one_protected_path_denies_as_a_whole(
        self, tmp_path: Path
    ) -> None:
        """A MultiEdit batch mixing a protected path with an ordinary
        exempt planning artifact must deny as a whole (fail closed)."""
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        self._install_runner(tmp_path)
        protected = tmp_path / ".map" / branch / "step_state.json"
        ordinary = tmp_path / ".map" / branch / f"spec_{branch}.md"
        ordinary.parent.mkdir(parents=True, exist_ok=True)
        ordinary.write_text("# spec\n", encoding="utf-8")

        code, stdout, _ = self.run_hook(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(protected),
                    "edits": [
                        {"file_path": str(ordinary)},
                        {"file_path": str(protected)},
                    ],
                },
            },
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- Path resolution: dotdot traversal must not defeat the protected set ---

    @pytest.mark.parametrize(
        "dotdot_suffix",
        [
            "{branch}/../{branch}/step_state.json",
            "x/../scripts/foo.py",
        ],
    )
    def test_path_traversal_dotdot_still_matches_protected_set(
        self, tmp_path: Path, dotdot_suffix: str
    ) -> None:
        """is_state_tamper_path resolves the candidate path (strict=False)
        before classifying it, exactly like is_exempt_path does — a literal
        '..' segment in the tool-supplied path string must not let a
        protected target slip past the detector. Both cases below resolve
        to a genuinely protected path: '.map/<branch>/../<branch>/step_state.json'
        collapses to '.map/<branch>/step_state.json' (protected basename);
        '.map/x/../scripts/foo.py' collapses to '.map/scripts/foo.py'
        (protected parts[1] == 'scripts').
        """
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        self._install_runner(tmp_path)
        rel = ".map/" + dotdot_suffix.format(branch=branch)
        target_str = str(tmp_path / rel)
        assert ".." in target_str, "fixture must actually embed a literal '..' segment"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": target_str}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)

    # --- VC2: planning artifacts stay allowed, no hold ---

    def test_planning_artifacts_still_allowed_during_active_workflow_no_hold(
        self, tmp_path: Path
    ) -> None:
        branch = "master"
        # Use a BLOCKING phase (not an editing phase) so an "allowed" result
        # is provably due to the .map/ exemption, not the phase itself.
        self._setup_step_state(tmp_path, branch, "PREDICTOR")
        self._install_runner(tmp_path)

        for rel in (
            f".map/{branch}/spec_{branch}.md",
            f".map/{branch}/task_plan_{branch}.md",
            f".map/{branch}/blueprint.json",
            f".map/{branch}/research/notes.md",
            f".map/{branch}/code-review-001.md",
            f".map/{branch}/compacted/notes.md",
            f".map/{branch}/approval_hold_hold-001.md",
        ):
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("content\n", encoding="utf-8")
            code, stdout, _ = self.run_hook(
                {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
                tmp_path,
                branch=branch,
            )
            assert code == 0, rel
            self._assert_allowed(stdout)

        holds_file = tmp_path / ".map" / branch / "approval_holds.json"
        assert not holds_file.exists()

    def test_ordinary_phase_deny_creates_no_hold(self, tmp_path: Path) -> None:
        branch = "master"
        self._setup_step_state(tmp_path, branch, "DECOMPOSE")
        self._install_runner(tmp_path)

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)

        holds_file = tmp_path / ".map" / branch / "approval_holds.json"
        assert not holds_file.exists()

    # --- VC3: hold-creation failure must still deny; never fail-open ---

    def test_missing_runner_still_denies_and_never_fails_open(
        self, tmp_path: Path
    ) -> None:
        """Fixture repo lacking .map/scripts/ entirely: create_approval_hold's
        subprocess call fails (script not found), but the hook must still
        deny — INV-4, hold creation is best-effort and must never convert a
        tamper deny into an allow, and must never escape to the outer
        fail-open handler.
        """
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        # Deliberately do NOT call self._install_runner(tmp_path).
        target = tmp_path / ".map" / branch / "step_state.json"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)
        # No runner was present, so no approval_holds.json could be written —
        # the deny must still have fired regardless.
        assert not (tmp_path / ".map" / branch / "approval_holds.json").exists()

    def test_vc3_deny_delivered_when_producer_raises(self, tmp_path: Path) -> None:
        """VC3 (INV-4), distinct from the runner-missing case above: the
        runner SCRIPT EXISTS but raises internally (e.g. a bug inside
        create_approval_hold itself, not a missing-file condition). The
        hook must still emit permissionDecision=deny and exit 0 — hold
        creation is best-effort regardless of WHY it failed, and a
        producer exception must never convert a tamper deny into an
        allow or escape to the outer fail-open handler.
        """
        branch = "master"
        self._setup_step_state(tmp_path, branch, "ACTOR")
        # A real file at the expected runner path, but its body raises
        # immediately — distinct from "script not found".
        dest = tmp_path / ".map" / "scripts"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "map_step_runner.py").write_text(
            "raise RuntimeError('boom')\n", encoding="utf-8"
        )
        target = tmp_path / ".map" / branch / "step_state.json"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_denied(stdout)
        # The producer raised before it could write anything durable.
        assert not (tmp_path / ".map" / branch / "approval_holds.json").exists()

    # --- VC5: no-op outside an active workflow ---

    def test_noop_when_no_step_state_json(self, tmp_path: Path) -> None:
        branch = "master"
        self._install_runner(tmp_path)
        target = tmp_path / ".map" / branch / "approval_holds.json"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_allowed(stdout)
        assert not target.exists()

    def test_noop_when_workflow_status_complete(self, tmp_path: Path) -> None:
        branch = "master"
        map_dir = tmp_path / ".map" / branch
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_step_phase": "COMPLETE",
                    "current_subtask_id": "ST-001",
                    "workflow_status": "WORKFLOW_COMPLETE",
                }
            )
        )
        self._install_runner(tmp_path)
        target = map_dir / "step_state.json"

        code, stdout, _ = self.run_hook(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            tmp_path,
            branch=branch,
        )
        assert code == 0
        self._assert_allowed(stdout)
        assert not (map_dir / "approval_holds.json").exists()

    def test_noop_outside_git_repo(self, tmp_path: Path) -> None:
        """Outside a git repo, get_branch_name() falls back to 'default' and,
        absent a .map/default/step_state.json, the detector no-ops —
        matching today's fail-open behavior (no .git dir at all here).
        """
        target = tmp_path / ".map" / "scripts" / "map_step_runner.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# script\n", encoding="utf-8")

        result = subprocess.run(
            ["python3", str(self.HOOK_PATH)],
            input=json.dumps(
                {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
            ),
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
        assert result.returncode == 0
        self._assert_allowed(result.stdout)
        assert not (tmp_path / ".map" / "default" / "approval_holds.json").exists()
