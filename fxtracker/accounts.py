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
Mail: Resend (REST).

Env:
    UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN   -> storage
    RESEND_API_KEY                                     -> sending
    MAIL_FROM        (default "WanderGrade <hello@send.wandergrade.com>")
    MAIL_REPLY_TO    (default "hello@wandergrade.com")
    SITE_ORIGIN      (default "https://wandergrade.com") — magic-link base

Mail domains are deliberately split: Resend is verified on send.wandergrade.com
because the apex SPF belongs to Cloudflare Email Routing (~all) and would
soft-fail anything Resend sent as @wandergrade.com. Replies are pointed back at
the apex, which Email Routing forwards to a real inbox.
"""

import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

MAGIC_TTL = 15 * 60          # a link is good for 15 minutes
SESSION_TTL = 90 * 24 * 3600  # then you sign in again
RATE_MAX = 5                  # link requests per bucket per hour
RATE_TTL = 3600
CADENCES = ("monthly", "quarterly", "off")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def enabled():
    """True when both storage and mail are configured; the UI hides otherwise."""
    return bool(_env("UPSTASH_REDIS_REST_URL") and _env("UPSTASH_REDIS_REST_TOKEN")
                and _env("RESEND_API_KEY"))


def valid_email(email):
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def norm_email(email):
    return (email or "").strip().lower()


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
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8")).get("result")


def _kv_get(key):
    return _redis("GET", key)


def _kv_set(key, value, ttl=None):
    return _redis("SET", key, value, "EX", ttl) if ttl else _redis("SET", key, value)


def _kv_del(key):
    return _redis("DEL", key)


def _rate_ok(bucket):
    """Allow at most RATE_MAX magic-link requests per bucket per hour."""
    key = "rl:" + bucket
    try:
        n = _redis("INCR", key)
        if n == 1:
            _redis("EXPIRE", key, RATE_TTL)
        return int(n) <= RATE_MAX
    except Exception:
        return True          # never lock people out because the limiter broke


# ---- mail (Resend over REST) ------------------------------------------------

def _send_mail(to, subject, html):
    # Sends from the send.* subdomain on purpose: the apex SPF belongs to
    # Cloudflare Email Routing (~all), so sending as @wandergrade.com would
    # soft-fail and land sign-in links in spam. Replies still go to the real
    # apex inbox, which Email Routing forwards.
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({
            "from": _env("MAIL_FROM", "WanderGrade <hello@send.wandergrade.com>"),
            "to": [to],
            "reply_to": _env("MAIL_REPLY_TO", "hello@wandergrade.com"),
            "subject": subject,
            "html": html,
        }).encode("utf-8"),
        headers={"Authorization": "Bearer " + _env("RESEND_API_KEY"),
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
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
            "subscribed": False, "created": int(time.time()), "updated": int(time.time())}


# ---- the flow ---------------------------------------------------------------

def request_link(email, origin, ip=""):
    """Mail a one-time sign-in link. Returns True when accepted.

    Callers should report success even on failure: telling a stranger whether
    an address is registered (or rate-limited) is an enumeration leak.
    """
    email = norm_email(email)
    if not valid_email(email):
        return False
    if not _rate_ok("e:" + email) or (ip and not _rate_ok("i:" + ip)):
        return False
    token = secrets.token_urlsafe(32)
    _kv_set("magic:" + token, email, MAGIC_TTL)
    base = (origin or _env("SITE_ORIGIN", "https://wandergrade.com")).rstrip("/")
    link = base + "/auth/verify?t=" + urllib.parse.quote(token)
    return _send_mail(email, "Sign in to WanderGrade", _magic_email_html(link))


def consume_token(token):
    """Redeem a magic token exactly once -> (email, session_id) or (None, None)."""
    if not token:
        return None, None
    email = _kv_get("magic:" + token)
    if not email:
        return None, None
    _kv_del("magic:" + token)                 # single use
    if not get_user(email):
        save_user(email, _blank_user())       # first sign-in creates the account
    sid = secrets.token_urlsafe(32)
    _kv_set("sess:" + sid, email, SESSION_TTL)
    return email, sid


def session_email(sid):
    return _kv_get("sess:" + sid) if sid else None


def end_session(sid):
    if sid:
        _kv_del("sess:" + sid)


def _clean_isos(seq):
    """Keep only plausible place codes, capped — never trust the client."""
    out = []
    for x in (seq or [])[:400]:
        if isinstance(x, str) and re.fullmatch(r"[A-Z]{2}(-[A-Z]{3})?", x):
            out.append(x)
    return sorted(set(out))


def sync_map(email, visited, wishlist):
    user = get_user(email) or _blank_user()
    user["visited"] = _clean_isos(visited)
    user["wishlist"] = _clean_isos(wishlist)
    return save_user(email, user)


def set_prefs(email, subscribed=None, cadence=None):
    user = get_user(email) or _blank_user()
    if subscribed is not None:
        user["subscribed"] = bool(subscribed)
    if cadence in CADENCES:
        user["cadence"] = cadence
    save_user(email, user)
    _sync_newsletter(email, user)
    return user


def public_user(user):
    """Only what the browser needs — never the raw record."""
    return {
        "visited": user.get("visited", []),
        "wishlist": user.get("wishlist", []),
        "cadence": user.get("cadence", "monthly"),
        "subscribed": bool(user.get("subscribed")),
    }


# ---- newsletter (Buttondown) ------------------------------------------------

def _sync_newsletter(email, user):
    """Mirror the subscribe choice + cadence into Buttondown as a tag.

    Cadence is per-subscriber here, so send_digest can pick recipients by tag
    (monthly every month; quarterly only in Jan/Apr/Jul/Oct). Best-effort: a
    newsletter hiccup must never break sign-in.
    """
    key = _env("BUTTONDOWN_API_KEY")
    if not key:
        return
    hdrs = {"Authorization": "Token " + key, "Content-Type": "application/json"}
    try:
        if user.get("subscribed") and user.get("cadence") != "off":
            body = json.dumps({"email_address": email,
                               "tags": ["cadence-" + user.get("cadence", "monthly")]}).encode()
            req = urllib.request.Request("https://api.buttondown.email/v1/subscribers",
                                         data=body, headers=hdrs, method="POST")
            urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code != 400:                      # 400 = already subscribed; fine
            pass
    except Exception:
        pass
