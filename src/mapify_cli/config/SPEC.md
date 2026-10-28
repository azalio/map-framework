---
id: map-config
type: submodule-design
status: draft
title: Project configuration and provider settings
parent: map-cli
---

## Responsibility

Configuration turns project preferences and provider settings into values consumed
by setup and workflow helpers. `MapConfig` and its loader/default writer interpret
`map-config.yaml`, including workflow profiles, context, memory and update options.
Validation and fallback behavior belong here rather than to command presentation.
Optional YAML availability and malformed or unsupported values are handled by the
loader's existing defaults and diagnostics.

The provider-facing side creates MAP MCP configuration and reads, merges and writes
project `.mcp.json`. Settings helpers merge local approvals and configure global
permissions without treating project settings as an entirely replaceable template.
Opt-in autonomy is represented in user-local settings, not the team-shared baseline;
the settings sentinel enables the runtime safety hook. Permission strings alone
are not the hard enforcement boundary.

## Boundary

Inputs are project paths, requested options and existing user configuration; outputs
are parsed configuration objects and targeted settings changes. Configuration does
not run provider sessions or advance workflow steps. The installed runner has its
own configuration-reading paths and synchronized value sets; this package is not
an unconditional runtime prerequisite for every installed script.

[map-cli](../SPEC.md) owns composition and observed sibling edges, including the
settings-to-delivery gitignore helper and token-policy dependency.
[map-delivery](../delivery/SPEC.md) owns managed asset placement; local settings
merge and `.mcp.json` behavior remain here. [map-template-runtime](../templates_src/SPEC.md)
owns the consuming hooks/runners, and [map-architecture](../../../docs/ARCHITECTURE.md)
owns detailed workflow and safety contracts.

**Unconfirmed boundary intent:** keep preference interpretation and conservative
configuration merges together, with runtime enforcement in hooks and execution
helpers. This is inferred from current code, not a new rule forbidding imports or
all configuration access elsewhere. Global permissions and local autonomy have
different scopes; neither is a claim that all configuration is project-local.
