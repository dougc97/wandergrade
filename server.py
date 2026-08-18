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

import base64
import gzip
import hmac
import html
import json
import os
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fxtracker import (
    accounts, advisories, build_dataset, build_ppp, flights,
    mailer, popularity, rates, render_guide, store, watchouts
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
CACHE_TTL = 600  # seconds; FX reference rates update at most daily.
_cache = {"key": None, "at": 0, "data": None}
_index_cache = {}  # days -> (timestamp, payload)
_adv_cache = {}     # source -> (timestamp, payload)
ADV_TTL = 6 * 3600  # advisories change rarely; refresh a few times a day
_flights_cache = {}  # origin -> (timestamp, payload)
FLIGHTS_TTL = 3600   # cached fares are fine for an hour
_pop_cache = {"at": 0, "data": None}
POP_TTL = 7 * 24 * 3600   # tourist arrivals are annual; refresh weekly
_ppp_cache = {"at": 0, "data": None}
PPP_TTL = 30 * 24 * 3600  # PPP is annual data; a monthly re-check is plenty

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
}

# Sent on every response. The CSP allows our own assets plus the few external
# origins the app genuinely uses: the Stay22 map iframe, Wikipedia/Wikimedia
# image+API fetches, and inline <style>/<script> the page relies on. form-action
# is intentionally left unset so the newsletter form can POST to Buttondown.
SECURITY_HEADERS = {
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
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "connect-src 'self' https:; "
        "frame-src https://www.stay22.com https://stay22.com; "
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
    "GUIDE_LINKS": "",
    "JSONLD": _WEBSITE_JSONLD,
    "ANALYTICS": _analytics_tag(),
    # Lets the page hide every trace of sign-in until accounts are provisioned.
    "ACCOUNTS": "<script>window.__WGACCT__=%s</script>" % (
        "true" if accounts.enabled() else "false"),
}
_html_tpl = None


def _asset_version(name):
    """File mtime as a cache-busting token; changes exactly when a deploy does."""
    try:
        return str(int(os.path.getmtime(os.path.join(PUBLIC, name))))
    except OSError:
        return "0"


def _index_template():
    global _html_tpl
    if _html_tpl is None:
        with open(os.path.join(PUBLIC, "index.html"), encoding="utf-8") as f:
            tpl = f.read()
        # Stamp asset URLs with the file's mtime so browsers can cache them
        # long-term (see _send_file) yet always fetch fresh after a deploy.
        tpl = re.sub(r"/app\.js(\?v=\d+)?", "/app.js?v=" + _asset_version("app.js"), tpl)
        tpl = re.sub(r"/styles\.css(\?v=\d+)?", "/styles.css?v=" + _asset_version("styles.css"), tpl)
        _html_tpl = tpl
    return _html_tpl


_SITE = "https://wandergrade.com"   # canonical origin for sitemap URLs


_dataset_cache = {"at": 0, "payload": None, "csv": None}
_DATASET_TTL = 3600


