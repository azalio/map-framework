# Конфигурация Cipher (cipher.yml)

После установки Cipher необходимо настроить файл конфигурации `cipher.yml`, который определяет как Cipher подключается к LLM, базам данных, и другим сервисам.

## Расположение конфигурационного файла

По умолчанию Cipher ищет `cipher.yml` в:
1. Текущей директории: `./cipher.yml`
2. Домашней директории: `~/.cipher/cipher.yml`
3. Явно указанном пути через флаг: `--agent /path/to/cipher.yml`

**Рекомендация:** Создайте `~/.cipher/cipher.yml` для глобальной конфигурации.

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
    You are an AI programming assistant focused on coding and reasoning tasks.

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

Cipher поддерживает множество LLM провайдеров. Выберите один:

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

---

#### Anthropic (Claude)

```yaml
llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  apiKey: $ANTHROPIC_API_KEY
  maxIterations: 50
```

**Преимущества:**
- ✅ Отличное качество reasoning
- ✅ Большой контекст (200K tokens)
- ✅ Надежность

**Требования:**
- API ключ от Anthropic
- Баланс на аккаунте

---

#### OpenAI (GPT)

```yaml
llm:
  provider: openai
  model: gpt-4o
  apiKey: $OPENAI_API_KEY
  maxIterations: 50
```

---

#### Gemini (Google)

```yaml
llm:
  provider: gemini
  model: gemini-2.0-flash-exp
  apiKey: $GEMINI_API_KEY
  maxIterations: 50
```

---

#### AWS Bedrock

```yaml
llm:
  provider: aws
  model: us.anthropic.claude-3-5-sonnet-20241022-v2:0
  maxIterations: 50
  aws:
    region: $AWS_REGION
    accessKeyId: $AWS_ACCESS_KEY_ID
    secretAccessKey: $AWS_SECRET_ACCESS_KEY
    sessionToken: $AWS_SESSION_TOKEN  # Опционально
```

---

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

---

#### Voyage AI (Рекомендуется для Anthropic пользователей)

```yaml
embedding:
  type: voyage
  model: voyage-3-large
  apiKey: $VOYAGE_API_KEY
  dimensions: 1024  # Поддерживает: 1024, 512, 256, 2048
```

---

#### OpenAI Embeddings

```yaml
embedding:
  type: openai
  model: text-embedding-3-small
  apiKey: $OPENAI_API_KEY
  dimensions: 1536
```

---

#### Gemini Embeddings

```yaml
embedding:
  type: gemini
  model: text-embedding-004
  apiKey: $GEMINI_API_KEY
```

---

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

Кастомизация базового поведения Cipher:

```yaml
systemPrompt:
  enabled: true
  content: |
    You are an AI programming assistant integrated with MAP Framework.
    You excel at:
    - Writing clean, maintainable code
    - Debugging and problem-solving with systematic approach
    - Code review with security awareness
    - Explaining complex technical concepts clearly
    - Reasoning through multi-step challenges

    Guidelines:
    - Always validate inputs and handle errors gracefully
    - Consider security implications in your solutions
    - Provide code examples when helpful
    - Break down complex problems into steps
```

**Совет:** Адаптируйте prompt под свой workflow. Для MAP Framework упомяните ACE patterns и structured thinking.

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
    You are a helpful AI assistant for coding tasks.

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
export CIPHER_PG_URL="postgresql://cipher:secure_password@localhost:5432/cipher"
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1024"
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
```

---

### Пример 2: Anthropic Claude + Voyage embeddings

**Для кого:** Профессиональные разработчики, приоритет качество > стоимость

**cipher.yml:**
```yaml
mcpServers: {}

llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  apiKey: $ANTHROPIC_API_KEY
  maxIterations: 50

embedding:
  type: voyage
  model: voyage-3-large
  apiKey: $VOYAGE_API_KEY
  dimensions: 1024

systemPrompt:
  enabled: true
  content: |
    You are an expert AI programming assistant integrated with MAP Framework.
    Focus on clean code, security, and maintainability.

