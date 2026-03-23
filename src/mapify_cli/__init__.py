#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer",
#     "rich",
#     "platformdirs",
#     "readchar",
#     "httpx",
#     "truststore",
# ]
# ///
"""
Mapify CLI - Setup tool for MAP Framework projects

Usage:
    uvx mapify init <project-name>
    uvx mapify init .

Or install globally:
    uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli
    mapify init <project-name>
    mapify check
"""

__version__ = "3.5.0"

import copy
import os
import subprocess
import sys
import shutil
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import typer
import httpx
import readchar
import ssl

try:
    import truststore

    HAS_TRUSTSTORE = True
except ImportError:
    HAS_TRUSTSTORE = False

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.align import Align
from rich.table import Table
from rich.tree import Tree
from typer.core import TyperGroup


# Create secure SSL context with proper fallback
def create_ssl_context():
    """Create SSL context with proper certificate validation."""
    try:
        if HAS_TRUSTSTORE:
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            return context
    except Exception:
        pass

    # Fallback to standard SSL context
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


ssl_context = create_ssl_context()


# Constants
MCP_SERVER_CHOICES = {
    "all": "All available MCP servers",
    "essential": "Essential (sequential-thinking, deepwiki)",
    "custom": "Select individually",
    "none": "Skip MCP setup",
}

INDIVIDUAL_MCP_SERVERS = {
    "sequential-thinking": "Chain-of-thought reasoning",
    "deepwiki": "GitHub repository intelligence",
}

console = Console()


# Extracted submodules (v3.5.0 platform refactor)
from mapify_cli.cli_ui import (
    StepTracker,
    BannerGroup,
    get_key,
    select_with_arrows,
    select_multiple_with_arrows,
    show_banner,
    BANNER,
    TAGLINE,
)
from mapify_cli.delivery import (
    create_task_decomposer_content,
    create_actor_content,
    create_monitor_content,
    create_predictor_content,
    create_evaluator_content,
    create_reflector_content,
    create_documentation_reviewer_content,
    create_agent_files,
    create_reference_files,
    create_command_files,
    create_skill_files,
    create_hook_files,
    create_config_files,
    create_commands_dir,
    create_map_tools,
)
from mapify_cli.config import (
    configure_global_permissions,
    create_or_merge_project_settings_local,
    create_mcp_config,
    build_standard_mcp_servers,
    read_project_mcp_json,
    write_project_mcp_json,
    merge_mcp_json,
    create_or_merge_project_mcp_json,
)


app = typer.Typer(
    name="mapify",
    help="Setup tool for MAP Framework projects",
    add_completion=False,
    invoke_without_command=True,
    cls=BannerGroup,
)

# Create subcommand groups
validate_app = typer.Typer(name="validate", help="Validate task dependency graphs")

app.add_typer(validate_app, name="validate")


def version_callback(value: bool):
    """Callback to show version and exit."""
    if value:
        console.print(f"mapify-cli version {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
):
    """Show banner when no subcommand is provided."""
    if (
        ctx.invoked_subcommand is None
        and "--help" not in sys.argv
        and "-h" not in sys.argv
        and not version
    ):
        show_banner()
        console.print(
            Align.center("[dim]Run 'mapify --help' for usage information[/dim]")
        )
        console.print()


def check_tool(tool: str) -> bool:
    """Check if a tool is installed."""
    # Special handling for Claude CLI
    if tool == "claude":
        claude_local_path = Path.home() / ".claude" / "local" / "claude"
        if claude_local_path.exists() and claude_local_path.is_file():
            return True

    return shutil.which(tool) is not None


def check_mcp_server(server: str) -> bool:
    """Check if an MCP server is recognized by this installation."""
    return server in build_standard_mcp_servers()


def is_debug_enabled(debug_flag: Optional[bool] = None) -> bool:
    """
    Check if debug mode is enabled via CLI flag or environment variable.

    Args:
        debug_flag: CLI --debug flag value (None, True, or False)

    Returns:
        True if debug logging should be enabled
    """
    # CLI flag takes precedence over environment variable
    if debug_flag is not None:
        return debug_flag

    # Check MAP_DEBUG environment variable
    env_debug = os.environ.get("MAP_DEBUG", "").lower()
    return env_debug in ("true", "1", "yes", "on")


