"""Passwordless accounts: email magic-link sign-in + cloud-synced travel map.

Why this exists: the Wander List lives in localStorage, which private-browsing
tabs throw away. An account lets a map survive private tabs and follow the
traveler across devices.

Design constraints this respects:
  * No third-party Python packages — both backends are plain HTTPS APIs called
    with urllib, so the stdlib-only deploy stays intact.
  * No passwords, ever. A one-time link proves control of the inbox; that's the
    whole credential. Nothing to leak, reset, or breach.
  * Fully OFF unless configured. Like CF_ANALYTICS_TOKEN, the feature reports
    itself disabled when the env vars are missing, so dev and self-hosting
    stay accountless.

Storage: Upstash Redis (REST). Keys, all short-lived except the user record:
    magic:<token> -> email          TTL 15 min, single use (deleted on verify)
    sess:<sid>    -> email          TTL 90 days
    user:<email>  -> JSON blob      no TTL: {visited, wishlist, cadence,
                                             subscribed, created, updated}
    rl:<bucket>   -> counter        TTL 1 h, throttles link requests
    rl:day:<date> -> counter        TTL 2 days, caps links mailed per UTC day
    migr:bd-optouts:{done,lock}     one-off Buttondown reconciliation (below)
Mail: Resend (REST).

Env:
    UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN   -> storage
    RESEND_API_KEY                                     -> sending
    MAIL_FROM        (default "WanderGrade <signin@wandergrade.com>")
    MAIL_REPLY_TO    (default "hello@wandergrade.com")
    SITE_ORIGIN      (default "https://wandergrade.com") — magic-link base, and
                     the only Origin allowed to request or redeem a link
    MAIL_DAILY_CAP   (default 80) — sign-in mails per UTC day, all addresses

Mail setup (since 2026-07-22): the ROOT domain wandergrade.com is the one
verified Resend domain (the free plan allows exactly one; it used to be the
send. subdomain). From-addresses are @wandergrade.com, DKIM-signed
d=wandergrade.com. SPF is evaluated against Resend's return-path
(send.wandergrade.com, SES include) — not the apex — so the apex SPF/MX can
keep belonging to Cloudflare Email Routing for inbound; both DKIM and SPF
align for DMARC (p=quarantine). The same domain backs Gmail's send-as for
hello@wandergrade.com via Resend SMTP. Replies go to the apex, which Email
Routing forwards to a real inbox.

NOTE: Resend API keys are domain-scoped at creation and cannot be re-scoped —
if the verified domain ever changes again, the production key dies with it
and a new one must be minted and set on Render (learned the hard way).
"""

import ipaddress
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import rates  # reuse the project's verifying SSL context (see _ssl_context)
from . import digest_variants
from .digest_variants import TAG_PREFIX, VARIANTS

MAGIC_TTL = 15 * 60          # a link is good for 15 minutes
SESSION_TTL = 90 * 24 * 3600  # then you sign in again
RATE_MAX = 5                  # link requests per bucket per hour
RATE_TTL = 3600
# Resend's free plan stops at 100 mails/day (3,000/month) for the whole
# account, and hello@'s Gmail send-as rides the same quota. Past this many
# sign-in links in a UTC day, further requests are dropped so a flood can't
# silently take real sign-ins (and the owner's own mail) down with it.
DAILY_MAIL_CAP = 80
# The digest is monthly only. "quarterly" is a retired choice that older
# records and cached pages may still send; it reads as monthly.
CADENCES = ("monthly", "off")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

# Identify ourselves on every outbound call. Both APIs sit behind Cloudflare,
# whose Browser Integrity Check answers urllib's default "Python-urllib/3.x"
# with 403 "error code: 1010" — a ban on the User-Agent, not on the credentials.
_UA = "Wandergrade/1.0 (+https://wandergrade.com)"


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def storage_configured():
    """True when Upstash is configured. Also what health.py (the refreshed
    /health.json) and advhistory.py (the advisory-level record) check to
    store there rather than in memory."""
    return bool(_env("UPSTASH_REDIS_REST_URL") and _env("UPSTASH_REDIS_REST_TOKEN"))


