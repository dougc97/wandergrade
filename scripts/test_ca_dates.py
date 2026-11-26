"""Canada's advisories carry their own date, as the US's and Germany's do.

    /usr/bin/python3 scripts/test_ca_dates.py

No network. Global Affairs Canada's feed dates every country
("date-published": {"date": "2026-10-13 16:30:41", "asp": ..., "timestamp":
...}), but fxtracker/advisories.py _canadian_advisories dropped it, and the
code said "Canada's feed carries no date": the Canada column on
/safe-and-cheap and /do-not-travel had no date where the US and Germany
columns have one, and a reader following Canada got only "Fetched …" in the
guide's safety badge tip. The date is now the item's `updated`, the field
and format ('YYYY-MM-DD') the other two use, so every reader of `updated`
treats Canada like them. The feed is the real one, recorded 2026-11-26
(scripts/advisories_sample.ca-2026-11-26.json), beside the recorded State
Department feed (scripts/advisories_sample.us-2026-11-25.xml), both through
the server's own parsers. What it holds the code to:
  * every recorded Canada row gets `updated`, Ottawa's day from "date"
    (Thailand 2026-10-13, Mexico 2026-11-18, Japan 2026-10-26), and nothing
    else in a row changes; a row whose date is missing or unreadable is
    exactly the row it was before (no `updated`), and the feed still loads;
  * _ca_date: "date" first, then "asp", then the timestamp as a UTC day;
    junk, an impossible day, a day before 2000, a zero or boolean timestamp
    and a non-dict, non-string value give '' (no date);
  * a Canada gap-fill on another government's list (Monaco on the US's)
    carries Canada's date with it;
  * the list pages: the Canada cell shows its date where the US and German
    cells show theirs (the same <span class="when">, no new element), the
    sources line gives Canada's newest date as it does the others', and the
    /do-not-travel lastmod still moves only with a level change;
  * advhistory: Canada's date never dates a level change (only the US's own
    words do), so the record is what it was; the ▲/▼ marks (map_picks,
    home_picks, guide_sizers) still need a change, so a dated Canada row
    with none shows none;
  * the guide's safety badge tip (public/app.js renderGuideSafety, run under
    jsc with scripts/appjs_harness.js): "Advisory dated 13 Oct 2026 ·
    fetched 26 Nov 2026" for a Canada reader, and for a US reader on a
    Canada gap-fill; "Fetched 26 Nov 2026" still where no date came; the
    Safety tab's "what each government says" card gives Canada's "Updated";
  * the newsletter never reads `updated` (its code doesn't name it), so a
    dated Canada row can't move an email.
"""
import copy, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(k, None)     # advhistory in memory, never the real store
from fxtracker import (advisories as A, advhistory as H, guide_sizers as GS, home_picks as HP,  # noqa: E402
                       map_picks as MP, picks, render_lists as RL)

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
P = lambda *a: os.path.join(ROOT, *a)
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
TODAY = "2026-11-26"

CA_RAW = json.load(open(P("scripts", "advisories_sample.ca-2026-11-26.json"), encoding="utf-8"))
US_RAW = open(P("scripts", "advisories_sample.us-2026-11-25.xml"), encoding="utf-8").read()
feed = {"ca": CA_RAW}


def fetch_json(url, retries=3):
    if url == A.CA_FEED:
        return copy.deepcopy(feed["ca"])
    raise RuntimeError("no network in this test: %s" % url)


A.rates.fetch_json = fetch_json
A._fetch_text = lambda url, retries=3: US_RAW
# Germany's list, small: enough for its column to carry its dates.
DE = {"source": "de", "source_name": A.SOURCES["de"], "source_url": A.AA_URL, "items": [
    {"iso": "AF", "country": "Afghanistan", "level": 4, "level_text": "Reisewarnung (avoid travel)",
     "link": "https://www.auswaertiges-amt.de/de/-/204692", "updated": "2026-10-02"},
    {"iso": "UA", "country": "Ukraine", "level": 4, "level_text": "Reisewarnung (avoid travel)",
     "link": "https://www.auswaertiges-amt.de/de/-/201946", "updated": "2026-11-20"},
    {"iso": "SY", "country": "Syrien", "level": 4, "level_text": "Reisewarnung (avoid travel)",
     "link": "https://www.auswaertiges-amt.de/de/-/204278", "updated": "2026-11-12"}]}
