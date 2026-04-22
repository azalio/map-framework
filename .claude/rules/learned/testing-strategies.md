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
