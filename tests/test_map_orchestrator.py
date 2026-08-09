"""
Tests for map_orchestrator.py — wave-based parallel execution commands.

Validates:
- set_waves: computes execution_waves from blueprint
- get_wave_step: returns parallel/sequential mode
- validate_wave_step: advances per-subtask phase
- advance_wave: increments current_wave_index
- Backward compat: get_next_step works when execution_waves is empty
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# The orchestrator is a template script, not a regular package module.
# We need to import it from its template location.
ORCHESTRATOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

# Add the scripts directory to sys.path so we can import map_orchestrator
sys.path.insert(0, str(ORCHESTRATOR_PATH))

import map_orchestrator  # pyright: ignore[reportMissingImports]


@pytest.fixture
def branch_dir(tmp_path, monkeypatch):
    """Create a temporary .map/<branch>/ directory and patch get_branch_name."""
    branch = "test-branch"
    map_dir = tmp_path / ".map" / branch
    map_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)
    return branch


def _write_valid_research_artifact(
    tmp_path: Path,
    branch: str,
    subtask_id: str = "ST-001",
) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def handle() -> bool:\n    return True\n", encoding="utf-8")
    research_dir = tmp_path / ".map" / branch / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "confidence": 0.9,
        "status": "OK",
        "search_method": "glob_grep",
        "search_stats": {
            "files_scanned": 1,
            "total_matches_found": 1,
            "results_truncated": False,
        },
        "executive_summary": "Service entry point handles the behavior under test.",
        "relevant_locations": [
            {
                "path": "src/service.py",
                "lines": [1, 2],
                "signature": "def handle() -> bool",
                "relevance": "Primary implementation entry point.",
                "relevance_score": 0.95,
                "has_intent": False,
            }
        ],
        "patterns_discovered": ["direct function dispatch"],
    }
    (research_dir / f"{subtask_id}__actor.md").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_flaky_triage_artifact(
    tmp_path: Path,
    branch: str,
    *,
    check_id: str = "pytest::test_flaky",
    disposition: str = "deferred_nondeterministic",
    pass_count: int = 1,
    fail_count: int = 1,
) -> Path:
    run_count = pass_count + fail_count
    evidence = []
    outcome_sequence = []
    for run in range(1, pass_count + 1):
        evidence.append(
            {"run": run, "status": "passed", "exit_code": 0, "summary": "passed"}
        )
        outcome_sequence.append("passed")
    for run in range(pass_count + 1, run_count + 1):
        evidence.append(
            {"run": run, "status": "failed", "exit_code": 1, "summary": "failed"}
        )
        outcome_sequence.append("failed")
    triage = {
        "check_id": check_id,
        "command": f"pytest {check_id}",
        "reason": "Mixed pass/fail outcomes across repeated runs.",
        "run_count": run_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "outcome_sequence": outcome_sequence,
        "disposition": disposition,
        "recommended_next_action": (
            "record_deferred_nondeterministic"
            if disposition == "deferred_nondeterministic"
            else "fix_confirmed_regression"
        ),
        "monitor_verdict_policy": "not_valid_without_explicit_triage",
        "operator_requirements": [
            "Do not weaken, skip, or delete the check.",
            "Do not treat this artifact as a passing gate.",
            "Record the deferred nondeterministic evidence in Monitor output or issue tracking.",
        ],
        "evidence": evidence,
    }
    path = tmp_path / ".map" / branch / "flaky_test_triage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "branch": branch,
                "updated_at": "2026-06-23T00:00:00Z",
                "triages": [triage],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _monitor_defer_envelope(
    *,
    valid: bool = False,
    check_id: str = "pytest::test_flaky",
    disposition_kind: str = "deferred_nondeterministic",
    failed_checks: "list[str] | None" = None,
    include_disposition: bool = True,
) -> str:
    """Build a complete Monitor JSON envelope signalling a flaky deferral.

    Full required-key set so the existing 2.4 envelope gate passes, then a
    structured `disposition` so validate_step's disposition binding can verify
    it. Knobs flip individual anti-gaming preconditions for rejection tests.
    """
    env: dict[str, object] = {
        "valid": valid,
        "summary": "Confirmed flaky check; deferring with recorded evidence.",
        "issues": [],
        "passed_checks": ["correctness"],
        "failed_checks": ["testability"] if failed_checks is None else failed_checks,
        "feedback_for_actor": "Flaky test deferred; see triage sidecar.",
        "estimated_fix_time": "5 minutes",
        "mcp_tools_used": [],
    }
    if include_disposition:
        env["disposition"] = {"kind": disposition_kind, "check_id": check_id}
    return json.dumps(env)


@pytest.fixture
def sample_blueprint(tmp_path):
    """Create a sample blueprint JSON with a fan-out DAG."""
    branch = "test-branch"
    bp_dir = tmp_path / ".map" / branch
    bp_dir.mkdir(parents=True, exist_ok=True)
    blueprint = {
        "subtasks": [
            {
                "id": "ST-001",
                "dependencies": [],
                "affected_files": ["models.py"],
            },
            {
                "id": "ST-002",
                "dependencies": ["ST-001"],
                "affected_files": ["views.py"],
            },
            {
                "id": "ST-003",
                "dependencies": ["ST-001"],
                "affected_files": ["urls.py"],
            },
            {
                "id": "ST-004",
                "dependencies": ["ST-002", "ST-003"],
                "affected_files": ["tests.py"],
            },
        ]
    }
    bp_file = bp_dir / "blueprint.json"
    bp_file.write_text(json.dumps(blueprint), encoding="utf-8")
    return str(bp_file)


def test_context_budget_warning_uses_standalone_config(tmp_path, monkeypatch, capsys):
    branch = "test-branch"
    (tmp_path / ".map" / branch).mkdir(parents=True)
    (tmp_path / ".map" / "config.yaml").write_text(
        "compression_policy: auto\n"
        "compression_threshold_tokens: 100\n"
        "compression_focus: keep MAP state\n"
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }
        )
        + "\n"
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    map_orchestrator._emit_context_budget_warning(branch, str(transcript))

    stderr = capsys.readouterr().err
    assert "[MAP context-meter]" in stderr
    assert "Context is at 100 / 100 tokens" in stderr
    assert "/compact keep MAP state" in stderr


class TestSetWaves:
    """Tests for set_waves command."""

    def test_set_waves_produces_correct_waves(self, branch_dir, sample_blueprint):
        result = map_orchestrator.set_waves(branch_dir, sample_blueprint)
        assert result["status"] == "success"
        waves = result["execution_waves"]
        assert waves[0] == ["ST-001"]
        assert set(waves[1]) == {"ST-002", "ST-003"}
        assert waves[2] == ["ST-004"]

    def test_set_waves_stores_in_state(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert len(state["execution_waves"]) == 3
        assert state["current_wave_index"] == 0

    def test_set_waves_missing_blueprint(self, branch_dir):
        result = map_orchestrator.set_waves(branch_dir, "/nonexistent.json")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_set_waves_splits_file_conflicts(self, branch_dir, tmp_path):
        """Subtasks sharing files get split into sub-waves."""
        branch = branch_dir
        bp_dir = tmp_path / ".map" / branch
        bp_dir.mkdir(parents=True, exist_ok=True)
        blueprint = {
            "subtasks": [
                {"id": "ST-001", "dependencies": [], "affected_files": ["shared.py"]},
                {"id": "ST-002", "dependencies": [], "affected_files": ["shared.py"]},
            ]
        }
        bp_file = bp_dir / "blueprint.json"
        bp_file.write_text(json.dumps(blueprint), encoding="utf-8")

        result = map_orchestrator.set_waves(branch, str(bp_file))
        assert result["status"] == "success"
        # Both are roots (wave 0) but share files, so should be split
        waves = result["execution_waves"]
        assert len(waves) == 2
        assert waves[0] == ["ST-001"]
        assert waves[1] == ["ST-002"]

    def test_set_waves_populates_subtask_sequence_when_empty(
        self, branch_dir, sample_blueprint
    ):
        """set_waves populates subtask_sequence when it is empty (issue #386)."""
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_sequence == []

        map_orchestrator.set_waves(branch_dir, sample_blueprint)

        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_sequence == ["ST-001", "ST-002", "ST-003", "ST-004"]
        assert state.current_subtask_id == "ST-001"
        assert state.subtask_index == 0

    def test_set_waves_does_not_overwrite_existing_subtask_sequence(
        self, branch_dir, sample_blueprint
    ):
        """set_waves leaves subtask_sequence alone when already populated."""
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.current_subtask_id = "ST-001"
        state.subtask_index = 0
        state.save(state_file)

        map_orchestrator.set_waves(branch_dir, sample_blueprint)

        state = map_orchestrator.StepState.load(state_file)
        # Must not be overwritten — user already set a specific sequence
        assert state.subtask_sequence == ["ST-001", "ST-002"]

    def test_set_waves_nested_blueprint_format(self, branch_dir, tmp_path):
        """Full decomposer output with subtasks nested under 'blueprint' key."""
        branch = branch_dir
        bp_dir = tmp_path / ".map" / branch
        bp_dir.mkdir(parents=True, exist_ok=True)
        full_output = {
            "schema_version": "2.0",
            "analysis": {"assumptions": [], "open_questions": []},
            "blueprint": {
                "id": "test",
                "summary": "Test",
                "subtasks": [
                    {"id": "ST-001", "dependencies": [], "affected_files": []},
                    {
                        "id": "ST-002",
                        "dependencies": ["ST-001"],
                        "affected_files": [],
                    },
                ],
            },
        }
        bp_file = bp_dir / "blueprint.json"
        bp_file.write_text(json.dumps(full_output), encoding="utf-8")

        result = map_orchestrator.set_waves(branch, str(bp_file))
        assert result["status"] == "success"
        waves = result["execution_waves"]
        assert waves[0] == ["ST-001"]
        assert waves[1] == ["ST-002"]


class TestGetWaveStep:
    """Tests for get_wave_step command."""

    def test_parallel_mode_for_multi_subtask_wave(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        # Advance past wave 0 (single subtask)
        map_orchestrator.advance_wave(branch_dir)
        result = map_orchestrator.get_wave_step(branch_dir)
        assert result["mode"] == "parallel"
        assert len(result["subtasks"]) == 2

    def test_sequential_mode_for_single_subtask_wave(
        self, branch_dir, sample_blueprint
    ):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.get_wave_step(branch_dir)
        assert result["mode"] == "sequential"
        assert len(result["subtasks"]) == 1
        assert result["subtasks"][0]["subtask_id"] == "ST-001"

    def test_is_complete_when_all_waves_done(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        # Advance past all 3 waves
        map_orchestrator.advance_wave(branch_dir)
        map_orchestrator.advance_wave(branch_dir)
        map_orchestrator.advance_wave(branch_dir)
        result = map_orchestrator.get_wave_step(branch_dir)
        assert result["is_complete"] is True

    def test_no_waves_returns_complete(self, branch_dir):
        """When no waves configured, returns complete with sequential message."""
        # Initialize state without waves
        state = map_orchestrator.StepState()
        state.save(Path(f".map/{branch_dir}/step_state.json"))
        result = map_orchestrator.get_wave_step(branch_dir)
        assert result["is_complete"] is True
        assert result["mode"] == "sequential"

    def test_tdd_mode_default_phase_is_test_writer(self, branch_dir, sample_blueprint):
        """In TDD mode, wave subtasks default to TEST_WRITER (2.25) not ACTOR."""
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.tdd_mode = True
        state.save(state_file)

        result = map_orchestrator.get_wave_step(branch_dir)
        for subtask in result["subtasks"]:
            assert subtask["step_id"] == "2.25"
            assert subtask["phase"] == "TEST_WRITER"


class TestValidateStepInitStateInvariant:
    """Regression tests for INIT_STATE subtask_sequence invariant (issue #386).

    validate_step("1.6") must not close when subtask_sequence is empty and a
    non-empty blueprint exists; it must auto-populate the sequence instead.
    """

    def _make_blueprint(self, tmp_path: Path, branch: str) -> Path:
        bp_dir = tmp_path / ".map" / branch
        bp_dir.mkdir(parents=True, exist_ok=True)
        blueprint = {
            "subtasks": [
                {"id": "ST-001", "dependencies": [], "affected_files": []},
                {"id": "ST-002", "dependencies": ["ST-001"], "affected_files": []},
                {"id": "ST-003", "dependencies": ["ST-001"], "affected_files": []},
                {"id": "ST-004", "dependencies": ["ST-002", "ST-003"], "affected_files": []},
            ]
        }
        bp_file = bp_dir / "blueprint.json"
        bp_file.write_text(json.dumps(blueprint), encoding="utf-8")
        return bp_file

    def _advance_to_1_6(self, branch_dir: str) -> None:
        """Advance workflow state to step 1.6 (INIT_STATE) via normal init flow."""
        map_orchestrator.initialize_workflow("Add feature", branch_dir)
        map_orchestrator.validate_step("1.0", branch_dir)
        map_orchestrator.validate_step("1.5", branch_dir)
        map_orchestrator.set_plan_approved("true", branch_dir)
        map_orchestrator.validate_step("1.55", branch_dir)
        # get_next_step auto-skips 1.56 (CHOOSE_MODE) and advances to 1.6
        step = map_orchestrator.get_next_step(branch_dir)
        assert step["step_id"] == "1.6", f"Expected step 1.6, got {step['step_id']!r}"

    def test_validate_step_1_6_auto_populates_from_blueprint(self, branch_dir, tmp_path):
        """Closing 1.6 with empty subtask_sequence auto-populates from blueprint."""
        self._make_blueprint(tmp_path, branch_dir)
        self._advance_to_1_6(branch_dir)

        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_sequence == [], "precondition: sequence must be empty"

        result = map_orchestrator.validate_step("1.6", branch_dir)

        assert result["valid"] is True, f"Expected valid=True, got: {result}"
        state = map_orchestrator.StepState.load(state_file)
        assert len(state.subtask_sequence) == 4
        assert state.current_subtask_id == "ST-001"
        assert state.subtask_index == 0

    def test_validate_step_1_6_returns_invalid_when_no_blueprint_and_empty_sequence(
        self, branch_dir
    ):
        """Closing 1.6 with empty sequence and no blueprint returns valid=false."""
        self._advance_to_1_6(branch_dir)

        result = map_orchestrator.validate_step("1.6", branch_dir)

        assert result["valid"] is False
        assert "resume_from_plan" in result.get("message", "")

    def test_validate_step_1_6_no_regression_when_sequence_already_set(
        self, branch_dir, tmp_path
    ):
        """Closing 1.6 with a pre-populated sequence still works (no regression)."""
        self._make_blueprint(tmp_path, branch_dir)
        self._advance_to_1_6(branch_dir)

        # Manually inject sequence (existing caller pattern)
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.save(state_file)

        result = map_orchestrator.validate_step("1.6", branch_dir)

        assert result["valid"] is True
        state = map_orchestrator.StepState.load(state_file)
        # Pre-set sequence must not be overwritten
        assert state.subtask_sequence == ["ST-001", "ST-002"]

    def test_full_issue_386_reproduction(self, branch_dir, tmp_path):
        """Full reproduction of issue #386: validate_step 1.6 → set_waves → get_next_step.

        Without the fix, get_next_step returned RESEARCH with current_subtask=null
        and subtask_progress='1/0'. With the fix, validate_step 1.6 auto-populates
        the sequence so get_next_step correctly returns subtask_progress='1/4'.
        """
        self._make_blueprint(tmp_path, branch_dir)
        map_orchestrator.initialize_workflow("Add feature", branch_dir)
        map_orchestrator.validate_step("1.0", branch_dir)
        map_orchestrator.validate_step("1.5", branch_dir)
        map_orchestrator.set_plan_approved("true", branch_dir)
        map_orchestrator.validate_step("1.55", branch_dir)

        # Exact reproduction sequence from issue #386 — no manual sequence injection
        map_orchestrator.validate_step("1.6", branch_dir)
        map_orchestrator.set_waves(
            branch_dir, str(tmp_path / ".map" / branch_dir / "blueprint.json")
        )
        step = map_orchestrator.get_next_step(branch_dir)

        assert step["current_subtask"] == "ST-001", (
            f"Expected current_subtask='ST-001', got {step['current_subtask']!r}. "
            "Bug #386: subtask_sequence was empty after validate_step 1.6."
        )
        assert step["subtask_progress"] != "1/0", (
            "subtask_progress='1/0' is the bug symptom — sequence was empty."
        )


class TestValidateWaveStep:
    """Tests for validate_wave_step command."""

    def test_advances_subtask_phase(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.validate_wave_step("ST-001", "2.2", branch_dir)
        assert result["valid"] is True
        assert result["next_phase"] == "2.3"

    def test_actor_step_advances_to_monitor(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is True
        assert result["next_phase"] == "2.4"

    def test_validation_passes_without_evidence(self, branch_dir, sample_blueprint):
        """Validation passes without evidence files (evidence removed from pipeline)."""
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is True


class TestPlanResumeContract:
    """Regression tests for /map-plan -> /map-efficient handoff."""

    def test_resume_from_plan_succeeds_for_planning_only_state(self, branch_dir):
        """Planning-shaped state should be resumable via resume_from_plan."""
        plan_dir = Path(f".map/{branch_dir}")
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "### ST-001: First\n- **Status:** pending\n", encoding="utf-8"
        )

        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001"]
        assert result["next_phase"] == "INIT_STATE"

    def test_resume_from_plan_fails_without_plan_file(self, branch_dir):
        """resume_from_plan should fail when no task plan exists."""
        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "error"
        assert "No plan found" in result["message"]

    def test_get_next_step_on_planning_only_state_skips_first_subtask(self, branch_dir):
        """A planning-only state file is not execution-safe without resume_from_plan."""
        state_file = Path(f".map/{branch_dir}/step_state.json")
        planning_state = {
            "_semantic_tag": "MAP_State_v1_0",
            "workflow": "map-plan",
            "started_at": "2026-01-01T00:00:00Z",
            "current_subtask_id": None,
            "current_step_phase": "INITIALIZED",
            "completed_steps": [],
            "pending_steps": [],
            "subtask_sequence": ["ST-001", "ST-002", "ST-003"],
            "aag_contracts": {"ST-001": "Actor -> Action -> Goal"},
            "constraints": {
                "max_files": None,
                "max_subtasks": None,
                "scope_glob": None,
            },
        }
        state_file.write_text(json.dumps(planning_state), encoding="utf-8")

        result = map_orchestrator.get_next_step(branch_dir)

        assert result["current_subtask"] == "ST-002"
        assert result["phase"] == "RESEARCH"

    def test_resume_from_plan_creates_state_with_correct_subtask_sequence(
        self, branch_dir
    ):
        """resume_from_plan should extract subtask IDs from task plan."""
        plan_dir = Path(f".map/{branch_dir}")
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "### ST-001: First\n- **Status:** pending\n\n### ST-002: Second\n- **Status:** pending\n",
            encoding="utf-8",
        )

        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001", "ST-002"]
        assert result["current_subtask_id"] == "ST-001"
        assert result["next_phase"] == "INIT_STATE"

        state = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert state.subtask_sequence == ["ST-001", "ST-002"]
        assert state.current_subtask_id == "ST-001"
        assert state.plan_approved is True
        assert state.execution_mode == "batch"

    def test_resume_from_plan_extracts_subtask_ids_from_map_plan_table(
        self, branch_dir
    ):
        """resume_from_plan should parse the table format emitted by /map-plan."""
        plan_dir = Path(f".map/{branch_dir}")
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\n| ID | Title | concern | diff | risk | one-step | deps |\n|----|-------|---------|------|------|----------|------|\n| ST-001 | Migration 108 | data | small | medium | yes | - |\n| ST-002 | Pure DecayDecision | runtime | medium | high | yes | ST-001 |\n",
            encoding="utf-8",
        )

        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001", "ST-002"]
        state = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert state.subtask_sequence == ["ST-001", "ST-002"]

    def test_resume_from_plan_prefers_blueprint_json_for_subtask_ids(
        self, branch_dir
    ):
        """blueprint.json is the machine contract; markdown is only fallback."""
        plan_dir = Path(f".map/{branch_dir}")
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\nHuman-readable plan without machine-readable IDs.\n",
            encoding="utf-8",
        )
        (plan_dir / "blueprint.json").write_text(
            json.dumps(
                {
                    "subtasks": [
                        {"id": "ST-001", "dependencies": []},
                        {"id": "ST-002", "dependencies": ["ST-001"]},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001", "ST-002"]
        assert result["waves_computed"] == "success"


class TestRestoreDeferredYagni:
    """Restore deferred_yagni items into active plan scope before approval."""

    def _seed_plan(self, branch: str) -> Path:
        plan_dir = Path(f".map/{branch}")
        blueprint = {
            "subtasks": [
                {
                    "id": "ST-001",
                    "title": "Existing subtask",
                    "dependencies": [],
                    "affected_files": ["src/service.py"],
                    "aag_contract": "Actor -> Update service -> Service works",
                    "expected_diff_size": "small",
                    "concern_type": "runtime",
                    "one_logical_step": True,
                    "validation_criteria": ["VC1 [AC-1]: service works"],
                    "requiredness": "explicit",
                    "pruneable": False,
                    "prune_rationale": "User explicitly asked for it.",
                }
            ],
            "coverage_map": {"AC-1": "ST-001"},
            "hard_constraints": [
                {"id": "AC-1", "description": "Existing service behavior works"}
            ],
            "soft_constraints": [],
            "deferred_yagni": [
                {
                    "id": "YG-001",
                    "title": "Add optional export",
                    "rationale": "Nice to have, not required for initial flow.",
                    "restore_hint": "Add CSV export only if the user asks.",
                }
            ],
        }
        (plan_dir / "blueprint.json").write_text(
            json.dumps(blueprint, indent=2) + "\n", encoding="utf-8"
        )
        (plan_dir / f"task_plan_{branch}.md").write_text(
            "# Task Plan\n\n"
            "### ST-001: Existing subtask\n"
            "- **Status:** pending\n\n"
            "## Deferred YAGNI\n\n"
            "- YG-001: Add optional export\n",
            encoding="utf-8",
        )
        state = map_orchestrator.StepState(
            current_step_id="1.55",
            current_step_phase="REVIEW_PLAN",
            plan_approved=True,
        )
        state.save(plan_dir / "step_state.json")
        return plan_dir

    def test_restores_deferred_item_into_blueprint_and_plan(self, branch_dir):
        plan_dir = self._seed_plan(branch_dir)

        result = map_orchestrator.restore_deferred_yagni("YG-001", branch_dir)

        assert result["status"] == "success"
        assert result["subtask_id"] == "ST-002"
        assert result["task_plan_updated"] is True
        assert result["plan_approved_reset"] is True

        blueprint = json.loads((plan_dir / "blueprint.json").read_text())
        assert blueprint["deferred_yagni"] == []
        restored = blueprint["subtasks"][-1]
        assert restored["id"] == "ST-002"
        assert restored["requiredness"] == "optional"
        assert restored["pruneable"] is False
        assert restored["restored_from_deferred_yagni"] == "YG-001"
        assert "Add CSV export" in restored["validation_criteria"][0]

        plan_text = (plan_dir / f"task_plan_{branch_dir}.md").read_text()
        assert "### ST-002: Add optional export" in plan_text
        assert "- **Restored from:** YG-001" in plan_text

        state = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert state.plan_approved is False

    def test_restores_with_explicit_subtask_id(self, branch_dir):
        plan_dir = self._seed_plan(branch_dir)

        result = map_orchestrator.restore_deferred_yagni(
            "YG-001", branch_dir, "ST-010"
        )

        assert result["status"] == "success"
        blueprint = json.loads((plan_dir / "blueprint.json").read_text())
        assert blueprint["subtasks"][-1]["id"] == "ST-010"

    def test_rejects_duplicate_subtask_id_without_mutating(self, branch_dir):
        plan_dir = self._seed_plan(branch_dir)

        result = map_orchestrator.restore_deferred_yagni(
            "YG-001", branch_dir, "ST-001"
        )

        assert result["status"] == "error"
        assert "already exists" in result["message"]
        blueprint = json.loads((plan_dir / "blueprint.json").read_text())
        assert len(blueprint["subtasks"]) == 1
        assert blueprint["deferred_yagni"][0]["id"] == "YG-001"

    def test_rejects_unknown_deferred_id(self, branch_dir):
        plan_dir = self._seed_plan(branch_dir)

        result = map_orchestrator.restore_deferred_yagni("YG-999", branch_dir)

        assert result["status"] == "error"
        assert "not found" in result["message"]
        blueprint = json.loads((plan_dir / "blueprint.json").read_text())
        assert blueprint["deferred_yagni"][0]["id"] == "YG-001"

    def test_cli_help_exposes_restore_command_and_subtask_id(self):
        script = (
            Path(__file__).parent.parent
            / "src" / "mapify_cli" / "templates" / "map" / "scripts"
            / "map_orchestrator.py"
        )

        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert "restore_deferred_yagni" in result.stdout
        assert "--subtask-id" in result.stdout


class TestAdvanceWave:
    """Tests for advance_wave command."""

    def test_increments_wave_index(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.advance_wave(branch_dir)
        assert result["status"] == "success"
        assert result["current_wave_index"] == 1
        assert result["is_complete"] is False

    def test_is_complete_after_last_wave(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        map_orchestrator.advance_wave(branch_dir)  # wave 1
        map_orchestrator.advance_wave(branch_dir)  # wave 2
        result = map_orchestrator.advance_wave(branch_dir)  # wave 3 (past end)
        assert result["is_complete"] is True

    def test_resets_subtask_phases(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        # Set some phases
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.subtask_phases = {"ST-001": "2.4"}
        state.save(state_file)
        # Advance wave
        map_orchestrator.advance_wave(branch_dir)
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_phases == {}

    def test_no_waves_returns_error(self, branch_dir):
        state = map_orchestrator.StepState()
        state.save(Path(f".map/{branch_dir}/step_state.json"))
        result = map_orchestrator.advance_wave(branch_dir)
        assert result["status"] == "error"

    def test_resets_sequential_state_for_next_wave(self, branch_dir, sample_blueprint):
        """After advance_wave, sequential API (get_next_step) works for the new wave."""
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        state_file = Path(f".map/{branch_dir}/step_state.json")

        # Simulate completing wave 0 — leave pending_steps empty
        state = map_orchestrator.StepState.load(state_file)
        state.pending_steps = []
        state.completed_steps = ["2.2", "2.3", "2.4"]
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.save(state_file)

        # Advance to wave 1
        result = map_orchestrator.advance_wave(branch_dir)
        assert result["status"] == "success"
        assert result["is_complete"] is False

        # Sequential state must be reset so get_next_step works
        state = map_orchestrator.StepState.load(state_file)
        assert state.current_step_id == "2.2"
        assert state.current_step_phase == "RESEARCH"
        assert "2.2" in state.pending_steps
        assert "2.3" in state.pending_steps
        assert "2.4" in state.pending_steps
        assert state.completed_steps == []
        assert state.retry_count == 0


class TestBackwardCompat:
    """Verify get_next_step works when execution_waves is empty."""

    def test_get_next_step_without_waves(self, branch_dir):
        """Standard sequential flow works when no waves are configured."""
        state = map_orchestrator.StepState()
        state.save(Path(f".map/{branch_dir}/step_state.json"))
        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "1.0"
        assert result["phase"] == "DECOMPOSE"
        assert result["is_complete"] is False

    def test_state_serialization_with_wave_fields(self, branch_dir):
        """State with wave fields serializes and deserializes correctly."""
        state = map_orchestrator.StepState()
        state.execution_waves = [["ST-001"], ["ST-002", "ST-003"]]
        state.current_wave_index = 1
        state.subtask_phases = {"ST-002": "2.3"}
        state.subtask_retry_counts = {"ST-002": 1}

        state_file = Path(f".map/{branch_dir}/step_state.json")
        state.save(state_file)

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.execution_waves == [["ST-001"], ["ST-002", "ST-003"]]
        assert loaded.current_wave_index == 1
        assert loaded.subtask_phases == {"ST-002": "2.3"}
        assert loaded.subtask_retry_counts == {"ST-002": 1}

    def test_old_state_file_loads_with_defaults(self, branch_dir):
        """State file without wave fields loads with sensible defaults."""
        old_state = {
            "workflow": "map-efficient",
            "current_step_id": "2.0",
            "current_step_phase": "XML_PACKET",  # intentionally old/removed phase — backward compat test
            "subtask_sequence": ["ST-001"],
            # No wave fields
        }
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state_file.write_text(json.dumps(old_state), encoding="utf-8")

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.execution_waves == []
        assert loaded.current_wave_index == 0
        assert loaded.subtask_phases == {}
        assert loaded.subtask_retry_counts == {}


class TestTDDMode:
    """Tests for TDD mode: set_tdd_mode, _get_step_order, auto-skip, and TDD-aware phases."""

    def test_get_step_order_default(self):
        """_get_step_order returns STEP_ORDER when tdd_mode=False."""
        order = map_orchestrator._get_step_order(False)
        assert order is map_orchestrator.STEP_ORDER
        assert "2.25" not in order
        assert "2.26" not in order

    def test_get_step_order_tdd(self):
        """_get_step_order returns TDD_STEP_ORDER when tdd_mode=True."""
        order = map_orchestrator._get_step_order(True)
        assert order is map_orchestrator.TDD_STEP_ORDER
        assert "2.25" in order
        assert "2.26" in order
        # TDD phases must come before ACTOR (2.3)
        assert order.index("2.25") < order.index("2.3")
        assert order.index("2.26") < order.index("2.3")
        assert order.index("2.25") < order.index("2.26")

    def test_set_tdd_mode_enables(self, branch_dir):
        """set_tdd_mode('true') enables TDD and rebuilds pending_steps with TDD phases."""
        state = map_orchestrator.StepState()
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.set_tdd_mode("true", branch_dir)
        assert result["status"] == "success"
        assert result["tdd_mode"] is True

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert loaded.tdd_mode is True
        assert "2.25" in loaded.pending_steps
        assert "2.26" in loaded.pending_steps

    def test_set_tdd_mode_disables(self, branch_dir):
        """set_tdd_mode('false') disables TDD and removes TDD phases from pending_steps."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state.pending_steps = map_orchestrator.TDD_STEP_ORDER.copy()
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.set_tdd_mode("false", branch_dir)
        assert result["status"] == "success"
        assert result["tdd_mode"] is False

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert loaded.tdd_mode is False
        assert "2.25" not in loaded.pending_steps
        assert "2.26" not in loaded.pending_steps

    def test_set_tdd_mode_invalid_value(self, branch_dir):
        """set_tdd_mode with invalid value returns error."""
        state = map_orchestrator.StepState()
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.set_tdd_mode("maybe", branch_dir)
        assert result["status"] == "error"
        assert "Invalid" in result["message"]

    def test_set_tdd_mode_preserves_completed_steps(self, branch_dir):
        """Enabling TDD mode doesn't re-add already completed steps."""
        state = map_orchestrator.StepState()
        state.completed_steps = ["1.0", "1.5"]
        state.pending_steps = [
            "1.55",
            "1.56",
            "1.6",
            "2.0",
            "2.1",
            "2.2",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        map_orchestrator.set_tdd_mode("true", branch_dir)

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "1.0" not in loaded.pending_steps
        assert "1.5" not in loaded.pending_steps
        assert "2.25" in loaded.pending_steps
        assert "2.26" in loaded.pending_steps

    def test_set_tdd_mode_accepts_various_truthy_values(self, branch_dir):
        """set_tdd_mode accepts 'yes', 'y', '1', 'true' as truthy."""
        for value in ["yes", "y", "1", "true", "TRUE", " True "]:
            state = map_orchestrator.StepState()
            state.save(Path(f".map/{branch_dir}/step_state.json"))
            result = map_orchestrator.set_tdd_mode(value, branch_dir)
            assert result["tdd_mode"] is True, f"Failed for value: {value!r}"

    def test_auto_skip_tdd_phases_when_disabled(self, branch_dir):
        """get_next_step auto-skips 2.25 and 2.26 when tdd_mode=False."""
        state = map_orchestrator.StepState()
        state.tdd_mode = False
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "AAG_CONTRACT"
        state.pending_steps = [
            "2.25",
            "2.26",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "2.3"
        assert result["phase"] == "ACTOR"

    def test_tdd_phases_not_skipped_when_enabled(self, branch_dir):
        """get_next_step does NOT skip 2.25 when tdd_mode=True."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "AAG_CONTRACT"
        state.pending_steps = [
            "2.25",
            "2.26",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "2.25"
        assert result["phase"] == "TEST_WRITER"

    def test_tdd_state_serialization(self, branch_dir):
        """tdd_mode field serializes and deserializes correctly."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state.save(state_file)

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.tdd_mode is True

    def test_old_state_without_tdd_mode_defaults_false(self, branch_dir):
        """State file without tdd_mode field defaults to False."""
        old_state = {
            "workflow": "map-efficient",
            "current_step_id": "1.0",
            "current_step_phase": "DECOMPOSE",
        }
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state_file.write_text(json.dumps(old_state), encoding="utf-8")

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.tdd_mode is False

    def test_validate_wave_step_with_tdd_mode(self, branch_dir, sample_blueprint):
        """validate_wave_step uses TDD step order when tdd_mode is enabled."""
        result = map_orchestrator.set_waves(branch_dir, sample_blueprint)
        assert result["status"] == "success"
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.tdd_mode = True
        state.subtask_phases = {"ST-001": "2.25"}

        state.save(state_file)
        result = map_orchestrator.validate_wave_step("ST-001", "2.25", branch_dir)
        assert result["valid"] is True
        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.subtask_phases["ST-001"] == "2.26"

    def test_circuit_breaker_uses_tdd_step_count(self, branch_dir):
        """check_circuit_breaker uses TDD step count when tdd_mode is enabled."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state.subtask_sequence = ["ST-001"]
        state.completed_steps = []
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.check_circuit_breaker(branch_dir)
        expected_max = len(map_orchestrator.TDD_STEP_ORDER)
        assert result["max_iterations"] == expected_max
        assert result["triggered"] is False

    def test_circuit_breaker_standard_step_count(self, branch_dir):
        """check_circuit_breaker uses standard step count when tdd_mode is disabled."""
        state = map_orchestrator.StepState()
        state.tdd_mode = False
        state.subtask_sequence = ["ST-001"]
        state.completed_steps = []
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.check_circuit_breaker(branch_dir)
        expected_max = len(map_orchestrator.STEP_ORDER)
        assert result["max_iterations"] == expected_max

    def test_tdd_step_order_has_more_steps(self):
        """TDD_STEP_ORDER has exactly 2 more steps than STEP_ORDER."""
        assert (
            len(map_orchestrator.TDD_STEP_ORDER) == len(map_orchestrator.STEP_ORDER) + 2
        )

    def test_set_tdd_mode_accepts_various_falsy_values(self, branch_dir):
        """set_tdd_mode accepts 'no', 'n', '0', 'false' as falsy."""
        for value in ["no", "n", "0", "false", "FALSE", " False "]:
            state = map_orchestrator.StepState()
            state.tdd_mode = True
            state.save(Path(f".map/{branch_dir}/step_state.json"))
            result = map_orchestrator.set_tdd_mode(value, branch_dir)
            assert result["tdd_mode"] is False, f"Failed for value: {value!r}"

    def test_get_next_step_after_mid_workflow_tdd_toggle(self, branch_dir):
        """get_next_step returns TEST_WRITER after enabling TDD mid-workflow."""
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.completed_steps = [
            "1.0",
            "1.5",
            "1.55",
            "1.56",
            "1.6",
            "2.0",
            "2.1",
            "2.2",
        ]
        state.pending_steps = ["2.3", "2.4", "2.6", "2.7", "2.8", "2.9", "2.10", "2.11"]
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        map_orchestrator.set_tdd_mode("true", branch_dir)
        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "2.25"
        assert result["phase"] == "TEST_WRITER"

    def test_skip_step_works_for_tdd_phases(self, branch_dir):
        """skip_step('2.25') succeeds when tdd_mode is True."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state.current_step_id = "2.25"
        state.current_step_phase = "TEST_WRITER"
        state.pending_steps = [
            "2.25",
            "2.26",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.skip_step("2.25", branch_dir)
        assert result["status"] == "success"

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "2.25" not in loaded.pending_steps
        assert "2.25" in loaded.completed_steps

    def test_auto_skip_tdd_uses_skipped_steps(self, branch_dir):
        """Auto-skipped TDD phases go to skipped_steps, not completed_steps."""
        state = map_orchestrator.StepState()
        state.tdd_mode = False
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.pending_steps = [
            "2.25",
            "2.26",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        map_orchestrator.get_next_step(branch_dir)

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "2.25" in loaded.skipped_steps
        assert "2.26" in loaded.skipped_steps
        assert "2.25" not in loaded.completed_steps
        assert "2.26" not in loaded.completed_steps

    def test_tdd_toggle_reversible(self, branch_dir):
        """Disabling then re-enabling TDD re-introduces TDD phases."""
        state = map_orchestrator.StepState()
        state.tdd_mode = True
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.completed_steps = [
            "1.0",
            "1.5",
            "1.55",
            "1.56",
            "1.6",
            "2.0",
            "2.1",
            "2.2",
        ]
        state.pending_steps = [
            "2.25",
            "2.26",
            "2.3",
            "2.4",
            "2.6",
            "2.7",
            "2.8",
            "2.9",
            "2.10",
            "2.11",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        # Disable TDD
        map_orchestrator.set_tdd_mode("false", branch_dir)
        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "2.25" not in loaded.pending_steps

        # Re-enable TDD
        map_orchestrator.set_tdd_mode("true", branch_dir)
        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "2.25" in loaded.pending_steps
        assert "2.26" in loaded.pending_steps

    def test_set_tdd_mode_no_global_steps_after_subtask(self, branch_dir):
        """set_tdd_mode after first subtask doesn't re-introduce 1.x steps."""
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 1
        state.current_subtask_id = "ST-002"
        state.completed_steps = []  # Reset after subtask transition
        state.pending_steps = [
            "2.2",
            "2.3",
            "2.4",
        ]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        map_orchestrator.set_tdd_mode("true", branch_dir)
        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        # Must NOT have 1.x steps
        for step in loaded.pending_steps:
            assert not step.startswith("1."), f"Global step {step} re-introduced"
        # Must have TDD steps
        assert "2.25" in loaded.pending_steps
        assert "2.26" in loaded.pending_steps

    def test_skipped_steps_serialization(self, branch_dir):
        """skipped_steps field serializes and deserializes correctly."""
        state = map_orchestrator.StepState()
        state.skipped_steps = ["2.25", "2.26"]
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state.save(state_file)

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.skipped_steps == ["2.25", "2.26"]

    def test_validate_wave_step_no_evidence_required(
        self, branch_dir, sample_blueprint
    ):
        """validate_wave_step passes without evidence directory (evidence removed)."""
        result = map_orchestrator.set_waves(branch_dir, sample_blueprint)
        assert result["status"] == "success"
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.subtask_phases = {"ST-001": "2.3"}
        state.save(state_file)

        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is True


class TestResumeSingleSubtask:
    """Tests for resume_single_subtask — single subtask execution."""

    def _create_plan(self, tmp_path, branch, subtask_ids):
        """Helper to create a task plan with given subtask IDs."""
        plan_dir = tmp_path / ".map" / branch
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_content = "# Task Plan\n\n"
        for st_id in subtask_ids:
            plan_content += f"### {st_id}\n- **Status:** pending\n\n"
        plan_file = plan_dir / f"task_plan_{branch}.md"
        plan_file.write_text(plan_content)
        return plan_dir

    def test_resume_single_subtask_success(self, branch_dir, tmp_path):
        """Basic single subtask setup creates correct state."""
        self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002", "ST-003"])
        result = map_orchestrator.resume_single_subtask("ST-002", branch_dir)
        assert result["status"] == "success"
        assert result["subtask_id"] == "ST-002"
        assert result["tdd_mode"] is False

        # Verify state file
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_sequence == ["ST-002"]
        assert state.current_subtask_id == "ST-002"
        assert state.current_step_id == "2.2"
        assert state.plan_approved is True
        assert "1.0" in state.completed_steps
        assert "2.2" in state.pending_steps

    def test_resume_single_subtask_with_tdd(self, branch_dir, tmp_path):
        """TDD mode adds TEST_WRITER and TEST_FAIL_GATE to pending steps."""
        self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002"])
        result = map_orchestrator.resume_single_subtask(
            "ST-001", branch_dir, tdd_mode=True
        )
        assert result["status"] == "success"
        assert result["tdd_mode"] is True

        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        assert state.tdd_mode is True
        assert "2.25" in state.pending_steps
        assert "2.26" in state.pending_steps

    def test_resume_single_subtask_no_plan(self, branch_dir):
        """Error when no plan file exists."""
        result = map_orchestrator.resume_single_subtask("ST-001", branch_dir)
        assert result["status"] == "error"
        assert "No plan found" in result["message"]

    def test_resume_single_subtask_not_in_plan(self, branch_dir, tmp_path):
        """Error when subtask ID is not in the plan."""
        self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002"])
        result = map_orchestrator.resume_single_subtask("ST-999", branch_dir)
        assert result["status"] == "error"
        assert "ST-999 not found" in result["message"]
        assert "ST-001" in result["message"]

    def test_resume_single_subtask_sets_workflow_status(self, branch_dir, tmp_path):
        """Resume sets workflow_status to IN_PROGRESS."""
        self._create_plan(tmp_path, branch_dir, ["ST-001"])
        map_orchestrator.resume_single_subtask("ST-001", branch_dir)
        state = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert state.workflow_status == "IN_PROGRESS"

    def test_resume_single_subtask_lists_all_subtasks(self, branch_dir, tmp_path):
        """Response includes all subtask IDs from the plan."""
        self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002", "ST-003"])
        result = map_orchestrator.resume_single_subtask("ST-001", branch_dir)
        assert result["all_subtasks_in_plan"] == ["ST-001", "ST-002", "ST-003"]

    def test_resume_single_subtask_then_get_next_step(self, branch_dir, tmp_path):
        """After resume_single_subtask, get_next_step returns RESEARCH."""
        self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002"])
        map_orchestrator.resume_single_subtask("ST-002", branch_dir)
        result = map_orchestrator.get_next_step(branch_dir)
        assert result["phase"] == "RESEARCH"
        assert result["current_subtask"] == "ST-002"

    def test_resume_single_subtask_includes_human_artifact_briefing(
        self, branch_dir, tmp_path
    ):
        """Resume returns session/review/verification context for handoff."""
        plan_dir = self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002"])
        (plan_dir / "code-review-002.md").write_text(
            "# Code Review 002\n\n- fix auth edge case\n- rerun pytest\n",
            encoding="utf-8",
        )
        (plan_dir / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: NEEDS WORK\n",
            encoding="utf-8",
        )

        result = map_orchestrator.resume_single_subtask("ST-001", branch_dir)

        briefing = result["resume_briefing"]
        assert briefing["latest_review_path"].endswith("code-review-002.md")
        assert briefing["latest_verification_verdict"] == "NEEDS WORK"
        assert "fix auth edge case" in "\n".join(briefing["suggested_fixes"])


class TestResumeFromTestContract:
    """Tests for persisted TEST_FAIL_GATE -> ACTOR handoff."""

    def _create_plan(self, tmp_path, branch, subtask_ids):
        plan_dir = tmp_path / ".map" / branch
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_content = "# Task Plan\n\n"
        for st_id in subtask_ids:
            plan_content += f"### {st_id}\n- **Status:** pending\n\n"
        (plan_dir / f"task_plan_{branch}.md").write_text(plan_content, encoding="utf-8")
        return plan_dir

    def test_mark_contract_ready_updates_state(self, branch_dir, tmp_path):
        plan_dir = self._create_plan(tmp_path, branch_dir, ["ST-001"])
        (plan_dir / "test_contract_ST-001.md").write_text(
            "# Test Contract\n", encoding="utf-8"
        )
        (plan_dir / "test_handoff_ST-001.json").write_text(
            '{"subtask_id":"ST-001","status":"contract_ready"}\n',
            encoding="utf-8",
        )
        state = map_orchestrator.StepState(
            current_subtask_id="ST-001",
            current_step_id="2.3",
            current_step_phase="ACTOR",
            pending_steps=["2.3", "2.4"],
            tdd_mode=True,
        )
        state.save(plan_dir / "step_state.json")

        result = map_orchestrator.mark_contract_ready("ST-001", branch_dir)

        assert result["status"] == "success"
        saved = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert saved.workflow_status == "CONTRACT_READY"
        assert saved.current_step_phase == "CONTRACT_READY"
        assert saved.pending_steps == ["CONTRACT_READY"]
        assert "ST-001" in saved.contract_ready_subtasks
        assert saved.contract_ready_subtasks["ST-001"]["ready_at"].endswith("Z")

    def test_get_next_step_pauses_when_contract_ready(self, branch_dir, tmp_path):
        plan_dir = self._create_plan(tmp_path, branch_dir, ["ST-001"])
        state = map_orchestrator.StepState(
            current_subtask_id="ST-001",
            subtask_index=0,
            subtask_sequence=["ST-001"],
            current_step_id="CONTRACT_READY",
            current_step_phase="CONTRACT_READY",
            workflow_status="CONTRACT_READY",
            pending_steps=["CONTRACT_READY"],
        )
        state.save(plan_dir / "step_state.json")

        result = map_orchestrator.get_next_step(branch_dir)

        assert result["step_id"] == "CONTRACT_READY"
        assert result["phase"] == "CONTRACT_READY"
        assert result["is_complete"] is False
        assert "Resume implementation with /map-task" in result["instruction"]

    def test_resume_from_test_contract_starts_at_actor(self, branch_dir, tmp_path):
        plan_dir = self._create_plan(tmp_path, branch_dir, ["ST-001", "ST-002"])
        (plan_dir / "test_contract_ST-001.md").write_text(
            "# Test Contract\n", encoding="utf-8"
        )
        (plan_dir / "test_handoff_ST-001.json").write_text(
            '{"subtask_id":"ST-001","status":"contract_ready"}\n',
            encoding="utf-8",
        )

        result = map_orchestrator.resume_from_test_contract("ST-001", branch_dir)

        assert result["status"] == "success"
        state = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert state.current_subtask_id == "ST-001"
        assert state.current_step_id == "2.3"
        assert state.current_step_phase == "ACTOR"
        assert state.pending_steps == ["2.3", "2.4"]
        assert state.tdd_mode is True
        assert state.completed_steps[-1] == "2.26"

    def test_build_resume_briefing_surfaces_contract_ready_action(
        self, branch_dir, tmp_path
    ):
        plan_dir = self._create_plan(tmp_path, branch_dir, ["ST-001"])
        (plan_dir / "test_contract_ST-001.md").write_text(
            "# Test Contract\n", encoding="utf-8"
        )
        (plan_dir / "test_handoff_ST-001.json").write_text(
            '{"subtask_id":"ST-001","status":"contract_ready"}\n',
            encoding="utf-8",
        )
        state = map_orchestrator.StepState(
            current_subtask_id="ST-001",
            current_step_id="CONTRACT_READY",
            current_step_phase="CONTRACT_READY",
            workflow_status="CONTRACT_READY",
        )
        state.save(plan_dir / "step_state.json")

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert any("persisted test contract" in item for item in result["next_action"])


class TestGetPlanProgress:
    """Tests for get_plan_progress — plan status overview."""

    def _create_plan_with_statuses(self, tmp_path, branch, subtasks):
        """Helper: subtasks is list of (id, status) tuples."""
        plan_dir = tmp_path / ".map" / branch
        plan_dir.mkdir(parents=True, exist_ok=True)
        content = "# Task Plan\n\n"
        for sid, status in subtasks:
            content += f"### {sid}: Some title\n- **Status:** {status}\n\n"
        (plan_dir / f"task_plan_{branch}.md").write_text(content)

    def test_all_pending(self, branch_dir, tmp_path):
        """All subtasks pending — suggested_next is first one."""
        self._create_plan_with_statuses(
            tmp_path,
            branch_dir,
            [("ST-001", "pending"), ("ST-002", "pending"), ("ST-003", "pending")],
        )
        result = map_orchestrator.get_plan_progress(branch_dir)
        assert result["status"] == "success"
        assert result["total"] == 3
        assert result["completed_count"] == 0
        assert result["pending_count"] == 3
        assert result["suggested_next"] == "ST-001"

    def test_some_complete(self, branch_dir, tmp_path):
        """Mix of complete and pending — suggested_next skips completed."""
        self._create_plan_with_statuses(
            tmp_path,
            branch_dir,
            [("ST-001", "complete"), ("ST-002", "complete"), ("ST-003", "pending")],
        )
        result = map_orchestrator.get_plan_progress(branch_dir)
        assert result["completed_count"] == 2
        assert result["pending_count"] == 1
        assert result["completed"] == ["ST-001", "ST-002"]
        assert result["pending"] == ["ST-003"]
        assert result["suggested_next"] == "ST-003"

    def test_all_complete(self, branch_dir, tmp_path):
        """All subtasks complete — suggested_next is None."""
        self._create_plan_with_statuses(
            tmp_path,
            branch_dir,
            [("ST-001", "complete"), ("ST-002", "complete")],
        )
        result = map_orchestrator.get_plan_progress(branch_dir)
        assert result["completed_count"] == 2
        assert result["pending_count"] == 0
        assert result["suggested_next"] is None

    def test_no_plan(self, branch_dir):
        """Error when no plan exists."""
        result = map_orchestrator.get_plan_progress(branch_dir)
        assert result["status"] == "error"
        assert "No plan found" in result["message"]

    def test_in_progress_counts_as_pending(self, branch_dir, tmp_path):
        """in_progress subtask counts as pending (not complete)."""
        self._create_plan_with_statuses(
            tmp_path,
            branch_dir,
            [("ST-001", "complete"), ("ST-002", "in_progress"), ("ST-003", "pending")],
        )
        result = map_orchestrator.get_plan_progress(branch_dir)
        assert result["completed_count"] == 1
        assert result["pending_count"] == 2
        assert result["suggested_next"] == "ST-002"

    def test_plan_progress_includes_resume_briefing(self, branch_dir, tmp_path):
        """Plan progress surfaces latest human-readable branch artifacts."""
        self._create_plan_with_statuses(
            tmp_path, branch_dir, [("ST-001", "complete"), ("ST-002", "pending")]
        )
        plan_dir = tmp_path / ".map" / branch_dir
        (plan_dir / "code-review-001.md").write_text(
            "# Code Review 001\n\n- update tests\n",
            encoding="utf-8",
        )

        result = map_orchestrator.get_plan_progress(branch_dir)

        briefing = result["resume_briefing"]
        assert briefing["latest_review_path"].endswith("code-review-001.md")
        assert "update tests" in "\n".join(briefing["suggested_fixes"])


class TestResumeFromPlan:
    """Tests for resume_from_plan artifact-aware context."""

    def test_resume_from_plan_includes_resume_briefing(self, branch_dir, tmp_path):
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\n### ST-001\n- **Status:** pending\n\n### ST-002\n- **Status:** pending\n",
            encoding="utf-8",
        )
        (plan_dir / "step_state.json").write_text(
            json.dumps({"aag_contracts": {"ST-001": "Keep auth isolated"}}),
            encoding="utf-8",
        )
        (plan_dir / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: READY FOR REVIEW\n",
            encoding="utf-8",
        )

        result = map_orchestrator.resume_from_plan(branch_dir)

        assert result["status"] == "success"
        briefing = result["resume_briefing"]
        assert briefing["latest_verification_verdict"] == "READY FOR REVIEW"


class TestResumeFromPlanAutoSetWaves:
    """Regression: resume_from_plan must auto-compute execution_waves when
    blueprint.json is present, so /map-efficient does not need a separate
    set_waves dispatch on resumed runs (#3 in the framework-issue triage)."""

    def test_blueprint_present_populates_execution_waves(self, branch_dir, tmp_path):
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\n### ST-001\n- **Status:** pending\n\n### ST-002\n- **Status:** pending\n",
            encoding="utf-8",
        )
        (plan_dir / "blueprint.json").write_text(
            json.dumps({
                "summary": "test",
                "subtasks": [
                    {"id": "ST-001", "title": "first", "dependencies": [], "affected_files": ["a.py"]},
                    {"id": "ST-002", "title": "second", "dependencies": ["ST-001"], "affected_files": ["b.py"]},
                ],
            }),
            encoding="utf-8",
        )
        result = map_orchestrator.resume_from_plan(branch_dir)
        assert result["status"] == "success"
        assert result.get("waves_computed") == "success", result

        reloaded = map_orchestrator.StepState.load(plan_dir / "step_state.json")
        assert reloaded.execution_waves, (
            "resume_from_plan must populate execution_waves when blueprint is present"
        )
        # Wave 0 = [ST-001] (no deps); Wave 1 = [ST-002] (depends on ST-001).
        assert reloaded.execution_waves[0] == ["ST-001"]
        assert reloaded.execution_waves[1] == ["ST-002"]

    def test_no_blueprint_marks_waves_skipped(self, branch_dir, tmp_path):
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\n### ST-001\n- **Status:** pending\n",
            encoding="utf-8",
        )
        result = map_orchestrator.resume_from_plan(branch_dir)
        assert result["status"] == "success"
        assert result.get("waves_computed") == "skipped"


class TestBuildResumeBriefing:
    """Tests for next-action resume briefing synthesis."""

    def test_build_resume_briefing_prefers_fixing_failed_verification(
        self, branch_dir, tmp_path
    ):
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"task_plan_{branch_dir}.md").write_text(
            "# Task Plan\n\n### ST-001: Auth\n- **Status:** in_progress\n\n### ST-002: UI\n- **Status:** pending\n",
            encoding="utf-8",
        )
        (plan_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "current_subtask_id": "ST-001",
                    "current_step_phase": "MONITOR",
                    "subtask_sequence": ["ST-001", "ST-002"],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: NEEDS WORK\n",
            encoding="utf-8",
        )
        (plan_dir / "code-review-001.md").write_text(
            "# Code Review 001\n\n- fix auth edge case\n",
            encoding="utf-8",
        )

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert result["current_subtask"] == "ST-001"
        assert result["current_phase"] == "MONITOR"
        assert result["suggested_next"] == "ST-001"
        assert result["next_action"][0].startswith(
            "Address issues from the latest verification"
        )
        assert any(
            "Review requested fixes" in action for action in result["next_action"]
        )


class TestReadTextIfExists:
    """Tests for _read_text_if_exists."""

    def test_happy_path_returns_content(self, tmp_path):
        """Returns full UTF-8 content of an existing file."""
        f = tmp_path / "sample.txt"
        f.write_text("hello world\n", encoding="utf-8")

        result = map_orchestrator._read_text_if_exists(f)

        assert result == "hello world\n"

    def test_missing_file_returns_empty_string(self, tmp_path):
        """Returns empty string for a path that does not exist."""
        result = map_orchestrator._read_text_if_exists(tmp_path / "nonexistent.txt")

        assert result == ""

    def test_directory_path_returns_empty_string(self, tmp_path):
        """Returns empty string when the path is a directory, not a file."""
        result = map_orchestrator._read_text_if_exists(tmp_path)

        assert result == ""

    def test_empty_file_returns_empty_string(self, tmp_path):
        """Returns empty string for an existing but empty file."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        result = map_orchestrator._read_text_if_exists(f)

        assert result == ""


class TestExtractRecentMarkdownSection:
    """Tests for _extract_recent_markdown_section."""

    def test_happy_path_returns_all_lines_when_under_limit(self):
        """Returns all non-empty lines when content is within max_lines."""
        content = "line one\nline two\nline three\n"

        result = map_orchestrator._extract_recent_markdown_section(
            content, max_lines=10
        )

        assert "line one" in result
        assert "line two" in result
        assert "line three" in result

    def test_empty_input_returns_empty_string(self):
        """Returns empty string for empty content."""
        result = map_orchestrator._extract_recent_markdown_section("", max_lines=12)

        assert result == ""

    def test_truncates_to_max_lines(self):
        """Returns only the last max_lines non-empty lines."""
        lines = [f"line {i}" for i in range(1, 21)]  # 20 lines
        content = "\n".join(lines)

        result = map_orchestrator._extract_recent_markdown_section(content, max_lines=5)

        result_lines = result.splitlines()
        assert len(result_lines) == 5
        assert result_lines[-1] == "line 20"
        assert result_lines[0] == "line 16"

    def test_blank_lines_are_skipped(self):
        """Blank/whitespace-only lines do not count towards max_lines."""
        content = "real line\n\n   \nreal line 2\n"

        result = map_orchestrator._extract_recent_markdown_section(
            content, max_lines=10
        )

        result_lines = result.splitlines()
        assert len(result_lines) == 2
        assert "real line" in result_lines[0]

    def test_whitespace_only_content_returns_empty(self):
        """Content consisting only of whitespace/newlines returns empty string."""
        result = map_orchestrator._extract_recent_markdown_section(
            "\n\n   \n", max_lines=12
        )

        assert result == ""


class TestLatestNumberedArtifact:
    """Tests for _latest_numbered_artifact."""

    def test_happy_path_returns_highest_numbered_file(self, tmp_path):
        """Returns the path of the highest-numbered matching file."""
        (tmp_path / "code-review-001.md").write_text("r1", encoding="utf-8")
        (tmp_path / "code-review-002.md").write_text("r2", encoding="utf-8")
        (tmp_path / "code-review-003.md").write_text("r3", encoding="utf-8")

        result = map_orchestrator._latest_numbered_artifact(tmp_path, "code-review")

        assert result is not None
        assert result.name == "code-review-003.md"

    def test_returns_none_for_empty_directory(self, tmp_path):
        """Returns None when no matching files exist in the directory."""
        result = map_orchestrator._latest_numbered_artifact(tmp_path, "code-review")

        assert result is None

    def test_ignores_non_numeric_suffixes(self, tmp_path):
        """Files with non-numeric suffixes are ignored."""
        (tmp_path / "code-review-draft.md").write_text("draft", encoding="utf-8")
        (tmp_path / "code-review-001.md").write_text("r1", encoding="utf-8")

        result = map_orchestrator._latest_numbered_artifact(tmp_path, "code-review")

        assert result is not None
        assert result.name == "code-review-001.md"

    def test_single_file_returned(self, tmp_path):
        """With a single matching file, that file is returned."""
        (tmp_path / "plan-review-007.md").write_text("plan", encoding="utf-8")

        result = map_orchestrator._latest_numbered_artifact(tmp_path, "plan-review")

        assert result is not None
        assert result.name == "plan-review-007.md"

    def test_different_prefix_not_matched(self, tmp_path):
        """Files with a different prefix are not included in the result."""
        (tmp_path / "code-review-001.md").write_text("r1", encoding="utf-8")

        result = map_orchestrator._latest_numbered_artifact(tmp_path, "plan-review")

        assert result is None


class TestBuildResumeBriefingExtended:
    """Extended tests for build_resume_briefing (complement TestBuildResumeBriefing)."""

    def _make_plan(self, tmp_path, branch, subtasks):
        """Helper: write a minimal task_plan file."""
        plan_dir = tmp_path / ".map" / branch
        plan_dir.mkdir(parents=True, exist_ok=True)
        content = "# Task Plan\n\n"
        for sid, status in subtasks:
            content += f"### {sid}: Title\n- **Status:** {status}\n\n"
        (plan_dir / f"task_plan_{branch}.md").write_text(content, encoding="utf-8")
        return plan_dir

    def test_returns_correct_structure_with_empty_artifacts(self, branch_dir, tmp_path):
        """Returns expected keys even when no review/verification artifacts exist."""
        self._make_plan(tmp_path, branch_dir, [("ST-001", "pending")])

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert "branch" in result
        assert "current_subtask" in result
        assert "current_phase" in result
        assert "completed_count" in result
        assert "pending_count" in result
        assert "suggested_next" in result
        assert "next_action" in result
        assert isinstance(result["next_action"], list)

    def test_populates_next_action_with_needs_work_verdict(self, branch_dir, tmp_path):
        """next_action starts with 'Address issues' when verdict is 'NEEDS WORK'."""
        plan_dir = self._make_plan(tmp_path, branch_dir, [("ST-001", "in_progress")])
        (plan_dir / "verification-summary.md").write_text(
            "# Verification Summary\n\n- Verdict: NEEDS WORK\n",
            encoding="utf-8",
        )
        # Write state so current_subtask is populated
        state = map_orchestrator.StepState()
        state.current_subtask_id = "ST-001"
        state.current_step_phase = "MONITOR"
        state.subtask_sequence = ["ST-001"]
        state.save(plan_dir / "step_state.json")

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert result["next_action"][0].startswith("Address issues")

    def test_next_action_empty_when_all_complete_and_no_issues(
        self, branch_dir, tmp_path
    ):
        """next_action includes workflow-complete hint when all subtasks are done."""
        self._make_plan(
            tmp_path, branch_dir, [("ST-001", "complete"), ("ST-002", "complete")]
        )

        result = map_orchestrator.build_resume_briefing(branch_dir)

        joined = " ".join(result["next_action"])
        assert "complete" in joined.lower() or "review" in joined.lower()

    def test_suggested_next_is_first_pending(self, branch_dir, tmp_path):
        """suggested_next is the first pending subtask in plan order."""
        self._make_plan(
            tmp_path,
            branch_dir,
            [("ST-001", "complete"), ("ST-002", "pending"), ("ST-003", "pending")],
        )

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert result["suggested_next"] == "ST-002"

    def test_current_subtask_from_state_file(self, branch_dir, tmp_path):
        """current_subtask is read from step_state.json when present."""
        plan_dir = self._make_plan(tmp_path, branch_dir, [("ST-001", "in_progress")])
        state = map_orchestrator.StepState()
        state.current_subtask_id = "ST-001"
        state.current_step_phase = "ACTOR"
        state.save(plan_dir / "step_state.json")

        result = map_orchestrator.build_resume_briefing(branch_dir)

        assert result["current_subtask"] == "ST-001"
        assert result["current_phase"] == "ACTOR"

    def test_no_plan_file_does_not_crash(self, branch_dir, tmp_path):
        """build_resume_briefing does not raise even when no plan file exists."""
        del tmp_path  # fixture side-effects (chdir) already applied via branch_dir
        result = map_orchestrator.build_resume_briefing(branch_dir)

        # Should return a dict with at minimum the branch key
        assert "branch" in result
        assert result["branch"] == branch_dir


class TestMonitorFailed:
    """Tests for monitor_failed() — automatic ACTOR retry on Monitor failure."""

    def _make_monitor_state(self, tmp_path, branch, **overrides):
        """Create a step_state.json at MONITOR phase."""
        state = map_orchestrator.StepState()
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.3"]
        for k, v in overrides.items():
            setattr(state, k, v)
        state_file = tmp_path / ".map" / branch / "step_state.json"
        state.save(state_file)
        return state_file

    def test_phase_resets_to_actor(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.monitor_failed(branch_dir, "fix it")
        assert result["status"] == "retrying"
        assert result["current_phase"] == "ACTOR"
        state = map_orchestrator.StepState.load(state_file)
        assert state.current_step_phase == "ACTOR"
        assert state.current_step_id == "2.3"

    def test_retry_count_increments(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.monitor_failed(branch_dir, "")
        assert result["retry_count"] == 1
        state = map_orchestrator.StepState.load(state_file)
        assert state.retry_count == 1

    def test_pending_steps_are_actor_and_monitor(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        map_orchestrator.monitor_failed(branch_dir, "")
        state = map_orchestrator.StepState.load(state_file)
        assert state.pending_steps == ["2.3", "2.4"]

    def test_tdd_mode_still_requeues_only_actor_monitor(self, branch_dir, tmp_path):
        """TDD pre-steps (2.25/2.26) are NOT re-run on retry."""
        self._make_monitor_state(tmp_path, branch_dir, tdd_mode=True)
        result = map_orchestrator.monitor_failed(branch_dir, "")
        assert result["status"] == "retrying"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state = map_orchestrator.StepState.load(state_file)
        assert state.pending_steps == ["2.3", "2.4"]

    def test_max_retries_escalation(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir, retry_count=5, max_retries=5)
        result = map_orchestrator.monitor_failed(branch_dir, "still broken")
        assert result["status"] == "max_retries"
        assert result["retry_count"] == 6

    def test_feedback_file_written_when_nonempty(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.monitor_failed(branch_dir, "Missing Reset()")
        assert result["feedback_file"] is not None
        fb = Path(result["feedback_file"])
        assert fb.exists()
        content = fb.read_text()
        assert "Missing Reset()" in content
        assert "retry 1" in content

    def test_feedback_file_highlights_blocker_items_and_preserves_full_text(
        self, branch_dir, tmp_path
    ):
        # BLOCKER lines are surfaced first; the complete original text is always
        # included in the "Full Monitor feedback" section so no content is dropped.
        self._make_monitor_state(tmp_path, branch_dir)
        feedback = "BLOCKER: build failed in src/app.py\nNON-BLOCKING: docs could mention another example\nnice-to-have: style could be more elegant\nMissing required test for handled timeout path"

        result = map_orchestrator.monitor_failed(branch_dir, feedback)

        content = Path(result["feedback_file"]).read_text()
        # Blocker items appear in the highlighted section
        assert "build failed" in content
        assert "Missing required test" in content
        assert "Actor may re-add or expand code only by naming" in content
        # Full original text is preserved — non-blocking lines are NOT dropped
        assert "docs could mention" in content
        assert "style could be more elegant" in content
        assert "Full Monitor feedback:" in content

    def test_feedback_file_non_english_feedback_preserved(self, branch_dir, tmp_path):
        # Russian/non-English feedback must NOT be replaced by a generic placeholder.
        # It should be forwarded in full because no English keyword will match it.
        self._make_monitor_state(tmp_path, branch_dir)
        ru_feedback = (
            "caBundle.enabled=false ломает компонент: Bundle не рендерится, но 6 ссылок на "
            "bundle-ConfigMap остаются в трёх Deployment -> поды в ContainerCreating."
        )

        result = map_orchestrator.monitor_failed(branch_dir, ru_feedback)

        content = Path(result["feedback_file"]).read_text()
        # The Russian defect description must survive into the retry artifact
        assert "ломает компонент" in content
        assert "ContainerCreating" in content
        # Must NOT be replaced by the old generic English-only placeholder
        assert "no BLOCKER-class feedback was detected" not in content

    def test_feedback_file_none_when_empty(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.monitor_failed(branch_dir, "")
        assert result["feedback_file"] is None

    def test_feedback_file_none_when_whitespace(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.monitor_failed(branch_dir, "   ")
        assert result["feedback_file"] is None

    def test_feedback_files_numbered_per_retry(self, branch_dir, tmp_path):
        """Each retry creates a separate feedback file, not overwriting."""
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        r1 = map_orchestrator.monitor_failed(branch_dir, "issue 1")
        # Reset phase back to MONITOR so the second call passes the guard
        state = map_orchestrator.StepState.load(state_file)
        state.current_step_phase = "MONITOR"
        state.save(state_file)
        r2 = map_orchestrator.monitor_failed(branch_dir, "issue 2")
        assert r1["feedback_file"] != r2["feedback_file"]
        assert Path(r1["feedback_file"]).exists()
        assert Path(r2["feedback_file"]).exists()

    def test_second_retry_requires_clean_retry_quarantine(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        first = map_orchestrator.monitor_failed(branch_dir, "issue 1")
        assert first["retry_isolation"] == "normal_retry"

        state = map_orchestrator.StepState.load(state_file)
        state.current_step_phase = "MONITOR"
        state.save(state_file)
        second = map_orchestrator.monitor_failed(
            branch_dir, "Actor repeated the rejected cache strategy."
        )

        assert second["retry_isolation"] == "clean_retry_required"
        quarantine_path = Path(second["retry_quarantine_path"])
        assert quarantine_path.exists()
        payload = json.loads(quarantine_path.read_text(encoding="utf-8"))
        entry = payload["quarantines"][0]
        assert entry["subtask_id"] == "ST-001"
        assert entry["retry_count"] == 2
        assert entry["preserved_constraints"]
        state = map_orchestrator.StepState.load(state_file)
        assert state.clean_retry_count == 1
        assert state.contaminated_retry_count == 1
        assert state.retry_isolation_status["ST-001"] == "clean_retry_required"

    def test_get_next_step_surfaces_clean_retry_instruction(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir, retry_count=1)
        map_orchestrator.monitor_failed(branch_dir, "Repeated stale approach")

        result = map_orchestrator.get_next_step(branch_dir)

        assert result["phase"] == "ACTOR"
        assert "CLEAN_RETRY mode is required" in result["instruction"]
        assert "retry_quarantine.json" in result["instruction"]

    def test_state_saved_on_max_retries(self, branch_dir, tmp_path):
        """State is persisted even in the max_retries early-return branch."""
        state_file = self._make_monitor_state(
            tmp_path, branch_dir, retry_count=5, max_retries=5
        )
        map_orchestrator.monitor_failed(branch_dir, "")
        state = map_orchestrator.StepState.load(state_file)
        assert state.retry_count == 6  # incremented and saved

    def test_phase_guard_accepts_actor_and_monitor(self, branch_dir, tmp_path):
        """monitor_failed() now accepts being called from MONITOR or
        ACTOR/APPLY/TEST_WRITER — the operator often notices verdict
        valid=false while cursor is still at 2.3 (skipped a validate_step
        on the way through). The phase-mismatch ceremony was friction."""
        self._make_monitor_state(tmp_path, branch_dir, current_step_phase="ACTOR")
        result = map_orchestrator.monitor_failed(branch_dir, "feedback")
        assert result["status"] in ("retrying", "max_retries"), result

    def test_phase_guard_rejects_clearly_wrong_phase(self, branch_dir, tmp_path):
        """Reject from clearly-wrong phases (DECOMPOSE / INIT_STATE / COMPLETE)
        where 'monitor failed' doesn't make sense."""
        self._make_monitor_state(
            tmp_path, branch_dir, current_step_phase="DECOMPOSE"
        )
        result = map_orchestrator.monitor_failed(branch_dir, "feedback")
        assert result["status"] == "error"
        assert "DECOMPOSE" in result["message"]

    def test_monitor_failed_then_get_next_step(self, branch_dir, tmp_path):
        """Integration: after monitor_failed(), get_next_step() returns ACTOR."""
        self._make_monitor_state(tmp_path, branch_dir)
        map_orchestrator.monitor_failed(branch_dir, "fix the bug")
        result = map_orchestrator.get_next_step(branch_dir)
        assert result["phase"] == "ACTOR"
        assert result["step_id"] == "2.3"


class TestDeferFlakySubtask:
    """Explicit non-binary Monitor outcome for confirmed flaky checks."""

    def _make_monitor_state(self, tmp_path, branch, **overrides):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        for k, v in overrides.items():
            setattr(state, k, v)
        state_file = tmp_path / ".map" / branch / "step_state.json"
        state.save(state_file)
        return state_file

    def test_rejects_without_valid_flaky_triage_sidecar(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)

        result = map_orchestrator.defer_flaky_subtask(
            "ST-001",
            branch_dir,
            "pytest::test_flaky",
        )

        assert result["status"] == "error"
        assert "flaky test triage not found" in result["message"]
        reloaded = map_orchestrator.StepState.load(state_file)
        assert "ST-001" not in reloaded.subtask_results
        assert reloaded.current_step_id == "2.4"

    def test_rejects_deterministic_failure_triage(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(
            tmp_path,
            branch_dir,
            check_id="pytest::test_flaky",
            disposition="deterministic_failure",
            pass_count=0,
            fail_count=2,
        )

        result = map_orchestrator.defer_flaky_subtask(
            "ST-001",
            branch_dir,
            "pytest::test_flaky",
        )

        assert result["status"] == "error"
        assert "no deferred_nondeterministic triage" in result["message"]
        reloaded = map_orchestrator.StepState.load(state_file)
        assert "ST-001" not in reloaded.subtask_results

    def test_records_non_green_defer_and_advances_to_next_subtask(
        self, branch_dir, tmp_path
    ):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")

        result = map_orchestrator.defer_flaky_subtask(
            "ST-001",
            branch_dir,
            "pytest::test_flaky",
            files_changed=["src/service.py"],
            summary="Monitor deferred a confirmed flaky check with recorded evidence.",
        )

        assert result["status"] == "success", result
        assert result["disposition"] == "deferred_nondeterministic"
        assert result["non_green_outcome"] is True
        assert result["next_step"] == "2.2"
        assert result["subtask_advanced_from"] == "ST-001"
        assert result["subtask_advanced_to"] == "ST-002"

        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-002"
        assert reloaded.current_step_id == "2.2"
        assert reloaded.current_step_phase == "RESEARCH"
        recorded = reloaded.subtask_results["ST-001"]
        assert recorded["status"] == "deferred_nondeterministic"
        assert recorded["files_changed"] == ["src/service.py"]
        assert recorded["non_green_outcome"] is True
        assert recorded["monitor_verdict_policy"] == "not_valid_without_explicit_triage"
        assert recorded["flaky_test_triage"]["check_id"] == "pytest::test_flaky"
        assert recorded["flaky_test_triage"]["pass_count"] == 1
        assert recorded["flaky_test_triage"]["fail_count"] == 1

    def test_final_deferred_subtask_marks_workflow_complete_with_evidence(
        self, branch_dir, tmp_path
    ):
        state_file = self._make_monitor_state(
            tmp_path,
            branch_dir,
            subtask_sequence=["ST-001"],
            subtask_index=0,
        )
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")

        result = map_orchestrator.defer_flaky_subtask(
            "ST-001",
            branch_dir,
            "pytest::test_flaky",
        )

        assert result["status"] == "success", result
        assert result["next_step"] == "COMPLETE"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.workflow_status == "WORKFLOW_COMPLETE"
        assert reloaded.current_step_phase == "COMPLETE"
        assert reloaded.subtask_results["ST-001"]["status"] == "deferred_nondeterministic"


class TestValidateStepDisposition:
    """validate_step 2.4 --disposition routes the THIRD Monitor outcome.

    A confirmed flaky check is deferred through the verdict path itself
    (valid:false + deferred:true), not via an out-of-band command, and the
    anti-gaming gate rejects every way of faking a deferral.
    """

    def _make_monitor_state(self, tmp_path, branch, **overrides):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        for k, v in overrides.items():
            setattr(state, k, v)
        state_file = tmp_path / ".map" / branch / "step_state.json"
        state.save(state_file)
        return state_file

    def test_deferred_disposition_routes_to_deferral_and_advances(
        self, branch_dir, tmp_path
    ):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")

        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            recommendation="needs_investigation",
            monitor_envelope=_monitor_defer_envelope(check_id="pytest::test_flaky"),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
            files_changed=["src/service.py"],
            summary="Monitor deferred a confirmed flaky check.",
        )

        # A deferred run is NON-GREEN: valid is false, but it is a routing
        # outcome (deferred), not a hard-stop retry.
        assert result["valid"] is False
        assert result["deferred"] is True
        assert result["non_green_outcome"] is True
        assert result["disposition"] == "deferred_nondeterministic"
        assert result["next_step"] == "2.2"
        assert result["subtask_advanced_to"] == "ST-002"

        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-002"
        recorded = reloaded.subtask_results["ST-001"]
        assert recorded["status"] == "deferred_nondeterministic"
        assert recorded["non_green_outcome"] is True
        assert recorded["files_changed"] == ["src/service.py"]
        assert recorded["flaky_test_triage"]["check_id"] == "pytest::test_flaky"

    def test_missing_sidecar_hard_stops_without_advancing(self, branch_dir, tmp_path):
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        # No sidecar written at all.
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "deferral rejected" in result["message"].lower()
        reloaded = map_orchestrator.StepState.load(state_file)
        assert "ST-001" not in reloaded.subtask_results
        assert reloaded.current_step_id == "2.4"

    def test_deterministic_failure_sidecar_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(
            tmp_path,
            branch_dir,
            check_id="pytest::test_flaky",
            disposition="deterministic_failure",
            pass_count=0,
            fail_count=2,
        )
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")

    def test_check_id_not_in_sidecar_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        # Sidecar exists for a DIFFERENT check; the "borrowed flake" exploit.
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::other")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(check_id="pytest::test_flaky"),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")

    def test_envelope_disposition_check_id_mismatch_rejected(
        self, branch_dir, tmp_path
    ):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")
        # Envelope's structured disposition names a different check than --check-id.
        envelope = _monitor_defer_envelope(check_id="pytest::DIFFERENT")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=envelope,
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "binding failed" in result["message"].lower()

    def test_envelope_valid_true_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(valid=True),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "binding failed" in result["message"].lower()

    def test_empty_failed_checks_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(failed_checks=[]),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "binding failed" in result["message"].lower()

    def test_contradictory_recommendation_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            recommendation="revise",  # contradicts a deferral
            monitor_envelope=_monitor_defer_envelope(),
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "contradict" in result["message"].lower()

    def test_missing_monitor_envelope_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        _write_flaky_triage_artifact(tmp_path, branch_dir, check_id="pytest::test_flaky")
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            disposition="deferred_nondeterministic",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "monitor-envelope" in result["message"].lower()

    def test_missing_check_id_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(),
            disposition="deferred_nondeterministic",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "check-id" in result["message"].lower()

    def test_unknown_disposition_rejected(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            monitor_envelope=_monitor_defer_envelope(),
            disposition="totally_made_up",
            check_id="pytest::test_flaky",
        )
        assert result["valid"] is False
        assert not result.get("deferred")
        assert "unknown monitor disposition" in result["message"].lower()

    def test_normal_verdict_without_disposition_unaffected(
        self, branch_dir, tmp_path
    ):
        # A disposition-less 2.4 close still behaves exactly as before.
        state_file = self._make_monitor_state(tmp_path, branch_dir)
        result = map_orchestrator.validate_step(
            "2.4",
            branch_dir,
            recommendation="approve",
        )
        assert result["valid"] is True
        assert not result.get("deferred")
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-002"

    @staticmethod
    def _make_project(root: Path) -> Path:
        """Populate <root>/.map/scripts/ from the template (main() anchors cwd
        to Path(__file__).parents[2], so the CLI must run from a real project
        layout — not the rendered template tree)."""
        import shutil

        scripts_dir = root / ".map" / "scripts"
        scripts_dir.mkdir(parents=True)
        for py_file in ORCHESTRATOR_PATH.glob("*.py"):
            shutil.copy(py_file, scripts_dir / py_file.name)
        return scripts_dir / "map_orchestrator.py"

    def test_cli_deferral_exits_zero(self, tmp_path):
        # The CLI is the real consumer of the valid:false+deferred:true shape:
        # a deferral must exit 0 so the skill does NOT treat it as a hard-stop.
        project = tmp_path / "project"
        project.mkdir()
        script = self._make_project(project)
        self._make_monitor_state(project, "test-branch")
        _write_flaky_triage_artifact(project, "test-branch", check_id="pytest::test_flaky")
        proc = subprocess.run(
            [
                sys.executable, str(script), "validate_step", "2.4",
                "--branch", "test-branch",
                "--disposition", "deferred_nondeterministic",
                "--check-id", "pytest::test_flaky",
                "--monitor-envelope", "-",
            ],
            input=_monitor_defer_envelope(check_id="pytest::test_flaky"),
            cwd=str(project), capture_output=True, text=True, timeout=30,
            check=False,
        )
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        payload = json.loads(proc.stdout)
        assert payload["valid"] is False
        assert payload["deferred"] is True
        assert payload["next_step"] == "2.2"

    def test_cli_rejected_deferral_exits_one(self, tmp_path):
        # No sidecar → the deferral cannot be honored → real failure, exit 1.
        project = tmp_path / "project"
        project.mkdir()
        script = self._make_project(project)
        self._make_monitor_state(project, "test-branch")
        proc = subprocess.run(
            [
                sys.executable, str(script), "validate_step", "2.4",
                "--branch", "test-branch",
                "--disposition", "deferred_nondeterministic",
                "--check-id", "pytest::test_flaky",
                "--monitor-envelope", "-",
            ],
            input=_monitor_defer_envelope(check_id="pytest::test_flaky"),
            cwd=str(project), capture_output=True, text=True, timeout=30,
            check=False,
        )
        assert proc.returncode == 1, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["valid"] is False
        assert not payload.get("deferred")

    def test_cli_archive_in_flight_exits_one(self, tmp_path):
        # An in-flight run cannot be archived → status=error → exit 1 so a
        # `set -e` / exit-code caller detects the refusal.
        project = tmp_path / "project"
        project.mkdir()
        script = self._make_project(project)
        state_dir = project / ".map" / "test-branch"
        state_dir.mkdir(parents=True)
        (state_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "workflow_status": "IN_PROGRESS",
                    "current_step_id": "2.3",
                    "current_step_phase": "ACTOR",
                }
            )
        )
        proc = subprocess.run(
            [sys.executable, str(script), "archive", "--branch", "test-branch"],
            cwd=str(project), capture_output=True, text=True, timeout=30,
            check=False,
        )
        assert proc.returncode == 1, proc.stdout
        assert json.loads(proc.stdout)["status"] == "error"
        assert (state_dir / "step_state.json").exists()  # in-flight never moved

    def test_cli_archive_completed_exits_zero(self, tmp_path):
        # A completed run archives cleanly → exit 0, active file gone.
        project = tmp_path / "project"
        project.mkdir()
        script = self._make_project(project)
        state_dir = project / ".map" / "test-branch"
        state_dir.mkdir(parents=True)
        (state_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "workflow_status": "WORKFLOW_COMPLETE",
                    "current_step_id": "COMPLETE",
                    "current_step_phase": "COMPLETE",
                }
            )
        )
        proc = subprocess.run(
            [sys.executable, str(script), "archive", "--branch", "test-branch"],
            cwd=str(project), capture_output=True, text=True, timeout=30,
            check=False,
        )
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert json.loads(proc.stdout)["status"] == "archived"
        assert not (state_dir / "step_state.json").exists()


class TestMonitorDispositionSingleSource:
    """Drift guard: the SSOT dict, the prompt, and the CLI must agree."""

    def test_prompt_names_every_disposition(self):
        monitor_prompt = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "agents" / "monitor.md"
        ).read_text(encoding="utf-8")
        for kind in map_orchestrator.MONITOR_DISPOSITIONS:
            assert kind in monitor_prompt, (
                f"disposition {kind!r} is in MONITOR_DISPOSITIONS but not named "
                "in the rendered Monitor prompt — prompt/parser drift"
            )

    def test_cli_disposition_help_mentions_supported_kinds(self):
        orchestrator_src = (ORCHESTRATOR_PATH / "map_orchestrator.py").read_text(
            encoding="utf-8"
        )
        # The --disposition argparse help must name each supported kind so the
        # CLI surface cannot silently drift from the routing policy.
        for kind in map_orchestrator.MONITOR_DISPOSITIONS:
            assert kind in orchestrator_src


class TestWaveMonitorFailed:
    """Tests for wave_monitor_failed() — per-subtask retry in wave execution."""

    def _make_wave_state(self, tmp_path, branch, **overrides):
        state = map_orchestrator.StepState()
        state.execution_waves = [["ST-001", "ST-002"]]
        state.current_wave_index = 0
        state.subtask_phases = {"ST-001": "2.4", "ST-002": "2.4"}
        state.subtask_retry_counts = {"ST-001": 0, "ST-002": 0}
        for k, v in overrides.items():
            setattr(state, k, v)
        state_file = tmp_path / ".map" / branch / "step_state.json"
        state.save(state_file)
        return state_file

    def test_subtask_phase_resets_to_actor(self, branch_dir, tmp_path):
        state_file = self._make_wave_state(tmp_path, branch_dir)
        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "fix")
        assert result["status"] == "retrying"
        assert result["current_phase"] == "ACTOR"
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_phases["ST-001"] == "2.3"

    def test_other_subtask_unaffected(self, branch_dir, tmp_path):
        state_file = self._make_wave_state(tmp_path, branch_dir)
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_phases["ST-002"] == "2.4"  # unchanged

    def test_retry_count_per_subtask(self, branch_dir, tmp_path):
        state_file = self._make_wave_state(tmp_path, branch_dir)
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_retry_counts["ST-001"] == 2
        assert state.subtask_retry_counts["ST-002"] == 0

    def test_wave_second_retry_requires_clean_retry(self, branch_dir, tmp_path):
        state_file = self._make_wave_state(tmp_path, branch_dir)
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "issue 1")
        result = map_orchestrator.wave_monitor_failed(
            "ST-001", branch_dir, "Repeated stale wave approach"
        )

        assert result["retry_isolation"] == "clean_retry_required"
        assert Path(result["retry_quarantine_path"]).exists()
        state = map_orchestrator.StepState.load(state_file)
        assert state.retry_isolation_status["ST-001"] == "clean_retry_required"
        wave = map_orchestrator.get_wave_step(branch_dir)
        subtask_map = {s["subtask_id"]: s for s in wave["subtasks"]}
        assert subtask_map["ST-001"]["retry_isolation"] == "clean_retry_required"
        assert "CLEAN_RETRY mode is required" in subtask_map["ST-001"]["instruction"]

    def test_max_retries_escalation(self, branch_dir, tmp_path):
        self._make_wave_state(
            tmp_path,
            branch_dir,
            subtask_retry_counts={"ST-001": 5, "ST-002": 0},
        )
        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        assert result["status"] == "max_retries"
        assert result["retry_count"] == 6

    def test_feedback_file_includes_subtask_id(self, branch_dir, tmp_path):
        self._make_wave_state(tmp_path, branch_dir)
        result = map_orchestrator.wave_monitor_failed(
            "ST-002", branch_dir, "type mismatch"
        )
        assert result["feedback_file"] is not None
        assert "ST-002" in result["feedback_file"]
        content = Path(result["feedback_file"]).read_text()
        assert "type mismatch" in content

    def test_wave_feedback_highlights_blocker_items_and_preserves_full_text(
        self, branch_dir, tmp_path
    ):
        # BLOCKER lines are surfaced first; full original text is always preserved.
        self._make_wave_state(tmp_path, branch_dir)
        feedback = "CRITICAL: security regression in auth flow\nNON-BLOCKING: documentation could be longer\ncosmetic: volume is high"

        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, feedback)

        content = Path(result["feedback_file"]).read_text()
        assert "security regression" in content
        # Full original text preserved — non-blocking lines are NOT dropped
        assert "documentation could be longer" in content
        assert "volume is high" in content
        assert "Full Monitor feedback:" in content

    def test_wave_feedback_non_english_preserved(self, branch_dir, tmp_path):
        # Non-English feedback must be forwarded in full, not replaced by a placeholder.
        self._make_wave_state(tmp_path, branch_dir)
        ru_feedback = (
            "YAML-якоря не выживают при слиянии Helm-значений: три Deployment "
            "ссылаются на несуществующий ConfigMap."
        )

        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, ru_feedback)

        content = Path(result["feedback_file"]).read_text()
        assert "YAML-якоря" in content
        assert "ConfigMap" in content
        assert "no BLOCKER-class feedback was detected" not in content

    def test_feedback_file_none_when_empty(self, branch_dir, tmp_path):
        self._make_wave_state(tmp_path, branch_dir)
        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        assert result["feedback_file"] is None

    def test_new_subtask_starts_at_zero_retries(self, branch_dir, tmp_path):
        """A subtask not in subtask_retry_counts starts at 0."""
        self._make_wave_state(
            tmp_path,
            branch_dir,
            subtask_retry_counts={},
        )
        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        assert result["retry_count"] == 1

    def test_max_retries_does_not_reset_subtask_phase(self, branch_dir, tmp_path):
        """subtask_phases is NOT modified when max_retries is hit."""
        state_file = self._make_wave_state(
            tmp_path,
            branch_dir,
            subtask_retry_counts={"ST-001": 5, "ST-002": 0},
        )
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "")
        state = map_orchestrator.StepState.load(state_file)
        assert state.subtask_phases["ST-001"] == "2.4"  # not reset on escalation

    def test_wave_monitor_failed_then_get_wave_step(self, branch_dir, tmp_path):
        """Integration: after wave_monitor_failed(), get_wave_step() shows ACTOR for reset subtask."""
        self._make_wave_state(tmp_path, branch_dir)
        map_orchestrator.wave_monitor_failed("ST-001", branch_dir, "fix type")
        result = map_orchestrator.get_wave_step(branch_dir)
        subtask_map = {s["subtask_id"]: s for s in result["subtasks"]}
        assert subtask_map["ST-001"]["step_id"] == "2.3"
        assert subtask_map["ST-001"]["phase"] == "ACTOR"
        assert subtask_map["ST-002"]["step_id"] == "2.4"  # unchanged


