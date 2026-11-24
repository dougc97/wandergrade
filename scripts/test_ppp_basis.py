"""Which price comparison each country's figure is on (fxtracker/build_ppp.py,
build_pl_history.py), offline: no network.

    /usr/bin/python3 scripts/test_ppp_basis.py

What it holds the code and data to (review 2026-11-23 items 15 and 23):
  * pick_basis: the household-consumption factor (PA.NUS.PRVT.PP) where its
    newest year is at most HOUSEHOLD_MAX_LAG behind the GDP-wide one, the
    GDP-wide factor (PA.NUS.PPP) flagged "basis": "gdp" otherwise, and the
    household one where there is no GDP-wide figure at all;
  * build() asks for both factors, flags the fallback, and adds MANUAL rows
    without ever overriding a World Bank row; manual_overdue names a row
    past its refresh_by (the dated reminder);
  * the committed ppp.json: household for the rich, high-investment places
    the GDP basis read cheap (Singapore, Qatar, Brunei, Macau), the GDP-wide
    fallback flagged for the countries stuck on the 2021 benchmark
    (Argentina, Aruba, Puerto Rico...); Taiwan's IMF row as entered;
  * Taiwan's hand-entered figures are not past refresh_by — this fails once
    a newer IMF World Economic Outlook is out (the dated reminder);
  * pl_history.json: each country's series on its map figure's basis — the
    fallback countries GDP-wide throughout, a household country's years
    without a household figure linked to the GDP-wide moves (no splice jump),
    the flagged years listed in "gdp";
  * the words: pricelevel.basis_note and app.js plBasisNote say the same
    thing; the guide's price ⓘ and the history chart's ⓘ carry them;
    /dollar-strength marks a flagged price ‡ with its note; the dataset says
    ppp_basis and ppp_source per row.
"""
import copy, datetime, html, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import build_dataset, build_pl_history, build_ppp, pricelevel  # noqa: E402
from fxtracker import render_strength as RS  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
J = lambda *p: json.load(open(os.path.join(ROOT, *p), encoding="utf-8"))
PPP = J("public", "ppp.json")
PLH = J("public", "pl_history.json")
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()

# ---- pick_basis ----------------------------------------------------------------
hh = {"SG": (2025, 0.9, "Singapore"), "QA": (2024, 2.7, "Qatar"), "XK": (2022, 0.4, "Kosovo"),
      "AR": (2021, 300.0, "Argentina"), "GU": (2021, 1.1, "Guam")}
gdp = {"SG": (2025, 0.8, "Singapore"), "QA": (2025, 2.0, "Qatar"), "XK": (2025, 0.36, "Kosovo"),
       "AR": (2025, 567.0, "Argentina"), "BR": (2025, 2.5, "Brazil")}
pb = build_ppp.pick_basis(hh, gdp)
results.append(ok(pb["SG"] == (2025, 0.9, "Singapore", None) and pb["QA"] == (2024, 2.7, "Qatar", None),
                  "household where it is current or %d year behind the GDP-wide figure (Singapore, Qatar)"
                  % build_ppp.HOUSEHOLD_MAX_LAG))
results.append(ok(pb["XK"][3] == "gdp" and pb["AR"] == (2025, 567.0, "Argentina", "gdp") and pb["BR"][3] == "gdp",
                  "GDP-wide, flagged, where household is older (Kosovo 2022, Argentina 2021) or missing (Brazil here)"))
results.append(ok(pb["GU"] == (2021, 1.1, "Guam", None), "household where there is no GDP-wide figure at all (Guam)"))

# ---- build(): both indicators, the flag, MANUAL -----------------------------------
asked = []


def fake(rows_by_ind):
    def f(url):
        ind = re.search(r"/indicator/([A-Z.]+)\?", url).group(1)
        asked.append(ind)
        return rows_by_ind.get(ind, [])
    return f


def row(iso, year, v, name=None):
    return {"country": {"id": iso, "value": name or iso}, "date": str(year), "value": v}


