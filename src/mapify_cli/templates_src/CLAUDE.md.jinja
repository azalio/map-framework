# MAP Framework (mapify-cli) — Agent Instructions

## What this repo is

- **Purpose:** `mapify` is a Python 3.11+ CLI that installs the MAP Framework into a target project (it writes `.claude/` skill-backed slash surfaces/config and `.map/` workflow artifacts).
- **Runtime code:** `src/mapify_cli/`
- **Bundled templates (what users get from `mapify init`):** `src/mapify_cli/templates/`
- **Dev templates/config used in this repo:** `.claude/` (keep it in sync with `src/mapify_cli/templates/`)

## Critical invariant: template single-source render

All shipped templates are generated from `src/mapify_cli/templates_src/**/*.jinja` via `make render-templates`. Never edit generated files directly — edit the `.jinja` source and re-render.

Generated trees (do NOT edit directly):
- `src/mapify_cli/templates/**`
- `.claude/**`
- `.codex/**`
- `.agents/skills/**`

To propagate any change to shipped templates:
- `make render-templates`

Verification:
- Run `make check-render` (renders and asserts no diff — enforces generated trees match source).
- Run `pytest tests/test_template_render.py -v` (byte-identity golden render tests).

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
