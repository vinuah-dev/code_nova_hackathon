"""Inkloom AI — HTTP API + static web app."""
import base64
import binascii
import hashlib
import io
import re
import threading
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import analysis, auth, config, db, gaps, integrity, learning, rag, scoring, storage, visual
from .config import UPLOAD_DIR, WEB_DIR

config.load_env()
app = FastAPI(title="Inkloom AI", version="0.1.0")

MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain", "text/markdown"}
PERMS = {
    "brand": {"admin"},
    "create": {"creator", "admin"},
    "edit": {"creator", "admin"},
    "review": {"creator", "manager", "approver", "admin"},
    "decide_fix": {"creator", "manager", "admin"},
    "comment": {"creator", "manager", "approver", "admin"},
    "request_revision": {"manager", "approver", "admin"},
    "endorse": {"manager", "admin"},
    "approve": {"approver", "admin"},
}
STATUS_LABEL = {"draft": "Draft", "ai_review": "AI Reviewed", "needs_revision": "Needs Revision",
                "pending_approval": "Pending Approval", "approved": "Approved", "rejected": "Rejected",
                "modified_after_approval": "Modified after approval"}


_ready = False
_ready_lock = threading.Lock()


def ensure_ready() -> None:
    """Create + seed the database on first use (works with or without ASGI lifespan events)."""
    global _ready
    if _ready:
        return
    with _ready_lock:
        if not _ready:
            with db.global_lock():  # Postgres: only one cold-starting instance seeds
                if not db.one("SELECT id FROM users LIMIT 1"):
                    from . import seed
                    seed.seed()
            if db.one("SELECT id FROM users WHERE password_hash IS NULL LIMIT 1"):
                from . import seed
                seed.set_demo_credentials()
            if not db.one("SELECT id FROM ml_models LIMIT 1"):
                learning.train()  # existing databases from before feedback learning
            _ready = True


PUBLIC_API = {"/api/status", "/api/auth/login", "/api/auth/demo-login", "/api/auth/demo-accounts", "/api/auth/logout"}


@app.middleware("http")
async def _auth_mw(request, call_next):
    path = request.url.path
    if not path.startswith("/api/"):
        res = await call_next(request)
        if path.endswith((".js", ".css", ".html")) or path == "/":
            res.headers["Cache-Control"] = "no-cache"  # always revalidate, so a new deploy is picked up at once
        return res
    await run_in_threadpool(ensure_ready)
    uid = await run_in_threadpool(auth.resolve, request.cookies.get(auth.COOKIE))
    if not uid and auth.header_auth_enabled():
        uid = request.headers.get("x-user-id")
    if not uid and path not in PUBLIC_API:
        return JSONResponse(status_code=401, content={"detail": "Please sign in."})
    tok = auth.current_user_id.set(uid)
    try:
        return await call_next(request)
    finally:
        auth.current_user_id.reset(tok)


# ---------------------------------------------------------------- helpers
def user(_header: str | None = None) -> dict:
    """The signed-in user (from the session cookie). The old X-User-Id argument is ignored."""
    u = db.one("SELECT * FROM users WHERE id=?", (auth.current_user_id.get() or "",))
    if not u:
        raise HTTPException(401, "Please sign in.")
    return u


# ---------------------------------------------------------------- auth
def _login_response(request: Request, u: dict) -> JSONResponse:
    token = auth.create_session(u["id"])
    res = JSONResponse({"user": auth.public(u)})
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    res.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure, path="/")
    return res


@app.post("/api/auth/login")
def login(request: Request, data: dict = Body(...)):
    email, pw = (data.get("email") or "").strip(), data.get("password") or ""
    if not email or not pw:
        raise HTTPException(400, "Enter your email and password.")
    try:
        u = auth.check_password(email, pw)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    if not u:
        raise HTTPException(401, "Email or password is incorrect.")
    return _login_response(request, u)


@app.get("/api/auth/demo-accounts")
def demo_accounts():
    if not auth.demo_login_enabled():
        return {"enabled": False, "accounts": []}
    rows = db.q("SELECT * FROM users WHERE email IS NOT NULL ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'creator' THEN 1 WHEN 'manager' THEN 2 ELSE 3 END")
    return {"enabled": True, "accounts": [auth.public(u) for u in rows]}


@app.post("/api/auth/demo-login")
def demo_login(request: Request, data: dict = Body(...)):
    if not auth.demo_login_enabled():
        raise HTTPException(403, "Demo sign-in is turned off.")
    u = db.one("SELECT * FROM users WHERE id=?", (data.get("user_id") or "",))
    if not u:
        raise HTTPException(404, "Unknown demo account")
    return _login_response(request, u)


