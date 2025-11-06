# Полное руководство: Настройка Cipher + Qdrant + PostgreSQL для MAP Framework

Этот документ описывает установку и настройку MCP сервера Cipher с backend'ом Qdrant (векторная БД) и PostgreSQL (реляционная БД) для использования с MAP Framework и Claude Code.

## Что это такое?

### Cipher MCP Server

**Cipher** - это Model Context Protocol (MCP) сервер, который предоставляет AI агентам (таким как Claude) возможность работать с долгосрочной памятью и reasoning traces.

**Ключевые возможности:**
- 🧠 **Dual memory system**: Хранение фактов (knowledge memory) и reasoning traces (reflection memory)
- 🔍 **Semantic search**: Поиск по смыслу, а не по ключевым словам
- 🔄 **Cross-project learning**: Знания доступны между разными проектами
- 📊 **Structured reasoning**: Извлечение и анализ цепочек рассуждений
- 🎯 **MAP integration**: Специально оптимизирован для MAP Framework workflows

---

### Qdrant

**Qdrant** - высокопроизводительная векторная база данных для semantic search.

**В нашей установке:**
- Хранит embeddings (векторные представления) знаний
- Обеспечивает быстрый semantic поиск
- Работает в Docker контейнере

---

### PostgreSQL

**PostgreSQL** - надежная реляционная БД для structured data.

**В нашей установке:**
- Хранит метаданные memory entries
- Хранит reasoning traces
- Обеспечивает ACID транзакции

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code / MAP Framework             │
│                                                             │
│  User interacts with Claude via chat interface             │
└────────────────────┬────────────────────────────────────────┘
                     │ MCP Protocol (stdio)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      Cipher MCP Server                      │
│                                                             │
│  • cipher_memory_search                                     │
│  • cipher_extract_and_operate_memory                        │
│  • cipher_extract_reasoning_steps                           │
│  • cipher_store_reasoning_memory                            │
│  • cipher_search_reasoning_patterns                         │
└─────────────┬──────────────────────────┬────────────────────┘
              │                          │
              │ PostgreSQL               │ Qdrant
              │ connection               │ HTTP API
              ▼                          ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│    PostgreSQL (Docker)   │  │      Qdrant (Docker)         │
│                          │  │                              │
│  • Metadata storage      │  │  • Vector embeddings         │
│  • Reasoning traces      │  │  • Semantic search           │
│  • Sessions              │  │  • Collections               │
└──────────────────────────┘  └──────────────────────────────┘
```

---

## Зачем это нужно для MAP Framework?

MAP Framework использует Cipher для реализации **ACE (Agentic Context Engineering)** - системы непрерывного обучения:

1. **Playbook bullets → Cipher**: Высококачественные паттерны (helpful_count >= 5) автоматически синхронизируются
2. **Cross-project patterns**: Знания из одного проекта доступны в другом
3. **Reasoning memory**: Сохранение успешных reasoning traces для future reference
4. **Deduplification**: Автоматическая проверка дубликатов через semantic search
5. **Continuous improvement**: Каждый MAP workflow обогащает knowledge base

---

## Быстрый старт (TL;DR)

Для опытных пользователей:

```bash
# 1. Скопируйте примеры конфигурации
cp -r examples/cipher ~/cipher-setup
cd ~/cipher-setup

# 2. Настройте .env
cp .env.example .env
nano .env  # Установите безопасный пароль

# 3. Запустите инфраструктуру
docker compose up -d

# 4. Установите Cipher
npm install -g @byterover/cipher

# 5. Создайте cipher.yml
mkdir -p ~/.cipher
cp /path/to/cipher.yml.example ~/.cipher/cipher.yml
nano ~/.cipher/cipher.yml  # Настройте LLM провайдер

# 6. Настройте Claude Code
nano ~/.claude.json
# Добавьте cipher MCP server конфигурацию

# 7. Перезапустите Claude Code
osascript -e 'quit app "Claude"'
open -a Claude

