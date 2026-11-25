"""Splitting uploaded files into passages (ingest.py)."""

import io
import json

import pytest

import ingest
from conftest import joined_pdf, parse_file, scanned_pdf, tiny_pdf


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
    parsed = parse_file("h.json", json.dumps(records).encode())
    assert parsed.skipped_records == 2
    assert parsed.passages[0].metadata == {"collection": "Sahih al-Bukhari", "hadith_number": 1, "grade": "Sahih",
                                           "nested": '{"a": 1}', "tags": ["a"]}
    assert parsed.passages[1].metadata == {"surah": 2}
    assert parsed.passages[2].text == "plain string record"


def test_text_jsonl_and_csv():
    assert [p.text for p in parse_file("a.txt", "Hello\r\n\r\n\r\nworld".encode("utf-8-sig")).passages] == ["Hello\n\nworld"]
    assert [p.text for p in parse_file("h.jsonl", b'{"text": "a"}\n\n{"text": "b"}\n').passages] == ["a", "b"]
    parsed = parse_file("q.csv", b"text,surah,ayah,hadith_number\nIn the name of Allah,1,1,007\n,2,2,\n")
    assert parsed.skipped_records == 1
    assert parsed.passages[0].metadata == {"surah": 1, "ayah": 1, "hadith_number": "007"}  # "007" stays text


def test_pdf_pages_keep_their_numbers():
    data = tiny_pdf(["Page one about patience.", "Page two about charity."])
    parsed = parse_file("book.PDF", data)
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
        parse_file(name, data)


def test_file_ids_and_names():
    assert ingest.clean_filename("C:\\fakepath\\Sahih Bukhari.json") == "Sahih Bukhari.json"
    assert ingest.clean_filename("") == "upload"
    assert ingest.file_id_for("Sahih Bukhari.json", b"abc").startswith("sahih-bukhari-")
    assert ingest.file_id_for("রোজা.txt", b"abc").startswith("file-")
    assert ingest.file_id_for("a.txt", b"one") != ingest.file_id_for("a.txt", b"two")


# --------------------------------------------------------------------------- #
# OCR of PDF pages without readable text
# --------------------------------------------------------------------------- #

ENGLISH_PAGE = "Patience is half of faith, and gratitude is the other half of it."
# Bengali in the non-Unicode Bijoy font, as a PDF's text layer gives it.
BIJOY_PAGE = "Avgiv mevB Avjøvni Dci fimv Kwi Ges Zuv‡KB Bev`Z Kwi| ‡ivRv Xvj¯^iƒc, myZivs ‡ivRv`vi †hb Akøxj K_v bv e‡j|"
BENGALI = "আমরা সবাই আল্লাহর উপর ভরসা করি এবং তাঁরই ইবাদত করি।"


@pytest.mark.parametrize("text, language, readable", [
    (ENGLISH_PAGE, "en", True),
    (ENGLISH_PAGE, None, True),
    ("   \n ", "en", False),  # a scan: no text layer
    ("��� text", "en", False),  # characters the font couldn't map
    (" abc", "bn", False),  # private-use glyphs
    (BIJOY_PAGE, "bn", False),  # Latin letters and symbols in a Bengali book
    (BIJOY_PAGE, "ur", False),
    (ENGLISH_PAGE, "bn", True),  # an English page in a Bengali book
    ("© 2010 Darussalam. All rights reserved.", "ur", True),
    (BENGALI, "bn", True),
    (BENGALI + " قال رسول الله صلى الله عليه وسلم", "bn", True),  # Arabic quotes are fine
    ("قال رسول الله صلى الله عليه وسلم", "ar", True),
    ("وہ نماز پڑھتا ہے", "ur", True),
    ("১২", "bn", True),  # no letters, only a page number
])
def test_pages_with_missing_or_garbled_text_are_unreadable(text, language, readable):
    assert ingest._readable(text, language) is readable


def test_scanned_pages_are_read_with_ocr(ocr_space):
    data = joined_pdf(tiny_pdf([ENGLISH_PAGE]), scanned_pdf(), tiny_pdf(["", ENGLISH_PAGE.replace("Patience", "Charity")]))
    seen = []
    reader = ingest.FileReader("book.pdf", io.BytesIO(data), len(data), language="en",
                               on_page=lambda *progress: seen.append(progress))
    passages = list(reader)
    assert [(p.metadata["page"], p.text) for p in passages] == [
        (1, ENGLISH_PAGE), (2, ocr_space.text), (4, ENGLISH_PAGE.replace("Patience", "Charity"))]
    # Only the scanned page is sent, drawn at 300 dpi, to Engine 2 for English; the blank page 3 isn't.
    [(engine, (width, height), _)] = ocr_space.calls
    assert engine == 2 and abs(width - 2550) <= 1 and abs(height - 3300) <= 1
    assert (reader.ocr_pages, reader.unread_pages, reader.warning) == (1, [], None)
    assert seen == [(1, 4, 0), (2, 4, 1), (3, 4, 1), (4, 4, 1)]


