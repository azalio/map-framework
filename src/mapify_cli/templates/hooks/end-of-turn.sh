#!/usr/bin/env bash
# =============================================================================
# End-of-Turn Lightweight Hook
# =============================================================================
#
# This hook runs when Claude finishes responding (Stop event).
#
# DESIGN (per LLM Council recommendations):
#   - Only runs if there are uncommitted changes (dirty state)
#   - Checks only changed files, not the entire project
#   - Auto-fixes what it can (silent)
#   - Only reports critical issues that need manual intervention
#   - Full linting moved to /map-check command
#
# Exit codes:
#   0 = Success (continue normally)
#   1 = Warning shown to user (non-blocking)
#   2 = Block and feed stderr to Claude (critical issues only)
#
# =============================================================================

set -euo pipefail

# Recursion guard: no-op when MAP spawned this subprocess (MAP_INVOKED_BY set)
[ -n "${MAP_INVOKED_BY:-}" ] && exit 0

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

VERBOSE="${CLAUDE_HOOK_VERBOSE:-false}"
CRITICAL_ISSUES=()

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[end-of-turn] $*" >&2
    fi
}

add_critical() {
    CRITICAL_ISSUES+=("$1")
}

# Read a flat dotted key from .map/config.yaml using minimal stdlib Python.
# Falls back to $2 when the file is absent, the key is missing, or python3
# is unavailable.  Never raises: all errors are silently swallowed so the
# hook degrades gracefully to host defaults.
_read_map_config_value() {
    local key="$1" default="$2"
    if [[ ! -f ".map/config.yaml" ]] || ! command -v python3 &>/dev/null; then
        printf '%s' "$default"
        return
    fi
    python3 -B -c "
import re, sys
key, default = sys.argv[1], sys.argv[2]
try:
    text = open('.map/config.yaml', encoding='utf-8').read()
    m = re.search(r'^\s*' + re.escape(key) + r'\s*:\s*(\S+)', text, re.MULTILINE)
    print(m.group(1).strip() if m else default)
except Exception:
    print(default)
" "$key" "$default" 2>/dev/null || printf '%s' "$default"
}

# -----------------------------------------------------------------------------
# Early Exit: Check for Dirty State
# -----------------------------------------------------------------------------

# Not a git repo? Exit silently.
if ! git rev-parse --git-dir &>/dev/null; then
    echo '{}'
    exit 0
fi

# No changes? Exit silently.
if [[ -z "$(git status --porcelain 2>/dev/null)" ]]; then
    log "No changes detected, skipping checks"
    echo '{}'
    exit 0
fi

log "Changes detected, running lightweight checks"

# -----------------------------------------------------------------------------
# Get Changed Files
# -----------------------------------------------------------------------------

# Get changed files: staged + unstaged + untracked
CHANGED_FILES=""

# Staged files (works even with no commits)
STAGED=$(git diff --cached --name-only 2>/dev/null || true)
if [[ -n "$STAGED" ]]; then
    CHANGED_FILES="$STAGED"
fi

# Unstaged changes (only if HEAD exists)
if git rev-parse HEAD &>/dev/null; then
    UNSTAGED=$(git diff --name-only HEAD 2>/dev/null || true)
    if [[ -n "$UNSTAGED" ]]; then
        CHANGED_FILES="$CHANGED_FILES"$'\n'"$UNSTAGED"
    fi
fi

# Untracked files
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null || true)
if [[ -n "$UNTRACKED" ]]; then
    CHANGED_FILES="$CHANGED_FILES"$'\n'"$UNTRACKED"
fi

# Remove empty lines and duplicates
CHANGED_FILES=$(echo "$CHANGED_FILES" | grep -v '^$' | sort -u || true)

if [[ -z "$CHANGED_FILES" ]]; then
    log "No specific files to check"
    echo '{}'
    exit 0
fi

log "Changed files: $(echo "$CHANGED_FILES" | tr '\n' ' ')"

# -----------------------------------------------------------------------------
# Auto-Fix Layer (Silent)
# -----------------------------------------------------------------------------

