# Architecture

Personal Telegram task-tracker bot.

## File structure

```
.
├── bot.py                  # Bot logic: handlers, message formatting, keyboards
├── database.py             # SQLite async wrapper (aiosqlite)
├── requirements.txt        # Python dependencies
├── Dockerfile              # python:3.11-slim, runs bot.py
├── docker-compose.yml      # Single service, mounts ./data for DB persistence
├── .env                    # Secrets (not in git)
├── data/
│   └── tasks.db            # SQLite database (not in git)
└── .github/
    └── workflows/
        └── deploy.yml      # Auto-deploy on push to main
```

## Components

### bot.py

| Function | Description |
|---|---|
| `escape_md(text)` | Escapes MarkdownV2 special characters |
| `build_message(items)` | Renders task list as MarkdownV2 string |
| `build_keyboard(message_id, items)` | Inline buttons for uncompleted tasks |
| `cmd_start` | `/start` — welcome message |
| `cmd_clear` | `/clear` — removes buttons from last active list |
| `handle_task_list` | Any text message → parse lines → send card → delete original |
| `handle_done` | Callback `done:{message_id}:{index}` → mark task done → edit message |

### database.py

Single table `tasks (message_id, chat_id, items, created_at)`.

| Function | Description |
|---|---|
| `init_db()` | Creates table if not exists |
| `save_tasks()` | INSERT OR REPLACE |
| `load_tasks()` | SELECT by message_id + chat_id |
| `mark_done()` | load → flip done=True → save |
| `get_last_active()` | Latest list with at least one undone task |
| `delete_tasks()` | DELETE by message_id + chat_id |

## Data flow

```
User sends text
  → handle_task_list
  → send bot message (placeholder keyboard)
  → save_tasks to SQLite
  → edit_message_reply_markup (real message_id)
  → delete user's original message

User taps button (done:{msg_id}:{i})
  → handle_done
  → mark_done in SQLite
  → edit_message_text (updated list)
  → if all done: remove keyboard + show 🎉
```

## callback_data format

`done:{message_id}:{index}` — uniquely identifies which task in which message.

## Deployment

- VPS: Ubuntu 22.04, Docker
- Deploy: `docker compose up -d --build`
- CI/CD: GitHub Actions (`deploy.yml`) — SSH into VPS, `git pull`, `docker compose up` on every push to `main`
- DB persisted via volume mount `./data:/app/data`
