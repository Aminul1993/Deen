"""Vercel Blob storage for the PDFs kept as books (see the Books section of main.py).

When BLOB_READ_WRITE_TOKEN is set, books are uploaded to that Vercel Blob store instead of this
server's disk, so they survive redeploys on hosts whose disk doesn't last, and several servers can
share them. Without it, main.py keeps them in data/books/ as before.

    BLOB_READ_WRITE_TOKEN  the store's read-write token (VERCEL_BLOB_READ_WRITE_TOKEN also works)
    BLOB_ACCESS            "private" (default) or "public": must match the store's access mode

Books are uploaded with the official SDK (vercel-blob), under books/<index>/<text>/<file id>-<random>.pdf,
and the address Blob returns is kept with the upload's row in Redis.

Readers get a book through the app, never from Blob directly: blob_response() asks Blob for the
byte range the browser asked for and streams it back. That works for private stores, where only
the token can read, and keeps pdf.js loading a large book a range at a time. The SDK's downloads
don't take a range, so this is a plain HTTPS request to the blob's delivery URL with the token,
as Vercel documents for reading private blobs without the SDK.
"""

import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, BinaryIO, Dict, Iterator, Mapping, Optional

from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from vercel.blob import sync as blob

logger = logging.getLogger("scripture_rag.storage")

MULTIPART_BYTES = 100 * 1024 * 1024  # Vercel recommends multipart uploads above this size
PART_BYTES = 8 * 1024 * 1024  # each part but the last must be at least 5 MiB
RETRIES = 3  # when Blob is rate limited or briefly unavailable; the SDK itself doesn't retry
READ_TIMEOUT_SECONDS = 30
READ_BLOCK = 64 * 1024
DELIVERY_DOMAIN = ".blob.vercel-storage.com"  # every blob's delivery URL is https://<store>.<access><this>/...
FORWARDED_HEADERS = ("Range", "If-Range", "If-None-Match")  # from the browser to Blob
RETURNED_HEADERS = ("Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified")  # and back

BlobError = blob.BlobError


class BlobMissing(Exception):
    """Blob has no such file (any more)."""


class BlobUnavailable(Exception):
    """Blob couldn't be reached, or refused the request."""


def token() -> str:
    """The read-write token, or "" when books stay on disk. Read on every call, like db.client()."""
    return (os.getenv("BLOB_READ_WRITE_TOKEN") or os.getenv("VERCEL_BLOB_READ_WRITE_TOKEN") or "").strip()


def enabled() -> bool:
    return bool(token())


def access() -> str:
    value = os.getenv("BLOB_ACCESS", "private").strip().lower() or "private"
    if value not in ("private", "public"):
        raise ValueError(f'BLOB_ACCESS must be "private" or "public", not {value!r}')
    return value


def describe() -> str:
    """Where new books go, for the log and the admin page: "in Vercel Blob (private store)" or "on this server's disk"."""
    if not enabled():
        return "on this server's disk"
    try:
        return f"in Vercel Blob ({access()} store)"
    except ValueError as exc:
        return f"in Vercel Blob, but {exc}"


def _with_retries(call: Any) -> Any:
    for attempt in range(RETRIES + 1):
        try:
            return call()
        except (blob.BlobServiceRateLimited, blob.BlobServiceNotAvailable) as exc:
            if attempt == RETRIES:
                raise
            delay = max(getattr(exc, "retry_after", 0) or 0, 2 ** attempt)
            logger.warning("Vercel Blob is busy (%s); retrying in %ds", exc, delay)
            time.sleep(delay)


def upload(pathname: str, stream: BinaryIO) -> str:
    """Upload a PDF from a seekable stream and return its delivery URL, which callers must keep.

    Every upload gets a new random suffix (books/…/<file id>-<random>.pdf), so a pathname is never
    reused: Vercel's CDN can serve a deleted or overwritten blob's old state for up to a minute,
    which would break a book deleted and uploaded again. Large files go in parts, so a 200 MB book
    needs only one part in memory at a time. Raises BlobError (a credentials, store or access-mode
    problem, or a failure that outlasted the retries).
    """
    mode = access()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    options = {"access": mode, "content_type": "application/pdf", "add_random_suffix": True}

    def send() -> str:
        stream.seek(0)
        if size <= MULTIPART_BYTES:
            return blob.put_blob(pathname, stream, content_length=size, **options).url
        with blob.multipart_upload_blob(pathname, **options) as parts:
            while part := stream.read(PART_BYTES):
                parts.upload_part(part)
        return parts.result.url

    return _with_retries(send)


