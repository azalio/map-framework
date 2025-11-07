#!/bin/bash
# Test script to verify validate-agent-templates.sh produces valid JSON
# even when blocking with multiline error messages

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_PATH="$SCRIPT_DIR/../.claude/hooks/validate-agent-templates.sh"

echo "Testing validate-agent-templates.sh JSON output..."

# Test Case 1: Block decision with multiline message
echo ""
echo "Test 1: Block decision with multiline message"
echo "----------------------------------------------"

# Create a test input that will trigger validation failure
TEST_INPUT=$(cat <<'EOF'
{
  "tool": "Write",
  "parameters": {
    "file_path": ".claude/agents/actor.md",
    "content": "# Actor Agent\n\nThis is a test file WITHOUT required template variables.\n\nIt should trigger validation failure."
  }
}
EOF
)

# Run the hook and capture output
OUTPUT=$(echo "$TEST_INPUT" | bash "$HOOK_PATH" 2>&1 || true)

# Test if output is valid JSON
echo "Output:"
echo "$OUTPUT"
echo ""

if echo "$OUTPUT" | jq empty 2>/dev/null; then
    echo "✅ PASS: Output is valid JSON"

    # Verify the decision field
    DECISION=$(echo "$OUTPUT" | jq -r '.decision')
    if [ "$DECISION" = "block" ]; then
        echo "✅ PASS: Decision is 'block' as expected"
    else
        echo "❌ FAIL: Decision is '$DECISION', expected 'block'"
        exit 1
    fi

    # Verify message field exists and contains newlines
    MESSAGE=$(echo "$OUTPUT" | jq -r '.message')
    if [ -n "$MESSAGE" ]; then
        echo "✅ PASS: Message field exists"

        # Check if message contains multiline content
        if echo "$MESSAGE" | grep -q $'\n'; then
            echo "✅ PASS: Message contains newlines (properly escaped in JSON)"
        else
            echo "⚠️  WARNING: Message doesn't contain newlines (might be single-line)"
        fi
    else
        echo "❌ FAIL: Message field is empty"
        exit 1
    fi
else
    echo "❌ FAIL: Output is not valid JSON"
    echo "$OUTPUT" | jq empty 2>&1 || true
    exit 1
fi

# Test Case 2: Allow decision with warning message
echo ""
echo "Test 2: Allow decision with warning message"
echo "--------------------------------------------"

# Create a test input that triggers warning but allows
# (agent file with valid templates but many lines removed)
TEST_INPUT_2=$(cat <<'EOF'
{
  "tool": "Edit",
  "parameters": {
    "file_path": ".claude/agents/actor.md",
    "old_string": "dummy",
    "new_string": "# Actor\n\n{{language}}\n{{project_name}}\n{{#if playbook_bullets}}test{{/if}}\n{{#if feedback}}test{{/if}}\n{{subtask_description}}\n\nShort content that removed many lines."
  }
}
EOF
)

# For this test, we need an existing file with >500 lines
# Create a temporary large file
TEMP_AGENT_FILE="$SCRIPT_DIR/../.claude/agents/test-temp-agent.md"
mkdir -p "$(dirname "$TEMP_AGENT_FILE")"

# Generate a file with 600 lines
{
    echo "# Test Agent"
    echo "{{language}}"
    echo "{{project_name}}"
    echo "{{#if playbook_bullets}}test{{/if}}"
    echo "{{#if feedback}}test{{/if}}"
    echo "{{subtask_description}}"
    for i in {1..600}; do
        echo "Line $i content here"
    done
} > "$TEMP_AGENT_FILE"

# Now test with this file
TEST_INPUT_3=$(cat <<EOF
{
  "tool": "Write",
  "parameters": {
    "file_path": "$TEMP_AGENT_FILE",
    "content": "# Test Agent\n\n{{language}}\n{{project_name}}\n{{#if playbook_bullets}}test{{/if}}\n{{#if feedback}}test{{/if}}\n{{subtask_description}}\n\nSmall content"
  }
}
EOF
)

OUTPUT_3=$(echo "$TEST_INPUT_3" | bash "$HOOK_PATH" 2>&1 || true)

echo "Output:"
echo "$OUTPUT_3"
echo ""

if echo "$OUTPUT_3" | jq empty 2>/dev/null; then
    echo "✅ PASS: Output is valid JSON"

    DECISION_3=$(echo "$OUTPUT_3" | jq -r '.decision')
    if [ "$DECISION_3" = "allow" ]; then
        echo "✅ PASS: Decision is 'allow' as expected"
    else
        echo "❌ FAIL: Decision is '$DECISION_3', expected 'allow'"
        exit 1
    fi

    # Check if message field exists (warning case)
    if echo "$OUTPUT_3" | jq -e '.message' > /dev/null 2>&1; then
        MESSAGE_3=$(echo "$OUTPUT_3" | jq -r '.message')
        if [ -n "$MESSAGE_3" ]; then
            echo "✅ PASS: Warning message exists"
        fi
    else
        echo "ℹ️  INFO: No message field (file doesn't exist or no warning triggered)"
    fi
else
    echo "❌ FAIL: Output is not valid JSON"
    echo "$OUTPUT_3" | jq empty 2>&1 || true
    exit 1
fi

# Cleanup
rm -f "$TEMP_AGENT_FILE"

# Test Case 3: Allow decision (valid file)
echo ""
echo "Test 3: Allow decision with valid templates"
echo "--------------------------------------------"

TEST_INPUT_4=$(cat <<'EOF'
{
  "tool": "Write",
  "parameters": {
    "file_path": ".claude/agents/actor.md",
    "content": "# Actor Agent\n\n{{language}}\n{{project_name}}\n{{#if playbook_bullets}}bullets{{/if}}\n{{#if feedback}}feedback{{/if}}\n{{subtask_description}}\n\nAll required templates present!"
  }
}
EOF
)

OUTPUT_4=$(echo "$TEST_INPUT_4" | bash "$HOOK_PATH" 2>&1 || true)

echo "Output:"
echo "$OUTPUT_4"
echo ""

if echo "$OUTPUT_4" | jq empty 2>/dev/null; then
    echo "✅ PASS: Output is valid JSON"

    DECISION_4=$(echo "$OUTPUT_4" | jq -r '.decision')
    if [ "$DECISION_4" = "allow" ]; then
        echo "✅ PASS: Decision is 'allow' as expected"
    else
        echo "❌ FAIL: Decision is '$DECISION_4', expected 'allow'"
        exit 1
    fi
else
    echo "❌ FAIL: Output is not valid JSON"
    echo "$OUTPUT_4" | jq empty 2>&1 || true
    exit 1
fi

echo ""
echo "=========================================="
echo "All tests passed! ✅"
echo "=========================================="
