"""SQLite storage. One file, created on first run."""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH, UPLOAD_DIR

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

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
  ai_error TEXT, created_at TEXT
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
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.executescript(SCHEMA)
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(users)")}
        for col in ("email", "password_hash"):  # databases created before login existed
            if col not in cols:
                _conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
        _conn.commit()
    return _conn


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args: tuple = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def pj(value, default=None):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def reset_all() -> None:
    """Drop every table (used by 'Reset demo data')."""
    global _conn
    with _lock:
        c = conn()
        tables = [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            c.execute(f"DROP TABLE IF EXISTS {t}")
        c.commit()
        c.executescript(SCHEMA)
