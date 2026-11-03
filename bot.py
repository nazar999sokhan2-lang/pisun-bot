import os
import sys
import random
import re
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
    KeyboardButton,
    BotCommand
)

from database import Database

# Config
BASE_DIR = Path(__file__).resolve().parent
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "8080"))

# Admin ID (твій Telegram ID)
ADMIN_IDS = [1743742401]

GROW_COOLDOWN = 24 * 3600  # 24 hours
CASINO_COOLDOWN = 3 * 60   # 3 minutes
DUEL_COOLDOWN = 5 * 60     # 5 minutes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("PisunBot")

db = Database(BASE_DIR / "game.db")
router = Router()

def get_badge(length: int) -> str:
    if length >= 86:
        return "👑"
    elif length >= 61:
        return "🐍"
    elif length >= 36:
        return "🦾"
    elif length >= 16:
        return "🌶"
    else:
        return "🤏"

def format_time_left(seconds: int) -> str:
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    return f"{mins} хв."

def get_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍆 Ростити"), KeyboardButton(text="📏 Мій розмір")],
            [KeyboardButton(text="🎰 Казино (5 см)"), KeyboardButton(text="⚔️ Дуель (інфо)")],
            [KeyboardButton(text="🏆 Топ гравців")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

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
        return f"{name}, ти вже міряв сьогодні! Спробуй через {format_time_left(left)}"

    if random.random() < 0.80:
        delta = random.randint(1, 10)
    else:
        delta = -random.randint(1, 4)

    new_len = max(0, u.get("length", 0) + delta)
    db.update_grow(user.id, new_len)
    badge = get_badge(new_len)

    if delta >= 0:
        return f"{name}, твій песюн виріс на {delta} см! 🎉\nТепер він {new_len} см {badge}"
    else:
        return f"{name}, твій песюн зменшився на {abs(delta)} см... 🤏\nТепер він {new_len} см {badge}"

# --- Logic: Top ---
def do_top(chat) -> str:
    chat_id = chat.id if chat.type in ("group", "supergroup") else None
    top = db.get_top_in_chat(chat_id=chat_id, limit=10)

    if not top:
        return "Топ 10 песюнiв:\n\nПоки що ніхто не міряв свій песюн!"

    lines = ["Топ 10 песюнiв:\n"]
    for i, u in enumerate(top, 1):
        display = u["display_name"] or u["username"] or "Анонім"
        badge = get_badge(u.get("length", 0))
        lines.append(f"{i}. {display} — {u.get('length', 0)} см {badge}")

    return "\n".join(lines)

# --- Logic: My Size ---
def do_my(user, chat) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    now = int(time.time())
    diff = now - u.get("last_grow", 0)
    cur_len = u.get("length", 0)
    badge = get_badge(cur_len)

    if diff >= GROW_COOLDOWN:
        status = "можна міряти прямо зараз!"
    else:
        left = GROW_COOLDOWN - diff
        status = f"до виміру: {format_time_left(left)}"

    return f"{name}, твій песюн зараз: {cur_len} см {badge} ({status})."

# --- Logic: Casino ---
def do_casino(user, chat, bet_amount: int) -> str:
    name = user.first_name or user.username or "Гравець"
    u = db.get_user(user.id, name, user.username)
    if chat.type in ("group", "supergroup"):
        db.register_chat(chat.id, user.id)

    cur_len = u.get("length", 0)

    if bet_amount <= 0:
        bet_amount = 5

    if bet_amount > 20:
        return f"{name}, максимальна ставка в казино — 20 см!"

    if cur_len < bet_amount:
        return f"{name}, у тебе замало сантиметрів! Твій розмір: {cur_len} см, а ставка: {bet_amount} см."

    now = int(time.time())
    diff = now - u.get("last_casino", 0)
    if diff < CASINO_COOLDOWN:
        left = CASINO_COOLDOWN - diff
        return f"🎰 {name}, відпочинь від казино! Наступна ставка через {format_time_left(left)}"

    dice = random.randint(1, 6)
    if dice >= 4:
        new_len = cur_len + bet_amount
        db.update_casino(user.id, new_len)
        return (
            f"🎰 {name} поставив {bet_amount} см на рулетку...\n"
            f"🎉 <b>Випало {dice} — ПЕРЕМОГА (+{bet_amount} см)!</b>\n"
            f"Твій новий розмір: {new_len} см {get_badge(new_len)}"
        )
    else:
        new_len = max(0, cur_len - bet_amount)
        db.update_casino(user.id, new_len)
        return (
            f"🎰 {name} поставив {bet_amount} см на рулетку...\n"
            f"💥 <b>Випало {dice} — ПРОГРАШ (-{bet_amount} см).</b>\n"
            f"Твій новий розмір: {new_len} см {get_badge(new_len)}"
        )

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

    if bet_amount <= 0:
        bet_amount = 3
    bet_amount = min(bet_amount, 15)

    a_len = a_u.get("length", 0)
    d_len = d_u.get("length", 0)

    if a_len < bet_amount:
        return f"{a_name}, у тебе замало сантиметрів ({a_len} см)!"

    if d_len < bet_amount:
        return f"{d_name} має замало сантиметрів для такої дуелі ({d_len} см)!"

    now = int(time.time())
    diff = now - a_u.get("last_duel", 0)
    if diff < DUEL_COOLDOWN:
        left = DUEL_COOLDOWN - diff
        return f"🥊 {a_name}, ти нещодавно бився! Наступна дуель через {format_time_left(left)}"

    d1 = random.randint(1, 10)
    d2 = random.randint(1, 10)
    while d1 == d2:
        d2 = random.randint(1, 10)

    if d1 > d2:
        db.transfer_duel(attacker.id, defender.id, bet_amount)
        return (
            f"🥊 <b>Дуель: {a_name} проти {d_name} на {bet_amount} см!</b>\n"
            f"🎲 Кидок: {a_name} ({d1}) vs {d_name} ({d2})\n\n"
            f"🏆 <b>Переміг {a_name}!</b> Відібрав +{bet_amount} см у суперника.\n"
            f"📏 {a_name}: {a_len + bet_amount} см | {d_name}: {d_len - bet_amount} см"
        )
    else:
        db.transfer_duel(defender.id, attacker.id, bet_amount)
        return (
            f"🥊 <b>Дуель: {a_name} проти {d_name} на {bet_amount} см!</b>\n"
            f"🎲 Кидок: {a_name} ({d1}) vs {d_name} ({d2})\n\n"
            f"💥 <b>{a_name} програв дуель!</b> {d_name} забирає +{bet_amount} см.\n"
            f"📏 {d_name}: {d_len + bet_amount} см | {a_name}: {a_len - bet_amount} см"
        )

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
        f"Користуйся кнопками внизу або командами в чаті:\n"
        f"• «🍆 Пісюн» — поміряти розмір раз на добу\n"
        f"• «🎰 Казино (5 см)» — гра на 5 см (або напиши: <code>ставка 10</code>)\n"
        f"• «🥊 Дуель» — бій із другом (відповідай словом: <code>дуель 3</code>)\n"
        f"• «🏆 Топ 10» — рейтинг лідерів чату"
    )
    await msg.answer(text, reply_markup=get_reply_keyboard(), parse_mode="HTML")

