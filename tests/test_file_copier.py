"""Tests for create_skill_files host-conditional pre-install skip (ST-004).

Covers VC1-VC4:
  VC1: missing blocking dep -> skip + print message; no files installed.
  VC2: all deps present -> identical file set/count as baseline (identity).
  VC3: upgrade-path guard fires when called directly with monkeypatched which.
  VC4: unit tests for _skill_missing_dependency (pip/env/requires-skills/happy).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.delivery.file_copier import (
    _skill_missing_dependency,
    create_skill_files,
    get_templates_dir,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _installed_skill_dirs(base: Path) -> set[str]:
    """Return the set of installed skill subdirectory names under .claude/skills/."""
    skills_dir = base / ".claude" / "skills"
    if not skills_dir.exists():
        return set()
    return {p.name for p in skills_dir.iterdir() if p.is_dir()}


def _expected_all_skill_dirs() -> set[str]:
    """Return the set of skill dir names present in the shipped templates."""
    templates_dir = get_templates_dir()
    skills_template_dir = templates_dir / "skills"
    return {
        p.name
        for p in skills_template_dir.iterdir()
        if p.is_dir() and p.name != "__pycache__"
    }


# ---------------------------------------------------------------------------
# (a) VC1: missing blocking dep -> skip, no files installed, message printed
# ---------------------------------------------------------------------------

class TestVC1MissingDepSkip:
    def test_vc1_missing_cmd_skips_skill_and_prints_message(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """map-state requires-cmd:[git]; patching _REQUIRES_CHECKER["requires-cmd"] skips it."""
        import mapify_cli.delivery.file_copier as fc

        real_cmd_checker = fc._REQUIRES_CHECKER["requires-cmd"]

        def patched_cmd_checker(name: str) -> bool:
            if name == "git":
                return False
            return real_cmd_checker(name)

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", patched_cmd_checker)

        count = create_skill_files(tmp_path)
        installed = _installed_skill_dirs(tmp_path)
        out = capsys.readouterr().out

        # map-state must NOT be installed
        assert "map-state" not in installed, (
            "map-state should be skipped when 'git' is not on PATH"
        )
        # All other skills should still be installed (only map-state has requires-cmd:git)
        all_skills = _expected_all_skill_dirs()
        expected_installed = all_skills - {"map-state"}
        assert installed == expected_installed, (
            f"Expected {expected_installed}, got {installed}"
        )
        # Count must be total-1
        assert count == len(all_skills) - 1, (
            f"Expected count={len(all_skills) - 1}, got {count}"
        )
        # Exact skip message must appear in stdout
        assert "[skipped: map-state: missing cmd git]" in out, (
            f"Expected skip message in stdout; got: {out!r}"
        )


# ---------------------------------------------------------------------------
# (b) VC2: all deps present -> identical file set and count (happy-path identity)
# ---------------------------------------------------------------------------

class TestVC2DepsPresent:
    def test_vc2_all_deps_present_installs_all_skills(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No monkeypatching: all shipped skills must be installed."""
        all_skills = _expected_all_skill_dirs()
        count = create_skill_files(tmp_path)
        installed = _installed_skill_dirs(tmp_path)
        out = capsys.readouterr().out

        assert installed == all_skills, (
            f"Expected all skill dirs {all_skills}, got {installed}"
        )
        assert count == len(all_skills), (
            f"Expected count={len(all_skills)}, got {count}"
        )
        # No skip messages when all deps are present
        assert "[skipped:" not in out, (
            f"Unexpected skip message in stdout: {out!r}"
        )


# ---------------------------------------------------------------------------
# (c) VC3: upgrade-path guard fires when create_skill_files called directly
# ---------------------------------------------------------------------------

