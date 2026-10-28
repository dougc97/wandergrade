"""The homepage's Top Picks table and the line above it, in the page's own
HTML for the view a first visit opens on: from the US, "Any time" (each
country on its best month of the next six), every filter at its default.
A reader who doesn't run JavaScript (a crawler, an AI assistant) used to
get an empty skeleton table here.

It is the table app.js renderGradeTable writes for that view, row for row
and in the same markup, so when the browser's own copy replaces it nothing
moves. Only the tooltips are left out (data-tip, title, aria-label: the
browser's copy brings them). index.html keeps today's skeleton beside it,
hidden; its inline script shows the skeleton instead for a reader whose
link, saved settings or six-month window differ from the served view (a
saved home country, a month in the link, Top 10…), who then gets the
client's rows exactly as before. app.js keeps these rows until its own
data is in (holdServedPicks), then draws the same ones.

Mirrors renderValue's ranking for that view (valueScores per month through
picks._score, which scripts/parity/parity.py holds equal to it; flexWindow,
bestOfWindow, cheapestFareMonth, rankValue; the safety floor "b", the
popular split, Top 5) and renderGradeTable's row markup (flexChips,
seasonalTags, the price-data ⚠️, fxMark, safetyPill, advMovedMark, the
weather pill and ⚠️, seasonStrip, the flights pill, coverageMark) and
renderValue's picksNote. scripts/test_home_picks.py runs app.js itself under
jsc on one fixture and compares: change them together.
"""

import datetime
import re

from . import picks, pricelevel

MON_FULL = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
MON_ABBR = [m[:3] for m in MON_FULL]
FLEX_MONTHS, FLEX_PARTIAL_DAYS = 6, 10      # app.js FLEX_MONTHS, FLEX_PARTIAL_DAYS
PICK_COUNT = 5                              # the Show default (index.html #pickCount)
FX_MARK_PCT = 5                             # app.js FX_MARK_PCT
PPP_DRIFT_WARN = 15                         # app.js PPP_DRIFT_WARN
ADV_MOVE_DAYS = 180                         # app.js ADV_MOVE_DAYS
_POPULAR_N = picks.POPULAR_N

