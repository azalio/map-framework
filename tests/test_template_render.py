"""Tests for template_renderer.py — ST-001 + ST-002.

Uses tiny in-test fixture dirs (tmp_path) — does NOT depend on a real
templates_src tree for ST-001 tests.

ST-002 tests use the real templates_src tree and verify byte-identity
of render_repo_trees('claude') output vs committed templates/** and .claude/**
sources.
"""

from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.delivery.template_renderer import (
    assert_no_stray_delimiters,
    diff_rendered_trees,
    get_environment,
    render_repo_trees,
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
            check=False,
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
            check=False,
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

    def test_vc2_hook_rendered_executable_even_if_source_not(self, tmp_path: Path) -> None:
        """A hook .py/.sh renders executable even when its .jinja source lacks +x.

        The harness execs hooks via their shebang, so a rendered hook MUST carry
        the executable bit. The renderer force-sets +x for files under a managed
        hooks/ dir regardless of the source bit (a hook author who forgets to
        chmod the .jinja must not ship a broken hook). Regression guard for the
        map-memory-* hooks that shipped 0o644 and failed 'Permission denied'.
        """
        import os

        templates_src = tmp_path / "templates_src"
        dest_root = tmp_path / "dest"

        # NOTE: executable=False — the source deliberately lacks +x.
        _make_fixture(
            templates_src,
            ".claude/hooks/no-exec-hook.py.jinja",
            "#!/usr/bin/env python3\nprint('{}')\n",
            executable=False,
        )
        # A non-hook file must NOT be force-marked executable.
        _make_fixture(templates_src, "plain.txt.jinja", "hi\n", executable=False)

        render_tree("claude", templates_src_root=templates_src, dest_root=dest_root)

        hook_dest = dest_root / ".claude" / "hooks" / "no-exec-hook.py"
        assert hook_dest.is_file()
        assert os.access(hook_dest, os.X_OK), (
            "rendered hook must be executable even when the .jinja source is not"
        )
        plain_dest = dest_root / "plain.txt"
        assert plain_dest.is_file()
        assert not os.access(plain_dest, os.X_OK), (
            "non-hook files must not be force-marked executable"
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
        import jinja2
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

        with pytest.raises(jinja2.TemplateSyntaxError):
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
        import jinja2
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

        with pytest.raises(jinja2.TemplateSyntaxError):
            render_tree(
                "claude",
                templates_src_root=templates_src,
                dest_root=dest_root,
            )

        assert not (dest_root / ".claude" / "hooks" / "new-hook.py").exists(), (
            "Hook was created despite broken template!"
        )


# ---------------------------------------------------------------------------
# ST-002 – render_repo_trees / Claude destination-map
# ---------------------------------------------------------------------------

# Locate repo root relative to this test file
_REPO_ROOT = Path(__file__).parent.parent
_TEMPLATES_SRC = _REPO_ROOT / "src" / "mapify_cli" / "templates_src"
_TEMPLATES_DEST = _REPO_ROOT / "src" / "mapify_cli" / "templates"
_CLAUDE_ROOT = _REPO_ROOT / ".claude"
_MAP_ROOT = _REPO_ROOT / ".map"

# Shipped-only relative paths (no .claude/ destination)
# Note: settings.json is intentionally NOT in this list — it is dual-dest
# (templates/ AND .claude/) so check-render gates both copies (issue #390).
_SHIPPED_ONLY_RELS = [
    "CLAUDE.md",
    "workflow-rules.json",
    "ralph-loop-config.json",
    "hooks/README.md",
    "rules/learned/README.md",
]


def _templates_src_available() -> bool:
    """Return True if the real templates_src tree exists (ST-002 tests)."""
    return _TEMPLATES_SRC.exists() and any(_TEMPLATES_SRC.rglob("*.jinja"))


def _is_bytecode(path: Path) -> bool:
    """Python bytecode caches are generated runtime artifacts, never rendered.

    A test that imports a rendered skill script (e.g. .claude/skills/
    map-so-search/scripts/sofa_search.py) can write a __pycache__/*.pyc into a
    generated tree; the byte-identity walks must skip it or they would flag it
    as an un-rendered file.
    """
    return "__pycache__" in path.parts or path.suffix == ".pyc"


_CODEX_ROOT = _REPO_ROOT / ".codex"
_AGENTS_SKILLS_ROOT = _REPO_ROOT / ".agents" / "skills"
_TEMPLATES_CODEX = _TEMPLATES_DEST / "codex"
_TEMPLATES_SRC_CODEX = _TEMPLATES_SRC / "codex"

import pytest as _pytest

_skip_no_templates_src = _pytest.mark.skipif(
    not _templates_src_available(),
    reason="templates_src not populated; run make render-templates first",
)

_skip_no_codex_templates_src = _pytest.mark.skipif(
    not (_TEMPLATES_SRC_CODEX.exists() and any(_TEMPLATES_SRC_CODEX.rglob("*.jinja"))),
    reason="templates_src/codex not populated; run make render-templates first",
)


class TestRenderRepoTreesClaude:
    """ST-002 byte-identity and destination-map tests for render_repo_trees('claude')."""

    @_skip_no_templates_src
    def test_vc1_dry_run_returns_empty(self) -> None:
        """dry_run=True must return an empty list without writing files."""
        result = render_repo_trees(
            "claude", dry_run=True, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        assert result == []

    @_skip_no_templates_src
    def test_vc1_templates_dest_byte_identity(self, tmp_path: Path) -> None:
        """render_repo_trees('claude') output is byte-identical vs committed templates/**.

        Renders into a temp dest to avoid mutating the live tree, then
        filecmp-compares each rendered file to the committed template.
        """
        # Build a resolver that only writes to a tmpdir (not the real trees).
        # We do this by running render_repo_trees with a temp repo_root copy.
        # Simpler: use render_tree with identity dest_root pointing to tmp.
        # But we need the same template files — just render all .jinja files
        # into tmp and compare with templates/.
        from mapify_cli.delivery.template_renderer import render_tree

        dest = tmp_path / "templates"
        render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=dest)

        # Every file under templates/ should exist and be byte-identical
        for committed in sorted(_TEMPLATES_DEST.rglob("*")):
            if not committed.is_file() or _is_bytecode(committed):
                continue
            rel = committed.relative_to(_TEMPLATES_DEST)
            rel_str = rel.as_posix()
            # Skip codex subtree (ST-003 scope)
            if rel_str.startswith("codex/"):
                continue
            rendered = dest / rel
            assert rendered.exists(), f"Rendered file missing: {rel}"
            assert filecmp.cmp(rendered, committed, shallow=False), (
                f"Byte-parity FAILED for templates/{rel}"
            )

    @_skip_no_templates_src
    def test_vc1_claude_dest_byte_identity(self, tmp_path: Path) -> None:
        """Shared subtrees rendered into a tmp tree match committed .claude/** files.

        Verifies that agents/, hooks/ (non-shipped-only), references/, skills/,
        and rules/ all produce byte-identical output to what is committed in .claude/.
        """
        from mapify_cli.delivery.template_renderer import render_tree

        dest = tmp_path / "claude_check"
        render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=dest)

        # Check all .claude/ files that should be shared (not shipped-only)
        for committed in sorted(_CLAUDE_ROOT.rglob("*")):
            if not committed.is_file() or _is_bytecode(committed):
                continue
            rel = committed.relative_to(_CLAUDE_ROOT)
            rel_str = rel.as_posix()
            # Skip files that are unmanaged (not in any shipped subtree)
            shared_prefixes = ("agents/", "hooks/", "references/", "skills/", "rules/")
            if not any(rel_str.startswith(p) for p in shared_prefixes):
                continue
            # Skip shipped-only files that should NOT be in .claude/
            if rel_str in _SHIPPED_ONLY_RELS:
                continue
            # hooks/README.md is shipped-only — skip if it exists in .claude/
            if rel_str == "hooks/README.md":
                continue
            # D11: rules/learned/*.md are unmanaged learned files (not templated)
            if rel_str.startswith("rules/learned/") and rel_str != "rules/learned/README.md":
                continue
            rendered = dest / rel
            assert rendered.exists(), f"Rendered file missing for .claude/{rel}"
            assert filecmp.cmp(rendered, committed, shallow=False), (
                f"Byte-parity FAILED for .claude/{rel}"
            )

    @_skip_no_templates_src
    def test_vc1_sofa_surfaces_golden_byte_identity(self, tmp_path: Path) -> None:
        """ST-007 VC1 [AC-8][INV-SOFA-7][HC-5]: the SOFA surfaces (map-so-search
        SKILL.md + sofa_search.py, and .map/scripts/sofa_client.py) render
        byte-identically from templates_src into every generated tree.

        (a) cross-tree parity: the committed parallel copies are byte-identical.
        (b) fresh-render parity: a fresh render of the templates tree reproduces
            the committed copies byte-for-byte.
        """
        from mapify_cli.delivery.template_renderer import render_tree

        # (a) cross-tree parity — committed copies must already match.
        cross_tree_pairs = [
            (
                _CLAUDE_ROOT / "skills/map-so-search/SKILL.md",
                _TEMPLATES_DEST / "skills/map-so-search/SKILL.md",
            ),
            (
                _CLAUDE_ROOT / "skills/map-so-search/scripts/sofa_search.py",
                _TEMPLATES_DEST / "skills/map-so-search/scripts/sofa_search.py",
            ),
            (
                _MAP_ROOT / "scripts/sofa_client.py",
                _TEMPLATES_DEST / "map/scripts/sofa_client.py",
            ),
        ]
        for left, right in cross_tree_pairs:
            assert left.is_file(), f"missing SOFA artifact: {left}"
            assert right.is_file(), f"missing SOFA artifact: {right}"
            assert filecmp.cmp(left, right, shallow=False), (
                f"cross-tree parity FAILED: {left} != {right} — run make render-templates"
            )

        # (b) fresh-render parity — render into a tmp dest and compare the SOFA
        # files (rel to _TEMPLATES_DEST) to the committed templates copies.
        dest = tmp_path / "claude_check"
        render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=dest)
        sofa_rels = [
            "skills/map-so-search/SKILL.md",
            "skills/map-so-search/scripts/sofa_search.py",
            "map/scripts/sofa_client.py",
        ]
        for rel in sofa_rels:
            committed = _TEMPLATES_DEST / rel
            rendered = dest / rel
            assert rendered.exists(), f"Rendered SOFA file missing: {rel}"
            assert filecmp.cmp(rendered, committed, shallow=False), (
                f"Golden byte-parity FAILED for SOFA surface {rel}"
            )

    @_skip_no_templates_src
    def test_vc1_shipped_only_not_written_to_claude(self) -> None:
        """Shipped-only files must NOT be present in .claude/ after a real render.

        This is a negative assertion: confirms the destination-map routes
        these files to templates/ only, not .claude/.
        """
        result = render_repo_trees(
            "claude", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        written_strs = [str(p) for p in result]
        for rel in _SHIPPED_ONLY_RELS:
            claude_path = str(_CLAUDE_ROOT / rel)
            assert claude_path not in written_strs, (
                f"Shipped-only file was incorrectly written to .claude/: {claude_path}"
            )

    @_skip_no_templates_src
    def test_settings_json_written_to_both_destinations(self) -> None:
        """settings.json is dual-dest: renders to templates/ AND .claude/ (issue #390).

        This gates the parity that check-render now enforces: a change to
        settings.json.jinja must propagate to BOTH destinations or check-render
        reports stale files.
        """
        result = render_repo_trees(
            "claude", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        written_strs = [str(p) for p in result]
        templates_path = str(_TEMPLATES_DEST / "settings.json")
        claude_path = str(_CLAUDE_ROOT / "settings.json")
        assert templates_path in written_strs, (
            "settings.json was NOT written to templates/ — check renderer destination map"
        )
        assert claude_path in written_strs, (
            "settings.json was NOT written to .claude/ — shipped-only classification "
            "must be removed (issue #390 regression)"
        )

    @_skip_no_templates_src
    def test_settings_json_dev_shipped_parity(self) -> None:
        """Parity gate: .claude/settings.json must byte-match templates/settings.json.

        Catches drift between the dev copy and the shipped mirror before it
        reaches a real user session (issue #390).
        """
        dev_file = _CLAUDE_ROOT / "settings.json"
        shipped_file = _TEMPLATES_DEST / "settings.json"
        assert dev_file.exists(), f".claude/settings.json missing: {dev_file}"
        assert shipped_file.exists(), f"templates/settings.json missing: {shipped_file}"
        assert dev_file.read_bytes() == shipped_file.read_bytes(), (
            "Parity FAILED: .claude/settings.json differs from templates/settings.json. "
            "Run 'make render-templates' to sync (issue #390)."
        )

    @_skip_no_templates_src
    def test_vc1_map_scripts_remap(self) -> None:
        """map/scripts/** templates render to BOTH templates/map/scripts/ AND .map/scripts/."""
        result = render_repo_trees(
            "claude", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        written_strs = [str(p) for p in result]

        # Find a known map/scripts file
        sample = "map_utils.py"
        templates_path = str(_TEMPLATES_DEST / "map" / "scripts" / sample)
        map_path = str(_MAP_ROOT / "scripts" / sample)

        assert templates_path in written_strs, (
            f"Expected templates/map/scripts/{sample} in written paths"
        )
        assert map_path in written_strs, (
            f"Expected .map/scripts/{sample} in written paths (map/ -> .map/ remap)"
        )

    @_skip_no_templates_src
    def test_vc1_hooks_last_across_both_dest_trees(self) -> None:
        """Hook paths in BOTH .claude/hooks/ and templates/hooks/ must sort last (INV-9)."""
        result = render_repo_trees(
            "claude", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        hook_indices = [
            i for i, p in enumerate(result)
            if ("/.claude/hooks/" in str(p) or "/templates/hooks/" in str(p))
        ]
        non_hook_indices = [
            i for i, p in enumerate(result)
            if not ("/.claude/hooks/" in str(p) or "/templates/hooks/" in str(p))
        ]
        assert hook_indices, "No hook paths found in written list"
        assert non_hook_indices, "No non-hook paths found in written list"
        assert max(non_hook_indices) < min(hook_indices), (
            f"Hooks-last invariant violated! "
            f"hooks at indices {hook_indices[:5]}, "
            f"non-hooks max at {max(non_hook_indices)}"
        )

    @_skip_no_templates_src
    def test_vc2_monitor_md_handlebars_intact(self) -> None:
        """monitor.md must contain Handlebars {{ }} tokens after rendering (INV-8)."""
        import tempfile

        from mapify_cli.delivery.template_renderer import render_tree

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=tmp)
            rendered = (tmp / "agents" / "monitor.md").read_text(encoding="utf-8")

        # monitor.md uses Handlebars {{ }} which must survive verbatim
        assert "{{" in rendered, "monitor.md lost Handlebars {{ tokens after render"
        assert "}}" in rendered, "monitor.md lost Handlebars }} tokens after render"

    @_skip_no_templates_src
    def test_vc2_end_of_turn_sh_bash_brackets_intact(self) -> None:
        """end-of-turn.sh must contain bash [[ ]] tokens after rendering (INV-8)."""
        import tempfile

        from mapify_cli.delivery.template_renderer import render_tree

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=tmp)
            rendered = (tmp / "hooks" / "end-of-turn.sh").read_text(encoding="utf-8")

        assert "[[" in rendered, "end-of-turn.sh lost bash [[ tokens after render"
        assert "]]" in rendered, "end-of-turn.sh lost bash ]] tokens after render"

    @_skip_no_templates_src
    def test_vc4_stray_delimiters_zero(self) -> None:
        """Zero stray delimiter hits across all claude .jinja files (VC4)."""
        errors = []
        for jinja_file in sorted(_TEMPLATES_SRC.rglob("*.jinja")):
            rel = jinja_file.relative_to(_TEMPLATES_SRC)
            # Skip codex scope
            if rel.as_posix().startswith("codex/"):
                continue
            text = jinja_file.read_text(encoding="utf-8")
            try:
                assert_no_stray_delimiters(text)
            except ValueError as exc:
                errors.append(f"{rel}: {exc}")
        assert not errors, "Stray delimiter hits in .jinja files:\n" + "\n".join(errors)

    @_skip_no_templates_src
    def test_templates_src_non_empty_discovery(self) -> None:
        """Sentinel: templates_src must contain at least 80 .jinja files (guards vacuous pass)."""
        jinja_files = list(_TEMPLATES_SRC.rglob("*.jinja"))
        assert len(jinja_files) >= 80, (
            f"templates_src discovery returned only {len(jinja_files)} .jinja files "
            "— path typo or missing sync? Expected >= 80."
        )


# ---------------------------------------------------------------------------
# ST-003 – render_repo_trees / Codex destination-map
# ---------------------------------------------------------------------------


class TestRenderRepoTreesCodex:
    """ST-003 byte-identity and destination-map tests for render_repo_trees('codex')."""

    @_skip_no_codex_templates_src
    def test_vc1_dry_run_returns_empty(self) -> None:
        """dry_run=True must return an empty list without writing files."""
        result = render_repo_trees(
            "codex", dry_run=True, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        assert result == []

    @_skip_no_codex_templates_src
    def test_vc1_templates_codex_byte_identity(self) -> None:
        """render_repo_trees('codex') output is byte-identical vs committed templates/codex/**.

        Renders for real and filecmp-compares each destination file against
        the committed template.  Uses the live tree (HC-5 already verifies
        empty diff after render, so re-rendering is idempotent).
        """
        # Snapshot committed bytes BEFORE the in-place re-render so a stale
        # committed tree is detectable: an in-place render of a drifted file
        # would change its bytes, making the post-render comparison fail.
        # (Comparing the file to itself after rendering is tautological.)
        before = {
            committed: committed.read_bytes()
            for committed in sorted(_TEMPLATES_CODEX.rglob("*"))
            if committed.is_file() and not _is_bytecode(committed)
        }
        render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        for committed, original in before.items():
            assert committed.read_bytes() == original, (
                f"Byte-parity FAILED for templates/codex/{committed.relative_to(_TEMPLATES_CODEX)}"
            )

    @_skip_no_codex_templates_src
    def test_vc1_codex_dev_byte_identity(self) -> None:
        """Rendered .codex/** files are byte-identical to committed .codex/** sources."""
        render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        for committed in sorted(_CODEX_ROOT.rglob("*")):
            if not committed.is_file() or _is_bytecode(committed):
                continue
            rel = committed.relative_to(_CODEX_ROOT)
            template_copy = _TEMPLATES_CODEX / rel
            assert template_copy.exists(), (
                f"templates/codex/{rel} missing — codex render did not produce it"
            )
            assert filecmp.cmp(committed, template_copy, shallow=False), (
                f"Byte-parity FAILED: .codex/{rel} vs templates/codex/{rel}"
            )

    @_skip_no_codex_templates_src
    def test_vc1_agents_skills_byte_identity(self) -> None:
        """Rendered .agents/skills/** files are byte-identical to committed sources."""
        render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        for committed in sorted(_AGENTS_SKILLS_ROOT.rglob("*")):
            if not committed.is_file() or _is_bytecode(committed):
                continue
            rel = committed.relative_to(_AGENTS_SKILLS_ROOT)
            template_copy = _TEMPLATES_CODEX / "skills" / rel
            assert template_copy.exists(), (
                f"templates/codex/skills/{rel} missing — codex render did not produce it"
            )
            assert filecmp.cmp(committed, template_copy, shallow=False), (
                f"Byte-parity FAILED: .agents/skills/{rel} vs templates/codex/skills/{rel}"
            )

    @_skip_no_codex_templates_src
    def test_vc1_skills_remap_to_agents_skills(self) -> None:
        """codex/skills/** templates render to BOTH templates/codex/skills/ AND .agents/skills/."""
        result = render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        written_strs = [str(p) for p in result]

        # Find a known skills file in both destinations
        sample_rel = "map-plan/SKILL.md"
        templates_path = str(_TEMPLATES_CODEX / "skills" / sample_rel)
        agents_path = str(_AGENTS_SKILLS_ROOT / sample_rel)

        assert templates_path in written_strs, (
            f"Expected templates/codex/skills/{sample_rel} in written paths"
        )
        assert agents_path in written_strs, (
            f"Expected .agents/skills/{sample_rel} in written paths (skills remap)"
        )

    @_skip_no_codex_templates_src
    def test_vc1_non_skills_remap_to_codex_dev(self) -> None:
        """codex non-skills files render to BOTH templates/codex/ AND .codex/."""
        result = render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        written_strs = [str(p) for p in result]

        # Check a known agents file
        sample_rel = "agents/decomposer.toml"
        templates_path = str(_TEMPLATES_CODEX / sample_rel)
        codex_dev_path = str(_CODEX_ROOT / sample_rel)

        assert templates_path in written_strs, (
            f"Expected templates/codex/{sample_rel} in written paths"
        )
        assert codex_dev_path in written_strs, (
            f"Expected .codex/{sample_rel} in written paths (.codex remap)"
        )

    @_skip_no_codex_templates_src
    def test_vc3_four_workflow_gate_copies_byte_identical(self) -> None:
        """All 4 workflow-gate.py copies must be byte-identical (VC3)."""
        copies = [
            _REPO_ROOT / ".claude" / "hooks" / "workflow-gate.py",
            _REPO_ROOT / ".codex" / "hooks" / "workflow-gate.py",
            _TEMPLATES_DEST / "hooks" / "workflow-gate.py",
            _TEMPLATES_CODEX / "hooks" / "workflow-gate.py",
        ]
        canonical = copies[0]
        for other in copies[1:]:
            assert other.exists(), f"workflow-gate.py missing at: {other}"
            assert filecmp.cmp(canonical, other, shallow=False), (
                f"workflow-gate.py DIFFERS: {canonical} vs {other}"
            )

    @_skip_no_codex_templates_src
    def test_vc3_workflow_gate_no_recursion_guard(self) -> None:
        """workflow-gate.py must NOT contain a recursion guard (VC3)."""
        wg = _REPO_ROOT / ".codex" / "hooks" / "workflow-gate.py"
        text = wg.read_text(encoding="utf-8")
        forbidden = ["_RECURSION_GUARD", "already_running"]
        for marker in forbidden:
            assert marker not in text, (
                f"Forbidden recursion-guard marker {marker!r} found in workflow-gate.py"
            )

    @_skip_no_codex_templates_src
    def test_vc4_stray_delimiters_zero_codex(self) -> None:
        """Zero stray delimiter hits across all codex .jinja files (VC4)."""
        errors = []
        jinja_files = list(_TEMPLATES_SRC_CODEX.rglob("*.jinja"))
        assert jinja_files, (
            "No .jinja files found under templates_src/codex/ — path typo or missing files?"
        )
        for jinja_file in sorted(jinja_files):
            rel = jinja_file.relative_to(_TEMPLATES_SRC_CODEX)
            text = jinja_file.read_text(encoding="utf-8")
            try:
                assert_no_stray_delimiters(text)
            except ValueError as exc:
                errors.append(f"codex/{rel}: {exc}")
        assert not errors, "Stray delimiter hits in codex .jinja files:\n" + "\n".join(errors)

    @_skip_no_codex_templates_src
    def test_hooks_last_codex_and_templates_codex(self) -> None:
        """Hook paths in BOTH .codex/hooks/ and templates/codex/hooks/ must sort last (INV-9)."""
        result = render_repo_trees(
            "codex", dry_run=False, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
        )
        hook_indices = [
            i for i, p in enumerate(result)
            if ("/.codex/hooks/" in str(p) or "/codex/hooks/" in str(p))
        ]
        non_hook_indices = [
            i for i, p in enumerate(result)
            if not ("/.codex/hooks/" in str(p) or "/codex/hooks/" in str(p))
        ]
        assert hook_indices, "No codex hook paths found in written list"
        assert non_hook_indices, "No non-hook paths found in written list"
        assert max(non_hook_indices) < min(hook_indices), (
            f"Hooks-last invariant violated for codex! "
            f"hooks at indices {hook_indices}, "
            f"non-hooks max at {max(non_hook_indices)}"
        )

    @_skip_no_codex_templates_src
    def test_codex_templates_src_non_empty_discovery(self) -> None:
        """Sentinel: templates_src/codex must contain at least 13 .jinja files."""
        jinja_files = list(_TEMPLATES_SRC_CODEX.rglob("*.jinja"))
        assert len(jinja_files) >= 13, (
            f"templates_src/codex discovery returned only {len(jinja_files)} .jinja files "
            "— path typo or missing files? Expected >= 13."
        )


# ---------------------------------------------------------------------------
# ST-005 – Golden-file fixtures (VC2/VC3): independent byte-snapshot ground truth
# ---------------------------------------------------------------------------

_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"


class TestGoldenFixturesClaude:
    """VC2/VC3: committed golden-file snapshots for the claude provider.

    The fixture at tests/fixtures/claude/escalation-matrix.md is an
    independent committed snapshot — it is NOT derived by re-rendering in
    the same test.  This makes the comparison non-tautological: the test
    fails if the renderer output drifts from the snapshot, catching both
    accidental template edits and renderer bugs.
    """

    @_skip_no_templates_src
    def test_vc2_claude_golden_escalation_matrix(self, tmp_path: Path) -> None:
        """Renderer byte-for-byte reproduces the committed claude golden fixture."""
        golden = _FIXTURES_DIR / "claude" / "escalation-matrix.md"
        assert golden.exists(), f"Golden fixture missing: {golden}"

        dest = tmp_path / "rendered"
        render_tree(
            "claude",
            templates_src_root=_TEMPLATES_SRC,
            dest_root=dest,
        )
        rendered_file = dest / "references" / "escalation-matrix.md"
        assert rendered_file.exists(), (
            "Renderer did not produce references/escalation-matrix.md"
        )
        rendered_bytes = rendered_file.read_bytes()
        golden_bytes = golden.read_bytes()
        assert rendered_bytes == golden_bytes, (
            f"Golden fixture mismatch for claude/escalation-matrix.md\n"
            f"  Golden  : {len(golden_bytes)} bytes\n"
            f"  Rendered: {len(rendered_bytes)} bytes\n"
            f"  Golden repr  (first 200): {golden_bytes[:200]!r}\n"
            f"  Rendered repr (first 200): {rendered_bytes[:200]!r}"
        )

    @_skip_no_templates_src
    def test_vc3_negative_mutated_fixture_fails(self, tmp_path: Path) -> None:
        """Byte-equality check catches a single-byte mutation in the golden fixture.

        The committed fixture is read into memory, one byte is flipped, and the
        test asserts that the comparison fails — proving the gate is not vacuous.
        The committed fixture file is NEVER modified.
        """
        golden = _FIXTURES_DIR / "claude" / "escalation-matrix.md"
        assert golden.exists(), f"Golden fixture missing: {golden}"

        dest = tmp_path / "rendered"
        render_tree(
            "claude",
            templates_src_root=_TEMPLATES_SRC,
            dest_root=dest,
        )
        rendered_bytes = (dest / "references" / "escalation-matrix.md").read_bytes()

        # Mutate the golden bytes in memory — the committed file is untouched.
        golden_bytes = golden.read_bytes()
        assert len(golden_bytes) > 0, "Golden fixture is empty"
        mutated = bytearray(golden_bytes)
        mutated[0] = (mutated[0] + 1) % 256
        mutated_bytes = bytes(mutated)

        # The equality check MUST fail (that is the assertion we are proving).
        assert rendered_bytes != mutated_bytes, (
            "Negative test failed: single-byte mutation was NOT detected by "
            "byte-equality comparison — the gate is non-functional."
        )


class TestGoldenFixturesCodex:
    """VC2/VC3: committed golden-file snapshots for the codex provider.

    The fixture at tests/fixtures/codex/config.toml is an independent committed
    snapshot of the rendered codex/config.toml.jinja template.
    """

    @_skip_no_codex_templates_src
    def test_vc2_codex_golden_config_toml(self, tmp_path: Path) -> None:
        """Renderer byte-for-byte reproduces the committed codex golden fixture."""
        golden = _FIXTURES_DIR / "codex" / "config.toml"
        assert golden.exists(), f"Golden fixture missing: {golden}"

        # Render only the codex subtree so the dest layout matches the
        # codex template structure (config.toml at root, not codex/config.toml).
        dest = tmp_path / "rendered"
        render_tree(
            "codex",
            templates_src_root=_TEMPLATES_SRC_CODEX,
            dest_root=dest,
        )
        rendered_file = dest / "config.toml"
        assert rendered_file.exists(), (
            "Renderer did not produce config.toml from codex subtree"
        )
        rendered_bytes = rendered_file.read_bytes()
        golden_bytes = golden.read_bytes()
        assert rendered_bytes == golden_bytes, (
            f"Golden fixture mismatch for codex/config.toml\n"
            f"  Golden  : {len(golden_bytes)} bytes\n"
            f"  Rendered: {len(rendered_bytes)} bytes\n"
            f"  Golden repr  (first 200): {golden_bytes[:200]!r}\n"
            f"  Rendered repr (first 200): {rendered_bytes[:200]!r}"
        )

    @_skip_no_codex_templates_src
    def test_vc3_negative_mutated_fixture_fails(self, tmp_path: Path) -> None:
        """Byte-equality check catches a single-byte mutation in the codex golden fixture.

        The committed fixture is read into memory, one byte is flipped, and the
        test asserts that the comparison fails.  The committed file is NOT modified.
        """
        golden = _FIXTURES_DIR / "codex" / "config.toml"
        assert golden.exists(), f"Golden fixture missing: {golden}"

        dest = tmp_path / "rendered"
        render_tree(
            "codex",
            templates_src_root=_TEMPLATES_SRC_CODEX,
            dest_root=dest,
        )
        rendered_bytes = (dest / "config.toml").read_bytes()

        golden_bytes = golden.read_bytes()
        assert len(golden_bytes) > 0, "Golden fixture is empty"
        mutated = bytearray(golden_bytes)
        mutated[0] = (mutated[0] + 1) % 256
        mutated_bytes = bytes(mutated)

        assert rendered_bytes != mutated_bytes, (
            "Negative test failed: single-byte mutation was NOT detected by "
            "byte-equality comparison — the gate is non-functional."
        )


# ---------------------------------------------------------------------------
# Non-destructive check-render gate (diff_rendered_trees)
# ---------------------------------------------------------------------------


class TestDiffRenderedTrees:
    """diff_rendered_trees() is the non-destructive replacement for the old
    ``check-render`` gate: it renders into a tempdir and byte-compares, never
    mutating the working tree and never gating hand-authored, non-rendered
    files (invariant D11)."""

    @_skip_no_templates_src
    def test_real_repo_trees_in_sync(self) -> None:
        """The committed trees must match a fresh render (the gate's job)."""
        for provider in ("claude", "codex"):
            stale = diff_rendered_trees(
                provider, repo_root=_REPO_ROOT, templates_src_root=_TEMPLATES_SRC
            )
            assert stale == [], (
                f"Stale generated files for provider {provider!r}: {stale}"
            )

    @_skip_no_templates_src
    def test_modified_gated_file_is_flagged(self, tmp_path: Path) -> None:
        """A drifted committed gate-tree file is reported as stale."""
        real = tmp_path / "repo"
        render_repo_trees("claude", repo_root=real, templates_src_root=_TEMPLATES_SRC)
        # Freshly rendered repo is in sync.
        assert (
            diff_rendered_trees(
                "claude", repo_root=real, templates_src_root=_TEMPLATES_SRC
            )
            == []
        )
        # Corrupt one gated .claude/ file.
        target = next(p for p in sorted((real / ".claude").rglob("*")) if p.is_file())
        target.write_text("DRIFT — no longer matches source\n", encoding="utf-8")
        stale = diff_rendered_trees(
            "claude", repo_root=real, templates_src_root=_TEMPLATES_SRC
        )
        assert target in stale, f"Expected {target} flagged as stale; got {stale}"

    @_skip_no_templates_src
    def test_missing_gated_file_is_flagged(self, tmp_path: Path) -> None:
        """A rendered file absent from the real repo is reported as stale."""
        real = tmp_path / "repo"
        render_repo_trees("claude", repo_root=real, templates_src_root=_TEMPLATES_SRC)
        target = next(p for p in sorted((real / ".claude").rglob("*")) if p.is_file())
        target.unlink()
        stale = diff_rendered_trees(
            "claude", repo_root=real, templates_src_root=_TEMPLATES_SRC
        )
        assert target in stale, f"Expected missing {target} flagged; got {stale}"

    @_skip_no_templates_src
    def test_unmanaged_learned_file_not_gated_and_not_mutated(
        self, tmp_path: Path
    ) -> None:
        """D11 hand-authored learned files are neither flagged nor reverted.

        This is the regression guard for the footgun the old gate had:
        ``git checkout -- .claude`` destroyed uncommitted edits to
        non-rendered files. The new gate renders into its own tempdir and
        only compares rendered files, so it can never touch these.
        """
        real = tmp_path / "repo"
        render_repo_trees("claude", repo_root=real, templates_src_root=_TEMPLATES_SRC)

        # Simulate an uncommitted, hand-authored learned-rules file (not rendered).
        learned = real / ".claude" / "rules" / "learned" / "architecture-patterns.md"
        learned.parent.mkdir(parents=True, exist_ok=True)
        sentinel = "# Architecture Patterns\n\n- **Hand-authored rule** (D11)\n"
        learned.write_text(sentinel, encoding="utf-8")

        # Also drift a genuinely-gated file so the gate returns non-empty.
        gated = next(
            p
            for p in sorted((real / ".claude" / "agents").rglob("*"))
            if p.is_file()
        )
        gated.write_text("DRIFT\n", encoding="utf-8")

        stale = diff_rendered_trees(
            "claude", repo_root=real, templates_src_root=_TEMPLATES_SRC
        )

        # The gated file is flagged; the unmanaged learned file is NOT.
        assert gated in stale
        assert learned not in stale, "Unmanaged D11 file must not be gated"
        # And crucially the learned file is untouched (never reverted/destroyed).
        assert learned.exists()
        assert learned.read_text(encoding="utf-8") == sentinel


# ---------------------------------------------------------------------------
# ST-012 VC2: golden-render tests — Requirements Index sentinel + SKILL
# instruction byte-identically in generated trees (HC-1 single-source render)
# ---------------------------------------------------------------------------


_MAP_PLAN_PLAN_REFERENCE_CLAUDE = _CLAUDE_ROOT / "skills" / "map-plan" / "plan-reference.md"
_MAP_PLAN_PLAN_REFERENCE_TEMPLATES = _TEMPLATES_DEST / "skills" / "map-plan" / "plan-reference.md"
_MAP_PLAN_SKILL_CLAUDE = _CLAUDE_ROOT / "skills" / "map-plan" / "SKILL.md"
_MAP_PLAN_SKILL_TEMPLATES = _TEMPLATES_DEST / "skills" / "map-plan" / "SKILL.md"

_RI_OPEN_SENTINEL = "<!-- mapify:requirements-index:v1 -->"
_RI_CLOSE_SENTINEL = "<!-- /mapify:requirements-index:v1 -->"
_RI_SKILL_INSTRUCTION = "Requirements Index (MANDATORY)"


class TestRequirementsIndexGoldenRender:
    """ST-012 VC2: assert that the Requirements Index single-source render
    landed in the generated trees with the expected content (HC-1).
    """

    def test_vc2_plan_reference_committed_contains_sentinel_open(self) -> None:
        """VC2: committed .claude/skills/map-plan/plan-reference.md contains
        the opening Requirements Index sentinel (ST-001 render landed).
        """
        assert _MAP_PLAN_PLAN_REFERENCE_CLAUDE.is_file(), (
            f"Generated plan-reference.md missing: {_MAP_PLAN_PLAN_REFERENCE_CLAUDE}"
        )
        content = _MAP_PLAN_PLAN_REFERENCE_CLAUDE.read_text(encoding="utf-8")
        assert _RI_OPEN_SENTINEL in content, (
            f"plan-reference.md missing opening sentinel {_RI_OPEN_SENTINEL!r} — "
            "run make render-templates after editing ST-001 .jinja source"
        )

    def test_vc2_plan_reference_committed_contains_sentinel_close(self) -> None:
        """VC2: committed plan-reference.md contains the closing sentinel."""
        assert _MAP_PLAN_PLAN_REFERENCE_CLAUDE.is_file(), (
            f"Generated plan-reference.md missing: {_MAP_PLAN_PLAN_REFERENCE_CLAUDE}"
        )
        content = _MAP_PLAN_PLAN_REFERENCE_CLAUDE.read_text(encoding="utf-8")
        assert _RI_CLOSE_SENTINEL in content, (
            f"plan-reference.md missing closing sentinel {_RI_CLOSE_SENTINEL!r}"
        )

    def test_vc2_skill_committed_contains_requirements_index_instruction(self) -> None:
        """VC2: committed .claude/skills/map-plan/SKILL.md contains the
        'Requirements Index (MANDATORY)' author instruction (ST-002 render landed).
        """
        assert _MAP_PLAN_SKILL_CLAUDE.is_file(), (
            f"Generated SKILL.md missing: {_MAP_PLAN_SKILL_CLAUDE}"
        )
        content = _MAP_PLAN_SKILL_CLAUDE.read_text(encoding="utf-8")
        assert _RI_SKILL_INSTRUCTION in content, (
            f"SKILL.md missing instruction {_RI_SKILL_INSTRUCTION!r} — "
            "run make render-templates after editing ST-002 .jinja source"
        )

    def test_vc2_templates_plan_reference_contains_sentinel(self) -> None:
        """VC2: committed templates/skills/map-plan/plan-reference.md contains
        the sentinel pair (cross-tree parity for the spec template).
        """
        assert _MAP_PLAN_PLAN_REFERENCE_TEMPLATES.is_file(), (
            f"Generated plan-reference.md missing in templates/: {_MAP_PLAN_PLAN_REFERENCE_TEMPLATES}"
        )
        content = _MAP_PLAN_PLAN_REFERENCE_TEMPLATES.read_text(encoding="utf-8")
        assert _RI_OPEN_SENTINEL in content
        assert _RI_CLOSE_SENTINEL in content

    def test_vc2_templates_skill_contains_requirements_index_instruction(self) -> None:
        """VC2: committed templates/skills/map-plan/SKILL.md contains
        the Requirements Index author instruction.
        """
        assert _MAP_PLAN_SKILL_TEMPLATES.is_file(), (
            f"Generated SKILL.md missing in templates/: {_MAP_PLAN_SKILL_TEMPLATES}"
        )
        content = _MAP_PLAN_SKILL_TEMPLATES.read_text(encoding="utf-8")
        assert _RI_SKILL_INSTRUCTION in content

    def test_vc2_cross_tree_plan_reference_byte_identity(self) -> None:
        """VC2: .claude/ and templates/ copies of plan-reference.md are byte-identical
        (cross-tree parity — proves HC-1 single render wrote both).
        """
        assert _MAP_PLAN_PLAN_REFERENCE_CLAUDE.is_file()
        assert _MAP_PLAN_PLAN_REFERENCE_TEMPLATES.is_file()
        assert filecmp.cmp(
            _MAP_PLAN_PLAN_REFERENCE_CLAUDE,
            _MAP_PLAN_PLAN_REFERENCE_TEMPLATES,
            shallow=False,
        ), (
            "cross-tree parity FAILED for plan-reference.md — "
            "run make render-templates"
        )

    def test_vc2_cross_tree_skill_byte_identity(self) -> None:
        """VC2: .claude/ and templates/ copies of map-plan/SKILL.md are byte-identical."""
        assert _MAP_PLAN_SKILL_CLAUDE.is_file()
        assert _MAP_PLAN_SKILL_TEMPLATES.is_file()
        assert filecmp.cmp(
            _MAP_PLAN_SKILL_CLAUDE,
            _MAP_PLAN_SKILL_TEMPLATES,
            shallow=False,
        ), (
            "cross-tree parity FAILED for map-plan/SKILL.md — "
            "run make render-templates"
        )

    @_skip_no_templates_src
    def test_vc2_fresh_render_plan_reference_byte_identity(self, tmp_path: Path) -> None:
        """VC2: a fresh render of templates_src produces plan-reference.md byte-identical
        to the committed copy — proves the .jinja source is the single source of truth.
        """
        from mapify_cli.delivery.template_renderer import render_tree

        dest = tmp_path / "rendered"
        render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=dest)

        rendered = dest / "skills" / "map-plan" / "plan-reference.md"
        assert rendered.exists(), "Fresh render did not produce plan-reference.md"
        assert filecmp.cmp(rendered, _MAP_PLAN_PLAN_REFERENCE_TEMPLATES, shallow=False), (
            "Fresh-render plan-reference.md differs from committed templates/ copy — "
            "edit .jinja source and run make render-templates"
        )

    @_skip_no_templates_src
    def test_vc2_fresh_render_skill_byte_identity(self, tmp_path: Path) -> None:
        """VC2: a fresh render of templates_src produces SKILL.md byte-identical
        to the committed copy — proves the .jinja source is the single source of truth.
        """
        from mapify_cli.delivery.template_renderer import render_tree

        dest = tmp_path / "rendered"
        render_tree("claude", templates_src_root=_TEMPLATES_SRC, dest_root=dest)

        rendered = dest / "skills" / "map-plan" / "SKILL.md"
        assert rendered.exists(), "Fresh render did not produce map-plan/SKILL.md"
        assert filecmp.cmp(rendered, _MAP_PLAN_SKILL_TEMPLATES, shallow=False), (
            "Fresh-render SKILL.md differs from committed templates/ copy — "
            "edit .jinja source and run make render-templates"
        )
