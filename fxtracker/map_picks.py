"""The homepage's served pick lists under the Safety and Flights maps
("Recently changed", "Below typical for <month>"), with the words the lists
will carry, so each row wraps where the real one will and is its final
height from the first paint.

index.html holds each row as blank spans of fixed widths (three and eight),
measured from one day's lists. Both lists move with the data: on 2026-10-10
the US feed had one move in its 180-day window, and the three spans wrapped
to a second line at 768 where the one real item didn't — the card row above
the Safety table shrank 24px when it landed (CLS 0.009); the Flights list's
eight routes were shorter names than its spans (115px held, 91 drawn: 24px
at 768 and 390, 0.004, and more for a reader scrolled to it). The server has
what the rows will say — the cached US advisory list and the default
origin's cached fares and curves, the same payloads the browser fetches — so
it writes the items themselves, in renderDimPicks' markup, into the served
.skel row (server.py _home_sizers; the guide's shell keeps index.html's
bytes). A cold cache serves index.html's own spans, as before.

Mirrors flightLows / fareValue / fmtDevPct and renderAdvisories' `changed`
and chLine in public/app.js — change them together: scripts/test_map_picks.py
runs both sides on one fixture under jsc.
"""

import datetime
import html
import math

MON_FULL = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
MON_ABBR = [m[:3] for m in MON_FULL]
ADV_MOVE_DAYS = 180          # app.js ADV_MOVE_DAYS: the window a move shows for
DE_LVL_LABEL = {1: "No warning", 2: "Some regions", 4: "Travel warning"}
# app.js countryName's names for the fare destinations country-names.json has
# no guide for: EXTRA_PLACES (VI, SX), else Chrome's Intl.DisplayNames.
EXTRA_NAMES = {
    "BM": "Bermuda", "VI": "U.S. Virgin Islands", "SX": "Sint Maarten", "KY": "Cayman Islands",
    "AG": "Antigua and Barbuda", "KN": "St. Kitts and Nevis", "GD": "Grenada", "DM": "Dominica",
    "VC": "St. Vincent and the Grenadines", "MF": "St. Martin", "MV": "Maldives",
    "PF": "French Polynesia", "PW": "Palau",
}


def _e(s):
    return html.escape(str(s or ""), quote=True)


_DATA_NAMES = None