# 8. Проверьте работоспособность
# В Claude Code чате: "Используй cipher_memory_search для поиска test"
```

Если что-то пошло не так, смотрите детальные инструкции ниже.

---

## Пошаговое руководство

### Шаг 1: Подготовка инфраструктуры (Docker)

Установите Qdrant и PostgreSQL в Docker контейнерах.

**Время:** ~10 минут
**Документ:** [examples/cipher/README.md](../examples/cipher/README.md)

**Что вы сделаете:**
- Настроите docker-compose.yml с двумя сервисами
- Создадите .env файл с безопасными credentials
- Запустите контейнеры и проверите health checks

---

### Шаг 2: Установка Cipher

Установите Cipher CLI через npm.

**Время:** ~5 минут
**Документ:** [cipher-setup-guide/02-cipher-installation.md](cipher-setup-guide/02-cipher-installation.md)

**Что вы сделаете:**
- Установите Node.js и npm (если нужно)
- Установите @byterover/cipher глобально или локально
- Проверите что команда `cipher` доступна

---

### Шаг 3: Конфигурация Cipher (cipher.yml)

Настройте LLM провайдер, embeddings, и memory options.

**Время:** ~15 минут
**Документ:** [cipher-setup-guide/03-cipher-configuration.md](cipher-setup-guide/03-cipher-configuration.md)

**Что вы сделаете:**
- Выберете LLM провайдер (Ollama, Anthropic, OpenAI, Gemini)
- Настроите embedding model (для semantic search)
- Настроите memory опции (similarity threshold, etc.)
- Настроите environment variables

---

### Шаг 4: Настройка Claude Code MCP

Подключите Cipher как MCP сервер в Claude Code.

**Время:** ~10 минут
**Документ:** [cipher-setup-guide/04-claude-code-setup.md](cipher-setup-guide/04-claude-code-setup.md)

**Что вы сделаете:**
- Отредактируете `.claude.json`
- Настроите environment variables для MCP сервера
- Перезапустите Claude Code
- Проверите что Cipher подключен

---

### Шаг 5: Проверка работоспособности

Убедитесь что все компоненты работают корректно.

**Время:** ~10 минут
**Документ:** [cipher-setup-guide/05-verification.md](cipher-setup-guide/05-verification.md)

**Что вы сделаете:**
- Проверите PostgreSQL и Qdrant health checks
- Протестируете Cipher в standalone и MCP режимах
- Проверите доступность MCP tools в Claude Code
- Сохраните тестовую memory и найдете её через search

---

### Шаг 6: Troubleshooting (если нужно)

Если что-то не работает, смотрите расширенный troubleshooting guide.

**Документ:** [cipher-setup-guide/06-troubleshooting.md](cipher-setup-guide/06-troubleshooting.md)

**Охватывает:**
- Docker и инфраструктурные проблемы
- PostgreSQL connection issues
- Qdrant dimension mismatch errors
- Cipher installation и configuration проблемы
- Claude Code MCP integration issues
- Performance optimization
- Security best practices

---

## Системные требования

### Минимальные

- **OS**: macOS 11+, Ubuntu 20.04+, Windows 10+ (с WSL2)
- **RAM**: 4GB свободной памяти
- **Disk**: 5GB свободного места
- **Docker**: 20.10+ (с Docker Compose V2)
- **Node.js**: 16.x+
- **npm**: 8.x+

### Рекомендуемые

- **RAM**: 8GB+
- **Disk**: 10GB+ (для больших knowledge bases)
- **SSD**: Для лучшей производительности Qdrant

---

## Опциональные компоненты

### Ollama (для локальных LLM)

Если вы хотите использовать локальные LLM вместо API:

```bash
# macOS
brew install ollama

# Запустите
ollama serve

