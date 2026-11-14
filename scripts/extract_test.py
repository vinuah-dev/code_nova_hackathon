"""Tests for 'Extract rules' (brand document -> proposed Brand Brain entries) and the health endpoint.

Run:  python scripts/extract_test.py      (pattern-based path; no AI calls)
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_ex_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase

from fastapi.testclient import TestClient  # noqa: E402

from server import extract  # noqa: E402
from server.main import app  # noqa: E402

passed = 0
H = lambda uid: {"X-User-Id": uid}  # noqa: E731


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


pdf = ROOT / "web" / "demo" / "Voltaro_Guidelines_Update_2026.pdf"
with TestClient(app) as c:
    did = c.post("/api/brand/documents", headers=H("u-admin"), json={"name": pdf.name, "mime": "application/pdf",
                                                                      "data": base64.b64encode(pdf.read_bytes()).decode()}).json()["id"]
    check(c.post(f"/api/brand/documents/{did}/extract", headers=H("u-creator")).status_code == 403, "only admins extract rules")
    r = c.post(f"/api/brand/documents/{did}/extract", headers=H("u-admin")).json()
    p = r["proposals"]
    check(r["engine"] == "rules", "falls back to pattern extraction without AI")
    check([t["preferred"] for t in p["terms"]] == ["Voltaro Care+"] and "Voltaro Care Plus" in p["terms"][0]["disallowed"], "term + likely misspellings")
    phrases = {x["phrase"] for x in p["prohibited"]}
    check({"insane", "mind-blowing", "lifetime free service"} <= phrases and "responsive" not in phrases, "banned words found; the suggested replacement is not banned")
    check(any(f["value"] == 2499 and f["unit"] == "INR" for f in p["facts"]) and any(f["value"] == 25 and f["unit"] == "km" for f in p["facts"]), "facts with value and unit")
    check([x["hex"] for x in p["colors"]] == ["#0FA3B1"], "new colour with hex")
    check(all(x["quote"] and x["source"] == f"DOC-{did}" for v in p.values() for x in v), "every proposal quotes its sentence and source")

    text = "Voltaro Care+ costs Rs 2,499 per year."
    check(extract._grounded("Voltaro Care+ costs Rs 2,499 per year", extract._norm(text)), "quote check accepts a real sentence")
    check(not extract._grounded("Voltaro Care+ is free forever", extract._norm(text)), "quote check rejects an invented sentence")

    check(c.post("/api/brand/prohibited", headers=H("u-admin"), json={"phrase": "insane", "reason": "hype", "replacement": "responsive"}).status_code == 200, "admin adds a proposal")
    r2 = c.post(f"/api/brand/documents/{did}/extract", headers=H("u-admin")).json()
    check(next(x for x in r2["proposals"]["prohibited"] if x["phrase"] == "insane")["already"], "already-added rules are marked")
    res = c.post("/api/dna", headers=H("u-creator"), json={"original": {"body": "Insane pickup!"}, "modified": {"body": "Responsive pickup."}}).json()
    check(any("insane" in (f.get("quote") or "").lower() for f in res["original"]["findings"]), "new rule is used by the next review")

    h = c.get("/api/health", headers=H("u-creator")).json()
    check(h["database"]["backend"] == "sqlite" and h["database"]["round_trip_ms"] >= 0 and "reviews" in h, "health endpoint reports database and reviews")

print(f"\nAll {passed} extract/health checks passed.")
