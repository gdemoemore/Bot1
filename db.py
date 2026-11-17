import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = os.getenv("TZ_NAME", "Europe/Moscow")
FREE_PER_DAY = int(os.getenv("FREE_PER_DAY", "2"))
CUPS_MODES = ["cups", "vessels", "both"]

_conn = sqlite3.connect(os.getenv("DB_PATH", "tarot.db"), check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    premium_until INTEGER DEFAULT 0,
    day TEXT DEFAULT '',
    used INTEGER DEFAULT 0,
    cups_mode TEXT DEFAULT 'cups',
    alts INTEGER DEFAULT 1,
    reversals INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments(
    charge_id TEXT PRIMARY KEY,
    user_id INTEGER,
    stars INTEGER,
    days INTEGER,
    ts INTEGER
);
""")


for _col, _ddl in (("extras", "INTEGER DEFAULT 1"), ("pick", "INTEGER DEFAULT 0")):
    try:
        _conn.execute(f"ALTER TABLE users ADD COLUMN {_col} {_ddl}")
    except sqlite3.OperationalError:
        pass
_conn.commit()


def today() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")


def user(uid: int) -> sqlite3.Row:
    _conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    _conn.commit()
    row = _conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if row["day"] != today():  # новый день — сброс счётчика
        _conn.execute("UPDATE users SET day=?, used=0 WHERE user_id=?", (today(), uid))
        _conn.commit()
        row = _conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    return row


def is_premium(uid: int) -> bool:
    return user(uid)["premium_until"] > time.time()


def premium_until(uid: int) -> int:
    return user(uid)["premium_until"]


def left_today(uid: int) -> int | None:
    """None = безлимит (подписка)."""
    if is_premium(uid):
        return None
    return max(0, FREE_PER_DAY - user(uid)["used"])


def register_use(uid: int) -> None:
    _conn.execute("UPDATE users SET used = used + 1 WHERE user_id=?", (uid,))
    _conn.commit()


def add_premium(uid: int, days: int) -> int:
    base = max(int(time.time()), user(uid)["premium_until"])
    until = base + days * 86400
    _conn.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, uid))
    _conn.commit()
    return until


def log_payment(charge_id: str, uid: int, stars: int, days: int) -> None:
    _conn.execute("INSERT OR IGNORE INTO payments VALUES(?,?,?,?,?)",
                  (charge_id, uid, stars, days, int(time.time())))
    _conn.commit()


def cycle_cups(uid: int) -> str:
    cur = user(uid)["cups_mode"]
    nxt = CUPS_MODES[(CUPS_MODES.index(cur) + 1) % len(CUPS_MODES)]
    _conn.execute("UPDATE users SET cups_mode=? WHERE user_id=?", (nxt, uid))
    _conn.commit()
    return nxt


def toggle(uid: int, field: str) -> None:
    assert field in ("alts", "reversals", "extras", "pick")
    _conn.execute(f"UPDATE users SET {field} = 1 - {field} WHERE user_id=?", (uid,))
    _conn.commit()
