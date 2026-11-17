"""
🔮 Таро-бот · колода Terra Volatile · расклады, свой вопрос, авторские расклады,
ручной выбор карт, хорарный разбор, подписка (Telegram Stars), AI-разбор (по желанию).

Переменные: BOT_TOKEN, ADMIN_ID, FREE_PER_DAY, TZ_NAME, DB_PATH,
            ANTHROPIC_API_KEY (необязательно), AI_MODEL, AI_FOR_FREE
"""
import asyncio
import html
import logging
import os
import random
import re
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

import ai
import db
from deck import build_deck, draw, pool_for
from horary import timing, verdict
from spreads import BIG, SPREADS, mathers_first_method, positions_of
from texts import SPREAD_OPEN, literary, summary

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
IMG_DIR = Path(__file__).parent / "cards"
PLANS = {30: 150, 90: 390, 365: 1290}   # дни → Stars

dp = Dispatcher()
WAIT: dict[int, dict] = {}        # ждём текст от пользователя
PICK: dict[int, dict] = {}        # ручной выбор карт
QUESTIONS: dict[int, str] = {}    # последний заданный вопрос

# ───────────────────────── форматирование ─────────────────────────


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def short_kw(card: dict, rev: bool) -> str:
    kw = (card["rev"] if rev else card["up"]).split(",")[:2]
    return "; ".join(k.strip() for k in kw)


def name_line(card: dict, rev: bool) -> str:
    return f"{card['icon']} <b>{card['name']}</b>" + (" ⟲ <i>перевёрнутая</i>" if rev else "")


def split_messages(parts: list[str], limit: int = 3600) -> list[str]:
    out, cur = [], ""
    for p in parts:
        while len(p) > limit:                      # очень длинный кусок режем по абзацам
            cut = p.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:cut])
            p = p[cut:].lstrip("\n")
        if cur and len(cur) + len(p) + 2 > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def reading_blocks(key: str, positions, drawn, question: str | None) -> list[str]:
    sp = SPREADS[key]
    parts = [f"{sp['title']}\n━━━━━━━━━━━━━━"]
    if question:
        parts.append(f"❓ <b>Вопрос:</b> «{esc(question)}»")
    if SPREAD_OPEN.get(key):
        parts.append(f"<i>{SPREAD_OPEN[key]}</i>")
    single = len(drawn) == 1
    for i, ((label, _pool), (card, rev)) in enumerate(zip(positions, drawn), start=1):
        head = "" if single else f"<b>{i}. {label}</b>\n"
        parts.append(f"{head}{name_line(card, rev)}\n{literary(card, rev)}")
    if key == "yesno":
        parts.append("❌ <b>Скорее НЕТ</b>" if drawn[0][1] else "✅ <b>Скорее ДА</b>")
    if key == "horary" and len(drawn) == 8:
        parts.append("⚖️ <b>Вердикт</b>\n" + verdict(drawn))
        c, r = drawn[7]
        parts.append("⏳ <b>Срок</b>\n" + timing(c, r) +
                     "\n<i>Условное соглашение: Жезлы — дни, Мечи — недели, Кубки — месяцы, "
                     "Монеты — годы, Сосуды — лунные циклы; число — ранг карты.</i>")
    s = summary(drawn)
    if s:
        parts.append(s)
    return parts


