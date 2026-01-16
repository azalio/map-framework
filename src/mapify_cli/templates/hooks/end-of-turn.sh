#!/usr/bin/env bash
# =============================================================================
# End-of-Turn Quality Gate Hook
# =============================================================================
#
# This hook runs when Claude finishes responding (Stop event).
# It performs quality checks to catch issues before they accumulate.
#
# Exit codes:
#   0 = Success (continue normally)
#   1 = Error shown to user (non-blocking warning)
#   2 = Block and feed stderr to Claude (use sparingly for Stop hooks)
#
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Set to "true" to enable verbose logging
VERBOSE="${CLAUDE_HOOK_VERBOSE:-false}"

# Maximum time for checks (seconds)
TIMEOUT=30

# Track warnings
WARNINGS=()
CRITICAL_ISSUES=()

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[end-of-turn] $*" >&2
    fi
}

add_warning() {
    WARNINGS+=("$1")
}

add_critical() {
    CRITICAL_ISSUES+=("$1")
}

run_check() {
    local name="$1"
    local cmd="$2"
    
    log "Running: $name"
    
    if timeout "$TIMEOUT" bash -c "$cmd" 2>/dev/null; then
        log "✓ $name passed"
        return 0
    else
        log "✗ $name failed (non-blocking)"
        add_warning "$name failed"
        return 0  # Don't fail the hook, just log
    fi
}

# -----------------------------------------------------------------------------
# Detect Project Type
# -----------------------------------------------------------------------------

is_python() {
    # Require a project marker file, not just .py files presence
    # Running linters on arbitrary .py files without project config causes false positives
    [[ -f "pyproject.toml" ]] || [[ -f "setup.py" ]] || [[ -f "requirements.txt" ]]
}

is_nodejs() {
    [[ -f "package.json" ]]
}

is_typescript() {
    [[ -f "tsconfig.json" ]]
}

is_go() {
    [[ -f "go.mod" ]]
}

is_rust() {
    [[ -f "Cargo.toml" ]]
}

# -----------------------------------------------------------------------------
# Project-Specific Checks
# -----------------------------------------------------------------------------

check_python() {
    log "Detected Python project"
    
    # Ruff (fast Python linter)
    if command -v ruff &>/dev/null; then
        run_check "ruff" "ruff check . --quiet"
    fi
    
    # Black (formatter check)
    if command -v black &>/dev/null; then
        run_check "black" "black --check --quiet . 2>/dev/null"
    fi
    
    # MyPy (type checker) - only if configured
    if command -v mypy &>/dev/null && [[ -f "mypy.ini" || -f "pyproject.toml" ]]; then
        run_check "mypy" "mypy . --ignore-missing-imports --no-error-summary 2>/dev/null"
    fi
}

check_nodejs() {
    log "Detected Node.js project"
    
    # Check if node_modules exists
    if [[ ! -d "node_modules" ]]; then
        log "node_modules missing, skipping npm checks"
        return 0
    fi
    
    # Run lint if available
    if grep -q '"lint"' package.json 2>/dev/null; then
        run_check "npm lint" "npm run lint --silent 2>/dev/null"
    fi
    
    # Run typecheck if TypeScript
    if is_typescript; then
        if grep -q '"typecheck"' package.json 2>/dev/null; then
            run_check "typecheck" "npm run typecheck --silent 2>/dev/null"
        elif command -v tsc &>/dev/null; then
            run_check "tsc" "tsc --noEmit 2>/dev/null"
        fi
    fi
}

check_go() {
    log "Detected Go project"
    
    # Go vet
    if command -v go &>/dev/null; then
        run_check "go vet" "go vet ./... 2>/dev/null"
    fi
    
    # Staticcheck
    if command -v staticcheck &>/dev/null; then
        run_check "staticcheck" "staticcheck ./... 2>/dev/null"
    fi
}

check_rust() {
    log "Detected Rust project"
    
    # Cargo check (fast type checking)
    if command -v cargo &>/dev/null; then
        run_check "cargo check" "cargo check --quiet 2>/dev/null"
    fi
    
    # Clippy (linter)
    if command -v cargo &>/dev/null; then
        run_check "clippy" "cargo clippy --quiet -- -D warnings 2>/dev/null"
    fi
}

# -----------------------------------------------------------------------------
# Universal Checks
# -----------------------------------------------------------------------------

check_secrets() {
    log "Checking for exposed secrets in staged files"
    
    # Only check if in git repo
    if ! git rev-parse --git-dir &>/dev/null; then
        return 0
    fi
    
    local staged_files
    staged_files=$(git diff --cached --name-only 2>/dev/null || true)
    
    if [[ -z "$staged_files" ]]; then
        return 0
    fi
    
    # Check for hardcoded secrets (simplified pattern)
    local secret_patterns='(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)\s*[=:]\s*["\x27][A-Za-z0-9_\-]{8,}'
    
    while IFS= read -r file; do
        if [[ -f "$file" ]] && grep -qE "$secret_patterns" "$file" 2>/dev/null; then
            add_critical "Possible hardcoded secret in staged file: $file"
        fi
    done <<< "$staged_files"
}

check_env_committed() {
    log "Checking .env not staged"
    
    if ! git rev-parse --git-dir &>/dev/null; then
        return 0
    fi
    
    if git diff --cached --name-only 2>/dev/null | grep -q "^\.env"; then
        add_critical ".env file is staged for commit!"
    fi
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
    log "Starting end-of-turn checks"
    
    # Run project-specific checks
    if is_python; then
        check_python
    fi
    
    if is_nodejs; then
        check_nodejs
    fi
    
    if is_go; then
        check_go
    fi
    
    if is_rust; then
        check_rust
    fi
    
    # Universal checks
    check_secrets
    check_env_committed
    
    log "End-of-turn checks complete"
    
    # Report results
    if [[ ${#CRITICAL_ISSUES[@]} -gt 0 ]]; then
        echo "⚠️  Critical issues found:" >&2
        for issue in "${CRITICAL_ISSUES[@]}"; do
            echo "  - $issue" >&2
        done
        exit 2  # Block and feed to Claude
    fi
    
    if [[ ${#WARNINGS[@]} -gt 0 ]]; then
        echo "⚠️  Warnings:" >&2
        for warning in "${WARNINGS[@]}"; do
            echo "  - $warning" >&2
        done
        exit 1  # Show warning to user
    fi
    
    exit 0
}

main "$@"
