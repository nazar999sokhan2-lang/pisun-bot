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

# Bottom Keyboard Window (ReplyKeyboardMarkup)
def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍆 Пісюн"), KeyboardButton(text="📏 Мій розмір")],
            [KeyboardButton(text="🏆 Топ 10")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def format_time_left(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    return f"{mins} хв."

def roll_delta() -> int:
    # 80% positive growth (+1..+10), 20% slight shrink (-1..-4)
    if random.random() < 0.80:
        return random.randint(1, 10)
    else:
        return -random.randint(1, 4)

def do_grow_logic(user, chat) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    now = int(time.time())
    diff = now - u["last_grow"]

    if diff < COOLDOWN_SECONDS:
        left = COOLDOWN_SECONDS - diff
        return f"{name}, ти вже міряв сьогодні! Спробуй через {format_time_left(left)}"

    delta = roll_delta()
    new_len = max(0, u["length"] + delta)
    db.update_grow(user.id, new_len)

    if delta >= 0:
        return f"{name}, твій песюн виріс на {delta} см! 🎉\nТепер він {new_len} см."
    else:
        return f"{name}, твій песюн зменшився на {abs(delta)} см... 🤏\nТепер він {new_len} см."

def do_top_logic(chat) -> str:
    chat_id = chat.id if chat.type in ("group", "supergroup") else None
    top = db.get_top_in_chat(chat_id=chat_id, limit=10)

    if not top:
        return "Топ 10 песюнiв:\n\nПоки що ніхто не міряв свій песюн!"

    lines = ["Топ 10 песюнiв:\n"]
    for i, u in enumerate(top, 1):
        display = u["display_name"] or u["username"] or "Анонім"
        lines.append(f"{i}. {display} — {u['length']} см")

    return "\n".join(lines)

def do_my_logic(user, chat) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    now = int(time.time())
    diff = now - u["last_grow"]

    if diff >= COOLDOWN_SECONDS:
        status = "можна міряти прямо зараз!"
    else:
        left = COOLDOWN_SECONDS - diff
        status = f"до виміру: {format_time_left(left)}"

    return f"{name}, твій песюн зараз: {u['length']} см ({status})."

# --- Handlers ---
@router.message(CommandStart())
async def handle_start(msg: Message):
    user = msg.from_user
    name = user.first_name or user.username or "Гравець"
    db.get_user(user.id, name, user.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, user.id)

    text = (
        f"Привіт, {name}!\n\n"
        f"Тисни кнопку «🍆 Пісюн» нижче, щоб поміряти розмір раз на добу.\n"
        f"Тисни «🏆 Топ 10», щоб переглянути рейтинг чату!"
    )
    await msg.answer(text, reply_markup=get_reply_keyboard())

# Grow triggers: /grow, 🍆 Пісюн, пісюн, !пісюн, песюн, !песюн
@router.message(Command("grow"))
@router.message(F.text.lower().in_([
    "🍆 пісюн", "пісюн", "!пісюн", "/пісюн", 
    "песюн", "!песюн", "/песюн", "ростити", "🍆 ростити", "поміряти", "🍆 поміряти"
]))
async def handle_grow(msg: Message):
    reply = do_grow_logic(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# Top triggers: /top, 🏆 Топ 10, топ, !топ, топ 10, !топ 10
@router.message(Command("top"))
@router.message(F.text.lower().in_([
    "🏆 топ 10", "топ 10", "!топ 10", "топ", "!топ", "/топ", "🏆 топ гравців", "топ гравців"
]))
async def handle_top(msg: Message):
    reply = do_top_logic(msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# My size triggers: /my, 📏 Мій розмір, розмір, !розмір
@router.message(Command("my"))
@router.message(F.text.lower().in_([
    "📏 мій розмір", "мій розмір", "розмір", "!розмір", "/розмір", "мій песюн", "мій пісюн"
]))
async def handle_my(msg: Message):
    reply = do_my_logic(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# --- Render Health Check Server ---
async def health(request):
    return web.Response(text="OK, PisunBot 2.0 with Bottom Keyboard is alive 24/7!", status=200)

async def run_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Healthcheck web server running on port {PORT}")

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await run_web()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is polling updates!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