def get_templates_dir() -> Path:
    """Get the path to bundled templates directory."""
    import importlib.resources

    try:
        # Python 3.11+ with importlib.resources.files
        if hasattr(importlib.resources, "files"):
            return Path(str(importlib.resources.files("mapify_cli") / "templates"))
    except Exception:
        pass

    # Fallback to module directory
    module_dir = Path(__file__).parent
    templates_dir = module_dir / "templates"
    if templates_dir.exists():
        return templates_dir

    # Development mode - check parent directories
    for parent in [module_dir.parent, module_dir.parent.parent]:
        templates_dir = parent / "templates"
        if templates_dir.exists():
            return templates_dir

    raise RuntimeError("Templates directory not found. Please reinstall mapify-cli.")


def count_template_markdown_files(template_subdir: str) -> int:
    """Count shipped markdown templates in a subdirectory."""
    template_dir = get_templates_dir() / template_subdir
    if not template_dir.exists():
        return 0
    return len([path for path in template_dir.glob("*.md") if path.is_file()])


def count_agent_templates() -> int:
    """Count shipped agent templates, excluding documentation files."""
    template_dir = get_templates_dir() / "agents"
    if not template_dir.exists():
        return 0

    exclude_files = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}
    return len(
        [
            path
            for path in template_dir.glob("*.md")
            if path.is_file() and path.name not in exclude_files
        ]
    )


def count_command_templates() -> int:
    """Count shipped slash command templates."""
    return count_template_markdown_files("commands")


def count_project_markdown_files(
    directory: Path, exclude_files: Optional[set[str]] = None
) -> int:
    """Count markdown files in a project directory."""
    if not directory.exists():
        return 0
    exclude_files = exclude_files or set()
    return len(
        [
            path
            for path in directory.glob("*.md")
            if path.is_file() and path.name not in exclude_files
        ]
    )


def is_map_initialized(project_path: Path) -> bool:
    """Return True when the current directory looks like a MAP project."""
    required_paths = [
        project_path / ".claude" / "agents",
        project_path / ".claude" / "commands",
        project_path / ".claude" / "settings.json",
        project_path / ".claude" / "workflow-rules.json",
    ]
    return all(path.exists() for path in required_paths)


def get_project_health(project_path: Path) -> Dict[str, Any]:
    """Collect project health diagnostics for check/doctor commands."""
    agent_exclude = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}
    current_branch = sanitize_identifier(get_current_branch_name())
    branch_dir = project_path / ".map" / current_branch
    required_paths = {
        ".claude/agents": project_path / ".claude" / "agents",
        ".claude/commands": project_path / ".claude" / "commands",
        ".claude/settings.json": project_path / ".claude" / "settings.json",
        ".claude/workflow-rules.json": project_path / ".claude" / "workflow-rules.json",
        ".map/scripts": project_path / ".map" / "scripts",
    }
    missing_paths = [name for name, path in required_paths.items() if not path.exists()]

    agents_dir = project_path / ".claude" / "agents"
    commands_dir = project_path / ".claude" / "commands"
    mcp_json_path = project_path / ".mcp.json"
    internal_mcp_path = project_path / ".claude" / "mcp_config.json"
    branch_artifact_files = [
        "qa-001.md",
        "verification-summary.md",
        "pr-draft.md",
    ]
    numbered_artifact_prefixes = ["plan-review", "code-review"]

    mcp_json_ok = False
    if mcp_json_path.exists():
        mcp_json_ok = read_project_mcp_json(mcp_json_path) is not None

    return {
        "initialized": is_map_initialized(project_path),
        "missing_paths": missing_paths,
        "installed_agents": count_project_markdown_files(agents_dir, agent_exclude),
        "installed_commands": count_project_markdown_files(commands_dir),
        "expected_agents": count_agent_templates(),
        "expected_commands": count_command_templates(),
        "has_project_mcp": mcp_json_path.exists(),
        "project_mcp_valid": mcp_json_ok,
        "has_internal_mcp": internal_mcp_path.exists(),
        "current_branch": current_branch,
        "branch_workspace_exists": branch_dir.exists(),
        "branch_workspace_files": (
            sorted(path.name for path in branch_dir.iterdir() if path.is_file())
            if branch_dir.exists()
            else []
        ),
        "branch_artifact_files": branch_artifact_files,
        "numbered_artifact_prefixes": numbered_artifact_prefixes,
        "expected_branch_artifact_count": len(branch_artifact_files)
        + len(numbered_artifact_prefixes),
        "branch_artifact_count": (
            len(
                [name for name in branch_artifact_files if (branch_dir / name).exists()]
            )
            + sum(
                1
                for prefix in numbered_artifact_prefixes
                if any(branch_dir.glob(f"{prefix}-*.md"))
            )
            if branch_dir.exists()
            else 0
        ),
    }


