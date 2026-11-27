# Deen — Quran & Hadith Q&A API

A FastAPI service that answers questions about Islam from the **Quran and Hadith**, using retrieval-augmented generation. The passages must **already be indexed** in one Pinecone index, with **one namespace per text**, for example `quran`, `sahih_bukhari` and `sahih_muslim`. The public endpoints only read the index. A token-protected [admin page](#admin-page) can upload files into it, delete them again, and swap the Groq and Pinecone credentials. Nothing ever creates an index. Uploaded PDFs are also kept, so anyone can read them page by page on the [books page](#books-page), and an answer's sources link to the page each passage came from.

A Groq-hosted LLM (`openai/gpt-oss-120b` by default, temperature 0.1) writes each answer from an Islamic perspective, following the **Hanafi madhhab**. Its rules:

- **Grounded:** it may only use the retrieved passages. When they don't settle a question, it says so, and for rulings that depend on someone's circumstances it suggests asking a qualified Hanafi scholar.
- **Rulings:** it may say what is obligatory, recommended, permitted, disliked or forbidden when the passages support it, and presents the ruling as the Hanafi position.
- **Cited:** every claim cites its passage, e.g. "(Quran, Surah 2, Ayah 153)" or "(Sahih al-Bukhari 52, graded Sahih)". A hadith's grade goes with every citation, and a point resting on a weak (da'if) hadith is flagged.
- **Your language:** the answer comes back in the language of the question, such as English, Arabic or Bengali.

Product decisions behind these rules are recorded in [PRODUCT.md](PRODUCT.md).

```
POST /query ──►  condense → retrieve → generate
                     │          │           │
 Groq: rewrite a follow-up      │           Groq (openai/gpt-oss-120b)
 as a standalone question       │
 (skipped without history)      Pinecone Inference embed
                                + index.query per namespace
```

## Requirements

- Python 3.10+
- An existing Pinecone index whose vectors carry metadata with:
  - the passage text under `text` or `content`
  - citation fields, which can use any of these keys:

    | Field | Accepted metadata keys |
    |---|---|
    | Quran surah / ayah | `surah`, `sura`, `surah_number` / `ayah`, `aya`, `ayat`, `ayah_number` |
    | Hadith collection | `collection`, `hadith_collection`, `collection_name` |
    | Hadith number | `hadith_number`, `hadithNumber`, `hadith_no`, `hadith_num`, `number` |
    | Hadith grade | `grade`, `hadith_grade`, `grading`, `authenticity` |
    | Other | `title`, `book` (`book_name`), `chapter`, `verse` |

    If your hadith records use other keys, add them to `CITATION_FIELDS` in [main.py](main.py). Fields that aren't citation fields are still passed to the model and returned under `metadata`.
