"""Execute the canonical A.0b wrapper without running project checks."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = (Path(__file__).resolve().parents[1]
         / "src/mapify_cli/templates_src/skills/map-review/SKILL.md.jinja")


def _run_wrapper(monkeypatch, first_output, returncode):
    text = SKILL.read_text(encoding="utf-8")
    wrapper = text.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    checks = []

    def run(argv, **kwargs):
        del kwargs
        if "begin_review_run" in argv:
            return subprocess.CompletedProcess(argv, 0, '{"completed":false}')
        check_id = argv[-1]
        checks.append(check_id)
        output = first_output if check_id == "lint" else json.dumps({
            "observation_valid": True, "passed": True, "full_gate_status": "passed",
        })
        return subprocess.CompletedProcess(argv, returncode if check_id == "lint" else 0, output)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["-", '{"lint":["make","lint"],"tests":["pytest"]}',
                                     "full", "", "", "{}"])
    exec(compile(wrapper, str(SKILL), "exec"), {})  # noqa: S102 - trusted canonical workflow snippet
    return checks


@pytest.mark.parametrize("attribution", ["unknown", "new", "baseline_only"])
def test_failed_observation_continues_collection(monkeypatch, capsys, attribution):
    receipt = {"observation_valid": True, "passed": False, "exit_code": 1,
               "full_gate_status": "failed", "baseline_attribution": {"status": attribution},
               "output_artifact": "review-checks/attempt/output.txt"}
    assert _run_wrapper(monkeypatch, json.dumps(receipt), 1) == ["lint", "tests"]
    output = capsys.readouterr().out
    assert "passed=False" in output
    assert "full_gate_status=failed" in output
    assert attribution in output


@pytest.mark.parametrize("output", ["", "not-json", "null", "[]", "{}",
                                    '{"observation_valid":false}',
                                    '{"observation_valid":"true"}'])
@pytest.mark.parametrize("returncode", [0, 1])
def test_invalid_observation_hard_stops(monkeypatch, output, returncode):
    with pytest.raises(SystemExit, match="observation"):
        _run_wrapper(monkeypatch, output, returncode)


def test_passing_observation_continues(monkeypatch):
    assert _run_wrapper(monkeypatch, json.dumps({
        "observation_valid": True, "passed": True, "full_gate_status": "passed",
    }), 0) == ["lint", "tests"]
