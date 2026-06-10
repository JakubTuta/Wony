import atexit
import json as _json
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
    # Add calls column if it doesn't exist yet (migration for existing DBs)
    try:
        conn.execute("ALTER TABLE turns ADD COLUMN calls TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_servers (
            name         TEXT PRIMARY KEY,
            transport    TEXT NOT NULL DEFAULT 'stdio',
            command      TEXT,
            args         TEXT,
            env          TEXT,
            url          TEXT,
            oauth_tokens TEXT,
            enabled      INTEGER NOT NULL DEFAULT 1,
            created_ts   TEXT NOT NULL,
            updated_ts   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            ref_id      INTEGER,
            ref_key     TEXT,
            text        TEXT NOT NULL,
            vector      BLOB NOT NULL,
            ts          TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_emb_turn "
        "ON embeddings(source_type, ref_id) WHERE ref_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_emb_keyed "
        "ON embeddings(source_type, ref_key) WHERE ref_key IS NOT NULL"
    )
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts
            USING fts5(user_text, assistant_text, content='turns', content_rowid='id')
        """)
        _fts_available = True
    except sqlite3.OperationalError:
        _fts_available = False
    conn.commit()


def insert_turn(
    user_text: str,
    assistant_text: str,
    calls: typing.Optional[typing.List[typing.Dict[str, typing.Any]]] = None,
) -> typing.Optional[int]:
    """Insert a conversation turn and return its row id."""
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    calls_json = _json.dumps(calls) if calls else None
    with _lock:
        cur = conn.execute(
            "INSERT INTO turns (session_id, ts, user_text, assistant_text, calls) VALUES (?, ?, ?, ?, ?)",
            (SESSION_ID, ts, user_text, assistant_text or "", calls_json),
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
        return row_id


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
            "SELECT id, session_id, ts, user_text, assistant_text, calls FROM turns ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result = []
        for r in reversed(rows):
            d = dict(r)
            raw_calls = d.get("calls")
            try:
                d["calls"] = _json.loads(raw_calls) if raw_calls else []
            except Exception:
                d["calls"] = []
            result.append(d)
        return result


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

# ------------------------------------------------------------------ mcp servers

def upsert_mcp_server(record: typing.Dict) -> None:
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn.execute(
            """
            INSERT INTO mcp_servers (name, transport, command, args, env, url, oauth_tokens, enabled, created_ts, updated_ts)
            VALUES (:name, :transport, :command, :args, :env, :url, :oauth_tokens, :enabled, :created_ts, :updated_ts)
            ON CONFLICT(name) DO UPDATE SET
                transport=excluded.transport, command=excluded.command, args=excluded.args,
                env=excluded.env, url=excluded.url, oauth_tokens=excluded.oauth_tokens,
                enabled=excluded.enabled, updated_ts=excluded.updated_ts
            """,
            {
                "name": record["name"],
                "transport": record.get("transport", "stdio"),
                "command": record.get("command") or None,
                "args": record.get("args") or "[]",
                "env": record.get("env") or "{}",
                "url": record.get("url") or None,
                "oauth_tokens": record.get("oauth_tokens") or None,
                "enabled": int(record.get("enabled", 1)),
                "created_ts": record.get("created_ts", ts),
                "updated_ts": ts,
            },
        )
        conn.commit()


def get_mcp_server(name: str) -> typing.Optional[typing.Dict]:
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM mcp_servers WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None


def delete_mcp_server(name: str) -> None:
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))
        conn.commit()


def all_mcp_servers(enabled_only: bool = False) -> typing.List[typing.Dict]:
    conn = _get_conn()
    with _lock:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM mcp_servers WHERE enabled = 1 ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mcp_servers ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]


def set_mcp_server_tokens(name: str, tokens: typing.Dict) -> None:
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        conn.execute(
            "UPDATE mcp_servers SET oauth_tokens = ?, updated_ts = ? WHERE name = ?",
            (_json.dumps(tokens), ts, name),
        )
        conn.commit()


# ------------------------------------------------------------------ embeddings

def upsert_embedding(
    source_type: str,
    ref_id: typing.Optional[int],
    ref_key: typing.Optional[str],
    text: str,
    vector: bytes,
) -> None:
    conn = _get_conn()
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        if ref_id is not None:
            conn.execute(
                """
                INSERT INTO embeddings (source_type, ref_id, ref_key, text, vector, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, ref_id) DO UPDATE SET
                    text=excluded.text, vector=excluded.vector, ts=excluded.ts
                """,
                (source_type, ref_id, ref_key, text, vector, ts),
            )
        else:
            conn.execute(
                """
                INSERT INTO embeddings (source_type, ref_id, ref_key, text, vector, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_type, ref_key) DO UPDATE SET
                    text=excluded.text, vector=excluded.vector, ts=excluded.ts
                """,
                (source_type, ref_id, ref_key, text, vector, ts),
            )
        conn.commit()


def all_embeddings(
    source_types: typing.Optional[typing.List[str]] = None,
) -> typing.List[typing.Dict]:
    conn = _get_conn()
    with _lock:
        if source_types:
            placeholders = ",".join("?" * len(source_types))
            rows = conn.execute(
                f"SELECT id, source_type, ref_id, ref_key, text, vector FROM embeddings WHERE source_type IN ({placeholders})",
                source_types,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, source_type, ref_id, ref_key, text, vector FROM embeddings"
            ).fetchall()
        return [dict(r) for r in rows]


def delete_embedding_by_ref(
    source_type: str,
    ref_id: typing.Optional[int] = None,
    ref_key: typing.Optional[str] = None,
) -> None:
    conn = _get_conn()
    with _lock:
        if ref_id is not None:
            conn.execute(
                "DELETE FROM embeddings WHERE source_type = ? AND ref_id = ?",
                (source_type, ref_id),
            )
        elif ref_key is not None:
            conn.execute(
                "DELETE FROM embeddings WHERE source_type = ? AND ref_key = ?",
                (source_type, ref_key),
            )
        conn.commit()


# ------------------------------------------------------------------

def wipe_all() -> None:
    """Delete every row the user owns: turns, facts, reminders, mcp servers, embeddings.

    Resets a fresh session id and clears the in-memory conversation window.
    """
    global SESSION_ID
    conn = _get_conn()
    with _lock:
        for table in ("turns", "facts", "reminders", "mcp_servers", "embeddings"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        if _fts_available:
            try:
                conn.execute("INSERT INTO turns_fts(turns_fts) VALUES('delete-all')")
            except sqlite3.OperationalError:
                try:
                    conn.execute("DELETE FROM turns_fts")
                except sqlite3.OperationalError:
                    pass
        conn.commit()
        SESSION_ID = str(uuid.uuid4())[:12]

    try:
        from helpers.conversation import Conversation
        Conversation.clear()
    except Exception:
        pass


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
