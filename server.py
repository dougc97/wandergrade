#!/usr/bin/env python3
"""Web dashboard + JSON API for the USD strength tracker. Pure stdlib.

Run:  python3 server.py          (then open http://localhost:8000)
      python3 server.py 9000     (custom port)

Endpoints:
  GET  /                serve the dashboard
  GET  /api/rates       computed favorability table (cached briefly)
  GET  /api/config      current settings
  POST /api/config      update settings (JSON body)
  POST /api/check       run the alert check now, return what it found
"""

import _thread
import base64
import collections
import contextlib
import difflib
import gzip
import hashlib
import hmac
import html
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fxtracker import (
    accounts, advhistory, advisories, build_dataset, build_pl_history, build_ppp, flights,
    flightshadow, flightvalue, guide_facts, guide_lines, guide_sizers, health, home_picks, llms_txt, mailer, map_picks, picks, popularity, rates,
    render_cheapest, render_guide, render_lists, render_methodology, render_privacy, store, strip_comments, triplegs, watchouts
)

# Optional HTTP Basic Auth — enforced only when BOTH env vars are set, so local
# runs stay open while a public/tunneled instance can require a login.
AUTH_USER = os.environ.get("FX_DASH_USER")
AUTH_PASS = os.environ.get("FX_DASH_PASSWORD")
AUTH_ON = bool(AUTH_USER and AUTH_PASS)

# Public mode (FX_PUBLIC=1): no login, anyone can browse — but mutating
# endpoints are disabled and email addresses are stripped from API responses,
# so strangers can't edit settings or trigger emails to the owner.
PUBLIC_MODE = os.environ.get("FX_PUBLIC") == "1"
if PUBLIC_MODE:
    AUTH_ON = False

PUBLIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
_BOOT = time.monotonic()   # /healthz's X-Uptime counts from here: a restart shows as a reset
CACHE_TTL = 600  # seconds; FX reference rates update at most daily.
# Rates cache is keyed per (settings, base), NOT a single slot: the site
# localizes base to each visitor's home currency, so one-slot caching made
# ordinary mixed-country traffic evict the entry on every alternation and
# everyone paid the full three-fetch recompute. Expired keys prune on write.
_rates_cache = {}  # (baseline_days, threshold_pct, watch, base) -> (ts, payload)
_index_cache = {}  # (range, base) -> (timestamp, payload)
# Expired rates/index entries are kept this long as the fallback for a failed
# refresh (see _cached), then pruned on write. Keys are bounded: bases are
# validated against the provider's list and the index has 9 fixed ranges.
STALE_MAX = 24 * 3600
_adv_cache = {}     # source -> (timestamp, payload)
ADV_TTL = 6 * 3600  # advisories change rarely; refresh a few times a day
_flights_cache = {}  # origin -> (timestamp, payload)
FLIGHTS_TTL = 3600   # cached fares are fine for an hour
_pop_cache = {"at": 0, "data": None}
POP_TTL = 7 * 24 * 3600   # tourist arrivals are annual; refresh weekly
_ppp_cache = {"at": 0, "data": None}
PPP_TTL = 30 * 24 * 3600  # PPP is annual data; a monthly re-check is plenty
PPP_RETRY = 24 * 3600     # after a refused or failed refresh, try again in a day

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".geojson": "application/geo+json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".woff2": "font/woff2",
}

# Sent on every response. The CSP allows our own assets plus the few external
# origins the app genuinely uses: Wikipedia/Wikimedia
# image+API fetches, and inline <style>/<script> the page relies on. form-action
# is intentionally left unset so the newsletter form can POST to Buttondown.
SECURITY_HEADERS = {
    # Only the first plain-http visit could be downgraded (http 301s to https
    # at the edge); this closes that too. No includeSubDomains until every
    # subdomain is confirmed https-only.
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        # static.cloudflareinsights.com is the Web Analytics beacon that
        # _analytics_tag() injects. Without it here the browser refuses the
        # script (script-src-elem) and the site records zero traffic while
        # looking perfectly healthy — the tag is in the HTML, the token is
        # valid, and nothing reports. That is exactly what happened: Search
        # Console showed real clicks while the Cloudflare dashboard sat at 0.
        "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https:; "
        # Nothing is framed (no embedded Stay22 map: the stay links open
        # the partner's own page), and no plugin content.
        "frame-src 'none'; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'"
    ),
}


# index.html carries {{TOKENS}} the server fills per request: the homepage gets
# these defaults; a /guide/<slug> page gets country-specific values (+ SSR body).
_WEBSITE_JSONLD = (
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"WebSite","name":"WanderGrade",'
    '"url":"https://wandergrade.com/",'
    '"description":"Every country graded A+ to F on prices, weather, safety and flights — '
    'decide where and when to travel next."}'
    "</script>"
)
# impact.com's site-ownership tag for the WanderGrade partner account (the
# Airbnb Demand Program application, 2026-10-21), in impact.com's own words
# and quotes: its check reads the homepage's <head>. It rides on JSONLD, the
# one head token only the homepage fills, so the 190 guides stay
# byte-identical (the Search Console freeze until Nov 9).
_IMPACT_VERIFY = "<meta name='impact-site-verification' value='cf7a1cf5-6953-488a-a53d-725a779d6766'>"
def _analytics_tag():
    """Cloudflare Web Analytics beacon, injected on every page only when
    CF_ANALYTICS_TOKEN is set (Render → Environment). The token is public (it
    ships in page source), so it lives in the env, not the repo. Empty string
    when unset, so dev/self-hosting stay analytics-free."""
    token = os.environ.get("CF_ANALYTICS_TOKEN", "").strip()
    if not token:
        return ""
    beacon = json.dumps({"token": token})   # safe-encodes the token into the attr
    return ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            "data-cf-beacon='%s'></script>" % beacon)


# Kept out of the import block above: the subscribe picker's currency list.
from fxtracker import digest_variants  # noqa: E402


def _un_members():
    """app.js UN_MEMBERS as one run of two-letter codes ("AFALDZ…") for
    VISITED_HOLD's "c": only a UN member's mark draws the Wander List's
    continent row (app.js continentProgress). Read out of app.js rather than
    copied, so the two can't drift; "" if the literal isn't found, and then
    no "c" is ever set and the phone floor it gates never applies."""
    try:
        with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
            m = re.search(r'^const UN_MEMBERS = new Set\(\((.*?)\)\.split\(" "\)\);', f.read(), re.M | re.S)
    except OSError:
        return ""
    return "".join(re.findall(r"\b[A-Z]{2}\b", m.group(1))) if m else ""


# TITLE / DESC / OGTITLE are mirrored in app.js _DEFAULT_META (restored when the
# reader leaves a guide in-app): change them together.
_HTML_DEFAULTS = {
    "TITLE": "WanderGrade — Where Should I Travel to Next?",
    "DESC": "Decide where — and when — to go. Every country graded A+ to F on "
            "prices, weather, safety, and flights. Free, no sign-up.",
    "OGTITLE": "Where Should I Travel to Next?",
    "URL": "https://wandergrade.com/",
    "OGIMAGE": "https://wandergrade.com/og.png",
    "GC_JS": "",
    "SSR_BODY": "",
    # The homepage's own h1. On a /guide/<country> page this becomes a plain
    # paragraph instead: that page's h1 belongs to the country, and this shell
    # headline is byte-identical across all 176 of them, so leaving it as an h1
    # meant every guide's first and strongest heading said nothing about the
    # country it was for. Same pixels either way — .sitetitle carries the style.
    "SITE_HEADING": '<h1 class="sitetitle">Where Should I Travel to Next?</h1>',
    # The guide tab's own h1 (#guideH1). Off a guide it waits hidden for app.js
    # to fill it; on /guide/<slug> it is the country's h1 from the first byte
    # (render_guide.h1_html), and hydration writes the same markup or nothing.
    "GUIDE_H1_HIDDEN": " hidden",
    "GUIDE_H1": "Travel Guide",
    "GUIDE_LINKS": "",
    "GUIDE_COUNT": "",
    # Which tab the served HTML shows before (or without) JS: Top Picks here,
    # the guide on /guide/<slug>. Left to JS alone, a no-JS reader or a
    # readability extractor got the Top Picks shell with the guide — its h1
    # and server-rendered body — inside a [hidden] section. JS visitors are
    # unaffected: the head script sets the same data-tab, activateTab the rest.
    "HTML_TAB": "",
    "VALUE_HIDDEN": "",
    "GUIDE_HIDDEN": " hidden",
    "GUIDE_DATA": "",
    "GUIDE_VISA": "",
    "GUIDE_CHART": "Loading…",
    # The guide's month-by-month table (render_guide.month_table, #when-to-go),
    # its own block right after #bestDetail. In index.html with no bytes of its
    # own, so the homepage and every guide not rolled out to stay byte-identical.
    "GUIDE_MONTHS": "",
    "CHART_LOADING": " loading",
    "GUIDE_SAFETY": "",
    "GUIDE_AI": "",
    "GUIDE_STAY": "",
    "GUIDE_INSURANCE": "",
    "VALUE_ACTIVE": ' class="active"',
    "GUIDE_ACTIVE": "",
    "JSONLD": _WEBSITE_JSONLD,
    "ANALYTICS": _analytics_tag(),
    # Lets the page hide every trace of sign-in until accounts are provisioned.
    # __WGDIGEST__: the newsletter currencies a reader can pick (the digest's
    # "send"-stage editions, fxtracker/digest_variants.ROLLOUT); just ["USD"]
    # shows no picker at all.
    "ACCOUNTS": "<script>window.__WGACCT__=%s;window.__WGDIGEST__=%s</script>" % (
        "true" if accounts.enabled() else "false",
        json.dumps(list(digest_variants.picker_codes()))),
    # The header's account button, shown in the served HTML when accounts are
    # on. Un-hidden by app.js instead, it arrived after first paint and grew
    # the header: +62px at 768-895 (the title and tagline re-wrapped around
    # it), the whole tab below moving with it (CLS 0.26 at 768).
    "ACCT_HIDDEN": "" if accounts.enabled() else " hidden",
    # The Data tab's owner-only action bar ("Check & email now"):
    # app.js un-hides it once /api/config says the server isn't read-only,
    # which on a private server grew the bar 46px after first paint (CLS
    # 0.034-0.041 at 390). Served visible exactly where init() would show it.
    "ACTIONS_HIDDEN": " hidden" if PUBLIC_MODE else "",
    # Wander List first paint. VISITED_STATS is the empty-state line
    # renderVisitedStats writes for a first visit (app.js MILESTONE_TIERS[0]:
    # change them together) — the tab grew 29px into it when app.js arrived
    # (CLS 0.095 at 390, 0.044 at 768). VISITED_PICK is the first option
    # buildVisited writes, so the select is sized like the combo that replaces
    # it instead of a 42px stub. VISITED_HOLD sets html[data-vis] for a
    # visitor whose lists are already in localStorage — "v" been, "w" want
    # to go — the floor styles.css holds under the stats and chips they will
    # fill; the served empty-state line gives way to it. A shared map (?v=)
    # stands in for the been list as app.js init() reads it (URLSearchParams,
    # GC_RE): the sharer's countries are the ones drawn. "c" when a been mark
    # is a UN member, the only kind that draws the continent row (on phones
    # the stats floor counts it; England or Puerto Rico alone don't draw
    # it). "s" when the "Save this map" button (.vsave) will show: accounts
    # on and not signed in (the head script's data-acct), app.js
    # renderVisitedStats' rule — on phones styles.css holds its line above
    # the map (over the map from 561px up it takes no room).
    # scripts/test_wander_save.py runs these rules against app.js's. It
    # belongs in the head script with the other pre-paint flags and will
    # move there: index.html itself can't change a byte while /guide/* is
    # under its Search Console measurement (until November 2026), so the
    # three are filled here and empty on a guide (which never paints this
    # tab first anyway; see _render_index).
    "VISITED_STATS": '<div class="vstats-line vstand"><span class="hint">Nothing marked yet</span>'
                     '<span class="awardtag locked" data-tip="Visit 5 countries to earn 🧭 Explorer" '
                     'title="">🔒 5 to 🧭 Explorer</span></div>',
    "VISITED_PICK": '<option value="">+ add a country…</option>',
    "VISITED_HOLD": '<script>(function(){try{var d=document.documentElement,'
                    'q=new URLSearchParams(location.search).get("v"),'
                    'b=q?q.split(",").map(function(x){return x.trim().toUpperCase()})'
                    '.filter(function(x){return/^[A-Z]{2}(-[A-Z]{3})?$/.test(x)})'
                    ':JSON.parse(localStorage.getItem("fx_visited")||"[]"),'
                    'u="%s".match(/../g)||[],'
                    'v=b.length>0,c=b.some(function(x){return u.indexOf(x)>=0}),'
                    'w=JSON.parse(localStorage.getItem("fx_wishlist")||"[]").length>0;'
                    'if(v||w)d.setAttribute("data-vis",(v?"v":"")+(c?"c":"")+(w?"w":"")'
                    '+(%s&&d.getAttribute("data-acct")!=="in"?"s":""));}catch(e){}})();</script>'
                    % (_un_members(), "true" if accounts.enabled() else "false"),
    # The pick-list rows under the Safety and Flights maps as index.html holds
    # them, blank spans of widths measured from one day's lists (a guide's
    # shell keeps these bytes). The homepage serves the lists' real words in
    # their place (_home_sizers, fxtracker/map_picks.py): three spans wrapped
    # to a line the one real move didn't take, eight to one its shorter
    # names didn't, and the table under each map rode up 24px at 768 when
    # the list landed. FLIGHTS_OFF marks the Flights view of a server with no
    # fares to serve (no Travelpayouts token), so nothing is held for them.
    "ADV_PICKS": '<div class="mappicksrow skel" data-for="advMap" aria-hidden="true">'
                 '<strong>Recently changed</strong><span style="width:9.3em"></span>'
                 '<span style="width:14.2em"></span><span style="width:9.6em"></span></div>',
    "FLIGHT_PICKS": '<div class="mappicksrow skel" data-for="flightMap" aria-hidden="true">'
                    '<strong>Below typical for October</strong><span style="width:7.8em"></span>'
                    '<span style="width:9.6em"></span><span style="width:7.9em"></span>'
                    '<span style="width:7.9em"></span><span style="width:9.1em"></span>'
                    '<span style="width:9.2em"></span><span style="width:9.5em"></span>'
                    '<span style="width:8.2em"></span></div>',
    "FLIGHTS_OFF": "",
    # Top Picks' table and the line above it for the view a first visit opens
    # on (fxtracker/home_picks.py, _home_picks), served on the homepage with
    # index.html's skeleton kept beside them, hidden; a guide (which never
    # paints Top Picks first) keeps index.html's bytes.
    "TOP_SSR": "", "TOP_SKEL_HIDDEN": "", "TOP_PICKS": "", "TOP_HOLD": "",
    "NOTE_SKEL_HIDDEN": "", "PICKS_NOTE": "",
    # A guide's grades line and fares-by-month strip for a first visit
    # (fxtracker/guide_lines.py, _guide_lines); empty, the strip hidden, as
    # index.html had them, wherever they aren't served.
    "GUIDE_GRADES": "", "FARES_HIDDEN": " hidden", "GUIDE_FARES": "", "GUIDE_HOLD": "",
    # A guide's 💰 local-prices line under its grades (guide_lines.cost,
    # _guide_cost); hidden and empty, as index.html had it, elsewhere.
    "COST_ATTRS": " hidden", "GUIDE_COST": "", "COST_HOLD": "",
}
_html_tpl = None


def _asset_version(name):
    """File mtime as a cache-busting token; changes exactly when a deploy does."""
    try:
        return str(int(os.path.getmtime(os.path.join(PUBLIC, name))))
    except OSError:
        return "0"


# /app.js goes out minified (301 KB -> 143 KB gzipped): public/app.min.js, which
# scripts/build_min_js.py writes with a pinned esbuild beside
# public/app.min.js.sha256, the sha256 of the app.js it was built from. It is
# served only while that hash is app.js's own. An app.js edited without a
# rebuild goes out as written, with one [min-js] log line, so a forgotten
# rebuild ships the bigger file, never stale code. FX_MIN_JS=0 (Render ->
# Environment, which restarts the server) serves app.js as written. The
# choice is kept while the three files' mtimes and sizes hold: app.js is
# hashed once per change, not per request.
MIN_JS = os.environ.get("FX_MIN_JS", "1").strip() != "0"
APP_JS = os.path.join(PUBLIC, "app.js")
APP_MIN_JS = os.path.join(PUBLIC, "app.min.js")
APP_MIN_SHA = APP_MIN_JS + ".sha256"
_app_js_memo = None        # (the files' stat keys and the switch, path served)
_app_js_lock = threading.Lock()


def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _choose_app_js():
    """(path to serve for /app.js, why app.js is served as written or None)."""
    if not MIN_JS:
        return APP_JS, "FX_MIN_JS=0"
    if not os.path.isfile(APP_MIN_JS):
        return APP_JS, "no app.min.js"
    try:
        with open(APP_MIN_SHA, encoding="utf-8") as f:
            stored = (f.read().split() or [""])[0].lower()
        with open(APP_JS, "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
    except (OSError, ValueError) as e:
        return APP_JS, "no app.min.js.sha256 (%s)" % e.__class__.__name__
    if not re.fullmatch(r"[0-9a-f]{64}", stored):
        return APP_JS, "app.min.js.sha256 holds no sha256"
    if stored != actual:
        return APP_JS, ("app.min.js was built from app.js %s, app.js is now %s: rebuild with "
                        "/usr/bin/python3 scripts/build_min_js.py" % (stored[:12], actual[:12]))
    return APP_MIN_JS, None


def _app_js_file():
    """The file /app.js serves: app.min.js while it is current, else app.js.
    Each new choice writes one line to the log."""
    global _app_js_memo
    key = (MIN_JS, _stat_key(APP_JS), _stat_key(APP_MIN_JS), _stat_key(APP_MIN_SHA))
    memo = _app_js_memo
    if memo is not None and memo[0] == key:
        return memo[1]
    with _app_js_lock:
        if _app_js_memo is not None and _app_js_memo[0] == key:
            return _app_js_memo[1]
        path, why = _choose_app_js()
        if why:
            print("[min-js] serving app.js as written: %s" % why, flush=True)
        else:
            print("[min-js] serving app.min.js for /app.js", flush=True)
        _app_js_memo = (key, path)
    return path


def _app_js_version():
    """/app.js's ?v= stamp: app.js's mtime, as styles.css's is its own (new on
    every deploy, which ppp.json and pl_history.json borrow through app.js's
    stamped()), then, while the minified copy is what goes out, 8 digits of
    that file's sha256. So the stamp changes whenever the bytes served do,
    also when only the copy (a rebuild) or FX_MIN_JS does, and a browser's
    year-long copy, or the service worker's, never outlives them."""
    try:
        v = str(int(os.path.getmtime(APP_JS)))
    except OSError:
        v = "0"
    path = _app_js_file()
    if path != APP_JS:
        try:
            with open(path, "rb") as f:
                v += "%08d" % (int(hashlib.sha256(f.read()).hexdigest(), 16) % 10 ** 8)
        except OSError:
            pass
    return v


# The raw template's <!-- --> notes (about 30% of its bytes, 9 KB of a
# guide's gzipped page) and every stylesheet's /* */ ones (styles.css 72 KB
# -> 28 KB gzipped) are taken out before anything is served
# (fxtracker/strip_comments.py): the template once, before any token is
# filled, so a rendered page's own markers (<!--tN-->, <!--email_off-->)
# are never touched; the stylesheets in _static_bytes. FX_STRIP_COMMENTS=0
# (Render -> Environment, which restarts the server) serves both as written.
STRIP_COMMENTS = os.environ.get("FX_STRIP_COMMENTS", "1").strip() != "0"


def _index_template():
    global _html_tpl
    if _html_tpl is None:
        with open(os.path.join(PUBLIC, "index.html"), encoding="utf-8") as f:
            tpl = f.read()
        if STRIP_COMMENTS:
            tpl = strip_comments.html(tpl)
        # Stamp asset URLs with the file's mtime so browsers can cache them
        # long-term (see _send_file) yet always fetch fresh after a deploy.
        tpl = re.sub(r"/app\.js(\?v=\d+)?", "/app.js?v=" + _app_js_version(), tpl)
        tpl = re.sub(r"/styles\.css(\?v=\d+)?", "/styles.css?v=" + _asset_version("styles.css"), tpl)
        _html_tpl = tpl
    return _html_tpl


# A guide page carries the whole single-page app, and every static h2/h3 in it
# belongs to another tab (Top Picks, Trip, Wander List, Data: "Where the dollar
# is strong…", "Travel advisories", "Fares by month"…) — 16 headings telling a
# crawler the Colombia page is about something else. On /guide/* only, they are
# served as <div data-h="2|3"> (ids kept, so app.js finds them as before) and
# app.js promoteShellHeadings() turns them back into h2/h3 the moment a reader
# opens one of those tabs — before it is revealed, so nothing moves. The tabs
# are also data-nosnippet: Google builds no snippet from the SMTP tip.
# Only inside those four tab sections: a heading added to the header, the guide
# tab or the footer stays a real heading (promoteShellHeadings never runs while
# the guide is showing, so a demoted one there would stay a div).
_SHELL_H = re.compile(r"<(/?)h([23])(?=[\s>])")
_SHELL_TABS = ("tab-value", "tab-trip", "tab-visited", "tab-data")
_SECTION_TAG = re.compile(r"<(/?)section(?=[\s>])")
_guide_tpl = None
# Their words too: some 620 of a guide's 1,550 served words, the same on every
# guide. On /guide/* each run of text in those four tabs with a letter or
# digit in it is served as a <!--tN--> comment, and the strings go in one JSON
# block (#shellText) that app.js restoreShellText() puts back in the same
# moment as the headings, before any of those tabs is revealed. Every element,
# id and attribute stays, so boot code finds all it finds today. Kept:
# script/style contents, and the .picklabel words enhanceSelect names its
# combos from at boot. Two tokens there hold words and are constants on a
# guide (_render_index never changes them for one), so they are filled first.
# FX_GUIDE_TEXTOUT=0 (Render → Environment, which restarts the server) serves
# every guide as before, byte for byte.
GUIDE_TEXTOUT = os.environ.get("FX_GUIDE_TEXTOUT", "1").strip() != "0"
_TEXTOUT_FILLED = ("ADV_PICKS", "FLIGHT_PICKS")
_TX_PART = re.compile(r"<!--.*?-->|<(script|style|template|svg|textarea)\b.*?</\1\s*>|<[^>]+>|\{\{[A-Z_]+\}\}",
                      re.S | re.I)
_TX_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)")
_TX_PICKLABEL = re.compile(r'\sclass="[^"]*\bpicklabel\b')
_TX_WORDY = re.compile(r"[^\W_]")   # a letter or a digit


def _text_out(sec, strings):
    """sec with every wordy text run outside a .picklabel swapped for
    <!--tN-->, N its index in strings (which gets the run as the DOM holds
    it: entities decoded, whitespace kept)."""
    out, pos, keep, depth = [], 0, None, 0   # keep: the open .picklabel's tag name

    def text(t):
        if keep or not _TX_WORDY.search(t):
            out.append(t)
        else:
            strings.append(html.unescape(t))
            out.append("<!--t%d-->" % (len(strings) - 1))

    for m in _TX_PART.finditer(sec):
        text(sec[pos:m.start()])
        part, pos = m.group(0), m.end()
        out.append(part)
        t = _TX_TAG.match(part) if not m.group(1) else None
        if not t:
            continue
        name = t.group(2).lower()
        if keep:                      # nested same-name tags until its close
            if name == keep:
                depth += -1 if t.group(1) else 1
                if not depth:
                    keep = None
        elif not t.group(1) and _TX_PICKLABEL.search(part):
            keep, depth = name, 1
    text(sec[pos:])
    return "".join(out)


def _section_end(tpl, a):
    """Index just past the </section> that closes the <section> at a (tabs nest
    sections of their own)."""
    depth = 0
    for m in _SECTION_TAG.finditer(tpl, a):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return tpl.index(">", m.end()) + 1
    raise ValueError("unclosed <section> at %d" % a)


def _guide_template():
    global _guide_tpl
    if _guide_tpl is None:
        tpl, strings = _index_template(), []
        if GUIDE_TEXTOUT:
            for k in _TEXTOUT_FILLED:
                tpl = tpl.replace("{{%s}}" % k, _HTML_DEFAULTS[k])
        for t in _SHELL_TABS:
            a = tpl.index('<section class="tab" id="%s"' % t)
            b = _section_end(tpl, a)
            sec = _SHELL_H.sub(lambda m: "</div" if m.group(1) else '<div data-h="%s"' % m.group(2),
                               tpl[a:b])
            sec = sec.replace('id="%s"' % t, 'id="%s" data-nosnippet' % t, 1)
            if GUIDE_TEXTOUT:
                sec = _text_out(sec, strings)
            tpl = tpl[:a] + sec + tpl[b:]
        if strings:   # "<" escaped: no string can end the script or open a comment in it
            tpl = tpl.replace('<script src="/app.js', '<script type="application/json" id="shellText">%s</script>\n'
                              '  <script src="/app.js' % json.dumps(strings, ensure_ascii=False).replace("<", "\\u003c"), 1)
        _guide_tpl = tpl
    return _guide_tpl


_SITE = "https://wandergrade.com"   # canonical origin for sitemap URLs


_dataset_cache = {"at": 0, "payload": None, "csv": None, "retry_at": 0, "error": ""}
_DATASET_TTL = 3600
# The rebuild in flight, if any (a threading.Event, set when it lands or
# fails): one at a time, shared by every request that finds the copy expired
# meanwhile (_dataset).
_dataset_flight = [None]
_dataset_flight_lock = threading.Lock()
# Seconds a request waits on another's rebuild before rebuilding itself, as
# every request did before. Above a rebuild's worst case on a failing
# upstream, as ADV_FLIGHT_WAIT is: build_dataset.build makes three rates
# fetches one after another (rates.compute_favorability), each 3 tries of
# rates.TIMEOUT (20 s) plus 1.5 + 3 s of backoff, so 3 x 64.5 = 193.5 s.
DATASET_FLIGHT_WAIT = 240


