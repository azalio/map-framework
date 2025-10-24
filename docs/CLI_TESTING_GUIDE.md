# CLI Testing Guide for MAP Framework

## Overview

This guide documents best practices for developing and testing CLI tools discovered during implementation of mapify CLI subcommands. Following these patterns prevents common issues with output pollution, version compatibility, and test-vs-reality mismatches.

## Table of Contents

1. [The Problem: Why CLI Tools Need Special Testing](#the-problem)
2. [Output Stream Management](#output-stream-management)
3. [Version Compatibility](#version-compatibility)
4. [Integration Testing](#integration-testing)
5. [Common Pitfalls](#common-pitfalls)
6. [Best Practices Checklist](#best-practices-checklist)

## The Problem

**Key Insight**: CliRunner behavior differs from actual CLI execution. Tests that pass with `runner.invoke()` may fail when users run the installed command.

### Real-World Example

**Scenario**: Implementing `mapify playbook sync` command that outputs JSON.

**What Happened**:
1. ✅ Unit tests passed with CliRunner
2. ❌ CI failed: `TypeError: CliRunner.__init__() got an unexpected keyword argument 'mix_stderr'`
3. ❌ Manual test revealed: JSON output polluted with diagnostic messages
4. ❌ User command `mapify playbook sync | jq` failed due to mixed stdout/stderr

**Root Causes**:
- SemanticSearchEngine printed "Loading model..." to stdout during initialization
- PlaybookManager printed "✓ Semantic search enabled" to stdout
- Used `CliRunner(mix_stderr=False)` parameter not available in older Click versions
- No integration test with actual CLI execution

## Output Stream Management

### Rule 1: Stdout is for Output, Stderr is for Diagnostics

**Why**: Users pipe CLI output through tools like `jq`, `grep`, `awk`. Diagnostic messages break pipes.

**Pattern**:

```python
import sys

# ❌ BAD: Pollutes stdout
print("Loading model...")
print("✓ Model loaded successfully")

# ✅ GOOD: Diagnostics go to stderr
print("Loading model...", file=sys.stderr)
print("✓ Model loaded successfully", file=sys.stderr)
```

### Rule 2: Verify Output Cleanliness

**Manual Validation**:

```bash
# Test JSON output is clean
mapify playbook sync | jq .

# If jq fails, stdout has pollution
mapify playbook sync 2>/dev/null | jq .  # Redirect stderr to verify

# Check what's in stderr
mapify playbook sync 2>&1 >/dev/null  # Show only stderr
```

**In Tests**:

```python
# Extract JSON from potentially mixed output
def test_json_output():
    result = runner.invoke(app, ["playbook", "sync"])

    # Find JSON start (handles diagnostic messages before JSON)
    json_start = result.stdout.find('{')
    assert json_start != -1, "No JSON found in output"

    json_str = result.stdout[json_start:]
    data = json.loads(json_str)  # Should not fail
    assert "status" in data
```

### Rule 3: Use Logging Module for Complex Cases

**Pattern**:

```python
import logging
import sys

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s',
    stream=sys.stderr
)

logger = logging.getLogger(__name__)

def command():
    logger.info("Starting process...")  # Goes to stderr
    result = do_work()
    print(json.dumps(result))  # Goes to stdout
```

## Version Compatibility

### Rule 1: Check Library Features Against Minimum Version

**Problem**: Using new library features that don't exist in CI environment.

**Example**:

```python
# ❌ BAD: mix_stderr added in Click 8.0, CI uses 7.x
from typer.testing import CliRunner
runner = CliRunner(mix_stderr=False)  # Fails in CI!

# ✅ GOOD: Backwards compatible approach
runner = CliRunner()  # Works everywhere
# Handle mixed streams in test assertions
```

**How to Check**:

```python
# Check Click/Typer version
import click
import typer
print(f"Click: {click.__version__}")
print(f"Typer: {typer.__version__}")

# Check parameter availability
from typer.testing import CliRunner
import inspect
sig = inspect.signature(CliRunner.__init__)
print("CliRunner parameters:", list(sig.parameters.keys()))
```

### Rule 2: Test with Minimum Supported Version

**In pyproject.toml**:

```toml
[project]
dependencies = [
    "click>=7.0",  # Specify minimum
    "typer>=0.9.0"
]
```

**In CI** (e.g., `.github/workflows/test.yml`):

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.12"]
    deps-version: ["minimum", "latest"]

- name: Install dependencies
  run: |
    if [ "${{ matrix.deps-version }}" = "minimum" ]; then
      pip install click==7.0 typer==0.9.0
    else
      pip install -e .
    fi
```

### Rule 3: Use Defensive Feature Detection

**Pattern**:

```python
def create_cli_runner():
    """Create CliRunner with best available features."""
    try:
        # Try newer feature
        from typer.testing import CliRunner
        return CliRunner(mix_stderr=False)
    except TypeError:
        # Fall back to compatible version
        return CliRunner()
```

## Integration Testing

### Rule 1: Always Test Actual CLI Execution

**Why**: CliRunner mocks environment. Real execution catches:
- Import issues
- Entry point configuration
- Environment variable handling
- Path resolution
- Package installation problems

**Pattern**:

```python
import subprocess
import sys

def test_cli_integration():
    """Test actual CLI command (not mocked)."""
    # Install package in editable mode
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], check=True)

    # Run actual CLI command
    result = subprocess.run(
        ["mapify", "playbook", "sync"],
        capture_output=True,
        text=True,
        timeout=30
    )

    assert result.returncode == 0

    # Verify output format
    json_start = result.stdout.find('{')
    assert json_start != -1
    data = json.loads(result.stdout[json_start:])
    assert "status" in data
```

### Rule 2: Test in Isolated Environment

**Using UV**:

```bash
# Create isolated environment
uv venv test_env
source test_env/bin/activate

# Install and test
uv tool install --force --editable .
mapify playbook sync

# Clean up
deactivate
rm -rf test_env
```

**In Tests**:

```python
import tempfile
import venv

def test_isolated_cli():
    """Test CLI in isolated virtual environment."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create venv
        venv.create(tmpdir, with_pip=True)

        # Install package
        pip = f"{tmpdir}/bin/pip"
        subprocess.run([pip, "install", "-e", "."], check=True)

        # Test command
        mapify = f"{tmpdir}/bin/mapify"
        result = subprocess.run([mapify, "playbook", "sync"], capture_output=True)
        assert result.returncode == 0
```

### Rule 3: Test Output Formats

**Pattern**:

```python
def test_json_output_clean():
    """Verify JSON output has no diagnostic pollution."""
    result = subprocess.run(
        ["mapify", "playbook", "sync"],
        capture_output=True,
        text=True
    )

    # Should be valid JSON (no diagnostic messages)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout is not clean JSON: {e}\nOutput: {result.stdout[:200]}")

    assert isinstance(data, dict)
```

## Common Pitfalls

### Pitfall 1: Assuming CliRunner == Real CLI

**Symptom**: Tests pass, users report command doesn't work.

**Example**:

```python
# ❌ Only tests with CliRunner
def test_sync():
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0

# ✅ Also tests real command
def test_sync_integration():
    result = subprocess.run(["mapify", "sync"], capture_output=True)
    assert result.returncode == 0
```

### Pitfall 2: Not Verifying Stream Separation

**Symptom**: `command | jq` works in tests but fails for users.

**Example**:

```python
# ❌ Doesn't verify stdout cleanliness
def test_sync():
    result = runner.invoke(app, ["sync"])
    data = json.loads(result.stdout)  # May work if diagnostic goes to stderr

# ✅ Verifies stdout has only JSON
def test_sync_clean():
    result = runner.invoke(app, ["sync"])
    # Verify stdout starts with { (no diagnostic prefix)
    assert result.stdout.strip().startswith('{'), \
        f"stdout has pollution: {result.stdout[:100]}"
```

### Pitfall 3: Library Dependency Prints to Stdout

**Symptom**: Your code doesn't print anything, but output is polluted.

**Detection**:

```bash
# Run command and capture stdout
mapify sync > output.json 2>/dev/null

# Check if it's valid JSON
cat output.json | jq .

# If fails, a dependency is printing to stdout
# Find the culprit:
python -c "
import sys
import io
sys.stdout = io.StringIO()  # Capture stdout
from mapify_cli import semantic_search  # Import suspected module
print('Captured:', repr(sys.stdout.getvalue()))
"
```

**Fix**:

```python
# In the offending module
import sys

# Replace print() with stderr
print("Loading...", file=sys.stderr)
```

### Pitfall 4: Tests Check Wrong Stream for Errors

**Symptom**: Error tests fail because Typer sends errors to stderr.

**Example**:

```python
# ❌ Only checks stdout
def test_invalid_command():
    result = runner.invoke(app, ["invalid"])
    assert "error" in result.stdout.lower()  # Fails! Error in stderr

# ✅ Checks both streams
def test_invalid_command():
    result = runner.invoke(app, ["invalid"])
    output = result.stdout + getattr(result, 'stderr', '')
    assert "error" in output.lower()
```

## Best Practices Checklist

### Before Writing Tests

- [ ] Identify if command outputs structured data (JSON, CSV, etc.)
- [ ] Check which libraries are imported (do they print?)
- [ ] Review minimum supported library versions
- [ ] Plan for both unit tests (CliRunner) and integration tests (subprocess)

### During Implementation

- [ ] Use `print(..., file=sys.stderr)` for ALL diagnostic output
- [ ] Use logging module for complex diagnostic needs
- [ ] Test command manually: `mapify command | jq .`
- [ ] Check library features are in minimum version

### During Testing

- [ ] Write CliRunner unit tests for logic
- [ ] Write subprocess integration tests for actual CLI
- [ ] Test with stdout piped to `jq` or `grep`
- [ ] Test in isolated environment (UV/venv)
- [ ] Verify JSON parsing doesn't fail

### Before Creating PR

- [ ] Run manual test: `uv tool install --force --editable . && mapify command`
- [ ] Verify CI uses compatible library versions
- [ ] Check test handles both mixed and separated streams
- [ ] Confirm no diagnostic messages in stdout

## Testing Workflow

### 1. Unit Test with CliRunner

```python
def test_playbook_sync():
    """Unit test with CliRunner."""
    result = runner.invoke(app, ["playbook", "sync"])
    assert result.exit_code == 0

    # Extract JSON robustly
    json_start = result.stdout.find('{')
    data = json.loads(result.stdout[json_start:])
    assert "status" in data
```

### 2. Integration Test with Subprocess

```python
def test_playbook_sync_integration():
    """Integration test with actual CLI."""
    result = subprocess.run(
        ["mapify", "playbook", "sync"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)  # Must be clean JSON
    assert "status" in data
```

### 3. Manual Verification

```bash
# Install and test
uv tool install --force --editable .

# Test basic execution
mapify playbook sync

# Test JSON output
mapify playbook sync | jq .

# Test with stderr redirected
mapify playbook sync 2>/dev/null | jq .

# Verify only JSON in stdout
mapify playbook sync 2>&1 >/dev/null  # Should show diagnostics
```

## Summary

**Key Takeaways**:

1. **Stdout = Output, Stderr = Diagnostics** - Always separate these
2. **CliRunner ≠ Real CLI** - Test both mocked and actual execution
3. **Version Matters** - Check library features against minimum version
4. **Manual Testing Required** - Run actual CLI before creating PR
5. **JSON Must Be Clean** - Test with `| jq` to verify

**When in Doubt**:
- Run the actual installed command
- Pipe through `jq` to verify clean output
- Test in isolated environment
- Check both stdout and stderr separately

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-24
**Related**: Monitor agent CLI validation, Predictor CLI risks, Reflector CLI patterns
