"""Round 3 improvement 1: text inside images (OCR) checked like body text.

The vision model is replaced by a stub that returns the poster's real lines (as Gemini does, in its
box_2d format), so this runs offline. Run:  python scripts/ocr_test.py
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_ocr_")
os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase
os.environ.pop("INKLOOM_DISABLE_AI", None)
os.environ["INKLOOM_AI_PROVIDER"] = "gemini"
os.environ["GEMINI_API_KEY"] = "test-key-not-used"  # calls are stubbed below

from fastapi.testclient import TestClient  # noqa: E402

from server import ai, ocr  # noqa: E402
from server.main import app  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
passed = 0
H = {"X-User-Id": "u-creator"}
POSTER_LINES = [  # what Gemini returned for web/demo/diwali_poster.png (box_2d = [ymin, xmin, ymax, xmax] on 0-1000)
    {"text": "DIWALI DHAMAKA", "box_2d": [[98, 86, 155, 883]]},
    {"text": "India's fastest", "box_2d": [326, 111, 373, 589]},
    {"text": "electric scooter", "box_2d": [400, 110, 447, 646]},
    {"text": "150 km range. Guaranteed.", "box_2d": [510, 110, 545, 696]},
    {"text": "Zero maintenance!!", "box_2d": [569, 109, 599, 521]},
    {"text": "BOOK NOW", "box_2d": [655, 154, 682, 397]},
]
calls = {"ocr": 0, "review": 0}
mode = {"ocr_fails": False}


def fake_call(system, content, schema, max_tokens=16000, budget=None):
    if system == ocr.SYSTEM:
        calls["ocr"] += 1
        if mode["ocr_fails"]:
            raise ai.AIUnavailable("AI service busy (503)")
        return {"lines": POSTER_LINES}
    calls["review"] += 1
    raise ai.AIUnavailable("review stubbed out in this test")


ai._call = fake_call


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


def poster(c):
    b64 = base64.b64encode((ROOT / "web" / "demo" / "diwali_poster.png").read_bytes()).decode()
    return c.post("/api/uploads", headers=H, json={"name": "diwali_poster.png", "mime": "image/png", "kind": "poster", "data": b64}).json()["id"]


def content(c, up, confidential=False):
    return c.post("/api/content", headers=H, json={"title": "Poster", "channel": "Instagram", "body": "Celebrate Diwali with Voltaro.",
                                                   "alt_text": "Festive poster of the Voltaro Glide S1 with an offer headline.",
                                                   "attachments": [up], "confidential": confidential}).json()["id"]


with TestClient(app) as c:
    check(ocr._clean([{"text": "a b", "box_2d": [[100, 200, 300, 400]]}])[0]["box"] == [0.2, 0.1, 0.4, 0.3], "box_2d (nested, 0-1000) becomes [x0, y0, x1, y1] fractions")
    check(ocr._clean([{"text": "bad", "box_2d": [1, 2]}, {"text": "", "box_2d": [1, 2, 3, 4]}]) == [], "malformed lines are dropped")

    cid = content(c, poster(c))
    r = c.post(f"/api/content/{cid}/analyze", headers=H).json()
    img = [f for f in r["findings"] if f.get("ocr")]
    quotes = {f["quote"].strip().lower() for f in img}
    check(calls["ocr"] == 1, "the poster is read once")
    check({"dhamaka", "150", "zero maintenance"} <= quotes, f"text inside the image is checked: {sorted(quotes)}")
    check(any("guarantee" in q for q in quotes) and any("fastest" in q for q in quotes), "claims printed on the poster are flagged")
    check(all(f["target"].startswith("image:") and f["box"] and len(f["box"]) == 4 for f in img), "every OCR finding carries its image region")
    f150 = next(f for f in img if f["quote"] == "150")
    check(f150["suggestion"]["replacement"] == "120" and 0.5 <= f150["box"][1] <= 0.55, "wrong range found on the right line, with the approved figure")

    c.post(f"/api/content/{cid}/analyze", headers=H)
    check(calls["ocr"] == 1, "re-review uses the cached OCR (no second call)")
    rep = c.get(f"/api/content/{cid}/report", headers=H).json()
    check(len(rep["version"]["attachments"][0]["meta"]["ocr"]["lines"]) == 6, "OCR lines are shown with the image in the report")

    before = calls["ocr"]
    cid2 = content(c, poster(c), confidential=True)
    r2 = c.post(f"/api/content/{cid2}/analyze", headers=H).json()
    check(calls["ocr"] == before and not any(f.get("ocr") for f in r2["findings"]), "confidential images are never sent for OCR")

    mode["ocr_fails"] = True
    cid3 = content(c, poster(c))
    r3 = c.post(f"/api/content/{cid3}/analyze", headers=H).json()
    meta = c.get(f"/api/content/{cid3}/report", headers=H).json()["version"]["attachments"][0]["meta"]
    check(r3["findings"] and meta["ocr"]["error"], "if OCR fails the review still completes and says why")
    mode["ocr_fails"] = False
    c.post(f"/api/content/{cid3}/analyze", headers=H)
    meta = c.get(f"/api/content/{cid3}/report", headers=H).json()["version"]["attachments"][0]["meta"]
    check(len(meta["ocr"]["lines"]) == 6, "a failed OCR is retried on the next review")

print(f"\nAll {passed} OCR checks passed.")
