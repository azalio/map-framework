"""Execute installed release safety blocks without git/network side effects."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapify_cli import app

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
OLD_SHA = "c" * 40
GOOD_RUN = {"status": "completed", "conclusion": "success", "headSha": BASE_SHA}
HEADINGS = ("### Gate 11:", "### 4.1 Pre-Push")


def bash_blocks(text: str, heading: str) -> list[str]:
    """Extract only bash fences in the named section, stopping at its next heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    blocks: list[str] = []
    current: list[str] | None = None
    for line in lines[start + 1 :]:
        if current is None:
            if re.match(r"^#{1,3} ", line):
                break
            if line == "```bash":
                current = []
        elif line == "```":
            blocks.append("\n".join(current))
            current = None
        else:
            current.append(line)
    assert blocks, f"no bash blocks under {heading}"
    return blocks


@pytest.fixture(scope="module", params=["claude", "codex"])
def installed_reference(request: pytest.FixtureRequest, tmp_path_factory) -> str:
    project = tmp_path_factory.mktemp(f"release_{request.param}")
    previous_cwd = Path.cwd()
    os.chdir(project)
    try:
        result = CliRunner().invoke(
            app,
            ["init", ".", "--provider", request.param, "--no-git", "--mcp", "none"],
        )
    finally:
        os.chdir(previous_cwd)
    assert result.exit_code == 0, result.output
    skill_root = ".claude/skills" if request.param == "claude" else ".agents/skills"
    reference = project / skill_root / "map-release/release-reference.md"
    return reference.read_text(encoding="utf-8")


# These executables refuse every unrecognised command; they never delegate to real git/gh.
FAKE_TOOLS = r'''
import json
import os
import sys
from pathlib import Path

name, args = Path(sys.argv[0]).name, sys.argv[1:]
case = json.loads(Path(os.environ["CASE_FILE"]).read_text())
with Path(os.environ["CALLS_FILE"]).open("a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "git":
    command = args[0]
    if command in ("fetch", "merge-base", "diff"):
        if case.get("git_failure") == command:
            print("simulated git failure", file=sys.stderr)
            sys.exit(9)
        print({"fetch": "", "merge-base": case["base"],
               "diff": case.get("files", "CHANGELOG.md\npyproject.toml\nsrc/mapify_cli/__init__.py")}[command])
    elif command == "branch":
        print("main")
    elif command == "rev-parse":
        print(case.get("tag_sha", case["head"]) if args[-1] != "HEAD" else case["head"])
    elif command == "rev-list":
        print(case.get("tag_sha", case["head"]))
    elif command == "tag":
        print("v1.2.0")
    elif command == "ls-remote":
        pass
    elif command == "push":
        print("fake push")
    else:
        sys.exit("unrecognised git command: " + repr(args))
elif name == "gh":
    if args[:2] == ["run", "list"]:
        if "--commit" in args:
            sha = args[args.index("--commit") + 1]
            if "release.yml" in args or "--workflow=release.yml" in args:
                payload = case.get("release_run", {"databaseId": 77, "status": "completed",
                              "conclusion": "success", "headSha": case["head"]})
            else:
                payload = case["run"] if sha == case["base"] else None
        else:
            payload = {"databaseId": 1, "status": "completed", "conclusion": "success",
                       "headSha": case["old"], "headBranch": "main"}
        if case.get("raw") is not None:
            print(case["raw"])
        else:
            selected = "--jq" in args and args[args.index("--jq") + 1] == ".[0]"
            print(json.dumps(payload if selected else ([] if payload is None else [payload])))
        sys.exit(case.get("gh_exit", 0))
    elif args[:2] == ["run", "watch"]:
        sys.exit(case.get("watch_exit", 0))
    elif args[:2] == ["run", "view"]:
        payload = case.get("release_final", {"status": "completed", "conclusion": "success",
                                             "headSha": case["head"]})
        print(case["raw_final"] if "raw_final" in case else json.dumps(payload))
        sys.exit(case.get("view_exit", 0))
    else:
        sys.exit("unrecognised gh command: " + repr(args))
else:
    sys.exit("unrecognised tool")
'''


