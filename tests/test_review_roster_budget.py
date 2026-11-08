"""Every scheduled reviewer of every shard fits the per-reviewer budget the planner promised (#642)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from tests.test_review_changed_scope import repo as _base_repo
from tests.test_review_changed_scope import runner, shard_manifest

repo = _base_repo
__all__ = ["repo"]

BUDGET = 260_000
CODEX_BUDGET = 560_000


def codex_rubrics():
    """The bundled role rubrics the Codex runner inlines into every normal-review prompt."""
    path = Path(runner.__file__).with_name("codex_review_runner.py")
    spec = importlib.util.spec_from_file_location("codex_review_runner_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module.ROLE_RUBRICS


def seed_near_full_shards(files=24, lines=200):
    """Many medium files so every shard is packed close to the planner capacity, plus real task artifacts."""
    directory = Path(".map/feature")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "spec_feature.md").write_text("# Spec\n" + "A requirement paragraph that is realistic.\n" * 1500)
    (directory / "task_plan_feature.md").write_text("# Plan\n" + "A planned step with detail.\n" * 1500)
    for index in range(files):
        package = Path(f"pkg_{index:02d}")
        package.mkdir(exist_ok=True)
        (package / f"module_{index:02d}.py").write_text(
            "".join(f"value_{index}_{line} = {line} * {index}  # padding text\n" for line in range(lines)))


def required_bytes(entry):
    context_id = entry["context_transport"]["context_id"]
    manifest_path = Path(".map/feature/review-context-objects") / context_id
    resources = shard_manifest(entry)["resources"]
    return manifest_path.stat().st_size + sum(item["bytes"] for item in resources.values() if item.get("required", True))


def assert_fits(built, budget, label):
    assert built["status"] == "success", (label, {k: v for k, v in built.items() if k != "prompts"})
    for role, entry in built["prompts"].items():
        size = required_bytes(entry)
        assert size <= budget, (label, role, size, budget)


def check_round(provider, arguments, monkeypatch, label):
    # Codex inlines ~240 KiB of role rubrics and the acceptance reader receives the bounded spec twice (prompt and
    # artifacts), so those rosters need a larger budget to leave room for sources.
    budget = BUDGET if provider == "claude" and "--adversarial" not in arguments else CODEX_BUDGET
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(budget))
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "40")
    # Task artifacts are lazy now, so the adversarial rosters need more source bytes to still need shards.
    seed_near_full_shards(files=48 if "--adversarial" in arguments or provider == "codex" else 24)
    admitted = runner.begin_review_run(branch="feature", provider=provider, arguments=arguments,
                                      round_id="roster", base_ref="main")
    assert admitted["status"] == "success", (label, admitted)
    assert len(admitted.get("shard_ids", [])) >= 2, (label, admitted)
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    reviewers = list(admitted["scheduled_reviewers"])
    codex = provider == "codex"
    built_any = 0
    for shard in admitted["shard_ids"]:
        if "monitor" in reviewers:
            built = runner.build_review_prompts(branch="feature", shard=shard, pack_sources=codex,
                                                role_rubrics=codex_rubrics() if codex else None)
            assert_fits(built, budget, (label, shard, "normal"))
            assert {"monitor", "predictor", "evaluator", "user_experience", "maintainer"} <= set(built["prompts"])
        else:
            built = runner.build_adversarial_review_prompts(branch="feature", reviewers=reviewers,
                                                            pack_sources=codex, shard=shard)
            assert_fits(built, budget, (label, shard, "adversarial"))
            assert set(reviewers) <= set(built["prompts"])
        built_any += 1
    assert built_any == len(admitted["shard_ids"])


def test_vc16_the_scenario_is_tight_enough_to_catch_a_small_reserve(repo, monkeypatch):
    """Negative proof: with the overhead measurement disabled and a small reserve the same shards overflow at prompt build."""
    del repo
    monkeypatch.setattr(runner, "REVIEW_CONTEXT_RESERVE_BYTES", 20_000)
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(BUDGET))
    monkeypatch.setenv("MAP_REVIEW_MAX_SHARDS", "40")
    monkeypatch.setattr(runner, "_review_fixed_overhead", lambda *_args, **_kwargs: {"total": 0, "breakdown": {}})
    # The published-view allowance is a measured safety too; the negative proof removes it with the rest.
    monkeypatch.setattr(runner, "_review_view_overhead", lambda _size: 0)
    # Added-file hunks are stubbed now; disabling that restores the duplicated bytes this scenario is sized against.
    monkeypatch.setattr(runner, "_review_stub_added_hunks", lambda diff, _stubs: diff)
    seed_near_full_shards()
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="roster", base_ref="main")
    assert admitted["status"] == "success", admitted
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    results = [runner.build_review_prompts(branch="feature", shard=shard) for shard in admitted["shard_ids"]]
    assert any(item["status"] == "error" and item["stop_reason"] == "review_context_budget_exceeded"
               for item in results), [item["status"] for item in results]


def test_vc17_unsharded_round_is_never_admitted_when_a_role_cannot_fit(repo, monkeypatch):
    del repo
    seed_near_full_shards(files=3)
    admitted_probe = runner.begin_review_run(branch="feature", provider="claude", round_id="probe", base_ref="main")
    sources = sum(runner._review_required_bytes(admitted_probe["target"], admitted_probe["required_files"]).values())
    runner.abandon_review_round("probe", reason="probe", branch="feature")
    # Old rule: sources + 64 KiB fits. Measured overhead (task artifacts, role prompts) does not.
    monkeypatch.setenv("MAP_REVIEW_CONTEXT_BUDGET_BYTES", str(sources + runner.REVIEW_CONTEXT_RESERVE_BYTES + 5_000))
    admitted = runner.begin_review_run(branch="feature", provider="claude", round_id="tight", base_ref="main")
    if admitted["status"] == "error":
        assert admitted["stop_reason"] == "review_context_budget_exceeded"
        return
    assert runner.create_review_bundle(branch="feature")["status"] == "success"
    for shard in admitted.get("shard_ids") or [""]:
        assert_fits(runner.build_review_prompts(branch="feature", shard=shard), sources + runner.REVIEW_CONTEXT_RESERVE_BYTES + 5_000,
                    ("unsharded", shard))


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("arguments", ["", "--adversarial", "--compare-orderings"])
def test_vc15_every_role_of_every_shard_fits_the_budget(repo, monkeypatch, provider, arguments):
    del repo
    check_round(provider, arguments, monkeypatch, (provider, arguments))


