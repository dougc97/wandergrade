"""Server-side rendering for per-country Travel Guide pages (SEO).

Every country gets a real URL (/guide/<slug>) whose HTML the server fills in
with country-specific <title>/meta/canonical and a crawlable content block
(best months, things to do with their insight sentences, what's in season,
visa). The SPA then hydrates on top — app.js removes the SSR block (#ssrGuide)
once it renders the interactive guide, so users never see it twice.

All content is read from the same JSON the frontend uses, plus one dated
snapshot (the guide-facts document, fxtracker/guide_facts.py) for the two
figures only WanderGrade answers — the price level against the US and the US
State Dept advisory — so a guide's title and snippet can say what the page is
actually for. The server recomputes that document once a day from its own
cached rates and advisories, and render() reads whichever copy is current via
guide_facts.get_doc(): it never calls a live API itself, so the HTML (which is
edge-cached) moves once a day, not with every rates blip.
"""

import datetime
import html
import json
import os
import re
import sys

from . import guide_facts

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
SITE = "https://wandergrade.com"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Spelled out for prose. Every search that reaches these pages is some form of
# "best time to visit <country>", and people type "December", not "Dec" — the
# abbreviations were fine as chip labels and invisible as body copy.
MON_FULL = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]


def _join_and(items):
    """a, b and c — reads as a sentence rather than a data dump."""
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    return "%s and %s" % (", ".join(items[:-1]), items[-1])

_data = None


def _load():
    global _data
    if _data is not None:
        return _data

    def j(name):
        with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
            return json.load(f)

    slugs = j("slugs.json")            # slug -> iso
    try:
        og = j("og-images.json")       # iso -> hero photo URL (optional)
    except OSError:
        og = {}
    # No guide-facts here: this cache lives as long as the process, and that
    # document is replaced daily (see _doc()).
    _data = {
        "slugs": slugs,
        "iso2slug": {iso: s for s, iso in slugs.items()},
        "names": j("country-names.json"),  # iso -> name
        "acts": j("activities.json"),
        "clim": j("climate.json"),
        "visa": j("visa.json"),
        "og": og,
    }
    return _data


# Names that read wrong bare inside a sentence or question ("Is Bahamas cheap to
# visit?", "Things to do in United States"). app.js NAME_THE is the same set:
# change them together (scripts/test_guide_meta.py holds the two equal). Labels
# ("Bahamas: local prices…", "Bahamas Travel Guide") and the h1 keep the bare name.
THE = {"BS", "PH", "NL", "AE", "GB", "US", "DO", "GM", "SB", "FO", "FK", "CF", "CG", "IM", "TF"}


def name_in_text(iso):
    """The country's name as it sits inside a sentence: "the Bahamas", "Japan"."""
    n = _load()["names"].get(iso, iso)
    return "the " + n if iso in THE else n


def activities(iso):
    """The country's activities.json entry (its hazards size the weather
    chart's stand-in, guide_sizers.chart)."""
    return _load()["acts"].get(iso) or {}


def iso_for_slug(slug):
    """ISO-2 for a URL slug, or None if it isn't a known country."""
    return _load()["slugs"].get(slug)


# ---- the guide's h1 ------------------------------------------------------------
# app.js flagEmoji/SPECIAL_FLAGS: England, Scotland and Wales are Unicode tag
# sequences, every other guide a regional-indicator pair.
_SUBDIV = {"GB-ENG": "gbeng", "GB-SCT": "gbsct", "GB-WLS": "gbwls"}


def flag_emoji(iso):
    if iso in _SUBDIV:
        return "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in _SUBDIV[iso]) + "\U000E007F"
    if re.fullmatch(r"[A-Z]{2}", iso or ""):
        return "".join(chr(0x1F1E6 + ord(c) - 65) for c in iso)
    return "\U0001F30D"