def mathers_blocks(rng: random.Random, u, question: str | None) -> list[str]:
    deck = build_deck(u["cups_mode"], bool(u["alts"]), rng, need78=True)
    A, C, E, F_ = mathers_first_method(deck, rng)
    flip = lambda cards: [(c, bool(u["reversals"]) and rng.random() < 0.35) for c in cards]
    horseshoes = [
        ("Подкова I · Прошлое / ты сам", flip(A)),
        ("Подкова II · Настоящее / обстоятельства", flip(C)),
        ("Подкова III · Будущее / путь", flip(E)),
    ]
    parts = [f"{SPREADS['mathers']['title']}\n━━━━━━━━━━━━━━"]
    if question:
        parts.append(f"❓ <b>Вопрос:</b> «{esc(question)}»")
    parts.append(f"<i>{SPREAD_OPEN['mathers']}</i>\n\n"
                 f"Колода разложена на кучки: A — {len(A)}, C — {len(C)}, E — {len(E)}. "
                 f"Кучка F ({len(F_)} карт) отложена и в чтении не участвует.\n"
                 "Читай подкову справа налево, затем пары: первая с последней, вторая с предпоследней…")
    for title, items in horseshoes:
        n = len(items)
        row = " · ".join(f"{i}. {c['name']}{'⟲' if r else ''}" for i, (c, r) in enumerate(items, 1))
        parts.append(f"<b>{title}</b> ({n} карт)\n<i>Ряд справа налево:</i>\n{row}")
        for i in range(n // 2):
            (a, ra), (b, rb) = items[i], items[n - 1 - i]
            parts.append(f"<b>{i + 1} ⟷ {n - i}</b>\n"
                         f"{name_line(a, ra)} — <i>{short_kw(a, ra)}</i>\n"
                         f"{name_line(b, rb)} — <i>{short_kw(b, rb)}</i>")
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
        [btn("❓ Свой вопрос", "ask"), btn("🔭 Хорарный разбор", "horary")],
        [btn("📚 Большие расклады", "big"), btn("✍️ Авторский расклад", "author")],
        [btn("⚙️ Колода", "settings"), btn("💎 Подписка", "sub")],
    ])


def big_menu() -> InlineKeyboardMarkup:
    rows = [[btn(SPREADS[k]["title"], f"spread:{k}")] for k in BIG]
    rows.append([btn("◀️ Назад", "menu:edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


QUESTION_SPREADS = ["yesno", "three", "celtic", "tree", "houses", "elements", "horary", "mathers"]


def question_kb() -> InlineKeyboardMarkup:
    rows = [[btn(SPREADS[k]["title"], f"qs:{k}")] for k in QUESTION_SPREADS]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("🔮 Новый расклад", "menu:new")]])


def sub_kb() -> InlineKeyboardMarkup:
    rows = [[btn(f"⭐ {d} дн. — {s} Stars", f"buy:{d}")] for d, s in PLANS.items()]
    rows.append([btn("◀️ Назад", "menu:edit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


CUPS_LABEL = {"cups": "Кубки (классика)", "vessels": "Сосуды вместо Кубков", "both": "Обе масти (5 мастей)"}


def settings_text_kb(uid: int):
    u = db.user(uid)
    onoff = lambda v: "вкл" if v else "выкл"
    text = (
        "⚙️ <b>Колода Terra Volatile</b>\n\n"
        f"Масть воды: <b>{CUPS_LABEL[u['cups_mode']]}</b>\n"
        f"Альтернативные карты: <b>{onoff(u['alts'])}</b>\n"
        f"Дополнительные карты: <b>{onoff(u['extras'])}</b>\n"
        f"Перевёрнутые карты: <b>{onoff(u['reversals'])}</b>\n"
        f"Выбор карт: <b>{'вручную' if u['pick'] else 'случайно'}</b>\n\n"
        "<i>Мазерс использует ровно 78 карт: дополнения в нём не участвуют, а «обе масти» сводятся к Кубкам. "
        "Расклады с жёсткими масть-позициями (Пять стихий, Год, Хорарный) тянутся случайно.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("💧 Масть воды", "set:cups")],
        [btn("🔀 Альтернативы", "set:alts"), btn("✦ Дополнения", "set:extras")],
        [btn("⟲ Перевёрнутые", "set:reversals"), btn("🖐 Выбор карт", "set:pick")],
        [btn("◀️ Назад", "menu:edit")],
    ])
    return text, kb


WELCOME = (
    "🌙 <b>Таро · Terra Volatile</b>\n\n"
    "Алхимическая колода, 5 мастей, альтернативные и дополнительные карты. "
    "Задай свой вопрос, составь авторский расклад или попроси хорарный разбор.\n\n"
    f"Бесплатно: {db.FREE_PER_DAY} расклада в день. Безлимит и развёрнутый разбор — по подписке 💎"
)


async def safe_edit(msg: Message, text: str, kb=None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=kb)


async def paywall(msg: Message):
    await msg.answer(
        f"🔒 Бесплатные расклады на сегодня закончились ({db.FREE_PER_DAY}/{db.FREE_PER_DAY}).\n"
        "Приходи завтра или оформи подписку 💎 — безлимит.", reply_markup=sub_kb())


# ───────────────────────── меню и подписка ─────────────────────────

@dp.message(CommandStart())
@dp.message(Command("menu"))
async def start(m: Message):
    db.user(m.from_user.id)
    WAIT.pop(m.from_user.id, None)
    await m.answer(WELCOME, reply_markup=main_menu())


@dp.message(Command("cancel"))
async def cancel(m: Message):
    for d in (WAIT, PICK, QUESTIONS):
        d.pop(m.from_user.id, None)
    await m.answer("Отменено.", reply_markup=main_menu())


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
                "С подпиской — безлимит на все расклады и развёрнутый литературный разбор.")
    await safe_edit(c.message, head, sub_kb())
    await c.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    days = int(c.data.split(":")[1])
    if days not in PLANS:
        return await c.answer()
    await c.message.answer_invoice(
        title=f"Таро+ на {days} дн.", description="Безлимитные расклады и развёрнутый разбор.",
        payload=f"sub:{days}", provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"Таро+ {days} дн.", amount=PLANS[days])])
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


