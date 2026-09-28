#!/usr/bin/env python3
"""Newsletter <-> site parity: score every country with the browser's scorer
(public/app.js valueScores, run under jsc via build_js.py) and the digest's
Python port (fxtracker/picks._score) from ONE fixture, and diff them.

The digest must grade exactly what a visitor sees on Top Picks — the site's
scorer is the truth and picks.py is its port. Any difference here is a port
bug (a clamp that rounds differently, a guard added to one side only), never
data: both sides read the same snapshot.

Fixture: scripts/parity/fixture_*.json — production /api answers, refreshed
with --refresh (GET only). public/{ppp,climate}.json and world.geojson come
from the repo at run time.

Run:  /usr/bin/python3 scripts/parity/parity.py [--refresh] [--month N] [--home DE --currency EUR]
Exit 0 on zero mismatches. A field mismatch prints iso, field, site vs digest.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from fxtracker import geo, picks, pricelevel  # noqa: E402

JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
SITE = "https://wandergrade.com"
FIXTURES = {
    "rates": "/api/rates",
    "advisories": "/api/advisories?source=us",
    "flights": "/api/flights?origin=US",
    "flight_value": "/api/flight-value?origin=US",
}
FIELDS = ("afford", "safe", "wx", "fly", "value", "pl", "fare", "fareEst", "fx", "advLvl")
# pl and fx are floats on both sides; the rest are rounded ints (or None/bool).
TOL = {"pl": 1e-9, "fx": 1e-9}


def _fixture_path(k):
    return os.path.join(HERE, "fixture_%s.json" % k)


def refresh():
    for k, path in FIXTURES.items():
        req = urllib.request.Request(SITE + path, headers={"User-Agent": "wandergrade-parity/1.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
        with open(_fixture_path(k), "wb") as f:
            f.write(data)
        print("refreshed %s (%d bytes)" % (k, len(data)))


def _load(name):
    with open(os.path.join(ROOT, "public", name), encoding="utf-8") as f:
        return json.load(f)


def load_fixture(month, home_iso, home_cur):
    fx = {k: json.load(open(_fixture_path(k), encoding="utf-8")) for k in FIXTURES}
    fx["ppp"] = _load("ppp.json")
    fx["climate"] = _load("climate.json")
    fx["world"] = geo.load_world()
    fx["month"] = month
    fx["home_iso"] = home_iso
    fx["home_currency"] = home_cur
    return fx


def site_scores(fixture):
    """Run the extracted browser scorer under jsc."""
    subprocess.check_call([sys.executable, os.path.join(HERE, "build_js.py")], stdout=subprocess.DEVNULL)
    fpath = os.path.join(HERE, "_fixture_run.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(fixture, f)
    js = os.path.join(HERE, "site.js")
    # jsc has no argv for read(); the fixture path is spliced in as a literal.
    with open(js, encoding="utf-8") as f:
        prog = f.read().replace("ARGS_FIXTURE", json.dumps(fpath))
    run = os.path.join(HERE, "_site_run.js")
    with open(run, "w", encoding="utf-8") as f:
        f.write(prog)
    out = subprocess.run([JSC, run], capture_output=True, text=True, timeout=120)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit("site scorer failed:\n%s\n%s" % (out.stdout[-2000:], out.stderr[-2000:]))
    return json.loads(out.stdout.strip().splitlines()[-1])


def digest_scores(fixture, month):
    """Score with the digest's port, from the same fixture."""
    ppp, climate = fixture["ppp"], fixture["climate"]
    rate_by_code = {r["code"]: r["rate_now"] for r in fixture["rates"]["rows"]}
    strength_by_code = {r["code"]: r["strength_pct"] for r in fixture["rates"]["rows"]}
    adv_by_iso = picks.advisory_levels(fixture["advisories"]["items"])
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO)
    anchor = picks._price_level(picks.HOME_ISO, ppp, rate_by_code, fit) or 1
    fares = picks.fare_context(fixture["flights"], geo.country_centroids(fixture["world"]))
    out = {"anchor_pl": anchor, "scored": {}}
    for iso in picks.CUR_BY_ISO:
        s = picks._score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
                         fit, fares, anchor)
        if s:
            out["scored"][iso] = {"afford": s["afford"], "safe": s["safe"], "wx": s["wx"], "fly": s["fly"],
                                  "value": s["value"], "pl": s["pl"], "fare": s["fare"],
                                  "fareEst": s["fareEst"], "fx": s["fx"], "advLvl": s["advLvl"]}
    return out


def _same(a, b, tol):
    if a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
        return a == b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def compare(site, digest):
    mism = []
    isos = sorted(set(site["scored"]) | set(digest["scored"]))
    for iso in isos:
        a, b = site["scored"].get(iso), digest["scored"].get(iso)
        if (a is None) != (b is None):
            mism.append((iso, "scored", a is not None, b is not None))
            continue
        if a is None:
            continue
        for f in FIELDS:
            if not _same(a.get(f), b.get(f), TOL.get(f, 0)):
                mism.append((iso, f, a.get(f), b.get(f)))
    return isos, mism


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch the production fixture (GET)")
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--home", default="US")
    ap.add_argument("--currency", default="USD")
    args = ap.parse_args()
    if args.refresh:
        refresh()
    if args.home != "US" or args.currency != "USD":
        # picks.py is US-only today (HOME_ISO); a non-US run only makes sense
        # once the digest is localized. Say so instead of comparing apples to
        # oranges.
        sys.exit("parity: the digest scores from the US only (picks.HOME_ISO); --home/--currency "
                 "are reserved for the localized-newsletter project")
    today = datetime.date.today()
    month = args.month or ((today.month - 1 + 2) % 12 + 1)   # the digest's own default
    fixture = load_fixture(month, args.home, args.currency)
    site = site_scores(fixture)
    digest = digest_scores(fixture, month)
    isos, mism = compare(site, digest)
    n_scored = sum(1 for i in isos if site["scored"].get(i))
    print("month %d · %d countries scored on the site, %d by the digest · anchor pl site %.6f digest %.6f"
          % (month, n_scored, len(digest["scored"]), site["anchor_pl"], digest["anchor_pl"]))
    for iso, f, a, b in mism:
        print("  MISMATCH %s %s: site=%r digest=%r" % (iso, f, a, b))
    print("%d mismatches across %d countries x %d fields" % (len(mism), len(isos), len(FIELDS)))
    sys.exit(1 if mism else 0)


if __name__ == "__main__":
    main()
