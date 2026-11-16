"""
🔮 Таро-бот · колода Terra Volatile · большие расклады · подписка (Telegram Stars)

Запуск:
    pip install -r requirements.txt
    export BOT_TOKEN="..."  ADMIN_ID="твой_telegram_id"
    python bot.py
"""
import asyncio
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, LabeledPrice, Message, PreCheckoutQuery,
)

import db
from deck import SUITS, build_deck, draw, pool_for
from spreads import BIG, SMALL, SPREADS, mathers_first_method, positions_of

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
IMG_DIR = Path(__file__).parent / "cards"

# дни → цена в Telegram Stars (XTR)
PLANS = {30: 150, 90: 390, 365: 1290}

dp = Dispatcher()

# ───────────────────────── форматирование ─────────────────────────


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def meaning(card: dict, rev: bool, full: bool = True) -> str:
    kw = card["rev"] if rev else card["up"]
    if full and card.get("theme"):
        kw = f"{kw} — в сфере {card['theme']}"
    return cap(kw) + "."


def short_kw(card: dict, rev: bool) -> str:
    kw = (card["rev"] if rev else card["up"]).split(",")[:2]
    return "; ".join(k.strip() for k in kw)


def name_line(card: dict, rev: bool) -> str:
    return f"{card['icon']} <b>{card['name']}</b>" + (" ⟲" if rev else "")


def split_messages(parts: list[str], limit: int = 3500) -> list[str]:
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 2 > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def card_blocks(key: str, drawn: list[tuple[dict, bool]]) -> list[str]:
    sp = SPREADS[key]
    labels = [p[0] for p in positions_of(key)]
    single = len(drawn) == 1
    parts = [f"{sp['title']}\n━━━━━━━━━━━━━━"]
    for i, (label, (card, rev)) in enumerate(zip(labels, drawn), start=1):
        head = "" if single else f"<b>{i}. {label}</b>\n"
        parts.append(f"{head}{name_line(card, rev)}\n<i>{meaning(card, rev)}</i>")
    if key == "yesno":
        parts.append("❌ <b>Скорее НЕТ</b>" if drawn[0][1] else "✅ <b>Скорее ДА</b>")
    return parts


def mathers_blocks(rng: random.Random, u) -> list[str]:
    deck = build_deck(u["cups_mode"], bool(u["alts"]), rng, need78=True)
    A, C, E, F = mathers_first_method(deck, rng)
    flip = lambda cards: [(c, bool(u["reversals"]) and rng.random() < 0.35) for c in cards]
    horseshoes = [
        ("Подкова I · Прошлое / ты сам", flip(A)),
        ("Подкова II · Настоящее / обстоятельства", flip(C)),
        ("Подкова III · Будущее / путь", flip(E)),
    ]
    parts = [
        f"{SPREADS['mathers']['title']}\n━━━━━━━━━━━━━━\n"
        f"Колода разложена на кучки: A — {len(A)}, C — {len(C)}, E — {len(E)}. "
        f"Кучка F ({len(F)} карт) отложена — к вопросу она не относится.\n"
        "<i>Читай подкову справа налево, затем пары: первая с последней, вторая с предпоследней…</i>"
    ]
    for title, items in horseshoes:
        n = len(items)
        row = " · ".join(f"{i}. {c['name']}{'⟲' if r else ''}" for i, (c, r) in enumerate(items, 1))
        parts.append(f"<b>{title}</b> ({n} карт)\n<i>Ряд справа налево:</i>\n{row}")
        for i in range(n // 2):
            (a, ra), (b, rb) = items[i], items[n - 1 - i]
            parts.append(
                f"<b>{i + 1} ⟷ {n - i}</b>\n"
                f"{name_line(a, ra)} — <i>{short_kw(a, ra)}</i>\n"
                f"{name_line(b, rb)} — <i>{short_kw(b, rb)}</i>"
            )
        if n % 2:
            m, rm = items[n // 2]
            parts.append(f"<b>{n // 2 + 1} (середина)</b>\n{name_line(m, rm)} — <i>{short_kw(m, rm)}</i>")
    return parts


def image_paths(drawn):
    paths = []
    for card, _ in drawn:
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = IMG_DIR / f"{card['id']}.{ext}"
            if p.exists():
                paths.append(p)
                break
        else:
            return []
    return paths


# ───────────────────────── клавиатуры ─────────────────────────

def btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🌅 Карта дня", "spread:day"), btn("⚖️ Да / Нет", "spread:yesno")],
        [btn("⏳ Прошлое · Настоящее · Будущее", "spread:three")],
        [btn("📚 Большие расклады", "big")],
        [btn("⚙️ Колода", "settings"), btn("💎 Подписка", "sub")],
    ])