def _dataset():
    """The public price-level dataset, rebuilt at most hourly.

    Building costs a rates fetch, so it is cached; if a rebuild fails we keep
    serving the last good copy rather than 503-ing a public data URL that other
    people may have wired into something. A failed rebuild is not tried again
    for a while, as _cached does (FAIL_RETRY with no copy, STALE_RETRY with
    one): /data reads the dataset three times per view, and with the rates
    down each read rebuilt, fetching with its retries and, on a page slot,
    queueing for the slot again after each.

    One rebuild at a time: a request that finds one in flight waits for it
    (holding no page slot, _idle_wait) and gets what it made, the new copy,
    or the stale copy or the error inside the backoff it set. When the hourly
    copy expired, every /data view and CSV/JSON download that came in during
    the rebuild used to rebuild too, side by side, each its own rates fetch.
    """
    while True:
        now = time.time()
        if _dataset_cache["payload"] is not None and now - _dataset_cache["at"] <= _DATASET_TTL:
            return _dataset_cache
        if now < _dataset_cache.get("retry_at", 0):
            if _dataset_cache["payload"] is None:
                raise RuntimeError(_dataset_cache.get("error") or "dataset rebuild failed")
            return _dataset_cache
        with _dataset_flight_lock:
            flight = _dataset_flight[0]
            lead = flight is None
            if lead:
                flight = _dataset_flight[0] = threading.Event()
        if lead:
            break
        if not _idle_wait(flight, DATASET_FLIGHT_WAIT):
            # Stuck on the network past any real rebuild: rebuild as before.
            with _no_slot():
                return _dataset_rebuild()
        # Landed or failed: the loop reads what it left (the copy, or the backoff).
    # A rates fetch: /data gives its page slot back meanwhile, and the
    # waiters get the outcome before it queues for the slot again.
    with _no_slot():
        try:
            return _dataset_rebuild()
        finally:
            with _dataset_flight_lock:
                _dataset_flight[0] = None
            flight.set()


def _dataset_rebuild():
    """Rebuild the dataset into _dataset_cache and return the cache; on a
    failure set the backoff and return the copy in hand, or raise with none."""
    now = time.time()
    try:
        payload = build_dataset.build(_ppp_data())
        _dataset_cache.update(at=now, payload=payload,
                              csv=build_dataset.to_csv(payload), retry_at=0, error="")
    except Exception as e:
        have = _dataset_cache["payload"] is not None
        _dataset_cache.update(retry_at=time.time() + (STALE_RETRY if have else FAIL_RETRY),
                              error=str(e))
        if not have:
            raise
    return _dataset_cache


# Fields a live refresh may never silently drop, with the year that goes with
# each. Without infl the site fell back to nominal FX and un-carried price
# levels (Turkey back to 0.33 and "+9%") while the digest, which reads the
# committed file, kept the real figures.
_PPP_KEEP = {"infl": "infl_year", "gdppc": "gdppc_year"}


def _ppp_keep_fields(base, live):
    """Stop a live PPP table from dropping fields the current one has.

    A few countries missing from one World Bank indicator get their current
    figures carried over into `live` (a country the source stops reporting
    shouldn't lose its carry-forward, nor block every later refresh). A loss
    on more than a tenth of them means the fetch itself was bad, and comes
    back as {field: [iso, ...]} for the caller to refuse the table. Returns
    (carried, refused)."""
    carried, refused = {}, {}
    for f, fy in _PPP_KEEP.items():
        have = [iso for iso, v in base.items() if v.get(f) is not None]
        lost = sorted(iso for iso in have if iso in live and live[iso].get(f) is None)
        if not lost:
            continue
        if len(lost) > len(have) * 0.1:
            refused[f] = lost
            continue
        for iso in lost:
            live[iso][f] = base[iso][f]
            if base[iso].get(fy) is not None:
                live[iso][fy] = base[iso][fy]
        carried[f] = lost
    return carried, refused


def _ppp_isos(lost):
    return "; ".join("%s on %d (%s%s)" % (f, len(isos), ",".join(isos[:8]),
                                          ",..." if len(isos) > 8 else "")
                     for f, isos in lost.items())


def _ppp_data():
    """PPP table, refreshed from the World Bank monthly, falling back to the
    file committed in public/.

    Why live rather than the static file alone: the committed ppp.json silently
    drifted a full year behind (only 42 countries on 2025 when the World Bank
    had published 2025 for 185) because nothing re-ran the builder. Same shape
    as _handle_popularity, which already does this for tourism receipts.

    Nothing here ever blocks on the network: a request is answered from the
    committed file (or the last good fetch) immediately, and the refresh runs on
    a background thread. Fetching inline would have made the first visitor after
    a deploy wait up to 40s for the World Bank.
    """
    now = time.time()
    if _ppp_cache["data"] is None:
        try:
            _ppp_cache["data"] = build_ppp.committed()
        except Exception:
            _ppp_cache["data"] = {}
    if (now - _ppp_cache["at"]) >= PPP_TTL and not _ppp_cache.get("busy"):
        _ppp_cache["busy"] = True

        def refresh():
            retry_at = time.time() - PPP_TTL + PPP_RETRY   # don't hammer a bad upstream
            try:
                base = _ppp_cache["data"] or {}
                # previous=: a failed CPI/GDP call carries those fields over
                # from the table we already serve instead of dropping them.
                live = build_ppp.build(previous=base) or {}
                # A truncated or partly-null API response must never quietly
                # shrink the number of gradeable countries, nor strip the
                # inflation or income fields (_ppp_keep_fields).
                if len(live) < max(1, int(len(base) * 0.9)):
                    _ppp_cache["at"] = retry_at
                    print("[ppp] live fetch gave %d vs %d committed; keeping current"
                          % (len(live), len(base)), flush=True)
                    return
                carried, refused = _ppp_keep_fields(base, live)
                if refused:
                    _ppp_cache["at"] = retry_at
                    print("[ppp] live table lost %s; keeping current" % _ppp_isos(refused),
                          flush=True)
                    return
                if carried:
                    print("[ppp] live table lacked %s; kept the current figures"
                          % _ppp_isos(carried), flush=True)
                _ppp_cache["data"] = live
                _ppp_cache["at"] = time.time()
                print("[ppp] refreshed: %d countries" % len(live), flush=True)
            except Exception as e:
                _ppp_cache["at"] = retry_at
                print("[ppp] live fetch failed (%s); keeping current" % e, flush=True)
            finally:
                _ppp_cache["busy"] = False

        threading.Thread(target=refresh, daemon=True).start()
    return _ppp_cache["data"]


_plh_cache = {"at": 0, "data": None}
# /ppp.json's and /pl_history.json's bytes (and gzipped, once a client asks)
# per table object: the caches replace a table on refresh, never edit it,
# so the same object means the same bytes. Off with the page memo (tests and
# tools that edit a table in place dump it every time); main() turns it on.
_json_bytes_memo = {}      # path -> (table, raw, gz or None)
_json_bytes_lock = threading.Lock()


def _json_bytes(path, obj, want_gz):
    """(raw, gzipped or None) of json.dumps(obj) for `path`, from the memo
    while `obj` is the table it was made from."""
    if _page_memo is None:
        return json.dumps(obj).encode("utf-8"), None
    with _json_bytes_lock:
        hit = _json_bytes_memo.get(path)
    if hit is None or hit[0] is not obj:
        hit = (obj, json.dumps(obj).encode("utf-8"), None)
    if want_gz and hit[2] is None:
        hit = hit[:2] + (gzip.compress(hit[1], GZIP_LEVEL),)
    with _json_bytes_lock:
        _json_bytes_memo[path] = hit
    return hit[1], hit[2]


def _pl_history():
    """Price level per country per year (the Cost of living chart), from the
    committed file at once and refreshed from the World Bank monthly on a
    background thread — the lesson of ppp.json, which drifted a year behind
    while nothing re-ran its builder. A refresh that would lose countries or
    years is refused."""
    now = time.time()
    if _plh_cache["data"] is None:
        try:
            _plh_cache["data"] = build_pl_history.committed()
        except Exception:
            _plh_cache["data"] = {"years": [], "pl": {}}
    if (now - _plh_cache["at"]) >= PPP_TTL and not _plh_cache.get("busy"):
        _plh_cache["busy"] = True

        def refresh():
            retry_at = time.time() - PPP_TTL + PPP_RETRY
            try:
                base = _plh_cache["data"] or {}
                live = build_pl_history.build()
                if len(live["pl"]) < int(len(base.get("pl") or {}) * 0.9) \
                        or (base.get("years") and live["years"][-1] < base["years"][-1]):
                    _plh_cache["at"] = retry_at
                    print("[pl-history] live fetch gave %d countries to %s; keeping current"
                          % (len(live["pl"]), live["years"][-1]), flush=True)
                    return
                _plh_cache["data"] = live
                _plh_cache["at"] = time.time()
            except Exception as e:
                _plh_cache["at"] = retry_at
                print("[pl-history] live fetch failed (%s); keeping current" % e, flush=True)
            finally:
                _plh_cache["busy"] = False

        threading.Thread(target=refresh, daemon=True).start()
    return _plh_cache["data"]


_guide_links_html = None


def _guide_links():
    """Anchors to every /guide/<slug>, for the collapsed index in the footer.

    The homepage previously contained no link to any guide page at all — the
    ranking table is built client-side, so a crawler saw a homepage that linked
    nowhere and 176 pages reachable only via the sitemap. Sitemap discovery
    alone gives no internal link equity and a lower crawl priority, which is a
    large part of why so few guides were indexed.

    Built once and cached: the slug list only changes on deploy.
    """
    global _guide_links_html
    if _guide_links_html is None:
        _guide_links_html = "".join(
            '<a href="/guide/%s">%s</a>' % (slug, html.escape(render_guide.name_for_iso(iso) or slug.title()))
            for slug, iso in render_guide.all_slugs())
    return _guide_links_html


def _guide_count():
    """How many guides the index lists — the number the "Browse all N country
    guides" summary quotes, so it can't go stale."""
    return _guide_links().count("<a ")


def _sitemap():
    """Generate sitemap.xml from the live slug list.

    Was a static file committed 2026-07-06, which had two problems Search
    Console showed: no <lastmod> at all (Google ignores changefreq/priority, so
    the file carried NO freshness signal), and it listed ?tab= variants of the
    homepage that canonicalize to "/" — Google filed those as "Alternate page
    with proper canonical tag" and they wasted crawl budget. Generating it
    means it can never drift from the real page set either.

    lastmod is the mtime of the newest file that actually feeds guide content —
    honest freshness, not a fabricated "now" on every request (which search
    engines learn to distrust).
    """
    # Content data only — deliberately NOT index.html. The template changes on
    # every CSS/markup tweak, which would bump all 177 lastmods for edits that
    # don't touch what a guide page actually says. A lastmod that moves
    # constantly is one Google stops believing.
    # NOT file mtimes: Render's deploy is a fresh checkout, so every mtime is
    # the deploy time and all 178 lastmods moved on every template tweak —
    # exactly the fabricated freshness this block documents avoiding. The
    # stamp is a committed file, bumped only when the content JSONs
    # (slugs/climate/activities/country-names/visa) actually change — every
    # page shares it.
    # A guide's own snapshot (its title, description, price figure and advisory
    # level — the guide-facts document the server recomputes daily,
    # fxtracker/guide_facts.py) moves only that guide: each entry records the
    # day it last changed as "m", so the daily recompute re-dates only the
    # guides whose figure or level moved, never "/" and "/data", whose content
    # it doesn't touch. And the day the snapshot passes render_guide.STALE_DAYS
    # every guide drops its figures — a real change, dated as one.
    try:
        with open(os.path.join(PUBLIC, "content-stamp.txt"), encoding="utf-8") as f:
            stamp = f.read().strip()[:10]
    except OSError:
        stamp = ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp or ""):
        stamp = time.strftime("%Y-%m-%d", time.gmtime())
    doc = guide_facts.get_doc() or {}  # one document for all 190 lastmods
    # The list pages are dated by their data, floored at the stamp:
    # /safe-and-cheap by the snapshot its prices come from, /do-not-travel by
    # the newest level change the cached feeds carry (none cached: the
    # stamp). Never today — the same fabricated freshness as above.
    safe_lm = max(stamp, render_lists.lastmod_of(doc.get("_asof")))
    dnt_lm = max(stamp, render_lists.newest_change({s: _adv_cached(s) for s in _ADV_SRCS}))
    strength_lm = _strength_lastmod(stamp)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
           '  <url><loc>%s/</loc><lastmod>%s</lastmod></url>' % (_SITE, stamp),
           '  <url><loc>%s/data</loc><lastmod>%s</lastmod></url>' % (_SITE, stamp),
           '  <url><loc>%s/safe-and-cheap</loc><lastmod>%s</lastmod></url>' % (_SITE, safe_lm),
           '  <url><loc>%s/do-not-travel</loc><lastmod>%s</lastmod></url>' % (_SITE, dnt_lm),
           '  <url><loc>%s/dollar-strength</loc><lastmod>%s</lastmod></url>' % (_SITE, strength_lm),
           # Dated by its own "Last updated", the day its words last changed:
           # a content-stamp bump for the guides' data doesn't touch it.
           '  <url><loc>%s/privacy</loc><lastmod>%s</lastmod></url>' % (_SITE, render_privacy.UPDATED),
           # The same for the methodology page: its own date, moved with its
           # words (scripts/test_how_grades_work.py holds the two together).
           '  <url><loc>%s%s</loc><lastmod>%s</lastmod></url>'
           % (_SITE, render_methodology.PATH, render_methodology.UPDATED)]
    # /cheapest and its 12 months, by the exchange rates' own date (every
    # row's price and grade moves with them), else the snapshot's; floored
    # at the stamp like the lists above, never today.
    cheap_lm = max(stamp, render_cheapest.lastmod_of(_fx_inputs()[0], doc))
    out += ['  <url><loc>%s%s</loc><lastmod>%s</lastmod></url>' % (_SITE, p, cheap_lm)
            for p in render_cheapest.PATHS]
    expired = render_guide.snapshot_expired_on(doc=doc)
    for slug, iso in render_guide.all_slugs():
        days = [stamp, render_guide.snapshot_changed(iso, doc), expired.isoformat() if expired else ""]
        out.append('  <url><loc>%s/guide/%s</loc><lastmod>%s</lastmod></url>'
                   % (_SITE, slug, max(x for x in days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x))))
    out.append('</urlset>')
    return ("\n".join(out) + "\n").encode("utf-8")   # _send_body takes bytes


# 50 characters: the 65 with " | WanderGrade" were cut in results (review #32).
_DATA_TITLE = "Cost of Living by Country: Free CSV & JSON Dataset"
def _dataset_count():
    """Rows in the live dataset — the count the /data copy quotes. It was
    hardcoded, and went stale the day Aruba, Curacao and Sierra Leone joined."""
    try:
        return len(_dataset()["payload"]["countries"])
    except Exception:
        return 176


def _data_desc():
    return ("Free dataset: what US$100 buys in %d countries, from World Bank PPP "
            "carried forward for inflation, at today's exchange rate. CSV and JSON, no sign-up."
            % _dataset_count())


def _data_page_body_tpl():
    """The dataset's own page. A public data URL nothing links to is a dead
    letter — crawlers never reach it and nobody can tell what it means, so the
    file needs somewhere to explain its method and licence.

    Served as a standalone document rather than through the app shell: the shell
    is a single-page app that boots into Top Picks and paints over any server
    body it wasn't expecting, so this page would have rendered the picks table
    to a reader who asked for a dataset.
    """
    return (
        '<div class="ssrguide">'
        "<h1>Cost of living by country: the dataset</h1>"
        "<p>What US$100 buys in <strong>__N__ countries</strong>, as a free CSV or JSON "
        "download. No sign-up, no key; exchange rates as of __ASOF__ (refreshed daily).</p>"
        '<p><a href="/data/price-levels.csv"><strong>Download CSV</strong></a> &middot; '
        '<a href="/data/price-levels.json"><strong>Download JSON</strong></a></p>'
        "<h2>What's in it</h2>"
        "<ul>"
        "<li><strong>price_level</strong> — World Bank PPP conversion factor for household "
        "consumption, carried "
        "forward from its year by the gap between local and US inflation, divided by "
        "the market exchange rate. 1.00 means prices match the US, 0.50 means half.</li>"
        "<li><strong>usd100_buys</strong> — the local purchasing power of US$100, in US "
        "dollars.__VN_BUYS__</li>"
        "<li>Plus the inputs, so you can check the arithmetic: PPP factor and its year, "
        "GDP per capita and its year, the currency used, the currency the PPP factor is "
        "quoted in (<code>ppp_unit</code>), the inflation rate and its year "
        "(<code>inflation_pct</code>, <code>inflation_year</code>), and the carry-forward "
        "multiplier it produced (<code>inflation_factor</code>, 1 when there is no "
        "current figure).</li>"
        "<li><strong>ppp_basis</strong> — <code>household</code>, or <code>gdp</code> where the World "
        "Bank has no usable recent household figure: its last one, carried forward along the GDP-wide "
        "factor; "
        "<code>ppp_source</code> says whose figure it is (Taiwan's, entered by hand: the IMF's GDP-wide "
        "figure, adjusted to household spending with the Penn World Table).</li>"
        "</ul>"
        # The table is US-based because World Bank PPP is quoted against the US;
        # a reader from anywhere else needs one line on how to compare from home.
        # The worked example is the download's own figures (_data_example).
        "<p>Comparing from somewhere else? Divide one price_level by the other: "
        "__EXAMPLE__. The <a href=\"/?tab=data&amp;dm=afford\">Data tab</a> does this "
        "for your home currency. Join on <code>iso</code>; <code>country</code> uses "
        "World Bank naming.</p>"
        "<h2>Why it differs from other PPP tables</h2>"
        "<p>Most purchasing-power figures are a snapshot: prices and exchange rates from "
        "the year the PPP was published, so they drift as both move. This carries the "
        "PPP factor forward for inflation and divides by <em>today's</em> market rate. A "
        "country shows up cheaper here than in a year-old table only when its currency "
        "has fallen faster than its prices have risen (beyond US inflation); where prices "
        "outran the currency, it shows up pricier.</p>"
        "<h2>What it is not</h2>"
        "<p>These are national averages for residents. Neighbourhoods popular with "
        "visitors, and rent paid by foreigners, run well above them — useful for "
        "comparing countries against each other, not as a travel budget.</p>"
        "<p>Countries whose exchange rate is a managed peg, or otherwise so far out of "
        "line with their income that the result would be fictional, are left out rather "
        "than guessed at. That is why the count is __N__ and not every country on earth.</p>"
        "<h2>Sources and licence</h2>"
        "<p>PPP conversion factors, consumer-price inflation and GDP per capita from the World Bank "
        "(<a href=\"https://data.worldbank.org\" rel=\"noopener\" target=\"_blank\">data.worldbank.org</a>, "
        "CC BY 4.0), and for Taiwan, which it doesn't cover, from the IMF's World Economic Outlook, "
        "adjusted to household spending with the "
        "<a href=\"https://www.rug.nl/ggdc/productivity/pwt/\" rel=\"noopener\" target=\"_blank\">Penn World "
        "Table</a> (CC BY 4.0); exchange rates from "
        "<a href=\"https://fxratesapi.com\" rel=\"noopener\" target=\"_blank\">fxratesapi.com</a>. "
        "The derived figures are free to reuse with attribution to "
        "<a href=\"/\">WanderGrade</a>.</p>"
        "</div>"
    )



def _rates_as_of():
    """The dataset's rate date as '28 Sep 2026' — day-month-year, not US
    numeric, for a page read from anywhere. Empty when the dataset is down."""
    try:
        d = datetime.strptime(_dataset()["payload"]["meta"]["rates_as_of"], "%Y-%m-%d")
        return "%d %s %d" % (d.day, d.strftime("%b"), d.year)
    except Exception:
        return ""


# "prices are about a third of Germany's": a ratio as the nearest plain
# fraction.
_FRACTION_WORDS = ((0.1, "a tenth of"), (0.2, "a fifth of"), (0.25, "a quarter of"), (1 / 3, "a third of"),
                   (0.4, "two fifths of"), (0.5, "half"), (0.6, "three fifths of"), (2 / 3, "two thirds of"),
                   (0.75, "three quarters of"), (0.8, "four fifths of"), (1.0, "the same as"))


def _fraction_words(r):
    """0.36 -> "about a third of"; 1.6 -> "about 1.6 times"."""
    if r > 1.1:
        return "about %.1f times" % r
    return "about " + min(_FRACTION_WORDS, key=lambda f: abs(f[0] - r))[1]


def _data_example():
    """The /data page's worked example from the price levels the download
    serves: (Vietnam's "usd100_buys" sentence, the "Vietnam 0.28 / Germany
    0.78 = 0.36" example). It was typed in, and still said Germany 0.81 after
    the download moved to 0.78 (household prices). Without the dataset, the
    sentence is left out and the example uses no numbers."""
    try:
        rows = {r.get("iso"): r for r in _dataset()["payload"]["countries"]}
        vn, de = rows["VN"], rows["DE"]
        a, b = "%.2f" % vn["price_level"], "%.2f" % de["price_level"]
        r = "%.2f" % (float(a) / float(b))
        buys = " Vietnam sits near US$%d." % (picks.js_round(vn["usd100_buys"] / 10.0) * 10)
    except Exception:
        return "", "Vietnam's &divide; Germany's is Vietnam's prices as a share of Germany's"
    return buys, ("Vietnam %s &divide; Germany %s &asymp; %s, so prices are %s Germany's"
                  % (a, b, r, _fraction_words(float(r))))


def _data_page_body():
    # The count, date and worked example come from the dataset; the copy has
    # literal % signs, so they are swapped in rather than %-formatted.
    asof = _rates_as_of()
    buys, example = _data_example()
    return (_data_page_body_tpl().replace("__N__", str(_dataset_count()))
            .replace("exchange rates as of __ASOF__ (refreshed daily)",
                     "exchange rates as of %s (refreshed daily)" % asof if asof
                     else "exchange rates refreshed daily")
            .replace("__VN_BUYS__", buys).replace("__EXAMPLE__", example))

# The same 🌍 tab icon as index.html: without it the browser asked for
# /favicon.ico on every shell page and got a 404.
_SHELL_ICON = ('<link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' '
               'viewBox=\'0 0 100 100\'><text y=\'.9em\' font-size=\'90\'>🌍</text></svg>">')


def _shell_page(title, body, head="", analytics=True, credits=True):
    """A whole, self-contained HTML document in the site's header/footer —
    no app.js. /data, the 404 page, the sign-in confirmation and the two list
    pages use it. credits=False drops the data sources from the footer, for a
    page that shows no data; a string is that page's own credit line (HTML)."""
    default_credits = ('Data: <a href="https://data.worldbank.org" rel="noopener" '
                       'target="_blank">World Bank</a> &amp; '
                       '<a href="https://fxratesapi.com" rel="noopener" target="_blank">fxratesapi.com</a> '
                       "&middot; ")
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>%s</title>%s%s"
        # The brand font and the saved theme, as index.html has them: without
        # these the shell pages fell back to system-ui and followed the OS even
        # after the reader had picked light or dark on the main page.
        '<link rel="preload" href="/fonts/LDIoaomQNQcsA88c7O9yZ4KMCoOg4Ko20yygg_vb.woff2" '
        'as="font" type="font/woff2" crossorigin>'
        '<link rel="stylesheet" href="/fonts/jakarta.css">'
        '<link rel="stylesheet" href="/styles.css?v=%s">'
        '<script>(function(){var t;try{t=localStorage.getItem("fx_theme")}catch(e){}'
        'if(t!=="dark"&&t!=="light")t=window.matchMedia&&matchMedia("(prefers-color-scheme: dark)")'
        '.matches?"dark":"light";document.documentElement.setAttribute("data-theme",t);})();</script>'
        "%s</head><body>"
        '<header><div class="headrow"><a class="homelink" href="/">'
        '<span class="brand">🌍 WanderGrade</span>'
        '<p class="sitetitle">Where Should I Travel to Next?</p>'
        '<p class="sub">Every country, graded A+ to F — free, no sign-up.</p>'
        "</a></div></header>"
        # .shellmain: the site gutter and reading measure (styles.css) — a bare
        # <main> ran edge to edge, with no side padding at all on a phone.
        '<main class="shellmain">%s</main>'
        "<footer>%s"
        # The two list pages, as index.html's footer carries them: an internal
        # link from every page, not just a sitemap entry (which earns no
        # crawl priority — see _guide_links).
        'Lists: <a href="/safe-and-cheap">Safest cheap countries</a> &middot; '
        '<a href="/do-not-travel">Do Not Travel list</a> &middot; '
        '<a href="/cheapest">Cheapest by month</a> &middot; '
        '<a href="/dollar-strength">Dollar strength</a> &middot; '
        '<a href="/how-grades-work">How grades work</a> &middot; '
        '<a href="/privacy">Privacy</a> &middot; '
        '<a href="/">Back to WanderGrade</a></footer></body></html>'
        % (html.escape(title), _SHELL_ICON, head, _asset_version("styles.css"),
           _analytics_tag() if analytics else "", body,
           credits if isinstance(credits, str) else (default_credits if credits else ""))
    ).encode("utf-8")


