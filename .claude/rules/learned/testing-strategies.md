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
