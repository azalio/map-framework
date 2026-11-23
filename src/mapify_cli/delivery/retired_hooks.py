"""Upgrade existing installations after the removal of the Safety Guardrails hook."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from mapify_cli.delivery.managed_file_copier import (
    CopyResult,
    _copy_json_managed,
    compute_hash,
    copy_managed_file,
    extract_metadata,
)

RETIRED_SAFETY_HOOK = "safety-guardrails.py"
_CLAUDE_LAUNCHERS = {
    f"$CLAUDE_PROJECT_DIR/.claude/hooks/{RETIRED_SAFETY_HOOK}",
    f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{RETIRED_SAFETY_HOOK}',
}


def _groups(settings: dict) -> Iterator[tuple[str, dict, list]]:
    events = settings.get("hooks")
    if isinstance(events, dict):
        for event, entries in events.items():
            if isinstance(entries, list):
                for group in entries:
                    if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                        yield event, group, group["hooks"]


def _command(hook: Any) -> str:
    value = hook.get("command") if isinstance(hook, dict) else None
    return value if isinstance(value, str) else ""


def _references_script(command: str, provider_dir: Path) -> bool:
    relative_path = f"{provider_dir.name}/hooks/{RETIRED_SAFETY_HOOK}"
    return bool(
        re.search(rf"(?<![\w.-]){re.escape(relative_path)}(?![\w./-])", command)
    )


def remove_legacy_local_registration(claude_dir: Path) -> None:
    """MAP 3.1 and 3.2 installed the command in the per-project local settings."""
    path = claude_dir / "settings.local.json"
    if claude_dir.is_symlink() or path.is_symlink():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    changed = False
    for event, group, hooks in list(_groups(data)):
        if event != "PreToolUse":
            continue
        keep = [hook for hook in hooks if _command(hook) not in _CLAUDE_LAUNCHERS]
        if len(keep) != len(hooks):
            changed = True
            if keep:
                group["hooks"] = keep
            else:
                data["hooks"][event].remove(group)
    if changed:
        with TemporaryDirectory(dir=claude_dir) as temp:
            staged = Path(temp) / path.name
            staged.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            staged.chmod(path.stat().st_mode & 0o777)
            staged.replace(path)


def copy_claude_settings(src: Path, dest: Path, version: str) -> CopyResult:
    """Preserve team launchers that still call the script under a custom command."""
    directory = dest.parent
    if (
        not (directory / "hooks" / RETIRED_SAFETY_HOOK).is_file()
        or not dest.is_file()
        or dest.is_symlink()
    ):
        return copy_managed_file(src, dest, version)
    try:
        current = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    template = json.loads(src.read_text(encoding="utf-8"))
    changed = False
    for event, group, hooks in _groups(current if isinstance(current, dict) else {}):
        custom = [
            hook
            for hook in hooks
            if _command(hook) not in _CLAUDE_LAUNCHERS
            and _references_script(_command(hook), directory)
        ]
        if custom:
            template["hooks"].setdefault(event, []).append({**group, "hooks": custom})
            changed = True
    if not changed:
        return copy_managed_file(src, dest, version)
    content = json.dumps(template, indent=2, ensure_ascii=False) + "\n"
    return _copy_json_managed(src, dest, content, version, compute_hash(content))


def retired_safety_hook_is_registered(provider_dir: Path) -> bool | None:
    """Return None when the installed registrations cannot be inspected."""
    paths: tuple[Path, ...]
    if provider_dir.name == ".codex":
        user_dir = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        paths = (provider_dir / "hooks.json", user_dir / "hooks.json")
    else:
        user_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        paths = (
            provider_dir / "settings.json",
            provider_dir / "settings.local.json",
            user_dir / "settings.json",
        )
    known = True
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            known = False
            continue
        if not isinstance(data, dict):
            known = False
            continue
        if any(
            _references_script(_command(hook), provider_dir)
            for _, _, hooks in _groups(data)
            for hook in hooks
        ):
            return True
    return False if known else None


def remove_retired_safety_hook(provider_dir: Path) -> None:
    """Remove a stock copy on refresh. A locally edited script belongs to the project."""
    hook_dir = provider_dir / "hooks"
    script = hook_dir / RETIRED_SAFETY_HOOK
    if (
        provider_dir.is_symlink()
        or hook_dir.is_symlink()
        or script.is_symlink()
        or not script.is_file()
    ):
        return
    try:
        content = script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    metadata, body = extract_metadata(content, ".py")
    if isinstance(metadata, dict) and metadata.get("generated_by") == "mapify-cli":
        # Watched installations wrapped the source after its shebang in a fence.
        if body.endswith("# map:end\n"):
            body = re.sub(
                r"^# map:start\n",
                "",
                body.removesuffix("# map:end\n"),
                count=1,
                flags=re.MULTILINE,
            )
        stock = compute_hash(body) == metadata.get("template_hash")
    else:
        # Shipped raw (pre-metadata) Claude releases and the last provider trees.
        stock = (
            compute_hash(content)
            in {
                "8420fd77e27b484dc21b2922c4a1c9533bcc0f37cc15672cc6ce3ce56dfaf150",  # 3.1-3.2
                "3dcac5caa0721f0fa35082fff550a4e867ba4d4ec6a627e00aff897986578b24",  # 3.3-3.5
                "983718c8a32130add2b2aaa13e70d074b96bb9c137f2b166ac19502eade2144c",
                "e909232e0b199a653340bcde021527678c427ab52aac4517ee550fb898584c8d",
            }
        )
    if stock and retired_safety_hook_is_registered(provider_dir) is False:
        script.unlink()