@app.get("/api/auth/me")
def me():
    return {"user": auth.public(user()), "demo_login": auth.demo_login_enabled()}


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.end_session(request.cookies.get(auth.COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE, path="/")
    return res


def need(u: dict, perm: str) -> None:
    if u["role"] not in PERMS[perm]:
        raise HTTPException(403, f"Your role ({u['role']}) cannot do this. Allowed: {', '.join(sorted(PERMS[perm]))}.")


def event(cid: int, uid: str, action: str, frm: str | None, to: str | None, note: str = "") -> None:
    db.ex("INSERT INTO events(content_id, user_id, action, from_status, to_status, note, at) VALUES (?,?,?,?,?,?,?)",
          (cid, uid, action, frm, to, note, db.now()))


def set_status(c: dict, to: str, uid: str, action: str, note: str = "") -> None:
    db.ex("UPDATE content SET status=?, updated_at=? WHERE id=?", (to, db.now(), c["id"]))
    event(c["id"], uid, action, c["status"], to, note)


def content_or_404(cid: int) -> dict:
    c = db.one("SELECT * FROM content WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "Content not found")
    return c


def save_upload(name: str, mime: str, data_b64: str, kind: str) -> dict:
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Unsupported file type {mime}. Use PNG, JPEG, WEBP, PDF or text.")
    try:
        raw = base64.b64decode(data_b64.split(",")[-1], validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "File data is not valid base64")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "File is larger than 15 MB")
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf",
           "text/plain": ".txt", "text/markdown": ".md"}[mime]
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(raw)
    text, meta = None, {}
    if mime == "application/pdf":
        try:
            from pypdf import PdfReader
            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        except Exception as e:  # malformed PDFs should not crash the request
            path.unlink(missing_ok=True)
            raise HTTPException(400, f"Could not read PDF: {e}")
    elif mime.startswith("text/"):
        text = raw.decode("utf-8", errors="replace")
    else:
        try:
            meta["palette"] = visual.palette(path)
            from PIL import Image
            with Image.open(path) as im:
                meta["size"] = im.size
        except Exception:
            path.unlink(missing_ok=True)
            raise HTTPException(400, "Could not read image")
    storage.save(path, raw, mime)  # also kept in the database when one is configured
    uid = db.ex("INSERT INTO uploads(kind, name, path, mime, sha256, text, meta, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, name, str(path), mime, hashlib.sha256(raw).hexdigest(), text, db.j(meta), db.now()))
    return public_upload(db.one("SELECT * FROM uploads WHERE id=?", (uid,)))


def public_upload(u: dict) -> dict:
    return {"id": u["id"], "kind": u["kind"], "name": u["name"], "mime": u["mime"], "sha256": u["sha256"],
            "meta": db.pj(u["meta"], {}), "has_text": bool(u.get("text")), "url": f"/api/files/upload/{u['id']}"}


# ---------------------------------------------------------------- status & users
@app.get("/api/status")
def status():
    return {"ai_configured": config.ai_configured(), "provider": config.provider(), "provider_label": config.provider_label(), "model": config.model(), "effort": config.effort(),
            "scoring": scoring.explain(), "status_labels": STATUS_LABEL, "permissions": {k: sorted(v) for k, v in PERMS.items()}}


@app.get("/api/users")
def users():
    return db.q("SELECT id, name, role, title, email FROM users ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'creator' THEN 1 WHEN 'manager' THEN 2 ELSE 3 END")


# ---------------------------------------------------------------- Brand Brain
@app.get("/api/brand")
def brand():
    facts = db.q("SELECT * FROM facts ORDER BY id")
    for f in facts:
        f["keywords"] = db.pj(f["keywords"], [])
        f["outdated_values"] = db.pj(f["outdated_values"], [])
    terms = db.q("SELECT * FROM terms")
    for t in terms:
        t["disallowed"] = db.pj(t["disallowed"], [])
    assets = db.q("SELECT * FROM assets ORDER BY id")
    for a in assets:
        a["meta"] = db.pj(a["meta"], {})
        a["url"] = f"/api/files/asset/{a['id']}"
    docs = db.q("SELECT id, name, uploaded_at, length(text) AS chars FROM documents")
    return {"guidelines": db.q("SELECT * FROM guidelines ORDER BY category, id"), "terms": terms,
            "prohibited": db.q("SELECT * FROM prohibited"), "facts": facts, "claims": db.q("SELECT * FROM claims ORDER BY id"),
            "colors": db.q("SELECT * FROM colors"), "assets": assets, "documents": docs,
            "history": db.q("SELECT * FROM guideline_history ORDER BY id DESC LIMIT 30"),
            "chunk_count": len(rag.build_chunks())}


@app.get("/api/brand/search")
def brand_search(q: str):
    return rag.retrieve(q, k=8)


def _upsert(table: str, key: str, data: dict, fields: list[str]):
    vals = [data.get(f) for f in fields]
    if data.get(key) and db.one(f"SELECT {key} FROM {table} WHERE {key}=?", (data[key],)):
        sets = ", ".join(f"{f}=?" for f in fields)
        db.ex(f"UPDATE {table} SET {sets} WHERE {key}=?", (*vals, data[key]))
        return data[key]
    cols = fields + ([key] if data.get(key) else [])
    args = vals + ([data[key]] if data.get(key) else [])
    return db.ex(f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(args))


@app.post("/api/brand/guidelines")
def save_guideline(data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "brand")
    if not data.get("title") or not data.get("body"):
        raise HTTPException(400, "Title and guideline text are required")
    if not data.get("id"):
        cat = (data.get("category") or "general").upper()[:5]
        n = len(db.q("SELECT id FROM guidelines WHERE category=?", (data.get("category"),))) + 1
        data["id"] = f"G-{cat}-{n:02d}"
        while db.one("SELECT id FROM guidelines WHERE id=?", (data["id"],)):
            n += 1
            data["id"] = f"G-{cat}-{n:02d}"
        db.ex("INSERT INTO guidelines(id, category, title, body, version, source, updated_at) VALUES (?,?,?,?,1,?,?)",
              (data["id"], data.get("category") or "general", data["title"], data["body"], "Added in Brand Brain", db.now()))
    else:
        old = db.one("SELECT * FROM guidelines WHERE id=?", (data["id"],))
        if not old:
            raise HTTPException(404, "Guideline not found")
        if old["body"] != data["body"]:
            db.ex("INSERT INTO guideline_history(guideline_id, old_body, new_body, changed_by, reason, at) VALUES (?,?,?,?,?,?)",
                  (old["id"], old["body"], data["body"], u["id"], data.get("reason") or "Edited in Brand Brain", db.now()))
        db.ex("UPDATE guidelines SET title=?, body=?, category=?, version=version+?, updated_at=? WHERE id=?",
              (data["title"], data["body"], data.get("category") or old["category"], 1 if old["body"] != data["body"] else 0, db.now(), old["id"]))
    return {"id": data["id"]}


@app.post("/api/brand/{kind}")
def save_brand_item(kind: str, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "brand")
    if kind == "terms":
        if not data.get("preferred") or not data.get("disallowed"):
            raise HTTPException(400, "Preferred term and at least one disallowed variant are required")
        dis = data["disallowed"] if isinstance(data["disallowed"], list) else [s.strip() for s in str(data["disallowed"]).split(",") if s.strip()]
        return {"id": _upsert("terms", "id", {**data, "disallowed": db.j(dis), "guideline_id": data.get("guideline_id") or "G-TERM-01"},
                               ["preferred", "disallowed", "note", "guideline_id"])}
    if kind == "prohibited":
        if not data.get("phrase"):
            raise HTTPException(400, "Phrase is required")
        return {"id": _upsert("prohibited", "id", {"severity": "medium", "category": "tone", **data},
                               ["phrase", "reason", "replacement", "severity", "category", "guideline_id"])}
    if kind == "facts":
        if not data.get("label") or not data.get("statement"):
            raise HTTPException(400, "Label and statement are required")
        if not data.get("id"):
            data["id"] = "F-" + "".join(ch for ch in data["label"].upper() if ch.isalnum())[:12]
        kw = data.get("keywords") or []
        kw = kw if isinstance(kw, list) else [s.strip() for s in str(kw).split(",") if s.strip()]
        od = data.get("outdated_values") or []
        od = od if isinstance(od, list) else [float(s) for s in str(od).split(",") if s.strip()]
        value = float(data["value"]) if data.get("value") not in (None, "") else None
        return {"id": _upsert("facts", "id", {**data, "value": value, "keywords": db.j(kw), "outdated_values": db.j(od), "verified_on": data.get("verified_on") or db.now()[:10]},
                               ["label", "value", "unit", "statement", "keywords", "outdated_values", "source", "verified_on"])}
    if kind == "claims":
        if not data.get("text") or not data.get("evidence"):
            raise HTTPException(400, "An approved claim needs its text and evidence")
        if not data.get("id"):
            data["id"] = f"C-{len(db.q('SELECT id FROM claims')) + 1:02d}"
            while db.one("SELECT id FROM claims WHERE id=?", (data["id"],)):
                data["id"] += "b"
        return {"id": _upsert("claims", "id", {**data, "approved_by": u["name"]}, ["text", "evidence", "approved_by"])}
    if kind == "colors":
        h = (data.get("hex") or "").strip().upper()
        if len(h) != 7 or not h.startswith("#"):
            raise HTTPException(400, "Colour must be a hex value like #3B2FC9")
        return {"id": _upsert("colors", "id", {**data, "hex": h}, ["name", "hex", "usage"])}
    if kind == "assets":
        up = save_upload(data["name"], data["mime"], data["data"], "brand-asset")
        if not up["mime"].startswith("image/"):
            raise HTTPException(400, "Brand assets must be images")
        row = db.one("SELECT * FROM uploads WHERE id=?", (up["id"],))
        aid = db.ex("INSERT INTO assets(kind, name, path, mime, meta, created_at) VALUES (?,?,?,?,?,?)",
                    (data.get("kind") or "logo", data.get("label") or data["name"], row["path"], row["mime"], row["meta"], db.now()))
        return {"id": aid}
    if kind == "documents":
        up = save_upload(data["name"], data["mime"], data["data"], "guideline-doc")
        row = db.one("SELECT * FROM uploads WHERE id=?", (up["id"],))
        if not (row["text"] or "").strip():
            raise HTTPException(400, "No text could be extracted from this document")
        did = db.ex("INSERT INTO documents(name, path, text, uploaded_at) VALUES (?,?,?,?)", (data["name"], row["path"], row["text"], db.now()))
        return {"id": did, "chars": len(row["text"])}
    raise HTTPException(404, "Unknown Brand Brain section")


@app.delete("/api/brand/{kind}/{item_id}")
def delete_brand_item(kind: str, item_id: str, x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    table = {"terms": "terms", "prohibited": "prohibited", "facts": "facts", "claims": "claims", "colors": "colors",
             "assets": "assets", "documents": "documents", "guidelines": "guidelines"}.get(kind)
    if not table:
        raise HTTPException(404, "Unknown section")
    db.ex(f"DELETE FROM {table} WHERE id=?", (item_id,))
    return {"ok": True}


# ---------------------------------------------------------------- files
@app.get("/api/files/upload/{uid}")
def file_upload(uid: int):
    u = db.one("SELECT path, mime FROM uploads WHERE id=?", (uid,))
    p = storage.local(u["path"]) if u else None
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type=u["mime"])


@app.get("/api/files/asset/{aid}")
def file_asset(aid: int):
    a = db.one("SELECT path, mime FROM assets WHERE id=?", (aid,))
    p = storage.local(a["path"]) if a else None
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type=a["mime"])


