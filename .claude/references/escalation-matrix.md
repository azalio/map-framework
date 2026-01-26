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

## Continue Retrying

| Condition | Max Retries |
|-----------|-------------|
| Test failures with clear fix path | 5 |
| Linting/formatting issues | 3 |
| Minor integration issues | 3 |
