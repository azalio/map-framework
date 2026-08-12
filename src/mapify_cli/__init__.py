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

__version__ = "3.25.0"

import json
import os
import shutil
import ssl
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer

try:
    import truststore  # pyright: ignore[reportMissingImports]

    HAS_TRUSTSTORE = True
except ImportError:
    truststore = None  # type: ignore[assignment]  # optional dependency
    HAS_TRUSTSTORE = False

from rich.align import Align
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from mapify_cli.cli_ui import (
    BANNER as BANNER,
)
from mapify_cli.cli_ui import (
    TAGLINE as TAGLINE,
)

# Local submodule re-exports (v3.5.0 platform refactor)
from mapify_cli.cli_ui import (
    BannerGroup,
    StepTracker,
    console,
    show_banner,
)
from mapify_cli.cli_ui import (
    get_key as get_key,
)
from mapify_cli.cli_ui import (
    select_multiple_with_arrows as select_multiple_with_arrows,
)
from mapify_cli.cli_ui import (
    select_with_arrows as select_with_arrows,
)
from mapify_cli.config import (
    build_standard_mcp_servers,
    configure_global_permissions,
    create_mcp_config,
    create_or_merge_project_mcp_json,
    create_or_merge_project_settings_local,
    read_project_mcp_json,
)
from mapify_cli.config import (
    merge_mcp_json as merge_mcp_json,
)
from mapify_cli.config import (
    write_project_mcp_json as write_project_mcp_json,
)
from mapify_cli.delivery import (
    create_actor_content as create_actor_content,
)
from mapify_cli.delivery import (
    create_agent_files as create_agent_files,
)
from mapify_cli.delivery import (
    create_command_files as create_command_files,
)
from mapify_cli.delivery import (
    create_commands_dir as create_commands_dir,
)
from mapify_cli.delivery import (
    create_config_files as create_config_files,
)
from mapify_cli.delivery import (
    create_documentation_reviewer_content as create_documentation_reviewer_content,
)
from mapify_cli.delivery import (
    create_evaluator_content as create_evaluator_content,
)
from mapify_cli.delivery import (
    create_hook_files as create_hook_files,
)
from mapify_cli.delivery import (
    create_monitor_content as create_monitor_content,
)
from mapify_cli.delivery import (
    create_predictor_content as create_predictor_content,
)
from mapify_cli.delivery import (
    create_reference_files as create_reference_files,
)
from mapify_cli.delivery import (
    create_reflector_content as create_reflector_content,
)
from mapify_cli.delivery import (
    create_skill_files as create_skill_files,
)
from mapify_cli.delivery import (
    create_task_decomposer_content as create_task_decomposer_content,
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
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
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
    "essential": "Essential (sequential-thinking)",
    "custom": "Select individually",
    "none": "Skip MCP setup",
}

