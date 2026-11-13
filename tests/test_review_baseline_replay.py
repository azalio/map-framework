"""Focused fail-closed tests for canonical exact-base replay primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def helper() -> dict[str, Any]:
    source = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates_src/_partials/review-baseline.py.jinja"
    namespace: dict[str, Any] = {
        "Path": Path, "Any": Any, "hashlib": hashlib, "subprocess": subprocess,
        "re": re, "os": os, "json": json,
    }
    exec(compile(source.read_text(), str(source), "exec"), namespace)  # noqa: S102 — canonical trusted partial
    return namespace


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repository"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("import os\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
                    "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / ".map").mkdir()
    return repo, base


def test_exact_tree_uses_admitted_commit_without_checkout(helper, repository):
    repo, base = repository
    (repo / "src/a.py").write_text("changed\n")
    hashes = helper["_review_baseline_materialize"](repo, base, repo / ".map/base")
    assert (repo / ".map/base/src/a.py").read_text() == "import os\n"
    assert (repo / "src/a.py").read_text() == "changed\n"
    assert hashes["src/a.py"] == hashlib.sha256(b"import os\n").hexdigest()
    assert not (repo / ".git/worktrees").exists()
    with pytest.raises(ValueError, match="fresh"):
        helper["_review_baseline_materialize"](repo, base, repo / ".map/base")


@pytest.mark.parametrize("base", ["HEAD", "main", "123abc", "a" * 39, "A" * 40])
def test_baseline_never_resolves_moving_refs(helper, repository, base):
    repo, _ = repository
    with pytest.raises(ValueError, match="full commit SHA"):
        helper["_review_baseline_materialize"](repo, base, repo / ".map/base")
    assert not (repo / ".map/base").exists()


@pytest.mark.parametrize("name,symlink", [(".env", False), (".ENV", False), ("private.key", False), ("link", True)])
def test_unsafe_tree_rejected_before_any_materialization(helper, repository, name, symlink):
    repo, _ = repository
    path = repo / name
    if symlink:
        path.symlink_to("../../escape")
    else:
        path.write_text("do not copy")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
                    "commit", "-qm", "unsafe"], cwd=repo, check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    with pytest.raises(ValueError, match="Unsupported"):
        helper["_review_baseline_materialize"](repo, base, repo / ".map/base")
    assert not (repo / ".map/base").exists()


def test_escaping_destination_parent_rejected(helper, repository, tmp_path):
    repo, base = repository
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".map/link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="fresh owned"):
        helper["_review_baseline_materialize"](repo, base, repo / ".map/link/base")
    assert not (outside / "base").exists()


def test_prepare_detects_config_untracked_and_input_changes(helper, repository):
    repo, base = repository
    prepare = helper["_review_baseline_prepare"]
    assert prepare(repo, base, ["make", "lint"])["status"] == "eligible"
    (repo / "src/a.py").write_text("new Python input\n")
    assert prepare(repo, base, ["make", "lint"])["status"] == "eligible"
    (repo / "pyproject.toml").write_text("[tool.ruff]\n")
    assert prepare(repo, base, ["make", "lint"])["status"] == "unknown"
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    (repo / "ignored.py").write_text("extra input\n")
    assert prepare(repo, base, ["make", "lint"])["status"] == "unknown"


RUFF = b"src/a.py:1:8: F401 `os` imported but unused\nFound 1 error.\n"
MYPY = b"src/a.py:1: error: Incompatible types  [assignment]\nFound 1 error in 1 file (checked 2 source files)\n"


def compare(helper, command, head, baseline, head_exit=1, base_exit=1):
    digest = {"src/a.py": "a" * 64}
    return helper["_review_baseline_compare"](command, head, baseline, head_exit, base_exit, digest, digest)


@pytest.mark.parametrize("command,output", [(["ruff", "check", "src/", "tests/"], RUFF), (["mypy", "src/"], MYPY)])
def test_exact_diagnostic_multiset_is_baseline_only(helper, command, output):
    assert compare(helper, command, output, output)["attribution"] == "baseline_only"
    changed = output.replace(b"unused", b"unused NEW").replace(b"Incompatible types", b"Different types")
    assert compare(helper, command, changed, output)["attribution"] == "new"


@pytest.mark.parametrize("output", [b"tool crashed\n", b"", RUFF + b"ERROR environment failure\n",
                                    RUFF.replace(b"Found 1", b"Found 2"), RUFF + b"[truncated]\n"])
def test_opaque_identical_failure_never_exempts(helper, output):
    assert compare(helper, ["ruff", "check", "src/", "tests/"], output, output)["attribution"] == "unknown"


def test_changed_file_diagnostic_has_no_proven_line_mapping(helper):
    result = helper["_review_baseline_compare"](["ruff", "check", "src/", "tests/"], RUFF, RUFF, 1, 1,
                                                {"src/a.py": "a" * 64}, {"src/a.py": "b" * 64})
    assert result["attribution"] == "unknown"


def test_duplicate_diagnostics_compare_as_multisets(helper):
    # Construct a valid duplicate transcript, not a count-only comparison.
    duplicate = b"\n".join([RUFF.splitlines()[0], RUFF.splitlines()[0], b"Found 2 errors.", b""])
    assert compare(helper, ["ruff", "check", "src/", "tests/"], duplicate, RUFF)["attribution"] == "new"


def test_make_first_failure_and_following_stage_failure(helper):
    ruff_failed = b"uv run --extra dev ruff check src/ tests/\n" + RUFF + b"make: *** [Makefile:54: lint] Error 1\n"
    assert compare(helper, ["make", "lint"], ruff_failed, ruff_failed, 2, 2)["attribution"] == "baseline_only"
    mypy_failed = (b"uv run --extra dev ruff check src/ tests/\nAll checks passed!\n"
                   b"uv run --extra dev mypy src/\n" + MYPY + b"make: *** [lint] Error 1\n")
    assert compare(helper, ["make", "lint"], mypy_failed, mypy_failed, 2, 2)["attribution"] == "baseline_only"
    assert compare(helper, ["make", "lint"], mypy_failed, ruff_failed, 2, 2)["attribution"] == "new"
    bad = ruff_failed + b"uv run --extra dev mypy src/\n"
    assert compare(helper, ["make", "lint"], bad, bad, 2, 2)["attribution"] == "unknown"


def test_witness_refuses_unproven_environment_and_scripts(helper, tmp_path):
    witness = helper["_review_baseline_witness"]
    assert witness(["make", "lint"])["status"] == "unknown"
    binary = tmp_path / "ruff"
    binary.write_text("#!/bin/sh\nexit 0\n")
    command = [str(binary), "check", "--isolated", "--no-respect-gitignore", "--no-cache",
               "--output-format", "concise", "src/", "tests/"]
    assert witness(command)["status"] == "unknown"


def test_native_isolated_ruff_can_replay_end_to_end(helper, repository, monkeypatch):
    repo, base = repository
    # The venv Ruff binary is native and outside this fixture's mutable tree.
    binary = Path(__file__).resolve().parents[1] / ".venv/bin/ruff"
    command = [str(binary), "check", "--isolated", "--no-respect-gitignore", "--no-cache",
               "--output-format", "concise", "src/", "tests/"]
    monkeypatch.chdir(repo)
    (repo / "tests").mkdir()
    witness = helper["_review_baseline_witness"](command)
    assert witness["status"] == "supported"
    prepared = helper["_review_baseline_prepare"](repo, base, command)
    assert prepared["status"] == "eligible"
    destination = repo / ".map/base"
    files = helper["_review_baseline_materialize"](repo, base, destination)
    (destination / "tests").mkdir()
    head = subprocess.run(command, cwd=repo, capture_output=True, check=False)
    baseline = subprocess.run(command, cwd=destination, capture_output=True, check=False)
    assert helper["_review_baseline_witness"](command) == witness
    result = helper["_review_baseline_compare"](command, head.stdout + head.stderr, baseline.stdout + baseline.stderr,
                                                head.returncode, baseline.returncode, prepared["head_files"], files)
    assert result["attribution"] == "baseline_only"
