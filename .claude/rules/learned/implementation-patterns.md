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

- **`claude -p` Output Has Two Channels: Envelope for Tokens, Transcript JSONL for Skill Name** (2026-06-04): When shelling `claude -p --output-format json` as a subprocess, two distinct output channels carry different information — do not confuse them. The JSON result envelope (stdout) carries `.result` (response text), `.usage` (input/output/cache tokens), and `.session_id`. The name of the skill/slash-surface that actually fired is NOT in the envelope — it is only in Claude Code's native transcript JSONL (located by session_id) as a `tool_use` block with `name=="Skill"` and `input.skill`. Deriving this from the framework's own scratch/digest schema rather than the native transcript yields a wrong claim. Verify empirically by reading the real transcript after a spike call; never infer from internal schema files. [workflow: map-efficient]
  ```python
  env = json.loads(proc.stdout)        # .result, .usage, .session_id
  tokens = env["usage"]                # CORRECT — tokens are in the envelope
  # env.get("skill")  -> None          # WRONG — fired-skill is NOT in the envelope
  for line in transcript_jsonl(env["session_id"]).read_text().splitlines():
      m = json.loads(line)
      if m.get("type") == "tool_use" and m.get("name") == "Skill":
          triggered = m["input"]["skill"]; break
  ```

- **Scoped Config-Flag Mutation: Seed a Throwaway Temp Copy; Never Modify the Production Source of Truth** (2026-06-04): When a tool/test needs a shipped config flag to behave differently from its production default (e.g. stripping `disable-model-invocation: true` so an eval can auto-select skills), mutate the flag ONLY in a throwaway temp dir seeded with a copy of the production config, discarded after the subprocess exits. Never patch the source repo or `templates_src`. A blanket production flip is a footgun: it silently changes behavior for every other user of the flag and may be committed accidentally. Scope of mutation must match scope of need: one subprocess call → one throwaway dir, always cleaned up in `finally`. [workflow: map-efficient]
  ```python
  tmp = Path(tempfile.mkdtemp())
  shutil.copytree(REPO / ".claude", tmp / ".claude")     # seed from production
  strip_flag(tmp / ".claude" / "skills")                 # mutate throwaway ONLY
  try:
      subprocess.run(["claude", "-p", prompt, "--output-format", "json"], cwd=tmp)
  finally:
      shutil.rmtree(tmp)                                  # production never touched
  ```

- **Clock-Free Core with Caller-Supplied Path: Inject Timestamps at the CLI Boundary, Not Inside the Worker** (2026-06-04): When a worker writes durable output (a timestamped JSONL, a run artifact), do NOT call `datetime.now()` inside the worker. Have the CLI/outermost caller generate the timestamped path and pass it as an explicit `out_path: Path` the worker treats as opaque. Benefits: (1) tests pass `tmp_path / "results.jsonl"` with zero clock monkeypatching; (2) the worker is deterministic given the same inputs+path; (3) resume keys on the path the CLI owns. Refines "Long-Running Operations Need Durable State by Default" by fixing WHERE path/timestamp generation lives — at the boundary, not the core. [workflow: map-efficient]
  ```python
  # CORRECT: worker takes out_path; CLI owns the timestamp
  def run_eval(*, entries, dispatcher, runs, out_path: Path, resume=False) -> list: ...
  # CLI: out = default_run_path(root, skill, datetime.now(tz).strftime("%Y%m%dT%H%M%SZ"))
  # Test: run_eval(..., out_path=tmp_path / "r.jsonl")   # no time mocking
  ```

- **Concurrent Durable Append: threading.Lock for Line Integrity + Stable cell_id Resume Key** (2026-06-04): When parallel workers append JSONL lines to a shared durable file, two invariants must BOTH hold: (1) no interleaved partial lines — guard each `f.write(line + "\n")` with a threading.Lock; (2) resume is idempotent regardless of write order — key on a stable id present in every record (cell_id), never on line number/position. Nondeterministic write order is fine as long as resume dedups by id. Each worker subprocess also runs in its own temp cwd so concurrent subprocesses never share a working dir. Complements "Long-Running Operations Need Durable State" (process-restart durability) with within-process concurrency safety. [workflow: map-efficient]
  ```python
  with self._lock:                       # atomic per-line append
      with out_path.open("a", encoding="utf-8") as f:
          f.write(json.dumps(record) + "\n")
  done = {json.loads(l)["cell_id"] for l in out_path.read_text().splitlines() if l.strip()}
  pending = [c for c in cells if make_cell_id(...) not in done]   # order-independent resume
  ```

