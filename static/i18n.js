/* The chat and books pages' own text in English, Bengali and Arabic, and the reader's choice of language.
 *
 * Load it in <head>: it sets <html lang> and dir (Arabic reads right to left) before the page is drawn.
 * Then the page calls DeenI18n.apply() to translate elements marked with data-i18n (text),
 * data-i18n-placeholder, data-i18n-aria-label or data-i18n-title, and DeenI18n.t(key, vars) for text it
 * builds itself. The choice is kept in this browser (localStorage) and is also the preferred language
 * for books: the books page lists books in it first.
 *
 * A string can hold {name} placeholders, filled from vars (numbers are written the language's way, e.g.
 * Bengali digits). A string that depends on a number is an object of plural forms, picked with
 * Intl.PluralRules from vars.count: "one", "two", "few", "many" or "other" (always present).
 * tests/test_i18n.py checks that every language has every key the pages use.
 */
(function (root) {
  "use strict";

  const LANGUAGES = {
    en: { name: "English", dir: "ltr" },
    bn: { name: "বাংলা", dir: "ltr" },
    ar: { name: "العربية", dir: "rtl" },
  };
  const STORAGE_KEY = "deen-language";

  const STRINGS = {
    "en": {
      "lang.label": "Language",

      "chat.title": "Deen · Quran & Hadith Q&A",
      "chat.tagline": "Quran & Hadith Q&A with citations",
      "chat.text": "Text",
      "chat.allTexts": "All texts",
      "chat.passages": "Passages",
      "chat.newChat": "New chat",
      "chat.books": "Books",
      "chat.emptyTitle": "Ask about the Quran and Hadith",
      "chat.emptyBody": "Answers follow the Hanafi school and come only from passages found in the Quran and Hadith, with every source cited: Surah and Ayah for the Quran, and collection, number and grade for each hadith. Ask in English, Arabic or Bengali, and follow up as you go.",
      "chat.chip1": "What does the Quran say about patience in hardship?",
      "chat.chip2": "What do the hadith say about the virtue of charity?",
      "chat.inputLabel": "Your question",
      "chat.placeholder": "Ask about the Quran or Hadith…",
      "chat.send": "Send question",
      "chat.keys": "Enter to send · Shift+Enter for a new line · ",
      "chat.disclaimer": "Answers can be incomplete, so check the cited sources.",
      "chat.scope": { "one": "{text} · {count} passage", "other": "{text} · {count} passages" },
      "chat.searching": "Searching the texts and writing an answer…",
      "chat.sources": { "one": "{count} source", "other": "{count} sources" },
      "chat.searchedFor": "Searched for: ",
      "chat.readBook": "Read “{title}”",
      "chat.readBookPage": "Read “{title}”, page {page}",
      "chat.retry": "Try again",
      "chat.unreachable": "Could not reach the server. Check that it is running, then try again.",
      "chat.unreadable": "The server's reply could not be read. Try again in a moment.",
      "chat.invalid": "Invalid request.",
      "chat.httpError": "The server returned an error (HTTP {status}).",
      "chat.availableTexts": " Available texts: {list}.",
      "chat.textsFailed": "Could not load the list of texts; searching all texts.",

      "reader.duas": "Duas",
      "reader.namaz": "Namaz Shikkha",
      "reader.close": "Close {name}",
      "reader.previous": "Previous",
      "reader.next": "Next",
      "reader.position": "Passage number",
      "reader.of": "of {total}",
      "reader.loading": "Loading…",
      "reader.empty": "Nothing has been added to {name} yet. Admins can add it by uploading files to the text named “{text}”.",

      "azan.title": "Azan times",
      "azan.close": "Close azan times",
      "azan.location": "Location",
      "azan.chooseCity": "Choose a city…",
      "azan.useLocation": "Use my location",
      "azan.method": "Calculation method",
      "azan.methodLabel": "Method",
      "azan.asr": "Asr",
      "azan.asrHanafi": "Hanafi: shadow twice its length",
      "azan.asrStandard": "Shafi'i, Maliki, Hanbali: shadow its length",
      "azan.note": "Times are calculated from the location and may differ by a few minutes from your local mosque's timetable. Your location stays in this browser.",
      "azan.cta": "Azan times: choose your location",
      "azan.next": "Next: ",
      "azan.now": "now",
      "azan.in": "in {time}",
      "azan.hours": "{count} h",
      "azan.minutes": "{count} min",
      "azan.noAzan": "no azan",
      "azan.nextTag": "next · {when}",
      "azan.localTime": " (local time there)",
      "azan.tomorrow": "Next azan: Fajr tomorrow at {time}, {when}.",
      "azan.finding": "Finding your location…",
      "azan.denied": "Location access was turned down. Choose a city instead, or allow location for this site.",
      "azan.notFound": "Your location couldn't be found. Choose a city instead.",
      "azan.myLocation": "My location",
      "prayer.fajr": "Fajr",
      "prayer.sunrise": "Sunrise",
      "prayer.dhuhr": "Dhuhr",
      "prayer.asr": "Asr",
      "prayer.maghrib": "Maghrib",
      "prayer.isha": "Isha",

      "zakat.button": "Zakat",
      "zakat.title": "Zakat calculator",
      "zakat.close": "Close zakat calculator",
      "zakat.intro": "Work out the zakat on your wealth, following the Hanafi school.",
      "zakat.prices": "Today's prices",
      "zakat.currency": "Currency",
      "zakat.unit": "Weigh gold and silver in",
      "zakat.unit.gram": "grams",
      "zakat.unit.tola": "tola or bhori (11.664 g)",
      "zakat.unit.ounce": "troy ounces (31.1 g)",
      "zakat.unitName.gram": "gram",
      "zakat.unitName.tola": "tola",
      "zakat.unitName.ounce": "troy ounce",
      "zakat.amount.gram": "{n} g",
      "zakat.amount.tola": "{n} tola",
      "zakat.amount.ounce": "{n} oz",
      "zakat.goldPrice": "Gold price per {unit}",
      "zakat.silverPrice": "Silver price per {unit}",
      "zakat.pricesHelp": "Use today's local rate for the kind of gold you own (such as 22 carat), for example from your jewellers' association.",
      "zakat.own": "What you own",
      "zakat.gold": "Gold, in {unit}s",
      "zakat.goldHelp": "Include jewellery you wear: in the Hanafi school it is zakatable. Gems such as diamonds aren't, unless kept for sale.",
      "zakat.silver": "Silver, in {unit}s",
      "zakat.cash": "Cash, in hand and in the bank",
      "zakat.receivables": "Money owed to you",
      "zakat.receivablesHelp": "Loans you've given that you expect to be repaid. You may pay their zakat when you get them back.",
      "zakat.stock": "Goods for sale",
      "zakat.stockHelp": "Stock you bought to sell, at today's selling price.",
      "zakat.investments": "Shares, funds and savings schemes",
      "zakat.investmentsHelp": "At today's value. If you hold shares for their dividends rather than to sell, ask a scholar: only part may be zakatable.",
      "zakat.owe": "What you owe",
      "zakat.debts": "Debts due",
      "zakat.debtsHelp": "Money you owe now, and this year's instalments of long-term loans such as a home loan.",
      "zakat.standard": "Nisab",
      "zakat.standardHanafi": "Hanafi: silver when your wealth is mixed",
      "zakat.standardGold": "Gold, for all wealth",
      "zakat.result": "Your zakat",
      "zakat.assetsTotal": "Zakatable assets",
      "zakat.debtsTotal": "Less debts",
      "zakat.net": "Zakatable wealth",
      "zakat.nisab": "Nisab",
      "zakat.ofGold": "{amount} of gold",
      "zakat.ofSilver": "{amount} of silver",
      "zakat.basisSilver": "Your wealth isn't gold or silver alone, so in the Hanafi school it's measured against the nisab of silver, which is better for the poor.",
      "zakat.basisGoldOnly": "You own only gold, so it's measured by its own nisab: 7.5 tola (87.48 g) of gold.",
      "zakat.basisSilverOnly": "You own only silver, so it's measured by its own nisab: 52.5 tola (612.36 g) of silver.",
      "zakat.basisGold": "You chose to measure all your wealth against the nisab of gold: 7.5 tola (87.48 g).",
      "zakat.due": "Zakat due (2.5%)",
      "zakat.dueShort": "Zakat due",
      "zakat.notDue": "Below the nisab: no zakat is due.",
      "zakat.belowNisab": "Below the nisab",
      "zakat.needGoldPrice": "Enter today's gold price to work out your zakat.",
      "zakat.needSilverPrice": "Enter today's silver price to work out the nisab.",
      "zakat.empty": "Enter what you own to see your zakat.",
      "zakat.invalid": "Enter numbers only, such as 1250 or 1,250.50.",
      "zakat.noteYear": "Zakat is due on wealth at or above the nisab once you have held it for a full lunar (Hijri) year.",
      "zakat.noteExempt": "Your home, car, household goods and personal belongings aren't zakatable.",
      "zakat.noteScholar": "This follows the Hanafi school. For a business, shares, loans or other complex cases, ask a qualified Hanafi scholar.",
      "zakat.notePrivacy": "Worked out in this browser. Prices and settings are remembered here; amounts aren't.",
      "zakat.clear": "Clear amounts",
      "zakat.ask": "Ask Deen about zakat",
      "zakat.askQuestion": "What do the Quran and hadith say about zakat on savings, gold and jewellery?",

      "books.title": "Deen · Books",
      "books.heading": "Books",
      "books.intro": "Read the books Deen's answers come from, one page at a time. Your place in each book is saved in this browser.",
      "books.openChat": "Open chat",
      "books.continue": "Continue reading",
      "books.pageOf": "Page {page} of {pages}",
      "books.pages": { "one": "{count} page", "other": "{count} pages" },
      "books.noLanguage": "Language not set",
      "books.empty": "No books yet. Books appear here when an admin uploads PDF files.",
      "books.loading": "Loading…",
      "books.loadFailed": "The books couldn't be loaded.",
      "books.allBooks": "All books",
      "books.previous": "Previous",
      "books.next": "Next",
      "books.pageNumber": "Page number",
      "books.pager": "Pages",
      "books.of": "of {pages}",
      "books.zoomIn": "Zoom in",
      "books.zoomOut": "Zoom out",
      "books.fit": "Fit to width",
      "books.openPdf": "Open PDF",
      "books.opening": "Opening the book…",
      "books.openFailed": "This book couldn't be opened.",
      "books.missing": "This book isn't available any more.",
      "books.resume": "Continue from page {page}",
      "books.retry": "Try again"
    },

    "bn": {
      "lang.label": "ভাষা",

      "chat.title": "Deen · কুরআন ও হাদিস প্রশ্নোত্তর",
      "chat.tagline": "সূত্রসহ কুরআন ও হাদিস প্রশ্নোত্তর",
      "chat.text": "গ্রন্থ",
      "chat.allTexts": "সব গ্রন্থ",
      "chat.passages": "অংশ",
      "chat.newChat": "নতুন চ্যাট",
      "chat.books": "বই",
      "chat.emptyTitle": "কুরআন ও হাদিস সম্পর্কে জিজ্ঞাসা করুন",
      "chat.emptyBody": "উত্তরগুলো হানাফি মাযহাব অনুসরণ করে এবং কেবল কুরআন ও হাদিসে পাওয়া অংশ থেকেই দেওয়া হয়, প্রতিটি সূত্রের উল্লেখসহ: কুরআনের জন্য সূরা ও আয়াত, আর প্রতিটি হাদিসের জন্য গ্রন্থ, নম্বর ও মান। বাংলা, ইংরেজি বা আরবিতে প্রশ্ন করুন, আর প্রয়োজনে আরও জানতে চান।",
      "chat.chip1": "বিপদে ধৈর্য ধরা সম্পর্কে কুরআন কী বলে?",
      "chat.chip2": "দান-সদকার ফজিলত সম্পর্কে হাদিসে কী বলা হয়েছে?",
      "chat.inputLabel": "আপনার প্রশ্ন",
      "chat.placeholder": "কুরআন বা হাদিস সম্পর্কে জিজ্ঞাসা করুন…",
      "chat.send": "প্রশ্ন পাঠান",
      "chat.keys": "পাঠাতে Enter · নতুন লাইনের জন্য Shift+Enter · ",
      "chat.disclaimer": "উত্তর অসম্পূর্ণ হতে পারে, তাই উল্লেখিত সূত্রগুলো যাচাই করে নিন।",
      "chat.scope": { "other": "{text} · {count}টি অংশ" },
      "chat.searching": "গ্রন্থগুলোতে খোঁজা হচ্ছে এবং উত্তর লেখা হচ্ছে…",
      "chat.sources": { "other": "{count}টি সূত্র" },
      "chat.searchedFor": "যা খোঁজা হয়েছে: ",
      "chat.readBook": "“{title}” বইটি পড়ুন",
      "chat.readBookPage": "“{title}” বইয়ের {page} নম্বর পৃষ্ঠা পড়ুন",
      "chat.retry": "আবার চেষ্টা করুন",
      "chat.unreachable": "সার্ভারে পৌঁছানো যায়নি। সার্ভার চালু আছে কি না দেখে আবার চেষ্টা করুন।",
      "chat.unreadable": "সার্ভারের উত্তর পড়া যায়নি। একটু পরে আবার চেষ্টা করুন।",
      "chat.invalid": "অনুরোধটি সঠিক নয়।",
      "chat.httpError": "সার্ভার একটি ত্রুটি জানিয়েছে (HTTP {status})।",
      "chat.availableTexts": " যে গ্রন্থগুলো আছে: {list}।",
      "chat.textsFailed": "গ্রন্থের তালিকা আনা যায়নি; সব গ্রন্থে খোঁজা হবে।",

      "reader.duas": "দোয়া",
      "reader.namaz": "নামাজ শিক্ষা",
      "reader.close": "{name} বন্ধ করুন",
      "reader.previous": "আগের",
      "reader.next": "পরের",
      "reader.position": "অংশ নম্বর",
      "reader.of": "/ {total}",
      "reader.loading": "লোড হচ্ছে…",
      "reader.empty": "{name}-এ এখনো কিছু যোগ করা হয়নি। অ্যাডমিন “{text}” নামের গ্রন্থে ফাইল আপলোড করে তা যোগ করতে পারেন।",

      "azan.title": "আজানের সময়",
      "azan.close": "আজানের সময় বন্ধ করুন",
      "azan.location": "অবস্থান",
      "azan.chooseCity": "একটি শহর বেছে নিন…",
      "azan.useLocation": "আমার অবস্থান ব্যবহার করুন",
      "azan.method": "হিসাবের পদ্ধতি",
      "azan.methodLabel": "পদ্ধতি",
      "azan.asr": "আসর",
      "azan.asrHanafi": "হানাফি: ছায়া বস্তুর দ্বিগুণ হলে",
      "azan.asrStandard": "শাফেয়ি, মালেকি, হাম্বলি: ছায়া বস্তুর সমান হলে",
      "azan.note": "সময়গুলো অবস্থান থেকে হিসাব করা, তাই আপনার এলাকার মসজিদের সময়সূচির সঙ্গে কয়েক মিনিটের পার্থক্য হতে পারে। আপনার অবস্থান এই ব্রাউজারেই থাকে।",
      "azan.cta": "আজানের সময়: আপনার অবস্থান বেছে নিন",
      "azan.next": "পরবর্তী: ",
      "azan.now": "এখন",
      "azan.in": "{time} পর",
      "azan.hours": "{count} ঘণ্টা",
      "azan.minutes": "{count} মিনিট",
      "azan.noAzan": "আজান নেই",
      "azan.nextTag": "পরবর্তী · {when}",
      "azan.localTime": " (সেখানকার স্থানীয় সময়)",
      "azan.tomorrow": "পরবর্তী আজান: আগামীকাল ফজর {time}-এ, {when}।",
      "azan.finding": "আপনার অবস্থান খোঁজা হচ্ছে…",
      "azan.denied": "অবস্থান জানার অনুমতি দেওয়া হয়নি। এর বদলে একটি শহর বেছে নিন, অথবা এই সাইটকে অবস্থান জানার অনুমতি দিন।",
      "azan.notFound": "আপনার অবস্থান পাওয়া যায়নি। এর বদলে একটি শহর বেছে নিন।",
      "azan.myLocation": "আমার অবস্থান",
      "prayer.fajr": "ফজর",
      "prayer.sunrise": "সূর্যোদয়",
      "prayer.dhuhr": "যোহর",
      "prayer.asr": "আসর",
      "prayer.maghrib": "মাগরিব",
      "prayer.isha": "এশা",

      "zakat.button": "যাকাত",
      "zakat.title": "যাকাত হিসাব",
      "zakat.close": "যাকাত হিসাব বন্ধ করুন",
      "zakat.intro": "হানাফি মাযহাব অনুযায়ী আপনার সম্পদের যাকাত হিসাব করুন।",
      "zakat.prices": "আজকের দাম",
      "zakat.currency": "মুদ্রা",
      "zakat.unit": "সোনা ও রুপার ওজনের একক",
      "zakat.unit.gram": "গ্রাম",
      "zakat.unit.tola": "ভরি বা তোলা (১১.৬৬৪ গ্রাম)",
      "zakat.unit.ounce": "ট্রয় আউন্স (৩১.১ গ্রাম)",
      "zakat.unitName.gram": "গ্রাম",
      "zakat.unitName.tola": "ভরি",
      "zakat.unitName.ounce": "ট্রয় আউন্স",
      "zakat.amount.gram": "{n} গ্রাম",
      "zakat.amount.tola": "{n} ভরি",
      "zakat.amount.ounce": "{n} আউন্স",
      "zakat.goldPrice": "প্রতি {unit} সোনার দাম",
      "zakat.silverPrice": "প্রতি {unit} রুপার দাম",
      "zakat.pricesHelp": "আপনার কাছে যে ধরনের সোনা আছে (যেমন ২২ ক্যারেট), তার আজকের স্থানীয় দাম লিখুন, যেমন জুয়েলার্স সমিতির ঘোষিত দাম।",
      "zakat.own": "আপনার যা আছে",
      "zakat.gold": "সোনা, {unit} হিসেবে",
      "zakat.goldHelp": "পরিধানের গয়নাও ধরুন: হানাফি মাযহাবে এরও যাকাত দিতে হয়। হীরার মতো রত্নের যাকাত নেই, যদি না তা বিক্রির জন্য রাখা হয়।",
      "zakat.silver": "রুপা, {unit} হিসেবে",
      "zakat.cash": "নগদ অর্থ, হাতে ও ব্যাংকে",
      "zakat.receivables": "আপনার পাওনা অর্থ",
      "zakat.receivablesHelp": "যে ঋণ দিয়েছেন এবং ফেরত পাওয়ার আশা করেন। চাইলে তা ফেরত পাওয়ার পর এর যাকাত দিতে পারেন।",
      "zakat.stock": "বিক্রির জন্য রাখা পণ্য",
      "zakat.stockHelp": "বিক্রির উদ্দেশ্যে কেনা মাল, আজকের বিক্রয়মূল্যে।",
      "zakat.investments": "শেয়ার, ফান্ড ও সঞ্চয় প্রকল্প",
      "zakat.investmentsHelp": "আজকের মূল্যে। শেয়ার বিক্রির জন্য নয়, লভ্যাংশের জন্য রাখলে একজন আলেমকে জিজ্ঞাসা করুন: হয়তো এর একটি অংশেরই যাকাত দিতে হবে।",
      "zakat.owe": "আপনার দেনা",
      "zakat.debts": "পরিশোধযোগ্য ঋণ",
      "zakat.debtsHelp": "এখন যে অর্থ পরিশোধ করতে হবে, এবং দীর্ঘমেয়াদি ঋণের (যেমন বাড়ির ঋণ) এ বছরের কিস্তি।",
      "zakat.standard": "নিসাব",
      "zakat.standardHanafi": "হানাফি: সম্পদ মিশ্র হলে রুপার নিসাব",
      "zakat.standardGold": "সব সম্পদের জন্য সোনার নিসাব",
      "zakat.result": "আপনার যাকাত",
      "zakat.assetsTotal": "যাকাতযোগ্য সম্পদ",
      "zakat.debtsTotal": "বাদ: ঋণ",
      "zakat.net": "যাকাতযোগ্য নিট সম্পদ",
      "zakat.nisab": "নিসাব",
      "zakat.ofGold": "{amount} সোনা",
      "zakat.ofSilver": "{amount} রুপা",
      "zakat.basisSilver": "আপনার সম্পদ শুধু সোনা বা শুধু রুপা নয়, তাই হানাফি মাযহাবে তা রুপার নিসাব দিয়ে মাপা হয়, যা গরিবদের জন্য বেশি উপকারী।",
      "zakat.basisGoldOnly": "আপনার শুধু সোনা আছে, তাই তা সোনার নিজস্ব নিসাব দিয়ে মাপা হয়: সাড়ে সাত ভরি (৮৭.৪৮ গ্রাম) সোনা।",
      "zakat.basisSilverOnly": "আপনার শুধু রুপা আছে, তাই তা রুপার নিজস্ব নিসাব দিয়ে মাপা হয়: সাড়ে বায়ান্ন ভরি (৬১২.৩৬ গ্রাম) রুপা।",
      "zakat.basisGold": "আপনি সব সম্পদ সোনার নিসাব দিয়ে মাপতে বেছে নিয়েছেন: সাড়ে সাত ভরি (৮৭.৪৮ গ্রাম)।",
      "zakat.due": "দেয় যাকাত (২.৫%)",
      "zakat.dueShort": "দেয় যাকাত",
      "zakat.notDue": "নিসাবের নিচে: যাকাত ফরজ নয়।",
      "zakat.belowNisab": "নিসাবের নিচে",
      "zakat.needGoldPrice": "যাকাত হিসাব করতে আজকের সোনার দাম লিখুন।",
      "zakat.needSilverPrice": "নিসাব হিসাব করতে আজকের রুপার দাম লিখুন।",
      "zakat.empty": "আপনার যাকাত দেখতে আপনার সম্পদের পরিমাণ লিখুন।",
      "zakat.invalid": "শুধু সংখ্যা লিখুন, যেমন ১২৫০ বা ১,২৫০.৫০।",
      "zakat.noteYear": "নিসাব পরিমাণ বা তার বেশি সম্পদ পূর্ণ এক চন্দ্র (হিজরি) বছর আপনার মালিকানায় থাকলে তার যাকাত ফরজ হয়।",
      "zakat.noteExempt": "বসতবাড়ি, গাড়ি, গৃহস্থালি জিনিস ও ব্যক্তিগত ব্যবহারের জিনিসের যাকাত নেই।",
      "zakat.noteScholar": "এই হিসাব হানাফি মাযহাব অনুযায়ী। ব্যবসা, শেয়ার, ঋণ বা অন্য জটিল ক্ষেত্রে একজন যোগ্য হানাফি আলেমকে জিজ্ঞাসা করুন।",
      "zakat.notePrivacy": "এই ব্রাউজারেই হিসাব করা হয়। দাম ও সেটিংস এখানে মনে রাখা হয়; সম্পদের পরিমাণ নয়।",
      "zakat.clear": "পরিমাণগুলো মুছুন",
      "zakat.ask": "যাকাত সম্পর্কে Deen-কে জিজ্ঞাসা করুন",
      "zakat.askQuestion": "সঞ্চয়, সোনা ও গয়নার যাকাত সম্পর্কে কুরআন ও হাদিসে কী বলা হয়েছে?",

      "books.title": "Deen · বই",
      "books.heading": "বই",
      "books.intro": "Deen-এর উত্তর যেসব বই থেকে আসে, সেগুলো পৃষ্ঠা ধরে পড়ুন। প্রতিটি বইয়ে আপনি কোথায় ছিলেন, তা এই ব্রাউজারে সংরক্ষিত থাকে।",
      "books.openChat": "চ্যাট খুলুন",
      "books.continue": "পড়া চালিয়ে যান",
      "books.pageOf": "পৃষ্ঠা {page} / {pages}",
      "books.pages": { "other": "{count} পৃষ্ঠা" },
      "books.noLanguage": "ভাষা উল্লেখ নেই",
      "books.empty": "এখনো কোনো বই নেই। অ্যাডমিন PDF ফাইল আপলোড করলে বইগুলো এখানে দেখা যাবে।",
      "books.loading": "লোড হচ্ছে…",
      "books.loadFailed": "বইগুলো লোড করা যায়নি।",
      "books.allBooks": "সব বই",
      "books.previous": "আগের",
      "books.next": "পরের",
      "books.pageNumber": "পৃষ্ঠা নম্বর",
      "books.pager": "পৃষ্ঠাগুলো",
      "books.of": "/ {pages}",
      "books.zoomIn": "বড় করুন",
      "books.zoomOut": "ছোট করুন",
      "books.fit": "প্রস্থ অনুযায়ী মানানসই",
      "books.openPdf": "PDF খুলুন",
      "books.opening": "বইটি খোলা হচ্ছে…",
      "books.openFailed": "বইটি খোলা যায়নি।",
      "books.missing": "এই বইটি আর পাওয়া যাচ্ছে না।",
      "books.resume": "{page} নম্বর পৃষ্ঠা থেকে পড়া চালিয়ে যান",
      "books.retry": "আবার চেষ্টা করুন"
    },

    "ar": {
      "lang.label": "اللغة",

      "chat.title": "Deen · أسئلة وأجوبة من القرآن والحديث",
      "chat.tagline": "أسئلة وأجوبة من القرآن والحديث مع ذكر المصادر",
      "chat.text": "النص",
      "chat.allTexts": "كل النصوص",
      "chat.passages": "المقاطع",
      "chat.newChat": "محادثة جديدة",
      "chat.books": "الكتب",
      "chat.emptyTitle": "اسأل عن القرآن والحديث",
      "chat.emptyBody": "تتبع الإجابات المذهب الحنفي، ولا تُستمد إلا من مقاطع وردت في القرآن والحديث، مع ذكر كل مصدر: السورة والآية للقرآن، والكتاب والرقم والدرجة لكل حديث. اسأل بالعربية أو الإنجليزية أو البنغالية، وتابع بأسئلة أخرى كما تشاء.",
      "chat.chip1": "ماذا يقول القرآن عن الصبر عند الشدائد؟",
      "chat.chip2": "ماذا تقول الأحاديث عن فضل الصدقة؟",
      "chat.inputLabel": "سؤالك",
      "chat.placeholder": "اسأل عن القرآن أو الحديث…",
      "chat.send": "إرسال السؤال",
      "chat.keys": "Enter للإرسال · Shift+Enter لسطر جديد · ",
      "chat.disclaimer": "قد تكون الإجابات ناقصة، فتحقق من المصادر المذكورة.",
      "chat.scope": {
        "one": "{text} · مقطع واحد",
        "two": "{text} · مقطعان",
        "few": "{text} · {count} مقاطع",
        "many": "{text} · {count} مقطعًا",
        "other": "{text} · {count} مقطع"
      },
      "chat.searching": "جارٍ البحث في النصوص وكتابة الإجابة…",
      "chat.sources": {
        "one": "مصدر واحد",
        "two": "مصدران",
        "few": "{count} مصادر",
        "many": "{count} مصدرًا",
        "other": "{count} مصدر"
      },
      "chat.searchedFor": "تم البحث عن: ",
      "chat.readBook": "اقرأ «{title}»",
      "chat.readBookPage": "اقرأ «{title}»، الصفحة {page}",
      "chat.retry": "حاول مرة أخرى",
      "chat.unreachable": "تعذّر الوصول إلى الخادم. تأكد من أنه يعمل، ثم حاول مرة أخرى.",
      "chat.unreadable": "تعذّرت قراءة رد الخادم. حاول مرة أخرى بعد قليل.",
      "chat.invalid": "الطلب غير صالح.",
      "chat.httpError": "أعاد الخادم خطأً (HTTP {status}).",
      "chat.availableTexts": " النصوص المتاحة: {list}.",
      "chat.textsFailed": "تعذّر تحميل قائمة النصوص؛ سيتم البحث في كل النصوص.",

      "reader.duas": "الأدعية",
      "reader.namaz": "تعليم الصلاة",
      "reader.close": "إغلاق {name}",
      "reader.previous": "السابق",
      "reader.next": "التالي",
      "reader.position": "رقم المقطع",
      "reader.of": "من {total}",
      "reader.loading": "جارٍ التحميل…",
      "reader.empty": "لم يُضف شيء إلى {name} بعد. يمكن للمشرفين إضافته برفع ملفات إلى النص المسمى “{text}”.",

      "azan.title": "مواقيت الأذان",
      "azan.close": "إغلاق مواقيت الأذان",
      "azan.location": "الموقع",
      "azan.chooseCity": "اختر مدينة…",
      "azan.useLocation": "استخدم موقعي",
      "azan.method": "طريقة الحساب",
      "azan.methodLabel": "الطريقة",
      "azan.asr": "العصر",
      "azan.asrHanafi": "الحنفي: حين يصير الظل مثلَي طول الشيء",
      "azan.asrStandard": "الشافعي والمالكي والحنبلي: حين يصير الظل مثل طول الشيء",
      "azan.note": "تُحسب المواقيت من الموقع، وقد تختلف ببضع دقائق عن جدول مسجدك المحلي. يبقى موقعك في هذا المتصفح.",
      "azan.cta": "مواقيت الأذان: اختر موقعك",
      "azan.next": "التالي: ",
      "azan.now": "الآن",
      "azan.in": "بعد {time}",
      "azan.hours": "{count} س",
      "azan.minutes": "{count} د",
      "azan.noAzan": "لا أذان",
      "azan.nextTag": "التالي · {when}",
      "azan.localTime": " (بالتوقيت المحلي هناك)",
      "azan.tomorrow": "الأذان التالي: الفجر غدًا الساعة {time}، {when}.",
      "azan.finding": "جارٍ تحديد موقعك…",
      "azan.denied": "تم رفض الوصول إلى الموقع. اختر مدينة بدلًا من ذلك، أو اسمح لهذا الموقع بمعرفة موقعك.",
      "azan.notFound": "تعذّر تحديد موقعك. اختر مدينة بدلًا من ذلك.",
      "azan.myLocation": "موقعي",
      "prayer.fajr": "الفجر",
      "prayer.sunrise": "الشروق",
      "prayer.dhuhr": "الظهر",
      "prayer.asr": "العصر",
      "prayer.maghrib": "المغرب",
      "prayer.isha": "العشاء",

      "zakat.button": "الزكاة",
      "zakat.title": "حاسبة الزكاة",
      "zakat.close": "إغلاق حاسبة الزكاة",
      "zakat.intro": "احسب زكاة أموالك وفق المذهب الحنفي.",
      "zakat.prices": "أسعار اليوم",
      "zakat.currency": "العملة",
      "zakat.unit": "وحدة وزن الذهب والفضة",
      "zakat.unit.gram": "غرام",
      "zakat.unit.tola": "تولة (11.664 غ)",
      "zakat.unit.ounce": "أونصة (31.1 غ)",
      "zakat.unitName.gram": "غرام",
      "zakat.unitName.tola": "تولة",
      "zakat.unitName.ounce": "أونصة",
      "zakat.amount.gram": "{n} غ",
      "zakat.amount.tola": "{n} تولة",
      "zakat.amount.ounce": "{n} أونصة",
      "zakat.goldPrice": "سعر الذهب لكل {unit}",
      "zakat.silverPrice": "سعر الفضة لكل {unit}",
      "zakat.pricesHelp": "استخدم سعر اليوم المحلي لنوع الذهب الذي تملكه (مثل عيار 22)، كالسعر الذي تعلنه نقابة الصاغة في بلدك.",
      "zakat.own": "ما تملكه",
      "zakat.gold": "الذهب، بوحدة {unit}",
      "zakat.goldHelp": "أدخل الحلي التي تلبسها، فهي تجب فيها الزكاة في المذهب الحنفي. ولا زكاة في الأحجار الكريمة كالألماس إلا إذا كانت للتجارة.",
      "zakat.silver": "الفضة، بوحدة {unit}",
      "zakat.cash": "النقد، في اليد وفي البنك",
      "zakat.receivables": "الديون التي لك على الناس",
      "zakat.receivablesHelp": "القروض التي أقرضتها وترجو استردادها. ويجوز أن تؤدي زكاتها عند قبضها.",
      "zakat.stock": "عروض التجارة",
      "zakat.stockHelp": "البضائع التي اشتريتها بنية البيع، بسعر بيعها اليوم.",
      "zakat.investments": "الأسهم والصناديق وخطط الادخار",
      "zakat.investmentsHelp": "بقيمتها اليوم. وإن كنت تحتفظ بالأسهم لأرباحها لا لبيعها فاسأل عالمًا، فقد تجب الزكاة في جزء منها فقط.",
      "zakat.owe": "ما عليك من ديون",
      "zakat.debts": "الديون المستحقة",
      "zakat.debtsHelp": "ما عليك سداده الآن، وأقساط هذا العام من القروض الطويلة كقرض المنزل.",
      "zakat.standard": "النصاب",
      "zakat.standardHanafi": "الحنفي: نصاب الفضة إذا اختلطت الأموال",
      "zakat.standardGold": "نصاب الذهب لكل الأموال",
      "zakat.result": "زكاتك",
      "zakat.assetsTotal": "الأموال الزكوية",
      "zakat.debtsTotal": "ناقص الديون",
      "zakat.net": "صافي المال الزكوي",
      "zakat.nisab": "النصاب",
      "zakat.ofGold": "{amount} من الذهب",
      "zakat.ofSilver": "{amount} من الفضة",
      "zakat.basisSilver": "أموالك ليست ذهبًا وحده ولا فضة وحدها، فتُقدَّر في المذهب الحنفي بنصاب الفضة، لأنه أنفع للفقراء.",
      "zakat.basisGoldOnly": "لا تملك إلا الذهب، فيُقدَّر بنصابه: 87.48 غرامًا من الذهب (7.5 تولة).",
      "zakat.basisSilverOnly": "لا تملك إلا الفضة، فتُقدَّر بنصابها: 612.36 غرامًا من الفضة (52.5 تولة).",
      "zakat.basisGold": "اخترت تقدير كل أموالك بنصاب الذهب: 87.48 غرامًا (7.5 تولة).",
      "zakat.due": "الزكاة الواجبة (2.5%)",
      "zakat.dueShort": "الزكاة الواجبة",
      "zakat.notDue": "دون النصاب: لا تجب الزكاة.",
      "zakat.belowNisab": "دون النصاب",
      "zakat.needGoldPrice": "أدخل سعر الذهب اليوم لحساب زكاتك.",
      "zakat.needSilverPrice": "أدخل سعر الفضة اليوم لحساب النصاب.",
      "zakat.empty": "أدخل ما تملكه لترى زكاتك.",
      "zakat.invalid": "أدخل أرقامًا فقط، مثل 1250 أو 1,250.50.",
      "zakat.noteYear": "تجب الزكاة في المال البالغ نصابًا إذا حال عليه حول هجري كامل.",
      "zakat.noteExempt": "لا زكاة في بيتك وسيارتك وأثاث منزلك وحاجاتك الشخصية.",
      "zakat.noteScholar": "هذا الحساب وفق المذهب الحنفي. وفي التجارة والأسهم والديون وغيرها من الحالات المعقدة، اسأل عالمًا حنفيًا مؤهلًا.",
      "zakat.notePrivacy": "يُحسب في هذا المتصفح. تُحفظ الأسعار والإعدادات هنا، أما المبالغ فلا.",
      "zakat.clear": "مسح المبالغ",
      "zakat.ask": "اسأل Deen عن الزكاة",
      "zakat.askQuestion": "ماذا يقول القرآن والحديث عن زكاة المدخرات والذهب والحلي؟",

      "books.title": "Deen · الكتب",
      "books.heading": "الكتب",
      "books.intro": "اقرأ الكتب التي تُستمد منها إجابات Deen صفحةً صفحة. يُحفظ موضع قراءتك في كل كتاب في هذا المتصفح.",
      "books.openChat": "فتح المحادثة",
      "books.continue": "متابعة القراءة",
      "books.pageOf": "الصفحة {page} من {pages}",
      "books.pages": {
        "one": "صفحة واحدة",
        "two": "صفحتان",
        "few": "{count} صفحات",
        "many": "{count} صفحةً",
        "other": "{count} صفحة"
      },
      "books.noLanguage": "اللغة غير محددة",
      "books.empty": "لا توجد كتب بعد. تظهر الكتب هنا عندما يرفع المشرف ملفات PDF.",
      "books.loading": "جارٍ التحميل…",
      "books.loadFailed": "تعذّر تحميل الكتب.",
      "books.allBooks": "كل الكتب",
      "books.previous": "السابقة",
      "books.next": "التالية",
      "books.pageNumber": "رقم الصفحة",
      "books.pager": "الصفحات",
      "books.of": "من {pages}",
      "books.zoomIn": "تكبير",
      "books.zoomOut": "تصغير",
      "books.fit": "ملاءمة العرض",
      "books.openPdf": "فتح ملف PDF",
      "books.opening": "جارٍ فتح الكتاب…",
      "books.openFailed": "تعذّر فتح هذا الكتاب.",
      "books.missing": "هذا الكتاب لم يعد متاحًا.",
      "books.resume": "تابع من الصفحة {page}",
      "books.retry": "حاول مرة أخرى"
    }
  }; // end STRINGS

  function initialLanguage() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && LANGUAGES[saved]) return saved;
    } catch (_) { /* storage blocked */ }
    for (const tag of navigator.languages || [navigator.language || ""]) {
      const code = String(tag).toLowerCase().split("-")[0];
      if (LANGUAGES[code]) return code;
    }
    return "en";
  }

  let lang = initialLanguage();
  const listeners = [];
  const formats = {};

  function setDocumentLanguage() {
    document.documentElement.lang = lang;
    document.documentElement.dir = LANGUAGES[lang].dir;
  }

  function numberFormat(options) {
    const key = lang + JSON.stringify(options || {});
    return formats[key] || (formats[key] = new Intl.NumberFormat(lang, options));
  }

  // A string in the current language; English when a translation is missing; fallback (or the key) when neither has it.
  function t(key, vars, fallback) {
    let entry = STRINGS[lang][key];
    let rulesLang = lang;
    if (entry == null) { entry = STRINGS.en[key]; rulesLang = "en"; }
    if (entry == null) return fallback != null ? fallback : key;
    if (typeof entry === "object") {
      const count = vars && typeof vars.count === "number" ? vars.count : 0;
      entry = entry[new Intl.PluralRules(rulesLang).select(count)] || entry.other;
    }
    return entry.replace(/\{(\w+)\}/g, (match, name) => {
      const value = vars ? vars[name] : undefined;
      if (value == null) return match;
      return typeof value === "number" ? numberFormat().format(value) : String(value);
    });
  }

  function apply(rootNode) {
    const scope = rootNode || document;
    setDocumentLanguage();
    scope.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    for (const attr of ["placeholder", "aria-label", "title"]) {
      scope.querySelectorAll("[data-i18n-" + attr + "]").forEach((node) => {
        node.setAttribute(attr, t(node.getAttribute("data-i18n-" + attr)));
      });
    }
  }

  function set(code) {
    if (!LANGUAGES[code] || code === lang) return;
    lang = code;
    try { localStorage.setItem(STORAGE_KEY, code); } catch (_) { /* storage blocked: for this page only */ }
    apply();
    for (const listener of listeners) listener(lang);
  }

  // Fill a <select> with the languages, each in its own script, and switch when it changes.
  function bindSelect(select) {
    select.replaceChildren(...Object.entries(LANGUAGES).map(([code, info]) => {
      const option = new Option(info.name, code);
      option.lang = code;
      return option;
    }));
    select.value = lang;
    select.addEventListener("change", () => set(select.value));
    listeners.push(() => { select.value = lang; });
  }

  // A language's name in the current language, e.g. "ইংরেজি" for "en" when the page is in Bengali.
  function languageName(code, fallback) {
    try {
      const name = new Intl.DisplayNames([lang], { type: "language" }).of(code);
      if (name && name !== code) return name;
    } catch (_) { /* old browser, or an unknown code */ }
    return fallback || code;
  }

  setDocumentLanguage();

  root.DeenI18n = {
    LANGUAGES,
    get lang() { return lang; },
    get dir() { return LANGUAGES[lang].dir; },
    t,
    apply,
    set,
    bindSelect,
    onChange: (listener) => listeners.push(listener),
    number: (value, options) => numberFormat(options).format(value),
    languageName,
  };
})(window);
