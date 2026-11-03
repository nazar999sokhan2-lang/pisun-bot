import os
import sys
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from database import GameDatabase
import game_logic

# Setup paths and environment
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "8080")) # Render assigns PORT dynamically

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("PisunBot")

# Database
db = GameDatabase(BASE_DIR / "game.db")
router = Router()

GROW_COOLDOWN = 24 * 3600 # 24 hours
DUEL_COOLDOWN = 1 * 3600  # 1 hour

def format_time_left(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} год")
    if minutes > 0 or hours == 0:
        parts.append(f"{minutes} хв")
    return " ".join(parts)

def generate_visual_penis(length: int) -> str:
    # 8====D
    segments = max(1, min(25, length // 2))
    return f"8{'=' * segments}D"

def get_main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="🍆 Ростити"), KeyboardButton(text="📏 Мій розмір")],
        [KeyboardButton(text="🏆 Топ гравців"), KeyboardButton(text="⚔️ Дуель (інфо)")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@router.message(CommandStart())
async def handle_start(message: Message):
    user = message.from_user
    db.get_or_create_user(user.id, user.username, user.first_name)
    if message.chat.type in ("group", "supergroup"):
        db.register_chat_member(message.chat.id, user.id)

    text = (
        f"🍆 <b>Вітаємо у PisunBot!</b>\n\n"
        f"Правила гри прості:\n"
        f"1. Тисни <b>«🍆 Ростити»</b> раз на добу, щоб випробувати удачу (+ або - см).\n"
        f"2. У групах кидай виклик друзям командою <code>/duel</code> (відповідай на повідомлення друга).\n"
        f"3. Змагайся за звання <b>🛸 Міжгалактичного Дрючка</b> у топі гравців!\n\n"
        f"Початковий розмір: <b>10 см</b>. Тисни кнопку внизу, щоб почати!"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.message(F.text == "🍆 Ростити")
@router.message(Command("grow"))
async def handle_grow(message: Message):
    user = message.from_user
    u_data = db.get_or_create_user(user.id, user.username, user.first_name)
    if message.chat.type in ("group", "supergroup"):
        db.register_chat_member(message.chat.id, user.id)

    now = int(time.time())
    last_grow = u_data.get("last_grow", 0)
    diff = now - last_grow

    if diff < GROW_COOLDOWN:
        left = GROW_COOLDOWN - diff
        await message.answer(
            f"😴 <b>{user.first_name}</b>, твій агрегат ще відпочиває!\n"
            f"⏳ Наступна спроба буде доступна через: <b>{format_time_left(left)}</b>.\n"
            f"Поточний розмір: <b>{u_data['length']} см</b> ({game_logic.get_title(u_data['length'])}).",
            parse_mode="HTML"
        )
        return

    delta, event_text = game_logic.roll_grow()
    new_length = max(0, u_data["length"] + delta)
    db.update_length(user.id, new_length, update_grow_time=True)

    title = game_logic.get_title(new_length)
    visual = generate_visual_penis(new_length)

    res_text = (
        f"🎲 <b>{user.first_name}</b> крутить рулетку росту...\n\n"
        f"{event_text}\n\n"
        f"📏 Твій новий розмір: <b>{new_length} см</b>\n"
        f"<code>{visual}</code>\n"
        f"🎖 Твій статус: <b>{title}</b>\n\n"
        f"<i>Наступна спроба через 24 години!</i>"
    )
    await message.answer(res_text, parse_mode="HTML")

@router.message(F.text == "📏 Мій розмір")
@router.message(Command("my"))
async def handle_my(message: Message):
    user = message.from_user
    u_data = db.get_or_create_user(user.id, user.username, user.first_name)
    if message.chat.type in ("group", "supergroup"):
        db.register_chat_member(message.chat.id, user.id)

    length = u_data["length"]
    title = game_logic.get_title(length)
    visual = generate_visual_penis(length)

    now = int(time.time())
    diff = now - u_data.get("last_grow", 0)
    if diff >= GROW_COOLDOWN:
        cooldown_status = "🟢 <b>Можна ростити просто зараз!</b> Тисни кнопку."
    else:
        left = GROW_COOLDOWN - diff
        cooldown_status = f"⏳ До росту: {format_time_left(left)}"

    msg = (
        f"👤 <b>Статистика: {user.first_name}</b>\n\n"
        f"📏 Довжина: <b>{length} см</b>\n"
        f"<code>{visual}</code>\n"
        f"🎖 Титул: <b>{title}</b>\n\n"
        f"⚔️ Перемог у дуелях: <b>{u_data.get('duels_won', 0)}</b> | Поразок: <b>{u_data.get('duels_lost', 0)}</b>\n"
        f"{cooldown_status}"
    )
    await message.answer(msg, parse_mode="HTML")

@router.message(F.text == "🏆 Топ гравців")
@router.message(Command("top"))
async def handle_top(message: Message):
    chat_id = message.chat.id if message.chat.type in ("group", "supergroup") else None
    top_users = db.get_top_in_chat(chat_id=chat_id, limit=10)

    if not top_users:
        await message.answer("🏆 Топ поки що порожній! Зробіть перший вимір.")
        return

    chat_label = "у цій групі" if chat_id else "глобальний"
    lines = [f"🏆 <b>ТОП-10 {chat_label.upper()}</b>\n"]
    medals = ["🥇", "🥈", "🥉"]

    for idx, u in enumerate(top_users):
        pos = medals[idx] if idx < 3 else f"{idx + 1}."
        name = u["first_name"] or u["username"] or "Анонім"
        title = game_logic.get_title(u["length"])
        lines.append(f"{pos} <b>{name}</b> — <b>{u['length']} см</b> <i>({title})</i>")

    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(F.text == "⚔️ Дуель (інфо)")
async def handle_duel_info(message: Message):
    text = (
        f"⚔️ <b>Як проводити дуелі?</b>\n\n"
        f"1. Додайте цього бота у спільну групу з друзями.\n"
        f"2. Відповідайте (Reply) на повідомлення будь-якого друга командою:\n"
        f"   <code>/duel</code>\n"
        f"3. Бот кине кубики 🎲. Переможець відірве від <b>2 до 5 см</b> у суперника і забере собі!"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("duel"))
async def handle_duel(message: Message):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚔️ Дуелі доступні тільки у групових чатах! Додай бота до групи з друзями.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("⚠️ Щоб викликати когось на дуель, напиши <code>/duel</code> у відповідь (Reply) на його повідомлення!")
        return

    attacker = message.from_user
    defender = message.reply_to_message.from_user

    if attacker.id == defender.id:
        await message.answer("🤔 Не можна дуелитися із самим собою, це дивно!")
        return

    if defender.is_bot:
        await message.answer("🤖 Боти не беруть участі у вимірах!")
        return

    a_data = db.get_or_create_user(attacker.id, attacker.username, attacker.first_name)
    d_data = db.get_or_create_user(defender.id, defender.username, defender.first_name)
    db.register_chat_member(message.chat.id, attacker.id)
    db.register_chat_member(message.chat.id, defender.id)

    now = int(time.time())
    diff = now - a_data.get("last_duel", 0)
    if diff < DUEL_COOLDOWN:
        left = DUEL_COOLDOWN - diff
        await message.answer(f"⏳ <b>{attacker.first_name}</b>, ти нещодавно бився! Відпочинь ще <b>{format_time_left(left)}</b>.")
        return

    # Roll duel
    d1, d2 = game_logic.roll_duel()
    transfer = min(max(1, d_data["length"] // 4), 5) # Transfers between 1 and 5 cm

    if d1 > d2:
        winner = attacker
        loser = defender
        db.record_duel_result(winner_id=attacker.id, loser_id=defender.id, transfer_cm=transfer)
        res_msg = (
            f"⚔️ <b>БИТВА ТИТАНІВ!</b>\n\n"
            f"<b>{attacker.first_name}</b> (🎲 {d1}) проти <b>{defender.first_name}</b> (🎲 {d2})\n\n"
            f"🎉 <b>Переміг {attacker.first_name}!</b>\n"
            f"Він відірвав у суперника <b>+{transfer} см</b>!\n\n"
            f"📏 Новий розмір {attacker.first_name}: <b>{a_data['length'] + transfer} см</b>\n"
            f"📏 Новий розмір {defender.first_name}: <b>{max(0, d_data['length'] - transfer)} см</b>"
        )
    else:
        winner = defender
        loser = attacker
        db.record_duel_result(winner_id=defender.id, loser_id=attacker.id, transfer_cm=transfer)
        res_msg = (
            f"⚔️ <b>БИТВА ТИТАНІВ!</b>\n\n"
            f"<b>{attacker.first_name}</b> (🎲 {d1}) проти <b>{defender.first_name}</b> (🎲 {d2})\n\n"
            f"💥 <b>{attacker.first_name} не розрахував сили і ПРОГРАВ!</b>\n"
            f"<b>{defender.first_name}</b> забирає собі <b>+{transfer} см</b>!\n\n"
            f"📏 Новий розмір {attacker.first_name}: <b>{max(0, a_data['length'] - transfer)} см</b>\n"
            f"📏 Новий розмір {defender.first_name}: <b>{d_data['length'] + transfer} см</b>"
        )

    await message.answer(res_msg, parse_mode="HTML")

# --- Render Health Check HTTP Handler ---
async def health_check(request):
    return web.Response(text="OK, PisunBot is alive and running 24/7!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health check web server started on port {PORT}")

# --- Main Entrypoint ---
async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in environment or .env file!")
        print("\nПомилка: BOT_TOKEN не знайдено! Вкажіть його у файлі .env\n")
        sys.exit(1)

    logger.info("Starting PisunBot...")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # 1. Start HTTP server for Render 24/7 health check
    await start_web_server()

    # 2. Start polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is ready and polling updates!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
