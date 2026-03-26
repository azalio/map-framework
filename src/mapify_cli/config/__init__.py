"""Configuration management for MAP Framework.

Handles settings, permissions, MCP server configuration, and project config.
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
from mapify_cli.config.project_config import (
    MapConfig,
    load_map_config,
    generate_default_config,
    write_default_config,
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
    "MapConfig",
    "load_map_config",
    "generate_default_config",
    "write_default_config",
]