def big_menu() -> InlineKeyboardMarkup:
    rows = [[btn(SPREADS[k]["title"], f"spread:{k}")] for k in BIG]
    rows.append([btn("◀️ Назад", "menu:edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("🔮 Новый расклад", "menu:new")]])


def sub_kb() -> InlineKeyboardMarkup:
    rows = [[btn(f"⭐ {days} дн. — {stars} Stars", f"buy:{days}")] for days, stars in PLANS.items()]
    rows.append([btn("◀️ Назад", "menu:edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


CUPS_LABEL = {"cups": "Кубки (классика)", "vessels": "Сосуды вместо Кубков", "both": "Обе масти (5 мастей)"}


def settings_text_kb(uid: int):
    u = db.user(uid)
    text = (
        "⚙️ <b>Колода Terra Volatile</b>\n\n"
        f"Масть воды: <b>{CUPS_LABEL[u['cups_mode']]}</b>\n"
        f"Альтернативные карты: <b>{'вкл' if u['alts'] else 'выкл'}</b>\n"
        f"Перевёрнутые карты: <b>{'вкл' if u['reversals'] else 'выкл'}</b>\n\n"
        "<i>Методы на 78 карт (Мазерс) всегда используют ровно 78: при «обеих мастях» берутся Кубки.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("💧 Масть воды", "set:cups")],
        [btn("🔀 Альтернативы", "set:alts"), btn("⟲ Перевёрнутые", "set:reversals")],
        [btn("◀️ Назад", "menu:edit")],
    ])
    return text, kb


WELCOME = (
    "🌙 <b>Таро · Terra Volatile</b>\n\n"
    "Алхимическая колода, 5 мастей, альтернативные арканы и большие расклады — "
    "от Кельтского креста до Первого способа Мазерса.\n\n"
    f"Бесплатно: {db.FREE_PER_DAY} расклада в день. Безлимит — по подписке 💎"
)


async def safe_edit(msg: Message, text: str, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=kb)


# ───────────────────────── хендлеры ─────────────────────────

@dp.message(CommandStart())
@dp.message(Command("menu"))
async def start(m: Message):
    db.user(m.from_user.id)
    await m.answer(WELCOME, reply_markup=main_menu())


@dp.message(Command("status"))
async def status(m: Message):
    uid = m.from_user.id
    if db.is_premium(uid):
        until = datetime.fromtimestamp(db.premium_until(uid)).strftime("%d.%m.%Y")
        await m.answer(f"💎 Подписка активна до <b>{until}</b>. Расклады без лимита.")
    else:
        await m.answer(f"Сегодня осталось бесплатных раскладов: <b>{db.left_today(uid)}</b> из {db.FREE_PER_DAY}.",
                       reply_markup=sub_kb())


@dp.callback_query(F.data.startswith("menu:"))
async def to_menu(c: CallbackQuery):
    if c.data == "menu:new":
        await c.message.answer("Выбери расклад 👇", reply_markup=main_menu())
    else:
        await safe_edit(c.message, "Выбери расклад 👇", main_menu())
    await c.answer()


@dp.callback_query(F.data == "big")
async def big(c: CallbackQuery):
    text = "📚 <b>Большие расклады</b>\n\n" + "\n".join(
        f"{SPREADS[k]['title']} — <i>{SPREADS[k]['intro']}</i>" for k in BIG)
    await safe_edit(c.message, text, big_menu())
    await c.answer()


@dp.callback_query(F.data == "settings")
async def settings(c: CallbackQuery):
    text, kb = settings_text_kb(c.from_user.id)
    await safe_edit(c.message, text, kb)
    await c.answer()


@dp.callback_query(F.data.startswith("set:"))
async def set_option(c: CallbackQuery):
    what = c.data.split(":")[1]
    if what == "cups":
        db.cycle_cups(c.from_user.id)
    else:
        db.toggle(c.from_user.id, what)
    text, kb = settings_text_kb(c.from_user.id)
    await safe_edit(c.message, text, kb)
    await c.answer("Сохранено")


@dp.callback_query(F.data == "sub")
async def sub(c: CallbackQuery):
    uid = c.from_user.id
    if db.is_premium(uid):
        until = datetime.fromtimestamp(db.premium_until(uid)).strftime("%d.%m.%Y")
        head = f"💎 Подписка активна до <b>{until}</b>. Можно продлить:"
    else:
        head = (f"💎 <b>Таро+</b>\n\nБез подписки — {db.FREE_PER_DAY} расклада в день. "
                "С подпиской — безлимит на все расклады, включая Мазерса и Кельтский крест.")
    await safe_edit(c.message, head, sub_kb())
    await c.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    days = int(c.data.split(":")[1])
    if days not in PLANS:
        return await c.answer()
    await c.message.answer_invoice(
        title=f"Таро+ на {days} дн.",
        description="Безлимитные расклады во всех режимах.",
        payload=f"sub:{days}",
        provider_token="",          # для Stars токен провайдера не нужен
        currency="XTR",
        prices=[LabeledPrice(label=f"Таро+ {days} дн.", amount=PLANS[days])],
    )
    await c.answer()


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(m: Message):
    pay = m.successful_payment
    days = int(pay.invoice_payload.split(":")[1])
    db.log_payment(pay.telegram_payment_charge_id, m.from_user.id, pay.total_amount, days)
    until = datetime.fromtimestamp(db.add_premium(m.from_user.id, days)).strftime("%d.%m.%Y")
    await m.answer(f"✨ Спасибо! Подписка активна до <b>{until}</b>.", reply_markup=main_menu())


@dp.message(Command("paysupport"))
async def paysupport(m: Message):
    await m.answer("По вопросам оплаты и возвратов напиши администратору бота.")


@dp.message(Command("grant"))
async def grant(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, days = m.text.split()
        until = db.add_premium(int(uid), int(days))
        await m.answer(f"Ок, до {datetime.fromtimestamp(until):%d.%m.%Y}")
    except ValueError:
        await m.answer("Формат: /grant user_id days")


@dp.message(Command("refund"))
async def refund(m: Message, bot: Bot):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, charge = m.text.split()
        await bot.refund_star_payment(user_id=int(uid), telegram_payment_charge_id=charge)
        await m.answer("Возврат выполнен.")
    except Exception as e:  # noqa: BLE001
        await m.answer(f"Ошибка: {e}\nФормат: /refund user_id charge_id")


@dp.callback_query(F.data.startswith("spread:"))
async def do_spread(c: CallbackQuery):
    key = c.data.split(":", 1)[1]
    uid = c.from_user.id
    await c.answer()

    left = db.left_today(uid)
    if left == 0:
        await c.message.answer(
            f"🔒 Бесплатные расклады на сегодня закончились ({db.FREE_PER_DAY}/{db.FREE_PER_DAY}).\n"
            "Приходи завтра или оформи подписку 💎 — безлимит.",
            reply_markup=sub_kb())
        return

    sp = SPREADS[key]
    status_msg = await c.message.answer(f"🔮 <i>Тасую колоду…</i>\n{sp['intro']}")
    await asyncio.sleep(1.2)
    await safe_edit(status_msg, "🕯 <i>Карты ложатся на стол…</i>")
    await asyncio.sleep(1.0)

    u = db.user(uid)
    rng = random.Random(f"{uid}-{db.today()}") if key == "day" else random.Random()
    paths: list[Path] = []

    if key == "mathers":
        parts = mathers_blocks(rng, u)
    else:
        deck = build_deck(u["cups_mode"], bool(u["alts"]), rng)
        drawn, used = [], set()
        for _label, pool in positions_of(key):
            # масти «Сосуды» для расклада стихий берём независимо от настроек колоды
            card, rev = draw(pool_for(deck, pool), 1, bool(u["reversals"]), rng, used)[0]
            used.add(card["id"])
            drawn.append((card, rev))
        parts = card_blocks(key, drawn)
        if len(drawn) <= 10:
            paths = image_paths(drawn)

    db.register_use(uid)
    left = db.left_today(uid)
    footer = ("🔮 <i>Карты показывают тенденцию, выбор всегда за тобой.</i>"
              + ("" if left is None else f"\n\nБесплатных раскладов сегодня осталось: {left}"))
    parts.append(footer)

    if paths:
        try:
            await c.message.answer_media_group([InputMediaPhoto(media=FSInputFile(p)) for p in paths])
        except Exception:  # noqa: BLE001
            logging.exception("images failed")

    try:
        await status_msg.delete()
    except TelegramBadRequest:
        pass
    msgs = split_messages(parts)
    for i, t in enumerate(msgs):
        await c.message.answer(t, reply_markup=after_kb() if i == len(msgs) - 1 else None)


async def main():
    if not TOKEN:
        raise SystemExit("Задай переменную окружения BOT_TOKEN")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
