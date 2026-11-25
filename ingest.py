"""Turn an uploaded file into passages ready to embed and store in Pinecone.

Used by the admin page (see the Admin section of main.py). Supported files:

- .txt, .md   Plain text, split into overlapping passages.
- .pdf        The text of each page, split into passages. Each passage keeps its page number.
              A page without readable text (scanned, or set in a non-Unicode font such as Bijoy) is
              read with OCR, when OCR.space is set up (see "OCR" below).
- .json       An array of records (or a single record).
- .jsonl      One record per line.
- .csv        One record per row, with a header row.

A record needs a "text" or "content" field. Its other fields (surah, ayah, collection,
hadith_number, grade, ...) are kept as metadata, so answers can cite them. A record's "id" is
ignored: vector ids are generated so a file can be deleted again. Long records are split, and
every part keeps the record's metadata.

Files are read as a stream (FileReader), so a large upload needn't fit in memory. The exception
is .json: an array is parsed whole, so .json files are limited to MAX_JSON_BYTES.

OCR: a PDF page's text layer is used when it's readable. When it's missing (a scan), garbled
(replacement or private-use characters), or not in the upload's script (a Bengali, Arabic or Urdu
book whose text comes out as Latin letters, as from Bijoy or SutonnyMJ fonts), the page is drawn
as an image with PDFium and sent to the OCR.space API (OCR_SPACE_API_KEY). Without a key, such
pages keep whatever text they have, as before OCR existed.
"""

import base64
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, BinaryIO, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

import pypdfium2 as pdfium
from pypdf import PdfReader

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Tuple[str, ...] = (".txt", ".md", ".pdf", ".json", ".jsonl", ".csv")

# multilingual-e5-large reads about 500 tokens of each passage and truncates the rest, and Arabic
# and Bengali use more tokens per character than English, so passages stay short.
CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150
MAX_METADATA_CHARS = 4000  # per value; Pinecone allows 40 KB of metadata per vector
MAX_JSON_BYTES = 50 * 1024 * 1024  # a .json array is parsed whole; larger record files should be .jsonl
TEXT_BLOCK_CHARS = 200_000  # plain text is split into passages this much at a time, at a paragraph break

# Record fields that hold the passage text: the fields main.extract_text() reads, in the same order.
TEXT_FIELDS: Tuple[str, ...] = ("text", "content")
IGNORED_FIELDS = {"id"}

# OCR of PDF pages without readable text, with OCR.space. Its Engine 3 reads Bengali, Arabic and
# Urdu (Engine 2 turns Bengali into Devanagari and drops Arabic letters), but the free plan allows
# only 1,000 Engine 3 pages a month; Engine 2, for everything else, allows 25,000.
OCR_SPACE_URL = "https://api.ocr.space/parse/image"
OCR_ENGINES: Dict[str, int] = {"bn": 3, "ar": 3, "ur": 3}
DEFAULT_OCR_ENGINE = 2
OCR_DPI = 300  # OCR reads best at about 300 dots per inch
OCR_MAX_PIXELS = 5000  # longest side of a page's image, so an oversized page can't take gigabytes
OCR_MAX_BYTES = 700_000  # a page's JPEG; the free plan takes files up to 1 MB, and base64 adds a third
OCR_TIMEOUT = 120  # seconds to wait for one page
OCR_MAX_FAILURES = 3  # pages in a row OCR.space fails on before the rest of the file isn't sent
# A text layer with fewer visible characters is checked with OCR too: it may be a page number or a
# watermark over a scanned page. Its own text is kept unless OCR finds much more.
SPARSE_PAGE_CHARS = 40
# Letters a page in each language is mostly written in. A page with fewer than a fifth of its letters
# in them is in another language (an English preface), or in an old non-Unicode font: Bijoy and
# SutonnyMJ turn Bengali into Latin letters and symbols, e.g. "Avjøvn&i Kv‡Q" for "আল্লাহর কাছে".
# Those symbols (Latin-1 and Windows-1252 ones), on 1 in 20 of its characters, tell the two apart.
_ARABIC_SCRIPT = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))
_SCRIPTS: Dict[str, Tuple[Tuple[int, int], ...]] = {"bn": ((0x0980, 0x09FF),), "ar": _ARABIC_SCRIPT, "ur": _ARABIC_SCRIPT}
_LEGACY_FONT_CHARS = frozenset(map(chr, range(0xA1, 0x100))) | frozenset("ŒœŠšŸŽžƒˆ˜†‡‰‹›")
_BROKEN_CATEGORIES = ("Cc", "Cn", "Co")  # control, unassigned and private-use characters
_pdfium_lock = threading.Lock()  # PDFium isn't thread-safe, and uploads are read in background threads

