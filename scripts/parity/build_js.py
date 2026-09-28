#!/usr/bin/env python3
"""Extract the browser's Top Picks scorer from public/app.js into a standalone
jsc program (scripts/parity/site.js) that scores every country from a fixture
and prints JSON — so parity.py can compare it, number for number, with the
newsletter's Python port (fxtracker/picks._score).

Named functions and consts are cut out of app.js by brace-matching from their
declaration, so the harness follows the code as it changes: renaming or
removing one of GRAB fails loudly here rather than silently comparing stale
copies. Everything the scorer reaches through globals (rates, ppp, climate,
the world map, the home currency, localStorage) is stubbed at the top from the
fixture.

Run:  /usr/bin/python3 scripts/parity/build_js.py   (then parity.py)
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "public", "app.js")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site.js")

# Declarations to lift, in an order that satisfies their references.
GRAB = [
    # CUR_BY_ISO is an IIFE that reads these two as it is built: they go first.
    "const EUROZONE", "const USD_USING", "const CUR_BY_ISO", "const PPP_UNIT",
    "const PL_PLAUSIBLE_SD", "const PRIMARY_COUNTRY", "const TABLE_CUR",
    "const WEIGHT_DEFS", "const PRI_W", "const clamp100",
    "function rateForCurrency", "function nowYearFrac", "function inflRate",
    "function inflUS", "function highInflUnknown", "function pplCarry",
    "function fxHomeIso", "function fxInflBasis", "function realFxPct",
    "function homeRatesNow", "function fxInfo", "function currencyCountries",
    "function currencyCountry", "function priceLevelRaw", "function _computePlFit",
    "function plFit", "function plImplausible", "function priceLevel",
    "function loadFactors", "function loadPriorities", "function loadWeights",
    "function countryCentroids", "function distKm", "function buildFareContext",
    "function valueScores", "function plAnchor",
]


def _decl_start(src, decl):
    """Index of `decl` at the start of a line (declarations are top-level)."""
    m = re.search(r"^" + re.escape(decl) + r"\b", src, re.M)
    if not m:
        sys.exit("build_js: %r not found in app.js — GRAB is stale" % decl)
    return m.start()


def _cut(src, decl):
    """The whole declaration: for a function, to its closing brace; for a
    const, to the ';' that ends the statement (brace/paren/bracket aware,
    string- and comment-aware enough for this file)."""
    i = _decl_start(src, decl)
    depth = 0
    in_str = None
    j = i
    n = len(src)
    is_fn = decl.startswith("function")
    while j < n:
        ch = src[j]
        if in_str:
            if ch == "\\":
                j += 2
                continue
            if ch == in_str:
                in_str = None
            elif in_str == "`" and ch == "$" and src[j + 1:j + 2] == "{":
                depth += 1          # template ${...}: braces inside count
                j += 1
        elif ch in "\"'`":
            in_str = ch
        elif src.startswith("//", j):
            j = src.index("\n", j)
        elif src.startswith("/*", j):
            j = src.index("*/", j) + 1
        elif ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
            if is_fn and depth == 0 and ch == "}":
                return src[i:j + 1]
        elif ch == ";" and depth == 0 and not is_fn:
            return src[i:j + 1]
        j += 1
    sys.exit("build_js: unterminated declaration %r" % decl)


PRELUDE = r'''
// ---- harness prelude: what app.js provides as globals ----------------------
"use strict";
const FIX = JSON.parse(read(ARGS_FIXTURE));
const $ = () => null;
const localStorage = { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = String(v); } };
const esc = (s) => String(s == null ? "" : s);
let homeBase = FIX.home_currency || "USD";
let lastRates = FIX.rates, dataRates = null, homeRates = null;
let ppp = FIX.ppp, climate = FIX.climate, worldGeo = FIX.world;
let priorities = null, factors = null;
let _centroids = null, _plFitFor, _plFitVal;
let flightsData = FIX.flights;
let ISO2SLUG = null;
function guidePassport() { return FIX.home_iso || "US"; }
function originIso() { return FIX.home_iso || "US"; }
function reducedMotion() { return true; }
// countryName only labels; the numbers never depend on it (and jsc has no Intl.DisplayNames).
function countryName(iso) { return (climate[iso] && climate[iso].name) || (ppp[iso] && ppp[iso].name) || iso; }
'''

EPILOGUE = r'''
// ---- harness main: score every country the way renderValue does ------------
function ADV_BY_ISO() {
  const out = {};
  for (const it of FIX.advisories.items || []) {
    if (it.iso && it.level && it.level > (out[it.iso] || 0)) out[it.iso] = it.level;
  }
  return out;
}
const advMap = ADV_BY_ISO();
const fares = buildFareContext();
const A = plAnchor(originIso());
const out = { anchor_pl: A.pl, scored: {} };
for (const iso in CUR_BY_ISO) {
  const s = valueScores(iso, FIX.month, advMap, fares, A.pl);
  if (s) out.scored[iso] = { afford: s.afford, safe: s.safe, wx: s.wx, fly: s.fly, value: s.value,
                             pl: s.pl, fare: s.fare, fareEst: s.fareEst, fx: s.fx, advLvl: s.advLvl };
}
print(JSON.stringify(out));
'''


def main():
    with open(APP, encoding="utf-8") as f:
        src = f.read()
    parts = [PRELUDE]
    for decl in GRAB:
        parts.append(_cut(src, decl))
    parts.append(EPILOGUE)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts))
    print("wrote %s (%d declarations)" % (OUT, len(GRAB)))


if __name__ == "__main__":
    main()
