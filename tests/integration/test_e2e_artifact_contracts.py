"""
Level 1 — E2E Artifact Contract Tests (no LLM)

Tests the full map-plan → map-efficient → map-review flow by validating:
1. Artifact handoff: output of phase N is valid input for phase N+1
2. State machine lifecycle: init → all phases → complete
3. Wave computation from blueprint DAG
4. Review handoff assembly from execution artifacts
5. Degradation: missing/corrupt artifacts produce clear errors

These tests use golden fixtures instead of LLM output, making them fast,
deterministic, and suitable for CI.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

# ---------- path setup for template scripts ----------
FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_PATH = REPO_ROOT / "src" / "mapify_cli" / "templates" / "map" / "scripts"
SRC_PATH = REPO_ROOT / "src"

# Add src/ so set_waves can import mapify_cli.dependency_graph
sys.path.insert(0, str(SRC_PATH))
sys.path.insert(0, str(SCRIPTS_PATH))

import map_orchestrator  # noqa: E402
import map_step_runner  # noqa: E402

# DependencyGraph may not be importable if mapify_cli deps are missing (e.g. Python <3.11)
try:
    from mapify_cli.dependency_graph import DependencyGraph  # noqa: F401

    _HAS_DEPENDENCY_GRAPH = True
except (ImportError, ModuleNotFoundError):
    _HAS_DEPENDENCY_GRAPH = False

needs_dependency_graph = pytest.mark.skipif(
    not _HAS_DEPENDENCY_GRAPH,
    reason="mapify_cli.dependency_graph not importable (needs Python 3.11+ with deps)",
)


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def branch():
    return "test-auth"


@pytest.fixture
def workspace(tmp_path, monkeypatch, branch):
    """Set up a clean .map/<branch>/ workspace with patched branch detection."""
    map_dir = tmp_path / ".map" / branch
    map_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(map_orchestrator, "get_branch_name", lambda: branch)
    monkeypatch.setattr(map_step_runner, "get_branch_name", lambda: branch)
    return map_dir


def _load_fixture(name: str) -> str:
    """Read a fixture file as text."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _load_fixture_json(name: str) -> dict:
    """Read a fixture file as JSON."""
    return json.loads(_load_fixture(name))


def _copy_fixture(name: str, dest: Path) -> Path:
    """Copy a fixture file to destination."""
    src = FIXTURES_DIR / name
    target = dest / src.name
    shutil.copy2(src, target)
    return target


# =====================================================================
# Phase 1: map-plan artifact production
# =====================================================================


class TestPlanArtifactProduction:
    """Verify that plan phase produces artifacts in the expected format."""

    def test_blueprint_has_required_fields(self):
        """Blueprint JSON must have subtasks with id, dependencies, affected_files."""
        bp = _load_fixture_json("blueprint.json")
        assert "subtasks" in bp
        for st in bp["subtasks"]:
            assert "id" in st, f"Subtask missing 'id': {st}"
            assert "dependencies" in st, f"Subtask {st['id']} missing 'dependencies'"
            assert (
                "affected_files" in st
            ), f"Subtask {st['id']} missing 'affected_files'"

    def test_blueprint_aag_contracts_present(self):
        """Each subtask should carry an AAG contract string."""
        bp = _load_fixture_json("blueprint.json")
        for st in bp["subtasks"]:
            assert "aag_contract" in st, f"Subtask {st['id']} missing 'aag_contract'"
            assert (
                len(st["aag_contract"]) > 10
            ), f"AAG contract too short for {st['id']}"

    def test_blueprint_dependency_ids_reference_existing_subtasks(self):
        """All dependency references must point to subtasks that exist."""
        bp = _load_fixture_json("blueprint.json")
        all_ids = {st["id"] for st in bp["subtasks"]}
        for st in bp["subtasks"]:
            for dep in st["dependencies"]:
                assert (
                    dep in all_ids
                ), f"Subtask {st['id']} depends on '{dep}' which doesn't exist"

    def test_task_plan_wrapped_in_map_tags(self):
        """task_plan.md must be wrapped in <MAP_Plan_v1_0> tags."""
        plan = _load_fixture("task_plan.md")
        assert "<MAP_Plan_v1_0>" in plan
        assert "</MAP_Plan_v1_0>" in plan

    def test_task_plan_references_all_subtask_ids(self):
        """task_plan.md should mention every subtask from the blueprint."""
        bp = _load_fixture_json("blueprint.json")
        plan = _load_fixture("task_plan.md")
        for st in bp["subtasks"]:
            assert st["id"] in plan, f"task_plan.md missing reference to {st['id']}"

    def test_plan_handoff_has_required_fields(self):
        """plan_handoff.json must carry canonical runtime bootstrap data."""
        handoff = _load_fixture_json("plan_handoff.json")
        assert handoff["source"] == "map-plan"
        assert handoff["subtask_sequence"] == ["ST-001", "ST-002", "ST-003", "ST-004"]
        assert "aag_contracts" in handoff
        assert "artifacts" in handoff
        assert handoff["artifacts"]["blueprint"].endswith("blueprint.json")

    def test_step_state_initialized_matches_schema(self):
        """Initial step_state.json must have all required fields."""
        state = _load_fixture_json("step_state_initialized.json")
        required_fields = [
            "workflow",
            "current_subtask_id",
            "subtask_sequence",
            "current_step_id",
            "current_step_phase",
            "completed_steps",
            "pending_steps",
            "plan_approved",
            "execution_waves",
        ]
        for field in required_fields:
            assert field in state, f"step_state.json missing '{field}'"

    def test_step_state_starts_at_decompose(self):
        """Initial state should start at DECOMPOSE phase."""
        state = _load_fixture_json("step_state_initialized.json")
        assert state["current_step_phase"] == "DECOMPOSE"
        assert state["current_step_id"] == "1.0"
        assert not state["completed_steps"]


