---
name: map-auto
description: "Single-entry autopilot wrapper for task automation. Routes tasks to existing MAP workflows conservatively."
---

# $map-auto — Autopilot Task Router

Accepts a task description and routes it through the appropriate MAP workflow without bypassing safety gates. This is a convenience wrapper for automated task ingestion and external loops; it does not replace explicit MAP commands, collapse MAP internals, or reimplement routing logic.

## Usage

```
$map-auto "<task description>"
$map-auto --dry-run "<task description>"
```

## Routing Logic

Evaluate conditions in strict order. Stop at the first match:

1. **Interrupted / In-Progress**: If `.map/<branch>/step_state.json` exists and state is `in_progress`, `pending_approval`, `failed`, or `completed` -> Route to `/map-resume`.
2. **Approved Plan Present**: If a valid, approved `task_plan_<branch>.md` or blueprint exists without pending holds -> Route to `/map-efficient`.
3. **Explicitly Small / Low-Risk**: If task is a direct, bounded edit with trivial scope and no architectural impact -> Route to `/map-fast` (or direct-edit off-ramp).
4. **Foggy / Strategic / Unscoped**: If task is vague, lacks acceptance criteria, or requires product/strategic discovery -> Route to `/map-wayfind`.
5. **Non-Trivial / Unplanned**: Default fallback -> `/map-plan`.

## Artifact Contract

Writes `.map/<branch>/auto-route.json` with the exact schema:

| Field | Type | Description |
|---|---|---|
| `task_summary` | string | Sanitized description of the task |
| `selected_route` | string | One of `/map-resume`, `/map-efficient`, `/map-fast`, `/map-wayfind`, `/map-plan` |
| `route_evidence` | array | List of signals/facts that triggered this route |
| `blocked_by` | array | Approval holds blocking continuation (`plan_approval`, `dangerous_action`, `safety_guardrail`, `review_check`) or `[]` |
| `next_command` | string | The exact MAP command to execute next |
| `dry_run` | boolean | `true` if invoked with `--dry-run` |
| `execution_started` | boolean | `true` if the routed command was dispatched, `false` if only recommended |

## Safety & Guardrails

- **Never bypass gates**: If `plan_approval`, `dangerous_action`, `safety_guardrail`, or review/check blockers exist, the wrapper stops immediately and populates `blocked_by`. It never auto-accepts risk.
- **Preserve artifacts**: Does not overwrite existing `task_plan_<branch>.md` or `blueprint.json`. Respects explicit-consent rules identical to `/map-plan`.
- **Dry-run**: `--dry-run` computes the route, writes `auto-route.json`, and halts without executing the next command.
- **Idempotent**: Safe to call repeatedly from task-tracker loops. Overwrites `auto-route.json` conservatively.
- **No silent consumption**: If `/map-wayfind` handoffs are pending, the wrapper surfaces them in `route_evidence` and routes to the appropriate handler rather than consuming them silently.

## Examples

```bash
$map-auto "Fix typo in README.md heading"
# -> detects trivial scope, routes to /map-fast

$map-auto "Implement OAuth2 SSO for dashboard"
# -> detects non-trivial scope, no plan, routes to /map-plan

$map-auto --dry-run "Refactor payment service error handling"
# -> writes .map/<branch>/auto-route.json with selected_route=/map-plan, execution_started=false, stops.
```

## Troubleshooting

- **Route artifact missing**: Ensure `.map/` is initialized via `mapify init`. Run `$map-auto` on the correct feature branch.
- **Unexpected route**: Inspect `.map/<branch>/auto-route.json` for `route_evidence` to understand the classifier decision. Override by invoking the explicit MAP command directly.
- **Blocked by hold**: Follow the `blocked_by` reference to resolve the approval hold (e.g., human sign-off for `dangerous_action`) before resuming.
- **State mismatch**: If `step_state.json` disagrees with artifacts, use `$map-resume` or orchestrator repair commands. This wrapper does not fix corrupted state.
