#!/bin/bash
# Python Static Analysis Handler
# Tools: ruff (linting), mypy (type checking)
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

# Run ruff (if available)
if command -v ruff &> /dev/null; then
    TOOLS_RUN+=("ruff")
    RUFF_OUT=$(timeout 30 ruff check --output-format=json "$FILES" 2>/dev/null || echo "[]")

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

        add_findings "$RUFF_NORM"
    fi
fi

# Run mypy (if available)
if command -v mypy &> /dev/null; then
    TOOLS_RUN+=("mypy")
    MYPY_OUT=$(timeout 30 mypy --no-color-output --no-error-summary "$FILES" 2>&1 || true)

    # Parse mypy text output to JSON using robust parsing
    if [[ -n "$MYPY_OUT" ]]; then
        MYPY_NORM=$(echo "$MYPY_OUT" | while IFS= read -r line; do
            local file lineno col msg
            if parse_colon_delimited "$line" file lineno col msg; then
                # Determine severity from message
                local severity="warning"
                if [[ "$msg" == *"error:"* ]]; then
                    severity="error"
                fi
                # Clean up message
                msg="${msg# }"
                msg="${msg#error: }"
                msg="${msg#note: }"
                msg=$(json_escape "$msg")
                file=$(json_escape "$file")

                echo "{\"tool\":\"mypy\",\"file\":\"$file\",\"line\":$lineno,\"column\":$col,\"severity\":\"$severity\",\"code\":\"mypy\",\"message\":\"$msg\",\"fixable\":false}"
            fi
        done | jq -s '.' 2>/dev/null || echo "[]")

        add_findings "$MYPY_NORM"
    fi
fi

# Generate output using common function
generate_output "python"
