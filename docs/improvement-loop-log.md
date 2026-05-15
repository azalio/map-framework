## 2026-04-13 - Official-frontmatter hygiene for MAP skills [2604.031]

- Decision: `implemented`
- Branch: `codex/2604-031-skill-frontmatter`
- Baseline: `map-planning` shipped with a 371-character description that referenced non-existent `map-workflows-guide` and `map-cli-reference` surfaces, `map-learn` had no argument hint for manual invocation, and no test failed on those metadata regressions.
- Forward Change: Shortening the two shipped skill descriptions, adding `argument-hint: "[workflow-summary]"` to `map-learn`, and adding dedicated metadata lint tests closed the actual UX gaps without pulling the whole stale skill taxonomy into scope.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py tests/test_command_templates.py -v` passed, and `uv run mapify init <new-dir> --no-git --mcp none` generated the updated skill frontmatter in a throwaway project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/`, `src/mapify_cli/templates/skills/`, or the installer copy path and you need to prove the generated project reflects the branch state.
- Reusable Learnings:
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `When changing shipped skill metadata, keep descriptions under 250 characters and make every map-* reference resolve to a real shipped command or skill.`
  - gotcha: `The globally installed mapify binary can lag behind the branch under test and show stale templates even when the repo diff is correct.`
  - review-check: `For manual slash skills, always verify the frontmatter exposes an argument hint before shipping catalog changes.`

## 2026-05-15 - Skill trigger and invocation regression testing [2604.034]

- Decision: `implemented`
- Branch: `codex/2604-034-skill-invocation-tests`
- Baseline: `test_skills.py` validated basic skill frontmatter and sync, but did not prove `skill-rules.json` manual invocation metadata matched `SKILL.md`, did not require direct slash names in trigger rules, did not test selected negative-trigger fixtures, and did not verify relative supporting links, supporting-file template sync, or `CLAUDE_PLUGIN_ROOT` hook commands.
- Forward Change: Added those catalog integrity checks and corrected `map-learn` from suggested domain skill to manual slash skill in both development and shipped template metadata.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v` passed, `pytest -m "not slow"` passed, and `uv run mapify init <temp-dir> --no-git --mcp none` emitted manual `map-learn` metadata plus bundled rule templates in a generated project.
- Next Trigger: Reuse this learning whenever a change touches `.claude/skills/skill-rules.json`, skill frontmatter, hook metadata, or Markdown links to files bundled under a skill directory.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `A skill with manual slash invocation must have an argument-hint and its direct map-* name in skill-rules keywords and intent patterns.`
  - invariant: `Relative Markdown links, non-SKILL supporting files, and CLAUDE_PLUGIN_ROOT hook commands must resolve and stay synced before template release.`
  - gotcha: `When linting Markdown links in skill bodies, strip fenced code blocks first so regex snippets like [ =]([0-9]+) are not mistaken for Markdown links.`

## 2026-05-15 - Explicit reference-vs-task skill architecture [2604.032]

- Decision: `implemented`
- Branch: `codex/2604-032-skill-taxonomy`
- Baseline: The shipped skills README still said skills were passive documentation only, referenced non-existent `map-workflows-guide`, and `skill-rules.json` had no machine-readable way to distinguish task workflows from reference guidance or `map-state` hook side effects.
- Forward Change: Added `skillClass` metadata, classified MAP slash workflows as `task`, classified `map-state` as `hybrid` with `runtimeEffects`, rewrote skill taxonomy docs, removed stale skill references, and added regression tests for task/reference/hybrid boundaries.
- Decisive Validation: `pytest tests/test_skills.py tests/test_template_sync.py -v`, `pytest -m "not slow"`, and `make lint` passed. `uv run mapify init <new-dir> --no-git --mcp none` emitted `map-state` as `hybrid`, `map-learn` as `task`, and the generated skills README included the taxonomy.
- Next Trigger: Reuse this learning whenever a change adds, removes, or reclassifies a shipped skill, especially if it changes manual invocation, hooks, scripts, or file-writing behavior.
- Reusable Learnings:
  - command: `pytest tests/test_skills.py tests/test_template_sync.py -v`
  - command: `uv run mapify init <new-dir> --no-git --mcp none`
  - invariant: `Every shipped skill-rules.json entry must declare skillClass as reference, task, or hybrid.`
  - invariant: `Task skills must be manual slash workflows; reference skills must not hide manual invocation, hooks, or runtime effects; hybrid skills must declare runtimeEffects.`
  - gotcha: `Docs can retain stale skill names even after catalog tests pass; grep for removed/non-shipped skill names such as map-workflows-guide and map-cli-reference when changing skill taxonomy.`
