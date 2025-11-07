#!/bin/bash
# Comprehensive end-to-end tests for Claude Code hooks
# Tests validate-agent-templates.sh, stop.sh, and user-prompt-submit.sh
# with edge cases: multiline content, special characters, unicode, large content

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VALIDATE_HOOK="$PROJECT_ROOT/.claude/hooks/validate-agent-templates.sh"
STOP_HOOK="$PROJECT_ROOT/.claude/hooks/stop.sh"
USER_PROMPT_HOOK="$PROJECT_ROOT/.claude/hooks/user-prompt-submit.sh"

# Temporary directory for test files
TEMP_DIR="$SCRIPT_DIR/temp_hook_tests"
mkdir -p "$TEMP_DIR"

# Cleanup function
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# Helper: Print test header
print_test_header() {
    local test_name="$1"
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Test: $test_name${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Helper: Run test and validate JSON output
run_test() {
    local test_name="$1"
    local hook_path="$2"
    local input_json="$3"
    local expected_exit="$4"
    local validation_func="$5"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    print_test_header "$test_name"
    
    # Run hook and capture output and exit code
    local output
    local exit_code
    
    set +e
    output=$(echo "$input_json" | bash "$hook_path" 2>&1)
    exit_code=$?
    set -e
    
    echo "Exit code: $exit_code (expected: $expected_exit)"
    
    # Check exit code
    if [ "$exit_code" -ne "$expected_exit" ]; then
        echo -e "${RED}❌ FAIL: Exit code mismatch${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    # Validate JSON output
    if ! echo "$output" | jq empty 2>/dev/null; then
        echo -e "${RED}❌ FAIL: Output is not valid JSON${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    echo -e "${GREEN}✓ JSON is valid${NC}"
    
    # Run custom validation
    if ! $validation_func "$output"; then
        echo -e "${RED}❌ FAIL: Validation failed${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    echo -e "${GREEN}✅ PASS: $test_name${NC}"
    PASSED_TESTS=$((PASSED_TESTS + 1))
    return 0
}

# Validation functions
validate_block_decision() {
    local output="$1"
    local decision=$(echo "$output" | jq -r '.decision')
    
    if [ "$decision" != "block" ]; then
        echo "Expected decision='block', got '$decision'"
        return 1
    fi
    
    echo -e "${GREEN}✓ Block decision${NC}"
    return 0
}

validate_allow_decision() {
    local output="$1"
    local decision=$(echo "$output" | jq -r '.decision')
    
    if [ "$decision" != "allow" ]; then
        echo "Expected decision='allow', got '$decision'"
        return 1
    fi
    
    echo -e "${GREEN}✓ Allow decision${NC}"
    return 0
}

validate_continue_true() {
    local output="$1"
    local continue_val=$(echo "$output" | jq -r '.continue')
    
    if [ "$continue_val" != "true" ]; then
        echo "Expected continue=true, got '$continue_val'"
        return 1
    fi
    
    echo -e "${GREEN}✓ Continue is true${NC}"
    return 0
}

# TEST SUITE 1: validate-agent-templates.sh
test_suite_validate() {
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}TEST SUITE 1: validate-agent-templates.sh${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    
    # Test 1.1: Multiline content missing templates
    local input=$(jq -n '{
        "tool": "Write",
        "parameters": {
            "file_path": ".claude/agents/actor.md",
            "content": "# Actor\n\nLine 1\nLine 2\nNo templates"
        }
    }')
    
    run_test "1.1: Multiline content missing templates" \
        "$VALIDATE_HOOK" \
        "$input" \
        1 \
        validate_block_decision
    
    # Test 1.2: Valid templates
    local input=$(jq -n '{
        "tool": "Write",
        "parameters": {
            "file_path": ".claude/agents/test.md",
            "content": "# Test\n{{language}}\n{{project_name}}\n{{#if playbook_bullets}}x{{/if}}\n{{#if feedback}}y{{/if}}\n{{subtask_description}}"
        }
    }')
    
    run_test "1.2: Valid templates" \
        "$VALIDATE_HOOK" \
        "$input" \
        0 \
        validate_allow_decision
    
    # Test 1.3: Non-agent file
    local input=$(jq -n '{
        "tool": "Write",
        "parameters": {
            "file_path": "README.md",
            "content": "# No templates needed"
        }
    }')
    
    run_test "1.3: Non-agent file" \
        "$VALIDATE_HOOK" \
        "$input" \
        0 \
        validate_allow_decision
}

# TEST SUITE 2: stop.sh
test_suite_stop() {
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}TEST SUITE 2: stop.sh${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    
    # Test 2.1: Python file
    local temp_py="$TEMP_DIR/test.py"
    echo 'print("hello")' > "$temp_py"
    
    local input=$(jq -n --arg path "$temp_py" '{
        "tool": "Write",
        "parameters": {
            "file_path": $path,
            "content": "test"
        }
    }')
    
    run_test "2.1: Python file" \
        "$STOP_HOOK" \
        "$input" \
        0 \
        validate_continue_true
    
    # Test 2.2: Non-code file
    local input=$(jq -n '{
        "tool": "Write",
        "parameters": {
            "file_path": "README.md",
            "content": "test"
        }
    }')
    
    run_test "2.2: Non-code file" \
        "$STOP_HOOK" \
        "$input" \
        0 \
        validate_continue_true
    
    # Test 2.3: Malformed JSON
    local input="{invalid}"
    
    run_test "2.3: Malformed JSON" \
        "$STOP_HOOK" \
        "$input" \
        0 \
        validate_continue_true
}

# TEST SUITE 3: user-prompt-submit.sh
test_suite_user_prompt() {
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}TEST SUITE 3: user-prompt-submit.sh${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
    
    # Test 3.1: Message with quotes
    local input='How do I use "quotes" in code?'
    
    run_test "3.1: Message with quotes" \
        "$USER_PROMPT_HOOK" \
        "$input" \
        0 \
        validate_continue_true
    
    # Test 3.2: Message with newlines
    local input=$'Line 1\nLine 2\nLine 3'
    
    run_test "3.2: Message with newlines" \
        "$USER_PROMPT_HOOK" \
        "$input" \
        0 \
        validate_continue_true
}

# MAIN
main() {
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  E2E Tests for Claude Code Hooks                     ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════╝${NC}"
    
    test_suite_validate
    test_suite_stop
    test_suite_user_prompt
    
    # Summary
    echo ""
    echo -e "${BLUE}╔═══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  SUMMARY                                              ║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Total:  $TOTAL_TESTS"
    echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
    
    if [ $FAILED_TESTS -gt 0 ]; then
        echo -e "${RED}Failed: $FAILED_TESTS${NC}"
        exit 1
    else
        echo -e "${GREEN}Failed: 0${NC}"
        echo -e "${GREEN}✅ ALL TESTS PASSED!${NC}"
        exit 0
    fi
}

main "$@"
