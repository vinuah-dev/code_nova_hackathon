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


def model() -> str:
    return os.environ.get("INKLOOM_MODEL", "claude-opus-5-5")


def effort() -> str:
    return os.environ.get("INKLOOM_EFFORT", "medium")


def ai_configured() -> bool:
    if os.environ.get("INKLOOM_DISABLE_AI") == "1":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
