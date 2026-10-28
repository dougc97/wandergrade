"""/dollar-strength — where the US dollar goes furthest right now, after
inflation — as pure functions, like the list pages (render_lists.py): the
cached documents in, a page body plus its <title>, description and sitemap
lastmod out. Nothing here reads the network or the server's caches, so
scripts/test_dollar_strength.py renders it from fixtures.

Every figure is one the site already shows, computed the same way:
  * the lede is the Data tab's "Overall dollar strength" (rates.compute_index:
    Jan 1999 = 100, equal-weighted geometric, chain-linked, ECB history),
    its 1-year and since-1999 changes, BOTH said to be before inflation, and
    the same ranges against the euro, yen, pound and franc alone — the core
    figure the chart's ⓘ gives, because the long-run rise is mostly
    high-inflation currencies sliding, not the dollar buying 30% more;
  * the table is the Currency tab's rows (the cached USD /api/rates), pegged
    currencies folded into their anchor's row as the tab folds them, ranked
    by pricelevel.real_fx_pct for the currency's representative country (the
    tab's currencyCountry), the figure behind its green rows and Top Picks'
    "your USD is unusually strong there";
  * prices are pricelevel.price_level against the US's own, with the income
    plausibility fit, carried to the day the server hands in (its UTC day,
    the date /cheapest and the Currency tab carry prices to), so the same
    inputs and day always print the same figures; a currency several places
    share shows the range across them, as the tab's cell does.

A currency with no honest inflation-adjusted figure (high inflation with no
current reading, no single country to adjust by, or too few days since a
change of exchange-rate regime) is listed apart with its before-inflation
move and the reason — never ranked on its nominal move.

Not advice: the page says what the numbers are (past moves and price
levels), never what to do with money. Class names avoid ad/adv/sponsor/
banner/promo and "advert" (EasyList); this page's own are .ds*.
"""

import datetime
import html
import math
from decimal import ROUND_HALF_UP, Decimal

from . import guide_facts, pricelevel, rates
from . import render_guide as rg
from . import render_lists as RL
from .picks import CUR_BY_ISO

PATH = "/dollar-strength"
TITLE_MAX = RL.TITLE_MAX
DESC_MAX = RL.DESC_MAX

# ---- mirrors of app.js (scripts/test_dollar_strength.py compares each) -----------
# Places the Currency tab prices but the site doesn't grade (app.js TABLE_CUR):
# kept out of CUR_BY_ISO so they never reach the rankings or the income fit.
TABLE_CUR = {"TO": "TOP", "WS": "WST", "MV": "MVR", "KY": "KYD", "BM": "BMD",
             "AG": "XCD", "DM": "XCD", "GD": "XCD", "KN": "XCD", "LC": "XCD", "VC": "XCD",
             "NC": "XPF", "PF": "XPF", "WF": "XPF"}
# A shared currency's representative country (app.js PRIMARY_COUNTRY): the
# inflation its after-inflation figure is netted against. XCD has none.
PRIMARY_COUNTRY = {"EUR": "DE", "XOF": "SN", "XAF": "CM", "USD": "US", "XCD": None}
CUR_SUPRA_FLAG = {"EUR": "🇪🇺", "XOF": "🌍", "XAF": "🌍", "XPF": "🌍", "XCD": "🌍", "XDR": "🌍"}
# Names for the places a currency row lists that have no guide (and so no
# guide name): the TABLE_CUR places and a few CUR_BY_ISO ones. The World
# Bank's own ("Macao SAR, China", "Micronesia, Fed. Sts.") is the last resort.
PLACE_NAMES = {"TO": "Tonga", "WS": "Samoa", "MV": "Maldives", "KY": "Cayman Islands", "BM": "Bermuda",
               "AG": "Antigua and Barbuda", "DM": "Dominica", "GD": "Grenada", "KN": "St Kitts and Nevis",
               "LC": "St Lucia", "VC": "St Vincent and the Grenadines", "NC": "New Caledonia",
               "PF": "French Polynesia", "WF": "Wallis and Futuna", "JE": "Jersey", "LI": "Liechtenstein",
               "SJ": "Svalbard", "MO": "Macau", "KM": "Comoros", "SC": "Seychelles", "MT": "Malta",
               "AD": "Andorra", "MC": "Monaco", "SM": "San Marino", "VA": "Vatican City",
               "MH": "Marshall Islands", "FM": "Micronesia", "PW": "Palau", "TC": "Turks and Caicos Islands",
               "VG": "British Virgin Islands", "BQ": "Caribbean Netherlands"}
