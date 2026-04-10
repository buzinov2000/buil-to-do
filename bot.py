import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 108117608

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

log = logging.getLogger(__name__)

# In-memory store for pending tasks awaiting user choice (add/new)
pending_tasks: dict[int, list[dict]] = {}

# Characters that must be escaped in MarkdownV2
_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_md(text: str) -> str:
    return re.sub(r"([" + re.escape(_MD_SPECIAL) + r"])", r"\\\1", text)


def parse_tasks(text: str) -> list[dict]:
    """Parse message text into task items with sections."""
    current_section = "today"
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low == "сегодня":
            current_section = "today"
        elif low == "завтра":
            current_section = "tomorrow"
        else:
            items.append({"text": stripped, "done": False, "section": current_section})
    return items


def build_message(items: list[dict]) -> str:
    today = [t for t in items if t.get("section", "today") == "today"]
    tomorrow = [t for t in items if t.get("section") == "tomorrow"]

    has_today_active = any(not t["done"] for t in today)
    has_tomorrow_active = any(not t["done"] for t in tomorrow)

    lines = ["📋 *Задачи*\n"]

    if has_today_active:
        lines.append("*— Сегодня —*")
        for i, task in enumerate(items):
            if task.get("section", "today") != "today":
                continue
            label = escape_md(task["text"])
            idx = items.index(task) + 1
            if task["done"]:
                lines.append(f"✅ ~{idx}\\. {label}~")
            else:
                lines.append(f"◻️ {idx}\\. {label}")
        lines.append("")

    if has_tomorrow_active:
        lines.append("*— Завтра —*")
        for i, task in enumerate(items):
            if task.get("section") != "tomorrow":
                continue
            label = escape_md(task["text"])
            idx = items.index(task) + 1
            if task["done"]:
                lines.append(f"✅ ~{idx}\\. {label}~")
            else:
                lines.append(f"◻️ {idx}\\. {label}")

    return "\n".join(lines)


def build_keyboard(message_id: int, items: list[dict]) -> InlineKeyboardMarkup | None:
    buttons = [
        InlineKeyboardButton(
            text=str(i + 1),
            callback_data=f"done:{message_id}:{i}",
        )
        for i, task in enumerate(items)
        if not task["done"]
    ]
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def owner_only(message: Message) -> bool:
    return message.from_user.id == OWNER_ID


@dp.message(Command("start"), owner_only)
async def cmd_start(message: Message):
    await message.answer(
        "Привет\\! Отправь мне список задач — каждая строка отдельная задача\\.\n\n"
        "Используй заголовки *сегодня* / *завтра* для секций\\.\n\n"
        "Нажимай на номер, чтобы отметить выполненной\\.\n\n"
        "/clear — убрать кнопки с последнего активного списка\\.",
        parse_mode="MarkdownV2",
    )


@dp.message(Command("clear"), owner_only)
async def cmd_clear(message: Message):
    result = await database.get_last_active(message.chat.id)
    if result is None:
        await message.answer("Активных списков нет\\.", parse_mode="MarkdownV2")
        return

    msg_id, items = result
    text = build_message(items) + "\n\n_\\(сброшено\\)_"
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg_id,
            text=text,
            parse_mode="MarkdownV2",
            reply_markup=None,
        )
    except Exception:
        pass
    await database.delete_tasks(message.chat.id, msg_id)
    await message.answer("Кнопки убраны\\.", parse_mode="MarkdownV2")


@dp.message(F.text, owner_only)
async def handle_task_list(message: Message):
    new_items = parse_tasks(message.text)
    if not new_items:
        return

    active = await database.get_last_active(message.chat.id)

    if active is not None:
        # Store pending tasks and ask the user
        pending_tasks[message.chat.id] = new_items
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="➕ Добавить к текущему", callback_data="add_to_existing"),
            InlineKeyboardButton(text="🆕 Новый список", callback_data="new_list"),
        ]])
        await message.answer(
            "Активный список уже есть\\. Что сделать с новыми задачами?",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        try:
            await message.delete()
        except Exception:
            pass
        return

    # No active list — create a new one
    await _create_new_list(message.chat.id, new_items)

    try:
        await message.delete()
    except Exception:
        pass


async def _create_new_list(chat_id: int, items: list[dict]) -> None:
    """Send a new task list message and save to DB."""
    text = build_message(items)
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=build_keyboard(0, items),
    )
    keyboard = build_keyboard(sent.message_id, items)
    await database.save_tasks(chat_id, sent.message_id, items)
    await bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=sent.message_id,
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "add_to_existing", lambda c: c.from_user.id == OWNER_ID)
async def handle_add_to_existing(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    new_items = pending_tasks.pop(chat_id, None)
    if new_items is None:
        await callback.answer("Нет ожидающих задач.")
        return

    active = await database.get_last_active(chat_id)
    if active is None:
        await callback.answer("Активный список не найден.")
        return

    msg_id, _ = active
    items = await database.append_tasks(chat_id, msg_id, new_items)

    text = build_message(items)
    keyboard = build_keyboard(msg_id, items)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )

    # Delete the service message with buttons
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Задачи добавлены.")


@dp.callback_query(F.data == "new_list", lambda c: c.from_user.id == OWNER_ID)
async def handle_new_list(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    new_items = pending_tasks.pop(chat_id, None)
    if new_items is None:
        await callback.answer("Нет ожидающих задач.")
        return

    await _create_new_list(chat_id, new_items)

    # Delete the service message
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Новый список создан.")


@dp.callback_query(F.data.startswith("done:"), lambda c: c.from_user.id == OWNER_ID)
async def handle_done(callback: CallbackQuery):
    _, msg_id_str, index_str = callback.data.split(":")
    msg_id = int(msg_id_str)
    index = int(index_str)

    items = await database.mark_done(callback.message.chat.id, msg_id, index)
    if items is None:
        await callback.answer("Задача не найдена.")
        return

    all_done = all(t["done"] for t in items)
    text = build_message(items)
    if all_done:
        text += "\n\n🎉 *Всё готово\\!*"

    keyboard = None if all_done else build_keyboard(msg_id, items)

    await bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=msg_id,
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )
    await callback.answer()


async def midnight_shift():
    """Shift 'tomorrow' tasks to 'today' and update messages."""
    updated = await database.shift_tomorrow_to_today()
    for chat_id, msg_id, items in updated:
        text = build_message(items)
        all_done = all(t["done"] for t in items)
        if all_done:
            text += "\n\n🎉 *Всё готово\\!*"
        keyboard = None if all_done else build_keyboard(msg_id, items)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
        except Exception:
            log.exception("Failed to update message %s in chat %s", msg_id, chat_id)


async def main():
    import pathlib
    pathlib.Path("data").mkdir(exist_ok=True)
    await database.init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Справка"),
        BotCommand(command="clear", description="Убрать кнопки с последнего списка"),
    ])

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(midnight_shift, "cron", hour=0, minute=0)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