# =====================================================================
# Phase 2: map-plan → map-efficient handoff
# =====================================================================


class TestPlanToEfficientHandoff:
    """Verify that plan artifacts are correctly consumed by the efficient phase."""

    def test_orchestrator_initializes_from_blueprint(self, workspace, branch):
        """Orchestrator should be able to initialize workflow from plan artifacts."""
        result = map_orchestrator.initialize_workflow("Add auth", branch)
        assert result["status"] == "initialized"

        state_file = workspace / "step_state.json"
        assert state_file.exists()

    @needs_dependency_graph
    def test_set_waves_computes_correct_dag(self, workspace, branch):
        """set_waves should build execution waves from blueprint DAG."""
        # Copy blueprint to workspace
        bp_fixture = FIXTURES_DIR / "blueprint.json"
        bp_dest = workspace / "blueprint.json"
        shutil.copy2(bp_fixture, bp_dest)

        # Initialize state first
        map_orchestrator.initialize_workflow("Add auth", branch)

        # Set waves from blueprint
        result = map_orchestrator.set_waves(branch, str(bp_dest))
        assert result["status"] == "success"
        assert result["wave_count"] >= 2  # ST-001 alone, then ST-002+003, then ST-004

        waves = result["execution_waves"]
        # ST-001 has no deps → wave 0
        assert "ST-001" in waves[0]
        # ST-004 depends on ST-002 and ST-003 → must be in a later wave
        st004_wave_idx = next(i for i, w in enumerate(waves) if "ST-004" in w)
        st002_wave_idx = next(i for i, w in enumerate(waves) if "ST-002" in w)
        st003_wave_idx = next(i for i, w in enumerate(waves) if "ST-003" in w)
        assert st004_wave_idx > st002_wave_idx
        assert st004_wave_idx > st003_wave_idx

    def test_get_next_step_walks_plan_phases(self, workspace, branch):
        """Orchestrator should walk through plan phases 1.0 → 1.5 → 1.55 → 1.6."""
        map_orchestrator.initialize_workflow("Add auth", branch)

        # Step 1.0: DECOMPOSE
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.0"
        assert step["phase"] == "DECOMPOSE"

        # Validate and advance
        result = map_orchestrator.validate_step("1.0", branch)
        assert result["valid"]

        # Step 1.5: INIT_PLAN
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.5"
        assert step["phase"] == "INIT_PLAN"

        result = map_orchestrator.validate_step("1.5", branch)
        assert result["valid"]

        # Step 1.55: REVIEW_PLAN (needs approval)
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.55"

        # Can't validate without approval
        result = map_orchestrator.validate_step("1.55", branch)
        assert not result["valid"]
        assert "not approved" in result["message"].lower()

        # Approve and validate
        map_orchestrator.set_plan_approved("true", branch)
        result = map_orchestrator.validate_step("1.55", branch)
        assert result["valid"]

        # Step 1.56 is auto-skipped (CHOOSE_MODE)
        # Step 1.6: INIT_STATE
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.6"
        assert step["phase"] == "INIT_STATE"

    def test_plan_complete_state_has_waves(self):
        """State after plan completion should have execution_waves and subtask_phases."""
        state = _load_fixture_json("step_state_plan_complete.json")
        assert state["plan_approved"] is True
        assert len(state["execution_waves"]) >= 2
        assert state["current_subtask_id"] == "ST-001"
        assert "1.0" in state["completed_steps"]
        assert "1.5" in state["completed_steps"]
        assert "1.6" in state["completed_steps"]


