import random
from typing import Tuple

TITLES = [
    (0, 5, "🤏 Малишок"),
    (6, 10, "🥒 Солоний огірочок"),
    (11, 15, "🌶 Юний перчик"),
    (16, 20, "🍆 Гідний боєць"),
    (21, 25, "🦾 Базука"),
    (26, 30, "🐍 Анаконда"),
    (31, 40, "👑 Цар району"),
    (41, 1000, "🛸 Міжгалактичний Дрючок")
]

POSITIVE_EVENTS = [
    ("З'їв вітаміни росту з морквою", (2, 6)),
    ("Сходив на тренування в спортзал", (3, 7)),
    ("Вкусила бджола, з'явився здоровий набряк", (4, 8)),
    ("Подивився гарячі фотки в інтернеті", (3, 6)),
    ("Полився теплою водою", (1, 4)),
    ("Випив енергетик з таурином", (2, 5)),
    ("Знайшов секретну мазь від шамана", (4, 9)),
    ("З'їв кілограм бананів", (2, 5)),
    ("Потягнув на турніку з обтяженням", (3, 7)),
    ("💥 КРИТИЧНИЙ УСПІХ! Знайшов магічну помпу", (10, 15)),
]

NEGATIVE_EVENTS = [
    ("Скупався в ополонці з крижаною водою", (2, 5)),
    ("Спав на животі і сильно притиснув", (1, 3)),
    ("Побачив курс долара і сильно перелякався", (3, 6)),
    ("Спробував підрівняти манікюрними ножицями", (4, 7)),
    ("Подивився на фото колишньої", (2, 5)),
    ("Защемив блискавкою на джинсах", (3, 6)),
    ("Забув вдягнути термобілизну на мороз", (2, 4)),
    ("💀 ФАТАЛЬНИЙ ФАКАП! Злякався шороху в темряві", (6, 9)),
]

def get_title(length: int) -> str:
    for low, high, title in TITLES:
        if low <= length <= high:
            return title
    return "🛸 Невідомий гігант"

def roll_grow() -> Tuple[int, str]:
    """Rolls a random grow or shrink event.
    Returns (delta_cm, event_text)
    """
    # 70% chance positive, 30% chance negative
    is_positive = random.random() < 0.70
    
    if is_positive:
        desc, (min_v, max_v) = random.choice(POSITIVE_EVENTS)
        delta = random.randint(min_v, max_v)
        return delta, f"{desc}: <b>+{delta} см!</b>"
    else:
        desc, (min_v, max_v) = random.choice(NEGATIVE_EVENTS)
        delta = -random.randint(min_v, max_v)
        return delta, f"{desc}: <b>{delta} см!</b>"

def roll_duel() -> Tuple[int, int]:
    """Rolls a dice for duel. Returns (winner_dice, loser_dice)."""
    d1 = random.randint(1, 100)
    d2 = random.randint(1, 100)
    while d1 == d2:
        d2 = random.randint(1, 100)
    return d1, d2
