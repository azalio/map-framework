"""Tests for create_skill_files host-conditional pre-install skip (ST-004).

Covers VC1-VC4:
  VC1: missing blocking dep -> skip + print message; no files installed.
  VC2: all deps present -> identical file set/count as baseline (identity).
  VC3: upgrade-path guard fires when called directly with monkeypatched which.
  VC4: unit tests for _skill_missing_dependency (pip/env/requires-skills/happy).
"""

from __future__ import annotations

import json
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

        # Deterministic: git ABSENT, every other command (incl. `claude`) PRESENT.
        # Do NOT delegate to the real checker — `claude` is absent on CI runners,
        # which would make map-memory-now skip on `claude` instead of `git` and
        # flip the skip message (env-dependent flake).
        def patched_cmd_checker(name: str) -> bool:
            return name != "git"

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", patched_cmd_checker)

        count = create_skill_files(tmp_path)
        installed = _installed_skill_dirs(tmp_path)
        out = capsys.readouterr().out

        # Both git-requiring skills must be skipped: map-state (requires-cmd:[git])
        # and map-memory-now (requires-cmd:[claude, git]).
        assert "map-state" not in installed, (
            "map-state should be skipped when 'git' is not on PATH"
        )
        assert "map-memory-now" not in installed, (
            "map-memory-now should be skipped when 'git' is not on PATH"
        )
        all_skills = _expected_all_skill_dirs()
        expected_installed = all_skills - {"map-state", "map-memory-now"}
        assert installed == expected_installed, (
            f"Expected {expected_installed}, got {installed}"
        )
        # Count must be total minus the two git-requiring skills
        assert count == len(all_skills) - 2, (
            f"Expected count={len(all_skills) - 2}, got {count}"
        )
        # Exact skip messages must appear in stdout for both skipped skills
        assert "[skipped: map-state: missing cmd git]" in out, (
            f"Expected map-state skip message in stdout; got: {out!r}"
        )
        assert "[skipped: map-memory-now: missing cmd git]" in out, (
            f"Expected map-memory-now skip message in stdout; got: {out!r}"
        )


# ---------------------------------------------------------------------------
# (b) VC2: all deps present -> identical file set and count (happy-path identity)
# ---------------------------------------------------------------------------

