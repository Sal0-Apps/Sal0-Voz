"""SQLite catalog and atomic files. All persistent paths are rooted in SAL0_DATA."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.getenv("SAL0_DATA", "data")).resolve()


def init():
    for folder in ("media", "projects", "models", "jobs", "exports", "backups", "cache"):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
          kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
          updated REAL NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        PRAGMA user_version=1;
        """)


@contextmanager
def db():
    conn = sqlite3.connect(DATA / "app.sqlite", timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def uid():
    return uuid.uuid4().hex


def put(kind, value):
    value = dict(value)
    value.setdefault("id", uid())
    value["updated"] = time.time()
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)",
                     (kind, value["id"], json.dumps(value, ensure_ascii=False), value["updated"]))
    return value


def get(kind, ident):
    with db() as conn:
        row = conn.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone()
    if not row:
        raise KeyError("Registro não encontrado")
    return json.loads(row[0])


def listing(kind, offset=0, limit=50):
    with db() as conn:
        rows = conn.execute("SELECT body FROM records WHERE kind=? ORDER BY updated DESC LIMIT ? OFFSET ?",
                            (kind, limit, offset)).fetchall()
    return [json.loads(row[0]) for row in rows]


def setting(key, value=None):
    with db() as conn:
        if value is not None:
            conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def safe_path(relative):
    path = (DATA / relative).resolve()
    if not path.is_relative_to(DATA) or path == DATA:
        raise ValueError("Caminho inválido")
    return path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
