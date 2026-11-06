import os
import sys
import random
import re
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)

from dotenv import load_dotenv
from database import Database

# --- Config ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "8080"))

# Telegram Admin ID
ADMIN_IDS = [1743742401]

GROW_COOLDOWN = 24 * 3600    # 24 години
CASINO_COOLDOWN = 90         # 1.5 хвилини
DUEL_COOLDOWN = 3 * 60       # 3 хвилини
MAX_CASINO_BET = 30          # Максимальна ставка

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("PisunBot")

db = Database(BASE_DIR / "game.db")
router = Router()

def get_badge(length: int) -> str:
    if length >= 90:
        return "👑"
    elif length >= 50:
        return "🐍"
    elif length >= 25:
        return "🍆"
    elif length >= 10:
        return "🌶"
    else:
        return "🤏"

def format_time_left(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    if mins > 0:
        return f"{mins} хв. {secs} сек."
    return f"{secs} сек."

REMOVE_KB = ReplyKeyboardRemove()

def get_casino_inline_keyboard(user_length: int) -> InlineKeyboardMarkup:
    """Швидкі кнопки ставок"""
    all_in_amount = min(user_length, MAX_CASINO_BET)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 2 см", callback_data="bet:dice:2"),
            InlineKeyboardButton(text="🎲 5 см", callback_data="bet:dice:5"),
            InlineKeyboardButton(text="🎲 10 см", callback_data="bet:dice:10")
        ],
        [
            InlineKeyboardButton(text="🎰 Слоти (5 см)", callback_data="bet:slots:5"),
            InlineKeyboardButton(text=f"🔥 Ва-банк ({all_in_amount} см)", callback_data=f"bet:dice:{all_in_amount}")
        ]
    ])

# --- Logic: Grow ---
def do_grow(user, chat) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    now = int(time.time())
    diff = now - u.get("last_grow", 0)

    if diff < GROW_COOLDOWN:
        left = GROW_COOLDOWN - diff
        return f"⏳ {name}, ти вже міряв сьогодні! Спробуй через {format_time_left(left)}"

    if random.random() < 0.80:
        delta = random.randint(1, 10)
    else:
        delta = -random.randint(1, 4)

    cur_len = u.get("length", 0)
    new_len = max(0, cur_len + delta)
    db.update_grow(user.id, new_len)

    badge = get_badge(new_len)
    if delta >= 0:
        return f"🍆 {name}, твій пісюн виріс на <b>+{delta} см</b>! 🎉\nТепер він: <b>{new_len} см</b> {badge}"
    else:
        return f"🍆 {name}, твій пісюн зменшився на <b>{delta} см</b>... 🤏\nТепер він: <b>{new_len} см</b> {badge}"

# --- Logic: My Size ---
def do_my(user, chat) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    cur_len = u.get("length", 0)
    badge = get_badge(cur_len)

    now = int(time.time())
    diff = now - u.get("last_grow", 0)
    if diff >= GROW_COOLDOWN:
        status = "можна міряти прямо зараз!"
    else:
        left = GROW_COOLDOWN - diff
        status = f"до виміру: {format_time_left(left)}"

    return f"📏 {name}, твій розмір: <b>{cur_len} см</b> {badge} ({status})"

# --- Logic: Top ---
def do_top(chat) -> str:
    chat_id = chat.id if chat.type in ("group", "supergroup") else None
    top = db.get_top_in_chat(chat_id=chat_id, limit=10)

    if not top:
        return "🏆 <b>Топ 10 лідерів:</b>\n\nПоки що ніхто не міряв свій розмір!"

    lines = ["🏆 <b>Топ 10 лідерів чату:</b>\n"]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    for i, u in enumerate(top):
        display = u.get("display_name") or u.get("username") or "Гравець"
        length = u.get("length", 0)
        badge = get_badge(length)
        medal = medals[i] if i < len(medals) else f"{i+1}."
        lines.append(f"{medal} <b>{display}</b> — {length} см {badge}")

    return "\n".join(lines)

