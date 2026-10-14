"""The AI prompts' pure pieces (the Travel Guide's "Plan X with AI" and the
Trip tab's "Plan this trip with AI"), cut out of public/app.js by name and
run under jsc.

  aiPlain        the site's typography made ASCII for a link: · — – − ≈ °
                 … → and curly quotes, each 6-9 characters once encoded, and
                 a locale's amounts (no-break spaces, non-Latin digits);
                 names keep their letters
  AI_SITES /     each site's cap on the encoded prompt (ChatGPT 30000,
  aiLink         Claude 4000, Grok 6000, Perplexity 12000): within it the
                 prefill link, past it the site's plain new chat
  AI_HINT_TIP    built from AI_SITES: a site added there is in the tip
  fareCurveFacts a route's month fares as the prompts quote them: count,
                 cheapest first (ties keep the sooner month), the priciest
  monthKeyText   "2027-04" -> "Apr 2027" / "April 2027"
  avoidAreas     Canada's avoid-travel lines (production's replies of
                 2026-10-13, scripts/watchouts_sample.2026-10-13.json): the
                 area from each line's first sentence, its regions only where
                 that sentence lists them, exceptions said as exceptions,
                 never a generic heading for its list; brief for the trip
  aiTripFlights  one trip row's fares: the month's own, the strip's cheapest
                 and priciest, the window's in flexible mode, every month of
                 a sparse route, the average fallback
  aiGuideFlights the guide's FLIGHTS line and whether it has a month curve
  aiFx           the guide's FX verdict rule (after inflation, past 2%), on
                 the guide line's own figure
  aiLevelText    Germany's levels said as what they are
  aiEntryAsk     the Schengen 90/180 ask only for a passport from outside it
  tripMonth      unset under Top Picks' "Any time" is flexible over its window

    /usr/bin/python3 scripts/test_ai_prompts.py
"""
import json, os, re, subprocess, sys, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):   # `const name = …;` up to the statement's line-ending ";"
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def jsc(prog):
    try:
        out = subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout)
    except Exception:
        return None


BASE = "\n".join([js_const("MONTHS"), js_const("MON_ABBR"), js_fn("fmtDay")])
names = ["aiPlain", "aiLink", "fareCurveFacts", "monthKeyText", "unshout", "avoidLead", "avoidText", "avoidAreas", "aiTripFlights",
         "aiGuideFlights", "aiFx", "aiLevelText", "aiEntryAsk", "tripMonth", "tripMonthSaved", "todayText"]
consts = ["AI_SITES", "AI_HINT_TIP", "SCHENGEN", "AVOID_GENERIC", "DE_LVL_PROMPT", "HUB_CITY", "aiRange"]
results.append(ok(all(js_fn(n) for n in names) and all(js_const(n) for n in consts),
                  "the prompts' pieces found in app.js: " + ", ".join(names + consts)))

# --- aiPlain --------------------------------------------------------------------
SAMPLE = ("WHEN: October 2026 — one of its comfiest months · best Mar–Apr; "
          "“Exercise normal precaution.” It’s ≈ 61% · 38 °C (100 °F) − Nazaré, Kraków… → Seville")
got = jsc("%s\n%s\nconst s = %s; const p = aiPlain(s);\nprint(JSON.stringify({ p, a: encodeURIComponent(s).length, b: encodeURIComponent(p).length }));"
          % (BASE, js_fn("aiPlain"), json.dumps(SAMPLE)))
want = ("WHEN: October 2026 - one of its comfiest months, best Mar-Apr; \"Exercise normal precaution.\" It's ~61%, "
        "38 C (100 F) - Nazaré, Kraków... -> Seville")
results.append(ok(got and got["p"] == want, "aiPlain: dashes, middots, curly quotes, ≈, °, −, …, → made plain, names keep their letters (got %r)" % (got and got["p"])))
non_ascii = got and sorted({c for c in got["p"] if ord(c) > 127})
results.append(ok(non_ascii == ["é", "ó"], "aiPlain: the only non-ASCII left is the names' letters (got %s)" % non_ascii))
results.append(ok(got and got["b"] < got["a"] - 60, "aiPlain: the sample's encoded length drops %s -> %s" % (got and got["a"], got and got["b"])))
# Amounts in the reader's locale (toLocaleString): fr-FR's narrow no-break
# space, Arabic-Indic digits and separators (ar-EG), Bengali digits, a
# no-break space; ASCII digits untouched.
NNBSP, NBSP, ARSEP = chr(0x202F), chr(0x00A0), chr(0x066C)
arab = lambda s: "".join(chr(0x0660 + int(d)) for d in s)
beng = lambda s: "".join(chr(0x09E6 + int(d)) for d in s)
LOC = "EUR 12" + NNBSP + "345 / EGP " + arab("12") + ARSEP + arab("345") + " / BDT " + beng("6789") + " / 1" + NBSP + "000 / 0123456789"
got = jsc("%s\nprint(JSON.stringify(aiPlain(%s)));" % (js_fn("aiPlain"), json.dumps(LOC)))
results.append(ok(got == "EUR 12 345 / EGP 12,345 / BDT 6789 / 1 000 / 0123456789",
                  "aiPlain: a locale's amounts made ASCII: narrow and plain no-break spaces, Arabic-Indic and Bengali digits, the Arabic thousands mark (got %r)" % got))

