"""Detect the ``python3`` interpreter that shipped hooks and scripts will use.

MAP ships every hook (``.claude/hooks/``, ``.codex/hooks/``) and every
``.map/scripts/`` runner with a ``#!/usr/bin/env python3`` shebang. The installed
framework therefore runs under whatever ``python3`` resolves to on the user's
PATH -- **not** under the interpreter that runs ``mapify`` (which is typically a
uv-managed 3.12/3.13 when installed via ``uvx`` / ``uv tool install``).

Those shipped files use Python 3.11+ constructs (``datetime.UTC``, PEP 604
unions in evaluated annotations), so a stock macOS ``/usr/bin/python3`` (3.9)
makes every hook fail at import time with ``ImportError: cannot import name
'UTC' from 'datetime'`` -- a message that says nothing about a Python version
requirement. ``pyproject.toml`` declares ``requires-python = ">=3.11"``, but that
constrains only the installer, never the interpreter the hooks pick up at
runtime.

This module turns that deferred, cryptic failure into an install-time gate:

* :func:`detect_hook_interpreter` resolves ``python3`` exactly the way a shebang
  does (``PATH`` lookup) and reports its version.
* :func:`format_problem` renders an actionable message naming the required
  version, the resolved interpreter, and how to fix it -- or ``None`` when the
  interpreter is fine.

The shipped executables carry the matching runtime half of this contract: a
version guard rendered from
``templates_src/_partials/python-version-guard.py.jinja`` that exits with the
same explanation instead of an ``ImportError`` traceback.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Minimum interpreter version for every shipped hook and .map/scripts runner.
# Keep in sync with pyproject.toml ``requires-python`` and with
# templates_src/_partials/python-version-guard.py.jinja.
MINIMUM_PYTHON: Final[tuple[int, int]] = (3, 11)

#: Escape hatch for CI and for users who knowingly install before fixing PATH.
SKIP_ENV_VAR: Final[str] = "MAPIFY_SKIP_PYTHON_CHECK"

#: Command a shebang resolves; parameterised only so tests can probe a fake.
DEFAULT_COMMAND: Final[str] = "python3"

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

# Printed by the probe; kept Python-2-parsable so even a bizarre ``python3`` on
# PATH produces a parsable line rather than a SyntaxError we cannot explain.
_VERSION_PROBE: Final[str] = (
    "import sys; sys.stdout.write('%d.%d.%d' % sys.version_info[:3])"
)

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"(\d+)\.(\d+)\.(\d+)")

_PROBE_TIMEOUT_SECONDS: Final[float] = 5.0


def minimum_python_str() -> str:
    """Return the minimum version as ``"3.11"``."""
    return f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}"


@dataclass(frozen=True)
class InterpreterInfo:
    """What the shebang-resolved ``python3`` on PATH turned out to be.

    Attributes:
        command: The command that was resolved (normally ``python3``).
        executable: Absolute path ``PATH`` lookup produced, or ``None`` when the
            command is not on ``PATH`` at all.
        version: ``(major, minor, micro)`` when the version could be read, else
            ``None``.
        detection_error: Why the version is unknown (not on PATH, probe failed,
            unparsable output). ``None`` when :attr:`version` is populated.
        shadowed: Path to a nearer ``python3`` that was deliberately ignored
            because it lives in the environment running ``mapify`` (see
            :func:`_own_environment_bin_dirs`). ``None`` when nothing was skipped.
    """

    command: str = DEFAULT_COMMAND
    executable: str | None = None
    version: tuple[int, int, int] | None = None
    detection_error: str | None = None
    shadowed: str | None = None

    @property
    def found(self) -> bool:
        """True when the command was resolvable on ``PATH``."""
        return self.executable is not None

    @property
    def satisfies_minimum(self) -> bool:
        """True only when a version was read AND it meets :data:`MINIMUM_PYTHON`.

        An unknown version is never treated as satisfying the floor: if we could
        not run the interpreter, the hooks cannot either.
        """
        return self.version is not None and self.version[:2] >= MINIMUM_PYTHON

    @property
    def version_str(self) -> str:
        """Version as ``"3.9.6"``, or ``"unknown"`` when detection failed."""
        if self.version is None:
            return "unknown"
        return ".".join(str(part) for part in self.version)

    @property
    def summary(self) -> str:
        """One-line description suitable for a status table."""
        if not self.found:
            return f"{self.command} not found on PATH"
        if self.version is None:
            return f"{self.executable} (version unknown)"
        return f"{self.executable} (Python {self.version_str})"


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    major, minor, micro = (int(part) for part in match.groups())
    return (major, minor, micro)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _resolve_path(entry: str) -> Path:
    try:
        return Path(entry).resolve()
    except OSError:  # pragma: no cover - unreadable PATH entry
        return Path(entry)


def _own_environment_bin_dirs() -> set[Path]:
    """Directories belonging to the environment that runs ``mapify`` itself.

    ``uvx mapify init`` (the documented install path) runs from an *ephemeral* uv
    environment whose ``bin`` is prepended to PATH -- with a modern ``python3`` in
    it. That interpreter disappears when the command exits, so it is exactly the
    wrong thing to judge: the hooks installed by this run are launched later, by
    Claude Code, from a shell that never sees it. Same for ``uv run`` / an
    activated venv. Skip these directories so the check answers "what will an
    independent shell resolve?".

    Only a *virtual* environment is skipped (``sys.prefix != sys.base_prefix``).
    When mapify runs from a plain system/Homebrew install, its own interpreter is
    a legitimate PATH-visible ``python3`` that hooks will resolve too, so nothing
    is excluded and the check stays a straight ``which`` lookup.
    """
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return set()
    candidates: set[Path] = set()
    if sys.executable:
        candidates.add(_resolve_path(sys.executable).parent)
    if sys.prefix:
        candidates.add(_resolve_path(sys.prefix) / "bin")
        candidates.add(_resolve_path(sys.prefix) / "Scripts")
    return candidates


def _path_outside_own_environment(raw_path: str | None = None) -> str:
    """Return PATH with the running environment's bin directories removed.

    Empty entries are preserved: POSIX ``execvp`` (and therefore
    ``#!/usr/bin/env python3``) reads an empty ``PATH`` entry as the current
    directory, and :func:`shutil.which` follows the same rule. Dropping them
    would let this check approve a *later* interpreter while the installed hooks
    keep resolving the ``./python3`` next to them. An empty entry is filtered
    only when the current directory *is* one of our own environment bin
    directories, which is what :func:`_resolve_path` reports for it.
    """
    source = os.environ.get("PATH", os.defpath) if raw_path is None else raw_path
    own = _own_environment_bin_dirs()
    kept = [
        entry for entry in source.split(os.pathsep) if _resolve_path(entry) not in own
    ]
    return os.pathsep.join(kept)


def _resolve_shebang_interpreter(command: str) -> tuple[str | None, str | None]:
    """Resolve *command* as an independent shell would.

    Returns:
        ``(executable, shadowed)``. *shadowed* is the nearer match that was
        ignored because it belongs to this process's own environment, or ``None``.
        When PATH offers nothing outside that environment, its own interpreter is
        returned as *executable* (better a real verdict than none).
    """
    nearest = shutil.which(command)
    outside = shutil.which(command, path=_path_outside_own_environment())
    if outside is None:
        return nearest, None
    if nearest is not None and _resolve_path(nearest) == _resolve_path(outside):
        return outside, None
    return outside, nearest


def detect_hook_interpreter(command: str = DEFAULT_COMMAND) -> InterpreterInfo:
    """Resolve *command* the way a ``#!/usr/bin/env`` shebang does and read its version.

    Args:
        command: Interpreter command to resolve on ``PATH``.

    Returns:
        An :class:`InterpreterInfo`. Never raises: every failure mode (absent
        command, unrunnable interpreter, timeout, unparsable output) is reported
        through :attr:`InterpreterInfo.detection_error`.
    """
    executable, shadowed = _resolve_shebang_interpreter(command)
    if executable is None:
        return InterpreterInfo(
            command=command,
            detection_error=f"{command} was not found on PATH",
            shadowed=shadowed,
        )
    version, error = _probe_version(executable)
    return InterpreterInfo(
        command=command,
        executable=executable,
        version=version,
        detection_error=error,
        shadowed=shadowed,
    )


def _probe_version(executable: str) -> tuple[tuple[int, int, int] | None, str | None]:
    """Return ``(version, detection_error)`` for *executable*; exactly one is set."""
    # Fast path: the resolved interpreter IS the one running mapify, so its version
    # is already known and no subprocess is needed.
    try:
        if sys.executable and os.path.samefile(executable, sys.executable):
            return (
                sys.version_info[0],
                sys.version_info[1],
                sys.version_info[2],
            ), None
    except OSError:
        pass

    try:
        proc = subprocess.run(
            [executable, "-c", _VERSION_PROBE],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, (
            f"{executable} did not respond within {_PROBE_TIMEOUT_SECONDS:.0f}s "
            "(on macOS a /usr/bin/python3 stub can block on the Xcode Command "
            "Line Tools prompt)"
        )
    except OSError as exc:
        return None, f"{executable} could not be executed: {exc}"

    if proc.returncode != 0:
        detail = _first_line(proc.stderr) or f"exit code {proc.returncode}"
        return None, f"{executable} failed the version probe: {detail}"

    version = _parse_version(proc.stdout)
    if version is None:
        return None, (
            f"{executable} printed an unparsable version: "
            f"{_first_line(proc.stdout)!r}"
        )
    return version, None


def skip_requested(env: Mapping[str, str] | None = None) -> bool:
    """True when :data:`SKIP_ENV_VAR` opts out of the check."""
    source: Mapping[str, str] = os.environ if env is None else env
    return source.get(SKIP_ENV_VAR, "").strip().lower() in _TRUTHY


def remediation_lines() -> list[str]:
    """Actionable, copy-pasteable ways to get a new enough ``python3`` on PATH."""
    minimum = minimum_python_str()
    return [
        f"  Homebrew (macOS):  brew install python@3.12   # or newer than {minimum}",
        "  uv:                uv python install 3.12",
        "  pyenv:             pyenv install 3.12 && pyenv global 3.12",
        "  Then confirm:      python3 --version",
    ]


def format_problem(info: InterpreterInfo) -> str | None:
    """Render an actionable message for a failing interpreter, else ``None``.

    Args:
        info: Result of :func:`detect_hook_interpreter`.

    Returns:
        Plain text (no rich markup, no square brackets so callers can print it
        through ``rich`` unescaped) describing the problem and the fix, or
        ``None`` when *info* satisfies :data:`MINIMUM_PYTHON`.
    """
    if info.satisfies_minimum:
        return None

    minimum = minimum_python_str()
    if not info.found:
        headline = (
            f"{info.command} was not found on PATH, so MAP hooks and "
            f".map/scripts/ runners cannot start."
        )
    elif info.version is None:
        headline = (
            f"could not determine the {info.command} version: "
            f"{info.detection_error}."
        )
    else:
        headline = (
            f"{info.command} on PATH is {info.summary}, "
            f"but MAP needs Python {minimum} or newer."
        )

    lines = [
        headline,
        "",
        (
            "Every shipped hook and .map/scripts/ runner starts with "
            "#!/usr/bin/env python3, so they all run under this interpreter -- not "
            f"under the one running mapify. On Python older than {minimum} they "
            "fail at import (for example: cannot import name 'UTC' from 'datetime')."
        ),
    ]
    if info.shadowed:
        lines += [
            "",
            (
                f"Note: {info.shadowed} was skipped -- it belongs to the "
                "environment running mapify (uvx/uv run/venv), which is gone by "
                "the time Claude Code launches a hook."
            ),
        ]
    lines += [
        "",
        f"Install Python {minimum}+ and make sure python3 resolves to it:",
        *remediation_lines(),
        "",
        (
            f"To install anyway, pass --skip-python-check or set {SKIP_ENV_VAR}=1; "
            "hooks and .map/scripts/ will stay broken until python3 is upgraded."
        ),
    ]
    return "\n".join(lines)


def check_hook_python(
    *, skip: bool = False, command: str = DEFAULT_COMMAND
) -> str | None:
    """Detect the hook interpreter and return a problem message, or ``None``.

    Args:
        skip: When True (CLI flag), skip detection entirely and report no
            problem. :data:`SKIP_ENV_VAR` has the same effect.
        command: Interpreter command to resolve.

    Returns:
        The message from :func:`format_problem`, or ``None`` when the
        interpreter is acceptable or the check was skipped.
    """
    if skip or skip_requested():
        return None
    return format_problem(detect_hook_interpreter(command))