def parse_version(version: str) -> tuple[int, ...]:
    """Parse a semantic-ish version string into an integer tuple."""
    cleaned = version.strip().lstrip("v")
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def sanitize_identifier(value: str, fallback: str = "main") -> str:
    """Sanitize a user or branch supplied identifier for filesystem use."""
    sanitized = value.strip().replace("/", "-")
    sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in sanitized)
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    sanitized = sanitized.strip("-.")
    return sanitized or fallback


def get_current_branch_name() -> str:
    """Return current git branch name, or 'main' when unavailable."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        branch = result.stdout.strip()
        return branch or "main"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "main"


def get_branch_workspace_dir(project_path: Path, branch: Optional[str] = None) -> Path:
    """Return the branch-scoped MAP workspace directory."""
    branch_name = sanitize_identifier(branch or get_current_branch_name())
    return project_path / ".map" / branch_name


def get_branch_artifact_templates() -> Dict[str, str]:
    """Return artifact templates aligned to MAP branch workspaces."""
    return {
        "code-review-001.md": "# Code Review 001\n\n## Scope\n\n## Findings\n\n### High\n\n### Medium\n\n### Low\n\n## Verdict\n- [ ] Ready\n- [ ] Needs revision\n",
        "qa-001.md": "# QA 001\n\n## Commands Run\n\n## Expected Result\n\n## Actual Result\n\n## Follow-ups\n",
        "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Rollback\n",
    }


def initialize_branch_workspace(
    project_path: Path, branch: Optional[str] = None
) -> Path:
    """Create branch-scoped planning artifacts inside `.map/<branch>/`."""
    branch_name = sanitize_identifier(branch or get_current_branch_name())
    workspace_dir = get_branch_workspace_dir(project_path, branch_name)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    for file_name, content in get_branch_artifact_templates().items():
        destination = workspace_dir / file_name
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")

    return workspace_dir


def get_branch_workspace_status(
    project_path: Path, branch: Optional[str] = None
) -> Dict[str, Any]:
    """Collect status information for branch-scoped planning artifacts."""
    branch_name = sanitize_identifier(branch or get_current_branch_name())
    workspace_dir = get_branch_workspace_dir(project_path, branch_name)
    expected_files = list(get_branch_artifact_templates().keys())
    existing_files = (
        sorted(path.name for path in workspace_dir.iterdir())
        if workspace_dir.exists()
        else []
    )
    missing_files = [name for name in expected_files if name not in existing_files]
    return {
        "branch": branch_name,
        "path": workspace_dir,
        "exists": workspace_dir.exists(),
        "existing_files": existing_files,
        "missing_files": missing_files,
        "is_complete": workspace_dir.exists() and not missing_files,
    }


def init_git_repo(project_path: Path, quiet: bool = False) -> bool:
    """Initialize a git repository"""
    try:
        original_cwd = Path.cwd()
        os.chdir(project_path)
        if not quiet:
            console.print("[cyan]Initializing git repository...[/cyan]")

        # Initialize repository
        subprocess.run(["git", "init"], check=True, capture_output=True)

        # Check if user has configured git identity
        try:
            user_email = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

            user_name = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

            if not user_email or not user_name:
                if not quiet:
                    console.print("[yellow]Git identity not configured.[/yellow]")
                    console.print(
                        "Setting temporary git identity for initial commit..."
                    )

                # Set temporary identity for this repository only
                subprocess.run(
                    [
                        "git",
                        "config",
                        "--local",
                        "user.email",
                        "map-framework@example.com",
                    ],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "config", "--local", "user.name", "MAP Framework"],
                    check=True,
                    capture_output=True,
                )

                if not quiet:
                    console.print(
                        "[yellow]Note: Please configure your git identity with:[/yellow]"
                    )
                    console.print(
                        "  git config --global user.email 'your.email@example.com'"
                    )
                    console.print("  git config --global user.name 'Your Name'")
        except subprocess.CalledProcessError:
            # If we can't check config, set temporary values
            subprocess.run(
                ["git", "config", "--local", "user.email", "map-framework@example.com"],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "--local", "user.name", "MAP Framework"],
                check=False,
                capture_output=True,
            )

        # Add files and create initial commit
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Try to commit
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit from MAP Framework"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            # Check if it's because there are no changes (all files might be ignored)
            if (
                "nothing to commit" in result.stdout
                or "nothing to commit" in result.stderr
            ):
                if not quiet:
                    console.print(
                        "[yellow]⚠[/yellow] No files to commit (check .gitignore)"
                    )
                return True
            else:
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, result.stdout, result.stderr
                )

        if not quiet:
            console.print("[green]✓[/green] Git repository initialized")
        return True
    except subprocess.CalledProcessError as e:
        if not quiet:
            error_msg = str(e)
            if hasattr(e, "stderr") and e.stderr:
                error_msg = e.stderr
            console.print(f"[red]Error initializing git repository:[/red] {error_msg}")
            console.print(
                "[yellow]Tip: You can skip git initialization with --no-git[/yellow]"
            )
        return False
    except FileNotFoundError:
        if not quiet:
            console.print("[red]Git is not installed or not in PATH.[/red]")
            console.print(
                "[yellow]Please install git or use --no-git to skip repository initialization[/yellow]"
            )
        return False
    finally:
        os.chdir(original_cwd)


def is_git_repo(path: Optional[Path] = None) -> bool:
    """Check if the specified path is inside a git repository"""
    if path is None:
        path = Path.cwd()

    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            cwd=path,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def is_command(cmd_list: List[str]) -> bool:
    """Check if a command exists on the system."""
    if not cmd_list:
        return False
    try:
        subprocess.run(["which", cmd_list[0]], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_latest_release(owner: str, repo: str) -> Optional[Dict[str, Any]]:
    """Get the latest release from GitHub."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        with httpx.Client(verify=create_ssl_context()) as client:
            response = client.get(url)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return None


