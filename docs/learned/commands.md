# Command Patterns (Learned)

<!-- IMPROVEMENT-PLAN-LOOP: promoted from loop learnings. Edit freely and commit with the project. -->

- **Use repo-built init for template verification** (2026-04-13): When validating shipped MAP templates, always run `uv run mapify init <new-dir> --no-git --mcp none` because the globally installed `mapify` binary may still reflect an older release instead of the branch you are reviewing. [workflow: improvement-plan-loop]

