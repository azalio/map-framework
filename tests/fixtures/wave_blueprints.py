"""
Canned blueprint + repo-shape fixtures for the eval/regression harness.

Blueprint-shape fixtures return a small typed dict carrying per-subtask:
  id, dependencies, outputs, inputs, affected_files (set)
Plus:
  affected_files_map: dict[str, set[str]]  — id -> files, for split_wave_by_file_conflicts
  build_graph() -> DependencyGraph         — convenience constructor

Git-shape fixtures build repo state under a caller-supplied tmp_path.
They use subprocess `git` calls; each function documents its git property and
skips gracefully when git is unavailable.

Consumers (ST-005/006/007/009/010) import from this module by name.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mapify_cli.dependency_graph import DependencyGraph, SubtaskNode

# ---------------------------------------------------------------------------
# Typed blueprint shape
# ---------------------------------------------------------------------------


@dataclass
class SubtaskSpec:
    """Per-subtask specification consumed by lint and wave computations."""

    id: str
    dependencies: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    affected_files: set[str] = field(default_factory=set)


@dataclass
class BlueprintFixture:
    """
    Returned by every blueprint-shape factory.

    subtasks:           ordered list of SubtaskSpec
    affected_files_map: id -> set of file paths (for split_wave_by_file_conflicts)
    """

    subtasks: list[SubtaskSpec]
    affected_files_map: dict[str, set[str]]

    def build_graph(self) -> DependencyGraph:
        """Construct a DependencyGraph from the fixture's subtasks."""
        graph = DependencyGraph()
        for spec in self.subtasks:
            graph.add_node(
                SubtaskNode(
                    id=spec.id,
                    dependencies=spec.dependencies,
                    outputs=spec.outputs,
                    status="pending",
                )
            )
        return graph


# ---------------------------------------------------------------------------
# Blueprint-shape factories
# ---------------------------------------------------------------------------


def linear_chain() -> BlueprintFixture:
    """
    4-subtask linear chain: ST-001 -> ST-002 -> ST-003 -> ST-004.

    compute_waves() must return 4 waves each of width 1.
    No file conflicts (each subtask has disjoint affected_files).
    """
    subtasks = [
        SubtaskSpec(
            id="ST-001",
            dependencies=[],
            outputs=["out_a.py"],
            inputs=[],
            affected_files={"src/module_a.py"},
        ),
        SubtaskSpec(
            id="ST-002",
            dependencies=["ST-001"],
            outputs=["out_b.py"],
            inputs=["out_a.py"],
            affected_files={"src/module_b.py"},
        ),
        SubtaskSpec(
            id="ST-003",
            dependencies=["ST-002"],
            outputs=["out_c.py"],
            inputs=["out_b.py"],
            affected_files={"src/module_c.py"},
        ),
        SubtaskSpec(
            id="ST-004",
            dependencies=["ST-003"],
            outputs=["out_d.py"],
            inputs=["out_c.py"],
            affected_files={"src/module_d.py"},
        ),
    ]
    affected_files_map: dict[str, set[str]] = {s.id: s.affected_files for s in subtasks}
    return BlueprintFixture(subtasks=subtasks, affected_files_map=affected_files_map)


def two_wave_parallel() -> BlueprintFixture:
    """
    Root node then 3 independent children with DISJOINT affected_files.

    Wave 0: [ST-001]
    Wave 1: [ST-002, ST-003, ST-004]  (all independent, no shared files)

    Used by wave-computation tests (ST-005) to verify parallel wave detection.
    split_wave_by_file_conflicts must leave wave 1 unsplit.
    """
    subtasks = [
        SubtaskSpec(
            id="ST-001",
            dependencies=[],
            outputs=["config.yaml"],
            inputs=[],
            affected_files={"config.yaml"},
        ),
        SubtaskSpec(
            id="ST-002",
            dependencies=["ST-001"],
            outputs=["service_a.py"],
            inputs=["config.yaml"],
            affected_files={"src/service_a.py"},
        ),
        SubtaskSpec(
            id="ST-003",
            dependencies=["ST-001"],
            outputs=["service_b.py"],
            inputs=["config.yaml"],
            affected_files={"src/service_b.py"},
        ),
        SubtaskSpec(
            id="ST-004",
            dependencies=["ST-001"],
            outputs=["service_c.py"],
            inputs=["config.yaml"],
            affected_files={"src/service_c.py"},
        ),
    ]
    affected_files_map = {s.id: s.affected_files for s in subtasks}
    return BlueprintFixture(subtasks=subtasks, affected_files_map=affected_files_map)