# app.js ACT_EMOJI, in its order (the first match wins).
ACT_EMOJI = [
    (r"aurora|northern lights|white nights", "🌌"), (r"whale|dolphin", "🐋"),
    (r"cherry blossom|sakura|blossom", "🌸"), (r"autumn leaves|foliage|fall colou?r|autumn colou?r", "🍁"),
    (r"migration", "🦓"), (r"garden|tulip|flower|keukenhof", "🌷"),
    (r"railway|train|trans-?siberian|metro|tram", "🚆"), (r"\bice\b|frozen|glacier", "🧊"),
    (r"opera|ballet|theat", "🎭"), (r"hermitage|museum|galler|\bart\b", "🖼️"), (r"red square", "🏛️"),
    (r"cheese", "🧀"), (r"rice terrace|paddy", "🌾"), (r"tulip", "🌷"),
    (r"beer|oktoberfest|brewery|pub", "🍺"), (r"flamenco|tango|salsa|dance", "💃"),
    (r"tapas|hawker|food|cuisine|street\s?food|culinary|dining", "🍜"),
    (r"architecture|skyline|gardens?", "🏛️"), (r"reef|snorkel|manta|coral|marine|lagoon|\bray", "🐠"),
    (r"turtle", "🐢"), (r"penguin", "🐧"), (r"bird|flamingo", "🦤"), (r"outback|savanna", "🐪"),
    (r"resort", "🏝️"), (r"cathedral|basilica", "⛪"), (r"canal", "🛶"), (r"lighthouse", "🗼"),
    (r"petra|nabataean|pyramid|ruins|ancient|archaeolog", "🏺"), (r"dead sea|salt flat|salar|uyuni", "🧂"),
    (r"crater|caldera", "🌋"), (r"canyon|gorge", "🏜️"), (r"baobab", "🌳"), (r"gorilla|chimp|lemur|monkey", "🐒"),
    (r"moai|easter island|statue", "🗿"), (r"gobi|kalahari|atacama|sahara|desert|dune", "🏜️"),
    (r"whale shark|diving|scuba|snorkel", "🤿"), (r"festival|naadam|carnival", "🎉"),
    (r"geothermal|hot spring|onsen|thermal|spa", "♨️"), (r"zip-?lin|bungee|adventure sport", "🪂"),
    (r"fjord", "🏔️"), (r"wine|vineyard|port wine", "🍷"),
    (r"div(e|ing)|snorkel|scuba", "🤿"), (r"surf", "🏄"), (r"ski|snowboard|\bsnow\b", "🎿"),
    (r"balloon", "🎈"), (r"shrine|pagoda", "⛩️"), (r"temple", "🛕"), (r"mosque", "🕌"),
    (r"church|cathedral|basilica|monaster", "⛪"), (r"ruins|ancient|archaeolog", "🏺"),
    (r"castle|palace|kremlin|\bfort\b|citadel", "🏰"), (r"safari|wildlife|gorilla|big five|game drive", "🦁"),
    (r"hik|trek|trail", "🥾"), (r"volcano", "🌋"), (r"mountain|peak|everest|kilimanjaro|alps|valley", "⛰️"),
    (r"desert|dune|sahara", "🏜️"), (r"waterfall|falls", "💦"), (r"lake", "🏞️"),
    (r"cruise|boat|sail|kayak|raft|river", "⛵"), (r"rainforest|jungle|forest", "🌴"),
    (r"wine|vineyard", "🍷"), (r"coffee|\btea\b", "☕"),
    (r"food|cuisine|cooking|culinary|dining|street\s?food", "🍜"),
    (r"market|bazaar|souk", "🛍️"), (r"museum|galler|\bart\b", "🖼️"),
    (r"festival|carnival|songkran|christmas", "🎉"), (r"nightlife|\bbar\b|\bclub\b|party", "🍸"),
    (r"spa|onsen|hot spring|thermal|wellness", "♨️"), (r"beach|coast|island", "🏖️"),
    (r"village", "🏘️"), (r"cit(y|ies)|town|skyline|metropolis", "🏙️"), (r"square|plaza|registan", "🏛️"),
    (r"steppe|nomad", "🐪"), (r"space|cosmodrome|baikonur", "🚀"), (r"histor|heritage", "🏛️"),
    (r"road trip|\broad\b", "🚗"), (r"bike|cycl", "🚲"),
]
_ACT_RE = [(re.compile(p), e) for p, e in ACT_EMOJI]


