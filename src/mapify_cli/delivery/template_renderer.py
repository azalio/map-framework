"""Jinja2-based template renderer for MAP Framework delivery.

Renders `templates_src/**/*.jinja` files into destination trees, with
safety guarantees:

  D7  – Environment uses non-conflicting custom delimiters so that
        Handlebars ``{{ }}``, bash ``[[ ]]``, and Python type hints
        like ``Callable[[...]]`` pass through verbatim:

            block_start_string   = '[%'
            block_end_string     = '%]'
            variable_start_string = '<%'
            variable_end_string   = '%>'
            comment_start_string  = '[#'
            comment_end_string    = '#]'
            keep_trailing_newline = True
            autoescape            = False

  D7a – Post-render each file is scanned for residual directive tokens
        ``[%``, ``<%``, ``[#``.  Any hit raises ValueError before the
        file is ever written to disk.

  INV-9 / HC-8 – All outputs are rendered into a TemporaryDirectory
        first.  Only after every render succeeds are the live files
        written.  Paths under ``.claude/hooks/`` are written LAST so a
        broken template cannot corrupt hooks that are already live.

  HC-8 – dry_run=True renders+verifies into temp but does NOT copy to
        the live destination.

Jinja2 is imported LAZILY inside ``get_environment()`` – importing this
module does NOT bring jinja2 into ``sys.modules``.

Template context provided to every template:
    PROVIDER – 'claude' or 'codex'
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import jinja2


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRAY_TOKENS = ("[%", "<%", "[#")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_no_stray_delimiters(text: str) -> None:
    """Raise ValueError if *text* contains residual Jinja2 directive tokens.

    Scans for ``[%``, ``<%``, and ``[#``.  A hit means the template had an
    un-rendered expression, which indicates a template authoring bug.

    Args:
        text: Rendered output string to validate.

    Raises:
        ValueError: If any stray delimiter token is found.
    """
    for token in _STRAY_TOKENS:
        idx = text.find(token)
        if idx != -1:
            context = text[max(0, idx - 20) : idx + 40].replace("\n", "\\n")
            raise ValueError(
                f"Stray delimiter token {token!r} found in rendered output near: {context!r}"
            )


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def get_environment() -> jinja2.Environment:
    """Return a Jinja2 Environment configured with MAP-safe custom delimiters.

    Uses delimiters that do NOT conflict with Handlebars, bash, or Python
    type hints.  See module docstring (D7) for the exact configuration.

    Jinja2 is imported lazily here so that importing this module does not
    load jinja2 into ``sys.modules``.

    Returns:
        Configured jinja2.Environment instance.
    """
    import jinja2  # noqa: PLC0415  (lazy import by design – VC4)

    return jinja2.Environment(
        block_start_string="[%",
        block_end_string="%]",
        variable_start_string="<%",
        variable_end_string="%>",
        comment_start_string="[#",
        comment_end_string="#]",
        keep_trailing_newline=True,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
    )


# ---------------------------------------------------------------------------
# Write-plan dataclass
# ---------------------------------------------------------------------------


@dataclass
class _WriteEntry:
    """One file to be written during the live-copy phase."""

    rendered_path: Path  # path inside the temp dir
    dest_path: Path  # absolute live destination path
    is_hook: bool = field(init=False)

    def __post_init__(self) -> None:
        # Classify as hook based on the dest path containing .claude/hooks/
        try:
            parts = self.dest_path.parts
            self.is_hook = any(
                parts[i] == ".claude" and i + 1 < len(parts) and parts[i + 1] == "hooks"
                for i in range(len(parts))
            )
        except Exception:
            self.is_hook = False


# ---------------------------------------------------------------------------
# Atomic write helper (reuse pattern from verification_recorder.py)
# ---------------------------------------------------------------------------


def _atomic_write_file(src: Path, dest: Path) -> None:
    """Copy *src* to *dest* atomically, preserving executable bits.

    Creates a temp file on the same filesystem as *dest*, copies content,
    then renames atomically.  Executable bits from *src* are preserved.

    Args:
        src: Source file (rendered output).
        dest: Destination path (live target).

    Raises:
        OSError: If the file cannot be written.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    src_mode = src.stat().st_mode
    data = src.read_bytes()

    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(data)

        # Preserve executable bits from source
        new_mode = tmp_path.stat().st_mode
        if src_mode & stat.S_IXUSR:
            new_mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        tmp_path.chmod(new_mode)

        tmp_path.replace(dest)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass  # best-effort cleanup
        raise


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------


def render_tree(
    provider: str,
    *,
    dry_run: bool = False,
    templates_src_root: Path | None = None,
    dest_root: Path | None = None,
) -> list[Path]:
    """Render all ``.jinja`` templates from *templates_src_root* into *dest_root*.

    Safety contract (INV-9 / HC-8):
      1. Every template is rendered into a TemporaryDirectory.
      2. If ANY render raises, the function aborts before writing ANY live file.
      3. Live files are written with paths under ``.claude/hooks/`` LAST.
      4. dry_run=True skips the live-write phase entirely.

    Args:
        provider: Provider name passed as ``PROVIDER`` context var
                  (typically ``'claude'`` or ``'codex'``).
        dry_run:  When True, render+verify but do not write live files.
        templates_src_root: Root of the ``.jinja`` source tree.
                  Defaults to ``<package>/templates_src``.
        dest_root: Root for live destination files.
                  Defaults to current working directory.

    Returns:
        List of live destination paths that were written (empty on dry_run).

    Raises:
        RuntimeError: If *templates_src_root* does not exist.
        ValueError: If a rendered file contains stray delimiter tokens.
        jinja2.TemplateSyntaxError: If a template has invalid syntax.
    """
    # Resolve defaults
    if templates_src_root is None:
        templates_src_root = _default_templates_src_root()
    if dest_root is None:
        dest_root = Path.cwd()

    if not templates_src_root.exists():
        raise RuntimeError(
            f"templates_src root not found: {templates_src_root}. "
            "Run 'make sync-templates' or provide a templates_src_root."
        )

    env = get_environment()
    context = {"PROVIDER": provider}

    # Collect all .jinja templates under templates_src_root
    jinja_files = sorted(templates_src_root.rglob("*.jinja"))

    # Phase 1: render ALL templates into a temp dir; abort on first error.
    write_plan: list[_WriteEntry] = []

    with tempfile.TemporaryDirectory(prefix="map_render_") as tmp_str:
        tmp_root = Path(tmp_str)

        for jinja_file in jinja_files:
            rel_path = jinja_file.relative_to(templates_src_root)
            # Strip .jinja suffix for destination name
            dest_rel = rel_path.with_suffix("")
            tmp_dest = tmp_root / dest_rel
            tmp_dest.parent.mkdir(parents=True, exist_ok=True)

            # Render (may raise TemplateSyntaxError / UndefinedError / etc.)
            template_text = jinja_file.read_text(encoding="utf-8")
            tmpl = env.from_string(template_text)
            rendered = tmpl.render(**context)

            # D7a: check for residual directive tokens
            assert_no_stray_delimiters(rendered)

            tmp_dest.write_text(rendered, encoding="utf-8")
            # Propagate executable bits from source template
            src_mode = jinja_file.stat().st_mode
            if src_mode & stat.S_IXUSR:
                tmp_dest.chmod(tmp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            live_dest = dest_root / dest_rel
            entry = _WriteEntry(rendered_path=tmp_dest, dest_path=live_dest)
            write_plan.append(entry)

        # Sort: non-hooks first, hooks last (INV-9)
        write_plan.sort(key=lambda e: (1 if e.is_hook else 0, e.dest_path))

        if dry_run:
            return []

        # Phase 2: write live files (hooks last)
        written: list[Path] = []
        for entry in write_plan:
            _atomic_write_file(entry.rendered_path, entry.dest_path)
            written.append(entry.dest_path)

    return written


# ---------------------------------------------------------------------------
# Default path resolution
# ---------------------------------------------------------------------------


def _default_templates_src_root() -> Path:
    """Return the default templates_src directory (package-relative).

    Returns:
        Absolute path to the templates_src root.
    """
    # <package_root>/templates_src
    module_dir = Path(__file__).parent.parent  # src/mapify_cli/
    candidate = module_dir / "templates_src"
    if candidate.exists():
        return candidate

    # dev layout: repo_root/templates_src
    for parent in [module_dir.parent, module_dir.parent.parent]:
        c = parent / "templates_src"
        if c.exists():
            return c

    # Return the primary candidate even if it doesn't exist yet;
    # render_tree will raise a clear RuntimeError.
    return module_dir / "templates_src"


# ---------------------------------------------------------------------------
# Optional __main__ entry point stub (ST-004 wires the real CLI)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render MAP jinja2 templates")
    parser.add_argument("provider", choices=["claude", "codex"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = render_tree(args.provider, dry_run=args.dry_run)
    for p in paths:
        print(p, file=sys.stdout)
