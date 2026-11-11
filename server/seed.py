"""Demo dataset: Voltaro Mobility, a FICTIONAL Indian electric-scooter brand.

All organisations, people, figures and certificates below are invented for the demo.
Seeded submissions are analysed by the real rule engine at setup time (no AI call),
so their findings and scores are genuine outputs of the product, not hard-coded.
"""
import hashlib
import os
import shutil

from . import analysis, auth, db, demo_assets, integrity, learning, storage
from .config import UPLOAD_DIR, WEB_DIR

# Demo sign-in: every demo account uses this password unless INKLOOM_DEMO_PASSWORD is set.
DEMO_PASSWORD = os.environ.get("INKLOOM_DEMO_PASSWORD", "voltaro-demo")
EMAILS = {"u-admin": "asha@voltaro.demo", "u-creator": "rohan@voltaro.demo", "u-agency": "kavya@pixelkite.demo",
          "u-manager": "meera@voltaro.demo", "u-approver": "vikram@voltaro.demo"}

USERS = [
    ("u-admin", "Asha Rao", "admin", "Brand Lead (Admin)"),
    ("u-creator", "Rohan Mehta", "creator", "Content Creator"),
    ("u-agency", "Kavya Nair", "creator", "Agency Partner — PixelKite"),
    ("u-manager", "Meera Iyer", "manager", "Marketing Manager"),
    ("u-approver", "Vikram Sen", "approver", "Head of Brand (Approver)"),
]

GUIDELINES = [
    ("G-VOICE-01", "tone", "Brand voice: calm confidence",
     "Voltaro sounds confident, warm and clear. We explain real benefits in plain words and let facts do the persuading. "
     "We do not hype, shout or use slang like 'dhamaka', 'crazy' or 'no-brainer'. Keep sentences short (under 25 words)."),
    ("G-TONE-02", "tone", "Punctuation and emphasis",
     "Use at most one exclamation mark in a piece of content. Never write whole words in capitals for emphasis; "
     "only approved acronyms (EV, IP67, ARAI, IDC) are capitalised."),
    ("G-CLAIM-01", "claims", "Promotional claims policy",
     "Every performance, comparative or superlative claim (best, fastest, cheapest, #1, guaranteed, zero, lifetime, India's first/most) "
     "must appear in the Approved Claims register with evidence before it is published. When unsure, describe the specific verified benefit instead."),
    ("G-FACT-01", "facts", "Product facts and figures",
     "Numbers about range, charging, speed, warranty and price must match the current Fact Sheet exactly. Range must be quoted "
     "as certified IDC range. Old figures from 2024–25 collateral are withdrawn."),
    ("G-TERM-01", "terminology", "Product and brand naming",
     "Write the product name exactly as 'Voltaro Glide S1' (three words, capital V, G and S, no hyphen). The charger is the 'Voltaro FastCharger'."),
    ("G-VIS-01", "visual", "Colour palette",
     "Use only the approved palette: Voltaro Indigo #3B2FC9 (primary), Spark Amber #FFB020 (accent, calls to action), "
     "Midnight #0E1A3A (text) and Cloud #F5F6FA / white backgrounds. Red is reserved for safety warnings."),
    ("G-VIS-02", "visual", "Logo usage",
     "Use the official logo file only. Never stretch, squash, recolour, rotate or redraw it. Keep clear space equal to the height "
     "of the 'V' symbol on all sides and place it on white, Cloud or Indigo backgrounds."),
    ("G-A11Y-01", "accessibility", "Alternative text for images",
     "Every image, poster and creative must ship with alt text: one or two sentences describing what is shown and the key message."),
    ("G-A11Y-02", "accessibility", "Colour contrast",
     "Text must meet WCAG 2.2 AA contrast: at least 4.5:1 for body text and 3:1 for large headlines."),
    ("G-A11Y-03", "accessibility", "Links and hashtags",
     "Link text must describe its destination (never 'click here'). Hashtags use CamelCase, e.g. #VoltaroGlideS1."),
    ("G-LEGAL-01", "legal", "Offers and validity",
     "Offers must state exact validity dates and link to terms and conditions. Expired offers must be removed from all channels."),
]

TERMS = [
    ("Voltaro Glide S1", ["Voltaro Glide S-1", "VoltaroGlide S1", "Glide-S1", "GlideS1", "Glide S-1", "Voltaro S1"],
     "Use the full name on first mention; 'Glide S1' is fine afterwards.", "G-TERM-01"),
    ("Voltaro FastCharger", ["Voltaro Fast Charger", "Fast-Charger", "Voltaro fast-charger"], "One word, capital F and C.", "G-TERM-01"),
]

