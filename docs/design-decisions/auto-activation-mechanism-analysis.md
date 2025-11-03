# ST-001: Auto-Activation Mechanism Analysis

**Analysis Date:** 2025-11-02
**Subtask:** Analyze how UserPromptSubmit hook + workflow-rules.json enable auto-activation

---

## Executive Summary

Analyzed Showcase's auto-activation pattern and MAP's existing UserPromptSubmit hook implementation. **Key finding:** MAP already has the infrastructure (user-prompt-submit.sh + inject_playbook_bullets.py) to implement workflow auto-suggestion - just needs extension to add trigger matching logic. Combining MAP's knowledge injection with Showcase's workflow suggestion creates **hybrid approach** that's more powerful than either alone.

---

## How UserPromptSubmit Hook Works

### Execution Flow

```
1. User types message in Claude Code
   ↓
2. UserPromptSubmit hook fires (configured in settings.hooks.json)
   ↓
3. Hook receives user message via stdin
   ↓
4. Hook analyzes message (extract keywords, match patterns)
   ↓
5. Hook queries relevant data (playbook, workflow-rules.json)
   ↓
6. Hook outputs JSON: {continue: true, additionalContext: "injected content"}
   ↓
7. Claude receives ENRICHED message (original + additionalContext)
   ↓
8. Claude processes enriched prompt
```

### Critical Technical Details

**Execution Context:** Hook runs in **Bash context**, NOT Claude context
- ✅ Can use: CLI tools (mapify), file operations, subprocess calls
- ❌ Cannot use: MCP tools (cipher_memory_search), Claude-specific APIs

**Timeout:** 5 seconds (Claude Code limit)

**Error Handling:** Always returns `{continue: true}` on error - injection is enhancement, not blocker

**Current MAP Implementation:**
```bash
# .claude/hooks/user-prompt-submit.sh (lines 17-66)
USER_MESSAGE=$(cat)  # Read from stdin

# Call Python helper
OUTPUT=$(python3 "$HELPER_SCRIPT" --message "$USER_MESSAGE" --limit "$MAX_BULLETS")

# Output JSON
echo "$OUTPUT"  # {continue: true, additionalContext: "..."}
```

---

## Workflow-Rules.json Schema

### Showcase Pattern (Declarative Triggers)

```json
{
  "workflows": {
    "map-debug": {
      "triggers": {
        "keywords": ["fix", "bug", "error", "broken", "failing"],
        "intentPatterns": [
          "why (is|does) .* (not work|fail)",
          "debug .*"
        ],
        "filePatterns": ["*.py", "*.go", "*.js"]
      },
      "priority": "high"
    }
  }
}
```

### Trigger Types

