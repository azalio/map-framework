"""Provider abstraction for MAP Framework delivery."""

from __future__ import annotations

import abc
from pathlib import Path

from mapify_cli.delivery.file_copier import (
    create_agent_files,
    create_command_files,
    create_config_files,
    create_hook_files,
    create_map_tools,
    create_reference_files,
    create_rules_dir,
    create_skill_files,
    ensure_map_statusline,
)


class BaseProvider(abc.ABC):
    """Abstract base for delivery providers."""

    @abc.abstractmethod
    def install(
        self,
        project_path: Path,
        *,
        mcp_servers: list[str] | None = None,
    ) -> dict[str, int]:
        """Install framework files into target project.

        Args:
            project_path: Root directory of the target project.
            mcp_servers: Optional list of MCP server names to configure.

        Returns:
            Mapping of category name to number of files created.
        """


class ClaudeProvider(BaseProvider):
    """Claude Code provider — delegates to existing file_copier functions.

    Not wired into interactive ``init`` (which needs per-step tracker
    feedback).  Available for programmatic / future upgrade use.
    """

    def install(
        self,
        project_path: Path,
        *,
        mcp_servers: list[str] | None = None,
    ) -> dict[str, int]:
        """Install Claude Code MAP files into target project."""
        servers = mcp_servers or []
        # Statusline wiring is a Claude-only resource decision and stays inside
        # this provider so it never leaks into the Codex install path. It is
        # non-destructive: skips when the user already configured a statusLine.
        statusline = ensure_map_statusline(project_path)
        return {
            "agents": create_agent_files(project_path, servers),
            "commands": create_command_files(project_path),
            "skills": create_skill_files(project_path),
            "references": create_reference_files(project_path),
            "tools": create_map_tools(project_path),
            "hooks": create_hook_files(project_path),
            "configs": create_config_files(project_path),
            "rules": create_rules_dir(project_path),
            "statusline": 1 if statusline.wired else 0,
        }


class CodexProvider(BaseProvider):
    """Codex CLI provider — installs .agents/.codex files from templates."""

    def install(
        self,
        project_path: Path,
        *,
        mcp_servers: list[str] | None = None,
    ) -> dict[str, int]:
        """Install Codex MAP files into target project.

        Args:
            project_path: Root directory of the target project.
            mcp_servers: Ignored (Codex uses TOML agent config, not MCP JSON).

        Returns:
            Mapping of category name to number of files created.
        """
        # Codex configures agents via TOML, not MCP JSON: the interface
        # parameter is accepted for BaseProvider conformance but intentionally
        # unused. `del` documents that and satisfies reportUnusedParameter.
        del mcp_servers
        # Deferred to avoid circular import (codex_copier imports from file_copier)
        from mapify_cli.delivery.codex_copier import create_codex_files

        return create_codex_files(project_path)