@app.command()
def init(
    project_name: Optional[str] = typer.Argument(
        None, help="Name for your new project directory (use '.' for current directory)"
    ),
    mcp: str = typer.Option(
        "all",
        "--mcp",
        help="MCP server installation (default: all). Options: all, essential, none, or comma-separated list (e.g. sequential-thinking,deepwiki)",
    ),
    no_git: bool = typer.Option(
        False, "--no-git", help="Skip git repository initialization"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force merge/overwrite when using '.' in non-empty directory",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Enable debug logging (creates .map/logs/workflow_*.log)"
    ),
):
    """
    Initialize a new MAP Framework project.

    This command will:
    1. Check that required tools are installed
    2. Create MCP configuration files
    3. Install MCP servers (defaults to all available servers)
    4. Create MAP agents and commands
    5. Initialize a git repository (optional)

    Examples:
        mapify init my-project              # Installs all MCP servers
        mapify init my-project --mcp none   # Skip MCP installation
        mapify init my-project --mcp essential
        mapify init my-project --mcp "sequential-thinking,deepwiki"
        mapify init .
        mapify init . --force  # Force init in non-empty current directory
        mapify init --debug  # Enable workflow logging
    """
    # Show banner
    show_banner()

    # Initialize workflow logger if debug mode is enabled
    workflow_logger = None
    if is_debug_enabled(debug):
        from mapify_cli.workflow_logger import MapWorkflowLogger

        workflow_logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = workflow_logger.start_session(
            task_id=f"mapify_init_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        console.print(f"[dim]Debug logging enabled: {log_file}[/dim]")
        workflow_logger.log_event(
            "command_start",
            f"mapify init {project_name or '.'}",
            metadata={"debug": debug, "mcp": mcp},
        )

    # Handle '.' as shorthand for current directory
    use_current_dir = project_name == "."

    if use_current_dir:
        project_name = None

    # Validate arguments
    if not use_current_dir and not project_name:
        console.print(
            "[red]Error:[/red] Must specify either a project name or use '.' for current directory"
        )
        raise typer.Exit(1)

    # Determine project directory
    if use_current_dir:
        project_name = Path.cwd().name
        project_path = Path.cwd()

        # Check if current directory has any files
        existing_items = list(project_path.iterdir())
        if existing_items:
            console.print(
                f"[yellow]Warning:[/yellow] Current directory is not empty ({len(existing_items)} items)"
            )
            if not force:
                response = typer.confirm("Do you want to continue?")
                if not response:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    raise typer.Exit(0)
    else:
        # Type assertion: flow guarantees project_name is not None here
        # (checked at line 1931, and not in use_current_dir branch)
        assert project_name is not None, (
            "project_name must be set in non-current-dir mode"
        )
        project_path = Path(project_name).resolve()
        if project_path.exists():
            console.print(
                f"[red]Error:[/red] Directory '{project_name}' already exists"
            )
            raise typer.Exit(1)
        project_path.mkdir(parents=True)

    # Setup tracker
    tracker = StepTracker("Initialize MAP Framework Project")

    # Check tools
    tracker.add("check-tools", "Check required tools")
    tracker.start("check-tools")

    git_available = check_tool("git")
    claude_available = check_tool("claude")

    if claude_available:
        tracker.complete("check-tools", "git, claude")
    elif git_available:
        tracker.complete("check-tools", "git")
    else:
        tracker.complete("check-tools", "minimal")

    # Use Claude Code (the only supported AI assistant)
    tracker.add("ai-select", "Select AI assistant")
    selected_ai = "claude"
    tracker.complete("ai-select", selected_ai)

    # Select MCP servers
    tracker.add("mcp-select", "Select MCP servers")
    tracker.start("mcp-select")

    selected_mcp_servers = []

    if mcp == "all":
        selected_mcp_servers = list(INDIVIDUAL_MCP_SERVERS.keys())
    elif mcp == "essential":
        selected_mcp_servers = ["sequential-thinking", "deepwiki"]
    elif mcp == "none":
        selected_mcp_servers = []
    else:
        # Parse comma-separated list
        requested = [s.strip() for s in mcp.split(",") if s.strip()]
        invalid = [s for s in requested if s not in INDIVIDUAL_MCP_SERVERS]
        if invalid:
            console.print(
                f"[yellow]Warning:[/yellow] Unrecognized MCP servers ignored: {', '.join(invalid)}"
            )
            console.print(f"Valid servers: {', '.join(INDIVIDUAL_MCP_SERVERS.keys())}")
        selected_mcp_servers = [s for s in requested if s in INDIVIDUAL_MCP_SERVERS]

    tracker.complete("mcp-select", f"{len(selected_mcp_servers)} servers")

    # Create MAP files
    tracker.add("create-agents", "Create MAP agents")
    tracker.start("create-agents")
    agent_count = create_agent_files(project_path, selected_mcp_servers)
    agent_word = "agent" if agent_count == 1 else "agents"
    tracker.complete("create-agents", f"{agent_count} {agent_word}")

    tracker.add("create-commands", "Create slash commands")
    tracker.start("create-commands")
    command_count = create_command_files(project_path)
    command_word = "command" if command_count == 1 else "commands"
    tracker.complete("create-commands", f"{command_count} {command_word}")

    tracker.add("create-skills", "Create skills")
    tracker.start("create-skills")
    skill_count = create_skill_files(project_path)
    skill_word = "skill" if skill_count == 1 else "skills"
    tracker.complete("create-skills", f"{skill_count} {skill_word}")

    tracker.add("create-references", "Create reference files")
    tracker.start("create-references")
    ref_count = create_reference_files(project_path)
    ref_word = "file" if ref_count == 1 else "files"
    tracker.complete("create-references", f"{ref_count} {ref_word}")

    tracker.add("create-map-tools", "Create MAP tools")
    tracker.start("create-map-tools")
    tool_count = create_map_tools(project_path)
    tool_word = "script" if tool_count == 1 else "scripts"
    tracker.complete("create-map-tools", f"{tool_count} {tool_word}")

    tracker.add("create-hooks", "Create MAP hooks")
    tracker.start("create-hooks")
    hook_count = create_hook_files(project_path)
    hook_word = "hook" if hook_count == 1 else "hooks"
    tracker.complete("create-hooks", f"{hook_count} {hook_word}")

    tracker.add("create-configs", "Create config files")
    tracker.start("create-configs")
    config_count = create_config_files(project_path)
    config_word = "file" if config_count == 1 else "files"
    tracker.complete("create-configs", f"{config_count} {config_word}")

    # Create default .map/config.yaml (project-level settings)
    tracker.add("map-config", "Create .map/config.yaml")
    tracker.start("map-config")
    try:
        from mapify_cli.config.project_config import write_default_config

        config_path = write_default_config(project_path)
        tracker.complete("map-config", str(config_path.relative_to(project_path)))
    except Exception as e:
        tracker.error("map-config", f"skipped: {e}")

    if selected_mcp_servers:
        # Create internal MCP config (for MAP Framework agent mappings)
        tracker.add("mcp-config", "Create internal MCP config")
        tracker.start("mcp-config")
        create_mcp_config(project_path, selected_mcp_servers)
        tracker.complete("mcp-config", f"{len(selected_mcp_servers)} servers")

        # Create/merge project .mcp.json (for Claude Code MCP server registration)
        tracker.add("mcp-project", "Create/merge .mcp.json")
        tracker.start("mcp-project")
        create_or_merge_project_mcp_json(project_path, selected_mcp_servers)
        tracker.complete("mcp-project", "Claude Code MCP config")

    # Initialize git
    if not no_git and git_available:
        tracker.add("git", "Initialize git repository")
        tracker.start("git")
        if is_git_repo(project_path):
            tracker.complete("git", "existing repo")
        else:
            if init_git_repo(project_path, quiet=True):
                tracker.complete("git", "initialized")
            else:
                tracker.error("git", "failed")

    tracker.add("project-permissions", "Configure project approvals")
    tracker.start("project-permissions")
    create_or_merge_project_settings_local(project_path)
    tracker.complete("project-permissions", ".claude/settings.local.json")

    tracker.add("finalize", "Finalize")
    tracker.complete("finalize", "project ready")

    # Configure global permissions for read-only commands
    console.print()  # Add spacing
    configure_global_permissions()

    # Show final tree
    with Live(tracker.render(), console=console, transient=True) as live:
        tracker.attach_refresh(lambda: live.update(tracker.render()))

    console.print(tracker.render())
    console.print("\n[bold green]✅ Project ready![/bold green]")

    # Next steps
    steps_lines = []
    if not use_current_dir:
        steps_lines.append(
            f"1. Go to the project folder: [cyan]cd {project_name}[/cyan]"
        )
        step_num = 2
    else:
        steps_lines.append("1. You're already in the project directory!")
        step_num = 2

    steps_lines.append(f"{step_num}. Start using MAP commands with Claude Code:")
    steps_lines.append(
        "   • [cyan]/map-efficient[/] - Implement features with optimized workflow (recommended)"
    )
    steps_lines.append("   • [cyan]/map-debug[/] - Debug issue using MAP analysis")
    steps_lines.append(
        "   • [cyan]/map-fast[/] - Quick implementation with minimal validation"
    )
    steps_lines.append(
        "   • [cyan]/map-learn[/] - Extract lessons from completed workflows"
    )
    steps_lines.append(
        f"{step_num + 1}. Run [cyan]/map-plan[/cyan] first when you want branch-scoped research, spec, and plan artifacts in `.map/<branch>/`"
    )

    steps_panel = Panel(
        "\n".join(steps_lines), title="Next Steps", border_style="cyan", padding=(1, 2)
    )
    console.print()
    console.print(steps_panel)


@app.command()
def check(debug: bool = typer.Option(False, "--debug", help="Enable debug logging")):
    """Check that all required tools are installed."""
    # Initialize workflow logger if debug mode is enabled
    if is_debug_enabled(debug):
        from mapify_cli.workflow_logger import MapWorkflowLogger

        workflow_logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = workflow_logger.start_session(
            task_id=f"mapify_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        console.print(f"[dim]Debug logging enabled: {log_file}[/dim]")
        workflow_logger.log_event(
            "command_start", "mapify check", metadata={"debug": debug}
        )
    show_banner()
    console.print("[bold]Checking MAP Framework environment...[/bold]\n")

    tracker = StepTracker("Check Available Tools")

    tools = [
        ("git", "Git version control"),
        ("claude", "Claude Code CLI"),
    ]

    # Add tools to tracker
    for tool, description in tools:
        tracker.add(tool, description)

    # Check each tool
    results = {}
    for tool, description in tools:
        if check_tool(tool):
            tracker.complete(tool, "available")
            results[tool] = True
        else:
            tracker.error(tool, "not found")
            results[tool] = False

    health = get_project_health(Path.cwd())

    tracker.add("project", "Detect MAP project")
    if health["initialized"]:
        tracker.complete("project", "initialized")
    else:
        tracker.error("project", "not initialized")

    tracker.add("templates", "Inspect bundled templates")
    if health["expected_agents"] and health["expected_commands"]:
        tracker.complete(
            "templates",
            f"{health['expected_agents']} agents, {health['expected_commands']} commands",
        )
    else:
        tracker.error("templates", "missing bundled templates")

    tracker.add("mcp", "Check supported MCP servers")
    supported_servers = sorted(build_standard_mcp_servers().keys())
    tracker.complete("mcp", ", ".join(supported_servers) or "none")

    console.print(tracker.render())
    console.print()

    if all(results.values()) and health["initialized"]:
        console.print(
            "[bold green]All tools are installed! MAP Framework is ready to use.[/bold green]"
        )
    else:
        console.print("[yellow]MAP environment needs attention:[/yellow]")
        if not results.get("git"):
            console.print("  • Install git: https://git-scm.com/downloads")
        if not results.get("claude"):
            console.print(
                "  • Install Claude Code: https://docs.anthropic.com/en/docs/claude-code/setup"
            )
        if not health["initialized"]:
            console.print("  • Initialize this directory: mapify init .")


@app.command()
def doctor(debug: bool = typer.Option(False, "--debug", help="Enable debug logging")):
    """Run a detailed MAP project readiness diagnosis."""
    if is_debug_enabled(debug):
        from mapify_cli.workflow_logger import MapWorkflowLogger

        workflow_logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = workflow_logger.start_session(
            task_id=f"mapify_doctor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        console.print(f"[dim]Debug logging enabled: {log_file}[/dim]")
        workflow_logger.log_event(
            "command_start", "mapify doctor", metadata={"debug": debug}
        )

    show_banner()
    console.print("[bold]Running MAP doctor...[/bold]\n")

    project_path = Path.cwd()
    health = get_project_health(project_path)
    tracker = StepTracker("MAP Doctor")

    for tool_name, description in [
        ("git", "Git version control"),
        ("claude", "Claude Code CLI"),
    ]:
        tracker.add(tool_name, description)
        if check_tool(tool_name):
            tracker.complete(tool_name, "available")
        else:
            tracker.error(tool_name, "not found")

    tracker.add("project", "MAP project structure")
    if not health["missing_paths"]:
        tracker.complete("project", "all core paths present")
    else:
        tracker.error("project", f"missing {len(health['missing_paths'])} path(s)")

    tracker.add("templates", "Installed template counts")
    if (
        health["installed_agents"] == health["expected_agents"]
        and health["installed_commands"] == health["expected_commands"]
    ):
        tracker.complete(
            "templates",
            f"{health['installed_agents']}/{health['expected_agents']} agents, "
            f"{health['installed_commands']}/{health['expected_commands']} commands",
        )
    else:
        tracker.error(
            "templates",
            f"agents {health['installed_agents']}/{health['expected_agents']}, "
            f"commands {health['installed_commands']}/{health['expected_commands']}",
        )

    tracker.add("planning", "Branch workspace artifacts")
    if health["branch_workspace_exists"]:
        tracker.complete(
            "planning",
            f"branch {health['current_branch']}: {health['branch_artifact_count']}/{health['expected_branch_artifact_count']} artifacts",
        )
    else:
        tracker.error("planning", f"missing .map/{health['current_branch']}")

    tracker.add("mcp", "Project MCP configuration")
    if health["has_project_mcp"]:
        if health["project_mcp_valid"]:
            tracker.complete("mcp", ".mcp.json valid")
        else:
            tracker.error("mcp", ".mcp.json unreadable")
    elif health["has_internal_mcp"]:
        tracker.complete("mcp", "internal config only")
    else:
        tracker.complete("mcp", "no MCP config")

    console.print(tracker.render())
    console.print()

    details = Table(title="Doctor Details", show_header=True, header_style="bold cyan")
    details.add_column("Check")
    details.add_column("Status")
    details.add_column("Details")
    details.add_row(
        "Project",
        "OK" if health["initialized"] else "Needs init",
        ".claude + workflow configs detected"
        if health["initialized"]
        else "Run `mapify init .`",
    )
    details.add_row(
        "Agents",
        f"{health['installed_agents']}/{health['expected_agents']}",
        "Installed vs bundled agent templates",
    )
    details.add_row(
        "Commands",
        f"{health['installed_commands']}/{health['expected_commands']}",
        "Installed vs bundled slash commands",
    )
    details.add_row(
        "Planning",
        (
            f"{health['branch_artifact_count']}/{health['expected_branch_artifact_count']}"
            if health["branch_workspace_exists"]
            else "missing"
        ),
        f"Current branch workspace: .map/{health['current_branch']}/",
    )
    details.add_row(
        "MCP",
        "valid"
        if health["project_mcp_valid"]
        else ("present" if health["has_project_mcp"] else "not configured"),
        ".mcp.json status",
    )
    console.print(details)

    if health["missing_paths"]:
        console.print()
        console.print("[yellow]Missing core paths:[/yellow]")
        for path_name in health["missing_paths"]:
            console.print(f"  • {path_name}")


@app.command()
def upgrade():
    """Upgrade MAP agents to the latest version."""
    show_banner()
    project_path = Path.cwd()

    if not is_map_initialized(project_path):
        console.print(
            "[yellow]MAP Framework not initialized in this directory.[/yellow]"
        )
        console.print("Run: [cyan]mapify init .[/cyan]")
        raise typer.Exit(0)

    console.print("[cyan]Checking for updates...[/cyan]")
    latest_release = get_latest_release("azalio", "map-framework")
    latest_version = None

    if latest_release and latest_release.get("tag_name"):
        latest_version = latest_release["tag_name"].lstrip("v")
        if parse_version(latest_version) > parse_version(__version__):
            console.print(
                f"[yellow]New version available:[/yellow] {latest_version} "
                f"(installed {__version__})"
            )
            if latest_release.get("html_url"):
                console.print(f"Release: [cyan]{latest_release['html_url']}[/cyan]")
        else:
            console.print(
                f"[green]You are on the latest installed version ({__version__}).[/green]"
            )
    else:
        console.print(
            "[dim]Could not fetch release metadata; refreshing local templates anyway.[/dim]"
        )

    tracker = StepTracker("Upgrade MAP Framework Files")

    existing_project_mcp = read_project_mcp_json(project_path / ".mcp.json")
    existing_server_names = []
    if existing_project_mcp:
        existing_server_names = list(existing_project_mcp.get("mcpServers", {}).keys())

    tracker.add("agents", "Refresh agent templates")
    tracker.start("agents")
    agent_count = create_agent_files(project_path, existing_server_names)
    tracker.complete("agents", f"{agent_count} files")

    tracker.add("commands", "Refresh slash commands")
    tracker.start("commands")
    command_count = create_command_files(project_path)
    tracker.complete("commands", f"{command_count} files")

    tracker.add("skills", "Refresh skills")
    tracker.start("skills")
    skill_count = create_skill_files(project_path)
    tracker.complete("skills", f"{skill_count} folders")

    tracker.add("references", "Refresh reference files")
    tracker.start("references")
    ref_count = create_reference_files(project_path)
    tracker.complete("references", f"{ref_count} files")

    tracker.add("hooks", "Refresh shared hooks")
    tracker.start("hooks")
    hook_count = create_hook_files(project_path)
    tracker.complete("hooks", f"{hook_count} files")

    tracker.add("configs", "Refresh config files")
    tracker.start("configs")
    config_count = create_config_files(project_path)
    tracker.complete("configs", f"{config_count} files")

    tracker.add("permissions", "Merge local approvals")
    tracker.start("permissions")
    create_or_merge_project_settings_local(project_path)
    tracker.complete("permissions", "settings.local.json updated")

    if (project_path / ".claude" / "mcp_config.json").exists() or (
        project_path / ".mcp.json"
    ).exists():
        tracker.add("mcp", "Preserve MCP config")
        tracker.complete("mcp", "left unchanged")

    console.print()
    console.print(tracker.render())
    console.print()
    console.print("[bold green]Upgrade complete.[/bold green]")
    console.print(
        "[dim]Note: upgrade refreshes shipped MAP files but does not overwrite project-specific MCP selections.[/dim]"
    )


# Validate commands


@validate_app.command("graph")
def validate_graph(
    input_file: Optional[Path] = typer.Argument(
        None, help="JSON file to validate (or use stdin)"
    ),
    visualize: bool = typer.Option(
        False, "--visualize", help="Show ASCII dependency tree"
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    format: str = typer.Option(
        "json", "-f", "--format", help="Output format: json or text"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail on warnings (e.g., orphaned tasks), not just critical errors (cycles, forward refs)",
    ),
):
    """Validate TaskDecomposer dependency graph

    Exit codes:
      0 - Valid graph (no critical errors; warnings allowed unless --strict)
      1 - Invalid graph (critical errors found, or warnings with --strict)
      2 - Malformed input (invalid JSON or missing required fields)
    """
    from mapify_cli.tools.validate_dependencies import (
        load_input,
        DependencyValidator,
        ASCIIGraphRenderer,
        print_report,
    )

    try:
        # Load input
        data = load_input(str(input_file) if input_file else None)

        # Validate
        validator = DependencyValidator(data)
        validator.validate_all()
        report = validator.get_report()

        # Print report
        print_report(report, format)

        # Display visualization if requested
        if visualize:
            console.print()  # Add blank line separator
            renderer = ASCIIGraphRenderer(validator)
            visualization = renderer.render(use_colors=not no_color)
            console.print(visualization)

        # Determine exit code based on issue severity
        has_critical = report.get("critical_issues", 0) > 0
        has_warnings = report.get("warnings", 0) > 0

        if has_critical:
            # Critical errors always fail
            raise typer.Exit(1)
        elif has_warnings and strict:
            # Warnings fail only in strict mode
            raise typer.Exit(1)
        # Otherwise exit 0 (success)

    except ValueError as e:
        # Input validation error (malformed JSON, missing fields)
        error_report = {
            "valid": False,
            "error": str(e),
            "error_type": "input_validation",
        }
        console.print_json(data=error_report)
        raise typer.Exit(2)


def main():
    app()


if __name__ == "__main__":
    main()
