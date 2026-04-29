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

| Hook | Event | Blocking? | Purpose |
|------|-------|-----------|---------|
| `safety-guardrails.py` | `PreToolUse` (Edit/Write/Read/MultiEdit/Bash) | Yes (JSON deny) | Block sensitive files, dangerous commands |
| `workflow-gate.py` | `PreToolUse` (Edit/Write/MultiEdit) | Yes (JSON deny) | Enforce Actor+Monitor workflow before edits |
| `workflow-context-injector.py` | `PreToolUse` (Edit/Write/Bash) | No | Inject MAP workflow reminder |
| `ralph-iteration-logger.py` | `PostToolUse` | No | Log iterations, detect file thrashing |
| `ralph-context-pruner.py` | `PreCompact` | No | Save restore point, prune logs |
| `pre-compact-save-transcript.py` | `PreCompact` | No | Save full conversation transcript |
| `post-compact-context.py` | `SessionStart` (compact) | No | Inject restore-point context |
| `end-of-turn.sh` | `Stop` | No | Auto-fix lint/format silently |
| `detect-clarification-triggers.py` | `UserPromptSubmit` | No | Detect "ask if unclear" + async/durability language |

Last reviewed: 2026-04-28.
