"""End-to-end exercise of the passwordless accounts flow, with no real
credentials: storage points at scripts/mock_upstash.py and mail is captured
in-process instead of sent, so the magic link can be followed. Buttondown
calls are captured the same way, and the HTTP half runs server.py's handler
in-process on a free port — nothing leaves this machine.

    python3 scripts/mock_upstash.py &        # in one shell
    python3 scripts/test_accounts.py         # in another
"""
import json, os, sys, threading, time, urllib.error, urllib.request

os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:8899"
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock"
os.environ["RESEND_API_KEY"] = "mock"
os.environ.pop("BUTTONDOWN_API_KEY", None)   # don't touch the real newsletter
os.environ.pop("SITE_ORIGIN", None)
os.environ.pop("MAIL_DAILY_CAP", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fxtracker import accounts

SENT = []
accounts._send_mail = lambda to, subject, html: (SENT.append((to, html)), True)[1]

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

print("accounts.enabled():", accounts.enabled())
results.append(ok(accounts.enabled(), "enabled() true when configured"))

# --- request a link ---------------------------------------------------------
results.append(ok(accounts.request_link("Doug@Example.COM ", "1.2.3.4"),
                  "request_link accepted"))
to, html = SENT[-1]
results.append(ok(to == "doug@example.com", "email normalised (case/space) -> " + to))
token = html.split("/auth/verify?t=")[1].split('"')[0]
results.append(ok(len(token) > 20, "magic link contains a token"))
results.append(ok('href="https://wandergrade.com/auth/verify?t=' in html,
                  "link built on SITE_ORIGIN default, never the request Host"))
os.environ["SITE_ORIGIN"] = "http://localhost:8000/"
accounts.request_link("origin@example.com", "1.2.3.4")
results.append(ok('href="http://localhost:8000/auth/verify?t=' in SENT[-1][1], "SITE_ORIGIN honoured"))
os.environ.pop("SITE_ORIGIN")

# --- bad addresses rejected -------------------------------------------------
results.append(ok(not accounts.request_link("nope", "1.2.3.4"), "invalid email rejected"))

# --- redeem -----------------------------------------------------------------
email, sid = accounts.consume_token(token)
results.append(ok(email == "doug@example.com" and bool(sid), "token redeems -> session"))
again, sid2 = accounts.consume_token(token)
results.append(ok(again is None and sid2 is None, "token is SINGLE-USE (replay refused)"))
results.append(ok(accounts.session_email(sid) == "doug@example.com", "session resolves to email"))
results.append(ok(accounts.consume_token("garbage") == (None, None), "garbage token refused"))

# --- account created with sane defaults -------------------------------------
u = accounts.get_user(email)
results.append(ok(u and u["cadence"] == "monthly" and u["subscribed"] is False and u["visited"] == [],
                  "first sign-in creates blank account, defaults sane"))

# --- sync + input sanitising -------------------------------------------------
u = accounts.sync_map(email, ["JP", "US", "GB-SCT", "<script>", "toolong", "jp"], ["BR", "BR"])
results.append(ok(u["visited"] == ["GB-SCT", "JP", "US"], "sync keeps valid ISO/subdivision, drops junk -> " + str(u["visited"])))
results.append(ok(u["wishlist"] == ["BR"], "wishlist dedupes"))
results.append(ok(accounts.get_user(email)["visited"] == ["GB-SCT", "JP", "US"], "map persisted to store"))
big = accounts.sync_map(email, ["JP"] * 5000, [])
results.append(ok(len(big["visited"]) == 1, "flood of dupes collapses (no unbounded growth)"))

# --- prefs / cadence, mirrored to Buttondown ----------------------------------
# The newsletter goes to the whole Buttondown list, so an opt-out that never
# reaches Buttondown is no opt-out at all.
BD = []
accounts._buttondown = lambda method, url, key, payload=None, extra=None: (
    BD.append((method, url, payload, extra or {})), 200)[1]
os.environ["BUTTONDOWN_API_KEY"] = "mock"
u = accounts.set_prefs(email, subscribed=False, cadence="off")
results.append(ok(BD == [], "first-time 'no newsletter' makes no Buttondown call (not an opt-out)"))
u = accounts.set_prefs(email, subscribed=True, cadence="monthly")
results.append(ok(u["subscribed"] is True and u["cadence"] == "monthly", "prefs saved (subscribe + monthly)"))
results.append(ok(len(BD) == 1 and BD[-1][0] == "POST" and BD[-1][2]["email_address"] == email
                  and BD[-1][3].get("X-Buttondown-Collision-Behavior") == "add",
                  "subscribe upserts the Buttondown subscriber"))
u = accounts.set_prefs(email, cadence="quarterly")
results.append(ok(u["cadence"] == "monthly", "retired 'quarterly' reads as monthly"))
u = accounts.set_prefs(email, cadence="bogus")
results.append(ok(u["cadence"] == "monthly", "invalid cadence ignored (kept monthly)"))
BD.clear()
u = accounts.set_prefs(email, subscribed=False, cadence="off")
results.append(ok(u["cadence"] == "off" and u["subscribed"] is False, "unsubscribe -> off"))
results.append(ok(len(BD) == 1 and BD[-1][0] == "PATCH" and BD[-1][1].endswith("/subscribers/" + email)
                  and BD[-1][2] == {"type": "unsubscribed"},
                  "opting out marks the Buttondown subscriber unsubscribed"))
BD.clear()
accounts.set_prefs(email, subscribed=True, cadence="off")
results.append(ok(BD == [], "subscribed but cadence off still sends nothing (already out)"))
os.environ.pop("BUTTONDOWN_API_KEY")
results.append(ok(accounts.public_user({"cadence": "quarterly", "subscribed": True})["cadence"] == "monthly",
                  "legacy quarterly records show as monthly"))
results.append(ok(set(accounts.public_user(u)) == {"visited", "wishlist", "cadence", "subscribed"},
                  "public_user exposes only safe fields"))

# --- the session window rolls forward on use ---------------------------------
# Shrink the 90 days to 2 seconds so real time can prove it: read the session a
# second in, and it must outlive the original expiry. A fixed window would have
# logged this traveler out mid-trip.
_real_ttl = accounts.SESSION_TTL
accounts.SESSION_TTL = 2
accounts._kv_set("sess:" + sid, email, accounts.SESSION_TTL)
time.sleep(1)
touched = accounts.session_email(sid)          # GETEX: re-stamps to 2s from now
results.append(ok(touched == email, "session reads back while alive"))
time.sleep(1.5)                                 # 2.5s since created: fixed TTL would be dead
results.append(ok(accounts.session_email(sid) == email,
                  "active session outlives its original expiry (window rolled)"))
accounts.SESSION_TTL = _real_ttl
accounts._kv_set("sess:" + sid, email, accounts.SESSION_TTL)

# --- sign out ----------------------------------------------------------------
accounts.end_session(sid)
results.append(ok(accounts.session_email(sid) is None, "sign out kills the session"))
results.append(ok(accounts.get_user(email) is not None, "...but the account/map survives sign out"))

# --- rate limiting -----------------------------------------------------------
SENT.clear()
sent = sum(1 for i in range(9) if accounts.request_link("flood@example.com", "9.9.9.9"))
results.append(ok(sent == accounts.RATE_MAX, f"rate limit caps link requests at {accounts.RATE_MAX} (got {sent})"))
ttl = accounts._redis("TTL", "rl:e:flood@example.com")
results.append(ok(0 < int(ttl) <= accounts.RATE_TTL, "limiter keys always carry a TTL (%s)" % ttl))
# One inbox, many spellings: +tags and Gmail dots share a bucket.
sent = sum(1 for i in range(9) if accounts.request_link("vic.tim+%d@gmail.com" % i, "10.0.0.%d" % i))
results.append(ok(sent == accounts.RATE_MAX, "plus/dot variants of one inbox share its limit (got %d)" % sent))
# IPv6: a whole /64 is one client.
sent = sum(1 for i in range(9) if accounts.request_link("v6-%d@example.com" % i, "2001:db8:1:2::%x" % (i + 1)))
results.append(ok(sent == accounts.RATE_MAX, "an IPv6 /64 shares one IP bucket (got %d)" % sent))
results.append(ok(accounts._ip_bucket("::ffff:1.2.3.4") == "1.2.3.4", "IPv4-mapped IPv6 buckets as IPv4"))
# Global daily cap protects the Resend quota.
day_key = "rl:day:" + time.strftime("%Y%m%d", time.gmtime())
already = int(accounts._redis("GET", day_key) or 0)
os.environ["MAIL_DAILY_CAP"] = str(already + 2)
sent = sum(1 for i in range(5) if accounts.request_link("cap%d@example.com" % i, "172.16.0.%d" % i))
results.append(ok(sent == 2, "daily mail cap stops sends past the cap (got %d)" % sent))
os.environ.pop("MAIL_DAILY_CAP")
accounts._redis("DEL", day_key)

# --- HTTP: the magic link, and who may ask for one ----------------------------
import server
from http.server import ThreadingHTTPServer
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
SITE = "https://wandergrade.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http(method, path, body=None, headers=None):
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with _opener.open(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


tok = "t" * 20 + "abcDEF_-123"
accounts._kv_set("magic:" + tok, "http@example.com", accounts.MAGIC_TTL)
st, hd, bd = http("GET", "/auth/verify?t=" + tok)
results.append(ok(st == 200 and b'method="post"' in bd and tok.encode() in bd
                  and "no-store" in hd.get("Cache-Control", "") and b"noindex" in bd,
                  "GET of the link serves a no-store, noindex confirm page"))
st, hd, bd = http("HEAD", "/auth/verify?t=" + tok)
results.append(ok(st == 200 and accounts._kv_get("magic:" + tok) == "http@example.com",
                  "GET/HEAD (mail scanners) leave the token unspent"))
st, hd, bd = http("GET", "/auth/verify?t=%22%3E%3Cscript%3E")
results.append(ok(st == 303 and hd.get("Location") == "/?signin=expired",
                  "malformed token -> expired, never echoed into the page"))
form = ("t=" + tok).encode()
st, hd, bd = http("POST", "/auth/verify", form, {"Content-Type": "application/x-www-form-urlencoded",
                                                  "Origin": "https://evil.example"})
results.append(ok(st == 403 and accounts._kv_get("magic:" + tok) == "http@example.com",
                  "cross-site POST refused (login CSRF), token kept"))
st, hd, bd = http("POST", "/auth/verify", form, {"Content-Type": "application/x-www-form-urlencoded",
                                                  "Sec-Fetch-Site": "cross-site"})
results.append(ok(st == 403, "Sec-Fetch-Site: cross-site refused"))
st, hd, bd = http("POST", "/auth/verify", form, {"Content-Type": "application/x-www-form-urlencoded",
                                                  "Origin": SITE, "Sec-Fetch-Site": "same-origin"})
results.append(ok(st == 303 and hd.get("Location") == "/?signin=ok" and "wg_sess=" in hd.get("Set-Cookie", "")
                  and accounts._kv_get("magic:" + tok) is None,
                  "same-origin POST redeems the token and sets the session"))
st, hd, bd = http("POST", "/auth/verify", form, {"Content-Type": "application/x-www-form-urlencoded",
                                                  "Origin": SITE})
results.append(ok(st == 303 and hd.get("Location") == "/?signin=expired", "second POST: token already spent"))

jreq = json.dumps({"email": "csrf@example.com"}).encode()
SENT.clear()
st, _, _ = http("POST", "/api/auth/request", jreq, {"Content-Type": "text/plain", "Origin": SITE})
results.append(ok(st == 403, "link request with a text/plain body (CORS simple request) refused"))
st, _, _ = http("POST", "/api/auth/request", jreq, {"Content-Type": "application/json",
                                                     "Origin": "https://evil.example"})
results.append(ok(st == 403, "link request from another origin refused"))
st, _, _ = http("POST", "/api/auth/request", jreq, {"Content-Type": "application/json"})
results.append(ok(st == 403 and SENT == [], "link request with no Origin/Sec-Fetch-Site refused"))
st, _, bd = http("POST", "/api/auth/request", jreq, {"Content-Type": "application/json; charset=utf-8",
                                                      "Origin": SITE, "Sec-Fetch-Site": "same-origin",
                                                      "Host": "evil.example"})
results.append(ok(st == 200 and json.loads(bd) == {"sent": True} and len(SENT) == 1
                  and "https://wandergrade.com/auth/verify" in SENT[-1][1],
                  "the site's own request is accepted, and a forged Host doesn't steer the link"))
big = b"[" + b"[]," * 20000 + b"[]]"
st, _, _ = http("POST", "/api/auth/logout", big, {"Content-Type": "application/json"})
results.append(ok(st == 401, "anonymous POST is refused before its body is read"))
st, _, _ = http("POST", "/api/auth/request", big, {"Content-Type": "application/json", "Origin": SITE})
results.append(ok(st == 413, "oversized body refused unread (413)"))
httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
