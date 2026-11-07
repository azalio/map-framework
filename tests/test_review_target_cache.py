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


@pytest.fixture(autouse=True)
def short_racy_window(monkeypatch):
    """Keep the suite fast; the shipped window is pinned separately."""
    monkeypatch.setattr(runner, "_REVIEW_RACY_NS", 1_000_000_000)


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


def warm_with(binding, *, settle=True):
    """Populate the cache and wait until an observation is a hit.

    Git may touch the index while a computation runs (racy-git smudging), and a file touched inside the racy
    window joins the signature as bytes. Under load that makes a stored entry unreusable once the file ages
    out, so one pass is not enough: repeat until a full pass beyond the window recomputes nothing.
    """
    if not settle:  # an uncacheable target (submodule) never produces a hit
        runner._review_target(binding)
        time.sleep(1.2)
        runner._review_target(binding)
        return runner._review_target(binding)
    for _ in range(8):
        runner._review_target(binding)
        time.sleep(1.2)  # leave the (shortened) racy window so later observations compare stable signatures
        calls = []
        original = runner._review_target_compute

        def counted(*args, _original=original, **kwargs):
            calls.append(1)
            return _original(*args, **kwargs)

        runner._review_target_compute = counted
        try:
            first = runner._review_target(binding)
            runner._review_target(binding)
        finally:
            runner._review_target_compute = original
        if not calls:
            return first
    raise AssertionError("the target cache never settled into a reusable entry")


def warm():
    """Populate the cache the way a real caller does and make sure a repeat observation is a hit."""
    return warm_with({})


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
    assert 1 <= computations["target"] <= 2  # a second attempt happens when the index refreshes mid-compute
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
        "m._REVIEW_RACY_NS = 1_000_000_000\n"
        "calls = []\n"
        "original = m._review_target_compute\n"
        "m._review_target_compute = lambda *a, **k: (calls.append(1), original(*a, **k))[1]\n"
        "m._review_target({}); print(json.dumps(len(calls)))\n"
    )
    result = subprocess.run(["python3", "-c", script, str(Path(runner.__file__).parent)], capture_output=True, text=True, check=False,
                            cwd=repository)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == 0


def git_out(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def commit_on(ref, files, message):
    """Commit ``files`` onto ``ref`` without touching the worktree, index or HEAD."""
    parent = git_out("rev-parse", ref)
    env = dict(os.environ, GIT_INDEX_FILE=str(Path(".git/tmpidx").resolve()))
    subprocess.run(["git", "read-tree", parent], env=env, check=True)
    for name, content in files.items():
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=content, capture_output=True,
                              text=True, check=True).stdout.strip()
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"], env=env, check=True)
    tree = subprocess.run(["git", "write-tree"], env=env, capture_output=True, text=True, check=True).stdout.strip()
    created = subprocess.run(["git", "commit-tree", tree, "-p", parent, "-m", message], capture_output=True,
                             text=True, check=True).stdout.strip()
    subprocess.run(["git", "update-ref", ref, created], check=True)


def test_vc8_explicit_base_still_notices_a_default_ref_move(repository):
    del repository
    subprocess.run(["git", "branch", "devel", "main"], check=True)
    binding = {"base_ref": "devel"}
    warm_with(binding)
    commit_on("refs/heads/main", {"REVIEW.md": "be strict about secrets\n"}, "policy")
    cached = runner._review_target(binding)
    assert cached == runner._review_target_compute(binding)
    assert cached["trusted_policy"]["files"]


def test_vc9_default_mode_notices_a_default_ref_move(repository):
    del repository
    warm_with({})
    commit_on("refs/heads/main", {"REVIEW.md": "be strict\n"}, "policy")
    assert runner._review_target({}) == runner._review_target_compute({})


def test_vc10_explicit_admission_survives_a_default_ref_move(repository):
    del repository
    subprocess.run(["git", "branch", "devel", "main"], check=True)
    warm_with({"base_ref": "devel"})
    commit_on("refs/heads/main", {"REVIEW.md": "be strict about secrets\n"}, "policy")
    admitted = runner.begin_review_run(round_id="r1", provider="codex", branch="feature", base_ref="devel")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"


def test_vc11_info_attributes_change_forces_a_recomputation(repository):
    del repository
    Path("code.py").write_text("value = 3\n")
    warm_with({})
    Path(".git/info/attributes").write_text("code.py -diff\n")
    assert runner._review_target({}) == runner._review_target_compute({})


def test_vc12_submodule_checkout_move_is_never_served_from_cache(repository, tmp_path_factory):
    del repository
    source = tmp_path_factory.mktemp("subsrc")
    subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
    for number in (1, 2):
        (source / "nested").mkdir(exist_ok=True)
        (source / "nested" / "f.txt").write_text(f"{number}\n")
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm",
                        str(number)], check=True)
    subprocess.run(["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "sm"],
                   check=True)
    subprocess.run(["git", "commit", "-qm", "add sm"], check=True)
    warm_with({}, settle=False)
    subprocess.run(["git", "-C", "sm", "checkout", "-q", "HEAD~1"], check=True)
    assert runner._review_target({}) == runner._review_target_compute({})


def test_vc13_explicit_base_watches_files_of_the_merge_base_tree(repository):
    del repository
    subprocess.run(["git", "checkout", "-q", "main"], check=True)
    Path("gone.txt").write_text("tracked\n")
    Path(".gitignore").write_text(".map/\ngone.txt\n")
    subprocess.run(["git", "add", "-f", "gone.txt", ".gitignore"], check=True)
    subprocess.run(["git", "commit", "-qm", "track gone"], check=True)
    subprocess.run(["git", "branch", "devel", "main"], check=True)
    subprocess.run(["git", "checkout", "-q", "devel"], check=True)
    subprocess.run(["git", "rm", "-q", "gone.txt"], check=True)
    subprocess.run(["git", "commit", "-qm", "drop on devel"], check=True)
    subprocess.run(["git", "checkout", "-q", "feature"], check=True)
    subprocess.run(["git", "rebase", "-q", "main"], check=True)
    subprocess.run(["git", "rm", "-q", "gone.txt"], check=True)
    subprocess.run(["git", "commit", "-qm", "drop on feature"], check=True)
    binding = {"base_ref": "devel"}
    warm_with(binding)
    Path("gone.txt").write_text("ignored but present in the merge-base tree\n")
    assert runner._review_target(binding) == runner._review_target_compute(binding)


def test_vc14_plan_listing_ignores_the_target_cache_directory(repository):
    warm_with({})
    assert (repository / ".map/.review-target-cache").is_dir()
    assert all(not item["branch"].startswith(".") for item in runner.list_plans()["plans"])


def test_vc16_shipped_racy_window_tolerates_clock_skew():
    assert "_REVIEW_RACY_NS = 10_000_000_000" in Path(runner.__file__).read_text(encoding="utf-8")