def esc(s):
    """app.js esc: & < > " ' (the apostrophe as &#39;, not html.escape's &#x27;)."""
    return (str("" if s is None else s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


# ---- the window -------------------------------------------------------------------

def flex_window(today):
    """app.js flexWindow: six months, starting next month once fewer than
    FLEX_PARTIAL_DAYS of this one remain (today counted). `today` is the
    reader's local date; the server's is UTC (the inline script compares)."""
    nxt = datetime.date(today.year + today.month // 12, today.month % 12 + 1, 1)
    left = (nxt - today).days
    start = today.month if left < FLEX_PARTIAL_DAYS else today.month - 1
    return [(start + i) % 12 + 1 for i in range(FLEX_MONTHS)]


def flex_span(win):
    return MON_ABBR[win[0] - 1] + "–" + MON_ABBR[win[-1] - 1]


def best_of_window(by_month, win, key="value", ok=None, own=None):
    """app.js bestOfWindow: {"s", "month"} for a country's best month of the
    window by `key` ("value", or "wx": comfort, then value), the sooner on a
    tie; with `ok` (a budget test) the best month it passes, preferring one
    `own` accepts (a month with its own fare) — "moved"/"own" say so. None
    when no month scored."""
    def pick(test):
        best = best_m = None
        for m in win:
            s = by_month.get(m)
            if not s or (test and not test(s)):
                continue
            if best is None:
                better = True
            elif key == "wx":
                a = s.get("wx") if s.get("wx") is not None else -1
                b = best.get("wx") if best.get("wx") is not None else -1
                better = a > b or (a == b and s["value"] > best["value"])
            else:
                better = s["value"] > best["value"]
            if better:
                best, best_m = s, m
        return {"s": best, "month": best_m} if best is not None else None

    best = pick(None)
    if not best or not ok:
        return best
    if own:
        mine = pick(lambda s: own(s) and ok(s))
        if mine:
            return best if mine["month"] == best["month"] else dict(mine, moved=True, own=True)
    if ok(best["s"]):
        return best
    fit = pick(ok)
    return dict(fit, moved=True) if fit else best


def flight_month_key(fv, m, today):
    """app.js flightMonthKey: month m's key in the payload's window, else its
    next occurrence."""
    mm = "%02d" % m
    for k in (fv or {}).get("months") or []:
        if str(k)[5:] == mm:
            return k
    return "%d-%s" % (today.year if m > today.month - 1 else today.year + 1, mm)


def cheapest_fare_month(c, keys):
    """app.js cheapestFareMonth: the window's cheapest cached month on a route
    with a typical range, the sooner on an equal fare."""
    if not c or c.get("median") is None or not c.get("curve"):
        return None
    best = None
    for k in keys:
        rec = c["curve"].get(k)
        if not rec or rec[0] is None:
            continue
        if best is None or rec[0] < best["price"]:
            best = {"key": k, "month": int(k[5:]), "price": rec[0]}
    return best


# ---- the ranking -------------------------------------------------------------------

def advisory_by_iso(payload):
    """app.js advisoryByIso: {iso: level}, the LAST row for an ISO winning (the
    page's own read; picks.advisory_levels keeps the most cautious)."""
    out = {}
    for it in (payload or {}).get("items") or []:
        if it.get("iso"):
            out[it["iso"]] = it.get("level")
    return out


def rank(inputs, today):
    """The view's Top 5, best first, each a picks._score dict for its best
    month of the window plus "month" and, where the route's cheapest month
    is another, "cheap_fly" ({month, price}). `inputs`: ppp, climate, rates
    (the USD /api/rates payload), advisories (the US /api/advisories
    payload), flights (/api/flights?origin=US, or None), fv (its flight-value
    build, or None), popular (the popular set)."""
    ppp, clim = inputs["ppp"], inputs["climate"]
    rows = inputs["rates"].get("rows") or []
    rate_by_code = {r["code"]: r["rate_now"] for r in rows if "code" in r and "rate_now" in r}
    strength = {r["code"]: r["strength_pct"] for r in rows if "code" in r and "strength_pct" in r}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO)
    anchor = picks._price_level("US", ppp, rate_by_code, fit) or 1
    fares = picks.fare_context(inputs.get("flights")) if inputs.get("flights") else None
    fv = inputs.get("fv")
    if fares:
        fares["fv"] = fv
    adv = advisory_by_iso(inputs["advisories"])
    win = flex_window(today)
    fv_c = (fv or {}).get("countries") if fv and fv.get("origin") == "US" else None
    keys = [flight_month_key(fv, m, today) for m in win]
    scored = []
    for iso in picks.CUR_BY_ISO:
        by_month = {m: picks._score(iso, m, ppp, clim, rate_by_code, strength, adv, fit, fares, anchor)
                    for m in win}
        b = best_of_window({m: s for m, s in by_month.items() if s}, win)
        if not b:
            continue
        # valueScores' flyMissing: no flights measure although fares are in.
        s = dict(b["s"], month=b["month"], fly_missing=b["s"].get("fly") is None and bool(fares))
        ch = cheapest_fare_month(fv_c.get(iso), keys) if fv_c else None
        if ch and ch["month"] != s["month"]:
            s["cheap_fly"] = ch
        scored.append(s)
    # rankValue: value, then the unrounded score, then the name.
    scored.sort(key=lambda s: (-s["value"], -s["raw"], s["name"]))
    eligible = [s for s in scored if s["advLvl"] != 3]          # safety floor "b"
    popular = [s for s in eligible if s["iso"] in inputs["popular"]]
    top = (popular or eligible)[:PICK_COUNT]
    # renderGradeTable re-sorts by the Overall column (raw, descending; stable).
    return sorted(top, key=lambda s: -s["raw"]), win, bool(popular)


# ---- the row's pieces (renderGradeTable's helpers) ------------------------------

def grade_cls(g):
    return "gr" + g.replace("+", "p").replace("—", "x")


def pill(score, extra=""):
    g = picks.grade(score)
    return '<span class="gr %s%s">%s</span>' % (grade_cls(g), " " + extra if extra else "", g)


def activity_emoji(text):
    t = str(text or "").lower()
    for rx, em in _ACT_RE:
        if rx.search(t):
            return em
    return "📍"


def hazards_for(acts, iso, month):
    return [h for h in ((acts.get(iso) or {}).get("hazards") or []) if month in (h.get("months") or [])]


def seasonal_tag(acts, iso, month):
    """seasonalTags(iso, month, 1, true): Any time's one tag."""
    hits = [x for x in ((acts.get(iso) or {}).get("seasonal") or []) if month in (x.get("months") or [])]
    if not hits:
        hz = [h.get("note") for h in hazards_for(acts, iso, month) if h.get("note")]
        if not hz:
            return ""
        short = re.split(r"[—.(]", hz[0])[0].strip()
        if len(short) > 30:
            short = short[:29].rstrip() + "…"
        return '<span class="seastag seasoff">⚠️ %s</span>' % esc(short)
    x = hits[0]
    return '<span class="seastag">%s %s</span>' % (activity_emoji(x.get("what")), esc(x.get("what")))


def seasons(scores):
    valid = [s for s in scores if s is not None]
    if not valid:
        return ["na"] * len(scores)
    mn, mx = min(valid), max(valid)
    rng = (mx - mn) or 1
    out = []
    for s in scores:
        if s is None:
            out.append("na")
        else:
            f = (s - mn) / rng
            out.append("peak" if f >= 0.66 else "off" if f <= 0.34 else "shoulder")
    return out


def season_strip(clim, iso, month):
    cl = clim.get(iso) or {}
    if len(cl.get("scores") or []) != 12:
        return ""
    seas = seasons(cl["scores"])
    good = seas.count("peak")
    cells = "".join('<i class="sc %s%s" data-m="%d"></i>' % (s, " now" if i + 1 == month else "", i + 1)
                    for i, s in enumerate(seas))
    return '<span class="seasonstrip%s" role="img">%s</span>' % (" scarce" if 0 < good <= 4 else "", cells)


def ppp_year(ppp):
    """app.js pppYear: the year most countries' price data is from."""
    n = {}
    for v in ppp.values():
        y = isinstance(v, dict) and v.get("year")
        if y:
            n[y] = n.get(y, 0) + 1
    # Object.keys order is ascending for integer-like keys; sort is stable.
    return sorted(sorted(n), key=lambda y: -n[y])[0] if n else None


def ppp_note(iso, ppp, strength):
    """Whether app.js pppNotes(iso) says anything (the afford pill's ⚠️):
    the currency well below its average (pppDrift), high inflation with no
    current figure (highInflUnknown), or old World Bank data (pppAgeNote)."""
    code = picks.CUR_BY_ISO.get(iso)
    nom = strength.get(code) if code and code != "USD" else None
    if isinstance(nom, (int, float)) and not isinstance(nom, bool):
        real = pricelevel.real_fx_pct(nom, iso, "US", ppp)
        if (nom if real is None else real) >= PPP_DRIFT_WARN:
            return True
    if pricelevel.high_infl_unknown(iso, ppp):
        return True
    y, most = (ppp.get(iso) or {}).get("year"), ppp_year(ppp)
    return bool(y and most and y < most - 1)


def fx_mark(s):
    """fxMark: the real move vs the 1-yr average where it is 5% or more."""
    pct = s.get("fx")
    if not isinstance(pct, (int, float)) or abs(pct) < FX_MARK_PCT:
        return ""
    up = pct > 0
    return '<span class="fxmark %s">%s%d%%</span>' % ("fxup" if up else "fxdn", "+" if up else "−",
                                                     abs(pricelevel.js_round(pct)))


def adv_moved(item, today):
    """advMovedMark: ▲/▼ for a level that moved within ADV_MOVE_DAYS."""
    on = str((item or {}).get("changed") or (item or {}).get("updated") or "")
    if not item or not item.get("change") or not on:
        return ""
    if on < (today - datetime.timedelta(days=ADV_MOVE_DAYS)).isoformat():
        return ""
    up = item["change"] == "up"
    return '<span class="advmv %s">%s</span>' % ("chup" if up else "chdown", "▲" if up else "▼")


def flag(iso):
    return picks.flag(iso) or "🌍"


# ---- the table and the note ---------------------------------------------------------

_HEAD = ('<table class="gradetable">\n'
         '    <thead><tr><th><span class="vh">Rank</span></th><th class="dest sortable" data-sk="dest" '
         'data-sortdir="" aria-sort="none"><button type="button" class="sortbtn">Destination</button></th>\n'
         '      <th class="sortable" data-sk="afford" data-sortdir="" aria-sort="none"><button type="button" '
         'class="sortbtn"><span aria-hidden="true">💰</span> <span class="thword">Affordability</span></button></th>\n'
         '      <th class="sortable" data-sk="safety" data-sortdir="" aria-sort="none"><button type="button" '
         'class="sortbtn"><span aria-hidden="true">🛡️</span> <span class="thword">Safety</span></button></th>\n'
         '      <th class="sortable" data-sk="weather" data-sortdir="" aria-sort="none"><button type="button" '
         'class="sortbtn"><span aria-hidden="true">🌤️</span> <span class="thword">Weather</span></button></th>\n'
         '      <th class="sortable" data-sk="flights" data-sortdir="" aria-sort="none"><button type="button" '
         'class="sortbtn"><span aria-hidden="true">✈️</span> <span class="thword">Flights</span></button></th>\n'
         '      <th class="ovh sortable" data-sk="overall" data-sortdir="desc" aria-sort="descending"><button '
         'type="button" class="sortbtn">Overall</button></th></tr></thead>\n'
         '    <tbody>')


def _row(i, s, inputs, slugs, meta, today):
    iso, rm = s["iso"], s["month"]
    acts, clim = inputs["activities"], inputs["climate"]
    e = esc(iso)
    href = "/guide/" + slugs[iso] if iso in slugs else "/?tab=guide&gc=" + iso
    chips = '<span class="seastag seasbest"><span class="sbw">Best in </span>%s</span>' % MON_ABBR[rm - 1]
    if s.get("cheap_fly"):
        chips += ('<span class="seastag seasfly">✈️ <span class="sfw">cheapest </span>%s</span>'
                  % MON_ABBR[s["cheap_fly"]["month"] - 1])
    hz = hazards_for(acts, iso, rm)
    wx = ('<span class="gr grx">—</span>' if s.get("wx") is None else pill(s["wx"])) \
        + ('<span class="hzmark">⚠️</span>' if hz else "")
    if s.get("fare") is None:
        fly = '<span class="gr grx">—</span>'
    elif s.get("fly_basis") != "month" and s.get("fareEst"):
        fly = '<span class="gr grx" role="img">~%s</span>' % picks.grade(s["fly"])
    else:
        fly = pill(s["fly"])
    # coverageMark: weather and flights are the measures a country can lack.
    missing = (s.get("fly_missing"), s.get("wx") is None)
    cov = ('<span class="covmark">%d/4</span>' % (4 - sum(missing))) if any(missing) else ""
    safe = ('<span class="gr %s">%s</span>' % (grade_cls(picks.SAFE_GRADE[s["advLvl"]]), picks.SAFE_GRADE[s["advLvl"]])
            if s.get("advLvl") else '<span class="gr grx">—</span>')
    return ('<tr data-iso="%s" data-m="%d" class="flexrow" style="--i:%d">\n'
            '      <td class="rank">#%d</td>\n'
            '      <td class="dest"><a class="destlink" href="%s"><span aria-hidden="true">%s</span> %s</a>%s%s</td>\n'
            '      <td class="scell" data-go="afford" data-iso="%s"><span class="pillwrap">%s%s%s</span></td>\n'
            '      <td class="scell" data-go="advisory" data-iso="%s"><span class="pillwrap">%s%s</span></td>\n'
            '      <td class="scell" data-go="weather" data-iso="%s"><span class="pillwrap">%s</span>%s</td>\n'
            '      <td class="scell" data-go="flights" data-iso="%s"><span class="pillwrap">%s</span>'
            '<span class="rowfares" data-iso="%s" data-m="%d"></span></td>\n'
            '      <td class="overall">%s<span class="ovnums"><span class="grnum">%d</span>%s</span></td>\n'
            '    </tr>'
            % (e, rm, i, i + 1, esc(href), flag(iso), esc(s["name"]), chips, seasonal_tag(acts, iso, rm),
               e, pill(s["afford"]), '<span class="hzmark">⚠️</span>'
               if ppp_note(iso, inputs["ppp"], inputs["strength"]) else "", fx_mark(s),
               e, safe, adv_moved(meta.get(iso), today),
               e, wx, season_strip(clim, iso, rm),
               e, fly, e, rm,
               pill(s["value"], "big"), s["value"], cov))


def table(top, inputs, slugs, today):
    """renderGradeTable's table for the rows (the header as markSort leaves it)."""
    meta = {}
    for it in (inputs["advisories"] or {}).get("items") or []:
        if it.get("iso"):
            meta[it["iso"]] = it                     # advisoryMetaByIso: the last row
    inputs = dict(inputs, strength={r["code"]: r["strength_pct"] for r in inputs["rates"].get("rows") or []
                                    if "code" in r and "strength_pct" in r})
    return _HEAD + "".join(_row(i, s, inputs, slugs, meta, today) for i, s in enumerate(top)) + "</tbody></table>"


def note(win, popular_found, data_backed):
    """renderValue's picksNote for the view (no budget, nothing hidden)."""
    ranked_by = "each one's best month in " + flex_span(win)
    if popular_found:
        return ("🌍 Popular destinations, ranked by %s%s — more finds under 💎 Hidden gems."
                % (ranked_by, ' <span class="muted">ⓘ</span>' if data_backed else ""))
    return "Ranked by %s — no mainstream destinations match these filters, so showing everything." % ranked_by


def popular_set(arrivals):
    """app.js ensurePopularity: the top POPULAR_N of CUR_BY_ISO by tourism
    receipts, or None (the fallback set stays) with 20 or fewer figures."""
    if not arrivals or len(arrivals) <= 20:
        return None
    ranked = sorted((iso for iso in picks.CUR_BY_ISO if arrivals.get(iso) is not None),
                    key=lambda i: -arrivals[i])
    return set(ranked[:_POPULAR_N])


def build(inputs, slugs, today=None):
    """{"window": "11,12,1,2,3,4", "table": html, "note": html} for the served
    view, or None without the inputs it needs. `inputs` as rank() takes it,
    plus activities, and popular (None: app.js's own fallback set, no ⓘ)."""
    today = today or datetime.date.today()
    if not (inputs.get("rates") and inputs["rates"].get("rows") and inputs.get("ppp")
            and inputs.get("climate") and inputs.get("advisories") and inputs.get("activities")):
        return None
    backed = inputs.get("popular") is not None
    inputs = dict(inputs, popular=inputs["popular"] if backed else picks.FALLBACK_POPULAR)
    top, win, found = rank(inputs, today)
    if not top:
        return None
    return {"window": ",".join(str(m) for m in win), "table": table(top, inputs, slugs, today),
            "note": note(win, found, backed)}
