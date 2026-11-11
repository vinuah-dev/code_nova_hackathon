"""Login sessions: PBKDF2 password hashes and HMAC-signed session tokens in an HttpOnly cookie.

Tokens are stateless (signed, with an expiry) because serverless hosts such as Vercel run several
instances that do not share a database. Sign-out clears the cookie and revokes the token on that instance.
The demo organisation also offers one-click "demo account" sign-in (INKLOOM_DEMO_LOGIN=0 turns it off).
"""
import contextvars
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

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


def _secret() -> bytes:
    """HMAC key for session tokens. Must be identical on every server instance (Vercel runs several).

    Order: INKLOOM_SESSION_SECRET (recommended) → derived from the configured AI key (already a shared
    server-side secret; HMAC-derived so the key itself is never exposed) → fixed development key.
    """
    s = os.environ.get("INKLOOM_SESSION_SECRET")
    if s:
        return s.encode()
    for k in ("GEMINI_API_KEY", "INKLOOM_AI_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(k):
            return hmac.new(os.environ[k].encode(), b"inkloom-session-v1", hashlib.sha256).digest()
    return b"inkloom-dev-only-session-key"  # local demo without any secret configured


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def create_session(user_id: str) -> str:
    """Stateless signed token 'user.expiry.nonce.signature', so any server instance can verify it."""
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{user_id}.{exp}.{secrets.token_urlsafe(12)}"
    return f"{payload}.{_sign(payload)}"


def resolve(token: str | None) -> str | None:
    try:
        uid, exp, nonce, sig = (token or "").split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(f"{uid}.{exp}.{nonce}")):
        return None
    if not exp.isdigit() or int(exp) < time.time():
        return None
    if db.one("SELECT 1 FROM sessions WHERE token_hash=?", (_th(token),)):
        return None  # signed out on this instance
    return uid


def end_session(token: str | None) -> None:
    """Sign-out clears the cookie; the token is also put on this instance's revocation list."""
    if resolve(token):
        exp = datetime.fromtimestamp(int(token.split(".")[1]), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.ex("INSERT OR IGNORE INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
              (_th(token), token.split(".")[0], db.now(), exp))
        db.ex("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))


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
