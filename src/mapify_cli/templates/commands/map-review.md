---
description: Interactive 4-section code review using Monitor, Predictor, and Evaluator agents
---

# MAP Review Workflow

Interactive, structured code review of current changes using Monitor, Predictor, and Evaluator agents.

**Task:** $ARGUMENTS

## Execution Rules

1. Execute all steps in the order listed below
2. Use the exact `subagent_type` values specified (monitor, predictor, evaluator)
3. All 3 agents are required — do not skip any
4. **Monitor `valid=false` is a hard stop** — report issues immediately, do not proceed to interactive presentation
5. Wait for all parallel calls to complete before proceeding to the next phase

## Review Preferences (Customize per project)

These defaults guide how agents weigh findings. Override by editing this section:

- **DRY:** Important — flag duplication aggressively
- **Testing:** Non-negotiable — missing tests = high severity
- **Engineering level:** "Engineered enough" — reject both under-engineering and over-engineering
- **Edge cases:** Prefer handling more, especially for public APIs
- **Clarity:** Explicit over clever — readable code wins
- **Performance:** Flag only when measurable impact is likely

## Expected Agent Output Schemas (Contract Reference)

These are the fields each agent is expected to return. The command prompt explicitly requests them.

**Monitor:**
- `valid`: boolean — overall pass/fail
- `summary`: string — brief description of findings
- `verdict`: `'approved'` | `'needs_revision'` | `'rejected'` — requested explicitly (not in base schema, `additionalProperties: true`)
- `issues[]`: array of `{severity, category, description, file_path, line_range, suggestion}`
- `passed_checks[]`: array of strings — checks that passed
- `failed_checks[]`: array of strings — checks that failed

**Predictor:**
- `risk_assessment`: `'low'` | `'medium'` | `'high'` | `'critical'`
- `predicted_state.affected_components[]`: array of affected components/files
- `predicted_state.breaking_changes[]`: array of `{type, description, mitigation}`
- `predicted_state.required_updates[]`: array of required follow-up changes
- `confidence.score`: float 0.0-1.0

**Evaluator:**
- `scores.functionality`: int 0-10
- `scores.code_quality`: int 0-10
- `scores.performance`: int 0-10
- `scores.security`: int 0-10
- `scores.testability`: int 0-10
- `scores.completeness`: int 0-10
- `overall_score`: float 1.0-10.0 (weighted)
- `recommendation`: `'proceed'` | `'improve'` | `'reconsider'`
- `strengths[]`: array of strings
- `weaknesses[]`: array of strings
- `next_steps[]`: array of strings

## Review Section Protocol

This protocol is used identically by all 4 review sections below. Do NOT deviate.

1. **Present top N issues** (N=4 in BIG mode, N=1 in SMALL mode) from the primary source agent for this section, using the section prefix (e.g., ARCH-1, QUALITY-2, TESTS-1, PERF-3)
2. **For each issue:**
   - Describe the problem with `file:line` references where available
   - Present 2-3 options with tradeoffs (pros/cons for each)
   - **Recommended option is always listed first** (marked with "(Recommended)")
3. **AskUserQuestion** with numbered issues and lettered options for each
   - Example: "ARCH-1: Option A (Recommended) / Option B / Option C"
   - **Skip AskUserQuestion in CI mode** — auto-select recommended options
4. **Summarize decisions** from this section in 3-5 lines before proceeding to the next section
   - Include: which issues were addressed, which options were chosen, what remains

## Step 0: Select Review Mode

**Parse $ARGUMENTS for `--ci` or `--auto`:**
- If `--ci` or `--auto` is present in $ARGUMENTS → set CI_MODE=true
- CI_MODE skips all AskUserQuestion calls and auto-selects recommended options

**If NOT CI_MODE:** Use AskUserQuestion to ask the user:

> How thorough should this review be?
> - **BIG** (Recommended): Up to 4 issues per section — comprehensive review
> - **SMALL**: 1 issue per section — quick pass for small changes

Default to BIG if user doesn't respond or in CI mode.

## Phase A: Collection (Parallel)

### Step A.1: Gather changes

```bash
git diff HEAD
git status
```

Save the diff output — it will be passed to all 3 agents.

### Step A.2: Launch all parallel calls

In **ONE message**, launch all 3 agent Task calls in parallel (no dependencies between them):

