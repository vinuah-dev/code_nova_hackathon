"""Round 3 improvement 3: checks on the evaluation benchmark and the /api/evaluation endpoint (no AI calls).

Run:  python scripts/eval_test.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["INKLOOM_HEADER_AUTH"] = "1"  # test-only: act as users via X-User-Id
os.environ["INKLOOM_DATA_DIR"] = tempfile.mkdtemp(prefix="inkloom_evt_")
os.environ["INKLOOM_DISABLE_AI"] = "1"
os.environ["INKLOOM_DB"] = "sqlite"
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from server import analysis, learning  # noqa: E402
from server.main import app  # noqa: E402

spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
spec.loader.exec_module(ev)

passed = 0


def check(cond, msg):
    global passed
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    passed += 1
    print(f"  ok  {msg}")


with TestClient(app) as c:
    c.get("/api/status")  # seeds the demo Brand Brain (incl. the Hindi/Hinglish pack) before reviewing directly
    items = ev.build()
    n = sum(len(i["expected"]) for i in items)
    check(n >= 100, f"benchmark has 100+ labelled issues ({n})")
    check(ev.build() == items, "benchmark is deterministic")
    check({"hi", "hinglish", "en"} <= {"hi" if any("ऀ" <= ch <= "ॿ" for ch in i["text"]) else ("hinglish" if " hai" in i["text"] or "karo" in i["text"].lower() else "en") for i in items}, "covers English, Hindi and Hinglish")

    clean = [i for i in items if not i["expected"]]
    false_alarms = sum(len(analysis.evaluate(i["text"], "", [], allow_ai=False)["findings"]) for i in clean)
    check(len(clean) >= 10 and false_alarms == 0, f"no false alarms on {len(clean)} clean posts")

    res, rows = ev.run_engine(items, allow_ai=False)
    check(res["recall_by_kind"]["keyword"]["recall"] >= 0.95 and res["precision"] >= 0.95, f"rules: keyword recall {res['recall_by_kind']['keyword']['recall']}, precision {res['precision']}")
    check(res["recall_by_kind"]["semantic"]["total"] >= 8, "semantic cases are part of the benchmark")
    check(ev.match([{"quote": "150"}], [{"quote": "150", "category": "facts"}])[0] == 1 and ev.match([{"quote": "x"}], [{"quote": "150", "category": "facts"}])[0] == 0, "matching counts exact planted words only")

    e = c.get("/api/evaluation", headers={"X-User-Id": "u-creator"}).json()
    check(e.get("available") and "rules" in e["engines"] and e["benchmark"]["labelled_issues"] >= 100, "app serves the latest benchmark results")
    check(learning.MIN_REAL >= 20, "learning model needs 20+ real decisions before it can change scores")

print(f"\nAll {passed} evaluation checks passed.")
