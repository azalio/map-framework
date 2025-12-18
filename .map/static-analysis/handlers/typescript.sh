#!/bin/bash
# TypeScript/JavaScript Static Analysis Handler
# Tools: eslint, tsc (TypeScript compiler)
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

# Run eslint (if available)
if command -v eslint &> /dev/null || [[ -x "./node_modules/.bin/eslint" ]]; then
    ESLINT_CMD="eslint"
    if [[ -x "./node_modules/.bin/eslint" ]]; then
        ESLINT_CMD="./node_modules/.bin/eslint"
    fi

    TOOLS_RUN+=("eslint")
    ESLINT_OUT=$(timeout 60 $ESLINT_CMD --format json $FILES 2>/dev/null || echo "[]")

    if [[ "$ESLINT_OUT" != "[]" && -n "$ESLINT_OUT" ]]; then
        ESLINT_NORM=$(echo "$ESLINT_OUT" | jq -c '[.[] | .filePath as $file | .messages[] | {
            tool: "eslint",
            file: $file,
            line: .line,
            column: .column,
            severity: (if .severity == 2 then "error" else "warning" end),
            code: (.ruleId // "eslint"),
            message: .message,
            fixable: (.fix != null)
        }]' 2>/dev/null || echo "[]")

        ALL_FINDINGS=$(echo "$ALL_FINDINGS $ESLINT_NORM" | jq -s 'add // []')
    fi
fi

# Run tsc type checking (if tsconfig.json exists)
if [[ -f "tsconfig.json" ]]; then
    TSC_CMD="tsc"
    if [[ -x "./node_modules/.bin/tsc" ]]; then
        TSC_CMD="./node_modules/.bin/tsc"
    fi

    if command -v $TSC_CMD &> /dev/null || [[ -x "./node_modules/.bin/tsc" ]]; then
        TOOLS_RUN+=("tsc")
        TSC_OUT=$(timeout 60 $TSC_CMD --noEmit --pretty false 2>&1 || true)

        if [[ -n "$TSC_OUT" ]]; then
            TSC_NORM=$(echo "$TSC_OUT" | grep -E "^[^(]+\([0-9]+,[0-9]+\):" | while read -r line; do
                # Parse format: file(line,col): error TSxxxx: message
                file=$(echo "$line" | sed -E 's/\([0-9]+,[0-9]+\):.*//')
                linenum=$(echo "$line" | sed -E 's/.*\(([0-9]+),[0-9]+\):.*/\1/')
                col=$(echo "$line" | sed -E 's/.*\([0-9]+,([0-9]+)\):.*/\1/')
                code=$(echo "$line" | sed -E 's/.*: (error TS[0-9]+):.*/\1/' | tr -d ' ')
                message=$(echo "$line" | sed -E 's/.*: error TS[0-9]+: //' | sed 's/"/\\"/g')

                echo "{\"tool\":\"tsc\",\"file\":\"$file\",\"line\":$linenum,\"column\":$col,\"severity\":\"error\",\"code\":\"$code\",\"message\":\"$message\",\"fixable\":false}"
            done | jq -s '.' 2>/dev/null || echo "[]")

            if [[ -n "$TSC_NORM" && "$TSC_NORM" != "null" ]]; then
                ALL_FINDINGS=$(echo "$ALL_FINDINGS $TSC_NORM" | jq -s 'add // []')
            fi
        fi
    fi
fi

# Calculate summary
ERROR_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="error")] | length')
WARNING_COUNT=$(echo "$ALL_FINDINGS" | jq '[.[] | select(.severity=="warning")] | length')
TOTAL_COUNT=$(echo "$ALL_FINDINGS" | jq 'length')

# Convert tools array to JSON
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
        language: "typescript",
        summary: {
            total: $total,
            errors: $errors,
            warnings: $warnings,
            pass: ($errors == 0)
        },
        findings: $findings,
        tools_run: $tools
    }'
