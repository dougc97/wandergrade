#!/usr/bin/env python3
"""Precompute PPP conversion factors per country -> public/ppp.json (World Bank,
free, no key). One call per indicator covers all countries.

The website combines this annual figure with the live exchange rate to derive a
"price level vs the US" (affordability): price_level = ppp_factor / market_rate.
Below ~1 means the country is cheaper than the US for a dollar holder.

The factor is the household-consumption one (PA.NUS.PRVT.PP): what the site's
tips describe, a local basket of what residents buy against the same basket
in the US. The GDP-wide factor (PA.NUS.PPP), which the site used until
2026-11, prices investment and government spending too, and so made rich,
high-investment places read cheap: Singapore 60% of US prices (78% on
household spending), Qatar 55% (73%), Macau 53% "very cheap" (59%). Where a country
has no household figure within HOUSEHOLD_MAX_LAG years of its GDP-wide one
(25 stop at the 2021-2023 benchmarks: Argentina, Aruba, Puerto Rico...), its
last household figure is carried forward along the GDP-wide one, flagged
"basis": "gdp" with "hh_year" (review 2026-11-23 item 15). Taiwan, which the
World Bank doesn't cover, comes from MANUAL (item 23): the IMF's GDP-wide
figure put on the household footing with Taiwan's own household/GDP price
ratio from the Penn World Table, so it counts as household spending too.

Run: python3 -m fxtracker.build_ppp
     python3 -m fxtracker.build_ppp --manual-only   # offline: re-join MANUAL
       rows (e.g. a new IMF release) to the committed file, every World Bank
       row left exactly as it is
"""

import json
import os
import sys
import time
import urllib.request

