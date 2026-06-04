"""Eval subprocess environment: telegram-bridge isolation (no hang on `tg listen`).

The telegram-bridge plugin's SessionStart hook injects an "always-listen — run
``tg listen``" instruction. If the eval ``claude -p`` agent obeys it, ``tg listen``
blocks on the Telegram long-poll until the dispatch timeout, and a triggered-skill
cell mis-records as a non-trigger. `_eval_subprocess_env` points ``TG_STATE_DIR``
at a config-less path inside the throwaway cwd: any ``tg listen`` / ``tg send`` the
agent runs inherits this env, finds no ``config.json``, and exits immediately
(``die``) instead of blocking — neutralising the hang without touching the
operator's real ``~/.claude/telegram`` config.
"""
from __future__ import annotations

from pathlib import Path

from mapify_cli.skills_eval.dispatcher import (
    _NO_TELEGRAM_STATE_DIRNAME,
    _eval_subprocess_env,
)


def test_env_sets_map_invoked_by_guard(tmp_path: Path) -> None:
    env = _eval_subprocess_env(tmp_path)
    assert env["MAP_INVOKED_BY"] == "skills-eval"


def test_env_points_tg_state_dir_under_cwd(tmp_path: Path) -> None:
    """TG_STATE_DIR is a path INSIDE the throwaway cwd (cleaned up with it)."""
    env = _eval_subprocess_env(tmp_path)
    tg_state = Path(env["TG_STATE_DIR"])
    assert tg_state == tmp_path / _NO_TELEGRAM_STATE_DIRNAME
    assert tmp_path in tg_state.parents


def test_tg_state_dir_has_no_config_so_tg_commands_exit_fast(tmp_path: Path) -> None:
    """The telegram gate is ``config.json`` presence; our dir must lack it.

    ``tg.py`` does ``if not os.path.exists(STATE_DIR/config.json): die()`` -> any
    ``tg listen`` / ``tg send`` the eval agent runs exits immediately instead of
    blocking on the Telegram long-poll.
    """
    env = _eval_subprocess_env(tmp_path)
    tg_state = Path(env["TG_STATE_DIR"])
    assert not (tg_state / "config.json").exists()


def test_env_preserves_inherited_environment(tmp_path: Path, monkeypatch) -> None:
    """The override is additive — existing env (e.g. PATH) is preserved."""
    monkeypatch.setenv("SOME_EXISTING_VAR", "keepme")
    env = _eval_subprocess_env(tmp_path)
    assert env.get("SOME_EXISTING_VAR") == "keepme"
    assert "PATH" in env


def test_env_does_not_mutate_real_tg_state_dir(tmp_path: Path, monkeypatch) -> None:
    """The operator's real TG_STATE_DIR (if set) is overridden ONLY in the returned
    dict for the subprocess — os.environ itself is not mutated."""
    monkeypatch.setenv("TG_STATE_DIR", "/real/operator/telegram")
    import os

    env = _eval_subprocess_env(tmp_path)
    assert env["TG_STATE_DIR"] == str(tmp_path / _NO_TELEGRAM_STATE_DIRNAME)
    # The process-wide environ is untouched.
    assert os.environ["TG_STATE_DIR"] == "/real/operator/telegram"
