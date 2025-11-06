# Проверка работоспособности установки Cipher

После завершения установки и настройки необходимо проверить что все компоненты работают корректно.

## Checklist проверки

- [ ] PostgreSQL запущен и доступен
- [ ] Qdrant запущен и доступен
- [ ] Cipher установлен и запускается
- [ ] cipher.yml корректно настроен
- [ ] Claude Code видит Cipher MCP
- [ ] MCP tools доступны в Claude Code
- [ ] Memory операции работают

---

## Шаг 1: Проверка Docker инфраструктуры

### PostgreSQL

```bash
# Проверка что контейнер запущен
docker compose ps | grep postgres
```

**Ожидаемый вывод:**
```
cipher-postgres   running   healthy   0.0.0.0:5432->5432/tcp
```

**Статус должен быть:** `Up` и `healthy`

---

**Проверка подключения к PostgreSQL:**
```bash
# Через docker exec
docker exec -it cipher-postgres psql -U cipher -d cipher -c "SELECT version();"
```

**Ожидаемый вывод:**
```
                                                 version
---------------------------------------------------------------------------------------------------------
 PostgreSQL 16.x on x86_64-pc-linux-musl, compiled by gcc ...
(1 row)
```

---

**Через psql с хоста:**
```bash
psql "postgresql://cipher:ваш_пароль@localhost:5432/cipher" -c "SELECT 1 AS test;"
```

**Ожидаемый вывод:**
```
 test
------
    1
(1 row)
```

---

### Qdrant

```bash
# Проверка что контейнер запущен
docker compose ps | grep qdrant
```

**Ожидаемый вывод:**
```
cipher-qdrant   running   healthy   0.0.0.0:6333-6334->6333-6334/tcp
```

---

**Проверка health endpoint:**
```bash
curl -s http://localhost:6333/healthz | jq '.'
```

**Ожидаемый вывод:**
```json
{
  "title": "qdrant - vector search engine",
  "version": "1.x.x"
}
```

---

**Проверка коллекций:**
```bash
curl -s http://localhost:6333/collections | jq '.result.collections'
```

**Ожидаемый вывод (первый запуск):**
```json
[]
```

После первого использования Cipher создаст коллекцию автоматически.

---

### Docker logs

**Проверка логов на ошибки:**
```bash
# PostgreSQL logs
docker compose logs postgres --tail=50 | grep -i error

# Qdrant logs
docker compose logs qdrant --tail=50 | grep -i error
```

**Ожидаемый вывод:** Нет ошибок (пустой вывод или только INFO сообщения).

---

## Шаг 2: Проверка установки Cipher

### Проверка что Cipher установлен

```bash
# Для глобальной установки
which cipher
```

**Ожидаемый вывод:**
```
/Users/ваше_имя/.npm-global/bin/cipher
# или
/usr/local/bin/cipher
```

---

**Проверка версии:**
```bash
cipher --version
```

**Ожидаемый вывод:**
```
cipher version x.x.x
```

---

### Проверка cipher.yml

```bash
# Проверка что файл существует
ls -la ~/.cipher/cipher.yml
```

**Ожидаемый вывод:**
```
-rw-r--r--  1 user  staff  3456 Nov  6 20:00 /Users/user/.cipher/cipher.yml
```

---

**Валидация YAML синтаксиса:**
```bash
python3 -c "import yaml; yaml.safe_load(open('$HOME/.cipher/cipher.yml'))" && echo "✅ YAML валиден"
```

**Ожидаемый вывод:**
```
✅ YAML валиден
```

---

### Тестовый запуск Cipher (standalone)

```bash
# Запуск в интерактивном режиме
echo "Hello, test Cipher setup" | cipher "respond with OK if you can read this"
```

**Ожидаемый вывод:**
```
OK, I can read your message.
```

Если Cipher отвечает, значит:
- ✅ LLM provider настроен корректно
- ✅ API ключи работают
- ✅ cipher.yml валиден

