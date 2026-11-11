"""Deterministic rule engine.

These checks run on every analysis, with or without the AI. Each finding points
at exact text offsets (or an image) and at the Brand Brain source it came from,
so the report is explainable and reproducible.
"""
import re
from datetime import date

from . import db, storage, visual

ALLOWED_CAPS = {"EV", "IP67", "ARAI", "IDC", "BIS", "USB", "LED", "GPS", "KM", "T&C", "FAQ", "AI", "OTA", "ABS", "CBS", "EMI", "GST", "INR"}

UNIT_ALIASES = {
    "km": r"(?:km|kms|kilometres|kilometers)(?![/a-z])",
    "min": r"(?:min|mins|minutes)\b",
    "years": r"(?:years?|yrs?)\b",
    "km/h": r"(?:km/h|kmph|kph)\b",
    "%": r"%",
    "hours": r"(?:hours?|hrs?)\b",
    "kg": r"(?:kg|kgs|kilograms?)\b",
}

# Claim triggers: superlatives, absolutes and guarantees.
CLAIM_TRIGGERS = [
    (r",?\s*\bbest[- ]in[- ]class\b", "high", ""),
    (r"\b(?:the |India's |the world's )?best\b", "high", "a great"),
    (r"\b(?:the |India's |the world's )?fastest\b", "high", "a quick"),
    (r"\b(?:the |India's )?cheapest\b", "high", "an affordable"),
    (r"\b(?:the |India's )?longest\b", "high", "a long"),
    (r"\b(?:#\s?1|number one|no\.\s?1)\b", "high", "a popular"),
    (r",?\s*\bguarantee(?:d|s)?\b", "critical", ""),
    (r"\b100\s?%", "critical", None),
    (r"\b(?:zero|no) maintenance\b", "critical", "low maintenance"),
    (r"\bnever (?:breaks?|fails?|needs?)\b", "high", None),
    (r"\b(?:unbeatable|unmatched|unrivalled|unrivaled)\b", "high", "standout"),
    (r"\blifetime (?:warranty|battery|guarantee)\b", "critical", None),
    (r"\b(?:India|world)'?s (?:most|first|only)\b", "high", None),
]

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _sentences(text: str):
    for m in re.finditer(r"[^.!?\n]+[.!?]*", text):
        s = m.group(0)
        if s.strip():
            yield m.start(), m.end(), s


def _sentence_at(text: str, pos: int) -> tuple[int, int, str]:
    for s, e, sent in _sentences(text):
        if s <= pos < e:
            return s, e, sent
    return 0, len(text), text


class Builder:
    def __init__(self):
        self.items: list[dict] = []
        self.n = 0

    def add(self, **f) -> None:
        self.n += 1
        f.setdefault("id", f"R{self.n}")
        f.setdefault("engine", "rules")
        f.setdefault("target", "body")
        f.setdefault("suggestion", None)
        f.setdefault("start", None)
        f.setdefault("end", None)
        self.items.append(f)

    def overlaps(self, target: str, start: int, end: int) -> bool:
        return any(i["target"] == target and i["start"] is not None and i["start"] < end and start < i["end"] for i in self.items)