def enabled():
    """True when both storage and mail are configured; the UI hides otherwise."""
    return storage_configured() and bool(_env("RESEND_API_KEY"))


def valid_email(email):
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def norm_email(email):
    return (email or "").strip().lower()


def site_origin():
    """The public origin: magic links point here, and only pages served from
    here may request or redeem one. Never derived from the request's Host."""
    return _env("SITE_ORIGIN", "https://wandergrade.com").rstrip("/")


def _mailbox(email):
    """One throttle bucket per real inbox: a+1@x and a+2@x (and, on Gmail,
    a.b@ vs ab@) are different strings that land in the same mailbox, so
    keying the limit on the raw address let one inbox be flooded anyway."""
    local, _, domain = email.partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return local + "@" + domain


def _ip_bucket(ip):
    """IPv6 clients get a whole /64 each, so per-address limits would be
    free to dodge; bucket them by /64. IPv4 stays per address."""
    ip = (ip or "").strip()
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip[:64]
    if addr.version == 4:
        return str(addr)
    if addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network(str(addr) + "/64", strict=False).network_address) + "/64"


# ---- Upstash Redis over REST ------------------------------------------------
# Commands are sent as a JSON array, e.g. ["SET","k","v","EX","900"].

def _redis(*cmd):
    base = _env("UPSTASH_REDIS_REST_URL").rstrip("/")
    token = _env("UPSTASH_REDIS_REST_TOKEN")
    if not base or not token:
        raise RuntimeError("storage not configured")
    req = urllib.request.Request(
        base,
        data=json.dumps([str(c) for c in cmd]).encode("utf-8"),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 "User-Agent": _UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10, context=rates._SSL) as r:
        return json.loads(r.read().decode("utf-8")).get("result")


def _kv_get(key):
    return _redis("GET", key)


def _kv_set(key, value, ttl=None):
    return _redis("SET", key, value, "EX", ttl) if ttl else _redis("SET", key, value)


def _kv_del(key):
    return _redis("DEL", key)


def _count(key, ttl):
    """Increment a counter that is guaranteed to expire. The key is created
    WITH its TTL (SET NX EX) before the INCR, so a failed follow-up call can
    no longer leave a TTL-less counter that locks a bucket out for good."""
    _redis("SET", key, 0, "EX", ttl, "NX")
    n = int(_redis("INCR", key))
    if n == 1:                     # expired in between: INCR made a bare key
        _redis("EXPIRE", key, ttl)
    return n


def _rate_ok(bucket):
    """Allow at most RATE_MAX magic-link requests per bucket per hour."""
    try:
        return _count("rl:" + bucket, RATE_TTL) <= RATE_MAX
    except Exception:
        return True          # never lock people out because the limiter broke


def _daily_cap_ok():
    try:
        cap = int(_env("MAIL_DAILY_CAP") or DAILY_MAIL_CAP)
    except ValueError:
        cap = DAILY_MAIL_CAP
    day = time.strftime("%Y%m%d", time.gmtime())
    try:
        n = _count("rl:day:" + day, 2 * 86400)
    except Exception:
        return True          # same fail-open rule as the per-bucket limiter
    if n > cap:
        if n == cap + 1:      # say it once, not on every dropped request
            print("[accounts] DAILY MAIL CAP HIT (%d); dropping sign-in mail until 00:00 UTC"
                  % cap, flush=True)
        return False
    return True


# ---- mail (Resend over REST) ------------------------------------------------

