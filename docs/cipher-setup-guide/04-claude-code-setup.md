# Настройка Claude Code для работы с Cipher MCP

После установки Cipher и настройки `cipher.yml`, необходимо настроить Claude Code (Claude Desktop) для использования Cipher как MCP сервера.

## Расположение конфигурации

Claude Code ищет MCP конфигурацию в двух местах:

### Глобальная конфигурация (рекомендуется)

**macOS:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Linux:**
```
~/.config/Claude/claude_desktop_config.json
```

**Windows:**
```
%APPDATA%\Claude\claude_desktop_config.json
```

### Проектная конфигурация

```
./.mcp.json  # В корне вашего проекта
```

**Важно:** Проектная конфигурация переопределяет глобальную!

---

## Базовая конфигурация Cipher MCP

### Вариант 1: Глобальная установка Cipher (рекомендуется)

Если вы установили Cipher глобально (`npm install -g @byterover/cipher`):

**~/Library/Application Support/Claude/claude_desktop_config.json:**
```json
{
  "mcpServers": {
    "cipher": {
      "command": "cipher",
      "args": [
        "--mode", "mcp",
        "--agent", "/Users/ваше_имя/.cipher/cipher.yml"
      ],
      "env": {
        "CIPHER_PG_URL": "postgresql://cipher:ваш_пароль@localhost:5432/cipher",
        "VECTOR_STORE_TYPE": "qdrant",
        "VECTOR_STORE_URL": "http://localhost:6333",
        "VECTOR_STORE_HOST": "localhost",
        "VECTOR_STORE_PORT": "6333",
        "VECTOR_STORE_DIMENSION": "1024",
        "MCP_SERVER_MODE": "aggregator",
        "STORAGE_DATABASE_TYPE": "postgresql",
        "OLLAMA_BASE_URL": "http://localhost:11434"
      }
    }
  }
}
```

**Замените:**
- `ваше_имя` → ваш username
- `ваш_пароль` → пароль PostgreSQL из `.env` файла
- `VECTOR_STORE_DIMENSION` → размерность из вашего `cipher.yml` (1024 или 1536)

---

### Вариант 2: Использование npx (без глобальной установки)

Если Cipher установлен локально или вы предпочитаете npx:

```json
{
  "mcpServers": {
    "cipher": {
      "command": "npx",
      "args": [
        "-y",
        "@byterover/cipher",
        "--mode", "mcp",
        "--agent", "/Users/ваше_имя/.cipher/cipher.yml"
      ],
      "env": {
        "CIPHER_PG_URL": "postgresql://cipher:ваш_пароль@localhost:5432/cipher",
        "VECTOR_STORE_TYPE": "qdrant",
        "VECTOR_STORE_URL": "http://localhost:6333",
        "VECTOR_STORE_HOST": "localhost",
        "VECTOR_STORE_PORT": "6333",
        "VECTOR_STORE_DIMENSION": "1024",
        "MCP_SERVER_MODE": "aggregator",
        "STORAGE_DATABASE_TYPE": "postgresql",
        "OLLAMA_BASE_URL": "http://localhost:11434"
      }
    }
  }
}
```

**Плюсы npx:**
- ✅ Работает без глобальной установки
- ✅ Автоматически использует последнюю версию
- ✅ Не зависит от PATH

**Минусы:**
- ❌ Медленнее первый запуск (скачивание пакета)
- ❌ Требует интернет при первом вызове

---

### Вариант 3: Использование environment variable expansion

Для безопасности, вместо hardcode паролей используйте variable expansion:

```json
{
  "mcpServers": {
    "cipher": {
      "command": "cipher",
      "args": [
        "--mode", "mcp",
        "--agent", "${HOME}/.cipher/cipher.yml"
      ],
      "env": {
        "CIPHER_PG_URL": "${CIPHER_PG_URL}",
        "VECTOR_STORE_TYPE": "qdrant",
        "VECTOR_STORE_URL": "${VECTOR_STORE_URL}",
        "VECTOR_STORE_HOST": "localhost",
        "VECTOR_STORE_PORT": "6333",
        "VECTOR_STORE_DIMENSION": "${VECTOR_STORE_DIMENSION}",
        "MCP_SERVER_MODE": "aggregator",
        "STORAGE_DATABASE_TYPE": "postgresql",
        "OLLAMA_BASE_URL": "${OLLAMA_BASE_URL}",
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      }
    }
  }
}
```

**Затем экспортируйте переменные в shell:**
```bash
# Добавьте в ~/.zshrc или ~/.bashrc
export CIPHER_PG_URL="postgresql://cipher:secure_password@localhost:5432/cipher"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_DIMENSION="1024"
export OLLAMA_BASE_URL="http://localhost:11434"
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."

# Перезагрузите shell
source ~/.zshrc
```