---

## Шаг 3: Проверка MCP режима

### Запуск Cipher в MCP режиме

```bash
cipher --mode mcp --agent ~/.cipher/cipher.yml &
CIPHER_PID=$!

# Подождите 2 секунды
sleep 2

# Проверьте что процесс запущен
ps -p $CIPHER_PID

# Остановите процесс
kill $CIPHER_PID
```

**Ожидаемый вывод:**
```
  PID TTY           TIME CMD
 1234 ttys001    0:00.50 cipher --mode mcp --agent /Users/user/.cipher/cipher.yml
```

Если процесс запустился без ошибок, значит:
- ✅ MCP режим работает
- ✅ Подключение к PostgreSQL успешно
- ✅ Подключение к Qdrant успешно

---

### Проверка логов MCP запуска

```bash
# Запуск с выводом логов
cipher --mode mcp --agent ~/.cipher/cipher.yml 2>&1 | head -20
```

**Ожидаемый вывод (примерно):**
```
[INFO] Starting Cipher in MCP mode...
[INFO] Loading agent config from ~/.cipher/cipher.yml
[INFO] Connecting to PostgreSQL...
[INFO] PostgreSQL connection established
[INFO] Connecting to Qdrant...
[INFO] Qdrant connection established
[INFO] MCP server ready, listening on stdio
```

**НЕ должно быть:**
- ❌ `[ERROR] Failed to connect to PostgreSQL`
- ❌ `[ERROR] Failed to connect to Qdrant`
- ❌ `[ERROR] Environment variable X not found`

---

## Шаг 4: Проверка Claude Code конфигурации

### Валидация .claude.json

```bash
# macOS
python3 -m json.tool ~/.claude.json > /dev/null && echo "✅ JSON валиден"

# Linux
python3 -m json.tool ~/.claude.json > /dev/null && echo "✅ JSON валиден"
```

**Ожидаемый вывод:**
```
✅ JSON валиден
```

---

### Проверка что Cipher в конфигурации

```bash
# macOS
jq '.mcpServers | keys[]' ~/.claude.json | grep cipher

# Linux
jq '.mcpServers | keys[]' ~/.claude.json | grep cipher
```

**Ожидаемый вывод:**
```
"cipher"
```

---

### Проверка environment variables в конфигурации

```bash
# macOS
jq '.mcpServers.cipher.env' ~/.claude.json
```

**Ожидаемый вывод (примерно):**
```json
{
  "CIPHER_PG_URL": "postgresql://cipher:password@localhost:5432/cipher",
  "VECTOR_STORE_TYPE": "qdrant",
  "VECTOR_STORE_URL": "http://localhost:6333",
  "VECTOR_STORE_HOST": "localhost",
  "VECTOR_STORE_PORT": "6333",
  "VECTOR_STORE_DIMENSION": "1024",
  "MCP_SERVER_MODE": "aggregator",
  "STORAGE_DATABASE_TYPE": "postgresql",
  "OLLAMA_BASE_URL": "http://localhost:11434"
}
```

**Проверьте:**
- ✅ `CIPHER_PG_URL` соответствует вашей PostgreSQL строке подключения
- ✅ `VECTOR_STORE_DIMENSION` соответствует `embedding.dimensions` в cipher.yml
- ✅ `OLLAMA_BASE_URL` указывает на запущенный Ollama (если используете)

---

## Шаг 5: Проверка Claude Code

### Перезапуск Claude Code

**macOS:**
```bash
# Полный выход
osascript -e 'quit app "Claude"'

# Запуск из терминала (чтобы увидеть логи)
open -a Claude

# Или запустите через иконку приложения
```

**Linux:**
```bash
pkill -9 claude
claude
```

---

### Проверка MCP серверов в Claude Code

1. Откройте Claude Code
2. Создайте новый чат
3. В правом верхнем углу найдите иконку MCP (или Settings)
4. Проверьте список MCP серверов

