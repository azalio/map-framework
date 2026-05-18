# MAP JSON Output Contracts

Use these contracts when a MAP skill prompt asks an agent to return JSON that is not already covered by evidence-first output examples.

Every `Output JSON with:` prompt section must be either:

- Evidence-first: include `evidence` or `quotes` before verdict, risk, score, root-cause, or decomposition judgment fields, and link to `map-output-examples.md` when the prompt is high-risk.
- Reference-backed: cite one of the compact workflow contracts below before listing fields.

## Decomposition Output

Use for TaskDecomposer prompts that split a user request into ordered work units.

Required shape:

```json
{
  "subtasks": [
    {
      "id": "string",
      "description": "string",
      "acceptance_criteria": "string | array",
      "depends_on": []
    }
  ],
  "total_subtasks": 1
}
```

The prompt may add workflow-specific fields such as `debug_type`, `estimated_complexity`, or `estimated_duration`, but it must keep subtasks atomic, testable, and dependency-aware.

## Actor Change Summary

Use for Actor prompts that edit files directly and return a compact status summary instead of serialized file contents.

Required shape:

```json
{
  "approach": "string",
  "files_changed": ["path/to/file"],
  "tests_run": [],
  "remaining_risks": []
}
```

The prompt may add workflow-specific fields such as `trade_offs`, `why_this_fixes_it`, or `potential_side_effects`. `tests_run` is an array of command strings and should be empty when no tests were run. The prompt must still say that files were edited directly with Edit/Write tools and that full file contents must not be serialized in the response.

## Monitor Verdict

Use for Monitor prompts that validate written repository state.

Required shape:

```json
{
  "valid": true,
  "issues": [],
  "verdict": "approved | needs_revision | rejected",
  "feedback": "string"
}
```

If the Monitor prompt can reject, block, or materially change workflow direction based on code, test output, or artifacts, prefer the evidence-first review finding contract from `map-output-examples.md` and include evidence before verdict fields.

## Learning Summary

Use for Reflector or learning prompts that extract durable rules from a completed workflow.

Required shape:

```json
{
  "key_insight": "string",
  "patterns_used": [],
  "patterns_discovered": [],
  "suggested_new_bullets": [],
  "workflow_efficiency": {}
}
```

The prompt must also tell the agent not to repeat existing learned rules already shown in context.