# --- AI_SITES / aiLink -----------------------------------------------------------
LINK = js_const("AI_SITES") + "\n" + js_fn("aiLink")
prog = ("%s\nconst mk = (n) => 'a'.repeat(n);\nconst out = AI_SITES.map((s) => ({ name: s.name, cap: s.cap, q: s.q, home: s.home,"
        " at: aiLink(s, mk(s.cap)), over: aiLink(s, mk(s.cap + 1)),"
        " enc: aiLink(s, 'Japan — 10 days & more?').href }));\n"
        "const space = AI_SITES.map((s) => aiLink(s, ' '.repeat(Math.floor(s.cap / 3))).fits + '/' + aiLink(s, ' '.repeat(Math.floor(s.cap / 3) + 1)).fits);\n"
        "print(JSON.stringify({ out, space }));" % LINK)
got = jsc(prog) or {"out": [], "space": []}
caps = {s["name"]: s["cap"] for s in got["out"]}
results.append(ok(caps == {"ChatGPT": 30000, "Google AI Mode": 2200, "Claude": 4000, "Grok": 6000, "Perplexity": 12000},
                  "AI_SITES caps, in button order: ChatGPT 30000, Google AI Mode 2200, Claude 4000, Grok 6000, Perplexity 12000 (got %s)" % caps))
results.append(ok(list(caps) == ["ChatGPT", "Google AI Mode", "Claude", "Grok", "Perplexity"], "AI_SITES order: ChatGPT, Google AI Mode, Claude, Grok, Perplexity"))
results.append(ok(all(s["at"]["fits"] and s["at"]["href"] == s["q"] + "a" * s["cap"] for s in got["out"]) and got["out"],
                  "aiLink: an encoded prompt exactly at the cap is prefilled"))
results.append(ok(all(not s["over"]["fits"] and s["over"]["href"] == s["home"] for s in got["out"]) and got["out"],
                  "aiLink: one character over the cap opens the site's plain new chat"))
results.append(ok(all(s["home"].startswith("https://") and s["q"].startswith("https://") and s["q"].endswith("q=") for s in got["out"]),
                  "aiLink: every link and home page is https, every prefill link ends in q="))
results.append(ok(all(s["enc"] == s["q"] + urllib.parse.quote("Japan — 10 days & more?", safe="!'()*-._~") for s in got["out"]),
                  "aiLink: the prompt is encodeURIComponent'd (& ? and the em dash encoded)"))
results.append(ok(got["space"] and all(x == "true/false" for x in got["space"]),
                  "aiLink measures the ENCODED prompt: a space costs 3 (cap/3 spaces fit, one more doesn't) (got %s)" % got["space"]))

# --- AI_HINT_TIP ------------------------------------------------------------------
# Built from AI_SITES: each site's behaviour in button order, so a site added
# there (Gemini, once it has been tested signed in) is one line.
prog = ("%s\nconst before = %s\nAI_SITES.push({ name: 'Gemini', q: 'https://example.test/?q=', home: 'https://example.test/', cap: 1, how: 'does a test thing' });\n"
        "%s\nprint(JSON.stringify({ before, after: AI_HINT_TIP, how: AI_SITES.map((s) => s.name + ' ' + s.how) }));"
        % (js_const("AI_SITES"), js_const("AI_HINT_TIP").replace("const AI_HINT_TIP = ", "", 1), js_const("AI_HINT_TIP")))
got = jsc(prog) or {"before": "", "after": "", "how": []}
idx = [got["before"].find(h) for h in got["how"][:5]]
results.append(ok(got["how"] and all(i >= 0 for i in idx) and idx == sorted(idx) and "copied instead" in got["before"],
                  "AI_HINT_TIP names each site's behaviour in button order, then the copy-and-paste fallback (got %r)" % got["before"]))
results.append(ok("Gemini does a test thing." in got["after"] and got["after"].endswith("paste it into."),
                  "AI_HINT_TIP: a site added to AI_SITES is in the tip with no second edit (got %r)" % got["after"]))

