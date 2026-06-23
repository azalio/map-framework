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

import map_orchestrator  # noqa: E402  # pyright: ignore[reportMissingImports]


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
            "\n".join(
                [
                    "# Task Plan",
                    "",
                    "| ID | Title | concern | diff | risk | one-step | deps |",
                    "|----|-------|---------|------|------|----------|------|",
                    "| ST-001 | Migration 108 | data | small | medium | yes | - |",
                    "| ST-002 | Pure DecayDecision | runtime | medium | high | yes | ST-001 |",
                    "",
                ]
            ),
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

    def test_feedback_file_forwards_only_blocker_items(self, branch_dir, tmp_path):
        self._make_monitor_state(tmp_path, branch_dir)
        feedback = "\n".join(
            [
                "BLOCKER: build failed in src/app.py",
                "NON-BLOCKING: docs could mention another example",
                "nice-to-have: style could be more elegant",
                "Missing required test for handled timeout path",
            ]
        )

        result = map_orchestrator.monitor_failed(branch_dir, feedback)

        content = Path(result["feedback_file"]).read_text()
        assert "build failed" in content
        assert "Missing required test" in content
        assert "docs could mention" not in content
        assert "style could be more elegant" not in content
        assert "Actor may re-add or expand code only by naming" in content

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

    def test_wave_feedback_forwards_only_blocker_items(self, branch_dir, tmp_path):
        self._make_wave_state(tmp_path, branch_dir)
        feedback = "\n".join(
            [
                "CRITICAL: security regression in auth flow",
                "NON-BLOCKING: documentation could be longer",
                "cosmetic: volume is high",
            ]
        )

        result = map_orchestrator.wave_monitor_failed("ST-001", branch_dir, feedback)

        content = Path(result["feedback_file"]).read_text()
        assert "security regression" in content
        assert "documentation could be longer" not in content
        assert "volume is high" not in content

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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        sha_proc = _sp.run(
            ["git", "log", "-1", "--format=%H"], cwd=tmp_path,
            capture_output=True, text=True,
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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / ".gitignore").write_text(".map/\n")
        (tmp_path / "seed.txt").write_text("seed")
        (tmp_path / "tracked.py").write_text("x = 1\n")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        # Second (non-root) commit so HEAD has a parent and `git diff-tree`
        # yields a NON-empty diff_paths. Without this, a root commit produces an
        # empty diff and files_not_in_diff is never computed — the gitignore
        # test would then pass vacuously without exercising the filter.
        (tmp_path / "seed.txt").write_text("seed v2")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "second"], cwd=tmp_path, capture_output=True)

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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "leak.py").write_text("nope")  # untracked: scope leak
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("MAP_STRICT_SCOPE", "1")
        result = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert result["valid"] is False
        assert "Mutation-boundary violation" in result["message"]

    def test_warning_routes_feedback_to_actor_once(self, branch_dir, tmp_path, monkeypatch):
        """Option ii: a non-strict scope leak does NOT hard-fail, but the FIRST
        MONITOR validate routes it back to the Actor as feedback (valid=False +
        'Scope warning'); the subtask is recorded in scope_feedback_subtasks so a
        SECOND validate with the same leak passes (guard prevents retry-burn)."""
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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "leak.py").write_text("nope")  # untracked: out-of-scope leak
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("MAP_STRICT_SCOPE", raising=False)

        r1 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r1["valid"] is False, r1
        assert "Scope warning" in r1["message"], r1
        assert "leak.py" in r1["message"], r1
        persisted = map_orchestrator.StepState.load(state_file)
        assert "ST-001" in persisted.scope_feedback_subtasks, persisted.scope_feedback_subtasks

        # Same leak persists, but the once-guard now lets the gate pass (no hard block).
        r2 = map_orchestrator.validate_step("2.4", branch_dir, recommendation="proceed")
        assert r2["valid"] is True, r2

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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
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
        _sp.run(["git", "init"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
        (tmp_path / "seed.txt").write_text("seed")
        _sp.run(["git", "add", "seed.txt"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        # ST-001's work IS implemented and committed (the documented order).
        (tmp_path / "a.py").write_text("x = 1\n")
        _sp.run(["git", "add", "a.py"], cwd=tmp_path, capture_output=True)
        _sp.run(["git", "commit", "-m", "ST-001"], cwd=tmp_path, capture_output=True)
        sha = _sp.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
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
        )
        # The script doesn't have per-command help, but the parent parser
        # must list --recommendation among its options.
        result_root = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=10,
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
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit when --recommendation omitted; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
