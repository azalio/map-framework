---
id: map-delivery
type: submodule-design
status: draft
title: Provider delivery and managed installation
parent: map-cli
---

## Responsibility

Delivery translates bundled MAP assets into provider-discoverable project files.
It owns installation mechanics, not the agent decisions expressed by those assets.
Claude delivery populates `.claude/`; Codex delivery uses its own discovery surfaces
and project `AGENTS.md`. Shared `.map/` tools support installed workflows. Provider
adapters coordinate these copies while the CLI retains interactive setup sequencing.

Managed copying attaches provenance where supported, detects edited content,
backs up drifted files and preserves user tails outside managed fences. Strict-schema
configuration ownership is tracked separately by the CLI's install manifest rather
than forced into every copied file. Delivery also prunes skill catalogs for missing
requirements, provides fallback agent content and builds governance inventories that
distinguish hook enforcement from prompt guidance. Project-local domain-skill
bootstrapping is distinct from the shipped managed catalog.

## Boundary

Inputs are packaged assets, destination project paths and provider/setup options;
outputs are installed files, copy/drift results and installation counts. Build-time
Jinja rendering is implemented here, while authoring and installed execution belong
to [map-template-runtime](../templates_src/SPEC.md). Rendering stages and verifies
outputs before live copying; delivery does not itself execute the workflow described
by a skill.

[map-cli](../SPEC.md) owns sibling dependency edges, including schema validation and
the deferred root version import. [map-config](../config/SPEC.md) owns settings/MCP
merge behavior; the manifest helpers at the CLI level own whole-install auditing.
The detailed provider, safety and workflow contracts remain in
[map-architecture](../../../docs/ARCHITECTURE.md).

**Unconfirmed boundary intent:** centralize provider placement and managed-file
mutation in delivery so callers reuse its preservation behavior instead of inventing
parallel copiers. This describes an inferred responsibility, not a newly enforced
ban on filesystem writes elsewhere. The current mix of rendering, copying and
reporting is recorded as-is; this draft does not propose a package split.
