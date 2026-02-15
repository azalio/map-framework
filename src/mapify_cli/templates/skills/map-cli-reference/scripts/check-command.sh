#!/usr/bin/env bash
# Check if a mapify subcommand exists and show usage help.
#
# Usage:
#   ./check-command.sh <subcommand> [option]
#
# Examples:
#   ./check-command.sh validate graph
#   ./check-command.sh init
#   ./check-command.sh playbook  # removed command
#
# Exit codes:
#   0 - Command exists
#   1 - Command not found
#   2 - Command removed

set -euo pipefail

SUBCOMMAND="${1:-}"
OPTION="${2:-}"

if [ -z "$SUBCOMMAND" ]; then
  echo "Usage: $0 <subcommand> [option]"
  echo ""
  echo "Checks if a mapify subcommand exists."
  echo ""
  echo "Available subcommands:"
  echo "  init       - Initialize project with MAP framework"
  echo "  check      - Run system checks"
  echo "  upgrade    - Upgrade agent templates"
  echo "  validate   - Validate dependency graphs"
  echo ""
  echo "Removed subcommands:"
  echo "  playbook   - Removed in v4.0+ (use mem0 MCP)"
  exit 1
fi

# Removed subcommands (replaced by mem0 MCP in v4.0+)
REMOVED_COMMANDS="playbook"

# Known valid commands
VALID_COMMANDS="init check upgrade validate"

# Check removed commands first
for dep in $REMOVED_COMMANDS; do
  if [ "$SUBCOMMAND" = "$dep" ]; then
    echo "ERROR: '$SUBCOMMAND' was removed in v4.0+ (use mem0 MCP instead)"
    echo ""
    echo "Replacements:"
    case "$SUBCOMMAND" in
      playbook)
        echo "  Pattern retrieval: mcp__mem0__map_tiered_search(query=\"...\", limit=5)"
        echo "  Pattern storage:   Task(subagent_type=\"curator\", ...)"
        echo "  Pattern archival:  mcp__mem0__map_archive_pattern(...)"
        ;;
    esac
    exit 2
  fi
done

# Check valid commands
FOUND=0
for cmd in $VALID_COMMANDS; do
  if [ "$SUBCOMMAND" = "$cmd" ]; then
    FOUND=1
    break
  fi
done

if [ "$FOUND" -eq 0 ]; then
  echo "ERROR: No such command '$SUBCOMMAND'"
  echo ""
  echo "Available commands: $VALID_COMMANDS"
  echo ""
  echo "Did you mean one of these?"
  # Simple fuzzy match
  for cmd in $VALID_COMMANDS; do
    echo "  mapify $cmd"
  done
  exit 1
fi

# Command exists, show help
echo "OK: 'mapify $SUBCOMMAND' is a valid command"

# Show subcommand-specific help
case "$SUBCOMMAND" in
  validate)
    echo ""
    echo "Usage: mapify validate graph <file> [--strict] [--visualize]"
    echo ""
    echo "Options:"
    echo "  --strict      Fail on warnings (exit code 1)"
    echo "  --visualize   Show dependency graph"
    echo ""
    echo "Exit codes: 0=valid, 1=invalid, 2=malformed input"
    if [ -n "$OPTION" ] && [ "$OPTION" != "graph" ]; then
      echo ""
      echo "WARNING: Unknown validate subcommand '$OPTION'. Did you mean 'graph'?"
    fi
    ;;
  init)
    echo ""
    echo "Usage: mapify init [project-name] [--mcp essential|full] [--force]"
    echo ""
    echo "Options:"
    echo "  --mcp essential  Install essential MCP tools only"
    echo "  --mcp full       Install all MCP tools"
    echo "  --force          Overwrite existing configuration"
    ;;
  check)
    echo ""
    echo "Usage: mapify check [--debug]"
    echo ""
    echo "Options:"
    echo "  --debug   Show detailed diagnostic information"
    ;;
  upgrade)
    echo ""
    echo "Usage: mapify upgrade"
    echo ""
    echo "Upgrades agent templates to latest version."
    ;;
esac

exit 0
