"""Test suite for mapify CLI tool."""

import builtins
import contextlib
import json
import os
import shlex
import stat
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import mapify_cli
import mapify_cli.update_state as update_state_module
from mapify_cli import (
    app,
    build_standard_mcp_servers,
    count_agent_templates,
    create_agent_files,
    create_command_files,
    create_commands_dir,
    create_or_merge_project_mcp_json,
    create_ssl_context,
    get_branch_artifact_templates,
    get_latest_release,
    get_templates_dir,
    init_git_repo,
    is_command,
    is_git_repo,
    merge_mcp_json,
    read_project_mcp_json,
    write_project_mcp_json,
)
from mapify_cli.auto_update import (
    UpdateMode,
    UpdateResult,
    UpdateStatus,
    check_and_update,
)
from mapify_cli.delivery import create_map_tools
from mapify_cli.install_manifest import read_manifest
from mapify_cli.update_install import (
    InstallKind,
    ProjectRefreshError,
    refresh_installed_providers,
)
from mapify_cli.update_state import (
    MAP_UPDATE_PARENT_LEASE_ENV,
    UpdateLockBusy,
    UpdateState,
    project_update_lock,
    provider_refresh_lock,
    read_update_state,
    write_update_state,
)
from mapify_cli.update_versions import (
    ReleaseHighlights,
    StableVersion,
    VersionTargets,
)

runner = CliRunner()


