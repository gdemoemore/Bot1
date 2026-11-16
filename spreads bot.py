"""Расклады. pool: None = вся колода, 'major' = старшие арканы, либо ключ масти."""
from __future__ import annotations

import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = os.getenv("TZ_NAME", "Europe/Moscow")

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def _year_positions():
    start = datetime.now(ZoneInfo(TZ)).month - 1
    pos = [(f"{MONTHS[(start + i) % 12]}", None) for i in range(12)]
    return [("Тема года", "major")] + pos


SPREADS = {
    # ── малые ──
    "day": dict(title="🌅 Карта дня", intro="Главный посыл на сегодня.",
                positions=[("Энергия дня", None)]),
    "yesno": dict(title="⚖️ Да / Нет", intro="Сформулируй вопрос так, чтобы ответом были «да» или «нет».",
                  positions=[("Ответ", None)]),
    "three": dict(title="⏳ Прошлое · Настоящее · Будущее", intro="Классика: откуда пришло и куда ведёт.",
                  positions=[("Прошлое", None), ("Настоящее", None), ("Будущее", None)]),
    # ── большие ──
    "celtic": dict(
        title="🌀 Кельтский крест", big=True,
        intro="Глубокий расклад на сложный вопрос (10 карт).",
        positions=[(p, None) for p in [
            "Суть ситуации", "Вызов / препятствие", "Корни, основа", "Недавнее прошлое",
            "Венец: возможный итог", "Ближайшее будущее", "Ты в ситуации", "Окружение",
            "Надежды и страхи", "Итог"]]),
    "tree": dict(
        title="🌳 Древо Жизни", big=True,
        intro="Десять сефирот — путь от замысла к воплощению (10 карт).",
        positions=[(p, None) for p in [
            "Кетер — высшая цель", "Хохма — импульс, мудрость", "Бина — форма, понимание",
            "Хесед — милость, рост", "Гебура — ограничение, суд", "Тиферет — сердце ситуации",
            "Нецах — желание, победа", "Ход — разум, слово", "Йесод — подсознание, основа",
            "Малкут — результат в материи"]]),
    "houses": dict(
        title="🏛 12 домов", big=True,
        intro="Астрологический расклад: вся жизнь по сферам (13 карт).",
        positions=[(p, None) for p in [
            "Ось вопроса", "I · Личность", "II · Ресурсы", "III · Общение", "IV · Дом, корни",
            "V · Любовь, творчество", "VI · Работа, здоровье", "VII · Партнёрства",
            "VIII · Кризисы, трансформация", "IX · Путь, смыслы", "X · Карьера, призвание",
            "XI · Друзья, надежды", "XII · Тайное, подсознание"]]),
    "year": dict(
        title="📅 Год по месяцам", big=True,
        intro="Тема года и 12 месяцев вперёд (13 карт).",
        positions=_year_positions),
    "elements": dict(
        title="⚗️ Пять стихий", big=True,
        intro="Фирменный расклад под 5 мастей Terra Volatile: по карте из каждой масти + итог.",
        positions=[("Земля — тело, деньги (Монеты)", "coins"),
                   ("Вода — чувства, связи (Кубки)", "cups"),
                   ("Воздух — мысли, слова (Мечи)", "swords"),
                   ("Огонь — воля, действие (Жезлы)", "wands"),
                   ("Эфир — дух, смысл (Сосуды)", "vessels"),
                   ("Квинтэссенция — синтез", "major")]),
    "mathers": dict(
        title="🜏 Первый способ Мазерса", big=True,
        intro="Метод из «The Tarot» (1888): вся колода делится на кучки A, C, E, "
              "которые раскладываются «подковами» и читаются парами.",
        positions=[]),  # особая логика
}

SMALL = ["day", "yesno", "three"]
BIG = ["mathers", "celtic", "tree", "houses", "year", "elements"]


def positions_of(key: str):
    p = SPREADS[key]["positions"]
    return p() if callable(p) else p


# ───────────── Мазерс: Первый способ ─────────────

def _split(cards: list) -> tuple[list, list]:
    """
    Раздача 'две на большую кучку, одна на малую':
    1-я → большая, 2-я → малая, 3–4 → большая, 5 → малая, …
    Карты кладутся рубашкой вверх, поэтому каждая следующая ложится СВЕРХУ:
    итоговый список — сверху вниз (так кучка берётся в руки).
    """
    small, big = [], []
    for i, c in enumerate(cards, start=1):
        if i == 1 or (i - 2) % 3 != 0:
            big.insert(0, c)
        else:
            small.insert(0, c)
    return small, big


def mathers_first_method(deck78: list, rng: random.Random):
    """
    Возвращает (A, C, E, F). F отложена и в чтении не участвует.
    Мазерс называет размеры 26/17/11/24, но его же правило раздачи
    для 35 карт даёт 12 и 23 — следуем правилу раздачи.
    """
    assert len(deck78) == 78
    deck = list(deck78)
    for _ in range(3):          # «тасовать и снимать трижды»
        rng.shuffle(deck)
        cut = rng.randrange(10, 68)
        deck = deck[cut:] + deck[:cut]
    a, b = _split(deck)
    c, d = _split(b)
    e, f = _split(d)
    return a, c, e, f
