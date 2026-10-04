"""Invisible stand-ins for the guide blocks app.js fills late, served inside
those blocks so each one is its own height from the first paint.

The visa line, the advisory (the level, the government's sentence, Canada's
safety notes and the health line), the AI buttons, the weather chart, the
stays and the insurance line are empty until app.js and their fetches land,
and were held at one height each (per advisory level for the advisory): the
median of 55 guides. Real advisories run from 69 to 700px, and every guide
away from the median moved the weather chart, the fare column and everything
under them when it filled — Thailand +36px at 768 and +68 at 1024, Italy -73
at 1024, Mexico +80-99 on a phone, Japan and Iceland -26; the AI buttons are
one row or two by the country's name (Italy 45px on a phone, held at 100),
the stays 154px at 1000-1149 for Thailand (held at 115), the chart 309 for
Thailand at 768 (held at 272). For a reader scrolling during a slow load
that was CLS 0.02-0.07 on most guides. The server has what those blocks will
say: the US advisory list and Canada's notes as its own caches hold them,
the health document, and the visa, climate, activity and stay files app.js
reads too. So it writes them, in app.js's own markup and classes, into a
hidden wrapper (.gsizer): the browser wraps that at the reader's real width,
which no per-level or per-band number could (measured equal to the drawn
blocks, to the pixel, on 20 guides at 390-1280). app.js replaces it, and
where it empties a block before refilling it holds the wrapper's height
until then (holdSizer).

The markup mirrors renderGuideVisa / renderGuideSafety / renderWatchouts /
renderGuideHealth / renderGuideAI / renderCountryClimate / renderGuideStay /
fillGuideInsurance in public/app.js — change them together; it only has to
wrap like them, so links have no targets and nothing in it can be focused,
clicked or read aloud (aria-hidden, visibility:hidden, data-nosnippet for
search). A block the server can't see the content of yet (cold caches) gets
no stand-in and keeps the stylesheet's median.
"""

import datetime
import html
import json
import os
import re

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
_files = {}


def _json(name):
    """A public/ data file app.js reads too, loaded once (they ship with
    the code)."""
    if name not in _files:
        try:
            with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
                _files[name] = json.load(f)
        except (OSError, ValueError):
            _files[name] = {}
    return _files[name]


ADV_LVL_WORDS = {
    "us": ["Normal precautions", "Increased caution", "Reconsider travel", "Do not travel"],
    "ca": ["Normal security precautions", "High degree of caution",
           "Avoid non-essential travel", "Avoid all travel"],
}
DE_LVL_LABEL = {1: "No warning", 2: "Some regions", 4: "Travel warning"}
MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ADV_MOVE_DAYS = 180          # app.js ADV_MOVE_DAYS: a move shows for this long
WN_CHIP = "West Nile"


def _e(s):
    return html.escape(str(s or ""), quote=True)


def _wrap(iso, inner):
    return ('<div class="gsizer" aria-hidden="true" data-nosnippet data-for="%s">%s</div>'
            % (_e(iso), inner))


def _day_short(d, today):
    """app.js fmtDayShort: "7 Jul", the year only when it isn't this one."""
    p = str(d or "")[:10].split("-")
    if len(p) < 3 or not p[1].isdigit() or not 1 <= int(p[1]) <= 12:
        return str(d or "")
    return "%d %s%s" % (int(p[2]), MON_ABBR[int(p[1]) - 1],
                        "" if int(p[0]) == today.year else " " + p[0])


def _chip(name, kind=""):
    """app.js chipHTML, less the visually-hidden words (out of the flow)."""
    if kind == "notice":
        return ('<span class="rkchip notice"><span>⚠️ </span><span class="rkname">%s</span></span>' % _e(name))
    if kind == "area":
        return '<span class="rkchip"><span class="rkname">%s</span><span class="rkmark"> ◐</span></span>' % _e(name)
    return '<span class="rkchip"><span class="rkname">%s</span></span>' % _e(name)


