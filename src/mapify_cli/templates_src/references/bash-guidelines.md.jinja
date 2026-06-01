# Bash Command Guidelines

**Purpose:** Best practices for running Bash commands in MAP Framework workflows to avoid common issues.

---

## ⚠️ CRITICAL: Avoid Output Buffering Issues

### DO NOT use these patterns:

```bash
# ❌ BAD - causes buffering problems
command | head -n 10
command | tail -n 20
command | less
command | more

# ❌ BAD - output may hang indefinitely
git log | head -10
pytest | tail -50
make test | head -100
```

### ✅ DO use these patterns instead:

```bash
# ✅ GOOD - use command-specific flags
git log -n 10
git log --max-count=10

# ✅ GOOD - let commands complete fully
pytest  # Don't truncate, let it finish
make test  # Don't truncate

# ✅ GOOD - read files directly
cat logfile.txt  # Then process in memory if needed
head -n 10 logfile.txt  # Direct file read is OK
```

---

## When Checking Command Output

### Pattern 1: Run Commands Directly

```bash
# ✅ GOOD - direct execution
git status
pytest tests/
make lint

# Get full output, process in your code if truncation needed
```

### Pattern 2: Use Command-Specific Limits

```bash
# ✅ GOOD - built-in flags
git log -n 10                    # Last 10 commits
git log --oneline -20            # Last 20 commits (short)
git diff --stat                  # Summary only
git branch -r | head -10         # OK: head on list output

# ✅ GOOD - language-specific
pytest -x                        # Stop at first failure
pytest --maxfail=3               # Stop after 3 failures
pytest -k "test_auth"            # Run specific tests only
```

### Pattern 3: Direct File Reading

```bash
# ✅ GOOD - read files, don't pipe command output
cat .map/main/task_plan_main.md
head -n 50 logs/workflow.log
tail -f logs/monitor.log  # Follow mode is OK
```

---

## Why This Matters

### The Problem: Output Buffering

When you pipe a command through `head/tail/less/more`, the receiving process buffers output, but:
- The source command keeps running
- Output sits in buffer, never reaches you
- Command appears "hung" when it's actually waiting
- Especially bad with interactive tools (pytest, make)

### Examples of What Goes Wrong

```bash
# ❌ This hangs because pytest output is buffered:
pytest tests/ | head -50
# pytest keeps running, but you never see output past line 50
# pytest waits for terminal, but terminal is waiting for head

# ❌ This truncates meaningful output:
make test | tail -100
# You miss the FIRST errors, only see last 100 lines
# Makes debugging harder
```

---

## Command-Specific Best Practices

### Git Commands

```bash
# ✅ Viewing history
git log -n 10                    # Not: git log | head -10
git log --oneline --graph -20    # Not: git log --graph | head -20
git log --since="2 weeks ago"    # Time-based filter

# ✅ Checking status
git status                       # Always run full, it's fast
git diff --stat                  # Summary if diff is large
git diff --name-only             # Just filenames

# ✅ Branch listing
git branch -a                    # Full list (usually not huge)
git branch -r | grep pattern     # OK: grep is different from head/tail
```

### Test Commands

```bash
# ✅ Running tests
pytest                           # Let it complete
pytest tests/test_auth.py        # Specific file
pytest -k "test_oauth"           # Pattern match
pytest -x                        # Stop at first failure
pytest --tb=short                # Shorter tracebacks

# ✅ Checking coverage
pytest --cov=src                 # Full coverage report
pytest --cov-report=term-missing # Show missing lines
```

### Build Commands

```bash
# ✅ Building/linting
make lint                        # Full output needed
make test                        # Don't truncate test results
make build                       # Full build log important

# If output is truly massive, redirect to file:
make build > build.log 2>&1
# Then analyze file with head/tail/grep
```

### Log Monitoring

```bash
# ✅ Live monitoring
tail -f logs/app.log             # Follow mode is fine
tail -f logs/workflow.log | grep ERROR  # Filtering is OK

# ✅ Historical analysis
grep "ERROR" logs/app.log        # Direct file grep
awk '/ERROR/ {print $1,$5}' logs/app.log  # Process full file
```

---

## When You MUST Truncate

If command output is genuinely massive (>10K lines), use these strategies:

### Strategy 1: Filter, Don't Truncate

```bash
# ✅ Filter what you need
git log --author="alice" -n 20
pytest -k "test_critical"
grep "ERROR" huge_log.txt | head -50  # Grep first, then truncate
```

### Strategy 2: Redirect to File

```bash
# ✅ Save full output, analyze later
command > output.txt 2>&1
head -n 100 output.txt   # Analyze file safely
tail -n 100 output.txt
grep "pattern" output.txt
```

### Strategy 3: Use Command Limits

```bash
# ✅ Most tools have built-in limits
git log --max-count=50
pytest --maxfail=5
find . -name "*.py" -print -quit  # Stop after first match
```

---

## Quick Reference

| ❌ Avoid | ✅ Use Instead |
|---------|---------------|
| `git log \| head -10` | `git log -n 10` |
| `pytest \| tail -50` | `pytest -x` (stop at first failure) |
| `make test \| head -100` | `make test` (full output) |
| `ls -la \| less` | `ls -la` (terminal handles paging) |
| `command \| more` | `command` (let terminal scroll) |
| `cat file \| head -50` | `head -50 file` (direct read) |

---

## Actor/Monitor Agent Guidelines

**For Actor agents:**
- When running tests after code changes, use `pytest` directly
- Don't truncate test output - Monitor needs full results
- If test output is huge, use `pytest -k` to run subset

**For Monitor agents:**
- Run full test suites without truncation
- If checking logs, use `grep` to filter, not `head/tail`
- Read verification results from files, not truncated command output

**For all agents:**
- If you see a command hanging, check if you piped through head/tail
- Prefer command-specific flags over pipe truncation
- When in doubt, run command fully and process output in memory

---

## Exception: When Pipes Are OK

These pipes are SAFE because they don't cause buffering issues:

```bash
# ✅ Filtering (grep, awk, sed)
git log | grep "fix:"
ps aux | grep python
cat file.txt | sed 's/old/new/g'

# ✅ Transformation
ls -la | awk '{print $9}'
git status | grep modified

# ✅ Count/aggregate
git log | wc -l
pytest | grep PASSED | wc -l
```

The key difference: **filtering/transforming processes all input** vs **head/tail stop early and cause buffering**.

---

**Version:** 1.0.0
**Last Updated:** 2026-01-27
**Applies To:** All MAP Framework agents and commands
