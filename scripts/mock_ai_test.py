"""Tests the OpenAI-compatible AI path (Gemini / Groq / OpenRouter / Ollama) against a local mock server.

Run:  python scripts/mock_ai_test.py
No real API key or network access needed.
"""
import base64
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODE = {"status": 200}
SEEN = []


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if MODE["status"] != 200:
            self.send_response(MODE["status"])
            self.end_headers()
            self.wfile.write(b'{"error":"limit"}')
            return
        answer = {"summary": "Mock review", "findings": [
            {"category": "tone", "severity": "medium", "title": "Hype-driven festive tone", "target": "body",
             "quote": "Meet the all-new", "explanation": "Hype opener.", "source_ids": ["G-VOICE-01", "BOGUS-9"],
             "replacement": "Introducing the", "rationale": "Calm voice", "confidence": 0.8},
            {"category": "visual", "severity": "high", "title": "Firecracker-style 'DHAMAKA' headline", "target": "image",
             "quote": "", "explanation": "Brand book bans explosion imagery.", "source_ids": [], "replacement": "",
             "rationale": "", "confidence": 0.9},
            {"category": "nonsense", "severity": "huge", "title": "should be dropped"},
        ]}
        out = {"choices": [{"finish_reason": "stop", "message": {"content": "```json\n" + json.dumps(answer) + "\n```"}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), Mock)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update({"INKLOOM_DATA_DIR": tempfile.mkdtemp(prefix="inkloom_mock_"), "INKLOOM_AI_PROVIDER": "openai-compatible",
                   "INKLOOM_AI_BASE_URL": f"http://127.0.0.1:{srv.server_port}", "INKLOOM_AI_API_KEY": "test-key",
                   "INKLOOM_MODEL": "mock-model"})
os.environ.pop("INKLOOM_DISABLE_AI", None)

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402

ok = 0


def check(cond, msg):
    global ok
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    ok += 1
    print(f"  ok  {msg}")


H = {"X-User-Id": "u-creator"}
demo = ROOT / "web" / "demo"
with TestClient(app) as c:
    st = c.get("/api/status").json()
    check(st["ai_configured"] and st["provider"] == "openai-compatible", "provider configured from env")
    up = c.post("/api/uploads", headers=H, json={"name": "p.png", "mime": "image/png", "kind": "poster",
                                                 "data": base64.b64encode((demo / "diwali_poster.png").read_bytes()).decode()}).json()
    cid = c.post("/api/content", headers=H, json={"title": "t", "body": (demo / "diwali_caption.txt").read_text(encoding="utf-8"),
                                                  "attachments": [up["id"]]}).json()["id"]
    r = c.post(f"/api/content/{cid}/analyze", headers=H).json()
    req = SEEN[-1]
    check(req["path"] == "/chat/completions" and req["auth"] == "Bearer test-key", "calls /chat/completions with bearer key")
    check(req["body"]["model"] == "mock-model" and req["body"]["response_format"]["type"] == "json_object", "model + JSON mode sent")
    parts = req["body"]["messages"][1]["content"]
    check(any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts), "poster sent as image")
    check(any("[G-VOICE-01]" in p.get("text", "") for p in parts), "retrieved Brand Brain sources sent with ids")
    check(r["mode"] == "ai+rules", f"mode ai+rules ({r['note'][:40]}…)")
    ai = [f for f in r["findings"] if f["engine"] == "ai"]
    check(len(ai) == 2, "invalid AI finding dropped, 2 kept")
    tone = next(f for f in ai if f["category"] == "tone")
    check(tone["start"] is not None and tone["grounded"] and tone["source_ids"] == ["G-VOICE-01"], "quote located, bogus source id removed, grounded")
    vis = next(f for f in ai if f["category"] == "visual")
    check(vis["target"].startswith("image:") and not vis["grounded"] and vis["confidence"] < 0.9, "uncited finding marked ungrounded and down-weighted")

    MODE["status"] = 429
    r2 = c.post(f"/api/content/{cid}/analyze", headers=H).json()
    check(r2["mode"] == "rules" and "Rate limited" in (r2["ai_error"] or ""), "429 falls back to rule-engine report with a clear note")
    check(len(r2["findings"]) >= 15, "fallback report still has the rule findings")
print(f"\nAll {ok} mock-AI checks passed.")
srv.shutdown()