def _watchouts(wo, lvl):
    """renderWatchouts: at Level 1-2 the regional lines and a closed fold
    (its summary line only); at 3-4 the heading, the chips, the regional
    lines and the Safety-tab link."""
    if not wo or not (wo.get("watchouts") or wo.get("regional")):
        return ""
    chips = '<span class="wochips">' + "".join(
        '<span class="wochip">%s</span>' % _e(x.get("t")) for x in wo.get("watchouts") or []) + "</span>"
    reg = ""
    for r in wo.get("regional") or []:
        head = (r.get("t") or "").split(" - ")[-1]
        regions = r.get("regions") or []
        if regions:
            lst = ": " + ", ".join(regions[:10]) + (" +%d more" % (len(regions) - 10) if len(regions) > 10 else "")
        else:
            lst = ": " + r["lead"] if r.get("lead") else ""
        starred = any(str(x).endswith("*") for x in regions)
        reg += ('<span class="woreg">📍 <b>%s</b>%s%s</span>'
                % (_e(head), _e(lst), ' <span class="muted">(* parts excepted — see details)</span>' if starred else ""))
    src = ('<span class="muted">(per %s%s)</span>'
           % (_e(wo.get("source")), " — <a>details ↗</a>" if wo.get("link") else ""))
    if 0 < lvl <= 2:
        return (reg + '<details class="wofold"><summary>🧭 Safety notes (%d) — nothing unusual for a Level %d '
                'country %s</summary></details>' % (len(wo.get("watchouts") or []), lvl, src))
    return ('<span class="wohead">Safety notes %s</span>' % src + chips + reg
            + '<span class="advsrcnote"><button type="button" class="linkbtn wotab" tabindex="-1">'
              'full picture → Safety tab</button></span>')


def _wn_agency(w, c):
    m = re.match(r"^(ECDC|CDC):", (c or {}).get("t") or "")
    return m.group(1) if m else (w.get("source") or "ECDC")


def _health(hdoc, iso, parent):
    """renderGuideHealth: Canada's diseases as chips, then West Nile."""
    cs = (hdoc or {}).get("c") or {}
    hp = parent if (iso not in cs and parent) else None
    hz = cs.get(hp or iso)
    if not hz:
        return ""
    w = (hdoc or {}).get("w") or {}
    wc = ((w.get("c") or {}).get(hp or iso)) if w else None
    notice, areas = hz.get("n") or [], hz.get("a") or []
    names = list(notice) + [x for x in hz.get("h") or [] if x not in notice]
    chips = "".join(_chip(n, "notice" if n in notice else "area" if n in areas else "") for n in names)
    body = ('<span class="hzwrap">%s</span> <span class="muted">ⓘ</span>' % chips if hz.get("h")
            else '<span class="muted">only the usual ⓘ</span>')
    link = " <a>health advice ↗</a>" if hz.get("s") else ""
    wn = ""
    if wc:
        by = _wn_agency(w, wc)
        ym = re.search(r"\b(?:in|the) (\d{4})\b", wc.get("t") or "")
        year = ym.group(1) if ym else (w.get("season") or "")
        cite = ("<a>per %s%s ↗</a>" % (_e(by), ", " + _e(year) if year else "")) if by in ("ECDC", "CDC") else "per " + _e(by)
        wn = ' <span class="hzwrap">%s</span> %s <span class="muted">ⓘ</span>' % (_chip(WN_CHIP), cite)
    who = " (%s)" % _e(parent_name(hp)) if hp else ""
    return ('<div class="guidehealth"><b><span>💉 </span>Health · per the Government of Canada%s:</b> '
            % who + body + link + wn + "</div>")


_PARENT_NAMES = {"GB": "United Kingdom", "DK": "Denmark"}


def parent_name(iso):
    return _PARENT_NAMES.get(iso, iso)


