#!/usr/bin/env python3
"""/dollar-strength (fxtracker/render_strength.py and its server wiring),
from fixtures — no network.

    /usr/bin/python3 scripts/test_dollar_strength.py

Fixtures: scripts/fixtures/strength/ holds production GETs of 2026-10-23,
trimmed (/api/rates without the old 1-year index and the unused row fields,
/ppp.json without names, /api/index?range=all and ?range=1y with every 10th
point). The ECB history behind the index is synthetic (a seeded random walk
from 1999), because /api/index only ever ships a thinned copy.

What it holds the code to:
  * the ranking is the Currency tab's rows (USD's own row out, pegged rows
    folded into their anchor) sorted by pricelevel.real_fx_pct, strongest
    first, and the page prints them in that order;
  * every figure is the one app.js computes for the same rows, run under jsc
    from the app's own functions (realFxPct, currencyCountry/-Countries,
    currencySpread over plAnchor("US"), signedPct, fxInflBasis, the
    realGain count), and the mirrored tables (TABLE_CUR, PRIMARY_COUNTRY,
    CUR_SUPRA_FLAG) equal app.js's; JS toFixed/fmtPct/fmtIdx formatting;
  * a currency with no honest real figure (high inflation with no current
    reading, no country, too few days since a regime change) is listed apart
    with its before-inflation move and the reason, never ranked;
  * the lede's index numbers are the Data tab's (the payloads' change_pct,
    core_change_pct and level, formatted as app.js does), "before inflation"
    is said, the core majors' figure is beside it; index_payloads equals
    rates.compute_index on the same history for 1y and all;
  * degraded: no rates, no PPP, no index history — each renders, says so,
    reports degraded; titles <= 60, descriptions <= 157; one h1, no ad-blocker
    class names, every /guide/ link real, no JavaScript in the body;
  * the server: /dollar-strength 200 (max-age=300, or no-store when an input
    is missing), the slash variant 301, deeper paths 404, HEAD, the memo, the
    sitemap line after /do-not-travel dated by the rates (never today).
"""
import datetime
import html.parser
import http.client
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "parity"))
from fxtracker import pricelevel, rates, render_guide as rg, render_strength as RS  # noqa: E402
import build_js  # noqa: E402  (scripts/parity: lifts declarations out of app.js)

FIX = os.path.join(ROOT, "scripts", "fixtures", "strength")
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


RATES = load("rates_2026-10-23.json")
PPP = load("ppp_2026-10-23.json")
IDX = {"all": load("index_all_2026-10-23.json"), "1y": load("index_1y_2026-10-23.json")}
TODAY = "2026-10-23"