def _data_jsonld():
    """schema.org Dataset markup for /data (Google's dataset search reads
    it): the two downloads, the sources it is built on, and the rates' date
    as dateModified (left out while the dataset is down). No license
    property: the page offers reuse with attribution, which is no named
    licence, so none is claimed (Doug's call, review #32)."""
    try:
        asof = _dataset()["payload"]["meta"]["rates_as_of"]
    except Exception:
        asof = None
    doc = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Cost of living by country: price levels vs the US",
        "description": _data_desc(),
        "url": _SITE + "/data",
        "keywords": ["cost of living", "price level", "purchasing power parity", "PPP",
                     "exchange rates", "travel costs"],
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "WanderGrade", "url": _SITE + "/"},
        "isBasedOn": ["https://data.worldbank.org", "https://fxratesapi.com"],
        "variableMeasured": ["price_level", "usd100_buys"],
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "text/csv",
             "contentUrl": _SITE + "/data/price-levels.csv"},
            {"@type": "DataDownload", "encodingFormat": "application/json",
             "contentUrl": _SITE + "/data/price-levels.json"},
        ],
    }
    if asof and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(asof)):
        doc["dateModified"] = asof
    # "</" can't close the script early: the JSON's own escape for "/".
    return ('<script type="application/ld+json">%s</script>'
            % json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


def _render_data_page():
    """A whole, self-contained HTML document for /data — no app.js.
    Carries the same og:image/twitter card as every other page: this is the
    page built to be shared, and it used to unfurl with no image."""
    desc = html.escape(_data_desc(), quote=True)
    head = (
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s/data">'
        '<meta property="og:type" content="website">'
        '<meta property="og:title" content="Cost of Living by Country — Free Dataset">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:url" content="%s/data">'
        '<meta property="og:site_name" content="WanderGrade">'
        '<meta property="og:image" content="%s/og.png">'
        '<meta name="twitter:card" content="summary_large_image">'
        % (desc, _SITE, desc, _SITE, _SITE)) + _data_jsonld()
    return _shell_page(_DATA_TITLE, _data_page_body(), head)


# ---- the list pages: /safe-and-cheap and /do-not-travel -----------------------
# Rendered by fxtracker/render_lists.py from the documents the server already
# holds — the three advisory caches, the guide-facts snapshot, climate, health,
# the price-level history, the cached rates — so a request costs a dict lookup
# (memoized below) and never an upstream fetch of its own.
_LIST_PATHS = ("/safe-and-cheap", "/do-not-travel")
_ADV_SRCS = ("us", "ca", "de")
_ADV_LINKS = ('<a href="https://travel.state.gov" rel="noopener" target="_blank">US State Dept</a>, '
              '<a href="https://travel.gc.ca/travelling/advisories" rel="noopener" target="_blank">'
              'Global Affairs Canada</a> &amp; '
              '<a href="https://www.auswaertiges-amt.de/de/ReiseUndSicherheit/reise-und-sicherheitshinweise" '
              'rel="noopener" target="_blank">German Foreign Office</a>')
_LIST_CREDITS = {
    "/safe-and-cheap": ('Data: <a href="https://data.worldbank.org" rel="noopener" target="_blank">World Bank</a> '
                        "(PPP; Taiwan: IMF, Penn World Table) &middot; Advisories: " + _ADV_LINKS
                        + " &middot; Health notes: Global Affairs "
                        'Canada &middot; Climate: <a href="https://open-meteo.com" rel="noopener" target="_blank">'
                        "Open-Meteo</a> &middot; "),
    "/do-not-travel": "Advisories: " + _ADV_LINKS + " &middot; ",
}
_list_memo = {}


def _adv_cached(source):
    """The advisory payload for `source` if the cache holds one (any age),
    else None — never a fetch. The sitemap reads these: it must not wait on
    three feeds after a cold start."""
    hit = _adv_cache.get(source)
    return hit[1] if hit else None


def _adv_inputs():
    """The three payloads — None where a feed is down with nothing cached, so
    the page says so and goes out uncached — when each was fetched, and
    {source: seconds} for a feed whose refresh is failing (the copy's age)."""
    payloads, fetched, stale = {}, {}, {}
    # A list not in hand is computed here (_adv_compute_once), which gives the
    # page slot back meanwhile; with any cold, the three are read under one
    # _no_slot, so the page queues for its slot again once, not once per
    # list, each time behind a crawler's guides.
    cold = any(_adv_cache.get(src) is None for src in _ADV_SRCS)
    with (_no_slot() if cold else contextlib.nullcontext()):
        got = {}
        for src in _ADV_SRCS:
            try:
                got[src] = _advisories_payload(src)
            except Exception as e:
                got[src] = e
    for src in _ADV_SRCS:
        p = got[src]
        if isinstance(p, Exception):
            print("[lists] %s advisories unavailable: %s" % (src, p), flush=True)
            payloads[src] = None
            continue
        hit = _adv_cache.get(src)
        # The cache's own object, not what _cached hands out while a refresh
        # fails: that is a new dict per request (the copy plus stale flags),
        # which missed the memo every time. Same content; the flags are read
        # off it here so the page can say the refresh is failing.
        payloads[src] = hit[1] if hit else p
        if hit:
            fetched[src] = hit[0]
        if p.get("stale_age"):
            stale[src] = int(p["stale_age"])
    return payloads, fetched, stale


# Who says "do not travel" (advisories.dnt_sources), from the three lists the
# cache holds at any age — never a fetch on a request's path. The guide's
# stays and tours go by it whichever list the reader picked: Germany's
# Reisewarnung for Saudi Arabia (US and Canada: Level 3), Canada's "Avoid all
# travel" for Venezuela (US: 3), the US's and Canada's Level 4 for Burkina
# Faso (Germany: some regions). Memoized on the cached payloads themselves
# (a refresh is a new object): ~700 items a guide render otherwise.
_dnt_memo = [None]   # [(payloads tuple, result)], swapped whole: request threads share it


def _adv_dnt():
    """{"flags": {ISO: [source, ...]}, "unknown": [source, ...] (lists not in
    hand), "own": {source: {ISO: level}}} from the cache as it is."""
    payloads = {}
    for src in _ADV_SRCS:
        hit = _adv_cache.get(src)
        payloads[src] = hit[1] if hit else None
    key = tuple(payloads[s] for s in _ADV_SRCS)
    memo = _dnt_memo[0]
    if memo and all(a is b for a, b in zip(memo[0], key)):
        return memo[1]
    flags, unknown = advisories.dnt_sources(payloads, guide_sizers.ADV_PARENT)
    val = {"flags": flags, "unknown": unknown,
           "own": {s: advisories.own_levels(p) for s, p in payloads.items() if p is not None}}
    _dnt_memo[0] = (key, val)
    return val


def _dnt_failed(dnt):
    """The lists not in hand whose fetch has failed (_adv_failed) — not ones
    still on their way after a boot: a reader can't wait those out, so the
    guide draws no stays or tours for them at once (app.js
    ensureBookingsKnown stops asking) rather than hold the block for a
    minute and then drop it."""
    return [s for s in dnt["unknown"] if s in _adv_failed]


def _guide_flagged(iso, dnt=None):
    """True when a government's own list in hand rates the country (or the
    territory's parent) Level 4."""
    dnt = dnt or _adv_dnt()
    return bool(advisories.dnt_for(iso, dnt["own"], guide_sizers.ADV_PARENT))


def _guide_no_bookings(iso, dnt=None):
    """True when a guide shows no stays or tours: a government's own list
    rates the country Level 4 (_guide_flagged), or a list whose fetch failed
    can't say it doesn't (a missing list is unknown, never a no)."""
    dnt = dnt or _adv_dnt()
    return _guide_flagged(iso, dnt) or bool(_dnt_failed(dnt))


def _with_dnt(data, dnt):
    """An /api/advisories payload with the do-not-travel marks app.js's
    guideNoBookings reads: `dnt` on each item some government's own list rates
    Level 4 (["us", "ca"]: who says so), `dnt_unlisted` for such a country
    the list has no row for at all (a gap-fill that failed when it was
    built), and `dnt_pending` naming the lists not in hand yet — until they
    are, a country without a mark is not known to be clear — with
    `dnt_failed`, those of them whose fetch failed (no use waiting). A new
    dict: the cached payload is shared."""
    flags = dnt["flags"]
    items = data.get("items") or []
    out = dict(data, items=[dict(it, dnt=flags[it["iso"]]) if it.get("iso") in flags else it
                            for it in items])
    listed = {it.get("iso") for it in items}
    unlisted = {iso: by for iso, by in flags.items() if iso not in listed}
    if unlisted:
        out["dnt_unlisted"] = unlisted
    if dnt["unknown"]:
        out["dnt_pending"] = list(dnt["unknown"])
        failed = _dnt_failed(dnt)
        if failed:
            out["dnt_failed"] = failed
    return out


_adv_warming = set()
_adv_warm_lock = threading.Lock()


def _adv_refresh(src):
    """Fetch one government's list on a background thread, unless one is
    already fetching it. Never raises: a request reading the copy in hand
    calls this, and a thread that won't start must not fail that request."""
    with _adv_warm_lock:
        if src in _adv_warming:
            return
        _adv_warming.add(src)

    def run():
        try:
            _advisories_payload(src, background=True)
        except Exception:
            pass
        finally:
            with _adv_warm_lock:
                _adv_warming.discard(src)

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        # (RuntimeError "can't start new thread".) Left in _adv_warming, the
        # list would never be refreshed again: let the next request try.
        with _adv_warm_lock:
            _adv_warming.discard(src)


def _warm_adv_lists():
    """Fetch, in the background and once at a time, each government's list the
    cache doesn't hold or holds past ADV_TTL, so the do-not-travel marks are
    whole and current: the requests that fill the cache ask for one list each,
    and after a deploy Canada's and Germany's stayed unloaded until a reader
    picked them. A list in its upstream failure backoff is left alone
    (_cached would only hand back what it has)."""
    now = time.time()
    for src in _ADV_SRCS:
        hit = _adv_cache.get(src)
        if hit and now - hit[0] < ADV_TTL:
            continue
        fail = _upstream_fail.get(("advisories", src))
        if fail and now < fail[0]:
            continue
        _adv_refresh(src)


def _guide_cache(iso):
    """The Cache-Control a guide page goes out with. Until the default
    origin's flight-value pass has run once (~9 minutes after a deploy), a
    render has no fares-strip marks; cached at the edge it would serve that
    for 5 minutes. Likewise while a government's list isn't in hand: the
    stays stand-in is drawn for a country that list may yet rule out (Saudi
    Arabia before Germany's list is in), or none at all while a fetch has
    failed, and the next render knows — unless a list already in hand rules
    the country out (_guide_flagged)."""
    _warm_adv_lists()
    dnt = _adv_dnt()
    warm = ((not flights.is_configured()
             or flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN))
            and (not dnt["unknown"] or _guide_flagged(iso, dnt)))
    return "public, max-age=300" if warm else "no-store"


