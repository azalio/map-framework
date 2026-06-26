# MAP Hooks — Rules of the Road

This directory contains Claude Code hook scripts wired in via
`.claude/settings.json`. The conventions below are non-negotiable for any
new or modified hook.

## Exit codes

Per the official Claude Code hook docs, **only exit code 2 blocks the
action** for most hook events. Any other non-zero exit (including `1`) is
treated as a **non-blocking error** — Claude logs a warning and proceeds.

This means:

- **Never use `sys.exit(1)` to block.** It silently fails closed (the
  blocked tool runs anyway).
- To block: emit a JSON `permissionDecision: "deny"` via stdout AND/OR
  use `sys.exit(2)`. The current MAP hooks (`safety-guardrails.py`,
  `workflow-gate.py`) use the JSON approach exclusively — follow that
  pattern.
- For informational hooks (the majority — `workflow-context-injector.py`,
  `detect-clarification-triggers.py`, etc.): **always exit 0** and emit
  context via `hookSpecificOutput.additionalContext`.

Audited 2026-04-28: every existing hook in this directory exits 0 and
delegates blocking decisions to stdout JSON. No `sys.exit(1)` blocks
anywhere. Keep it that way.

## Special case: `WorktreeCreate`

Per the docs, `WorktreeCreate` blocks on **any** non-zero exit. None of
the current MAP hooks target this event, but if a future hook does:
explicit `sys.exit(0)` is mandatory unless intent is to block.

## JSON output schema (PreToolUse)

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",          // or "allow", "ask", "defer"
    "permissionDecisionReason": "<why>"
  }
}
```

For non-PreToolUse events (e.g., `UserPromptSubmit`, `SessionStart`):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "<event-name>",
    "additionalContext": "<text injected into Claude's context>"
  }
}
```

Output is capped at 10,000 characters by Claude Code — keep messages
terse.

## Multi-hook precedence

When multiple hooks fire on the same event, decisions resolve as:

```
deny  >  defer  >  ask  >  allow
```

Practical implication: a single `deny` from any hook in the chain wins,
even if other hooks in the chain return `allow`. This is why MAP layers
`safety-guardrails.py` (always-on file/command blocklist) before
`workflow-gate.py` (workflow-state gate) — neither can override the
other's deny.

## Inputs

All hooks receive a JSON payload via stdin. Common fields:

- `session_id`, `transcript_path`, `cwd`, `permission_mode`,
  `hook_event_name`
- `agent_id`, `agent_type` — present only when the hook fires inside a
  subagent context

Event-specific fields (e.g., `tool_name`, `tool_input`, `prompt`) are
documented per event in the official Claude Code docs.

## Hook inventory

All 16 hooks (15 `.py` + `end-of-turn.sh`) are classified against the
`MAP_INVOKED_BY` recursion-guard contract. **REQUIRE_GUARD** hooks early-exit
when MAP spawns a nested subprocess; **FORBID_GUARD** hooks must always fire
and may not carry the guard. Full contract and per-hook rationale:
[`../references/hook-patterns.md`](../references/hook-patterns.md). The
classification is enforced by `scripts/lint-hooks.py` (in `make lint` /
`make check`).

| Hook | Event | Blocking? | Class | Purpose |
|------|-------|-----------|-------|---------|
| `safety-guardrails.py` | `PreToolUse` (Edit/Write/Read/MultiEdit/Bash) | Yes (JSON deny) | FORBID_GUARD | Block sensitive files, dangerous commands |
| `workflow-gate.py` | `PreToolUse` (Edit/Write/MultiEdit) | Yes (JSON deny) | FORBID_GUARD | Enforce Actor+Monitor workflow before edits |
| `post-compact-context.py` | `SessionStart` (compact) | No | FORBID_GUARD | Inject restore-point context (re-prime after compaction) |
| `context-meter.py` | `UserPromptSubmit` | No | REQUIRE_GUARD | Nudge `/compact <focus>` when the token threshold is crossed |
| `map-token-meter.py` | `SubagentStop` + `Stop` | No | REQUIRE_GUARD | Attribute per-turn token usage to the active MAP subtask |
| `workflow-context-injector.py` | `PreToolUse` (Edit/Write/Bash) | No | REQUIRE_GUARD | Inject MAP workflow reminder |
| `ralph-iteration-logger.py` | `PostToolUse` | No | REQUIRE_GUARD | Log iterations, detect file thrashing |
| `ralph-context-pruner.py` | `PreCompact` | No | REQUIRE_GUARD | Save restore point, prune logs |
| `pre-compact-save-transcript.py` | `PreCompact` | No | REQUIRE_GUARD | Save full conversation transcript |
| `detect-clarification-triggers.py` | `UserPromptSubmit` | No | REQUIRE_GUARD | Detect "ask if unclear" + async/durability language |
| `end-of-turn.sh` | `Stop` | No | REQUIRE_GUARD | Auto-fix lint/format silently |
| `scrub-internal-ids.py` | `Stop` | No | REQUIRE_GUARD | On `WORKFLOW_COMPLETE`, strip leaked `ST-`/`AC-`/`VC-`/`INV-`/`HC-` IDs from run-changed code and commit the cleanup (gated, runs once) |
| `map-memory-capture.py` | `Stop` | No | REQUIRE_GUARD | Append per-turn scratch WAL record (cross-session memory) |
| `map-memory-endmark.py` | `SessionEnd` | No | REQUIRE_GUARD | Best-effort 'ended' marker for the session WAL |
| `map-memory-finalize.py` | `SessionStart` | No | REQUIRE_GUARD | Finalize prior dirty session scratches into digests (claude -p) |
| `map-memory-recall.py` | `SessionStart` + `UserPromptSubmit` | No | REQUIRE_GUARD | Inject ranked recalled session memory (additionalContext) |

> The Codex twin `.codex/hooks/workflow-gate.py` is FORBID_GUARD like its
> Claude counterpart; this inventory covers `.claude/hooks/` only.

Last reviewed: 2026-05-29.