# The chart's ⓘ names the core majors in this order (app.js CORE_NAME).
CORE_NAME = {"EUR": "euro", "JPY": "yen", "GBP": "pound", "CHF": "Swiss franc"}
CORE_ORDER = ("EUR", "JPY", "GBP", "CHF")

# The rates feed's (fxratesapi.com /currencies) own misspellings, put right here.
CUR_NAME_FIX = {"COP": "Colombian Peso"}

# A long "used in" list (the euro's 27) shows this many names, then "and N more".
NAMES_SHOWN = 3
INDEX_RANGES = ("1y", "all")


# ---- JavaScript number formatting, so a figure reads as the site prints it ---------

def js_fixed(x, dp):
    """Number.prototype.toFixed: the exact binary value, halves away from
    zero (Python's '%.2f' sends exact halves to even: 0.125 -> 0.12, JS 0.13);
    -0 prints as 0."""
    x = float(x)
    if x == 0:
        x = 0.0
    return str(Decimal(x).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP))


def signed_pct(p, dp=1):
    """app.js signedPct: a true minus, and no sign on a figure that rounds to
    nothing ("0.0%", never "+0.0%" or "−0.0%")."""
    s = js_fixed(p, dp)
    if s.lstrip("-").replace("0", "").replace(".", "") == "":
        return s.replace("-", "") + "%"
    return ("−" + s[1:] if s[0] == "-" else "+" + s) + "%"


def fmt_pct(p):
    """app.js fmtPct, the strength chart's change: two decimals under 10%."""
    a = abs(p)
    return ("+" if p >= 0 else "−") + js_fixed(a, 1 if a >= 10 else 2) + "%"


def fmt_idx(v):
    """app.js fmtIdx, the chart's headline level: one decimal from 10 up,
    else three significant figures (toPrecision(3); a level under 0.001,
    which toPrecision writes in exponent form, never occurs)."""
    if abs(v) >= 10:
        return js_fixed(v, 1)
    if v == 0:
        return "0.00"
    e = int(math.floor(math.log10(abs(v))))
    return js_fixed(v, max(0, 2 - e))


# ---- the index: the Data tab's figures, from the history the server caches ---------

def index_payloads(dates, cols, today=None):
    """{"1y": payload, "all": payload} for the dollar, each the numbers
    rates.compute_index(rng, "USD") returns on the ECB history — change_pct,
    core_change_pct, core, index_count, base_date, as_of and the headline
    level (its last point, to five significant figures) — "all" also carries
    "monthly", the level at each month's last fixing, for the page's small
    line. From
    (dates, cols) as rates.get_history() holds them: no fetch, so the server
    hands in its cached copy. None when there is too little to chain."""
    today = today or datetime.date.today()
    basket = rates._index_basket("USD")
    pts = rates._chain_index(dates, cols, basket)
    if len(pts) < 2:
        return None
    cpts = rates._chain_index(dates, cols, rates._index_basket("USD", rates.CORE))
    out = {}
    for rng in INDEX_RANGES:
        win = rates._window(pts, rng, today)
        first, last = win[0][1], win[-1][1]
        core = None
        if cpts:
            cw = rates._window(cpts, rng, today)
            if len(cw) > 1 and cw[0][1]:
                core = round((cw[-1][1] / cw[0][1] - 1.0) * 100.0, 2)
        out[rng] = {"range": rng, "base": "USD", "source": "ecb",
                    "change_pct": round((last / first - 1.0) * 100.0, 2) if first else 0.0,
                    "core_change_pct": core, "core": sorted(rates.CORE - {"USD"}),
                    "index_count": len(basket), "base_date": pts[0][0], "as_of": win[-1][0],
                    "level": float("%.5g" % last)}
    monthly = {}
    for d, v in pts:
        monthly[d[:7]] = (d, v)
    out["all"]["monthly"] = [{"date": d, "value": float("%.5g" % v)} for d, v in monthly.values()]
    return out


def _level(p):
    """The headline level of a payload: ours carries it, /api/index's is its
    last point (what the chart prints)."""
    if p.get("level") is not None:
        return p["level"]
    pts = p.get("index") or []
    return pts[-1]["value"] if pts else None


