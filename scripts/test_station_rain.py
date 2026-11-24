"""Rain against each place's own station records (fxtracker/build_climate.py
RAIN_REF and STATION_RAIN, 2026-11-24), offline: no network.

    /usr/bin/python3 scripts/test_station_rain.py

What it holds the data to:
  * every STATION_RAIN entry is cited: the station, the normal period (or a
    label saying what the figures are), where it is, the agency the
    Wikipedia climate box cites, the page, why it replaced the reanalysis's
    rain, twelve months of mm, and either twelve months of days or None with
    the station's day rule saying why (days only where counted at 1 mm);
  * climate.json carries exactly that rain on those rows (whole mm and days,
    rounded half up), names it ("rain_src" = station_label), and its scores
    and best months are what the build's own code makes of it: running the
    offline path (with_station_rain) on the committed row gives the same row
    back, and best = best_months(scores);
  * no other row claims a station source; RAIN_REF and STATION_RAIN don't
    overlap, and together cover every month-table row, each RAIN_REF entry
    naming its station, period and source;
  * the corrected rows' yearly totals sit within RAIN_RATIO (1.5) of their
    station's, and so does every row that kept Open-Meteo's rain (the rule
    that put a row in STATION_RAIN);
  * the temperature behind each score is recovered faithfully: for known
    temperatures and rain, _temp_for gives back a temperature that rescores
    within a point of the true one with any other rain (within half a
    degree's points where the score was clamped at 0 or 100, which pins only
    the rounded °C);
  * the guide's month table quotes the source for every station row.
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import build_climate as bc, render_guide as rg  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
CLIM = json.load(open(os.path.join(ROOT, "public", "climate.json"), encoding="utf-8"))
ST, REF = bc.STATION_RAIN, bc.RAIN_REF
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0


def table_eligible(row):
    cols = [row.get(k) or [] for k in ("scores", "temps", "rain_mm")]
    days = row.get("rain_days")
    return (all(len(x) == 12 and None not in x for x in cols) and len(set(cols[0])) >= 2
            and (days is None or (len(days) == 12 and None not in days)))


ELIGIBLE = sorted(i for i, r in CLIM.items() if table_eligible(r))

# --- the citations -----------------------------------------------------------------------
bad = []
for iso, st in sorted(ST.items()):
    words = all(isinstance(st.get(k), str) and st[k].strip() for k in ("station", "where", "agency", "why", "days_rule"))
    period = bool(re.match(r"^\d{4}–\d{4}$", st.get("period") or "")) or (st.get("period") == "" and "period" in st["agency"])
    page = (st.get("page") or "").startswith("en.wikipedia.org/wiki/")
    mm = isinstance(st.get("mm"), list) and len(st["mm"]) == 12 and all(num(x) for x in st["mm"])
    days = (st.get("days") is None and st["days_rule"] != "≥1.0 mm") or (
        isinstance(st["days"], list) and len(st["days"]) == 12 and all(num(x) for x in st["days"])
        and ("1 mm" in st["days_rule"] or "1.0 mm" in st["days_rule"]))
    if not (words and period and page and mm and days and (iso in bc.SAMPLE_POINTS or iso in bc.LEFT_ALONE)):
        bad.append(iso)
results.append(ok(len(ST) >= 20 and not bad,
                  "all %d STATION_RAIN entries cite station, period, place, agency, page and why, with 12 months of mm "
                  "and either 12 months of days counted at 1 mm or none%s" % (len(ST), (": " + " ".join(bad)) if bad else "")))
results.append(ok({"BT", "EC", "NP", "PE", "CR"} <= set(ST) and ST["BT"]["station"] == "Paro"
                  and ST["EC"]["station"] == "Quito",
                  "the review's cases are in it: Paro, Quito, Kathmandu, Cusco, Costa Rica"))

# --- what climate.json carries ----------------------------------------------------------
wrong, drift, notbest = [], [], []
for iso, st in sorted(ST.items()):
    row = CLIM.get(iso) or {}
    mm, days = bc.station_series(st)
    if (row.get("rain_src") != bc.station_label(st) or row.get("rain_mm") != mm or row.get("rain_days") != days):
        wrong.append(iso)
        continue
    if bc.with_station_rain(iso, row) != row:
        drift.append(iso)
    if row.get("best") != bc.best_months(row["scores"], iso):
        notbest.append(iso)
results.append(ok(not wrong, "every STATION_RAIN row carries the station's rain (whole mm, days or none) and names it%s"
                  % ((": " + " ".join(wrong)) if wrong else "")))
results.append(ok(not drift and not notbest,
                  "their scores and best months are the build's own (the offline path gives each committed row back)%s"
                  % ((": " + " ".join(drift + notbest)) if drift or notbest else "")))
loose = [i for i in ST if any(abs(s - bc.comfort(t, r)) > bc.REVISION_SCORE
                              for s, t, r in zip(CLIM[i]["scores"], CLIM[i]["temps"], CLIM[i]["rain_mm"]))]
results.append(ok(not loose, "each station row's score is comfort() of its own month (°C rounded: within %d points)%s"
                  % (bc.REVISION_SCORE, (": " + " ".join(loose)) if loose else "")))
claim = sorted(i for i, r in CLIM.items() if r.get("rain_src") and i not in ST)
results.append(ok(not claim, "no other row claims a station source%s" % ((": " + " ".join(claim)) if claim else "")))

# --- the references and the 1.5x rule ---------------------------------------------------
both = sorted(set(ST) & set(REF))
uncovered = [i for i in ELIGIBLE if i not in ST and i not in REF]
badref = [i for i, v in REF.items() if not (isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], int) and v[0] > 0
                                            and isinstance(v[1], str) and v[1].count(",") >= 2)]
results.append(ok(not both and not uncovered and not badref and len(ELIGIBLE) >= 186,
                  "RAIN_REF (%d) and STATION_RAIN (%d) don't overlap and cover all %d month-table rows, each reference "
                  "naming station, period and source%s" % (len(REF), len(ST), len(ELIGIBLE),
                                                            (": " + " ".join(both + uncovered + badref))
                                                            if both or uncovered or badref else "")))
ratios = {i: bc.rain_ratio(i, CLIM[i]) for i in ELIGIBLE}
out = sorted(i for i, r in ratios.items() if r is None or not 1 / bc.RAIN_RATIO <= r <= bc.RAIN_RATIO)
results.append(ok(not out and all(abs(ratios[i] - 1) < 0.01 for i in ST),
                  "every month-table row's yearly rain is within %g times its station's either way; the %d corrected "
                  "rows match theirs (Paro %d mm, Quito %d, Kathmandu %d, Cusco %d)%s"
                  % (bc.RAIN_RATIO, len(ST), sum(CLIM["BT"]["rain_mm"]), sum(CLIM["EC"]["rain_mm"]),
                     sum(CLIM["NP"]["rain_mm"]), sum(CLIM["PE"]["rain_mm"]), (": " + " ".join(out)) if out else "")))
results.append(ok(all(not [w for w in bc.point_warnings(CLIM[i], i) if "rain" in w] for i in ELIGIBLE),
                  "the build warns about no row's rain"))

# --- recovering the temperature behind a score ------------------------------------------
worst, worst_clamped = 0, 0
for t10 in range(-50, 400, 7):            # -5.0 .. 39.9 °C
    t = t10 / 10 + 0.03
    for r in (0, 3, 40, 151, 333):
        s = bc.comfort(t, r + 0.3)        # Open-Meteo's rain, stored rounded to r
        back = bc._temp_for(s, round(t), r)
        for r2 in (0, 25, 90, 400):
            d = abs(bc.comfort(back, r2) - bc.comfort(t, r2))
            if s in (0, 100):
                worst_clamped = max(worst_clamped, d)
            else:
                worst = max(worst, d)
half_degree = max(bc.HOT_PTS_PER_C, bc.COLD_PTS_PER_C) / 2
results.append(ok(worst <= 1 and worst_clamped <= half_degree,
                  "a temperature recovered from a rounded row rescores within %d point of the true one; from a score "
                  "clamped at 0 or 100 (the row pins only the rounded °C) within %d (half a degree's points; of the "
                  "corrected rows only Iceland's January was clamped, at 0)" % (worst, worst_clamped)))

# --- the guide quotes it ------------------------------------------------------------------
caps = {i: re.search(r"<caption>(.*?)</caption>", rg.month_table(i)).group(1) for i in ST if rg.month_table(i)}
miss = [i for i in ST if not caps.get(i, "").endswith("; rain: " + bc.station_label(ST[i]).replace("'", "&#x27;"))]
results.append(ok(not miss and len(caps) == len(ST),
                  "every station row's month table names its rain source (Paro: %s)%s"
                  % (caps.get("BT"), (": " + " ".join(miss)) if miss else "")))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
