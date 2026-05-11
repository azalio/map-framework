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
