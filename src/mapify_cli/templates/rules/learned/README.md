# Learned Rules (MAP Framework)

This directory contains lessons extracted by `/map-learn` from completed MAP workflows.
Claude Code loads these files at session start, making past lessons available in future sessions.

## How it works

- `/map-learn` calls the Reflector agent to analyze a completed workflow
- Patterns are written as markdown bullets in topic-based files (e.g., `security-patterns.md`)
- Files with `paths:` frontmatter only load when Claude works with matching files
- Files without `paths:` frontmatter load in every session

## Managing rules

- **Edit freely**: these files are yours — add, modify, or remove any rule
- **Prune periodically**: remove outdated rules that no longer apply
- **Keep files under 50 rules each** for best Claude Code adherence
- **Commit with your project**: `git add .claude/rules/` to share with team
