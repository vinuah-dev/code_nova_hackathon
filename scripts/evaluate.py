"""Round 3 improvement 3: evaluate the reviewer and the learning model on a labelled benchmark.

The benchmark is built deterministically from clean sentences plus planted issues whose category and
exact words are known, so every expected finding is labelled by construction (English, Hindi, Hinglish).
For each engine we report precision, recall and F1:
  rules      the deterministic rule engine only
  ai+rules   the full product (Gemini + rules), only with --ai
Then every finding the full product produced is labelled correct (matches a planted issue) or a false
alarm, and the feedback-learning model is cross-validated on those labels against the engine's own
confidence (the same quality gate the app uses).

Run:  python scripts/evaluate.py           (rules only, ~10 s)
      python scripts/evaluate.py --ai      (also Gemini; needs GEMINI_API_KEY in .env; several minutes)
Writes scripts/eval_benchmark.json (the labelled set) and server/eval_results.json (shown in the app).
"""
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_eval_")
os.environ["INKLOOM_DB"] = "sqlite"
USE_AI = "--ai" in sys.argv
if not USE_AI:
    os.environ["INKLOOM_DISABLE_AI"] = "1"

from server import config  # noqa: E402

config.load_env()
os.environ["INKLOOM_DB"] = "sqlite"

import numpy as np  # noqa: E402

from server import analysis, db, learning, seed  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

CLEAN = [
    "The Voltaro Glide S1 is designed for calm, everyday city rides.",
    "Book a test ride at your nearest Voltaro Experience Centre.",
    "The battery pack is IP67 rated for dust and water resistance.",
    "Charge 0-80% in 50 minutes with the Voltaro FastCharger.",
    "The Voltaro Glide S1 has a certified range of 120 km per charge.",
    "Plan your weekend rides with the Voltaro app.",
    "Our service team is ready to help with your first ride.",
    "Ride through the monsoon with confidence.",
]
# (text, [(category, exact quote that must be flagged)])
PLANTED = [
    ("The Glide-S1 is ready for your commute.", [("terminology", "Glide-S1")]),
    ("Meet the GlideS1, built for busy streets.", [("terminology", "GlideS1")]),
    ("The Voltaro S1 handles city traffic with ease.", [("terminology", "Voltaro S1")]),
    ("Top up at home with the Voltaro Fast Charger.", [("terminology", "Voltaro Fast Charger")]),
    ("Ride 150 km on a single charge.", [("facts", "150")]),
    ("Ride 110 km on a single charge.", [("facts", "110")]),
    ("It charges 0-80% in 60 minutes.", [("facts", "60")]),
    ("Every scooter has a battery warranty of 5 years.", [("facts", "5")]),
    ("Reach a top speed of 80 km/h.", [("facts", "80")]),
    ("It is the best scooter in India.", [("claims", "best")]),
    ("This is the fastest way to cross town.", [("claims", "fastest")]),
    ("Savings are guaranteed for every rider.", [("claims", "guaranteed")]),
    ("Enjoy zero maintenance for years.", [("claims", "zero maintenance")]),
    ("Expect unbeatable comfort on rough roads.", [("claims", "unbeatable")]),
    ("Get it at an unbeatable price this month.", [("claims", "unbeatable price")]),
    ("It is a cheap way to commute.", [("tone", "cheap")]),
    ("Switching is a no-brainer.", [("tone", "no-brainer")]),
    ("Grab this crazy deal today.", [("tone", "crazy deal")]),
    ("Hurry, stocks are limited.", [("tone", "Hurry")]),
    ("Join the festive dhamaka at our showroom.", [("tone", "dhamaka")]),
    ("It is a petrol killer on two wheels.", [("tone", "petrol killer")]),
    ("Click here to book a test ride.", [("accessibility", "Click here")]),
    ("Weekend rides feel amazing!!", [("tone", "!!")]),
    ("Get HUGE savings on accessories.", [("tone", "HUGE")]),
    ("Offer valid till 31 Dec 2025.", [("facts", "2025")]),
    ("दिवाली धमाका ऑफ़र आ गया है।", [("tone", "धमाका")]),
    ("यह सबसे सस्ता स्कूटर नहीं, सबसे भरोसेमंद है।", [("tone", "सस्ता")]),
    ("एक चार्ज में 150 किमी की रेंज पाइए।", [("facts", "150")]),
    ("हर खरीद पर गारंटी के साथ।", [("claims", "गारंटी")]),
    ("जल्दी करो, स्टॉक सीमित है।", [("tone", "जल्दी करो")]),
    ("यहाँ क्लिक करें और टेस्ट राइड बुक करें।", [("accessibility", "यहाँ क्लिक करें")]),
    ("Yeh sabse best scooter hai.", [("claims", "sabse best")]),
    ("Jaldi karo, offer limited hai.", [("tone", "Jaldi karo")]),
    ("Pakka guarantee ke saath ghar le jao.", [("claims", "pakka guarantee")]),
    ("Dhaasu deal sirf is hafte.", [("tone", "Dhaasu")]),
    ("Yahan click karein aur ride book karein.", [("accessibility", "Yahan click karein")]),
]
# Harder issues no keyword rule covers: they need judgement (implied claims, mocking competitors).
# These show what the AI adds on top of the rules.
SEMANTIC = [
    ("Leave every other scooter in the dust.", [("claims", "Leave every other scooter in the dust")]),
    ("Other brands' scooters break down all the time.", [("tone", "Other brands' scooters break down all the time")]),
    ("Doctors recommend riding a Voltaro every day.", [("claims", "Doctors recommend riding a Voltaro")]),
    ("You will never have to think about charging again.", [("claims", "never have to think about charging again")]),
    ("Free service for life with every scooter.", [("claims", "Free service for life")]),
    ("The safest scooter money can buy.", [("claims", "The safest scooter money can buy")]),
    ("Only losers still ride petrol bikes.", [("tone", "Only losers still ride petrol bikes")]),
    ("Saves you ₹50,000 every year on fuel.", [("claims", "Saves you ₹50,000 every year on fuel")]),
]
PLANTED_ALL = PLANTED + SEMANTIC


