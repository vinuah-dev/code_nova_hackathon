"""File storage that survives serverless instances.

Files are written to the local upload folder as before and, when a Postgres database is configured,
also stored in the `blobs` table. `local(path)` returns a readable local path, restoring the file
from the database first if this instance has never seen it (another Vercel instance uploaded it).
"""
from pathlib import Path

from . import db
from .config import UPLOAD_DIR


def _key(path) -> str:
    return Path(path).name


def save(path, raw: bytes, mime: str | None = None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(raw)
    db.conn()
    if db.IS_PG:
        db.ex("INSERT INTO blobs(name, data, mime, created_at) VALUES (?,?,?,?) "
              "ON CONFLICT(name) DO UPDATE SET data=excluded.data, mime=excluded.mime",
              (_key(p), raw, mime, db.now()))


def save_file(path, mime: str | None = None) -> None:
    """Mirror an existing local file into the database."""
    save(path, Path(path).read_bytes(), mime)


def local(path) -> str | None:
    """A local path for `path`, restoring it from the database if needed. None if it doesn't exist anywhere."""
    if not path:
        return None
    p = Path(path)
    if p.exists():
        return str(p)
    alt = UPLOAD_DIR / _key(p)
    if alt.exists():
        return str(alt)
    db.conn()
    if db.IS_PG:
        row = db.one("SELECT data FROM blobs WHERE name=?", (_key(p),))
        if row and row["data"] is not None:
            alt.parent.mkdir(parents=True, exist_ok=True)
            alt.write_bytes(bytes(row["data"]))
            return str(alt)
    return None