def _fx_inputs():
    """{currency: strength_pct} from the rates the server already caches, and
    the PPP table, for the dollar column. Read, never computed: a cold rates
    cache would cost the page three upstream fetches, so the column waits for
    the rates to be cached (_warm_rates shortly after boot, else the first
    /api/rates or the daily recompute) and is left out until then."""
    try:
        cfg = store.load_config()
        hit = _rates_cache.get((cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD"))
        return (hit[1] if hit else None), (_ppp_data() if _ppp_cache["at"] else None)
    except Exception as e:
        print("[lists] no dollar column: %s" % e, flush=True)
        return None, None


def _fx_map(rates_payload):
    """{currency: strength_pct} from a cached /api/rates payload. Built only
    on a memo miss: the payload object is the memo key, not this dict."""
    if not rates_payload:
        return None
    return {r["code"]: r["strength_pct"] for r in rates_payload.get("rows") or []
            if "code" in r and "strength_pct" in r}


def _list_head(path, title, desc):
    """description, canonical and the share card, as _render_data_page has them."""
    d, u = html.escape(desc, quote=True), _SITE + path
    return ('<meta name="description" content="%s">'
            '<link rel="canonical" href="%s">'
            '<meta property="og:type" content="website">'
            '<meta property="og:title" content="%s">'
            '<meta property="og:description" content="%s">'
            '<meta property="og:url" content="%s">'
            '<meta property="og:site_name" content="WanderGrade">'
            '<meta property="og:image" content="%s/og.png">'
            '<meta name="twitter:card" content="summary_large_image">'
            % (d, u, html.escape(title, quote=True), d, u, _SITE))


def _list_page(path):
    """{bytes, degraded} for a list page, memoized on the identity of its
    inputs: a refreshed feed, snapshot, health document or rates entry is a
    new object and re-renders; so does a new UTC day (the "recent" window and
    the year in the title). The inputs are kept beside the result so none of
    their ids can be recycled while it is the key. Every other request is a
    dict lookup, which is what Render's free tier can afford."""
    payloads, fetched, stale = _adv_inputs()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    docs = (payloads["us"], payloads["ca"], payloads["de"])
    if path == "/safe-and-cheap":
        rp, ppp = _fx_inputs()
        docs += (guide_facts.get_doc() or {}, render_lists.climate(), health.get_doc(), _pl_history(), rp, ppp)
        render = lambda: render_lists.safe_and_cheap(*docs[:7], fetched=fetched, fx=_fx_map(rp), ppp=ppp,
                                                     stale=stale, today=today)
    else:
        render = lambda: render_lists.do_not_travel(*docs, fetched=fetched, stale=stale, today=today)
    # A failing refresh is printed to the hour ("copy from 7h ago",
    # render_lists._age), so the memo keys on the hour: the text moves once
    # an hour, not every request.
    key = tuple(id(x) for x in docs) + (today,) + tuple(stale.get(s, 0) // 3600 for s in _ADV_SRCS)
    hit = _list_memo.get(path)
    if hit and hit[0] == key:
        return hit[2]
    page = render()
    out = {"bytes": _shell_page(page["title"], page["html"], _list_head(path, page["title"], page["desc"]),
                                credits=_LIST_CREDITS[path]),
           "degraded": page["degraded"], "available": page.get("available", True)}
    _list_memo[path] = (key, docs, out)
    return out


# ---- /dollar-strength (fxtracker/render_strength.py) ---------------------------
# The Currency tab's rows ranked after inflation, under the Data tab's dollar
# index, from what the server already holds: the USD /api/rates entry and the
# PPP table (_fx_inputs, as /safe-and-cheap's dollar column reads them) and
# the strength chart's ECB history as rates.get_history() last stored it.
# Never a fetch on a request's path; a missing input renders, says so and
# goes out no-store. Imported here, beside the only code that uses it.
from fxtracker import render_strength  # noqa: E402

# The shell pages whose other spellings (/Cheapest/January, /Safe-and-cheap,
# a capital and a slash at once) 301 to their lowercase URL. Never /guide/:
# that has its own redirects (_guide_redirect).
_LOWER_PATHS = frozenset(_LIST_PATHS + render_cheapest.PATHS
                         + (render_strength.PATH, "/privacy", render_methodology.PATH, "/data"))

_STRENGTH_CREDITS = ('Data: <a href="https://fxratesapi.com" rel="noopener" target="_blank">fxratesapi.com</a> '
                     '(rates) &middot; <a href="https://www.ecb.europa.eu/stats/policy_and_exchange_rates/'
                     'euro_reference_exchange_rates/html/index.en.html" rel="noopener" target="_blank">'
                     "ECB reference rates</a> (index history since 1999) &middot; "
                     '<a href="https://data.worldbank.org" rel="noopener" target="_blank">World Bank</a> '
                     "(PPP, inflation; Taiwan: IMF, Penn World Table) &middot; Advisories: " + _ADV_LINKS
                     + " &middot; ")
_strength_memo = [None]        # (key, inputs, out), swapped whole: request threads share it
_strength_idx_memo = [None]    # (history snapshot, day, index payloads)
_strength_warm = {"busy": False, "at": 0.0}


def _strength_history():
    """The strength chart's history (fetched_at, dates, cols) as the cache
    holds it, or None — never a fetch here. Only a Data-tab visit refreshes
    it otherwise, so a copy past rates.HISTORY_TTL asks for a refresh on a
    background thread (at most once a minute) and the page re-renders when
    it lands; one past HISTORY_STALE, which /api/index no longer serves
    either, counts as not cached."""
    snap = rates._history["snap"]
    now = time.time()
    if (not snap[1] or now - snap[0] >= rates.HISTORY_TTL) and not _strength_warm["busy"] \
            and now - _strength_warm["at"] >= 60:
        _strength_warm.update(busy=True, at=now)

        def run():
            try:
                rates.get_history()
            except Exception as e:
                print("[dollar-strength] index history refresh failed: %s" % e, flush=True)
            finally:
                _strength_warm["busy"] = False

        threading.Thread(target=run, daemon=True).start()
    return snap if snap[1] and now - snap[0] < rates.HISTORY_STALE else None


def _strength_index(snap, day):
    """The index's 1-year and since-1999 figures for `day` (the date
    rates.compute_index windows by), memoized on the history snapshot."""
    if snap is None:
        return None
    memo = _strength_idx_memo[0]
    if memo and memo[0] is snap and memo[1] == day:
        return memo[2]
    try:
        val = render_strength.index_payloads(snap[1], snap[2], datetime.strptime(day, "%Y-%m-%d").date())
    except Exception as e:
        print("[dollar-strength] index figures unavailable: %s" % e, flush=True)
        val = None
    _strength_idx_memo[0] = (snap, day, val)
    return val


def _strength_page():
    """{bytes, degraded} for /dollar-strength, memoized on the identity of
    its inputs (a refreshed rates entry, PPP table or history is a new
    object) and the day — like _list_page."""
    rp, ppp = _fx_inputs()
    day = datetime.now().strftime("%Y-%m-%d")   # compute_index's date.today()
    # Prices are carried to the UTC day, as /cheapest (picks._score) and the
    # Currency tab (app.js nowYearFrac) carry them, so the three agree.
    utc_day = time.strftime("%Y-%m-%d", time.gmtime())
    idx = _strength_index(_strength_history(), day)
    # The three advisory lists as the cache holds them, never a fetch (as
    # /cheapest reads them): the red "Do not travel" pill beside a place any
    # of them rates Level 4 (review #27).
    adv, _fetched, _stale = _cheap_adv()
    key = (id(rp), id(ppp), id(idx), day, utc_day) + tuple(id(adv[s]) for s in _ADV_SRCS)
    hit = _strength_memo[0]
    if hit and hit[0] == key:
        return hit[2]
    page = render_strength.dollar_strength(rp, ppp, idx, today=day, price_day=utc_day, adv=adv)
    out = {"bytes": _shell_page(page["title"], page["html"],
                                _list_head(render_strength.PATH, page["title"], page["desc"]),
                                credits=_STRENGTH_CREDITS),
           "degraded": page["degraded"]}
    _strength_memo[0] = (key, (rp, ppp, idx, tuple(adv[s] for s in _ADV_SRCS)), out)
    return out


def _strength_lastmod(stamp):
    """The sitemap's date for /dollar-strength: the cached rates' own as-of
    date, floored at the content stamp (never today; nothing cached: the
    stamp)."""
    try:
        cfg = store.load_config()
        hit = _rates_cache.get((cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), "USD"))
    except Exception:
        hit = None
    return max(stamp, render_lists.lastmod_of(((hit[1] if hit else None) or {}).get("as_of")))


_privacy_memo = [None]
_methodology_memo = [None]


def _render_methodology_page():
    """/how-grades-work in the list pages' shell (fxtracker/render_methodology.py),
    its numbers read from the scoring code and the refresh intervals from this
    file's TTLs. Fixed per deploy, so built once per process."""
    if _methodology_memo[0] is None:
        p = render_methodology.page({"rates": CACHE_TTL, "ppp": PPP_TTL, "adv": ADV_TTL,
                                     "flights": FLIGHTS_TTL})
        _methodology_memo[0] = _shell_page(p["title"], p["html"],
                                           _list_head(render_methodology.PATH, p["title"], p["desc"]),
                                           credits=False)
    return _methodology_memo[0]


def _render_privacy_page():
    """/privacy in the list pages' shell (fxtracker/render_privacy.py). Its
    words are fixed per deploy, so it is built once per process."""
    if _privacy_memo[0] is None:
        p = render_privacy.privacy()
        _privacy_memo[0] = _shell_page(p["title"], p["html"], _list_head("/privacy", p["title"], p["desc"]),
                                       credits=False)
    return _privacy_memo[0]


# ---- /cheapest and /cheapest/<month> --------------------------------------------
# The cheapest countries to visit each month from the US (fxtracker/
# render_cheapest.py): Top Picks' own scoring for a US traveller, run on what
# the server already caches — the three advisory lists at any age (a refresh
# is started in the background, never awaited), the USD rates rows and PPP
# table (_fx_inputs), climate, the guide-facts snapshot, the US fares and
# their flight-value curves (flightvalue.build reads the curve cache alone).
# All 13 pages render together on a miss; every other request is a lookup.
_CHEAP_CREDITS = ('Data: <a href="https://data.worldbank.org" rel="noopener" target="_blank">World Bank</a> '
                  '(PPP; Taiwan: IMF, Penn World Table) &amp; '
                  '<a href="https://fxratesapi.com" rel="noopener" target="_blank">fxratesapi.com</a> '
                  "&middot; Advisories: " + _ADV_LINKS + " &middot; Climate: "
                  '<a href="https://open-meteo.com" rel="noopener" target="_blank">Open-Meteo</a> &middot; '
                  'Flights: <a href="https://www.aviasales.com" rel="noopener" target="_blank">Aviasales</a> '
                  "(cached fares) &middot; ")
_cheap_memo = [None]   # (key, inputs kept alive, fv, {path: {bytes, degraded}}), swapped whole


def _cheap_adv():
    """The three lists as the cache holds them (None: not in hand), their
    fetch times, and {source: seconds} for a list past its TTL whose refresh
    is failing (_cached's stale-on-error copy) — never a fetch on this path."""
    _warm_adv_lists()
    now = time.time()
    payloads, fetched, stale = {}, {}, {}
    for src in _ADV_SRCS:
        hit = _adv_cache.get(src)
        payloads[src] = hit[1] if hit else None
        if hit:
            fetched[src] = hit[0]
            if now - hit[0] >= ADV_TTL and (src in _adv_refresh_failing
                                            or ("advisories", src) in _upstream_fail):
                stale[src] = int(now - hit[0])
    return payloads, fetched, stale


def _cheap_fares():
    """(fares payload, flight-value build, state) for the default origin from
    the caches alone. "off" with no fare source (local dev: dashes, not a
    degradation); "cold" until the fares are cached and the origin's first
    warm pass has run (the curves are still filling, grades may move)."""
    if not flights.is_configured():
        return None, None, "off"
    hit = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
    fares = hit[1] if hit else None
    fv = _fv_build(fares) if fares else None
    warm = fares is not None and flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN)
    return fares, fv, "warm" if warm else "cold"


def _cheap_page(path):
    """{bytes, degraded, available} for one of render_cheapest.PATHS, memoized on the
    identity of the inputs (a refreshed list, rates entry, PPP table,
    snapshot or fares payload is a new object), the UTC day (the months'
    years, the curves' window), the fares' state, a failing list's age to
    the hour, and the flight-value curves by value (they have no identity:
    the curve cache fills and refreshes in place)."""
    payloads, fetched, stale = _cheap_adv()
    rp, ppp = _fx_inputs()
    fares, fv, state = _cheap_fares()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    docs = (payloads["us"], payloads["ca"], payloads["de"], rp, ppp, render_lists.climate(),
            guide_facts.get_doc(), fares, _pl_history())
    key = tuple(id(x) for x in docs) + (today, state) + tuple(stale.get(s, 0) // 3600 for s in _ADV_SRCS)
    hit = _cheap_memo[0]
    if hit and hit[0] == key and hit[2] == fv:
        return hit[3][path]
    pages = render_cheapest.pages(*docs[:7], flights=fares, fv=fv, fares_state=state, fetched=fetched,
                                  stale=stale, today=today, pl_alt=(docs[8] or {}).get("alt"))
    out = {p: {"bytes": _shell_page(pg["title"], pg["html"], _list_head(p, pg["title"], pg["desc"]),
                                    credits=_CHEAP_CREDITS),
               "degraded": pg["degraded"], "available": pg["available"]} for p, pg in pages.items()}
    _cheap_memo[0] = (key, docs, fv, out)
    return out[path]


_NOINDEX = '<meta name="robots" content="noindex">'


# The shell pages a 404 may point to, by the footer's own names. Any other
# lowercase page (_LOWER_PATHS, the months included) is named from its path.
_PAGE_LABELS = {"/safe-and-cheap": "Safest cheap countries", "/do-not-travel": "Do Not Travel list",
                "/cheapest": "Cheapest by month", "/dollar-strength": "Dollar strength",
                "/data": "The price-level dataset", "/privacy": "Privacy",
                render_methodology.PATH: "How grades work"}
# Past this many characters a 404 path is nobody's typo: no suggestion, so a
# long junk URL can't buy difflib time.
_SUGGEST_MAX = 80
_guide_candidates = None


def _guide_suggest_map():
    """{spelling: slug} for every guide: its slug, its name slugified and the
    aliases _guide_redirect already 301s — what a typo is measured against.
    Built once: the slug list only changes on deploy."""
    global _guide_candidates
    if _guide_candidates is None:
        iso_to_slug = {iso: sl for sl, iso in render_guide.all_slugs()}
        out = {}
        for slug, iso in render_guide.all_slugs():
            out[slug] = slug
            out.setdefault(_slugish(render_guide.name_for_iso(iso) or slug), slug)
        for alias, iso in GUIDE_ALIASES.items():
            if iso in iso_to_slug:
                out.setdefault(alias, iso_to_slug[iso])
        _guide_candidates = out
    return _guide_candidates


def _did_you_mean(path):
    """(href, label) for a 404 path one typo away from a page, else None:
    /guide/columbia -> Colombia, /cheapest/febuary -> February,
    /safe-and-cheep -> Safest cheap countries. difflib's ratio, so a
    near-miss of a few letters, never a guess from a word or two."""
    if not path or len(path) > _SUGGEST_MAX:
        return None
    low = path.lower().rstrip("/")
    if low.startswith("/guide/"):
        word = _slugish(low[len("/guide/"):])
        cands = _guide_suggest_map()
        hit = difflib.get_close_matches(word, list(cands), n=1, cutoff=0.75) if word else []
        if not hit:
            return None
        slug = cands[hit[0]]
        iso = render_guide.iso_for_slug(slug)
        return "/guide/" + slug, render_guide.name_for_iso(iso) or slug
    if low.startswith(render_cheapest.HUB + "/"):
        word = low[len(render_cheapest.HUB) + 1:]
        hit = difflib.get_close_matches(word, list(render_cheapest.SLUGS), n=1, cutoff=0.7)
        if not hit:
            return None
        m = render_cheapest.SLUGS.index(hit[0]) + 1
        return render_cheapest.path_for(m), "Cheapest countries in " + render_guide.MON_FULL[m - 1]
    pages = sorted(_LOWER_PATHS)
    hit = difflib.get_close_matches(low, pages, n=1, cutoff=0.8)
    if not hit:
        return None
    m = render_cheapest.month_of(hit[0])
    label = _PAGE_LABELS.get(hit[0]) or ("Cheapest countries in " + render_guide.MON_FULL[m - 1] if m
                                         else hit[0].strip("/").replace("-", " ").capitalize())
    return hit[0], label


def _render_404_page(message, suggest=None):
    """Human-facing 404: a way back in plus the guide index, open (it is
    what the reader came for), not bare JSON. `suggest`: _did_you_mean's
    (href, label), said first."""
    dym = ('<p class="didyoumean">Did you mean <a href="%s"><strong>%s</strong></a>?</p>'
           % (html.escape(suggest[0], quote=True), html.escape(suggest[1]))) if suggest else ""
    body = (
        '<div class="ssrguide"><h1>%s</h1>%s'
        '<p><a href="/"><strong>Back to WanderGrade →</strong></a></p></div>'
        '<details class="guideindex" open><summary>Browse all %d country guides</summary>'
        '<nav class="guideindex-links">%s</nav></details>'
        % (html.escape(message), dym, _guide_count(), _guide_links()))
    # No data on this page, so no data credits in its footer.
    return _shell_page("Not found | WanderGrade", body, _NOINDEX, credits=False)


# The 404 page's bytes and gzip, by message and suggestion: a handful of
# pages (one per suggestion at most) that never change while the process
# runs, made once each. A guide miss is answered without a page slot
# (_guide_miss), so its cost is outside the slots' bound.
_nf_memo = {}
_NF_MEMO_MAX = 256
_nf_lock = threading.Lock()
# At most one guide "Did you mean" search (difflib over every guide name)
# per SUGGEST_EVERY seconds for a 404 answered without a slot (_suggest_ok).
# Wall-clock seconds, so on a
# starved CPU (Render's free tier; stall_check --on-ms 2 runs the process 2%
# of the time) a shorter gap is a bigger share: 0.05 s let a burst that took
# 3-4 s to drain run ~70 searches, about what its other 130 misses cost. Once
# a second it's a few. _nf_suggest_at: when the last one started
# (time.monotonic()).
SUGGEST_EVERY = 1.0
_nf_suggest_at = [float("-inf")]


def _not_found_bytes(message, suggest, gz):
    """(raw, gzip or None) of _render_404_page(message, suggest); gzip only
    when `gz` (the client takes it)."""
    key = (message, suggest)
    hit = _nf_memo.get(key)   # one dict read, atomic: no lock for the usual case
    if hit is None:
        hit = [_render_404_page(message, suggest), None]
        with _nf_lock:
            if len(_nf_memo) >= _NF_MEMO_MAX:
                _nf_memo.clear()
            hit = _nf_memo.setdefault(key, hit)
    if gz and hit[1] is None:
        hit[1] = gzip.compress(hit[0], GZIP_LEVEL)
    return hit[0], (hit[1] if gz else None)


def _suggest_ok(path):
    """True when the 404 for `path` may run its "Did you mean" search
    (difflib, _did_you_mean). Always with slots off (tests, tools) or when
    this request holds a slot: the slots bound those. Always for a path
    outside /guide/ (any case, as _did_you_mean reads it): its search is over
    a short list (the list pages, /cheapest/<month>: ~0.01-0.04 ms, less than
    a 503), those 404s never took a slot, and they search as they always
    did, so a scanner's /wp-login.php spends no turn and a reader's
    /safe-and-cheep keeps its suggestion during a crawl. A /guide/ 404
    answered without a slot (a guide miss, _guide_miss) searches every guide
    name (~0.2-0.35 ms, most of a miss's cost) only while a slot is free and
    at most once per SUGGEST_EVERY across all of them: misses take no slot,
    so in a burst made of nothing but misses the slots look free. 150 typo URLs at once
    (stall_check --on-ms 2) each ran the search and held /healthz up to
    5.8 s, where shedding most of them 503 had held it 0.7-2.7 s; paced at
    0.05 s, 36 searches ran while the burst drained (worst probe 4.0 s);
    once a second, 3, and over six runs beside the shedding code the worst
    probe was 1.2-2.4 s against its 1.5-2.8 s, at the same CPU. A lone typo
    keeps its suggestion."""
    slots = _page_slots
    if slots is None or getattr(_slot_held, "slots", None) is not None:
        return True
    if not path.lower().startswith("/guide/"):
        return True
    if slots._value == 0:
        return False
    now = time.monotonic()
    if now - _nf_suggest_at[0] < SUGGEST_EVERY:   # the burst's usual answer, without the lock
        return False
    with _nf_lock:
        if now - _nf_suggest_at[0] < SUGGEST_EVERY:
            return False
        _nf_suggest_at[0] = now
    return True


def _render_verify_page(token):
    """The page the emailed link opens. It spends nothing: mail scanners and
    link previewers (Safe Links, Proofpoint, chat unfurlers) GET every link
    before the human does, and a GET that redeemed the single-use token left
    the real click with "link expired". Only the button's same-origin POST
    signs in."""
    body = (
        '<div class="ssrguide"><h1>Finish signing in</h1>'
        '<form class="subform" method="post" action="/auth/verify">'
        '<input type="hidden" name="t" value="%s">'
        '<button type="submit" autofocus>Sign in →</button></form></div>'
        % html.escape(token, quote=True))
    # No analytics beacon: it would report this URL, live token and all.
    return _shell_page("Sign in | WanderGrade", body, _NOINDEX, analytics=False)


def _fare_strip_hint(iso):
    """Whether this guide's fares-by-month strip will draw for the site's
    default origin, from the caches alone (never an upstream call): the
    country's row in the cached fares and its routes' cached curves, with the
    3 months of the next 12 renderGuideFares needs. The page holds the strip's
    167px only then (data-fm, styles.css): held for every guide, it was given
    back on the half of graded guides production has no curve for, and the
    prices and FX lines under it jumped up 154px (CLS 0.14 at 1280 on
    Slovakia for a reader scrolling during a slow load; 0.002 held only
    here). Not known (no token, fares not cached yet) is no hold."""
    try:
        if not flights.is_configured():
            return False
        hit = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
        rows = (hit[1].get("countries") or []) if hit else []
        row = next((r for r in rows if r.get("iso") == iso), None)
        if not row:
            return False
        m = flights.get_country_monthly(flightvalue.DEFAULT_ORIGIN, row, lookup=flights.monthly_cached)
        win = set(flightvalue.window_months())
        return bool(m) and sum(1 for k in (m.get("months") or {}) if k in win) >= 3
    except Exception:
        return False


# flightvalue.build for the default origin, as the server's pages read it:
# twice per guide (_guide_fv, _guide_lines) and per home render (_home_sizers,
# _home_picks), plus /cheapest's, at 1.3 ms a call: 2.6 ms of a 5.8 ms guide.
_fv_memo = [None]   # (fares, curve entries kept alive, local day, until, fv), swapped whole


def _fv_build(fares):
    """flightvalue.build(DEFAULT_ORIGIN, fares), memoized on everything it
    reads: the fares payload (by identity: a refresh is a new object), every
    cached route curve (flights.monthly_entries: entries are replaced on
    write, so an equal snapshot is an unchanged cache), the local date (its
    12-month window, the partial month, departures already flown) and the
    first moment a curve would read differently with no write
    (flights.monthly_read_until: due a refresh, or too old to serve). Equal
    to a fresh build, so every page stays byte-identical. Shared: read it,
    never modify it."""
    now = time.time()
    entries = flights.monthly_entries()
    day = datetime.now().date()          # what build's window_months() reads
    memo = _fv_memo[0]
    if memo and memo[0] is fares and memo[2] == day and now < memo[3] and memo[1] == entries:
        return memo[4]
    until = flights.monthly_read_until(entries, now)
    fv = flightvalue.build(flightvalue.DEFAULT_ORIGIN, fares)
    _fv_memo[0] = (fares, entries, day, until, fv)
    return fv


def _guide_fv(iso):
    """(flight-value build, date of its fares) for the default origin from the
    caches alone, for a guide whose month table carries a fare column; (None,
    None) for any other guide, with no fare source, or before the fares are
    cached. The page stays no-store until the origin's first warm pass has
    run (_guide_cache), so a column a cold render leaves out comes later."""
    if not render_guide.month_table_on(iso) or not flights.is_configured():
        return None, None
    hit = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
    if not hit or not hit[1]:
        return None, None
    try:
        return (_fv_build(hit[1]), datetime(*time.gmtime(hit[0])[:3]).date())
    except Exception as e:   # the fare column only: never the page
        print("[month-table] %s %s" % (iso, e), file=sys.stderr, flush=True)
        return None, None


def _fare_col_hints(iso):
    """The fare column's FX line for a reader at home in the US (the
    default), as a data- mark styles.css reads to hold its room or not
    (data-fx): "0" when the country has no currency the FX feed charts —
    none at all, or a trend shorter than the 6 months renderGuideFx needs,
    by the server's own cached trends — and "home" when it uses the dollar
    (no FX story for a dollar reader). Held anyway, it was given back:
    Puerto Rico's column fell from 250px to 18 at 768 (CLS 0.12 for a reader
    scrolling during a slow load). The local-prices line (data-cost) left
    the column for a place under the grades (review #11, _guide_cost)."""
    out = ""
    home = guide_sizers.GUIDE_PARENT.get(iso, iso)
    cur = picks.CUR_BY_ISO.get(home)
    hit = rates._trend_cache.get("USD")
    trend = hit[1] if hit else None
    if not cur or (trend is not None and len((trend.get(cur) or {}).get("months") or []) < 6):
        out += ' data-fx="0"'
    elif cur == "USD":
        out += ' data-fx="home"'
    return out


def _guide_sizers(iso, level, no_bookings=False):
    """Invisible stand-ins for the guide blocks app.js fills (the visa line,
    the advisory, the AI buttons, the weather chart, the stays and the
    insurance line; fxtracker/guide_sizers.py),
    from the data files and what the caches hold right now — never an
    upstream call. Nothing for a block whose content isn't cached yet: it
    keeps its per-level height (styles.css). No stays where a government
    says not to travel at all (no_bookings, _guide_no_bookings). The
    attributes for #tab-guide go under "_ATTRS" (the per-source levels)."""
    out = {}
    attrs = ""
    try:
        out["GUIDE_VISA"] = guide_sizers.visa(iso)
        out["GUIDE_AI"] = guide_sizers.ai(iso, render_guide.name_in_text(iso))
        ch = guide_sizers.chart(iso, render_guide.name_in_text(iso),
                                (render_guide.activities(iso) or {}).get("hazards"))
        if ch:   # the frame instead of "Loading…" and its per-hazard-count hold
            out.update(GUIDE_CHART=ch, CHART_LOADING="")
        hit = _adv_cache.get("us")
        adv = hit[1] if hit else None
        items = {it.get("iso"): it for it in (adv or {}).get("items") or [] if it.get("iso")}
        # Only with Canada's notes in hand: without them the copy came out
        # short (745px total error on 10 guides vs 1,150 for the per-level
        # heights in styles.css), and the first render after every deploy is
        # the one the edge then serves for 5 minutes. A miss fetches the
        # notes in the background so the next render is exact.
        notes = watchouts.cached(iso)
        # Canada's and Germany's lists as the cache holds them: a reader who
        # follows one gets its advisory, its level (the safety notes fold at
        # 1-2) and its insurance line, and the US stand-in was the wrong
        # height for them (Lebanon to a German-source reader at 1280: the US
        # Level 4 block against Germany's "Some regions", the chart and fare
        # column 100px up when it filled). Each gets its own stand-in and its
        # level on #tab-guide (data-lvca, data-lvde); index.html's first
        # script picks the reader's before the first paint (data-gsrc).
        others = {}
        for src in ("ca", "de"):
            p = _adv_cached(src)
            if p:
                others[src] = (p, {it.get("iso"): it for it in p.get("items") or [] if it.get("iso")})
                attrs += ' data-lv%s="%d"' % (src, guide_sizers.level_of(iso, others[src][1]))
        if notes is not None:
            out["GUIDE_SAFETY"] = guide_sizers.safety(
                iso, items, (adv or {}).get("source_name"), notes, health.get_doc())
            for src, (p, its) in others.items():
                out["GUIDE_SAFETY"] += guide_sizers.safety(
                    iso, its, p.get("source_name"), notes, health.get_doc(), source=src)
        else:
            _warm_watchouts(iso)
        # No stays under "do not travel" — where any government says it
        # (no_bookings: Venezuela and Saudi Arabia are US Level 3), as app.js's
        # guideNoBookings has it for every reader, or the server's level and
        # the US list's say Level 4. The insurance line follows the reader's
        # own source: its stand-in is served when some reader gets one, and
        # styles.css drops it under the reader's Level 4 (data-level).
        lvl_now = int((items.get(iso) or {}).get("level") or 0)
        us4 = level == 4 or lvl_now == 4
        if not us4 and not no_bookings:
            out["GUIDE_STAY"] = guide_sizers.stay(iso)
        if not us4 or any(guide_sizers.level_of(iso, its) != 4 for _p, its in others.values()):
            out["GUIDE_INSURANCE"] = guide_sizers.insurance(iso)
    except Exception as e:   # a hint only: never the page
        print("[guide-sizers] %s: %s" % (iso, e), file=sys.stderr, flush=True)
    out["_ATTRS"] = attrs
    return out


def _home_sizers():
    """The homepage's served pick lists under the Safety and Flights maps
    (fxtracker/map_picks.py) with the words the lists will carry, from the
    caches alone — never an upstream call: the US advisory list, and the
    default origin's fares and curves once its warm pass has run (before
    that, build() is mostly `pending` and the list would be short). A cold
    cache keeps index.html's own spans. On a server with no Travelpayouts
    token the fares fetch answers "not configured": data-nofares tells
    styles.css to hold nothing for them (the list, the key, the table's two
    screens went when that answer landed — the table rode up 103px at 768,
    CLS 0.37 on a local checkout; production has the token)."""
    out = {}
    try:
        hit = _adv_cache.get("us")
        adv = hit[1] if hit else None
        if adv:
            out["ADV_PICKS"] = map_picks.advisory_row(adv, render_guide.name_for_iso)
        if not flights.is_configured():
            out["FLIGHTS_OFF"] = " data-nofares"
        elif adv and flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN):
            # The list leaves out Level 3-4 destinations by that same US list
            # (flightLows): without it in hand the row would name them too.
            hit = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
            fares = hit[1] if hit else None
            if fares and fares.get("countries"):
                fv = _fv_build(fares)
                levels = {it.get("iso"): it.get("level") for it in adv.get("items") or [] if it.get("iso")}
                out["FLIGHT_PICKS"] = map_picks.flights_row(fv, levels, render_guide.name_for_iso)
    except Exception as e:   # a hint only: never the page
        print("[home-sizers] %s" % e, file=sys.stderr, flush=True)
    return out


# Before first paint, on the homepage only: the served Top Picks (data-ssr: the
# six months they rank) stay for a reader they are for, and give way to
# index.html's skeleton — today's page, which app.js then fills — for a reader
# they aren't: a link that sets the view (any query but tab=value and the
# tracking ones), a saved home country, currency, Top N, safety floor, budget,
# interests, factors, priorities, advisory source, visited list or a ranking of
# the ★ want-to-go list (wg_showvisited "want"), or a local
# date whose six months differ from the server's (flexWindow; the server's
# date is UTC). app.js holdServedPicks keeps the served rows until its data is
# in. ES5, like index.html's other inline scripts.
_TOP_HOLD = (
    '<script>(function(){var h=document.getElementById("topCards"),w=h&&h.getAttribute("data-ssr");if(!w)return;'
    'var off=false,q=new URLSearchParams(location.search);'
    'q.forEach(function(x,k){if(!/^(utm_[a-z]+|gclid|fbclid|ref)$/.test(k)&&!(k==="tab"&&x==="value"))off=true;});'
    'try{var L=localStorage,v=function(k){return L.getItem(k)};'
    'if((v("fx_origin")||"US")!=="US"||(v("fx_homecur")||"USD")!=="USD"||(v("fx_pickcount")||"5")!=="5"'
    '||(v("fx_safefloor")||"b")!=="b"||v("wg_budget")||v("fx_factors2")||v("fx_priorities2")'
    '||(v("wg_advsrc")||"us")!=="us"||v("wg_showvisited")==="want"||JSON.parse(v("wg_interests")||"[]").length'
    '||JSON.parse(v("fx_visited")||"[]").length)off=true;}catch(e){}'
    'var d=new Date(),m=d.getMonth(),s=new Date(d.getFullYear(),m+1,0).getDate()-d.getDate()+1<10?m+1:m,x=[];'
    'for(var i=0;i<6;i++)x.push((s+i)%12+1);if(x.join()!==w)off=true;'
    'var t=h.getElementsByTagName("table"),n=document.getElementById("picksNote");'
    'if(off){h.removeAttribute("data-ssr");t[0].hidden=false;h.removeChild(t[1]);n.firstChild.hidden=false;'
    'while(n.childNodes.length>1)n.removeChild(n.lastChild);}'
    'else{h.removeChild(t[0]);n.removeChild(n.firstChild);}})();</script>')


# Before first paint, on a guide whose grades line and fares strip are served
# (#tab-guide data-gssr: the month they grade, then the server's month): they
# stay for a reader they are for and are emptied — today's page, which app.js
# then fills — for one they aren't: a link with any query but the tracking
# ones (?vmn= sets the month), a saved home country, currency, factors,
# priorities, advisory source or fare currency, or a local date whose month
# or six-month window differs from the server's (UTC). app.js holdServedGuide
# keeps them until its data is in. ES5, like index.html's other inline scripts.
_GUIDE_HOLD = (
    '<script>(function(){var g=document.getElementById("tab-guide"),w=g&&g.getAttribute("data-gssr");if(!w)return;'
    'var off=false,q=new URLSearchParams(location.search);'
    'q.forEach(function(x,k){if(!/^(utm_[a-z]+|gclid|fbclid|ref)$/.test(k))off=true;});'
    'try{var L=localStorage,v=function(k){return L.getItem(k)};'
    'if((v("fx_origin")||"US")!=="US"||(v("fx_homecur")||"USD")!=="USD"||v("fx_factors2")||v("fx_priorities2")'
    '||(v("wg_advsrc")||"us")!=="us"||(v("wg_flightcur")||"USD")!=="USD")off=true;}catch(e){}'
    'var d=new Date(),m=d.getMonth(),s=new Date(d.getFullYear(),m+1,0).getDate()-d.getDate()+1<10?m+1:m;'
    'if((s%12+1)+","+(m+1)!==w)off=true;'
    'if(off){g.removeAttribute("data-gssr");document.getElementById("guideGrades").innerHTML="";'
    'var f=document.getElementById("guideFares");f.hidden=true;f.innerHTML="";}})();</script>')


def _guide_lines(iso):
    """A guide's grades line and fares strip for a first visit
    (fxtracker/guide_lines.py), as tokens, from the caches alone — the
    payloads the browser fetches: the US advisory list, the USD rates, the
    PPP table, and the default origin's fares, curves and this country's
    curve once its warm pass has run. Anything missing: {} (empty, as
    before)."""
    hit = _adv_cache.get("us")
    adv = hit[1] if hit else None
    rp, ppp = _fx_inputs()
    if not (adv and rp and ppp):
        return {}
    fares = fv = curve = None
    if flights.is_configured():
        if not flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN):
            return {}
        fh = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
        fares = fh[1] if fh else None
        if not fares:
            return {}
        fv = _fv_build(fares)
        row = next((r for r in fares.get("countries") or [] if r.get("iso") == iso), None)
        curve = flights.get_country_monthly(flightvalue.DEFAULT_ORIGIN, row, lookup=flights.monthly_cached) \
            if row else None
    d = render_guide._load()
    today = datetime(*time.gmtime()[:3]).date()
    inputs = {"rates": rp, "ppp": ppp, "climate": d["clim"], "activities": d["acts"],
              "advisories": adv, "flights": fares, "fv": fv}
    # The strip's search link where app.js guideNoBookings is false: no
    # government's own list says Level 4 (nor the US list's gap-filled
    # level), and every list is in (one still out is "not known": no link,
    # as the browser draws it until it is).
    dnt = _adv_dnt()
    book = not dnt["unknown"] and not _guide_flagged(iso, dnt) and guide_lines.adv_level(iso, adv) != 4
    strip = guide_lines.fares(iso, curve, fv, today, render_guide.name_for_iso, book) if curve else ""
    return {"_ATTRS": ' data-gssr="%d,%d"' % (guide_lines.guide_month(today), today.month),
            "GUIDE_GRADES": guide_lines.grades(iso, inputs, today),
            "FARES_HIDDEN": "" if strip else " hidden", "GUIDE_FARES": strip,
            "GUIDE_HOLD": "\n          " + _GUIDE_HOLD}


# Before first paint, on a guide whose 💰 line is served (_guide_cost): it is
# a US reader's (the US's own guide its home line), so for a reader from
# elsewhere (a saved home country, or a shared link's ?vo= / ?fo=) it keeps its
# room invisibly (.pend) until renderGuideCost draws theirs: another band word
# and country, or their home line on their own country's guide. A first visit
# keeps it as it is (the reader is the US until /api/geo says otherwise, after
# paint, and their line then takes the same room). The room is the same
# whoever's line fills it (styles.css .guidecost: one line, two on a phone).
# ES5, like index.html's other inline scripts.
_COST_HOLD = (
    '<script>(function(){var c=document.getElementById("guideCost");if(!c)return;'
    'try{var q=new URLSearchParams(location.search),v=q.get("vo")||q.get("fo"),'
    'o=/^[A-Z]{2}$/.test(v||"")?v:(localStorage.getItem("fx_origin")||"US");'
    'if(o!=="US")c.className+=" pend";}catch(e){}})();</script>')


def _guide_cost(iso, snapshot, snapshot_l4):
    """A guide's 💰 local-prices line under its grades (review #11), as
    tokens: guide_lines.cost from the rates, PPP table and US advisory list
    the server caches (never fetched here), else the dated snapshot's words,
    with the pre-paint script. Hidden and empty where there is nothing to
    say (no figure), as index.html had it. The US's own guide carries its
    home line (guide_lines.HOME_LINE, the served reader being the US), which
    needs no data, so its room is never served empty."""
    home = guide_sizers.GUIDE_PARENT.get(iso, iso)
    if home == "US":
        return {"COST_ATTRS": ' data-iso="%s"' % iso, "GUIDE_COST": guide_lines.cost(iso, None, None),
                "COST_HOLD": "\n          " + _COST_HOLD}
    # The PPP table as /ppp.json serves it right now: the committed file until
    # the World Bank refresh has run (_ppp_data), not None as _fx_inputs has
    # it until then (up to ~40 s after boot). Waiting served the dated
    # snapshot line in that window, which app.js swapped for the live one
    # (another figure, and a line shorter on many guides on a phone).
    rp = _fx_inputs()[0]
    ppp = _ppp_data() if rp else None
    hit = _adv_cache.get("us")
    line = guide_lines.cost(iso, rp if ppp else None, ppp if rp else None,
                            hit[1] if hit else None, snapshot, snapshot_l4)
    if not line:
        return {}
    return {"COST_ATTRS": ' data-iso="%s"' % iso, "GUIDE_COST": line, "COST_HOLD": "\n          " + _COST_HOLD}


def _warm_popularity():
    """Fetch the tourism figures /api/popularity serves in the background
    (once at a time), so the homepage's Top Picks can be served next render."""
    if _pop_cache.get("busy"):
        return
    _pop_cache["busy"] = True

    def run():
        try:
            _pop_cache.update(at=time.time(), data={"arrivals": popularity.get_arrivals()})
        except Exception as e:
            print("[home-picks] popularity: %s" % e, file=sys.stderr, flush=True)
        finally:
            _pop_cache["busy"] = False

    threading.Thread(target=run, daemon=True).start()


def _home_picks():
    """The homepage's Top Picks table and note for the view a first visit
    opens on (fxtracker/home_picks.py), as tokens, from the caches alone —
    the same payloads the browser fetches: the US advisory list, the USD
    rates, the PPP table, the popularity figures, and the default origin's
    fares and curves once its warm pass has run (before that the browser's
    own rows would still move). Anything missing: {} (index.html's skeleton,
    as before), and the popularity figures are fetched for next time."""
    hit = _adv_cache.get("us")
    adv = hit[1] if hit else None
    rp, ppp = _fx_inputs()
    pop = (_pop_cache.get("data") or {}).get("arrivals")
    if not pop:
        _warm_popularity()
    if not (adv and rp and ppp and pop):
        return {}
    fares = fv = None
    if flights.is_configured():
        if not flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN):
            return {}
        fh = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
        fares = fh[1] if fh else None
        if not fares:
            return {}
        fv = _fv_build(fares)
    d = render_guide._load()
    r = home_picks.build({"rates": rp, "ppp": ppp, "climate": d["clim"], "activities": d["acts"],
                          "advisories": adv, "flights": fares, "fv": fv,
                          "popular": home_picks.popular_set(pop)},
                         d["iso2slug"], datetime(*time.gmtime()[:3]).date())
    if not r:
        return {}
    return {"TOP_SSR": ' data-ssr="%s"' % r["window"], "TOP_SKEL_HIDDEN": " hidden",
            "TOP_PICKS": "\n        " + r["table"], "TOP_HOLD": "\n        " + _TOP_HOLD,
            "NOTE_SKEL_HIDDEN": " hidden", "PICKS_NOTE": r["note"]}


# Per-country share cards: public/og/<slug>.jpg, 1200x630, rendered offline by
# scripts/dev/og_cards.mjs (the server can't render images), which records the
# facts each card shows in public/og/cards.json. A guide's og:image and
# twitter:image are its card while the file exists and those facts are still
# the data's (name, best months, curated or not); otherwise /og.png, as every
# page had before. So a climate.json rebuild that moves a country's best
# months falls back to the site card until the cards are re-rendered
# (scripts/test_og_cards.py names the stale ones). Read once per process.
_og_cards_memo = [None]


def _og_cards():
    """{iso: card URL} for every card that exists and matches the data."""
    if _og_cards_memo[0] is None:
        out = {}
        try:
            with open(os.path.join(PUBLIC, "og", "cards.json"), encoding="utf-8") as f:
                cards = json.load(f)
            d = render_guide._load()
            for slug, iso in d["slugs"].items():
                c, clim = cards.get(slug), d["clim"].get(iso) or {}
                want = {"iso": iso, "name": d["names"].get(iso) or slug,
                        "best": [m for m in clim.get("best") or [] if 1 <= m <= 12],
                        "curated": bool(clim.get("curated"))}
                if c == want and os.path.isfile(os.path.join(PUBLIC, "og", slug + ".jpg")):
                    out[iso] = "%s/og/%s.jpg" % (_SITE, slug)
        except (OSError, ValueError) as e:
            print("[og-cards] none: %s" % e, file=sys.stderr, flush=True)
        _og_cards_memo[0] = out
    return _og_cards_memo[0]


