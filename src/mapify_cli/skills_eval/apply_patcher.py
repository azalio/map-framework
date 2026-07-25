"""Apply an optimized skill description to the single-source .jinja template.

Invariants enforced by this module
-----------------------------------
INV-5 / source-untouched:  only the specified .jinja file is written;
                            generated trees are updated via render_repo_trees.
INV-9 / path-safety:       target .jinja must resolve under templates_src/;
                            paths under .git/ are rejected.
VC3 / no-op messages:      two distinct messages for the two no-write outcomes;
                            baseline is NEVER written back (no_improvement guard).
VC4 / fail-loud:           patch_skill_description raises ValueError on bad input
                            with NO partial write; YAML block scalar format enforced.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def patch_skill_description(skill_md_path: Path, new_description: str) -> None:
    """Rewrite the ``description:`` block scalar in a SKILL.md.jinja frontmatter.

    The file MUST begin with ``---\\n`` and contain a closing ``\\n---``.
    The ``description:`` key MUST exist at column 0 in the frontmatter.

    All computation is done in-memory; the file is written ONCE at the end.
    On any validation error the file is left completely untouched.

    Args:
        skill_md_path: Path to the .jinja file to patch (or any SKILL.md).
        new_description: Replacement description text (already .strip()'d).

    Raises:
        ValueError: frontmatter missing, description key absent, or path rejected.
        FileNotFoundError: skill_md_path does not exist.
    """
    # Intent: read-then-compute-then-write-once; no partial write on failure.
    text = skill_md_path.read_text(encoding="utf-8")

    # --- Validate frontmatter presence ---
    if not text.startswith("---\n"):
        raise ValueError(
            f"No YAML frontmatter found in {skill_md_path}: "
            "file must start with '---\\n'"
        )
    # Find closing --- (must have \n--- to be valid)
    close_idx = text.find("\n---", 3)
    if close_idx == -1:
        raise ValueError(
            f"No closing '---' found in frontmatter of {skill_md_path}"
        )
    # The closing marker: we want the \n--- (possibly \n---\n or \n--- at EOF)
    # close_idx points to the '\n' before '---'
    frontmatter_end = close_idx + 4  # len('\n---') = 4

    frontmatter = text[4:close_idx]  # content between the two ---
    rest_of_file = text[frontmatter_end:]  # everything from closing --- onward

    # --- Locate description: key at column 0 ---
    fm_lines = frontmatter.split("\n")
    desc_line_idx: int | None = None
    for i, line in enumerate(fm_lines):
        if line.startswith("description:"):
            desc_line_idx = i
            break

    if desc_line_idx is None:
        raise ValueError(
            f"No 'description:' key found at column 0 in frontmatter of {skill_md_path}"
        )

    # --- Find the indented body lines that belong to description ---
    # A YAML block scalar body includes indented lines AND interior blank lines
    # (blank lines are part of a multi-paragraph '|' block), ending at the first
    # NON-blank 0-indent line (the next key) or end of frontmatter.
    body_start = desc_line_idx + 1
    body_end = body_start  # exclusive end index
    for i in range(body_start, len(fm_lines)):
        line = fm_lines[i]
        if line == "" or line.startswith((" ", "\t")):
            body_end = i + 1
        else:
            break
    # Trim TRAILING blank lines back out of the replaced span so a blank separator
    # between the description block and the next key is preserved (no whitespace drift).
    # Interior blanks are kept because the trim stops at the first non-blank line.
    while body_end > body_start and fm_lines[body_end - 1] == "":
        body_end -= 1

    # --- Build the new description block scalar (|- strip chomping) ---
    # Use '|-' so YAML-parsed value == new_description exactly (no trailing newline).
    new_desc_lines = ["description: |-"]
    for desc_line in new_description.split("\n"):
        new_desc_lines.append(f"  {desc_line}")

    # --- Reassemble frontmatter ---
    new_fm_lines = (
        fm_lines[:desc_line_idx]
        + new_desc_lines
        + fm_lines[body_end:]
    )
    new_frontmatter = "\n".join(new_fm_lines)
    new_text = "---\n" + new_frontmatter + "\n---" + rest_of_file

    # Intent: single atomic write after all validation passes.
    skill_md_path.write_text(new_text, encoding="utf-8")


def apply_optimized_description(
    *,
    skill: str,
    winner: str,
    current_description: str,
    no_improvement: bool,
    repo_root: Path,
    stage: bool = True,
) -> str:
    """Apply ``winner`` description to the skill's single-source .jinja template.

    Prints a user-facing message and returns an outcome code string.

    Outcome codes:
        ``'no_improvement'``  — baseline wins; nothing written.
        ``'identical'``       — winner == current; nothing written.
        ``'applied'``         — .jinja patched and trees re-rendered.

    Args:
        skill: Skill name (e.g. ``'map-skill-eval'``).
        winner: Candidate description text that won the eval.
        current_description: Current description text from the .jinja.
        no_improvement: True when baseline beat every candidate on held-out test.
        repo_root: Absolute path to the repository root.
        stage: If True, stage the patched .jinja + existing gate trees via a scoped
            ``git add -- <paths>`` after rendering (warn-only on failure; never commits).

    Returns:
        Outcome code string.

    Raises:
        ValueError: Path safety violation (outside templates_src or under .git/).
        FileNotFoundError: .jinja source file does not exist.
    """
    # --- VC3: no_improvement guard — NEVER write baseline back ---
    if no_improvement:
        print(
            "No improvement found: current description already optimal on held-out test"
        )
        return "no_improvement"

    # --- VC3: winner identical guard ---
    if winner == current_description:
        print("Winner identical to current description; no file changes")
        return "identical"

    # --- Resolve and validate target path BEFORE any filesystem touch (INV-9) ---
    # Path-safety runs first so a traversal/.git target is rejected even when the
    # file does not exist (resolve() normalises '..' without requiring existence).
    templates_src_root = (repo_root / "src" / "mapify_cli" / "templates_src").resolve()
    jinja = repo_root / "src" / "mapify_cli" / "templates_src" / "skills" / skill / "SKILL.md.jinja"
    resolved = jinja.resolve()

    # Intent: reject paths that escape templates_src or touch .git/
    try:
        resolved.relative_to(templates_src_root)
    except ValueError:
        raise ValueError(
            f"Path safety violation: {resolved} is not under {templates_src_root}"
        ) from None

    if ".git" in resolved.parts:
        raise ValueError(f"Path safety violation: {resolved} is under .git/")

    if not jinja.exists():
        raise FileNotFoundError(
            f"SKILL.md.jinja not found for skill '{skill}': {jinja}"
        )

    # --- Patch the .jinja source ---
    patch_skill_description(jinja, winner)

    # --- Re-render both providers (INV-5) ---
    # Intent: import inline to keep module importable without jinja2 at module load time.
    # Pass templates_src_root explicitly so that when repo_root is a temp dir
    # the renderer reads from the temp copy, not the installed package source.
    from mapify_cli.delivery.template_renderer import render_repo_trees

    render_templates_src = repo_root / "src" / "mapify_cli" / "templates_src"
    render_repo_trees("claude", repo_root=repo_root, templates_src_root=render_templates_src)
    render_repo_trees("codex", repo_root=repo_root, templates_src_root=render_templates_src)

    # --- Optionally stage ONLY the patched source + rendered gate trees (warn-only) ---
    # Scoped staging (never `git add -A`): avoids sweeping unrelated dirty files
    # (in-progress work, .map/ workflow state) into the caller's next commit.
    if stage:
        gate_relpaths = (
            ".claude",
            ".codex",
            "src/mapify_cli/templates",
            ".agents/skills",
        )
        to_stage: list[str] = [str(jinja.relative_to(repo_root))]
        for rel in gate_relpaths:
            if (repo_root / rel).exists():
                to_stage.append(rel)
        result = subprocess.run(
            ["git", "add", "--", *to_stage],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"Warning: 'git add' failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

    # --- Reminder: skill-rules.json is NOT auto-patched ---
    print(
        f"Applied new description for '{skill}'. "
        "Note: skill-rules.json description is NOT auto-patched — "
        "update it by hand or via ST-008."
    )

    return "applied"
