"""SQLite storage: the Groq and Pinecone credentials, the files uploaded from the admin page, and
the uploads still in progress (upload_jobs), so any worker process can report on them.

The database is one file, data/deen.db by default (set DB_PATH to move it, e.g. onto a persistent
volume). It's created on first use. It holds API keys in plain text, so keep it out of version
control and readable only by the server's user.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "deen.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    name        TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    index_name  TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    file_id     TEXT NOT NULL,
    filename    TEXT NOT NULL,
    passages    INTEGER NOT NULL,
    size_bytes  INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (index_name, namespace, file_id)
);
CREATE TABLE IF NOT EXISTS upload_jobs (
    id         TEXT PRIMARY KEY,
    namespace  TEXT NOT NULL,
    filename   TEXT,                  -- NULL while a web address is still downloading
    source_url TEXT,                  -- set for downloads, without query string or password
    size       INTEGER,               -- total bytes expected; NULL while downloading
    received   INTEGER NOT NULL DEFAULT 0,
    state      TEXT NOT NULL,         -- receiving, downloading, processing, done or failed
    passages   INTEGER NOT NULL DEFAULT 0,  -- stored so far
    result     TEXT,                  -- JSON of the upload result when done
    error      TEXT,                  -- why it failed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

JOB_STATES_FINISHED = ("done", "failed")

UPLOAD_COLUMNS = "file_id, filename, namespace, passages, size_bytes, uploaded_at"

_ready: Set[Path] = set()
_ready_lock = threading.Lock()


def database_path() -> Path:
    # Read on every call, so DB_PATH from .env applies even though this module is imported first.
    return Path(os.getenv("DB_PATH", "").strip() or DEFAULT_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _create_schema(path: Path) -> None:
    if path in _ready:
        return
    with _ready_lock:
        if path in _ready:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        conn = sqlite3.connect(path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # readers aren't blocked by a writer
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        if is_new:
            try:
                os.chmod(path, 0o600)  # owner only: the file holds API keys (no effect on Windows)
            except OSError:
                pass
        _ready.add(path)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits when the block succeeds, rolls back when it raises, then closes."""
    path = database_path()
    _create_schema(path)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Settings (credentials and models)
# --------------------------------------------------------------------------- #


def get_settings() -> Dict[str, str]:
    with _connect() as conn:
        return {row["name"]: row["value"] for row in conn.execute("SELECT name, value FROM settings")}


def save_settings(values: Dict[str, str]) -> None:
    """Insert or update settings, all in one transaction."""
    now = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO settings (name, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT (name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            [(name, value, now) for name, value in values.items()],
        )


# --------------------------------------------------------------------------- #
# Uploaded files
# --------------------------------------------------------------------------- #


def list_uploads(index_name: str) -> List[Dict[str, Any]]:
    """Files uploaded to this index, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {UPLOAD_COLUMNS} FROM uploads WHERE index_name = ? ORDER BY uploaded_at DESC, filename",
            (index_name,),
        )
        return [dict(row) for row in rows]


def get_upload(index_name: str, namespace: str, file_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {UPLOAD_COLUMNS} FROM uploads WHERE index_name = ? AND namespace = ? AND file_id = ?",
            (index_name, namespace, file_id),
        ).fetchone()
        return dict(row) if row else None


def save_upload(index_name: str, namespace: str, file_id: str, filename: str,
                passages: int, size_bytes: int, uploaded_at: Optional[str] = None) -> Dict[str, Any]:
    """Record an uploaded file and return its row.

    uploaded_at orders a reader's passages. It defaults to now, and a file uploaded again keeps
    the time of its first upload, so it doesn't jump to the end of the reader.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT INTO uploads (index_name, namespace, file_id, filename, passages, size_bytes, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (index_name, namespace, file_id) DO UPDATE SET "
            "filename = excluded.filename, passages = excluded.passages, size_bytes = excluded.size_bytes",
            (index_name, namespace, file_id, filename, passages, size_bytes, uploaded_at or _now()),
        )
    row = get_upload(index_name, namespace, file_id)
    assert row is not None
    return row


def delete_upload(index_name: str, namespace: str, file_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM uploads WHERE index_name = ? AND namespace = ? AND file_id = ?",
            (index_name, namespace, file_id),
        )


# --------------------------------------------------------------------------- #
# Uploads in progress
# --------------------------------------------------------------------------- #


def create_job(job_id: str, namespace: str, state: str, filename: Optional[str] = None,
               source_url: Optional[str] = None, size: Optional[int] = None) -> Dict[str, Any]:
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO upload_jobs (id, namespace, filename, source_url, size, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, namespace, filename, source_url, size, state, now, now),
        )
    job = get_job(job_id)
    assert job is not None
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM upload_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job(job_id: str, **fields: Any) -> None:
    columns = ", ".join(f"{name} = ?" for name in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE upload_jobs SET {columns}, updated_at = ? WHERE id = ?",
                     (*fields.values(), _now(), job_id))


def stale_jobs(before: str) -> List[str]:
    """Jobs last updated before this time: finished ones, and uploads that were abandoned."""
    with _connect() as conn:
        return [row["id"] for row in conn.execute("SELECT id FROM upload_jobs WHERE updated_at < ?", (before,))]


def delete_job(job_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM upload_jobs WHERE id = ?", (job_id,))


def move_job(job_id: str, from_state: str, to_state: str) -> bool:
    """Change a job's state only if it's still from_state. False when another request got there first."""
    with _connect() as conn:
        cursor = conn.execute("UPDATE upload_jobs SET state = ?, updated_at = ? WHERE id = ? AND state = ?",
                              (to_state, _now(), job_id, from_state))
        return cursor.rowcount == 1
