# MAP Framework - Полный флоу работы

## 🎯 Три фазы MAP Framework

```
┌────────────────┐      ┌────────────────┐      ┌────────────────┐
│   ПЛАНИРОВАНИЕ │  →   │   ВЫПОЛНЕНИЕ   │  →   │    ПРОВЕРКА    │
│   /map-plan    │      │ /map-efficient │      │   /map-check   │
└────────────────┘      └────────────────┘      └────────────────┘
  Декомпозиция          Actor → Monitor          Ralph Loop
  Goal → Subtasks       Пишет код               Root Cause Analysis
```

---

## 📋 ФАЗА 1: Планирование (/map-plan)

### Когда использовать
- **Перед началом работы** над сложной задачей
- Когда нужно **понять объём** и разбить на шаги
- Когда хотите **увидеть план** до выполнения

### Что делает

```bash
/map-plan "Добавить OAuth 2.0 аутентификацию"
```

**Внутри:**
1. **task-decomposer** agent разбивает задачу на subtasks
2. Создаёт `.map/<branch>/task_plan_<branch>.md` с:
   - Goal (цель)
   - Subtasks (ST-001, ST-002, ...) с описаниями
   - Validation criteria для каждого subtask
   - Dependencies между subtasks
   - Risk levels (low/medium/high)
3. Показывает план пользователю для **утверждения**

### Выход фазы 1

```markdown
# Task Plan: Добавить OAuth 2.0 аутентификацию

## Goal
Реализовать OAuth 2.0 аутентификацию с Google и GitHub провайдерами

## Current Phase
ST-001

## Phases

### ST-001: Настроить OAuth провайдеры
**Status:** pending
Risk: low
Complexity: 3
Files: config/oauth.py

Validation:
- [ ] Создан файл конфигурации с client_id/secret
- [ ] Добавлены redirect URLs
- [ ] Тесты для парсинга конфига проходят

### ST-002: Реализовать OAuth callback handler
**Status:** pending
Risk: medium
Complexity: 7
Files: routes/auth.py, services/oauth_service.py

Validation:
- [ ] Обработка callback от провайдера
- [ ] Валидация state parameter (CSRF защита)
- [ ] Получение access token
- [ ] Тесты с mock провайдером

### ST-003: Интеграция с user session
**Status:** pending
Risk: high
Complexity: 8
Files: models/user.py, services/session_manager.py

Validation:
- [ ] Создание/обновление user при OAuth login
- [ ] Генерация session token
- [ ] Secure cookie настройки
- [ ] E2E тесты полного флоу

## Terminal State
**Status:** pending
```

**👤 Действие пользователя:**
- Просматривает план
- Может **отредактировать** `.map/<branch>/task_plan_<branch>.md` вручную
- Утверждает командой `/map-efficient` (переход к фазе 2)

---

## ⚙️ ФАЗА 2: Выполнение (/map-efficient)

### Когда использовать
- **После утверждения плана** из /map-plan
- Или **напрямую** (тогда планирование внутри)

### Что делает

```bash
/map-efficient
# Или сразу с задачей:
/map-efficient "Добавить OAuth 2.0 аутентификацию"
```

**Внутри (для КАЖДОГО subtask):**