def run_block(
    tmp_path: Path, block: str, overrides: dict | None = None, values: dict | None = None
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("git", "gh"):
        tool = bin_dir / name
        tool.write_text(f"#!{sys.executable}\n" + FAKE_TOOLS, encoding="utf-8")
        tool.chmod(0o755)
    jq = shutil.which("jq")
    assert jq is not None, "release safety tests require jq"
    if not (bin_dir / "jq").exists():
        (bin_dir / "jq").symlink_to(jq)
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "sleep").chmod(0o755)
    case = {"base": BASE_SHA, "head": HEAD_SHA, "old": OLD_SHA, "run": GOOD_RUN}
    case.update(overrides or {})
    case_file, calls_file = tmp_path / "case.json", tmp_path / "calls.jsonl"
    case_file.write_text(json.dumps(case), encoding="utf-8")
    package = tmp_path / "src/mapify_cli"
    package.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.0"\n', encoding="utf-8"
    )
    (package / "__init__.py").write_text('__version__ = "1.2.0"\n', encoding="utf-8")
    environment = {
        "PATH": f"{bin_dir}:{os.defpath}",
        "CASE_FILE": str(case_file),
        "CALLS_FILE": str(calls_file),
        **(values or {}),
    }
    result = subprocess.run(
        ["/bin/bash", "-c", block], cwd=tmp_path, env=environment,
        text=True, capture_output=True, check=False, timeout=10,
    )
    calls = (
        [json.loads(line) for line in calls_file.read_text().splitlines()]
        if calls_file.exists() else []
    )
    return result, calls


BAD_EVIDENCE = [
    pytest.param({"run": {**GOOD_RUN, "conclusion": "failure"}}, id="failed-target-old-green"),
    pytest.param({"run": None}, id="missing-target-old-green"),
    pytest.param({"run": {**GOOD_RUN, "status": "queued"}}, id="queued"),
    pytest.param({"run": {**GOOD_RUN, "status": "in_progress"}}, id="running"),
    pytest.param({"run": {**GOOD_RUN, "headSha": OLD_SHA}}, id="wrong-head"),
    pytest.param({"run": {"status": "completed", "conclusion": "success"}}, id="missing-head"),
    pytest.param({"run": {**GOOD_RUN, "headSha": None}}, id="null-head"),
    pytest.param({"run": {"headSha": BASE_SHA, "conclusion": "success"}}, id="missing-status"),
    pytest.param({"run": {"headSha": BASE_SHA, "status": "completed"}}, id="missing-conclusion"),
    pytest.param({"run": []}, id="wrong-shape"),
    pytest.param({"raw": "not-json"}, id="malformed"),
    pytest.param({"raw": ""}, id="empty"),
    pytest.param({"raw": json.dumps(GOOD_RUN) + "\nnull"}, id="multiple-json-values"),
    pytest.param({"gh_exit": 9}, id="api-failure-with-good-output"),
    pytest.param({"git_failure": "fetch"}, id="fetch-failure"),
    pytest.param({"git_failure": "merge-base"}, id="merge-base-failure"),
    pytest.param({"git_failure": "diff"}, id="diff-failure"),
    pytest.param({"base": ""}, id="empty-merge-base"),
    pytest.param({"files": "CHANGELOG.md\nsrc/mapify_cli/cli.py"}, id="unverified-code"),
    pytest.param({"files": "README.md"}, id="unverified-docs"),
]


@pytest.mark.parametrize("heading", HEADINGS)
@pytest.mark.parametrize("case", BAD_EVIDENCE)
def test_ci_gate_rejects_unverified_evidence(
    installed_reference: str, tmp_path: Path, heading: str, case: dict
) -> None:
    result, _ = run_block(tmp_path, bash_blocks(installed_reference, heading)[0], case)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize("heading", HEADINGS)