def _dataset():
    """The public price-level dataset, rebuilt at most hourly.

    Building costs a rates fetch, so it is cached; if a rebuild fails we keep
    serving the last good copy rather than 503-ing a public data URL that other
    people may have wired into something.
    """
    now = time.time()
    if _dataset_cache["payload"] is None or now - _dataset_cache["at"] > _DATASET_TTL:
        try:
            payload = build_dataset.build(_ppp_data())
            _dataset_cache.update(at=now, payload=payload,
                                  csv=build_dataset.to_csv(payload))
        except Exception:
            if _dataset_cache["payload"] is None:
                raise
    return _dataset_cache


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
            try:
                base = _ppp_cache["data"] or {}
                live = build_ppp.build()
                # A truncated or partly-null API response must never quietly
                # shrink the number of gradeable countries.
                if live and len(live) >= max(1, int(len(base) * 0.9)):
                    _ppp_cache["data"] = live
                    _ppp_cache["at"] = time.time()
                    print("[ppp] refreshed: %d countries" % len(live))
                else:
                    _ppp_cache["at"] = time.time()   # don't hammer a bad upstream
                    print("[ppp] live fetch gave %d vs %d committed; keeping current"
                          % (len(live or {}), len(base)))
            except Exception as e:
                _ppp_cache["at"] = time.time()
                print("[ppp] live fetch failed (%s); keeping current" % e)
            finally:
                _ppp_cache["busy"] = False

        threading.Thread(target=refresh, daemon=True).start()
    return _ppp_cache["data"]


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
    mtimes = []
    for name in ("slugs.json", "climate.json", "activities.json",
                 "country-names.json", "visa.json"):
        try:
            mtimes.append(os.path.getmtime(os.path.join(PUBLIC, name)))
        except OSError:
            pass
    stamp = time.strftime("%Y-%m-%d", time.gmtime(max(mtimes) if mtimes else time.time()))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
           '  <url><loc>%s/</loc><lastmod>%s</lastmod></url>' % (_SITE, stamp),
           '  <url><loc>%s/data</loc><lastmod>%s</lastmod></url>' % (_SITE, stamp)]
    for slug, _iso in render_guide.all_slugs():
        out.append('  <url><loc>%s/guide/%s</loc><lastmod>%s</lastmod></url>'
                   % (_SITE, slug, stamp))
    out.append('</urlset>')
    return ("\n".join(out) + "\n").encode("utf-8")   # _send_body takes bytes


_DATA_TITLE = "Cost of Living by Country — Free CSV & JSON Dataset | WanderGrade"
_DATA_DESC = ("Free dataset: what US$100 buys in 173 countries, from World Bank PPP "
              "divided by today's market exchange rate. CSV and JSON, no sign-up.")


def _data_page_body():
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
        "<p>What US$100 buys in <strong>173 countries</strong>, as a free CSV or JSON "
        "download. No sign-up, no key, updated continuously.</p>"
        '<p><a href="/data/price-levels.csv"><strong>Download CSV</strong></a> &middot; '
        '<a href="/data/price-levels.json"><strong>Download JSON</strong></a></p>'
        "<h2>What's in it</h2>"
        "<ul>"
        "<li><strong>price_level</strong> — World Bank PPP conversion factor divided by "
        "the market exchange rate. 1.00 means prices match the US, 0.50 means half.</li>"
        "<li><strong>usd100_buys</strong> — the local purchasing power of US$100, in US "
        "dollars. Vietnam sits near $370.</li>"
        "<li>Plus the inputs, so you can check the arithmetic: PPP factor and its year, "
        "GDP per capita and its year, and the currency used.</li>"
        "</ul>"
        "<h2>Why it differs from other PPP tables</h2>"
        "<p>Most purchasing-power figures divide by an exchange rate fixed at the time "
        "the PPP was published, so they drift as currencies move. This divides by "
        "<em>today's</em> market rate, which is why a country whose currency has fallen "
        "shows up as cheaper here than in a year-old table.</p>"
        "<h2>What it is not</h2>"
        "<p>These are national averages for residents. Neighbourhoods popular with "
        "visitors, and rent paid by foreigners, run well above them — useful for "
        "comparing countries against each other, not as a travel budget.</p>"
        "<p>Countries whose exchange rate is a managed peg, or otherwise so far out of "
        "line with their income that the result would be fictional, are left out rather "
        "than guessed at. That is why the count is 173 and not every country on earth.</p>"
        "<h2>Sources and licence</h2>"
        "<p>PPP conversion factors and GDP per capita from the World Bank "
        "(<a href=\"https://data.worldbank.org\" rel=\"noopener\" target=\"_blank\">data.worldbank.org</a>, "
        "CC BY 4.0); exchange rates from "
        "<a href=\"https://fxratesapi.com\" rel=\"noopener\" target=\"_blank\">fxratesapi.com</a>. "
        "The derived figures are free to reuse with attribution to "
        "<a href=\"/\">WanderGrade</a>.</p>"
        "</div>"
    )


