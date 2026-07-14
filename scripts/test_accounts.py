"""End-to-end exercise of the passwordless accounts flow, with no real
credentials: storage points at scripts/mock_upstash.py and mail is captured
in-process instead of sent, so the magic link can be followed.

    python3 scripts/mock_upstash.py &        # in one shell
    python3 scripts/test_accounts.py         # in another
"""
import os, sys, time

os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:8899"
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock"
os.environ["RESEND_API_KEY"] = "mock"
os.environ.pop("BUTTONDOWN_API_KEY", None)   # don't touch the real newsletter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fxtracker import accounts

SENT = []
accounts._send_mail = lambda to, subject, html: (SENT.append((to, html)), True)[1]

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

print("accounts.enabled():", accounts.enabled())
results.append(ok(accounts.enabled(), "enabled() true when configured"))

# --- request a link ---------------------------------------------------------
results.append(ok(accounts.request_link("Doug@Example.COM ", "https://wandergrade.com", "1.2.3.4"),
                  "request_link accepted"))
to, html = SENT[-1]
results.append(ok(to == "doug@example.com", "email normalised (case/space) -> " + to))
token = html.split("/auth/verify?t=")[1].split('"')[0]
results.append(ok(len(token) > 20, "magic link contains a token"))

# --- bad addresses rejected -------------------------------------------------
results.append(ok(not accounts.request_link("nope", "https://x", "1.2.3.4"), "invalid email rejected"))

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

# --- prefs / cadence ---------------------------------------------------------
u = accounts.set_prefs(email, subscribed=True, cadence="quarterly")
results.append(ok(u["subscribed"] is True and u["cadence"] == "quarterly", "prefs saved (subscribe + quarterly)"))
u = accounts.set_prefs(email, cadence="bogus")
results.append(ok(u["cadence"] == "quarterly", "invalid cadence ignored (kept quarterly)"))
u = accounts.set_prefs(email, subscribed=False, cadence="off")
results.append(ok(u["cadence"] == "off" and u["subscribed"] is False, "unsubscribe -> off"))
results.append(ok(set(accounts.public_user(u)) == {"visited", "wishlist", "cadence", "subscribed"},
                  "public_user exposes only safe fields"))

# --- sign out ----------------------------------------------------------------
accounts.end_session(sid)
results.append(ok(accounts.session_email(sid) is None, "sign out kills the session"))
results.append(ok(accounts.get_user(email) is not None, "...but the account/map survives sign out"))

# --- rate limiting -----------------------------------------------------------
SENT.clear()
sent = sum(1 for i in range(9) if accounts.request_link("flood@example.com", "https://x", "9.9.9.9"))
results.append(ok(sent == accounts.RATE_MAX, f"rate limit caps link requests at {accounts.RATE_MAX} (got {sent})"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