# Загрузите модели
ollama pull qwen2.5-coder:7b
ollama pull mxbai-embed-large
```

**Документация:** https://ollama.ai/download

---

### LLM API Keys

Получите API ключ от одного из провайдеров:

- **Anthropic Claude**: https://console.anthropic.com/settings/keys
- **OpenAI GPT**: https://platform.openai.com/api-keys
- **Google Gemini**: https://makersuite.google.com/app/apikey
- **Voyage AI** (embeddings): https://dash.voyageai.com/api-keys

---

## Что дальше?

После успешной установки:

### 1. Интеграция с MAP workflows

Cipher автоматически используется в MAP Framework slash commands:
- `/map-feature` - Curator синхронизирует bullets в Cipher
- `/map-debug` - Reflector ищет похожие проблемы в Cipher
- `/map-refactor` - Predictor использует Cipher для impact analysis

### 2. Ручное использование

В Claude Code чате вы можете явно использовать Cipher tools:

**Сохранить знание:**
```
Запомни: "FastAPI middleware порядок имеет значение - регистрация снизу вверх, выполнение сверху вниз"
```

**Поиск:**
```
Найди в моей memory все что связано с FastAPI middleware
```

**Reasoning traces:**
```
Извлеки мои reasoning steps из предыдущего ответа и сохрани как паттерн
```

### 3. Мониторинг knowledge base

```bash
# Проверка количества знаний
docker exec -it cipher-postgres psql -U cipher -d cipher -c "SELECT COUNT(*) FROM memories;"

# Проверка векторов в Qdrant
curl http://localhost:6333/collections/cipher_memory | jq '.result.points_count'
```

### 4. Backup и maintenance

```bash
# Backup PostgreSQL
docker exec -it cipher-postgres pg_dump -U cipher cipher > cipher-backup-$(date +%Y%m%d).sql

# Backup Qdrant (volume)
docker run --rm -v qdrant_storage:/data -v $(pwd):/backup alpine tar czf /backup/qdrant-backup-$(date +%Y%m%d).tar.gz /data
```

---

## FAQ

### Q: Нужен ли мне Cipher для MAP Framework?

**A:** Cipher опционален. MAP Framework работает без него, но Cipher добавляет:
- Cross-project learning (знания переносятся между проектами)
- Автоматическую дедупликацию playbook bullets
- Reasoning memory для complex debugging
- Semantic search по историческим решениям

**Рекомендация:** Начните с базового MAP Framework, добавьте Cipher позже когда почувствуете потребность в cross-project knowledge.

---

### Q: Какой LLM провайдер выбрать?

**A:** Зависит от ваших приоритетов:

| Провайдер | Плюсы | Минусы | Рекомендация |
|-----------|-------|--------|--------------|
| **Ollama** | Бесплатно, приватность, быстро на мощном железе | Требует мощное железо, качество ниже API моделей | Dev на мощной машине |
| **Anthropic Claude** | Отличное reasoning, большой контекст (200K) | Платно (~$3/M tokens) | Production, complex reasoning |
| **OpenAI GPT** | Хорошее качество, широкая поддержка | Платно (~$2.5/M tokens) | Balanced choice |
| **Gemini** | Дешево (~$0.35/M tokens), большой контекст | Качество варьируется | Budget-conscious |

**Наша рекомендация для MAP Framework:** Anthropic Claude Sonnet + Voyage embeddings (лучшее качество reasoning).

---

### Q: Сколько места займет knowledge base?

**A:** Зависит от использования:

- **Small project** (~100 knowledge entries): ~50MB PostgreSQL, ~100MB Qdrant
- **Medium project** (~1000 entries): ~200MB PostgreSQL, ~500MB Qdrant
- **Large project** (~10000 entries): ~1GB PostgreSQL, ~3GB Qdrant

**Совет:** Регулярно архивируйте старые знания (>6 месяцев).

---

### Q: Как удалить старые знания?

**A:**
```bash
# Удалить знания старше 6 месяцев
docker exec -it cipher-postgres psql -U cipher -d cipher -c "DELETE FROM memories WHERE created_at < NOW() - INTERVAL '6 months';"

