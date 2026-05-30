# Context Compression — Implementation Plan

Status: shipped (PR #104)
Owner: azalio
Last updated: 2026-04-30

## Decisions (locked)

- Default threshold: **fixed `120_000`** for v1. Model-aware deferred to v2.
- `aggressive` policy: **`0.4 × threshold`** multiplier (≈48k at default). No
  separate absolute number.
- Codex provider: **ship now** with stderr warning from the orchestrator. A
  dedicated `context-summarizer` agent for Codex is a follow-up, not a blocker.

## Goal

Add a token-aware context-compaction policy to MAP Framework. Users choose between
"never compact" (quality-leaning) and "auto compact at threshold" (cost-leaning).
Implementation is provider-agnostic (works for both Claude Code and Codex providers).

## Key research findings (drives the design)

1. **A hook cannot programmatically run `/compact`.** Claude Code's `PreCompact` event
   fires *after* compaction is initiated; there is no documented hook output that
   triggers `/compact`. Reference: https://code.claude.com/docs/en/hooks.
2. **`/compact` accepts free-form instructions** as `\/compact <text>`. The text
   arrives in `PreCompact` hook stdin as `custom_instructions`.
3. **Built-in auto-compact** fires at ~83.5% of context window, configurable via env
   `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (1–100). It is a *floor* safety net, too late for
   quality preservation.
4. **Token counts** are not surfaced to hooks. The reliable source is the
   `transcript_path` JSONL: sum
   `usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens`
   from the **last assistant entry**. `tiktoken` is wrong for Claude (different
   tokenizer); the Anthropic SDK is canonical.
5. **Long-context degradation** ([Chroma "Context Rot"](https://research.trychroma.com/context-rot),
   Anthropic engineering posts) starts well before window limits — on 200k models
   noticeable degradation can begin around ~50k for semantically distant queries; on
   Opus 1M, problems begin at ~20% utilization.

## Design

Since hooks cannot trigger `/compact`, we use a **soft-trigger / assertive nudge**:
when threshold is crossed, a `UserPromptSubmit` hook injects an `additionalContext`
block that instructs the assistant to run `/compact <focus>` itself. Reliable in
practice and consistent with how MAP already steers the assistant via
`mandatory_next_action` in `step_state.json`.

### Defaults

| Field                          | Default                                                                                        |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| `compression_policy`           | `"auto"` — accepted: `never` / `auto` / `aggressive`                                           |
| `compression_threshold_tokens` | `120_000` (~60% of Sonnet-200k; below Chroma-observed degradation zone)                        |
| `compression_focus`            | `"MAP step state, last 2 monitor verdicts, pending subtasks; drop tool-result bodies older than 3 turns"` |

`aggressive` reuses the same trigger but with `0.4 × threshold` (~48k).

### Why 120k

- Sonnet-200k: 120k = ~60%, safely below built-in 83.5% auto-compact floor.
- Opus-200k: same.
- Opus/Sonnet 1M: project-level override to 250k recommended (above that, Anthropic's
  own data shows quality and cost both turn unfavorable).
- Conservative single-number default avoids needing model detection in v1.

## Implementation steps

Each step lands as its own commit. Order is enforced by dependencies.

### 1. `src/mapify_cli/token_budget.py` — pure module

Functions:

- `count_last_turn_tokens(transcript_path: Path) -> int`
  Parses JSONL, walks from the end, returns the sum of `input_tokens +
  cache_read_input_tokens + cache_creation_input_tokens` from the most recent
  assistant entry. Returns `0` if no assistant entry yet.
- `effective_threshold(config) -> int` — handles `aggressive` multiplier.
- `format_compact_instruction(config, used, threshold) -> str`
  Returns the ready-to-paste `/compact <focus>` line plus a one-line preface
  ("Context is at X / Y tokens (Z%) — MAP policy=auto requires compaction now.").

Tests: `tests/test_token_budget.py` with fixture JSONL containing known `usage`
blocks. Cover: missing transcript, empty transcript, only-user entries, multi-turn,
malformed lines.

### 2. Extend `MapConfig` in `src/mapify_cli/config/project_config.py`

Add three fields with the defaults above. Validate `compression_policy` value.
Update `generate_default_config()` with commented examples.

### 3. New hook `.claude/hooks/context-meter.py`

- Event: `UserPromptSubmit`.
- Reads `transcript_path` from stdin JSON.
- Loads policy/threshold from `.map/config.yaml`.
- If `policy == "never"` → exit 0 silently.
- If `used >= threshold` AND no recent `last-compact.marker` (< 5 min old) →
  emits `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
  "additionalContext": "<warning + /compact line>"}}`.
- Registered in `.claude/settings.json`.

### 4. Cooldown marker in `pre-compact-save-transcript.py`

Append `last-compact.marker` (UTC timestamp) write into the existing PreCompact
hook so that `context-meter.py` does not nudge again immediately after built-in
auto-compact at 83.5% has just finished.

### 5. Orchestrator integration (Codex-friendly)

In `src/mapify_cli/templates/map/scripts/map_orchestrator.py`, between MAP phases,
call `token_budget.count_last_turn_tokens()` against the latest known transcript
location and emit the same warning to stderr. This path matters for the Codex
provider, which has no Claude Code hooks. For Codex we cannot run `/compact` at
all — print a recommendation to invoke a yet-to-be-added `context-summarizer`
agent (out of scope for this plan; document as follow-up).

### 6. `mapify init` flags

In `src/mapify_cli/__init__.py`, extend the `init` command with:

- `--compression {auto,never,aggressive}` (default: `never` — opt-in only;
  the original plan shipped `auto` but unsolicited nudges on long
  workflows hurt UX, so the default was flipped 2026-05-24)
- `--compression-threshold INT` (default: `120000`)

Both are written into `.map/config.yaml` at init time.

### 7. Template sync

Run `make render-templates`. If the new hook does not propagate to
`src/mapify_cli/templates/hooks/`, update the matching `.jinja` source in `templates_src/hooks/`. Verify with
`pytest tests/test_template_render.py -v`.

### 8. Full test pass

`make check` (lint + tests) must be green.

### 9. Docs

- `docs/USAGE.md` — new section "Context budget" with the three policies and an
  example of overriding the threshold for Opus 1M.
- `README.md` — one-line mention in quick-start.
- `CHANGELOG.md` — entry under `Unreleased`.

## Explicitly out of scope

- Replacing or disabling Claude Code's built-in 83.5% auto-compact — it stays as a
  floor safety net.
- Networked `anthropic.messages.count_tokens()` calls — JSONL `usage` blocks are
  sufficient and offline.
- `tiktoken` integration — wrong tokenizer for Claude.
- Custom Codex-side summarizer agent — separate plan.

## Resolved questions

1. Default threshold → fixed `120_000` for v1; revisit model-aware in v2.
2. `aggressive` policy → multiplier `0.4 ×` of `compression_threshold_tokens`.
3. Codex story → ship orchestrator stderr warning now; summarizer agent is a
   follow-up issue.
