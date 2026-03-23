"""Configuration management for MAP Framework.

Handles settings, permissions, and MCP server configuration.
"""

from mapify_cli.config.settings import (
    configure_global_permissions,
    create_or_merge_project_settings_local,
)
from mapify_cli.config.mcp import (
    create_mcp_config,
    build_standard_mcp_servers,
    read_project_mcp_json,
    write_project_mcp_json,
    merge_mcp_json,
    create_or_merge_project_mcp_json,
)

__all__ = [
    "configure_global_permissions",
    "create_or_merge_project_settings_local",
    "create_mcp_config",
    "build_standard_mcp_servers",
    "read_project_mcp_json",
    "write_project_mcp_json",
    "merge_mcp_json",
    "create_or_merge_project_mcp_json",
]
