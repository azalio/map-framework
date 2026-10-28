---
id: map-grace-evaluation
type: submodule-design
status: draft
title: GRACE evidence aggregation
parent: map-cli
---

## Responsibility

GRACE evaluation is a deterministic evidence layer for comparing semantic
code-contract anchor variants. It represents fixtures, individual run observations,
variant aggregates, stale-anchor findings and a versioned report. The six variants
are `baseline`, `inline`, `lex`, `min`, `inj` and `lie`; placement categories distinguish
code-local anchors, prompt injection and absence of anchors.

Aggregation consumes supplied records for one variant and derives success, retries,
token usage and stale-detection summaries, with a caller-supplied baseline for comparisons.
Run identifiers are deterministic. Report timestamps are supplied by callers, not
read from a clock inside this package. Serialization converts data objects to and
from dictionaries; it does not itself persist reports or collect provider evidence.

The sweep examines supplied source strings for `# CONTRACT:` and `# ANCHOR:` comments
and checks nearby lines for a small set of contradiction signals. Findings identify
locations and variants. This is a heuristic stale-anchor audit, not a semantic proof
that code satisfies every claim. The deliberately false `lie` variant provides a
negative-control use case.

## Boundary

The current package exposes data and pure deterministic logic: it does not launch
providers, read fixture files, write reports or consume live token logs. Paths in
fixture/report data describe integration surfaces, not implemented I/O. A GRACE CLI
runner, model dispatcher and report viewer remain future integration work rather
than implied capabilities of the existing schema.

[map-cli](../SPEC.md) owns local composition and sibling dependencies;
[map-architecture](../../../docs/ARCHITECTURE.md) records the GRACE slice's system
context. Trigger tuning remains owned by
[map-skill-evaluation](../../../docs/SKILL-EVAL.md), and whole-run outcome scoring
by [map-trajectory-evaluation](../../../docs/TRAJECTORY-EVAL.md); GRACE does not
replace or duplicate either evaluation contract.

**Unconfirmed boundary intent:** preserve the deterministic data/sweep layer and
place future dispatch, clock and filesystem operations at an explicit caller
boundary. This is an inference from current implementation and comments, not a
new dependency prohibition for an unimplemented runner.