# app.js GUIDE_PARENT and ADV_PARENT: England, Scotland and Wales read the
# UK's advisory and health advice; the Crown Dependencies the UK's advisory,
# the Faroes Denmark's.
GUIDE_PARENT = {"GB-ENG": "GB", "GB-SCT": "GB", "GB-WLS": "GB"}
ADV_PARENT = dict(GUIDE_PARENT, GG="GB", IM="GB", JE="GB", FO="DK")


def safety(iso, items, source_name, wo, hdoc, today=None):
    """The advisory block as renderGuideSafety draws it for a reader of the
    US list (the default), or "" without an entry to draw from. `items` maps
    ISO -> entry of the cached /api/advisories?source=us payload, `wo` is
    Canada's cached notes for the country, `hdoc` the health document."""
    parent = ADV_PARENT.get(iso) if iso not in items and ADV_PARENT.get(iso) in items else None
    item = items.get(iso) or (items.get(parent) if parent else None)
    if not item or not item.get("level"):
        return ""
    today = today or datetime.date.today()
    try:
        lvl = int(item.get("level") or 0)
    except (TypeError, ValueError):
        return ""
    src_of = item.get("via") or "us"
    words = (DE_LVL_LABEL.get(lvl, "") if src_of == "de"
             else (ADV_LVL_WORDS.get(src_of) or ADV_LVL_WORDS["us"])[lvl - 1] if 1 <= lvl <= 4 else "")
    badge = words if src_of == "de" else "Level %d · %s" % (lvl, words)
    cls = "nowarn" if src_of == "de" and lvl == 1 else "advlvl%d" % lvl
    src = (item.get("via_name") or source_name or "U.S. State Department") + (
        " (%s advisory)" % parent_name(parent) if parent else "")
    moved = ""
    on = item.get("changed") or item.get("updated") or ""
    cutoff = (today - datetime.timedelta(days=ADV_MOVE_DAYS)).isoformat()
    if item.get("change") in ("up", "down") and on and str(on)[:10] >= cutoff:
        up = item["change"] == "up"
        moved = ' <span class="advmoved %s">%s %s</span>' % (
            "chup" if up else "chdown", "▲ raised" if up else "▼ lowered", _e(_day_short(on, today)))
    why = ' <span class="advwhy">“%s”</span>' % _e(item["summary"]) if item.get("summary") else ""
    inner = ('<span class="advbadge %s">🛡️ %s</span>%s <span class="guidevisa-txt"><b>Safety · per %s:</b>%s '
             '<span class="advlinks"><a>full advisory ↗</a> · <button type="button" class="linkbtn" tabindex="-1">'
             'switch source (US · CA · DE) → Safety tab</button></span> <span>%s</span></span>'
             % (cls, _e(badge.rstrip(" ·")), moved, _e(src), why,
                _watchouts(wo, int((items.get(iso) or {}).get("level") or 0))))
    return _wrap(iso, inner + _health(hdoc, iso, GUIDE_PARENT.get(iso)))


def stay(iso, spots=None):
    """The stays block as renderGuideStay draws it (first spot chosen), or ""
    with no spots (app.js hides the block then). `spots` defaults to the
    country's entry in public/stay-coords.json, the file app.js reads."""
    if spots is None:
        spots = _json("stay-coords.json").get(iso)
    if isinstance(spots, dict):
        spots = [{"n": spots.get("near"), "ll": spots.get("ll")}]
    spots = [s for s in spots or [] if isinstance(s, dict) and s.get("ll") and s.get("n")]
    if not spots:
        return ""
    chips = ('<div class="staychips">' + "".join(
        '<button type="button" class="staychip%s" tabindex="-1">📍 %s</button>' % (" active" if i == 0 else "", _e(s["n"]))
        for i, s in enumerate(spots)) + "</div>") if len(spots) > 1 else ""
    # A <div>, not the h3 app.js writes: no heading in the served outline
    # for a block that isn't there yet (.staytitle sets the h3's font and
    # margins, so it lays out the same).
    return _wrap(iso, '<div class="staytitle">🏨 Where to stay <span class="staynear">near %s</span></div>' % _e(spots[0]["n"])
                 + chips + '<div class="staybtns"><a class="staybtn">🏨 Booking.com <span class="ext">↗</span></a>'
                 '<a class="staybtn">🎒 Hostelworld <span class="ext">↗</span></a></div>')