class TestVC2DepsPresent:
    def test_vc2_all_deps_present_installs_all_skills(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """All deps present -> every shipped skill installed (identity).

        Force every dependency checker to report present so the assertion is
        host-independent: a CI image without git on PATH must not make this
        happy-path identity test fail (map-state declares requires-cmd:[git]).
        """
        import mapify_cli.delivery.file_copier as fc

        for kind in fc._REQUIRES_CHECKER:
            monkeypatch.setitem(fc._REQUIRES_CHECKER, kind, lambda _: True)

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
        # Two skills require git (map-state, map-memory-now) -> both skipped.
        assert count2 == len(all_skills) - 2, (
            "Upgrade path: count must exclude both git-requiring skills "
            "(map-state, map-memory-now)"
        )
        assert "[skipped: map-state: missing cmd git]" in out2, (
            f"Upgrade path: map-state skip message must appear; got: {out2!r}"
        )
        assert "[skipped: map-memory-now: missing cmd git]" in out2, (
            f"Upgrade path: map-memory-now skip message must appear; got: {out2!r}"
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


# ---------------------------------------------------------------------------
# Catalog/dir consistency: a skipped skill is pruned from the installed
# skill-rules.json so the catalog never advertises an absent skill.
# ---------------------------------------------------------------------------


def _installed_catalog_skills(base: Path) -> set[str]:
    """Skill names listed in the installed .claude/skills/skill-rules.json."""
    catalog = base / ".claude" / "skills" / "skill-rules.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    return set(data.get("skills", {}).keys())


class TestCatalogConsistencyOnSkip:
    def test_skipped_skill_pruned_from_installed_catalog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """map-state skipped (git missing) must NOT remain in installed catalog."""
        import mapify_cli.delivery.file_copier as fc

        monkeypatch.setitem(
            fc._REQUIRES_CHECKER, "requires-cmd", lambda name: name != "git"
        )

        create_skill_files(tmp_path)

        installed_dirs = _installed_skill_dirs(tmp_path)
        catalog_skills = _installed_catalog_skills(tmp_path)

        assert "map-state" not in installed_dirs, "map-state dir should be skipped"
        assert "map-state" not in catalog_skills, (
            "skipped map-state must be pruned from installed skill-rules.json "
            "so the catalog matches the on-disk skill set"
        )
        # The catalog and the on-disk skill dirs must agree.
        assert catalog_skills == installed_dirs, (
            f"catalog {catalog_skills} != installed dirs {installed_dirs}"
        )

    def test_all_present_keeps_full_catalog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No skips -> installed catalog is unchanged (no pruning, no drift)."""
        import mapify_cli.delivery.file_copier as fc

        for kind in fc._REQUIRES_CHECKER:
            monkeypatch.setitem(fc._REQUIRES_CHECKER, kind, lambda _: True)

        create_skill_files(tmp_path)
        catalog_skills = _installed_catalog_skills(tmp_path)
        assert "map-state" in catalog_skills
        assert catalog_skills == _installed_skill_dirs(tmp_path)


# ---------------------------------------------------------------------------
# Robustness: a malformed catalog entry must not crash the install and must
# not silently disable the gate.
# ---------------------------------------------------------------------------

class TestMalformedCatalogRobustness:
    def test_non_dict_entry_yields_no_requirements(self) -> None:
        """A non-dict skill entry is treated as having no requirements (no crash)."""
        import mapify_cli.delivery.file_copier as fc

        assert fc._extract_requires_block("x", None) == {}
        assert fc._extract_requires_block("x", ["requires-cmd"]) == {}
        assert fc._extract_requires_block("x", "git") == {}

    def test_scalar_requires_value_is_warned_not_silently_dropped(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A typo'd scalar requires-cmd must surface a warning, not vanish silently."""
        import mapify_cli.delivery.file_copier as fc

        # "git" (a string, not ["git"]) violates SKILL_REQUIREMENTS_SCHEMA.
        block = fc._extract_requires_block("bad-skill", {"requires-cmd": "git"})
        out = capsys.readouterr().out

        # Malformed value is not enforced (not a list) ...
        assert block == {}
        # ... but it is surfaced rather than silently swallowed.
        assert "bad-skill" in out and "malformed requires-*" in out, (
            f"expected a malformed-requires warning; got: {out!r}"
        )

    def test_wellformed_block_passes_through(self) -> None:
        import mapify_cli.delivery.file_copier as fc

        block = fc._extract_requires_block(
            "ok-skill", {"requires-cmd": ["git"], "requires-skills": ["map-state"]}
        )
        # Only blocking, list-valued keys are returned; requires-skills excluded.
        assert block == {"requires-cmd": ["git"]}


# ---------------------------------------------------------------------------
# VC3 / EC-4 (ST-007): host-gate prunes map-memory-now when `claude` is absent
# ---------------------------------------------------------------------------


class TestMapMemoryNowHostGate:
    """map-memory-now requires-cmd:[claude, git]; absent claude -> skip + prune catalog."""

    def test_vc3_map_memory_now_pruned_when_claude_absent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When `claude` is not on PATH, map-memory-now must be skipped and absent
        from the installed skill-rules.json catalog."""
        import mapify_cli.delivery.file_copier as fc

        # Deterministic: `claude` ABSENT, every other command (incl. `git`) PRESENT.
        # Do NOT delegate to the real checker — git may be absent on some hosts,
        # which would make map-memory-now skip on `git` instead of `claude`.
        def no_claude(name: str) -> bool:
            return name != "claude"

        monkeypatch.setitem(fc._REQUIRES_CHECKER, "requires-cmd", no_claude)

        create_skill_files(tmp_path)
        out = capsys.readouterr().out

        installed_dirs = _installed_skill_dirs(tmp_path)
        catalog_skills = _installed_catalog_skills(tmp_path)

        assert "map-memory-now" not in installed_dirs, (
            "map-memory-now skill dir must be absent when `claude` is not on PATH"
        )
        assert "map-memory-now" not in catalog_skills, (
            "map-memory-now must be pruned from installed skill-rules.json "
            "when `claude` is absent (host-gate EC-4)"
        )
        assert "[skipped: map-memory-now: missing cmd claude]" in out, (
            f"Expected skip message for map-memory-now; got: {out!r}"
        )
        # Catalog and on-disk dirs must stay consistent.
        assert catalog_skills == installed_dirs, (
            f"catalog {catalog_skills} != installed dirs {installed_dirs}"
        )