def _data_name(iso):
    """The name climate.json, then ppp.json, carries for `iso` — app.js
    countryName's order before it falls back to Intl.DisplayNames. The three
    Caribbean fare destinations with no guide (AG, KN, VC) came out as
    "Antigua & Barbuda" here and "Antigua and Barbuda" in the browser; a
    served span 2-6 characters short can wrap the row differently from the
    rendered one, the shift this module exists to remove."""
    global _DATA_NAMES
    if _DATA_NAMES is None:
        import json
        import os
        public = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
        _DATA_NAMES = {}
        for fname in ("ppp.json", "climate.json"):   # climate wins, so it is read last
            try:
                with open(os.path.join(public, fname), encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        if isinstance(v, dict) and v.get("name"):
                            _DATA_NAMES[k] = v["name"]
            except (OSError, ValueError):
                pass
    return _DATA_NAMES.get(iso)


def _name(names, iso):
    """`names`: ISO -> name (render_guide.name_for_iso), or None."""
    return (names(iso) if iso else None) or _data_name(iso) or EXTRA_NAMES.get(iso)


def _day_short(d, today):
    """app.js fmtDayShort: "21 May", the year only when it isn't this one."""
    p = str(d or "")[:10].split("-")
    if len(p) < 3 or not p[1].isdigit() or not 1 <= int(p[1]) <= 12:
        return str(d or "")
    return "%d %s%s" % (int(p[2]), MON_ABBR[int(p[1]) - 1],
                        "" if int(p[0]) == today.year else " " + p[0])


def _spans(items):
    """renderDimPicks' items: "<span>1. …</span>", the html already safe."""
    return "".join("<span>%d. %s</span>" % (i + 1, t) for i, t in enumerate(items))


# ---- Flights: "Below typical for <month>" --------------------------------------

def dev_pct(d):
    """app.js fmtDevPct: a signed whole percent with a real minus sign."""
    p = math.floor(d * 100 + 0.5)        # Math.round: halves go up
    return "0%" if p == 0 else ("−" if p < 0 else "+") + str(abs(p)) + "%"


def month_key(fv, today):
    """The departure month the tab bands for a reader who hasn't chosen one
    (app.js flightMonthNum + flightMonthKey): this month, or next month after
    the 15th, as its key in the payload's 12-month window."""
    m = today.month
    if today.day > 15:
        m = m % 12 + 1
    mm = "-%02d" % m
    for k in fv.get("months") or []:
        if str(k).endswith(mm):
            return k
    return "%d%s" % (today.year + (1 if m < today.month else 0), mm)


def flight_lows(fv, levels, names, key):
    """app.js flightLows for a reader with no region or higher-risk filter:
    [(deviation, iso)] of the routes banded Low for `key`, most below typical
    first. `levels` is advisoryByIso (ISO -> level of the US list)."""
    out = []
    for iso, c in (fv.get("countries") or {}).items():
        if not isinstance(c, dict) or c.get("pending") or c.get("median") is None:
            continue
        rec = (c.get("curve") or {}).get(key)
        price = rec[0] if rec else None
        if price is None or not price < c["lo"]:
            continue
        if not _name(names, iso) or (levels.get(iso) or 0) >= 3:
            continue
        out.append((price / c["median"] - 1, iso))
    out.sort(key=lambda x: x[0])         # stable, like the browser's
    return out


def flight_items(fv, levels, names, today):
    """The list's eight lines: "Canada −42%"."""
    return [_e(_name(names, iso)) + " " + dev_pct(dev)
            for dev, iso in flight_lows(fv, levels, names, month_key(fv, today))[:8]]


def flights_row(fv, levels, names, today=None):
    """The served row under the Flights map (index.html's, with the real
    items): the month in the title is the inline script's to correct for a
    link's ?vmn=; the items are the default month's."""
    today = today or datetime.date.today()
    key = month_key(fv, today)
    return ('<div class="mappicksrow skel" data-for="flightMap" aria-hidden="true">'
            '<strong>Below typical for %s</strong>%s</div>'
            % (MON_FULL[int(key[5:7]) - 1], _spans(flight_items(fv, levels, names, today))))


# ---- Safety: "Recently changed" -----------------------------------------------

def adv_items(payload, names, today):
    """renderAdvisories' `changed` list through chLine, for the whole world:
    the moves the list reports within the window, newest first, up to 8."""
    cutoff = (today - datetime.timedelta(days=ADV_MOVE_DAYS)).isoformat()
    src = payload.get("source") or "us"
    moved = []
    for it in payload.get("items") or []:
        on = str(it.get("changed") or it.get("updated") or "")
        if it.get("change") and on >= cutoff:
            moved.append((on, it))
    moved.sort(key=lambda x: x[0], reverse=True)
    out = []
    for on, it in moved[:8]:
        up = it["change"] == "up"
        try:
            lvl = int(it.get("level") or 0)
        except (TypeError, ValueError):
            lvl = 0
        words = DE_LVL_LABEL.get(lvl, "") if (it.get("via") or src) == "de" else "L%d" % lvl
        name = _name(names, it.get("iso")) or it.get("country") or ""
        out.append('%s <b class="%s" role="img" aria-label="%s">%s</b> %s · %s'
                   % (_e(name), "chup" if up else "chdown", "raised to" if up else "lowered to",
                      "▲" if up else "▼", _e(words), _e(_day_short(on, today))))
    return out


def advisory_row(payload, names, today=None):
    """The served row under the Safety map, or "" when nothing moved in the
    window — renderDimPicks removes the row then, so none is held."""
    today = today or datetime.date.today()
    items = adv_items(payload, names, today)
    if not items:
        return ""
    return ('<div class="mappicksrow skel" data-for="advMap" aria-hidden="true">'
            '<strong>Recently changed</strong>%s</div>' % _spans(items))