#### 1. Keyword Triggers
- **Simple word matching:** "fix" → /map-debug
- **Pros:** Fast, simple, no regex complexity
- **Cons:** False positives ("fix typo in docs" shouldn't trigger code debugging)

#### 2. Intent Pattern Triggers (Regex)
- **Captures sentence structure:** "why does X fail" → debug intent
- **Pros:** More precise than keywords, understands context
- **Cons:** Requires careful regex design, harder to maintain

#### 3. File-Based Triggers
- **Context-aware:** `*.test.py` mentioned → suggest test workflow
- **Pros:** Dramatically reduces false positives
- **Cons:** Requires file path extraction from message

---

## Concrete Examples

### Scenario 1: Bug Fixing

**User Input:** "Fix the authentication bug in auth.py"

**Showcase Behavior:**
```
Trigger Match:
  - keywords: ['fix', 'bug'] ✓
  - filePatterns: ['*.py'] ✓

Suggestion:
  💡 Suggested workflow: /map-debug (matches bug fixing pattern)

  Based on your request, consider using `/map-debug` which provides:
  - Systematic root cause analysis
  - Monitor validation of fix
  - Reflector lessons learned

  Or proceed with your request without the workflow.
```

**MAP Current Behavior:**
```
Keyword Extraction: ['fix', 'authentication', 'bug', 'auth', 'py']

Playbook Query: mapify playbook query "fix authentication bug auth py" --limit 5

Injected Context:
  # Relevant Playbook Patterns

  ## 1. [debug-0042] DEBUGGING
  *Quality: 8/10 | Relevance: 0.85*

  When fixing authentication bugs, check JWT token expiration first...

  ## 2. [impl-0023] IMPLEMENTATION
  ...(3 more bullets)
```

**Comparison:** Showcase SUGGESTS workflow, MAP INJECTS relevant knowledge. Both are valuable!

---

### Scenario 2: Feature Implementation

**User Input:** "Add user profile page with avatar upload"

**Showcase Behavior:**
```
Trigger Match:
  - keywords: ['add'] ✓
  - intentPatterns: ['add .* (page|feature|component)'] ✓

Suggestion:
  💡 Suggested workflow: /map-feature (matches feature implementation pattern)
```

**MAP Current Behavior:**
```
Keyword Extraction: ['add', 'user', 'profile', 'page', 'avatar', 'upload']

Playbook Query: mapify playbook query "add user profile page avatar upload" --limit 5

Injected Context:
  # Relevant Playbook Patterns

  ## 1. [impl-0067] IMPLEMENTATION
  *Quality: 9/10 | Relevance: 0.78*

  When implementing file uploads, use presigned URLs to avoid server memory issues...
```

---

### Scenario 3: Refactoring

**User Input:** "Refactor the database layer to use repository pattern"

**Showcase Behavior:**
```
Trigger Match:
  - keywords: ['refactor'] ✓
  - intentPatterns: ['refactor .* to (use|implement)'] ✓

Suggestion:
  💡 Suggested workflow: /map-refactor (matches refactoring pattern)
```

---

### Scenario 4: Question (No Action)

**User Input:** "What is the MAP framework?"

**Showcase Behavior:**
```
Trigger Match: None (question, not action request)
Suggestion: None - no workflow needed
```

**MAP Current Behavior:**
```
Keyword Extraction: ['map', 'framework']

Playbook Query: mapify playbook query "map framework" --limit 5

Injected Context:
  # Relevant Playbook Patterns

  ## 1. [arch-0001] ARCHITECTURE
  *Quality: 10/10 | Relevance: 0.95*

  MAP Framework is a modular agentic planner with 8 specialized agents...

  (provides answer directly from playbook)
```

**Winner:** MAP's approach is BETTER for this scenario - provides answer from knowledge base instead of suggesting unnecessary workflow.

---

## Comparison: Manual vs Auto-Suggested Workflows

### MAP Current Approach (Manual Invocation)

**User Flow:**
```
1. User thinks "I need to fix a bug"
2. User remembers MAP has workflows
3. User recalls /map-debug exists
4. User types "/map-debug fix auth bug"
5. MAP workflow starts
```

**Problems:**
- ❌ User must REMEMBER MAP workflows exist
- ❌ User must REMEMBER which workflow to use
- ❌ User must REMEMBER slash command syntax
- ❌ High cognitive load for new users
- ❌ Easy to forget workflows after not using MAP for a while

---

### Showcase Approach (Auto-Suggested)

**User Flow:**
```
1. User thinks "I need to fix a bug"
2. User types naturally: "fix the auth bug"
3. UserPromptSubmit hook analyzes message
4. System suggests: "💡 Consider /map-debug workflow"
5. User decides: accept suggestion or proceed normally
```

**Benefits:**
- ✅ Zero cognitive load - user types naturally
- ✅ System teaches user about workflows organically
- ✅ No need to remember slash commands
- ✅ Works for experienced AND new users
- ✅ Non-intrusive - suggestion, not forced workflow

---

## Hybrid Approach for MAP

### Proposed Architecture

**Combine MAP's knowledge injection with Showcase's workflow suggestion:**

```
User types: "fix the auth bug in login.py"
  ↓
UserPromptSubmit hook extracts keywords: ['fix', 'auth', 'bug', 'login', 'py']
  ↓
Hook checks workflow-rules.json → keywords match /map-debug
  ↓
Hook queries playbook: mapify playbook query "fix auth bug login"
  ↓
Hook injects BOTH:
  1. Workflow suggestion: "💡 Consider /map-debug for systematic debugging"
  2. Knowledge bullets: Top 3 relevant playbook patterns about auth debugging
  ↓
Claude receives enriched message with:
  - Original user request
  - Suggested workflow (optional)
  - Relevant knowledge (always helpful)
  ↓
Claude can:
  (a) Invoke /map-debug automatically
  (b) Use knowledge directly without workflow
  (c) Ask user for clarification
```

### Advantages

✅ **Best of both worlds:** Proactive workflow suggestion + relevant knowledge
✅ **Non-blocking:** User can ignore suggestion and proceed with natural request
✅ **Educational:** Teaches users about MAP workflows organically
✅ **Flexible:** Claude decides whether to use workflow or handle directly
✅ **Backward compatible:** Existing playbook injection still works

---

## Proposed Implementation

### 1. Create workflow-rules.json

**Location:** `.claude/workflow-rules.json`

```json
{
  "workflows": {
    "/map-feature": {
      "triggers": {
        "keywords": ["implement", "add", "create", "build", "new"],
        "intentPatterns": [
          "implement .* (feature|functionality)",
          "add .* (page|component|module|service)",
          "create .* (api|endpoint|handler)"
        ],
        "filePatterns": ["src/**/*.py", "src/**/*.go", "src/**/*.js"],
        "antiPatterns": ["fix", "bug", "error", "refactor"]
      },
      "priority": "high",
      "description": "Systematic feature implementation with full MAP workflow",
      "suggestion_template": "💡 **Suggested workflow:** `/map-feature` - Implements new features with systematic validation and learning. [Learn more](docs/workflows.md#map-feature)"
    },

    "/map-debug": {
      "triggers": {
        "keywords": ["fix", "bug", "error", "broken", "failing", "crash", "issue"],
        "intentPatterns": [
          "why (is|does) .* (not work|fail|break)",
          "debug .*",
          "investigate .*",
          "figure out (why|what)",
          ".* (not working|failing|broken)"
        ],
        "filePatterns": ["**/*.py", "**/*.go", "**/*.js", "**/*.ts"],
        "antiPatterns": ["implement", "add", "create"]
      },
      "priority": "high",
      "description": "Systematic debugging with root cause analysis",
      "suggestion_template": "💡 **Suggested workflow:** `/map-debug` - Debug issues with systematic root cause analysis. [Learn more](docs/workflows.md#map-debug)"
    },

    "/map-refactor": {
      "triggers": {
        "keywords": ["refactor", "clean", "improve", "reorganize", "simplify", "optimize"],
        "intentPatterns": [
          "refactor .* to (use|implement|follow)",
          "clean up .*",
          "improve .* (structure|architecture|design)",
          "reorganize .*",
          "simplify .*"
        ],
        "filePatterns": ["**/*.py", "**/*.go", "**/*.js", "**/*.ts"],
        "antiPatterns": ["implement", "add", "bug", "fix"]
      },
      "priority": "medium",
      "description": "Refactoring with impact analysis",
      "suggestion_template": "💡 **Suggested workflow:** `/map-refactor` - Refactor code with impact analysis and systematic validation. [Learn more](docs/workflows.md#map-refactor)"
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

### 2. Extend inject_playbook_bullets.py

**Add workflow matching logic:**

```python
def load_workflow_rules() -> Dict:
    """Load workflow-rules.json"""
    rules_path = Path(".claude/workflow-rules.json")
    if not rules_path.exists():
        return {}
    return json.loads(rules_path.read_text())

def match_workflow_triggers(message: str, keywords: List[str]) -> Optional[Dict]:
    """Match user message against workflow triggers

    Returns:
        Dict with workflow name and suggestion if matched, None otherwise
    """
    rules = load_workflow_rules()
    if not rules:
        return None

    message_lower = message.lower()
    best_match = None
    best_priority = 0

    for workflow_name, workflow_config in rules.get("workflows", {}).items():
        triggers = workflow_config.get("triggers", {})
        priority_map = {"high": 3, "medium": 2, "low": 1}
        priority = priority_map.get(workflow_config.get("priority", "low"), 1)

        # Check antiPatterns first (exclusions)
        anti_patterns = triggers.get("antiPatterns", [])
        if any(anti in message_lower for anti in anti_patterns):
            continue  # Skip this workflow

        # Check keyword match
        workflow_keywords = triggers.get("keywords", [])
        keyword_match = any(kw in keywords for kw in workflow_keywords)

        # Check intent patterns (regex)
        intent_patterns = triggers.get("intentPatterns", [])
        intent_match = any(
            re.search(pattern, message_lower)
            for pattern in intent_patterns
        )

        # Match if either keywords or intent patterns match
        if keyword_match or intent_match:
            if priority > best_priority:
                best_match = {
                    "workflow": workflow_name,
                    "suggestion": workflow_config.get("suggestion_template", f"Consider using {workflow_name}"),
                    "priority": workflow_config.get("priority", "low")
                }
                best_priority = priority

    return best_match

def format_output_with_workflow(playbook_bullets: str, workflow_suggestion: Optional[Dict]) -> str:
    """Combine playbook bullets with workflow suggestion"""
    parts = []

    # Add workflow suggestion first (most visible)
    if workflow_suggestion:
        parts.append(workflow_suggestion["suggestion"])
        parts.append("\n---\n")

    # Add playbook bullets
    if playbook_bullets:
        parts.append(playbook_bullets)

    return "\n".join(parts)
```

### 3. Update main() function

```python
def main():
    # ... existing code ...

    # Extract keywords
    keywords = extract_keywords(args.message)

    # Match workflow triggers
    workflow_match = match_workflow_triggers(args.message, keywords)

    # Query playbook (existing logic)
    response = query_playbook(keywords, args.limit)
    playbook_bullets = format_bullets_as_markdown(response.get('results', []))

    # Combine workflow suggestion + playbook bullets
    additional_context = format_output_with_workflow(playbook_bullets, workflow_match)

    # Output JSON
    if additional_context:
        output = {"continue": True, "additionalContext": additional_context}
    else:
        output = {"continue": True}

    print(json.dumps(output, indent=2))
```

### 4. Add Session State Tracking

**Prevent suggestion fatigue:**

```python
def check_session_state(workflow_name: str) -> bool:
    """Check if workflow was recently suggested in this session

    Returns:
        True if suggestion is allowed, False if in cooldown period
    """
    state_file = Path(".claude/.hook_state/workflow_suggestions.json")
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Load session state
    if state_file.exists():
        state = json.loads(state_file.read_text())
    else:
        state = {"suggestions": {}}

    # Check cooldown
    last_suggested = state["suggestions"].get(workflow_name)
    if last_suggested:
        last_time = datetime.fromisoformat(last_suggested)
        cooldown_minutes = 5  # From workflow-rules.json settings
        if datetime.now() - last_time < timedelta(minutes=cooldown_minutes):
            return False  # Still in cooldown

    # Update state
    state["suggestions"][workflow_name] = datetime.now().isoformat()
    state_file.write_text(json.dumps(state, indent=2))

    return True
```

---

## Key Insights

### 1. Architectural Constraint
**UserPromptSubmit hook is BASH-BASED**, not Claude-based
→ Can only use CLI tools (mapify), NOT MCP tools (cipher)
→ This is design decision, not limitation - hooks execute before Claude context exists

### 2. Existing Infrastructure
**MAP already HAS UserPromptSubmit hook** that injects playbook bullets
→ Extending it to also suggest workflows is straightforward change
→ No need to build from scratch, just enhance existing implementation

### 3. Complementary Patterns
**Showcase pattern (workflow suggestion) + MAP pattern (knowledge injection) = Hybrid approach**
→ More powerful than either alone
→ Workflow suggestion guides user, knowledge bullets provide substance

### 4. UX Transformation
**Auto-activation solves "users forget workflows exist" problem**
→ Turns MAP from "tool you invoke" into "assistant that guides you"
→ Fundamental UX improvement - proactive vs reactive

### 5. Session Awareness
**Session tracking prevents annoyance**
→ Don't suggest same workflow twice in 5 minutes
→ Max 3 suggestions per session
→ Showcase has this, MAP doesn't yet - critical for good UX

### 6. Declarative Configuration
**JSON-based trigger rules > hardcoded Python logic**
→ Non-developers can add new triggers without coding
→ Easier to maintain and version control
→ Clear separation of concerns (logic vs configuration)

### 7. False Positive Mitigation
**File-based triggers + antiPatterns dramatically reduce false positives**
→ "fix bug" in `docs/*.md` shouldn't suggest /map-debug for code
→ antiPatterns: ["implement"] prevents /map-debug from matching "implement fix for bug"
→ Context-aware suggestions feel intelligent, not spammy

### 8. Priority System
**Handles conflicting triggers intelligently**
→ If both /map-debug and /map-refactor match, prioritize based on confidence
→ High priority workflows take precedence over medium/low
→ Prevents ambiguous suggestions

---

## Implementation Effort & Impact

### Effort Estimate
**Medium (2-4 hours of development)**
- Create workflow-rules.json: 30 minutes
- Extend inject_playbook_bullets.py: 90 minutes
- Add session state tracking: 45 minutes
- Testing and refinement: 60 minutes

### Expected Impact
**High - Transforms MAP UX from "manual invocation" to "guided assistance"**

**Metrics to track:**
- Workflow usage frequency (before vs after)
- User confusion incidents ("which workflow should I use?")
- Time to first workflow invocation (new users)
- Suggestion acceptance rate (% of suggestions actually used)

---

## Testing Strategy

### Unit Tests
```python
def test_keyword_extraction():
    """Test keyword extraction filters stop words correctly"""

def test_intent_pattern_matching():
    """Test regex patterns match user intent"""

def test_anti_pattern_filtering():
    """Test antiPatterns prevent false positives"""

def test_priority_resolution():
    """Test highest priority workflow wins in conflicts"""

def test_session_state_tracking():
    """Test cooldown prevents repeat suggestions"""
```

### Integration Tests
```python
def test_full_hook_with_workflow_suggestion():
    """Test complete UserPromptSubmit hook flow with workflow matching"""

def test_combined_playbook_and_workflow_injection():
    """Test hybrid approach injects both suggestions and knowledge"""

def test_hook_timeout_compliance():
    """Test hook completes within 5s timeout for worst-case input"""
```

### Manual Testing
```bash
# Test bug fixing suggestion
echo "Fix the authentication bug in auth.py" | .claude/hooks/user-prompt-submit.sh

# Test feature implementation suggestion
echo "Add user profile page with avatar upload" | .claude/hooks/user-prompt-submit.sh

# Test refactoring suggestion
echo "Refactor database layer to use repository pattern" | .claude/hooks/user-prompt-submit.sh

# Test no suggestion (question)
echo "What is the MAP framework?" | .claude/hooks/user-prompt-submit.sh

# Test session cooldown
echo "Fix bug 1" | .claude/hooks/user-prompt-submit.sh
echo "Fix bug 2" | .claude/hooks/user-prompt-submit.sh  # Should NOT suggest again (cooldown)
```

---

## Next Steps

### Immediate Actions
1. ✅ Create workflow-rules.json with initial trigger definitions
2. ✅ Extend inject_playbook_bullets.py to load and match workflow triggers
3. ✅ Add format_workflow_suggestion() function
4. ✅ Update format_output() to include BOTH playbook bullets AND workflow suggestion
5. ✅ Add session state tracking to prevent suggestion fatigue

### Testing Phase
1. ⏳ Write unit tests for keyword/pattern matching
2. ⏳ Write integration tests for full hook workflow
3. ⏳ Manual testing with various user messages to tune triggers
4. ⏳ Gather user feedback on suggestion quality and UX

### Documentation
1. ⏳ Update .claude/hooks/README.md to document workflow suggestion feature
2. ⏳ Create docs/workflows.md explaining when to use each workflow
3. ⏳ Add examples to workflow-rules.json with inline comments
4. ⏳ Update USAGE.md with auto-suggestion examples

### Future Enhancements
1. 📋 Add file-based triggers (extract file paths from message)
2. 📋 Add confidence scoring (show confidence % for suggestions)
3. 📋 Add multi-workflow suggestions (show top 2 if both match)
4. 📋 Add learning from user acceptance (decrease confidence if suggestion ignored)
5. 📋 Add project-specific trigger customization (per-project overrides)

---

## References

- **Showcase Analysis:** SHOWCASE_ANALYSIS_SUMMARY.md (lines 1-218)
- **Synthesis JSON:** ST-007-synthesis.json (lines 1-184)
- **MAP Hook Implementation:** .claude/hooks/user-prompt-submit.sh (lines 1-67)
- **Helper Script:** .claude/hooks/helpers/inject_playbook_bullets.py (lines 1-209)
- **Hook Documentation:** .claude/hooks/README.md (lines 1-272)

---

## Conclusion

Showcase's auto-activation pattern via UserPromptSubmit hook is **directly applicable to MAP** with minimal implementation effort. MAP already has the infrastructure in place - just needs extension to add workflow trigger matching. The proposed **hybrid approach** (workflow suggestion + knowledge injection) is more powerful than either pattern alone and transforms MAP's UX from "tool you invoke" to "assistant that guides you."

**Most impactful change:** Users no longer need to remember slash commands - MAP proactively suggests the right workflow based on their natural language request, while still providing relevant knowledge from the playbook. This dramatically lowers the cognitive load for both new and experienced users.
