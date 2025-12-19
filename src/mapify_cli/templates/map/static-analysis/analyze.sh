#!/bin/bash
# Static Analysis Dispatcher
# Invokes language-specific handlers and returns normalized JSON output
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANDLERS_DIR="${SCRIPT_DIR}/handlers"

# Default values
LANGUAGE=""
FILES=""
CONFIG="{}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --language) LANGUAGE="$2"; shift 2 ;;
        --files) FILES="$2"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Auto-detect language if not provided
if [[ -z "$LANGUAGE" || "$LANGUAGE" == "auto" ]]; then
    if [[ -f "pyproject.toml" || -f "requirements.txt" || -f "setup.py" ]]; then
        LANGUAGE="python"
    elif [[ -f "go.mod" ]]; then
        LANGUAGE="go"
    elif [[ -f "package.json" ]]; then
        # Check for TypeScript
        if [[ -f "tsconfig.json" ]]; then
            LANGUAGE="typescript"
        else
            LANGUAGE="javascript"
        fi
    elif [[ -f "Cargo.toml" ]]; then
        LANGUAGE="rust"
    else
        # Try to detect from file extensions using safer pattern checks
        if compgen -G "*.py" > /dev/null; then
            LANGUAGE="python"
        elif compgen -G "*.go" > /dev/null; then
            LANGUAGE="go"
        elif compgen -G "*.ts" > /dev/null; then
            LANGUAGE="typescript"
        else
            LANGUAGE="unknown"
        fi
    fi
fi

# Validate language against whitelist to prevent path traversal
case "$LANGUAGE" in
    python|go|javascript|typescript|rust|unknown)
        # allowed values
        ;;
    *)
        LANGUAGE="unknown"
        ;;
esac

# Check if handler exists
HANDLER="${HANDLERS_DIR}/${LANGUAGE}.sh"
if [[ ! -x "$HANDLER" ]]; then
    # Return JSON indicating no handler
    cat <<EOF
{
    "success": false,
    "language": "${LANGUAGE}",
    "error": "No handler for language: ${LANGUAGE}",
    "summary": { "total": 0, "errors": 0, "warnings": 0, "pass": true },
    "findings": [],
    "tools_run": []
}
EOF
    exit 0
fi

# Execute handler
"$HANDLER" --files "$FILES" --config "$CONFIG"