# Python: ruff auto-fix
if command -v ruff &>/dev/null; then
    for file in $CHANGED_FILES; do
        if [[ "$file" == *.py ]] && [[ -f "$file" ]]; then
            ruff check --fix --quiet "$file" 2>/dev/null || true
        fi
    done
fi

# Go: gofmt auto-fix
if command -v gofmt &>/dev/null; then
    for file in $CHANGED_FILES; do
        if [[ "$file" == *.go ]] && [[ -f "$file" ]]; then
            gofmt -w "$file" 2>/dev/null || true
        fi
    done
fi

# -----------------------------------------------------------------------------
# Critical Checks Only (on changed files)
# -----------------------------------------------------------------------------

# Check for secrets in staged files (always critical)
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)
if [[ -n "$STAGED_FILES" ]]; then
    SECRET_PATTERN='(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)\s*[=:]\s*["'"'"'][A-Za-z0-9_\-]{8,}'
    while IFS= read -r file; do
        if [[ -f "$file" ]] && grep -qE "$SECRET_PATTERN" "$file" 2>/dev/null; then
            add_critical "Possible hardcoded secret in staged file: $file"
        fi
    done <<< "$STAGED_FILES"

    # Check for .env files staged
    if echo "$STAGED_FILES" | grep -q "^\.env"; then
        add_critical ".env file is staged for commit!"
    fi
fi

# Python: Check for syntax errors only (fast, critical).
# We use `ast.parse` instead of `py_compile` because `py_compile` always
# writes `__pycache__/*.pyc` next to the source — even with `-B` or
# PYTHONDONTWRITEBYTECODE, since emitting bytecode is `py_compile`'s entire
# job. Touching any .py under .map/scripts/ or src/mapify_cli/templates/ then
# leaves a tracked __pycache__/ that the template-hygiene gate
# (tests/test_template_render.py) rejects.
if command -v python3 &>/dev/null; then
    for file in $CHANGED_FILES; do
        if [[ "$file" == *.py ]] && [[ -f "$file" ]]; then
            if ! python3 -B -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "$file" 2>/dev/null; then
                add_critical "Python syntax error in: $file"
            fi
        fi
    done
fi

# Go: Check for compile errors only (fast, critical)
if command -v go &>/dev/null && [[ -f "go.mod" ]]; then
    # Allow disabling this check entirely via .map/config.yaml:
    #   checks.go.build: false
    _go_build_cfg=$(_read_map_config_value "checks.go.build" "true")
    case "$_go_build_cfg" in
        false|False|no|No|off|Off|0)
            log "Go build check disabled via checks.go.build config"
            ;;
        *)
            GO_FILES=""
            for file in $CHANGED_FILES; do
                if [[ "$file" == *.go ]] && [[ -f "$file" ]]; then
                    GO_FILES="$GO_FILES $file"
                fi
            done
            if [[ -n "$GO_FILES" ]]; then
                # Determine effective GOOS: env var takes precedence, then
                # .map/config.yaml checks.go.goos, then host default.
                # This prevents false criticals for Linux-only projects
                # developed on macOS (e.g. projects using cgroups/eBPF/netlink).
                #   Example config:  checks.go.goos: linux
                _go_goos="${GOOS:-$(_read_map_config_value 'checks.go.goos' '')}"
                _go_build_ok=true
                if [[ -n "$_go_goos" ]]; then
                    GOOS="$_go_goos" go build -o /dev/null ./... 2>/dev/null \
                        || _go_build_ok=false
                else
                    go build -o /dev/null ./... 2>/dev/null || _go_build_ok=false
                fi
                if [[ "$_go_build_ok" == "false" ]]; then
                    add_critical "Go build errors detected (run 'go build ./...' for details)"
                fi
            fi
            ;;
    esac
fi

# -----------------------------------------------------------------------------
# Report Results
# -----------------------------------------------------------------------------

if [[ ${#CRITICAL_ISSUES[@]} -gt 0 ]]; then
    echo "⚠️  Critical issues found:" >&2
    for issue in "${CRITICAL_ISSUES[@]}"; do
        echo "  - $issue" >&2
    done
    echo "" >&2
    echo "Run /map-check for full diagnostics" >&2
    exit 2  # Block and feed to Claude
fi

log "Lightweight checks passed"
echo '{}'
exit 0