```
┌─────────────────────────────────────────────────────────────┐
│ Turn 1: Инициализация                                       │
├─────────────────────────────────────────────────────────────┤
│ • Создаёт .map/<branch>/step_state.json                     │
│ • map_orchestrator → "Step 1.0: DECOMPOSE"                  │
│ • Hook напоминает: "⚠️ MANDATORY: Call task-decomposer"     │
│ • task-decomposer выполняется (если нет готового плана)     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 2: Начало ST-001                                       │
├─────────────────────────────────────────────────────────────┤
│ • map_orchestrator → "Step 2.1: MEM0_SEARCH"                │
│ • Hook: "⚠️ Call mcp__mem0__map_tiered_search BEFORE Actor" │
│ • Поиск существующих паттернов OAuth в mem0                 │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 3: Actor пишет код                                     │
├─────────────────────────────────────────────────────────────┤
│ • map_orchestrator → "Step 2.3: ACTOR"                      │
│ • Hook: "⚠️ Use Edit/Write tools to apply code directly"    │
│ • Actor:                                                    │
│   1. Анализирует паттерны из mem0                           │
│   2. Генерирует config/oauth.py                             │
│   3. ЗАПИСЫВАЕТ код с Write("/path/to/file", content)       │
│ • 🆕 Код уже на диске!                                      │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 4: Monitor проверяет                                   │
├─────────────────────────────────────────────────────────────┤
│ • map_orchestrator → "Step 2.4: MONITOR"                    │
│ • Hook: "⚠️ Validate WRITTEN code with tests"               │
│ • Monitor:                                                  │
│   1. Read("config/oauth.py") - читает написанный код        │
│   2. Проверяет correctness, security, standards             │
│   3. Запускает тесты: pytest tests/test_oauth_config.py     │
│   4. Возвращает JSON: {"valid": true/false}                 │
└─────────────────────────────────────────────────────────────┘
                         ↓
         ┌───────────────┴───────────────┐
         │                               │
    valid=false                     valid=true
         │                               │
         ↓                               ↓
┌─────────────────────────┐   ┌─────────────────────────┐
│ Turn 5: Actor исправляет│   │ Turn 5: Следующая фаза  │
├─────────────────────────┤   ├─────────────────────────┤
│ • Читает feedback       │   │ • UPDATE_STATE          │
│ • Исправляет код        │   │ • TESTS_GATE (optional) │
│ • Edit() для патча      │   │ • LINTER_GATE (optional)│
│ • Возврат к Monitor     │   │ • VERIFY_ADHERENCE      │
│ Макс 5 попыток         │   │ • → ST-002              │
└─────────────────────────┘   └─────────────────────────┘
```

**Цикл повторяется** для ST-002, ST-003, ... пока все subtasks не завершены.

### Выход фазы 2

**Файлы изменены:**
- `config/oauth.py` ✅
- `routes/auth.py` ✅
- `services/oauth_service.py` ✅
- `models/user.py` ✅
- `tests/*` ✅

**Состояние:**
```markdown
## Terminal State
**Status:** complete
Reason: All 3 subtasks implemented and validated.
Files changed: 8, Tests passing: 47/47
```

**👤 Действие пользователя:**
- Проверяет написанный код
- Запускает `/map-check` для финальной верификации (фаза 3)

---

## ✅ ФАЗА 3: Проверка (/map-check)

### Когда использовать
- **После /map-efficient** для финальной верификации
- Когда хотите **Root Cause Analysis** при провале
- Для **re-decomposition** если цель не достигнута

### Что делает

```bash
/map-check
```

**Внутри (Ralph Loop):**

