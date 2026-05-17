# Evidence-First Output Examples

Use these compact examples when a MAP prompt asks an agent to return JSON after reviewing code, specs, logs, or workflow artifacts.

## Review Finding

```json
{
  "evidence": [
    {
      "file_path": "src/service.py",
      "line_range": "42-47",
      "quote": "user_id = request.args['user_id']",
      "relevance": "The value is trusted before authorization checks."
    }
  ],
  "valid": false,
  "verdict": "needs_revision",
  "issues": [
    {
      "severity": "HIGH",
      "category": "security",
      "description": "The endpoint trusts a caller-controlled user id before authz.",
      "file_path": "src/service.py",
      "line_range": "42-47",
      "suggestion": "Resolve the authenticated principal first and compare it to the requested account."
    }
  ]
}
```

## Debug Root Cause

```json
{
  "quotes": [
    {
      "source": "test output",
      "locator": "pytest tests/test_service.py::test_retry",
      "quote": "AssertionError: expected 3 attempts, got 1",
      "relevance": "Confirms the retry loop exits after the first failure."
    },
    {
      "source": "src/retry.py",
      "locator": "lines 18-23",
      "quote": "except TimeoutError: raise",
      "relevance": "The handler re-raises instead of continuing the retry loop."
    }
  ],
  "root_cause": "TimeoutError is re-raised before the retry counter can advance.",
  "next_steps": ["Change the TimeoutError branch to continue until attempts are exhausted."]
}
```

## Spec Review Finding

```json
{
  "evidence": [
    {
      "file_path": ".map/feature/spec_feature.md",
      "line_range": "31-39",
      "quote": "Background sync runs every 5 minutes",
      "relevance": "The spec omits conflict handling for overlapping sync runs."
    }
  ],
  "finding": {
    "severity": "HIGH",
    "category": "concurrency",
    "description": "The spec schedules repeated background work but does not define locking or idempotency.",
    "suggested_fix": "Add an invariant for single active sync per account and define stale-lock recovery."
  }
}
```
