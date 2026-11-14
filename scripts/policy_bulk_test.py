"""Tests for the approval policy and bulk CSV review, on a throwaway database (no AI calls).

Run:  python scripts/policy_bulk_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_pol_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

passed = 0
H = lambda uid: {"X-User-Id": uid}  # noqa: E731
BAD = "Glide-S1 gives 150 km, the best scooter in India, guaranteed!! Click here."


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


def new_reviewed(c, body=BAD):
    cid = c.post("/api/content", headers=H("u-creator"), json={"title": "Policy test", "channel": "Instagram", "body": body}).json()["id"]
    c.post(f"/api/content/{cid}/analyze", headers=H("u-creator"))
    return cid


with TestClient(app) as c:
    p = c.get("/api/policy", headers=H("u-creator")).json()
    check(p == {"min_score_to_submit": 0, "require_endorsement": False, "block_critical": False}, "policy is off by default")
    check(c.post("/api/policy", headers=H("u-creator"), json={"min_score_to_submit": 80}).status_code == 403, "only admins change the policy")
    check(c.post("/api/policy", headers=H("u-admin"), json={"min_score_to_submit": 140}).status_code == 400, "invalid minimum score rejected")
    c.post("/api/policy", headers=H("u-admin"), json={"min_score_to_submit": 80, "require_endorsement": True, "block_critical": True})

    cid = new_reviewed(c)
    r = c.post(f"/api/content/{cid}/submit", headers=H("u-creator"), json={})
    check(r.status_code == 409 and "at least 80" in r.json()["detail"], "low-scoring content cannot be submitted")

    c.post("/api/policy", headers=H("u-admin"), json={"min_score_to_submit": 0})
    check(c.post(f"/api/content/{cid}/submit", headers=H("u-creator"), json={}).status_code == 200, "submit allowed once the threshold is off")
    r = c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={"override_reason": "ok"})
    check(r.status_code == 409 and "endorse" in r.json()["detail"], "approval needs a manager endorsement first")
    c.post(f"/api/content/{cid}/endorse", headers=H("u-manager"), json={"note": "fine"})
    r = c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={"override_reason": "ok"})
    check(r.status_code == 409 and "critical" in r.json()["detail"], "open critical issues block approval even with an override")
    c.post("/api/policy", headers=H("u-admin"), json={"block_critical": False})
    check(c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={"override_reason": "Legal approved"}).status_code == 200, "approved once policy allows the override")
    audit = c.get("/api/audit.csv", headers=H("u-approver")).text
    check("policy_changed" in audit, "policy changes are in the audit log")
    c.post("/api/policy", headers=H("u-admin"), json={"require_endorsement": False})

    csv_rows = [{"title": "Clean", "channel": "Blog", "body": "Book a test ride of the Voltaro Glide S1 at your nearest Voltaro Experience Centre."},
                {"title": "Risky", "channel": "Ads", "body": BAD}, {"title": "Empty", "body": "   "}]
    r = c.post("/api/bulk-review", headers=H("u-creator"), json={"rows": csv_rows})
    d = r.json()
    check(r.status_code == 200 and d["summary"]["count"] == 2, "bulk review skips empty rows and reviews the rest")
    by = {i["title"]: i for i in d["items"]}
    check(by["Clean"]["score"] > by["Risky"]["score"] and by["Risky"]["serious"] > 0, "scores separate clean and risky items")
    rep = c.get(f"/api/content/{by['Risky']['id']}/report", headers=H("u-creator")).json()
    check(rep["content"]["status"] == "ai_review" and rep["analysis"] and not rep["content"]["confidential"], "each bulk item is a reviewed draft with its own report")
    check(c.post("/api/bulk-review", headers=H("u-manager"), json={"rows": csv_rows}).status_code == 403, "managers cannot create content in bulk")
    check(c.post("/api/bulk-review", headers=H("u-creator"), json={"rows": [{"body": "x"}] * 26}).status_code == 400, "more than 25 rows rejected")

print(f"\nAll {passed} policy/bulk checks passed.")
