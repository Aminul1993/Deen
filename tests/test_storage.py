"""Books kept in Vercel Blob (storage.py), with the SDK and Blob's delivery URLs faked."""

import io
import re
import urllib.error
import urllib.parse
from email.message import Message
from types import SimpleNamespace

import pytest
from vercel.blob import sync as real_blob

import db
import main
import storage
from conftest import AUTH, FakeIndex, install, tiny_pdf

TOKEN = "vercel_blob_rw_teststore_secret0123"
BOOK = tiny_pdf(["Page one about patience.", "Page two about charity."])


class FakeBlob:
    """The vercel.blob.sync calls storage.py makes, kept in a dict, and Blob's delivery URLs (open)."""

    BlobError = real_blob.BlobError
    BlobServiceRateLimited = real_blob.BlobServiceRateLimited
    BlobServiceNotAvailable = real_blob.BlobServiceNotAvailable

    def __init__(self):
        self.files = {}  # delivery URL -> bytes
        self.calls = []
        self.fail = []  # errors the next uploads raise, in turn
        self.requests = []  # (url, headers) of every read
        self.status = None  # make every read answer this HTTP error
        self.suffixes = 0

    def _url(self, pathname, access, add_random_suffix):
        assert add_random_suffix  # pathnames are never reused (see storage.upload)
        self.suffixes += 1
        stem, dot, extension = pathname.rpartition(".")
        return f"https://teststore.{access}.blob.vercel-storage.com/{urllib.parse.quote(stem)}-r{self.suffixes}{dot}{extension}"

    def put_blob(self, pathname, body, *, access, content_length=None, content_type=None, add_random_suffix=False):
        if self.fail:
            raise self.fail.pop(0)
        data = body.read(content_length)
        assert len(data) == content_length
        url = self._url(pathname, access, add_random_suffix)
        self.files[url] = data
        self.calls.append(("put", pathname, access, content_type))
        return SimpleNamespace(url=url)

    def multipart_upload_blob(self, pathname, *, access, content_type=None, add_random_suffix=False):
        fake = self

        class Upload:
            def __enter__(self):
                self.parts = []
                return self

            def upload_part(self, part):
                self.parts.append(bytes(part))

            def __exit__(self, kind, value, traceback):
                if kind is None:
                    url = fake._url(pathname, access, add_random_suffix)
                    fake.files[url] = b"".join(self.parts)
                    fake.calls.append(("multipart", pathname, [len(p) for p in self.parts]))
                    self.result = SimpleNamespace(url=url)
                return False

        return Upload()

    def delete_blob(self, url):
        self.files.pop(url, None)
        self.calls.append(("delete", url))

    def open(self, request):
        """Blob's delivery URLs: the token for private blobs, and byte ranges."""
        url = request.full_url
        headers = dict(request.header_items())
        self.requests.append((url, headers))
        if self.status:
            raise urllib.error.HTTPError(url, self.status, "error", Message(), None)
        if ".private." in url and headers.get("Authorization") != f"Bearer {TOKEN}":
            raise urllib.error.HTTPError(url, 403, "Forbidden", Message(), None)
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", Message(), None)
        data = self.files[url]
        reply = Message()
        reply["Accept-Ranges"] = "bytes"
        reply["ETag"] = '"abc"'
        if match := re.fullmatch(r"bytes=(\d+)-(\d+)", headers.get("Range", "")):
            start, end = int(match[1]), int(match[2])
            if start >= len(data):
                reply["Content-Range"] = f"bytes */{len(data)}"
                raise urllib.error.HTTPError(url, 416, "Range Not Satisfiable", reply, None)
            data, status = data[start:end + 1], 206
            reply["Content-Range"] = f"bytes {start}-{start + len(data) - 1}/{len(self.files[url])}"
        else:
            status = 200
        reply["Content-Length"] = str(len(data))
        body = io.BytesIO(data)
        return SimpleNamespace(status=status, headers=reply, read=body.read, close=body.close)


@pytest.fixture
def blob_store(monkeypatch):
    fake = FakeBlob()
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", TOKEN)
    monkeypatch.setattr(storage, "blob", fake)
    monkeypatch.setattr(storage, "_open", fake.open)
    return fake


def upload(client, filename="Bahishti_Zewar.pdf", content=BOOK, namespace="fiqh"):
    return client.post("/admin/api/files", headers=AUTH, data={"namespace": namespace, "language": "en"},
                       files={"file": (filename, content, "application/pdf")})


