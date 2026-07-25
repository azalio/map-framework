"""Tests for apply_patcher.py (ST-006).

Covers VC1 (frontmatter description patched in rendered .claude/), VC2 (rendered
trees byte-identical after apply), VC3 (two distinct no-op messages), and VC4
(fail-loud on missing frontmatter / description key / bad paths).

CRITICAL: tests NEVER patch or render the real repo's templates_src / .claude /
.codex.  Every test that touches the render pipeline seeds a TEMP copy of
templates_src at a tmp_path and injects repo_root=tmp_path to all calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mapify_cli.skills_eval.apply_patcher import (
    apply_optimized_description,
    patch_skill_description,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Real repo root — used ONLY for seeding temp copies; never for patching/rendering.
_REAL = Path(__file__).resolve().parents[1]

# Skill used throughout the tests (must exist in templates_src).
_SKILL = "map-skill-eval"


def _seed_templates_src(tmp_path: Path) -> Path:
    """Copy the real templates_src tree into tmp_path; return the copy root."""
    src = _REAL / "src" / "mapify_cli" / "templates_src"
    dst = tmp_path / "src" / "mapify_cli" / "templates_src"
    shutil.copytree(src, dst)
    return tmp_path


def _jinja_path(tmp_root: Path, skill: str = _SKILL) -> Path:
    return (
        tmp_root
        / "src"
        / "mapify_cli"
        / "templates_src"
        / "skills"
        / skill
        / "SKILL.md.jinja"
    )


def _read_frontmatter_description(skill_md: Path) -> str:
    """Parse the YAML frontmatter via skill_ir.parse_frontmatter and return description."""
    from mapify_cli.skill_ir import parse_frontmatter

    text = skill_md.read_text(encoding="utf-8")
    # Extract text between the two ---
    assert text.startswith("---\n"), f"No frontmatter in {skill_md}"
    close_idx = text.find("\n---", 3)
    assert close_idx != -1, f"No closing --- in {skill_md}"
    fm_text = text[4:close_idx]
    parsed = parse_frontmatter(fm_text)
    return str(parsed.get("description", "")).strip()


# ---------------------------------------------------------------------------
# VC4: patch_skill_description — happy path
# ---------------------------------------------------------------------------


def test_vc4_patch_block_scalar_body_replaced(tmp_path: Path) -> None:
    """Happy path: description body is replaced; other keys and body are untouched."""
    jinja = _jinja_path(_seed_templates_src(tmp_path))
    original = jinja.read_text(encoding="utf-8")
    new_desc = "A brand-new description for testing."

    patch_skill_description(jinja, new_desc)

    patched = jinja.read_text(encoding="utf-8")
    # Parse back and confirm
    result = _read_frontmatter_description(jinja)
    assert result == new_desc, f"Got: {result!r}"

    # Other keys must still be present
    assert "effort:" in patched
    assert "disable-model-invocation:" in patched
    assert "argument-hint:" in patched

    # Body after closing --- is preserved
    orig_body_start = original.find("\n---\n") + 5
    orig_body = original[orig_body_start:]
    patch_body_start = patched.find("\n---\n") + 5
    patch_body = patched[patch_body_start:]
    assert patch_body == orig_body, "Body after frontmatter must be unchanged"


def test_vc4_patch_multiline_description_round_trips(tmp_path: Path) -> None:
    """A winner with newlines and special chars round-trips to exactly new_desc."""
    jinja = _jinja_path(_seed_templates_src(tmp_path))
    new_desc = (
        "Line one of a multi-line description.\n"
        "Line two: disable-model-invocation: true\n"
        "Line three: special chars <>&\"'"
    )

    patch_skill_description(jinja, new_desc)
    result = _read_frontmatter_description(jinja)
    assert result == new_desc, f"Round-trip mismatch.\nGot:      {result!r}\nExpected: {new_desc!r}"


def test_vc4_patch_uses_block_scalar_strip_chomping(tmp_path: Path) -> None:
    """Patched file uses '|-' (strip chomping) so no trailing newline in YAML parse."""
    jinja = _jinja_path(_seed_templates_src(tmp_path))
    new_desc = "Simple description."

    patch_skill_description(jinja, new_desc)
    patched = jinja.read_text(encoding="utf-8")
    assert "description: |-" in patched, "Must use '|-' block scalar indicator"


# ---------------------------------------------------------------------------
# VC4: patch_skill_description — fail-loud, no partial write
# ---------------------------------------------------------------------------


def test_vc4_fail_loud_no_frontmatter(tmp_path: Path) -> None:
    """ValueError raised and file unchanged when no YAML frontmatter present."""
    bad_file = tmp_path / "SKILL.md"
    original_content = "# No frontmatter here\nSome body."
    bad_file.write_text(original_content, encoding="utf-8")

    with pytest.raises(ValueError, match="frontmatter"):
        patch_skill_description(bad_file, "irrelevant")

    # File must be completely unchanged
    assert bad_file.read_text(encoding="utf-8") == original_content


def test_vc4_fail_loud_missing_description_key(tmp_path: Path) -> None:
    """ValueError raised and file unchanged when description: key is absent."""
    content = "---\nname: test-skill\neffort: low\n---\n# Body\n"
    bad_file = tmp_path / "SKILL.md"
    bad_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="description"):
        patch_skill_description(bad_file, "irrelevant")

    assert bad_file.read_text(encoding="utf-8") == content


def test_vc4_fail_loud_no_closing_fence(tmp_path: Path) -> None:
    """ValueError raised when there is no closing --- in frontmatter."""
    content = "---\nname: test-skill\ndescription: foo\n"
    bad_file = tmp_path / "SKILL.md"
    bad_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        patch_skill_description(bad_file, "irrelevant")

    assert bad_file.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# VC4: apply_optimized_description — path safety
# ---------------------------------------------------------------------------


def test_vc4_path_outside_templates_src_rejected(tmp_path: Path) -> None:
    """ValueError raised when skill would resolve outside templates_src."""
    repo_root = _seed_templates_src(tmp_path)

    # Use path traversal in skill name
    with pytest.raises((ValueError, FileNotFoundError)):
        apply_optimized_description(
            skill="../../evil",
            winner="new desc",
            current_description="old desc",
            no_improvement=False,
            repo_root=repo_root,
            stage=False,
        )


def test_vc4_missing_jinja_raises_file_not_found(tmp_path: Path) -> None:
    """FileNotFoundError when the skill does not exist in templates_src."""
    repo_root = _seed_templates_src(tmp_path)

    with pytest.raises(FileNotFoundError):
        apply_optimized_description(
            skill="nonexistent-skill-xyz",
            winner="new desc",
            current_description="old desc",
            no_improvement=False,
            repo_root=repo_root,
            stage=False,
        )


def test_vc4_git_path_in_parts_rejected(tmp_path: Path) -> None:
    """A target whose resolved path contains '.git' is rejected (under templates_src).

    Path-safety runs BEFORE the existence check, so this raises even though no such
    file exists — the '.git' segment is what triggers the ValueError, not relative_to.
    """
    repo_root = _seed_templates_src(tmp_path)

    with pytest.raises(ValueError, match=r"\.git"):
        apply_optimized_description(
            skill=".git/evil",
            winner="new desc",
            current_description="old desc",
            no_improvement=False,
            repo_root=repo_root,
            stage=False,
        )


def test_vc4_multiparagraph_block_scalar_fully_replaced(tmp_path: Path) -> None:
    """A multi-paragraph '|' block (interior blank lines) is fully replaced.

    The body-scan must consume interior blank lines as part of the block scalar,
    so the orphaned second paragraph is gone after patch and the next key survives.
    """
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: foo\n"
        "description: |\n"
        "  Paragraph one.\n"
        "\n"
        "  Paragraph two after a blank line.\n"
        "effort: medium\n"
        "---\n"
        "# body kept verbatim\n",
        encoding="utf-8",
    )

    patch_skill_description(skill_md, "Replacement description.")

    patched = skill_md.read_text(encoding="utf-8")
    assert _read_frontmatter_description(skill_md) == "Replacement description."
    # The second paragraph must be fully gone (block was consumed, not truncated).
    assert "Paragraph two after a blank line." not in patched
    assert "Paragraph one." not in patched
    # The next key and the body are intact.
    assert "effort: medium" in patched
    assert "# body kept verbatim" in patched


# ---------------------------------------------------------------------------
# VC3: no-op outcomes — two distinct messages
# ---------------------------------------------------------------------------


def test_vc3_no_improvement_message_and_no_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """no_improvement=True prints exact message; .jinja content and mtime unchanged."""
    repo_root = _seed_templates_src(tmp_path)
    jinja = _jinja_path(repo_root)
    original_content = jinja.read_text(encoding="utf-8")
    original_mtime = jinja.stat().st_mtime

    result = apply_optimized_description(
        skill=_SKILL,
        winner="some winner",
        current_description="old desc",
        no_improvement=True,
        repo_root=repo_root,
        stage=False,
    )

    captured = capsys.readouterr()
    assert result == "no_improvement"
    assert "No improvement found: current description already optimal on held-out test" in captured.out
    # File must be completely untouched
    assert jinja.read_text(encoding="utf-8") == original_content
    assert jinja.stat().st_mtime == original_mtime


def test_vc3_winner_identical_message_and_no_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """winner == current_description prints exact message; .jinja unchanged."""
    repo_root = _seed_templates_src(tmp_path)
    jinja = _jinja_path(repo_root)
    original_content = jinja.read_text(encoding="utf-8")
    original_mtime = jinja.stat().st_mtime

    current_desc = "Same description text."

    result = apply_optimized_description(
        skill=_SKILL,
        winner=current_desc,
        current_description=current_desc,
        no_improvement=False,
        repo_root=repo_root,
        stage=False,
    )

    captured = capsys.readouterr()
    assert result == "identical"
    assert "Winner identical to current description; no file changes" in captured.out
    assert jinja.read_text(encoding="utf-8") == original_content
    assert jinja.stat().st_mtime == original_mtime


# ---------------------------------------------------------------------------
# VC1 + VC2: full apply with temp repo
# ---------------------------------------------------------------------------


def test_vc1_rendered_claude_skill_md_description_equals_winner(tmp_path: Path) -> None:
    """VC1: after apply, .claude/skills/<skill>/SKILL.md frontmatter description == winner."""
    repo_root = _seed_templates_src(tmp_path)
    winner = "A completely new optimized description for the skill."

    result = apply_optimized_description(
        skill=_SKILL,
        winner=winner,
        current_description="something different",
        no_improvement=False,
        repo_root=repo_root,
        stage=False,
    )

    assert result == "applied"

    # Check the rendered .claude/skills/map-skill-eval/SKILL.md
    rendered_skill_md = repo_root / ".claude" / "skills" / _SKILL / "SKILL.md"
    assert rendered_skill_md.exists(), f"Expected rendered file: {rendered_skill_md}"

    rendered_desc = _read_frontmatter_description(rendered_skill_md)
    assert rendered_desc == winner, (
        f"Rendered description mismatch.\nGot:      {rendered_desc!r}\nExpected: {winner!r}"
    )


def test_vc2_rendered_trees_byte_identical_after_apply(tmp_path: Path) -> None:
    """VC2: diff_rendered_trees returns [] for both providers after apply.

    Both repo_root and templates_src_root point to the temp copy so the check
    compares a fresh render (from the patched temp source) against the already-
    rendered temp output — they must be byte-identical.
    """
    from mapify_cli.delivery.template_renderer import (
        diff_rendered_trees,
    )

    repo_root = _seed_templates_src(tmp_path)
    templates_src_root = repo_root / "src" / "mapify_cli" / "templates_src"
    winner = "New description for byte-identity test."

    result = apply_optimized_description(
        skill=_SKILL,
        winner=winner,
        current_description="old description value",
        no_improvement=False,
        repo_root=repo_root,
        stage=False,
    )

    assert result == "applied"

    # After render, diff_rendered_trees must return [] (byte-identical).
    # Pass templates_src_root so diff_rendered_trees reads from the patched temp
    # source rather than the installed package's templates_src.
    diffs_claude = diff_rendered_trees(
        "claude", repo_root=repo_root, templates_src_root=templates_src_root
    )
    assert diffs_claude == [], (
        f"claude trees not byte-identical after apply. Diffs: {diffs_claude}"
    )

    diffs_codex = diff_rendered_trees(
        "codex", repo_root=repo_root, templates_src_root=templates_src_root
    )
    assert diffs_codex == [], (
        f"codex trees not byte-identical after apply. Diffs: {diffs_codex}"
    )


def test_vc1_skill_rules_json_description_unchanged(tmp_path: Path) -> None:
    """VC1: skill-rules.json description is NOT modified by apply."""
    repo_root = _seed_templates_src(tmp_path)

    # Find the skill-rules.json.jinja and render initial state
    from mapify_cli.delivery.template_renderer import render_repo_trees

    render_repo_trees("claude", repo_root=repo_root)

    # Read skill-rules.json BEFORE apply
    skill_rules = repo_root / ".claude" / "skills" / "skill-rules.json"
    if not skill_rules.exists():
        pytest.skip("skill-rules.json not present in rendered output")

    import json as _json

    before = _json.loads(skill_rules.read_text(encoding="utf-8"))
    # skills is a dict keyed by skill name, each value is a dict with 'description' etc.
    skills_before: dict[str, object] = before.get("skills", {})
    skill_entry_before = skills_before.get(_SKILL, {})
    before_desc = skill_entry_before.get("description") if isinstance(skill_entry_before, dict) else None  # type: ignore[union-attr]

    winner = "Totally different description that should not appear in skill-rules.json."

    apply_optimized_description(
        skill=_SKILL,
        winner=winner,
        current_description="some old desc",
        no_improvement=False,
        repo_root=repo_root,
        stage=False,
    )

    after = _json.loads(skill_rules.read_text(encoding="utf-8"))
    skills_after: dict[str, object] = after.get("skills", {})
    skill_entry_after = skills_after.get(_SKILL, {})
    after_desc = skill_entry_after.get("description") if isinstance(skill_entry_after, dict) else None  # type: ignore[union-attr]

    assert before_desc == after_desc, (
        f"skill-rules.json description was modified by apply!\n"
        f"Before: {before_desc!r}\nAfter:  {after_desc!r}"
    )
    assert winner not in str(after_desc), (
        "Winner text must NOT appear in skill-rules.json after apply"
    )
