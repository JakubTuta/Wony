import atexit
import sqlite3
import threading
import typing
import uuid
from datetime import datetime, timedelta

_DB_FILE = "wony.db"
_lock = threading.Lock()
_conn: typing.Optional[sqlite3.Connection] = None
_fts_available: bool = False

SESSION_ID: str = str(uuid.uuid4())[:12]


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                conn = sqlite3.connect(_DB_FILE, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                _init_schema(conn)
                _conn = conn
                atexit.register(close)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    global _fts_available
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL,
            ts              TEXT NOT NULL,
            user_text       TEXT NOT NULL,
            assistant_text  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            ts    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id             TEXT PRIMARY KEY,
            text           TEXT NOT NULL,
            when_str       TEXT,
            trigger_type   TEXT NOT NULL,
            trigger_kwargs TEXT NOT NULL,
            created_ts     TEXT NOT NULL
        )
    """)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts
            USING fts5(user_text, assistant_text, content='turns', content_rowid='id')
        """)
        _fts_available = True
    except sqlite3.OperationalError:
        _fts_available = False
    conn.commit()


def insert_turn(user_text: str, assistant_text: str) -> None:
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        cur = conn.execute(
            "INSERT INTO turns (session_id, ts, user_text, assistant_text) VALUES (?, ?, ?, ?)",
            (SESSION_ID, ts, user_text, assistant_text or ""),
        )
        row_id = cur.lastrowid
        if _fts_available:
            try:
                conn.execute(
                    "INSERT INTO turns_fts(rowid, user_text, assistant_text) VALUES (?, ?, ?)",
                    (row_id, user_text, assistant_text or ""),
                )
            except sqlite3.OperationalError:
                pass
        conn.commit()


def search_turns(
    keyword: str,
    days_back: int = 30,
    limit: int = 5,
) -> typing.List[typing.Dict]:
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat(timespec="seconds")
    with _lock:
        if _fts_available:
            try:
                rows = conn.execute(
                    """
                    SELECT t.id, t.session_id, t.ts, t.user_text, t.assistant_text
                    FROM turns t
                    JOIN turns_fts f ON t.id = f.rowid
                    WHERE turns_fts MATCH ? AND t.ts >= ?
                    ORDER BY t.ts DESC
                    LIMIT ?
                    """,
                    (keyword, cutoff, limit),
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        pattern = f"%{keyword}%"
        rows = conn.execute(
            """
            SELECT id, session_id, ts, user_text, assistant_text
            FROM turns
            WHERE (user_text LIKE ? OR assistant_text LIKE ?) AND ts >= ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (pattern, pattern, cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def turns_on_date(date_str: str) -> typing.List[typing.Dict]:
    conn = _get_conn()
    day = _normalize_date(date_str)
    with _lock:
        rows = conn.execute(
            "SELECT id, session_id, ts, user_text, assistant_text FROM turns WHERE ts LIKE ? ORDER BY ts ASC",
            (f"{day}%",),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_turns(limit: int = 10) -> typing.List[typing.Dict]:
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id, session_id, ts, user_text, assistant_text FROM turns ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# ------------------------------------------------------------------ facts (profile store)

def get_fact(key: str) -> typing.Optional[str]:
    conn = _get_conn()
    with _lock:
        row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_fact(key: str, value: str) -> None:
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn.execute(
            "INSERT INTO facts (key, value, ts) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
            (key, value, ts),
        )
        conn.commit()


def remove_fact(key: str) -> bool:
    conn = _get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0


def all_facts() -> typing.Dict[str, str]:
    conn = _get_conn()
    with _lock:
        rows = conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}


def import_facts_from_dict(data: typing.Dict[str, str]) -> None:
    """Bulk-insert facts without overwriting existing keys."""
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        for key, value in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO facts (key, value, ts) VALUES (?, ?, ?)",
                (key, str(value), ts),
            )
        conn.commit()


# ------------------------------------------------------------------

# ------------------------------------------------------------------ reminders

def save_reminder(meta: typing.Dict) -> None:
    import json as _json
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO reminders (id, text, when_str, trigger_type, trigger_kwargs, created_ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                meta["id"],
                meta["text"],
                meta.get("when_str", ""),
                meta["trigger_type"],
                _json.dumps(meta.get("trigger_kwargs", {})),
                ts,
            ),
        )
        conn.commit()


def delete_reminder(reminder_id: str) -> None:
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()


def all_reminders() -> typing.List[typing.Dict]:
    import json as _json
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id, text, when_str, trigger_type, trigger_kwargs, created_ts FROM reminders"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["trigger_kwargs"] = _json.loads(d["trigger_kwargs"])
            except Exception:
                d["trigger_kwargs"] = {}
            result.append(d)
        return result


# ------------------------------------------------------------------

def close() -> None:
    """Flush and close the SQLite connection. Safe to call multiple times."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.commit()
                _conn.close()
            except Exception:
                pass
            _conn = None


def _normalize_date(date_str: str) -> str:
    try:
        import dateparser
        dt = dateparser.parse(date_str, settings={"RETURN_AS_TIMEZONE_AWARE": False})
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return date_str[:10]