def check_text(text: str, target: str, b: Builder) -> None:
    if not text:
        return
    low = text.lower()

    # 1. Terminology
    for t in db.q("SELECT * FROM terms"):
        for bad in sorted(db.pj(t["disallowed"], []), key=len, reverse=True):
            for m in re.finditer(r"(?<![\w-])" + re.escape(bad) + r"(?![\w-])", text, flags=re.I):
                if m.group(0) == t["preferred"] or b.overlaps(target, m.start(), m.end()):
                    continue
                b.add(category="terminology", severity="medium", title="Incorrect product or brand name",
                      quote=m.group(0), start=m.start(), end=m.end(), target=target,
                      explanation=f"'{m.group(0)}' is a non-approved variant. The approved name is '{t['preferred']}'. {t['note'] or ''}".strip(),
                      source_ids=[f"T-{t['id']}"] + ([t["guideline_id"]] if t["guideline_id"] else []),
                      suggestion={"replacement": t["preferred"], "rationale": "Use the exact approved name."},
                      confidence=0.95, signature=f"term:{bad.lower()}")

    # 2. Prohibited phrases
    for p in db.q("SELECT * FROM prohibited"):
        rep = p["replacement"] or ""
        lead = r"(?:\b(?:a|an) )?" if re.match(r"(?i)an? ", rep) else ""
        for m in re.finditer(r"(?<!\w)" + lead + re.escape(p["phrase"]) + r"(?!\w)", text, flags=re.I):
            if b.overlaps(target, m.start(), m.end()):
                continue
            b.add(category=p["category"] or "tone", severity=p["severity"] or "medium",
                  title=f"Prohibited phrase: '{p['phrase']}'", quote=m.group(0), start=m.start(), end=m.end(), target=target,
                  explanation=p["reason"] or "This phrase is on the brand's prohibited list.",
                  source_ids=[f"P-{p['id']}"] + ([p["guideline_id"]] if p["guideline_id"] else []),
                  suggestion={"replacement": p["replacement"], "rationale": "Approved alternative from the Brand Brain."} if p["replacement"] else None,
                  confidence=0.9, signature=f"prohibited:{p['phrase'].lower()}")

    # 3. Facts (numbers that contradict or repeat outdated values)
    for f in db.q("SELECT * FROM facts"):
        if f["value"] is None or not f["unit"]:
            continue
        kws = [k.lower() for k in db.pj(f["keywords"], [])]
        unit_re = UNIT_ALIASES.get(f["unit"], re.escape(f["unit"]))
        outdated = [float(x) for x in db.pj(f["outdated_values"], [])]
        for s, e, sent in _sentences(text):
            sl = sent.lower()
            if kws and not any(k in sl for k in kws):
                continue
            for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:-|to)?\s*" + unit_re, sent, flags=re.I):
                num = float(m.group(1).replace(",", ""))
                if abs(num - float(f["value"])) < 1e-6:
                    continue
                a, z = s + m.start(1), s + m.end(1)
                if b.overlaps(target, a, z):
                    continue
                is_old = any(abs(num - o) < 1e-6 for o in outdated)
                val = f["value"]
                val_txt = str(int(val)) if float(val).is_integer() else str(val)
                b.add(category="facts", severity="high",
                      title="Outdated product information" if is_old else "Contradicts an approved fact",
                      quote=m.group(1), start=a, end=z, target=target,
                      explanation=(f"The content states {m.group(0).strip()} for {f['label'].lower()}. "
                                   + ("This value appeared in an earlier fact sheet and has been superseded. " if is_old else "")
                                   + f"The approved fact is: {f['statement']}"),
                      source_ids=[f["id"], "G-FACT-01"],
                      suggestion={"replacement": val_txt, "rationale": f"Matches the verified fact ({f['source']}, {f['verified_on']})."},
                      confidence=0.9 if is_old else 0.8, signature=f"fact:{f['id']}:{num:g}")

    # 4. Unsupported claims
    approved = db.q("SELECT * FROM claims")
    for pat, sev, softer in CLAIM_TRIGGERS:
        for m in re.finditer(pat, text, flags=re.I):
            if b.overlaps(target, m.start(), m.end()):
                continue
            s, e, sent = _sentence_at(text, m.start())
            sent_tokens = set(re.findall(r"[a-z0-9]+", sent.lower()))
            supported = None
            for c in approved:
                ct = set(re.findall(r"[a-z0-9]+", c["text"].lower())) - {"the", "a", "of", "in", "and", "with"}
                if ct and len(ct & sent_tokens) / len(ct) >= 0.6:
                    supported = c
                    break
            if supported:
                continue
            b.add(category="claims", severity=sev, title="Unsupported promotional claim",
                  quote=m.group(0), start=m.start(), end=m.end(), target=target,
                  explanation=(f"'{sent.strip()}' makes a superlative or absolute claim ('{m.group(0).lstrip(', ')}') "
                               "that is not in the Approved Claims register, so there is no evidence on file to support it."),
                  source_ids=["G-CLAIM-01"],
                  suggestion=({"replacement": softer, "rationale": ("Removes the unsupported claim." if softer == "" else "Softens the claim so it no longer needs evidence.") + " Alternatively, add it to the Approved Claims register with evidence."}
                              if softer is not None else None),
                  confidence=0.75, signature="claim:" + re.sub(r"^(?:the |india s |the world s )", "", re.sub(r"[^a-z0-9]+", " ", m.group(0).lower()).strip()))

    # 5. Expired dates / offers
    this_year = date.today().year
    for m in re.finditer(r"\b(?:valid|till|until|ends?|offer|launch(?:ing)?|available from)\b[^.\n]{0,40}?\b(20\d\d)\b", text, flags=re.I):
        yr = int(m.group(1))
        if yr < this_year:
            a, z = m.start(1), m.end(1)
            b.add(category="facts", severity="medium", title="Possibly expired date or offer",
                  quote=m.group(0), start=m.start(), end=m.end(), target=target,
                  explanation=f"This mentions {yr}, which is in the past. Expired offers or launch dates must be removed or updated.",
                  source_ids=["G-LEGAL-01"], suggestion=None, confidence=0.65, signature="fact:expired-date")

    # 6. Tone mechanics
    excl = [m for m in re.finditer(r"!+", text)]
    for i, m in enumerate(excl):
        if i > 0 or len(m.group(0)) > 1:
            b.add(category="tone", severity="low", title="Too many exclamation marks",
                  quote=m.group(0), start=m.start(), end=m.end(), target=target,
                  explanation="The brand voice allows at most one exclamation mark per piece. Extra ones read as shouting.",
                  source_ids=["G-TONE-02"], suggestion={"replacement": ".", "rationale": "Calm, confident punctuation."},
                  confidence=0.9, signature="tone:exclamation")
    for m in re.finditer(r"\b[A-Z][A-Z']{3,}\b", text):
        w = m.group(0)
        if w in ALLOWED_CAPS or b.overlaps(target, m.start(), m.end()):
            continue
        b.add(category="tone", severity="low", title="All-caps shouting",
              quote=w, start=m.start(), end=m.end(), target=target,
              explanation="Words in capitals are read as shouting and are harder to read for people with dyslexia. Only approved acronyms may be capitalised.",
              source_ids=["G-TONE-02"], suggestion={"replacement": w.capitalize(), "rationale": "Sentence case."},
              confidence=0.85, signature="tone:all-caps")

    # 7. Text accessibility
    for m in re.finditer(r"\bclick here\b", text, flags=re.I):
        b.add(category="accessibility", severity="medium", title="Non-descriptive link text",
              quote=m.group(0), start=m.start(), end=m.end(), target=target,
              explanation="Screen-reader users often navigate by links; 'click here' gives no context.",
              source_ids=["G-A11Y-03"], suggestion={"replacement": "Visit our website", "rationale": "Describe the destination instead of the action."},
              confidence=0.9, signature="a11y:click-here")
    for m in re.finditer(r"#([a-z0-9]{12,})\b", text):
        b.add(category="accessibility", severity="low", title="Hashtag not in CamelCase",
              quote=m.group(0), start=m.start(), end=m.end(), target=target,
              explanation="Screen readers read lowercase run-together hashtags as one long word. Capitalise each word.",
              source_ids=["G-A11Y-03"], suggestion=None, confidence=0.8, signature="a11y:hashtag-case")
    for s, e, sent in _sentences(text):
        if len(sent.split()) > 32:
            b.add(category="accessibility", severity="low", title="Very long sentence",
                  quote=sent.strip()[:80] + "…", start=s, end=e, target=target,
                  explanation=f"This sentence has {len(sent.split())} words. Keep sentences under ~25 words for readability.",
                  source_ids=["G-VOICE-01"], suggestion=None, confidence=0.7, signature="a11y:long-sentence")