def _core_words(p):
    names = [CORE_NAME[c] for c in CORE_ORDER if c in (p.get("core") or [])]
    if not names:
        return ""
    return (", ".join(names[:-1]) + " and " + names[-1]) if len(names) > 1 else names[0]


def _spark(points, label, up):
    """The index since 1999 as one line, drawn by the server: a fixed-height
    box (no layout shift), stretched to the column, the stroke kept even by
    non-scaling-stroke; currentColor, so the theme's green or red. x by date,
    so the thinned /api/index points draw right too."""
    if len(points) < 2:
        return ""
    d0 = datetime.date.fromisoformat(points[0]["date"])
    span = (datetime.date.fromisoformat(points[-1]["date"]) - d0).days or 1
    vals = [p["value"] for p in points]
    lo, hi = min(vals + [100.0]), max(vals + [100.0])
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad
    w, h = 1000, 100
    y = lambda v: (hi - v) / (hi - lo) * h
    xy = " ".join("%.1f,%.1f" % ((datetime.date.fromisoformat(p["date"]) - d0).days / span * w, y(p["value"]))
                  for p in points)
    return ('<figure class="dsfig"><svg class="dsline %s" viewBox="0 0 %d %d" preserveAspectRatio="none" '
            'role="img" aria-label="%s"><line x1="0" y1="%.1f" x2="%d" y2="%.1f"/><polyline points="%s"/></svg>'
            "<figcaption><span>%s = 100</span><span>%s</span></figcaption></figure>"
            % ("up" if up else "down", w, h, html.escape(label, quote=True), y(100.0), w, y(100.0), xy,
               html.escape(rg.MON[d0.month - 1] + " " + str(d0.year)),
               html.escape("%s · %s" % (fmt_idx(vals[-1]), RL._day(points[-1]["date"])))))


def index_lede(idx):
    """(lede HTML, the small line or "", aria/description bits) from
    {"1y": payload, "all": payload}; ("", "", None) without them."""
    if not idx or not idx.get("1y") or not idx.get("all"):
        return "", "", None
    y1, al = idx["1y"], idx["all"]
    level = _level(al)
    if level is None:
        return "", "", None
    base = datetime.date.fromisoformat(al["base_date"])
    since = str(base.year)
    core = _core_words(al)
    tip = ("Exchange rates before inflation: a currency with high inflation slides against the rest over the "
           "years, so long ranges can run well ahead of what prices abroad feel like. Equal-weighted across %d "
           "currencies (geometric, chain-linked), %s %d = 100. Built on ECB euro reference rates (daily fixings, "
           "back to 1999)." % (al["index_count"], rg.MON[base.month - 1], base.year))
    lede = ("The overall dollar index (%s %d = 100) is <strong>%s</strong> as of %s: <strong>%s</strong> over "
            "the past year and <strong>%s</strong> since %s, both before inflation."
            % (rg.MON[base.month - 1], base.year, fmt_idx(level), html.escape(RL._day(al["as_of"])),
               fmt_pct(y1["change_pct"]), fmt_pct(al["change_pct"]), since))
    if core and y1.get("core_change_pct") is not None and al.get("core_change_pct") is not None:
        lede += (" Against the %s alone: <strong>%s</strong> over the past year, <strong>%s</strong> since %s."
                 % (core, fmt_pct(y1["core_change_pct"]), fmt_pct(al["core_change_pct"]), since))
    lede += ' <span class="dstip" title="%s">ⓘ</span>' % html.escape(tip, quote=True)
    aria = ("US dollar index since %s %d (= 100): %s on %s, %s since %s and %s over the past year, before inflation"
            % (rg.MON_FULL[base.month - 1], base.year, fmt_idx(level), RL._day(al["as_of"]),
               fmt_pct(al["change_pct"]), since, fmt_pct(y1["change_pct"])))
    if core and al.get("core_change_pct") is not None:
        aria += "; against the %s alone %s since %s" % (core, fmt_pct(al["core_change_pct"]), since)
    spark = _spark(al.get("monthly") or al.get("index") or [], aria + ".", al["change_pct"] >= 0)
    return lede, spark, {"level": level, "y1": y1["change_pct"], "all": al["change_pct"], "since": since}


# ---- the currencies ----------------------------------------------------------------

def currency_countries(code):
    """app.js currencyCountries: every place using `code`, CUR_BY_ISO's order
    first, then the table-only places."""
    out = [iso for iso, c in CUR_BY_ISO.items() if c == code]
    out += [iso for iso, c in TABLE_CUR.items() if c == code and iso not in out]
    return out


