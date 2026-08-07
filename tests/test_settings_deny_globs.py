"""Regression tests for settings.json deny-glob patterns (issue #397).

Verifies that the permission deny rules in the shipped settings.json template
scope secret/credentials globs by file extension, so that source files whose
names contain 'secret' or 'credentials' as a substring are NOT blocked by
the native Claude Code permission layer.

The safety-guardrails.py hook provides a separate, more nuanced layer that
handles these same concerns with safe-path-prefix allowlisting; these tests
guard only the coarser settings.json deny-glob layer.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Both copies must be tested — .claude/ is the dev copy, templates/ is what ships.
SETTINGS_FILES = [
    REPO_ROOT / ".claude" / "settings.json",
    REPO_ROOT / "src" / "mapify_cli" / "templates" / "settings.json",
]
SETTINGS_IDS = [str(p.relative_to(REPO_ROOT)) for p in SETTINGS_FILES]


def _edit_deny_globs(settings_path: Path) -> list[str]:
    """Return the glob strings from every Edit(...) deny rule in settings.json."""
    data = json.loads(settings_path.read_text())
    deny_rules: list[str] = data.get("permissions", {}).get("deny", [])
    globs: list[str] = []
    for rule in deny_rules:
        if rule.startswith("Edit(") and rule.endswith(")"):
            globs.append(rule[5:-1])
    return globs


def _write_deny_globs(settings_path: Path) -> list[str]:
    """Return the glob strings from every Write(...) deny rule in settings.json."""
    data = json.loads(settings_path.read_text())
    deny_rules: list[str] = data.get("permissions", {}).get("deny", [])
    globs: list[str] = []
    for rule in deny_rules:
        if rule.startswith("Write(") and rule.endswith(")"):
            globs.append(rule[6:-1])
    return globs


def _multiedit_deny_globs(settings_path: Path) -> list[str]:
    """Return the glob strings from every MultiEdit(...) deny rule in settings.json."""
    data = json.loads(settings_path.read_text())
    deny_rules: list[str] = data.get("permissions", {}).get("deny", [])
    globs: list[str] = []
    for rule in deny_rules:
        if rule.startswith("MultiEdit(") and rule.endswith(")"):
            globs.append(rule[10:-1])
    return globs


# ---------------------------------------------------------------------------
# Regression: broad globs must be absent (issue #397)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
def test_broad_secret_glob_absent(settings_path: Path) -> None:
    """Edit(**/*secret*) must NOT be in the deny list — it blocks source files."""
    globs = _edit_deny_globs(settings_path)
    assert "**/*secret*" not in globs, (
        f"{settings_path.relative_to(REPO_ROOT)}: "
        "broad deny glob '**/*secret*' blocks source files like "
        "secret_service.go — use extension-scoped patterns instead (issue #397)"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
def test_broad_credentials_glob_absent(settings_path: Path) -> None:
    """Edit(**/*credentials*) must NOT be in the deny list — it blocks source files."""
    globs = _edit_deny_globs(settings_path)
    assert "**/*credentials*" not in globs, (
        f"{settings_path.relative_to(REPO_ROOT)}: "
        "broad deny glob '**/*credentials*' blocks source files — "
        "use extension-scoped patterns instead (issue #397)"
    )


# ---------------------------------------------------------------------------
# Secret/credentials manifest files are still blocked (extension-scoped globs)
# ---------------------------------------------------------------------------

_BLOCKED_SECRET_FILES = [
    # Claude Code's deny globs use **/* which requires at least one path separator;
    # files at the absolute repo root (no directory) are caught by the
    # safety-guardrails.py hook instead. These are realistic in-directory paths.
    "infra/k8s/secret-store.json",
    "deploy/secret_config.yaml",
    "k8s/secrets.yaml",
    "ops/secrets.yml",
    "config/secrets.json",
    "deploy/secrets.toml",
    "envs/secrets.env",
    "manifests/my_secret.yaml",
]

_BLOCKED_CREDENTIALS_FILES = [
    "config/credentials.yaml",
    "deploy/credentials.yml",
    "secrets/credentials.json",
    "config/credentials.toml",
    "envs/credentials.env",
    "ops/aws-credentials.yaml",
    "cfg/gcp_credentials.json",
]


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_SECRET_FILES)
def test_secret_manifest_files_still_blocked(
    settings_path: Path, src_file: str
) -> None:
    """Secret manifest files (.yaml/.json/etc.) must still match a deny glob."""
    globs = _edit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: secret file {src_file!r} "
        "is no longer blocked by any Edit deny glob — check extension-scoped patterns"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_CREDENTIALS_FILES)
def test_credentials_manifest_files_still_blocked(
    settings_path: Path, src_file: str
) -> None:
    """Credential manifest files (.yaml/.json/etc.) must still match a deny glob."""
    globs = _edit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: credentials file {src_file!r} "
        "is no longer blocked by any Edit deny glob — check extension-scoped patterns"
    )


# ---------------------------------------------------------------------------
# Source code files with 'secret'/'credentials' in the name are NOT blocked
# ---------------------------------------------------------------------------