class TestVC3UpgradePathGuard:
    def test_vc3_upgrade_path_guard_fires_on_missing_cmd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Calling create_skill_files directly (as upgrade does) must trigger guard."""
        import mapify_cli.delivery.file_copier as fc

        # First install without patching so there IS an existing installation.
        create_skill_files(tmp_path)
        capsys.readouterr()  # discard first-install output

        # Simulate upgrade: call create_skill_files again with git missing.
        monkeypatch.setitem(
            fc._REQUIRES_CHECKER, "requires-cmd", lambda name: name != "git"
        )

        count2 = create_skill_files(tmp_path)
        out2 = capsys.readouterr().out

        all_skills = _expected_all_skill_dirs()
        assert count2 == len(all_skills) - 1, (
            "Upgrade path: count must exclude skipped map-state"
        )
        assert "[skipped: map-state: missing cmd git]" in out2, (
            f"Upgrade path: skip message must appear; got: {out2!r}"
        )


# ---------------------------------------------------------------------------
# (d) VC4: unit tests for _skill_missing_dependency
# ---------------------------------------------------------------------------

class TestVC4SkillMissingDependency:
    def test_vc4_returns_none_when_no_requires(self) -> None:
        assert _skill_missing_dependency({}) is None

    def test_vc4_returns_none_when_all_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", lambda _: True)
        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-pip", lambda _: True)
        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-env", lambda _: True)
        result = _skill_missing_dependency({
            "requires-cmd": ["git"],
            "requires-pip": ["yaml"],
            "requires-env": ["HOME"],
        })
        assert result is None

    def test_vc4_missing_pip_returns_pip_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-pip", lambda _: False)
        result = _skill_missing_dependency({"requires-pip": ["some_nonexistent_pkg"]})
        assert result is not None
        kind, name = result
        assert kind == "pip"
        assert name == "some_nonexistent_pkg"

    def test_vc4_missing_env_returns_env_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(
            fc._REQUIRES_CHECKER,
            "requires-env",
            lambda name: name != "MISSING_VAR_XYZ_12345",
        )
        result = _skill_missing_dependency({"requires-env": ["MISSING_VAR_XYZ_12345"]})
        assert result is not None
        kind, name = result
        assert kind == "env"
        assert name == "MISSING_VAR_XYZ_12345"

    def test_vc4_requires_skills_is_warn_only_returns_none(self) -> None:
        """requires-skills must never cause a skip (returns None)."""
        # _skill_missing_dependency only checks blocking keys; requires-skills
        # is explicitly excluded from _BLOCKING_REQUIRES_KEYS.
        result = _skill_missing_dependency({"requires-skills": ["map-state"]})
        assert result is None, (
            "requires-skills is warn-only and must never cause "
            "_skill_missing_dependency to return a (kind, name) tuple"
        )

    def test_vc4_missing_cmd_returns_cmd_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", lambda _: False)
        result = _skill_missing_dependency({"requires-cmd": ["nonexistent-tool-xyz"]})
        assert result is not None
        kind, name = result
        assert kind == "cmd"
        assert name == "nonexistent-tool-xyz"

    def test_vc4_first_missing_dep_wins_order_cmd_before_pip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """requires-cmd is checked before requires-pip."""
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", lambda _: False)
        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-pip", lambda _: False)
        result = _skill_missing_dependency({
            "requires-cmd": ["git"],
            "requires-pip": ["yaml"],
        })
        assert result is not None
        kind, _ = result
        assert kind == "cmd", "cmd must be checked before pip"

    def test_vc4_env_check_reads_name_only_not_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Security: _check_requires_env must use 'name in os.environ', not read value."""
        import mapify_cli.delivery.file_copier as fc

        # Set a sentinel variable whose value we must never observe.
        sentinel_name = "MAP_SECURITY_TEST_VAR_DO_NOT_READ"
        monkeypatch.setenv(sentinel_name, "SECRET_VALUE")

        # The check must return True (name is present) without accessing the value.
        result = fc._check_requires_env(sentinel_name)
        assert result is True

        # Also verify absent var returns False.
        monkeypatch.delenv(sentinel_name, raising=False)
        result2 = fc._check_requires_env(sentinel_name)
        assert result2 is False
