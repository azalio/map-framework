"""
Validation tests for the wave_blueprints fixture module (ST-004).

VC1: Every fixture constructs without error and exposes required fields.
VC2: Fixture module source contains no TODO/FIXME/... placeholders.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.wave_blueprints import (
    BlueprintFixture,
    SubtaskSpec,
    conflict_split,
    dirty_repo,
    linear_chain,
    non_git_dir,
    shallow_clone,
    submodule_repo,
    two_wave_parallel,
)

_FIXTURE_SRC = Path(__file__).parent / "fixtures" / "wave_blueprints.py"


# ---------------------------------------------------------------------------
# — all fixtures loadable and expose documented fields
# ---------------------------------------------------------------------------


class TestAllFixturesLoadable:
    """VC1: Each fixture constructs without error and exposes the documented fields."""

    # --- blueprint-shape fixtures ---

    def _assert_blueprint_fields(self, fix: BlueprintFixture) -> None:
        assert isinstance(fix, BlueprintFixture)
        assert isinstance(fix.subtasks, list)
        assert len(fix.subtasks) >= 1
        assert isinstance(fix.affected_files_map, dict)
        for spec in fix.subtasks:
            assert isinstance(spec, SubtaskSpec)
            assert isinstance(spec.id, str) and spec.id
            assert isinstance(spec.dependencies, list)
            assert isinstance(spec.outputs, list)
            assert isinstance(spec.inputs, list)
            assert isinstance(spec.affected_files, set)

    def test_all_fixtures_loadable_linear_chain(self) -> None:
        fix = linear_chain()
        self._assert_blueprint_fields(fix)
        assert len(fix.subtasks) == 4, "linear_chain must have 4 subtasks"
        ids = [s.id for s in fix.subtasks]
        assert ids == ["ST-001", "ST-002", "ST-003", "ST-004"]
        # verify chain structure
        assert fix.subtasks[0].dependencies == []
        assert fix.subtasks[1].dependencies == ["ST-001"]
        assert fix.subtasks[2].dependencies == ["ST-002"]
        assert fix.subtasks[3].dependencies == ["ST-003"]

    def test_all_fixtures_loadable_two_wave_parallel(self) -> None:
        fix = two_wave_parallel()
        self._assert_blueprint_fields(fix)
        root = fix.subtasks[0]
        children = fix.subtasks[1:]
        assert root.dependencies == []
        for child in children:
            assert root.id in child.dependencies
        # verify disjoint affected_files among children
        child_file_sets = [c.affected_files for c in children]
        for i, a in enumerate(child_file_sets):
            for j, b in enumerate(child_file_sets):
                if i != j:
                    assert not (a & b), (
                        f"two_wave_parallel: children {i} and {j} share files — "
                        "wave must be truly parallel"
                    )

    def test_all_fixtures_loadable_conflict_split(self) -> None:
        fix = conflict_split()
        self._assert_blueprint_fields(fix)
        # must have at least one shared file among the parallel subtasks
        parallel_ids = [s.id for s in fix.subtasks if s.dependencies != []]
        all_files: list[set[str]] = [fix.affected_files_map[sid] for sid in parallel_ids]
        found_conflict = any(
            bool(all_files[i] & all_files[j])
            for i in range(len(all_files))
            for j in range(i + 1, len(all_files))
        )
        assert found_conflict, "conflict_split must have at least one shared file"

    def test_all_fixtures_loadable_build_graph(self) -> None:
        """build_graph() works for all three blueprint fixtures."""
        from mapify_cli.dependency_graph import DependencyGraph

        for factory in (linear_chain, two_wave_parallel, conflict_split):
            fix = factory()
            graph = fix.build_graph()
            assert isinstance(graph, DependencyGraph)
            assert graph.size() == len(fix.subtasks)

    # --- git-shape fixtures ---

    def test_all_fixtures_loadable_non_git_dir(self, tmp_path: Path) -> None:
        if shutil.which("git") is None:
            pytest.skip("git not available")
        repo = non_git_dir(tmp_path)
        assert repo.is_dir()
        # must NOT be a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, "non_git_dir must not be a git repository"

    def test_all_fixtures_loadable_shallow_clone(self, tmp_path: Path) -> None:
        repo = shallow_clone(tmp_path)
        assert repo.is_dir()
        # must be a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, "shallow_clone must be a valid git repo"
        # shallow marker file must exist
        shallow_file = repo / ".git" / "shallow"
        assert shallow_file.exists(), ".git/shallow marker must exist for shallow_clone"

    def test_all_fixtures_loadable_submodule_repo(self, tmp_path: Path) -> None:
        repo = submodule_repo(tmp_path)
        assert repo.is_dir()
        # .gitmodules must exist
        assert (repo / ".gitmodules").exists(), "submodule_repo must have .gitmodules"
        # git submodule status must succeed
        result = subprocess.run(
            ["git", "submodule", "status"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"git submodule status failed: {result.stderr}"

    def test_all_fixtures_loadable_dirty_repo(self, tmp_path: Path) -> None:
        repo = dirty_repo(tmp_path)
        assert repo.is_dir()
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout.strip(), (
            "dirty_repo must have uncommitted changes (git status --porcelain non-empty)"
        )


# ---------------------------------------------------------------------------
# — no placeholder TODO/FIXME/... values in the fixture module
# ---------------------------------------------------------------------------


class TestFixturesNoPlaceholders:
    """VC2: Fixture source has no TODO/FIXME/ellipsis placeholders."""

    def test_fixtures_no_placeholders(self) -> None:
        source = _FIXTURE_SRC.read_text()
        forbidden = ["TODO", "FIXME"]
        for token in forbidden:
            assert token not in source, (
                f"Placeholder '{token}' found in {_FIXTURE_SRC}; "
                "fixtures must not contain placeholder values"
            )

        # Check for bare ellipsis used as a body placeholder (not in docstrings)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and node.value.value is ...:
                raise AssertionError(
                    f"Bare ellipsis placeholder found at line {node.lineno} "
                    f"in {_FIXTURE_SRC}"
                )

    def test_fixtures_blueprint_affected_files_nonempty(self) -> None:
        """Blueprint fixtures' affected_files are non-empty for each subtask."""
        for factory in (linear_chain, two_wave_parallel, conflict_split):
            fix = factory()
            for spec in fix.subtasks:
                assert spec.affected_files, (
                    f"{factory.__name__}: subtask {spec.id} has empty affected_files; "
                    "lint and wave computations require at least one file"
                )

    def test_fixtures_affected_files_map_matches_subtasks(self) -> None:
        """affected_files_map keys match subtask ids for all blueprint fixtures."""
        for factory in (linear_chain, two_wave_parallel, conflict_split):
            fix = factory()
            spec_ids = {s.id for s in fix.subtasks}
            map_ids = set(fix.affected_files_map.keys())
            assert spec_ids == map_ids, (
                f"{factory.__name__}: affected_files_map keys {map_ids} "
                f"do not match subtask ids {spec_ids}"
            )