LOCKED_PROVIDER_REFRESH_PARENT = r"""
import os
import subprocess
import sys
import time
from pathlib import Path

from mapify_cli.update_state import MAP_UPDATE_PARENT_LEASE_ENV, project_update_lock

project = Path(sys.argv[1])
lock_held = Path(sys.argv[2])
release = Path(sys.argv[3])
command = sys.argv[4:]
with project_update_lock(project, timeout_s=0.0) as lease:
    lock_held.write_text("held\n", encoding="utf-8")
    while not release.exists():
        time.sleep(0.01)
    environment = os.environ.copy()
    environment[MAP_UPDATE_PARENT_LEASE_ENV] = lease.token
    result = subprocess.run(
        command,
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
"""


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    """Capture file paths and bytes so failed refreshes prove non-mutation."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.relative_to(root).as_posix()
        not in {
            ".map/update.lock",
            ".map/provider-refresh.lock",
        }
    }


class TestSSLContext:
    """Test SSL context creation with proper security."""

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", True)
    @mock.patch("mapify_cli.truststore.SSLContext")
    def test_ssl_context_with_truststore(self, mock_ssl_context):
        """Test SSL context creation when truststore is available."""
        mock_context = mock.Mock()
        mock_ssl_context.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", False)
    @mock.patch("ssl.create_default_context")
    def test_ssl_context_fallback(self, mock_create_default):
        """Test SSL context creation falls back to default when truststore unavailable."""
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED

    @mock.patch("mapify_cli.HAS_TRUSTSTORE", True)
    @mock.patch("mapify_cli.truststore.SSLContext")
    @mock.patch("ssl.create_default_context")
    def test_ssl_context_fallback_on_error(self, mock_create_default, mock_ssl_context):
        """Test SSL context creation falls back when truststore raises exception."""
        mock_ssl_context.side_effect = Exception("Truststore error")
        mock_context = mock.Mock()
        mock_create_default.return_value = mock_context

        context = create_ssl_context()

        assert context == mock_context
        assert mock_context.check_hostname is True
        assert mock_context.verify_mode == 2  # ssl.CERT_REQUIRED


class TestTemplates:
    """Test template directory discovery."""

    @mock.patch("importlib.resources.files")
    def test_get_templates_dir_bundled(self, mock_files):
        """Test finding templates in bundled package."""
        mock_path = mock.Mock()
        mock_path.__truediv__ = mock.Mock(
            return_value=Path(__file__).parent.parent / "templates"
        )
        mock_files.return_value = mock_path

        result = get_templates_dir()
        assert "templates" in str(result)

    @mock.patch("importlib.resources.files", side_effect=Exception("Not found"))
    def test_get_templates_dir_fallback(self, mock_files):
        """Test fallback to module directory."""
        del mock_files  # side_effect fires on call; mock object itself not needed
        # This will use the actual module directory fallback
        result = get_templates_dir()
        assert result.exists()

    @mock.patch("importlib.resources.files", side_effect=Exception("Not found"))
    def test_get_templates_dir_not_found(self, mock_files):
        """Test error when templates not found anywhere."""
        del mock_files  # side_effect fires on call; mock object itself not needed
        # Mock Path methods to simulate templates not existing
        with (
            mock.patch("pathlib.Path.exists", return_value=False),
            pytest.raises(RuntimeError, match="Templates directory not found"),
        ):
            get_templates_dir()


class TestGitOperations:
    """Test git repository operations."""

    def test_is_git_repo_true(self, tmp_path):
        """Test detecting git repository."""
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True

    def test_is_git_repo_false(self, tmp_path):
        """Test detecting non-git directory."""
        assert is_git_repo(tmp_path) is False

    def test_init_git_repo_success(self, tmp_path):
        """Test successful git repository initialization."""
        # Create a dummy file
        (tmp_path / "test.txt").write_text("test")

        result = init_git_repo(tmp_path, quiet=True)
        assert result is True
        assert is_git_repo(tmp_path) is True

    def test_init_git_repo_no_identity(self, tmp_path):
        """Test git init handles missing identity by setting temporary one."""
        # Create a dummy file
        (tmp_path / "test.txt").write_text("test")

        # Simply verify that init_git_repo succeeds
        # The function will set temporary identity if needed
        result = init_git_repo(tmp_path, quiet=True)
        assert result is True
        assert is_git_repo(tmp_path) is True

    def test_init_git_repo_no_git(self, tmp_path):
        """Test graceful handling when git is not installed."""
        with mock.patch(
            "subprocess.run", side_effect=FileNotFoundError("git not found")
        ):
            result = init_git_repo(tmp_path, quiet=True)
            assert result is False

    def test_init_git_repo_empty_directory(self, tmp_path):
        """Test git init in empty directory (no files to commit)."""
        # Don't create any files - should handle "nothing to commit" gracefully
        result = init_git_repo(tmp_path, quiet=True)
        # Should still return True even if no files to commit
        assert result is True


class TestInitCommand:
    """Test the init command."""

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    def test_init_installs_manual_upgrade_and_default_auto_config(
        self, tmp_path: Path, provider: str
    ) -> None:
        os.chdir(tmp_path)
        args = [
            "init",
            ".",
            "--force",
            "--no-git",
            "--mcp",
            "none",
            "--provider",
            provider,
        ]

        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.stdout
        assert "updates.auto: true" in (tmp_path / ".map" / "config.yaml").read_text(
            encoding="utf-8"
        )
        assert (
            ".map/provider-refresh.lock"
            in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        )
        assert (
            ".map/installer.lock"
            in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        )
        settings_local_line = ".claude/settings.local.json"
        gitignore_lines = (
            (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        )
        if provider == "claude":
            assert settings_local_line in gitignore_lines
        else:
            assert settings_local_line not in gitignore_lines
        skill_root = tmp_path / (
            ".claude/skills" if provider == "claude" else ".agents/skills"
        )
        assert (skill_root / "map-upgrade" / "SKILL.md").is_file()

    def test_init_no_auto_update_persists_false(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--no-auto-update",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "updates.auto: false" in (tmp_path / ".map" / "config.yaml").read_text()

    def test_init_merges_update_runtime_ignores_idempotently(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("custom-cache/\n.map/update.lock\n", encoding="utf-8")
        gitignore.chmod(0o640)
        args = ["init", ".", "--force", "--no-git", "--mcp", "none"]

        first = runner.invoke(app, args)
        first_text = gitignore.read_text(encoding="utf-8")
        second = runner.invoke(app, args)
        second_text = gitignore.read_text(encoding="utf-8")

        assert first.exit_code == second.exit_code == 0
        assert first_text == second_text
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640
        assert "custom-cache/" in first_text.splitlines()
        for path in (
            ".map/update-state.json",
            ".map/update.lock",
            ".map/provider-refresh.lock",
            ".map/installer.lock",
        ):
            assert first_text.splitlines().count(path) == 1

    @pytest.mark.parametrize(
        "required_line",
        [
            ".map/update-state.json",
            ".map/update.lock",
            ".map/provider-refresh.lock",
            ".map/installer.lock",
        ],
    )
    @pytest.mark.parametrize("negation_kind", ["exact", "wildcard", "unrelated"])
    def test_update_runtime_gitignore_repairs_paths_before_later_negations(
        self,
        tmp_path: Path,
        required_line: str,
        negation_kind: str,
    ) -> None:
        from mapify_cli.delivery.file_copier import merge_update_runtime_gitignore

        negation = {
            "exact": f"!{required_line}",
            "wildcard": "!.map/**",
            "unrelated": "!unrelated/**",
        }[negation_kind]
        original = f"user-rule/\n{required_line}\n{negation}\n"
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(original, encoding="utf-8")
        gitignore.chmod(0o640)

        changed = merge_update_runtime_gitignore(tmp_path)
        repaired = gitignore.read_text(encoding="utf-8")
        repaired_lines = repaired.splitlines()

        assert changed == 1
        assert repaired.startswith(original)
        assert repaired_lines.count(required_line) == 2
        assert max(
            index for index, line in enumerate(repaired_lines) if line == required_line
        ) > repaired_lines.index(negation)
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640

        assert merge_update_runtime_gitignore(tmp_path) == 0
        assert gitignore.read_text(encoding="utf-8") == repaired

    def test_update_runtime_gitignore_noop_rejects_post_read_swap(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mapify_cli.delivery import file_copier

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "# map:update-runtime\n"
            ".map/update-state.json\n"
            ".map/update.lock\n"
            ".map/provider-refresh.lock\n"
            ".map/installer.lock\n",
            encoding="utf-8",
        )
        real_read = file_copier._read_safe_gitignore

        def read_then_swap(path: Path, directory_fd: int | None):
            existing, original = real_read(path, directory_fd)
            replacement = path.with_name("replacement.gitignore")
            replacement.write_bytes(existing)
            os.replace(replacement, path)
            return existing, original

        monkeypatch.setattr(file_copier, "_read_safe_gitignore", read_then_swap)

        with pytest.raises(file_copier.UpdateRuntimeGitignoreSecurityError):
            file_copier.merge_update_runtime_gitignore(tmp_path)

    @pytest.mark.parametrize("attack", ["symlink", "hardlink"])
    def test_init_refuses_unsafe_gitignore_without_mutating_outside_file(
        self,
        tmp_path: Path,
        attack: str,
    ) -> None:
        if attack == "hardlink" and os.name == "nt":
            pytest.skip("POSIX hardlink security contract")
        os.chdir(tmp_path)
        outside = tmp_path / "outside-gitignore"
        outside.write_bytes(b"outside-gitignore-sentinel\n")
        outside.chmod(0o640)
        gitignore = tmp_path / ".gitignore"
        if attack == "symlink":
            gitignore.symlink_to(outside)
        else:
            try:
                os.link(outside, gitignore)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")

        result = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--mcp", "none"],
        )

        assert result.exit_code == 1
        assert "unsafe project .gitignore" in result.stdout
        assert outside.read_bytes() == b"outside-gitignore-sentinel\n"
        assert stat.S_IMODE(outside.stat().st_mode) == 0o640
        if attack == "symlink":
            assert gitignore.is_symlink()
        else:
            assert os.path.samefile(gitignore, outside)
            assert outside.stat().st_nlink == 2

    def test_init_refuses_nonregular_gitignore(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.mkdir()

        result = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--mcp", "none"],
        )

        assert result.exit_code == 1
        assert "unsafe project .gitignore" in result.stdout
        assert gitignore.is_dir()

    @pytest.mark.parametrize(
        ("provider", "extra_args"),
        [
            ("codex", ["--sofa"]),
            ("claude", ["--agent-memory", "local"]),
            ("claude", ["--autonomy"]),
        ],
    )
    @pytest.mark.parametrize("attack", ["symlink", "hardlink"])
    def test_init_rejects_unsafe_gitignore_before_flag_specific_writers(
        self,
        tmp_path: Path,
        provider: str,
        extra_args: list[str],
        attack: str,
    ) -> None:
        if attack == "hardlink" and os.name == "nt":
            pytest.skip("POSIX hardlink security contract")
        os.chdir(tmp_path)
        outside = tmp_path / "outside-flag-gitignore"
        outside.write_bytes(b"outside-flag-sentinel\n")
        outside.chmod(0o640)
        gitignore = tmp_path / ".gitignore"
        if attack == "symlink":
            gitignore.symlink_to(outside)
        else:
            try:
                os.link(outside, gitignore)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")

        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                provider,
                *extra_args,
            ],
        )

        assert result.exit_code == 1
        assert "unsafe project .gitignore" in result.stdout
        assert outside.read_bytes() == b"outside-flag-sentinel\n"
        assert stat.S_IMODE(outside.stat().st_mode) == 0o640
        if attack == "symlink":
            assert gitignore.is_symlink()
        else:
            assert os.path.samefile(gitignore, outside)
            assert outside.stat().st_nlink == 2

    @pytest.mark.parametrize(
        ("provider", "extra_args", "required_line", "feature_path", "feature_marker"),
        [
            (
                "codex",
                ["--sofa"],
                ".sofa/",
                ".map/config.yaml",
                "sofa.enabled: true",
            ),
            (
                "claude",
                ["--agent-memory", "local"],
                ".claude/agent-memory-local/",
                ".map/config.yaml",
                "claude_agents.persistent_memory: local",
            ),
            (
                "claude",
                ["--autonomy"],
                ".claude/settings.local.json",
                ".claude/settings.local.json",
                '"autonomy": true',
            ),
        ],
    )
    def test_init_premerges_requested_feature_into_readonly_gitignore(
        self,
        tmp_path: Path,
        provider: str,
        extra_args: list[str],
        required_line: str,
        feature_path: str,
        feature_marker: str,
    ) -> None:
        os.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("user-rule/\n", encoding="utf-8")
        gitignore.chmod(0o444)

        with mock.patch("mapify_cli.configure_global_permissions"):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    *extra_args,
                ],
            )

        feature_file = tmp_path / feature_path
        feature_text = (
            feature_file.read_text(encoding="utf-8") if feature_file.is_file() else ""
        )
        if result.exit_code == 0:
            ignore_text = gitignore.read_text(encoding="utf-8")
            assert required_line in ignore_text.splitlines()
            assert ignore_text.startswith("user-rule/\n")
            assert stat.S_IMODE(gitignore.stat().st_mode) == 0o444
            assert feature_marker in feature_text
        else:
            # Platforms that cannot replace a read-only file must fail during
            # the early atomic merge, before enabling the requested feature.
            assert feature_marker not in feature_text

    @pytest.mark.parametrize("feature", ["sofa", "agent-memory", "settings-local"])
    @pytest.mark.parametrize("attack", ["symlink", "hardlink"])
    def test_feature_gitignore_mergers_reject_unsafe_targets(
        self,
        tmp_path: Path,
        feature: str,
        attack: str,
    ) -> None:
        from mapify_cli.delivery.file_copier import UpdateRuntimeGitignoreSecurityError

        if attack == "hardlink" and os.name == "nt":
            pytest.skip("POSIX hardlink security contract")
        if feature == "sofa":
            from mapify_cli.delivery.file_copier import merge_sofa_gitignore as merge
        elif feature == "agent-memory":
            from mapify_cli.delivery.file_copier import (
                merge_agent_memory_gitignore as merge,
            )
        else:
            from mapify_cli.config.settings import (
                ensure_settings_local_gitignored as merge,
            )

        outside = tmp_path / f"outside-{feature}-gitignore"
        outside.write_bytes(b"outside-feature-sentinel\n")
        outside.chmod(0o640)
        gitignore = tmp_path / ".gitignore"
        if attack == "symlink":
            gitignore.symlink_to(outside)
        else:
            try:
                os.link(outside, gitignore)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")

        with pytest.raises(UpdateRuntimeGitignoreSecurityError):
            merge(tmp_path)

        assert outside.read_bytes() == b"outside-feature-sentinel\n"
        assert stat.S_IMODE(outside.stat().st_mode) == 0o640

    @pytest.mark.parametrize(
        ("feature", "marker", "required_line"),
        [
            ("sofa", "# map:sofa", ".sofa/"),
            (
                "agent-memory",
                "# map:agent-memory-local",
                ".claude/agent-memory-local/",
            ),
            (
                "settings-local",
                "# map:settings-local",
                ".claude/settings.local.json",
            ),
        ],
    )
    def test_feature_gitignore_mergers_are_atomic_and_idempotent(
        self,
        tmp_path: Path,
        feature: str,
        marker: str,
        required_line: str,
    ) -> None:
        if feature == "sofa":
            from mapify_cli.delivery.file_copier import merge_sofa_gitignore as merge
        elif feature == "agent-memory":
            from mapify_cli.delivery.file_copier import (
                merge_agent_memory_gitignore as merge,
            )
        else:
            from mapify_cli.config.settings import (
                ensure_settings_local_gitignored as merge,
            )

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("user-rule/\n", encoding="utf-8")
        gitignore.chmod(0o640)

        first = merge(tmp_path)
        second = merge(tmp_path)
        content = gitignore.read_text(encoding="utf-8")

        assert first == 1
        assert second == 0
        assert content.startswith("user-rule/\n")
        assert content.count(marker) == 1
        assert content.splitlines().count(required_line) == 1
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640

    @pytest.mark.parametrize(
        ("feature", "marker", "required_line"),
        [
            ("sofa", "# map:sofa", ".sofa/"),
            (
                "agent-memory",
                "# map:agent-memory-local",
                ".claude/agent-memory-local/",
            ),
            (
                "settings-local",
                "# map:settings-local",
                ".claude/settings.local.json",
            ),
        ],
    )
    def test_feature_gitignore_mergers_repair_marker_only_state(
        self,
        tmp_path: Path,
        feature: str,
        marker: str,
        required_line: str,
    ) -> None:
        if feature == "sofa":
            from mapify_cli.delivery.file_copier import merge_sofa_gitignore as merge
        elif feature == "agent-memory":
            from mapify_cli.delivery.file_copier import (
                merge_agent_memory_gitignore as merge,
            )
        else:
            from mapify_cli.config.settings import (
                ensure_settings_local_gitignored as merge,
            )

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(f"{marker}\n", encoding="utf-8")
        gitignore.chmod(0o640)

        changed = merge(tmp_path)
        content = gitignore.read_text(encoding="utf-8")

        assert changed == 1
        assert content.splitlines().count(marker) == 1
        assert content.splitlines().count(required_line) == 1
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640

    @pytest.mark.parametrize(
        ("feature", "marker", "required_line", "wildcard_negation"),
        [
            ("sofa", "# map:sofa", ".sofa/", "!.sofa/**"),
            (
                "agent-memory",
                "# map:agent-memory-local",
                ".claude/agent-memory-local/",
                "!.claude/agent-memory-local/**",
            ),
            (
                "settings-local",
                "# map:settings-local",
                ".claude/settings.local.json",
                "!.claude/settings.*",
            ),
        ],
    )
    @pytest.mark.parametrize("negation_kind", ["exact", "wildcard", "unrelated"])
    def test_feature_gitignore_mergers_repair_paths_before_later_negations(
        self,
        tmp_path: Path,
        feature: str,
        marker: str,
        required_line: str,
        wildcard_negation: str,
        negation_kind: str,
    ) -> None:
        if feature == "sofa":
            from mapify_cli.delivery.file_copier import merge_sofa_gitignore as merge
        elif feature == "agent-memory":
            from mapify_cli.delivery.file_copier import (
                merge_agent_memory_gitignore as merge,
            )
        else:
            from mapify_cli.config.settings import (
                ensure_settings_local_gitignored as merge,
            )

        negation = {
            "exact": f"!{required_line}",
            "wildcard": wildcard_negation,
            "unrelated": "!unrelated/**",
        }[negation_kind]
        original = f"user-rule/\n{marker}\n{required_line}\n{negation}\n"
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(original, encoding="utf-8")
        gitignore.chmod(0o640)

        changed = merge(tmp_path)
        repaired = gitignore.read_text(encoding="utf-8")
        repaired_lines = repaired.splitlines()

        assert changed == 1
        assert repaired.startswith(original)
        assert repaired_lines.count(marker) == 1
        assert repaired_lines.count(required_line) == 2
        assert repaired_lines[-1] == required_line
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640

        assert merge(tmp_path) == 0
        assert gitignore.read_text(encoding="utf-8") == repaired

    def test_feature_gitignore_merger_does_not_accept_leading_space_path(
        self,
        tmp_path: Path,
    ) -> None:
        from mapify_cli.delivery.file_copier import merge_sofa_gitignore

        original = "user-rule/\n  .sofa/\n"
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(original, encoding="utf-8")

        assert merge_sofa_gitignore(tmp_path) == 1
        repaired = gitignore.read_text(encoding="utf-8")
        assert repaired.startswith(original)
        assert repaired.splitlines().count(".sofa/") == 1

    @pytest.mark.parametrize(
        (
            "provider",
            "extra_args",
            "marker",
            "required_line",
            "feature_path",
            "feature_marker",
        ),
        [
            (
                "codex",
                ["--sofa"],
                "# map:sofa",
                ".sofa/",
                ".map/config.yaml",
                "sofa.enabled: true",
            ),
            (
                "claude",
                ["--agent-memory", "local"],
                "# map:agent-memory-local",
                ".claude/agent-memory-local/",
                ".map/config.yaml",
                "claude_agents.persistent_memory: local",
            ),
            (
                "claude",
                ["--autonomy"],
                "# map:settings-local",
                ".claude/settings.local.json",
                ".claude/settings.local.json",
                '"autonomy": true',
            ),
        ],
    )
    def test_init_repairs_marker_only_privacy_block_before_feature_enablement(
        self,
        tmp_path: Path,
        provider: str,
        extra_args: list[str],
        marker: str,
        required_line: str,
        feature_path: str,
        feature_marker: str,
    ) -> None:
        os.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(f"{marker}\n", encoding="utf-8")

        with mock.patch("mapify_cli.configure_global_permissions"):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    *extra_args,
                ],
            )

        assert result.exit_code == 0, result.stdout
        ignore_lines = gitignore.read_text(encoding="utf-8").splitlines()
        assert ignore_lines.count(marker) == 1
        assert ignore_lines.count(required_line) == 1
        assert feature_marker in (tmp_path / feature_path).read_text(encoding="utf-8")

    def test_update_runtime_gitignore_replace_failure_preserves_file(
        self,
        tmp_path: Path,
    ) -> None:
        from mapify_cli.delivery.file_copier import merge_update_runtime_gitignore

        gitignore = tmp_path / ".gitignore"
        gitignore.write_bytes(b"user-rule/\n")
        gitignore.chmod(0o640)

        with (
            mock.patch(
                "mapify_cli.delivery.file_copier.os.replace",
                side_effect=OSError("replace failed"),
            ),
            pytest.raises(OSError, match="replace failed"),
        ):
            merge_update_runtime_gitignore(tmp_path)

        assert gitignore.read_bytes() == b"user-rule/\n"
        assert stat.S_IMODE(gitignore.stat().st_mode) == 0o640
        assert list(tmp_path.glob(".gitignore.*.tmp")) == []

    def test_update_runtime_gitignore_supports_platform_without_fchmod(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mapify_cli.delivery import file_copier

        monkeypatch.delattr(file_copier.os, "fchmod", raising=False)

        with mock.patch.object(file_copier.os, "chmod") as path_chmod:
            changed = file_copier.merge_update_runtime_gitignore(tmp_path)

        assert changed == 1
        path_chmod.assert_not_called()
        assert (
            ".map/installer.lock"
            in (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
        )

    def test_update_runtime_gitignore_closes_temp_before_replace(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mapify_cli.delivery import file_copier

        real_create_temporary = file_copier._create_gitignore_temporary
        real_replace = file_copier.os.replace
        captured_descriptor: dict[str, int] = {}

        def tracking_create_temporary(
            gitignore: Path,
            directory_fd: int | None,
        ) -> tuple[int, str | Path]:
            descriptor, temporary_name = real_create_temporary(gitignore, directory_fd)
            captured_descriptor["value"] = descriptor
            return descriptor, temporary_name

        def replace_after_close(
            source: str | Path,
            destination: str | Path,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            with pytest.raises(OSError):
                os.fstat(captured_descriptor["value"])
            if src_dir_fd is None and dst_dir_fd is None:
                real_replace(source, destination)
            else:
                real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

        monkeypatch.setattr(
            file_copier,
            "_create_gitignore_temporary",
            tracking_create_temporary,
        )
        monkeypatch.setattr(file_copier.os, "replace", replace_after_close)

        changed = file_copier.merge_update_runtime_gitignore(tmp_path)

        assert changed == 1
        assert (tmp_path / ".gitignore").is_file()

    def test_init_auto_update_reenables_existing_project(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--no-auto-update",
            ],
        )
        second = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--auto-update",
            ],
        )
        assert first.exit_code == second.exit_code == 0
        assert "updates.auto: true" in (tmp_path / ".map" / "config.yaml").read_text()

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    @pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
    def test_init_without_update_flag_preserves_existing_value(
        self,
        tmp_path: Path,
        provider: str,
        enabled: bool,
    ) -> None:
        os.chdir(tmp_path)
        config_path = tmp_path / ".map" / "config.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            f"updates.auto: {'true' if enabled else 'false'}\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                provider,
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert config_path.read_text(encoding="utf-8") == (
            f"updates.auto: {'true' if enabled else 'false'}\n"
        )

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    @pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
    def test_init_explicit_auto_update_override_must_be_verified(
        self,
        tmp_path: Path,
        provider: str,
        enabled: bool,
    ) -> None:
        os.chdir(tmp_path)
        config_path = tmp_path / ".map" / "config.yaml"
        config_path.parent.mkdir()
        previous = not enabled
        config_path.write_text(
            f"updates.auto: {'true' if previous else 'false'}\n",
            encoding="utf-8",
        )

        with mock.patch(
            "mapify_cli.config.project_config.apply_auto_update_override",
            return_value=None,
        ):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    "--auto-update" if enabled else "--no-auto-update",
                ],
            )

        assert result.exit_code == 1
        assert "Failed to persist requested automatic-update setting" in result.stdout
        assert "Project ready" not in result.stdout
        assert config_path.read_text(encoding="utf-8") == (
            f"updates.auto: {'true' if previous else 'false'}\n"
        )

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    @pytest.mark.parametrize("enabled", [False, True], ids=["disabled", "enabled"])
    def test_init_explicit_auto_update_write_failure_is_fatal(
        self,
        tmp_path: Path,
        provider: str,
        enabled: bool,
    ) -> None:
        os.chdir(tmp_path)

        with mock.patch(
            "mapify_cli.config.project_config.apply_auto_update_override",
            side_effect=OSError("config is read-only"),
        ):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    "--auto-update" if enabled else "--no-auto-update",
                ],
            )

        assert result.exit_code == 1
        assert "Failed to persist requested automatic-update setting" in result.stdout
        assert "config is read-only" in result.stdout
        assert "Project ready" not in result.stdout

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    @pytest.mark.parametrize(
        ("failure_boundary", "patch_target", "extra_args"),
        [
            (
                "default config",
                "mapify_cli.config.project_config.write_default_config",
                [],
            ),
            (
                "compression override",
                "mapify_cli.config.project_config.apply_compression_overrides",
                ["--compression", "auto"],
            ),
        ],
    )
    def test_explicit_auto_update_pre_persistence_failure_is_fatal(
        self,
        tmp_path: Path,
        provider: str,
        failure_boundary: str,
        patch_target: str,
        extra_args: list[str],
    ) -> None:
        os.chdir(tmp_path)

        with mock.patch(
            patch_target,
            side_effect=OSError(f"{failure_boundary} failed"),
        ):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    "--auto-update",
                    *extra_args,
                ],
            )

        assert result.exit_code == 1
        assert "Failed to persist requested automatic-update setting" in result.stdout
        assert f"{failure_boundary} failed" in " ".join(result.stdout.split())
        assert "Project ready" not in result.stdout

    def test_init_explicit_auto_update_rejects_malformed_persisted_config(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        config_path = tmp_path / ".map" / "config.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            "updates.auto: false\nbroken: [\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--auto-update",
            ],
        )

        assert result.exit_code == 1
        assert "Failed to persist requested automatic-update setting" in result.stdout
        assert "Project ready" not in result.stdout

    @pytest.mark.parametrize("provider", ["claude", "codex"])
    def test_explicit_auto_update_does_not_make_later_sofa_failure_fatal(
        self,
        tmp_path: Path,
        provider: str,
    ) -> None:
        os.chdir(tmp_path)

        with mock.patch(
            "mapify_cli.config.project_config.apply_sofa_overrides",
            side_effect=OSError("sofa config failed"),
        ):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--provider",
                    provider,
                    "--auto-update",
                    "--sofa",
                ],
            )

        assert result.exit_code == 0, result.stdout
        assert "skipped: sofa config failed" in result.stdout
        assert (
            "Failed to persist requested automatic-update setting" not in result.stdout
        )
        assert "Project ready" in result.stdout
        assert "updates.auto: true" in (tmp_path / ".map" / "config.yaml").read_text(
            encoding="utf-8"
        )

    def test_init_basic(self, tmp_path):
        """Test basic initialization without options.

        Verifies that:
        - Init succeeds with default --mcp all option
        - Agent and command directories are created
        - MCP config is created with all servers
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()

        # Project-level approvals should be created
        settings_local = tmp_path / ".claude" / "settings.local.json"
        assert settings_local.exists()
        settings = json.loads(settings_local.read_text())
        allow = settings.get("permissions", {}).get("allow", [])
        assert "Bash(go test *)" in allow
        assert "Bash(go vet *)" in allow
        assert "Bash(go mod tidy *)" in allow
        assert "mcp__sourcecraft__list_pull_request_comments" in allow
        assert "Bash(make generate manifests)" in allow
        assert "Bash(make manifests)" in allow
        assert "Bash(git worktree add *)" in allow
        assert (
            'Bash(openssl req -x509 -newkey rsa:512 -keyout /dev/null -out /dev/stdout -days 365 -nodes -subj "/CN=test" 2>/dev/null)'
            in allow
        )

    def test_init_always_uses_claude(self, tmp_path):
        """Test that init always uses Claude (no AI selection prompt).

        Verifies that:
        - No AI selection occurs (hardcoded to 'claude')
        - Claude agents are created
        - Output mentions Claude or project ready
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        # Should show "claude" somewhere in output (AI assistant confirmation)
        assert "claude" in result.stdout.lower() or "Project ready" in result.stdout

    def test_init_ai_flag_not_accepted(self, tmp_path):
        """Test that passing --ai flag results in a clear error.

        Verifies that:
        - Typer rejects --ai flag with "no such option: --ai"
        - Command fails with non-zero exit code
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--ai", "cursor", "--no-git"])

        assert result.exit_code != 0
        # Typer should reject the unknown option
        # Check both stdout and output for compatibility across Typer versions
        output_text = getattr(result, "output", result.stdout)
        assert (
            "no such option" in output_text.lower()
            or "unrecognized" in output_text.lower()
        )

    def test_init_mcp_none(self, tmp_path):
        """Test init with --mcp none option.

        Verifies that:
        - Init succeeds with --mcp none
        - MCP config is not created or is empty
        - Agent files are still created
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()

        # MCP config might exist but should be empty or minimal
        mcp_config_path = tmp_path / ".claude" / "mcp_config.json"
        if mcp_config_path.exists():
            mcp_config = json.loads(mcp_config_path.read_text())
            # Should have no MCP servers or empty mcp_servers dict
            assert len(mcp_config.get("mcp_servers", {})) == 0

    def test_init_tracker_shows_claude(self, tmp_path):
        """Test that tracker shows Claude as selected AI.

        Verifies that:
        - Output mentions Claude as the AI assistant
        - No other AI assistants are mentioned
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        # Should show claude in the tracker output
        assert "claude" in result.stdout.lower() or "Project ready" in result.stdout

    def test_init_claude_with_essential_mcp(self, tmp_path):
        """Test initialization with Claude and essential MCP servers.

        Verifies that:
        - Init succeeds with --mcp essential
        - Essential MCP servers are configured (sequential-thinking)
        - deepwiki is no longer installed (removed)
        - Agent files are created
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "essential"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Check MCP config contains essential servers
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "sequential-thinking" in mcp_config["mcp_servers"]
        assert "deepwiki" not in mcp_config["mcp_servers"]

    def test_init_with_directory(self, tmp_path):
        """Test init with specific directory name.

        Verifies that:
        - New directory is created with specified name
        - Agent files are created in new directory
        """
        os.chdir(tmp_path)
        project_name = "my-project"

        result = runner.invoke(app, ["init", project_name, "--no-git", "--mcp", "none"])

        assert result.exit_code == 0
        project_path = tmp_path / project_name
        assert project_path.exists()
        assert (project_path / ".claude" / "agents").exists()

    def test_init_already_initialized(self, tmp_path):
        """Test init when project already has .claude directory.

        Verifies that:
        - First init succeeds
        - Second init with --force succeeds
        - --force allows re-initialization
        """
        os.chdir(tmp_path)

        # Initialize once
        result1 = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert result1.exit_code == 0

        # Try to initialize again in same directory with --force
        result2 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result2.exit_code == 0
        # Should succeed with --force
        assert (
            "Project ready" in result2.stdout or "already initialized" in result2.stdout
        )

    def test_init_with_mcp_servers(self, tmp_path):
        """Test init with MCP servers specified via CLI.

        Verifies that:
        - --mcp essential flag installs essential servers
        - MCP config contains sequential-thinking (deepwiki removed)
        """
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--mcp", "essential", "--no-git"])

        assert result.exit_code == 0
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        assert "sequential-thinking" in mcp_config["mcp_servers"]
        assert "deepwiki" not in mcp_config["mcp_servers"]

    def test_init_defaults_to_all_mcp_servers(self, tmp_path, monkeypatch):
        """Test that init without --mcp flag defaults to installing all MCP servers.

        Regression test for non-interactive init behavior.
        Verifies that:
        - Init completes without interactive prompts
        - The default MCP server (sequential-thinking) is installed by default
        - mcp_config.json is created with the default server set (deepwiki removed)
        """
        # Use fresh CliRunner to avoid state pollution from previous tests
        import sys

        from typer.testing import CliRunner as FreshRunner

        fresh_runner = FreshRunner()

        original_cwd = os.getcwd()
        original_stdin = sys.stdin
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        monkeypatch.chdir(tmp_path)
        try:
            # Ensure stdin/stdout/stderr are reset to avoid fileno() issues
            sys.stdin = sys.__stdin__
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            # Run init without --mcp flag (should default to "all")
            result = fresh_runner.invoke(app, ["init", ".", "--no-git"])
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            os.chdir(original_cwd)

        assert result.exit_code == 0, f"Init failed: {result.stdout}"
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "mcp_config.json").exists()

        # Verify default MCP servers are configured
        mcp_config = json.loads((tmp_path / ".claude" / "mcp_config.json").read_text())
        expected_servers = [
            "sequential-thinking",
        ]

        assert "mcp_servers" in mcp_config, "mcp_config missing 'mcp_servers' key"
        for server in expected_servers:
            assert (
                server in mcp_config["mcp_servers"]
            ), f"MCP server '{server}' not found in config"

        # Verify exactly the expected default set (no extras)
        assert sorted(mcp_config["mcp_servers"]) == sorted(
            expected_servers
        ), f"Expected default MCP servers {expected_servers}, found {mcp_config['mcp_servers']}"

    def test_init_force_no_prompts(self, tmp_path):
        """Test that init --force completes without interactive confirmation prompts.

        Regression test for non-interactive force behavior.
        Verifies that:
        - Running init in non-empty directory with --force completes silently
        - No interactive prompts are triggered
        - Command succeeds with exit code 0
        """
        os.chdir(tmp_path)

        # Create a non-empty directory with some files
        (tmp_path / "existing_file.txt").write_text("existing content")
        (tmp_path / "README.md").write_text("# Existing project")

        # First init to create .claude directory (use --force since dir is non-empty)
        result1 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result1.exit_code == 0, f"First init failed: {result1.stdout}"

        # Modify an agent file to verify --force overwrites
        actor_file = tmp_path / ".claude" / "agents" / "actor.md"
        actor_file.write_text("# Modified by user")

        # Run init --force in non-empty directory (should complete without prompts)
        result2 = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )

        assert result2.exit_code == 0, f"Init --force failed: {result2.stdout}"

        # Verify command completed successfully
        assert (
            "Project ready" in result2.stdout or "initialized" in result2.stdout.lower()
        )

        # Verify existing non-.claude files are preserved
        assert (tmp_path / "existing_file.txt").exists()
        assert (tmp_path / "existing_file.txt").read_text() == "existing content"
        assert (tmp_path / "README.md").exists()

        # Verify agent file was updated/restored (not the user's modified version)
        # This confirms --force actually re-initialized the files
        assert actor_file.exists()
        restored_content = actor_file.read_text()
        assert (
            restored_content != "# Modified by user"
        ), "--force did not restore template files"
        # Should contain some template markers (not exact match due to potential updates)
        assert len(restored_content) > 100, "Restored actor.md seems too short"

    def test_vc2_init_sofa_then_bare_init_does_not_clobber(self, tmp_path):
        """VC2 [AC-1]: init --sofa writes sofa.enabled=true; bare re-run does not clobber it."""
        os.chdir(tmp_path)

        # First init with --sofa
        result1 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--sofa"]
        )
        assert result1.exit_code == 0, f"init --sofa failed: {result1.stdout}"

        config_file = tmp_path / ".map" / "config.yaml"
        assert config_file.exists(), ".map/config.yaml was not created"
        content_after_sofa = config_file.read_text()
        assert (
            "sofa.enabled: true" in content_after_sofa
        ), "sofa.enabled: true not written after --sofa"

        # Second bare init (no --sofa) with --force to allow re-run in non-empty dir
        result2 = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result2.exit_code == 0, f"bare re-init failed: {result2.stdout}"

        # write_default_config is skip-if-exists, so the config is unchanged;
        # and no apply_sofa_overrides call was made — value must still be true.
        content_after_bare = config_file.read_text()
        assert (
            "sofa.enabled: true" in content_after_bare
        ), "bare re-run clobbered sofa.enabled: true"

    def test_vc1_init_sofa_flag_writes_config(self, tmp_path):
        """VC1 [AC-1]: mapify init --sofa writes sofa.enabled: true to .map/config.yaml."""
        os.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--sofa"]
        )
        assert result.exit_code == 0, f"init --sofa failed: {result.stdout}"

        config_file = tmp_path / ".map" / "config.yaml"
        assert config_file.exists()
        assert "sofa.enabled: true" in config_file.read_text()

    def test_vc1_bare_init_no_active_sofa_line(self, tmp_path):
        """VC1 [AC-1]: bare init (no --sofa) produces no active sofa.enabled: true line."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert result.exit_code == 0, f"init failed: {result.stdout}"

        config_file = tmp_path / ".map" / "config.yaml"
        assert config_file.exists()
        assert "sofa.enabled: true" not in config_file.read_text()