def h1_topics(iso, doc=None):
    """'cost, safety & when to go' — only the topics this guide has data for:
    cost where the snapshot has a price figure (not Taiwan, Cuba, the US
    itself…), safety where it has an advisory (not Western Sahara or the French
    Southern Territories). app.js guideH1Text() reads the same two fields of
    guide-facts.json. Topics, never figures, so a stale snapshot claims nothing."""
    f = _facts(iso, doc)
    t = (["cost"] if f.get("pct") is not None else []) + (["safety"] if f.get("adv") else []) + ["when to go"]
    return t[0] if len(t) == 1 else "%s & %s" % (", ".join(t[:-1]), t[-1])


def h1_html(iso, doc=None):
    """The guide's one h1, the same markup as app.js guideH1Html(): it is served
    as #guideH1 itself and hydration leaves it alone (renderGuide compares
    textContent, so html.escape's &#x27; vs esc()'s &#39; doesn't matter). No
    figures — the client never waits on live data to draw it, and it can never
    contradict any. "<Country> travel" keeps the page's strongest heading on
    the query the titles no longer lead with; the name is green (.gname), as
    the country was in the old "Travel Guide — Japan" heading."""
    name = _load()["names"].get(iso, iso)
    return '<span aria-hidden="true">%s</span> <span class="gname">%s</span> travel: %s' % (
        flag_emoji(iso), html.escape(name), html.escape(h1_topics(iso, doc)))


# ---- the price level / advisory snapshot (fxtracker/guide_facts.py) -------------
# Each government's own words for its levels: app.js ADV_LVL_WORDS / DE_LVL_LABEL.
ADV_LVL_WORDS = {
    "us": ["Normal precautions", "Increased caution", "Reconsider travel", "Do not travel"],
    "ca": ["Normal security precautions", "High degree of caution",
           "Avoid non-essential travel", "Avoid all travel"],
}
DE_LVL_LABEL = {1: "No warning", 2: "Some regions", 4: "Travel warning"}
# app.js ADV_SRC_SHORT. Puerto Rico, the US itself, Guam and the Falklands are
# rated by Canada in the US feed's gaps: they are never called a US advisory.
ADV_SRC_SHORT = {"us": "US State Dept", "ca": "Global Affairs Canada", "de": "German Foreign Office"}
# Still guarded although the server recomputes the snapshot daily: if that
# stops landing (a feed down for months, the refresher off), the figures age
# out rather than being presented as current.
STALE_DAYS = 90
_stale_warned = None      # the snapshot date last warned about


def lvl_words(src, lvl):
    if src == "de":
        return DE_LVL_LABEL.get(lvl, "")
    w = ADV_LVL_WORDS.get(src) or ADV_LVL_WORDS["us"]
    return w[lvl - 1] if lvl and 1 <= lvl <= 4 else ""


def _doc():
    """The guide-facts document in force: the freshest of the server's daily
    recompute and the committed public/guide-facts.json (guide_facts.get_doc).
    Fetched per call and never cached here — the refresher replaces it in
    place, and a copy pinned in this module would keep yesterday's titles
    until a restart. A render takes it once and passes it down (doc=), so one
    page never mixes two documents."""
    return guide_facts.get_doc() or {}


def snapshot_asof(doc=None):
    """The snapshot's date, or None."""
    try:
        return datetime.date.fromisoformat(str((_doc() if doc is None else doc).get("_asof") or ""))
    except ValueError:
        return None


def snapshot_fresh(today=None, doc=None):
    """False once the snapshot is more than STALE_DAYS old: from then on every
    number and advisory clause drops out of the description and SSR lines
    (the title only ever asks a question, so it keeps its variant)."""
    global _stale_warned
    doc = _doc() if doc is None else doc
    a = snapshot_asof(doc)
    ok = bool(a) and ((today or datetime.date.today()) - a).days <= STALE_DAYS
    if not ok and doc and _stale_warned != a:
        _stale_warned = a
        print("WARNING: the guide facts are from %s (over %d days old) — guide pages dropped "
              "their price and advisory figures. The server's daily recompute isn't landing "
              "(see its [guide-facts] log lines; DEPLOY.md has the manual fallback)"
              % (a, STALE_DAYS), file=sys.stderr)
    return ok