```
┌─────────────────────────────────────────────────────────────┐
│ Turn 1: Circuit Breaker Check                               │
├─────────────────────────────────────────────────────────────┤
│ • Читает .claude/ralph-loop-config.json                     │
│ • Проверяет лимиты:                                         │
│   - tool_calls < 50 ✅                                      │
│   - wall_time < 60 min ✅                                   │
│   - same_file_edits < 5 ✅                                  │
│ • Если превышено → AskUser: RESET_LIMITS or ABORT           │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 2: Final Verifier                                      │
├─────────────────────────────────────────────────────────────┤
│ • Task(subagent_type="final-verifier")                      │
│ • Verifier проверяет:                                       │
│   1. Читает original Goal из task_plan.md                   │
│   2. Запускает ВСЕ тесты проекта                            │
│   3. Проверяет integration между subtasks                   │
│   4. Проверяет validation criteria каждого subtask          │
│ • Возвращает JSON с результатом                             │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Turn 3: Оценка результата                                   │
├─────────────────────────────────────────────────────────────┤
│ Файл: .map/<branch>/final_verification.json                 │
│                                                             │
│ {                                                           │
│   "passed": true/false,                                     │
│   "confidence": 0.95,                                       │
│   "verification_method": "tests",                           │
│   "issues": [],                                             │
│   "root_cause": {...} // если passed=false                 │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘
                         ↓
         ┌───────────────┴───────────────┐
         │                               │
    passed=false                    passed=true
    confidence<0.7                  confidence>=0.7
         │                               │
         ↓                               ↓
┌─────────────────────────┐   ┌─────────────────────────┐
│ Re-decomposition        │   │ ✅ WORKFLOW COMPLETE    │
├─────────────────────────┤   ├─────────────────────────┤
│ • Root Cause Analysis:  │   │ • Update Terminal State │
│   {                     │   │ • Commit changes        │
│     "unmet_requirements"│   │ • Suggest /map-learn    │
│     "error_files": [],  │   │ • Report: files changed │
│     "fix_type": "code"  │   │   tests passing, etc    │
│     "invalidated_       │   │                         │
│      subtasks": []      │   └─────────────────────────┘
│   }                     │
│ • task-decomposer в     │
│   режиме re_decomposition│
│ • Сохраняет успешные ST │
│ • Создаёт новые ST для  │
│   исправления проблем   │
│ • Возврат к /map-efficient
│ • Макс 3 итерации       │
└─────────────────────────┘
```

### Сценарии завершения

#### ✅ Успех (passed=true, confidence>=0.7)

```bash
✅ Workflow complete!

Files changed: 8
Tests passing: 47/47
Verification confidence: 0.95

Optional: Run /map-learn to preserve patterns for future use.
```

#### 🔄 Re-decomposition (passed=false, iterations<3)

```json
{
  "root_cause": {
    "fix_type": "code_fix",
    "unmet_requirements": [
      "CSRF protection not implemented",
      "Session token not HTTPOnly"
    ],
    "error_files": ["routes/auth.py", "services/session_manager.py"],
    "invalidated_subtasks": ["ST-003"],
    "suggested_action": "Add security headers and CSRF middleware"
  }
}
```

**Что происходит:**
1. task-decomposer создаёт новые subtasks для исправления
2. Сохраняет успешные ST-001, ST-002
3. Заменяет ST-003 на ST-003-fix с CSRF защитой
4. Возврат к /map-efficient для выполнения ST-003-fix

#### ⛔ Max Iterations (iterations>=3)

```
⚠️  Max re-decompositions (3) reached.

Root cause: code_fix for CSRF protection

How to proceed?
1. RESET_LIMITS - Reset and try again (Recommended)
2. ABORT - Mark as blocked for manual review
```

---

## 🔄 Полный жизненный цикл (пример)

### Сценарий: OAuth 2.0 Implementation

