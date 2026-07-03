---
paths:
  - "**/test_*"
  - "**/tests/**"
  - "**/*_test.*"
  - "**/*.test.*"
---

# Testing Strategies (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Monitor Bugs Must Generate Regression Tests** (2026-03-26): When Monitor (or any review tool) finds a bug, always write a failing test that reproduces the bug BEFORE fixing it, because without a regression test the same bug silently reappears during future refactors. Name tests `test_<function>_<what_was_found>` to serve as living documentation. [workflow: map-learn-improvement]

- **Acceptance Tests Must Assert Observable Side Effects, Not Return Types** (2026-04-20): When testing installation, delivery, or file-writing functions, always assert observable filesystem side effects — specific files exist at correct paths, file content matches expectations, paths that must NOT exist are absent. Never rely on return-value structure alone (counts, dicts). A function can return `{'skills': 5}` while writing to the wrong directory. Include negative assertions for provider isolation (`.claude/` must not exist after codex init). [workflow: map-efficient]
  ```python
  # WEAK — passes even if files written to wrong path
  def test_codex_installs_skills(tmp_path):
      counts = create_codex_files(tmp_path)
      assert counts['skills'] > 0  # wrong-path still passes

  # STRONG — asserts actual observable side effects
  def test_codex_installs_skills(tmp_path):
      create_codex_files(tmp_path)
      assert (tmp_path / '.codex' / 'skills' / 'map-plan' / 'SKILL.md').exists()
      assert not (tmp_path / '.claude').exists()  # negative: provider isolation
  ```

- **Workflow Phase Migration Requires Test Contract Reassignment** (2026-05-12): When a function's responsibility is migrated between workflow phases (e.g., artifact X is no longer created by phase A but is now created by phase B), every existing test that asserts artifact X's presence MUST be audited and reassigned: phase A tests must assert X is ABSENT (negative contract), and new phase B tests assert X is PRESENT. Skipping this leaves tests pinning the old contract and producing false failures against the new valid behavior. In this workflow, `/map-plan` previously created `step_state.json`; that contract moved to `/map-efficient` INIT_STATE. Two `TestMapPlanE2E` tests continued to assert presence and broke against the new design until rewritten as negative-contract assertions. [workflow: map-efficient]
  ```python
  # WRONG — old contract still pinned after responsibility migrated:
  def test_plan_step_state_initialized(map_dir):
      run_map_plan()
      assert (map_dir / 'step_state.json').exists()  # /map-plan no longer creates this

  # CORRECT — realigned to new contract with explanatory message:
  def test_plan_does_not_create_step_state(map_dir):
      run_map_plan()
      assert not (map_dir / 'step_state.json').exists(), (
          'step_state.json must NOT be created by /map-plan; '
          'it is initialized by /map-efficient INIT_STATE'
      )
  ```

- **Prose-Literal Pinned Tests Must Be Rewritten in the Same Commit as Prose Removal** (2026-05-27): When a refactor removes or replaces exact prose strings from skill files, agent prompts, or any text artifact that tests assert verbatim (e.g., `assert 'emit ONLY the JSON envelope' in content`), identify ALL such pinned tests BEFORE writing the refactor commit. The test turns red the instant the prose is gone, making the commit unbuildable mid-edit. Procedure: (1) grep the test suite for every literal string being removed, (2) plan the replacement assertion (structural tag, function name, behavioral property), (3) include the test rewrite in the SAME atomic commit as the prose removal. This is narrower than 'Workflow Phase Migration Requires Test Contract Reassignment' — it applies to any prose removal regardless of phase migration. [workflow: map-efficient]
  ```bash
  # Step 1: Before writing the refactor, grep for the prose being removed:
  grep -r 'emit ONLY the JSON envelope' tests/
  # → tests/test_skills.py:88:    assert 'emit ONLY the JSON envelope' in content

  # Step 2: Plan the structural replacement assertion:
  # Old: assert 'emit ONLY the JSON envelope' in content
  # New: assert '<format_rules>' in retry_prompt  # tag that replaced the prose

  # Step 3: Commit touches BOTH the skill file and the test atomically.

  # WRONG — commit prose removal alone, discover red test after:
  git add skills/monitor.md && git commit -m 'remove prose retry instructions'
  # pytest fails — forced amend or second commit under time pressure
  ```

