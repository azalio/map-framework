"""Tests for cache-friendly agent prompt layering (#231).

Covers two surfaces:
  * the runtime builders in the rendered `.map/scripts/map_step_runner.py`
    (`_render_review_prompt`, `_render_complexity_lens_prompt`,
    `build_review_prompts`, `_load_prompt_layering`);
  * the install-time `MapConfig` in `mapify_cli.config.project_config`.

The central invariant: in `stable_first` mode the stable role/contract sections
form a byte-identical PREFIX across same-role dispatches whose only difference is
the variable `<documents>` (bundle / preferences / diff). `docs_first` (the
default) must stay byte-identical to the historical envelope.

Note (#231 resolved): the byte-identical prefix was the *conjectured* precondition
for an automatic prefix-cache hit, but the layering choice was determined
cache-neutral at the Claude Code Task layer (the harness owns cache_control and
the stable/variable seam is mid-block). These tests pin the ordering/prefix
behavior — which still matters because `stable_first` changes token order and
therefore model attention — not a caching claim. See docs/ARCHITECTURE.md.
"""

import sys
from pathlib import Path

# Import the SHIPPED runner from the generated tree (same source the installer
# copies into target projects). Suppress bytecode so importing it does not drop
# a *.pyc into the generated tree that byte-identity render tests then flag.
sys.dont_write_bytecode = True
SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS_PATH))

import map_step_runner as m  # type: ignore[import-not-found]

_DOCS_MARKER = "\n\n<documents>"
_STABLE_TAGS = ("<task>", "<workflow_policy>", "<instructions>", "</expected_output>")


def _monitor_spec() -> dict:
    return m.REVIEW_PROMPT_SPECS["monitor"]


def _review(layering: str, bundle: str, prefs: str, diff: str) -> str:
    return m._render_review_prompt(
        _monitor_spec(), bundle, prefs, diff, layering=layering
    )


# --------------------------------------------------------------------------- #
# docs_first: unchanged default behavior
# --------------------------------------------------------------------------- #
class TestDocsFirstUnchanged:
    def test_default_equals_explicit_docs_first(self):
        default = m._render_review_prompt(_monitor_spec(), "B", "P", "D")
        explicit = _review("docs_first", "B", "P", "D")
        assert default == explicit

    def test_docs_first_leads_with_documents(self):
        prompt = _review("docs_first", "B", "P", "D")
        assert prompt.startswith("<documents>")
        # The stable contract is a SUFFIX behind the variable documents.
        assert prompt.index("<documents>") < prompt.index("<task>")

    def test_docs_first_stable_contract_not_in_shared_prefix(self):
        """Cache-defeat demonstration: two docs_first dispatches that differ
        only in their variable documents do NOT share the stable contract in
        their common prefix — so a prefix cache cannot reach it."""
        import os

        p1 = _review("docs_first", "BUNDLE_ONE", "PREFS_ONE", "DIFF_ONE")
        p2 = _review("docs_first", "BUNDLE_TWO", "PREFS_TWO", "DIFF_TWO")
        common = os.path.commonprefix([p1, p2])
        assert "</expected_output>" not in common
        assert "<instructions>" not in common


# --------------------------------------------------------------------------- #
# stable_first: byte-identical cacheable prefix
# --------------------------------------------------------------------------- #
class TestStableFirstPrefixInvariant:
    def test_stable_first_leads_with_contract(self):
        prompt = _review("stable_first", "B", "P", "D")
        assert prompt.startswith("<task>")
        assert prompt.rstrip().endswith("</documents>")

    def test_stable_prefix_byte_identical_across_documents(self):
        """The whole stable contract is a byte-identical prefix regardless of
        the variable bundle / preferences / diff — the cacheable property."""
        p1 = _review("stable_first", "BUNDLE_ONE", "PREFS_ONE", "DIFF_ONE")
        p2 = _review("stable_first", "BUNDLE_TWO", "PREFS_TWO", "DIFF_TWO")

        assert _DOCS_MARKER in p1 and _DOCS_MARKER in p2
        prefix1 = p1[: p1.index(_DOCS_MARKER)]
        prefix2 = p2[: p2.index(_DOCS_MARKER)]
        assert prefix1 == prefix2, "stable prefix must not vary with documents"
        # And that prefix carries the full contract (non-trivial cache win).
        for tag in _STABLE_TAGS:
            assert tag in prefix1, f"stable prefix missing {tag}"
        # The variable content lives only after the marker.
        assert "BUNDLE_ONE" not in prefix1 and "DIFF_ONE" not in prefix1

    def test_same_content_only_reorders_no_loss(self):
        """Reordering preserves every section — same set of bytes, different
        order — so no content is dropped switching modes."""
        docs = _review("docs_first", "B", "P", "D")
        stable = _review("stable_first", "B", "P", "D")
        assert docs != stable
        for tag in ("<documents>", *_STABLE_TAGS, "</documents>"):
            assert tag in docs and tag in stable

    def test_invalid_mode_falls_back_to_docs_first(self):
        assert _review("bogus", "B", "P", "D") == _review("docs_first", "B", "P", "D")


