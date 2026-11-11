"""End-to-end API test of the full demo journey, on a throwaway database.

Run:  python scripts/smoke_test.py            (rule engine only, no API calls)
      INKLOOM_TEST_NO_AI=0 python scripts/smoke_test.py   (also exercises Claude if a key is configured)
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_test_")
os.environ.setdefault("INKLOOM_TEST_NO_AI", "1")
if os.environ["INKLOOM_TEST_NO_AI"] == "1":
    os.environ["INKLOOM_DISABLE_AI"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

DEMO = ROOT / "web" / "demo"
passed = 0


def H(uid):
    return {"X-User-Id": uid}


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


with TestClient(app, headers={"X-User-Id": "u-creator"}) as c:
    st = c.get("/api/status").json()
    check("ai_configured" in st, f"status endpoint (AI configured: {st['ai_configured']})")
    brand = c.get("/api/brand").json()
    check(len(brand["guidelines"]) >= 10 and brand["assets"], "Brand Brain seeded with guidelines and official logo")

    # Demo step 2: upload brand guidelines PDF (admin)
    r = c.post("/api/brand/documents", headers=H("u-admin"), json={"name": "Voltaro_Brand_Book_2026.pdf", "mime": "application/pdf", "data": b64(DEMO / "Voltaro_Brand_Book_2026.pdf")})
    check(r.status_code == 200 and r.json()["chars"] > 200, f"brand book PDF uploaded and text extracted ({r.json().get('chars')} chars)")
    hits = c.get("/api/brand/search", params={"q": "firecracker festive diwali"}).json()
    check(any(h["id"].startswith("DOC-") for h in hits), "retrieval finds the uploaded brand book paragraph")
    r = c.post("/api/brand/facts", headers=H("u-creator"), json={"label": "x", "statement": "y"})
    check(r.status_code == 403, "creators cannot edit the Brand Brain (role check)")
    r = c.post("/api/brand/facts", headers=H("u-admin"), json={"label": "Boot space", "value": 26, "unit": "litres", "statement": "Under-seat storage is 26 litres.", "keywords": "storage, boot", "source": "Spec sheet"})
    check(r.status_code == 200, "admin adds an approved fact")

    # Demo step 4: creator uploads poster + logo + caption
    poster = c.post("/api/uploads", headers=H("u-creator"), json={"name": "diwali_poster.png", "mime": "image/png", "kind": "poster", "data": b64(DEMO / "diwali_poster.png")}).json()
    logo = c.post("/api/uploads", headers=H("u-creator"), json={"name": "logo_used_in_poster.png", "mime": "image/png", "kind": "logo", "data": b64(DEMO / "logo_used_in_poster.png")}).json()
    check(poster["meta"]["palette"], "poster uploaded, palette extracted")
    caption = (DEMO / "diwali_caption.txt").read_text(encoding="utf-8")
    cid = c.post("/api/content", headers=H("u-creator"), json={"title": "Diwali launch poster", "channel": "Instagram", "body": caption, "alt_text": "", "attachments": [poster["id"], logo["id"]]}).json()["id"]

    # Steps 5-7: review
    res = c.post(f"/api/content/{cid}/analyze", headers=H("u-creator")).json()
    cats = {f["category"] for f in res["findings"]}
    titles = [f["title"] for f in res["findings"]]
    print("     findings:", len(res["findings"]), "score:", res["score"], "mode:", res["mode"])
    for f in res["findings"]:
        print(f"       [{f['severity']:8}] {f['category']:13} {f['title']} - {f.get('quote')!r}")
    check({"claims", "facts", "terminology", "tone", "visual", "accessibility"} <= cats, "findings cover all six dimensions")
    check(any("stretched" in t.lower() for t in titles) and any("recoloured" in t.lower() for t in titles), "logo distortion and recolouring detected")
    check(any(t == "Unapproved brand colour" for t in titles), "off-brand poster colour detected")
    check(any(t == "Missing image alt text" for t in titles), "missing alt text detected")
    check(all(f["sources"] for f in res["findings"] if f["engine"] == "rules"), "every rule finding cites an approved source")
    check(res["score"] < 60, f"non-compliant content scores low ({res['score']})")

    rep = c.get(f"/api/content/{cid}/report").json()
    aid = rep["analysis"]["id"]
    fixable = [f for f in rep["analysis"]["findings"] if f["suggestion"] and f["suggestion"].get("replacement") and f["start"] is not None and f["target"] == "body"]
    # Step 9: accept all text fixes except one, reject one as a false positive
    for f in fixable[:-1]:
        c.post(f"/api/analyses/{aid}/decisions", headers=H("u-creator"), json={"finding_id": f["id"], "decision": "accepted"})
    c.post(f"/api/analyses/{aid}/decisions", headers=H("u-creator"), json={"finding_id": fixable[-1]["id"], "decision": "rejected", "note": "test"})
    r = c.post(f"/api/content/{cid}/apply-fixes", headers=H("u-creator"), json={"analysis_id": aid})
    check(r.status_code == 200, f"accepted fixes applied as a new version ({r.json().get('version')})")
    fx = r.json()
    print("     before:", fx["before"]["score"], "after:", fx["after"]["score"], "applied:", len(fx["applied"]), "skipped:", len(fx["skipped"]))
    new_body = c.get(f"/api/content/{cid}").json()["versions"][0]["body"]
    print("     revised text:", new_body)
    check(fx["after"]["score"] > fx["before"]["score"], "step 10: revised score is higher than original")
    v = c.get(f"/api/content/{cid}").json()["versions"]
    check(v[-1]["body"] == caption, "original version is preserved untouched")

    dna = c.get(f"/api/content/{cid}/dna", params={"a": 1, "b": 2}).json()
    check(dna["resolved"] and dna["delta"] > 0, f"Brand DNA comparison: {len(dna['resolved'])} resolved, delta {dna['delta']}")

    # Steps 11-12: submit -> approve
    r = c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={})
    check(r.status_code == 400, "cannot approve before submission")
    check(c.post(f"/api/content/{cid}/submit", headers=H("u-creator"), json={}).status_code == 200, "step 11: submitted for approval")
    check(c.post(f"/api/content/{cid}/approve", headers=H("u-manager"), json={}).status_code == 403, "manager cannot give final approval")
    check(c.post(f"/api/content/{cid}/endorse", headers=H("u-manager"), json={"note": "Looks good after fixes"}).status_code == 200, "manager endorses")
    r = c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={})
    check(r.status_code == 409, "approval blocked while serious findings are open (no override reason)")
    r = c.post(f"/api/content/{cid}/approve", headers=H("u-approver"), json={"override_reason": "Poster visuals will be re-exported by design team; caption approved."})
    check(r.status_code == 200 and len(r.json()["hash"]) == 64, "step 12: approved with recorded override; SHA-256 stored")

    # Step 13: Integrity Shield
    check(c.post(f"/api/content/{cid}/verify").json()["status"] == "intact", "integrity verified intact")
    c.post(f"/api/content/{cid}/simulate-tamper", headers=H("u-admin"), json={})
    ver = c.post(f"/api/content/{cid}/verify").json()
    check(ver["status"] == "modified" and any(d["op"] != "equal" for d in ver["diff"]["body"]), "step 13: out-of-band edit detected with diff")
    check(c.get(f"/api/content/{cid}").json()["status"] == "modified_after_approval", "status forced back to re-review")
    r = c.put(f"/api/content/{cid}", headers=H("u-creator"), json={"body": "edited"})
    check(r.status_code == 200, "in-app edit after approval creates a new version")

    # Step 14: Brand Intelligence
    ins = c.get("/api/insights").json()
    print("     insights:", [i["title"] for i in ins])
    check(len(ins) >= 2, "step 14: recurring mistakes surfaced as guideline gaps")
    p = c.post(f"/api/insights/{ins[0]['id']}/propose", headers=H("u-admin")).json()
    check(p["text"], f"guideline improvement proposed ({p['engine']})")
    check(c.post(f"/api/insights/{ins[0]['id']}/decide", headers=H("u-admin"), json={"decision": "approved"}).status_code == 200, "admin approves guideline change")
    check(c.get("/api/brand").json()["history"], "guideline history recorded")

    an = c.get("/api/analytics").json()
    check(an["submissions"] >= 10 and an["top_guidelines"], f"analytics: {an['submissions']} submissions, avg {an['overall_score']}")

    sim = c.post("/api/dna", headers=H("u-creator"), json={"original": {"body": "The Voltaro Glide S1 offers 120 km of certified range."}, "modified": {"body": "The Glide-S1 offers 150 km, the best range ever!!"}}).json()
    check(sim["delta"] < 0 and sim["introduced"], f"DNA simulator on free text: {sim['original']['score']} -> {sim['modified']['score']}")

    # Confidential content never reaches the AI
    cid2 = c.post("/api/content", headers=H("u-creator"), json={"title": "Unreleased model teaser", "body": "Coming soon.", "confidential": True}).json()["id"]
    r2 = c.post(f"/api/content/{cid2}/analyze", headers=H("u-creator")).json()
    check(r2["mode"] == "rules" and "confidential" in r2["note"].lower(), "confidential content is reviewed by rules only")

print(f"\nAll {passed} checks passed.")
