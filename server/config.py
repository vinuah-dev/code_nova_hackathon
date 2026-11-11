"""Settings and a tiny .env loader (keeps us free of extra dependencies)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Serverless hosts (Vercel) only allow writes under /tmp; data there is ephemeral and re-seeded on cold start.
_default_data = Path("/tmp/inkloom") if os.environ.get("VERCEL") else ROOT / "data"
DATA_DIR = Path(os.environ.get("INKLOOM_DATA_DIR") or _default_data)
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "inkloom.db"
WEB_DIR = ROOT / "web"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and k not in os.environ:
            os.environ[k] = v


# Providers. "anthropic" uses the official SDK; the others speak the OpenAI-compatible
# /chat/completions protocol, which Gemini, Groq, OpenRouter and Ollama all expose.
PRESETS = {
    "anthropic": {"label": "Claude", "model": "claude-opus-5-5", "base_url": None},
    "gemini": {"label": "Gemini", "model": "gemini-3.5-flash", "fallback": "gemini-3.5-flash-lite", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "groq": {"label": "Groq", "model": "meta-llama/llama-4-scout-17b-16e-instruct", "base_url": "https://api.groq.com/openai/v1"},
    "openrouter": {"label": "OpenRouter", "model": "google/gemini-2.5-flash", "base_url": "https://openrouter.ai/api/v1"},
    "ollama": {"label": "Ollama (local)", "model": "llama3.2-vision", "base_url": "http://localhost:11434/v1"},
    "openai-compatible": {"label": "AI", "model": "", "base_url": None},
}


def provider() -> str:
    p = (os.environ.get("INKLOOM_AI_PROVIDER") or "").strip().lower()
    if p in PRESETS:
        return p
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "anthropic"


def provider_label() -> str:
    return PRESETS[provider()]["label"]


def model() -> str:
    return os.environ.get("INKLOOM_MODEL") or PRESETS[provider()]["model"]


def fallback_model() -> str | None:
    return os.environ.get("INKLOOM_FALLBACK_MODEL") or PRESETS[provider()].get("fallback")


def base_url() -> str | None:
    return (os.environ.get("INKLOOM_AI_BASE_URL") or PRESETS[provider()]["base_url"] or "").rstrip("/") or None


def api_key() -> str | None:
    p = provider()
    if p == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return (os.environ.get("INKLOOM_AI_API_KEY") or (os.environ.get("GEMINI_API_KEY") if p == "gemini" else None)
            or ("ollama" if p == "ollama" else None))


def send_images() -> bool:
    return os.environ.get("INKLOOM_AI_IMAGES", "1") != "0"


def effort() -> str:
    return os.environ.get("INKLOOM_EFFORT", "medium")


def ai_configured() -> bool:
    if os.environ.get("INKLOOM_DISABLE_AI") == "1":
        return False
    if provider() != "anthropic" and not base_url():
        return False
    return bool(api_key())
