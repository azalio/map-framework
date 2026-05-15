# Command Patterns (Learned)

<!-- IMPROVEMENT-PLAN-LOOP: promoted from loop learnings. Edit freely and commit with the project. -->

- **Use repo-built init for template verification** (2026-04-13): When validating shipped MAP templates, always run `uv run mapify init <new-dir> --no-git --mcp none` because the globally installed `mapify` binary may still reflect an older release instead of the branch you are reviewing. [workflow: improvement-plan-loop]
- **Use non-existent target paths for init smoke tests** (2026-05-15): `mapify init <path>` creates the target directory, so do not pre-create it with `mktemp -d`; pass a unique path under an existing temp parent and then inspect the generated `.claude/` artifacts. [workflow: improvement-plan-loop]
- **Grep stale skill names during taxonomy changes** (2026-05-15): When skill catalog docs change, search for removed or non-shipped skill names such as `map-workflows-guide` and `map-cli-reference`; generated install smoke tests prove current templates emit metadata, but they do not catch every stale prose reference. [workflow: improvement-plan-loop]
