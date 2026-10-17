"""Public runner checks use admission-bound execution deadlines."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "src/mapify_cli/templates/map/scripts/map_step_runner.py"


@pytest.fixture()
def check_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], check=True)
    Path(".gitignore").write_text(".map/\n")
    Path("writer.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base"], check=True, capture_output=True)
    return tmp_path / ".map/main/review-verdict-ledger.json"


def _cli(*args):
    process = subprocess.run([sys.executable, str(RUNNER), *args], capture_output=True, text=True, check=False)
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def _admit(timeout):
    return _cli("begin_review_run", "--mode", "lightweight", "--round-id", "timeout",
                "--required-check", "suite", "--check-specs-json",
                json.dumps({"suite": [sys.executable, "-c", "import time; time.sleep(0.15)"]}),
                "--check-timeouts-json", json.dumps({"suite": timeout}))


def test_custom_check_timeout_is_enforced_and_frozen(check_workspace):
    admission = _admit(0.02)
    assert admission["status"] == "success", admission
    result = _cli("run_test_gate", "--check-id", "suite")
    assert result["passed"] is False and result["exit_code"] is None, result
    ledger = json.loads(check_workspace.read_text())
    assert ledger["execution_checks"]["suite"]["status"] == "timeout"
    assert ledger["execution_checks"]["suite"]["timeout_seconds"] == 0.02
    assert ledger["convergence"]["rounds"][0]["binding"]["check_timeouts"] == {"suite": 0.02}
    before = check_workspace.read_bytes()
    changed = _admit(2)
    assert changed["status"] == "error", changed
    assert check_workspace.read_bytes() == before


def test_custom_check_timeout_allows_success(check_workspace):
    del check_workspace
    assert _admit(2)["status"] == "success"
    result = _cli("run_test_gate", "--check-id", "suite")
    assert result["passed"] is True and result["exit_code"] == 0, result


@pytest.mark.parametrize("timeout", [0, -1, True, "2", None, float("nan"), float("inf")])
def test_invalid_check_timeout_rejected_without_admission(check_workspace, timeout):
    result = _admit(timeout)
    assert result["status"] == "error", result
    assert not check_workspace.exists()


def test_timeout_for_unadmitted_check_rejected(check_workspace):
    result = _cli("begin_review_run", "--mode", "lightweight", "--check-timeouts-json", '{"missing": 2}')
    assert result["status"] == "error", result
    assert not check_workspace.exists()
