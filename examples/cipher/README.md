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

Конфигурация Docker Compose с двумя сервисами:

- **Qdrant** (порты 6333/6334) - векторная база данных для embeddings
- **PostgreSQL** (порт 5432) - реляционная БД для метаданных

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

Если порты 5432, 6333, или 6334 заняты другими процессами:

```bash
# Проверьте какой процесс использует порт
lsof -i :5432
lsof -i :6333

# Либо измените порты в docker-compose.yml
```

### Контейнеры не запускаются

```bash
# Проверьте логи
docker compose logs postgres
docker compose logs qdrant

# Проверьте что Docker daemon запущен
docker ps
```

Полное руководство: [docs/MCP-CIPHER-QDRANT-SETUP.md](../../docs/MCP-CIPHER-QDRANT-SETUP.md)
