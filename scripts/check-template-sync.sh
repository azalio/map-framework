#!/bin/bash
# Check agent template synchronization between .claude/agents/ and src/mapify_cli/templates/agents/

set -e

echo "🔍 Checking agent template synchronization..."
echo ""

agents=(
    "task-decomposer"
    "actor"
    "monitor"
    "predictor"
    "evaluator"
    "reflector"
    "curator"
    "documentation-reviewer"
)

all_synced=true

for agent in "${agents[@]}"; do
    source=".claude/agents/${agent}.md"
    target="src/mapify_cli/templates/agents/${agent}.md"

    if [ ! -f "$source" ]; then
        echo "⚠️  MISSING SOURCE: ${agent}.md"
        echo "   Expected: $source"
        all_synced=false
        continue
    fi

    if [ ! -f "$target" ]; then
        echo "⚠️  MISSING TARGET: ${agent}.md"
        echo "   Expected: $target"
        echo "   Run: cp $source $target"
        all_synced=false
        continue
    fi

    if ! diff -q "$source" "$target" > /dev/null 2>&1; then
        echo "❌ OUT OF SYNC: ${agent}.md"
        echo "   Source: $source"
        echo "   Target: $target"
        echo "   Run: cp $source $target"
        all_synced=false
    else
        echo "✅ IN SYNC: ${agent}.md"
    fi
done

echo ""

if [ "$all_synced" = true ]; then
    echo "✅ All agent templates are synchronized!"
    exit 0
else
    echo "❌ Some templates are out of sync. Please synchronize before committing."
    echo ""
    echo "Quick fix:"
    echo "  cp .claude/agents/*.md src/mapify_cli/templates/agents/"
    exit 1
fi
