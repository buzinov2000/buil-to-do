import asyncio
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Characters that must be escaped in MarkdownV2
_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_md(text: str) -> str:
    return re.sub(r"([" + re.escape(_MD_SPECIAL) + r"])", r"\\\1", text)


def build_message(items: list[dict]) -> str:
    lines = ["📋 *Задачи на сегодня*\n"]
    for i, task in enumerate(items, start=1):
        label = escape_md(task["text"])
        if task["done"]:
            lines.append(f"✅ ~{i}\\. {label}~")
        else:
            lines.append(f"◻️ {i}\\. {label}")
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


@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет\\! Отправь мне список задач — каждая строка отдельная задача\\.\n\n"
        "Нажимай на номер, чтобы отметить выполненной\\.\n\n"
        "/clear — убрать кнопки с последнего активного списка\\.",
        parse_mode="MarkdownV2",
    )


@dp.message(Command("clear"))
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


@dp.message(F.text)
async def handle_task_list(message: Message):
    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not lines:
        return

    items = [{"text": line, "done": False} for line in lines]
    text = build_message(items)

    # Send with a placeholder message_id=0, then update after we know the real id
    sent = await message.answer(
        text,
        parse_mode="MarkdownV2",
        reply_markup=build_keyboard(0, items),  # temporary keyboard
    )

    # Rebuild keyboard with the real message_id and update the message
    keyboard = build_keyboard(sent.message_id, items)
    await database.save_tasks(message.chat.id, sent.message_id, items)

    await bot.edit_message_reply_markup(
        chat_id=message.chat.id,
        message_id=sent.message_id,
        reply_markup=keyboard,
    )

    try:
        await message.delete()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("done:"))
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


async def main():
    import pathlib
    pathlib.Path("data").mkdir(exist_ok=True)
    await database.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
