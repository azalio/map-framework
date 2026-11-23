"""Upgrade existing installations after the removal of the Safety Guardrails hook."""

from __future__ import annotations

import json
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


def read_settings_for_refresh(path: Path) -> dict:
    """Read settings before a writer can discard a legacy hook registration."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a settings object")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        if (path.parent / "hooks" / RETIRED_SAFETY_HOOK).is_file():
            raise ValueError(
                f"Cannot refresh unreadable hook settings at {path}"
            ) from exc
        return {}


def remove_legacy_local_registration(claude_dir: Path) -> None:
    """MAP 3.1 and 3.2 installed the command in the per-project local settings."""
    path = claude_dir / "settings.local.json"
    if (
        claude_dir.is_symlink()
        or path.is_symlink()
        or project_owns_retired_script(claude_dir)
    ):
        return
    data = read_settings_for_refresh(path)
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
    """Keep project-authored launchers when replacing the shipped Claude settings."""
    directory = dest.parent
    if not dest.is_file() or dest.is_symlink():
        return copy_managed_file(src, dest, version)
    current = read_settings_for_refresh(dest)
    retained: dict[str, list[dict]] = {}
    project_owned = project_owns_retired_script(directory)
    for event, group, hooks in _groups(current):
        custom = [
            hook
            for hook in hooks
            if (project_owned or _command(hook) not in _CLAUDE_LAUNCHERS)
            and RETIRED_SAFETY_HOOK in _command(hook)
        ]
        if custom:
            retained.setdefault(event, []).append({**group, "hooks": custom})
    if not retained:
        return copy_managed_file(src, dest, version)
    template = json.loads(src.read_text(encoding="utf-8"))
    for event, groups in retained.items():
        template["hooks"].setdefault(event, []).extend(groups)
    content = json.dumps(template, indent=2, ensure_ascii=False) + "\n"
    return _copy_json_managed(src, dest, content, version, compute_hash(content))


def project_owns_retired_script(provider_dir: Path) -> bool:
    """Protect a project script when it differs from the installed MAP copy."""
    hook_dir = provider_dir / "hooks"
    script = hook_dir / RETIRED_SAFETY_HOOK
    if provider_dir.is_symlink() or hook_dir.is_symlink() or script.is_symlink():
        return True
    try:
        content = script.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError):
        return True
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
    return not stock


def remove_retired_safety_hook(provider_dir: Path) -> None:
    script = provider_dir / "hooks" / RETIRED_SAFETY_HOOK
    if script.is_file() and not project_owns_retired_script(provider_dir):
        script.unlink(missing_ok=True)
