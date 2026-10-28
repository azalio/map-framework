---
id: map-template-runtime
type: submodule-design
status: draft
title: Template authoring and installed workflow runtime
parent: map-cli
---

## Responsibility

This tree is the authoring source for prompts, shared partials, hooks and installed
workflow scripts. Build-time Jinja expands provider conditionals and includes into
bundled `templates/` assets; delivery subsequently installs those assets into target
projects. The renderer uses `[% ... %]`, `<% ... %>` and `[# ... #]` delimiters,
so runtime text such as ordinary double braces survives rendering. Installed
scripts do not require Jinja to interpret their source.

The installed orchestrator sequences work using branch `step_state.json`; the step
runner performs deterministic artifact, validation and state operations around
agent work. Skills and hooks connect those operations to the provider. Their detailed
workflow sequencing, safety and evidence contracts belong to
[map-architecture](../../../docs/ARCHITECTURE.md), not a second architecture here.

## Boundary

[map-delivery](../delivery/SPEC.md) owns rendering and managed installation mechanics.
This tree owns what is authored and what runs after installation. Generated bundles
and installed copies are outputs, not independent authoring authorities. Rendering
and parity checks are maintenance operations, not required execution phases for a
user's installed workflow.

Core runners are designed to work without importing the installed `mapify_cli`
package, but package independence is not universal. Actual optional integrations
include schema checks, dependency-graph loading, repository insight and tool-output
offload, with fallback behavior. The dispatch-observability command reports an
error if its package helper is unavailable. Memory hooks explicitly import
[map-memory](../memory/SPEC.md) helpers (preferring a source checkout), guard recursive
invocation and silently no-op when imports are unavailable; they are not self-contained
memory implementations.

[map-cli](../SPEC.md) owns the package's sibling dependency map.
[map-skill-evaluation](../../../docs/SKILL-EVAL.md) owns description-tuning/apply
contracts, and [map-trajectory-evaluation](../../../docs/TRAJECTORY-EVAL.md) owns
full-run evaluation.

**Unconfirmed boundary intent:** preserve a package-independent core runtime while
making package-assisted features explicit. This is not a prohibition on helper
imports or a promise that every optional command works without MAP installed.
This draft documents the current boundary without generating or changing runtime assets.
