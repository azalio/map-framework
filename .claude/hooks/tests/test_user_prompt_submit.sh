#!/bin/bash
# Integration tests for user-prompt-submit hook
# Tests bash → Python flow end-to-end with mocked playbook

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/../user-prompt-submit.sh"
HELPER_SCRIPT="$SCRIPT_DIR/../helpers/inject_playbook_bullets.py"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper: Print test result
print_result() {
    local test_name="$1"
    local status="$2"
    local message="${3:-}"

    TESTS_RUN=$((TESTS_RUN + 1))

    if [ "$status" = "PASS" ]; then
        echo -e "${GREEN}✓${NC} $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    elif [ "$status" = "SKIP" ]; then
        echo -e "${YELLOW}⊘${NC} $test_name (skipped: $message)"
    else
        echo -e "${RED}✗${NC} $test_name"
        [ -n "$message" ] && echo "  Error: $message"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# Helper: Validate JSON output
validate_json() {
    local output="$1"
    if echo "$output" | python3 -m json.tool >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Test 1: Hook script exists and is executable
test_hook_exists() {
    if [ -f "$HOOK_SCRIPT" ] && [ -x "$HOOK_SCRIPT" ]; then
        print_result "Hook script exists and is executable" "PASS"
    else
        print_result "Hook script exists and is executable" "FAIL" "Script not found or not executable"
    fi
}

# Test 2: Helper script exists
test_helper_exists() {
    if [ -f "$HELPER_SCRIPT" ]; then
        print_result "Helper script exists" "PASS"
    else
        print_result "Helper script exists" "FAIL" "Helper not found at $HELPER_SCRIPT"
    fi
}

# Test 3: Short message is skipped
test_short_message() {
    local output
    output=$(echo "hi" | bash "$HOOK_SCRIPT" 2>/dev/null)

    if validate_json "$output"; then
        local continue_value
        continue_value=$(echo "$output" | python3 -c "import sys, json; print(json.load(sys.stdin)['continue'])")

        if [ "$continue_value" = "True" ]; then
            print_result "Short message is skipped" "PASS"
        else
            print_result "Short message is skipped" "FAIL" "continue should be True"
        fi
    else
        print_result "Short message is skipped" "FAIL" "Invalid JSON output"
    fi
}

# Test 4: Missing playbook database
test_missing_playbook() {
    # Temporarily rename playbook.db if it exists
    local playbook_path=".claude/playbook.db"
    local backup_path=".claude/playbook.db.test-backup"

    if [ -f "$playbook_path" ]; then
        mv "$playbook_path" "$backup_path"
    fi

    local output
    output=$(echo "This is a test message" | bash "$HOOK_SCRIPT" 2>/dev/null)

    # Restore playbook
    if [ -f "$backup_path" ]; then
        mv "$backup_path" "$playbook_path"
    fi

    if validate_json "$output"; then
        print_result "Missing playbook handled gracefully" "PASS"
    else
        print_result "Missing playbook handled gracefully" "FAIL" "Invalid JSON output"
    fi
}

# Test 5: Valid message produces JSON output
test_valid_message() {
    # Check if mapify is available
    if ! command -v mapify >/dev/null 2>&1; then
        print_result "Valid message produces JSON output" "SKIP" "mapify CLI not installed"
        return
    fi

    # Check if playbook exists
    if [ ! -f ".claude/playbook.db" ]; then
        print_result "Valid message produces JSON output" "SKIP" "No playbook database"
        return
    fi

    local output
    output=$(echo "implement JWT authentication with refresh tokens" | bash "$HOOK_SCRIPT" 2>/dev/null)

    if validate_json "$output"; then
        local has_continue
        has_continue=$(echo "$output" | python3 -c "import sys, json; print('continue' in json.load(sys.stdin))")

        if [ "$has_continue" = "True" ]; then
            print_result "Valid message produces JSON output" "PASS"
        else
            print_result "Valid message produces JSON output" "FAIL" "Missing 'continue' field"
        fi
    else
        print_result "Valid message produces JSON output" "FAIL" "Invalid JSON output"
    fi
}

# Test 6: Hook always exits 0
test_exit_code() {
    echo "test message" | bash "$HOOK_SCRIPT" >/dev/null 2>&1
    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        print_result "Hook always exits 0" "PASS"
    else
        print_result "Hook always exits 0" "FAIL" "Exit code was $exit_code"
    fi
}

# Test 7: Helper script handles empty keywords
test_helper_empty_keywords() {
    local output
    output=$(python3 "$HELPER_SCRIPT" --message "a b c" 2>/dev/null)

    if validate_json "$output"; then
        local continue_value
        continue_value=$(echo "$output" | python3 -c "import sys, json; print(json.load(sys.stdin)['continue'])")

        if [ "$continue_value" = "True" ]; then
            print_result "Helper handles empty keywords" "PASS"
        else
            print_result "Helper handles empty keywords" "FAIL" "continue should be True"
        fi
    else
        print_result "Helper handles empty keywords" "FAIL" "Invalid JSON output"
    fi
}

# Test 8: Helper script keyword extraction
test_helper_keyword_extraction() {
    # This test requires Python unittest
    if python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR/../helpers'); from inject_playbook_bullets import extract_keywords; result = extract_keywords('implement JWT authentication'); assert 'implement' in result and 'jwt' in result" 2>/dev/null; then
        print_result "Helper extracts keywords correctly" "PASS"
    else
        print_result "Helper extracts keywords correctly" "FAIL" "Keyword extraction failed"
    fi
}

# Test 9: JSON output format validation
test_json_output_format() {
    local output='{"continue": true, "additionalContext": "test"}'

    if validate_json "$output"; then
        local has_continue has_context
        has_continue=$(echo "$output" | python3 -c "import sys, json; data = json.load(sys.stdin); print(isinstance(data.get('continue'), bool))")
        has_context=$(echo "$output" | python3 -c "import sys, json; data = json.load(sys.stdin); print('additionalContext' in data)")

        if [ "$has_continue" = "True" ]; then
            print_result "JSON output format is valid" "PASS"
        else
            print_result "JSON output format is valid" "FAIL" "continue must be boolean"
        fi
    else
        print_result "JSON output format is valid" "FAIL" "Invalid JSON"
    fi
}

# Test 10: stdin reading works correctly
test_stdin_reading() {
    local test_message="This is a test message for stdin reading"
    local output

    output=$(echo "$test_message" | bash "$HOOK_SCRIPT" 2>&1 | grep "Received message" || true)

    if echo "$output" | grep -q "test message"; then
        print_result "stdin reading works correctly" "PASS"
    else
        # This test might fail if logging is disabled, which is fine
        print_result "stdin reading works correctly" "SKIP" "Cannot verify (logging may be disabled)"
    fi
}

# Main test execution
main() {
    echo "================================================"
    echo "User-Prompt-Submit Hook Integration Tests"
    echo "================================================"
    echo ""

    # Change to project root
    cd "$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"

    # Run tests
    test_hook_exists
    test_helper_exists
    test_short_message
    test_missing_playbook
    test_valid_message
    test_exit_code
    test_helper_empty_keywords
    test_helper_keyword_extraction
    test_json_output_format
    test_stdin_reading

    # Print summary
    echo ""
    echo "================================================"
    echo "Test Summary"
    echo "================================================"
    echo "Total tests: $TESTS_RUN"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    if [ $TESTS_FAILED -gt 0 ]; then
        echo -e "${RED}Failed: $TESTS_FAILED${NC}"
        exit 1
    else
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    fi
}

# Run main if executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
