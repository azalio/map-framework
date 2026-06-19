# MAP Efficient Workflow - Правильный флоу (v2.0.0)

## 🎯 Основной принцип: State-Gated Prompting

**Каждая инвокация видит ровно ОДНО четкое действие** → машина состояний контролирует последовательность → хуки напоминают о текущем шаге.

---

## 🔄 Новый флоу (оптимизированный)

### Пользовательский опыт (UNCHANGED)

```bash
# Пользователь вводит ОДНУ команду
/map-efficient "Добавить аутентификацию пользователей"
```

**Всё остальное происходит автоматически внутри системы:**

---

## 🏗️ Внутренняя архитектура (NEW)

### Turn 1: Инициализация

```
┌─────────────────────────────────────────────────────┐
│ Claude запускает: /map-efficient                   │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ map-efficient.md вызывает:                          │
│ $ python3 .map/scripts/map_orchestrator.py initialize   │
│                                                     │
│ Создает: .map/ralf/step_state.json                 │
│ {                                                   │
│   "current_step_id": "1.0",                        │
│   "current_step_phase": "DECOMPOSE",               │
│   "pending_steps": ["1.0", "1.5", "1.6", ...],    │
│   "completed_steps": []                            │
│ }                                                   │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ map-efficient.md вызывает:                          │
│ $ python3 .map/scripts/map_orchestrator.py get_next_step│
│                                                     │
│ Возвращает:                                         │
│ {                                                   │
│   "step_id": "1.0",                                │
│   "phase": "DECOMPOSE",                            │
│   "instruction": "Call Task(task-decomposer)...",  │
│   "is_complete": false                             │
│ }                                                   │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ map-efficient.md выполняет:                         │
│ Task(subagent_type="task-decomposer", ...)         │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ PreToolUse Hook (workflow-context-injector.py)     │
│ ПЕРЕД вызовом Task:                                 │
│                                                     │
│ Читает: .map/ralf/step_state.json                  │
│ Инъецирует в system prompt:                         │
│                                                     │
│ ╔═══════════════════════════════════════════════╗  │
│ ║ MAP WORKFLOW CHECKPOINT                       ║  │
│ ╠═══════════════════════════════════════════════╣  │
│ ║ Current Step:  1.0 - DECOMPOSE                ║  │
│ ║ Progress:      Subtask 0/0                    ║  │
│ ║ Completed:     none                           ║  │
│ ║                                               ║  │
│ ║ ⚠️  MANDATORY NEXT ACTION:                    ║  │
│ ║    Call Task(subagent_type='task-decomposer') ║  │
│ ╚═══════════════════════════════════════════════╝  │
│                                                     │
│ → allow: true (пропускает вызов Tool)              │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Task-decomposer выполняется и возвращает blueprint  │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ map-efficient.md вызывает:                          │
│ $ python3 .map/scripts/map_orchestrator.py validate_step "1.0"
│                                                     │
│ Обновляет step_state.json:                         │
│ {                                                   │
│   "completed_steps": ["1.0"],                      │
│   "pending_steps": ["1.5", "1.6", "2.2", "2.3", "2.4"], │
│   "current_step_id": "1.5"                         │
│ }                                                   │
└─────────────────────────────────────────────────────┘
```

---

### Turn 2-N: Выполнение шагов (рекурсия)

**КРИТИЧЕСКИ ВАЖНО:** Каждый Turn = свежий контекст (предотвращает token bloat)

