#!/usr/bin/env python3
"""Build public/guide-facts.json — the COMMITTED copy of the per-guide
snapshot behind each country page's title, meta description, FAQ answers,
SSR fact lines and sitemap <lastmod>.

Two figures only WanderGrade puts side by side — the price level against the
US (the hydrated page's 💰 "Local prices ≈ N% of the US") and the advisory
level the guide's 🛡️ badge shows (US State Dept, gaps filled by Canada or
Germany as the live feed fills them) — computed from a dated rates +
advisories pair, so render_guide never calls a live API (the HTML is
edge-cached) and every number it prints carries the month it is from.

In production this file is only the fallback. The server recomputes the same
document daily from its own cached rates and advisories and the PPP table it
serves (fxtracker/guide_facts.py, on Render or with GUIDE_FACTS_REFRESH=1),
stores it in Upstash, and serves the freshest copy — this file only until a
fresh deploy's first check, or while the inputs are down. Both paths run ONE
function, guide_facts.build(): this script is that function on fixtures.

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
sets exactly what the server would on in-app navigation — and m, the day that
guide's entry last changed (a title, description, figure or level), which is
its sitemap <lastmod>. public/content-stamp.txt is NOT touched: it dates the
content every page shares, and a snapshot rebuild changes none of it.

When to run it (a fallback, no longer a monthly chore): when
scripts/test_guide_meta.py says the committed copy is getting old (it fails
once it is within 15 days of render_guide.STALE_DAYS = 90, the age at which a
server that can't recompute would drop every figure), or when the
production logs show the daily recompute isn't landing ("[guide-facts] …
keeping the copy"):
    /usr/bin/python3 scripts/parity/parity.py --refresh     # GET-only production fixtures
    /usr/bin/python3 scripts/build_guide_facts.py
    /usr/bin/python3 scripts/test_guide_meta.py
then commit public/guide-facts.json + the fixtures and deploy.

Run:  /usr/bin/python3 scripts/build_guide_facts.py [--rates F] [--advisories F]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fxtracker import guide_facts  # noqa: E402

PUBLIC = os.path.join(ROOT, "public")
OUT = guide_facts.OUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rates", default=os.path.join(HERE, "parity", "fixture_rates.json"))
    ap.add_argument("--advisories", default=os.path.join(HERE, "parity", "fixture_advisories.json"))
    args = ap.parse_args()
    rates = json.load(open(args.rates, encoding="utf-8"))
    advisories = json.load(open(args.advisories, encoding="utf-8"))
    ppp = json.load(open(os.path.join(PUBLIC, "ppp.json"), encoding="utf-8"))
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    guides = guide_facts.all_guides()
    try:
        data, changed, lost = guide_facts.build(rates, advisories, ppp, old, guides)
    except guide_facts.InputError as e:
        sys.exit("build_guide_facts: %s — nothing written" % e)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(guide_facts.dump(data))
    n_pct = sum(1 for i in guides if data[i].get("pct") is not None)
    n_adv = sum(1 for i in guides if data[i].get("adv"))
    print("guide-facts.json: %d guides as of %s · %d with a price level · %d with an advisory · %d changed"
          % (len(guides), data["_asof"], n_pct, n_adv, len(changed)))
    if changed:
        print("lastmod -> %s for %s%s" % (data[changed[0]]["m"], ", ".join(changed[:8]),
                                          " …" if len(changed) > 8 else ""))
    if lost:
        print("lost a figure: %s" % ", ".join(lost))


if __name__ == "__main__":
    main()