- A Pinecone API key and a Groq API key
- A Redis database (e.g. a free Redis Cloud database) for the credentials, the list of uploaded files and upload progress
- Optionally, a [Vercel Blob](https://vercel.com/docs/vercel-blob) store for the uploaded PDFs; without one they're kept on the server's disk (see [Storing books in Vercel Blob](#storing-books-in-vercel-blob))
- Optionally, an [OCR.space](https://ocr.space/ocrapi) API key (free), to read scanned PDFs (see [Scanned PDFs (OCR)](#scanned-pdfs-ocr))

Citations are built like this:

| Metadata | Reference |
|---|---|
| `surah: 2, ayah: 153` in namespace `quran` | `Quran (Surah 2, Ayah 153)` |
| `collection: "Sahih al-Bukhari", hadith_number: 52, grade: "Sahih"` | `Sahih al-Bukhari 52, graded Sahih` |
| plus `book: "Book of Faith"` (or `book: 2` → `Book 2`) | `Sahih al-Bukhari 52 (Book of Faith), graded Sahih` |
| `hadith_number: 10, grade: "Da'if"`, no collection, namespace `abu_dawud` | `Abu Dawud 10, graded Da'if` |
| `title: "For good in both worlds", surah: 2, ayah: 201`, in any namespace | `Quran (Surah 2, Ayah 201)` |

A surah is always cited as the Quran's, whatever the record's title or its text's name (`quran_bangla` too). To cite a commentary by surah and ayah under its own name, give its records a `collection`.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then set ADMIN_TOKEN and REDIS_URL
uvicorn main:app --host 0.0.0.0 --port 8000
```

Behind a reverse proxy, add `--proxy-headers --forwarded-allow-ips=<the proxy's address>`, so the per-visitor question limit (see [Errors](#errors)) sees each visitor's address instead of the proxy's.

Run the tests (Pinecone, Groq and Redis are faked, so they need no credentials or network):

```bash
pip install -r requirements-dev.txt
pytest
```

Then open `http://localhost:8000/admin`, sign in with `ADMIN_TOKEN` and enter the Groq and Pinecone credentials (see [Credentials](#credentials)). On startup the app connects with the stored credentials. If they're missing or don't work, it still starts, so they can be fixed on the admin page, but questions fail until then (503 when credentials are missing). Interactive API docs are served at `http://localhost:8000/docs`.

### Chat UI

Open `http://localhost:8000/` for a chatbot web page served by the same app (no separate build or server). It lets you:

- pick one text or **All texts** (the list comes from `GET /texts`) and the number of passages (`top_k`)
- choose the page's language: English, বাংলা (Bengali) or العربية (Arabic) (see [Page language](#page-language))
- ask questions and read answers with their numbered sources: citation (with the hadith grade), text and excerpt. A passage from an uploaded PDF links to its book, at its page, e.g. **Read “Bahishti Zewar”, page 34**, which opens the [books page](#books-page) in a new tab
- read the uploaded books page by page with the **Books** button, shown once there is at least one
- read the duas, or the Namaz Shikkha steps, one by one with the **Duas** and **Namaz Shikkha** buttons (see [Duas and Namaz Shikkha](#duas-and-namaz-shikkha))
- choose a location and see the day's azan times, with a countdown to the next one (see [Azan times](#azan-times))
- work out the zakat due on their wealth with the **Zakat** button, following the Hanafi school (see [Zakat calculator](#zakat-calculator))
- see API errors (unknown text, Groq or Pinecone failures) inline in the chat

Follow-up questions such as "tell me more" or "what about the hadith?" work: the page sends the last 4 exchanges with each question (see [Follow-up questions](#follow-up-questions)). When a follow-up was rewritten before searching, the answer shows a "Searched for: …" line. **New chat** clears the context, and reloading the page does too.

#### Page language

The globe menu in the top bar translates the chat page and the books page into English, Bengali or Arabic: buttons, labels, messages, the azan times and their prayer names, the reader buttons and the example questions. In Arabic the whole page reads right to left. Numbers, dates and times are written the language's way, e.g. Bengali digits. The first visit uses the browser's language when it's one of the three, and English otherwise; the choice is kept in this browser (`localStorage`) and shared by both pages. It's also the preferred language for books: the books page lists books in it first.

The menu changes only the page's own text. **Answers still come in the language of the question** (see [Answer language](#answer-language)), messages already in the conversation stay as they were, and error messages from the server stay in English. Proper names stay as they are: city names, the calculation methods, and the texts' names. The admin page is English only.

The translations are in [static/i18n.js](static/i18n.js). To change a wording, edit it there in all three languages; `pytest` checks that every language has every string and that every string the pages use exists. To add a language, add it to `LANGUAGES` and `STRINGS` in that file, with its plural forms (the test lists which forms each language needs).

### Books page

Open `http://localhost:8000/books`, or the **Books** button on the chat page, to read the PDFs uploaded on the [admin page](#admin-page). It works like a small library:

- **Shelves by language.** Books are grouped by the language chosen when they were uploaded. The page's language comes first, then the others by name, then books uploaded without a language. Each card shows the title (from the file name: `Bahishti_Zewar.pdf` becomes "Bahishti Zewar"), the language, the number of pages and the text it was uploaded to.
- **One page at a time.** A book opens in a reader that draws one page at a time with [pdf.js](static/vendor/pdfjs/README.md), fitted to the window's width (at most 860 pixels wide at 100%). Turn pages with **Previous** and **Next**, the arrow keys, by typing a page number, or by swiping on a touch screen. Zoom from 50% to 300%; the zoom is remembered. A page's text can be selected, copied, found with the browser's search (Ctrl+F) and read by a screen reader, when the PDF has text (a scan has only pictures). **Open PDF** opens the file itself in the browser's own viewer. Only the parts of the PDF that the pages shown need are downloaded, so a large book opens quickly.
- **Your place is saved** in this browser (`localStorage`, one entry per book, `deen-book:<text>/<book id>`), every time you turn a page. Opening a book without a page takes you back to where you were, and books you've started appear under **Continue reading**, most recent first, with a progress bar. Nothing about your reading is sent to the server.
- **Links to a page.** The address of the page you're on, `/books?text=<text>&book=<book id>&page=<n>`, opens the book there. The links in an answer's sources are such addresses. A link to a page doesn't move your saved place: if you were elsewhere in the book, the reader offers **Continue from page N**, and your place moves only once you turn a page.

PDFs uploaded before this page existed weren't kept, so they aren't listed; upload them again to add them. Every PDF that's uploaded can be read, and downloaded, by anyone who can open the site, so upload only books you may publish.

#### Azan times

A bar under the top bar shows the next azan and how long until it, e.g. `Dhaka · Next: Asr 3:36 PM · in 1 h 5 min`. Click it to open the day's times (Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha) and to choose the location:

- **A city** from the list, grouped by country (Bangladesh, India, Pakistan, the Gulf, the UK, North America and more). Choosing a city also picks the calculation method usually used there, for example Karachi for Bangladesh, Umm al-Qura for Saudi Arabia and ISNA for North America.
- **Use my location**, from the browser's location (asked for permission first). It uses the browser's time zone and the method of the nearest listed city. Browsers only allow this over HTTPS or on `localhost`, so the button is hidden otherwise.

Under **Calculation method** you can change the method (Karachi, Muslim World League, ISNA, Egypt, Umm al-Qura, Gulf, Kuwait, Qatar, Singapore) and the Asr method. **Asr defaults to Hanafi** (when a shadow is its noon length plus twice the object's height), in line with the rest of Deen; the standard Shafi'i, Maliki and Hanbali time is one choice away.

The times are calculated in the browser by [static/prayer-times.js](static/prayer-times.js), from the sun's position (U.S. Naval Observatory formulas, accurate to about a minute). No request leaves the page and the location is stored only in the browser (`localStorage`). For a city in another time zone, times are shown in that city's local time. Where twilight never gets dark enough (high latitudes in summer), Fajr and Isha are capped at the method's share of the night. The times can differ by a few minutes from a local mosque's timetable, which may add safety minutes, and the dialog says so. To add a city, add it to `CITIES` in that file.

#### Zakat calculator

The **Zakat** button opens a calculator that works out the zakat on a person's wealth, following the Hanafi school. Everything is calculated in the browser by [static/zakat.js](static/zakat.js): no figure is sent to the server.

1. **Today's prices.** Choose the currency and the unit gold and silver are weighed in (grams, tola or bhori of 11.664 g, or troy ounces), then enter today's local price per unit of gold (for the kind owned, such as 22 carat) and of silver. There are no live prices: rates differ by country and purity, and fetching them would send requests outside the app.
2. **What you own:** gold and silver by weight, cash in hand and in the bank, money owed to you, goods for sale, and shares, funds and savings schemes, by value.
3. **What you owe:** debts due now, including this year's instalments of long-term loans.

The result updates as you type: zakatable assets, debts, the net zakatable wealth, the nisab with its weight, which rule set it, and the zakat due. The amount due stays in view at the bottom, next to **Ask Deen about zakat**, which closes the calculator and asks the chat what the Quran and hadith say, so the evidence comes with citations from the indexed texts.

The rules (see the comment at the top of [static/zakat.js](static/zakat.js)):

| Rule | Hanafi position used |
|---|---|
| Rate | 2.5% (a fortieth) of zakatable wealth at or above the nisab, once it has been held for a full lunar year |
| Nisab | Gold: 87.48 g (7.5 tola, 20 mithqal). Silver: 612.36 g (52.5 tola, 200 dirhams) |
| Which nisab | Gold alone is measured against the gold nisab, and silver alone against the silver one. Anything else (gold with silver, either with money, or money alone) is added up by value and measured against the **silver** nisab, which is better for the poor. **Nisab: Gold, for all wealth** is offered for those whose scholar advises it |
| Jewellery | Gold and silver jewellery counts, worn or not. Gems don't, unless kept for sale |
| Debts | Debts due now, and this year's instalments of long-term loans, are taken off first |
| Not zakatable | Home, car, household goods, personal belongings |

So 80 g of gold on its own owes nothing (it's below 87.48 g), but the same gold with any cash is measured against the silver nisab and does. For a business, shares held for dividends, loans and other complex cases, the calculator says to ask a qualified Hanafi scholar.

Amounts can be typed with Bengali or Arabic-Indic digits and with thousands separators (`1,25,000`, `১,২৫,০০০`). The currency defaults to the one used in the azan times city's country, then the browser's region, then the page's language, and the unit to bhori when the page is in Bengali. The prices, currency, unit and nisab choice are remembered in this browser (`localStorage`); the amounts aren't, so they aren't left on a shared computer. Changing the unit rewrites the prices and weights in it without changing the result.

The calculator's arithmetic is tested by `tests/test_zakat.py`, which runs `static/zakat.js` with QuickJS (`quickjs` in `requirements-dev.txt`), so the tests need no browser or Node.js.

#### Duas and Namaz Shikkha

The **Duas** and **Namaz Shikkha** buttons open a reader that shows one passage at a time: a dua, or a step of the prayer. Each shows its section, title, Arabic, transliteration, meaning or instruction, and source. Use **Previous** and **Next**, the left and right arrow keys, or type a number to jump. The list wraps around at both ends, and the page remembers where you were in each reader in this browser.

Nothing is built in. Each reader shows the files an admin uploads on the [admin page](#admin-page) to its text, in upload order, and each file's records in file order:

| Button | Text (namespace) |
|---|---|
| **Duas** | `duas` |
| **Namaz Shikkha** | `namaz` |

A button appears only when its text has at least one passage. For Namaz Shikkha, put the steps in a file in the order they're done. Each record needs a `text` field (the meaning, or the instruction). Optional fields get their own place in the reader:

| Field | Shown as |
|---|---|
| `section` (or `category`, `topic`) | Small heading above the title, e.g. `Wudu` or `Morning duas` |
| `title` | Heading |
| `arabic` (or `arabic_text`, `text_ar`) | Large Arabic text, right to left |
| `transliteration` (or `translit`) | Italic line |
| `surah` and `ayah`, or `collection`, `hadith_number`, `grade` and `book` | Citation, e.g. `Quran (Surah 2, Ayah 201)` or `Sahih al-Bukhari 52, graded Sahih` |
| anything else, e.g. `step` | Small "Step: …" line, with the source file |

A hadith number without a `collection` isn't shown as a citation, because it wouldn't say which book it's from; it's listed with the other fields instead.

```json
{"section": "General", "title": "For good in both worlds", "arabic": "رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً وَقِنَا عَذَابَ النَّارِ", "transliteration": "Rabbana atina fid-dunya hasanatan wa fil-akhirati hasanatan wa qina 'adhaban-nar", "text": "Our Lord, give us good in this world and good in the Hereafter, and protect us from the punishment of the Fire.", "surah": 2, "ayah": 201}
```

Both texts are also searched like any other text when someone asks a question. Passages indexed some other way, not through the admin page, don't appear in the readers. To add another reader, add its namespace and button name to `READERS` in [main.py](main.py).

**Arabic and Bengali:**
- Questions, answers and excerpts in Arabic display right to left. The question box switches direction as you type.
- Bracketed citations stay in the right place when English and Arabic are mixed.
- Arabic and Bengali text get extra line spacing and a language tag, so screen readers switch voice.

The page is [static/index.html](static/index.html) plus the azan time calculator [static/prayer-times.js](static/prayer-times.js) and the translations [static/i18n.js](static/i18n.js), and loads nothing from outside the app, so it works offline. The books page, [static/books.html](static/books.html), doesn't either: pdf.js is kept in [static/vendor/pdfjs/](static/vendor/pdfjs/) (Apache License 2.0), and loaded only when a book is opened. The fonts are self-hosted from [static/fonts/](static/fonts/) under the SIL Open Font License, with a licence file per family:

- Source Serif 4 for Latin text
- Noto Naskh Arabic, about 90 KB
- Noto Serif Bengali, about 190 KB

A browser downloads the Arabic or Bengali font only when the page shows that script.

On touch devices, Enter adds a new line and the send button sends. With a mouse or trackpad, Enter sends and Shift+Enter adds a new line. If a request fails because of the server, Groq or Pinecone, the error shows a **Try again** button.

### Admin page

Open `http://localhost:8000/admin` and sign in with the `ADMIN_TOKEN` from `.env`. Without an `ADMIN_TOKEN` of at least 24 characters, the page is turned off and its API returns 403: there's no limit on sign-in attempts, so a short token could be guessed. Generate a token with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Credentials

The Groq API key and model, and the Pinecone API key, index name and embedding model, are kept only in the Redis database (`REDIS_URL`) and changed on the admin page. Leave a key blank to keep the current one. The models default to `openai/gpt-oss-120b` and `multilingual-e5-large`. If Groq retires a model (as it did `llama-3.3-70b-versatile`), questions fail with a 502 until another one is entered here; the admin page checks that the key can use it. Before anything is saved, the new values are tested:

- Groq: the key must be accepted and able to use the model.
- Pinecone: the key must open the index, the index must be a standard (dense) index, and the embedding model must produce vectors of the index's dimension. Pinecone's newer "document" indexes embed text themselves and refuse the vectors Deen writes, so they're rejected with a message saying so; create a standard index with the model's dimension (1024 for `multilingual-e5-large`) and cosine metric.

Only the service whose settings changed is tested, so you can enter Groq before Pinecone or the other way round. If a check fails, nothing changes and the page says why. If the checks pass, the values are saved and new questions use them right away, without a restart, in every worker process: each request checks the stored settings and reconnects when they've changed. Until every credential is entered, the page lists what's missing and questions return 503.

**Moving from `.env`.** On the first start, when the database has no settings yet, any `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_EMBEDDING_MODEL`, `GROQ_API_KEY` and `GROQ_MODEL` in the environment are copied into it once, and the log says so. After that, those variables are ignored, so remove them from `.env`.

The database stores the keys in plain text. Keep `REDIS_URL` secret (it contains the password), use a database only this app can reach, and use a `rediss://` (TLS) address if your host offers one. Every key starts with `deen:`, so the database can be shared with other apps.

**Upload files.** Choose a text (namespace), or type a new name to create one, choose the files' **language** (English, Bengali, Arabic or Urdu), then pick one or more files of up to 200 MB each (.json up to 50 MB). Each file is split into passages, embedded with the configured model (`input_type="passage"`) and upserted into that namespace. New texts appear in the chat page's text list, and in its "All texts" search, within about a minute: the chat reuses Pinecone's index statistics for 60 seconds instead of fetching them for every question.

The language is stored with the file and with each of its passages (`language`, e.g. `"bn"`), and the books page shelves books by it. A record's own `language` field wins over the one chosen. To offer another language, add its code and name to `LANGUAGES` in [main.py](main.py).

| File | How it's split | Metadata kept |
|---|---|---|
| `.txt`, `.md` | Passages of about 1,000 characters, overlapping by about 150 and ending at a paragraph, sentence or word break | `source_file`, `language` |
| `.pdf` | The same, page by page. Pages without readable text are read with [OCR](#scanned-pdfs-ocr). **The PDF itself is kept as a book** (see below) | `source_file`, `language`, `page` |
| `.json` (array), `.jsonl`, `.csv` | One record per item, line or row. Each needs a `text` or `content` field. Long records are split, and every part keeps the record's fields | `source_file`, `language` and every other field of the record, such as `surah`, `ayah`, `collection`, `hadith_number`, `grade`, `book` |

**PDFs are kept as books.** Once a PDF's passages are stored, the file itself is kept, whether it was uploaded or downloaded from a web address, and can be read on the [books page](#books-page). Uploading a new version of it replaces the book too, and deleting the file deletes it. If the PDF can't be kept, the upload still succeeds and its passages can be cited, but the upload result says why the file isn't a book (and so does the log). Where books are kept is shown on the admin page, under the texts in the index:

- **In [Vercel Blob](https://vercel.com/docs/vercel-blob)**, when `BLOB_READ_WRITE_TOKEN` is set (see [Storing books in Vercel Blob](#storing-books-in-vercel-blob)). Use this when the server's disk doesn't last across deploys, or with several servers.
- **Otherwise on the server's disk**, in `data/books/<index>/<text>/<file id>.pdf`. Keep that folder on persistent storage and back it up, like the Redis database. With several servers, they all need the same `data/` folder (shared storage), since any of them may be asked for a book.

#### Scanned PDFs (OCR)

A PDF page's own text is used when it's readable. A page is read with OCR instead, in the language chosen for the upload, when its text is:

- **missing**: a scanned page is only a picture;
- **garbled**: mostly replacement (`�`), private-use or control characters, from a font the PDF doesn't map to Unicode;
- **in an old non-Unicode font**: in a Bengali, Arabic or Urdu file, fewer than a fifth of its letters are in that script, and at least 1 in 20 of its characters are symbols such as `‡ ¨ © ø`. Fonts such as Bijoy or SutonnyMJ turn Bengali into those (`Avjøvn&i Kv‡Q` for আল্লাহর কাছে). A page in plain Latin letters, such as an English preface in a Bengali book, is kept as it is;
- **sparse**: fewer than 40 visible characters on a page with a picture, such as a watermark over a scanned page. The page keeps its own text unless OCR finds more than twice as much. If OCR can't read it yet, its few characters aren't stored (a watermark such as `www.example.org` on every page would only be found by mistake): it waits to be read again, like the pages below.

A page that's blank, or has only a little text (a title) and no picture, isn't sent. The others are drawn as 300 dpi greyscale JPEGs with PDFium (`pypdfium2`), made smaller if needed to stay under 700 KB, and sent one at a time to the [OCR.space API](https://ocr.space/OCRAPI):

- **Bengali, Arabic and Urdu** files go to its **Engine 3**, which reads them almost word for word. Engine 2 turns Bengali into Devanagari and drops Arabic letters, and has no Urdu.
- **English** files, and files without a language, go to **Engine 2**.

OCR takes a few seconds a page, so a 500-page scanned book takes about half an hour; the admin page shows which page it's on and how many were read with OCR, and the upload result says how many pages were. Engine 3 is an AI model: in testing it "corrected" a spelling (রোজাদার to রোযাদার). Its Markdown headings and bold marks are removed. OCR text can have mistakes, so prefer a PDF with real text when there is one.

Set `OCR_SPACE_API_KEY` in `.env` (on Vercel, in the project's environment variables) to a key from [ocr.space/ocrapi/freekey](https://ocr.space/ocrapi/freekey), and restart. It can hold several keys separated by commas (`K1,K2,K3`): one is used until OCR.space refuses it (an invalid key, or its limit reached), then the next. When it asks to slow down (E582), the next key is tried, and once every key has been asked, it waits 1, 2 and then 4 minutes before giving up on the rest of the file, whose pages then wait to be read again. Check OCR.space's terms before using several free keys; the daily limit is per server IP address, whatever the key. The free plan allows **1,000 Engine 3 pages a month** (Bengali, Arabic, Urdu), 25,000 Engine 2 pages a month, and **500 requests a day per server IP address**, so a large Bengali book can use a month's Engine 3 pages; the PRO plan raises the limits. Every page sent leaves the server for OCR.space.

If OCR.space refuses the key or a limit is reached (it answers with an error), or it fails on 3 pages in a row, the rest of the file isn't sent. Without a key, no page is sent.

#### PDFs read partly

Pages OCR couldn't read, for any of those reasons or because it failed on just that page, give no passages (garbled text would only be found by mistake), and the file is still added, even a scanned PDF with no page read at all. The pages are listed with the file (`pending_pages`), and:

- the upload result says how many there are and why, e.g. what OCR.space answered;
- the admin page's list of files marks the file **N pages not read yet** (hover for which), with a **Read N pages again** button.

The button, or `POST /admin/api/files/{id}/ocr?namespace=…`, reads just those pages again, once the limit has reset or the key is set, from the PDF kept as a book (on disk, or downloaded from Vercel Blob). It runs in the background like a large upload, with the same progress, and pages it still can't read stay listed for next time. Pages are read again in the listed order, which puts the ones OCR.space failed on (such as E563, "OCR Engine 3 timed out") after the ones it didn't get to, so a few pages that time out every time can't stop each try after 3 failures before the others are sent. Their passages get the ids after the file's others (`<file id>#<n>`), so deleting the file removes them too; in a [reader](#duas-and-namaz-shikkha) they come after the file's other passages. If the PDF wasn't kept as a book, upload it again instead. A file can be uploaded, read again or deleted by one request at a time: another gets a 409 until it's finished.

#### Storing books in Vercel Blob

Set `BLOB_READ_WRITE_TOKEN` in `.env` to the read-write token of a Blob store (in the Vercel dashboard: the store's settings, or **Add a read-write token env var** when connecting it to a project), and restart. New PDFs then go to that store, under `books/<index>/<text>/<file id>-<random>.pdf`; the address Blob returns is kept with the file's row in Redis. Each upload gets a new random suffix because Vercel's CDN can serve a deleted or replaced blob's old content for up to a minute, which would otherwise break a book deleted and uploaded again. Files over 100 MB go up in 8 MB parts, so a 200 MB book needs little memory, and uploads retry when Blob is rate limited or briefly unavailable.

- **Private or public store.** Private stores (the default, and what `BLOB_ACCESS=private` expects) can only be read with the token. For a public store, set `BLOB_ACCESS=public`; the value must match the store's access mode, which can't be changed after the store is created. If it doesn't match, PDFs aren't kept and the upload result says to check it.
- **Readers never get the Blob address.** `GET /books/{text}/{id}.pdf` asks Blob for the byte range the browser asked for and streams it back, so a private store stays private, and pdf.js still loads a large book a range at a time. The token is only ever sent to `*.blob.vercel-storage.com` over HTTPS, and redirects aren't followed. Every page a reader turns passes through the server, so mind Blob's [download pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing) for very large or popular books.
- **Books kept on disk before Blob was set up** are still served from the disk, and are moved to Blob only if the file is uploaded again. Turning Blob off again works the same way the other round.
- **Not in Blob:** upload parts still go to `data/upload-parts/` while a job runs (they're deleted when it ends), and the credentials, file list and job progress stay in Redis.

The token is a long-lived secret with full access to the store: keep it out of git (`.env` is ignored) and rotate it in the dashboard if it leaks. On Vercel, the SDK prefers its own short-lived OIDC credentials for uploads and deletes, but reading a private book through the server needs the read-write token, so set it there too.

Records without `text` or `content` are skipped and counted in the upload result. A record's own `id` is ignored. Vector ids are `<file-name>-<content-hash>#<n>`. Uploading a file with the same name to the same text again replaces the earlier version: its passages are deleted once the new ones are stored, and the file keeps its original upload time, so it keeps its place in a reader. Files are read as a stream and embedded and stored one batch of 96 passages at a time, so even a 200 MB file needs little memory. The exception is `.json`: an array is parsed whole, which is why `.json` files are limited to 50 MB; save bigger record files as `.jsonl`. Uploads retry when Pinecone rate-limits them, so a large file can take a long time. If a new file fails partway, the vectors already written for it are deleted; if an unchanged file fails while being uploaded again, its earlier copy is kept.

**Or from a web address.** Instead of picking a file, paste a direct link to one, for example a raw file on GitHub. The server downloads it in the background (up to 200 MB; the site must start answering within 30 seconds) and adds it exactly like an uploaded file. A web page is refused before its body is downloaded. The file name comes from the name the site sends, then from the address, then from the file type the site reports, and must be one of the supported types. Web pages (HTML) are refused, with a message asking for a direct file link. Only `http://` and `https://` addresses on the public internet are downloaded: addresses that resolve to private, local or cloud-metadata networks (such as `localhost`, `10.x`, `192.168.x` or `169.254.169.254`) are refused, and so are redirects to them. Each passage stores the address as `source_url`, without its query string or any user name and password, since passages' metadata is returned by the public `/query` API. Downloading the same address again replaces the earlier version, as with a file of the same name.

**Large files.** The admin page sends every file in 4 MB parts (Vercel refuses request bodies over 4.5 MB), then the server processes it in the background, so neither the upload nor the embedding has to fit in one web request:

1. The page starts a job with the file's name and size. Unsupported files, and files over 200 MB, are refused before anything is sent.
2. It sends the parts in order, showing the percentage. A part that fails because of the network is sent again; if the server already has it, the server says how much it has and the page carries on from there.
3. Once all parts have arrived, the server processes the file in a background thread, and the page shows how many passages are stored so far (and, for a PDF, which page it's on and how many were read with OCR). You can close the page now: the job carries on, and the file appears in the list when it's done. Before then, while parts are being sent, the browser asks before leaving the page, since the upload would be lost.

**Not on Vercel.** A job needs a server that keeps running after a request has been answered: Vercel stops a function within minutes (at most 800 seconds) and keeps no files between requests, so a large upload or a scanned book would be cut off partway. When the `VERCEL` environment variable is set, starting a job or reading pages again answers 503 and says so. Run Deen on a normal server or your own computer with the same `.env` and upload from its admin page: it uses the same Redis database, Pinecone index and Blob store, so the files and books appear on the Vercel site too.

Parts are kept in `data/upload-parts/` until the job ends. Job progress is kept in the database, so any worker process can take parts or report on a job. A job is processed by the process that started it; if that process stops, the job is reported as failed after 10 minutes without progress. Finished and abandoned jobs, and their parts, are removed after a day.

Behind a reverse proxy, allow request bodies a little over 4 MB (for nginx, `client_max_body_size 5m;`). Mind the cost of very large files: embedding uses about one token per 3–4 characters of English, so a 200 MB file needs roughly 50–60 million tokens, far more than Pinecone's free Starter allowance of 5 million a month.

**Delete files.** The page lists the files uploaded from it to the current index, with their language, for books a link to read them, and for PDFs read partly, their [pages not read yet](#pdfs-read-partly). **Delete** removes a file's vectors from Pinecone, and its book. This list is kept in the same Redis database, so that database must keep its data across restarts (turn on persistence if your host has it off). Texts indexed some other way are counted in the totals, but can't be deleted from the page.

The admin endpoints live under `/admin/api/` and need an `Authorization: Bearer <ADMIN_TOKEN>` header. Besides the page's job endpoints (`POST /jobs`, `PUT /jobs/{id}/data?offset=…`, `POST /jobs/{id}/finish`, `GET /jobs/{id}`), `POST /files` (a form with `namespace` and `file`) and `POST /files/from-url` (JSON with `namespace` and `url`) upload a file of up to 20 MB in a single request, for scripts. `POST /files/{id}/ocr?namespace=…` reads a PDF's [pages not read yet](#pdfs-read-partly) again, as a job. All of them take an optional `language` (a code from `LANGUAGES`, such as `bn`); the admin page always sends one. They're left out of `/docs`. Keys are never sent back to the browser; the page shows only their first and last four characters.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ADMIN_TOKEN` | yes, to manage credentials | unset (admin page off) | Token for the [admin page](#admin-page). At least 24 characters, or the admin page stays off; use a long random value |
| `REDIS_URL` | yes | unset | Redis database holding the credentials, the list of uploaded files and upload progress, e.g. `redis://default:password@host:6379` |
| `MIN_RELEVANCE_SCORE` | no | unset (keep all) | Drop matches scoring below this value (cosine/dotproduct indexes only) |
| `LOG_LEVEL` | no | `INFO` | Python log level |
| `BLOB_READ_WRITE_TOKEN` | no | unset (books on disk) | A Vercel Blob store's read-write token: uploaded PDFs are kept there instead of `data/books/`. `VERCEL_BLOB_READ_WRITE_TOKEN` also works. See [Storing books in Vercel Blob](#storing-books-in-vercel-blob) |
| `BLOB_ACCESS` | no | `private` | `private` or `public`: the Blob store's access mode, which must match it |
| `OCR_SPACE_API_KEY` | no | unset (no OCR) | An [OCR.space](https://ocr.space/ocrapi) API key, or several separated by commas, for reading scanned PDF pages. See [Scanned PDFs (OCR)](#scanned-pdfs-ocr) |

Credentials aren't read from the environment, except once on the first start (see [Moving from `.env`](#credentials)).

## Aligning the embedding model with your vectors

Queries only match well if they're embedded by **the same model that embedded the indexed passages**. A different model, even one with the same dimension, gives meaningless similarity scores.

1. **Use the ingestion model.** If the passages were embedded with Pinecone Inference using `multilingual-e5-large`, keep the default. It's multilingual, so English, Arabic and Bengali questions can all match the same passages. If another Pinecone-hosted dense model was used (for example `llama-text-embed-v2`), enter that name as the embedding model on the admin page.
2. **Check the dimension.** `GET /texts` reports the index `dimension`. `multilingual-e5-large` produces 1024-dimensional vectors. If the query embedding's dimension doesn't match the index, `/query` returns HTTP 500 with a message naming both dimensions.
3. **Query vs. passage.** Queries are embedded with `input_type="query"`. Asymmetric models such as e5 expect the passages to have been embedded with `input_type="passage"`, which is what Pinecone's ingestion examples do.
4. **Vectors from outside Pinecone.** If the passages were embedded with OpenAI, sentence-transformers or another provider, Pinecone Inference can't reproduce them. Replace the body of `embed_query()` in [main.py](main.py) with a call to that same model.
5. **Dense models only.** Sparse models (such as `pinecone-sparse-english-v0`) are rejected with a clear error.

### Calibrating `MIN_RELEVANCE_SCORE`

Every source in a `/query` response includes its `score` (the chat page doesn't show it to readers). Run a few questions that clearly match a passage and a few that don't, then set the threshold between the two groups. With e5 models, cosine scores bunch together (unrelated text often still scores around 0.7), so leave the threshold unset until you have looked at real scores. When no passage passes the threshold, the API replies that it found nothing relevant and does not call the LLM. That reply is in Bengali or Arabic when the question is, and English otherwise.

## Answer language

The answer is written in the language of the question. For questions in Bengali or Arabic script, the prompt names the language explicitly ("Answer the question in Bengali"), because English excerpts otherwise pull the model towards English. Arabic-script questions containing Urdu or Persian letters aren't labelled Arabic; for those, and for every other language, the prompt asks for "the same language as the question". When a passage is in another language from the answer, the model gives its meaning in the answer's language and keeps the citation.

## API

### `GET /health`

Liveness check. Makes no external calls.

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### `GET /texts`

Lists the namespaces (one per text) and their vector counts.

```bash
curl http://localhost:8000/texts
```

```json
{
  "index": "deen",
  "dimension": 1024,
  "total_vector_count": 21362,
  "texts": [
    {"namespace": "quran", "vector_count": 6236, "name": "Quran"},
    {"namespace": "sahih_bukhari", "vector_count": 7563, "name": "Sahih Bukhari"},
    {"namespace": "sahih_muslim", "vector_count": 7563, "name": "Sahih Muslim"}
  ]
}
```

### `GET /read`

Lists the [readers](#duas-and-namaz-shikkha) and how many passages each has. The chat page shows a button for each one with passages.

```json
{"readers": [
  {"text": "duas", "name": "Duas", "total": 214, "item": null},
  {"text": "namaz", "name": "Namaz Shikkha", "total": 24, "item": null}
]}
```

### `GET /read/{text}`

One passage of a reader, where `{text}` is `duas` or `namaz`. Without `position`, returns only the count. `position` is 0-based and wraps around past the end.

```bash
curl "http://localhost:8000/read/duas?position=0"
```

```json
{
  "text": "duas",
  "name": "Duas",
  "total": 214,
  "item": {
    "position": 0,
    "section": "General",
    "title": "For good in both worlds",
    "arabic": "رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً ...",
    "transliteration": "Rabbana atina fid-dunya hasanatan ...",
    "text": "Our Lord, give us good in this world and good in the Hereafter, ...",
    "reference": "Quran (Surah 2, Ayah 201)",
    "details": {"source_file": "duas.json"}
  }
}
```

When the text has no passages, `total` is 0 and `item` is `null`. Any other `{text}` returns 404, and so does a position whose vector was deleted from Pinecone outside the app.

### `GET /books/list`

The PDFs kept as [books](#books-page), by title, and the language codes a book can have. Needs only the index name to be set, not Pinecone or Groq.

```json
{
  "languages": {"en": "English", "bn": "Bengali", "ar": "Arabic", "ur": "Urdu"},
  "books": [
    {"id": "bahishti-zewar-831188a7b310", "text": "fiqh", "title": "Bahishti Zewar", "filename": "Bahishti_Zewar.pdf",
     "language": "bn", "pages": 312, "size_bytes": 4823112, "uploaded_at": "2026-11-19T10:45:46+00:00",
     "pdf": "/books/fiqh/bahishti-zewar-831188a7b310.pdf", "url": "/books?text=fiqh&book=bahishti-zewar-831188a7b310",
     "text_name": "Fiqh"}
  ]
}
```

### `GET /books/{text}/{id}.pdf`

A book's PDF, shown in the browser (`Content-Disposition: inline`, with the original file name). It answers `Range` requests, which pdf.js uses to fetch only the parts of a large book it needs. An address that isn't a kept book returns 404.

### `POST /query`

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | string | required | 1–2000 characters, in any language |
| `namespace` | string or null | `null` | A namespace from `/texts`. `null`, omitted or `"all"` searches every text |
| `top_k` | int | `5` | 1–20 passages |
| `history` | list | `[]` | Earlier turns, oldest first: `{"role": "user" \| "assistant", "content": "..."}`. At most 8 messages, each up to 10,000 characters. See [Follow-up questions](#follow-up-questions) |

When searching **all** texts, each namespace is queried for `top_k` matches in parallel. The results are merged, sorted by similarity, and the best `top_k` overall are kept. Matches without `text`/`content` metadata are skipped. An unknown namespace returns HTTP 404 with the list of available namespaces.

Response:

```json
{
  "answer": "Charity is strongly encouraged. The Quran praises those who spend their wealth by night and by day (Quran, Surah 2, Ayah 274), and a hadith teaches that charity does not decrease wealth (Sahih Muslim 2588, graded Sahih) ...",
  "search_query": "What do the Quran and hadith say about charity?",
  "sources": [
    {
      "id": "quran-2-274",
      "namespace": "quran",
      "score": 0.8731,
      "reference": "Quran (Surah 2, Ayah 274)",
      "surah": 2,
      "ayah": 274,
      "excerpt": "Those who spend their wealth by night and by day, secretly and publicly ...",
      "metadata": {"translation": "Sahih International"}
    },
    {
      "id": "muslim-2588",
      "namespace": "sahih_muslim",
      "score": 0.8519,
      "reference": "Sahih Muslim 2588, graded Sahih",
      "collection": "Sahih Muslim",
      "hadith_number": 2588,
      "grade": "Sahih",
      "excerpt": "Charity does not decrease wealth ...",
      "metadata": {"narrator": "Abu Hurairah"}
    }
  ]
}
```

Each source lists the citation fields that were present (`title`, `book`, `chapter`, `verse`, `surah`, `ayah`, `collection`, `hadith_number`, `grade`) at the top level. Any other metadata goes under `metadata`. `search_query` is what was actually searched: the `query` itself, or its standalone rewrite when `history` was sent.

A source whose passage comes from a PDF kept as a book also has `book`: its id, text, title, language, the passage's `page`, the PDF's address (`pdf`) and the books page opened at that page (`url`):

```json
"book": {"id": "bahishti-zewar-831188a7b310", "text": "fiqh", "title": "Bahishti Zewar", "language": "bn", "page": 34,
         "pdf": "/books/fiqh/bahishti-zewar-831188a7b310.pdf", "url": "/books?text=fiqh&book=bahishti-zewar-831188a7b310&page=34"}
```

#### Follow-up questions

The API stores nothing between requests. To ask a follow-up, the client sends the earlier turns in `history`:

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Tell me more about what it says on patience.",
    "namespace": "quran",
    "history": [
      {"role": "user", "content": "What does the Quran say about hardship?"},
      {"role": "assistant", "content": "The Quran says believers will be tested (Quran, Surah 2, Ayah 155) ..."}
    ]
  }'
```

When `history` isn't empty, the graph makes two Groq calls:

1. **condense** rewrites the question into one that stands on its own, in the question's own language, such as *"What else does the Quran say about patience in hardship?"*. This rewrite is what gets embedded and searched, because "tell me more" alone would match nothing useful.
2. **generate** receives the earlier turns, the original question, the rewrite, and the newly retrieved excerpts. The system prompt says earlier turns only explain what the question refers to. Every claim must still be cited from the new excerpts.

Without `history`, condense is skipped and the request costs one Groq call, as before. Each history message is cut to 1,500 characters inside the prompts to stay within Groq token limits. Send only the most recent turns: the chat UI sends the last 8 messages, each cut to those 1,500 characters.

#### Search one text

```bash
# Quran only
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does the Quran say about patience in hardship?", "namespace": "quran", "top_k": 5}'

# One hadith collection, with more passages
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the virtue of fasting in Ramadan?", "namespace": "sahih_bukhari", "top_k": 8}'

# A question in Bengali gets an answer in Bengali
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "রোজার ফজিলত সম্পর্কে হাদিসে কী বলা হয়েছে?"}'
```

#### Search the Quran and Hadith together

```bash
# Search every namespace
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What do the Quran and hadith say about kindness to parents?", "namespace": "all", "top_k": 10}'

# Omitting namespace does the same thing
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Is it permissible to combine prayers while travelling?", "top_k": 12}'
```

Because the merged results are ranked purely by score, one text can take most of the slots. To make sure both the Quran and the Hadith appear, raise `top_k` (10–20) or run one query per namespace.

#### Windows PowerShell

In Windows PowerShell 5.1, `curl` is an alias for `Invoke-WebRequest`. Use `curl.exe` with the examples above, or:

```powershell
$body = @{ query = "What does the Quran say about patience?"; namespace = "quran"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/query -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

Sending the body as UTF-8 bytes keeps Arabic and Bengali questions intact in Windows PowerShell 5.1.

### Errors

| Status | When |
|---|---|
| 404 | `namespace` doesn't exist in the index (the response lists available namespaces), or a book's address isn't a kept book |
| 422 | Invalid request: blank `query`, `top_k` outside 1–20, more than 8 `history` messages, a `role` other than `user`/`assistant`, … |
| 500 | Misconfiguration: embedding dimension mismatch, or a sparse embedding model |
| 429 | More than 20 questions from one visitor (IP address) within a minute. The response says how many seconds to wait, also in a `Retry-After` header. Counts are kept per worker process |
| 502 | Pinecone or Groq request failed |
| 503 | Credentials haven't been entered on the admin page yet (the message names what's missing). The books endpoints need only the index name. Also when a worker process is already answering 20 questions: the rest are turned away, with a `Retry-After` header, so the pages and books keep loading while Groq is slow |

## Project layout

```
main.py            FastAPI app, the question pipeline (condense, retrieve, generate), prompts, Pinecone and Groq clients, books, admin API
ingest.py          Splits uploaded files (.txt, .md, .pdf, .json, .jsonl, .csv) into passages for the admin API, with OCR for scanned PDF pages
static/index.html  Chatbot web page, served at /
static/books.html  Books page (library and page-by-page reader), served at /books
static/i18n.js     The chat and books pages' text in English, Bengali and Arabic, and the language menu
static/prayer-times.js  Azan time calculator and city list for the chat page (runs in the browser)
static/zakat.js    Zakat calculator's arithmetic and Hanafi nisab rules for the chat page (runs in the browser)
static/admin.html  Admin page, served at /admin
static/base.css    Fonts, colours and the parts the three pages share
static/vendor/pdfjs/  pdf.js, which draws a book's pages on the books page (Apache License 2.0)
db.py              Redis storage for the credentials, the list of uploaded files and upload progress
storage.py         Vercel Blob storage for the PDFs kept as books: upload, delete, and range reads through the app
static/fonts/      Self-hosted Source Serif 4, Noto Naskh Arabic and Noto Serif Bengali (woff2) with their licences, served under /static
data/              Not in git: upload parts while they're processed, and the PDFs kept as books (data/books/)
PRODUCT.md         Product decisions: users, positioning, Hanafi stance, languages
requirements.txt   Dependencies
requirements-dev.txt  Test dependencies (pytest, fakeredis, quickjs)
tests/             Tests, with Pinecone and Groq faked: run `pytest`
.env.example       Environment variable template
```