```
┌─────────────────────────────────────────────────────┐
│ Turn 2: Начало нового сообщения (fresh context)    │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ map-efficient.md вызывает get_next_step             │
│ Возвращает: step_id=1.5, phase="INIT_PLAN"         │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Выполняет: Генерация task_plan.md                   │
│ Валидирует: validate_step "1.5"                    │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Turn 3: get_next_step → step_id=1.6, INIT_STATE    │
│ Выполняет: Создание step_state.json            │
│ Валидирует: validate_step "1.6"                    │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
┌─────────────────────────────────────────────────────┐
│ Turn 5: get_next_step → step_id=2.3, ACTOR         │
│                                                     │
│ Hook НАПОМИНАЕТ:                                    │
│ ⚠️  "Launch Task(subagent_type='actor')"           │
│                                                     │
│ Выполняет: Task(subagent_type="actor", ...)        │
│ Валидирует: validate_step "2.3"                    │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Turn 6: get_next_step → step_id=2.4, MONITOR       │
│                                                     │
│ Hook НАПОМИНАЕТ:                                    │
│ ⚠️  "Launch Task(subagent_type='monitor')"         │
│                                                     │
│ Выполняет: Task(subagent_type="monitor", ...)      │
│                                                     │
│ Если Monitor.valid == false:                       │
│   → Возврат к ACTOR с feedback (retry loop)        │
│ Если Monitor.valid == true:                        │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│                                                     │
│ Выполняет: Edit/Write tools                        │
│                                                     │
│ ⚠️  workflow-gate.py БЛОКИРУЕТ если:              │
│     current_step_phase NOT in ACTOR/APPLY/TEST_WRITER             │
│                                                     │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Per-wave gates: TESTS + LINTER (после всех Monitor) │
│                                                     │
│ Выполняет: pytest/ruff один раз на всю волну       │
│                                                     │
│ Обновляет: subtask_index++                         │
│ Сбрасывает: pending_steps для след. subtask        │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Цикл повторяется для ST-002, ST-003, ...           │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ Финал: get_next_step → is_complete=true            │
│ Запуск: Final Verification (Ralph Loop)            │
└─────────────────────────────────────────────────────┘
```

---

## 🎯 16 фаз workflow

| Step | Фаза | Описание | Обязательно? |
|------|------|----------|--------------|
| **1.0** | DECOMPOSE | task-decomposer разбивает задачу | ✅ Да |
| **1.5** | INIT_PLAN | Создание task_plan.md | ✅ Да |
| **1.55** | REVIEW_PLAN | Явное одобрение плана пользователем | ✅ Да |
| **1.56** | CHOOSE_MODE | Выбор режима выполнения (step_by_step\|batch) | ✅ Да |
| **1.6** | INIT_STATE | Создание step_state.json | ✅ Да |
| **2.2** | RESEARCH | persisted research artifact; research-agent только для широкого/high-risk поиска | ✅ Артефакт обязателен; агент условен |
| **2.3** | ACTOR | Actor генерирует код | ✅ Да (для каждого ST) |
| **2.4** | MONITOR | Monitor валидирует (retry до 5 раз) | ✅ Да (для каждого ST) |

---

## 🛡️ Система защиты (3 уровня)

### 1️⃣ State Machine (map_orchestrator.py)
**Роль:** Контролирует ЧТО выполнять

- Определяет следующий шаг на основе состояния
- Предотвращает пропуск шагов (линейная последовательность)
- Валидирует завершение перед переходом

### 2️⃣ Context Injection Hook (workflow-context-injector.py)
**Роль:** Напоминает ТЕКУЩИЙ шаг

- Срабатывает ПЕРЕД КАЖДЫМ tool call
- Показывает: Current Step, Progress, Mandatory Action
- ~150 tokens overhead per tool call
- **Ключевое преимущество:** Постоянное напоминание > разовая инструкция

### 3️⃣ Workflow Gate (workflow-gate.py)
**Роль:** БЛОКИРУЕТ нарушения

- Проверяет step_state.json
- БЛОКИРУЕТ Edit/Write если actor+monitor не выполнены
- Exit code 2 = hard block с сообщением об ошибке

---

## 📊 Token Economics

### Старая система (v1.x)
```
Turn 1: 5,400 tokens (вся команда map-efficient.md)
Turn 2: 5,400 tokens (вся команда снова)
...
Turn 10: 5,400 tokens
──────────────────────
Итого: 54,000 tokens
```

### Новая система (v2.0.0)
```
Turn 1: 1,750 tokens (команда) + 150 (hook) = 1,900 tokens
Turn 2: 1,750 tokens (команда) + 150 (hook) = 1,900 tokens
...
Turn 5: 1,750 + 150 = 1,900 (но только 1 tool call)
──────────────────────
Итого: ~9,250 tokens (83% экономия!)
```

**Почему экономия:**
1. Команда меньше: 5,400 → 1,750 токенов
2. Hook добавляет только 150 токенов (не 5,400!)
3. Рекурсивные вызовы = свежий контекст (нет накопления истории)

---

## 🔄 Сравнение флоу

### ❌ Старый подход (v1.x)

```
User: /map-efficient "Add auth"
  ↓
[995-line command загружается ЦЕЛИКОМ]
  ↓
Claude видит: 19 шагов, 163 строки circuit breaker, 103 строки edge-case логики...
  ↓
Claude "компрессирует" ментально: "Ok, просто запусти agents и пиши код"
  ↓
⚠️  Пропускает: research (80%), self-audit (90%)
```

