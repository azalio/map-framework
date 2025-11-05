# Playbook Mode Fix Plan

## Problem Statement

Claude Code agents consistently struggle with playbook usage due to confusing documentation:

### Issue 1: Wrong Default Mode in Examples
**Current state:** All MAP workflow commands (.claude/commands/map-*.md) show examples with `--mode local`
```bash
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5 --mode local)
```

**Problem:** This limits search to LOCAL playbook only, missing cross-project patterns in cipher.

**Impact:**
- Agents don't benefit from lessons learned in other projects
- Knowledge stays siloed within single project
- Defeats the purpose of ACE (Agentic Context Engineering) dual-memory system

### Issue 2: Misleading Documentation
**Current:** docs/USAGE.md states `--mode local` is "(default)" and "(fast)"

**Problem:** This encourages using local-only mode even though:
- Hybrid mode is more valuable for learning
- Cipher contains validated cross-project patterns
- Speed difference is negligible for small result sets (--limit 5-10)

### Issue 3: Legacy playbook.json References
**Current:** 47 files still reference `playbook.json`

**Problem:** Playbook migrated to SQLite (.claude/playbook.db) but docs not fully updated

## Solution

### 1. Change Recommended Default to Hybrid Mode

**Rationale:**
- Hybrid mode searches BOTH local playbook AND cipher
- Provides access to cross-project validated patterns
- Aligns with MAP Framework's ACE integration goals
- Minimal performance impact with --limit flag

**Changes needed:**
- Update all workflow commands to use `--mode hybrid`
- Update USAGE.md to recommend hybrid as best practice
- Keep `--mode local` as performance optimization option

### 2. Update All Workflow Commands

Files to modify:
- `.claude/commands/map-efficient.md` (line 126)
- `.claude/commands/map-feature.md` (line 133)
- `.claude/commands/map-debug.md`
- `.claude/commands/map-refactor.md`
- `.claude/commands/map-review.md`
- All corresponding `src/mapify_cli/templates/commands/*.md`

**Change:**
```bash
# OLD (wrong)
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5 --mode local)

# NEW (correct)
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5 --mode hybrid)
```

### 3. Update Documentation Guidance

**docs/USAGE.md** changes:
```markdown
# OLD
**Query modes:**
- `--mode local` (default) - Search local playbook only (fast, <50ms)
- `--mode hybrid` - Search both playbook and cipher (comprehensive)

# NEW
**Query modes:**
- `--mode hybrid` (RECOMMENDED) - Search both playbook and cipher for maximum learning
- `--mode local` - Search local playbook only (use for performance optimization)
- `--mode cipher` - Search cipher only (cross-project patterns)

**Why hybrid mode?**
✅ Access to cross-project validated patterns from cipher
✅ Learns from past experiences across all projects
✅ Minimal performance impact with --limit flag (<100ms)
✅ Aligns with ACE (Agentic Context Engineering) design

**When to use local mode:**
- Very large result sets (--limit >50)
- No cipher MCP server available
- Project-specific patterns only needed
```

### 4. Update Skills Documentation

**Files:**
- `.claude/skills/map-workflows-guide/resources/playbook-system.md` (line 304)
- `src/mapify_cli/templates/skills/map-workflows-guide/resources/playbook-system.md`

**Change:** Remove recommendation to use `--mode local` for large playbooks. Instead recommend:
- Archive old bullets
- Use --section filters
- Keep hybrid mode for comprehensive search

### 5. Clean Up playbook.json References

**Action:** Replace remaining references to `playbook.json` with `playbook.db` in:
- Documentation files
- Code comments
- Error messages

## Implementation Checklist

- [ ] Update map-efficient.md (local + template)
- [ ] Update map-feature.md (local + template)
- [ ] Update map-debug.md (local + template)
- [ ] Update map-refactor.md (local + template)
- [ ] Update map-review.md (local + template)
- [ ] Update USAGE.md query modes section
- [ ] Update playbook-system.md skill resource (local + template)
- [ ] Sync all templates to src/mapify_cli/templates/
- [ ] Verify with scripts/check-template-sync.sh
- [ ] Update CLAUDE.md if needed
- [ ] Test with actual workflow run
- [ ] Create commit with clear explanation

## Expected Outcomes

✅ Agents will automatically search both local and cipher knowledge
✅ Cross-project learning becomes default behavior
✅ No more confusion about which mode to use
✅ Consistent recommendations across all documentation
✅ Better alignment with ACE dual-memory design

## Risks & Mitigation

**Risk:** Slight performance degradation for users without cipher MCP
**Mitigation:** Document --mode local as optimization option

**Risk:** Users might not have cipher configured
**Mitigation:** Hybrid mode gracefully falls back to local-only if cipher unavailable

**Risk:** Breaking existing user workflows
**Mitigation:** CLI default stays `local`, only documentation/examples change
