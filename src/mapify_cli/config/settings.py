"""Settings and permissions management for MAP Framework."""

import json
from pathlib import Path
from typing import Dict, Any

from rich.console import Console

console = Console()


def configure_global_permissions() -> None:
    """Configure global Claude Code permissions for read-only commands"""
    claude_dir = Path.home() / ".claude"
    settings_file = claude_dir / "settings.json"

    # Create .claude directory if it doesn't exist
    claude_dir.mkdir(exist_ok=True)

    # Default permissions for read-only commands
    default_permissions = {
        "allow": [
            "Bash(git status *)",
            "Bash(git log *)",
            "Bash(git diff *)",
            "Bash(git show *)",
            "Bash(git check-ignore *)",
            "Bash(git branch --show-current *)",
            "Bash(git branch -a *)",
            "Bash(git rev-parse *)",
            "Bash(git ls-files *)",
            "Bash(ls *)",
            "Bash(cat *)",
            "Bash(head *)",
            "Bash(tail *)",
            "Bash(wc *)",
            "Bash(grep *)",
            "Bash(find *)",
            "Bash(sort *)",
            "Bash(uniq *)",
            "Bash(jq *)",
            "Bash(which *)",
            "Bash(echo *)",
            "Bash(pwd *)",
            "Bash(whoami *)",
            "Bash(ruby -c *)",
            "Bash(go fmt /tmp/ *)",
            "Bash(gofmt -l *)",
            "Bash(gofmt -d *)",
            "Bash(go vet *)",
            "Bash(go build *)",
            "Bash(go test -c *)",
            "Bash(go mod download *)",
            "Bash(go mod tidy *)",
            "Bash(chmod +x *)",
            "Read(//Users/**)",
            "Read(//private/tmp/**)",
            "Glob(**)",
        ],
        "deny": [],
    }

    # Read existing settings or create new
    if settings_file.exists():
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            console.print(
                "[yellow]Warning:[/yellow] Corrupted settings.json, will recreate"
            )
            settings = {}
    else:
        settings = {}

    # Merge permissions (preserve user's custom permissions)
    if "permissions" not in settings:
        settings["permissions"] = default_permissions
    else:
        # Add new permissions if they don't exist
        existing_allow = set(settings["permissions"].get("allow", []))
        for perm in default_permissions["allow"]:
            if perm not in existing_allow:
                settings["permissions"].setdefault("allow", []).append(perm)

    # Write back
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)

    console.print(f"[green]✓[/green] Configured global permissions in {settings_file}")
    console.print(
        f"[dim]  Added {len(default_permissions['allow'])} read-only command patterns[/dim]"
    )


def create_or_merge_project_settings_local(project_path: Path) -> None:
    """Create/merge .claude/settings.local.json with safe project allowlist.

    Claude Code supports per-project approvals via `.claude/settings.local.json`.
    This file is user-local (should not be committed) and is merged by Claude Code
    with global settings from `~/.claude/settings.json`.

    IMPORTANT:
    - Shared, repo-committed hooks MUST be configured in `.claude/settings.json`.
    - `.claude/settings.local.json` is for user-local approvals/allowlists and should
      not be used as the primary distribution mechanism for project hooks.

    We keep this allowlist intentionally narrow and focused on common safe actions
    for local development workflows.
    """

    settings_file = project_path / ".claude" / "settings.local.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    default_permissions: Dict[str, Any] = {
        "allow": [
            # SourceCraft MCP helpers (project-scoped)
            "mcp__sourcecraft__list_pull_request_comments",
            # Common safe Go workflows (project-scoped)
            "Bash(go test *)",
            "Bash(go test -c *)",
            "Bash(go vet *)",
            "Bash(go build *)",
            "Bash(go mod download *)",
            "Bash(go mod tidy *)",
            "Bash(gofmt -l *)",
            "Bash(gofmt -d *)",
            # Common safe Make targets
            "Bash(make generate manifests)",
            "Bash(make manifests)",
            # Common git workflows
            "Bash(git worktree add *)",
            # Used by some test/dev scripts to produce temporary dev certs
            'Bash(openssl req -x509 -newkey rsa:512 -keyout /dev/null -out /dev/stdout -days 365 -nodes -subj "/CN=test" 2>/dev/null)',
        ],
        "deny": [],
        "ask": [],
    }

    # Load existing settings if present
    if settings_file.exists():
        try:
            existing_settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            console.print(
                f"[yellow]Warning:[/yellow] Corrupted {settings_file}, will recreate"
            )
            existing_settings = {}
    else:
        existing_settings = {}

    if isinstance(existing_settings, dict) and existing_settings.get("hooks"):
        console.print(
            "[yellow]Warning:[/yellow] .claude/settings.local.json contains hooks. "
            "Claude Code loads hooks from BOTH .claude/settings.json and .claude/settings.local.json, "
            "so this can cause duplicate hook executions. "
            "Move shared hooks to .claude/settings.json and remove the hooks section from settings.local.json."
        )

    existing_settings.setdefault("permissions", {})
    permissions = existing_settings["permissions"]

    # Merge allowlist (preserve user customizations)
    existing_allow = set(permissions.get("allow", []))
    for entry in default_permissions["allow"]:
        if entry not in existing_allow:
            permissions.setdefault("allow", []).append(entry)

    permissions.setdefault("deny", permissions.get("deny", []))
    permissions.setdefault("ask", permissions.get("ask", []))

    settings_file.write_text(json.dumps(existing_settings, indent=2) + "\n")