⚠️ **Внимание:** Claude Desktop должен быть запущен из shell с этими переменными!

---

## Полная конфигурация с несколькими MCP серверами

Пример конфигурации MAP Framework с Cipher и другими полезными MCP серверами:

```json
{
  "mcpServers": {
    "cipher": {
      "command": "cipher",
      "args": ["--mode", "mcp", "--agent", "${HOME}/.cipher/cipher.yml"],
      "env": {
        "CIPHER_PG_URL": "${CIPHER_PG_URL}",
        "VECTOR_STORE_TYPE": "qdrant",
        "VECTOR_STORE_URL": "http://localhost:6333",
        "VECTOR_STORE_HOST": "localhost",
        "VECTOR_STORE_PORT": "6333",
        "VECTOR_STORE_DIMENSION": "1024",
        "MCP_SERVER_MODE": "aggregator",
        "STORAGE_DATABASE_TYPE": "postgresql",
        "OLLAMA_BASE_URL": "${OLLAMA_BASE_URL}"
      }
    },
    "claude-reviewer": {
      "command": "npx",
      "args": ["-y", "@vibesnipe/code-review-mcp"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      }
    },
    "sequential-thinking": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    },
    "deepwiki": {
      "type": "sse",
      "url": "https://mcp.deepwiki.com/sse"
    }
  }
}
```

---

## API Keys в конфигурации

### Опция 1: Явные ключи в env (простой способ)

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-api03-...",
    "OPENAI_API_KEY": "sk-...",
    "VOYAGE_API_KEY": "pa-..."
  }
}
```

❌ **Недостатки:**
- Ключи в plain text в конфиге
- Видны в файловой системе
- Сложнее ротация ключей

---

### Опция 2: Environment variable expansion (рекомендуется)

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
    "OPENAI_API_KEY": "${OPENAI_API_KEY}",
    "VOYAGE_API_KEY": "${VOYAGE_API_KEY}"
  }
}
```

✅ **Преимущества:**
- Ключи не в конфиге
- Легко ротировать (меняете в shell env)
- Можно использовать secret managers

**Настройка:**
```bash
# Добавьте в ~/.zshrc или ~/.bashrc
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export VOYAGE_API_KEY="pa-..."

# Важно! Перезапустите Claude Desktop после изменений
```

---

### Опция 3: Загрузка из .env файла

Создайте `~/.cipher/.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
VOYAGE_API_KEY=pa-...
CIPHER_PG_URL=postgresql://cipher:password@localhost:5432/cipher
```

Затем загрузите в shell config:
```bash
# В ~/.zshrc или ~/.bashrc
if [ -f ~/.cipher/.env ]; then
  set -a; source ~/.cipher/.env; set +a
fi
```

---

## Проверка конфигурации

### Шаг 1: Валидация JSON

```bash
# Проверка синтаксиса JSON (macOS)
python3 -m json.tool ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Или через jq
jq '.' ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Если ошибка синтаксиса:**
- Проверьте запятые (последний элемент не должен иметь запятую)
- Проверьте кавычки (двойные `"`, не одинарные `'`)
- Проверьте скобки (каждая `{` должна иметь `}`)

---

### Шаг 2: Проверка путей

```bash
# Проверка что cipher доступен
which cipher

# Проверка что cipher.yml существует
ls -la ~/.cipher/cipher.yml

# Проверка что путь в конфиге правильный
jq '.mcpServers.cipher.args' ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

---

### Шаг 3: Проверка environment variables

```bash
# Проверка что переменные установлены
env | grep CIPHER
env | grep VECTOR_STORE
env | grep OLLAMA
```

**Если переменные не установлены:**
```bash
# Перезагрузите shell config
source ~/.zshrc  # или ~/.bashrc

# Проверьте снова
echo $CIPHER_PG_URL
```

---

### Шаг 4: Перезапуск Claude Desktop

**macOS:**
```bash
# Полный выход из приложения
osascript -e 'quit app "Claude"'

# Или через Activity Monitor: Force Quit "Claude"

