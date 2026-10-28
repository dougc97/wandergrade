#!/usr/bin/env python3
"""The homepage's app-style guide links (/?tab=guide&gc=ZA) 301 to the guide
page (server._guide_query_redirect), in-process: no network, no server of
its own beyond a loopback one for the route.

    /usr/bin/python3 scripts/test_guide_query_redirect.py

What it holds the code to:
  * the rule: tab=guide and a gc code the app opens (app.js GC_RE, the same
    pattern here), read as URLSearchParams.get reads them (percent and "+"
    decoded, the first value wins), with a guide page; every other pair kept
    byte for byte and in order, tab and gc dropped, empty pairs dropped;
  * what stays the homepage: no tab or another tab, a lowercase or malformed
    code, a country with no guide (Malta), an ai= link (only a ?gc= landing
    opens the Plan with AI panel), no query at all;
  * every one of the 190 guides: /?tab=guide&gc=<its code> -> /guide/<slug>;
  * the links that make these URLs: newsletter._guide_url for the USD
    edition and a vo= edition lands on the guide with vmn (and vo) kept, and
    app.js guidePath still builds the form the rule reads;
  * the route: 301 with the Location, public max-age=3600, no body, the
    security headers; HEAD the same; the Location answers 200 with the
    guide's own canonical; "/" and the homepage URLs above stay 200 with
    the homepage's bytes.
"""
import os
import re
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import newsletter, render_guide as rg  # noqa: E402
from fxtracker.digest_variants import VARIANTS  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
R = server._guide_query_redirect
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()

# --- the rule ---------------------------------------------------------------------------
CASES = [
    ("/?tab=guide&gc=ZA", "/guide/south-africa"),
    ("/?tab=guide&gc=BH", "/guide/bahrain"),
    ("/?gc=TH&tab=guide&vmn=3", "/guide/thailand?vmn=3"),
    ("/?tab=guide&gc=AR&vmn=11&utm_source=wandergrade&utm_medium=email&utm_campaign=jan-2027",
     "/guide/argentina?vmn=11&utm_source=wandergrade&utm_medium=email&utm_campaign=jan-2027"),
    ("/?tab=guide&gc=FR&vmn=1&vo=DE", "/guide/france?vmn=1&vo=DE"),
    ("/?tab=guide&gc=JP&vmf=1", "/guide/japan?vmf=1"),
    ("/?tab=guide&gc=GB-SCT", "/guide/scotland"),
    ("/?tab=guide&gc=GB-ENG&vmn=6", "/guide/england?vmn=6"),
    ("/?tab=guide&gc=GB", "/guide/united-kingdom"),
    ("/?tab=guid%65&gc=Z%41", "/guide/south-africa"),            # decoded, as URLSearchParams does
    ("/?t%61b=guide&g%63=ZA", "/guide/south-africa"),            # keys too
    ("/?tab=guide&gc=ZA&g%63=BH&vmn=2", "/guide/south-africa?vmn=2"),   # an encoded second gc dropped, not handed on
    ("/?tab=guide&gc=ZA&gc=BH", "/guide/south-africa"),          # the first gc, every gc dropped
    ("/?tab=guide&tab=data&gc=ZA", "/guide/south-africa"),       # the first tab
    ("/?tab=guide&&gc=ZA&&vmn=2&", "/guide/south-africa?vmn=2"),
    ("/?tab=guide&gc=ZA&utm_campaign=a+b%20c&x", "/guide/south-africa?utm_campaign=a+b%20c&x"),
    ("/?tab=guide&gc=ZA&ai=", "/guide/south-africa?ai="),       # an empty ai opens nothing on either page
]
STAY = [
    "/", "/?", "/?tab=value", "/?gc=ZA", "/?tab=data&gc=ZA", "/?tab=Guide&gc=ZA",
    "/?tab=guide", "/?tab=guide&gc=", "/?tab=guide&gc=za", "/?tab=guide&gc=ZAF",
    "/?tab=guide&gc=GB-sct", "/?tab=guide&gc=ZA%0D%0ALocation:%20x", "/?tab=guide&gc=ZA%20",
    "/?tab=guide&gc=MT", "/?tab=guide&gc=MT&vmf=1", "/?tab=guide&gc=XX",
    "/?tab=guide&gc=JP&vmn=10&ai=1", "/?ai=1&tab=guide&gc=JP", "/?tab=guide&gc=JP&a%69=1",
]
bad = [(u, R(u), want) for u, want in CASES if R(u) != want]
results.append(ok(not bad, "%d guide links 301 to their guide, the rest of the query kept in order: %s"
                  % (len(CASES), bad or "all")))
