---
id: map-memory
type: submodule-design
status: draft
title: Cross-session memory
parent: map-cli
---

## Responsibility

Memory converts bounded session observations into reusable, branch-scoped context.
Capture appends sanitized scratch JSONL under `.map/<branch>/sessions/scratch/`;
it records observations rather than fabricating inferred decisions. Native-envelope
evidence extraction retains narrow tool identities, targets and outcomes instead
of raw payload bodies. `digest_schema` supplies shared field names, bounds and
redaction/sanitization utilities.

Finalization is the expensive boundary: it selects prior dirty sessions, locks the
branch, invokes the selected provider to produce a digest, then publishes the digest
before marking scratch finalized and cleaning it up. Failures leave scratch available
for retry. Memory cost logging is separate from mutation of workflow token accounting.
Recall reads finalized branch digests, ranks keyword/ticket and recency matches with
optional usefulness feedback, and emits capped, sanitized context. Recall does not
invoke a model.

## Boundary

Capture's hot path is best-effort, with no network, model or subprocess calls;
branch resolution reads git metadata directly. Provider execution belongs to
finalization, not per-turn capture. Hook shims in
[map-template-runtime](../templates_src/SPEC.md) decode events and wrap returned
context; package helpers own capture, finalization and ranking. Missing package
imports cause those installed memory hooks to no-op, rather than making memory
a standalone copied implementation.

[map-cli](../SPEC.md) owns sibling edges to locking, branch sanitization,
provider validation, Codex normalization and token-usage types. CLI memory commands
are another caller of the same helpers. Detailed system context remains in
[map-architecture](../../../docs/ARCHITECTURE.md).

**Unconfirmed boundary intent:** retain a cheap observation path and keep model
work behind lazy finalization; reuse the shared digest schema across producers and
consumers. These are inferred module boundaries, not a blanket prohibition on
provider integration. Session digests supply fallible historical context, not
workflow completion authority or a replacement for current source and test evidence.
