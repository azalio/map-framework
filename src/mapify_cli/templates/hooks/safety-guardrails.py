#!/usr/bin/env python3
"""
Safety Guardrails - PreToolUse Hook

Merged hook that blocks:
- Access to sensitive files (.env, credentials, private keys)
- Dangerous shell commands (rm -rf /, force push, etc.)
- Branch mutation from verifier-class subagents (#424): no git commit/push/reset
  and no Edit/Write outside `.map/` when `agent_type` names a read-and-report
  agent. Reads are never restricted.

Trigger: Edit|Write|Bash
Exit codes:
  0 - Allow
  0 + permissionDecision=deny - Block (preferred)
"""

import json
import os
import sys

# =============================================================================
# Default constants (overridable via .map/config.yaml → safe_path_prefixes)
# =============================================================================

# Dangerous file patterns (case-insensitive)
_DEFAULT_DANGEROUS_FILE_PATTERNS = [
    r"\.env($|\.)",  # .env, .env.local, .env.production
    r"credentials",
    r"private[_-]?key",
    r"\.pem$",
    r"secrets?\.(json|ya?ml|toml)",
    r"id_rsa",
    r"id_ed25519",
    r"\.key$",
    r"passwords?\.(json|ya?ml|toml|txt)$",  # password files, not any file with "password" in path
    r"tokens?\.(json|ya?ml|toml|txt)$",  # token files, not any file with "token" in path
]

_DEFAULT_DANGEROUS_FILE_MARKERS = (
    ".env",
    "credential",
    "private",
    "key",
    ".pem",
    "secret",
    "id_rsa",
    "id_ed25519",
    "password",
    "token",
)

# Dangerous bash command patterns
_DEFAULT_DANGEROUS_COMMANDS = [
    # Block `rm -rf /` (bare root), `rm -rf /etc`, `rm -rf /home/user`, etc.,
    # but ALLOW deletion of subpaths UNDER a temp root (rm -rf /tmp/<dir>,
    # /private/tmp/<dir>, /var/folders/<dir>, /var/tmp/<dir>) — legitimate
    # scratch cleanup. The negative lookahead requires a trailing slash, so the
    # temp root itself (`rm -rf /tmp`) stays blocked; only children are allowed.
    r"rm\s+-rf\s+/(?!(?:tmp|private/tmp|var/folders|var/tmp)/)",  # rm -rf / (non-temp)
    r"rm\s+-rf\s+\*",  # rm -rf *
    r"rm\s+-rf\s+\.\.",  # rm -rf ..
    r"git\s+push.*--force.*main",
    r"git\s+push.*--force.*master",
    r"git\s+push\s+-f.*main",
    r"git\s+push\s+-f.*master",
    r"git\s+reset\s+--hard",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",  # Fork bomb
    r"chmod\s+-R\s+777\s+/",
    r">\s*/dev/sd",  # Writing to disk devices
]

# Safe path prefixes (skip checks for known safe directories)
_DEFAULT_SAFE_PATH_PREFIXES = [
    "src/",
    "lib/",
    "test/",
    "tests/",
    "docs/",
    "pkg/",
    "cmd/",
    "internal/",
    ".claude/agents/",
    ".claude/commands/",
    ".claude/hooks/",
    ".claude/references/",
    ".claude/skills/",
    "scripts/",
]


