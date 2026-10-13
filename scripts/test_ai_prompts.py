"""The AI prompts' pure pieces (the Travel Guide's "Plan X with AI" and the
Trip tab's "Plan this trip with AI"), cut out of public/app.js by name and
run under jsc.

  aiPlain        the site's typography made ASCII for a link: · — – − ≈ °
                 … → and curly quotes, each 6-9 characters once encoded;
                 names keep their letters
  AI_SITES /     each site's cap on the encoded prompt (ChatGPT 30000,
  aiLink         Claude 4000, Grok 6000, Perplexity 12000): within it the
                 prefill link, past it the site's plain new chat
  fareCurveFacts a route's month fares as the prompts quote them: count,
                 cheapest first (ties keep the sooner month), the priciest
  monthKeyText   "2027-04" -> "Apr 2027" / "April 2027"
  avoidAreas     Canada's avoid-travel lines grouped by call, all-travel
                 first; places, else the heading, else the first sentence;
                 brief keeps the shorter of heading and places
  aiTripFlights  one trip row's fares: the month's own, the strip's cheapest
                 and priciest, the window's in flexible mode, a sparse route's
                 months, the average fallback
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
names = ["aiPlain", "aiLink", "fareCurveFacts", "monthKeyText", "avoidAreas", "aiTripFlights", "aiEntryAsk",
         "tripMonth", "tripMonthSaved", "todayText"]
results.append(ok(all(js_fn(n) for n in names) and js_const("AI_SITES") and js_const("SCHENGEN"),
                  "the prompts' pieces found in app.js: " + ", ".join(names) + ", AI_SITES, SCHENGEN"))

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

# --- AI_SITES / aiLink -----------------------------------------------------------
LINK = js_const("AI_SITES") + "\n" + js_fn("aiLink")
prog = ("%s\nconst mk = (n) => 'a'.repeat(n);\nconst out = AI_SITES.map((s) => ({ name: s.name, cap: s.cap, q: s.q, home: s.home,"
        " at: aiLink(s, mk(s.cap)), over: aiLink(s, mk(s.cap + 1)),"
        " enc: aiLink(s, 'Japan — 10 days & more?').href }));\n"
        "const space = AI_SITES.map((s) => aiLink(s, ' '.repeat(Math.floor(s.cap / 3))).fits + '/' + aiLink(s, ' '.repeat(Math.floor(s.cap / 3) + 1)).fits);\n"
        "print(JSON.stringify({ out, space }));" % LINK)
got = jsc(prog) or {"out": [], "space": []}
caps = {s["name"]: s["cap"] for s in got["out"]}
results.append(ok(caps == {"ChatGPT": 30000, "Claude": 4000, "Grok": 6000, "Perplexity": 12000},
                  "AI_SITES caps, in button order: ChatGPT 30000, Claude 4000, Grok 6000, Perplexity 12000 (got %s)" % caps))
results.append(ok(list(caps) == ["ChatGPT", "Claude", "Grok", "Perplexity"], "AI_SITES order: ChatGPT, Claude, Grok, Perplexity"))
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
TH = {"regional": [{"t": "Southern provinces of Narathiwat, Pattani, Yala and southern Songkhla province - Avoid all travel",
                    "regions": ["Narathiwat", "Pattani", "Yala", "southern Songkhla province"]}]}
MA = {"regional": [{"t": "Western Sahara border regions - Avoid all travel",
                    "regions": ["within 30 km west of the militarized zone of the Berm",
                                "between the Berm and neighbouring countries on the eastern and southern sides"]},
                   {"t": "Border with Algeria - Avoid all travel", "lead": "Avoid all travel to the area within 20 km. More.", "regions": []},
                   {"t": "Western Sahara - Avoid non-essential travel", "regions": []}]}
MIX = {"regional": [{"t": "Regional Advisory - Avoid non-essential travel", "lead": "Avoid non-essential travel to the states below. Details.",
                     "regions": []},
                    {"t": "Island of Providencia - Take normal security precautions", "regions": []},
                    {"t": "PALESTINE - AVOID ALL TRAVEL", "regions": ["Gaza*", "West Bank"]},
                    {"t": "Mindanao - Avoid all travel", "regions": ["A", "B", "C", "D", "E", "F", "G", "H"]}]}
prog = ("%s\nprint(JSON.stringify([avoidAreas(%s, 12), avoidAreas(%s, 12), avoidAreas(%s, 6, true), avoidAreas(%s, 6), avoidAreas(null, 6), avoidAreas({ regional: [] }, 6)]));"
        % (js_fn("avoidAreas"), json.dumps(TH), json.dumps(MA), json.dumps(MA), json.dumps(MIX)))
got = jsc(prog) or [None] * 6
results.append(ok(got[0] == [{"call": "Avoid all travel", "names": ["Narathiwat", "Pattani", "Yala", "southern Songkhla province"]}],
                  "avoidAreas Thailand: the four places, as the guide's 📍 line lists them (got %s)" % got[0]))
results.append(ok(got[1] == [{"call": "Avoid all travel", "names": ["within 30 km west of the militarized zone of the Berm",
                                                                       "between the Berm and neighbouring countries on the eastern and southern sides",
                                                                       "Border with Algeria"]},
                             {"call": "Avoid non-essential travel", "names": ["Western Sahara"]}],
                  "avoidAreas Morocco: places, else the line's heading; grouped by call (got %s)" % got[1]))
results.append(ok(got[2] == [{"call": "Avoid all travel", "names": ["Western Sahara border regions", "Border with Algeria"]},
                             {"call": "Avoid non-essential travel", "names": ["Western Sahara"]}],
                  "avoidAreas brief (the trip): the heading where it is shorter than the places (got %s)" % got[2]))
results.append(ok(got[3] == [{"call": "Avoid all travel", "names": ["Gaza (parts excepted)", "West Bank", "A", "B", "C", "D", "and 4 more"]},
                             {"call": "Avoid non-essential travel", "names": ["Avoid non-essential travel to the states below"]}],
                  "avoidAreas: all-travel first, an upper-case call read, a star said, past max 'and N more', "
                  "a 'Regional advisory' heading replaced by its first sentence, a safer-than-the-rest line left out (got %s)" % got[3]))
results.append(ok(got[4] == [] and got[5] == [], "avoidAreas with no watchouts or no regional lines -> []"))

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
prog = ("%s\n%s\n%s\n%s\nconst _aiFares = { 'US:TH': %s, 'US:PT': %s, 'US:KH': %s, 'US:HR': null };\n"
        "print(JSON.stringify([aiTripFlights('TH', 10), aiTripFlights('PT', 11), aiTripFlights('PT', 9), aiTripFlights('TH', null),"
        " aiTripFlights('TH', null, [10, 11, 12, 1, 2, 3]), aiTripFlights('KH', null), aiTripFlights('KH', 11), aiTripFlights('XX', 11),"
        " aiTripFlights('HR', null), (flightsData = null, aiTripFlights('HR', null))]));"
        % (BASE, STUBS, js_fn("fareCurveFacts"), js_fn("monthKeyText") + "\n" + js_fn("aiTripFlights"),
           json.dumps(TH_FM), json.dumps(PT_FM), json.dumps(KH_FM)))
got = jsc(prog) or [None] * 10
want = ["flights Oct USD 838 (cheapest Feb 2027 USD 775, priciest Jun 2027 USD 1,253)",
        "flights Nov USD 65 (its cheapest month; priciest Jul 2027 USD 197)",
        "flights: no Sep fare cached (cheapest Nov 2026 USD 65, priciest Jul 2027 USD 197)",
        "flights cheapest Feb 2027 USD 775, priciest Jun 2027 USD 1,253",
        "flights in my window: cheapest Feb 2027 USD 775, priciest Dec 2026 USD 913",
        "flights: only Dec 2026 USD 1,060 cached",
        "flights: no Nov fare cached (only Dec 2026 USD 1,060)",
        "flights avg USD 640 (all months)",
        "flights: none cached", ""]
labels = ["a fixed month with a strip: its fare, the year's cheapest and priciest",
          "the trip month is the cheapest: said so",
          "no fare in the trip month: the strip's cheapest and priciest",
          "flexible, no window: the year's cheapest and priciest",
          "flexible over a window: the window's cheapest and priciest, said so",
          "flexible, a one-month route: the month it has",
          "a fixed month a sparse route lacks: the months it has",
          "no month curve: the cached average, said so",
          "nothing cached on a configured server: said so",
          "no fares on the server: nothing"]
for g, w, l in zip(got, want, labels):
    results.append(ok(g == w, "aiTripFlights, %s: %r" % (l, g)))

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

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