# ───────────────────────── вопрос / авторский / хорарный ─────────────────────────

@dp.callback_query(F.data == "ask")
async def ask(c: CallbackQuery):
    await c.answer()
    if db.left_today(c.from_user.id) == 0:
        return await paywall(c.message)
    WAIT[c.from_user.id] = {"mode": "question"}
    await c.message.answer(
        "✍️ <b>Задай свой вопрос</b>\n\nНапиши его одним сообщением: чем конкретнее, тем точнее расклад. "
        "Например: «Стоит ли мне менять работу этой осенью?»\n\n/cancel — отмена")


@dp.callback_query(F.data == "horary")
async def horary(c: CallbackQuery):
    await c.answer()
    if db.left_today(c.from_user.id) == 0:
        return await paywall(c.message)
    WAIT[c.from_user.id] = {"mode": "horary_question"}
    await c.message.answer(
        "🔭 <b>Хорарный разбор</b>\n\nЭто разбор одного конкретного вопроса: кто ты в нём, что или кто его предмет, "
        "суть, преграды, помощь, скрытое влияние, исход, вердикт и ориентировочный срок.\n\n"
        "Напиши вопрос одним сообщением, чётко и с одним предметом "
        "(лучше «Напишет ли мне Иван до конца месяца?», чем «Что будет у нас?»).\n\n/cancel — отмена")


@dp.callback_query(F.data == "author")
async def author(c: CallbackQuery):
    await c.answer()
    if db.left_today(c.from_user.id) == 0:
        return await paywall(c.message)
    WAIT[c.from_user.id] = {"mode": "author_positions"}
    await c.message.answer(
        "✍️ <b>Авторский расклад</b>\n\nПришли названия позиций, <b>каждую с новой строки</b> (от 2 до 12). Например:\n\n"
        "Что у него в мыслях\nЧто он чувствует\nКогда проявится\nЧто с практикой\n\n"
        "Карты возьмутся из твоей колоды, в том числе дополнительные (⚙️ Колода).\n\n/cancel — отмена")


