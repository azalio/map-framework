"""E2E test for validating CLI command correctness in agent templates.

This test ensures that agent templates use correct mapify CLI commands,
preventing common mistakes like:
- Wrong operation field ('op' instead of 'type')
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli import get_templates_dir


def _isolated_git_env(**extra: str) -> dict[str, str]:
    """Keep test Git operations inside their disposable checkout."""
    return {
        **{key: value for key, value in os.environ.items()
           if not key.startswith("GIT_")},
        **extra,
    }


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_monitor_reports_missing_runtime_in_linked_worktree(provider, tmp_path, monkeypatch):
    """Ignored MAP state must not become a false code-review failure."""
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "wrong-checkout"))
    templates = get_templates_dir()
    primary = tmp_path / "primary"
    primary.mkdir()
    git_env = _isolated_git_env()
    subprocess.run(["git", "init", "-q"], cwd=primary, env=git_env, check=True)
    (primary / ".gitignore").write_text(".map/\n")
    (primary / "source.py").write_text("value = 1\n")
    subprocess.run(
        ["git", "add", ".gitignore", "source.py"],
        cwd=primary, env=git_env, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "commit", "-qm", "base"], cwd=primary, env=git_env, check=True,
    )
    workspace = primary / ".map" / "actor"
    workspace.mkdir(parents=True)
    (workspace / "blueprint.json").write_text(json.dumps({
        "subtasks": [{"id": "ST-001", "affected_files": ["source.py"]}],
    }))
    worktree = tmp_path / "worker"
    subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(worktree)],
        cwd=primary, env=git_env, check=True,
    )
    (worktree / "source.py").write_text("value = 2\n")
    assert not (worktree / ".map/scripts/map_step_runner.py").exists()
    assert not (worktree / ".map/actor/blueprint.json").exists()
    missing = subprocess.run(
        [sys.executable, ".map/scripts/map_step_runner.py",
         "validate_mutation_boundary", "actor", "ST-001"],
        cwd=worktree, env=git_env, capture_output=True, text=True, check=False,
    )
    assert missing.returncode != 0
    assert "map_step_runner.py" in missing.stderr

    if provider == "claude":
        contract = (templates / "agents/monitor.md").read_text()
    else:
        contract = tomllib.loads(
            (templates / "codex/agents/monitor.toml").read_text()
        )["developer_instructions"]
    assert "Actor runtime preflight in linked worktrees" in contract
    assert "MAP runtime unavailable in this worktree" in contract
    assert 'recommendation: "block"' in contract
    assert "continue any independent" in contract
    assert "skip the two runner-dependent Actor gates" in contract
    assert "name both the reviewed checkout and the different" in contract
    assert "no mutation-boundary or cross-subtask gate" in contract
    assert "copy (do not symlink)" in contract
    assert "A standalone" in contract
    assert (
        '(cd "$(git rev-parse --show-toplevel)" && python3 '
        '.map/scripts/map_step_runner.py validate_mutation_boundary <branch> <subtask_id>)'
    ) in contract
    if provider == "claude":
        assert (
            '(cd "$(git rev-parse --show-toplevel)" && python3 '
            '.map/scripts/map_step_runner.py detect_cross_subtask_regression_risk '
            '<branch> <subtask_id>)'
        ) in contract

    # A checkout-local runtime and blueprint let the real gate inspect the
    # worker diff. Using the initialized checkout as project root would miss it.
    worker_scripts = worktree / ".map" / "scripts"
    worker_scripts.mkdir(parents=True)
    for name in ("map_step_runner.py", "map_utils.py"):
        (worker_scripts / name).write_bytes((templates / "map/scripts" / name).read_bytes())
    worker_workspace = worktree / ".map" / "actor"
    worker_workspace.mkdir(parents=True)
    (worker_workspace / "blueprint.json").write_bytes(
        (workspace / "blueprint.json").read_bytes()
    )
    result = subprocess.run(
        [sys.executable, str(worker_scripts / "map_step_runner.py"),
         "validate_mutation_boundary", "actor", "ST-001"],
        cwd=worktree,
        env={**git_env, "CLAUDE_PROJECT_DIR": str(worktree)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["actual"] == ["source.py"]

    nested = worktree / "nested"
    nested.mkdir()
    nested_env = {**git_env, "PATH": str(Path(sys.executable).parent)
                  + os.pathsep + git_env.get("PATH", "")}
    nested_env.pop("CLAUDE_PROJECT_DIR", None)
    nested_gate = subprocess.run(
        ["sh", "-c", ('(cd "$(git rev-parse --show-toplevel)" && '
         ' python3 .map/scripts/map_step_runner.py '
         'validate_mutation_boundary actor ST-001)')],
        cwd=nested, env=nested_env, capture_output=True, text=True, check=False,
    )
    assert nested_gate.returncode == 0, nested_gate.stderr
    assert json.loads(nested_gate.stdout)["actual"] == ["source.py"]
    if provider == "claude":
        nested_risk = subprocess.run(
            ["sh", "-c", ('(cd "$(git rev-parse --show-toplevel)" && '
             ' python3 .map/scripts/map_step_runner.py '
             'detect_cross_subtask_regression_risk actor ST-001)')],
            cwd=nested, env=nested_env,
            capture_output=True, text=True, check=False,
        )
        assert nested_risk.returncode == 0, nested_risk.stderr
        assert json.loads(nested_risk.stdout)["subtask_id"] == "ST-001"


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_standalone_review_does_not_require_actor_blueprint(provider, tmp_path):
    """Real review CLI works without Actor state; routed Monitor agrees."""
    templates = get_templates_dir()
    runner = templates / "map/scripts/map_step_runner.py"
    env = _isolated_git_env(CLAUDE_PROJECT_DIR=str(tmp_path))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    source = tmp_path / "external.py"
    source.write_text("def divide(x):\n    return 1 / x\n")
    subprocess.run(["git", "add", "external.py"], cwd=tmp_path, env=env, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "commit", "-qm", "external base"], cwd=tmp_path, env=env, check=True,
    )
    source.write_text("def divide(x):\n    return 1 / 0\n")
    result = subprocess.run(
        [sys.executable, str(runner), "build_review_prompts", "--branch", "external"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    prompt = json.loads(result.stdout)["prompts"]["monitor"]["prompt"]
    assert "Review code correctness" in prompt
    assert "+    return 1 / 0" in prompt
    assert not (tmp_path / ".map/external/blueprint.json").exists()
    if provider == "claude":
        contract = (templates / "agents/monitor.md").read_text()
    else:
        contract = tomllib.loads(
            (templates / "codex/agents/monitor.toml").read_text()
        )["developer_instructions"]
    assert "Standalone /map-review" in contract
    assert "Do not require an Actor AAG contract, blueprint, or subtask ID" in contract
    assert "Never infer standalone review from a missing blueprint" in contract
    assert "validate_mutation_boundary <branch> <subtask_id>" in contract
    assert 'status="error"' in contract
    assert 'status="violation"' in contract


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("case", ["clean", "missing_blueprint", "unknown_subtask", "violation"])
def test_actor_review_boundary_remains_enforced(provider, case, tmp_path):
    """A standalone review exception never changes the actual Actor CLI gate."""
    templates = get_templates_dir()
    env = _isolated_git_env(CLAUDE_PROJECT_DIR=str(tmp_path), MAP_STRICT_SCOPE="1")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    workspace = tmp_path / ".map/actor"
    workspace.mkdir(parents=True)
    if case != "missing_blueprint":
        (workspace / "blueprint.json").write_text(json.dumps({
            "subtasks": [{"id": "ST-001", "affected_files": ["allowed.py"]}],
        }))
    (tmp_path / "allowed.py").write_text("x = 1\n")
    if case == "violation":
        (tmp_path / "unexpected.py").write_text("x = 2\n")
    # Workflow artifacts must not count as application mutations.
    (tmp_path / ".gitignore").write_text(".map/\n.gitignore\n")
    before = {p.name: p.read_bytes() for p in workspace.iterdir()}
    result = subprocess.run(
        [sys.executable, str(templates / "map/scripts/map_step_runner.py"),
         "validate_mutation_boundary", "actor",
         "ST-999" if case == "unknown_subtask" else "ST-001"],
        cwd=tmp_path,
        env=env,
        capture_output=True, text=True, check=False,
    )
    report = json.loads(result.stdout)
    expected = {"clean": "clean", "missing_blueprint": "error",
                "unknown_subtask": "error", "violation": "violation"}[case]
    assert report["status"] == expected, (provider, report)
    assert (result.returncode == 0) == (case == "clean"), report
    for name, content in before.items():
        assert (workspace / name).read_bytes() == content


class TestAgentCLICorrectness:
    """Test that agent templates use correct CLI commands."""

    @pytest.fixture
    def agent_files(self):
        """Get all agent template files."""
        templates_dir = get_templates_dir()
        agents_dir = templates_dir / "agents"

        # Get all .md files except documentation
        agent_files = [
            f
            for f in agents_dir.glob("*.md")
            if f.name not in ["README.md", "CHANGELOG.md", "MCP-PATTERNS.md"]
        ]

        return agent_files

    def test_no_wrong_operation_field(self, agent_files):
        """Test that agents use 'type' field instead of 'op' in delta operations."""
        errors = []

        for agent_file in agent_files:
            content = agent_file.read_text()

            # Check for "op": "ADD/UPDATE/DEPRECATE" pattern
            if re.search(r'"op":\s*"(ADD|UPDATE|DEPRECATE)"', content):
                matches = re.finditer(r'"op":\s*"(ADD|UPDATE|DEPRECATE)"', content)
                for match in matches:
                    start = max(0, match.start() - 100)
                    end = min(len(content), match.end() + 100)
                    context = content[start:end]
                    # Allow if it's in error examples
                    if "❌" not in context and "**WRONG**" not in context:
                        errors.append(
                            f"{agent_file.name}: Using '\"op\":' field, should be '\"type\":' "
                            f"in delta operations"
                        )
                        break

        assert not errors, "\n".join(errors)

    def test_agents_have_cli_reference(self, agent_files):
        """Test that agents have CLI reference section."""
        warnings = []

        # Agents that should have CLI guidance
        cli_heavy_agents = ["actor.md", "reflector.md"]

        for agent_file in agent_files:
            if agent_file.name in cli_heavy_agents:
                content = agent_file.read_text()

                # Check if agent has CLI reference section
                has_cli_reference = "<mapify_cli_reference>" in content

                if not has_cli_reference:
                    warnings.append(
                        f"{agent_file.name}: No CLI reference found. "
                        f"Consider adding <mapify_cli_reference> section."
                    )

        # Warnings don't fail the test, but are printed
        if warnings:
            print("\nCLI Reference Warnings:")
            for warning in warnings:
                print(f"  - {warning}")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
