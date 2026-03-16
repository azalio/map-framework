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
    (map_dir / "evidence").mkdir()
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


class TestValidateWaveStep:
    """Tests for validate_wave_step command."""

    def test_advances_subtask_phase(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.validate_wave_step("ST-001", "2.0", branch_dir)
        assert result["valid"] is True
        assert result["next_phase"] == "2.1"

    def test_actor_step_advances_to_monitor(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        # Create evidence file for actor step
        evidence_dir = Path(f".map/{branch_dir}/evidence")
        evidence = {
            "phase": "actor",
            "subtask_id": "ST-001",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        (evidence_dir / "actor_ST-001.json").write_text(
            json.dumps(evidence), encoding="utf-8"
        )
        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is True
        assert result["next_phase"] == "2.4"

    def test_missing_evidence_blocks_validation(self, branch_dir, sample_blueprint):
        map_orchestrator.set_waves(branch_dir, sample_blueprint)
        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is False
        assert "Evidence file missing" in result["message"]


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
            "current_step_phase": "XML_PACKET",
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
        state.pending_steps = ["1.55", "1.56", "1.6", "2.0", "2.1", "2.2", "2.3",
                               "2.4", "2.6", "2.7", "2.8", "2.9", "2.10", "2.11"]
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
        state.pending_steps = ["2.25", "2.26", "2.3", "2.4", "2.6", "2.7",
                               "2.8", "2.9", "2.10", "2.11"]
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
        state.pending_steps = ["2.25", "2.26", "2.3", "2.4", "2.6", "2.7",
                               "2.8", "2.9", "2.10", "2.11"]
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

        evidence = {
            "phase": "TEST_WRITER",
            "subtask_id": "ST-001",
            "status": "applied",
        }
        evidence_file = Path(f".map/{branch_dir}/evidence/test_writer_ST-001.json")
        evidence_file.write_text(json.dumps(evidence), encoding="utf-8")

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
        assert len(map_orchestrator.TDD_STEP_ORDER) == len(map_orchestrator.STEP_ORDER) + 2

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
        state.completed_steps = ["1.0", "1.5", "1.55", "1.56", "1.6",
                                 "2.0", "2.1", "2.2"]
        state.pending_steps = ["2.3", "2.4", "2.6", "2.7", "2.8",
                               "2.9", "2.10", "2.11"]
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
        state.pending_steps = ["2.25", "2.26", "2.3", "2.4", "2.6", "2.7",
                               "2.8", "2.9", "2.10", "2.11"]
        state.save(Path(f".map/{branch_dir}/step_state.json"))

        result = map_orchestrator.skip_step("2.25", branch_dir)
        assert result["status"] == "success"

        loaded = map_orchestrator.StepState.load(
            Path(f".map/{branch_dir}/step_state.json")
        )
        assert "2.25" not in loaded.pending_steps
        assert "2.25" in loaded.completed_steps

    def test_validate_wave_step_missing_evidence_dir(self, branch_dir, sample_blueprint):
        """validate_wave_step returns error when evidence directory is missing."""
        result = map_orchestrator.set_waves(branch_dir, sample_blueprint)
        assert result["status"] == "success"
        state_file = Path(f".map/{branch_dir}/step_state.json")
        state = map_orchestrator.StepState.load(state_file)
        state.subtask_phases = {"ST-001": "2.3"}
        # Remove evidence directory
        evidence_dir = Path(f".map/{branch_dir}/evidence")
        if evidence_dir.exists():
            import shutil
            shutil.rmtree(evidence_dir)
        state.save(state_file)

        result = map_orchestrator.validate_wave_step("ST-001", "2.3", branch_dir)
        assert result["valid"] is False
        assert "Evidence directory missing" in result["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
