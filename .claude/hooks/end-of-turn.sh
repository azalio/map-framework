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

get_time_ms() {
    # Get current time in milliseconds (POSIX-compatible)
    # Uses python as fallback if date doesn't support %N
    if date +%s%3N 2>/dev/null | grep -qE '^[0-9]+$'; then
        date +%s%3N
    elif command -v python3 &>/dev/null; then
        python3 -c 'import time; print(int(time.time() * 1000))'
    elif command -v python &>/dev/null; then
        python -c 'import time; print(int(time.time() * 1000))'
    else
        # Fallback: seconds * 1000 (less precise)
        echo $(($(date +%s) * 1000))
    fi
}

get_branch_name() {
    # Extract current git branch name, default to 'default' if not in git repo
    if git rev-parse --git-dir &>/dev/null; then
        git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "default"
    else
        echo "default"
    fi
}

call_verification_recorder() {
    # Record verification result to .map/verification_results_<branch>.json
    # Non-blocking: failures don't stop the hook
    #
    # Args:
    #   $1: recipe_id (e.g., "check_ruff", "check_secrets")
    #   $2: status (pass|fail|skipped)
    #   $3: summary (human-readable description)
    #   $4: duration_ms (optional, milliseconds)

    local recipe_id="$1"
    local status="$2"
    local summary="$3"
    local duration_ms="${4:-}"

    local branch
    branch=$(get_branch_name)

    # Build command args
    local cmd_args=("$branch" "$recipe_id" "$status" "$summary")
    if [[ -n "$duration_ms" ]]; then
        cmd_args+=("$duration_ms")
    fi

    # Call verification recorder (non-blocking)
    # Use || true to prevent hook failure if recorder fails
    python -m mapify_cli.verification_recorder "${cmd_args[@]}" 2>/dev/null || true
}

run_check() {
    local name="$1"
    local cmd="$2"
    local recipe_id="${3:-check_${name// /_}}"  # Default: sanitize name to recipe_id

    log "Running: $name"

    # Measure duration using POSIX-compatible timing
    local start_ms
    start_ms=$(get_time_ms)

    if timeout "$TIMEOUT" bash -c "$cmd" 2>/dev/null; then
        local end_ms
        end_ms=$(get_time_ms)
        local duration=$((end_ms - start_ms))
        log "✓ $name passed"

        # Record success
        call_verification_recorder "$recipe_id" "pass" "$name passed" "$duration"
        return 0
    else
        local end_ms
        end_ms=$(get_time_ms)
        local duration=$((end_ms - start_ms))
        log "✗ $name failed (non-blocking)"
        add_warning "$name failed"

        # Record failure
        call_verification_recorder "$recipe_id" "fail" "$name failed" "$duration"
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
        run_check "ruff" "ruff check . --quiet" "check_ruff"
    fi

    # Black (formatter check)
    if command -v black &>/dev/null; then
        run_check "black" "black --check --quiet . 2>/dev/null" "check_black"
    fi

    # MyPy (type checker) - only if configured
    if command -v mypy &>/dev/null && [[ -f "mypy.ini" || -f "pyproject.toml" ]]; then
        # Check src/ directory if it exists, otherwise check current directory
        if [[ -d "src" ]]; then
            run_check "mypy" "mypy src/ --ignore-missing-imports --no-error-summary 2>/dev/null" "check_mypy"
        else
            run_check "mypy" "mypy . --ignore-missing-imports --no-error-summary 2>/dev/null" "check_mypy"
        fi
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
        run_check "npm lint" "npm run lint --silent 2>/dev/null" "check_npm_lint"
    fi

    # Run typecheck if TypeScript
    if is_typescript; then
        if grep -q '"typecheck"' package.json 2>/dev/null; then
            run_check "typecheck" "npm run typecheck --silent 2>/dev/null" "check_typecheck"
        elif command -v tsc &>/dev/null; then
            run_check "tsc" "tsc --noEmit 2>/dev/null" "check_tsc"
        fi
    fi
}

check_go() {
    log "Detected Go project"

    # Go vet
    if command -v go &>/dev/null; then
        run_check "go vet" "go vet ./... 2>/dev/null" "check_go_vet"
    fi

    # Staticcheck
    if command -v staticcheck &>/dev/null; then
        run_check "staticcheck" "staticcheck ./... 2>/dev/null" "check_staticcheck"
    fi
}

check_rust() {
    log "Detected Rust project"

    # Cargo check (fast type checking)
    if command -v cargo &>/dev/null; then
        run_check "cargo check" "cargo check --quiet 2>/dev/null" "check_cargo_check"
    fi

    # Clippy (linter)
    if command -v cargo &>/dev/null; then
        run_check "clippy" "cargo clippy --quiet -- -D warnings 2>/dev/null" "check_clippy"
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

    local start_ms
    start_ms=$(get_time_ms)

    local staged_files
    staged_files=$(git diff --cached --name-only 2>/dev/null || true)

    if [[ -z "$staged_files" ]]; then
        local end_ms
        end_ms=$(get_time_ms)
        local duration=$((end_ms - start_ms))
        call_verification_recorder "check_secrets" "skipped" "No staged files to check" "$duration"
        return 0
    fi

    # Check for hardcoded secrets (simplified pattern)
    local secret_patterns='(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)\s*[=:]\s*["\x27][A-Za-z0-9_\-]{8,}'
    local found_secrets=false

    while IFS= read -r file; do
        if [[ -f "$file" ]] && grep -qE "$secret_patterns" "$file" 2>/dev/null; then
            add_critical "Possible hardcoded secret in staged file: $file"
            found_secrets=true
        fi
    done <<< "$staged_files"

    local end_ms
    end_ms=$(get_time_ms)
    local duration=$((end_ms - start_ms))

    if [[ "$found_secrets" == "true" ]]; then
        call_verification_recorder "check_secrets" "fail" "Hardcoded secrets found in staged files" "$duration"
    else
        call_verification_recorder "check_secrets" "pass" "No secrets found in staged files" "$duration"
    fi
}

check_env_committed() {
    log "Checking .env not staged"

    if ! git rev-parse --git-dir &>/dev/null; then
        return 0
    fi

    local start_ms
    start_ms=$(get_time_ms)

    if git diff --cached --name-only 2>/dev/null | grep -q "^\.env"; then
        local end_ms
        end_ms=$(get_time_ms)
        local duration=$((end_ms - start_ms))
        add_critical ".env file is staged for commit!"
        call_verification_recorder "check_env_committed" "fail" ".env file is staged" "$duration"
    else
        local end_ms
        end_ms=$(get_time_ms)
        local duration=$((end_ms - start_ms))
        call_verification_recorder "check_env_committed" "pass" ".env not staged" "$duration"
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

    echo '{}'
    exit 0
}

main "$@"