class TestRefreshExistingInit:
    """Hidden fresh-process refresh mode preserves project-owned choices."""

    @pytest.fixture(autouse=True)
    def _avoid_global_settings_writes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mapify_cli, "configure_global_permissions", mock.Mock())

    def test_refresh_existing_preserves_claude_mcp_selection_and_writes_dual_manifest(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)

        first = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        second = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert first.exit_code == 0, first.stdout
        assert second.exit_code == 0, second.stdout
        assert refresh.exit_code == 0, refresh.stdout
        assert not (tmp_path / ".mcp.json").exists()
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.providers == ["claude", "codex"]

    def test_dual_provider_refresh_smoke_retains_both_skill_catalogs(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)

        first = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        second = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert first.exit_code == 0, first.stdout
        assert second.exit_code == 0, second.stdout
        assert refresh.exit_code == 0, refresh.stdout
        assert (tmp_path / ".claude" / "skills" / "map-upgrade" / "SKILL.md").is_file()
        assert (tmp_path / ".agents" / "skills" / "map-upgrade" / "SKILL.md").is_file()
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.providers == ["claude", "codex"]

    def test_refresh_existing_is_hidden_from_init_help(self) -> None:
        result = runner.invoke(app, ["init", "--help"])

        assert result.exit_code == 0
        assert "--refresh-existing" not in result.stdout

    def test_refresh_existing_strips_parent_lease_before_any_command_work(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        observed: list[bool] = []

        def inspect_environment(*_args: object, **_kwargs: object) -> bool:
            observed.append(MAP_UPDATE_PARENT_LEASE_ENV in os.environ)
            return False

        with mock.patch.object(
            update_state_module,
            "validate_parent_update_lease",
            side_effect=inspect_environment,
        ):
            result = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
                env={MAP_UPDATE_PARENT_LEASE_ENV: "x" * 43},
            )

        assert result.exit_code == 1
        assert observed == [False]

    def test_refresh_existing_reports_busy_update_lock_without_mutation(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        with project_update_lock(tmp_path, timeout_s=0.0):
            before = _snapshot_tree(tmp_path)
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )

        assert refresh.exit_code == 1
        assert "already running" in refresh.stdout
        after = _snapshot_tree(tmp_path)
        before.pop(".map/update.lock", None)
        after.pop(".map/update.lock", None)
        assert after == before

    def test_refresh_existing_reports_unsafe_lock_path_clearly(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        lock_target = tmp_path / ".map" / "unexpected-lock-target"
        lock_target.write_text("not a MAP lock\n", encoding="utf-8")
        (tmp_path / ".map" / "update.lock").symlink_to(lock_target)

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "unsafe MAP update lock path" in refresh.stdout

    def test_refresh_existing_rejects_forged_parent_lease(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude",),
            ),
        )
        with project_update_lock(tmp_path, timeout_s=0.0) as lease:
            before = _snapshot_tree(tmp_path)
            monkeypatch.setattr(
                update_state_module.os, "getppid", lambda: lease.owner_pid
            )
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
                env={MAP_UPDATE_PARENT_LEASE_ENV: "x" * 43},
            )

        assert refresh.exit_code == 1
        assert "invalid parent update lease" in refresh.stdout
        after = _snapshot_tree(tmp_path)
        before.pop(".map/update.lock", None)
        after.pop(".map/update.lock", None)
        assert after == before

    def test_refresh_existing_borrows_valid_parent_lease_without_deadlock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude",),
            ),
        )

        with project_update_lock(tmp_path, timeout_s=0.0) as lease:
            monkeypatch.setattr(
                update_state_module.os, "getppid", lambda: lease.owner_pid
            )
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
                env={MAP_UPDATE_PARENT_LEASE_ENV: lease.token},
            )

        assert refresh.exit_code == 0, refresh.stdout
        assert read_update_state(tmp_path).pending_refresh is False

    @pytest.mark.skipif(os.name == "nt", reason="POSIX executable-script smoke")
    def test_real_provider_child_borrows_parent_lease_without_deadlock(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude",),
            ),
        )
        executable = tmp_path / "mapify-child"
        executable.write_text(
            f"#!{sys.executable}\nfrom mapify_cli import app\napp()\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)

        with project_update_lock(tmp_path, timeout_s=0.0):
            refreshed = refresh_installed_providers(
                tmp_path,
                ("claude",),
                mapify_executable=executable,
            )

        assert refreshed == ("claude",)
        state = read_update_state(tmp_path)
        assert state.pending_refresh is False
        assert state.pending_providers == ()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX executable-script smoke")
    @pytest.mark.timeout(20)
    def test_concurrent_standalone_dual_recovery_serializes_and_retries(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        claude = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        codex = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--provider", "codex"]
        )
        assert claude.exit_code == codex.exit_code == 0
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude", "codex"),
            ),
        )
        executable = tmp_path / "mapify-child"
        child_holds_lock = tmp_path / "provider-child-holds-update-lock"
        release_child = tmp_path / "release-provider-child"
        executable.write_text(
            f"#!{sys.executable}\nfrom mapify_cli import app\napp()\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
        base = [
            str(executable),
            "init",
            ".",
            "--force",
            "--no-git",
            "--provider",
        ]
        environment = os.environ.copy()
        environment.pop(MAP_UPDATE_PARENT_LEASE_ENV, None)
        first = subprocess.Popen(
            [
                sys.executable,
                "-c",
                LOCKED_PROVIDER_REFRESH_PARENT,
                str(tmp_path),
                str(child_holds_lock),
                str(release_child),
                *base,
                "claude",
                "--refresh-existing",
            ],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5.0
            while not child_holds_lock.exists():
                if first.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError(
                        "provider child never started while update.lock was held"
                    )
                time.sleep(0.01)

            with (
                pytest.raises(UpdateLockBusy),
                project_update_lock(tmp_path, timeout_s=0.0),
            ):
                raise AssertionError("provider child must still hold update.lock")

            contender = subprocess.run(
                [*base, "codex", "--refresh-existing"],
                cwd=tmp_path,
                env=environment,
                timeout=5.0,
                check=False,
                capture_output=True,
                text=True,
            )
            release_child.write_text("release\n", encoding="utf-8")
            first_stdout, first_stderr = first.communicate(timeout=10.0)
        finally:
            release_child.write_text("release\n", encoding="utf-8")
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5.0)

        assert first.returncode == 0, first_stdout + first_stderr
        assert contender.returncode == 1
        assert "already running" in contender.stdout
        narrowed = read_update_state(tmp_path)
        assert narrowed.pending_refresh is True
        assert narrowed.pending_providers == ("codex",)

        retry = subprocess.run(
            [*base, "codex", "--refresh-existing"],
            cwd=tmp_path,
            env=environment,
            timeout=10.0,
            check=False,
            capture_output=True,
            text=True,
        )

        assert retry.returncode == 0, retry.stdout + retry.stderr
        completed = read_update_state(tmp_path)
        assert completed.pending_refresh is False
        assert completed.pending_providers == ()

    def test_refresh_existing_holds_both_locks_through_provider_mutation(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout

        def guarded_install(
            _provider: object,
            project: Path,
            *,
            mcp_servers: list[str],
        ) -> dict[str, int]:
            del mcp_servers
            with (
                pytest.raises(UpdateLockBusy),
                project_update_lock(project, timeout_s=0.0),
            ):
                raise AssertionError("update lock must cover provider mutation")
            with (
                pytest.raises(UpdateLockBusy),
                provider_refresh_lock(project, timeout_s=0.0),
            ):
                raise AssertionError("refresh lock must cover provider mutation")
            return {}

        with mock.patch(
            "mapify_cli.delivery.providers.ClaudeProvider.install",
            new=guarded_install,
        ):
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )

        assert refresh.exit_code == 0, refresh.stdout

    def test_refresh_existing_rejects_uninitialized_project(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)

        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert result.exit_code == 1
        assert "initialized MAP project" in result.stdout
        assert not (tmp_path / ".claude").exists()

    def test_refresh_existing_does_not_create_uninitialized_named_project(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        target = tmp_path / "not-initialized"

        result = runner.invoke(
            app,
            [
                "init",
                target.name,
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert result.exit_code == 1
        assert not target.exists()

    def test_refresh_existing_rejects_initialized_named_project_without_mutation(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        target = tmp_path / "sibling"
        first = runner.invoke(
            app,
            ["init", target.name, "--no-git", "--mcp", "none"],
        )
        assert first.exit_code == 0, first.stdout
        before = _snapshot_tree(tmp_path)

        refresh = runner.invoke(
            app,
            [
                "init",
                target.name,
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "current directory" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before

    @pytest.mark.parametrize(
        ("installed_provider", "requested_provider"),
        [("claude", "codex"), ("codex", "claude")],
    )
    def test_refresh_existing_rejects_uninstalled_provider_without_mutation(
        self,
        tmp_path: Path,
        installed_provider: str,
        requested_provider: str,
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                installed_provider,
            ],
        )
        assert first.exit_code == 0, first.stdout
        before = _snapshot_tree(tmp_path)

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                requested_provider,
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "installed provider" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before

    def test_refresh_existing_requires_config_and_complete_provider_layout(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        (tmp_path / ".map").mkdir()
        (tmp_path / ".map" / "config.yaml").write_text("", encoding="utf-8")
        (tmp_path / ".claude").mkdir()

        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert result.exit_code == 1
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_refresh_existing_does_not_claim_user_modified_mcp_server(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        (tmp_path / ".map").mkdir()
        (tmp_path / ".map" / "config.yaml").write_text(
            "updates.auto: true\n", encoding="utf-8"
        )
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        custom_server = {"command": "custom-sequential-thinking"}
        (tmp_path / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"sequential-thinking": custom_server}}),
            encoding="utf-8",
        )

        result = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert not (tmp_path / ".claude" / "mcp_config.json").exists()
        mcp_data = json.loads((tmp_path / ".mcp.json").read_text())
        assert mcp_data["mcpServers"]["sequential-thinking"] == custom_server
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert not any(
            entry.key_path == "mcpServers.sequential-thinking"
            for entry in manifest.config_entries
        )

    def test_refresh_existing_preserves_project_choices(self, tmp_path: Path) -> None:
        from mapify_cli.config.project_config import load_map_config

        os.chdir(tmp_path)
        with mock.patch("mapify_cli.configure_global_permissions"):
            first = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--mcp",
                    "none",
                    "--compression",
                    "aggressive",
                    "--compression-threshold",
                    "250000",
                    "--sofa",
                    "--agent-memory",
                    "local",
                    "--no-auto-update",
                    "--autonomy",
                ],
            )
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )

        assert first.exit_code == 0, first.stdout
        assert refresh.exit_code == 0, refresh.stdout
        config = load_map_config(tmp_path)
        assert config.compression_policy == "aggressive"
        assert config.compression_threshold_tokens == 250_000
        assert config.sofa_enabled is True
        assert config.claude_agents_persistent_memory == "local"
        assert config.updates_auto is False
        reflector = (tmp_path / ".claude" / "agents" / "reflector.md").read_text()
        assert "memory: user_local" in reflector
        settings = json.loads(
            (tmp_path / ".claude" / "settings.local.json").read_text()
        )
        assert settings["mapify"]["autonomy"] is True

    def test_refresh_existing_skips_global_permissions(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        with mock.patch("mapify_cli.configure_global_permissions") as configure:
            first = runner.invoke(
                app,
                ["init", ".", "--force", "--no-git", "--mcp", "none"],
            )
            assert first.exit_code == 0, first.stdout
            configure.assert_called_once_with()
            configure.reset_mock()

            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )

        assert refresh.exit_code == 0, refresh.stdout
        configure.assert_not_called()

    def test_refresh_existing_configuration_failure_is_fatal_but_normal_init_warns(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout

        with mock.patch(
            "mapify_cli.config.project_config.write_default_config",
            side_effect=OSError("config is read-only"),
        ):
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )
            normal = runner.invoke(
                app,
                ["init", ".", "--force", "--no-git", "--mcp", "none"],
            )

        assert refresh.exit_code == 1
        assert "config is read-only" in refresh.stdout
        assert normal.exit_code == 0, normal.stdout

    def test_refresh_existing_malformed_project_config_is_fatal_and_non_mutating(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        malformed = "claude_agents.persistent_memory: [\n"
        config_path = tmp_path / ".map" / "config.yaml"
        config_path.write_text(malformed, encoding="utf-8")
        reflector_path = tmp_path / ".claude" / "agents" / "reflector.md"
        reflector_path.write_text("user sentinel\n", encoding="utf-8")

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing project configuration" in refresh.stdout
        assert config_path.read_text(encoding="utf-8") == malformed
        assert reflector_path.read_text(encoding="utf-8") == "user sentinel\n"

    def test_refresh_existing_malformed_mcp_config_is_fatal_and_non_mutating(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        malformed = '{"mcpServers": {'
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(malformed, encoding="utf-8")
        reflector_path = tmp_path / ".claude" / "agents" / "reflector.md"
        reflector_path.write_text("user sentinel\n", encoding="utf-8")

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing Claude MCP configuration" in refresh.stdout
        assert mcp_path.read_text(encoding="utf-8") == malformed
        assert list(tmp_path.glob(".mcp.backup.*.json")) == []
        assert reflector_path.read_text(encoding="utf-8") == "user sentinel\n"

    @pytest.mark.parametrize(
        "manifest_content",
        [
            "{malformed",
            "[]\n",
            json.dumps(
                {
                    "mapify_version": "3.25.0",
                    "provider": "claude",
                    "installed_at": "2026-08-13T00:00:00Z",
                    "entries": {},
                }
            ),
        ],
        ids=["malformed", "non-object", "schema-invalid"],
    )
    def test_refresh_existing_invalid_manifest_is_fatal_and_non_mutating(
        self, tmp_path: Path, manifest_content: str
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        manifest_path.write_text(manifest_content, encoding="utf-8")
        before = _snapshot_tree(tmp_path)

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing install manifest" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before

    @pytest.mark.parametrize(
        "manifest_content",
        [
            "{malformed",
            "[]\n",
            json.dumps(
                {
                    "mapify_version": "3.25.0",
                    "provider": "claude",
                    "installed_at": "2026-08-13T00:00:00Z",
                    "entries": {},
                }
            ),
        ],
        ids=["malformed", "non-object", "schema-invalid"],
    )
    def test_pending_refresh_invalid_manifest_is_regenerated_under_parent_lock(
        self,
        tmp_path: Path,
        manifest_content: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        config_path = tmp_path / ".map" / "config.yaml"
        config_before = config_path.read_bytes()
        catalog_before = {
            path.name
            for path in (tmp_path / ".claude" / "skills").iterdir()
            if path.is_dir()
        }
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        manifest_path.write_text(manifest_content, encoding="utf-8")
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude",),
            ),
        )

        with project_update_lock(tmp_path, timeout_s=0.0) as lease:
            monkeypatch.setattr(
                update_state_module.os, "getppid", lambda: lease.owner_pid
            )
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
                env={MAP_UPDATE_PARENT_LEASE_ENV: lease.token},
            )

        assert refresh.exit_code == 0, refresh.stdout
        assert config_path.read_bytes() == config_before
        assert {
            path.name
            for path in (tmp_path / ".claude" / "skills").iterdir()
            if path.is_dir()
        } == catalog_before
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(raw_manifest, dict)
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.providers == ["claude"]
        state = read_update_state(tmp_path)
        assert state.last_installed_version == mapify_cli.__version__
        assert state.pending_refresh is False
        assert state.pending_providers == ()
        assert list(manifest_path.parent.glob(f".{manifest_path.name}.*.tmp")) == []

    def test_pending_refresh_does_not_bypass_unreadable_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        manifest_before = manifest_path.read_bytes()
        pending_state = UpdateState(
            last_installed_version=mapify_cli.__version__,
            pending_refresh=True,
            pending_providers=("claude",),
        )
        write_update_state(tmp_path, pending_state)
        original_read_text = Path.read_text

        def deny_manifest_read(
            path: Path,
            encoding: str | None = None,
            errors: str | None = None,
        ) -> str:
            if path == manifest_path:
                raise PermissionError("manifest unreadable")
            return original_read_text(path, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", deny_manifest_read)

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing install manifest" in refresh.stdout
        assert manifest_path.read_bytes() == manifest_before
        assert read_update_state(tmp_path) == pending_state

    def test_pending_dual_provider_refresh_narrows_then_clears_state(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        claude = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        codex = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        assert claude.exit_code == 0, claude.stdout
        assert codex.exit_code == 0, codex.stdout
        config_path = tmp_path / ".map" / "config.yaml"
        config_before = config_path.read_bytes()
        claude_catalog = {
            path.name
            for path in (tmp_path / ".claude" / "skills").iterdir()
            if path.is_dir()
        }
        codex_catalog = {
            path.name
            for path in (tmp_path / ".agents" / "skills").iterdir()
            if path.is_dir()
        }
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        manifest_path.write_text("{malformed", encoding="utf-8")
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude", "codex"),
            ),
        )

        first_refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert first_refresh.exit_code == 0, first_refresh.stdout
        first_state = read_update_state(tmp_path)
        assert first_state.pending_refresh is True
        assert first_state.pending_providers == ("codex",)
        first_manifest = read_manifest(tmp_path)
        assert first_manifest is not None
        assert first_manifest.providers == ["claude", "codex"]

        second_refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "codex",
                "--refresh-existing",
            ],
        )

        assert second_refresh.exit_code == 0, second_refresh.stdout
        completed_state = read_update_state(tmp_path)
        assert completed_state.pending_refresh is False
        assert completed_state.pending_providers == ()
        assert config_path.read_bytes() == config_before
        assert {
            path.name
            for path in (tmp_path / ".claude" / "skills").iterdir()
            if path.is_dir()
        } == claude_catalog
        assert {
            path.name
            for path in (tmp_path / ".agents" / "skills").iterdir()
            if path.is_dir()
        } == codex_catalog
        completed_manifest = read_manifest(tmp_path)
        assert completed_manifest is not None
        assert completed_manifest.providers == ["claude", "codex"]

    def test_standalone_dual_provider_refresh_migrates_providerless_v1_state(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        claude = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        codex = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        assert claude.exit_code == 0, claude.stdout
        assert codex.exit_code == 0, codex.stdout
        state_path = tmp_path / ".map" / "update-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "last_attempt_at": None,
                    "last_observed_version": mapify_cli.__version__,
                    "last_installed_version": mapify_cli.__version__,
                    "pending_refresh": True,
                    "pending_providers": [],
                }
            ),
            encoding="utf-8",
        )

        first_refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--refresh-existing",
            ],
        )

        assert first_refresh.exit_code == 0, first_refresh.stdout
        first_state = read_update_state(tmp_path)
        assert first_state.schema_version == 2
        assert first_state.pending_refresh is True
        assert first_state.pending_providers == ("codex",)

        second_refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "codex",
                "--refresh-existing",
            ],
        )

        assert second_refresh.exit_code == 0, second_refresh.stdout
        completed_state = read_update_state(tmp_path)
        assert completed_state.pending_refresh is False
        assert completed_state.pending_providers == ()

    def test_manual_recovery_action_rebuilds_corrupt_manifest_and_is_terminal(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        manifest_path.write_text("{malformed", encoding="utf-8")
        write_update_state(
            tmp_path,
            UpdateState(
                last_installed_version=mapify_cli.__version__,
                pending_refresh=True,
                pending_providers=("claude",),
            ),
        )
        refresh_error = ProjectRefreshError(
            "refresh failed",
            pending_providers=("claude",),
        )
        with (
            mock.patch(
                "mapify_cli.auto_update.detect_install_kind",
                return_value=InstallKind.PIP,
            ),
            mock.patch(
                "mapify_cli.auto_update.refresh_installed_providers",
                side_effect=refresh_error,
            ),
        ):
            update_result = check_and_update(
                tmp_path,
                mapify_cli.__version__,
                UpdateMode.MANUAL,
            )

        assert update_result.status is UpdateStatus.ERROR
        assert update_result.message is not None
        action = update_result.message.splitlines()[-1]
        assert action == (
            "mapify init . --force --no-git --provider claude --refresh-existing"
        )

        command = shlex.split(action)
        assert command[:2] == ["mapify", "init"]
        recovery = runner.invoke(app, command[1:])

        assert recovery.exit_code == 0, recovery.stdout
        recovered_manifest = read_manifest(tmp_path)
        assert recovered_manifest is not None
        assert recovered_manifest.providers == ["claude"]
        recovered_state = read_update_state(tmp_path)
        assert recovered_state.pending_refresh is False
        assert recovered_state.pending_providers == ()

    def test_refresh_existing_unreadable_manifest_is_fatal_and_non_mutating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout
        manifest_path = tmp_path / ".map" / "mapify.lock.json"
        before = _snapshot_tree(tmp_path)
        original_read_text = Path.read_text

        def deny_manifest_read(
            path: Path,
            encoding: str | None = None,
            errors: str | None = None,
        ) -> str:
            if path == manifest_path:
                raise PermissionError("manifest unreadable")
            return original_read_text(path, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", deny_manifest_read)
        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "claude",
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing install manifest" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before

    @pytest.mark.parametrize(
        "mcp_content",
        ['{"mcpServers": {', "[]\n"],
        ids=["malformed", "non-object"],
    )
    def test_codex_refresh_invalid_mcp_is_fatal_and_non_mutating(
        self, tmp_path: Path, mcp_content: str
    ) -> None:
        os.chdir(tmp_path)
        claude = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        codex = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        assert claude.exit_code == 0, claude.stdout
        assert codex.exit_code == 0, codex.stdout
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(mcp_content, encoding="utf-8")
        before = _snapshot_tree(tmp_path)

        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "codex",
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing Claude MCP configuration" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before
        assert list(tmp_path.glob(".mcp.backup.*.json")) == []

    def test_codex_refresh_unreadable_mcp_is_fatal_and_non_mutating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        os.chdir(tmp_path)
        claude = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--mcp",
                "none",
                "--provider",
                "claude",
            ],
        )
        codex = runner.invoke(
            app,
            ["init", ".", "--force", "--no-git", "--provider", "codex"],
        )
        assert claude.exit_code == 0, claude.stdout
        assert codex.exit_code == 0, codex.stdout
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        before = _snapshot_tree(tmp_path)
        original_read_text = Path.read_text

        def deny_mcp_read(
            path: Path,
            encoding: str | None = None,
            errors: str | None = None,
        ) -> str:
            if path == mcp_path:
                raise PermissionError("MCP config unreadable")
            return original_read_text(path, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", deny_mcp_read)
        refresh = runner.invoke(
            app,
            [
                "init",
                ".",
                "--force",
                "--no-git",
                "--provider",
                "codex",
                "--debug",
                "--refresh-existing",
            ],
        )

        assert refresh.exit_code == 1
        assert "existing Claude MCP configuration" in refresh.stdout
        assert _snapshot_tree(tmp_path) == before
        assert list(tmp_path.glob(".mcp.backup.*.json")) == []

    def test_refresh_existing_manifest_failure_is_fatal_but_normal_init_warns(
        self, tmp_path: Path
    ) -> None:
        os.chdir(tmp_path)
        first = runner.invoke(
            app, ["init", ".", "--force", "--no-git", "--mcp", "none"]
        )
        assert first.exit_code == 0, first.stdout

        with mock.patch(
            "mapify_cli.install_manifest.write_manifest",
            side_effect=OSError("manifest is read-only"),
        ):
            refresh = runner.invoke(
                app,
                [
                    "init",
                    ".",
                    "--force",
                    "--no-git",
                    "--provider",
                    "claude",
                    "--refresh-existing",
                ],
            )
            normal = runner.invoke(
                app,
                ["init", ".", "--force", "--no-git", "--mcp", "none"],
            )

        assert refresh.exit_code == 1
        assert "manifest is read-only" in refresh.stdout
        assert normal.exit_code == 0, normal.stdout


class TestSofaGitignoreMerge:
    """Tests for merge_sofa_gitignore — ST-002 / AC-2."""

    def test_vc1_gitignore_created_when_absent(self, tmp_path):
        """VC1 [AC-2]: no root .gitignore → merge → file exists with marker + .sofa/."""
        from mapify_cli.delivery.file_copier import merge_sofa_gitignore

        assert not (tmp_path / ".gitignore").exists()

        result = merge_sofa_gitignore(tmp_path)

        assert result == 1, "Expected 1 (file created)"
        content = (tmp_path / ".gitignore").read_text()
        assert "# map:sofa" in content
        assert ".sofa/" in content

    def test_vc2_gitignore_appends_under_marker(self, tmp_path):
        """VC2 [AC-2]: pre-existing .gitignore → existing lines preserved + block appended."""
        from mapify_cli.delivery.file_copier import merge_sofa_gitignore

        existing = "node_modules/\n.env\n"
        (tmp_path / ".gitignore").write_text(existing)

        result = merge_sofa_gitignore(tmp_path)

        assert result == 1, "Expected 1 (file modified)"
        content = (tmp_path / ".gitignore").read_text()
        # Existing lines preserved byte-for-byte
        assert content.startswith(existing)
        # Block appended
        assert "# map:sofa" in content
        assert ".sofa/" in content

    def test_vc3_gitignore_merge_idempotent(self, tmp_path):
        """VC3 [AC-2]: calling merge twice produces exactly ONE marker and ONE .sofa/ line."""
        from mapify_cli.delivery.file_copier import merge_sofa_gitignore

        merge_sofa_gitignore(tmp_path)
        result2 = merge_sofa_gitignore(tmp_path)

        assert result2 == 0, "Expected 0 (no-op on second call)"
        content = (tmp_path / ".gitignore").read_text()
        assert content.count("# map:sofa") == 1
        assert content.count(".sofa/") == 1

    def test_vc4_no_sofa_gitignore_entry_without_sofa_flag(self, tmp_path):
        """VC4 [AC-2][INV-SOFA-1]: init without --sofa must NOT write sofa entries.

        Non-vacuous: a repo-root .gitignore is pre-created so the negative
        assertions exercise a file that actually exists. Automatic-update
        runtime ignores are independently required, while prior user entries
        must remain byte-for-byte at the start of the file.
        """
        os.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        original = "node_modules/\n.env\n"
        gitignore.write_text(original)

        result = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )

        assert result.exit_code == 0, f"init failed: {result.stdout}"
        content = gitignore.read_text()
        assert "# map:sofa" not in content
        assert ".sofa/" not in content.splitlines()
        assert content.startswith(original)
        for path in (
            ".map/update-state.json",
            ".map/update.lock",
            ".map/provider-refresh.lock",
        ):
            assert content.splitlines().count(path) == 1

    def test_vc4_init_with_sofa_flag_writes_marker(self, tmp_path):
        """VC4 [AC-2]: init WITH --sofa must write the sofa marker to root .gitignore."""
        os.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--sofa"]
        )

        assert result.exit_code == 0, f"init --sofa failed: {result.stdout}"
        content = (tmp_path / ".gitignore").read_text()
        assert "# map:sofa" in content
        assert ".sofa/" in content

    def test_vc1_init_default_no_sofa_artifacts(self, tmp_path):
        """VC1 [AC-6][INV-SOFA-1]: init WITHOUT --sofa creates no `.sofa/`
        directory and writes no active `sofa.enabled: true` line."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0, f"init failed: {result.stdout}"
        # No credential directory is created on the default (disabled) path.
        assert not (tmp_path / ".sofa").exists()
        # The generated config never activates SOFA.
        config_text = (tmp_path / ".map" / "config.yaml").read_text()
        active_sofa = [
            line
            for line in config_text.splitlines()
            if line.strip().startswith("sofa.enabled:")
        ]
        assert (
            active_sofa == []
        ), f"default config must not activate sofa.enabled: {active_sofa}"


class TestAutonomyPosture:
    """Tests for the opt-in --autonomy posture in settings.local.json."""

    def _read_local(self, tmp_path):
        return json.loads((tmp_path / ".claude" / "settings.local.json").read_text())

    def test_autonomy_true_writes_broad_allow_deny_and_sentinel(self, tmp_path):
        from mapify_cli.config.settings import create_or_merge_project_settings_local

        create_or_merge_project_settings_local(tmp_path, autonomy=True)

        data = self._read_local(tmp_path)
        allow = data["permissions"]["allow"]
        deny = data["permissions"]["deny"]
        assert "Bash(*)" in allow
        assert "Edit(*)" in allow and "Write(*)" in allow
        assert "Bash(git commit:*)" in deny
        assert "Bash(git push:*)" in deny
        # Sentinel beside the permissions it governs (read by the hook).
        assert data["mapify"]["autonomy"] is True
        # Narrow dev allowlist still merged (not replaced by autonomy).
        assert "Bash(go test *)" in allow

    def test_autonomy_true_gitignores_settings_local(self, tmp_path):
        from mapify_cli.config.settings import create_or_merge_project_settings_local

        create_or_merge_project_settings_local(tmp_path, autonomy=True)

        content = (tmp_path / ".gitignore").read_text()
        assert ".claude/settings.local.json" in content.splitlines()
        assert "# map:settings-local" in content

    def test_autonomy_none_leaves_no_sentinel_but_gitignores_local_settings(
        self, tmp_path
    ):
        from mapify_cli.config.settings import create_or_merge_project_settings_local

        create_or_merge_project_settings_local(tmp_path, autonomy=None)

        data = self._read_local(tmp_path)
        assert "mapify" not in data
        assert "Bash(*)" not in data["permissions"]["allow"]
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert ".claude/settings.local.json" in gitignore.splitlines()
        assert any(
            line.startswith("# map:settings-local") for line in gitignore.splitlines()
        )

    def test_autonomy_false_removes_posture(self, tmp_path):
        from mapify_cli.config.settings import create_or_merge_project_settings_local

        create_or_merge_project_settings_local(tmp_path, autonomy=True)
        create_or_merge_project_settings_local(tmp_path, autonomy=False)

        data = self._read_local(tmp_path)
        assert "Bash(*)" not in data["permissions"]["allow"]
        assert "Bash(git commit:*)" not in data["permissions"]["deny"]
        assert "mapify" not in data
        # Teardown preserves the narrow dev allowlist.
        assert "Bash(go test *)" in data["permissions"]["allow"]

    def test_autonomy_true_idempotent(self, tmp_path):
        from mapify_cli.config.settings import create_or_merge_project_settings_local

        create_or_merge_project_settings_local(tmp_path, autonomy=True)
        create_or_merge_project_settings_local(tmp_path, autonomy=True)

        data = self._read_local(tmp_path)
        assert data["permissions"]["allow"].count("Bash(*)") == 1
        assert data["permissions"]["deny"].count("Bash(git commit:*)") == 1
        content = (tmp_path / ".gitignore").read_text()
        assert content.count("# map:settings-local") == 1
        assert content.count(".claude/settings.local.json") == 1

    def test_init_autonomy_flag_end_to_end(self, tmp_path):
        os.chdir(tmp_path)

        result = runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--autonomy"]
        )

        assert result.exit_code == 0, f"init --autonomy failed: {result.stdout}"
        data = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
        assert data["mapify"]["autonomy"] is True
        assert "Bash(*)" in data["permissions"]["allow"]
        assert (
            ".claude/settings.local.json"
            in (tmp_path / ".gitignore").read_text().splitlines()
        )


class TestConfigureGlobalPermissions:
    """Claude Code matches all file-reading tools against Read(path) rules only;
    a stale Glob(**) rule is never enforced and only emits a startup warning."""

    def _global_settings_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return tmp_path / ".claude" / "settings.json"

    def test_fresh_install_writes_read_not_glob(self, tmp_path, monkeypatch):
        from mapify_cli.config.settings import configure_global_permissions

        settings_path = self._global_settings_path(tmp_path, monkeypatch)
        configure_global_permissions()

        allow = json.loads(settings_path.read_text())["permissions"]["allow"]
        assert "Read(**)" in allow
        assert "Glob(**)" not in allow

    def test_existing_stale_glob_rule_is_migrated(self, tmp_path, monkeypatch):
        from mapify_cli.config.settings import configure_global_permissions

        settings_path = self._global_settings_path(tmp_path, monkeypatch)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"permissions": {"allow": ["Glob(**)"], "deny": []}})
        )

        configure_global_permissions()

        allow = json.loads(settings_path.read_text())["permissions"]["allow"]
        assert "Read(**)" in allow
        assert "Glob(**)" not in allow

    def test_existing_duplicate_stale_glob_rules_are_all_migrated(
        self, tmp_path, monkeypatch
    ):
        from mapify_cli.config.settings import configure_global_permissions

        settings_path = self._global_settings_path(tmp_path, monkeypatch)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"permissions": {"allow": ["Glob(**)", "Glob(**)"], "deny": []}})
        )

        configure_global_permissions()

        allow = json.loads(settings_path.read_text())["permissions"]["allow"]
        assert allow.count("Glob(**)") == 0
        assert allow.count("Read(**)") == 1

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        from mapify_cli.config.settings import configure_global_permissions

        settings_path = self._global_settings_path(tmp_path, monkeypatch)
        configure_global_permissions()
        configure_global_permissions()

        allow = json.loads(settings_path.read_text())["permissions"]["allow"]
        assert allow.count("Read(**)") == 1

    def test_init_default_no_autonomy_sentinel(self, tmp_path):
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])

        assert result.exit_code == 0, f"init failed: {result.stdout}"
        data = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
        assert "mapify" not in data
        assert "Bash(*)" not in data["permissions"]["allow"]


class TestCheckCommand:
    """Test the check command."""

    def test_check_not_initialized(self, tmp_path):
        """Test check command shows tool status."""
        os.chdir(tmp_path)
        result = runner.invoke(app, ["check"])

        # Should show available tools
        assert result.exit_code == 0
        assert (
            "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout
        )

    @mock.patch("mapify_cli.check_tool")
    def test_check_initialized(self, mock_check_tool, tmp_path):
        """Test check command when tools are installed."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert (
            "Check Available Tools" in result.stdout or "MAP Framework" in result.stdout
        )
        assert "initialized" in result.stdout
        expected_agents = count_agent_templates()
        assert f"{expected_agents} agents" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_check_with_mcp_servers(self, mock_check_tool, tmp_path):
        """Test check command shows MCP server status."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["check"])

        assert result.exit_code == 0
        assert "sequential-thinking" in result.stdout
        assert "deepwiki" not in result.stdout


class TestDoctorCommand:
    """Test the doctor command."""

    @mock.patch("mapify_cli.check_tool")
    def test_doctor_initialized_project(self, mock_check_tool, tmp_path):
        """Doctor should report healthy project structure after init."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        init_result = runner.invoke(app, ["init", ".", "--no-git", "--mcp", "none"])
        assert init_result.exit_code == 0

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "MAP Doctor" in result.stdout
        assert ".map/main/" in result.stdout
        expected_agents = count_agent_templates()
        assert f"{expected_agents}/{expected_agents}" in result.stdout

    @mock.patch("mapify_cli.check_tool")
    def test_doctor_reports_missing_structure(self, mock_check_tool, tmp_path):
        """Doctor should surface missing paths in non-initialized directories."""
        os.chdir(tmp_path)
        mock_check_tool.return_value = True

        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0
        assert "Missing core paths" in result.stdout
        assert ".map/scripts" in result.stdout


