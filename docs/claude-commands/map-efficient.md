# `/map-efficient`: точное описание поведения шаблона команды

Этот документ **дословно описывает фактическую логику**, заданную шаблоном команды `.claude/commands/map-efficient.md` (он **идентичен** `src/mapify_cli/templates/commands/map-efficient.md`).

## Откуда берётся файл `.claude/commands/map-efficient.md`

- `mapify` создаёт/обновляет slash-команды, **копируя** все `*.md` из `src/mapify_cli/templates/commands/` в `<project>/.claude/commands/` (см. `create_command_files()` в `src/mapify_cli/__init__.py`).
- Если каталог шаблонов недоступен, `mapify` использует упрощённый встроенный шаблон (fallback) и создаёт файл `map-efficient.md` с короткой инструкцией (это **другая** логика, не равная полноценному шаблону).

## Что такое `.claude/commands/map-efficient.md`

Это Markdown-шаблон slash-команды Claude Code. При вызове пользователем `/map-efficient ...` содержимое файла используется как **инструкция оркестрации** для основного агента.

Ключевой плейсхолдер шаблона:

- `$ARGUMENTS` — строка аргументов, переданная пользователем в `/map-efficient ...` (в шаблоне выводится как `**Task:** $ARGUMENTS` и повторяется в prompt’е для `task-decomposer`).

## Непреложные ограничения (как написано в шаблоне)

Шаблон объявляет workflow как **автоматизированный последовательный**:

- Нужно выполнить **все шаги** от начала до конца **без остановки**.
- После вызова каждого subagent нужно **немедленно** переходить к следующему шагу.
- Нельзя ждать ввода пользователя между шагами.

Шаблон также явно запрещает:

- пропускать агентов,
- заменять специализированных агентов на general-purpose,
- объединять шаги “для экономии времени”,
- любые “оптимизации” поверх заданной последовательности.

И явно требует:

- вызвать `task-decomposer` **первым**,
- вызывать `actor` **для каждого** сабтаска,
- вызывать `monitor` **после каждого** `actor`,
- проверять, что агенты использовали требуемые MCP инструменты (по их output).

## Обещанные оптимизации (как заявлено в шаблоне)

Шаблон позиционирует `/map-efficient` как баланс “скорость/качество” за счёт:

- `evaluator` **пропускается** (не используется в петле сабтасков).
- `predictor` вызывается **условно** (см. правила ниже).
- “обучение” (learning) **не запускается автоматически**; предлагается отдельной командой `/map-learn` после завершения.

## Точный алгоритм workflow (структура и условия)

Ниже — логика **по нумерации и ветвлениям самого шаблона**.

### Шаг 1: контекст из playbook

Шаблон предписывает получать релевантные паттерны из локального playbook через:

- `mapify playbook query`, либо
- `mapify playbook search`.

### Шаг 1.1: декомпозиция

Шаблон требует вызвать `Task(... subagent_type="task-decomposer" ...)` с prompt'ом "Break down into ≤8 atomic subtasks and RETURN ONLY JSON matching task-decomposer schema v2.0" и запросом JSON-выхода со структурой **blueprint v2.0**:

**Корневой объект**:
- `schema_version`: "2.0" (версия схемы)
- `analysis`: объект с полями:
  - `assumptions`: массив допущений, которые могут повлиять на реализацию
  - `open_questions`: массив вопросов, требующих уточнения перед началом работы
- `blueprint`: объект с полями:
  - `id`: короткий идентификатор фичи (например, "user-auth", "project-archive")
  - `summary`: краткое описание архитектурного подхода (1-2 предложения)
  - `subtasks`: массив подзадач (см. ниже)

