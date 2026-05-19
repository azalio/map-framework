# MAP XML Prompt Envelopes

Use this reference when a MAP skill builds a long subagent prompt that mixes user
requirements, persisted artifacts, workflow policy, and an output contract.

## Purpose

MAP prompts should preserve the user's requirements and branch artifacts before
asking an agent to reason over them. For long-context prompts, put the documents
or artifacts first, then the task and instructions, then the expected output.

This follows Anthropic's prompt engineering guidance, accessed 2026-05-19:

- `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags`
- `https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips`

The relevant constraints are:

- use consistent, descriptive XML tags when prompts mix instructions, context,
  examples, and variable inputs
- put long documents and data above the query/instructions for long-context work
- wrap multi-document inputs in nested document tags with source metadata
- keep output contracts in their own section so schema requirements are not
  confused with task context

## Standard Envelope

```xml
<documents>
  <document source="path-or-origin">
    <document_content>
    ...long artifact, diff, spec, finding, or request...
    </document_content>
  </document>
</documents>

<task>
The one-sentence job for this agent.
</task>

<workflow_policy>
The MAP phase rules, ordering constraints, and hard stops that apply to this
agent call.
</workflow_policy>

<instructions>
The concrete checks or actions the agent should perform, in order.
</instructions>

<expected_output>
The response schema, evidence requirements, and any formatting constraints.
</expected_output>
```

## Rules

- Keep artifact text inside `<documents>` or `<artifacts>` before instructions.
- Use `<task>` for the user's goal or current subtask, not markdown `**Task:**`
  inside generated subagent prompts.
- Use `<workflow_policy>` for MAP sequencing rules and hard stops.
- Use `<constraints>` when the agent must obey scope, file, or phase limits.
- Use `<expected_output>` for JSON fields and evidence-first requirements.
- Keep existing MAP semantic tags such as `<MAP_Contract>` and `<map_context>`;
  they may live inside `<documents>` or `<artifacts>` when they are input data.