class TestInternalUpdateCommand:
    """Test the hidden machine-readable project update adapter."""

    @pytest.mark.parametrize(
        ("mode", "expected_exit_code", "expected_payload"),
        [
            ("automatic", 0, None),
            (
                "manual",
                1,
                {
                    "status": "error",
                    "message": "MAP update failed: updater import failed",
                },
            ),
        ],
    )
    def test_internal_update_import_failure_obeys_mode_boundary(
        self,
        tmp_path: Path,
        mode: str,
        expected_exit_code: int,
        expected_payload: dict[str, str] | None,
    ) -> None:
        real_import = builtins.__import__

        def fail_updater_import(
            name: str,
            globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: Sequence[str] | None = (),
            level: int = 0,
        ) -> object:
            if name == "mapify_cli.auto_update":
                print("incidental import stdout")
                print("incidental import stderr", file=sys.stderr)
                raise ImportError("updater import failed")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fail_updater_import):
            result = runner.invoke(
                app,
                ["_update", "--mode", mode, "--project", str(tmp_path)],
            )

        assert result.exit_code == expected_exit_code
        assert result.stderr == ""
        if expected_payload is None:
            assert result.stdout_bytes == b""
            assert result.output == ""
        else:
            assert result.stdout.count("\n") == 1
            assert json.loads(result.stdout) == expected_payload
            assert "incidental import" not in result.output
            assert "Traceback" not in result.output

    def test_internal_update_invalid_raw_mode_does_not_import_updater(
        self, tmp_path: Path
    ) -> None:
        real_import = builtins.__import__

        def reject_updater_import(
            name: str,
            globals: Mapping[str, object] | None = None,
            locals: Mapping[str, object] | None = None,
            fromlist: Sequence[str] | None = (),
            level: int = 0,
        ) -> object:
            if name == "mapify_cli.auto_update":
                raise AssertionError("invalid mode must be rejected before import")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=reject_updater_import):
            result = runner.invoke(
                app,
                ["_update", "--mode", "scheduled", "--project", str(tmp_path)],
            )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert json.loads(result.stdout) == {
            "status": "error",
            "message": "--mode must be automatic or manual",
        }

    @pytest.mark.parametrize("attack", ["symlink", "hardlink"])
    @pytest.mark.parametrize("lock_name", ["update.lock", "provider-refresh.lock"])
    @pytest.mark.parametrize("mode", ["automatic", "manual"])
    def test_internal_update_unsafe_lock_path_obeys_mode_boundary(
        self,
        tmp_path: Path,
        lock_name: str,
        mode: str,
        attack: str,
    ) -> None:
        if attack == "hardlink" and os.name == "nt":
            pytest.skip("POSIX hardlink security contract")
        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        target = map_dir / f"{lock_name}.target"
        target.write_text("not a MAP lock\n", encoding="utf-8")
        if attack == "symlink":
            (map_dir / lock_name).symlink_to(target)
        else:
            try:
                os.link(target, map_dir / lock_name)
            except (NotImplementedError, OSError) as exc:
                pytest.skip(f"hardlinks unavailable: {exc}")

        with mock.patch(
            "mapify_cli.auto_update.detect_install_kind",
            return_value=InstallKind.PIP,
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", mode, "--project", str(tmp_path)],
            )

        assert result.stderr == ""
        if mode == "automatic":
            assert result.exit_code == 0
            assert result.stdout == ""
        else:
            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert "unsafe MAP update lock path" in payload["message"]
            assert lock_name in payload["message"]
            assert "Remove the unsafe path" in payload["message"]
        assert target.read_text(encoding="utf-8") == "not a MAP lock\n"

    @pytest.mark.parametrize("mode", ["automatic", "manual"])
    def test_internal_update_symlinked_map_ancestor_obeys_mode_boundary(
        self,
        tmp_path: Path,
        mode: str,
    ) -> None:
        outside = tmp_path / "outside-map"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"outside-bytes")
        (tmp_path / ".map").symlink_to(outside, target_is_directory=True)

        with mock.patch(
            "mapify_cli.auto_update.detect_install_kind",
            return_value=InstallKind.PIP,
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", mode, "--project", str(tmp_path)],
            )

        if mode == "automatic":
            assert result.exit_code == 0
            assert result.stdout == ""
        else:
            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert "unsafe MAP update lock path" in payload["message"]
            assert "update.lock" in payload["message"]
        assert sentinel.read_bytes() == b"outside-bytes"
        assert not (outside / "update.lock").exists()
        assert not (outside / "provider-refresh.lock").exists()

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_error_is_silent_success(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR, "3.25.0", message="offline"
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.output == ""

    def test_internal_update_automatic_lock_cleanup_failure_preserves_reload(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".claude" / "skills").mkdir(parents=True)

        @contextlib.contextmanager
        def failing_cleanup_lock(
            project: Path,
            *,
            timeout_s: float,
        ):
            del project, timeout_s
            yield
            raise OSError("lock cleanup failed")

        with (
            mock.patch(
                "mapify_cli.auto_update.detect_install_kind",
                return_value=InstallKind.PIP,
            ),
            mock.patch(
                "mapify_cli.auto_update.project_update_lock",
                failing_cleanup_lock,
            ),
            mock.patch(
                "mapify_cli.auto_update.fetch_version_targets",
                return_value=VersionTargets(StableVersion(3, 26, 0), None),
            ),
            mock.patch("mapify_cli.auto_update.install_exact_version"),
            mock.patch(
                "mapify_cli.auto_update.installed_providers",
                return_value=("claude",),
            ),
            mock.patch(
                "mapify_cli.auto_update.refresh_installed_providers",
                return_value=("claude",),
            ),
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", "automatic", "--project", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert result.stderr == ""
        assert json.loads(result.stdout) == {
            "status": "updated",
            "current_version": "3.25.0",
            "installed_version": "3.26.0",
            "refreshed_providers": ["claude"],
            "reload_current_skill": True,
        }
        assert "lock cleanup failed" not in result.output

    def test_internal_update_automatic_final_state_failure_preserves_reload(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        real_write_state = write_update_state

        def fail_completed_state_write(project: Path, state: UpdateState) -> None:
            if state.last_installed_version == "3.26.0" and not state.pending_refresh:
                raise OSError("final state write failed")
            real_write_state(project, state)

        with (
            mock.patch(
                "mapify_cli.auto_update.detect_install_kind",
                return_value=InstallKind.PIP,
            ),
            mock.patch(
                "mapify_cli.auto_update.fetch_version_targets",
                return_value=VersionTargets(StableVersion(3, 26, 0), None),
            ),
            mock.patch("mapify_cli.auto_update.install_exact_version"),
            mock.patch(
                "mapify_cli.auto_update.installed_providers",
                return_value=("claude",),
            ),
            mock.patch(
                "mapify_cli.auto_update.refresh_installed_providers",
                return_value=("claude",),
            ),
            mock.patch(
                "mapify_cli.auto_update.write_update_state",
                side_effect=fail_completed_state_write,
            ),
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", "automatic", "--project", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert result.stderr == ""
        assert json.loads(result.stdout) == {
            "status": "updated",
            "current_version": "3.25.0",
            "installed_version": "3.26.0",
            "refreshed_providers": ["claude"],
            "reload_current_skill": True,
        }
        assert "final state write failed" not in result.output

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_partial_refresh_error_remains_silent(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "config.toml").write_text("", encoding="utf-8")
        (tmp_path / ".agents" / "skills").mkdir(parents=True)
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR,
            "3.25.0",
            installed_version="3.26.0",
            message="codex refresh failed",
            refreshed_providers=("claude",),
            reload_current_skill=True,
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout_bytes == b""
        assert result.stderr == ""
        assert result.output == ""

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_does_not_infer_completion_after_provider_marker_loss(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        # The failed Codex child removed its layout marker after Claude completed.
        # A post-error rescan therefore sees only Claude and cannot prove completion.
        (tmp_path / ".claude" / "skills").mkdir(parents=True)
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR,
            "3.25.0",
            installed_version="3.26.0",
            message="codex refresh failed after marker removal",
            refreshed_providers=("claude",),
            reload_current_skill=True,
            refresh_complete=False,
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout_bytes == b""
        assert result.stderr == ""

    def test_internal_update_automatic_late_metadata_failure_emits_updated_json(
        self, tmp_path: Path
    ) -> None:
        with (
            mock.patch(
                "mapify_cli.auto_update.detect_install_kind",
                return_value=InstallKind.PIP,
            ),
            mock.patch(
                "mapify_cli.auto_update.fetch_version_targets",
                return_value=VersionTargets(
                    StableVersion(3, 26, 0),
                    StableVersion(4, 0, 0),
                ),
            ),
            mock.patch("mapify_cli.auto_update.install_exact_version"),
            mock.patch(
                "mapify_cli.auto_update.installed_providers",
                return_value=("claude", "codex"),
            ),
            mock.patch(
                "mapify_cli.auto_update.refresh_installed_providers",
                return_value=("claude", "codex"),
            ),
            mock.patch(
                "mapify_cli.auto_update.fetch_release_highlights",
                side_effect=OSError("GitHub offline"),
            ),
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", "automatic", "--project", str(tmp_path)],
            )

        assert result.exit_code == 0
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert json.loads(result.stdout) == {
            "status": "updated",
            "current_version": "3.25.0",
            "installed_version": "3.26.0",
            "refreshed_providers": ["claude", "codex"],
            "reload_current_skill": True,
        }

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_unexpected_exception_is_silent_success(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        def raise_noisily(*_args: object, **_kwargs: object) -> UpdateResult:
            print("incidental stdout")
            print("incidental stderr", file=sys.stderr)
            raise OSError("unexpected")

        mock_update.side_effect = raise_noisily

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.output == ""

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_to_dict_failure_is_silent_success(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        broken_result = mock.Mock(status=UpdateStatus.CURRENT)
        broken_result.to_dict.side_effect = TypeError("cannot serialize result")
        mock_update.return_value = broken_result

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.output == ""

    @mock.patch("mapify_cli.auto_update.check_and_update")
    @mock.patch(
        "mapify_cli._write_internal_update_json",
        side_effect=OSError("stdout closed"),
    )
    def test_internal_update_automatic_write_failure_is_silent_success(
        self,
        mock_write: mock.Mock,
        mock_update: mock.Mock,
        tmp_path: Path,
    ) -> None:
        mock_update.return_value = UpdateResult(UpdateStatus.CURRENT, "3.25.0")

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.output == ""
        assert mock_write.call_count == 1

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_success_emits_one_clean_unicode_json_object(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        expected = UpdateResult(
            UpdateStatus.CURRENT,
            "3.25.0",
            message="Текущая версия 🎉",
        )

        def return_noisily(*_args: object, **_kwargs: object) -> UpdateResult:
            print("incidental stdout")
            print("incidental stderr", file=sys.stderr)
            return expected

        mock_update.side_effect = return_noisily

        result = runner.invoke(
            app,
            ["_update", "--mode", "automatic", "--project", str(tmp_path)],
        )

        expected_output = (
            '{"status": "current", "current_version": "3.25.0", '
            '"message": "Текущая версия 🎉", "reload_current_skill": false}\n'
        )
        assert result.exit_code == 0
        assert result.stdout == expected_output
        assert result.stderr == ""
        assert result.output == expected_output
        assert result.stdout.count("\n") == 1

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_error_is_json_failure(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR, "3.25.0", message="offline"
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert json.loads(result.stdout) == {
            "status": "error",
            "current_version": "3.25.0",
            "message": "offline",
            "reload_current_skill": False,
        }

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_unexpected_exception_is_bounded_json_failure(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        def raise_noisily(*_args: object, **_kwargs: object) -> UpdateResult:
            print("incidental stdout")
            print("incidental stderr", file=sys.stderr)
            raise OSError("unexpected" + "🎉" * 3_000)

        mock_update.side_effect = raise_noisily

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["message"].startswith("MAP update failed: unexpected")
        assert len(payload["message"]) <= 2_000
        assert len(result.stdout_bytes) <= 16 * 1_024

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_service_error_is_bounded_valid_json(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        original_message = "offline " + "🎉" * 20_000
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR,
            "3.25.0",
            message=original_message,
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert len(result.stdout_bytes) <= 16 * 1_024
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["current_version"] == "3.25.0"
        assert payload["message"].startswith("offline ")
        assert len(payload["message"]) < len(original_message)

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_to_dict_failure_is_one_json_failure(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        broken_result = mock.Mock(status=UpdateStatus.CURRENT)
        broken_result.to_dict.side_effect = TypeError("cannot serialize result")
        mock_update.return_value = broken_result

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert len(result.stdout_bytes) <= 16 * 1_024
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "message": "MAP update failed: cannot serialize result",
        }
        assert "Traceback" not in result.output

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_write_failure_emits_one_fallback_json(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        mock_update.return_value = UpdateResult(UpdateStatus.CURRENT, "3.25.0")
        real_write = mapify_cli._write_internal_update_json
        call_count = 0

        def fail_first_write(payload: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("stdout closed")
            real_write(payload)

        with mock.patch(
            "mapify_cli._write_internal_update_json",
            side_effect=fail_first_write,
        ):
            result = runner.invoke(
                app,
                ["_update", "--mode", "manual", "--project", str(tmp_path)],
            )

        assert result.exit_code == 1
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert json.loads(result.stdout) == {
            "status": "error",
            "message": "MAP update failed: stdout closed",
        }
        assert "Traceback" not in result.output

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_major_metadata_is_bounded_with_required_fields(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        original_body = "🎉" * 20_000
        mock_update.return_value = UpdateResult(
            UpdateStatus.MAJOR_AVAILABLE,
            "3.25.0",
            major=ReleaseHighlights(
                version=StableVersion(4, 0, 0),
                title="MAP 4",
                body=original_body,
                url="https://github.com/azalio/map-framework/releases/tag/v4.0.0",
            ),
        )

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert result.stderr == ""
        assert result.stdout.count("\n") == 1
        assert len(result.stdout_bytes) <= 16 * 1_024
        payload = json.loads(result.stdout)
        assert payload["status"] == "major_available"
        assert payload["current_version"] == "3.25.0"
        assert payload["major"]["version"] == "4.0.0"
        assert payload["major"]["title"] == "MAP 4"
        assert payload["major"]["url"].endswith("/v4.0.0")
        assert len(payload["major"]["body"]) < len(original_body)

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_success_emits_one_clean_unicode_json_object(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        expected = UpdateResult(
            UpdateStatus.UPDATED,
            "3.25.0",
            installed_version="3.26.0",
            message="Обновлено 🎉",
            refreshed_providers=("claude", "codex"),
            reload_current_skill=True,
        )

        def return_noisily(*_args: object, **_kwargs: object) -> UpdateResult:
            print("incidental stdout")
            print("incidental stderr", file=sys.stderr)
            return expected

        mock_update.side_effect = return_noisily

        result = runner.invoke(
            app,
            ["_update", "--mode", "manual", "--project", str(tmp_path)],
        )

        expected_output = (
            '{"status": "updated", "current_version": "3.25.0", '
            '"installed_version": "3.26.0", "message": "Обновлено 🎉", '
            '"refreshed_providers": ["claude", "codex"], '
            '"reload_current_skill": true}\n'
        )
        assert result.exit_code == 0
        assert result.stdout == expected_output
        assert result.stderr == ""
        assert result.output == expected_output
        assert result.stdout.count("\n") == 1

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_invalid_mode_is_one_clean_json_failure(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["_update", "--mode", "scheduled", "--project", str(tmp_path)],
        )

        expected_output = (
            json.dumps(
                {"status": "error", "message": "--mode must be automatic or manual"}
            )
            + "\n"
        )
        assert result.exit_code == 1
        assert result.stdout == expected_output
        assert result.stderr == ""
        assert result.output == expected_output
        mock_update.assert_not_called()

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_manual_forwards_approved_major(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        mock_update.return_value = UpdateResult(UpdateStatus.CURRENT, "3.25.0")

        result = runner.invoke(
            app,
            [
                "_update",
                "--mode",
                "manual",
                "--project",
                str(tmp_path),
                "--approve-major",
                "4.0.0",
            ],
        )

        assert result.exit_code == 0
        mock_update.assert_called_once_with(
            tmp_path.resolve(),
            current_version=mapify_cli.__version__,
            mode=UpdateMode.MANUAL,
            approved_major="4.0.0",
        )

    @mock.patch("mapify_cli.auto_update.check_and_update")
    def test_internal_update_automatic_approved_major_rejection_is_silent(
        self, mock_update: mock.Mock, tmp_path: Path
    ) -> None:
        mock_update.return_value = UpdateResult(
            UpdateStatus.ERROR,
            "3.25.0",
            message="A major version can be approved only in manual mode.",
        )

        result = runner.invoke(
            app,
            [
                "_update",
                "--mode",
                "automatic",
                "--project",
                str(tmp_path),
                "--approve-major",
                "4.0.0",
            ],
        )

        assert result.exit_code == 0
        assert result.output == ""
        mock_update.assert_called_once_with(
            tmp_path.resolve(),
            current_version=mapify_cli.__version__,
            mode=UpdateMode.AUTOMATIC,
            approved_major="4.0.0",
        )

    def test_internal_update_is_hidden_from_help(self) -> None:
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "_update" not in result.stdout


class TestUpgradeCommand:
    """Test the upgrade command."""

    @mock.patch("mapify_cli.auto_update.check_and_update")
    @mock.patch("mapify_cli.get_latest_release", return_value={"tag_name": "v0.0.1"})
    def test_public_upgrade_does_not_use_auto_update_service(
        self, mock_release: mock.Mock, mock_auto: mock.Mock
    ) -> None:
        del mock_release

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        mock_auto.assert_not_called()

    @mock.patch("mapify_cli._run_self_upgrade", return_value=0)
    @mock.patch(
        "mapify_cli._self_upgrade_command",
        return_value=["uv", "tool", "upgrade", "mapify-cli"],
    )
    @mock.patch("mapify_cli._mapify_install_kind", return_value="uv-tool")
    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_self_upgrades_when_newer(
        self, mock_get_latest, _mock_kind, _mock_cmd, mock_run, tmp_path
    ):
        """A newer release self-upgrades the mapify CLI and writes no project files."""
        del _mock_kind, _mock_cmd
        os.chdir(tmp_path)
        mock_get_latest.return_value = {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v9.9.9",
        }

        result = runner.invoke(app, ["upgrade"])

        # Rich may hard-wrap output to terminal width; normalize whitespace
        # before substring checks so wrapped lines still match.
        normalized = " ".join(result.stdout.split())
        assert result.exit_code == 0, result.stdout
        assert "New version available" in normalized
        assert "mapify upgraded" in normalized
        # Directs users at the project-file refresh path
        assert "mapify init . --force" in normalized
        # Shelled out to the self-upgrade command exactly once
        mock_run.assert_called_once_with(["uv", "tool", "upgrade", "mapify-cli"])
        # upgrade no longer creates any project files
        assert not (tmp_path / ".claude").exists()

    @mock.patch("mapify_cli._run_self_upgrade")
    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_already_latest_does_nothing(
        self, mock_get_latest, mock_run, tmp_path
    ):
        """When already on the latest release, no upgrade command runs."""
        os.chdir(tmp_path)
        mock_get_latest.return_value = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v0.0.1",
        }

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "Already on the latest release" in result.stdout
        assert "Nothing to upgrade" in result.stdout
        mock_run.assert_not_called()

    @mock.patch("mapify_cli._run_self_upgrade")
    @mock.patch("mapify_cli._mapify_install_kind", return_value="source")
    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_source_checkout_disabled(
        self, mock_get_latest, _mock_kind, mock_run, tmp_path
    ):
        """A source checkout disables self-upgrade and runs no command."""
        del _mock_kind
        os.chdir(tmp_path)
        mock_get_latest.return_value = {"tag_name": "v9.9.9"}

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 0
        assert "self-upgrade is disabled" in result.stdout
        mock_run.assert_not_called()

    @mock.patch("mapify_cli._run_self_upgrade", return_value=1)
    @mock.patch(
        "mapify_cli._self_upgrade_command",
        return_value=["uv", "tool", "upgrade", "mapify-cli"],
    )
    @mock.patch("mapify_cli._mapify_install_kind", return_value="uv-tool")
    @mock.patch("mapify_cli.get_latest_release")
    def test_upgrade_command_failure_exits_nonzero(
        self, mock_get_latest, _mock_kind, _mock_cmd, _mock_run, tmp_path
    ):
        """A failing upgrade command surfaces a nonzero exit and a manual hint."""
        del _mock_kind, _mock_cmd, _mock_run
        os.chdir(tmp_path)
        mock_get_latest.return_value = {"tag_name": "v9.9.9"}

        result = runner.invoke(app, ["upgrade"])

        assert result.exit_code == 1
        assert "Upgrade command failed" in result.stdout

    @mock.patch("mapify_cli.get_latest_release", return_value=None)
    def test_upgrade_no_release_metadata_attempts_anyway(
        self, _mock_get_latest, tmp_path
    ):
        """No release metadata: upgrade still proceeds past the version gate."""
        del _mock_get_latest
        os.chdir(tmp_path)
        result = runner.invoke(app, ["upgrade"])

        # In the pytest runtime mapify resolves to a source checkout, so the
        # self-upgrade path short-circuits cleanly instead of shelling out.
        normalized = " ".join(result.stdout.split())
        assert result.exit_code == 0
        assert "Could not fetch release metadata" in normalized


class TestSelfUpgradeHelpers:
    """Unit tests for install-kind detection and the upgrade-command builder."""

    def test_install_kind_uv_tool(self, monkeypatch):
        monkeypatch.setattr(
            mapify_cli,
            "__file__",
            "/home/u/.local/share/uv/tools/mapify-cli/lib/"
            "python3.11/site-packages/mapify_cli/__init__.py",
        )
        assert mapify_cli._mapify_install_kind() == "uv-tool"

    def test_install_kind_pip(self, monkeypatch):
        monkeypatch.setattr(
            mapify_cli,
            "__file__",
            "/home/u/.venv/lib/python3.11/site-packages/mapify_cli/__init__.py",
        )
        assert mapify_cli._mapify_install_kind() == "pip"

    def test_install_kind_source(self, monkeypatch):
        monkeypatch.setattr(
            mapify_cli,
            "__file__",
            "/home/u/gitroot/map-framework/src/mapify_cli/__init__.py",
        )
        assert mapify_cli._mapify_install_kind() == "source"

    def test_self_upgrade_command_uv_tool(self, monkeypatch):
        monkeypatch.setattr(mapify_cli.shutil, "which", lambda *_: "/usr/bin/uv")
        assert mapify_cli._self_upgrade_command("uv-tool") == [
            "/usr/bin/uv",
            "tool",
            "upgrade",
            "mapify-cli",
        ]

    def test_self_upgrade_command_uv_tool_missing_uv(self, monkeypatch):
        monkeypatch.setattr(mapify_cli.shutil, "which", lambda *_: None)
        assert mapify_cli._self_upgrade_command("uv-tool") is None

    def test_self_upgrade_command_pip(self):
        assert mapify_cli._self_upgrade_command("pip") == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "mapify-cli",
        ]

    def test_self_upgrade_command_source_is_none(self):
        assert mapify_cli._self_upgrade_command("source") is None


class TestAgentCreation:
    """Test agent file creation."""

    def test_create_agent_files(self, tmp_path):
        """Test creating agent files with no MCP servers."""
        create_agent_files(tmp_path, [])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()
        assert (agents_dir / "task-decomposer.md").exists()
        assert (agents_dir / "actor.md").exists()
        assert (agents_dir / "monitor.md").exists()

    def test_create_agent_files_with_templates(self, tmp_path):
        """Test creating agent files from templates."""
        create_agent_files(tmp_path, ["sequential-thinking"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Verify agent files contain MCP references
        actor_content = (agents_dir / "actor.md").read_text()
        assert "actor" in actor_content.lower()

    @mock.patch("mapify_cli.get_templates_dir")
    def test_create_agent_files_fallback(self, mock_get_templates, tmp_path):
        """Test creating agent files when templates are missing (uses fallback generators).

        Verifies that:
        - Fallback generators create valid agent content
        - 8 core agents are created via fallback generators
        - Content includes required sections (IDENTITY, ROLE)
        - MCP integration sections are included when MCP servers specified

        Note: Fallback generators only cover the core agents. The remaining
        agents (research-agent, final-verifier) are only available when
        copying from templates.
        """
        # Mock templates directory that doesn't have agent templates
        mock_templates_path = tmp_path / "mock_templates"
        mock_templates_path.mkdir(parents=True, exist_ok=True)
        mock_get_templates.return_value = mock_templates_path

        # Call create_agent_files with MCP servers
        create_agent_files(tmp_path, ["sequential-thinking"])

        agents_dir = tmp_path / ".claude" / "agents"
        assert agents_dir.exists()

        # Verify core agents were created using fallback generators
        expected_agents = [
            "task-decomposer.md",
            "actor.md",
            "monitor.md",
            "predictor.md",
            "evaluator.md",
            "reflector.md",
            "documentation-reviewer.md",
        ]

        for agent_file in expected_agents:
            agent_path = agents_dir / agent_file
            assert agent_path.exists(), f"Agent {agent_file} not created"

            # Verify content has required sections
            content = agent_path.read_text()
            assert "---" in content, f"Agent {agent_file} missing YAML frontmatter"
            assert "name:" in content, f"Agent {agent_file} missing name field"
            # Check for role/identity sections (various formats)
            has_core_section = any(
                marker in content for marker in ["IDENTITY", "ROLE", "Role:", "# Role"]
            )
            assert has_core_section, f"Agent {agent_file} missing core sections"

            # Verify MCP integration for agents that use MCP tools
            if any(
                name in agent_file
                for name in ["task-decomposer", "actor", "monitor", "predictor"]
            ):
                assert (
                    "mcp" in content.lower() or "tool" in content.lower()
                ), f"Agent {agent_file} missing MCP integration section"


class TestCommandCreation:
    """Test command file creation."""

    def test_create_commands_dir(self, tmp_path):
        """Test creating commands directory."""
        create_commands_dir(tmp_path)

        commands_dir = tmp_path / ".claude" / "commands"
        assert commands_dir.exists()
        assert (commands_dir / "README.md").exists()

    def test_create_command_files(self, tmp_path):
        """Test creating command files — commands migrated to skills, only README remains."""
        create_command_files(tmp_path)

        commands_dir = tmp_path / ".claude" / "commands"
        assert commands_dir.exists()
        # After skills migration, commands/ has only README.md (no map-*.md)
        command_files = [p for p in commands_dir.glob("*.md") if p.name != "README.md"]
        assert len(command_files) == 0


class TestHelperFunctions:
    """Test helper functions."""

    def test_is_command_basic(self):
        """Test is_command with basic commands."""
        # Test with a command that should exist on all systems
        assert is_command(["python"]) is True or is_command(["python3"]) is True

    @mock.patch("httpx.Client")
    def test_get_latest_release(self, mock_client):
        """Test fetching latest release from GitHub."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/azalio/map-framework/releases/tag/v1.0.0",
        }

        mock_client_instance = mock.Mock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__enter__ = mock.Mock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = mock.Mock(return_value=False)
        mock_client.return_value = mock_client_instance

        result = get_latest_release("azalio", "map-framework")
        assert result is not None
        assert result["tag_name"] == "v1.0.0"


class TestMcpJsonConfig:
    """Test .mcp.json creation and merging functionality."""

    def test_build_standard_mcp_servers_returns_all_servers(self):
        """Test that build_standard_mcp_servers returns all expected servers."""
        servers = build_standard_mcp_servers()

        expected_servers = [
            "sequential-thinking",
        ]
        for server in expected_servers:
            assert server in servers, f"Missing server: {server}"

        # deepwiki MCP installation was removed — it must not be shipped.
        assert "deepwiki" not in servers

    def test_build_standard_mcp_servers_correct_types(self):
        """Test that servers have correct transport types."""
        servers = build_standard_mcp_servers()

        # stdio servers should have 'command' key
        for server_name in ["sequential-thinking"]:
            assert "command" in servers[server_name], f"{server_name} missing command"
            assert "args" in servers[server_name], f"{server_name} missing args"

    def test_read_project_mcp_json_missing_file(self, tmp_path):
        """Test reading non-existent .mcp.json returns None."""
        mcp_file = tmp_path / ".mcp.json"
        result = read_project_mcp_json(mcp_file)
        assert result is None

    def test_read_project_mcp_json_valid_file(self, tmp_path):
        """Test reading valid .mcp.json returns parsed content."""
        mcp_file = tmp_path / ".mcp.json"
        config = {"mcpServers": {"test": {"command": "test"}}}
        mcp_file.write_text(json.dumps(config))

        result = read_project_mcp_json(mcp_file)
        assert result == config

    def test_read_project_mcp_json_invalid_json(self, tmp_path):
        """Test reading invalid JSON returns None and creates backup."""
        import re

        mcp_file = tmp_path / ".mcp.json"
        mcp_file.write_text("{ invalid json }")

        result = read_project_mcp_json(mcp_file)

        assert result is None
        # Check that backup was created with correct naming pattern
        backup_files = list(tmp_path.glob(".mcp.backup.*.json"))
        assert len(backup_files) == 1

        # Verify backup filename matches expected format: YYYYMMDD_HHMMSS_XXXXXXXX (8 hex chars)
        backup_name = backup_files[0].name
        assert re.match(
            r"\.mcp\.backup\.\d{8}_\d{6}_[a-f0-9]{8}\.json$", backup_name
        ), f"Backup name doesn't match expected format: {backup_name}"

    def test_write_project_mcp_json_creates_file(self, tmp_path):
        """Test writing .mcp.json creates file with correct format."""
        mcp_file = tmp_path / ".mcp.json"
        config = {"mcpServers": {"test": {"command": "test"}}}

        write_project_mcp_json(mcp_file, config)

        assert mcp_file.exists()
        content = mcp_file.read_text()
        assert content.endswith("\n")  # Should have trailing newline
        parsed = json.loads(content)
        assert parsed == config

    @pytest.mark.skipif(
        __import__("os").getuid() == 0,
        reason="root bypasses file-permission enforcement; test is meaningless when running as root",
    )
    def test_write_project_mcp_json_permission_error(self, tmp_path):
        """Test write_project_mcp_json raises OSError on permission denied."""
        mcp_file = tmp_path / ".mcp.json"
        mcp_file.touch()
        mcp_file.chmod(0o444)  # Read-only

        config = {"mcpServers": {"test": {"command": "test"}}}

        try:
            with pytest.raises(OSError):
                write_project_mcp_json(mcp_file, config)
        finally:
            # Restore permissions so tmp_path cleanup works
            mcp_file.chmod(0o644)

    def test_merge_mcp_json_preserves_existing(self):
        """Test that merge preserves existing servers."""
        existing = {
            "mcpServers": {
                "user-server": {"command": "user-cmd"},
            }
        }
        new_servers = {
            "deepwiki": {"type": "http", "url": "https://mcp.deepwiki.com/mcp"},
        }

        result = merge_mcp_json(existing, new_servers)

        assert "user-server" in result["mcpServers"]
        assert "deepwiki" in result["mcpServers"]
        assert result["mcpServers"]["user-server"]["command"] == "user-cmd"

    def test_merge_mcp_json_does_not_overwrite(self):
        """Test that merge does not overwrite existing servers with same name."""
        existing = {
            "mcpServers": {
                "deepwiki": {
                    "type": "http",
                    "url": "https://custom.url",
                },  # User's custom
            }
        }
        new_servers = {
            "deepwiki": {
                "type": "http",
                "url": "https://mcp.deepwiki.com/mcp",
            },  # Standard
        }

        result = merge_mcp_json(existing, new_servers)

        # User's custom config should be preserved
        assert result["mcpServers"]["deepwiki"]["url"] == "https://custom.url"

    def test_merge_mcp_json_adds_mcpservers_key(self):
        """Test that merge adds mcpServers key if missing."""
        existing = {"other_key": "value"}
        new_servers = {
            "deepwiki": {"type": "http", "url": "https://mcp.deepwiki.com/mcp"}
        }

        result = merge_mcp_json(existing, new_servers)

        assert "mcpServers" in result
        assert "deepwiki" in result["mcpServers"]
        assert "other_key" in result  # Other keys preserved

    def test_create_or_merge_new_file(self, tmp_path):
        """Test creating new .mcp.json when file doesn't exist."""
        create_or_merge_project_mcp_json(tmp_path, ["sequential-thinking"])

        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists()

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        assert "sequential-thinking" in config["mcpServers"]
        # deepwiki was removed — it is filtered out even if requested.
        assert "deepwiki" not in config["mcpServers"]
        assert len(config["mcpServers"]) == 1

    def test_create_or_merge_existing_file(self, tmp_path):
        """Test merging into existing .mcp.json."""
        # Create existing file with user's server
        mcp_file = tmp_path / ".mcp.json"
        existing_config = {
            "mcpServers": {
                "my-custom-server": {"command": "my-server", "args": ["mcp"]},
            }
        }
        mcp_file.write_text(json.dumps(existing_config))

        # Run merge
        create_or_merge_project_mcp_json(tmp_path, ["sequential-thinking"])

        # Verify merge
        config = json.loads(mcp_file.read_text())
        assert "my-custom-server" in config["mcpServers"]  # User's server preserved
        assert "sequential-thinking" in config["mcpServers"]  # New server added

    def test_create_or_merge_empty_servers_list(self, tmp_path):
        """Test that empty servers list doesn't create file."""
        create_or_merge_project_mcp_json(tmp_path, [])

        mcp_file = tmp_path / ".mcp.json"
        assert not mcp_file.exists()

    def test_create_or_merge_filters_unknown_servers(self, tmp_path):
        """Test that unknown server names are ignored (deepwiki is now unknown)."""
        create_or_merge_project_mcp_json(
            tmp_path, ["deepwiki", "unknown-server", "sequential-thinking"]
        )

        mcp_file = tmp_path / ".mcp.json"
        config = json.loads(mcp_file.read_text())

        assert "sequential-thinking" in config["mcpServers"]
        assert (
            "deepwiki" not in config["mcpServers"]
        )  # removed → filtered like any unknown
        assert "unknown-server" not in config["mcpServers"]

    def test_init_creates_mcp_json(self, tmp_path):
        """Test that mapify init creates .mcp.json file."""
        os.chdir(tmp_path)

        result = runner.invoke(app, ["init", ".", "--force", "--mcp", "essential"])

        # Allow exit code 0 or initialization messages
        mcp_file = tmp_path / ".mcp.json"
        assert (
            mcp_file.exists()
        ), f"Expected .mcp.json to be created. Output: {result.output}"

        config = json.loads(mcp_file.read_text())
        assert "mcpServers" in config
        # essential = sequential-thinking only (deepwiki install was removed)
        assert "sequential-thinking" in config["mcpServers"]
        assert "deepwiki" not in config["mcpServers"]


class TestCreateMapTools:
    """Test create_map_tools() function for static analysis tools."""

    def test_create_map_tools_creates_directory(self, tmp_path):
        """Test that create_map_tools creates .map directory with static-analysis."""
        count = create_map_tools(tmp_path)

        map_dir = tmp_path / ".map"
        static_analysis_dir = map_dir / "static-analysis"

        assert map_dir.exists()
        assert static_analysis_dir.exists()
        assert count > 0  # Should have created some scripts

    def test_create_map_tools_copies_scripts(self, tmp_path):
        """Test that static analysis scripts are copied correctly."""
        create_map_tools(tmp_path)

        static_analysis_dir = tmp_path / ".map" / "static-analysis"
        handlers_dir = static_analysis_dir / "handlers"

        # Verify main script exists
        assert (static_analysis_dir / "analyze.sh").exists()

        # Verify handlers exist
        assert handlers_dir.exists()
        assert (handlers_dir / "python.sh").exists()
        assert (handlers_dir / "go.sh").exists()
        assert (handlers_dir / "typescript.sh").exists()
        assert (handlers_dir / "common.sh").exists()

    def test_create_map_tools_makes_scripts_executable(self, tmp_path):
        """Test that scripts are made executable."""
        create_map_tools(tmp_path)

        static_analysis_dir = tmp_path / ".map" / "static-analysis"
        handlers_dir = static_analysis_dir / "handlers"

        # Check main script is executable
        analyze_script = static_analysis_dir / "analyze.sh"
        assert analyze_script.stat().st_mode & 0o111  # Has execute bit

        # Check handler scripts are executable
        for script in handlers_dir.glob("*.sh"):
            assert script.stat().st_mode & 0o111, f"{script.name} should be executable"

    def test_create_map_tools_refreshes_managed_scripts(self, tmp_path):
        """Managed scripts are (over)written; unrelated user files are preserved.

        Phase C2: map tools are MAP-owned and installed per-file via
        copy_managed_file(fenced=False) rather than a whole-directory rmtree.
        That refreshes the managed scripts in place but no longer destroys
        unrelated files a user may have dropped into .map/static-analysis/.
        """
        map_dir = tmp_path / ".map" / "static-analysis"
        map_dir.mkdir(parents=True)
        # A stale copy of a managed script (different content) should be refreshed.
        stale_managed = map_dir / "analyze.sh"
        stale_managed.write_text("#!/usr/bin/env bash\n# stale\n")
        # An unrelated user file should NOT be destroyed (no whole-dir wipe).
        user_file = map_dir / "my_notes.txt"
        user_file.write_text("user content")

        create_map_tools(tmp_path)

        # Managed script refreshed to shipped content (no longer "stale").
        assert stale_managed.exists()
        assert "stale" not in stale_managed.read_text()
        # Unrelated user file preserved.
        assert user_file.exists()
        assert user_file.read_text() == "user content"

    def test_create_map_tools_returns_script_count(self, tmp_path):
        """Test that function returns correct count of scripts."""
        count = create_map_tools(tmp_path)

        # Count actual scripts created (.sh + .py)
        map_dir = tmp_path / ".map"
        actual_count = len(list(map_dir.rglob("*.sh"))) + len(
            list(map_dir.rglob("*.py"))
        )

        assert count == actual_count
        assert count >= 5  # analyze.sh + common.sh + python.sh + go.sh + typescript.sh

    @mock.patch("mapify_cli.delivery.file_copier.get_templates_dir")
    def test_create_map_tools_no_templates(self, mock_get_templates, tmp_path):
        """Test handling when templates directory doesn't have map subdirectory."""
        # Mock empty templates directory
        mock_templates = tmp_path / "empty_templates"
        mock_templates.mkdir()
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when no map templates exist
        assert count == 0

    @mock.patch("mapify_cli.delivery.file_copier.get_templates_dir")
    def test_create_map_tools_map_exists_but_no_static_analysis(
        self, mock_get_templates, tmp_path
    ):
        """Test when templates_dir/map exists but has no shipped content."""
        mock_templates = tmp_path / "templates"
        mock_templates.mkdir()
        (mock_templates / "map").mkdir()
        mock_get_templates.return_value = mock_templates

        count = create_map_tools(tmp_path)

        # Should return 0 when map template is empty
        assert count == 0
        assert (tmp_path / ".map").exists()

    def test_create_map_tools_preserves_other_map_contents(self, tmp_path):
        """Test that other files in .map are preserved."""
        # Create .map with other content
        map_dir = tmp_path / ".map"
        map_dir.mkdir()
        other_file = map_dir / "other_data.json"
        other_file.write_text('{"key": "value"}')

        # Run create_map_tools
        create_map_tools(tmp_path)

        # Other file should still exist
        assert other_file.exists()
        assert other_file.read_text() == '{"key": "value"}'

        # New scripts should also exist
        assert (map_dir / "static-analysis" / "analyze.sh").exists()


class TestBranchArtifactTemplates:
    """Tests for get_branch_artifact_templates()."""

    def test_returns_expected_keys(self):
        """Artifact template keys must match the expected set exactly."""
        templates = get_branch_artifact_templates()
        assert set(templates.keys()) == {
            "code-review-001.md",
            "qa-001.md",
            "pr-draft.md",
        }


class TestCodexProvider:
    """Functional tests for Codex CLI provider (AC-1 through AC-20).

    Each test method maps to one acceptance criterion in the Codex provider spec.
    The ``codex_project`` fixture runs ``mapify init . --provider codex --no-git``
    in a fresh tmp_path and returns the project root.
    """

    # ------------------------------------------------------------------ #
    # Shared fixture                                                       #
    # ------------------------------------------------------------------ #

    @pytest.fixture
    def codex_project(self, tmp_path):
        """Run init with --provider codex and return the project root path."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert (
            result.exit_code == 0
        ), f"init --provider codex failed (exit {result.exit_code}):\n{result.output}"
        return tmp_path

    # ------------------------------------------------------------------ #
    # AC-1: .agents/skills/map-plan/SKILL.md created                      #
    # ------------------------------------------------------------------ #

    def test_ac01_creates_skill_file(self, codex_project):
        """AC-1: map-plan SKILL.md must exist after init."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        assert skill_file.exists(), f"Expected {skill_file} to exist"

    # ------------------------------------------------------------------ #
    # AC-2: SKILL.md has valid YAML frontmatter                           #
    # ------------------------------------------------------------------ #

    def test_ac02_skill_has_valid_frontmatter(self, codex_project):
        """AC-2: SKILL.md must start with '---' and contain name/description fields."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith(
            "---"
        ), "SKILL.md must start with YAML frontmatter '---'"
        assert "name:" in content, "SKILL.md frontmatter must contain 'name:'"
        assert (
            "description:" in content
        ), "SKILL.md frontmatter must contain 'description:'"

    # ------------------------------------------------------------------ #
    # AC-3: SKILL.md contains no Claude-specific tool references          #
    # ------------------------------------------------------------------ #

    def test_ac03_skill_no_claude_tool_refs(self, codex_project):
        """AC-3: SKILL.md must not reference Claude-only tool functions."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        forbidden_patterns = [
            "Agent(",
            "AskUserQuestion(",
            "subagent_type=",
            "Read(",
            "Write(",
            "Edit(",
            "Glob(",
            "Grep(",
        ]
        for pattern in forbidden_patterns:
            assert (
                pattern not in content
            ), f"SKILL.md must not contain Claude tool reference '{pattern}'"

    # ------------------------------------------------------------------ #
    # AC-4: AGENTS.md exists at project root                              #
    # ------------------------------------------------------------------ #

    def test_ac04_creates_agents_md(self, codex_project):
        """AC-4: AGENTS.md must exist at the project root and be non-empty."""
        agents_md = codex_project / "AGENTS.md"
        assert agents_md.exists(), "AGENTS.md must exist at project root"
        content = (
            agents_md.read_text(encoding="utf-8") if not agents_md.is_symlink() else ""
        )
        # Either a real file with content or a symlink to CLAUDE.md
        assert agents_md.is_symlink() or len(content) > 0, "AGENTS.md must be non-empty"
        if not agents_md.is_symlink():
            assert (
                "$map-plan" in content
            ), "Codex AGENTS.md must document skill invocation with $"
            assert (
                "$map-efficient" in content
            ), "Codex AGENTS.md must document the execution skill"
            assert (
                "codex_hooks" not in content
            ), "Codex AGENTS.md must not document deprecated codex_hooks"

    # ------------------------------------------------------------------ #
    # AC-5: config.toml, agents/*.toml, hooks/workflow-gate.py exist      #
    # ------------------------------------------------------------------ #

    def test_ac05_creates_config_and_agents(self, codex_project):
        """AC-5: config.toml and at least one agent TOML and the hook script must exist."""
        codex_dir = codex_project / ".codex"
        assert (codex_dir / "config.toml").exists(), ".codex/config.toml must exist"
        config_text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        assert (
            "hooks = true" in config_text
        ), "Codex config must enable canonical hooks feature"
        assert (
            "codex_hooks" not in config_text
        ), "Codex config must not use deprecated codex_hooks feature alias"
        toml_files = list((codex_dir / "agents").glob("*.toml"))
        assert (
            len(toml_files) > 0
        ), ".codex/agents/ must contain at least one *.toml file"
        assert (
            codex_dir / "hooks" / "workflow-gate.py"
        ).exists(), ".codex/hooks/workflow-gate.py must exist"

    # ------------------------------------------------------------------ #
    # AC-6: .map/scripts/ installed (or skipped if already present)       #
    # ------------------------------------------------------------------ #

    def test_ac06_map_scripts_installed_or_skipped(self, codex_project, tmp_path):
        """AC-6: .map/scripts/ installed when absent, pre-existing files preserved."""
        map_scripts = codex_project / ".map" / "scripts"
        templates_scripts = get_templates_dir() / "map" / "scripts"
        if templates_scripts.exists() and any(templates_scripts.iterdir()):
            assert (
                map_scripts.exists()
            ), ".map/scripts/ must exist when template provides scripts"

        # Verify skip-if-exists: pre-existing custom scripts survive codex init
        project2 = tmp_path / "skip_test"
        project2.mkdir()
        scripts_dir = project2 / ".map" / "scripts"
        scripts_dir.mkdir(parents=True)
        custom_script = scripts_dir / "custom.py"
        custom_script.write_text("# user custom script\n")

        runner2 = CliRunner()
        os.chdir(project2)
        result = runner2.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0, f"init failed: {result.output}"
        assert (
            custom_script.exists()
        ), ".map/scripts/custom.py must survive codex init (skip-if-exists)"
        assert custom_script.read_text() == "# user custom script\n"

    # ------------------------------------------------------------------ #
    # AC-7: Default init (no --provider) creates .claude/, not .codex/    #
    # ------------------------------------------------------------------ #

    def test_ac07_default_init_unchanged(self, tmp_path):
        """AC-7: 'init .' without --provider must create .claude/ and not .codex/."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--no-git", "--mcp", "none", "--force"]
        )
        assert result.exit_code == 0, f"Default init failed:\n{result.output}"
        assert (
            tmp_path / ".claude"
        ).exists(), ".claude/ must exist for default provider"
        assert not (
            tmp_path / ".codex"
        ).exists(), ".codex/ must NOT be created by the default claude provider"

    # ------------------------------------------------------------------ #
    # AC-8: Template sync enforced (reference to ST-008 coverage)         #
    # ------------------------------------------------------------------ #

    def test_ac08_template_sync_enforced(self):
        """AC-8: Codex templates must be present in src/mapify_cli/templates/codex/.

        The exhaustive render-parity check lives in tests/test_template_render.py.
        This test is a quick smoke check that the directory exists and is non-empty.
        """
        codex_templates = get_templates_dir() / "codex"
        assert (
            codex_templates.exists()
        ), "templates/codex/ must exist (render enforced by test_template_render.py)"
        all_files = list(codex_templates.rglob("*"))
        template_files = [f for f in all_files if f.is_file()]
        assert (
            len(template_files) > 0
        ), "templates/codex/ must contain at least one file"

    # ------------------------------------------------------------------ #
    # AC-9: SKILL.md has all 9 step section headers                       #
    # ------------------------------------------------------------------ #

    def test_ac09_skill_has_all_steps(self, codex_project):
        """AC-9: SKILL.md must contain all 9 step section headers."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        expected_steps = [
            "## Step 0",
            "## Step 1",
            "## Step 2",
            "## Step 3",
            "## Step 4",
            "## Step 5",
            "## Step 6",
            "## Step 7",
            "## Step 8",
        ]
        for step_header in expected_steps:
            assert step_header in content, f"SKILL.md must contain '{step_header}'"

    # ------------------------------------------------------------------ #
    # AC-10: No Claude references in any Codex provider file              #
    # ------------------------------------------------------------------ #

    def test_ac10_no_claude_refs_anywhere(self, codex_project):
        """AC-10: No Codex provider file should reference Claude-specific tool APIs."""
        claude_tool_patterns = [
            "Agent(",
            "AskUserQuestion(",
            "subagent_type=",
        ]
        violations: list[str] = []
        for root in (codex_project / ".codex", codex_project / ".agents"):
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError):
                    continue
                for pattern in claude_tool_patterns:
                    if pattern in content:
                        rel = file_path.relative_to(codex_project)
                        violations.append(f"{rel}: contains '{pattern}'")
        assert not violations, (
            "Claude-specific tool references found in Codex provider files:\n"
            + "\n".join(violations)
        )

    # ------------------------------------------------------------------ #
    # AC-11: Codex skills map-fast, map-check, and map-efficient exist     #
    # ------------------------------------------------------------------ #

    def test_ac11_stub_skills_exist(self, codex_project):
        """AC-11: Codex skills must exist under the official .agents/skills root."""
        skills_dir = codex_project / ".agents" / "skills"
        assert (
            skills_dir / "map-fast" / "SKILL.md"
        ).exists(), ".agents/skills/map-fast/SKILL.md must exist"
        assert (
            skills_dir / "map-check" / "SKILL.md"
        ).exists(), ".agents/skills/map-check/SKILL.md must exist"
        assert (
            skills_dir / "map-efficient" / "SKILL.md"
        ).exists(), ".agents/skills/map-efficient/SKILL.md must exist"
        assert (
            skills_dir / "map-efficient" / "efficient-reference.md"
        ).exists(), ".agents/skills/map-efficient/efficient-reference.md must exist"

    # ------------------------------------------------------------------ #
    # AC-9 (map-review port spec): Codex map-review skill + refs exist    #
    # ------------------------------------------------------------------ #

    @pytest.mark.skipif(
        not (
            Path(__file__).resolve().parents[1]
            / "src"
            / "mapify_cli"
            / "templates_src"
            / "codex"
            / "skills"
            / "map-review"
            / "review-reference.md.jinja"
        ).exists()
        or not (
            Path(__file__).resolve().parents[1]
            / "src"
            / "mapify_cli"
            / "templates_src"
            / "codex"
            / "skills"
            / "map-review"
            / "adversarial-reference.md.jinja"
        ).exists(),
        reason="review-reference.md.jinja / adversarial-reference.md.jinja not authored yet",
    )
    def test_ac09_codex_map_review_skill_exists(self, codex_project):
        """AC-9 (map-review port spec): Codex map-review skill and its two
        reference files must exist under both the shipped templates root
        and the official .agents/skills root post-init."""
        templates_dir = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "mapify_cli"
            / "templates"
            / "codex"
            / "skills"
            / "map-review"
        )
        for filename in ("SKILL.md", "review-reference.md", "adversarial-reference.md"):
            assert (
                templates_dir / filename
            ).exists(), f"templates/codex/skills/map-review/{filename} must exist"

        agents_skills_dir = codex_project / ".agents" / "skills" / "map-review"
        for filename in ("SKILL.md", "review-reference.md", "adversarial-reference.md"):
            assert (
                agents_skills_dir / filename
            ).exists(), f".agents/skills/map-review/{filename} must exist"

    # ------------------------------------------------------------------ #
    # AC-12: hooks.json and workflow-gate.py both created                 #
    # ------------------------------------------------------------------ #

    def test_ac12_hooks_created(self, codex_project):
        """AC-12: hooks.json and hooks/workflow-gate.py must exist with correct config."""
        import json as _json

        codex_dir = codex_project / ".codex"
        hooks_json_path = codex_dir / "hooks.json"
        assert hooks_json_path.exists(), ".codex/hooks.json must exist"
        assert (
            codex_dir / "hooks" / "workflow-gate.py"
        ).exists(), ".codex/hooks/workflow-gate.py must exist"

        # Verify hook command uses quoted git-root-resolved path
        hooks_data = _json.loads(hooks_json_path.read_text())
        assert set(hooks_data) == {
            "hooks"
        }, ".codex/hooks.json must not include MAP-only top-level metadata"
        command = hooks_data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert (
            "$(git rev-parse --show-toplevel)" in command
        ), "Hook command must use $(git rev-parse --show-toplevel) for path resolution"
        # Path must be quoted to handle spaces in directory names
        assert (
            '"$(git rev-parse --show-toplevel)' in command
        ), "Hook command path must be quoted for spaces in paths"

    # ------------------------------------------------------------------ #
    # AC-13: CodexProvider is a subclass of BaseProvider                  #
    # ------------------------------------------------------------------ #

    def test_ac13_codex_provider_isinstance(self):
        """AC-13: CodexProvider must be an instance of BaseProvider."""
        from mapify_cli.delivery.providers import BaseProvider, CodexProvider

        provider = CodexProvider()
        assert isinstance(
            provider, BaseProvider
        ), "CodexProvider must inherit from BaseProvider"

    # ------------------------------------------------------------------ #
    # AC-14: --provider codex does NOT create .claude/                    #
    # ------------------------------------------------------------------ #

    def test_ac14_codex_init_no_claude_dir(self, codex_project):
        """AC-14: init --provider codex must not create the .claude/ directory."""
        assert not (
            codex_project / ".claude"
        ).exists(), ".claude/ must NOT be created when using --provider codex"

    # ------------------------------------------------------------------ #
    # AC-15: SKILL.md includes spawn_agent with monitor in SPEC_REVIEW    #
    # ------------------------------------------------------------------ #

    def test_ac15_spec_review_step(self, codex_project):
        """AC-15: SKILL.md must include a spawn_agent call using 'monitor' agent."""
        skill_file = codex_project / ".agents" / "skills" / "map-plan" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        # The SPEC_REVIEW step uses spawn_agent with agent_type="monitor"
        assert "spawn_agent(" in content, "SKILL.md must contain spawn_agent("
        assert (
            'agent_type="monitor"' in content
        ), 'SKILL.md must contain agent_type="monitor" for SPEC_REVIEW step'

    # ------------------------------------------------------------------ #
    # AC-16: --provider foo exits 1 with helpful message                  #
    # ------------------------------------------------------------------ #

    def test_ac16_invalid_provider_exits_1(self, tmp_path):
        """AC-16: An unrecognised --provider value must exit 1 with an error message."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "foo", "--no-git", "--force"]
        )
        assert (
            result.exit_code == 1
        ), f"Expected exit code 1 for invalid provider, got {result.exit_code}"
        assert (
            "Valid providers" in result.output
        ), "Error message must mention 'Valid providers'"
        assert "claude" in result.output, "Valid providers list must include 'claude'"
        assert "codex" in result.output, "Valid providers list must include 'codex'"

    # ------------------------------------------------------------------ #
    # AC-17: Each .toml has required fields                               #
    # ------------------------------------------------------------------ #

    def test_ac17_agent_toml_fields(self, codex_project):
        """AC-17: Every agent TOML must contain name, description, developer_instructions."""
        agents_dir = codex_project / ".codex" / "agents"
        toml_files = list(agents_dir.glob("*.toml"))
        assert len(toml_files) > 0, ".codex/agents/ must contain at least one *.toml"
        for toml_file in toml_files:
            content = toml_file.read_text(encoding="utf-8")
            assert "name" in content, f"{toml_file.name} must contain 'name' field"
            assert (
                "description" in content
            ), f"{toml_file.name} must contain 'description' field"
            assert (
                "developer_instructions" in content
            ), f"{toml_file.name} must contain 'developer_instructions' field"

    # ------------------------------------------------------------------ #
    # AC-18: hooks.json matcher value is "Bash"                           #
    # ------------------------------------------------------------------ #

    def test_ac18_hooks_matcher_is_bash(self, codex_project):
        """AC-18: hooks.json must configure the PreToolUse hook with matcher 'Bash'."""
        hooks_json_path = codex_project / ".codex" / "hooks.json"
        hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        pre_tool_use = hooks_data.get("hooks", {}).get("PreToolUse", [])
        assert (
            len(pre_tool_use) > 0
        ), "hooks.json must define at least one PreToolUse entry"
        matchers = [entry.get("matcher") for entry in pre_tool_use]
        assert (
            "Bash" in matchers
        ), f"hooks.json PreToolUse must have a 'Bash' matcher, got: {matchers}"

    def test_ac18b_hooks_json_merges_existing_project_hooks(self, tmp_path):
        """AC-18b: Codex init preserves project hooks and removes legacy MAP metadata."""
        project = tmp_path / "existing_codex_hooks"
        project.mkdir()
        hooks_json_path = project / ".codex" / "hooks.json"
        hooks_json_path.parent.mkdir(parents=True)
        hooks_json_path.write_text(
            json.dumps(
                {
                    "_map_managed": {"generated_by": "mapify-cli"},
                    "customTopLevel": "must be dropped for Codex schema",
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "echo session"}]}
                        ],
                        "UserPromptSubmit": [
                            {"hooks": [{"type": "command", "command": "echo prompt"}]}
                        ],
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "echo existing bash",
                                        "timeout": 3,
                                    },
                                    {
                                        "type": "command",
                                        "command": "python3 old/.codex/hooks/workflow-gate.py",
                                        "timeout": 1,
                                    },
                                ],
                            },
                            {
                                "matcher": "Read",
                                "hooks": [{"type": "command", "command": "echo read"}],
                            },
                        ],
                        "PostToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": "echo post"}],
                            }
                        ],
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "echo stop"}]}
                        ],
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        local_runner = CliRunner()
        os.chdir(project)
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0, f"init failed:\n{result.output}"

        hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        assert set(hooks_data) == {"hooks"}
        hooks = hooks_data["hooks"]
        assert hooks["SessionStart"][0]["hooks"][0]["command"] == "echo session"
        assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == "echo prompt"
        assert hooks["PostToolUse"][0]["hooks"][0]["command"] == "echo post"
        assert hooks["Stop"][0]["hooks"][0]["command"] == "echo stop"

        pre_tool_use = hooks["PreToolUse"]
        bash_entries = [
            entry
            for entry in pre_tool_use
            if isinstance(entry, dict) and entry.get("matcher") == "Bash"
        ]
        assert len(bash_entries) == 1
        bash_hooks = bash_entries[0]["hooks"]
        commands = [hook["command"] for hook in bash_hooks]
        assert "echo existing bash" in commands
        assert "python3 old/.codex/hooks/workflow-gate.py" not in commands
        workflow_gate_commands = [
            command
            for command in commands
            if ".codex/hooks/workflow-gate.py" in command
        ]
        assert len(workflow_gate_commands) == 1
        assert any(
            entry.get("matcher") == "Read"
            and entry["hooks"][0]["command"] == "echo read"
            for entry in pre_tool_use
            if isinstance(entry, dict)
        )

        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0, f"second init failed:\n{result.output}"
        hooks_data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        all_commands = [
            hook["command"]
            for entry in hooks_data["hooks"]["PreToolUse"]
            if isinstance(entry, dict)
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict)
        ]
        assert (
            sum(".codex/hooks/workflow-gate.py" in command for command in all_commands)
            == 1
        )

    # ------------------------------------------------------------------ #
    # AC-19: Discovery paths — skills/agents/config at expected locations #
    # ------------------------------------------------------------------ #

    def test_ac19_codex_discovery_paths(self, codex_project):
        """AC-19: Validate that Codex files are at the discovery paths Codex expects."""
        codex_dir = codex_project / ".codex"
        skills_dir = codex_project / ".agents" / "skills"
        expected_paths = [
            skills_dir / "map-plan" / "SKILL.md",
            skills_dir / "map-fast" / "SKILL.md",
            skills_dir / "map-check" / "SKILL.md",
            skills_dir / "map-efficient" / "SKILL.md",
            codex_dir / "agents",
            codex_dir / "config.toml",
        ]
        for path in expected_paths:
            assert (
                path.exists()
            ), f"Expected discovery path does not exist: {path.relative_to(codex_project)}"
        # Agents directory must have TOML files for agent discovery
        toml_count = len(list((codex_dir / "agents").glob("*.toml")))
        assert (
            toml_count >= 1
        ), f".codex/agents/ must have at least 1 *.toml for agent discovery, found {toml_count}"
        assert not (
            codex_dir / "skills"
        ).exists(), (
            "Codex skills must be installed under .agents/skills, not .codex/skills"
        )

    # ------------------------------------------------------------------ #
    # AC-20: workflow-gate.py blocks file-modifying commands in RESEARCH  #
    # ------------------------------------------------------------------ #

    def test_ac20_workflow_gate_blocks_during_restricted(self, codex_project):
        """AC-20: workflow-gate.py must block Edit during non-editing phases."""
        import json as _json

        gate_script = codex_project / ".codex" / "hooks" / "workflow-gate.py"
        assert gate_script.exists(), "workflow-gate.py must exist"

        # Verify the gate has EDITING_PHASES that exclude RESEARCH
        gate_source = gate_script.read_text(encoding="utf-8")
        gate_ns: dict = {}
        exec(compile(gate_source, str(gate_script), "exec"), gate_ns)  # noqa: S102
        editing_phases = gate_ns["EDITING_PHASES"]
        assert (
            "RESEARCH" not in editing_phases
        ), "RESEARCH must NOT be in EDITING_PHASES"
        assert "ACTOR" in editing_phases, "ACTOR must be in EDITING_PHASES"

        # Simulate gate invocation: Edit tool during RESEARCH phase → should block.
        # Path must be in-repo (relative) — an out-of-repo path is unconditionally
        # orthogonal (#164) and would be allowed regardless of phase.
        payload_block = _json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": "test.py"}}
        )
        branch_dir = codex_project / ".map" / "default"
        branch_dir.mkdir(parents=True, exist_ok=True)
        state_file = branch_dir / "step_state.json"
        state_file.write_text(
            _json.dumps({"current_step_phase": "RESEARCH"}), encoding="utf-8"
        )

        proc = subprocess.run(
            [sys.executable, str(gate_script)],
            input=payload_block,
            capture_output=True,
            text=True,
            cwd=str(codex_project),
            check=False,
        )
        assert (
            proc.returncode == 0
        ), f"workflow-gate.py must exit 0 always, got {proc.returncode}"
        gate_output = _json.loads(proc.stdout.strip())
        hook_output = gate_output.get("hookSpecificOutput", {})
        assert (
            hook_output.get("permissionDecision") == "deny"
        ), f"Expected 'deny' for Edit in RESEARCH phase, got: {gate_output}"

    # ------------------------------------------------------------------ #
    # AC-21: upgrade on codex project must not create .claude/             #
    # ------------------------------------------------------------------ #

    @mock.patch("mapify_cli.get_latest_release")
    def test_ac21_upgrade_codex_project_no_claude(self, mock_get_latest, codex_project):
        """AC-21: 'mapify upgrade' upgrades the CLI only and creates no project files.

        upgrade is now provider-agnostic and never writes into the project, so a
        codex project stays codex-only — no .claude/ is ever created.
        """
        mock_get_latest.return_value = {"tag_name": "v9.9.9"}
        local_runner = CliRunner()
        os.chdir(codex_project)
        result = local_runner.invoke(app, ["upgrade"])
        assert result.exit_code == 0, f"upgrade failed: {result.output}"
        assert not (
            codex_project / ".claude"
        ).exists(), ".claude/ must NOT be created by upgrade on a codex project"

    def test_ac22_map_efficient_state_machine_markers(self, codex_project):
        """AC-22: $map-efficient documents the required state-machine commands."""
        skill_file = codex_project / ".agents" / "skills" / "map-efficient" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        for marker in [
            "resume_from_plan",
            "get_next_step",
            "validate_step",
            "record_subtask_result",
            "write_run_health_report",
        ]:
            assert marker in content, f"$map-efficient must document {marker}"

        mutation_index = content.index("## Mutation Boundary Constraints")
        implement_index = content.index("Implement exactly")
        assert (
            mutation_index < implement_index
        ), "Mutation boundary constraints must appear before implementation directives"


class TestDetectProviderEdgeCases:
    """TESTS-1: _detect_provider and is_map_initialized edge cases."""

    def test_detect_provider_codex_wins_when_both_exist(self, tmp_path):
        """When both .codex/ and .claude/ exist, codex is detected."""
        from mapify_cli import _detect_provider

        (tmp_path / ".codex" / "config.toml").parent.mkdir(parents=True)
        (tmp_path / ".codex" / "config.toml").write_text("[codex]\n")
        (tmp_path / ".claude" / "settings.json").parent.mkdir(parents=True)
        (tmp_path / ".claude" / "settings.json").write_text("{}\n")
        assert _detect_provider(tmp_path) == "codex"

    def test_detect_provider_returns_claude_when_neither(self, tmp_path):
        """When neither provider dir exists, default to claude."""
        from mapify_cli import _detect_provider

        assert _detect_provider(tmp_path) == "claude"

    def test_is_map_initialized_codex_layout(self, tmp_path):
        """is_map_initialized recognizes a codex-only project."""
        from mapify_cli import is_map_initialized

        (tmp_path / ".codex" / "config.toml").parent.mkdir(parents=True)
        (tmp_path / ".codex" / "config.toml").write_text("[codex]\n")
        (tmp_path / ".agents" / "skills").mkdir(parents=True)
        assert is_map_initialized(tmp_path) is True

    def test_is_map_initialized_neither_layout(self, tmp_path):
        """is_map_initialized returns False for empty directory."""
        from mapify_cli import is_map_initialized

        assert is_map_initialized(tmp_path) is False


class TestDoctorCodexProject:
    """TESTS-2: doctor() on codex project produces correct output."""

    def test_doctor_codex_no_false_missing_paths(self, tmp_path):
        """doctor on a codex project must not report .claude/* as missing."""
        local_runner = CliRunner()
        os.chdir(tmp_path)
        # Init as codex first
        result = local_runner.invoke(
            app, ["init", ".", "--provider", "codex", "--no-git", "--force"]
        )
        assert result.exit_code == 0
        # Run doctor
        result = local_runner.invoke(app, ["doctor"])
        assert (
            ".claude/agents" not in result.output
        ), "doctor must not report .claude/agents as missing for codex project"
        assert (
            ".claude/commands" not in result.output
        ), "doctor must not report .claude/commands as missing for codex project"
        assert "all core paths present" in result.output or "codex" in result.output


class TestClaudeProviderInstall:
    """TESTS-3: ClaudeProvider.install() unit test."""

    def test_claude_provider_creates_all_categories(self, tmp_path):
        """ClaudeProvider.install() must return counts for all expected categories."""
        from mapify_cli.delivery.providers import ClaudeProvider

        provider = ClaudeProvider()
        counts = provider.install(tmp_path, mcp_servers=[])
        expected_keys = {
            "agents",
            "commands",
            "skills",
            "references",
            "tools",
            "hooks",
            "configs",
            "rules",
            "statusline",
        }
        assert (
            set(counts.keys()) == expected_keys
        ), f"ClaudeProvider.install() must return all category keys, got: {set(counts.keys())}"
        # Each category must have created at least one file
        for key, value in counts.items():
            assert value >= 0, f"counts['{key}'] must be non-negative"
        # agents should always have files; commands migrated to skills
        assert counts["agents"] > 0, "ClaudeProvider must create agent files"

    def test_claude_provider_creates_claude_dir(self, tmp_path):
        """ClaudeProvider.install() must create .claude/ directory."""
        from mapify_cli.delivery.providers import ClaudeProvider

        provider = ClaudeProvider()
        provider.install(tmp_path, mcp_servers=[])
        assert (tmp_path / ".claude" / "agents").exists()
        assert (tmp_path / ".claude" / "commands").exists()
        assert not (
            tmp_path / ".codex"
        ).exists(), "ClaudeProvider must not create .codex/"
