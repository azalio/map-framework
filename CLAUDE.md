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
- `.claude/settings.json`, `.claude/settings.hooks.json`, `.claude/workflow-rules.json` → `src/mapify_cli/templates/`

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

- Don’t add or expose secrets. Avoid reading/writing `.env*` and credential/key files.
- When changing playbook/pattern storage behavior, keep Curator-mediated writes (see `.claude/agents/curator.md` and `docs/ARCHITECTURE.md`).

## Progressive disclosure pointers

- Architecture deep dive: `docs/ARCHITECTURE.md`
- Usage/workflows: `docs/USAGE.md`
- Release process: `RELEASING.md`