# app.js VISA_META: the chip's word and colour, and the line's words.
VISA_META = {
    "free": ("Visa-free", "vfree", "Visa-free entry"),
    "eta": ("eTA", "veasy", "Electronic travel authorization (apply online)"),
    "voa": ("On arrival", "veasy", "Visa on arrival"),
    "evisa": ("eVisa", "vmid", "eVisa — apply online before you go"),
    "required": ("Visa req'd", "vhard", "Visa required in advance (embassy/consulate)"),
    "special": ("Restricted", "vhard", "Special restrictions apply"),
    "check": ("Check", "vchk", "Requirements vary — verify before booking"),
}
MON_FULL = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]


def visa(iso):
    """The visa line as renderGuideVisa draws it for a US passport (the
    default origin), or "" where it shows none. A reader from elsewhere gets
    their own passport's line, a line or two either way."""
    if (GUIDE_PARENT.get(iso) or iso) == "US":
        return _wrap(iso, '<span class="visa vfree">🛂 Home</span> '
                     '<span class="guidevisa-txt">Your home country — no visa needed.</span>')
    vj = _json("visa.json")
    v = vj.get(iso) or vj.get(GUIDE_PARENT.get(iso, iso)) or {}
    if not isinstance(v, dict) or not v.get("status"):
        return ""
    label, cls, long_ = VISA_META.get(v["status"]) or VISA_META["check"]
    detail = long_ + (" · " + v["note"] if v.get("note") else "")
    link = " <a>official details ↗</a>" if str(v.get("link") or "").startswith("https://travel.state.gov/") else ""
    y, _, m = str(vj.get("_verified") or "").partition("-")
    checked = (MON_FULL[int(m) - 1] + " " + y if m.isdigit() and 1 <= int(m) <= 12 else y) if y else ""
    as_of = (" Checked %s; verify before booking — rules change." % _e(checked) if checked
             else " Verify before booking — rules change.")
    return _wrap(iso, '<span class="visa %s">🛂 %s</span> <span class="guidevisa-txt"><b>Visa · US passport:</b> '
                 '%s.%s %s</span>' % (cls, _e(label), _e(detail), link, as_of))


MONTHS = MON_FULL
# app.js REGIONS and ISO_REGION: the region named after the chart's heading.
REGIONS = {"AMER": "Americas", "EUR": "Europe", "MENA": "Middle East & N. Africa",
           "ASIA": "Asia", "AFRICA": "Africa (Sub-Saharan)", "OCEANIA": "Oceania"}
_ISO_REGION = {
    "AMER": "US CA MX GT BZ HN NI CR PA CU DO HT JM TT BS BB AW CW CO VE GY SR EC PE BR BO PY CL AR UY",
    "EUR": "GB GB-ENG GB-SCT GB-WLS IM JE GG CH LI NO SJ SE DK GL FO IS CZ PL HU RO BG RS BA MK AL MD UA BY "
           "RU TR AT BE CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES HR AD MC SM VA ME XK",
    "MENA": "IL PS SA AE QA KW BH OM JO LB SY IQ IR YE EG MA DZ TN LY EH",
    "ASIA": "CN JP KR IN PK BD LK NP AF MM TH VN KH LA MY SG ID PH BN HK MO TW MN KZ UZ TM KG TJ AZ AM GE BT",
    "AFRICA": "ZA NG KE GH ET TZ UG RW BI SD SS ER SO DJ AO MZ ZM BW NA SZ LS MW MG MU GM GN LR CD CV KM MR "
              "SC SN CI ML BF NE BJ TG GW CM TD CF CG GA GQ",
    "OCEANIA": "AU NZ FJ PG SB VU WS TO GU",
}
ISO_REGION = {iso: r for r, isos in _ISO_REGION.items() for iso in isos.split()}
# The guides app.js places by the map's continents instead (regionOf); none
# for Antarctica and the French Southern Lands.
ISO_REGION.update(FK="AMER", PR="AMER", SV="AMER", KP="ASIA", TL="ASIA", NC="OCEANIA", SL="AFRICA", ZW="AFRICA")


