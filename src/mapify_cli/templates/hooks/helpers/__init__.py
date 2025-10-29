"""Helper scripts for Claude Code hooks.

This package contains Python helper scripts called by bash hooks.
Helpers cannot call MCP tools (run outside Claude context) but can:
- Execute CLI commands (mapify, git, etc.)
- Process JSON/text data
- Format output for Claude Code consumption
"""