# --- fareCurveFacts / monthKeyText -------------------------------------------------
FC = js_fn("fareCurveFacts") + "\n" + js_fn("monthKeyText")
KEYS = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
MONTHS_IN = {"2026-10": {"price": 838}, "2026-11": {"price": 879}, "2026-12": {"price": 913},
             "2027-01": {"price": 890}, "2027-02": {"price": 775}, "2027-06": {"price": 1253},
             "2027-03": {"price": 0}}
TIES = {"2026-10": {"price": 500}, "2026-12": {"price": 400}, "2027-01": {"price": 400}, "2027-02": {"price": 900},
        "2027-03": {"price": 900}}
prog = ("%s\n%s\nconst r = (f) => f && { n: f.n, cheap: f.cheap.map((x) => x.key + ' ' + x.price), dear: f.dear.key };\n"
        "print(JSON.stringify([r(fareCurveFacts(%s, %s)), r(fareCurveFacts(%s, %s)), fareCurveFacts({}, %s), fareCurveFacts(null, %s),"
        " monthKeyText('2027-04'), monthKeyText('2026-10', true)]));"
        % (BASE, FC, json.dumps(MONTHS_IN), json.dumps(KEYS), json.dumps(TIES), json.dumps(KEYS), json.dumps(KEYS), json.dumps(KEYS)))
got = jsc(prog) or [None] * 6
results.append(ok(got[0] == {"n": 5, "cheap": ["2027-02 775", "2026-10 838", "2026-11 879", "2027-01 890", "2026-12 913"], "dear": "2026-12"},
                  "fareCurveFacts over the window: June (outside it) and a zero fare don't count; cheapest Feb, priciest Dec (got %s)" % got[0]))
results.append(ok(got[1] == {"n": 5, "cheap": ["2026-12 400", "2027-01 400", "2026-10 500", "2027-02 900", "2027-03 900"], "dear": "2027-02"},
                  "fareCurveFacts ties keep the sooner month, cheapest and priciest alike (got %s)" % got[1]))
results.append(ok(got[2] is None and got[3] is None, "fareCurveFacts with no fares -> null"))
results.append(ok(got[4] == "Apr 2027" and got[5] == "October 2026", "monthKeyText: Apr 2027, October 2026 (got %s, %s)" % (got[4], got[5])))

# --- avoidAreas ---------------------------------------------------------------------
# Production's /api/watchouts replies of 2026-10-13 (regional lines only),
# the cases the review found: a band's states read as whole states (India),
# exceptions read as places to avoid (Karachi; Israel's excepted roads in
# place of Palestine), a generic heading standing for its list (Colombia).
WO = json.load(open(os.path.join(ROOT, "scripts", "watchouts_sample.2026-10-13.json"), encoding="utf-8"))
AV = "\n".join([js_const("AVOID_GENERIC"), js_fn("unshout"), js_fn("avoidLead"), js_fn("avoidText"), js_fn("avoidAreas")])
got = jsc("%s\nconst WO = %s;\nconst out = {};\nfor (const c in WO) out[c] = { guide: avoidAreas(WO[c], 0), trip: avoidAreas(WO[c], 10, true) };\n"
          "print(JSON.stringify(out));" % (AV, json.dumps(WO))) or {}
