"""The snapshot fingerprint is reused while cheap signals are unchanged and never when they change (#657)."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.test_review_context_delivery import (
    acknowledge,
    bind,
    final_envelope,
    prepare,
    runner,
    serve,
)
from tests.test_review_context_delivery import repository as _repository

repository = _repository
__all__ = ["repository"]


@pytest.fixture
def computations(monkeypatch):
    """Count full target recomputations and trusted-policy rediscoveries."""
    counts = {"target": 0, "policy": 0}
    for key, name in (("target", "_review_target_compute"), ("policy", "_review_trusted_policy")):
        original = getattr(runner, name)

        def counted(*args, _key=key, _original=original, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(runner, name, counted)
    return counts


def reset(counts):
    counts["target"] = counts["policy"] = 0


def warm():
    """Populate the cache the way a real caller does and make sure a repeat observation is a hit."""
    runner._review_target({})
    time.sleep(3.5)  # leave the racy window so later observations compare stable signatures
    first = runner._review_target({})
    runner._review_target({})
    return first


def test_vc1_serve_ack_capture_in_one_state_never_recompute_the_target(repository, computations):
    del repository
    state = bind(prepare()["monitor"])
    warm()
    reset(computations)
    chunk = serve(state)
    assert acknowledge(state, chunk)["status"] == "context_pending"
    while True:
        state = runner.review_context_status(state["session_id"], "delivery-round", branch="feature")
        if state["status"] == "context_ready":
            break
        chunk = serve(state)
        state = acknowledge(state, chunk)
        if state["status"] == "context_ready":
            break
    result = runner.capture_review_output("monitor", json.dumps(final_envelope(state)), "delivery-round",
                                          branch="feature")
    assert result["status"] == "success", result
    assert computations == {"target": 0, "policy": 0}


def test_vc2_cached_target_equals_a_fresh_computation(repository):
    del repository
    cached = warm()
    assert runner._review_target({}) == cached == runner._review_target_compute({})


MUTATIONS = {
    "required_file": lambda: Path("code.py").write_text("value = 3\n"),
    "new_commit": lambda: subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "next"], check=True),
    "index_only": lambda: subprocess.run(["git", "update-index", "--chmod=+x", "code.py"], check=True),
    "untracked_file": lambda: Path("fresh.py").write_text("x = 1\n"),
    "policy_file": lambda: Path("CLAUDE.md").write_text("rules\n"),
    "staged_new_file": lambda: (Path("staged.py").write_text("y = 1\n"),
                                subprocess.run(["git", "add", "staged.py"], check=True)),
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_vc3_every_cheap_signal_change_forces_a_recomputation(repository, computations, mutation):
    del repository
    before = warm()
    reset(computations)
    runner._review_target({})
    assert computations["target"] == 0, "precondition: an unchanged state is a cache hit"
    MUTATIONS[mutation]()
    after = runner._review_target({})
    # the index may be refreshed while computing, which costs one extra attempt before the entry is stored
    assert 1 <= computations["target"] <= 2, mutation
    assert after != before, mutation
    assert after == runner._review_target_compute({})


def test_vc4_rewrite_with_restored_mtime_is_still_detected_outside_the_racy_window(repository, computations):
    del repository
    target = Path("code.py")
    warm()
    reset(computations)
    stat = target.stat()
    target.write_text("value = 9\n")  # same size as "value = 2\n"
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = runner._review_target({})
    assert computations["target"] == 1
    assert changed == runner._review_target_compute({})


def test_vc5_unchanged_state_stays_a_hit_after_the_racy_window(repository, computations):
    del repository
    warm()
    reset(computations)
    runner._review_target({})
    assert computations["target"] == 0


def test_vc6_explicit_base_and_default_base_do_not_share_an_entry(repository, computations):
    del repository
    warm()
    reset(computations)
    explicit = runner._review_target({"base_ref": "main"})
    assert computations["target"] == 1
    assert explicit["base_ref"] == "main"


def test_vc7_cache_lives_outside_branch_directories_and_survives_a_new_process(repository):
    entries = list((repository / ".map/.review-target-cache").glob("*.json"))
    assert entries == []
    warm()
    entries = list((repository / ".map/.review-target-cache").glob("*.json"))
    assert len(entries) == 1
    script = (
        "import sys, json; sys.path.insert(0, sys.argv[1])\n"
        "import map_step_runner as m\n"
        "calls = []\n"
        "original = m._review_target_compute\n"
        "m._review_target_compute = lambda *a, **k: (calls.append(1), original(*a, **k))[1]\n"
        "m._review_target({}); print(json.dumps(len(calls)))\n"
    )
    result = subprocess.run(["python3", "-c", script, str(Path(runner.__file__).parent)], capture_output=True, text=True, check=False,
                            cwd=repository)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == 0