# --------------------------------------------------------------------------- #
# complexity-lens builder mirrors the same layering
# --------------------------------------------------------------------------- #
class TestComplexityLensLayering:
    def test_docs_first_default_unchanged(self):
        default = m._render_complexity_lens_prompt("B", "D", "lite")
        explicit = m._render_complexity_lens_prompt("B", "D", "lite", "docs_first")
        assert default == explicit
        assert default.startswith("<documents>")

    def test_stable_first_reorders(self):
        prompt = m._render_complexity_lens_prompt("B", "D", "lite", "stable_first")
        assert prompt.startswith("<task>")
        assert prompt.rstrip().endswith("</documents>")


# --------------------------------------------------------------------------- #
# runtime config loader
# --------------------------------------------------------------------------- #
class TestLoadPromptLayering:
    def _write_config(self, tmp_path: Path, body: str) -> None:
        map_dir = tmp_path / ".map"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "config.yaml").write_text(body, encoding="utf-8")

    def test_absent_config_defaults_docs_first(self, tmp_path):
        assert m._load_prompt_layering(tmp_path) == "docs_first"

    def test_reads_stable_first(self, tmp_path):
        self._write_config(tmp_path, "prompt_layering: stable_first\n")
        assert m._load_prompt_layering(tmp_path) == "stable_first"

    def test_invalid_value_falls_back(self, tmp_path):
        self._write_config(tmp_path, "prompt_layering: sideways\n")
        assert m._load_prompt_layering(tmp_path) == "docs_first"

    def test_commented_key_defaults(self, tmp_path):
        self._write_config(tmp_path, "# prompt_layering: stable_first\n")
        assert m._load_prompt_layering(tmp_path) == "docs_first"


# --------------------------------------------------------------------------- #
# build_review_prompts threads the configured mode end-to-end
# --------------------------------------------------------------------------- #
class TestBuildReviewPromptsThreading:
    def _chdir_with_config(self, monkeypatch, tmp_path: Path, body: str) -> None:
        map_dir = tmp_path / ".map"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "config.yaml").write_text(body, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

    def test_default_is_docs_first(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = m.build_review_prompts(
            branch="test-branch",
            review_bundle_text="BUNDLE",
            git_diff_text="DIFF",
        )
        assert result["prompt_layering"] == "docs_first"
        assert result["prompts"]["monitor"]["prompt"].startswith("<documents>")

    def test_stable_first_threads_to_every_prompt(self, monkeypatch, tmp_path):
        self._chdir_with_config(
            monkeypatch, tmp_path, "prompt_layering: stable_first\n"
        )
        result = m.build_review_prompts(
            branch="test-branch",
            review_bundle_text="BUNDLE",
            git_diff_text="DIFF",
        )
        assert result["prompt_layering"] == "stable_first"
        for role, payload in result["prompts"].items():
            assert payload["prompt"].startswith("<task>"), (
                f"{role} prompt not stable_first ordered"
            )

    def test_stable_first_reaches_complexity_lens(self, monkeypatch, tmp_path):
        self._chdir_with_config(
            monkeypatch,
            tmp_path,
            "minimality: lite\nprompt_layering: stable_first\n",
        )
        result = m.build_review_prompts(
            branch="test-branch",
            review_bundle_text="BUNDLE",
            git_diff_text="DIFF",
        )
        assert "complexity_lens" in result["prompts"], "minimality lite must add lens"
        assert result["prompts"]["complexity_lens"]["prompt"].startswith("<task>")


# --------------------------------------------------------------------------- #
# install-time MapConfig registration + validation
# --------------------------------------------------------------------------- #
class TestMapConfigPromptLayering:
    def test_default_is_docs_first(self):
        from mapify_cli.config.project_config import MapConfig

        assert MapConfig().prompt_layering == "docs_first"

    def test_valid_value_loads(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir(parents=True)
        (map_dir / "config.yaml").write_text(
            "prompt_layering: stable_first\n", encoding="utf-8"
        )
        assert load_map_config(tmp_path).prompt_layering == "stable_first"

    def test_invalid_value_falls_back_to_default(self, tmp_path):
        from mapify_cli.config.project_config import load_map_config

        map_dir = tmp_path / ".map"
        map_dir.mkdir(parents=True)
        (map_dir / "config.yaml").write_text(
            "prompt_layering: sideways\n", encoding="utf-8"
        )
        assert load_map_config(tmp_path).prompt_layering == "docs_first"

    def test_generated_config_documents_the_knob(self):
        from mapify_cli.config.project_config import generate_default_config

        body = generate_default_config()
        assert "prompt_layering" in body
        # Shipped commented (default docs_first unchanged), not active.
        assert "# prompt_layering: docs_first" in body
        assert "\nprompt_layering:" not in body
