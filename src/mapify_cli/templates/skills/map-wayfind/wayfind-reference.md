# /map-wayfind Supporting Reference

Detail for `/map-wayfind` so the invoked `SKILL.md` stays focused on the active flow. All operations go through `python3 .map/scripts/wayfind_runner.py <command>`; each prints a JSON result with a `status` of `success` or `error`.

## Ticket types

| Type | Meaning | Human-in-the-loop | Counts toward one-per-session |
|------|---------|-------------------|-------------------------------|
| `research` | Find out an answer that already exists (read code/docs, run a query). A subagent may do this. | No | No — resolve as many as you learn |
| `prototype` | Build a cheap, throwaway probe to see how an approach feels, then get the human's read. | Yes | Yes |
| `grilling` | Interrogate the human: ask the sharp question, capture their verbatim answer. | Yes | Yes |
| `task` | A self-contained decision or chore you can settle yourself. | No | Yes |

Human-in-the-loop (`prototype`, `grilling`) tickets cannot be resolved until a verbatim human answer is recorded with `record_human_input`.

## Fog-sharpness rubric

Create a ticket only when the concern passes the sharpness test — otherwise keep it as fog and graduate it later.

- **Sharp (make a ticket):** you can state it as ONE question with a bounded answer space, and you know what "resolved" looks like. E.g. "Do we store sessions in Redis or Postgres?"
- **Foggy (keep as fog):** you can only gesture at an area of unease, the question would be compound, or you cannot yet say what a good answer is. E.g. "auth and the new checkout probably interact somehow."
- When a session's work makes a foggy area sharp, `graduate_fog` it into a ticket.

## Command reference

Lifecycle / read-only:

```bash
create_wayfind_map <slug> "<title>" "<destination>" [--notes "..."] [--fog-json '["...", "..."]']
wayfind_status [--slug <slug>]          # no slug: list all maps; with slug: counts + handoff_eligible
list_handoffs                           # completed handoffs (used by /map-plan's offer)
show_ticket <slug> <ticket_id>
wayfind_frontier <slug>                 # open + unblocked + unclaimed tickets, creation order
```

Tickets:

```bash
add_ticket <slug> "<title>" <type> "<sharp question>" [--blocked-by-json '["T-001"]'] [--from-fog F-1]
wire_blocking <slug> <ticket_id> '["T-001","T-002"]'   # rejects unknown ids, self-block, cycles
claim_ticket <slug> <ticket_id> <session>              # HITL types return hitl_pending: true
release_ticket <slug> <ticket_id> <session>            # crash/interrupt recovery; owner only
record_human_input <slug> <ticket_id> <session> <path> # verbatim human answer (file must be non-empty)
resolve_ticket <slug> <ticket_id> <session> "<gist>" <resolution_path>
amend_resolution <slug> <ticket_id> [--gist "<corrected one-liner>"] [--resolution-path <path>]  # fix a resolved ticket's gist/path without reopening
amend_out_of_scope <slug> (--ticket-id T-003 | --fog-id F-2) [--reason "..."] [--gist "..."]      # fix an out-of-scope entry's reason/gist
```

Fog & scope:

```bash
add_fog <slug> "<still-vague concern>"
graduate_fog <slug> <fog_id> "<title>" <type> "<sharp question>" [--blocked-by-json '[...]']
rule_out_of_scope <slug> "<reason>" [--ticket-id T-003] [--fog-id F-2] [--gist "..."]
```

Handoff:

```bash
emit_wayfind_handoff <slug> [--remaining-risks-json '["..."]'] [--early --confirmed-by-user] [--branch <branch>]
```

Every mutating command also accepts `--expected-revision <n>` (optimistic-concurrency guard): it fails with `stale_revision` if the map has advanced past `<n>`, protecting against concurrent sessions clobbering each other. Read `revision` from `wayfind_status` first.

## Files under `.map/wayfind/<slug>/`