- **Side-Effect-Only pytest Fixtures Need `del` Suppression, Not Rename** (2026-05-12): When a pytest fixture is used ONLY for its `monkeypatch.chdir` / `monkeypatch.setattr` side effects and the return value is never referenced in the test body, Pyright flags the parameter as `reportUnusedParameter`. The idiomatic fix is `del fixture_name` as the first statement of the body: the name IS referenced (by the del), side effects have already executed, Pyright is satisfied. DO NOT rename to `_fixture_name` — pytest matches fixtures by exact parameter name, so renaming disconnects the injection and the side effects never run. [workflow: map-efficient]
  ```python
  @pytest.fixture
  def branch_workspace(monkeypatch, tmp_path):
      monkeypatch.chdir(tmp_path)
      monkeypatch.setattr('mapify_cli.runner.CWD', tmp_path)
      return tmp_path  # return value unused by some tests

  # WRONG — Pyright flags reportUnusedParameter
  def test_runner_uses_cwd(branch_workspace):
      result = run_command()
      assert result.exit_code == 0

  # WRONG — breaks pytest injection (match-by-name); side effects never run
  def test_runner_uses_cwd(_branch_workspace):
      ...

  # CORRECT — del satisfies Pyright; side effects already applied at this point
  def test_runner_uses_cwd(branch_workspace):
      del branch_workspace
      result = run_command()
      assert result.exit_code == 0
  ```

- **Integration-Test Framework Gates via Real Invocation, Not Just the Pure Function** (2026-05-29): When a framework ships a gate (truncation detector, linter, validator) used both as a library function AND as a CLI invoked by a skill/CI, prove it fires on BOTH paths with real invocation artifacts — a unit test of the pure function is not enough. The contract that breaks silently lives at the integration boundary (stdin pipe, process exit code, classification scope), exactly where the unit test does not reach. In Phase A the truncation gate's pure function was unit-tested and correct, yet the CLI was non-functional in every Task/Agent call because nothing was piped. Add a subprocess test that runs the actual CLI entrypoint with empty stdin, with piped-valid, and with piped-invalid input and asserts the exit/status of each. [workflow: map-efficient]
  ```python
  def _run_gate_cli(stdin_text: str) -> dict:
      proc = subprocess.run(
          [sys.executable, str(SCRIPTS_PATH / "tool.py"), "detect", "--agent", "actor"],
          input=stdin_text, capture_output=True, text=True,
      )
      assert proc.returncode == 0, proc.stderr
      return json.loads(proc.stdout)

  def test_cli_no_input_is_not_a_failure(self):
      assert _run_gate_cli("")["status"] == "no_input"   # bare call ≠ hard stop
  def test_cli_piped_prose_is_flagged(self):
      assert _run_gate_cli("shipping now")["truncated"] is True
  ```

- **Parametrized Tests That Discover Cases From the Filesystem Need a Non-Empty Discovery Guard** (2026-05-29): When a `@pytest.mark.parametrize` list is built by globbing the filesystem (hook files, both dev+template trees, Codex+Claude copies), an empty discovery — from a path typo, missing dir, or accidental exclusion — silently produces ZERO cases and the suite reports green. The invariant is then completely untested while looking covered. Add a standalone sentinel test asserting the discovered list meets a minimum count (and, for multi-tree coverage, that EACH tree contributes), so a vacuous pass becomes a hard failure. [workflow: map-efficient]
  ```python
  HOOK_FILES = glob.glob(".claude/hooks/*.py") + glob.glob(".codex/hooks/*.py")

  def test_hook_discovery_non_empty():  # fails loudly if a glob silently returns []
      claude = [p for p in HOOK_FILES if "/.claude/" in p]
      codex  = [p for p in HOOK_FILES if "/.codex/"  in p]
      assert claude and codex, f"empty discovery — path typo? {HOOK_FILES}"

  @pytest.mark.parametrize("hook_path", HOOK_FILES)  # would pass vacuously on []
  def test_hook_has_guard(hook_path): ...
  ```