# --- Logic: Duel ---
def do_duel(attacker, defender, chat, bet_amount: int) -> str:
    a_name = attacker.first_name or attacker.username or "Гравець"
    d_name = defender.first_name or defender.username or "Гравець"

    if attacker.id == defender.id:
        return "🤔 Не можна викликати на дуель самого себе!"

    if defender.is_bot:
        return "🤖 Боти не беруть участі в дуелях!"

    a_u = db.get_user(attacker.id, a_name, attacker.username)
    d_u = db.get_user(defender.id, d_name, defender.username)
    db.register_chat(chat.id, attacker.id)
    db.register_chat(chat.id, defender.id)

    bet_amount = max(1, min(bet_amount, 30))
    a_len = a_u.get("length", 0)
    d_len = d_u.get("length", 0)

    if a_len < bet_amount:
        return f"❌ {a_name}, у тебе замало сантиметрів ({a_len} см)!"

    if d_len < bet_amount:
        return f"❌ {d_name} має замало сантиметрів ({d_len} см)!"

    now = int(time.time())
    diff = now - a_u.get("last_duel", 0)
    if diff < DUEL_COOLDOWN:
        left = DUEL_COOLDOWN - diff
        return f"⏳ {a_name}, наступна дуель через {format_time_left(left)}"

    d1 = random.randint(1, 100)
    d2 = random.randint(1, 100)
    while d1 == d2:
        d2 = random.randint(1, 100)

    if d1 > d2:
        db.transfer_duel(attacker.id, defender.id, bet_amount)
        return (
            f"🥊 <b>Дуель: {a_name} проти {d_name} на {bet_amount} см!</b>\n"
            f"🎲 Кидок: {a_name} ({d1}) vs {d_name} ({d2})\n\n"
            f"🏆 <b>Переміг {a_name}!</b> (+{bet_amount} см)\n"
            f"📏 {a_name}: {a_len + bet_amount} см | {d_name}: {d_len - bet_amount} см"
        )
    else:
        db.transfer_duel(defender.id, attacker.id, bet_amount)
        return (
            f"🥊 <b>Дуель: {a_name} проти {d_name} на {bet_amount} см!</b>\n"
            f"🎲 Кидок: {a_name} ({d1}) vs {d_name} ({d2})\n\n"
            f"💥 <b>{a_name} програв!</b> {d_name} забирає +{bet_amount} см\n"
            f"📏 {d_name}: {d_len + bet_amount} см | {a_name}: {a_len - bet_amount} см"
        )

# --- Play Casino Function ---
async def play_casino_round(bot: Bot, chat_id: int, user, game_type: str, bet: int, reply_to_msg_id: Optional[int] = None):
    name = user.first_name or "Гравець"
    u = db.get_user(user.id, name, user.username)
    cur_len = u.get("length", 0)

    if bet <= 0:
        bet = 2

    bet = min(bet, MAX_CASINO_BET)

    if cur_len < bet:
        text = f"❌ {name}, у тебе замало сантиметрів! Твій розмір: {cur_len} см, а ставка: {bet} см."
        await bot.send_message(chat_id, text, reply_to_message_id=reply_to_msg_id)
        return

    now = int(time.time())
    diff = now - u.get("last_casino", 0)
    if diff < CASINO_COOLDOWN:
        left = CASINO_COOLDOWN - diff
        text = f"🎰 {name}, наступна ставка доступна через <b>{format_time_left(left)}</b>"
        await bot.send_message(chat_id, text, reply_to_message_id=reply_to_msg_id, parse_mode="HTML")
        return

    emoji = "🎰" if game_type == "slots" else "🎲"
    dice_msg = await bot.send_dice(chat_id, emoji=emoji, reply_to_message_id=reply_to_msg_id)
    dice_val = dice_msg.dice.value

    # Затримка анімації Telegram
    await asyncio.sleep(2.5)

    is_win = False
    win_multiplier = 2

    if game_type == "slots":
        # 64 = 777 (джекпот x4)
        if dice_val == 64:
            is_win = True
            win_multiplier = 4
        elif dice_val in (1, 22, 43):  # Три однакових символи
            is_win = True
            win_multiplier = 3
        elif dice_val in (16, 32, 48): # Два однакових
            is_win = True
            win_multiplier = 2
    else:
        # Кубик: 4, 5, 6 перемога (x2)
        if dice_val >= 4:
            is_win = True
            win_multiplier = 2

    if is_win:
        win_cm = bet * (win_multiplier - 1)
        new_len = cur_len + win_cm
        db.update_casino(user.id, new_len)
        text = (
            f"🎉 <b>Випало {dice_val}! ПЕРЕМОГА (+{win_cm} см)</b> (х{win_multiplier}) 🥳\n"
            f"📏 {name}, твій новий розмір: <b>{new_len} см</b> {get_badge(new_len)}"
        )
    else:
        new_len = max(0, cur_len - bet)
        db.update_casino(user.id, new_len)
        text = (
            f"💥 <b>Випало {dice_val}... ПРОГРАШ (-{bet} см)</b> 🤏\n"
            f"📏 {name}, твій новий розмір: <b>{new_len} см</b> {get_badge(new_len)}"
        )

    await dice_msg.reply(text, reply_markup=REMOVE_KB, parse_mode="HTML")

