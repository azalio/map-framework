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

- **Conditional vs Required Field Distinction in Truncation Detection** (2026-05-27): When building a detect_truncated_agent_output function (or any output validator), distinguish REQUIRED fields (must always be present in a valid output) from CONDITIONAL fields (present only when a trigger condition is met, e.g., sibling_comparison only when siblings exist). CONDITIONAL fields must be EXCLUDED from the required_keys used for truncation detection, but INCLUDED in the output skeleton as a placeholder string (e.g., '[CONDITIONAL]') so the agent knows the field exists. Treating conditional fields as required produces false truncation positives on valid outputs that legitimately omit the field. [workflow: map-efficient]
  ```python
  # WRONG — conditional field in required_keys: valid outputs falsely flagged truncated
  MONITOR_REQUIRED = ('severity', 'justification', 'sibling_comparison')  # conditional!

  def detect_truncated(output: dict) -> bool:
      return any(k not in output for k in MONITOR_REQUIRED)  # false positive when no siblings

  # CORRECT — conditional in skeleton only; required_keys derived from non-conditional:
  AGENT_OUTPUT_SCHEMAS = {
      'monitor': {
          'severity': '',                        # required
          'justification': '',                   # required
          'sibling_comparison': '[CONDITIONAL]', # conditional — marker value
      }
  }
  MONITOR_REQUIRED = tuple(
      k for k, v in AGENT_OUTPUT_SCHEMAS['monitor'].items()
      if v != '[CONDITIONAL]'
  )  # ('severity', 'justification') — sibling_comparison correctly excluded

  def detect_truncated(output: dict) -> bool:
      return any(k not in output for k in MONITOR_REQUIRED)  # correct
  ```

- **Content-Preserving Reorganization Requires Sorted-Line-Set Self-Check** (2026-05-27): When performing a content-preserving file reorganization (inserting a marker, adding frontmatter, moving a section) where the intent is that NO body lines are added, removed, or reordered, verify the invariant mechanically via a sorted-line-set comparison: extract line sets before and after (excluding known-inserted lines), sort both, and assert equality. Human diff review misses spurious blank lines, off-by-one insertions, and near-identical whitespace variants. Run the check as an inline Python snippet immediately after the edit — catching violations in-place is cheaper than reverting a commit. [workflow: map-efficient]
  ```python
  import subprocess

  def verify_content_preserving(
      path: str,
      inserted_lines: set[str],
      frontmatter_lines: int = 2,
      base_ref: str = 'HEAD',
  ) -> None:
      before = subprocess.check_output(
          ['git', 'show', f'{base_ref}:{path}'], text=True
      ).splitlines()
      with open(path) as f:
          after = f.read().splitlines()

      def normalize(lines: list[str]) -> list[str]:
          body = lines[frontmatter_lines:]  # skip frontmatter
          return sorted(l for l in body if l.strip() not in inserted_lines)

      assert normalize(before) == normalize(after), (
          f'Content-preserving invariant violated in {path}. '
          f'Before: {len(normalize(before))} lines, After: {len(normalize(after))} lines'
      )

  # Run immediately after editing the file:
  verify_content_preserving(
      'predictor.md',
      inserted_lines={'<!-- REFERENCE APPENDIX (read on demand) -->'},
  )
  ```

- **`del` Is Illegal Inside a Python Lambda Body** (2026-05-12): When suppressing Pyright `reportUnusedParameter` on a lambda with variadic args (`*_args, **_kwargs`), never insert `del _args, _kwargs` inside the lambda body — `del` is a STATEMENT and lambda bodies are limited to a single expression. The insertion produces `SyntaxError`. Correct alternatives: an inline `# pyright: ignore[reportUnusedParameter]` on the lambda line, OR rely on the `_` prefix convention (Pyright honors `_`-prefixed names without warning in most configurations). For regular `def` functions `del` works fine. [workflow: map-efficient]
  ```python
  # WRONG — del is a statement; illegal in lambda expression body
  types.SimpleNamespace(
      compute=lambda *_args, **_kwargs: del _args, _kwargs or mock_result  # SyntaxError!
  )

  # CORRECT — inline pyright suppression comment
  types.SimpleNamespace(
      compute=lambda *_args, **_kwargs: mock_result  # pyright: ignore[reportUnusedParameter]
  )

  # In a regular def (NOT lambda), del is valid:
  def compute(*_args: object, **_kwargs: object) -> Result:
      del _args, _kwargs
      return mock_result
  ```
