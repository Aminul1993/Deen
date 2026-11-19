"""Splitting uploaded files into passages (ingest.py)."""

import io
import json

import pytest

import ingest
from conftest import tiny_pdf


def test_chunks_end_at_sentences_and_overlap():
    text = ("Sentence number %d is here. " * 200) % tuple(range(200))
    chunks = ingest.chunk_text(text)
    assert len(chunks) > 3
    assert all(len(c) <= ingest.CHUNK_CHARS for c in chunks)
    assert all(c.endswith(".") for c in chunks[:-1])
    assert chunks[1][:30] in chunks[0]  # consecutive passages overlap


def test_chunks_handle_bengali_long_words_and_blank_text():
    chunks = ingest.chunk_text("রোজা একটি ফরজ ইবাদত। " * 200)
    assert len(chunks) > 2 and all(c.endswith("।") for c in chunks[:-1])
    assert len(ingest.chunk_text("x" * 2500)) == 3  # no break point still makes progress
    assert ingest.chunk_text("   \n\n  ") == []
    assert ingest.chunk_text("short") == ["short"]


def test_records_keep_citation_fields_and_skip_records_without_text():
    records = [
        {"id": "x1", "text": "Actions are by intentions", "collection": "Sahih al-Bukhari", "hadith_number": 1,
         "grade": "Sahih", "nested": {"a": 1}, "tags": ["a", None, ""], "empty": "", "nan": float("nan")},
        {"content": "Second", "surah": 2},
        {"no_text": True},
        "plain string record",
        42,
    ]
    parsed = ingest.parse_file("h.json", json.dumps(records).encode())
    assert parsed.skipped_records == 2
    assert parsed.passages[0].metadata == {"collection": "Sahih al-Bukhari", "hadith_number": 1, "grade": "Sahih",
                                           "nested": '{"a": 1}', "tags": ["a"]}
    assert parsed.passages[1].metadata == {"surah": 2}
    assert parsed.passages[2].text == "plain string record"


def test_text_jsonl_and_csv():
    assert [p.text for p in ingest.parse_file("a.txt", "Hello\r\n\r\n\r\nworld".encode("utf-8-sig")).passages] == ["Hello\n\nworld"]
    assert [p.text for p in ingest.parse_file("h.jsonl", b'{"text": "a"}\n\n{"text": "b"}\n').passages] == ["a", "b"]
    parsed = ingest.parse_file("q.csv", b"text,surah,ayah,hadith_number\nIn the name of Allah,1,1,007\n,2,2,\n")
    assert parsed.skipped_records == 1
    assert parsed.passages[0].metadata == {"surah": 1, "ayah": 1, "hadith_number": "007"}  # "007" stays text


def test_pdf_pages_keep_their_numbers():
    data = tiny_pdf(["Page one about patience.", "Page two about charity."])
    parsed = ingest.parse_file("book.PDF", data)
    assert [p.metadata for p in parsed.passages] == [{"page": 1}, {"page": 2}]
    assert "patience" in parsed.passages[0].text
    reader = ingest.FileReader("book.pdf", io.BytesIO(data), len(data))
    assert reader.page_count is None
    list(reader)
    assert reader.page_count == 2


@pytest.mark.parametrize("name, data, message", [
    ("x.docx", b"abc", "can't be uploaded"),
    ("x.txt", b"\xff\xfe\x00bad", "UTF-8"),
    ("x.json", b"{bad", "valid JSON"),
    ("x.json", b"3", "array"),
    ("x.json", b'[{"title": "no text"}]', "None of the 1 records"),
    ("x.jsonl", b'{"text": "a"}\n{oops\n', "Line 2"),
    ("x.txt", b"   ", "no text"),
    ("x.pdf", b"not a pdf", "couldn't be read"),
])
def test_unusable_files_say_why(name, data, message):
    with pytest.raises(ingest.IngestError, match=message):
        ingest.parse_file(name, data)


def test_file_ids_and_names():
    assert ingest.clean_filename("C:\\fakepath\\Sahih Bukhari.json") == "Sahih Bukhari.json"
    assert ingest.clean_filename("") == "upload"
    assert ingest.file_id_for("Sahih Bukhari.json", b"abc").startswith("sahih-bukhari-")
    assert ingest.file_id_for("রোজা.txt", b"abc").startswith("file-")
    assert ingest.file_id_for("a.txt", b"one") != ingest.file_id_for("a.txt", b"two")
