# Implementation Plan: Auto-Activation System for MAP Framework

## Context

После анализа claude-code-infrastructure-showcase (2k+ stars) были выявлены 3 genuinely новых паттерна для улучшения MAP Framework. Анализ завершен, результаты закоммичены в commit 29cfeb1.

**Статус:**
- ✅ Анализ завершен (6 subtasks)
- ✅ Playbook обновлен (147→152 bullets, 2 deprecated)
- ✅ Документация создана (docs/MAP_VS_SHOWCASE_COMPARISON.md)
- ✅ Cleanup выполнен, commit создан
- 🔄 **СЛЕДУЮЩЕЕ:** Реализация P0 - Auto-Activation System

---

## Priority P0: Auto-Activation System (2-4 hours) ⭐

### Что это такое?

**Проблема:** Пользователь должен помнить и вручную вводить /map-debug, /map-feature, /map-efficient

**Решение:** UserPromptSubmit hook автоматически анализирует контекст и предлагает подходящий workflow

**Пример:**
```
Пользователь: "У меня failing tests в auth.test.ts"
MAP (автоматически): "🎯 WORKFLOW SUGGESTION: Consider using /map-debug
  Reason: Detected keywords ['failing', 'tests'] + file pattern 'auth.test.ts'"
```

### Референсы для изучения

**Созданная документация:**
1. `ST-001-AUTO-ACTIVATION-ANALYSIS.md` (684 lines) - ГЛАВНЫЙ ДОКУМЕНТ с implementation guide
2. `docs/auto-activation-comparison.md` (583 lines) - User journey diagrams
3. `docs/MAP_VS_SHOWCASE_COMPARISON.md` (section "Auto-Activation System")

**Showcase implementation reference:**
- `docs/claude-code-infrastructure-showcase/.claude/hooks/skill-activation-prompt.ts`
- `docs/claude-code-infrastructure-showcase/.claude/skills/skill-rules.json`

### Implementation Steps

#### Шаг 1: Создать workflow-rules.json (15 минут)

**Файл:** `.claude/workflow-rules.json`

**Содержание:**
```json
{
  "version": "1.0",
  "description": "MAP workflow activation triggers",
  "workflows": {
    "map-debug": {
      "priority": "high",
      "description": "Debug issues, fix bugs, resolve test failures",
      "promptTriggers": {
        "keywords": [
          "bug",
          "error",
          "failing test",
          "broken",
          "not working",
          "issue",
          "fix",
          "debug"
        ],
        "intentPatterns": [
          "(fix|debug|resolve).*?(bug|error|issue|test)",
          "(why|what).*?(not working|failing|broken)",
          "tests?.*?(fail|error)"
        ]
      },
      "fileTriggers": {
        "pathPatterns": [
          "**/*.test.ts",
          "**/*.test.py",
          "**/*.spec.ts",
          "**/tests/**"
        ]
      }
    },
    "map-feature": {
      "priority": "high",
      "description": "Implement new features (critical, full validation)",
      "promptTriggers": {
        "keywords": [
          "implement",
          "add feature",
          "new feature",
          "create",
          "build",
          "critical"
        ],
        "intentPatterns": [
          "(implement|add|create|build).*?(feature|functionality)",
          "new.*?(feature|component|module)",
          "critical.*?(feature|implementation)"
        ]
      }
    },
    "map-efficient": {
      "priority": "high",
      "description": "Production features (optimized workflow, 60-70% tokens)",
      "promptTriggers": {
        "keywords": [
          "production",
          "optimize",
          "enhance",
          "improve",
          "update feature"
        ],
        "intentPatterns": [
          "(optimize|enhance|improve).*?(feature|code|implementation)",
          "production.*?(feature|deploy)",
          "update.*?(feature|functionality)"
        ]
      }
    },
    "map-refactor": {
      "priority": "medium",
      "description": "Refactor code, improve structure",
      "promptTriggers": {
        "keywords": [
          "refactor",
          "restructure",
          "reorganize",
          "clean up",
          "improve structure"
        ],
        "intentPatterns": [
          "(refactor|restructure|reorganize).*?(code|component|module)",
          "clean.*?up.*?(code|structure)",
          "improve.*?(structure|architecture)"
        ]
      }
    },
    "map-fast": {
      "priority": "low",
      "description": "Quick prototypes, throwaway code (NO learning)",
      "promptTriggers": {
        "keywords": [
          "quick",
          "prototype",
          "throwaway",
          "experiment",
          "test idea",
          "spike"
        ],
        "intentPatterns": [
          "(quick|fast).*?(prototype|test|experiment)",
          "throwaway.*?(code|implementation)",
          "(spike|experiment).*?(idea|approach)"
        ]
      }
    }
  },
  "notes": {
    "priority_matching": "If multiple workflows match, suggest highest priority",
    "session_tracking": "Track suggested workflows per session to avoid repeats",
    "customization": "Add project-specific keywords and file patterns as needed"
  }
}
```

