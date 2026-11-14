"""Turn an uploaded brand document into proposed Brand Brain entries (facts, terms, prohibited phrases,
approved claims, colours) for an admin to review. Nothing is added automatically.

AI path: the model reads the document and must quote the exact sentence each proposal comes from;
proposals whose quote is not in the document are dropped (no invented rules).
Fallback path (no AI, AI busy, or confidential): simple patterns (hex colours, "never use 'x'",
"write it as 'x'", numbers with units).
"""
import re

from . import ai, config, db

KINDS = ("facts", "terms", "prohibited", "claims", "colors")
QUOTE = "\"'‘’“”"

SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "value": {"type": ["number", "null"]}, "unit": {"type": "string"},
            "statement": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}, "quote": {"type": "string"}},
            "required": ["label", "statement", "quote"]}},
        "terms": {"type": "array", "items": {"type": "object", "properties": {
            "preferred": {"type": "string"}, "disallowed": {"type": "array", "items": {"type": "string"}}, "quote": {"type": "string"}},
            "required": ["preferred", "disallowed", "quote"]}},
        "prohibited": {"type": "array", "items": {"type": "object", "properties": {
            "phrase": {"type": "string"}, "reason": {"type": "string"}, "replacement": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high"]}, "quote": {"type": "string"}},
            "required": ["phrase", "reason", "quote"]}},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "evidence": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["text", "evidence", "quote"]}},
        "colors": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "hex": {"type": "string"}, "usage": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["name", "hex", "quote"]}},
    },
    "required": list(KINDS),
}

SYSTEM = ("You extract machine-checkable brand rules from a company's brand guideline document. Only extract what the "
          "document states explicitly; never invent facts, numbers, words or colours. For every item, copy into 'quote' the exact "
          "sentence from the document it comes from. facts = official product figures (range, price, warranty, speed, time) with "
          "value and unit. terms = official spelling of a product or brand name, with wrong variants people might write. "
          "prohibited = words or phrases the document says not to use, with a reason and an on-brand replacement. "
          "claims = promotional claims the document approves, with the evidence it cites. colors = named brand colours with hex codes.")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')).strip().lower()


def _grounded(quote: str, text_norm: str) -> bool:
    q = _norm(quote).rstrip(".")
    return len(q) >= 8 and q in text_norm


def _existing() -> dict:
    return {
        "facts": {_norm(r["label"]) for r in db.q("SELECT label FROM facts")},
        "terms": {_norm(r["preferred"]) for r in db.q("SELECT preferred FROM terms")},
        "prohibited": {_norm(r["phrase"]) for r in db.q("SELECT phrase FROM prohibited")},
        "claims": {_norm(r["text"]) for r in db.q("SELECT text FROM claims")},
        "colors": {r["hex"].upper() for r in db.q("SELECT hex FROM colors")},
    }


def _key(kind: str, item: dict) -> str:
    return {"facts": lambda i: _norm(i.get("label")), "terms": lambda i: _norm(i.get("preferred")),
            "prohibited": lambda i: _norm(i.get("phrase")), "claims": lambda i: _norm(i.get("text")),
            "colors": lambda i: (i.get("hex") or "").upper()}[kind](item)


def _variants(name: str) -> list[str]:
    """Typical wrong spellings of a product name: hyphenated, run together, '+' spelled out."""
    out = set()
    parts = name.split()
    if len(parts) > 1:
        out.add("-".join(parts))
        out.add("".join(parts))
        out.add(" ".join(parts[1:]))
    if "+" in name:
        out.add(name.replace("+", " Plus"))
        out.add(name.replace("+", ""))
    return sorted(v for v in out if v and v != name)[:4]


def heuristic(text: str) -> dict:
    found = {k: [] for k in KINDS}
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    for s in sentences:
        for m in re.finditer(r"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)?)\s*#([0-9A-Fa-f]{6})\b", s):
            found["colors"].append({"name": m.group(1), "hex": "#" + m.group(2).upper(), "usage": "", "quote": s})
        if re.search(r"\b(never|do not|don't|avoid)\b", s, re.I):
            for w in re.findall(rf"[{QUOTE}]([^{QUOTE}]{{2,40}})[{QUOTE}]", s):
                if re.search(rf"\b(?:say|use|write)\s+[{QUOTE}]{re.escape(w)}[{QUOTE}]\s+instead", s, re.I):
                    continue
                found["prohibited"].append({"phrase": w.strip(), "reason": s[:160], "replacement": "", "severity": "medium", "quote": s})
        m = re.search(rf"\b(?:write|spell|always use|refer to it as|call it)\b[^{QUOTE}]*[{QUOTE}]([^{QUOTE}]{{3,40}})[{QUOTE}]", s, re.I)
        if m:
            found["terms"].append({"preferred": m.group(1).strip(), "disallowed": _variants(m.group(1).strip()), "quote": s})
        if "#" not in s:
            cur = re.search(r"(?:₹|\bRs\.?)\s?(\d[\d,]*(?:\.\d+)?)", s)
            num = re.search(r"\b(\d[\d,]*(?:\.\d+)?)\s*(km/h|km|minutes|min|years|year|hours|%)", s)
            hit = (cur.group(1), "INR") if cur else (num.group(1), num.group(2)) if num else None
            if hit:
                label = " ".join(re.findall(r"[A-Za-z+]+", s)[:5])
                found["facts"].append({"label": label, "value": float(hit[0].replace(",", "")), "unit": hit[1], "statement": s, "keywords": [], "quote": s})
    return found


def extract(doc_id: int) -> dict:
    d = db.one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if not d:
        raise LookupError("Document not found")
    text = d["text"] or ""
    engine, note, raw = "rules", "Pattern-based extraction (AI review is not configured).", None
    if config.ai_configured():
        try:
            raw = ai._call(SYSTEM, [{"type": "text", "text": f"DOCUMENT ({d['name']}):\n\n{text[:15000]}"}], SCHEMA, 6000)
            engine, note = "ai", f"{config.provider_label()} · {config.model()}: every proposal quotes the sentence it came from."
        except ai.AIUnavailable as e:
            note = f"AI unavailable ({e}); pattern-based extraction used instead."
    if raw is None:
        raw = heuristic(text)
    text_norm = _norm(text)
    have = _existing()
    out, dropped = {k: [] for k in KINDS}, 0
    for kind in KINDS:
        seen = set()
        for item in raw.get(kind) or []:
            if not isinstance(item, dict):
                continue
            k = _key(kind, item)
            if not k or k in seen:
                continue
            if not _grounded(item.get("quote", ""), text_norm):
                dropped += 1  # not traceable to the document: never proposed
                continue
            seen.add(k)
            if kind == "colors" and not re.fullmatch(r"#[0-9A-F]{6}", (item.get("hex") or "").upper()):
                continue
            if kind == "terms" and not item.get("disallowed"):
                item["disallowed"] = _variants(item.get("preferred", ""))
            item["already"] = k in have[kind]
            item["source"] = f"DOC-{doc_id}"
            out[kind].append(item)
    return {"document": {"id": d["id"], "name": d["name"]}, "engine": engine, "note": note, "dropped_ungrounded": dropped, "proposals": out}