@app.post("/api/uploads")
def upload(data: dict = Body(...), x_user_id: str | None = Header(None)):
    need(user(x_user_id), "create")
    return save_upload(data["name"], data["mime"], data["data"], data.get("kind") or "attachment")


# ---------------------------------------------------------------- content
def _content_summary(c: dict) -> dict:
    a = db.one("SELECT id, score, mode, findings, created_at FROM analyses WHERE content_id=? AND version_number=? ORDER BY id DESC LIMIT 1",
               (c["id"], c["current_version"]))
    owner = db.one("SELECT name FROM users WHERE id=?", (c["owner_id"],))
    fs = db.pj(a["findings"], []) if a else []
    return {**c, "status_label": STATUS_LABEL.get(c["status"], c["status"]), "owner": owner["name"] if owner else None,
            "score": a["score"] if a else None, "mode": a["mode"] if a else None, "analysis_id": a["id"] if a else None,
            "issues": len(fs), "critical": sum(1 for f in fs if f["severity"] in ("critical", "high"))}


@app.get("/api/content")
def list_content():
    return [_content_summary(c) for c in db.q("SELECT * FROM content ORDER BY updated_at DESC")]


@app.post("/api/content")
def create_content(data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "create")
    if not (data.get("title") or "").strip():
        raise HTTPException(400, "Title is required")
    atts = _attachments(data.get("attachments") or [])
    if not (data.get("body") or "").strip() and not atts:
        raise HTTPException(400, "Add some text or upload a file to review")
    cid = db.ex("INSERT INTO content(title, channel, status, owner_id, confidential, current_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (data["title"].strip(), data.get("channel") or "Social", "draft", u["id"], 1 if data.get("confidential") else 0, 1, db.now(), db.now()))
    db.ex("INSERT INTO versions(content_id, number, body, alt_text, attachments, created_by, created_at, note) VALUES (?,?,?,?,?,?,?,?)",
          (cid, 1, data.get("body") or "", data.get("alt_text") or "", db.j(atts), u["id"], db.now(), "Created"))
    event(cid, u["id"], "created", None, "draft")
    return {"id": cid}


def _attachments(ids: list) -> list[dict]:
    out = []
    for i in ids:
        up = db.one("SELECT * FROM uploads WHERE id=?", (int(i),))
        if not up:
            raise HTTPException(400, f"Upload {i} not found")
        out.append({"id": up["id"], "kind": up["kind"], "name": up["name"], "mime": up["mime"]})
    return out


@app.get("/api/content/{cid}")
def get_content(cid: int):
    c = content_or_404(cid)
    versions = db.q("SELECT * FROM versions WHERE content_id=? ORDER BY number DESC", (cid,))
    for v in versions:
        v["attachments"] = [public_upload(u) for u in analysis._uploads([a["id"] for a in db.pj(v["attachments"], [])])]
    names = {u["id"]: u for u in db.q("SELECT * FROM users")}
    comments = db.q("SELECT * FROM comments WHERE content_id=? ORDER BY id", (cid,))
    events = db.q("SELECT * FROM events WHERE content_id=? ORDER BY id", (cid,))
    for r in comments + events:
        r["user"] = names.get(r["user_id"], {"name": r["user_id"], "role": "system"})
    analyses = db.q("SELECT id, version_number, score, mode, created_at FROM analyses WHERE content_id=? ORDER BY id DESC", (cid,))
    alerts = db.q("SELECT * FROM integrity_alerts WHERE content_id=? ORDER BY id DESC", (cid,))
    for al in alerts:
        al["diff"] = db.pj(al["diff"], {})
    return {**_content_summary(c), "versions": versions, "comments": comments, "events": events, "analyses": analyses,
            "alerts": alerts}


@app.put("/api/content/{cid}")
def edit_content(cid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "edit")
    c = content_or_404(cid)
    cur = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, c["current_version"]))
    atts = _attachments(data["attachments"]) if "attachments" in data else db.pj(cur["attachments"], [])
    n = c["current_version"] + 1
    db.ex("INSERT INTO versions(content_id, number, body, alt_text, attachments, created_by, created_at, note) VALUES (?,?,?,?,?,?,?,?)",
          (cid, n, data.get("body", cur["body"]), data.get("alt_text", cur["alt_text"]), db.j(atts), u["id"], db.now(), data.get("note") or "Edited"))
    db.ex("UPDATE content SET current_version=?, title=?, updated_at=? WHERE id=?", (n, data.get("title") or c["title"], db.now(), cid))
    event(cid, u["id"], "edited", c["status"], c["status"], f"Version {n}")
    if c["status"] == "approved":
        integrity.verify(cid)  # flags modified_after_approval
    elif c["status"] in ("pending_approval", "ai_review", "rejected"):
        set_status(db.one("SELECT * FROM content WHERE id=?", (cid,)), "draft", u["id"], "reopened", "Edited after review; must be reviewed again")
    return {"version": n}


