"""Organisation approval policy, set by a brand admin and enforced by the server (not only the UI).

- min_score_to_submit: content below this compliance score cannot be submitted for approval
  (findings marked as false positives do not count). 0 = off.
- require_endorsement: a manager must endorse the current submission before an approver can approve it.
- block_critical: content with an open critical finding cannot be approved, even with an override reason.
"""
from . import db

DEFAULTS = {"min_score_to_submit": 0, "require_endorsement": False, "block_critical": False}


def get() -> dict:
    row = db.one("SELECT value FROM kv WHERE key='policy'")
    stored = db.pj(row["value"], {}) if row else {}
    return {**DEFAULTS, **{k: v for k, v in (stored or {}).items() if k in DEFAULTS}}


def save(data: dict) -> dict:
    cur = get()
    if "min_score_to_submit" in data:
        try:
            v = int(data["min_score_to_submit"])
        except (TypeError, ValueError):
            raise ValueError("Minimum score must be a whole number from 0 to 100")
        if not 0 <= v <= 100:
            raise ValueError("Minimum score must be a whole number from 0 to 100")
        cur["min_score_to_submit"] = v
    for k in ("require_endorsement", "block_critical"):
        if k in data:
            cur[k] = bool(data[k])
    db.ex("INSERT INTO kv(key, value) VALUES ('policy', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (db.j(cur),))
    return cur


def check_submit(analysis: dict) -> str | None:
    p = get()
    score = analysis.get("score_after_review", analysis.get("score"))
    if p["min_score_to_submit"] and score is not None and score < p["min_score_to_submit"]:
        return (f"Policy: content needs a compliance score of at least {p['min_score_to_submit']} to be submitted "
                f"(this version scores {round(score)}). Apply fixes or mark false positives, then submit again.")
    return None


def check_approve(cid: int, analysis: dict | None) -> str | None:
    p = get()
    if p["require_endorsement"]:
        sub = db.one("SELECT id FROM events WHERE content_id=? AND action='submitted' ORDER BY id DESC LIMIT 1", (cid,))
        endorsed = sub and db.one("SELECT id FROM events WHERE content_id=? AND action='endorsed' AND id>? LIMIT 1", (cid, sub["id"]))
        if not endorsed:
            return "Policy: a marketing manager must endorse this submission before it can be approved."
    if p["block_critical"] and analysis:
        crit = [f for f in analysis["findings"] if f["severity"] == "critical" and f.get("decision") != "rejected"]
        if crit:
            return (f"Policy: {len(crit)} critical finding(s) are open. Content with critical issues cannot be approved, "
                    "even with an override. Fix them or mark them as false positives.")
    return None