- **dict[str,object] Pyright Barrier: Cast at Return/Creation Sites for Iterate and Double-Index Operations** (2026-06-21): When a function returns `dict[str, object]`, Pyright rejects any operation on a retrieved value that needs the runtime type — iteration (`for e in result["errors"]`), subscript/double-index (`result["fc"]["status"]`), method calls. Equality comparison (`result["errors"] == []`) is the ONLY operation legal on `object`, which is why pre-existing compare-only tests stay clean while new tests that iterate or double-index produce a batch of errors. Fix by widening the return type to `dict[str, Any]` at the few creation/return sites (the builder helper + direct returns), NOT by adding `cast()` at every downstream usage. [workflow: map-efficient]
  ```python
  # WRONG — dict[str, object] blocks iterate/index downstream; equality still ok
  def validate(bp) -> dict[str, object]: ...
  for e in result["errors"]: ...          # ERROR: object not iterable
  fc = result["forward_coverage"]; fc["status"]   # ERROR: object has no __getitem__
  result["errors"] == []                  # OK
  # CORRECT — widen at the creation site; all callers unblocked, no per-call casts
  from typing import Any
  def validate(bp) -> dict[str, Any]: ...   # 34 downstream errors cleared by 1 change site
  ```

- **Behavior-Neutral Foundation: Gate Every New Path Behind a Flag That Defaults to Current Behavior, Plus Add a Default-Config Proof Test** (2026-06-29): When shipping a foundation subtask for a risky feature (parallel execution, new state machine, schema migration), every new code path must be predicate-gated behind a config key or compile-time constant that defaults to the existing behavior. A `WAVE_CONCURRENCY_ENABLED=False` constant (or equivalent) prevents any new dispatch path from being exercised by default. The proof is NOT "the tests still pass" — it is a dedicated test that loads the default (empty) config and asserts the old/sequential path is selected. Without this test, a subtle config-default bug can silently activate the new path on upgrade in every consumer repo. Ship the flag, ship the test, then the foundation can land without a soak period. [workflow: map-efficient]
  ```python
  # WRONG: new path always reachable; no behavioral gate
  def select_wave_loop(config: MapConfig) -> WaveLoop:
      if config.execution_wave_mode == 'parallel':
          return ParallelWaveLoop(config)  # reachable if user misconfigures
      return SequentialWaveLoop(config)

  # CORRECT: compile-time kill-switch + proof test
  WAVE_CONCURRENCY_ENABLED = False  # PR-level constant; flip only when feature is ready
  def select_wave_loop(config: MapConfig) -> WaveLoop:
      if not WAVE_CONCURRENCY_ENABLED or config.execution_wave_mode != 'parallel':
          return SequentialWaveLoop(config)  # old path, guaranteed in this PR
      return ParallelWaveLoop(config)

  def test_default_config_selects_sequential_loop(tmp_path):
      cfg = load_map_config(tmp_path / '.map' / 'config.yaml')  # no file -> defaults
      assert isinstance(select_wave_loop(cfg), SequentialWaveLoop)
  ```

- **Shared .jinja Templates Rendering Into Multiple Provider Trees Must Not Contain Provider-Specific API Tokens in the Codex Variant** (2026-06-29): When a `.jinja` template in `templates_src/` renders into BOTH a Claude-family tree (`.claude/skills/`) AND a Codex/agents-family tree (`.agents/skills/`, `templates/codex/`), provider-specific Claude API identifiers — `subagent_type=`, `Agent(`, `AskUserQuestion(`, `Task(` — must not appear in the codex-rendered output. A CI test (`test_ac10_no_claude_refs_anywhere`) enforces this and hard-fails `make check`. The leak is easy to introduce when editing doc examples in a shared `.jinja` (you write from the Claude perspective). Fix: after `make render-templates`, grep the codex output paths for forbidden tokens; if found, use provider-neutral prose or a jinja conditional. Do not rely on the CI gate as first-line detection — grep after rendering, before commit. [workflow: map-efficient]
  ```bash
  make render-templates
  grep -r 'subagent_type=\|AskUserQuestion\|Agent(\|Task(' .agents/skills/ src/mapify_cli/templates/codex/
  # must be empty; otherwise use provider-neutral phrasing or {% if provider == 'claude' %}...{% else %}...{% endif %}
  ```

- **Test Discrete-Unit Membership on the Structured Representation, Not a Flattened/Implicit Proxy** (2026-07-03): When a check or extraction is meant to test membership or boundaries over discrete structured units (argv tokens, section headings, CLI flags), always operate on the structured representation directly — list membership, an explicit state flag — rather than collapsing it to a flattened string or an implicit two-address range. The flattened/implicit form's native semantics (substring-anywhere-in-text, range-closes-on-co-match) silently test a broader-or-narrower property than intended and degrade to flaky-or-always-wrong behavior instead of erroring where you'd notice: a joined-argv substring check false-positived on an unrelated pytest tmp_path fragment, and an awk `/start/,/end/` range collapsed to one line because its two regexes could co-match, permanently zeroing a CHANGELOG-completeness gate. Generalizes both the testing-strategies "argv token membership" rule and the error-patterns "awk range collapse" rule to a single root cause. [workflow: map-release]
