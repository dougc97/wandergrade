#!/usr/bin/env python3
"""Plain-words report of the two-week fare-source test (fxtracker/flightshadow.py):
today's source (/v1/prices/monthly) against Travelpayouts' grouped_prices, US
fares from New York, compared once a day by the live server. Read-only.

    /usr/bin/python3 scripts/dev/flight_shadow_report.py https://wandergrade.com/api/flight-shadow
    /usr/bin/python3 scripts/dev/flight_shadow_report.py saved.json

The argument is /api/flight-shadow's JSON: its URL, or a file saved from it.
It says how often the two sources give the same price, how often a month's
Low / Typical / High word would change, whether the new source reads this
month and next cheaper (the worry from the Oct 26 spike), how long each takes
to warm up after a deploy, and how many extra calls the test costs a day.
The "What this suggests" lines are a rule of thumb for Doug's decision, not
the decision.
"""
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

BAND_WORD = {"L": "Low", "T": "Typical", "H": "High"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
# The rule of thumb behind "What this suggests".
AGREE_OK = 0.95       # the band word the same on at least this share of months
NEAR_GAP_OK = 0.10    # this month and next: at most this much more disagreement than later months


def name(iso):
    try:
        from fxtracker import render_guide
        return render_guide.name_for_iso(iso) or iso
    except Exception:
        return iso


def month_words(k):
    try:
        return "%s %s" % (MONTHS[int(k[5:7]) - 1], k[:4])
    except (ValueError, IndexError):
        return k


def pct(a, b):
    return "%d%%" % round(100.0 * a / b) if b else "n/a"


def money(v):
    return "$%s" % format(v, ",") if v is not None else "none"


def mins(secs):
    if secs is None:
        return "unknown"
    secs = int(round(secs))
    return "%d min %02d s" % (secs // 60, secs % 60) if secs >= 60 else "%d s" % secs


def read(src):
    if src.startswith(("http://", "https://")):
        # Cloudflare answers Python's default User-Agent with a 403.
        req = urllib.request.Request(src, headers={"User-Agent": "wandergrade-report/1.0",
                                                   "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def add(total, part):
    for k, v in (part or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total[k] = total.get(k, 0) + v


def report(doc, out=print):
    st = doc.get("status") or {}
    days = [d for d in doc.get("days") or [] if isinstance(d, dict)]
    good = [d for d in days if not d.get("aborted") and d.get("agg")]
    out("Fare source test: today's source vs Travelpayouts' grouped_prices (%s fares, from %s)"
        % (st.get("origin", "US"), (days[-1].get("hub") if days else None) or "NYC"))
    out("Status: %s, %s. %d of %d daily runs done; it stops by itself after %d, or after %s."
        % (st.get("state", "?"), st.get("why", "?"), st.get("complete", len(good)), st.get("wanted", 14),
           st.get("wanted", 14), st.get("until", "?")))
    if not days:
        out("\nNo results yet. The first run comes 30 minutes or more after a deploy, once the fares are in.")
        return
    out("Results: %d day(s), %s to %s%s." % (len(days), days[0].get("day"), days[-1].get("day"),
                                           ("; %d stopped early" % (len(days) - len(good))) if len(days) != len(good) else ""))

    out("\nDay by day (route months = the same city's months in both sources)")
    out("  %-10s %6s %8s %6s %8s %12s %14s %10s" % ("day", "calls", "months", "same", "within5", "bands agree",
                                                   "ranges now/new", "near same"))
    for d in days:
        c = d.get("calls") or {}
        if d.get("aborted") or not d.get("agg"):
            out("  %-10s %6s  stopped early: %s" % (d.get("day"), c.get("grouped", "?"), d.get("aborted") or "no data"))
            continue
        a = d["agg"]
        r, b, n = a["route_months"], a["bands"], a["banded"]
        near = [x for x in a["by_offset"]["route"][:2]]
        nb, ns = sum(x[0] for x in near), sum(x[1] for x in near)
        out("  %-10s %6d %8d %6s %8s %12s %14s %10s" % (
            d["day"], c.get("grouped", 0), r["both"], pct(r["same"], r["both"]), pct(r["within5"], r["both"]),
            pct(b["agree"], b["both"]), "%d/%d" % (n["live"], n["shadow"]), pct(ns, nb)))

    if not good:
        out("\nNo complete run yet.")
        return
    r, cm, bands, banded = {}, {}, {"both": 0, "agree": 0}, {}
    matrix, by_route, by_band = {}, [[0] * 4 for _ in range(12)], [[0] * 6 for _ in range(12)]
    for d in good:
        a = d["agg"]
        add(r, a["route_months"])
        add(cm, a["country_months"])
        add(bands, {"both": a["bands"]["both"], "agree": a["bands"]["agree"]})
        add(banded, a["banded"])
        for k, v in a["bands"]["matrix"].items():
            matrix[k] = matrix.get(k, 0) + v
        for i, row in enumerate(a["by_offset"]["route"][:12]):
            by_route[i] = [x + y for x, y in zip(by_route[i], row)]
        for i, row in enumerate(a["by_offset"]["bands"][:12]):
            by_band[i] = [x + y for x, y in zip(by_band[i], row)]
    n = len(good)

    out("\nOver all %d complete day(s)" % n)
    out("  Same price on %s of the months both sources have for the same city (%s within 5%%; %d months)."
        % (pct(r.get("same", 0), r.get("both", 0)), pct(r.get("within5", 0), r.get("both", 0)), r.get("both", 0)))
    diff = r.get("shadow_cheaper", 0) + r.get("live_cheaper", 0)
    out("  Where they differ, the new source is cheaper %d times and dearer %d times." % (
        r.get("shadow_cheaper", 0), r.get("live_cheaper", 0)))
    out("  Months only the new source has: %d; only today's source: %d (a month's fare missing on one side)."
        % (r.get("shadow_only", 0), r.get("live_only", 0)))
    out("  Same stops on %s and the same departure day on %s of the shared months."
        % (pct(r.get("stops_same", 0), r.get("both", 0)), pct(r.get("dep_same", 0), r.get("both", 0))))
    out("  Countries with a Low/Typical/High range, per day: today's source %.0f, the new source %.0f "
        "(%.0f would lose it, %.0f would gain it)." % (
            banded.get("live", 0) / n, banded.get("shadow", 0) / n, banded.get("live_only", 0) / n,
            banded.get("shadow_only", 0) / n))
    out("  The Low/Typical/High word is the same on %s of the %d months both sources band."
        % (pct(bands["agree"], bands["both"]), bands["both"]))
    flips = sorted(((v, k) for k, v in matrix.items() if k[0] != k[1]), reverse=True)
    if flips:
        out("  Changes: " + ", ".join("%s to %s %d" % (BAND_WORD.get(k[0], k[0]), BAND_WORD.get(k[1], k[1]), v)
                                      for v, k in flips[:6]) + ".")

    nb, ns = sum(x[0] for x in by_route[:2]), sum(x[1] for x in by_route[:2])
    lb, ls = sum(x[0] for x in by_route[2:]), sum(x[1] for x in by_route[2:])
    ncheap, ndear = sum(x[2] for x in by_route[:2]), sum(x[3] for x in by_route[:2])
    out("  This month and next: same price %s (%d months); later months %s (%d). Where the near months "
        "differ, the new source is cheaper %d of %d times." % (pct(ns, nb), nb, pct(ls, lb), lb, ncheap,
                                                               ncheap + ndear))
    # The Flights tab opens on this month until the 15th, then on next month.
    low_live = low_new = 0
    for d in good:
        off = 0 if d.get("tab_month") == (d.get("window") or [None])[0] else 1
        low_live += d["agg"]["by_offset"]["bands"][off][2]
        low_new += d["agg"]["by_offset"]["bands"][off][3]
    out("  In the month the Flights tab opens on (%s on the last day), countries marked Low, per day: "
        "today's source %.1f, the new source %.1f." % (month_words(good[-1].get("tab_month") or ""),
                                                       low_live / n, low_new / n))

    last = good[-1]
    warm = ((last.get("live") or {}).get("warm") or {}).get("first") or {}
    c = last.get("calls") or {}
    if warm:
        out("  Warm-up after a deploy: today's source took %s to fill (%d calls, a typical call %s ms; "
            "ready %s after the server started%s)." % (
                mins(warm.get("secs")), warm.get("calls", 0), (warm.get("ms") or {}).get("median", "?"),
                mins(warm.get("boot_s")), ", stopped early" if warm.get("aborted") else ""))
    else:
        out("  Warm-up after a deploy: today's source not measured yet (no fill finished since the last deploy).")
    out("  The new source would need %d calls: about %s at the planned 0.3 s gap (a typical call %s ms)."
        % (c.get("grouped", 0), mins(c.get("proj_fill_s")), (c.get("ms") or {}).get("median", "?")))
    calls = [d.get("calls", {}).get("grouped", 0) for d in days]
    failed = sum(d.get("calls", {}).get("failed", 0) for d in days)
    pace = c.get("pace_s") or st.get("pace_s") or 1
    out("  Extra calls: about %d a day (most %d), at most %d a minute (the limit is 600 a minute); "
        "%d failed in all%s." % (round(sum(calls) / len(calls)), max(calls), round(60 / pace), failed,
                                  "; %d one-way rows ignored" % sum(d.get("calls", {}).get("oneway_rows", 0) for d in days)
                                  if any(d.get("calls", {}).get("oneway_rows") for d in days) else ""))
    age = (last.get("live") or {}).get("age_h") or {}
    if age:
        out("  Today's curves were %.1f hours old (typical) when compared, at most %.1f: the new source's are fresh."
            % (age.get("median", 0), age.get("max", 0)))

    worst = []
    for iso, v in (last.get("dest") or {}).items():
        for k, e in (v.get("m") or {}).items():
            if e[0] is not None and e[1] is not None and e[2] is not None and e[2] != 1:
                worst.append((abs(e[2] - 1), iso, k, e))
    if worst:
        out("\nBiggest differences on %s (country curve the site shows)" % last.get("day"))
        for _, iso, k, e in sorted(worst, reverse=True)[:10]:
            b = e[3]
            word = "" if b == "--" else ", %s on both" % BAND_WORD[b[0]] if b[0] == b[1] else \
                ", %s to %s" % (BAND_WORD.get(b[0], "no range"), BAND_WORD.get(b[1], "no range"))
            out("  %s, %s: %s now, %s new (%+d%%%s)" % (name(iso), month_words(k), money(e[0]), money(e[1]),
                                                     round((e[2] - 1) * 100), word))

    out("\nWhat this suggests (rule of thumb: bands the same on %d%%+ of months, this month and next no more "
        "than %d points worse than later months, no country losing its range)" % (AGREE_OK * 100, NEAR_GAP_OK * 100))
    agree = bands["agree"] / bands["both"] if bands["both"] else 0
    near_gap = (ls / lb if lb else 0) - (ns / nb if nb else 0)
    lose = banded.get("live_only", 0) / n
    reasons = []
    if agree < AGREE_OK:
        reasons.append("the band word changes on %s of months" % pct(bands["both"] - bands["agree"], bands["both"]))
    if near_gap > NEAR_GAP_OK:
        reasons.append("this month and next disagree %d points more than later months" % round(near_gap * 100))
    if lose >= 0.5:
        reasons.append("about %.0f country(ies) a day would lose their range" % lose)
    if n < 14:
        reasons.append("only %d of 14 days so far" % n)
    if not reasons:
        out("  Switching the US to the new source looks safe on these numbers.")
    else:
        out("  Not yet: " + "; ".join(reasons) + ".")


def main(argv):
    if len(argv) < 2:
        print(__doc__.split("\n\n")[1])
        return 2
    report(read(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