- **A Linter That Enforces Gate Invariants Must Ship a `--self-test` Covering Every Failure Mode, Wired Into CI** (2026-05-29): A lint/gate tool that claims to detect violations (missing guard, misplaced guard, forbidden guard, unclassified file) must include a `--self-test` mode that synthesizes one input per failure mode and asserts each exits nonzero, plus a conformant input that exits zero. Without it, the happy-path CI run (no violations present → exit 0) never exercises the detection logic, so a reviewer can only verify enforcement by reading code. Wire the self-test into `make check` or invoke it from pytest via importlib. In Phase A, Monitor caught two uncovered failure modes (FORBID indirect-variable bypass, shell inline-comment) that a self-test would have caught mechanically. [workflow: map-efficient]

- **Config-Flag Default Flip Requires Auditing Incidental-Placeholder Tests vs Contract Tests** (2026-05-30): When flipping the default value of a config flag (e.g., `MAP_MONITOR_HOTFIX` 0→1), audit every test that references the old default and classify each as (a) CONTRACT TEST — the flag's behavior IS what's under test; keep it, update to assert the new default; or (b) INCIDENTAL-PLACEHOLDER — the test merely needed some phase/mode and grabbed this flag's old behavior as a convenient prop; re-point the placeholder to a value that STILL exercises the same gate. In this workflow, flipping `MAP_MONITOR_HOTFIX` to default-ON broke ~13 tests that used the MONITOR phase only because it was non-editing at the time — not because MONITOR gate behavior was the contract under test; the fix re-pointed them to PREDICTOR (still strictly gated) and added one real default-allow test + one `=0` strict opt-out test. Distinct from "Workflow Phase Migration Requires Test Contract Reassignment" (responsibility moves between phases): here the same test breaks because it used the old default as an incidental fixture. [workflow: map-efficient]
  ```python
  # INCIDENTAL-PLACEHOLDER — grabbed MONITOR because it was non-editing:
  def test_setup_phase_blocks_writes(...):
      result = run(phase="MONITOR", action="write")
      assert result.denied  # breaks when MONITOR default flips to allow
  # AFTER AUDIT — re-point to a phase whose gate IS still the invariant:
  def test_setup_phase_blocks_writes(...):
      result = run(phase="PREDICTOR", action="write")  # still gated
      assert result.denied
  # CONTRACT TEST — MONITOR gate behavior IS under test; keep + update:
  def test_monitor_allows_edits_by_default(...): assert run(phase="MONITOR", action="write").allowed
  def test_monitor_strict_opt_out_blocks(monkeypatch):
      monkeypatch.setenv("MAP_MONITOR_HOTFIX", "0")
      assert run(phase="MONITOR", action="write").denied
  ```

- **Guard and Pinning Tests Need a Negative-Proof Run Before Commit** (2026-05-30): Before committing any guard/pinning test (one that asserts a specific string, value, or property IS present to prevent accidental removal), validate it actually catches a violation with a one-off negative-proof run: temporarily break the guarded property, confirm the test goes RED, then restore and confirm GREEN. Without this, a guard test can be structurally valid yet functionally vacuous — a wrong assertion path, mismatched regex, or stale file path makes it pass whether or not the guard holds. Applies to prose-literal pinned tests, sentinel-presence tests, hook-parity tests, and linter self-tests alike. In this workflow a Copilot-requested pinned-prose test was proven by rewording the shipped SKILL.md prose, observing the failure, then restoring clean. Adjacent to but broader than "Prose-Literal Pinned Tests" (update discipline) and "Linter --self-test" (linter-specific). [workflow: map-efficient]
  ```bash
  # Negative-proof protocol before committing a guard test:
  # 1. break the guarded property (sed/edit out the pinned string)
  # 2. pytest <the guard test>   -> confirm FAILED
  # 3. git restore <file>        -> confirm GREEN
  # 4. commit file + test together
  ```