@app.post("/api/content/{cid}/analyze")
def analyze(cid: int, x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "review")
    c = content_or_404(cid)
    res = analysis.run_for_content(cid, u["id"])
    if c["status"] in ("draft", "needs_revision", "modified_after_approval", "rejected", "ai_review"):
        set_status(c, "ai_review", u["id"], "ai_review", f"Score {res['score']} ({res['mode']})")
    return res


@app.get("/api/content/{cid}/report")
def report(cid: int, version: int | None = None):
    c = content_or_404(cid)
    vnum = version or c["current_version"]
    v = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, vnum))
    if not v:
        raise HTTPException(404, "Version not found")
    a = analysis.latest(cid, vnum)
    ups = analysis._uploads([x["id"] for x in db.pj(v["attachments"], [])])
    pdf_text = "\n\n".join(x.get("text") or "" for x in ups if x.get("mime") == "application/pdf")
    prev = None
    if vnum > 1:
        pa = analysis.latest(cid, vnum - 1)
        if pa:
            prev = {"version": vnum - 1, "score": pa["score"], "dimensions": pa["dimensions"]}
    return {"content": _content_summary(c), "version": {**v, "attachments": [public_upload(x) for x in ups]},
            "pdf_text": pdf_text, "analysis": a, "previous": prev}


