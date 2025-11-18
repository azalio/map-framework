# MAP Agent Contracts Plan - Reviewer Feedback Fixes

**Date:** 2025-11-18
**Status:** Fix document for MAP_AGENT_CONTRACTS_PLAN.md

## Summary of Issues

Reviewer identified repo alignment issues and design gaps that need fixing before implementation.

## Critical Fixes Required

### 1. Schema Location/Shape Mismatch ✓ IN PROGRESS

**Issue:** Plan uses aggregated files `src/mapify_cli/schemas/agent_inputs.json` and `agent_outputs.json`, but `verify_schema_template_sync.py` expects per-agent files (e.g., `schemas/actor_input.json`).

**Fix Applied:**
- Changed deliverables section (lines 499-504) to specify per-agent files
- Added note about compatibility with verify script
- Updated file structure to show:
  ```
  schemas/
  ├── actor_input.json
  ├── monitor_input.json
  ... (8 files each for input/output)
  ```

**Remaining:**
- Fix corrupted JSON structure in Agent Output Contracts section (lines 766-1164)
- Remove aggregated format examples, keep only per-agent examples

---

### 2. Agent Name Normalization (Hyphens vs Underscores)

**Issue:** Templates use hyphenated names (`task-decomposer`, `documentation-reviewer`), but JSON samples use underscored keys (`task_decomposer`, `documentation_reviewer`).

**Files Affected:**
- docs/MAP_AGENT_CONTRACTS_PLAN.md lines: 54, 55, 614, 973, 914, 1313, 2297, 2304, 2523

**Fix Required:**
Add normalization rule to schema section:

```markdown
**Agent Name Convention:**
- Schema files use hyphenated names matching template files: `task-decomposer`, `documentation-reviewer`
- Code implementations should normalize hyphens to underscores for lookups:
  ```python
  def normalize_agent_name(name: str) -> str:
      return name.replace("-", "_")
  ```
```

---

### 3. CLI Test Import Path

**Issue:** Tests import `from mapify_cli.cli import cli`, but no `mapify_cli/cli.py` exists. The Typer app lives in `src/mapify_cli/__init__.py`.

**File:** docs/MAP_AGENT_CONTRACTS_PLAN.md line 2620

**Current:**
```python
from mapify_cli.cli import cli
```

**Fix:**
```python
from mapify_cli import app as cli
```

---

### 4. Missing jsonschema Dependency

**Issue:** Validator uses `jsonschema` but it's not declared in `pyproject.toml`.

**Fix Required:**
Add to Phase 2 deliverables section:

```markdown
### Phase 2: Validation Logic

**Dependencies to Add:**
- `jsonschema>=4.0.0` to `pyproject.toml` [project.dependencies]

**Rationale:** Pre-flight validator uses `jsonschema.validate()` and `jsonschema.exceptions.ValidationError`.
```

---

### 5. Add mkdir for .map/validation_logs

**Issue:** Example snippets write to `.map/validation_logs/` without ensuring directory exists.

**Files Affected:** Lines 1857, 1870, 1890, 1895

**Fix:** Prepend to all validation snippets:

```bash
mkdir -p .map/validation_logs
```

**Example (line 1870):**
```bash
# Before validation
mkdir -p .map/validation_logs

# Then run detector
python -m mapify_cli.validation.mcp_tool_detector ...
```

---

### 6. Replace jq with Python Fallback

**Issue:** Line 1895 uses `jq` which may not be installed. Provide portable Python alternative.

**Current (line 1895):**
```bash
cat /tmp/curator_output.txt | jq '.sync_to_cipher | length' | grep -q '^0$' && echo "⚠️  Warning"
```

**Fix:**
```bash
python -c 'import json,sys; data=json.load(open("/tmp/curator_output.txt")); print(len(data.get("sync_to_cipher",[])))' | grep -q '^0$' && echo "⚠️  Warning: Curator sync_to_cipher empty"
```

---

### 7. Monitor Input Schema vs Integration Test Mismatch