def delete(url: str) -> None:
    """Delete a blob by its delivery URL. Deleting one that's already gone succeeds."""
    _with_retries(lambda: blob.delete_blob(url))


def _checked(url: str) -> urllib.parse.SplitResult:
    """Only Vercel Blob delivery URLs, over HTTPS: the token must never be sent anywhere else."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not (parts.hostname or "").endswith(DELIVERY_DOMAIN):
        raise BlobUnavailable(f"{url!r} isn't a Vercel Blob address")
    return parts


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Blob doesn't redirect; refusing to follow keeps the token from going to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def _open(request: urllib.request.Request) -> Any:
    return _opener.open(request, timeout=READ_TIMEOUT_SECONDS)


def _chunks(upstream: Any) -> Iterator[bytes]:
    while chunk := upstream.read(READ_BLOCK):
        yield chunk


def _content_disposition(filename: str) -> str:
    quoted = urllib.parse.quote(filename)
    return f"inline; filename*=utf-8''{quoted}" if quoted != filename else f'inline; filename="{filename}"'


def _read_headers(url: str) -> Dict[str, str]:
    """Headers to read a blob with: the token, for a private store."""
    host = _checked(url).hostname or ""
    headers = {"User-Agent": "Deen-books/1.0"}
    if f".private{DELIVERY_DOMAIN}" in f".{host}":
        if not token():
            raise BlobUnavailable("BLOB_READ_WRITE_TOKEN isn't set, so private books can't be read")
        headers["Authorization"] = f"Bearer {token()}"
    return headers


def download(url: str, sink: BinaryIO) -> None:
    """Copy a whole book from Blob into sink, e.g. to read its pages again.

    Raises BlobMissing when Blob doesn't have it, BlobUnavailable when Blob can't be read.
    """
    try:
        upstream = _open(urllib.request.Request(url, headers=_read_headers(url)))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise BlobMissing(url) from None
        raise BlobUnavailable(f"Vercel Blob answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise BlobUnavailable("Vercel Blob couldn't be reached") from exc
    try:
        for chunk in _chunks(upstream):
            sink.write(chunk)
    except OSError as exc:  # the connection dropped partway
        raise BlobUnavailable("Vercel Blob stopped sending the book") from exc
    finally:
        upstream.close()


def blob_response(url: str, request_headers: Mapping[str, str], filename: str,
                  extra_headers: Optional[Dict[str, str]] = None) -> Response:
    """Stream a book from Blob: the whole file, or the byte range the browser asked for (206).

    Raises BlobMissing when Blob doesn't have it, BlobUnavailable when Blob can't be read.
    """
    headers = _read_headers(url)
    for name in FORWARDED_HEADERS:
        if request_headers.get(name):
            headers[name] = request_headers[name]

    reply = {**(extra_headers or {}), "Content-Disposition": _content_disposition(filename)}
    try:
        upstream = _open(urllib.request.Request(url, headers=headers))
    except urllib.error.HTTPError as exc:
        error_headers = exc.headers or {}
        kept = {name: error_headers[name] for name in RETURNED_HEADERS if error_headers.get(name)}
        if exc.code in (304, 416):  # unchanged since the browser's copy, or a range past the end
            return Response(status_code=exc.code, headers={**reply, **kept})
        if exc.code == 404:
            raise BlobMissing(url) from None
        raise BlobUnavailable(f"Vercel Blob answered HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise BlobUnavailable("Vercel Blob couldn't be reached") from exc

    kept = {name: upstream.headers[name] for name in RETURNED_HEADERS if upstream.headers.get(name)}
    return StreamingResponse(_chunks(upstream), status_code=upstream.status, media_type="application/pdf",
                             headers={**reply, **kept}, background=BackgroundTask(upstream.close))