def snapshot_expired_on(today=None, doc=None):
    """The first day past STALE_DAYS (the day every guide dropped its figures),
    once that day has come; else None. The sitemap dates that change."""
    a = snapshot_asof(doc)
    if not a:
        return None
    d = a + datetime.timedelta(days=STALE_DAYS + 1)
    return d if d <= (today or datetime.date.today()) else None


def snapshot_changed(iso, doc=None):
    """The day this guide's snapshot entry last changed ("m", kept by
    guide_facts.date_entries), or "" — the guide's sitemap <lastmod>."""
    return str(_facts(iso, doc).get("m") or "")[:10]


def _facts(iso, doc=None):
    return (_doc() if doc is None else doc).get(iso) or {}


def _mon_year(d, full=False):
    return ("%s %d" % ((MON_FULL if full else MON)[d.month - 1], d.year)) if d else ""


def _band_q(f):
    """"Cheap" or "Expensive": which question the title asks."""
    return "Cheap" if f.get("band") in ("cheap", "very cheap") else "Expensive"


def _months_ranges(best):
    """December–February and July: runs of 3+ months as a range (wrapping
    December into January). Description only — it is a length rung."""
    s = sorted(set(m for m in best if 1 <= m <= 12))
    runs = []
    for m in s:
        if runs and m == runs[-1][-1] + 1:
            runs[-1].append(m)
        else:
            runs.append([m])
    if len(runs) > 1 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs[0] = runs.pop() + runs[0]
    out = []
    for r in runs:
        if len(r) >= 3:
            out.append("%s–%s" % (MON_FULL[r[0] - 1], MON_FULL[r[-1] - 1]))
        else:
            out.extend(MON_FULL[m - 1] for m in r)
    return _join_and(out)


TITLE_MAX = 60
DESC_MAX = 155


# The cost clause after the question, longest first. "Costs", not "Prices":
# "<country> travel cost" is the query, and it is a character shorter. "Travel"
# is added only where it fits without dropping a clause the shorter rung keeps
# — never at the price of "vs US", the comparison only this site makes.
_COST_TAILS = [" Travel Costs vs US, Safety & Best Time", " Costs vs US, Safety & Best Time",
               " Travel Costs vs US & Best Time", " Costs vs US & Best Time",
               " Travel Costs vs US", " Costs vs US", ""]


def _title(iso, f):
    """A question nobody else's page answers. Never a number or a level: a stale
    snapshot can only change which question is asked, and a question claims
    nothing. Level 3 and 4 countries are asked "safe?" (the query people type
    about them); Level 4 is never asked "cheap?". The first rung that fits
    TITLE_MAX wins; long names drop clauses, never letters."""
    n = _load()["names"].get(iso, iso)
    nt = name_in_text(iso)
    adv, has_p = f.get("adv"), f.get("pct") is not None
    if adv == 4 or (adv == 3 and not has_p):
        rest = " Travel Advisory, Costs & Weather" if has_p else " Travel Advisory & Weather"
        ladder = ["Is %s Safe to Visit?%s" % (nt, rest),
                  "Is %s Safe to Visit? Travel Advisory" % nt,
                  "Is %s Safe to Visit?" % nt]
    elif has_p:
        if adv == 3:
            head = ("Is %s Safe & Cheap to Visit?" if _band_q(f) == "Cheap" else "Is %s Safe to Visit?") % nt
            tails = [t for t in _COST_TAILS if "Safety" not in t]   # the question asks it
        else:
            head = "Is %s %s to Visit?" % (nt, _band_q(f))
            tails = _COST_TAILS
        ladder = [head + t for t in tails]
    else:
        ladder = ["%s Travel Guide: Best Time to Visit & Things to Do" % n,
                  "%s Travel Guide: Best Time to Visit" % n,
                  "%s Travel Guide" % n]
    for t in ladder:
        if len(t) <= TITLE_MAX:
            return t
    return ladder[-1]


