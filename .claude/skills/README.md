# MAP Skills System

## What are Skills?

**Skills** = Passive documentation modules (NOT agents!)

Skills provide specialized guidance without executing code. They help users understand MAP Framework concepts and make informed decisions.

## Skills vs Agents

| Skills | Agents |
|--------|--------|
| **Passive** documentation | **Active** execution |
| Load via Skill tool | Execute via Task tool |
| Provide guidance | Write code |
| Progressive disclosure (<500 lines) | Full specification (orchestrated) |
| User-initiated | Workflow-initiated |

**Example:**
- **Skill:** map-workflows-guide (explains when to use each workflow)
- **Agent:** actor.md (implements code based on workflow)

---

## Available Skills

### map-workflows-guide

**Purpose:** Help users choose the right MAP workflow for their task

**Triggers:** (auto-suggested when user prompts match)
- Keywords: "which workflow", "difference between", "when to use"
- Intent patterns: Questions about workflow selection

**Content:**
- Quick decision tree (5 questions)
- Workflow comparison matrix (5 workflows)
- Detailed workflow descriptions
- Agent architecture overview
- 8 deep-dive resource files

**How to use:**
```
User: "Which workflow should I use for implementing auth?"
MAP: [Auto-suggests map-workflows-guide skill]
User: "Load map-workflows-guide"
MAP: [Shows decision tree and comparison matrix]
```

**Resources available:**
- `map-fast-deep-dive.md` - When (not) to use /map-fast
- `map-efficient-deep-dive.md` - Optimization strategies
- `map-feature-deep-dive.md` - Full validation workflow
- `map-debug-deep-dive.md` - Debugging techniques
- `map-refactor-deep-dive.md` - Dependency analysis
- `agent-architecture.md` - How 8 agents orchestrate
- `playbook-system.md` - Knowledge storage and search
- `cipher-integration.md` - Cross-project learning

---

## Creating New Skills

See [docs/P1_SKILLS_SYSTEM_IMPLEMENTATION.md](../docs/P1_SKILLS_SYSTEM_IMPLEMENTATION.md) for:
- Skill structure (SKILL.md + resources/)
- 500-line rule (progressive disclosure pattern)
- Integration with auto-activation
- Testing procedures

### Skill Structure Template

```
.claude/skills/my-skill/
├── SKILL.md                      # Main entry (<500 lines)
│   ├── Frontmatter (YAML)
│   ├── Quick overview
│   ├── Decision support
│   └── Links to resources/
└── resources/
    ├── topic-1-deep-dive.md     # Detailed exploration
    ├── topic-2-deep-dive.md
    └── reference-guide.md       # Quick reference
```

### Frontmatter Format

```yaml
---
name: my-skill
description: Brief description of what this skill provides
version: 1.0
---
```

---

## Integration with Auto-Activation

Skills work seamlessly with P0 auto-activation system:

**How it works:**
1. User prompt analyzed by `user-prompt-submit.sh` hook
2. Hook checks `skill-rules.json` for matching triggers
3. If match found: Suggests skill to user
4. User can load skill for detailed guidance

**Configuration:**
- **Trigger definitions:** `.claude/skills/skill-rules.json`
- **Auto-activation hook:** `.claude/hooks/user-prompt-submit.sh`
- **Helper script:** `.claude/hooks/helpers/suggest_skill.py`

---

## File Structure

```
.claude/skills/
├── skill-rules.json                  # Trigger configuration for all skills
├── README.md                         # This file
└── map-workflows-guide/
    ├── SKILL.md                      # Main entry (<500 lines)
    └── resources/
        ├── map-fast-deep-dive.md
        ├── map-efficient-deep-dive.md
        ├── map-feature-deep-dive.md
        ├── map-debug-deep-dive.md
        ├── map-refactor-deep-dive.md
        ├── agent-architecture.md
        ├── playbook-system.md
        └── cipher-integration.md
```

---

## Best Practices

### For Skill Authors

1. **Follow 500-line rule** - Main SKILL.md should be scannable (~5 min read)
2. **Progressive disclosure** - Details in resources/, linked from main
3. **Clear triggers** - Define specific keywords and intent patterns
4. **Examples over theory** - Show concrete use cases
5. **Link related resources** - Cross-reference other skills/docs

### For Users

1. **Trust auto-suggestions** - Skills are triggered for good reasons
2. **Load skills proactively** - Don't guess, get guidance
3. **Explore resources** - Deep-dives provide comprehensive context
4. **Apply patterns** - Skills show "why" and "when", not just "how"

---

## Troubleshooting

### Skill not auto-suggesting

**Check:**
1. `skill-rules.json` has correct triggers
2. Hook reads `skill-rules.json` successfully
3. Test keyword matching manually:
   ```bash
   echo "which workflow should I use" | .claude/hooks/helpers/suggest_skill.py --rules .claude/skills/skill-rules.json
   ```

**Fix:** Update trigger patterns in `skill-rules.json`

### Skill content too long

**Problem:** Main SKILL.md exceeds 500 lines

**Solution:**
1. Move detailed sections to `resources/`
2. Keep only overview + navigation in main file
3. Add links to resources for deep dives

### Resources not loading

**Check:**
1. Resource files exist in `resources/` directory
2. Links in SKILL.md use correct paths
3. Markdown link syntax is valid

---

## Metrics

**Track skill effectiveness:**
- Activation rate (how often skills are suggested)
- Load rate (how often users load suggested skills)
- Resource access (which deep-dives are most popular)
- Workflow confusion reduction (before/after P1)

**Target metrics:**
- >30% of sessions load a skill
- ~50% reduction in "which workflow?" questions
- Correct workflow selection rate >80%

---

## See Also

- [P1 Implementation Plan](../docs/P1_SKILLS_SYSTEM_IMPLEMENTATION.md)
- [Auto-Activation System](../docs/auto-activation-comparison.md)
- [MAP Architecture](../docs/ARCHITECTURE.md)