def test_pdfs_are_kept_in_blob_and_read_through_the_app(client, blob_store):
    install(index=FakeIndex())
    r = upload(client)
    assert r.status_code == 200 and r.json()["warning"] is None
    file_id = r.json()["file"]["file_id"]
    assert blob_store.calls == [("put", f"books/deen/fiqh/{file_id}.pdf", "private", "application/pdf")]
    assert not main.BOOKS_DIR.exists()  # nothing on the server's disk
    row = db.get_upload("deen", "fiqh", file_id)
    assert row["book"] and row["book_url"] == f"https://teststore.private.blob.vercel-storage.com/books/deen/fiqh/{file_id}-r1.pdf"

    files = client.get("/admin/api/files", headers=AUTH).json()
    assert files["book_storage"] == "in Vercel Blob (private store)" and files["files"][0]["book"] is True
    [book] = client.get("/books/list").json()["books"]
    assert book["pdf"] == f"/books/fiqh/{file_id}.pdf"  # readers never see the Blob address

    r = client.get(book["pdf"])
    assert r.status_code == 200 and r.content == BOOK
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    assert r.headers["cache-control"] == "public, max-age=86400"
    r = client.get(book["pdf"], headers={"Range": "bytes=0-7"})
    assert r.status_code == 206 and r.content == BOOK[:8]
    assert r.headers["content-range"] == f"bytes 0-7/{len(BOOK)}" and r.headers["accept-ranges"] == "bytes"
    url, headers = blob_store.requests[-1]
    assert url == row["book_url"] and headers["Authorization"] == f"Bearer {TOKEN}" and headers["Range"] == "bytes=0-7"
    assert client.get(book["pdf"], headers={"Range": f"bytes={len(BOOK) + 10}-{len(BOOK) + 20}"}).status_code == 416

    state = {"query": "patience", "history": [], "search_query": "patience", "namespace": "fiqh", "top_k": 5,
             "context": [], "sources": [], "answer": ""}
    assert all(s["book"]["id"] == file_id for s in main.retrieve(main.get_resources(), state)["sources"])  # answers link to it

    assert client.delete(f"/admin/api/files/{file_id}", headers=AUTH, params={"namespace": "fiqh"}).status_code == 200
    assert blob_store.calls[-1] == ("delete", row["book_url"]) and not blob_store.files
    assert client.get(book["pdf"]).status_code == 404


def test_large_pdfs_go_up_in_parts_and_replaced_ones_are_deleted(client, blob_store, monkeypatch):
    monkeypatch.setattr(storage, "MULTIPART_BYTES", 1000)
    monkeypatch.setattr(storage, "PART_BYTES", 700)
    install()
    big = tiny_pdf([f"Page {n} of a long book." for n in range(1, 12)])
    first = upload(client, "book.pdf", big).json()["file"]
    kind, _, sizes = blob_store.calls[-1]
    assert kind == "multipart" and sum(sizes) == len(big) and all(size == 700 for size in sizes[:-1]) and len(sizes) > 1
    old_url = db.get_upload("deen", "fiqh", first["file_id"])["book_url"]
    assert blob_store.files[old_url] == big

    edited = upload(client, "book.pdf", tiny_pdf(["A corrected page."])).json()
    assert edited["replaced_versions"] == 1 and ("delete", old_url) in blob_store.calls
    assert list(blob_store.files) == [db.get_upload("deen", "fiqh", edited["file"]["file_id"])["book_url"]]


def test_the_same_pdf_uploaded_again_gets_a_new_blob_and_the_old_one_goes(client, blob_store):
    install()
    file_id = upload(client).json()["file"]["file_id"]
    first = db.get_upload("deen", "fiqh", file_id)["book_url"]
    upload(client)  # identical content, so the same file id
    second = db.get_upload("deen", "fiqh", file_id)["book_url"]
    assert second != first and list(blob_store.files) == [second] and ("delete", first) in blob_store.calls

    blob_store.fail = [real_blob.BlobError("Access denied", status_code=403)]
    r = upload(client)  # Blob refuses this time: the copy already kept still serves
    assert r.json()["file"]["book"] is True and r.json()["warning"] is None
    assert db.get_upload("deen", "fiqh", file_id)["book_url"] == second and list(blob_store.files) == [second]
    assert client.get(f"/books/fiqh/{file_id}.pdf").content == BOOK


def test_blob_failures_are_retried_or_leave_the_upload_without_a_book(client, blob_store):
    install()
    blob_store.fail = [real_blob.BlobServiceRateLimited(1), real_blob.BlobServiceNotAvailable("down")]
    assert upload(client, "a.pdf").json()["file"]["book"] is True  # third try worked

    blob_store.fail = [real_blob.BlobError("This store does not exist.", status_code=403)]
    r = upload(client, "b.pdf", tiny_pdf(["Another book."]))
    assert r.status_code == 200 and r.json()["file"]["passages"] == 1 and r.json()["file"]["book"] is False
    assert "Vercel Blob refused it" in r.json()["warning"]
    assert [b["filename"] for b in client.get("/books/list").json()["books"]] == ["a.pdf"]