class TestReopenForFixes:
    """Tests for reopen_for_fixes() — transition COMPLETE → ACTOR for review fixes."""

    def _make_complete_state(self, tmp_path, branch, **overrides):
        state = map_orchestrator.StepState()
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.pending_steps = []
        state.completed_steps = ["1.0", "1.5", "1.6", "2.3", "2.4"]
        for k, v in overrides.items():
            setattr(state, k, v)
        state_file = tmp_path / ".map" / branch / "step_state.json"
        state.save(state_file)
        return state_file

    def test_reopens_from_complete_to_actor(self, branch_dir, tmp_path):
        state_file = self._make_complete_state(tmp_path, branch_dir)
        result = map_orchestrator.reopen_for_fixes(branch_dir, "fix type error")
        assert result["status"] == "reopened"
        assert result["current_phase"] == "ACTOR"
        state = map_orchestrator.StepState.load(state_file)
        assert state.current_step_phase == "ACTOR"
        assert state.current_step_id == "2.3"
        assert state.pending_steps == ["2.3", "2.4"]

    def test_resets_retry_count(self, branch_dir, tmp_path):
        self._make_complete_state(tmp_path, branch_dir, retry_count=3)
        map_orchestrator.reopen_for_fixes(branch_dir, "")
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state = map_orchestrator.StepState.load(state_file)
        assert state.retry_count == 0

    def test_rejects_in_progress_workflow(self, branch_dir, tmp_path):
        """Reopen must refuse when no completion signal is set."""
        state = map_orchestrator.StepState()
        state.current_step_id = "2.3"
        state.current_step_phase = "MONITOR"
        state.workflow_status = "IN_PROGRESS"
        state.pending_steps = ["2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.reopen_for_fixes(branch_dir, "")
        assert result["status"] == "error"
        assert "MONITOR" in result["message"]

    def test_accepts_canonical_workflow_status_with_stale_phase(
        self, branch_dir, tmp_path
    ):
        """Regression for the STACKLAND-1591 bug: reopen must accept a workflow
        marked complete via ``workflow_status == "WORKFLOW_COMPLETE"`` even
        when ``current_step_phase`` is stale (left on "ACTOR" by a partial
        ``jq`` mutation in older map-check)."""
        state = map_orchestrator.StepState()
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "ACTOR"  # stale!
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.pending_steps = []
        state.completed_steps = ["1.0", "1.5", "1.6", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.reopen_for_fixes(branch_dir, "fix REVIEW-1")
        assert result["status"] == "reopened", result
        assert result["current_phase"] == "ACTOR"

    def test_resets_workflow_status_and_completed_at(self, branch_dir, tmp_path):
        """Reopen must reset every completion field atomically — the same
        rule mark_workflow_complete enforces in the forward direction.
        Otherwise reopen leaves workflow_status="WORKFLOW_COMPLETE" while
        the workflow is back in ACTOR, defeating the whole point of using
        workflow_status as the canonical completion signal."""
        state = map_orchestrator.StepState()
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.completed_at = "2026-05-07T15:00:00Z"
        state.pending_steps = []
        state.completed_steps = ["1.0", "1.5", "1.6", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        map_orchestrator.reopen_for_fixes(branch_dir, "fix lint")

        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.workflow_status == "IN_PROGRESS"
        assert reloaded.completed_at is None
        assert reloaded.current_step_phase == "ACTOR"
        assert reloaded.current_step_id == "2.3"

    def test_no_state_file_returns_error(self, branch_dir, tmp_path):
        del tmp_path  # fixture side-effects (chdir) already applied via branch_dir
        result = map_orchestrator.reopen_for_fixes(branch_dir, "")
        assert result["status"] == "error"

    def test_feedback_file_written(self, branch_dir, tmp_path):
        self._make_complete_state(tmp_path, branch_dir)
        result = map_orchestrator.reopen_for_fixes(branch_dir, "fix DRY violation")
        assert result["feedback_file"] is not None
        content = Path(result["feedback_file"]).read_text()
        assert "fix DRY violation" in content

    def test_reopen_then_get_next_step(self, branch_dir, tmp_path):
        """Integration: after reopen, get_next_step returns ACTOR."""
        self._make_complete_state(tmp_path, branch_dir)
        map_orchestrator.reopen_for_fixes(branch_dir, "review fixes")
        result = map_orchestrator.get_next_step(branch_dir)
        assert result["phase"] == "ACTOR"
        assert result["step_id"] == "2.3"


class TestMarkWorkflowComplete:
    """Tests for mark_workflow_complete() — atomic completion transition.

    Replaces the historical ``jq '.current_state = "WORKFLOW_COMPLETE"'``
    mutation in map-check that left ``current_step_phase`` stale and broke
    ``reopen_for_fixes`` in the next ``/map-review``.
    """

    def test_atomic_transition_from_actor_phase(self, branch_dir, tmp_path):
        """Happy path: pending=[], stale ACTOR phase → all four canonical
        completion fields are set in a single save."""
        state = map_orchestrator.StepState()
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        state.workflow_status = "IN_PROGRESS"
        state.pending_steps = []
        state.completed_steps = ["1.0", "1.5", "1.6", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.mark_workflow_complete(branch_dir)

        assert result["status"] == "success", result
        assert result["workflow_status"] == "WORKFLOW_COMPLETE"
        assert result["current_step_id"] == "COMPLETE"
        assert result["current_step_phase"] == "COMPLETE"
        assert result["completed_at"].endswith("Z")

        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.workflow_status == "WORKFLOW_COMPLETE"
        assert reloaded.current_step_id == "COMPLETE"
        assert reloaded.current_step_phase == "COMPLETE"
        assert reloaded.completed_at == result["completed_at"]

    def test_rejects_when_pending_steps_remain(self, branch_dir, tmp_path):
        """Refuse to close an in-flight workflow."""
        state = map_orchestrator.StepState()
        state.pending_steps = ["2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.mark_workflow_complete(branch_dir)

        assert result["status"] == "error"
        assert "pending" in result["message"]

    def test_no_state_file_returns_error(self, branch_dir, tmp_path):
        del tmp_path  # fixture side-effects (chdir) already applied via branch_dir
        result = map_orchestrator.mark_workflow_complete(branch_dir)
        assert result["status"] == "error"

    def test_completed_at_round_trips_through_save_load(self, branch_dir, tmp_path):
        """completed_at must serialize via to_dict / from_dict."""
        state = map_orchestrator.StepState()
        state.pending_steps = []
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        map_orchestrator.mark_workflow_complete(branch_dir)
        reloaded = map_orchestrator.StepState.load(state_file)

        assert reloaded.completed_at is not None
        assert reloaded.completed_at.endswith("Z")

    def test_then_reopen_for_fixes_works(self, branch_dir, tmp_path):
        """Integration: mark_workflow_complete → reopen_for_fixes succeeds.

        This is the end-to-end path for ``/map-check`` → ``/map-review`` →
        post-review fix; it must work without manual state surgery.
        """
        state = map_orchestrator.StepState()
        state.pending_steps = []
        state.completed_steps = ["1.0", "1.5", "1.6", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        mark_result = map_orchestrator.mark_workflow_complete(branch_dir)
        assert mark_result["status"] == "success"

        reopen_result = map_orchestrator.reopen_for_fixes(branch_dir, "fix lint")
        assert reopen_result["status"] == "reopened"
        assert reopen_result["current_phase"] == "ACTOR"


class TestMarkSubtaskComplete:
    """mark_subtask_complete short-circuits a no-op / already-done subtask
    without spinning the full research→actor→monitor cycle."""

    def test_marks_current_subtask_advances_to_next(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.mark_subtask_complete(
            "ST-001", branch_dir, reason="already done historically"
        )
        assert result["status"] == "success"
        assert result["advanced_to"] == "ST-002"
        assert result["workflow_complete"] is False

        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-002"
        assert reloaded.subtask_index == 1
        assert reloaded.subtask_phases["ST-001"] == "COMPLETE"
        assert reloaded.subtask_results["ST-001"]["status"] == "no-op"
        assert "already done historically" in reloaded.subtask_results["ST-001"]["summary"]
        assert reloaded.pending_steps[0] == "2.2"  # fresh phases for next subtask

    def test_marks_last_subtask_closes_workflow(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.mark_subtask_complete("ST-001", branch_dir, "docs-only")
        assert result["workflow_complete"] is True
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.workflow_status == "WORKFLOW_COMPLETE"
        assert reloaded.current_step_phase == "COMPLETE"
        assert reloaded.completed_at is not None
        assert reloaded.pending_steps == []

    def test_rejects_unknown_subtask(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.mark_subtask_complete("ST-999", branch_dir, "x")
        assert result["status"] == "error"
        assert "ST-999" in result["message"]

    def test_marking_non_current_subtask_only_records_phase(
        self, branch_dir, tmp_path
    ):
        """Marking a NON-current subtask records the no-op result and phase
        without disturbing the workflow cursor."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.mark_subtask_complete("ST-002", branch_dir, "future no-op")
        assert result["status"] == "success"
        assert result["advanced_to"] is None
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-001"
        assert reloaded.subtask_phases["ST-002"] == "COMPLETE"
        assert reloaded.subtask_results["ST-002"]["status"] == "no-op"


class TestValidateStepIdempotency:
    """validate_step X is idempotent when X already in completed_steps —
    re-running after a double-advance no longer explodes with 'Step mismatch'."""

    def test_idempotent_no_op_when_already_completed(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.validate_step("2.3", branch_dir)
        assert result["valid"] is True, result
        assert result.get("idempotent") is True
        # state.current_step_id stays at 2.4, not regressed:
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_step_id == "2.4"


class TestValidateStepInterSubtaskBoundary:
    """validate_step at the boundary between subtasks must signal
    ADVANCE_SUBTASK, not COMPLETE — the workflow is NOT done while more
    subtasks remain in subtask_sequence (regression for #4)."""

    def test_inter_subtask_advances_atomically_to_next_research(
        self, branch_dir, tmp_path
    ):
        """Previously returned an ADVANCE_SUBTASK sentinel that left
        next-subtask fields unpopulated. Now validate_step("2.4") on
        inter-subtask boundary atomically bumps subtask_index, resets
        completed/pending, sets current_step_id to next subtask's 2.2."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        # plant blueprint for the auto-mutation-boundary check to be a no-op
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        state_file = plan_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is True
        assert result["next_step"] == "2.2", result
        assert result["subtask_advanced_from"] == "ST-001"
        assert result["subtask_advanced_to"] == "ST-002"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.subtask_index == 1
        assert reloaded.current_subtask_id == "ST-002"
        assert reloaded.current_step_id == "2.2"
        assert reloaded.current_step_phase == "RESEARCH"
        assert reloaded.completed_steps == []
        assert "2.2" in reloaded.pending_steps
        assert reloaded.workflow_status == "IN_PROGRESS"

    def test_final_subtask_still_returns_complete(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["next_step"] == "COMPLETE"

    def test_final_subtask_sets_workflow_status_complete_atomically(
        self, branch_dir, tmp_path
    ):
        """Regression: validate_step's sequential terminal must set
        workflow_status=WORKFLOW_COMPLETE + completed_at atomically with
        phase=COMPLETE — not leave the run at IN_PROGRESS. A stale IN_PROGRESS
        silently disabled every WORKFLOW_COMPLETE-gated hook (scrub-internal-ids,
        teardown/archival) on the most common completion path.
        """
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="proceed"
        )
        assert result["next_step"] == "COMPLETE"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_step_phase == "COMPLETE"
        assert reloaded.current_step_id == "COMPLETE"
        assert reloaded.workflow_status == "WORKFLOW_COMPLETE"
        assert reloaded.completed_at is not None


class TestArchiveCompletedWorkflow:
    """archive_completed_workflow retires a finished run so the branch
    fail-opens; it is idempotent and refuses to touch an in-flight run.
    initialize_workflow auto-archives a prior COMPLETED run on branch reuse.
    """

    def test_noop_when_no_state_file(self, branch_dir, tmp_path):
        del tmp_path
        result = map_orchestrator.archive_completed_workflow(branch_dir)
        assert result["status"] == "noop"

    def test_refuses_in_flight_workflow(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.archive_completed_workflow(branch_dir)
        assert result["status"] == "error"
        assert state_file.exists()  # in-flight run is never moved

    def test_archives_completed_workflow(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.archive_completed_workflow(branch_dir)
        assert result["status"] == "archived"
        assert not state_file.exists()  # active file gone -> gate fail-opens
        archive = Path(result["archive_file"])
        assert archive.exists()
        assert archive.name.startswith("step_state.completed-")

    def test_idempotent_second_call_is_noop(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        first = map_orchestrator.archive_completed_workflow(branch_dir)
        assert first["status"] == "archived"
        second = map_orchestrator.archive_completed_workflow(branch_dir)
        assert second["status"] == "noop"  # nothing active left to archive

    def test_initialize_auto_archives_prior_completed(self, branch_dir, tmp_path):
        prior = map_orchestrator.StepState()
        prior.workflow_status = "WORKFLOW_COMPLETE"
        prior.current_step_id = "COMPLETE"
        prior.current_step_phase = "COMPLETE"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        prior.save(state_file)
        result = map_orchestrator.initialize_workflow("new task", branch_dir)
        assert result["status"] == "initialized"
        assert "archived_prior" in result
        fresh = map_orchestrator.StepState.load(state_file)
        assert fresh.workflow_status != "WORKFLOW_COMPLETE"  # not the prior run
        assert Path(result["archived_prior"]).exists()  # prior preserved

    def test_initialize_does_not_archive_in_flight(self, branch_dir, tmp_path):
        prior = map_orchestrator.StepState()
        prior.workflow_status = "IN_PROGRESS"
        prior.current_step_id = "2.3"
        prior.current_step_phase = "ACTOR"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        prior.save(state_file)
        result = map_orchestrator.initialize_workflow("new task", branch_dir)
        assert "archived_prior" not in result
        archives = list(
            (tmp_path / ".map" / branch_dir).glob("step_state.completed-*.json")
        )
        assert archives == []


class TestAbandonWorkflow:
    """abandon_workflow provides an escape hatch for stuck/in-flight workflows.

    Unlike archive_completed_workflow (which refuses non-terminal states),
    abandon_workflow can retire any workflow including INITIALIZED ones with
    an empty subtask_sequence — the common stuck case from issue #360.
    """

    def test_noop_when_no_state_file(self, branch_dir, tmp_path):
        del tmp_path
        result = map_orchestrator.abandon_workflow(branch_dir)
        assert result["status"] == "noop"

    def test_abandons_in_flight_workflow(self, branch_dir, tmp_path):
        """abandon_workflow can retire an in-flight (ACTOR-phase) workflow —
        unlike archive_completed_workflow which refuses non-terminal states.
        """
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.abandon_workflow(branch_dir)
        assert result["status"] == "abandoned"
        assert not state_file.exists()  # active file gone -> gate fail-opens
        abandon_file = Path(result["abandon_file"])
        assert abandon_file.exists()
        assert abandon_file.name.startswith("step_state.abandoned-")
        assert result["phase_at_abandon"] == "ACTOR"

    def test_abandons_initialized_workflow_with_empty_subtask_sequence(
        self, branch_dir, tmp_path
    ):
        """Core #360 repro: a freshly-initialized workflow with an empty
        subtask_sequence (stuck INITIALIZED state) can now be retired via
        abandon_workflow.  archive_completed_workflow would have refused.
        """
        state = map_orchestrator.StepState()
        state.workflow_status = "INITIALIZED"
        state.current_step_phase = "DECOMPOSE"
        state.subtask_sequence = []
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.abandon_workflow(branch_dir)
        assert result["status"] == "abandoned"
        assert not state_file.exists()
        assert Path(result["abandon_file"]).name.startswith("step_state.abandoned-")

    def test_delegates_to_archive_when_already_complete(self, branch_dir, tmp_path):
        """abandon_workflow on a WORKFLOW_COMPLETE run delegates to
        archive_completed_workflow so terminal runs get the .completed- suffix.
        """
        state = map_orchestrator.StepState()
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.abandon_workflow(branch_dir)
        assert result["status"] == "archived"  # delegated to archive path
        assert not state_file.exists()
        archive_file = Path(result["archive_file"])
        assert archive_file.name.startswith("step_state.completed-")

    def test_idempotent_second_call_is_noop(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        first = map_orchestrator.abandon_workflow(branch_dir)
        assert first["status"] == "abandoned"
        second = map_orchestrator.abandon_workflow(branch_dir)
        assert second["status"] == "noop"

    def test_cli_abandon_in_flight_exits_zero(self, tmp_path):
        """CLI: `abandon` on an in-flight run exits 0 (not 1 like archive on error)."""
        project = tmp_path / "project"
        project.mkdir()
        script = self._make_project(project)
        state_dir = project / ".map" / "test-branch"
        state_dir.mkdir(parents=True)
        (state_dir / "step_state.json").write_text(
            json.dumps(
                {
                    "workflow_status": "IN_PROGRESS",
                    "current_step_id": "2.3",
                    "current_step_phase": "ACTOR",
                }
            )
        )
        proc = subprocess.run(
            [sys.executable, str(script), "abandon", "--branch", "test-branch"],
            cwd=str(project), capture_output=True, text=True, timeout=30,
            check=False,
        )
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        payload = json.loads(proc.stdout)
        assert payload["status"] == "abandoned"
        assert not (state_dir / "step_state.json").exists()

    @staticmethod
    def _make_project(root: Path) -> Path:
        import shutil

        scripts_dir = root / ".map" / "scripts"
        scripts_dir.mkdir(parents=True)
        for py_file in ORCHESTRATOR_PATH.glob("*.py"):
            shutil.copy(py_file, scripts_dir / py_file.name)
        return scripts_dir / "map_orchestrator.py"


class TestValidateStepResearchEnforcement:
    """RESEARCH (2.2) is documented MANDATORY; validate_step 2.2 must reject
    when no research artifact exists for the current subtask."""

    def test_rejects_when_no_research_artifact(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.validate_step("2.2", branch_dir)
        assert result["valid"] is False
        assert "RESEARCH artifact invalid" in result["message"]

    def test_accepts_when_research_artifact_present(
        self, branch_dir, tmp_path
    ):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        _write_valid_research_artifact(tmp_path, branch_dir, "ST-001")
        result = map_orchestrator.validate_step("2.2", branch_dir)
        assert result["valid"] is True, result
        assert result["next_step"] == "2.3"

    def test_rejects_malformed_research_artifact(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        research_dir = tmp_path / ".map" / branch_dir / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "ST-001__actor.md").write_text("findings", encoding="utf-8")

        result = map_orchestrator.validate_step("2.2", branch_dir)

        assert result["valid"] is False
        assert "strict JSON" in result["message"]


class TestRecordSubtaskResultAutoCommitSha:
    """record_subtask_result auto-detects current HEAD commit when caller
    didn't pass --commit-sha. Strengthens downstream provenance — every
    recorded subtask result now carries a SHA the operator can git-show."""

    def test_auto_detects_head_commit_sha(self, branch_dir, tmp_path, monkeypatch):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        # Init a git repo with one commit so HEAD resolves.
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        sha_proc = _sp.run(
            ["git", "log", "-1", "--format=%H"], cwd=tmp_path,
            capture_output=True, text=True,
            check=False,
        )
        expected_sha = sha_proc.stdout.strip()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        result = map_orchestrator.record_subtask_result(
            "ST-001", branch_dir, files_changed=[], status="valid",
            summary="auto sha", commit_sha=None,
        )
        assert result["status"] == "success"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.last_subtask_commit_sha == expected_sha

    def test_explicit_commit_sha_wins(self, branch_dir, tmp_path, monkeypatch):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        map_orchestrator.record_subtask_result(
            "ST-001", branch_dir, files_changed=[], status="valid",
            summary="x", commit_sha="cafebabe",
        )
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.last_subtask_commit_sha == "cafebabe"


class TestRecordSubtaskResultGitignoredArtifact:
    """record_subtask_result must NOT raise a 'Possible Actor truncation'
    warning for declared files that are gitignored-but-present on disk (e.g.
    .map/ workflow artifacts like spike docs). They never appear in git
    diff/status by design — that is intentional, not truncation."""

    def _init_git_repo(self, tmp_path):
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / ".gitignore").write_text(".map/\n")
        (tmp_path / "seed.txt").write_text("seed")
        (tmp_path / "tracked.py").write_text("x = 1\n")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        # Second (non-root) commit so HEAD has a parent and `git diff-tree`
        # yields a NON-empty diff_paths. Without this, a root commit produces an
        # empty diff and files_not_in_diff is never computed — the gitignore
        # test would then pass vacuously without exercising the filter.
        (tmp_path / "seed.txt").write_text("seed v2")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "second"], cwd=tmp_path, capture_output=True, check=False)

    def test_gitignored_artifact_not_flagged(self, branch_dir, tmp_path, monkeypatch):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        self._init_git_repo(tmp_path)
        # A real deliverable that exists on disk but is gitignored (.map/**).
        artifact = tmp_path / ".map" / branch_dir / "spike_st001.md"
        artifact.write_text("spike verdict", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        result = map_orchestrator.record_subtask_result(
            "ST-001", branch_dir,
            files_changed=[f".map/{branch_dir}/spike_st001.md"],
            status="valid", summary="spike", commit_sha=None,
        )
        assert result["status"] == "success"
        # No false truncation warning, no files_not_in_diff for the gitignored file.
        assert "files_not_in_diff" not in result, result
        assert "Possible Actor truncation" not in result.get("warning", ""), result

    def test_non_gitignored_unchanged_tracked_file_still_flagged(
        self, branch_dir, tmp_path, monkeypatch
    ):
        """Negative control (proves the filter is SPECIFIC): a tracked file that
        exists, is NOT gitignored, and was not touched by this subtask's diff
        still surfaces in files_not_in_diff — the gitignore filter must not be a
        blanket suppression."""
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        self._init_git_repo(tmp_path)  # tracked.py committed, unchanged in HEAD
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        result = map_orchestrator.record_subtask_result(
            "ST-001", branch_dir,
            files_changed=["tracked.py"],
            status="valid", summary="x", commit_sha=None,
        )
        assert result["status"] == "success"
        assert result.get("files_not_in_diff") == ["tracked.py"], result


class TestValidateStepTransactionalMonitor:
    """validate_step('2.4') now implicitly closes pending 2.3 (ACTOR) so
    callers don't get 'Step mismatch: expected 2.3' when they jump straight
    from Monitor pass to validation."""

    def test_two_four_auto_closes_pending_two_three(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        # Mid-flight: cursor at 2.3, both 2.3 and 2.4 still pending.
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        state.completed_steps = ["2.2"]
        state.pending_steps = ["2.3", "2.4"]
        # Plant required research artifact so the 2.2-style enforcement
        # never blocks (we're past 2.2 here).
        research_dir = tmp_path / ".map" / branch_dir / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "ST-001__actor.md").write_text("ok")
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        # Jump straight to 2.4 — historically this returned Step mismatch.
        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is True, result
        reloaded = map_orchestrator.StepState.load(state_file)
        assert "2.3" in reloaded.completed_steps
        assert "2.4" in reloaded.completed_steps


class TestRecordSubtaskResultCli:
    """record_subtask_result is the canonical write path for subtask outcomes;
    the earlier release advised this in skill docs but exposed no CLI, so
    callers either reached into Python or relied on indirect recording."""

    def test_records_result_to_step_state(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.record_subtask_result(
            "ST-001", branch_dir, files_changed=["a.py"], status="valid",
            summary="all green", commit_sha="abc123",
        )
        assert result["status"] == "success"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.subtask_results["ST-001"]["status"] == "valid"
        assert reloaded.subtask_results["ST-001"]["files_changed"] == ["a.py"]
        assert reloaded.last_subtask_commit_sha == "abc123"


class TestFinalizePlan:
    """finalize_plan bumps artifact_manifest.stages.plan to 'complete' so
    /map-plan stops leaving the stage stuck in 'partial' after artifacts ship."""

    def test_bumps_partial_to_complete_when_artifacts_present(self, branch_dir, tmp_path):
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"task_plan_{branch_dir}.md").write_text("# plan\n### ST-001\n")
        (plan_dir / "blueprint.json").write_text(json.dumps({"subtasks": [{"id": "ST-001"}]}))
        (plan_dir / "artifact_manifest.json").write_text(json.dumps({
            "stages": {"plan": {"status": "partial"}}
        }))
        result = map_orchestrator.finalize_plan(branch_dir)
        assert result["status"] == "success"
        manifest = json.loads((plan_dir / "artifact_manifest.json").read_text())
        assert manifest["stages"]["plan"]["status"] == "complete"

    def test_noop_without_artifacts(self, branch_dir, tmp_path):
        del tmp_path  # fixture side-effects (chdir) already applied via branch_dir
        result = map_orchestrator.finalize_plan(branch_dir)
        assert result["status"] == "noop"


class TestValidateStepAutoMutationBoundary:
    """validate_step('2.4') now runs validate_mutation_boundary so scope
    leaks can't silently slip past MONITOR. Warn-only by default; STRICT mode
    escalates."""

    def test_strict_mode_rejects_violation(self, branch_dir, tmp_path, monkeypatch):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        # Plant blueprint with ONE expected file but make repo have an
        # untracked extra to trip the boundary check.
        plan_dir = tmp_path / ".map" / branch_dir
        (plan_dir / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["a.py"]}],
        }))
        # Init real git repo so validate_mutation_boundary's git calls work.
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "leak.py").write_text("nope")  # untracked: scope leak
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is False
        assert "Mutation-boundary violation" in result["message"]

    def test_warning_routes_feedback_to_actor_once(self, branch_dir, tmp_path, monkeypatch):
        """A non-strict scope leak never hard-fails the gate. The FIRST call with
        a warning records the subtask in scope_feedback_subtasks and surfaces the
        out-of-scope files as advisory scope_warning metadata in the success
        response (valid=True). The SECOND call with the same leak advances normally
        with no scope_warning (guard prevents repeated advisory noise)."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        plan_dir = tmp_path / ".map" / branch_dir
        (plan_dir / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["a.py"]}],
        }))
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "leak.py").write_text("nope")  # untracked: out-of-scope leak
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)

        r1 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r1["valid"] is True, r1  # advisory only — gate passes on first occurrence
        assert "scope_warning" in r1, r1
        assert "leak.py" in str(r1["scope_warning"].get("unexpected", [])), r1
        persisted = map_orchestrator.StepState.load(state_file)
        assert "ST-001" in persisted.scope_feedback_subtasks, persisted.scope_feedback_subtasks

        # Same leak persists; second call: guard already fired, no scope_warning metadata.
        r2 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r2["valid"] is True, r2
        assert "scope_warning" not in r2, r2

    def test_false_progress_routes_feedback_when_nothing_changed(
        self, branch_dir, tmp_path, monkeypatch
    ):
        """Correctness analog of the scope nudge: MONITOR closing a subtask that
        declares affected_files but changed NOTHING is false-progress — routed
        back to the Actor once (valid=False + 'False-progress'), then the guard
        (progress_feedback_subtasks) lets a re-validate pass."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        plan_dir = tmp_path / ".map" / branch_dir
        (plan_dir / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["a.py"]}],
        }))
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        # NOTHING changed for ST-001 — a.py never created, no edits at all.
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)

        r1 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r1["valid"] is False, r1
        assert "False-progress" in r1["message"], r1
        persisted = map_orchestrator.StepState.load(state_file)
        assert "ST-001" in persisted.progress_feedback_subtasks, persisted.progress_feedback_subtasks

        # Guard lets the re-validate pass (bounded to one nudge per subtask).
        r2 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r2["valid"] is True, r2

    def test_committed_subtask_passes_2_4_without_false_progress(
        self, branch_dir, tmp_path, monkeypatch
    ):
        """#162: the documented per-subtask close order is
        commit -> record_subtask_result --commit-sha -> validate_step 2.4. After
        the commit the working tree is clean and last_subtask_commit_sha is THIS
        subtask's own commit. validate_step 2.4 must NOT fire false-progress on
        the FIRST call (no redundant second call): the committed work counts as
        the subtask's mutation surface via the parent re-base."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.pending_steps = ["2.4"]
        state.completed_steps = ["2.2", "2.3"]
        plan_dir = tmp_path / ".map" / branch_dir
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "title": "x", "affected_files": ["a.py"]}],
        }))
        import subprocess as _sp
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True, check=False)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "seed.txt"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=False)
        # ST-001's work IS implemented and committed (the documented order).
        (tmp_path / "a.py").write_text("x = 1\n")
        _sp.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True, check=False)
        _sp.run(["git", "commit", "-m", "ST-001"], cwd=tmp_path, capture_output=True, check=False)
        sha = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True,
            check=False,
        ).stdout.strip()
        # Mimic record_subtask_result --commit-sha <SHA>.
        state.record_subtask_result("ST-001", ["a.py"], "valid", commit_sha=sha)
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)

        r1 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r1["valid"] is True, r1  # NO false-progress on the first call
        persisted = map_orchestrator.StepState.load(state_file)
        assert "ST-001" not in persisted.progress_feedback_subtasks, (
            persisted.progress_feedback_subtasks
        )