@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(m: Message):
    uid = m.from_user.id
    st = WAIT.get(uid)
    if not st:
        return await m.answer("Нажми /menu, чтобы выбрать расклад 🔮")
    text = m.text.strip()
    mode = st["mode"]

    if mode == "question":
        WAIT.pop(uid)
        QUESTIONS[uid] = text[:400]
        await m.answer(f"Твой вопрос: «{esc(text[:400])}»\n\nВыбери расклад, на котором будем отвечать:",
                       reply_markup=question_kb())

    elif mode == "horary_question":
        WAIT.pop(uid)
        QUESTIONS[uid] = text[:400]
        await begin_reading(m, uid, "horary", question=text[:400])

    elif mode == "author_positions":
        labels = []
        for line in re.split(r"[\n;]+", text):
            line = re.sub(r"^\s*(?:\d+[.)]|[-•—])\s*", "", line).strip()
            if line:
                labels.append(esc(line[:60]))
        if not 2 <= len(labels) <= 12:
            return await m.answer("Нужно от 2 до 12 позиций, каждая с новой строки. Попробуй ещё раз или /cancel.")
        st.update(mode="author_question", positions=[(lb, None) for lb in labels])
        await m.answer("Принято ✨ Теперь напиши вопрос к раскладу или «-», чтобы без вопроса.")

    elif mode == "author_question":
        WAIT.pop(uid)
        q = None if text == "-" else text[:400]
        if q:
            QUESTIONS[uid] = q
        await begin_reading(m, uid, "author", question=q, positions=st["positions"])


@dp.callback_query(F.data.startswith("qs:"))
async def question_spread(c: CallbackQuery):
    await c.answer()
    q = QUESTIONS.get(c.from_user.id)
    if not q:
        return await c.message.answer("Вопрос потерялся. Нажми «❓ Свой вопрос» и напиши его заново.")
    await begin_reading(c.message, c.from_user.id, c.data.split(":", 1)[1], question=q)


# ───────────────────────── расклад ─────────────────────────

@dp.callback_query(F.data.startswith("spread:"))
async def spread(c: CallbackQuery):
    await c.answer()
    await begin_reading(c.message, c.from_user.id, c.data.split(":", 1)[1])


def draw_for(positions, u, rng):
    deck = build_deck(u["cups_mode"], bool(u["alts"]), rng, extras=bool(u["extras"]))
    used, drawn = set(), []
    for _label, pool in positions:
        card, rev = draw(pool_for(deck, pool), 1, bool(u["reversals"]), rng, used)[0]
        used.add(card["id"])
        drawn.append((card, rev))
    return drawn


async def begin_reading(msg: Message, uid: int, key: str, question=None, positions=None):
    if db.left_today(uid) == 0:
        return await paywall(msg)
    positions = positions or positions_of(key)
    u = db.user(uid)
    pick_ok = (u["pick"] and key not in ("day", "mathers")
               and all(p is None for _l, p in positions))
    if not pick_ok:
        return await run_reading(msg, uid, key, question, positions)

    rng = random.Random()
    deck = build_deck(u["cups_mode"], bool(u["alts"]), rng, extras=bool(u["extras"]))
    rng.shuffle(deck)
    size = min(max(2 * len(positions), 12), 30)
    fan = [(c, bool(u["reversals"]) and rng.random() < 0.35) for c in deck[:size]]
    PICK[uid] = dict(key=key, question=question, positions=positions, fan=fan, picks=[])
    await msg.answer(pick_text(uid), reply_markup=pick_kb(uid))


def pick_text(uid: int) -> str:
    st = PICK[uid]
    n, k = len(st["positions"]), len(st["picks"])
    label = st["positions"][k][0]
    return (f"🎴 <b>Выбери карты</b> ({k}/{n})\n\nСосредоточься на вопросе и коснись карты, которая тебя зовёт.\n"
            f"Сейчас позиция: <b>{label}</b>")


