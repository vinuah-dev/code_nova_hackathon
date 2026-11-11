"""Sign-in / sign-out tests with real session cookies (no X-User-Id shortcut).

Run:  python scripts/auth_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_auth_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ.pop("INKLOOM_HEADER_AUTH", None)

os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase

from fastapi.testclient import TestClient  # noqa: E402

from server import auth, db  # noqa: E402
from server.main import app  # noqa: E402
from server.seed import DEMO_PASSWORD  # noqa: E402

passed = 0


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


with TestClient(app) as c:
    check(c.get("/api/content").status_code == 401, "API is closed without a session")
    check(c.get("/api/status").status_code == 200, "status endpoint stays public")
    check(c.get("/api/content", headers={"X-User-Id": "u-admin"}).status_code == 401, "X-User-Id header is ignored outside tests")
    check(c.post("/api/auth/login", json={"email": "rohan@voltaro.demo", "password": "nope"}).status_code == 401, "wrong password rejected")
    check(c.post("/api/auth/login", json={"email": "", "password": ""}).status_code == 400, "empty form rejected")

    r = c.post("/api/auth/login", json={"email": "Rohan@Voltaro.demo", "password": DEMO_PASSWORD})
    check(r.status_code == 200 and r.json()["user"]["role"] == "creator", "correct password signs in (email case-insensitive)")
    ck = r.headers.get("set-cookie", "")
    check("HttpOnly" in ck and "samesite=lax" in ck.lower(), "session cookie is HttpOnly + SameSite=Lax")
    token = c.cookies.get(auth.COOKIE)
    check(auth.resolve(token) == "u-creator", "token is HMAC-signed and verifiable on any instance")
    check(auth.resolve(token.replace("u-creator", "u-admin", 1)) is None, "tampered token (changed user) is rejected")
    check(auth.resolve(token[:-1] + ("0" if token[-1] != "0" else "1")) is None, "token with a broken signature is rejected")
    check(c.get("/api/auth/me").json()["user"]["id"] == "u-creator", "/api/auth/me returns the signed-in user")
    check("password_hash" not in c.get("/api/users").json()[0], "password hashes never leave the server")
    check(c.post("/api/admin/reset-demo").status_code == 403, "roles still enforced from the session (creator cannot reset)")

    check(c.post("/api/auth/logout").status_code == 200, "sign out")
    c.cookies.clear()
    check(c.get("/api/content").status_code == 401, "after sign out the API is closed again")
    c.cookies.set(auth.COOKIE, token)
    check(c.get("/api/content").status_code == 401, "signed-out token is revoked")
    c.cookies.clear()

    d = c.get("/api/auth/demo-accounts").json()
    check(d["enabled"] and len(d["accounts"]) == 5, "5 demo accounts offered on the sign-in page")
    r = c.post("/api/auth/demo-login", json={"user_id": "u-admin"})
    check(r.status_code == 200 and c.get("/api/auth/me").json()["user"]["role"] == "admin", "one-click demo sign-in")
    check(c.post("/api/admin/reset-demo").status_code == 200 and c.get("/api/auth/me").status_code == 200, "admin stays signed in after resetting demo data")
    c.post("/api/auth/logout")
    c.cookies.clear()

    for _ in range(5):
        c.post("/api/auth/login", json={"email": "meera@voltaro.demo", "password": "wrong"})
    r = c.post("/api/auth/login", json={"email": "meera@voltaro.demo", "password": DEMO_PASSWORD})
    check(r.status_code == 429, "5 wrong passwords lock that email for a few minutes")

    os.environ["INKLOOM_DEMO_LOGIN"] = "0"
    check(c.post("/api/auth/demo-login", json={"user_id": "u-admin"}).status_code == 403, "demo sign-in can be turned off")
    check(c.get("/api/auth/demo-accounts").json()["enabled"] is False, "demo accounts hidden when turned off")
    os.environ.pop("INKLOOM_DEMO_LOGIN")

print(f"\nAll {passed} auth checks passed.")