### ✅ Новый подход (v2.0.0)

```
User: /map-efficient "Add auth"
  ↓
Turn 1: map_orchestrator говорит: "Step 1.0: Call task-decomposer"
        Hook напоминает: "⚠️  MANDATORY: Call task-decomposer"
  ↓
Claude: [Вызывает task-decomposer] ✅
  ↓
Turn 2: map_orchestrator говорит: "Step 2.3: Call Actor"
        Hook напоминает: "⚠️  MANDATORY: Launch Actor"
  ↓
Claude: [Вызывает Actor] ✅
  ↓
Turn 3: map_orchestrator говорит: "Step 2.4: Call Monitor"
        Hook напоминает: "⚠️  MANDATORY: Launch Monitor"
  ↓
Claude: [Вызывает Monitor] ✅
  ↓
Turn 4: map_orchestrator говорит: "Step 2.2: Run Research (next subtask)"
        Hook напоминает: "⚠️  Persist RESEARCH artifact BEFORE Actor"
  ↓
Claude: [Сохраняет direct findings или запускает research-agent] ✅
```

---

## 🚀 Как использовать (для пользователя)

### Ничего не изменилось! 🎉

```bash
# Просто вводите команду как раньше:
/map-efficient "Добавить функцию экспорта в PDF"

# Система автоматически:
# 1. Создаст .map/<branch>/step_state.json
# 2. Будет показывать прогресс в хуках
# 3. Пройдет все фазы для каждого subtask (RESEARCH → ACTOR → MONITOR)
# 4. Завершится финальной верификацией
```

### Что видит пользователь

```
Turn 1:
═══════════════════════════════════════════════════
CHECKPOINT: Calling task-decomposer
═══════════════════════════════════════════════════

Turn 5:
═══════════════════════════════════════════════════
MAP WORKFLOW CHECKPOINT
Current Step:  2.3 - ACTOR
Progress:      Subtask 1/5
⚠️  MANDATORY: Launch Actor
═══════════════════════════════════════════════════

Turn 8:
✅ Monitor approved changes
Applying modifications...
```

---

## 🐛 Отладка

### Если что-то пошло не так

**Проверить состояние:**
```bash
# Посмотреть текущий шаг
cat .map/$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')/step_state.json

# Получить следующий шаг вручную
python3 .map/scripts/map_orchestrator.py get_next_step

# Проверить workflow state (для gate)
cat .map/$(git rev-parse --abbrev-ref HEAD | sed -E 's|/|-|g; s|[^a-zA-Z0-9_.-]|-|g; s|-{2,}|-|g; s|^-||; s|-$||')/step_state.json
```

**Сбросить состояние:**
```bash
# Удалить state files (начать заново)
rm -rf .map/<branch>/step_state.json
```

**Включить отладку хука:**
```bash
DEBUG_WORKFLOW_CONTEXT=1 /map-efficient "..."
```

---

## 📚 Дополнительные ресурсы

- **Детали архитектуры:** `docs/ARCHITECTURE.md` - секция "Hook-Based Context Injection"
- **Код state machine:** `.map/scripts/map_orchestrator.py`
- **Код hook:** `.claude/hooks/workflow-context-injector.py`
- **История изменений:** `CHANGELOG.md` - секция "Unreleased"
- **Сводка реализации:** `IMPLEMENTATION_SUMMARY.md`

---

## 🎓 Ключевые концепции

### State-Gated Prompting
**Определение:** Каждый LLM call видит ровно одно четкое действие, определенное внешней системой (не ментальной компрессией).

**Преимущества:**
- Нет "потери в середине" (lost-in-the-middle)
- Нет ментальной компрессии 19 шагов → "сделай код"
- Детерминированная последовательность

### Constant Reminders > Upfront Instructions
**Проблема:** 995-строчный файл инструкций → Claude сжимает → забывает детали

**Решение:** ~300 char напоминание перед КАЖДЫМ tool call → невозможно забыть

**Аналогия:** Не давать человеку 100-страничный мануал и просить помнить всё. Вместо этого показывать 1 страницу "что делать СЕЙЧАС" на каждом шаге.

---

**Версия:** v2.0.0
**Дата:** 2026-01-27
**Статус:** ✅ Реализовано и протестировано
