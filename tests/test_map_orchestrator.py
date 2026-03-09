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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