# --- Handlers ---

@router.message(CommandStart())
async def handle_start(msg: Message):
    name = msg.from_user.first_name or "Гравець"
    db.get_user(msg.from_user.id, name, msg.from_user.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, msg.from_user.id)

    text = (
        f"Привіт, <b>{name}</b>!\n\n"
        f"• «🍆 <b>Ростити</b>» — поміряти розмір раз на добу\n"
        f"• «📏 <b>Мій розмір</b>» — перевірити довжину\n"
        f"• «🎰 <b>Казино</b>» — гра на кубиках та слотах (або пиши: <code>ставка 5</code> чи <code>вабанк</code>)\n"
        f"• «⚔️ <b>Дуель</b>» — відповідай на повідомлення друга словом: <code>дуель 5</code>\n"
        f"• «🏆 <b>Топ 10</b>» — рейтинг лідерів чату"
    )
    await msg.answer(text, reply_markup=REMOVE_KB, parse_mode="HTML")

@router.message(Command("grow"))
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["ростити", "пісюн", "песюн", "поміряти"])))
async def handle_grow(msg: Message):
    reply = do_grow(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=REMOVE_KB, parse_mode="HTML")

@router.message(Command("my"))
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["розмір", "мій розмір", "мій песюн", "мій пісюн"])))
async def handle_my(msg: Message):
    reply = do_my(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=REMOVE_KB, parse_mode="HTML")

@router.message(Command("top"))
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["топ", "лідери", "top"])))
async def handle_top(msg: Message):
    reply = do_top(msg.chat)
    await msg.answer(reply, reply_markup=REMOVE_KB, parse_mode="HTML")

# --- Casino Menu & Text Bets ---
@router.message(Command("casino"))
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["казино", "casino", "рулетка"])))
async def handle_casino_menu(msg: Message):
    user = msg.from_user
    u = db.get_user(user.id, user.first_name, user.username)
    cur_len = u.get("length", 0)

    # Якщо користувач просто написав "казино" або натиснув кнопку
    match = re.search(r'\d+', msg.text)
    if match:
        bet = int(match.group())
        await play_casino_round(msg.bot, msg.chat.id, user, "dice", bet, msg.message_id)
        return

    text = (
        f"🎰 <b>Казино Дрючка</b>\n"
        f"Твій баланс: <b>{cur_len} см</b>\n\n"
        f"Обери швидку ставку або напиши в чат (наприклад: <code>ставка 10</code>):"
    )
    await msg.answer(text, reply_markup=get_casino_inline_keyboard(cur_len), parse_mode="HTML")

# Ставка текстом: "ставка 10", "ставка 5", "бет 15"
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["ставка", "bet", "бет"])))
async def handle_text_bet(msg: Message):
    match = re.search(r'\d+', msg.text)
    bet = int(match.group()) if match else 5
    await play_casino_round(msg.bot, msg.chat.id, msg.from_user, "dice", bet, msg.message_id)

# Ва-банк текстом: "вабанк", "ва-банк", "allin", "all in"
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["вабанк", "ва-банк", "allin", "all-in"])))
async def handle_all_in(msg: Message):
    user = msg.from_user
    u = db.get_user(user.id, user.first_name, user.username)
    cur_len = u.get("length", 0)
    bet = min(cur_len, MAX_CASINO_BET)
    if bet <= 0:
        await msg.answer("❌ У тебе 0 см, ва-банк неможливий!")
        return
    await play_casino_round(msg.bot, msg.chat.id, user, "dice", bet, msg.message_id)

