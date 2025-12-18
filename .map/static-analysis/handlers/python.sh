#!/bin/bash
# Python Static Analysis Handler
# Tools: ruff (linting), mypy (type checking)
set -euo pipefail

FILES=""
CONFIG="{}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --files) FILES="$2"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# If no files specified, use current directory
if [[ -z "$FILES" ]]; then
    FILES="."
fi

TOOLS_RUN=()
ALL_FINDINGS="[]"

# Run ruff (if available)
if command -v ruff &> /dev/null; then
    TOOLS_RUN+=("ruff")
    RUFF_OUT=$(timeout 30 ruff check --output-format=json $FILES 2>/dev/null || echo "[]")

    # Normalize ruff output to standard format
    if [[ "$RUFF_OUT" != "[]" && -n "$RUFF_OUT" ]]; then
        RUFF_NORM=$(echo "$RUFF_OUT" | jq -c '[.[] | {
            tool: "ruff",
            file: .filename,
            line: .location.row,
            column: .location.column,
            severity: (if .code | startswith("F") then "error" elif .code | startswith("E") then "error" else "warning" end),
            code: .code,
            message: .message,
            fixable: (.fix != null)
        }]' 2>/dev/null || echo "[]")

        ALL_FINDINGS=$(echo "$ALL_FINDINGS $RUFF_NORM" | jq -s 'add // []')
    fi
fi

# Run mypy (if available)
if command -v mypy &> /dev/null; then
    TOOLS_RUN+=("mypy")
    MYPY_OUT=$(timeout 30 mypy --no-color-output --no-error-summary $FILES 2>&1 || true)

    # Parse mypy text output to JSON
    if [[ -n "$MYPY_OUT" ]]; then
        MYPY_NORM=$(echo "$MYPY_OUT" | grep -E "^[^:]+:[0-9]+:" | while IFS=: read -r file line col rest; do
            # Determine severity from message
            if echo "$rest" | grep -q "error:"; then
                severity="error"
            else
                severity="warning"
            fi
            message=$(echo "$rest" | sed 's/^ *error: //' | sed 's/^ *note: //' | sed 's/"/\\"/g')
            echo "{\"tool\":\"mypy\",\"file\":\"$file\",\"line\":$line,\"column\":${col:-0},\"severity\":\"$severity\",\"code\":\"mypy\",\"message\":\"$message\",\"fixable\":false}"
        done | jq -s '.' 2>/dev/null || echo "[]")

        if [[ -n "$MYPY_NORM" && "$MYPY_NORM" != "null" ]]; then
            ALL_FINDINGS=$(echo "$ALL_FINDINGS $MYPY_NORM" | jq -s 'add // []')
        fi
    fi
fi

# Calculate summary
ERROR_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="error")] | length')
WARNING_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="warning")] | length')
TOTAL_COUNT=$(echo "$ALL_FINDINGS" | jq 'length')

# Convert tools array to JSON
TOOLS_JSON=$(printf '%s\n' "${TOOLS_RUN[@]}" | jq -R . | jq -s .)

# Output normalized JSON
jq -n \
    --argjson findings "$ALL_FINDINGS" \
    --argjson errors "$ERROR_COUNT" \
    --argjson warnings "$WARNING_COUNT" \
    --argjson total "$TOTAL_COUNT" \
    --argjson tools "$TOOLS_JSON" \
    '{
        success: true,
        language: "python",
        summary: {
            total: $total,
            errors: $errors,
            warnings: $warnings,
            pass: ($errors == 0)
        },
        findings: $findings,
        tools_run: $tools
    }'