@app.post("/api/analyses/{aid}/decisions")
def decide_finding(aid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "decide_fix")
    if data.get("decision") not in ("accepted", "rejected", None):
        raise HTTPException(400, "decision must be accepted, rejected or null")
    if data.get("decision") is None:
        db.ex("DELETE FROM decisions WHERE analysis_id=? AND finding_id=?", (aid, data["finding_id"]))
    else:
        db.ex("INSERT INTO decisions(analysis_id, finding_id, decision, user_id, note, at) VALUES (?,?,?,?,?,?) "
              "ON CONFLICT(analysis_id, finding_id) DO UPDATE SET decision=excluded.decision, user_id=excluded.user_id, note=excluded.note, at=excluded.at",
              (aid, data["finding_id"], data["decision"], u["id"], data.get("note"), db.now()))
    learning.train()  # every decision is a new training label (NumPy, a few milliseconds)
    a = db.one("SELECT content_id FROM analyses WHERE id=?", (aid,))
    return analysis.latest(a["content_id"])


def _tidy(s: str) -> str:
    """Small grammar clean-up after substitutions: a/an agreement, doubled spaces, space before punctuation."""
    s = re.sub(r"\b([Aa])n? (?=([A-Za-z]))", lambda m: (m.group(1) + ("n " if m.group(2).lower() in "aeiou" else " ")), s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" +([.,!?;:])", r"\1", s)
    return s


@app.post("/api/content/{cid}/apply-fixes")
def apply_fixes(cid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    """Apply ONLY the suggestions a human accepted, as a new version. Never overwrites the original."""
    u = user(x_user_id)
    need(u, "edit")
    c = content_or_404(cid)
    a = analysis.latest(cid, c["current_version"])
    if not a or a["id"] != data.get("analysis_id"):
        raise HTTPException(409, "Report is out of date — re-run the review first")
    v = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, c["current_version"]))
    overrides = data.get("overrides") or {}
    texts = {"body": v["body"] or "", "alt_text": v["alt_text"] or ""}
    applied, skipped = [], []
    edits = defaultdict(list)
    for f in a["findings"]:
        if f.get("decision") != "accepted":
            continue
        rep = overrides.get(f["id"], (f.get("suggestion") or {}).get("replacement"))
        if f["target"] == "alt_text" and f["start"] is None and overrides.get(f["id"]):
            texts["alt_text"] = overrides[f["id"]]
            applied.append(f["id"])
            continue
        if f["target"] not in texts or f["start"] is None or rep is None:
            skipped.append({"id": f["id"], "title": f["title"], "reason": "Needs a manual change (image or no exact text location)"})
            continue
        if texts[f["target"]][f["start"]:f["end"]] != f["quote"] and texts[f["target"]][f["start"]:f["end"]].lower() != f["quote"].lower():
            skipped.append({"id": f["id"], "title": f["title"], "reason": "Text moved since the review"})
            continue
        edits[f["target"]].append((f["start"], f["end"], rep, f["id"]))
    for tgt, lst in edits.items():
        lst.sort(key=lambda e: e[0], reverse=True)
        last_start = None
        s = texts[tgt]
        for start, end, rep, fid in lst:
            if last_start is not None and end > last_start:
                skipped.append({"id": fid, "reason": "Overlaps another accepted fix"})
                continue
            orig = s[start:end].lstrip(", ")
            before = s[:start].rstrip()
            at_sentence_start = not before or before[-1] in ".!?\n"
            if rep and orig[:1].isupper() and rep[:1].islower() and at_sentence_start:
                rep = rep[0].upper() + rep[1:]
            s = s[:start] + rep + s[end:]
            last_start = start
            applied.append(fid)
        texts[tgt] = _tidy(s)
    if not applied:
        raise HTTPException(400, "No accepted text fixes to apply" + (f" ({len(skipped)} need manual changes)" if skipped else ""))
    n = c["current_version"] + 1
    db.ex("INSERT INTO versions(content_id, number, body, alt_text, attachments, created_by, created_at, note) VALUES (?,?,?,?,?,?,?,?)",
          (cid, n, texts["body"], texts["alt_text"], v["attachments"], u["id"], db.now(), f"Applied {len(applied)} accepted fix(es)"))
    db.ex("UPDATE content SET current_version=?, updated_at=? WHERE id=?", (n, db.now(), cid))
    event(cid, u["id"], "fixes_applied", c["status"], c["status"], f"Version {n}: {len(applied)} fix(es) accepted by {u['name']}")
    res = analysis.run_for_content(cid, u["id"])
    return {"version": n, "applied": applied, "skipped": skipped, "before": {"score": a["score"], "dimensions": a["dimensions"]},
            "after": {"score": res["score"], "dimensions": res["dimensions"]}}