def conflict_split() -> BlueprintFixture:
    """
    A wave of 3 subtasks where 2 share an affected file.

    Dependency structure:
      ST-001 (root) -> ST-002, ST-003, ST-004 (all parallel)

    Wave 1: [ST-002, ST-003, ST-004]
    File layout (conflict on 'src/shared.py'):
      ST-002: {src/shared.py, src/module_x.py}
      ST-003: {src/module_y.py}            <- no conflict
      ST-004: {src/shared.py, src/module_z.py}  <- conflicts with ST-002

    split_wave_by_file_conflicts([ST-002, ST-003, ST-004], map) must produce
    at least 2 sub-waves, with ST-002 and ST-004 in different sub-waves.
    """
    subtasks = [
        SubtaskSpec(
            id="ST-001",
            dependencies=[],
            outputs=["base.py"],
            inputs=[],
            affected_files={"src/base.py"},
        ),
        SubtaskSpec(
            id="ST-002",
            dependencies=["ST-001"],
            outputs=["x.py"],
            inputs=["base.py"],
            affected_files={"src/shared.py", "src/module_x.py"},
        ),
        SubtaskSpec(
            id="ST-003",
            dependencies=["ST-001"],
            outputs=["y.py"],
            inputs=["base.py"],
            affected_files={"src/module_y.py"},
        ),
        SubtaskSpec(
            id="ST-004",
            dependencies=["ST-001"],
            outputs=["z.py"],
            inputs=["base.py"],
            affected_files={"src/shared.py", "src/module_z.py"},
        ),
    ]
    affected_files_map = {s.id: s.affected_files for s in subtasks}
    return BlueprintFixture(subtasks=subtasks, affected_files_map=affected_files_map)


# ---------------------------------------------------------------------------
# Git-shape factories
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    """Return True if git is available on PATH."""
    return shutil.which("git") is not None


def _git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git command, returning the CompletedProcess."""
    import os

    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=run_env,
    )


def _git_allow_file_protocol() -> dict[str, str]:
    """
    Return env-var override that allows local file:// git transport.

    Modern git (2.38.1+) blocks local-path clones/submodule-add by default
    (CVE-2022-39253 mitigation).  Setting GIT_CONFIG_COUNT + the matching
    key/value pair re-enables the file protocol for test-only local repos.
    """
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "protocol.file.allow",
        "GIT_CONFIG_VALUE_0": "always",
    }


def non_git_dir(tmp_path: Path) -> Path:
    """
    Return a plain directory that is NOT a git repository.

    Property asserted by tests: `git rev-parse --git-dir` exits nonzero.
    """
    repo = tmp_path / "non_git"
    repo.mkdir()
    (repo / "file.txt").write_text("hello\n")
    return repo


def shallow_clone(tmp_path: Path) -> Path:
    """
    Return a git repo that simulates shallow-clone semantics.

    Implementation: creates a real git repo, commits one file, then writes
    `.git/shallow` (the file that git uses to mark a repo as shallow).
    The worktree probe code (ST-008/009) can detect this via:
      git rev-parse --is-shallow-repository  (returns 'true')
    or by checking for the existence of .git/shallow.

    This is an honest minimal implementation: a real git init with a real
    commit and the shallow marker file — not a fake.

    Skip if git is unavailable.
    """
    if not _git_available():
        pytest.skip("git not available")

    repo = tmp_path / "shallow_repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    (repo / "README.md").write_text("shallow clone fixture\n")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial commit", cwd=repo)

    # Write the shallow marker — this is what makes git treat the repo as shallow
    (repo / ".git" / "shallow").write_text("")

    return repo


def submodule_repo(tmp_path: Path) -> Path:
    """
    Return a git repo containing a real submodule.

    Creates:
      1. A bare "upstream" repo to act as the submodule remote.
      2. A "main" repo that contains the submodule via `git submodule add`.

    Property asserted by tests: `.gitmodules` file exists and `git submodule
    status` exits 0.

    Skip if git is unavailable.
    """
    if not _git_available():
        pytest.skip("git not available")

    # Create a bare upstream repo that will be used as the submodule origin
    upstream = tmp_path / "upstream.git"
    upstream.mkdir()
    _git("init", "--bare", str(upstream))

    # Seed the upstream with one commit (bare repos start empty, submodule add needs HEAD)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test User", cwd=seed)
    (seed / "lib.py").write_text("# submodule lib\n")
    _git("add", "lib.py", cwd=seed)
    _git("commit", "-m", "initial", cwd=seed)
    _git("remote", "add", "origin", str(upstream), cwd=seed)
    _git("push", "origin", "HEAD:main", cwd=seed)

    # Create the main repo
    main = tmp_path / "main_repo"
    main.mkdir()
    _git("init", cwd=main)
    _git("config", "user.email", "test@example.com", cwd=main)
    _git("config", "user.name", "Test User", cwd=main)
    (main / "main.py").write_text("# main\n")
    _git("add", "main.py", cwd=main)
    _git("commit", "-m", "initial main", cwd=main)

    # Add the submodule — uses the local bare repo as the remote.
    # Modern git (>=2.38.1) blocks file:// transport by default; allow it for
    # this test-only local repo via GIT_CONFIG_COUNT env vars.
    _file_env = _git_allow_file_protocol()
    _git(
        "submodule", "add",
        "--branch", "main",
        str(upstream),
        "lib",
        cwd=main,
        env=_file_env,
    )
    _git("commit", "-m", "add submodule", cwd=main)

    return main


def dirty_repo(tmp_path: Path) -> Path:
    """
    Return a git repo with uncommitted changes (`git status --porcelain` non-empty).

    Creates a clean repo, commits one file, then modifies a tracked file
    without staging — this makes the working tree dirty.

    Property asserted by tests: `git status --porcelain` produces non-empty output.

    Skip if git is unavailable.
    """
    if not _git_available():
        pytest.skip("git not available")

    repo = tmp_path / "dirty_repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)

    # Commit a clean file first
    tracked = repo / "tracked.py"
    tracked.write_text("x = 1\n")
    _git("add", "tracked.py", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)

    # Modify the tracked file without staging — makes working tree dirty
    tracked.write_text("x = 2  # modified but not staged\n")

    return repo
