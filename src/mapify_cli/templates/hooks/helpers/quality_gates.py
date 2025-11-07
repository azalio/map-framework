#!/usr/bin/env python3
"""Helper script for stop hook: Run quality gates on modified files.

This script:
1. Takes a file path as input (the file that was just modified)
2. Runs appropriate checks based on file type:
   - Python (.py): syntax check (py_compile), pytest if tests exist
   - Go (.go): go fmt, go vet
   - TypeScript (.ts, .tsx): tsc --noEmit
   - Rust (.rs): rustc syntax check
3. Outputs JSON with check results

Note: This runs AFTER code is written, as a post-modification validation.
It's informational only - never blocks the response.
"""

import sys
import json
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Optional


def run_command(cmd: List[str], cwd: Optional[str] = None, timeout: int = 25) -> Dict:
    """Run a shell command and capture output.

    Args:
        cmd: Command and arguments as list
        cwd: Working directory (defaults to current)
        timeout: Timeout in seconds

    Returns:
        Dict with returncode, stdout, stderr
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": 124,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except Exception as e:
        return {"returncode": 1, "stdout": "", "stderr": str(e)}


def check_python_syntax(file_path: str) -> Dict:
    """Check Python file syntax using py_compile.

    Args:
        file_path: Path to Python file

    Returns:
        Check result dict with status, message, details
    """
    result = run_command(["python3", "-m", "py_compile", file_path])

    if result["returncode"] == 0:
        return {
            "name": "python_syntax",
            "status": "passed",
            "message": f"Syntax check passed: {file_path}",
            "details": None,
        }
    else:
        return {
            "name": "python_syntax",
            "status": "failed",
            "message": f"Syntax error in {file_path}",
            "details": result["stderr"],
        }


def check_go_syntax(file_path: str) -> Dict:
    """Check Go file syntax using go fmt and go vet.

    Args:
        file_path: Path to Go file

    Returns:
        Check result dict with status, message, details
    """
    # Check if go is available
    go_check = run_command(["which", "go"], timeout=2)
    if go_check["returncode"] != 0:
        return {
            "name": "go_syntax",
            "status": "skipped",
            "message": "go not installed",
            "details": None,
        }

    # Check formatting with go fmt -l (lists unformatted files)
    fmt_result = run_command(["go", "fmt", file_path])

    # Check for common issues with go vet
    vet_result = run_command(["go", "vet", file_path])

    errors = []
    if fmt_result["returncode"] != 0:
        errors.append(f"go fmt: {fmt_result['stderr']}")
    if vet_result["returncode"] != 0:
        errors.append(f"go vet: {vet_result['stderr']}")

    if not errors:
        return {
            "name": "go_syntax",
            "status": "passed",
            "message": f"Go checks passed: {file_path}",
            "details": None,
        }
    else:
        return {
            "name": "go_syntax",
            "status": "failed",
            "message": f"Go checks failed: {file_path}",
            "details": "\n".join(errors),
        }


def check_typescript_syntax(file_path: str) -> Dict:
    """Check TypeScript file syntax using tsc.

    Args:
        file_path: Path to TypeScript file

    Returns:
        Check result dict with status, message, details
    """
    # Check if tsc is available
    tsc_check = run_command(["which", "tsc"], timeout=2)
    if tsc_check["returncode"] != 0:
        return {
            "name": "typescript_syntax",
            "status": "skipped",
            "message": "tsc not installed",
            "details": None,
        }

    # Run tsc --noEmit for type checking without emitting files
    result = run_command(["tsc", "--noEmit", file_path])

    if result["returncode"] == 0:
        return {
            "name": "typescript_syntax",
            "status": "passed",
            "message": f"TypeScript check passed: {file_path}",
            "details": None,
        }
    else:
        return {
            "name": "typescript_syntax",
            "status": "failed",
            "message": f"TypeScript errors in {file_path}",
            "details": result["stdout"] + result["stderr"],
        }


def check_rust_syntax(file_path: str) -> Dict:
    """Check Rust file syntax using rustc.

    Args:
        file_path: Path to Rust file

    Returns:
        Check result dict with status, message, details
    """
    # Check if rustc is available
    rustc_check = run_command(["which", "rustc"], timeout=2)
    if rustc_check["returncode"] != 0:
        return {
            "name": "rust_syntax",
            "status": "skipped",
            "message": "rustc not installed",
            "details": None,
        }

    # Use rustc --crate-type lib for syntax check (works on stable and nightly)
    # Note: cargo check would be more comprehensive for projects with dependencies
    result = run_command(["rustc", "--crate-type", "lib", file_path], timeout=10)

    if result["returncode"] == 0:
        return {
            "name": "rust_syntax",
            "status": "passed",
            "message": f"Rust syntax check passed: {file_path}",
            "details": None,
        }
    else:
        return {
            "name": "rust_syntax",
            "status": "failed",
            "message": f"Rust syntax errors in {file_path}",
            "details": result["stderr"],
        }


def find_related_tests(file_path: str) -> Optional[str]:
    """Find test file(s) related to the modified file.

    Args:
        file_path: Path to modified file

    Returns:
        Path to test file or tests directory, or None if not found
    """
    path = Path(file_path)

    # Strategy 1: Look for test_{filename}.py in tests/ directory
    if path.name.startswith("test_"):
        # Already a test file
        return str(path)

    # Strategy 2: Look for corresponding test file
    test_filename = f"test_{path.stem}.py"

    # Check common test locations
    possible_locations = [
        path.parent / "tests" / test_filename,
        path.parent.parent / "tests" / test_filename,
        Path("tests") / test_filename,
    ]

    for test_path in possible_locations:
        if test_path.exists():
            return str(test_path)

    # Strategy 3: If file is in src/, run all tests (safer for shared code)
    if "src/" in str(path) or "mapify_cli/" in str(path):
        tests_dir = Path("tests")
        if tests_dir.exists() and tests_dir.is_dir():
            return str(tests_dir)

    return None


def run_pytest(target: Optional[str]) -> Dict:
    """Run pytest on specific test file or directory.

    Args:
        target: Test file/directory path, or None to skip

    Returns:
        Check result dict
    """
    if not target:
        return {
            "name": "pytest",
            "status": "skipped",
            "message": "No related tests found",
            "details": None,
        }

    # Check if pytest is available
    pytest_check = run_command(["python3", "-m", "pytest", "--version"], timeout=5)
    if pytest_check["returncode"] != 0:
        return {
            "name": "pytest",
            "status": "skipped",
            "message": "pytest not installed",
            "details": None,
        }

    # Run pytest with minimal verbosity
    result = run_command(
        [
            "python3",
            "-m",
            "pytest",
            target,
            "-v",
            "--tb=short",  # Short traceback format
            "-x",  # Stop at first failure (fast feedback)
        ],
        timeout=20,
    )

    if result["returncode"] == 0:
        # Count tests run
        stdout = result["stdout"]
        if "passed" in stdout:
            return {
                "name": "pytest",
                "status": "passed",
                "message": f"Tests passed: {target}",
                "details": stdout,
            }
        else:
            return {
                "name": "pytest",
                "status": "passed",
                "message": f"No tests collected from {target}",
                "details": stdout,
            }
    else:
        return {
            "name": "pytest",
            "status": "failed",
            "message": f"Tests FAILED: {target}",
            "details": f"{result['stdout']}\n{result['stderr']}",
        }


def run_quality_gates(file_path: str) -> Dict:
    """Run all quality gates for a file.

    Args:
        file_path: Path to modified file

    Returns:
        Dict with overall status and individual check results
    """
    checks = []
    path = Path(file_path)
    file_ext = path.suffix

    # Check 1: Syntax validation based on file type
    print(f"[quality_gates] Running syntax check on {file_path}...", file=sys.stderr)

    if file_ext == ".py":
        syntax_result = check_python_syntax(file_path)
        checks.append(syntax_result)

        # Check 2: Run related tests for Python files
        print("[quality_gates] Looking for related tests...", file=sys.stderr)
        test_target = find_related_tests(file_path)
        if test_target:
            print(f"[quality_gates] Found test target: {test_target}", file=sys.stderr)
        else:
            print("[quality_gates] No related tests found", file=sys.stderr)

        pytest_result = run_pytest(test_target)
        checks.append(pytest_result)

    elif file_ext == ".go":
        syntax_result = check_go_syntax(file_path)
        checks.append(syntax_result)

    elif file_ext in [".ts", ".tsx"]:
        syntax_result = check_typescript_syntax(file_path)
        checks.append(syntax_result)

    elif file_ext == ".rs":
        syntax_result = check_rust_syntax(file_path)
        checks.append(syntax_result)

    else:
        # Unknown file type
        checks.append(
            {
                "name": "syntax_check",
                "status": "skipped",
                "message": f"No syntax checker for {file_ext} files",
                "details": None,
            }
        )

    # Determine overall status
    failed_checks = [c for c in checks if c["status"] == "failed"]
    passed_checks = [c for c in checks if c["status"] == "passed"]
    skipped_checks = [c for c in checks if c["status"] == "skipped"]

    if failed_checks:
        overall_status = "failed"
        summary = f"{len(failed_checks)} check(s) failed, {len(passed_checks)} passed, {len(skipped_checks)} skipped"
    elif passed_checks:
        overall_status = "passed"
        summary = (
            f"All {len(passed_checks)} check(s) passed, {len(skipped_checks)} skipped"
        )
    else:
        overall_status = "skipped"
        summary = "All checks skipped"

    return {
        "file": file_path,
        "status": overall_status,
        "summary": summary,
        "checks": checks,
    }


def format_check_results(results: Dict) -> str:
    """Format check results as human-readable text.

    Args:
        results: Results dict from run_quality_gates

    Returns:
        Formatted string for stderr output
    """
    lines = []
    lines.append(f"\nFile: {results['file']}")
    lines.append(f"Status: {results['status'].upper()}")
    lines.append(f"Summary: {results['summary']}\n")

    for check in results["checks"]:
        status_icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️ "}.get(
            check["status"], "?"
        )

        lines.append(f"{status_icon} {check['name']}: {check['message']}")

        # Include details for failures
        if check["status"] == "failed" and check["details"]:
            # Limit details to last 20 lines to avoid spam
            details_lines = check["details"].split("\n")
            if len(details_lines) > 20:
                details_lines = details_lines[-20:]
                lines.append("   ... (truncated, showing last 20 lines) ...")
            lines.append("   " + "\n   ".join(details_lines))

    return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run quality gates on modified file")
    parser.add_argument("--file", required=True, help="Path to modified file")

    args = parser.parse_args()

    # Validate file exists
    if not Path(args.file).exists():
        print(f"[quality_gates] Error: File not found: {args.file}", file=sys.stderr)
        output = {
            "file": args.file,
            "status": "error",
            "summary": "File not found",
            "checks": [],
        }
        print(json.dumps(output, indent=2))
        return 1

    # Run quality gates
    results = run_quality_gates(args.file)

    # Output JSON to stdout
    print(json.dumps(results, indent=2))

    # Output human-readable format to stderr
    print(format_check_results(results), file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[quality_gates] Fatal error: {e}", file=sys.stderr)
        output = {"file": "unknown", "status": "error", "summary": str(e), "checks": []}
        print(json.dumps(output, indent=2))
        sys.exit(0)  # Exit 0 to avoid blocking (non-blocking mode)
