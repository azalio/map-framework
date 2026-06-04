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

__version__ = "3.10.0"

import os
import subprocess
import sys
import shutil
import ssl
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import typer
import httpx

try:
    import truststore

    HAS_TRUSTSTORE = True
except ImportError:
    truststore = None  # type: ignore[assignment]  # optional dependency
    HAS_TRUSTSTORE = False

from rich.panel import Panel
from rich.live import Live
from rich.align import Align
from rich.table import Table

# Local submodule re-exports (v3.5.0 platform refactor)
from mapify_cli.cli_ui import console
from mapify_cli.cli_ui import (
    StepTracker,
    BannerGroup,
    get_key as get_key,
    select_with_arrows as select_with_arrows,
    select_multiple_with_arrows as select_multiple_with_arrows,
    show_banner,
    BANNER as BANNER,
    TAGLINE as TAGLINE,
)
from mapify_cli.delivery import (
    create_task_decomposer_content as create_task_decomposer_content,
    create_actor_content as create_actor_content,
    create_monitor_content as create_monitor_content,
    create_predictor_content as create_predictor_content,
    create_evaluator_content as create_evaluator_content,
    create_reflector_content as create_reflector_content,
    create_documentation_reviewer_content as create_documentation_reviewer_content,
    create_agent_files,
    create_reference_files,
    create_command_files,
    create_skill_files,
    create_hook_files,
    create_config_files,
    create_commands_dir as create_commands_dir,
)
from mapify_cli.config import (
    configure_global_permissions,
    create_or_merge_project_settings_local,
    create_mcp_config,
    build_standard_mcp_servers,
    read_project_mcp_json,
    write_project_mcp_json as write_project_mcp_json,
    merge_mcp_json as merge_mcp_json,
    create_or_merge_project_mcp_json,
)


# Create secure SSL context with proper fallback
def create_ssl_context():
    """Create SSL context with proper certificate validation."""
    try:
        if HAS_TRUSTSTORE:
            assert truststore is not None  # narrowed by HAS_TRUSTSTORE guard
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

skill_eval_app = typer.Typer(
    name="skill-eval", help="Evaluate a skill's trigger accuracy + cost"
)

app.add_typer(skill_eval_app, name="skill-eval")


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
    """Get the path to bundled templates directory.

    Delegates to :func:`mapify_cli.delivery.file_copier.get_templates_dir`
    to avoid duplication.
    """
    from mapify_cli.delivery.file_copier import get_templates_dir as _get

    return _get()


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
    """Return True when the current directory looks like a MAP project.

    Recognises both Claude Code layout (.claude/) and Codex layout (.codex/
    config plus .agents/skills).
    """
    claude_paths = [
        project_path / ".claude" / "agents",
        project_path / ".claude" / "commands",
        project_path / ".claude" / "settings.json",
        project_path / ".claude" / "workflow-rules.json",
    ]
    codex_paths = [
        project_path / ".codex" / "config.toml",
        project_path / ".agents" / "skills",
    ]
    return all(p.exists() for p in claude_paths) or all(p.exists() for p in codex_paths)


def _detect_provider(project_path: Path) -> str:
    """Detect which provider was used to initialise this project."""
    if (project_path / ".codex" / "config.toml").exists():
        return "codex"
    return "claude"