def _send_mail(to, subject, html):
    # Sends from the send.* subdomain on purpose: the apex SPF belongs to
    # Cloudflare Email Routing (~all), so sending as @wandergrade.com would
    # soft-fail and land sign-in links in spam. Replies still go to the real
    # apex inbox, which Email Routing forwards.
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({
            "from": _env("MAIL_FROM", "WanderGrade <signin@wandergrade.com>"),
            "to": [to],
            "reply_to": _env("MAIL_REPLY_TO", "hello@wandergrade.com"),
            "subject": subject,
            "html": html,
        }).encode("utf-8"),
        headers={"Authorization": "Bearer " + _env("RESEND_API_KEY"),
                 "Content-Type": "application/json",
                 "User-Agent": _UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=rates._SSL) as r:
            return r.status in (200, 201)
    except urllib.error.HTTPError as e:
        # Surface Resend's own explanation ("domain not verified", bad from
        # address, ...). The caller reports success to the browser regardless —
        # never leak whether an address exists — so this is the only place the
        # real reason can be seen.
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise RuntimeError("resend HTTP %s: %s" % (e.code, detail)) from None


def _magic_email_html(link):
    return f"""<!doctype html><html><body style="margin:0;background:#0b0f14;
  font-family:-apple-system,'Segoe UI',Arial,sans-serif;color:#e6edf5">
  <div style="max-width:520px;margin:0 auto;padding:40px 28px">
    <p style="font-size:15px;font-weight:800;letter-spacing:3px;color:#34d27b;margin:0 0 28px">
      🌍 WANDERGRADE</p>
    <h1 style="font-size:26px;margin:0 0 12px;color:#fff">Sign in to your travel map</h1>
    <p style="font-size:15px;line-height:1.6;color:#9fb3cd;margin:0 0 28px">
      Tap the button to sign in. It works once and expires in 15 minutes.</p>
    <a href="{link}" style="display:inline-block;background:#34d27b;color:#04120a;
      text-decoration:none;font-weight:800;font-size:16px;padding:14px 30px;border-radius:10px">
      Sign in →</a>
    <p style="font-size:13px;line-height:1.6;color:#7d8ea3;margin:32px 0 0">
      If you didn't request this, ignore it — nothing happens without this link.</p>
  </div></body></html>"""


# ---- users ------------------------------------------------------------------

def get_user(email):
    raw = _kv_get("user:" + email)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def save_user(email, data):
    data["updated"] = int(time.time())
    _kv_set("user:" + email, json.dumps(data))
    return data


def _blank_user():
    return {"visited": [], "wishlist": [], "cadence": "monthly",
            "subscribed": False, "currency": None,
            "created": int(time.time()), "updated": int(time.time())}


# ---- the flow ---------------------------------------------------------------

def request_link(email, ip=""):
    """Mail a one-time sign-in link. Returns True when accepted.

    Callers should report success even on failure: telling a stranger whether
    an address is registered (or rate-limited) is an enumeration leak.

    The link is always built on site_origin(), never the request's Host: a
    proxy that forwarded a forged Host would otherwise mail a victim a link to
    the attacker's server, which is an account takeover.
    """
    email = norm_email(email)
    if not valid_email(email):
        return False
    if not _rate_ok("e:" + _mailbox(email)) or (ip and not _rate_ok("i:" + _ip_bucket(ip))):
        return False
    # Last, so throttled requests don't eat the day's allowance.
    if not _daily_cap_ok():
        return False
    token = secrets.token_urlsafe(32)
    _kv_set("magic:" + token, email, MAGIC_TTL)
    link = site_origin() + "/auth/verify?t=" + urllib.parse.quote(token)
    return _send_mail(email, "Sign in to WanderGrade", _magic_email_html(link))


def consume_token(token):
    """Redeem a magic token exactly once -> (email, session_id) or (None, None)."""
    if not token:
        return None, None
    # GETDEL, not GET then DEL: two racing redemptions must not both win.
    email = _redis("GETDEL", "magic:" + token)
    if not email:
        return None, None
    if not get_user(email):
        save_user(email, _blank_user())       # first sign-in creates the account
    sid = secrets.token_urlsafe(32)
    _kv_set("sess:" + sid, email, SESSION_TTL)
    return email, sid


