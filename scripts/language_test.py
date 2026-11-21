"""Round 3 improvement 2: Hindi and Hinglish content checks. Throwaway database, no AI calls.

Run:  python scripts/language_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_lang_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ["INKLOOM_DB"] = "sqlite"  # never touch a configured Postgres/Supabase

from fastapi.testclient import TestClient  # noqa: E402

from server import lang, seed  # noqa: E402
from server.main import app  # noqa: E402

passed = 0
sys.stdout.reconfigure(encoding="utf-8")
H = {"X-User-Id": "u-creator"}
HI = "दिवाली धमाका! वोल्टारो Glide-S1 अब सबसे सस्ता इलेक्ट्रिक स्कूटर, एक चार्ज में 150 किमी की रेंज, 100% गारंटी के साथ!! यहाँ क्लिक करें और जल्दी करो।"
HG = "Diwali ka sabse best offer! Glide-S1 ab ek charge mein 150 km chalega, pakka guarantee ke saath!! Jaldi karo, yahan click karein. Dhaasu deal sirf 31 Oct 2025 tak."
CLEAN_HI = "वोल्टारो Glide S1 के साथ बारिश में भी आराम से सफ़र करें। नज़दीकी Voltaro Experience Centre पर टेस्ट राइड बुक करें।"


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


def review(c, body):
    r = c.post("/api/dna", headers=H, json={"original": {"body": body}, "modified": {"body": body}}).json()["original"]
    return r, {f["quote"].strip().lower(): f for f in r["findings"]}


with TestClient(app) as c:
    check(lang.detect(HI)["code"] == "hi" and lang.detect(HG)["code"] == "hinglish", "detects Hindi and Hinglish")
    check(lang.detect("Book a test ride of the Voltaro Glide S1 today.")["code"] == "en", "English stays English")

    r, by = review(c, HI)
    check(by["धमाका"]["suggestion"]["replacement"] == "उत्सव" and by["सस्ता"]["suggestion"]["replacement"] == "किफ़ायती",
          "Hindi slang flagged with Devanagari suggestions")
    check("गारंटी" in by and by["गारंटी"]["category"] == "claims", "Hindi guarantee is an unsupported claim")
    check("150" in by and by["150"]["suggestion"]["replacement"] == "120", "wrong range in किमी checked against the fact sheet")
    check("जल्दी करो" in by, "phrase before the danda (।) is matched")
    check(by["यहाँ क्लिक करें"]["suggestion"]["replacement"] == "हमारी वेबसाइट देखें", "Hindi 'click here' gets a Hindi fix")

    r, by = review(c, HG)
    check(by["sabse best"]["suggestion"]["replacement"] == "bahut badhiya", "Hinglish superlative gets a Hinglish fix")
    check("pakka guarantee" in by and "dhaasu" in by and "jaldi karo" in by, "Hinglish claims and slang flagged")
    check(any(f["signature"] == "fact:expired-date" for f in r["findings"]), "expired offer 'tak' date flagged")

    r, by = review(c, CLEAN_HI)
    check(r["score"] >= 85, f"clean Hindi post scores as ready ({r['score']})")

    cid = c.post("/api/content", headers=H, json={"title": "Hindi", "channel": "Instagram", "body": HI}).json()["id"]
    a = c.post(f"/api/content/{cid}/analyze", headers=H).json()
    for f in a["findings"]:
        if (f.get("suggestion") or {}).get("replacement") is not None and f.get("start") is not None:
            c.post(f"/api/analyses/{a['analysis_id']}/decisions", headers=H, json={"finding_id": f["id"], "decision": "accepted"})
    fx = c.post(f"/api/content/{cid}/apply-fixes", headers=H, json={"analysis_id": a["analysis_id"]}).json()
    body = c.get(f"/api/content/{cid}/report", headers=H).json()["version"]["body"]
    check(fx["after"]["score"] > fx["before"]["score"] and "उत्सव" in body and "किफ़ायती" in body, f"Hindi fixes apply: {fx['before']['score']} -> {fx['after']['score']}")
    check(c.get(f"/api/content/{cid}/report", headers=H).json()["language"]["code"] == "hi", "report shows the detected language")
    check(seed.ensure_language_pack() == 0, "language pack is idempotent")

print(f"\nAll {passed} language checks passed.")