class TestPeekCurrentStep:
    """peek_current_step is the read-only recovery escape hatch for the case
    where validate_step rejects a double-advance with 'Step mismatch: expected
    Y, got X'. It returns the same shape as get_next_step but never saves the
    state, so callers can recover the canonical step id without risk of
    further mutating it."""

    def test_returns_pending_head_without_saving(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.2"
        state.current_step_phase = "RESEARCH"
        state.pending_steps = ["2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        mtime_before = state_file.stat().st_mtime_ns
        result = map_orchestrator.peek_current_step(branch_dir)
        mtime_after = state_file.stat().st_mtime_ns

        assert mtime_before == mtime_after, "peek must not write state"
        assert result["step_id"] == "2.3"
        assert result["phase"] == "ACTOR"
        assert result["is_complete"] is False
        assert result["current_subtask"] == "ST-001"

    def test_returns_complete_when_workflow_complete(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        result = map_orchestrator.peek_current_step(branch_dir)
        assert result["is_complete"] is True
        assert result["step_id"] == "COMPLETE"


class TestGetNextStepWorkflowCompleteShortCircuit:
    """Regression: get_next_step must honor workflow_status == 'WORKFLOW_COMPLETE'.

    Observed: after a successful run, if the state file's pending_steps was
    repopulated by a partial recovery path while workflow_status was already
    'WORKFLOW_COMPLETE', get_next_step would walk the per-step branches and
    return a fresh step (e.g. '2.2 RESEARCH for ST-015') instead of reporting
    completion. The function checked 'CONTRACT_READY' upfront but NOT
    'WORKFLOW_COMPLETE'. The completion signal should be authoritative.
    """

    def test_returns_complete_when_workflow_status_marked_complete(
        self, branch_dir, tmp_path
    ):
        """Even with non-empty pending_steps, workflow_status=='WORKFLOW_COMPLETE'
        must short-circuit to is_complete=True."""
        state = map_orchestrator.StepState()
        state.workflow_status = "WORKFLOW_COMPLETE"
        state.current_step_id = "COMPLETE"
        state.current_step_phase = "COMPLETE"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        # Simulate a stale repopulation of pending_steps (the bug condition).
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.get_next_step(branch_dir)

        assert result["is_complete"] is True, (
            f"get_next_step must short-circuit on WORKFLOW_COMPLETE, got {result}"
        )
        assert result["step_id"] == "COMPLETE"
        assert result["phase"] == "COMPLETE"

    def test_in_progress_status_still_returns_next_step(
        self, branch_dir, tmp_path
    ):
        """Negative control: IN_PROGRESS state must still drive normal flow."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.pending_steps = ["2.2", "2.3", "2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.get_next_step(branch_dir)

        assert result["is_complete"] is False
        assert result["step_id"] == "2.2"


class TestBackfillSubtaskIds:
    """Self-describing-record fix: record_subtask_result entries now carry a
    redundant ``subtask_id`` field so downstream reporters/log shippers
    that forward entries individually stop receiving ``subtask_id: null``.
    backfill_subtask_ids walks legacy state and writes the field where
    missing.
    """

    def test_record_writes_subtask_id_on_entry(self):
        state = map_orchestrator.StepState()
        state.record_subtask_result(
            "ST-001", ["a.py"], "valid", "ok", commit_sha="abc"
        )
        entry = state.subtask_results["ST-001"]
        assert entry["subtask_id"] == "ST-001"
        assert entry["commit_sha"] == "abc"

    def test_backfill_populates_legacy_entries(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001", "ST-002"]
        # Legacy entry shape (no subtask_id field — what old states have).
        state.subtask_results = {
            "ST-001": {"files_changed": ["a.py"], "status": "valid"},
            "ST-002": {"files_changed": ["b.py"], "status": "valid", "subtask_id": "ST-002"},
        }
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.backfill_subtask_ids(branch_dir)
        assert result["status"] == "success"
        assert result["updated"] == 1
        assert result["updated_ids"] == ["ST-001"]
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.subtask_results["ST-001"]["subtask_id"] == "ST-001"
        # Already-correct entry left untouched.
        assert reloaded.subtask_results["ST-002"]["subtask_id"] == "ST-002"

    def test_backfill_is_idempotent(self, branch_dir, tmp_path):
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-001", ["a.py"], "valid")
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        first = map_orchestrator.backfill_subtask_ids(branch_dir)
        assert first["updated"] == 0
        second = map_orchestrator.backfill_subtask_ids(branch_dir)
        assert second["updated"] == 0

    def test_backfill_error_when_state_missing(self, branch_dir, tmp_path):
        # No step_state.json present
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        if sf.exists():
            sf.unlink()
        result = map_orchestrator.backfill_subtask_ids(branch_dir)
        assert result["status"] == "error"


class TestSubtaskResults:
    """Tests for StepState subtask_results and last_subtask_commit_sha fields."""

    def test_subtask_results_default_empty(self):
        state = map_orchestrator.StepState()
        assert state.subtask_results == {}
        assert state.last_subtask_commit_sha is None

    def test_record_subtask_result(self):
        state = map_orchestrator.StepState()
        state.record_subtask_result(
            "ST-001", ["a.py", "b.py"], "valid", "All tests pass"
        )
        assert "ST-001" in state.subtask_results
        assert state.subtask_results["ST-001"]["files_changed"] == ["a.py", "b.py"]
        assert state.subtask_results["ST-001"]["status"] == "valid"
        assert state.subtask_results["ST-001"]["summary"] == "All tests pass"

    def test_record_subtask_result_with_commit_sha(self):
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-001", ["a.py"], "valid", commit_sha="abc123")
        assert state.subtask_results["ST-001"]["status"] == "valid"
        assert state.last_subtask_commit_sha == "abc123"

    def test_record_subtask_result_without_commit_sha_preserves_existing(self):
        state = map_orchestrator.StepState()
        state.last_subtask_commit_sha = "old_sha"
        state.record_subtask_result("ST-002", ["b.py"], "valid")
        assert state.last_subtask_commit_sha == "old_sha"

    def test_serialize_deserialize_roundtrip(self):
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-001", ["x.py"], "valid")
        state.last_subtask_commit_sha = "abc123def"

        data = state.to_dict()
        assert data["subtask_results"]["ST-001"]["status"] == "valid"
        assert data["last_subtask_commit_sha"] == "abc123def"

        restored = map_orchestrator.StepState.from_dict(data)
        assert restored.subtask_results["ST-001"]["files_changed"] == ["x.py"]
        assert restored.last_subtask_commit_sha == "abc123def"

    def test_save_load_roundtrip(self, tmp_path):
        state_file = tmp_path / "step_state.json"
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-002", ["c.py"], "invalid", "Tests failed")
        state.last_subtask_commit_sha = "deadbeef"
        state.save(state_file)

        loaded = map_orchestrator.StepState.load(state_file)
        assert loaded.subtask_results["ST-002"]["status"] == "invalid"
        assert loaded.last_subtask_commit_sha == "deadbeef"

    def test_backward_compat_missing_fields(self):
        """Old step_state.json without new fields should load safely."""
        old_data = {"workflow": "map-efficient", "started_at": "2026-01-01"}
        restored = map_orchestrator.StepState.from_dict(old_data)
        assert restored.subtask_results == {}
        assert restored.last_subtask_commit_sha is None

    def test_record_subtask_result_empty_files(self):
        """record_subtask_result with empty files_changed list."""
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-003", [], "valid", "No files changed")
        assert state.subtask_results["ST-003"]["files_changed"] == []
        assert state.subtask_results["ST-003"]["status"] == "valid"
        assert state.subtask_results["ST-003"]["summary"] == "No files changed"

    def test_record_subtask_result_empty_summary(self):
        """record_subtask_result with empty summary string."""
        state = map_orchestrator.StepState()
        state.record_subtask_result("ST-004", ["x.py"], "valid")
        assert state.subtask_results["ST-004"]["summary"] == ""


class TestValidateStepRecommendationCLIRegistration:
    """Regression: --recommendation must be a registered argparse option,
    not scraped from extra_args. The scrape implementation was bypassed
    by argparse strict mode (unknown -- flags fail before reaching
    extra_args), so the skill instruction was broken in practice.
    """

    def test_cli_accepts_recommendation_flag(self, branch_dir, tmp_path):
        del branch_dir, tmp_path  # CLI subprocess uses its own cwd
        script = (
            Path(__file__).parent.parent
            / "src" / "mapify_cli" / "templates" / "map" / "scripts"
            / "map_orchestrator.py"
        )
        # Help text exposes the flag; no argparse error.
        result = subprocess.run(
            [sys.executable, str(script), "validate_step", "--help"],
            capture_output=True, text=True, timeout=10,
            check=False,
        )
        # The script doesn't have per-command help, but the parent parser
        # must list --recommendation among its options.
        result_root = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=10,
            check=False,
        )
        assert "--recommendation" in result_root.stdout, (
            f"--recommendation missing from CLI options. stdout: {result_root.stdout!r}"
        )
        # Direct invocation with the flag must NOT exit with argparse's
        # exit(2) "unrecognized arguments" — even if state load fails,
        # argparse parsing itself must succeed.
        assert "unrecognized arguments: --recommendation" not in result.stderr


class TestGetNextStepResearchSkipWarning:
    """Fix #3 (2026-05-27): if get_next_step is about to return 2.3
    (ACTOR) for the current subtask but 2.2 (RESEARCH) was never
    completed AND no research artifact exists on disk AND TDD
    auto-skip wasn't the path, emit a soft warning in the response.
    Does NOT block (back-compat with legacy TDD auto-skip flow) but
    surfaces the silent skip so operator sees it. Catches the final-
    subtask silent skip that hit ST-016 in a production run.
    """

    def test_warning_emitted_when_about_to_return_actor_without_artifact(
        self, branch_dir, tmp_path
    ):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-016"]
        state.current_subtask_id = "ST-016"
        state.current_step_id = "2.3"
        state.current_step_phase = "ACTOR"
        # Drift: pending starts at 2.3, 2.2 NOT in completed_steps,
        # no research artifact on disk, no TDD skip in history.
        state.completed_steps = []
        state.skipped_steps = []
        state.pending_steps = ["2.3", "2.4"]
        state.plan_approved = True
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(sf)

        result = map_orchestrator.get_next_step(branch_dir)
        # Still returns 2.3 (no auto-reinsertion — would break TDD flow).
        assert result["step_id"] == "2.3"
        # But warning surfaces the silent skip.
        assert "warning" in result, result
        assert "RESEARCH" in result["warning"]
        assert "ST-016" in result["warning"]

    def test_no_warning_when_research_artifact_present(
        self, branch_dir, tmp_path
    ):
        """When research artifact IS on disk, no warning — operator did
        the research, just didn't record completion."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-016"]
        state.current_subtask_id = "ST-016"
        state.current_step_id = "2.3"
        state.completed_steps = []
        state.pending_steps = ["2.3", "2.4"]
        state.plan_approved = True
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(sf)
        research_dir = tmp_path / ".map" / branch_dir / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "ST-016__actor.md").write_text("findings")

        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "2.3"
        assert "warning" not in result

    def test_no_warning_when_tdd_skip_in_history(
        self, branch_dir, tmp_path
    ):
        """TDD-auto-skip path (2.25/2.26 in skipped_steps) is the
        documented legitimate way to reach 2.3 without 2.2 — must NOT
        trigger the warning."""
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-016"]
        state.current_subtask_id = "ST-016"
        state.current_step_id = "2.3"
        state.skipped_steps = ["2.25", "2.26"]
        state.pending_steps = ["2.3", "2.4"]
        state.plan_approved = True
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(sf)

        result = map_orchestrator.get_next_step(branch_dir)
        assert result["step_id"] == "2.3"
        assert "warning" not in result


class TestValidateStepRecommendationOmittedWarning:
    """ST-003: closing 2.4 without --recommendation is now a hard-fail so the
    verdict-consistency gate cannot be bypassed. The orchestrator returns
    valid=False with recommendation_required=True when recommendation is absent.
    """

    def _seed(self, branch_dir: str, tmp_path: Path) -> Path:
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(sf)
        return sf

    def test_hard_fail_when_recommendation_omitted(
        self, branch_dir, tmp_path
    ):
        """ST-003: omitting --recommendation is now a hard-fail (valid=False),
        not a soft warning. Enforces the verdict-consistency gate structurally."""
        self._seed(branch_dir, tmp_path)
        result = map_orchestrator.validate_step("2.4", branch_dir)
        assert result["valid"] is False, result
        assert result.get("recommendation_required") is True, result
        assert "--recommendation" in result["message"]

    def test_no_error_when_recommendation_passed(
        self, branch_dir, tmp_path
    ):
        self._seed(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="proceed"
        )
        assert result["valid"] is True
        assert result.get("recommendation_required") is None


class TestValidateStepRecommendationContract:
    """Fix #6: validate_step 2.4 now enforces the Monitor recommendation
    contract orchestrator-side. Skill rule "valid=true +
    recommendation∈{revise,block,needs_investigation} = fail" used to be
    prose-only; now passing --recommendation revise|block|needs_investigation
    to validate_step 2.4 makes it return valid=false even when the step
    would otherwise close cleanly.
    """

    def _seed_state(self, branch_dir: str, tmp_path: Path) -> Path:
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        return state_file

    def test_revise_recommendation_rejects(self, branch_dir, tmp_path):
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="revise"
        )
        assert result["valid"] is False
        assert result["recommendation"] == "revise"
        assert "revise" in result["message"]

    def test_block_recommendation_rejects(self, branch_dir, tmp_path):
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="BLOCK"
        )
        assert result["valid"] is False
        assert result["recommendation"] == "block"

    def test_needs_investigation_rejects(self, branch_dir, tmp_path):
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="needs_investigation"
        )
        assert result["valid"] is False

    def test_proceed_recommendation_does_not_block(self, branch_dir, tmp_path):
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="proceed"
        )
        assert result["valid"] is True

    def test_missing_recommendation_is_now_hard_fail(
        self, branch_dir, tmp_path
    ):
        # ST-003: omitting recommendation is now a hard-fail, not backward-compat.
        # Callers MUST pass --recommendation to close 2.4.
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.validate_step("2.4", branch_dir)
        assert result["valid"] is False
        assert result.get("recommendation_required") is True


