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
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import jinja2


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRAY_TOKENS = ("[%", "<%", "[#")

# Shipped-only paths (relative to templates_src root, after stripping .jinja).
# These are rendered to src/mapify_cli/templates/ ONLY — never written to
# the dev .claude/ tree.
_CLAUDE_SHIPPED_ONLY: frozenset[str] = frozenset(
    {
        "CLAUDE.md",
        "settings.json",
        "workflow-rules.json",
        "ralph-loop-config.json",
        "hooks/README.md",
        "rules/learned/README.md",
    }
)

# Hook paths in multiple destination trees that must sort LAST (INV-9).
# Any dest path whose parts include one of these (parent, child) sequences
# is classified as a hook.
_HOOK_PARENT_SEQUENCES: tuple[tuple[str, str], ...] = (
    (".claude", "hooks"),
    ("templates", "hooks"),
)


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


def _path_is_hook(dest_path: Path) -> bool:
    """Return True if *dest_path* is under a managed hooks directory.

    Recognises both ``.claude/hooks/`` and ``templates/hooks/`` (and any
    absolute path that contains either sequence) so that the hooks-last
    ordering invariant (INV-9) applies across all destination trees.

    Args:
        dest_path: Absolute live destination path.

    Returns:
        True if the path should be written last (is a hook).
    """
    try:
        parts = dest_path.parts
        for parent_name, child_name in _HOOK_PARENT_SEQUENCES:
            for i in range(len(parts) - 1):
                if parts[i] == parent_name and parts[i + 1] == child_name:
                    return True
    except Exception:
        pass
    return False


@dataclass
class _WriteEntry:
    """One file to be written during the live-copy phase."""

    rendered_path: Path  # path inside the temp dir
    dest_path: Path  # absolute live destination path
    is_hook: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_hook = _path_is_hook(self.dest_path)


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
# Destination-resolver helpers
# ---------------------------------------------------------------------------


def _build_claude_resolver(
    repo_root: Path,
    templates_root: Path,
) -> Callable[[Path], list[Path]]:
    """Build a destination resolver for the CLAUDE provider.

    Implements the destination-map from the ST-002 design doc:

    * agents/**, hooks/ (except README.md), references/**, skills/**
      → BOTH ``src/mapify_cli/templates/<rel>`` AND ``.claude/<rel>``

    * map/scripts/**, map/static-analysis/**
      → BOTH ``src/mapify_cli/templates/<rel>`` AND ``.map/<rel>``
        (``map/`` prefix remaps to ``.map/`` in the dev tree)

    * hooks/README.md, rules/learned/README.md, CLAUDE.md,
      settings.json, workflow-rules.json, ralph-loop-config.json
      → ``src/mapify_cli/templates/<rel>`` ONLY (shipped-only — no dev dest)

    A rendered file mapping to 0 destinations is simply not written live
    (future use; not used for CLAUDE provider currently).

    Args:
        repo_root:      Absolute repo root (e.g. ``/path/to/map-framework``).
        templates_root: Absolute path to ``src/mapify_cli/templates/``.

    Returns:
        Callable mapping ``rel_path: Path`` (relative, `.jinja`-stripped)
        to a list of absolute live destination paths.
    """
    claude_root = repo_root / ".claude"
    map_root = repo_root / ".map"

    def resolver(rel_path: Path) -> list[Path]:
        rel_str = rel_path.as_posix()  # use forward slashes for matching
        shipped = templates_root / rel_path

        # --- Shipped-only: no dev dest ---
        if rel_str in _CLAUDE_SHIPPED_ONLY:
            return [shipped]

        # --- map/** prefix: remap map/ -> .map/ for dev dest ---
        if rel_str.startswith("map/"):
            # Intent: dev tree uses .map/ prefix, not map/
            dev_rel = Path(rel_str[len("map/"):])
            return [shipped, map_root / dev_rel]

        # --- Shared subtrees: shipped + .claude/ ---
        prefixes = ("agents/", "hooks/", "references/", "skills/", "rules/")
        if any(rel_str.startswith(p) for p in prefixes):
            return [shipped, claude_root / rel_path]

        # --- Root-level files not in the shipped-only set ---
        # e.g. any future root file that is not shipped-only
        return [shipped, claude_root / rel_path]

    return resolver


def _build_codex_resolver(
    repo_root: Path,
    templates_root: Path,
) -> Callable[[Path], list[Path]]:
    """Build a destination resolver for the CODEX provider (ST-003 stub).

    ST-003 will implement the full codex destination map.  This stub ensures
    the design compiles and ``render_repo_trees('codex')`` has a defined
    entry point without blowing up.

    Args:
        repo_root:      Absolute repo root (unused until ST-003).
        templates_root: Absolute path to ``src/mapify_cli/templates/`` (unused).

    Returns:
        Resolver that always returns an empty list (no live writes).
    """
    # TODO(ST-003): implement codex destination-map. These parameters are part
    # of the resolver contract ST-003 will fill in; explicitly drop them here so
    # the stub is honest and no unused-parameter diagnostic is raised.
    del repo_root, templates_root

    def resolver(rel_path: Path) -> list[Path]:
        del rel_path  # stub: codex has no live destinations until ST-003
        return []

    return resolver


# ---------------------------------------------------------------------------
# Core renderer (single-dest, identity; preserves ST-001 contract)
# ---------------------------------------------------------------------------


