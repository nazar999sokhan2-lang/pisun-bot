import os
import sys
import random
import asyncio
import logging
import time
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from database import Database

# Config
BASE_DIR = Path(__file__).resolve().parent
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "8080"))
COOLDOWN_SECONDS = 24 * 3600  # 24 hours

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("PisunBot")

db = Database(BASE_DIR / "game.db")
router = Router()

# Visual generator
def make_visual(length: int) -> str:
    bars = max(1, min(24, length // 2))
    return f"8{'=' * bars}D"

def format_time(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год {mins} хв"
    return f"{mins} хв"

def roll_growth():
    # 75% positive, 25% negative
    if random.random() < 0.75:
        # Rare crit
        if random.random() < 0.08:
            delta = random.randint(11, 16)
            return delta, f"🔥 <b>КРИТИЧНИЙ УСПІХ!</b> Знайшов секретну мазь: <b>+{delta} см</b>!"
        delta = random.randint(2, 8)
        phrases = [
            f"💪 З'їв порцію вітамінів: <b>+{delta} см</b>!",
            f"☀️ Погрівся на сонечку: <b>+{delta} см</b>!",
            f"🏋️‍♂️ Сходив на тренування: <b>+{delta} см</b>!",
            f"🍌 З'їв зв'язку бананів: <b>+{delta} см</b>!",
            f"⚡ Випив енергетик: <b>+{delta} см</b>!"
        ]
        return delta, random.choice(phrases)
    else:
        delta = -random.randint(1, 5)
        phrases = [
            f"🥶 Скупався в крижаній воді: <b>{delta} см</b>!",
            f"😴 Спав на животі: <b>{delta} см</b>!",
            f"😱 Побачив ціни в магазині: <b>{delta} см</b>!",
            f"💨 Задув холодний вітер: <b>{delta} см</b>!"
        ]
        return delta, random.choice(phrases)

def get_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍆 Поміряти"), KeyboardButton(text="📏 Мій розмір")],
            [KeyboardButton(text="🏆 Топ чату")]
        ],
        resize_keyboard=True
    )

@router.message(CommandStart())
async def cmd_start(msg: Message):
    user = msg.from_user
    db.get_user(user.id, user.first_name, user.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, user.id)

    text = (
        f"👋 <b>Привіт, {user.first_name}!</b>\n\n"
        f"Це простий та веселий бот для вимірювання розміру з друзями.\n\n"
        f"🍆 <b>Правила:</b>\n"
        f"• Раз на добу тисни <b>«🍆 Поміряти»</b> (розмір може вирости або зменшитися).\n"
        f"• Тисни <b>«🏆 Топ чату»</b>, щоб побачити, хто лідер серед друзів!\n\n"
        f"Початковий розмір: <b>10 см</b>. Тисни кнопку нижче!"
    )
    await msg.answer(text, reply_markup=get_menu(), parse_mode="HTML")

@router.message(F.text == "🍆 Поміряти")
@router.message(Command("grow"))
async def cmd_grow(msg: Message):
    user = msg.from_user
    u = db.get_user(user.id, user.first_name, user.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, user.id)

    now = int(time.time())
    diff = now - u["last_grow"]

    if diff < COOLDOWN_SECONDS:
        left = COOLDOWN_SECONDS - diff
        await msg.answer(
            f"⏳ <b>{user.first_name}</b>, ти вже міряв сьогодні!\n\n"
            f"📏 Твій розмір: <b>{u['length']} см</b>\n"
            f"<code>{make_visual(u['length'])}</code>\n\n"
            f"Наступна спроба через: <b>{format_time(left)}</b>",
            parse_mode="HTML"
        )
        return

    delta, event_text = roll_growth()
    new_len = max(0, u["length"] + delta)
    db.set_length(user.id, new_len)

    visual = make_visual(new_len)
    chat_id = msg.chat.id if msg.chat.type in ("group", "supergroup") else None
    rank = db.get_rank(user.id, chat_id)

    res = (
        f"🍆 <b>Результат вимірювання: {user.first_name}</b>\n\n"
        f"{event_text}\n\n"
        f"📏 Новий розмір: <b>{new_len} см</b>\n"
        f"<code>{visual}</code>\n\n"
        f"🏆 Місце в топі: <b>#{rank}</b>\n"
        f"<i>(наступний вимір через 24 години)</i>"
    )
    await msg.answer(res, parse_mode="HTML")

@router.message(F.text == "📏 Мій розмір")
@router.message(Command("my"))
async def cmd_my(msg: Message):
    user = msg.from_user
    u = db.get_user(user.id, user.first_name, user.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, user.id)

    chat_id = msg.chat.id if msg.chat.type in ("group", "supergroup") else None
    rank = db.get_rank(user.id, chat_id)
    now = int(time.time())
    diff = now - u["last_grow"]

    if diff >= COOLDOWN_SECONDS:
        status_line = "🟢 <b>Можна міряти прямо зараз!</b> Тисни кнопку."
    else:
        left = COOLDOWN_SECONDS - diff
        status_line = f"⏳ Наступна спроба через: <b>{format_time(left)}</b>"

    text = (
        f"👤 <b>Профіль: {user.first_name}</b>\n\n"
        f"📏 Розмір: <b>{u['length']} см</b>\n"
        f"<code>{make_visual(u['length'])}</code>\n\n"
        f"🏆 Місце в топі: <b>#{rank}</b>\n"
        f"{status_line}"
    )
    await msg.answer(text, parse_mode="HTML")

@router.message(F.text == "🏆 Топ чату")
@router.message(Command("top"))
async def cmd_top(msg: Message):
    chat_id = msg.chat.id if msg.chat.type in ("group", "supergroup") else None
    top = db.get_top(chat_id=chat_id, limit=10)

    if not top:
        await msg.answer("🏆 Топ поки що порожній! Натисніть «🍆 Поміряти».")
        return

    medals = ["🥇", "🥈", "🥉"]
    title_label = "ЧАТУ" if chat_id else "ГЛОБАЛЬНИЙ"
    lines = [f"🏆 <b>ТОП-10 {title_label}</b>\n"]

    for i, p in enumerate(top):
        pos = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        name = p["first_name"] or p["username"] or "Анонім"
        lines.append(f"{pos} <b>{name}</b> — <b>{p['length']} см</b>")

    await msg.answer("\n".join(lines), parse_mode="HTML")

# Render 24/7 web ping handler
async def health(request):
    return web.Response(text="OK, PisunBot 2.0 is alive 24/7!", status=200)

async def run_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web healthcheck server running on port {PORT}")

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await run_web()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started successfully!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
