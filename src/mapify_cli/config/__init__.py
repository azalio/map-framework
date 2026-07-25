"""Configuration management for MAP Framework.

Handles settings, permissions, MCP server configuration, and project config.
"""

from mapify_cli.config.mcp import (
    build_standard_mcp_servers,
    create_mcp_config,
    create_or_merge_project_mcp_json,
    merge_mcp_json,
    read_project_mcp_json,
    write_project_mcp_json,
)
from mapify_cli.config.project_config import (
    MapConfig,
    generate_default_config,
    load_map_config,
    write_default_config,
)
from mapify_cli.config.settings import (
    configure_global_permissions,
    create_or_merge_project_settings_local,
)

__all__ = [
    "MapConfig",
    "build_standard_mcp_servers",
    "configure_global_permissions",
    "create_mcp_config",
    "create_or_merge_project_mcp_json",
    "create_or_merge_project_settings_local",
    "generate_default_config",
    "load_map_config",
    "merge_mcp_json",
    "read_project_mcp_json",
    "write_default_config",
    "write_project_mcp_json",
]
