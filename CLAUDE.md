# MAP Framework (mapify-cli) — Agent Instructions

## What this repo is

- **Purpose:** `mapify` is a Python 3.11+ CLI that installs the MAP Framework into a target project (it writes `.claude/` skill-backed slash surfaces/config and `.map/` workflow artifacts).
- **Runtime code:** `src/mapify_cli/`
- **Bundled templates (what users get from `mapify init`):** `src/mapify_cli/templates/`
- **Dev templates/config used in this repo:** `.claude/` (keep it in sync with `src/mapify_cli/templates/`)

## Critical invariant: template synchronization

If you change anything under `.claude/` that is shipped to users, you MUST copy it to the matching path under `src/mapify_cli/templates/` before finishing.

Common synced paths:
- `.claude/agents/` → `src/mapify_cli/templates/agents/`
- `.claude/commands/` → `src/mapify_cli/templates/commands/` (custom-command scaffolding only; MAP `/map-*` surfaces live in skills)
- `.claude/skills/` → `src/mapify_cli/templates/skills/`
- `.claude/hooks/` → `src/mapify_cli/templates/hooks/`
- `.claude/references/` → `src/mapify_cli/templates/references/`
- `.claude/settings.json`, `.claude/workflow-rules.json` → `src/mapify_cli/templates/`

Do the sync via a deterministic command (preferred):
- `make sync-templates` (runs `scripts/sync-templates.sh`)

Verification:
- Run `pytest tests/test_template_sync.py -v` (enforces agent template sync).
- For other `.claude/` files, use `git diff`/`git status` to ensure the template copy was updated too.

## Skill catalog invariant

When changing shipped skills, keep `.claude/skills/skill-rules.json` and `src/mapify_cli/templates/skills/skill-rules.json` explicit about `skillClass`:
- `task` for manual slash workflows that may call agents, run checks, or write artifacts.
- `reference` for guidance-only skills with no manual invocation, hooks, or runtime effects.
- `hybrid` only when reference guidance ships hooks/scripts or artifact side effects; list `runtimeEffects`.

Validation:
- Run `pytest tests/test_skills.py tests/test_template_sync.py -v`.
- Run `uv run mapify init <new-temp-path> --no-git --mcp none` and inspect generated `.claude/skills/skill-rules.json` for shipped metadata changes.

## How to work in this repo

- Prefer deterministic tooling over “manual review”: run `make check` (or `make lint` / `make test`) after changes.
- When changing scripts, hooks, CLIs, or generated provider surfaces, test both negative/no-op paths and positive paths with realistic inputs. A hook returning `{}` proves only the silent path; also build minimal state/artifacts that should trigger its intended output or side effect.
- When changing user-facing behavior, also update relevant docs:
  - `README.md` (quick-start)
  - `docs/USAGE.md` (workflows and CLI usage)
  - `docs/ARCHITECTURE.md` (system design / agents)
- For releases, follow `RELEASING.md` and update `CHANGELOG.md`.

## Safety expectations

- Don't add or expose secrets. Avoid reading/writing `.env*` and credential/key files.

## MAP Workflow Rules

- If **Monitor** returns `valid=false`, treat it as a **hard stop**: fix the issues before proceeding.
  - Do NOT dismiss Monitor feedback as "out of scope" / "separate task".
  - If you're unsure whether fixing it is in scope: ask the user explicitly and wait for a decision.

## Fix every surfaced error — no exceptions

- Every error surfaced by ANY tool during a workflow must be fixed before the workflow can complete. This includes:
  - `make lint`, `make check`, `make test`, `pytest`, `ruff`, `mypy`
  - **IDE / type-checker diagnostics surfaced in the conversation** (Pyright, Pylance, language-server diagnostics)
  - Hook output and tool-result diagnostics
- "Pre-existing" is NOT a valid reason to skip. If the diagnostic surfaces in the current run, it is current.
- "Not in the CI gate" is NOT a valid reason to skip. The error is real if any tool reported it.
- "Static-analysis noise" is NOT a category. Either the type system is correct and the code is wrong, or the annotation needs fixing — pick one and fix it.
- Only legitimate skip: the user explicitly approves deferral in the current conversation. Document the deferral in writing.

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

### Git commands: do NOT use `-C` when already in the repo

When the working directory is already this repository, run git commands **without** the `-C` flag:

```bash
# ✅ Correct (working directory is already the repo):
git status
git diff
git log -n 5

# ❌ Wrong (redundant -C triggers permission prompts):
git -C /path/to/map-framework status
git -C /path/to/map-framework diff
```

**Full guidelines:** `.claude/references/bash-guidelines.md`

## Progressive disclosure pointers

- Architecture deep dive: `docs/ARCHITECTURE.md`
- Usage/workflows: `docs/USAGE.md`
- Release process: `RELEASING.md`