# Places to end a passage, best first: paragraph, line, sentence (Latin, Arabic, Urdu, Bengali), word.
_BREAKS: Tuple[str, ...] = ("\n\n", "\n", ". ", "? ", "! ", "؟ ", "۔ ", "। ", " ")
_WHOLE_NUMBER = re.compile(r"-?[1-9]\d{0,14}|0")


class IngestError(ValueError):
    """The file can't be turned into passages. The message says why, for the admin."""


@dataclass(frozen=True)
class Passage:
    text: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class ParsedFile:
    passages: List[Passage]
    skipped_records: int  # records with no "text" or "content"


def clean_filename(filename: str) -> str:
    """The file's base name, without any directory a browser or client sent with it."""
    name = re.split(r"[\\/]", filename or "")[-1].strip()
    return name[:200] or "upload"


def file_id_for(filename: str, data: Union[bytes, BinaryIO]) -> str:
    """A stable id for this file's contents, used as the prefix of its vector ids.

    Uploading the same file to the same namespace again overwrites its vectors instead of
    duplicating them. data is the content, or a seekable stream of it, which is left at its start.
    """
    digest = hashlib.sha256()
    if isinstance(data, bytes):
        digest.update(data)
    else:
        for block in iter(lambda: data.read(1 << 20), b""):
            digest.update(block)
        data.seek(0)
    slug = re.sub(r"[^a-z0-9]+", "-", PurePath(filename).stem.lower()).strip("-")[:40] or "file"
    return f"{slug}-{digest.hexdigest()[:12]}"


