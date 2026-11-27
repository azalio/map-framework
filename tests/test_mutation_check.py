import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.load_tolerance import LOAD_DEADLINE

SCRIPTS = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts"
PROOF = "checks/test_value.py"
POINT = f"{PROOF}::test_accepts_positive"
SOURCE = "def accepts(value):\n    return value >= 1  # first positive integer\n"
WEAK_PROOF = (
    "from value import accepts\n\ndef test_accepts_positive():\n    assert accepts(3)\n"
)
BOUNDARY = {
    "path": "value.py",
    "before": "value >= 1",
    "after": "value > 1",
    "effect": "reject the first positive integer",
}
NO_OP = {
    "path": "value.py",
    "before": "value >= 1",
    "after": "False",
    "effect": "reject every input",
}


@pytest.fixture()
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    shutil.copytree(
        SCRIPTS, tmp_path / ".map/scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    (tmp_path / ".gitignore").write_text(".map/\n__pycache__/\n.pytest_cache/\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    (tmp_path / "value.py").write_text(SOURCE)
    (tmp_path / "checks").mkdir()
    (tmp_path / PROOF).write_text(WEAK_PROOF)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def cli(repo, *args, script="mutation_check.py"):
    result = subprocess.run(
        [sys.executable, f".map/scripts/{script}", *map(str, args)],
        cwd=repo,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        text=True,
        capture_output=True,
        timeout=LOAD_DEADLINE,
        check=False,
    )
    assert result.stdout.strip(), result.stderr
    return result.returncode, json.loads(result.stdout)


def check(repo, mutations, *options):
    path = repo / "plan.json"
    path.write_text(
        json.dumps({"criterion": "AC-1", "tests": [POINT], "mutations": mutations})
    )
    code, body = cli(repo, path, *options)
    assert body["status"] and "baseline" in body, body
    assert (repo / body["report"]).is_file()
    return code, body


def outcomes(body):
    return [row["outcome"] for row in body["mutations"]]


def assert_current(repo, report, expected):
    code, result = cli(repo, "--check-report", report)
    assert result["current"] is expected, result
    assert (code == 0) is expected


def test_independent_boundary_assertion_turns_survivor_into_detection(repo):
    code, weak = check(repo, [NO_OP, BOUNDARY])
    assert code != 0
    assert outcomes(weak) == ["detected", "survived"]
    assert_current(repo, weak["report"], True)
    proof = repo / PROOF
    assert proof.read_text() == WEAK_PROOF
    assert (repo / "value.py").read_text() == SOURCE

    proof.write_text(WEAK_PROOF + "    assert accepts(1)\n")
    assert_current(repo, weak["report"], False)
    code, strong = check(repo, [NO_OP, BOUNDARY])
    assert code == 0, strong
    assert outcomes(strong) == ["detected", "detected"]
    assert_current(repo, strong["report"], True)

    (repo / "value.py").write_text(SOURCE + "\n# clarified the domain\n")
    assert_current(repo, strong["report"], False)


def test_invalid_equivalent_and_setup_failures_give_no_detection(repo):
    (repo / PROOF).write_text(
        "import pytest\nfrom value import accepts\n\n"
        "@pytest.fixture(autouse=True)\ndef check_fixture():\n    assert not accepts(0)\n\n"
        "def test_accepts_positive():\n    assert accepts(3)\n"
    )
    variants = [
        {**BOUNDARY, "after": "value >="},
        {**BOUNDARY, "before": "# first positive integer", "after": "# threshold"},
        {
            **BOUNDARY,
            "before": "def accepts(value):",
            "after": "import missing_fixture_module\ndef accepts(value):",
        },
        {**BOUNDARY, "after": "value >= 0"},
    ]
    code, body = check(repo, variants, "--limit", len(variants))
    assert code != 0
    syntax, equivalent, collection, setup = outcomes(body)
    assert syntax == "invalid"
    assert equivalent == "equivalent"
    assert collection in {"invalid", "inconclusive"}
    assert setup in {"invalid", "inconclusive"}
    assert (repo / "value.py").read_text() == SOURCE


def test_timeout_is_inconclusive(repo):
    slow = {
        **BOUNDARY,
        "before": "    return",
        "after": "    import time\n    time.sleep(120)\n    return",
        "effect": "delay the result beyond the execution budget",
    }
    code, body = check(repo, [slow], "--timeout", 8, "--total-timeout", 45)
    assert code != 0
    assert outcomes(body) == ["inconclusive"]
    assert (repo / "value.py").read_text() == SOURCE


def test_failed_baseline_never_counts_as_detection(repo):
    (repo / PROOF).write_text(WEAK_PROOF + "    assert accepts(0)\n")
    code, body = check(repo, [NO_OP, BOUNDARY])
    assert code != 0
    assert outcomes(body) == ["not_run", "not_run"], body
    assert (repo / PROOF).read_text() == WEAK_PROOF + "    assert accepts(0)\n"


def test_limit_keeps_unrun_candidate_visible(repo):
    (repo / PROOF).write_text(
        WEAK_PROOF + "\n\ndef test_outside_criterion():\n    assert False\n"
    )
    code, body = check(repo, [NO_OP, BOUNDARY], "--limit", 1)
    assert code != 0
    assert outcomes(body) == ["detected", "not_run"]


def test_existing_frozen_acceptance_proof_is_preserved(repo):
    branch = repo / ".map/main"
    branch.mkdir()
    (branch / "spec_main.md").write_text(
        "# Spec\n<!-- mapify:requirements-index:v1 -->\n```yaml\nrequirements:\n"
        "  - id: AC-1\n    kind: acceptance_criterion\n"
        "```\n<!-- /mapify:requirements-index:v1 -->\n"
    )
    payload = {
        "ac_id": "AC-1",
        "command": [sys.executable, "-m", "pytest", "-q", POINT],
        "proof_files": [PROOF],
        "subtask_id": "ST-001",
        "author": "test-writer",
    }
    (repo / "plan.json").write_text(
        json.dumps({"criterion": "AC-1", "tests": [POINT], "mutations": [NO_OP]})
    )
    for operation, data in (
        ("freeze_acceptance_contract", payload),
        ("run_acceptance_proofs", {}),
    ):
        code, result = cli(
            repo, operation, "--json", json.dumps(data), script="map_step_runner.py"
        )
        assert code == 0 and result["status"] == "success", result
    protected = [repo / "value.py", repo / PROOF, branch / "acceptance-proofs.json"]
    original = [path.read_bytes() for path in protected]
    code, body = check(repo, [NO_OP])
    assert code == 0 and outcomes(body) == ["detected"], body
    assert [path.read_bytes() for path in protected] == original
    code, result = cli(
        repo, "evaluate_acceptance", "--json", "{}", script="map_step_runner.py"
    )
    assert code == 0 and result["requirements"][0]["status"] == "proven", result


@pytest.mark.parametrize(("selected", "mutations"), [([], [NO_OP]), ([POINT], [])])
def test_empty_selection_cannot_prove_adequacy(repo, selected, mutations):
    plan = repo / "plan.json"
    plan.write_text(
        json.dumps({"criterion": "AC-1", "tests": selected, "mutations": mutations})
    )
    code, body = cli(repo, plan)
    assert code != 0, body
    assert all(row["outcome"] != "detected" for row in body.get("mutations", [])), body


@pytest.mark.parametrize(
    "candidate",
    [
        {**BOUNDARY, "before": "value >= 999"},
        {
            "path": PROOF,
            "before": "assert accepts(3)",
            "after": "assert accepts(0)",
            "effect": "change the selected proof itself",
        },
    ],
    ids=["absent-fragment", "selected-proof"],
)
def test_inapplicable_candidate_cannot_be_a_detection(repo, candidate):
    plan = repo / "plan.json"
    plan.write_text(
        json.dumps({"criterion": "AC-1", "tests": [POINT], "mutations": [candidate]})
    )
    code, body = cli(repo, plan)
    assert code != 0, body
    assert all(
        row["outcome"] in {"invalid", "not_run"} for row in body.get("mutations", [])
    ), body
    assert (repo / "value.py").read_text() == SOURCE
    assert (repo / PROOF).read_text() == WEAK_PROOF


def test_interrupt_preserves_dirty_source_untracked_proof_and_index(
    repo, tmp_path_factory
):
    observer = tmp_path_factory.mktemp("mutation-observer")
    marker = observer / "mutant-started"
    gate = observer / "gate"
    draft = repo / "checks/test_draft.py"
    source = repo / "value.py"
    source.write_text(SOURCE.replace("value >= 1", "value >= 2"))
    subprocess.run(["git", "add", "value.py"], cwd=repo, check=True)
    source.write_text(SOURCE.replace("value >= 1", "value >= 4"))
    draft.write_text(
        "import fcntl\nfrom pathlib import Path\nfrom value import accepts\n\n"
        "def test_threshold():\n"
        "    assert not accepts(3)\n"
        "    if not accepts(4):\n"
        f"        with Path({str(marker)!r}).open('w') as witness, Path({str(gate)!r}).open('rb') as gate:\n"
        "            fcntl.flock(witness, fcntl.LOCK_EX)\n"
        "            witness.write('running')\n"
        "            witness.flush()\n"
        "            fcntl.flock(gate, fcntl.LOCK_SH)\n"
        "    assert accepts(4)\n"
    )
    plan = repo / "plan.json"
    candidate = {**BOUNDARY, "before": "value >= 4", "after": "value > 4"}
    plan.write_text(
        json.dumps(
            {
                "criterion": "AC-1",
                "tests": ["checks/test_draft.py::test_threshold"],
                "mutations": [candidate],
            }
        )
    )
    original = source.read_bytes(), draft.read_bytes()
    staged = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=repo)
    with gate.open("wb") as barrier:
        fcntl.flock(barrier, fcntl.LOCK_EX)
        process = subprocess.Popen(
            [
                sys.executable,
                ".map/scripts/mutation_check.py",
                str(plan),
                "--timeout",
                str(int(LOAD_DEADLINE)),
                "--total-timeout",
                str(int(LOAD_DEADLINE * 2)),
            ],
            cwd=repo,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + LOAD_DEADLINE
            while not marker.exists() or not marker.read_bytes():
                if process.poll() is not None:
                    pytest.fail(
                        f"Runner exited before the draft test reached its mutant: {process.communicate()}"
                    )
                assert time.monotonic() < deadline, "Draft test did not reach mutant"
                time.sleep(0.02)
            assert (source.read_bytes(), draft.read_bytes()) == original
            process.send_signal(signal.SIGINT)
            stdout, _ = process.communicate(timeout=LOAD_DEADLINE)
            assert process.returncode != 0
            with marker.open("rb") as witness:
                fcntl.flock(witness, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            barrier.close()
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=LOAD_DEADLINE)

    assert (source.read_bytes(), draft.read_bytes()) == original
    assert (
        subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=repo)
        == staged
    )
    reports = [json.loads(stdout)] if stdout.strip() else []
    reports.extend(
        json.loads(path.read_bytes()) for path in (repo / ".map").rglob("*.json")
    )
    for report in reports:
        if isinstance(report, dict) and "mutations" in report:
            assert all(
                row["outcome"] in {"not_run", "inconclusive"}
                for row in report["mutations"]
            ), report


def test_cli_import_failure_and_wrong_output_are_distinct(repo):
    (repo / "value.py").write_text("import math\nprint(math.ceil(2.3))\n")
    (repo / PROOF).write_text(
        "import subprocess\nimport sys\n\n"
        "def test_accepts_positive():\n"
        "    result = subprocess.run([sys.executable, 'value.py'], capture_output=True, text=True, check=False)\n"
        "    assert result.returncode == 0, result.stderr\n"
        "    assert result.stdout.strip() == '3'\n"
    )
    candidates = [
        {
            "path": "value.py",
            "before": "import math",
            "after": "import missing_numeric_fixture",
            "effect": "fail during CLI import",
        },
        {
            "path": "value.py",
            "before": "math.ceil",
            "after": "math.floor",
            "effect": "print the lower integer",
        },
    ]
    code, body = check(repo, candidates)
    startup, output = outcomes(body)
    assert output == "detected", body
    assert startup in {"invalid", "inconclusive"}, body
    assert code != 0, body


@pytest.mark.parametrize("payload", [[], {"plan": None}], ids=["array", "null-plan"])
def test_malformed_report_is_not_current(repo, payload):
    report = repo / "report.json"
    report.write_text(json.dumps(payload))
    assert_current(repo, report, False)
