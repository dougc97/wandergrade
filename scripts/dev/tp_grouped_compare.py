#!/usr/bin/env python3
"""Offline comparison of a tp_grouped_probe.py run (no network, no token):
/v1/prices/monthly (M, today's source) against aviasales/v3/grouped_prices
(G default market, GU market=us, GT GU + 3-21 day trips).

    /usr/bin/python3 scripts/dev/tp_grouped_compare.py PROBE.json [--json OUT.json]

Prints, per question:
  1. coverage: months per route in the flight-value window, per source
  2. price agreement on months both have, and what explains a gap:
     one-way vs round trip, trip length, departure day, stops, airline
  3. does market=us change grouped_prices (G vs GU)? does 3-21 days (GT)?
  4. the Flights tab: per country (Part A: the sampled city; Part B: up to 3
     cities, cheapest per month, as get_monthly_multi does) the curve,
     whether it bands (6+ months) and each month's Low / Typical / High,
     against the live site's curves (/api/flight-value, M plus row fill)
  5. speed and rate-limit headers
"""
import datetime
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from fxtracker import flightvalue as fvm  # noqa: E402

SRC = ("M", "G", "GU", "GT")      # set from the probe's meta in main()


def day(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def rows(res, window):
    """{YYYY-MM: row} in the window, departures not yet flown (the server's
    _upcoming), for a 200 answer; {} otherwise."""
    if not res or res.get("status") != 200 or not isinstance(res.get("data"), dict):
        return {}
    today = TODAY.isoformat()
    out = {}
    for k, v in res["data"].items():
        if not isinstance(v, dict) or v.get("price") is None:
            continue
        m = k[:7]
        dep = str(v.get("departure_at") or "")[:10]
        if m in window and not (len(dep) == 10 and dep < today):
            out[m] = v
    return out


def trip_days(v):
    a, b = day(v.get("departure_at")), day(v.get("return_at"))
    return (b - a).days if a and b else None


def fno(x):
    """A flight number as a number: M gives 90, grouped_prices "090"."""
    try:
        return int(str(x).lstrip("0") or 0)
    except ValueError:
        return str(x)


def stops(v, src):
    """M's transfers is the larger of the two legs; grouped's is the
    outbound leg only, with return_transfers beside it."""
    if src == "M" or "return_transfers" not in v:
        return v.get("transfers")
    return max(v.get("transfers") or 0, v.get("return_transfers") or 0)


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def q(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None


def curve_bands(curve):
    """{month: band} for a {month: price} curve, the Flights tab's way."""
    stats = fvm.curve_stats(fvm.stats_prices(curve, PARTIAL))
    if stats.get("median") is None:
        return {}, stats
    return {k: fvm.band(p, stats) for k, p in curve.items()}, stats


def main(argv):
    global TODAY, PARTIAL, SRC
    doc = json.load(open(argv[1]))
    SRC = ("M",) + tuple(doc["meta"].get("variants") or ("G", "GU", "GT"))
    BV = tuple(doc["meta"].get("b_variants") or ("GU",))
    started = doc["meta"]["started"]
    TODAY = datetime.date.fromisoformat(started[:10])
    PARTIAL = fvm.partial_month(TODAY)
    window = set(fvm.window_months(TODAY))
    out = {"started": started, "window": sorted(window)}
    A = doc["A"]
    print("probe started %s; window %s .. %s; %d paired routes, %d Part B cities" % (
        started, min(window), max(window), len(A), len(doc["B"])))

    # 1. coverage
    print("\n1. months per route in the window (Part A, %d routes)" % len(A))
    cov = {s: [len(rows(r.get(s), window)) for r in A] for s in SRC}
    status = {s: {} for s in SRC}
    for r in A:
        for s in SRC:
            k = (r.get(s) or {}).get("status")
            status[s][k] = status[s].get(k, 0) + 1
    for s in SRC:
        c = cov[s]
        print("  %-2s statuses %s | months: mean %.1f, median %s, routes with 6+: %d, with 0: %d" % (
            s, status[s], st.mean(c), st.median(c), sum(1 for x in c if x >= 6), sum(1 for x in c if x == 0)))
    by_bucket = {}
    for r in A:
        b = by_bucket.setdefault(r["bucket"], {s: [] for s in SRC})
        for s in SRC:
            b[s].append(len(rows(r.get(s), window)))
    for b, d in by_bucket.items():
        print("  bucket %-3s (%d routes): " % (b, len(d["M"])) + ", ".join(
            "%s %.1f" % (s, st.mean(d[s])) for s in SRC))
    for s in SRC[1:]:
        union = [len(set(rows(r.get("M"), window)) | set(rows(r.get(s), window))) for r in A]
        lost = sum(len(set(rows(r.get("M"), window)) - set(rows(r.get(s), window))) for r in A)
        new = sum(len(set(rows(r.get(s), window)) - set(rows(r.get("M"), window))) for r in A)
        print("  M or %s: mean %.1f, routes with 6+: %d | months M has and %s lacks: %d, %s has and M lacks: %d" % (
            s, st.mean(union), sum(1 for x in union if x >= 6), s, lost, s, new))
    out["coverage"] = {s: cov[s] for s in SRC}

    # 2. price agreement M vs each grouped variant, with explanations
    for s in SRC[1:]:
        pairs = []
        for r in A:
            m, g = rows(r.get("M"), window), rows(r.get(s), window)
            for k in sorted(set(m) & set(g)):
                pairs.append((r["iso"], r["city"], k, m[k], g[k]))
        if not pairs:
            print("\n2. M vs %s: no shared months" % s)
            continue
        ratios = [g["price"] / m["price"] for *_, m, g in pairs if m["price"]]
        same = sum(1 for *_, m, g in pairs if round(m["price"]) == round(g["price"]))
        ow_m = sum(1 for *_, m, g in pairs if not m.get("return_at"))
        ow_g = sum(1 for *_, m, g in pairs if not g.get("return_at"))
        same_dep = sum(1 for *_, m, g in pairs if day(m.get("departure_at")) == day(g.get("departure_at")))
        same_trip = sum(1 for *_, m, g in pairs if trip_days(m) == trip_days(g) and trip_days(m) is not None)
        same_flight = sum(1 for *_, m, g in pairs if m.get("airline") and m.get("airline") == g.get("airline")
                          and fno(m.get("flight_number")) == fno(g.get("flight_number")))
        print("\n2. M vs %s on %d shared months (%d routes)" % (s, len(pairs), len({p[1] for p in pairs})))
        print("  same price: %d (%.0f%%); %s/M price ratio p10 %.2f, median %.2f, p90 %.2f; %s cheaper on %d, dearer on %d" % (
            same, pct(same, len(pairs)), s, q(ratios, .1), st.median(ratios), q(ratios, .9), s,
            sum(1 for x in ratios if x < 0.995), sum(1 for x in ratios if x > 1.005)))
        print("  one-way (no return_at): M %d, %s %d | same departure day %d | same trip length %d | same airline+flight %d" % (
            ow_m, s, ow_g, same_dep, same_trip, same_flight))
        tm = [trip_days(m) for *_, m, g in pairs if trip_days(m) is not None]
        tg = [trip_days(g) for *_, m, g in pairs if trip_days(g) is not None]
        if tm and tg:
            print("  trip length days: M median %s (p10 %s, p90 %s); %s median %s (p10 %s, p90 %s); M trips under 3 days %d, %s %d" % (
                st.median(tm), q(tm, .1), q(tm, .9), s, st.median(tg), q(tg, .1), q(tg, .9),
                sum(1 for x in tm if x < 3), s, sum(1 for x in tg if x < 3)))
        same_stops = sum(1 for *_, m, g in pairs if stops(m, "M") == stops(g, s))
        print("  same stops (M's max of both legs vs grouped max(transfers, return_transfers)): %d/%d" % (
            same_stops, len(pairs)))
        exp = [m.get("expires_at") for *_, m, g in pairs if m.get("expires_at")]
        if exp:
            print("  M expires_at range %s .. %s" % (min(exp), max(exp)))
        out.setdefault("pairs", {})[s] = [
            {"iso": iso, "city": c, "month": k, "M": m, s: g} for iso, c, k, m, g in pairs]
        if s == SRC[1]:
            print("  ten examples (route month: M price dep->ret stops | GU price dep->ret stops):")
            for iso, c, k, m, g in pairs[:10]:
                print("    %s %s %s: $%s %s->%s %s | $%s %s->%s %s" % (
                    iso, c, k, m["price"], str(m.get("departure_at"))[:10], str(m.get("return_at"))[:10], m.get("transfers"),
                    g["price"], str(g.get("departure_at"))[:10], str(g.get("return_at"))[:10], g.get("transfers")))

    # 3. G vs GU (market) and GU vs GT (trip length)
    for a, b in zip(SRC[1:], SRC[2:]):
        same_n = same_p = shared = 0
        for r in A:
            x, y = rows(r.get(a), window), rows(r.get(b), window)
            same_n += len(x) == len(y)
            for k in set(x) & set(y):
                shared += 1
                same_p += round(x[k]["price"]) == round(y[k]["price"])
        print("\n3. %s vs %s: same month count on %d/%d routes; same price on %d/%d shared months" % (
            a, b, same_n, len(A), same_p, shared))

    # 4. the Flights tab
    live = doc["live_fv"].get("countries") or {}
    print("\n4. Flights tab bands")
    live_curve = {iso: {k: p for k, (p, _c) in (c.get("curve") or {}).items() if k in window}
                  for iso, c in live.items() if not c.get("pending")}
    out["bands"] = {}
    for bv in BV:
        # Country curves from this variant: up to 3 cities, cheapest per month.
        gc_all, done = {}, set()
        for r in doc["B"]:          # cities in the server's order (live_flights "cities")
            if r["iso"] in done:
                continue
            cur = gc_all.setdefault(r["iso"], {})
            for k, v in rows(r.get(bv), window).items():
                if k not in cur or v["price"] < cur[k]:
                    cur[k] = round(v["price"])
            if len(cur) >= 10:      # get_monthly_multi stops once a city covers the year
                done.add(r["iso"])
        isos = sorted(set(live_curve) | set(gc_all))
        n_live = sum(1 for i in isos if len(live_curve.get(i, {})) >= fvm.MIN_MONTHS)
        n_g = sum(1 for i in isos if len(gc_all.get(i, {})) >= fvm.MIN_MONTHS)
        n_fill = sum(1 for i in isos if len(set(live_curve.get(i, {})) | set(gc_all.get(i, {}))) >= fvm.MIN_MONTHS)
        agree = total = same_price = shared = 0
        flips = []
        for iso in isos:
            lc, gc = live_curve.get(iso, {}), gc_all.get(iso, {})
            for k in set(lc) & set(gc):
                shared += 1
                same_price += lc[k] == gc[k]
            if len(lc) < fvm.MIN_MONTHS or len(gc) < fvm.MIN_MONTHS:
                continue
            lb, _ = curve_bands(lc)
            gb, _ = curve_bands(gc)
            for k in set(lb) & set(gb):
                total += 1
                if lb[k] == gb[k]:
                    agree += 1
                else:
                    flips.append((iso, k, lc[k], lb[k], gc[k], gb[k]))
        print("  %s: countries banded (6+ months): live today %d, %s alone %d, live filled with %s %d (of %d); "
              "same price as live on %d/%d shared country-months" % (bv, n_live, bv, n_g, bv, n_fill, len(isos),
                                                                     same_price, shared))
        print("    months banded by both (live vs %s-only curve): %d, same band on %d (%.0f%%)" % (
            bv, total, agree, pct(agree, total)))
        for f in flips[:8]:
            print("      %s %s: live $%s %s | %s $%s %s" % (f[0], f[1], f[2], f[3], bv, f[4], f[5]))
        out["bands"][bv] = {"live": n_live, "alone": n_g, "fill": n_fill, "both_months": total, "agree": agree,
                            "flips": flips, "same_price": same_price, "shared": shared}

    # 5. speed and limits
    print("\n5. speed")
    for s in SRC:
        ms = [r[s]["ms"] for r in A if s in r and r[s].get("status") == 200]
        if ms:
            print("  %-2s median %d ms, p90 %d ms; rate headers e.g. %s" % (
                s, st.median(ms), q(ms, .9), next((r[s]["rate"] for r in A if s in r and r[s].get("rate")), {})))
    for bv in BV:
        msb = [r[bv]["ms"] for r in doc["B"] if (r.get(bv) or {}).get("status") == 200]
        if msb:
            print("  Part B %s: %d calls, median %d ms" % (bv, len(msb), st.median(msb)))

    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w") as f:
            json.dump(out, f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