**Issue:** Monitor input schema doesn't include `actor_output`, `acceptance_criteria`, `test_strategy`, but integration test validates those fields (lines 2595-2614).

**Fix Options:**

**Option A:** Add missing fields to monitor schema
```json
{
  "properties": {
    ...
    "actor_output": { "type": "string", "default": "" },
    "acceptance_criteria": { "type": "array", "items": { "type": "string" }, "default": [] },
    "test_strategy": { "type": "string", "default": "" }
  }
}
```

**Option B:** Update integration test to use only defined schema fields

**Recommendation:** Option A - add fields to schema (they're useful for validation context).

---

### 8. MCP Tool Detection Robustness

**Issue:** Current detector requires BOTH call indicators AND "JSON-like structure" (lines 1714-1723). This misses natural language outputs like "using mcp__cipher__cipher_memory_search" (line 2318 fixture).

**Current Logic (line 1721-1723):**
```python
# FIXED: Changed OR to AND logic to prevent false positives
# Tool name must appear with BOTH call indicators AND structured context
if is_actual_call and has_json_structure:
    detected_tools.add(tool_name)
```

**Problem:** Too strict - misses valid calls in plain text.

**Fix:** Remove JSON structure requirement OR switch to stricter phrase matching:

**Option A (Recommended):** Stricter phrases, no JSON requirement
```python
call_indicators = [
    "invoked mcp__",
    "called mcp__",
    "using mcp__",
    "executed mcp__"
]

# Require explicit call verb BEFORE tool name
for indicator in call_indicators:
    if f"{indicator}{tool_name}" in context:
        detected_tools.add(tool_name)
        break
```

**Option B:** Require explicit output format from agents
```markdown
**Agent Contract:** Agents MUST output `mcp_tools_used` array:
```json
{
  "mcp_tools_used": ["mcp__cipher__cipher_memory_search"]
}
```

---

### 9. Add CLI Entrypoint for MCP Detector

**Issue:** Templates call `python -m mapify_cli.validation.mcp_tool_detector` (lines 1870, 1890) but module has no `__main__.py`.

**Fix:** Add to `src/mapify_cli/validation/mcp_tool_detector.py`:

```python
def main():
    """CLI entrypoint for MCP tool verification."""
    import argparse
    parser = argparse.ArgumentParser(description="Verify MCP tool usage in agent output")
    parser.add_argument("--agent", required=True, help="Agent name (reflector, curator)")
    parser.add_argument("--output", required=True, help="Path to agent output file")
    args = parser.parse_args()

    with open(args.output) as f:
        output_text = f.read()

    result = verify_mcp_tools(args.agent, output_text)

    if result.verified:
        print(f"✓ {args.agent} MCP tool verification passed")
        sys.exit(0)
    else:
        print(f"✗ {args.agent} missing required MCP tools: {', '.join(result.missing_tools)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**OR** (Alternative): Route via `mapify validate` subcommand:

```python
@validate_app.command("mcp-tools")
def validate_mcp_tools_cmd(
    agent_name: str = typer.Argument(...),
    output_file: Path = typer.Argument(..., exists=True)
):
    """Verify agent called required MCP tools."""
    # Implementation here
```

---

## Validation Checklist

- [✓] Schema location fixed (per-agent files)
- [ ] Agent name normalization rule added
- [ ] CLI import path fixed (line 2620)
- [ ] jsonschema dependency documented in plan
- [ ] mkdir -p .map/validation_logs added (4 locations)
- [ ] jq replaced with Python (line 1895)
- [ ] Monitor schema aligned with integration test
- [ ] MCP detection robustness improved
- [ ] CLI entrypoint for MCP detector added

---

## Next Steps

1. Fix corrupted JSON structure in Agent Output Contracts section
2. Apply all 9 fixes above
3. Run verification: `python scripts/verify_schema_template_sync.py --all`
4. Validate all bash snippets are executable
5. Review with Monitor agent before marking as "Ready for Implementation"
