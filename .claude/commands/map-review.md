---
description: Comprehensive MAP review of changes using Monitor, Predictor, and Evaluator agents
---

# MAP Review Workflow

Review current changes using MAP agents for comprehensive quality analysis.

## What This Command Does

1. **Monitor** - Validates code correctness, security, standards compliance
2. **Predictor** - Analyzes impact on codebase, breaking changes, dependencies
3. **Evaluator** - Scores overall quality and provides actionable feedback

## Step 1: Query mem0 for Review Patterns

```bash
# Get review best practices
REVIEW_PATTERNS=$(mcp__mem0__map_tiered_search(query="code review", limit=5))
```

## Step 2: Get Current Changes

```bash
# Get staged and unstaged changes
git diff HEAD
git status
```

## Step 3: Invoke All Review Agents in Parallel

**IMPORTANT**: Call Monitor, Predictor, and Evaluator simultaneously by invoking all three Task calls in a single message. These agents operate independently on the same git diff without shared state.

```
Task(
  subagent_type="monitor",
  description="Review code changes",
  prompt="Review the following changes for code quality:

**Changes:**
[paste git diff output]

**mem0 Context:**
[paste relevant mem0 patterns]

Check for:
- Code correctness and logic errors
- Security vulnerabilities (OWASP top 10)
- Standards compliance
- Test coverage gaps
- Performance issues

Output JSON with:
- valid: boolean
- issues: array of {severity, category, description, file_path, line_range, suggestion}
- verdict: 'approved' | 'needs_revision' | 'rejected'
- summary: string"
)

Task(
  subagent_type="predictor",
  description="Analyze change impact",
  prompt="Analyze the impact of these changes:

**Changes:**
[paste git diff output]

**mem0 Context:**
[paste relevant mem0 patterns]

Analyze:
- Affected files and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment
- Integration points affected

Output JSON with:
- affected_files: array of {path, change_type, impact_level}
- breaking_changes: array of {type, description, mitigation}
- dependencies_affected: array of strings
- risk_level: 'low' | 'medium' | 'high'
- recommendations: array of strings"
)

Task(
  subagent_type="evaluator",
  description="Score change quality",
  prompt="Evaluate the overall quality of these changes:

**Changes:**
[paste git diff output]

**mem0 Context:**
[paste relevant mem0 patterns]

Provide quality assessment using 1-10 scoring (matches evaluator agent template):
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

**How Parallel Execution Works:**
1. Claude Code will process all three Task calls from the same message
2. Each agent analyzes the git diff independently
3. Wait for all three Task calls to complete before proceeding
4. Collect results from Monitor, Predictor, and Evaluator outputs

## Step 4: Aggregate and Present Results

Once all three agents have completed, combine their findings:

### Review Summary

**Monitor Analysis:**
- Verdict: [monitor.verdict]
- Issues Found: [count by severity]
- Valid: [monitor.valid]

**Predictor Analysis:**
- Risk Level: [predictor.risk_level]
- Breaking Changes: [predictor.breaking_changes.length]
- Affected Files: [predictor.affected_files.length]

**Evaluator Assessment:**
- Overall Score: [evaluator.overall_score]/10
- Code Quality: [evaluator.scores.code_quality]/10
- Security: [evaluator.scores.security]/10
- Recommendation: [evaluator.recommendation]

### Critical Issues (High Severity)

[List high-severity issues from Monitor]

### Breaking Changes

[List breaking changes from Predictor]

### Recommendations

**From Monitor:**
[List Monitor suggestions for critical issues]

**From Predictor:**
[List Predictor recommendations]

**From Evaluator:**
[List Evaluator improvements needed]

### Final Verdict

Based on combined analysis:
- **Proceed if:** Monitor verdict = 'approved' AND Evaluator recommendation = 'proceed'
- **Revise if:** Monitor verdict = 'needs_revision' OR Evaluator recommendation = 'improve'
- **Block if:** Monitor verdict = 'rejected' OR Evaluator recommendation = 'reconsider' OR (Predictor risk_level = 'high' AND breaking_changes.length > 0)

---

## 💡 Optional: Preserve Review Learnings

If the review revealed valuable patterns or common issues worth preserving:

```
/map-learn [review summary with issues found and resolution patterns]
```

## MCP Tools Available

- `mcp__mem0__map_tiered_search` - Search past review patterns
- `mcp__sequential-thinking__sequentialthinking` - Complex analysis decisions
