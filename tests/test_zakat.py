"""The zakat calculator's arithmetic (static/zakat.js), run in QuickJS: the Hanafi nisab rules and typed amounts."""

import json
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")  # requirements-dev.txt

SCRIPT = (Path(__file__).resolve().parent.parent / "static" / "zakat.js").read_text(encoding="utf-8")
GOLD, SILVER = 10_000.0, 100.0  # prices per gram
SILVER_NISAB = 612.36 * SILVER  # 61,236
GOLD_NISAB = 87.48 * GOLD  # 874,800


@pytest.fixture(scope="module")
def js():
    context = quickjs.Context()
    context.eval(SCRIPT)
    return context


def calculate(js, **values):
    return json.loads(js.eval(f"JSON.stringify(Zakat.calculate({json.dumps(values)}))"))


def test_money_alone_is_measured_against_the_silver_nisab(js):
    r = calculate(js, silverPrice=SILVER, cash=100_000)
    assert (r["basis"], r["metal"], r["nisabValue"], r["reached"]) == ("silver", "silver", pytest.approx(SILVER_NISAB), True)
    assert r["due"] == pytest.approx(2_500)
    assert calculate(js, silverPrice=SILVER, cash=60_000)["due"] == 0


def test_gold_alone_is_measured_by_its_own_nisab(js):
    """Hanafi: 80 g of gold alone owes nothing, though it's worth far more than the silver nisab."""
    r = calculate(js, goldPrice=GOLD, gold=80)
    assert (r["basis"], r["reached"], r["due"]) == ("gold-only", False, 0)
    r = calculate(js, goldPrice=GOLD, gold=90)
    assert r["nisabValue"] == pytest.approx(GOLD_NISAB) and r["due"] == pytest.approx(90 * GOLD * 0.025)
    assert calculate(js, silverPrice=SILVER, silver=600)["reached"] is False  # silver alone: 612.36 g
    assert calculate(js, silverPrice=SILVER, silver=700)["basis"] == "silver-only"


def test_mixed_wealth_is_added_up_and_measured_against_silver(js):
    r = calculate(js, goldPrice=GOLD, silverPrice=SILVER, gold=80, cash=1)  # the same gold, with any money
    assert r["basis"] == "silver" and r["reached"] is True and r["due"] == pytest.approx((800_000 + 1) * 0.025)
    r = calculate(js, goldPrice=GOLD, silverPrice=SILVER, gold=3, silver=200, receivables=5_000, stock=2_000,
                  investments=1_000)
    assert r["assets"] == pytest.approx(30_000 + 20_000 + 8_000) and r["due"] == 0  # 58,000 < 61,236


def test_debts_due_are_taken_off_first(js):
    r = calculate(js, silverPrice=SILVER, cash=100_000, debts=50_000)
    assert (r["net"], r["reached"], r["due"]) == (50_000, False, 0)
    r = calculate(js, silverPrice=SILVER, cash=100_000, debts=20_000)
    assert r["due"] == pytest.approx(2_000)
    assert calculate(js, silverPrice=SILVER, cash=10, debts=50)["net"] == 0  # never below zero
    assert calculate(js, goldPrice=GOLD, gold=90, debts=50_000)["reached"] is False  # 900,000 − 50,000 < 874,800


def test_the_gold_nisab_can_be_chosen_for_all_wealth(js):
    r = calculate(js, goldPrice=GOLD, silverPrice=SILVER, cash=100_000, standard="gold")
    assert (r["basis"], r["nisabValue"], r["due"]) == ("gold", pytest.approx(GOLD_NISAB), 0)
    assert calculate(js, goldPrice=GOLD, cash=1_000_000, standard="gold")["due"] == pytest.approx(25_000)


def test_prices_the_answer_needs(js):
    r = calculate(js, cash=100_000)
    assert r["missing"] == ["silverPrice"] and r["due"] is None and r["assets"] == 100_000
    assert calculate(js, silverPrice=SILVER, gold=10, cash=5)["missing"] == ["goldPrice"]
    assert calculate(js, cash=5, standard="gold")["missing"] == ["goldPrice"]
    assert calculate(js, goldPrice=GOLD, gold=100)["missing"] == []  # gold alone needs no silver price
    empty = calculate(js, goldPrice=GOLD, silverPrice=SILVER)
    assert empty["empty"] is True and empty["due"] == 0


@pytest.mark.parametrize("text, expected", [
    ("", None), ("  ", None), ("1250", 1250), ("1,250.5", 1250.5), ("1,25,000", 125000), ("12,5", 12.5),
    ("1.234,56", 1234.56), ("১,২৫,০০০", 125000), ("২৫০.৫", 250.5), ("٢٥٠٫٥", 250.5), ("۱۲۰۰", 1200),
    ("1 000", 1000), ("5.", 5), (".5", 0.5),
])
def test_typed_amounts(js, text, expected):
    assert js.eval(f"Zakat.parseAmount({json.dumps(text)})") == expected


@pytest.mark.parametrize("text", ["abc", "-5", "1e5", "5..2", "12a"])
def test_amounts_that_are_not_numbers(js, text):
    assert js.eval(f"isNaN(Zakat.parseAmount({json.dumps(text)}))") is True


def test_units_and_rate(js):
    assert js.eval("Zakat.UNITS.tola") == 11.664 and js.eval("Zakat.RATE") == 0.025
    assert js.eval("Zakat.NISAB_GRAMS.gold / Zakat.UNITS.tola") == pytest.approx(7.5)
    assert js.eval("Zakat.NISAB_GRAMS.silver / Zakat.UNITS.tola") == pytest.approx(52.5)
