#!/usr/bin/env python3
"""/privacy (fxtracker/render_privacy.py) and its links, in-process: no
network, no server of its own beyond a loopback one for the route.

    /usr/bin/python3 scripts/test_privacy.py

What it holds the code to:
  * the route: GET /privacy is 200 text/html, cached like the list pages,
    sets no cookie; HEAD answers the same with no body; /privacy/ 301s to it;
    the sitemap lists it dated by its own "Last updated", and llms.txt
    links it;
  * the page: one h1, title and description in the list pages' limits, HTML
    that html.parser accepts, every section there, the last-updated date,
    the contact address, no "Airbnb", no class an ad blocker would hide;
  * the page names every third-party host the site's pages load, computed
    here from the code and the served HTML, not typed by hand: each external
    <script>/<link>/<img>/<iframe> in the homepage, guides, the shell pages
    and /privacy itself (served with an analytics token set), each host
    app.js fetches or loads images from by a literal URL, and the hosts of
    the guides' hero photos (public/og-images.json, the same Wikipedia lead
    images the guide loads), and each host the newsletter's images come
    from (newsletter.py's <img> literals, picks.cover()'s photo proxy);
  * it makes no claim the code breaks: not "no tracking cookies" (the
    Wikimedia photos set a year-long ID cookie, which the page names), not
    "everything that leaves"; and the server log it describes keeps a
    sign-in link's one-time token out;
  * it names each partner app.js links to with a partner ID, each AI site
    the guide's buttons open, the services accounts.py hands an email to, and
    the one cookie server.py sets;
  * the footer: the homepage links /privacy; every guide doesn't, and renders
    byte-identical to the same template with the {{FOOTER_PRIVACY}} token
    taken out (the Search Console freeze on /guide/* until November 2026);
    the shell pages (/data, the lists, 404) link it.
"""
import html.parser
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# A public-format token so the served HTML carries the beacon, as production's
# does (server.py fills ANALYTICS at import).
os.environ["CF_ANALYTICS_TOKEN"] = "0123456789abcdef0123456789abcdef"
from fxtracker import llms_txt, render_guide as rg, render_privacy as RP  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
SERVER_SRC = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
ACCOUNTS_SRC = open(os.path.join(ROOT, "fxtracker", "accounts.py"), encoding="utf-8").read()
NEWS_SRC = open(os.path.join(ROOT, "fxtracker", "newsletter.py"), encoding="utf-8").read()
PICKS_SRC = open(os.path.join(ROOT, "fxtracker", "picks.py"), encoding="utf-8").read()
OWN = {"wandergrade.com", "www.wandergrade.com", "localhost", "127.0.0.1"}

page = RP.privacy()
body = page["html"]
served = server._render_privacy_page().decode("utf-8")
text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))

