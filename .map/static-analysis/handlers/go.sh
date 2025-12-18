#!/bin/bash
# Go Static Analysis Handler
# Tools: go vet, gofmt, staticcheck (if available)
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
    FILES="./..."
fi

TOOLS_RUN=()
ALL_FINDINGS="[]"

# Run go vet
if command -v go &> /dev/null; then
    TOOLS_RUN+=("go vet")
    VET_OUT=$(timeout 30 go vet "$FILES" 2>&1 || true)

    if [[ -n "$VET_OUT" ]]; then
        VET_NORM=$(echo "$VET_OUT" | grep -E "^[^:]+:[0-9]+:" | while IFS=: read -r file line rest; do
            message=$(echo "$rest" | sed 's/"/\\"/g' | xargs)
            echo "{\"tool\":\"go vet\",\"file\":\"$file\",\"line\":$line,\"column\":0,\"severity\":\"error\",\"code\":\"vet\",\"message\":\"$message\",\"fixable\":false}"
        done | jq -s '.' 2>/dev/null || echo "[]")

        if [[ -n "$VET_NORM" && "$VET_NORM" != "null" ]]; then
            ALL_FINDINGS=$(echo "$ALL_FINDINGS $VET_NORM" | jq -s 'add // []')
        fi
    fi
fi

# Run gofmt check
if command -v gofmt &> /dev/null; then
    TOOLS_RUN+=("gofmt")
    # gofmt -l lists files that need formatting
    if [[ "$FILES" == "./..." ]]; then
        # Use null-delimited output from find to safely handle filenames with spaces
        FMT_OUT=$(find . -name "*.go" -not -path "./vendor/*" -print0 2>/dev/null | xargs -0 gofmt -l 2>/dev/null || true)
    else
        FMT_OUT=$(gofmt -l "$FILES" 2>/dev/null || true)
    fi

    if [[ -n "$FMT_OUT" ]]; then
        FMT_NORM=$(echo "$FMT_OUT" | while read -r file; do
            echo "{\"tool\":\"gofmt\",\"file\":\"$file\",\"line\":1,\"column\":0,\"severity\":\"warning\",\"code\":\"format\",\"message\":\"File needs formatting\",\"fixable\":true}"
        done | jq -s '.' 2>/dev/null || echo "[]")

        if [[ -n "$FMT_NORM" && "$FMT_NORM" != "null" ]]; then
            ALL_FINDINGS=$(echo "$ALL_FINDINGS $FMT_NORM" | jq -s 'add // []')
        fi
    fi
fi

# Run staticcheck (if available)
if command -v staticcheck &> /dev/null; then
    TOOLS_RUN+=("staticcheck")
    SC_OUT=$(timeout 60 staticcheck -f json "$FILES" 2>/dev/null || echo "")

    if [[ -n "$SC_OUT" ]]; then
        # staticcheck outputs NDJSON (one JSON object per line)
        # Use jq -s to slurp all objects into an array, then transform each
        SC_NORM=$(echo "$SC_OUT" | jq -s '[.[] | {
            tool: "staticcheck",
            file: .location.file,
            line: .location.line,
            column: .location.column,
            severity: (if .severity == "error" then "error" else "warning" end),
            code: .code,
            message: .message,
            fixable: false
        }]' 2>/dev/null || echo "[]")

        if [[ -n "$SC_NORM" && "$SC_NORM" != "null" && "$SC_NORM" != "[]" ]]; then
            ALL_FINDINGS=$(echo "$ALL_FINDINGS $SC_NORM" | jq -s 'add // []')
        fi
    fi
fi

# Calculate summary
ERROR_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="error")] | length')
WARNING_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="warning")] | length')
TOTAL_COUNT=$(echo "$ALL_FINDINGS" | jq 'length')

# Convert tools array to JSON (handle empty array safely)
if [[ ${#TOOLS_RUN[@]} -gt 0 ]]; then
    TOOLS_JSON=$(printf '%s\n' "${TOOLS_RUN[@]}" | jq -R . | jq -s .)
else
    TOOLS_JSON="[]"
fi

# Output normalized JSON
jq -n \
    --argjson findings "$ALL_FINDINGS" \
    --argjson errors "$ERROR_COUNT" \
    --argjson warnings "$WARNING_COUNT" \
    --argjson total "$TOTAL_COUNT" \
    --argjson tools "$TOOLS_JSON" \
    '{
        success: true,
        language: "go",
        summary: {
            total: $total,
            errors: $errors,
            warnings: $warnings,
            pass: ($errors == 0)
        },
        findings: $findings,
        tools_run: $tools
    }'