def currency_country(code):
    """app.js currencyCountry: the representative country, or None."""
    if code in PRIMARY_COUNTRY:
        return PRIMARY_COUNTRY[code]
    cs = currency_countries(code)
    return cs[0] if cs else None


def place_name(iso, ppp=None):
    return rg.name_for_iso(iso) or PLACE_NAMES.get(iso) or ((ppp or {}).get(iso) or {}).get("name") or iso


def table_rows(payload):
    """(rows, {anchor: [pegged codes]}): the Currency tab's rows — the USD
    feed without the dollar's own row, a pegged currency folded into its
    anchor's row when the anchor is listed (it moves with it by exactly the
    same %, before inflation)."""
    rows = [r for r in (payload or {}).get("rows") or [] if r.get("code") and r["code"] != "USD"]
    listed = {r["code"] for r in rows}
    folded, out = {}, []
    for r in rows:
        a = r.get("pegged_to")
        if a and a in listed:
            folded.setdefault(a, []).append(r["code"])
        else:
            out.append(r)
    return out, folded


def _as_date(d):
    try:
        return datetime.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def price_levels(payload, ppp, day=None):
    """{iso: price level vs the US} for every place the table can price:
    app.js priceLevel (tablePriceLevel for the table-only places, tested
    against the fit but never feeding it) over plAnchor("US").pl, carried to
    `day` — the server's UTC day, the date /cheapest (picks._score) and the
    Currency tab (app.js nowYearFrac) carry prices to, so a country prints
    one figure on all three — else the rates' own date."""
    when = _as_date(day) or _as_date((payload or {}).get("as_of"))
    now_y = pricelevel.now_year(when) if when else None
    rate_by_code = {r["code"]: r["rate_now"] for r in payload.get("rows") or [] if "code" in r and "rate_now" in r}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, CUR_BY_ISO, now_y)
    us = pricelevel.price_level("US", ppp, rate_by_code, CUR_BY_ISO, fit, now_y) or 1
    out = {}
    for iso in list(CUR_BY_ISO) + [i for i in TABLE_CUR if i not in CUR_BY_ISO]:
        if iso in CUR_BY_ISO or iso in pricelevel.PPP_UNIT:
            pl = pricelevel.price_level(iso, ppp, rate_by_code, CUR_BY_ISO, fit, now_y)
        else:
            pl = pricelevel.raw_price_level(iso, ppp, rate_by_code, TABLE_CUR, now_y)
            if pl is not None and pricelevel.implausible(iso, ppp, pl, fit):
                pl = None
        if pl:
            out[iso] = pl / us
    return out


def _pct(rel):
    return pricelevel.js_round(100 * rel)


def cur_name(code, name):
    """The feed's currency name, with its known misspellings put right."""
    return CUR_NAME_FIX.get(code) or name or code


def rank(payload, ppp, day=None):
    """(ranked, apart, folded): every Currency-tab row as a dict, those with
    an inflation-adjusted figure strongest first (ties by code), the rest
    with the reason they have none. `day`: price_levels' carry date."""
    rows, folded = table_rows(payload)
    pls = price_levels(payload, ppp, day)
    ranked, apart = [], []
    for r in rows:
        code, nominal = r["code"], r.get("strength_pct")
        if not isinstance(nominal, (int, float)) or isinstance(nominal, bool):
            continue
        iso = currency_country(code)
        places = currency_countries(code)
        priced = sorted(((pls[i], i) for i in places if i in pls), key=lambda t: t[0])
        row = {"code": code, "name": cur_name(code, r.get("name")), "iso": iso, "places": places, "nominal": nominal,
               "real": None, "adj": False, "priced": priced, "pegged": folded.get(code, []),
               "strong": False, "reason": None}
        if r.get("no_trend"):
            row["reason"] = ("trend", None)
        elif not iso:
            row["reason"] = ("country", None)
        else:
            real = pricelevel.real_fx_pct(nominal, iso, "US", ppp)
            if real is None:
                row["reason"] = ("infl", iso)
            else:
                row["real"] = real
                row["adj"] = pricelevel.infl_rate(iso, ppp) is not None
                # The tab's green rows ("stronger than usual after inflation",
                # app.js realGain): `favorable` is the feed's at-least-the-
                # threshold above the 1-yr average; still ahead after inflation.
                row["strong"] = bool(r.get("favorable") and r.get("watched", True) and real > 0)
        (apart if row["reason"] else ranked).append(row)
    ranked.sort(key=lambda x: (-x["real"], x["code"]))
    apart.sort(key=lambda x: x["code"])
    return ranked, apart, folded


