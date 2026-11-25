"""Azan times (static/prayer-times.js), run in QuickJS: a published timetable, Hanafi Asr and the high-latitude rule.

QuickJS has no Intl, so these call PrayerTimes.hoursFor with a fixed UTC offset; forDay only adds the
time zone around it.
"""

import json
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")  # requirements-dev.txt

SCRIPT = (Path(__file__).resolve().parent.parent / "static" / "prayer-times.js").read_text(encoding="utf-8")
DHAKA = (23.8103, 90.4125, 6)  # latitude, longitude, UTC offset
LONDON_SUMMER = (51.5074, -0.1278, 1)


@pytest.fixture(scope="module")
def js():
    context = quickjs.Context()
    context.eval(SCRIPT)
    return context


def times(js, date, place, method, asr="hanafi"):
    """Clock times "HH:MM" (rounded to the minute), or None where the sun never reaches the angle."""
    args = ", ".join(map(str, (*date, *place)))
    hours = json.loads(js.eval(f"JSON.stringify(PrayerTimes.hoursFor({args}, {json.dumps({'method': method, 'asr': asr})}))"))
    return {name: None if h is None else f"{round(h * 60) // 60:02d}:{round(h * 60) % 60:02d}" for name, h in hours.items()}


def minutes(clock):
    hours, mins = map(int, clock.split(":"))
    return hours * 60 + mins


def test_dhaka_matches_a_published_timetable(js):
    # UrduPoint's Dhaka timetable for 24 September 2026, Karachi method, Hanafi Asr.
    published = {"fajr": "04:32", "sunrise": "05:48", "dhuhr": "11:50", "asr": "16:12", "maghrib": "17:53", "isha": "19:08"}
    got = times(js, (2026, 9, 24), DHAKA, "karachi")
    for name, clock in published.items():
        assert abs(minutes(got[name]) - minutes(clock)) <= 1, (name, got[name], clock)


def test_hanafi_asr_is_later_than_the_standard_one(js):
    hanafi = times(js, (2026, 11, 25), DHAKA, "karachi", "hanafi")
    standard = times(js, (2026, 11, 25), DHAKA, "karachi", "standard")
    assert minutes(hanafi["asr"]) - minutes(standard["asr"]) > 30
    assert {k: v for k, v in hanafi.items() if k != "asr"} == {k: v for k, v in standard.items() if k != "asr"}


def test_fajr_and_isha_are_capped_where_twilight_never_ends(js):
    # In London around midsummer the sun never gets 18° below the horizon: the method's share of the night is used.
    t = times(js, (2026, 6, 21), LONDON_SUMMER, "mwl", "standard")
    assert all(t.values()), t
    night = (minutes(t["sunrise"]) + 24 * 60) - minutes(t["maghrib"])
    assert abs((minutes(t["sunrise"]) - minutes(t["fajr"])) - 18 / 60 * night) <= 1
    assert abs((minutes(t["isha"]) - minutes(t["maghrib"])) - 17 / 60 * night) <= 1