_ALLOWED_SOURCE_FILES = [
    "lockbox/internal/handler/secret_service.go",
    "secret_service_test.go",
    "secret_service_versions.go",
    "src/credentials_manager.py",
    "internal/credentials/client.go",
    "pkg/secrets_injector/main.go",
    "lib/secrets_vault.ts",
    "app/secret_store.rb",
    "credentials_provider.java",
    "src/secret_helper.rs",
]


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _ALLOWED_SOURCE_FILES)
def test_source_files_with_secret_in_name_not_blocked(
    settings_path: Path, src_file: str
) -> None:
    """Source files whose names contain 'secret'/'credentials' must not be blocked.

    Regression for issue #397: Edit(**/*secret*) blocked secret_service.go,
    secret_service_test.go, and secret_service_versions.go in a secrets-management
    service codebase — making the agent unable to edit any file with 'secret'
    in its path.
    """
    globs = _edit_deny_globs(settings_path)
    for glob_pat in globs:
        assert not fnmatch.fnmatch(src_file, glob_pat), (
            f"{settings_path.relative_to(REPO_ROOT)}: "
            f"deny glob {glob_pat!r} blocks source file {src_file!r}. "
            "Deny rules must only block secret MATERIAL files (by extension), "
            "not source code that uses 'secret' in identifiers."
        )


# ---------------------------------------------------------------------------
# .env files are blocked (both root-level and in subdirectories)
# ---------------------------------------------------------------------------

# Subdirectory .env files — blocked by Edit(**/.env*) but NOT by the old Edit(./.env*).
# Root-level .env protection comes from safety-guardrails.py, not these settings.json globs.
_BLOCKED_SUBDIRECTORY_ENV_FILES = [
    "backend/.env",
    "services/api/.env",
    "services/api/.env.local",
    "apps/web/.env.production",
    "apps/web/.env.development",
]


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("env_file", _BLOCKED_SUBDIRECTORY_ENV_FILES)
def test_subdirectory_env_files_blocked(settings_path: Path, env_file: str) -> None:
    """Subdirectory .env* files must match a deny glob.

    Regression for the bug where Edit(./.env*) only matched at the root level
    while Edit(**/.env*) was the intent — subdirectory .env files like
    backend/.env were not blocked by the settings.json layer.
    """
    globs = _edit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(env_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: .env file {env_file!r} "
        "is not blocked by any Edit deny glob — use Edit(**/.env*) not Edit(./.env*)"
    )


# ---------------------------------------------------------------------------
# Security Gap 12: Write and MultiEdit deny globs must mirror Edit globs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
def test_write_env_glob_present(settings_path: Path) -> None:
    """Write(**/.env*) must be in the deny list (security gap 12).

    Claude Code treats Edit, Write, and MultiEdit as distinct tools — a deny
    rule for Edit(...) does not block Write(...).  Before the fix only Edit
    rules covered .env files, leaving Write open.
    """
    globs = _write_deny_globs(settings_path)
    assert "**/.env*" in globs, (
        f"{settings_path.relative_to(REPO_ROOT)}: "
        "Write(**/.env*) is missing from the deny list — "
        "Claude Code treats Write as a separate tool from Edit"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
def test_multiedit_env_glob_present(settings_path: Path) -> None:
    """MultiEdit(**/.env*) must be in the deny list (security gap 12)."""
    globs = _multiedit_deny_globs(settings_path)
    assert "**/.env*" in globs, (
        f"{settings_path.relative_to(REPO_ROOT)}: "
        "MultiEdit(**/.env*) is missing from the deny list — "
        "Claude Code treats MultiEdit as a separate tool from Edit"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_SECRET_FILES)
def test_secret_manifest_files_blocked_by_write(
    settings_path: Path, src_file: str
) -> None:
    """Secret manifest files (.yaml/.json/etc.) must also be blocked by Write deny globs."""
    globs = _write_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: secret file {src_file!r} "
        "is not blocked by any Write deny glob — check extension-scoped patterns"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_SECRET_FILES)
def test_secret_manifest_files_blocked_by_multiedit(
    settings_path: Path, src_file: str
) -> None:
    """Secret manifest files (.yaml/.json/etc.) must also be blocked by MultiEdit deny globs."""
    globs = _multiedit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: secret file {src_file!r} "
        "is not blocked by any MultiEdit deny glob — check extension-scoped patterns"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_CREDENTIALS_FILES)
def test_credentials_manifest_files_blocked_by_write(
    settings_path: Path, src_file: str
) -> None:
    """Credential manifest files (.yaml/.json/etc.) must also be blocked by Write deny globs."""
    globs = _write_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: credentials file {src_file!r} "
        "is not blocked by any Write deny glob — check extension-scoped patterns"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("src_file", _BLOCKED_CREDENTIALS_FILES)
def test_credentials_manifest_files_blocked_by_multiedit(
    settings_path: Path, src_file: str
) -> None:
    """Credential manifest files (.yaml/.json/etc.) must also be blocked by MultiEdit deny globs."""
    globs = _multiedit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(src_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: credentials file {src_file!r} "
        "is not blocked by any MultiEdit deny glob — check extension-scoped patterns"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("env_file", _BLOCKED_SUBDIRECTORY_ENV_FILES)
def test_subdirectory_env_files_blocked_by_write(
    settings_path: Path, env_file: str
) -> None:
    """Subdirectory .env* files must also be blocked by Write deny globs (security gap 12)."""
    globs = _write_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(env_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: .env file {env_file!r} "
        "is not blocked by any Write deny glob"
    )


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=SETTINGS_IDS)
@pytest.mark.parametrize("env_file", _BLOCKED_SUBDIRECTORY_ENV_FILES)
def test_subdirectory_env_files_blocked_by_multiedit(
    settings_path: Path, env_file: str
) -> None:
    """Subdirectory .env* files must also be blocked by MultiEdit deny globs (security gap 12)."""
    globs = _multiedit_deny_globs(settings_path)
    matched = any(fnmatch.fnmatch(env_file, g) for g in globs)
    assert matched, (
        f"{settings_path.relative_to(REPO_ROOT)}: .env file {env_file!r} "
        "is not blocked by any MultiEdit deny glob"
    )