class FileReader:
    """The passages of an uploaded file, read as they're needed, so a large file needn't fit in memory.

    Iterate it once. An unsupported file is refused when the reader is created, before anything
    is read; a file with nothing to index raises IngestError when iteration ends. skipped_records
    counts records without text, so far.

    A PDF's pages without readable text are read with OCR, in language (an upload language code,
    see OCR_ENGINES). Pages OCR can't read (no key, a limit reached, a failure) give no passages:
    they're listed in unread_pages, so they can be read again later with pages=unread_pages. A
    PDF whose only text is on such pages isn't refused. on_page is called after each PDF page read
    with (pages read, pages to read, pages read with OCR).
    """

    def __init__(self, filename: str, stream: BinaryIO, size: int, language: Optional[str] = None,
                 on_page: Optional[Callable[[int, int, int], None]] = None,
                 pages: Optional[Sequence[int]] = None) -> None:
        self.extension = PurePath(filename).suffix.lower()
        if self.extension not in SUPPORTED_EXTENSIONS:
            raise IngestError(
                f"Files of type {self.extension or '(no extension)'} can't be uploaded. "
                f"Use one of: {', '.join(SUPPORTED_EXTENSIONS)}."
            )
        if self.extension == ".json" and size > MAX_JSON_BYTES:
            raise IngestError(
                f".json files are read all at once, so they can be at most {MAX_JSON_BYTES // 2**20} MB. "
                "Save larger record files as .jsonl, one record per line."
            )
        self.stream = stream
        self.language = language
        self.on_page = on_page
        self.only_pages = pages  # a PDF's page numbers to read (from 1), or None for all of them
        self.skipped_records = 0
        self.page_count: Optional[int] = None  # a PDF's number of pages, once reading has started
        self.ocr_pages = 0  # PDF pages whose text was read with OCR
        self.unread_pages: List[int] = []  # numbers of PDF pages without readable text that OCR couldn't read
        self.ocr_problem: Optional[str] = None  # why OCR stopped being used, once a page needed it

    def __iter__(self) -> Iterator[Passage]:
        count = 0
        for passage in self._passages():
            count += 1
            yield passage
        if count or self.unread_pages or self.only_pages is not None:
            return  # pages left for OCR to read later, or chosen pages that were blank
        if self.skipped_records:
            raise IngestError(f'None of the {self.skipped_records} records has a "text" or "content" field to index.')
        raise IngestError("The file has no text to index.")

    @property
    def warning(self) -> Optional[str]:
        """Pages of a PDF left unread, for the admin, or None."""
        if not self.unread_pages:
            return None
        one = len(self.unread_pages) == 1
        return (f"Of the PDF's {self.page_count} pages, {len(self.unread_pages)} {'has' if one else 'have'} no readable "
                f"text (scanned, set in an old non-Unicode font, or in another language than the one chosen), and "
                f"OCR couldn't read {'it' if one else 'them'} yet: {self.ocr_problem or 'the server log says why.'}")

    def _passages(self) -> Iterator[Passage]:
        if self.extension in (".txt", ".md"):
            for block in _text_blocks(_lines(self.stream)):
                yield from (Passage(chunk, {}) for chunk in chunk_text(block))
        elif self.extension == ".pdf":
            yield from self._pdf_passages()
        elif self.extension == ".json":
            yield from self._records(_json_records(self.stream.read()))
        elif self.extension == ".jsonl":
            yield from self._records(_jsonl_records(_lines(self.stream)))
        else:  # .csv
            yield from self._records(csv.DictReader(_lines(self.stream)), parse_numbers=True)

    def _pdf_passages(self) -> Iterator[Passage]:
        pages = _pdf_pages(self.stream)
        self.page_count = len(pages)
        numbers = range(len(pages)) if self.only_pages is None else sorted(
            {n - 1 for n in self.only_pages if 1 <= n <= len(pages)})
        ocr = _PageReader(self.stream, self.language)
        try:
            for done, number in enumerate(numbers, start=1):
                try:
                    text = pages[number].extract_text() or ""
                except Exception as exc:
                    raise IngestError(_BAD_PDF) from exc
                text = self._checked(pages[number], text, number, ocr)
                if self.on_page:
                    self.on_page(done, len(numbers), self.ocr_pages)
                yield from (Passage(chunk, {"page": number + 1}) for chunk in chunk_text(text))
        finally:
            ocr.close()

    def _checked(self, page: Any, text: str, number: int, ocr: "_PageReader") -> str:
        """A page's text: its text layer, or what OCR reads when that's missing, garbled or sparse."""
        unreadable = not _readable(text, self.language)
        if not unreadable and _visible(text) >= SPARSE_PAGE_CHARS:
            return text
        garbled = unreadable and _visible(text) > 0
        if not garbled and not _has_images(page):  # a blank page, or a title: no scan to read
            return text
        read = ocr.read(number)
        self.ocr_problem = ocr.problem or ocr.last_error
        if read is None:  # OCR can't be used, or failed on this page
            if not unreadable:
                return text
            self.unread_pages.append(number + 1)
            return ""  # garbled text would only be found by mistake: the page waits to be read again
        # A sparse page keeps its own text (a title, say) unless OCR finds what it's printed over.
        if _visible(read) and (unreadable or _visible(read) > 2 * _visible(text)):
            self.ocr_pages += 1
            return read
        return text

    def _records(self, records: Iterable[Any], parse_numbers: bool = False) -> Iterator[Passage]:
        for record in records:
            if isinstance(record, str):
                record = {"text": record}
            text = _record_text(record) if isinstance(record, dict) else ""
            if not text:
                self.skipped_records += 1
                continue
            fields = {key: value for key, value in record.items() if key not in TEXT_FIELDS and key not in IGNORED_FIELDS}
            metadata = _metadata(fields, parse_numbers)
            yield from (Passage(chunk, metadata) for chunk in chunk_text(text))