real_fetch = build_ppp._fetch
build_ppp._fetch = fake({
    "PA.NUS.PRVT.PP": [row("SG", 2025, 0.9), row("AR", 2021, 300.0), row("AR", 2020, 200.0)],
    "PA.NUS.PPP": [row("SG", 2025, 0.8), row("AR", 2025, 567.0), row("TW", 2025, 14.0, "Taiwan (WB)")],
    "NY.GDP.PCAP.CD": [row("SG", 2025, 90000.0)], "FP.CPI.TOTL.ZG": [row("SG", 2025, 1.0)]})
try:
    t = build_ppp.build()
finally:
    build_ppp._fetch = real_fetch
results.append(ok({"PA.NUS.PRVT.PP", "PA.NUS.PPP"} <= set(asked), "build() asks the World Bank for both factors"))
results.append(ok(t["SG"]["ppp"] == 0.9 and "basis" not in t["SG"] and t["AR"]["ppp"] == 567.0
                  and t["AR"]["basis"] == "gdp" and t["AR"]["year"] == 2025,
                  "the table: Singapore household (no flag), Argentina GDP-wide 2025 with basis gdp"))
results.append(ok(t["TW"]["ppp"] == 14.0 and "src" not in t["TW"],
                  "a MANUAL row never overrides the World Bank's own (were it ever to publish Taiwan)"))
FAKE_ROW = {"ppp": 13.0, "year": 2025, "name": "Taiwan", "basis": "gdp", "src": "imf",
            "src_note": "IMF World Economic Outlook, test", "refresh_by": "2027-05-15"}
real_manual = dict(build_ppp.MANUAL)
build_ppp.MANUAL.clear()
build_ppp.MANUAL["TW"] = FAKE_ROW
build_ppp._fetch = fake({"PA.NUS.PRVT.PP": [row("SG", 2025, 0.9)], "PA.NUS.PPP": [row("SG", 2025, 0.8)],
                         "NY.GDP.PCAP.CD": [row("SG", 2025, 90000.0)], "FP.CPI.TOTL.ZG": [row("SG", 2025, 1.0)]})
try:
    t = build_ppp.build()
    late = (build_ppp.manual_overdue(datetime.date(2027, 5, 16)), build_ppp.manual_overdue(datetime.date(2027, 5, 15)))
finally:
    build_ppp._fetch = real_fetch
    build_ppp.MANUAL.clear()
    build_ppp.MANUAL.update(real_manual)
results.append(ok(t["TW"] == {k: v for k, v in FAKE_ROW.items() if k != "refresh_by"},
                  "a MANUAL row joins the build as entered (refresh_by stays in the code)"))
results.append(ok(late == (["TW"], []), "manual_overdue fires the day after refresh_by and not before"))

# ---- the committed tables --------------------------------------------------------
results.append(ok(all(r.get("basis") in (None, "gdp") for r in PPP.values()),
                  "ppp.json rows are household (no basis) or basis gdp, nothing else"))
fallback = {"AR", "AW", "PR", "BB", "CW", "FO", "GL", "MM", "SZ", "ZW", "XK", "SD", "KN", "FM"}
results.append(ok(all(PPP[i].get("basis") == "gdp" for i in fallback),
                  "the GDP-wide fallback is flagged where the household figure stops at 2021-2023 "
                  "(Argentina, Aruba, Puerto Rico, Kosovo...)"))
results.append(ok(all(not PPP[i].get("basis") for i in ("SG", "QA", "BN", "MO", "US", "VN", "TH", "FR")),
                  "Singapore, Qatar, Brunei, Macau and the rest are on household spending"))
n_hh = sum(1 for r in PPP.values() if not r.get("basis"))
results.append(ok(n_hh >= 170 and sum(1 for r in PPP.values() if r.get("basis")) <= 32,
                  "%d countries on household spending, %d on a fallback" % (n_hh, len(PPP) - n_hh)))