INDIVIDUAL_MCP_SERVERS = {
    "sequential-thinking": "Chain-of-thought reasoning",
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

research_eval_app = typer.Typer(
    name="research-eval",
    help="Evaluate research-agent localization quality without provider calls",
)

app.add_typer(research_eval_app, name="research-eval")

code_map_app = typer.Typer(
    name="code-map",
    help="Structural code-map provider for MAP research (Python AST fallback).",
)

app.add_typer(code_map_app, name="code-map")

domain_skill_app = typer.Typer(
    name="domain-skill",
    help="Bootstrap a project-local domain/reference skill for Claude Code.",
)

app.add_typer(domain_skill_app, name="domain-skill")

governance_app = typer.Typer(
    name="governance",
    help="Inventory and audit MAP behavior-shaping assets installed in a project.",
)

app.add_typer(governance_app, name="governance")

preset_app = typer.Typer(
    name="preset",
    help="Manage MAP workflow customization presets.",
)

app.add_typer(preset_app, name="preset")

prompt_profile_app = typer.Typer(
    name="prompt-profile",
    help="Manage MAP prompt profiles — versioned, eval-gated prompt lifecycle.",
)

app.add_typer(prompt_profile_app, name="prompt-profile")


def version_callback(value: bool):
    """Callback to show version and exit."""
    if value:
        console.print(f"mapify-cli version {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    ctx: typer.Context,
    version: bool | None = typer.Option(
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


def is_debug_enabled(debug_flag: bool | None = None) -> bool:
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
    directory: Path, exclude_files: set[str] | None = None
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


def get_project_health(project_path: Path) -> dict[str, Any]:
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


def get_branch_workspace_dir(project_path: Path, branch: str | None = None) -> Path:
    """Return the branch-scoped MAP workspace directory."""
    branch_name = sanitize_identifier(branch or get_current_branch_name())
    return project_path / ".map" / branch_name


def get_branch_artifact_templates() -> dict[str, str]:
    """Return artifact templates aligned to MAP branch workspaces."""
    return {
        "code-review-001.md": "# Code Review 001\n\n## Scope\n\n## Findings\n\n### High\n\n### Medium\n\n### Low\n\n## Verdict\n- [ ] Ready\n- [ ] Needs revision\n",
        "qa-001.md": "# QA 001\n\n## Commands Run\n\n## Expected Result\n\n## Actual Result\n\n## Follow-ups\n",
        "pr-draft.md": "# PR Draft\n\n## Summary\n\n## Validation\n\n## Risks / Rollback\n",
    }


def initialize_branch_workspace(
    project_path: Path, branch: str | None = None
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
    project_path: Path, branch: str | None = None
) -> dict[str, Any]:
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
            check=False,
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


def is_git_repo(path: Path | None = None) -> bool:
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


def is_command(cmd_list: list[str]) -> bool:
    """Check if a command exists on the system."""
    if not cmd_list:
        return False
    try:
        subprocess.run(["which", cmd_list[0]], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_latest_release(owner: str, repo: str) -> dict[str, Any] | None:
    """Get the latest release from GitHub."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        with httpx.Client(verify=create_ssl_context()) as client:
            response = client.get(url)
            if response.status_code == 200:
                return response.json()
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass
    return None


@app.command()
def init(
    project_name: str | None = typer.Argument(
        None, help="Name for your new project directory (use '.' for current directory)"
    ),
    mcp: str = typer.Option(
        "all",
        "--mcp",
        help="MCP server installation (default: all). Options: all, essential, none, or comma-separated list (e.g. sequential-thinking)",
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
    compression: str | None = typer.Option(
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
    compression_threshold: int | None = typer.Option(
        None,
        "--compression-threshold",
        help=(
            "Token threshold for the compression nudge (only applies when "
            "--compression auto|aggressive). Default 120000 (~60% of a 200k "
            "window). Raise to ~250000 for Opus 1M or long 50+ subtask plans. "
            "When omitted, the existing config value is preserved on re-run."
        ),
    ),
    sofa: bool = typer.Option(
        False,
        "--sofa",
        help=(
            "Enable Stack Overflow for Agents (SOFA) integration (opt-in, off "
            "by default). Writes sofa.enabled=true to .map/config.yaml. "
            "See docs/USAGE.md."
        ),
    ),
    agent_memory: str = typer.Option(
        "off",
        "--agent-memory",
        help=(
            "Role-local persistent memory for the reflector learning agent "
            "(opt-in, off by default). Adds a `memory:` frontmatter field to "
            ".claude/agents/reflector.md and writes "
            "claude_agents.persistent_memory=<level> to .map/config.yaml. "
            "Allowed: off, local (user-local, NOT committed), "
            "project (project-scoped, committed). See docs/USAGE.md."
        ),
    ),
    autonomy: bool | None = typer.Option(
        None,
        "--autonomy/--no-autonomy",
        help=(
            "Opt-in 'YOLO-minus-git' posture (claude provider only): auto-approve "
            "most tools in the per-user, gitignored .claude/settings.local.json "
            "while a PreToolUse hook keeps git commit/push blocked (you run them). "
            "--no-autonomy removes it. Omit to leave existing local settings "
            "untouched. The committed team settings.json stays the secure baseline. "
            "See docs/USAGE.md."
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
        mapify init my-project --mcp "sequential-thinking"
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
            task_id=f"mapify_init_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
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

    # Autonomy posture is delivered via .claude/settings.local.json + the Claude
    # safety-guardrails hook, neither of which the codex provider installs.
    if provider == "codex" and autonomy is not None:
        console.print(
            "[yellow]Note:[/yellow] --autonomy/--no-autonomy applies to the claude "
            "provider only; ignored for --provider codex."
        )

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

    from mapify_cli.config.project_config import VALID_AGENT_MEMORY_LEVELS
    if agent_memory not in VALID_AGENT_MEMORY_LEVELS:
        console.print(
            f"[red]Error:[/red] Invalid --agent-memory '{agent_memory}'. "
            f"Valid: {', '.join(sorted(VALID_AGENT_MEMORY_LEVELS))}"
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
            selected_mcp_servers = ["sequential-thinking"]
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
                apply_agent_memory_overrides,
                apply_compression_overrides,
                apply_sofa_overrides,
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
            if sofa:
                apply_sofa_overrides(config_path)
                from mapify_cli.delivery.file_copier import merge_sofa_gitignore

                merge_sofa_gitignore(project_path)
            if agent_memory != "off":
                apply_agent_memory_overrides(config_path, agent_memory)
            tracker.complete(
                "map-config", str(config_path.relative_to(project_path))
            )
        except Exception as e:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
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

        # Surface the non-destructive statusline decision so the user knows
        # whether the context status row was wired or their own was preserved.
        if claude_counts.get("statusline"):
            console.print(
                "[dim]· Context statusline → .claude/settings.local.json "
                "(remove the statusLine key there to disable)[/dim]"
            )
        else:
            console.print(
                "[dim]· Existing statusLine detected — MAP statusline not wired[/dim]"
            )

        # Create default .map/config.yaml (project-level settings)
        tracker.add("map-config", "Create .map/config.yaml")
        tracker.start("map-config")
        try:
            from mapify_cli.config.project_config import (
                apply_agent_memory_overrides,
                apply_compression_overrides,
                apply_sofa_overrides,
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
            if sofa:
                apply_sofa_overrides(config_path)
                from mapify_cli.delivery.file_copier import merge_sofa_gitignore

                merge_sofa_gitignore(project_path)
            if agent_memory != "off":
                apply_agent_memory_overrides(config_path, agent_memory)
                from mapify_cli.delivery.file_copier import (
                    apply_reflector_memory_field,
                    merge_agent_memory_gitignore,
                )

                apply_reflector_memory_field(project_path, agent_memory)
                if agent_memory == "local":
                    merge_agent_memory_gitignore(project_path)
            tracker.complete("map-config", str(config_path.relative_to(project_path)))
        except Exception as e:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
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
        create_or_merge_project_settings_local(project_path, autonomy=autonomy)
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

    # Write install manifest (.map/mapify.lock.json) — scan-based, after all files
    # have been installed by both providers.
    tracker.add("manifest", "Write install manifest")
    tracker.start("manifest")
    try:
        from mapify_cli.install_manifest import build_manifest, write_manifest

        manifest = build_manifest(project_path, provider, __version__)
        manifest_path = write_manifest(project_path, manifest)
        tracker.complete(
            "manifest",
            f"{len(manifest.entries)} entries → {manifest_path.relative_to(project_path)}",
        )
    except Exception as _manifest_exc:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        tracker.error("manifest", f"skipped: {_manifest_exc}")

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
        steps_lines.append(f"{step_num}. Drive the MAP loop with Codex:")
        steps_lines.append(
            "   • [cyan]$map-plan[/]      decompose the task — you approve before any code"
        )
        steps_lines.append(
            "   • [cyan]$map-efficient[/] implement the approved plan"
        )
        steps_lines.append("   • [cyan]$map-check[/]     quality gates against the plan")
        steps_lines.append(
            "   • [cyan]$map-review[/]    semantic review vs spec, tests & diff"
        )
        steps_lines.append("   • [cyan]$map-learn[/]     save gotchas as project memory")
        steps_lines.append(
            f"{step_num + 1}. Tiny edit? [cyan]$map-fast[/] skips full planning. Bug? [cyan]$map-debug[/]."
        )
        steps_lines.append(
            f"{step_num + 2}. Trust this project in Codex settings for .codex/ config to take effect; skills live in .agents/skills"
        )
    else:
        steps_lines.append(f"{step_num}. Drive the MAP loop in Claude Code:")
        steps_lines.append(
            "   • [cyan]/map-plan[/]      decompose the task — you approve before any code"
        )
        steps_lines.append(
            "   • [cyan]/map-efficient[/] implement the approved plan"
        )
        steps_lines.append("   • [cyan]/map-check[/]     quality gates against the plan")
        steps_lines.append(
            "   • [cyan]/map-review[/]    semantic review vs spec, tests & diff"
        )
        steps_lines.append("   • [cyan]/map-learn[/]     save gotchas as project memory")
        steps_lines.append(
            f"{step_num + 1}. Tiny edit? [cyan]/map-fast[/] skips full planning. Bug? [cyan]/map-debug[/]."
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
            task_id=f"mapify_check_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
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
            task_id=f"mapify_doctor_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
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


def _format_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "n/a"


def _render_minimality_report(report: Mapping[str, Any]) -> None:
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        summary = {}
    branches = report.get("branches")
    branch_rows = branches if isinstance(branches, list) else []

    console.print("[bold]Minimality rollout report[/bold]")
    console.print(
        f"Current config minimality: [cyan]{report.get('current_config_minimality', 'off')}[/cyan]"
    )
    console.print(
        f"Decision: [bold]{summary.get('decision', 'insufficient_data')}[/bold] "
        f"(ready_for_phase3={summary.get('ready_for_phase3', False)})"
    )
    console.print(
        "Runs: "
        f"{summary.get('complete_opt_in_runs', 0)} opt-in complete, "
        f"{summary.get('complete_off_runs', 0)} off-baseline complete, "
        f"{summary.get('complete_runs_missing_historical_minimality', 0)} inferred"
    )
    console.print(
        "Averages: "
        f"retry {float(summary.get('avg_retry_events_opt_in', 0.0)):.2f} opt-in vs "
        f"{float(summary.get('avg_retry_events_off', 0.0)):.2f} off; "
        f"guard rework {float(summary.get('avg_guard_rework_opt_in', 0.0)):.2f} opt-in vs "
        f"{float(summary.get('avg_guard_rework_off', 0.0)):.2f} off; "
        f"YAGNI reversal {_format_percent(summary.get('user_reversal_rate'))}"
    )

    reasons = summary.get("reasons")
    if isinstance(reasons, list) and reasons:
        console.print()
        console.print("[bold]Reasons[/bold]")
        for reason in reasons:
            console.print(f"  - {reason}")

    next_actions = summary.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        console.print()
        console.print("[bold]Next actions[/bold]")
        for action in next_actions:
            console.print(f"  - {action}")

    cohort_branches = summary.get("cohort_branches")
    if isinstance(cohort_branches, Mapping):
        cohort_rows = (
            ("Off baseline", cohort_branches.get("off_baseline")),
            ("Opt-in", cohort_branches.get("opt_in")),
            (
                "Missing historical minimality",
                cohort_branches.get("missing_historical_minimality"),
            ),
        )
        if any(isinstance(branches, list) and branches for _, branches in cohort_rows):
            console.print()
            console.print("[bold]Cohort branches[/bold]")
            for label, branches in cohort_rows:
                if isinstance(branches, list) and branches:
                    console.print(f"  {label}: " + ", ".join(map(str, branches)))

    manual_review_gate = summary.get("manual_review_gate")
    if (
        isinstance(manual_review_gate, Mapping)
        and manual_review_gate.get("required") is True
    ):
        console.print()
        console.print("[bold]Manual review gate[/bold]")
        candidate_branches = manual_review_gate.get("candidate_branches")
        if isinstance(candidate_branches, list) and candidate_branches:
            console.print(
                "  Candidate opt-in branches: "
                + ", ".join(map(str, candidate_branches))
            )
        checklist = manual_review_gate.get("checklist")
        if isinstance(checklist, list) and checklist:
            console.print("  Checklist:")
            for item in checklist:
                console.print(f"  - {item}")

    if branch_rows:
        table = Table(title="Branch Samples", show_header=True, header_style="bold cyan")
        table.add_column("Branch")
        table.add_column("Status")
        table.add_column("Minimality")
        table.add_column("Source")
        table.add_column("Retries", justify="right")
        table.add_column("Guard", justify="right")
        table.add_column("YAGNI", justify="right")
        for row in branch_rows:
            if not isinstance(row, Mapping):
                continue
            table.add_row(
                str(row.get("branch", "")),
                str(row.get("terminal_status", "")),
                str(row.get("minimality", "")),
                str(row.get("minimality_source", "")),
                str(row.get("retry_events", 0)),
                str(row.get("guard_rework_events", 0)),
                f"{row.get('restored_yagni_count', 0)}/{row.get('total_yagni_recommendations', 0)}",
            )
        console.print()
        console.print(table)


@app.command("minimality-report")
def minimality_report(
    project_path: Path = typer.Option(
        Path("."),
        "--path",
        "-p",
        help="Project root containing .map/ artifacts",
    ),
    min_complete_runs: int = typer.Option(
        3,
        "--min-runs",
        min=1,
        help="Minimum complete runs required per off/opt-in cohort",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the machine-readable report as JSON",
    ),
) -> None:
    """Summarize local minimality telemetry for the Phase 3 default-flip gate."""
    from mapify_cli.minimality_report import build_minimality_rollout_report

    report = build_minimality_rollout_report(project_path, min_complete_runs)
    if json_output:
        console.print_json(data=report)
        return
    _render_minimality_report(report)


def _mapify_install_kind() -> str:
    """Classify how this mapify CLI is installed.

    Returns one of:
      - ``"uv-tool"``: installed via ``uv tool install`` (self-upgradeable with uv)
      - ``"pip"``:     installed into a regular/virtualenv site-packages (pip -U)
      - ``"source"``:  running from a source checkout / editable install
        (self-upgrade disabled — the user owns the tree)
    """
    pkg = str(Path(__file__).resolve()).replace("\\", "/")
    if "/uv/tools/" in pkg:
        return "uv-tool"
    if "/site-packages/" in pkg or "/dist-packages/" in pkg:
        return "pip"
    return "source"


def _self_upgrade_command(kind: str) -> list[str] | None:
    """Return the argv that upgrades mapify-cli for ``kind``, or None if unknown."""
    if kind == "uv-tool":
        uv = shutil.which("uv")
        return [uv, "tool", "upgrade", "mapify-cli"] if uv else None
    if kind == "pip":
        return [sys.executable, "-m", "pip", "install", "--upgrade", "mapify-cli"]
    return None


def _run_self_upgrade(cmd: list[str]) -> int:
    """Run the self-upgrade command, streaming its output. Returns the exit code.

    Returns ``127`` when the executable is not found. Isolated into its own
    function so tests can stub the subprocess invocation without patching the
    module-level ``subprocess`` used by many other commands.
    """
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        return 127


@app.command()
def upgrade():
    """Upgrade the mapify CLI itself to the latest released version.

    This refreshes the installed ``mapify-cli`` package (the tool), not the
    files inside a project. After upgrading, run ``mapify init . --force`` to
    refresh a project's shipped MAP files with the new templates.
    """
    show_banner()

    console.print("[cyan]Checking for the latest release...[/cyan]")
    latest_release = get_latest_release("azalio", "map-framework")
    latest_version: str | None = None

    if latest_release and latest_release.get("tag_name"):
        latest_version = str(latest_release["tag_name"]).lstrip("v")
        if parse_version(latest_version) > parse_version(__version__):
            console.print(
                f"[yellow]New version available:[/yellow] {latest_version} "
                f"(installed {__version__})"
            )
            if latest_release.get("html_url"):
                console.print(f"Release: [cyan]{latest_release['html_url']}[/cyan]")
        else:
            console.print(
                f"[green]Already on the latest release ({__version__}).[/green]"
            )
            console.print("[dim]Nothing to upgrade.[/dim]")
            raise typer.Exit(0)
    else:
        console.print(
            "[dim]Could not fetch release metadata; attempting upgrade anyway.[/dim]"
        )

    kind = _mapify_install_kind()

    if kind == "source":
        source_root = Path(__file__).resolve().parents[2]
        console.print(
            "[yellow]Running from a source checkout — self-upgrade is disabled.[/yellow]"
        )
        console.print(f"[dim]Source: {source_root}[/dim]")
        console.print(
            "[dim]Update with [cyan]git pull[/cyan] "
            "(then re-install the tool if needed).[/dim]"
        )
        raise typer.Exit(0)

    cmd = _self_upgrade_command(kind)
    if cmd is None:
        console.print(
            "[red]Could not determine how to upgrade mapify automatically.[/red]"
        )
        console.print(
            "Upgrade manually: [cyan]uv tool upgrade mapify-cli[/cyan] "
            "or [cyan]pip install --upgrade mapify-cli[/cyan]"
        )
        raise typer.Exit(1)

    console.print()
    console.print(f"[cyan]Upgrading mapify-cli...[/cyan] [dim]({' '.join(cmd)})[/dim]")
    exit_code = _run_self_upgrade(cmd)

    if exit_code != 0:
        console.print()
        console.print(
            f"[red]Upgrade command failed (exit {exit_code}).[/red] Run it manually:"
        )
        console.print(f"  [cyan]{' '.join(cmd)}[/cyan]")
        raise typer.Exit(1)

    target = latest_version or "the latest release"
    console.print()
    console.print(
        f"[bold green]mapify upgraded[/bold green] (was {__version__}, now {target})."
    )
    console.print("[dim]Confirm with [cyan]mapify --version[/cyan].[/dim]")
    console.print(
        "[dim]To refresh this project's MAP files with the new templates, run "
        "[cyan]mapify init . --force[/cyan].[/dim]"
    )


@app.command("check-installed")
def check_installed(
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
) -> None:
    """Compare installed MAP files against .map/mapify.lock.json.

    Reports missing files (in manifest but absent from disk), orphaned files
    (MAP-managed on disk but not recorded in the manifest), and drifted files
    (template hash differs from the manifest record).

    Exit codes: 0 = all ok, 1 = issues found, 2 = no manifest.
    """
    from mapify_cli.install_manifest import check_installed as _check_installed
    from mapify_cli.install_manifest import read_manifest

    target = project_path or Path.cwd()

    manifest = read_manifest(target)
    if manifest is None:
        console.print(
            f"[yellow]No install manifest found at {target / '.map' / 'mapify.lock.json'}[/yellow]"
        )
        console.print(
            "[dim]Run [cyan]mapify init .[/cyan] to generate the manifest.[/dim]"
        )
        raise typer.Exit(2)

    console.print(
        f"[bold]MAP install manifest[/bold] — provider: [cyan]{manifest.provider}[/cyan], "
        f"version: [cyan]{manifest.mapify_version}[/cyan], "
        f"installed: [dim]{manifest.installed_at}[/dim]"
    )
    console.print(f"[dim]{len(manifest.entries)} entries recorded[/dim]")
    console.print()

    result = _check_installed(target)

    has_issues = False

    if result.missing:
        has_issues = True
        console.print(f"[red]Missing ({len(result.missing)} files):[/red]")
        for path in result.missing:
            console.print(f"  [red]✗[/red] {path}")

    if result.orphaned:
        has_issues = True
        console.print(f"[yellow]Orphaned ({len(result.orphaned)} files):[/yellow]")
        for path in result.orphaned:
            console.print(f"  [yellow]?[/yellow] {path}")

    if result.drifted:
        has_issues = True
        console.print(f"[yellow]Drifted ({len(result.drifted)} files):[/yellow]")
        for path in result.drifted:
            console.print(f"  [yellow]~[/yellow] {path}")

    if result.ok and not has_issues:
        console.print(
            f"[green]✅ All {len(result.ok)} managed files match the manifest.[/green]"
        )
    elif not has_issues:
        console.print("[green]✅ No issues found.[/green]")
    else:
        console.print()
        console.print(
            "[dim]Run [cyan]mapify init . --force[/cyan] to refresh managed files.[/dim]"
        )
        raise typer.Exit(1)


@app.command()
def uninstall(
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt.",
    ),
) -> None:
    """Remove MAP-owned config entries from provider config files.

    Reads .map/mapify.lock.json and removes only the config-merge entries
    MAP injected (MCP server keys in .mcp.json, the MAP statusline in
    settings.local.json).  User-modified or user-owned entries are
    preserved.  Installed files (.claude/, .map/scripts/, etc.) are
    NOT removed by this command.

    Exit codes: 0 = ok / nothing to remove, 1 = error, 2 = no manifest.
    """
    from mapify_cli.install_manifest import read_manifest, reconcile_config

    target = project_path or Path.cwd()

    manifest = read_manifest(target)
    if manifest is None:
        console.print(
            f"[yellow]No install manifest found at "
            f"{target / '.map' / 'mapify.lock.json'}[/yellow]"
        )
        console.print("[dim]Run [cyan]mapify init .[/cyan] to generate the manifest.[/dim]")
        raise typer.Exit(2)

    if not manifest.config_entries:
        console.print("[green]No MAP-owned config entries in the manifest.[/green]")
        return

    console.print(
        f"[bold]MAP config entries to remove[/bold] "
        f"(provider: [cyan]{manifest.provider}[/cyan]):"
    )
    for entry in manifest.config_entries:
        console.print(f"  [dim]{entry.file}[/dim]  [cyan]{entry.key_path}[/cyan]")

    console.print()
    if not yes:
        confirm = typer.confirm(
            "Remove these MAP-owned config entries?",
            default=False,
        )
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            return

    result = reconcile_config(target)

    if result.removed:
        console.print(f"[green]Removed ({len(result.removed)}):[/green]")
        for label in result.removed:
            console.print(f"  [green]✓[/green] {label}")

    if result.skipped:
        console.print(
            f"[yellow]Skipped ({len(result.skipped)}) — user-modified, preserved:[/yellow]"
        )
        for label in result.skipped:
            console.print(f"  [yellow]~[/yellow] {label}")

    if result.missing:
        console.print(f"[dim]Already absent ({len(result.missing)}):[/dim]")
        for label in result.missing:
            console.print(f"  [dim]-[/dim] {label}")

    if not result.removed and not result.skipped and not result.missing:
        console.print("[dim]Nothing to do.[/dim]")


# ---------------------------------------------------------------------------
# Preset management commands (#291)
# ---------------------------------------------------------------------------

_PRESET_MANIFEST_KEYS = ("id", "title", "version")


def _presets_dir(project_dir: Path) -> Path:
    return project_dir / ".map" / "presets"


def _read_preset_manifest(preset_path: Path) -> dict[str, Any] | None:
    manifest_path = preset_path / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@preset_app.command("list")
def preset_list(
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List installed MAP presets in a project's .map/presets/ directory."""
    target = project_path or Path.cwd()
    presets_root = _presets_dir(target)

    if not presets_root.is_dir():
        if output_json:
            typer.echo(json.dumps({"presets": []}))
        else:
            console.print("[dim]No presets installed. Use 'mapify preset add --from <path>' to install one.[/dim]")
        return

    presets: list[dict[str, Any]] = []
    for entry in sorted(presets_root.iterdir()):
        if not entry.is_dir():
            continue
        manifest = _read_preset_manifest(entry)
        if manifest is None:
            presets.append({"id": entry.name, "title": entry.name, "version": "?", "description": "(no manifest)"})
        else:
            presets.append({
                "id": manifest.get("id", entry.name),
                "title": manifest.get("title", entry.name),
                "version": manifest.get("version", "?"),
                "description": manifest.get("description", ""),
            })

    if output_json:
        typer.echo(json.dumps({"presets": presets}))
        return

    if not presets:
        console.print("[dim]No presets installed. Use 'mapify preset add --from <path>' to install one.[/dim]")
        return

    table = Table(title="Installed MAP Presets", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Version", style="dim")
    table.add_column("Description", style="dim")
    for p in presets:
        table.add_row(p["id"], p["title"], p["version"], p.get("description", ""))
    console.print(table)


@preset_app.command("add")
def preset_add(
    from_path: Path = typer.Option(
        ...,
        "--from",
        help="Path to a preset directory containing manifest.json.",
        show_default=False,
    ),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite if already installed."),
) -> None:
    """Install a MAP preset from a local directory into .map/presets/.

    The source directory must contain a manifest.json with at least: id, title, version.
    """
    if not from_path.is_dir():
        console.print(f"[red]Error:[/red] '{from_path}' is not a directory.")
        raise typer.Exit(1)

    manifest = _read_preset_manifest(from_path)
    if manifest is None:
        console.print(
            f"[red]Error:[/red] No valid manifest.json found in '{from_path}'.\n"
            "A preset directory must contain manifest.json with 'id', 'title', and 'version' keys."
        )
        raise typer.Exit(1)

    missing = [k for k in _PRESET_MANIFEST_KEYS if k not in manifest]
    if missing:
        console.print(
            f"[red]Error:[/red] manifest.json is missing required keys: {', '.join(missing)}"
        )
        raise typer.Exit(1)

    preset_id: str = manifest["id"]
    if not preset_id or "/" in preset_id or "\\" in preset_id or ".." in preset_id:
        console.print(
            f"[red]Error:[/red] Invalid preset id '{preset_id}' — must be a plain name (no path separators)."
        )
        raise typer.Exit(1)

    target = project_path or Path.cwd()
    dest = _presets_dir(target) / preset_id

    if dest.exists() and not force:
        console.print(
            f"[yellow]Preset '{preset_id}' is already installed.[/yellow] "
            "Use --force to overwrite."
        )
        raise typer.Exit(1)

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(str(from_path), str(dest))
    console.print(
        f"[green]Preset '{preset_id}'[/green] ({manifest.get('title', preset_id)} "
        f"v{manifest.get('version', '?')}) installed to {dest}."
    )


def _preset_state_path(preset_dir: Path) -> Path:
    return preset_dir / ".state.json"


def _read_preset_state(preset_dir: Path) -> dict[str, Any]:
    path = _preset_state_path(preset_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_preset_state(preset_dir: Path, state: dict[str, Any]) -> None:
    _preset_state_path(preset_dir).write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_preset_enabled(preset_dir: Path) -> bool:
    return _read_preset_state(preset_dir).get("enabled", True)


def _resolve_installed_preset(presets_root: Path, preset_id: str) -> Path | None:
    candidate = presets_root / preset_id
    return candidate if candidate.is_dir() else None


@preset_app.command("remove")
def preset_remove(
    preset_id: str = typer.Argument(..., help="ID of the preset to remove."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove an installed MAP preset from .map/presets/."""
    target = project_path or Path.cwd()
    preset_dir = _resolve_installed_preset(_presets_dir(target), preset_id)
    if preset_dir is None:
        console.print(f"[red]Error:[/red] Preset '{preset_id}' is not installed.")
        raise typer.Exit(1)

    if not yes:
        confirm = typer.confirm(f"Remove preset '{preset_id}'?", default=False)
        if not confirm:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    shutil.rmtree(preset_dir)
    console.print(f"[green]Preset '{preset_id}' removed.[/green]")


@preset_app.command("enable")
def preset_enable(
    preset_id: str = typer.Argument(..., help="ID of the preset to enable."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
) -> None:
    """Enable a disabled MAP preset."""
    target = project_path or Path.cwd()
    preset_dir = _resolve_installed_preset(_presets_dir(target), preset_id)
    if preset_dir is None:
        console.print(f"[red]Error:[/red] Preset '{preset_id}' is not installed.")
        raise typer.Exit(1)

    state = _read_preset_state(preset_dir)
    state["enabled"] = True
    _write_preset_state(preset_dir, state)
    console.print(f"[green]Preset '{preset_id}' enabled.[/green]")


@preset_app.command("disable")
def preset_disable(
    preset_id: str = typer.Argument(..., help="ID of the preset to disable."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
) -> None:
    """Disable a MAP preset without uninstalling it."""
    target = project_path or Path.cwd()
    preset_dir = _resolve_installed_preset(_presets_dir(target), preset_id)
    if preset_dir is None:
        console.print(f"[red]Error:[/red] Preset '{preset_id}' is not installed.")
        raise typer.Exit(1)

    state = _read_preset_state(preset_dir)
    state["enabled"] = False
    _write_preset_state(preset_dir, state)
    console.print(f"[yellow]Preset '{preset_id}' disabled.[/yellow]")


@preset_app.command("resolve")
def preset_resolve(
    template_name: str = typer.Argument(..., help="Template name to resolve (e.g. 'map-efficient.md')."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show which preset layers contribute to a template in resolution order.

    Resolution order (highest priority first): project overrides → enabled presets → core templates.
    """
    target = project_path or Path.cwd()
    presets_root = _presets_dir(target)

    layers: list[dict[str, Any]] = []

    # Tier 1: project overrides
    project_override = target / ".map" / "overrides" / template_name
    if project_override.is_file():
        layers.append({"tier": "project-override", "path": str(project_override), "enabled": True})

    # Tier 2: installed presets (sorted alphabetically for determinism)
    if presets_root.is_dir():
        for entry in sorted(presets_root.iterdir()):
            if not entry.is_dir():
                continue
            enabled = _is_preset_enabled(entry)
            template_path = entry / "templates" / template_name
            if template_path.is_file():
                manifest = _read_preset_manifest(entry)
                strategy = (manifest or {}).get("strategies", {}).get(template_name, "append")
                layers.append({
                    "tier": "preset",
                    "preset_id": entry.name,
                    "path": str(template_path),
                    "strategy": strategy,
                    "enabled": enabled,
                })

    # Tier 3: core template (shipped by mapify)
    try:
        core_path = get_templates_dir() / template_name
        if core_path.is_file():
            layers.append({"tier": "core", "path": str(core_path), "enabled": True})
    except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
        pass

    if output_json:
        typer.echo(json.dumps({"template": template_name, "layers": layers}))
        return

    if not layers:
        console.print(f"[dim]No layers found for template '{template_name}'.[/dim]")
        return

    console.print(f"[bold]Resolution layers for:[/bold] [cyan]{template_name}[/cyan]")
    for i, layer in enumerate(layers, 1):
        tier = layer["tier"]
        enabled_str = "" if layer.get("enabled", True) else " [dim](disabled)[/dim]"
        strategy_str = f" strategy=[cyan]{layer['strategy']}[/cyan]" if "strategy" in layer else ""
        preset_str = f" preset=[cyan]{layer['preset_id']}[/cyan]" if "preset_id" in layer else ""
        console.print(f"  {i}. tier={tier}{preset_str}{strategy_str}{enabled_str} → {layer['path']}")


# ---------------------------------------------------------------------------
# Preset composition helpers (Slice 3)
# ---------------------------------------------------------------------------

_COMPOSITION_STRATEGIES = frozenset({"replace", "prepend", "append", "wrap"})
_WRAP_PLACEHOLDER = "{CORE_TEMPLATE}"


def _preset_priority(preset_dir: Path) -> int:
    state = _read_preset_state(preset_dir)
    return int(state.get("priority", 50))


def _compose_template(core_content: str, layer_content: str, strategy: str) -> str:
    """Apply a composition strategy to produce the final template content."""
    if strategy == "replace":
        return layer_content
    if strategy == "prepend":
        return layer_content + "\n" + core_content
    if strategy == "append":
        return core_content + "\n" + layer_content
    if strategy == "wrap":
        if _WRAP_PLACEHOLDER in layer_content:
            return layer_content.replace(_WRAP_PLACEHOLDER, core_content)
        return layer_content + "\n" + core_content
    return core_content


def _build_resolution_order(presets_root: Path, template_name: str) -> list[dict[str, Any]]:
    """Return enabled preset layers for a template, sorted by priority descending."""
    layers: list[dict[str, Any]] = []
    if not presets_root.is_dir():
        return layers
    for entry in presets_root.iterdir():
        if not entry.is_dir() or not _is_preset_enabled(entry):
            continue
        template_path = entry / "templates" / template_name
        if not template_path.is_file():
            continue
        manifest = _read_preset_manifest(entry)
        strategy = (manifest or {}).get("strategies", {}).get(template_name, "append")
        layers.append({
            "preset_id": entry.name,
            "path": template_path,
            "strategy": strategy,
            "priority": _preset_priority(entry),
        })
    layers.sort(key=lambda x: x["priority"], reverse=True)
    return layers


@preset_app.command("render")
def preset_render(
    template_name: str = typer.Argument(..., help="Template name to render (e.g. 'map-efficient.md')."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output rendered content as JSON."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print composed content without writing to disk."),
) -> None:
    """Compose a template by layering enabled presets over the core template.

    Strategies (applied highest-priority first):
      replace — preset content replaces the core entirely
      prepend — preset content is inserted above the core
      append  — preset content is inserted below the core
      wrap    — preset content wraps the core via {CORE_TEMPLATE} placeholder
    """
    target = project_path or Path.cwd()
    presets_root = _presets_dir(target)

    # Start from project override if present, else core template
    project_override = target / ".map" / "overrides" / template_name
    if project_override.is_file():
        composed = project_override.read_text(encoding="utf-8")
        source = f"project-override:{project_override}"
    else:
        try:
            core_path = get_templates_dir() / template_name
            if core_path.is_file():
                composed = core_path.read_text(encoding="utf-8")
                source = f"core:{core_path}"
            else:
                composed = ""
                source = "core:(not found)"
        except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
            composed = ""
            source = "core:(error)"

    layers = _build_resolution_order(presets_root, template_name)
    applied: list[str] = []
    for layer in layers:
        layer_content = Path(layer["path"]).read_text(encoding="utf-8")
        strategy: str = layer["strategy"]
        if strategy not in _COMPOSITION_STRATEGIES:
            strategy = "append"
        composed = _compose_template(composed, layer_content, strategy)
        applied.append(f"{layer['preset_id']}({strategy})")

    if output_json:
        typer.echo(json.dumps({
            "template": template_name,
            "source": source,
            "applied_layers": applied,
            "content": composed,
        }))
        return

    if True:
        console.print(f"[bold]Composed:[/bold] [cyan]{template_name}[/cyan]")
        if applied:
            console.print(f"[dim]Layers applied:[/dim] {' → '.join(applied)}")
        else:
            console.print("[dim]No preset layers matched; showing core/override content.[/dim]")
        console.print()
        console.print(composed)


@preset_app.command("set-priority")
def preset_set_priority(
    preset_id: str = typer.Argument(..., help="ID of the preset to reprioritize."),
    priority: int = typer.Argument(..., help="Priority value (higher = applied first). Default: 50."),
    project_path: Path | None = typer.Argument(
        None,
        help="Project root directory (defaults to current directory).",
    ),
) -> None:
    """Set the composition priority of an installed preset.

    Higher priority presets are applied first in the composition stack.
    When two presets target the same template, the one with higher priority
    has its strategy applied first, then lower-priority presets layer on top.
    """
    target = project_path or Path.cwd()
    preset_dir = _resolve_installed_preset(_presets_dir(target), preset_id)
    if preset_dir is None:
        console.print(f"[red]Error:[/red] Preset '{preset_id}' is not installed.")
        raise typer.Exit(1)

    state = _read_preset_state(preset_dir)
    state["priority"] = priority
    _write_preset_state(preset_dir, state)
    console.print(f"[green]Preset '{preset_id}'[/green] priority set to {priority}.")


# Prompt profile commands

_PROFILE_MANIFEST_KEYS = ("id", "title", "version")


def _prompt_profiles_dir(project_dir: Path) -> Path:
    return project_dir / ".map" / "prompt-profiles"


def _read_profile_manifest(profile_path: Path) -> dict[str, Any] | None:
    manifest_path = profile_path / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_active_profile(profiles_root: Path) -> str | None:
    """Return the active profile id from active.json, or None."""
    active_path = profiles_root / "active.json"
    if not active_path.is_file():
        return None
    try:
        data = json.loads(active_path.read_text(encoding="utf-8"))
        return data.get("active") or None
    except (OSError, json.JSONDecodeError):
        return None


@prompt_profile_app.command("list")
def prompt_profile_list(
    project_path: Path = typer.Option(
        Path("."),
        "--project-path",
        "-p",
        help="Root of the target project (where .map/ lives).",
        resolve_path=True,
    ),
    output_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List installed MAP prompt profiles in a project's .map/prompt-profiles/ directory."""
    from rich.table import Table

    profiles_root = _prompt_profiles_dir(project_path)
    active_id = _read_active_profile(profiles_root)

    profiles: list[dict[str, Any]] = []

    if profiles_root.is_dir():
        for entry in sorted(profiles_root.iterdir()):
            if not entry.is_dir():
                continue
            manifest = _read_profile_manifest(entry)
            if manifest is None:
                continue
            missing = [k for k in _PROFILE_MANIFEST_KEYS if k not in manifest]
            if missing:
                continue
            profiles.append({
                "id": manifest["id"],
                "title": manifest["title"],
                "version": manifest["version"],
                "description": manifest.get("description", ""),
                "targets": manifest.get("targets", []),
                "active": manifest["id"] == active_id,
            })

    if output_json:
        console.print_json(json.dumps({"profiles": profiles, "active": active_id}))
        return

    if not profiles:
        console.print("No prompt profiles found in .map/prompt-profiles/.")
        console.print(
            "Create a profile at .map/prompt-profiles/<id>/manifest.json "
            "with required keys: id, title, version."
        )
        return

    table = Table(title="Prompt Profiles", box=None, show_header=True, header_style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Description")

    for profile in profiles:
        status = "active" if profile["active"] else "installed"
        table.add_row(
            profile["id"],
            profile["title"],
            profile["version"],
            status,
            profile["description"] or "",
        )

    console.print(table)

    if active_id and not any(p["id"] == active_id for p in profiles):
        console.print(
            f"[yellow]Warning:[/yellow] active profile '{active_id}' not found in "
            f".map/prompt-profiles/. The active.json pointer may be stale."
        )


# Research localization eval commands


@research_eval_app.command("score")
def research_eval_score(
    output_file: Path = typer.Argument(
        ...,
        help="ResearchEvidence JSON/text output file to score",
    ),
    expected_file: Path = typer.Argument(
        ...,
        help="JSON list, or object with expected_locations, of target file ranges",
    ),
    repo_root: Path | None = typer.Option(
        None,
        "--repo-root",
        help="Fixture repository root for path and line-range validation",
    ),
    fail_under_file_f1: float = typer.Option(
        0.0,
        "--fail-under-file-f1",
        min=0.0,
        max=1.0,
        help="Exit 1 when file-level F1 is below this threshold",
    ),
    fail_under_line_f1: float = typer.Option(
        0.0,
        "--fail-under-line-f1",
        min=0.0,
        max=1.0,
        help="Exit 1 when line-overlap F1 is below this threshold",
    ),
    overbroad_line_threshold: int = typer.Option(
        50,
        "--overbroad-line-threshold",
        min=1,
        help="Count predicted locations above this line span as over-broad",
    ),
    fail_on_malformed: bool = typer.Option(
        True,
        "--fail-on-malformed/--allow-malformed",
        help="Exit 1 when parsed output contains malformed locations",
    ),
) -> None:
    """Score research-agent localization against known fixture targets.

    Exit codes:
      0 - Score meets thresholds
      1 - Score below threshold or malformed output found
      2 - Input files are missing or malformed
    """
    import json

    from mapify_cli.research_eval import (
        load_expected_locations,
        score_research_output,
        score_to_dict,
    )

    try:
        output = output_file.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[bold red]Error:[/bold red] cannot read output file: {exc}")
        raise typer.Exit(2)

    try:
        expected = load_expected_locations(expected_file)
    except (OSError, ValueError) as exc:
        console.print(f"[bold red]Error:[/bold red] cannot load expected targets: {exc}")
        raise typer.Exit(2)

    root = repo_root.resolve() if repo_root else Path.cwd()
    score = score_research_output(
        output,
        expected,
        repo_root=root,
        overbroad_line_threshold=overbroad_line_threshold,
    )

    failed_reasons: list[str] = []
    if score.file_level.f1 < fail_under_file_f1:
        failed_reasons.append(
            f"file_level.f1 {score.file_level.f1:.3f} < {fail_under_file_f1:.3f}"
        )
    if score.line_level.f1 < fail_under_line_f1:
        failed_reasons.append(
            f"line_level.f1 {score.line_level.f1:.3f} < {fail_under_line_f1:.3f}"
        )
    if fail_on_malformed and score.malformed_count > 0:
        failed_reasons.append(f"malformed_count {score.malformed_count} > 0")

    payload = {
        "passed": not failed_reasons,
        "failed_reasons": failed_reasons,
        "thresholds": {
            "fail_under_file_f1": fail_under_file_f1,
            "fail_under_line_f1": fail_under_line_f1,
            "fail_on_malformed": fail_on_malformed,
            "overbroad_line_threshold": overbroad_line_threshold,
        },
        "score": score_to_dict(score),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if failed_reasons:
        raise typer.Exit(1)


@research_eval_app.command("compare")
def research_eval_compare(
    baseline_file: Path = typer.Argument(
        ...,
        help="ResearchEvidence JSON/text from the baseline discovery arm (e.g. glob_grep)",
    ),
    treatment_file: Path = typer.Argument(
        ...,
        help="ResearchEvidence JSON/text from the treatment discovery arm (e.g. structural-map)",
    ),
    expected_file: Path = typer.Argument(
        ...,
        help="JSON list, or object with expected_locations, of target file ranges",
    ),
    baseline_name: str = typer.Option(
        "baseline",
        "--baseline-name",
        help="Display name for the baseline arm",
    ),
    treatment_name: str = typer.Option(
        "treatment",
        "--treatment-name",
        help="Display name for the treatment arm",
    ),
    repo_root: Path | None = typer.Option(
        None,
        "--repo-root",
        help="Fixture repository root for path existence (stale detection) and line validation",
    ),
    min_treatment_file_f1: float = typer.Option(
        0.0,
        "--min-file-f1",
        min=0.0,
        max=1.0,
        help="Hard quality floor on treatment file-level F1 (token-only wins are not enough)",
    ),
    min_treatment_line_f1: float = typer.Option(
        0.0,
        "--min-line-f1",
        min=0.0,
        max=1.0,
        help="Hard quality floor on treatment line-level F1",
    ),
    max_stale_regression: int = typer.Option(
        0,
        "--max-stale-regression",
        min=0,
        help="Max allowed increase in stale/missing-file locations for treatment vs baseline",
    ),
    overbroad_line_threshold: int = typer.Option(
        50,
        "--overbroad-line-threshold",
        min=1,
        help="Locations with span above this are counted as over-broad",
    ),
    no_warn_regression: bool = typer.Option(
        False,
        "--no-warn-regression",
        help="Suppress quality-regression warnings (treatment vs baseline delta)",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write JSON report to this file (default: stdout only)",
    ),
) -> None:
    """Compare two ResearchEvidence discovery arms (baseline vs treatment).

    Scores quality (precision/recall/F1) and exploration-cost metrics
    (location_count, stale_count, overbroad_count) separately so token/LOC
    reduction cannot mask lower evidence quality.

    Exit codes:
      0 - Treatment meets all hard quality floors and stale-regression limits
      1 - Hard failure: quality floor not met or stale regression exceeded
      2 - Input files are missing or malformed
    """
    import json

    from mapify_cli.research_eval_compare import compare_research_files

    for label, path in [
        ("baseline", baseline_file),
        ("treatment", treatment_file),
        ("expected", expected_file),
    ]:
        if not path.is_file():
            console.print(f"[bold red]Error:[/bold red] {label} file not found: {path}")
            raise typer.Exit(2)

    root = repo_root.resolve() if repo_root else None
    try:
        report = compare_research_files(
            baseline_file,
            treatment_file,
            expected_file,
            baseline_name=baseline_name,
            treatment_name=treatment_name,
            repo_root=root,
            overbroad_line_threshold=overbroad_line_threshold,
            min_treatment_file_f1=min_treatment_file_f1,
            min_treatment_line_f1=min_treatment_line_f1,
            max_stale_regression=max_stale_regression,
            warn_on_quality_regression=not no_warn_regression,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2)

    payload = report.as_dict()
    output_json = json.dumps(payload, indent=2, sort_keys=True)
    print(output_json)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output_json + "\n", encoding="utf-8")

    if not report.passed:
        raise typer.Exit(1)


# Skill-eval commands


@skill_eval_app.command("run")
def skill_eval_run(
    skill: str = typer.Argument(..., help="Skill under test, e.g. map-debug"),
    eval_set: Path | None = typer.Option(
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
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model alias for claude -p (e.g. haiku, sonnet, opus). "
        "Default: the claude CLI session default. Pin to compare trigger "
        "accuracy across model tiers.",
    ),
    runs: int = typer.Option(
        1, "--runs", min=1, help="Passes per prompt (default 1). Use >1 to average "
        "out single-pass noise when comparing models.",
    ),
) -> None:
    """Run a skill evaluation matrix.

    Exit codes:
      0 - Success (or dry-run completed)
      1 - Runtime error (claude not found, or unexpected failure)
      2 - Validation error (missing --eval-set or malformed eval-set file)
    """
    # Intent: lazy import to keep top-level import time low and avoid import cycles.

    import mapify_cli.skills_eval.aggregator as _aggregator
    import mapify_cli.skills_eval.runner as _runner
    from mapify_cli.skills_eval.dispatcher import ClaudeSubprocessDispatcher
    from mapify_cli.skills_eval.eval_schema import EvalResultRecord

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
        # D10: variant_id fixed = 1; runs is caller-controlled (default 1).
        planned = len(entries) * 1 * runs
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
            root, skill, datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
    else:
        out_path = _runner.default_run_path(
            root, skill, datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )

    # Run the evaluation matrix.
    disp = ClaudeSubprocessDispatcher(model=model)
    _aggregator.bounded_run(
        skill=skill,
        entries=entries,
        dispatcher=disp,
        runs=runs,
        out_path=out_path,
        resume=resume,
        max_concurrency=max_concurrency,
    )

    # Read all records from the output file, aggregate, and print summary.
    records: list[EvalResultRecord] = []
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
    input_file: Path | None = typer.Argument(
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
        ASCIIGraphRenderer,
        DependencyValidator,
        load_input,
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
    except Exception:  # noqa: BLE001, S110
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
    eval_set: Path | None = typer.Option(
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
    run_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

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
    result_path: Path | None = typer.Option(
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


# ---------------------------------------------------------------------------
# skill-eval trajectory (issue #351: AgentLens-style outcome eval)
# ---------------------------------------------------------------------------


@skill_eval_app.command("trajectory")
def skill_eval_trajectory(
    skill: str = typer.Argument(
        ..., help="Skill under evaluation, e.g. map-task"
    ),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Path to a whole-skill fixture directory (manifest.json + repo/).",
    ),
    runs: int = typer.Option(
        3,
        "--runs",
        min=1,
        help="Repeated runs per fixture (default 3) for variance / flaky detection.",
    ),
    variant: str = typer.Option(
        "good",
        "--variant",
        help="Seed variant: 'good' (baseline) or 'bad' (degrade seeded copy).",
    ),
    degrade: str = typer.Option(
        "body", "--degrade", help="What the 'bad' variant degrades: body|actor|monitor."
    ),
    timeout: float = typer.Option(
        3600.0, "--timeout", help="Per-run claude -p timeout (seconds)."
    ),
    judge_timeout: float = typer.Option(
        360.0, "--judge-timeout", help="Per-run batched judge claude -p timeout."
    ),
    no_judge: bool = typer.Option(
        False,
        "--no-judge",
        help="Skip the LLM judge (deterministic components only). Cheapest.",
    ),
    anchor: str | None = typer.Option(
        None,
        "--anchor",
        help="Compare against a prior run: path to a .jsonl, or 'latest'.",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="Output .jsonl path (default .map/eval-runs/trajectory/...)."
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume the latest run, skipping present run_ids."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate fixture + print planned runs; spend nothing, no dispatcher.",
    ),
    open_html: bool = typer.Option(
        False, "--open", help="Open the side-by-side report in the default browser."
    ),
) -> None:
    """Run a trajectory-level outcome eval over a full skill run (issue #351).

    Seeds an isolated project, executes the whole skill body, scores six
    component metrics (formal/end_result/tool_use deterministic +
    instruction_compliance/pitfalls/reporting_trust from one batched judge
    call), aggregates repeated runs (median/variance/hard-pass/flaky), and
    optionally renders a candidate-vs-anchor side-by-side regression report.

    Exit codes:
      0 - Success (or dry-run completed)
      1 - Runtime error (claude not found, or unexpected failure)
      2 - Validation error (missing --fixture or malformed fixture)
    """

    import mapify_cli.skills_eval.trajectory.judge as _judge
    import mapify_cli.skills_eval.trajectory.runner as _trunner
    from mapify_cli.skills_eval.trajectory.dispatcher import (
        ClaudeTrajectoryDispatcher,
    )
    from mapify_cli.skills_eval.trajectory.repeated import aggregate_repeated
    from mapify_cli.skills_eval.trajectory.report import (
        build_report,
        render_comparison_to_path,
    )

    # SC-2: --fixture is required.
    if fixture is None:
        console.print("[bold red]Error:[/bold red] provide --fixture PATH")
        raise typer.Exit(2)
    if not fixture.is_dir():
        console.print(f"[bold red]Error:[/bold red] fixture dir not found: {fixture}")
        raise typer.Exit(2)

    # Validate the manifest BEFORE dry-run and before any dispatcher.
    try:
        manifest = _trunner.load_fixture_manifest(fixture)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(2)

    root = Path.cwd()
    run_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    if out is not None:
        out_path = out
    elif resume:
        latest = _trunner.latest_run_path(root, skill)
        out_path = latest if latest is not None else _trunner.default_run_path(
            root, skill, run_ts
        )
    else:
        out_path = _trunner.default_run_path(root, skill, run_ts)

    # Dry-run: zero quota, NO dispatcher, NO claude required.
    if dry_run:
        planned = 1 * runs
        console.print(
            f"[bold]Dry-run:[/bold] fixture=[bold]{manifest['fixture']}[/bold] "
            f"skill=[bold]{skill}[/bold] variant=[cyan]{variant}[/cyan] "
            f"runs=[cyan]{planned}[/cyan] judge=[cyan]{'off' if no_judge else 'on'}[/cyan] "
            f"— spends 0 quota"
        )
        raise typer.Exit(0)

    # HC-6: require claude BEFORE any invocation (real run or judge).
    if shutil.which("claude") is None:
        console.print(
            "[bold red]Error:[/bold red] requires-cmd: claude — "
            "install the claude CLI and ensure it is on PATH"
        )
        raise typer.Exit(1)

    dispatcher: object = ClaudeTrajectoryDispatcher()
    judge_runner = None if no_judge else _judge.ClaudeJudgeRunner()

    _trunner.run_matrix(
        fixture_dirs=[fixture],
        repo_root=root,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        runs=runs,
        out_path=out_path,
        ts=run_ts,
        judge_runner=judge_runner,
        judge_timeout=judge_timeout,
        run_timeout=timeout,
        variant=variant,
        degrade=degrade,
        resume=resume,
    )

    records = _trunner.read_records(out_path)
    agg = aggregate_repeated(records)
    fa = agg.fixture(str(manifest["fixture"]))
    median_str = (
        f"{fa.composite_median:.3f}" if fa else "n/a"
    )
    hp_str = (
        f"{fa.hard_pass_count}/{fa.n}" if fa else "n/a"
    )
    flaky_str = (
        f" flaky=[cyan]{'; '.join(fa.flaky_reasons)}[/cyan]"
        if fa and fa.flaky
        else ""
    )
    console.print(
        f"\n[bold]Trajectory eval complete:[/bold] skill=[bold]{skill}[/bold] "
        f"fixture=[bold]{manifest['fixture']}[/bold] "
        f"composite_median=[cyan]{median_str}[/cyan] "
        f"hard_pass=[cyan]{hp_str}[/cyan]{flaky_str}"
    )
    console.print(f"  records: [cyan]{out_path}[/cyan]")

    # Side-by-side regression report against an anchor run.
    if anchor is not None:
        anchor_path = _resolve_anchor(anchor, root, skill)
        if anchor_path is None or not anchor_path.is_file():
            console.print(
                f"[bold red]Error:[/bold red] anchor run not found: {anchor}"
            )
            raise typer.Exit(1)
        anchor_records = _trunner.read_records(anchor_path)
        report = build_report(
            records,
            anchor_records,
            candidate_path=str(out_path),
            anchor_path=str(anchor_path),
        )
        html_path = out_path.with_suffix(".html")
        render_comparison_to_path(report, html_path)
        reg = report.n_regressions
        console.print(
            f"  side-by-side: [cyan]{html_path}[/cyan] "
            f"({reg} regression(s) vs anchor)"
        )
        if open_html:
            _open_best_effort(html_path)

    if dry_run is False and no_judge:
        console.print("  [dim]judge skipped (--no-judge)[/dim]")


def _resolve_anchor(anchor: str, root: Path, skill: str) -> Path | None:
    """Resolve ``--anchor`` to a .jsonl path ('latest' or an explicit path)."""
    if anchor == "latest":
        latest_dir = root / ".map" / "eval-runs" / "trajectory" / skill
        candidates = sorted(latest_dir.glob("*.jsonl")) if latest_dir.is_dir() else []
        # Exclude the candidate currently being written by picking the
        # previous-to-last when two exist; callers pass 'latest' meaning the
        # most recent PRIOR run.
        return candidates[-2] if len(candidates) >= 2 else (
            candidates[-1] if candidates else None
        )
    return Path(anchor)


def main():
    app()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Code-map commands
# ---------------------------------------------------------------------------


@code_map_app.command("query")
def code_map_query(
    query: str = typer.Argument(..., help="Symbol name or keyword to search for."),
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        "-r",
        help="Root of the repository to index (default: current directory).",
    ),
    max_results: int = typer.Option(
        5,
        "--max-results",
        "-n",
        min=1,
        max=20,
        help="Maximum number of locations to return (default 5).",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Write ResearchEvidence JSON to this file (default: stdout only).",
    ),
) -> None:
    """Query the structural code map for a symbol and emit ResearchEvidence JSON.

    Scans all Python files under REPO_ROOT using AST parsing (no external
    dependencies required) and returns matching symbol locations compatible
    with the existing ResearchEvidence contract.

    Exit codes:
      0 - One or more matching locations found.
      1 - No matches found, empty index, or error.
    """
    from mapify_cli.code_map import query_code_map

    result = query_code_map(query, repo_root.resolve(), max_results=max_results)
    evidence = result.as_research_evidence()

    print(evidence)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(evidence + "\n", encoding="utf-8")

    if result.status not in ("ok",):
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Domain-skill commands
# ---------------------------------------------------------------------------


@domain_skill_app.command("init")
def domain_skill_init(
    project_path: str | None = typer.Argument(
        None,
        help="Project directory to bootstrap the domain skill in (default: current directory)",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Skill name in kebab-case (default: <project-name>-domain)",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite an existing domain skill file",
    ),
) -> None:
    """Bootstrap a project-local domain/reference skill.

    Scans README.md, pyproject.toml, package.json, go.mod, and Makefile to
    extract factual content. Missing facts become explicit placeholders for you
    to fill. No content is fabricated, and secrets are never read or emitted.

    The generated .claude/skills/<name>/SKILL.md is yours — it is not a
    MAP-managed shipped template and will not be overwritten by mapify init.

    This differs from /map-learn: this skill provides day-one project context
    before any workflow runs; /map-learn captures lessons after a run completes.

    Examples:

        mapify domain-skill init

        mapify domain-skill init . --name myproject-domain

        mapify domain-skill init /path/to/project --overwrite
    """
    from mapify_cli.delivery.domain_skill import create_domain_skill

    target = Path(project_path) if project_path else Path.cwd()
    if not target.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {target}")
        raise typer.Exit(1)

    skill_file, created = create_domain_skill(target, skill_name=name, overwrite=overwrite)

    rel = skill_file.relative_to(target)
    if created:
        console.print(f"[green]Created[/green] {rel}")
        console.print(
            "[dim]Edit the file and replace placeholders with real project facts.[/dim]"
        )
        console.print(
            "[dim]Do not commit secrets, tokens, passwords, or API keys into this file.[/dim]"
        )
    else:
        console.print(
            f"[yellow]Skipped:[/yellow] {rel} already exists"
            " (use --overwrite to replace)"
        )


# ---------------------------------------------------------------------------
# Governance commands
# ---------------------------------------------------------------------------


@governance_app.command("report")
def governance_report(
    project_path: str | None = typer.Argument(
        None,
        help="Project directory to audit (default: current directory)",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Output the report as JSON instead of Markdown",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Write the report to a file instead of stdout",
    ),
) -> None:
    """Generate a governance report for MAP behavior-shaping assets.

    Inventories installed skills, hooks, references, and learned rules in the
    .claude/ directory and classifies each asset under six governance categories:
    Charter, Policy, Context, Harness, Oversight, Learning.

    Distinguishes enforced controls (runtime hooks) from prompt-only guidance
    (skills, references, learned rules) and lists governance gaps where
    policy claims rely solely on prompt text without a backing harness control.

    Examples:

        mapify governance report

        mapify governance report /path/to/project

        mapify governance report --json --out .map/governance.json
    """
    from mapify_cli.delivery.governance_report import build_governance_report

    target = Path(project_path) if project_path else Path.cwd()
    if not target.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {target}")
        raise typer.Exit(1)

    report = build_governance_report(target)

    if not report.assets:
        console.print(
            f"[yellow]No MAP assets found[/yellow] in {target} — "
            "run 'mapify init' first to install the MAP framework."
        )
        raise typer.Exit(1)

    content = report.as_json() if output_json else report.as_markdown()

    if out is not None:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        console.print(f"[green]Written[/green] {out_path}")
    elif output_json:
        # Bypass Rich to avoid ANSI escape codes in JSON output
        typer.echo(content)
    else:
        console.print(content)