**Ожидаемый результат:**
```
✅ cipher - Connected
```

**Если показывает ошибку:**
```
❌ cipher - Failed to connect
```

Проверьте логи:
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Linux
tail -f ~/.config/Claude/logs/mcp*.log
```

---

## Шаг 6: Тестирование MCP tools

### Тест 1: cipher_memory_search

В Claude Code чате напишите:
```
Используй cipher_memory_search чтобы найти в моей memory базе информацию про "test query"
```

**Ожидаемый результат:**
- Claude вызовет MCP tool `cipher_memory_search`
- Вернет результаты (может быть пустой массив при первом запуске)
- Не должно быть ошибок подключения

---

### Тест 2: cipher_extract_and_operate_memory

В Claude Code чате напишите:
```
Запомни следующий факт: "MAP Framework использует Cipher для cross-project knowledge management"
```

**Ожидаемый результат:**
- Claude вызовет `cipher_extract_and_operate_memory`
- Факт будет сохранен в PostgreSQL и Qdrant
- Claude подтвердит успешное сохранение

---

### Тест 3: Проверка что память сохранилась

```bash
# Проверка в PostgreSQL
docker exec -it cipher-postgres psql -U cipher -d cipher -c "SELECT COUNT(*) FROM memories;"
```

**Ожидаемый вывод:**
```
 count
-------
     1
(1 row)
```

---

```bash
# Проверка в Qdrant
curl -s http://localhost:6333/collections | jq '.result.collections[].name'
```

**Ожидаемый вывод:**
```
"cipher_memory"
```

---

**Проверка количества vectors:**
```bash
curl -s http://localhost:6333/collections/cipher_memory | jq '.result.points_count'
```

**Ожидаемый вывод:**
```
1
```

---

### Тест 4: Поиск сохраненной памяти

В Claude Code чате напишите:
```
Найди в моей memory все что связано с MAP Framework
```

**Ожидаемый результат:**
- Claude вызовет `cipher_memory_search`
- Найдет ранее сохраненный факт про MAP Framework
- Покажет результаты поиска

---

## Шаг 7: Проверка reasoning memory

### Тест reasoning extraction

В Claude Code чате напишите:
```
Давай пошагово решим задачу: как установить Cipher с нуля?

Мои рассуждения:
1. Сначала нужно установить Node.js
2. Затем установить Cipher через npm
3. Настроить cipher.yml
4. Настроить Claude Code

Извлеки эти reasoning steps и сохрани их.
```

**Ожидаемый результат:**
- Claude вызовет `cipher_extract_reasoning_steps`
- Затем `cipher_store_reasoning_memory`
- Reasoning trace будет сохранен

---

### Тест reasoning search

```
Найди в моей reasoning memory паттерны связанные с установкой софта
```

**Ожидаемый результат:**
- Claude вызовет `cipher_search_reasoning_patterns`
- Найдет ранее сохраненный reasoning trace
- Покажет шаги установки

---

## Шаг 8: Performance и Health Check

### Проверка latency

**PostgreSQL query time:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "\timing on" -c "SELECT COUNT(*) FROM memories;"
```

**Ожидаемый результат:**
```
Time: 5.234 ms
```

Должно быть < 100ms для локальной БД.

---

**Qdrant search time:**
```bash
time curl -s http://localhost:6333/collections/cipher_memory/points/search \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 5
  }' > /dev/null
```

**Примечание:** `"vector": [0.1, 0.2, ...]` - это placeholder. Для реального тестирования необходимо предоставить полный вектор с правильной размерностью (1024 или 1536 элементов в зависимости от вашей конфигурации embedding).

Должно быть < 200ms.

---

### Проверка ресурсов

```bash
# Memory usage
docker stats --no-stream cipher-postgres cipher-qdrant

# Disk usage
docker exec -it cipher-postgres du -sh /var/lib/postgresql/data
docker exec -it cipher-qdrant du -sh /qdrant/storage
```

