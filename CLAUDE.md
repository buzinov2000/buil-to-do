# CLAUDE.md

## Проект

Личный Telegram-бот-трекер задач. Подробное описание — в TASK.md.

---

## Правила

- Код и комментарии — английский
- UI текст (сообщения бота) — русский
- Не усложняй: весь бот в двух файлах (bot.py + database.py)
- SQLite достаточно, не предлагай ничего другого
- Не добавляй фичи из "не входит в V1" без явной просьбы

---

## Среда

- VPS Ubuntu, деплой через docker-compose
- Секреты в .env (не коммитить)

### .env

```
BOT_TOKEN=
ALLOWED_IDS=108117608,ID2,ID3
```

---

## Ключевые решения

**Парсинг ввода:**
Каждая непустая строка = одна задача. Пустые строки игнорируются.

**callback_data формат:**
`done:{message_id}:{index}` — чтобы однозначно идентифицировать какую задачу в каком сообщении закрываем.

**MarkdownV2 экранирование:**
Все спецсимволы в тексте задач экранировать перед отправкой. Это важно — aiogram бросит ошибку если забыть.

**Состояние:**
SQLite хранит только активные (незавершённые полностью) списки. Когда все задачи выполнены — запись можно оставить для истории, но кнопки убираются.

---

## Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

```yaml
# docker-compose.yml
services:
  bot:
    build: .
    restart: always
    env_file: .env
    volumes:
      - ./data:/app/data  # для SQLite файла
```

SQLite файл хранить в ./data/tasks.db — чтобы не терялся при пересборке контейнера.

---

## Порядок разработки

1. database.py — создание таблицы, save/load/update задач
2. bot.py — /start, парсинг сообщения, отправка с кнопками
3. Обработчик callback — редактирование сообщения при нажатии
4. /clear команда
5. Dockerfile + docker-compose.yml

---

## Команды

```bash
# Локальный запуск
pip install -r requirements.txt
python bot.py

# Деплой
docker-compose up -d --build

# Логи
docker-compose logs -f
```
