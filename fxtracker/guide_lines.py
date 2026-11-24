"""A guide's A–F grade row (#guideGrades) and its fares-by-month strip
(#guideFares), in the page's HTML for the reader a first visit is: from the
US, "Any time" (graded for the first month of the next six), the default
priorities. A reader who doesn't run JavaScript (a crawler, an AI assistant)
used to get an empty grades line and no fares at all.

They are what app.js renderGuideGrades and renderGuideFares write for that
reader once its data is in, in the same markup, so when the browser draws
its own nothing moves; only the tooltips are left out (data-tip, title,
aria-label: the browser's copy brings them), all but two ⓘ's a reader
without the script needs too: the one after the month the grades are for
("Graded for December from the US…") and the fares strip's, which names
the search link's commission. index.html's pre-paint script
(server.py _GUIDE_HOLD) empties them again for a reader they aren't for —
whose saved home country, currency, priorities, advisory source or fare
currency, or whose link or six-month window, differ — who then gets the
page exactly as before; app.js keeps them until its own data is in.

Mirrors renderGuideGrades (valueScores through picks._score for the
month, safetyPill, guideAdvLevel, the 🧳 days) and renderGuideFares
(the country's one monthly curve, the Flights tab's typical range,
fareValueFill, fareShort) for a USD reader. scripts/test_guide_lines.py
runs app.js itself under jsc on one fixture and compares: change them
together.
"""

import datetime
import urllib.parse

from . import geo, guide_sizers, picks, pricelevel
from .home_picks import MON_ABBR, MON_FULL, advisory_by_iso, esc, flex_window, grade_cls, pill


# ---- the grades line ---------------------------------------------------------------

def guide_month(today):
    """app.js travelMonth() on a first visit: Any time's first month."""
    return flex_window(today)[0]


def adv_level(iso, payload):
    """app.js guideAdvLevel: the country's row, else its parent's (ADV_PARENT:
    England -> the UK, Guernsey -> the UK…), the last row winning; 0 without."""
    meta = {}
    for it in (payload or {}).get("items") or []:
        if it.get("iso"):
            meta[it["iso"]] = it
    parent = guide_sizers.ADV_PARENT.get(iso)
    it = meta.get(iso) or (meta.get(parent) if parent else None)
    return it.get("level") if it else 0


def score(iso, inputs, month):
    """app.js guideScores(iso, month) for a US reader — valueScores(iso,
    month, advisoryByIso(), buildFareContext(), anchor) for a country — or
    None (no price level, unrated, or Level 4).

    A place scoring leaves out on purpose (ADV_PARENT: England, Scotland,
    Wales, the Faroes, the Isle of Man, Guernsey) is graded on its parent's
    advisory, and on its parent's price level and currency where it has none
    of its own (the Faroes keep theirs), with its own weather and no fare:
    the parent's affordability and safety and its weather, averaged as
    picks._score averages, which itself never sees these places."""
    ppp = inputs["ppp"]
    rows = inputs["rates"].get("rows") or []
    rate_by_code = {r["code"]: r["rate_now"] for r in rows if "code" in r and "rate_now" in r}
    strength = {r["code"]: r["strength_pct"] for r in rows if "code" in r and "strength_pct" in r}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO)
    anchor = picks._price_level("US", ppp, rate_by_code, fit) or 1
    fares = picks.fare_context(inputs.get("flights"), geo.site_centroids()) if inputs.get("flights") else None
    if fares:
        fares["fv"] = inputs.get("fv")
    adv = advisory_by_iso(inputs["advisories"])
    clim = inputs["climate"]
    parent = guide_sizers.ADV_PARENT.get(iso)
    lvl = parent and (adv.get(iso) or adv.get(parent))
    if lvl:
        adv = dict(adv, **{iso: lvl})
        if picks._price_level(iso, ppp, rate_by_code, fit) is None:
            p = picks._score(parent, month, ppp, clim, rate_by_code, strength, adv, fit, fares, anchor)
            if not p:
                return None
            sc = (clim.get(iso) or {}).get("scores") or []
            wx = sc[month - 1] if len(sc) >= month else None
            comps = {"afford": p["afford"], "safe": p["safe"]}
            if wx is not None:
                comps["wx"] = wx
            num = sum(picks.WEIGHTS[k] * v for k, v in comps.items())
            den = sum(picks.WEIGHTS[k] for k in comps)
            return dict(p, iso=iso, name=(clim.get(iso) or {}).get("name") or iso, wx=wx, fly=None, fare=None,
                        fareEst=False, fly_basis=None, raw=num / den if den else 0,
                        value=picks.clamp100(num / den) if den else 0, pl_of=parent)
    return picks._score(iso, month, ppp, clim, rate_by_code, strength, adv, fit, fares, anchor)


