#!/bin/bash
# Claude Code SubagentStop hook: Track MAP agent performance metrics
# Collects execution time, success rate, and quality scores for analysis
#
# Input: JSON via stdin with subagent result
# Output: JSON with optional message
# Exit code: Always 0

set -euo pipefail

# Read JSON input from Claude Code
INPUT=$(cat)

# Extract subagent info
AGENT_NAME=$(echo "$INPUT" | jq -r '.agent_name // .subagent_name // empty')
START_TIME=$(echo "$INPUT" | jq -r '.start_time // empty')
END_TIME=$(echo "$INPUT" | jq -r '.end_time // empty')
SUCCESS=$(echo "$INPUT" | jq -r '.success // true')
OUTPUT=$(echo "$INPUT" | jq -r '.output // empty')

# Skip if not a MAP agent
if [[ ! "$AGENT_NAME" =~ ^(task-decomposer|actor|monitor|predictor|evaluator|orchestrator|reflector|curator)$ ]]; then
    echo '{"message": "Not a MAP agent, skipping"}'
    exit 0
fi

# Calculate execution time if timestamps available
EXECUTION_TIME="unknown"
if [ -n "$START_TIME" ] && [ -n "$END_TIME" ] && [ "$START_TIME" != "null" ] && [ "$END_TIME" != "null" ]; then
    START_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$START_TIME" +%s 2>/dev/null || echo "0")
    END_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$END_TIME" +%s 2>/dev/null || echo "0")
    if [ "$START_EPOCH" != "0" ] && [ "$END_EPOCH" != "0" ]; then
        EXECUTION_TIME=$((END_EPOCH - START_EPOCH))
    fi
fi

# Extract quality metrics from output if available
QUALITY_SCORE="unknown"
if echo "$OUTPUT" | grep -qE "(score|quality|rating):? *[0-9.]+"; then
    QUALITY_SCORE=$(echo "$OUTPUT" | grep -oE "(score|quality|rating):? *[0-9.]+" | grep -oE "[0-9.]+" | head -1)
fi

# Create metrics directory
METRICS_DIR=".claude/metrics"
mkdir -p "$METRICS_DIR" 2>/dev/null || true

# Create metrics file for this session
METRICS_FILE="$METRICS_DIR/agent_metrics.jsonl"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Append metrics as JSON line
cat >> "$METRICS_FILE" <<EOF
{"timestamp":"$TIMESTAMP","agent":"$AGENT_NAME","execution_time":$EXECUTION_TIME,"success":$SUCCESS,"quality_score":"$QUALITY_SCORE"}
EOF

# Calculate aggregate statistics
TOTAL_RUNS=$(grep "\"agent\":\"$AGENT_NAME\"" "$METRICS_FILE" 2>/dev/null | wc -l | tr -d ' ')
SUCCESS_RUNS=$(grep "\"agent\":\"$AGENT_NAME\"" "$METRICS_FILE" 2>/dev/null | grep "\"success\":true" | wc -l | tr -d ' ')

SUCCESS_RATE="0"
if [ "$TOTAL_RUNS" -gt 0 ]; then
    SUCCESS_RATE=$(echo "scale=2; $SUCCESS_RUNS * 100 / $TOTAL_RUNS" | bc 2>/dev/null || echo "0")
fi

# Generate summary report
SUMMARY_FILE="$METRICS_DIR/summary.txt"
cat > "$SUMMARY_FILE" <<EOF
# MAP Agent Performance Metrics
# Generated: $TIMESTAMP

## Agent Statistics

### $AGENT_NAME
- Total runs: $TOTAL_RUNS
- Successful: $SUCCESS_RUNS
- Success rate: ${SUCCESS_RATE}%
- Last execution: ${EXECUTION_TIME}s
- Last quality: $QUALITY_SCORE

---
Full metrics: $METRICS_FILE
EOF

# Store metrics in cipher for analysis (if available)
if command -v claude &> /dev/null; then
    METRICS_TEXT="MAP Agent Performance: $AGENT_NAME
- Execution time: ${EXECUTION_TIME}s
- Success: $SUCCESS
- Quality score: $QUALITY_SCORE
- Success rate: ${SUCCESS_RATE}% ($SUCCESS_RUNS/$TOTAL_RUNS)
- Timestamp: $TIMESTAMP"

    echo "$METRICS_TEXT" | claude --mcp-only mcp__cipher__cipher_extract_and_operate_memory \
        --interaction "$METRICS_TEXT" \
        --memoryMetadata '{"source":"metrics-hook","agent":"'"$AGENT_NAME"'","environment":"dev"}' \
        2>/dev/null || true
fi

MESSAGE="📊 Metrics tracked: $AGENT_NAME
- Execution: ${EXECUTION_TIME}s
- Success: $SUCCESS
- Quality: $QUALITY_SCORE
- Success rate: ${SUCCESS_RATE}% ($TOTAL_RUNS runs)"

echo "{\"message\": \"$MESSAGE\"}"
exit 0