def _render_data_page():
    """A whole, self-contained HTML document for /data — no app.js."""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>%s</title>"
        '<meta name="description" content="%s">'
        '<link rel="canonical" href="%s/data">'
        '<meta property="og:title" content="Cost of Living by Country — Free Dataset">'
        '<meta property="og:description" content="%s">'
        '<meta property="og:url" content="%s/data">'
        '<link rel="stylesheet" href="/styles.css?v=%s">'
        "%s</head><body>"
        '<header><div class="headrow"><a class="homelink" href="/">'
        '<span class="brand">🌍 WanderGrade</span>'
        '<p class="sitetitle">Where Should I Travel to Next?</p>'
        '<p class="sub">Every country, graded A+ to F — free, no sign-up.</p>'
        "</a></div></header><main>%s</main>"
        '<footer>Data: <a href="https://data.worldbank.org" rel="noopener" '
        'target="_blank">World Bank</a> &amp; '
        '<a href="https://fxratesapi.com" rel="noopener" target="_blank">fxratesapi.com</a> '
        '&middot; <a href="/">Back to WanderGrade</a></footer></body></html>'
        % (html.escape(_DATA_TITLE), html.escape(_DATA_DESC, quote=True), _SITE,
           html.escape(_DATA_DESC, quote=True), _SITE,
           _asset_version("styles.css"), _analytics_tag(), _data_page_body())
    ).encode("utf-8")


def _render_index(gc_iso=None):
    """Fill index.html's tokens. gc_iso=None -> homepage defaults; otherwise a
    country page with server-rendered <title>/meta/canonical and body."""
    vals = dict(_HTML_DEFAULTS)
    vals["GUIDE_LINKS"] = _guide_links()
    if gc_iso:
        r = render_guide.render(gc_iso)
        vals.update(
            TITLE=html.escape(r["title"]),
            DESC=html.escape(r["desc"], quote=True),
            OGTITLE=html.escape(r["og_title"], quote=True),
            URL=html.escape(r["url"], quote=True),
            SSR_BODY=r["body"],                       # already-safe HTML
            GC_JS="<script>window.__WGGC__=%s;</script>" % json.dumps(gc_iso),
            JSONLD=r.get("jsonld", ""),               # FAQPage schema (raw JSON-LD)
            # Demoted so the country's own <h1> is the only one on the page.
            SITE_HEADING='<p class="sitetitle">Where Should I Travel to Next?</p>',
        )
        if r.get("ogimage"):                          # country hero photo
            vals["OGIMAGE"] = html.escape(r["ogimage"], quote=True)
    out = _index_template()
    for k, v in vals.items():
        out = out.replace("{{%s}}" % k, v)
    return out.encode("utf-8")


def _rates_payload(cfg, base="USD"):
    key = (cfg["baseline_days"], cfg["threshold_pct"], tuple(cfg["watch"]), base)
    now = time.time()
    if _cache["key"] == key and (now - _cache["at"]) < CACHE_TTL:
        return _cache["data"]
    data = rates.compute_favorability(
        baseline_days=cfg["baseline_days"],
        threshold_pct=cfg["threshold_pct"],
        watch=cfg["watch"],
        base=base,
    )
    _cache.update(key=key, at=now, data=data)
    return data


def _base_param(qs):
    """Validated ?base= currency code; anything dodgy falls back to USD."""
    base = (qs.get("base", ["USD"])[0] or "USD").strip().upper()
    return base if re.fullmatch(r"[A-Z]{3}", base) else "USD"