def _og_image(iso):
    """The guide's own share card URL, or None (the page keeps /og.png)."""
    return _og_cards().get(iso)


def _render_index(gc_iso=None):
    """Fill index.html's tokens. gc_iso=None -> homepage defaults; otherwise a
    country page with server-rendered <title>/meta/canonical and body."""
    vals = dict(_HTML_DEFAULTS)
    vals["GUIDE_LINKS"] = _guide_links()
    vals["GUIDE_COUNT"] = str(_guide_count())
    if not gc_iso:
        vals.update(_home_sizers())
        try:
            vals.update(_home_picks())
        except Exception as e:   # the skeleton, as before: never the page
            print("[home-picks] %s" % e, file=sys.stderr, flush=True)
        vals["JSONLD"] = _IMPACT_VERIFY + vals["JSONLD"]
    if gc_iso:
        no_book = _guide_no_bookings(gc_iso)
        fv, fares_at = _guide_fv(gc_iso)
        # Canada's notes as cached: a marked place's ⓘ drops a quote they
        # show gone or reworded (fxtracker/avoid_marks.py).
        r = render_guide.render(gc_iso, fv, fares_at, no_book, watchouts.cached(gc_iso))
        vals.update(
            TITLE=html.escape(r["title"]),
            DESC=html.escape(r["desc"], quote=True),
            OGTITLE=html.escape(r["og_title"], quote=True),
            URL=html.escape(r["url"], quote=True),
            GUIDE_H1_HIDDEN="",
            GUIDE_H1=r["h1_html"],                    # already-safe HTML
            SSR_BODY=r["body"],                       # already-safe HTML
            GUIDE_MONTHS=("\n        " + r["months"]) if r["months"] else "",
            GC_JS="<script>window.__WGGC__=%s;</script>" % json.dumps(gc_iso),
            # No JSON-LD: the WebSite block is the homepage's (Google reads the
            # site name from there only), and the guides' FAQPage went with
            # its invisible questions (render_guide.render says why).
            JSONLD="",
            # Demoted so the country's own <h1> is the only one on the page.
            SITE_HEADING='<p class="sitetitle">Where Should I Travel to Next?</p>',
            # The guide is the page: shown and underlined without JS.
            HTML_TAB=' data-tab="guide"',
            VALUE_HIDDEN=" hidden",
            GUIDE_HIDDEN="",
            # render_guide's layout hints: styles.css holds the empty blocks
            # at the sizes for the guide's advisory level (data-level) and the
            # weather chart for its number of hazard lines (data-hz, 1 or 2+),
            # and no stays block where no stays come (data-nostay: Ethiopia,
            # whose places are all in zones Canada says to avoid — held, the
            # insurance line rose 135px at 1280 when it went — and every
            # country a government says not to travel to, whoever the reader
            # follows: _guide_no_bookings).
            GUIDE_DATA=(' data-level="%d"' % r["adv"] if r.get("adv") in (1, 2, 3, 4) else "")
            + (' data-hz="%d"' % min(r.get("hz") or 0, 2) if r.get("hz") else "")
            + ("" if not no_book and guide_sizers.stay(gc_iso) else ' data-nostay="1"')
            + (' data-fm="1"' if _fare_strip_hint(gc_iso) else "")
            + _fare_col_hints(gc_iso),
            VALUE_ACTIVE="",
            GUIDE_ACTIVE=' class="active"',
            # No first-paint stand-ins for tabs a guide never shows first —
            # and the guides' HTML stays byte-identical to before them.
            ACTIONS_HIDDEN=" hidden",
            VISITED_STATS="", VISITED_PICK="", VISITED_HOLD="",
        )
        sz = _guide_sizers(gc_iso, r.get("adv"), no_book)
        vals["GUIDE_DATA"] += sz.pop("_ATTRS", "")
        vals.update(sz)
        try:
            gl = _guide_lines(gc_iso)
        except Exception as e:   # empty, as before: never the page
            print("[guide-lines] %s %s" % (gc_iso, e), file=sys.stderr, flush=True)
            gl = {}
        vals["GUIDE_DATA"] += gl.pop("_ATTRS", "")
        vals.update(gl)
        try:
            vals.update(_guide_cost(gc_iso, r.get("cost") or "", r.get("adv") == 4))
        except Exception as e:   # hidden, as before: never the page
            print("[guide-cost] %s %s" % (gc_iso, e), file=sys.stderr, flush=True)
        if r.get("ogimage"):                          # the site's card (render_guide)
            vals["OGIMAGE"] = html.escape(r["ogimage"], quote=True)
        card = _og_image(gc_iso)
        if card:                                      # the country's own card
            vals["OGIMAGE"] = card
    out = _guide_template() if gc_iso else _index_template()
    for k, v in vals.items():
        out = out.replace("{{%s}}" % k, v)
    return out.encode("utf-8")


# ---- the page memo: rendered guide and home bytes ------------------------------
# A guide or the homepage was rendered from scratch, and gzipped, on every
# request, though between two requests nothing it reads usually changes: a
# crawler's HEAD and then GET of one URL, each Cloudflare POP fetching the same
# page for its own 5-minute copy, a guide asked for twice. A page is kept
# here, raw and (once a client asks for it) gzipped, only when it goes out
# public, max-age=300 (PAGE_MEMO_CACHE), and handed out again only while
#   - every input it was rendered from is the very object it was (_page_inputs:
#     the advisory lists, rates, PPP, fares, flight values, FX trend, health
#     and guide-facts documents, Canada's notes or the popularity figures; each
#     cache replaces what it holds, never edits it), and the values it read
#     (fares configured, warm pass done, failed lists, the UTC and local day)
#     are equal: any change re-renders at once;
#   - its Cache-Control decision is still PAGE_MEMO_CACHE: a page that would go
#     out no-store now is rendered fresh, as before;
#   - it is younger than PAGE_MEMO_TTL, so anything not listed above moves
#     within the 5 minutes an edge copy of it lasts anyway.
# A query string never changed a guide or the homepage (_render_index takes
# only the country), so /guide/japan?x=1 and /guide/japan share an entry; HEAD
# sends the same status and headers from it. At most PAGE_MEMO_MAX pages, the
# least recently used dropped first. Off (None) unless server.main() turns
# it on: tests and tools that edit a cache in place render every time.
PAGE_MEMO_TTL = 300
PAGE_MEMO_MAX = 64          # ~100 KB raw + ~28 KB gzipped each: ~8 MB at most
PAGE_MEMO_CACHE = "public, max-age=300"
_page_memo = None           # OrderedDict: iso or "" -> (born, objs, vals, raw, gz or None)
_page_memo_lock = threading.Lock()
# "[page-memo]" when reading a page's inputs raised (the page is rendered
# without the memo): at most one line per PAGE_MEMO_LOG_EVERY seconds, the
# ones held back counted, since a bad input fails every guide alike.
PAGE_MEMO_LOG_EVERY = 60
_page_memo_err = {"at": 0.0, "held": 0}


def _page_inputs_failed(iso, e):
    now = time.time()
    with _page_memo_lock:
        line = now - _page_memo_err["at"] >= PAGE_MEMO_LOG_EVERY
        held = _page_memo_err["held"]
        if line:
            _page_memo_err.update(at=now, held=0)
        else:
            _page_memo_err["held"] += 1
    if line:
        print("[page-memo] %s: reading its inputs raised %s: %s; rendered without the memo%s"
              % (iso or "home", type(e).__name__, e, ", %d more since" % held if held else ""),
              file=sys.stderr, flush=True)


def _page_inputs(iso):
    """(objects, values) a guide (iso) or the homepage (None) is rendered
    from: objects compared by identity, values by equality. Read through the
    accessors the render itself uses, side effects included (_fx_inputs'
    PPP refresh check, the background fetch of Canada's notes or of the
    popularity figures when missing), so a memo hit starts what a render
    would have."""
    configured = flights.is_configured()
    fh = _flights_cache.get(flightvalue.DEFAULT_ORIGIN)
    fv = _fv_build(fh[1]) if configured and fh and fh[1] else None
    rp, ppp = _fx_inputs()
    objs = tuple(_adv_cache.get(s) for s in _ADV_SRCS) + (
        rp, ppp, fh, fv, rates._trend_cache.get("USD"), health.get_doc(), guide_facts.get_doc())
    if iso:
        notes = watchouts.cache_entry(iso)
        if notes is None or notes[1].get("_failed"):
            _warm_watchouts(iso)       # as _guide_sizers does with no notes in hand
        objs += (notes,)
    else:
        pop = _pop_cache.get("data")
        if not (pop or {}).get("arrivals"):
            _warm_popularity()         # as _home_picks does
        objs += (pop,)
    vals = (configured, flightvalue.has_warmed(flightvalue.DEFAULT_ORIGIN), frozenset(_adv_failed),
            time.strftime("%Y-%m-%d", time.gmtime()), datetime.now().date())
    return objs, vals


def _page_bytes(iso, want_gz):
    """(raw, gzipped or None) for a guide (iso) or the homepage (None) that
    goes out as PAGE_MEMO_CACHE: from the memo when nothing it was rendered
    from has changed, else rendered (and kept). gzipped only when asked.

    Reading the inputs must never cost the page: they go through the very
    accessors the render calls, but the render catches what those raise
    block by block (a flight-value build that raises drops the fare column,
    a popularity thread that won't start leaves the skeleton), where an
    exception here would drop the connection on every public guide and the
    homepage until the bad input left its cache. So when they raise, the page
    is rendered as with the memo off, and not kept."""
    try:
        objs, vals = _page_inputs(iso)
    except Exception as e:
        _page_inputs_failed(iso, e)
        raw = _render_index(iso)
        return raw, (gzip.compress(raw, GZIP_LEVEL) if want_gz else None)
    key, now = iso or "", time.time()
    with _page_memo_lock:
        hit = _page_memo.get(key)
        if hit is not None:
            _page_memo.move_to_end(key)
    if hit is not None and now - hit[0] < PAGE_MEMO_TTL and hit[2] == vals \
            and len(hit[1]) == len(objs) and all(a is b for a, b in zip(hit[1], objs)):
        raw, gz = hit[3], hit[4]
        if want_gz and gz is None:
            gz = gzip.compress(raw, GZIP_LEVEL)
            with _page_memo_lock:
                if _page_memo.get(key) is hit:
                    _page_memo[key] = hit[:4] + (gz,)
        return raw, gz
    raw = _render_index(iso)
    gz = gzip.compress(raw, GZIP_LEVEL) if want_gz else None
    with _page_memo_lock:
        _page_memo[key] = (now, objs, vals, raw, gz)
        _page_memo.move_to_end(key)
        for k in [k for k, e in _page_memo.items() if now - e[0] >= PAGE_MEMO_TTL]:
            del _page_memo[k]
        while len(_page_memo) > PAGE_MEMO_MAX:
            _page_memo.popitem(last=False)
    return raw, gz


# ---- upstream-backed caches ----------------------------------------------------
# A refresh that fails must not turn a copy we already hold into an error: the
# US advisory feed in particular is flaky, and one failed 6-hourly refresh made
# /api/advisories 500 (blanking Top Picks) until the feed came back, each
# request waiting on the upstream timeout first. So an expired entry is served
# marked stale while the upstream is down, with the upstream retried at most
# every STALE_RETRY seconds. A failure with nothing to fall back on is
# remembered only FAIL_RETRY seconds — never pinned for a whole TTL, which is
# what made one fxratesapi blip blank the Data-tab chart for 10 minutes.
STALE_RETRY = 600
FAIL_RETRY = 30
_upstream_fail = {}   # (cache name, key) -> (retry_after_ts, error message)


def _stale(hit, now):
    return dict(hit[1], stale=True, stale_age=int(now - hit[0]))


def _cached(name, cache, key, ttl, compute, stale_max=None):
    now = time.time()
    hit = cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    usable = hit if hit and (stale_max is None or now - hit[0] < stale_max) else None
    fk = (name, key)
    fail = _upstream_fail.get(fk)
    if fail and now < fail[0]:
        if usable:
            return _stale(usable, now)
        raise RuntimeError(fail[1])
    try:
        data = compute()
    except Exception as e:
        _upstream_fail[fk] = (now + (STALE_RETRY if usable else FAIL_RETRY), str(e))
        # Keys are client-influenced (bases, origins): drop expired entries so
        # a stream of distinct failures can't grow this without bound.
        # Snapshot first: request threads and the boot-warm thread share it.
        for k, (until, _m) in list(_upstream_fail.items()):
            if until < now:
                _upstream_fail.pop(k, None)
        if usable:
            print("[%s] refresh failed (%s); serving the copy from %ds ago"
                  % (name, e, now - usable[0]), flush=True)
            return _stale(usable, now)
        raise
    _upstream_fail.pop(fk, None)
    if stale_max is not None:     # prune what is too old to ever be served
        # Snapshot + pop: two threads can prune the same key at once (the
        # flight-value warm-up runs off-request), and a second `del` raised.
        for k, (at, _) in list(cache.items()):
            if now - at >= stale_max:
                cache.pop(k, None)
    cache[key] = (now, data)
    return data


_adv_failed = set()   # sources whose last fetch failed with no copy to serve (_dnt_failed)
# Sources whose last refresh failed while a copy was in hand, until one lands.
# Its own record, not _upstream_fail's: any _cached failure (rates, flights)
# prunes that table's expired entries, and a list whose backoff had run out
# then went out unmarked until the background retry failed again.
_adv_refresh_failing = set()

# A list past ADV_TTL is refreshed off the request path. Requests used to
# recompute it inline, each on its own: every 6 hours /api/advisories,
# /safe-and-cheap, /do-not-travel and the boot warm-up all fetched and parsed
# the same feeds at once, and on Render's 0.1 CPU the listen queue filled and
# its /healthz check timed out (2026-11-10, 2026-11-16). Now a request gets
# the copy in hand and one background refresh per list runs (_adv_refresh);
# only a list not in hand at all is computed while a request waits, and then
# by one caller at a time (_adv_compute_once).
_adv_flights = {}          # source -> {"done": Event, "result" | "error"}: the computation in flight
_adv_flight_lock = threading.Lock()
# Seconds to wait on another caller's computation before computing as before.
# Above a computation's worst case on a failing upstream, so a slow feed
# never undoes the single flight: a list fetches its own feed and the two
# gap-fills one after another, and a feed that times out takes 3 tries of
# rates.TIMEOUT (20 s) plus 1.5 + 3 s of backoff, so 3 x 64.5 = 193.5 s.
ADV_FLIGHT_WAIT = 240


def _adv_compute_once(source):
    """The list for `source` through _cached (the copy while it is current,
    else a refresh, or the stale copy inside the failure backoff), computed
    by one caller at a time: a caller that finds a computation in flight
    waits for it and gets its result, or raises its error. A wait past
    ADV_FLIGHT_WAIT (a computation stuck on the network) goes to _cached
    itself, as every caller did before."""
    def compute():
        out = _cached("advisories", _adv_cache, source, ADV_TTL, lambda: _advisories_fresh(source))
        # _cached hands back the copy marked stale when the refresh failed
        # (or is inside its backoff), the new list when it landed.
        if out.get("stale") is True:
            _adv_refresh_failing.add(source)
        else:
            _adv_refresh_failing.discard(source)
        return out
    with _adv_flight_lock:
        flight = _adv_flights.get(source)
        lead = flight is None
        if lead:
            flight = _adv_flights[source] = {"done": threading.Event()}
    if lead:
        # Fetches: a list page gives its page slot back meanwhile, and its
        # followers get the outcome before it queues for the slot again (a
        # crawler's guides holding every slot delay the leader only, not a
        # slotless /api/advisories waiting on a list already in _adv_cache).
        with _no_slot():
            try:
                flight["result"] = compute()
            except BaseException as e:
                flight["error"] = e
                raise
            finally:
                with _adv_flight_lock:
                    _adv_flights.pop(source, None)
                flight["done"].set()
        return flight["result"]
    if not _idle_wait(flight["done"], ADV_FLIGHT_WAIT):
        with _no_slot():
            return compute()
    if "error" in flight:
        raise flight["error"]
    return flight["result"]


def _adv_read(source):
    """The list for `source` on a request's path: the copy in hand at any age,
    never a computation while there is one. Past ADV_TTL it goes out as it is
    and one background refresh starts, unless the last refresh failed
    (_adv_refresh_failing): then, as before, it goes out marked stale
    (_stale), and inside the failure backoff no refresh starts. Not in hand
    at all: _adv_compute_once."""
    hit = _adv_cache.get(source)
    if hit is None:
        return _adv_compute_once(source)
    now = time.time()
    if now - hit[0] < ADV_TTL:
        return hit[1]
    fail = _upstream_fail.get(("advisories", source))
    if not (fail and now < fail[0]):
        _adv_refresh(source)
    return _stale(hit, now) if fail or source in _adv_refresh_failing else hit[1]


def _advisories_payload(source, background=False):
    """The cached list /api/advisories serves for `source` (stale-on-error,
    see _cached). A request's path reads the copy in hand (_adv_read);
    background=True (the refresh thread, the guide-facts refresher) waits
    for a current list instead (_adv_compute_once)."""
    # No stale_max: a days-old advisory list beats a 500 that blanks Top
    # Picks, and the payload says it is stale.
    try:
        out = _adv_compute_once(source) if background else _adv_read(source)
    except Exception:
        _adv_failed.add(source)
        raise
    _adv_failed.discard(source)
    return out


# One "[refresh]" line when a heavy upstream refresh ends (the advisory lists,
# the rates; rates.get_history writes its own): what, how long, how much of
# this thread's CPU, so a slow health check can be laid beside what was
# running. At most one per name every REFRESH_LOG_EVERY seconds (a failing
# upstream is retried every FAIL_RETRY); the ones held back are counted.
REFRESH_LOG_EVERY = 60
_refresh_logged = {}   # name -> [last line's time, lines held back since]
_refresh_log_lock = threading.Lock()


def _timed_refresh(name, compute):
    """compute(), with its [refresh] line once it returns or raises."""
    t0, c0 = time.time(), time.thread_time()
    err = None
    try:
        return compute()
    except Exception as e:
        err = e
        raise
    finally:
        now = time.time()
        with _refresh_log_lock:
            rec = _refresh_logged.setdefault(name, [0.0, 0])
            line = now - rec[0] >= REFRESH_LOG_EVERY
            held, rec[1] = (rec[1], 0) if line else (0, rec[1] + 1)
            if line:
                rec[0] = now
        if line:
            print("[refresh] %s %s in %.2fs (cpu %d ms)%s" % (
                name, "failed: %s" % err if err is not None else "done", now - t0,
                (time.thread_time() - c0) * 1000, ", %d more since" % held if held else ""), flush=True)


def _advisories_fresh(source):
    # Each freshly fetched list goes past WanderGrade's own record of the
    # levels it has seen (fxtracker/advhistory.py), which stamps the items
    # whose level it saw change. Only here, where the list is computed — never
    # per request — and it can't fail the list: a storage error just leaves
    # the items unstamped.
    return _timed_refresh("advisories " + source, lambda: _stamp_fetched(advhistory.record_and_annotate(
        source, advisories.get_advisories(source))))


def _stamp_fetched(payload):
    """The list with `fetched`, the UTC day it was read, for the guide
    badge's tip ("Advisory dated 7 Jul 2026 · fetched 23 Nov 2026"). A stale
    copy served on a failed refresh keeps the day it was really read."""
    if not isinstance(payload, dict):
        return payload
    return dict(payload, fetched=time.strftime("%Y-%m-%d", time.gmtime()))


def _rates_payload(cfg, base="USD"):
    key = (cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), base)
    return _cached("rates", _rates_cache, key, CACHE_TTL, lambda: _timed_refresh("rates " + base, lambda: (
        rates.compute_favorability(
            baseline_days=cfg["baseline_days"],
            threshold_pct=cfg["threshold_pct"],
            watch=cfg["watch"],
            base=base,
        ))), stale_max=STALE_MAX)


def _fares(origin):
    """The cached fares payload /api/flights serves, for the server's own
    fare features (guide chart, flight value). Stale-on-error like the rates:
    a failed refresh serves the last good copy for up to a day. Callers check
    configured + a supported origin first, so an error payload never lands
    in the cache."""
    return _cached("flights", _flights_cache, origin, FLIGHTS_TTL,
                   lambda: flights.get_flights(origin), stale_max=STALE_MAX)


def _public_fares(data):
    # Per-country month curves ride along for the server's fare charts; the
    # browser never reads them, so they don't ship (they'd double the payload).
    if not data.get("countries"):
        return data
    return dict(data, countries=[{k: v for k, v in r.items() if k != "months"}
                                 for r in data["countries"]])


def _base_param(qs):
    """?base= as a currency the FX provider really quotes (blank = USD), or
    None. Checked BEFORE any upstream call: a made-up code used to buy three
    upstream fetches, a full year of history among them, on every request."""
    base = (qs.get("base", ["USD"])[0] or "USD").strip().upper()
    return base if rates.is_known_base(base) else None


# The chart's ranges (rates.INDEX_RANGES). A link from before they existed
# carries ?days= (30/90/180/365); it snaps to the range that replaced it, so
# each base still has a fixed handful of cache keys.
def _index_range(qs):
    rng = (qs.get("range", [""])[0] or "").strip().lower()
    if rng in rates.INDEX_RANGES:
        return rng
    try:
        days = int(qs.get("days", ["365"])[0])
    except (TypeError, ValueError):
        days = 365
    return "1m" if days <= 30 else "3m" if days <= 90 else "6m" if days <= 180 else "1y"


# Other names people type or link for a country -> its ISO code. Each 301s to
# the canonical /guide/<slug>; a bare ISO code (/guide/jp, which the share card
# prints before the slug table loads) resolves the same way.
GUIDE_ALIASES = {
    "usa": "US", "america": "US", "united-states-of-america": "US",
    # england/scotland/wales are guides of their own (GB-ENG/SCT/WLS).
    "uk": "GB", "great-britain": "GB", "britain": "GB", "northern-ireland": "GB",
    "uae": "AE", "emirates": "AE",
    "czech-republic": "CZ", "turkiye": "TR", "ivory-coast": "CI",
    "cote-divoire": "CI", "burma": "MM", "swaziland": "SZ", "macedonia": "MK",
    "holland": "NL", "the-netherlands": "NL", "korea": "KR",
    "republic-of-korea": "KR", "dprk": "KP", "east-timor": "TL",
    "drc": "CD", "democratic-republic-of-the-congo": "CD",
    "congo-kinshasa": "CD", "congo-brazzaville": "CG", "bosnia": "BA",
    "the-bahamas": "BS", "the-gambia": "GM", "viet-nam": "VN", "lao-pdr": "LA",
    "russian-federation": "RU", "brunei-darussalam": "BN",
    "syrian-arab-republic": "SY", "kyrgyz-republic": "KG",
    "slovak-republic": "SK", "falklands": "FK", "png": "PG",
    "palestinian-territories": "PS", "hong-kong": "HK", "macau": "MO",
    "macao": "MO",
}


def _slugish(raw):
    """/guide/T%C3%BCrkiye, /guide/United_States -> turkiye, united-states."""
    s = unicodedata.normalize("NFKD", urllib.parse.unquote(raw))
    s = s.encode("ascii", "ignore").decode("ascii").replace("&", "and").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _guide_redirect(raw):
    """Canonical slug for a non-canonical /guide/ path, or None."""
    slug = _slugish(raw)
    if render_guide.iso_for_slug(slug):
        return slug
    iso_to_slug = {iso: sl for sl, iso in render_guide.all_slugs()}
    # Any ISO-style code, not only two letters: the subdivision guides are
    # keyed GB-ENG/GB-SCT/GB-WLS, and /guide/gb-eng 404'd.
    return iso_to_slug.get(GUIDE_ALIASES.get(slug) or slug.upper())


def _guide_path_redirect(raw, raw_path):
    """The Location for /guide/<raw> when <raw> isn't the exact slug
    (render_guide.iso_for_slug, checked first by the caller) but names a
    guide: /guide/<slug>, the query kept byte for byte. None for a true miss
    (the 404 page). `raw_path`: the request's whole path, query and all."""
    name = raw.strip("/")
    target = _guide_redirect(name) if name and "/" not in name else None
    if not target:
        return None
    query = raw_path.split("?", 1)[1] if "?" in raw_path else ""
    return "/guide/" + target + ("?" + query if query else "")


# app.js GC_RE: the codes a ?gc= link opens (JP, and GB-SCT-style home nations).
_GC_RE = re.compile(r"[A-Z]{2}(-[A-Z]{3})?")


def _guide_query_redirect(raw_path):
    """/guide/<slug>?<the rest> for a homepage URL in the app's own guide form
    (/?tab=guide&gc=ZA: the newsletter's links, and app.js guidePath before
    slugs.json loads), or None. Served as the homepage, each was a second URL
    for a guide page, and Search Console listed /?tab=guide&gc=ZA as
    "Duplicate, Google chose different canonical than user".

    Only where the app would open that guide anyway: tab=guide, a gc code by
    GC_RE, read the way URLSearchParams.get reads them (decoded, first value
    wins), and a guide page for the code (Malta has none: its link stays).
    tab and gc are dropped and every other pair is kept byte for byte (vmn,
    vmf, vo, UTM tags), in order. Not with ai=: only a ?gc= landing opens the
    Plan with AI panel (postApplyShared), and /guide/<slug>?ai=1 would not."""
    query = raw_path.split("?", 1)[1] if "?" in raw_path else ""
    pairs = [p for p in query.split("&") if p]
    keys = [urllib.parse.unquote_plus(p.split("=", 1)[0]) for p in pairs]
    first = {}
    for k, p in zip(keys, pairs):
        first.setdefault(k, urllib.parse.unquote_plus(p.split("=", 1)[1]) if "=" in p else "")
    gc = first.get("gc", "")
    if first.get("tab") != "guide" or first.get("ai") or not _GC_RE.fullmatch(gc):
        return None
    slug = {iso: sl for sl, iso in render_guide.all_slugs()}.get(gc)
    if not slug:
        return None
    rest = "&".join(p for k, p in zip(keys, pairs) if k not in ("tab", "gc"))
    return "/guide/" + slug + ("?" + rest if rest else "")