PROHIBITED = [
    ("cheap", "Undermines our premium, dependable positioning.", "affordable", "medium", "tone", "G-VOICE-01"),
    ("unbeatable price", "Unverifiable price claim and hype language.", "a fair price", "high", "claims", "G-CLAIM-01"),
    ("no-brainer", "Slang; doesn't fit our calm, respectful voice.", "easy choice", "low", "tone", "G-VOICE-01"),
    ("petrol killer", "Mocks other riders and competitors.", "a cleaner way to ride", "high", "tone", "G-VOICE-01"),
    ("hurry", "Pressure selling conflicts with calm confidence.", "Book now", "low", "tone", "G-VOICE-01"),
    ("dhamaka", "Firecracker/explosion slang; conflicts with festive-campaign rule.", "celebration", "medium", "tone", "G-VOICE-01"),
    ("crazy deal", "Hype language.", "limited-time offer", "medium", "tone", "G-VOICE-01"),
]

FACTS = [
    ("F-RANGE", "Certified range", 120, "km", "The Voltaro Glide S1 has a certified range of 120 km per charge (IDC test cycle).",
     ["range", "charge", "single charge", "goes"], [100, 110], "ARAI certificate ARAI/2026/EV/0412 (fictional)", "2026-08-14"),
    ("F-CHARGE", "Fast-charge time", 50, "min", "0–80% charge in 50 minutes with the Voltaro FastCharger.",
     ["charge", "charging", "0-80", "0–80"], [60, 65], "Voltaro test report VT-CH-22 (fictional)", "2026-08-14"),
    ("F-WARRANTY", "Battery warranty", 3, "years", "Battery warranty: 3 years or 40,000 km, whichever is earlier.",
     ["warranty"], [5], "Warranty policy v4 (fictional)", "2026-07-01"),
    ("F-SPEED", "Top speed", 85, "km/h", "Top speed is 85 km/h.", ["speed", "top speed"], [80], "ARAI certificate ARAI/2026/EV/0412 (fictional)", "2026-08-14"),
    ("F-IP", "Battery protection", None, None, "The battery pack is IP67 rated for dust and water resistance.", ["ip67", "water"], [], "BIS test summary (fictional)", "2026-05-20"),
    ("F-PRICE", "Starting price", None, None, "Ex-showroom price starts at ₹1,19,999 in Bengaluru (Oct 2026).", ["price", "₹"], [], "Pricing memo Oct 2026 (fictional)", "2026-10-01"),
]

CLAIMS = [
    ("C-01", "Red Dot Design Award 2025 winner", "Red Dot Award: Product Design 2025 certificate RD-25-1187 (fictional)"),
    ("C-02", "India's most awarded electric scooter design", "Brand audit Aug 2026: 6 design awards, more than any other Indian e-scooter (fictional PR fact pack)"),
    ("C-03", "Ride up to 120 km on a single charge", "ARAI certified IDC range (F-RANGE)"),
    ("C-04", "Over 50,000 riders across 40 cities", "CRM export, 30 Sep 2026 (fictional)"),
]

COLORS = [("Voltaro Indigo", "#3B2FC9", "Primary"), ("Spark Amber", "#FFB020", "Accent / calls to action"),
          ("Midnight", "#0E1A3A", "Text"), ("Cloud", "#F5F6FA", "Background"), ("White", "#FFFFFF", "Background")]