def test_garbled_and_sparse_pages(ocr_space, monkeypatch):
    # Bengali goes to Engine 3; its Markdown headings and bold marks are dropped.
    ocr_space.text = "# রোজার অধ্যায়\n\n**" + BENGALI + "**"
    parsed = parse_file("book.pdf", tiny_pdf([BIJOY_PAGE]), language="bn")
    assert [p.text for p in parsed.passages] == ["রোজার অধ্যায়\n\n" + BENGALI]
    assert ocr_space.calls[-1][0] == 3

    # A short text page without a picture (a title) isn't sent; one over a scan (a watermark) is.
    calls = len(ocr_space.calls)
    assert [p.text for p in parse_file("t.pdf", tiny_pdf(["Bahishti Zewar"])).passages] == ["Bahishti Zewar"]
    assert len(ocr_space.calls) == calls
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(scanned_pdf())).pages[0]).merge_page(PdfReader(io.BytesIO(tiny_pdf(["www.example.org"]))).pages[0])
    out = io.BytesIO()
    writer.write(out)
    ocr_space.text = ENGLISH_PAGE
    assert [p.text for p in parse_file("w.pdf", out.getvalue(), language="en").passages] == [ENGLISH_PAGE]

    # A page's image is made smaller until it fits OCR.space's file size limit.
    monkeypatch.setattr(ingest, "OCR_MAX_BYTES", 15_000)
    parse_file("s.pdf", scanned_pdf(), language="ar")
    engine, size, length = ocr_space.calls[-1]
    assert engine == 3 and length <= 15_000 and size[0] < 2550


def test_pages_ocr_cant_read_are_left_for_later():
    with pytest.raises(ingest.IngestError, match="no text to index"):  # blank pages aren't scans
        parse_file("blank.pdf", tiny_pdf(["", ""]))

    # Without OCR, garbled and scanned pages give no passages and are listed, to be read later.
    data = joined_pdf(tiny_pdf([ENGLISH_PAGE, BIJOY_PAGE, ""]), scanned_pdf())
    reader = ingest.FileReader("book.pdf", io.BytesIO(data), len(data), language="bn")
    assert [p.text for p in reader] == [ENGLISH_PAGE]
    assert reader.unread_pages == [2, 4]
    assert reader.warning.startswith("Of the PDF's 4 pages, 2 have no readable text")
    data = scanned_pdf(2)  # a scan with nothing read isn't refused: it waits for OCR
    reader = ingest.FileReader("scan.pdf", io.BytesIO(data), len(data))
    assert list(reader) == [] and reader.unread_pages == [1, 2] and "OCR_SPACE_API_KEY" in reader.warning

    # Reading chosen pages again: only those, with progress counted over them.
    seen = []
    data = joined_pdf(tiny_pdf([ENGLISH_PAGE, ENGLISH_PAGE]), scanned_pdf())
    reader = ingest.FileReader("book.pdf", io.BytesIO(data), len(data), pages=[3, 2, 99],
                               on_page=lambda *progress: seen.append(progress))
    assert [p.metadata["page"] for p in reader] == [2] and reader.unread_pages == [3]
    assert seen == [(1, 2, 0), (2, 2, 0)]


def test_ocr_space_errors(ocr_space):
    # A refused key stops OCR for the rest of the file, after one request.
    ocr_space.error = (403, b'{"error":"E555: API key not valid","details":"Get your FREE ocr api key at Ocr.Space."}')
    reader = ingest.FileReader("scan.pdf", io.BytesIO(scanned_pdf(3)), 0)
    assert list(reader) == [] and reader.unread_pages == [1, 2, 3]
    assert "OCR.space answered: E555: API key not valid" in reader.warning
    assert len(ocr_space.calls) == 1

    # Pages it can't read are skipped and listed; after a few in a row, the rest aren't sent.
    ocr_space.error = None
    ocr_space.answer = {"ParsedResults": [{"FileParseExitCode": -20, "ErrorMessage": "Timed out"}],
                        "OCRExitCode": 3, "IsErroredOnProcessing": True, "ErrorMessage": ["Page timed out"]}
    data = joined_pdf(tiny_pdf([ENGLISH_PAGE]), scanned_pdf(4))
    reader = ingest.FileReader("book.pdf", io.BytesIO(data), len(data), language="en")
    assert len(list(reader)) == 1
    assert len(ocr_space.calls) == 1 + ingest.OCR_MAX_FAILURES
    assert reader.unread_pages == [2, 3, 4, 5] and "OCR.space answered: Timed out" in reader.warning

    ocr_space.answer = {"IsErroredOnProcessing": True, "ErrorMessage": ["You may only perform this action upto maximum 500 times"]}
    reader = ingest.FileReader("scan.pdf", io.BytesIO(scanned_pdf(1)), 0)
    assert list(reader) == [] and "maximum 500 times" in reader.warning
