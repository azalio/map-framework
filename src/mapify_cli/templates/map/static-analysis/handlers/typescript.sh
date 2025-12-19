#!/bin/bash
# TypeScript/JavaScript Static Analysis Handler
# Tools: eslint, tsc (TypeScript compiler)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

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

# Run eslint (if available)
if command -v eslint &> /dev/null || [[ -x "./node_modules/.bin/eslint" ]]; then
    ESLINT_CMD="eslint"
    if [[ -x "./node_modules/.bin/eslint" ]]; then
        ESLINT_CMD="./node_modules/.bin/eslint"
    fi

    TOOLS_RUN+=("eslint")
    ESLINT_OUT=$(timeout 60 "$ESLINT_CMD" --format json "$FILES" 2>/dev/null || echo "[]")

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

        add_findings "$ESLINT_NORM"
    fi
fi

# Run tsc type checking (if tsconfig.json exists)
if [[ -f "tsconfig.json" ]]; then
    TSC_CMD="tsc"
    if [[ -x "./node_modules/.bin/tsc" ]]; then
        TSC_CMD="./node_modules/.bin/tsc"
    fi

    if [[ -x "./node_modules/.bin/tsc" ]] || command -v tsc &> /dev/null; then
        TOOLS_RUN+=("tsc")
        TSC_OUT=$(timeout 60 "$TSC_CMD" --noEmit --pretty false 2>&1 || true)

        if [[ -n "$TSC_OUT" ]]; then
            # Parse format: file(line,col): error TSxxxx: message
            TSC_NORM=$(echo "$TSC_OUT" | while IFS= read -r line; do
                if [[ "$line" =~ ^(.+)\(([0-9]+),([0-9]+)\):\ error\ (TS[0-9]+):\ (.*)$ ]]; then
                    local file="${BASH_REMATCH[1]}"
                    local linenum="${BASH_REMATCH[2]}"
                    local col="${BASH_REMATCH[3]}"
                    local code="${BASH_REMATCH[4]}"
                    local message="${BASH_REMATCH[5]}"

                    file=$(json_escape "$file")
                    message=$(json_escape "$message")

                    echo "{\"tool\":\"tsc\",\"file\":\"$file\",\"line\":$linenum,\"column\":$col,\"severity\":\"error\",\"code\":\"$code\",\"message\":\"$message\",\"fixable\":false}"
                fi
            done | jq -s '.' 2>/dev/null || echo "[]")

            add_findings "$TSC_NORM"
        fi
    fi
fi

# Generate output using common function
generate_output "typescript"
