"""Tests for template_renderer.py — ST-001.

Uses tiny in-test fixture dirs (tmp_path) — does NOT depend on a real
templates_src tree.
"""

from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.delivery.template_renderer import (
    assert_no_stray_delimiters,
    get_environment,
    render_tree,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fixture(
    templates_src: Path,
    rel_path: str,
    content: str,
    executable: bool = False,
) -> Path:
    """Write a .jinja fixture under *templates_src* and return its path."""
    p = templates_src / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    if executable:
        import stat
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


# ---------------------------------------------------------------------------
# VC1 – Environment delimiters
# ---------------------------------------------------------------------------


class TestGetEnvironment:
    def test_vc1_block_delimiters(self) -> None:
        env = get_environment()
        assert env.block_start_string == "[%"
        assert env.block_end_string == "%]"

    def test_vc1_variable_delimiters(self) -> None:
        env = get_environment()
        assert env.variable_start_string == "<%"
        assert env.variable_end_string == "%>"

    def test_vc1_comment_delimiters(self) -> None:
        env = get_environment()
        assert env.comment_start_string == "[#"
        assert env.comment_end_string == "#]"

    def test_vc1_keep_trailing_newline(self) -> None:
        env = get_environment()
        assert env.keep_trailing_newline is True

    def test_vc1_autoescape_false(self) -> None:
        env = get_environment()
        assert env.autoescape is False

    def test_passthrough_handlebars(self) -> None:
        """Handlebars {{ }} must pass through verbatim."""
        env = get_environment()
        tmpl = env.from_string("{{ name }} and [[ bash ]] and Callable[[str], int]")
        result = tmpl.render(PROVIDER="claude")
        assert result == "{{ name }} and [[ bash ]] and Callable[[str], int]"

    def test_passthrough_bash_double_brackets(self) -> None:
        """Bash [[ ]] must pass through verbatim."""
        env = get_environment()
        tmpl = env.from_string("[[ -f file ]] && echo yes")
        result = tmpl.render(PROVIDER="claude")
        assert result == "[[ -f file ]] && echo yes"

    def test_passthrough_python_type_hints(self) -> None:
        """Python Callable[[...]] type hints must pass through verbatim."""
        env = get_environment()
        tmpl = env.from_string("def f(cb: Callable[[int, str], bool]) -> None: ...")
        result = tmpl.render(PROVIDER="claude")
        assert result == "def f(cb: Callable[[int, str], bool]) -> None: ..."

    def test_custom_delimiters_render(self) -> None:
        """Custom delimiters DO expand MAP variables."""
        env = get_environment()
        tmpl = env.from_string("provider=<% PROVIDER %>")
        result = tmpl.render(PROVIDER="codex")
        assert result == "provider=codex"


# ---------------------------------------------------------------------------
# assert_no_stray_delimiters
# ---------------------------------------------------------------------------


class TestAssertNoStrayDelimiters:
    def test_clean_text_passes(self) -> None:
        # should not raise
        assert_no_stray_delimiters("Hello, {{ world }}! [[ bash ]]")

    def test_stray_block_token_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match=r"\[%"):
            assert_no_stray_delimiters("some [% leftover %] text")

    def test_stray_variable_token_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match=r"<%"):
            assert_no_stray_delimiters("content <% PROVIDER %> here")

    def test_stray_comment_token_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match=r"\[#"):
            assert_no_stray_delimiters("text [# comment #] here")

    def test_empty_string_passes(self) -> None:
        assert_no_stray_delimiters("")


# ---------------------------------------------------------------------------
# VC4 – Lazy import (subprocess test)
# ---------------------------------------------------------------------------


