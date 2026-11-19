# pdf.js

[pdf.js](https://mozilla.github.io/pdf.js/) 5.4.530 (Apache License 2.0, see `LICENSE`), from the npm package
`pdfjs-dist`, `legacy/build/` (the build for older browsers). The books page (`static/books.html`) uses it
to show uploaded PDFs one page at a time. It's kept here, not loaded from a CDN, so the site works without
any third-party requests.

`wasm/` holds the decoders for JPEG 2000 images (OpenJPEG) and ICC colour profiles (qcms), with their licences.
Not included: `cmaps/` (only needed for PDFs that use predefined CJK character maps) and `standard_fonts/`
(PDFs that don't embed the standard 14 fonts fall back to system fonts).

To update: download `pdfjs-dist` from npm, check its `dist.integrity`, and copy the same files.