A._german_advisories = lambda: copy.deepcopy(DE)

CA = A._canadian_advisories()
BY = {it["iso"]: it for it in CA["items"]}
ROWS = {v["country-iso"].strip().upper(): v for v in CA_RAW["data"].values()
        if isinstance(v, dict) and len((v.get("country-iso") or "").strip()) == 2 and v.get("advisory-state") is not None}

# ---- the recorded feed ----------------------------------------------------------
results.append(ok(len(CA["items"]) == len(ROWS) == 229, "the recorded feed parses: %d rows" % len(CA["items"])))
results.append(ok(all("updated" in it for it in CA["items"]), "every recorded Canada row has `updated`"))
results.append(ok(all(re.fullmatch(r"\d{4}-\d\d-\d\d", it["updated"]) for it in CA["items"]),
                  "in the US/German format, 'YYYY-MM-DD'"))
results.append(ok(all(BY[iso]["updated"] == v["date-published"]["date"][:10] for iso, v in ROWS.items()),
                  "each is the feed's own day for the row (date-published \"date\", Ottawa's)"))
for iso, day in (("TH", "2026-10-13"), ("MX", "2026-11-18"), ("JP", "2026-10-26")):
    results.append(ok(BY[iso]["updated"] == day, "%s dated %s (got %s)" % (iso, day, BY[iso].get("updated"))))
results.append(ok(all(set(it) == {"iso", "country", "level", "level_text", "link", "updated"} for it in CA["items"]),
                  "a row is what it was plus `updated`, nothing else"))

# The same feed with no dates at all is exactly what the parser gave before.
undated = copy.deepcopy(CA_RAW)
for v in undated["data"].values():
    v.pop("date-published", None)
feed["ca"] = undated
CA0 = A._canadian_advisories()
results.append(ok(CA0["items"] == [{k: v for k, v in it.items() if k != "updated"} for it in CA["items"]]
                  and not any("updated" in it for it in CA0["items"]),
                  "no date-published: every row exactly as before, no `updated`"))
# Odd dates on some rows: those rows go undated, the rest keep theirs.
odd = copy.deepcopy(CA_RAW)
odd_vals = {"TH": None, "MX": "garbage", "JP": {"date": "", "asp": None, "timestamp": 0},
            "FR": 20261125, "VN": {"date": "2026-02-30 10:00:00"}}
for v in odd["data"].values():
    iso = (v.get("country-iso") or "").strip().upper()
    if iso in odd_vals:
        v["date-published"] = odd_vals[iso]
feed["ca"] = odd
CAX = {it["iso"]: it for it in A._canadian_advisories()["items"]}
results.append(ok(len(CAX) == 229 and all("updated" not in CAX[i] for i in odd_vals)
                  and all(CAX[i]["updated"] == BY[i]["updated"] for i in CAX if i not in odd_vals),
                  "odd dates on five rows: those five undated, the feed still loads, the rest dated"))
feed["ca"] = CA_RAW

# ---- _ca_date ---------------------------------------------------------------------
CASES = [
    ({"date": "2026-10-13 16:30:41", "asp": "2026-10-13T16:30:41.78-04:00", "timestamp": 1791923441}, "2026-10-13"),
    # Ottawa's evening is already tomorrow in UTC: "date" is Canada's own day.
    ({"date": "2026-11-18 21:05:16", "asp": "2026-11-18T21:05:16-05:00", "timestamp": 1795053916}, "2026-11-18"),
    ({"date": "junk", "asp": "2026-10-13T16:30:41-04:00"}, "2026-10-13"),
    ({"date": "2026-13-40 00:00:00", "asp": "2026-10-13T16:30:41-04:00"}, "2026-10-13"),
    ({"timestamp": 1791923441}, "2026-10-13"),
    ({"timestamp": "1791923441"}, "2026-10-13"),
    ("2026-10-13 16:30:41", "2026-10-13"),
    (None, ""), ("", ""), ({}, ""), ("garbage", ""), ([], ""), (20261013, ""),
    ({"date": "2026-02-30 10:00:00"}, ""), ({"date": "2026-10-130"}, ""), ({"date": "1999-12-31 23:00:00"}, ""),
    ({"timestamp": 0}, ""), ({"timestamp": True}, ""), ({"timestamp": "abc"}, ""), ({"timestamp": -10 ** 20}, ""),
    ({"timestamp": None, "date": None, "asp": None}, ""),
]
for raw, want in CASES:
    got = A._ca_date(raw)
    results.append(ok(got == want, "_ca_date(%r) == %r%s" % (raw, want, "" if got == want else " — got %r" % got)))

