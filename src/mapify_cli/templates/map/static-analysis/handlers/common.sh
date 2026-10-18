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
    error_count=$(printf '%s' "$all_findings" | jq '[.[] | select(.severity=="error")] | length')
    warning_count=$(printf '%s' "$all_findings" | jq '[.[] | select(.severity=="warning")] | length')
    total_count=$(printf '%s' "$all_findings" | jq 'length')

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
# Usage: parse_colon_delimited "file:line:col:message" file line col message
# Output names must be writable scalar identifiers, not BASH_REMATCH or __map_parse_*.
parse_colon_delimited() {
    [[ $# -eq 5 ]] || return 1
    local __map_parse_name __map_parse_decl
    for __map_parse_name in "$2" "$3" "$4" "$5"; do
        [[ "$__map_parse_name" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || return 1
        [[ "$__map_parse_name" != __map_parse_* && "$__map_parse_name" != BASH_REMATCH ]] || return 1
        # Bash 3.2 printf -v can report success for readonly targets. Reject
        # attributes that prevent or transform scalar writes before any assignment.
        __map_parse_decl=$(declare -p "$__map_parse_name" 2>/dev/null) || __map_parse_decl=""
        if [[ "$__map_parse_decl" =~ ^declare\ -[^\ ]*[aAirnlu] ]]; then
            return 1
        fi
    done

    # printf -v supports Bash 3.2; reserved locals avoid shadowing caller outputs.
    # Chain assignments so a failed write cannot report successful parsing.
    if [[ "$1" =~ ^(.+):([0-9]+):([0-9]+):(.*)$ ]]; then
        printf -v "$2" '%s' "${BASH_REMATCH[1]}" &&
        printf -v "$3" '%s' "${BASH_REMATCH[2]}" &&
        printf -v "$4" '%s' "${BASH_REMATCH[3]}" &&
        printf -v "$5" '%s' "${BASH_REMATCH[4]}"
        return $?
    fi

    # Fallback to file:line:message (no column)
    if [[ "$1" =~ ^(.+):([0-9]+):(.*)$ ]]; then
        printf -v "$2" '%s' "${BASH_REMATCH[1]}" &&
        printf -v "$3" '%s' "${BASH_REMATCH[2]}" &&
        printf -v "$4" '%s' 0 &&
        printf -v "$5" '%s' "${BASH_REMATCH[3]}"
        return $?
    fi

    return 1
}