def _join_and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def month_span(ms):
    """app.js monthSpan: "Jun–Oct", "Nov–Apr" across New Year, else a list."""
    s = sorted(m for m in ms or [] if 1 <= m <= 12)
    if not s:
        return ""
    if len(s) == 1:
        return MON_ABBR[s[0] - 1]
    contig = lambda a: all(not i or m == a[i - 1] + 1 for i, m in enumerate(a))
    if contig(s):
        return MON_ABBR[s[0] - 1] + "–" + MON_ABBR[s[-1] - 1]
    missing = [m for m in range(1, 13) if m not in set(s)]
    if missing and contig(missing):
        return MON_ABBR[missing[-1] % 12] + "–" + MON_ABBR[(missing[0] + 10) % 12]
    return ", ".join(MON_ABBR[m - 1] for m in s)


def chart(iso, name_in_text, hazards):
    """The weather chart's frame as renderCountryClimate draws it — heading
    and °C/°F toggle, the best-months sentence, a line per month hazard and
    the 150px bars — or "" without climate data. `name_in_text` is "the
    Bahamas"-style, `hazards` the country's activities.json hazards."""
    c = _json("climate.json").get(iso)
    if not isinstance(c, dict) or not c.get("scores"):
        return ""
    best = _join_and(MONTHS[m - 1] for m in c.get("best") or [] if 1 <= m <= 12)
    name = _e(name_in_text)
    if not best:
        line = "📅 Curated best months:" if c.get("curated") else "📅 Best weather:"
    elif c.get("curated"):
        line = ("📅 The best months to visit %s are <strong>%s</strong> — judged on weather and seasonality."
                % (name, _e(best)))
    else:
        line = "📅 The best weather in %s is in <strong>%s</strong>." % (name, _e(best))
    temps = any(t is not None for t in c.get("temps") or [])
    rg = REGIONS.get(ISO_REGION.get(iso))
    head = ('<div class="besthead"><div class="gh2"><span>🌤️</span> Best time to visit %s%s%s</div>%s</div>'
            % (name, ' <span class="muted">· %s</span>' % _e(rg) if rg else "",
               '<span class="legendinfo">ⓘ</span>' if temps else "",
               '<div class="tempunit"><button type="button" tabindex="-1">°C</button>'
               '<button type="button" tabindex="-1">°F</button></div>' if temps else ""))
    lines = "".join('<div class="hazardline">⚠️ <b>%s:</b> %s</div>' % (_e(month_span(h.get("months"))), _e(h.get("note")))
                    for h in hazards or [] if isinstance(h, dict))
    return _wrap(iso, head + '<div class="monthslabel">%s</div>' % line + lines + '<div class="bars"></div>')


def insurance(iso):
    """The insurance line as fillGuideInsurance draws it. Its note's bottom
    margin runs out of the block (into the stays column beside the advisory
    from 900px), which a held height can't stand in for: 12px short at 1280."""
    return _wrap(iso, '<div class="staybtns"><a class="staybtn">🛡️ Travel insurance (EKTA) <span class="ext">↗</span></a></div>'
                 '<p class="affnote">Some links in this section are affiliate links — we may earn a commission, '
                 'at no extra cost to you.</p>')


def ai(iso, name):
    """The trip and AI buttons as renderGuideAI draws them for a country not
    on the reader's trip: one row or two by the length of the name (45px or
    100 on a phone — Italy one, Thailand two)."""
    return _wrap(iso, '<button type="button" class="tripbtn" tabindex="-1">🧳 Add %s to my trip</button>'
                 '<button type="button" class="aibtn" tabindex="-1">✨ Plan %s with AI →</button>' % (_e(name), _e(name)))