def test_blob_reads_that_fail(client, blob_store):
    install()
    file_id = upload(client).json()["file"]["file_id"]
    pdf = f"/books/fiqh/{file_id}.pdf"
    blob_store.files.clear()  # deleted in the dashboard, say
    r = client.get(pdf)
    assert r.status_code == 404 and "missing from storage" in r.json()["detail"]
    blob_store.status = 500
    assert client.get(pdf).status_code == 502

    # The token goes only to Blob's own hosts, whatever the database says.
    blob_store.status, blob_store.requests = None, []
    row = db.get_upload("deen", "fiqh", file_id)
    db.save_upload("deen", "fiqh", file_id, row["filename"], row["passages"], row["size_bytes"], book=True,
                   book_url="https://attacker.example/books/x.pdf")
    assert client.get(pdf).status_code == 502 and blob_store.requests == []
    with pytest.raises(storage.BlobUnavailable):
        storage._checked("http://teststore.private.blob.vercel-storage.com/x.pdf")


def test_books_kept_on_disk_before_blob_are_still_served(client, monkeypatch):
    install()
    file_id = upload(client).json()["file"]["file_id"]  # no token yet: kept on disk
    fake = FakeBlob()
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", TOKEN)
    monkeypatch.setattr(storage, "blob", fake)
    monkeypatch.setattr(storage, "_open", fake.open)
    r = client.get(f"/books/fiqh/{file_id}.pdf", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.content == BOOK[:4] and fake.requests == []
    assert client.delete(f"/admin/api/files/{file_id}", headers=AUTH, params={"namespace": "fiqh"}).status_code == 200
    assert not main._book_path("deen", "fiqh", file_id).exists() and fake.calls == []

    # The same file uploaded to Blob, then to disk (Blob switched off), then to Blob again: each time
    # the copy kept before is removed.
    upload(client)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN")
    upload(client)
    assert main._book_path("deen", "fiqh", file_id).exists() and not fake.files
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", TOKEN)
    upload(client)
    assert not main._book_path("deen", "fiqh", file_id).exists() and db.get_upload("deen", "fiqh", file_id)["book_url"]


def test_blob_settings(monkeypatch):
    assert storage.describe() == "on this server's disk"
    monkeypatch.setenv("VERCEL_BLOB_READ_WRITE_TOKEN", TOKEN)
    assert storage.describe() == "in Vercel Blob (private store)"
    monkeypatch.setenv("BLOB_ACCESS", "Public")
    assert storage.access() == "public"
    monkeypatch.setenv("BLOB_ACCESS", "secret")
    assert "BLOB_ACCESS" in storage.describe()
    with pytest.raises(ValueError):
        storage.access()


def test_pages_of_a_book_in_blob_are_read_again_from_blob(client, blob_store, ocr_space):
    from conftest import joined_pdf, scanned_pdf
    from test_jobs import wait_for
    install()
    book = joined_pdf(tiny_pdf(["Patience is half of faith, and gratitude is the other half of it."]), scanned_pdf())
    ocr_space.error = (403, b'{"error":"E301: Daily limit reached"}')
    file = upload(client, filename="Scan.pdf", content=book).json()["file"]
    assert file["pending_pages"] == [2] and file["book"]
    url = db.get_upload("deen", "fiqh", file["file_id"])["book_url"]

    ocr_space.error = None
    blob_store.requests.clear()
    job = client.post(f"/admin/api/files/{file['file_id']}/ocr", headers=AUTH, params={"namespace": "fiqh"}).json()
    job = wait_for(client, job["id"])
    assert job["state"] == "done", job["error"]
    assert job["result"]["file"]["pending_pages"] == [] and job["result"]["file"]["passages"] == 2
    [(read, headers)] = blob_store.requests  # the whole book, with the token
    assert read == url and headers["Authorization"] == f"Bearer {TOKEN}" and "Range" not in headers

    # A book Blob no longer has can't be read again.
    ocr_space.error = (403, b'{"error":"E301: Daily limit reached"}')
    file = upload(client, filename="Other.pdf", content=joined_pdf(book, scanned_pdf())).json()["file"]
    blob_store.files.clear()
    job = client.post(f"/admin/api/files/{file['file_id']}/ocr", headers=AUTH, params={"namespace": "fiqh"}).json()
    job = wait_for(client, job["id"])
    assert job["state"] == "failed" and "missing from Vercel Blob" in job["error"]
    assert db.get_upload("deen", "fiqh", file["file_id"])["pending_pages"] == [2, 3]
