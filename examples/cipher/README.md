# Cipher MCP Infrastructure Setup

Эта директория содержит примеры конфигурации для развертывания инфраструктуры Cipher MCP (Qdrant + PostgreSQL) в Docker.

## Быстрый старт

1. **Скопируйте файлы к себе:**
```bash
cp examples/cipher/docker-compose.yml ~/cipher-infra/
cp examples/cipher/.env.example ~/cipher-infra/.env
cd ~/cipher-infra/
```

2. **Настройте окружение:**
```bash
# Сгенерируйте безопасный пароль
openssl rand -base64 24

# Отредактируйте .env и установите пароль
nano .env
```

3. **Запустите инфраструктуру:**
```bash
docker compose --env-file .env up -d
```

4. **Проверьте статус:**
```bash
docker compose ps
```

## Что включено

### docker-compose.yml

Конфигурация Docker Compose с тремя сервисами:

- **Qdrant** (порты 6333/6334) - векторная база данных для embeddings
- **PostgreSQL** (порт 5432) - реляционная БД для метаданных
- **Neo4j** (порты 7687/7474) - граф БД для knowledge graph (опционально)

### .env.example

Шаблон переменных окружения с комментариями и советами по безопасности.

## Строки подключения для Cipher MCP

После запуска инфраструктуры, используйте эти строки подключения в конфигурации Cipher MCP:

**PostgreSQL:**
```
postgresql://cipher:your_secure_password_here@localhost:5432/cipher
```

**Qdrant:**
```
http://localhost:6333
```

**Neo4j (опционально):**
```
bolt://localhost:7687
```

### Доступ к Neo4j Browser

После запуска Neo4j откройте в браузере:
```
http://localhost:7474
```

**Credentials:**
- Username: `neo4j` (или значение из NEO4J_USER)
- Password: ваш пароль из `.env` файла (NEO4J_PASSWORD)

**APOC Plugin:** Автоматически установлен для расширенных graph операций.

## Следующие шаги

После развертывания инфраструктуры:

1. Установите Cipher MCP (см. [docs/MCP-CIPHER-QDRANT-SETUP.md](../../docs/MCP-CIPHER-QDRANT-SETUP.md))
2. Настройте Claude Desktop конфигурацию
3. Протестируйте подключение

## Безопасность

⚠️ **ВАЖНО:**
- Никогда не коммитьте файл `.env` в git!
- Используйте сильные пароли (минимум 16 символов)
- Добавьте `.env` в `.gitignore`

## Troubleshooting

### Порты заняты

Если порты 5432, 6333, 6334, 7474, или 7687 заняты другими процессами:

```bash
# Проверьте какой процесс использует порт
lsof -i :5432   # PostgreSQL
lsof -i :6333   # Qdrant REST
lsof -i :6334   # Qdrant gRPC
lsof -i :7474   # Neo4j Browser
lsof -i :7687   # Neo4j Bolt

# Либо измените порты в docker-compose.yml
```

### Контейнеры не запускаются

```bash
# Проверьте логи
docker compose logs postgres
docker compose logs qdrant
docker compose logs neo4j

# Проверьте что Docker daemon запущен
docker ps
```

### Neo4j требует много памяти

По умолчанию Neo4j настроен на 512MB-2GB heap memory. Если у вас мало RAM:

```yaml
# В docker-compose.yml измените:
NEO4J_dbms_memory_heap_initial__size: 256m
NEO4J_dbms_memory_heap_max__size: 512m
```

Полное руководство: [docs/MCP-CIPHER-QDRANT-SETUP.md](../../docs/MCP-CIPHER-QDRANT-SETUP.md)