class TestLazyImport:
    def test_vc4_jinja2_not_in_modules_after_import(self) -> None:
        """jinja2 must NOT appear in sys.modules after bare module import."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import mapify_cli.delivery.template_renderer; "
                    "assert 'jinja2' not in sys.modules, "
                    "'jinja2 was imported at module load time'"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Lazy-import assertion failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_vc4_jinja2_in_modules_after_get_environment(self) -> None:
        """After calling get_environment(), jinja2 MUST be in sys.modules."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import mapify_cli.delivery.template_renderer as m; "
                    "m.get_environment(); "
                    "assert 'jinja2' in sys.modules, "
                    "'jinja2 not loaded after get_environment()'"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Post-get_environment assertion failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# VC2 – render_tree writes, hooks last
# ---------------------------------------------------------------------------


class TestRenderTree:
    def test_vc2_basic_render_creates_output(self, tmp_path: Path) -> None:
        """render_tree produces a rendered file at the dest path."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        _make_fixture(templates_src, "hello.txt.jinja", "Hello <% PROVIDER %>!\n")

        written = render_tree(
            "claude",
            templates_src_root=templates_src,
            dest_root=dest_root,
        )

        assert len(written) == 1
        assert (dest_root / "hello.txt").read_text() == "Hello claude!\n"

    def test_vc2_provider_context_substituted(self, tmp_path: Path) -> None:
        """PROVIDER variable is substituted in output."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        _make_fixture(templates_src, "p.txt.jinja", "<% PROVIDER %>")

        render_tree("codex", templates_src_root=templates_src, dest_root=dest_root)
        assert (dest_root / "p.txt").read_text() == "codex"

    def test_vc2_hooks_written_last(self, tmp_path: Path) -> None:
        """Paths under .claude/hooks/ must be written AFTER non-hook paths."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        # Non-hook template
        _make_fixture(templates_src, "README.md.jinja", "# Readme\n")
        # Hook template
        _make_fixture(
            templates_src,
            ".claude/hooks/my-hook.py.jinja",
            "# hook for <% PROVIDER %>\n",
        )
        # Another non-hook
        _make_fixture(templates_src, "config.json.jinja", '{"p": "<% PROVIDER %>"}\n')

        written = render_tree(
            "claude",
            templates_src_root=templates_src,
            dest_root=dest_root,
        )

        # Find the hook among written paths
        hook_indices = [
            i for i, p in enumerate(written) if ".claude" in str(p) and "hooks" in str(p)
        ]
        non_hook_indices = [
            i for i, p in enumerate(written) if not (".claude" in str(p) and "hooks" in str(p))
        ]

        assert hook_indices, "No hook path found in written list"
        assert non_hook_indices, "No non-hook path found in written list"

        # Every hook index must come AFTER every non-hook index
        assert max(non_hook_indices) < min(hook_indices), (
            f"Hook paths not last! hooks at {hook_indices}, non-hooks at {non_hook_indices}\n"
            f"Written order: {[str(p) for p in written]}"
        )

    def test_vc2_dry_run_does_not_write_live(self, tmp_path: Path) -> None:
        """dry_run=True must not write any live files."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        _make_fixture(templates_src, "file.txt.jinja", "content\n")

        written = render_tree(
            "claude",
            dry_run=True,
            templates_src_root=templates_src,
            dest_root=dest_root,
        )

        assert written == []
        assert not (dest_root / "file.txt").exists()

    def test_vc2_byte_parity_filecmp(self, tmp_path: Path) -> None:
        """Written file must be byte-identical to the expected rendered content."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        content = "PROVIDER=<% PROVIDER %>\nextra line\n"
        _make_fixture(templates_src, "cfg.txt.jinja", content)

        render_tree("claude", templates_src_root=templates_src, dest_root=dest_root)

        dest_file = dest_root / "cfg.txt"
        # Write expected file for comparison
        expected = tmp_path / "expected.txt"
        expected.write_text("PROVIDER=claude\nextra line\n", encoding="utf-8")

        assert filecmp.cmp(dest_file, expected, shallow=False), (
            f"Byte-parity failed.\nExpected: {expected.read_bytes()!r}\n"
            f"Got: {dest_file.read_bytes()!r}"
        )

    def test_vc2_nested_dirs_created(self, tmp_path: Path) -> None:
        """Nested destination directories are created automatically."""
        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        _make_fixture(templates_src, "a/b/c/file.txt.jinja", "deep\n")

        render_tree("claude", templates_src_root=templates_src, dest_root=dest_root)

        assert (dest_root / "a" / "b" / "c" / "file.txt").read_text() == "deep\n"

    def test_missing_templates_src_raises(self, tmp_path: Path) -> None:
        """RuntimeError if templates_src_root does not exist."""
        import pytest
        with pytest.raises(RuntimeError, match="templates_src root not found"):
            render_tree(
                "claude",
                templates_src_root=tmp_path / "nonexistent",
                dest_root=tmp_path / "dest",
            )


# ---------------------------------------------------------------------------
# VC3 – Broken template does NOT mutate live .claude/hooks/
# ---------------------------------------------------------------------------


class TestBrokenTemplateAbort:
    def test_vc3_broken_template_raises_without_mutating_hooks(
        self, tmp_path: Path
    ) -> None:
        """A broken template must raise; pre-seeded live hooks must be unchanged."""
        import pytest

        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        # Pre-seed a live hook file that must remain untouched
        hook_dir = dest_root / ".claude" / "hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        sentinel = hook_dir / "existing-hook.py"
        sentinel_content = b"# original hook content\n"
        sentinel.write_bytes(sentinel_content)

        # A valid non-hook template (renders fine)
        _make_fixture(templates_src, "readme.md.jinja", "# readme\n")

        # A broken template (invalid syntax) under .claude/hooks/
        _make_fixture(
            templates_src,
            ".claude/hooks/broken.py.jinja",
            "[% if %]",  # invalid Jinja2 syntax
        )

        with pytest.raises(Exception):
            render_tree(
                "claude",
                templates_src_root=templates_src,
                dest_root=dest_root,
            )

        # The pre-seeded hook must be byte-unchanged
        assert sentinel.read_bytes() == sentinel_content, (
            "Live hook was mutated despite broken template!"
        )

    def test_vc3_stray_delimiter_raises_without_mutating_hooks(
        self, tmp_path: Path
    ) -> None:
        """A template that renders stray delimiters must raise before hooks are written."""
        import pytest

        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        # Pre-seed live hook
        hook_dir = dest_root / ".claude" / "hooks"
        hook_dir.mkdir(parents=True, exist_ok=True)
        sentinel = hook_dir / "guard.py"
        sentinel_content = b"# untouched\n"
        sentinel.write_bytes(sentinel_content)

        # Template that produces stray delimiter in output:
        # use a Jinja2 variable to emit the literal "[%" token so the
        # template PARSES and RENDERS successfully, but the rendered
        # output contains the stray token that assert_no_stray_delimiters catches.
        _make_fixture(
            templates_src,
            "bad.txt.jinja",
            "<% '[' + '%' %> leftover\n",
        )

        with pytest.raises(ValueError, match=r"\[%"):
            render_tree(
                "claude",
                templates_src_root=templates_src,
                dest_root=dest_root,
            )

        # Hook must be byte-unchanged
        assert sentinel.read_bytes() == sentinel_content

    def test_vc3_new_hook_not_created_on_broken_template(
        self, tmp_path: Path
    ) -> None:
        """A new hook template must NOT be created if any template raises."""
        import pytest

        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        # Broken non-hook template
        _make_fixture(templates_src, "broken.txt.jinja", "[% bad syntax")

        # Hook template that would have been written
        _make_fixture(
            templates_src,
            ".claude/hooks/new-hook.py.jinja",
            "# new hook\n",
        )

        with pytest.raises(Exception):
            render_tree(
                "claude",
                templates_src_root=templates_src,
                dest_root=dest_root,
            )

        assert not (dest_root / ".claude" / "hooks" / "new-hook.py").exists(), (
            "Hook was created despite broken template!"
        )
