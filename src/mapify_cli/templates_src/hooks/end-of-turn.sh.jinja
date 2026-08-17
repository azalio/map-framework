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
#   - Stop-hook re-entry is honored (stop_hook_active) and persistent findings
#     are self-capped, so a finding the agent cannot resolve inside the turn
#     never livelocks the session (#437)
#   - Before the first commit, per-language gates run only on files the current
#     turn actually wrote (stateful snapshot), not on every untracked file (#438)
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

# -----------------------------------------------------------------------------
# Stop-hook Re-entry Guard (#437)
# -----------------------------------------------------------------------------
# Claude Code re-invokes a Stop hook that blocked, passing 'stop_hook_active:
# true' in the hook input, so the hook can let the turn end instead of blocking
# forever. Without this check, any finding that cannot be resolved inside the
# turn (human decision, upstream fix, action outside the agent's authority)
# livelocks the session: the turn tries to end, the hook blocks again, forever.
if [[ ! -t 0 ]]; then
    HOOK_INPUT="$(cat 2>/dev/null || true)"
    if printf '%s' "$HOOK_INPUT" | grep -qE '"stop_hook_active"[[:space:]]*:[[:space:]]*"*true'; then
        log "stop_hook_active=true, letting the turn end"
        echo '{}'
        exit 0
    fi
fi

# -----------------------------------------------------------------------------
# Early Exit: Check for Dirty State
# -----------------------------------------------------------------------------

# Not a git repo? Exit silently.
if ! git rev-parse --git-dir &>/dev/null; then
    echo '{}'
    exit 0
fi

# Runtime state lives inside the git dir, so it never pollutes the working tree
# and never shows up in 'git status'. Used by:
#   - the no-commit changed-file snapshot (#438)
#   - the repeated-finding self-cap (#437)
GIT_DIR_PATH="$(git rev-parse --git-dir 2>/dev/null || true)"
STATE_DIR="$GIT_DIR_PATH/mapify-end-of-turn"
SNAPSHOT_FILE="$STATE_DIR/untracked.snapshot"
BLOCK_STATE_FILE="$STATE_DIR/block.state"

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
if git rev-parse --verify HEAD &>/dev/null; then
    UNSTAGED=$(git diff --name-only HEAD 2>/dev/null || true)
    if [[ -n "$UNSTAGED" ]]; then
        CHANGED_FILES="$CHANGED_FILES"$'\n'"$UNSTAGED"
    fi
fi

# Untracked files.
# With HEAD present, plain 'git ls-files --others' is fine. Before the first
# commit there is no baseline, so it would report every init-created file as
# "changed" on every turn and the per-language gates would fire on unrelated
# turns (#438). In that state we gate only files the current turn actually
# wrote: untracked files that are new or were modified since the previous hook
# run ended (their mtime is newer than the snapshot written at the end of that
# run). The very first run has no baseline and treats everything as changed.
NO_HEAD_MODE=0
if git rev-parse --verify HEAD &>/dev/null; then
    UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null || true)
else
    NO_HEAD_MODE=1
    UNTRACKED=""
    CURRENT_UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null || true)
    if [[ -f "$SNAPSHOT_FILE" ]]; then
        while IFS= read -r file; do
            [[ -z "$file" ]] && continue
            if find "$file" -newer "$SNAPSHOT_FILE" -print 2>/dev/null | grep -q .; then
                UNTRACKED="$UNTRACKED"$'\n'"$file"
            fi
        done <<< "$CURRENT_UNTRACKED"
    else
        UNTRACKED="$CURRENT_UNTRACKED"
    fi
fi
if [[ -n "$UNTRACKED" ]]; then
    CHANGED_FILES="$CHANGED_FILES"$'\n'"$UNTRACKED"
fi

# Remove empty lines and duplicates
CHANGED_FILES=$(echo "$CHANGED_FILES" | grep -v '^$' | sort -u || true)