def session_email(sid):
    """Read a session and roll its window forward in the same breath.

    GETEX fetches the value and re-stamps the TTL atomically, so keeping a
    traveler signed in costs no extra round trip. The 90 days therefore run
    from the last visit, not from sign-in: plan a trip every few months and
    you never see another magic link, while a genuinely dormant session still
    ages out. server.py re-sends the cookie so its Max-Age tracks this.
    """
    return _redis("GETEX", "sess:" + sid, "EX", SESSION_TTL) if sid else None


def end_session(sid):
    if sid:
        _kv_del("sess:" + sid)


def _clean_isos(seq):
    """Keep only plausible place codes, capped — never trust the client."""
    out = []
    for x in (seq if isinstance(seq, list) else [])[:400]:
        if isinstance(x, str) and re.fullmatch(r"[A-Z]{2}(-[A-Z]{3})?", x):
            out.append(x)
    return sorted(set(out))


def sync_map(email, visited, wishlist):
    user = get_user(email) or _blank_user()
    user["visited"] = _clean_isos(visited)
    user["wishlist"] = _clean_isos(wishlist)
    return save_user(email, user)


def _cadence(value):
    """Stored/requested cadence -> "monthly" or "off" (legacy "quarterly" and
    anything unknown read as monthly)."""
    return "off" if value == "off" else "monthly"


def _wants_mail(user):
    return bool(user.get("subscribed")) and _cadence(user.get("cadence")) != "off"


def _pickable():
    """The currencies an account may choose: the subscribe picker's, i.e. the
    digest's "send"-stage editions (read at call time, so a ROLLOUT commit
    needs no other change). With USD alone there is no choice to store."""
    codes = digest_variants.picker_codes()
    return codes if len(codes) > 1 else ()


def _currency(value):
    """A requested newsletter currency -> its code if readers can pick it right
    now, else None. Any of the ten used to be accepted: in the shipping
    USD-only state set_prefs(currency="CNY") wrote a currency-cny tag, which
    creates that tag in Buttondown and files the reader under an edition that
    isn't sent."""
    c = value.strip().upper() if isinstance(value, str) else None
    return c if c in _pickable() else None


def set_prefs(email, subscribed=None, cadence=None, currency=None):
    user = get_user(email) or _blank_user()
    was = _wants_mail(user)
    if subscribed is not None:
        user["subscribed"] = bool(subscribed)
    if cadence in CADENCES or cadence == "quarterly":
        user["cadence"] = _cadence(cadence)
    code = _currency(currency)
    prev = user.get("currency")
    changed = code is not None and code != prev
    if code is not None:
        user["currency"] = code
    save_user(email, user)
    # A currency-only change re-tags without the subscribe upsert, so picking
    # a currency never spends the list's daily subscriber-create allowance.
    touch_list = subscribed is not None or cadence is not None
    retag = changed or (touch_list and bool(user.get("currency")))
    tagged = _sync_newsletter(email, user, was, post=touch_list, retag=retag, picked=changed)
    if changed and tagged == "failed":
        # Reconcile: Buttondown still holds the old currency tag (its lookup
        # or the write failed twice), so the account goes back to the old
        # choice as well, and the panel snaps back to it. Keeping the new one
        # showed GBP in the account while the reader kept getting EUR, and
        # picking GBP again was impossible: it was already the selected value.
        cur = get_user(email) or user
        if cur.get("currency") == code:      # unless a later request moved it on
            cur["currency"] = prev
            save_user(email, cur)
        user = cur
    return user


def public_user(user):
    """Only what the browser needs — never the raw record."""
    return {
        "visited": user.get("visited", []),
        "wishlist": user.get("wishlist", []),
        "cadence": _cadence(user.get("cadence", "monthly")),
        "subscribed": bool(user.get("subscribed")),
        "currency": user.get("currency"),
    }


# ---- newsletter (Buttondown) ------------------------------------------------

_BD_API = "https://api.buttondown.email/v1/subscribers"


def _buttondown(method, url, key, payload=None, extra=None):
    """One Buttondown call -> HTTP status. Never raises for HTTP errors; the
    body of a non-2xx is logged, since that is the only place it shows."""
    hdrs = {"Authorization": "Token " + key, "Content-Type": "application/json",
            "User-Agent": _UA}
    hdrs.update(extra or {})
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10, context=rates._SSL) as r:
            return r.status
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        if e.code != 404:
            print("[accounts] buttondown %s -> HTTP %s: %s" % (method, e.code, detail),
                  flush=True)
        return e.code