def _adv_src(f):
    """'US State Dept' / 'US State Dept (United Kingdom advisory)'."""
    src = ADV_SRC_SHORT.get(f.get("src"), ADV_SRC_SHORT["us"])
    if f.get("advof"):
        src += " (%s advisory)" % _load()["names"].get(f["advof"], f["advof"])
    return src


def _desc(iso, f, asof):
    """The snippet: price level vs the US, the best months, the advisory —
    attributed and dated — then the curated summary if room is left. No letter
    grade: the overall grade moves with the month and the reader's priorities,
    so a meta letter would contradict the page most of the year."""
    d = _load()
    n = d["names"].get(iso, iso)            # the leading label: "Bahamas: local prices…"
    nt = name_in_text(iso)                  # inside a sentence: "Best weather in the Bahamas"
    c = d["clim"].get(iso) or {}
    curated = bool(c.get("curated"))
    best = [m for m in (c.get("best") or []) if 1 <= m <= 12]
    summary = " ".join(((d["acts"].get(iso) or {}).get("summary") or "").split())
    lvl = f.get("adv")
    src = f.get("src")
    has_p = f.get("pct") is not None

    def build(ranges=False, words=True, band=True):
        # No "(very cheap)" beside "Do not travel": a bargain verdict is the
        # wrong thing to say about a place the government says to stay out of.
        band = band and lvl != 4
        P = None
        if has_p:
            extra = ([f["band"]] if band and f.get("band") else []) + (
                ["%s-wide figure" % ("UK" if f.get("plof") == "GB" else d["names"].get(f["plof"], f["plof"]))]
                if f.get("plof") else [])
            P = "%s: local prices ≈ %d%% of the US%s." % (
                n, f["pct"], (" (%s)" % "; ".join(extra)) if extra else "")
        B = None
        if best:
            mt = _months_ranges(best) if ranges else _join_and(MON_FULL[m - 1] for m in best)
            if P:
                B = ("Best months to visit: %s." if curated else "Best weather: %s.") % mt
            else:
                B = ("Best months to visit %s: %s." if curated else "Best weather in %s: %s.") % (nt, mt)
        S = None
        if lvl:
            if src == "de":
                S = "%s: “%s”." % (_adv_src(f), lvl_words(src, lvl))
            else:
                S = "%s: Level %d%s." % (_adv_src(f), lvl, (", " + lvl_words(src, lvl)) if words else "")
        core = [S, P, B] if lvl == 4 else [P, B, S]
        core = [x for x in core if x]
        if (P or S) and asof:
            core.append("As of %s." % _mon_year(asof))
        return " ".join(core)

    # Cumulative rungs until it fits: month ranges, then the level words for
    # Levels 1-2, then the band, then Level 3's words. "Do not travel" stays.
    lv = lvl or 0
    s = ""
    for opts in (dict(), dict(ranges=True), dict(ranges=True, words=lv >= 3 or src == "de"),
                 dict(ranges=True, words=lv >= 3 or src == "de", band=False),
                 dict(ranges=True, words=lv >= 4 or src == "de", band=False)):
        s = build(**opts)
        if len(s) <= DESC_MAX:
            break
    if not s:
        return _clip(summary or generic_desc(iso), DESC_MAX)
    fill = _summary_fit(summary, DESC_MAX - len(s) - 1)
    return s + " " + fill if fill else s


def generic_desc(iso):
    """The number-free last resort — app.js guideMeta() shows the same sentence
    when guide-facts.json can't be loaded."""
    return ("What to do in %s, when to go, and what's in season — "
            "graded on prices, weather, safety and flights." % name_in_text(iso))


def _summary_fit(summary, room):
    """The curated summary in what room is left: whole; else up to its " — "
    (the clause before it stands alone, so it ends with a full stop); else up
    to a ", " with an ellipsis; else nothing. Never a cut mid-phrase ("…a long
    Indian Ocean coast and…"). Under 25 characters isn't worth the space."""
    if not summary or room < 25:
        return ""
    if len(summary) <= room:
        return summary
    for sep, end in ((" — ", "."), (", ", "…")):
        cuts = [i for i in range(len(summary)) if summary.startswith(sep, i)]
        for i in reversed(cuts):
            head = summary[:i].rstrip(".,;: ")
            if 25 <= len(head) + len(end) <= room:
                return head + end
    return ""