# =====================================================================
# Phase 3: map-efficient execution lifecycle
# =====================================================================


class TestEfficientExecutionLifecycle:
    """Test the Actor → Monitor loop with waves, retries, and advancement."""

    def _setup_plan_complete_state(self, workspace, branch):
        """Load the 'plan complete' fixture into workspace."""
        state_data = _load_fixture_json("step_state_plan_complete.json")
        state_file = workspace / "step_state.json"
        state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")

        # Also need blueprint for wave operations
        bp_fixture = FIXTURES_DIR / "blueprint.json"
        shutil.copy2(bp_fixture, workspace / "blueprint.json")

    def test_wave_step_returns_parallel_batch(self, workspace, branch):
        """get_wave_step should return parallel subtask batch for wave with >1 subtask."""
        self._setup_plan_complete_state(workspace, branch)

        # Wave 0: ST-001 only → sequential
        wave_step = map_orchestrator.get_wave_step(branch)
        assert wave_step["mode"] == "sequential"
        assert len(wave_step["subtasks"]) == 1
        assert wave_step["subtasks"][0]["subtask_id"] == "ST-001"

    def test_wave_advance_through_all_waves(self, workspace, branch):
        """Should be able to advance through all waves to completion."""
        self._setup_plan_complete_state(workspace, branch)

        wave_count = len(
            _load_fixture_json("step_state_plan_complete.json")["execution_waves"]
        )

        for i in range(wave_count):
            wave_step = map_orchestrator.get_wave_step(branch)
            assert not wave_step["is_complete"], f"Completed too early at wave {i}"

            # Simulate: validate each subtask's ACTOR → MONITOR
            for st_info in wave_step["subtasks"]:
                st_id = st_info["subtask_id"]
                # Actor done
                map_orchestrator.validate_wave_step(st_id, "2.3", branch)
                # Monitor done
                map_orchestrator.validate_wave_step(st_id, "2.4", branch)

            # Advance to next wave
            result = map_orchestrator.advance_wave(branch)
            assert result["status"] == "success"

        # Should be complete now
        wave_step = map_orchestrator.get_wave_step(branch)
        assert wave_step["is_complete"]

    def test_monitor_failure_retries_actor(self, workspace, branch):
        """Monitor failure should reset phase to ACTOR and increment retry count."""
        self._setup_plan_complete_state(workspace, branch)

        # Simulate monitor failure for ST-001 in wave mode
        result = map_orchestrator.wave_monitor_failed("ST-001", branch, "Fix imports")
        assert result["status"] == "retrying"
        assert result["retry_count"] == 1

        # Phase should be back to ACTOR
        state = map_orchestrator.StepState.load(workspace / "step_state.json")
        assert state.subtask_phases.get("ST-001") == "2.3"  # ACTOR step

    def test_max_retries_escalates(self, workspace, branch):
        """Exceeding max retries should escalate to user."""
        self._setup_plan_complete_state(workspace, branch)

        # Hit max retries
        for i in range(6):
            result = map_orchestrator.wave_monitor_failed("ST-001", branch, f"Fail {i}")

        assert result["status"] == "max_retries"

    def test_human_artifacts_created(self, workspace, branch):
        """ensure_human_artifacts should create qa and pr-draft files."""
        result = map_step_runner.ensure_human_artifacts()
        assert result["status"] == "success"
        assert (workspace / "qa-001.md").exists()
        assert (workspace / "pr-draft.md").exists()

    def test_numbered_artifact_increments(self, workspace, branch):
        """Code review artifacts should auto-increment: 001 → 002 → 003."""
        (workspace / "code-review-001.md").write_text("review 1", encoding="utf-8")

        result = map_step_runner.next_numbered_artifact_path("code-review")
        assert result["file_name"] == "code-review-002.md"

        (workspace / "code-review-002.md").write_text("review 2", encoding="utf-8")

        result = map_step_runner.next_numbered_artifact_path("code-review")
        assert result["file_name"] == "code-review-003.md"


# =====================================================================
# Phase 4: map-efficient → map-review handoff
# =====================================================================


