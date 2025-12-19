#!/bin/bash
# Go Static Analysis Handler
# Tools: go vet, gofmt, staticcheck (if available)
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
    FILES="./..."
fi

TOOLS_RUN=()

# Run go vet
if command -v go &> /dev/null; then
    TOOLS_RUN+=("go vet")
    VET_OUT=$(timeout 30 go vet "$FILES" 2>&1 || true)

    if [[ -n "$VET_OUT" ]]; then
        VET_NORM=$(echo "$VET_OUT" | while IFS= read -r line; do
            local file lineno col msg
            if parse_colon_delimited "$line" file lineno col msg; then
                msg="${msg# }"
                msg=$(json_escape "$msg")
                file=$(json_escape "$file")
                echo "{\"tool\":\"go vet\",\"file\":\"$file\",\"line\":$lineno,\"column\":$col,\"severity\":\"error\",\"code\":\"vet\",\"message\":\"$msg\",\"fixable\":false}"
            fi
        done | jq -s '.' 2>/dev/null || echo "[]")

        add_findings "$VET_NORM"
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
        FMT_NORM=$(echo "$FMT_OUT" | while IFS= read -r file; do
            file=$(json_escape "$file")
            echo "{\"tool\":\"gofmt\",\"file\":\"$file\",\"line\":1,\"column\":0,\"severity\":\"warning\",\"code\":\"format\",\"message\":\"File needs formatting\",\"fixable\":true}"
        done | jq -s '.' 2>/dev/null || echo "[]")

        add_findings "$FMT_NORM"
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

        add_findings "$SC_NORM"
    fi
fi

# Generate output using common function
generate_output "go"
