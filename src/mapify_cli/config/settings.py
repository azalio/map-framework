"""Settings and permissions management for MAP Framework."""

import json
from pathlib import Path
from typing import Any

from mapify_cli.cli_ui import console

# ---------------------------------------------------------------------------
# Autonomy posture (opt-in via `mapify init --autonomy`)
# ---------------------------------------------------------------------------
#
# "YOLO-minus-git": auto-approve most tools locally while keeping the human in
# control of commit/push. This is a *personal* risk preference, so it is written
# ONLY to the per-user, gitignored .claude/settings.local.json — never to the
# committed, team-shared .claude/settings.json baseline.
#
# The permission-level git deny below is documentation / defense-in-depth: under
# a broad ``Bash(*)`` allow it is bypassable (``bash -c 'git commit'`` matches as
# ``bash``). The actual hard block is the ``safety-guardrails.py`` PreToolUse
# hook, which is gated on the ``mapify.autonomy`` sentinel this module writes.
_AUTONOMY_ALLOW = [
    "Bash(*)",
    "Read(*)",
    "Edit(*)",
    "Write(*)",
    "MultiEdit(*)",
    "Glob(*)",
    "Grep(*)",
    "LS(*)",
]
_AUTONOMY_DENY = [
    "Bash(git commit:*)",
    "Bash(git push:*)",
]


def ensure_settings_local_gitignored(project_path: Path) -> int:
    """Idempotently add ``.claude/settings.local.json`` to the repo-root .gitignore.

    User-local approvals and machine-specific statusline paths must not leak
    into the team via a committed settings.local.json. The exact ignore path is
    authoritative; descriptive markers and superseded rules are repaired.

    Returns 1 when the file was created or modified, 0 when already up-to-date.
    """
    from mapify_cli.delivery.file_copier import merge_settings_local_gitignore

    return merge_settings_local_gitignore(project_path)


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
            "Read(**)",
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
        allow_list = settings["permissions"].setdefault("allow", [])

        # Migrate the stale "Glob(**)" rule: Claude Code now matches all
        # file-reading tools against Read(path) rules only, so a previously
        # installed "Glob(**)" silently stopped being enforced (startup
        # warning only). The append-if-missing loop below never removes
        # stale entries, so heal already-materialized global settings here.
        if "Glob(**)" in allow_list:
            allow_list[:] = [perm for perm in allow_list if perm != "Glob(**)"]

        # Add new permissions if they don't exist
        existing_allow = set(allow_list)
        for perm in default_permissions["allow"]:
            if perm not in existing_allow:
                allow_list.append(perm)

    # Write back
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)

    console.print(f"[green]✓[/green] Configured global permissions in {settings_file}")
    console.print(
        f"[dim]  Added {len(default_permissions['allow'])} read-only command patterns[/dim]"
    )


def create_or_merge_project_settings_local(
    project_path: Path, *, autonomy: bool | None = None
) -> None:
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

    Args:
        project_path: Target project root.
        autonomy: Opt-in "YOLO-minus-git" posture.
            - ``True``  → merge a broad tool allowlist + git commit/push deny and
              write the ``mapify.autonomy`` sentinel.
            - ``False`` → remove the autonomy allow/deny entries and the sentinel
              (teardown for ``--no-autonomy``).
            - ``None``  → leave any existing autonomy posture untouched (default on
              re-run, so re-init never silently flips a user's choice).
    """

    # Establish and revalidate the privacy boundary before writing any local
    # approval state, including the default narrow allowlist.  This also closes
    # the gap between init's early preflight and this later writer.
    ensure_settings_local_gitignored(project_path)

    settings_file = project_path / ".claude" / "settings.local.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    default_permissions: dict[str, Any] = {
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

    permissions.setdefault("deny", [])
    permissions.setdefault("ask", [])

    # Autonomy posture (opt-in). None = leave as-is.
    if autonomy is True:
        _apply_autonomy(existing_settings, permissions)
    elif autonomy is False:
        _remove_autonomy(existing_settings, permissions)

    settings_file.write_text(json.dumps(existing_settings, indent=2) + "\n")

    if autonomy is True:
        console.print(
            "[yellow]Autonomy mode:[/yellow] auto-allowing most tools in "
            ".claude/settings.local.json (per-user, gitignored). git commit/push "
            "stay blocked — you run them. The local deny overrides the team baseline."
        )
    elif autonomy is False:
        console.print(
            "[dim]Autonomy mode disabled: removed local broad-allow + git block "
            "from .claude/settings.local.json.[/dim]"
        )


def _apply_autonomy(settings: dict[str, Any], permissions: dict[str, Any]) -> None:
    """Add the broad allow + git deny entries and the autonomy sentinel."""
    allow = permissions.setdefault("allow", [])
    for entry in _AUTONOMY_ALLOW:
        if entry not in allow:
            allow.append(entry)

    deny = permissions.setdefault("deny", [])
    for entry in _AUTONOMY_DENY:
        if entry not in deny:
            deny.append(entry)

    # Sentinel beside the permissions it governs so posture and permissions
    # cannot drift apart; read by the safety-guardrails.py PreToolUse hook.
    mapify_meta = settings.setdefault("mapify", {})
    if isinstance(mapify_meta, dict):
        mapify_meta["autonomy"] = True


def _remove_autonomy(settings: dict[str, Any], permissions: dict[str, Any]) -> None:
    """Remove the autonomy allow/deny entries and the sentinel (teardown)."""
    if isinstance(permissions.get("allow"), list):
        permissions["allow"] = [
            e for e in permissions["allow"] if e not in _AUTONOMY_ALLOW
        ]
    if isinstance(permissions.get("deny"), list):
        permissions["deny"] = [
            e for e in permissions["deny"] if e not in _AUTONOMY_DENY
        ]

    mapify_meta = settings.get("mapify")
    if isinstance(mapify_meta, dict):
        mapify_meta.pop("autonomy", None)
        if not mapify_meta:
            settings.pop("mapify", None)
