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

Per home currency (the digest's editions, fxtracker/digest_variants.py):
scripts/parity/fixtures/<CUR>/{rates,flights,flight_value}.json are
/api/rates?base=CUR, /api/flights?origin=ISO and /api/flight-value?origin=ISO
for that edition's home. The USD fixtures above stay the price-level rates
(the site's lastRates); the CUR rates are its homeRates (strength in CUR).
A cold flight-value payload ("filling") is a valid fixture: both sides then
fall back to the distance measure for the same routes.

Run:  /usr/bin/python3 scripts/parity/parity.py [--refresh] [--month N] [--currency EUR | --all]
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
from fxtracker.digest_variants import PICKER_ORDER, VARIANTS  # noqa: E402

JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
SITE = "https://wandergrade.com"
FIXTURES = {
    "rates": "/api/rates",
    "advisories": "/api/advisories?source=us",
    "flights": "/api/flights?origin=US",
    "flight_value": "/api/flight-value?origin=US",
}
FIELDS = ("afford", "safe", "wx", "fly", "value", "pl", "fare", "fareEst", "fx", "advLvl", "flyBasis")
# pl and fx are floats on both sides; the rest are rounded ints (or None/bool).
TOL = {"pl": 1e-9, "fx": 1e-9}


# Per-currency fixtures: name -> /api path template (CUR, ISO filled in).
CUR_FIXTURES = {
    "rates": "/api/rates?base={cur}",
    "flights": "/api/flights?origin={iso}",
    "flight_value": "/api/flight-value?origin={iso}",
}


def _fixture_path(k, cur="USD"):
    if cur == "USD":
        return os.path.join(HERE, "fixture_%s.json" % k)
    return os.path.join(HERE, "fixtures", cur, "%s.json" % k)


def _get(path):
    req = urllib.request.Request(SITE + path, headers={"User-Agent": "wandergrade-parity/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def refresh(currencies=("USD",)):
    for cur in currencies:
        if cur == "USD":
            todo = [(k, path) for k, path in FIXTURES.items()]
        else:
            iso = VARIANTS[cur].home_iso
            todo = [(k, t.format(cur=cur, iso=iso)) for k, t in CUR_FIXTURES.items()]
        for k, path in todo:
            data = _get(path)
            out = _fixture_path(k, cur)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(data)
            print("refreshed %s %s (%d bytes)" % (cur, k, len(data)))


def _load(name):
    with open(os.path.join(ROOT, "public", name), encoding="utf-8") as f:
        return json.load(f)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_fixture(month, home_iso, home_cur):
    fx = {k: _read(_fixture_path(k)) for k in FIXTURES}
    if home_cur != "USD":
        # rates stays USD (price levels); the home's own rates measure strength.
        fx["home_rates"] = _read(_fixture_path("rates", home_cur))
        fx["flights"] = _read(_fixture_path("flights", home_cur))
        fx["flight_value"] = _read(_fixture_path("flight_value", home_cur))
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
    """Score with the digest's port, from the same fixture — the way
    picks.build_variant() scores the fixture's home edition."""
    ppp, climate = fixture["ppp"], fixture["climate"]
    home_iso, home_cur = fixture["home_iso"], fixture["home_currency"]
    rate_by_code = {r["code"]: r["rate_now"] for r in fixture["rates"]["rows"]}
    home_rows = (fixture.get("home_rates") or fixture["rates"])["rows"]
    strength_by_code = {r["code"]: r["strength_pct"] for r in home_rows}
    adv_by_iso = picks.advisory_levels(fixture["advisories"]["items"])
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO)
    anchor = picks._price_level(home_iso, ppp, rate_by_code, fit) or 1
    fares = picks.fare_context(fixture["flights"], geo.country_centroids(fixture["world"]))
    if fares:
        fares["fv"] = fixture["flight_value"]
    out = {"anchor_pl": anchor, "scored": {}}
    for iso in picks.CUR_BY_ISO:
        s = picks._score(iso, month, ppp, climate, rate_by_code, strength_by_code, adv_by_iso,
                         fit, fares, anchor, home_iso=home_iso, home_cur=home_cur)
        if s:
            out["scored"][iso] = {"afford": s["afford"], "safe": s["safe"], "wx": s["wx"], "fly": s["fly"],
                                  "value": s["value"], "pl": s["pl"], "fare": s["fare"],
                                  "fareEst": s["fareEst"], "fx": s["fx"], "advLvl": s["advLvl"],
                                  "flyBasis": s["fly_basis"]}
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


def run_one(month, cur):
    home = VARIANTS[cur].home_iso
    fixture = load_fixture(month, home, cur)
    site = site_scores(fixture)
    digest = digest_scores(fixture, month)
    isos, mism = compare(site, digest)
    n_scored = sum(1 for i in isos if site["scored"].get(i))
    print("%s (home %s) month %d · %d countries scored on the site, %d by the digest · "
          "anchor pl site %.6f digest %.6f"
          % (cur, home, month, n_scored, len(digest["scored"]), site["anchor_pl"], digest["anchor_pl"]))
    for iso, f, a, b in mism:
        print("  MISMATCH %s %s %s: site=%r digest=%r" % (cur, iso, f, a, b))
    print("%s: %d mismatches across %d countries x %d fields" % (cur, len(mism), len(isos), len(FIELDS)))
    return len(mism)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch the production fixture (GET)")
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--currency", default="USD", help="a digest edition: " + ", ".join(PICKER_ORDER))
    ap.add_argument("--home", default=None, help="must match the edition's home (digest_variants)")
    ap.add_argument("--all", action="store_true", help="every edition")
    args = ap.parse_args()
    curs = list(PICKER_ORDER) if args.all else [args.currency.upper()]
    for cur in curs:
        if cur not in VARIANTS:
            sys.exit("parity: no digest edition for %s (digest_variants.VARIANTS)" % cur)
    if args.home and (args.all or args.home.upper() != VARIANTS[curs[0]].home_iso):
        sys.exit("parity: the %s edition's home is %s (digest_variants); --home can't change it"
                 % (curs[0], VARIANTS[curs[0]].home_iso))
    if args.refresh:
        refresh(curs)
    today = datetime.date.today()
    month = args.month or ((today.month - 1 + 2) % 12 + 1)   # the digest's own default
    total = sum(run_one(month, cur) for cur in curs)
    if len(curs) > 1:
        print("all editions: %d mismatches" % total)
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
