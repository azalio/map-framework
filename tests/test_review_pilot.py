"""Offline public-seam tests for the bounded subscription pilot."""

import json
from pathlib import Path
from typing import Any

import pytest

from mapify_cli.skills_eval.review_pilot import prepare

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests/skills_eval/review_corpus"


def test_prepare_freezes_six_slots_and_clean_historical_prompts(tmp_path: Path) -> None:
    run = tmp_path / "pilot"
    manifest = prepare(CORPUS, REPO, tmp_path / "corrections.json", run, "2.1.301")
    assert manifest["model"] == "claude-opus-5-5"
    assert manifest["limits"] == {"invocations": 6, "input": 2100000, "output": 49000}
    assert [
        (s["case_id"], s["repeat"], s["input_reservation"]) for s in manifest["slots"]
    ] == [
        ("c-41be", 1, 650000),
        ("c-93f0", 1, 100000),
        ("c-7d2a", 1, 300000),
        ("c-41be", 2, 650000),
        ("c-93f0", 2, 100000),
        ("c-7d2a", 2, 300000),
    ]
    for slot in manifest["slots"]:
        assert slot["output_reservation"] == 8166
        prompt = (run / slot["prompt_file"]).read_text()
        assert '"labels"' not in prompt
        assert '"scenario"' not in prompt
        assert '"evidence"' not in prompt
        assert slot["estimated_input"] <= slot["input_reservation"]
        assert slot["prompt_bytes"] == len(prompt.encode())
    assert manifest["slots"][0]["prompt_hash"] == manifest["slots"][3]["prompt_hash"]
    assert "heuristic" in manifest["estimator"]


def result_bytes(input_tokens: int = 100, output_tokens: int = 20) -> bytes:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "No supported findings.",
            "num_turns": 1,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 40,
            },
            "modelUsage": {
                "claude-opus-5-5": {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "cacheReadInputTokens": 30,
                    "cacheCreationInputTokens": 40,
                }
            },
        }
    ).encode()


def test_run_reserves_before_executor_and_reports_six_without_replay(
    tmp_path: Path,
) -> None:
    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    calls = []

    def execute(request: Any) -> int:
        state = json.loads((directory / "ledger.json").read_text())
        assert state["attempts"][-1]["status"] == "reserved"
        assert not list(request.cwd.iterdir())
        assert request.argv[request.argv.index("--tools") + 1] == ""
        assert request.argv[request.argv.index("--model") + 1] == "claude-opus-5-5"
        assert request.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8166"
        assert "ANTHROPIC_BASE_URL" not in request.env
        assert "PYTHONPATH" not in request.env
        assert "UNTRUSTED HISTORICAL INPUT" in request.prompt.decode()
        request.stdout.write_bytes(result_bytes())
        request.stderr.write_bytes(b"fixture stderr")
        calls.append(request)
        return 0

    run(directory, execute)
    run(directory, execute)
    summary = report(directory)
    assert len(calls) == 6
    assert summary["totals"] == {
        "input": 1020,
        "output": 120,
        "cache_read": 180,
        "cache_creation": 240,
    }
    assert summary["status"] == "complete"
    assert (directory / "raw/0.stderr").read_bytes() == b"fixture stderr"


@pytest.mark.parametrize("mutation", ["extra", "symlink", "changed", "baseline"])
def test_run_rejects_contamination_before_spawn(tmp_path: Path, mutation: str) -> None:
    from mapify_cli.skills_eval.review_pilot import run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    exported = directory / "exports/c-41be"
    if mutation == "extra":
        (exported / "labels.json").write_text("host only")
    elif mutation == "symlink":
        (exported / "leak").symlink_to(CORPUS)
    elif mutation == "changed":
        (exported / "review.diff").write_text("changed")
    else:
        (directory / "baseline.txt").write_text("changed")
    with pytest.raises(ValueError):
        run(directory, lambda _: pytest.fail("must not spawn"))


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "bool",
        "negative",
        "float",
        "duplicate",
        "malformed",
        "model",
        "tool",
        "timeout",
        "exit",
        "overrun",
    ],
)
def test_bad_outcome_stops_and_preserves_raw_without_retry(
    tmp_path: Path, failure: str
) -> None:
    import subprocess

    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    data = json.loads(result_bytes())
    if failure == "missing":
        del data["usage"]["cache_read_input_tokens"]
    elif failure in {"bool", "negative", "float"}:
        data["usage"]["input_tokens"] = {"bool": True, "negative": -1, "float": 1.5}[
            failure
        ]
    elif failure == "model":
        data["model"] = "another-model"
    elif failure == "tool":
        data["usage"]["server_tool_use"] = {"web_search_requests": 1}
    raw = json.dumps(data).encode()
    if failure == "duplicate":
        raw = b'{"usage":{},"usage":{}}'
    elif failure == "malformed":
        raw = b"not JSON"
    elif failure == "overrun":
        raw = result_bytes(2100001)
    calls = []

    def execute(request: Any) -> int:
        calls.append(request)
        request.stdout.write_bytes(raw)
        request.stderr.write_bytes(b"offline diagnostic")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fake", 1)
        return 1 if failure == "exit" else 0

    with pytest.raises(ValueError, match="stopped"):
        run(directory, execute)
    with pytest.raises(ValueError, match="never resend"):
        run(directory, execute)
    assert len(calls) == 1
    assert (directory / "raw/0.stdout").read_bytes() == raw
    summary = report(directory)
    assert summary["status"] == "partial"
    assert summary["attempts"][0]["status"] == "stopped"


