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

import map_orchestrator  # type: ignore[import-not-found]
import map_step_runner  # type: ignore[import-not-found]

# DependencyGraph may not be importable if mapify_cli deps are missing (e.g. Python <3.11)
try:
    from mapify_cli.dependency_graph import DependencyGraph

    del DependencyGraph
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


def _write_valid_research(workspace: Path, subtask_id: str) -> None:
    project_dir = workspace.parents[1]
    source = project_dir / "src" / "service.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def handle() -> bool:\n    return True\n", encoding="utf-8")
    research_dir = workspace / "research"
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


class TestResearchLocalizationEvalContract:
    """Research localization eval is part of the no-provider E2E contract."""

    def test_mapify_research_eval_scores_fixture_repo(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from mapify_cli import app

        source = tmp_path / "src" / "service.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "".join(f"line {index}\n" for index in range(1, 41)),
            encoding="utf-8",
        )
        research_output = tmp_path / "research.json"
        research_output.write_text(
            json.dumps(
                {
                    "status": "OK",
                    "confidence": 0.9,
                    "search_stats": {
                        "files_scanned": 1,
                        "total_matches_found": 1,
                        "results_truncated": False,
                    },
                    "relevant_locations": [
                        {
                            "path": "src/service.py",
                            "lines": [20, 22],
                            "relevance": "Primary implementation branch.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        expected = tmp_path / "expected.json"
        expected.write_text(
            json.dumps(
                {
                    "expected_locations": [
                        {"path": "src/service.py", "lines": [20, 22]}
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            app,
            [
                "research-eval",
                "score",
                str(research_output),
                str(expected),
                "--repo-root",
                str(tmp_path),
                "--fail-under-file-f1",
                "1.0",
                "--fail-under-line-f1",
                "1.0",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["passed"] is True
        assert payload["score"]["exact_match_count"] == 1
        assert payload["score"]["file_level"]["f1"] == 1.0
        assert payload["score"]["line_level"]["f1"] == 1.0


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
        del workspace
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
        del branch
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
        result: dict[str, object] = {}
        for i in range(6):
            result = map_orchestrator.wave_monitor_failed("ST-001", branch, f"Fail {i}")

        assert result["status"] == "max_retries"

    def test_human_artifacts_created(self, workspace, branch):
        """ensure_human_artifacts should create qa and pr-draft files."""
        del branch
        result = map_step_runner.ensure_human_artifacts()
        assert result["status"] == "success"
        assert (workspace / "qa-001.md").exists()
        assert (workspace / "pr-draft.md").exists()

    def test_numbered_artifact_increments(self, workspace, branch):
        """Code review artifacts should auto-increment: 001 → 002 → 003."""
        del branch
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

        # 6. Walk subtask execution steps (RESEARCH → ACTOR → MONITOR).
        # validate_step("2.2") now enforces that save_research wrote a real
        # artifact for the current subtask (MANDATORY RESEARCH); plant one
        # per subtask so the gate accepts.
        _write_valid_research(workspace, "ST-001")
        for step_id in ["2.2", "2.3", "2.4"]:
            step = map_orchestrator.get_next_step(branch)
            assert (
                step["step_id"] == step_id
            ), f"Expected {step_id}, got {step['step_id']}"
            # ST-003: closing 2.4 now requires Monitor's recommendation.
            rec = "proceed" if step_id == "2.4" else None
            map_orchestrator.validate_step(step_id, branch, recommendation=rec)

        # 7. Should advance to next subtask
        step = map_orchestrator.get_next_step(branch)
        assert step["current_subtask"] == "ST-002"
        assert step["step_id"] == "2.2"

        # 8. Complete second subtask
        _write_valid_research(workspace, "ST-002")
        for step_id in ["2.2", "2.3", "2.4"]:
            step = map_orchestrator.get_next_step(branch)
            assert step["step_id"] == step_id
            # ST-003: closing 2.4 now requires Monitor's recommendation.
            rec = "proceed" if step_id == "2.4" else None
            map_orchestrator.validate_step(step_id, branch, recommendation=rec)

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
        for wave_idx in range(len(waves)):
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
        del workspace
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
        del branch
        state_file = workspace / "step_state.json"
        state_file.write_text("not json at all", encoding="utf-8")

        state = map_orchestrator.StepState.load(state_file)
        assert state.workflow == "map-efficient"
        assert state.current_step_id == "1.0"

    def test_resume_briefing_missing_artifacts(self, workspace, branch):
        """get_resume_briefing should handle missing artifacts gracefully."""
        del workspace
        briefing = map_orchestrator.get_resume_briefing(branch)
        assert briefing["branch"] == branch
        assert briefing["latest_review_path"] is None
        assert briefing["verification_summary_path"] is None
        assert briefing["latest_verification_verdict"] is None

    def test_validate_step_mismatch(self, workspace, branch):
        """Validating a step that isn't current should fail."""
        del workspace
        map_orchestrator.initialize_workflow("Add auth", branch)
        result = map_orchestrator.validate_step("2.3", branch)
        assert not result["valid"]
        assert "mismatch" in result["message"].lower()

    def test_monitor_failed_wrong_phase(self, workspace, branch):
        """monitor_failed from non-MONITOR phase should error."""
        del workspace
        map_orchestrator.initialize_workflow("Add auth", branch)
        result = map_orchestrator.monitor_failed(branch, "some feedback")
        assert result["status"] == "error"
        assert "MONITOR" in result["message"]


# =====================================================================
# Ordering backward compatibility + round-trip (AC-14)
# =====================================================================


def _setup_review_bundle_prerequisites(workspace: Path, branch: str) -> None:
    """Populate workspace with minimal artifacts needed by create_review_bundle.

    Mirrors the minimal-fixture pattern from TestEfficientExecutionLifecycle but
    targets the map-review phase helpers.  All files use placeholder text so
    create_review_bundle() can inventory them without failing.
    """
    workspace.mkdir(parents=True, exist_ok=True)

    # Spec and task plan
    (workspace / f"spec_{branch}.md").write_text("# Spec\nMinimal spec.", encoding="utf-8")
    (workspace / f"task_plan_{branch}.md").write_text("# Plan\nMinimal plan.", encoding="utf-8")

    # Copy a real blueprint so dependency-graph helpers don't blow up
    shutil.copy2(FIXTURES_DIR / "blueprint.json", workspace / "blueprint.json")

    # Execution-phase artifacts
    (workspace / "verification-summary.md").write_text(
        "# Verification\nVERDICT: READY FOR REVIEW", encoding="utf-8"
    )
    (workspace / "qa-001.md").write_text("# QA\nAll checks passed.", encoding="utf-8")
    (workspace / "pr-draft.md").write_text(
        "# PR Draft\n\n## Summary\n- Auth added.\n\n## Validation\n- Tests pass.\n\n## Risks / Follow-up\n- None.\n",
        encoding="utf-8",
    )
    (workspace / "active-issues.json").write_text(
        '{"updated_at": "2026-01-01T00:00:00Z", "issues": []}', encoding="utf-8"
    )
    shutil.copy2(FIXTURES_DIR / "code_review.md", workspace / "code-review-001.md")

    # Artifact manifest (empty dict is acceptable; create_review_bundle merges into it)
    (workspace / "artifact_manifest.json").write_text("{}", encoding="utf-8")


class TestOrderingBackwardCompat:
    """AC-14(a) — legacy bundle without 'ordering' still loads (EC-7 defaults)."""

    def test_ordering_backward_compat(self, workspace, branch):
        """Legacy bundle (no ordering key) returns EC-7 safe defaults from build_review_handoff."""
        _setup_review_bundle_prerequisites(workspace, branch)

        # Step 1: produce a fresh bundle (ordering key will be present; we remove it to simulate legacy).
        result = map_step_runner.create_review_bundle(branch)
        assert result["status"] in ("success", "warn"), f"Bundle creation failed: {result}"

        bundle_json_path = workspace / "review-bundle.json"
        assert bundle_json_path.exists(), "review-bundle.json must exist after create_review_bundle"

        # Step 2: strip the 'ordering' key to simulate a legacy bundle from before ST-003.
        bundle_data = json.loads(bundle_json_path.read_text(encoding="utf-8"))
        bundle_data.pop("ordering", None)
        bundle_json_path.write_text(json.dumps(bundle_data, indent=2), encoding="utf-8")
        assert "ordering" not in bundle_data, "Ordering key must be absent for this test"

        # Step 3: call build_review_handoff; it must not crash and must return EC-7 defaults.
        handoff = map_step_runner.build_review_handoff(branch)

        assert handoff["review_order_mode"] == "default"
        assert handoff["review_order_seed"] is None
        assert handoff["drift_detected"] is False
        assert handoff["compare_status"] is None


class TestOrderingRoundtrip:
    """AC-14(b) — write bundle WITH ordering -> reload -> handoff matches -> schema clean."""

    def test_ordering_roundtrip(self, workspace, branch, monkeypatch):
        """Staged ordering round-trips through create_review_bundle -> review-bundle.json -> build_review_handoff."""
        _setup_review_bundle_prerequisites(workspace, branch)

        # Stage a non-default ordering payload (simulates what record_review_ordering would set).
        staged_ordering: dict = {
            "mode": "compare-orderings",
            "seed": 42,
            "runs": [
                {
                    "run_id": "run-1",
                    "section_order": ["architecture", "code_quality", "tests", "performance"],
                    "verdict": "REVISE",
                    "primary_issues": ["AUTH-01", "AUTH-02"],
                },
                {
                    "run_id": "run-2",
                    "section_order": ["performance", "tests", "code_quality", "architecture"],
                    "verdict": "BLOCK",
                    "primary_issues": ["AUTH-01", "AUTH-03"],
                },
            ],
            "drift_detected": True,
            "drift_summary": "Verdict changed REVISE->BLOCK across orderings.",
            "final_verdict": "BLOCK",
            "compare_status": "complete",
        }
        monkeypatch.setattr(map_step_runner, "_PENDING_REVIEW_ORDERING", staged_ordering)

        # create_review_bundle consumes _PENDING_REVIEW_ORDERING (clears it after read).
        result = map_step_runner.create_review_bundle(branch)
        assert result["status"] in ("success", "warn"), f"Bundle creation failed: {result}"

        # AC-14(b)-1: bundle result dict has ordering key with staged values.
        assert "ordering" in result, "result must contain 'ordering' key"
        assert result["ordering"]["mode"] == "compare-orderings"
        assert result["ordering"]["seed"] == 42
        assert result["ordering"]["drift_detected"] is True

        # AC-14(b)-2: review-bundle.json on disk contains the ordering object.
        bundle_json_path = workspace / "review-bundle.json"
        bundle_on_disk = json.loads(bundle_json_path.read_text(encoding="utf-8"))
        assert "ordering" in bundle_on_disk, "review-bundle.json must persist ordering key"
        disk_ordering = bundle_on_disk["ordering"]
        assert disk_ordering["mode"] == "compare-orderings"
        assert disk_ordering["seed"] == 42
        assert disk_ordering["drift_detected"] is True
        assert disk_ordering["compare_status"] == "complete"

        # AC-14(b)-3: build_review_handoff reads from the on-disk bundle and surfaces the 4 fields.
        handoff = map_step_runner.build_review_handoff(branch)
        assert handoff["review_order_mode"] == "compare-orderings"
        assert handoff["review_order_seed"] == 42
        assert handoff["drift_detected"] is True
        assert handoff["compare_status"] == "complete"

        # AC-14(b)-4: no schema validation error means schema accepted the new format.
        assert result.get("schema_validation_error") is None, (
            f"Schema rejected the ordering object: {result.get('schema_validation_error')}"
        )

        # AC-14(b)-5: missing prior-stage diff/test inputs warn without breaking ordering.
        manifest_status = result.get("manifest_status", {})
        assert manifest_status.get("status") == "warn", (
            f"Manifest stage must surface missing prior-stage inputs; got: {manifest_status}"
        )


class TestPrDraftUnaffectedByOrdering:
    """AC-14(c) + AC-13 OOS — pr-draft.md content is unchanged by ordering metadata."""

    def test_pr_draft_unaffected_by_ordering(self, workspace, branch, monkeypatch):
        """PR draft content is byte-identical with and without an ordering payload."""
        _setup_review_bundle_prerequisites(workspace, branch)

        # Path 1: build pr-draft WITHOUT staged ordering.
        # Ensure ordering state is clean (no pending payload).
        monkeypatch.setattr(map_step_runner, "_PENDING_REVIEW_ORDERING", None)

        pr_result_1 = map_step_runner.write_pr_draft(
            summary="Auth feature added.",
            validation="All tests pass.",
            risks_follow_up="Monitor rate-limit edge cases.",
            branch=branch,
        )
        assert pr_result_1["status"] == "success"
        content_without_ordering = Path(pr_result_1["path"]).read_text(encoding="utf-8")

        # Path 2: stage a non-default ordering, then build pr-draft again.
        staged_ordering_2: dict = {
            "mode": "shuffle-sections",
            "seed": 99,
            "runs": [],
            "drift_detected": False,
            "drift_summary": None,
            "final_verdict": "PROCEED",
            "compare_status": None,
        }
        monkeypatch.setattr(map_step_runner, "_PENDING_REVIEW_ORDERING", staged_ordering_2)

        pr_result_2 = map_step_runner.write_pr_draft(
            summary="Auth feature added.",
            validation="All tests pass.",
            risks_follow_up="Monitor rate-limit edge cases.",
            branch=branch,
        )
        assert pr_result_2["status"] == "success"
        content_with_ordering = Path(pr_result_2["path"]).read_text(encoding="utf-8")

        # Assert: pr-draft content is byte-identical regardless of ordering state.
        assert content_without_ordering == content_with_ordering, (
            "pr-draft.md must be identical with and without ordering payload.\n"
            f"Without: {content_without_ordering!r}\n"
            f"With:    {content_with_ordering!r}"
        )

        # AC-13 OOS: build_handoff_bundle output must NOT contain ordering-specific keys.
        handoff_bundle = map_step_runner.build_handoff_bundle(branch)
        assert "review_order_mode" not in handoff_bundle, (
            "build_handoff_bundle must NOT surface review_order_mode (AC-13 OOS)"
        )
        assert "drift_detected" not in handoff_bundle, (
            "build_handoff_bundle must NOT surface drift_detected (AC-13 OOS)"
        )
