# MAP Skills System

MAP ships Claude Code skills as the runtime slash surface for MAP workflows and as supporting reference material. Skills are not agents, but they are not all passive documentation either: some skills define task procedures that call agents, run scripts, or write workflow artifacts.

## Skill Classes

MAP uses `skillClass` in `skill-rules.json` to make the runtime role explicit.

| Class | Use For | Runtime Boundary |
|-------|---------|------------------|
| `reference` | Conventions, heuristics, explanations, and decision support | Loads knowledge into the current session; should not own a deterministic workflow |
| `task` | Manual slash workflows such as `/map-efficient`, `/map-review`, and `/map-learn` | May orchestrate agents, run validation, and write artifacts when invoked |
| `hybrid` | Operational guidance with supporting hooks/scripts, currently `map-state` | Provides reference guidance and declares explicit `runtimeEffects` for hook or artifact side effects |

`type` and `enforcement` still describe activation behavior. `skillClass` describes what the skill is allowed to do after it is invoked.

## Current Classification

| Skill | Class | Notes |
|-------|-------|-------|
| `map-state` | `hybrid` | Explains branch-scoped planning and ships hooks/scripts that surface focus and completion checks |
| `map-learn` | `task` | Manual slash workflow with `disable-model-invocation: true`; writes learned rules from a completed workflow handoff |
| `map-plan`, `map-efficient`, `map-fast`, `map-debug`, `map-tdd`, `map-task`, `map-check`, `map-review`, `map-resume`, `map-release`, `map-explain` | `task` | Skill-backed slash workflows invoked directly by the user |

## Skills vs Agents

| Skills | Agents |
|--------|--------|
| Loaded through the Skill surface or invoked as slash workflows | Launched through the Task tool by a workflow |
| Define instructions, policies, hooks, scripts, and supporting files | Perform specialized analysis, implementation, review, or learning work |
| Own provider-facing runtime contracts under `.claude/skills/` | Own role-specific prompts under `.claude/agents/` |
| May call agents when the skill is a task workflow | Do not define slash surfaces themselves |

## File Structure

```text
.claude/skills/
├── skill-rules.json                  # Activation and skillClass metadata
├── README.md                         # This file
├── map-state/
│   ├── SKILL.md
│   └── scripts/
├── map-learn/
│   ├── SKILL.md
│   └── templates/
└── map-*/SKILL.md                    # Skill-backed MAP slash workflows
```

## Authoring Guidance

Use a `reference` skill when the content is mostly durable knowledge: conventions, decision trees, examples, troubleshooting, or domain guidance. Reference skills should be safe to load opportunistically and should avoid owning multi-step mutation procedures.

Use a `task` skill when the skill behaves like a workflow: it has required steps, validation gates, agent calls, file writes, commits, releases, or other deterministic procedures. Manual slash task skills should normally use `disable-model-invocation: true` and an `argument-hint` so users see a clear invocation shape.

Use `hybrid` only when both are true: the skill is useful as reference material, and it also ships runtime helpers such as hooks or scripts. Hybrid skills must list `runtimeEffects` in `skill-rules.json` so users can tell which behavior comes from reading instructions and which behavior comes from installed hooks or scripts.

Keep `SKILL.md` focused on invocation policy, decision rules, and navigation to supporting files. Move long examples, troubleshooting matrices, and templates into supporting files so invoked skill content stays compact.

## Template Sync

The development copy under `.claude/skills/` must stay byte-for-byte synced with `src/mapify_cli/templates/skills/`, because `mapify init` installs the template copy into user projects.

Use:

```bash
make render-templates
pytest tests/test_skills.py tests/test_template_render.py -v
```

## Troubleshooting

### Skill metadata drift

Run `pytest tests/test_skills.py -v`. The suite checks frontmatter, direct invocation metadata, skillClass values, hybrid runtime effects, trigger rules, supporting-file links, hook script paths, and template sync.

### Generated project does not match this branch

Run `uv run mapify init <new-temp-path> --no-git --mcp none` from this repo. Do not use a globally installed `mapify` binary for branch validation because it can lag behind local templates.

### New task skill is not invocable

Check that the skill has `argument-hint`, the direct `map-*` name appears in `skill-rules.json` keywords and intent patterns, and `skillClass` is `task`.