# Persist the untracked snapshot (no-commit repos only) so the next turn can
# tell which files are new. Written at the end of the run so its mtime marks
# "previous run finished" for the -newer comparison above.
persist_snapshot() {
    if [[ "$NO_HEAD_MODE" == "1" ]]; then
        mkdir -p "$STATE_DIR" 2>/dev/null || true
        printf '%s\n' "$CURRENT_UNTRACKED" | grep -v '^$' | sort -u > "$SNAPSHOT_FILE" 2>/dev/null || true
    fi
}

if [[ -z "$CHANGED_FILES" ]]; then
    persist_snapshot
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
            ruff check --fix --quiet "$file" >/dev/null 2>&1 || true
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
# We use 'ast.parse' instead of 'py_compile' because 'py_compile' always
# writes '__pycache__/*.pyc' next to the source — even with '-B' or
# PYTHONDONTWRITEBYTECODE, since emitting bytecode is 'py_compile''s entire
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
    GO_FILES=""
    for file in $CHANGED_FILES; do
        if [[ "$file" == *.go ]] && [[ -f "$file" ]]; then
            GO_FILES="$GO_FILES $file"
        fi
    done
    if [[ -n "$GO_FILES" ]]; then
        # Quick syntax check via go build with no output
        if ! go build -o /dev/null ./... 2>/dev/null; then
            add_critical "Go build errors detected (run 'go build ./...' for details)"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# Repeated-finding Self-cap (#437)
# -----------------------------------------------------------------------------
# A Stop hook that blocks on a finding the agent cannot resolve within the turn
# would re-block the end of every subsequent turn forever (livelock). The
# primary guard is the stop_hook_active re-entry check above; this cap is the
# fallback for harnesses that do not re-invoke Stop hooks with that flag: after
# N consecutive turns with the exact same critical findings the hook stops
# blocking and downgrades to a non-blocking warning so the session can proceed.
if [[ ${#CRITICAL_ISSUES[@]} -gt 0 ]]; then
    BLOCK_CAP="${MAPIFY_END_OF_TURN_BLOCK_CAP:-3}"
    [[ "$BLOCK_CAP" =~ ^[0-9]+$ ]] || BLOCK_CAP=3
    ISSUES_TEXT="$(printf '%s\n' "${CRITICAL_ISSUES[@]}")"
    COUNT=1
    if [[ -f "$BLOCK_STATE_FILE" ]]; then
        PREV_COUNT="$(sed -n '1s/^count=//p' "$BLOCK_STATE_FILE" 2>/dev/null || true)"
        PREV_TEXT="$(sed -n '3,$p' "$BLOCK_STATE_FILE" 2>/dev/null || true)"
        if [[ "$PREV_TEXT" == "$ISSUES_TEXT" ]] && [[ "$PREV_COUNT" =~ ^[0-9]+$ ]]; then
            COUNT=$((PREV_COUNT + 1))
        fi
    fi
    mkdir -p "$STATE_DIR" 2>/dev/null || true
    printf 'count=%s\n---\n%s\n' "$COUNT" "$ISSUES_TEXT" > "$BLOCK_STATE_FILE" 2>/dev/null || true
    if [[ "$COUNT" -gt "$BLOCK_CAP" ]]; then
        echo "⚠️  Same critical issue for $((COUNT - 1)) consecutive turns (self-capped, no longer blocking):" >&2
        for issue in "${CRITICAL_ISSUES[@]}"; do
            echo "  - $issue" >&2
        done
        echo "" >&2
        echo "Run /map-check for full diagnostics. Set MAPIFY_END_OF_TURN_BLOCK_CAP to adjust the cap." >&2
        persist_snapshot
        exit 1
    fi
else
    # No critical issues this turn: reset the repeat counter.
    rm -f "$BLOCK_STATE_FILE" 2>/dev/null || true
fi

# -----------------------------------------------------------------------------
# Report Results
# -----------------------------------------------------------------------------

persist_snapshot

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
