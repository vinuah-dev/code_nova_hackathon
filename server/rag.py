"""Retrieval over approved brand knowledge (the "Brand Brain").

Every guideline, fact, approved claim, terminology rule, prohibited phrase, colour
and paragraph of an uploaded guideline document becomes a chunk with a stable
source id (e.g. G-TONE-01, F-RANGE, C-02, DOC-3#4). We rank chunks with BM25 —
lexical, fast, no embedding service needed, and fully explainable. The top chunks
are what the AI is allowed to cite; findings citing anything else are marked
ungrounded.
"""
import math
import re
from collections import Counter

from . import db

_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
_STOP = set("""a an the and or of to in on for with by at from is are was were be been it its this that these
those as we our you your they their i he she not no but if then so than into over under about can will just
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP]


def build_chunks() -> list[dict]:
    chunks: list[dict] = []
    for g in db.q("SELECT * FROM guidelines"):
        chunks.append({"id": g["id"], "type": "guideline", "category": g["category"],
                       "title": g["title"], "text": g["body"]})
    for f in db.q("SELECT * FROM facts"):
        chunks.append({"id": f["id"], "type": "fact", "category": "facts", "title": f["label"],
                       "text": f"{f['statement']} (Source: {f['source'] or 'n/a'}, verified {f['verified_on'] or 'n/a'})"})
    for c in db.q("SELECT * FROM claims"):
        chunks.append({"id": c["id"], "type": "claim", "category": "claims", "title": "Approved claim",
                       "text": f"{c['text']} Evidence: {c['evidence'] or 'n/a'}"})
    for t in db.q("SELECT * FROM terms"):
        bad = ", ".join(db.pj(t["disallowed"], []))
        chunks.append({"id": f"T-{t['id']}", "type": "term", "category": "terminology",
                       "title": f"Use '{t['preferred']}'",
                       "text": f"Always write '{t['preferred']}'. Do not write: {bad}. {t['note'] or ''}"})
    for p in db.q("SELECT * FROM prohibited"):
        chunks.append({"id": f"P-{p['id']}", "type": "prohibited", "category": p["category"],
                       "title": f"Avoid '{p['phrase']}'",
                       "text": f"Do not use '{p['phrase']}'. {p['reason'] or ''} Prefer: {p['replacement'] or 'rephrase'}."})
    colors = db.q("SELECT * FROM colors")
    if colors:
        chunks.append({"id": "V-PALETTE", "type": "visual", "category": "visual", "title": "Approved colour palette",
                       "text": "Approved colours: " + "; ".join(f"{c['name']} {c['hex']} ({c['usage']})" for c in colors)})
    for d in db.q("SELECT id, name, text FROM documents"):
        paras = [p.strip() for p in re.split(r"\n\s*\n", d["text"] or "") if len(p.strip()) > 40]
        for i, p in enumerate(paras, 1):
            chunks.append({"id": f"DOC-{d['id']}#{i}", "type": "document", "category": "document",
                           "title": f"{d['name']} §{i}", "text": p[:1200]})
    return chunks


class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs = [Counter(tokenize(c["title"] + " " + c["text"])) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, text: str, k: int = 8, k1: float = 1.4, b: float = 0.75) -> list[dict]:
        qtok = set(tokenize(text))
        scored = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in qtok:
                if t in d:
                    tf = d[t]
                    s += self.idf[t] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.lens[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [{**self.chunks[i], "score": round(s, 3)} for s, i in scored[:k]]


def retrieve(text: str, k: int = 10) -> list[dict]:
    """Top-k chunks for the content, plus the core guidelines that always apply."""
    chunks = build_chunks()
    idx = Index(chunks)
    hits = idx.search(text, k=k)
    have = {h["id"] for h in hits}
    # Tone/voice, accessibility and palette guidance applies to every piece of content.
    for c in chunks:
        if c["id"] not in have and (c["category"] in ("tone", "accessibility") or c["id"] == "V-PALETTE") and c["type"] in ("guideline", "visual"):
            hits.append({**c, "score": 0.0, "always": True})
            have.add(c["id"])
    return hits


def source_lookup() -> dict[str, dict]:
    return {c["id"]: c for c in build_chunks()}