def pick_kb(uid: int) -> InlineKeyboardMarkup:
    st = PICK[uid]
    rows, row = [], []
    for i in range(len(st["fan"])):
        row.append(btn("✨" if i in st["picks"] else "🎴", f"pk:{i}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("pk:"))
async def pick(c: CallbackQuery):
    uid = c.from_user.id
    st = PICK.get(uid)
    if not st:
        return await c.answer("Выбор устарел, начни расклад заново", show_alert=True)
    i = int(c.data.split(":")[1])
    if i in st["picks"]:
        return await c.answer("Эта карта уже выбрана")
    st["picks"].append(i)
    n = len(st["positions"])
    if len(st["picks"]) < n:
        await safe_edit(c.message, pick_text(uid), pick_kb(uid))
        return await c.answer()
    PICK.pop(uid)
    await c.answer("Карты выбраны ✨")
    await safe_edit(c.message, "🎴 Карты выбраны ✨")
    drawn = [st["fan"][j] for j in st["picks"]]
    await run_reading(c.message, uid, st["key"], st["question"], st["positions"], drawn)


async def run_reading(msg: Message, uid: int, key: str, question, positions, drawn=None):
    if db.left_today(uid) == 0:
        return await paywall(msg)
    sp = SPREADS[key]
    u = db.user(uid)
    status_msg = await msg.answer(f"🔮 <i>Тасую колоду…</i>\n{sp['intro']}")
    await asyncio.sleep(1.2)
    await safe_edit(status_msg, "🕯 <i>Карты ложатся на стол…</i>")
    await asyncio.sleep(1.0)

    rng = random.Random(f"{uid}-{db.today()}") if key == "day" else random.Random()
    paths = []
    if key == "mathers":
        parts = mathers_blocks(rng, u, question)
    else:
        if drawn is None:
            drawn = draw_for(positions, u, rng)
        parts = reading_blocks(key, positions, drawn, question)
        if len(drawn) <= 10:
            paths = image_paths(drawn)

    db.register_use(uid)
    left = db.left_today(uid)
    can_ai = (ai.enabled() and key != "mathers" and
              (db.is_premium(uid) or uid == ADMIN_ID or ai.allowed_for_free()))
    footer = "🔮 <i>Карты показывают тенденцию, выбор всегда за тобой.</i>"
    if left is not None:
        footer += f"\n\nБесплатных раскладов сегодня осталось: {left}"
        if ai.enabled() and not can_ai and key != "mathers":
            footer += "\n💎 Развёрнутый литературный разбор по каждой позиции доступен по подписке."
    parts.append(footer)

    if paths:
        try:
            await msg.answer_media_group([InputMediaPhoto(media=FSInputFile(p)) for p in paths])
        except Exception:  # noqa: BLE001
            logging.exception("images failed")
    try:
        await status_msg.delete()
    except TelegramBadRequest:
        pass

    msgs = split_messages(parts)
    for i, t in enumerate(msgs):
        last = i == len(msgs) - 1 and not can_ai
        await msg.answer(t, reply_markup=after_kb() if last else None)

    if can_ai and drawn:
        wait = await msg.answer("✨ <i>Составляю развёрнутый разбор…</i>")
        items = [(html.unescape(re.sub(r"<[^>]+>", "", lb)), c["name"], r, short_kw(c, r))
                 for (lb, _p), (c, r) in zip(positions, drawn)]
        extra = ""
        if key == "horary" and len(drawn) == 8:
            extra = (re.sub(r"<[^>]+>", "", verdict(drawn)) + " Срок: " + timing(*drawn[7]))
        text = await ai.narrative(re.sub(r"[^\w\s·/,-]", "", sp["title"]).strip(), question, items, extra)
        try:
            await wait.delete()
        except TelegramBadRequest:
            pass
        if text:
            chunks = split_messages([ai.to_html(text)])
            for i, t in enumerate(chunks):
                await msg.answer(("📜 <b>Развёрнутый разбор</b>\n\n" if i == 0 else "") + t,
                                 reply_markup=after_kb() if i == len(chunks) - 1 else None)
        else:
            await msg.answer("Не получилось составить развёрнутый разбор, попробуй позже.", reply_markup=after_kb())


async def main():
    if not TOKEN:
        raise SystemExit("Задай переменную окружения BOT_TOKEN")
    logging.basicConfig(level=logging.INFO)
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
