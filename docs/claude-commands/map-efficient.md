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

Шаблон требует вызвать `Task(... subagent_type="task-decomposer" ...)` с prompt’ом “Break down this task into atomic subtasks (≤8)” и запросом JSON-выхода со структурой:

- `subtasks`: массив объектов `{id, description, acceptance_criteria, estimated_complexity, risk_level, depends_on}`
- `total_subtasks`
- `estimated_duration`

И предписывает присваивать `risk_level` по шкале `low|medium|high`, причём прямо написано:

- `high`: security-sensitive, breaking changes, multi-file modifications
- `medium`: moderate complexity, some dependencies
- `low`: simple, isolated changes

Также в prompt’е `task-decomposer` указано, что **risk level определяет вызов Predictor**: `high/medium = yes`, `low = no` (это правило далее уточняется шагом 2.6).

### Шаг 2: цикл по сабтаскам (Efficient Loop)

#### Шаг 2.1: контекст для сабтаска (playbook)

**A. Local playbook query**:

```bash
PLAYBOOK_BULLETS=$(mapify playbook query "[subtask description]" --limit 5)
```

**B. Cipher search (опционально, но “recommended”)**:

```text
mcp__cipher__cipher_memory_search(query="[subtask concept]", top_k=5)
```

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
    subtask.complexity == "high" OR
    subtask.security_critical == True
)
```

Если `self_moa_enabled == true` → выполняется путь Self‑MoA (2.3a–2.3d). Иначе → стандартный путь (2.3–2.4).

### Путь Self‑MoA (2.3a–2.3d)

#### 2.3a: параллельно 3 варианта Actor

Требуется вызвать `actor` 3 раза с разными фокусами:

- v1: `approach_focus: security`
- v2: `approach_focus: performance`
- v3: `approach_focus: simplicity`

И прямо сказано “Execute all 3 Actor calls in parallel”.

#### 2.3b: параллельно 3 варианта Monitor

Требуется валидировать каждый вариант отдельно через `monitor`, с полями в output, включая:

- `decisions_identified`
- `compatibility_features` (перечень: `error_paradigm, concurrency_model, state_management, type_strictness, naming_convention, imports_used`)
- `contract_compliant`
- `recommended_as_base`

И прямо сказано “Execute all 3 Monitor calls in parallel”.

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

#### 2.4: Monitor

Требуется `Task(... subagent_type="monitor" ...)`, который проверяет корректность/безопасность/перфоманс/тесты/стандарты и обязан выставить риск-флаг:

- `high_risk_detected: boolean` (если `true`, Predictor будет вызван).

В prompt’е Monitor также перечислены условия, при которых нужно считать риск высоким (Security vulnerabilities, breaking API changes likely, >3 файлов, complex dependencies).

#### 2.5: решение и повторы

- Если `monitor.valid === false`: дать feedback Actor и вернуться к 2.3 (max 3–5 iterations).
- Если `monitor.valid === true`: продолжить к 2.6.

Отдельно в конце шаблона в секции “Critical Constraints” явно задано ограничение: **MAX 5 iterations per subtask**.

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

#### 2.7–2.8: применение и переход дальше

Шаблон предписывает:

- применить изменения “using Write/Edit tools” и отметить сабтаск выполненным;
- повторить шаги 2.1–2.7 для остальных сабтасков.

### Шаг 3: финал

Шаблон требует в конце:

- запустить тесты (если применимо),
- создать commit,
- дать summary: реализованные фичи, изменённые файлы, качество, и блок “Token efficiency” с подсчётом Predictor calls и оценкой savings (в тексте: ~40–50% vs `/map-feature`).

## Опционально: `/map-learn`

После завершения workflow шаблон предлагает (не обязует) запустить `/map-learn` для сохранения паттернов, и перечисляет когда стоит/не стоит это делать.

## Явно перечисленные MCP инструменты

В конце шаблон перечисляет “MCP Tools Available”:

- `mcp__cipher__cipher_memory_search`
- `mcp__cipher__cipher_extract_and_operate_memory`
- `mcp__sequential-thinking__sequentialthinking`
- `mcp__context7__get-library-docs`
- `mcp__claude-reviewer__request_review`

## Прочие секции, которые есть в шаблоне

- Таблица “Comparison: /map-efficient vs Alternatives” (сравнение с `/map-feature` и `/map-fast`).
- Блок “Example” с примером запроса пользователя и иллюстрацией, когда вызывается Predictor.
- Финальная строка-инструкция: “Begin now with efficient workflow.”
