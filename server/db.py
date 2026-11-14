"""Storage: SQLite locally, Postgres (e.g. Supabase) when DATABASE_URL is set.

All queries in the app use SQLite-style `?` placeholders; for Postgres they are rewritten to `%s`,
the schema is translated (AUTOINCREMENT → BIGSERIAL, REAL → DOUBLE PRECISION, BLOB → BYTEA) and
INSERTs into tables with a numeric id get `RETURNING id`, so the rest of the code is backend-agnostic.
"""
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import DATA_DIR, DB_PATH, UPLOAD_DIR

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL, title TEXT, email TEXT, password_hash TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS guidelines (
  id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, source TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS guideline_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, guideline_id TEXT, old_body TEXT, new_body TEXT,
  changed_by TEXT, reason TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT, preferred TEXT NOT NULL, disallowed TEXT NOT NULL,
  note TEXT, guideline_id TEXT
);
CREATE TABLE IF NOT EXISTS prohibited (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phrase TEXT NOT NULL, reason TEXT, replacement TEXT,
  severity TEXT DEFAULT 'medium', category TEXT DEFAULT 'tone', guideline_id TEXT
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, label TEXT NOT NULL, value REAL, unit TEXT, statement TEXT NOT NULL,
  keywords TEXT, outdated_values TEXT, source TEXT, verified_on TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY, text TEXT NOT NULL, evidence TEXT, approved_by TEXT
);
CREATE TABLE IF NOT EXISTS colors (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, hex TEXT NOT NULL, usage TEXT
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
  mime TEXT, meta TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, path TEXT, text TEXT, uploaded_at TEXT
);
CREATE TABLE IF NOT EXISTS content (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, channel TEXT, status TEXT NOT NULL,
  owner_id TEXT, confidential INTEGER DEFAULT 0, current_version INTEGER DEFAULT 1,
  approved_version INTEGER, approved_hash TEXT, is_demo INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER NOT NULL, number INTEGER NOT NULL,
  body TEXT, alt_text TEXT, attachments TEXT, created_by TEXT, created_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, path TEXT, mime TEXT,
  sha256 TEXT, text TEXT, meta TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER, version_number INTEGER,
  mode TEXT, engine_note TEXT, score REAL, dimensions TEXT, findings TEXT, retrieved TEXT,
  ai_error TEXT, created_at TEXT, ai_ms INTEGER
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, finding_id TEXT, decision TEXT,
  user_id TEXT, note TEXT, at TEXT, UNIQUE(analysis_id, finding_id)
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER, user_id TEXT, body TEXT,
  finding_id TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER, user_id TEXT, action TEXT,
  from_status TEXT, to_status TEXT, note TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS integrity_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER, detected_at TEXT, expected TEXT,
  actual TEXT, diff TEXT, source TEXT, resolved INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gap_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT, signature TEXT UNIQUE, guideline_id TEXT, title TEXT,
  description TEXT, count INTEGER, examples TEXT, suggestion TEXT, status TEXT DEFAULT 'open',
  decided_by TEXT, decided_at TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ml_models (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trained_at TEXT, status TEXT, gate_passed INTEGER,
  info TEXT, metrics TEXT, vocab TEXT, weights TEXT, reasons TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, user_name TEXT, role TEXT, tester TEXT, page TEXT, task TEXT,
  rating INTEGER, completed TEXT, comment TEXT, device TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS blobs (name TEXT PRIMARY KEY, data BLOB, mime TEXT, created_at TEXT);
"""

TABLES = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA)
KEEP_ON_RESET = {"feedback"}
MIGRATIONS = [("users", "email", "TEXT"), ("users", "password_hash", "TEXT"), ("analyses", "ai_ms", "INTEGER")]  # user-testing evidence survives "Reset demo data"
SERIAL_TABLES = {t for t, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", SCHEMA, flags=re.S) if "AUTOINCREMENT" in body}


# ------------------------------------------------------------------ backend selection
def database_url() -> str | None:
    """Postgres URL (Supabase etc.). INKLOOM_DB=sqlite forces SQLite (used by the test scripts)."""
    if os.environ.get("INKLOOM_DB") == "sqlite":
        return None
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        return None
    # Vercel's Supabase integration appends params psycopg doesn't know (e.g. supa=...); keep only libpq ones.
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query) if k in {"sslmode", "connect_timeout", "application_name", "options"}]
    if not any(k == "sslmode" for k, _ in keep) and parts.hostname not in ("localhost", "127.0.0.1"):
        keep.append(("sslmode", "require"))
    return urlunsplit(parts._replace(scheme="postgresql", query=urlencode(keep)))


IS_PG = False


def backend() -> str:
    return "postgres" if database_url() else "sqlite"


def _pg_schema() -> str:
    s = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)
    s = s.replace(" BLOB,", " BYTEA,")
    # Supabase exposes the public schema over its REST Data API. Turning RLS on with no policies blocks
    # that API completely; the app connects as the table owner, which RLS does not restrict.
    return s + "".join(f"\nALTER TABLE {t} ENABLE ROW LEVEL SECURITY;" for t in TABLES)


def _connect_pg(url: str):
    import psycopg
    from psycopg.rows import dict_row
    # prepare_threshold=None: works behind transaction poolers (Supabase/pgbouncer) too.
    return psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)


def conn():
    global _conn, IS_PG
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        url = database_url()
        if url:
            IS_PG = True
            _conn = _connect_pg(url)
            with global_lock_raw(_conn):
                _conn.execute(_pg_schema())
                for table, col, typ in MIGRATIONS:
                    _conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
        else:
            IS_PG = False
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON")
            _conn.executescript(SCHEMA)
            for table, col, typ in MIGRATIONS:  # databases created before these columns existed
                if col not in {r[1] for r in _conn.execute(f"PRAGMA table_info({table})")}:
                    _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            _conn.commit()
    return _conn


# ------------------------------------------------------------------ queries
def _pg_sql(sql: str) -> str:
    return sql.replace("%", "%%").replace("?", "%s")


def _run(sql: str, args: tuple):
    """Execute with one reconnect attempt (serverless connections can be dropped while idle)."""
    global _conn
    for attempt in (1, 2):
        c = conn()
        try:
            if IS_PG:
                return c.execute(_pg_sql(sql), args)
            return c.execute(sql, args)
        except Exception as e:  # noqa: BLE001
            if IS_PG and attempt == 1 and _is_connection_error(e):
                try:
                    _conn.close()
                except Exception:  # noqa: BLE001
                    pass
                _conn = None
                continue
            raise


def _is_connection_error(e: Exception) -> bool:
    import psycopg
    return isinstance(e, (psycopg.OperationalError, psycopg.InterfaceError))


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _run(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args: tuple = ()) -> int:
    with _lock:
        conn()
        if IS_PG:
            m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, flags=re.I)
            if m and m.group(1) in SERIAL_TABLES and "RETURNING" not in sql.upper():
                row = _run(sql.rstrip().rstrip(";") + " RETURNING id", args).fetchone()
                return row["id"] if row else 0
            _run(sql, args)
            return 0
        cur = _run(sql, args)
        _conn.commit()
        return cur.lastrowid


@contextmanager
def global_lock_raw(c):
    """Cross-instance lock (Postgres advisory lock) so two cold starts don't seed at the same time."""
    if IS_PG:
        c.execute("SELECT pg_advisory_lock(726354)")
        try:
            yield
        finally:
            c.execute("SELECT pg_advisory_unlock(726354)")
    else:
        yield


@contextmanager
def global_lock():
    with _lock:
        with global_lock_raw(conn()):
            yield


def j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def pj(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reset_all() -> None:
    """Drop every app table and recreate the schema (used by 'Reset demo data')."""
    with _lock:
        c = conn()
        if IS_PG:
            c.execute("DROP TABLE IF EXISTS " + ", ".join(t for t in TABLES if t not in KEEP_ON_RESET) + " CASCADE")
            c.execute(_pg_schema())
            return
        tables = [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            if t not in KEEP_ON_RESET:
                c.execute(f"DROP TABLE IF EXISTS {t}")
        c.commit()
        c.executescript(SCHEMA)
