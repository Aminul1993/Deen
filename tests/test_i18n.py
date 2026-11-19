"""The chat and books pages' translations (static/i18n.js): complete in every language, and every key used exists."""

import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
PAGES = ["index.html", "books.html"]

# Plural forms each language's numbers can need (CLDR rules, as Intl.PluralRules picks them).
PLURAL_FORMS = {"en": {"one", "other"}, "bn": {"other"}, "ar": {"one", "two", "few", "many", "other"}}


def strings():
    source = (STATIC / "i18n.js").read_text(encoding="utf-8")
    body = source.split("const STRINGS = ", 1)[1].split("}; // end STRINGS", 1)[0] + "}"
    return json.loads(body)


def placeholders(entry):
    texts = entry.values() if isinstance(entry, dict) else [entry]
    return {name for text in texts for name in re.findall(r"\{(\w+)\}", text)}


def test_every_language_has_every_string():
    table = strings()
    assert set(table) == set(PLURAL_FORMS)
    keys = set(table["en"])
    for lang, entries in table.items():
        assert set(entries) == keys, f"{lang}: missing {keys - set(entries)}, extra {set(entries) - keys}"
        for key, entry in entries.items():
            if isinstance(entry, dict):
                assert set(entry) <= PLURAL_FORMS[lang] and "other" in entry, (lang, key)
                assert isinstance(table["en"][key], dict), (lang, key)
            # A translation may drop {count} where the words say it ("مصدر واحد"), but not invent placeholders.
            assert placeholders(entry) <= placeholders(table["en"][key]) | {"count"}, (lang, key)


@pytest.mark.parametrize("page", PAGES)
def test_every_key_a_page_uses_exists(page):
    keys = set(strings()["en"])
    html = (STATIC / page).read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html))
    used |= set(re.findall(r'\bt\("([\w.]+)"\s*[,)]', html))
    used |= set(re.findall(r'i18nTitle = "([\w.]+)"', html))
    assert used, page
    assert used <= keys, f"{page} uses keys that don't exist: {used - keys}"
