# Auto-Activation Comparison: Manual vs Auto-Suggested Workflows

## Current State: Manual Invocation

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER JOURNEY                             │
└─────────────────────────────────────────────────────────────────┘

   User thinks: "I need to fix a bug"
                      │
                      ▼
   ┌────────────────────────────────────────┐
   │ User must REMEMBER:                     │
   │ 1. MAP workflows exist                  │
   │ 2. Which workflow to use (/map-debug)   │
   │ 3. Slash command syntax                 │
   └────────────────────────────────────────┘
                      │
                      ▼
   User types: "/map-debug fix auth bug"
                      │
                      ▼
   ┌────────────────────────────────────────┐
   │ MAP workflow starts                     │
   │ - Task Decomposer                       │
   │ - Actor → Monitor → Predictor           │
   │ - Evaluator → Reflector → Curator       │
   └────────────────────────────────────────┘

   ❌ PROBLEMS:
   - High cognitive load (must remember workflows)
   - Poor discoverability (new users don't know workflows exist)
   - Easy to forget after not using MAP for a while
   - Friction in workflow adoption
```

---

## Proposed State: Auto-Suggested Workflows

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER JOURNEY                             │
└─────────────────────────────────────────────────────────────────┘

   User thinks: "I need to fix a bug"
                      │
                      ▼
   User types naturally: "fix the auth bug"
                      │
                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │              UserPromptSubmit HOOK                           │
   │                                                              │
   │  1. Extract keywords: ['fix', 'auth', 'bug']                │
   │  2. Load workflow-rules.json                                │
   │  3. Match triggers:                                         │
   │     - keywords: ['fix', 'bug'] ✓                            │
   │     - intentPatterns: match                                 │
   │     - priority: high                                        │
   │  4. Query playbook: "fix auth bug"                          │
   │  5. Check session state (cooldown)                          │
   └─────────────────────────────────────────────────────────────┘
                      │
                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │              ENRICHED MESSAGE TO CLAUDE                      │
   │                                                              │
   │  Original: "fix the auth bug"                               │
   │                                                              │
   │  💡 Suggested workflow: /map-debug                          │
   │     Debug issues with systematic root cause analysis.       │
   │     [Learn more](docs/workflows.md#map-debug)               │
   │                                                              │
   │  ---                                                         │
   │                                                              │
   │  # Relevant Playbook Patterns                               │
   │                                                              │
   │  ## 1. [debug-0042] DEBUGGING                               │
   │  *Quality: 8/10 | Relevance: 0.85*                          │
   │                                                              │
   │  When fixing authentication bugs, check JWT token           │
   │  expiration first...                                        │
   │                                                              │
   │  ## 2. [impl-0023] IMPLEMENTATION                           │
   │  ...                                                         │
   └─────────────────────────────────────────────────────────────┘
                      │
                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │              CLAUDE DECISION TREE                            │
   │                                                              │
   │  Option A: Invoke /map-debug automatically                  │
   │  Option B: Use playbook knowledge directly                  │
   │  Option C: Ask user for clarification                       │
   └─────────────────────────────────────────────────────────────┘

   ✅ BENEFITS:
   - Zero cognitive load (type naturally)
   - Self-teaching system (discovers workflows organically)
   - Works for new AND experienced users
   - Non-intrusive (suggestion, not forced)
   - Combines workflow guidance + knowledge injection
```

---

## Side-by-Side Comparison

| Aspect | Manual Invocation (Current) | Auto-Suggested (Proposed) |
|--------|----------------------------|---------------------------|
| **User Input** | `/map-debug fix auth bug` | `fix the auth bug` |
| **Cognitive Load** | High (must remember syntax) | Zero (type naturally) |
| **Discoverability** | Poor (requires documentation) | Excellent (system teaches) |
| **New User Experience** | Confusing ("what workflows exist?") | Intuitive (suggestions guide) |
| **Experienced User** | Fast (if remembered) | Faster (no syntax needed) |
| **Workflow Adoption** | Low (forgotten after disuse) | High (proactive suggestions) |
| **Context Provided** | None (user provides all context) | Rich (workflow + knowledge bullets) |
| **Flexibility** | None (must use workflow) | High (suggestion can be ignored) |

---

## Technical Architecture Comparison

### Current: Direct Invocation

```
┌──────────┐
│   User   │
└────┬─────┘
     │ Types: "/map-debug fix bug"
     ▼
┌─────────────────┐
│  Claude Code    │
│  Slash Command  │
│  Parser         │
└────┬────────────┘
     │ Invoke slash command
     ▼
┌─────────────────────┐
│  /map-debug.md      │
│  (Command Template) │
└────┬────────────────┘
     │ Orchestrate agents
     ▼
┌─────────────────────────────────┐
│  Task → Actor → Monitor →       │
│  Predictor → Evaluator →        │
│  Reflector → Curator            │
└─────────────────────────────────┘
```

### Proposed: Hook-Based Auto-Activation

```
┌──────────┐
│   User   │
└────┬─────┘
     │ Types: "fix the auth bug"
     ▼
┌───────────────────────────────────┐
│  UserPromptSubmit HOOK            │
│  (.claude/hooks/                  │
│   user-prompt-submit.sh)          │
└────┬──────────────────────────────┘
     │ Call helper script
     ▼
┌───────────────────────────────────────────────────┐
│  inject_playbook_bullets.py                       │
│                                                   │
│  1. extract_keywords("fix the auth bug")         │
│     → ['fix', 'auth', 'bug']                     │
│                                                   │
│  2. match_workflow_triggers(message, keywords)   │
│     Load workflow-rules.json                     │
│     Match: /map-debug (high priority)            │
│                                                   │
│  3. query_playbook("fix auth bug")               │
│     mapify playbook query --format json          │
│                                                   │
│  4. check_session_state("/map-debug")            │
│     Not suggested in last 5 minutes ✓            │
│                                                   │
│  5. format_output_with_workflow()                │
│     Combine suggestion + bullets                 │
└────┬──────────────────────────────────────────────┘
     │ Return JSON
     ▼
┌───────────────────────────────────────────────────┐
│  {                                                │
│    "continue": true,                             │
│    "additionalContext": "                        │
│      💡 Suggested: /map-debug                    │
│                                                   │
│      # Relevant Playbook Patterns                │
│      ## 1. [debug-0042] DEBUGGING                │
│      ...                                          │
│    "                                              │
│  }                                                │
└────┬──────────────────────────────────────────────┘
     │ Inject into prompt
     ▼
┌───────────────────────────────────────────────────┐
│  Claude Code receives ENRICHED message:           │
│                                                   │
│  User: "fix the auth bug"                        │
│                                                   │
│  [Context from hook]                             │
│  💡 Suggested workflow: /map-debug               │
│  # Relevant Playbook Patterns                    │
│  ...                                              │
└────┬──────────────────────────────────────────────┘
     │ Claude decides
     ▼
┌───────────────────────────────────────────────────┐
│  DECISION TREE:                                   │
│                                                   │
│  IF user intent is clear AND workflow suggested: │
│    → Invoke /map-debug automatically             │
│  ELSE IF playbook has answer:                    │
│    → Use knowledge directly (no workflow)        │
│  ELSE:                                            │
│    → Ask user for clarification                  │
└───────────────────────────────────────────────────┘
```

---

## Workflow Rules JSON Structure

```json
{
  "workflows": {
    "/map-debug": {
      "triggers": {
        "keywords": [
          "fix", "bug", "error", "broken",
          "failing", "crash", "issue"
        ],
        "intentPatterns": [
          "why (is|does) .* (not work|fail|break)",
          "debug .*",
          "investigate .*",
          ".* (not working|failing|broken)"
        ],
        "filePatterns": [
          "**/*.py", "**/*.go",
          "**/*.js", "**/*.ts"
        ],
        "antiPatterns": [
          "implement", "add", "create"
        ]
      },
      "priority": "high",
      "suggestion_template": "💡 **Suggested workflow:** `/map-debug`"
    },

    "/map-feature": {
      "triggers": {
        "keywords": [
          "implement", "add", "create",
          "build", "new"
        ],
        "intentPatterns": [
          "implement .* (feature|functionality)",
          "add .* (page|component|module)",
          "create .* (api|endpoint|handler)"
        ],
        "antiPatterns": [
          "fix", "bug", "error", "refactor"
        ]
      },
      "priority": "high",
      "suggestion_template": "💡 **Suggested workflow:** `/map-feature`"
    },

    "/map-refactor": {
      "triggers": {
        "keywords": [
          "refactor", "clean", "improve",
          "reorganize", "simplify"
        ],
        "intentPatterns": [
          "refactor .* to (use|implement)",
          "clean up .*",
          "improve .* (structure|design)"
        ],
        "antiPatterns": [
          "implement", "add", "bug", "fix"
        ]
      },
      "priority": "medium",
      "suggestion_template": "💡 **Suggested workflow:** `/map-refactor`"
    }
  },

  "settings": {
    "max_suggestions_per_session": 3,
    "suggestion_cooldown_minutes": 5,
    "enable_file_based_triggers": true,
    "enable_intent_patterns": true,
    "priority_threshold": "medium"
  }
}
```

---

## Session State Tracking

```json
{
  "suggestions": {
    "/map-debug": "2025-11-02T14:23:45",
    "/map-feature": "2025-11-02T13:15:30"
  },
  "suggestion_count": 2,
  "session_start": "2025-11-02T13:00:00"
}
```

**Cooldown Logic:**
- If workflow suggested < 5 minutes ago → Skip suggestion (prevent spam)
- If suggestion_count >= 3 → Skip suggestion (prevent fatigue)
- Session state persists in `.claude/.hook_state/workflow_suggestions.json`

---

## Example Interactions

### Example 1: Bug Fixing (High Priority Match)

```
USER:
"Fix the authentication bug in auth.py"

HOOK ANALYSIS:
- Keywords: ['fix', 'auth', 'bug', 'py']
- Workflow match: /map-debug (high priority)
- Playbook query: "fix auth bug"
- Session state: Not suggested recently ✓

CLAUDE RECEIVES:
Original: "Fix the authentication bug in auth.py"

💡 **Suggested workflow:** `/map-debug` - Debug issues with
systematic root cause analysis.

---

# Relevant Playbook Patterns

## 1. [debug-0042] DEBUGGING
*Quality: 8/10 | Relevance: 0.85*

When fixing authentication bugs, check JWT token expiration
first. Common issue: tokens expire after 1 hour but UI doesn't
handle refresh...

CLAUDE ACTION:
"I'll use the /map-debug workflow to systematically fix this bug.
Let me start by decomposing the debugging task..."

[Invokes /map-debug automatically]
```

### Example 2: Feature Request (High Priority Match)

```
USER:
"Add user profile page with avatar upload"

HOOK ANALYSIS:
- Keywords: ['add', 'user', 'profile', 'page', 'avatar', 'upload']
- Workflow match: /map-feature (high priority)
- Playbook query: "add user profile page avatar upload"
- Session state: Not suggested recently ✓

CLAUDE RECEIVES:
Original: "Add user profile page with avatar upload"

💡 **Suggested workflow:** `/map-feature` - Implements new
features with systematic validation and learning.

---

# Relevant Playbook Patterns

## 1. [impl-0067] IMPLEMENTATION
*Quality: 9/10 | Relevance: 0.78*

When implementing file uploads, use presigned URLs to avoid
server memory issues. Pattern: 1) Generate presigned URL,
2) Client uploads directly to S3, 3) Server validates...

CLAUDE ACTION:
"I'll use the /map-feature workflow to implement this
systematically. Let me decompose this into subtasks..."

[Invokes /map-feature automatically]
```

### Example 3: Refactoring (Medium Priority Match)

```
USER:
"Refactor the database layer to use repository pattern"

HOOK ANALYSIS:
- Keywords: ['refactor', 'database', 'layer', 'repository', 'pattern']
- Workflow match: /map-refactor (medium priority)
- Playbook query: "refactor database layer repository pattern"
- Session state: Not suggested recently ✓

CLAUDE RECEIVES:
Original: "Refactor the database layer to use repository pattern"

💡 **Suggested workflow:** `/map-refactor` - Refactor code
with impact analysis and systematic validation.

---

# Relevant Playbook Patterns

## 1. [refactor-0089] REFACTORING
*Quality: 7/10 | Relevance: 0.92*

Repository pattern: 1) Create interface first, 2) Implement
concrete repos, 3) Inject dependencies. Benefits: testability,
decoupling, maintainability...

CLAUDE ACTION:
"I'll use the /map-refactor workflow to ensure we don't break
existing functionality. Let me start by analyzing the impact..."

[Invokes /map-refactor automatically]
```

### Example 4: Question (No Workflow Needed)

```
USER:
"What is the MAP framework?"

HOOK ANALYSIS:
- Keywords: ['map', 'framework']
- Workflow match: None (question, not action)
- Playbook query: "map framework"
- Session state: N/A

CLAUDE RECEIVES:
Original: "What is the MAP framework?"

# Relevant Playbook Patterns

## 1. [arch-0001] ARCHITECTURE
*Quality: 10/10 | Relevance: 0.95*

MAP Framework is a modular agentic planner with 8 specialized
agents working in orchestrated sequence...

CLAUDE ACTION:
"Based on the playbook, MAP Framework is a modular agentic
planner with 8 specialized agents..."

[Answers directly from playbook, no workflow invocation]
```

### Example 5: Cooldown Prevention

```
USER (14:00):
"Fix bug in login"

HOOK ANALYSIS:
- Workflow match: /map-debug
- Session state: Last suggested /map-debug at 13:58 (2 mins ago)
- Cooldown active: YES (5 min cooldown)
- Skip workflow suggestion, inject playbook only

CLAUDE RECEIVES:
Original: "Fix bug in login"

# Relevant Playbook Patterns
[No workflow suggestion - cooldown active]

---

USER (14:10):
"Fix bug in signup"

HOOK ANALYSIS:
- Workflow match: /map-debug
- Session state: Last suggested /map-debug at 13:58 (12 mins ago)
- Cooldown expired: YES
- Suggest workflow again

CLAUDE RECEIVES:
Original: "Fix bug in signup"

💡 **Suggested workflow:** `/map-debug`
[Workflow suggestion shown - cooldown expired]
```

---

## Implementation Checklist

### Phase 1: Core Infrastructure
- [x] Analyze Showcase pattern (ST-001)
- [ ] Create workflow-rules.json schema
- [ ] Extend inject_playbook_bullets.py with trigger matching
- [ ] Add format_workflow_suggestion() function
- [ ] Update format_output() to combine suggestions + bullets

### Phase 2: Session Management
- [ ] Implement check_session_state() function
- [ ] Create .claude/.hook_state/ directory structure
- [ ] Add session state persistence (JSON file)
- [ ] Implement cooldown logic (5 minute default)
- [ ] Implement max suggestions per session (3 default)

### Phase 3: Testing
- [ ] Unit tests for keyword extraction
- [ ] Unit tests for intent pattern matching
- [ ] Unit tests for antiPattern filtering
- [ ] Unit tests for session state tracking
- [ ] Integration test for full hook workflow
- [ ] Manual testing with various user messages

### Phase 4: Documentation
- [ ] Update .claude/hooks/README.md
- [ ] Create docs/workflows.md (explain each workflow)
- [ ] Add inline comments to workflow-rules.json
- [ ] Update USAGE.md with auto-suggestion examples
- [ ] Create migration guide for existing users

### Phase 5: Refinement
- [ ] Gather user feedback on suggestion quality
- [ ] Tune trigger keywords/patterns based on feedback
- [ ] Adjust cooldown/max suggestions based on usage
- [ ] Add project-specific workflow-rules.json overrides
- [ ] Consider confidence scoring for suggestions

---

## Success Metrics

### Quantitative Metrics
- **Workflow usage frequency:** Track before/after implementation
- **Suggestion acceptance rate:** % of suggestions that result in workflow invocation
- **Time to first workflow:** New users (days to first /map-* usage)
- **False positive rate:** % of suggestions that were irrelevant
- **Session suggestion count:** Average suggestions per session

### Qualitative Metrics
- **User confusion incidents:** "Which workflow should I use?" questions
- **User feedback:** Survey responses on UX improvement
- **Documentation references:** Decrease in workflow documentation lookups
- **Organic discovery:** Users discovering workflows without reading docs

### Target Goals
- 50%+ increase in workflow usage frequency
- 70%+ suggestion acceptance rate
- 3x faster time to first workflow for new users
- <10% false positive rate
- Average 1-2 suggestions per session (not overwhelming)

---

## Conclusion

The auto-activation pattern via UserPromptSubmit hook transforms MAP from a "tool you must remember to invoke" into an "assistant that proactively guides you." By combining workflow suggestions (Showcase pattern) with knowledge injection (MAP pattern), we create a hybrid approach that:

✅ **Reduces cognitive load** - Type naturally, system suggests workflows
✅ **Improves discoverability** - Learn workflows organically through suggestions
✅ **Maintains flexibility** - Suggestions are non-intrusive, can be ignored
✅ **Provides substance** - Workflow guidance + relevant knowledge bullets
✅ **Prevents fatigue** - Session tracking ensures suggestions don't become spam

**Implementation is straightforward** - MAP already has the infrastructure (user-prompt-submit.sh + inject_playbook_bullets.py), just needs extension to add trigger matching logic. Expected development time: 2-4 hours for core functionality, plus testing and refinement.