@pytest.mark.parametrize("files", ["", "CHANGELOG.md\npyproject.toml\nsrc/mapify_cli/__init__.py"])
def test_ci_gate_accepts_only_exact_good_metadata(
    installed_reference: str, tmp_path: Path, heading: str, files: str
) -> None:
    result, calls = run_block(
        tmp_path, bash_blocks(installed_reference, heading)[0], {"files": files}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    queries = [call for call in calls if call[:3] == ["gh", "run", "list"]]
    assert len(queries) == 1
    assert "--branch" not in queries[0]
    assert queries[0][queries[0].index("--commit") + 1] == BASE_SHA
    assert queries[0][queries[0].index("--workflow") + 1] == "CI"
    assert ["git", "diff", "--name-only", BASE_SHA, "HEAD"] in calls
    assert not any(call[:3] == ["gh", "run", "view"] for call in calls)


@pytest.mark.parametrize("heading", ["### 3.3 Verify", "### 4.1 Pre-Push"])
@pytest.mark.parametrize("matching", [True, False])
def test_fresh_shell_selects_version_tag_and_checks_head(
    installed_reference: str, tmp_path: Path, heading: str, matching: bool
) -> None:
    result, calls = run_block(
        tmp_path, bash_blocks(installed_reference, heading)[0],
        {"tag_sha": HEAD_SHA if matching else OLD_SHA},
        {"LAST_TAG": "v999.0.0", "RUN_ID": "999"},
    )
    assert (result.returncode == 0) == matching, result.stdout + result.stderr
    assert ["git", "rev-parse", "v1.2.0^{commit}"] in calls
    assert not any(call[:2] == ["git", "tag"] for call in calls)


@pytest.mark.parametrize("values", [{}, {"BUMP_TYPE": "patch"}, {"NEW_VERSION": "1.2.0"}])
def test_version_execution_requires_explicit_approved_values(
    installed_reference: str, tmp_path: Path, values: dict
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "bump-version.sh"
    script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > bump-called\n', encoding="utf-8")
    script.chmod(0o755)
    result, _ = run_block(
        tmp_path, bash_blocks(installed_reference, "### 3.2 Execute")[0], values=values
    )
    assert result.returncode != 0
    assert not (tmp_path / "bump-called").exists()


@pytest.mark.parametrize("case", [
    {},
    {"release_run": None},
    {"release_run": {"databaseId": 77, "headSha": OLD_SHA}},
    {"release_run": {"headSha": HEAD_SHA}},
    {"gh_exit": 9},
    {"raw": "not-json"},
    {"watch_exit": 9},
    {"view_exit": 9},
    {"release_final": {"status": "completed", "conclusion": "success", "headSha": OLD_SHA}},
    {"release_final": {"status": "in_progress", "conclusion": "success", "headSha": HEAD_SHA}},
])
def test_monitor_selects_exact_release_commit_in_fresh_shell(
    installed_reference: str, tmp_path: Path, case: dict
) -> None:
    result, calls = run_block(
        tmp_path, bash_blocks(installed_reference, "## Phase 5:")[0], case,
        {"RUN_ID": "999", "LAST_TAG": "v999.0.0"},
    )
    assert (result.returncode == 0) == (case == {}), result.stdout + result.stderr
    queries = [call for call in calls if call[:3] == ["gh", "run", "list"]]
    assert queries
    for query in queries:
        assert query[query.index("--commit") + 1] == HEAD_SHA
        assert query[query.index("--workflow") + 1] == "release.yml"
    if case == {}:
        assert ["gh", "run", "watch", "77", "--exit-status"] in calls


@pytest.mark.parametrize("case", [
    pytest.param(
        {"raw": json.dumps({"databaseId": 77, "headSha": HEAD_SHA}) + "\nnull"},
        id="run-query-good-then-null",
    ),
    pytest.param(
        {"raw_final": json.dumps({"status": "completed", "conclusion": "failure",
                                  "headSha": HEAD_SHA}) + "\n" +
         json.dumps({"status": "completed", "conclusion": "success", "headSha": HEAD_SHA})},
        id="final-failure-then-success",
    ),
])
def test_monitor_rejects_multiple_json_documents(
    installed_reference: str, tmp_path: Path, case: dict
) -> None:
    result, calls = run_block(
        tmp_path, bash_blocks(installed_reference, "## Phase 5:")[0], case
    )
    assert result.returncode != 0, result.stdout + result.stderr
    if "raw" in case:
        assert not any(call[:3] == ["gh", "run", "watch"] for call in calls)