# --- the route ------------------------------------------------------------------------
_real_log = server.Handler.log_message
server.Handler.log_message = lambda self, *a: None   # no request lines in the test's output
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
        with opener.open(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


st, hd, raw = get("/privacy")
results.append(ok(st == 200 and hd.get("Content-Type") == "text/html; charset=utf-8"
                  and hd.get("Cache-Control") == "public, max-age=300" and "Set-Cookie" not in hd
                  and raw.decode("utf-8") == served,
                  "GET /privacy: 200 text/html; charset=utf-8, public max-age=300, no cookie (%s %s %s)"
                  % (st, hd.get("Content-Type"), hd.get("Cache-Control"))))
st2, hd2, raw2 = get("/privacy", "HEAD")
results.append(ok(st2 == 200 and raw2 == b"" and hd2.get("Content-Type") == hd.get("Content-Type"),
                  "HEAD /privacy: the same status and type, no body"))
st3, hd3, _ = get("/privacy/?utm_source=x")
results.append(ok(st3 == 301 and hd3.get("Location") == "/privacy?utm_source=x",
                  "/privacy/ 301s to /privacy, query kept (%s %s)" % (st3, hd3.get("Location"))))
st4, hd4, home_raw = get("/")
home = home_raw.decode("utf-8")
httpd.shutdown()

sm = server._sitemap().decode("utf-8")
results.append(ok("<loc>https://wandergrade.com/privacy</loc><lastmod>%s</lastmod>" % RP.UPDATED in sm,
                  "the sitemap lists /privacy at its own last-updated date %s" % RP.UPDATED))
txt = llms_txt.build(rg.all_slugs(), rg.name_for_iso)
results.append(ok("(https://wandergrade.com/privacy)" in txt, "llms.txt links /privacy"))

# --- the page ---------------------------------------------------------------------------
class Check(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1 = 0
        self.classes = []

    def handle_starttag(self, tag, attrs):
        self.h1 += tag == "h1"
        for k, v in attrs:
            if k in ("class", "id") and v:
                self.classes += v.split()


c = Check()
try:
    c.feed(served)
    parsed = True
except Exception:
    parsed = False
results.append(ok(parsed and c.h1 == 1, "html.parser accepts the served page; exactly one h1 (%d)" % c.h1))
results.append(ok(len(page["title"]) <= 60 and len(page["desc"]) <= 157 and "<title>Privacy | WanderGrade</title>" in served
                  and ('<link rel="canonical" href="https://wandergrade.com/privacy">' in served),
                  "title (%d) and description (%d) in the list pages' limits; canonical /privacy"
                  % (len(page["title"]), len(page["desc"]))))
bad = [k for k in c.classes if re.match(r"(ad|adv|sponsor|banner|promo)", k) or "advert" in k]
results.append(ok(not bad, "no class or id an ad blocker would hide (%s)" % bad))
SECTIONS = ["device", "analytics", "country", "account", "newsletter", "partners", "content", "ai",
            "sharing", "hosting", "never", "rights", "contact"]
missing = [s for s in SECTIONS if '<section id="%s">' % s not in body]
results.append(ok(not missing, "every section is there (missing: %s)" % missing))
results.append(ok("Last updated 21 October 2026" in text and RP.UPDATED == "2026-10-21",
                  "the last-updated date reads 21 October 2026"))
results.append(ok(body.count('href="mailto:hello@wandergrade.com"') >= 3, "hello@wandergrade.com, as a mailto link"))
results.append(ok(body.count('<!--email_off--><a href="mailto:hello@wandergrade.com">hello@wandergrade.com</a><!--/email_off-->')
                  == body.count("mailto:") and "[email" not in body,
                  "every mailto link sits inside Cloudflare's email_off markers (no \"[email protected]\" without JS)"))
results.append(ok("airbnb" not in served.lower(), "no Airbnb anywhere on the page"))
for words in ["No ads", "nothing sold", "no cookie from WanderGrade unless you sign in", "never sell",
              "unsubscribe", "commission", "GDPR", "delete", "local storage", "no password", "WMF-Uniq",
              "sign out every device", "marked as visited", "Gmail", "a.nel.cloudflare.com", "Postmark"]:
    results.append(ok(words.lower() in text.lower(), "says “%s”" % words))
claims = [w for w in ["no tracking cookies", "everything that leaves", "nothing about you"]
          if w in (text + " " + page["desc"]).lower()]
results.append(ok(not claims, "no claim the code breaks (found: %s)" % claims))

# The log the Hosting section describes: the request line, with a sign-in
# link's token taken out (Render keeps the log).
import io  # noqa: E402
_err, sys.stderr = sys.stderr, io.StringIO()
try:
    _real_log(server.Handler, '"%s" %s %s', "GET /auth/verify?t=SECRETtoken_123 HTTP/1.1", "200", "-")
    _real_log(server.Handler, '"%s" %s %s', "GET /?tab=value&vo=GB HTTP/1.1", "200", "-")
    logged = sys.stderr.getvalue()
finally:
    sys.stderr = _err
results.append(ok("SECRETtoken" not in logged and "/auth/verify?t=[redacted] HTTP/1.1" in logged
                  and "/?tab=value&vo=GB" in logged,
                  "the server log drops a sign-in token and keeps other addresses whole"))

# --- third-party hosts, computed ------------------------------------------------------------
RES_TAG = re.compile(r"<(script|link|img|iframe|source|video|audio)\b[^>]*?\b(?:src|href)=[\"']([^\"']+)[\"']", re.I)


def resource_hosts(doc):
    out = set()
    for tag, url in RES_TAG.findall(doc):
        h = urlsplit(url).hostname if url.startswith(("http://", "https://", "//")) else None
        if h and h not in OWN:
            out.add(h)
    return out


GUIDES = ["JP", "PH", "LK", "PT", "ET", "BF", "US", "GB-ENG"]
guides = {iso: server._render_index(iso).decode("utf-8") for iso in GUIDES}
shell = server._shell_page("t", "<p>x</p>").decode("utf-8")
from_html = set()
for doc in [home, served, shell] + list(guides.values()):
    from_html |= resource_hosts(doc)
# app.js: a URL literal on a line that fetches it or loads it as an image.
from_app = set()
for line in APP.splitlines():
    if re.search(r"fetch\(|\bapi = |new Image|\.src = ", line):
        from_app |= {h for h in re.findall(r"[\"'`]https://([a-z0-9.-]+)", line) if h not in OWN}
# The newsletter: hosts in its <img> literals, and the photo proxy picks.cover() builds.
from_mail = {h for line in NEWS_SRC.splitlines() if "<img" in line
             for h in re.findall(r"https://([a-z0-9.-]+)", line)}
cover_src = re.search(r"^def cover\(.*?^def ", PICKS_SRC, re.M | re.S)
from_mail |= set(re.findall(r'"url": \("https://([a-z0-9.-]+)', cover_src.group(0) if cover_src else ""))
results.append(ok({"flagcdn.com", "images.weserv.nl"} <= from_mail,
                  "the computed list finds the newsletter's image hosts (%s)" % sorted(from_mail)))
og = json.load(open(os.path.join(ROOT, "public", "og-images.json"), encoding="utf-8"))
from_photos = {urlsplit(u).hostname for u in og.values() if isinstance(u, str) and u.startswith("https://")}
hosts = from_html | from_app | from_photos | from_mail
results.append(ok({"static.cloudflareinsights.com"} <= from_html and {"en.wikipedia.org", "commons.wikimedia.org"} <= from_app
                  and "upload.wikimedia.org" in from_photos,
                  "the computed lists find the beacon, the Wikipedia APIs and the photo hosts (%s)" % sorted(hosts)))
unnamed = sorted(h for h in hosts if h not in text)
results.append(ok(not unnamed, "every third-party host the pages load is named on the page (%d; unnamed: %s)"
                  % (len(hosts), unnamed)))

# --- partners, AI sites, services, the cookie ---------------------------------------------
# A link with a partner ID in app.js: marker=, aid, pid= or a tp.media redirect.
BRANDS = {"www.aviasales.com": ["Aviasales", "Travelpayouts"], "www.stay22.com": ["Stay22"],
          "www.viator.com": ["Viator"], "tp.media": ["Travelpayouts", "EKTA"]}
partner_hosts = set()
for fn in ["flightSearchURL", "viatorURL", "insuranceHref", "renderGuideStay"]:
    m = re.search(r"^function %s\(.*?^\}" % fn, APP, re.M | re.S)
    if m:
        partner_hosts |= set(re.findall(r"\"https://([a-z0-9.-]+)/", m.group(0)))
results.append(ok(partner_hosts and partner_hosts <= set(BRANDS),
                  "every partner-link host in app.js has a name to look for (%s)" % sorted(partner_hosts)))
stays = set(re.findall(r"stay22\.com/allez/([a-z]+)\?", APP))
names = sorted({n for h in partner_hosts for n in BRANDS.get(h, [h])}
               | {{"booking": "Booking.com", "vrbo": "Vrbo"}.get(s, s) for s in stays} | {"Hostelworld"})
results.append(ok(all(n in text for n in names), "names the partners: %s (missing: %s)"
                  % (", ".join(names), [n for n in names if n not in text])))
ai = re.findall(r'\{ name: "([^"]+)", q: "https://', APP)
results.append(ok(len(ai) >= 4 and all(n in text for n in ai), "names every AI button's site: %s" % ", ".join(ai)))
svc = {"api.resend.com": "Resend", "api.buttondown.email": "Buttondown"}
found = set(re.findall(r"\"https://([a-z0-9.-]+)/", ACCOUNTS_SRC))
results.append(ok(found <= set(svc) and all(svc[h] in text for h in found)
                  and ("UPSTASH_REDIS_REST_URL" not in ACCOUNTS_SRC or "Upstash" in text),
                  "names the services accounts.py hands an email to (%s + Upstash)" % sorted(found)))
cookie = re.findall(r'SESS_COOKIE = "([^"]+)"', SERVER_SRC)
results.append(ok(cookie and cookie[0] in text and SERVER_SRC.count('"Set-Cookie"') == 1,
                  "names the one cookie server.py sets (%s)" % cookie))

# --- the footer ---------------------------------------------------------------------------
LINK = '<a href="/privacy">Privacy</a>'
foot = home[home.find("<footer>"):home.find("</footer>")]
results.append(ok(st4 == 200 and LINK in foot and "{{" not in home, "the homepage's footer links /privacy"))
results.append(ok(all("/privacy" not in g and "{{FOOTER_PRIVACY}}" not in g for g in guides.values()),
                  "no guide carries the link or the bare token (%s)" % ", ".join(GUIDES)))
# The same guides from the template with the token taken out: byte for byte.
tpl_now, gtpl_now = server._index_template(), server._guide_template()
try:
    server._html_tpl = tpl_now.replace("{{FOOTER_PRIVACY}}", "")
    server._guide_tpl = None
    without = {iso: server._render_index(iso).decode("utf-8") for iso in GUIDES}
finally:
    server._html_tpl, server._guide_tpl = tpl_now, gtpl_now
same = [iso for iso in GUIDES if without[iso] == guides[iso]]
results.append(ok(len(same) == len(GUIDES) and tpl_now.count("{{FOOTER_PRIVACY}}") == 1,
                  "every guide is byte-identical to the token-less template's (%d of %d)" % (len(same), len(GUIDES))))
results.append(ok(LINK in shell and LINK in server._render_404_page("x").decode("utf-8"),
                  "the shell pages' footer (/data, the lists, 404) links /privacy"))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