def meta(iso, f=None, asof=None, doc=None):
    """{"title", "desc"} for a guide — the ONE implementation: render() uses it,
    and guide_facts.compute stores its output in the document (t, d, and dn =
    the number-free description) for app.js to set on in-app navigation.

    f/asof default to the document in force (doc, else _doc()). Past
    STALE_DAYS the description falls back to its number-free variant; the
    title keeps its question."""
    if f is None:
        doc = _doc() if doc is None else doc
        f = _facts(iso, doc)
        fresh = snapshot_fresh(doc=doc)
        asof = snapshot_asof(doc) if fresh else None
        nums = f if fresh else {}
    else:
        nums = f
    return {"title": _title(iso, f), "desc": _desc(iso, nums, asof)}


def meta_numberfree(iso):
    """The description with every number and advisory clause dropped."""
    return _desc(iso, {}, None)


def _cost_line(iso, f, asof):
    """'Local prices ≈ 47% of the US (Sep 2026)' — the hydrated 💰 line's words."""
    if f.get("pct") is None:
        return ""
    tag = _mon_year(asof)
    if f.get("plof"):
        tag = "%s figure, %s" % ("UK-wide" if f["plof"] == "GB" else
                                 _load()["names"].get(f["plof"], f["plof"]) + "-wide", tag)
    return "Local prices ≈ %d%% of the US (%s)" % (f["pct"], tag)


def _safety_line(iso, f, asof):
    """'Level 3 · Reconsider travel — Safety · per US State Dept (Sep 2026)' —
    the hydrated 🛡️ badge, attributed to whoever set it."""
    lvl, src = f.get("adv"), f.get("src")
    if not lvl:
        return ""
    badge = lvl_words(src, lvl) if src == "de" else "Level %d · %s" % (lvl, lvl_words(src, lvl))
    who = ADV_SRC_SHORT.get(src, ADV_SRC_SHORT["us"])
    tag = _mon_year(asof)
    if f.get("advof"):
        tag = "%s advisory, %s" % (_load()["names"].get(f["advof"], f["advof"]), tag)
    return "%s — Safety · per %s (%s)" % (badge, who, tag)


# app.js VISA_META `long` text, so the crawlable line reads like the hydrated
# one ("Visa-free entry · 90 days"). Joining the raw status code printed "check
# no visa; expedition operators arrange permits" on pages Google indexes.
VISA_LONG = {
    "free": "Visa-free entry",
    "eta": "Electronic travel authorization (apply online)",
    "voa": "Visa on arrival",
    "evisa": "eVisa — apply online before you go",
    "required": "Visa required in advance (embassy/consulate)",
    "special": "Special restrictions apply",
    "check": "Requirements vary — verify before booking",
}


def _visa_line(v, verified):
    """The US-passport visa sentence, or "" where the guide shows no visa row."""
    if not v.get("status"):          # app.js visaInfo: no status, no row
        return ""
    txt = VISA_LONG.get(v["status"], VISA_LONG["check"])
    if v.get("note"):
        txt += " · " + v["note"]
    y, _, m = (verified or "").partition("-")
    when = ("%s %s" % (MON_FULL[int(m) - 1], y)) if m.isdigit() and 1 <= int(m) <= 12 else y
    tail = (" Checked %s; verify before booking — rules change." % when if when
            else " Verify before booking — rules change.")
    return "<p><strong>Visa (US passport):</strong> %s.%s</p>" % (html.escape(txt), html.escape(tail))


def _label(x):
    """An activity is either a plain string or {'t': label, 'd': insight}."""
    return x.get("t") if isinstance(x, dict) else x


def _insight(x):
    return x.get("d") if isinstance(x, dict) else ""


def _clip(text, n=157):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


