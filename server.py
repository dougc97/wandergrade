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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fxtracker import advisories, flights, mailer, popularity, rates, render_guide, store

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
        "script-src 'self' 'unsafe-inline'; "
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
_HTML_DEFAULTS = {
    "TITLE": "WanderGrade — Where Should I Travel to Next?",
    "DESC": "Decide where — and when — to go. Every country graded A+ to F on "
            "prices, weather, safety, and flights. Free, no sign-up.",
    "OGTITLE": "Where Should I Travel to Next?",
    "URL": "https://wandergrade.com/",
    "OGIMAGE": "https://wandergrade.com/og.png",
    "GC_JS": "",
    "SSR_BODY": "",
    "JSONLD": _WEBSITE_JSONLD,
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


def _render_index(gc_iso=None):
    """Fill index.html's tokens. gc_iso=None -> homepage defaults; otherwise a
    country page with server-rendered <title>/meta/canonical and body."""
    vals = dict(_HTML_DEFAULTS)
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

    def _send_body(self, body, ctype, status=200, cache=None):
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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status=200):
        self._send_body(json.dumps(obj).encode("utf-8"),
                        "application/json; charset=utf-8", status)

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
            else "public, max-age=86400" if ext == ".geojson" \
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
        if not self._authed():
            return
        if PUBLIC_MODE:
            self._send_json({"error": "settings and email are disabled on the public site"}, 403)
            return
        path = self.path.split("?", 1)[0]
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


def main():
    # Port: CLI arg wins, else $PORT (hosting platforms set this), else 8000.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8000))
    # Bind localhost-only when run locally; bind all interfaces when a platform
    # provides $PORT (so the host can route traffic to the container).
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("fx-tracker dashboard on {0}:{1}".format(host, port))
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
