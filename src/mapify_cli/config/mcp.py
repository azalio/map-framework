"""MCP server configuration management for MAP Framework."""

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from mapify_cli.cli_ui import console


def create_mcp_config(project_path: Path, mcp_servers: list[str]) -> None:
    """Create MCP configuration file"""
    config: dict[str, Any] = {
        "mcp_servers": {},
        "agent_mcp_mappings": {
            "task-decomposer": [],
            "actor": [],
            "monitor": [],
            "predictor": [],
            "evaluator": [],
            "reflector": [],
            "documentation-reviewer": [],
            "research-agent": [],
            "final-verifier": [],
        },
        "workflow_settings": {
            "always_retrieve_knowledge": True,
            "store_successful_patterns": True,
            "use_professional_review": True,
            "enable_sequential_thinking": True,
            "knowledge_cache_ttl": 3600,
        },
    }

    # Add server configurations
    server_configs = {
        "sequential-thinking": {
            "enabled": True,
            "description": "Chain-of-thought reasoning",
            "config": {
                "max_thoughts": 10,
                "branch_exploration": True,
                "hypothesis_verification": True,
            },
        },
    }

    # Add selected servers
    for server in mcp_servers:
        if server in server_configs:
            config["mcp_servers"][server] = server_configs[server]

    # Update agent mappings based on selected servers
    if "sequential-thinking" in mcp_servers:
        for agent in [
            "task-decomposer",
            "monitor",
            "evaluator",
            "reflector",
        ]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("sequential-thinking")

    # Write config file
    config_file = project_path / ".claude" / "mcp_config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2))


# =============================================================================
# Project-level .mcp.json functions (for Claude Code MCP server configuration)
# =============================================================================


def build_standard_mcp_servers() -> dict[str, dict[str, Any]]:
    """Build standard MCP server configurations for Claude Code .mcp.json format.

    Returns dict mapping server names to their Claude Code MCP configurations.
    Uses verified configurations from production installations.

    Note: These configs are for the project-level .mcp.json file that Claude Code
    reads, separate from the internal .claude/mcp_config.json.
    """
    return {
        "sequential-thinking": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        },
    }


def read_project_mcp_json(path: Path) -> dict[str, Any] | None:
    """Read .mcp.json from project root.

    Args:
        path: Path to .mcp.json file

    Returns:
        Parsed JSON dict if file exists and is valid, None otherwise

    Handles:
        - File not found (returns None)
        - Invalid JSON (logs warning, creates backup, returns None)
        - Permission errors (logs warning, returns None)
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError as e:
        console.print(f"[yellow]Warning:[/yellow] Invalid JSON in {path.name}: {e}")
        # Create backup with timestamp + UUID to prevent race conditions
        # UUID ensures unique names even with concurrent processes
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        backup_path = path.with_suffix(f".backup.{timestamp}_{unique_id}.json")
        try:
            if path.exists():  # Check before rename to handle concurrent processes
                path.rename(backup_path)
                console.print(
                    f"[dim]Backed up corrupted file to {backup_path.name}[/dim]"
                )
            else:
                console.print(
                    "[dim]Corrupted file already removed by another process[/dim]"
                )
        except OSError as backup_error:
            console.print(
                f"[yellow]Warning:[/yellow] Could not create backup: {backup_error}"
            )
        return None
    except (OSError, PermissionError) as e:
        console.print(f"[yellow]Warning:[/yellow] Cannot read {path.name}: {e}")
        return None


def write_project_mcp_json(path: Path, config: dict[str, Any]) -> None:
    """Write .mcp.json to project root with proper formatting.

    Args:
        path: Path to .mcp.json file
        config: Configuration dict to write

    Raises:
        OSError: If write fails (permission, disk space, etc.)

    Format:
        - indent=2 for readability
        - UTF-8 encoding
        - Newline at end of file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config, indent=2, ensure_ascii=False)
    path.write_text(content + "\n", encoding="utf-8")


