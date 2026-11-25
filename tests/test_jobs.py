"""Large uploads: files read as a stream, sent in parts, downloaded, and processed in the background."""

import io
import json
import time

import pytest

import db
import ingest
import main
from conftest import AUTH, FakeIndex, install


def wait_for(client, job_id, timeout=15):
    """Poll a job until it's done or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/admin/api/jobs/{job_id}", headers=AUTH).json()
        if job["state"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still {job['state']}")


def send_file(client, namespace, filename, data, language=None):
    """The admin page's flow: start a job, send the parts, finish, wait."""
    body = {"namespace": namespace, "filename": filename, "size": len(data), "language": language}
    job = client.post("/admin/api/jobs", headers=AUTH, json=body).json()
    for offset in range(0, len(data), job["chunk_bytes"]):
        part = data[offset:offset + job["chunk_bytes"]]
        r = client.put(f"/admin/api/jobs/{job['id']}/data", headers=AUTH, params={"offset": offset}, content=part)
        assert r.status_code == 200, r.text
    assert client.post(f"/admin/api/jobs/{job['id']}/finish", headers=AUTH).status_code == 200
    return wait_for(client, job["id"])


@pytest.fixture
def small_parts(monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_CHUNK_BYTES", 1000)


# ---------------------------------------------------------------- reading files as a stream


def test_plain_text_is_split_in_blocks(monkeypatch):
    monkeypatch.setattr(ingest, "TEXT_BLOCK_CHARS", 500)
    text = "".join(f"Paragraph {n}. " * 20 + "\n\n" for n in range(50))
    blocks = list(ingest._text_blocks(io.StringIO(text)))
    assert len(blocks) > 5 and "".join(blocks) == text
    passages = list(ingest.FileReader("big.txt", io.BytesIO(text.encode()), len(text)))
    assert len(passages) > 5 and all(len(p.text) <= ingest.CHUNK_CHARS for p in passages)
    assert "Paragraph 0." in passages[0].text and "Paragraph 49." in passages[-1].text


def test_records_are_read_as_they_are_needed():
    lines = b'{"text": "one"}\n{"text": "two"}\n{bad json\n'
    reader = iter(ingest.FileReader("r.jsonl", io.BytesIO(lines), len(lines)))
    assert [next(reader).text, next(reader).text] == ["one", "two"]  # read before the bad line is reached
    with pytest.raises(ingest.IngestError, match="Line 3"):
        next(reader)


def test_unsupported_and_oversized_json_are_refused_before_reading(monkeypatch):
    with pytest.raises(ingest.IngestError, match="can't be uploaded"):
        ingest.FileReader("x.exe", io.BytesIO(), 10)
    with pytest.raises(ingest.IngestError, match=".jsonl"):
        ingest.FileReader("big.json", io.BytesIO(), ingest.MAX_JSON_BYTES + 1)


def test_stopping_early_leaves_the_stream_open():
    stream = io.BytesIO(b"a\nb\nc\n")
    lines = ingest._lines(stream)
    next(lines)
    lines.close()
    assert not stream.closed


def test_file_ids_are_the_same_for_bytes_and_streams():
    stream = io.BytesIO(b"content")
    assert ingest.file_id_for("a.txt", b"content") == ingest.file_id_for("a.txt", stream)
    assert stream.tell() == 0


# ---------------------------------------------------------------- files sent in parts


def test_a_file_sent_in_parts_is_processed_in_the_background(client, small_parts):
    index = FakeIndex()
    install(index=index)
    text = ("Line number %d of a large file. " * 400) % tuple(range(400))
    job = send_file(client, "tafsir", "big.txt", text.encode())
    assert job["state"] == "done", job
    stored = job["result"]["file"]["passages"]
    assert stored == job["passages"] > 1 and len(index.vectors) == stored
    assert db.list_uploads("deen")[0]["size_bytes"] == len(text.encode())
    assert not main._part_path(job["id"]).exists()  # the parts are deleted afterwards


def test_parts_must_arrive_in_order_and_fit_the_size(client, small_parts):
    install()
    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "filename": "f.txt", "size": 1500}).json()
    url = f"/admin/api/jobs/{job['id']}/data"
    assert client.put(url, headers=AUTH, params={"offset": 0}, content=b"a" * 1000).json()["received"] == 1000

    r = client.put(url, headers=AUTH, params={"offset": 0}, content=b"a" * 1000)  # a resent part
    assert r.status_code == 409 and r.json()["detail"]["received"] == 1000
    assert client.put(url, headers=AUTH, params={"offset": 1000}, content=b"a" * 1001).status_code == 413  # too big
    r = client.put(url, headers=AUTH, params={"offset": 1000}, content=b"b" * 600)
    assert r.status_code == 413  # more than the declared size

    r = client.post(f"/admin/api/jobs/{job['id']}/finish", headers=AUTH)
    assert r.status_code == 400 and "1,000 of 1,500 bytes" in r.json()["detail"]
    client.put(url, headers=AUTH, params={"offset": 1000}, content=b"b" * 500)
    assert client.post(f"/admin/api/jobs/{job['id']}/finish", headers=AUTH).status_code == 200
    assert client.post(f"/admin/api/jobs/{job['id']}/finish", headers=AUTH).status_code == 409  # not twice
    assert wait_for(client, job["id"])["state"] == "done"