def get_project_health(project_path: Path) -> Dict[str, Any]:
    """Collect project health diagnostics for check/doctor commands."""
    agent_exclude = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}
    current_branch = sanitize_identifier(get_current_branch_name())
    branch_dir = project_path / ".map" / current_branch
    detected = _detect_provider(project_path)

    if detected == "codex":
        required_paths = {
            ".codex/config.toml": project_path / ".codex" / "config.toml",
            ".agents/skills": project_path / ".agents" / "skills",
            ".codex/agents": project_path / ".codex" / "agents",
            ".map/scripts": project_path / ".map" / "scripts",
        }
    else:
        required_paths = {
            ".claude/agents": project_path / ".claude" / "agents",
            ".claude/commands": project_path / ".claude" / "commands",
            ".claude/settings.json": project_path / ".claude" / "settings.json",
            ".claude/workflow-rules.json": project_path
            / ".claude"
            / "workflow-rules.json",
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
    original_cwd = Path.cwd()
    try:
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
    provider: str = typer.Option(
        "claude",
        "--provider",
        help="Delivery provider: claude (default) or codex",
    ),
    compression: Optional[str] = typer.Option(
        None,
        "--compression",
        help=(
            "Context-compression policy: never (default, opt-in everywhere), "
            "auto (nudge when last turn >= threshold), or aggressive "
            "(nudge at 0.4 x threshold). When omitted the existing config "
            "value is preserved and re-running ``mapify init`` does not "
            "overwrite user choices. See docs/USAGE.md."
        ),
    ),
    compression_threshold: Optional[int] = typer.Option(
        None,
        "--compression-threshold",
        help=(
            "Token threshold for the compression nudge (only applies when "
            "--compression auto|aggressive). Default 120000 (~60% of a 200k "
            "window). Raise to ~250000 for Opus 1M or long 50+ subtask plans. "
            "When omitted, the existing config value is preserved on re-run."
        ),
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

    # Validate provider
    valid_providers = ("claude", "codex")
    if provider not in valid_providers:
        console.print(
            f"[red]Error:[/red] Invalid provider '{provider}'. "
            f"Valid providers: {', '.join(valid_providers)}"
        )
        raise typer.Exit(1)

    # Validate compression policy & threshold only when the user actually
    # passed the flag — None means "leave existing config alone", which is
    # the correct behaviour on re-run in an existing project. The canonical
    # policy set lives in ``token_budget`` so this validation cannot drift
    # from config-load validation or the budgeting logic.
    from mapify_cli.token_budget import VALID_POLICIES
    if compression is not None and compression not in VALID_POLICIES:
        console.print(
            f"[red]Error:[/red] Invalid compression policy '{compression}'. "
            f"Valid: {', '.join(VALID_POLICIES)}"
        )
        raise typer.Exit(1)
    if compression_threshold is not None and compression_threshold <= 0:
        console.print(
            "[red]Error:[/red] --compression-threshold must be > 0"
        )
        raise typer.Exit(1)

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
        assert (
            project_name is not None
        ), "project_name must be set in non-current-dir mode"
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

    if provider == "codex":
        codex_available = check_tool("codex")
        if codex_available:
            tracker.complete("check-tools", "git, codex" if git_available else "codex")
        elif git_available:
            tracker.complete("check-tools", "git")
        else:
            tracker.complete("check-tools", "minimal")
    else:
        claude_available = check_tool("claude")
        if claude_available:
            tracker.complete("check-tools", "git, claude")
        elif git_available:
            tracker.complete("check-tools", "git")
        else:
            tracker.complete("check-tools", "minimal")

    # Select provider
    tracker.add("ai-select", "Select provider")
    selected_ai = provider
    tracker.complete("ai-select", selected_ai)

    # Select MCP servers (Claude only — Codex uses TOML agent config)
    selected_mcp_servers = []

    if provider != "codex":
        tracker.add("mcp-select", "Select MCP servers")
        tracker.start("mcp-select")

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
                console.print(
                    f"Valid servers: {', '.join(INDIVIDUAL_MCP_SERVERS.keys())}"
                )
            selected_mcp_servers = [s for s in requested if s in INDIVIDUAL_MCP_SERVERS]

        tracker.complete("mcp-select", f"{len(selected_mcp_servers)} servers")

    if provider == "codex":
        # Codex provider: install .agents/.codex files + .map/scripts/ (skip-if-exists)
        from mapify_cli.delivery.providers import CodexProvider

        tracker.add("create-codex", "Create Codex files")
        tracker.start("create-codex")
        codex_provider = CodexProvider()
        counts = codex_provider.install(project_path)
        total = sum(counts.values())
        tracker.complete("create-codex", f"{total} files")

        # Codex provider also gets .map/config.yaml so context-compression
        # policy is honoured by the orchestrator on Codex sessions too.
        tracker.add("map-config", "Create .map/config.yaml")
        tracker.start("map-config")
        try:
            from mapify_cli.config.project_config import (
                apply_compression_overrides,
                write_default_config,
            )

            config_path = write_default_config(project_path)
            # Only persist compression overrides when the user explicitly
            # passed a flag. ``write_default_config`` is idempotent and a
            # bare ``mapify init .`` re-run must NOT silently rewrite
            # existing compression_policy / threshold to CLI defaults.
            if compression is not None or compression_threshold is not None:
                apply_compression_overrides(
                    config_path, compression, compression_threshold
                )
            tracker.complete(
                "map-config", str(config_path.relative_to(project_path))
            )
        except Exception as e:
            tracker.error("map-config", f"skipped: {e}")
    else:
        # Claude provider: use ClaudeProvider abstraction
        from mapify_cli.delivery.providers import ClaudeProvider

        tracker.add("create-claude", "Create Claude Code files")
        tracker.start("create-claude")
        claude_provider = ClaudeProvider()
        claude_counts = claude_provider.install(
            project_path, mcp_servers=selected_mcp_servers
        )
        total_claude = sum(claude_counts.values())
        tracker.complete("create-claude", f"{total_claude} files")

        # Create default .map/config.yaml (project-level settings)
        tracker.add("map-config", "Create .map/config.yaml")
        tracker.start("map-config")
        try:
            from mapify_cli.config.project_config import (
                apply_compression_overrides,
                write_default_config,
            )

            config_path = write_default_config(project_path)
            # Only persist compression overrides when the user explicitly
            # passed a flag. ``write_default_config`` is idempotent and a
            # bare ``mapify init .`` re-run must NOT silently rewrite
            # existing compression_policy / threshold to CLI defaults.
            if compression is not None or compression_threshold is not None:
                apply_compression_overrides(
                    config_path, compression, compression_threshold
                )
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

        tracker.add("project-permissions", "Configure project approvals")
        tracker.start("project-permissions")
        create_or_merge_project_settings_local(project_path)
        tracker.complete("project-permissions", ".claude/settings.local.json")

    # Initialize git (shared, provider-agnostic)
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

    tracker.add("finalize", "Finalize")
    tracker.complete("finalize", "project ready")

    # Configure global permissions for read-only commands (Claude only)
    if provider != "codex":
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

    if provider == "codex":
        steps_lines.append(f"{step_num}. Start using MAP skills with Codex:")
        steps_lines.append("   • [cyan]$map-plan[/] - Plan and decompose complex tasks")
        steps_lines.append(
            "   • [cyan]$map-fast[/] - Quick implementation with minimal validation"
        )
        steps_lines.append("   • [cyan]$map-check[/] - Quality gates and verification")
        steps_lines.append(
            "   • [cyan]$map-efficient[/] - Execute approved MAP plans end to end"
        )
        steps_lines.append(
            f"{step_num + 1}. Trust this project in Codex settings for .codex/ config to take effect; skills live in .agents/skills"
        )
    else:
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

    detected = _detect_provider(Path.cwd())
    if detected == "codex":
        tools = [
            ("git", "Git version control"),
            ("codex", "Codex CLI"),
        ]
    else:
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
        tracker.complete("project", f"initialized ({detected} provider)")
    else:
        tracker.error("project", "not initialized")

    tracker.add("templates", "Inspect bundled templates")
    if health["expected_agents"]:
        tracker.complete(
            "templates",
            f"{health['expected_agents']} agents",
        )
    else:
        tracker.error("templates", "missing bundled templates")

    if detected != "codex":
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
        if detected == "codex" and not results.get("codex"):
            console.print("  • Install Codex CLI: https://github.com/openai/codex")
        elif not results.get("claude"):
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
    detected = _detect_provider(project_path)
    health = get_project_health(project_path)
    tracker = StepTracker("MAP Doctor")

    if detected == "codex":
        tool_list = [("git", "Git version control"), ("codex", "Codex CLI")]
    else:
        tool_list = [("git", "Git version control"), ("claude", "Claude Code CLI")]

    for tool_name, description in tool_list:
        tracker.add(tool_name, description)
        if check_tool(tool_name):
            tracker.complete(tool_name, "available")
        else:
            tracker.error(tool_name, "not found")

    tracker.add("project", "MAP project structure")
    if detected == "codex":
        codex_dir = project_path / ".codex"
        codex_checks = {
            ".codex/config.toml": codex_dir / "config.toml",
            ".agents/skills": project_path / ".agents" / "skills",
            ".codex/agents": codex_dir / "agents",
            ".map/scripts": project_path / ".map" / "scripts",
        }
        codex_missing = [n for n, p in codex_checks.items() if not p.exists()]
        if not codex_missing:
            tracker.complete("project", "all core paths present (codex)")
        else:
            tracker.error("project", f"missing {len(codex_missing)} path(s)")
    elif not health["missing_paths"]:
        tracker.complete("project", "all core paths present")
    else:
        tracker.error("project", f"missing {len(health['missing_paths'])} path(s)")

    if detected != "codex":
        tracker.add("templates", "Installed template counts")
        if health["installed_agents"] == health["expected_agents"]:
            tracker.complete(
                "templates",
                f"{health['installed_agents']}/{health['expected_agents']} agents",
            )
        else:
            tracker.error(
                "templates",
                f"agents {health['installed_agents']}/{health['expected_agents']}",
            )

    tracker.add("planning", "Branch workspace artifacts")
    if health["branch_workspace_exists"]:
        tracker.complete(
            "planning",
            f"branch {health['current_branch']}: {health['branch_artifact_count']}/{health['expected_branch_artifact_count']} artifacts",
        )
    else:
        tracker.error("planning", f"missing .map/{health['current_branch']}")

    if detected != "codex":
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
        (
            f".{detected} + workflow configs detected"
            if health["initialized"]
            else "Run `mapify init .`"
        ),
    )
    if detected != "codex":
        details.add_row(
            "Agents",
            f"{health['installed_agents']}/{health['expected_agents']}",
            "Installed vs bundled agent templates",
        )
        details.add_row(
            "Skills",
            "via .claude/skills/",
            "Slash commands delivered as skills",
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
    if detected != "codex":
        details.add_row(
            "MCP",
            (
                "valid"
                if health["project_mcp_valid"]
                else ("present" if health["has_project_mcp"] else "not configured")
            ),
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

    if _detect_provider(project_path) == "codex":
        console.print(
            "[yellow]Codex projects: re-run "
            "[cyan]mapify init . --provider codex --force[/cyan] to refresh.[/yellow]"
        )
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

    # Track drift across all file types
    from mapify_cli.delivery.managed_file_copier import DriftReport

    drift_report = DriftReport()

    existing_project_mcp = read_project_mcp_json(project_path / ".mcp.json")
    existing_server_names = []
    if existing_project_mcp:
        existing_server_names = list(existing_project_mcp.get("mcpServers", {}).keys())

    tracker.add("agents", "Refresh agent templates")
    tracker.start("agents")
    agent_count = create_agent_files(project_path, existing_server_names, drift_report)
    tracker.complete("agents", f"{agent_count} files")

    tracker.add("commands", "Refresh slash commands")
    tracker.start("commands")
    command_count = create_command_files(project_path, drift_report)
    tracker.complete("commands", f"{command_count} files")

    tracker.add("skills", "Refresh skills")
    tracker.start("skills")
    skill_count = create_skill_files(project_path)
    tracker.complete("skills", f"{skill_count} folders")

    tracker.add("references", "Refresh reference files")
    tracker.start("references")
    ref_count = create_reference_files(project_path, drift_report)
    tracker.complete("references", f"{ref_count} files")

    tracker.add("hooks", "Refresh shared hooks")
    tracker.start("hooks")
    hook_count = create_hook_files(project_path, drift_report)
    tracker.complete("hooks", f"{hook_count} files")

    tracker.add("configs", "Refresh config files")
    tracker.start("configs")
    config_count = create_config_files(project_path, drift_report)
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

    # Show drift warnings if any files were modified by the user
    if drift_report.has_drift:
        console.print()
        console.print(
            f"[yellow]⚠ {len(drift_report.drifted_files)} file(s) had local modifications:[/yellow]"
        )
        for r in drift_report.drifted_files:
            try:
                rel = r.dest.relative_to(project_path)
            except ValueError:
                rel = r.dest
            backup_note = ""
            if r.backed_up and r.backup_path:
                try:
                    backup_rel = r.backup_path.relative_to(project_path)
                except ValueError:
                    backup_rel = r.backup_path
                backup_note = f" → backup: [cyan]{backup_rel}[/cyan]"
            console.print(f"  [yellow]•[/yellow] {rel}{backup_note}")
        console.print(
            "[dim]Your changes were backed up to .bak files. "
            "Review and re-apply any customizations if needed.[/dim]"
        )

    console.print()
    console.print("[bold green]Upgrade complete.[/bold green]")
    console.print(
        "[dim]Note: upgrade refreshes shipped MAP files but does not overwrite project-specific MCP selections.[/dim]"
    )


# Skill-eval commands


@skill_eval_app.command("run")
def skill_eval_run(
    skill: str = typer.Argument(..., help="Skill under test, e.g. map-debug"),
    eval_set: Optional[Path] = typer.Option(
        None, "--eval-set", help="Path to eval-set JSON"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate eval-set + print planned count; spend nothing"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume a partial run, skipping completed cells"
    ),
    max_concurrency: int = typer.Option(
        1, "--max-concurrency", min=1, help="Bounded parallel dispatch (default 1)"
    ),
) -> None:
    """Run a skill evaluation matrix.

    Exit codes:
      0 - Success (or dry-run completed)
      1 - Runtime error (claude not found, or unexpected failure)
      2 - Validation error (missing --eval-set or malformed eval-set file)
    """
    # Intent: lazy import to keep top-level import time low and avoid import cycles.
    import mapify_cli.skills_eval.runner as _runner
    import mapify_cli.skills_eval.aggregator as _aggregator
    from mapify_cli.skills_eval.dispatcher import ClaudeSubprocessDispatcher
    from mapify_cli.skills_eval.eval_schema import EvalResultRecord
    from datetime import timezone

    # SC-2: --eval-set is required.
    if eval_set is None:
        console.print(
            "[bold red]Error:[/bold red] provide --eval-set PATH"
        )
        raise typer.Exit(2)

    # SC-2: load and validate the eval-set; malformed/empty → Exit(2), NO invocations.
    try:
        entries = _runner.load_eval_set(eval_set)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2)

    # Dry-run path: zero quota, NO dispatcher construction, NO claude required.
    if dry_run:
        # D10: variant_id fixed = 1, runs = 1.
        planned = len(entries) * 1 * 1
        console.print(
            f"[bold]Dry-run:[/bold] planned [cyan]{planned}[/cyan] invocation(s) "
            f"for skill [bold]{skill}[/bold] — spends 0 quota"
        )
        raise typer.Exit(0)

    # HC-6: require claude BEFORE any invocation.
    if shutil.which("claude") is None:
        console.print(
            "[bold red]Error:[/bold red] requires-cmd: claude — "
            "install the claude CLI and ensure it is on PATH"
        )
        raise typer.Exit(1)

    # Resolve output path.
    root = Path.cwd()
    if resume:
        latest = _runner.latest_run_path(root, skill)
        out_path = latest if latest is not None else _runner.default_run_path(
            root, skill, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
    else:
        out_path = _runner.default_run_path(
            root, skill, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )

    # Run the evaluation matrix.
    disp = ClaudeSubprocessDispatcher()
    _aggregator.bounded_run(
        skill=skill,
        entries=entries,
        dispatcher=disp,
        runs=1,
        out_path=out_path,
        resume=resume,
        max_concurrency=max_concurrency,
    )

    # Read all records from the output file, aggregate, and print summary.
    records: List[EvalResultRecord] = []
    if out_path.exists():
        for raw_line in out_path.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                records.append(EvalResultRecord.from_dict(__import__("json").loads(raw_line)))
            except (ValueError, KeyError):
                continue

    summary = _aggregator.aggregate(records)
    console.print(
        f"\n[bold]Eval complete:[/bold] skill=[bold]{skill}[/bold] "
        f"pass_rate=[cyan]{summary.pass_rate:.1%}[/cyan] "
        f"({summary.passed_cells}/{summary.total_cells} cells passed)"
    )
    if summary.tokens_mean is not None:
        console.print(
            f"  tokens mean={summary.tokens_mean:.1f} "
            f"stddev={summary.tokens_stddev or 0.0:.1f} "
            f"(n={summary.token_sample_size})"
        )
    if summary.duration_mean is not None:
        console.print(
            f"  duration mean={summary.duration_mean:.2f}s "
            f"stddev={summary.duration_stddev or 0.0:.2f}s"
        )
    console.print(f"  artifact: [cyan]{out_path}[/cyan]")


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


def _open_best_effort(path: Path) -> None:
    """Open *path* in the default browser — swallow any error (VC5/SC-2)."""
    import webbrowser  # lazy import: optional use-path

    try:
        webbrowser.open(path.as_uri())
    except Exception:  # noqa: BLE001
        pass  # SC-2: never errors the run


def _read_skill_description(root: Path, skill: str) -> str:
    """Return the description: field from SKILL.md frontmatter, or '' on any failure."""
    skill_md = root / ".claude" / "skills" / skill / "SKILL.md"
    if not skill_md.exists():
        return ""
    try:
        from mapify_cli.skill_ir import parse_frontmatter  # lazy import

        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return ""
        close = text.find("\n---", 4)
        if close == -1:
            return ""
        frontmatter_text = text[4:close]
        parsed = parse_frontmatter(frontmatter_text)
        return str(parsed.get("description", ""))
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# skill-eval optimize
# ---------------------------------------------------------------------------

_OPTIMIZE_MIN_ENTRIES: int = 5


@skill_eval_app.command("optimize")
def skill_eval_optimize(
    skill: str = typer.Argument(..., help="Skill under optimisation, e.g. map-plan"),
    eval_set: Optional[Path] = typer.Option(
        None, "--eval-set", help="Path to eval-set JSON"
    ),
    iterations: int = typer.Option(
        5, "--iterations", min=1, help="Total iterations including baseline (default 5)"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Apply the winning description back to the .jinja source"
    ),
    open_html: bool = typer.Option(
        False, "--open", help="Open the HTML report in the default browser"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print planned call budget; spend nothing, no dispatcher"
    ),
) -> None:
    """Optimise a skill's trigger description via repeated eval iterations.

    Exit codes:
      0 - Success (or dry-run completed)
      1 - Runtime error (claude not found)
      2 - Validation error (missing --eval-set, malformed eval-set, or < 5 entries)
    """
    import json  # lazy — keep top-level import time low

    import mapify_cli.skills_eval.runner as _runner
    from datetime import timezone

    # 1. --eval-set is required.
    if eval_set is None:
        console.print("[bold red]Error:[/bold red] provide --eval-set PATH")
        raise typer.Exit(2)

    # 2. Load and validate eval-set.
    try:
        entries = _runner.load_eval_set(eval_set)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2)

    # 3. MIN-SIZE guard — BEFORE dry-run and BEFORE any dispatcher (VC2).
    if len(entries) < _OPTIMIZE_MIN_ENTRIES:
        console.print(
            f"[bold red]Error:[/bold red] eval-set has {len(entries)} "
            f"{'entry' if len(entries) == 1 else 'entries'}; "
            f"optimize requires >= {_OPTIMIZE_MIN_ENTRIES} entries"
        )
        raise typer.Exit(2)

    # 4. DRY-RUN — print budget, exit 0, construct NO dispatcher (VC1).
    if dry_run:
        from mapify_cli.skills_eval.description_optimizer import (
            _DEFAULT_SEED,
            split_train_test,
        )

        train, test = split_train_test(entries, _DEFAULT_SEED)
        n_train = len(train)
        n_test = len(test)
        total_dispatches = iterations * (n_train + n_test)
        console.print(
            f"[bold]Dry-run:[/bold] "
            f"{iterations} x ({n_train}+{n_test}) = [cyan]{total_dispatches}[/cyan] "
            f"dispatch calls + [cyan]{iterations}[/cyan] proposer calls"
        )
        console.print("model: default (resolved by claude CLI)")
        raise typer.Exit(0)

    # 5. CLAUDE CHECK — require claude BEFORE any invocation (VC3).
    if shutil.which("claude") is None:
        console.print(
            "[bold red]Error:[/bold red] requires-cmd: claude — "
            "install the claude CLI and ensure it is on PATH"
        )
        raise typer.Exit(1)

    # 6. REAL RUN.
    import mapify_cli.skills_eval.proposer as _proposer
    from mapify_cli.skills_eval.description_optimizer import optimize
    from mapify_cli.skills_eval.viewer import render_to_path

    root = Path.cwd()
    out_dir = root / ".map" / "eval-runs" / skill
    out_dir.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    current_description = _read_skill_description(root, skill)

    result = optimize(
        skill=skill,
        entries=entries,
        current_description=current_description,
        proposer=_proposer.propose_description,
        dispatcher=None,
        source_claude_dir=root / ".claude",
        out_dir=out_dir,
        run_ts=run_ts,
        iterations=iterations,
    )

    json_path = out_dir / f"{run_ts}-optimize.json"
    html_path = out_dir / f"{run_ts}-optimize.html"
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    render_to_path(result, html_path)

    status_label = "no improvement" if result.no_improvement else f"iter {result.winning_iteration}"
    winner_iter = next(
        (it for it in result.iterations if it.selected),
        None,
    )
    test_pass_rate = winner_iter.test_pass_rate if winner_iter is not None else 0.0
    console.print(
        f"[bold]Optimize complete:[/bold] skill=[bold]{skill}[/bold] "
        f"winner=[cyan]{status_label}[/cyan] "
        f"test_pass_rate=[cyan]{test_pass_rate:.1%}[/cyan]"
    )
    console.print(f"  artifact: [cyan]{json_path}[/cyan]")

    if apply:
        from mapify_cli.skills_eval.apply_patcher import apply_optimized_description

        apply_optimized_description(
            skill=skill,
            winner=result.winning_description,
            current_description=current_description,
            no_improvement=result.no_improvement,
            repo_root=root,
            stage=True,
        )

    if open_html:
        _open_best_effort(html_path)


# ---------------------------------------------------------------------------
# skill-eval view
# ---------------------------------------------------------------------------


@skill_eval_app.command("view")
def skill_eval_view(
    skill: str = typer.Argument(..., help="Skill whose optimization result to view"),
    result_path: Optional[Path] = typer.Option(
        None, "--result", help="Path to a specific *-optimize.json file"
    ),
    open_html: bool = typer.Option(
        False, "--open", help="Open the HTML report in the default browser"
    ),
) -> None:
    """Render the latest (or specified) optimize result as an HTML report.

    Exit codes:
      0 - Success
      2 - No optimize result found
    """
    import json

    from mapify_cli.skills_eval.eval_schema import OptimizeResult
    from mapify_cli.skills_eval.viewer import render_to_path

    out_dir = Path.cwd() / ".map" / "eval-runs" / skill

    if result_path is not None:
        path = result_path
    else:
        candidates = sorted(out_dir.glob("*-optimize.json"))
        if not candidates:
            console.print(
                f"[bold red]Error:[/bold red] no optimize result found under {out_dir}"
            )
            raise typer.Exit(2)
        path = candidates[-1]

    res = OptimizeResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
    html = path.with_suffix(".html")
    render_to_path(res, html)
    console.print(f"  report: [cyan]{html}[/cyan]")

    if open_html:
        _open_best_effort(html)


def main():
    app()


if __name__ == "__main__":
    main()