# ---- gap-fills -----------------------------------------------------------------
US = A.get_advisories("us")
fills = {it["iso"]: it for it in US["items"] if it.get("via") == "ca"}
results.append(ok(fills.get("MC", {}).get("updated") == "2026-11-13" and fills["GI"].get("updated") == "2026-10-13",
                  "Canada's gap-fills on the US list carry Canada's date (Monaco 2026-11-13, Gibraltar 2026-10-13)"))
results.append(ok(fills and all(f.get("updated") == BY[i]["updated"] for i, f in fills.items()),
                  "all %d Canada gap-fills on the US list dated as on Canada's own" % len(fills)))
CAP = A.get_advisories("ca")
results.append(ok(all(it.get("updated") for it in CAP["items"] if not it.get("via")),
                  "Canada's own list, as /api/advisories?source=ca serves it, dated throughout"))

# ---- the list pages -------------------------------------------------------------
USP = A._us_advisories()
cell = lambda it: RL._gov_cell("ca", it)
results.append(ok(RL._when(BY["TH"]) == '<span class="when">13 Oct 2026</span>',
                  "Thailand's Canada cell: \"13 Oct 2026\" under the pill"))
results.append(ok(RL._when(dict(BY["MX"], changed="2026-11-20", change="up"))
                  == '<span class="when">18 Nov 2026 · ↑ since 20 Nov 2026</span>',
                  "with a recorded change: the date, then the change, as the US and German cells read"))
results.append(ok(RL._when({k: v for k, v in BY["JP"].items() if k != "updated"}) == "",
                  "an undated Canada row: no date, as before"))
DNT = RL.do_not_travel(USP, CAP, DE, fetched={"us": 1795694400, "ca": 1795694400, "de": 1795694400}, today=TODAY)
html_ = DNT["html"]


def row_of(page, iso):
    """The table row whose country cell links to the country's guide."""
    link = 'href="/guide/%s"' % RL._slug(iso)
    for r in re.findall(r"<tr>.*?</tr>", page, re.S):
        name = re.search(r'<td class="name"[^>]*>(.*?)</td>', r, re.S)
        if name and link in name.group(1):
            return r
    return ""


def gov_td(row, label):
    m = re.search(r'<td data-l="%s"[^>]*><span class="v">(.*?)</span></td>' % re.escape(label), row, re.S)
    return m.group(1) if m else ""


for iso in ("AF", "UA", "SY"):
    r = row_of(html_, iso)
    us_c, ca_c = gov_td(r, "US"), gov_td(r, "Canada")
    want = '<span class="when">%s</span>' % RL._day(BY[iso]["updated"])
    results.append(ok(want in ca_c and ca_c.count('class="when"') == 1 and 'class="when"' in us_c,
                      "/do-not-travel %s: Canada's cell dated %s, as the US's is (%r)"
                      % (iso, RL._day(BY[iso]["updated"]), re.sub(r"<[^>]+>", " ", ca_c).split())))
results.append(ok(re.search(r"Global Affairs Canada: fetched [^·]*, newest advisory dated 26 Nov 2026", html_),
                  "the sources line gives Canada's newest date, as it does the US's and Germany's"))
results.append(ok(DNT["lastmod"] == RL.lastmod_of(*[c[0] for c in RL.recent_changes(
                      {s: RL.own_by_iso(p) for s, p in (("us", USP), ("ca", CA0), ("de", DE))})]),
                  "the /do-not-travel lastmod is the same with or without Canada's dates (level changes only)"))
