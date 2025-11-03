#!/bin/bash
# Test suite for auto-activation system
# Tests workflow suggestion functionality

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/../user-prompt-submit.sh"
SESSION_FILE=".claude/cache/workflow_suggestions_session.txt"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to run test
run_test() {
    local test_name="$1"
    local input="$2"
    local expected_workflow="$3"

    echo -n "Test: $test_name... "

    # Clear session file
    rm -f "$SESSION_FILE"

    # Run hook
    output=$(printf '%s' "$input" | "$HOOK_SCRIPT" 2>/dev/null || true)

    if [ "$expected_workflow" = "none" ]; then
        # Should NOT contain workflow suggestion
        if echo "$output" | grep -q "Suggested Workflow"; then
            echo -e "${RED}FAILED${NC} (unexpected suggestion)"
            ((TESTS_FAILED++))
        else
            echo -e "${GREEN}PASSED${NC}"
            ((TESTS_PASSED++))
        fi
    else
        # Should contain expected workflow
        if echo "$output" | grep -q "/$expected_workflow"; then
            echo -e "${GREEN}PASSED${NC}"
            ((TESTS_PASSED++))
        else
            echo -e "${RED}FAILED${NC} (expected /$expected_workflow)"
            ((TESTS_FAILED++))
        fi
    fi
}

echo "=== Auto-Activation Test Suite ==="
echo

# Test Case 1: Debug workflow trigger
run_test "Debug trigger" "Fix failing tests in auth.test.ts" "map-debug"

# Test Case 2: Feature workflow trigger
run_test "Feature trigger" "Implement new user registration feature" "map-feature"

# Test Case 3: Efficient workflow trigger
run_test "Efficient trigger" "Optimize database queries for better performance" "map-efficient"

# Test Case 4: Refactor workflow trigger
run_test "Refactor trigger" "Restructure the authentication module" "map-refactor"

# Test Case 5: Fast workflow trigger
run_test "Fast trigger" "Quick prototype for testing the idea" "map-fast"

# Test Case 6: No trigger (should not suggest)
run_test "No trigger" "What is the weather today?" "none"

# Test Case 7: Session tracking
echo -n "Test: Session tracking... "
rm -f "$SESSION_FILE"
# First request
output1=$(printf '%s' "Fix the bug" | "$HOOK_SCRIPT" 2>/dev/null || true)
# Second request (same workflow)
output2=$(printf '%s' "Fix another bug" | "$HOOK_SCRIPT" 2>/dev/null || true)

if echo "$output1" | grep -q "/map-debug" && ! echo "$output2" | grep -q "/map-debug"; then
    echo -e "${GREEN}PASSED${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAILED${NC} (session tracking not working)"
    ((TESTS_FAILED++))
fi

# Clean up
rm -f "$SESSION_FILE"

echo
echo "=== Test Results ==="
echo "Passed: $TESTS_PASSED"
echo "Failed: $TESTS_FAILED"
echo

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