# Admin command: /give
@router.message(F.text.func(lambda t: any(k in t.lower() for k in ["give", "додати", "бонус", "накрутити"])))
async def handle_admin_give(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return

    match = re.search(r'\d+', msg.text)
    amount = int(match.group()) if match else 20

    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
    else:
        target = msg.from_user

    t_name = target.first_name or target.username or "Гравець"
    t_u = db.get_user(target.id, t_name, target.username)
    if msg.chat.type in ("group", "supergroup"):
        db.register_chat(msg.chat.id, target.id)

    new_len = t_u.get("length", 0) + amount
    conn = db._get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET length = ? WHERE user_id = ?", (new_len, target.id))
        conn.commit()
    finally:
        conn.close()

    await msg.answer(f"👑 <b>Адмін-бонус:</b> {t_name} отримав <b>+{amount} см</b>!\nТепер його розмір: <b>{new_len} см</b> {get_badge(new_len)}", parse_mode="HTML")

# Admin command: /reset
@router.message(Command("reset"))
async def handle_admin_reset(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        return
    conn = db._get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_grow = 0, last_casino = 0, last_duel = 0 WHERE user_id = ?", (msg.from_user.id,))
        conn.commit()
    finally:
        conn.close()
    await msg.answer("⚡ <b>Таймери скинуто!</b> Можна знову ростити, грати в казино та дуелитися.", parse_mode="HTML")

# Grow
@router.message(Command("grow"))
@router.message(F.text.func(lambda t: any(k in t.lower() for k in ["пісюн", "песюн", "ростити", "поміряти"])))
async def handle_grow(msg: Message):
    reply = do_grow(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# Top
@router.message(Command("top"))
@router.message(F.text.func(lambda t: "топ" in t.lower() or "top" in t.lower()))
async def handle_top(msg: Message):
    reply = do_top(msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# My Size
@router.message(Command("my"))
@router.message(F.text.func(lambda t: "розмір" in t.lower() or "мій песюн" in t.lower() or "мій пісюн" in t.lower()))
async def handle_my(msg: Message):
    reply = do_my(msg.from_user, msg.chat)
    await msg.answer(reply, reply_markup=get_reply_keyboard())

# Casino Button / Command (ставка, казино, bet)
@router.message(Command("casino"))
@router.message(F.text.func(lambda t: any(k in t.lower() for k in ["казино", "ставка", "bet", "casino"])))
async def handle_casino(msg: Message):
    try:
        user = msg.from_user
        name = user.first_name or user.username or "Гравець"
        u = db.get_user(user.id, name, user.username)
        if msg.chat.type in ("group", "supergroup"):
            db.register_chat(msg.chat.id, user.id)

        match = re.search(r'\d+', msg.text)
        bet = int(match.group()) if match else 5
        if bet <= 0:
            bet = 5
        if bet > 20:
            await msg.answer(f"{name}, максимальна ставка в казино — 20 см!")
            return

        cur_len = u.get("length", 0)
        if cur_len < bet:
            await msg.answer(f"{name}, у тебе замало сантиметрів! Твій розмір: {cur_len} см, а ставка: {bet} см.")
            return

        now = int(time.time())
        diff = now - u.get("last_casino", 0)
        if diff < CASINO_COOLDOWN:
            left = CASINO_COOLDOWN - diff
            await msg.answer(f"🎰 {name}, відпочинь від казино! Наступна ставка через {format_time_left(left)}")
            return

        # 1. Відправляємо справжній живий 3D-кубик Telegram
        dice_msg = await msg.answer_dice(emoji="🎲")
        dice_val = dice_msg.dice.value

        # Чекаємо поки закінчиться анімація кидка кубика (2.5 сек)
        await asyncio.sleep(2.5)

        # 4, 5, 6 — виграш, 1, 2, 3 — програш
        if dice_val >= 4:
            new_len = cur_len + bet
            db.update_casino(user.id, new_len)
            text = (
                f"🎉 <b>Випало {dice_val}! ПЕРЕМОГА (+{bet} см)</b> 🥳\n"
                f"📏 {name}, твій новий розмір: <b>{new_len} см</b> {get_badge(new_len)}"
            )
        else:
            new_len = max(0, cur_len - bet)
            db.update_casino(user.id, new_len)
            text = (
                f"💥 <b>Випало {dice_val}... ПРОГРАШ (-{bet} см)</b> 🤏\n"
                f"📏 {name}, твій новий розмір: <b>{new_len} см</b> {get_badge(new_len)}"
            )

        await dice_msg.reply(text, reply_markup=get_reply_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in handle_casino: {e}", exc_info=True)
        await msg.answer("⚠️ Помилка казино. Спробуйте ще раз!")

# Duel Info Button / Duel execution
@router.message(Command("duel"))
@router.message(F.text.func(lambda t: any(k in t.lower() for k in ["дуель", "duel", "бій"])))
async def handle_duel(msg: Message):
    try:
        if msg.chat.type not in ("group", "supergroup"):
            await msg.answer("⚔️ Дуелі доступні тільки у спільних групах з друзями!")
            return

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            text = (
                f"⚔️ <b>Як викликати друга на дуель?</b>\n\n"
                f"1. Зроби <b>відповідь (Reply)</b> на повідомлення друга в чаті.\n"
                f"2. Напиши: <code>дуель 3</code> (або просто <code>дуель</code>).\n"
                f"3. Переможець забере сантиметри в суперника!"
            )
            await msg.answer(text, reply_markup=get_reply_keyboard(), parse_mode="HTML")
            return

        match = re.search(r'\d+', msg.text)
        bet = int(match.group()) if match else 3
        reply = do_duel(msg.from_user, msg.reply_to_message.from_user, msg.chat, bet)
        await msg.answer(reply, reply_markup=get_reply_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in handle_duel: {e}", exc_info=True)
        await msg.answer("⚠️ Помилка дуелі. Спробуйте ще раз!")

# Help
@router.message(Command("help"))
async def handle_help(msg: Message):
    text = (
        "🎮 <b>Команди PisunBot:</b>\n\n"
        "🍆 <b>/grow</b> — ростити свій розмір раз на добу\n"
        "📏 <b>/my</b> — дізнатися поточний розмір і таймер\n"
        "🎰 <b>/casino</b> (або <code>ставка 5</code>) — рулетка на см (макс 20 см)\n"
        "⚔️ <b>/duel</b> (або <code>дуель 3</code> у відповідь другові) — бій\n"
        "🏆 <b>/top</b> — рейтинг лідерів чату"
    )
    await msg.answer(text, reply_markup=get_reply_keyboard(), parse_mode="HTML")

# --- Render Health Check Server ---
async def health(request):
    return web.Response(text="OK, PisunBot 2.0 with Fixes is alive 24/7!", status=200)

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
    
    # Реєстрація команд в меню Telegram
    try:
        await bot.set_my_commands([
            BotCommand(command="grow", description="🍆 Ростити розмір"),
            BotCommand(command="my", description="📏 Мій розмір"),
            BotCommand(command="casino", description="🎰 Казино (рулетка)"),
            BotCommand(command="duel", description="⚔️ Дуель з другом"),
            BotCommand(command="top", description="🏆 Топ лідерів"),
            BotCommand(command="help", description="ℹ️ Довідка та команди")
        ])
    except Exception as e:
        logger.warning(f"Could not set commands menu: {e}")

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
