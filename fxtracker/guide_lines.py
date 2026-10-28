"""A guide's A–F grade row (#guideGrades) and its fares-by-month strip
(#guideFares), in the page's HTML for the reader a first visit is: from the
US, "Any time" (graded for the first month of the next six), the default
priorities. A reader who doesn't run JavaScript (a crawler, an AI assistant)
used to get an empty grades line and no fares at all.

They are what app.js renderGuideGrades and renderGuideFares write for that
reader once its data is in, in the same markup, so when the browser draws
its own nothing moves; only the tooltips are left out (data-tip, title,
aria-label: the browser's copy brings them). index.html's pre-paint script
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

from . import guide_sizers, picks, pricelevel
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
    """valueScores(iso, month, advisoryByIso(), buildFareContext(), anchor)
    for a US reader, or None (no price level, unrated, or Level 4)."""
    ppp = inputs["ppp"]
    rows = inputs["rates"].get("rows") or []
    rate_by_code = {r["code"]: r["rate_now"] for r in rows if "code" in r and "rate_now" in r}
    strength = {r["code"]: r["strength_pct"] for r in rows if "code" in r and "strength_pct" in r}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO)
    anchor = picks._price_level("US", ppp, rate_by_code, fit) or 1
    fares = picks.fare_context(inputs.get("flights")) if inputs.get("flights") else None
    if fares:
        fares["fv"] = inputs.get("fv")
    return picks._score(iso, month, ppp, inputs["climate"], rate_by_code, strength,
                        advisory_by_iso(inputs["advisories"]), fit, fares, anchor)


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
            + '<span class="muted">ⓘ</span>')


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


def fares(iso, curve, fv, today, names):
    """renderGuideFares' strip for a USD reader, or "" (fewer than three
    months: the strip stays hidden). `curve` is flights.get_country_monthly
    for the US ({"origin", "months": {"YYYY-MM": {"price"…}}}); `fv` the
    flight-value build (the Flights tab's typical range); `names` ISO -> the
    site's name (app.js countryName for a guide)."""
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
    return ('<span class="fareshead">✈️ Fares by month<span class="legendinfo">ⓘ</span> <span class="muted">%s</span>'
            '</span><div class="bars farebars" role="img">%s</div>'
            % (esc("%s → %s · round-trip, USD" % (origin, names(iso) or iso)), "".join(cols)))