class Handler(BaseHTTPRequestHandler):
    # Generic identity — don't advertise the framework/Python version.
    server_version = "WanderGrade"
    sys_version = ""

    # ---- helpers ---------------------------------------------------------
    def _gzip_ok(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _send_body(self, body, ctype, status=200, cache=None, extra=None):
        """Send a response, gzipping text payloads over ~1KB when accepted.
        world.geojson alone drops ~163KB -> ~50KB, which matters most on
        Render free-tier cold starts."""
        encoding = None
        if len(body) > 1024 and self._gzip_ok() and not ctype.startswith("image/"):
            body = gzip.compress(body, 9)
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
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)   # HEAD: same status/headers, no body

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
        # HttpOnly so no script can read it; Lax survives the magic-link
        # click (a top-level GET from the email) but blocks cross-site POSTs.
        bits = [f"{self.SESS_COOKIE}={'' if clear else sid}", "Path=/", "HttpOnly",
                "SameSite=Lax", "Secure",
                "Max-Age=0" if clear else f"Max-Age={accounts.SESSION_TTL}"]
        return ("Set-Cookie", "; ".join(bits))

    def _handle_auth_verify(self):
        """The link target from the email: redeem once, then land on the map."""
        from urllib.parse import parse_qs, urlparse
        token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        try:
            email, sid = accounts.consume_token(token)
        except Exception:
            email, sid = None, None
        # Never echo the token back; ?signin= is just a UI hint.
        self.send_response(303)
        for hk, hv in SECURITY_HEADERS.items():
            self.send_header(hk, hv)
        if email:
            self.send_header(*self._set_session_cookie(sid))
        self.send_header("Location", "/?signin=" + ("ok" if email else "expired"))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_auth_post(self, path):
        if not accounts.enabled():
            self._send_json({"error": "accounts are not configured"}, 503)
            return
        body = self._read_body()
        if path == "/api/auth/request":
            origin = "https://" + (self.headers.get("Host") or "wandergrade.com")
            ip = (self.headers.get("CF-Connecting-IP")
                  or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                  or self.client_address[0])
            # The browser is always told "sent" — revealing whether an address
            # exists (or is throttled) would let anyone probe the user list. So
            # the server log is the ONLY place a real failure is visible.
            try:
                if not accounts.request_link(body.get("email", ""), origin, ip):
                    print("[accounts] link NOT sent: invalid address or rate limited",
                          flush=True)
            except Exception as e:
                print("[accounts] link send FAILED: %s" % e, flush=True)
            self._send_json({"sent": True})
            return
        email = self._session_email()
        if not email:
            self._send_json({"error": "not signed in"}, 401)
            return
        if path == "/api/auth/sync":
            user = accounts.sync_map(email, body.get("visited"), body.get("wishlist"))
            self._send_json({"user": accounts.public_user(user)})
        elif path == "/api/auth/prefs":
            user = accounts.set_prefs(email, body.get("subscribed"), body.get("cadence"))
            self._send_json({"user": accounts.public_user(user)})
        elif path == "/api/auth/logout":
            accounts.end_session(self._cookie(self.SESS_COOKIE))
            self._send_json({"ok": True}, extra=[self._set_session_cookie("", clear=True)])
        else:
            self._send_json({"error": "not found"}, 404)

    def _send_file(self, path, versioned=False):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(path)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        # ?v=<mtime>-stamped assets (the template rewrites app.js/styles.css)
        # can cache forever — the URL itself changes on deploy. geojson is
        # effectively static; other data files change with deploys, so keep
        # their staleness window short (10 min) to not mask fresh releases.
        cache = "public, max-age=31536000, immutable" if versioned \
            else "public, max-age=86400" if ext in (".geojson", ".mp3") \
            else "public, max-age=600" if ext == ".json" \
            else "public, max-age=300"
        self._send_body(body, ctype, cache=cache)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("  %s\n" % (fmt % args))

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

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        # Unauthenticated health check for hosting platforms (Render, etc.).
        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        # Canonical-domain redirect: bounce the old *.onrender.com host to the
        # custom domain so links and SEO consolidate on one host. /healthz above
        # is exempt so Render's health checks are unaffected. Requests already on
        # wandergrade.com don't match and serve normally.
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
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
            try:
                self._send_json(_rates_payload(store.load_config(), base))
            except Exception as e:  # network/provider hiccup or unknown base
                self._send_json({"error": str(e)}, 502)
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
            if not dest and iso:
                now = time.time()
                hit = _flights_cache.get(origin)
                payload = hit[1] if hit and (now - hit[0]) < FLIGHTS_TTL else None
                if payload is None:
                    try:
                        payload = flights.get_flights(origin)
                        if payload.get("configured"):
                            _flights_cache[origin] = (now, payload)
                    except Exception:
                        payload = None
                if payload:
                    row = next((r for r in payload.get("countries", []) if r.get("iso") == iso), None)
                    if row:
                        # Merge across the country's top cached cities — one
                        # secondary city rarely has a full year of months.
                        cities = row.get("cities") or ([row["dest"]] if row.get("dest") else [])
                        self._send_json(flights.get_monthly_multi(origin, cities))
                        return
            self._send_json(flights.get_monthly(origin, dest))
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
            self._send_json(watchouts.get_watchouts(iso))
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
            self._send_body(_render_index(None), "text/html; charset=utf-8",
                            cache="public, max-age=300")
            return
        if path.startswith("/guide/"):
            slug = path[len("/guide/"):].strip("/").lower()
            iso = render_guide.iso_for_slug(slug)
            if iso:
                self._send_body(_render_index(iso), "text/html; charset=utf-8",
                                cache="public, max-age=300")
            else:
                self._send_json({"error": "country not found"}, 404)
            return
        if path == "/sitemap.xml":
            self._send_body(_sitemap(), "application/xml; charset=utf-8",
                            cache="public, max-age=3600")
            return
        if path in ("/data", "/data/"):
            self._send_body(_render_data_page(), "text/html; charset=utf-8",
                            cache="public, max-age=300")
            return
        if path == "/ppp.json":
            self._send_json(_ppp_data(), extra=[("Cache-Control", "public, max-age=86400")])
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
        # static files
        rel = path.lstrip("/")
        safe = os.path.normpath(os.path.join(PUBLIC, rel))
        if not safe.startswith(PUBLIC):
            self._send_json({"error": "forbidden"}, 403)
            return
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

    def _handle_index(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        try:
            days = int(qs.get("days", ["365"])[0])
        except ValueError:
            days = 365
        days = max(30, min(3650, days))
        base = _base_param(qs)
        now = time.time()
        hit = _index_cache.get((days, base))
        if hit and (now - hit[0]) < CACHE_TTL:
            self._send_json(hit[1])
            return
        try:
            payload = rates.compute_index(days, base)
        except Exception as e:
            self._send_json({"error": str(e)}, 502)
            return
        _index_cache[(days, base)] = (now, payload)
        self._send_json(payload)

    def _handle_flights(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        # origin is an ISO-2 country code (aggregated to that country's hub)
        origin = (qs.get("origin", ["US"])[0] or "US").strip().upper()[:2]
        now = time.time()
        hit = _flights_cache.get(origin)
        if hit and (now - hit[0]) < FLIGHTS_TTL:
            self._send_json(hit[1])
            return
        try:
            data = flights.get_flights(origin)
        except Exception as e:
            self._send_json({"error": str(e)}, 502)
            return
        if data.get("configured"):
            _flights_cache[origin] = (now, data)
        self._send_json(data)

    def _handle_advisories(self):
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        source = (qs.get("source", ["us"])[0] or "us").strip().lower()
        if source not in advisories.SOURCES:
            source = "us"
        now = time.time()
        hit = _adv_cache.get(source)
        if hit and (now - hit[0]) < ADV_TTL:
            self._send_json(hit[1])
            return
        try:
            data = advisories.get_advisories(source)
        except Exception as e:
            self._send_json({"error": str(e)}, 502)
            return
        _adv_cache[source] = (now, data)
        self._send_json(data)

    def _handle_popularity(self):
        now = time.time()
        if _pop_cache["data"] and (now - _pop_cache["at"]) < POP_TTL:
            self._send_json(_pop_cache["data"])
            return
        try:
            data = {"arrivals": popularity.get_arrivals()}
        except Exception as e:
            self._send_json({"error": str(e), "arrivals": {}}, 502)
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
        _cache["key"] = None  # force recompute next fetch
        out = store.load_config()
        out["email"] = _redact_email(out["email"])
        self._send_json({"ok": True, "config": out})

    def _handle_check(self):
        cfg = store.load_config()
        try:
            data = _rates_payload(cfg)
        except Exception as e:
            self._send_json({"error": str(e)}, 502)
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


def main():
    # Port: CLI arg wins, else $PORT (hosting platforms set this), else 8000.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    # Bind localhost-only when run locally; bind all interfaces when a platform
    # provides $PORT (so the host can route traffic to the container).
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    if os.environ.get("RENDER"):   # set by Render; never self-ping from a laptop
        _keep_warm()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("fx-tracker dashboard on {0}:{1}".format(host, port))
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