def _sync_newsletter(email, user, was_subscribed=False, post=True, retag=False, picked=False):
    """Mirror the account's newsletter choice into Buttondown.

    The digest goes to the whole Buttondown list every month, so the list IS
    the preference: subscribing adds (or re-activates) the address; opting
    out marks it unsubscribed there, or the next issue would still arrive.
    Only a change away from subscribed unsubscribes — an account that never
    opted in here may still be on the list through the site's public form,
    and not ticking a box at sign-in is not an opt-out of that. Nothing but
    set_prefs (the /api/auth/prefs call) reaches this: signing in, the map
    sync and signing out never touch the list, and the sign-in form sends
    prefs only when its box is ticked, so the account panel is the one place
    an opt-out comes from.

    The newsletter's home currency (the digest edition they get) rides on a
    currency-* tag: `retag` sets it to the stored one, replacing any other
    currency tag, after the upsert (`post`) when there is one. A stored
    currency that has since been switched off (digest_variants.ROLLOUT) is
    left alone: Buttondown keeps whatever tag it has, and its reader gets USD
    until the edition returns.

    `picked` (the currency was just changed) also reaches an address that is
    on the list through the public form while this account isn't opted in:
    picking here is the only way such a reader can switch editions, because
    a second form subscribe ADDS a tag instead of swapping it (Buttondown's
    docs), and the earliest edition in SEND_ORDER wins. It re-tags an
    existing regular or unactivated subscriber and nothing else: never the
    subscribe call (that would be an opt-in nobody gave), never an
    unsubscribed address, and nothing at all when the address isn't there.

    Returns the currency tag's outcome ("ok", "absent", "failed") when one
    was attempted, else None. Best-effort: a newsletter hiccup must never
    break sign-in or the prefs save, so failures are logged, not raised.
    """
    key = _env("BUTTONDOWN_API_KEY")
    if not key:
        return None
    tagging = False
    try:
        if _wants_mail(user):
            if post:
                # "add" upserts: creates a new subscriber, merges the tag into
                # an existing one, and re-activates an address that
                # unsubscribed earlier — this is that person explicitly
                # opting back in.
                _buttondown("POST", _BD_API, key,
                            {"email_address": email, "tags": ["cadence-monthly"]},
                            {"X-Buttondown-Collision-Behavior": "add"})
            if retag and user.get("currency") in _pickable():
                tagging = True
                return _set_currency_tag(email, key, user["currency"])
        elif was_subscribed:
            _buttondown("PATCH", _BD_API + "/" + urllib.parse.quote(email, safe="@"), key,
                        {"type": "unsubscribed"})
        elif picked and user.get("currency") in _pickable():
            tagging = True
            return _set_currency_tag(email, key, user["currency"], only=("regular", "unactivated"))
    except Exception as e:
        print("[accounts] buttondown sync failed: %s" % e, flush=True)
        return "failed" if tagging else None
    return None


TAG_RETRY_PAUSE = 1.0                    # seconds before the one retry
_TRANSIENT = (None, 429, 500, 502, 503, 504)   # None: no HTTP answer at all


