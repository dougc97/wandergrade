"""Month-level hazards in public/activities.json ("hazards": [{months, note}]),
in-process, no network.

    /usr/bin/python3 scripts/test_activity_hazards.py

What it holds the data to:
  * every hazard names months 1-12 and a note, and no two of a country's
    hazards share a month: the guide chart keeps one note per month
    (app.js renderCountryClimate's hzByMonth), so an overlap would hide one;
  * winter air pollution is flagged where a best-weather month would
    otherwise hide it (review 2026-11-23 item 26): Delhi scores 99 for
    weather in November. India and Pakistan Nov-Jan, Bangladesh, Nepal and
    Mongolia Dec-Feb;
  * hazards are display-only: neither scoring copy (picks.py, app.js
    valueScores) reads them, so they never move a grade or a ranking;
  * the chart line and the month table word the span the same way
    ("Nov–Jan", guide_sizers.month_span).
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_sizers, render_guide as rg   # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or bool(c)
results = []
ACTS = json.load(open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8"))

bad, overlap = [], []
for iso, a in sorted(ACTS.items()):
    seen = set()
    for h in a.get("hazards") or []:
        m = h.get("months") or []
        if not m or not h.get("note") or any(not isinstance(x, int) or not 1 <= x <= 12 for x in m):
            bad.append(iso)
        if seen & set(m):
            overlap.append(iso)
        seen |= set(m)
results.append(ok(not bad, "every hazard has months 1-12 and a note %s" % (bad or "")))
results.append(ok(not overlap, "no country's hazards share a month %s" % (overlap or "")))

SMOG = {"IN": ([11, 12, 1], "Delhi"), "PK": ([11, 12, 1], "Lahore"), "BD": ([12, 1, 2], "Dhaka"),
        "NP": ([12, 1, 2], "Kathmandu"), "MN": ([12, 1, 2], "Ulaanbaatar")}
for iso, (months, place) in SMOG.items():
    hit = [h for h in ACTS[iso].get("hazards") or [] if place in h["note"]]
    results.append(ok(len(hit) == 1 and hit[0]["months"] == months and re.match(r"Winter (smog|haze) — ", hit[0]["note"]),
                      "%s: winter air hazard over %s naming %s" % (iso, guide_sizers.month_span(months), place)))
results.append(ok(guide_sizers.month_span([11, 12, 1]) == "Nov–Jan" and guide_sizers.month_span([12, 1, 2]) == "Dec–Feb",
                  "a span across New Year reads Nov–Jan / Dec–Feb"))

picks = open(os.path.join(ROOT, "fxtracker", "picks.py"), encoding="utf-8").read()
app = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
vs = re.search(r"\nfunction valueScores\(.*?\n}\n", app, re.S)
results.append(ok("hazard" not in picks and vs and "hazard" not in vs.group(0).lower(),
                  "display-only: picks.py and app.js valueScores never read hazards"))

# India's month table shows the smog in its ⚠️ column, under November.
was = rg.MONTH_TABLE_ALL
try:
    rg.MONTH_TABLE_ALL = True
    t = rg.month_table("IN")
finally:
    rg.MONTH_TABLE_ALL = was
nov = re.search(r'<tr id="november"[^>]*>(.*?)</tr>', t or "", re.S)
results.append(ok(nov and "Winter smog" in nov.group(1) and "<b>Nov–Jan:</b> Winter smog" in t,
                  "India's month table: ⚠️ in November and a Nov–Jan line under the table"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