@app.post("/api/content/{cid}/submit")
def submit(cid: int, data: dict = Body(default={}), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "edit")
    c = content_or_404(cid)
    if not analysis.latest(cid, c["current_version"]):
        raise HTTPException(400, "Run the AI review on the latest version before submitting")
    if c["status"] not in ("ai_review", "needs_revision", "draft", "modified_after_approval"):
        raise HTTPException(400, f"Cannot submit from status '{STATUS_LABEL.get(c['status'])}'")
    set_status(c, "pending_approval", u["id"], "submitted", data.get("note") or "")
    return {"ok": True}


def _comment(cid: int, uid: str, body: str, finding_id: str | None = None) -> None:
    db.ex("INSERT INTO comments(content_id, user_id, body, finding_id, at) VALUES (?,?,?,?,?)", (cid, uid, body, finding_id, db.now()))


@app.post("/api/content/{cid}/comments")
def comment(cid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "comment")
    content_or_404(cid)
    if not (data.get("body") or "").strip():
        raise HTTPException(400, "Comment is empty")
    _comment(cid, u["id"], data["body"].strip(), data.get("finding_id"))
    return {"ok": True}


@app.post("/api/content/{cid}/request-revision")
def request_revision(cid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "request_revision")
    c = content_or_404(cid)
    if c["status"] not in ("pending_approval", "ai_review", "modified_after_approval"):
        raise HTTPException(400, "Only submitted content can be sent back")
    if not (data.get("note") or "").strip():
        raise HTTPException(400, "Say what needs to change")
    _comment(cid, u["id"], data["note"].strip())
    set_status(c, "needs_revision", u["id"], "revision_requested", data["note"].strip())
    return {"ok": True}


@app.post("/api/content/{cid}/endorse")
def endorse(cid: int, data: dict = Body(default={}), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "endorse")
    c = content_or_404(cid)
    if c["status"] != "pending_approval":
        raise HTTPException(400, "Only content pending approval can be endorsed")
    event(cid, u["id"], "endorsed", c["status"], c["status"], data.get("note") or "Manager review complete — recommended for approval")
    if data.get("note"):
        _comment(cid, u["id"], data["note"])
    return {"ok": True}


@app.post("/api/content/{cid}/approve")
def approve(cid: int, data: dict = Body(default={}), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "approve")
    c = content_or_404(cid)
    if c["status"] != "pending_approval":
        raise HTTPException(400, "Content must be submitted for approval first")
    a = analysis.latest(cid, c["current_version"])
    open_serious = [f for f in (a["findings"] if a else []) if f["severity"] in ("critical", "high") and f.get("decision") != "rejected"]
    if open_serious and not (data.get("override_reason") or "").strip():
        raise HTTPException(409, f"{len(open_serious)} critical/high finding(s) are still open. Fix them, mark them as false positives, "
                                 "or give an override reason — the decision is yours, but it is recorded.")
    v = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, c["current_version"]))
    h = integrity.version_hash(c, v)
    db.ex("UPDATE content SET approved_version=?, approved_hash=?, updated_at=? WHERE id=?", (v["number"], h, db.now(), cid))
    db.ex("UPDATE integrity_alerts SET resolved=1 WHERE content_id=?", (cid,))
    snap = {"title": c["title"], "body": v["body"], "alt_text": v["alt_text"], "version": v["number"], "hash": h,
            "override_reason": data.get("override_reason"), "note": data.get("note"), "score": a["score"] if a else None}
    set_status(c, "approved", u["id"], "approved", db.j(snap))
    return {"hash": h, "version": v["number"]}


@app.post("/api/content/{cid}/reject")
def reject(cid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "approve")
    c = content_or_404(cid)
    if c["status"] != "pending_approval":
        raise HTTPException(400, "Only content pending approval can be rejected")
    if not (data.get("note") or "").strip():
        raise HTTPException(400, "Give a reason for rejecting")
    _comment(cid, u["id"], data["note"].strip())
    set_status(c, "rejected", u["id"], "rejected", data["note"].strip())
    return {"ok": True}


@app.post("/api/content/{cid}/verify")
def verify(cid: int):
    content_or_404(cid)
    return integrity.verify(cid)


@app.post("/api/content/{cid}/simulate-tamper")
def simulate_tamper(cid: int, data: dict = Body(default={}), x_user_id: str | None = Header(None)):
    """DEMO ONLY: changes the stored approved text directly in the database, bypassing the app,
    to show that the Integrity Shield catches edits made outside the workflow."""
    need(user(x_user_id), "brand")
    c = content_or_404(cid)
    if c["status"] != "approved":
        raise HTTPException(400, "Simulate tampering on approved content")
    v = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, c["current_version"]))
    new = data.get("body") or (v["body"] or "") + " Now with a guaranteed 200 km range!"
    db.ex("UPDATE versions SET body=? WHERE id=?", (new, v["id"]))
    return {"ok": True, "note": "Database row changed directly. Run verification to detect it."}


@app.get("/api/integrity")
def integrity_overview():
    results = integrity.verify_all()
    alerts = db.q("SELECT ia.*, c.title FROM integrity_alerts ia JOIN content c ON c.id=ia.content_id ORDER BY ia.id DESC LIMIT 50")
    for al in alerts:
        al["diff"] = db.pj(al["diff"], {})
    protected = db.q("SELECT id, title, approved_version, approved_hash, status, updated_at FROM content WHERE approved_hash IS NOT NULL")
    return {"results": results, "alerts": alerts, "protected": protected}