def _ggf(emo, word, pill_html):
    return ('<span class="ggf"><span aria-hidden="true">%s</span><span class="vh">%s </span>%s</span>'
            % (emo, word, pill_html))


def grades(iso, inputs, today):
    """renderGuideGrades' line for the guide's own country."""
    month = guide_month(today)
    s = score(iso, inputs, month)
    act = (inputs["activities"].get(iso) or {})
    days = ('<span class="ggdays">🧳 %s–%s days</span>' % (act["days"][0], act["days"][1])
            if act.get("days") else "")
    grey = lambda txt: '<span class="gr grx">%s</span>' % txt
    if not s:
        lvl = adv_level(iso, inputs["advisories"])
        why = ("Level 4, do not travel: not graded" if lvl == 4
               else "No advisory from the governments we follow, so it isn't graded" if not lvl
               else "Not enough data to grade it")
        return grey("—") + '<span class="vh"> %s</span>' % esc(why) + days
    if s.get("fare") is None:
        fly = grey("—")
    elif s.get("fly_basis") != "month" and s.get("fareEst"):
        fly = grey("~" + picks.grade(s["fly"]))
    else:
        fly = pill(s["fly"])
    safe = ('<span class="gr %s">%s</span>' % (grade_cls(picks.SAFE_GRADE[s["advLvl"]]), picks.SAFE_GRADE[s["advLvl"]])
            if s.get("advLvl") else grey("—"))
    return (pill(s["value"], "big").replace('class="', 'data-gg="ov" class="', 1)
            + '<span class="ggnum" data-gg="num">%d</span>' % s["value"]
            + _ggf("💰", "Affordability", pill(s["afford"]))
            + _ggf("🛡️", "Safety", safe)
            + _ggf("🌤️", "Weather", grey("—") if s.get("wx") is None else pill(s["wx"]))
            + _ggf("✈️", "Flights", fly.replace('class="', 'data-gg="fly" class="', 1)) + days
            + '<span class="muted ggmon" data-tip="%s" title="">%s ⓘ</span>' % (esc(graded_tip(month)), MON_ABBR[month - 1]))


def graded_tip(month):
    """app.js guideGradedTip for a first visit (from the US, the default
    priorities): the one tooltip the served line carries, since it says
    which month the grades are for."""
    return ("Graded for %s from the US, weighted by your Top Picks priorities — the grades the Top Picks "
            "table and this page's 📸 share card show." % MON_FULL[month - 1])


# ---- the fares strip ---------------------------------------------------------------

