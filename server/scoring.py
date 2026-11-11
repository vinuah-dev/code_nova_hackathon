"""Transparent compliance scoring.

Every open finding carries a penalty = SEVERITY_PENALTY[severity] × confidence.
    overall   = 100 × e^(−Σ penalties / 100)
    dimension = 100 × e^(−Σ penalties in that dimension / 50)
So clean content scores 100, one medium terminology slip ≈ 91, one wrong fact ≈ 82,
and heavily non-compliant content approaches 0. Findings a reviewer rejected as
false positives do not count. Same input → same score, every time.
"""
import math

SEVERITY_PENALTY = {"critical": 35, "high": 20, "medium": 10, "low": 4}
DIMENSIONS = ["claims", "facts", "terminology", "tone", "visual", "accessibility"]
LABELS = {"claims": "Claims", "facts": "Facts", "terminology": "Terminology", "tone": "Tone & messaging",
          "visual": "Visual identity", "accessibility": "Accessibility"}


def penalty(f: dict) -> float:
    return SEVERITY_PENALTY.get(f.get("severity"), 5) * float(f.get("confidence") or 0.7)


def score(findings: list[dict], ignore_ids: set[str] | None = None) -> dict:
    ignore_ids = ignore_ids or set()
    per = {k: 0.0 for k in DIMENSIONS}
    for f in findings:
        if f["id"] in ignore_ids:
            continue
        cat = f.get("category") if f.get("category") in per else "tone"
        per[cat] += penalty(f)
    total = sum(per.values())
    dims = {k: round(100 * math.exp(-v / 50), 1) for k, v in per.items()}
    return {"overall": round(100 * math.exp(-total / 100), 1), "dimensions": dims, "penalty": round(total, 1)}


def explain() -> dict:
    return {"penalties": SEVERITY_PENALTY, "labels": LABELS,
            "formula": "overall = 100 × e^(−Σ penalty / 100), where penalty = severity weight × confidence for every open finding",
            "bands": {"ready": 85, "attention": 60}}
