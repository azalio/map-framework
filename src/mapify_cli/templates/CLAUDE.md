# MAP Framework (mapify-cli) — Agent Instructions

## What this repo is

- **Purpose:** `mapify` is a Python 3.11+ CLI that installs the MAP Framework into a target project (it writes `.claude/` prompts/config and `.map/` workflow artifacts).
- **Runtime code:** `src/mapify_cli/`
- **Bundled templates (what users get from `mapify init`):** `src/mapify_cli/templates/`
- **Dev templates/config used in this repo:** `.claude/` (keep it in sync with `src/mapify_cli/templates/`)

## Critical invariant: template synchronization

If you change anything under `.claude/` that is shipped to users, you MUST copy it to the matching path under `src/mapify_cli/templates/` before finishing.

Common synced paths:
- `.claude/agents/` → `src/mapify_cli/templates/agents/`
- `.claude/commands/` → `src/mapify_cli/templates/commands/`
- `.claude/hooks/` → `src/mapify_cli/templates/hooks/`
- `.claude/references/` → `src/mapify_cli/templates/references/`
- `.claude/settings.json`, `.claude/workflow-rules.json` → `src/mapify_cli/templates/`

Do the sync via a deterministic command (preferred):
- `make sync-templates` (runs `scripts/sync-templates.sh`)

Verification:
- Run `pytest tests/test_template_sync.py -v` (enforces agent template sync).
- For other `.claude/` files, use `git diff`/`git status` to ensure the template copy was updated too.

## How to work in this repo

- Prefer deterministic tooling over “manual review”: run `make check` (or `make lint` / `make test`) after changes.
- When changing user-facing behavior, also update relevant docs:
  - `README.md` (quick-start)
  - `docs/USAGE.md` (workflows and CLI usage)
  - `docs/ARCHITECTURE.md` (system design / agents)
- For releases, follow `RELEASING.md` and update `CHANGELOG.md`.

## Safety expectations

- Don't add or expose secrets. Avoid reading/writing `.env*` and credential/key files.

## Bash Command Guidelines

**CRITICAL:** Avoid output buffering issues that cause commands to hang.

### ❌ DO NOT use these patterns:
```bash
command | head -n X    # Causes buffering, output hangs
command | tail -n X    # Causes buffering, output hangs
command | less         # Interactive, causes issues
command | more         # Interactive, causes issues
```

### ✅ DO use these patterns instead:
```bash
# Use command-specific flags
git log -n 10                  # Not: git log | head -10
git log --max-count=10

# Let commands complete fully
pytest                         # Don't truncate
make test                      # Don't truncate

# Read files directly
head -n 10 logfile.txt         # Direct file read is OK
cat file.txt                   # Then process in memory
```

### Why this matters:
When you pipe through `head/tail/less/more`, the source command keeps running but output buffers indefinitely. This makes commands appear "hung" when they're actually waiting for the pipe to complete.

**Exception:** Filtering pipes are OK (grep, awk, sed) because they process all input.

**Full guidelines:** `.claude/references/bash-guidelines.md`

## Progressive disclosure pointers

- Architecture deep dive: `docs/ARCHITECTURE.md`
- Usage/workflows: `docs/USAGE.md`
- Release process: `RELEASING.md`