- **Mock-Shape Fidelity to Live API Response Shape: Mock Dict Objects, Not Simplified Primitives** (2026-06-12): When writing tests for code that consumes an external API, mock with the ACTUAL live response shape for every nested field — even fields that appear simple in the feature under test. If the live API returns `tags` as `list[{id, name, description}]` but the test uses `list[str]`, the rendering code that does `', '.join(str(t))` passes all tests yet leaks Python dict reprs (`{'id': 1, 'name': 'python', ...}`) into production output. This mismatch is invisible until live verification. For each field used in the code path under test, look up the actual API schema and replicate the exact JSON shape in the fixture. Test the field-extraction step (e.g. `t['name']` vs `str(t)`) as an explicit unit test with both shapes (string fallback + dict real-shape) so a regression is caught before live exercise. [workflow: map-efficient]
  ```python
  # WRONG — tags mocked as plain strings; passes tests, breaks in production
  MOCK_POST = {
      'title': 'How to use asyncio',
      'tags': ['python', 'asyncio'],          # live API returns dicts, not strings
      'body': 'Use async/await...',
  }
  # Renderer: ', '.join(str(t) for t in post['tags'])
  # => 'python, asyncio' in tests; "{'id':1,'name':'python',...}, ..." in production

  # CORRECT — replicate the actual live API shape in the fixture
  MOCK_POST = {
      'title': 'How to use asyncio',
      'tags': [                               # real shape: list of dicts
          {'id': 1, 'name': 'python', 'description': 'the Python language'},
          {'id': 2, 'name': 'asyncio', 'description': 'async I/O library'},
      ],
      'body': 'Use async/await...',
  }
  # Renderer must extract names explicitly and tolerate both shapes:
  # ', '.join(t['name'] if isinstance(t, dict) else str(t) for t in post['tags'])
  ```

- **Test-Induced Bytecode Cache Pollution in Generated Trees: Suppress Bytecode When Importing Shipped Scripts by Path** (2026-06-12): When a test imports a Python script from a generated (rendered) tree using `importlib.util.spec_from_file_location`, Python writes `__pycache__/*.pyc` files into that tree. Byte-identity tree-walk tests that treat any non-source file as un-rendered then fail — not because anything was incorrectly generated, but because the TEST itself polluted the tree it was validating. Fix at two levels: (1) suppress bytecode writes in the test module (`sys.dont_write_bytecode = True` before the import); (2) exclude `__pycache__/` and `*.pyc` patterns from all tree-walk parity and file-sync checks. The broader lesson: a test that loads source from a tree it is also measuring for purity must be written to be side-effect-free with respect to that tree. This failure mode is triggered by the FIRST language-importable shipped artifact in a tree that previously contained only non-executable files. [workflow: map-efficient]
  ```python
  # WRONG — importing the shipped script leaves __pycache__/*.pyc in the generated tree
  import importlib.util
  spec = importlib.util.spec_from_file_location(
      'sofa_search', '.claude/skills/map-so-search/scripts/sofa_search.py'
  )
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  # => writes .claude/skills/.../scripts/__pycache__/sofa_search.cpython-311.pyc
  # => byte-identity tree-walk test sees stray .pyc, reports render mismatch

  # CORRECT — suppress bytecode before import; exclude __pycache__ in walk helpers
  import sys, importlib.util
  _prev = sys.dont_write_bytecode
  sys.dont_write_bytecode = True
  try:
      spec = importlib.util.spec_from_file_location(
          'sofa_search', '.claude/skills/map-so-search/scripts/sofa_search.py'
      )
      mod = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(mod)
  finally:
      sys.dont_write_bytecode = _prev

  # In tree-walk parity helpers — exclude cache dirs from the walk:
  def _walk_tree(root):
      for p in root.rglob('*'):
          if '__pycache__' in p.parts or p.suffix == '.pyc':
              continue
          yield p
  ```