**Команды для создания:**
```bash
# Создать файл
# (используй Write tool с содержимым выше)

# Проверить валидность JSON
jq . .claude/workflow-rules.json
```

#### Шаг 2: Создать UserPromptSubmit hook (30-45 минут)

**Файл:** `.claude/hooks/user-prompt-submit.sh`

**Базовая версия (bash):**
```bash
#!/bin/bash
# .claude/hooks/user-prompt-submit.sh
# UserPromptSubmit hook for MAP workflow auto-activation

set -euo pipefail

# Read input from stdin (JSON with {prompt, recentFiles, ...})
INPUT=$(cat)

# Extract prompt (lowercase for matching)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""' | tr '[:upper:]' '[:lower:]')

# Exit if empty prompt
if [ -z "$PROMPT" ]; then
  exit 0
fi

# Load workflow rules
RULES_FILE=".claude/workflow-rules.json"
if [ ! -f "$RULES_FILE" ]; then
  exit 0
fi

# Session tracking to avoid repeat suggestions
SESSION_FILE=".claude/cache/workflow_suggestions_session.txt"
mkdir -p .claude/cache

# Check if already suggested in this session
if [ -f "$SESSION_FILE" ]; then
  SUGGESTED_COUNT=$(wc -l < "$SESSION_FILE" 2>/dev/null || echo "0")
  if [ "$SUGGESTED_COUNT" -ge 1 ]; then
    # Already suggested once this session, skip
    exit 0
  fi
fi

# Match workflows
MATCHED_WORKFLOW=""
MATCH_REASON=""

# Check map-debug triggers
if echo "$PROMPT" | grep -qE "(bug|error|failing test|broken|fix|debug)"; then
  MATCHED_WORKFLOW="map-debug"
  MATCH_REASON="Detected keywords: bug/error/failing test"
fi

# Check map-feature triggers
if [ -z "$MATCHED_WORKFLOW" ] && echo "$PROMPT" | grep -qE "(implement|add feature|new feature|create)"; then
  MATCHED_WORKFLOW="map-feature"
  MATCH_REASON="Detected keywords: implement/add feature"
fi

# Check map-efficient triggers
if [ -z "$MATCHED_WORKFLOW" ] && echo "$PROMPT" | grep -qE "(production|optimize|enhance|improve)"; then
  MATCHED_WORKFLOW="map-efficient"
  MATCH_REASON="Detected keywords: production/optimize"
fi

# Check map-refactor triggers
if [ -z "$MATCHED_WORKFLOW" ] && echo "$PROMPT" | grep -qE "(refactor|restructure|reorganize)"; then
  MATCHED_WORKFLOW="map-refactor"
  MATCH_REASON="Detected keywords: refactor/restructure"
fi

# Check map-fast triggers
if [ -z "$MATCHED_WORKFLOW" ] && echo "$PROMPT" | grep -qE "(quick|prototype|throwaway|experiment)"; then
  MATCHED_WORKFLOW="map-fast"
  MATCH_REASON="Detected keywords: quick/prototype"
fi

# If matched, output suggestion
if [ -n "$MATCHED_WORKFLOW" ]; then
  echo ""
  echo "🎯 WORKFLOW SUGGESTION: Consider using /$MATCHED_WORKFLOW"
  echo "   Reason: $MATCH_REASON"
  echo ""
  echo "   To use: Type '/$MATCHED_WORKFLOW' or ask me to use it"
  echo "   To skip: Continue with your request"
  echo ""

  # Track suggestion
  echo "$MATCHED_WORKFLOW" >> "$SESSION_FILE"
fi

exit 0
```

**Команды для создания:**
```bash
# Создать hook (используй Write tool)

# Сделать исполняемым
chmod +x .claude/hooks/user-prompt-submit.sh

# Тестирование вручную
echo '{"prompt": "fix bug in auth.test.ts"}' | .claude/hooks/user-prompt-submit.sh
# Expected output: Suggestion for /map-debug

echo '{"prompt": "implement new user registration"}' | .claude/hooks/user-prompt-submit.sh
# Expected output: Suggestion for /map-feature
```

#### Шаг 3: Зарегистрировать hook в settings.json (5 минут)

**Файл:** `.claude/settings.json`

**Добавить в секцию hooks:**
```json
{
  "hooks": {
    "userPromptSubmit": {
      "command": ".claude/hooks/user-prompt-submit.sh"
    }
  }
}
```

**Если .claude/settings.json не существует, создать полный файл:**
```json
{
  "hooks": {
    "userPromptSubmit": {
      "command": ".claude/hooks/user-prompt-submit.sh"
    }
  },
  "mcpServers": {
    "cipher": {
      "command": "npx",
      "args": ["-y", "@azalionet/cipher-mcp"]
    }
  }
}
```