tw = PPP.get("TW") or {}
m = build_ppp.MANUAL["TW"]
results.append(ok(tw.get("ppp") == 13.655061 and tw.get("year") == 2025 and tw.get("src") == "imf"
                  and tw.get("basis") == "gdp" and tw.get("infl") == 1.66 and tw.get("gdppc") == 39511.56
                  and tw.get("src_note") == "IMF World Economic Outlook, October 2026" and "refresh_by" not in tw
                  and tw == {k: v for k, v in m.items() if k != "refresh_by"},
                  "Taiwan: the IMF's October 2026 WEO figures as entered in MANUAL (PPPEX 13.655061, CPI 1.66%, "
                  "GDP/head $39,512), flagged imf and GDP-wide"))
overdue = build_ppp.manual_overdue()
results.append(ok(not overdue, "Taiwan's IMF figures are current (refresh_by %s)%s" % (
    m["refresh_by"], "" if not overdue else ": PAST DUE — enter the newest IMF World Economic Outlook figures "
                                            "in build_ppp.MANUAL and bump refresh_by")))

# ---- pl_history.json --------------------------------------------------------------
G = PLH.get("gdp") or {}
Y = PLH["years"]


def years_of(iso):
    return {y for a, b in G.get(iso, []) for y in range(a, b + 1)}


ar_years = {Y[i] for i, v in enumerate(PLH["pl"]["AR"]) if v is not None}
results.append(ok(ar_years and years_of("AR") == ar_years,
                  "a fallback country's history is GDP-wide throughout, every shown year flagged (Argentina)"))
results.append(ok("SG" not in G and "VN" in G and years_of("VN") == set(range(1990, 1995)),
                  "a household country flags only its years with no household figure (Vietnam 1990-1994; "
                  "Singapore none)"))
hh_ser = {2000: 10.0, 2001: 11.0}
gd_ser = {1998: 4.0, 1999: 5.0, 2000: 5.0, 2001: 5.5}
f, flagged = build_pl_history.factors({"ZZ": hh_ser}, {"ZZ": gd_ser})
results.append(ok(f["ZZ"] == {1998: 8.0, 1999: 10.0, 2000: 10.0, 2001: 11.0} and flagged["ZZ"] == [[1998, 1999]],
                  "factors(): years before the household series follow the GDP-wide moves, linked at 2000 "
                  "(no splice jump), flagged 1998-1999"))
f, flagged = build_pl_history.factors({"ZZ": {2021: 3.0}}, {"ZZ": {2021: 2.0, 2025: 2.4}})
results.append(ok(f["ZZ"] == {2021: 2.0, 2025: 2.4} and flagged["ZZ"] == [[2021, 2021], [2025, 2025]],
                  "factors(): a fallback country (household stops 4 years early) is GDP-wide in every year"))
results.append(ok("PA.NUS.PRVT.PP" in PLH.get("source", ""), "pl_history.json names the household factor as its source"))

# ---- the words, in both languages ------------------------------------------------
gdp_txt = pricelevel.basis_note("AR", PPP)
imf_txt = pricelevel.basis_note("TW", PPP)
results.append(ok(gdp_txt == "GDP-wide figure: the World Bank has no recent household-spending one for it."
                  and imf_txt == "IMF figure (IMF World Economic Outlook, October 2026), GDP-wide: the World Bank "
                                 "doesn't cover it." and pricelevel.basis_note("SG", PPP) == "",
                  "basis_note: GDP-wide (Argentina), IMF (Taiwan), nothing for household (Singapore)"))
results.append(ok('if (e.basis === "gdp") return "%s";' % gdp_txt in APP
                  and "return `IMF figure (${e.src_note || \"World Economic Outlook\"}), GDP-wide: the World Bank "
                      "doesn't cover it.`;" in APP,
                  "app.js plBasisNote says exactly what pricelevel.basis_note says"))
gc = APP[APP.index("async function renderGuideCost"):APP.index("// ---- Travel Guide: \"Where to stay\"")]
results.append(ok(gc.count("plBasisNote(iso)") == 4, "both guide price ⓘ tips (live and snapshot) carry plBasisNote"))
results.append(ok("colBasisNote(colIso)" in APP and "plHist.gdp" in APP,
                  "the Cost over time ⓘ names the GDP-wide years (colBasisNote)"))