memoryOptions:
  similarityThreshold: 0.80
  useLLMDecisions: true  # Используем Claude для решений
  confidenceThreshold: 0.7
  maxSimilarResults: 10  # Больше контекста
  enableBatchProcessing: true
  enableDeleteOperations: true
```

**Environment variables:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export VOYAGE_API_KEY="pa-..."
export CIPHER_PG_URL="postgresql://cipher:secure_password@localhost:5432/cipher"
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1024"
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
```

---

### Пример 3: Гибридная конфигурация (Ollama LLM + OpenAI embeddings)

**Для кого:** Баланс между стоимостью и качеством

**cipher.yml:**
```yaml
mcpServers: {}

llm:
  provider: ollama
  model: qwen2.5-coder:7b
  maxIterations: 50
  baseURL: $OLLAMA_BASE_URL

embedding:
  type: openai
  model: text-embedding-3-small
  apiKey: $OPENAI_API_KEY
  dimensions: 1536  # Обратите внимание на другую размерность!

systemPrompt:
  enabled: true
  content: |
    You are an AI assistant specialized in software engineering.

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
export OPENAI_API_KEY="sk-..."
export CIPHER_PG_URL="postgresql://cipher:secure_password@localhost:5432/cipher"
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1536"  # Важно! Совпадает с embedding dimensions
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
```

⚠️ **Внимание:** `VECTOR_STORE_DIMENSION` должна совпадать с `embedding.dimensions`!

---

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

# Проверка API ключей (частично)
echo "ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:0:10}..."
echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."
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

---

## Troubleshooting

### Проблема: "Cannot find cipher.yml"

**Решение:**
```bash
# Проверьте путь
ls -la ~/.cipher/cipher.yml

# Создайте директорию если нужно
mkdir -p ~/.cipher

# Создайте конфигурацию из примера
cp /Users/azalio/gitroot/cipher/memAgent/cipher.yml ~/.cipher/
```

---

### Проблема: "Invalid YAML syntax"

**Решение:**
```bash
# Проверьте отступы (только пробелы, НЕ табы!)
sed 's/\t/[TAB]/g' ~/.cipher/cipher.yml | head -20

# Валидация через Python
python3 -c "import yaml, os; yaml.safe_load(open(os.path.expanduser('~/.cipher/cipher.yml')))"
```

---

### Проблема: "Environment variable not found"

**Симптомы:** `$OLLAMA_BASE_URL is not defined`

**Решение:**
```bash
# Убедитесь что переменные экспортированы
export OLLAMA_BASE_URL="http://localhost:11434"

# Для постоянного эффекта добавьте в ~/.zshrc или ~/.bashrc
echo 'export OLLAMA_BASE_URL="http://localhost:11434"' >> ~/.zshrc
source ~/.zshrc
```

---

### Проблема: "Dimension mismatch"

**Симптомы:** Qdrant ошибка о несоответствии размерности векторов

**Причина:** `VECTOR_STORE_DIMENSION` не совпадает с `embedding.dimensions` в cipher.yml

**Решение:**
```bash
# Проверьте cipher.yml
grep -A 4 'embedding:' ~/.cipher/cipher.yml | grep dimensions

# Проверьте environment variable
echo $VECTOR_STORE_DIMENSION

# Они должны совпадать! Если нет:
export VECTOR_STORE_DIMENSION="1024"  # Или 1536 для OpenAI embeddings
```

---

## Следующие шаги

После настройки `cipher.yml`:

1. ✅ Настройте Claude Code MCP integration → [04-claude-code-setup.md](04-claude-code-setup.md)
2. ✅ Проверьте работоспособность → [05-verification.md](05-verification.md)

## Дополнительные ресурсы

- 📚 [Официальная документация Cipher configuration](https://docs.byterover.dev/cipher/configuration)
- 💻 [Примеры конфигураций в репозитории](https://github.com/campfirein/cipher/tree/main/examples)
- 🔧 [Шаблоны для разных LLM провайдеров](https://github.com/campfirein/cipher/blob/main/memAgent/cipher.yml)
