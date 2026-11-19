/* Zakat for the chat page, worked out in the browser (the figures never leave it), following the
 * Hanafi school, like the rest of Deen:
 *
 * - Zakat is a fortieth (2.5%) of zakatable wealth at or above the nisab, once it has been held
 *   for a full lunar year.
 * - The nisab is 20 mithqal of gold, 87.48 g (7.5 tola), or 200 dirhams of silver, 612.36 g (52.5 tola).
 * - Gold on its own is measured against the nisab of gold, and silver on its own against that of
 *   silver. Wealth of more than one kind (gold with silver, either with money, money alone) is added
 *   up by value and measured against the nisab of silver, which is better for the poor. The page
 *   also offers the gold nisab for all wealth, for those whose scholar advises it.
 * - Gold and silver jewellery counts, worn or not. Debts due now (and this year's instalments of
 *   long-term loans) are taken off first.
 *
 * Only arithmetic is here, no page code, so tests/test_zakat.py can run it too.
 */
(function (root) {
  "use strict";

  const RATE = 0.025; // a fortieth
  const NISAB_GRAMS = { gold: 87.48, silver: 612.36 };
  // Units for weighing gold and silver: grams in one unit. A tola (bhori in Bangladesh) is 11.664 g.
  const UNITS = { gram: 1, tola: 11.664, ounce: 31.1034768 };
  const MONEY = ["cash", "receivables", "stock", "investments"]; // amounts in the chosen currency

  // Currencies to choose from, and the usual one for each azan-times country and browser region.
  const CURRENCIES = ["BDT", "INR", "PKR", "NPR", "LKR", "SAR", "AED", "QAR", "KWD", "OMR", "BHD", "EGP", "TRY",
    "MYR", "SGD", "IDR", "GBP", "EUR", "USD", "CAD", "AUD", "JPY", "NGN", "KES", "ZAR"];
  const COUNTRY_CURRENCIES = {
    "Bangladesh": "BDT", "India": "INR", "Pakistan": "PKR", "Nepal": "NPR", "Sri Lanka": "LKR",
    "Saudi Arabia": "SAR", "United Arab Emirates": "AED", "Qatar": "QAR", "Kuwait": "KWD", "Oman": "OMR",
    "Bahrain": "BHD", "Egypt": "EGP", "Türkiye": "TRY", "Malaysia": "MYR", "Singapore": "SGD",
    "Indonesia": "IDR", "United Kingdom": "GBP", "France": "EUR", "Germany": "EUR", "Italy": "EUR",
    "Canada": "CAD", "United States": "USD", "Australia": "AUD", "Japan": "JPY", "Nigeria": "NGN",
    "Kenya": "KES", "South Africa": "ZAR",
  };
  const REGION_CURRENCIES = {
    BD: "BDT", IN: "INR", PK: "PKR", NP: "NPR", LK: "LKR", SA: "SAR", AE: "AED", QA: "QAR", KW: "KWD",
    OM: "OMR", BH: "BHD", EG: "EGP", TR: "TRY", MY: "MYR", SG: "SGD", ID: "IDR", GB: "GBP", US: "USD",
    CA: "CAD", AU: "AUD", JP: "JPY", NG: "NGN", KE: "KES", ZA: "ZAR", FR: "EUR", DE: "EUR", IT: "EUR",
    ES: "EUR", NL: "EUR", BE: "EUR", IE: "EUR", AT: "EUR", PT: "EUR", FI: "EUR", GR: "EUR",
  };

  // Bengali and Arabic-Indic digits, as people may type them.
  const DIGITS = { "০": 0, "১": 1, "২": 2, "৩": 3, "৪": 4, "৫": 5, "৬": 6, "৭": 7, "৮": 8, "৯": 9 };
  for (let i = 0; i < 10; i++) {
    DIGITS[String.fromCharCode(0x660 + i)] = i; // ٠-٩
    DIGITS[String.fromCharCode(0x6f0 + i)] = i; // ۰-۹
  }

  // A typed amount: null when blank, NaN when it isn't a number of zero or more. Thousands separators
  // are ignored ("1,25,000", "1,250.5"); a comma is the decimal point only when it's the last
  // separator and 1 or 2 digits follow it ("12,5", "1.234,56"). "٫" is the Arabic decimal point.
  function parseAmount(text) {
    let s = String(text == null ? "" : text).trim();
    if (!s) return null;
    s = s.replace(/[০-৯٠-٩۰-۹]/g, (d) => String(DIGITS[d])).replace(/[\s  '٬]/g, "").replace(/٫/g, ".");
    const lastComma = s.lastIndexOf(",");
    const lastDot = s.lastIndexOf(".");
    if (lastComma > lastDot && /^\d{1,2}$/.test(s.slice(lastComma + 1)) && (lastDot !== -1 || s.indexOf(",") === lastComma)) {
      s = s.slice(0, lastComma).replace(/[.,]/g, "") + "." + s.slice(lastComma + 1);
    } else {
      s = s.replace(/,/g, "");
    }
    if (!/^\d*\.?\d+$|^\d+\.$/.test(s)) return NaN;
    return Number(s);
  }

  const amount = (value) => (typeof value === "number" && isFinite(value) && value > 0 ? value : 0);
  const price = (value) => (typeof value === "number" && isFinite(value) && value > 0 ? value : null);

  // input: goldPrice and silverPrice per gram; gold and silver in grams; cash, receivables, stock,
  // investments and debts as amounts; standard "hanafi" (default) or "gold". Missing values count as 0.
  // Returns the values, the nisab used and why (basis), and the zakat due. When a price the
  // answer needs is missing, `missing` names it and net, nisabValue, reached and due are null.
  function calculate(input) {
    const goldPrice = price(input.goldPrice);
    const silverPrice = price(input.silverPrice);
    const gold = amount(input.gold);
    const silver = amount(input.silver);
    const money = MONEY.reduce((sum, key) => sum + amount(input[key]), 0);
    const debts = amount(input.debts);

    let basis;
    if (gold && !silver && !money) basis = "gold-only";
    else if (silver && !gold && !money) basis = "silver-only";
    else basis = input.standard === "gold" ? "gold" : "silver";
    const metal = basis === "gold-only" || basis === "gold" ? "gold" : "silver";

    const missing = [];
    if ((gold || metal === "gold") && !goldPrice) missing.push("goldPrice");
    if ((silver || metal === "silver") && !silverPrice) missing.push("silverPrice");

    const goldValue = gold && goldPrice ? gold * goldPrice : 0;
    const silverValue = silver && silverPrice ? silver * silverPrice : 0;
    const assets = goldValue + silverValue + money;
    const result = {
      goldValue, silverValue, money, assets, debts, basis, metal, nisabGrams: NISAB_GRAMS[metal], missing,
      net: null, nisabValue: null, reached: null, due: null,
      empty: !gold && !silver && !money,
    };
    if (missing.length) return result;
    result.net = Math.max(0, assets - debts);
    result.nisabValue = NISAB_GRAMS[metal] * (metal === "gold" ? goldPrice : silverPrice);
    result.reached = result.net > 0 && result.net >= result.nisabValue;
    result.due = result.reached ? result.net * RATE : 0;
    return result;
  }

  root.Zakat = { RATE, NISAB_GRAMS, UNITS, CURRENCIES, COUNTRY_CURRENCIES, REGION_CURRENCIES, parseAmount, calculate };
})(typeof window !== "undefined" ? window : globalThis);