# At most PAGE_SLOTS server-rendered pages are worked on at once. With a 128
# backlog a crawler's burst is accepted whole, and on Render's 0.1 CPU thirty
# pages rendering side by side kept the health check's thread from running
# for 5-9 s even with no advisory refresh (stall_check --scenario fresh
# --crawl 30: max 8.9 s, 4 of 47 probes over 5 s; with 3 slots 2.4-5.8 s;
# adv_expired --crawl 30: 9 over 5 s -> none).
#
# A slot bounds CPU, so only the routes that render from what the server
# already holds take one (_SLOT_PATHS, _slot_route), GET and HEAD alike:
#   (i)   slot: / (the app shell), /guide/<slug>, /data, /safe-and-cheap,
#         /do-not-travel, /cheapest and its 12 months, /dollar-strength and
#         /privacy. Each reads caches and refreshes them
#         on background threads, with two exceptions that wait on the network
#         inline and give the slot back while they do (_no_slot): /data
#         rebuilding its dataset (_dataset: a rates fetch, at most hourly,
#         computing it or waiting on the rebuild another request leads), and
#         a list page asking for an advisory list not in hand at all
#         (_adv_compute_once, after a cold start: computing it, or waiting on
#         the computation another thread leads).
#   (ii)  no slot, trivial: /healthz, static files from public/ (robots.txt,
#         app.js, styles.css, images), /health.json and /guide-facts.json
#         (bytes memoized per document), /ppp.json and /pl_history.json
#         (bytes memoized per table, _json_bytes), /sitemap.xml and /llms.txt
#         (well under a millisecond each), /api/flight-shadow (bytes
#         memoized, fxtracker/flightshadow.py), redirects, 404s. The app fetches
#         the two tables on a visitor's first load, past Cloudflare's HTML
#         cache, and the Top Picks tab doesn't build without the first: shed
#         with the crawler's guides they were, and a Googlebot fetch of the
#         sitemap with them.
#         Redirects on the slot routes above included, so they are never
#         queued or shed (_redirect_only, asked before a slot is): the old
#         query-form guide URL (/?tab=guide&gc=JP -> /guide/japan), another
#         spelling of a guide (/guide/Japan, /guide/usa, /guide/jp/) and any
#         path on the onrender.com host. In the Nov 18 14:30 ET crawl that
#         Render restarted a64aea2 over, 35-40% of requests were
#         /?tab=guide&gc=XX: each waited behind guide renders like a page,
#         and past PAGE_QUEUE_MAX got the 503 page where the crawler needed
#         the 301 to reach the guide. Answering one is a few dict lookups.
#         So is a /guide/ path that names no guide, answered with the 404
#         page (_guide_miss: the shell's, made once, its "Did you mean"
#         left out while every slot is taken and paced to one search per
#         SUGGEST_EVERY, _suggest_ok): queued with the crawler's guides, a
#         miss could get the 503 page instead of its 404.
#         /?tab=guide&gc=SC (no Seychelles guide) is the homepage: a slot.
#         Not a 301 to /: it is the address app.js gives the guide of each
#         of the 29 countries with data but no guide page (guidePath, for
#         links, shares and the guide's own canonical, setGuideMeta), and
#         the app opens that guide there. A 301 would land those readers
#         on Top Picks, and browsers would keep it if a guide page came
#         later. The homepage's served canonical is / anyway.
#   (iii) no slot, may wait on an upstream inline: every /api/* route
#         (rates, flights and fare months via Travelpayouts, Canada's notes,
#         fx-trend, the advisories fallback, Upstash for /api/auth/me),
#         /auth/verify (Upstash), /data/price-levels.json and .csv (the
#         same dataset rebuild). An idle network wait costs no CPU, and
#         three of them holding every slot kept every other visitor's page
#         waiting up to PAGE_SLOT_WAIT.
#
# Past the slots, load is shed: a slot-route request that finds PAGE_QUEUE_MAX
# others already waiting is answered 503 at once, and one that waits
# PAGE_SLOT_WAIT without getting a slot is answered 503 then (_take_slot,
# Handler._send_busy: Retry-After, no-store, a two-line page; HEAD alike, no
# body). It used to run without a slot after the wait, so under a crawl that
# outlasted PAGE_SLOT_WAIT the renders in flight grew without bound (~45
# observed) and /healthz had to win the GIL from all of them: stall_check's
# Nov 16 replay (--crawl 130 --rate 2.8 --burst-at 45 --on-ms 2) failed on
# a64aea2 in 2 of 3 runs (up to 19 probes over 5 s, worst 15.4 s; with gzip
# clients 29 over 5 s, worst 19.5 s), the slow probes starting 30-40 s into
# the crawl, when the first waits ran out. Answering 503 instead: no probe over
# 5 s in any of 17 runs at that pattern, worst 0.5-1.4 s during the crawl.
# The queue cap adds the heavier crawl (--rate 5, 190 guides): with the wait
# alone 18-22 probes went over 5 s in 2 of 3 runs, with a cap of 8 none in 2
# of 3 (worst 2.1-2.8 s), and a waiting page is told at once instead of after
# 15 s.
#
# Two slots, not three: renders use no network (a page waiting on one gives
# its slot back, _no_slot), so on one shared CPU a third concurrent render
# adds no throughput, only one more thread for /healthz to win the GIL from.
# With the cap of 8, at --rate 5: 3 slots failed both runs (34 and 14 probes
# over 5 s, worst 12.6 and 8.1 s), 2 slots passed all three (worst 1.35-1.63 s)
# serving as many pages (43-51 of 190 against 54 and 43); at the Nov 16 pattern
# 2 slots served 50 and 57 of 130 against 50-52 with 3, worst probe 1.24-1.36 s;
# in production's state (fares, notes) 48 against 40, worst 1.0 s against 1.2.
# One slot did as well at --rate 5 but leaves a page alone with the background
# work (Canada's notes, two workers) for the GIL: 44 served.
# A crawler reads 503 + Retry-After as "slow down" (Googlebot backs off); a
# visitor only meets it while the site is that far behind, where before the
# health check timed out and Render restarted the whole container.
# None (the default: tests, tools) is unbounded; server.main() turns it on.
PAGE_SLOTS = 2
PAGE_SLOT_WAIT = 15
PAGE_QUEUE_MAX = 8      # slot-route requests waiting at once before new ones get 503 at once
SHED_RETRY_AFTER = 30   # seconds, the 503's Retry-After
# A list page whose inputs aren't in hand yet (after a restart, prices, climate
# or every US level missing: render_cheapest.available, or /safe-and-cheap
# with no US levels from the feed or the snapshot, or no prices) is the same
# page sent as a 503 with this Retry-After, so a crawler never stores its
# "isn't available right now" copy. The snapshot standing in for the US feed
# is a full list: 200, uncached.
LIST_UNAVAILABLE_RETRY = 300
# The way out if the slot holders themselves hang (no known path does: a
# stalled write gives up after Handler.CLIENT_IO_TIMEOUT, inline network
# waits give their slot back and time out): when every slot has been held
# PAGE_STUCK_AFTER seconds or more, a page that would be shed runs without a
# slot instead, as every page did after its wait before shedding, and the
# [busy] line counts it. Shedding alone would answer every page 503 for as
# long as they stay stuck while /healthz, which takes no slot, kept Render
# from restarting anything. A render takes milliseconds; two minutes is not
# load.
PAGE_STUCK_AFTER = 120
_page_slots = None
_slot_waiting = [0]     # requests waiting in _take_slot right now
_slot_wait_lock = threading.Lock()
_slot_since = {}        # thread ident -> time.monotonic() it took the slot it holds
# One "[busy]" line on stderr, at most every BUSY_LOG_EVERY seconds, while
# pages are shed, finish without a slot, or BUSY_QUEUE_DEEP or more wait:
# counts since the last line, so a health-check failure can be laid beside
# the load that caused it (Render keeps ~7 days of logs). A timer writes the
# last window's counts once things go quiet. Redirects take no slot
# (_redirect_only), so they are in none of the counts: a crawl like Nov 18's
# reads lower here than it did on 0c811b5, where its 301s queued and were shed.
# Nor do a guide miss's 404s (_guide_miss).
BUSY_LOG_EVERY = 30
BUSY_QUEUE_DEEP = 4
_busy = {"at": 0.0, "queue": 0, "wait": 0, "slotless": 0, "deep": 0, "peak": 0, "stuck": 0, "bot": 0,
         "timer": None}
# Sheds are split by whether the User-Agent names itself a crawler, so the
# [busy] lines show whether people are being turned away or only bots (a
# crawler with a browser's User-Agent counts as a person: an upper bound).
_BOT_UA = re.compile(r"bot\b|bot/|crawl|spider|slurp|scrap|preview|externalhit|headless|python|curl|wget|"
                     r"go-http|java/|okhttp|axios|node-fetch|httpx|libwww|ahrefs|semrush|petal|yandex|baidu",
                     re.IGNORECASE)
_busy_lock = threading.Lock()


def _busy_note(kind, bot=False):
    """Count one event for the [busy] line: "queue" or "wait" (a page shed,
    _take_slot; `bot`: its User-Agent names a crawler), "slotless" (a page
    back from its inline wait finishing without a slot, _no_slot), "deep" (a
    request queueing behind BUSY_QUEUE_DEEP or more) or "stuck"; write the
    line if BUSY_LOG_EVERY has passed."""
    with _busy_lock:
        _busy[kind] += 1
        if bot and kind in ("queue", "wait"):
            _busy["bot"] += 1
        _busy["peak"] = max(_busy["peak"], _slot_waiting[0])
        line = _busy_line(time.time())
        arm = _busy["timer"] is None
    if line:
        sys.stderr.write(line)
    if arm:
        _busy_arm()


def _busy_line(now):
    """The [busy] line for the counts so far and reset them, or None (inside
    BUSY_LOG_EVERY of the last one, or nothing counted). Under _busy_lock."""
    if now - _busy["at"] < BUSY_LOG_EVERY or not any(_busy.get(k) for k in ("queue", "wait", "slotless", "deep",
                                                                             "stuck")):
        return None
    slots = _page_slots
    size = slots._initial_value if slots is not None else PAGE_SLOTS
    in_use = (size - slots._value) if slots is not None else 0
    stuck = ""
    if _busy.get("stuck"):
        oldest = max([time.monotonic() - t for t in list(_slot_since.values())] or [0])
        stuck = ", %d run without a slot past stuck slots (oldest held %ds)" % (_busy["stuck"], oldest)
    line = ("[busy] %s: shed %d (%d with %d+ waiting, %d after %ds; %d to crawler UAs), %d slotless, "
            "%d queued deep, queue peak %d, now %d waiting, %d/%d slots in use%s\n"
            % ("last %gs" % BUSY_LOG_EVERY if _busy["at"] else "since boot", _busy["queue"] + _busy["wait"],
               _busy["queue"], PAGE_QUEUE_MAX, _busy["wait"], PAGE_SLOT_WAIT, _busy["bot"], _busy["slotless"],
               _busy["deep"], _busy["peak"], _slot_waiting[0], in_use, size, stuck))
    _busy.update(at=now, queue=0, wait=0, slotless=0, deep=0, peak=0, stuck=0, bot=0)
    return line


def _busy_arm():
    """Write the window's counts BUSY_LOG_EVERY from now if any came in, and
    keep doing so while they do. One timer at a time (_busy["timer"])."""
    def flush():
        with _busy_lock:
            if _busy["timer"] is not t:
                return               # replaced (a test reset it)
            line = _busy_line(time.time())
            _busy["timer"] = None
        if line:
            sys.stderr.write(line)
            _busy_arm()
    t = threading.Timer(BUSY_LOG_EVERY, flush)
    t.daemon = True
    with _busy_lock:
        if _busy["timer"] is not None:
            return
        _busy["timer"] = t
    try:
        t.start()
    except Exception:
        with _busy_lock:
            _busy["timer"] = None
_slot_held = threading.local()   # .slots: the semaphore this request thread holds a slot of
_SLOT_PATHS = frozenset(("/", "/data", "/privacy", render_methodology.PATH, render_strength.PATH)
                        + _LIST_PATHS + render_cheapest.PATHS)


def _slot_route(path):
    """True for a route that takes a page slot (class (i) above)."""
    return path in _SLOT_PATHS or path.startswith("/guide/")


def _request_host(headers):
    """The request's Host header, lowercased, port dropped ("" without one)."""
    return (headers.get("Host") or "").split(":", 1)[0].lower()


def _uptime_host(host):
    """True when /healthz may say X-Uptime to this Host (_request_host): the
    onrender.com host and what Render's own probe or a local run sends (an
    IPv4 address, a name without a dot such as localhost, no Host at all).
    Never the public site, nor any other domain: an allow-list, so a second
    custom domain, or wandergrade.com with a trailing dot, stays private."""
    return host.endswith(".onrender.com") or "." not in host or bool(_IPV4_RE.fullmatch(host))


_IPV4_RE = re.compile(r"\d{1,3}(\.\d{1,3}){3}")


# _redirect_only parses a URL before any slot is taken; past this many bytes
# (real links, UTM tags and all, are a few hundred) it doesn't, and the
# request queues for a slot as every page did before, so a 64 KB query can't
# buy ~6 ms of parsing per request outside the slots.
REDIRECT_CHECK_MAX = 2048


def _redirect_only(path, raw_path, host):
    """True when Handler._do_get answers this slot-route request with a
    redirect and renders nothing, so do_GET runs it without a slot (class (ii)
    above). `path`: the request path without its query; `raw_path`:
    self.path; `host`: _request_host(). The same decisions _do_get makes, from
    the same helpers, in the order it makes them: the onrender.com host's
    301, the query-form guide URL on / (_guide_query_redirect) and a /guide/
    path that isn't the exact slug but names a guide (_guide_path_redirect).
    Anything else, a URL longer than REDIRECT_CHECK_MAX, or an error here, is
    False: the request queues for a slot as before and _do_get decides (and
    raises) on its own. The guide data it reads (render_guide._load) is
    loaded by main() before the first request: lazily, every request of a
    burst on a fresh process parsed the six files itself, outside the slots."""
    try:
        if host.endswith(".onrender.com"):
            return True
        if len(raw_path) > REDIRECT_CHECK_MAX:
            return False
        if path == "/":
            return _guide_query_redirect(raw_path) is not None
        if path.startswith("/guide/"):
            raw = path[len("/guide/"):]
            return not render_guide.iso_for_slug(raw) and _guide_path_redirect(raw, raw_path) is not None
    except Exception:
        pass
    return False


def _guide_miss(path, raw_path):
    """True when Handler._do_get answers this /guide/ request with the 404
    page: neither a guide's exact slug nor another spelling of one
    (_guide_path_redirect), so do_GET runs it without a slot, as a redirect
    (class (ii) above). Its page is the shell's 404 with the guide index,
    made once (_not_found_bytes), with a "Did you mean" (difflib,
    _did_you_mean) only while a slot is free and at most once per
    SUGGEST_EVERY across all slotless misses (_suggest_ok): a whole request
    ~0.35 ms of CPU on a Mac with it, ~0.08 ms without, where the 503 a
    shed miss got was ~0.05 ms. A slot let a miss wait behind the crawler's
    guides and be shed 503 like them. Anything else, a URL longer than
    REDIRECT_CHECK_MAX, or an error here, is False: the request queues for a
    slot as before. Asked after _redirect_only, which has answered the
    onrender.com host."""
    try:
        if not path.startswith("/guide/") or len(raw_path) > REDIRECT_CHECK_MAX:
            return False
        raw = path[len("/guide/"):]
        return not render_guide.iso_for_slug(raw) and _guide_path_redirect(raw, raw_path) is None
    except Exception:
        return False


def _slot_taken():
    with _slot_wait_lock:
        _slot_since[threading.get_ident()] = time.monotonic()


def _slot_given_back():
    with _slot_wait_lock:
        _slot_since.pop(threading.get_ident(), None)


def _slots_stuck(size):
    """True when all `size` slots have been held PAGE_STUCK_AFTER or more."""
    now = time.monotonic()
    with _slot_wait_lock:
        held = list(_slot_since.values())
    return len(held) >= size and all(now - t >= PAGE_STUCK_AFTER for t in held)


def _take_slot(slots, bot=False):
    """Take one of `slots` for a request arriving on a slot route: None once
    taken (recorded in _slot_since), "stuck" when it is to run without one
    (every slot held past PAGE_STUCK_AFTER), else why it is shed: "queue"
    (PAGE_QUEUE_MAX others already waiting: no wait at all) or "wait" (none
    came within PAGE_SLOT_WAIT). `bot`: the request's User-Agent names a
    crawler (the [busy] line's split)."""
    if slots.acquire(blocking=False):
        _slot_taken()
        return None
    with _slot_wait_lock:
        full = _slot_waiting[0] >= PAGE_QUEUE_MAX
        if not full:
            _slot_waiting[0] += 1
        deep = _slot_waiting[0] >= BUSY_QUEUE_DEEP
    if full:
        if _slots_stuck(slots._initial_value):
            _busy_note("stuck")
            return "stuck"
        _busy_note("queue", bot)
        return "queue"
    if deep:
        _busy_note("deep")
    try:
        got = slots.acquire(timeout=PAGE_SLOT_WAIT)
    finally:
        with _slot_wait_lock:
            _slot_waiting[0] -= 1
    if not got:
        if _slots_stuck(slots._initial_value):
            _busy_note("stuck")
            return "stuck"
        _busy_note("wait", bot)
        return "wait"
    _slot_taken()
    return None


@contextlib.contextmanager
def _no_slot():
    """Run the block without this request's page slot, if it holds one: an
    upstream fetch, or a wait on another thread's work, uses no CPU. The
    slot is taken again after. Off a slot (background threads, tests):
    nothing.

    Taking it back is not an arrival: it skips PAGE_QUEUE_MAX, and past
    PAGE_SLOT_WAIT the request finishes without a slot rather than being shed.
    It has already done its waiting (a rates fetch, an advisory list's
    computation) and was admitted under the slots once; a 503 now would
    throw away work it has paid for and leave the reader nothing, where the
    slotless finish is one render. Few requests ever get here (/data's hourly
    dataset rebuild, a list page asking for a cold advisory list, both
    computed once for everyone waiting), so this can't pile up renders the
    way the crawler's guides did when every request ran slotless after the
    wait."""
    slots = getattr(_slot_held, "slots", None)
    if slots is None:
        yield
        return
    _slot_held.slots = None
    _slot_given_back()
    slots.release()
    try:
        yield
    finally:
        if slots.acquire(timeout=PAGE_SLOT_WAIT):
            _slot_taken()
            _slot_held.slots = slots
        else:
            _busy_note("slotless")


def _idle_wait(event, timeout):
    """event.wait(timeout) without holding this request's page slot: a
    request waiting on another thread's work (a cold advisory list the boot
    warm-up is computing) uses no CPU, and three of them held every slot and
    kept a crawler's pages waiting PAGE_SLOT_WAIT."""
    with _no_slot():
        return event.wait(timeout)


# zlib level for text responses. 9 cost twice 6's CPU for ~0.3% fewer bytes
# (a 100 KB guide 2.2 -> 1.0 ms for +0.4%, world.geojson 15.5 -> 5.6 ms for
# +0.2%, app.js 23.6 -> 16.7 ms for +0.2%), and every page and uncached
# asset pays it on Render's 0.15 CPU. zlib lets go of the GIL while it works,
# so this is quota, not /healthz latency.
GZIP_LEVEL = 6


# ---- static files in memory -----------------------------------------------------
# _send_file read a static file from disk and gzipped it again on every
# request: world.geojson (186 KB), activities.json (209 KB) and app.js
# (810 KB, 17 ms of zlib on Render's CPU) for every visitor whose browser or
# Cloudflare POP didn't have them. Text files are kept here, raw and (once a
# client asks) gzipped, each checked against its mtime and size on every
# request, so a changed file is read again at once. Stylesheets are kept
# with their comments out (STRIP_COMMENTS). Images, fonts and media are read
# per request as before: only text is compressed, and the share cards alone
# are ~10 MB. A text file over STATIC_MEMO_MAX is read per request too.
STATIC_MEMO_MAX = 2 * 1024 * 1024
_static_memo = {}          # path -> ((mtime_ns, size), raw, gz or None)
_static_lock = threading.Lock()
_FONT_DIR = os.path.join(PUBLIC, "fonts") + os.sep
_OG_DIR = os.path.join(PUBLIC, "og") + os.sep


def _immutable_font(path):
    return path.startswith(_FONT_DIR) and path.endswith(".woff2")


def _og_card_file(path):
    return path.startswith(_OG_DIR) and path.endswith(".jpg")


def _static_text(path):
    """True for a file _static_bytes keeps: text by its type."""
    ctype = CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream")
    return ctype.startswith(("text/", "application/javascript", "application/json", "application/geo+json",
                             "application/xml", "image/svg+xml"))


def _static_bytes(path, wants_gz):
    """(raw, gzipped or None) for the static file at `path`: raw as served
    (a stylesheet without its comments), gzipped when wants_gz(raw) says the
    response is. From the memo while the file's mtime and size are the same."""
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    if not _static_text(path) or st.st_size > STATIC_MEMO_MAX:
        with open(path, "rb") as f:
            raw = f.read()
        return raw, None
    with _static_lock:
        hit = _static_memo.get(path)
    if hit is None or hit[0] != key:
        with open(path, "rb") as f:
            raw = f.read()
        if STRIP_COMMENTS and path.endswith(".css"):
            raw = strip_comments.css(raw.decode("utf-8")).encode("utf-8")
        hit = (key, raw, None)
    if hit[2] is None and wants_gz(hit[1]):
        hit = hit[:2] + (gzip.compress(hit[1], GZIP_LEVEL),)
    with _static_lock:
        _static_memo[path] = hit
    return hit[1], (hit[2] if wants_gz(hit[1]) else None)


# What a read or write on a request's own socket raises when the client is
# gone: Handler.handle writes one [disconnect] line for these, and only for
# these when _ClientIO tagged them.
_CLIENT_IO_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, BlockingIOError)


class _ClientIO:
    """A request's rfile or wfile: what its own reads and writes raise as a
    client hang-up is tagged (`_client_io`), so Handler.handle can tell it
    from the same exception class raised by an upstream fetch on the way."""
    __slots__ = ("_f",)

    def __init__(self, f):
        self._f = f

    def __getattr__(self, name):
        return getattr(self._f, name)

    def _io(self, fn, *a):
        try:
            return fn(*a)
        except _CLIENT_IO_ERRORS as e:
            e._client_io = True
            raise

    def write(self, b):
        return self._io(self._f.write, b)

    def flush(self):
        return self._io(self._f.flush)

    def readline(self, *a):
        return self._io(self._f.readline, *a)

    def read(self, *a):
        return self._io(self._f.read, *a)


