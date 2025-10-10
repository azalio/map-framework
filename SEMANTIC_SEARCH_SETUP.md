# Semantic Search Setup для MAP Framework

## Быстрая установка

```bash
pip install -r requirements-semantic.txt
```

## Что это делает?

После установки зависимостей, MAP framework автоматически будет использовать **семантический поиск** вместо keyword matching для поиска relevant bullets в playbook.

### Преимущества:
- 🎯 **Поиск по смыслу**, не по ключевым словам
- 🧠 **Понимает синонимы**: "JWT signature" ≈ "token verification"
- 🔍 **Находит похожие паттерны** даже если нет точных совпадений
- ⚡ **Автоматическая дедупликация** похожих bullets (90% similarity)
- 💾 **Кеширование embeddings** для быстрой работы

### Как это работает?

1. При вызове `/map-feature` или других slash команд
2. Orchestrator agent создает `PlaybookManager()`
3. PlaybookManager автоматически загружает semantic search engine
4. `get_relevant_bullets()` использует cosine similarity вместо keyword matching

## Troubleshooting

### Проблема: 401 Unauthorized при загрузке модели

**Решение**: Выйти из HuggingFace CLI
```bash
hf auth logout
```

### Проблема: Keras 3 compatibility error

**Решение**: Уже исправлено! В `requirements-semantic.txt` включен `tf-keras` (Keras 2)

### Проблема: Semantic search не работает

**Проверка**:
```bash
python -c "from mapify_cli.playbook_manager import PlaybookManager; m = PlaybookManager(); print('✓' if m.semantic_engine else '✗')"
```

Должно вывести `✓ Semantic search enabled`

## Технические детали

- **Модель**: `all-MiniLM-L6-v2` (80MB, 384 dimensions)
- **Скорость**: ~3000 предложений/сек на CPU
- **Кеш**: `.claude/embeddings_cache/embeddings.pkl`
- **Fallback**: Если зависимости не установлены, автоматически используется keyword matching

## Как отключить?

Если нужно временно отключить:
```python
manager = PlaybookManager(use_semantic_search=False)
```

Но это не нужно делать через CLI - просто не устанавливай зависимости.
