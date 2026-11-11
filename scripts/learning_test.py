"""Tests for the feedback-learning model, on a throwaway database (no AI calls).

Run:  python scripts/learning_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_learn_")
os.environ["INKLOOM_DISABLE_AI"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from server import learning  # noqa: E402
from server.main import app  # noqa: E402

passed = 0
H = lambda uid: {"X-User-Id": uid}  # noqa: E731


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


# Posts where the team consistently rejects "long sentence" + "exclamation" flags and accepts naming/fact fixes.
POSTS = [
    "Charging the Glide-S1 at home is simple because the onboard charger works with any standard socket and the app tells you how long is left so you can plan your whole day without any worry at all. Wow!",
    "Our riders love how the GlideS1 handles city traffic, and many of them tell us that their daily commute has become calmer, quicker and cheaper than it ever was on their old petrol scooter. Ride on!",
    "The Voltaro S1 is the scooter that our service team recommends to every new rider who asks about a dependable daily commuter for busy Indian cities with heavy traffic and long waits. Great!",
    "Range of 110 km on the Glide S-1 makes weekend trips easy, and families across Pune and Mumbai have told us that they now plan short getaways around their scooter instead of the car. Amazing!",
    "With the Voltaro Fast Charger you can top up during lunch, and riders who use it at our experience centres say that it fits neatly into their day without ever needing to plan a long stop anywhere. Yes!",
    "New helmets for the VoltaroGlide S1 are in stores this week, and our accessory team designed them with extra ventilation for summer rides so that commuters stay cool and comfortable in the heat. Enjoy!",
]

with TestClient(app) as c:
    s = c.get("/api/learning").json()
    m = s["model"]
    check(m is not None and m["info"]["seeded"] > 0 and m["info"]["real"] == 0, f"model trained on seeded demo feedback ({m['info']['n']} decisions)")
    check(m["status"] in ("shadow", "collecting"), f"starts in {m['status']} mode, not changing scores")
    check(m["metrics"] is None or m["metrics"]["folds"] >= 2, "evaluated with grouped cross-validation")

    # Shadow mode: predictions shown but confidence unchanged.
    r = c.post("/api/dna", headers=H("u-creator"), json={"original": {"body": POSTS[0]}, "modified": {"body": POSTS[1]}}).json()
    f0 = r["original"]["findings"][0]
    check("learned" in f0 and f0["learned"]["applied"] is False and "confidence_raw" not in f0, "shadow mode: prediction attached, confidence untouched")

    check(c.post("/api/learning/train", headers=H("u-creator")).status_code == 403, "only admins can retrain")
    check(c.post("/api/learning/mode", headers=H("u-admin"), json={"mode": "bad"}).status_code == 400, "invalid mode rejected")

    # Simulate a team giving consistent feedback on new submissions.
    for i, body in enumerate(POSTS):
        cid = c.post("/api/content", headers=H("u-creator"), json={"title": f"Learning test {i}", "channel": "Blog", "body": body}).json()["id"]
        res = c.post(f"/api/content/{cid}/analyze", headers=H("u-creator")).json()
        aid = res["analysis_id"]
        for f in res["findings"]:
            fam = learning.family(f)
            dec = "rejected" if fam in ("a11y:long-sentence", "tone:exclamation") else "accepted"
            assert c.post(f"/api/analyses/{aid}/decisions", headers=H("u-creator"), json={"finding_id": f["id"], "decision": dec}).status_code == 200

    s = c.get("/api/learning").json()
    m = s["model"]
    print("     ", m["info"], m["metrics"] and m["metrics"]["model"], m["reasons"])
    check(m["info"]["real"] > 0, f"real decisions retrain the model instantly ({m['info']['real']} real)")
    check(m["gate_passed"] and m["status"] == "active", "quality gate passed -> model active")
    check(m["metrics"]["model"]["brier"] < m["metrics"]["baseline"]["brier"], "model beats the engine-confidence baseline out-of-fold")
    labels = {x["label"]: x["weight"] for x in s["signals"]}
    check(labels.get("Long sentence", 0) < 0, "learned that 'long sentence' flags are usually false positives")

    # Active: new reviews get recalibrated confidence and a different score.
    r = c.post("/api/dna", headers=H("u-creator"), json={"original": {"body": POSTS[2]}, "modified": {"body": POSTS[3]}}).json()
    allf = r["original"]["findings"] + r["modified"]["findings"]
    longs = [f for f in allf if f.get("signature") == "a11y:long-sentence"]
    check(longs and longs[0]["learned"]["applied"] and longs[0]["confidence"] < longs[0]["confidence_raw"],
          "active: long-sentence confidence lowered" + (f" ({longs[0]['confidence_raw']} -> {longs[0]['confidence']})" if longs else ""))
    check(len(r["original"]["findings"]) == len([f for f in r["original"]["findings"] if f.get("learned")]), "no finding is hidden by the model")

    # Admin can pin it to shadow.
    s = c.post("/api/learning/mode", headers=H("u-admin"), json={"mode": "shadow"}).json()
    check(s["model"]["status"] == "shadow", "admin pins model to shadow mode")
    r = c.post("/api/dna", headers=H("u-creator"), json={"original": {"body": POSTS[2]}, "modified": {"body": POSTS[3]}}).json()
    check(all(not f["learned"]["applied"] for f in r["original"]["findings"]), "pinned shadow: scores unchanged again")
    c.post("/api/learning/mode", headers=H("u-admin"), json={"mode": "auto"})

print(f"\nAll {passed} learning checks passed.")
