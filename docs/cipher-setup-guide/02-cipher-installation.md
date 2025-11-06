# Установка Cipher через npm

Эта секция описывает установку MCP сервера Cipher для использования с MAP Framework и Claude Code.

## Prerequisites (Предварительные требования)

### Обязательные

- **Node.js**: версия 16.x или выше (рекомендуется 18.x LTS)
  ```bash
  node --version  # Проверка версии
  ```

- **npm**: версия 8.x или выше
  ```bash
  npm --version  # Проверка версии
  ```

### Опциональные

- **Docker и Docker Compose**: для контейнерной установки
- **pnpm**: для установки из исходников
- **API ключи** от LLM провайдеров (OpenAI, Anthropic, Gemini, или Qwen)
- **Git**: для установки из исходников

## Методы установки

### Метод 1: Глобальная установка через npm (Рекомендуется)

**Для кого:** Большинство пользователей, особенно при использовании с Claude Code и MAP Framework

**Команды:**
```bash
npm install -g @byterover/cipher
cipher --version
```

**Плюсы:**
- ✅ Доступна команда `cipher` из любой директории
- ✅ Простая интеграция с MCP серверами
- ✅ Автоматические обновления через npm
- ✅ Минимальная конфигурация

**Минусы:**
- ❌ Требует глобальные права установки
- ❌ Может конфликтовать с другими глобальными пакетами
- ❌ Одна версия на всю систему

---

### Метод 2: Локальная установка через npm

**Для кого:** Проекты с строгими требованиями к версиям или CI/CD окружения

**Команды:**
```bash
cd your-project
npm install @byterover/cipher
npx cipher --version
```

**Плюсы:**
- ✅ Изолированная установка на проект
- ✅ Разные версии для разных проектов
- ✅ Не требует глобальных прав
- ✅ Версия фиксируется в package.json

**Минусы:**
- ❌ Нужно использовать `npx cipher` вместо `cipher`
- ❌ Установка в каждом проекте
- ❌ Больше дискового пространства

---

### Метод 3: Docker контейнер

**Для кого:** Разработка, тестирование, или изолированные окружения

**Команды:**
```bash
git clone https://github.com/campfirein/cipher.git
cd cipher
cp .env.example .env

# Настроить .env файл с API ключами
nano .env

# Запустить Docker Compose
docker-compose up --build -d

# Проверить работоспособность
curl http://localhost:3000/health
```

**Плюсы:**
- ✅ Полная изоляция окружения
- ✅ Включает UI интерфейс (опционально)
- ✅ Проще для разработки и тестирования
- ✅ Не требует Node.js на хост-системе

**Минусы:**
- ❌ Требует Docker и Docker Compose
- ❌ Больше ресурсов (память, CPU)
- ❌ Сложнее для интеграции с MCP
- ❌ UI сборка пропускается на ARM64 по умолчанию

## Проверка установки

### Шаг 1: Проверка версии

```bash
cipher --version
```

**Ожидаемый вывод:**
```
cipher version x.x.x (или информация о версии)
```

**Что проверяется:** Успешная установка и доступность команды cipher

---

### Шаг 2: Проверка справки

```bash
cipher --help
```

**Ожидаемый вывод:**
```
Вывод справки с доступными командами и опциями
```

**Что проверяется:** Работоспособность CLI интерфейса

---

### Шаг 3: Проверка MCP режима

```bash
cipher --mode mcp
```

**Ожидаемый вывод:**
```
Запуск в MCP режиме (не должно быть ошибок подключения)
```

**Что проверяется:** MCP режим для интеграции с Claude Code

---

### Шаг 4: Проверка интерактивного режима

```bash
echo 'test' | cipher 'analyze this'
```

**Ожидаемый вывод:**
```
Ответ от LLM (требуется настроенный API ключ)
```

**Что проверяется:** Интерактивный режим с stdin

## Устранение неполадок (Troubleshooting)

### Проблема 1: Команда 'cipher' не найдена

**Симптомы:** После глобальной установки команда `cipher` не распознается

**Решение:**
```bash
# 1. Проверьте PATH
echo $PATH | grep npm

# 2. Найдите npm bin директорию
npm config get prefix

# 3. Добавьте в PATH (временно)
export PATH="$(npm config get prefix)/bin:$PATH"

# 4. Для постоянного эффекта добавьте в ~/.zshrc или ~/.bashrc
echo 'export PATH="$(npm config get prefix)/bin:$PATH"' >> ~/.zshrc

# 5. Перезагрузите shell
source ~/.zshrc
```

---

### Проблема 2: Ошибка 'Cannot find module'

**Симптомы:** При запуске появляется ошибка о ненайденном модуле

**Решение:**
```bash
# 1. Проверьте установку
npm list -g @byterover/cipher

# 2. Переустановите
npm uninstall -g @byterover/cipher
npm install -g @byterover/cipher

# 3. Очистите кеш npm
npm cache clean --force

# 4. Проверьте права доступа
ls -la $(npm config get prefix)/lib/node_modules/@byterover
```

---

### Проблема 3: MCP сервер не запускается

**Симптомы:** Ошибка 'ENOENT' при запуске через MCP