# ---------------------------------------------------------------- Brand DNA Simulator
@app.post("/api/dna")
def dna(data: dict = Body(...), x_user_id: str | None = Header(None)):
    user(x_user_id)
    o, m = data.get("original") or {}, data.get("modified") or {}
    ups = analysis._uploads([int(i) for i in data.get("attachments") or []])
    allow_ai = bool(data.get("use_ai")) and not data.get("confidential")
    ra = analysis.evaluate(o.get("body", ""), o.get("alt_text", ""), ups, allow_ai)
    rb = analysis.evaluate(m.get("body", ""), m.get("alt_text", ""), ups, allow_ai)
    return _dna_compare(ra, rb, o.get("body", ""), m.get("body", ""))


def _dna_compare(ra: dict, rb: dict, ta: str, tb: str) -> dict:
    def key(f):
        return (f["category"], f["title"], (f.get("quote") or "").lower())
    ka, kb = Counter(key(f) for f in ra["findings"]), Counter(key(f) for f in rb["findings"])
    introduced = [f for f in rb["findings"] if kb[key(f)] > ka.get(key(f), 0)]
    resolved = [f for f in ra["findings"] if ka[key(f)] > kb.get(key(f), 0)]
    dims = {k: {"original": ra["dimensions"][k], "modified": rb["dimensions"][k], "delta": round(rb["dimensions"][k] - ra["dimensions"][k], 1)}
            for k in ra["dimensions"]}
    return {"original": {"score": ra["score"], "dimensions": ra["dimensions"], "findings": ra["findings"], "mode": ra["mode"], "note": ra.get("note") or ra.get("engine_note")},
            "modified": {"score": rb["score"], "dimensions": rb["dimensions"], "findings": rb["findings"], "mode": rb["mode"], "note": rb.get("note") or rb.get("engine_note")},
            "delta": round(rb["score"] - ra["score"], 1), "dimensions": dims, "introduced": introduced, "resolved": resolved,
            "diff": integrity.text_diff(ta, tb)}


@app.get("/api/content/{cid}/dna")
def content_dna(cid: int, a: int, b: int):
    va = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, a))
    vb = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (cid, b))
    aa, ab = analysis.latest(cid, a), analysis.latest(cid, b)
    if not (va and vb and aa and ab):
        raise HTTPException(404, "Both versions need a review first")
    return _dna_compare(aa, ab, va["body"] or "", vb["body"] or "")


# ---------------------------------------------------------------- Brand Intelligence + analytics
@app.get("/api/insights")
def insights():
    return gaps.refresh()