class TestMarkSubtaskCompleteKind:
    """Audit-ledger fix #10: mark_subtask_complete now classifies the
    short-circuit via --kind so post-run reports can group "deferred stubs"
    apart from "no-op auto-detected" apart from "done in a prior PR".
    """

    def _seed_state(self, branch_dir: str, tmp_path: Path) -> Path:
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)
        return state_file

    def test_default_kind_is_noop_backward_compat(self, branch_dir, tmp_path):
        state_file = self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.mark_subtask_complete(
            "ST-002", branch_dir, "auto-detected no-op"
        )
        assert result["status"] == "success"
        assert result["kind"] == "noop"
        # Legacy entry status stays "no-op" so existing reporters keep working.
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.subtask_results["ST-002"]["status"] == "no-op"
        assert reloaded.subtask_completion_reasons["ST-002"]["kind"] == "noop"

    def test_deferred_kind_records_distinct_status(self, branch_dir, tmp_path):
        state_file = self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.mark_subtask_complete(
            "ST-002", branch_dir, "will land in follow-up PR", kind="deferred"
        )
        assert result["kind"] == "deferred"
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.subtask_results["ST-002"]["status"] == "deferred"
        assert reloaded.subtask_completion_reasons["ST-002"]["kind"] == "deferred"
        assert (
            reloaded.subtask_completion_reasons["ST-002"]["reason"]
            == "will land in follow-up PR"
        )

    def test_unknown_kind_is_rejected(self, branch_dir, tmp_path):
        self._seed_state(branch_dir, tmp_path)
        result = map_orchestrator.mark_subtask_complete(
            "ST-002", branch_dir, "x", kind="rubbish"
        )
        assert result["status"] == "error"
        assert "rubbish" in result["message"]

    def test_stub_kind_serializes_through_roundtrip(self, branch_dir, tmp_path):
        state_file = self._seed_state(branch_dir, tmp_path)
        map_orchestrator.mark_subtask_complete(
            "ST-002", branch_dir, "placeholder", kind="stub"
        )
        # Roundtrip via JSON to ensure the field persists.
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["subtask_completion_reasons"]["ST-002"]["kind"] == "stub"
        restored = map_orchestrator.StepState.from_dict(data)
        assert restored.subtask_completion_reasons["ST-002"]["kind"] == "stub"


