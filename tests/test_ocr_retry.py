"""PDFs read partly: pages OCR couldn't read are marked, and can be read again later."""

import db
import main
from conftest import AUTH, FakeIndex, install, joined_pdf, scanned_pdf, tiny_pdf
from test_books import book_file, upload
from test_jobs import wait_for

TEXT = "Patience is half of faith, and gratitude is the other half of it."
BOOK = joined_pdf(tiny_pdf([TEXT]), scanned_pdf(2))  # a text page, then two scanned ones
LIMIT = (403, b'{"error":"E301: Daily limit of 500 requests reached","details":"Try again tomorrow."}')


def retry(client, file_id, namespace="fiqh"):
    return client.post(f"/admin/api/files/{file_id}/ocr", headers=AUTH, params={"namespace": namespace})


def vector_pages(index, namespace="fiqh"):
    return {id_: v["metadata"]["page"] for (ns, id_), v in index.vectors.items() if ns == namespace}


def test_unread_pages_are_marked_and_read_again_later(client, ocr_space):
    index = FakeIndex()
    install(index=index)
    ocr_space.error = LIMIT
    r = upload(client, "fiqh", "Scan.pdf", BOOK, language="en")
    assert r.status_code == 200, r.text
    result = r.json()
    file_id = result["file"]["file_id"]
    assert (result["file"]["passages"], result["file"]["pending_pages"], result["file"]["book"]) == (1, [2, 3], True)
    assert "Daily limit of 500 requests" in result["warning"] and "marked in the list of files" in result["warning"]
    assert client.get("/admin/api/files", headers=AUTH).json()["files"][0]["pending_pages"] == [2, 3]
    assert vector_pages(index) == {f"{file_id}#0": 1}

    # The limit is still reached for the second page: one more page is read, one still waits.
    ocr_space.error = [None, LIMIT]
    job = retry(client, file_id).json()
    assert job["state"] == "processing"
    job = wait_for(client, job["id"])
    assert job["state"] == "done", job["error"]
    assert (job["pages"], job["pages_read"], job["ocr_pages"]) == (2, 2, 1)
    file = job["result"]["file"]
    assert (file["passages"], file["pending_pages"], job["result"]["ocr_pages"]) == (2, [3], 1)
    assert "Of the PDF's 3 pages, 1 has no readable text" in job["result"]["warning"]
    assert vector_pages(index) == {f"{file_id}#0": 1, f"{file_id}#1": 2}  # the new passages come after the others

    ocr_space.error = None
    job = wait_for(client, retry(client, file_id).json()["id"])
    assert job["result"]["file"]["pending_pages"] == [] and job["result"]["warning"] is None
    assert vector_pages(index) == {f"{file_id}#0": 1, f"{file_id}#1": 2, f"{file_id}#2": 3}
    assert db.get_upload("deen", "fiqh", file_id)["passages"] == 3
    r = retry(client, file_id)
    assert r.status_code == 409 and "already" in r.json()["detail"]

    # Uploaded again with the pages unread: its passages from the earlier reads go too.
    ocr_space.error = LIMIT
    assert upload(client, "fiqh", "Scan.pdf", BOOK, language="en").json()["file"]["pending_pages"] == [2, 3]
    assert vector_pages(index) == {f"{file_id}#0": 1}

    # Deleting removes every passage, including ones added by reading pages again.
    ocr_space.error = None
    wait_for(client, retry(client, file_id).json()["id"])
    assert client.delete(f"/admin/api/files/{file_id}", headers=AUTH, params={"namespace": "fiqh"}).status_code == 200
    assert vector_pages(index) == {}


def test_a_file_is_read_again_by_one_job_at_a_time(client, ocr_space):
    install()
    ocr_space.error = LIMIT
    file_id = upload(client, "fiqh", "Scan.pdf", BOOK, language="en").json()["file"]["file_id"]
    lock = main._lock_name("deen", "fiqh", file_id)
    assert db.lock(lock, "another-job", 60)
    for r in (retry(client, file_id), upload(client, "fiqh", "Scan.pdf", BOOK, language="en"),
              client.delete(f"/admin/api/files/{file_id}", headers=AUTH, params={"namespace": "fiqh"})):
        assert r.status_code == 409 and "right now" in r.json()["detail"]
    db.unlock(lock, "another-job")
    ocr_space.error = None
    assert wait_for(client, retry(client, file_id).json()["id"])["state"] == "done"
    assert db.lock(lock, "next", 60)  # the job let go of it


def test_pages_can_only_be_read_again_from_a_kept_book(client):
    install()
    assert retry(client, "nothing-0123456789ab").status_code == 404
    file = upload(client, "fiqh", "Scan.pdf", BOOK, language="en").json()["file"]  # no OCR key: pages wait
    assert file["pending_pages"] == [2, 3]
    book_file("fiqh", file["file_id"]).unlink()
    r = retry(client, file["file_id"])
    assert r.status_code == 409 and "Upload it again" in r.json()["detail"]
    text_only = upload(client, "fiqh", "Text.pdf", tiny_pdf([TEXT]), language="en").json()["file"]
    assert retry(client, text_only["file_id"]).status_code == 409