def check_images(uploads: list[dict], alt_text: str, b: Builder) -> None:
    brand_colors = db.q("SELECT * FROM colors")
    logos = db.q("SELECT * FROM assets WHERE kind='logo'")
    images = [u for u in uploads if (u.get("mime") or "").startswith("image/")]
    posters = [u for u in images if u["kind"] != "logo"]

    if posters and not (alt_text or "").strip():
        b.add(category="accessibility", severity="high", title="Missing image alt text",
              quote="(no alt text)", target="alt_text",
              explanation="This content includes an image but no alternative text, so screen-reader users get nothing.",
              source_ids=["G-A11Y-01"], suggestion=None, confidence=0.98, signature="a11y:alt-missing")
    elif posters and len(alt_text.strip()) < 25:
        b.add(category="accessibility", severity="medium", title="Alt text too vague",
              quote=alt_text.strip(), start=0, end=len(alt_text), target="alt_text",
              explanation="Alt text should describe what the image shows and why it matters, not just 'poster' or 'image'.",
              source_ids=["G-A11Y-01"], suggestion=None, confidence=0.8, signature="a11y:alt-vague")

    for u in posters:
        meta = db.pj(u.get("meta"), {}) or {}
        pal = meta.get("palette") or visual.palette(storage.local(u["path"]) or u["path"])
        for issue in visual.check_palette(pal, brand_colors):
            b.add(category="visual", severity="high" if issue["share"] > 0.15 else "medium",
                  title="Unapproved brand colour", quote=issue["hex"], target=f"image:{u['id']}",
                  explanation=(f"{issue['hex']} covers about {round(issue['share'] * 100)}% of '{u['name']}' and is not in the approved palette "
                               f"(nearest approved colour: {issue['nearest']} {issue['nearest_hex']}, ΔE {issue['delta_e']})."),
                  source_ids=["V-PALETTE", "G-VIS-01"],
                  suggestion={"replacement": issue["nearest_hex"], "rationale": f"Swap to {issue['nearest']}."},
                  confidence=0.85, signature=f"visual:color:{issue['nearest'].lower()}", evidence_data=issue)
        big = [p for p in pal if p["share"] >= 0.08]
        if len(big) >= 2:
            cr = visual.contrast_ratio(visual.hex_to_rgb(big[0]["hex"]), visual.hex_to_rgb(big[1]["hex"]))
            if cr < 3.0:
                b.add(category="accessibility", severity="medium", title="Low contrast between dominant colours",
                      quote=f"{big[0]['hex']} / {big[1]['hex']}", target=f"image:{u['id']}",
                      explanation=(f"The two dominant colours in '{u['name']}' have a contrast ratio of {cr}:1. "
                                   "Any text set in one over the other would fail WCAG (needs 4.5:1, or 3:1 for large text). Heuristic check: verify the actual text colours."),
                      source_ids=["G-A11Y-02"], suggestion=None, confidence=0.6, signature="a11y:contrast")

    if logos:
        for u in [x for x in images if x["kind"] == "logo"]:
            best = None
            for lg in logos:
                r = visual.compare_logo(storage.local(u["path"]) or u["path"], storage.local(lg["path"]) or lg["path"])
                if best is None or r["shape_similarity"] > best[1]["shape_similarity"]:
                    best = (lg, r)
            lg, r = best
            ev = {**r, "official_asset": lg["name"]}
            if r["shape_similarity"] < 0.72:
                b.add(category="visual", severity="critical", title="Logo does not match any official logo",
                      quote=u["name"], target=f"image:{u['id']}",
                      explanation=f"Shape similarity to the closest official logo ('{lg['name']}') is only {round(r['shape_similarity'] * 100)}%. This may be an old or unofficial mark.",
                      source_ids=["G-VIS-02"], suggestion={"replacement": lg["name"], "rationale": "Use the official logo file from the Brand Brain."},
                      confidence=0.75, signature="logo:unofficial", evidence_data=ev)
                continue
            if r["aspect_diff_pct"] > 8:
                b.add(category="visual", severity="high", title="Logo is stretched or distorted",
                      quote=u["name"], target=f"image:{u['id']}",
                      explanation=f"The logo's aspect ratio is {r['aspect_candidate']} vs {r['aspect_official']} for the official mark ({r['aspect_diff_pct']}% off). Logos must be scaled proportionally.",
                      source_ids=["G-VIS-02"], suggestion={"replacement": lg["name"], "rationale": "Re-export from the official file and scale proportionally."},
                      confidence=0.9, signature="logo:distorted", evidence_data=ev)
            if r["color_delta_e"] > 15:
                b.add(category="visual", severity="high", title="Logo has been recoloured",
                      quote=u["name"], target=f"image:{u['id']}",
                      explanation=f"The logo's main colour is {r['main_color_candidate']} but the official mark uses {r['main_color_official']} (ΔE {r['color_delta_e']}).",
                      source_ids=["G-VIS-02", "V-PALETTE"], suggestion={"replacement": lg["name"], "rationale": "Use the official colourway."},
                      confidence=0.85, signature="logo:recoloured", evidence_data=ev)


def run(body: str, alt_text: str, uploads: list[dict]) -> list[dict]:
    b = Builder()
    check_text(body or "", "body", b)
    pdf_text = "\n\n".join(u.get("text") or "" for u in uploads if u.get("mime") == "application/pdf")
    if pdf_text.strip():
        check_text(pdf_text, "pdf", b)
    check_images(uploads, alt_text or "", b)
    b.items.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["start"] if f["start"] is not None else 10**9))
    return b.items
