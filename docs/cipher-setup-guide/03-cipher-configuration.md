# Конфигурация Cipher (cipher.yml)

После установки Cipher необходимо настроить файл конфигурации `cipher.yml`, который определяет как Cipher подключается к LLM, базам данных, и другим сервисам.

## Расположение конфигурационного файла

По умолчанию Cipher ищет `cipher.yml` в:

1. Текущей директории: `./cipher.yml`
2. Домашней директории: `~/.cipher/cipher.yml`
3. Явно указанном пути через флаг: `--agent /path/to/cipher.yml`

**Рекомендация:** Создайте `~/.cipher/cipher.yml` для глобальной конфигурации.

```bash
mkdir -p ~/.cipher/
touch ~/.cipher/cipher.yml
```

## Базовая структура cipher.yml

```yaml
# MCP серверы (опционально для MAP Framework)
mcpServers: {}

# LLM провайдер (ОБЯЗАТЕЛЬНО)
llm:
  provider: ollama
  model: qwen2.5-coder:7b
  maxIterations: 50
  baseURL: $OLLAMA_BASE_URL

# Embeddings для векторного поиска (ОБЯЗАТЕЛЬНО)
embedding:
  type: ollama
  model: mxbai-embed-large
  baseUrl: $OLLAMA_BASE_URL
  dimensions: 1024

# System prompt (опционально)
systemPrompt:
  enabled: true
  content: |
    You are Cipher, a knowledge management and reasoning system for MAP Framework.
    Extract actionable knowledge, identify patterns, support ACE learning cycles.

# Memory операции (опционально)
memoryOptions:
  similarityThreshold: 0.85
  useLLMDecisions: false
  confidenceThreshold: 0.7
  maxSimilarResults: 5
  enableBatchProcessing: true
  enableDeleteOperations: true
```

## Детальная конфигурация

### 1. LLM Provider Configuration

Cipher поддерживает множество LLM провайдеров. За дополнительной документацией обратитесь к документации cipher.

#### Ollama (Локальный LLM)

```yaml
llm:
  provider: ollama
  model: qwen2.5-coder:7b
  maxIterations: 50
  baseURL: $OLLAMA_BASE_URL  # http://localhost:11434
```

**Преимущества:**

- ✅ Полностью локальный, без затрат на API
- ✅ Приватность данных
- ✅ Быстрая работа на мощном железе

**Требования:**

- Ollama установлен и запущен
- Модель загружена: `ollama pull qwen2.5-coder:7b`

### 2. Embedding Configuration

Embeddings используются для векторного поиска в памяти.

#### Ollama Embeddings (Рекомендуется для локального использования)

```yaml
embedding:
  type: ollama
  model: mxbai-embed-large
  baseUrl: $OLLAMA_BASE_URL
  dimensions: 1024
```

**Требования:**

- Модель загружена: `ollama pull mxbai-embed-large`
- Размерность (1024) должна совпадать с `VECTOR_STORE_DIMENSION` в environment variables

### 3. Memory Options

Настройки для работы с memory системой:

```yaml
memoryOptions:
  # Порог similarity для UPDATE операций (0.0-1.0)
  # Если новая память > 85% похожа на существующую, она обновляет её
  similarityThreshold: 0.85

  # Использовать LLM для решений об ADD/UPDATE/DELETE
  # false = использовать similarity-based логику (быстрее, дешевле)
  useLLMDecisions: false

  # Минимальная уверенность для операций (0.0-1.0)
  confidenceThreshold: 0.7

  # Максимальное количество похожих memory для retrieve
  maxSimilarResults: 5

  # Обрабатывать несколько фактов batch'ом
  enableBatchProcessing: true

  # Разрешить DELETE операции
  enableDeleteOperations: true
```

**Рекомендации:**

- `similarityThreshold: 0.85` - высокий порог предотвращает дубликаты
- `useLLMDecisions: false` - экономит токены, достаточно similarity
- `confidenceThreshold: 0.7` - балансирует precision/recall

---

### 4. System Prompt

Кастомизация базового поведения Cipher для MAP Framework:

```yaml
systemPrompt:
  enabled: true
  content: |
    You are Cipher, a knowledge management and reasoning system integrated with MAP Framework.

    Your core capabilities:
    - Knowledge Management: Extract, store, and retrieve semantic knowledge across sessions
    - Reasoning Analysis: Capture and evaluate multi-step thought processes
    - Pattern Recognition: Identify recurring patterns in problem-solving approaches
    - Context Integration: Connect related knowledge from different domains

    MAP Framework Integration:
    - Support ACE (Acquire, Curate, Extract) learning patterns
    - Enable MAP (Modular Agentic Planner) workflow memory persistence
    - Facilitate cross-session knowledge continuity
    - Track reasoning evolution across tasks

    Operating Principles:
    - Semantic search over exact matches (use embeddings effectively)
    - Deduplication before storage (avoid redundant knowledge)
    - Quality scoring for knowledge entries (helpful_count matters)
    - Cross-project knowledge sharing (not project-siloed)

    Knowledge Domains You Handle:
    - Software architecture and design patterns
    - Technical documentation and specifications
    - Problem-solving approaches and trade-offs
    - Testing strategies and verification methods
    - Code quality principles and best practices
    - Security considerations and threat models
    - API design and integration patterns
    - System debugging and troubleshooting

    When Processing Interactions:
    1. Extract actionable knowledge (not conversational fluff)
    2. Identify reasoning patterns (not just conclusions)
    3. Classify domain appropriately (frontend, backend, devops, etc.)
    4. Score confidence accurately (0.0-1.0 scale)
    5. Suggest operation (ADD/UPDATE/DELETE/NONE) based on similarity

    Response Style:
    - Concise and structured (not verbose)
    - Focus on "why" and "when" (not just "what")
    - Include trade-offs and alternatives
    - Cite source when retrieving knowledge
    - Admit uncertainty rather than hallucinate
```

