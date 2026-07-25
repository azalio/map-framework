"""
Guard tests for INV-6: the mapify init import chain must NOT load
template_renderer or jinja2 at import time.

All assertions run in a FRESH interpreter subprocess so that sys.modules
pollution from other tests in the same process cannot produce false-greens.

VC1 [AC-2/INV-7]: providers use plain-copy helpers, never render_tree/render_repo_trees.
VC2 [INV-6/AC-9]: importing the init entrypoint (mapify_cli and delivery chain) does
                  not load mapify_cli.delivery.template_renderer or jinja2.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run *code* in a fresh Python interpreter and return the result."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )


# ---------------------------------------------------------------------------
# VC2 — fresh-interpreter import-graph tests
# ---------------------------------------------------------------------------


def test_vc2_import_mapify_cli_top_level_does_not_load_template_renderer() -> None:
    """Importing the top-level mapify_cli package must NOT pull in template_renderer."""
    proc = _run_python(
        """
        import sys
        # Ensure the project src is on the path when invoked directly
        import importlib
        importlib.import_module('mapify_cli')

        bad_mods = [
            m for m in sys.modules
            if m == 'mapify_cli.delivery.template_renderer'
            or m.startswith('mapify_cli.delivery.template_renderer.')
        ]
        if bad_mods:
            raise AssertionError(
                f"INV-6 VIOLATED: importing mapify_cli loaded template_renderer. "
                f"Offending modules: {bad_mods}. "
                f"A transitive import has broken the lazy-load contract — "
                f"find the import and move it inside the function that needs it."
            )

        if 'jinja2' in sys.modules:
            raise AssertionError(
                "INV-6 VIOLATED: importing mapify_cli loaded jinja2. "
                "jinja2 must only be imported by template_renderer, not at init time. "
                "Find the eager import and move it inside the rendering function."
            )
        """
    )
    assert proc.returncode == 0, (
        f"Fresh-interpreter import-graph check failed.\n"
        f"stdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )


def test_vc2_import_delivery_chain_does_not_load_template_renderer() -> None:
    """
    Importing the full delivery chain (what mapify init actually uses) must NOT
    pull in template_renderer or jinja2.

    This imports the same symbols that __init__.py re-exports, which is the
    real dispatch chain for `mapify init` regardless of provider.
    """
    proc = _run_python(
        """
        import sys

        # Import every symbol that mapify_cli/__init__.py pulls from delivery.
        # This mirrors the actual init-time import chain so that a new transitive
        # import added to any of these modules is caught immediately.
        from mapify_cli.delivery import (
            create_task_decomposer_content,
            create_actor_content,
            create_monitor_content,
            create_predictor_content,
            create_evaluator_content,
            create_reflector_content,
            create_documentation_reviewer_content,
            create_agent_files,
            create_reference_files,
            create_command_files,
            create_skill_files,
            create_hook_files,
            create_config_files,
            create_commands_dir,
        )
        from mapify_cli.delivery.providers import ClaudeProvider, CodexProvider

        bad_mods = [
            m for m in sys.modules
            if m == 'mapify_cli.delivery.template_renderer'
            or m.startswith('mapify_cli.delivery.template_renderer.')
        ]
        if bad_mods:
            raise AssertionError(
                f"INV-6 VIOLATED: importing the delivery chain loaded template_renderer. "
                f"Offending modules: {bad_mods}. "
                f"A transitive import inside delivery.__init__ or providers.py has broken "
                f"the lazy-load contract. Move the import inside the rendering function."
            )

        if 'jinja2' in sys.modules:
            raise AssertionError(
                "INV-6 VIOLATED: importing the delivery chain loaded jinja2. "
                "jinja2 must not be imported at delivery-chain import time. "
                "Find the eager import and defer it."
            )
        """
    )
    assert proc.returncode == 0, (
        f"Fresh-interpreter delivery-chain import-graph check failed.\n"
        f"stdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )


def test_vc2_import_providers_does_not_load_template_renderer() -> None:
    """
    Importing providers.py specifically must NOT load template_renderer or jinja2.
    CodexProvider defers its create_codex_files import inside install(); this test
    guards against accidentally moving that import to module level.
    """
    proc = _run_python(
        """
        import sys
        from mapify_cli.delivery.providers import ClaudeProvider, CodexProvider

        bad_mods = [
            m for m in sys.modules
            if m == 'mapify_cli.delivery.template_renderer'
            or m.startswith('mapify_cli.delivery.template_renderer.')
        ]
        if bad_mods:
            raise AssertionError(
                f"INV-6 VIOLATED: importing providers loaded template_renderer. "
                f"Offending modules: {bad_mods}."
            )

        if 'jinja2' in sys.modules:
            raise AssertionError(
                "INV-6 VIOLATED: importing providers loaded jinja2. "
                "jinja2 must remain deferred."
            )
        """
    )
    assert proc.returncode == 0, (
        f"Fresh-interpreter providers import-graph check failed.\n"
        f"stdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )


# ---------------------------------------------------------------------------
# VC1 — source-scan: providers use copier helpers, NOT render functions
# ---------------------------------------------------------------------------


def _read_providers_source() -> str:
    """Return source text of providers.py for static inspection."""
    providers_path = (
        _REPO_ROOT / "src" / "mapify_cli" / "delivery" / "providers.py"
    )
    return providers_path.read_text(encoding="utf-8")


def test_vc1_providers_do_not_reference_render_tree() -> None:
    """ClaudeProvider and CodexProvider must not reference render_tree."""
    source = _read_providers_source()
    assert "render_tree" not in source, (
        "INV-7 VIOLATED: providers.py references render_tree. "
        "ClaudeProvider.install and CodexProvider.install must use plain-copy helpers "
        "(create_agent_files / create_codex_files), never template rendering. "
        "Remove the render_tree reference and replace with the appropriate copier."
    )


def test_vc1_providers_do_not_reference_render_repo_trees() -> None:
    """ClaudeProvider and CodexProvider must not reference render_repo_trees."""
    source = _read_providers_source()
    assert "render_repo_trees" not in source, (
        "INV-7 VIOLATED: providers.py references render_repo_trees. "
        "Provider install methods must use plain-copy helpers only. "
        "Remove the render_repo_trees reference."
    )


def test_vc1_providers_do_not_import_template_renderer() -> None:
    """providers.py must not import template_renderer at module or function level."""
    source = _read_providers_source()
    assert "template_renderer" not in source, (
        "INV-7/INV-6 VIOLATED: providers.py contains a reference to template_renderer. "
        "Providers must remain jinja2-free; rendering belongs in template_renderer.py only."
    )


def test_vc1_claude_provider_install_uses_copy_helpers() -> None:
    """ClaudeProvider.install must call create_agent_files (plain-copy helper)."""
    from mapify_cli.delivery.providers import ClaudeProvider

    source = inspect.getsource(ClaudeProvider.install)
    assert "create_agent_files" in source, (
        "AC-2 VIOLATED: ClaudeProvider.install does not call create_agent_files. "
        "The provider must delegate to plain-copy helpers, not template rendering."
    )


def test_vc1_codex_provider_install_uses_create_codex_files() -> None:
    """CodexProvider.install must call create_codex_files (plain-copy helper)."""
    from mapify_cli.delivery.providers import CodexProvider

    source = inspect.getsource(CodexProvider.install)
    assert "create_codex_files" in source, (
        "AC-2 VIOLATED: CodexProvider.install does not call create_codex_files. "
        "The provider must delegate to the codex plain-copy helper."
    )


# ---------------------------------------------------------------------------
# VC3 — jinja2 is still a runtime dep (regression guard)
# ---------------------------------------------------------------------------


def test_vc3_pyproject_lists_jinja2() -> None:
    """pyproject.toml must still declare jinja2 as a runtime dependency."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    assert "jinja2" in content.lower(), (
        "AC-9 VIOLATED: jinja2 is no longer listed in pyproject.toml. "
        "jinja2 is a runtime dependency used by template_renderer; do not remove it."
    )
