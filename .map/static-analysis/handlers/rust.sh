#!/usr/bin/env bash
# Rust Static Analysis Handler
# Tools: cargo fmt (format check)
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

# Run cargo fmt check (if available)
if command -v cargo &> /dev/null; then
    # Only run if this looks like a Rust project
    if [[ -f "Cargo.toml" ]]; then
        # NOTE: cargo fmt does not accept file lists; it runs at workspace level.
        TOOLS_RUN+=("cargo fmt")
        FMT_OUT=$(timeout 60 cargo fmt -- --check 2>&1 || true)

        if [[ -n "$FMT_OUT" ]]; then
            # rustfmt output is not reliably file:line:col, so emit a single finding
            msg=$(json_escape "$FMT_OUT")
            add_findings "[{\"tool\":\"cargo fmt\",\"file\":\"Cargo.toml\",\"line\":1,\"column\":0,\"severity\":\"warning\",\"code\":\"format\",\"message\":\"$msg\",\"fixable\":true}]"
        fi
    fi
fi

# Generate output using common function
generate_output "rust"