# ---- cells ---------------------------------------------------------------------------

def _flag(code, iso):
    return CUR_SUPRA_FLAG.get(code) or (rg.flag_emoji(iso) if iso else "🌍")


def _place_link(iso, ppp):
    nm = html.escape(place_name(iso, ppp))
    slug = RL._slug(iso)
    return '<a href="/guide/%s">%s</a>' % (slug, nm) if slug else nm


def _used_in(row, ppp):
    """The places using the currency, its representative first, the rest by
    name; past NAMES_SHOWN + 1 it is cut to NAMES_SHOWN and "and N more",
    the whole list in the tooltip."""
    places = list(row["places"])
    if not places:
        return "—"
    rep = row["iso"] if row["iso"] in places else None
    rest = sorted((i for i in places if i != rep), key=lambda i: place_name(i, ppp))
    order = ([rep] if rep else []) + rest
    if len(order) <= NAMES_SHOWN + 1:
        return ", ".join(_place_link(i, ppp) for i in order)
    shown = order[:NAMES_SHOWN]
    full = ", ".join(place_name(i, ppp) for i in order)
    return ('%s <span class="dsmore" title="%s">and %d more</span>'
            % (", ".join(_place_link(i, ppp) for i in shown), html.escape(full, quote=True), len(order) - len(shown)))


def _infl_words(iso, ppp):
    """app.js inflGapText for a US traveller: "Bolivia ~12%/yr vs the US ~3%/yr"."""
    pc = lambda r: "~%s%%/yr" % str(pricelevel.js_round(r * 100)).replace("-", "−")
    return "%s %s vs the US %s" % (place_name(iso, ppp), pc(pricelevel.infl_rate(iso, ppp)),
                                   pc(pricelevel.us_infl(ppp)))


def _after(row, ppp):
    txt = signed_pct(row["real"])
    cls = "pos" if row["real"] > 0 and txt != "0.0%" else "neg" if row["real"] < 0 and txt != "0.0%" else ""
    if row["adj"]:
        tip = "After inflation: %s (World Bank)." % _infl_words(row["iso"], ppp)
        mark = ""
    else:
        tip = ("No inflation figure for %s: the exchange-rate move alone, rising local prices not netted out."
               % place_name(row["iso"], ppp))
        mark = '<sup class="fn">†</sup>'
    return '<span%s title="%s">%s</span>%s' % (' class="%s"' % cls if cls else "", html.escape(tip, quote=True),
                                                txt, mark)