**Типичные значения:**
- PostgreSQL: 50-100MB RAM, 100-500MB disk
- Qdrant: 100-500MB RAM, 100MB-1GB disk (зависит от количества vectors)

---

## Troubleshooting распространенных проблем

### Проблема: PostgreSQL не healthy

```bash
docker compose logs postgres --tail=100
```

Если видите `FATAL: password authentication failed`:
- Проверьте пароль в `.env` файле
- Проверьте `CIPHER_PG_URL` в Claude Code конфиге
- Пересоздайте контейнер: `docker compose down -v && docker compose up -d`

---

### Проблема: Qdrant не отвечает

```bash
docker compose restart qdrant
docker compose logs qdrant --tail=50
```

Если видите `address already in use`:
- Порт 6333 или 6334 занят другим процессом
- Найдите процесс: `lsof -i :6333`
- Остановите конфликтующий процесс или измените порты в docker-compose.yml

---

### Проблема: Cipher не может подключиться к PostgreSQL

**Симптомы:** `connection refused` или `could not connect to server`

**Решение:**

1. Проверьте что PostgreSQL запущен: `docker compose ps`
2. Проверьте строку подключения: `echo $CIPHER_PG_URL`
3. Тестовое подключение: `psql "$CIPHER_PG_URL" -c "SELECT 1"`
4. Проверьте firewall: `sudo ufw status` (Linux)

---

### Проблема: Claude Code не видит MCP tools

**Симптомы:** В чате нет доступа к cipher tools

**Решение:**

1. Проверьте логи: `tail -f ~/Library/Logs/Claude/mcp*.log`
2. Полный перезапуск Claude Code (Cmd+Q, затем запуск)
3. Проверьте JSON конфиг: `python3 -m json.tool ~/.claude.json`
4. Проверьте что Cipher запускается: `cipher --mode mcp --agent ~/.cipher/cipher.yml`

---

## Итоговый checklist

✅ **Инфраструктура:**
- [ ] PostgreSQL: `docker compose ps | grep postgres` → `healthy`
- [ ] Qdrant: `curl http://localhost:6333/healthz` → `{"title":"qdrant"}`

✅ **Cipher:**
- [ ] Установлен: `which cipher` → путь к бинарнику
- [ ] Конфиг валиден: `python3 -c "import yaml; yaml.safe_load(open('$HOME/.cipher/cipher.yml'))"`
- [ ] MCP режим работает: `cipher --mode mcp --agent ~/.cipher/cipher.yml` → запускается без ошибок

✅ **Claude Code:**
- [ ] Конфиг валиден: `python3 -m json.tool ~/.claude.json`
- [ ] Cipher в конфиге: `jq '.mcpServers | keys[]' ... | grep cipher` → `"cipher"`
- [ ] MCP сервер подключен: В Claude Code UI → `✅ cipher - Connected`

✅ **Функциональность:**
- [ ] Memory search работает: Тест в Claude Code чате
- [ ] Memory save работает: Факт сохранился в PostgreSQL/Qdrant
- [ ] Reasoning extraction работает: Reasoning trace сохранен

**Если все чекбоксы ✅, установка завершена успешно!**

---

## Следующие шаги

После успешной проверки:

1. ✅ Изучите расширенный troubleshooting → [06-troubleshooting.md](06-troubleshooting.md)
2. ✅ Прочитайте полное руководство → [MCP-CIPHER-QDRANT-SETUP.md](../MCP-CIPHER-QDRANT-SETUP.md)
3. ✅ Начните использовать Cipher в ваших MAP workflows!

## Дополнительные ресурсы

- 📚 [Официальная документация Cipher](https://docs.byterover.dev/cipher)
- 💻 [MAP Framework INSTALL.md](../INSTALL.md)
- 🔧 [Примеры использования](../../examples/cipher/)
