"""Approval Integrity Shield: hash the approved version, detect any later change."""
import difflib
import re
import hashlib
import json

from . import db


def version_hash(content: dict, version: dict) -> str:
    atts = db.pj(version["attachments"], [])
    ids = [a["id"] for a in atts]
    shas = []
    if ids:
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r["sha256"] for r in db.q(f"SELECT id, sha256 FROM uploads WHERE id IN ({marks})", tuple(ids))}
        shas = [rows.get(i) for i in ids]
    canonical = json.dumps({"title": content["title"], "body": version["body"] or "", "alt_text": version["alt_text"] or "",
                            "attachments": shas}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text_diff(a: str, b: str) -> list[dict]:
    """Word-level diff (readable for people, unlike character diffs)."""
    ta, tb = re.findall(r"\s+|\w+|[^\w\s]", a or ""), re.findall(r"\s+|\w+|[^\w\s]", b or "")
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        out.append({"op": op, "old": "".join(ta[i1:i2]), "new": "".join(tb[j1:j2])})
    return out


def snapshot(content_id: int) -> dict | None:
    """The record written at approval time (stored in the event log)."""
    e = db.one("SELECT note FROM events WHERE content_id=? AND action='approved' ORDER BY id DESC LIMIT 1", (content_id,))
    return db.pj(e["note"], None) if e else None


def verify(content_id: int) -> dict:
    c = db.one("SELECT * FROM content WHERE id=?", (content_id,))
    if not c or not c["approved_hash"]:
        return {"status": "not_approved"}
    snap = snapshot(content_id) or {}
    cur = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (content_id, c["current_version"]))
    actual = version_hash(c, cur)
    ok = actual == c["approved_hash"]
    res = {"status": "intact" if ok else "modified", "expected": c["approved_hash"], "actual": actual,
           "approved_version": c["approved_version"], "current_version": c["current_version"]}
    if not ok:
        res["diff"] = {
            "body": text_diff(snap.get("body", ""), cur["body"] or ""),
            "alt_text": text_diff(snap.get("alt_text", ""), cur["alt_text"] or ""),
            "title_changed": snap.get("title") not in (None, c["title"]),
        }
        open_alert = db.one("SELECT id FROM integrity_alerts WHERE content_id=? AND resolved=0 AND actual=?", (content_id, actual))
        if not open_alert:
            db.ex("INSERT INTO integrity_alerts(content_id, detected_at, expected, actual, diff, source) VALUES (?,?,?,?,?,?)",
                  (content_id, db.now(), c["approved_hash"], actual, db.j(res["diff"]), "verification"))
        if c["status"] == "approved":
            db.ex("UPDATE content SET status='modified_after_approval', updated_at=? WHERE id=?", (db.now(), content_id))
            db.ex("INSERT INTO events(content_id, user_id, action, from_status, to_status, note, at) VALUES (?,?,?,?,?,?,?)",
                  (content_id, "system", "integrity_violation", "approved", "modified_after_approval",
                   "Content no longer matches the SHA-256 recorded at approval. Re-review required.", db.now()))
    return res


def verify_all() -> list[dict]:
    out = []
    for c in db.q("SELECT id, title FROM content WHERE approved_hash IS NOT NULL"):
        r = verify(c["id"])
        out.append({"content_id": c["id"], "title": c["title"], **{k: r[k] for k in ("status",)}})
    return out