class TestCursorAdvancesPastMarkedSubtasks:
    """Regression for the ST-033 friction: mark_subtask_complete wrote
    subtask_phases[sid]="COMPLETE" (uppercase) while the deps-resolver
    looked for lowercase "completed", so the cursor returned to the same
    stub indefinitely. Now phase comparison is case-insensitive AND any
    non-empty subtask_results entry counts as done.
    """

    def test_uppercase_phase_marker_counts_as_done(self, branch_dir, tmp_path):
        del branch_dir, tmp_path
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        # mark_subtask_complete writes uppercase — must still count.
        state.subtask_phases["ST-002"] = "COMPLETE"
        completed = map_orchestrator._completed_subtask_ids_for_deps(state)
        assert "ST-002" in completed, completed

    def test_subtask_results_entry_alone_counts_as_done(
        self, branch_dir, tmp_path
    ):
        del branch_dir, tmp_path
        # Even without a subtask_phases marker, any recorded entry should
        # let the cursor move past the id.
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003"]
        state.subtask_index = 1
        state.current_subtask_id = "ST-002"
        state.subtask_results = {
            "ST-003": {
                "subtask_id": "ST-003",
                "files_changed": ["x.py"],
                "status": "valid",
            }
        }
        completed = map_orchestrator._completed_subtask_ids_for_deps(state)
        assert "ST-003" in completed, completed

    def test_deferred_nondeterministic_result_counts_as_terminal_for_deps(
        self, branch_dir, tmp_path
    ):
        del branch_dir, tmp_path
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_results = {
            "ST-001": {
                "subtask_id": "ST-001",
                "files_changed": [],
                "status": "deferred_nondeterministic",
                "non_green_outcome": True,
            }
        }

        completed = map_orchestrator._completed_subtask_ids_for_deps(state)

        assert "ST-001" in completed, completed

    def test_validate_step_advances_past_already_marked_subtasks(
        self, branch_dir, tmp_path
    ):
        # ST-033 reproduction: cursor at idx=0, ST-002 marked done via
        # mark_subtask_complete (uppercase phase). Closing ST-001's 2.4
        # must advance to COMPLETE, not loop back to ST-002.
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state.subtask_phases["ST-002"] = "COMPLETE"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is True
        assert result["next_step"] == "COMPLETE", result


