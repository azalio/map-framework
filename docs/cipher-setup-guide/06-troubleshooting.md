# Расширенный Troubleshooting

Этот документ содержит решения распространенных и редких проблем при работе с Cipher + Qdrant + PostgreSQL.

## Категории проблем

- [Docker и инфраструктура](#docker-и-инфраструктура)
- [PostgreSQL](#postgresql)
- [Qdrant](#qdrant)
- [Cipher установка и конфигурация](#cipher-установка-и-конфигурация)
- [Claude Code и MCP](#claude-desktop-и-mcp)
- [Performance и оптимизация](#performance-и-оптимизация)
- [Security и безопасность](#security-и-безопасность)

---

## Docker и инфраструктура

### Проблема: Docker контейнеры не запускаются

**Симптомы:**
```bash
docker compose up -d
# ERROR: ...
```

**Решения:**

**1. Проверка Docker daemon:**
```bash
docker info
```

Если ошибка `Cannot connect to the Docker daemon`:
- macOS: Откройте Docker Desktop
- Linux: `sudo systemctl start docker`
- Windows: Запустите Docker Desktop

---

**2. Проверка docker-compose.yml синтаксиса:**
```bash
docker compose config
```

Если ошибка `yaml: line X: ...`:
- Проверьте отступы (только пробелы, не табы!)
- Проверьте что все ключи уникальны
- Валидируйте через `yamllint docker-compose.yml`

---

**3. Конфликт портов:**
```bash
# Проверка занятых портов
lsof -i :5432  # PostgreSQL
lsof -i :6333  # Qdrant REST
lsof -i :6334  # Qdrant gRPC
```

Если порт занят:
- Остановите конфликтующий процесс: `kill -9 <PID>`
- Или измените порты в docker-compose.yml:
  ```yaml
  ports:
    - "5433:5432"  # Внешний порт 5433 вместо 5432
  ```

---

### Проблема: Контейнеры запускаются, но падают сразу

**Симптомы:**
```bash
docker compose ps
# STATE: Restarting
```

**Решения:**

**1. Проверка логов:**
```bash
docker compose logs postgres
docker compose logs qdrant
```

**2. Типичные ошибки:**

**Недостаточно памяти:**
```
FATAL:  could not map anonymous shared memory: Cannot allocate memory
```

Решение:
```bash
# Увеличьте Docker memory limit
# Docker Desktop → Settings → Resources → Memory → 4GB+
```

**Проблемы с volumes:**
```
ERROR: Cannot start service postgres: error while mounting volume
```

Решение:
```bash
# Удалите старые volumes
docker compose down -v

# Пересоздайте
docker compose up -d
```

---

### Проблема: `docker compose` команда не найдена

**Симптомы:**
```bash
docker compose
# -bash: docker: command not found
```

**Решения:**

**Для старых версий Docker используйте `docker-compose` (с дефисом):**
```bash
docker-compose --version

# Если не установлен:
# macOS
brew install docker-compose

# Linux
sudo apt-get install docker-compose

# Или используйте Docker Compose V2 (встроен в Docker 20.10+)
docker compose version
```

---

## PostgreSQL

### Проблема: PostgreSQL не принимает подключения

**Симптомы:**
```
psql: error: connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused
```

**Решения:**

**1. Проверка что контейнер запущен и healthy:**
```bash
docker compose ps postgres
```

Должен показывать `Up` и `healthy` (не `starting`).

---

**2. Проверка логов:**
```bash
docker compose logs postgres --tail=100 | grep -i error
```

**3. Типичные ошибки:**

**"database system is starting up":**
- Подождите 10-30 секунд, PostgreSQL еще загружается
- Проверьте через `docker compose ps` когда статус станет `healthy`

**"FATAL: password authentication failed":**
```bash
# Проверьте переменные окружения
docker compose exec postgres env | grep POSTGRES

# Должны совпадать с вашим .env файлом
```

Решение:
```bash
# Пересоздайте контейнер с правильными credentials
docker compose down -v  # ВАЖНО: -v удалит данные!
docker compose up -d
```

---

### Проблема: Нет прав на запись в PostgreSQL

**Симптомы:**
```
ERROR: permission denied for table memories
```

**Решения:**

**1. Проверка пользователя:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "\du"
```

Пользователь `cipher` должен иметь права `Superuser` или `Create DB`.

---

**2. Если нет прав, дайте их:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "ALTER USER cipher CREATEDB;"
```

---

### Проблема: PostgreSQL занимает много места

**Симптомы:**
```bash
docker exec -it cipher-postgres du -sh /var/lib/postgresql/data
# 5.0G
```

**Решения:**

**1. Vacuum и анализ:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "VACUUM FULL; ANALYZE;"
```

**2. Очистка старых WAL файлов:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "SELECT pg_wal_replay_pause();"
docker exec -it cipher-postgres psql -U cipher -d cipher -c "SELECT pg_wal_replay_resume();"
```

**3. Архивация и удаление старых данных:**
```bash
# Создайте backup перед удалением
docker exec -it cipher-postgres pg_dump -U cipher cipher > backup.sql

# Удалите старые записи (например, старше 6 месяцев)
docker exec -it cipher-postgres psql -U cipher -d cipher -c "DELETE FROM memories WHERE created_at < NOW() - INTERVAL '6 months';"

# Vacuum для освобождения места
docker exec -it cipher-postgres psql -U cipher -d cipher -c "VACUUM FULL;"
```

---

## Qdrant

### Проблема: Qdrant не отвечает на запросы

**Симптомы:**
```bash
curl http://localhost:6333/healthz
# curl: (7) Failed to connect to localhost port 6333: Connection refused
```

**Решения:**

**1. Проверка контейнера:**
```bash
docker compose ps qdrant
```

**2. Проверка логов:**
```bash
docker compose logs qdrant --tail=50
```

**Типичные ошибки:**

**"address already in use":**
```bash
# Найдите процесс на порту 6333
lsof -i :6333

# Остановите его
kill -9 <PID>

# Перезапустите Qdrant
docker compose restart qdrant
```

**"failed to create collection":**
```bash
# Проверьте storage volume
docker volume inspect qdrant_storage

# Если проблемы с правами:
docker compose down
docker volume rm qdrant_storage
docker compose up -d
```

---

### Проблема: Dimension mismatch error

**Симптомы:**
```
ERROR: Vector dimension mismatch: expected 1024, got 1536
```

**Причина:** `VECTOR_STORE_DIMENSION` не совпадает с `embedding.dimensions` в cipher.yml

**Решения:**

**1. Проверьте размерности:**
```bash
# cipher.yml
grep -A 4 'embedding:' ~/.cipher/cipher.yml | grep dimensions

# Environment variable
echo $VECTOR_STORE_DIMENSION

# Claude Code config
jq '.mcpServers.cipher.env.VECTOR_STORE_DIMENSION' ~/.claude.json
```

**2. Если не совпадают, синхронизируйте:**
```bash
# Вариант 1: Измените VECTOR_STORE_DIMENSION
export VECTOR_STORE_DIMENSION="1536"  # Совпадает с OpenAI embeddings

# Вариант 2: Измените cipher.yml
# embedding:
#   dimensions: 1024  # Совпадает с VECTOR_STORE_DIMENSION
```

**3. Пересоздайте коллекцию в Qdrant:**
```bash
# Удалите старую коллекцию
curl -X DELETE http://localhost:6333/collections/cipher_memory

# При следующем запуске Cipher создаст коллекцию с правильной размерностью
```

---

### Проблема: Qdrant медленный поиск

**Симптомы:**
```bash
time curl -X POST http://localhost:6333/collections/cipher_memory/points/search ...
# real    0m5.234s  # > 1 секунды
```

**Решения:**

**1. Создайте индексы:**
```bash
curl -X PUT http://localhost:6333/collections/cipher_memory/index \
  -H "Content-Type: application/json" \
  -d '{
    "field_name": "created_at",
    "field_schema": "datetime"
  }'
```

**2. Оптимизируйте параметры поиска:**
```bash
# В cipher.yml
memoryOptions:
  maxSimilarResults: 5  # Меньше результатов = быстрее
  similarityThreshold: 0.85  # Выше порог = меньше кандидатов
```

**3. Увеличьте память для Qdrant:**
```yaml
# docker-compose.yml
services:
  qdrant:
    deploy:
      resources:
        limits:
          memory: 1G  # Было 512M
```

---

## Cipher установка и конфигурация

### Проблема: Cipher не устанавливается через npm

**Симптомы:**
```bash
npm install -g @byterover/cipher
# ERR! code EACCES
# ERR! syscall access
# ERR! path /usr/local/lib/node_modules
```

**Решения:**

❌ **НЕ используйте sudo!**

✅ **Настройте npm prefix:**
```bash
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.zshrc
source ~/.zshrc

# Теперь установите
npm install -g @byterover/cipher
```

---

### Проблема: cipher.yml environment variables не работают

**Симптомы:**
```
ERROR: Environment variable OLLAMA_BASE_URL is not defined
```

**Решения:**

**1. Проверьте что переменные экспортированы:**
```bash
env | grep OLLAMA_BASE_URL
```

Если пусто:
```bash
export OLLAMA_BASE_URL="http://localhost:11434"
```

**2. Для постоянного эффекта:**
```bash
echo 'export OLLAMA_BASE_URL="http://localhost:11434"' >> ~/.zshrc
source ~/.zshrc
```

**3. Или используйте явные значения в cipher.yml:**
```yaml
llm:
  baseURL: "http://localhost:11434"  # Без $
```

---

### Проблема: Cipher не может загрузить LLM model

**Симптомы:**
```
ERROR: Failed to load model qwen2.5-coder:7b
```

**Решения:**

**Для Ollama:**
```bash
# Проверьте что Ollama запущен
curl http://localhost:11434/api/tags

# Загрузите модель
ollama pull qwen2.5-coder:7b

# Проверьте что модель загружена
ollama list | grep qwen2.5-coder
```

**Для embedding models:**
```bash
ollama pull mxbai-embed-large
```

---

### Проблема: YAML syntax error в cipher.yml

**Симптомы:**
```
ERROR: Error parsing cipher.yml: yaml: line 15: mapping values are not allowed in this context
```

**Решения:**

**1. Проверка отступов (только пробелы!):**
```bash
# Найдите табы (плохо)
sed 's/\t/[TAB]/g' ~/.cipher/cipher.yml | grep '\[TAB\]'

# Замените табы на пробелы
sed -i 's/\t/  /g' ~/.cipher/cipher.yml
```

**2. Валидация YAML:**
```bash
python3 -c "import yaml, os; yaml.safe_load(open(os.path.expanduser('~/.cipher/cipher.yml')))"
```

**3. Используйте YAML linter:**
```bash
# Установите yamllint
pip3 install yamllint

# Проверьте файл
yamllint ~/.cipher/cipher.yml
```

---

## Claude Code и MCP

### Проблема: Claude Code не загружает MCP конфиг

**Симптомы:**
- MCP серверы не появляются в Claude Code
- Нет доступа к cipher tools

**Решения:**

**1. Проверка расположения конфига:**
```bash
# macOS - должен быть здесь:
ls -la ~/.claude.json

# Linux:
ls -la ~/.claude.json
```

**2. Валидация JSON:**
```bash
# macOS
python3 -m json.tool ~/.claude.json

# Если ошибка, найдите строку с проблемой
```

**3. Полный перезапуск Claude Code:**
```bash
# macOS
osascript -e 'quit app "Claude"'
killall Claude  # Если osascript не сработал
open -a Claude

# Linux
pkill -9 claude
claude
```

**4. Проверка прав на файл:**
```bash
# Файл должен быть readable
chmod 644 ~/.claude.json
```

---

### Проблема: MCP server "Failed to start"

**Симптомы:**
В Claude Code:
```
❌ cipher - Failed to start
```

**Решения:**

**1. Проверка логов:**
```bash
# macOS
tail -f ~/Library/Logs/Claude/mcp*.log

# Linux
tail -f ~/.config/Claude/logs/mcp*.log
```

**Типичные ошибки в логах:**

**"command not found: cipher":**
```bash
# Проверьте что cipher установлен
which cipher

# Если нет, используйте npx в конфиге:
{
  "command": "npx",
  "args": ["-y", "@byterover/cipher", "--mode", "mcp", ...]
}
```

**"Cannot find module cipher.yml":**
```bash
# Проверьте путь в args
jq '.mcpServers.cipher.args' ~/.claude.json

# Используйте абсолютный путь:
"--agent", "/Users/username/.cipher/cipher.yml"

# Или используйте ${HOME}:
"--agent", "${HOME}/.cipher/cipher.yml"
```

**"Environment variable X not set":**
```bash
# Добавьте переменные явно в env секцию конфига
```

---

### Проблема: Environment variables не пробрасываются в MCP

**Симптомы:**
Cipher запускается, но не может подключиться к БД из-за отсутствия env vars

**Причина:** Claude Code не загружает `~/.zshrc` автоматически

**Решения:**

**Вариант 1: Запуск Claude Code из терминала**
```bash
# macOS
open -a Claude

# Теперь переменные из shell будут доступны
```

**Вариант 2: Явные переменные в конфиге**
```json
{
  "mcpServers": {
    "cipher": {
      "env": {
        "CIPHER_PG_URL": "postgresql://cipher:password@localhost:5432/cipher",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        ...
      }
    }
  }
}
```

**Вариант 3: launchd environment (macOS)**
```bash
# Создайте ~/Library/LaunchAgents/environment.plist
launchctl setenv CIPHER_PG_URL "postgresql://..."
```

---

### Проблема: MCP tools не вызываются

**Симптомы:**
Claude отвечает, но не использует cipher tools

**Решения:**

**1. Проверьте что tools доступны:**
В Claude Code чате напишите:
```
Покажи мне список всех доступных MCP tools
```

Claude должен показать `cipher_memory_search`, `cipher_extract_and_operate_memory`, и т.д.

**2. Явно попросите использовать tool:**
```
Используй cipher_memory_search чтобы найти информацию про "test"
```

**3. Проверьте логи MCP сервера:**
```bash
tail -f ~/Library/Logs/Claude/mcp-cipher.log
```

---

## Performance и оптимизация

### Проблема: Медленные запросы к памяти

**Симптомы:**
`cipher_memory_search` занимает > 5 секунд

**Решения:**

**1. Оптимизация PostgreSQL:**
```sql
-- Создайте индексы
CREATE INDEX idx_memories_created_at ON memories(created_at);
CREATE INDEX idx_memories_updated_at ON memories(updated_at);

-- Анализ таблиц
ANALYZE memories;
```

**2. Оптимизация Qdrant:**
```bash
# Остановите контейнеры
docker compose down
# Запустите контейнеры (память указывается в docker-compose.yml)
docker compose up -d --scale qdrant=1
```

Затем укажите лимит памяти для сервиса qdrant в вашем `docker-compose.yml`:

```yaml
services:
  qdrant:
    deploy:
      resources:
        limits:
          memory: 1g
```

**3. Уменьшите количество результатов:**
```yaml
# cipher.yml
memoryOptions:
  maxSimilarResults: 3  # Было 5 или 10
```

---

### Проблема: Высокое использование памяти

**Симптомы:**
```bash
docker stats
# qdrant   1.5GB  # Слишком много
```

**Решения:**

**1. Ограничьте память в docker-compose.yml:**
```yaml
services:
  qdrant:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
```

**2. Очистите старые коллекции:**
```bash
curl -X DELETE http://localhost:6333/collections/old_collection
```

**3. Оптимизируйте индексы:**
```bash
curl -X POST http://localhost:6333/collections/cipher_memory/optimizer \
  -H "Content-Type: application/json" \
  -d '{"optimize": true}'
```

---

## Security и безопасность

### Проблема: Пароли в plain text в конфигах

**Решение:**

✅ **Используйте environment variable expansion:**

**Плохо:**
```json
{
  "env": {
    "CIPHER_PG_URL": "postgresql://cipher:YOUR_PASSWORD_HERE@localhost:5432/cipher"
  }
}
```

**Хорошо:**
```json
{
  "env": {
    "CIPHER_PG_URL": "${CIPHER_PG_URL}"
  }
}
```

```bash
# В ~/.zshrc
export CIPHER_PG_URL="postgresql://cipher:$(cat ~/.secrets/pg_password)@localhost:5432/cipher"
```

---

### Проблема: API ключи в git репозитории

**Симптомы:**
Случайно закоммитили `.env` или конфиг с ключами

**Решения:**

**1. Немедленно ротируйте ключи:**
- Anthropic: https://console.anthropic.com/settings/keys
- OpenAI: https://platform.openai.com/api-keys
- Voyage AI: https://dash.voyageai.com/api-keys

**2. Удалите из git history:**
```bash
# Используйте git-filter-repo
pip3 install git-filter-repo
git filter-repo --path .env --invert-paths --force

# Или BFG Repo-Cleaner
java -jar bfg.jar --delete-files .env
```

**3. Добавьте в .gitignore:**
```bash
echo ".env" >> .gitignore
echo ".claude.json" >> .gitignore
git add .gitignore
git commit -m "Add sensitive files to .gitignore"
```

---

### Проблема: PostgreSQL доступен из интернета

**Симптомы:**
```bash
netstat -an | grep 5432
# 0.0.0.0:5432  # Плохо! Слушает все интерфейсы
```

**Решения:**

**1. Ограничьте в docker-compose.yml:**
```yaml
services:
  postgres:
    ports:
      - "127.0.0.1:5432:5432"  # Только localhost
```

**2. Настройте firewall:**
```bash
# UFW (Ubuntu)
sudo ufw deny 5432

# iptables
sudo iptables -A INPUT -p tcp --dport 5432 -j DROP
sudo iptables -A INPUT -s 127.0.0.1 -p tcp --dport 5432 -j ACCEPT
```

---

## Диагностика в одну команду

Быстрая проверка всех компонентов:

```bash
#!/bin/bash
echo "=== Cipher Setup Diagnostic ==="
echo

echo "1. Docker:"
docker --version && echo "✅ Docker installed" || echo "❌ Docker not found"

echo
echo "2. Docker Compose:"
docker compose version && echo "✅ Docker Compose V2" || docker-compose --version && echo "✅ Docker Compose V1" || echo "❌ Docker Compose not found"

echo
echo "3. PostgreSQL:"
docker compose ps | grep postgres | grep healthy && echo "✅ PostgreSQL healthy" || echo "❌ PostgreSQL not healthy"
psql "postgresql://cipher:${POSTGRES_PASSWORD}@localhost:5432/cipher" -c "SELECT 1" > /dev/null 2>&1 && echo "✅ PostgreSQL connection OK" || echo "❌ PostgreSQL connection failed"

echo
echo "4. Qdrant:"
docker compose ps | grep qdrant | grep healthy && echo "✅ Qdrant healthy" || echo "❌ Qdrant not healthy"
curl -s http://localhost:6333/healthz > /dev/null && echo "✅ Qdrant API OK" || echo "❌ Qdrant API failed"

echo
echo "5. Cipher:"
which cipher > /dev/null && echo "✅ Cipher installed" || echo "❌ Cipher not found"
[ -f ~/.cipher/cipher.yml ] && echo "✅ cipher.yml exists" || echo "❌ cipher.yml not found"
python3 -c "import os, yaml; yaml.safe_load(open(os.path.expanduser('~/.cipher/cipher.yml')))" 2>/dev/null && echo "✅ cipher.yml valid" || echo "❌ cipher.yml invalid"

echo
echo "6. Claude Code:"
[ -f ~/.claude.json ] && echo "✅ Config exists" || echo "❌ Config not found"
python3 -m json.tool ~/.claude.json > /dev/null 2>&1 && echo "✅ Config valid JSON" || echo "❌ Config invalid JSON"

echo
echo "=== End of Diagnostic ==="
```

Сохраните как `diagnose-cipher.sh` и запустите:
```bash
chmod +x diagnose-cipher.sh
./diagnose-cipher.sh
```

---

## Получение помощи

Если проблема не решена:

1. 📝 Соберите логи:
```bash
# Docker logs
docker compose logs > cipher-logs.txt

# Claude Code logs (macOS)
tar -czf claude-logs.tar.gz ~/Library/Logs/Claude/

# System info
uname -a > system-info.txt
docker --version >> system-info.txt
```

2. 🔍 Опишите проблему:
- Что вы пытались сделать?
- Какой результат ожидали?
- Что произошло вместо этого?
- Какие сообщения об ошибках видели?

3. 💬 Создайте issue:
- [MAP Framework GitHub](https://github.com/your-repo/map-framework/issues)
- [Cipher GitHub](https://github.com/campfirein/cipher/issues)

4. 🤝 Сообщество:
- [Cipher Discord](https://discord.gg/byterover)
- [Claude Code Discord](https://discord.gg/anthropic)

---

## Дополнительные ресурсы

- 📚 [Официальная документация Cipher](https://docs.byterover.dev/cipher/troubleshooting)
- 💻 [FAQ по Qdrant](https://qdrant.tech/documentation/faq/)
- 🔧 [PostgreSQL Performance Tips](https://wiki.postgresql.org/wiki/Performance_Optimization)
- 🐳 [Docker troubleshooting guide](https://docs.docker.com/config/daemon/#troubleshoot-the-daemon)