- `state.json` — canonical store. Never edit by hand.
- `map.md` — regenerated low-resolution overview (Destination, Notes, Decisions so far, Frontier, Blocked/claimed, Fog, Out of scope). DO-NOT-EDIT banner.
- `tickets/T-00N.md` — regenerated per-ticket detail.
- `resolutions/T-00N.md` — YOUR prose answer for a ticket (you write this before `resolve_ticket`).
- `resolutions/T-00N.human.md` — the human's VERBATIM answer for a HITL ticket (you save this before `record_human_input`).
- `handoff.md` / `handoff.json` — the final artifact `/map-plan --wayfind <slug>` consumes.

## Terminal (handoff-eligible) condition

`emit_wayfind_handoff` refuses unless the map is truly exhausted: fog empty AND no active claims AND every ticket in `{resolved, out_of_scope}` AND at least one ticket exists. A map with a claimed or blocked ticket is NOT eligible even if the frontier momentarily looks empty. Use `--early --confirmed-by-user` to override; the open items become explicit remaining risks in the handoff.

## How /map-plan consumes the handoff

`handoff.json` maps 1:1 onto the `/map-plan` spec template:

- `decisions[]` → spec **Decisions Made** (these are settled — the interview must not re-ask them).
- `out_of_scope[]` → spec **Out of Scope**.
- `remaining_risks[]` → spec **Open Questions**.

Run `/map-plan --wayfind <slug>` on a feature branch. Without an explicit slug, `/map-plan` runs `list_handoffs`; if exactly one completed handoff exists it OFFERS it, but never consumes silently.

## Examples

**Charting a foggy feature**

```text
/map-wayfind chart "rebuild checkout"
→ destination: "a faster, single-page checkout"
→ interview surfaces real uncertainty → chart it
create_wayfind_map checkout "Checkout v2" "a faster, single-page checkout" \
  --fog-json '["how does the new flow interact with legacy auth?"]'
add_ticket checkout "Session store" task "Redis or Postgres for cart sessions?"
add_ticket checkout "Payments SDK" research "Which payment SDKs support our regions?"
add_ticket checkout "One-page vs wizard" grilling "One-page checkout or a 3-step wizard?"
wire_blocking checkout T-001 '["T-002"]'   # session store waits on the SDK finding
```

**Working one ticket (human-in-the-loop)**

```text
/map-wayfind work checkout
claim_ticket checkout T-003 20260717T101500Z    # grilling → hitl_pending: true
→ ask the human verbatim: "One-page checkout or a 3-step wizard?"; STOP; hand control back
→ human answers; save verbatim to resolutions/T-003.human.md
record_human_input checkout T-003 20260717T101500Z resolutions/T-003.human.md
→ write resolutions/T-003.md
resolve_ticket checkout T-003 20260717T101500Z "One-page; wizard tested worse in the poll" resolutions/T-003.md
→ stop (one non-research decision resolved this session)
```

**Handing off**

```text
/map-wayfind handoff checkout
wayfind_status --slug checkout    # handoff_eligible: true
emit_wayfind_handoff checkout --remaining-risks-json '["fraud rules not yet scoped"]'
→ /map-plan --wayfind checkout   (on a feature branch)
```

## Troubleshooting

- **`not_terminal` on handoff** — an item is still open. Run `wayfind_status --slug <slug>`; the error's `open_items` names each blocker. Resolve or `rule_out_of_scope` them, or hand off `--early --confirmed-by-user`.
- **`awaiting_human`** — a `prototype`/`grilling` ticket needs a recorded human answer first (`record_human_input`).
- **`session_limit`** — a per-session non-research cap is active via `WAYFIND_MAX_NONRESEARCH_RESOLVES_PER_SESSION` (unset/0 = unlimited, the default); mint a fresh session id and continue, or raise/unset the cap.
- **`already_claimed` / `blocked` / `not_owner`** — the ticket is taken, has unresolved blockers, or is claimed by another session. Check `map.md`'s Blocked/claimed section.
- **`stale_revision`** — another session advanced the map; re-read it and retry with the current `--expected-revision`.
- **`cycle`** — a `wire_blocking` call would create a dependency loop; the blocker relationship is likely backwards.
- **Duplicate slug** — a map with that slug exists; pick another slug or continue the existing one with `work`.
