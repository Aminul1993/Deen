"""Turn an uploaded file into passages ready to embed and store in Pinecone.

Used by the admin page (see the Admin section of main.py). Supported files:

- .txt, .md   Plain text, split into overlapping passages.
- .pdf        The text of each page, split into passages. Each passage keeps its page number.
              Scanned PDFs have no text layer and are rejected.
- .json       An array of records (or a single record).
- .jsonl      One record per line.
- .csv        One record per row, with a header row.

A record needs a "text" or "content" field. Its other fields (surah, ayah, collection,
hadith_number, grade, ...) are kept as metadata, so answers can cite them. A record's "id" is
ignored: vector ids are generated so a file can be deleted again. Long records are split, and
every part keeps the record's metadata.

Files are read as a stream (FileReader), so a large upload needn't fit in memory. The exception
is .json: an array is parsed whole, so .json files are limited to MAX_JSON_BYTES.
"""

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, BinaryIO, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from pypdf import PdfReader

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
    """

    def __init__(self, filename: str, stream: BinaryIO, size: int) -> None:
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
        self.skipped_records = 0
        self.page_count: Optional[int] = None  # a PDF's number of pages, once reading has started

    def __iter__(self) -> Iterator[Passage]:
        count = 0
        for passage in self._passages():
            count += 1
            yield passage
        if not count:
            if self.skipped_records:
                raise IngestError(f'None of the {self.skipped_records} records has a "text" or "content" field to index.')
            if self.extension == ".pdf":
                raise IngestError("The PDF has no text layer (it may be scanned). Run OCR on it, then upload it again.")
            raise IngestError("The file has no text to index.")

    def _passages(self) -> Iterator[Passage]:
        if self.extension in (".txt", ".md"):
            for block in _text_blocks(_lines(self.stream)):
                yield from (Passage(chunk, {}) for chunk in chunk_text(block))
        elif self.extension == ".pdf":
            pages = _pdf_pages(self.stream)
            self.page_count = len(pages)
            yield from _pdf_passages(pages)
        elif self.extension == ".json":
            yield from self._records(_json_records(self.stream.read()))
        elif self.extension == ".jsonl":
            yield from self._records(_jsonl_records(_lines(self.stream)))
        else:  # .csv
            yield from self._records(csv.DictReader(_lines(self.stream)), parse_numbers=True)

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


def parse_file(filename: str, data: bytes) -> ParsedFile:
    """All of a small file's passages at once."""
    reader = FileReader(filename, io.BytesIO(data), len(data))
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


def _pdf_passages(pages: Sequence[Any]) -> Iterator[Passage]:
    for number in range(len(pages)):
        try:
            page_text = pages[number].extract_text() or ""
        except Exception as exc:
            raise IngestError(_BAD_PDF) from exc
        yield from (Passage(chunk, {"page": number + 1}) for chunk in chunk_text(page_text))


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
