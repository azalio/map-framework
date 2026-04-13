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

