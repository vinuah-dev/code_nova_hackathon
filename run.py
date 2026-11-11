"""Start Inkloom AI locally:  python run.py   then open http://127.0.0.1:8000"""
import os
import uvicorn

from server.config import load_env

if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("INKLOOM_PORT", "8000"))
    uvicorn.run("server.main:app", host="127.0.0.1", port=port, reload=False)
