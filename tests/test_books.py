"""Books: uploaded PDFs are kept, listed, served page by page, and linked from answers' sources."""

import json

import db
import main
from conftest import AUTH, FakeIndex, install, tiny_pdf
from test_jobs import send_file, wait_for

BOOK = tiny_pdf(["Page one about patience.", "Page two about charity."])


def upload(client, namespace, filename, content, language=None, mime="application/pdf"):
    data = {"namespace": namespace, **({"language": language} if language else {})}
    return client.post("/admin/api/files", headers=AUTH, data=data, files={"file": (filename, content, mime)})


def book_file(namespace, file_id):
    return main._book_path("deen", namespace, file_id)


def test_an_uploaded_pdf_becomes_a_book(client):
    index = FakeIndex()
    install(index=index)
    r = upload(client, "fiqh", "Bahishti_Zewar.pdf", BOOK, language="bn")
    assert r.status_code == 200, r.text
    file = r.json()["file"]
    assert (file["language"], file["pages"], file["book"]) == ("bn", 2, True)
    assert book_file("fiqh", file["file_id"]).read_bytes() == BOOK
    metadata = [v["metadata"] for v in index.vectors.values()]
    assert {(m["language"], m["page"]) for m in metadata} == {("bn", 1), ("bn", 2)}

    body = client.get("/books/list").json()
    assert body["languages"] == main.LANGUAGES
    [book] = body["books"]
    assert (book["title"], book["text"], book["language"], book["pages"]) == ("Bahishti Zewar", "fiqh", "bn", 2)
    assert book["url"] == f"/books?text=fiqh&book={file['file_id']}"

    r = client.get(book["pdf"])
    assert r.status_code == 200 and r.content == BOOK
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    r = client.get(book["pdf"], headers={"Range": "bytes=0-7"})  # pdf.js reads large books in ranges
    assert r.status_code == 206 and r.content == BOOK[:8]

    files = client.get("/admin/api/files", headers=AUTH).json()
    assert files["files"][0]["book"] is True and files["languages"]["bn"] == "Bengali"
    assert client.get("/books").headers["content-type"].startswith("text/html")


def test_only_pdfs_are_books_and_languages_are_checked(client):
    install()
    r = upload(client, "duas", "duas.json", json.dumps([{"text": "A dua."}]).encode(), language="ar", mime="text/plain")
    assert r.status_code == 200 and r.json()["file"]["book"] is False and r.json()["file"]["language"] == "ar"
    assert upload(client, "fiqh", "no-language.pdf", BOOK).json()["file"]["language"] is None
    assert [b["title"] for b in client.get("/books/list").json()["books"]] == ["no-language"]
    r = upload(client, "fiqh", "x.pdf", BOOK, language="klingon")
    assert r.status_code == 422 and "en, bn, ar, ur" in r.json()["detail"]


def test_deleting_or_replacing_a_pdf_removes_its_book(client, monkeypatch):
    times = iter(f"2026-01-01T00:00:0{i}+00:00" for i in range(10))
    monkeypatch.setattr(db, "_now", lambda: next(times))
    install()
    first = upload(client, "fiqh", "book.pdf", BOOK, language="en").json()["file"]
    edited = upload(client, "fiqh", "book.pdf", tiny_pdf(["A corrected page."]), language="en").json()
    assert edited["replaced_versions"] == 1
    assert not book_file("fiqh", first["file_id"]).exists()
    assert book_file("fiqh", edited["file"]["file_id"]).exists()
    assert [b["pages"] for b in client.get("/books/list").json()["books"]] == [1]

    file_id = edited["file"]["file_id"]
    assert client.delete(f"/admin/api/files/{file_id}", headers=AUTH, params={"namespace": "fiqh"}).status_code == 200
    assert not book_file("fiqh", file_id).exists()
    assert client.get("/books/list").json()["books"] == []
    assert client.get(f"/books/fiqh/{file_id}.pdf").status_code == 404


def test_book_addresses_are_checked(client):
    install()
    file_id = upload(client, "fiqh", "book.pdf", BOOK).json()["file"]["file_id"]
    for path in [f"/books/fiqh/{file_id[:-1]}x.pdf", f"/books/other/{file_id}.pdf", "/books/fiqh/..%2Fsecret.pdf",
                 f"/books/-bad/{file_id}.pdf"]:
        assert client.get(path).status_code == 404, path
    book_file("fiqh", file_id).unlink()  # e.g. the data folder was lost
    assert client.get(f"/books/fiqh/{file_id}.pdf").status_code == 404
    assert client.get("/books/list").json()["books"] == []


def test_books_need_the_index_name(client):
    assert client.get("/books/list").status_code == 503


def test_pdfs_sent_in_parts_or_downloaded_are_kept(client, web_server, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_CHUNK_BYTES", 300)
    install()
    job = client.post("/admin/api/jobs", headers=AUTH, json={"namespace": "x", "filename": "f.pdf", "size": 5, "language": "xx"})
    assert job.status_code == 422

    job = send_file(client, "fiqh", "Parts.pdf", BOOK, language="ur")
    assert job["state"] == "done", job
    file = job["result"]["file"]
    assert (file["language"], file["pages"], file["book"]) == ("ur", 2, True)
    assert book_file("fiqh", file["file_id"]).read_bytes() == BOOK
    assert not main._part_path(job["id"]).exists()

    job = client.post("/admin/api/jobs", headers=AUTH,
                      json={"namespace": "fazail", "url": web_server + "/files/Fazail_Amal.pdf", "language": "en"}).json()
    job = wait_for(client, job["id"])
    assert job["state"] == "done", job
    file = job["result"]["file"]
    assert (file["filename"], file["language"], file["book"]) == ("Fazail_Amal.pdf", "en", True)
    titles = {b["title"]: b["language"] for b in client.get("/books/list").json()["books"]}
    assert titles == {"Parts": "ur", "Fazail Amal": "en"}


def test_sources_link_to_the_page_of_their_book(client):
    index = FakeIndex()
    install(index=index)
    file_id = upload(client, "fiqh", "Bahishti_Zewar.pdf", BOOK, language="bn").json()["file"]["file_id"]
    upload(client, "fiqh", "notes.txt", b"Plain notes about patience.", mime="text/plain")

    state = {"query": "patience", "history": [], "search_query": "patience", "namespace": "fiqh", "top_k": 5,
             "context": [], "sources": [], "answer": ""}
    sources = main.retrieve(state)["sources"]
    books = {s["metadata"]["page"]: s["book"] for s in sources if "book" in s}
    assert books[2] == {"id": file_id, "text": "fiqh", "title": "Bahishti Zewar", "language": "bn", "page": 2,
                        "pdf": f"/books/fiqh/{file_id}.pdf", "url": f"/books?text=fiqh&book={file_id}&page=2"}
    assert sorted(books) == [1, 2]
    assert not any("book" in s for s in sources if s["metadata"]["source_file"] == "notes.txt")
