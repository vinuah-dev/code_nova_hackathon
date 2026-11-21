"""Round 3 improvement 1: read the text printed inside images (posters, banners, social creatives).

We use the vision model we already call (Gemini via the OpenAI-compatible API) as the OCR engine:
it transcribes each line exactly and returns a bounding box, which lets the report draw the problem
region on the image. Results are cached in the upload's `meta`, so a re-review costs nothing.
Never called for confidential content (the caller checks), and a failure only means "no OCR text".
"""
import re

from . import ai, config, db

SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"},
        "box_2d": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
        "required": ["text", "box_2d"]}}},
    "required": ["lines"],
}
SYSTEM = ("You are an OCR engine. Transcribe every line of text visible in the image exactly as printed: keep the "
          "spelling, numbers, punctuation, capital letters and script (English, Hindi, Hinglish). Do not translate, "
          "correct or add anything. For each line give box_2d = [ymin, xmin, ymax, xmax] on a 0-1000 scale "
          "(the standard Gemini box format). Return JSON only.")
OCR_BUDGET_S = 20


def _clean(lines) -> list[dict]:
    out = []
    for ln in lines if isinstance(lines, list) else []:
        if not isinstance(ln, dict):
            continue
        text = re.sub(r"\s+", " ", str(ln.get("text") or "")).strip()
        raw = ln.get("box_2d") or ln.get("box") or []
        if len(raw) == 1 and isinstance(raw[0], list):  # some answers nest the box: [[ymin, xmin, ymax, xmax]]
            raw = raw[0]
        if not text or len(raw) != 4:
            continue
        try:
            vals = [float(v) for v in raw]
        except (TypeError, ValueError):
            continue
        scale = 1000.0 if max(vals) > 1.5 else 1.0  # models answer on 0-1000 or 0-1
        ymin, xmin, ymax, xmax = (max(0.0, min(1.0, v / scale)) for v in vals)
        x0, x1, y0, y1 = min(xmin, xmax), max(xmin, xmax), min(ymin, ymax), max(ymin, ymax)
        if x1 <= x0 or y1 <= y0:
            continue
        out.append({"text": text, "box": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]})
    return out


def read(upload: dict) -> dict:
    """OCR one image upload, using the cache in its meta when present. Returns {'lines', 'engine', 'error'}."""
    meta = db.pj(upload.get("meta"), {}) or {}
    if isinstance(meta.get("ocr"), dict) and not meta["ocr"].get("error"):
        return meta["ocr"]
    if not config.ai_configured():
        return {"lines": [], "engine": None, "error": "OCR needs the AI service, which is not configured"}
    try:
        raw = ai._call(SYSTEM, [{"type": "text", "text": "Read all text in this image."}, ai._image_block(upload["path"])],
                       SCHEMA, 3000, budget=OCR_BUDGET_S)
        result = {"lines": _clean(raw.get("lines") if isinstance(raw, dict) else None),
                  "engine": f"{config.provider_label()} · {config.model()}", "error": None}
    except ai.AIUnavailable as e:
        result = {"lines": [], "engine": None, "error": str(e)}
    meta["ocr"] = result
    upload["meta"] = db.j(meta)
    if upload.get("id") is not None:
        db.ex("UPDATE uploads SET meta=? WHERE id=?", (db.j(meta), upload["id"]))
    return result


def text_and_index(lines: list[dict]) -> tuple[str, list[tuple[int, int, list]]]:
    """Join OCR lines into one text (one line per row) and keep where each line starts, for boxes."""
    parts, index, pos = [], [], 0
    for ln in lines:
        parts.append(ln["text"])
        index.append((pos, pos + len(ln["text"]), ln["box"]))
        pos += len(ln["text"]) + 1
    return "\n".join(parts), index


def box_for(index: list, start: int | None, end: int | None) -> list | None:
    """Union of the boxes of the OCR lines a finding's span touches."""
    if start is None:
        return None
    hits = [b for s, e, b in index if s <= (end or start) and start <= e]
    if not hits:
        return None
    return [min(b[0] for b in hits), min(b[1] for b in hits), max(b[2] for b in hits), max(b[3] for b in hits)]
