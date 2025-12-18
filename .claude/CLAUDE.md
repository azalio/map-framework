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
cp .claude/agents/research-agent.md src/mapify_cli/templates/agents/
cp .claude/agents/synthesizer.md src/mapify_cli/templates/agents/

# 3. Синхронизируй команды
cp .claude/commands/map-efficient.md src/mapify_cli/templates/commands/
cp .claude/commands/map-debug.md src/mapify_cli/templates/commands/
cp .claude/commands/map-fast.md src/mapify_cli/templates/commands/
cp .claude/commands/map-learn.md src/mapify_cli/templates/commands/
cp .claude/commands/map-release.md src/mapify_cli/templates/commands/
cp .claude/commands/map-review.md src/mapify_cli/templates/commands/

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

При работе с MAP Framework slash commands (`/map-efficient`, `/map-debug`, `/map-fast`):

### Обязательная последовательность агентов

Для КАЖДОГО subtask:

```
1. Actor (implement)
2. Monitor (validate) → If invalid: return to Actor with feedback
3. Predictor (analyze impact) ← условно, для high-risk subtasks
4. Apply changes
```

### Learning is OPTIONAL via /map-learn

Reflector и Curator теперь вызываются ТОЛЬКО через отдельную команду `/map-learn`:

✅ **НОВЫЙ ПОДХОД**:
- Workflows (map-efficient, map-debug, map-fast) НЕ включают автоматический learning
- После завершения workflow предлагай пользователю: "Если хотите сохранить паттерны — запустите `/map-learn`"
- `/map-learn` вызывает Reflector → Curator → playbook update → cipher sync

❌ **Не добавляй learning в workflows**:
- Не вызывай Reflector/Curator автоматически в map-efficient, map-debug
- Не делай работу Reflector/Curator самостоятельно

### Когда рекомендовать /map-learn

Предлагай `/map-learn` если:
- Были найдены новые паттерны решения
- Debugging выявил нестандартные проблемы
- Несколько итераций Actor→Monitor (>3)

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