def _set_currency_tag(email, key, code, only=None):
    """Make the stored currency's tag the subscriber's only currency-* tag.
    PATCH replaces the tag list, so it sends the current tags minus other
    currency tags (any case) plus this one: cadence-monthly and anything the
    owner added stay. No PATCH when nothing would change.

    The currency written is the account's stored one, re-read just before
    the write, not `code` (what this request saved): two quick picks run on
    two server threads, each reading the tags and then writing them, and
    whichever wrote last used to win — the tag could end up on the first
    pick while the account showed the second. Re-reading makes both writes
    agree with the account. A transient failure (no answer, 429, 5xx) is
    retried once after TAG_RETRY_PAUSE.

    `only`: subscriber types that may be re-tagged (others count as absent).
    Returns "ok" (the tag is right), "absent" (no such subscriber, or not of
    a type in `only`), or "failed"."""
    sub = None
    for attempt in (0, 1):
        try:
            status, sub = _bd_subscriber(email, key)
        except Exception:
            status, sub = None, None
        if status == 200 and isinstance(sub, dict):
            break
        if status == 404:
            return "absent"
        if attempt == 0 and status in _TRANSIENT:
            time.sleep(TAG_RETRY_PAUSE)
            continue
        print("[accounts] currency tag: lookup of %s -> HTTP %s" % (_mask(email), status), flush=True)
        return "failed"
    if only is not None and sub.get("type") not in only:
        return "absent"
    fresh = (get_user(email) or {}).get("currency")
    if fresh in _pickable():
        code = fresh
    tags = list(sub.get("tags") or [])
    want = [t for t in tags if not (isinstance(t, str) and t.lower().startswith(TAG_PREFIX))]
    want.append(VARIANTS[code].tag)
    if sorted(map(str, want)) == sorted(map(str, tags)):
        return "ok"
    for attempt in (0, 1):
        try:
            status = _buttondown("PATCH", _BD_API + "/" + urllib.parse.quote(email, safe="@"), key,
                                 {"tags": want})
        except Exception:
            status = None
        if status in (200, 201, 202, 204):
            return "ok"
        if attempt == 0 and status in _TRANSIENT:
            time.sleep(TAG_RETRY_PAUSE)
            continue
        print("[accounts] currency tag: update of %s -> HTTP %s" % (_mask(email), status), flush=True)
        return "failed"
    return "failed"


# ---- one-off: opt-outs from before they reached Buttondown -------------------
# Until 2026-09 an account's "No emails" only flipped the stored flag, so an
# account that opted out stayed on the Buttondown list and still got every
# issue. reconcile_optouts() walks the stored accounts once after deploy and
# unsubscribes those addresses — but only subscribers the account flow itself
# created, which carry its cadence-* tag. The public form adds no cadence-*
# tag (only, once the currency picker is on, a currency-* one, which this
# pass ignores), and the old account code never tagged an address that was
# already on the list, so an address that joined through the form is never
# touched: the account never had a say over its subscription. Safe to re-run:
# an address already unsubscribed is skipped.
RECONCILE_DONE = "migr:bd-optouts:done"   # set after a clean pass; never expires
RECONCILE_LOCK = "migr:bd-optouts:lock"
RECONCILE_LOCK_TTL = 3600
RECONCILE_PAUSE = 1.0    # seconds after each Buttondown call: far under its rate limit
RECONCILE_SCAN = 200     # keys per SCAN page


def _mask(email):
    """a***@example.com: enough to follow a log line, not to harvest one."""
    local, _, domain = email.partition("@")
    return local[:1] + "***@" + domain