class TestEfficientToReviewHandoff:
    """Verify that execution artifacts are consumable by the review phase."""

    def test_resume_briefing_reads_review_artifacts(self, workspace, branch):
        """get_resume_briefing should find and parse review + verification artifacts."""
        # Place execution artifacts
        shutil.copy2(FIXTURES_DIR / "code_review.md", workspace / "code-review-001.md")
        shutil.copy2(
            FIXTURES_DIR / "verification_summary.md",
            workspace / "verification-summary.md",
        )
        (workspace / "qa-001.md").write_text("# QA passed", encoding="utf-8")

        briefing = map_orchestrator.get_resume_briefing(branch)
        assert briefing["branch"] == branch
        assert briefing["latest_review_path"] is not None
        assert "code-review-001" in briefing["latest_review_path"]
        assert briefing["verification_summary_path"] is not None
        assert briefing["latest_verification_verdict"] == "READY FOR REVIEW"

    def test_resume_briefing_extracts_suggested_fixes(self, workspace, branch):
        """Briefing should extract bullet-point fixes from latest review."""
        review_content = (
            "# Code Review 001\n\n"
            "## Issues\n"
            "- Fix missing type hint on register()\n"
            "- Add rate limit check before password comparison\n"
            "- Remove debug print statement in jwt.py\n"
        )
        (workspace / "code-review-001.md").write_text(review_content, encoding="utf-8")

        briefing = map_orchestrator.get_resume_briefing(branch)
        assert len(briefing["suggested_fixes"]) == 3
        assert "type hint" in briefing["suggested_fixes"][0]

    def test_build_resume_briefing_combines_progress_and_artifacts(
        self, workspace, branch
    ):
        """build_resume_briefing should merge plan progress with artifact context."""
        # Set up state with some completed subtasks
        state = map_orchestrator.StepState()
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.current_subtask_id = "ST-002"
        state.current_step_phase = "ACTOR"
        state.subtask_index = 1
        state.save(workspace / "step_state.json")

        # Place review artifacts
        shutil.copy2(FIXTURES_DIR / "code_review.md", workspace / "code-review-001.md")
        shutil.copy2(
            FIXTURES_DIR / "verification_summary.md",
            workspace / "verification-summary.md",
        )

        result = map_orchestrator.build_resume_briefing(branch)
        assert result["branch"] == branch
        assert result["current_subtask"] == "ST-002"
        assert result["current_phase"] == "ACTOR"


# =====================================================================
# Phase 5: Full lifecycle (plan → efficient → review readiness)
# =====================================================================


class TestFullLifecycle:
    """Smoke test: walk through the entire state machine from init to completion."""

    def test_full_init_to_completion(self, workspace, branch):
        """Walk the full orchestrator lifecycle without LLM."""
        # 1. Initialize
        result = map_orchestrator.initialize_workflow("Add auth", branch)
        assert result["status"] == "initialized"

        # 2. Walk plan phases
        for step_id in ["1.0", "1.5"]:
            step = map_orchestrator.get_next_step(branch)
            assert step["step_id"] == step_id
            map_orchestrator.validate_step(step_id, branch)

        # 3. Approve plan
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.55"
        map_orchestrator.set_plan_approved("true", branch)
        map_orchestrator.validate_step("1.55", branch)

        # 4. INIT_STATE (1.56 auto-skipped)
        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.6"

        # Inject subtask sequence before validating INIT_STATE
        state = map_orchestrator.StepState.load(workspace / "step_state.json")
        state.subtask_sequence = ["ST-001", "ST-002"]
        state.save(workspace / "step_state.json")

        map_orchestrator.validate_step("1.6", branch)

        # 5. Verify subtask is now set
        state = map_orchestrator.StepState.load(workspace / "step_state.json")
        assert state.current_subtask_id == "ST-001"

        # 6. Walk subtask execution steps (RESEARCH → ACTOR → MONITOR)
        for step_id in ["2.2", "2.3", "2.4"]:
            step = map_orchestrator.get_next_step(branch)
            assert (
                step["step_id"] == step_id
            ), f"Expected {step_id}, got {step['step_id']}"
            map_orchestrator.validate_step(step_id, branch)

        # 7. Should advance to next subtask
        step = map_orchestrator.get_next_step(branch)
        assert step["current_subtask"] == "ST-002"
        assert step["step_id"] == "2.2"

        # 8. Complete second subtask
        for step_id in ["2.2", "2.3", "2.4"]:
            step = map_orchestrator.get_next_step(branch)
            assert step["step_id"] == step_id
            map_orchestrator.validate_step(step_id, branch)

        # 9. All done
        step = map_orchestrator.get_next_step(branch)
        assert step["is_complete"]
        assert step["phase"] == "COMPLETE"

    @needs_dependency_graph
    def test_full_wave_lifecycle(self, workspace, branch):
        """Walk the wave-based parallel execution lifecycle."""
        # 1. Initialize with blueprint
        map_orchestrator.initialize_workflow("Add auth", branch)
        bp_fixture = FIXTURES_DIR / "blueprint.json"
        shutil.copy2(bp_fixture, workspace / "blueprint.json")

        # 2. Walk plan phases to completion
        for step_id in ["1.0", "1.5"]:
            map_orchestrator.get_next_step(branch)
            map_orchestrator.validate_step(step_id, branch)

        map_orchestrator.set_plan_approved("true", branch)
        map_orchestrator.validate_step("1.55", branch)

        # Inject subtask sequence
        state = map_orchestrator.StepState.load(workspace / "step_state.json")
        state.subtask_sequence = ["ST-001", "ST-002", "ST-003", "ST-004"]
        state.save(workspace / "step_state.json")

        step = map_orchestrator.get_next_step(branch)
        assert step["step_id"] == "1.6"
        map_orchestrator.validate_step("1.6", branch)

        # 3. Set waves from blueprint
        result = map_orchestrator.set_waves(branch)
        assert result["status"] == "success"
        waves = result["execution_waves"]

        # 4. Execute waves
        for wave_idx, wave in enumerate(waves):
            wave_step = map_orchestrator.get_wave_step(branch)
            assert not wave_step["is_complete"]
            assert wave_step["wave_index"] == wave_idx

            for st_info in wave_step["subtasks"]:
                st_id = st_info["subtask_id"]
                map_orchestrator.validate_wave_step(st_id, "2.3", branch)
                map_orchestrator.validate_wave_step(st_id, "2.4", branch)

            map_orchestrator.advance_wave(branch)

        # 5. All waves done
        wave_step = map_orchestrator.get_wave_step(branch)
        assert wave_step["is_complete"]

        # 6. Verify review handoff artifacts can be created
        map_step_runner.ensure_human_artifacts()
        assert (workspace / "qa-001.md").exists()
        assert (workspace / "pr-draft.md").exists()


