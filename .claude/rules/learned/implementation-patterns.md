---
paths:
  - "**/*.py"
---

# Implementation Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Python Dataclass Type Validation** (2026-03-26): When building a dataclass from parsed YAML/JSON config, always add explicit type checking (isinstance in __post_init__ or pre-filter before construction), because Python dataclass type hints are documentation only — a string where int is expected passes silently and breaks downstream operations. [workflow: map-learn-improvement]

- **Validation Functions Must Return None on Invalid** (2026-03-26): When writing a function named load_and_validate or similar, always return None (or raise) on invalid input and return data only on valid, because callers use `if result is not None:` as a validity signal — returning data on failure inverts the contract silently. [workflow: map-learn-improvement]

- **Symmetric Read/Write Paths for Structured File Headers** (2026-04-11): When injecting metadata into structured text files, detect known header formats (YAML frontmatter `---`, shebangs `#!`, XML prolog) and insert AFTER the header block, never before it. The extraction path must search at the same position where the write path inserted. Asymmetric read/write paths cause silent metadata loss or duplicate entries on round-trip. Retain a fallback for files without the header to preserve backward compatibility. [workflow: map-learn-bugfix]
  ```python
  # WRONG: prepend unconditionally, corrupts YAML frontmatter
  content = f"{COMMENT}\n{original}"

  # CORRECT: detect boundary, inject after; extraction mirrors inject
  def inject_after_frontmatter(content: str, comment: str) -> str:
      if content.startswith("---"):
          end = content.find("\n---\n", 3)
          if end != -1:
              pos = end + 5  # character after closing ---\n
              return content[:pos] + comment + "\n" + content[pos:]
      return comment + "\n" + content  # fallback: no frontmatter
  ```