def test_missing_usage_is_unknown_not_zero(tmp_path: Path) -> None:
    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")

    def execute(request: Any) -> int:
        request.stdout.write_bytes(b"{}")
        request.stderr.write_bytes(b"")
        return 0

    with pytest.raises(ValueError):
        run(directory, execute)
    assert report(directory)["accounting_complete"] is False
    assert report(directory)["unknown_slots"] == [0]


def test_restart_after_process_death_never_replays(tmp_path: Path) -> None:
    import subprocess
    import sys

    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    script = """
import os, sys
from pathlib import Path
from mapify_cli.skills_eval.review_pilot import run

def execute(request):
    request.stdout.write_bytes(b'partial output')
    request.stderr.write_bytes(b'partial diagnostic')
    os._exit(23)

run(Path(sys.argv[1]), execute)
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(directory)], cwd=REPO, check=False
    )
    assert process.returncode == 23
    with pytest.raises(ValueError, match="never resend"):
        run(directory, lambda _: pytest.fail("must not replay"))
    assert report(directory)["attempts"][0]["status"] == "reserved"
    assert (directory / "raw/0.stdout").read_bytes() == b"partial output"


def test_prepare_and_cli_report_are_offline(tmp_path: Path) -> None:
    import subprocess
    import sys

    directory = tmp_path / "pilot"
    args = [sys.executable, "-m", "mapify_cli.skills_eval.review_pilot"]
    prepared = subprocess.run(
        args
        + [
            "prepare",
            "--corpus",
            str(CORPUS),
            "--repo",
            str(REPO),
            "--corrections",
            str(tmp_path / "corrections.json"),
            "--run-dir",
            str(directory),
            "--cli-version",
            "2.1.301",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert (directory / "manifest.json").exists()
    reported = subprocess.run(
        args + ["report", "--run-dir", str(directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert reported.returncode == 0, reported.stderr
    assert json.loads(reported.stdout)["attempts"] == []


def test_concurrent_process_is_excluded_by_stable_lock(tmp_path: Path) -> None:
    import subprocess
    import sys
    import time

    from mapify_cli.skills_eval.review_pilot import run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    script = """
import sys, time
from pathlib import Path
from mapify_cli.skills_eval.review_pilot import run

def execute(request):
    request.stdout.write_bytes(b'entered')
    time.sleep(60)
    return 1

