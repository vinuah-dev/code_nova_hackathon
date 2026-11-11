"""Guideline Gap Intelligence: repeated mistakes => the guideline is probably unclear."""
from collections import defaultdict

from . import ai, config, db

MIN_SUBMISSIONS = 3


def _latest_findings() -> list[tuple[dict, dict]]:
    rows = db.q("""SELECT a.* , c.title AS content_title, c.channel FROM analyses a JOIN content c ON c.id=a.content_id
                   WHERE a.id IN (SELECT MAX(id) FROM analyses GROUP BY content_id, version_number)""")
    out = []
    for a in rows:
        for f in db.pj(a["findings"], []):
            out.append((a, f))
    return out


def _guideline_for(f: dict) -> str | None:
    for s in f.get("source_ids", []):
        if s.startswith("G-"):
            return s
    return None


def _fallback_text(sig: str, g: dict, examples: list[str]) -> str:
    kind = sig.split(":")[0]
    ex = ", ".join(f"'{e}'" for e in sorted(set(examples))[:4])
    extra = {
        "term": f"Clarification: the following forms are NOT approved and keep appearing in drafts: {ex}. Always copy the product name exactly as written in the Terminology list, including spacing and capitalisation.",
        "prohibited": f"Clarification: {ex} is on the prohibited list. When you want to express this idea, use the approved alternative shown in the Brand Brain.",
        "claim": f"Clarification: words such as {ex} are comparative or absolute claims. Only use them when the exact claim, with evidence, is in the Approved Claims register. Otherwise describe the specific, verified benefit instead.",
        "fact": f"Clarification: outdated or incorrect figures ({ex}) keep appearing. Always copy numbers from the current Fact Sheet; earlier figures are withdrawn.",
        "visual": f"Clarification: colours close to, but not exactly, the approved palette ({ex}) keep appearing. Use the exact hex values; tints are not allowed unless listed.",
        "logo": "Clarification: always place the logo from the official file, scaled proportionally (hold Shift), never recoloured or redrawn.",
        "a11y": "Clarification: every image needs alt text of at least one full sentence describing what is shown and why it matters; contrast must meet WCAG AA.",
        "tone": "Clarification: no more than one exclamation mark per piece and no words in capitals (except listed acronyms). Confidence comes from specifics, not volume.",
    }.get(kind, "Clarification: add a concrete do/don't example for this rule.")
    return g["body"].rstrip() + "\n\n" + extra


def refresh() -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {"contents": set(), "examples": [], "guideline": None, "category": None, "title": None})
    for a, f in _latest_findings():
        if f.get("engine") == "ai":
            continue  # AI signatures are free text; only group deterministic signatures
        sig = f.get("signature")
        if not sig:
            continue
        gkey = sig.split(":")[0] + ":" + sig.split(":")[1] if sig.startswith(("fact:", "visual:")) else sig
        grp = groups[gkey]
        grp["contents"].add(a["content_id"])
        grp["examples"].append(f.get("quote") or "")
        grp["guideline"] = grp["guideline"] or _guideline_for(f)
        grp["category"] = f["category"]
        grp["title"] = f["title"]
    insights = []
    for sig, grp in groups.items():
        n = len(grp["contents"])
        if n < MIN_SUBMISSIONS or not grp["guideline"]:
            continue
        g = db.one("SELECT * FROM guidelines WHERE id=?", (grp["guideline"],))
        if not g:
            continue
        uniq = sorted({e for e in grp["examples"] if e})
        title = f"{n} submissions: {grp['title'].lower()}"
        desc = (f"{n} different submissions triggered the same issue ({grp['title'].lower()}; e.g. {', '.join(repr(u) for u in uniq[:3])}). "
                f"Guideline {g['id']} ('{g['title']}') may not explain this clearly enough.")
        existing = db.one("SELECT * FROM gap_insights WHERE signature=?", (sig,))
        if existing:
            db.ex("UPDATE gap_insights SET count=?, examples=?, title=?, description=? WHERE id=?",
                  (n, db.j(uniq[:10]), title, desc, existing["id"]))
        else:
            db.ex("INSERT INTO gap_insights(signature, guideline_id, title, description, count, examples, suggestion, status, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", (sig, g["id"], title, desc, n, db.j(uniq[:10]), None, "open", db.now()))
    return list_insights()


def list_insights() -> list[dict]:
    rows = db.q("SELECT gi.*, g.title AS guideline_title, g.body AS guideline_body FROM gap_insights gi LEFT JOIN guidelines g ON g.id=gi.guideline_id ORDER BY gi.status='open' DESC, gi.count DESC")
    for r in rows:
        r["examples"] = db.pj(r["examples"], [])
        r["suggestion"] = db.pj(r["suggestion"], None)
    return rows


def propose(insight_id: int) -> dict:
    gi = db.one("SELECT * FROM gap_insights WHERE id=?", (insight_id,))
    g = db.one("SELECT * FROM guidelines WHERE id=?", (gi["guideline_id"],))
    examples = db.pj(gi["examples"], [])
    sug = None
    if config.ai_configured():
        try:
            r = ai.propose_guideline(g, gi["description"], examples)
            sug = {"text": r["proposed_text"], "why": r["why"], "engine": "ai"}
        except ai.AIUnavailable as e:
            sug = {"text": _fallback_text(gi["signature"], g, examples), "why": f"Template proposal (AI unavailable: {e}).", "engine": "template"}
    else:
        sug = {"text": _fallback_text(gi["signature"], g, examples), "why": "Template proposal built from the repeated examples (AI not configured).", "engine": "template"}
    db.ex("UPDATE gap_insights SET suggestion=? WHERE id=?", (db.j(sug), insight_id))
    return sug


def decide(insight_id: int, decision: str, user_id: str, text: str | None) -> None:
    gi = db.one("SELECT * FROM gap_insights WHERE id=?", (insight_id,))
    if decision == "approved":
        g = db.one("SELECT * FROM guidelines WHERE id=?", (gi["guideline_id"],))
        new_body = (text or (db.pj(gi["suggestion"], {}) or {}).get("text") or "").strip()
        if not new_body:
            raise ValueError("No proposed text to apply")
        db.ex("INSERT INTO guideline_history(guideline_id, old_body, new_body, changed_by, reason, at) VALUES (?,?,?,?,?,?)",
              (g["id"], g["body"], new_body, user_id, f"Gap insight #{insight_id}: {gi['title']}", db.now()))
        db.ex("UPDATE guidelines SET body=?, version=version+1, updated_at=? WHERE id=?", (new_body, db.now(), g["id"]))
    db.ex("UPDATE gap_insights SET status=?, decided_by=?, decided_at=? WHERE id=?", (decision, user_id, db.now(), insight_id))