def _prices(row, ppp):
    pr = row["priced"]
    if not pr:
        tip = ("No World Bank price data for %s." % ", ".join(place_name(i, ppp) for i in row["places"])
               if row["places"] else "Not matched to a country.")
        return '<span title="%s">—</span>' % html.escape(tip, quote=True)
    if len(pr) == 1:
        rel, iso = pr[0]
        return '<span title="%s">%d%%</span> <span class="band">%s</span>' % (
            html.escape("%s: local prices vs the US" % place_name(iso, ppp), quote=True), _pct(rel),
            html.escape(guide_facts.band(rel)))
    (lo, lo_iso), (hi, hi_iso) = pr[0], pr[-1]
    n = len(pr)
    mid = pr[(n - 1) // 2][0] if n % 2 else (pr[n // 2 - 1][0] + pr[n // 2][0]) / 2
    k = len(row["places"])
    count = ("%d places use the %s" % (n, row["code"]) if n >= k
             else "%d of the %d places using the %s have price data" % (n, k, row["code"]))
    tip = "%s %d%% to %s %d%% · %s (median %d%%)" % (
        place_name(lo_iso, ppp), _pct(lo), place_name(hi_iso, ppp), _pct(hi), count, _pct(mid))
    txt = "%d%%" % _pct(lo) if _pct(lo) == _pct(hi) else "%d–%d%%" % (_pct(lo), _pct(hi))
    return '<span title="%s">%s</span>' % (html.escape(tip, quote=True), txt)


def _currency_cell(row, n):
    """The currency's name cell; the rank rides in it on a phone and tablet,
    where the # column is hidden (as /cheapest's .rk)."""
    peg = ""
    if row["pegged"]:
        peg = (' <span class="dspegs" title="%s">+%d pegged</span>'
               % (html.escape("Fixed to the %s at official rates, so they move with it by exactly the same %% "
                              "before inflation: %s." % (row["code"], ", ".join(row["pegged"])), quote=True),
                  len(row["pegged"])))
    return ('<td class="name" data-l="Currency"><span class="rk">%d.</span> %s <span class="dscode">%s</span> %s%s</td>'
            % (n, _flag(row["code"], row["iso"]), html.escape(row["code"]), html.escape(row["name"]), peg))


def _reason(row, ppp):
    kind, iso = row["reason"]
    if kind == "infl":
        e = ppp.get(iso) or {}
        return ("%s's latest inflation figure (%s%% in %s) is older than its %s price data"
                % (place_name(iso, ppp), str(pricelevel.js_round(e.get("infl") or 0)).replace("-", "−"),
                   e.get("infl_year"), e.get("year")))
    if kind == "trend":
        return "fewer than %d days of rates since its exchange-rate regime changed" % rates.MIN_TREND_DAYS
    if row["places"]:
        return "shared by %d places, with no one country's inflation to adjust by" % len(row["places"])
    return "not matched to a country"


# ---- the page --------------------------------------------------------------------------

HEAD = (("#", ""),
        ("Currency", ""),
        ("Used in", "Every place using the currency; links open its guide."),
        ("Before inflation", "The dollar's exchange rate today vs its own average over the past year."),
        ("After inflation", "The same move net of the gap between local and US inflation (World Bank): "
                            "the figure behind the Currency tab's green rows and Top Picks."),
        ("Prices vs US", "Local prices vs the US (100%): World Bank PPP carried forward for inflation, at the "
                         "same day's exchange rates. A shared currency shows the range across its places."))


def dollar_strength(rates_payload, ppp, idx=None, today=None, price_day=None):
    """The /dollar-strength page. `rates_payload` is the cached USD /api/rates
    payload, `ppp` the PPP table, `idx` {"1y", "all"} index payloads
    (index_payloads, or /api/index answers) — each None when the server
    doesn't hold it, and then the page still renders, says so and reports
    `degraded` (the server sends it no-store). `price_day`: the UTC day
    prices are carried to (price_levels), `today` when not given."""
    today = today or datetime.date.today().isoformat()
    have_fx = bool(rates_payload and (rates_payload.get("rows") or []) and ppp)
    lede, spark, ix = index_lede(idx)
    notes = []
    if not ix:
        lede = ("The overall dollar index isn't loaded right now, so its figures are left out: this page is "
                "served uncached until it is back.")
    ranked, apart, folded = rank(rates_payload, ppp, price_day or today) if have_fx else ([], [], {})
    strong = sum(1 for r in ranked if r["strong"])
    asof = (rates_payload or {}).get("as_of") if have_fx else None

    body = ""
    if have_fx:
        trs = []
        for n, row in enumerate(ranked, 1):
            trs.append('<tr><td class="num" data-l="#">%d</td>%s%s%s%s%s</tr>' % (
                n, _currency_cell(row, n),
                RL._cell("Used in", _used_in(row, ppp)),
                RL._cell("Before inflation", signed_pct(row["nominal"])),
                RL._cell("After inflation", _after(row, ppp)),
                RL._cell("Prices vs US", _prices(row, ppp))))
        counts = ('<p class="sub"><strong>%d</strong> %s, the strongest dollar after inflation first: '
                  '<strong>%d</strong> %s stronger than usual <span class="dstip" title="%s">ⓘ</span></p>'
                  % (len(ranked), RL._plural(len(ranked), "currency", "currencies"), strong,
                     RL._plural(strong, "is", "are"), html.escape(
                      "At least %s%% above its 1-year average before inflation, and still ahead after the "
                      "inflation gap between the two countries — the Currency tab's green rows."
                      % js_fixed((rates_payload or {}).get("threshold_pct", 2.0), 0), quote=True)))
        body += counts + ('<div class="listbox"><table class="listtable dstable"><thead><tr>%s</tr></thead>'
                          "<tbody>%s</tbody></table></div>"
                          % ("".join('<th%s>%s</th>' % (' title="%s"' % html.escape(t, quote=True) if t else "",
                                                        html.escape(h)) for h, t in HEAD),
                             "".join(trs) or '<tr><td class="name" data-l="Currency">None today.</td></tr>'))
        if apart:
            items = "".join(
                '<li>%s <span class="dscode">%s</span> %s: <strong>%s</strong> before inflation — %s.</li>'
                % (_flag(r["code"], r["iso"]), html.escape(r["code"]), html.escape(r["name"]),
                   signed_pct(r["nominal"]), html.escape(_reason(r, ppp))) for r in apart)
            body += ('<h2>No inflation-adjusted figure (%d)</h2><ul class="dsnone">%s</ul>' % (len(apart), items))
        if any(not r["adj"] for r in ranked):
            notes.append("† No inflation figure for that country: the exchange-rate move alone.")
        notes.append("Before inflation: the dollar's exchange rate on %s vs its average over the past year. "
                     "After inflation: that move net of the gap between local and US inflation, for the "
                     "currency's main country (Germany for the euro). Prices are national averages vs the US. "
                     "Past moves, not a forecast." % html.escape(RL._day(asof)))
    else:
        missing = [w for w, have in (("the exchange rates", (rates_payload or {}).get("rows")),
                                     ("the World Bank price data", ppp)) if not have]
        plural = len(missing) > 1 or missing[0] == "the exchange rates"
        what = " and ".join(missing)
        notes.append("%s %s loaded right now, so the currency table is left out: this page is served uncached "
                     "until %s back." % (what[0].upper() + what[1:], "aren't" if plural else "isn't",
                                         "they are" if plural else "it is"))
    body += ('<p class="xlink">See also: <a href="/?tab=data">the Currency tab and the dollar chart</a> · '
             '<a href="/safe-and-cheap">the safest cheap countries</a> · '
             '<a href="/data">the price-level dataset</a>.</p>')

    parts = []
    if have_fx:
        parts.append("Exchange rates: fxratesapi.com, as of %s, each vs its own %d-day average"
                     % (html.escape(RL._day(asof)), (rates_payload or {}).get("baseline_days") or 364))
        parts.append("Inflation and PPP: World Bank")
    if ix:
        parts.append("Dollar index: ECB euro reference rates, to %s" % html.escape(RL._day(idx["all"]["as_of"])))
    sources = (" · ".join(parts) + ".") if parts else ""

    h1 = "Where the US dollar is strongest now, after inflation"
    title = RL._fit(["Where the US Dollar Is Strongest Now, Inflation-Adjusted",
                     "Where the US Dollar Is Strongest Now"], TITLE_MAX)
    day = RL._day(asof) or RL._day(today)
    if ranked:
        top = ranked[0]
        top_name = place_name(top["iso"], ppp) if top["iso"] and top["code"] not in CUR_SUPRA_FLAG else top["name"]
        cn = RL._plural(len(ranked), "currency", "currencies")
        desc = RL._fit([
            "%d %s ranked by the US dollar's move vs its 1-year average after inflation: %d stronger than "
            "usual, %s first at %s. As of %s." % (len(ranked), cn, strong, top_name, signed_pct(top["real"]), day),
            "%d %s ranked by the US dollar's move vs its 1-year average after inflation; %d stronger than "
            "usual. As of %s." % (len(ranked), cn, strong, day)], DESC_MAX)
    else:
        desc = RL._fit(["Where the US dollar goes furthest right now: every currency ranked by its move vs its "
                        "1-year average after inflation, with local prices vs the US."], DESC_MAX)
    page_html = ('<div class="listpage dspage"><h1>%s</h1><p class="lede">%s</p>%s%s%s%s</div>'
                 % (html.escape(h1), lede, spark, body,
                    "".join('<p class="note">%s</p>' % n for n in notes if n),
                    '<p class="asof">%s</p>' % sources if sources else ""))
    return {
        "path": PATH,
        "title": title, "desc": desc, "h1": h1,
        "html": page_html,
        # The day the figures are from: the rates' own date (never "today").
        "lastmod": RL.lastmod_of(asof),
        "degraded": not (have_fx and ix),
        "counts": {"ranked": len(ranked), "strong": strong, "apart": len(apart),
                   "pegged": sum(len(v) for v in folded.values())},
        "codes": {"ranked": [r["code"] for r in ranked], "apart": [r["code"] for r in apart]},
        "rows": ranked, "apart": apart, "index": ix,
    }