# Обробка натискань швидких кнопок казино
@router.callback_query(F.data.startswith("bet:"))
async def handle_casino_callback(call: CallbackQuery):
    parts = call.data.split(":")
    game_type = parts[1]
    bet = int(parts[2])

    await call.answer()
    await play_casino_round(call.bot, call.message.chat.id, call.from_user, game_type, bet)

# --- Duel Handler ---
@router.message(Command("duel"))
@router.message(F.text.func(lambda t: t and any(k in t.lower() for k in ["дуель", "duel", "бій"])))
async def handle_duel(msg: Message):
    if msg.chat.type not in ("group", "supergroup"):
        await msg.answer("⚔️ Дуелі доступні тільки у спільних групах!")
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        text = (
            f"⚔️ <b>Як викликати друга на дуель?</b>\n\n"
            f"1. Зроби <b>відповідь (Reply)</b> на повідомлення друга в чаті.\n"
            f"2. Напиши: <code>дуель 5</code> (або просто <code>дуель</code>).\n"
            f"3. Бот кине кубики і визначить переможця!"
        )
        await msg.answer(text, reply_markup=REMOVE_KB, parse_mode="HTML")
        return

    match = re.search(r'\d+', msg.text)
    bet = int(match.group()) if match else 3
    reply = do_duel(msg.from_user, msg.reply_to_message.from_user, msg.chat, bet)
    await msg.answer(reply, reply_markup=REMOVE_KB, parse_mode="HTML")

# --- Admin Handlers ---
@router.message(Command("give"))
async def handle_admin_give(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    match = re.search(r'\d+', msg.text)
    amount = int(match.group()) if match else 20

    target = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else msg.from_user
    t_name = target.first_name or "Гравець"
    t_u = db.get_user(target.id, t_name, target.username)

    new_len = t_u.get("length", 0) + amount
    conn = db._get_conn()
    try:
        cursor = conn.cursor()
        db._exec(cursor, "UPDATE users SET length = ? WHERE user_id = ?", (new_len, target.id))
        conn.commit()
    finally:
        conn.close()

    await msg.answer(f"👑 <b>Адмін-бонус:</b> {t_name} отримав <b>+{amount} см</b>!\nРозмір: <b>{new_len} см</b> {get_badge(new_len)}", parse_mode="HTML")

@router.message(Command("backup"))
async def handle_admin_backup(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    users = db.get_all_users()
    if not users:
        await msg.answer("📋 База порожня або в ній немає гравців з розміром > 0.")
        return
    lines = ["📋 <b>Бекап гравців та сантиметрів:</b>\n"]
    for u in users:
        name = u.get("display_name") or u.get("username") or str(u.get("user_id"))
        lines.append(f"• ID: <code>{u['user_id']}</code> | {name} — <b>{u['length']} см</b>")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("reset"))
async def handle_admin_reset(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    conn = db._get_conn()
    try:
        cursor = conn.cursor()
        db._exec(cursor, "UPDATE users SET last_grow = 0, last_casino = 0, last_duel = 0 WHERE user_id = ?", (msg.from_user.id,))
        conn.commit()
    finally:
        conn.close()
    await msg.answer("⚡ <b>Таймери скинуто!</b>", parse_mode="HTML")

# --- Render 24/7 Healthcheck ---
async def health(request):
    return web.Response(text="OK, PisunBot 24/7 is alive!", status=200)

async def run_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Healthcheck web server running on port {PORT}")

# --- Main Entrypoint ---
async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN is missing in environment or .env! Будь ласка, вкажіть ваш токен бота у файлі .env")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await run_web()
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await bot.set_my_commands([
            BotCommand(command="grow", description="🍆 Ростити розмір"),
            BotCommand(command="my", description="📏 Мій розмір"),
            BotCommand(command="casino", description="🎰 Казино"),
            BotCommand(command="duel", description="⚔️ Дуель з другом"),
            BotCommand(command="top", description="🏆 Топ лідерів"),
        ])
    except Exception as e:
        logger.warning(f"Could not set commands menu: {e}")

    logger.info("PisunBot is running cleanly with New Casino!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