# EKTA travel insurance, via Travelpayouts. A plain link on purpose: their only
# alternative is an embedded widget, and a third-party script is a failure mode
# this site does not need (a blocked one silently cost us every analytics number
# we had). marker=738472 is the affiliate id and is public by design — it ships
# in the URL either way.
#
# sub_id is the only part that varies. EKTA has no per-country pages — every
# destination is chosen inside one quote form on their homepage, and guessed
# paths like /colombia 404 — so all 176 links land in the same place. Tagging
# each with its slug costs nothing and is the only way to learn which guide
# pages actually convert. It does NOT make the destination country-specific,
# which is why the link text below says "travel insurance" and not "Colombia
# travel insurance": the reader picks their own destination once they arrive,
# and promising otherwise would be a lie for a few extra clicks.
_EKTA = ("https://tp.media/r?campaign_id=225&marker=738472&p=5869"
         "&sub_id=guide-%s&trs=541205&u=https%%3A%%2F%%2Fektatraveling.com")


def _insurance_link(slug):
    # Names the insurer. "Compare travel insurance" claimed a comparison that
    # does not exist — this is one company's quote form, not a marketplace.
    return ('<p class="afflink"><a class="staybtn" href="%s" '
            'rel="sponsored nofollow noopener" target="_blank">'
            "\U0001f6e1️ Travel insurance (EKTA)</a> "
            '<span class="affnote">Affiliate link — we may earn a commission, '
            "at no extra cost to you.</span></p>" % html.escape(_EKTA % slug, quote=True))


