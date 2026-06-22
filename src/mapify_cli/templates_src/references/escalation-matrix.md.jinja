# Escalation Decision Matrix

Reference guide for orchestrator agents on when to escalate failures vs. retry.

---

## Immediate Escalation (no retry)

| Condition | Reason |
|-----------|--------|
| Ambiguous user request | Verification cannot determine intent |
| Security-sensitive operation | Any uncertainty requires human approval |
| Destructive operation + confidence < 0.95 | Risk too high |
| External API/service failure | Cannot be fixed by re-decomposition |
| Missing credentials/permissions | Requires user action |

## Escalate After 2 Retries

| Condition | Reason |
|-----------|--------|
| Same subtask failing repeatedly | Likely fundamental issue |
| Confidence oscillating > 0.3 | Model uncertain |
| Same error message 2+ times | Not making progress |

## Bounded-effort terminal escalation (#255 — deterministic)

This is the deterministic terminal outcome for the `/map-efficient`
Actor→Monitor loop. It supersedes the prose "escalate to user" for two cases and
emits ONE structured outcome via
`map_step_runner.py build_escalation_outcome <subtask_id> <reason>`:

| Trigger | reason | `outcome` | What happens |
|---------|--------|-----------|--------------|
| 3rd **identical** normalized failure (`escalation_recommended:true`) | `repeated_failure` | `BLOCKED` | STOP immediately. The constraint armed at the 2nd identical failure was the single bounded recovery act; a 3rd means it did not work. |
| `monitor_failed` returns `status:"max_retries"` (budget exhausted across **differing** failures) | `max_retries` | `CLARIFICATION_NEEDED` | STOP; the task likely needs reframing/clarification. |

Properties: `status:"escalated"`, durable `.map/<branch>/escalation_<subtask>.md`
blocker report, `escalation` manifest stage, idempotent. The stop is re-derived
from the anti_repeat store inside the subcommand (latest-signature rule), so a
fresh signature on the last attempt returns `status:"not_escalated"` and the loop
resumes — a spurious call cannot fabricate a terminal stop. A CLEAN_RETRY
iteration (`--quarantine-active`) defers the stop so the one-shot reset runs first.

**The legacy retry-3 Stuck Recovery below is BYPASSED for an identical-failure
loop** (a dominant repeated signature short-circuits straight to escalation). It
stays active only for **non-identical stuckness** — changing failures with no
dominant repeated signature, where research/predictor recovery may still help.

## Stuck Recovery (Intermediate — at retry 3, non-identical failures only)

For non-identical stuckness (no dominant repeated signature), invoke intermediate
recovery at monitor retry 3:

| Step | Action | Skip Condition |
|------|--------|----------------|
| 1. research-agent | Find alternative approach for stuck subtask | Reuse existing findings if already ran for this subtask |
| 2. predictor | Analyze why current approach fails, suggest alternatives | Skip for `risk_level == "low"` subtasks |
| 3. Resume retries | Pass recovery context to Actor for retries 4-5 | — |
| 4. User escalation | If research-agent + predictor found nothing useful | Only if recovery context is empty |

This path is orchestrator-level logic in `map-efficient.md`, not a Ralph Loop state transition.

## Guard Pattern Escalation (after 2 rework attempts)

When Monitor passes but TESTS_GATE/LINTER_GATE fails (regression detected):

| Rework Attempt | Action |
|----------------|--------|
| 1-2 | Retry Actor with guard failure context (test/lint stderr) |
| 3+ | Escalate to user: "Guard failure after 2 rework attempts. Skip/Abort?" |

Guard rework counter is independent of monitor retry counter.

## Continue Retrying

| Condition | Max Retries |
|-----------|-------------|
| Test failures with clear fix path | 5 |
| Linting/formatting issues | 3 |
| Minor integration issues | 3 |
