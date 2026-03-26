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

import map_orchestrator  # noqa: E402


@pytest.fixture
def branch_dir(tmp_path, monkeypatch):
    """Create a temporary .map/<branch>/ directory and patch get_branch_name."""
    branch = "test-branch"
    map_dir = tmp_path / ".map" / branch
    map_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)
    return branch


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
        result = map_orchestrator.build_resume_briefing(branch_dir)

        # Should return a dict with at minimum the branch key
        assert "branch" in result
        assert result["branch"] == branch_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