# /dollar-strength: a flagged single-country price is marked ‡ and footnoted.
SF = os.path.join(ROOT, "scripts", "fixtures", "strength")
rates_p = json.load(open(os.path.join(SF, "rates_2026-10-23.json"), encoding="utf-8"))
sppp = copy.deepcopy(json.load(open(os.path.join(SF, "ppp_2026-10-23.json"), encoding="utf-8")))
sppp["BO"]["basis"] = "gdp"
page = RS.dollar_strength(rates_p, sppp, None, today="2026-10-23")["html"]
bob = re.search(r'<tr>(?:(?!</tr>).)*<span class="dscode">BOB</span>.*?</tr>', page, re.S)
results.append(ok(bool(bob) and '<sup class="fn">‡</sup>' in bob.group(0) and gdp_txt in bob.group(0)
                  and RS.BASIS_NOTE in page,
                  "/dollar-strength: a GDP-wide price (Bolivia, flagged here) is marked ‡, its title says why, "
                  "the note explains"))
plain = RS.dollar_strength(rates_p, json.load(open(os.path.join(SF, "ppp_2026-10-23.json"), encoding="utf-8")), None,
                           today="2026-10-23")["html"]
results.append(ok("‡" not in plain, "/dollar-strength: no ‡ and no note when no priced country is flagged"))
tppp = json.load(open(os.path.join(SF, "ppp_2026-10-23.json"), encoding="utf-8"))
tppp["TW"] = {k: v for k, v in build_ppp.MANUAL["TW"].items() if k != "refresh_by"}
tpage = RS.dollar_strength(rates_p, tppp, None, today="2026-10-23")["html"]
twd = re.search(r'<tr>(?:(?!</tr>).)*<span class="dscode">TWD</span>.*?</tr>', tpage, re.S)
results.append(ok(bool(twd) and re.search(r"\d+%</span><sup class=\"fn\">‡</sup>", twd.group(0)) is not None
                  and html.escape(imf_txt, quote=True) in twd.group(0) and "Taiwan's is the IMF's" in tpage
                  and "vs the US ~3%/yr (IMF)." in twd.group(0) and "(World Bank)" not in twd.group(0)
                  and "Inflation and PPP: World Bank (Taiwan: IMF)." in tpage
                  and "Inflation and PPP: World Bank." in plain,
                  "/dollar-strength: Taiwan's row gets a price (it had none), marked ‡ with the IMF source, and "
                  "its inflation is credited to the IMF"))
results.append(ok("(${gap}, ${inflSource(fxIso)})" in APP and '" (" + inflSource(iso) + ")."' in APP
                  and 'src === "imf" ? "IMF" : "World Bank"' in APP and pricelevel.infl_source("TW", PPP) == "IMF"
                  and pricelevel.infl_source("VN", PPP) == "World Bank",
                  "app.js's inflation tips credit the IMF for Taiwan (inflSource), as infl_source does"))

# The dataset: per-row basis and source, the meta naming both factors and the IMF.
real_fav = build_dataset.rates.compute_favorability
build_dataset.rates.compute_favorability = lambda: {"as_of": rates_p.get("as_of"), "rows": rates_p["rows"]}
try:
    ds = build_dataset.build(PPP)
finally:
    build_dataset.rates.compute_favorability = real_fav
by = {r["iso"]: r for r in ds["countries"]}
results.append(ok(build_dataset.FIELDS[-2:] == ["ppp_basis", "ppp_source"]
                  and by.get("VN", {}).get("ppp_basis") == "household" and by["VN"]["ppp_source"] == "World Bank"
                  and (by.get("AR") is None or by["AR"]["ppp_basis"] == "gdp")
                  and by.get("TW", {}).get("ppp_source") == "IMF" and by["TW"]["ppp_basis"] == "gdp"
                  and "PA.NUS.PRVT.PP" in ds["meta"]["ppp_source"] and "PA.NUS.PPP" in ds["meta"]["ppp_source"]
                  and "IMF" in ds["meta"]["ppp_source"] and "IMF" in ds["meta"]["licence"],
                  "dataset: ppp_basis and ppp_source on the end of every row (Taiwan: IMF, gdp); the meta names "
                  "PRVT.PP, PPP and the IMF"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