A, N = "Avoid all travel", "Avoid non-essential travel"
pairs = lambda r: [(x["call"], x["text"]) for x in r] if r is not None else None
g = lambda c, k: pairs((got.get(c) or {}).get(k))
want = {
    ("IN", "guide"): [(A, "the Union Territory of Jammu and Kashmir"),
                      (A, "areas within 10 km of the border with Pakistan in the following states: Gujarat; Punjab; Rajasthan"),
                      (N, "Manipur")],
    ("IN", "trip"): [(A, "Union Territory of Jammu and Kashmir"), (A, "Border areas with Pakistan"), (N, "Manipur")],
    ("PK", "guide"): [(A, "Pakistan-administered Kashmir; the province of Balochistan; the province of Khyber Pakhtunkhwa*; "
                          "the section of the Karakoram Highway from Mansehra to Chilas; and other areas Canada lists"),
                      (N, "the city of Karachi, except these areas: District of Karachi (formerly Karachi South); "
                          "DHA Phase 7 Extension in the District of Korangi; Lalazar, Naval Officers Residential Estate 1 and Port Tower "
                          "Complex in the District of Keamari; Jinnah International Airport and Shahrah-e-Faisal Road between the airport "
                          "and the city, in the District of Gulshan")],
    ("PK", "trip"): [(A, "Pakistan-administered Kashmir; the province of Balochistan; the province of Khyber Pakhtunkhwa*; "
                         "the section of the Karakoram Highway from Mansehra to Chilas; and other areas Canada lists"),
                     (N, "Karachi (parts excepted)")],
    ("IL", "guide"): [(A, "Palestine"), (A, "the parts of the Golan Heights that border Syria, east of Highway 98"), (N, "Israel"), (N, "Jerusalem")],
    ("IL", "trip"): [(A, "Palestine"), (A, "Border with Syria"), (N, "Israel"), (N, "Jerusalem")],
    ("EG", "guide"): [(A, "northern Sinai"),
                      (A, "The Western desert and Libyan border area: within 50 kilometres of the border with Libya; "
                          "the Western Desert, west of the Giza-Luxor-Aswan-Abu Simbel road, including the oasis of Dakhla"),
                      (N, "the northern part of the Governorate of South Sinai")],
    ("EG", "trip"): [(A, "Northern Sinai"), (A, "The Western desert and Libyan border area"), (N, "Northern part of the Governorate of South Sinai")],
    ("TR", "guide"): [(A, "within 10 km of the borders with Iraq and Syria"), (N, "Southeastern provinces: Hakkari; Sirnak")],
    ("TR", "trip"): [(A, "Borders with Iraq and Syria"), (N, "Hakkari; Sirnak")],
    ("MA", "guide"): [(A, "Western Sahara border regions: within 30 km west of the militarized zone of the Berm; "
                          "between the Berm and neighbouring countries on the eastern and southern sides"),
                      (A, "the area within 20 km of the border with Algeria"), (N, "Western Sahara")],
    ("MA", "trip"): [(A, "Western Sahara border regions"), (A, "Border with Algeria"), (N, "Western Sahara")],
    ("TH", "guide"): [(A, "Narathiwat; Pattani; Yala; southern Songkhla province")],
    ("TH", "trip"): [(A, "Narathiwat; Pattani; Yala; southern Songkhla province")],
    ("PH", "trip"): [(A, "Western Mindanao"), (N, "Central and Eastern Mindanao")],
}
labels = {
    "IN": "India: the 10 km band with Pakistan kept with its three states (not 'avoid all travel: Gujarat, Punjab, Rajasthan')",
    "PK": "Pakistan: Karachi's listed areas are its exceptions; the parser's 'the area*' leftovers are 'other areas Canada lists'",
    "IL": "Israel: Palestine, not the two roads Canada excepts from it; guide and trip agree; capitals unshouted",
    "EG": "Egypt: northern Sinai from Canada's sentence, a sentence cut at 'north of St.' backed off to its last comma",
    "TR": "Turkey: the 10 km band from the sentence; the trip's places where shorter than the heading",
    "MA": "Morocco: a named heading leads its places; the band's distance from the sentence",
    "TH": "Thailand: a heading that names every place gives way to the places",
    "PH": "the Philippines: the trip's named headings",
}
for (c, k), w in want.items():
    results.append(ok(g(c, k) == w, "avoidAreas %s, %s: %s (got %s)" % (c, k, labels[c], g(c, k))))
co_g, co_t = g("CO", "guide") or [], g("CO", "trip") or []
co_all = WO["CO"]["regional"][0]["regions"]
results.append(ok(len(co_g) == 2 and co_g[0][0] == A and all(r in co_g[0][1] for r in co_all)
                  and "Cesar, in the municipalities of González and Río de Oro; Chocó*" in co_g[0][1],
                  "avoidAreas Colombia, guide: every department and band listed, joined with '; ' (a name's own comma stays inside it) (got %s)" % co_g[:1]))
results.append(ok(co_g and "Valle del Cauca*; and other areas Canada lists" in co_g[1][1],
                  "avoidAreas Colombia, guide: no cap (Valle del Cauca, Cali's department, is named) and the nested 'the following towns in Chocó' is 'other areas'"))
results.append(ok(len(co_t) == 2 and not any(t == "Border areas" for _, t in co_t) and "Buenaventura" in co_t[0][1]
                  and co_t[1][1].endswith("; Meta*; and 4 more"),
                  "avoidAreas Colombia, trip: a generic 'Border areas' heading never stands for its list; past 10 places 'and N more' (got %s)" % co_t))
ec = g("EC", "guide") or []
results.append(ok(len(ec) == 3 and ec[0][1].startswith("the area within 20 km of the border with Colombia in the following provinces: Carchi (except for")
                  and ec[2][1].startswith("the following areas (except within 20 km of the border with Colombia where we advise against all travel): the province of Esmeraldas;"),
                  "avoidAreas Ecuador: an 'except' inside the sentence (not 'the following') leaves the places as the area (got %s)" % ec))
MIX = {"regional": [{"t": "Regional Advisory - Avoid non-essential travel", "lead": "Avoid non-essential travel to the states below. Details.", "regions": []},
                    {"t": "Island of Providencia - Take normal security precautions", "lead": "Take normal security precautions.", "regions": []},
                    {"t": "Mindanao - AVOID ALL TRAVEL", "lead": "Avoid all travel to the following provinces: A B", "regions": list("ABCDEFGH")},
                    {"t": "Somewhere - Avoid all travel", "lead": "Avoid all travel to " + "x" * 190 + ", near y", "regions": []},
                    {"t": "Regional advisory - Avoid all travel", "lead": "The situation is volatile. More.", "regions": []},
                    {"t": "Border areas - Avoid all travel", "lead": "Avoid all travel to " + "z" * 200, "regions": []},
                    {"t": "Somewhere else - Avoid all travel", "lead": "Avoid all travel to " + "w" * 200, "regions": []}]}