def parse_file(filename: str, data: bytes, language: Optional[str] = None) -> ParsedFile:
    """All of a small file's passages at once."""
    reader = FileReader(filename, io.BytesIO(data), len(data), language=language)
    passages = list(reader)
    return ParsedFile(passages=passages, skipped_records=reader.skipped_records)


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into passages of at most `size` characters, overlapping by about `overlap`.

    Each passage ends at the last paragraph, line, sentence or word break in the second half
    of its window, so passages rarely stop mid-sentence.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for separator in _BREAKS:
                cut = window.rfind(separator, size // 2)
                if cut != -1:
                    end = start + cut + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Step back to overlap the previous passage, then forward to the start of a word.
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return chunks


# --------------------------------------------------------------------------- #
# Formats
# --------------------------------------------------------------------------- #


_NOT_UTF8 = "The file isn't UTF-8 text. Save it with UTF-8 encoding and upload it again."
_BAD_PDF = "The PDF couldn't be read. It may be damaged or password-protected."


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError(_NOT_UTF8) from exc


def _lines(stream: BinaryIO) -> Iterator[str]:
    """The stream's lines, decoded as UTF-8 as they're read. Leaves the stream itself open."""
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    try:
        for line in text:  # not "yield from": closing this generator early would then close the stream
            yield line
    except UnicodeDecodeError as exc:
        raise IngestError(_NOT_UTF8) from exc
    finally:
        text.detach()


def _text_blocks(lines: Iterable[str]) -> Iterator[str]:
    """Plain text in blocks of about TEXT_BLOCK_CHARS, ending at a blank line when there is one."""
    block: List[str] = []
    size = 0
    for line in lines:
        block.append(line)
        size += len(line)
        if size >= TEXT_BLOCK_CHARS and (not line.strip() or size >= 4 * TEXT_BLOCK_CHARS):
            yield "".join(block)
            block, size = [], 0
    if block:
        yield "".join(block)


def _pdf_pages(stream: BinaryIO) -> Sequence[Any]:
    try:
        pages = PdfReader(stream).pages
        len(pages)  # reads the page tree, so a damaged file fails here
    except Exception as exc:  # pypdf raises many types for damaged or encrypted files
        raise IngestError(_BAD_PDF) from exc
    return pages


def _visible(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def _readable(text: str, language: Optional[str]) -> bool:
    """Whether a page's text layer is real text: not missing (a scan) or garbled (a broken font)."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return False
    broken = sum(1 for c in chars if c == "\ufffd" or unicodedata.category(c) in _BROKEN_CATEGORIES)
    if broken * 10 > len(chars):
        return False
    script = _SCRIPTS.get(language or "")
    if not script:
        return True
    letters = [ord(c) for c in chars if c.isalpha()]
    native = sum(1 for c in letters if any(low <= c <= high for low, high in script))
    if not letters or native * 5 >= len(letters):
        return True
    return sum(1 for c in chars if c in _LEGACY_FONT_CHARS) * 20 < len(chars)  # else an old non-Unicode font


def _has_images(page: Any) -> bool:
    """Whether a page draws a picture, such as a scan. A page that can't be checked counts as one."""
    try:
        return len(page.images) > 0
    except Exception:
        return True


class _OcrError(Exception):
    """OCR.space didn't read a page. refused: it turned the request itself down (the key, or a limit)."""

    def __init__(self, message: str, refused: bool = False) -> None:
        super().__init__(message)
        self.refused = refused


class _PageReader:
    """Reads a PDF's pages with OCR: draws each as an image with PDFium, then sends it to OCR.space.

    Opens the PDF with PDFium when the first page needs it, so a PDF with a good text layer costs nothing.
    """

    def __init__(self, stream: BinaryIO, language: Optional[str]) -> None:
        self.stream = stream
        self.engine = OCR_ENGINES.get(language or "", DEFAULT_OCR_ENGINE)
        self.api_key = os.getenv("OCR_SPACE_API_KEY", "").strip()
        self.problem: Optional[str] = None if self.api_key else (
            "OCR isn't set up on the server. Set OCR_SPACE_API_KEY (see the README).")
        self.failures = 0  # pages in a row OCR.space failed on
        self.last_error: Optional[str] = None  # what OCR.space answered when it last failed
        self.pdf: Optional[pdfium.PdfDocument] = None

    def read(self, index: int) -> Optional[str]:
        """The page's text, or None if OCR can't be used (see problem) or failed on this page."""
        if self.problem:
            return None
        if self.pdf is None:
            try:
                with _pdfium_lock:
                    self.pdf = pdfium.PdfDocument(self.stream)  # reads the same stream as pypdf, seeking each time
            except pdfium.PdfiumError as exc:
                logger.warning("PDFium could not open a PDF for OCR: %s", exc)
                self.problem = "Its pages couldn't be drawn as images to send to OCR."
                return None
        try:
            image = _jpeg(self._draw(index))
        except Exception:
            logger.warning("Could not draw page %d of a PDF for OCR", index + 1, exc_info=True)
            return None
        try:
            text = _ocr_space(image, self.api_key, self.engine)
        except _OcrError as exc:
            logger.warning("OCR.space didn't read page %d of a PDF: %s", index + 1, exc)
            self.failures += 1
            self.last_error = f"OCR.space answered: {exc}"
            if exc.refused or self.failures >= OCR_MAX_FAILURES:  # the rest would fail too: stop sending them
                self.problem = self.last_error
            return None
        self.failures = 0
        return text

    def _draw(self, index: int) -> Any:
        assert self.pdf is not None
        with _pdfium_lock:
            page = self.pdf[index]
            try:
                width, height = page.get_size()
                scale = min(OCR_DPI / 72, OCR_MAX_PIXELS / max(width, height, 1))
                bitmap = page.render(scale=scale, grayscale=True)
                try:
                    return bitmap.to_pil().copy()  # the image shares the bitmap's memory until copied
                finally:
                    bitmap.close()
            finally:
                page.close()

    def close(self) -> None:
        if self.pdf is not None:
            with _pdfium_lock:
                self.pdf.close()
            self.pdf = None


def _jpeg(image: Any) -> bytes:
    """A page's image as a JPEG of at most OCR_MAX_BYTES, made smaller until it fits."""
    while True:
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80, optimize=True)
        if out.tell() <= OCR_MAX_BYTES or min(image.size) < 600:
            return out.getvalue()
        image = image.resize((image.width * 4 // 5, image.height * 4 // 5))


_MARKDOWN = re.compile(r"^#{1,6} +|\*\*", re.MULTILINE)  # Engine 3 marks headings and bold text as Markdown


def _ocr_space(image: bytes, api_key: str, engine: int) -> str:
    """The text OCR.space reads in a JPEG image. Raises _OcrError."""
    form = {"base64Image": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
            "OCREngine": engine, "language": "auto", "detectOrientation": "true", "scale": "true"}
    request = urllib.request.Request(OCR_SPACE_URL, data=urllib.parse.urlencode(form).encode(),
                                     headers={"apikey": api_key})
    try:
        with urllib.request.urlopen(request, timeout=OCR_TIMEOUT) as response:
            answer = json.loads(response.read())
    except urllib.error.HTTPError as exc:  # e.g. 403 {"error": "E555: API key not valid", ...}
        raise _OcrError(_ocr_error(exc.read()) or f"HTTP {exc.code}", refused=exc.code < 500) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:  # unreachable, timed out, not JSON
        raise _OcrError(f"it couldn't be reached ({exc})") from exc
    results = answer.get("ParsedResults") if isinstance(answer, dict) else None
    result = results[0] if results and isinstance(results[0], dict) else {}
    if str(result.get("FileParseExitCode")) != "1":
        raise _OcrError(_ocr_error(result.get("ErrorMessage")) or _ocr_error(answer) or "it couldn't read the page")
    return _MARKDOWN.sub("", str(result.get("ParsedText") or ""))


def _ocr_error(detail: Any) -> str:
    """OCR.space's error message, from an answer's body or its ErrorMessage (a string or a list of them)."""
    if isinstance(detail, bytes):
        try:
            detail = json.loads(detail)
        except ValueError:
            return detail.decode("utf-8", "replace").strip()[:300]
    if isinstance(detail, dict):
        detail = detail.get("error") or detail.get("ErrorMessage")
    if isinstance(detail, list):
        detail = " ".join(str(item) for item in detail if item)
    return str(detail or "").strip()[:300]


def _json_records(data: bytes) -> List[Any]:
    try:
        parsed = json.loads(_decode(data))
    except json.JSONDecodeError as exc:
        raise IngestError(f"The file isn't valid JSON (line {exc.lineno}: {exc.msg}).") from exc
    if isinstance(parsed, dict):
        return [parsed]
    if not isinstance(parsed, list):
        raise IngestError("A .json file must hold an array of records.")
    return parsed


def _jsonl_records(lines: Iterable[str]) -> Iterator[Any]:
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestError(f"Line {number} isn't valid JSON ({exc.msg}).") from exc


def _record_text(record: Dict[Any, Any]) -> str:
    for field in TEXT_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


def _metadata(fields: Dict[Any, Any], parse_numbers: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or not key.strip():
            continue  # csv puts surplus cells under the key None
        if parse_numbers and isinstance(value, str) and _WHOLE_NUMBER.fullmatch(value.strip()):
            value = int(value)  # CSV cells are all text: "52" -> 52, to match JSON uploads
        cleaned = _metadata_value(value)
        if cleaned is not None:
            out[key.strip()] = cleaned
    return out


def _metadata_value(value: Any) -> Any:
    """Convert a value to a type Pinecone metadata accepts: string, number, boolean or list of strings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value.strip()[:MAX_METADATA_CHARS] or None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip()[:MAX_METADATA_CHARS] for item in value if item is not None]
        return [item for item in items if item] or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:MAX_METADATA_CHARS]
    return None