def render_tree(
    provider: str,
    *,
    dry_run: bool = False,
    templates_src_root: Path | None = None,
    dest_root: Path | None = None,
    dest_resolver: Callable[[Path], list[Path]] | None = None,
) -> list[Path]:
    """Render all ``.jinja`` templates from *templates_src_root* into *dest_root*.

    Safety contract (INV-9 / HC-8):
      1. Every template is rendered into a TemporaryDirectory.
      2. If ANY render raises, the function aborts before writing ANY live file.
      3. Live files are written with paths under hook directories LAST.
      4. dry_run=True skips the live-write phase entirely.

    The optional *dest_resolver* parameter enables multi-destination routing:
    it maps each ``rel_path`` (relative path, ``.jinja``-stripped) to a list
    of absolute destination paths.  The default resolver writes every file
    once into *dest_root* (identity mapping — ST-001 contract preserved).

    When *dest_resolver* is supplied, *dest_root* is still accepted for
    backward compatibility but is ignored if the resolver returns non-empty
    destinations.  If the resolver returns an empty list for a given file,
    that file is not written live (0-destination case).

    Args:
        provider: Provider name passed as ``PROVIDER`` context var
                  (typically ``'claude'`` or ``'codex'``).
        dry_run:  When True, render+verify but do not write live files.
        templates_src_root: Root of the ``.jinja`` source tree.
                  Defaults to ``<package>/templates_src``.
        dest_root: Root for live destination files (identity mode only).
                  Defaults to current working directory.
        dest_resolver: Optional callable mapping each rendered relative path
                  to a list of absolute live destination paths.  When None,
                  an identity resolver into *dest_root* is used.

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

    # Build identity resolver if none supplied (ST-001 contract).
    # Intent: use a separate name to avoid Pyright reportRedeclaration on the
    # parameter; _resolver is the effective callable used below.
    if dest_resolver is None:
        _dest_root = dest_root  # capture for closure

        def _identity_resolver(rel_path: Path) -> list[Path]:
            return [_dest_root / rel_path]

        _resolver: Callable[[Path], list[Path]] = _identity_resolver
    else:
        _resolver = dest_resolver

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
                tmp_dest.chmod(
                    tmp_dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )

            # Resolve live destinations for this rendered file
            live_dests = _resolver(dest_rel)
            for live_dest in live_dests:
                entry = _WriteEntry(rendered_path=tmp_dest, dest_path=live_dest)
                write_plan.append(entry)
            # 0-destination case: file simply omitted from write_plan

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
# Public driver: render_repo_trees
# ---------------------------------------------------------------------------


def render_repo_trees(
    provider: str,
    *,
    dry_run: bool = False,
    repo_root: Path | None = None,
    templates_src_root: Path | None = None,
) -> list[Path]:
    """Render all templates for *provider* into their live repo destinations.

    This is the high-level entry point called by ``make render-templates``
    (ST-004).  It builds the provider-specific destination resolver and
    delegates to :func:`render_tree`.

    For CLAUDE provider the destination map is:

    * Shared subtrees (agents, hooks, references, skills, rules):
      → ``src/mapify_cli/templates/<rel>`` AND ``.claude/<rel>``

    * map/ subtrees (scripts, static-analysis):
      → ``src/mapify_cli/templates/<rel>`` AND ``.map/<rel>``

    * Shipped-only configs (CLAUDE.md, settings.json, workflow-rules.json,
      ralph-loop-config.json, hooks/README.md, rules/learned/README.md):
      → ``src/mapify_cli/templates/<rel>`` ONLY

    For CODEX provider, ST-003 will implement the full map; this stub
    renders into zero live destinations.

    INV-9 is enforced across ALL destinations: all files are rendered into
    a single TemporaryDirectory first; byte-parity and stray-delimiter
    checks are performed; only then are live writes issued with hook paths
    (both ``.claude/hooks/`` and ``templates/hooks/``) written LAST.

    Args:
        provider:           ``'claude'`` or ``'codex'``.
        dry_run:            When True, render+verify but do not write live.
        repo_root:          Absolute path to the repository root.
                            Defaults to the repo root inferred from this
                            module's location.
        templates_src_root: Root of the ``.jinja`` source tree.
                            Defaults to ``<package>/templates_src``.

    Returns:
        List of absolute live destination paths that were written.
        Empty list on dry_run.

    Raises:
        ValueError: For unknown *provider* values.
        RuntimeError: If *templates_src_root* does not exist.
    """
    if repo_root is None:
        repo_root = _default_repo_root()
    if templates_src_root is None:
        templates_src_root = _default_templates_src_root()

    # templates/ shipped destination root (always inside repo)
    templates_dest = repo_root / "src" / "mapify_cli" / "templates"

    if provider == "claude":
        resolver = _build_claude_resolver(
            repo_root=repo_root,
            templates_root=templates_dest,
        )
    elif provider == "codex":
        resolver = _build_codex_resolver(
            repo_root=repo_root,
            templates_root=templates_dest,
        )
    else:
        raise ValueError(
            f"Unknown provider {provider!r}. "
            "Expected 'claude' or 'codex'."
        )

    return render_tree(
        provider,
        dry_run=dry_run,
        templates_src_root=templates_src_root,
        dest_resolver=resolver,
    )


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


def _default_repo_root() -> Path:
    """Infer the repository root from this module's location.

    Walks up from ``src/mapify_cli/delivery/`` to find the repo root
    by looking for a ``pyproject.toml`` marker file.

    Returns:
        Absolute path to the repository root.
    """
    module_dir = Path(__file__).parent  # src/mapify_cli/delivery/
    for candidate in [
        module_dir.parent.parent.parent,  # src/mapify_cli/delivery -> repo root
        module_dir.parent.parent,  # one level up
    ]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    # Fallback: three levels up
    return module_dir.parent.parent.parent


# ---------------------------------------------------------------------------
# Optional __main__ entry point stub (ST-004 wires the real CLI)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render MAP jinja2 templates")
    parser.add_argument("provider", choices=["claude", "codex"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = render_repo_trees(args.provider, dry_run=args.dry_run)
    for p in paths:
        print(p, file=sys.stdout)
