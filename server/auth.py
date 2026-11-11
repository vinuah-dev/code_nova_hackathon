"""Login sessions: PBKDF2 password hashes, random session tokens in an HttpOnly cookie.

Only the SHA-256 of a session token is stored, so a leaked database cannot be replayed as a login.
The demo organisation also offers one-click "demo account" sign-in (INKLOOM_DEMO_LOGIN=0 turns it off).
"""
import contextvars
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from . import db

COOKIE = "inkloom_session"
SESSION_DAYS = 7
ITERATIONS = 120_000
current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)

_failures: dict[str, list[float]] = {}
MAX_FAILURES, WINDOW = 5, 300  # 5 wrong passwords per email per 5 minutes


def demo_login_enabled() -> bool:
    return os.environ.get("INKLOOM_DEMO_LOGIN", "1") != "0"


def header_auth_enabled() -> bool:
    """Test-only: lets the API test scripts act as a user via X-User-Id. Never set this in production."""
    return os.environ.get("INKLOOM_HEADER_AUTH") == "1"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, it, salt, dk = (stored or "").split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(got.hex(), dk)
    except (ValueError, TypeError):
        return False


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.ex("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)", (_th(token), user_id, db.now(), exp))
    db.ex("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))
    return token


def resolve(token: str | None) -> str | None:
    if not token:
        return None
    s = db.one("SELECT user_id, expires_at FROM sessions WHERE token_hash=?", (_th(token),))
    if not s or s["expires_at"] < db.now():
        return None
    return s["user_id"]


def end_session(token: str | None) -> None:
    if token:
        db.ex("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


def check_password(email: str, password: str) -> dict | None:
    """Returns the user on success. Raises PermissionError when the email is temporarily locked."""
    key = email.strip().lower()
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < WINDOW]
    if len(recent) >= MAX_FAILURES:
        raise PermissionError("Too many wrong attempts. Try again in a few minutes.")
    u = db.one("SELECT * FROM users WHERE lower(email)=?", (key,))
    if u and verify_password(password, u.get("password_hash")):
        _failures.pop(key, None)
        return u
    _failures[key] = recent + [now]
    return None


def public(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "name", "role", "title", "email")}
