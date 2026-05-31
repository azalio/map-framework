#!/usr/bin/env python3
"""ST-011: Inject map:start/map:end fence markers into templates_src jinja files.

Rules per format:
  .md  (no frontmatter): <!-- map:start --> first line, <!-- map:end --> last line
  .md  (with YAML frontmatter ---): <!-- map:start --> after closing ---, <!-- map:end --> last
  .py  (has shebang): shebang line 1, # map:start line 2, ..., # map:end last line
  .sh  (has shebang): same as .py
  .toml: # map:start line 1, ..., # map:end last line
  .json: SKIP (no fence)

Each fence token is a standalone line (strip() == token exactly).
Preserves trailing newline.
Skips files that already contain a fence token.
"""

from __future__ import annotations

import sys
from pathlib import Path

TEMPLATES_SRC = Path(__file__).parent.parent / "src" / "mapify_cli" / "templates_src"

MD_START = "<!-- map:start -->"
MD_END = "<!-- map:end -->"
HASH_START = "# map:start"
HASH_END = "# map:end"


def find_yaml_frontmatter_end(lines: list[str]) -> int:
    """Return index of the line AFTER the closing --- of YAML frontmatter.

    Returns 0 if no frontmatter found (caller should treat as no-frontmatter).
    Frontmatter must start with --- on line 0 and have a closing --- at index > 0.
    """
    if not lines or lines[0].rstrip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            # Return index of line after closing ---
            return i + 1
    return 0  # No closing --- found → treat as no frontmatter


def inject_fences(path: Path) -> bool:
    """Inject fence markers into a single file. Returns True if modified."""
    # Determine format by stripping .jinja and getting the real extension
    stem = path.stem  # e.g. "actor.md" for "actor.md.jinja"
    real_ext = Path(stem).suffix.lower()  # e.g. ".md"

    # JSON: skip
    if real_ext == ".json":
        return False

    # Only handle supported formats
    if real_ext not in (".md", ".py", ".sh", ".toml"):
        return False

    text = path.read_text(encoding="utf-8")

    # Check for existing fence markers — skip if already fenced
    if real_ext == ".md":
        start_tok, end_tok = MD_START, MD_END
    else:
        start_tok, end_tok = HASH_START, HASH_END

    for line in text.splitlines():
        if line.strip() == start_tok or line.strip() == end_tok:
            print(f"SKIP (already fenced): {path}", file=sys.stderr)
            return False

    # Preserve trailing newline state
    has_trailing_newline = text.endswith("\n")
    lines = text.splitlines()

    if not lines:
        # Empty file — add fences around empty content
        new_lines = [start_tok, end_tok]
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True

    if real_ext == ".md":
        fm_end = find_yaml_frontmatter_end(lines)
        if fm_end > 0:
            # Has frontmatter: insert start fence after closing ---
            # [0..fm_end-1] = frontmatter lines, insert start_tok at fm_end
            new_lines = lines[:fm_end] + [start_tok] + lines[fm_end:] + [end_tok]
        else:
            # No frontmatter: start fence is first line
            new_lines = [start_tok] + lines + [end_tok]

    elif real_ext in (".py", ".sh"):
        # Shebang must be line 0; insert start fence at line 1
        if lines[0].startswith("#!"):
            new_lines = [lines[0], start_tok] + lines[1:] + [end_tok]
        else:
            # No shebang (unexpected per research, but handle safely)
            new_lines = [start_tok] + lines + [end_tok]

    elif real_ext == ".toml":
        # No shebang: start fence is first line
        new_lines = [start_tok] + lines + [end_tok]

    else:
        return False  # unreachable

    result = "\n".join(new_lines)
    if has_trailing_newline:
        result += "\n"

    path.write_text(result, encoding="utf-8")
    return True


def main() -> None:
    modified = 0
    skipped = 0

    jinja_files = sorted(TEMPLATES_SRC.rglob("*.jinja"))
    print(f"Found {len(jinja_files)} .jinja files in templates_src")

    for path in jinja_files:
        stem = path.stem
        real_ext = Path(stem).suffix.lower()
        if real_ext == ".json":
            print(f"SKIP (json): {path.relative_to(TEMPLATES_SRC)}")
            skipped += 1
            continue
        if real_ext not in (".md", ".py", ".sh", ".toml"):
            print(f"SKIP (unknown ext {real_ext}): {path.relative_to(TEMPLATES_SRC)}")
            skipped += 1
            continue

        if inject_fences(path):
            print(f"FENCED: {path.relative_to(TEMPLATES_SRC)}")
            modified += 1
        else:
            skipped += 1

    print(f"\nDone: {modified} files fenced, {skipped} skipped")


if __name__ == "__main__":
    main()