got = jsc("%s\nprint(JSON.stringify([avoidAreas(%s, 6), avoidAreas(%s, 6, true), avoidAreas(null, 6), avoidAreas({ regional: [] }, 6)]));"
          % (AV, json.dumps(MIX), json.dumps(MIX))) or [None] * 4
results.append(ok(pairs(got[0]) == [(A, "Mindanao: A; B; C; D; E; F; and 2 more"), (A, "x" * 190), (A, "The situation is volatile"),
                                    (A, "z" * 200 + "..."), (A, "Somewhere else"), (N, "areas Canada lists")],
                  "avoidAreas: all-travel first, an upper-case call read, past max 'and N more', a sentence cut off at 200 backed off to its "
                  "last comma (with none, '...', or a named heading), an unreadable one's first sentence, a list that never came said so, "
                  "a safer-than-the-rest line left out (got %s)" % got[0]))
results.append(ok(pairs(got[1]) == [(A, "Mindanao"), (A, "Somewhere"), (A, "The situation is volatile"), (A, "z" * 200 + "..."),
                                    (A, "Somewhere else"), (N, "areas Canada lists")],
                  "avoidAreas brief: a named heading alone, a generic one never (got %s)" % got[1]))
results.append(ok(got[2] == [] and got[3] == [], "avoidAreas with no watchouts or no regional lines -> []"))

# --- aiTripFlights --------------------------------------------------------------------
# The clock and formatting stubbed: Oct 2026, fares in USD as "USD n".
STUBS = ("const nextMonthKey = (m) => (m >= 10 ? 2026 : 2027) + '-' + String(m).padStart(2, '0');\n"
         "const flightMonthKey = nextMonthKey;\nconst fareYearKeys = () => MON_ABBR.map((x, i) => nextMonthKey(i + 1));\n"
         "const fmtBC = (usd) => 'USD ' + Math.round(usd).toLocaleString('en-US');\nconst originIso = () => 'US';\n"
         "let flightsData = { configured: true, by_country: { KH: 1060, XX: 640 } };\n")
TH_FM = {"months": {"2026-10": {"price": 838}, "2026-11": {"price": 879}, "2026-12": {"price": 913}, "2027-01": {"price": 890},
                    "2027-02": {"price": 775}, "2027-03": {"price": 841}, "2027-04": {"price": 832}, "2027-06": {"price": 1253}}}
PT_FM = {"months": {"2026-11": {"price": 65}, "2026-12": {"price": 80}, "2027-01": {"price": 70}, "2027-03": {"price": 90},
                    "2027-05": {"price": 120}, "2027-07": {"price": 197}}}
KH_FM = {"months": {"2026-12": {"price": 1060}}}
NL_FM = {"months": {"2026-10": {"price": 165}, "2026-11": {"price": 165}, "2027-01": {"price": 233}, "2027-09": {"price": 183}}}
prog = ("%s\n%s\n%s\n%s\nconst _aiFares = { 'US:TH': %s, 'US:PT': %s, 'US:KH': %s, 'US:NL': %s, 'US:HR': null };\n"
        "print(JSON.stringify([aiTripFlights('TH', 10), aiTripFlights('PT', 11), aiTripFlights('PT', 9), aiTripFlights('TH', null),"
        " aiTripFlights('TH', null, [10, 11, 12, 1, 2, 3]), aiTripFlights('KH', null), aiTripFlights('KH', 11), aiTripFlights('XX', 11),"
        " aiTripFlights('HR', null), aiTripFlights('NL', 2), aiTripFlights('NL', null), (flightsData = null, aiTripFlights('HR', null))]));"
        % (BASE, STUBS, js_fn("fareCurveFacts"), js_fn("monthKeyText") + "\n" + js_fn("aiTripFlights"),
           json.dumps(TH_FM), json.dumps(PT_FM), json.dumps(KH_FM), json.dumps(NL_FM)))