run(Path(sys.argv[1]), execute)
"""
    child = subprocess.Popen([sys.executable, "-c", script, str(directory)], cwd=REPO)
    try:
        deadline = time.monotonic() + 30
        while not (directory / "raw/0.stdout").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (directory / "raw/0.stdout").exists()
        with pytest.raises(ValueError, match="already running"):
            run(directory, lambda _: pytest.fail("concurrent invocation"))
    finally:
        child.kill()
        child.wait(timeout=10)
    with pytest.raises(ValueError, match="never resend"):
        run(directory, lambda _: pytest.fail("restart replay"))


def test_publication_failure_keeps_reservation_and_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")

    def execute(request: Any) -> int:
        request.stdout.write_bytes(result_bytes())
        request.stderr.write_bytes(b"preserved")

        def fail_replace(*_args: Any) -> None:
            raise OSError("injected publication failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        return 0

    with pytest.raises(OSError, match="publication failure"):
        run(directory, execute)
    monkeypatch.undo()
    assert report(directory)["attempts"][0]["status"] == "reserved"
    with pytest.raises(ValueError, match="never resend"):
        run(directory, lambda _: pytest.fail("must not resend"))
    assert (directory / "raw/0.stdout").read_bytes() == result_bytes()


@pytest.mark.parametrize("corruption", [b"{", b"{}", b'{"attempts":true}'])
def test_corrupt_ledger_blocks_spawn(tmp_path: Path, corruption: bytes) -> None:
    from mapify_cli.skills_eval.review_pilot import run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    (directory / "ledger.json").write_bytes(corruption)
    with pytest.raises(ValueError):
        run(directory, lambda _: pytest.fail("corrupt ledger must block"))


def test_observed_usage_blocks_next_reservation(tmp_path: Path) -> None:
    from mapify_cli.skills_eval.review_pilot import run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")
    calls = []

    def execute(request: Any) -> int:
        calls.append(request)
        request.stdout.write_bytes(result_bytes(2050000))
        request.stderr.write_bytes(b"")
        return 0

    with pytest.raises(ValueError, match="admission budget"):
        run(directory, execute)
    assert len(calls) == 1


def test_correction_invalidates_report_without_destroying_raw(tmp_path: Path) -> None:
    from mapify_cli.skills_eval.review_corpus import correct_labels, load_corpus
    from mapify_cli.skills_eval.review_pilot import report

    directory = tmp_path / "pilot"
    corrections = tmp_path / "corrections.json"
    prepare(CORPUS, REPO, corrections, directory, "2.1.301")
    (directory / "raw/0.stdout").write_bytes(b"historical")
    case = load_corpus(CORPUS, REPO)["cases"][0]
    correct_labels(
        CORPUS,
        REPO,
        corrections,
        "test-correction",
        case["id"],
        case["labels"],
        expected_revision=0,
        reason="verified",
    )
    with pytest.raises(ValueError, match="stale"):
        report(directory)
    assert (directory / "raw/0.stdout").read_bytes() == b"historical"


def test_completed_raw_evidence_cannot_be_silently_changed(tmp_path: Path) -> None:
    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")

    def execute(request: Any) -> int:
        request.stdout.write_bytes(result_bytes())
        request.stderr.write_bytes(b"")
        return 0

    run(directory, execute)
    (directory / "raw/0.stdout").write_bytes(b"changed")
    with pytest.raises(ValueError, match="raw evidence"):
        report(directory)


def test_live_adapter_boundary_is_exercised_only_with_fake_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from mapify_cli.skills_eval.review_pilot import Request, live_executor

    captured = []

    def fake_process(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        captured.append((argv, kwargs))
        kwargs["stdout"].write(b"raw stdout")
        kwargs["stderr"].write(b"raw stderr")
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(subprocess, "run", fake_process)
    request = Request(
        ["offline-fake"],
        {"HOME": "fixture"},
        tmp_path,
        b"stdin",
        tmp_path / "out",
        tmp_path / "err",
    )
    assert live_executor(request) == 7
    assert len(captured) == 1
    assert captured[0][1]["input"] == b"stdin"
    assert captured[0][1]["env"] == {"HOME": "fixture"}
    assert captured[0][1]["cwd"] == tmp_path
    assert captured[0][1]["timeout"] == 900
    assert request.stdout.read_bytes() == b"raw stdout"
    assert request.stderr.read_bytes() == b"raw stderr"


def test_correction_during_first_call_blocks_second_reservation(tmp_path: Path) -> None:
    from mapify_cli.skills_eval.review_corpus import correct_labels, load_corpus
    from mapify_cli.skills_eval.review_pilot import run

    directory = tmp_path / "pilot"
    corrections = tmp_path / "corrections.json"
    prepare(CORPUS, REPO, corrections, directory, "2.1.301")
    case = load_corpus(CORPUS, REPO)["cases"][0]
    calls = []

    def execute(request: Any) -> int:
        calls.append(request)
        request.stdout.write_bytes(result_bytes())
        request.stderr.write_bytes(b"retained")
        if len(calls) == 1:
            correct_labels(
                CORPUS,
                REPO,
                corrections,
                "mid-run",
                case["id"],
                case["labels"],
                expected_revision=0,
                reason="verified",
            )
        return 0

    with pytest.raises(ValueError, match="stale"):
        run(directory, execute)
    assert len(calls) == 1
    assert len(json.loads((directory / "ledger.json").read_text())["attempts"]) == 1
    assert (directory / "raw/0.stdout").read_bytes() == result_bytes()


@pytest.mark.parametrize("outcome", ["overrun", "error", "timeout"])
@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_stopped_raw_evidence_is_verified(
    tmp_path: Path, outcome: str, channel: str
) -> None:
    import subprocess

    from mapify_cli.skills_eval.review_pilot import report, run

    directory = tmp_path / "pilot"
    prepare(CORPUS, REPO, tmp_path / "corrections.json", directory, "2.1.301")

    def execute(request: Any) -> int:
        request.stdout.write_bytes(result_bytes(2100001))
        request.stderr.write_bytes(b"retained diagnostic")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fake", 1)
        return 1 if outcome == "error" else 0

    with pytest.raises(ValueError, match="stopped"):
        run(directory, execute)
    assert report(directory)["accounting_complete"] is (outcome == "overrun")
    (directory / "raw" / f"0.{channel}").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="raw evidence"):
        report(directory)