**Важно:** Этот промпт оптимизирован для MAP Framework, фокусируется на knowledge management и reasoning, а не только на программировании.

---

### 5. Knowledge Graph (опционально)

Knowledge Graph позволяет Cipher моделировать сложные связи между entities (advanced relationship modeling).

**По умолчанию выключен!** Если при запуске `cipher --mode mcp` видите:
```
INFO: [KG-Factory] Knowledge graph is disabled in environment
```

Это нормально. Knowledge Graph опционален.

#### Вариант 1: In-Memory (рекомендуется для начала)

Простой вариант без дополнительной инфраструктуры:

```bash
export KNOWLEDGE_GRAPH_ENABLED="true"
export KNOWLEDGE_GRAPH_TYPE="in-memory"
```

Или в cipher.yml (если поддерживается):

```yaml
knowledgeGraph:
  enabled: true
  type: in-memory
```

**Плюсы:**
- ✅ Не требует Neo4j
- ✅ Быстрый старт
- ✅ Достаточно для большинства случаев

**Минусы:**
- ❌ Данные не персистятся между перезапусками Cipher
- ❌ Ограниченные возможности graph queries

---

#### Вариант 2: Neo4j (production)

Для advanced relationship modeling и персистентности:

**Шаг 1:** Запустите Neo4j в Docker

**Способ 1: Через Docker Compose (рекомендуется)**

Neo4j уже включён в `examples/cipher/docker-compose.yml`:

```bash
cd examples/cipher/
cp .env.example .env

# Отредактируйте .env и установите пароли:
# - POSTGRES_PASSWORD
# - NEO4J_PASSWORD

# Запустите все сервисы (Qdrant + PostgreSQL + Neo4j)
docker compose up -d

# Проверьте статус
docker compose ps
```

**Способ 2: Отдельный контейнер**

```bash
docker run -d \
  --name cipher-neo4j \
  -p 7687:7687 \
  -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/secure_neo4j_password \
  -v neo4j_data:/data \
  neo4j:latest
```

**Шаг 2:** Настройте environment variables

```bash
export KNOWLEDGE_GRAPH_ENABLED="true"
export KNOWLEDGE_GRAPH_TYPE="neo4j"
export KNOWLEDGE_GRAPH_HOST="localhost"
export KNOWLEDGE_GRAPH_PORT="7687"
export KNOWLEDGE_GRAPH_USERNAME="neo4j"
export KNOWLEDGE_GRAPH_PASSWORD="secure_neo4j_password"
export KNOWLEDGE_GRAPH_DATABASE="neo4j"
```

**Или укажите полный URI:**

```bash
export KNOWLEDGE_GRAPH_URI="bolt://localhost:7687"
```

**Шаг 3:** Проверьте подключение

```bash
# Через Neo4j Browser
open http://localhost:7474

# Или через curl
curl http://localhost:7474
```

**Плюсы:**
- ✅ Персистентное хранилище
- ✅ Продвинутые graph queries (Cypher)
- ✅ Визуализация связей через Neo4j Browser
- ✅ Поддержка множественных баз (Neo4j 4.0+)

**Минусы:**
- ❌ Требует дополнительный Docker контейнер
- ❌ Больше памяти и CPU
- ❌ Сложнее настройка

---

#### Полный список KG переменных