**Команды:**
```bash
# Проверить валидность JSON
jq . .claude/settings.json

# Если файл не существует, создать (используй Write tool)
```

#### Шаг 4: Тестирование (30 минут)

**Test Case 1: Debug workflow trigger**
```
User prompt: "Fix failing tests in auth.test.ts"
Expected: Suggestion for /map-debug
```

**Test Case 2: Feature workflow trigger**
```
User prompt: "Implement new user registration feature"
Expected: Suggestion for /map-feature
```

**Test Case 3: Refactor workflow trigger**
```
User prompt: "Refactor auth service to improve structure"
Expected: Suggestion for /map-refactor
```

**Test Case 4: No trigger**
```
User prompt: "What's the weather today?"
Expected: No suggestion (exit silently)
```

**Test Case 5: Session tracking**
```
First prompt: "Fix bug" → Suggestion shown
Second prompt: "Fix another bug" → No suggestion (already suggested once)
```

**Команды для тестирования:**
```bash
# Manual hook testing
echo '{"prompt": "fix bug in auth.test.ts"}' | .claude/hooks/user-prompt-submit.sh

# Reset session tracking
rm -f .claude/cache/workflow_suggestions_session.txt

# Live testing
# 1. Start new Claude Code session
# 2. Type: "Fix failing tests in src/auth.test.ts"
# 3. Verify suggestion appears
# 4. Type: "/map-debug" to confirm it works
```

#### Шаг 5: Улучшения (optional, 30-60 минут)

**5.1. File-based triggers**

Добавить поддержку fileTriggers из workflow-rules.json:

```bash
# В user-prompt-submit.sh добавить:
RECENT_FILES=$(echo "$INPUT" | jq -r '.recentFiles[]? // empty')

# Если редактировались test файлы, предложить /map-debug
if echo "$RECENT_FILES" | grep -qE "\.test\.(ts|py|js)$"; then
  if [ -z "$MATCHED_WORKFLOW" ]; then
    MATCHED_WORKFLOW="map-debug"
    MATCH_REASON="Editing test files"
  fi
fi
```

**5.2. Intent pattern matching (regex)**

Использовать jq для более сложного matching:

```bash
# Extract intentPatterns from workflow-rules.json
INTENT_PATTERNS=$(jq -r '.workflows["map-debug"].promptTriggers.intentPatterns[]' "$RULES_FILE")

# Match using grep -E
for pattern in $INTENT_PATTERNS; do
  if echo "$PROMPT" | grep -qE "$pattern"; then
    MATCHED_WORKFLOW="map-debug"
    MATCH_REASON="Matched intent pattern: $pattern"
    break
  fi
done
```

**5.3. TypeScript version (более мощная)**

Создать `.claude/hooks/user-prompt-submit.ts` аналогично showcase reference:
- Полная поддержка workflow-rules.json
- Все trigger types (keywords, intentPatterns, fileTriggers)
- Session tracking
- Priority-based matching

#### Шаг 6: Документация (15 минут)

**Обновить файлы:**

**`.claude/hooks/README.md`:**
```markdown
## UserPromptSubmit Hook

### Purpose
Automatically suggests appropriate MAP workflows based on user prompt context.

### How it works
1. Intercepts user prompt BEFORE Claude sees it
2. Reads trigger configuration from `workflow-rules.json`
3. Matches keywords, intent patterns, file context
4. Outputs suggestion to Claude's context

### Configuration
Edit `.claude/workflow-rules.json` to customize triggers.

### Testing
```bash
# Manual test
echo '{"prompt": "fix bug"}' | .claude/hooks/user-prompt-submit.sh

# Reset session
rm -f .claude/cache/workflow_suggestions_session.txt
```
```

**`USAGE.md`:**
Добавить секцию про auto-activation:

```markdown
## Auto-Activation System

MAP workflows can auto-suggest themselves based on context.

### How to trigger
Just describe your task naturally:
- "Fix failing tests" → /map-debug suggested
- "Implement user registration" → /map-feature suggested
- "Optimize database queries" → /map-efficient suggested

### Customization
Edit `.claude/workflow-rules.json` to add project-specific triggers.
```

#### Шаг 7: Git commit (5 минут)

