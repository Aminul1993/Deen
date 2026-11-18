"""Redis storage: the Groq and Pinecone credentials, the files uploaded from the admin page, and
the uploads still in progress (upload jobs), so any worker process can report on them.

REDIS_URL says where the database is, e.g. redis://default:password@host:port (rediss:// for
TLS). Every key starts with "deen:", so the database can be shared with other apps:

    deen:settings              hash: setting name -> value
    deen:uploads:<index name>  hash: JSON [namespace, file id] -> JSON of the uploaded file's row
    deen:job:<id>              hash: column -> JSON value, one per upload in progress
    deen:jobs                  set of the ids of those jobs

It holds API keys in plain text, so keep the URL secret and the database private.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis

PREFIX = "deen:"
SETTINGS_KEY = PREFIX + "settings"
JOBS_KEY = PREFIX + "jobs"

JOB_STATES_FINISHED = ("done", "failed")

JOB_FIELDS = ("id", "namespace", "filename", "source_url", "size", "received", "state", "passages",
              "result", "error", "created_at", "updated_at")

_clients: Dict[str, redis.Redis] = {}


def client() -> redis.Redis:
    """The client for REDIS_URL, made once per address. It's thread-safe (it keeps a connection pool)."""
    # Read on every call, so REDIS_URL from .env applies even though this module is imported first.
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise RuntimeError("REDIS_URL isn't set. Set it to the Redis database, "
                           "e.g. REDIS_URL=redis://default:password@host:6379")
    if url not in _clients:
        # health checks reconnect after a hosted Redis drops an idle connection
        _clients[url] = redis.Redis.from_url(url, decode_responses=True, socket_timeout=10,
                                             socket_connect_timeout=10, health_check_interval=30)
    return _clients[url]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Settings (credentials and models)
# --------------------------------------------------------------------------- #


def get_settings() -> Dict[str, str]:
    return client().hgetall(SETTINGS_KEY)


def save_settings(values: Dict[str, str]) -> None:
    """Insert or update settings, all at once."""
    if values:
        client().hset(SETTINGS_KEY, mapping=values)


# --------------------------------------------------------------------------- #
# Uploaded files
# --------------------------------------------------------------------------- #


def _uploads_key(index_name: str) -> str:
    return f"{PREFIX}uploads:{index_name}"


def _upload_field(namespace: str, file_id: str) -> str:
    return json.dumps([namespace, file_id])


def list_uploads(index_name: str) -> List[Dict[str, Any]]:
    """Files uploaded to this index, newest first."""
    rows = [json.loads(row) for row in client().hvals(_uploads_key(index_name))]
    rows.sort(key=lambda row: row["filename"])
    rows.sort(key=lambda row: row["uploaded_at"], reverse=True)  # stable, so equal times stay by filename
    return rows


def get_upload(index_name: str, namespace: str, file_id: str) -> Optional[Dict[str, Any]]:
    row = client().hget(_uploads_key(index_name), _upload_field(namespace, file_id))
    return json.loads(row) if row else None


def save_upload(index_name: str, namespace: str, file_id: str, filename: str,
                passages: int, size_bytes: int, uploaded_at: Optional[str] = None) -> Dict[str, Any]:
    """Record an uploaded file and return its row.

    uploaded_at orders a reader's passages. It defaults to now, and a file uploaded again keeps
    the time of its first upload, so it doesn't jump to the end of the reader.
    """
    earlier = get_upload(index_name, namespace, file_id)
    row = {"file_id": file_id, "filename": filename, "namespace": namespace, "passages": passages,
           "size_bytes": size_bytes, "uploaded_at": earlier["uploaded_at"] if earlier else uploaded_at or _now()}
    client().hset(_uploads_key(index_name), _upload_field(namespace, file_id), json.dumps(row))
    return row


def delete_upload(index_name: str, namespace: str, file_id: str) -> None:
    client().hdel(_uploads_key(index_name), _upload_field(namespace, file_id))


# --------------------------------------------------------------------------- #
# Uploads in progress
# --------------------------------------------------------------------------- #


def _job_key(job_id: str) -> str:
    return f"{PREFIX}job:{job_id}"


def _encode(fields: Dict[str, Any]) -> Dict[str, str]:
    """Each value as JSON, so numbers and None come back as they went in."""
    return {name: json.dumps(value) for name, value in fields.items()}


def create_job(job_id: str, namespace: str, state: str, filename: Optional[str] = None,
               source_url: Optional[str] = None, size: Optional[int] = None) -> Dict[str, Any]:
    now = _now()
    job = {"id": job_id, "namespace": namespace, "filename": filename, "source_url": source_url, "size": size,
           "received": 0, "state": state, "passages": 0, "result": None, "error": None,
           "created_at": now, "updated_at": now}
    pipe = client().pipeline()  # MULTI/EXEC: both or neither
    pipe.hset(_job_key(job_id), mapping=_encode(job))
    pipe.sadd(JOBS_KEY, job_id)
    pipe.execute()
    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    raw = client().hgetall(_job_key(job_id))
    if not raw:
        return None
    return {name: json.loads(raw[name]) if name in raw else None for name in JOB_FIELDS}


def update_job(job_id: str, **fields: Any) -> None:
    client().hset(_job_key(job_id), mapping=_encode({**fields, "updated_at": _now()}))


def stale_jobs(before: str) -> List[str]:
    """Jobs last updated before this time: finished ones, and uploads that were abandoned."""
    ids = list(client().smembers(JOBS_KEY))
    pipe = client().pipeline(transaction=False)
    for job_id in ids:
        pipe.hget(_job_key(job_id), "updated_at")
    # A job whose hash is gone counts as stale too, so its id leaves the set.
    return [job_id for job_id, updated in zip(ids, pipe.execute()) if updated is None or json.loads(updated) < before]


def delete_job(job_id: str) -> None:
    pipe = client().pipeline()
    pipe.delete(_job_key(job_id))
    pipe.srem(JOBS_KEY, job_id)
    pipe.execute()


def move_job(job_id: str, from_state: str, to_state: str) -> bool:
    """Change a job's state only if it's still from_state. False when another request got there first."""
    key = _job_key(job_id)

    def move(pipe: redis.client.Pipeline) -> bool:
        # WATCH makes EXEC fail, and this run again, if the job changes before the update lands.
        if pipe.hget(key, "state") != json.dumps(from_state):
            return False
        pipe.multi()
        pipe.hset(key, mapping=_encode({"state": to_state, "updated_at": _now()}))
        return True

    return client().transaction(move, key, value_from_callable=True)