class TestIsWorkflowCompleteCoverageBased:
    """Regression for #14: write_run_health_report (via _is_workflow_complete
    and _derive_terminal_status) must report "complete" when every subtask
    in subtask_sequence has a recorded result — even if the cursor still
    points at a non-COMPLETE phase due to mid-run drift."""

    def test_full_coverage_returns_complete_when_cursor_stuck(self):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_phase = "ACTOR"  # stuck mid-flight
        for sid in state.subtask_sequence:
            state.subtask_results[sid] = {
                "subtask_id": sid,
                "files_changed": ["x.py"],
                "status": "valid",
            }
        assert map_orchestrator._is_workflow_complete(state) is True

    def test_partial_coverage_returns_false(self):
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003"]
        state.subtask_results = {
            "ST-001": {"subtask_id": "ST-001", "status": "valid"}
        }
        assert map_orchestrator._is_workflow_complete(state) is False


class TestDepsAwareRuntimeAdvance:
    """Runtime safety net: even when planning fails and a forward-dep
    blueprint slips through, validate_step("2.4") at the inter-subtask
    boundary skips subtasks whose deps aren't satisfied yet, walking
    forward to the first ready subtask. If no ready subtask exists,
    emits BLOCKED_ON_DEPS instead of silently advancing.
    """

    def _seed_blueprint(self, tmp_path: Path, branch: str, subtasks: list[dict]) -> None:
        bp_dir = tmp_path / ".map" / branch
        bp_dir.mkdir(parents=True, exist_ok=True)
        (bp_dir / "blueprint.json").write_text(
            json.dumps({"subtasks": subtasks}), encoding="utf-8"
        )

    def test_skips_unready_subtask_picks_next_ready(
        self, branch_dir, tmp_path
    ):
        # Planning slipped: blueprint claims ST-002 deps=[ST-003] but
        # ST-002 was put before ST-003 in subtask_sequence. After
        # closing ST-001, runtime advance must skip ST-002 (unmet dep)
        # and land on ST-003 instead.
        self._seed_blueprint(
            tmp_path,
            branch_dir,
            [
                {"id": "ST-001", "dependencies": []},
                {"id": "ST-002", "dependencies": ["ST-003"]},
                {"id": "ST-003", "dependencies": []},
            ],
        )
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")

        assert result["valid"] is True
        assert result["subtask_advanced_from"] == "ST-001"
        # Skipped ST-002 (forward-dep), landed on ST-003.
        assert result["subtask_advanced_to"] == "ST-003"
        assert result["skipped_for_deps"] == ["ST-002"]
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_subtask_id == "ST-003"
        assert reloaded.subtask_index == 2

    def test_blocked_on_deps_when_no_subtask_ready(
        self, branch_dir, tmp_path
    ):
        # ST-001 done, but ST-002 depends on ST-999 which doesn't exist
        # in subtask_sequence (and was never recorded as done). Advance
        # has no candidate — emit BLOCKED_ON_DEPS instead of COMPLETE.
        self._seed_blueprint(
            tmp_path,
            branch_dir,
            [
                {"id": "ST-001", "dependencies": []},
                {"id": "ST-002", "dependencies": ["ST-999"]},
            ],
        )
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")

        assert result["valid"] is True
        assert result["next_step"] == "BLOCKED_ON_DEPS"
        assert "ST-002" in result["blocked_subtasks"]
        reloaded = map_orchestrator.StepState.load(state_file)
        assert reloaded.current_step_id == "BLOCKED_ON_DEPS"

    def test_no_blueprint_falls_through_to_linear_walk(
        self, branch_dir, tmp_path
    ):
        # When no blueprint exists, advance falls back to linear order
        # (no deps to honor). Backward compatibility: existing flows
        # without a blueprint must still work.
        bp = tmp_path / ".map" / branch_dir / "blueprint.json"
        if bp.exists():
            bp.unlink()
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is True
        assert result["subtask_advanced_to"] == "ST-002"

    def test_mark_subtask_complete_unblocks_dependent(
        self, branch_dir, tmp_path
    ):
        # Operator manually marks ST-003 complete via mark_subtask_complete;
        # ST-002 (deps=[ST-003]) must then be picked up on next advance.
        self._seed_blueprint(
            tmp_path,
            branch_dir,
            [
                {"id": "ST-001", "dependencies": []},
                {"id": "ST-002", "dependencies": ["ST-003"]},
                {"id": "ST-003", "dependencies": []},
            ],
        )
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        # Pre-mark ST-003 via subtask_phases (what mark_subtask_complete writes).
        state.subtask_phases["ST-003"] = "completed"
        state_file = tmp_path / ".map" / branch_dir / "step_state.json"
        state.save(state_file)

        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is True
        # Now ST-002 is ready (ST-003 marked done) — advance lands on it.
        assert result["subtask_advanced_to"] == "ST-002"


class TestSetSubtasksTopologicalSort:
    """Planning-stage fix: set_subtasks reorders subtask_ids to honor
    blueprint deps, so a decomposer that emitted ST-012 deps=[ST-027]
    can no longer leak a forward-dep into runtime — set_subtasks puts
    ST-027 before ST-012 in subtask_sequence. Cycles are rejected
    rather than silently persisted.
    """

    def _write_bp(self, tmp_path: Path, branch: str, subtasks: list[dict]) -> None:
        bp_dir = tmp_path / ".map" / branch
        bp_dir.mkdir(parents=True, exist_ok=True)
        (bp_dir / "blueprint.json").write_text(
            json.dumps({"subtasks": subtasks}), encoding="utf-8"
        )

    def test_already_topological_input_is_noop_passthrough(
        self, branch_dir, tmp_path
    ):
        self._write_bp(
            tmp_path,
            branch_dir,
            [
                {"id": "ST-001", "dependencies": []},
                {"id": "ST-002", "dependencies": ["ST-001"]},
                {"id": "ST-003", "dependencies": ["ST-002"]},
            ],
        )
        result = map_orchestrator.set_subtasks(
            ["ST-001", "ST-002", "ST-003"], branch_dir
        )
        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001", "ST-002", "ST-003"]
        # No reorder flag when input is already correct — keeps the path
        # quiet for well-formed blueprints.
        assert "reordered" not in result

    def test_forward_dep_in_input_is_corrected(self, branch_dir, tmp_path):
        # The exact friction reported on neuro-vlad: ST-012 declared with
        # deps=[ST-027] but listed BEFORE ST-027 in the input id-order.
        # set_subtasks must reorder so ST-027 precedes ST-012.
        subtasks = [{"id": f"ST-{i:03d}", "dependencies": []} for i in range(1, 6)]
        subtasks[1]["dependencies"] = ["ST-005"]  # ST-002 depends on ST-005
        self._write_bp(tmp_path, branch_dir, subtasks)
        input_ids = ["ST-001", "ST-002", "ST-003", "ST-004", "ST-005"]
        result = map_orchestrator.set_subtasks(input_ids, branch_dir)
        assert result["status"] == "success"
        assert result["reordered"] is True
        assert result["original_sequence"] == input_ids
        seq = result["subtask_sequence"]
        assert seq.index("ST-005") < seq.index("ST-002")
        # ST-001/003/004 (no deps) stay in their relative input order.
        assert seq.index("ST-001") < seq.index("ST-003")
        assert seq.index("ST-003") < seq.index("ST-004")
        # current_subtask_id reflects the new head.
        assert result["current_subtask_id"] == seq[0]

    def test_cycle_is_rejected(self, branch_dir, tmp_path):
        # ST-001 -> ST-002 -> ST-001 (cycle); cannot produce any valid order.
        self._write_bp(
            tmp_path,
            branch_dir,
            [
                {"id": "ST-001", "dependencies": ["ST-002"]},
                {"id": "ST-002", "dependencies": ["ST-001"]},
            ],
        )
        result = map_orchestrator.set_subtasks(["ST-001", "ST-002"], branch_dir)
        assert result["status"] == "error"
        assert "cycle" in result["message"].lower()

    def test_missing_blueprint_falls_back_to_input_order(
        self, branch_dir, tmp_path
    ):
        # No blueprint = no deps to honor; preserve caller-provided order.
        # (delete any blueprint that branch_dir fixture might have planted)
        bp = tmp_path / ".map" / branch_dir / "blueprint.json"
        if bp.exists():
            bp.unlink()
        result = map_orchestrator.set_subtasks(
            ["ST-003", "ST-001", "ST-002"], branch_dir
        )
        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-003", "ST-001", "ST-002"]
        assert "reordered" not in result

    def test_shell_joined_subtask_argument_is_split(self, branch_dir, tmp_path):
        bp = tmp_path / ".map" / branch_dir / "blueprint.json"
        if bp.exists():
            bp.unlink()

        result = map_orchestrator.set_subtasks(
            ["ST-001 ST-002 ST-003"], branch_dir
        )

        assert result["status"] == "success"
        assert result["subtask_sequence"] == ["ST-001", "ST-002", "ST-003"]
        state = map_orchestrator.StepState.load(
            tmp_path / ".map" / branch_dir / "step_state.json"
        )
        assert state.subtask_sequence == ["ST-001", "ST-002", "ST-003"]

    def test_invalid_subtask_id_is_rejected(self, branch_dir, tmp_path):
        bp = tmp_path / ".map" / branch_dir / "blueprint.json"
        if bp.exists():
            bp.unlink()

        result = map_orchestrator.set_subtasks(["ST-001", "ST-002,ST-003"], branch_dir)

        assert result["status"] == "error"
        assert "Invalid subtask ID" in result["message"]