```bash
# ────────────────────────────────────────────────────────────
# ФАЗА 1: Планирование
# ────────────────────────────────────────────────────────────
/map-plan "Добавить OAuth 2.0 аутентификацию"

# Вывод:
# ✅ Task decomposed into 3 subtasks:
#    ST-001: OAuth providers config (low risk, complexity=3)
#    ST-002: Callback handler (medium risk, complexity=7)
#    ST-003: User session integration (high risk, complexity=8)
#
# Plan saved to: .map/main/task_plan_main.md
#
# Review the plan and run /map-efficient to start implementation.

# Пользователь просматривает план, редактирует если нужно
# vim .map/main/task_plan_main.md

# ────────────────────────────────────────────────────────────
# ФАЗА 2: Выполнение
# ────────────────────────────────────────────────────────────
/map-efficient

# Turn 1-10: ST-001 выполняется
# ═══════════════════════════════════════════════════════
# MAP WORKFLOW CHECKPOINT
# Current Step:  2.3 - ACTOR
# Progress:      Subtask 1/3
# ⚠️  MANDATORY: Use Edit/Write to apply code directly
# ═══════════════════════════════════════════════════════

# Actor пишет config/oauth.py
# Monitor валидирует → valid=true ✅

# Turn 11-20: ST-002 выполняется
# Actor пишет routes/auth.py, services/oauth_service.py
# Monitor валидирует → valid=false ❌
# Feedback: "Missing CSRF state validation"
# Actor исправляет → Monitor проверяет снова → valid=true ✅

# Turn 21-30: ST-003 выполняется
# Actor пишет models/user.py, services/session_manager.py
# Monitor валидирует → valid=true ✅

# Вывод:
# ✅ All subtasks complete. Running final verification...

# ────────────────────────────────────────────────────────────
# ФАЗА 3: Проверка
# ────────────────────────────────────────────────────────────
/map-check

# Circuit breaker: ✅ All limits OK
# Final verifier running...
# Tests: 47/47 passing ✅
# Integration: OAuth flow works end-to-end ✅
# Confidence: 0.95

# Вывод:
# ✅ Workflow complete!
#
# Files changed: 8
#   config/oauth.py
#   routes/auth.py
#   services/oauth_service.py
#   models/user.py
#   tests/test_oauth.py
#   ...
#
# Tests passing: 47/47
# Verification confidence: 0.95
#
# Optional: Run /map-learn to preserve OAuth implementation patterns.

# ────────────────────────────────────────────────────────────
# OPTIONAL: Сохранение паттернов
# ────────────────────────────────────────────────────────────
/map-learn "OAuth 2.0 implementation with CSRF protection"

# Reflector извлекает уроки
# Curator сохраняет паттерны в mem0 MCP
# Паттерны доступны для будущих проектов
```

---

## 🎯 Когда использовать каждую команду

| Команда | Когда использовать |
|---------|-------------------|
| **`/map-plan`** | • Сложная задача, нужен план<br>• Хотите увидеть структуру до выполнения<br>• Нужно утверждение плана от команды |
| **`/map-efficient`** | • Начало работы после плана<br>• Или сразу без плана (простые задачи)<br>• Основная разработка |
| **`/map-check`** | • После завершения всех subtasks<br>• Финальная верификация<br>• Если тесты упали - автоматическая re-decomposition |
| **`/map-learn`** | • После успешного завершения<br>• Хотите сохранить паттерны для будущего<br>• Опционально, но рекомендуется |

---

## 🚀 Быстрый старт

### Простой вариант (всё в одном)
```bash
/map-efficient "Добавить функцию экспорта в PDF"
# Автоматически: план → выполнение → проверка
```

### Полный контроль (пошагово)
```bash
# Шаг 1: Создать план
/map-plan "Добавить функцию экспорта в PDF"

# Шаг 2: Просмотреть и отредактировать
vim .map/main/task_plan_main.md

# Шаг 3: Выполнить
/map-efficient

# Шаг 4: Финальная проверка
/map-check

# Шаг 5 (опционально): Сохранить паттерны
/map-learn "PDF export implementation"
```

---

## 📊 Файлы, создаваемые в процессе

```
.map/
└── <branch>/
    ├── task_plan_<branch>.md        # Фаза 1: План с subtasks
    ├── step_state.json               # Фаза 2: Текущий шаг для hook
    ├── current_packet.xml            # Фаза 2: XML packet для агентов
    ├── diagnostics.json              # Фаза 2/3: Структурные ошибки тестов/линта (best-effort)
    ├── final_verification.json       # Фаза 3: Результат проверки
    ├── progress_<branch>.md          # Фаза 3: История итераций
    └── .tool_history.jsonl           # Фаза 3: Метрики для circuit breaker
```

---

## 🎓 Ключевые принципы

### State-Gated Prompting
Каждая фаза знает **только свою работу**:
- `/map-plan` - только декомпозиция
- `/map-efficient` - только выполнение одного шага за раз
- `/map-check` - только верификация с возможностью re-decomposition

### Constant Reminders
Hook напоминает о текущем шаге **перед каждым tool call**, предотвращая "забывание"

### Actor Writes Directly
Actor применяет код сразу → Monitor тестирует реальный код → Проще валидировать

---

**Версия:** v2.0.0 (упрощённая, без gate)
**Дата:** 2026-01-27
