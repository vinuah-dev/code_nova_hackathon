"""Language detection for brand reviews: English, Hindi (Devanagari) and Hinglish (Hindi in Latin script).

Cheap and deterministic, so it runs on every review and costs nothing:
- Hindi: share of Devanagari letters among all letters.
- Hinglish: share of common Hindi function words among Latin-script words.
"""
import re

DEVA = "ऀ-ॿ"
# Letters and signs only: the danda (।, ॥) is punctuation and must count as a boundary.
DEVA_WORD = "ऀ-ॣ०-ॿ"
# Word boundary that also works for Devanagari (Python's \\b breaks on vowel signs such as ा or े).
B_LEFT = rf"(?<![\w{DEVA_WORD}])"
B_RIGHT = rf"(?![\w{DEVA_WORD}])"

HINGLISH_WORDS = {
    "hai", "hain", "ka", "ki", "ke", "ko", "se", "mein", "main", "par", "aur", "ya", "nahi", "nahin", "kya", "kyun", "kyunki",
    "ho", "hoga", "hogi", "karo", "karein", "kare", "karna", "kar", "abhi", "sabse", "wala", "wali", "wale", "bhi", "ye", "yeh",
    "vo", "woh", "hum", "aap", "tum", "apna", "apni", "liye", "sirf", "bas", "ek", "do", "teen", "ab", "jaldi", "bahut", "accha",
    "achha", "acchi", "sasta", "sasti", "mehnga", "naya", "nayi", "saath", "tak", "lekin", "agar", "toh", "to", "hamara", "hamari",
    "dekho", "dekhiye", "milega", "milegi", "chalao", "chalaiye", "yahan", "yaha", "wahan", "kab", "kaise", "kitna", "paisa",
}


def detect(text: str) -> dict:
    """Return {'code': 'en'|'hi'|'hinglish'|'mixed', 'label': ..., 'devanagari': share, 'hinglish': share}."""
    text = text or ""
    deva = len(re.findall(f"[{DEVA}]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    letters = deva + latin
    words = re.findall(r"[A-Za-z]+", text.lower())
    hing = sum(1 for w in words if w in HINGLISH_WORDS)
    deva_share = deva / letters if letters else 0.0
    hing_share = hing / len(words) if words else 0.0
    if not letters:
        code = "en"
    elif deva_share >= 0.6:
        code = "hi"
    elif deva_share >= 0.15:
        code = "mixed"
    elif hing_share >= 0.15 and hing >= 2:
        code = "hinglish"
    else:
        code = "en"
    labels = {"en": "English", "hi": "Hindi (Devanagari)", "hinglish": "Hinglish (Hindi in Latin script)", "mixed": "Mixed Hindi and English"}
    return {"code": code, "label": labels[code], "devanagari": round(deva_share, 2), "hinglish": round(hing_share, 2)}


def has_devanagari(s: str) -> bool:
    return bool(re.search(f"[{DEVA}]", s or ""))
