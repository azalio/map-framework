"""Tests for the MAP context statusline (issue #284, Phase 3).

Covers three surfaces:
  * the ``map-statusline.py`` render command (subprocess against the rendered
    ``.claude/hooks/`` copy, mock ``statusLine`` stdin);
  * ``ensure_map_statusline`` non-destructive install wiring;
  * provider integration + render placement (Claude-only, never Codex).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "map-statusline.py"
SHIPPED_HOOK = REPO_ROOT / "src" / "mapify_cli" / "templates" / "hooks" / "map-statusline.py"


def _run_statusline(payload: dict | str, cwd: Path | None = None) -> tuple[int, str]:
    """Run the statusline command with *payload* on stdin; return (rc, stdout)."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=stdin,
        text=True,
        capture_output=True,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,
        timeout=15,
    )
    return proc.returncode, proc.stdout


def _make_repo(tmp: Path, branch: str = "feature-x") -> Path:
    """Create a minimal project with a .git/HEAD pointing at *branch*."""
    project = tmp / "proj"
    (project / ".git").mkdir(parents=True)
    (project / ".git" / "HEAD").write_text(
        f"ref: refs/heads/{branch}\n", encoding="utf-8"
    )
    return project


# --------------------------------------------------------------------------- #
# Hook behavior
# --------------------------------------------------------------------------- #


