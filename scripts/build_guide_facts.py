#!/usr/bin/env python3
"""Build public/guide-facts.json: the per-guide snapshot behind each country
page's title, meta description, FAQ answers and SSR fact lines.

Two figures only WanderGrade puts side by side — the price level against the
US (the hydrated page's 💰 "Local prices ≈ N% of the US") and the advisory
level the guide's 🛡️ badge shows (US State Dept, gaps filled by Canada or
Germany as the live feed fills them) — computed ONCE from a dated rates +
advisories pair, so render_guide never calls a live API (the HTML is
edge-cached) and every number it prints carries the month it is from.

Inputs: --rates / --advisories, defaulting to the parity fixtures
(scripts/parity/fixture_*.json — production /api answers, refreshed with
`parity.py --refresh`, GET only), and the committed public/ppp.json. The price
level is pricelevel.price_level with the income plausibility fit, which
parity.py proves equal to app.js priceLevel. The carry-forward for inflation is
taken at the rates' own as_of date, so a rebuild reproduces the same figures.

Each entry: pct (js_round(100*pl); never for the US), band (app.js plWord on
the two printed decimals), plof (the UK for England/Scotland/Wales), adv, src
(us/ca/de), advof (the parent whose advisory a territory shows), and t/d/dn —
render_guide.meta()'s title, description and number-free description, so app.js
sets exactly what the server would on in-app navigation.

public/content-stamp.txt (the sitemap's <lastmod>) is bumped to today only
when a title, description, figure or level actually changed.

Run:  /usr/bin/python3 scripts/build_guide_facts.py [--rates F] [--advisories F]
Then restart server.py (render_guide reads the file once per process).
"""

import argparse
import datetime
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fxtracker import picks, pricelevel, render_guide  # noqa: E402

PUBLIC = os.path.join(ROOT, "public")
OUT = os.path.join(PUBLIC, "guide-facts.json")
STAMP = os.path.join(PUBLIC, "content-stamp.txt")

# app.js GUIDE_PARENT (price level, always) and ADV_PARENT (advisory, only when
# the place has no row of its own).
GUIDE_PARENT = {"GB-ENG": "GB", "GB-SCT": "GB", "GB-WLS": "GB"}
ADV_PARENT = dict(GUIDE_PARENT, GG="GB", IM="GB", JE="GB", FO="DK")
CHANGE_KEYS = ("t", "d", "pct", "adv")


def band(pl):
    """app.js plWord(pl) against the US: banded on toFixed(2), the digits the
    page prints. Decimal(pl) is the exact binary value, and HALF_UP on it is
    toFixed's rounding."""
    r = float(Decimal(pl).quantize(Decimal("0.01"), ROUND_HALF_UP))
    if r <= 1 - 0.1:
        return "very cheap" if r < 0.55 else "cheap"
    return "about the same" if r <= 1 + 0.1 else "pricey"


def build(rates, advisories, guides):
    asof = datetime.date.fromisoformat(rates["as_of"][:10])
    now_y = pricelevel.now_year(asof)
    ppp = json.load(open(os.path.join(PUBLIC, "ppp.json"), encoding="utf-8"))
    rate_by_code = {r["code"]: r["rate_now"] for r in rates["rows"]}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO, now_y)
    us = pricelevel.price_level("US", ppp, rate_by_code, picks.CUR_BY_ISO, fit, now_y) or 1
    meta = {}
    for it in advisories["items"]:              # app.js advisoryMetaByIso: last wins
        if it.get("iso"):
            meta[it["iso"]] = it
    default_src = advisories.get("source") or "us"

    out = {"_asof": asof.isoformat()}
    for iso in sorted(guides):
        f = {}
        pl_iso = GUIDE_PARENT.get(iso, iso)
        pl = pricelevel.price_level(pl_iso, ppp, rate_by_code, picks.CUR_BY_ISO, fit, now_y)
        if pl and iso != "US":
            rel = pl / us
            f["pct"] = pricelevel.js_round(100 * rel)
            f["band"] = band(rel)
            if pl_iso != iso:
                f["plof"] = pl_iso
        parent = ADV_PARENT.get(iso) if iso not in meta and ADV_PARENT.get(iso) in meta else None
        it = meta.get(iso) or (parent and meta[parent])
        if it and it.get("level"):
            f["adv"] = it["level"]
            f["src"] = it.get("via") or default_src
            if parent:
                f["advof"] = parent
        m = render_guide.meta(iso, f, asof)
        f["t"], f["d"] = m["title"], m["desc"]
        dn = render_guide.meta_numberfree(iso)
        if dn != f["d"]:
            f["dn"] = dn
        out[iso] = f
    return out


def dump(data):
    """One country per line: a rebuild's diff reads country by country."""
    keys = ["_asof"] + sorted(k for k in data if k != "_asof")
    return "{\n" + ",\n".join(
        "%s:%s" % (json.dumps(k), json.dumps(data[k], ensure_ascii=False, separators=(",", ":")))
        for k in keys) + "\n}\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", default=os.path.join(HERE, "parity", "fixture_rates.json"))
    ap.add_argument("--advisories", default=os.path.join(HERE, "parity", "fixture_advisories.json"))
    args = ap.parse_args()
    rates = json.load(open(args.rates, encoding="utf-8"))
    advisories = json.load(open(args.advisories, encoding="utf-8"))
    guides = [iso for _slug, iso in render_guide.all_slugs()]
    data = build(rates, advisories, guides)

    n_pct = sum(1 for k, v in data.items() if k != "_asof" and "pct" in v)
    n_adv = sum(1 for k, v in data.items() if k != "_asof" and "adv" in v)
    # A truncated feed would publish 190 number-free pages and bump every
    # lastmod for it: refuse instead.
    if n_pct < 0.75 * len(guides) or n_adv < 0.9 * len(guides):
        sys.exit("build_guide_facts: only %d price levels / %d advisories for %d guides — "
                 "inputs look broken, nothing written" % (n_pct, n_adv, len(guides)))

    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    changed = [iso for iso in guides
               if any((old.get(iso) or {}).get(k) != data[iso].get(k) for k in CHANGE_KEYS)]
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(dump(data))
    print("guide-facts.json: %d guides as of %s · %d with a price level · %d with an advisory · %d changed"
          % (len(guides), data["_asof"], n_pct, n_adv, len(changed)))
    if changed:
        today = datetime.date.today().isoformat()
        with open(STAMP, "w", encoding="utf-8") as fh:
            fh.write(today + "\n")
        print("content-stamp.txt -> %s (%s%s)" % (today, ", ".join(changed[:8]),
                                                   " …" if len(changed) > 8 else ""))


if __name__ == "__main__":
    main()
