# Skill Eval Fixtures

This directory contains JSON eval-set fixtures for the MAP Framework skill evaluation system.

## Fixture Types

### Smoke Fixture (do not modify)

- `map_debug_eval_set.json` — 3-entry smoke fixture used by fast unit tests.
  This file exists to validate the `load_eval_set` / `run_eval` pipeline with
  minimal prompt count. **Do not add entries or rename it** — tests pin the exact
  entry count (3) and any change will break the smoke gate.

### Optimizer Eval-Sets

The following fixtures are consumed by `skill-eval optimize` to run the
anti-overfit description optimizer:

- `map_plan_optimize_eval_set.json` — eval-set for the `map-plan` skill
  (task decomposition / feature planning prompts)
- `map_efficient_optimize_eval_set.json` — eval-set for the `map-efficient` skill
  (MAP build-loop execution / subtask-apply prompts)
- `map_debug_optimize_eval_set.json` — larger eval-set for the `map-debug` skill
  (failure diagnosis / crash investigation prompts, wider variety than the smoke fixture)

## Why >= 8 Entries per Optimizer Fixture

The description optimizer uses a deterministic 60/40 train/test split:

```
n_test = max(1, round(n * 0.4))
```

With `n = 8` this gives `n_test = 3`, which is the minimum for a meaningful
held-out pass-rate signal. Smaller fixtures yield `n_test <= 2`, making the
held-out score a 0/1 coin-flip that cannot distinguish a good description
candidate from a bad one. The >= 8 floor ensures the optimizer has a statistically
useful held-out set while keeping fixture authoring lightweight.

## Authoring New Fixtures

Each JSON file must follow this schema:

```json
{
  "entries": [
    {
      "prompt": "<required string>",
      "should_trigger": "<skill name>",
      "assertions": [{"type": "contains", "value": "<substring of prompt>"}]
    },
    {
      "prompt": "<negative example>",
      "should_not_trigger": "<skill name>"
    }
  ]
}
```

Rules:
- `prompt` is required on every entry.
- Use `should_trigger` XOR `should_not_trigger` (or neither) per entry — not both.
- `assertions` is optional; when present, values should be lowercase substrings
  that genuinely appear in the prompt text.
- Include at least 1-2 `should_not_trigger` negatives to exercise the rejection path.
- Target 8-10 entries total to satisfy the >= 8 optimizer sizing requirement.