def _bd_subscriber(email, key):
    """(HTTP status, subscriber dict or None) for one address in Buttondown."""
    req = urllib.request.Request(
        _BD_API + "/" + urllib.parse.quote(email, safe="@"),
        headers={"Authorization": "Token " + key, "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=10, context=rates._SSL) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, None


def reconcile_optouts(delay=60, pause=RECONCILE_PAUSE, backoff=60, tries=3,
                      retry_wait=RECONCILE_LOCK_TTL):
    """Unsubscribe, in Buttondown, accounts that opted out before opt-outs
    reached it. Runs on a background thread at server start; a no-op without
    the Buttondown and Upstash keys, once a clean pass has set RECONCILE_DONE,
    or while another instance (a deploy overlap) holds the lock. A pass with
    any error sets no marker and is tried again `retry_wait` seconds later, up
    to `tries` passes, then at the next start: waiting for a redeploy could
    let the next issue reach the very people this is for. Returns the last
    pass's stats, or None when it didn't run."""
    key = _env("BUTTONDOWN_API_KEY")
    if not storage_configured():
        return None
    if not key:
        # Accounts are on but the list is out of reach: say so, since opt-outs
        # (here and in the account panel) silently can't reach Buttondown.
        print("[accounts] BUTTONDOWN_API_KEY not set: opt-outs can't reach the newsletter "
              "list; reconciliation skipped", flush=True)
        return None
    time.sleep(delay)        # let a cold start answer its first visitors first
    stats = None
    for attempt in range(tries):
        if attempt:
            time.sleep(retry_wait)
        stats = _reconcile_pass(key, pause, backoff)
        if not stats or not stats["errors"]:
            break
    return stats


def _reconcile_pass(key, pause, backoff):
    """One walk over the stored accounts -> stats, or None when already done.
    A held lock returns stats with errors=1 and locked=True, so the caller
    retries after the lock's TTL instead of giving up for the process's life."""
    stats = {"accounts": 0, "looked_up": 0, "unsubscribed": 0, "errors": 0}
    try:
        if _kv_get(RECONCILE_DONE):
            return None
        if not _redis("SET", RECONCILE_LOCK, int(time.time()), "EX", RECONCILE_LOCK_TTL, "NX"):
            # Held — by a live instance, or by one killed mid-pass (a deploy
            # overlap) whose lock outlives it. Not "done": come back after the
            # lock's TTL; the done-marker keeps a finished pass from repeating.
            return dict(stats, errors=1, locked=True)
    except Exception as e:           # a storage blip is retried like any other error
        print("[accounts] reconcile: storage unavailable (%s); will retry" % e, flush=True)
        return dict(stats, errors=1)
    print("[accounts] reconcile: checking opted-out accounts against Buttondown", flush=True)
    try:
        cursor = "0"
        while True:
            cursor, keys = _redis("SCAN", cursor, "MATCH", "user:*", "COUNT", RECONCILE_SCAN)
            for k in keys or []:
                stats["accounts"] += 1
                email = k[len("user:"):]
                user = get_user(email)
                if not user or _wants_mail(user):
                    continue
                stats["looked_up"] += 1
                status, sub = _bd_subscriber(email, key)
                time.sleep(pause)
                if status == 429:                    # one polite retry, then move on
                    time.sleep(backoff)
                    status, sub = _bd_subscriber(email, key)
                    time.sleep(pause)
                if status == 404:                    # not on the list: nothing to undo
                    continue
                if status != 200 or not isinstance(sub, dict):
                    print("[accounts] reconcile: lookup of %s -> HTTP %s"
                          % (_mask(email), status), flush=True)
                    if status in (401, 403):         # bad key: every call would fail
                        raise RuntimeError("Buttondown refused the API key")
                    stats["errors"] += 1
                    continue
                tags = sub.get("tags") or []
                if sub.get("type") != "regular" or not any(
                        isinstance(t, str) and t.startswith("cadence-") for t in tags):
                    continue
                # Re-read: someone opting back in during the pass wins.
                if _wants_mail(get_user(email) or {}):
                    continue
                code = _buttondown("PATCH", _BD_API + "/" + urllib.parse.quote(email, safe="@"),
                                   key, {"type": "unsubscribed"})
                time.sleep(pause)
                if 200 <= code < 300:
                    stats["unsubscribed"] += 1
                    print("[accounts] reconcile: unsubscribed %s (account had opted out)"
                          % _mask(email), flush=True)
                else:
                    stats["errors"] += 1
            if str(cursor) == "0":
                break
    except Exception as e:
        stats["errors"] += 1
        print("[accounts] reconcile stopped: %s" % e, flush=True)
    try:
        if stats["errors"]:
            print("[accounts] reconcile: %s; not marked done, will retry" % stats, flush=True)
        else:
            _kv_set(RECONCILE_DONE, json.dumps(dict(stats, at=int(time.time()))))
            print("[accounts] reconcile done: %s" % stats, flush=True)
        _kv_del(RECONCILE_LOCK)    # the pass is over either way; a retry may take it
    except Exception as e:
        print("[accounts] reconcile: couldn't record the result (%s)" % e, flush=True)
    return stats