class TestCwdIndependence:
    """Regression coverage for the project-root anchor in `main()` (PR #105).

    Invoking the orchestrator via an absolute path from a foreign cwd must
    operate on the project the script lives in, not the caller's cwd. The
    fix uses ``Path(__file__).resolve().parents[2]`` before any state
    lookup. This was previously not covered, and the symptom — a misleading
    ``Step mismatch: expected 1.0, got 2.3`` — is silent at the unit-test
    layer because in-process tests always import the module and bypass
    ``main()``.
    """

    @staticmethod
    def _make_project(root: Path) -> Path:
        """Create ``<root>/.map/scripts/`` populated from the template.

        The fix relies on ``__file__`` being inside ``<project>/.map/scripts/``,
        so we copy every sibling .py module the orchestrator imports
        (map_utils, diagnostics, etc.) — not just the entry-point script.
        """
        import shutil

        scripts_dir = root / ".map" / "scripts"
        scripts_dir.mkdir(parents=True)
        for py_file in ORCHESTRATOR_PATH.glob("*.py"):
            shutil.copy(py_file, scripts_dir / py_file.name)
        return scripts_dir / "map_orchestrator.py"

    @staticmethod
    def _seed_state(
        project: Path,
        branch: str,
        *,
        current_step_id: str,
        current_step_phase: str,
        completed: list[str],
        pending: list[str],
    ) -> None:
        branch_dir = project / ".map" / branch
        branch_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "workflow": "map-efficient",
            "current_subtask_id": "ST-001",
            "subtask_index": 0,
            "subtask_sequence": ["ST-001"],
            "current_step_id": current_step_id,
            "current_step_phase": current_step_phase,
            "completed_steps": completed,
            "pending_steps": pending,
        }
        (branch_dir / "step_state.json").write_text(json.dumps(state))

    def test_get_next_step_reads_state_from_script_project_not_cwd(
        self, tmp_path
    ):
        """The orchestrator script lives in project_a; the caller's cwd is
        an unrelated project_b. With the cwd-anchor in place the script
        must read project_a/.map/<branch>/step_state.json, not project_b's.

        We seed project_a in a fully-completed terminal state (workflow
        finished). project_b has no .map/ at all — so a broken anchor
        would fall back to default-initialised state and return step
        ``1.0`` / ``DECOMPOSE``. The two outcomes are structurally
        distinct, so the assertion uniquely identifies which project was
        read.
        """
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        script = self._make_project(project_a)
        self._seed_state(
            project_a,
            "test-branch",
            current_step_id="2.4",
            current_step_phase="MONITOR",
            completed=["1.0", "1.5", "1.55", "1.56", "1.6", "2.2", "2.3"],
            pending=[],
        )

        # Foreign cwd with no .map/ at all
        project_b = tmp_path / "project_b"
        project_b.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "get_next_step",
                "--branch",
                "test-branch",
            ],
            cwd=str(project_b),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"orchestrator failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        out = json.loads(result.stdout)
        # Anchor working: state read from project_a → COMPLETE / is_complete
        # Anchor broken: state read from cwd (no state) → default 1.0
        assert out.get("step_id") == "COMPLETE" and out.get("is_complete") is True, (
            f"orchestrator did not read project_a state (cwd-anchor broken). "
            f"got: {out}"
        )

    def test_validate_step_uses_script_project_state_under_foreign_cwd(
        self, tmp_path
    ):
        """Validating the step that project_a is currently on must succeed
        regardless of cwd. Caller's cwd has a state at a DIFFERENT step —
        if the anchor were broken, validate_step would emit a step mismatch.
        """
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        script = self._make_project(project_a)
        self._seed_state(
            project_a,
            "test-branch",
            current_step_id="1.0",
            current_step_phase="DECOMPOSE",
            completed=[],
            pending=["1.5", "1.55", "1.56", "1.6"],
        )

        project_b = tmp_path / "project_b"
        # project_b's state claims we're already at step 2.3 — validating
        # "1.0" against this would fail with "Step mismatch".
        self._seed_state(
            project_b,
            "test-branch",
            current_step_id="2.3",
            current_step_phase="ACTOR",
            completed=["1.0", "1.5", "1.55", "1.56", "1.6", "2.2"],
            pending=["2.4"],
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "validate_step",
                "1.0",
                "--branch",
                "test-branch",
            ],
            cwd=str(project_b),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"orchestrator failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        out = json.loads(result.stdout)
        assert out.get("valid") is True, (
            f"validate_step read state from cwd (project_b is at step 2.3) "
            f"instead of project_a (at step 1.0). got: {out}"
        )

    def test_set_waves_resolves_relative_blueprint_in_script_project(
        self, tmp_path
    ):
        """``set_waves --blueprint .map/<branch>/blueprint.json`` uses a
        relative path. The cwd-anchor must rebase that relative argument
        against the script's project (project_a), not the caller's cwd
        (project_b). Without the anchor, the orchestrator would either
        fail to find the blueprint or — worse — read a different
        blueprint from the caller's directory.
        """
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        script = self._make_project(project_a)
        # Seed project_a state at INIT_STATE so set_waves is a valid
        # transition, plus a 3-subtask blueprint with a fan-out.
        self._seed_state(
            project_a,
            "test-branch",
            current_step_id="1.6",
            current_step_phase="INIT_STATE",
            completed=["1.0", "1.5", "1.55", "1.56"],
            pending=[],
        )
        blueprint = {
            "subtasks": [
                {"id": "ST-001", "dependencies": [], "affected_files": ["a.py"]},
                {"id": "ST-002", "dependencies": ["ST-001"], "affected_files": ["b.py"]},
                {"id": "ST-003", "dependencies": ["ST-001"], "affected_files": ["c.py"]},
            ]
        }
        (project_a / ".map" / "test-branch" / "blueprint.json").write_text(
            json.dumps(blueprint)
        )

        # Caller's cwd has its OWN .map/<branch>/blueprint.json with a
        # different shape (single subtask). If the anchor were broken, the
        # relative blueprint argument would resolve here.
        project_b = tmp_path / "project_b"
        (project_b / ".map" / "test-branch").mkdir(parents=True)
        (project_b / ".map" / "test-branch" / "blueprint.json").write_text(
            json.dumps({"subtasks": [{"id": "ST-X", "dependencies": []}]})
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "set_waves",
                "--branch",
                "test-branch",
                "--blueprint",
                ".map/test-branch/blueprint.json",
            ],
            cwd=str(project_b),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"orchestrator failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        out = json.loads(result.stdout)
        # Anchor working: project_a's blueprint (3 subtasks, 2 waves)
        # Anchor broken: project_b's blueprint (1 subtask, 1 wave with ST-X)
        assert out.get("status") == "success", (
            f"set_waves did not succeed: {out}"
        )
        waves = out.get("execution_waves") or []
        flat = [st for wave in waves for st in wave]
        assert "ST-001" in flat and "ST-X" not in flat, (
            f"set_waves resolved blueprint relative to cwd (project_b) "
            f"instead of script project (project_a). got: {out}"
        )

    def test_claude_project_dir_takes_priority_over_script_anchor(
        self, tmp_path
    ):
        """CLAUDE_PROJECT_DIR wins over the script-anchored root (issue #328).

        project_a holds the script and is at COMPLETE state. project_b is at
        step 1.0. With CLAUDE_PROJECT_DIR=project_b the orchestrator must read
        project_b's state, not project_a's.
        """
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        script = self._make_project(project_a)
        self._seed_state(
            project_a,
            "test-branch",
            current_step_id="2.4",
            current_step_phase="MONITOR",
            completed=["1.0", "1.5", "1.55", "1.56", "1.6", "2.2", "2.3"],
            pending=[],
        )

        project_b = tmp_path / "project_b"
        self._seed_state(
            project_b,
            "test-branch",
            current_step_id="1.0",
            current_step_phase="DECOMPOSE",
            completed=[],
            pending=["1.5", "1.55", "1.56", "1.6"],
        )

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "get_next_step",
                "--branch",
                "test-branch",
            ],
            cwd=str(project_a),
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_b)},
            check=False,
        )
        assert result.returncode == 0, (
            f"orchestrator failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        out = json.loads(result.stdout)
        # CLAUDE_PROJECT_DIR wins → project_b state (pending step 1.5).
        # If script-anchored root won instead → project_a state (COMPLETE /
        # is_complete=True).
        assert out.get("is_complete") is not True, (
            f"orchestrator returned COMPLETE — it read project_a (script-anchored) "
            f"instead of project_b (CLAUDE_PROJECT_DIR). got {out!r}. "
            f"stderr: {result.stderr!r}"
        )
        assert out.get("step_id") == "1.5", (
            f"orchestrator did not honour CLAUDE_PROJECT_DIR (expected "
            f"step_id='1.5' from project_b, got {out!r}). "
            f"stderr: {result.stderr!r}"
        )

    def test_git_toplevel_from_caller_cwd_takes_priority_over_script_anchor(
        self, tmp_path
    ):
        """git rev-parse --show-toplevel from the caller's cwd wins over the
        script-anchored root when no CLAUDE_PROJECT_DIR is set (issue #328).

        This reproduces the worktree scenario: the script lives in project_a
        (not a git repo), but the caller's cwd is project_b (a real git repo).
        The orchestrator must resolve project_b as the project root and read
        state from there instead of from project_a.
        """
        project_a = tmp_path / "project_a"
        project_a.mkdir()
        script = self._make_project(project_a)
        # project_a: COMPLETE state (wrong answer if script-anchor wins)
        self._seed_state(
            project_a,
            "test-branch",
            current_step_id="2.4",
            current_step_phase="MONITOR",
            completed=["1.0", "1.5", "1.55", "1.56", "1.6", "2.2", "2.3"],
            pending=[],
        )

        # project_b: a real git repo (simulates a git worktree checkout).
        # git rev-parse --show-toplevel works after `git init` alone — no
        # commit is required for toplevel detection.
        project_b = tmp_path / "project_b"
        project_b.mkdir()
        subprocess.run(
            ["git", "init", str(project_b)],
            check=True,
            capture_output=True,
        )
        # project_b: step 1.0 state (correct answer if git-toplevel wins)
        self._seed_state(
            project_b,
            "test-branch",
            current_step_id="1.0",
            current_step_phase="DECOMPOSE",
            completed=[],
            pending=["1.5", "1.55", "1.56", "1.6"],
        )

        # Strip CLAUDE_PROJECT_DIR so only the git-toplevel path is exercised
        env_no_cpd = {
            k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"
        }
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "get_next_step",
                "--branch",
                "test-branch",
            ],
            cwd=str(project_b),  # caller's cwd IS a git repo
            capture_output=True,
            text=True,
            env=env_no_cpd,
            check=False,
        )
        assert result.returncode == 0, (
            f"orchestrator failed: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        out = json.loads(result.stdout)
        # git-toplevel wins → project_b state (pending step 1.5).
        # If script-anchored root won instead → project_a state (COMPLETE /
        # is_complete=True).
        assert out.get("is_complete") is not True, (
            f"orchestrator returned COMPLETE — it read project_a (script-anchored) "
            f"instead of project_b (git-toplevel). got {out!r}. "
            f"stderr: {result.stderr!r}"
        )
        assert out.get("step_id") == "1.5", (
            f"orchestrator did not resolve project root from caller's git repo "
            f"(expected step_id='1.5' from project_b, got {out!r}). "
            f"stderr: {result.stderr!r}"
        )


class TestValidateStep24RequiredRecommendation:
    """ST-003 / VC1-VC3: validate_step 2.4 requires --recommendation.
    Without it the verdict-consistency gate cannot enforce that Monitor's
    revise/block/needs_investigation is honoured.
    """

    def _seed(self, branch_dir: str, tmp_path: Path) -> None:
        state = map_orchestrator.StepState()
        state.workflow_status = "IN_PROGRESS"
        state.subtask_sequence = ["ST-001"]
        state.subtask_index = 0
        state.current_subtask_id = "ST-001"
        state.current_step_id = "2.4"
        state.current_step_phase = "MONITOR"
        state.completed_steps = ["2.2", "2.3"]
        state.pending_steps = ["2.4"]
        sf = tmp_path / ".map" / branch_dir / "step_state.json"
        sf.parent.mkdir(parents=True, exist_ok=True)
        state.save(sf)

    # VC1 -------------------------------------------------------------------
    def test_vc1_validate_step_24_requires_recommendation(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """VC1: omitting recommendation → valid=False + recommendation_required=True."""
        self._seed(branch_dir, tmp_path)
        result = map_orchestrator.validate_step("2.4", branch_dir)
        assert result["valid"] is False, result
        assert result.get("recommendation_required") is True, result
        assert "--recommendation" in result["message"]

    # VC3 -------------------------------------------------------------------
    def test_vc3_validate_step_24_proceed_closes(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """VC3: recommendation='proceed' → valid=True (step closes cleanly)."""
        self._seed(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="proceed"
        )
        assert result["valid"] is True, result
        assert result.get("recommendation_required") is None

    def test_vc3_validate_step_24_revise_rejects(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """VC3: recommendation='revise' → valid=False (Monitor verdict enforced)."""
        self._seed(branch_dir, tmp_path)
        result = map_orchestrator.validate_step(
            "2.4", branch_dir, recommendation="revise"
        )
        assert result["valid"] is False, result
        assert result.get("recommendation") == "revise"

    def test_vc3_validate_step_24_idempotent_noop(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """VC3: already-completed 2.4 re-validated with recommendation=None → valid=True (no-op path)."""
        self._seed(branch_dir, tmp_path)
        # First close it properly.
        map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        # Now re-validate without recommendation — idempotent path must succeed.
        result = map_orchestrator.validate_step("2.4", branch_dir)
        assert result["valid"] is True, result
        assert result.get("idempotent") is True, result

    # VC2 -------------------------------------------------------------------
    def test_vc2_validate_step_24_cli_nonzero_without_recommendation(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """VC2: CLI subprocess validate_step 2.4 without --recommendation → returncode != 0."""
        self._seed(branch_dir, tmp_path)
        script = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "templates" / "map" / "scripts" / "map_orchestrator.py"
        )
        result = subprocess.run(
            [sys.executable, str(script), "validate_step", "2.4",
             "--branch", branch_dir],
            capture_output=True, text=True, cwd=str(tmp_path),
            check=False,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit when --recommendation omitted; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Slice 3 — predicate-gated sequential wave-loop
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, wave_mode: str) -> None:
    """Write a minimal .map/config.yaml with execution.wave_mode set."""
    map_dir = tmp_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "config.yaml").write_text(
        f"execution.wave_mode: {wave_mode}\n", encoding="utf-8"
    )


def _write_step_state(
    branch: str,
    tmp_path: Path,
    execution_waves: list,
    extra: dict | None = None,
) -> None:
    """Write a minimal step_state.json with given execution_waves."""
    import json as _json

    state: dict = {
        "workflow": "map-efficient",
        "started_at": "2026-01-01T00:00:00",
        "current_subtask_id": None,
        "subtask_index": 0,
        "subtask_sequence": [],
        "current_step_id": "1.0",
        "current_step_phase": "DECOMPOSE",
        "completed_steps": [],
        "pending_steps": [],
        "retry_count": 0,
        "max_retries": 5,
        "plan_approved": False,
        "execution_mode": "batch",
        "tdd_mode": False,
        "skipped_steps": [],
        "execution_waves": execution_waves,
        "current_wave_index": 0,
        "subtask_phases": {},
        "subtask_retry_counts": {},
        "workflow_status": "INITIALIZED",
        "subtask_files_changed": {},
        "guard_rework_counts": {},
        "constraints": None,
        "subtask_results": {},
        "last_subtask_commit_sha": None,
        "contract_ready_subtasks": {},
        "clean_retry_count": 0,
        "contaminated_retry_count": 0,
        "scope_feedback_subtasks": [],
        "progress_feedback_subtasks": [],
        "retry_isolation_status": {},
        "retry_quarantine_paths": {},
        "completed_at": None,
        "subtask_completion_reasons": {},
    }
    if extra:
        state.update(extra)
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    (branch_dir / "step_state.json").write_text(
        _json.dumps(state), encoding="utf-8"
    )


def test_wave_loop_sequential_no_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC1 [HC-2]: get_wave_step returns concurrency_enabled=False for width>=2 wave
    when the kill-switch MAP_EFFICIENT_SEQUENTIAL_ONLY=1 is engaged.

    Slice 6: the default is now ON (concurrent). Re-pointed to the kill-switch off-ramp
    to prove the byte-identical-to-legacy contract still holds under the kill-switch.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    branch = "test-st010-vc1"
    # Two subtasks in one wave → concurrency_enabled=False under kill-switch.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    result = map_orchestrator.get_wave_step(branch)

    assert result["is_complete"] is False
    assert result["concurrency_enabled"] is False, (
        f"concurrency_enabled must be False under MAP_EFFICIENT_SEQUENTIAL_ONLY=1: {result}"
    )
    # Both subtasks still listed in the result; the dispatch mode is sequential.
    assert len(result["subtasks"]) == 2  # both listed; dispatcher iterates one at a time


def test_wave_loop_predicate_gating_default_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2 [AC-10]: select_execution_strategy gates on wave_mode AND has_parallel_groups."""
    import types

    monkeypatch.chdir(tmp_path)
    branch = "test-st010-vc2"
    # Build a state with a width>=2 wave.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    # 1. Default (wave_mode=off) → sequential regardless of wave width.
    _write_config(tmp_path, "off")
    monkeypatch.setattr(
        map_orchestrator,
        "select_execution_strategy",
        map_orchestrator.select_execution_strategy,
    )
    # Inject a mock _execution_wave_mode returning "off" via the import path.
    # select_execution_strategy imports from map_step_runner inside the function;
    # we patch by injecting a fake module into sys.modules for the call scope.
    import sys as _sys

    def _fake_runner(wave_mode: str, isolation: str) -> "types.ModuleType":
        """Build a fake map_step_runner exposing BOTH readers that
        select_execution_strategy imports (wave_mode + worktree isolation)."""
        mod = types.ModuleType("map_step_runner")

        def _wm(_project_dir: object) -> str:
            del _project_dir
            return wave_mode

        def _iso(_project_dir: object) -> str:
            del _project_dir
            return isolation

        mod._execution_wave_mode = _wm  # type: ignore[attr-defined]
        mod._worktree_isolation_mode = _iso  # type: ignore[attr-defined]
        return mod

    # Save any real map_step_runner so we restore (not erase) it afterwards —
    # other tests in the session may rely on the genuine imported module.
    _orig_msr = _sys.modules.get("map_step_runner")
    try:
        # 1. wave_mode=off → sequential even with isolation on and a parallel group.
        _sys.modules["map_step_runner"] = _fake_runner("off", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["strategy"] == "sequential", f"off → sequential: {result}"
        assert result["wave_mode"] == "off"
        assert result["has_parallel_groups"] is True  # waves exist, but mode is off

        # 2. wave_mode=on + isolation=required + parallel group → wave_loop.
        _sys.modules["map_step_runner"] = _fake_runner("on", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["strategy"] == "wave_loop", f"on + iso=required + width>=2 → wave_loop: {result}"
        assert result["wave_mode"] == "on"
        assert result["worktree_isolation"] == "required"

        # 3. wave_mode=auto + isolation=auto + parallel group → wave_loop.
        _sys.modules["map_step_runner"] = _fake_runner("auto", "auto")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["strategy"] == "wave_loop", f"auto + iso=auto + width>=2 → wave_loop: {result}"

        # 4. ISOLATION GATE: wave_mode=auto (default) but isolation=off → sequential.
        #    This is the behavior-neutral default (MapConfig: wave_mode=auto, isolation=off).
        _sys.modules["map_step_runner"] = _fake_runner("auto", "off")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["strategy"] == "sequential", f"auto + iso=off → sequential (default): {result}"
        assert result["worktree_isolation"] == "off"

        # 5. wave_mode=on + isolation=required but ALL waves width-1 → sequential.
        _write_step_state(branch, tmp_path, execution_waves=[["ST-001"], ["ST-002"]])
        _sys.modules["map_step_runner"] = _fake_runner("on", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["strategy"] == "sequential", f"on + all width-1 → sequential: {result}"
        assert result["has_parallel_groups"] is False
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr
        else:
            _sys.modules.pop("map_step_runner", None)


def test_advance_wave_atomic_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3 [AC-10]: advance_wave atomically resets ALL per-wave sub-state."""
    monkeypatch.chdir(tmp_path)
    branch = "test-st010-vc3"
    # Seed stale sub-state that must be cleared on advance.
    _write_step_state(
        branch,
        tmp_path,
        execution_waves=[["ST-001"], ["ST-002"]],
        extra={
            "current_wave_index": 0,
            "subtask_phases": {"ST-001": "2.4"},
            "subtask_retry_counts": {"ST-001": 3},
            "pending_steps": ["2.3", "2.4"],
            "completed_steps": ["1.0", "2.2"],
            "skipped_steps": ["2.25"],
            "current_step_id": "2.3",
            "current_step_phase": "ACTOR",
            "retry_count": 2,
            "current_subtask_id": "ST-001",
        },
    )

    result = map_orchestrator.advance_wave(branch)

    assert result["status"] == "success", result
    assert result["current_wave_index"] == 1

    # Read back state and assert atomic reset of ALL per-wave sub-state.
    import json as _json
    state_path = tmp_path / ".map" / branch / "step_state.json"
    state = _json.loads(state_path.read_text())

    assert state["subtask_phases"] == {}, f"subtask_phases not reset: {state['subtask_phases']}"
    assert state["subtask_retry_counts"] == {}, (
        f"subtask_retry_counts not reset: {state['subtask_retry_counts']}"
    )
    assert state["completed_steps"] == [], f"completed_steps not reset: {state['completed_steps']}"
    assert state["skipped_steps"] == [], f"skipped_steps not reset: {state['skipped_steps']}"
    assert state["retry_count"] == 0, f"retry_count not reset: {state['retry_count']}"
    # current_subtask_id and current_step_id must point at the new wave's first subtask.
    assert state["current_subtask_id"] == "ST-002", (
        f"current_subtask_id not advanced: {state['current_subtask_id']}"
    )
    assert state["current_step_id"] == "2.2", (
        f"current_step_id not reset to research start: {state['current_step_id']}"
    )
    # pending_steps must be reset to the research-onward order (no stale entries).
    assert state["pending_steps"], "pending_steps not repopulated for the new wave"
    assert state["pending_steps"][0] == "2.2", (
        f"pending_steps not reset to research start: {state['pending_steps']}"
    )
    assert "2.4" in state["pending_steps"], (
        f"pending_steps missing later phases after reset: {state['pending_steps']}"
    )


def test_vc1_concurrency_allowed_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC1 [AC-1]: concurrency_allowed truth table for select_execution_strategy.

    True only when strategy==wave_loop AND isolation in {auto,required} AND has_parallel_groups.
    Each condition is toggled off in turn to verify the AND semantics.
    """
    import sys as _sys
    import types

    monkeypatch.chdir(tmp_path)
    branch = "test-vc1-concurrency-allowed"
    # Seed a step_state with a width>=2 execution_waves group.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    def _fake_runner(wave_mode: str, isolation: str) -> "types.ModuleType":
        mod = types.ModuleType("map_step_runner")

        def _wm(_project_dir: object) -> str:
            del _project_dir
            return wave_mode

        def _iso(_project_dir: object) -> str:
            del _project_dir
            return isolation

        mod._execution_wave_mode = _wm  # type: ignore[attr-defined]
        mod._worktree_isolation_mode = _iso  # type: ignore[attr-defined]
        return mod

    _orig_msr = _sys.modules.get("map_step_runner")
    try:
        # True: all three conditions satisfied (wave_loop + auto isolation + parallel groups).
        _sys.modules["map_step_runner"] = _fake_runner("on", "auto")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is True, (
            f"on+auto+width>=2 must give concurrency_allowed=True: {result}"
        )
        assert result["strategy"] == "wave_loop"

        # True: isolation=required also qualifies.
        _sys.modules["map_step_runner"] = _fake_runner("on", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is True, (
            f"on+required+width>=2 must give concurrency_allowed=True: {result}"
        )

        # True: wave_mode=auto also qualifies.
        _sys.modules["map_step_runner"] = _fake_runner("auto", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is True, (
            f"auto+required+width>=2 must give concurrency_allowed=True: {result}"
        )

        # False: condition 1 off — wave_mode=off → strategy=sequential.
        _sys.modules["map_step_runner"] = _fake_runner("off", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is False, (
            f"wave_mode=off must give concurrency_allowed=False: {result}"
        )
        assert result["strategy"] == "sequential"

        # False: condition 2 off — isolation=off → strategy=sequential.
        _sys.modules["map_step_runner"] = _fake_runner("on", "off")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is False, (
            f"isolation=off must give concurrency_allowed=False: {result}"
        )

        # False: condition 3 off — all waves width-1 → has_parallel_groups=False.
        _write_step_state(branch, tmp_path, execution_waves=[["ST-001"], ["ST-002"]])
        _sys.modules["map_step_runner"] = _fake_runner("on", "required")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
        assert result["concurrency_allowed"] is False, (
            f"all width-1 waves must give concurrency_allowed=False: {result}"
        )
        assert result["has_parallel_groups"] is False
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr
        else:
            _sys.modules.pop("map_step_runner", None)


def test_vc2_default_config_concurrent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2 [AC-10] (reframed Slice 6): default config (wave_mode=auto, isolation=auto)
    with a parallel-ready plan now gives strategy=='wave_loop' AND concurrency_allowed==True.

    The old premise (isolation defaults to 'off' → always sequential) is gone in Slice 6.
    New proof: default config → concurrent for a parallel-ready plan.
    """
    import sys as _sys
    import types

    monkeypatch.chdir(tmp_path)
    branch = "test-vc2-default-concurrent"
    # Seed a width>=2 wave so has_parallel_groups=True.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    def _fake_runner_slice6(wave_mode: str, isolation: str) -> "types.ModuleType":
        mod = types.ModuleType("map_step_runner")

        def _wm(_project_dir: object) -> str:
            del _project_dir
            return wave_mode

        def _iso(_project_dir: object) -> str:
            del _project_dir
            return isolation

        mod._execution_wave_mode = _wm  # type: ignore[attr-defined]
        mod._worktree_isolation_mode = _iso  # type: ignore[attr-defined]
        return mod

    _orig_msr = _sys.modules.get("map_step_runner")
    try:
        # Slice 6 defaults: wave_mode=auto, isolation=auto (!=off) → wave_loop for parallel plan.
        _sys.modules["map_step_runner"] = _fake_runner_slice6("auto", "auto")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)

        assert result["strategy"] == "wave_loop", (
            f"Slice 6 default config + parallel plan must give strategy='wave_loop': {result}"
        )
        assert result["concurrency_allowed"] is True, (
            f"Slice 6 default config + parallel plan must give concurrency_allowed=True: {result}"
        )
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr
        else:
            _sys.modules.pop("map_step_runner", None)


def test_vc2_kill_switch_forces_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2 kill-switch [AC-10]: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 forces sequential
    regardless of config — the byte-identical-to-legacy proof now applies to the
    kill-switch path, not the default config path.

    This re-points the old 'default config → sequential' contract to the kill-switch.
    """
    import sys as _sys
    import types

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    branch = "test-vc2-kill-switch"
    # Seed a parallel-ready plan — kill-switch must block it.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    def _fake_runner_parallel(wave_mode: str, isolation: str) -> "types.ModuleType":
        mod = types.ModuleType("map_step_runner")

        def _wm(_project_dir: object) -> str:
            del _project_dir
            return wave_mode

        def _iso(_project_dir: object) -> str:
            del _project_dir
            return isolation

        mod._execution_wave_mode = _wm  # type: ignore[attr-defined]
        mod._worktree_isolation_mode = _iso  # type: ignore[attr-defined]
        return mod

    _orig_msr = _sys.modules.get("map_step_runner")
    try:
        # Even with parallel-ready defaults (wave_mode=auto, isolation=auto),
        # the kill-switch short-circuits to sequential before reading config.
        _sys.modules["map_step_runner"] = _fake_runner_parallel("auto", "auto")
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)

        assert result["strategy"] == "sequential", (
            f"MAP_EFFICIENT_SEQUENTIAL_ONLY=1 must give strategy='sequential': {result}"
        )
        assert result["concurrency_allowed"] is False, (
            f"MAP_EFFICIENT_SEQUENTIAL_ONLY=1 must give concurrency_allowed=False: {result}"
        )
        assert result["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
            f"Kill-switch reason must be WAVE_REASON_SEQUENTIAL_ONLY_ENV, got {result['reason']!r}"
        )

        # Also verify compute_dispatch_gate short-circuits to sequential.
        gate = map_orchestrator.compute_dispatch_gate(branch, tmp_path)
        assert gate["dispatch_mode"] == "sequential", (
            f"compute_dispatch_gate must return sequential under kill-switch: {gate}"
        )
        assert gate["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
            f"compute_dispatch_gate reason must be WAVE_REASON_SEQUENTIAL_ONLY_ENV: {gate}"
        )
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr
        else:
            _sys.modules.pop("map_step_runner", None)


def test_vc3_strategy_cli_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3 [render-parity]: CLI 'select_execution_strategy <branch>' prints JSON with concurrency_allowed.

    Invokes the generated .map/scripts/map_orchestrator.py via subprocess to prove
    the CLI handler is wired in the rendered tree after make render-templates.
    """
    import shutil

    monkeypatch.chdir(tmp_path)
    branch = "test-vc3-cli-handler"

    # Copy the rendered scripts into <tmp_path>/.map/scripts/ (same pattern as other CLI tests).
    scripts_dir = tmp_path / ".map" / "scripts"
    scripts_dir.mkdir(parents=True)
    for py_file in ORCHESTRATOR_PATH.glob("*.py"):
        shutil.copy(py_file, scripts_dir / py_file.name)

    script = scripts_dir / "map_orchestrator.py"

    # Seed branch state: sequential (no config.yaml → isolation defaults to off).
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    proc = subprocess.run(
        [sys.executable, str(script), "select_execution_strategy", "--branch", branch],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"CLI exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    data = json.loads(proc.stdout)
    assert "concurrency_allowed" in data, (
        f"CLI output missing 'concurrency_allowed' key: {data}"
    )
    assert isinstance(data["concurrency_allowed"], bool), (
        f"concurrency_allowed must be bool, got {type(data['concurrency_allowed'])}: {data}"
    )
    assert "strategy" in data
    assert "worktree_isolation" in data
    assert "has_parallel_groups" in data


# ---------------------------------------------------------------------------
# ST-002: structured dispatch signal in get_wave_step
# ---------------------------------------------------------------------------


def test_vc1_get_wave_step_dispatch_mode_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC1: dispatch_mode=='sequential' and isolation_active/reason non-empty for both
    width-1 and width>=2 active waves.

    Slice 6: concurrent_dispatch defaults to True, so the fake runner also exposes
    _concurrent_dispatch_enabled. The 'isolation=off' case uses concurrent_dispatch=False
    to avoid the config-contradiction DispatchGateError (isolation=off + dispatch=True
    is an error, not a sequential fallback — per-repo opt-out requires BOTH flags).
    """
    import types

    monkeypatch.chdir(tmp_path)

    def _fake_runner(isolation: str, concurrent: bool = True) -> "types.ModuleType":
        mod = types.ModuleType("map_step_runner")

        def _iso(_project_dir: object) -> str:
            del _project_dir
            return isolation

        def _dispatch(_project_dir: object) -> bool:
            del _project_dir
            return concurrent

        def _wm(_project_dir: object) -> str:
            del _project_dir
            return "auto"

        mod._worktree_isolation_mode = _iso  # type: ignore[attr-defined]
        mod._concurrent_dispatch_enabled = _dispatch  # type: ignore[attr-defined]
        mod._execution_wave_mode = _wm  # type: ignore[attr-defined]
        return mod

    import sys as _sys

    _orig_msr = _sys.modules.get("map_step_runner")
    try:
        # width-1 wave, isolation=required, dispatch=True → dispatch_mode=sequential
        # (width-1 wave → WAVE_REASON_CURRENT_WAVE_SEQUENTIAL)
        _sys.modules["map_step_runner"] = _fake_runner("required", concurrent=True)
        branch1 = "test-st002-vc1-width1"
        _write_step_state(branch1, tmp_path, execution_waves=[["ST-001"]])
        result1 = map_orchestrator.get_wave_step(branch1)

        assert result1["dispatch_mode"] == "sequential", (
            f"width-1 wave: expected dispatch_mode='sequential', got: {result1}"
        )
        assert result1["isolation_active"] is True, (
            f"width-1 wave: isolation='required' → isolation_active must be True: {result1}"
        )
        assert result1["reason"], f"width-1 wave: reason must be non-empty: {result1}"
        assert result1["is_complete"] is False

        # width-2 wave, isolation=off, dispatch=False (per-repo opt-out) → isolation_active=False
        # Note: isolation=off + dispatch=True would raise DispatchGateError (config contradiction).
        # Per-repo opt-out: disable dispatch to get sequential without the error.
        _sys.modules["map_step_runner"] = _fake_runner("off", concurrent=False)
        branch2 = "test-st002-vc1-width2"
        _write_step_state(branch2, tmp_path, execution_waves=[["ST-001", "ST-002"]])
        result2 = map_orchestrator.get_wave_step(branch2)

        assert result2["dispatch_mode"] == "sequential", (
            f"width-2 wave: expected dispatch_mode='sequential', got: {result2}"
        )
        assert result2["isolation_active"] is False, (
            f"width-2 wave: isolation='off' → isolation_active must be False: {result2}"
        )
        assert result2["reason"], f"width-2 wave: reason must be non-empty: {result2}"
        assert result2["is_complete"] is False
    finally:
        if _orig_msr is None:
            _sys.modules.pop("map_step_runner", None)
        else:
            _sys.modules["map_step_runner"] = _orig_msr


def test_vc2_dispatch_mode_never_concurrent_on_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2 (reframed Slice 6): dispatch_mode is 'sequential' on every return path
    when MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch engaged).

    The old premise 'WAVE_CONCURRENCY_ENABLED is False → always sequential' no longer
    holds for the default config in Slice 6 (defaults are ON). Re-pointed to the
    kill-switch to prove the byte-identical-to-legacy contract.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    branch = "test-st002-vc2"

    # Path 1: no waves → no_waves early return (kill-switch is redundant here but consistent)
    _write_step_state(branch, tmp_path, execution_waves=[])
    r_no_waves = map_orchestrator.get_wave_step(branch)
    assert r_no_waves["dispatch_mode"] == "sequential", (
        f"no-waves path: dispatch_mode must be 'sequential': {r_no_waves}"
    )
    assert r_no_waves["concurrency_enabled"] is False, (
        f"no-waves path: concurrency_enabled alias must be False: {r_no_waves}"
    )

    # Path 2: wave exhausted → wave_complete early return
    _write_step_state(
        branch,
        tmp_path,
        execution_waves=[["ST-001"]],
        extra={"current_wave_index": 99},
    )
    r_complete = map_orchestrator.get_wave_step(branch)
    assert r_complete["dispatch_mode"] == "sequential", (
        f"wave-complete path: dispatch_mode must be 'sequential': {r_complete}"
    )
    assert r_complete["concurrency_enabled"] is False, (
        f"wave-complete path: concurrency_enabled alias must be False: {r_complete}"
    )

    # Path 3: active wave (width>=2) → kill-switch forces sequential
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])
    r_active = map_orchestrator.get_wave_step(branch)
    assert r_active["dispatch_mode"] == "sequential", (
        f"active-wave path: dispatch_mode must be 'sequential' under kill-switch: {r_active}"
    )
    assert r_active["concurrency_enabled"] is False, (
        f"active-wave path: concurrency_enabled alias must be False under kill-switch: {r_active}"
    )


def test_vc3_get_wave_step_reason_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3: each of the three return paths emits its distinct stable reason code."""
    monkeypatch.chdir(tmp_path)
    branch = "test-st002-vc3"

    # Path 1: no waves
    _write_step_state(branch, tmp_path, execution_waves=[])
    r_no_waves = map_orchestrator.get_wave_step(branch)
    assert r_no_waves["reason"] == map_orchestrator.WAVE_REASON_NO_WAVES, (
        f"no-waves path: expected reason={map_orchestrator.WAVE_REASON_NO_WAVES!r}: {r_no_waves}"
    )

    # Path 2: wave index exhausted
    _write_step_state(
        branch,
        tmp_path,
        execution_waves=[["ST-001"]],
        extra={"current_wave_index": 99},
    )
    r_complete = map_orchestrator.get_wave_step(branch)
    assert r_complete["reason"] == map_orchestrator.WAVE_REASON_WAVE_COMPLETE, (
        f"wave-complete path: expected reason={map_orchestrator.WAVE_REASON_WAVE_COMPLETE!r}: "
        f"{r_complete}"
    )

    # Path 3: active wave (width=1 → single subtask, not parallelizable)
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001"]])
    r_active = map_orchestrator.get_wave_step(branch)
    # Slice 6: with defaults ON, a width-1 wave returns gate_not_parallelizable
    # (single task cannot form parallel groups); WAVE_REASON_DISPATCH_SEQUENTIAL is
    # now only emitted on the legacy path (pre-dispatch gate, reached when worktree
    # isolation is explicitly off or the dispatch gate short-circuits before color-grouping).
    assert r_active["reason"] == map_orchestrator.WAVE_REASON_GATE_NOT_PARALLELIZABLE, (
        f"active-wave path (width=1): expected reason="
        f"{map_orchestrator.WAVE_REASON_GATE_NOT_PARALLELIZABLE!r}: {r_active}"
    )

    # All three codes must be distinct stable strings
    codes = {
        map_orchestrator.WAVE_REASON_NO_WAVES,
        map_orchestrator.WAVE_REASON_WAVE_COMPLETE,
        map_orchestrator.WAVE_REASON_GATE_NOT_PARALLELIZABLE,
    }
    assert len(codes) == 3, f"reason codes must all be distinct: {codes}"


# ---------------------------------------------------------------------------
# ST-007: HC-1 default-config behavior-neutrality PROOF tests
# ---------------------------------------------------------------------------
# These tests use the REAL map_step_runner (no sys.modules mock) against an
# actual filesystem project_dir with no .map/config.yaml (or an empty one),
# proving that the real MapConfig defaults keep every dispatch path sequential.
# The genuine proof: each test seeds a width>=2 wave (a parallelizable plan),
# which WOULD trigger wave_loop if the config asked for it — but the isolation
# gate (defaults to 'off') keeps everything on the legacy sequential path.


def test_vc1_default_config_neutral_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HC-1 proof (Slice 6 reframe): with MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch),
    select_execution_strategy returns strategy=='sequential', concurrency_allowed==False —
    even when a parallelizable (width>=2) wave exists and the config defaults are ON.

    This replaces the old 'default isolation=off keeps sequential' proof. Slice 6
    flipped both defaults to ON (wave_mode='auto', isolation='auto'), so the old test
    was asserting a premise that no longer holds. The kill-switch is the new
    byte-identical-to-legacy off-ramp and is non-tautological: the width>=2 wave
    makes has_parallel_groups=True (WOULD engage wave_loop without the kill-switch).
    """
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    branch = "test-st007-vc1-killswitch"

    # Seed a width>=2 execution wave — has_parallel_groups will be True.
    # Without the kill-switch, Slice 6 defaults WOULD select strategy='wave_loop'.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    # No .map/config.yaml — defaults are ON ('auto'/'auto'), but kill-switch fires first.
    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr

    assert result["strategy"] == "sequential", (
        f"kill-switch must give strategy='sequential': {result}"
    )
    assert result["concurrency_allowed"] is False, (
        f"kill-switch must give concurrency_allowed=False: {result}"
    )
    assert result["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
        f"kill-switch must return WAVE_REASON_SEQUENTIAL_ONLY_ENV reason: {result}"
    )


def test_vc2_default_config_neutral_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HC-1 proof (Slice 6 reframe): with MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch),
    get_wave_step returns dispatch_mode=='sequential' and concurrency_enabled==False.

    The old premise ('default isolation=off → dispatch sequential') no longer holds in
    Slice 6 (defaults are ON). Re-pointed to the kill-switch path. Width>=2 wave seeded
    to prove the gate stays sequential DESPITE a parallelizable plan.
    """
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    branch = "test-st007-vc2-killswitch"

    # Seed a width>=2 wave — WOULD be concurrently dispatched if kill-switch were off.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    # Kill-switch fires before config/isolation is even read.
    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        result = map_orchestrator.get_wave_step(branch)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr

    assert result["dispatch_mode"] == "sequential", (
        f"kill-switch: dispatch_mode must be 'sequential': {result}"
    )
    assert result["concurrency_enabled"] is False, (
        f"kill-switch: concurrency_enabled alias must be False: {result}"
    )
    assert result["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
        f"kill-switch: reason must be WAVE_REASON_SEQUENTIAL_ONLY_ENV: {result}"
    )

    # create_subtask_worktree with per-repo isolation=off must still no-op.
    # This covers the per-repo opt-out path (separate from kill-switch).
    # Write a config with worktree.isolation: off explicitly.
    map_dir = tmp_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "config.yaml").write_text("worktree.isolation: off\n", encoding="utf-8")

    _orig_msr2 = _sys.modules.pop("map_step_runner", None)
    try:
        import map_step_runner as _msr  # pyright: ignore[reportMissingImports]

        wt_result = _msr.create_subtask_worktree("ST-001")
    finally:
        if _orig_msr2 is not None:
            _sys.modules["map_step_runner"] = _orig_msr2

    assert wt_result["status"] == "disabled", (
        f"isolation=off: create_subtask_worktree must return status='disabled': {wt_result}"
    )
    assert wt_result["ok"] is False, (
        f"isolation=off: create_subtask_worktree must return ok=False: {wt_result}"
    )


def test_vc3_dormant_keys_do_not_flip_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HC-1 proof (Slice 6 reframe): dormant Slice-5a keys (execution.max_actors,
    execution.retry_degraded_once) alone do NOT override the per-repo opt-out:
    with worktree.isolation=off set explicitly, strategy remains 'sequential'.

    Proves that the dormant fields have no effect on the execution path.
    Width>=2 wave seeded; the isolation=off config is the only thing keeping
    dispatch sequential (non-tautological — would engage wave_loop if isolation=auto).
    """
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    branch = "test-st007-vc3-dormant-keys"

    # Seed a width>=2 wave — parallelizable plan present.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    # Config: dormant ST-005 keys + explicit worktree.isolation=off (per-repo opt-out).
    # Slice 6 defaults are ON; the explicit isolation=off override keeps dispatch sequential.
    map_dir = tmp_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "config.yaml").write_text(
        "execution.max_actors: 3\n"
        "execution.retry_degraded_once: true\n"
        "worktree.isolation: off\n",
        encoding="utf-8",
    )

    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        result = map_orchestrator.select_execution_strategy(branch, tmp_path)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr

    assert result["strategy"] == "sequential", (
        f"per-repo isolation=off must keep strategy 'sequential': {result}"
    )
    assert result["concurrency_allowed"] is False, (
        f"per-repo isolation=off must keep concurrency_allowed=False: {result}"
    )
    assert result["worktree_isolation"] == "off", (
        f"worktree_isolation must be 'off' (explicit per-repo override): {result}"
    )
    assert result["has_parallel_groups"] is True, (
        "has_parallel_groups must be True so isolation=off — not absent waves — "
        "is what keeps the strategy sequential (non-tautological proof)"
    )


# ---------------------------------------------------------------------------
# ST-001: compute_dispatch_gate — config-driven fail-closed concurrency gate
# ---------------------------------------------------------------------------


def _write_config_keys(tmp_path: Path, **keys: str) -> None:
    """Write a .map/config.yaml with arbitrary dotted keys (ST-001 helper)."""
    map_dir = tmp_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(f"{k}: {v}" for k, v in keys.items())
    (map_dir / "config.yaml").write_text(lines + "\n", encoding="utf-8")


def test_vc1_concurrent_dispatch_on_isolation_off_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC1 [AC-1-GATE] [HC-3]: concurrent_dispatch=true + isolation='off' raises
    DispatchGateError — never silently degrades to sequential."""
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    branch = "test-st001-vc1-gate"

    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])
    # Config: flag on, isolation off (the forbidden contradiction).
    _write_config_keys(
        tmp_path,
        **{
            "execution.concurrent_dispatch": "true",
            "worktree.isolation": "off",
        },
    )

    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        with pytest.raises(map_orchestrator.DispatchGateError) as exc_info:
            map_orchestrator.compute_dispatch_gate(branch, tmp_path)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr

    assert "isolation" in str(exc_info.value).lower(), (
        f"DispatchGateError message should mention isolation: {exc_info.value}"
    )


