"""A government's words quoted up to a sentence's end are never cut inside an
abbreviation: the Safety tab's "<Country> what each government says" card
(the State Department's summary) and the chips' tips under 🧭 Safety notes
(Canada's first sentence of each topic).

    /usr/bin/python3 scripts/test_gov_trim.py

No network. fxtracker/advisories.py caps a summary at 280 characters; one it
cuts at a word ends in "…", and public/app.js renderGov trims that back to
its last full sentence (sentenceEnds). It used to trim at the last ". ", so
"U.S. citizens" read as a sentence end: Ukraine's quote stopped at
"…consular assistance to U.S.", the DRC's at "…Title 49 of the U.S.", the
UAE's at "…armed conflict. U.S.". app.js itself runs under jsc
(scripts/appjs_harness.js); the US items come from the recorded feed
(scripts/advisories_sample.us-2026-11-25.xml) through the server's own
parser, as the card gets them from /api/advisories. What it holds the code to:
  * Ukraine, the DRC and the UAE read their first sentence, whole, with the
    US's, Canada's or Germany's list picked as the reader's own;
  * every recorded summary: one without "…" is quoted as it is; one with
    "…" ends on a real sentence end (no abbreviation's stop) or keeps its "…";
  * the edge cases: no "…", a short summary, "…" right after "U.S.", a
    sentence that genuinely ends in "U.S." (not cut there: it reads like
    "the U.S. Embassy", and a longer quote beats a wrong cut), no sentence
    end at all, "..." for "…", the 40-character floor, "?"/"!" and quotes;
  * sentenceEnds on each abbreviation it knows (U.S., U.K., U.A.E., D.C.,
    D.R., e.g., i.e., a.m., p.m., initials, St., Mt., No., Dr., Mr., Mrs.,
    months), and "40°C." still ending a sentence;
  * Canada's chips: fxtracker/watchouts.py _first_sentence (a chip's tip, on
    the guide's 🧭 Safety notes and the Safety table's notes row) split at
    every stop, so the U.S. Virgin Islands' "Earthquakes and tsunamis" tip
    read "The U.S." and St. Vincent's "Volcano" one "…on the island of St.".
    It now reads the paragraph with watchouts._sentences, as the regional
    lines do. Each topic's paragraph below is Global Affairs Canada's own
    (data.international.gc.ca, recorded 2026-11-26), with what main 1a1d75b
    quoted and what it must quote. The regional lines don't change (the
    avoid-zone tests hold them).
"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories as A, watchouts as W  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()

# The recorded State Department feed, parsed by the server's own code.
RAW = open(P("scripts", "advisories_sample.us-2026-11-25.xml"), encoding="utf-8").read()
A._fetch_text = lambda url, retries=3: RAW
US = A._us_advisories()
SUM = {it["iso"]: it["summary"] for it in US["items"] if it.get("iso") and it.get("summary")}

# What the card quoted on main 1a1d75b (2026-11-26), and what it must quote.
REAL = {
    "UA": ("Do not travel to Ukraine for any reason due to the Russia-Ukraine war. The Embassy is open and operating "
           "in Kyiv; however, Embassy personnel are subject to movement, curfew, and activity restrictions, which may "
           "cause delays in provision of consular assistance to U.S.",
           "Do not travel to Ukraine for any reason due to the Russia-Ukraine war."),
    "CD": ("Do not travel to the Democratic Republic of the Congo (DRC) due to health, crime, unrest, terrorism, and "
           "kidnapping. Due to the Ebola outbreak in the DRC, the Department of Homeland Security has implemented new "
           "restrictions under Title 49 of the U.S.",
           "Do not travel to the Democratic Republic of the Congo (DRC) due to health, crime, unrest, terrorism, and "
           "kidnapping."),
    "AE": ("Reconsider travel to the United Arab Emirates due to terrorism and armed conflict. U.S.",
           "Reconsider travel to the United Arab Emirates due to terrorism and armed conflict."),
}

# Made-up summaries for the edge cases: (what, summary, the quote it must give).
FIRST = "Exercise increased caution in Fooland due to crime and unrest."      # 62 characters
EDGE = [
    ("no \"…\": quoted whole, \"U.S.\" and all",
     FIRST + " U.S. citizens should carry a copy of their passport.",
     FIRST + " U.S. citizens should carry a copy of their passport."),
    ("a short summary: no sentence end past 40 characters, so it keeps its \"…\"",
     "Do not travel. The border is closed to…", "Do not travel. The border is closed to…"),
    ("\"…\" right after \"U.S.\"",
     FIRST + " Embassy staff need permission to leave the capital, which limits the help it can give to U.S.…",
     FIRST),
    ("a sentence that genuinely ends in \"U.S.\" is not cut there (it reads like \"the U.S. Embassy\")",
     FIRST + " Some visitors had trouble getting visas in the U.S. The Embassy can only offer limited help to…",
     FIRST),
    ("no real sentence end at all: the whole summary with its \"…\"",
     "Do not travel to Fooland due to terrorism, kidnapping, armed conflict, and the limited ability of the U.S. "
     "government to provide emergency services to U.S. citizens in the north of…",
     "Do not travel to Fooland due to terrorism, kidnapping, armed conflict, and the limited ability of the U.S. "
     "government to provide emergency services to U.S. citizens in the north of…"),
    ("\"...\" in place of \"…\"", FIRST + " Curfews apply in the north and the U.S. Embassy...", FIRST),
    ("the old 40-character floor: a 41-character first sentence is no place to stop",
     "Do not travel to Fooland due to the wars. Embassy staff cannot travel outside the capital without…",
     "Do not travel to Fooland due to the wars. Embassy staff cannot travel outside the capital without…"),
    ("…a 42-character one is",
     "Do not travel to Foo-land due to the wars. Embassy staff cannot travel outside the capital without…",
     "Do not travel to Foo-land due to the wars."),
    ("other abbreviations: St., Mt., D.R., a.m./p.m., e.g., No.",
     FIRST + " Avoid St. Mary Parish and Mt. Hagen. Flights to the D.R. Congo leave at 6:00 a.m. Some routes, e.g. "
     "Route No. 5 near the U.A.E. Embassy, close at 9 p.m. Others close at…",
     FIRST + " Avoid St. Mary Parish and Mt. Hagen."),
    ("a question mark, and a full stop inside quotes",
     "Why reconsider travel to Fooland at all? Officials said \"leave the north now.\" The Embassy in the north is…",
     "Why reconsider travel to Fooland at all? Officials said \"leave the north now.\""),
]

# sentenceEnds: (text, the sentences it must find). None of the stops inside
# an abbreviation ends one.
ENDS = [
    ("Help for U.S. citizens is limited. U.K. nationals should call the U.K. Embassy. The U.A.E. Embassy is open.",
     ["Help for U.S. citizens is limited.", "U.K. nationals should call the U.K. Embassy.", "The U.A.E. Embassy is open."]),
    ("Flights leave Washington, D.C. Tuesdays. They stop in the D.R. Congo.",
     ["Flights leave Washington, D.C. Tuesdays.", "They stop in the D.R. Congo."]),
    ("Carry ID, e.g. A passport, i.e. The original. Fine.", ["Carry ID, e.g. A passport, i.e. The original.", "Fine."]),
    ("Curfew is 6:00 p.m. To 6:00 a.m. Daily. Stay in.", ["Curfew is 6:00 p.m. To 6:00 a.m. Daily.", "Stay in."]),
    ("Ask John F. Kennedy. Then go.", ["Ask John F. Kennedy.", "Then go."]),
    ("Avoid St. Lucia, Mt. Elbrus and No. 5 Road. Dr. Smith, Mr. Lee and Mrs. Diaz agree. Done.",
     ["Avoid St. Lucia, Mt. Elbrus and No. 5 Road.", "Dr. Smith, Mr. Lee and Mrs. Diaz agree.", "Done."]),
    ("Updated Sept. 5 and Jan. 2026. Fine.", ["Updated Sept. 5 and Jan. 2026.", "Fine."]),
    ("A citizens' problem. not a sentence. Done.", ["A citizens' problem. not a sentence.", "Done."]),
    ("Temperatures reach 40°C. Carry water. Rest in the C. Block.", ["Temperatures reach 40°C.", "Carry water.", "Rest in the C. Block."]),
]

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp;
ensureAllAdvisories = async () => {};
const quote = () => { const m = /<p class="govsum">([\s\S]*?)<\/p>/.exec($("govScroll").innerHTML); return m ? m[1] : null; };
const rows = () => (($("govScroll").innerHTML.match(/class="govrow/g)) || []).length;
const card = async (iso, mine) => {
  advisories = _advBySource[mine]; govIso = iso;
  await renderGov(false);
  return { quote: quote(), rows: rows(), mine: /govrow mine"><div class="govname">([^<]*)/.exec($("govScroll").innerHTML) };
};
const out = { real: {}, all: {}, edge: [], ends: [] };
(async () => {
  _advBySource.us = FIX.us; _advBySource.ca = FIX.ca; _advBySource.de = FIX.de;
  for (const iso of FIX.real) for (const mine of ["us", "ca", "de"]) {
    const c = await card(iso, mine);
    out.real[iso + ":" + mine] = { quote: c.quote, rows: c.rows, mine: c.mine ? c.mine[1] : "" };
  }
  advisories = _advBySource.us;
  for (const it of FIX.us.items) if (it.iso && it.summary) { govIso = it.iso; await renderGov(false); out.all[it.iso] = quote(); }
  // The edge cases, each as Fooland's own US summary.
  for (const s of FIX.edge) {
    _advBySource.us = { source: "us", items: [{ iso: "FX", country: "Fooland", level: 3, level_text: "Reconsider travel", summary: s }] };
    advisories = _advBySource.us; govIso = "FX";
    await renderGov(false); out.edge.push(quote());
  }
  for (const t of FIX.ends) {
    let a = 0; const ss = sentenceEnds(t).map((e) => { const s = t.slice(a, e).trim(); a = e; return s; });
    if (t.slice(a).trim()) ss.push(t.slice(a).trim());
    out.ends.push(ss);
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""

# Canada's and Germany's lists carry levels, not summaries: enough of each for
# the three cards to have their three rows.
CA = {"source": "ca", "source_name": "Global Affairs Canada", "items": [
    {"iso": "UA", "country": "Ukraine", "level": 4, "level_text": "Avoid all travel"},
    {"iso": "CD", "country": "Congo (Kinshasa)", "level": 4, "level_text": "Avoid all travel"},
    {"iso": "AE", "country": "United Arab Emirates", "level": 3, "level_text": "Avoid non-essential travel"}]}
DE = {"source": "de", "source_name": "German Foreign Office", "items": [
    {"iso": "UA", "country": "Ukraine", "level": 4, "level_text": "Reisewarnung (avoid travel)"},
    {"iso": "CD", "country": "Kongo", "level": 2, "level_text": "Teilreisewarnung (warning for some regions)"},
    {"iso": "AE", "country": "VAE", "level": 1, "level_text": "Keine Warnung (no warning)"}]}
FIX = {"us": US, "ca": CA, "de": DE, "real": sorted(REAL), "edge": [e[1] for e in EDGE], "ends": [e[0] for e in ENDS],
       "ppp": json.load(open(P("public", "ppp.json"), encoding="utf-8"))}

with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-500:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)

esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
unesc = lambda s: s.replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

# ---- the three countries the round-9 gate saw ----------------------------------
for iso, (was, want) in sorted(REAL.items()):
    results.append(ok(SUM.get(iso, "").endswith("…") and SUM[iso].startswith(want),
                      "%s: the recorded summary is cut by the server (ends in \"…\") and opens with the sentence" % iso))
    results.append(ok(SUM.get(iso, "").startswith(was), "%s: main's quote was the summary trimmed at \"U.S. \"" % iso))
    for mine in ("us", "ca", "de"):
        c = js["real"]["%s:%s" % (iso, mine)]
        results.append(ok(c["quote"] is not None and unesc(c["quote"]) == want and c["rows"] == 3,
                          "%s card, %s list picked: quotes %r (was %r)%s" % (
                              iso, mine.upper(), want[-48:], was[-30:],
                              "" if c["quote"] and unesc(c["quote"]) == want else " — got %r" % c["quote"])))
    results.append(ok([js["real"][iso + ":" + m]["mine"][:2] for m in ("us", "ca", "de")] == ["🇺🇸", "🇨🇦", "🇩🇪"],
                      "%s card: the reader's own government's row is marked for each list" % iso))

# ---- every recorded summary ------------------------------------------------------
ABBR_END = re.compile(r"(?:^|[^\w.])(?:(?:[^\W\d_]\.){2,}|[A-Z]\.|(?:St|Mt|No|Dr|Mr|Mrs)\.)$")
whole = [i for i, s in SUM.items() if not s.endswith(("…", "..."))]
cut = [i for i, s in SUM.items() if s.endswith(("…", "..."))]
results.append(ok(len(js["all"]) == len(SUM) >= 200, "all %d recorded summaries drawn in a card" % len(SUM)))
bad = [i for i in whole if unesc(js["all"].get(i) or "") != SUM[i]]
results.append(ok(not bad, "the %d summaries without \"…\" are quoted whole %s" % (len(whole), bad[:5])))
bad = []
for i in cut:
    q = unesc(js["all"].get(i) or "")
    if q == SUM[i]:
        continue
    if not (SUM[i].startswith(q) and q.endswith((".", "!", "?")) and len(q) > 41 and not ABBR_END.search(q)
            and SUM[i][len(q)] == " "):
        bad.append((i, q[-40:]))
results.append(ok(not bad and len(cut) >= 4, "the %d with \"…\" end on a real sentence end or keep the \"…\" %s" % (len(cut), bad)))

# ---- the edge cases ----------------------------------------------------------------
for (what, s, want), got in zip(EDGE, js["edge"]):
    results.append(ok(got is not None and unesc(got) == want,
                      "%s%s" % (what, "" if got is not None and unesc(got) == want else " — got %r" % got)))

# ---- sentenceEnds --------------------------------------------------------------------
for (t, want), got in zip(ENDS, js["ends"]):
    results.append(ok(got == want, "sentenceEnds: %r%s" % (t[:60], "" if got == want else " — got %r" % got)))

# ---- Canada's chips -------------------------------------------------------------------
# (iso, field, topic heading HTML, its first paragraph, main's tip, the tip now).
CHIPS = [
    ("VI", "disasters-climate", "Earthquakes and tsunamis",
     "<p>The U.S. Virgin Islands are located in\u202fan active seismic zone.\u202fEarthquakes occur\u202ffrequently.</p>",
     "The U.S.", "The U.S. Virgin Islands are located in an active seismic zone."),
    ("VI", "disasters-climate", "Climate change",
     "<p>Climate change is affecting the U.S. Virgin Islands. Extreme and unusual weather events are becoming more "
     "frequent and may affect your travel plans. Monitor local media for the latest information.</p>",
     "Climate change is affecting the U.S.", "Climate change is affecting the U.S. Virgin Islands."),
    ("VI", "security", "Public transportation",
     "<p>Open-air &ldquo;safari taxis,&rdquo; which are shared, are common on the islands of St. Thomas and St. John.</p>",
     "Open-air “safari taxis,” which are shared, are common on the islands of St.",
     "Open-air “safari taxis,” which are shared, are common on the islands of St. Thomas and St. John."),
    ("VC", "disasters-climate", "Volcano",
     "<p>La Soufri&egrave;re volcano, located on the island of St. Vincent, is active. The last significant eruption "
     "occurred on April 2021.</p>",
     "La Soufrière volcano, located on the island of St.", "La Soufrière volcano, located on the island of St. Vincent, is active."),
    ("PE", "security", "Fraud",
     "<p>Counterfeit currency in both sol and U.S. dollars is a growing and serious problem. Counterfeit bills are "
     "widely distributed, including by banks, casinos and local stores.</p>",
     "Counterfeit currency in both sol and U.S.", "Counterfeit currency in both sol and U.S. dollars is a growing and serious problem."),
    ("BH", "security", "<p>Tensions in the Middle East</p>",
     "<p>On July 20, 2026, the U.S. Embassy in Manama issued the following security alert: &ldquo;The U.S. Embassy "
     "has information to suggest that Iran may seek to target unspecified locations in central Manama.&rdquo;</p>",
     "On July 20, 2026, the U.S.",
     "On July 20, 2026, the U.S. Embassy in Manama issued the following security alert: “The U.S. Embassy has "
     "information to suggest that Iran may seek to target unspecified locations in central Manama.”"),
    ("BN", "security", "Public transportation", "<p>Buses operate between 6 a.m. and 8 p.m. but are infrequent.</p>",
     "Buses operate between 6 a.m.", "Buses operate between 6 a.m. and 8 p.m. but are infrequent."),
    ("MR", "security", "Demonstrations",
     "<p>Demonstrations occur from time to time, particularly on Fridays between 1 p.m. and 3 p.m, after the afternoon "
     "prayer. Even peaceful demonstrations can turn violent at any time.</p>",
     "Demonstrations occur from time to time, particularly on Fridays between 1 p.m.",
     "Demonstrations occur from time to time, particularly on Fridays between 1 p.m. and 3 p.m, after the afternoon prayer."),
    ("MW", "security", "Adventure tourism <b></b>",
     "<p>Outdoor activities, such as kayaking, scuba diving, snorkelling, hiking, mountain biking, etc. and other "
     "adventure activities can be dangerous if unprepared. Trails are not always marked.</p>",
     "Outdoor activities, such as kayaking, scuba diving, snorkelling, hiking, mountain biking, etc.",
     "Outdoor activities, such as kayaking, scuba diving, snorkelling, hiking, mountain biking, etc. and other "
     "adventure activities can be dangerous if unprepared."),
    # A stray stop before a small letter isn't a sentence end: Canada's words
    # as written, not two of them dropped.
    ("TM", "security", "Demonstrations", "<p>Demonstrations occur. regularly.</p>",
     "Demonstrations occur.", "Demonstrations occur. regularly."),
    # Unchanged: a plain first sentence, and a temperature's "°C." ends one.
    ("KW", "disasters-climate", "Heat waves",
     "<p>Kuwait experiences extreme heat, especially in the summer between June and August, with temperatures well "
     "above 40&deg;C. Heat waves can cause dehydration.</p>",
     None, "Kuwait experiences extreme heat, especially in the summer between June and August, with temperatures well "
           "above 40°C."),
]
for iso, field, head, para, was, want in CHIPS:
    got = W.from_feed(iso, {"data": {"eng": {field: "<h3>%s</h3>%s<p>More text.</p>" % (head, para)}}})["watchouts"]
    d = got[0]["d"] if got else None
    results.append(ok(d == want, "%s chip %r: tip reads %r%s%s" % (
        iso, re.sub(r"<[^>]+>", "", head).strip(), want[-50:], " (was %r)" % was[-40:] if was else " (as before)",
        "" if d == want else " — got %r" % d)))

# The trim reads sentenceEnds, not a bare ". ".
src = re.search(r"async function renderGov\(focus\) \{.*?\n\}\n", APP, re.S).group(0)
results.append(ok("sentenceEnds(" in src and 'lastIndexOf(". "' not in src, "renderGov trims with sentenceEnds"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
