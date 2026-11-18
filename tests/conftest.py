"""Test setup: an isolated database per test, no real credentials, and fakes for Pinecone, Groq and Redis.

Run with:  pytest
"""

import json
import os
import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Before main is imported: load_dotenv() doesn't override variables that are already set, so these
# keep the real .env out of the tests. With REDIS_URL empty, the real database can't be reached.
ADMIN_TOKEN = "test-admin-token-0123456789-abcdef"
os.environ.update({
    "REDIS_URL": "",
    "ADMIN_TOKEN": ADMIN_TOKEN,
    "PINECONE_API_KEY": "", "PINECONE_INDEX_NAME": "", "PINECONE_EMBEDDING_MODEL": "",
    "GROQ_API_KEY": "", "GROQ_MODEL": "", "MIN_RELEVANCE_SCORE": "",
})

import main  # noqa: E402

DIM = 4  # vector size of the fake embedding model


class RateLimited(Exception):
    status_code = 429


class FakeIndex:
    """A Pinecone index kept in a dict. events records embed/upsert order across fakes."""

    def __init__(self, dim=DIM, fail_upsert_after=None, events=None):
        self.dim = dim
        self.vectors = {}  # (namespace, id) -> record
        self.deleted = []
        self.fail_upsert_after = fail_upsert_after
        self.upserts = 0
        self.stats_calls = 0
        self.events = events if events is not None else []

    def describe_index_stats(self):
        self.stats_calls += 1
        counts = {}
        for ns, _ in self.vectors:
            counts[ns] = counts.get(ns, 0) + 1
        return {"namespaces": {ns: {"vector_count": n} for ns, n in counts.items()}, "dimension": self.dim,
                "total_vector_count": len(self.vectors)}

    def upsert(self, vectors, namespace):
        self.upserts += 1
        if self.fail_upsert_after is not None and self.upserts > self.fail_upsert_after:
            raise RuntimeError("boom")
        assert len(vectors) <= main.UPSERT_BATCH
        self.events.append("upsert")
        for v in vectors:
            assert set(v["metadata"]) >= {"text", "source_file"}
            self.vectors[(namespace, v["id"])] = v

    def fetch(self, ids, namespace):
        return {"vectors": {i: {"id": i, "metadata": self.vectors[(namespace, i)]["metadata"]}
                            for i in ids if (namespace, i) in self.vectors}}

    def delete(self, ids, namespace):
        assert len(ids) <= main.DELETE_BATCH
        self.deleted.append((namespace, list(ids)))
        for i in ids:
            self.vectors.pop((namespace, i), None)


class FakeInference:
    def __init__(self, dim=DIM, rate_limit_times=0, events=None):
        self.dim = dim
        self.calls = []
        self.rate_limit_times = rate_limit_times
        self.events = events if events is not None else []

    def embed(self, model, inputs, parameters):
        if self.rate_limit_times:
            self.rate_limit_times -= 1
            raise RateLimited("429")
        assert len(inputs) <= main.EMBED_BATCH
        self.calls.append((model, len(inputs), parameters["input_type"]))
        self.events.append("embed")
        return [{"values": [0.1] * self.dim} for _ in inputs]


class FakePC:
    def __init__(self, dim=DIM, rate_limit_times=0, document_index=False, events=None):
        self.inference = FakeInference(dim, rate_limit_times, events)
        self.document_index = document_index

    def describe_index(self, name):
        """Shaped like Pinecone's answers: standard indexes also list a schema, of vector fields only."""
        if self.document_index:
            fields = {"chunk_text": {"type": "string", "full_text_search": {"language": "en"},
                                     "embed": {"model": "multilingual-e5-large"}}}
        else:
            fields = {"_values": {"type": "dense_vector", "dimension": DIM, "metric": "cosine"},
                      "_sparse_values": {"type": "sparse_vector"}}
        return {"name": name, "spec": {"serverless": {"schema": {"fields": fields}}}}


BASE_SETTINGS = dict(pinecone_api_key="pcsk_1234567890abcdefWXYZ", index_name="deen",
                     embedding_model="multilingual-e5-large", groq_api_key="gsk_abcdefghijklmnop1234",
                     groq_model="llama-3.3-70b-versatile")


def install(index=None, pc=None, **overrides):
    """Save working settings and hand the app fake Pinecone clients for them."""
    values = {**BASE_SETTINGS, **overrides}
    main.db.save_settings(values)
    settings = main.Settings(**values, min_score=None)
    res = main.Resources(settings=settings, pc=pc or FakePC(), index=index or FakeIndex(), llm=main.make_llm(settings))
    main.set_resources(res)
    return res


AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A fresh database and no cached clients, statistics or rate-limit counts for every test."""
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(main.db, "client", lambda: redis)
    monkeypatch.setattr(main, "PARTS_DIR", tmp_path / "upload-parts")
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)
    main.set_resources(None)
    main._stats_cache = (None, 0.0, {})
    main._recent_questions.clear()
    yield
    main.set_resources(None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture
def web_server(monkeypatch):
    """A local HTTP server; downloads from it are allowed, other private addresses stay blocked."""
    import threading
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    pages = {
        "/duas.json": (200, "text/plain", json.dumps([{"text": "A dua from the web."}]).encode()),
        "/page": (200, "text/html", b"<html>hi</html>"),
        "/big.txt": (200, "text/plain", b"x" * 2000),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/to-private":
                self.send_response(302)
                self.send_header("Location", "http://10.0.0.1/secret.json")
                self.end_headers()
                return
            status, content_type, body = pages.get(self.path, (404, "text/plain", b"missing"))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    check = main._public_url
    monkeypatch.setattr(main, "_public_url",
                        lambda url: urllib.parse.urlsplit(url) if urllib.parse.urlsplit(url).hostname == "127.0.0.1" else check(url))
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