@app.post("/api/insights/{iid}/propose")
def insight_propose(iid: int, x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    if not db.one("SELECT id FROM gap_insights WHERE id=?", (iid,)):
        raise HTTPException(404)
    return gaps.propose(iid)


@app.post("/api/insights/{iid}/decide")
def insight_decide(iid: int, data: dict = Body(...), x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "brand")
    if data.get("decision") not in ("approved", "dismissed"):
        raise HTTPException(400, "decision must be approved or dismissed")
    try:
        gaps.decide(iid, data["decision"], u["id"], data.get("text"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------------------------------------------------------------- user-testing feedback
FEEDBACK_TASKS = ["Submit content for review", "Understand a finding", "Fix issues", "Approve content", "Set up the Brand Brain", "Other"]


@app.post("/api/feedback")
def feedback_add(data: dict = Body(...), x_user_id: str | None = Header(None)):
    """Structured feedback from user tests: what the tester tried, a 1-5 rating, whether they managed it."""
    u = user(x_user_id)
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Pick a rating from 1 to 5")
    if not 1 <= rating <= 5:
        raise HTTPException(400, "Pick a rating from 1 to 5")
    task = data.get("task") if data.get("task") in FEEDBACK_TASKS else "Other"
    completed = data.get("completed") if data.get("completed") in ("yes", "partly", "no") else None
    fid = db.ex("INSERT INTO feedback(user_id, user_name, role, tester, page, task, rating, completed, comment, device, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (u["id"], u["name"], u["role"], (data.get("tester") or "").strip()[:80] or None, (data.get("page") or "")[:120],
                 task, rating, completed, (data.get("comment") or "").strip()[:2000], (data.get("device") or "")[:20], db.now()))
    return {"id": fid}


def _feedback_rows() -> list[dict]:
    return db.q("SELECT * FROM feedback ORDER BY id DESC")


@app.get("/api/feedback")
def feedback_list(x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    rows = _feedback_rows()
    n = len(rows)
    by_task = {}
    for r in rows:
        t = by_task.setdefault(r["task"], {"task": r["task"], "count": 0, "sum": 0, "done": 0})
        t["count"] += 1
        t["sum"] += r["rating"]
        t["done"] += r["completed"] == "yes"
    return {"tasks": FEEDBACK_TASKS, "rows": rows,
            "summary": {"count": n, "avg_rating": round(sum(r["rating"] for r in rows) / n, 2) if n else None,
                        "completed_share": round(sum(r["completed"] == "yes" for r in rows) / n * 100) if n else None,
                        "testers": len({r["tester"] or r["user_id"] for r in rows}),
                        "by_task": [{"task": t["task"], "count": t["count"], "avg": round(t["sum"] / t["count"], 2),
                                     "completed_share": round(t["done"] / t["count"] * 100)} for t in by_task.values()]}}


@app.get("/api/feedback.csv")
def feedback_csv(x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "created_at", "tester", "user_name", "role", "task", "rating", "completed", "comment", "page", "device"]
    w.writerow(cols)
    for r in reversed(_feedback_rows()):
        w.writerow([r.get(c) if r.get(c) is not None else "" for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inkloom-user-feedback.csv"})


@app.get("/api/audit.csv")
def audit_csv(x_user_id: str | None = Header(None)):
    """Full audit trail: who did what to which content, including approvals, overrides and integrity alerts."""
    u = user(x_user_id)
    if u["role"] not in ("admin", "approver", "manager"):
        raise HTTPException(403, "Only admins, managers and approvers can export the audit log")
    import csv
    users = {r["id"]: r for r in db.q("SELECT id, name, role FROM users")}
    titles = {r["id"]: r["title"] for r in db.q("SELECT id, title FROM content")}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["at", "content_id", "content", "user", "role", "action", "from_status", "to_status", "version", "sha256", "override_reason", "note"])
    for e in db.q("SELECT * FROM events ORDER BY at, id"):
        who = users.get(e["user_id"]) or {"name": e["user_id"], "role": ""}
        note, version, sha, override = e["note"] or "", "", "", ""
        snap = db.pj(note) if e["action"] == "approved" else None
        if isinstance(snap, dict):
            version, sha, override, note = snap.get("version", ""), snap.get("hash", ""), snap.get("override_reason") or "", snap.get("note") or ""
        w.writerow([e["at"], e["content_id"], titles.get(e["content_id"], ""), who["name"], who["role"], e["action"],
                    e["from_status"] or "", e["to_status"] or "", version, sha, override, note])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inkloom-audit-log.csv"})


@app.get("/api/feedback/tasks")
def feedback_tasks():
    return FEEDBACK_TASKS


@app.get("/api/learning")
def learning_summary():
    return learning.summary()


@app.post("/api/learning/train")
def learning_train(x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    learning.train()
    return learning.summary()


@app.post("/api/learning/mode")
def learning_mode(data: dict = Body(...), x_user_id: str | None = Header(None)):
    need(user(x_user_id), "brand")
    try:
        learning.set_mode(data.get("mode"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return learning.summary()


@app.get("/api/analytics")
def analytics():
    contents = db.q("SELECT * FROM content")
    latest = {}
    for c in contents:
        a = analysis.latest(c["id"], c["current_version"])
        if a:
            latest[c["id"]] = a
    open_findings = [(cid, f) for cid, a in latest.items() for f in a["findings"] if f.get("decision") != "rejected"]
    by_guideline, by_cat, by_channel = Counter(), Counter(), defaultdict(Counter)
    chan = {c["id"]: c["channel"] or "Other" for c in contents}
    for cid, f in open_findings:
        for s in f.get("source_ids", []):
            if s.startswith("G-"):
                by_guideline[s] += 1
                break
        by_cat[f["category"]] += 1
        by_channel[chan[cid]][f["category"]] += 1
    gl = {g["id"]: g["title"] for g in db.q("SELECT id, title FROM guidelines")}
    high_risk = [{"id": cid, "title": next(c["title"] for c in contents if c["id"] == cid), "score": a["score"],
                  "critical": sum(1 for f in a["findings"] if f["severity"] == "critical" and f.get("decision") != "rejected")}
                 for cid, a in latest.items() if a["score"] < 60 or any(f["severity"] == "critical" and f.get("decision") != "rejected" for f in a["findings"])]
    trend = db.q("SELECT substr(created_at,1,10) AS day, ROUND(CAST(AVG(score) AS NUMERIC), 1) AS avg, COUNT(*) AS n FROM analyses GROUP BY day ORDER BY day")
    status_counts = Counter(c["status"] for c in contents)
    return {
        "overall_score": round(sum(a["score"] for a in latest.values()) / len(latest), 1) if latest else None,
        "submissions": len(contents), "reviewed": len(latest), "violations": len(open_findings),
        "pending_approvals": status_counts.get("pending_approval", 0),
        "status_counts": {STATUS_LABEL.get(k, k): v for k, v in status_counts.items()},
        "high_risk": sorted(high_risk, key=lambda x: x["score"])[:8],
        "top_guidelines": [{"id": k, "title": gl.get(k, k), "count": v} for k, v in by_guideline.most_common(8)],
        "by_category": dict(by_cat), "by_channel": {k: dict(v) for k, v in by_channel.items()},
        "trend": trend, "alerts": db.one("SELECT COUNT(*) AS n FROM integrity_alerts WHERE resolved=0")["n"],
        "recommendations": [i for i in gaps.list_insights() if i["status"] == "open"][:5],
        "ai_share": round(sum(1 for a in latest.values() if a["mode"] == "ai+rules") / len(latest) * 100) if latest else 0,
    }


@app.post("/api/admin/reset-demo")
def reset_demo(request: Request, x_user_id: str | None = Header(None)):
    u = user(x_user_id)
    need(u, "brand")
    from . import seed
    db.reset_all()
    seed.seed()
    # Sessions were wiped with the data; keep the admin who pressed the button signed in.
    return _login_response(request, db.one("SELECT * FROM users WHERE id=?", (u["id"],)))


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse(status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {exc}"})


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