def build(n_items=60, clean_items=10, seed_value=7) -> list[dict]:
    rng = random.Random(seed_value)
    items = []
    for i in range(n_items):
        sents = rng.sample(CLEAN, rng.randint(1, 2))
        expected = []
        if i >= clean_items:
            for text, exp in rng.sample(PLANTED_ALL, rng.randint(1, 4)):
                sents.insert(rng.randint(0, len(sents)), text)
                expected += [{"category": c, "quote": q, "semantic": (text, exp) in SEMANTIC} for c, q in exp]
        items.append({"id": f"B{i + 1:03d}", "text": " ".join(sents), "expected": expected})
    # Make sure every semantic case appears at least once, in its own post.
    for j, (text, exp) in enumerate(SEMANTIC):
        items.append({"id": f"S{j + 1:02d}", "text": f"{CLEAN[j % len(CLEAN)]} {text}",
                      "expected": [{"category": c, "quote": q, "semantic": True} for c, q in exp]})
    return items


def match(findings: list[dict], expected: list[dict]) -> tuple[int, int, list[bool]]:
    """A finding is correct if its quote overlaps a planted quote (each planted issue counts once)."""
    used, labels = set(), []
    for f in findings:
        q = (f.get("quote") or "").strip().lower()
        hit = None
        for k, e in enumerate(expected):
            eq = e["quote"].lower()
            if k not in used and q and (eq in q or q in eq):
                hit = k
                break
        if hit is not None:
            used.add(hit)
        labels.append(hit is not None)
    match.last_used = used
    return sum(labels), len(used), labels


def scores(tp_f, n_f, tp_e, n_e) -> dict:
    p = tp_f / n_f if n_f else 0.0
    r = tp_e / n_e if n_e else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "findings": n_f, "correct": tp_f, "missed": n_e - tp_e}