def test_unusable_uploads_are_refused_up_front(client, monkeypatch):
    install()
    start = lambda **body: client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", **body})  # noqa: E731
    assert start(filename="a.exe", size=10).status_code == 400
    assert start(filename="a.txt").status_code == 422
    assert start(filename="a.txt", size=10, namespace="all").status_code == 422
    monkeypatch.setattr(main, "MAX_LARGE_UPLOAD_BYTES", 100)
    assert start(filename="a.txt", size=101).status_code == 413
    assert client.get("/admin/api/jobs/nope", headers=AUTH).status_code == 404
    assert client.post("/admin/api/jobs", json={"namespace": "x", "filename": "a.txt", "size": 1}).status_code == 401


def test_a_file_with_nothing_to_index_fails_with_the_reason(client, small_parts):
    install()
    job = send_file(client, "x", "empty.txt", b"   \n\n  ")
    assert job["state"] == "failed" and "no text" in job["error"]


def test_a_stalled_job_is_reported_as_failed(client, monkeypatch):
    install()
    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "filename": "f.txt", "size": 5}).json()
    with monkeypatch.context() as m:  # as if its server stopped 20 minutes ago, mid-way
        m.setattr(db, "_now", lambda: main._iso_ago(minutes=20))
        db.update_job(job["id"], state="processing")
    status = client.get(f"/admin/api/jobs/{job['id']}", headers=AUTH).json()
    assert status["state"] == "failed" and "stopped" in status["error"]


def test_old_jobs_and_their_parts_are_forgotten(client, monkeypatch):
    install()
    old = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "filename": "f.txt", "size": 5}).json()
    with monkeypatch.context() as m:
        m.setattr(db, "_now", lambda: main._iso_ago(hours=25))
        db.update_job(old["id"])
    assert main._part_path(old["id"]).exists()
    client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "filename": "g.txt", "size": 5})
    assert db.get_job(old["id"]) is None and not main._part_path(old["id"]).exists()


# ---------------------------------------------------------------- web addresses


def test_a_web_address_is_downloaded_in_the_background(client, web_server):
    index = FakeIndex()
    install(index=index)
    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "duas", "url": web_server + "/duas.json"}).json()
    assert job["state"] == "downloading" and job["filename"] is None
    job = wait_for(client, job["id"])
    assert job["state"] == "done" and job["filename"] == "duas.json" and job["received"] == job["size"] > 0
    assert next(iter(index.vectors.values()))["metadata"]["source_url"] == web_server + "/duas.json"

    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "duas", "url": web_server + "/page"}).json()
    job = wait_for(client, job["id"])
    assert job["state"] == "failed" and "web page" in job["error"]


def test_a_private_web_address_is_refused_straight_away(client):
    install()
    r = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "duas", "url": "http://10.0.0.1/a.json"})
    assert r.status_code == 400 and "private or local" in r.json()["detail"]


def test_background_work_is_refused_on_vercel(client, monkeypatch):
    """Vercel stops a function within minutes of its request, so a job there would be cut off partway."""
    install()
    monkeypatch.setenv("VERCEL", "1")
    for path, body in [("/admin/api/jobs", {"namespace": "x", "filename": "a.txt", "size": 10}),
                       ("/admin/api/files/a-0123456789ab/ocr?namespace=x", None)]:
        r = client.post(path, headers=AUTH, json=body)
        assert r.status_code == 503 and "same .env" in r.json()["detail"], path


def test_a_download_over_the_limit_fails(client, web_server, monkeypatch):
    install()
    monkeypatch.setattr(main, "MAX_LARGE_UPLOAD_BYTES", 1000)
    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "url": web_server + "/big.txt"}).json()
    job = wait_for(client, job["id"])
    assert job["state"] == "failed" and "at most" in job["error"]


def test_records_from_a_large_upload_keep_their_citations(client, small_parts):
    index = FakeIndex()
    install(index=index)
    lines = "\n".join(json.dumps({"text": f"Hadith {n}", "collection": "Sahih Muslim", "hadith_number": n}) for n in range(1, 301))
    job = send_file(client, "muslim", "muslim.jsonl", lines.encode())
    assert job["state"] == "done" and job["result"]["file"]["passages"] == 300
    numbers = sorted(v["metadata"]["hadith_number"] for v in index.vectors.values())
    assert numbers == list(range(1, 301))


def test_scanned_pdfs_are_read_with_ocr_and_report_pages(client, ocr_space):
    from conftest import scanned_pdf
    install()
    job = send_file(client, "fiqh", "Scan.pdf", scanned_pdf(2), language="bn")
    assert job["state"] == "done", job["error"]
    assert (job["pages"], job["pages_read"], job["ocr_pages"]) == (2, 2, 2)
    assert job["result"]["ocr_pages"] == 2 and job["result"]["warning"] is None
    assert job["result"]["file"]["passages"] == 2 and [c[0] for c in ocr_space.calls] == [3, 3]
