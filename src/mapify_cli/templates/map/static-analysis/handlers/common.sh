#!/bin/bash
# Common utilities for static analysis handlers
# Source this file at the beginning of each handler

# Accumulator for findings - use array instead of repeated jq concatenation
declare -a FINDINGS_ARRAY=()

# Add findings to accumulator (avoids O(n²) concatenation)
add_findings() {
    local findings_json="$1"
    if [[ -n "$findings_json" && "$findings_json" != "[]" && "$findings_json" != "null" ]]; then
        FINDINGS_ARRAY+=("$findings_json")
    fi
}

# Merge all findings into single JSON array
merge_findings() {
    if [[ ${#FINDINGS_ARRAY[@]} -eq 0 ]]; then
        echo "[]"
        return
    fi

    # Concatenate all arrays efficiently with jq
    printf '%s\n' "${FINDINGS_ARRAY[@]}" | jq -s 'add // []' 2>/dev/null || echo "[]"
}

# Generate summary and output final JSON
# Usage: generate_output "language"
generate_output() {
    local language="$1"
    local all_findings
    all_findings=$(merge_findings)

    # Calculate summary
    local error_count warning_count total_count tools_json
    error_count=$(echo "$all_findings" | jq '[.[] | select(.severity=="error")] | length')
    warning_count=$(echo "$all_findings" | jq '[.[] | select(.severity=="warning")] | length')
    total_count=$(echo "$all_findings" | jq 'length')

    # Convert tools array to JSON (handle empty array safely)
    if [[ ${#TOOLS_RUN[@]} -gt 0 ]]; then
        tools_json=$(printf '%s\n' "${TOOLS_RUN[@]}" | jq -R . | jq -s .)
    else
        tools_json="[]"
    fi

    # Output normalized JSON
    jq -n \
        --argjson findings "$all_findings" \
        --argjson errors "$error_count" \
        --argjson warnings "$warning_count" \
        --argjson total "$total_count" \
        --argjson tools "$tools_json" \
        --arg language "$language" \
        '{
            success: true,
            language: $language,
            summary: {
                total: $total,
                errors: $errors,
                warnings: $warnings,
                pass: ($errors == 0)
            },
            findings: $findings,
            tools_run: $tools
        }'
}

# Safe JSON string escaping
json_escape() {
    local str="$1"
    # Escape backslashes first, then quotes
    str="${str//\\/\\\\}"
    str="${str//\"/\\\"}"
    str="${str//$'\t'/\\t}"
    str="${str//$'\r'/\\r}"
    str="${str//$'\n'/\\n}"
    echo "$str"
}

# Parse tool output line with robust handling of colons in filenames
# Usage: parse_colon_delimited "file:line:col:message" -> sets FILE, LINE, COL, MESSAGE
parse_colon_delimited() {
    local input="$1"
    local -n out_file="$2"
    local -n out_line="$3"
    local -n out_col="$4"
    local -n out_msg="$5"

    # Try file:line:col:message pattern first
    if [[ "$input" =~ ^(.+):([0-9]+):([0-9]+):(.*)$ ]]; then
        out_file="${BASH_REMATCH[1]}"
        out_line="${BASH_REMATCH[2]}"
        out_col="${BASH_REMATCH[3]}"
        out_msg="${BASH_REMATCH[4]}"
        return 0
    fi

    # Fallback to file:line:message (no column)
    if [[ "$input" =~ ^(.+):([0-9]+):(.*)$ ]]; then
        out_file="${BASH_REMATCH[1]}"
        out_line="${BASH_REMATCH[2]}"
        out_col=0
        out_msg="${BASH_REMATCH[3]}"
        return 0
    fi

    return 1
}