| Переменная | Значение по умолчанию | Обязательна | Описание |
|------------|----------------------|-------------|----------|
| `KNOWLEDGE_GRAPH_ENABLED` | `false` | Нет | Включить knowledge graph |
| `KNOWLEDGE_GRAPH_TYPE` | `in-memory` | Нет | `in-memory` или `neo4j` |
| `KNOWLEDGE_GRAPH_HOST` | `localhost` | Для Neo4j | Хост Neo4j сервера |
| `KNOWLEDGE_GRAPH_PORT` | `7687` | Для Neo4j | Bolt протокол порт |
| `KNOWLEDGE_GRAPH_URI` | — | Для Neo4j | Полный URI (bolt://...) |
| `KNOWLEDGE_GRAPH_USERNAME` | `neo4j` | Для Neo4j | Пользователь Neo4j |
| `KNOWLEDGE_GRAPH_PASSWORD` | — | **Да (Neo4j)** | Пароль Neo4j |
| `KNOWLEDGE_GRAPH_DATABASE` | `neo4j` | Для Neo4j | Имя базы данных |

---

#### Пример использования с Claude Code MCP

В `~/.claude.json`:

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

        "KNOWLEDGE_GRAPH_ENABLED": "true",
        "KNOWLEDGE_GRAPH_TYPE": "in-memory"
      }
    }
  }
}
```

**Для Neo4j добавьте:**

```json
{
  "env": {
    ...
    "KNOWLEDGE_GRAPH_TYPE": "neo4j",
    "KNOWLEDGE_GRAPH_PASSWORD": "${KNOWLEDGE_GRAPH_PASSWORD}"
  }
}
```

---

**Когда использовать Knowledge Graph:**

✅ **Включить если:**
- Нужно моделировать сложные связи между entities
- Важна визуализация relationships
- Работаете с большим объёмом взаимосвязанных знаний
- Используете Neo4j для других задач в проекте

❌ **Не нужен если:**
- Просто храните facts и reasoning traces
- Semantic search через Qdrant достаточен
- Хотите минимальную конфигурацию
- Избегаете дополнительной инфраструктуры

**Совет:** Начните без knowledge graph. Включите позже если почувствуете ограничения semantic search.

---

## Environment Variables

Cipher использует environment variables для secrets и настроек подключения.

### Обязательные для MCP режима

```bash
# PostgreSQL connection string
export CIPHER_PG_URL="postgresql://cipher:ваш_пароль@localhost:5432/cipher"

# Qdrant connection
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1024"

# MCP server mode
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
```

### LLM API Keys

```bash
# Ollama (локальный)
export OLLAMA_BASE_URL="http://localhost:11434"

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."

# Gemini
export GEMINI_API_KEY="..."

# Voyage AI (для embeddings)
export VOYAGE_API_KEY="..."
```

### Опциональные

```bash
# Путь к database файлу
export CIPHER_DB_PATH="$HOME/.cipher/memory.db"

# Логирование
export CIPHER_LOG_LEVEL="info"  # debug, info, warn, error
```

---

## Примеры конфигураций

### Пример 1: Полностью локальная установка (Ollama)

**Для кого:** Пользователи с мощным локальным железом, заботящиеся о приватности

**cipher.yml:**

```yaml
mcpServers: {}

llm:
  provider: ollama
  model: qwen2.5-coder:7b
  maxIterations: 50
  baseURL: $OLLAMA_BASE_URL

embedding:
  type: ollama
  model: mxbai-embed-large
  baseUrl: $OLLAMA_BASE_URL
  dimensions: 1024

systemPrompt:
  enabled: true
  content: |
    You are Cipher, a knowledge management and reasoning system for MAP Framework.
    Extract actionable knowledge, identify patterns, support ACE learning cycles.

memoryOptions:
  similarityThreshold: 0.85
  useLLMDecisions: false
  confidenceThreshold: 0.7
  maxSimilarResults: 5
  enableBatchProcessing: true
  enableDeleteOperations: true
```

**Environment variables:**

```bash
export OLLAMA_BASE_URL="http://localhost:11434"
export CIPHER_PG_URL="postgresql://cipher:cipherpass@localhost:5432/cipher"
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1024"
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
```

## Проверка конфигурации

### Шаг 1: Валидация YAML

```bash
# Проверка синтаксиса YAML
python3 -c "import yaml, os; yaml.safe_load(open(os.path.expanduser('~/.cipher/cipher.yml')))"

# Или через yq (если установлен)
yq eval '.' ~/.cipher/cipher.yml
```

### Шаг 2: Проверка environment variables

```bash
# Проверка всех обязательных переменных
echo "CIPHER_PG_URL: ${CIPHER_PG_URL:-(not set)}"
echo "VECTOR_STORE_URL: ${VECTOR_STORE_URL:-(not set)}"
echo "VECTOR_STORE_DIMENSION: ${VECTOR_STORE_DIMENSION:-(not set)}"
echo "MCP_SERVER_MODE: ${MCP_SERVER_MODE:-(not set)}"
```

### Шаг 3: Тестовый запуск

```bash
# Запуск Cipher с вашей конфигурацией
cipher --mode mcp --agent ~/.cipher/cipher.yml

# Если успешно, вы увидите:
# - Cipher запускается без ошибок
# - Подключение к PostgreSQL успешно
# - Подключение к Qdrant успешно
# - MCP сервер слушает stdin/stdout
```

## Следующие шаги

После настройки `cipher.yml`:

1. ✅ Настройте Claude Code MCP integration → [04-claude-code-setup.md](04-claude-code-setup.md)
2. ✅ Проверьте работоспособность → [05-verification.md](05-verification.md)

## Дополнительные ресурсы

- 📚 [Официальная документация Cipher configuration](https://docs.byterover.dev/cipher/configuration)
- 💻 [Примеры конфигураций в репозитории](https://github.com/campfirein/cipher/tree/main/examples)
- 🔧 [Шаблоны для разных LLM провайдеров](https://github.com/campfirein/cipher/blob/main/memAgent/cipher.yml)
