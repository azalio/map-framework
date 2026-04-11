"""
Level 2 — E2E Tests with Claude SDK (real LLM)

Tests the full map-plan → map-efficient → map-review flow by actually running
Claude Code CLI against a minimal test project. These tests are:
- Expensive (real API calls)
- Non-deterministic (LLM output varies)
- Slow (minutes per test)

Run with: pytest tests/integration/test_e2e_claude_sdk.py -m slow
Skip in CI: pytest -m "not slow"

Each test creates a fresh temp directory with a tiny Python project,
runs `mapify init`, then exercises the MAP commands via `claude -p`.

Environment requirements:
- ANTHROPIC_API_KEY set (or claude CLI already authenticated)
- claude CLI available on PATH
- mapify CLI installed (pip install -e .)
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

# Skip all tests in this module if ANTHROPIC_API_KEY is not set
# or if claude CLI is not available
pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration,
]


def _claude_available() -> bool:
    """Check if claude CLI is available."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _mapify_available() -> bool:
    """Check if mapify CLI is available."""
    try:
        result = subprocess.run(
            ["mapify", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _api_key_available() -> bool:
    """Check if Anthropic API key is set or claude CLI is authenticated."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # Check if claude CLI is authenticated via `claude auth status`
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _e2e_ready() -> bool:
    """Check if all prerequisites for e2e tests are met."""
    return _claude_available() and _mapify_available() and _api_key_available()


SKIP_REASON = "claude CLI, mapify CLI, or API key/auth not available"


def _run_claude(prompt: str, cwd: str, timeout: int = 300, max_turns: int = 50) -> str:
    """Run claude -p with a prompt and return the output.

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory
        timeout: Timeout in seconds (default 5 minutes)
        max_turns: Maximum agent turns (default 50)

    Returns:
        Claude's text output
    """
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "text",
                "--max-turns",
                str(max_turns),
            ],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"claude CLI timed out after {timeout}s for prompt: {prompt[:80]}\n"
            f"Partial output: {partial[-1000:]}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout[:2000]}\n"
            f"stderr: {result.stderr[:2000]}"
        )
    return result.stdout


def _run_mapify_init(project_dir: str) -> None:
    """Run mapify init inside an existing project directory.

    Uses 'mapify init . --force' from within the project dir, because
    'mapify init <path>' expects the directory to NOT exist (it creates it).
    """
    result = subprocess.run(
        ["mapify", "init", ".", "--force", "--no-git"],
        capture_output=True,
        text=True,
        cwd=project_dir,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mapify init failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture
def test_project(tmp_path):
    """Create a minimal Python project for testing."""
    if not _e2e_ready():
        pytest.skip(SKIP_REASON)
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create a tiny project
    (project_dir / "app.py").write_text(
        textwrap.dedent(
            """\
        \"\"\"Simple calculator app for e2e testing.\"\"\"


        def add(a: int, b: int) -> int:
            return a + b


        def subtract(a: int, b: int) -> int:
            return a - b


        if __name__ == "__main__":
            print(f"2 + 3 = {add(2, 3)}")
        """
        ),
        encoding="utf-8",
    )

    (project_dir / "test_app.py").write_text(
        textwrap.dedent(
            """\
        from app import add, subtract


        def test_add():
            assert add(2, 3) == 5


        def test_subtract():
            assert subtract(5, 3) == 2
        """
        ),
        encoding="utf-8",
    )

    # Init git repo
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(
        ["git", "init"],
        cwd=str(project_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=str(project_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(project_dir),
        capture_output=True,
        check=True,
        env=git_env,
    )

    # Create feature branch
    subprocess.run(
        ["git", "checkout", "-b", "feat/add-multiply"],
        cwd=str(project_dir),
        capture_output=True,
        check=True,
    )

    # Install MAP framework
    _run_mapify_init(str(project_dir))

    return project_dir


def _get_branch_name(project_dir: Path) -> str:
    """Get the current git branch name, sanitized the same way MAP does.

    MAP replaces '/' with '-' in branch names for filesystem safety.
    e.g. 'feat/add-multiply' -> 'feat-add-multiply'
    """
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()
    # Sanitize: match map_utils.py get_branch_name() behavior
    return branch.replace("/", "-")


def _get_map_dir(project_dir: Path) -> Path:
    """Get the .map/<branch>/ directory."""
    branch = _get_branch_name(project_dir)
    return project_dir / ".map" / branch


# =====================================================================
# Test: map-plan produces valid artifacts
# =====================================================================


@pytest.mark.skipif(not _e2e_ready(), reason=SKIP_REASON)
class TestMapPlanE2E:
    """Test that /map-plan produces valid, parseable artifacts."""

    def test_plan_creates_required_artifacts(self, test_project):
        """Running /map-plan should produce spec, blueprint, task_plan, step_state."""
        output = _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        map_dir = _get_map_dir(test_project)
        branch = _get_branch_name(test_project)

        # Check required artifacts exist
        assert (map_dir / "blueprint.json").exists(), (
            f"blueprint.json not found in {map_dir}. " f"Claude output: {output[:500]}"
        )
        assert (map_dir / f"task_plan_{branch}.md").exists() or any(
            f.name.startswith("task_plan") for f in map_dir.glob("task_plan*.md")
        ), "task_plan not found"
        assert (map_dir / "step_state.json").exists(), "step_state.json not found"

    def test_plan_blueprint_is_valid_json(self, test_project):
        """Blueprint should be valid JSON with subtasks."""
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        map_dir = _get_map_dir(test_project)
        bp_file = map_dir / "blueprint.json"

        bp = json.loads(bp_file.read_text(encoding="utf-8"))

        # Support nested format
        if "blueprint" in bp and isinstance(bp["blueprint"], dict):
            subtasks = bp["blueprint"].get("subtasks", [])
        else:
            subtasks = bp.get("subtasks", [])

        assert len(subtasks) >= 1, "Blueprint should have at least one subtask"
        for st in subtasks:
            assert "id" in st, f"Subtask missing 'id': {st}"
            assert "dependencies" in st, f"Subtask missing 'dependencies': {st}"

    def test_plan_step_state_initialized(self, test_project):
        """step_state.json should be initialized at DECOMPOSE or later."""
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        map_dir = _get_map_dir(test_project)
        state = json.loads((map_dir / "step_state.json").read_text(encoding="utf-8"))

        assert state["workflow"] in (
            "map-plan",
            "map-efficient",
        ), f"Unexpected workflow value: {state['workflow']}"
        assert "subtask_sequence" in state
        assert isinstance(state["subtask_sequence"], list)


# =====================================================================
# Test: map-efficient executes the plan
# =====================================================================


@pytest.mark.skipif(not _e2e_ready(), reason=SKIP_REASON)
class TestMapEfficientE2E:
    """Test that /map-efficient executes the plan and produces code + review artifacts."""

    def test_efficient_produces_code_changes(self, test_project):
        """Running /map-efficient after /map-plan should produce actual code changes."""
        # Step 1: Plan
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        # Step 2: Execute
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        # Verify: code was modified
        app_content = (test_project / "app.py").read_text(encoding="utf-8")
        assert (
            "multiply" in app_content.lower()
        ), "Expected multiply function in app.py after execution"

    def test_efficient_creates_review_artifacts(self, test_project):
        """map-efficient should produce code-review and verification artifacts."""
        # Plan + Execute
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        map_dir = _get_map_dir(test_project)

        # Check for review artifacts (at least one code-review-NNN.md)
        reviews = list(map_dir.glob("code-review-*.md"))
        assert len(reviews) >= 1, (
            f"Expected at least one code-review artifact in {map_dir}. "
            f"Found: {[f.name for f in map_dir.iterdir()]}"
        )

    def test_efficient_tests_pass(self, test_project):
        """After execution, project tests should pass."""
        # Plan + Execute
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        # Run pytest on the test project — tests MUST pass (rc=0)
        result = subprocess.run(
            ["python3", "-m", "pytest", "-v"],
            cwd=str(test_project),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert (
            result.returncode == 0
        ), f"Project tests failed after map-efficient:\n{result.stdout[-2000:]}"

    def test_efficient_multiply_works(self, test_project):
        """The generated multiply function must actually compute correctly."""
        # Plan + Execute
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        # Directly invoke the generated code and verify correctness
        result = subprocess.run(
            [
                "python3",
                "-c",
                "from app import multiply; "
                "assert multiply(2, 2) == 4, f'2*2={multiply(2,2)}'; "
                "assert multiply(0, 5) == 0, f'0*5={multiply(0,5)}'; "
                "assert multiply(-3, 7) == -21, f'-3*7={multiply(-3,7)}'; "
                "print('multiply: all checks passed')",
            ],
            cwd=str(test_project),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"multiply() produced wrong results:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# =====================================================================
# Test: map-review analyzes changes
# =====================================================================


@pytest.mark.skipif(not _e2e_ready(), reason=SKIP_REASON)
class TestMapReviewE2E:
    """Test that /map-review produces a structured review verdict."""

    def test_review_ci_mode_produces_verdict(self, test_project):
        """map-review --ci should produce a verdict without interaction."""
        # Plan + Execute
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        # Review in CI mode
        output = _run_claude(
            "/map-review --ci",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        # Should mention a verdict
        output_lower = output.lower()
        assert any(
            verdict in output_lower
            for verdict in ["proceed", "revise", "block", "approved"]
        ), f"Expected verdict in review output, got: {output[:1000]}"

    def test_review_creates_review_artifact(self, test_project):
        """map-review should produce a numbered code-review artifact."""
        # Plan + Execute
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=600,
            max_turns=100,
        )

        map_dir = _get_map_dir(test_project)
        reviews_before = set(map_dir.glob("code-review-*.md"))
        # Capture modification times of existing review files
        mtimes_before = {r.name: r.stat().st_mtime for r in reviews_before}

        # Review
        review_output = _run_claude(
            "/map-review --ci",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )

        reviews_after = set(map_dir.glob("code-review-*.md"))
        new_reviews = reviews_after - reviews_before

        # map-review may create a new code-review-NNN.md OR update an
        # existing one, OR produce its verdict via pr-draft / active-issues.
        # Accept any evidence that the review actually ran.
        updated_existing = any(
            r.stat().st_mtime > mtimes_before.get(r.name, 0) for r in reviews_after
        )
        has_pr_draft = (map_dir / "pr-draft.md").exists()
        has_active_issues = (map_dir / "active-issues.json").exists()
        review_produced_output = any(
            v in review_output.lower()
            for v in ["proceed", "revise", "block", "approved"]
        )

        assert (
            len(new_reviews) >= 1
            or updated_existing
            or has_pr_draft
            or has_active_issues
            or review_produced_output
        ), (
            f"Expected map-review to produce review artifacts or verdict. "
            f"New reviews: {[r.name for r in new_reviews]}, "
            f"pr-draft exists: {has_pr_draft}, "
            f"active-issues exists: {has_active_issues}, "
            f"output verdict: {review_produced_output}"
        )


# =====================================================================
# Test: Full flow smoke test
# =====================================================================


@pytest.mark.skipif(not _e2e_ready(), reason=SKIP_REASON)
class TestFullFlowE2E:
    """Smoke test: run the entire plan → efficient → review flow."""

    def test_full_flow_plan_to_review(self, test_project):
        """The complete flow should produce valid code and a review verdict.

        This is the main e2e smoke test. It validates:
        1. /map-plan produces blueprint + step_state
        2. /map-efficient produces code changes + review artifacts
        3. /map-review produces a verdict

        Note: map-efficient can take 10+ minutes for complex tasks.
        """
        map_dir = _get_map_dir(test_project)

        # Phase 1: Plan
        _run_claude(
            "/map-plan Add a multiply(a, b) function to app.py with tests",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        assert (map_dir / "blueprint.json").exists(), "Plan failed: no blueprint"
        assert (map_dir / "step_state.json").exists(), "Plan failed: no step_state"

        # Phase 2: Execute (needs more time — multi-subtask with Actor/Monitor loops)
        _run_claude(
            "/map-efficient",
            cwd=str(test_project),
            timeout=900,
            max_turns=120,
        )
        app_content = (test_project / "app.py").read_text(encoding="utf-8")
        assert (
            "multiply" in app_content.lower()
        ), "Efficient failed: no multiply function"

        # Phase 3: Review
        review_output = _run_claude(
            "/map-review --ci",
            cwd=str(test_project),
            timeout=600,
            max_turns=80,
        )
        review_lower = review_output.lower()
        has_verdict = any(
            v in review_lower for v in ["proceed", "revise", "block", "approved"]
        )
        assert has_verdict, f"Review produced no verdict: {review_output[:500]}"

        # Verify artifacts chain is complete
        assert list(map_dir.glob("code-review-*.md")), "No code-review artifacts"
        assert (map_dir / "pr-draft.md").exists() or (
            map_dir / "qa-001.md"
        ).exists(), "Missing final artifacts"