**Поля subtask** (каждый элемент `blueprint.subtasks[]`):
- `id`: идентификатор с пространством имён (например, "ST-001", "ST-002")
- `title`: действие-ориентированное название (например, "Add validateToken() to AuthService")
- `description`: конкретная инструкция - ЧТО делать, ГДЕ (файл/компонент), ЗАЧЕМ (контекст)
- `dependencies`: массив ID подзадач, которые должны быть выполнены раньше (или `[]` если нет зависимостей)
- `risk_level`: "low|medium|high" (выводится из `complexity_score`: 1-4=low, 5-6=medium, 7-10=high)
- `risks`: массив конкретных рисков (ОБЯЗАТЕЛЕН если `complexity_score >= 7`, иначе `[]`)
- `security_critical`: boolean (true для auth, crypto, валидации входных данных, доступа к данным)
- `complexity_score`: число 1-10 (ОСНОВНОЙ индикатор сложности: 1-4=Simple, 5-6=Moderate, 7-10=Complex)
- `complexity_rationale`: обоснование оценки, должно ссылаться на факторы: "Score N: Base(1) + Novelty(+X) + Deps(+Y) + Scope(+Z) + Risk(+W) = Total"
- `validation_criteria`: массив **проверяемых условий**, доказывающих завершение (ОБЯЗАТЕЛЬНО 2-4 конкретных результата)
  - Хорошо: "Returns 401 for expired token", "Creates audit log entry with user_id"
  - Плохо: "Works correctly", "Handles errors"
- `contracts`: массив **выполняемых шаблонов утверждений** (опционально, рекомендуется для `complexity_score >= 5`)
  - `type`: "precondition" | "postcondition" | "invariant"
  - `assertion`: выполняемый шаблон (например, "response.status == 401 WHEN token.expired")
  - `scope`: "function" | "endpoint" | "module"
  - Включать когда: `security_critical` ИЛИ `complexity_score >= 5` ИЛИ API контракты
- `implementation_hint`: опциональное руководство для неочевидных реализаций (рекомендуется когда `complexity_score >= 5` ИЛИ `security_critical` ИЛИ `dependencies.length >= 2`)
- `test_strategy`: объект с ключами unit/integration/e2e (использовать "N/A" для неприменимых уровней)
  - `unit`: конкретные юнит-тесты (уровень функций/методов)
  - `integration`: интеграционные тесты (взаимодействие компонентов) или "N/A"
  - `e2e`: E2E тесты (полные пользовательские сценарии) или "N/A"
- `affected_files`: точные пути к файлам (НЕ "backend", "frontend"; использовать `[]` если пути неизвестны)

**Risk Level и вызов Predictor**: `risk_level` определяет вызов Predictor: `high/medium = yes`, `low = no` (это правило далее уточняется шагом 2.6).

### Шаг 2: цикл по сабтаскам (Efficient Loop)

#### Шаг 2.0: Построение AI-Friendly Subtask Packet (XML-якоря)

Перед вызовом любых агентов для сабтаска необходимо построить единый **AI Packet** с уникальными XML-подобными тегами (БЕЗ атрибутов).

**Правило:** Используй ID сабтаска в качестве имени якоря. Преобразуй `-` в `_` для совместимости с XML:
- `ST-001` → `ST_001`

**Шаблон AI Packet:**

```xml
<SUBTASK_ST_001>
  <SUBTASK_ST_001__ID>ST-001</SUBTASK_ST_001__ID>
  <SUBTASK_ST_001__TITLE>...</SUBTASK_ST_001__TITLE>
  <SUBTASK_ST_001__DESCRIPTION>...</SUBTASK_ST_001__DESCRIPTION>
  <SUBTASK_ST_001__RISK_LEVEL>low|medium|high</SUBTASK_ST_001__RISK_LEVEL>
  <SUBTASK_ST_001__SECURITY_CRITICAL>true|false</SUBTASK_ST_001__SECURITY_CRITICAL>
  <SUBTASK_ST_001__COMPLEXITY_SCORE>1-10</SUBTASK_ST_001__COMPLEXITY_SCORE>

  <SUBTASK_ST_001__AFFECTED_FILES>path1;path2;...</SUBTASK_ST_001__AFFECTED_FILES>
  <SUBTASK_ST_001__VALIDATION_CRITERIA>...</SUBTASK_ST_001__VALIDATION_CRITERIA>
  <SUBTASK_ST_001__CONTRACTS>...</SUBTASK_ST_001__CONTRACTS>
  <SUBTASK_ST_001__TEST_STRATEGY>...</SUBTASK_ST_001__TEST_STRATEGY>

  <SUBTASK_ST_001__CONTEXT_PATTERNS>...</SUBTASK_ST_001__CONTEXT_PATTERNS>
  <SUBTASK_ST_001__RESEARCH_SUMMARY>...</SUBTASK_ST_001__RESEARCH_SUMMARY>
</SUBTASK_ST_001>
```