```
Task(
  subagent_type="monitor",
  description="Review code changes",
  prompt="Review the following changes for code quality, security, and correctness.

**Review Preferences:**
[paste Review Preferences section above]

**Changes:**
[paste git diff output]

Check for:
- Code correctness and logic errors
- Security vulnerabilities (OWASP top 10)
- Standards compliance
- Test coverage gaps
- Performance issues

Output JSON with:
- valid: boolean
- summary: string
- verdict: 'approved' | 'needs_revision' | 'rejected'
- issues: array of {severity, category, description, file_path, line_range, suggestion}
- passed_checks: array of strings
- failed_checks: array of strings"
)

Task(
  subagent_type="predictor",
  description="Analyze change impact",
  prompt="Analyze the impact of these changes on the broader codebase.

**Review Preferences:**
[paste Review Preferences section above]

**Changes:**
[paste git diff output]

Analyze:
- Affected components and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment (low/medium/high/critical)
- Integration points affected

Output JSON with:
- risk_assessment: 'low' | 'medium' | 'high' | 'critical'
- predicted_state:
    affected_components: array of affected files/modules
    breaking_changes: array of {type, description, mitigation}
    required_updates: array of strings
- confidence:
    score: float 0.0-1.0"
)

Task(
  subagent_type="evaluator",
  description="Score change quality",
  prompt="Evaluate the overall quality of these changes.

**Review Preferences:**
[paste Review Preferences section above]

**Changes:**
[paste git diff output]

Provide quality assessment using 1-10 scoring:
- Functionality score (1-10)
- Code quality score (1-10)
- Performance score (1-10)
- Security score (1-10)
- Testability score (1-10)
- Completeness score (1-10)

Output JSON with:
- scores: {functionality, code_quality, performance, security, testability, completeness}
- overall_score: weighted float (1.0-10.0)
- recommendation: 'proceed' | 'improve' | 'reconsider'
- strengths: array of strings
- weaknesses: array of strings
- next_steps: array of strings"
)
```

**Parallel execution:** All 3 agent calls MUST be issued in a single message. Wait for all to complete before proceeding.

### Hard Stop Check

After all agents complete, check Monitor output:
- If `Monitor.valid = false` → **HARD STOP**. Present Monitor issues immediately and do not proceed to Phase B. The user must fix issues before re-running the review.

## Phase B: Interactive Presentation (4 Sections)

Present findings section by section. Each section follows the **Review Section Protocol** defined above.

### Section 1: Architecture

**Primary source:** Predictor (`breaking_changes`, `affected_components`, `risk_assessment`)
**Cross-reference:** Evaluator `scores.completeness`
**Issue prefix:** `ARCH`

Focus on:
- Breaking changes and their mitigations
- Affected component blast radius
- Architectural fit of the changes
- Completeness of the change set (are all affected areas updated?)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 2

### Section 2: Code Quality

**Primary source:** Monitor (`issues` filtered by category: correctness, code-quality, maintainability)
**Cross-reference:** Evaluator `scores.code_quality`
**Issue prefix:** `QUALITY`

Focus on:
- Correctness issues (logic errors, edge cases)
- Code quality issues (naming, structure, DRY violations)
- Maintainability concerns
- Standards compliance

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 3

### Section 3: Tests

**Primary source:** Monitor (`issues` filtered by category: testability, test-coverage)
**Cross-reference:** Evaluator `scores.testability`
**Issue prefix:** `TESTS`

Focus on:
- Missing test coverage for new/changed code
- Test quality (edge cases, error paths)
- Testability of the implementation (dependency injection, mocking seams)

→ Follow **Review Section Protocol**
→ Summarize decisions before proceeding to Section 4

### Section 4: Performance

**Primary source:** Monitor (`issues` filtered by category: performance)
**Cross-reference:** Evaluator `scores.performance` + Predictor `risk_assessment`
**Issue prefix:** `PERF`

Focus on:
- Performance regressions
- Algorithmic complexity concerns
- Resource usage (memory, CPU, I/O)
- Only flag issues where measurable impact is likely (per Review Preferences)

→ Follow **Review Section Protocol**

## Final Verdict

Based on combined agent outputs, determine one of:

**PROCEED:** All conditions met:
- `Monitor.verdict = 'approved'` AND `Monitor.valid = true`
- `Evaluator.recommendation = 'proceed'`

**REVISE:** Any condition true:
- `Monitor.verdict = 'needs_revision'`
- `Evaluator.recommendation = 'improve'`

**BLOCK:** Any condition true (highest priority):
- `Monitor.verdict = 'rejected'`
- `Evaluator.recommendation = 'reconsider'`
- `Evaluator.scores.security < 5`
- `Evaluator.scores.functionality < 5`
- `Predictor.risk_assessment = 'high'` AND `predicted_state.breaking_changes` is non-empty

**Priority:** BLOCK > REVISE > PROCEED

Present the verdict with a summary table:
- Monitor verdict + valid status
- Evaluator overall score + recommendation
- Predictor risk assessment
- Key issues resolved during interactive review
- Remaining action items

## CI/Auto Mode Behavior

When `CI_MODE = true` (triggered by `--ci` or `--auto` in $ARGUMENTS):
- Skip all AskUserQuestion calls
- Auto-select BIG mode (4 issues per section)
- Auto-select recommended options for all issues
- Present all 4 sections as a batch report (no pauses between sections)
- Output structured verdict at the end
- Suitable for CI pipelines and automated review contexts

## MCP Tools Used

- `mcp__sequential-thinking__sequentialthinking` — Complex analysis decisions during interactive presentation

---

**Begin review now.**