facts = json.load(open(P("public", "guide-facts.json"), encoding="utf-8"))
clim = json.load(open(P("public", "climate.json"), encoding="utf-8"))
SAC = RL.safe_and_cheap(USP, CAP, DE, facts, clim, {}, {}, today=TODAY)
listed = SAC["isos"]["safe"]
results.append(ok(len(listed) >= 3, "/safe-and-cheap lists countries from the recorded feeds (%d)" % len(listed)))
for iso in listed[:3]:
    ca_c = gov_td(row_of(SAC["html"], iso), "Canada")
    results.append(ok(('<span class="when">%s</span>' % RL._day(BY[iso]["updated"])) in ca_c,
                      "/safe-and-cheap %s: Canada's cell dated %s" % (iso, RL._day(BY[iso]["updated"]))))
SAC0 = RL.safe_and_cheap(USP, CA0, DE, facts, clim, {}, {}, today=TODAY)
results.append(ok(SAC0["isos"] == SAC["isos"] and SAC0["counts"] == SAC["counts"] and SAC0["lastmod"] == SAC["lastmod"],
                  "/safe-and-cheap: the same countries, counts and lastmod with or without Canada's dates"))
strip = lambda h: re.sub(r'<span class="when">[^<]*</span>|(, |: )newest advisory dated \d{1,2} \w{3} \d{4}', "", h)
results.append(ok(strip(SAC0["html"]) == strip(SAC["html"]) and strip(RL.do_not_travel(
                      USP, CA0, DE, fetched={"us": 1795694400, "ca": 1795694400, "de": 1795694400}, today=TODAY)["html"])
                  == strip(html_),
                  "both pages differ from the undated render only by Canada's dates (and its newest date)"))
whens = lambda h: h.count('<span class="when">')
ca_cells = lambda h: len(re.findall(r'<td data-l="Canada"[^>]*><span class="v"><span class="lvl lvl\d', h))
results.append(ok(whens(SAC["html"]) - whens(SAC0["html"]) == ca_cells(SAC["html"]) > 0,
                  "/safe-and-cheap: one date added per rated Canada cell (%d), nothing else"
                  % ca_cells(SAC["html"])))

# ---- advhistory and the moved marks ------------------------------------------------
H._mem.clear()
H.record_and_annotate("ca", {"items": [dict(BY["MX"], level=1)]}, "2026-11-01")
r = H.record_and_annotate("ca", {"items": [dict(BY["MX"])]}, "2026-11-20")["items"][0]
results.append(ok(r.get("changed") == "2026-11-20" and r.get("change") == "up" and r["updated"] == "2026-11-18",
                  "a Canada level change is dated the day the record saw it, not by Canada's date (the US's "
                  "words alone date one)"))
T = __import__("datetime").date(2026, 11, 26)
dated = dict(BY["MX"])          # dated 18 Nov, no change
results.append(ok(HP.adv_moved(dated, T) == "" and MP.adv_items({"source": "ca", "items": [dated]}, lambda i: None, T) == []
                  and "advmoved" not in GS.safety("MX", {"MX": dated}, A.SOURCES["ca"], None, None, T, "ca"),
                  "a dated Canada row with no change: no ▲/▼ on Top Picks, the Safety map row or the guide line"))
moved = dict(BY["MX"], changed="2026-11-20", change="up")
results.append(ok("advmv chup" in HP.adv_moved(moved, T) and "20 Nov" in MP.adv_items({"source": "ca", "items": [moved]}, lambda i: None, T)[0]
                  and "▲ raised 20 Nov" in GS.safety("MX", {"MX": moved}, A.SOURCES["ca"], None, None, T, "ca"),
                  "with a recorded change: marked and dated by the change, as for the US and Germany"))

