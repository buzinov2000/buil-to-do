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

        # Migrate: add "section" field to existing items
        async with db.execute("SELECT message_id, chat_id, items FROM tasks") as cursor:
            rows = await cursor.fetchall()
        for msg_id, chat_id, raw_items in rows:
            items = json.loads(raw_items)
            if items and "section" not in items[0]:
                for item in items:
                    item["section"] = "today"
                await db.execute(
                    "UPDATE tasks SET items = ? WHERE message_id = ? AND chat_id = ?",
                    (json.dumps(items, ensure_ascii=False), msg_id, chat_id),
                )
        await db.commit()

        # Migrate: add "created_by" column
        async with db.execute("PRAGMA table_info(tasks)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "created_by" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN created_by TEXT DEFAULT ''")
            await db.commit()


async def save_tasks(chat_id: int, message_id: int, items: list[dict], created_by: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tasks (message_id, chat_id, items, created_by) VALUES (?, ?, ?, ?)",
            (message_id, chat_id, json.dumps(items, ensure_ascii=False), created_by),
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


async def mark_done(chat_id: int, message_id: int, index: int, done_by: str = "") -> list[dict] | None:
    items = await load_tasks(chat_id, message_id)
    if items is None or index >= len(items):
        return None
    items[index]["done"] = True
    if done_by:
        items[index]["done_by"] = done_by
    # Direct UPDATE to preserve created_by
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tasks SET items = ? WHERE message_id = ? AND chat_id = ?",
            (json.dumps(items, ensure_ascii=False), message_id, chat_id),
        )
        await db.commit()
    return items


async def get_last_active(chat_id: int) -> tuple[int, list[dict], str] | None:
    """Return (message_id, items, created_by) for the latest list that still has undone tasks."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message_id, items, created_by FROM tasks WHERE chat_id = ? ORDER BY created_at DESC",
            (chat_id,),
        ) as cursor:
            async for row in cursor:
                items = json.loads(row[1])
                if any(not t["done"] for t in items):
                    return row[0], items, row[2] or ""
    return None


async def get_created_by(chat_id: int, message_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT created_by FROM tasks WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id),
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0] or "") if row else ""


async def append_tasks(chat_id: int, message_id: int, new_items: list[dict]) -> list[dict]:
    """Append new_items to an existing task list. Direct UPDATE to preserve created_by."""
    items = await load_tasks(chat_id, message_id)
    if items is None:
        items = []
    items.extend(new_items)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tasks SET items = ? WHERE message_id = ? AND chat_id = ?",
            (json.dumps(items, ensure_ascii=False), message_id, chat_id),
        )
        await db.commit()
    return items


async def shift_tomorrow_to_today() -> list[tuple[int, int, list[dict], str]]:
    """Move all undone 'tomorrow' tasks to 'today'. Returns updated (chat_id, message_id, items, created_by)."""
    updated = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT message_id, chat_id, items, created_by FROM tasks") as cursor:
            rows = await cursor.fetchall()
        for msg_id, chat_id, raw_items, created_by in rows:
            items = json.loads(raw_items)
            changed = False
            for item in items:
                if item.get("section") == "tomorrow" and not item["done"]:
                    item["section"] = "today"
                    changed = True
            if changed:
                await db.execute(
                    "UPDATE tasks SET items = ? WHERE message_id = ? AND chat_id = ?",
                    (json.dumps(items, ensure_ascii=False), msg_id, chat_id),
                )
                updated.append((chat_id, msg_id, items, created_by or ""))
        await db.commit()
    return updated


async def delete_tasks(chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM tasks WHERE message_id = ? AND chat_id = ?",
            (message_id, chat_id),
        )
        await db.commit()