# Запустите снова
open -a Claude
```

**Linux:**
```bash
pkill -9 claude
claude  # Или через иконку приложения
```

⚠️ **Важно:** После ЛЮБЫХ изменений в `claude_desktop_config.json` нужен полный перезапуск Claude Desktop!

---

## Использование Cipher в Claude Code

После настройки, Cipher MCP tools доступны в Claude Code:

### Доступные MCP tools

1. **cipher_extract_and_operate_memory** - Сохранить знания в memory
2. **cipher_memory_search** - Поиск по knowledge base
3. **cipher_extract_reasoning_steps** - Извлечь reasoning steps
4. **cipher_evaluate_reasoning** - Оценить качество reasoning
5. **cipher_store_reasoning_memory** - Сохранить reasoning trace
6. **cipher_search_reasoning_patterns** - Поиск reasoning patterns
7. **cipher_bash** - Выполнить bash команды

### Пример использования

**В Claude Code чате:**
```
Найди в моей memory базе все что я знаю про FastAPI authentication
```

Claude автоматически вызовет `cipher_memory_search` с вашим запросом.

**Или явный вызов:**
```
Используй cipher_memory_search чтобы найти паттерны работы с PostgreSQL
```

---

## Troubleshooting

### Проблема 1: "MCP server 'cipher' failed to start"

**Симптомы:** В Claude Code внизу показывается ошибка подключения к Cipher

**Решение:**

**Шаг 1:** Проверьте логи Claude Desktop
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Linux
tail -f ~/.config/Claude/logs/mcp*.log
```

**Шаг 2:** Проверьте что Cipher запускается вручную
```bash
cipher --mode mcp --agent ~/.cipher/cipher.yml
```

Если ошибка:
- ❌ "command not found" → Установите Cipher или используйте `npx`
- ❌ "Cannot find cipher.yml" → Проверьте путь в `args`
- ❌ "Environment variable not found" → Экспортируйте переменные

**Шаг 3:** Проверьте конфигурацию
```bash
jq '.mcpServers.cipher' ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

---

### Проблема 2: "Environment variables not loaded"

**Симптомы:** Cipher запускается, но не может подключиться к PostgreSQL/Qdrant

**Решение:**

Claude Desktop не загружает `~/.zshrc` автоматически!

**Вариант 1:** Запустите Claude из терминала
```bash
# macOS
open -a Claude

# Теперь переменные из shell будут доступны
```

**Вариант 2:** Добавьте переменные явно в конфиг
```json
{
  "env": {
    "CIPHER_PG_URL": "postgresql://cipher:password@localhost:5432/cipher",
    "VECTOR_STORE_URL": "http://localhost:6333",
    ...
  }
}
```

**Вариант 3:** Используйте launchd (macOS) для environment variables
```bash
# Создайте ~/Library/LaunchAgents/environment.plist
# (требует дополнительной настройки)
```

---

### Проблема 3: "Database connection failed"

**Симптомы:** `connection to server at "localhost" (::1), port 5432 failed`

**Решение:**

**Шаг 1:** Проверьте что PostgreSQL запущен
```bash
docker compose ps | grep postgres
```

Должен показывать `Up` и `healthy`.

**Шаг 2:** Проверьте строку подключения
```bash
# Тест подключения
psql "postgresql://cipher:ваш_пароль@localhost:5432/cipher" -c "SELECT 1"
```

**Шаг 3:** Проверьте environment variable в MCP конфиге
```bash
jq '.mcpServers.cipher.env.CIPHER_PG_URL' ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

---

### Проблема 4: "Qdrant connection timeout"

**Симптомы:** `Failed to connect to Qdrant at http://localhost:6333`

**Решение:**

**Шаг 1:** Проверьте что Qdrant запущен
```bash
curl http://localhost:6333/healthz
```

Должен вернуть `{"status":"ok"}`.

**Шаг 2:** Проверьте VECTOR_STORE_URL
```bash
jq '.mcpServers.cipher.env.VECTOR_STORE_URL' ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Шаг 3:** Проверьте firewall/ports
```bash
lsof -i :6333
netstat -an | grep 6333
```

---

### Проблема 5: "JSON parse error in config"

**Симптомы:** Claude Desktop не запускается или показывает ошибку конфигурации

**Решение:**

**Шаг 1:** Валидация JSON
```bash
python3 -m json.tool ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Шаг 2:** Найдите ошибку в выводе
Типичные ошибки:
- ❌ Trailing comma: `"args": [...],` (последняя запятая)
- ❌ Одинарные кавычки: `'cipher'` вместо `"cipher"`
- ❌ Незакрытые скобки: `{` без `}`
- ❌ Комментарии: JSON не поддерживает `//` комментарии

**Шаг 3:** Используйте резервную копию
```bash
cp ~/Library/Application\ Support/Claude/claude_desktop_config.json.bak ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

---

## Следующие шаги

После настройки Claude Code:

1. ✅ Проверьте работоспособность → [05-verification.md](05-verification.md)
2. ✅ Изучите troubleshooting → [06-troubleshooting.md](06-troubleshooting.md)

## Дополнительные ресурсы

- 📚 [MAP Framework .mcp.json.example](../../.mcp.json.example)
- 💻 [Официальная документация Claude Code MCP](https://docs.anthropic.com/claude/docs/model-context-protocol)
- 🔧 [Примеры конфигураций](../../examples/cipher/)