def test_full_context_renders_pct_tokens_and_branch(tmp_path: Path) -> None:
    project = _make_repo(tmp_path, "feature-x")
    payload = {
        "model": {"display_name": "Opus"},
        "workspace": {"current_dir": str(project)},
        "context_window": {
            "used_percentage": 47,
            "context_window_size": 200000,
            "total_input_tokens": 94000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert out.strip() == "[Opus] MAP ctx 47% (94k/200k) · feature-x"


def test_extended_window_renders_megatokens(tmp_path: Path) -> None:
    project = _make_repo(tmp_path)
    payload = {
        "model": {"display_name": "Opus"},
        "cwd": str(project),
        "context_window": {
            "used_percentage": 12,
            "context_window_size": 1000000,
            "total_input_tokens": 120000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert "ctx 12% (120k/1.0M)" in out


def test_null_percentage_shows_dashes_not_zero(tmp_path: Path) -> None:
    # Before the first API response / right after /compact the harness sends
    # used_percentage=null. A misleading "0%" must never be shown.
    payload = {
        "model": {"display_name": "Opus"},
        "cwd": str(tmp_path),
        "context_window": {
            "used_percentage": None,
            "context_window_size": 200000,
            "total_input_tokens": 0,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert "ctx --%" in out
    assert "0%" not in out


def test_missing_window_size_uses_uncertainty_marker(tmp_path: Path) -> None:
    payload = {
        "model": {"display_name": "Opus"},
        "cwd": str(tmp_path),
        "context_window": {"used_percentage": 30, "total_input_tokens": 60000},
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    # Fallback window is biased low (200k) and marked with '?' so a guessed
    # percentage is never shown as if authoritative.
    assert "200k?" in out


def test_no_context_window_degrades_to_neutral_line(tmp_path: Path) -> None:
    project = tmp_path / "myproj"
    project.mkdir()
    payload = {"model": {"display_name": "Sonnet"}, "cwd": str(project)}
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert out.strip() == "[Sonnet] MAP · myproj"


def test_step_segment_from_step_state(tmp_path: Path) -> None:
    project = _make_repo(tmp_path, "feature-x")
    branch_dir = project / ".map" / "feature-x"
    branch_dir.mkdir(parents=True)
    (branch_dir / "step_state.json").write_text(
        json.dumps({"current_subtask_id": "ST-003", "current_step_phase": "ACTOR"}),
        encoding="utf-8",
    )
    payload = {
        "model": {"display_name": "Opus"},
        "workspace": {"current_dir": str(project)},
        "context_window": {
            "used_percentage": 5,
            "context_window_size": 200000,
            "total_input_tokens": 10000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert out.strip() == "[Opus] MAP ctx 5% (10k/200k) · feature-x · ST-003 ACTOR"


def test_worktree_git_file_pointer_resolves_branch(tmp_path: Path) -> None:
    # Linked worktree: .git is a FILE pointing at the real gitdir.
    real_git = tmp_path / "realgit"
    (real_git / "worktrees" / "wt").mkdir(parents=True)
    (real_git / "worktrees" / "wt" / "HEAD").write_text(
        "ref: refs/heads/wt-branch\n", encoding="utf-8"
    )
    project = tmp_path / "wtproj"
    project.mkdir()
    (project / ".git").write_text(
        f"gitdir: {real_git / 'worktrees' / 'wt'}\n", encoding="utf-8"
    )
    payload = {
        "model": {"display_name": "Opus"},
        "cwd": str(project),
        "context_window": {
            "used_percentage": 1,
            "context_window_size": 200000,
            "total_input_tokens": 1000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert "wt-branch" in out


def test_no_git_omits_branch_segment(tmp_path: Path) -> None:
    project = tmp_path / "nogit"
    project.mkdir()
    payload = {
        "model": {"display_name": "Opus"},
        "cwd": str(project),
        "context_window": {
            "used_percentage": 8,
            "context_window_size": 200000,
            "total_input_tokens": 16000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert out.strip() == "[Opus] MAP ctx 8% (16k/200k)"


def test_missing_model_omits_prefix(tmp_path: Path) -> None:
    payload = {
        "cwd": str(tmp_path),
        "context_window": {
            "used_percentage": 8,
            "context_window_size": 200000,
            "total_input_tokens": 16000,
        },
    }
    rc, out = _run_statusline(payload)
    assert rc == 0
    assert out.startswith("MAP ctx")


@pytest.mark.parametrize("stdin", ["", "not json", "[]", "null"])
def test_garbage_stdin_never_blank_exit_zero(stdin: str) -> None:
    rc, out = _run_statusline(stdin)
    assert rc == 0
    assert out.strip() != ""  # the status row must never go dark


def test_hook_is_executable_in_both_claude_trees() -> None:
    assert HOOK_PATH.is_file() and os.access(HOOK_PATH, os.X_OK)
    assert SHIPPED_HOOK.is_file() and os.access(SHIPPED_HOOK, os.X_OK)


def test_statusline_not_rendered_into_codex_trees() -> None:
    assert not (REPO_ROOT / ".codex" / "hooks" / "map-statusline.py").exists()
    assert not (
        REPO_ROOT / "src" / "mapify_cli" / "templates" / "codex" / "hooks"
        / "map-statusline.py"
    ).exists()


def test_statusline_exempt_from_recursion_guard_contract() -> None:
    # The statusline is a render command, not a settings.json event hook, so it
    # is intentionally exempt from the MAP_INVOKED_BY recursion-guard contract.
    import importlib.util

    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(
        "lint_hooks", REPO_ROOT / "scripts" / "lint-hooks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "map-statusline.py" in module.IGNORED_BASENAMES
    assert "map-statusline.py" not in module.REQUIRE_GUARD
    assert "map-statusline.py" not in module.FORBID_GUARD


# --------------------------------------------------------------------------- #
# ensure_map_statusline install wiring
# --------------------------------------------------------------------------- #


def _fresh_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    return project, home


def test_wires_statusline_into_settings_local_when_none_exists(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import ensure_map_statusline

    project, home = _fresh_project(tmp_path)
    result = ensure_map_statusline(project, home=home)

    assert result.wired is True
    assert result.reason == "wired"
    local = project / ".claude" / "settings.local.json"
    assert local.exists()
    data = json.loads(local.read_text())
    assert data["statusLine"]["type"] == "command"
    # The command points at the installed hook (absolute, quoted for spaces).
    assert "map-statusline.py" in data["statusLine"]["command"]
    # MAP-managed settings.json must stay free of statusLine (no drift churn).
    assert not (project / ".claude" / "settings.json").exists()


def test_idempotent_second_install_skips(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import ensure_map_statusline

    project, home = _fresh_project(tmp_path)
    ensure_map_statusline(project, home=home)
    again = ensure_map_statusline(project, home=home)
    assert again.wired is False
    assert again.reason == "existing:local"


def test_skips_when_user_global_statusline_exists(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import ensure_map_statusline

    project, home = _fresh_project(tmp_path)
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "mine"}})
    )
    result = ensure_map_statusline(project, home=home)
    assert result.wired is False
    assert result.reason == "existing:user"
    # Non-destructive: MAP wrote nothing into the project.
    assert not (project / ".claude" / "settings.local.json").exists()


def test_skips_when_project_statusline_exists(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import ensure_map_statusline

    project, home = _fresh_project(tmp_path)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "proj"}})
    )
    result = ensure_map_statusline(project, home=home)
    assert result.wired is False
    assert result.reason == "existing:project"


def test_merge_preserves_existing_local_keys(tmp_path: Path) -> None:
    from mapify_cli.delivery.file_copier import ensure_map_statusline

    project, home = _fresh_project(tmp_path)
    local = project / ".claude" / "settings.local.json"
    local.write_text(json.dumps({"permissions": {"allow": ["X"]}}))
    ensure_map_statusline(project, home=home)
    data = json.loads(local.read_text())
    assert data["permissions"] == {"allow": ["X"]}
    assert "statusLine" in data


# --------------------------------------------------------------------------- #
# Provider integration / isolation
# --------------------------------------------------------------------------- #


def test_claude_provider_wires_statusline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapify_cli.delivery.providers import ClaudeProvider

    # Isolate detection from the developer's real ~/.claude: Path.home() honours
    # $HOME on POSIX, so point it at an empty fake home with no statusLine.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    counts = ClaudeProvider().install(tmp_path)
    assert counts.get("statusline") == 1
    local = tmp_path / ".claude" / "settings.local.json"
    assert local.exists()
    assert "statusLine" in json.loads(local.read_text())


def test_codex_provider_does_not_wire_statusline(tmp_path: Path) -> None:
    from mapify_cli.delivery.providers import CodexProvider

    CodexProvider().install(tmp_path)
    # Provider isolation: Codex install never touches .claude/.
    assert not (tmp_path / ".claude" / "settings.local.json").exists()