class Handler(BaseHTTPRequestHandler):
    # Generic identity — don't advertise the framework/Python version.
    server_version = "WanderGrade"
    sys_version = ""

    # ---- helpers ---------------------------------------------------------
    def _gzip_ok(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _gzips(self, body, ctype):
        """True when _send_body sends `body` gzipped: a text payload over ~1KB
        to a client that accepts it."""
        # Already-compressed media is left alone — and audio MUST be: a gzipped
        # mp3 has no byte ranges, which iOS Safari needs to play it at all.
        return len(body) > 1024 and self._gzip_ok() \
            and not ctype.startswith(("image/", "audio/", "video/", "font/woff2"))

    def _send_body(self, body, ctype, status=200, cache=None, extra=None, gzipped=None):
        """Send a response, gzipping text payloads over ~1KB when accepted.
        world.geojson alone drops ~163KB -> ~50KB, which matters most on
        Render free-tier cold starts. `gzipped`: body already compressed
        (the page memo's copy), used where _gzips says to compress."""
        encoding = None
        if self._gzips(body, ctype):
            body = gzipped if gzipped is not None else gzip.compress(body, GZIP_LEVEL)
            encoding = "gzip"
        self.send_response(status)
        for hk, hv in SECURITY_HEADERS.items():
            self.send_header(hk, hv)
        self.send_header("Content-Type", ctype)
        if encoding:
            self.send_header("Content-Encoding", encoding)
        if cache:
            self.send_header("Cache-Control", cache)
        for hk, hv in (extra or []):
            self.send_header(hk, hv)
        self.send_header("Content-Length", str(len(body)))
        self._end_headers_with(b"" if getattr(self, "_head_only", False) else body)   # HEAD: no body

    def _end_headers_with(self, body):
        """end_headers() and then `body`, in one write: each write is a
        syscall the thread gives the GIL up for, and under load winning it
        back means waiting behind every runnable thread. The bytes on the
        wire are the same. (An HTTP/0.9 request has no headers: body only.)"""
        if not hasattr(self, "_headers_buffer") or self.request_version == "HTTP/0.9":
            self.end_headers()
            if body:
                self.wfile.write(body)
            return
        self._headers_buffer.append(b"\r\n")
        if body:
            self._headers_buffer.append(body)
        self.flush_headers()

    def _send_page(self, iso, cache):
        """A guide (iso) or the homepage (None) going out with `cache`: from
        the page memo when it is on and the page is public for 5 minutes
        (_page_bytes), else rendered for this request alone, as before."""
        ctype = "text/html; charset=utf-8"
        if _page_memo is None or cache != PAGE_MEMO_CACHE:
            self._send_body(_render_index(iso), ctype, cache=cache)
            return
        raw, gz = _page_bytes(iso, self._gzip_ok())   # a page is always over _gzips' 1 KB
        self._send_body(raw, ctype, cache=cache, gzipped=gz)

    def _send_json(self, obj, status=200, extra=None):
        # Say something about caching, or the browser decides for us. With no
        # Cache-Control at all it caches JSON heuristically and can keep serving a
        # pre-deploy payload: a returning visitor was still holding an advisories
        # response from before Palestine got a Level 4, so it stayed graded and
        # visible for them long after the fix shipped. Five minutes bounds that —
        # the data behind it only moves a few times a day (ADV_TTL is 6h server
        # side), so this costs nothing and caps staleness at something survivable.
        # Errors are never cached, and callers that set their own (auth: no-store)
        # keep it — a duplicate header would be ambiguous.
        extra = list(extra or [])
        if not any(k.lower() == "cache-control" for k, _ in extra):
            extra.append(("Cache-Control",
                          "public, max-age=300" if status == 200 else "no-store"))
        self._send_body(json.dumps(obj).encode("utf-8"),
                        "application/json; charset=utf-8", status, extra=extra)

    # ---- accounts (passwordless magic-link) ------------------------------
    SESS_COOKIE = "wg_sess"

    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _session_email(self):
        try:
            return accounts.session_email(self._cookie(self.SESS_COOKIE))
        except Exception:
            return None

    def _set_session_cookie(self, sid, clear=False):
        # HttpOnly so no script can read it; set on the confirm page's
        # same-origin POST, and Lax keeps it off cross-site POSTs.
        bits = [f"{self.SESS_COOKIE}={'' if clear else sid}", "Path=/", "HttpOnly",
                "SameSite=Lax", "Secure",
                "Max-Age=0" if clear else f"Max-Age={accounts.SESSION_TTL}"]
        return ("Set-Cookie", "; ".join(bits))

    def _own_origins(self):
        """Origins our own pages are served from: the public site, plus the
        local dev server when that is what this request is talking to."""
        own = {accounts.site_origin().lower()}
        host = (self.headers.get("Host") or "").strip().lower()
        if re.fullmatch(r"(localhost|127\.0\.0\.1)(:\d{1,5})?", host):
            own.add("http://" + host)
        return own

    def _same_origin(self, allow_bare=False):
        """True when the browser says this request came from one of our own
        pages. Sec-Fetch-Site and Origin are set by the browser and can't be
        forged by a cross-site page, which is what stops CSRF (a script
        outside a browser can send anything, but rides no one's cookies or
        IP reputation). Referer is the fallback for browsers that send
        neither; allow_bare admits a request with none of the three."""
        sfs = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if sfs:
            return sfs == "same-origin"
        origin = (self.headers.get("Origin") or "").strip().lower().rstrip("/")
        if origin:
            return origin in self._own_origins()
        ref = (self.headers.get("Referer") or "").strip().lower()
        if ref:
            return any(ref.startswith(o + "/") for o in self._own_origins())
        return allow_bare

    _TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")

    def _signin_redirect(self, ok, sid=None):
        # Never echo the token back; ?signin= is just a UI hint.
        self.send_response(303)
        for hk, hv in SECURITY_HEADERS.items():
            self.send_header(hk, hv)
        if ok:
            self.send_header(*self._set_session_cookie(sid))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Location", "/?signin=" + ("ok" if ok else "expired"))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_auth_verify(self):
        """GET/HEAD of the emailed link: a confirm page that spends nothing
        (see _render_verify_page). A malformed token can't be redeemed
        anyway, so it goes straight to the "expired" hint."""
        from urllib.parse import parse_qs, urlparse
        token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        if not self._TOKEN_RE.fullmatch(token):
            self._signin_redirect(False)
            return
        self._send_body(_render_verify_page(token), "text/html; charset=utf-8",
                        cache="no-store", extra=[("X-Robots-Tag", "noindex")])

    def _handle_auth_verify_post(self):
        """The confirm page's button: redeem once, then land on the map.
        Same-origin only — a cross-site form posting an attacker's token would
        otherwise sign the victim into the attacker's account (login CSRF),
        and the app would then upload the victim's map into it. Bare requests
        pass, so an old in-app browser that sends no Origin can still sign in."""
        if not self._same_origin(allow_bare=True):
            self._send_json({"error": "forbidden"}, 403)
            return
        raw = self._read_raw()
        if raw is None:
            return
        from urllib.parse import parse_qs
        try:
            token = parse_qs(raw.decode("utf-8")).get("t", [""])[0]
        except UnicodeDecodeError:
            token = ""
        email, sid = None, None
        if self._TOKEN_RE.fullmatch(token):
            try:
                email, sid = accounts.consume_token(token)
            except Exception:
                email, sid = None, None
        self._signin_redirect(bool(email), sid)

    def _handle_auth_post(self, path):
        if not accounts.enabled():
            self._send_json({"error": "accounts are not configured"}, 503)
            return
        if path == "/api/auth/request":
            # Only our own page may ask for a link. A cross-site fetch with a
            # text/plain body is a CORS "simple request" (no preflight), so
            # without this any web page could make its visitors' browsers mail
            # links to any address, each from a fresh IP bucket.
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json" or not self._same_origin():
                self._send_json({"error": "forbidden"}, 403)
                return
            body = self._read_body()
            if body is None:
                return
            ip = (self.headers.get("CF-Connecting-IP")
                  or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or self.client_address[0])
            # The browser is always told "sent" — revealing whether an address
            # exists (or is throttled) would let anyone probe the user list. So
            # the server log is the ONLY place a real failure is visible.
            try:
                email = body.get("email", "")
                if not accounts.request_link(email if isinstance(email, str) else "", ip):
                    print("[accounts] link NOT sent: invalid address, rate limited or daily cap",
                          flush=True)
            except Exception as e:
                print("[accounts] link send FAILED: %s" % e, flush=True)
            self._send_json({"sent": True})
            return
        # Everything else needs a session, and is checked before any body is
        # read: an anonymous request never gets as far as parsing JSON.
        email = self._session_email()
        if not email:
            self._send_json({"error": "not signed in"}, 401)
            return
        if path == "/api/auth/logout":
            accounts.end_session(self._cookie(self.SESS_COOKIE))
            self._send_json({"ok": True}, extra=[self._set_session_cookie("", clear=True)])
            return
        if path not in ("/api/auth/sync", "/api/auth/prefs"):
            self._send_json({"error": "not found"}, 404)
            return
        body = self._read_body()
        if body is None:
            return
        if path == "/api/auth/sync":
            user = accounts.sync_map(email, body.get("visited"), body.get("wishlist"))
        else:
            user = accounts.set_prefs(email, body.get("subscribed"), body.get("cadence"),
                                      body.get("currency"))
        self._send_json({"user": accounts.public_user(user)})

    def _send_not_found(self, message="Page not found"):
        """JSON for the API (and JSON files), a real page for everyone else."""
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") or path.endswith(".json"):
            self._send_json({"error": "not found"}, 404)
            return
        suggest = None
        if _suggest_ok(path):
            try:
                suggest = _did_you_mean(path)
            except Exception as e:   # a suggestion is a nicety: never a 500 instead of the 404
                print("[404] no suggestion for %r: %s" % (path[:80], e), flush=True)
        raw, gz = _not_found_bytes(message, suggest, self._gzip_ok())
        self._send_body(raw, "text/html; charset=utf-8", 404, cache="no-store",
                        extra=[("X-Robots-Tag", "noindex")], gzipped=gz)

    def _send_file(self, path, versioned=False):
        # Directories (/fonts) and anything else that isn't a plain file get
        # a 404 — open() on a directory raised IsADirectoryError, which killed
        # the handler and surfaced as a Cloudflare 502.
        if not os.path.isfile(path):
            self._send_not_found()
            return
        ext = os.path.splitext(path)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        # ?v=<mtime>-stamped assets (the template rewrites app.js/styles.css)
        # can cache forever — the URL itself changes on deploy. So can the
        # font files: their names are Google Fonts' own, which change with
        # the font (jakarta.css names them, and it isn't immutable). geojson
        # is effectively static; the share cards (/og/<slug>.jpg) change only
        # when scripts/dev/og_cards.mjs is re-run; other data files change
        # with deploys, so keep their staleness window short (10 min) to not
        # mask fresh releases.
        cache = "public, max-age=31536000, immutable" if versioned or _immutable_font(path) \
            else "public, max-age=86400" if ext in (".geojson", ".mp3") or _og_card_file(path) \
            else "public, max-age=600" if ext == ".json" \
            else "public, max-age=300"
        if ctype.startswith(("audio/", "video/")):
            self._send_media(path, ctype, cache)
            return
        try:
            body, gz = _static_bytes(path, lambda raw: self._gzips(raw, ctype))
        except OSError:
            self._send_not_found()
            return
        self._send_body(body, ctype, cache=cache, gzipped=gz)

    def _send_media(self, path, ctype, cache):
        """Media with byte-range support. iOS Safari won't play audio/video
        from a server that answers a Range request with the whole file, so
        honour a single `bytes=a-b` / `a-` / `-n` range with a 206."""
        size = os.path.getsize(path)
        extra = [("Accept-Ranges", "bytes")]
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        start, end = 0, size - 1
        if m and m.group(1) and m.group(2) and int(m.group(2)) < int(m.group(1)):
            m = None                           # invalid range: ignore it, send it all
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:                              # suffix: the last n bytes
                start = max(0, size - int(m.group(2)))
            if start >= size or start > end:
                self.send_response(416)
                for hk, hv in SECURITY_HEADERS.items():
                    self.send_header(hk, hv)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            extra.append(("Content-Range", "bytes %d-%d/%d" % (start, end, size)))
            status = 206
        else:
            status = 200                       # no (or an unsupported) range
        with open(path, "rb") as f:
            f.seek(start)
            body = f.read(end - start + 1)
        self._send_body(body, ctype, status, cache=cache, extra=extra)

    # Real bodies are tiny: sync sends at most 2x400 ISO codes, the rest a
    # few fields. Anything bigger is refused unread — json.loads of a ~20MB
    # body of empty lists peaked above the 512MB instance limit.
    MAX_BODY = 16 * 1024

    def _read_raw(self):
        """The request body as bytes, or None after answering 400/413 itself."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._send_json({"error": "bad Content-Length"}, 400)
            return None
        if length > self.MAX_BODY:
            self.close_connection = True   # the unread body can't be parsed as a request
            self._send_json({"error": "request body too large"}, 413)
            return None
        return self.rfile.read(length) if length else b""

    def _read_body(self):
        """The JSON body as a dict ({} for anything else), or None after
        answering 400/413 itself."""
        raw = self._read_raw()
        if raw is None:
            return None
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):   # UnicodeDecodeError is a ValueError
            return {}
        return data if isinstance(data, dict) else {}

    # A sign-in link's one-time token stays out of the log (Render keeps it),
    # as it stays out of the analytics beacon (_render_verify_page).
    _LOG_TOKEN = re.compile(r"(/auth/verify\?)[^\s\"]*")

    def log_message(self, fmt, *args):  # quieter console; no client address
        sys.stderr.write("  %s\n" % self._LOG_TOKEN.sub(r"\1t=[redacted]", fmt % args))

    # A client that hangs up before its response is out (a crawler's timeout,
    # Cloudflare giving up on an origin fetch, a reader closing the tab) raised
    # out of handle(), and socketserver printed "Exception occurred during
    # processing of request" and a traceback: 3.1 KB in 27 separate writes to
    # stderr each, in bursts on /api/flights and the fare months in Render's
    # log. One line instead; any other exception keeps its traceback.
    #
    # Only when it came from this request's own socket (_ClientIO tags it):
    # the same classes come out of an upstream fetch (Upstash or a feed
    # closing on us is http.client.RemoteDisconnected, a ConnectionResetError,
    # which urllib passes through unwrapped), and those keep their traceback.
    _DISCONNECTS = _CLIENT_IO_ERRORS

    # A read or write on the request's socket that makes no progress for
    # CLIENT_IO_TIMEOUT seconds gives up: nothing bounded it, so a slot
    # holder writing a page to a peer that stopped reading held its slot for
    # good, and with both slots held so every page would be shed while
    # /healthz stayed green. Set as SO_SNDTIMEO/SO_RCVTIMEO, not settimeout():
    # Python polls before every operation on a socket with a timeout, one
    # more GIL hand-off per read and write, and /healthz's latency under
    # load is counted in those. A stalled write raises BlockingIOError (one
    # [disconnect] line, "timeout"); a request line that never comes reads
    # as empty and the connection closes, as for a client that hangs up.
    CLIENT_IO_TIMEOUT = 30

    def setup(self):
        super().setup()
        secs = self.CLIENT_IO_TIMEOUT
        tv = struct.pack("ll", int(secs), int(round(secs % 1 * 1e6)))   # struct timeval
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, tv)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, tv)
        except OSError:
            pass
        self.rfile, self.wfile = _ClientIO(self.rfile), _ClientIO(self.wfile)

    def handle(self):
        try:
            super().handle()
        except self._DISCONNECTS as e:
            if not getattr(e, "_client_io", False):
                raise
            self.close_connection = True
            sys.stderr.write("  [disconnect] %s %s %s\n" % (
                getattr(self, "command", None) or "-",
                self._LOG_TOKEN.sub(r"\1t=[redacted]", getattr(self, "path", None) or "-"),
                "timeout (no progress in %gs)" % self.CLIENT_IO_TIMEOUT if isinstance(e, BlockingIOError)
                else type(e).__name__))

    # ---- auth ------------------------------------------------------------
    def _authed(self):
        """True if auth is off, or the request carries valid Basic credentials.
        Sends a 401 challenge and returns False otherwise."""
        if not AUTH_ON:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                # constant-time compare to avoid timing leaks
                if hmac.compare_digest(user, AUTH_USER) and hmac.compare_digest(pw, AUTH_PASS):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="fx-tracker"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    # ---- routing ---------------------------------------------------------
    def do_HEAD(self):
        # Serve HEAD by running the GET path with the body suppressed — same
        # status + headers, no payload. Without this the stdlib base handler
        # returns 501 to HEAD probes (crawlers, link-checkers, uptime monitors).
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    # Sent when a page is shed (_take_slot): small enough to go out raw, and
    # no-store so no cache keeps "busy" as the page.
    _BUSY_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1">'
                  '<title>Busy | WanderGrade</title></head><body><p>WanderGrade is busy '
                  'right now. Please try again in a minute.</p><p><a href="/">WanderGrade</a></p>'
                  '</body></html>').encode("utf-8")

    def _send_busy(self, body=None, retry_after=None):
        # No X-Robots-Tag: Google ignores a 5xx's body anyway, and a crawler
        # that applied noindex whatever the status could drop the URL itself;
        # 503 + Retry-After says "come back later" on its own. `body`: a page
        # rendered without its data (a list page before its inputs load,
        # LIST_UNAVAILABLE_RETRY) goes out as itself, the reader sees what it
        # says, and Google keeps its last good copy instead of the empty one.
        self._send_body(self._BUSY_PAGE if body is None else body, "text/html; charset=utf-8", 503,
                        cache="no-store", extra=[("Retry-After", str(retry_after or SHED_RETRY_AFTER))])

    def do_GET(self):
        slots = _page_slots
        path = self.path.split("?", 1)[0]
        # A redirect on a slot route (/?tab=guide&gc=JP, /guide/Japan, the
        # onrender.com host) renders nothing, and a guide miss's 404 page next
        # to nothing: never queued, never shed.
        if (slots is None or not _slot_route(path)
                or _redirect_only(path, self.path, _request_host(self.headers)) or _guide_miss(path, self.path)):
            return self._do_get()
        why = _take_slot(slots, bool(_BOT_UA.search(self.headers.get("User-Agent") or "")))
        if why == "stuck":
            return self._do_get()
        if why:
            self._send_busy()
            return
        _slot_held.slots = slots
        try:
            return self._do_get()
        finally:
            if getattr(_slot_held, "slots", None) is slots:
                _slot_held.slots = None
                _slot_given_back()
                slots.release()

    def _do_get(self):
        path = self.path.split("?", 1)[0]
        # Unauthenticated health check for hosting platforms (Render, etc.).
        if path == "/healthz":
            # send_response() with its request-log line moved to after the
            # answer: stderr is one pipe whose lock every request's line (and
            # any traceback) shares, and Render's probe shouldn't wait on it.
            self.send_response_only(200)
            self.send_header("Server", self.version_string())
            self.send_header("Date", self.date_time_string())
            self.send_header("Content-Type", "text/plain")
            # Whole seconds since this process started, so a restart Render
            # made (a failed check) can be seen after the fact: on Render's
            # own probe (Host: its internal address) and the onrender.com
            # host (_uptime_host), never on the public site, where anyone
            # could read its restart times. Keyed on Host, not CF-Ray:
            # Render's own edge is Cloudflare too, so every outside request
            # carries a CF-Ray, the onrender.com host's included (seen
            # 2026-11-19), and X-Uptime showed only to the probe.
            if _uptime_host(_request_host(self.headers)):
                self.send_header("X-Uptime", str(int(time.monotonic() - _BOOT)))
            self.send_header("Content-Length", "2")
            self._end_headers_with(b"ok")
            self.log_request(200)
            return
        # Canonical-domain redirect: bounce the old *.onrender.com host to the
        # custom domain so links and SEO consolidate on one host. /healthz above
        # is exempt so Render's health checks are unaffected. Requests already on
        # wandergrade.com don't match and serve normally.
        # (A redirect takes no page slot: do_GET asks _redirect_only.)
        host = _request_host(self.headers)
        if host.endswith(".onrender.com"):
            self.send_response(301)
            self.send_header("Location", "https://wandergrade.com" + self.path)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # Accounts are public by design and predate the owner-only auth gate.
        if path == "/auth/verify":
            self._handle_auth_verify()
            return
        if path == "/api/auth/me":
            email = self._session_email() if accounts.enabled() else None
            user = accounts.get_user(email) if email else None
            extra = [("Cache-Control", "no-store")]
            if email:
                # session_email() just rolled the stored session forward; re-stamp
                # Max-Age to match, or the cookie would still die 90 days after
                # sign-in and log out an active traveler anyway. Fires once per
                # page load, and costs no extra storage call.
                extra.append(self._set_session_cookie(self._cookie(self.SESS_COOKIE)))
            self._send_json({"email": email, "user": accounts.public_user(user) if user else None},
                            extra=extra)
            return
        if not self._authed():
            return
        if path == "/api/rates":
            from urllib.parse import parse_qs, urlparse
            base = _base_param(parse_qs(urlparse(self.path).query))
            if base is None:
                self._send_json({"error": "unknown base currency"}, 400)
                return
            try:
                self._send_json(_rates_payload(store.load_config(), base))
            except Exception as e:  # provider down and no earlier copy to serve
                self._send_json({"error": str(e)}, 500)
            return
        if path == "/api/index":
            self._handle_index()
            return
        if path == "/api/advisories":
            self._handle_advisories()
            return
        if path == "/api/flight-months":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            origin = (qs.get("origin", ["US"])[0] or "US").strip().upper()[:2]
            dest = (qs.get("dest", [""])[0] or "").strip().upper()[:3]
            iso = (qs.get("iso", [""])[0] or "").strip().upper()[:2]
            # iso -> destination city resolves HERE, against the same cached
            # fares payload the flights tab uses — so a guide page needs only
            # this one call, with no client-side fares bootstrap to race.
            if not dest and iso and flights.is_configured() and origin in flights.ORIGIN_HUBS:
                try:
                    payload = _fares(origin)
                except Exception:
                    # Couldn't resolve the country to a city: a failure, not
                    # "no fares" — same rule as _send_fare_months.
                    self._send_json({"configured": True, "months": {},
                                     "error": "fare lookup failed"}, 500)
                    return
                row = next((r for r in payload.get("countries", []) if r.get("iso") == iso), None)
                if row:
                    # The country's ONE curve (its top cached cities + the
                    # latest-prices rows) — the Flights tab bands this exact
                    # curve, so the chart and the tab never disagree.
                    self._send_fare_months(flights.get_country_monthly(origin, row))
                    return
            self._send_fare_months(flights.get_monthly(origin, dest))
            return
        if path == "/api/trip-legs":
            self._handle_trip_legs()
            return
        if path == "/api/flight-value":
            self._handle_flight_value()
            return
        if path == "/api/flight-shadow":
            # The fare-source comparison so far (fxtracker/flightshadow.py),
            # for scripts/dev/flight_shadow_report.py: linked from nowhere,
            # from memory alone (no upstream or storage call), never cached
            # or indexed.
            raw, gz = flightshadow.body(self._gzip_ok())
            self._send_body(raw, "application/json; charset=utf-8", cache="no-store",
                            extra=[("X-Robots-Tag", "noindex")], gzipped=gz)
            return
        if path == "/api/fx-trend":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            cur = (qs.get("cur", [""])[0] or "").strip().upper()[:3]
            base = _base_param(qs)
            t, failed = None, False
            # Unknown base: the same empty answer, but without buying a
            # full-year upstream fetch per made-up code.
            if base and re.fullmatch(r"[A-Z]{3}", cur):
                try:
                    t = rates.get_trend(cur, base)
                except Exception:
                    t, failed = None, True
            base = base or (qs.get("base", ["USD"])[0] or "USD").strip().upper()[:3]
            # null is an answer (unknown currency / provider gap) — the guide
            # simply doesn't render the sparkline. A provider failure gets the
            # same body, but no-store: no cache may hold the gap as an answer.
            self._send_json(t or {"code": cur, "base": base, "months": []},
                            extra=[("Cache-Control", "no-store")] if failed else None)
            return
        if path == "/api/geo":
            # Visitor's country from Cloudflare's CF-IPCountry header — pure
            # per-request geolocation, nothing stored, no third-party service.
            # no-store is load-bearing twice over: the answer is personal, and
            # the HTML this feeds defaults into is edge-cached, so geo must
            # never ride anything cacheable. ?as=XX is a dev override (the
            # local server sits behind no proxy and has no header to read).
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            country = (qs.get("as", [""])[0] or self.headers.get("CF-IPCountry", "") or "").strip().upper()[:2]
            self._send_json({"country": country if country.isalpha() else ""},
                            extra=[("Cache-Control", "no-store")])
            return
        if path == "/api/watchouts":
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            iso = (qs.get("iso", [""])[0] or "")[:2]
            # A feed failure answers the same empty body, but no-store.
            notes, failed = watchouts.lookup(iso)
            self._send_json(notes, extra=[("Cache-Control", "no-store")] if failed else None)
            return
        if path == "/api/flights":
            self._handle_flights()
            return
        if path == "/api/flight-origins":
            self._send_json({"origins": flights.origins()})
            return
        if path == "/api/popularity":
            self._handle_popularity()
            return
        if path == "/api/config":
            cfg = store.load_config()
            cfg["email"] = _redact_email(cfg["email"])
            if PUBLIC_MODE:
                # don't leak the owner's email address on a public deployment
                for k in ("username", "from_addr", "to_addr"):
                    cfg["email"][k] = ""
            cfg["readonly"] = PUBLIC_MODE
            self._send_json(cfg)
            return
        # Server-rendered pages: homepage + per-country guide (/guide/<slug>).
        # Both go through the index.html template so <title>/meta/canonical are
        # right before any JS runs. Unknown slugs 404 rather than serving a
        # soft-200 duplicate of the homepage.
        if path == "/":
            # /?tab=guide&gc=ZA 301s to /guide/south-africa, query and all
            # (_guide_query_redirect): one URL per guide. No page slot
            # (do_GET asks _redirect_only first).
            target = _guide_query_redirect(self.path)
            if target:
                self._redirect(target)
                return
            self._send_page(None, "public, max-age=300")
            return
        if path.startswith("/guide/"):
            raw = path[len("/guide/"):]
            iso = render_guide.iso_for_slug(raw)
            if iso:
                # Decided before the render: a list that lands in between
                # only makes the page more right than its header says.
                cache = _guide_cache(iso)
                self._send_page(iso, cache)
                return
            # Only the exact lowercase slug is served. Everything else that
            # names a guide — /guide/Japan, a trailing slash, an alternate
            # name (turkiye, usa), an ISO code (tr, gb-eng) — 301s to it,
            # query and all (UTM tags are how Reddit traffic is attributed).
            # /guide/Japan used to answer 200: a duplicate page per spelling.
            # A true miss gets a real 404 page. (Neither takes a page slot:
            # do_GET asks _redirect_only and _guide_miss, from the same helper.)
            target = _guide_path_redirect(raw, self.path)
            if target:
                self._redirect(target)
            else:
                self._send_not_found("No guide for that country")
            return
        if path == "/sitemap.xml":
            self._send_body(_sitemap(), "application/xml; charset=utf-8",
                            cache="public, max-age=3600")
            return
        if path == "/llms.txt":
            # The site described for AI assistants (fxtracker/llms_txt.py):
            # most AI fetchers don't run JavaScript, so they need telling which
            # pages answer without it. From the sitemap's slug list.
            self._send_body(llms_txt.build(render_guide.all_slugs(), render_guide.name_for_iso).encode("utf-8"),
                            "text/plain; charset=utf-8", cache="public, max-age=3600")
            return
        low = path.lower()
        if low != path and low.rstrip("/") in _LOWER_PATHS:
            # /Cheapest/January, /Safe-and-cheap: one 301 to the lowercase
            # canonical URL (slash dropped), query and all, as /guide/Japan does.
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect(low.rstrip("/") + ("?" + query if query else ""))
            return
        if path in _LIST_PATHS:
            page = _list_page(path)
            if not page.get("available", True):
                # /safe-and-cheap with no list to draw: a 503 with the page.
                self._send_busy(page["bytes"], LIST_UNAVAILABLE_RETRY)
                return
            # no-store while a feed is down: Cloudflare must never hold a copy
            # whose column reads "not loaded" for its five minutes.
            self._send_body(page["bytes"], "text/html; charset=utf-8",
                            cache="no-store" if page["degraded"] else "public, max-age=300")
            return
        if path.endswith("/") and path.rstrip("/") in _LIST_PATHS:
            # One canonical URL each: the slash variant 301s to it, query and
            # all; anything deeper is a real 404, not a soft duplicate.
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect(path.rstrip("/") + ("?" + query if query else ""))
            return
        if path.startswith(tuple(p + "/" for p in _LIST_PATHS)):
            self._send_not_found()
            return
        if path == "/data":
            body = _render_data_page()
            # no-store while the dataset is down (nothing built yet): the copy
            # then has no date and a fallback count, as a list page with a feed
            # down goes out uncached.
            self._send_body(body, "text/html; charset=utf-8",
                            cache="no-store" if _dataset_cache["payload"] is None else "public, max-age=300")
            return
        if path == "/data/":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect("/data" + ("?" + query if query else ""))
            return
        if path == "/privacy":
            # Cached like the list pages (the edge follows this header once
            # Cloudflare's HTML rule names the path); no cookie, nothing personal.
            self._send_body(_render_privacy_page(), "text/html; charset=utf-8",
                            cache="public, max-age=300")
            return
        if path == "/privacy/":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect("/privacy" + ("?" + query if query else ""))
            return
        if path == render_methodology.PATH:
            # Like /privacy: fixed words, cached at the edge, no cookie.
            self._send_body(_render_methodology_page(), "text/html; charset=utf-8",
                            cache="public, max-age=300")
            return
        if path == render_methodology.PATH + "/":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            self._redirect(render_methodology.PATH + ("?" + query if query else ""))
            return
        if path == render_cheapest.HUB or path.startswith(render_cheapest.HUB + "/"):
            # The hub and the twelve months; the slash variant 301s to its
            # canonical URL, query and all, and anything else under /cheapest/
            # (another spelling, a deeper path) is the site's 404.
            seg = path[len(render_cheapest.HUB) + 1:].rstrip("/")
            if path in render_cheapest.PATHS:
                page = _cheap_page(path)
                if not page["available"]:
                    # No list can be drawn yet (render_cheapest.available):
                    # the page says so, as a 503, never a 200 to be indexed.
                    self._send_busy(page["bytes"], LIST_UNAVAILABLE_RETRY)
                else:
                    self._send_body(page["bytes"], "text/html; charset=utf-8",
                                    cache="no-store" if page["degraded"] else "public, max-age=300")
            elif path.endswith("/") and path.rstrip("/") in render_cheapest.PATHS:
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                self._redirect(path.rstrip("/") + ("?" + query if query else ""))
            elif "/" not in seg and render_cheapest.month_alias(seg):
                # /cheapest/feb, /cheapest/Sept, /cheapest/2: the month's
                # page, in one 301, query and all (no slot: not a slot path).
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                self._redirect(render_cheapest.path_for(render_cheapest.month_alias(seg))
                               + ("?" + query if query else ""))
            else:
                self._send_not_found()
            return
        if path == render_strength.PATH:
            page = _strength_page()
            # no-store while an input is missing, as the list pages do.
            self._send_body(page["bytes"], "text/html; charset=utf-8",
                            cache="no-store" if page["degraded"] else "public, max-age=300")
            return
        if path.startswith(render_strength.PATH + "/"):
            # The slash variant 301s to the one URL, query and all; deeper is a 404.
            if path.rstrip("/") == render_strength.PATH:
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                self._redirect(render_strength.PATH + ("?" + query if query else ""))
            else:
                self._send_not_found()
            return
        if path in ("/ppp.json", "/pl_history.json"):
            raw, gz = _json_bytes(path, _ppp_data() if path == "/ppp.json" else _pl_history(), self._gzip_ok())
            self._send_body(raw, "application/json; charset=utf-8", extra=[("Cache-Control", "public, max-age=86400")],
                            gzipped=gz)
            return
        if path == "/health.json":
            # The freshest of the refreshed copy and the committed file (see
            # fxtracker/health.py); the file itself if anything goes wrong.
            try:
                body = health.get_json_bytes()
            except Exception as e:
                print("[health] serving the static file: %s" % e, flush=True)
                body = None
            if body:
                self._send_body(body, "application/json; charset=utf-8",
                                cache="public, max-age=600")
            else:
                self._send_file(os.path.join(PUBLIC, "health.json"))
            return
        if path == "/guide-facts.json":
            # The guide-facts document in force — the server's daily recompute,
            # or the committed file until there is one (fxtracker/guide_facts.py)
            # — so in-app navigation sets the same titles the server renders.
            # Ten minutes, as before: it changes once a day.
            try:
                body = guide_facts.get_json_bytes()
            except Exception as e:
                print("[guide-facts] serving the static file: %s" % e, flush=True)
                body = None
            if body:
                self._send_body(body, "application/json; charset=utf-8",
                                cache="public, max-age=600")
            else:
                self._send_file(os.path.join(PUBLIC, "guide-facts.json"))
            return
        if path in ("/data/price-levels.json", "/data/price-levels.csv"):
            try:
                data = _dataset()
            except Exception as e:
                self._send_json({"error": "dataset unavailable: %s" % e}, 503)
                return
            # Hour cache: the PPP half is annual, the rate half moves slowly, and
            # the build costs a rates fetch. CORS-open because the whole point is
            # that other people can pull it.
            extra = [("Cache-Control", "public, max-age=3600"),
                     ("Access-Control-Allow-Origin", "*")]
            if path.endswith(".csv"):
                extra.append(("Content-Disposition",
                              'inline; filename="wandergrade-price-levels.csv"'))
                self._send_body(data["csv"].encode("utf-8"),
                                "text/csv; charset=utf-8", extra=extra)
            else:
                self._send_json(data["payload"], extra=extra)
            return
        # The raw template, {{TOKENS}} and all, is not a page.
        if path == "/index.html":
            self._redirect("/")
            return
        # static files
        rel = path.lstrip("/")
        if rel.endswith("/"):
            # normpath below drops a trailing slash, so /og.png/ and /app.js/
            # served the file: a duplicate URL per asset. A file has no slash form.
            self._send_not_found()
            return
        safe = os.path.normpath(os.path.join(PUBLIC, rel))
        if os.path.commonpath([PUBLIC, safe]) != PUBLIC:
            self._send_json({"error": "forbidden"}, 403)
            return
        # The minified copy has one URL, /app.js, and only while it is
        # current (_app_js_file); its own path and hash file aren't pages.
        name = os.path.relpath(safe, PUBLIC)
        if name in ("app.min.js", "app.min.js.sha256"):
            self._send_not_found()
            return
        if name == "app.js":
            safe = _app_js_file()
        versioned = "v=" in (self.path.split("?", 1)[1] if "?" in self.path else "") \
            and os.path.splitext(safe)[1] in (".js", ".css")
        self._send_file(safe, versioned=versioned)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        # Account endpoints must work on the public site — that's their whole
        # point — unlike the owner-only settings/email endpoints below.
        if path.startswith("/api/auth/"):
            self._handle_auth_post(path)
            return
        if path == "/auth/verify":
            self._handle_auth_verify_post()
            return
        if not self._authed():
            return
        if PUBLIC_MODE:
            self._send_json({"error": "settings and email are disabled on the public site"}, 403)
            return
        if path == "/api/config":
            self._handle_config_update()
        elif path == "/api/check":
            self._handle_check()
        else:
            self._send_json({"error": "not found"}, 404)

    def _redirect(self, location, status=301):
        self.send_response(status)
        for hk, hv in SECURITY_HEADERS.items():
            self.send_header(hk, hv)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_fare_months(self, data):
        # A failed upstream lookup is an error, not an empty year: a non-2xx
        # makes the client drop it and retry on the next render, where a 200
        # {months:{}} was cached as "no fares" for the whole session.
        if data.get("error") and not data.get("months"):
            self._send_json(data, 500)
        else:
            self._send_json(data)

    def _handle_index(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        rng = _index_range(qs)
        base = _base_param(qs)
        if base is None:
            self._send_json({"error": "unknown base currency"}, 400)
            return
        try:
            payload = _cached("index", _index_cache, (rng, base), CACHE_TTL,
                              lambda: rates.compute_index(rng, base), stale_max=STALE_MAX)
        except Exception as e:
            # 500, not 502: Cloudflare swallows origin 502s and serves its own
            # text page instead of this JSON.
            self._send_json({"error": str(e)}, 500)
            return
        self._send_json(payload)

    def _handle_flights(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        # origin is an ISO-2 country code (aggregated to that country's hub)
        origin = (qs.get("origin", ["US"])[0] or "US").strip().upper()[:2]
        # Never cache error payloads: get_flights marks unsupported origins
        # configured=True, so gating on that flag alone let arbitrary 2-char
        # strings each pin a permanent cache entry. Those (and no token) get
        # get_flights' own answer, uncached.
        if not flights.is_configured() or origin not in flights.ORIGIN_HUBS:
            self._send_json(flights.get_flights(origin))
            return
        # The same stale-on-error copy the guide chart and /api/flight-value
        # read: a failed hourly refresh no longer blanks the Flights table
        # while the value column beside it still has its fares.
        try:
            data = _fares(origin)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
            return
        self._send_json(_public_fares(data))

    def _handle_trip_legs(self):
        # The Trip tab's legs between its countries (fxtracker/triplegs.py),
        # from the cached hub fares only: at most triplegs.MAX_FETCH uncached
        # hub payloads per request, none while the server is busy (the rest
        # come back pending and the browser estimates them). /api/ takes no
        # page slot. Per reader and trip, so never cached; linked from
        # nowhere a crawler follows, and noindex in case.
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        hdrs = [("Cache-Control", "no-store"), ("X-Robots-Tag", "noindex")]
        try:
            origin, isos, month = triplegs.parse(qs.get("origin", [""])[0], qs.get("isos", [""])[0],
                                                 qs.get("month", [""])[0])
        except ValueError as e:
            self._send_json({"error": str(e)}, 400, extra=hdrs)
            return
        if not flights.is_configured():
            self._send_json({"configured": False, "origin": origin, "month": month, "legs": {},
                             "fit": {"a": None, "b": None, "n": 0}, "pending": []}, extra=hdrs)
            return
        out = triplegs.legs(origin, isos, month, fares_for=_fares, cached=_fares_fresh,
                            busy=bool(_flight_shadow_busy()), stale_for=_fares_in_hand)
        self._send_json(out, extra=hdrs)

    def _handle_flight_value(self):
        # Low / typical / high per destination for the Flights tab: every
        # country's monthly curve + its typical range, so the browser bands
        # any departure month instantly. Answers from the cache alone; a
        # background warmer fills the rest (see fxtracker/flightvalue.py).
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        origin = (qs.get("origin", ["US"])[0] or "US").strip().upper()
        if origin not in flights.ORIGIN_HUBS:
            self._send_json({"error": "unsupported origin"}, 400)
            return
        if not flights.is_configured():
            self._send_json({"configured": False, "origin": origin, "countries": {},
                             "months": flightvalue.window_months(),
                             "partial": flightvalue.partial_month(),
                             "min_months": flightvalue.MIN_MONTHS,
                             "filling": False, "ready": 0, "total": 0})
            return
        try:
            fares = _fares(origin)
        except Exception:
            self._send_json({"error": "fare lookup failed"}, 500)
            return
        payload = flightvalue.serve(origin, fares)
        # Incomplete must not be cached — mid-fill the tab re-polls for the
        # rest, and after an aborted pass a reload should see the retry. Once
        # complete, the curves move at most twice a day (12h upstream cache).
        done = not payload["filling"] and payload["ready"] >= payload["total"]
        self._send_json(payload, extra=[("Cache-Control", "public, max-age=600" if done
                                         else "no-store")])

    def _handle_advisories(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        source = (qs.get("source", ["us"])[0] or "us").strip().lower()
        if source not in advisories.SOURCES:
            source = "us"
        try:
            data = _advisories_payload(source)
        except Exception as e:
            # Nothing cached yet and the chosen feed is down (cold start):
            # another government's list, still labelled by its own
            # source_name, beats a 500. Not stored under the requested source,
            # so that feed is tried again once its short backoff ends.
            data = None
            for alt in advisories.FALLBACK_ORDER:
                if alt == source:
                    continue
                try:
                    data = dict(_adv_read(alt), fallback_for=source)
                    break
                except Exception:
                    continue
            if data is None:
                self._send_json({"error": str(e)}, 500)
                return
        # The do-not-travel marks from all three lists (_with_dnt), whichever
        # was asked for. Not cached by the browser while one is still being
        # fetched: app.js's ensureBookingsKnown asks again until it is in.
        _warm_adv_lists()
        data = _with_dnt(data, _adv_dnt())
        self._send_json(data, extra=[("Cache-Control", "no-store")] if data.get("dnt_pending") else None)

    def _handle_popularity(self):
        now = time.time()
        if _pop_cache["data"] and (now - _pop_cache["at"]) < POP_TTL:
            self._send_json(_pop_cache["data"])
            return
        try:
            data = {"arrivals": popularity.get_arrivals()}
        except Exception as e:
            self._send_json({"error": str(e), "arrivals": {}}, 500)
            return
        _pop_cache.update(at=now, data=data)
        self._send_json(data)

    @staticmethod
    def _clamped(value, lo, hi, cast):
        """Coerce a settings number into its sane range; None if unusable."""
        try:
            return max(lo, min(hi, cast(value)))
        except (TypeError, ValueError):
            return None

    def _handle_config_update(self):
        incoming = self._read_body()
        if incoming is None:
            return
        cfg = store.load_config()
        if isinstance(incoming.get("watch"), list):
            cfg["watch"] = [str(c).upper()[:3] for c in incoming["watch"]][:200]
        bounds = {
            "baseline_days": (30, 3650, int),
            "threshold_pct": (0, 50, float),
            "alert_cooldown_hours": (1, 8760, int),
        }
        for k, (lo, hi, cast) in bounds.items():
            if k in incoming:
                v = self._clamped(incoming[k], lo, hi, cast)
                if v is not None:
                    cfg[k] = v
        if "email" in incoming and isinstance(incoming["email"], dict):
            # Preserve stored password if the client sends the redaction placeholder.
            sent = dict(incoming["email"])
            if sent.get("password") == REDACTED:
                sent.pop("password", None)
            cfg["email"].update(sent)
        store.save_config(cfg)
        _rates_cache.clear()  # settings changed; recompute on next fetch
        out = store.load_config()
        out["email"] = _redact_email(out["email"])
        self._send_json({"ok": True, "config": out})

    def _handle_check(self):
        cfg = store.load_config()
        try:
            data = _rates_payload(cfg)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)
            return
        favorable = [r for r in data["rows"] if r["favorable"] and r["watched"]]
        sent = False
        error = None
        if favorable and mailer.is_configured(cfg["email"]):
            try:
                subject, text, html = mailer.render_alert(
                    favorable, data["as_of"], data["baseline_days"])
                mailer.send_email(cfg["email"], subject, text, html)
                sent = True
            except Exception as e:
                error = str(e)
        self._send_json({
            "as_of": data["as_of"],
            "favorable": favorable,
            "email_configured": mailer.is_configured(cfg["email"]),
            "email_sent": sent,
            "error": error,
        })


REDACTED = "********"


def _redact_email(email_cfg):
    out = dict(email_cfg)
    if out.get("password"):
        out["password"] = REDACTED
    return out


_watchouts_warming = set()   # ISOs queued or being fetched
_watchouts_queue = []        # ISOs waiting for a worker, oldest first
_watchouts_workers = [0]     # worker threads running
_watchouts_lock = threading.Lock()
WATCHOUTS_WORKERS = 2        # Canada-notes fetches at once


def _warm_watchouts(iso):
    """Fetch one country's Canada notes in the background (once at a time),
    so the guide's advisory block can be sized on its next render. At most
    WATCHOUTS_WORKERS fetch at once and the rest wait their turn: a crawler
    after a cold start renders guide after guide, and each used to start a
    thread of its own. A country queued or in flight is not queued again."""
    key = (iso or "").upper()
    with _watchouts_lock:
        if not key or key in _watchouts_warming:
            return
        _watchouts_warming.add(key)
        _watchouts_queue.append(key)
        if _watchouts_workers[0] >= WATCHOUTS_WORKERS:
            return
        _watchouts_workers[0] += 1
    try:
        threading.Thread(target=_watchouts_work, daemon=True).start()
    except Exception:
        with _watchouts_lock:
            _watchouts_workers[0] -= 1
            # Nobody will take what this worker would have: let a later
            # render queue those countries again.
            if not _watchouts_workers[0]:
                _watchouts_warming.difference_update(_watchouts_queue)
                del _watchouts_queue[:]


def _watchouts_work():
    while True:
        with _watchouts_lock:
            if not _watchouts_queue:
                _watchouts_workers[0] -= 1
                return
            key = _watchouts_queue.pop(0)
        try:
            watchouts.get_watchouts(key)
        except Exception:
            pass
        finally:
            with _watchouts_lock:
                _watchouts_warming.discard(key)


def _keep_warm():
    # Render's free tier sleeps the service after ~15 idle minutes (next visitor
    # waits ~50s). The GitHub Actions cron that was meant to prevent this fires
    # 1.5-3h apart in practice — GitHub throttles */10 schedules hard — so the
    # service keeps itself warm instead: while it's awake, it pings its own
    # public /healthz every 10 minutes, which counts as inbound traffic and
    # resets the idle clock indefinitely. A sleeping service runs nothing, so
    # this can't WAKE it — deploys and the (slow) GH cron remain that layer.
    # Through Cloudflare, so the UA matters: default Python-urllib gets a 1010.
    def loop():
        while True:
            time.sleep(600)
            try:
                req = urllib.request.Request(
                    "https://wandergrade.com/healthz",
                    headers={"User-Agent": "Wandergrade/1.0 (+https://wandergrade.com; keep-warm)"})
                urllib.request.urlopen(req, timeout=20, context=rates._SSL).read()
            except Exception:
                pass   # transient failure just means the next tick tries again

    threading.Thread(target=loop, daemon=True).start()


def _warm_flight_value(origin=flightvalue.DEFAULT_ORIGIN, delay=20):
    # The Flights tab's low/typical/high needs every destination's monthly
    # curve; fill the default origin's in the background shortly after boot
    # (after the first health checks) so the first visitor finds it ready.
    # A no-op without a Travelpayouts token.
    def run():
        time.sleep(delay)
        if not flights.is_configured():
            return
        try:
            fares = _fares(origin)
        except Exception as e:
            print("[flight-value] warm-up skipped: %s" % e, flush=True)
            return
        flightvalue.start_warm(origin, fares.get("countries") or [])

    threading.Thread(target=run, daemon=True).start()


def _flight_shadow_busy():
    """Why the log-only fare comparison (fxtracker/flightshadow.py) must wait
    right now, or None. It asks before its daily run and before every call
    it makes: a background refresh that parses a feed, a page being rendered
    or waiting for a slot, or pages queued deep or shed in the last 10
    minutes (a [busy] line: a crawl)."""
    if _adv_warming:
        return "advisory refresh"
    if _strength_warm["busy"]:
        return "FX history fetch"
    if health._running.locked():
        return "health rebuild"
    if guide_facts._running.locked():
        return "guide facts rebuild"
    slots = _page_slots
    if slots is not None and (slots._value < slots._initial_value or _slot_waiting[0]):
        return "pages rendering"
    if _busy["at"] and time.time() - _busy["at"] < 600:
        return "pages queued or shed lately"
    return None


def _cached_fares(origin):
    """The fares payload in the cache for `origin`, or None: never a refresh
    (the comparison must not move what readers see, not even its timing)."""
    hit = _flights_cache.get(origin)
    return hit[1] if hit else None


def _fares_fresh(origin):
    """True when _fares(origin) answers from the cache (a copy inside its
    hour): /api/trip-legs reads those freely, and counts the rest against
    its fetch cap."""
    hit = _flights_cache.get(origin)
    return bool(hit) and time.time() - hit[0] < FLIGHTS_TTL


def _fares_in_hand(origin):
    """A copy past its hour but inside STALE_MAX (what a failed refresh would
    serve), or None: never a refresh. /api/trip-legs uses it rather than
    fetch, or leave the country pending."""
    hit = _flights_cache.get(origin)
    return hit[1] if hit and time.time() - hit[0] < STALE_MAX else None


def _warm_rates(delay=15):
    # /safe-and-cheap's dollar column reads the cached /api/rates rows and is
    # left out until some request has computed them (_fx_inputs: a page must
    # never wait on three upstream fetches). Nothing computes them for the
    # first visitor after a restart — the keep-warm only pings /healthz, the
    # daily recompute runs two minutes in — so one background fetch after
    # boot, the call the homepage's first visitor makes, fills the column.
    def run():
        time.sleep(delay)
        try:
            _rates_payload(store.load_config(), "USD")
        except Exception as e:
            print("[rates] warm-up skipped: %s" % e, flush=True)

    threading.Thread(target=run, daemon=True).start()


def _warm_fx_history(delay=25):
    # The strength chart's 27 years of ECB rates (~2.7 MB, a few seconds):
    # fetched once after boot so the first Data-tab visitor doesn't wait on it.
    def run():
        time.sleep(delay)
        try:
            rates.get_history()
        except Exception as e:
            print("[fx-history] warm-up skipped: %s" % e, flush=True)

    threading.Thread(target=run, daemon=True).start()


# server.main() hands the GIL round every SWITCH_INTERVAL seconds, not
# CPython's 5 ms. A thread that does I/O (the accept loop, /healthz's
# handler) drops the GIL at each syscall and then waits up to a whole
# interval to get it back from a CPU-bound one (a background feed parse, page
# renders), and on Render's 0.1 CPU each of those waits stretches ~10x in
# wall time. Chosen by measurement (the largest value with no /healthz probe
# over 5 s and no error in any run), with the page slots scoped to
# server-rendered pages: stall_check at on_ms 5, two runs each, probes over
# 5 s (worst probe, s):
#
#   interval  adv_expired --crawl 30  fresh --crawl 30  adv_expired   cold --crawl 30
#   0.1 ms    0, 0 (3.5, 3.5)         0, 0 (1.9, 2.1)   0, 0 (1.4)    0, 0 (2.6, 1.8)
#   0.5 ms    2, 4 (6.1, 7.4)         0, 1 (4.0, 5.4)   0, 0 (1.4)    0, 0 (3.2, 3.5)
#   1 ms      8, 10 (10.1, 11.9)      0, 3 (4.7, 6.3)   0, 0 (1.5)    0, 0 (4.5, 3.7)
#   5 ms      32, 32 (all time out)   2, 3 (6.4, 6.9)   0, 0 (3.6)    30, 9 (16.8, 8.8)
#
# Its cost: process CPU for 60 guide renders by 8 clients while the lists
# refresh in the background (unthrottled, 3 runs): 0.79 s at 0.1 ms, 0.75 s
# at 0.5 and 1 ms, 0.74 s at 5 ms (+6%).
SWITCH_INTERVAL = 0.0001


class _Server(ThreadingHTTPServer):
    # socketserver's listen backlog is 5, and Linux drops connections past
    # it: while the advisory lists recomputed, a few page requests filled it
    # and Render's /healthz check timed out.
    request_queue_size = 128
    daemon_threads = True

    # One thread per connection, started without waiting for it to run.
    # threading.Thread.start() blocks until the new thread has run its first
    # lines, so the accept loop, which every waiting /healthz probe is queued
    # behind, paid two GIL hand-offs per connection (the new thread winning
    # the GIL, then the loop winning it back), each a wait behind every
    # runnable thread. With 34 requests arriving at once during an advisory
    # refresh (stall_check --scenario adv_expired --crawl 30 --on-ms 2) the
    # probes sat unaccepted for 10-14 s, the loop parked in select() unable to
    # get the GIL back: 9-18 probes over 5 s, worst 11.6-14.3 s; started
    # this way, 2 over 5 s, worst 6.2 s. The handler threads are daemon-like
    # as before (daemon_threads) and keep their thread-locals; nothing joins
    # them.
    def process_request(self, request, client_address):
        _thread.start_new_thread(self.process_request_thread, (request, client_address))


def main():
    # Port: CLI arg wins, else $PORT (hosting platforms set this), else 8000.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    # Bind localhost-only when run locally; bind all interfaces when a platform
    # provides $PORT (so the host can route traffic to the container).
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    if os.environ.get("RENDER"):   # set by Render; never self-ping from a laptop
        _keep_warm()
    # Each government's feed parsed once per refresh and shared by the three
    # lists that read it (fxtracker/advisories.py FEED_MEMO_TTL): off outside
    # the server, so the newsletter build and the tests parse as before.
    advisories.FEED_MEMO_TTL = 120
    sys.setswitchinterval(SWITCH_INTERVAL)
    global _page_slots, _page_memo
    _page_slots = threading.BoundedSemaphore(PAGE_SLOTS)
    _page_memo = collections.OrderedDict()
    # The guides' slugs, names and data (render_guide._load, six files, ~330
    # KB), loaded once here, before the first request: _redirect_only reads
    # them for every /guide/ request before it takes a slot, and the lazy
    # load has no lock, so the first burst on a fresh process (a deploy, or
    # Render's restart mid-crawl, as on Nov 18) parsed them once per request
    # in flight, outside the slots: stall_check --scenario nov18_scrape_all
    # --on-ms 2 saw 19-20 parses, and 14-26 probes over 5 s against main's
    # 6-12. A failure here is left to the requests, as before.
    try:
        render_guide._load()
        _og_cards()   # and the share cards' facts (one small file), for the same reason
    except Exception as e:
        sys.stderr.write("[boot] guide data not loaded: %r\n" % (e,))
    _warm_flight_value()
    _warm_rates()
    _warm_fx_history()
    # The three governments' lists, for the guides' "do not travel" marks
    # (_adv_dnt): nothing asked for them until a reader's /api/advisories, so
    # the first guide after a deploy went out not knowing Germany's Level 4
    # for Saudi Arabia (no-store, its stays held and then hidden).
    t = threading.Timer(10, _warm_adv_lists)
    t.daemon = True
    t.start()
    # Canada's health advice ages; the server rebuilds /health.json itself
    # once it's a week old (fxtracker/health.py). Render only, unless
    # HEALTH_REFRESH=1 — never from a laptop by accident.
    health.start_refresher()
    # The guide pages' titles, descriptions and lastmods quote a dated price
    # level and advisory; the server recomputes them daily from the same
    # cached rates, advisories and PPP table /api/rates, /api/advisories and
    # /ppp.json serve (fxtracker/guide_facts.py) — in-process, never over
    # HTTP to itself. Render only, unless GUIDE_FACTS_REFRESH=1.
    # The live World Bank table, not the committed one: start its refresh now
    # and hand the refresher nothing until that first attempt has finished
    # ("at" moves on success and failure alike), so a check that comes first
    # is kept and retried within the hour instead of moving figures twice on
    # every restart day.
    _ppp_data()
    guide_facts.start_refresher(
        get_rates=lambda: _rates_payload(store.load_config(), "USD"),
        get_advisories=lambda: _advisories_payload("us", background=True),
        get_ppp=lambda: _ppp_data() if _ppp_cache["at"] else None)
    # Two weeks of a log-only, once-a-day comparison of the fare source with
    # Travelpayouts' grouped_prices (fxtracker/flightshadow.py): Render only,
    # off the request path, reads the caches and writes only its own Upstash
    # keys; /api/flight-shadow shows what it has found.
    flightshadow.start(_cached_fares, busy=_flight_shadow_busy)
    # One-off after deploy: opt-outs from before they reached Buttondown (see
    # accounts.reconcile_optouts). Background, and a no-op without the
    # Buttondown/Upstash keys or once its done-marker is set.
    threading.Thread(target=accounts.reconcile_optouts, daemon=True).start()
    httpd = _Server((host, port), Handler)
    print("fx-tracker dashboard on {0}:{1}".format(host, port))
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