got = jsc(prog) or [None] * 12
want = ["flights Oct USD 838 (cheapest Feb 2027 USD 775, priciest Jun 2027 USD 1,253)",
        "flights Nov USD 65 (its cheapest month; priciest Jul 2027 USD 197)",
        "flights: no Sep fare cached (cheapest Nov 2026 USD 65, priciest Jul 2027 USD 197)",
        "flights cheapest Feb 2027 USD 775, priciest Jun 2027 USD 1,253",
        "flights in my window: cheapest Feb 2027 USD 775, priciest Dec 2026 USD 913",
        "flights: only Dec 2026 USD 1,060 cached",
        "flights: no Nov fare cached (only Dec 2026 USD 1,060)",
        "flights avg USD 640",
        "flights: none cached",
        "flights: no Feb fare cached (only Oct 2026 USD 165, Nov 2026 USD 165, Jan 2027 USD 233, Sep 2027 USD 183)",
        "flights: only Oct 2026 USD 165, Nov 2026 USD 165, Jan 2027 USD 233, Sep 2027 USD 183 cached", ""]
labels = ["a fixed month with a strip: its fare, the year's cheapest and priciest",
          "the trip month is the cheapest: said so",
          "no fare in the trip month: the strip's cheapest and priciest",
          "flexible, no window: the year's cheapest and priciest",
          "flexible over a window: the window's cheapest and priciest, said so",
          "flexible, a one-month route: the month it has",
          "a fixed month a sparse route lacks: the months it has",
          "no month curve: the cached average, said so",
          "nothing cached on a configured server: said so",
          "a four-month route, a month it lacks: every month it has, in order (not 'only' three of them)",
          "a four-month route, flexible: every month it has",
          "no fares on the server: nothing"]
for g, w, l in zip(got, want, labels):
    results.append(ok(g == w, "aiTripFlights, %s: %r" % (l, g)))

# --- aiFx ---------------------------------------------------------------------------
# The guide's verdict rule: none without the destination's inflation figure
# (adj false: the Faroes' "exchange rate only"), none inside ±2%; the guide
# prompt quotes the guide line's own figure (/api/fx-trend) once it has come.
FX = ("let F = null; const fxInfo = () => F; const GUIDE_PARENT = {}; let homeBase = 'USD'; const _fxTrendSeen = {};\n"
      "const realFxPct = (iso, nom) => Math.round((nom - 0.3) * 100) / 100;\n" + js_fn("aiFx"))
prog = ("%s\nconst out = [];\nconst at = (f, short) => { F = f; out.push(aiFx('XX', short)); };\n"
        "at({ code: 'DKK', real: 3.6, adj: false }); at({ code: 'EUR', real: 3.6, adj: true }); at({ code: 'EUR', real: 3.6, adj: true }, true);\n"
        "at({ code: 'EUR', real: 1.94, adj: true }); at({ code: 'TRY', real: -4.44, adj: true }); at(null);\n"
        "_fxTrendSeen['USD:EUR'] = { pct: 2.4 }; at({ code: 'EUR', real: 1.9, adj: true }); at({ code: 'EUR', real: 3.6, adj: true }, true);\n"
        "print(JSON.stringify(out));" % FX)
got = jsc(prog) or [None] * 8
want = ["", "my USD goes 3.6% further than usual there (vs its 12-month average, after inflation)", "money goes 3.6% further than usual",
        "", "my USD goes 4.4% less far than usual there (vs its 12-month average, after inflation)", "",
        "my USD goes 2.1% further than usual there (vs its 12-month average, after inflation)", "money goes 3.6% further than usual"]
labels = ["no inflation figure for the destination: no verdict", "after inflation, past 2%", "the trip's short form",
          "inside 2%: unsaid", "a weaker rate, one decimal", "no rates: nothing",
          "the guide line's own figure (fx-trend) over the rates table's: India's 1.9 vs the line's 2.1",
          "the trip's short form reads the table, not the guide's line"]
for g_, w, l in zip(got, want, labels):
    results.append(ok(g_ == w, "aiFx, %s: %r" % (l, g_)))

# --- aiLevelText ----------------------------------------------------------------------
LV = ("let SRC = 'de'; const advSrcOf = (it) => it.via || SRC; const advLevelText = (iso, l) => iso + ' Level ' + l;\n"
      + js_const("DE_LVL_PROMPT") + "\n" + js_fn("aiLevelText"))
got = jsc("%s\nconst o = (it) => aiLevelText({ it, of: 'TH' });\nconst out = [o({ level: 2 }), o({ level: 1 }), o({ level: 4 }), o({ level: 3 }), o({ level: 2, via: 'us' })];\n"
          "SRC = 'us'; out.push(o({ level: 2 }));\nprint(JSON.stringify(out));" % LV)
results.append(ok(got == ["partial travel warning for some regions", "no travel warning", "travel warning", "TH Level 3", "TH Level 2", "TH Level 2"],
                  "aiLevelText: Germany's own levels said as what they are, not its quoted label; a gap another government filled, and the US, in their words (got %s)" % got))