**Решение:**

**Вариант 1:** Убедитесь что cipher установлен глобально
```bash
which cipher
```

**Вариант 2:** Используйте полный путь в `.mcp.json`:
```json
{
  "command": "$(npm config get prefix)/bin/cipher"
}
```

**Вариант 3:** Используйте npx в `.mcp.json`:
```json
{
  "command": "npx",
  "args": ["@byterover/cipher", "--mode", "mcp"]
}
```

**Вариант 4:** Проверьте логи Claude Code для деталей ошибки

---

### Проблема 4: Переменные окружения не загружаются

**Симптомы:** .env файлы не загружаются в MCP режиме

**Важно:** В MCP режиме .env файлы НЕ загружаются автоматически!

**Решение 1:** Экспортируйте переменные в shell
```bash
export OPENAI_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key
```

**Решение 2:** Добавьте env секцию в `.mcp.json`:
```json
{
  "env": {
    "OPENAI_API_KEY": "${OPENAI_API_KEY}",
    "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
  }
}
```

**Решение 3:** Используйте dotenv в shell config
```bash
eval $(cat .env | sed 's/^/export /')
```

---

### Проблема 5: Docker UI не собирается на ARM64

**Симптомы:** На Apple Silicon (M1/M2/M3) UI сборка не работает

**Причина:** По умолчанию UI сборка пропускается на ARM64

**Решение для включения:**

**Вариант 1:** При сборке образа
```bash
docker build --build-arg BUILD_UI=true .
```

**Вариант 2:** В docker-compose.yml
```yaml
services:
  cipher-api:
    build:
      args:
        BUILD_UI: true
```

⚠️ **Внимание:** Сборка может быть нестабильной на ARM64

---

### Проблема 6: Ошибка 'Permission denied'

**Симптомы:** Ошибка прав доступа при установке

**Решение (правильное):**

❌ **НЕ используйте sudo с npm!** Это плохая практика.

✅ **Настройте npm для установки без sudo:**
```bash
# 1. Создайте директорию для глобальных пакетов
mkdir ~/.npm-global

# 2. Настройте npm
npm config set prefix '~/.npm-global'

# 3. Добавьте в PATH
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.zshrc
source ~/.zshrc

# 4. Установите cipher
npm install -g @byterover/cipher
```

---

### Проблема 7: Memory не сохраняется между сессиями

**Симптомы:** Cipher не запоминает предыдущие разговоры

**Решение:**

```bash
# 1. Создайте директорию для данных
mkdir -p ~/.cipher

# 2. Проверьте права
chmod 755 ~/.cipher

# 3. Явно укажите путь к БД через environment variable
export CIPHER_DB_PATH=~/.cipher/memory.db

# 4. В MCP конфиге добавьте:
```

```json
{
  "env": {
    "CIPHER_DB_PATH": "${HOME}/.cipher/memory.db"
  }
}
```

## Важные замечания

### 🔑 API ключи обязательны
Cipher требует хотя бы один API ключ от LLM провайдера (OpenAI, Anthropic, Gemini, или Qwen) для работы.

### 🔄 Автоматическое продолжение сессий
Cipher автоматически продолжает или создает дефолтную сессию при запуске в интерактивном режиме.

### 📁 Хранение данных
По умолчанию Cipher сохраняет данные в `~/.cipher/` (можно изменить через `CIPHER_DB_PATH`).

### 🔌 MCP режим для Claude Code
Для интеграции с MAP Framework всегда используйте флаг `--mode mcp` при запуске Cipher.

### 🌐 Нулевая конфигурация
Официально Cipher позиционируется как "zero configuration setup", но для production использования рекомендуется настроить переменные окружения.

### 🔍 Семантический поиск
Cipher использует embeddings для семантического поиска по памяти, что требует подключения к LLM API.

### ⚠️ Версионирование
Используйте `npm list -g @byterover/cipher` для проверки установленной версии. MAP Framework тестировался с последней стабильной версией.

### 🐳 Docker ограничения
При использовании Docker контейнера, интеграция с Claude Code MCP требует дополнительной настройки сети (expose ports).

### 💡 Локальная vs глобальная
Для MAP Framework рекомендуется глобальная установка, так как MCP сервер должен быть доступен из любой директории.

### 🔐 Безопасность API ключей
Никогда не коммитьте `.env` файлы или `.mcp.json` с реальными API ключами в git. Используйте переменные окружения или environment variable expansion: `${OPENAI_API_KEY}`.

## Следующие шаги

После успешной установки Cipher:

1. ✅ Настройте файл конфигурации `cipher.yml` → [03-cipher-configuration.md](03-cipher-configuration.md)
2. ✅ Настройте Claude Code MCP integration → [04-claude-code-setup.md](04-claude-code-setup.md)
3. ✅ Проверьте работоспособность → [05-verification.md](05-verification.md)

## Дополнительные ресурсы

- 📚 [Официальная документация Cipher](https://docs.byterover.dev/cipher/overview)
- 💻 [GitHub репозиторий](https://github.com/campfirein/cipher)
- 🔧 [Примеры конфигурации](../../examples/cipher/)
