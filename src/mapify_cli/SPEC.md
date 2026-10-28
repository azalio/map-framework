---
id: map-cli
type: module-design
status: draft
title: CLI and local integration layer
parent: map-architecture
---

## Responsibility

The CLI is the local composition and integration layer beneath
[map-architecture](../../docs/ARCHITECTURE.md). `__init__.py` assembles Typer commands,
provider selection, project setup and diagnostics; it also retains compatibility
re-exports. This draft records the existing implementation, not a new layering policy.

Flat helpers remain within this boundary: update policy coordinates version discovery,
package installation, leases and provider refresh; install auditing records managed
files and config-entry ownership for comparison and removal. Workflow state,
finalization, logging and verification helpers persist local evidence rather than
replace the installed workflow state machine. Repository analysis, token accounting
and provider/Codex normalization are shared local services, not separate spec nodes.

## Boundary and observed dependencies

The composition root imports [map-config](config/SPEC.md),
[map-delivery](delivery/SPEC.md), provider registry and install/update helpers, and
lazily dispatches memory, repository analysis and evaluation commands.
[map-template-runtime](templates_src/SPEC.md) owns the authoring/installed-runtime
boundary; [map-memory](memory/SPEC.md) owns session learning.

Sibling edges observed in code are owned here:

- Delivery's file copier consumes `schemas` for skill requirements validation.
- `config.settings` delegates local-settings gitignore repair to delivery;
  project configuration also consumes token-budget policy values.
- Memory finalization consumes `token_budget.TokenUsage`, provider validation and
  `codex_exec` invocation/event normalization; capture uses branch sanitization,
  and finalization uses shared locking.
- Skill evaluation's `apply_patcher` consumes delivery's Jinja environment and
  `skill_ir` frontmatter parsing when applying provider-specific descriptions.
- Delivery's `_get_version()` defers a reverse import of root `__version__`.
  This is an existing coupling, not an acyclic-layer guarantee. Update policy
  also imports the root SSL-context helper.

**Unconfirmed boundary intent:** keep command composition here and reuse the named
shared helpers across siblings; these observed edges are not a universal import
allowlist or a prohibition on other dependencies.

Evaluation contracts remain in [map-skill-evaluation](../../docs/SKILL-EVAL.md)
and [map-trajectory-evaluation](../../docs/TRAJECTORY-EVAL.md), without a duplicate
`skills_eval/SPEC.md`. [map-grace-evaluation](grace_eval/SPEC.md) describes the
separate deterministic GRACE evidence layer. Detailed workflow and safety contracts
remain with map-architecture rather than being restated here.