# --- aiGuideFlights -------------------------------------------------------------------
# The month curve (3+ months, the chart's floor) with the band and range; one
# or two cached months quoted as they are (Palau's one January fare used to
# read as "the average across all months"); the average and the distance
# estimate as the fallback, named. curve: whether the "is October right" ask fits.
GF = (STUBS + js_const("HUB_CITY") + "\n" + js_const("aiRange") + "\n"
      "const fareValue = () => ({ c: { median: 1000, lo: 957, hi: 1160 } }); const flightValue = { origin: 'US' };\n"
      "flightsData = { configured: true, hub: 'NYC' };\nconst buildFareContext = () => ({ prices: { XX: 640, YY: 900 }, est: new Set(['YY']) });\n"
      "const countryNameInText = (iso) => 'the ' + iso;\n" + js_fn("fareCurveFacts") + "\n" + js_fn("monthKeyText") + "\n" + js_fn("aiGuideFlights"))
JP_FM = {"hub": "NYC", "months": {"2026-10": {"price": 966}, "2026-11": {"price": 864}, "2027-04": {"price": 812}, "2027-05": {"price": 1288}}}
PW_FM = {"hub": "NYC", "months": {"2027-01": {"price": 2089}}}
got = jsc("%s\n%s\nconst _aiFares = { 'US:JP': %s, 'US:PW': %s };\nprint(JSON.stringify([aiGuideFlights('JP', 10), aiGuideFlights('PW', 10), aiGuideFlights('XX', 10), aiGuideFlights('YY', 10), aiGuideFlights('ZZ', 10)]));"
          % (BASE, GF, json.dumps(JP_FM), json.dumps(PW_FM))) or [None] * 5
want = [{"curve": True, "text": "FLIGHTS from New York (cheapest cached round trip per departure month, not live quotes): October USD 966, typical for this route "
                                "(usual USD 957-1,160). Cheapest: Apr 2027 USD 812, Nov 2026 USD 864. Priciest: May 2027 USD 1,288."},
        {"curve": False, "text": "FLIGHTS from New York (cheapest cached round trip, not live quotes): only Jan 2027 USD 2,089 cached."},
        {"curve": False, "text": "FLIGHTS from New York: about USD 640 round trip, the average of its cached fares (none by month)."},
        {"curve": False, "text": "FLIGHTS from New York: about USD 900 round trip, a distance-based estimate (no cached fares to the YY)."},
        {"curve": False, "text": ""}]
labels = ["a month curve: the month's fare, band and range, the cheapest two and the priciest",
          "one cached month: quoted as it is, no curve to ask about", "no month curve: the average, named",
          "no cached fare: the distance estimate, named", "nothing at all: no line"]
for g_, w, l in zip(got, want, labels):
    results.append(ok(g_ == w, "aiGuideFlights, %s: %s" % (l, g_)))

# --- aiEntryAsk ---------------------------------------------------------------------
prog = ("%s\n%s\nlet PP = 'US'; const guidePassport = () => PP;\nconst out = [];\n"
        "for (const [pp, isos] of [['US', ['PT', 'MA']], ['GB', ['ES']], ['DE', ['PT']], ['IE', ['ES']], ['US', ['JP']], ['CH', ['FR']]])"
        " { PP = pp; out.push(/Schengen/.test(aiEntryAsk(isos))); }\nprint(JSON.stringify(out));" % (js_const("SCHENGEN"), js_fn("aiEntryAsk")))
got = jsc(prog)
results.append(ok(got == [True, True, False, False, False, False],
                  "aiEntryAsk: the Schengen 90/180 ask for US and UK passports in Schengen, not for German, Irish or Swiss ones, nor outside it (got %s)" % got))

# --- tripMonth ----------------------------------------------------------------------
# Unset under Top Picks' "Any time" is flexible over its window (it used to be
# the window's first month: "14 days in October"); "I'm flexible" picked is
# flexible over the year; a month is itself; unset in month mode follows Top
# Picks' month. The select's value is what the reader sees (renderTripBar
# selects "I'm flexible" for unset under Any time).
TM = js_fn("tripMonth") + "\n" + js_fn("tripMonthSaved")
prog = ("%s\nlet SEL = null, SAVED = null, FLEX = false; const $ = () => SEL;\nconst localStorage = { getItem: () => SAVED };\n"
        "let sharedTripView = null; const picksFlex = () => FLEX; const flexWindow = () => [10, 11, 12, 1, 2, 3]; const picksMonth = () => 10;\n"
        "const out = [];\nfor (const [sel, saved, flex] of [[null, null, true], ['0', null, true], ['0', '0', true], [null, '0', true], ['11', '11', true],"
        " [null, null, false], ['10', null, false], [null, '3', false]]) { SEL = sel === null ? null : { value: sel }; SAVED = saved; FLEX = flex; out.push(tripMonth()); }\n"
        "sharedTripView = { tm: '0' }; SEL = null; SAVED = null; FLEX = true; out.push(tripMonth());\nprint(JSON.stringify(out));" % TM)