def run_engine(items, allow_ai, engine_filter=None):
    tot = {"tp_f": 0, "n_f": 0, "tp_e": 0, "n_e": 0}
    rows, by_lang, ai_failures = [], {}, 0
    kinds = {"keyword": [0, 0], "semantic": [0, 0]}  # [found, total] per kind of planted issue
    for it in items:
        r = analysis.evaluate(it["text"], "", [], allow_ai=allow_ai)
        if allow_ai and r["mode"] != "ai+rules":
            ai_failures += 1
        fs = [f for f in r["findings"] if engine_filter is None or f["engine"] == engine_filter]
        tp_f, tp_e, labels = match(fs, it["expected"])
        for k, e in enumerate(it["expected"]):
            kind = "semantic" if e.get("semantic") else "keyword"
            kinds[kind][1] += 1
            kinds[kind][0] += k in match.last_used
        for k in tot:
            tot[k] += {"tp_f": tp_f, "n_f": len(fs), "tp_e": tp_e, "n_e": len(it["expected"])}[k]
        lg = "hi" if any("ऀ" <= ch <= "ॿ" for ch in it["text"]) else ("hinglish" if any(w in it["text"].lower().split() for w in ("hai", "karo", "karein", "ke", "sirf")) else "en")
        b = by_lang.setdefault(lg, {"tp_f": 0, "n_f": 0, "tp_e": 0, "n_e": 0})
        b["tp_f"] += tp_f; b["n_f"] += len(fs); b["tp_e"] += tp_e; b["n_e"] += len(it["expected"])
        for f, ok in zip(fs, labels):
            rows.append({**f, "_y": 1.0 if ok else 0.0, "_group": it["id"]})
    out = scores(tot["tp_f"], tot["n_f"], tot["tp_e"], tot["n_e"])
    out["by_language"] = {k: scores(v["tp_f"], v["n_f"], v["tp_e"], v["n_e"]) for k, v in by_lang.items()}
    out["recall_by_kind"] = {k: {"found": f, "total": t, "recall": round(f / t, 3) if t else None} for k, (f, t) in kinds.items()}
    if allow_ai:
        out["ai_unavailable_items"] = ai_failures
    return out, rows


def learning_eval(rows: list[dict]) -> dict:
    """Grouped cross-validation of the feedback-learning model on benchmark-labelled findings."""
    y = np.array([r["_y"] for r in rows])
    groups = sorted({r["_group"] for r in rows})
    if len(rows) < 20 or y.sum() in (0, len(rows)) or len(groups) < 4:
        return {"status": "not enough labelled variety", "n": len(rows), "false_alarms": int(len(rows) - y.sum())}
    vocab = learning._vocab(rows)
    X = learning._matrix(rows, vocab)
    k = min(5, len(groups))
    fold_of = {g: i % k for i, g in enumerate(groups)}
    folds = np.array([fold_of[r["_group"]] for r in rows])
    oof = np.zeros(len(rows))
    for i in range(k):
        tr, te = folds != i, folds == i
        oof[te] = learning._sigmoid(X[te] @ learning._fit(X[tr], y[tr])) if len(set(y[tr])) > 1 else y[tr].mean()
    base = np.array([learning.raw_conf(r) for r in rows])
    m, b = learning._metrics(oof, y), learning._metrics(base, y)
    gain = (b["brier"] - m["brier"]) / b["brier"] if b["brier"] else 0.0
    return {"n": len(rows), "false_alarms": int(len(rows) - y.sum()), "folds": k, "model": m, "baseline": b, "brier_gain": round(gain, 3),
            "passes_gate": bool(gain >= learning.MIN_GAIN and m["accuracy"] >= b["accuracy"])}


def main():
    db.conn()
    seed.seed()
    seed.ensure_language_pack()
    items = build()
    bench = ROOT / "scripts" / "eval_benchmark.json"
    bench.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    n_expected = sum(len(i["expected"]) for i in items)
    print(f"benchmark: {len(items)} posts, {n_expected} labelled issues, {sum(1 for i in items if not i['expected'])} clean posts")
    res_path = ROOT / "server" / "eval_results.json"
    prev = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    results = {"run_at": time.strftime("%Y-%m-%d %H:%M"), "benchmark": {"posts": len(items), "labelled_issues": n_expected,
               "clean_posts": sum(1 for i in items if not i["expected"]), "languages": ["English", "Hindi", "Hinglish"]},
               "engines": {}, "learning": prev.get("learning")}
    t = time.time()
    results["engines"]["rules"], rule_rows = run_engine(items, allow_ai=False)
    print("rules", results["engines"]["rules"], f"{time.time() - t:.1f}s")
    if USE_AI and config.ai_configured():
        t = time.time()
        results["engines"]["ai+rules"], rows = run_engine(items, allow_ai=True)
        results["engines"]["ai_only"] = scores(sum(r["_y"] for r in rows if r["engine"] == "ai"), sum(1 for r in rows if r["engine"] == "ai"), 0, 0) | {"recall": None, "f1": None, "missed": None}
        print("ai+rules", results["engines"]["ai+rules"], f"{time.time() - t:.1f}s")
        results["learning"] = learning_eval(rows)
        results["learning"]["source"] = "findings from the full product (AI + rules) on the benchmark"
    else:
        results["engines"].update({k: v for k, v in (prev.get("engines") or {}).items() if k != "rules"})
        if not results.get("learning"):
            results["learning"] = learning_eval(rule_rows) | {"source": "rule-engine findings on the benchmark"}
    print("learning", results["learning"])
    res_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", res_path)


if __name__ == "__main__":
    main()
