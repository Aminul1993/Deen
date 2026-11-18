/* Azan (prayer) times for the chat page, calculated in the browser: the location never leaves it.
 *
 * The sun's position comes from the U.S. Naval Observatory's low-precision formulas
 * (https://aa.usno.navy.mil/faq/sun_approx), accurate to about a minute, which is what most prayer
 * time calculators use. Fajr and Isha are the times the sun is a method's number of degrees below
 * the horizon; Asr is when an object's shadow is its noon shadow plus once (standard) or twice
 * (Hanafi) its length. Where twilight never gets dark enough (high latitudes in summer), Fajr and
 * Isha are capped at the method's share of the night ("angle-based" rule).
 */
(function (root) {
  "use strict";

  // Twilight angles in degrees below the horizon, or Isha a fixed number of minutes after Maghrib.
  const METHODS = {
    karachi: { name: "University of Islamic Sciences, Karachi", fajr: 18, isha: 18 },
    mwl: { name: "Muslim World League", fajr: 18, isha: 17 },
    isna: { name: "Islamic Society of North America", fajr: 15, isha: 15 },
    egypt: { name: "Egyptian General Authority of Survey", fajr: 19.5, isha: 17.5 },
    makkah: { name: "Umm al-Qura, Makkah", fajr: 18.5, ishaMinutes: 90 },
    gulf: { name: "Gulf region", fajr: 19.5, ishaMinutes: 90 },
    kuwait: { name: "Kuwait", fajr: 18, isha: 17.5 },
    qatar: { name: "Qatar", fajr: 18, ishaMinutes: 90 },
    singapore: { name: "Singapore, Malaysia and Indonesia", fajr: 20, isha: 18 },
  };
  const ASR_FACTORS = { hanafi: 2, standard: 1 }; // shadow length added to the noon shadow
  const PRAYERS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]; // sunrise is shown, but has no azan

  // Cities to pick from, with the calculation method usually used there.
  const CITIES = [
    ["Bangladesh", "Asia/Dhaka", "karachi", [
      ["Dhaka", 23.8103, 90.4125], ["Chattogram", 22.3569, 91.7832], ["Khulna", 22.8456, 89.5403],
      ["Rajshahi", 24.3745, 88.6042], ["Sylhet", 24.8949, 91.8687], ["Barishal", 22.701, 90.3535],
      ["Rangpur", 25.7439, 89.2752], ["Mymensingh", 24.7471, 90.4203], ["Cumilla", 23.4607, 91.1809],
      ["Gazipur", 23.9999, 90.4203], ["Narayanganj", 23.6238, 90.5], ["Bogura", 24.8465, 89.3773],
      ["Jashore", 23.1664, 89.2081], ["Cox's Bazar", 21.4272, 92.0058],
    ]],
    ["India", "Asia/Kolkata", "karachi", [
      ["Kolkata", 22.5726, 88.3639], ["Delhi", 28.6139, 77.209], ["Mumbai", 19.076, 72.8777],
      ["Hyderabad", 17.385, 78.4867], ["Bengaluru", 12.9716, 77.5946], ["Chennai", 13.0827, 80.2707],
      ["Lucknow", 26.8467, 80.9462],
    ]],
    ["Pakistan", "Asia/Karachi", "karachi", [
      ["Karachi", 24.8607, 67.0011], ["Lahore", 31.5204, 74.3587], ["Islamabad", 33.6844, 73.0479],
    ]],
    ["Nepal", "Asia/Kathmandu", "karachi", [["Kathmandu", 27.7172, 85.324]]],
    ["Sri Lanka", "Asia/Colombo", "karachi", [["Colombo", 6.9271, 79.8612]]],
    ["Saudi Arabia", "Asia/Riyadh", "makkah", [
      ["Makkah", 21.3891, 39.8579], ["Madinah", 24.5247, 39.5692], ["Riyadh", 24.7136, 46.6753],
      ["Jeddah", 21.4858, 39.1925],
    ]],
    ["United Arab Emirates", "Asia/Dubai", "gulf", [["Dubai", 25.2048, 55.2708], ["Abu Dhabi", 24.4539, 54.3773]]],
    ["Qatar", "Asia/Qatar", "qatar", [["Doha", 25.2854, 51.531]]],
    ["Kuwait", "Asia/Kuwait", "kuwait", [["Kuwait City", 29.3759, 47.9774]]],
    ["Oman", "Asia/Muscat", "gulf", [["Muscat", 23.588, 58.3829]]],
    ["Bahrain", "Asia/Bahrain", "gulf", [["Manama", 26.2285, 50.586]]],
    ["Egypt", "Africa/Cairo", "egypt", [["Cairo", 30.0444, 31.2357]]],
    ["Türkiye", "Europe/Istanbul", "mwl", [["Istanbul", 41.0082, 28.9784]]],
    ["Malaysia", "Asia/Kuala_Lumpur", "singapore", [["Kuala Lumpur", 3.139, 101.6869]]],
    ["Singapore", "Asia/Singapore", "singapore", [["Singapore", 1.3521, 103.8198]]],
    ["Indonesia", "Asia/Jakarta", "singapore", [["Jakarta", -6.2088, 106.8456]]],
    ["United Kingdom", "Europe/London", "mwl", [
      ["London", 51.5074, -0.1278], ["Birmingham", 52.4862, -1.8904], ["Manchester", 53.4808, -2.2426],
    ]],
    ["France", "Europe/Paris", "mwl", [["Paris", 48.8566, 2.3522]]],
    ["Germany", "Europe/Berlin", "mwl", [["Berlin", 52.52, 13.405]]],
    ["Italy", "Europe/Rome", "mwl", [["Rome", 41.9028, 12.4964]]],
    ["United States", null, "isna", [
      ["New York", 40.7128, -74.006, "America/New_York"], ["Chicago", 41.8781, -87.6298, "America/Chicago"],
      ["Houston", 29.7604, -95.3698, "America/Chicago"], ["Los Angeles", 34.0522, -118.2437, "America/Los_Angeles"],
    ]],
    ["Canada", "America/Toronto", "isna", [["Toronto", 43.6532, -79.3832]]],
    ["Australia", null, "mwl", [
      ["Sydney", -33.8688, 151.2093, "Australia/Sydney"], ["Melbourne", -37.8136, 144.9631, "Australia/Melbourne"],
    ]],
    ["Japan", "Asia/Tokyo", "mwl", [["Tokyo", 35.6762, 139.6503]]],
    ["Nigeria", "Africa/Lagos", "mwl", [["Lagos", 6.5244, 3.3792]]],
    ["Kenya", "Africa/Nairobi", "mwl", [["Nairobi", -1.2921, 36.8219]]],
    ["South Africa", "Africa/Johannesburg", "mwl", [["Johannesburg", -26.2041, 28.0473]]],
  ].flatMap(([country, zone, method, cities]) => cities.map(([name, lat, lng, cityZone]) => ({
    id: (country + "-" + name).toLowerCase().replace(/[^a-z0-9]+/g, "-"),
    name, country, lat, lng, timeZone: cityZone || zone, method,
  })));

  // ---------- astronomy (degrees in, degrees out) ----------

  const rad = (d) => d * Math.PI / 180;
  const deg = (r) => r * 180 / Math.PI;
  const sin = (d) => Math.sin(rad(d));
  const cos = (d) => Math.cos(rad(d));
  const tan = (d) => Math.tan(rad(d));
  const arcsin = (x) => deg(Math.asin(x));
  const arccos = (x) => deg(Math.acos(x)); // NaN outside [-1, 1]: the sun never reaches that angle
  const arccot = (x) => deg(Math.atan(1 / x));
  const arctan2 = (y, x) => deg(Math.atan2(y, x));
  const wrap = (a, b) => ((a % b) + b) % b;

  function julianDay(year, month, day) {
    if (month <= 2) { year -= 1; month += 12; }
    const a = Math.floor(year / 100);
    const b = 2 - a + Math.floor(a / 4);
    return Math.floor(365.25 * (year + 4716)) + Math.floor(30.6001 * (month + 1)) + day + b - 1524.5;
  }

  function sunPosition(jd) {
    const d = jd - 2451545.0;
    const g = wrap(357.529 + 0.98560028 * d, 360); // mean anomaly
    const q = wrap(280.459 + 0.98564736 * d, 360); // mean longitude
    const l = wrap(q + 1.915 * sin(g) + 0.020 * sin(2 * g), 360); // ecliptic longitude
    const e = 23.439 - 0.00000036 * d; // obliquity of the ecliptic
    const ra = wrap(arctan2(cos(e) * sin(l), cos(l)) / 15, 24);
    return { declination: arcsin(sin(e) * sin(l)), equation: q / 15 - ra };
  }

  /** Times as hours after local midnight (NaN where the sun never reaches the angle). */
  function hoursFor(year, month, day, lat, lng, utcOffset, settings) {
    const method = METHODS[settings.method] || METHODS.karachi;
    const factor = ASR_FACTORS[settings.asr] || ASR_FACTORS.hanafi;
    const jd = julianDay(year, month, day) - lng / (15 * 24);

    const noon = (t) => wrap(12 - sunPosition(jd + t).equation, 24);
    // When the sun is `angle` degrees below the horizon (negative: above), before or after noon.
    const sunAngleTime = (angle, t, beforeNoon) => {
      const decl = sunPosition(jd + t).declination;
      const h = arccos((-sin(angle) - sin(decl) * sin(lat)) / (cos(decl) * cos(lat))) / 15;
      return noon(t) + (beforeNoon ? -h : h);
    };
    const asr = (t) => {
      const decl = sunPosition(jd + t).declination;
      return sunAngleTime(-arccot(factor + tan(Math.abs(lat - decl))), t);
    };

    // Evaluate the sun's position near each event's usual time (as a fraction of the day).
    const t = {
      fajr: sunAngleTime(method.fajr, 5 / 24, true),
      sunrise: sunAngleTime(0.833, 6 / 24, true), // refraction and the sun's radius
      dhuhr: noon(12 / 24),
      asr: asr(13 / 24),
      maghrib: sunAngleTime(0.833, 18 / 24),
      isha: method.isha ? sunAngleTime(method.isha, 18 / 24) : NaN,
    };
    if (method.ishaMinutes) t.isha = t.maghrib + method.ishaMinutes / 60;

    const night = wrap(t.sunrise - t.maghrib, 24);
    if (!isNaN(night)) {
      const fajrCap = method.fajr / 60 * night;
      if (isNaN(t.fajr) || wrap(t.sunrise - t.fajr, 24) > fajrCap) t.fajr = t.sunrise - fajrCap;
      if (method.isha) {
        const ishaCap = method.isha / 60 * night;
        if (isNaN(t.isha) || wrap(t.isha - t.maghrib, 24) > ishaCap) t.isha = t.maghrib + ishaCap;
      }
    }

    const shift = utcOffset - lng / 15; // local solar time -> the place's clock time
    for (const name of Object.keys(t)) t[name] += shift;
    return t;
  }

  // ---------- time zones ----------

  /** The calendar date at `instant` in `timeZone`: {year, month, day}. */
  function localDate(instant, timeZone) {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone, year: "numeric", month: "numeric", day: "numeric" })
      .formatToParts(instant);
    const get = (type) => Number(parts.find((p) => p.type === type).value);
    return { year: get("year"), month: get("month"), day: get("day") };
  }

  /** Hours `timeZone` is ahead of UTC at `instant`, e.g. 6 for Dhaka. */
  function utcOffset(instant, timeZone) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
      hour: "numeric", minute: "numeric", second: "numeric",
    }).formatToParts(instant);
    const get = (type) => Number(parts.find((p) => p.type === type).value);
    const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
    return (asUtc - Math.floor(instant.getTime() / 1000) * 1000) / 3600000;
  }

  // ---------- public API ----------

  /**
   * The day's times at `place` ({lat, lng, timeZone}) for the date it is there at `instant`.
   * Returns {date: {year, month, day}, times: {fajr, sunrise, dhuhr, asr, maghrib, isha}},
   * each a Date rounded to the minute, or null where it doesn't occur.
   */
  function forDay(instant, place, settings) {
    const date = localDate(instant, place.timeZone);
    const midday = new Date(Date.UTC(date.year, date.month - 1, date.day, 12));
    const offset = utcOffset(new Date(midday.getTime() - utcOffset(midday, place.timeZone) * 3600000), place.timeZone);
    const hours = hoursFor(date.year, date.month, date.day, place.lat, place.lng, offset, settings);
    const startUtc = Date.UTC(date.year, date.month - 1, date.day);
    const times = {};
    for (const [name, h] of Object.entries(hours)) {
      times[name] = isFinite(h) ? new Date(Math.round((startUtc + (h - offset) * 3600000) / 60000) * 60000) : null;
    }
    return { date, times };
  }

  /** The next azan after `instant`: {name, time}, looking into tomorrow after Isha. */
  function next(instant, place, settings) {
    for (let days = 0; days < 3; days++) {
      const { times } = forDay(new Date(instant.getTime() + days * 86400000), place, settings);
      const name = PRAYERS.find((p) => times[p] && times[p] > instant);
      if (name) return { name, time: times[name] };
    }
    return null;
  }

  const api = { METHODS, ASR_FACTORS, PRAYERS, CITIES, forDay, next, hoursFor, utcOffset };
  root.PrayerTimes = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
