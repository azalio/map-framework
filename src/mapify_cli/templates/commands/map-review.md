---
description: Comprehensive MAP review of changes using Monitor, Predictor, and Evaluator agents
---

# MAP Review Workflow

Review current changes using MAP agents for comprehensive quality analysis.

## What This Command Does

1. **Monitor** - Validates code correctness, security, standards compliance
2. **Predictor** - Analyzes impact on codebase, breaking changes, dependencies
3. **Evaluator** - Scores overall quality and provides actionable feedback

## Step 1: Query Playbook for Review Patterns

```bash
# Get review best practices
REVIEW_PATTERNS=$(mapify playbook query "code review" --limit 5)
```

## Step 2: Get Current Changes

```bash
# Get staged and unstaged changes
git diff HEAD
git status
```

## Step 3: Call Monitor Agent

```
Task(
  subagent_type="monitor",
  description="Review code changes",
  prompt="Review the following changes for code quality:

**Changes:**
[paste git diff output]

**Playbook Context:**
[paste relevant playbook bullets]

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
```

## Step 4: Call Predictor Agent

```
Task(
  subagent_type="predictor",
  description="Analyze change impact",
  prompt="Analyze the impact of these changes:

**Changes:**
[paste git diff output]

**Monitor Results:**
[paste monitor output]

Analyze:
- Affected files and modules
- Breaking changes (API, schema, behavior)
- Dependencies that need updates
- Risk assessment

Output JSON with:
- affected_files: array of {path, change_type, impact_level}
- breaking_changes: array of {type, description, mitigation}
- dependencies_affected: array of strings
- risk_level: 'low' | 'medium' | 'high'
- recommendations: array of strings"
)
```

## Step 5: Call Evaluator Agent

```
Task(
  subagent_type="evaluator",
  description="Score change quality",
  prompt="Evaluate the overall quality of these changes:

**Changes:**
[paste git diff output]

**Monitor Results:**
[paste monitor output]

**Predictor Results:**
[paste predictor output]

Provide quality assessment:
- Code quality score (0-100)
- Test coverage assessment
- Documentation completeness
- Maintainability score
- Overall verdict

Output JSON with:
- scores: {code_quality, test_coverage, documentation, maintainability, overall}
- verdict: 'excellent' | 'good' | 'acceptable' | 'needs_work' | 'reject'
- strengths: array of strings
- improvements_needed: array of strings
- final_recommendation: string"
)
```

## Step 6: Summary Report

Present combined findings:

### Review Summary
- **Monitor Verdict:** [verdict]
- **Predictor Risk Level:** [risk_level]
- **Evaluator Score:** [overall]/100

### Issues Found
[List issues by severity]

### Recommendations
[Actionable next steps]

---

## 💡 Optional: Preserve Review Learnings

If the review revealed valuable patterns or common issues worth preserving:

```
/map-learn [review summary with issues found and resolution patterns]
```

## MCP Tools Available

- `mcp__cipher__cipher_memory_search` - Search past review patterns
- `mcp__sequential-thinking__sequentialthinking` - Complex analysis decisions