bad = [(u, R(u)) for u in STAY if R(u) is not None]
results.append(ok(not bad, "%d other homepage URLs stay the homepage: %s" % (len(STAY), bad or "all")))

slugs = rg.all_slugs()
miss = [(sl, iso, R("/?tab=guide&gc=" + iso)) for sl, iso in slugs if R("/?tab=guide&gc=" + iso) != "/guide/" + sl]
results.append(ok(len(slugs) == 190 and not miss and len({iso for _, iso in slugs}) == len(slugs),
                  "every guide's code 301s to its own slug (%d guides, misses %s)" % (len(slugs), miss or "none")))

# The same codes as the app: GC_RE's literal in app.js is the server's pattern.
m = re.search(r"const GC_RE = /\^(.+?)\$/;", APP)
results.append(ok(bool(m) and m.group(1) == server._GC_RE.pattern,
                  "server._GC_RE is app.js GC_RE (%s vs %s)" % (server._GC_RE.pattern, m and m.group(1))))
# The form app.js builds before slugs.json loads, and the ai= rule's reason.
results.append(ok('"/?tab=guide&gc=" + encodeURIComponent(iso)' in APP
                  and 'if (sharedQ.get("ai")) openGuideAI(gc);' in APP,
                  "app.js guidePath still builds /?tab=guide&gc=, and ai= still opens only from a ?gc= landing"))

# --- the links that make them ---------------------------------------------------------------
usd = newsletter._guide_url("AR", 11)
eur = next(v for v in VARIANTS.values() if v.code != "USD")
ed = newsletter._guide_url("FR", 1, eur)
results.append(ok(usd == "https://wandergrade.com/?tab=guide&gc=AR&vmn=11"
                  and R(usd[len(newsletter.SITE):]) == "/guide/argentina?vmn=11"
                  and R(ed[len(newsletter.SITE):]) == "/guide/france?vmn=1&vo=" + eur.home_iso,
                  "the newsletter's guide links land on the guide with vmn (and vo) kept: %s -> %s, %s -> %s"
                  % (usd, R(usd[len(newsletter.SITE):]), ed, R(ed[len(newsletter.SITE):]))))

# --- the route ----------------------------------------------------------------------------
server.Handler.log_message = lambda self, *a: None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def get(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


link = "/?tab=guide&gc=ZA&vmn=11&utm_source=wandergrade&utm_medium=email"
st, hd, raw = get(link)
sec = all(hd.get(k) == v for k, v in server.SECURITY_HEADERS.items())
results.append(ok(st == 301 and hd.get("Location") == "/guide/south-africa?vmn=11&utm_source=wandergrade&utm_medium=email"
                  and hd.get("Cache-Control") == "public, max-age=3600" and hd.get("Content-Length") == "0"
                  and raw == b"" and sec,
                  "GET %s: 301 to the guide, public max-age=3600, Content-Length 0, security headers (%s %s %s)"
                  % (link, st, hd.get("Location"), hd.get("Cache-Control"))))
# http.client reads no body for HEAD whatever is sent, so the headers are what's checked.
st2, hd2, _ = get(link, "HEAD")
results.append(ok(st2 == 301 and hd2.get("Location") == hd.get("Location") and hd2.get("Content-Length") == "0"
                  and hd2.get("Cache-Control") == "public, max-age=3600"
                  and all(hd2.get(k) == v for k, v in server.SECURITY_HEADERS.items()),
                  "HEAD answers the same 301: Location, Content-Length 0, cache and security headers"))
st3, hd3, raw3 = get(hd.get("Location") or "/guide/south-africa")
results.append(ok(st3 == 200 and '<link rel="canonical" href="https://wandergrade.com/guide/south-africa">'
                  in raw3.decode("utf-8"),
                  "the Location answers 200 with the guide's own canonical (%s)" % st3))
_, _, home = get("/")
kept = {u: get(u) for u in ("/?tab=guide&gc=MT", "/?tab=guide&gc=JP&vmn=10&ai=1", "/?tab=guide&gc=za", "/?tab=value")}
bad = [(u, s) for u, (s, h, b) in kept.items() if s != 200 or b != home]
results.append(ok(not bad, "/ and the homepage URLs above answer 200 with the homepage's bytes: %s" % (bad or "all")))
httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