got = jsc(prog) or [None] * 9
W6 = [10, 11, 12, 1, 2, 3]
want = [{"month": None, "flexible": True, "window": W6}, {"month": None, "flexible": True, "window": W6},
        {"month": None, "flexible": True, "window": None}, {"month": None, "flexible": True, "window": None},
        {"month": 11, "flexible": False}, {"month": 10, "flexible": False}, {"month": 10, "flexible": False},
        {"month": 3, "flexible": False}, {"month": None, "flexible": True, "window": None}]
labels = ["unset, Any time, no select -> flexible over the window",
          "unset, Any time, the select showing I'm flexible -> flexible over the window",
          "I'm flexible picked, Any time -> flexible over the year",
          "I'm flexible saved, no select -> flexible over the year",
          "November picked, Any time -> November",
          "unset, month mode -> Top Picks' month",
          "unset, month mode, the select on October -> October",
          "March saved, no select -> March",
          "a shared trip's I'm flexible -> flexible over the year"]
for g, w, l in zip(got, want, labels):
    results.append(ok(g == w, "tripMonth, %s (got %s)" % (l, g)))

# --- todayText ------------------------------------------------------------------------
got = jsc("%s\n%s\nprint(JSON.stringify([todayText(new Date(2026, 9, 13)), todayText(new Date(2027, 0, 5))]));" % (BASE, js_fn("todayText")))
results.append(ok(got == ["13 Oct 2026", "5 Jan 2027"], "todayText: 13 Oct 2026, 5 Jan 2027 (got %s)" % got))

# --- the sentence's own exception and run-together list (2026-10-14) ------------
# Checked against travel.gc.ca on 2026-10-14 (67 countries): Jordan's
# exception sits inside the first sentence ("…with the exception of the
# tourist site Umm Qais, due to…") and was dropped; Tunisia's lists come only
# run together after the sentence's colon, and both lines read "areas Canada
# lists". Production's replies for the two, scripts/watchouts_sample.2026-10-14.json.
WO2 = json.load(open(os.path.join(ROOT, "scripts", "watchouts_sample.2026-10-14.json"), encoding="utf-8"))
got = jsc("%s\nconst WO = %s;\nconst out = {};\nfor (const c in WO) out[c] = avoidAreas(WO[c], 10).map((x) => x.call + ': ' + x.text);\n"
          "print(JSON.stringify(out));" % (AV, json.dumps(WO2))) or {}
results.append(ok("Avoid all travel: within 5 km of the borders with Iraq and Syria (except the tourist site Umm Qais)" in (got.get("JO") or []),
                  "Jordan keeps the exception inside its sentence: Umm Qais (got %s)" % got.get("JO")))
results.append(ok("Avoid all travel: the area within 20 km of the Algerian border; and other areas Canada lists" in (got.get("TN") or []),
                  "Tunisia's avoid-all line names the 20 km Algerian border zone from the run-together list (got %s)" % got.get("TN")))
results.append(ok("Avoid non-essential travel: the Delegation of Remada Mount Orbata" in (got.get("TN") or []),
                  "Tunisia's non-essential line names Remada and Mount Orbata, not 'areas Canada lists'"))

# --- the guide's 📍 lines use the same reader ------------------------------------
# watchoutsBlockHTML listed a line's regions bare under its call: Israel's
# guide said "AVOID ALL TRAVEL: Highway 1, Route 90 …", the roads Canada
# EXCEPTS from Palestine; Pakistan listed Karachi's excepted districts as
# places to avoid. It now reads avoid lines through avoidText; others keep
# their form.
WB = AV + "\n" + js_fn("watchoutsBlockHTML") + "\nfunction esc(s){return String(s==null?'':s);}\n"
got = jsc("%s\nconst WO = %s;\nconst out = {};\nfor (const c of ['IL','PK','IN','TH']) out[c] = watchoutsBlockHTML({ watchouts: [], regional: WO[c].regional }).reg.replace(/<[^>]+>/g, '|');\n"
          "print(JSON.stringify(out));" % (WB, json.dumps(WO))) or {}
il, pk, inn = got.get("IL", ""), got.get("PK", ""), got.get("IN", "")
results.append(ok("Avoid all travel|: Palestine" in il and "Highway 1" not in il, "guide line, Israel: 'Avoid all travel: Palestine', not the excepted roads (got %s)" % il[:200]))
results.append(ok("the city of Karachi, except these areas:" in pk, "guide line, Pakistan: Karachi's districts read as exceptions"))
results.append(ok("within 10 km of the border with Pakistan" in inn, "guide line, India: the 10 km band, not whole states"))
results.append(ok("Narathiwat; Pattani; Yala" in got.get("TH", ""), "guide line, Thailand: its provinces, '; '-joined"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
