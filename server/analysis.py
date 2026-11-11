"""Runs a full review: rules + retrieval + (optionally) Claude, then scores."""
from . import ai, config, db, rag, rules, scoring

CATS = {"tone", "terminology", "claims", "facts", "visual", "accessibility"}
SEVS = {"critical", "high", "medium", "low"}


def _uploads(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return db.q(f"SELECT * FROM uploads WHERE id IN ({marks})", tuple(ids))


def _locate(text: str, quote: str) -> tuple[int | None, int | None]:
    if not quote or not text:
        return None, None
    i = text.find(quote)
    if i < 0:
        i = text.lower().find(quote.lower())
    return (i, i + len(quote)) if i >= 0 else (None, None)


def _merge_ai(result: dict, texts: dict, rule_findings: list[dict], lookup: dict, images: list[dict]) -> list[dict]:
    out = []
    raw = result.get("findings") if isinstance(result, dict) else None
    for n, f in enumerate(raw if isinstance(raw, list) else [], 1):
        # Providers without strict schemas can return loose JSON: normalise or skip.
        if not isinstance(f, dict) or f.get("category") not in CATS or f.get("severity") not in SEVS:
            continue
        f.setdefault("title", "Brand issue")
        f.setdefault("explanation", "")
        f["source_ids"] = [s for s in f.get("source_ids") or [] if isinstance(s, str)]
        try:
            f["confidence"] = float(f.get("confidence") or 0.6)
        except (TypeError, ValueError):
            f["confidence"] = 0.6
        if f.get("target") not in ("body", "alt_text", "pdf", "image"):
            f["target"] = "body"
        target = f.get("target", "body")
        if target == "image":
            target = f"image:{images[0]['id']}" if images else "body"
            start = end = None
        else:
            start, end = _locate(texts.get(target, ""), f.get("quote", ""))
        valid = [s for s in f.get("source_ids", []) if s in lookup]
        conf = max(0.0, min(1.0, float(f.get("confidence") or 0.6)))
        if not valid:
            conf = round(conf * 0.6, 2)
        if start is not None and any(r["target"] == target and r["start"] is not None and r["start"] < end and start < r["end"] and r["category"] == f["category"] for r in rule_findings):
            continue  # rule engine already covers this span
        rep = (f.get("replacement") or "").strip()
        out.append({
            "id": f"A{n}", "engine": "ai", "category": f["category"], "severity": f["severity"], "title": f["title"],
            "quote": f.get("quote", ""), "start": start, "end": end, "target": target,
            "explanation": f["explanation"], "source_ids": valid, "grounded": bool(valid),
            "suggestion": {"replacement": rep, "rationale": f.get("rationale", "")} if rep and start is not None else
                          ({"replacement": None, "rationale": f.get("rationale", "")} if f.get("rationale") else None),
            "confidence": conf, "signature": f"ai:{f['category']}:{f['title'].lower()[:40]}",
        })
    return out


def evaluate(body: str, alt_text: str, uploads: list[dict], allow_ai: bool = True) -> dict:
    """Pure evaluation (no storage). Used by reviews and the Brand DNA Simulator."""
    rule_findings = rules.run(body, alt_text, uploads)
    for f in rule_findings:
        f["grounded"] = True
    pdf_text = "\n\n".join(u.get("text") or "" for u in uploads if u.get("mime") == "application/pdf")
    query = " ".join([body or "", alt_text or "", pdf_text[:4000]])
    sources = rag.retrieve(query, k=10)
    lookup = rag.source_lookup()
    findings = list(rule_findings)
    mode, note, err = "rules", "Rule engine only: AI review is not configured.", None
    if not allow_ai:
        note = "Rule engine only: content is marked confidential, so it was not sent to the AI service."
    elif config.ai_configured():
        images = [u for u in uploads if (u.get("mime") or "").startswith("image/")]
        logos = db.q("SELECT * FROM assets WHERE kind='logo'")
        try:
            res = ai.review(body, alt_text, pdf_text, images, logos, sources, rule_findings)
            texts = {"body": body or "", "alt_text": alt_text or "", "pdf": pdf_text}
            findings += _merge_ai(res, texts, rule_findings, lookup, images)
            mode, note = "ai+rules", f"{config.provider_label()} · {config.model()}: " + str(res.get("summary", ""))
        except ai.AIUnavailable as e:
            err = str(e)
            note = f"AI review unavailable ({err}). Showing the rule-engine report; every finding below is still real."
    for f in findings:
        f["sources"] = [{"id": s, "title": lookup[s]["title"], "text": lookup[s]["text"], "type": lookup[s]["type"]}
                        for s in f.get("source_ids", []) if s in lookup]
    sc = scoring.score(findings)
    return {"mode": mode, "note": note, "ai_error": err, "findings": findings, "score": sc["overall"],
            "dimensions": sc["dimensions"], "retrieved": [{k: s[k] for k in ("id", "title", "type", "score")} for s in sources],
            "pdf_text": pdf_text}


def run_for_content(content_id: int, user_id: str | None = None) -> dict:
    c = db.one("SELECT * FROM content WHERE id=?", (content_id,))
    v = db.one("SELECT * FROM versions WHERE content_id=? AND number=?", (content_id, c["current_version"]))
    att = [a["id"] for a in db.pj(v["attachments"], [])]
    result = evaluate(v["body"] or "", v["alt_text"] or "", _uploads(att), allow_ai=not c["confidential"])
    aid = db.ex("INSERT INTO analyses(content_id, version_number, mode, engine_note, score, dimensions, findings, retrieved, ai_error, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (content_id, v["number"], result["mode"], result["note"], result["score"], db.j(result["dimensions"]),
                 db.j(result["findings"]), db.j(result["retrieved"]), result["ai_error"], db.now()))
    return {"analysis_id": aid, **result}


def latest(content_id: int, version: int | None = None) -> dict | None:
    if version is None:
        a = db.one("SELECT * FROM analyses WHERE content_id=? ORDER BY id DESC LIMIT 1", (content_id,))
    else:
        a = db.one("SELECT * FROM analyses WHERE content_id=? AND version_number=? ORDER BY id DESC LIMIT 1", (content_id, version))
    if not a:
        return None
    a["dimensions"] = db.pj(a["dimensions"], {})
    a["findings"] = db.pj(a["findings"], [])
    a["retrieved"] = db.pj(a["retrieved"], [])
    dec = {d["finding_id"]: d for d in db.q("SELECT * FROM decisions WHERE analysis_id=?", (a["id"],))}
    for f in a["findings"]:
        f["decision"] = dec.get(f["id"], {}).get("decision")
        f["decision_note"] = dec.get(f["id"], {}).get("note")
    rejected = {fid for fid, d in dec.items() if d["decision"] == "rejected"}
    adj = scoring.score(a["findings"], ignore_ids=rejected)
    a["score_after_review"] = adj["overall"]
    return a