# ---- app.js: the guide's badge tip and the government card -----------------------------
DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
ppp = FIX.ppp;
ensureAdvisories = async () => advisories;
ensureAllAdvisories = async () => {};
const tipOf = () => { const m = /class="advbadge [^"]*" data-tip="([^"]*)"/.exec($("guideSafety").innerHTML); return m ? m[1] : null; };
const out = { tip: {}, gov: {} };
(async () => {
  for (const [key, list, iso] of FIX.badges) {
    advisories = FIX[list]; ccGuideIso = iso;
    renderGuideSafety(iso); await null; await null; await null;
    out.tip[key] = tipOf();
  }
  _advBySource.us = FIX.us; _advBySource.ca = FIX.ca; _advBySource.de = FIX.de;
  for (const iso of FIX.gov) {
    advisories = FIX.ca; govIso = iso; await renderGov(false);
    const m = /Global Affairs Canada<\/div>[\s\S]*?<div class="muted">([\s\S]*?)<\/div>/.exec($("govScroll").innerHTML);
    out.gov[iso] = m ? m[1].replace(/<a [^>]*>[^<]*<\/a>/, "LINK") : null;
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""
stamp = lambda p: dict(p, fetched=TODAY)
FIX = {"ca": stamp(CAP), "ca0": stamp(dict(CAP, items=CA0["items"])), "us": stamp(US), "de": stamp(DE),
       "badges": [["TH", "ca", "TH"], ["MX", "ca", "MX"], ["JP", "ca", "JP"], ["JP0", "ca0", "JP"], ["MC", "us", "MC"],
                  ["US-TH", "us", "TH"]],
       "gov": ["TH", "MX", "JP"], "ppp": json.load(open(P("public", "ppp.json"), encoding="utf-8"))}
with tempfile.TemporaryDirectory() as d:
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
    json.dump(FIX, open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(open(P("scripts", "appjs_harness.js"), encoding="utf-8").read() + "\n"
                                          + open(P("public", "app.js"), encoding="utf-8").read() + "\n"
                                          + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-500:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" not in js:
    tip = js["tip"]
    for iso, day in (("TH", "13 Oct 2026"), ("MX", "18 Nov 2026"), ("JP", "26 Oct 2026")):
        want = "Advisory dated %s · fetched 26 Nov 2026" % day
        results.append(ok(tip.get(iso) == want, "guide badge tip, Canada reader, %s: %r (was \"Fetched 26 Nov 2026\")%s"
                          % (iso, want, "" if tip.get(iso) == want else " — got %r" % tip.get(iso))))
    results.append(ok(tip.get("JP0") == "Fetched 26 Nov 2026", "an undated row still says only \"Fetched 26 Nov 2026\""))
    results.append(ok(tip.get("MC") == "Advisory dated 13 Nov 2026 · fetched 26 Nov 2026",
                      "a US reader on Monaco (Canada's gap-fill) gets Canada's date: %r" % tip.get("MC")))
    results.append(ok(tip.get("US-TH") == "Advisory dated 7 Jul 2026 · fetched 26 Nov 2026",
                      "a US reader on Thailand: the State Department's date, unchanged (%r)" % tip.get("US-TH")))
    for iso, day in (("TH", "13 Oct 2026"), ("MX", "18 Nov 2026"), ("JP", "26 Oct 2026")):
        want = "Updated %s · LINK" % day
        results.append(ok(js["gov"].get(iso) == want, "government card, Canada's row for %s: %r%s"
                          % (iso, want, "" if js["gov"].get(iso) == want else " — got %r" % js["gov"].get(iso))))

# ---- the newsletter ---------------------------------------------------------------
NL = [P("fxtracker", f) for f in ("picks.py", "newsletter.py", "digest_variants.py")] + \
     [P("scripts", f) for f in ("send_digest.py", "check.py", "digest_check.py", "digest_snapshot.py")]
named = [os.path.relpath(f, ROOT) for f in NL if os.path.exists(f)
         and re.search(r"""["']updated["']|\.updated\b""", open(f, encoding="utf-8").read())]
results.append(ok(not named, "the newsletter's code never reads `updated`%s" % (": " + ", ".join(named) if named else "")))
items_d, items_u = US["items"], [{k: v for k, v in it.items() if k != "updated"} for it in US["items"]]
results.append(ok(picks.advisory_levels(items_d) == picks.advisory_levels(items_u)
                  and picks.advisory_sources(items_d) == picks.advisory_sources(items_u),
                  "the digest's levels and sources are the same with or without dates"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
