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

Скрипт для проверки синхронизации:

```bash
#!/bin/bash
# scripts/check-template-sync.sh

echo "Checking template synchronization..."

# Check agents
for agent in task-decomposer actor monitor predictor evaluator reflector curator documentation-reviewer; do
    source=".claude/agents/${agent}.md"
    target="src/mapify_cli/templates/agents/${agent}.md"

    if [ -f "$source" ] && [ -f "$target" ]; then
        if ! diff -q "$source" "$target" > /dev/null; then
            echo "❌ OUT OF SYNC: agents/${agent}.md"
            echo "   Run: cp $source $target"
        else
            echo "✅ IN SYNC: agents/${agent}.md"
        fi
    else
        echo "⚠️  MISSING: agents/${agent}.md (source or target not found)"
    fi
done

# Check commands
for command in map-feature map-debug map-refactor map-review map-efficient map-fast; do
    source=".claude/commands/${command}.md"
    target="src/mapify_cli/templates/commands/${command}.md"

    if [ -f "$source" ] && [ -f "$target" ]; then
        if ! diff -q "$source" "$target" > /dev/null; then
            echo "❌ OUT OF SYNC: commands/${command}.md"
            echo "   Run: cp $source $target"
        else
            echo "✅ IN SYNC: commands/${command}.md"
        fi
    else
        echo "⚠️  MISSING: commands/${command}.md (source or target not found)"
    fi
done
```

### Git Pre-Commit Hook

Добавь в `.claude/hooks/pre-commit.sh`:

```bash
# Check template synchronization
echo "Checking agent template synchronization..."
if ! bash scripts/check-template-sync.sh | grep -q "❌"; then
    echo "✅ Templates in sync"
else
    echo "❌ ERROR: Templates out of sync!"
    echo "Run: cp .claude/agents/*.md src/mapify_cli/templates/agents/"
    exit 1
fi
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
- "Я сам обновлю playbook.json"
- "Пропущу Reflector для простой задачи"

✅ **ХОРОШО**:
- Всегда вызывай `Task(subagent_type="reflector", ...)`
- Всегда вызывай `Task(subagent_type="curator", ...)`
- Проверяй что Reflector использовал `cipher_memory_search`
- Проверяй что Curator использовал `cipher_memory_search` для дедупликации

### Почему это важно?

**Двойная система памяти**:
- **Playbook** (`.claude/playbook.json`) - проектные паттерны
- **Cipher** (MCP tool) - кросс-проектные знания

Когда пропускаешь агентов:
- ✅ Playbook обновляется (ты делаешь вручную)
- ❌ Cipher НЕ обновляется (MCP tools не вызываются)
- ❌ Знания не дедуплицируются (cipher_memory_search не вызывается)
- ❌ Будущие workflows не получают преимуществ

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