- **First-Instance of New Artifact Kind Unmasks Hardcoded Count Guards: Derive Expected Sets Dynamically** (2026-06-12): When you add the very first instance of a new file type or artifact kind to a catalog (e.g. the first Python script shipped inside a skill directory), hardcoded count assertions (`assert len(skill_names) == 16`), format-validation tests, and sync-check tests all fail — not because the new artifact is wrong, but because those tests were written against a fixed historical set and never anticipated the new kind. The correct pattern: any test that counts or enumerates catalog members must derive its expected set DYNAMICALLY from the catalog source of truth (e.g. read `skill-rules.json` at test time), never from a hardcoded literal. A test that fails on the addition of a correct, passing artifact is a false gate. [workflow: map-efficient]
  ```python
  # WRONG — hardcoded count breaks the moment a new skill is added
  def test_skill_count():
      rules = json.loads(Path('.claude/skills/skill-rules.json').read_text())
      assert len(rules['skills']) == 16  # breaks when first hybrid skill is registered

  # CORRECT — derive expected set from the catalog dynamically
  def test_all_registered_scripts_exist():
      rules = json.loads(Path('.claude/skills/skill-rules.json').read_text())
      for skill in rules['skills']:
          for effect in skill.get('runtimeEffects', []):
              script = Path('.claude/skills') / skill['name'] / 'scripts' / effect
              assert script.exists(), f"Registered runtimeEffect {script} not found"
      # Count comes from catalog, not a literal — works for N=0, 1, ..., N+1
  ```

- **Blueprint-Named Test Functions Are a Monitor Contract: Author Them in the Same Subtask as the Code** (2026-06-04): When a subtask blueprint's `test_strategy` names specific pytest function names (e.g. `test_vc3_resume_skips_present_cell_ids`), Monitor treats those names as a HARD completeness contract: a subtask whose logic is correct but whose blueprint-named functions do not yet exist gets `valid=false` (hard stop). The completeness unit is code + named-test-functions-together, not code alone — the blueprint author chose the names to specify observable behavior, so an absent name means the behavior is unverified. Never stub a named test with `pass`/`# TODO` and call the subtask done; the stub satisfies the import but not the contract. In this workflow ST-005's runner code was correct but Monitor hard-stopped until the four named VC tests were authored with real assertions. [workflow: map-efficient]

- **Final Verification Must Check Shipped Docs Against Actual Behavior, Then Grep for the Same Drift Class** (2026-06-04): After code+tests are green, a dedicated final-verification pass must validate that user-facing docs (SKILL.md, README, CLI `--help`) match actual behavior: default values, accepted schema formats, flag names, output field names. Prose drift is invisible to pytest/ruff/mypy. When the first drift instance is found, immediately grep the WHOLE doc for the same class of claim (every `--flag default`, every schema example, every accepted file-format mention) before moving on — drift clusters because the doc was written once from a design doc, not from running code. Here the final-verifier caught a `--max-concurrency` default of 4 (actual 1); grepping the same file then surfaced a fictional YAML eval-set schema block + `.yaml` examples that the JSON-only loader could never parse. [workflow: map-efficient]
  ```bash
  # one drift found -> grep the whole doc for the drift class before marking done
  mapify skill-eval --help | grep -i max-concurrency        # actual default
  grep -nE 'default|yaml|schema|--[a-z-]+' docs/SKILL.md     # reconcile every claim
  ```

- **Snapshot-Before-Mutate: Tautological File-Comparison Tests Must Capture State Before In-Place Operations** (2026-06-21): When a test verifies that an in-place operation (render, format, migration) actually changed a file, compare PRE-operation bytes to POST-operation bytes — never the post-operation file to itself. `filecmp.cmp(path, path)` (or reading the file twice after the operation) is always True regardless of whether the operation did anything, because both sides read the same post-mutation content. Capture `path.read_bytes()` BEFORE the operation, then compare to `read_bytes()` after — a no-op render now fails the test, which is the correct stale-tree signal. [workflow: map-efficient]
  ```python
  # WRONG — always-True tautology; never detects a broken/no-op render
  render_templates(tmp); assert filecmp.cmp(committed, committed)   # same file both sides
  # CORRECT — snapshot before the in-place mutation
  snapshot = committed.read_bytes()        # BEFORE
  render_templates(tmp)
  assert committed.read_bytes() != snapshot, "render should have updated the stale file"
  ```

