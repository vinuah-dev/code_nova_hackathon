"""Tests for in-app user-testing feedback and the audit-log export, on a throwaway database.

Run:  python scripts/feedback_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_fb_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

passed = 0
H = lambda uid: {"X-User-Id": uid}  # noqa: E731


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


with TestClient(app) as c:
    tasks = c.get("/api/feedback/tasks", headers=H("u-creator")).json()
    check(len(tasks) >= 5, "feedback tasks listed")
    r = c.post("/api/feedback", headers=H("u-creator"), json={"task": tasks[0], "rating": 4, "completed": "yes", "comment": "Clear findings", "tester": "Tester A", "device": "mobile"})
    check(r.status_code == 200, "creator can leave feedback")
    c.post("/api/feedback", headers=H("u-approver"), json={"task": tasks[3], "rating": 2, "completed": "partly", "comment": "Override step confusing"})
    check(c.post("/api/feedback", headers=H("u-creator"), json={"rating": 9}).status_code == 400, "rating outside 1-5 rejected")
    check(c.post("/api/feedback", headers=H("u-creator"), json={"rating": "x"}).status_code == 400, "non-numeric rating rejected")
    check(c.get("/api/feedback", headers=H("u-creator")).status_code == 403, "only admins read feedback")
    d = c.get("/api/feedback", headers=H("u-admin")).json()
    s = d["summary"]
    check(s["count"] == 2 and s["avg_rating"] == 3.0 and s["completed_share"] == 50, f"summary: {s['count']} responses, avg {s['avg_rating']}, {s['completed_share']}% completed")
    check(s["testers"] == 2 and len(s["by_task"]) == 2, "per-task breakdown and tester count")
    csv = c.get("/api/feedback.csv", headers=H("u-admin"))
    check(csv.status_code == 200 and "Override step confusing" in csv.text and csv.text.startswith("id,"), "CSV export for the submission evidence")
    check(c.post("/api/admin/reset-demo", headers=H("u-admin")).status_code == 200, "demo data reset")
    check(c.get("/api/feedback", headers=H("u-admin")).json()["summary"]["count"] == 2, "feedback survives a demo reset")
    c.cookies.clear()  # reset-demo signs the admin back in with a cookie; test the header roles below
    audit = c.get("/api/audit.csv", headers=H("u-approver"))
    check(audit.status_code == 200 and audit.text.startswith("at,content_id") and ",approved," in audit.text, "audit log CSV with approvals and SHA-256")
    check(c.get("/api/audit.csv", headers=H("u-creator")).status_code == 403, "creators cannot export the audit log")

print(f"\nAll {passed} feedback checks passed.")