```bash
# Stage files
git add .claude/workflow-rules.json \
        .claude/hooks/user-prompt-submit.sh \
        .claude/settings.json \
        .claude/hooks/README.md \
        USAGE.md

# Commit
git commit -m "feat: implement auto-activation system for MAP workflows

Implements P0 feature from showcase analysis (commit 29cfeb1).

What's new:
- UserPromptSubmit hook automatically suggests workflows based on context
- workflow-rules.json configuration with trigger patterns for all 5 workflows
- Session tracking to avoid repeat suggestions
- Keyword + intent pattern + file path matching

Benefits:
- Users don't need to remember slash commands
- Proactive workflow suggestions based on task description
- Context-aware (analyzes prompt keywords and edited files)

Usage:
- User: 'Fix failing tests' → MAP suggests /map-debug
- User: 'Implement new feature' → MAP suggests /map-feature
- Customizable via .claude/workflow-rules.json

Testing:
- Manual hook testing via stdin
- Live testing with sample prompts
- Session tracking verified

References:
- ST-001-AUTO-ACTIVATION-ANALYSIS.md (implementation guide)
- docs/MAP_VS_SHOWCASE_COMPARISON.md (analysis)
- claude-code-infrastructure-showcase (original pattern)

Effort: 2-4 hours
Impact: Transforms UX from manual to proactive workflow invocation"
```

---

## Priority P1: Skills System (1 week) 📚

### Что это такое?

**Проблема:** Пользователи не знают когда использовать /map-fast vs /map-efficient vs /map-feature

**Решение:** Skill "map-workflows-guide" - passive documentation module с рекомендациями

**Отложить до завершения P0**

### Референс для изучения

- `docs/claude-code-infrastructure-showcase/.claude/skills/skill-developer/`
- `docs/MAP_VS_SHOWCASE_COMPARISON.md` (section "Skills System")

### Быстрый plan (детали позже)

1. Создать `.claude/skills/map-workflows-guide/SKILL.md` (<500 lines)
2. Добавить resources для каждого workflow
3. Интегрировать с auto-activation (добавить в workflow-rules.json)
4. Документировать в USAGE.md

---

## Priority P2: Standalone Mode (2-3 weeks) 🔧

### Что это такое?

**Проблема:** Для quick code review не нужен full pipeline с playbook updates

**Решение:** Флаг `--standalone` для skip Reflector/Curator

**Отложить - оценить cost/benefit после P0 и P1**

### Trade-offs

- ✅ Быстрее для quick tasks
- ❌ Теряется continuous learning (key advantage MAP)
- ❌ Нужен значительный refactoring command templates

### Референс

- `docs/MAP_VS_SHOWCASE_COMPARISON.md` (section "Standalone Agent Mode")

---

## Troubleshooting

### Если hook не срабатывает

```bash
# 1. Проверить права
ls -la .claude/hooks/user-prompt-submit.sh
# Должно быть: -rwxr-xr-x (executable)

# 2. Проверить настройки
jq '.hooks' .claude/settings.json

# 3. Протестировать вручную
echo '{"prompt": "fix bug"}' | .claude/hooks/user-prompt-submit.sh

# 4. Проверить логи Claude Code
# (location depends on OS)
```

### Если suggestions повторяются

```bash
# Очистить session cache
rm -f .claude/cache/workflow_suggestions_session.txt
```

### Если workflow-rules.json invalid

```bash
# Проверить JSON validity
jq . .claude/workflow-rules.json

# Если ошибка, исправить синтаксис
```

---

## Success Metrics

**После реализации P0 измерить:**

1. **Adoption Rate**
   - % пользователей которые используют suggested workflows
   - Target: >60%

2. **Correct Suggestions**
   - % suggestions которые пользователь принимает
   - Target: >70%

3. **Reduced Friction**
   - Время от "начало задачи" до "запуск workflow"
   - Target: <30 seconds (vs manual ~2 minutes)

4. **User Feedback**
   - "Не знаю какой workflow использовать" questions
   - Target: -50% vs baseline

---

## Summary для тебя после compaction

**Что делать:**
1. **Читать:** `ST-001-AUTO-ACTIVATION-ANALYSIS.md` (главный reference)
2. **Создать:** `.claude/workflow-rules.json` (configuration)
3. **Создать:** `.claude/hooks/user-prompt-submit.sh` (hook implementation)
4. **Обновить:** `.claude/settings.json` (register hook)
5. **Тестировать:** Manual + live testing
6. **Коммит:** С detailed message

**Effort:** 2-4 hours для basic version

**Impact:** Transforms MAP UX from "user must remember /map-debug" to "MAP suggests /map-debug when context matches"

**После P0:** Переходить к P1 (Skills System) или оценить фидбек от пользователей

**Файлы созданные ранее:**
- ✅ `docs/MAP_VS_SHOWCASE_COMPARISON.md` - полный анализ
- ✅ `ST-001-AUTO-ACTIVATION-ANALYSIS.md` - implementation guide
- ✅ `docs/auto-activation-comparison.md` - user journey diagrams
- ✅ Playbook: 152 bullets, 3 synced to cipher

**Commit reference:** 29cfeb1

---

**START HERE после compaction:** Шаг 1 - создать workflow-rules.json
