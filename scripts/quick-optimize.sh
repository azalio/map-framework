#!/bin/bash
# Quick template optimization analysis

echo "=== MAP Template Size Analysis ==="
echo ""

cd .claude/agents

total=0
for file in *.md; do
  [[ "$file" == "CHANGELOG.md" ]] && continue
  [[ "$file" == "README.md" ]] && continue
  [[ "$file" == "MCP-PATTERNS.md" ]] && continue
  
  lines=$(wc -l < "$file")
  total=$((total + lines))
  printf "%-35s %5d lines\n" "$file" "$lines"
done

echo ""
echo "Total: $total lines"
echo "10% reduction target: $((total / 10)) lines"
echo "15% reduction target: $((total * 15 / 100)) lines"