- **Shared-Fixture Edits Need an Aggregate Suite Run at the Origin Subtask, Not Deferred to Whichever Later Subtask Notices** (2026-07-02): When a subtask edits a shared config/fixture source (e.g. config.toml.jinja consumed by a golden-fixture test elsewhere), running only that subtask's OWN scoped/targeted tests is insufficient even though it's the correct fast-iteration default — the drift it introduces into a golden fixture used by a DIFFERENT, unrelated test can lie dormant for multiple subsequent subtasks until something finally runs the full aggregate suite. In one workflow, two early subtasks registered new agents in a shared config.toml.jinja and both passed their own scoped tests cleanly, but a golden fixture asserted against by an unrelated test only surfaced as stale 4 subtasks later, when the full aggregate pytest suite finally ran. The origin subtask and the surfacing subtask were different, purely due to test-run granularity, not code causality. Rule: any subtask whose affected_files include a file consumed by golden/snapshot fixtures elsewhere in the repo should trigger at least one full aggregate suite run before that subtask closes, not defer it to whichever later subtask happens to run the full suite first. Distinct from "Targeted Per-File Checks Are Not a Substitute for the Full Aggregate Lint Gate" (that rule is about lint scope within ONE subtask); this is about a defect's ORIGIN subtask being different from its SURFACING subtask purely because the aggregate suite wasn't run until later. [workflow: map-efficient]
  ```bash
  # Subtask edits a shared render source (e.g. config.toml.jinja):
  # WRONG -- only scoped tests, golden fixture drift goes undetected for N subtasks:
  pytest tests/test_config_toml_render.py -x -q   # passes; fixture staleness invisible

  # CORRECT -- grep affected_files against known golden-fixture consumers, then run aggregate:
  grep -rl 'fixtures/codex/config.toml' tests/   # finds the golden-fixture test
  pytest tests/ -x -q                             # full suite -- catches it at the origin
                                                   # subtask, not N subtasks later
  ```

- **Argv Token Membership, Never Substring-in-Joined-String, for "Bad Command Not Called" Assertions** (2026-07-03): When a test asserts that a list of discrete tokens (subprocess argv, CLI flags, path segments) does NOT contain any of a set of "bad" values, check list/token membership directly (`bad not in call`) — never flatten the list to a string first (`bad not in " ".join(call)`). Flattening changes the check from "is this exact token present" to "does this substring occur anywhere in the concatenated text", which also matches incidental fragments inside unrelated data: file paths, UUIDs, tmp directory names, commit SHAs. This produces environment-dependent flakiness — a test failed on macOS CI only because pytest's `tmp_path` fixture happened to generate a random directory name containing the banned substring "rm" (e.g. `cx43xdqhzy2rmp6tqr`), inside an unrelated git-worktree path argument, not as an actual `rm` subcommand invocation. [workflow: map-release]
  ```python
  # WRONG: substring-in-joined-string check — false positive when tmp_path contains 'rm'
  for call in recorded_calls:
      joined = " ".join(call)
      for bad in ("checkout", "stash", "reset", "restore", "commit", "rm"):
          assert bad not in joined
          # e.g. call = ['git', 'worktree', 'add', '--detach',
          #              '/tmp/pytest-x/cx43xdqhzy2rmp6tqr/', 'abc123']
          # joined contains 'rm' inside 'cx43xdqhzy2rmp6tqr' -> assertion fails on CI only

  # CORRECT: token-list membership — checks discrete elements, immune to substring noise
  for call in recorded_calls:
      for bad in ("checkout", "stash", "reset", "restore", "commit", "rm"):
          assert bad not in call  # 'rm' as a whole argv element, not a text fragment
  ```
