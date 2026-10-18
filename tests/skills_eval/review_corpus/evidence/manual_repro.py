"""UNEXECUTED historical probes, for explicit manual review/authorization only.

Usage: python3 manual_repro.py /absolute/path/to/source/repository
Runs pinned public runner CLIs in disposable fixtures, never historical hooks or
models. Source Git operations are read-only; Git mutations affect fixtures only.
Printed observations are not admission evidence until independently inspected.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_ROOT = "src/mapify_cli/templates/map/scripts/"
REVISIONS = {
    "retained_worktree": {
        "base": "8a01f713d2b3239e845c91c4d1811b3f34d227a0",
        "head": "89303b798a7a54e82c3069a388100c847ba3f2cd",
        "fix": "206de516f1a144940dbf8e699ecedefddb3d3d48",
    },
    "health_help": {
        "base": "4ec2235bfa46a1a8c3521c819f4804269c9726ce",
        "head": "ec9d4b31e7cff67be781e841034a2098f21c6192",
        "fix": "de241e279805c18afaf017fbcdaa5cee8cd390f9",
    },
}


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo, text=True, timeout=30,
    ).strip()


def extract_scripts(source: Path, revision: str, destination: Path) -> Path:
    """Copy only regular Python runner/helper blobs; do not checkout a history."""
    entries = git(source, "ls-tree", "-r", revision, SCRIPT_ROOT).splitlines()
    for entry in entries:
        metadata, path = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        if mode not in {"100644", "100755"} or kind != "blob" or not path.endswith(".py"):
            continue
        relative = Path(path).relative_to(SCRIPT_ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(
            ["git", "cat-file", "blob", blob], cwd=source, timeout=30,
        ))
    return destination / "map_step_runner.py"


def invoke(runner: Path, fixture: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({
        "CLAUDE_PROJECT_DIR": str(fixture), "GIT_OPTIONAL_LOCKS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    # Avoid carrying parent-session repository/workflow overrides into fixtures.
    for key in list(environment):
        if key.startswith("MAP_") or key in {"GIT_DIR", "GIT_WORK_TREE", "PYTHONPATH"}:
            environment.pop(key)
    return subprocess.run(
        [sys.executable, "-B", str(runner), *args], cwd=fixture,
        env=environment, capture_output=True, text=True, timeout=60, check=False,
    )


def observe(source: Path, scenario: str, revision: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="corpus-manual-") as temporary:
        root = Path(temporary)
        runner = extract_scripts(source, revision, root / "scripts")
        fixture = root / "fixture"
        fixture.mkdir()
        if scenario == "health_help":
            result = invoke(runner, fixture, "write_run_health_report", "--help")
            return {
                "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
                "created_files": sorted(str(p.relative_to(fixture)) for p in fixture.rglob("*")
                                        if p.is_file()),
                "boundary": "Base predates command: unknown-command is not a fixed help response.",
            }
        git(fixture, "init", "-b", "corpus-probe")
        git(fixture, "config", "user.name", "Corpus fixture")
        git(fixture, "config", "user.email", "fixture@example.invalid")
        git(fixture, "config", "core.hooksPath", "/dev/null")
        (fixture / ".gitignore").write_text(".map/\n")
        (fixture / "target.py").write_text("original = True\n")
        git(fixture, "add", ".")
        git(fixture, "-c", "commit.gpgsign=false", "commit", "-m", "fixture seed")
        workspace = fixture / ".map/corpus-probe"
        workspace.mkdir(parents=True)
        (workspace / "step_state.json").write_text('{"subtask_results": {}}')
        config = fixture / ".map/config.yaml"
        config.write_text("worktree.isolation: auto\n")
        baseline = invoke(runner, fixture, "record_subtask_baseline", "corpus-probe", "ST-002")
        if baseline.returncode != 0:
            raise RuntimeError(f"Baseline failed: {baseline.stdout} {baseline.stderr}")
        retained = root / "retained"
        git(fixture, "worktree", "add", "--detach", str(retained), "HEAD")
        (workspace / "worktrees.json").write_text(json.dumps({"worktrees": {
            "ST-002": {"subtask_id": "ST-002", "path": str(retained),
                       "base_sha": git(fixture, "rev-parse", "HEAD"), "status": "created"},
        }}))
        config.write_text("worktree.isolation: off\nexecution.concurrent_dispatch: false\n")
        (fixture / "target.py").write_text("actor = True\n")
        result = invoke(runner, fixture, "detect_actor_files_changed_mismatch",
                        "corpus-probe", "ST-002", "--declared", "target.py")
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1]).resolve(strict=True)
    observations = {
        scenario: {role: {"revision": revision, "observation": observe(source, scenario, revision)}
                   for role, revision in versions.items()}
        for scenario, versions in REVISIONS.items()
    }
    print(json.dumps({"observations": observations, "admission": "requires manual adjudication"}, indent=2))


if __name__ == "__main__":
    main()
