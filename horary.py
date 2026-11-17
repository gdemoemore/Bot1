"""Хорарный разбор: тональность карт, вердикт «да/нет» и срок."""
from __future__ import annotations

from deck import MINORS

# тональность по рангу (Туз … Король): +1 благоприятно, -1 тяжело, 0 нейтрально
_BASE = [1, 0, 1, 0, -1, 1, 0, 1, 1, 0, 0, 0, 0, 0]
_SWORD_HARD = {3, 5, 7, 8, 9, 10}
_MAJOR = [1, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, -1, 1, -1, -1, 1, -1, 1, 1, 1]
_ALT = {"alt_truth": 0, "alt_time": 0, "alt_hubris": -1}

_UNITS = {
    "wands": ("день", "дня", "дней"),
    "swords": ("неделя", "недели", "недель"),
    "cups": ("месяц", "месяца", "месяцев"),
    "coins": ("год", "года", "лет"),
    "vessels": ("лунный цикл", "лунных цикла", "лунных циклов"),
}


def card_rank(card: dict) -> int | None:
    suit, _, num = card["id"].rpartition("_")
    return int(num) if suit in MINORS and num.isdigit() else None


def tone(card: dict, rev: bool) -> float:
    cid = card["id"]
    if "tone" in card:
        b = card["tone"]
    elif cid.startswith("major_"):
        b = _MAJOR[int(cid[6:])]
    elif cid in _ALT:
        b = _ALT[cid]
    else:
        r = card_rank(card)
        if r is None:
            b = 0
        else:
            b = _BASE[r - 1]
            if card["suit"] == "swords" and r in _SWORD_HARD:
                b = -1
    return -0.5 * b if rev else b


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return forms[1]
    return forms[2]


def timing(card: dict, rev: bool) -> str:
    r = card_rank(card)
    if r is None:
        txt = ("Срок определяется не по часам, а по поворотному событию: ориентируйся на период "
               "от одного до трёх месяцев.")
    elif r >= 11:
        txt = ("Срок зависит от человека, которого олицетворяет карта: всё сдвинется, когда он "
               "или она сделает свой ход.")
    else:
        txt = f"Около {r} {_plural(r, _UNITS[card['suit']])}."
    if rev:
        txt += " Перевёрнутая карта говорит о задержке, закладывай больший срок."
    return txt


def verdict(drawn: list[tuple[dict, bool]]) -> str:
    """drawn: 8 карт хорарного расклада (индексы: 2 суть, 3 мешает, 4 поможет, 5 скрытое, 6 исход)."""
    t = [tone(c, r) for c, r in drawn]
    core, block, help_, hidden, out = t[2], t[3], t[4], t[5], t[6]
    score = 2 * out + core + 0.5 * help_ + 0.5 * hidden + (0.5 if block > 0 else 0)
    if score >= 2:
        head = "✅ <b>Скорее ДА.</b> Исход и поддерживающие карты складываются в пользу желаемого."
    elif score <= -2:
        head = "❌ <b>Скорее НЕТ.</b> Исход и преграды говорят, что в нынешнем виде желаемое не сбудется."
    else:
        head = ("⚖️ <b>Однозначного ответа нет.</b> Всё решается твоим шагом: "
                "смотри на карты «Что мешает» и «Что поможет».")
    return head + "\n<i>Это тенденция по раскладу, а не приговор: карты не отменяют твоей воли.</i>"