# =====================================================================
# Degradation tests
# =====================================================================


class TestDegradation:
    """Test behavior with missing or corrupt artifacts."""

    @needs_dependency_graph
    def test_set_waves_missing_blueprint(self, workspace, branch):
        """set_waves should return error when blueprint is missing."""
        map_orchestrator.initialize_workflow("Add auth", branch)
        result = map_orchestrator.set_waves(branch)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @needs_dependency_graph
    def test_set_waves_corrupt_blueprint(self, workspace, branch):
        """set_waves should return error on invalid JSON."""
        map_orchestrator.initialize_workflow("Add auth", branch)
        (workspace / "blueprint.json").write_text("{ invalid json", encoding="utf-8")
        result = map_orchestrator.set_waves(branch)
        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    @needs_dependency_graph
    def test_set_waves_empty_subtasks(self, workspace, branch):
        """set_waves should return error when subtasks list is empty."""
        map_orchestrator.initialize_workflow("Add auth", branch)
        (workspace / "blueprint.json").write_text('{"subtasks": []}', encoding="utf-8")
        result = map_orchestrator.set_waves(branch)
        assert result["status"] == "error"
        assert "no subtasks" in result["message"].lower()

    def test_load_state_from_corrupt_file(self, workspace, branch):
        """Loading corrupt step_state.json should return fresh state, not crash."""
        state_file = workspace / "step_state.json"
        state_file.write_text("not json at all", encoding="utf-8")

        state = map_orchestrator.StepState.load(state_file)
        assert state.workflow == "map-efficient"
        assert state.current_step_id == "1.0"

    def test_resume_briefing_missing_artifacts(self, workspace, branch):
        """get_resume_briefing should handle missing artifacts gracefully."""
        briefing = map_orchestrator.get_resume_briefing(branch)
        assert briefing["branch"] == branch
        assert briefing["latest_review_path"] is None
        assert briefing["verification_summary_path"] is None
        assert briefing["latest_verification_verdict"] is None

    def test_validate_step_mismatch(self, workspace, branch):
        """Validating a step that isn't current should fail."""
        map_orchestrator.initialize_workflow("Add auth", branch)
        result = map_orchestrator.validate_step("2.3", branch)
        assert not result["valid"]
        assert "mismatch" in result["message"].lower()

    def test_monitor_failed_wrong_phase(self, workspace, branch):
        """monitor_failed from non-MONITOR phase should error."""
        map_orchestrator.initialize_workflow("Add auth", branch)
        result = map_orchestrator.monitor_failed(branch, "some feedback")
        assert result["status"] == "error"
        assert "MONITOR" in result["message"]