def merge_mcp_json(
    existing: dict[str, Any], new_servers: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge new MCP servers into existing .mcp.json configuration.

    Args:
        existing: Existing .mcp.json content (may be empty dict)
        new_servers: Dict mapping server names to their configs

    Returns:
        Merged configuration with existing servers preserved

    Behavior:
        - Preserves existing mcpServers entries (user customizations)
        - Only adds new servers that don't exist
        - Preserves other top-level keys (e.g., custom settings)
    """
    result = copy.deepcopy(existing)

    # Ensure mcpServers key exists
    if "mcpServers" not in result:
        result["mcpServers"] = {}

    # Merge servers - existing entries take precedence (never overwrite user configs)
    for server_name, server_config in new_servers.items():
        if server_name not in result["mcpServers"]:
            result["mcpServers"][server_name] = server_config

    return result


def create_or_merge_project_mcp_json(
    project_path: Path, mcp_servers: list[str]
) -> None:
    """Create or merge .mcp.json in project root for Claude Code.

    Args:
        project_path: Project root directory
        mcp_servers: List of MCP server names to configure (e.g., ["sequential-thinking"])

    Behavior:
        - If mcp_servers is empty: No file created/modified (early return)
        - If .mcp.json exists: merge new servers (preserve existing)
        - If .mcp.json missing: create new with selected servers
        - Console output shows whether created or merged
        - Existing user servers NEVER overwritten
        - System directories (/etc, /sys, etc.) are rejected for safety

    This creates the project-level .mcp.json that Claude Code uses,
    separate from the internal .claude/mcp_config.json.

    Raises:
        typer.Exit(1): On file write errors or invalid paths
    """
    # Path validation - resolve to prevent traversal
    resolved_path = project_path.resolve()

    # Validate against system directories (defense-in-depth)
    forbidden_prefixes = ["/etc", "/sys", "/proc", "/boot", "/dev", "/var/run"]
    resolved_str = str(resolved_path)
    for forbidden in forbidden_prefixes:
        if resolved_str == forbidden or resolved_str.startswith(forbidden + "/"):
            console.print(
                f"[red]Error:[/red] Cannot initialize in system directory {forbidden}"
            )
            raise typer.Exit(1)

    mcp_json_path = resolved_path / ".mcp.json"

    # Build standard server configs for requested servers
    all_standard_servers = build_standard_mcp_servers()
    selected_servers = {
        name: config
        for name, config in all_standard_servers.items()
        if name in mcp_servers
    }

    if not selected_servers:
        # No servers to configure
        return

    # Read existing config if present
    existing_config = read_project_mcp_json(mcp_json_path)

    try:
        if existing_config is not None:
            # Merge mode - preserve existing entries
            merged_config = merge_mcp_json(existing_config, selected_servers)
            write_project_mcp_json(mcp_json_path, merged_config)

            # Count how many new servers were added
            existing_servers = existing_config.get("mcpServers", {})
            new_count = len([s for s in selected_servers if s not in existing_servers])
            if new_count > 0:
                console.print(
                    f"[green]✓[/green] Merged {new_count} new server(s) into .mcp.json"
                )
            else:
                console.print(
                    "[green]✓[/green] .mcp.json already contains all requested servers"
                )
        else:
            # Create mode - new file
            new_config: dict[str, Any] = {"mcpServers": selected_servers}
            write_project_mcp_json(mcp_json_path, new_config)
            console.print(
                f"[green]✓[/green] Created .mcp.json with {len(selected_servers)} server(s)"
            )

        # Show which servers are configured
        console.print(
            f"[dim]  Configured: {', '.join(sorted(selected_servers.keys()))}[/dim]"
        )
    except OSError as e:
        console.print(f"[red]Error:[/red] Failed to write .mcp.json: {e}")
        raise typer.Exit(1) from e