def _js_num(x):
    """A JavaScript number as String(x) writes it: 62, not 62.0."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _hex(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def _mix(a, b, t):
    A, B = _hex(a), _hex(b)
    return "rgb(" + ",".join(str(pricelevel.js_round(v + (B[i] - v) * t)) for i, v in enumerate(A)) + ")"


def _fill(band, dev):
    """app.js fareValueFill for a banded month."""
    if band == "typical":
        return "#eef0f1"
    t = 0.45 + 0.55 * min(1, abs(dev) / 0.3)
    return _mix("#eef0f1", "#0a7d28" if band == "low" else "#b00020", t)


def _locale(n):
    """Number.prototype.toLocaleString() in en-US: grouped, up to 3 decimals."""
    if float(n).is_integer():
        return format(int(n), ",")
    return format(round(n, 3), ",").rstrip("0").rstrip(".")


def fare_short(n):
    """app.js fareShort."""
    if n < 1000:
        return _locale(n)
    if n < 1e6:
        return _locale(pricelevel.js_round(n / 100) / 10 if n < 1e4 else pricelevel.js_round(n / 1000)) + "K"
    return _locale(pricelevel.js_round(n / 1e5) / 10 if n < 1e7 else pricelevel.js_round(n / 1e6)) + "M"


# The Aviasales affiliate marker (app.js TP_MARKER): public by design, it
# ships in every flight link.
TP_MARKER = "738472"


def search_url(hub, dest, key, today):
    """app.js flightSearchURLFrom: an Aviasales search from `hub` to `dest`
    for the departure month `key` ("2026-12"): out on its 15th, or tomorrow
    once that has passed, back 10 days later, one traveller. None without a
    hub or a destination."""
    if not hub or not dest:
        return None
    dep = datetime.date(int(key[:4]), int(key[5:7]), 15)
    dep = max(dep, today + datetime.timedelta(days=1))
    ret = dep + datetime.timedelta(days=10)
    seg = lambda d: "%02d%02d" % (d.day, d.month)
    return ("https://www.aviasales.com/search/" + urllib.parse.quote(hub + seg(dep) + dest + seg(ret) + "1", safe="")
            + "?marker=" + TP_MARKER)


def _fare_link(curve, months, prices, sel, today, book):
    """app.js guideFareLink: the travel month's search from the route's hub,
    or the cheapest month's when it has no fare; "" where bookings aren't
    shown (`book` false: a government says not to go, or a list isn't in)."""
    if not book:
        return ""
    m = sel
    if prices[m - 1] is None:
        m = 0
        for i, p in enumerate(prices):
            if p is not None and (not m or p < prices[m - 1]):
                m = i + 1
    if not m:
        return ""
    key = "%d-%02d" % (today.year if m > today.month - 1 else today.year + 1, m)
    rec = months.get(key)
    hub = (curve or {}).get("hub")
    url = search_url(hub, (rec.get("dest") if isinstance(rec, dict) else None) or (curve or {}).get("dest"), key, today)
    if not url:
        return ""
    return ('<a href="%s" target="_blank" rel="sponsored nofollow noopener">✈️ Search %s flights from %s '
            '<span class="ext">↗</span></a>' % (esc(url), MON_ABBR[m - 1], esc(hub)))


def fares(iso, curve, fv, today, names, book=True):
    """renderGuideFares' strip for a USD reader, or "" (fewer than three
    months: the strip stays hidden). `curve` is flights.get_country_monthly
    for the US ({"origin", "hub", "months": {"YYYY-MM": {"price", "dest"…}}});
    `fv` the flight-value build (the Flights tab's typical range); `names`
    ISO -> the site's name (app.js countryName for a guide); `book` whether
    the strip's search link shows (app.js guideNoBookings(iso) === false)."""
    months = (curve or {}).get("months") or {}
    prices = []
    for m in range(1, 13):
        y = today.year if m > today.month - 1 else today.year + 1
        rec = months.get("%d-%02d" % (y, m))
        prices.append(rec.get("price") if isinstance(rec, dict) else None)
    known = [p for p in prices if p is not None]
    if len(known) < 3:
        return ""
    c = ((fv or {}).get("countries") or {}).get(iso) if (fv or {}).get("origin") == ((curve or {}).get("origin") or "US") else None
    typ = c if c and c.get("median") is not None else None
    srt = sorted(known)
    mid = len(srt) >> 1
    med = typ["median"] if typ else (srt[mid] if len(srt) % 2 else (srt[mid - 1] + srt[mid]) / 2)
    sel = guide_month(today)
    cols = []
    for i, p in enumerate(prices):
        cls = "col" + (" selmonth" if i + 1 == sel else "")
        if p is None:
            cols.append('<div class="%s"><div class="mscore">–</div><div class="fill na" style="height:8%%"></div>'
                        '<div class="mlabel">%s</div></div>' % (cls, MON_ABBR[i]))
            continue
        dev = p / med - 1
        band = ("low" if p < typ["lo"] else "high" if p > typ["hi"] else "typical") if typ else \
            ("low" if dev < -0.08 else "high" if dev > 0.08 else "typical")
        h = max(30, min(95, 62 - dev * 110))
        fill = "" if band == "typical" else ";background:" + _fill(band, dev)
        n = pricelevel.js_round(p)
        cols.append('<div class="%s"><div class="mscore"><span class="mfull">%s</span><span class="mshort">%s</span></div>'
                    '<div class="fill%s" style="height:%s%%%s"></div><div class="mlabel">%s</div></div>'
                    % (cls, _locale(n), fare_short(n), " typ" if band == "typical" else "", _js_num(h), fill,
                       MON_ABBR[i]))
    origin = names((curve or {}).get("origin") or "US") or "US"
    return ('<span class="fareshead">✈️ Fares by month<span class="legendinfo" data-tip="%s" title="">ⓘ</span> '
            '<span class="muted">%s</span></span><div class="bars farebars" role="img">%s</div>'
            '<div class="faresearch">%s</div>'
            % (esc(fares_tip(typ is not None)), esc("%s → %s · round-trip, USD" % (origin, names(iso) or iso)),
               "".join(cols), _fare_link(curve, months, prices, sel, today, book)))


def fares_tip(typ):
    """renderGuideFares' ⓘ for a USD reader (nothing converted); `typ`
    whether the Flights tab's range colours the bars. The strip's one
    tooltip kept: it names the search link's commission, which a reader
    without the script needs as much as one with it."""
    return ("Cheapest cached round-trip Aviasales has seen for each departure month — indicative, not live. "
            "Taller = cheaper. Colour = the month against the route's typical fare: green low, pale typical, red high"
            + (" (the Flights tab's range)." if typ else ".")
            + " The ✈️ search link is an affiliate link: we may earn a commission, at no extra cost to you.")
