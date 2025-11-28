# MAP Framework Development Instructions

## Critical: Template Synchronization

**ВАЖНО**: После изменения любых файлов в `.claude/agents/` или `.claude/commands/`, ВСЕГДА синхронизируй их в `src/mapify_cli/templates/`!

### Почему это критично?

Когда пользователи запускают `mapify init`, они получают шаблоны из `src/mapify_cli/templates/`, а НЕ из `.claude/`. Если забыть синхронизировать:
- Новые пользователи получают УСТАРЕВШИЕ шаблоны
- Улучшения НЕ доступны через `mapify init`
- Создаётся расхождение между dev и production шаблонами

### Процесс синхронизации

После ЛЮБОГО изменения файлов в `.claude/agents/` или `.claude/commands/`:

```bash
# 1. Проверь что изменилось
git status .claude/agents/ .claude/commands/

# 2. Синхронизируй агентов
cp .claude/agents/task-decomposer.md src/mapify_cli/templates/agents/
cp .claude/agents/actor.md src/mapify_cli/templates/agents/
cp .claude/agents/monitor.md src/mapify_cli/templates/agents/
cp .claude/agents/predictor.md src/mapify_cli/templates/agents/
cp .claude/agents/evaluator.md src/mapify_cli/templates/agents/
cp .claude/agents/reflector.md src/mapify_cli/templates/agents/
cp .claude/agents/curator.md src/mapify_cli/templates/agents/
cp .claude/agents/documentation-reviewer.md src/mapify_cli/templates/agents/

# 3. Синхронизируй команды
cp .claude/commands/map-feature.md src/mapify_cli/templates/commands/
cp .claude/commands/map-debug.md src/mapify_cli/templates/commands/
cp .claude/commands/map-refactor.md src/mapify_cli/templates/commands/
cp .claude/commands/map-review.md src/mapify_cli/templates/commands/
cp .claude/commands/map-efficient.md src/mapify_cli/templates/commands/
cp .claude/commands/map-fast.md src/mapify_cli/templates/commands/

# 4. Проверь что файлы скопировались
git status src/mapify_cli/templates/

# 5. Закоммить вместе с остальными изменениями
git add src/mapify_cli/templates/
```

### Автоматическая проверка

Проверка синхронизации через pytest (запускается в CI):

```bash
# Запуск тестов синхронизации
pytest tests/test_template_sync.py -v

# Тесты проверяют:
# - Все файлы из .claude/agents/ существуют в templates/
# - Нет orphaned файлов в templates/ без source
# - Контент файлов идентичен
# - Frontmatter не ссылается на удалённые файлы
```

## MAP Workflow Enforcement

При работе с MAP Framework slash commands (`/map-feature`, `/map-debug`, `/map-refactor`):

### Обязательная последовательность агентов

Для КАЖДОГО subtask:

```
1. Actor (implement)
2. Monitor (validate) → If invalid: return to Actor with feedback
3. Predictor (analyze impact)
4. Evaluator (score quality) → If not approved: return to Actor
5. Reflector (extract lessons) ← ОБЯЗАТЕЛЬНО
6. Curator (update playbook) ← ОБЯЗАТЕЛЬНО
```

### НИКОГДА не делай работу агентов самостоятельно

❌ **ПЛОХО**:
- "Я сам проанализирую успех и напишу lessons learned"
- "Я сам обновлю playbook напрямую" (через sqlite3 или Edit)
- "Пропущу Reflector для простой задачи"

✅ **ХОРОШО**:
- Всегда вызывай `Task(subagent_type="reflector", ...)`
- Всегда вызывай `Task(subagent_type="curator", ...)`
- Проверяй что Reflector использовал `cipher_memory_search`
- Проверяй что Curator использовал `cipher_memory_search` для дедупликации

### Почему это важно?

**Двойная система памяти**:
- **Playbook** (`.claude/playbook.db` SQLite) - проектные паттерны
- **Cipher** (MCP tool) - кросс-проектные знания

Когда пропускаешь агентов:
- ✅ Playbook обновляется (ты делаешь вручную)
- ❌ Cipher НЕ обновляется (MCP tools не вызываются)
- ❌ Знания не дедуплицируются (cipher_memory_search не вызывается)
- ❌ Будущие workflows не получают преимуществ

## Playbook Update Rules

**CRITICAL: How to Update Playbook**

✅ **CORRECT WAY (via Curator agent)**:
1. Call `Task(subagent_type="curator", ...)`
2. Curator outputs JSON delta operations
3. Apply via: `mapify playbook apply-delta curator_operations.json`

❌ **NEVER DO THIS**:
- ❌ `sqlite3 .claude/playbook.db "UPDATE bullets SET..."`  (direct SQL)
- ❌ `Edit(.claude/playbook.db, ...)` (Edit tool on binary file)
- ❌ Manually creating JSON and applying without Curator review

**Why**:
- Curator validates quality, checks duplicates, scores patterns
- `apply-delta` maintains playbook integrity, handles transactions
- Direct sqlite breaks schema, bypasses validation

## Template Variable Protection

**НИКОГДА не удаляй** template variables из agent files:
- `{{language}}`
- `{{#if playbook_bullets}}...{{/if}}`
- `{{feedback}}`
- `{{code}}`
- и т.д.

Эти переменные критичны для orchestration. Git hook `.claude/hooks/pre-commit.sh` проверяет их наличие.

## Documentation Updates

При изменении функциональности обновляй:
1. **USAGE.md** - примеры использования, best practices
2. **README.md** - quick reference
3. **ARCHITECTURE.md** - технические детали (если меняется архитектура)

## Testing

Перед коммитом:

```bash
# Запусти все тесты
pytest

# Проверь новую функциональность вручную
mapify --help
mapify validate graph tests/fixtures/valid_graph.json
```

## Commit Messages

Используй conventional commits:

```
feat: add new feature
fix: bug fix
docs: documentation update
refactor: code refactoring
test: add tests
chore: maintenance
```

Для больших изменений добавляй детальное описание в body коммита.