# (title, channel, owner, body, alt_text, final_status, comment)
SUBMISSIONS = [
    ("Monsoon ride safety reel", "Instagram", "u-creator",
     "Rain or shine, the Voltaro Glide S1 keeps you steady. With an IP67 rated battery pack and combined braking, you can ride through the monsoon with confidence. Book a test ride at your nearest Voltaro Experience Centre.",
     "A rider in a yellow raincoat on a Voltaro Glide S1 crossing a wet city street at dusk.", "approved", None),
    ("Product page FAQ snippet", "Website", "u-creator",
     "The Voltaro Glide S1 offers 120 km of certified range (IDC) and a top speed of 85 km/h. Battery warranty is 3 years or 40,000 km, whichever is earlier.",
     "", "approved", None),
    ("Weekend range blog teaser", "Blog", "u-creator",
     "The Glide-S1 now goes 100 km on one charge — the best range in its class! Plan your weekend escape today.",
     "", "needs_revision", "Range figure is from the old fact sheet and 'best in class' isn't in the claims register. Please fix before resubmitting."),
    ("College campaign banner", "Display ads", "u-agency",
     "Students, the GlideS1 is the cheapest way to beat traffic. 100 km range, 5 year warranty!!", "", "rejected",
     "Off-voice and two outdated facts. Please rework with the current fact sheet."),
    ("Festive service email", "Email", "u-creator",
     "Thank you for riding with Voltaro. Your Glide-S1 is eligible for a free service check this festive season. Click here to book a slot.",
     "", "pending_approval", None),
    ("50,000 riders milestone post", "LinkedIn", "u-creator",
     "Over 50,000 riders across 40 cities now choose the Voltaro Glide S1. Thank you for helping us build a cleaner, quieter way to move.",
     "", "pending_approval", None),
    ("Dealer WhatsApp broadcast", "WhatsApp", "u-agency",
     "HURRY! Voltaro Glide S-1 at an unbeatable price. 0-80% charge in 60 minutes. Best scooter for city riders.", "", "ai_review", None),
    ("New colours teaser", "Instagram", "u-agency",
     "Glide-S1 in three new shades. The best looking scooter in India, guaranteed.", "", "ai_review", None),
    ("Search ad — range", "Search ads", "u-creator",
     "Voltaro Glide S1: 110 km range, best in class. Book a test ride today.", "", "draft", None),
]


# Older, already-published posts (Aug–Sep 2026) with SEEDED reviewer feedback, so the feedback-learning
# model has something to learn from in the demo. Findings come from the real rule engine; only the
# accept/reject decisions are simulated, using the per-rule policy below, and every one of them is
# stored with the note "Seeded demo feedback" so the UI can show seeded vs real decisions separately.
HISTORY = [
    ("Weekend ride diaries", "Instagram", "u-creator",
     "Sunday mornings feel different on a Voltaro Glide S1! Quiet streets, cool air and zero noise. #weekendride #voltaro"),
    ("Charging explained", "Blog", "u-creator",
     "Charging your Glide-S1 at home is simple because the onboard charger works with a standard 15 A socket and the app tells you exactly how long is left so you can plan your day without worrying about range at all. Charges 0–80% in 60 minutes with the Voltaro Fast Charger."),
    ("Festive greetings", "Facebook", "u-agency",
     "Happy Navratri from all of us at Voltaro! Ride bright, ride safe! Zero emissions, all the celebration."),
    ("City commute tips", "LinkedIn", "u-creator",
     "Commuting in Bengaluru traffic is easier on a scooter that is light, quick to park and silent, and our riders tell us that the Voltaro Glide S1 has cut their daily travel time while also cutting fuel costs to nearly nothing every single month."),
    ("Range myth buster", "Instagram", "u-agency",
     "Range anxiety? Not with the GlideS1. Ride 110 km on a single charge. The best way to beat traffic! #rangeanxiety"),
    ("Service centre launch", "Twitter", "u-creator",
     "Our new Pune service centre is open! Book a slot online, and click here for directions."),
    ("Rider story: Ananya", "Blog", "u-agency",
     "Ananya rides 40 km every day across Hyderabad and says the Voltaro Glide S1 is the most comfortable scooter she has owned, with a seat that stays comfortable through long rides and a ride quality that handles potholes without fuss."),
    ("Battery care 101", "Newsletter", "u-creator",
     "Keep your battery between 20% and 80% for daily rides. The battery warranty covers 5 years. Zero maintenance worries!"),
    ("Monsoon offer recap", "Email", "u-agency",
     "Thank you for an amazing monsoon season! Hurry, our crazy deal on accessories is back for one week only!"),
    ("Top speed reel", "Instagram", "u-creator",
     "85 km/h top speed, zero compromise on control. Meet the fastest way across town! #voltaroglide"),
    ("Dealer onboarding note", "Internal", "u-creator",
     "Please brief every new dealer on the Voltaro Glide S1 fact sheet before launch day so that every number they quote to customers about range, charging and warranty matches what the certificate says and nothing older is repeated."),
    ("Accessory launch", "Facebook", "u-agency",
     "New helmets and rain covers for your Voltaro S1 are here! Cheap, cheerful and built for Indian roads."),
    ("Green commute week", "LinkedIn", "u-creator",
     "This Green Commute Week, Voltaro riders across 40 cities saved fuel and time. Zero tailpipe emissions, every single ride."),
    ("Test ride invite", "Email", "u-agency",
     "Your test ride is confirmed! Bring a valid licence and arrive ten minutes early. #testride"),
]
# Simulated reviewer behaviour: how often the team rejected each rule family as a false positive.
SEED_REJECT_RATE = {"a11y:long-sentence": 0.85, "a11y:hashtag-case": 0.7, "tone:exclamation": 0.65, "claim": 0.55}