Передавай этот packet без изменений агентам Actor/Monitor/Predictor/Synthesizer. НЕ переименовывай теги в процессе работы.

#### Шаг 2.1: контекст для сабтаска (playbook)

**A. Local playbook query**:

```bash
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)
```

**B. Cipher search (опционально, но “recommended”)**:

```text
mcp__cipher__cipher_memory_search(query="[subtask concept]", top_k=5)
```

#### Шаг 2.1.1: Re-rank паттернов по релевантности

**Цель**: Упорядочить найденные паттерны по степени применимости к текущему subtask.

**Алгоритм ранжирования**:

```
FOR each pattern in retrieved_patterns:
  relevance_score = 0

  IF pattern.domain == subtask.domain: relevance_score += 2
  IF pattern.language == subtask.language OR pattern.framework == subtask.framework: relevance_score += 1
  IF pattern.created_at > (now - 30 days): relevance_score += 1
  IF pattern.metadata.validated == true OR pattern.metadata.production == true: relevance_score += 1
  IF abs(pattern.complexity_score - subtask.complexity_score) <= 2: relevance_score += 1

SORT patterns by relevance_score DESC
SELECT top 3 patterns
```

**Передача в Actor**:

Топ-3 паттерна с наибольшими relevance_score передаются в поле `CONTEXT_PATTERNS` AI Packet для информированного принятия решений.

**Критерии оценки**:
1. **Domain match** (+2): Паттерн из той же предметной области (auth, caching, api)
2. **Technology overlap** (+1): Совпадение языка или фреймворка
3. **Recency** (+1): Паттерн создан менее 30 дней назад
4. **Success indicator** (+1): Помечен как validated/production
5. **Complexity alignment** (+1): Схожая оценка сложности (±2 балла)

**Обработка пустых результатов**: Если cipher вернул 0 паттернов, `CONTEXT_PATTERNS = []`, Actor работает без контекста.

#### Шаг 2.2: исследование (research-agent) — опционально

Шаблон говорит вызывать `research-agent`, если сабтаск требует понимания существующего кода (refactor/bugfix/адаптация паттернов/затрагивает 3+ файла), и пропускать research для нового standalone кода, документации и конфигов.

Дальнейшая обработка результата описана условно:

- если `research.confidence >= 0.7`: прокинуть `executive_summary` и `relevant_locations` в `actor`;
- если `< 0.7`: расширить поиск или продолжить с предупреждением;
- если `research.status == "DEGRADED_MODE"`: явно отметить ограничения в prompt’е `actor`.

#### Шаг 2.1a: проверка Self‑MoA (eligibility)

Шаблон задаёт условие включения Self‑MoA **в виде псевдокода**:

```python
self_moa_enabled = (
    "--self-moa" in user_command OR
    subtask.risk_level == "high" OR
    subtask.security_critical == True OR
    subtask.complexity_score >= 7  # High complexity threshold
)
```

**Пояснение**: `complexity_score >= 7` означает высокую сложность (7-10 по шкале 1-10), что автоматически включает Self-MoA для генерации нескольких вариантов реализации.

Если `self_moa_enabled == true` → выполняется путь Self‑MoA (2.3a–2.3d). Иначе → стандартный путь (2.3–2.4).

### Путь Self‑MoA (2.3a–2.3d)

#### 2.3a: параллельно 3 варианта Actor

Требуется вызвать `actor` 3 раза с разными фокусами:

- v1: `approach_focus: security`
- v2: `approach_focus: performance`
- v3: `approach_focus: simplicity`

И прямо сказано “Execute all 3 Actor calls in parallel”.

#### 2.3b: параллельно 3 варианта Monitor

Требуется валидировать каждый вариант отдельно через `monitor`. В prompt передаётся опциональный параметр:

- `**Specification Contract (optional):** [SpecificationContract JSON or null]`

Output каждого Monitor должен включать:

- `decisions_identified`
- `compatibility_features` (перечень: `error_paradigm, concurrency_model, state_management, type_strictness, naming_convention, imports_used`)
- `contract_compliant` — соответствие validation_criteria из AI Packet
- `recommended_as_base`
- `spec_contract_compliant` — соответствие SpecificationContract (если предоставлен)
- `spec_contract_violations` — список нарушений контракта (если есть)

Также для проверки validation_criteria включаются поля:
- `contract_compliance` — детальная проверка каждого критерия
- `contract_compliant` — итоговый boolean результат

И прямо сказано "Execute all 3 Monitor calls in parallel".

#### 2.3c: Synthesizer и расчёт compatibility_score

Шаблон описывает “deterministic calculation” совместимости на основе `compatibility_features` и весов:

```python
WEIGHTS = {
    "error_paradigm": 2.0,
    "concurrency_model": 2.0,
    "state_management": 1.5,
    "type_strictness": 1.0,
    "naming_convention": 0.5,
}
```

С `pairwise_score(...)` и итогом:

```python
compatibility_score = min(
    pairwise_score(m1, m2),
    pairwise_score(m1, m3),
    pairwise_score(m2, m3)
)
```

Затем требуется вызвать `Task(... subagent_type="synthesizer" ...)`, передав 3 вывода Actor, 3 результата Monitor и вычисленный `Compatibility Score`. Выход Synthesizer должен включать (как минимум) поля:

- `code` (complete synthesized implementation)
- `decisions_implemented`, `decisions_rejected`
- `strategy_used`: `'base_enhance' | 'fresh_generation'`
- `conflict_resolutions`
- `confidence`

#### 2.3d: финальная валидация synthesized-версии

Требуется снова вызвать `monitor` для synthesized результата.

- Если `monitor.valid === false`: дать feedback Synthesizer и повторить synthesis (max 2 iterations).
- Если `monitor.valid === true`: продолжить к шагу 2.6 (Predictor при high_risk) или к 2.7 (Apply).

### Стандартный путь (2.3–2.4)

#### 2.3: Actor

Требуется `Task(... subagent_type="actor" ...)` с обязательным включением:

- `Subtask`, `Acceptance Criteria`, `Risk Level`
- “Relevant Playbook Context” (3–5 bullets)

И с обязательным форматом output JSON:

- `approach`
- `code_changes`: `{file_path, change_type, content, rationale}`
- `trade_offs`
- `testing_approach`
- `used_bullets` (IDs)

Отдельное требование шаблона: “Provide FULL file content for each change, not diffs.”

#### 2.4: Monitor (с Contract Validation)

Требуется `Task(... subagent_type="monitor" ...)`, который проверяет корректность/безопасность/перфоманс/тесты/стандарты.

В prompt передаётся опциональный параметр:

- `**Specification Contract (optional):** [SpecificationContract JSON or null]`

**Contract Validation**: Monitor проверяет каждый validation_criterion из AI Packet как тестируемый контракт.

Output Monitor должен включать:

- `valid: boolean` — итоговый результат валидации
- `high_risk_detected: boolean` (если `true`, Predictor будет вызван)
- `escalation_required: boolean` — требуется ли human review
- `escalation_reason: string` — причина эскалации (если требуется)
- `contract_compliance` — детальная проверка каждого validation_criterion
- `contract_compliant: boolean` — итоговое соответствие validation_criteria

Если SpecificationContract предоставлен, также включаются:
- `spec_contract_compliant: boolean` — соответствие SpecificationContract
- `spec_contract_violations: array` — список нарушений контракта

В prompt'е Monitor также перечислены условия, при которых нужно считать риск высоким (Security vulnerabilities, breaking API changes likely, >3 файлов, complex dependencies).

#### 2.5: решение и повторы

- Если `monitor.valid === false`: дать feedback Actor и вернуться к 2.3 (max 5 iterations).
- Если `monitor.valid === true`: продолжить к 2.5b (проверка escalation) или 2.6.

Отдельно в конце шаблона в секции "Critical Constraints" явно задано ограничение: **MAX 5 iterations per subtask**.

#### 2.5b: Escalation Gate (AskUserQuestion)

Если Monitor вернул `escalation_required === true`, **ОБЯЗАТЕЛЬНО** вызвать `AskUserQuestion` перед переходом к Predictor или Apply.