# Пересоздать Qdrant коллекцию (удалит все vectors)
curl -X DELETE http://localhost:6333/collections/cipher_memory

# При следующем использовании Cipher пересоздаст коллекцию
```

---

### Q: Можно ли использовать Cipher без Docker?

**A:** Да, но сложнее:

1. Установите PostgreSQL и Qdrant нативно на хосте
2. Настройте connection strings в cipher.yml
3. Убедитесь что сервисы запускаются при старте системы

**Рекомендация:** Используйте Docker для простоты maintenance.

---

### Q: Как обновить Cipher?

**A:**
```bash
# Глобальная установка
npm update -g @byterover/cipher

# Проверка версии
cipher --version

# Перезапустите Claude Code после обновления
```

---

### Q: Безопасно ли хранить API ключи в .claude.json?

**A:** Относительно безопасно (файл доступен только вашему пользователю), но лучше использовать environment variable expansion:

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
  }
}
```

```bash
# В ~/.zshrc
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Известные ограничения

1. **macOS ARM64 (M1/M2/M3)**: Cipher UI сборка в Docker может быть нестабильной. Используйте `--build-arg BUILD_UI=false` или npm установку.

2. **Windows WSL2**: Требуется WSL2 с Docker Desktop. WSL1 не поддерживается.

3. **Memory limits**: Qdrant может потреблять значительную память (>500MB) при больших коллекциях. Настройте resource limits в docker-compose.yml.

4. **Embedding dimensions**: Нельзя изменить размерность embeddings после создания Qdrant коллекции. Придется пересоздать коллекцию (потеря данных).

5. **Concurrent writes**: PostgreSQL может показывать `deadlock detected` при очень высокой нагрузке. Используйте retry logic или уменьшите concurrency.

---

## Дополнительные ресурсы

### Официальная документация

- 📚 [Cipher Documentation](https://docs.byterover.dev/cipher)
- 💻 [Cipher GitHub](https://github.com/campfirein/cipher)
- 🔍 [Qdrant Documentation](https://qdrant.tech/documentation/)
- 🐘 [PostgreSQL Documentation](https://www.postgresql.org/docs/)

### MAP Framework

- 📖 [MAP Framework README](../README.md)
- ⚙️ [MAP Framework INSTALL.md](INSTALL.md)
- 🎯 [Playbook-Cipher Integration](PLAYBOOK-CIPHER-INTEGRATION.md)
- 🏗️ [MAP Architecture](ARCHITECTURE.md)

### Community

- 💬 [Cipher Discord](https://discord.gg/byterover)
- 🤝 [MAP Framework Discussions](https://github.com/your-repo/map-framework/discussions)

---

## Changelog

### 2025-11-06 - Initial Release
- Создана полная документация по установке Cipher + Qdrant + PostgreSQL
- Добавлены примеры конфигураций для разных LLM провайдеров
- Comprehensive troubleshooting guide
- Verification checklist
- Integration с MAP Framework workflows

---

## Лицензия и благодарности

- **MAP Framework**: MIT License
- **Cipher**: [Проверьте лицензию](https://github.com/campfirein/cipher/blob/main/LICENSE)
- **Qdrant**: Apache 2.0 License
- **PostgreSQL**: PostgreSQL License

**Благодарности:**
- Byterover team за создание Cipher
- Qdrant team за отличную векторную БД
- Anthropic за Claude и MCP protocol
- MAP Framework contributors

---

## Обратная связь

Нашли ошибку или есть предложения по улучшению документации?

- 🐛 [Создайте issue](https://github.com/your-repo/map-framework/issues)
- 💡 [Предложите улучшение](https://github.com/your-repo/map-framework/pulls)
- 💬 [Обсудите в Discussions](https://github.com/your-repo/map-framework/discussions)

---

**Happy coding with MAP Framework + Cipher! 🚀**
