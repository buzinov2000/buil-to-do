import json
import aiosqlite

DB_PATH = "data/tasks.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                message_id INTEGER,
                chat_id    INTEGER,
                items      TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, chat_id)
            )
        """)
        await db.commit()


async def save_tasks(chat_id: int, message_id: int, items: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tasks (message_id, chat_id, items) VALUES (?, ?, ?)",
            (message_id, chat_id, json.dumps(items, ensure_ascii=False)),
        )
        await db.commit()


async def load_tasks(chat_id: int, message_id: int) -> list[dict] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT items FROM tasks WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id),
        ) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else None


async def mark_done(chat_id: int, message_id: int, index: int) -> list[dict] | None:
    items = await load_tasks(chat_id, message_id)
    if items is None or index >= len(items):
        return None
    items[index]["done"] = True
    await save_tasks(chat_id, message_id, items)
    return items


async def get_last_active(chat_id: int) -> tuple[int, list[dict]] | None:
    """Return (message_id, items) for the latest list that still has undone tasks."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id, items FROM tasks WHERE chat_id = ? ORDER BY created_at DESC",
            (chat_id,),
        ) as cursor:
            async for row in cursor:
                items = json.loads(row[1])
                if any(not t["done"] for t in items):
                    return row[0], items
    return None


async def delete_tasks(chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM tasks WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id),
        )
        await db.commit()