def test_vc2_flag_false_returns_sequential_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC2 [AC-1-GATE] [HC-1] (Slice 6 reframe): per-repo concurrent_dispatch=false
    and global kill-switch both force sequential with no DispatchGateError.

    Sub-test A: MAP_EFFICIENT_SEQUENTIAL_ONLY=1 (kill-switch) → sequential.
    Sub-test B: explicit false in config → sequential.
    Sub-test C: get_wave_step under kill-switch stays sequential.
    """
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    branch = "test-st001-vc2-sequential"

    # Width>=2 wave — would be parallelizable without the sequential gates.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])

    # Sub-test A: kill-switch → sequential (no config needed).
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        result_a = map_orchestrator.compute_dispatch_gate(branch, tmp_path)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr
    monkeypatch.delenv("MAP_EFFICIENT_SEQUENTIAL_ONLY")

    assert result_a["dispatch_mode"] == "sequential", (
        f"Kill-switch → dispatch_mode must be 'sequential': {result_a}"
    )
    assert result_a["reason"] == map_orchestrator.WAVE_REASON_SEQUENTIAL_ONLY_ENV, (
        f"Kill-switch → reason must be WAVE_REASON_SEQUENTIAL_ONLY_ENV: {result_a}"
    )

    # Sub-test B: explicit false in config (per-repo opt-out) → sequential.
    _write_config_keys(
        tmp_path,
        **{
            "execution.concurrent_dispatch": "false",
            "worktree.isolation": "auto",  # isolation=auto so the dispatch flag is the gate
        },
    )
    _orig_msr2 = _sys.modules.pop("map_step_runner", None)
    try:
        result_b = map_orchestrator.compute_dispatch_gate(branch, tmp_path)
    finally:
        if _orig_msr2 is not None:
            _sys.modules["map_step_runner"] = _orig_msr2

    assert result_b["dispatch_mode"] == "sequential", (
        f"Explicit false → dispatch_mode must be 'sequential': {result_b}"
    )
    assert result_b["reason"] == map_orchestrator.WAVE_REASON_DISPATCH_SEQUENTIAL, (
        f"Explicit false → reason must be WAVE_REASON_DISPATCH_SEQUENTIAL: {result_b}"
    )

    # Sub-test C: get_wave_step under kill-switch stays sequential and never raises.
    _write_step_state(branch, tmp_path, execution_waves=[["ST-001", "ST-002"]])
    monkeypatch.setenv("MAP_EFFICIENT_SEQUENTIAL_ONLY", "1")
    _orig_msr3 = _sys.modules.pop("map_step_runner", None)
    try:
        wave_result = map_orchestrator.get_wave_step(branch)
    finally:
        if _orig_msr3 is not None:
            _sys.modules["map_step_runner"] = _orig_msr3
    monkeypatch.delenv("MAP_EFFICIENT_SEQUENTIAL_ONLY")

    assert wave_result["dispatch_mode"] == "sequential", (
        f"get_wave_step kill-switch → dispatch_mode must be 'sequential': {wave_result}"
    )
    assert wave_result["concurrency_enabled"] is False, (
        f"get_wave_step kill-switch → concurrency_enabled must be False: {wave_result}"
    )


def test_vc3_flag_on_isolation_required_concurrent_and_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VC3 [AC-1-GATE]: dispatch_mode=='concurrent' iff full conjunction holds;
    non-parallelizable plan → sequential+WAVE_REASON_GATE_NOT_PARALLELIZABLE (not error);
    reason codes are stable and distinct."""
    import sys as _sys

    monkeypatch.chdir(tmp_path)
    branch_conc = "test-st001-vc3-concurrent"
    branch_seq = "test-st001-vc3-seq-no-parallel"

    # --- Case A: flag=true, isolation=required, width>=2 wave → concurrent ---
    _write_step_state(branch_conc, tmp_path, execution_waves=[["ST-001", "ST-002"]])
    _write_config_keys(
        tmp_path,
        **{
            "execution.concurrent_dispatch": "true",
            "execution.wave_mode": "on",
            "worktree.isolation": "required",
        },
    )

    _orig_msr = _sys.modules.pop("map_step_runner", None)
    try:
        result_conc = map_orchestrator.compute_dispatch_gate(branch_conc, tmp_path)
    finally:
        if _orig_msr is not None:
            _sys.modules["map_step_runner"] = _orig_msr

    assert result_conc["dispatch_mode"] == "concurrent", (
        f"flag=true + isolation=required + width>=2 → expected concurrent: {result_conc}"
    )
    assert result_conc["reason"] == map_orchestrator.WAVE_REASON_CONCURRENT_GATED, (
        f"concurrent path → reason must be WAVE_REASON_CONCURRENT_GATED: {result_conc}"
    )

    # --- Case B: flag=true, isolation=required, all width-1 → sequential (not error) ---
    _write_step_state(branch_seq, tmp_path, execution_waves=[["ST-001"], ["ST-002"]])
    # Keep same config (flag=true, isolation=required, wave_mode=on)

    _orig_msr2 = _sys.modules.pop("map_step_runner", None)
    try:
        result_seq = map_orchestrator.compute_dispatch_gate(branch_seq, tmp_path)
    finally:
        if _orig_msr2 is not None:
            _sys.modules["map_step_runner"] = _orig_msr2

    assert result_seq["dispatch_mode"] == "sequential", (
        f"flag=true + isolation=required + all-width-1 → expected sequential: {result_seq}"
    )
    assert result_seq["reason"] == map_orchestrator.WAVE_REASON_GATE_NOT_PARALLELIZABLE, (
        f"not-parallelizable → reason must be WAVE_REASON_GATE_NOT_PARALLELIZABLE: {result_seq}"
    )

    # --- Reason codes are stable non-empty distinct strings ---
    codes = {
        map_orchestrator.WAVE_REASON_CONCURRENT_GATED,
        map_orchestrator.WAVE_REASON_GATE_NOT_PARALLELIZABLE,
        map_orchestrator.WAVE_REASON_DISPATCH_SEQUENTIAL,
        map_orchestrator.WAVE_REASON_NO_WAVES,
        map_orchestrator.WAVE_REASON_WAVE_COMPLETE,
    }
    assert len(codes) == 5, f"All five reason codes must be distinct: {codes}"
    assert all(isinstance(c, str) and c for c in codes), (
        f"All reason codes must be non-empty strings: {codes}"
    )


def test_vc4_mixed_plan_current_width1_later_width2_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2 mixed-plan gate: width-1 current wave + width>=2 later wave -> sequential
    with WAVE_REASON_CURRENT_WAVE_SEQUENTIAL (not WAVE_REASON_GATE_NOT_PARALLELIZABLE).

    Non-tautology: pointing current_wave_index at the width-2 wave (Case B below)
    yields concurrent — proving the two reason-code paths are distinct.
    """
    import sys as _sys

    monkeypatch.chdir(tmp_path)

    _write_config_keys(
        tmp_path,
        **{
            "execution.concurrent_dispatch": "true",
            "execution.wave_mode": "auto",
            "worktree.isolation": "required",
        },
    )

    # Case A: current wave is width-1 (index=0), later wave is width-2 (index=1).
    branch_a = "test-st001-vc4-mixed-plan-current-1"
    _write_step_state(
        branch_a,
        tmp_path,
        execution_waves=[["ST-001"], ["ST-002", "ST-003"]],
        extra={"current_wave_index": 0},
    )

    _orig_msr_a = _sys.modules.pop("map_step_runner", None)
    try:
        result_a = map_orchestrator.compute_dispatch_gate(branch_a, tmp_path)
    finally:
        if _orig_msr_a is not None:
            _sys.modules["map_step_runner"] = _orig_msr_a

    assert result_a["dispatch_mode"] == "sequential", (
        f"width-1 current wave must yield sequential: {result_a}"
    )
    assert result_a["reason"] == map_orchestrator.WAVE_REASON_CURRENT_WAVE_SEQUENTIAL, (
        f"mixed-plan with width-1 current wave must use WAVE_REASON_CURRENT_WAVE_SEQUENTIAL, "
        f"not WAVE_REASON_GATE_NOT_PARALLELIZABLE: {result_a}"
    )

    # Case B (non-tautology probe): same plan, current_wave_index=1 (the width-2 wave)
    # must return concurrent — proving Case A's reason is about CURRENT wave, not the plan.
    branch_b = "test-st001-vc4-mixed-plan-current-2"
    _write_step_state(
        branch_b,
        tmp_path,
        execution_waves=[["ST-001"], ["ST-002", "ST-003"]],
        extra={"current_wave_index": 1},
    )

    _orig_msr_b = _sys.modules.pop("map_step_runner", None)
    try:
        result_b = map_orchestrator.compute_dispatch_gate(branch_b, tmp_path)
    finally:
        if _orig_msr_b is not None:
            _sys.modules["map_step_runner"] = _orig_msr_b

    assert result_b["dispatch_mode"] == "concurrent", (
        f"width-2 current wave (index=1) must yield concurrent: {result_b}"
    )
    assert result_b["reason"] == map_orchestrator.WAVE_REASON_CONCURRENT_GATED, (
        f"width-2 current wave must use WAVE_REASON_CONCURRENT_GATED: {result_b}"
    )


# ============================================================================
# Regression Tests — Bug #320: set_waves ImportError fallback for uv tool installs
# ============================================================================


class TestSetWavesImportFallback:
    """Regression tests for bug #320.

    Previously the ImportError fallback in set_waves only searched source-checkout
    layout paths (src/mapify_cli/dependency_graph.py relative to parents of __file__).
    When mapify-cli is installed via 'uv tool install' or 'pipx install', the package
    lives in ~/.local/share/uv/tools/mapify-cli/lib/python3.X/site-packages/, so the
    fallback silently failed.

    Fix: extend the candidate list to include common installed-package locations.
    """

    def test_set_waves_error_message_mentions_uv_tool_path(
        self, branch_dir: str, tmp_path: Path
    ) -> None:
        """When dependency_graph cannot be found anywhere, the error message must
        mention the uv-tool Python path so users know how to fix it (regression #320)."""
        from unittest import mock

        # Write a minimal blueprint so we can get past the file-reading step.
        bp_dir = tmp_path / ".map" / branch_dir
        bp_dir.mkdir(parents=True, exist_ok=True)
        blueprint = {
            "subtasks": [
                {"id": "ST-001", "dependencies": [], "affected_files": []},
            ]
        }
        bp_file = bp_dir / "blueprint.json"
        bp_file.write_text(json.dumps(blueprint), encoding="utf-8")

        # Simulate a totally missing dependency_graph: make importlib.util.spec_from_file_location
        # always return None (as if no candidate file exists), and make Path.home() point to an
        # empty tmp dir (so no uv/pipx tool dirs exist to find).
        empty_home = tmp_path / "fake_home"
        empty_home.mkdir()

        with (
            mock.patch.object(
                map_orchestrator.importlib.util,
                "spec_from_file_location",
                return_value=None,
            ) if hasattr(map_orchestrator, "importlib") else mock.patch("importlib.util.spec_from_file_location", return_value=None),
            mock.patch("pathlib.Path.home", return_value=empty_home),
            mock.patch.dict(sys.modules, {"mapify_cli.dependency_graph": None}),
        ):
            result = map_orchestrator.set_waves(branch_dir, str(bp_file))

        assert result["status"] == "error"
        msg = result.get("message", "")
        assert "uv tool install" in msg or "uv-tool" in msg or "mapify-cli" in msg, (
            f"Error message should guide users to the uv-tool install path. Got: {msg!r}. "
            "Bug #320: previously had no guidance for uv tool install users."
        )

    def test_set_waves_fallback_finds_module_in_fake_uv_tool_dir(
        self, branch_dir: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """set_waves must succeed when dependency_graph.py is only available
        at the uv-tool install layout path (regression for bug #320).

        We build a fake uv-tool directory tree rooted at a tmp home, plant the
        REAL dependency_graph.py there, then simulate the package-level import
        failing so the fallback path is exercised.
        """
        import shutil
        from unittest import mock

        # Build the fake uv-tool installed-package layout.
        fake_home = tmp_path / "fake_home"
        py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        site_packages = (
            fake_home
            / ".local" / "share" / "uv" / "tools" / "mapify-cli"
            / "lib" / py_version / "site-packages" / "mapify_cli"
        )
        site_packages.mkdir(parents=True)

        # Copy the real dependency_graph.py into the fake site-packages.
        real_dg = (
            Path(__file__).resolve().parents[1]
            / "src" / "mapify_cli" / "dependency_graph.py"
        )
        shutil.copy(real_dg, site_packages / "dependency_graph.py")

        # Write a blueprint to work with.
        bp_dir = tmp_path / ".map" / branch_dir
        bp_dir.mkdir(parents=True, exist_ok=True)
        blueprint = {
            "subtasks": [
                {"id": "ST-001", "dependencies": [], "affected_files": []},
                {"id": "ST-002", "dependencies": ["ST-001"], "affected_files": []},
            ]
        }
        bp_file = bp_dir / "blueprint.json"
        bp_file.write_text(json.dumps(blueprint), encoding="utf-8")

        # Patch Path.home() so the fallback search lands in our fake tree.
        monkeypatch.setattr(map_orchestrator.Path, "home", staticmethod(lambda: fake_home))

        # Force the package-level import to raise ImportError so the fallback runs.
        with mock.patch.dict(sys.modules, {"mapify_cli.dependency_graph": None}):
            result = map_orchestrator.set_waves(branch_dir, str(bp_file))

        assert result["status"] == "success", (
            f"set_waves should succeed when dependency_graph is found in the fake "
            f"uv-tool install dir. status={result.get('status')!r}, "
            f"message={result.get('message')!r}. "
            "Bug #320: fallback didn't include uv tool install paths."
        )
        waves = result["execution_waves"]
        assert waves[0] == ["ST-001"]
        assert waves[1] == ["ST-002"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
