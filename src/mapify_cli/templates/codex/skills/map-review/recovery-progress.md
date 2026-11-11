# Recovery and progress review

Use this reference when changed code controls retries, ownership/leases, ACKs,
transactions, result acceptance, cursors or checkpoints. Keep the scope on the
changed path and its actual callers. The parent can use authorized scoped probes;
shell-free reviewers use admitted evidence and report missing context.

## Establish two contracts

- Safety: data and external effects remain consistent; stale work cannot overwrite
  the current owner's result.
- Progress: a supported healthy caller can finish or acquire work after a failure.

Recover the contract from the base implementation, callers and established tests.
A new test that encodes the new behavior does not by itself authorize that behavior.
For each relevant scenario, record the base/head difference, state before/after,
next input and the transition that permits recovery.

## Trace successive attempts

| Changed boundary | Sequence to inspect |
| --- | --- |
| Retry | Failure followed by another call from the same worker |
| Ownership | Repeated fast failures while a healthy competitor actually attempts work |
| Lease | Owner stalls or dies; expiry, locks and takeover determine availability |
| Generation | A late result arrives after reacquisition, including the same identity |
| Admission | Multiple threads share an identity; denied admission is not success |
| Transaction | Failure before/after an external effect, rollback and cleanup failure |

Keep attempt time, last successful completion, lease renewal and checkpoint separate.
An unsuccessful attempt that renews ownership may indefinitely exclude healthy work.
Prove a permitted repeatable sequence with a competitor that gets execution time;
unfair scheduling alone is not an implementation defect.

## Follow rejected responses into the next request

After rejecting a response, inspect both stored data and control state: cursor,
version, token, generation or completion flag. Identify the next actual request
and what response the dependency produces for that input. A stale cursor can
request the same unusable delta forever while the dependency is healthy.
Check whether reset, resync, reconciliation or a server fallback provides an exit.
Do not require unconditional reset after ordinary transport errors.

A mock that returns failure and then success independently of its input cannot
prove recovery when success requires an input transition absent from the code.
Use a causal fake or inspect the actual outgoing request and server contract.
Unavailable dependency behavior remains an explicit question.

## Bound the finding

A refutation of data loss does not refute an independently evidenced progress
failure; preserve each distinct cause/scenario under its own ID. Bounded waiting
can still unnecessarily occupy a scarce resource and delay independent work.
State the demonstrated consequence without claiming a permanent leak, outage or
throughput regression without evidence. Record unresolved local questions and
blockers in the final answer, and carry them into the next review snapshot.