def _seed_feedback() -> None:
    for i, (title, channel, owner, body) in enumerate(HISTORY):
        ts = f"2026-{8 + i // 8:02d}-{(i * 4) % 27 + 1:02d}T10:30:00Z"
        cid = db.ex("INSERT INTO content(title, channel, status, owner_id, confidential, current_version, is_demo, created_at, updated_at)"
                    " VALUES (?,?,?,?,0,1,1,?,?)", (title, channel, "approved", owner, ts, ts))
        db.ex("INSERT INTO versions(content_id, number, body, alt_text, attachments, created_by, created_at, note) VALUES (?,?,?,?,?,?,?,?)",
              (cid, 1, body, "", "[]", owner, ts, "Seeded demo content (published archive)"))
        res = analysis.evaluate(body, "", [], allow_ai=False)
        aid = db.ex("INSERT INTO analyses(content_id, version_number, mode, engine_note, score, dimensions, findings, retrieved, ai_error, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (cid, 1, "rules", "Seeded demo data, analysed by the rule engine during setup.", res["score"], db.j(res["dimensions"]),
                     db.j(res["findings"]), db.j(res["retrieved"]), None, ts))
        for f in res["findings"]:
            fam = learning.family(f)
            rate = SEED_REJECT_RATE.get(fam, SEED_REJECT_RATE.get(fam.split(":")[0], 0.08))
            u = int(hashlib.sha256(f"{title}|{f['id']}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
            db.ex("INSERT INTO decisions(analysis_id, finding_id, decision, user_id, note, at) VALUES (?,?,?,?,?,?)",
                  (aid, f["id"], "rejected" if u < rate else "accepted", owner, learning.SEED_NOTE, ts))
        c = db.one("SELECT * FROM content WHERE id=?", (cid,))
        v = db.one("SELECT * FROM versions WHERE content_id=? AND number=1", (cid,))
        h = integrity.version_hash(c, v)
        db.ex("UPDATE content SET approved_version=1, approved_hash=? WHERE id=?", (h, cid))
        snap = db.j({"title": title, "body": body, "alt_text": "", "version": 1, "hash": h, "score": res["score"], "note": "Seeded approval"})
        for action, frm, to, actor, note in (("created", None, "draft", owner, "Seeded demo content (published archive)"),
                                             ("approved", "pending_approval", "approved", "u-approver", snap)):
            db.ex("INSERT INTO events(content_id, user_id, action, from_status, to_status, note, at) VALUES (?,?,?,?,?,?,?)",
                  (cid, actor, action, frm, to, note, ts))


def set_demo_credentials() -> None:
    for uid, email in EMAILS.items():
        u = db.one("SELECT password_hash FROM users WHERE id=?", (uid,))
        if u and not u["password_hash"]:
            db.ex("UPDATE users SET email=?, password_hash=? WHERE id=?", (email, auth.hash_password(DEMO_PASSWORD), uid))


def _add_asset(src, name, kind="logo"):
    dest = UPLOAD_DIR / f"brand_{src.name}"
    shutil.copy(src, dest)
    storage.save_file(dest, "image/png")
    from . import visual
    return db.ex("INSERT INTO assets(kind, name, path, mime, meta, created_at) VALUES (?,?,?,?,?,?)",
                 (kind, name, str(dest), "image/png", db.j({"palette": visual.palette(dest)}), db.now()))


def seed() -> None:
    db.conn()
    for u in USERS:
        db.ex("INSERT INTO users(id, name, role, title) VALUES (?,?,?,?)", u)
    set_demo_credentials()
    for gid, cat, title, body in GUIDELINES:
        db.ex("INSERT INTO guidelines(id, category, title, body, version, source, updated_at) VALUES (?,?,?,?,1,?,?)",
              (gid, cat, title, body, "Voltaro Brand Guidelines v3 (seed)", db.now()))
    for pref, dis, note, gid in TERMS:
        db.ex("INSERT INTO terms(preferred, disallowed, note, guideline_id) VALUES (?,?,?,?)", (pref, db.j(dis), note, gid))
    for p in PROHIBITED:
        db.ex("INSERT INTO prohibited(phrase, reason, replacement, severity, category, guideline_id) VALUES (?,?,?,?,?,?)", p)
    for f in FACTS:
        db.ex("INSERT INTO facts(id, label, value, unit, statement, keywords, outdated_values, source, verified_on) VALUES (?,?,?,?,?,?,?,?,?)",
              (f[0], f[1], f[2], f[3], f[4], db.j(f[5]), db.j(f[6]), f[7], f[8]))
    for c in CLAIMS:
        db.ex("INSERT INTO claims(id, text, evidence, approved_by) VALUES (?,?,?,?)", (*c, "Asha Rao"))
    for c in COLORS:
        db.ex("INSERT INTO colors(name, hex, usage) VALUES (?,?,?)", c)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    assets = demo_assets.generate(UPLOAD_DIR / "_brand", WEB_DIR / "demo")
    _add_asset(assets["logo"], "Voltaro primary logo")

    for i, (title, channel, owner, body, alt, final, comment) in enumerate(SUBMISSIONS):
        ts = f"2026-{10 + (i // 5):02d}-{(i * 3) % 27 + 1:02d}T{9 + i % 8:02d}:15:00Z"
        cid = db.ex("INSERT INTO content(title, channel, status, owner_id, confidential, current_version, is_demo, created_at, updated_at)"
                    " VALUES (?,?,?,?,0,1,1,?,?)", (title, channel, "draft", owner, ts, ts))
        db.ex("INSERT INTO versions(content_id, number, body, alt_text, attachments, created_by, created_at, note) VALUES (?,?,?,?,?,?,?,?)",
              (cid, 1, body, alt, "[]", owner, ts, "Seeded demo content"))
        db.ex("INSERT INTO events(content_id, user_id, action, from_status, to_status, note, at) VALUES (?,?,?,?,?,?,?)",
              (cid, owner, "created", None, "draft", "Seeded demo content", ts))
        if final == "draft":
            continue
        res = analysis.evaluate(body, alt, [], allow_ai=False)
        db.ex("INSERT INTO analyses(content_id, version_number, mode, engine_note, score, dimensions, findings, retrieved, ai_error, created_at)"
              " VALUES (?,?,?,?,?,?,?,?,?,?)",
              (cid, 1, "rules", "Seeded demo data, analysed by the rule engine during setup.", res["score"], db.j(res["dimensions"]),
               db.j(res["findings"]), db.j(res["retrieved"]), None, ts))
        path = {"ai_review": ["ai_review"], "pending_approval": ["ai_review", "pending_approval"],
                "needs_revision": ["ai_review", "pending_approval", "needs_revision"],
                "rejected": ["ai_review", "pending_approval", "rejected"], "approved": ["ai_review", "pending_approval", "approved"]}[final]
        prev = "draft"
        for st in path:
            actor = {"ai_review": owner, "pending_approval": owner, "needs_revision": "u-manager", "rejected": "u-approver", "approved": "u-approver"}[st]
            note = comment if st in ("needs_revision", "rejected") else ""
            if st == "approved":
                c = db.one("SELECT * FROM content WHERE id=?", (cid,))
                v = db.one("SELECT * FROM versions WHERE content_id=? AND number=1", (cid,))
                h = integrity.version_hash(c, v)
                db.ex("UPDATE content SET approved_version=1, approved_hash=? WHERE id=?", (h, cid))
                note = db.j({"title": title, "body": body, "alt_text": alt, "version": 1, "hash": h, "score": res["score"], "note": "Seeded approval"})
            db.ex("INSERT INTO events(content_id, user_id, action, from_status, to_status, note, at) VALUES (?,?,?,?,?,?,?)",
                  (cid, actor, {"ai_review": "ai_review", "pending_approval": "submitted", "needs_revision": "revision_requested",
                                "rejected": "rejected", "approved": "approved"}[st], prev, st, note, ts))
            prev = st
        if comment:
            db.ex("INSERT INTO comments(content_id, user_id, body, at) VALUES (?,?,?,?)",
                  (cid, "u-manager" if final == "needs_revision" else "u-approver", comment, ts))
        db.ex("UPDATE content SET status=? WHERE id=?", (final, cid))
    _seed_feedback()
    learning.train()
