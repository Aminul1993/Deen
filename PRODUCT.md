# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Members of the public who want to learn what the Quran and Hadith say about a question. They use Deen as a public website on desktop or phone, ask in plain language, and expect an answer they can check against the cited sources.

People ask in English, Arabic or Bengali.

## Product Purpose

Deen answers questions about Islam from the Quran and Hadith. Every answer is grounded in passages retrieved from an existing index and cites them. Success means a learner gets a clear answer in their own language and can verify each point against the cited passage.

## Positioning

- **Islam-centred.** Answers speak from an Islamic perspective, not as a neutral survey of religions.
- **Declared school.** Rulings and interpretation follow the **Hanafi** madhhab.
- **Checkable evidence.** Every claim cites its source: Surah and Ayah for the Quran, and collection, hadith number and authenticity grade for Hadith.

## Operating Context

- Public website. A FastAPI app serves the chat page at `/`, and the page calls `POST /query` and `GET /texts`.
- Reads an existing Pinecone index with one namespace per text. The public site never edits the index. An admin page at `/admin`, protected by `ADMIN_TOKEN`, can upload files into it, delete them again, and swap the Groq and Pinecone credentials, which are kept in a SQLite database rather than in `.env`.
- Embeds queries with Pinecone Inference (`multilingual-e5-large` by default), so questions in Arabic and Bengali can be matched as well as English ones.
- Generates answers with a Groq-hosted LLM (`openai/gpt-oss-120b` by default; `llama-3.3-70b-versatile` was retired by Groq in 2026).
- The API keeps no state between requests. The chat page sends the last 4 exchanges with each question so follow-up questions work. Reloading the page or pressing **New chat** clears them.

## Capabilities and Constraints

**Confirmed**
- Texts in the index, now and planned: **Quran** and **Hadith**. No other scriptures are indexed or planned.
- Hadith metadata includes the authenticity grade (sahih, hasan, da'if), the collection and the hadith number.
- Answers may give religious rulings (for example, whether something is permitted), based on the cited Quran and Hadith passages and following the Hanafi madhhab.
- Answers come back in the language of the question: English, Arabic or Bengali.
- The chat page lets people choose a text or all texts, and how many passages to retrieve (3–20). It shows each answer's sources with their citation, an excerpt and a relevance score.
- The chat page's **Duas** and **Namaz Shikkha** readers show what an admin uploaded to the `duas` and `namaz` texts one passage at a time, with Arabic, transliteration, meaning or instruction, and source, and let people step through it. No dua or prayer guidance is built in: it all comes from uploaded, citable sources.
- The chat page shows azan times for a location the person chooses (a listed city, or the browser's location), calculated in the browser so the location isn't sent anywhere. Asr defaults to the Hanafi time; the standard time is an option.

**How the implementation carries these decisions out** (`main.py`, `static/index.html`)
- `SYSTEM_PROMPT` answers from an Islamic perspective following the Hanafi madhhab, may state rulings the excerpts support, and must cite every claim. It must not quote verses, hadith or scholars' opinions that aren't in the excerpts.
- Hadith citations read "Sahih al-Bukhari 52 (Book of Faith), graded Sahih". The accepted metadata keys are listed in `CITATION_FIELDS` and the README. The exact keys in the real index haven't been checked against it.
- The answer language follows the question. Bengali and Arabic script are detected and named in the prompt, and the no-results reply is localized.
- The chat page displays Arabic right to left and self-hosts Arabic and Bengali fonts.

**Open decisions**
- Which Quran translation(s) and which Hadith collections are indexed.
- Whether every ruling should carry a note. Today the model suggests asking a qualified Hanafi scholar only when the excerpts don't settle a ruling, or when the answer depends on the person's circumstances.
- How the Islam-centred, comparative positioning applies now that only Quran and Hadith are indexed. For example, whether "comparative" means relating Quran and Hadith passages to each other.

## Brand Commitments

- Name: **Deen**.
- Licence: MIT (see `LICENSE`).
- No logo or other brand assets exist. The favicon in `static/index.html` is a placeholder.

## Evidence on Hand

- An existing Pinecone index with Quran and Hadith namespaces. Its name and keys live in `.env`, not in the repository.
- Hadith records carry grade, collection and number metadata.
- There are no users, testimonials, usage figures, scholarly endorsements or reviews. Future work must not invent any, and must not claim that a scholar or institution has reviewed or approved the answers.

## Product Principles

1. **No citation, no claim.** Every statement traces to a retrieved passage: Surah and Ayah for the Quran; collection, number and grade for Hadith.
2. **Say where you stand.** Rulings follow the Hanafi madhhab, and the product presents itself that way rather than as the only possible view.
3. **The grade is part of the evidence.** A hadith's authenticity grade travels with it wherever it's cited, so learners can weigh it.
4. **Answer in the asker's language.** English, Arabic and Bengali are all first-class. None of them is a fallback.
5. **Written for learners.** Explanations suit a public audience without assuming religious training.

## Accessibility & Inclusion

- Arabic text, in questions, answers and Quran passages, must display right-to-left and stay legible.
- Bengali must render with a font that covers Bengali script. The page self-hosts Noto Naskh Arabic and Noto Serif Bengali for this.
- No formal accessibility standard has been confirmed as a requirement.
