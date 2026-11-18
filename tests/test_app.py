"""The API: citations, admin sign-in, credentials, uploads, readers and limits. Pinecone and Groq are faked."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import db
import main
from conftest import AUTH, FakeIndex, FakePC, install


def upload(client, namespace, filename, content, mime="text/plain"):
    data = content if isinstance(content, bytes) else content.encode()
    return client.post("/admin/api/files", headers=AUTH, data={"namespace": namespace}, files={"file": (filename, data, mime)})


@pytest.fixture
def fake_groq(monkeypatch):
    calls = []

    class FakeGroq:
        def __init__(self, api_key, timeout, max_retries):
            self.models = SimpleNamespace(retrieve=self.retrieve)

        def retrieve(self, model):
            calls.append(model)
            if model == "missing":
                raise main.GroqNotFoundError.__new__(main.GroqNotFoundError)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main, "Groq", FakeGroq)
    return calls


# ---------------------------------------------------------------- citations


@pytest.mark.parametrize("namespace, fields, expected", [
    ("quran", {"surah": 2, "ayah": 153}, "Quran (Surah 2, Ayah 153)"),
    ("bukhari", {"collection": "Sahih al-Bukhari", "hadith_number": 52, "grade": "Sahih"}, "Sahih al-Bukhari 52, graded Sahih"),
    ("bukhari", {"collection": "Sahih al-Bukhari", "hadith_number": 52, "book": "Book of Faith", "grade": "Sahih"},
     "Sahih al-Bukhari 52 (Book of Faith), graded Sahih"),
    ("abu_dawud", {"hadith_number": 10, "grade": "Da'if"}, "Abu Dawud 10, graded Da'if"),
])
def test_citations(namespace, fields, expected):
    assert main.format_reference(namespace, fields) == expected


# ---------------------------------------------------------------- admin sign-in


def test_admin_needs_the_token(client):
    install()
    assert client.get("/admin/api/settings").status_code == 401
    assert client.get("/admin/api/settings", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/admin/api/settings", headers={"Authorization": "Basic " + AUTH["Authorization"][7:]}).status_code == 401
    body = client.get("/admin/api/settings", headers=AUTH).json()
    assert body["groq_api_key"] == "gsk_…1234" and body["pinecone_api_key"] == "pcsk…WXYZ" and body["missing"] == []
    assert "/admin/api" not in json.dumps(client.get("/openapi.json").json())


@pytest.mark.parametrize("token, reason", [("", "isn't set"), ("short-guessable", "shorter than 24")])
def test_missing_or_short_admin_token_turns_admin_off(client, monkeypatch, token, reason):
    monkeypatch.setenv("ADMIN_TOKEN", token)
    response = client.get("/admin/api/settings", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403 and reason in response.json()["detail"]


# ---------------------------------------------------------------- credentials


def test_credentials_are_tested_before_saving(client, fake_groq, monkeypatch):
    install()
    new_index = FakeIndex()
    wrong_dimension = {"on": False}

    def fake_connect(api_key, index_name):
        if index_name == "nope":
            raise main.NotFoundException("no index", 404)
        return FakePC(dim=8 if wrong_dimension["on"] else 4), new_index

    monkeypatch.setattr(main, "connect_pinecone", fake_connect)

    r = client.put("/admin/api/settings", headers=AUTH, json={"groq_model": "llama-3.3-70b-versatile", "groq_api_key": ""})
    assert r.json()["changed"] == [] and not fake_groq

    r = client.put("/admin/api/settings", headers=AUTH, json={"groq_api_key": "gsk_NEWKEY0000000000zzzz", "groq_model": "llama-x"})
    assert r.status_code == 200 and r.json()["changed"] == ["groq_api_key", "groq_model"]
    assert db.get_settings()["groq_model"] == "llama-x" and main.get_resources().settings.groq_model == "llama-x"

    r = client.put("/admin/api/settings", headers=AUTH, json={"groq_model": "missing"})
    assert r.status_code == 400 and "no model named 'missing'" in r.json()["detail"]
    r = client.put("/admin/api/settings", headers=AUTH, json={"index_name": "nope"})
    assert r.status_code == 400 and "no index named 'nope'" in r.json()["detail"]
    wrong_dimension["on"] = True
    r = client.put("/admin/api/settings", headers=AUTH, json={"embedding_model": "wrong-dim"})
    wrong_dimension["on"] = False
    assert r.status_code == 400 and "8-dimensional" in r.json()["detail"]
    assert db.get_settings()["embedding_model"] == "multilingual-e5-large"

    r = client.put("/admin/api/settings", headers=AUTH, json={"index_name": "deen-2", "pinecone_api_key": "pcsk_new_key_000000000000"})
    assert r.status_code == 200 and main.get_resources().index is new_index
    assert client.put("/admin/api/settings", headers=AUTH, json={"groq_model": "llama-z"}).status_code == 200
    assert main.get_resources().index is new_index  # a Groq-only change keeps the Pinecone connection
    assert client.put("/admin/api/settings", headers=AUTH, json={"groq_api_key": "has space"}).status_code == 422


def test_a_document_index_is_refused(client, monkeypatch):
    """Finding 1: a Pinecone document index refuses Deen's vectors, so it's rejected up front."""
    install()
    monkeypatch.setattr(main, "connect_pinecone", lambda key, name: (FakePC(document_index=True), FakeIndex()))
    r = client.put("/admin/api/settings", headers=AUTH, json={"index_name": "preach"})
    assert r.status_code == 400 and "document index" in r.json()["detail"]
    assert db.get_settings()["index_name"] == "deen"

    pc = FakePC(document_index=True)
    install(pc=pc)  # already saved before this check existed
    r = upload(client, "duas", "a.txt", "A dua.")
    assert r.status_code == 400 and "document index" in r.json()["detail"]
    assert pc.inference.calls == []  # no embedding tokens spent


def test_a_credentials_change_reaches_other_processes(monkeypatch):
    """Finding 6: settings saved by another worker process are picked up on the next request."""
    install()
    monkeypatch.setattr(main, "connect_pinecone", lambda key, name: (FakePC(), FakeIndex()))
    db.save_settings({"groq_model": "changed-elsewhere"})  # as another process's admin save would
    assert main.get_resources().settings.groq_model == "changed-elsewhere"


def test_setup_from_an_empty_database(client, fake_groq, monkeypatch):
    assert client.get("/texts").status_code == 503
    assert client.post("/query", json={"query": "hi"}).status_code == 503
    body = client.get("/admin/api/settings", headers=AUTH).json()
    assert body["missing"] == ["Groq API key", "Pinecone API key", "Pinecone index name"]

    r = client.put("/admin/api/settings", headers=AUTH, json={"index_name": "deen"})
    assert r.status_code == 400 and "Enter the Pinecone API key" in r.json()["detail"]
    r = client.put("/admin/api/settings", headers=AUTH, json={"groq_api_key": "gsk_firstkey000000000000"})
    assert "Pinecone API key and Pinecone index name are entered" in r.json()["warning"]
    with pytest.raises(main.NotConfiguredError):
        main.get_resources()

    monkeypatch.setattr(main, "connect_pinecone", lambda key, name: (FakePC(), FakeIndex()))
    r = client.put("/admin/api/settings", headers=AUTH, json={"pinecone_api_key": "pcsk_firstkey00000000000", "index_name": "deen"})
    assert r.status_code == 200 and r.json()["warning"] is None
    assert client.get("/texts").status_code == 200


def test_env_credentials_are_copied_once_and_the_app_starts_without_pinecone(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fromenv000000000000")
    monkeypatch.setenv("PINECONE_API_KEY", "pcsk_fromenv0000000000")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "envindex")

    def pinecone_down(key, name):
        raise RuntimeError("pinecone down")

    monkeypatch.setattr(main, "connect_pinecone", pinecone_down)
    with TestClient(main.app) as client:  # runs the startup code
        assert client.get("/health").status_code == 200
        assert db.get_settings()["index_name"] == "envindex"
        r = client.get("/texts")
        assert r.status_code == 502 and "envindex" in str(r.json()["detail"])
    monkeypatch.setenv("GROQ_API_KEY", "gsk_changed")
    main.import_env_credentials()
    assert db.get_settings()["groq_api_key"] == "gsk_fromenv000000000000"


# ---------------------------------------------------------------- uploads


def test_upload_list_and_delete(client):
    index, pc = FakeIndex(), FakePC(rate_limit_times=2)
    install(index=index, pc=pc)
    text = ("Verse text number %d. " * 6000) % tuple(range(6000))
    r = upload(client, "tafsir", "C:\\x\\My Tafsir.txt", text)
    assert r.status_code == 200
    n = r.json()["file"]["passages"]
    assert n > main.EMBED_BATCH and len(index.vectors) == n
    assert index.vectors[("tafsir", r.json()["file"]["file_id"] + "#0")]["metadata"]["source_file"] == "My Tafsir.txt"

    r = upload(client, "muslim", "muslim.json", json.dumps([{"text": "Hadith", "collection": "Sahih Muslim", "hadith_number": 5}, {"x": 1}]))
    assert r.json()["skipped_records"] == 1
    body = client.get("/admin/api/files", headers=AUTH).json()
    assert len(body["files"]) == 2 and body["total_vector_count"] == n + 1

    for bad in ["all", "", "bad name", "-x"]:
        assert upload(client, bad, "a.txt", "hi").status_code == 422
    assert upload(client, "x", "a.exe", "hi").status_code == 400

    tafsir = next(f for f in body["files"] if f["namespace"] == "tafsir")
    r = client.delete(f"/admin/api/files/{tafsir['file_id']}", headers=AUTH, params={"namespace": "tafsir"})
    assert r.json() == {"deleted_passages": n} and not any(ns == "tafsir" for ns, _ in index.vectors)
    assert client.delete(f"/admin/api/files/{tafsir['file_id']}", headers=AUTH, params={"namespace": "tafsir"}).status_code == 404


def test_uploads_are_embedded_and_stored_batch_by_batch(client):
    """Finding 3: only one batch of vectors is held at a time."""
    events = []
    install(index=FakeIndex(events=events), pc=FakePC(events=events))
    text = ("Word %d here. " * 20000) % tuple(range(20000))
    assert upload(client, "x", "big.txt", text).status_code == 200
    assert events.count("embed") > 1
    assert events.index("upsert") < events.index("embed", 1)  # stored before the next batch is embedded


def test_a_failed_new_upload_leaves_nothing_behind(client):
    index = FakeIndex(fail_upsert_after=1)
    install(index=index)
    r = upload(client, "x", "f.txt", ("Word %d here. " * 8000) % tuple(range(8000)))
    assert r.status_code == 502 and "wasn't added" in r.json()["detail"]
    assert not index.vectors and db.list_uploads("deen") == []


def test_a_failed_reupload_keeps_the_earlier_copy(client):
    """Finding 2: re-uploading the same file reuses its ids, so a failure must not delete them."""
    index = FakeIndex()
    install(index=index)
    text = ("Word %d here. " * 8000) % tuple(range(8000))
    n = upload(client, "x", "f.txt", text).json()["file"]["passages"]
    index.fail_upsert_after = index.upserts + 1
    assert upload(client, "x", "f.txt", text).status_code == 502
    assert len(index.vectors) == n and db.list_uploads("deen")[0]["passages"] == n


def test_uploading_an_edited_file_replaces_the_earlier_version(client, monkeypatch):
    """Finding 4: same name, new content: the old passages go, and the file keeps its place in the reader."""
    times = iter(f"2026-01-01T00:00:0{i}+00:00" for i in range(10))
    monkeypatch.setattr(db, "_now", lambda: next(times))
    index = FakeIndex()
    install(index=index)
    steps = [{"text": "Step one."}, {"text": "Step two."}]
    first = upload(client, "namaz", "namaz.json", json.dumps(steps)).json()["file"]
    upload(client, "namaz", "a-later.json", json.dumps([{"text": "Later file."}]))
    upload(client, "namaz", "namaz.json", json.dumps(steps))  # unchanged: keeps its upload time too

    edited = upload(client, "namaz", "namaz.json", json.dumps(steps + [{"text": "Step three, fixed."}])).json()
    assert edited["replaced_versions"] == 1
    rows = [f for f in db.list_uploads("deen") if f["filename"] == "namaz.json"]
    assert len(rows) == 1 and rows[0]["passages"] == 3 and rows[0]["uploaded_at"] == first["uploaded_at"]
    assert not any(vid.startswith(first["file_id"]) for _, vid in index.vectors)
    texts = [client.get("/read/namaz", params={"position": p}).json()["item"]["text"] for p in range(4)]
    assert texts == ["Step one.", "Step two.", "Step three, fixed.", "Later file."]


def test_dimension_mismatch_stops_an_upload(client):
    install(index=FakeIndex(dim=8))
    r = upload(client, "x", "f.txt", "hello")
    assert r.status_code == 500 and "8-dimensional" in str(r.json()["detail"])


def test_a_rate_limited_question_fails_fast():
    install(pc=FakePC(rate_limit_times=1))
    with pytest.raises(main.RetrievalError):
        main.embed_query(main.get_resources(), "q")


# ---------------------------------------------------------------- readers


def test_readers(client):
    index = FakeIndex()
    install(index=index)
    assert [r["total"] for r in client.get("/read").json()["readers"]] == [0, 0]
    assert client.get("/read/quran").status_code == 404

    duas = [
        {"title": "For good in both worlds", "arabic": "رَبَّنَا آتِنَا", "transliteration": "Rabbana atina",
         "text": "Our Lord, give us good in this world", "surah": 2, "ayah": 201, "category": "General"},
        {"text": "بِاسْمِكَ اللَّهُمَّ", "arabic": "بِاسْمِكَ اللَّهُمَّ", "collection": "Sahih al-Bukhari", "hadith_number": 6324, "grade": "Sahih"},
    ]
    upload(client, "duas", "a.json", json.dumps(duas))
    upload(client, "namaz", "namaz.json", json.dumps([{"section": "Salah", "title": "Takbir", "text": "Say Allahu akbar.", "hadith_number": 3}]))

    item = client.get("/read/duas", params={"position": 0}).json()["item"]
    assert (item["section"], item["title"], item["reference"]) == ("General", "For good in both worlds", "Quran (Surah 2, Ayah 201)")
    assert item["details"] == {"source_file": "a.json"}
    item = client.get("/read/duas", params={"position": 1}).json()["item"]
    assert item["arabic"] is None and item["reference"] == "Sahih al-Bukhari 6324, graded Sahih"
    assert client.get("/read/duas", params={"position": 2}).json()["item"]["position"] == 0  # wraps around
    item = client.get("/read/namaz", params={"position": 0}).json()["item"]
    assert item["reference"] is None and item["details"] == {"hadith_number": 3, "source_file": "namaz.json"}

    del index.vectors[next(k for k in index.vectors if k[0] == "duas")]
    assert client.get("/read/duas", params={"position": 0}).status_code == 404


# ---------------------------------------------------------------- limits and caching


def test_each_visitor_gets_a_limited_number_of_questions():
    """Finding 5."""
    visitor = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))
    for _ in range(main.QUERY_LIMIT_PER_MINUTE):
        main.limit_questions(visitor)
    with pytest.raises(HTTPException) as refused:
        main.limit_questions(visitor)
    assert refused.value.status_code == 429 and "Retry-After" in refused.value.headers
    main.limit_questions(SimpleNamespace(client=SimpleNamespace(host="198.51.100.1")))  # others are unaffected


def test_the_question_endpoint_is_limited(client):
    statuses = {client.post("/query", json={"query": "hi"}).status_code for _ in range(main.QUERY_LIMIT_PER_MINUTE)}
    assert statuses == {503}  # not set up, but counted
    assert client.post("/query", json={"query": "hi"}).status_code == 429


def test_index_statistics_are_reused_for_a_minute():
    """Finding 9."""
    index = FakeIndex()
    main.cached_index_stats(index)
    main.cached_index_stats(index)
    assert index.stats_calls == 1
    main.cached_index_stats(FakeIndex())  # another index isn't served from the cache
    main._stats_cache = (index, main.time.monotonic() - main.STATS_TTL_SECONDS - 1, {})
    main.cached_index_stats(index)
    assert index.stats_calls == 2


# ---------------------------------------------------------------- upload from a web address


@pytest.mark.parametrize("url", [
    "ftp://example.org/a.json", "not a url", "http://127.0.0.1/a.json", "http://localhost/a.json",
    "http://10.0.0.5/a.json", "http://192.168.1.2/a.json", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/a.json", "http://[::ffff:127.0.0.1]/a.json",
])
def test_web_addresses_must_be_public_http(url):
    with pytest.raises(main.AdminRequestError):
        main._public_url(url)


def test_a_public_address_is_allowed():
    assert main._public_url("https://8.8.8.8/duas.json").hostname == "8.8.8.8"


@pytest.mark.parametrize("url, content_type, disposition, expected", [
    ("https://x.org/data/duas.json", "text/plain", None, "duas.json"),  # e.g. GitHub raw files
    ("https://x.org/download?id=7", "application/octet-stream", "Namaz steps.csv", "Namaz steps.csv"),
    ("https://x.org/api/duas", "application/json", None, "duas.json"),
    ("https://x.org/", "application/pdf", None, "x.org.pdf"),
])
def test_download_names(url, content_type, disposition, expected):
    assert main._download_name(url, content_type, disposition) == expected


@pytest.mark.parametrize("content_type, message", [("text/html", "web page"), ("image/png", "image/png")])
def test_downloads_that_are_not_files_are_refused(content_type, message):
    with pytest.raises(main.AdminRequestError, match=message):
        main._download_name("https://x.org/thing", content_type, None)


def test_fetching_files_from_a_web_server(web_server, monkeypatch):
    name, data = main.fetch_url(web_server + "/duas.json")
    assert name == "duas.json" and b"A dua from the web." in data
    for path, message in [("/missing.json", "HTTP 404"), ("/page", "web page"), ("/to-private", "private or local")]:
        with pytest.raises(main.AdminRequestError, match=message):
            main.fetch_url(web_server + path)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1000)
    with pytest.raises(HTTPException) as too_big:
        main.fetch_url(web_server + "/big.txt")
    assert too_big.value.status_code == 413


def test_upload_from_a_web_address(client, monkeypatch):
    index = FakeIndex()
    install(index=index)
    content = {"v": [{"text": "First version."}]}
    monkeypatch.setattr(main, "fetch_url", lambda url: ("duas.json", json.dumps(content["v"]).encode()))
    url = "https://user:secret@example.org/files/duas.json?token=abc#top"

    r = client.post("/admin/api/files/from-url", headers=AUTH, json={"url": url, "namespace": "duas"})
    assert r.status_code == 200 and r.json()["file"]["filename"] == "duas.json"
    metadata = next(iter(index.vectors.values()))["metadata"]
    assert metadata["source_url"] == "https://example.org/files/duas.json"  # no password, token or fragment

    content["v"] = [{"text": "Second version."}, {"text": "Added."}]
    r = client.post("/admin/api/files/from-url", headers=AUTH, json={"url": url, "namespace": "duas"})
    assert r.json()["replaced_versions"] == 1 and len(index.vectors) == 2
    assert client.post("/admin/api/files/from-url", headers=AUTH, json={"url": url, "namespace": "all"}).status_code == 422
    assert client.post("/admin/api/files/from-url", json={"url": url, "namespace": "duas"}).status_code == 401
