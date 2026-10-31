"""Supplemental #557 regressions: readers must not mix admitted and live scopes."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.review_context_helpers import original_review_prompt
from tests.test_review_explicit_base import SCRIPTS, admit, git, runner
from tests.test_review_explicit_base import stack as stack  # noqa: PLC0414 -- expose pytest fixture


def mutate_scope(change):
    if change == "deleted":
        git("branch", "-D", "runtime")
    elif change == "changed-merge-base":
        git("branch", "-f", "runtime", "HEAD")
    else:
        git("checkout", "main" if change == "policy" else "runtime")
        if change == "policy":
            Path("REVIEW.md").write_text("MAIN_POLICY: new independent authority.\n")
        git("commit", "-am", "advance authority", "--allow-empty")
        git("checkout", "product")


def fresh_consumer(consumer, *, supplied=False):
    kwargs = {"branch": "product"}
    if supplied:
        kwargs["git_diff_text"] = "SUPPLIED_DIFF_SENTINEL"
    code = """
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import map_step_runner as runner
try:
    result = getattr(runner, sys.argv[2])(**json.loads(sys.argv[3]))
except (ValueError, RuntimeError) as exc:
    result = {"status": "error", "message": str(exc)}
print(json.dumps(result))
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code, str(SCRIPTS), consumer, json.dumps(kwargs)],
        check=False, capture_output=True, text=True, timeout=45,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("change", ["same-merge-base", "changed-merge-base", "deleted", "policy"])
@pytest.mark.parametrize("consumer,supplied", [
    ("snapshot_code_state", False),
    ("build_review_prompts", False),
    ("build_adversarial_review_prompts", False),
    ("build_review_prompts", True),
    ("build_adversarial_review_prompts", True),
    ("build_cross_ai_review_prompt", True),
])
def test_fresh_public_readers_reject_stale_admitted_scope(stack, change, consumer, supplied):
    admit(base_ref="runtime")
    bundle = runner.create_review_bundle(branch="product")
    assert bundle["status"] == "success"
    ledger = Path(".map/product/review-verdict-ledger.json")
    mode = Path(".map/product/review-mode.json")
    before = (ledger.read_bytes(), mode.read_bytes())
    mutate_scope(change)
    if change == "same-merge-base":
        assert git("merge-base", "runtime", "HEAD") == stack["runtime"]
        assert git("rev-parse", "runtime") != stack["runtime"]
    elif change == "changed-merge-base":
        assert git("merge-base", "runtime", "HEAD") != stack["runtime"]
    result = fresh_consumer(consumer, supplied=supplied)
    assert isinstance(result, dict) and result.get("status") == "error", result
    assert (ledger.read_bytes(), mode.read_bytes()) == before


@pytest.mark.parametrize("change", ["same-merge-base", "changed-merge-base", "deleted", "policy"])
def test_supplied_diff_does_not_bypass_scope_resolution(stack, change):
    del stack
    admit(base_ref="runtime")
    mutate_scope(change)
    with pytest.raises((ValueError, RuntimeError)):
        runner._scoped_review_diff("product", "SUPPLIED_DIFF_SENTINEL")


@pytest.mark.parametrize("consumer", ["snapshot_code_state", "build_review_prompts", "build_adversarial_review_prompts"])
def test_current_scope_readers_still_observe_dirty_work(stack, consumer):
    """Dirty work requires fresh immutable admission before a prompt can expose it."""
    admit(base_ref="runtime")
    assert runner.create_review_bundle(branch="product")["status"] == "success"
    Path("product.py").write_text("PRODUCT = 558\n")
    result = fresh_consumer(consumer)
    if consumer == "snapshot_code_state":
        assert result["status"] == "success", result
        assert result["diff_base"] == stack["runtime"][:12]
        assert "product.py" in result["uncommitted_files_changed"]
    else:
        # An immutable delivery cannot mix newly dirty code with the older
        # admitted bundle. Re-admit it explicitly before constructing prompts.
        assert result["status"] == "error", result
        assert runner.abandon_review_round("stack", reason="Include new dirty work", branch="product")["status"] == "success"
        admitted = runner.begin_review_run(branch="product", base_ref="runtime", round_id="refreshed")
        assert admitted["status"] == "success", admitted
        assert runner.create_review_bundle(branch="product")["status"] == "success"
        result = fresh_consumer(consumer)
        assert result["status"] == "success", result
        for name, entry in result["prompts"].items():
            prompt = original_review_prompt(runner, entry, name, branch="product")
            assert "+PRODUCT = 558" in prompt, name
            assert "+PARENT_ONLY = 1701" not in prompt, name


def test_admitted_default_with_unrelated_ancestry_keeps_dirty_fallback(stack):
    del stack
    tree = git("rev-parse", "main^{tree}")
    unrelated = git("commit-tree", tree, "-m", "unrelated default authority")
    git("update-ref", "refs/heads/main", unrelated)
    Path("product.py").write_text("PRODUCT = 558\n")
    admission = admit()
    assert not admission["target"]["base"]
    result = fresh_consumer("snapshot_code_state")
    assert result["status"] == "success", result
    assert result["diff_base"] == result["diff_base_ref"] == ""
    assert "product.py" in result["files_changed"]