def _load_config_overrides() -> dict:
    """Load overrides from .map/config.yaml if it exists.

    Reads safe_path_prefixes from project config to allow customization.
    Falls back to defaults when config is missing or unreadable.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    config_path = os.path.join(project_dir, ".map", "config.yaml")
    if not os.path.exists(config_path):
        return {}
    try:
        import yaml  # type: ignore[import-untyped]

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        return {}


# Load overrides once at module init
_config = _load_config_overrides()

DANGEROUS_FILE_PATTERNS = _config.get(
    "dangerous_file_patterns", _DEFAULT_DANGEROUS_FILE_PATTERNS
)
DANGEROUS_COMMANDS = _config.get("dangerous_commands", _DEFAULT_DANGEROUS_COMMANDS)
SAFE_PATH_PREFIXES = _config.get("safe_path_prefixes", _DEFAULT_SAFE_PATH_PREFIXES)


def is_safe_path(path: str) -> bool:
    """Check if path is in known safe directory."""
    return any(path.startswith(prefix) for prefix in SAFE_PATH_PREFIXES)


def check_file_safety(path: str) -> tuple[bool, str]:
    """Check if file path is safe to access. Returns (is_safe, reason)."""
    if not path:
        return True, ""

    # Fast path: known safe directories
    if is_safe_path(path):
        return True, ""

    # Check dangerous patterns against the basename only, not the full path.
    # Matching the full path causes false positives when a directory name contains
    # security-related words (e.g. "secrets-injector", "stackland-secrets-webhook"):
    # a legitimate file like "values.yaml" inside such a directory would be blocked
    # even though the file itself is not a credential file.  The patterns are designed
    # to catch files with dangerous *names* — anchoring to the basename is correct.
    basename_lower = os.path.basename(path).lower()
    if DANGEROUS_FILE_PATTERNS == _DEFAULT_DANGEROUS_FILE_PATTERNS and not any(
        marker in basename_lower for marker in _DEFAULT_DANGEROUS_FILE_MARKERS
    ):
        return True, ""

    import re

    for pattern in DANGEROUS_FILE_PATTERNS:
        if re.search(pattern, basename_lower, re.IGNORECASE):
            return (
                False,
                f"Blocked: Access to sensitive file pattern '{pattern}' in path: {path}",
            )

    return True, ""


def check_command_safety(command: str) -> tuple[bool, str]:
    """Check if bash command is safe. Returns (is_safe, reason)."""
    if not command:
        return True, ""

    import re

    for pattern in DANGEROUS_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Blocked: Dangerous command pattern detected: {pattern}"

    return True, ""


def _autonomy_enabled() -> bool:
    """Return True when the per-user autonomy posture is active.

    Detected via the ``mapify.autonomy`` sentinel that ``mapify init --autonomy``
    writes into the gitignored ``.claude/settings.local.json``. The sentinel lives
    beside the permissions it governs so posture and permissions cannot drift
    apart. Read fresh on each invocation (the hook is a short-lived subprocess).
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    path = os.path.join(project_dir, ".claude", "settings.local.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 -- deliberate fallback/resilience boundary, must not propagate
        return False
    return (
        isinstance(data, dict)
        and isinstance(data.get("mapify"), dict)
        and data["mapify"].get("autonomy") is True
    )


def check_autonomy_git_block(command: str) -> tuple[bool, str]:
    """Hard-block ``git commit`` / ``git push`` when autonomy mode is active.

    Under a broad ``Bash(*)`` allow the permission-level deny for git commit/push
    is bypassable (``bash -c 'git commit'`` matches as ``bash``, not as
    ``git commit``). This PreToolUse hook sees the raw command string, so a single
    regex over the whole command catches the wrapped/chained forms too — it is the
    only gate that survives ``bash -c``. Catches realistic (sloppy /
    model-generated) bypasses, not a determined adversary; pair with branch
    protection for an absolute guarantee.
    """
    if not command or not _autonomy_enabled():
        return True, ""

    import re

    # ``git`` must start a shell token (handles ``bash -c 'git commit'``);
    # optional git options / ``-C <path>`` may sit between git and the subcommand;
    # the subcommand must itself be a full token (avoids matching ``committing``).
    git_block = re.compile(
        r"(?:^|[\s;&|`'\"()])"
        r"git\s+"
        r"(?:-\S+\s+|-C\s+\S+\s+|-c\s+\S+\s+)*"
        r"(?:commit|push)"
        r"(?:$|[\s;&|`'\"()])",
        re.IGNORECASE,
    )
    if git_block.search(command):
        return (
            False,
            ("Autonomy mode blocks git commit/push — run it yourself "
            "(human owns commit/push)."),
        )
    return True, ""


# =============================================================================
# Verifier-class capability boundary (#424)
# =============================================================================

# Agents dispatched with a read-and-report contract. They legitimately write
# their own review artifacts under `.map/<branch>/`, but must never mutate
# source or the branch — a final-verifier run once hand-edited generated trees
# and committed them mid-audit, then reported "working tree clean" for its own
# post-commit state, masking the breakage from the orchestrating session.
VERIFIER_AGENT_TYPES = frozenset(
    {
        "final-verifier",
        "monitor",
        "evaluator",
        "predictor",
        "documentation-reviewer",
    }
)

# Write scope a verifier keeps: its own branch-scoped artifact directory.
VERIFIER_WRITABLE_PREFIXES = (".map/", "/.map/")

# git subcommands that mutate the index, the worktree, refs, history, or config.
# `pull`/`fetch`/`submodule` are included because they move the very refs the
# verifier is auditing; `config`/`update-ref`/`symbolic-ref`/`filter-branch`/`notes`
# because they rewrite repository state out from under the audit. A verifier needs
# none of them — the list is deliberately fail-closed.
_GIT_MUTATING_SUBCOMMANDS = (
    "add",
    "am",
    "apply",
    "branch",
    "checkout",
    "cherry-pick",
    "clean",
    "commit",
    "config",
    "fetch",
    "filter-branch",
    "gc",
    "merge",
    "mv",
    "notes",
    "prune",
    "pull",
    "push",
    "rebase",
    "reset",
    "restore",
    "revert",
    "rm",
    "sparse-checkout",
    "stash",
    "submodule",
    "switch",
    "symbolic-ref",
    "tag",
    "update-ref",
    "worktree",
)


def _normalize_agent_type(raw: object) -> str:
    """Strip plugin scoping (`plugin:pkg:monitor` -> `monitor`) and lowercase."""
    if not isinstance(raw, str):
        return ""
    return raw.strip().split(":")[-1].lower()


def is_verifier_agent(agent_type: object) -> bool:
    """True when the tool call originates from a read-and-report agent."""
    return _normalize_agent_type(agent_type) in VERIFIER_AGENT_TYPES


def check_verifier_command(command: str) -> tuple[bool, str]:
    """Block git mutations from a verifier-class agent. Returns (is_safe, reason).

    Same token-anchored matching as the autonomy block so `bash -c 'git commit'`
    and `git -C <path> commit` are caught too. Read-only git (status, diff, log,
    show, rev-parse, ls-files) stays allowed — it is how a verifier gathers
    evidence.
    """
    if not command:
        return True, ""

    import re

    pattern = re.compile(
        r"(?:^|[\s;&|`'\"()])"
        r"git\s+"
        r"(?:-\S+\s+|-C\s+\S+\s+|-c\s+\S+\s+)*"
        r"(?:" + "|".join(_GIT_MUTATING_SUBCOMMANDS) + r")"
        r"(?:$|[\s;&|`'\"()])",
        re.IGNORECASE,
    )
    match = pattern.search(command)
    if match:
        return (
            False,
            (
                f"Blocked: verifier-class agents must not mutate the branch "
                f"(matched `{match.group(0).strip()}`). Report the finding in your "
                "verdict instead — the orchestrating session owns all git writes."
            ),
        )
    return True, ""


def check_verifier_path(path: str) -> tuple[bool, str]:
    """Confine verifier writes to `.map/`. Returns (is_safe, reason).

    The path is normalized BEFORE the prefix check: a raw text comparison accepts
    `.map/../src/mapify_cli/cli.py`, which starts with `.map/` yet resolves outside
    the allowed workspace.

    This is the outer boundary only. Runner-owned state inside `.map/`
    (`.map/scripts/**`, `step_state.json`, `approval_holds.json`, …) is separately
    protected from direct hand-editing by the workflow-gate state-tamper detector,
    which applies to every caller, not just verifiers.
    """
    if not path:
        return True, ""
    normalized = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
    normalized = normalized.removeprefix("./")
    if normalized.startswith(VERIFIER_WRITABLE_PREFIXES) or "/.map/" in normalized:
        return True, ""
    return (
        False,
        (
            f"Blocked: verifier-class agents may only write under `.map/`; "
            f"refused write to {path}. Report the required change in your verdict "
            "instead of applying it."
        ),
    )


def deny(reason: str) -> None:
    """Deny tool execution using structured PreToolUse decision control."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("{}")
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    # `agent_type` is present only when the hook fires inside a subagent.
    verifier = is_verifier_agent(input_data.get("agent_type"))

    # Check file-based tools
    if tool_name in ("Edit", "Write", "Read", "MultiEdit"):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
        is_safe, reason = check_file_safety(file_path)
        if not is_safe:
            deny(f"{reason} (tool={tool_name})")
        # Reads stay unrestricted — a verifier must be able to read everything.
        if verifier and tool_name in ("Edit", "Write", "MultiEdit"):
            is_safe, reason = check_verifier_path(file_path)
            if not is_safe:
                deny(f"{reason} (tool={tool_name})")

    # Check bash commands
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        is_safe, reason = check_command_safety(command)
        if not is_safe:
            deny(f"{reason} (tool={tool_name})")
        if verifier:
            is_safe, reason = check_verifier_command(command)
            if not is_safe:
                deny(reason)
        is_safe, reason = check_autonomy_git_block(command)
        if not is_safe:
            deny(reason)

    print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
