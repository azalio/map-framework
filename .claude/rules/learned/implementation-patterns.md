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

- **Blast-Radius / "Validate Callers" Detectors Must Exclude Generic Process-Entrypoint Names** (2026-05-29): When a static-analysis detector flags a changed module-level symbol and recommends validating its external callers, exclude generic process-entrypoint names (`main`, and by extension `run`/`cli`/`app` if a project uses them that way) in the SAME predicate that already excludes dunders and too-short names. These names are invoked by convention (`if __name__ == "__main__"`, `python -m`, entry_points), never imported as shared helpers, so they have no true import-callers — but the literal word matches prose in docs/config. A changed `def main()` matched "main" in ~168 SKILL.md / settings.json lines and recommended `validate_callers` on every entrypoint edit. Centralize the exclusion in one `_is_reportable_symbol` predicate so every consumer inherits it; meaningful-symbol callers in markdown stay flagged by design. [workflow: map-efficient]
  ```python
  _GENERIC_ENTRYPOINT_NAMES = frozenset({"main"})  # add run/cli/app only if used that way

  def _is_reportable_symbol(name: str) -> bool:
      return (
          bool(name)
          and not (name.startswith("__") and name.endswith("__"))  # dunders
          and len(name) >= 3                                        # too-short
          and name not in _GENERIC_ENTRYPOINT_NAMES                 # convention-called entrypoints
      )
  ```

- **Watched-vs-Owned File Categorization via a Single `fenced=` Boolean on the Copy Function** (2026-05-31): When an installer manages files in two lifecycle categories — (A) "watched/fenced": managed region refreshed in place, user content BELOW the fence preserved byte-for-byte on update (INV-5); (B) "owned": fully overwritten on update, timestamped `.bak` on drift, no fence — model the split as ONE per-call boolean `fenced=` on the shared copy function, not two functions or a string enum. One code path, one audit trail, one place to fix fence logic. Callers pass `fenced=True` where the downstream user is expected to extend below the fence (agents, skills, CLAUDE.md), `fenced=False` for fully-owned trees (references, map scripts, hooks). JSON is always `fenced=False` because it has no comment syntax — ownership is signalled by a sentinel root key (in this repo, `_map_managed`) instead. [workflow: map-efficient]
  ```python
  def copy_managed_file(src, dest, version, *, fenced: bool = True): ...
  copy_managed_file(s/"CLAUDE.md",     d/"CLAUDE.md",     version)               # watched
  copy_managed_file(s/"host-paths.md", d/"host-paths.md", version, fenced=False) # owned
  ```

- **Preserve Executable Bits After an Atomic Temp-File Writer: chmod 0o755 After Every Managed Write of an Executable** (2026-05-31): A managed copier that writes atomically (write a temp file, then `os.replace()`/`Path.replace()` into place) sets the destination mode from the TEMP file's creation mode — typically `0o644` — discarding the source file's `+x`. Any `.sh` or hook/script `.py` installed via this path silently loses executability; the file is correct but `./script.sh` fails "Permission denied", often not surfacing until an integration test invokes it. Fix: after every managed write of a known-executable file (`.sh`, `hooks/*.py`, `scripts/*`), explicitly re-chmod to `0o755`. Do not rely on `shutil.copy2` or source-mode preservation through the atomic replace — the replace drops source metadata. Mirror the chmod in EVERY caller (map-tools, codex hooks, skill scripts). [workflow: map-efficient]
  ```python
  copy_managed_file(src, dest, version)
  if src.suffix in (".sh", ".py") and dest.exists():
      dest.chmod(dest.stat().st_mode | 0o755)
  # test guard: assert os.access(installed_hook, os.X_OK)
  ```