from . import rates  # reuse the verifying SSL context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "ppp.json")
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
# PA.NUS.PRVT.PP = PPP conversion factor, private consumption (local currency
# units per international $); PA.NUS.PPP = the same over all of GDP, the
# fallback. The end year was hardcoded to 2025, which would have silently
# ignored 2026 data the moment the World Bank published it. Ask for next year
# too — absent years simply come back null and are skipped.
_THIS_YEAR = time.gmtime().tm_year
URL = ("https://api.worldbank.org/v2/country/all/indicator/PA.NUS.PRVT.PP"
       "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
GDP_PPP_URL = ("https://api.worldbank.org/v2/country/all/indicator/PA.NUS.PPP"
               "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# A household figure counts when it is at most this many years older than the
# country's GDP-wide one. Older, and it is carried forward along the GDP-wide
# figure (flagged, pick_basis): the carry-forward for inflation stops at
# MAX_CARRY_YEARS (pricelevel.py), so a 2021 household factor would
# under-state four years of local inflation, and a figure the World Bank
# stopped extrapolating is a stale one. Qatar, Gambia and Equatorial Guinea
# (household 2024, GDP 2025) pass; Kosovo, Sudan, Micronesia (2022) and
# St Kitts (2023) don't.
HOUSEHOLD_MAX_LAG = 1
# Why not the raw GDP-wide figure for those: it reads 2-29% under the
# household one (household / GDP-wide in each fallback country's last year
# with both: Argentina 1.11, Aruba 1.11, Puerto Rico 1.12, Myanmar 1.22,
# Zimbabwe 1.19, Sudan 1.29; Nauru and Tuvalu read higher, 0.81 and 0.89), so
# those countries ranked cheaper than their peers on the household basis.
# Linked at the last year with both, the figure is the household level moved
# by the GDP-wide figure's own change since, as pl_history links a household
# country's missing years: the map's figure and the history's latest year
# are the same number.
#
# Household figures after a year are left out where they stop describing the
# places visitors go; the country then takes that same carried-forward
# figure, from the last year kept.
HOUSEHOLD_UNTIL = {
    # West Bank & Gaza: the household factor went 0.535 (2023) -> 0.791
    # (2024) -> 0.907 (2025) while the GDP-wide one held at 0.58-0.63, which
    # read Palestine at 98% of US prices (69% on the GDP-wide figure):
    # wartime prices in Gaza, not the West Bank towns the guide is about (its
    # weather is Bethlehem's). Review of batch B, 2026-11-24.
    "PS": 2023,
}
# Hand-entered rows for places the World Bank doesn't cover, each with its
# source ("src", "src_note") and the date the next release is out
# ("refresh_by"). They join every build (the committed file and the server's
# monthly live refresh alike) unless the World Bank ever publishes the
# country itself, shaped by manual_row().
# Taiwan (review 2026-11-23 item 23): the IMF's World Economic Outlook,
# October 2026 (published 2026-10-13), from the IMF's SDMX API
# (api.imf.org, dataset IMF.RES:WEO, series TWN.PPPEX.A, TWN.PCPIPCH.A,
# TWN.NGDPDPC.A; 2025 is the latest actual year): PPPEX 13.655061 NT$ per
# international $ ("ppp_gdp") — GDP-wide, as the IMF publishes no household
# factor — consumer-price inflation 1.657958%, GDP per head US$39,511.56.
# Refresh after each April and October WEO; `refresh_by` is when the next one
# is out and scripts/test_ppp_basis.py fails after it.
# The GDP-wide figure read Taiwan a little cheap next to every other country
# (household spending since item 15), so manual_row() scales it by Taiwan's
# own household / GDP price-level ratio ("hh_ratio"): the Penn World Table
# (Groningen Growth and Development Centre), release 11.0, through FRED's
# copies of its series (PLCCPPTWA670NRUG = pl_c, household consumption;
# PLGDPOTWA670NRUG = pl_gdpo, output-side GDP; and the same two for the US,
# fetched 2026-11-24). PWT states both against the US GDP price level, so
# Taiwan's pl_c / pl_gdpo is divided by the US's own (the World Bank's
# factors are each against the same US aggregate) and averaged over the last
# three years it has, for stability:
#   2021  TW 0.5430 / 0.5575, US 0.9651 / 1.0000 -> 1.0092
#   2022  TW 0.5242 / 0.5291, US 1.0264 / 1.0714 -> 1.0340
#   2023  TW 0.5130 / 0.5213, US 1.0672 / 1.1097 -> 1.0233   mean 1.0221
# Sanity check, World Bank household / GDP-wide factor (PA.NUS.PRVT.PP /
# PA.NUS.PPP), 2021-2023 mean: Hong Kong 1.079, Japan 1.084, Korea 1.121,
# Singapore 1.269 (median 1.10). Taiwan's 1.022 sits just under its peers,
# so the scaling, if anything, under-corrects. Refresh hh_ratio with a new
# PWT release (hh_version) — not on the IMF's timetable.
MANUAL = {
    "TW": {"ppp_gdp": 13.655061, "year": 2025, "name": "Taiwan", "src": "imf",
           "src_note": "World Economic Outlook, October 2026",
           "hh_ratio": 1.0221, "hh_src": "Penn World Table", "hh_version": "11.0",
           "hh_years": [2021, 2022, 2023],
           "gdppc": 39511.56, "gdppc_year": 2025, "infl": 1.66, "infl_year": 2025,
           "refresh_by": "2027-05-15"},
}


def manual_row(iso):
    """MANUAL[iso] as it joins the table: refresh_by stays in the code, and a
    GDP-wide figure with a household / GDP ratio ("ppp_gdp" x "hh_ratio")
    becomes the household-equivalent "ppp", with no "basis" flag: every
    reader treats it as household spending, and pricelevel.basis_note says
    how it was estimated. A row entered as a plain "ppp" joins as entered."""
    row = {k: v for k, v in MANUAL[iso].items() if k != "refresh_by"}
    if row.get("ppp_gdp") and row.get("hh_ratio"):
        row["ppp"] = round(row["ppp_gdp"] * row["hh_ratio"], 6)
    return row


# GDP per capita in current US$. Not used for the grade — only to sanity-check the
# price level. Price level tracks income log-linearly (the Penn effect), so a
# country whose price level is wildly out of line with its income is almost always
# a broken exchange rate rather than a genuinely expensive place. Sudan is the
# live example: the official rate is pegged near 602 SDG/USD while the currency
# really trades far weaker, which made the site rank Sudan the most expensive
# country on earth, ahead of Iceland and Switzerland.
GDP_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD"
           "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# Consumer-price inflation, annual %. The PPP factor is a year-old snapshot of
# local prices; dividing it by TODAY's rate with no inflation carry-forward read
# Turkey (CPI ~35%) as far cheaper than it is. pricelevel.py and app.js carry the
# factor forward with this, and use it to turn nominal FX moves into real ones.
# World Bank only: IMF DataMapper is bot-walled.
CPI_URL = ("https://api.worldbank.org/v2/country/all/indicator/FP.CPI.TOTL.ZG"
           "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
# GDP in local currency and in US$. Where the two are identical the World Bank's
# "local currency" is the US dollar, so the PPP factor is USD per international
# $ (West Bank & Gaza, Liberia) — build-time check only, see _warn_usd_units().
GDP_LCU_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CN"
               "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))
GDP_USD_URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD"
               "?format=json&date=2017:%d&per_page=20000" % (_THIS_YEAR + 1))


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fx-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=40, context=rates._SSL) as resp:
        raw = resp.read().decode("utf-8-sig")
    return json.loads(raw)[1] or []


def _latest_by_iso(rows, valid):
    """Newest non-null value per country. The World Bank publishes with a lag and
    not every country lands in the same year, so we keep the latest PER COUNTRY."""
    latest = {}  # iso -> (year, value, name)
    for r in rows:
        iso = r["country"]["id"]
        val = r["value"]
        if val is None or len(iso) != 2 or not iso.isalpha() or iso not in valid:
            continue
        year = int(r["date"])
        if iso not in latest or year > latest[iso][0]:
            latest[iso] = (year, val, r["country"]["value"])
    return latest


def _carry_over(out, previous, fields):
    """Copy `fields` for every country from the previous table (same shape as
    ppp.json). Used when a secondary fetch fails outright."""
    n = 0
    for iso, e in out.items():
        old = (previous or {}).get(iso) or {}
        if all(old.get(f) is not None for f in fields):
            e.update({f: old[f] for f in fields})
            n += 1
    return n


def _secondary(url, what, out, valid, previous, fields, digits, fallback_msg):
    """Merge one optional World Bank indicator into `out` as fields[0] (value)
    and fields[1] (year). It must never fail the PPP build. When the fetch fails
    (or comes back empty), the previous table's figures are kept per country:
    dropping them silently switched the inflation carry-forward and real FX off
    site-wide for the 30 days until the next refresh (Turkey back to pl 0.33)."""
    try:
        got = _latest_by_iso(_fetch(url), valid)
        if not got:
            raise ValueError("empty response")
        for iso, (y, v, _nm) in got.items():
            if iso in out:
                out[iso][fields[0]] = round(v, digits)
                out[iso][fields[1]] = y
    except Exception as e:
        kept = _carry_over(out, previous, fields)
        print("WARNING: {0} fetch failed ({1}). {2}".format(
            what, e, "Kept the previous figures for %d countries." % kept if kept
            else fallback_msg))


def _series_by_iso(rows, valid):
    """({iso: {year: value}}, {iso: name}) for the countries on the map."""
    series, names = {}, {}
    for r in rows:
        iso, val = r["country"]["id"], r["value"]
        if val is None or len(iso) != 2 or not iso.isalpha() or iso not in valid:
            continue
        series.setdefault(iso, {})[int(r["date"])] = val
        names.setdefault(iso, r["country"]["value"])
    return series, names


def household_kept(iso, series):
    """A country's household-factor years, less those HOUSEHOLD_UNTIL leaves
    out."""
    cut = HOUSEHOLD_UNTIL.get(iso)
    return {y: v for y, v in (series or {}).items() if cut is None or y <= cut}


def pick_basis(household, gdp):
    """{iso: (year, value, basis, hh_year)} from the two factors' yearly
    figures ({iso: {year: value}}):
      * the newest household figure, where it is no more than
        HOUSEHOLD_MAX_LAG years older than the newest GDP-wide one (basis
        None, hh_year None);
      * else the newest GDP-wide figure times household / GDP-wide in the
        last year with both: the household level carried forward along the
        GDP-wide figure (basis "gdp", hh_year that last year);
      * the GDP-wide figure itself (basis "gdp", hh_year None) only where
        the two never share a year.
    HOUSEHOLD_UNTIL's years count as missing."""
    out = {}
    for iso in set(household) | set(gdp):
        h, g = household_kept(iso, household.get(iso)), gdp.get(iso) or {}
        hy, gy = (max(h) if h else None), (max(g) if g else None)
        if h and (gy is None or hy >= gy - HOUSEHOLD_MAX_LAG):
            out[iso] = (hy, h[hy], None, None)
        elif g:
            both = [y for y in h if g.get(y)]
            if both:
                at = max(both)
                out[iso] = (gy, g[gy] * h[at] / g[at], "gdp", at)
            else:
                out[iso] = (gy, g[gy], "gdp", None)
    return out


def build(previous=None):
    """Fetch and shape the PPP table: {iso: {ppp, year, name, basis, hh_year,
    gdppc, gdppc_year, infl, infl_year}} (basis and hh_year only on the
    fallback, pick_basis; the last four only when the World Bank has them).
    MANUAL rows join last.

    Shared by main() (writes the committed file) and the server's live refresh,
    so both paths can never disagree about how the data is derived. Keeps the
    latest available year PER COUNTRY — the World Bank publishes with a lag and
    not every country lands in the same year.

    `previous` (a table in the same shape, e.g. the one being replaced) backs
    the income and inflation fields when their own fetch fails.
    """
    # Only keep real countries that exist on our map.
    with open(GEOJSON, encoding="utf-8") as f:
        valid = {feat["properties"]["iso"] for feat in json.load(f)["features"]
                 if feat["properties"].get("iso") and feat["properties"]["iso"] != "-99"}

    hh, hh_names = _series_by_iso(_fetch(URL), valid)
    gdp, gdp_names = _series_by_iso(_fetch(GDP_PPP_URL), valid)
    out = {}
    for iso, (y, v, b, hy) in pick_basis(hh, gdp).items():
        out[iso] = {"ppp": round(v, 6), "year": y, "name": hh_names.get(iso) or gdp_names.get(iso)}
        if b:
            out[iso]["basis"] = b
        if hy is not None:
            out[iso]["hh_year"] = hy

    # Income is a cross-check, not an input to the grade. With neither a fetch
    # nor a previous figure, entries carry no gdppc and the client falls back
    # to its absolute plausibility bounds.
    _secondary(GDP_URL, "GDP per capita", out, valid, previous, ("gdppc", "gdppc_year"), 2,
               "Price-level plausibility check will fall back to absolute bounds.")
    # Same rule for inflation: without it the price level simply isn't carried
    # forward (factor 1), which is what the site did before this existed.
    _secondary(CPI_URL, "inflation", out, valid, previous, ("infl", "infl_year"), 2,
               "Price levels will not be carried forward for inflation.")
    for iso in MANUAL:
        if iso in valid and iso not in out:
            out[iso] = manual_row(iso)
    return out


def manual_overdue(today=None):
    """MANUAL rows past their refresh_by date (a newer IMF release is out)."""
    import datetime
    d = (today or datetime.date.today()).isoformat()
    return sorted(iso for iso, r in MANUAL.items() if r.get("refresh_by", "9999") < d)


def _warn_usd_units(out):
    """Flag countries whose World Bank local currency is the US dollar but which
    pricelevel.PPP_UNIT doesn't know about — their PPP factor would otherwise be
    divided by a local rate it isn't quoted in (Palestine published 3x too cheap,
    Liberia dropped). Warn only: it runs at commit time, never in the live refresh."""
    from .pricelevel import PPP_UNIT
    from .picks import CUR_BY_ISO
    def same_year(rows):   # the value for the PPP factor's own data year
        return {r["country"]["id"]: r["value"] for r in rows if r["value"] is not None
                and r["date"] == str(out.get(r["country"]["id"], {}).get("year"))}
    try:
        lcu, usd = same_year(_fetch(GDP_LCU_URL)), same_year(_fetch(GDP_USD_URL))
    except Exception as e:
        print("WARNING: PPP unit check skipped ({0}).".format(e))
        return
    for iso in sorted(out):
        a, b = lcu.get(iso), usd.get(iso)
        if not a or not b or abs(a / b - 1) > 1e-6:
            continue
        unit = PPP_UNIT.get(iso) or CUR_BY_ISO.get(iso)
        # Ungraded (no currency mapping) or pegged 1:1 to the dollar: harmless.
        if unit in (None, "USD", "BSD", "BMD", "PAB"):
            continue
        print("WARNING: {0}'s PPP factor is quoted in US dollars (GDP in local currency == "
                  "GDP in US$) but it is divided by {1}; add it to pricelevel.PPP_UNIT and "
                  "app.js PPP_UNIT.".format(iso, unit))


def committed():
    """The ppp.json checked into the repo — the fallback when the API is down."""
    with open(OUT, encoding="utf-8") as f:
        return json.load(f)


def apply_manual(table, valid=None):
    """`table` (ppp.json's shape) with the MANUAL rows joined again, as build()
    joins them: a hand-entered row ("src") is replaced and a missing one added
    (where `valid`, the map's countries, allows), and a World Bank row is never
    overridden. Offline, so a change to MANUAL can ship without the World
    Bank's latest revisions to every other country (main --manual-only)."""
    out = dict(table)
    for iso in MANUAL:
        if (out.get(iso) or {}).get("src") or (iso not in out and (valid is None or iso in valid)):
            out[iso] = manual_row(iso)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        prev = committed()
    except Exception:
        prev = None
    if "--manual-only" in argv:
        with open(GEOJSON, encoding="utf-8") as f:
            valid = {feat["properties"]["iso"] for feat in json.load(f)["features"]}
        out = apply_manual(prev or {}, valid)
    else:
        out = build(previous=prev)
        _warn_usd_units(out)
    for iso in manual_overdue():
        print("WARNING: {0}'s hand-entered figures ({1}) are past refresh_by {2}: enter the newest "
              "IMF World Economic Outlook figures in build_ppp.MANUAL.".format(
                  iso, "IMF " + MANUAL[iso]["src_note"], MANUAL[iso]["refresh_by"]))
    print("basis: {0} household, {1} carried forward along the GDP-wide figure ({2}), {3} hand-entered ({4})".format(
        sum(1 for r in out.values() if not r.get("basis")),
        sum(1 for r in out.values() if r.get("basis") == "gdp" and not r.get("src")),
        " ".join(sorted(i for i, r in out.items() if r.get("basis") == "gdp" and not r.get("src"))),
        sum(1 for r in out.values() if r.get("src")), " ".join(sorted(i for i, r in out.items() if r.get("src")))))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1}".format(len(out), OUT))


if __name__ == "__main__":
    main()