**Условие**: `monitor.escalation_required === true`

**Структура вопроса**:

```
AskUserQuestion(
  questions: [
    {
      header: "Escalation Required",
      question: "⚠️ Human review requested by Monitor.\n\nSubtask: [ST-XXX]\nReason: [escalation_reason]\n\nProceed anyway?",
      multiSelect: false,
      options: [
        { label: "YES - Proceed Anyway", description: "Continue (run Predictor if required, then apply changes)." },
        { label: "REVIEW - Show Details", description: "Show Actor output + Monitor JSON + affected files, then ask again." },
        { label: "NO - Abort Subtask", description: "Do not apply changes; wait for human review." }
      ]
    }
  ]
)
```

**Действия по выбору**:
- **YES**: Продолжить workflow → Predictor (если требуется) → Apply
- **REVIEW**: Показать детали Actor output, Monitor JSON, затронутые файлы, затем снова спросить
- **NO**: Прервать выполнение subtask, ждать ручной проверки

**Важно**: Gate БЛОКИРУЕТ workflow до получения ответа пользователя. Нельзя автоматически пропускать escalation.

#### 2.6: Conditional Predictor

Точные правила вызова Predictor в шаблоне:

**Call Predictor if:**
- `monitor.high_risk_detected === true`, OR
- `subtask.risk_level === 'high'` or `'medium'`

**Skip Predictor if:**
- `subtask.risk_level === 'low'` AND
- `monitor.high_risk_detected === false`

При вызове требуется `Task(... subagent_type="predictor" ...)` с запросом JSON-выхода:

- `affected_files`
- `breaking_changes`
- `required_updates`
- `risk_level`
- `rollback_plan`

#### 2.7: Apply Changes

Применить изменения с помощью Write/Edit tools. Перейти к следующим gates.

#### 2.8: Gate 2: Tests Available / Run

После применения изменений для subtask запустить тесты, если доступны (**НЕ устанавливать зависимости** во время этого gate).

**Приоритет**: Использовать команды из `<SUBTASK_...__TEST_STRATEGY>`. Иначе:
- **Python (pytest)**: `pytest` или целевые тесты если известны
- **JavaScript (package.json)**: `npm test` / `pnpm test` / `yarn test` (в зависимости от репозитория)
- **Go (go.mod)**: `go test ./...`
- **Rust (Cargo.toml)**: `cargo test`

**Если тесты не найдены**: пометить gate как skipped и продолжить.

#### 2.9: Gate 3: Formatter / Linter

После tests gate запустить проверку форматирования/линтинга, если доступно (**НЕ устанавливать зависимости** во время этого gate).

**Приоритет**: Использовать repo-standard команды (например, `make lint`, `make fmt`, `make check`). Иначе:
- **Python**: `ruff check`, `black --check`, `mypy` (если настроены)
- **JavaScript/TypeScript**: `eslint`, `prettier -c` (если настроены)
- **Go**: `gofmt` проверка + `golangci-lint run` (если настроен)
- **Rust**: `cargo fmt --check`, `cargo clippy`

**Если инструменты не найдены**: пометить gate как skipped и продолжить.

После завершения всех gates перейти к следующему subtask (повторить шаги 2.0–2.9).

### Шаг 3: Summary

После завершения всех subtasks:

- Запустить тесты (если применимо)
- Создать commit (если запрошено)
- Отчёт: реализованные фичи, изменённые файлы

**Опционально:** Запустить `/map-learn [summary]` для сохранения ценных паттернов для будущих workflows.

## Когда рекомендовать `/map-learn`

Предлагать `/map-learn` если:
- Были найдены новые паттерны решения
- Debugging выявил нестандартные проблемы
- Несколько итераций Actor→Monitor (>3)

## Используемые MCP инструменты

Workflow использует следующие MCP инструменты:

- `mcp__cipher__cipher_memory_search` — поиск кросс-проектных паттернов
- `mcp__cipher__cipher_extract_and_operate_memory` — сохранение новых паттернов
- `mcp__sequential-thinking__sequentialthinking` — структурированный анализ

---

Begin now with efficient workflow.