class Check(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1, self.names, self.hrefs, self.text, self.open = 0, [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.h1 += tag == "h1"
        for k in ("class", "id"):
            if a.get(k):
                self.names += a[k].split()
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag not in ("br", "meta", "link", "img", "input"):
            self.open.append(tag)

    def handle_endtag(self, tag):
        if self.open and self.open[-1] == tag:
            self.open.pop()
        else:
            raise ValueError("unbalanced </%s> (open: %s)" % (tag, self.open[-3:]))

    def handle_data(self, data):
        self.text.append(data)


FORBIDDEN = re.compile(r"^(ad|adv|sponsor|banner|promo)|advert", re.I)


def hygiene(page, label, links=True):
    c = Check()
    c.feed(page["html"])
    c.close()
    results.append(ok(len(page["title"]) <= RS.TITLE_MAX, "%s: title %d chars <= %d: %r"
                      % (label, len(page["title"]), RS.TITLE_MAX, page["title"])))
    results.append(ok(len(page["desc"]) <= RS.DESC_MAX, "%s: description %d chars <= %d: %r"
                      % (label, len(page["desc"]), RS.DESC_MAX, page["desc"])))
    results.append(ok(c.h1 == 1, "%s: exactly one h1 (%d)" % (label, c.h1)))
    bad = sorted({n for n in c.names if FORBIDDEN.search(n)})
    results.append(ok(not bad, "%s: no class or id an ad blocker hides %s" % (label, bad or "")))
    guides = [h for h in c.hrefs if h.startswith("/guide/")]
    dead = [h for h in guides if not rg.iso_for_slug(h[len("/guide/"):])]
    results.append(ok((bool(guides) if links else True) and not dead,
                      "%s: %d /guide/ links, every one a real slug %s" % (label, len(guides), dead or "")))
    results.append(ok(not c.open, "%s: html.parser accepts it, every tag closed %s" % (label, c.open or "")))
    text = " ".join(c.text)
    results.append(ok("None" not in text and "None" not in page["title"] + page["desc"] and "nan" not in text.lower().split(),
                      "%s: no \"None\" in the text" % label))
    results.append(ok("<script" not in page["html"], "%s: no JavaScript in the body" % label))
    for w in ("buy now", "exchange now", "invest", "forecast to", "will rise", "will fall"):
        if w in text.lower():
            results.append(ok(False, "%s: no advice wording (%r found)" % (label, w)))
    return c, text


# ---- JavaScript formatting -------------------------------------------------------------
VALS = [131.45, 31.45, 0.125, -0.04, -0.0, 0.0, 2.675, 1.005, 0.5, 2.5, -2.5, 1e-7, 41.83, -11.64, 9.995, -9.995, 0.4, 1.99]


def jsc(prog):
    path = os.path.join(ROOT, "scripts", "parity", "_strength_run.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prog)
    try:
        out = subprocess.run([JSC, path], capture_output=True, text=True, timeout=60)
    finally:
        os.remove(path)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit("jsc failed:\n%s\n%s" % (out.stdout[-2000:], out.stderr[-2000:]))
    return json.loads(out.stdout.strip().splitlines()[-1])


with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()
fmt_js = jsc("\n".join([
    'const MON_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];',
    build_js._cut(APP, "function signedPct"), build_js._cut(APP, "const fmtIdx"), build_js._cut(APP, "const fmtPct"),
    "const V = %s;" % json.dumps(VALS),
    "print(JSON.stringify({fixed1: V.map((v) => v.toFixed(1)), fixed2: V.map((v) => v.toFixed(2)),"
    " signed: V.map((v) => signedPct(v, 1)), pct: V.map(fmtPct), idx: V.filter((v) => v >= 0.001).map(fmtIdx)}));"]))
results.append(ok(fmt_js["fixed1"] == [RS.js_fixed(v, 1) for v in VALS] and fmt_js["fixed2"] == [RS.js_fixed(v, 2) for v in VALS],
                  "js_fixed is Number.toFixed on %d values (exact halves, -0, 131.45 -> 131.4)" % len(VALS)))
results.append(ok(fmt_js["signed"] == [RS.signed_pct(v) for v in VALS] and fmt_js["pct"] == [RS.fmt_pct(v) for v in VALS]
                  and fmt_js["idx"] == [RS.fmt_idx(v) for v in VALS if v >= 0.001],
                  "signed_pct, fmt_pct and fmt_idx print what app.js signedPct, fmtPct and fmtIdx print"))

# ---- the realistic fixture ---------------------------------------------------------------
P = RS.dollar_strength(RATES, PPP, IDX, today=TODAY)
c, text = hygiene(P, "/dollar-strength")
results.append(ok(not P["degraded"] and P["lastmod"] == "2026-10-23", "everything in hand: not degraded; lastmod is the rates' "
                  "as-of date (%s)" % P["lastmod"]))

# Rows as the Currency tab has them: USD's own row out, pegged rows folded.
rows = [r for r in RATES["rows"] if r["code"] != "USD"]
listed = {r["code"] for r in rows}
folded = {r["code"] for r in rows if r.get("pegged_to") in listed}
tab = [r for r in rows if r["code"] not in folded]
expect_real = {}
for r in tab:
    iso = RS.currency_country(r["code"])
    real = pricelevel.real_fx_pct(r["strength_pct"], iso, "US", PPP) if iso and not r.get("no_trend") else None
    expect_real[r["code"]] = real
order = sorted((code for code, v in expect_real.items() if v is not None), key=lambda k: (-expect_real[k], k))
results.append(ok(P["codes"]["ranked"] == order, "the ranking is real_fx_pct, strongest first (%d currencies, %s first)"
                  % (len(order), order[0])))
results.append(ok(all(a >= b for a, b in zip([expect_real[k] for k in order], [expect_real[k] for k in order][1:])),
                  "and it never rises down the table"))
shown = re.findall(r'<tr><td class="num" data-l="#">(\d+)</td><td class="name" data-l="Currency"><span class="rk">(\d+)\.</span>'
                   r'[^<]*<span class="dscode">([A-Z]{3})</span>', P["html"])
results.append(ok([c for _n, _r, c in shown] == order
                  and [int(n) for n, _r, _c in shown] == [int(r) for _n, r, _c in shown] == list(range(1, len(order) + 1)),
                  "the page prints the rows in that order, numbered 1..%d in the # column and again in the name "
                  "cell (the rank a phone or tablet card shows, # being hidden there)" % len(order)))
results.append(ok(sorted(P["codes"]["apart"]) == sorted(k for k, v in expect_real.items() if v is None)
                  and not set(P["codes"]["apart"]) & set(order),
                  "every currency without a real figure is apart, none ranked: %s" % P["codes"]["apart"]))
results.append(ok(not folded & set(P["codes"]["ranked"] + P["codes"]["apart"]) and "USD" not in P["codes"]["ranked"]
                  and P["counts"]["pegged"] == len(folded),
                  "pegged rows (%s) fold into their anchor, never listed on their own; no USD row" % ", ".join(sorted(folded))))
eur = re.search(r'<tr>(?:(?!</tr>).)*<span class="dscode">EUR</span>.*?</tr>', P["html"], re.S).group(0)
pegs = sorted(r["code"] for r in rows if r.get("pegged_to") == "EUR")
results.append(ok('+%d pegged</span>' % len(pegs) in eur and ", ".join(c for c in [r["code"] for r in rows] if c in pegs) in eur,
                  "the euro's row says +%d pegged, the codes in its tooltip" % len(pegs)))
m = re.search(r'data-l="Used in"><span class="v">(.*?)</span></td>', eur, re.S).group(1)
n_eur = len(RS.currency_countries("EUR"))
results.append(ok(m.startswith('<a href="/guide/germany">Germany</a>, ') and ("and %d more" % (n_eur - RS.NAMES_SHOWN)) in m
                  and m.count("<a ") <= RS.NAMES_SHOWN and re.search(r'title="Germany, [^"]*Vatican City', m)
                  and "MC" not in re.search(r'title="([^"]*)"', m).group(1).split(", "),
                  "a long list (the euro's %d places) is cut: Germany first, %d names, \"and %d more\", every name in the tooltip"
                  % (n_eur, RS.NAMES_SHOWN, n_eur - RS.NAMES_SHOWN)))
bob = re.search(r'<tr>(?:(?!</tr>).)*<span class="dscode">BOB</span>.*?</tr>', P["html"], re.S).group(0)
results.append(ok('<a href="/guide/bolivia">Bolivia</a>' in bob and "+41.8%" in bob and ">+31.6%<" in bob
                  and 'class="pos"' in bob and "Bolivia ~" in bob and '%</span> <span class="band">very cheap' in bob,
                  "Bolivia's row: guide link, before and after inflation, the inflation gap in the tooltip, prices with the band"))
twd = re.search(r'<tr>(?:(?!</tr>).)*<span class="dscode">TWD</span>.*?</tr>', P["html"], re.S).group(0)
results.append(ok('<sup class="fn">†</sup>' in twd and "No inflation figure for Taiwan" in twd
                  and "† No inflation figure for that country" in text and '<sup class="fn">†</sup>' not in bob,
                  "a country with no inflation figure (Taiwan) is marked † and footnoted: its figure is the exchange rate alone"))

# Every figure against app.js, run under jsc from its own functions.
GRAB = ["const EUROZONE", "const USD_USING", "const CUR_BY_ISO", "const PPP_UNIT", "const PL_PLAUSIBLE_SD",
        "const PRIMARY_COUNTRY", "const TABLE_CUR", "const CUR_SUPRA_FLAG", "function rateForCurrency", "function inflRate",
        "function inflUS", "function highInflUnknown", "function pplCarry", "function fxHomeIso", "function fxInflBasis",
        "function realFxPct", "function currencyCountries", "function currencyCountry", "function priceLevelRaw",
        "function _computePlFit", "function plFit", "function plImplausible", "function priceLevel",
        "function tablePriceLevel", "function currencySpread", "function plAnchor", "function signedPct"]
asof = datetime.date.fromisoformat(RATES["as_of"])
prelude = """
"use strict";
const FIX = %s;
let homeBase = "USD", lastRates = FIX.rates, dataRates = null, homeRates = null, ppp = FIX.ppp, ISO2SLUG = null;
let _plFitFor, _plFitVal;
function guidePassport() { return "US"; }
function originIso() { return "US"; }
function countryName(iso) { return iso; }
// The rates' own date, as the server carries prices to it (guide_facts).
function nowYearFrac() { return FIX.now_y; }
""" % json.dumps({"rates": RATES, "ppp": PPP, "now_y": pricelevel.now_year(asof)})
epilogue = r"""
const rows = FIX.rates.rows.filter((r) => r.code !== "USD");
const listed = new Set(rows.map((r) => r.code));
const folded = {};
const tableRows = rows.filter((r) => {
  if (!r.pegged_to || !listed.has(r.pegged_to)) return true;
  (folded[r.pegged_to] = folded[r.pegged_to] || []).push(r.code);
  return false;
});
const A = plAnchor("US");
const out = { folded, strong: 0, rows: {}, consts: { TABLE_CUR, PRIMARY_COUNTRY, CUR_SUPRA_FLAG } };
for (const r of tableRows) {
  const c = currencyCountry(r.code);
  const real = c ? realFxPct(c, r.strength_pct) : null;
  if (r.favorable && r.watched && real != null && real > 0) out.strong++;
  const sp = currencySpread(r.code);
  const pc = (pl) => Math.round(100 * (pl / A.pl));
  out.rows[r.code] = { ctry: c, places: currencyCountries(r.code), real,
    before: signedPct(r.strength_pct, 1), after: real == null ? null : signedPct(real, 1),
    adj: c ? !!fxInflBasis(c, "US").adj : false,
    lo: sp ? pc(sp.lo.pl) : null, hi: sp ? pc(sp.hi.pl) : null, n: sp ? sp.n : 0,
    lo_iso: sp ? sp.lo.iso : null, hi_iso: sp ? sp.hi.iso : null };
}
print(JSON.stringify(out));
"""
J = jsc(prelude + "\n\n".join(build_js._cut(APP, d) for d in GRAB) + epilogue)
results.append(ok(J["consts"]["TABLE_CUR"] == RS.TABLE_CUR and J["consts"]["PRIMARY_COUNTRY"] == RS.PRIMARY_COUNTRY
                  and J["consts"]["CUR_SUPRA_FLAG"] == RS.CUR_SUPRA_FLAG,
                  "TABLE_CUR, PRIMARY_COUNTRY and CUR_SUPRA_FLAG equal app.js's"))
results.append(ok(set(J["rows"]) == set(P["codes"]["ranked"]) | set(P["codes"]["apart"]),
                  "the page's currencies are exactly the Currency tab's rows (%d)" % len(J["rows"])))
mism = []
for row in P["rows"] + P["apart"]:
    j = J["rows"][row["code"]]
    if j["ctry"] != row["iso"] or j["places"] != row["places"]:
        mism.append((row["code"], "country", j["ctry"], row["iso"]))
    if j["before"] != RS.signed_pct(row["nominal"]):
        mism.append((row["code"], "before", j["before"], RS.signed_pct(row["nominal"])))
    if row in P["rows"]:
        if j["real"] is None or abs(j["real"] - row["real"]) > 1e-9 or j["after"] != RS.signed_pct(row["real"]):
            mism.append((row["code"], "after", j["real"], row["real"]))
        if j["adj"] != row["adj"]:
            mism.append((row["code"], "adj", j["adj"], row["adj"]))
    elif row["reason"][0] != "trend" and j["real"] is not None:
        mism.append((row["code"], "apart but the tab has a real figure", j["real"], None))
    pr = row["priced"]
    mine = (RS._pct(pr[0][0]), RS._pct(pr[-1][0]), len(pr), pr[0][1], pr[-1][1]) if pr else (None, None, 0, None, None)
    if (j["lo"], j["hi"], j["n"], j["lo_iso"], j["hi_iso"]) != mine:
        mism.append((row["code"], "prices", (j["lo"], j["hi"], j["n"], j["lo_iso"], j["hi_iso"]), mine))
for m in mism[:12]:
    print("        mismatch %s %s: app.js=%r page=%r" % m)
results.append(ok(not mism, "every row's country, before- and after-inflation figure (to 1e-9 and as printed), "
                  "\"no inflation figure\" mark and price range equal app.js's (%d rows, %d mismatches)"
                  % (len(J["rows"]), len(mism))))
results.append(ok(J["folded"] == {k: v for k, v in RS.table_rows(RATES)[1].items()},
                  "the folded pegs equal the tab's: %s" % J["folded"]))
results.append(ok(J["strong"] == P["counts"]["strong"]
                  and "<strong>%d</strong> are stronger than usual" % J["strong"] in P["html"],
                  "\"stronger than usual\" is the tab's green-row count (%d)" % J["strong"]))
# Spot-check the printed cells against the JS figures.
cells = re.findall(r'<tr><td class="num"[^>]*>\d+</td><td class="name"[^>]*>.*?<span class="dscode">([A-Z]{3})</span>.*?'
                   r'data-l="Before inflation"><span class="v">([^<]*)</span>.*?data-l="After inflation"><span class="v">'
                   r'<span[^>]*>([^<]*)</span>.*?data-l="Prices vs US"><span class="v">(.*?)</span></td></tr>', P["html"], re.S)
bad = []
for code, before, after, prices in cells:
    j = J["rows"][code]
    want = "—" if j["lo"] is None else ("%d%%" % j["lo"] if j["n"] == 1 or j["lo"] == j["hi"] else "%d–%d%%" % (j["lo"], j["hi"]))
    if before != j["before"] or after != j["after"] or re.sub(r"<[^>]+>", "", prices).split(" ")[0] != want:
        bad.append((code, before, after, prices[:60]))
results.append(ok(len(cells) == len(order) and not bad, "the printed cells are app.js's figures (%d rows) %s"
                  % (len(cells), bad[:3] or "")))

# Apart: the reasons.
apart = {r["code"]: r for r in P["apart"]}
ul = re.search(r'<ul class="dsnone">(.*?)</ul>', P["html"], re.S).group(1)
results.append(ok("<h2>No inflation-adjusted figure (%d)</h2>" % len(apart) in P["html"]
                  and "ARS</span> Argentine Peso: <strong>+5.5%</strong> before inflation — Argentina&#x27;s latest inflation "
                      "figure (220% in 2024) is older than its 2025 price data." in ul
                  and "PAB</span> Panamanian Balboa: <strong>0.0%</strong> before inflation — not matched to a country." in ul
                  and "XCD</span> East Caribbean Dollar: <strong>0.0%</strong> before inflation — shared by 6 places" in ul,
                  "the apart list: each with its before-inflation move and its reason (stale high inflation, no country, "
                  "a currency shared with no one inflation figure)"))

# The lede: the Data tab's figures, before inflation, with the core majors.
results.append(ok("<strong>131.4</strong> as of 22 Oct 2026" in P["html"]
                  and "<strong>+0.40%</strong> over the past year and <strong>+31.4%</strong> since 1999, both before inflation"
                  in P["html"]
                  and "Against the euro, yen, pound and Swiss franc alone: <strong>+2.27%</strong> over the past year, "
                      "<strong>+1.99%</strong> since 1999" in P["html"],
                  "the lede: index 131.4 (fmtIdx of 131.45), +0.40% / +31.4% before inflation, core +2.27% / +1.99%"))
results.append(ok(P["index"] == {"level": 131.45, "y1": IDX["1y"]["change_pct"], "all": IDX["all"]["change_pct"], "since": "1999"},
                  "its numbers are the /api/index payloads' own"))
results.append(ok("slides against the rest" in P["html"] and P["html"].count("before inflation") >= 3,
                  "\"before inflation\" said in the lede and the rows; the ⓘ explains the long-run drift"))
svg = re.search(r'<svg class="dsline up"[^>]*role="img" aria-label="([^"]+)"', P["html"])
results.append(ok(svg and "131.4 on 22 Oct 2026" in svg.group(1) and "+31.4% since 1999" in svg.group(1)
                  and "before inflation" in svg.group(1) and "+1.99% since 1999" in svg.group(1)
                  and "<figcaption><span>Jan 1999 = 100</span><span>131.4 · 22 Oct 2026</span></figcaption>" in P["html"],
                  "the index line: role=img with the numbers in its label, the base and today under it"))
results.append(ok(P["title"] == "Where the US Dollar Is Strongest Now, Inflation-Adjusted"
                  and P["desc"].startswith("%d currencies ranked" % len(order)) and "%d stronger than usual" % J["strong"] in P["desc"]
                  and "Bolivia first at +31.6%" in P["desc"] and "23 Oct 2026" in P["desc"],
                  "title fixed; the description from live figures: %r" % P["desc"]))

# ---- index_payloads == rates.compute_index on one history ----------------------------
rnd = random.Random(7)
d, dates = datetime.date(1999, 1, 4), []
while d <= datetime.date(2026, 10, 22):
    if d.weekday() < 5:
        dates.append(d.isoformat())
    d += datetime.timedelta(days=1)
cols = {}
for c in sorted(rates.MAJORS):
    v, col = 1.0 + rnd.random() * 100, []
    for i, day in enumerate(dates):
        v *= math.exp(rnd.gauss(0.00003 if c != "TRY" else 0.0007, 0.006))
        col.append(None if (c == "BRL" and day < "2000-01-03") or (c == "ISK" and "2008-10-09" <= day <= "2018-01-31") else v)
    cols[c] = col
real_get, real_series = rates.get_history, dict(rates._series_cache)
rates.get_history = lambda: (12345.0, dates, cols)
rates._series_cache.clear()
try:
    today = datetime.date(2026, 10, 23)
    mine = RS.index_payloads(dates, cols, today)
    same = []
    for rng in ("1y", "all"):
        ref = rates.compute_index(rng, "USD", today)
        for k in ("change_pct", "core_change_pct", "core", "index_count", "base_date", "as_of", "source"):
            same.append((rng, k, ref[k] == mine[rng][k], ref[k], mine[rng][k]))
        same.append((rng, "level", ref["index"][-1]["value"] == mine[rng]["level"], ref["index"][-1]["value"], mine[rng]["level"]))
finally:
    rates.get_history = real_get
    rates._series_cache.clear()
    rates._series_cache.update(real_series)
diff = [s for s in same if not s[2]]
results.append(ok(not diff, "index_payloads equals rates.compute_index (1y and all: change, core change, level, dates, "
                  "basket) on a synthetic 1999-2026 history %s" % (diff[:2] or "")))
mon = mine["all"]["monthly"]
results.append(ok(len(mon) == len({x["date"][:7] for x in mon}) == (2026 - 1999) * 12 + 10
                  and mon[-1]["value"] == mine["all"]["level"] and mon[0]["date"] == "1999-01-29",
                  "monthly points: one per month, the month's last fixing, ending on the headline level (%d)" % len(mon)))
P2 = RS.dollar_strength(RATES, PPP, mine, today=TODAY)
results.append(ok(not P2["degraded"] and P2["html"].count("<polyline") == 1
                  and len(re.search(r'<polyline points="([^"]*)"', P2["html"]).group(1).split()) == len(mon)
                  and fmt_js and "%s</strong> as of 22 Oct 2026" % RS.fmt_idx(mine["all"]["level"]) in P2["html"],
                  "from index_payloads the page draws the monthly line and prints its level"))

# ---- degraded -------------------------------------------------------------------------------
D1 = RS.dollar_strength(RATES, PPP, None, today=TODAY)
hygiene(D1, "no index history")
results.append(ok(D1["degraded"] and "The overall dollar index isn't loaded right now" in D1["html"] and "<svg" not in D1["html"]
                  and "131.4" not in D1["html"] and D1["codes"]["ranked"] == order and "Dollar index:" not in D1["html"],
                  "no index history: the lede omits the index and says so, the table stands, degraded"))
D2 = RS.dollar_strength(None, PPP, IDX, today=TODAY)
hygiene(D2, "no rates", links=False)
results.append(ok(D2["degraded"] and "The exchange rates aren't loaded right now, so the currency table is left out: this page "
                  "is served uncached until they are back." in D2["html"] and "<table" not in D2["html"]
                  and "<strong>131.4</strong>" in D2["html"] and D2["lastmod"] == "",
                  "no rates: the index lede stands, the table is left out and the page says so; degraded, no lastmod"))
D3 = RS.dollar_strength(RATES, None, IDX, today=TODAY)
results.append(ok(D3["degraded"] and "The World Bank price data isn't loaded right now" in D3["html"] and "it is back" in D3["html"]
                  and "<table" not in D3["html"], "no PPP table: said so, in the singular; degraded"))
D4 = RS.dollar_strength(None, None, None, today=TODAY)
hygiene(D4, "nothing cached", links=False)
results.append(ok(D4["degraded"] and "The exchange rates and the World Bank price data aren't loaded" in D4["html"]
                  and "isn't loaded right now" in D4["html"] and '<p class="asof">' not in D4["html"],
                  "nothing cached: still a page, every gap said, degraded"))
D5 = RS.dollar_strength(dict(RATES, rows=[]), PPP, IDX, today=TODAY)
results.append(ok(D5["degraded"] and "<table" not in D5["html"], "a rates payload with no rows counts as not loaded"))
# A row just after a regime switch claims no move: apart, never ranked.
nt = dict(RATES, rows=[dict(r, strength_pct=0.0, no_trend=True) if r["code"] == "THB" else r for r in RATES["rows"]])
D6 = RS.dollar_strength(nt, PPP, IDX, today=TODAY)
results.append(ok("THB" in D6["codes"]["apart"] and "THB" not in D6["codes"]["ranked"]
                  and "fewer than 30 days of rates since its exchange-rate regime changed" in D6["html"],
                  "a no-trend row (regime change) is apart with its reason"))
results.append(ok(all(" None" not in p["html"] and ">None<" not in p["html"] for p in (P, P2, D1, D2, D3, D4, D5, D6)),
                  "no None leaks on any variant"))

# ---- review fixes: the feed's misspelling, the shared-currency count, one carry date ---------
cop_feed = next(r["name"] for r in RATES["rows"] if r["code"] == "COP")
results.append(ok(cop_feed == "Coombian Peso" and 'COP</span> Colombian Peso' in P["html"] and "Coombian" not in P["html"],
                  "the feed's \"Coombian Peso\" prints as Colombian Peso"))
counts_ok, seen_short = True, 0
for row in P["rows"]:
    n, k = len(row["priced"]), len(row["places"])
    if n < 2:
        continue
    want = ("%d places use the %s" % (n, row["code"]) if n >= k
            else "%d of the %d places using the %s have price data" % (n, k, row["code"]))
    seen_short += n < k
    counts_ok = counts_ok and want in P["html"]
eur = next(r for r in P["rows"] if r["code"] == "EUR")
results.append(ok(counts_ok and seen_short >= 1 and "%d places use the EUR" % len(eur["priced"]) not in P["html"],
                  "a shared currency's price tooltip counts the places with price data against all that use it "
                  "(EUR: %d of %d)" % (len(eur["priced"]), len(eur["places"]))))
# /cheapest's price figure (picks._score: price_level with now_y=None, today in UTC) and this page's for the
# same inputs and the same UTC day, for every single-place currency; and the day decides the carry.
from fxtracker import picks  # noqa: E402
utc_today = datetime.datetime.now(datetime.timezone.utc).date()
rate_by = {r["code"]: r["rate_now"] for r in RATES["rows"] if "code" in r and "rate_now" in r}
fit0 = pricelevel.plausibility_fit(PPP, rate_by, picks.CUR_BY_ISO)
anchor0 = picks._price_level("US", PPP, rate_by, fit0) or 1
cheap_pct = {iso: pricelevel.js_round(100 * pl / anchor0) for iso in picks.CUR_BY_ISO
             for pl in [picks._price_level(iso, PPP, rate_by, fit0)] if pl}
mine = RS.price_levels(RATES, PPP, utc_today.isoformat())
same_day = [iso for iso in cheap_pct if iso in mine and pricelevel.js_round(100 * mine[iso]) == cheap_pct[iso]]
results.append(ok(len(same_day) == len([i for i in cheap_pct if i in mine]) and len(same_day) > 100,
                  "carried to the same UTC day, every country's price matches /cheapest's (picks._score) figure "
                  "(%d countries)" % len(same_day)))
PD = RS.dollar_strength(RATES, PPP, IDX, today=TODAY, price_day=utc_today.isoformat())
single = [r for r in PD["rows"] if len(r["priced"]) == 1 and r["priced"][0][1] in cheap_pct]
results.append(ok(single and all('>%d%%</span>' % cheap_pct[r["priced"][0][1]] in PD["html"] for r in single),
                  "the page itself prints /cheapest's %% for its %d single-place currencies on that day" % len(single)))
later = (datetime.date.fromisoformat(TODAY) + datetime.timedelta(days=30)).isoformat()
lv30 = RS.price_levels(RATES, PPP, later)
ref30 = pricelevel.now_year(datetime.date.fromisoformat(later))
fit30 = pricelevel.plausibility_fit(PPP, rate_by, picks.CUR_BY_ISO, ref30)
us30 = pricelevel.price_level("US", PPP, rate_by, picks.CUR_BY_ISO, fit30, ref30)
results.append(ok(all(abs(lv30[i] - pricelevel.price_level(i, PPP, rate_by, picks.CUR_BY_ISO, fit30, ref30) / us30) < 1e-12
                      for i in ("BO", "MY", "TR", "JP")) and RS.price_levels(RATES, PPP) == RS.price_levels(RATES, PPP, TODAY),
                  "price_day sets the carry date (30 days on: the inflation carried that far); none given: the rates' date"))
results.append(ok(re.search(r'<td class="name" data-l="Currency"><span class="rk">1\.</span> ', P["html"]) is not None,
                  "the rank rides in the currency cell for phone and tablet cards"))
css = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
blk = css[css.index("/* /dollar-strength"):css.index("/* /cheapest */")]
results.append(ok(".listpage .dstable td.name { color: var(--ink); }" in blk and ".listpage .dstable .rk" in blk
                  and "@media (min-width: 1024px) { .listpage .dstable .rk { display: none; } }" in blk,
                  "CSS (in the /dollar-strength block): the currency cell is ink, not the site-wide .name gray; "
                  "the card rank hides from 1024px, where # shows"))

# ---- the server ------------------------------------------------------------------------------
import server  # noqa: E402

cfg = server.store.load_config()
key = (cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD")
now = time.time()
fetches = []
rates.get_history = lambda: fetches.append(1) or (_ for _ in ()).throw(RuntimeError("no network in tests"))
server._ppp_cache.update(at=now, data=PPP)
server._rates_cache[key] = (now, RATES)
rates._history["snap"] = (now, dates, cols)
try:
    a = server._strength_page()
    b = server._strength_page()
    page = a["bytes"].decode("utf-8")
    results.append(ok(not a["degraded"] and a is b and "<title>Where the US Dollar Is Strongest Now, Inflation-Adjusted</title>" in page
                      and '<link rel="canonical" href="https://wandergrade.com/dollar-strength">' in page
                      and "ECB reference rates</a> (index history since 1999)" in page and "<polyline" in page,
                      "server: the page from the caches (title, canonical, credits, the line); a repeat is the memo's object"))
    sm = server._sitemap().decode("utf-8")
    lines = sm.splitlines()
    i = next(n for n, l in enumerate(lines) if "/do-not-travel<" in l)
    results.append(ok("<loc>https://wandergrade.com/dollar-strength</loc><lastmod>2026-10-23</lastmod>" in lines[i + 1]
                      and sm.count("/dollar-strength<") == 1,
                      "sitemap: one /dollar-strength line, right after /do-not-travel, dated by the rates (2026-10-23)"))
    # An HTTP round trip: the route, the slash variant, deeper paths, HEAD.
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def get(path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        conn.request(method, path)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), body

    st, hd, body = get("/dollar-strength")
    results.append(ok(st == 200 and hd.get("Cache-Control") == "public, max-age=300" and b"<h1>Where the US dollar" in body,
                      "GET /dollar-strength: 200, public, max-age=300"))
    st, hd, body = get("/dollar-strength/?utm_source=x")
    results.append(ok(st == 301 and hd.get("Location") == "/dollar-strength?utm_source=x",
                      "the slash variant 301s to the one URL, query and all"))
    st, hd, body = get("/dollar-strength/eur")
    results.append(ok(st == 404, "a deeper path is the site's 404 (%d)" % st))
    st, hd, body = get("/dollar-strength", "HEAD")
    results.append(ok(st == 200 and body == b"" and hd.get("Cache-Control") == "public, max-age=300", "HEAD: 200, no body"))
    # Index history missing: degraded and no-store; the history refresh is
    # asked for off the request path (here it fails at once, with no network).
    rates._history["snap"] = (0.0, [], {})
    server._strength_warm.update(busy=False, at=0.0)
    st, hd, body = get("/dollar-strength")
    for _ in range(50):
        if fetches:
            break
        time.sleep(0.05)
    results.append(ok(st == 200 and hd.get("Cache-Control") == "no-store"
                      and b"The overall dollar index isn't loaded right now" in body and fetches,
                      "no index history: 200, no-store, says so, and a background refresh is asked for"))
    n = len(fetches)
    get("/dollar-strength")
    results.append(ok(len(fetches) == n, "the refresh is asked for at most once a minute"))
    # A history older than HISTORY_STALE counts as not cached.
    rates._history["snap"] = (time.time() - rates.HISTORY_STALE - 5, dates, cols)
    results.append(ok(server._strength_history() is None, "a history past HISTORY_STALE is not served"))
    rates._history["snap"] = (time.time(), dates, cols)
    server._rates_cache.clear()
    st, hd, body = get("/dollar-strength")
    results.append(ok(st == 200 and hd.get("Cache-Control") == "no-store" and b"<table" not in body
                      and b"The exchange rates aren" in body, "no cached rates: 200, no-store, the table left out"))
    sm = server._sitemap().decode("utf-8")
    stamp = open(os.path.join(ROOT, "public", "content-stamp.txt")).read().strip()[:10]
    results.append(ok("<loc>https://wandergrade.com/dollar-strength</loc><lastmod>%s</lastmod>" % stamp in sm,
                      "no cached rates: the sitemap date falls back to the content stamp (%s), never today" % stamp))
    httpd.shutdown()
finally:
    rates.get_history = real_get

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