def render(iso):
    """Return the token values for a country page: title, description, og title,
    canonical URL, the h1 (served as #guideH1 itself) and the crawlable body."""
    d = _load()
    name = name_in_text(iso)          # every use below sits inside a sentence or heading
    slug = d["iso2slug"].get(iso, iso.lower())
    a = d["acts"].get(iso, {}) or {}
    c = d["clim"].get(iso, {}) or {}
    v = d["visa"].get(iso, {}) or {}

    best = c.get("best") or []
    # Curated mirrors the hydrated page's claim exactly: only 35 countries have
    # hand-curated best months; the rest have a weather score, and saying
    # "best months to visit" about those asserts a judgement nobody made.
    curated = bool(c.get("curated"))
    # Full month names everywhere the snippet appears — people type
    # "December", not "Dec" (same reasoning as the body copy switch).
    best_txt = _join_and(MON_FULL[m - 1] for m in best if 1 <= m <= 12)
    summary = (a.get("summary") or "").strip()
    acts = a.get("activities") or []
    seasonal = a.get("seasonal") or []

    # Title and description come from meta() — the same strings guide-facts.json
    # hands app.js for in-app navigation. Past the staleness guard the figures
    # (and their date) drop out of the description and fact lines alike.
    # One document for the whole page: the daily recompute can land mid-render.
    doc = _doc()
    mt = meta(iso, doc=doc)
    fresh = snapshot_fresh(doc=doc)
    f = _facts(iso, doc) if fresh else {}
    asof = snapshot_asof(doc) if fresh else None
    url = "%s/guide/%s" % (SITE, slug)

    # No <h1> here: #guideH1 is the page's h1 on the server and after hydration.
    p = []
    if summary:
        p.append("<p>%s</p>" % html.escape(summary))
    # The two fact lines the hydrated page shows as 💰 and 🛡️, from the dated
    # snapshot — and what the description claims, said on the page.
    cost = _cost_line(iso, f, asof)
    if cost:
        p.append("<p>💰 %s</p>" % html.escape(cost))
    safety = _safety_line(iso, f, asof)
    if safety:
        p.append("<p>🛡️ %s</p>" % html.escape(safety))
    if best_txt:
        # Every query landing here is "best time to visit <country>", and that
        # phrase used to appear only in the <title> — the body answered it under
        # the heading "What's in season", which is a different question, and in
        # abbreviated months nobody searches for. Heading and prose now say the
        # thing people actually typed.
        p.append("<h2>🌤️ Best time to visit %s</h2>" % html.escape(name))
        # Same sentence the hydrated page shows: the strong "best months to
        # visit" claim only where months are hand-curated; a weather statement
        # everywhere else. SSR asserting more than the live page is a lie
        # Google eventually reads side by side.
        p.append(("<p>The best months to visit %s are <strong>%s</strong>, "
                  "judged on weather and seasonality.</p>" if curated else
                  "<p>The best weather in %s is in <strong>%s</strong>.</p>")
                 % (html.escape(name), html.escape(best_txt)))
    # The hydrated outline (renderActivity): one h2, two h3s — h3, not h4, so
    # the outline skips no level. 1em: the size the h4s had.
    if acts or seasonal:
        p.append("<h2>Things to do in %s</h2>" % html.escape(name))
    if acts:
        p.append('<h3 style="font-size:1em">🎒 Top things to do</h3><ul>')
        for x in acts:
            t, ins = _label(x), _insight(x)
            li = "<li><strong>%s</strong>" % html.escape(t or "")
            if ins:
                li += " — %s" % html.escape(ins)
            p.append(li + "</li>")
        p.append("</ul>")
    if seasonal:
        p.append('<h3 style="font-size:1em">🗓️ What\'s in season</h3><ul>')
        for s in seasonal:
            months = [MON[m - 1] for m in (s.get("months") or []) if 1 <= m <= 12]
            li = "<li><strong>%s</strong>" % html.escape(s.get("what", ""))
            if months:
                li += " (%s)" % ", ".join(months)
            if s.get("d"):
                li += " — %s" % html.escape(s["d"])
            p.append(li + "</li>")
        p.append("</ul>")
    vline = _visa_line(v, d["visa"].get("_verified"))
    if vline:
        p.append(vline)
    p.append(_insurance_link(slug))

    return {
        "iso": iso,
        "title": mt["title"],
        "desc": mt["desc"],
        # og:title and twitter:title say what the <title> says.
        "og_title": mt["title"],
        "url": url,
        "h1_html": h1_html(iso, doc),
        "body": "\n".join(p),
        # No FAQPage JSON-LD (it was here until Oct 2026): Google requires an
        # FAQ's questions to be visible on the page, and these 926 were only in
        # the markup (the page shows the facts as the 💰/🛡️/best-time lines,
        # not as Q&A). FAQ rich results are shown only for government and
        # health sites since 2023, so the markup could only ever count against
        # the page as structured-data spam, never earn a result.
        # og:image is the site's own card, NOT the Wikimedia hero: Wikimedia
        # returns 403 to Meta's crawlers, so a hotlinked og:image meant every
        # Facebook/Messenger share of every guide rendered imageless. The
        # photo still shows on the page itself.
        "ogimage": SITE + "/og.png",
        # Layout hints for the page's first paint (server.py GUIDE_DATA),
        # sizing the boxes app.js fills. The advisory level by the snapshot:
        # the advisory block's height follows it (133px at 768 for Level 1,
        # 317 for Level 3), and a Level 4 ("do not travel") guide's grades
        # line is a lone "—", not the ~440px of grades the empty line is held
        # at, and it shows no stays or insurance; held for them anyway, the
        # country picker sat under the title and then jumped beside it (CLS
        # 0.32 at 768-785). Taken even from a stale snapshot: it only sizes
        # empty boxes.
        "adv": _facts(iso, doc).get("adv"),
        # The weather chart's month-hazard lines (monsoon, smoke season…):
        # 25px each at 768, the chart's whole spread between countries.
        "hz": len(a.get("hazards") or []),
        # The snapshot's price figure: without one the guide's local-prices
        # line has nothing to say either (Taiwan, Cuba), so its room isn't held.
        "pct": _facts(iso, doc).get("pct"),
    }


def all_slugs():
    """Every (slug, iso) for the sitemap and any build tooling."""
    return sorted(_load()["slugs"].items())


def name_for_iso(iso):
    """Display name for an ISO2, or None. Used by the homepage's crawlable
    index of every guide page — anchor text needs the country's real name, not
    the slug, both for readers and because the words in a link are a ranking
    signal for the page it points at."""
    return (_load()["names"] or {}).get(iso)
